"""Unit tests for the parent rolling work-pool.

Replaces ~1,470 LOC that tested five agreeing signal sources (checkpoint
terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard membership). The
pool has ONE: a child resolves when its subprocess exits. run_child is an
injected callable, so none of this touches the grid, sqlite, or a subprocess.
"""
import os
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))

# pool.py's default row_landed/broken callables lazily `import closed_loop`,
# which (via graph/config.py) resolves AUTORESEARCH_MODE against modes.SPECS
# at import time; "foils" (the module-level fallback) is dangling (retired
# 2026-08-08). Every test below passes its own run_child/next_pick fakes but
# not always row_landed/broken, so the lazy import can fire. Same pattern as
# tests/test_no_mock_mode.py.
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


class TestPoolWidth(unittest.TestCase):
    def test_never_exceeds_q_in_flight(self):
        peak = {"n": 0}
        lock = threading.Lock()
        gate = threading.Event()

        def run_child(name, x):
            with lock:
                peak["n"] += 1
                peak_now = peak["n"]
                peak["max"] = max(peak.get("max", 0), peak_now)
            gate.wait(timeout=5)
            with lock:
                peak["n"] -= 1
            return 0

        next_pick, _ = _picker()
        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=9, alpha=1.0,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None)
        t.cancel()
        self.assertLessEqual(peak["max"], 3)


class TestReplenish(unittest.TestCase):
    def test_one_resolution_triggers_exactly_one_new_pick(self):
        next_pick, counter = _picker()
        pool.run_rolling(mode="m", picker="p", q=2, max_evals=5, alpha=1.0,
                         name_prefix="t", run_child=lambda n, x: 0,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None)
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
                         stop_flag=lambda: False, renew=lambda: None)
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
                               stop_flag=lambda: False, renew=lambda: None)
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
            row_landed=lambda name, mode: rows.get(name, False))
        self.assertEqual(res["rows"], 1)
        self.assertFalse(res["aborted"])

    def test_q_consecutive_rowless_aborts(self):
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=2, max_evals=10, alpha=1.0,
            name_prefix="t", run_child=lambda n, x: 1,
            next_pick=next_pick,
            stop_flag=lambda: False, renew=lambda: None,
            row_landed=lambda name, mode: False)
        self.assertTrue(res["aborted"])
        self.assertLess(res["launched"], 10)


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
                               renew=lambda: None)
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
                               stop_flag=lambda: False, renew=renew)
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
                             stop_flag=lambda: False, renew=renew)


if __name__ == "__main__":
    unittest.main()
