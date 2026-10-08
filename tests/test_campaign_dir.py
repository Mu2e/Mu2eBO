"""core/campaign_dir.py: child names and the campaign record."""
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import campaign_dir as cd  # noqa: E402
from campaign_dir import (CampaignBusy, CampaignDir, child_name,  # noqa: E402
                          is_child, parse_child)
from tests.engine_fixtures import TmpCase  # noqa: E402

HOLD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from campaign_dir import CampaignDir
from pathlib import Path
with CampaignDir(Path(sys.argv[2]), sys.argv[3]).start({"study": "s"}):
    open(sys.argv[4], "w").close()
    time.sleep(30)
"""


class TestChildNames(unittest.TestCase):
    def test_child_names(self):
        self.assertEqual(child_name("foo", 7), "fooR07_00")
        self.assertEqual(parse_child("fooR07_00"), ("foo", 7))
        self.assertEqual(parse_child("fooR123_00"), ("foo", 123))
        self.assertEqual(parse_child("foo2R00_00"), ("foo2", 0))
        for bad in ("fooR5_00", "fooR00_01", "fooR00_00x", "single", "R00_00"):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_child(bad))
        self.assertTrue(is_child("foo", "fooR12_00"))
        self.assertFalse(is_child("foo", "foo2R00_00"))
        self.assertFalse(is_child("foo", "fooR5_00"))


class _Camp(TmpCase):
    def setUp(self):
        super().setUp()
        self.camp = CampaignDir(self.tmp, "cmp")

    def hold_elsewhere(self, prefix="cmp"):
        """Another process alive on `prefix`; returns once it holds it."""
        ready = self.tmp / f"{prefix}.ready"
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(ROOT / "core"),
                              str(self.tmp), prefix, str(ready)])
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait()))
        deadline = time.monotonic() + 20
        while not ready.exists():
            self.assertLess(time.monotonic(), deadline, "holder never ready")
            time.sleep(0.05)
        return p


class TestRecord(_Camp):
    def test_start_record_finish(self):
        self.assertIsNone(self.camp.record())
        self.assertFalse(self.camp.alive())
        with self.camp.start({"prefix": "cmp", "study": "s", "q": 2,
                              "max_evals": 4}):
            self.assertEqual(self.camp.record()["study"], "s")
            self.assertTrue(self.camp.alive())
            self.assertEqual(self.camp.launched_by(), "shell")
            self.camp.finish(0)
        self.assertFalse(self.camp.alive())
        rec = self.camp.record()
        self.assertEqual((rec["exit_code"], rec["q"]), (0, 2))
        self.assertIn("ended", rec)
        self.assertEqual(self.camp.exit_code(), 0)

    def test_a_second_start_is_refused(self):
        self.hold_elsewhere()
        with self.assertRaises(CampaignBusy) as cm:
            with self.camp.start({"study": "s"}):
                pass
        self.assertIn("already running", str(cm.exception))

    def test_restart_of_an_ended_prefix(self):
        with self.camp.start({"study": "s", "started": 1.0}):
            self.camp.append_outcome({"name": "cmpR00_00", "reason": "ok"})
            self.camp.finish(0)
        with self.camp.start({"study": "s", "started": 2.0}):
            self.assertEqual(self.camp.record()["started"], 2.0)
            self.assertNotIn("exit_code", self.camp.record())
        self.assertEqual(list(self.camp.outcomes()), ["cmpR00_00"])

    def test_a_bad_record_raises(self):
        self.camp.path.mkdir(parents=True)
        (self.camp.path / cd.RECORD).write_text("{")
        with self.assertRaises(ValueError):
            self.camp.record()


class TestOutcomes(_Camp):
    def test_outcomes(self):
        self.assertEqual(self.camp.outcomes(), {})
        self.camp.path.mkdir(parents=True)
        self.camp.append_outcome({"name": "cmpR00_00", "reason": "child rc=1"})
        self.camp.append_outcome({"name": "cmpR01_00", "reason": "ok"})
        self.camp.append_outcome({"name": "cmpR00_00", "reason": "ok"})
        out = self.camp.outcomes()
        self.assertEqual({n: o["reason"] for n, o in out.items()},
                         {"cmpR00_00": "ok", "cmpR01_00": "ok"})

    def test_a_truncated_line_raises(self):
        self.camp.path.mkdir(parents=True)
        (self.camp.path / cd.OUTCOMES).write_text(
            json.dumps({"name": "cmpR00_00"}) + "\n" + '{"name": "cmpR01_')
        with self.assertRaises(ValueError) as cm:
            self.camp.outcomes()
        self.assertIn("outcomes.jsonl:2", str(cm.exception))


class TestTruncatedOutcomes(_Camp):
    def test_appends_after_a_truncated_line_stay_readable(self):
        """A parent killed mid-append leaves a partial line; a relaunch's
        appends must not glue onto it, and the good lines stay readable
        with the bad one reported."""
        self.camp.path.mkdir(parents=True)
        (self.camp.path / cd.OUTCOMES).write_text(
            json.dumps({"name": "cmpR00_00", "reason": "ok"}) + "\n"
            + '{"name": "cmpR01_00", "rea')
        self.camp.append_outcome({"name": "cmpR02_00", "reason": "ok"})
        self.camp.append_outcome({"name": "cmpR03_00", "reason": "broken"})
        errors = []
        out = self.camp.outcomes(errors)
        self.assertEqual(sorted(out), ["cmpR00_00", "cmpR02_00", "cmpR03_00"])
        self.assertEqual(len(errors), 1)
        self.assertIn("outcomes.jsonl:2", errors[0])


class TestLiveness(_Camp):
    def test_alive_through_the_mcp_lock(self):
        import locks
        self.camp.path.mkdir(parents=True)
        with locks.hold(self.camp.path / cd.MCP_LOCK):
            self.assertTrue(self.camp.alive())
        self.assertFalse(self.camp.alive())

    def test_exit_code_from_rc(self):
        self.assertIsNone(self.camp.exit_code())
        self.camp.path.mkdir(parents=True)
        (self.camp.path / cd.RC).write_text("2\n")
        self.assertEqual(self.camp.exit_code(), 2)
        (self.camp.path / cd.RC).write_text("x\n")
        self.assertIsNone(self.camp.exit_code())

    def test_launched_by(self):
        self.assertIsNone(self.camp.launched_by())
        self.camp.write_launch({"prefix": "cmp", "pid": None})
        self.assertEqual(self.camp.launched_by(), "mcp")
        self.camp.update_launch(pid=42)
        self.assertEqual(self.camp.launch()["pid"], 42)

    def test_write_launch_is_exclusive(self):
        self.camp.write_launch({"prefix": "cmp"})
        with self.assertRaises(FileExistsError):
            self.camp.write_launch({"prefix": "cmp"})

    def test_stop(self):
        self.assertFalse(self.camp.stopping())
        path = self.camp.stop()
        self.assertEqual(path, self.camp.path / cd.STOP)
        self.assertTrue(self.camp.stopping())


if __name__ == "__main__":
    unittest.main()
