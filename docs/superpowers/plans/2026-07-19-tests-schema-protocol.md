# Tests + Schema Single-Sourcing + JSON Protocol — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a green suite mean the live path works (flock, grid verbs, picker tested), make `modes.SPECS` the single authority for leaderboard columns, and move the graph↔driver seam from exit-codes/stdout-regex to typed JSON — with TSV bytes on disk never changing.

**Architecture:** Golden-harness-led (spec `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`): durable tests for untouched code first, then a byte-parity golden harness, then the two refactors (Phase 1 schema → ModeSpec; Phase 2 JSON protocol), each gated on goldens re-verifying byte-identical.

**Tech Stack:** Python 3.11 single project `.venv` (langgraph + botorch 0.18 + torch CPU), stdlib `unittest` (NOT pytest), `fcntl` flock, subprocess seams.

## Global Constraints

- Suite command (run after EVERY commit, must be green):
  `cd /exp/mu2e/app/users/oksuzian/autoresearch && PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v`
  (`PYTHONPATH=` guards against leaked cvmfs Musing site-packages — wiki
  `incidents/venv-relocated-to-data-volume.md`.)
- **TSV bytes on disk never change.** No test or golden run may write to
  `leaderboards/*.tsv` — tests always repoint mode instances at tmp copies.
- **Never `git push`** (Bash subshells can't reach the user's ssh-agent).
  Stage named paths only — never `git add docs/` or `git add -A`.
- Every commit message ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- Before any live smoke (Tasks 4, 8): verify no campaign is running:
  `ps -fu $USER -ww | grep "[c]losed_loop"` must be empty.
- Test-file import bootstrap (same convention as `tests/test_harvest.py`):
  `sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))`.
- `bo_driver` line numbers below are as of commit `eac8131`; re-locate by
  content if drifted.

---

### Task 1: `tests/test_flock.py` — real flock coverage

The 2026-07-17 incident: `_flock_ex` was completely broken (decorator
capture) while the 158-test suite stayed green — no test exercised the lock
helpers end-to-end. These tests use REAL `fcntl.flock` on tmp files, with a
child process for contention (flock is per-process, so same-process
re-acquisition would not test exclusion).

**Files:**
- Create: `tests/test_flock.py`
- Under test: `core/bo_driver.py:47-93` (`_lock_path`, `_flock_ex`, `_flock_sh`)

**Interfaces:**
- Consumes: `bo_driver._lock_path(target: Path) -> Path`,
  `bo_driver._flock_ex(target)` / `_flock_sh(target)` (contextmanagers).
- Produces: nothing (durable tests only).

- [ ] **Step 1: Write the tests**

```python
"""Real-flock tests for bo_driver._lock_path/_flock_ex/_flock_sh.

Regression anchor: 2026-07-17 the _lock_path insertion silently captured
_flock_ex's @contextmanager decorator — every real lock acquisition raised
TypeError while the whole suite stayed green (no test entered the
contextmanagers). These tests hold locks for real and probe contention from
a child process (flock exclusion is between processes/fds, not within one).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402

# Child: try a non-blocking flock of the given kind on argv[1]; rc 0 = got
# it, rc 3 = blocked.
_CHILD = r"""
import fcntl, sys
mode = fcntl.LOCK_EX if sys.argv[2] == "ex" else fcntl.LOCK_SH
try:
    with open(sys.argv[1], "w") as f:
        fcntl.flock(f.fileno(), mode | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(3)
sys.exit(0)
"""


def _child_try(lock_path: Path, kind: str) -> int:
    return subprocess.run(
        [sys.executable, "-c", _CHILD, str(lock_path), kind],
        capture_output=True).returncode


class TestLockPath(unittest.TestCase):
    def test_anchor_is_locks_dir_next_to_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "leaderboard_bo_x.tsv"
            lp = bo._lock_path(target)
            self.assertEqual(lp, Path(tmp) / "locks" / "leaderboard_bo_x.tsv.lock")
            self.assertTrue(lp.parent.is_dir())  # locks/ auto-created


class TestFlockContention(unittest.TestCase):
    def test_ex_blocks_child_ex_until_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            lp = bo._lock_path(target)
            with bo._flock_ex(target):
                self.assertEqual(_child_try(lp, "ex"), 3)  # blocked
                self.assertEqual(_child_try(lp, "sh"), 3)  # readers blocked too
            self.assertEqual(_child_try(lp, "ex"), 0)      # released

    def test_sh_allows_child_sh_blocks_child_ex(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            lp = bo._lock_path(target)
            with bo._flock_sh(target):
                self.assertEqual(_child_try(lp, "sh"), 0)  # concurrent readers OK
                self.assertEqual(_child_try(lp, "ex"), 3)  # writer blocked

    def test_contextmanagers_are_actually_contextmanagers(self):
        # The 2026-07-17 breakage made _flock_ex(target) raise TypeError.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            with bo._flock_ex(target):
                pass
            with bo._flock_sh(target):
                pass


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new file, then the whole suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_flock -v`
Expected: 4 tests PASS.
Run the full suite (Global Constraints command). Expected: 160 tests OK.

- [ ] **Step 3: Commit**

```bash
git add tests/test_flock.py
git commit -m "test: real-flock coverage for _lock_path/_flock_ex/_flock_sh

Closes the gap that let the 2026-07-17 decorator-capture breakage ship
with a green suite: contention is probed from a child process against
the locks/-dir anchor.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 2: `tests/test_pipeline_verbs.py` + poll runner seam

Grid-verb logic (submit idempotency, stamp-at-submit, poll exit conditions,
list-outputs gating) currently has zero tests. One minimal seam is added:
`poll_cluster` gains an injected `runner` (default = today's
`subprocess.run`) so the jobsub_q boundary is fakeable.

**Files:**
- Modify: `core/pipeline.py:765` (`poll_cluster` signature) and `:783` (the
  `subprocess.run` call)
- Create: `tests/test_pipeline_verbs.py`

**Interfaces:**
- Consumes: `pipeline.cmd_submit(args)`, `cmd_poll(args)`,
  `cmd_list_outputs(args)`, `poll_cluster(stage, cluster, *, quorum,
  cap_hours, runner=None)`, module globals `STATE`, `STAGES`, `OUTSTAGE`,
  `GRID_STAGES`; `harvest.STAGE_CHAIN_STAMP` / `stamp_stage_chain`.
- Produces: the `runner` keyword on `poll_cluster` (later tasks don't
  depend on it; it is test-only injection with a live default).

- [ ] **Step 1: Add the runner seam to `poll_cluster`**

In `core/pipeline.py`, change the signature (line 765):

```python
def poll_cluster(stage: str, cluster: int, *, quorum: float = 0.9,
                 cap_hours: float = 24.0, runner=None) -> None:
```

and the jobsub_q call (line 783):

```python
        out = (runner or subprocess.run)(
            ["jobsub_q", "-G", "mu2e", f"--user={USER}",
             "--constraint", f"ClusterId=={cluster}"],
            capture_output=True, text=True,
        )
```

No other body changes. `cmd_poll` keeps calling it without `runner`.

- [ ] **Step 2: Write the tests**

```python
"""Grid-verb tests for core/pipeline.py: submit idempotency, stamp-at-submit,
poll exit conditions (via injected jobsub_q runner), list-outputs gating.
No grid contact: STATE/STAGES/OUTSTAGE are patched to tmp dirs and the
jobsub/subprocess boundary is faked."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import pipeline  # noqa: E402
import harvest as hv  # noqa: E402


def _q_result(rc=0, stdout=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")


def _queue_lines(cluster, n):
    return "\n".join(f"{cluster}.{i}@jobsub01.fnal.gov" for i in range(n))


class TestSubmitIdempotency(unittest.TestCase):
    def test_noop_when_cluster_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "submit_stage") as sub, \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            (Path(tmp) / "poke_cluster.txt").write_text("123\n")
            pipeline.cmd_submit(SimpleNamespace(stage="poke", force=False,
                                                dry_run=False))
            sub.assert_not_called()

    def test_stamps_chain_then_submits_on_first_submit(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES", ("poke", "harvest2")), \
             mock.patch.object(pipeline, "submit_stage") as sub, \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            pipeline.cmd_submit(SimpleNamespace(stage="poke", force=False,
                                                dry_run=False))
            stamp = Path(tmp) / hv.STAGE_CHAIN_STAMP
            self.assertTrue(stamp.exists())
            self.assertEqual(hv.stamped_stage_chain(Path(tmp)),
                             ["poke", "harvest2"])
            sub.assert_called_once()

    def test_existing_stamp_not_overwritten(self):
        # Stamp-once semantics: a legacy config resubmitted under a new env
        # keeps ITS chain (the ff11R00_07 +1.5% sob bias class).
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES", ("newchain",)), \
             mock.patch.object(pipeline, "submit_stage"), \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            hv.stamp_stage_chain(Path(tmp), ["oldchain"])
            pipeline.cmd_submit(SimpleNamespace(stage="newchain", force=False,
                                                dry_run=False))
            self.assertEqual(hv.stamped_stage_chain(Path(tmp)), ["oldchain"])


class TestPollExitConditions(unittest.TestCase):
    def _outstage(self, tmp, cluster, bare, hashed):
        base = Path(tmp) / str(cluster) / "00"
        base.mkdir(parents=True)
        for i in range(bare):
            (base / f"{i:05d}").mkdir()
        for i in range(hashed):
            (base / f"{bare + i:05d}.6d475c59").mkdir()

    def test_returns_on_convergence_without_sleeping(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep",
                               side_effect=AssertionError("slept")):
            self._outstage(tmp, 123, bare=4, hashed=0)
            runner = mock.Mock(return_value=_q_result(0, ""))  # queue drained
            pipeline.poll_cluster("poke", 123, runner=runner)  # returns, no sleep

    def test_failure_aware_exit_queue_drained_all_dirs_but_unsettled(self):
        # 2 bare + 2 perma-hash = all 4 dirs present, settled < target=3:
        # must return (WARN) so list_outputs/harvest fail loudly, not hang.
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep",
                               side_effect=AssertionError("slept")):
            self._outstage(tmp, 123, bare=2, hashed=2)
            runner = mock.Mock(return_value=_q_result(0, ""))
            pipeline.poll_cluster("poke", 123, runner=runner)

    def test_jobsub_q_failure_is_retried_not_treated_as_empty_queue(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep") as slept:
            self._outstage(tmp, 123, bare=4, hashed=0)
            runner = mock.Mock(side_effect=[_q_result(1, ""),
                                            _q_result(0, "")])
            pipeline.poll_cluster("poke", 123, runner=runner)
            self.assertEqual(runner.call_count, 2)
            slept.assert_called_once_with(60)


class TestListOutputsGating(unittest.TestCase):
    def test_noop_when_outputs_listed_and_resolvable(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "list_outputs") as lo:
            f = Path(tmp) / "some.art"
            f.write_text("x")
            (Path(tmp) / "poke_outputs.txt").write_text(f"{f}\n")
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            lo.assert_not_called()

    def test_reglobs_when_listed_paths_vanished(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "list_outputs") as lo:
            (Path(tmp) / "poke_outputs.txt").write_text(
                f"{tmp}/gone.art\n")
            (Path(tmp) / "poke_cluster.txt").write_text("123\n")
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            lo.assert_called_once_with("poke", 123)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run new file + full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_pipeline_verbs -v`
Expected: 8 tests PASS (stderr may show `_check_stage_config_sha` WARN
lines — the helper warns-and-returns by contract).
Full suite: 168 OK.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_verbs.py core/pipeline.py
git commit -m "test: grid-verb coverage + injectable jobsub_q runner in poll_cluster

Submit idempotency, stamp-at-submit(+stamp-once), poll convergence /
failure-aware exit / jobsub_q-retry, list-outputs gating — all faked at
the new runner seam (default unchanged: subprocess.run).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 3: `tests/test_botorch_predict.py` + `--leaderboard` override + seam smoke

Picker tests run in the main suite now (single venv). Two small additive
seams make the tests and the golden harness possible:
`botorch_predict` gains `--leaderboard <path>` (repoints the mode instance's
leaderboard before picking — test/golden-only) and `botorch_ask` gains a
matching `leaderboard=` kwarg that forwards it.

**Files:**
- Modify: `core/botorch_predict.py` (`main()` argparse + repoint),
  `core/bo_driver.py:1165` (`botorch_ask` signature + cmd)
- Create: `tests/test_botorch_predict.py`

**Interfaces:**
- Consumes: `botorch_predict._load_history_tensor(mode, sob_only=False)`,
  `_seed(round_idx)`, `_emit_picks(cands, int_dims)`,
  `_sobol_cold_start(bounds, q, round_idx)`, `compute_explore_picks(...)`,
  `main(argv)`; `bo_driver.botorch_ask`, `bo.MODES`, `bo.Point`.
- Produces: `botorch_predict.py --leaderboard PATH` CLI arg;
  `botorch_ask(..., leaderboard: Path | None = None)`. Task 4's golden (b)
  depends on `--leaderboard`.

- [ ] **Step 1: Add the `--leaderboard` override to `botorch_predict.main()`**

In `core/botorch_predict.py` `main()`, after the `--pending-json` argument:

```python
    ap.add_argument("--leaderboard", type=str, default=None,
                    help="Override the mode's leaderboard TSV path (tests + "
                         "golden harness only; live callers omit it)")
```

and directly after `ns = ap.parse_args(argv)`:

```python
    if ns.leaderboard:
        bo.MODES[ns.mode].leaderboard = Path(ns.leaderboard)
        print(f"[botorch_predict] leaderboard override: {ns.leaderboard}",
              flush=True)
```

- [ ] **Step 2: Add the forwarding kwarg to `botorch_ask`**

In `core/bo_driver.py:1165`, signature gains `leaderboard: Path | None = None`
(after `venv_py`), docstring gains one line
(`leaderboard: test/golden-only override forwarded as --leaderboard.`), and
after the `cmd = [...]` list construction add:

```python
        if leaderboard is not None:
            cmd += ["--leaderboard", str(leaderboard)]
```

- [ ] **Step 3: Write the tests**

```python
"""Picker tests for core/botorch_predict.py (main suite since the 2026-07-18
single-venv consolidation) + the botorch_ask subprocess seam smoke.

Fixtures repoint bo.MODES["foilsflash"].leaderboard at a tmp 10-row TSV
(foilsflash: load_priors()==[] so history is exactly the fixture). The live
leaderboards are never touched."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402

HEADER = ("config\textra_rOut_up\textra_rOut_dn\textra_halfThickness_up"
          "\textra_halfThickness_dn\textra_f_up\textra_f_dn"
          "\tsob\tflash_edep\talpha\tobj\n")


def write_fixture(path: Path, n: int = 10, header_only: bool = False):
    rows = []
    for i in range(n):
        u = i / max(1, n - 1)
        x = [50 + 200 * u, 250 - 200 * u, 0.002 + 0.9 * u, 0.9 - 0.8 * u,
             0.05 + 0.9 * u, 0.9 - 0.85 * u]
        sob, flash = 3.0 + 0.8 * u, 1e-7 * (1 + 9 * u)
        rows.append(f"cfg{i:03d}\t{x[0]:.4f}\t{x[1]:.4f}\t{x[2]:.6f}"
                    f"\t{x[3]:.6f}\t{x[4]:.4f}\t{x[5]:.4f}"
                    f"\t{sob:.5f}\t{flash:.5e}\t100000.000\t{sob:.5f}\n")
    path.write_text(HEADER + ("" if header_only else "".join(rows)))


def patched_leaderboard(tmp: str, **kw):
    lb = Path(tmp) / "leaderboard_bo_foilsflash.tsv"
    write_fixture(lb, **kw)
    return mock.patch.object(bo.MODES["foilsflash"], "leaderboard", lb)


BOUNDS_LO = bp.MODE_SPECS["foilsflash"]["lo"]
BOUNDS_HI = bp.MODE_SPECS["foilsflash"]["hi"]


def in_bounds(x):
    return all(lo - 1e-9 <= v <= hi + 1e-9
               for v, lo, hi in zip(x, BOUNDS_LO, BOUNDS_HI))


class TestLoadHistoryTensor(unittest.TestCase):
    def test_parses_rows_and_log_transforms_second_objective(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, int_dims = bp._load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (10, 6))
            self.assertEqual(tuple(Y.shape), (10, 2))
            self.assertAlmostEqual(float(Y[0, 1]), -math.log10(1e-7), places=6)
            self.assertEqual(bounds.shape[-1], 6)
            self.assertEqual(int_dims, [])

    def test_nonpositive_calo_rows_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp) as _:
            lb = bo.MODES["foilsflash"].leaderboard
            with lb.open("a") as f:
                f.write("bad\t100.0\t100.0\t0.5\t0.5\t0.5\t0.5"
                        "\t3.0\t0.00000e+00\t100000.000\t3.0\n")
            X, Y, _, _ = bp._load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (10, 6))

    def test_sob_only_path_is_1d(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            _, Y, _, _ = bp._load_history_tensor("foilsflash", sob_only=True)
            self.assertEqual(tuple(Y.shape), (10, 1))

    def test_width_guard_systemexit_on_dim_mismatch(self):
        wrong = [bo.Point(cfg="w", x=[1.0, 2.0, 3.0], sob=1.0, calo=1e-7)]
        with mock.patch.object(bo.MODES["foilsflash"], "load_history",
                               return_value=wrong):
            with self.assertRaises(SystemExit):
                bp._load_history_tensor("foilsflash")

    def test_cold_start_returns_empty_with_correct_width(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            X, Y, _, _ = bp._load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (0, 6))
            self.assertEqual(tuple(Y.shape), (0, 2))


class TestSeedAndEmit(unittest.TestCase):
    def test_seed_is_xor_not_pow(self):
        # 42^1=43, 42^2=40, 42^3=41 under XOR; pow would explode.
        self.assertEqual([bp._seed(i) for i in range(4)], [42, 43, 40, 41])

    def test_emit_picks_native_types_and_int_rounding(self):
        import torch
        out = bp._emit_picks(torch.tensor([[1.4, 2.6]]), int_dims=[1])
        self.assertEqual(out, [(1.4, 3)])
        self.assertIsInstance(out[0][0], float)
        self.assertIsInstance(out[0][1], int)

    def test_sobol_cold_start_deterministic_and_in_bounds(self):
        import torch
        bounds = torch.tensor([BOUNDS_LO, BOUNDS_HI])
        a = bp._sobol_cold_start(bounds, q=3, round_idx=5)
        b = bp._sobol_cold_start(bounds, q=3, round_idx=5)
        self.assertTrue(torch.equal(a, b))
        self.assertEqual(tuple(a.shape), (3, 6))
        for row in a.tolist():
            self.assertTrue(in_bounds(row))


class TestComputeExplorePicks(unittest.TestCase):
    def test_cold_start_path_returns_q_picks(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            picks = bp.compute_explore_picks(q=2, mode="foilsflash",
                                             round_idx=0)
            self.assertEqual(len(picks), 2)
            for p in picks:
                self.assertTrue(in_bounds(p))

    def test_real_gp_qnehvi_pick_on_fixture(self):
        # The one real GP fit in the suite (CPU, ~seconds on 10 rows).
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            picks = bp.compute_explore_picks(q=1, mode="foilsflash",
                                             round_idx=0, picker="qnehvi")
            self.assertEqual(len(picks), 1)
            self.assertEqual(len(picks[0]), 6)
            self.assertTrue(in_bounds(picks[0]))

    def test_main_emits_picks_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = Path(tmp) / "lb.tsv"
            write_fixture(lb, header_only=True)  # cold start = fast
            out = Path(tmp) / "picks.json"
            bp.main(["--mode", "foilsflash", "--q", "2", "--round-idx", "0",
                     "--leaderboard", str(lb),
                     "--emit-picks-json", str(out)])
            picks = json.loads(out.read_text())
            self.assertEqual(len(picks), 2)


class TestBotorchAskSeamSmoke(unittest.TestCase):
    def test_ask_q2_roundtrip_through_subprocess(self):
        # End-to-end: bo_driver.botorch_ask -> .venv python botorch_predict.py
        # --leaderboard <tmp fixture> --emit-picks-json. The only slow test
        # in the suite (one real 10-row GP fit in a fresh interpreter).
        with tempfile.TemporaryDirectory() as tmp:
            lb = Path(tmp) / "lb.tsv"
            write_fixture(lb)
            xs = bo.botorch_ask("foilsflash", q=2, seed_idx=0,
                                picker="qnehvi", leaderboard=lb)
            self.assertEqual(len(xs), 2)
            for x in xs:
                self.assertEqual(len(x), 6)
                self.assertTrue(in_bounds(x))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run new file + full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_botorch_predict -v`
Expected: 12 tests PASS (~1-3 min total; the seam smoke dominates).
Full suite: 180 OK.

- [ ] **Step 5: Commit**

```bash
git add tests/test_botorch_predict.py core/botorch_predict.py core/bo_driver.py
git commit -m "test: picker unit tests + botorch_ask seam smoke; --leaderboard override

_load_history_tensor row parsing / width guard / sob-only / cold-start,
xor seeding, emit typing, one real GP fit, and an end-to-end subprocess
ask against a tmp fixture. --leaderboard (CLI + botorch_ask kwarg) is the
test/golden-only repoint that makes fixture-fed picker runs possible.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 4: `tests/golden_parity.py` + captured baseline

Manually-run harness (same convention as `test_wal_multiwriter_stress.py`:
NO `test_` defs, invisible to unittest discover). Three sections; captures
land in `tests/goldens/` (committed). Re-run `check` after every refactor
commit (Tasks 5-7).

Golden (a) subtlety: `obj` is recomputed from parsed (rounded) sob/calo, so
a regenerated line can differ from disk in the last obj digit for rows
whose full-precision obj rounded differently. The harness therefore records
the mismatch SET at capture time; `check` requires the set (and the sha256
of all regenerated lines) to be IDENTICAL — that pins reader+writer
stability without pretending pre-existing rounding drift away.

**Files:**
- Create: `tests/golden_parity.py`, `tests/goldens/` (baseline JSONs +
  frozen leaderboard copy)

**Interfaces:**
- Consumes: `bo.MODES` (all 6), `format_row`/`load_history_row`,
  `botorch_predict.py --leaderboard` (Task 3), `bo.cmd_evaluate` /
  `bo.cmd_preflight` (in-process, args via SimpleNamespace).
- Produces: `tests/goldens/parity_a_baseline.json`,
  `leaderboard_bo_foilsflash.frozen.tsv`, `picks_hybrid_q2_r0.json`,
  `seam_replay_baseline.json`. Tasks 5-7 gate on `check` passing.

- [ ] **Step 1: Write the harness**

```python
#!/usr/bin/env python3
"""Golden parity harness (manually run; NOT part of unittest discover).

Usage:
    PYTHONPATH= .venv/bin/python tests/golden_parity.py capture [a b c]
    PYTHONPATH= .venv/bin/python tests/golden_parity.py check   [a b c]

(a) per-mode leaderboard round-trip: load_history_row -> format_row over
    every live leaderboard; baseline = per-mode row counts, skip counts,
    mismatch-index set, sha256 of regenerated lines. Pins reader+writer.
(b) picker: hybrid q=2 round-0 picks on the frozen foilsflash leaderboard
    copy via `botorch_predict.py --leaderboard`. Exact-compare, allclose
    (1e-6) fallback reported as WARN.
(c) seam replay: evaluate (in-process, tmp leaderboard copy) + preflight
    (real G4, ~2 min) for a completed foilsflash config. Baseline = rc,
    obj, appended line, verdict line — and, once Phase 2 lands, the
    emitted JSON payloads (re-capture then).
Never writes to leaderboards/ — evaluate replays into a tmp copy.
"""
import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from csv import DictReader
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import bo_driver as bo  # noqa: E402

GOLDENS = ROOT / "tests" / "goldens"
FROZEN_LB = GOLDENS / "leaderboard_bo_foilsflash.frozen.tsv"
PICKS_BASE = GOLDENS / "picks_hybrid_q2_r0.json"
A_BASE = GOLDENS / "parity_a_baseline.json"
C_BASE = GOLDENS / "seam_replay_baseline.json"


def _roundtrip_mode(name):
    mode = bo.MODES[name]
    if not mode.leaderboard.exists():
        return None
    raw_lines = mode.leaderboard.read_text().splitlines(keepends=True)
    regen, mismatches, skipped = [], [], 0
    with mode.leaderboard.open() as f:
        rows = list(DictReader(f, delimiter="\t"))
    for i, (row, raw) in enumerate(zip(rows, raw_lines[1:])):
        try:
            p = mode.load_history_row(row)
            alpha = float(row.get("alpha", bo.DEFAULT_ALPHA))
            line = mode.format_row(p, alpha)[1]
        except (KeyError, ValueError):
            skipped += 1
            continue
        regen.append(line)
        if line != raw:
            mismatches.append(i)
    header = mode.format_row(
        bo.Point(cfg="x", x=[0.0] * len(mode.KNOB_NAMES), sob=0.0,
                 calo=1.0), bo.DEFAULT_ALPHA)[0]
    return {
        "rows": len(rows), "skipped": skipped, "mismatch_idx": mismatches,
        "header_matches_disk": header == raw_lines[0],
        "sha256": hashlib.sha256("".join(regen).encode()).hexdigest(),
    }


def section_a():
    return {name: _roundtrip_mode(name) for name in sorted(bo.MODES)}


def section_b():
    out = Path(tempfile.mkdtemp()) / "picks.json"
    subprocess.run(
        [sys.executable, str(ROOT / "core" / "botorch_predict.py"),
         "--mode", "foilsflash", "--q", "2", "--round-idx", "0",
         "--picker", "hybrid", "--leaderboard", str(FROZEN_LB),
         "--emit-picks-json", str(out)],
        check=True)
    return json.loads(out.read_text())


def _pick_replay_config():
    mode = bo.MODES["foilsflash"]
    grid = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
    for p in reversed(mode.load_history()):
        geom = mode.proposal_dir / f"{p.cfg}_geom.txt"
        summary = grid / p.cfg / "harvest" / "summary.json"
        if geom.exists() and summary.exists():
            return p.cfg, summary
    raise SystemExit("no completed foilsflash config with geom+summary found")


def section_c():
    cfg, summary = _pick_replay_config()
    result = {"config": cfg}
    # -- evaluate replay against a TMP leaderboard copy --
    mode = bo.MODES["foilsflash"]
    tmp = Path(tempfile.mkdtemp())
    lb_copy = tmp / mode.leaderboard.name
    shutil.copyfile(mode.leaderboard, lb_copy)
    orig = mode.leaderboard
    mode.leaderboard = lb_copy
    try:
        buf = io.StringIO()
        args = SimpleNamespace(mode="foilsflash", config_name=cfg,
                               summary=str(summary), alpha=bo.DEFAULT_ALPHA)
        with contextlib.redirect_stdout(buf):
            rc = bo.cmd_evaluate(args)
        m = re.search(r"obj=([+-]?\d+\.\d+)", buf.getvalue())
        result["evaluate"] = {
            "rc": rc, "obj": m.group(1) if m else None,
            "appended_line": lb_copy.read_text().splitlines()[-1],
        }
        ej = getattr(args, "emit_json", None)
        if ej and Path(ej).exists():
            result["evaluate"]["json"] = json.loads(Path(ej).read_text())
    finally:
        mode.leaderboard = orig
    # -- preflight replay (real G4 init, ~2 min) --
    buf = io.StringIO()
    args = SimpleNamespace(mode="foilsflash", config_name=cfg)
    with contextlib.redirect_stdout(buf):
        rc = bo.cmd_preflight(args)
    verdict_lines = [ln for ln in buf.getvalue().splitlines()
                     if any(k in ln for k in ("PASS", "FAIL", "AMBIGUOUS"))]
    result["preflight"] = {"rc": rc,
                           "verdict_line": verdict_lines[-1] if verdict_lines else None}
    return result


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    sections = sys.argv[2:] or ["a", "b", "c"]
    GOLDENS.mkdir(exist_ok=True)
    fails = 0
    if "a" in sections:
        cur = section_a()
        if action == "capture":
            A_BASE.write_text(json.dumps(cur, indent=2))
            print(f"[a] captured -> {A_BASE}")
        else:
            base = json.loads(A_BASE.read_text())
            ok = cur == base
            print(f"[a] round-trip parity: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                for k in base:
                    if base[k] != cur.get(k):
                        print(f"    mode {k}: baseline={base[k]}\n"
                              f"             current ={cur.get(k)}")
                fails += 1
    if "b" in sections:
        if action == "capture":
            if not FROZEN_LB.exists():
                shutil.copyfile(
                    ROOT / "leaderboards" / "leaderboard_bo_foilsflash.tsv",
                    FROZEN_LB)
            PICKS_BASE.write_text(json.dumps(section_b(), indent=2))
            print(f"[b] captured -> {PICKS_BASE}")
        else:
            base, cur = json.loads(PICKS_BASE.read_text()), section_b()
            if cur == base:
                print("[b] picker parity: OK (exact)")
            else:
                close = (len(cur) == len(base) and all(
                    abs(a - b) < 1e-6
                    for ra, rb in zip(cur, base) for a, b in zip(ra, rb)))
                print(f"[b] picker parity: "
                      f"{'WARN (allclose only)' if close else 'MISMATCH'}")
                if not close:
                    print(f"    baseline={base}\n    current ={cur}")
                    fails += 1
    if "c" in sections:
        cur = section_c()
        if action == "capture":
            C_BASE.write_text(json.dumps(cur, indent=2))
            print(f"[c] captured -> {C_BASE}")
        else:
            base = json.loads(C_BASE.read_text())
            ok = cur == base
            print(f"[c] seam replay parity: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                print(f"    baseline={json.dumps(base, indent=2)}\n"
                      f"    current ={json.dumps(cur, indent=2)}")
                fails += 1
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Capture the baseline (needs the no-campaign precondition —
  section (c) runs a real preflight)**

```bash
ps -fu $USER -ww | grep "[c]losed_loop"   # must print nothing
PYTHONPATH= .venv/bin/python tests/golden_parity.py capture a b c
```
Expected: three `captured ->` lines; section (c) takes ~2-3 min (G4 init).
Then immediately verify the check passes against its own capture:
`PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b c` → all OK
(b may print WARN allclose if the GP fit is not bit-deterministic — if so,
note it; WARN is acceptable, MISMATCH is not).

- [ ] **Step 3: Full suite (unchanged — harness has no test_ defs)**

Expected: 180 OK, count unchanged from Task 3.

- [ ] **Step 4: Commit**

```bash
git add tests/golden_parity.py tests/goldens/
git commit -m "test: golden parity harness + captured baseline (rows/picks/seam)

(a) per-mode leaderboard round-trip fingerprint, (b) fixed-seed hybrid
q=2 picks on a frozen foilsflash copy, (c) evaluate+preflight replay of a
completed config. check must pass after every refactor commit this round.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 5: Phase 1 — schema single-sourcing into ModeSpec

`ModeSpec` gains `knob_names` / `knob_fmts` / `metric_cols` (all required,
values copied verbatim from today's driver literals). Driver class attrs
become registry-reading properties; the ProdTarget header derives from the
spec; the picker width-guard message derives from the spec. TSV bytes
unchanged — goldens prove it.

**Files:**
- Modify: `core/modes.py` (dataclass + all 6 SPECS entries),
  `core/bo_driver.py` (BOMode properties; delete per-class
  KNOB_NAMES/KNOB_FMTS/CALO_COL attrs at :394-396, :519, :546-548, :636,
  :673-676, :907, :1071; ProdTarget header at :1025-1028),
  `core/botorch_predict.py:117-121` (guard message),
  `tests/test_modes.py` (new pins)

**Interfaces:**
- Consumes: `modes.SPECS`, driver `format_row`/`load_history_row`.
- Produces: `ModeSpec.knob_names: Tuple[str, ...]`,
  `ModeSpec.knob_fmts: Tuple[str, ...]`,
  `ModeSpec.metric_cols: Tuple[str, ...]` — the ONLY declaration of a
  mode's leaderboard columns from this commit on.

- [ ] **Step 1: Add the three fields + `__post_init__` to `ModeSpec`**

In `core/modes.py`, after the `checks_managed_overlap: bool` field:

```python
    # Leaderboard schema (single source — ADR-0002 extension, 2026-07-19).
    # knob_names/knob_fmts: per-knob column names + per-position formats.
    # metric_cols: the FULL post-knob column tail; the ProdTarget family's
    # divergence (mu_per_POT/edep/peak-dose, no sob/calo/alpha) is data
    # here, not a special case. The leading `config` column is a writer
    # detail (golden (a) pins it).
    knob_names: Tuple[str, ...]
    knob_fmts: Tuple[str, ...]
    metric_cols: Tuple[str, ...]

    def __post_init__(self):
        if self.bounds_lo is not None:
            assert (len(self.knob_names) == len(self.knob_fmts)
                    == len(self.bounds_lo)), (
                f"{self.name}: knob_names ({len(self.knob_names)}) / "
                f"knob_fmts ({len(self.knob_fmts)}) / bounds "
                f"({len(self.bounds_lo)}) lockstep broken")
```

- [ ] **Step 2: Add the values to every SPECS entry** (verbatim from the
  driver literals being deleted; keyword args, so field order is safe)

```python
# foils:
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_rIn_up", "extra_rIn_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "calo", "alpha", "obj"),
# foilsf: same knob_fmts/metric_cols as foils, names end in f:
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_f_up", "extra_f_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "calo", "alpha", "obj"),
# foilsflash: same knob_names/knob_fmts as foilsf:
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_f_up", "extra_f_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "flash_edep", "alpha", "obj"),
# foilsg ((rOut, hT, f) per z-group, same *4 style as its bounds):
        knob_names=("rOut_g0", "hT_g0", "f_g0", "rOut_g1", "hT_g1", "f_g1",
                    "rOut_g2", "hT_g2", "f_g2", "rOut_g3", "hT_g3", "f_g3"),
        knob_fmts=("{:.4f}", "{:.6f}", "{:.4f}") * 4,
        metric_cols=("sob", "calo", "alpha", "obj"),
# prodtarget:
        knob_names=("r0", "r1", "r2", "t0", "t1", "t2",
                    "l0", "l1", "l2", "N"),
        knob_fmts=("{:.4f}",) * 9 + ("{:d}",),
        metric_cols=("mu_per_POT", "edep_per_POT_MeV",
                     "peak_dose_Gy_per_POT", "peak_plate_idx", "obj"),
# prodtarget6d:
        knob_names=("r0", "r1", "r2", "t0", "t1", "t2"),
        knob_fmts=("{:.4f}",) * 6,
        metric_cols=("mu_per_POT", "edep_per_POT_MeV",
                     "peak_dose_Gy_per_POT", "peak_plate_idx", "obj"),
```

- [ ] **Step 3: Rewire the driver to read the registry**

In `core/bo_driver.py`, replace the BOMode class-attr block
(`KNOB_FMTS: tuple` at :170, `CALO_COL = "calo"` at :171, and
`KNOB_NAMES: tuple = ()` at :190) with properties (keep the explanatory
comment block at :164-169, reworded to say the values live in
`modes.SPECS`):

```python
    @property
    def KNOB_NAMES(self) -> tuple:
        return _modes.SPECS[self.name].knob_names

    @property
    def KNOB_FMTS(self) -> tuple:
        return _modes.SPECS[self.name].knob_fmts

    @property
    def CALO_COL(self) -> str:
        # Foils-family second-objective column = metric_cols[1].
        return _modes.SPECS[self.name].metric_cols[1]
```

Derive both headers from `metric_cols`:

```python
# BOMode.format_row (:173-175):
    def format_row(self, p: Point, alpha: float) -> tuple[str, str]:
        cols = _modes.SPECS[self.name].metric_cols
        header = ("config\t" + "\t".join(self.KNOB_NAMES)
                  + "\t" + "\t".join(cols) + "\n")
# ProdTargetMode.format_row header (:1025-1028):
        header = ("config\t" + "\t".join(self.KNOB_NAMES)
                  + "\t" + "\t".join(_modes.SPECS[self.name].metric_cols)
                  + "\n")
```

Delete the now-shadowing per-class attrs (keep surrounding comments where
they explain geometry, condense where they only explained the schema):
`FoilsMode.KNOB_NAMES` (:394-396), `FoilsMode.KNOB_FMTS` (:519),
`FoilsFracMode.KNOB_NAMES` (:546-548), `FoilsFlashMode.CALO_COL` (:636),
`FoilsGroupMode.KNOB_NAMES`+`KNOB_FMTS` (:673-676),
`ProdTargetMode.KNOB_NAMES` (:907), `ProdTarget6DMode.KNOB_NAMES` (:1071).

Then verify nothing reads the attrs at class level (properties only work on
instances):

```bash
grep -rn "Mode\.KNOB_\|Mode\.CALO_COL" core/ graph/ tests/
```
Expected: no hits (fix any by going through the instance or
`modes.SPECS[...]` directly).

- [ ] **Step 4: Spec-derive the picker width-guard message**

In `core/botorch_predict.py:117-121`:

```python
        if X.shape[1] != len(spec["lo"]):
            raise SystemExit(
                f"[botorch_predict] mode={mode} dim mismatch: history has "
                f"{X.shape[1]}D points but modes.SPECS[{mode!r}] declares "
                f"{len(spec['lo'])}D bounds (knobs: "
                f"{_modes.SPECS[mode].knob_names}). Leaderboard schema and "
                f"registry disagree.")
```

- [ ] **Step 5: Add registry pins to `tests/test_modes.py`**

Append (inside the file's existing test-class conventions — add a new class):

```python
class TestSchemaFields(unittest.TestCase):
    def test_lockstep_enforced_at_construction(self):
        import dataclasses
        with self.assertRaises(AssertionError):
            dataclasses.replace(modes.SPECS["foils"], knob_names=("one",))

    def test_metric_cols_spot_pins(self):
        self.assertEqual(modes.SPECS["foilsflash"].metric_cols,
                         ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(modes.SPECS["foils"].metric_cols,
                         ("sob", "calo", "alpha", "obj"))
        self.assertEqual(
            modes.SPECS["prodtarget"].metric_cols,
            ("mu_per_POT", "edep_per_POT_MeV", "peak_dose_Gy_per_POT",
             "peak_plate_idx", "obj"))

    def test_driver_reads_registry(self):
        import bo_driver as bo
        for name, mode in bo.MODES.items():
            self.assertEqual(mode.KNOB_NAMES, modes.SPECS[name].knob_names)
            self.assertEqual(mode.KNOB_FMTS, modes.SPECS[name].knob_fmts)

    def test_calo_col_derives_from_metric_cols(self):
        import bo_driver as bo
        self.assertEqual(bo.MODES["foilsflash"].CALO_COL, "flash_edep")
        self.assertEqual(bo.MODES["foils"].CALO_COL, "calo")
```

(Match the import style at the top of `test_modes.py`; it already imports
`modes`.)

- [ ] **Step 6: Full suite + goldens**

Run the suite: expected ~185 OK.
Run: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b`
Expected: `[a] round-trip parity: OK`, `[b] picker parity: OK` (byte/exact —
this IS the "TSV bytes unchanged" proof for the refactor).

- [ ] **Step 7: Commit**

```bash
git add core/modes.py core/bo_driver.py core/botorch_predict.py tests/test_modes.py
git commit -m "refactor: leaderboard schema single-sourced into ModeSpec

knob_names/knob_fmts/metric_cols are registry data (all required,
lockstep asserted at construction); driver KNOB_NAMES/KNOB_FMTS/CALO_COL
are now registry-reading properties, both format_row headers derive from
metric_cols, picker width guard message is spec-derived. Goldens (a)+(b)
byte-identical; friction-survey candidate 3 resolved.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 6: Phase 2a — preflight verdict JSON

The preflight verdict crosses the seam as typed JSON; exit codes remain
only as a transport-failure backstop (decoded as `ambiguous`, which routes
to retry/human review and never silently passes).

**Files:**
- Modify: `core/bo_driver.py` (rename `cmd_preflight` → `_cmd_preflight_impl`
  at :1479; new wrapper + `write_json_atomic` + `PREFLIGHT_VERDICTS`;
  argparse `--emit-json` at :1717-1719),
  `graph/pipeline_io.py:104-130` (`run_preflight` reads JSON; rc-map deleted)
- Create: `tests/test_seam_protocol.py`

**Interfaces:**
- Consumes: `GRID_DATA_ROOT / <cfg> / "state"` (pipeline_io's existing
  state-dir convention, `pipeline_io.py:248`).
- Produces: `bo_driver.PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed",
  2: "fail_init", 3: "ambiguous"}`;
  `bo_driver.write_json_atomic(path: Path, payload: dict) -> None`;
  `state/<cfg>/preflight_verdict.json` with keys
  `{"verdict", "rc", "reasons", "log_path", "config"}`. Task 7 reuses
  `write_json_atomic`.

- [ ] **Step 1: Driver side**

In `core/bo_driver.py`, above `def cmd_preflight` (line 1479) add:

```python
# Preflight verdict vocabulary — the ONE home of the rc mapping (was
# duplicated as a decode dict in graph/pipeline_io.py).
PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init",
                      3: "ambiguous"}


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp+rename in the destination dir (readers never see
    a partial file; rename is atomic within one filesystem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
```

Rename `def cmd_preflight(args):` (line 1479) to
`def _cmd_preflight_impl(args):` (body unchanged), and add after its end
(line 1693, after `return 3`):

```python
def cmd_preflight(args):
    rc = _cmd_preflight_impl(args)
    if getattr(args, "emit_json", None):
        mode = MODES[args.mode]
        verdict = PREFLIGHT_VERDICTS.get(rc, "ambiguous")
        write_json_atomic(Path(args.emit_json), {
            "verdict": verdict,
            "rc": rc,
            # Coarse cause class; the log carries the detailed FAIL lines.
            "reasons": [f"preflight classifier verdict: {verdict} (rc={rc})"],
            "log_path": str(mode.preflight_dir / f"{args.config_name}.log"),
            "config": args.config_name,
        })
    return rc
```

In `main()` (line 1717-1719) add to the preflight subparser:

```python
    p_pre.add_argument("--emit-json", dest="emit_json", default=None,
                       help="Write the typed verdict JSON to this path "
                            "(graph seam; tmp+rename atomic)")
```

- [ ] **Step 2: Graph side — `run_preflight` reads the JSON**

Replace `graph/pipeline_io.py:104-130` with:

```python
def run_preflight(mode_name: str, config_name: str, timeout_s: int = PREFLIGHT_TIMEOUT_S) -> tuple[str, str]:
    """Run `bo_driver.py preflight <cfg>` and read the typed verdict JSON.

    Returns (status, log_tail). status ∈ {"pass", "fail_managed",
    "fail_init", "ambiguous", "timeout"}. A missing/unparseable JSON
    (process crash, transport failure) decodes as "ambiguous" with a loud
    reason — fail-safe: ambiguous routes to retry/human review and never
    silently passes.
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = state_dir / "preflight_verdict.json"
    verdict_path.unlink(missing_ok=True)  # never read a stale verdict
    cmd = [
        sys.executable,
        str(BO_DRIVER),
        "--mode", mode_name,
        "preflight", config_name,
        "--emit-json", str(verdict_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return "timeout", "(preflight timed out)"

    tail = "\n".join(proc.stdout.splitlines()[-80:])
    try:
        status = json.loads(verdict_path.read_text())["verdict"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        status = "ambiguous"
        tail = (f"(preflight verdict JSON missing/unparseable at "
                f"{verdict_path}: {e!r}; rc={proc.returncode} — decoding as "
                f"ambiguous)\n" + tail)
    return status, tail
```

(The `{0:..., 1:...}` rc-decode dict is gone with the replacement. Check
`graph/nodes.py` for a comment re-listing the rc map near its preflight
node and update the comment to point at `bo_driver.PREFLIGHT_VERDICTS`.)

- [ ] **Step 3: Tests**

Create `tests/test_seam_protocol.py`:

```python
"""Typed-JSON seam tests: preflight verdict (Phase 2a) and — from Task 7 —
evaluate result (Phase 2b). The driver subprocess is faked by writing (or
not writing) the JSON the way a real/crashed run would."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))
import bo_driver as bo  # noqa: E402
import pipeline_io as pio  # noqa: E402


class TestWriteJsonAtomic(unittest.TestCase):
    def test_writes_parseable_json_and_no_tmp_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "v.json"
            bo.write_json_atomic(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})
            self.assertEqual(list(p.parent.glob("*.tmp")), [])


class TestPreflightVerdictEmit(unittest.TestCase):
    def test_wrapper_emits_verdict_json(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(bo, "_cmd_preflight_impl", return_value=1):
            out = Path(tmp) / "preflight_verdict.json"
            rc = bo.cmd_preflight(SimpleNamespace(
                mode="foilsflash", config_name="cfgX", emit_json=str(out)))
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["verdict"], "fail_managed")
            self.assertEqual(payload["rc"], 1)
            self.assertEqual(payload["config"], "cfgX")
            self.assertTrue(payload["reasons"])
            self.assertIn("cfgX.log", payload["log_path"])

    def test_no_emit_json_attr_is_fine(self):
        with mock.patch.object(bo, "_cmd_preflight_impl", return_value=0):
            rc = bo.cmd_preflight(SimpleNamespace(mode="foilsflash",
                                                  config_name="cfgX"))
            self.assertEqual(rc, 0)


def _fake_run(write_json=None, rc=0):
    """subprocess.run stand-in: optionally writes the verdict JSON the way
    the driver would, then returns a completed-process shim."""
    def run(cmd, **kw):
        if write_json is not None:
            i = cmd.index("--emit-json")
            bo.write_json_atomic(Path(cmd[i + 1]), write_json)
        return SimpleNamespace(returncode=rc, stdout="tail line\n", stderr="")
    return run


class TestRunPreflightReadsJson(unittest.TestCase):
    def _call(self, tmp, runner):
        with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
             mock.patch.object(pio.subprocess, "run", side_effect=runner):
            return pio.run_preflight("foilsflash", "cfgX")

    def test_valid_json_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, _ = self._call(tmp, _fake_run(
                {"verdict": "fail_init", "rc": 2, "reasons": [],
                 "log_path": "x", "config": "cfgX"}, rc=2))
            self.assertEqual(status, "fail_init")

    def test_missing_json_decodes_ambiguous_with_loud_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, tail = self._call(tmp, _fake_run(None, rc=0))
            self.assertEqual(status, "ambiguous")
            self.assertIn("missing/unparseable", tail)

    def test_stale_verdict_from_prior_run_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "cfgX" / "state" / "preflight_verdict.json"
            bo.write_json_atomic(stale, {"verdict": "pass", "rc": 0})
            status, _ = self._call(tmp, _fake_run(None, rc=1))
            self.assertEqual(status, "ambiguous")  # stale "pass" not trusted


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Full suite + goldens + re-capture (c)**

Suite: ~191 OK.
`PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b` → OK.
Re-capture (c) so the baseline gains the verdict JSON (rc + verdict line
must equal the old baseline — eyeball the diff before overwriting):
`PYTHONPATH= .venv/bin/python tests/golden_parity.py capture c`
(the harness passes no `emit_json` attr in-process, so the preflight replay
pins the rc/verdict-line path; the JSON transport is pinned by the unit
tests above).

- [ ] **Step 5: Commit**

```bash
git add core/bo_driver.py graph/pipeline_io.py tests/test_seam_protocol.py tests/goldens/seam_replay_baseline.json
git commit -m "feat: preflight verdict crosses the seam as typed JSON

bo_driver preflight --emit-json writes state/<cfg>/preflight_verdict.json
(atomic tmp+rename); run_preflight reads it, deletes the rc-decode dict,
and decodes transport failure as loud 'ambiguous' (fail-safe). Stale
verdicts are unlinked pre-run.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 7: Phase 2b — evaluate result JSON; stdout regex deleted

**Files:**
- Modify: `core/bo_driver.py` (`cmd_evaluate` emits JSON at :1293-1335;
  evaluate subparser `--emit-json` at :1712-1715),
  `graph/pipeline_io.py:399-426` (`run_evaluate` reads JSON; regex deleted)
- Modify: `tests/test_seam_protocol.py` (evaluate-side tests)

**Interfaces:**
- Consumes: `bo_driver.write_json_atomic`, `Point.obj(alpha)`.
- Produces: `state/<cfg>/evaluate_result.json` with keys
  `{"config": str, "obj": float, "sob": float, "calo_or_flash": float,
  "row_appended": true}` — written ONLY on the success path (a run that
  returns rc≠0 appended nothing and emits nothing).

- [ ] **Step 1: Driver side**

In `core/bo_driver.py` `cmd_evaluate`, after `mode.append_history(p, args.alpha)`
(line 1331) and before the `pend_tag` line:

```python
    if getattr(args, "emit_json", None):
        write_json_atomic(Path(args.emit_json), {
            "config": p.cfg,
            "obj": p.obj(args.alpha),
            "sob": p.sob,
            "calo_or_flash": p.calo,
            "row_appended": True,
        })
```

In `main()` (evaluate subparser, :1712-1715) add:

```python
    p_eval.add_argument("--emit-json", dest="emit_json", default=None,
                        help="Write the typed result JSON to this path "
                             "(graph seam; written only after the row lands)")
```

- [ ] **Step 2: Graph side — `run_evaluate` reads JSON, regex dies**

Replace `graph/pipeline_io.py:399-426` with:

```python
def run_evaluate(mode_name: str, config_name: str, metrics: dict,
                 alpha: float = DEFAULT_ALPHA) -> tuple[float | None, str]:
    """Write metrics to a tmp summary.json, call the driver's evaluate verb,
    and read the objective from the typed result JSON.

    Contract: rc != 0 → the driver refused (missing metrics, bad geom…) and
    appended nothing → return (None, tail) — callers already treat that as
    a zero_row. rc == 0 with missing/unparseable JSON is a HARD error: a
    run that cannot prove it recorded a row already is one.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"graph_eval_{config_name}_"))
    summary_path = tmp / "summary.json"
    summary_path.write_text(json.dumps(metrics, indent=2))
    result_path = GRID_DATA_ROOT / config_name / "state" / "evaluate_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)  # never read a stale result

    cmd = [
        sys.executable,
        str(BO_DRIVER),
        "--mode", mode_name,
        "--alpha", f"{alpha}",
        "evaluate", config_name, str(summary_path),
        "--emit-json", str(result_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])

    if proc.returncode != 0:
        return None, tail
    try:
        return float(json.loads(result_path.read_text())["obj"]), tail
    except (FileNotFoundError, json.JSONDecodeError, KeyError,
            TypeError, ValueError) as e:
        raise RuntimeError(
            f"evaluate rc=0 but result JSON missing/unparseable at "
            f"{result_path}: {e!r}; stdout tail:\n{tail}")
```

Then confirm the module still needs its `re` import
(`grep -n "re\." graph/pipeline_io.py` — the `_SCAN_PATTERNS` scanner uses
it; keep).

- [ ] **Step 3: Evaluate-side tests** (append to `tests/test_seam_protocol.py`)

```python
class TestCmdEvaluateEmit(unittest.TestCase):
    def _tmp_mode(self, tmp):
        mode = bo.MODES["foilsflash"]
        patches = [
            mock.patch.object(mode, "leaderboard",
                              Path(tmp) / "leaderboard_bo_foilsflash.tsv"),
            mock.patch.object(mode, "proposal_dir", Path(tmp) / "proposals"),
        ]
        return mode, patches

    def test_success_appends_row_and_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                x = [100.0, 100.0, 0.05, 0.05, 0.5, 0.5]
                mode.render_proposal("cfgE", x)
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps(
                    {"s_over_sqrt_b": 3.5, "flash_edep_per_pot": 1e-6}))
                out = Path(tmp) / "evaluate_result.json"
                rc = bo.cmd_evaluate(SimpleNamespace(
                    mode="foilsflash", config_name="cfgE",
                    summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                    emit_json=str(out)))
                self.assertEqual(rc, 0)
                self.assertIn("cfgE\t", mode.leaderboard.read_text())
                payload = json.loads(out.read_text())
                self.assertEqual(payload["config"], "cfgE")
                self.assertTrue(payload["row_appended"])
                self.assertAlmostEqual(payload["sob"], 3.5)

    def test_refusal_emits_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps({"s_over_sqrt_b": 3.5}))
                out = Path(tmp) / "evaluate_result.json"
                # flash edep missing → extract_metrics SystemExit → refusal
                with self.assertRaises(SystemExit):
                    bo.cmd_evaluate(SimpleNamespace(
                        mode="foilsflash", config_name="cfgE",
                        summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                        emit_json=str(out)))
                self.assertFalse(out.exists())


def _fake_eval_run(write_json=None, rc=0):
    def run(cmd, **kw):
        if write_json is not None:
            i = cmd.index("--emit-json")
            bo.write_json_atomic(Path(cmd[i + 1]), write_json)
        return SimpleNamespace(returncode=rc, stdout="tail\n", stderr="")
    return run


class TestRunEvaluateReadsJson(unittest.TestCase):
    def _call(self, tmp, runner):
        with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
             mock.patch.object(pio.subprocess, "run", side_effect=runner):
            return pio.run_evaluate("foilsflash", "cfgX",
                                    {"s_over_sqrt_b": 1.0})

    def test_obj_comes_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj, _ = self._call(tmp, _fake_eval_run(
                {"config": "cfgX", "obj": 1.234, "sob": 1.2,
                 "calo_or_flash": 1e-6, "row_appended": True}, rc=0))
            self.assertEqual(obj, 1.234)

    def test_rc_nonzero_returns_none_unchanged_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj, tail = self._call(tmp, _fake_eval_run(None, rc=1))
            self.assertIsNone(obj)
            self.assertIn("tail", tail)

    def test_rc_zero_without_json_is_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self._call(tmp, _fake_eval_run(None, rc=0))
```

- [ ] **Step 4: Full suite + goldens + re-capture (c)**

Suite: ~197 OK.
`check a b` → OK. Re-capture (c): the harness's evaluate replay can now set
`emit_json` — update `section_c` to pass
`emit_json=str(tmp / "evaluate_result.json")` in the SimpleNamespace so the
baseline records the JSON payload too, then
`capture c` and eyeball that rc/obj/appended_line are unchanged vs the
previous baseline before committing.

- [ ] **Step 5: Commit**

```bash
git add core/bo_driver.py graph/pipeline_io.py tests/test_seam_protocol.py tests/golden_parity.py tests/goldens/seam_replay_baseline.json
git commit -m "feat: evaluate result crosses the seam as typed JSON; obj regex deleted

cmd_evaluate --emit-json writes state/<cfg>/evaluate_result.json only
after the row lands; run_evaluate reads obj from it. rc!=0 keeps the
(None, tail) zero_row contract; rc==0 without JSON is a hard error. The
`obj=` stdout regex is gone.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 8: Live smokes + wiki sweep

**Files:**
- Modify: `wiki/concepts/architecture-friction-survey-2026-07.md`,
  `wiki/concepts/ml-stack-review-2026-07.md`,
  `wiki/concepts/simplification-audit-2026-07.md`,
  `wiki/drivers/tests.md`, `wiki/index.md`, `wiki/log.md`,
  `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`
  (status → implemented + one honest verification note, below)

**Interfaces:** none (verification + records).

- [ ] **Step 1: Precondition**

`ps -fu $USER -ww | grep "[c]losed_loop"` → must be empty.

- [ ] **Step 2: Live picker smoke (read-only)**

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import bo_driver as bo
xs = bo.botorch_ask('foilsflash', q=2, seed_idx=0, picker='hybrid')
print('picks:', xs); assert len(xs) == 2 and all(len(x) == 6 for x in xs)"
```
Expected: 2 in-bounds picks off the live leaderboard (~1-3 min).

- [ ] **Step 3: Mock chain smoke**

```bash
wc -l leaderboards/leaderboard_bo_foilsflash.tsv leaderboards/pending_bo_foilsflash.tsv
PYTHONPATH= .venv/bin/python -m graph.run --mock --mode foilsflash \
  --thread-id protoSMOKE1 --config-name protoSMOKE1 2>&1 | tail -20
```
Expected: chain reaches END without traceback. KNOWN QUIRK (recorded
2026-07-18, unchanged by this round): the foilsflash mock summary carries
only `calo_per_pot`, so the driver's evaluate REFUSES (flash-edep guard,
rc≠0) → `run_evaluate` returns `(None, tail)` → the graph records
`zero_row cause=obj_unparseable`-class outcome and NO leaderboard row.
This is the rc≠0 transport path working as designed; the JSON SUCCESS
paths are pinned by `tests/test_seam_protocol.py` and golden (c). Note:
the mock path also bypasses preflight, so preflight-JSON coverage comes
from golden (c)'s real replay, not this smoke.
Cleanup the smoke's pending row (cp not mv — preserves the flock inode):

```bash
grep -v "protoSMOKE1" leaderboards/pending_bo_foilsflash.tsv > /tmp/pend.tmp
cp /tmp/pend.tmp leaderboards/pending_bo_foilsflash.tsv
wc -l leaderboards/leaderboard_bo_foilsflash.tsv leaderboards/pending_bo_foilsflash.tsv
```
Leaderboard line count must equal the pre-smoke count.

- [ ] **Step 4: Amend the spec's verification wording (one honest note)**

In `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`,
set `Status: implemented 2026-07-19` and amend the Verification bullet
"one full `graph.run --mock` chain (exercises preflight-JSON →
evaluate-JSON end-to-end...)" with:
"(Implementation note 2026-07-19: the mock path bypasses preflight and the
foilsflash mock evaluate refuses pre-append by design, so the mock chain
verifies graph wiring + the rc≠0 transport path; the JSON success paths
are covered by tests/test_seam_protocol.py and golden (c)'s real replay.)"

- [ ] **Step 5: Wiki sweep** (each page: bump `timestamp:`, keep
  `description:` mirrored in `index.md`; `log.md` bullet under `## 2026-07-19`
  at the TOP)

- `architecture-friction-survey-2026-07.md`: candidates 3 (leaderboard
  schema) and 4 (typed JSON protocol) → RESOLVED 2026-07-19 with commit
  refs; the "pipeline.py and botorch_predict.py have ZERO test imports"
  fact → resolved note pointing at the three new test files; description
  updated accordingly.
- `ml-stack-review-2026-07.md`: the picker-untested gap note → resolved
  (unit tests + seam smoke in main suite).
- `simplification-audit-2026-07.md`: the Tier-2 "Verification note"
  (`botorch_predict.py still has zero unit tests`) → superseded note with
  date.
- `drivers/tests.md`: rewrite the summary/key-facts counts (now 10 test
  files + final test count from Task 7's suite run; golden harness usage
  line: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check`);
  description + index one-liner updated to the new counts.
- `index.md`: sync the three concept one-liners + tests one-liner.
- `log.md`: one bullet: tests/schema/protocol round landed — schema in
  ModeSpec, JSON seam, N new tests, goldens byte-identical, commit range.

- [ ] **Step 6: Final suite run + commit**

Full suite one last time (must be green; note the final count).

```bash
git add wiki/concepts/architecture-friction-survey-2026-07.md wiki/concepts/ml-stack-review-2026-07.md wiki/concepts/simplification-audit-2026-07.md wiki/drivers/tests.md wiki/index.md wiki/log.md docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md
git commit -m "docs(wiki): tests/schema/protocol round recorded; friction candidates 3+4 resolved

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

Report to the user: commits made, final test count, goldens status
(exact vs allclose on (b)), the known mock-chain quirk unchanged, and that
everything is local awaiting their `git push`. The follow-on slimming
round (spec `2026-07-19-slim-shrink-sweep-design.md`) starts as its own
plan only after this one is reviewed as landed.
