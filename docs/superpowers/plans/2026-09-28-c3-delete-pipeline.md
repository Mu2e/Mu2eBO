# Phase C3: Delete the Old Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the contract engine the only way to run a study, then:
- delete the old pipeline and its tests;
- rename the engine's runner and loop to `graph.run` and `graph.closed_loop`;
- rewrite the docs and skills for the engine.

**Architecture:**
1. The Kerberos check moves into `core/contract.py`. The tree stays green.
2. One cut commit:
   - archives the seven original foilspf studies;
   - deletes every pipeline-only module, tool, test and fixture;
   - strips the pipeline fallbacks out of the shared modules
     (`core/modes.py`, `core/kit_registry.py`, `core/botorch_predict.py`,
     `graph/pool.py`, `core/paths.py`);
   - trims the shared tests.
3. A rename commit.
4. Two documentation tasks.

The seven `_ax` studies' `measure_basis_sha` must not change, so every row
already on their boards stays appendable.

**Tech Stack:** Python 3.12 (`ana 2.8.0`, via `$AUTORESEARCH_PYTHON`),
unittest, LangGraph (engine only), MCP stdio kits.

**Spec:** `docs/superpowers/specs/2026-09-28-c3-delete-pipeline-design.md`

## Global Constraints

- **Environment:** `cd /exp/mu2e/app/users/oksuzian/autoresearch && source activate.sh`.
- **Suite:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`.
  - One file: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_<name> -v`.
  - A full run takes about 5 min.
- **Branch:** `generic-study-phase-c3`.
- **Git:**
  - Stage explicit paths only: `git add <path>...` / `git rm` / `git mv`. Never `git add -A`, `git add .`, `git stash`, `git checkout -- <file>` or `git reset`.
  - The operator's uncommitted `docs/*` changes and untracked `docs/*` files must stay untouched and unstaged.
- **Commit trailers**, every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```
- **Scratch and outputs** go under `/exp/mu2e/data/users/oksuzian/`, never `/tmp` or `$HOME`.
- **No silent fallbacks.** A removed default becomes a required argument or a loud error, never a quiet substitute.
- **Look before deleting.** Read each file before `git rm` (Task 2 Step 3 says what to look for).
- **History files keep old names:**
  - Do not edit `docs/superpowers/specs/*` or `docs/superpowers/plans/*` other than this plan.
  - Do not edit `wiki/log.md` entries older than today.
- **Unchanged measurement.** After Tasks 2 and 3, each `_ax` study's `measure_basis_sha` must equal:
  ```
  foilsflash_ax  405cc0e850b9dc4ed28ee96bea8187c94185bce654230acc5016de73a1763d6f
  foilspf2k_ax   2060c97e7de0a4a18f6364e0a721e6abe45e4bc98a089b4ffedcea75385e12a4
  foilspf_ax     e96f0491abe95519352962dc51616fca0598eabf5b5cfba122734179da3b250e
  foilspfbp_ax   54467d3e05b4742da1fbd3a7809cf50f770fdc18219c40773ada487355cb0547
  foilspfbpx_ax  d6ee2d286f6e8e26a6417dfb9530789beefd8f385179036f60c4385d1e6d8a4d
  foilspfbpz_ax  c4aafee1c30ba5121ab727bcab4513786b6d076c10f976d1b786daf95e218a80
  foilspfbw_ax   01bcbd62be9a8f4d8b825e85267a3e7b45a0746b2784f1c48c32aeacba962191
  ```
  Check with:
  ```bash
  PYTHONPATH= "$AUTORESEARCH_PYTHON" -c "
  import sys; sys.path.insert(0,'core'); import modes
  for n in sorted(modes.STUDIES):
      if n.endswith('_ax'): print(n, modes.STUDIES[n].measure_basis_sha)"
  ```
- **Do not change:**
  - `stage_entries/*.json`, the `desc_fmt` key, or `core/pipeline_templates/` (spec rulings);
  - any `mode_specs/*_ax.json`;
  - `kits.toml` server entries.
- **Keep the v1 layout code** in `core/leaderboard.py` (spec ruling).

## Review Focus

1. An operator types the old command shape, `python -m graph.run --mode foilspf --x-point 1,2,3`. Expected: argparse refuses with exit 2, and nothing starts. Pinned in Task 3 (`tests/test_run.py`).
2. An operator names an archived study (`--study foilspf`) in `graph.run` or `graph.closed_loop`. Expected: exit 2, "unknown study", with a hint that `mode_specs/archive/` is not loaded. Pinned in Task 3.
3. A stale `AUTORESEARCH_MODE=foilspf` (or any value) is still exported in the operator's shell. Expected: every engine import ignores it, with no `SystemExit`. Pinned in Task 2 (`tests/test_modes.py`).
4. An `_ax` study whose board file does not exist yet; six of the seven have none. Expected: `botorch_predict.history_points` returns `[]`, and `load_history_tensor` returns empty tensors, never a crash. Pinned in Task 2 (`tests/test_botorch_predict.py`).
5. `graph.closed_loop` refuses a busy child name. Expected: the recovery hint names the new runner (`pgrep -f 'graph.run.*<name>'`), not `study_run`. Pinned in Task 3 (`tests/test_closed_loop.py`).

---

### Task 1: The Kerberos check moves into `core/contract.py`

**Files:**
- Modify: `core/contract.py`: imports at lines 21-27; add the Kerberos block after `requires_kerberos` (~line 375).
- Modify: `core/launch_checks.py`: replace `GRID_TICKET_SECONDS`, `_klist_text`, `_parse_klist_time` and `check_kerberos` with a re-export.
- Modify: `graph/study_run.py`: lines 23-24 (import) and 35-37 (`_kerberos`).
- Test: `tests/test_contract.py` (new class `TestKerberos`); `tests/test_launch_checks.py` (drop its `TestKerberos`, lines ~15-67).

**Interfaces:**
- Produces: `contract.GRID_TICKET_SECONDS = 4 * 3600`.
- Produces: `contract.check_kerberos(min_seconds: int, *, klist_text=_klist_text, now=time.time) -> str | None`.
- Produces: `contract._klist_text() -> str | None` and `contract._parse_klist_time(stamp: str) -> int | None`.
- The code is moved verbatim from `core/launch_checks.py`, which keeps re-exporting the names until Task 2 deletes it.

- [ ] **Step 1: Write the failing tests** in `tests/test_contract.py`, at the end, before `if __name__ == "__main__":` if present:

```python
# A krbtgt line in klist's real shape; the expiry is far enough out that only
# an absurd min_seconds trips it.
KLIST_OK = """Ticket cache: FILE:/tmp/krb5cc_1000
Default principal: someone@FNAL.GOV

Valid starting       Expires              Service principal
01/01/2030 11:35:23  01/02/2030 13:35:19  krbtgt/FNAL.GOV@FNAL.GOV
"""


class TestKerberos(unittest.TestCase):
    """The engine's grid-launch ticket gate (moved from the pipeline's
    core/launch_checks.py in Phase C3)."""

    def setUp(self):
        # Computed the way the module does, so the test is independent of
        # the machine's timezone.
        self.expiry = ct._parse_klist_time("01/02/2030 13:35:19")

    def test_no_ticket_is_a_problem(self):
        self.assertIn("kinit", ct.check_kerberos(0, klist_text=lambda: None))

    def test_ticket_cache_without_krbtgt_is_a_problem(self):
        """An expired cache still prints a header; only a krbtgt line counts."""
        header = "Ticket cache: FILE:/tmp/krb5cc_1000\n\nValid starting\n"
        self.assertIn("kinit", ct.check_kerberos(0, klist_text=lambda: header))

    def test_zero_seconds_accepts_any_live_ticket(self):
        self.assertIsNone(ct.check_kerberos(0, klist_text=lambda: KLIST_OK))

    def test_long_ticket_passes_the_grid_life_check(self):
        self.assertIsNone(ct.check_kerberos(
            ct.GRID_TICKET_SECONDS, klist_text=lambda: KLIST_OK,
            now=lambda: self.expiry - 86400))

    def test_short_ticket_fails_the_grid_life_check(self):
        """The gate is REMAINING life, not validity."""
        problem = ct.check_kerberos(
            ct.GRID_TICKET_SECONDS, klist_text=lambda: KLIST_OK,
            now=lambda: self.expiry - 3600)
        self.assertIsNotNone(problem)
        self.assertIn("4 h left", problem)

    def test_unparseable_expiry_does_not_block_a_launch(self):
        """klist's stamp is locale-dependent; refusing to launch over a date
        format would be worse than the risk the gate guards."""
        odd = KLIST_OK.replace("01/02/2030 13:35:19", "2030-01-02T13:35:19")
        self.assertIsNone(ct.check_kerberos(ct.GRID_TICKET_SECONDS,
                                            klist_text=lambda: odd))

    def test_two_digit_year_parses(self):
        self.assertEqual(ct._parse_klist_time("01/02/30 13:35:19"),
                         self.expiry)

    def test_grid_seconds_is_four_hours(self):
        self.assertEqual(ct.GRID_TICKET_SECONDS, 4 * 3600)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract.TestKerberos -v`
Expected: 8 errors, `AttributeError: module 'contract' has no attribute '_parse_klist_time'`.

- [ ] **Step 3: Move the code.**

In `core/contract.py`, add `import subprocess` and `from datetime import datetime` to the stdlib imports. `time` is already imported. Then, directly after the `requires_kerberos` function, add this block:

```python
# A grid launch submits steps for HOURS, not once at the start, so validity
# now is not enough -- the ticket has to outlive the run (moved from the
# pipeline's core/launch_checks.py in Phase C3).
GRID_TICKET_SECONDS = 4 * 3600


def _klist_text() -> Optional[str]:
    """Raw `klist` output, or None when there is no usable ticket cache."""
    try:
        p = subprocess.run(["klist"], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _parse_klist_time(stamp: str) -> Optional[int]:
    """klist's local-time stamp as an epoch, or None if it does not parse.
    Both a 4- and 2-digit year are in the wild."""
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return int(datetime.strptime(stamp, fmt).timestamp())
        except ValueError:
            continue
    return None


def check_kerberos(min_seconds: int, *, klist_text=_klist_text,
                   now=time.time) -> Optional[str]:
    """Ticket present, and with `min_seconds` of life left.

    A ticket that expires mid-run kills the run at the next submit
    (wiki/incidents/kerberos-mid-run-expiry.md), and the prodtools input
    gate reports the resulting auth failure as "absent from dCache tape" --
    which reads as missing data, sending you to look at SAM instead of at
    your ticket.
    """
    text = klist_text()
    if not text:
        return "no valid Kerberos ticket -- run kinit first."
    krbtgt = [ln for ln in text.splitlines() if "krbtgt" in ln]
    if not krbtgt:
        return "no valid Kerberos ticket -- run kinit first."
    if min_seconds <= 0:
        return None
    # `MM/DD/YYYY HH:MM:SS  MM/DD/YYYY HH:MM:SS  krbtgt/...`: fields 3+4 are
    # the expiry. An unparseable line is NOT fatal -- klist's format is
    # locale-dependent, and refusing to launch over a date format would be
    # worse than the risk it guards.
    fields = krbtgt[0].split()
    if len(fields) < 4:
        return None
    expiry = _parse_klist_time(f"{fields[2]} {fields[3]}")
    if expiry is None:
        return None
    left = expiry - int(now())
    if left < min_seconds:
        return (f"Kerberos ticket has under {min_seconds // 3600} h left "
                f"({left // 60} min) -- a chain submits stages for hours and "
                f"will die at a later submit. Run 'kinit' before launching.")
    return None
```

In `core/launch_checks.py`, delete the definitions of `GRID_TICKET_SECONDS`, `_klist_text`, `_parse_klist_time` and `check_kerberos`, and the comment above `GRID_TICKET_SECONDS`. Keep `QUOTA_ABORT_PCT`. In their place, after the `import paths` line, add:

```python
# Moved to core/contract.py in Phase C3 (the engine's launch gate); this
# module is deleted with the pipeline.
from contract import (GRID_TICKET_SECONDS, _klist_text,  # noqa: E402,F401
                      _parse_klist_time, check_kerberos)
```

Remove any `datetime` import that is now unused in `launch_checks.py`. Keep `time` if still used there, and check with `grep -n "time\." core/launch_checks.py`.

In `graph/study_run.py`, change the contract import to:

```python
from contract import (ContractError, EXECUTORS, GRID_TICKET_SECONDS,  # noqa: E402
                      KitSet, check_kerberos, executor_problems,
                      kit_step_problems, requires_kerberos)
```

and `_kerberos` to:

```python
def _kerberos():
    return check_kerberos(GRID_TICKET_SECONDS)
```

In `tests/test_launch_checks.py`, delete `KLIST_OK`, `EXPIRY` and `class TestKerberos` (the tests now live in `test_contract.py`).

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract tests.test_launch_checks tests.test_study_run -v 2>&1 | tail -5`
Expected: `OK`.

Then run the full suite. Expected: `OK (skipped=3)`, with the same count as before; eight tests moved.

- [ ] **Step 5: Commit**

```bash
git add core/contract.py core/launch_checks.py graph/study_run.py tests/test_contract.py tests/test_launch_checks.py
git commit -F - <<'EOF'
contract: the Kerberos launch gate moves in from launch_checks

The engine's grid-launch check (4 h of ticket) now lives next to
requires_kerberos, so graph/study_run.py no longer imports the
pipeline's launch_checks module, which Phase C3 deletes. launch_checks
re-exports the names until then.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 2: The cut: archive the originals and delete the pipeline

One commit, green at its end. Deleting the pipeline breaks its fallbacks inside
shared modules, so the deletions, the shared-module edits and the test trims
land together.

**Files:**
- Move: `mode_specs/{foilsflash,foilspf,foilspf2k,foilspfbp,foilspfbpx,foilspfbpz,foilspfbw}.json` go to `mode_specs/archive/`.
- Delete, source:
  - `core/pipeline.py`, `core/harvest.py`, `core/bo_driver.py`, `core/study_compat.py`;
  - `core/prodtools_exec.py`, `core/prodtools_submit_driver.py`, `core/runtime.py`, `core/launch_checks.py`;
  - `graph/run.py`, `graph/closed_loop.py`, `graph/nodes.py`, `graph/pipeline_io.py`, `graph/state.py`, `graph/build.py`;
  - `tools/run_grid.sh`, `tools/run_local.sh`, `tools/c2b_parity.py` (and `tools/` if it is then empty).
- Delete, tests:
  - `test_closed_loop.py`, `test_foilspf_spec.py`, `test_geom_golden_parity.py`, `test_golden_parity_harness.py`;
  - `test_harvest.py`, `test_json_mode.py`, `test_nodes.py`, `test_no_mock_mode.py`;
  - `test_pipeline_verbs.py`, `test_seam_protocol.py`, `test_stages_retired.py`, `test_prodtools_exec.py`;
  - `test_launch_checks.py`, `test_mode_archive.py`, `test_c2b_parity.py`, `test_runtime_constants.py`, `test_study_compat.py`;
  - `tests/golden_parity.py`, `tests/fixtures/modes/`, `tests/fixtures/golden_geom/`, `tests/goldens/`.
- Modify: `core/modes.py` (rewrite), `core/kit_registry.py`, `core/botorch_predict.py`, `graph/pool.py`, `graph/study_run.py`, `graph/study_loop.py`, `core/paths.py`.
- Modify (docstrings only): `core/adapters/prodtools_entry.py`, `core/adapters/preflight_checks.py`, `graph/__init__.py`.
- Modify, tests:
  - `test_botorch_predict.py`, `test_surrogate.py`, `test_modes.py`, `test_study_engine.py`;
  - `test_c2b_studies.py`, `test_kit_config.py`, `test_contract.py`, `test_generic_core.py`;
  - `test_flock.py`, `test_pool.py`, `test_audit_fixes.py`, `test_paths.py`;
  - `test_activate.py`, `test_boards.py`, `test_leaderboard.py`, `test_preflight_checks.py`;
  - `test_zero_overlap_policy.py`, `test_recursion_limit.py`, `test_live_leaderboard_headers.py`, `test_no_hardcoded_paths.py`.

**Interfaces:**
- Consumes: `contract.check_kerberos`, `contract.GRID_TICKET_SECONDS` (Task 1).
- Produces: `modes.STUDIES: Dict[str, Study]`, `modes.PICKER_CHOICES`, `modes.DEFAULT_PICKER`, `modes.MODES_DIR`, and nothing else in `core/modes.py`.
- Produces: `botorch_predict.history_points(name) -> list[Point]`, which always goes through `boards.board_for(modes.STUDIES[name]).load()`.
- Produces: `pool.run_rolling(mode, picker, q, max_evals, name_prefix, *, run_child, next_pick, row_landed, broken, stagger, stop_flag=None, renew=None, log=print, heartbeat=HEARTBEAT_S)`.
  - `run_child`, `next_pick`, `row_landed`, `broken` and `stagger` are required.
  - `alpha` is gone.
- Produces: `kit_registry.KitDecl` without the `engine` and `pipeline` fields.

- [ ] **Step 1: Write the new failing tests** (Review Focus 3 and 4).

In `tests/test_modes.py`, add (the file is rewritten in Step 9; add this class now so it runs red first):

```python
class TestStaleModeEnv(unittest.TestCase):
    def test_a_stale_autoresearch_mode_is_ignored(self):
        """AUTORESEARCH_MODE was the pipeline's mode switch. After Phase C3
        nothing reads it: a leftover export in the operator's shell must
        not break an import, whatever it names."""
        env = dict(os.environ, AUTORESEARCH_MODE="no_such_mode_c3",
                   PYTHONPATH="")
        code = ("import sys; sys.path.insert(0, 'core'); sys.path.insert(0, 'graph'); "
                "import modes, botorch_predict, study_run, study_loop; print('ok')")
        p = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertIn("ok", p.stdout)
```

`ROOT` is the repo root; define `ROOT = Path(__file__).resolve().parent.parent` at module level if the file does not have it.

In `tests/test_botorch_predict.py`, add:

```python
class TestMissingBoard(unittest.TestCase):
    def test_a_study_with_no_board_file_has_empty_history(self):
        """Six of the seven _ax studies have no board yet; neither the live
        nor the archive file exists. That is an empty history, not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.tsv"
            with mock.patch.object(
                    bp.boards, "board_for",
                    lambda s: Leaderboard.for_study(s, path=missing,
                                                    archive_path=None)):
                self.assertEqual(bp.history_points(STUDY), [])
                X, Y, _, _ = bp.load_history_tensor(STUDY)
        self.assertEqual(X.shape[0], 0)
        self.assertEqual(Y.shape[0], 0)
```

This needs Step 9's fixture changes (`STUDY`, `Leaderboard`), so it is written now and run after Step 9.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_modes.TestStaleModeEnv -v`
Expected: FAIL. Importing `botorch_predict` imports `bo_driver`, which imports `runtime`, which calls `resolve_env_mode()`: `SystemExit` "unknown AUTORESEARCH_MODE".

- [ ] **Step 2: Archive the originals**

```bash
for s in foilsflash foilspf foilspf2k foilspfbp foilspfbpx foilspfbpz foilspfbw; do git mv mode_specs/$s.json mode_specs/archive/$s.json; done
```

Their boards `leaderboards/leaderboard_bo_<name>.tsv` stay where they are.

- [ ] **Step 3: Look, then delete the pipeline files.**

Read each file in the Files "Delete" lists. For each test file, write one line in the report file:
- `<file>: <n> tests, all of deleted code`; or
- `<file>: kept <test> by moving it to <surviving file>, because it tests <surviving behaviour>`.

The expected answer for every file is "all of deleted code". The one known exception, the Kerberos tests, already moved in Task 1. If a test does exercise surviving engine code, move it to that code's test file, with the imports rewritten to the surviving module, before deleting.

```bash
git rm core/pipeline.py core/harvest.py core/bo_driver.py core/study_compat.py core/prodtools_exec.py core/prodtools_submit_driver.py core/runtime.py core/launch_checks.py
git rm graph/run.py graph/closed_loop.py graph/nodes.py graph/pipeline_io.py graph/state.py graph/build.py
git rm tools/run_grid.sh tools/run_local.sh tools/c2b_parity.py
git rm tests/test_closed_loop.py tests/test_foilspf_spec.py tests/test_geom_golden_parity.py tests/test_golden_parity_harness.py tests/test_harvest.py tests/test_json_mode.py tests/test_nodes.py tests/test_no_mock_mode.py tests/test_pipeline_verbs.py tests/test_seam_protocol.py tests/test_stages_retired.py tests/test_prodtools_exec.py tests/test_launch_checks.py tests/test_mode_archive.py tests/test_c2b_parity.py tests/test_runtime_constants.py tests/test_study_compat.py tests/golden_parity.py
git rm -r tests/fixtures/modes tests/fixtures/golden_geom tests/goldens
```

Before the last `git rm -r`, check that no surviving test reads those directories: `grep -rn "fixtures/modes\|golden_geom\|goldens" tests/*.py`. Only files already deleted may match. Afterwards `ls tools/`: remove the directory only if it is empty (`rmdir tools`).

- [ ] **Step 4: Rewrite `core/modes.py`** with exactly this content:

```python
"""The study registry: every schema-2 study file under mode_specs/ (plus the
directories in AUTORESEARCH_STUDY_PATH), loaded once by core/study.py, and
the batch pickers. mode_specs/archive/ is not loaded: it holds retired and
archived studies (the seven original foilspf studies since Phase C3).
"""
from __future__ import annotations

import os
from pathlib import Path

# THE IMPORT MIRRORS OUR OWN PACKAGE-QUALIFICATION (__package__): this
# module loads as `core.modes` from the repo root AND as bare `modes` from
# code that puts core/ on sys.path. A hardcoded qualified import fails
# outright on the bare path; a hardcoded bare import would, on the
# qualified path, load study.py a SECOND time under a different
# sys.modules key.
if __package__:
    from core.study import load_study_dirs  # noqa: E402
else:
    from study import load_study_dirs  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
STUDIES = load_study_dirs(MODES_DIR, os.environ.get("AUTORESEARCH_STUDY_PATH"))

# The batch pickers, declared once: graph/study_loop.py validates --picker
# and core/botorch_predict.py dispatches on it. cl_min retired per ADR-0001.
PICKER_CHOICES = ("qnehvi", "qlnei", "budget_sob", "hybrid")
DEFAULT_PICKER = "hybrid"
```

- [ ] **Step 5: Trim `core/kit_registry.py`**
- Delete the `engine` and `pipeline` fields, and their comments, from `class KitDecl`.
- Delete the `KitDecl("ce_sensitivity", ...)` and `KitDecl("flash_edep_per_pot", ...)` entries.
- Remove `engine=True, pipeline=True` / `engine=True, pipeline=False` from the three remaining `KitDecl(...)` calls, and from the native-kit construction at the old line 231 (`return KitDecl(cfg.name, ...)`).
- `grep -n "engine\|pipeline" core/kit_registry.py` afterwards. Any remaining mention must describe something that still exists.

- [ ] **Step 6: Cut `core/botorch_predict.py` loose from `bo_driver`**
- Replace lines 1-7 (the module docstring) with:
  ```python
  #!/usr/bin/env python3
  """BoTorch pickers for any study (objectives, transforms and the constraint
  from modes.STUDIES): graph/study_loop.py and the surrogate MCP
  (surrogate/adapter.py) call compute_explore_picks / load_history_tensor /
  build_problem. Pickers: qnehvi, qlnei, budget_sob, hybrid -- see
  compute_explore_picks.
  """
  ```
- Delete line 20, `import bo_driver as bo  # noqa: E402`. Keep the `sys.path.insert` above it, which `import modes` needs.
- Replace `history_points` with:
  ```python
  def history_points(name: str):
      """A study's evaluated points: its live board under DATA_ROOT plus the
      committed archive (core/boards.py). A study with neither file has an
      empty history."""
      return boards.board_for(_modes.STUDIES[name]).load()
  ```
- Delete `def main(...)` and the `if __name__ == "__main__":` block at the end.
- Remove imports that are now unused. Check each of `argparse`, `json` and `os` with `grep -n "argparse\.\|json\.\|os\." core/botorch_predict.py`.

- [ ] **Step 7: Strip `graph/pool.py`'s pipeline defaults**
- Change the module docstring's sentence `*_cluster.txt survives only as `_name_busy_reason`'s LAUNCH-time double-launch guard.` to `*_cluster.txt survives only as the runner's LAUNCH-time double-launch guard (graph/study_loop.py busy_reason).`
- Replace the `run_rolling` signature and its fallback lines with:
  ```python
  def run_rolling(mode, picker, q, max_evals, name_prefix, *, run_child,
                  next_pick, row_landed, broken, stagger, stop_flag=None,
                  renew=None, log=print, heartbeat=HEARTBEAT_S):
      """Keep q children in flight until max_evals launched and the pool drains.

      Returns {"launched", "rows", "outcomes", "aborted"}. `stagger` separates
      launches: concurrent mu2ejobsub within ~10s races
      (wiki/incidents/concurrent-token-contention.md measured 60-90s safe).
      `heartbeat` is REPORT-ONLY -- never resolves/abandons (_log_inflight).
      """
      stop_flag = stop_flag or (lambda: False)
      renew = renew or (lambda: None)
  ```
  The old `run_child = run_child or ...`, `next_pick = ...`, `row_landed = ...`, `broken = ...` and `if stagger is None: from runtime import ...` lines go. The rest of the body is unchanged. If the body uses `alpha`, stop and report.
- Delete the `# --- production defaults ---` section's pipeline functions: `_default_run_child`, `_pending_names`, `_name_busy_reason`, `_default_pick_source`, `_default_row_landed`, `_default_broken`.
- Keep `child_name` and `next_free_name`; `graph/study_loop.py` imports them.
- Remove imports that are now unused (`uuid`, and `subprocess`/`sys` if unused).

- [ ] **Step 8: The runner and the loop drop their pipeline gates.**

In `graph/study_run.py`, delete these lines:

```python
    if args.study not in _modes.ENGINE:
        return refuse(f"study {args.study!r} runs on the pipeline kits; use "
                      f"graph.run / graph.closed_loop until Phase C")
```

In `graph/study_loop.py`:
- Delete the `if args.study not in _modes.ENGINE:` block (4 lines).
- Remove `alpha=None, ` from the `run_rolling(...)` call.
- Change `make_pick_source`'s docstring tail `returns one x; the board is read once per process, like the pipeline's pick source (graph/pool.py::_default_pick_source).` to `returns one x; the board is read once per process.`

In `core/paths.py`:
- Delete every public name whose only users were deleted. Check each with `grep -rnw <name> core graph surrogate tests --include=*.py`. The expected candidates are `BO_WORK` and `prodtools_root`, and anything used only by them.
- Update any docstring that names `pipeline.py`, `harvest`, `bo_driver` or `modes.SPECS` (around old lines 150-185) to describe the surviving callers. Find those callers with `grep -rn "paths.verify\|verify(" core graph`.

In `core/adapters/prodtools_entry.py`, `core/adapters/preflight_checks.py` and `graph/__init__.py`, rewrite docstring sentences that say "until Phase C3 deletes it" or name the deleted pipeline, so they describe today's callers only. There are no code changes in these three files.

- [ ] **Step 9: Trim the shared tests.**

The rule for every file below: a test whose subject was deleted goes. A test of surviving code that reached it through a deleted module is rewritten to import the surviving module directly. A file with nothing left is deleted with `git rm`. List every deleted or rewritten test in the report, with one reason each. Specific changes:

`tests/test_botorch_predict.py`:
- Delete `import bo_driver as bo`.
- Add `from leaderboard import Leaderboard, Point`.
- Replace `HEADER`, `write_fixture`, `patched_leaderboard`, `BOUNDS_LO` and `BOUNDS_HI` with:
  ```python
  # The engine twin of the old foilsflash study: same knobs and objectives.
  STUDY = "foilsflash_ax"


  def _board(path: Path) -> Leaderboard:
      return Leaderboard.for_study(bp._modes.STUDIES[STUDY], path=path,
                                   archive_path=None)


  def write_fixture(path: Path, n: int = 10, header_only: bool = False):
      lb = _board(path)
      cols = lb.header().rstrip("\n").split("\t")
      lines = [lb.header()]
      for i in range(0 if header_only else n):
          u = i / max(1, n - 1)
          x = [50 + 200 * u, 250 - 200 * u, 0.002 + 0.9 * u, 0.9 - 0.8 * u,
               0.05 + 0.9 * u, 0.9 - 0.85 * u]
          vals = {"config": f"cfg{i:03d}",
                  **{k: f"{v:.6f}" for k, v in zip(lb.knob_names, x)},
                  "sob": f"{3.0 + 0.8 * u:.5f}",
                  "flash_edep": f"{1e-7 * (1 + 9 * u):.5e}"}
          lines.append("\t".join(vals.get(c, "0") for c in cols) + "\n")
      path.write_text("".join(lines))


  def patched_leaderboard(tmp: str, **kw):
      lb = Path(tmp) / f"leaderboard_bo_{STUDY}.tsv"
      write_fixture(lb, **kw)
      return mock.patch.object(bp.boards, "board_for",
                               lambda s: _board(lb))


  BOUNDS_LO = list(bp._modes.STUDIES[STUDY].bounds_lo)
  BOUNDS_HI = list(bp._modes.STUDIES[STUDY].bounds_hi)
  ```
- Replace every `"foilsflash"` study argument with `STUDY`.
- Replace `bo.Point(` with `Point(`.
- Replace `mock.patch.object(bo.MODES["foilsflash"], "load_history", return_value=...)` with `mock.patch.object(bp, "history_points", return_value=...)`, keeping the same return value.
- Delete the tests that call `bp.main(...)` or `bo.botorch_ask(...)`; both are deleted code.
- Update the module docstring: fixtures patch `botorch_predict.boards.board_for` to read a tmp v2 board for `foilsflash_ax`.

`tests/test_surrogate.py`:
- Import `STUDY` alongside `patched_leaderboard` from `tests.test_botorch_predict`.
- Replace the `"foilsflash"` study names with `STUDY`.
- Rewrite the docstring's `bo.MODES[...]` sentence the same way.

`tests/test_modes.py`:
- Keep `TestStaleModeEnv` (Step 1).
- Keep tests of `STUDIES` loading, of `PICKER_CHOICES`/`DEFAULT_PICKER`, and the subprocess bare-import test (adapt it: bare `import modes` must work).
- Delete every test of `SPECS`, `ModeSpec`, `DEFAULT_MODE`, `resolve_env_mode`, `stamp_mode_from_argv`, `assert_mode_stamped`, `runtime`, `pipeline`, `bo_driver`, `closed_loop` or `study_compat`.
- Add:
  ```python
  class TestRegistry(unittest.TestCase):
      def test_the_live_studies_are_the_seven_engine_twins(self):
          import modes
          live = {n for n in modes.STUDIES if not n.startswith("_")}
          self.assertTrue({"foilsflash_ax", "foilspf_ax", "foilspf2k_ax",
                           "foilspfbp_ax", "foilspfbpx_ax", "foilspfbpz_ax",
                           "foilspfbw_ax"} <= live)
          self.assertFalse({"foilsflash", "foilspf", "foilspf2k", "foilspfbp",
                            "foilspfbpx", "foilspfbpz", "foilspfbw"} & live,
                           "the originals are archived, not loaded")
  ```
  Adjust the `live` set if `AUTORESEARCH_STUDY_PATH` fixtures are loaded in the test process; the assertion is on the two named sets.

`tests/test_study_engine.py`:
- Delete the tests of `modes.runs_on_engine`, `modes.ENGINE`, `modes.SPECS` and `study_compat`: `test_compat_refuses_a_v2_board`, the "no single runner" test, `test_a_study_both_runners_can_drive_runs_on_the_engine`, and any other test using those names.
- Update the study-name list assertion (old lines ~203-209) to the names now loaded: the originals are gone, the `_ax` twins and the fixtures stay.

`tests/test_c2b_studies.py`:
- Delete the class comparing each twin against its original (`mode_specs/<name>.json`).
- Keep `TestFixtures`.
- Replace remaining `modes.ENGINE`/`SPECS` checks with `modes.STUDIES`.

`tests/test_kit_config.py`:
- Delete `test_pipeline_kits_are_not_engine_kits` and `test_the_pre_check_kit_runs_on_both_runners`.
- In `test_native_kits_are_engine_kits`, delete `self.assertTrue(decl.engine)`.

`tests/test_contract.py`: remove `engine=`/`pipeline=` from the `KitDecl(...)` built near old line 264.

`tests/test_generic_core.py`:
- Remove `core/bo_driver.py` and any other deleted file from the `USAGE`/`STRICT` lists.
- Fix the needle list near old line 44 that names `KitDecl("flash_edep_per_pot", ...)`: drop that entry.

`tests/test_flock.py`: import the lock helpers from `leaderboard` (`_flock_ex`, `_flock_sh`, `_lock_path`) instead of through `bo_driver`.

`tests/test_pool.py`:
- Remove `alpha=1.0` from every `run_rolling(...)` call, and pass `stagger=0` where a call relied on the default.
- Delete `test_default_stagger_comes_from_config`.
- Delete the busy-name class testing `_default_pick_source`/`_name_busy_reason`/`_pending_names` (old line ~319 onward).
- Fix the header comments that describe `closed_loop`/`runtime`/`_default_*`.
- Every remaining call must pass `run_child`, `next_pick`, `row_landed`, `broken` and `stagger`.

The remaining files follow the rule, with `grep -n "bo_driver\|pipeline\|harvest\|runtime\|study_compat\|launch_checks\|prodtools_exec\|closed_loop\|graph.run\|nodes\|SPECS\|ENGINE" tests/<file>.py` to find the spots:
- `test_audit_fixes.py`, `test_paths.py`, `test_activate.py`, `test_boards.py`;
- `test_leaderboard.py`, `test_preflight_checks.py`, `test_zero_overlap_policy.py`;
- `test_recursion_limit.py`: it pins the deleted pipeline's `.stream()` call. If nothing else is left in it, delete the file;
- `test_live_leaderboard_headers.py`: it checks live board headers against studies. It now covers the `_ax` studies only, and the archived boards are not checked;
- `test_no_hardcoded_paths.py`.

Run `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_modes tests.test_botorch_predict -v 2>&1 | tail -5`.
Expected: `OK`. `TestStaleModeEnv` and `TestMissingBoard` now pass.

- [ ] **Step 10: Grep gate** (spec acceptance 2):

```bash
grep -rnE "import (bo_driver|pipeline|harvest|runtime|study_compat|launch_checks|prodtools_exec|nodes|pipeline_io|build|state)\b|from (bo_driver|pipeline|harvest|runtime|study_compat|launch_checks|prodtools_exec|nodes|pipeline_io|build|state) import" core graph surrogate tests --include=*.py
grep -rnE "\bSPECS\b|ModeSpec|\bbo_driver\b|AUTORESEARCH_MODE" core graph surrogate tests kits.toml activate.sh setup.sh --include=* | grep -v "tests/test_modes.py.*AUTORESEARCH_MODE"
```

Expected: the first prints nothing. The second prints nothing except `test_modes.py`'s `TestStaleModeEnv`. `graph/study_graph.py` and `core/scheduler.py` may import a LangGraph `StateGraph` or `state` object. Read any hit before deciding whether it is a real import of a deleted module.

- [ ] **Step 11: Unchanged measurement.** Run the `measure_basis_sha` check from Global Constraints. All seven values must be identical.

- [ ] **Step 12: Full suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t . 2>&1 | tail -4`
Expected: `OK (skipped=N)`. Record the test count in the report (it drops from 1128).

- [ ] **Step 13: Commit.** Stage only the paths this task touched: the `git mv`/`git rm` paths are already staged, then `git add` each modified file by name.

```bash
git add core/modes.py core/kit_registry.py core/botorch_predict.py core/paths.py graph/pool.py graph/study_run.py graph/study_loop.py graph/__init__.py core/adapters/prodtools_entry.py core/adapters/preflight_checks.py tests/<each modified test file>
git status --short | grep -v "^ M docs/\|^?? docs/"   # nothing unstaged outside the operator's docs/
git commit -F - <<'EOF'
delete the old pipeline; archive the seven original foilspf studies

The contract engine is now the only runner. Gone: core/pipeline.py,
harvest.py, bo_driver.py, study_compat.py, prodtools_exec.py,
prodtools_submit_driver.py, runtime.py, launch_checks.py; graph/run.py,
closed_loop.py, nodes.py, pipeline_io.py, state.py, build.py; the
tools/ launchers and the C2b parity tool; the pipeline-only tests and
goldens. The seven original foilspf studies move to mode_specs/archive/
(unloaded); their v1 boards stay in leaderboards/ as files.

Shared modules lose their pipeline fallbacks: modes.py keeps STUDIES
and the pickers; KitDecl loses engine/pipeline and the two pipeline-only
kits; botorch_predict reads every board through core/boards.py; pool's
run_rolling requires its callables and stagger. The _ax studies'
measure_basis_sha values are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 3: The renames `graph.study_run` → `graph.run`, `graph.study_loop` → `graph.closed_loop`

**Files:**
- Move: `graph/study_run.py` → `graph/run.py`; `graph/study_loop.py` → `graph/closed_loop.py`.
- Move: `tests/test_study_run.py` → `tests/test_run.py`; `tests/test_study_loop.py` → `tests/test_closed_loop.py`.
- Modify: every code or test reference; find them with `grep -rn "study_run\|study_loop" core graph surrogate tests kits.toml`.

**Interfaces:**
- Consumes: Task 2's tree.
- Produces: `python -m graph.run` (the one-point runner, same flags as before) and `python -m graph.closed_loop` (the campaign loop, same flags).
- Produces: log and refusal prefixes `[run]` and `[closed_loop]`.
- Produces: the bare modules `run` and `closed_loop` on the `graph/` path.

- [ ] **Step 1: Write the failing tests** (Review Focus 1, 2, 5). In `tests/test_study_run.py`, still at its old path, add:

```python
class TestOldAndArchivedShapes(unittest.TestCase):
    def test_the_old_pipeline_command_shape_is_refused(self):
        """The pipeline's `graph.run --mode foilspf --x-point ...` must fail
        loudly at argparse, not start anything."""
        with self.assertRaises(SystemExit) as cm, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            study_run.main(["--mode", "foilspf", "--x-point", "1,2,3"])
        self.assertEqual(cm.exception.code, 2)

    def test_an_archived_study_is_unknown_with_a_hint(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = study_run.main(["--study", "foilspf", "--config", "c3x01",
                              "--campaign", "c3x", "--x=1"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown study 'foilspf'", out.getvalue())
        self.assertIn("mode_specs/archive/", out.getvalue())
```

The file already has `import study_run` and `import io`. In `tests/test_study_loop.py`, which has `import paths` and `import study_loop`, add:

```python
class TestRenamedHints(unittest.TestCase):
    def test_busy_hint_names_the_renamed_runner(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(paths, "GRID_DATA_ROOT", Path(tmp)):
            sd = Path(tmp) / "c3R00_00" / "state"
            sd.mkdir(parents=True)
            (sd / "point.json").write_text("{}")
            why = study_loop.busy_reason("c3R00_00", set())
        self.assertIn("pgrep -f 'graph.run.*c3R00_00'", why)

    def test_an_archived_study_is_unknown_with_a_hint(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = study_loop.main(["--study", "foilspf", "--q", "1",
                                  "--max-evals", "1", "--name-prefix", "c3x"])
        self.assertEqual(rc, 2)
        self.assertIn("mode_specs/archive/", out.getvalue())
```

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_run.TestOldAndArchivedShapes tests.test_study_loop.TestRenamedHints -v`
Expected:
- the old-shape test PASSES already (argparse refuses unknown required flags);
- the two archived-study tests FAIL, because the message has no `mode_specs/archive/` hint;
- the busy-hint test FAILS, because the message says `study_run.*`.

- [ ] **Step 2: Rename the files**

```bash
git mv graph/study_run.py graph/run.py
git mv graph/study_loop.py graph/closed_loop.py
git mv tests/test_study_run.py tests/test_run.py
git mv tests/test_study_loop.py tests/test_closed_loop.py
```

- [ ] **Step 3: Update the references.**

In `graph/run.py`:
- The docstring commands become `python -m graph.run ...`.
- Delete the sentence `Phase C renames this to graph.run when the pipeline path is deleted.`
- `graph/study_loop.py` in the docstring becomes `graph/closed_loop.py`.
- `refuse()` prints `[run] REFUSED: `.
- The unknown-study refusal becomes:
  ```python
  if args.study not in _modes.STUDIES:
      return refuse(f"unknown study {args.study!r}; known "
                    f"{sorted(_modes.STUDIES)} (studies under "
                    f"mode_specs/archive/ are not loaded)")
  ```

In `graph/closed_loop.py`:
- The docstring's `graph.study_run` becomes `graph.run` and `python -m graph.study_loop` becomes `python -m graph.closed_loop`.
- Delete the sentence `Phase C folds this into graph/closed_loop.py when the pipeline path is deleted.`
- `from study_run import launch_refusals, parse_context` becomes `from run import launch_refusals, parse_context`.
- The `"-m", "graph.study_run"` in `make_run_child` becomes `"-m", "graph.run"`, and its docstring `Popen `graph.study_run`` becomes `Popen `graph.run``.
- The busy hint `pgrep -f 'study_run.*{name}'` becomes `pgrep -f 'graph.run.*{name}'`.
- Every `[study_loop]` prefix becomes `[closed_loop]`.
- The unknown-study refusal gets the same `(studies under mode_specs/archive/ are not loaded)` tail.
- The no-knobs refusal's `run graph.study_run` becomes `run graph.run`.

Then run `grep -rn "study_run\|study_loop" core graph surrogate tests kits.toml` and update every remaining hit:
- imports in tests (`import study_run` becomes `import run`, `import study_loop` becomes `import closed_loop`, and every `study_run.`/`study_loop.` use becomes `run.`/`closed_loop.`);
- `mock.patch.object(study_run, ...)` targets;
- asserted strings `[study_run]`/`[study_loop]`;
- `tests/test_generic_core.py`'s `STRICT` file list (`graph/study_run.py` becomes `graph/run.py`, `graph/study_loop.py` becomes `graph/closed_loop.py`);
- comments in `core/kit_registry.py`, `core/contract.py` and `core/modes.py`.

Expected afterwards: the grep prints nothing.

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_run tests.test_closed_loop -v 2>&1 | tail -5`
Expected: `OK`, including the four new tests.

Then run the `measure_basis_sha` check (Global Constraints): unchanged. Then the full suite: `OK`, with the count from Task 2 plus 4.

- [ ] **Step 5: Commit**

```bash
git add graph/run.py graph/closed_loop.py tests/test_run.py tests/test_closed_loop.py <each other modified file by name>
git commit -F - <<'EOF'
rename graph.study_run -> graph.run, graph.study_loop -> graph.closed_loop

With the pipeline gone the engine takes the standard names (generic-study
design, "Phase C renames them"). Log/refusal prefixes follow ([run],
[closed_loop]); an unknown study now says mode_specs/archive/ is not
loaded, and the busy-name hint names graph.run.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 4: Repo documentation, wiki and repo commands

**Files:**
- Modify: `README.md` (rewrite), `CONTEXT.md`, `mode_specs/README.md`.
- Modify, wiki:
  - `wiki/drivers/contract-engine.md`, `wiki/drivers/tests.md`;
  - `wiki/drivers/{pipeline,graph-runner,closed-loop-runner,bo-driver,preflight,local-executor}.md`;
  - `wiki/index.md`, `wiki/log.md`.
- Modify: `.claude/commands/closed-loop-harvest.md`, `.claude/commands/closed-loop-status.md`.

**Interfaces:**
- Consumes: Tasks 2-3 (the command names, the deleted file list, the new test count from Task 3's full run).

- [ ] **Step 1: Read first:** `README.md`, `CONTEXT.md`, `mode_specs/README.md`, the two command files, each wiki page listed, and `wiki/CLAUDE.md` (the OKF page contract: frontmatter, `timestamp`, and the `log.md` newest-first rule).

- [ ] **Step 2: Rewrite `README.md` around the engine:**
- **What the project is:** a BO search over Mu2e geometry.
- **Setup:** `source activate.sh`; `AUTORESEARCH_PRODTOOLS`; `AUTORESEARCH_ANAKIT`; `kits.toml`.
- **Studies:** `mode_specs/*_ax.json`, one file per study. `mode_specs/archive/` is unloaded history.
- **One point:** `python -m graph.run --study foilspfbpz_ax --config <name> --campaign <name> --x=<v1,...,v10> --context alpha=100000.0 --executor grid|local [--parallel N]`.
- **A campaign:** `python -m graph.closed_loop --study <s> --q <n> --max-evals <n> --picker budget_sob --name-prefix <p> --context alpha=100000.0 --executor grid`. Stop it by touching `$GRAPH_DATA/<prefix>/STOP`.
- **Where things land:**
  - `<GRID_DATA_ROOT>/<config>/state/` (`point.json`, `<step>_cluster.txt`, `<step>_results.json`, `broken.txt`);
  - the v2 boards under `DATA_ROOT/autoresearch_leaderboards/`;
  - the child logs `GRAPH_DATA/closed_loop_logs/<config>.log`.
- **Tests:** the suite command.
- **Pointers:** `wiki/drivers/contract-engine.md` and the surrogate MCP.

Keep it under ~120 lines. Check every command against `python -m graph.run --help` and `python -m graph.closed_loop --help`.

- [ ] **Step 3: Update `CONTEXT.md`.** Rewrite the glossary entries that describe the pipeline/engine split (old lines ~13, 28, 31, 84, 101, 112) so they describe the engine only: `graph.run`, `graph.closed_loop`, `core/contract.py`, kits.
- Retire "ModeSpec" and "bo_driver.MODES" as current terms. Where the file keeps a history note, one line says they were deleted in Phase C3 (2026-09-28).

- [ ] **Step 4: Update `mode_specs/README.md`**
- Name the command shapes `graph.run` and `graph.closed_loop`.
- Add a short "archive/" section: what it holds (the four schema-1 ipa/nominal files; the seven original foilspf studies since C3, whose v1 boards stay in `leaderboards/`) and that nothing loads it.
- Remove text that describes pipeline-only behaviour.
- Keep the `desc_fmt` description: the key stays, per the spec ruling.

- [ ] **Step 5: Wiki.**

`contract-engine.md`:
- Bump `timestamp` to 2026-09-28.
- Update the frontmatter `description` and the index one-liner to mention C3.
- Replace the current-state command names (`graph.study_run`, `graph.study_loop`) with `graph.run` and `graph.closed_loop`. Leave dated historical bullets alone.
- Add a section **"Pipeline deleted (Phase C3)"** covering:
  - the spec path;
  - what was deleted;
  - the archive decision;
  - the three rulings (desc_fmt kept, `pipeline_templates/` kept, v1 code kept);
  - the unchanged `measure_basis_sha`;
  - "Acceptance: pending (local run + surrogate MCP)", which the controller fills in afterwards.
- Add the ported-launch-checks follow-up (quota, config-name-free, stale clusters) to its follow-ups list.

The six pipeline pages:
- Set `status: superseded` and `status_note: 'deleted in Phase C3 (2026-09-28); see contract-engine'`.
- Bump `timestamp`.
- Add one line at the top of the Summary pointing to [contract-engine](/drivers/contract-engine.md).
- Do not otherwise rewrite them; they are the record.

`tests.md`: the new file and test counts (from Task 3's full run); the golden parity harness line goes, since it was deleted.

`index.md`:
- Mark the six pages "(**deleted 2026-09-28**, Phase C3)" in their one-liners.
- Update the contract-engine and tests one-liners.

`log.md`: under the existing `## 2026-09-28` heading at the top, add bullets for each page changed.

Check the links: `grep -on "\](/[a-z-]*/[a-z0-9-]*\.md)" wiki/**/*.md`. Every link target must exist.

- [ ] **Step 6: Rewrite the two repo commands** for the engine:

`closed-loop-status.md` reports a running `graph.closed_loop` campaign:
- find it with `pgrep -f "graph.closed_loop.*<prefix>"`;
- per child, the latest `[steps]`/`[run]` lines of `GRAPH_DATA/closed_loop_logs/<child>.log` and the files in `<GRID_DATA_ROOT>/<child>/state/`;
- the grid queue via `jobsub_q`;
- new rows on the study's v2 board.

`closed-loop-harvest.md` is about landing or diagnosing a child's row:
- read `<step>_results.json` and `broken.txt`;
- a rerun of `graph.run` with the same `--config` adopts finished steps;
- delete `broken.txt` to retry.

Keep each command's frontmatter keys. Remove every reference to `bo_driver`, `pipeline.py`, `harvest`, `graph.run --mode` and pending TSVs.

- [ ] **Step 7: Commit**

```bash
git add README.md CONTEXT.md mode_specs/README.md wiki/drivers/contract-engine.md wiki/drivers/tests.md wiki/drivers/pipeline.md wiki/drivers/graph-runner.md wiki/drivers/closed-loop-runner.md wiki/drivers/bo-driver.md wiki/drivers/preflight.md wiki/drivers/local-executor.md wiki/index.md wiki/log.md .claude/commands/closed-loop-harvest.md .claude/commands/closed-loop-status.md
git commit -F - <<'EOF'
docs: the engine is the only runner (Phase C3)

README rewritten around graph.run / graph.closed_loop; CONTEXT.md and
mode_specs/README.md follow; the six pipeline wiki pages are marked
superseded; contract-engine gets the C3 section; the repo's
closed-loop-status/harvest commands now read the engine's state files
and v2 boards.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 5: The user-level skills

**Files (outside the repo, not in git; edit in place):**
- `~/.claude/skills/launch-bo-chain/SKILL.md`;
- `~/.claude/skills/more-jobs/SKILL.md`;
- `~/.claude/skills/autopsy/SKILL.md`;
- `~/.claude/skills/status/SKILL.md`.

**Interfaces:**
- Consumes: the command shapes from `README.md` (Task 4).

- [ ] **Step 1: Back up and read.** Copy each file to `/exp/mu2e/data/users/oksuzian/claude-scratch/c3-skill-backup/<skill>/SKILL.md` (create the directory), then read each in full.

- [ ] **Step 2: Rewrite each for the engine.** Keep each skill's frontmatter `name` and `description`, editing the description only where it names the pipeline. Keep its purpose and section structure.

- `launch-bo-chain`: launch one point with `python -m graph.run` (or a campaign with `graph.closed_loop`) under `setsid nohup`, log to `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/<name>.log`.
  - **Pre-launch checks:** Kerberos (the runner refuses a grid launch with under 4 h), a fresh config name, `AUTORESEARCH_PRODTOOLS` and `AUTORESEARCH_ANAKIT` exported.
  - **Monitoring:** the `[steps]` lines and the state files.
  - **Gotchas:**
    - resume by rerunning the same `--config` (it adopts `<step>_results.json`);
    - `broken.txt` must be deleted to retry;
    - pgrep matching your own shell: use `ps -fu $USER -ww | grep "[g]raph.run"`.
  - Drop `--thread-id`, `--mode`, `--x-point`, `--no-mock`, `pipeline.py` and template-edit A/B content.
- `more-jobs`: read it first and map each pipeline step to its engine equivalent, i.e. more events means a new config with changed `fixed` values in a study copy. If a step has no engine equivalent, say so in the skill instead of inventing one.
- `autopsy`: diagnose a failed engine point:
  - `broken.txt`, `<step>_results.json`, `<step>_cluster.txt`;
  - the child log's `[steps]` lines;
  - prodtools `run_status` via the handle `<config>.<step>`;
  - the anakit step directory `<GRID_DATA_ROOT>/<config>/anakit/<step>/` (`anakit_result.json`, `mu2e.log`).
- `status`: follow the repo command `closed-loop-status.md` (Task 4) for campaigns. Parents are `graph.closed_loop`/`graph.run`; boards are v2.

- [ ] **Step 3: Check.** `grep -n "bo_driver\|pipeline.py\|--mode\|--x-point\|thread-id\|harvest" ~/.claude/skills/{launch-bo-chain,more-jobs,autopsy,status}/SKILL.md` prints nothing, unless a line explicitly marks something as history.

Nothing to commit: these files are outside the repo. The report lists the four files and the backup path.

---

## Acceptance (the controller, after the final review)

1. The full suite is green at the branch tip.
2. The grep gate from Task 2 Step 10 is clean, and there is no `study_run`/`study_loop` in `core graph surrogate tests kits.toml`.
3. **Local run under the new name:**
   ```bash
   cd /exp/mu2e/app/users/oksuzian/autoresearch && source activate.sh
   export AUTORESEARCH_ANAKIT=/exp/mu2e/app/users/oksuzian/analysis-mcp-server AUTORESEARCH_PRODTOOLS=/exp/mu2e/app/users/oksuzian/muse_050125/prodtools
   export AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c3_sandbox/local AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies
   PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study foilspfbpz_local --config c3local01 --campaign c3local --x=99.6745,103.0623,116.9368,0.018037,0.071303,0.035832,0.0904,0.2627,0.3544,-37.1405 --context alpha=100000.0 --executor local --parallel 4
   ```
   Pass: the pre-check passes, all 5 steps complete, and one row lands in the sandbox board.
4. **Surrogate MCP:** start `surrogate/mcp_server.py` fresh (as `.mcp.json` does) and call `list_problems`. Pass: the seven `_ax` studies are listed, and no original is.
5. Record the acceptance in `wiki/drivers/contract-engine.md` (replace "Acceptance: pending") and `wiki/log.md`, then commit.
6. Update the memory: `project_pipeline_reference_only.md` (deleted in C3), `feedback_use_graph_runner.md` (`graph.run` is now the engine runner) and `MEMORY.md`.
