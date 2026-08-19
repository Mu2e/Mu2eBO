"""Unit tests for the parent rolling work-pool.

Replaces ~1,470 LOC that tested five agreeing signal sources (checkpoint
terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard membership). The
pool has ONE: a child resolves when its subprocess exits. run_child is an
injected callable, so none of this touches the grid, sqlite, or a subprocess.
"""
import contextlib
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
# closed_loop`, which (via core/runtime.py) resolves AUTORESEARCH_MODE
# against modes.SPECS at import time. Every test below passes its own
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
    """The `renew` injection point fires before every launch AND at every
    resolution (not once per round -- there are no rounds; and not
    launch-only, or the drain runs unrenewed -- finding M7). See
    graph/closed_loop.py's `renew_token`, which run_rolling's production
    caller wires in as `renew=renew_token` and which is time-gated
    internally, so the extra call sites cost nothing; a fatal renewal
    failure (kinit/getToken) must not be swallowed."""

    def test_renew_called_at_every_launch_and_every_resolution(self):
        calls = {"n": 0}

        def renew():
            calls["n"] += 1

        next_pick, _ = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=3, max_evals=7,
                               alpha=1.0, name_prefix="t",
                               run_child=lambda n, x: 0, next_pick=next_pick,
                               stop_flag=lambda: False, renew=renew,
                               broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(res["launched"], 7)
        self.assertEqual(len(res["outcomes"]), 7)
        self.assertEqual(calls["n"], 14)  # 7 launches + 7 resolutions

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
        import runtime
        m.assert_called_once_with(runtime.CLOSED_LOOP_STAGGER_SEC)


class TestNameSkip(unittest.TestCase):
    """CRITICAL 1, review round 2 + finding C1, final review:
    _default_pick_source must skip any candidate name a PRIOR run under the
    same --name-prefix already RESOLVED (leaderboard row / broken.txt) or
    still has WORK IN FLIGHT for (*_cluster.txt / pending TSV row).
    Relaunching under the same prefix is the standard recovery move here.

    Without the resolution half, a fresh in-process counter starting at i=0
    collides with the prior run's names and _default_row_landed/
    _default_broken read the OLD run's outcome for the NEW child. Without
    the in-flight half, a second graph.run launches alongside a surviving
    detached child, re-uses its cluster files, and lands TWO leaderboard
    rows under one name -- both carrying the FIRST child's metrics.
    """

    def setUp(self):
        # Hermetic: neither the live grid state root nor the live pending
        # TSV may decide a unit test. Each case overrides as needed.
        self._td = tempfile.TemporaryDirectory()
        self.state_root = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _state_dir(self, name):
        d = self.state_root / name / "state"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _patches(self, cl, *, lb=frozenset(), broken=(), pending=frozenset(),
                 picks=((1.0, 2.0),)):
        return (
            mock.patch.object(cl, "_leaderboard_names",
                              return_value=set(lb)),
            mock.patch.object(cl, "_child_is_broken",
                              side_effect=lambda n: n in broken),
            mock.patch.object(cl, "_child_state_dir",
                              side_effect=self._state_dir),
            mock.patch.object(pool, "_pending_names",
                              return_value=set(pending)),
            mock.patch.object(cl, "_botorch_picks_subprocess",
                              return_value=list(picks)),
        )

    def test_skips_name_already_in_leaderboard(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl, lb={"fooR00_00"}):
                st.enter_context(p)
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_skips_broken_name(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl, broken={"fooR00_00"}):
                st.enter_context(p)
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_skips_name_with_stale_cluster_file(self):
        """Finding C1: a surviving child from a crashed parent has NO
        leaderboard row and NO broken.txt -- its only trace is the
        `<stage>_cluster.txt` its submit wrote. Launching a second
        graph.run under that name double-submits and lands two corrupt
        rows. FAILS without the *_cluster.txt condition in
        _name_busy_reason (the pool hands back fooR00_00)."""
        import closed_loop as cl
        (self._state_dir("fooR00_00") / "mubeam_cluster.txt").write_text("12345\n")
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl):
                st.enter_context(p)
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_cluster_skip_logs_the_recovery_recipe(self):
        """Finding I3's diagnostic half: the deleted STALE_CLUSTER
        Resolution carried an actionable message; the skip must too."""
        import closed_loop as cl
        sd = self._state_dir("fooR00_00")
        (sd / "mustops_ce_cluster.txt").write_text("999\n")
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl):
                st.enter_context(p)
            buf = st.enter_context(mock.patch("builtins.print"))
            next_pick("foilspf", "hybrid", [])
        printed = " ".join(str(c.args[0]) for c in buf.call_args_list)
        self.assertIn("fooR00_00", printed)
        self.assertIn(str(sd), printed)
        self.assertIn("_cluster.txt", printed)
        self.assertIn("--name-prefix", printed)

    def test_skips_name_with_unresolved_pending_row(self):
        """The pre-submit half of the same window: a prior child that died
        in propose/preflight has a pending TSV row and nothing else."""
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl, pending={"fooR00_00"}):
                st.enter_context(p)
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR01_00")

    def test_skips_multiple_consecutive_collisions(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl, lb={"fooR00_00", "fooR02_00"},
                                   pending={"fooR01_00"}):
                st.enter_context(p)
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR03_00")

    def test_skip_always_yields_a_name_never_an_empty_launch(self):
        """The monotonic-counter property that makes this safe: unlike the
        retired node_launch_children (which filtered a FIXED list of q names
        and could end with pending == [] -- closed-loop-stale-cluster-
        silent-no-launch), a skip here ADVANCES to a fresh index. Every
        next_pick returns a usable name, however many are busy."""
        import closed_loop as cl
        busy = {f"fooR{i:02d}_00" for i in range(7)}
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            for p in self._patches(cl, lb=busy):
                st.enter_context(p)
            names = [next_pick("foilspf", "hybrid", [])[1] for _ in range(3)]
        self.assertEqual(names, ["fooR07_00", "fooR08_00", "fooR09_00"])

    def test_no_collision_uses_first_name(self):
        import closed_loop as cl
        next_pick = pool._default_pick_source("foo")
        with contextlib.ExitStack() as st:
            ps = self._patches(cl)
            for p in ps[:-1]:
                st.enter_context(p)
            m = st.enter_context(ps[-1])
            x, name = next_pick("foilspf", "hybrid", [])
        self.assertEqual(name, "fooR00_00")
        self.assertEqual(x, [1.0, 2.0])
        # round_idx passed to the picker subprocess is the POST-skip index.
        self.assertEqual(m.call_args.kwargs["round_idx"], 0)


class TestPendingNames(unittest.TestCase):
    def test_unregistered_mode_contributes_nothing(self):
        # Synthetic test modes (mode="m") are not in bo_driver.MODES and
        # have no pending file; the guard must not raise.
        self.assertEqual(pool._pending_names("definitely-not-a-mode"), set())

    def test_reads_names_from_the_mode_pending_file(self):
        import bo_driver as bo
        fake = mock.Mock()
        fake.load_pending.return_value = [("aR00_00", [1.0]), ("aR01_00", [2.0])]
        with mock.patch.dict(bo.MODES, {"zz": fake}, clear=False):
            self.assertEqual(pool._pending_names("zz"),
                             {"aR00_00", "aR01_00"})


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
        import paths
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
            with mock.patch.object(paths, "GRAPH_DATA", tmp), \
                 mock.patch.object(paths, "REPO_ROOT", tmp), \
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
        import paths

        class _FakeProc:
            def __init__(self, cmd, **kwargs):
                pass

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(paths, "GRAPH_DATA", tmp), \
                 mock.patch.object(paths, "REPO_ROOT", tmp), \
                 mock.patch.object(pool.subprocess, "Popen", _FakeProc):
                run_child = pool._default_run_child("foilspf", 1.0e5)
                run_child("fooR00_00", [1.0])
            self.assertTrue((tmp / "closed_loop_logs" / "fooR00_00.log").exists())


class TestHeartbeat(unittest.TestCase):
    """Finding I3: `next(as_completed(...))` had no timeout, so a hung child
    (harvest-pyroot-nfs-rpc-hang: D-state 5.5 h with no timeout at any
    layer) froze the parent log forever. The heartbeat is REPORT-ONLY -- it
    must not resolve or abandon anything, or it re-creates
    closed-loop-barrier-timeout-zero-rows-falsepos."""

    def test_heartbeat_fires_while_blocked_and_names_the_children(self):
        lines = []
        gate = threading.Event()

        def run_child(name, x):
            gate.wait(timeout=5)
            return 0

        next_pick, _ = _picker()
        t = threading.Timer(0.35, gate.set)
        t.start()
        res = pool.run_rolling(mode="m", picker="p", q=2, max_evals=2,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False, renew=lambda: None,
                               row_landed=lambda n, m: True,
                               broken=_NOT_BROKEN, stagger=0,
                               log=lines.append, heartbeat=0.05)
        t.cancel()
        beats = [ln for ln in lines if "heartbeat" in ln]
        self.assertTrue(beats, f"no heartbeat emitted; got {lines}")
        self.assertIn("in flight", beats[0])
        self.assertTrue(any("c0" in b for b in beats))
        # Report-only: every child still resolved normally.
        self.assertEqual(res["launched"], 2)
        self.assertEqual(len(res["outcomes"]), 2)
        self.assertEqual(res["rows"], 2)
        self.assertFalse(res["aborted"])

    def test_heartbeat_does_not_resolve_or_abandon(self):
        """A child that outlives many heartbeats is still waited for."""
        lines = []
        gate = threading.Event()
        done = []

        def run_child(name, x):
            gate.wait(timeout=5)
            done.append(name)
            return 0

        next_pick, _ = _picker()
        t = threading.Timer(0.4, gate.set)
        t.start()
        res = pool.run_rolling(mode="m", picker="p", q=1, max_evals=1,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False, renew=lambda: None,
                               row_landed=lambda n, m: True,
                               broken=_NOT_BROKEN, stagger=0,
                               log=lines.append, heartbeat=0.02)
        t.cancel()
        self.assertGreater(len([ln for ln in lines if "heartbeat" in ln]), 3)
        self.assertEqual(done, ["c0"])
        self.assertEqual(res["rows"], 1)

    def test_stall_warning_carries_the_recovery_text(self):
        lines = []
        inflight = {object(): ("cX", [1.0])}
        pool._log_inflight(inflight, {"cX": 0.0}, lines.append,
                           now=25 * 3600.0)
        joined = " ".join(lines)
        self.assertIn("WARNING cX", joined)
        self.assertIn("_cluster.txt", joined)
        self.assertIn("--name-prefix", joined)
        self.assertIn("pgrep", joined)

    def test_no_warning_below_threshold(self):
        lines = []
        inflight = {object(): ("cX", [1.0])}
        pool._log_inflight(inflight, {"cX": 0.0}, lines.append, now=3600.0)
        self.assertEqual(len(lines), 1)
        self.assertIn("heartbeat", lines[0])
        self.assertNotIn("WARNING", lines[0])


class TestRenewDuringDrain(unittest.TestCase):
    """Finding M7: renew() ran only in the top-up loop, so a q=20 pool could
    drain for hours after its last launch with no `kinit -R`. Children share
    the parent ccache; an expiry during a late stage submit is
    kerberos-mid-run-expiry (the eval VANISHES, no row, no loud failure)."""

    def test_renew_called_on_every_resolution_including_the_drain(self):
        calls = {"n": 0}
        next_pick, _ = _picker()

        def renew():
            calls["n"] += 1

        pool.run_rolling(mode="m", picker="p", q=3, max_evals=3, alpha=1.0,
                         name_prefix="t", run_child=lambda n, x: 0,
                         next_pick=next_pick, stop_flag=lambda: False,
                         renew=renew, row_landed=lambda n, m: True,
                         broken=_NOT_BROKEN, stagger=0)
        # 3 launches + 3 resolutions; the point is that it exceeds the
        # launch count, i.e. the drain renews too.
        self.assertGreater(calls["n"], 3)

    def test_resolution_time_renew_failure_is_reported_not_fatal(self):
        """Asymmetric on purpose: the PRE-LAUNCH renew is the fatal gate
        ("can we still submit?"); the resolution-time one is hygiene for
        children already running, and aborting the parent on it would
        abandon reporting for a pool that is only draining."""
        lines = []
        state = {"launches": 0}
        next_pick, _ = _picker()

        def renew():
            # Fail only after every launch is done, i.e. during the drain.
            if state["launches"] < 2:
                state["launches"] += 1
                return
            raise SystemExit(2)

        res = pool.run_rolling(mode="m", picker="p", q=2, max_evals=2,
                               alpha=1.0, name_prefix="t",
                               run_child=lambda n, x: 0, next_pick=next_pick,
                               stop_flag=lambda: False, renew=renew,
                               row_landed=lambda n, m: True,
                               broken=_NOT_BROKEN, stagger=0,
                               log=lines.append)
        self.assertEqual(res["rows"], 2)
        self.assertEqual(len(res["outcomes"]), 2)
        self.assertTrue(any("renew at resolution failed" in ln
                            for ln in lines), lines)


if __name__ == "__main__":
    unittest.main()
