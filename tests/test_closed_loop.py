"""Self-tests for graph/closed_loop.py — pure-ish, no grid contact.

Run from project root:
  python -m unittest tests.test_closed_loop -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))

import closed_loop as cl  # noqa: E402


class TestRouteAfterDecide(unittest.TestCase):
    def _base(self, **overrides):
        s = {"zero_rows": False, "round_idx": 1, "max_rounds": 10}
        s.update(overrides)
        return s

    def test_zero_rows_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide(self._base(zero_rows=True)), cl.END
            )

    def test_max_rounds_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide(self._base(round_idx=10, max_rounds=10)),
                cl.END,
            )

    def test_stop_flag_ends(self):
        with mock.patch.object(cl, "_stop_requested", return_value=True):
            self.assertEqual(cl.route_after_decide(self._base()), cl.END)

    def test_default_loops_to_renew_token(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(cl.route_after_decide(self._base()), "renew_token")


class TestDecideNext(unittest.TestCase):
    def test_bumps_round_and_clears_children_only(self):
        state = {
            "mode": "helical",
            "round_idx": 2,
            "children": {"foo": {"pid": 1}},
            "completed_names": ["a", "b"],
            "history_len_before": 10,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=15):
            out = cl.node_decide_next(state)
        self.assertEqual(out["round_idx"], 3)
        self.assertEqual(out["children"], {})
        self.assertFalse(out["zero_rows"])
        # completed_names intentionally persists across rounds
        self.assertNotIn("completed_names", out)

    def test_zero_new_rows_all_resolved_sets_zero_rows_true(self):
        # All of this round's launched children resolved, 0 new rows →
        # genuine all-failed round (foilsX04 shape) → exit.
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "launched_names": ["a", "b"],
            "completed_names": ["a", "b"],
            "history_len_before": 42,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertTrue(out["zero_rows"])
        self.assertEqual(out["round_idx"], 2)

    def test_negative_delta_all_resolved_sets_zero_rows_true(self):
        # Defensive: leaderboard shouldn't shrink, but if it does, treat
        # as zero-row (no progress) rather than continuing.
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "launched_names": ["a"],
            "completed_names": ["a"],
            "history_len_before": 10,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=8):
            out = cl.node_decide_next(state)
        self.assertTrue(out["zero_rows"])

    def test_barrier_timeout_pending_does_not_set_zero_rows(self):
        # foilsg03/foilsg05 false-positive: barrier timed out with children
        # still running on the grid. 0 new rows means "not finished yet",
        # not "all failed" — must carry the round forward.
        # See wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md.
        state = {
            "mode": "helical",
            "round_idx": 0,
            "children": {},
            "launched_names": ["a", "b", "c"],
            "completed_names": ["a"],
            "history_len_before": 42,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertFalse(out["zero_rows"])
        self.assertEqual(out["round_idx"], 1)

    def test_completed_cumulative_across_rounds_doesnt_mask_pending(self):
        # completed_names persists across rounds; a raw count comparison
        # (len(completed) >= len(launched)) would be trivially true here
        # even though this round's only child is still pending.
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "launched_names": ["c"],
            "completed_names": ["prev_a", "prev_b"],
            "history_len_before": 42,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertFalse(out["zero_rows"])

    def test_completed_includes_this_round_failure_exits(self):
        # Same cumulative completed set, but this round's child DID resolve
        # (failed without a row) → all-failed semantics preserved.
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "launched_names": ["c"],
            "completed_names": ["prev_a", "prev_b", "c"],
            "history_len_before": 42,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertTrue(out["zero_rows"])

    def test_stop_seen_exits_even_with_pending_children(self):
        # Barrier recorded a STOP_FLAG observation; decide_next must
        # propagate it and route_after_decide must END even though the
        # pending children suppressed zero_rows — without re-reading the
        # (possibly already removed) flag file.
        state = {
            "mode": "helical",
            "round_idx": 0,
            "max_rounds": 10,
            "children": {},
            "launched_names": ["a", "b"],
            "completed_names": ["a"],
            "history_len_before": 42,
            "stop_seen": True,
        }
        with mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_decide_next(state)
        self.assertFalse(out["zero_rows"])
        self.assertTrue(out["stop_seen"])
        routed = dict(state, **out)
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(cl.route_after_decide(routed), cl.END)


class TestAssignNames(unittest.TestCase):
    def _state(self):
        return {
            "name_prefix": "helical",
            "round_idx": 0,
            "mode": "helical",
            "children": {
                "_pick_00": {"x_point": [1, 2, 3, 4]},
                "_pick_01": {"x_point": [5, 6, 7, 8]},
            },
            "completed_names": [],
        }

    def test_placeholders_become_real_names(self):
        with mock.patch.object(cl, "_child_in_leaderboard", return_value=False), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertEqual(
            sorted(out["children"]), ["helicalR00_00", "helicalR00_01"]
        )
        self.assertEqual(
            out["children"]["helicalR00_00"]["x_point"], [1, 2, 3, 4]
        )
        self.assertEqual(out["completed_names"], [])

    def test_already_in_leaderboard_skipped(self):
        in_lb = {"helicalR00_00"}
        with mock.patch.object(cl, "_child_in_leaderboard",
                                lambda n, m: n in in_lb), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertNotIn("helicalR00_00", out["children"])
        self.assertIn("helicalR00_01", out["children"])
        self.assertIn("helicalR00_00", out["completed_names"])

    def test_broken_skipped(self):
        with mock.patch.object(cl, "_child_in_leaderboard", return_value=False), \
             mock.patch.object(cl, "_child_is_broken",
                                lambda n: n == "helicalR00_01"):
            out = cl.node_assign_names(self._state())
        self.assertIn("helicalR00_00", out["children"])
        self.assertNotIn("helicalR00_01", out["children"])
        self.assertIn("helicalR00_01", out["completed_names"])


class TestRenewToken(unittest.TestCase):
    @staticmethod
    def _ok():
        return mock.Mock(returncode=0, stderr="")

    @staticmethod
    def _fail():
        return mock.Mock(returncode=1, stderr="auth failed")

    # kinit -R goes through cl.subprocess.run; getToken now goes through the
    # shared cl.run_sourced_bash helper (retry-protected), so the two are
    # mocked separately rather than as one ordered side_effect list.
    def test_happy_path_no_errors(self):
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._ok()):
            out = cl.node_renew_token(state)
        self.assertEqual(out["errors"], [])

    def test_getToken_nonzero_rc_exits(self):
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._fail()):
            with self.assertRaises(SystemExit) as cm:
                cl.node_renew_token(state)
        self.assertEqual(cm.exception.code, 2)

    def test_getToken_raises_exits(self):
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", side_effect=OSError("ENOKEY")):
            with self.assertRaises(SystemExit) as cm:
                cl.node_renew_token(state)
        self.assertEqual(cm.exception.code, 2)

    def test_kinit_failure_does_not_exit(self):
        # kinit -R is best-effort; only getToken failure is fatal
        state = {"round_idx": 0, "errors": []}
        with mock.patch.object(cl.subprocess, "run", return_value=self._fail()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._ok()):
            out = cl.node_renew_token(state)
        self.assertTrue(any("kinit -R" in e for e in out["errors"]))


class TestPredictPicks(unittest.TestCase):
    def test_under_q_logs_error(self):
        state = {"q": 5, "round_idx": 0, "errors": [], "mode": "helical"}
        fake_gp = mock.Mock()
        fake_gp.compute_explore_picks.return_value = [
            (1, 2, 3, 4), (5, 6, 7, 8),
        ]
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp), \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        self.assertTrue(any("only got 2/5 picks" in e for e in out["errors"]))
        self.assertEqual(len(out["children"]), 2)
        self.assertEqual(out["history_len_before"], 42)

    def test_full_q_no_error(self):
        state = {"q": 2, "round_idx": 0, "errors": [], "mode": "helical"}
        fake_gp = mock.Mock()
        fake_gp.compute_explore_picks.return_value = [
            (1, 2, 3, 4), (5, 6, 7, 8),
        ]
        with mock.patch.object(cl, "_import_gp", return_value=fake_gp), \
             mock.patch.object(cl, "_leaderboard_len", return_value=10):
            out = cl.node_predict_picks(state)
        self.assertEqual(out["errors"], [])
        self.assertEqual(sorted(out["children"]), ["_pick_00", "_pick_01"])
        self.assertEqual(out["history_len_before"], 10)

    def test_qnparego_routes_to_botorch_subprocess(self):
        # Any picker != cl_min shells into .venv-botorch; _import_gp is NOT
        # touched. Assert routing + picker verbatim pass-through.
        state = {"q": 3, "round_idx": 2, "errors": [], "mode": "foilsflash",
                 "picker": "qnparego"}
        picks = [(float(i),) * 6 for i in range(3)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_import_gp") as gp, \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs.get("picker"), "qnparego")
        self.assertEqual(m.call_args.args[0], "foilsflash")  # mode
        self.assertEqual(m.call_args.args[2], 2)             # round_idx
        gp.assert_not_called()
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["children"]), 3)
        self.assertEqual(out["history_len_before"], 42)

    def test_hybrid_routes_to_botorch_subprocess(self):
        state = {"q": 5, "round_idx": 0, "errors": [], "mode": "foilsflash",
                 "picker": "hybrid"}
        picks = [(float(i),) * 6 for i in range(5)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_import_gp") as gp, \
             mock.patch.object(cl, "_leaderboard_len", return_value=10):
            out = cl.node_predict_picks(state)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs.get("picker"), "hybrid")
        gp.assert_not_called()
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["children"]), 5)


class TestChildIsBroken(unittest.TestCase):
    def test_broken_present(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp):
                state_dir = tmp / "fooR00_00" / "state"
                state_dir.mkdir(parents=True)
                (state_dir / "broken.txt").write_text("x")
                self.assertTrue(cl._child_is_broken("fooR00_00"))

    def test_broken_absent(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cl, "GRID_DATA_ROOT", Path(td)):
                self.assertFalse(cl._child_is_broken("nope"))


class TestBuildGraph(unittest.TestCase):
    def test_renew_token_is_a_node(self):
        g = cl._build_outer_graph()
        # All expected nodes present; renew_token is the start-of-round node.
        for n in ("renew_token", "predict_picks", "assign_names",
                  "launch_children", "barrier", "decide_next"):
            self.assertIn(n, g.nodes, f"missing node {n}")

    def test_refit_and_check_removed(self):
        # Convergence-by-pareto-hash machinery was deleted 2026-05-29
        # (foilsX04 false-positive incident, 0 true saves in 15 runs).
        g = cl._build_outer_graph()
        self.assertNotIn("refit_and_check", g.nodes)


class TestUniqueThreadIdPerLaunch(unittest.TestCase):
    """Issue #7: closed_loop must pass a per-launch unique --thread-id so a
    stale SqliteSaver checkpoint keyed on `config_name` cannot resume into a
    fresh child and silently swap its identity.
    See wiki/incidents/closed-loop-thread-id-checkpoint-collision.md.
    """

    def _capture_cmd(self):
        """Stub Popen that records the cmd list and returns a fake proc."""
        captured = []

        class _FakeProc:
            def __init__(self, cmd):
                self.pid = 999
                self._cmd = cmd

        def _popen(cmd, **kwargs):
            captured.append(list(cmd))
            return _FakeProc(cmd)

        return captured, _popen

    def _state(self, td):
        # Two children sharing identical x_point shapes but different names.
        return {
            "mode": "helical",
            "alpha": 0.0,
            "stagger_sec": 0,
            "errors": [],
            "children": {
                "fooR00_00": {"x_point": [1.0, 2.0, 3.0, 4.0], "log": str(td / "a.log"), "pid": None, "started_at": 0.0},
                "fooR00_01": {"x_point": [5.0, 6.0, 7.0, 8.0], "log": str(td / "b.log"), "pid": None, "started_at": 0.0},
            },
        }

    def test_thread_id_unique_per_child(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            captured, popen = self._capture_cmd()
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(self._state(tmp))
            self.assertEqual(len(captured), 2)
            tids = [c[c.index("--thread-id") + 1] for c in captured]
            names = [c[c.index("--config-name") + 1] for c in captured]
            # config_name keeps the user-visible identity ...
            self.assertEqual(sorted(names), ["fooR00_00", "fooR00_01"])
            # ... but thread_id must NOT equal config_name (would collide).
            for tid, name in zip(tids, names):
                self.assertNotEqual(tid, name,
                                    f"thread_id {tid} == config_name {name}; collision-risk")
                self.assertTrue(tid.startswith(name + "_"),
                                f"thread_id {tid} should namespace under {name}")
            # And the two threads must differ from each other.
            self.assertNotEqual(tids[0], tids[1])
            # node persists thread_id on the child record (for barrier lookup).
            for name in names:
                self.assertIn("thread_id", out["children"][name])

    def test_thread_id_reused_on_resume(self):
        """A crashed parent re-entering launch_children with an already-set
        thread_id must reuse it — otherwise the barrier's checkpoint lookup
        (keyed on the FIRST-assigned thread_id) cannot find the child."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            captured, popen = self._capture_cmd()
            state = self._state(tmp)
            # Pre-populate one child with a thread_id (simulating prior launch).
            state["children"]["fooR00_00"]["thread_id"] = "fooR00_00_deadbeef"
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                cl.node_launch_children(state)
            for c in captured:
                if "fooR00_00" in c:
                    tid = c[c.index("--thread-id") + 1]
                    self.assertEqual(tid, "fooR00_00_deadbeef",
                                     "resume path must reuse the prior thread_id")


class TestIsChildTerminal(unittest.TestCase):
    """`graph.build.is_child_terminal` — relocated from closed_loop in the
    2026-06-06 refactor. Disambiguation of fresh threads vs real terminal
    is load-bearing: see wiki/incidents/barrier-false-positive-round1.md."""

    def test_passes_thread_id_to_get_state(self):
        from graph.build import is_child_terminal
        seen = {}

        class _FakeGraph:
            def get_state(self, cfg):
                seen["cfg"] = cfg
                return None

        is_child_terminal(thread_id="fooR00_00_deadbeef", child_graph=_FakeGraph())
        self.assertEqual(seen["cfg"]["configurable"]["thread_id"], "fooR00_00_deadbeef")

    def test_fresh_thread_returns_false_via_inmemory_saver(self):
        """End-to-end fresh-thread case: build the real inner graph against an
        in-memory checkpointer and call get_state on a never-run thread_id.
        Asserts the load-bearing disambiguation (no checkpoint → not terminal)
        works without any node ever executing."""
        from langgraph.checkpoint.memory import InMemorySaver
        from graph.build import build_graph, is_child_terminal

        saver = InMemorySaver()
        child_graph = build_graph().compile(checkpointer=saver)
        self.assertFalse(is_child_terminal(thread_id="never-run", child_graph=child_graph))


class TestBarrierRefusesEmptyChildren(unittest.TestCase):
    """Regression: barrier on empty launch set must raise, not silently exit.

    History: foilsZ06 (2026-06-05) exited via the all([])==True path after
    decide_next cleared `children`. The exit was misattributed to a LangGraph
    replay bug for several turns. Real trigger was a stale STOP_FLAG, but
    the latent vacuous-all() trap remains a correctness hazard if a future
    refactor ever delivers an empty children dict to the barrier.
    """

    def test_empty_launched_names_raises(self):
        state = {
            "mode": "helical",
            "round_idx": 1,
            "children": {},
            "launched_names": [],
            "completed_names": ["prev_round_a", "prev_round_b"],
            "errors": [],
        }
        with self.assertRaises(RuntimeError) as cm:
            cl.node_barrier(state)
        self.assertIn("launched_names empty", str(cm.exception))


class TestBarrierDeadPid(unittest.TestCase):
    """A child whose process died without writing any resolution artifact
    (no leaderboard row, no broken.txt, non-terminal checkpoint) can never
    resolve — the barrier must mark it completed-failed instead of waiting
    out the timeout cap. foilsf08 crash shape; see
    wiki/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md
    and docs/closed-loop-barrier-fix.md change 1b.
    """

    @staticmethod
    def _dead_pid():
        import subprocess
        proc = subprocess.Popen(["true"])
        proc.wait()
        return proc.pid

    def test_dead_pid_marks_completed_failed(self):
        dead = self._dead_pid()
        state = {
            "mode": "helical",
            "round_idx": 0,
            "barrier_poll_sec": 0,
            "barrier_max_min": 60,
            "children": {
                "fooR00_00": {"pid": dead, "thread_id": "fooR00_00_x"},
            },
            "launched_names": ["fooR00_00"],
            "completed_names": [],
            "errors": [],
        }
        with mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
             mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
             mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
             mock.patch("graph.build.is_child_terminal", return_value=False), \
             mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_stop_requested", return_value=False):
            out = cl.node_barrier(state)
        self.assertEqual(out["completed_names"], ["fooR00_00"])
        self.assertTrue(
            any("died without resolution" in e for e in out["errors"]),
            f"expected dead-pid error, got: {out['errors']}",
        )
        self.assertFalse(out["stop_seen"])
        self.assertFalse(out["timeout_seen"])

    def test_live_pid_not_marked(self):
        # Our own process is definitely alive; with a 0-min backstop cap
        # the barrier should exit via the backstop with the child still
        # pending, NOT via the dead-pid path.
        import os
        state = {
            "mode": "helical",
            "round_idx": 0,
            "barrier_poll_sec": 0,
            "barrier_max_min": 0,
            "children": {
                "fooR00_00": {"pid": os.getpid(), "thread_id": "fooR00_00_x"},
            },
            "launched_names": ["fooR00_00"],
            "completed_names": [],
            "errors": [],
        }
        with mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
             mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
             mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
             mock.patch("graph.build.is_child_terminal", return_value=False), \
             mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_stop_requested", return_value=False):
            out = cl.node_barrier(state)
        self.assertEqual(out["completed_names"], [])
        self.assertTrue(out["timeout_seen"])


class TestStaleClusterSkipIsLoud(unittest.TestCase):
    """Regression: stale `*_cluster.txt` from a crashed prior run must not
    silently skip launch and cause the barrier to hang 240min.
    See wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md.
    """

    def _capture_cmd(self):
        captured = []

        class _FakeProc:
            def __init__(self, cmd):
                self.pid = 999
                self._cmd = cmd

        def _popen(cmd, **kwargs):
            captured.append(list(cmd))
            return _FakeProc(cmd)

        return captured, _popen

    def _two_child_state(self, td):
        return {
            "mode": "helical",
            "alpha": 0.0,
            "round_idx": 0,
            "stagger_sec": 0,
            "errors": [],
            "completed_names": [],
            "children": {
                "fooR00_00": {"x_point": [1.0, 2.0, 3.0, 4.0], "log": str(td / "a.log"), "pid": None, "started_at": 0.0},
                "fooR00_01": {"x_point": [5.0, 6.0, 7.0, 8.0], "log": str(td / "b.log"), "pid": None, "started_at": 0.0},
            },
        }

    def test_stale_cluster_excluded_from_launched_names(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Stale cluster.txt for child 00 only (mimics prior crashed submit).
            sd = tmp / "fooR00_00" / "state"
            sd.mkdir(parents=True)
            (sd / "mubeam_cluster.txt").write_text("70267542")
            captured, popen = self._capture_cmd()
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(self._two_child_state(tmp))
            self.assertEqual(len(captured), 1, "only the non-stale child should Popen")
            self.assertEqual(out["launched_names"], ["fooR00_01"])
            self.assertIn("fooR00_00", out["completed_names"])
            self.assertTrue(
                any("SKIP fooR00_00" in e and "stale" in e for e in out["errors"]),
                f"expected loud SKIP error for fooR00_00, got: {out['errors']}",
            )

    def test_all_stale_then_barrier_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for n in ("fooR00_00", "fooR00_01"):
                sd = tmp / n / "state"
                sd.mkdir(parents=True)
                (sd / "mubeam_cluster.txt").write_text("X")
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(self._two_child_state(tmp))
            self.assertEqual(out["launched_names"], [])
            self.assertEqual(sorted(out["completed_names"]), ["fooR00_00", "fooR00_01"])
            # Empty launched_names now correctly trips node_barrier's guard.
            state = {
                "mode": "helical",
                "round_idx": 0,
                "children": out["children"],
                "launched_names": out["launched_names"],
                "completed_names": out["completed_names"],
                "errors": out["errors"],
            }
            with self.assertRaises(RuntimeError) as cm:
                cl.node_barrier(state)
            self.assertIn("launched_names empty", str(cm.exception))

    def test_leaderboard_resume_is_silent(self):
        """If a child is already in the leaderboard (legit resume), it should
        be skipped silently (no error) — the barrier marks it done on first
        poll tick. Only stale-cluster-without-leaderboard is loud."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Stale cluster.txt AND leaderboard presence for child 00.
            sd = tmp / "fooR00_00" / "state"
            sd.mkdir(parents=True)
            (sd / "mubeam_cluster.txt").write_text("X")
            captured, popen = self._capture_cmd()

            def _in_lb(name, mode):
                return name == "fooR00_00"

            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", side_effect=_in_lb):
                out = cl.node_launch_children(self._two_child_state(tmp))
            self.assertEqual(out["launched_names"], ["fooR00_01"])
            # fooR00_00 is leaderboard-present → not in completed_names, no error.
            self.assertNotIn("fooR00_00", out["completed_names"])
            self.assertFalse(
                any("fooR00_00" in e for e in out["errors"]),
                f"leaderboard resume should be silent, got: {out['errors']}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
