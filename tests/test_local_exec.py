"""Local executor tests: no grid contact anywhere. Every path is a tmpdir."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import local_exec  # noqa: E402


class TestLocalRoots(unittest.TestCase):
    def test_job_dir_mirrors_the_outstage_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                d = local_exec.job_dir("cfg001", 7, 3)
            self.assertEqual(
                d,
                Path(tmp) / "autoresearch_local" / "cfg001" / "7" / "00" / "00003")

    def test_next_runid_starts_at_one_then_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                self.assertEqual(local_exec.next_runid("cfg001"), 1)
                local_exec.job_dir("cfg001", 1, 0).mkdir(parents=True)
                self.assertEqual(local_exec.next_runid("cfg001"), 2)

    def test_list_outputs_local_writes_the_same_file_the_grid_path_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                for i in (0, 1):
                    d = local_exec.job_dir("cfg001", 1, i)
                    d.mkdir(parents=True)
                    (d / f"sim.x.TargetStops.{i}.art").write_text("x")
                    (d / "ignored.log").write_text("x")
                files = local_exec.list_outputs_local(
                    "mubeam", "cfg001", 1, "sim.*.TargetStops.*.art", state)
            self.assertEqual(len(files), 2)
            listed = (state / "mubeam_outputs.txt").read_text().split()
            self.assertEqual(len(listed), 2)
            self.assertTrue(all(p.endswith(".art") for p in listed))
            self.assertEqual(listed, sorted(listed))
