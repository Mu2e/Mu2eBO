"""Local executor tests: no grid contact anywhere. Every path is a tmpdir."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import local_exec  # noqa: E402
import pipeline  # noqa: E402


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


class TestScaleDials(unittest.TestCase):
    def test_none_gives_the_default(self):
        self.assertEqual(local_exec.resolve_scale(None, 1, "mubeam"), 1)

    def test_bare_value_applies_to_every_stage(self):
        self.assertEqual(local_exec.resolve_scale(["4"], 1, "mubeam"), 4)
        self.assertEqual(local_exec.resolve_scale(["4"], 1, "concat"), 4)

    def test_per_stage_override_wins_regardless_of_order(self):
        self.assertEqual(
            local_exec.resolve_scale(["1", "elebeam_flash=4"], 1,
                                     "elebeam_flash"), 4)
        self.assertEqual(
            local_exec.resolve_scale(["elebeam_flash=4", "1"], 1,
                                     "elebeam_flash"), 4)
        self.assertEqual(
            local_exec.resolve_scale(["1", "elebeam_flash=4"], 1, "mubeam"), 1)

    def test_a_malformed_entry_is_a_loud_error(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["notanumber"], 1, "mubeam")
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["mubeam=x"], 1, "mubeam")

    def test_whitespace_around_equals_is_stripped(self):
        self.assertEqual(
            local_exec.resolve_scale(["mubeam = 4"], 1, "mubeam"), 4)

    def test_empty_key_after_strip_raises(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["=4"], 1, "mubeam")

    def test_negative_bare_value_raises(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["-4"], 1, "mubeam")

    def test_zero_bare_value_raises(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["0"], 1, "mubeam")

    def test_negative_per_stage_value_raises(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["mubeam=-1"], 1, "mubeam")


class TestPipelineLocalWiring(unittest.TestCase):
    def test_events_stamp_carries_the_local_value_not_the_configured_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state):
                pipeline.stamp_local_events("mustops_ce", 200)
            self.assertEqual(
                (state / "mustops_ce_events_per_job.txt").read_text().strip(),
                "200")

    def test_concat_merge_factor_clamps_to_available_inputs(self):
        self.assertEqual(pipeline.clamp_merge_factor(200, 1), 1)
        self.assertEqual(pipeline.clamp_merge_factor(200, 350), 200)
        self.assertEqual(pipeline.clamp_merge_factor(200, 200), 200)

    def test_local_build_never_invokes_grid_tools(self):
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return mock.Mock(returncode=0, stdout="# fcl\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.subprocess, "run", fake_run):
                pipeline.cmd_local_build(SimpleNamespace(
                    stage="mubeam", local_njobs=["2"], local_events=["200"]))

            # The stamp must be WIRED, not merely implemented: harvest scales
            # every metric by this file, so a cmd_local_build that forgets to
            # call stamp_local_events leaves the configured value in place and
            # biases every local metric by the ratio.
            self.assertEqual(
                (state / "mubeam_events_per_job.txt").read_text().strip(),
                "200")

        flat = [tok for cmd in seen for tok in cmd]
        self.assertNotIn("mu2ejobsub", flat)
        self.assertNotIn("jobsub_q", flat)
        self.assertIn("mu2ejobfcl", flat)

    def test_submit_stage_still_stamps_the_configured_events_per_job(self):
        # The grid stamp had to survive the _jobdef_cmd extraction, and nothing
        # else in the suite covers it: test_pipeline_verbs mocks submit_stage
        # wholesale. dry_run stops before mu2ejobsub, so no grid contact.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline, "_probe_input_urls"), \
                 mock.patch.object(pipeline.subprocess, "run",
                                   return_value=mock.Mock(returncode=0,
                                                          stdout="# fcl\n",
                                                          stderr="")):
                pipeline.submit_stage("mubeam", {}, dry_run=True)
            self.assertEqual(
                (state / "mubeam_events_per_job.txt").read_text().strip(),
                str(pipeline.STAGES["mubeam"]["events_per_job"]))

    def test_local_jobdef_matches_the_grid_jobdef_except_events_per_job(self):
        # The whole point of extracting _jobdef_cmd: local and grid build the
        # SAME cnf. If these ever diverge, a local run stops predicting
        # anything about the grid run it is supposed to stand in for.
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "t.fcl"
            t.write_text("x")
            with mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_grid_setup_sh",
                                   return_value="/setup.sh"):
                grid = pipeline._jobdef_cmd("mubeam", t, "dsc", "dsc-desc",
                                            Path(tmp))
                local = pipeline._jobdef_cmd("mubeam", t, "dsc", "dsc-desc",
                                             Path(tmp), events_per_job=200)
        self.assertEqual(len(grid), len(local))
        i = local.index("--events-per-job")
        self.assertEqual(local[i + 1], "200")
        self.assertEqual(
            grid[i + 1], str(pipeline.STAGES["mubeam"]["events_per_job"]))
        # Everything OTHER than the events value is byte-identical.
        self.assertEqual(grid[:i + 1] + grid[i + 2:],
                         local[:i + 1] + local[i + 2:])

    def test_local_build_refuses_a_stage_it_cannot_stage_inputs_for(self):
        # Better a loud refusal than a cnf with no --inputs: mu2ejobdef would
        # accept that, and the job would then read nothing and report success.
        for stage in ("concat", "mustops_ce"):
            with self.subTest(stage=stage), self.assertRaises(SystemExit):
                pipeline.cmd_local_build(SimpleNamespace(
                    stage=stage, local_njobs=None, local_events=None))

    def test_poll_is_a_noop_in_local_mode(self):
        # run_jobs_local is synchronous, so by the time poll could run every
        # job is done. Without this guard a graph-driven chain would feed the
        # runid in <stage>_cluster.txt to jobsub_q as if it were a cluster id.
        with mock.patch.dict(os.environ, {"AUTORESEARCH_LOCAL": "1"}), \
             mock.patch.object(pipeline, "poll_cluster") as pc:
            pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                              cap_hours=24.0))
        pc.assert_not_called()

    def test_local_run_refuses_the_same_stages_local_build_does(self):
        # local-run writes state/<stage>_cluster.txt. A runid parked in
        # concat_cluster.txt trips cmd_submit's idempotency guard, so a stray
        # `local-run concat` would silently suppress a REAL grid submit.
        for stage in ("concat", "mustops_ce"):
            with self.subTest(stage=stage), self.assertRaises(SystemExit):
                pipeline.cmd_local_run(SimpleNamespace(
                    stage=stage, local_njobs=None, local_events=None,
                    local_pool=None))

    def test_poll_is_a_noop_on_the_marker_alone_without_the_env_var(self):
        # `submit --local` is a flag, not an env var, so a later poll runs in a
        # process where AUTORESEARCH_LOCAL is unset. The marker must carry it,
        # or the runid goes to jobsub_q as a ClusterId.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("1\n")
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.dict(os.environ), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "poll_cluster") as pc:
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                                  cap_hours=24.0))
        pc.assert_not_called()

    def test_list_outputs_never_reaches_the_grid_lister_in_local_mode(self):
        # Without the marker check this is safe only by accident (the
        # idempotency guard happens to match the local paths local-run wrote).
        # A local run with ZERO outputs empties that guard and would fall
        # through to a /pnfs glob for a runid-shaped cluster.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("1\n")
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.dict(os.environ), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "list_outputs") as lo:
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                d = local_exec.job_dir("cfg001", 1, 0)
                d.mkdir(parents=True)
                (d / "sim.x.TargetStops.0.art").write_text("x")
                pipeline.cmd_list_outputs(SimpleNamespace(stage="mubeam",
                                                          force=False))
                # ... and again with the local tree EMPTY, the corner the
                # idempotency guard cannot cover.
                (d / "sim.x.TargetStops.0.art").unlink()
                pipeline.cmd_list_outputs(SimpleNamespace(stage="mubeam",
                                                          force=False))
            lo.assert_not_called()
            self.assertEqual(
                (state / "mubeam_outputs.txt").read_text().strip(), "")
