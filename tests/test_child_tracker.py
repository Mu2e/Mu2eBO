"""Unit tests for graph/child_tracker.py — the barrier's Resolution owner.

All signals are injected fakes (the point of the Signals adapter): no disk,
no SQLite, no mock.patch of module internals.
"""
import unittest

from graph.child_tracker import ChildTracker, Resolution


class FakeSignals:
    def __init__(self):
        self.rows = set()
        self.broken = set()
        self.terminal = set()
        self.dead_pids = set()
        self.clusters = set()
        self.leaderboard_reads = 0

    def leaderboard_names(self):
        self.leaderboard_reads += 1
        return set(self.rows)

    def is_broken(self, name):
        return name in self.broken

    def is_terminal(self, thread_id):
        return thread_id in self.terminal

    def pid_alive(self, pid):
        return pid not in self.dead_pids

    def has_cluster(self, name):
        return name in self.clusters


def _children(*names, pid=1000):
    return {n: {"pid": pid + i, "thread_id": f"{n}_tid"}
            for i, n in enumerate(names)}


class TestResolutions(unittest.TestCase):
    def test_row_resolves_done_row(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a", "b"), sig)
        sig.rows.add("a")
        changed = t.tick()
        self.assertEqual(changed, {"a": Resolution.DONE_ROW})
        self.assertFalse(t.all_resolved())
        self.assertEqual(t.pending_count(), 1)

    def test_broken_resolves_done_broken(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.broken.add("a")
        self.assertEqual(t.tick(), {"a": Resolution.DONE_BROKEN})
        self.assertTrue(t.all_resolved())

    def test_terminal_no_row_resolves(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.terminal.add("a_tid")
        self.assertEqual(t.tick(), {"a": Resolution.DONE_TERMINAL_NO_ROW})

    def test_terminal_falls_back_to_name_without_thread_id(self):
        sig = FakeSignals()
        t = ChildTracker({"a": {"pid": 1}}, sig)
        sig.terminal.add("a")
        self.assertEqual(t.tick(), {"a": Resolution.DONE_TERMINAL_NO_ROW})

    def test_row_beats_broken_and_terminal(self):
        # Precedence mirrors the historical barrier: a leaderboard row is the
        # authoritative success signal even if broken/terminal also present.
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.rows.add("a")
        sig.broken.add("a")
        sig.terminal.add("a_tid")
        self.assertEqual(t.tick(), {"a": Resolution.DONE_ROW})


class TestDeadPidGrace(unittest.TestCase):
    def test_dead_pid_needs_two_ticks(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.dead_pids.add(1000)
        self.assertEqual(t.tick(), {})            # tick 1: suspect only
        self.assertFalse(t.all_resolved())
        self.assertEqual(t.tick(), {"a": Resolution.DEAD_UNRESOLVED})
        self.assertTrue(t.all_resolved())

    def test_row_landing_during_grace_wins(self):
        # foilsf08 race: process dies while its final leaderboard append is
        # landing — the grace tick must let the row win.
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.dead_pids.add(1000)
        t.tick()                                   # suspect
        sig.rows.add("a")
        self.assertEqual(t.tick(), {"a": Resolution.DONE_ROW})

    def test_pid_flap_clears_suspicion(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.dead_pids.add(1000)
        t.tick()                                   # suspect
        sig.dead_pids.clear()                      # alive again (flap)
        self.assertEqual(t.tick(), {})             # suspicion cleared
        sig.dead_pids.add(1000)
        self.assertEqual(t.tick(), {})             # fresh grace tick required
        self.assertEqual(t.tick(), {"a": Resolution.DEAD_UNRESOLVED})

    def test_unlaunched_child_without_pid_never_dead(self):
        sig = FakeSignals()
        t = ChildTracker({"a": {"pid": None}}, sig)
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.resolutions()["a"], Resolution.RUNNING)


class TestStaleCluster(unittest.TestCase):
    def test_stale_cluster_resolves_never_launched_child(self):
        # pid None + has_cluster -> STALE_CLUSTER on first tick, sticky.
        sig = FakeSignals()
        t = ChildTracker({"a": {"pid": None}}, sig)
        sig.clusters.add("a")
        self.assertEqual(t.tick(), {"a": Resolution.STALE_CLUSTER})
        self.assertTrue(t.all_resolved())
        # Sticky: a later signal flap (cluster file removed by an operator)
        # must not un-resolve the child.
        sig.clusters.discard("a")
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.resolutions()["a"], Resolution.STALE_CLUSTER)

    def test_pid_none_without_cluster_stays_running(self):
        sig = FakeSignals()
        t = ChildTracker({"a": {"pid": None}}, sig)
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.resolutions()["a"], Resolution.RUNNING)
        self.assertFalse(t.all_resolved())

    def test_launched_child_never_stale(self):
        # pid set + has_cluster True -> normal pid/row logic, not STALE.
        # A launched child's OWN cluster.txt (written by this round's grid
        # submission) must never be mistaken for a prior aborted run's; the
        # pid-present branch takes priority and has_cluster is never even
        # consulted while a pid is recorded.
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.clusters.add("a")           # this child's own in-flight cluster.txt
        self.assertEqual(t.tick(), {})  # pid alive, no row -> stays RUNNING
        self.assertEqual(t.resolutions()["a"], Resolution.RUNNING)
        sig.dead_pids.add(1000)
        t.tick()                        # dead-pid grace tick (suspect only)
        self.assertEqual(t.tick(), {"a": Resolution.DEAD_UNRESOLVED})


class TestLaunchFailed(unittest.TestCase):
    def test_launch_failed_resolves_immediately_no_grace(self):
        # pid None + launch_failed True (Popen raised in node_launch_children)
        # -> DEAD_UNRESOLVED on the FIRST tick, no two-tick dead-pid grace
        # (there is no in-flight process/append to race).
        sig = FakeSignals()
        t = ChildTracker({"a": {"pid": None, "launch_failed": True}}, sig)
        self.assertEqual(t.tick(), {"a": Resolution.DEAD_UNRESOLVED})
        self.assertTrue(t.all_resolved())
        # Sticky: a later signal flap must not un-resolve the child.
        self.assertEqual(t.tick(), {})
        self.assertEqual(t.resolutions()["a"], Resolution.DEAD_UNRESOLVED)


class TestStickinessAndPreseed(unittest.TestCase):
    def test_resolution_is_sticky(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.rows.add("a")
        t.tick()
        sig.rows.clear()                           # signal flap
        self.assertEqual(t.tick(), {})             # no re-resolution
        self.assertEqual(t.resolutions()["a"], Resolution.DONE_ROW)

    def test_already_done_excluded_but_counted(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a", "b"), sig, already_done=["b"])
        self.assertEqual(t.pending_count(), 1)
        self.assertIn("b", t.done_names())
        sig.rows.add("a")
        t.tick()
        self.assertTrue(t.all_resolved())
        self.assertEqual(t.done_names(), {"a", "b"})


class TestEfficiencyContract(unittest.TestCase):
    def test_one_leaderboard_read_per_tick(self):
        # Pins the once-per-tick flock read (a per-child read re-parses the
        # growing TSV q times per tick, thousands of times per round).
        sig = FakeSignals()
        t = ChildTracker(_children("a", "b", "c", "d", "e"), sig)
        t.tick()
        self.assertEqual(sig.leaderboard_reads, 1)

    def test_no_leaderboard_read_when_all_resolved(self):
        sig = FakeSignals()
        t = ChildTracker(_children("a"), sig)
        sig.rows.add("a")
        t.tick()
        reads = sig.leaderboard_reads
        t.tick()
        self.assertEqual(sig.leaderboard_reads, reads)


if __name__ == "__main__":
    unittest.main()
