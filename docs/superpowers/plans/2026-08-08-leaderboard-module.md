# Leaderboard Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the five dormant Python-mode adapters, then introduce `core/leaderboard.py` — a schema-owning module for the per-mode history and pending TSVs with fail-loud + quarantine semantics.

**Architecture:** Phase 0 (Tasks 1–3) deletes the dormant adapters and everything only they used, so one row shape remains. Phase 1 (Tasks 4–8) builds the `Leaderboard` class (stdlib-only, no project imports — everything arrives via the constructor), slots it under `BOMode` as one-line delegations (zero `graph/` changes), and adds a `pending-prune` CLI verb plus regression tests for the three motivating incidents. Spec: `docs/superpowers/specs/2026-08-08-leaderboard-module-design.md`.

**Tech Stack:** Python 3.11 stdlib (`csv`, `json`, `fcntl`, `dataclasses`, `pathlib`); `unittest` (NOT pytest — this repo uses `unittest discover`).

## Global Constraints

- **Work in an isolated git worktree branched from `json-modes`.** The live checkout runs campaign foilspfbpz01, whose children re-import `core/` fresh each wave — never edit the live tree. Merge only after the campaign drains (the operator gates this).
- Test command (repo/worktree root): `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v`. Single file: `PYTHONPATH= .venv/bin/python -m unittest tests.test_leaderboard -v`. The leading `PYTHONPATH=` blank is required. If the suite hangs silently ~15 s in, delete `~/.cache/torch_extensions/*/logei_fused_ext/lock` (stale FileBaton, known issue).
- On-disk formats are **byte-identical for healthy files**: history header `"config\t" + knobs + "\t" + metric_cols + "\n"`; history row tail `{sob:.5f}\t{calo:.5e}\t{alpha:.3f}\t{obj:.5f}`; pending header `config\tx\talpha\tsubmitted_at`; pending row `{name}\t{json_x}\t{alpha:.3f}\t{int_epoch}`.
- Stale-pending threshold: **48 h** (`STALE_PENDING_S = 48 * 3600.0`). Quarantine file: `<file>.quarantine.tsv` appended next to the file it shadows.
- `metric_cols` is always exactly 4 columns `(sob-like, calo-like, "alpha", "obj")`.
- Zero changes under `graph/` in this entire plan.
- Commit messages: `refactor:`/`feat:`/`test:` prefix, subject ≤72 chars, body says why, and end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- Never `git push`. Never `git add -A`/`-u`/`.` — stage explicit paths only. Never wildcard `rm`.
- If the live-file header test (Task 8) fails on a real tracked TSV, STOP and report BLOCKED — do not "fix" a tracked leaderboard file.

---

### Task 1: Phase-0 archive cut — bo_driver.py, modes.py, mode_json.py

**Files:**
- Modify: `core/bo_driver.py` (delete :351-1142 adapters; edit :141-180, :1246-1259, :1896-1898)
- Modify: `core/modes.py` (delete five SPECS entries :147-289 region + orphaned constants)
- Modify: `core/mode_json.py` (delete `PYTHON_MODE_LEADERBOARDS` :65-76 and its consumer ~:503-510)
- Test: existing suite (update: `tests/test_modes.py`, `tests/test_mode_json.py`, `tests/test_audit_fixes.py`, `tests/test_botorch_predict.py`, `tests/test_closed_loop.py`, `tests/test_geom_template.py`, `tests/test_zero_overlap_policy.py`)

**Interfaces:**
- Consumes: nothing from other tasks (first task).
- Produces: `MODES` containing only `JsonMode` instances; `BOMode` with no `parse_geom`, concrete `load_priors() -> []`, and the pending-based `x_for_evaluate` as the base implementation. Task 6 relies on `BOMode` having exactly the methods listed in its step 3.

- [ ] **Step 1: Delete the five adapter classes.** In `core/bo_driver.py`, delete the contiguous region from the line `class FoilsMode(BOMode):` (line 351) up to but NOT including the line `class JsonMode(BOMode):` (line 1143). Sub-boundaries for orientation: `FoilsFracMode` 566, `FoilsGroupMode` 638, `ProdTargetMode` 779, `ProdTarget6DMode` 1041.

- [ ] **Step 2: Empty the Python-mode registry.** Replace lines 1246-1252:

```python
MODES: dict[str, BOMode] = {
    "foils":        FoilsMode(),
    "foilsf":       FoilsFracMode(),
    "foilsg":       FoilsGroupMode(),
    "prodtarget":   ProdTargetMode(),
    "prodtarget6d": ProdTarget6DMode(),
}
```

with:

```python
MODES: dict[str, BOMode] = {}
```

and update the comment above the `for _name, _spec in _modes.SPECS.items():` loop (it says "The six Python modes are already in MODES above" — now: "Every mode is JSON-defined; the Python adapters were archived 2026-08-08, see docs/superpowers/specs/2026-08-08-leaderboard-module-design.md").

- [ ] **Step 3: Shrink the BOMode interface.** In the `BOMode` class body (:141-180):
  - Delete the `@abstractmethod parse_geom` declaration (lines 161-162).
  - Replace the `@abstractmethod load_priors` (lines 155-156) with a concrete default:

```python
    def load_priors(self) -> list[Point]:
        """No mode has code-carried priors anymore (botorch Sobol cold-starts
        a fresh line; history comes from the leaderboard)."""
        return []
```

  - Replace the base `x_for_evaluate` (lines 164-180, the parse_geom round-trip) with `JsonMode.x_for_evaluate`'s body (currently at :1175-1193) — move it up verbatim, docstring included, and delete the override from `JsonMode`. Also delete `JsonMode.parse_geom` (:1169-1173) and `JsonMode.load_priors` (:1163-1164), now covered by the base class.
  - Update the `BOMode` class docstring (:142-148): the "6 mode-specific methods" list no longer includes `load_priors`, `parse_geom`.

- [ ] **Step 4: Make `--mode` required.** At :1896-1898 the parser reads `ap.add_argument("--mode", choices=list(MODES.keys()), default="foils", ...)`. Delete `default="foils"` and add `required=True`. Then verify every subprocess caller already passes `--mode` explicitly: `grep -n "bo_driver" graph/pipeline_io.py` and confirm each constructed command includes `"--mode"` (expected: all do).

- [ ] **Step 5: Delete the five SPECS entries.** In `core/modes.py`, delete the dict entries `"foils":`, `"foilsf":`, `"foilsg":`, `"prodtarget":`, `"prodtarget6d":` (the region :147-289 inside `SPECS: Dict[str, ModeSpec] = {...}`), leaving `SPECS: Dict[str, ModeSpec] = {}` followed by the existing `SPECS.update(load_mode_dir(MODES_DIR, SPECS))`. Then delete now-orphaned module constants: grep each `_NAME = ` constant above SPECS (e.g. `_PRODTARGET_TARBALL`, `_HELICAL_LOCAL`, any `_FOILS*`) and delete those with zero remaining references (`grep -n "<const>" core/ graph/ tests/ -r`). Update the `harvest_verb` field comment (:70) from `"harvest" | "harvest-pot-only"` to `"harvest"` only.

- [ ] **Step 6: Delete the Python-leaderboard carve-out in mode_json.py.** Delete the `PYTHON_MODE_LEADERBOARDS` dict (:65-76) with its lead-in comment block, and its consumer in the validation function (~:503-510: the `owner = PYTHON_MODE_LEADERBOARDS.get(lb)` block through the `raise ValueError(... belongs to the Python mode ...)`). Keep the JSON-vs-JSON name-collision check and everything else.

- [ ] **Step 7: Sweep for stranded mode-name references.** Run `grep -n '"foils"\|"foilsf"\|"foilsg"\|"prodtarget"\|"prodtarget6d"\|prodtarget6d\|foilsg' core/bo_driver.py core/pipeline.py core/modes.py core/mode_json.py` and fix every live-code hit — in particular any preflight mode TUPLE naming a deleted mode (the surface-check tuple near the bottom of `bo_driver.py`; cf. wiki incident `preflight-mode-tuple-prodtarget6d-omission` — membership tuples silently go stale). Comment/docstring hits may stay if historical ("retired 2026-08-08" phrasing preferred).

- [ ] **Step 8: Run the suite and fix the fallout tests.** Run the full suite. Expected initial failures in: `tests/test_modes.py` (9 refs — completeness/registry tests naming the five modes), `tests/test_mode_json.py` (4 refs — `TestLeaderboardUniqueness` pins the deleted map; delete that TestCase; a collision-guard test may use a Python-mode name — repoint it at an existing JSON name like `foilsflash`), `tests/test_botorch_predict.py` / `tests/test_closed_loop.py` / `tests/test_audit_fixes.py` / `tests/test_geom_template.py` / `tests/test_zero_overlap_policy.py` (grep each for `foils"`, `foilsf`, `foilsg`, `prodtarget` — update fixtures/parametrization to JSON modes, or delete cases that exist only to exercise a deleted adapter). Do NOT touch `tests/fixtures/modes/*.json` fixture files unless a test names them for a deleted mode. Re-run until green.

- [ ] **Step 9: Commit.**

```bash
git add core/bo_driver.py core/modes.py core/mode_json.py tests/test_modes.py tests/test_mode_json.py tests/test_audit_fixes.py tests/test_botorch_predict.py tests/test_closed_loop.py tests/test_geom_template.py tests/test_zero_overlap_policy.py
git commit -m "refactor(modes): archive the five dormant Python-mode adapters"
```

(Body: dormant since June; JsonMode backs all active modes; interface shrinks to what the live path uses; per spec 2026-08-08. Add the two trailer lines from Global Constraints. If Step 7 touched additional test files, stage them explicitly too.)

Note: `graph/state.py` needs NO change — its mode field is already a plain `str`, not a Literal (checked 2026-08-08; the spec line about the Literal is a no-op).

---

### Task 2: Phase-0 archive cut — pipeline.py pot_only path

**Files:**
- Modify: `core/pipeline.py` (delete `cmd_harvest_pot_only` :1188-1267, the `STAGES["pot_only"]` entry ~:235, verb dispatch, `__PT_PLATE_NAMES__` templating ~:379, docstring mentions :14 region/:134/:520)
- Modify: `core/mode_json.py` (delete the `_POT_ONLY_STAGE` validation block :299-320)
- Test: `tests/test_pipeline_verbs.py` (and any other test the greps surface)

**Interfaces:**
- Consumes: Task 1 (SPECS no longer contains any mode with `harvest_verb="harvest-pot-only"` or `grid_stages=("pot_only",)`).
- Produces: `pipeline.py` with a single harvest verb (`harvest`); no task depends on details beyond that.

- [ ] **Step 1: Map every pot_only reference.** Run `grep -n "pot_only\|harvest-pot-only\|PT_PLATE_NAMES" core/pipeline.py core/mode_json.py core/modes.py tests/*.py` and list the hits. Expected clusters: the `STAGES["pot_only"]` dict entry (~:235-238), `cmd_harvest_pot_only` (:1188-1267), the verb dispatch entry for `"harvest-pot-only"` in the argument parsing/dispatch at the bottom of the file, `_check_stage_config_sha("pot_only")` inside the deleted function, the `__PT_PLATE_NAMES__` token handling (~:379), docstring/comment mentions (:14 area, :134, :520), and `core/mode_json.py:299-320`.

- [ ] **Step 2: Delete them.** Remove `cmd_harvest_pot_only` wholesale, the `"pot_only"` entry from `STAGES`, the `harvest-pot-only` verb from the dispatch table/parser, the `__PT_PLATE_NAMES__` templating branch, the `mode_json.py` `_POT_ONLY_STAGE` block (:299-320) and the `_POT_ONLY_STAGE` constant if now unused, and prune the docstring/comment mentions. If `core/pipeline_templates/pot_only/` exists (`ls core/pipeline_templates/`), `git rm -r core/pipeline_templates/pot_only` (explicit path).

- [ ] **Step 3: Run the suite.** Fix any test referencing the deleted verb (expected: at most `tests/test_pipeline_verbs.py`; it covered submit/poll/list-outputs, so likely already green). Re-run until green.

- [ ] **Step 4: Commit.**

```bash
git add core/pipeline.py core/mode_json.py
git commit -m "refactor(pipeline): retire the harvest-pot-only verb with its modes"
```

(Stage `tests/test_pipeline_verbs.py` and the removed template dir too if touched. Trailers per Global Constraints.)

---

### Task 3: Phase-0 — delete the fossil pending files

**Files:**
- Delete: `leaderboards/pending_bo_foils.tsv`, `leaderboards/pending_bo_foilsf.tsv`, `leaderboards/pending_bo_foilsg.tsv`, `leaderboards/pending_bo_prodtarget.tsv`, `leaderboards/pending_bo_prodtarget6d.tsv`, `leaderboards/pending_bo_helical.tsv`, `leaderboards/pending_bo_ipa.tsv`

**Interfaces:**
- Consumes: Tasks 1-2 (the owning modes no longer exist).
- Produces: nothing downstream; this is the operator-visible deletion step from the spec.

- [ ] **Step 1: Verify the exact set.** `ls leaderboards/pending_bo_*.tsv`. The seven files above (and ONLY those) belong to archived/dead modes. Every other `pending_bo_*.tsv` belongs to a live JSON mode — do not touch. All `leaderboard_*.tsv` files are KEPT (frozen history record).

- [ ] **Step 2: Delete with explicit paths** (never a wildcard):

```bash
git rm leaderboards/pending_bo_foils.tsv leaderboards/pending_bo_foilsf.tsv leaderboards/pending_bo_foilsg.tsv leaderboards/pending_bo_prodtarget.tsv leaderboards/pending_bo_prodtarget6d.tsv leaderboards/pending_bo_helical.tsv leaderboards/pending_bo_ipa.tsv
```

If any of the seven is untracked, `git rm` errors for it — remove that one with plain `rm leaderboards/pending_bo_<name>.tsv` (explicit path) instead.

- [ ] **Step 3: Suite still green** (no code change expected to care — this catches a test that read a fossil by path).

- [ ] **Step 4: Commit.**

```bash
git commit -m "chore(leaderboards): delete fossil pending files of archived modes"
```

(Body: five carried fused headers from the fixed remove_pending bug + 23-95 stale June rows each; frozen leaderboard_*.tsv all kept. Trailers per Global Constraints.)

---

### Task 4: `core/leaderboard.py` — history half (Point, locks, load/append, quarantine)

**Files:**
- Create: `core/leaderboard.py`
- Test: `tests/test_leaderboard.py` (create)

**Interfaces:**
- Consumes: nothing (stdlib-only module; Task 1's uniform 4-col shape is an assumption it validates).
- Produces (Tasks 5-8 rely on these exact names): `Point(cfg, x, sob, calo, extras=None)` with `.obj(alpha)`; `to_py_scalars(x)`; `_lock_path/_flock_ex/_flock_sh`; `LeaderboardError`, `SchemaMismatch(path, expected, found, quarantined=None)`, `RowParseError(path, line_no, cause)`; `Leaderboard(path, name, knob_names, knob_fmts, metric_cols)` frozen dataclass with `from_spec(spec, root)`, `header()`, `load() -> list[Point]`, `append(p, alpha)`, `quarantine_path()`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_leaderboard.py`:

```python
"""Leaderboard module: schema-owning history/pending I/O (spec 2026-08-08).

Regression anchors: touched-leaderboard-headerless-history-loss (foilspfbw01),
the remove_pending header-fusion bug (foilsflash24R00_00), stale pending rows.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from leaderboard import (  # noqa: E402
    Leaderboard, Point, SchemaMismatch, RowParseError)


def make_lb(tmp: Path) -> Leaderboard:
    return Leaderboard(
        path=tmp / "leaderboard_bo_test.tsv", name="test",
        knob_names=("k0", "k1"), knob_fmts=("{:.2f}", "{:.2f}"),
        metric_cols=("sob", "flash_edep", "alpha", "obj"))


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = make_lb(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def test_header_line(self):
        self.assertEqual(self.lb.header(),
                         "config\tk0\tk1\tsob\tflash_edep\talpha\tobj\n")

    def test_missing_file_loads_empty(self):
        self.assertEqual(self.lb.load(), [])

    def test_append_load_roundtrip(self):
        p = Point(cfg="t01", x=[1.5, 2.5], sob=3.14159, calo=6.85e-7)
        self.lb.append(p, alpha=1.0e5)
        first = self.lb.path.read_text().splitlines()[0] + "\n"
        self.assertEqual(first, self.lb.header())
        [got] = self.lb.load()
        self.assertEqual(got.cfg, "t01")
        self.assertEqual(got.x, [1.5, 2.5])
        self.assertAlmostEqual(got.sob, 3.14159, places=5)
        self.assertAlmostEqual(got.calo, 6.85e-7, places=12)

    def test_touched_file_is_loud_not_empty(self):
        # touched-leaderboard-headerless-history-loss: a 0-byte existing file
        # must raise, never return [] while rows could exist.
        self.lb.path.touch()
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_fused_header_is_loud(self):
        # the remove_pending fusion shape: header and row 1 on one line.
        self.lb.path.write_text(
            "config\tk0\tk1\tsob\tflash_edep\talpha\tobj"
            "t01\t1.00\t2.00\t3.00000\t1.00000e-07\t1.000\t3.00000\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_malformed_row_is_loud_with_line_number(self):
        self.lb.append(Point("t01", [1.0, 2.0], 3.0, 1e-7), alpha=1.0)
        with self.lb.path.open("a") as f:
            f.write("t02\tnot_a_number\t2.00\t3.00000\t1.0e-07\t1.000\t3.00000\n")
        with self.assertRaises(RowParseError) as cm:
            self.lb.load()
        self.assertEqual(cm.exception.line_no, 3)

    def test_append_on_mismatch_quarantines_then_raises(self):
        self.lb.path.write_text("config\twrong\theader\n")
        p = Point(cfg="t01", x=[1.0, 2.0], sob=3.0, calo=1e-7)
        with self.assertRaises(SchemaMismatch):
            self.lb.append(p, alpha=1.0)
        q = self.lb.quarantine_path()
        self.assertTrue(q.exists())
        lines = q.read_text().splitlines()
        self.assertEqual(lines[0] + "\n", self.lb.header())
        self.assertTrue(lines[1].startswith("t01\t"))
        # main file untouched
        self.assertEqual(self.lb.path.read_text(), "config\twrong\theader\n")

    def test_bad_spec_fails_at_construction(self):
        with self.assertRaises(ValueError):
            Leaderboard(path=self.tmp / "x.tsv", name="x",
                        knob_names=("a",), knob_fmts=("{:.2f}",),
                        metric_cols=("sob", "calo"))  # not 4 columns


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure.** `PYTHONPATH= .venv/bin/python -m unittest tests.test_leaderboard -v` — expected: `ModuleNotFoundError: No module named 'leaderboard'`.

- [ ] **Step 3: Implement.** Create `core/leaderboard.py`. `_lock_path`, `_flock_ex`, `_flock_sh` are MOVED VERBATIM from `core/bo_driver.py:45-93` (docstrings included — the locks/-dir-anchor rationale matters); `Point` and `to_py_scalars` moved verbatim from `:105-124`. (Leave the originals in `bo_driver.py` for now — Task 6 deletes them there; duplication is fine for one task.) Then:

```python
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
```

then (after the moved `Point`/`to_py_scalars`/lock helpers):

```python
@dataclass(frozen=True)
class Leaderboard:
    path: Path
    name: str
    knob_names: tuple
    knob_fmts: tuple
    metric_cols: tuple   # exactly (sob-like, calo-like, "alpha", "obj")

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
    def from_spec(cls, spec, root: Path) -> "Leaderboard":
        return cls(path=root / spec.leaderboard_rel, name=spec.name,
                   knob_names=tuple(spec.knob_names),
                   knob_fmts=tuple(spec.knob_fmts),
                   metric_cols=tuple(spec.metric_cols))

    # --- history -----------------------------------------------------------
    def header(self) -> str:
        return ("config\t" + "\t".join(self.knob_names)
                + "\t" + "\t".join(self.metric_cols) + "\n")

    def quarantine_path(self) -> Path:
        return self.path.with_name(self.path.name + ".quarantine.tsv")

    def load(self) -> list[Point]:
        if not self.path.exists():
            return []
        out = []
        with _flock_sh(self.path), self.path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(self.path, self.header(), first)
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
                    raise RowParseError(self.path, line_no, e) from e
        return out

    def _format_line(self, p: Point, alpha: float) -> str:
        knobs = "\t".join(
            fmt.format(v) for fmt, v in zip(self.knob_fmts, p.x))
        return (f"{p.cfg}\t{knobs}\t{p.sob:.5f}\t{p.calo:.5e}"
                f"\t{alpha:.3f}\t{p.obj(alpha):.5f}\n")

    def append(self, p: Point, alpha: float) -> None:
        line = self._format_line(p, alpha)
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
```

- [ ] **Step 4: Run to verify pass.** `PYTHONPATH= .venv/bin/python -m unittest tests.test_leaderboard -v` — all Task-4 tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add core/leaderboard.py tests/test_leaderboard.py
git commit -m "feat(leaderboard): schema-owning history module, fail-loud + quarantine"
```

(Trailers per Global Constraints.)

---

### Task 5: `core/leaderboard.py` — pending half (add/load/remove/prune, stale warning)

**Files:**
- Modify: `core/leaderboard.py`
- Test: `tests/test_leaderboard.py` (extend)

**Interfaces:**
- Consumes: Task 4's `Leaderboard`, `PENDING_HEADER`, `STALE_PENDING_S`, error types, `to_py_scalars`.
- Produces (Tasks 6-7 rely on): `pending_path() -> Path`, `pending_add(name, x, alpha)`, `pending_load(now=None) -> list[tuple[str, list]]`, `pending_remove(name) -> bool`, `pending_prune(older_than_h=48.0, now=None) -> list[str]`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_leaderboard.py`:

```python
import io
import time
from contextlib import redirect_stderr


class TestPending(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = make_lb(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def test_add_load_remove_roundtrip(self):
        self.lb.pending_add("t01", [1.5, 2.5], alpha=1.0e5)
        self.lb.pending_add("t02", [3.0, 4.0], alpha=1.0e5)
        self.assertEqual(self.lb.pending_load(),
                         [("t01", [1.5, 2.5]), ("t02", [3.0, 4.0])])
        self.assertTrue(self.lb.pending_remove("t01"))
        self.assertFalse(self.lb.pending_remove("t01"))
        self.assertEqual(self.lb.pending_load(), [("t02", [3.0, 4.0])])

    def test_last_row_removal_keeps_header_newline(self):
        # regression: the fusion bug's ROOT CAUSE — header must stay
        # newline-terminated when the last pending row is removed.
        self.lb.pending_add("t01", [1.0, 2.0], alpha=1.0)
        self.assertTrue(self.lb.pending_remove("t01"))
        self.assertTrue(self.lb.pending_path().read_text().endswith("\n"))
        self.lb.pending_add("t02", [3.0, 4.0], alpha=1.0)
        self.assertEqual(self.lb.pending_load(), [("t02", [3.0, 4.0])])

    def test_stale_rows_warn_but_are_returned(self):
        self.lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
        now = time.time() + 49 * 3600
        buf = io.StringIO()
        with redirect_stderr(buf):
            rows = self.lb.pending_load(now=now)
        self.assertEqual(rows, [("old01", [1.0, 2.0])])
        self.assertIn("old01", buf.getvalue())
        self.assertIn("pending-prune", buf.getvalue())

    def test_prune_removes_only_stale(self):
        self.lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
        self.lb.pending_add("new01", [3.0, 4.0], alpha=1.0)
        now = time.time() + 49 * 3600
        # Both rows share a real timestamp, so selectivity is exercised via
        # the threshold: at 50h neither qualifies, at 48h both do.
        self.assertEqual(self.lb.pending_prune(older_than_h=50.0, now=now), [])
        removed = self.lb.pending_prune(older_than_h=48.0, now=now)
        self.assertEqual(sorted(removed), ["new01", "old01"])
        self.assertEqual(self.lb.pending_load(), [])
        self.assertTrue(self.lb.pending_path().read_text().endswith("\n"))

    def test_pending_header_mismatch_is_loud(self):
        self.lb.pending_path().write_text("config\twrong\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.pending_load()
        with self.assertRaises(SchemaMismatch):
            self.lb.pending_add("t01", [1.0, 2.0], alpha=1.0)
        self.assertTrue(self.lb.pending_path()
                        .with_name(self.lb.pending_path().name
                                   + ".quarantine.tsv").exists())
```

- [ ] **Step 2: Run to verify failure** (`AttributeError: ... no attribute 'pending_add'`).

- [ ] **Step 3: Implement.** Add to the `Leaderboard` class. `pending_remove` is `BOMode.remove_pending` (`bo_driver.py:314-344`) moved verbatim — INCLUDING the incident tombstone comment at :328-342 — with `self.pending_path()` for `pp`. The rest:

```python
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
```

- [ ] **Step 4: Run — all tests pass** (fix the module until they do, not the tests).

- [ ] **Step 5: Commit.**

```bash
git add core/leaderboard.py tests/test_leaderboard.py
git commit -m "feat(leaderboard): pending ownership — stale warning + explicit prune"
```

---

### Task 6: BOMode delegates to Leaderboard; bo_driver sheds the moved code

**Files:**
- Modify: `core/bo_driver.py` (delete moved definitions; rewire `BOMode`; keep public API)
- Test: `tests/test_modes.py` (move the format/parse round-trip to the module API), full suite

**Interfaces:**
- Consumes: Tasks 4-5 (`Leaderboard`, `Point`, `to_py_scalars`, lock helpers, all pending methods).
- Produces: `BOMode.load_history/append_history/load_pending/append_pending/remove_pending/pending_path` — signatures unchanged; plus `BOMode.leaderboard_io() -> Leaderboard` (Task 7 uses it). `bo_driver.Point` and `bo_driver.to_py_scalars` still importable (re-export).

- [ ] **Step 1: Rewire imports.** In `core/bo_driver.py`, delete the local definitions of `_lock_path`, `_flock_ex`, `_flock_sh` (:45-93), `Point` (:105-116), `to_py_scalars` (:120-124). Below the existing `import modes as _modes`-style imports add (bare import — `core/` is on the path exactly like `modes`):

```python
from leaderboard import (  # noqa: E402  (re-exports: Point, to_py_scalars
    Leaderboard, Point, to_py_scalars,   # are public API of this module)
    _flock_ex, _flock_sh, _lock_path)
```

- [ ] **Step 2: Delete the BOMode I/O bodies.** Remove `format_row` (:203-216), `load_history_row` (:218-221), `load_history` (:266-276), `append_history` (:278-285), `pending_path` (:288-289), `load_pending` (:291-302), `append_pending` (:304-312), `remove_pending` (:314-344), and the `CALO_COL` property (:198-201) IF `grep -n "CALO_COL" core/ graph/ tests/ -r` shows no remaining consumer (expected: only the deleted `load_history_row` used it; if a test asserts it, update the test to read `spec.metric_cols[1]`).

- [ ] **Step 3: Add the delegation block** in `BOMode` where the deleted methods were:

```python
    # --- leaderboard + pending I/O: owned by core/leaderboard.py -----------
    def leaderboard_io(self) -> Leaderboard:
        lb = getattr(self, "_lb_cache", None)
        if lb is None:
            spec = _modes.SPECS[self.name]
            lb = Leaderboard(path=self.leaderboard, name=self.name,
                             knob_names=tuple(spec.knob_names),
                             knob_fmts=tuple(spec.knob_fmts),
                             metric_cols=tuple(spec.metric_cols))
            self._lb_cache = lb
        return lb

    def load_history(self) -> list[Point]:
        return self.leaderboard_io().load()

    def append_history(self, p: Point, alpha: float):
        self.leaderboard_io().append(p, alpha)

    def pending_path(self) -> Path:
        return self.leaderboard_io().pending_path()

    def load_pending(self) -> list[tuple[str, list]]:
        return self.leaderboard_io().pending_load()

    def append_pending(self, name: str, x, alpha: float):
        self.leaderboard_io().pending_add(name, x, alpha)

    def remove_pending(self, name: str) -> bool:
        return self.leaderboard_io().pending_remove(name)
```

(Note `leaderboard_io()` builds from `self.leaderboard` — already `ROOT / spec.leaderboard_rel` in `JsonMode.__init__` — not `from_spec`, so a test-subclassed mode with a custom path keeps working.)

- [ ] **Step 4: Fix the fallout.** Run the suite. Expected: `tests/test_modes.py` round-trip tests (~:104-133) called `mode.format_row`/`load_history_row` — rewrite them against `MODES[name].leaderboard_io()`: `append()` to a temp-dir `Leaderboard` built with the same spec columns, `load()` back, compare Points (the Task 4 round-trip test is the template). Any other `format_row` reference in tests gets the same treatment. `mode_json.py`'s error strings mention `BOMode.format_row`/`load_history_row` in PROSE — update the two strings to name `core/leaderboard.py` instead (:376, :380 region). Re-run until fully green.

- [ ] **Step 5: Verify the moved code left no duplicates.** `grep -n "def format_row\|def load_history_row\|def _flock_ex\|class Point" core/bo_driver.py` → zero hits; `grep -rn "def append_history\|def load_history\b" core/` → only `leaderboard.py`... (`load_history` remains as the BOMode delegation — confirm exactly one `def load_history` in `bo_driver.py`, the one-liner).

- [ ] **Step 6: Commit.**

```bash
git add core/bo_driver.py core/mode_json.py tests/test_modes.py
git commit -m "refactor(bo_driver): BOMode delegates all TSV I/O to Leaderboard"
```

---

### Task 7: `pending-prune` CLI verb

**Files:**
- Modify: `core/bo_driver.py` (subparser ~:1900-1920 region + command function + dispatch)
- Test: `tests/test_leaderboard.py` (extend — test the command function directly)

**Interfaces:**
- Consumes: Task 6's `BOMode.leaderboard_io()`, Task 5's `pending_prune`.
- Produces: CLI `./core/bo_driver.py --mode <m> pending-prune [--older-than-hours H]`; function `cmd_pending_prune(args) -> int`.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_leaderboard.py`:

```python
class TestPendingPruneCmd(unittest.TestCase):
    def test_cmd_pending_prune_prints_and_prunes(self):
        import types
        import bo_driver as bo
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            lb = make_lb(tmp)
            lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
            mode = next(iter(bo.MODES.values()))
            with unittest.mock.patch.object(
                    type(mode), "leaderboard_io", return_value=lb):
                args = types.SimpleNamespace(
                    mode=mode.name, older_than_hours=-1.0)  # everything stale
                rc = bo.cmd_pending_prune(args)
                self.assertEqual(rc, 0)
                self.assertEqual(lb.pending_load(), [])  # row actually pruned
```

(add `import unittest.mock` at the top of the file with the other imports; `--mode` flows through `args.mode` → `bo.MODES[args.mode]`, so patching `leaderboard_io` on the mode's class isolates the filesystem.)

- [ ] **Step 2: Run to verify failure** (`AttributeError: module 'bo_driver' has no attribute 'cmd_pending_prune'`).

- [ ] **Step 3: Implement.** In `core/bo_driver.py`, next to `cmd_propose`/`cmd_evaluate`:

```python
def cmd_pending_prune(args):
    mode = MODES[args.mode]
    removed = mode.leaderboard_io().pending_prune(
        older_than_h=args.older_than_hours)
    if removed:
        print(f"[{mode.name}] pruned {len(removed)} stale pending row(s): "
              + ", ".join(removed))
    else:
        print(f"[{mode.name}] nothing stale "
              f"(threshold {args.older_than_hours:.0f}h)")
    return 0
```

and in the parser section (after the `preflight` subparser, ~:1917):

```python
    p_prune = sub.add_parser(
        "pending-prune",
        help="Delete pending rows older than a threshold (never automatic; "
             "this is the command the stale-row warning points at)")
    p_prune.add_argument("--older-than-hours", type=float, default=48.0)
```

Wire it in the same `cmd` dispatch the other verbs use (match the existing pattern at the bottom of `main`, e.g. add `"pending-prune": cmd_pending_prune` or the equivalent `elif`).

- [ ] **Step 4: Run — test passes; suite green.**

- [ ] **Step 5: Commit.**

```bash
git add core/bo_driver.py tests/test_leaderboard.py
git commit -m "feat(bo_driver): pending-prune verb — explicit stale-row removal"
```

---

### Task 8: Live-file header invariant test + final verification

**Files:**
- Create: `tests/test_live_leaderboard_headers.py`
- Test: full suite

**Interfaces:**
- Consumes: `Leaderboard.from_spec(spec, root)` (Task 4), `modes.SPECS`, `PENDING_HEADER`.
- Produces: the permanent invariant test; nothing downstream.

- [ ] **Step 1: Write the test** (it should PASS immediately — it is the pre-landing safety check, kept forever):

```python
"""Every live tracked leaderboard/pending file must satisfy its ModeSpec
header — the pre-landing check of spec 2026-08-08, kept permanently so
schema drift is caught in the suite, not mid-campaign.

If this fails on a REAL tracked file: STOP, report — do not edit the file.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import modes  # noqa: E402
from leaderboard import Leaderboard, PENDING_HEADER  # noqa: E402


class TestLiveFileHeaders(unittest.TestCase):
    def test_every_live_leaderboard_and_pending_header(self):
        checked = 0
        for name, spec in modes.SPECS.items():
            lb = Leaderboard.from_spec(spec, root=ROOT)
            if lb.path.exists():
                with lb.path.open() as f:
                    first = f.readline()
                self.assertEqual(
                    first.rstrip("\n"), lb.header().rstrip("\n"),
                    msg=f"{lb.path} header != ModeSpec({name}) schema")
                checked += 1
            pp = lb.pending_path()
            if pp.exists() and pp.stat().st_size > 0:
                with pp.open() as f:
                    first = f.readline()
                self.assertEqual(
                    first.rstrip("\n"), PENDING_HEADER.rstrip("\n"),
                    msg=f"{pp} pending header malformed")
                checked += 1
        self.assertGreater(checked, 0, "no live files found — wrong ROOT?")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it.** Expected PASS. If it fails on a tracked file, STOP per Global Constraints (report which file and both header lines).

- [ ] **Step 3: Full-suite + zero-graph-diff verification.**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v
git diff --stat json-modes...HEAD -- graph/
```

Expected: suite green; the `graph/` diff is EMPTY.

- [ ] **Step 4: Commit.**

```bash
git add tests/test_live_leaderboard_headers.py
git commit -m "test(leaderboard): permanent live-file header invariant"
```

---

## Post-plan (operator, not the implementer)

- Merge to `json-modes` only after foilspfbpz01 drains; run the suite once more in the live tree post-merge.
- Wiki updates (archived-mode project pages, index one-liners, log bullet) happen in the operator session, uncommitted, per project convention.
