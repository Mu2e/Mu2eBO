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
import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))  # BO/pipeline modules (2026-07-17 reorg)

# closed_loop.py calls modes.stamp_mode_from_argv() at import, which only
# stamps when "--mode <spec>" is on the command line (real launches always
# pass it) or an already-set AUTORESEARCH_MODE; under `-m unittest` there is
# no such flag, so core/runtime.py's module-level
# `_modes.SPECS[os.environ.get("AUTORESEARCH_MODE", _modes.DEFAULT_MODE)]`
# decides. tests/__init__.py stamps the suite's mode once for the whole
# process -- this setdefault is only reached by `discover -s tests` without
# `-t .`, which never imports the package __init__. It must therefore agree
# with tests/__init__.py; it used to say "foilsflash" and, because this file
# sorts first under discovery, silently pinned the ENTIRE suite to foilsflash.
os.environ.setdefault("AUTORESEARCH_MODE", "foilspf")
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


class TestDryRun(unittest.TestCase):
    """`node_predict_picks` and `_leaderboard_len` were deleted (final
    review, finding M2): nothing called them, `_dry_run` always went
    straight to `_botorch_picks_subprocess`, and their return dict was the
    retired RoundState shape. These retarget the four assertions that had
    real value -- that every picker, including the default, routes through
    the one picker subprocess -- at the live caller.
    """

    @staticmethod
    def _args(**kw):
        base = dict(mode="foilspf", q=2, picker="hybrid", name_prefix="foo")
        base.update(kw)
        return argparse.Namespace(**base)

    def _run(self, args, picks):
        buf = io.StringIO()
        with mock.patch.object(cl, "_botorch_picks_subprocess",
                               return_value=picks) as m, \
             contextlib.redirect_stdout(buf):
            rc = cl._dry_run(args)
        return rc, m, buf.getvalue()

    def _dims(self, mode):
        return len(cl._modes.SPECS[mode].knob_names)

    def test_default_picker_routes_through_the_subprocess(self):
        n = self._dims("foilspf")
        picks = [(float(i),) * n for i in range(2)]
        rc, m, out = self._run(self._args(), picks)
        self.assertEqual(rc, 0)
        self.assertEqual(m.call_args.kwargs.get("picker"), cl.DEFAULT_PICKER)
        self.assertEqual(m.call_args.kwargs.get("round_idx"), 0)
        self.assertEqual(m.call_args.args[0], "foilspf")

    def test_explicit_picker_is_forwarded(self):
        n = self._dims("foilsflash")
        picks = [(float(i),) * n for i in range(3)]
        rc, m, out = self._run(
            self._args(mode="foilsflash", q=3, picker="qlnei"), picks)
        self.assertEqual(m.call_args.kwargs.get("picker"), "qlnei")
        self.assertEqual(m.call_args.args[1], 3)  # q

    def test_prints_production_shaped_names(self):
        """Finding M3: the preview printed `{prefix}R00_{j:02d}` while
        graph/pool.py emits `{prefix}R{i:02d}_00`, so an operator was shown
        names the campaign would never use."""
        n = self._dims("foilspf")
        picks = [(float(i),) * n for i in range(3)]
        rc, m, out = self._run(self._args(q=3), picks)
        for j in range(3):
            self.assertIn(f"fooR{j:02d}_00", out)
        self.assertNotIn("fooR00_01", out)

    def test_labels_come_from_the_registry(self):
        n = self._dims("foilspf")
        picks = [(1.0,) * n]
        rc, m, out = self._run(self._args(q=1), picks)
        for label in cl._modes.SPECS["foilspf"].knob_names:
            self.assertIn(f"{label}=", out)


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
