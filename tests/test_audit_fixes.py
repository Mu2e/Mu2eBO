"""Targeted regression tests for the /simplify audit fixes (2026-05-29) and
later ones. The pipeline-only fix classes went with the pipeline in Phase C3
(2026-09-28); what remains tests surviving code:

  TestRunSourcedBash      -- graph/sourced_bash.py (env-flake retry helper)
  TestPendingTsvRoundTrip -- core/leaderboard.py (pending TSV round-trip)

Run from project root:
  PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
"""
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "graph"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

import modes  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402


class TestRunSourcedBash(unittest.TestCase):
    """graph/sourced_bash.py — shared cvmfs/spack env-flake retry helper
    (the offline_preflight check runs through it). See
    wiki/incidents/sourced-env-stderr-swallowed.md.
    """
    @classmethod
    def setUpClass(cls):
        import sourced_bash
        cls.sb = sourced_bash

    def _proc(self, rc, out="", err=""):
        return subprocess.CompletedProcess(["bash"], rc, stdout=out, stderr=err)

    def test_success_first_try_no_retry(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("true", backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 0)
        self.assertFalse(r.timed_out)
        self.assertEqual(m.call_count, 1)      # no retries on success
        sleep.assert_not_called()

    def test_retries_then_succeeds(self):
        # log= captured, not printed: these rc=127 banners are the first
        # thing a new operator sees when they run the suite from a fresh
        # clone, and a mocked failure must not look like a real one.
        seq = [self._proc(127), self._proc(127), self._proc(0)]
        log = io.StringIO()
        with mock.patch.object(self.sb.subprocess, "run", side_effect=seq) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("flaky", backoffs=(1, 2, 3), log=log)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(sleep.call_count, 2)  # slept before attempts 2 and 3
        self.assertEqual(log.getvalue().count("retrying in"), 2)
        self.assertIn("rc=127", log.getvalue())

    def test_exhausts_and_returns_last_failure(self):
        log = io.StringIO()
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(127, err="boom")) as m, \
             mock.patch.object(self.sb.time, "sleep"):
            r = self.sb.run_sourced_bash("always-fail", backoffs=(1, 2, 3),
                                         log=log)
        self.assertEqual(r.returncode, 127)    # returned, NOT raised
        self.assertEqual(m.call_count, 4)      # len(backoffs)+1 attempts
        # One banner per retry, none after the final attempt.
        self.assertEqual(log.getvalue().count("retrying in"), 3)

    def test_should_retry_predicate_banner_blocks_retry(self):
        # Preflight predicate: nonzero rc but a Geant4 banner -> genuine
        # result, must NOT retry.
        def banner_gate(p):
            started = "Geant4" in (p.stdout or "") + (p.stderr or "")
            return p.returncode != 0 and not started
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(3, out="...Geant4 version...")) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("mu2e", should_retry=banner_gate,
                                         backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 3)
        self.assertEqual(m.call_count, 1)      # banner present -> no retry
        sleep.assert_not_called()

    def test_timeout_is_not_retried(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("mu2e", 5)) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("slow", timeout=5, backoffs=(1, 2, 3))
        self.assertTrue(r.timed_out)
        self.assertEqual(r.returncode, -1)
        self.assertEqual(m.call_count, 1)      # timeout = running, not a flake
        sleep.assert_not_called()

    def test_spack_cache_export_prepended(self):
        # NFSv4.0 seqid-wedge mitigation: every command must run with
        # spack's cache (and its fcntl locks) on node-local /tmp, not
        # NFS HOME. See wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md.
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m:
            self.sb.run_sourced_bash("source setup.sh && getToken")
        argv = m.call_args[0][0]
        self.assertEqual(argv[:2], ["bash", "-c"])
        self.assertTrue(argv[2].startswith(
            "export SPACK_USER_CACHE_PATH=/tmp/spack_cache_"))
        self.assertTrue(argv[2].endswith(" && source setup.sh && getToken"))

    def test_spack_cache_export_prepended_login_shell(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m:
            self.sb.run_sourced_bash("getToken", login=True)
        argv = m.call_args[0][0]
        self.assertEqual(argv[:2], ["bash", "-lc"])
        self.assertTrue(argv[2].startswith("export SPACK_USER_CACHE_PATH="))


class TestPendingTsvRoundTrip(unittest.TestCase):
    """pending_remove must leave the file newline-terminated (2026-07-26).

    The old code wrote `"\\n".join([header] + kept) + ("\\n" if kept else "")`,
    so emptying the file left the header UNterminated. pending_add opens in
    "a" mode, so the next proposal landed on the header line itself
    ("...submitted_atfoilsflash22R00_00\\t[...]") and the file stayed a single
    line forever — pending_load() silently returned 0 rows.

    It survived unnoticed because every consumer degraded QUIETLY: Python modes
    recovered x from parse_geom, the propose_one collision guard just stopped
    seeing pending names, and botorch_ask got an empty X_pending (so concurrent
    children stopped repelling each other's in-flight points). It only became
    visible when foilsflash went JSON-defined and the pending TSV became the
    sole record of x — costing foilsflash24R00_00 a finished 3.5 h eval.

    Existing coverage checked only that the removal was CALLED before the
    row was appended; nothing ever read the file back after a removal.
    Driven through Leaderboard directly since Phase C3 (it went through the
    pipeline's JsonMode wrappers before).
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Any study exercises this generically.
        self.lb = Leaderboard.for_study(
            modes.STUDIES["foilsflash_ax"],
            path=self.tmp / "leaderboard_bo_probe.tsv", archive_path=None)

    def _x(self, v):
        return [float(v)] * len(self.lb.knob_names)

    def test_append_after_emptying_is_still_parseable(self):
        """The exact production sequence: propose, evaluate (clears the last
        row), propose again. The second proposal must be readable."""
        self.lb.pending_add("cfgA", self._x(1), 1.0)
        self.assertTrue(self.lb.pending_remove("cfgA"))
        self.lb.pending_add("cfgB", self._x(2), 1.0)
        got = self.lb.pending_load()
        self.assertEqual([c for c, _ in got], ["cfgB"],
                         "pending row lost: the file was not newline-terminated "
                         "after the previous removal")

    def test_file_is_newline_terminated_when_emptied(self):
        self.lb.pending_add("cfgA", self._x(1), 1.0)
        self.lb.pending_remove("cfgA")
        self.assertTrue(self.lb.pending_path().read_text().endswith("\n"))

    def test_many_propose_evaluate_cycles_never_corrupt(self):
        """A single bad cycle poisons the file permanently, so iterate."""
        for i in range(5):
            self.lb.pending_add(f"cfg{i}", self._x(i), 1.0)
            self.assertEqual([c for c, _ in self.lb.pending_load()], [f"cfg{i}"],
                             f"cycle {i}: pending unreadable")
            self.lb.pending_remove(f"cfg{i}")
        self.assertEqual(self.lb.pending_load(), [])

    def test_x_survives_the_round_trip_exactly(self):
        """The pending file is the record of an in-flight eval's
        coordinates, so the values must come back bit-for-bit, not merely
        parse."""
        x = [250.0, 203.394671, 0.209299, 0.621833, 0.95, 0.720726]
        self.lb.pending_add("cfgX", x, 1.0e5)
        (_, got), = self.lb.pending_load()
        self.assertEqual(got, x)


if __name__ == "__main__":
    unittest.main(verbosity=2)
