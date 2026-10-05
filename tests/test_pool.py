"""Unit tests for the parent rolling work-pool.

Replaces ~1,470 LOC that tested five agreeing signal sources (checkpoint
terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard membership). The
pool has ONE: a child resolves when its subprocess exits. run_child is an
injected callable, so none of this touches the grid, sqlite, or a subprocess.
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))

import pool  # noqa: E402


def _picker(n_dims=2):
    """Deterministic pick source: x is [i, i], name is c{i}."""
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        i = counter["i"]
        counter["i"] += 1
        return [float(i)] * n_dims, f"c{i}"
    return next_pick, counter


# Neutral broken= fake: run_rolling requires the callable, and these cases
# are about pool MECHANICS, not about which child broke.
_NOT_BROKEN = lambda name: False  # noqa: E731

# Neutral row_landed= fake, same reasoning as _NOT_BROKEN one line up. These
# cases are about pool MECHANICS (width, stagger, drain, abort arithmetic),
# not about whether a row landed, so they want "every child landed".
_ROW_LANDED = lambda name, mode: True  # noqa: E731


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
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=9,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False,
                         row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
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
        pool.run_rolling(mode="m", picker="p", q=2, max_evals=5,
                         name_prefix="t", run_child=lambda n, x: 0,
                         next_pick=next_pick,
                         stop_flag=lambda: False,
                         row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
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
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=3,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False,
                         row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
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
                               name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
                               row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(len(finished), 4)
        self.assertEqual(len(res["outcomes"]), 4)


class TestOnOutcome(unittest.TestCase):
    def test_on_outcome_sees_every_outcome(self):
        seen = []
        next_pick, _ = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=2, max_evals=3,
                               name_prefix="t",
                               run_child=lambda name, x: 0,
                               next_pick=next_pick, stop_flag=lambda: False,
                               row_landed=_ROW_LANDED, broken=_NOT_BROKEN,
                               stagger=0, on_outcome=seen.append)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen, res["outcomes"])
        self.assertEqual({oc.reason for oc in seen}, {"ok"})


class TestNoRowStreak(unittest.TestCase):
    def test_streak_increments_on_rowless_and_resets_on_row(self):
        """Each child's outcome is observed as it resolves; there are no wave
        baselines for a row to be absorbed into. That is the root fix for
        rolling-no-row-streak-false-increment."""
        rows = {"c0": False, "c1": True, "c2": False}
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=1, max_evals=3,
            name_prefix="t",
            run_child=lambda n, x: 0 if rows.get(n) else 1,
            next_pick=next_pick,
            stop_flag=lambda: False,
            row_landed=lambda name, mode: rows.get(name, False),
            broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(res["rows"], 1)
        self.assertFalse(res["aborted"])

    def test_q_consecutive_rowless_aborts(self):
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=2, max_evals=10,
            name_prefix="t", run_child=lambda n, x: 1,
            next_pick=next_pick,
            stop_flag=lambda: False,
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
                               name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: stop["v"],
                               row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
        self.assertLess(res["launched"], 20)
        self.assertEqual(len(res["outcomes"]), len(done))


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
                             name_prefix="t",
                             run_child=lambda n, x: 0, next_pick=next_pick,
                             stop_flag=lambda: False,
                             row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
        m.assert_not_called()

    def test_stagger_sleeps_between_but_not_before_first_launch(self):
        next_pick, _ = _picker()
        with mock.patch.object(pool.time, "sleep") as m:
            res = pool.run_rolling(mode="m", picker="p", q=1, max_evals=3,
                                   name_prefix="t",
                                   run_child=lambda n, x: 0,
                                   next_pick=next_pick,
                                   stop_flag=lambda: False,
                                   row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=42)
        # 3 launches -> 2 gaps between them, none before the first.
        self.assertEqual(m.call_args_list, [mock.call(42), mock.call(42)])
        self.assertEqual(res["launched"], 3)


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
                               name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
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
                               name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
                               row_landed=lambda n, m: True,
                               broken=_NOT_BROKEN, stagger=0,
                               log=lines.append, heartbeat=0.02)
        t.cancel()
        self.assertGreater(len([ln for ln in lines if "heartbeat" in ln]), 3)
        self.assertEqual(done, ["c0"])
        self.assertEqual(res["rows"], 1)

    def test_stall_warning_carries_the_recovery_text(self):
        """The advice must match graph/closed_loop.py::busy_reason: a
        same-prefix relaunch is NOT safe once state exists for the name."""
        lines = []
        inflight = {object(): ("cX", [1.0], 0.0)}
        pool._log_inflight(inflight, lines.append, now=25 * 3600.0)
        joined = " ".join(lines)
        self.assertIn("WARNING cX", joined)
        self.assertIn("busy_reason", joined)
        self.assertIn("another --name-prefix", joined)
        self.assertIn("do NOT relaunch it under the same --name-prefix", joined)
        self.assertIn("run.lock", joined)

    def test_no_warning_below_threshold(self):
        lines = []
        inflight = {object(): ("cX", [1.0], 0.0)}
        pool._log_inflight(inflight, lines.append, now=3600.0)
        self.assertEqual(len(lines), 1)
        self.assertIn("heartbeat", lines[0])
        self.assertNotIn("WARNING", lines[0])


class TestNextFreeName(unittest.TestCase):
    def test_skips_busy_names_and_summarises_after_the_limit(self):
        n = pool.SKIP_LOG_LIMIT + 3
        busy = {pool.child_name("p", i) for i in range(n)}
        lines = []
        name, i = pool.next_free_name(
            "p", 0, lambda nm: "busy" if nm in busy else None,
            log=lines.append, summary_hint="HINT")
        self.assertEqual((name, i), (pool.child_name("p", n), n))
        self.assertEqual(sum(ln.startswith("[pool] SKIP") for ln in lines),
                         pool.SKIP_LOG_LIMIT)
        self.assertIn("3 further", lines[-1])
        self.assertIn("HINT", lines[-1])

    def test_a_free_start_is_returned_as_is(self):
        lines = []
        self.assertEqual(pool.next_free_name("p", 4, lambda nm: None,
                                             log=lines.append, summary_hint=""),
                         ("pR04_00", 4))
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
