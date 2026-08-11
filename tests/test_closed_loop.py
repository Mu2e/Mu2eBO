"""Self-tests for graph/closed_loop.py — pure-ish, no grid contact.

Run from project root:
  python -m unittest tests.test_closed_loop -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))  # BO/pipeline modules (2026-07-17 reorg)

# graph/closed_loop.py's own presniff_mode() only stamps AUTORESEARCH_MODE
# when "--mode" is present in sys.argv (real launches always pass it); under
# `-m unittest` there is no such flag, so graph/config.py's module-level
# `_modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foils")]` would KeyError
# at the `from config import (...)` below now that "foils" no longer exists
# in modes.SPECS (archived 2026-08-08). setdefault so an explicitly-set env
# (e.g. a real launch's own --mode) always wins.
os.environ.setdefault("AUTORESEARCH_MODE", "foilsflash")
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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            "name_prefix": "foils",
            "round_idx": 0,
            "mode": "foils",
            "children": {
                "_pick_00": {"x_point": [1, 2, 3, 4]},
                "_pick_01": {"x_point": [5, 6, 7, 8]},
            },
            "completed_names": [],
        }

    def test_placeholders_become_real_names(self):
        # node_assign_names now does ONE hoisted _leaderboard_names(mode)
        # read instead of a per-child _child_in_leaderboard call.
        with mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertEqual(
            sorted(out["children"]), ["foilsR00_00", "foilsR00_01"]
        )
        self.assertEqual(
            out["children"]["foilsR00_00"]["x_point"], [1, 2, 3, 4]
        )
        self.assertEqual(out["completed_names"], [])

    def test_already_in_leaderboard_skipped(self):
        with mock.patch.object(cl, "_leaderboard_names",
                                return_value={"foilsR00_00"}), \
             mock.patch.object(cl, "_child_is_broken", return_value=False):
            out = cl.node_assign_names(self._state())
        self.assertNotIn("foilsR00_00", out["children"])
        self.assertIn("foilsR00_01", out["children"])
        self.assertIn("foilsR00_00", out["completed_names"])

    def test_broken_skipped(self):
        with mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
             mock.patch.object(cl, "_child_is_broken",
                                lambda n: n == "foilsR00_01"):
            out = cl.node_assign_names(self._state())
        self.assertIn("foilsR00_00", out["children"])
        self.assertNotIn("foilsR00_01", out["children"])
        self.assertIn("foilsR00_01", out["completed_names"])


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
    # cl_min retired per ADR-0001: every picker routes through
    # _botorch_picks_subprocess; there is no in-process GP path to mock.

    def test_under_q_logs_error(self):
        state = {"q": 5, "round_idx": 0, "errors": [], "mode": "foils"}
        picks = [(1, 2, 3, 4), (5, 6, 7, 8)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks), \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        self.assertTrue(any("only got 2/5 picks" in e for e in out["errors"]))
        self.assertEqual(len(out["children"]), 2)
        self.assertEqual(out["history_len_before"], 42)

    def test_full_q_no_error_default_picker(self):
        # No explicit picker: DEFAULT_PICKER (hybrid) must route through the
        # subprocess like everything else.
        state = {"q": 2, "round_idx": 0, "errors": [], "mode": "foils"}
        picks = [(1, 2, 3, 4), (5, 6, 7, 8)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=10):
            out = cl.node_predict_picks(state)
        self.assertEqual(m.call_args.kwargs.get("picker"), cl.DEFAULT_PICKER)
        self.assertEqual(out["errors"], [])
        self.assertEqual(sorted(out["children"]), ["_pick_00", "_pick_01"])
        self.assertEqual(out["history_len_before"], 10)

    def test_qnparego_routes_to_botorch_subprocess(self):
        state = {"q": 3, "round_idx": 2, "errors": [], "mode": "foilsflash",
                 "picker": "qnparego"}
        picks = [(float(i),) * 6 for i in range(3)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs.get("picker"), "qnparego")
        self.assertEqual(m.call_args.args[0], "foilsflash")  # mode
        self.assertEqual(m.call_args.args[2], 2)             # round_idx
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["children"]), 3)
        self.assertEqual(out["history_len_before"], 42)

    def test_hybrid_routes_to_botorch_subprocess(self):
        state = {"q": 5, "round_idx": 0, "errors": [], "mode": "foilsflash",
                 "picker": "hybrid"}
        picks = [(float(i),) * 6 for i in range(5)]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=10):
            out = cl.node_predict_picks(state)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs.get("picker"), "hybrid")
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
            "mode": "foils",
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
    """Regression: barrier on an EMPTY CHILDREN DICT must raise, not silently
    exit.

    History: foilsZ06 (2026-06-05) exited via the all([])==True path after
    decide_next cleared `children`. The exit was misattributed to a LangGraph
    replay bug for several turns. Real trigger was a stale STOP_FLAG, but
    the latent vacuous-all() trap remains a correctness hazard if a future
    refactor ever delivers an empty children dict to the barrier.

    NEW contract (ChildTracker full-cut): the guard narrows to "children
    dict empty" specifically. An empty `launched_names` with a NON-empty
    children dict (all-stale or all-resume round — nothing Popen'd this
    round) is now legitimate and proceeds to the tracker instead of raising.
    """

    def test_empty_children_dict_raises(self):
        state = {
            "mode": "foils",
            "round_idx": 1,
            "children": {},
            "launched_names": [],
            "completed_names": ["prev_round_a", "prev_round_b"],
            "errors": [],
        }
        with self.assertRaises(RuntimeError) as cm:
            cl.node_barrier(state)
        self.assertIn("children dict empty", str(cm.exception))

    def test_children_present_nothing_launched_proceeds(self):
        # Nothing Popen'd this round (e.g. a pure resume) but the children
        # dict is non-empty — the barrier must NOT raise; it hands off to
        # the tracker, which resolves the child via the leaderboard row.
        state = {
            "mode": "foils",
            "round_idx": 0,
            "barrier_poll_sec": 0,
            "barrier_max_min": 60,
            "children": {"fooR00_00": {"pid": None, "thread_id": "fooR00_00_x"}},
            "launched_names": [],
            "completed_names": [],
            "errors": [],
        }
        with mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
             mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
             mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
             mock.patch("graph.build.is_child_terminal", return_value=False), \
             mock.patch.object(cl, "_leaderboard_names", return_value={"fooR00_00"}), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_stop_requested", return_value=False):
            out = cl.node_barrier(state)
        self.assertEqual(out["completed_names"], ["fooR00_00"])


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
            "mode": "foils",
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
            "mode": "foils",
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
            "mode": "foils",
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
            # node_launch_children no longer does its own completed/error
            # bookkeeping for stale-cluster children (moved to the barrier's
            # ChildTracker — see test_all_stale_resolves_via_tracker below).
            self.assertNotIn("completed_names", out)
            self.assertEqual(out["children"]["fooR00_00"]["pid"], None)

    def test_all_stale_resolves_via_tracker(self):
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
            # Empty launched_names with a non-empty children dict no longer
            # trips node_barrier's guard — it now RETURNS (no raise), with
            # every stale name resolved via the tracker's STALE_CLUSTER path.
            state = {
                "mode": "foils",
                "round_idx": 0,
                "barrier_poll_sec": 0,
                "barrier_max_min": 60,
                "children": out["children"],
                "launched_names": out["launched_names"],
                "completed_names": [],
                "errors": out["errors"],
            }
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
                 mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
                 mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
                 mock.patch("graph.build.is_child_terminal", return_value=False), \
                 mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
                 mock.patch.object(cl, "_child_is_broken", return_value=False), \
                 mock.patch.object(cl, "_stop_requested", return_value=False):
                out2 = cl.node_barrier(state)
            self.assertEqual(sorted(out2["completed_names"]),
                              ["fooR00_00", "fooR00_01"])
            stale_errors = [e for e in out2["errors"] if "STALE_CLUSTER" in e]
            self.assertEqual(
                len(stale_errors), 2,
                f"expected one STALE_CLUSTER error line per name, got: {out2['errors']}")

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
            # node_launch_children no longer produces completed_names/errors
            # bookkeeping at all (moved to the barrier's ChildTracker) — a
            # leaderboard-present resume is silent by construction here.
            self.assertNotIn("completed_names", out)
            self.assertFalse(
                any("fooR00_00" in e for e in out["errors"]),
                f"leaderboard resume should be silent, got: {out['errors']}",
            )


class TestLaunchFailedResolvesAtBarrier(unittest.TestCase):
    """Review finding: a child whose `subprocess.Popen` RAISES in
    node_launch_children ends up with pid=None and NO *_cluster.txt — the
    old (deleted) launch bookkeeping force-completed it immediately, but the
    ChildTracker only resolved pid-None children via has_cluster, so a
    launch-failed child silently stayed RUNNING until the 24h barrier
    backstop. `rec["launch_failed"]` + the tracker's immediate-resolve
    branch restore loud, immediate resolution.
    """

    def _one_child_state(self, td):
        return {
            "mode": "foils",
            "alpha": 0.0,
            "round_idx": 0,
            "stagger_sec": 0,
            "errors": [],
            "completed_names": [],
            "children": {
                "fooR00_00": {"x_point": [1.0, 2.0, 3.0, 4.0], "log": str(td / "a.log"), "pid": None, "started_at": 0.0},
            },
        }

    def test_popen_failure_resolves_at_barrier(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            def _raise_popen(cmd, **kwargs):
                raise OSError("fork failed (simulated)")

            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", _raise_popen), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(self._one_child_state(tmp))
            self.assertEqual(out["launched_names"], [])
            self.assertTrue(
                any("launch[fooR00_00]" in e for e in out["errors"]),
                f"expected launch error, got: {out['errors']}")
            self.assertTrue(out["children"]["fooR00_00"].get("launch_failed"))
            self.assertIsNone(out["children"]["fooR00_00"]["pid"])

            # Empty launched_names with a non-empty children dict does NOT
            # trip node_barrier's empty-children guard (see
            # TestBarrierRefusesEmptyChildren) — it proceeds to the tracker,
            # which must resolve the launch-failed child immediately.
            state = {
                "mode": "foils",
                "round_idx": 0,
                "barrier_poll_sec": 0,
                "barrier_max_min": 60,
                "children": out["children"],
                "launched_names": out["launched_names"],
                "completed_names": [],
                "errors": out["errors"],
            }
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
                 mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
                 mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
                 mock.patch("graph.build.is_child_terminal", return_value=False), \
                 mock.patch.object(cl, "_leaderboard_names", return_value=set()), \
                 mock.patch.object(cl, "_child_is_broken", return_value=False), \
                 mock.patch.object(cl, "_stop_requested", return_value=False):
                out2 = cl.node_barrier(state)
            self.assertEqual(out2["completed_names"], ["fooR00_00"])
            self.assertTrue(
                any("launch failed" in e for e in out2["errors"]),
                f"expected 'launch failed' barrier message, got: {out2['errors']}")

    def test_resolved_launch_failed_child_not_relaunched(self):
        """Final-review finding (rolling zombie): a child that launch-failed
        in an earlier wave and was resolved as DEAD_UNRESOLVED lands in
        `completed_names`, but rolling mode never clears the `children`
        dict between waves. Without a completed_names check, this record
        (pid=None, no cluster.txt, no leaderboard row, no broken.txt) looks
        indistinguishable from a fresh unlaunched pick and would be
        re-Popen'd — running UNTRACKED since the tracker already counts it
        done. `node_launch_children` must skip it instead."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            popen_mock = mock.Mock()
            state = {
                "mode": "foils",
                "alpha": 0.0,
                "round_idx": 1,
                "rolling": True,
                "stagger_sec": 0,
                "errors": [],
                "completed_names": ["fooR00_00"],
                "children": {
                    "fooR00_00": {
                        "x_point": [1.0, 2.0, 3.0, 4.0],
                        "log": str(tmp / "a.log"),
                        "pid": None,
                        "launch_failed": True,
                    },
                },
            }
            with mock.patch.object(cl, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch.object(cl.subprocess, "Popen", popen_mock), \
                 mock.patch.object(cl, "_child_in_leaderboard", return_value=False):
                out = cl.node_launch_children(state)
            popen_mock.assert_not_called()
            self.assertEqual(out["launched_names"], [])


class TestRolling(unittest.TestCase):
    """--rolling pool-replenishment semantics (predict / barrier / decide /
    route). The barrier path (rolling=False) is pinned by every other class
    in this file — these tests only cover the rolling branches."""

    def _state(self, **kw):
        base = {
            "mode": "foils", "q": 3, "max_evals": 6, "rolling": True,
            "round_idx": 1, "errors": [], "picker": "hybrid",
            "children": {
                "foilsR00_00": {"x_point": [1.0] * 6, "pid": 11},
                "foilsR00_01": {"x_point": [2.0] * 6, "pid": 12},
                "foilsR00_02": {"x_point": [3.0] * 6, "pid": 13},
            },
            "completed_names": ["foilsR00_01"],
            "no_row_streak": 0,
            "prev_completed_names": [],
            "history_len_before": 42,
        }
        base.update(kw)
        return base

    def test_predict_replenishes_free_slots_with_pending(self):
        # 3-wide pool, 2 in flight -> 1 replacement; picker gets the 2
        # running x_points as pending (X_pending fantasies).
        state = self._state()
        picks = [(9.0,) * 6]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        self.assertEqual(m.call_args.args[1], 1)  # q_next
        pend = m.call_args.kwargs["pending"]
        self.assertEqual(sorted(p[0] for p in pend), [1.0, 3.0])
        self.assertIn("foilsR00_00", out["children"])  # carried forward
        self.assertIn("_pick_00", out["children"])     # replacement added

    def test_predict_budget_caps_replenishment(self):
        # launched_total=3, max_evals=4 -> only 1 slot despite 1 free + ...
        state = self._state(max_evals=4, completed_names=["foilsR00_00",
                                                          "foilsR00_01"])
        picks = [(9.0,) * 6]
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            cl.node_predict_picks(state)
        # pool has 2 free slots but budget allows only 4-3=1
        self.assertEqual(m.call_args.args[1], 1)

    def test_predict_drain_skips_subprocess(self):
        # Budget exhausted: no subprocess call, children untouched.
        state = self._state(max_evals=3)
        with mock.patch.object(cl, "_botorch_picks_subprocess") as m, \
             mock.patch.object(cl, "_leaderboard_len", return_value=42):
            out = cl.node_predict_picks(state)
        m.assert_not_called()
        self.assertNotIn("children", out)
        self.assertEqual(out["history_len_before"], 42)

    def test_barrier_exits_on_first_resolution(self):
        # One child lands a row on the first tick, one is alive: rolling
        # barrier must hand the freed slot back instead of waiting.
        state = {
            "mode": "foils", "round_idx": 1, "rolling": True,
            "barrier_poll_sec": 0, "barrier_max_min": 60,
            "children": {
                "fooR00_00": {"pid": os.getpid(), "thread_id": "a"},
                "fooR00_01": {"pid": os.getpid(), "thread_id": "b"},
            },
            "launched_names": ["fooR00_00", "fooR00_01"],
            "completed_names": [], "errors": [],
        }
        with mock.patch.object(cl, "_open_saver_conn", return_value=mock.Mock()), \
             mock.patch.object(cl, "SqliteSaver", return_value=mock.Mock()), \
             mock.patch("graph.build.build_graph", return_value=mock.Mock()), \
             mock.patch("graph.build.is_child_terminal", return_value=False), \
             mock.patch.object(cl, "_leaderboard_names",
                               return_value={"fooR00_00"}), \
             mock.patch.object(cl, "_child_is_broken", return_value=False), \
             mock.patch.object(cl, "_stop_requested", return_value=False):
            out = cl.node_barrier(state)
        self.assertEqual(out["completed_names"], ["fooR00_00"])
        self.assertFalse(out["stop_seen"])
        self.assertFalse(out["timeout_seen"])

    def test_decide_streak_accumulates_and_resets(self):
        # 1 newly-resolved child whose row is ABSENT from the leaderboard
        # -> rowless -> streak 1, children NOT cleared.
        state = self._state()
        with mock.patch.object(cl, "_leaderboard_len", return_value=42), \
             mock.patch.object(cl, "_leaderboard_names", return_value=set()):
            out = cl.node_decide_next(state)
        self.assertEqual(out["no_row_streak"], 1)
        self.assertFalse(out["zero_rows"])
        self.assertFalse(out["rolling_done"])
        self.assertNotIn("children", out)
        self.assertNotIn("launched_names", out)
        # the resolved child's row PRESENT -> resets the streak
        state2 = self._state(no_row_streak=2)
        with mock.patch.object(cl, "_leaderboard_len", return_value=43), \
             mock.patch.object(cl, "_leaderboard_names",
                               return_value={"foilsR00_01"}):
            out2 = cl.node_decide_next(state2)
        self.assertEqual(out2["no_row_streak"], 0)

    def test_decide_streak_immune_to_baseline_absorbed_row(self):
        # Regression (incidents/rolling-no-row-streak-false-increment): a child
        # resolved AND its row IS in the leaderboard, but the length baseline
        # already absorbed that row (new_rows delta == 0 — the ff18 w1 race).
        # Count-based accounting incremented the streak on this SUCCESSFUL
        # child; name-based must keep it at 0.
        state = self._state(completed_names=["foilsR00_01"],
                            prev_completed_names=[], no_row_streak=0,
                            history_len_before=100)
        with mock.patch.object(cl, "_leaderboard_len", return_value=100), \
             mock.patch.object(cl, "_leaderboard_names",
                               return_value={"foilsR00_01"}):
            out = cl.node_decide_next(state)
        self.assertEqual(out["no_row_streak"], 0)  # NOT 1
        self.assertFalse(out["zero_rows"])

    def test_decide_aborts_on_full_pool_streak(self):
        # q consecutive rowless resolutions == foilsX04 shape -> abort.
        state = self._state(no_row_streak=2)
        with mock.patch.object(cl, "_leaderboard_len", return_value=42), \
             mock.patch.object(cl, "_leaderboard_names", return_value=set()):
            out = cl.node_decide_next(state)
        self.assertEqual(out["no_row_streak"], 3)
        self.assertTrue(out["zero_rows"])

    def test_decide_rolling_done_when_budget_drained(self):
        state = self._state(
            max_evals=3,
            completed_names=["foilsR00_00", "foilsR00_01", "foilsR00_02"])
        with mock.patch.object(cl, "_leaderboard_len", return_value=44), \
             mock.patch.object(cl, "_leaderboard_names",
                               return_value={"foilsR00_00", "foilsR00_01",
                                             "foilsR00_02"}):
            out = cl.node_decide_next(state)
        self.assertTrue(out["rolling_done"])

    def test_route_rolling(self):
        with mock.patch.object(cl, "_stop_requested", return_value=False):
            self.assertEqual(
                cl.route_after_decide({"rolling": True, "rolling_done": True}),
                cl.END)
            self.assertEqual(
                cl.route_after_decide({"rolling": True, "zero_rows": True}),
                cl.END)
            self.assertEqual(
                cl.route_after_decide({"rolling": True, "timeout_seen": True}),
                cl.END)
            # max_rounds is IGNORED under rolling — budget governs.
            self.assertEqual(
                cl.route_after_decide(
                    {"rolling": True, "round_idx": 99, "max_rounds": 1}),
                "renew_token")


if __name__ == "__main__":
    unittest.main(verbosity=2)
