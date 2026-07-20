# Slimming Round (Shrink + Sweep) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the two designed shrink refactors — ChildTracker full-cut (`graph/closed_loop.py`) and harvest phase-2 runner seams (`core/pipeline.py`) — plus the audit's last hygiene items and the B0 follow-ups inherited from the tests round.

**Architecture:** Spec `docs/superpowers/specs/2026-07-19-slim-shrink-sweep-design.md` (+ its B0 section). Protection: the 196-test suite, the golden parity harness (`check a b c`), and a bit-identical golden re-harvest for the pipeline change. Sequencing: sweep → B0 batch → harvest seams → ChildTracker full-cut → shrink audit → records.

**Tech Stack:** Python 3.11 single `.venv`, stdlib `unittest` (NOT pytest), LangGraph closed loop, injected-runner/Signals seams.

## Global Constraints

- Suite command (green after EVERY commit; use PYTHONUNBUFFERED=1 when pasting evidence):
  `cd /exp/mu2e/app/users/oksuzian/autoresearch && PYTHONUNBUFFERED=1 PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v`
  Current count: 196. Report actual counts as they grow/shrink.
- Golden gate after every code commit: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b` → OK. (Section c re-runs a 3-min G4 preflight — only where a task says so.)
- **No campaign running** before ANY commit that touches `graph/` or `core/pipeline.py`: `ps -fu $USER -ww | grep "[c]losed_loop"` must be empty (plain pgrep false-positives on its own wrapper).
- Work directly in /exp/mu2e/app/users/oksuzian/autoresearch on branch `main`. NO git worktrees (untracked `.venv` symlink breaks there). Never `git push`. Stage named paths only. One named-path `rm` per Bash call (the auto-mode classifier blocks compound rm).
- TSV bytes under `leaderboards/` never change.
- Every commit message ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- Line numbers below are as of commit `480521d` — re-locate by content if drifted.

## Spec-reality amendments this plan encodes (record in Task 6's spec sweep)

1. **Spec commit ④ (streak/zero-rows move) DISSOLVED**: the name-based streak
   accounting already landed in `node_decide_next` (closed_loop.py:663-677,
   "fixes rolling-no-row-streak-false-increment") and is regression-pinned by
   `tests/test_closed_loop.py::TestRolling::test_decide_streak_immune_to_baseline_absorbed_row`.
   Moving it onto tracker Resolutions would add state plumbing with zero
   behavior win — not done, recorded instead.
2. **"Mock closed-loop round (q=2, --mock children)" verification is
   impossible as written**: closed_loop has only `--dry-run` (picker preview)
   and hardcodes `--no-mock` into child launches (closed_loop.py:458).
   Replacement verification = unit tests through the REAL node functions
   (existing pattern) + `graph.run --mock` single-chain smoke + live
   validation riding the next campaign (the barrier first-cut precedent).
3. **Run1BAna debris is 40 `config_bo*` dirs, not 3**: the spec's
   "config_bo000..002" undercounted. Same intent (our early-era BO debris);
   Task 1 verifies untracked status per-dir and sweeps exactly the
   `config_bo*` set. `config_v*`/`config_t*` are NOT touched (reported only).
4. **Root `.bak` sediment already gone**: `find -maxdepth 1 -name "*.bak*"`
   is empty; Task 1 verifies and reports zero.

---

### Task 1: Block B sweep (hygiene)

**Files:**
- Possibly modify or delete: `.claude/commands/closed-loop-status.md`
- Delete (untracked, outside our git): `Run1BAna/workflows/config_bo000` … `config_bo039`
- Possibly modify: any `.claude/` or tracked-docs file the orphan grep flags

**Interfaces:** none produced; read-only checks + deletions.

- [ ] **Step 1: Re-audit `.claude/commands/closed-loop-status.md`**

Read the file. Verify each concrete reference against today's reality:
leaderboard paths (`leaderboards/leaderboard_bo_foilsflash.tsv`), name
prefixes (foilsflash-era), any awk column indices (foilsflash rows are
`config + 6 knobs + sob flash_edep alpha obj` → sob=$8, flash=$9, obj=$11),
process-check recipes (must use the bracket-trick
`ps -fu $USER -ww | grep "[c]losed_loop"`), and log paths
(`/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/…`). Fix stale
references in place; if the whole command is redundant with the status
skill, note that in the report but do NOT delete without listing what only
it provides. Record the verdict either way.

- [ ] **Step 2: Run1BAna config_bo debris**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch/Run1BAna && git status --porcelain --ignored -- workflows/ | head -60
```
Confirm every `workflows/config_bo0NN/` is untracked/ignored in the NESTED
repo (they are our early-era driver output, `bo000..bo039`). Then delete
each with its own named call:
`rm -rf /exp/mu2e/app/users/oksuzian/autoresearch/Run1BAna/workflows/config_bo000`
… through `config_bo039` (40 calls). Do NOT touch `config_v*`, `config_t*`,
`fcl/`, `scripts/`, `src/`, `run1?_*`, `notes.org`, or the two
`run_config_v24_*.log` files — list them in the report as left-in-place.
If any `config_bo*` shows as TRACKED in the nested repo, skip it and report.

- [ ] **Step 3: Verify `.bak` sediment is zero**

`find /exp/mu2e/app/users/oksuzian/autoresearch -maxdepth 1 -name "*.bak*"` →
expect empty; report the (expected-zero) count.

- [ ] **Step 4: Orphan-reference grep**

```bash
grep -rn "skopt\|cl_min\|\.venv-graph\|\.venv-botorch\|pending/\|requirements-graph\|requirements-botorch" .claude/ docs/agents/ CONTEXT.md 2>/dev/null
```
For each hit, judge: live instruction (fix), historical narrative (leave),
or dead file (report). Expect few. Fix live ones in place.

- [ ] **Step 5: Suite + commit**

Full suite (196 OK — nothing here touches code; the run is the regression
tripwire). Stage exactly the files you edited (named paths). Commit:

```
chore: Block B sweep — status-command re-audit, Run1BAna config_bo debris (40 dirs), orphan refs

<one line per finding: verdicts, counts, what was left in place>
```
(+ the two trailer lines from Global Constraints.)

---

### Task 2: B0 code batch (inherited follow-ups)

**Files:**
- Modify: `core/bo_driver.py` (format_row tail guard; build_space dead guard),
  `core/modes.py` (`__post_init__` assert → raise), `tests/test_modes.py`
  (exception type), `graph/nodes.py` (comment + maybe cause string),
  `tests/test_flock.py`, `tests/test_seam_protocol.py`
- Test: the same test files

**Interfaces:**
- Produces: `ModeSpec.__post_init__` raises `ValueError` (not bare assert);
  `BOMode.format_row` raises `ValueError` on a non-4-column `metric_cols`
  tail. Later tasks rely on nothing else from here.

- [ ] **Step 1: `ModeSpec.__post_init__` assert → raise** (`core/modes.py`)

Replace the bare `assert (...)` block with:

```python
    def __post_init__(self):
        if self.bounds_lo is not None and not (
                len(self.knob_names) == len(self.knob_fmts)
                == len(self.bounds_lo)):
            raise ValueError(
                f"{self.name}: knob_names ({len(self.knob_names)}) / "
                f"knob_fmts ({len(self.knob_fmts)}) / bounds "
                f"({len(self.bounds_lo)}) lockstep broken")
```

In `tests/test_modes.py::TestSchemaFields.test_lockstep_enforced_at_construction`,
change `assertRaises(AssertionError)` → `assertRaises(ValueError)`.

- [ ] **Step 2: `format_row` tail guard** (`core/bo_driver.py`)

In `BOMode.format_row`, after `cols = _modes.SPECS[self.name].metric_cols`:

```python
        if len(cols) != 4:
            raise ValueError(
                f"{self.name}: BOMode.format_row writes a 4-column tail "
                f"(sob-like, calo-like, alpha, obj) but metric_cols is "
                f"{cols} — override format_row for this shape "
                f"(ProdTargetMode pattern)")
```

Add a test to `tests/test_modes.py::TestSchemaFields`:

```python
    def test_format_row_rejects_non4_metric_tail(self):
        import dataclasses
        import bo_driver as bo
        bad = dataclasses.replace(modes.SPECS["foils"],
                                  metric_cols=("sob", "calo", "obj"))
        with mock.patch.dict(modes.SPECS, {"foils": bad}):
            with self.assertRaises(ValueError):
                bo.MODES["foils"].format_row(
                    bo.Point(cfg="x", x=[0.0] * 6, sob=0.0, calo=1.0), 1.0)
```
(Add `from unittest import mock` to the file's imports if absent.)

- [ ] **Step 3: delete `build_space`'s dead guard** (`core/bo_driver.py`)

The `if len(self.KNOB_NAMES) != len(spec.bounds_lo): raise ValueError(...)`
block in `build_space` is dead by construction (KNOB_NAMES reads the same
spec entry whose `__post_init__` enforces lockstep). Delete it, leaving:
`# lockstep enforced at ModeSpec construction (modes.py __post_init__)`.

- [ ] **Step 4: two seam tests** (append to `tests/test_seam_protocol.py`)

```python
class TestSeamStaleAndFallback(unittest.TestCase):
    def test_stale_evaluate_result_not_reused(self):
        # Pre-seed a stale result; driver writes nothing, rc=1 → (None, tail)
        # and the stale obj must NOT be returned.
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "cfgX" / "state" / "evaluate_result.json"
            bo.write_json_atomic(stale, {"config": "cfgX", "obj": 9.9,
                                         "sob": 9.9, "calo_or_flash": 1e-9,
                                         "row_appended": True})
            with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
                 mock.patch.object(pio.subprocess, "run",
                                   side_effect=_fake_eval_run(None, rc=1)):
                obj, _ = pio.run_evaluate("foilsflash", "cfgX",
                                          {"s_over_sqrt_b": 1.0})
            self.assertIsNone(obj)

    def test_preflight_out_of_domain_rc_decodes_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(bo, "_cmd_preflight_impl", return_value=99):
            out = Path(tmp) / "preflight_verdict.json"
            rc = bo.cmd_preflight(SimpleNamespace(
                mode="foilsflash", config_name="cfgX", emit_json=str(out)))
            self.assertEqual(rc, 99)
            self.assertEqual(json.loads(out.read_text())["verdict"],
                             "ambiguous")
```

- [ ] **Step 5: flock follow-ups** (`tests/test_flock.py`)

Append to `test_ex_blocks_child_ex_until_released` after the existing
post-release EX check: `self.assertEqual(_child_try(lp, "sh"), 0)`.
Add one line to the module docstring: `Assumes tempfile.TemporaryDirectory
resolves to local /tmp — flock semantics weaken on NFS/Ceph mounts.`

- [ ] **Step 6: `graph/nodes.py` cosmetics**

(a) Point its preflight status-string comment at the single source: append
`(vocabulary: bo_driver.PREFLIGHT_VERDICTS + "timeout")` to the comment
near `node_render_preflight`.
(b) The `_record_zero_row` cause string `"obj_unparseable"` (nodes.py:265):
first `grep -rn "obj_unparseable" --include=*.py --include=*.md . wiki/`
— if consumers beyond prose exist, leave the string and add a comment
`# historical cause name; obj now arrives via evaluate_result.json`; if
only prose, rename to `"evaluate_no_row"` AND update every prose hit in
the same commit. Either way, record which path you took.

- [ ] **Step 7: verify + commit**

Focused: `tests.test_modes`, `tests.test_seam_protocol`, `tests.test_flock`
all green; then full suite (expect 196 + 3 new = 199; report actual);
`golden_parity.py check a b` OK (format_row byte-behavior unchanged for
valid specs). Commit:

```
refactor: B0 batch — lockstep raises, dead guard deleted, seam+flock tests, nodes cosmetics
```
(+ trailers.) `git add core/bo_driver.py core/modes.py graph/nodes.py tests/test_modes.py tests/test_seam_protocol.py tests/test_flock.py` (+ any prose files from 6b).

---

### Task 3: A2 — harvest phase-2 runner seams

**Files:**
- Modify: `core/harvest.py` (two new functions + two path constants),
  `core/pipeline.py` (`cmd_harvest` Steps 1+4 delegate; local constants
  deleted), `tests/test_harvest.py`

**Interfaces:**
- Consumes: `harvest.parse_edepana_saw`, `harvest.parse_s_over_sqrt_b`
  (existing).
- Produces: `harvest.EDEP_FCL`, `harvest.SENSITIVITY_MACRO` (Path consts);
  `harvest.run_edepana(harvest_dir, ce_files, *, runner) -> tuple[int, Path]`;
  `harvest.run_sensitivity_macro(harvest_dir, nts_path, ce_abs_eff, *, runner) -> float`.
  `runner(cmd: list[str], cwd: Path)` returns an object with
  `.returncode/.stdout/.stderr`; the CALLER binds env (keeps harvest.py
  subprocess-free by design).

- [ ] **Step 1: add to `core/harvest.py`** (near the existing parser
  functions; keep the module stdlib-only — the runners carry subprocess)

```python
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
EDEP_FCL = AUTORESEARCH / "Run1BAna/workflows/fcl/edep.fcl"
SENSITIVITY_MACRO = AUTORESEARCH / "Run1BAna/workflows/scripts/rough_run1a_sensitivity.C"


def run_edepana(harvest_dir: Path, ce_files: Sequence[Path], *, runner):
    """Harvest Step 1: EdepAna over the CeEndpoint art files.

    Returns (ce_seen, nts_path). Writes ce_files.txt, edep_wrapper.fcl and
    edep.log into harvest_dir. runner(cmd, cwd) -> proc-like; the caller
    binds env/FHICL_FILE_PATH. HARD-fail (SystemExit) on rc != 0 or an
    unparseable 'Saw N events' line — this is the sob numerator, never
    fail-soft (unlike extract_secondary_edep).
    """
    ce_list = harvest_dir / "ce_files.txt"
    ce_list.write_text("\n".join(str(p) for p in ce_files) + "\n")
    nts_path = harvest_dir / "nts.ce.root"
    wrapper = harvest_dir / "edep_wrapper.fcl"
    wrapper.write_text(
        f'#include "{EDEP_FCL.relative_to(AUTORESEARCH).as_posix()}"\n'
        f'services.TFileService.fileName: "{nts_path.name}"\n'
    )
    edep_log = harvest_dir / "edep.log"
    proc = runner(["mu2e", "-c", str(wrapper), "-S", str(ce_list)],
                  harvest_dir)
    edep_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"EdepAna failed (rc={proc.returncode}); see {edep_log}")
    try:
        return parse_edepana_saw(proc.stdout), nts_path
    except ValueError as e:
        raise SystemExit(f"{e}; see {edep_log}")


def run_sensitivity_macro(harvest_dir: Path, nts_path: Path,
                          ce_abs_eff: float, *, runner) -> float:
    """Harvest Step 4: rough_run1a_sensitivity.C -> S/sqrt(B).

    cwd is the Run1BAna workflows dir (macro path in cmd is
    workflows-relative). Writes rough_run1a_sensitivity.log. HARD-fail on
    rc != 0 / unparseable output.
    """
    macro_log = harvest_dir / "rough_run1a_sensitivity.log"
    cwd = SENSITIVITY_MACRO.parent.parent
    cmd = ["root", "-q", "-b", "-l",
           f'scripts/rough_run1a_sensitivity.C("{nts_path}", '
           f'{ce_abs_eff:.16g}, "{harvest_dir}")']
    proc = runner(cmd, cwd)
    macro_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(
            f"rough_run1a_sensitivity.C failed (rc={proc.returncode}); "
            f"see {macro_log}")
    try:
        return parse_s_over_sqrt_b(proc.stdout)
    except ValueError as e:
        raise SystemExit(f"{e}; see {macro_log}")
```

(`Sequence` is already imported in harvest.py.) The wrapper/cmd/log text
must be BYTE-IDENTICAL to what `cmd_harvest` writes today (Task 3 Step 2's
deletions are the source) — the golden re-harvest gate depends on it.

- [ ] **Step 2: delegate in `core/pipeline.py`**

Replace `cmd_harvest`'s Step 1 block (`print(">>> Step 1..."` through the
`ce_seen = ...` parse, currently :1266-1287) with:

```python
    print(">>> Step 1: EdepAna on CeEndpoint outputs")
    def _mu2e_runner(cmd, cwd):
        return subprocess.run(
            cmd, cwd=cwd,
            env={**env, "FHICL_FILE_PATH":
                 f"{AUTORESEARCH}:{env.get('FHICL_FILE_PATH', '')}"},
            capture_output=True, text=True, check=False)
    ce_seen, nts_path = hv.run_edepana(harvest_dir, ce_files,
                                       runner=_mu2e_runner)
```

Replace the Step 4 block (`print(">>> Step 4..."` through the
`s_over_sqrt_b = ...` parse, currently :1303-1315) with:

```python
    print(">>> Step 4: rough_run1a_sensitivity.C")
    def _root_runner(cmd, cwd):
        return subprocess.run(cmd, cwd=cwd, env=env,
                              capture_output=True, text=True, check=False)
    s_over_sqrt_b = hv.run_sensitivity_macro(harvest_dir, nts_path,
                                             ce_abs_eff, runner=_root_runner)
```

Delete pipeline.py's own `EDEP_FCL`/`SENSITIVITY_MACRO` constants
(:956-957) after grepping that Steps 1/4 were their only consumers; the
comment block above them points to harvest.py now. `AUTORESEARCH` (:955)
stays (used by `_mu2e_runner` and elsewhere — verify with grep before
touching it).

- [ ] **Step 3: fake-runner tests** (append to `tests/test_harvest.py`,
  following the file's existing conventions)

```python
class TestRunEdepana(unittest.TestCase):
    def _runner(self, rc=0, stdout="x\nSaw 12345 events\ny"):
        calls = []
        def run(cmd, cwd):
            calls.append((cmd, cwd))
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr="e")
        run.calls = calls
        return run

    def test_success_writes_artifacts_and_parses_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            hd = Path(tmp)
            runner = self._runner()
            ce_seen, nts = hv.run_edepana(hd, [Path("/a/f1.art"),
                                               Path("/a/f2.art")],
                                          runner=runner)
            self.assertEqual(ce_seen, 12345)
            self.assertEqual(nts, hd / "nts.ce.root")
            self.assertEqual((hd / "ce_files.txt").read_text(),
                             "/a/f1.art\n/a/f2.art\n")
            wrapper = (hd / "edep_wrapper.fcl").read_text()
            self.assertIn('#include "Run1BAna/workflows/fcl/edep.fcl"',
                          wrapper)
            self.assertIn('fileName: "nts.ce.root"', wrapper)
            self.assertIn("Saw 12345 events", (hd / "edep.log").read_text())
            cmd, cwd = runner.calls[0]
            self.assertEqual(cmd[0], "mu2e")
            self.assertEqual(cwd, hd)

    def test_scientific_notation_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(stdout="Saw 2.70937e+06 events")
            ce_seen, _ = hv.run_edepana(Path(tmp), [Path("/a/f.art")],
                                        runner=runner)
            self.assertEqual(ce_seen, 2709370)

    def test_nonzero_rc_hard_fails_with_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                hv.run_edepana(Path(tmp), [Path("/a/f.art")],
                               runner=self._runner(rc=9))
            self.assertIn("edep.log", str(cm.exception))

    def test_unparseable_count_hard_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                hv.run_edepana(Path(tmp), [Path("/a/f.art")],
                               runner=self._runner(stdout="no count here"))


class TestRunSensitivityMacro(unittest.TestCase):
    def _runner(self, rc=0, stdout="S/sqrt(B) = 3.140"):
        calls = []
        def run(cmd, cwd):
            calls.append((cmd, cwd))
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
        run.calls = calls
        return run

    def test_success_parses_and_uses_workflows_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner()
            val = hv.run_sensitivity_macro(Path(tmp), Path("/n/nts.root"),
                                           0.0123, runner=runner)
            self.assertAlmostEqual(val, 3.140)
            cmd, cwd = runner.calls[0]
            self.assertEqual(cwd, hv.SENSITIVITY_MACRO.parent.parent)
            self.assertIn("/n/nts.root", cmd[-1])
            self.assertIn("0.0123", cmd[-1])

    def test_nonzero_rc_hard_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                hv.run_sensitivity_macro(Path(tmp), Path("/n/nts.root"),
                                         0.0123, runner=self._runner(rc=1))
```
(Add `from types import SimpleNamespace` to the file's imports if absent.)

- [ ] **Step 4: golden re-harvest gate** (the proven Eval-summary method)

Precondition: campaign check. Pick the newest completed foilsflash config
whose `harvest/summary.json` AND `state/mustops_ce_outputs.txt` paths still
resolve on /pnfs (start with `foilsflash13R00_02`, the config the July
switchover validated; fall back to a newer one if its inputs migrated).
Then:

```bash
GRID=/exp/mu2e/data/users/oksuzian/autoresearch_grid
CFG=foilsflash13R00_02   # or the fallback you verified
cp $GRID/$CFG/harvest/summary.json /tmp/summary.pre-a2.json
PYTHONPATH= .venv/bin/python core/pipeline.py --config $CFG harvest
PYTHONPATH= .venv/bin/python - <<'EOF'
import json
a = json.load(open("/tmp/summary.pre-a2.json"))
b = json.load(open("/exp/mu2e/data/users/oksuzian/autoresearch_grid/foilsflash13R00_02/harvest/summary.json"))
diff = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
print("DIFFERING KEYS:", sorted(diff) or "NONE — bit-identical")
EOF
```
Gate: NONE (all keys bit-identical; `harvested_at`-style timestamps, if any
key differs only by run time, list them explicitly and justify). If keys
differ otherwise: the seam changed behavior — fix, never accept. Restore
nothing (the re-harvest output IS the same content on success).

- [ ] **Step 5: suite + goldens + commit**

Focused `tests.test_harvest` (expect 26 + 7 new = 33; report actual), full
suite, `check a b` OK. Commit:

```
refactor: harvest Steps 1+4 behind injected runners in harvest.py

EdepAna + sensitivity-macro subprocess steps move out of cmd_harvest
(hard-fail semantics preserved); golden re-harvest of <CFG> bit-identical
across all summary.json keys.
```
(+ trailers.) `git add core/harvest.py core/pipeline.py tests/test_harvest.py`

---

### Task 4: A1 — ChildTracker full-cut (STALE_CLUSTER + launch/assign rewiring)

**Files:**
- Modify: `graph/child_tracker.py`, `graph/closed_loop.py`,
  `tests/test_child_tracker.py`, `tests/test_closed_loop.py`

**Interfaces:**
- Produces: `Resolution.STALE_CLUSTER = "stale_cluster"`; Signals protocol
  gains `has_cluster(name: str) -> bool`; `_DiskSignals.has_cluster`.
- Behavior change (intended, tested): an all-stale/no-launch round now
  RESOLVES cleanly via STALE_CLUSTER instead of the barrier raising
  RuntimeError; the barrier's empty-guard narrows to "children dict empty".

- [ ] **Step 1: `graph/child_tracker.py`**

Add to `Resolution`: `STALE_CLUSTER = "stale_cluster"` (it is `is_done` via
the existing `is not RUNNING` property). Add to the `Signals` protocol:

```python
    def has_cluster(self, name: str) -> bool:
        """A prior run's *_cluster.txt exists in the child's state dir."""
        ...
```

In `tick()`, replace the final `else:` (pid) branch with:

```python
            else:
                pid = rec.get("pid")
                if pid is None:
                    # Never launched by this parent. If a prior aborted
                    # run left *_cluster.txt, the grid was submitted but
                    # never harvested — this child can never resolve via
                    # row/broken/terminal here. Resolve loudly.
                    if self._signals.has_cluster(name):
                        new = Resolution.STALE_CLUSTER
                elif not self._signals.pid_alive(pid):
                    if name in self._dead_suspect:
                        new = Resolution.DEAD_UNRESOLVED
                    else:
                        # Grace: confirm on the NEXT tick, in case the final
                        # leaderboard append was racing the process death.
                        self._dead_suspect.add(name)
                else:
                    self._dead_suspect.discard(name)
```

Rewrite the module docstring's last paragraph (the "not implemented yet"
note) to: stale-cluster children are now a first-class `STALE_CLUSTER`
Resolution raised by the tracker itself; `node_launch_children` still
skips the Popen (double-submit guard) but no longer does its own
completed/error bookkeeping.

- [ ] **Step 2: `graph/closed_loop.py`**

(a) `_DiskSignals` gains:

```python
    def has_cluster(self, name: str) -> bool:
        return any(_child_state_dir(name).glob("*_cluster.txt"))
```

(b) `node_launch_children`: KEEP `_already_running` and the Popen skip
(that guard prevents double-submits). DELETE the post-loop bookkeeping
block (`completed = list(state.get("completed_names", []))` through
`completed.append(name)`, currently :484-504) and drop `completed_names`
from the return dict — the barrier's tracker now owns stale-cluster
resolution. Keep `launched_names` exactly as is (pid-based).

(c) `node_barrier`: narrow the empty-guard —

```python
    if not children:
        raise RuntimeError(
            f"barrier[r{state.get('round_idx')}]: children dict empty — "
            f"state pipeline corrupted between launch_children and barrier")
    if not launched:
        print(f"[closed_loop] barrier[r{state.get('round_idx')}]: nothing "
              f"launched this round ({len(children)} children resume/stale) — "
              f"tracker will resolve them", flush=True)
```

and add the transition case (alongside DONE_TERMINAL_NO_ROW /
DEAD_UNRESOLVED):

```python
                elif res is Resolution.STALE_CLUSTER:
                    msg = (f"barrier[{name}]: STALE_CLUSTER — *_cluster.txt "
                           f"in {_child_state_dir(name)} from a prior "
                           f"aborted submit, no leaderboard row; child was "
                           f"not launched. Run `rm "
                           f"{_child_state_dir(name)}/*_cluster.txt` and "
                           f"relaunch, or use a different --name-prefix.")
                    print(f"[closed_loop] {msg}", flush=True)
                    errors.append(msg)
```

(d) `node_assign_names`: hoist the per-child leaderboard read — before the
loop: `lb_names = _leaderboard_names(mode)`; in the loop replace
`_child_in_leaderboard(name, mode)` with `name in lb_names`. (One flocked
TSV parse instead of q.)

- [ ] **Step 3: tests**

`tests/test_child_tracker.py` — extend the fake signals with
`has_cluster` (default False) and add:

```python
    def test_stale_cluster_resolves_never_launched_child(self):
        # pid None + has_cluster -> STALE_CLUSTER on first tick, sticky.
    def test_pid_none_without_cluster_stays_running(self):
    def test_launched_child_never_stale(self):
        # pid set + has_cluster True -> normal pid/row logic, not STALE.
```
(Write real bodies following the file's existing fake-signals pattern;
each asserts via `tracker.tick()` / `resolutions()`.)

`tests/test_closed_loop.py` — `TestStaleClusterSkipIsLoud`:
- `test_stale_cluster_excluded_from_launched_names`: keep (still true).
- `test_all_stale_then_barrier_refuses`: REWRITE as
  `test_all_stale_resolves_via_tracker`: same setup, but the barrier now
  RETURNS (no raise) with every stale name in `completed_names` and a
  STALE_CLUSTER error line per name (assert `"STALE_CLUSTER"` in an errors
  entry and completed == all names).
- `test_leaderboard_resume_is_silent`: keep; verify it still passes with
  the launch bookkeeping gone (resume children resolve via DONE_ROW at the
  barrier).
`TestBarrierRefusesEmptyChildren::test_empty_launched_names_raises`:
rewrite to pin the NEW contract — empty children dict raises; children
present but nothing launched proceeds (and resolves via tracker).

- [ ] **Step 4: verify + commit**

Campaign precondition. Focused `tests.test_child_tracker` +
`tests.test_closed_loop`; full suite; `check a b` OK; plus the wiring
smoke: `PYTHONUNBUFFERED=1 PYTHONPATH= .venv/bin/python -m graph.run --mock --mode foilsflash --thread-id slimSMOKE1 --config-name slimSMOKE1 2>&1 | tail -5`
(chain reaches END; clean its pending row: `grep -v "slimSMOKE1" leaderboards/pending_bo_foilsflash.tsv > /tmp/p.tmp` then `cp /tmp/p.tmp leaderboards/pending_bo_foilsflash.tsv`; leaderboard line count unchanged). Commit:

```
refactor: ChildTracker full-cut — STALE_CLUSTER resolution, launch/assign rewiring

Stale-cluster children resolve via the tracker (loud, clean) instead of
launch-side bookkeeping; all-stale rounds no longer RuntimeError at the
barrier; assign_names does one leaderboard read. Live validation rides
the next campaign (barrier first-cut precedent).
```
(+ trailers.) `git add graph/child_tracker.py graph/closed_loop.py tests/test_child_tracker.py tests/test_closed_loop.py`

---

### Task 5: test_closed_loop redundancy audit (the "acrobatics shrink")

**Files:**
- Modify (possibly): `tests/test_closed_loop.py`

**Interfaces:** none. May legitimately conclude "nothing to shrink".

- [ ] **Step 1: audit**

`grep -c "mock.patch" tests/test_closed_loop.py` and read the barrier/
launch test classes. For each test that now duplicates coverage the
injected-fake `tests/test_child_tracker.py` provides at the tracker level,
judge: does it ALSO pin closed_loop-side wiring (_DiskSignals binding,
error-message routing, state plumbing)? Delete only tests that are pure
duplicates of tracker-level coverage; simplify (don't delete) tests that
pin wiring. The design's original target — `mock.patch(build_graph)` /
`is_child_terminal` acrobatics — may already be minimal after Task 4's
rewrites; a recorded "audited, N deleted / M kept because wiring" verdict
is a valid outcome.

- [ ] **Step 2: suite + commit** (only if something changed)

Full suite green (report the new count). Commit:
`test: prune closed_loop tests made redundant by tracker-level coverage`
(+ trailers), or record "no commit — audit found no pure duplicates" in
the task report.

---

### Task 6: records — spec amendments + wiki sweep

**Files:**
- Modify: `docs/superpowers/specs/2026-07-19-slim-shrink-sweep-design.md`,
  `wiki/concepts/mode-registry-childtracker-design.md`,
  `wiki/concepts/architecture-friction-survey-2026-07.md`,
  `wiki/drivers/closed-loop-runner.md`, `wiki/drivers/tests.md`,
  `wiki/drivers/bo-driver.md`, `wiki/drivers/pipeline.md`,
  `wiki/index.md`, `wiki/log.md`

**Interfaces:** none.

- [ ] **Step 1: spec amendments** (in the slim spec's Status/relevant
  sections, dated 2026-07-19): the four spec-reality amendments listed at
  the top of this plan, plus Task 5's verdict; Status → implemented.

- [ ] **Step 2: wiki sweep** (OKF contract: bump `timestamp:`, mirror
  `description:` ↔ index one-liner byte-identically, ONE `log.md` bullet
  under `## 2026-07-19` at the TOP, bundle-relative links):

- `mode-registry-childtracker-design.md`: full-cut DONE note (STALE_CLUSTER
  + launch/assign rewiring + barrier-guard change; streak-move dissolved as
  already-landed).
- `closed-loop-runner.md`: barrier semantics update (all-stale resolves,
  empty-children raises) + the stale-cluster operator recipe unchanged.
- `architecture-friction-survey-2026-07.md`: harvest phase-2 (candidate 5's
  Steps 1+4 slice) done; cmd_harvest now subprocess-free except Step 2's
  event counting (record that honestly).
- `bo-driver.md`: fix the B0-noted drift (KNOB_NAMES/CALO_COL live in
  modes.SPECS; preflight/evaluate have `--emit-json`).
- `pipeline.md`: cmd_harvest delegates Steps 1+4 to harvest.py runners.
- `tests.md`: new counts (grep-verify), incident links for stale-cluster.
- `wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md`: append a
  dated resolution note — the pathology now resolves as STALE_CLUSTER
  (status can stay `resolved`; bump timestamp).
- `index.md` mirrors + `log.md` bullet (commit list of the round).

- [ ] **Step 3: final suite + commit**

Full suite green (final count). Stage the named files only. Commit:
`docs(wiki): slimming round recorded — ChildTracker full-cut + harvest seams + sweep`
(+ trailers.) Then report: commits, counts, golden verdicts, the Task 1/5
verdicts, and that everything is local awaiting `git push`.
