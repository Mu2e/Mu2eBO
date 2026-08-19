"""Unit tests for the parent rolling work-pool.

Replaces ~1,470 LOC that tested five agreeing signal sources (checkpoint
terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard membership). The
pool has ONE: a child resolves when its subprocess exits. run_child is an
injected callable, so none of this touches the grid, sqlite, or a subprocess.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))

# pool.py's default row_landed/broken/pick-source callables lazily `import
# closed_loop`, which (via graph/config.py) resolves AUTORESEARCH_MODE
# against modes.SPECS at import time; "foils" (the module-level fallback) is
# dangling (retired 2026-08-08). Every test below passes its own
# run_child/next_pick fakes but not always row_landed/broken, so the lazy
# import can fire. Same pattern as tests/test_no_mock_mode.py.
os.environ.setdefault("AUTORESEARCH_MODE", "foilspf")

import pool  # noqa: E402


def _picker(n_dims=2):
    """Deterministic pick source: x is [i, i], name is c{i}."""
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        i = counter["i"]
        counter["i"] += 1
        return [float(i)] * n_dims, f"c{i}"
    return next_pick, counter


# Neutral broken= fake: MINOR 10 (review round 2) -- without this, five of
# seven original test_pool.py cases fell through to _default_broken, which
# stats real paths under the live grid data root. Read-only, so not a
# constraint violation, but it left half the injection seam unused and made
# unit tests depend on operator environment state.
_NOT_BROKEN = lambda name: False  # noqa: E731


class TestPoolWidth(unittest.TestCase):
    def test_never_exceeds_q_in_flight(self):
        # Two independent checks: the executor's own max_workers=q bound
        # (peak concurrent run_child calls), AND run_rolling's OWN
        # len(inflight) < q bookkeeping, observed via the x_pending list
        # every next_pick call receives (MINOR 11, review round 2: the
        # peak-thread check alone would still pass even if run_rolling's own
        # throttling were deleted, since ThreadPoolExecutor(max_workers=q)
        # mechanically caps concurrency on its own).
        peak = {"n": 0}
        lock = threading.Lock()
        gate = threading.Event()
        pending_sizes = []

        def run_child(name, x):
            with lock:
                peak["n"] += 1
                peak["max"] = max(peak.get("max", 0), peak["n"])
            gate.wait(timeout=5)
            with lock:
                peak["n"] -= 1
            return 0

        counter = {"i": 0}

        def next_pick(mode, picker, x_pending):
            pending_sizes.append(len(x_pending))
            i = counter["i"]
            counter["i"] += 1
            return [float(i)] * 2, f"c{i}"

        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=9, alpha=1.0,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None,
                         broken=_NOT_BROKEN, stagger=0)
        t.cancel()
        self.assertLessEqual(peak["max"], 3)
        # x_pending is the in-flight set BEFORE this pick is added, so it
        # must never reach q (3) -- reaching q would mean run_rolling was
        # about to push a 4th child into a pool of width 3.
        self.assertTrue(pending_sizes)
        self.assertLessEqual(max(pending_sizes), 2)


class TestReplenish(unittest.TestCase):
    def test_one_resolution_triggers_exactly_one_new_pick(self):
        next_pick, counter = _picker()
        pool.run_rolling(mode="m", picker="p", q=2, max_evals=5, alpha=1.0,
                         name_prefix="t", run_child=lambda n, x: 0,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None,
                         broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(counter["i"], 5)

    def test_x_pending_equals_in_flight_set(self):
        seen = []
        gate = threading.Event()

        def run_child(name, x):
            gate.wait(timeout=5)
            return 0

        def next_pick(mode, picker, x_pending):
            seen.append([list(v) for v in x_pending])
            i = len(seen) - 1
            return [float(i)], f"c{i}"

        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=3, alpha=1.0,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None,
                         broken=_NOT_BROKEN, stagger=0)
        t.cancel()
        self.assertEqual(seen[0], [])
        self.assertEqual(seen[1], [[0.0]])
        self.assertEqual(seen[2], [[0.0], [1.0]])


class TestDrain(unittest.TestCase):
    def test_loop_drains_inflight_before_exiting(self):
        """The final-round orphan-children fix, as an assertion."""
        finished = []

        def run_child(name, x):
            finished.append(name)
            return 0

        next_pick, _ = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=4, max_evals=4,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False, renew=lambda: None,
                               broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(len(finished), 4)
        self.assertEqual(len(res["outcomes"]), 4)


class TestNoRowStreak(unittest.TestCase):
    def test_streak_increments_on_rowless_and_resets_on_row(self):
        """Each child's outcome is observed as it resolves; there are no wave
        baselines for a row to be absorbed into. That is the root fix for
        rolling-no-row-streak-false-increment."""
        rows = {"c0": False, "c1": True, "c2": False}
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=1, max_evals=3, alpha=1.0,
            name_prefix="t",
            run_child=lambda n, x: 0 if rows.get(n) else 1,
            next_pick=next_pick,
            stop_flag=lambda: False, renew=lambda: None,
            row_landed=lambda name, mode: rows.get(name, False),
            broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(res["rows"], 1)
        self.assertFalse(res["aborted"])

    def test_q_consecutive_rowless_aborts(self):
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=2, max_evals=10, alpha=1.0,
            name_prefix="t", run_child=lambda n, x: 1,
            next_pick=next_pick,
            stop_flag=lambda: False, renew=lambda: None,
            row_landed=lambda name, mode: False,
            broken=_NOT_BROKEN, stagger=0)
        self.assertTrue(res["aborted"])
        self.assertLess(res["launched"], 10)


class TestAbortThreshold(unittest.TestCase):
    """Pins `_should_abort`'s formula directly (MINOR 8, review round 2):
    q=1 requires TWO consecutive rowless resolutions, q>1 requires exactly
    q. Extracted to a pure function specifically so this doesn't need to be
    proven by racing a real thread pool -- test_q_consecutive_rowless_aborts
    above only pins "it aborts eventually", not the exact threshold."""

    def test_q1_requires_two_not_one(self):
        self.assertFalse(pool._should_abort(streak=1, q=1))
        self.assertTrue(pool._should_abort(streak=2, q=1))

    def test_q_gt_1_requires_exactly_q(self):
        self.assertFalse(pool._should_abort(streak=2, q=3))
        self.assertTrue(pool._should_abort(streak=3, q=3))

    def test_q20_requires_exactly_20_not_21(self):
        # The regression this guards: `streak > q` (review round 1's fix)
        # required q+1=21 at q=20 -- over half a 40-eval budget before
        # aborting, where the intent was 20.
        self.assertFalse(pool._should_abort(streak=20, q=21))
        self.assertTrue(pool._should_abort(streak=20, q=20))


class TestStopFlag(unittest.TestCase):
    def test_stop_halts_topup_but_still_drains(self):
        stop = {"v": False}
        done = []

        def run_child(name, x):
            done.append(name)
            stop["v"] = True
            return 0

        next_pick, counter = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=2, max_evals=20,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: stop["v"],
                               renew=lambda: None,
                               broken=_NOT_BROKEN, stagger=0)
        self.assertLess(res["launched"], 20)
        self.assertEqual(len(res["outcomes"]), len(done))


class TestRenewHook(unittest.TestCase):
    """The `renew` injection point fires before every launch (not once per
    round -- there are no rounds). See graph/closed_loop.py's `renew_token`,
    which run_rolling's production caller wires in as `renew=renew_token`;
    a fatal renewal failure (kinit/getToken) must not be swallowed."""

    def test_renew_called_once_per_launch(self):
        calls = {"n": 0}

        def renew():
            calls["n"] += 1

        next_pick, _ = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=3, max_evals=7,
                               alpha=1.0, name_prefix="t",
                               run_child=lambda n, x: 0, next_pick=next_pick,
                               stop_flag=lambda: False, renew=renew,
                               broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(calls["n"], res["launched"])
        self.assertEqual(calls["n"], 7)

    def test_renew_failure_propagates_not_swallowed(self):
        def renew():
            raise RuntimeError("getToken rc=1: krb5 expired")

        next_pick, _ = _picker()
        with self.assertRaises(RuntimeError):
            pool.run_rolling(mode="m", picker="p", q=2, max_evals=5,
                             alpha=1.0, name_prefix="t",
                             run_child=lambda n, x: 0, next_pick=next_pick,
                             stop_flag=lambda: False, renew=renew,
                             broken=_NOT_BROKEN, stagger=0)


class TestStagger(unittest.TestCase):
    """IMPORTANT 4, review round 2: node_launch_children's 90s inter-launch
    stagger (concurrent-token-contention.md) was dropped in the pool
    rewrite. run_rolling now takes an explicit `stagger` seconds parameter,
    slept between launches (not before the first)."""

    def test_stagger_zero_does_not_sleep(self):
        # Sanity: the whole rest of this suite relies on stagger=0 being a
        # real no-op, not merely "small". If this regresses, every timed
        # test in this file (gate.wait(timeout=5) etc.) becomes flaky.
        next_pick, _ = _picker()
        with mock.patch.object(pool.time, "sleep") as m:
            pool.run_rolling(mode="m", picker="p", q=2, max_evals=4,
                             alpha=1.0, name_prefix="t",
                             run_child=lambda n, x: 0, next_pick=next_pick,
                             stop_flag=lambda: False, renew=lambda: None,
                             broken=_NOT_BROKEN, stagger=0)
        m.assert_not_called()

    def test_stagger_sleeps_between_but_not_before_first_launch(self):
        next_pick, _ = _picker()
        with mock.patch.object(pool.time, "sleep") as m:
            res = pool.run_rolling(mode="m", picker="p", q=1, max_evals=3,
                                   alpha=1.0, name_prefix="t",
                                   run_child=lambda n, x: 0,
                                   next_pick=next_pick,
                                   stop_flag=lambda: False,
                                   renew=lambda: None,
                                   broken=_NOT_BROKEN, stagger=42)
        # 3 launches -> 2 gaps between them, none before the first.
        self.assertEqual(m.call_args_list, [mock.call(42), mock.call(42)])
        self.assertEqual(res["launched"], 3)

    def test_default_stagger_comes_from_config(self):
        next_pick, _ = _picker()
        with mock.patch.object(pool.time, "sleep") as m:
            pool.run_rolling(mode="m", picker="p", q=1, max_evals=2,
                             alpha=1.0, name_prefix="t",
                             run_child=lambda n, x: 0, next_pick=next_pick,
                             stop_flag=lambda: False, renew=lambda: None,
                             broken=_NOT_BROKEN)  # stagger omitted
        import config
        m.assert_called_once_with(config.CLOSED_LOOP_STAGGER_SEC)


class TestNameSkip(unittest.TestCase):
    """CRITICAL 1, review round 2: _default_pick_source must skip any
    candidate name already resolved by a PRIOR run under the same
    --name-prefix -- the standard recovery move in this project. Without
    this, a fresh in-process counter starting at i=0 collides with the
    prior run's names, and _default_row_landed/_default_broken then read
    the OLD run's outcome for the NEW child: a campaign where every child
    fails could still report rows=launched, aborted=False if every name
    happens to be a prior success."""

    def test_skips_name_already_in_leaderboard(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with mock.patch.object(cl, "_leaderboard_names",
                               return_value={"fooR00_00"}), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=[(1.0, 2.0)]):
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_skips_broken_name(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken",
                               side_effect=lambda n: n == "fooR00_00"), \
             mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=[(1.0, 2.0)]):
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_skips_multiple_consecutive_collisions(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with mock.patch.object(cl, "_leaderboard_names",
                               return_value={"fooR00_00", "fooR01_00",
                                             "fooR02_00"}), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=[(1.0, 2.0)]):
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR03_00")

    def test_no_collision_uses_first_name(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=[(1.0, 2.0)]) as m:
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR00_00")
        self.assertEqual(x, [1.0, 2.0])
        # round_idx passed to the picker subprocess is the POST-skip index.
        self.assertEqual(m.call_args.kwargs["round_idx"], 0)


class TestDefaultRowLanded(unittest.TestCase):
    """IMPORTANT 2, review round 2: _default_row_landed must fail CLOSED
    (return False / propagate) on a real error, and only special-case the
    synthetic-test-mode KeyError, narrowly."""

    def test_unregistered_mode_returns_true(self):
        # tests/test_pool.py's own mode="m" -- production main() never
        # reaches this branch (argparse restricts --mode to real modes).
        self.assertTrue(pool._default_row_landed("c0", "definitely-not-a-real-mode"))

    def test_real_mode_membership(self):
        import closed_loop as cl
        with mock.patch.object(cl, "_leaderboard_names",
                               return_value={"foilspfR00_00"}):
            self.assertTrue(pool._default_row_landed("foilspfR00_00", "foilspf"))
            self.assertFalse(pool._default_row_landed("foilspfR00_01", "foilspf"))

    def test_real_error_inside_load_history_propagates(self):
        # A genuine failure reading a REGISTERED mode's leaderboard must not
        # be swallowed into "landed=True" -- that would fail the no-row-
        # streak abort guard open on the one signal it reads.
        import closed_loop as cl
        with mock.patch.object(cl, "_leaderboard_names",
                               side_effect=KeyError("cfg")):
            with self.assertRaises(KeyError):
                pool._default_row_landed("foilspfR00_00", "foilspf")


class TestDefaultRunChild(unittest.TestCase):
    """IMPORTANT 6, review round 2: the production launch path
    (_default_run_child) had zero tests. subprocess.Popen is stubbed -- no
    grid contact. Covers the argv shape the deleted
    TestUniqueThreadIdPerLaunch used to pin (--config-name vs --thread-id,
    --x-point %.6f formatting, --mode, --alpha, start_new_session=True,
    cwd) plus the log-handle-closing behavior (one leaked fd per child over
    a 40-eval campaign would exhaust the parent's ulimit)."""

    def test_argv_shape_and_popen_kwargs(self):
        import config
        captured = {}

        class _FakeProc:
            def __init__(self, cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                captured["stdout_open_at_popen"] = not kwargs["stdout"].closed

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(config, "GRAPH_DATA", tmp), \
                 mock.patch.object(config, "PROJECT_ROOT", tmp), \
                 mock.patch.object(pool.subprocess, "Popen", _FakeProc):
                run_child = pool._default_run_child("foilspf", 1.0e5)
                rc = run_child("fooR00_00", [1.0, 2.5, -3.0])

        self.assertEqual(rc, 0)
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1:3], ["-m", "graph.run"])
        self.assertEqual(cmd[cmd.index("--config-name") + 1], "fooR00_00")
        tid = cmd[cmd.index("--thread-id") + 1]
        self.assertNotEqual(tid, "fooR00_00",
                            "thread_id must not equal config_name (collision risk)")
        self.assertTrue(tid.startswith("fooR00_00_"))
        self.assertEqual(cmd[cmd.index("--mode") + 1], "foilspf")
        self.assertEqual(cmd[cmd.index("--alpha") + 1], str(1.0e5))
        self.assertEqual(cmd[cmd.index("--x-point") + 1],
                         "1.000000,2.500000,-3.000000")
        self.assertTrue(captured["kwargs"]["start_new_session"])
        self.assertEqual(captured["kwargs"]["cwd"], str(tmp))
        self.assertTrue(captured["stdout_open_at_popen"],
                        "child must receive an OPEN handle to write to")
        self.assertTrue(captured["kwargs"]["stdout"].closed,
                        "parent must not leak its copy of the child's log handle")

    def test_log_file_written_under_graph_data(self):
        import config

        class _FakeProc:
            def __init__(self, cmd, **kwargs):
                pass

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(config, "GRAPH_DATA", tmp), \
                 mock.patch.object(config, "PROJECT_ROOT", tmp), \
                 mock.patch.object(pool.subprocess, "Popen", _FakeProc):
                run_child = pool._default_run_child("foilspf", 1.0e5)
                run_child("fooR00_00", [1.0])
            self.assertTrue((tmp / "closed_loop_logs" / "fooR00_00.log").exists())


if __name__ == "__main__":
    unittest.main()
