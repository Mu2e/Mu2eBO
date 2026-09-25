"""Leaderboard: the schema-owning module for per-study history + pending TSVs.

Every read checks the physical header against the spec-derived one and fails
loudly (never a silent 0-row history — see
wiki/incidents/touched-leaderboard-headerless-history-loss.md); every append
hitting a mismatch quarantines the row BEFORE raising, so a finished eval is
never lost to a schema error. Stdlib-only, no project imports.
Spec: docs/superpowers/specs/2026-08-08-leaderboard-module-design.md
"""
from __future__ import annotations

import csv
import fcntl
import json
import sys
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

STALE_PENDING_S = 48 * 3600.0
PENDING_HEADER = "config\tx\talpha\tsubmitted_at\n"

# v2 rows end in these columns (generic-study design, "Leaderboard rows").
V2_META = ("handles", "spec_sha", "measure_sha", "time")


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
            f"{path}: header does not match the study's leaderboard schema.\n"
            f"  expected: {expected.rstrip()!r}\n"
            f"  found:    {found.rstrip()!r}{saved}\n"
            f"  Refusing to proceed — a mismatched header means silent "
            f"history loss (GP cold-start) or rows at wrong coordinates.")


class RowParseError(LeaderboardError):
    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path, self.line_no, self.cause = path, line_no, cause
        super().__init__(f"{path}:{line_no}: unparseable row ({cause!r})")


class MeasureMismatch(LeaderboardError):
    def __init__(self, path: Path, found, new: str, quarantined: Path):
        super().__init__(
            f"{path}: this row's measure_sha {new[:12]} differs from the "
            f"board's {sorted(s[:12] for s in found)}.\n"
            f"  row saved to quarantine: {quarantined}\n"
            f"  A board holds one measurement: a changed kit setting, step, "
            f"metric or kit version means a new board (leaderboard.file), "
            f"never mixed rows.")


class DuplicateRow(LeaderboardError):
    def __init__(self, path: Path, name: str, quarantined: Path):
        super().__init__(
            f"{path}: config {name!r} already has a row with different "
            f"values.\n  row saved to quarantine: {quarantined}")


def _lock_path(target: Path) -> Path:
    """Flock anchor for `target`: <target's dir>/locks/<target's name>.lock.

    Lock files are intentionally NEVER deleted — deleting one while a process
    holds it lets the next opener lock a fresh inode at the same path,
    silently splitting the mutual exclusion.
    """
    lock_dir = target.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / (target.name + ".lock")


@contextmanager
def _flock_ex(target: Path):
    """Exclusive-lock target's locks/-dir anchor for the duration of the block."""
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextmanager
def _flock_sh(target: Path):
    """Shared-lock target's locks/-dir anchor: readers block only writers,
    closing the torn-row race where a reader could observe a partially
    written line mid-append."""
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@dataclass
class Point:
    """One evaluated config: knob vector x plus named values y (the study's
    objectives and extra metrics, keyed by name)."""
    cfg: str
    x: list
    y: dict


def to_py_scalars(x) -> list:
    """Coerce numpy scalars to native Python types for JSON/msgpack —
    see wiki/incidents/langgraph-checkpoint-numpy-int64.md."""
    return [v.item() if hasattr(v, "item") else v for v in x]


@dataclass(frozen=True)
class Leaderboard:
    path: Path
    name: str
    knob_names: tuple
    knob_fmts: tuple
    value_names: tuple      # objectives then extra metrics (read back)
    value_fmts: tuple
    extra_columns: tuple    # objects with .name/.fmt/.evaluate(env); never read back
    context_names: tuple    # runtime values append() must receive
    consts: dict            # visible to extra-column expressions
    archive_path: Path | None = None   # committed read-only priors
    layout: str = "v1"                 # "v2" adds the V2_META columns

    def __post_init__(self):
        if len(self.knob_names) != len(self.knob_fmts):
            raise ValueError(
                f"{self.name}: knob_names/knob_fmts length mismatch "
                f"({len(self.knob_names)} vs {len(self.knob_fmts)})")
        if len(self.value_names) != len(self.value_fmts):
            raise ValueError(
                f"{self.name}: value_names/value_fmts length mismatch")

    @classmethod
    def for_study(cls, study, *, path: Path,
                  archive_path: Path | None) -> "Leaderboard":
        values = tuple(study.objectives) + tuple(study.extra_metrics)
        return cls(path=path, name=study.name,
                   knob_names=tuple(study.knob_names),
                   knob_fmts=tuple(study.knob_fmts),
                   value_names=tuple(v.name for v in values),
                   value_fmts=tuple(v.fmt for v in values),
                   extra_columns=tuple(study.extra_columns),
                   context_names=tuple(study.context),
                   consts=dict(study.consts),
                   archive_path=archive_path,
                   layout=study.layout)

    # --- history -----------------------------------------------------------
    def header(self) -> str:
        cols = ("config", *self.knob_names, *self.value_names,
                *(c.name for c in self.extra_columns))
        if self.layout == "v2":
            cols += V2_META
        return "\t".join(cols) + "\n"

    def quarantine_path(self) -> Path:
        return self.path.with_name(self.path.name + ".quarantine.tsv")

    def _load_one(self, path: Path, *, lock: bool = True) -> list[Point]:
        """lock=False for the committed archive: _lock_path CREATES the lock
        file, so even a SHARED lock needs WRITE access to the repo
        (PermissionError at propose from someone else's checkout). The
        archive changes only by git commit, which no flock serializes anyway.
        """
        if not path.exists():
            return []
        out = []
        with (_flock_sh(path) if lock else nullcontext()), path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = self.header().rstrip("\n").split("\t")
            reader = csv.DictReader(f, fieldnames=cols, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                try:
                    out.append(Point(
                        cfg=row["config"],
                        x=[float(row[c]) for c in self.knob_names],
                        y={v: float(row[v]) for v in self.value_names}))
                except (KeyError, ValueError, TypeError) as e:
                    raise RowParseError(path, line_no, e) from e
        return out

    def load(self) -> list[Point]:
        """Committed priors first, then live rows; a config in BOTH counts
        once, archive-wins (a row left behind after promotion would enter
        the GP training set twice)."""
        archive = (self._load_one(self.archive_path, lock=False)
                   if self.archive_path else [])
        seen = {p.cfg for p in archive}
        live = [p for p in self._load_one(self.path) if p.cfg not in seen]
        return archive + live

    def format_line(self, p: Point, context: dict, meta: dict | None = None) -> str:
        """The exact line append() writes. Public so a caller holding the
        only record of a row's x can validate the row before discarding
        that record."""
        missing = [c for c in self.context_names if c not in context]
        if missing:
            raise LeaderboardError(
                f"{self.name}: row {p.cfg!r} needs runtime value(s) {missing} "
                f"(leaderboard.context) and the caller did not pass them")
        knobs = [fmt.format(v) for fmt, v in zip(self.knob_fmts, p.x)]
        values = [fmt.format(p.y[n])
                  for fmt, n in zip(self.value_fmts, self.value_names)]
        env = {**self.consts, **p.y, **context}
        extras = [c.fmt.format(c.evaluate(env)) for c in self.extra_columns]
        cells = [p.cfg, *knobs, *values, *extras]
        if self.layout == "v2":
            if meta is None or set(meta) != set(V2_META):
                raise LeaderboardError(
                    f"{self.name}: a v2 row needs meta {list(V2_META)}, got "
                    f"{None if meta is None else sorted(meta)}")
            for key in V2_META:
                v = meta[key]
                if not isinstance(v, str) or not v or "\t" in v or "\n" in v:
                    raise LeaderboardError(
                        f"{self.name}: meta {key!r} must be a non-empty "
                        f"string without tabs or newlines, got {v!r}")
            cells += [meta[k] for k in V2_META]
        elif meta is not None:
            raise LeaderboardError(f"{self.name}: a v1 row carries no meta")
        return "\t".join(cells) + "\n"

    def _raw_rows(self, path: Path | None) -> list[dict]:
        """Every row of `path` as {column: text}; the caller holds the lock
        (the live board) or none is needed (the archive)."""
        if path is None or not path.exists():
            return []
        with path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = self.header().rstrip("\n").split("\t")
            return list(csv.DictReader(f, fieldnames=cols, delimiter="\t"))

    def _check_v2(self, rows: list[dict], line: str) -> bool:
        """False when this exact row (apart from `time`) is already on the
        board. Raises DuplicateRow or MeasureMismatch, quarantining first."""
        cols = self.header().rstrip("\n").split("\t")
        new = dict(zip(cols, line.rstrip("\n").split("\t")))

        def sans_time(row):
            return {k: v for k, v in row.items() if k != "time"}
        same = [r for r in rows if r["config"] == new["config"]]
        if same:
            if all(sans_time(r) == sans_time(new) for r in same):
                return False
            self._append_quarantine(self.header(), line)
            raise DuplicateRow(self.path, new["config"],
                               self.quarantine_path())
        found = {r["measure_sha"] for r in rows}
        if found and found != {new["measure_sha"]}:
            self._append_quarantine(self.header(), line)
            raise MeasureMismatch(self.path, found, new["measure_sha"],
                                  self.quarantine_path())
        return True

    def append(self, p: Point, context: dict, meta: dict | None = None) -> bool:
        """True when a row was written. On a v2 board, False when the same
        row (apart from `time`) is already there: idempotent by name."""
        line = self.format_line(p, context, meta)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _flock_ex(self.path):
            if self.path.exists():
                with self.path.open() as f:
                    first = f.readline()
                if first.rstrip("\n") != self.header().rstrip("\n"):
                    self._append_quarantine(self.header(), line)
                    raise SchemaMismatch(self.path, self.header(), first,
                                         quarantined=self.quarantine_path())
            if self.layout == "v2":
                rows = (self._raw_rows(self.archive_path)
                        + self._raw_rows(self.path))
                if not self._check_v2(rows, line):
                    return False
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return True
            with self.path.open("a") as f:
                f.write(line)
            return True

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
        # LOCK_EX: two concurrent removals can race, one truncate clobbering
        # the other's deletion.
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
            # ALWAYS terminate with a newline, even when `kept` is empty: the
            # old `("\n" if kept else "")` left the header unterminated, and
            # appends in "a" mode then wrote the next row straight onto the
            # header line -- the file became a single line forever and
            # load_pending() returned 0 rows, silently. Fatal once the
            # pending TSV became the ONLY record of x: a campaign child
            # lost a finished 3.5 h eval to it (2026-07-26).
            pp.write_text("\n".join([header] + kept) + "\n")
            return True
