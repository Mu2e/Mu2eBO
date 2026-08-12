"""Local executor tests: no grid contact anywhere. Every path is a tmpdir."""
import os
import subprocess
import sys
import tempfile
import threading
import time
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


class TestFclProvenance(unittest.TestCase):
    def _build(self, tmp, n=2):
        state = Path(tmp) / "state"
        state.mkdir(parents=True, exist_ok=True)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            idx = cmd[cmd.index("--index") + 1]
            return mock.Mock(returncode=0, stdout=f"# fcl for job {idx}\n",
                             stderr="")

        with mock.patch.object(local_exec.subprocess, "run", fake_run):
            paths = local_exec.build_fcls(
                "mubeam", "cnf.tar", Path(tmp), state, n, "tape", {})
        return state, paths, calls

    def test_build_writes_one_fcl_per_index_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, calls = self._build(tmp, n=2)
            self.assertEqual(len(paths), 2)
            self.assertTrue((state / "fcl" / "mubeam_00000.fcl").exists())
            self.assertTrue((state / "fcl" / "mubeam_00001.fcl").exists())
            self.assertEqual(len(calls), 2)
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"), [])

    def test_hand_edit_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, _ = self._build(tmp, n=2)
            paths[1].write_text("# I changed this by hand\n")
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"),
                             ["mubeam_00001.fcl"])

    def test_a_missing_hash_record_counts_as_edited(self):
        # Deleting the sidecar must not silently read as "unmodified".
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, _ = self._build(tmp, n=1)
            (state / "fcl" / "mubeam_00000.fcl.sha256").unlink()
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"),
                             ["mubeam_00000.fcl"])


class TestLocalExecution(unittest.TestCase):
    def test_runs_one_mu2e_per_job_in_its_own_dir_and_never_calls_grid_tools(self):
        seen = []

        def fake_run(cmd, **kw):
            seen.append((cmd, kw.get("cwd")))
            Path(kw["cwd"], "sim.x.TargetStops.0.art").write_text("x")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(3):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 3, 200, {}, pool=2)

        self.assertEqual(res["ok"], 3)
        self.assertEqual(res["failed"], [])
        self.assertEqual(len(seen), 3)
        for cmd, cwd in seen:
            self.assertEqual(cmd[0], "mu2e")
            self.assertIn("-n", cmd)
            self.assertEqual(cmd[cmd.index("-n") + 1], "200")
            self.assertTrue(cwd.endswith(("00000", "00001", "00002")))
        # The point of the whole design: no grid tooling, ever.
        flat = [tok for cmd, _ in seen for tok in cmd]
        self.assertNotIn("mu2ejobsub", flat)
        self.assertNotIn("jobsub_q", flat)

    def test_a_failing_job_is_reported_not_raised(self):
        def fake_run(cmd, **kw):
            idx = int(Path(kw["cwd"]).name)
            return mock.Mock(returncode=0 if idx == 0 else 1,
                             stdout="", stderr="boom")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(2):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 2, 200, {}, pool=2)

        self.assertEqual(res["ok"], 1)
        self.assertEqual(res["failed"], [1])

    def test_a_subprocess_raise_is_reported_not_raised(self):
        def fake_run(cmd, **kw):
            idx = int(Path(kw["cwd"]).name)
            if idx == 1:
                raise FileNotFoundError("mu2e: not found")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(2):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 2, 200, {}, pool=2)

        self.assertEqual(res["ok"], 1)
        self.assertEqual(res["failed"], [1])

    def test_pool_bounds_concurrency(self):
        running = 0
        max_running = 0
        lock = threading.Lock()

        def fake_run(cmd, **kw):
            nonlocal running, max_running
            with lock:
                running += 1
                max_running = max(max_running, running)
            time.sleep(0.01)
            with lock:
                running -= 1
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(6):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 6, 200, {}, pool=2)

        self.assertEqual(res["ok"], 6)
        self.assertLessEqual(max_running, 2)
        self.assertGreater(max_running, 1)
