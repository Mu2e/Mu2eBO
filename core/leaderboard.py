"""Leaderboard: the schema-owning module for per-mode history + pending TSVs.

The ModeSpec declares the row schema; this module ENFORCES it. Every read
checks the physical header against the spec-derived one and fails loudly on
disagreement (never a silent 0-row history — see
wiki/incidents/touched-leaderboard-headerless-history-loss.md). Every append
that hits a mismatched file saves the row to <file>.quarantine.tsv BEFORE
raising, so a finished eval's result is never lost to a schema error.

Stdlib-only, no project imports: everything arrives via the constructor, so
the botorch venv and tests import it with no path games.
Spec: docs/superpowers/specs/2026-08-08-leaderboard-module-design.md
"""
from __future__ import annotations

import csv
import fcntl
import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

STALE_PENDING_S = 48 * 3600.0
PENDING_HEADER = "config\tx\talpha\tsubmitted_at\n"


class LeaderboardError(RuntimeError):
    """Base for all schema/parse failures raised by this module."""


class SchemaMismatch(LeaderboardError):
    def __init__(self, path: Path, expected: str, found: str,
                 quarantined: Path | None = None):
        self.path, self.expected, self.found = path, expected, found
        self.quarantined = quarantined
        saved = (f"\n  row saved to quarantine: {quarantined}"
                 if quarantined else "")
        super().__init__(
            f"{path}: header does not match the ModeSpec schema.\n"
            f"  expected: {expected.rstrip()!r}\n"
            f"  found:    {found.rstrip()!r}{saved}\n"
            f"  Refusing to proceed — a mismatched header means silent "
            f"history loss (GP cold-start) or rows at wrong coordinates.")


class RowParseError(LeaderboardError):
    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path, self.line_no, self.cause = path, line_no, cause
        super().__init__(f"{path}:{line_no}: unparseable row ({cause!r})")


def _lock_path(target: Path) -> Path:
    """Flock anchor for `target`: <target's dir>/locks/<target's name>.lock.

    All runtime lock files live in a dedicated locks/ folder next to the
    thing they guard (relative to the target's parent, NOT a global constant,
    so tests that point a mode's TSVs at a tmp dir keep their lock isolation).
    Lock files are created if absent and intentionally NEVER deleted —
    deleting one while a process holds it would let the next opener lock a
    fresh inode at the same path, silently splitting the mutual exclusion.
    """
    lock_dir = target.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / (target.name + ".lock")


@contextmanager
def _flock_ex(target: Path):
    """Exclusive-lock target's locks/-dir anchor for the duration of the block.

    Used by leaderboard/pending TSV writers when multiple closed-loop child
    processes may append concurrently.
    """
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextmanager
def _flock_sh(target: Path):
    """Shared-lock target's locks/-dir anchor for the duration of the block.

    Paired with _flock_ex on the same path: writers (append_history) hold EX
    and block readers; readers (load_history) hold SH and block only writers,
    not each other. Closes the torn-row race where a reader could observe a
    partially-written leaderboard line mid-append.
    """
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@dataclass
class Point:
    """Generic BO point: x layout depends on mode."""
    cfg: str
    x: list      # mode-specific list of param values
    sob: float
    calo: float
    extras: dict | None = None  # mode-specific side metrics (logged not optimized)

    def obj(self, alpha: float) -> float:
        return self.sob - alpha * self.calo


def to_py_scalars(x) -> list:
    """Coerce numpy scalars (np.int64/np.float64) to native Python types for
    JSON/msgpack. Shared by append_pending and graph/pipeline_io.propose_one —
    see wiki/incidents/langgraph-checkpoint-numpy-int64.md."""
    return [v.item() if hasattr(v, "item") else v for v in x]


@dataclass(frozen=True)
class Leaderboard:
    path: Path
    name: str
    knob_names: tuple
    knob_fmts: tuple
    metric_cols: tuple   # exactly (sob-like, calo-like, "alpha", "obj")
    archive_path: Path | None = None   # committed read-only priors

    def __post_init__(self):
        if len(self.metric_cols) != 4:
            raise ValueError(
                f"{self.name}: metric_cols must be the 4-column tail "
                f"(sob-like, calo-like, alpha, obj); got {self.metric_cols}")
        if len(self.knob_names) != len(self.knob_fmts):
            raise ValueError(
                f"{self.name}: knob_names/knob_fmts length mismatch "
                f"({len(self.knob_names)} vs {len(self.knob_fmts)})")

    @classmethod
    def from_spec(cls, spec, *, live_root: Path,
                  archive_root: Path) -> "Leaderboard":
        """live_root is this operator's flat board directory; archive_root is
        the repo, where the committed priors keep their relative path."""
        rel = Path(spec.leaderboard_rel)
        return cls(path=live_root / rel.name, name=spec.name,
                   knob_names=tuple(spec.knob_names),
                   knob_fmts=tuple(spec.knob_fmts),
                   metric_cols=tuple(spec.metric_cols),
                   archive_path=archive_root / rel)

    # --- history -----------------------------------------------------------
    def header(self) -> str:
        return ("config\t" + "\t".join(self.knob_names)
                + "\t" + "\t".join(self.metric_cols) + "\n")

    def quarantine_path(self) -> Path:
        return self.path.with_name(self.path.name + ".quarantine.tsv")

    def _load_one(self, path: Path) -> list[Point]:
        if not path.exists():
            return []
        out = []
        with _flock_sh(path), path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = ("config", *self.knob_names, *self.metric_cols)
            reader = csv.DictReader(f, fieldnames=cols, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                try:
                    out.append(Point(
                        cfg=row["config"],
                        x=[float(row[c]) for c in self.knob_names],
                        sob=float(row[self.metric_cols[0]]),
                        calo=float(row[self.metric_cols[1]])))
                except (KeyError, ValueError, TypeError) as e:
                    raise RowParseError(path, line_no, e) from e
        return out

    def load(self) -> list[Point]:
        """Committed priors first, then this operator's own rows.

        A config appearing in BOTH is counted once, archive-wins: promoting
        live rows into the committed archive is a manual git commit, so a
        row left behind in the live file would otherwise enter the GP
        training set twice.
        """
        archive = self._load_one(self.archive_path) if self.archive_path else []
        seen = {p.cfg for p in archive}
        live = [p for p in self._load_one(self.path) if p.cfg not in seen]
        return archive + live

    def _format_line(self, p: Point, alpha: float) -> str:
        knobs = "\t".join(
            fmt.format(v) for fmt, v in zip(self.knob_fmts, p.x))
        return (f"{p.cfg}\t{knobs}\t{p.sob:.5f}\t{p.calo:.5e}"
                f"\t{alpha:.3f}\t{p.obj(alpha):.5f}\n")

    def append(self, p: Point, alpha: float) -> None:
        line = self._format_line(p, alpha)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _flock_ex(self.path):
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return
            with self.path.open() as f:
                first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                self._append_quarantine(self.header(), line)
                raise SchemaMismatch(self.path, self.header(), first,
                                     quarantined=self.quarantine_path())
            with self.path.open("a") as f:
                f.write(line)

    def _append_quarantine(self, header: str, line: str) -> None:
        qp = self.quarantine_path()
        new = not qp.exists()
        with qp.open("a") as f:
            if new:
                f.write(header)
            f.write(line)

    # --- pending -----------------------------------------------------------
    def pending_path(self) -> Path:
        return self.path.parent / f"pending_bo_{self.name}.tsv"

    def _pending_quarantine_path(self) -> Path:
        pp = self.pending_path()
        return pp.with_name(pp.name + ".quarantine.tsv")

    def pending_add(self, name: str, x, alpha: float) -> None:
        pp = self.pending_path()
        row = (f"{name}\t{json.dumps(to_py_scalars(x))}"
               f"\t{alpha:.3f}\t{int(time.time())}\n")
        with _flock_ex(pp):
            if not pp.exists():
                pp.write_text(PENDING_HEADER + row)
                return
            with pp.open() as f:
                first = f.readline()
            if first.rstrip("\n") != PENDING_HEADER.rstrip("\n"):
                qp = self._pending_quarantine_path()
                new = not qp.exists()
                with qp.open("a") as f:
                    if new:
                        f.write(PENDING_HEADER)
                    f.write(row)
                raise SchemaMismatch(pp, PENDING_HEADER, first,
                                     quarantined=qp)
            with pp.open("a") as f:
                f.write(row)

    def pending_load(self, *, now: float | None = None) -> list:
        pp = self.pending_path()
        if not pp.exists():
            return []
        now = time.time() if now is None else now
        out, stale = [], []
        with _flock_sh(pp), pp.open() as f:
            first = f.readline()
            if first.rstrip("\n") != PENDING_HEADER.rstrip("\n"):
                raise SchemaMismatch(pp, PENDING_HEADER, first)
            cols = ("config", "x", "alpha", "submitted_at")
            reader = csv.DictReader(f, fieldnames=cols, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                try:
                    name, x = row["config"], json.loads(row["x"])
                    age_s = now - float(row["submitted_at"])
                except (KeyError, ValueError, TypeError,
                        json.JSONDecodeError) as e:
                    raise RowParseError(pp, line_no, e) from e
                out.append((name, x))
                if age_s > STALE_PENDING_S:
                    stale.append((name, age_s / 3600.0))
        if stale:
            rows = "\n".join(f"    {n}  ({h:.0f}h old)" for n, h in stale)
            print(f"[{self.name}] WARNING: {len(stale)} pending row(s) older "
                  f"than {STALE_PENDING_S/3600:.0f}h — likely dead children "
                  f"still repelling the GP as phantom in-flight points:\n"
                  f"{rows}\n  To remove:  ./core/bo_driver.py --mode "
                  f"{self.name} pending-prune", file=sys.stderr)
        return out

    def pending_prune(self, older_than_h: float = 48.0,
                      now: float | None = None) -> list[str]:
        pp = self.pending_path()
        now = time.time() if now is None else now
        with _flock_ex(pp):
            if not pp.exists():
                return []
            lines = pp.read_text().splitlines()
            if not lines:
                return []
            first = lines[0]
            if first != PENDING_HEADER.rstrip("\n"):
                raise SchemaMismatch(pp, PENDING_HEADER, first + "\n")
            kept, removed = [first], []
            for ln in lines[1:]:
                cells = ln.split("\t")
                try:
                    age_h = (now - float(cells[3])) / 3600.0
                except (IndexError, ValueError):
                    kept.append(ln)   # unparseable rows are prune-immune;
                    continue          # pending_load will name them loudly
                if age_h > older_than_h:
                    removed.append(cells[0])
                else:
                    kept.append(ln)
            if removed:
                # same newline invariant as pending_remove
                pp.write_text("\n".join(kept) + "\n")
            return removed

    def pending_remove(self, name: str) -> bool:
        pp = self.pending_path()
        # Read-modify-write under lock: without LOCK_EX two concurrent removals
        # can race and one's truncate overwrites the other's deletion.
        with _flock_ex(pp):
            if not pp.exists():
                return False
            rows = pp.read_text().splitlines()
            if len(rows) < 2:
                return False
            header, body = rows[0], rows[1:]
            kept = [r for r in body if not r.startswith(name + "\t")]
            if len(kept) == len(body):
                return False
            # ALWAYS terminate with a newline, including when `kept` is empty.
            # The old `("\n" if kept else "")` left the header unterminated
            # once the last pending row was removed, and append_pending opens
            # in "a" mode -- so the NEXT proposal was written straight onto the
            # header line ("...submitted_atfoilsflash22R00_00\t[...]"). From
            # then on the file was a single line forever: load_pending()
            # returned 0 rows, silently. That went unnoticed for a long time
            # because nothing depended on reading it back -- Python modes
            # recovered x via parse_geom, and the only other consumers degrade
            # quietly (the propose_one collision guard stops seeing pending
            # names, and botorch_ask gets an empty X_pending so concurrent
            # children no longer repel each other's in-flight points). It
            # became fatal the moment foilsflash went JSON-defined and
            # x_for_evaluate made the pending TSV the ONLY record of x:
            # foilsflash24R00_00 lost a finished 3.5 h eval to it (2026-07-26).
            pp.write_text("\n".join([header] + kept) + "\n")
            return True
