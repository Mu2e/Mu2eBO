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

    def next_pick(picker, x_pending):
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
_ROW_LANDED = lambda name: True  # noqa: E731


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

        def next_pick(picker, x_pending):
            pending_sizes.append(len(x_pending))
            i = counter["i"]
            counter["i"] += 1
            return [float(i)] * 2, f"c{i}"

        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(picker="p", q=3, max_evals=9,
                         run_child=run_child,
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
        pool.run_rolling(picker="p", q=2, max_evals=5,
                         run_child=lambda n, x: 0,
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

        def next_pick(picker, x_pending):
            seen.append([list(v) for v in x_pending])
            i = len(seen) - 1
            return [float(i)], f"c{i}"

        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(picker="p", q=3, max_evals=3,
                         run_child=run_child,
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
        res = pool.run_rolling(picker="p", q=4, max_evals=4,
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
                               row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(len(finished), 4)
        self.assertEqual(len(res["outcomes"]), 4)


class TestOnOutcome(unittest.TestCase):
    def test_on_outcome_sees_every_outcome(self):
        seen = []
        next_pick, _ = _picker()
        res = pool.run_rolling(picker="p", q=2, max_evals=3,
                               run_child=lambda name, x: 0,
                               next_pick=next_pick, stop_flag=lambda: False,
                               row_landed=_ROW_LANDED, broken=_NOT_BROKEN,
                               stagger=0, on_outcome=seen.append)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen, res["outcomes"])
        self.assertEqual({oc.reason for oc in seen}, {"ok"})

    def test_a_raising_on_outcome_is_logged_and_the_pool_goes_on(self):
        lines = []

        def on_outcome(oc):
            raise TypeError(f"cannot record {oc.name}")

        next_pick, _ = _picker()
        res = pool.run_rolling(picker="p", q=2, max_evals=4,
                               run_child=lambda name, x: 0,
                               next_pick=next_pick, row_landed=_ROW_LANDED,
                               broken=_NOT_BROKEN, stagger=0,
                               log=lines.append, on_outcome=on_outcome)
        self.assertEqual(res["launched"], 4)
        self.assertEqual(len(res["outcomes"]), 4)
        warned = [ln for ln in lines if "on_outcome" in ln]
        self.assertEqual(len(warned), 4, lines)
        for i in range(4):
            self.assertTrue(any(f"cannot record c{i}" in ln for ln in warned))


def _eio_for_c0(otherwise):
    """A row_landed/broken fake that raises for c0 (a CephFS EIO on the
    board or on broken.txt) and answers `otherwise` for every other child."""
    def check(name):
        if name == "c0":
            raise OSError(5, "Input/output error")
        return otherwise(name)
    return check


class TestFailures(unittest.TestCase):
    """A raise from a pool callable used to unwind through the executor's
    __exit__, which waits for every in-flight child in silence: no
    heartbeat, no Outcome line, no on_outcome, the traceback only once the
    last child exited (hours to days on the grid)."""

    def test_a_failing_pick_is_logged_at_once_drained_then_raised(self):
        """budget_sob's refusal (core/botorch_predict.py) on a fresh board
        whose first rows are over budget: the realistic trigger."""
        lines, seen = [], []
        gate = threading.Event()
        calls = {"n": 0}

        def run_child(name, x):
            if name != "c0":
                gate.wait(timeout=5)
            return 0

        def next_pick(picker, x_pending):
            i = calls["n"]
            calls["n"] += 1
            if i == 3:      # the first replacement, with c1 and c2 in flight
                raise ValueError("GP predicts NO point; refusing")
            return [float(i)], f"c{i}"

        t = threading.Timer(0.3, gate.set)
        t.start()
        with self.assertRaises(ValueError) as cm:
            pool.run_rolling(picker="p", q=3, max_evals=6,
                             run_child=run_child, next_pick=next_pick,
                             row_landed=_ROW_LANDED, broken=_NOT_BROKEN,
                             stagger=0, log=lines.append, heartbeat=0.05,
                             on_outcome=seen.append)
        t.cancel()
        self.assertIn("GP predicts NO point", str(cm.exception))
        self.assertEqual(calls["n"], 4)     # nothing picked after it
        fatal = [i for i, ln in enumerate(lines) if "[pool] FATAL" in ln]
        self.assertEqual(len(fatal), 1, lines)
        self.assertIn("ValueError: GP predicts NO point", lines[fatal[0]])
        self.assertIn("2 in flight", lines[fatal[0]])
        # Logged when it happened: the children still in flight resolve
        # after it, through the normal drain (heartbeat, a line each).
        after = lines[fatal[0] + 1:]
        self.assertTrue(any("heartbeat" in ln for ln in after), lines)
        self.assertIn("[pool] c1: ok", after)
        self.assertIn("[pool] c2: ok", after)
        self.assertEqual(sorted(oc.name for oc in seen), ["c0", "c1", "c2"])

    def test_a_pick_failing_with_nothing_in_flight_still_raises(self):
        lines = []

        def next_pick(picker, x_pending):
            raise ValueError("budget_sob needs a constraint")

        with self.assertRaises(ValueError):
            pool.run_rolling(picker="p", q=2, max_evals=2,
                             run_child=lambda name, x: 0,
                             next_pick=next_pick, row_landed=_ROW_LANDED,
                             broken=_NOT_BROKEN, stagger=0, log=lines.append)
        self.assertTrue(any("[pool] FATAL" in ln and "0 in flight" in ln
                            for ln in lines), lines)

    def test_a_landed_row_counts_even_when_broken_cannot_be_read(self):
        """broken.txt is read only for a child with no row: a transient
        error on it (ESTALE on CephFS) must not turn landed rows into a
        no-row streak and abort a healthy campaign."""
        def stale(name):
            raise OSError(116, "Stale file handle")
        next_pick, _ = _picker()
        res = pool.run_rolling(picker="p", q=2, max_evals=4,
                               run_child=lambda name, x: 0,
                               next_pick=next_pick, stagger=0,
                               row_landed=_ROW_LANDED, broken=stale,
                               log=lambda m: None)
        self.assertEqual(res["rows"], 4)
        self.assertFalse(res["aborted"])
        self.assertEqual({oc.reason for oc in res["outcomes"]}, {"ok"})

    def test_a_raising_row_or_broken_check_is_that_childs_outcome(self):
        """Fail closed (row_landed never fails open): a child whose row was
        not seen counts as rowless, toward the no-row streak, and keeps its
        log line."""
        no_row_for_c0 = lambda name: name != "c0"  # noqa: E731
        for check, rows, fake in (("row_landed", _ROW_LANDED, _ROW_LANDED),
                                  ("broken", no_row_for_c0, _NOT_BROKEN)):
            with self.subTest(check=check):
                lines, seen = [], []
                checks = {"row_landed": rows, "broken": _NOT_BROKEN,
                          check: _eio_for_c0(fake)}
                next_pick, _ = _picker()
                res = pool.run_rolling(picker="p", q=2, max_evals=3,
                                       run_child=lambda name, x: 0,
                                       next_pick=next_pick, stagger=0,
                                       log=lines.append,
                                       on_outcome=seen.append, **checks)
                self.assertEqual(seen, res["outcomes"])
                self.assertEqual(sorted(oc.name for oc in seen),
                                 ["c0", "c1", "c2"])
                c0 = next(oc for oc in seen if oc.name == "c0")
                self.assertEqual((c0.rc, c0.row_landed, c0.broken),
                                 (0, False, False))
                self.assertEqual(c0.reason, "outcome unknown: OSError: "
                                            "[Errno 5] Input/output error")
                self.assertIn(f"[pool] c0: {c0.reason}", lines)
                self.assertIn("[pool] c0: no-row streak 1/2", lines)
                self.assertEqual(res["rows"], 2)
                self.assertFalse(res["aborted"])


class TestNoRowStreak(unittest.TestCase):
    def test_streak_increments_on_rowless_and_resets_on_row(self):
        """Each child's outcome is observed as it resolves; there are no wave
        baselines for a row to be absorbed into. That is the root fix for
        rolling-no-row-streak-false-increment."""
        rows = {"c0": False, "c1": True, "c2": False}
        next_pick, _ = _picker()
        res = pool.run_rolling(
            picker="p", q=1, max_evals=3,
            run_child=lambda n, x: 0 if rows.get(n) else 1,
            next_pick=next_pick,
            stop_flag=lambda: False,
            row_landed=lambda name: rows.get(name, False),
            broken=_NOT_BROKEN, stagger=0)
        self.assertEqual(res["rows"], 1)
        self.assertFalse(res["aborted"])

    def test_a_landed_row_resets_the_streak_whatever_the_rc(self):
        """A child that lands its row and then exits non-zero (a kit that
        fails to close, say) succeeded: counting it rowless would push a
        healthy campaign toward ABORT. Its reason still shows the rc."""
        rows = {"c1": True, "c3": True}
        lines = []
        next_pick, _ = _picker()
        res = pool.run_rolling(
            picker="p", q=1, max_evals=4,
            run_child=lambda n, x: 1,
            next_pick=next_pick,
            row_landed=lambda name: rows.get(name, False),
            broken=_NOT_BROKEN, stagger=0, log=lines.append)
        self.assertFalse(res["aborted"], lines)
        self.assertEqual(res["launched"], 4)
        self.assertEqual(res["rows"], 2)
        by_name = {oc.name: oc for oc in res["outcomes"]}
        self.assertTrue(by_name["c1"].row_landed)
        self.assertEqual(by_name["c1"].reason, "row landed but child rc=1")
        self.assertEqual(by_name["c0"].reason, "child rc=1")

    def test_q_consecutive_rowless_aborts(self):
        next_pick, _ = _picker()
        res = pool.run_rolling(
            picker="p", q=2, max_evals=10,
            run_child=lambda n, x: 1,
            next_pick=next_pick,
            stop_flag=lambda: False,
            row_landed=lambda name: False,
            broken=_NOT_BROKEN, stagger=0)
        self.assertTrue(res["aborted"])
        self.assertLess(res["launched"], 10)


class TestAbortThreshold(unittest.TestCase):
    """Pins `_should_abort`'s formula directly (MINOR 8, review round 2):
    q=1 requires TWO consecutive rowless resolutions, q>1 requires exactly
    q. Extracted to a pure function specifically so this doesn't need to be
    proven by racing a real thread pool -- test_q_consecutive_rowless_aborts
    above only pins "it aborts eventually", not the exact threshold."""

    def test_the_threshold(self):
        for streak, q, want in (
                (1, 1, False), (2, 1, True),     # q=1 requires two, not one
                (2, 3, False), (3, 3, True),     # q>1 requires exactly q
                # The regression this guards: `streak > q` (review round 1's
                # fix) required q+1=21 at q=20 -- over half a 40-eval budget
                # before aborting, where the intent was 20.
                (20, 21, False), (20, 20, True)):
            with self.subTest(streak=streak, q=q):
                self.assertIs(pool._should_abort(streak=streak, q=q), want)


class TestStopFlag(unittest.TestCase):
    def test_stop_halts_topup_but_still_drains(self):
        stop = {"v": False}
        done = []

        def run_child(name, x):
            done.append(name)
            stop["v"] = True
            return 0

        next_pick, counter = _picker()
        res = pool.run_rolling(picker="p", q=2, max_evals=20,
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
            pool.run_rolling(picker="p", q=2, max_evals=4,
                             run_child=lambda n, x: 0, next_pick=next_pick,
                             stop_flag=lambda: False,
                             row_landed=_ROW_LANDED, broken=_NOT_BROKEN, stagger=0)
        m.assert_not_called()

    def test_stagger_sleeps_between_but_not_before_first_launch(self):
        next_pick, _ = _picker()
        with mock.patch.object(pool.time, "sleep") as m:
            res = pool.run_rolling(picker="p", q=1, max_evals=3,
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
        res = pool.run_rolling(picker="p", q=2, max_evals=2,
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
                               row_landed=lambda n: True,
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
        res = pool.run_rolling(picker="p", q=1, max_evals=1,
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False,
                               row_landed=lambda n: True,
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
