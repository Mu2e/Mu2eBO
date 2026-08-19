"""Self-tests for graph/closed_loop.py — pure-ish, no grid contact.

Run from project root:
  python -m unittest tests.test_closed_loop -v

The barrier/checkpoint/graph machinery (node_assign_names, node_launch_children,
node_barrier, node_decide_next, route_after_decide, _build_outer_graph,
is_child_terminal) is gone -- the parent is now graph/pool.py's bounded
work-pool (see tests/test_pool.py). What remains here are the pieces
graph/pool.py still depends on: the picker subprocess wrapper, the renew-
token gate, and the child-broken signal.
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


class TestRenewToken(unittest.TestCase):
    """renew_token() is a plain zero-arg callable (no more RoundState/round_idx
    shape) wired into run_rolling as `renew=renew_token` -- see
    tests/test_pool.py::TestRenewHook for the call-once-per-launch and
    exception-propagation contracts at the pool level."""

    def setUp(self):
        # RENEW_MIN_INTERVAL_S gate state is module-global (deliberately --
        # it must survive across run_rolling's many renew() calls within one
        # campaign); reset it so tests don't leak state into each other.
        cl._last_renewed_at = 0.0

    @staticmethod
    def _ok():
        return mock.Mock(returncode=0, stderr="")

    @staticmethod
    def _fail():
        return mock.Mock(returncode=1, stderr="auth failed")

    # kinit -R goes through cl.subprocess.run; getToken now goes through the
    # shared cl.run_sourced_bash helper (retry-protected), so the two are
    # mocked separately rather than as one ordered side_effect list.
    def test_happy_path_returns_normally(self):
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._ok()):
            self.assertIsNone(cl.renew_token())

    def test_getToken_nonzero_rc_exits(self):
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._fail()):
            with self.assertRaises(SystemExit) as cm:
                cl.renew_token()
        self.assertEqual(cm.exception.code, 2)

    def test_getToken_raises_exits(self):
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash", side_effect=OSError("ENOKEY")):
            with self.assertRaises(SystemExit) as cm:
                cl.renew_token()
        self.assertEqual(cm.exception.code, 2)

    def test_kinit_failure_does_not_exit(self):
        # kinit -R is best-effort; only getToken failure is fatal
        with mock.patch.object(cl.subprocess, "run", return_value=self._fail()), \
             mock.patch.object(cl, "run_sourced_bash", return_value=self._ok()):
            self.assertIsNone(cl.renew_token())

    def test_time_gate_skips_within_window(self):
        # IMPORTANT 7, review round 2: run_rolling calls renew() once per
        # LAUNCH (~40/campaign vs ~2 before), and every real call sources
        # setupmu2e-art.sh from /cvmfs -- a known flake class that is FATAL
        # on persistent failure. The gate caps exposure regardless of call
        # frequency.
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash",
                               return_value=self._ok()) as m_bash:
            cl.renew_token()  # first call: real, sets _last_renewed_at
            m_bash.assert_called_once()
            m_bash.reset_mock()
            cl.renew_token()  # second call, same instant: gated, no-op
        m_bash.assert_not_called()

    def test_time_gate_allows_after_window_elapses(self):
        with mock.patch.object(cl.subprocess, "run", return_value=self._ok()), \
             mock.patch.object(cl, "run_sourced_bash",
                               return_value=self._ok()) as m_bash:
            cl.renew_token()
            cl._last_renewed_at -= (cl.RENEW_MIN_INTERVAL_S + 1)
            m_bash.reset_mock()
            cl.renew_token()
        m_bash.assert_called_once()

    def test_wired_into_run_rolling_call(self):
        # The actual regression this whole class guards against: run_rolling
        # supporting `renew`/`stop_flag` hooks is necessary but not
        # sufficient -- main() has to actually pass them. Before the round-1
        # fix, main() called run_rolling() with no `renew=` at all, silently
        # dropping krb5 renewal (kerberos-mid-run-expiry); before round 2,
        # `stop_flag=` was likewise never passed, so STOP_CLOSED_LOOP did
        # nothing. run_rolling is imported at module level specifically so
        # it's a patchable cl.run_rolling attribute here (MINOR 12, review
        # round 2 -- this used to grep the source text, which also caught
        # the regression but doesn't survive a reformat).
        fake_result = {"launched": 0, "rows": 0, "aborted": False, "outcomes": []}
        argv = ["closed_loop.py", "--mode", "foilspf", "--q", "2",
                "--max-evals", "4", "--name-prefix", "zz"]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(cl, "run_rolling",
                                   return_value=fake_result) as m, \
                 mock.patch.object(cl, "GRAPH_DATA", tmp), \
                 mock.patch("paths.verify"), \
                 mock.patch.object(sys, "argv", argv):
                rc = cl.main()
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        self.assertIs(kwargs.get("renew"), cl.renew_token)
        self.assertIs(kwargs.get("stop_flag"), cl._stop_requested)
        self.assertEqual(rc, 0)


class TestPredictPicks(unittest.TestCase):
    # cl_min retired per ADR-0001: every picker routes through
    # _botorch_picks_subprocess; there is no in-process GP path to mock.
    # node_predict_picks itself is no longer called by main() (pool.py
    # calls _botorch_picks_subprocess directly per-pick) but is kept for
    # --dry-run parity; these tests pin its non-rolling behavior.

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
