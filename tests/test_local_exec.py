"""Local executor tests: no grid contact anywhere. Every path is a tmpdir."""
import contextlib
import errno
import io
import json
import math
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

    def test_a_failing_mu2ejobfcl_surfaces_its_stderr(self):
        # check=True raises with stderr CAPTURED and str(exc) omits it, so
        # without this handling an rc!=0 is completely opaque -- the shape of
        # jobsub-disk-quota-stderr-swallowed and sourced-env-stderr-swallowed.
        def fake_run(cmd, **kw):
            raise subprocess.CalledProcessError(
                1, cmd, output="partial stdout",
                stderr="mu2ejobfcl: no such jobdef cnf.tar")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            err = io.StringIO()
            with mock.patch.object(local_exec.subprocess, "run", fake_run), \
                 contextlib.redirect_stderr(err), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(subprocess.CalledProcessError):
                    local_exec.build_fcls("mubeam", "cnf.tar", Path(tmp),
                                          state, 1, "tape", {})
        self.assertIn("no such jobdef", err.getvalue())
        self.assertIn("partial stdout", out.getvalue())

    def test_a_smaller_rebuild_prunes_the_larger_previous_set(self):
        # Build 4, then build 1: indices 1-3 must not survive. edited_fcls
        # globs ALL <stage>_*.fcl, so a survivor with a matching sidecar is
        # merely noise, but one whose sidecar was clobbered reads as
        # "hand-edited" for a job that never ran.
        with tempfile.TemporaryDirectory() as tmp:
            state, _, _ = self._build(tmp, n=4)
            self.assertTrue((state / "fcl" / "mubeam_00003.fcl").exists())
            self._build(tmp, n=1)
            fcls = sorted(p.name for p in (state / "fcl").glob("mubeam_*.fcl"))
            self.assertEqual(fcls, ["mubeam_00000.fcl"])
            self.assertEqual(
                sorted(p.name for p in
                       (state / "fcl").glob("mubeam_*.fcl.sha256")),
                ["mubeam_00000.fcl.sha256"])
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"), [])

    def test_pruning_leaves_another_stages_fcls_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            other = local_exec.fcl_path(state, "elebeam_flash", 0)
            other.write_text("keep me")
            self._build(tmp, n=1)
            self.assertTrue(other.exists())

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
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
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

    def test_local_build_rebuilds_an_existing_cnf_instead_of_reusing_it(self):
        # submit_stage unlinks and rebuilds unconditionally; so must this. The
        # cnf on disk is as likely as not one a GRID submit built at the
        # configured 5000 events/job, and reusing it silently discards
        # --local-events and every template edit -- while local-build still
        # prints that it built something.
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return mock.Mock(returncode=0, stdout="# fcl\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (Path(tmp) / "mubeam").mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.subprocess, "run", fake_run):
                # Built INSIDE the patch: _stage_desc formats with CONFIG, so
                # the name only matches the one cmd_local_build computes if
                # CONFIG is already bound here.
                cnf = (Path(tmp) / "mubeam" /
                       f"cnf.{pipeline.USER}.{pipeline._stage_desc('mubeam')}."
                       f"{pipeline._stage_dsconf('mubeam')}.0.tar")
                cnf.write_text("a stale cnf built at 5000 events/job")
                pipeline.cmd_local_build(SimpleNamespace(
                    stage="mubeam", local_njobs=["1"], local_events=["200"]))
                self.assertFalse(cnf.exists(),
                                 "the stale cnf survived local-build")
        jobdefs = [c for c in seen if c and c[0] == "mu2ejobdef"]
        self.assertEqual(len(jobdefs), 1)
        self.assertEqual(
            jobdefs[0][jobdefs[0].index("--events-per-job") + 1], "200")

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

    def test_the_env_var_alone_does_not_make_poll_skip_a_live_grid_cluster(self):
        # AUTORESEARCH_LOCAL is an ACTIVATION switch (cmd_submit reads it to
        # choose local mode), never a DETECTION signal. An operator who
        # exported it for a study and then launched a campaign from the same
        # shell must still get a real poll: with the env var in
        # _is_local_stage, this poll silently no-ops on a LIVE cluster and the
        # chain marches on to harvest jobs that have not finished.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("70314159\n")  # a real one
            # ... and NO mubeam_local.txt.

            def fake_run_jobwait(stage_dir, cnf, jobid, njobs, wait_json,
                                 env, **kw):
                Path(wait_json).write_text('{"ok": 999999, "failed": 0, '
                                           '"unknown": [], "jobs": []}')
                return 0

            with mock.patch.dict(os.environ, {"AUTORESEARCH_LOCAL": "1"}), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "_check_stage_config_sha"), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline.px, "run_jobwait",
                                   side_effect=fake_run_jobwait) as pc:
                pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                                  cap_hours=24.0))
        pc.assert_called_once()
        # jobid arg (position 2) falls back to <stage>_cluster.txt when no
        # <stage>_jobsub_id.txt exists.
        self.assertEqual(pc.call_args[0][2], "70314159")

    @contextlib.contextmanager
    def _local_run_env(self, tmp):
        """Drive the REAL cmd_local_run with only subprocess mocked out.

        Everything else -- marker write, cluster write, run pool, events
        stamp, output listing -- is the shipping code path.

        _maybe_refresh_token is stubbed because it stats the MACHINE's real
        bearer-token file and, when that is older than TOKEN_REFRESH_AGE_S,
        shells out to getToken. That made these four tests pass or fail on
        how recently the operator had submitted anything -- the suite is
        green on a fresh token and errors on a stale one.
        """
        state = Path(tmp) / "state"
        (state / "fcl").mkdir(parents=True)

        def fake_run(cmd, **kw):
            Path(kw["cwd"], "sim.x.TargetStops.0.art").write_text("x")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.dict(os.environ), \
             mock.patch.object(pipeline, "STATE", state), \
             mock.patch.object(pipeline, "CONFIG", "cfg001"), \
             mock.patch.object(pipeline, "sourced_env", return_value={}), \
             mock.patch.object(pipeline, "_maybe_refresh_token"), \
             mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
             mock.patch.object(local_exec.subprocess, "run", fake_run):
            os.environ.pop("AUTORESEARCH_LOCAL", None)
            yield state

    def test_local_run_writes_the_marker_BEFORE_the_cluster_file(self):
        # The ordering invariant, asserted on the WRITE half -- until now only
        # the clearing half was pinned, so the two lines could be swapped with
        # the whole suite still green. If the process dies between them, the
        # residue must be a marker with no cluster file (poll no-ops;
        # harmless), never a runid that nothing distinguishes from a real
        # ClusterId (poll hands it to jobsub_q and waits out the 24h cap on a
        # /pnfs dir that will never appear).
        order = []
        real_write_text = Path.write_text

        def spy(self, data, *a, **kw):
            order.append(self.name)
            return real_write_text(self, data, *a, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            with self._local_run_env(tmp) as state, \
                 mock.patch.object(Path, "write_text", spy):
                pipeline.cmd_local_run(SimpleNamespace(
                    stage="mubeam", local_njobs=["1"], local_events=["200"],
                    local_pool=1))

            marker = state / "mubeam_local.txt"
            cluster = state / "mubeam_cluster.txt"
            self.assertTrue(marker.exists(), "no marker: poll would jobsub_q "
                                             "the runid as a ClusterId")
            self.assertTrue(cluster.exists())
            self.assertEqual(marker.read_text().strip(),
                             cluster.read_text().strip())
            # ... and the whole point of the invariant: which came first.
            self.assertIn("mubeam_local.txt", order)
            self.assertIn("mubeam_cluster.txt", order)
            self.assertLess(order.index("mubeam_local.txt"),
                            order.index("mubeam_cluster.txt"),
                            "the runid was written before its marker")

    def test_local_run_stamps_the_local_events_and_lists_the_local_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._local_run_env(tmp) as state:
                pipeline.cmd_local_run(SimpleNamespace(
                    stage="mubeam", local_njobs=["2"], local_events=["200"],
                    local_pool=1))
            self.assertEqual(
                (state / "mubeam_events_per_job.txt").read_text().strip(),
                "200")
            listed = [p for p in
                      (state / "mubeam_outputs.txt").read_text().splitlines()
                      if p.strip()]
            self.assertEqual(len(listed), 2)
            runid = (state / "mubeam_cluster.txt").read_text().strip()
            for p in listed:
                self.assertIn(f"/autoresearch_local/cfg001/{runid}/00/", p)

    def test_local_run_warns_about_a_hand_edited_fcl(self):
        # Spec test 5, at the verb rather than the edited_fcls unit: the
        # warning is the feature's headline, and nothing asserted that
        # cmd_local_run actually prints it.
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with self._local_run_env(tmp) as state:
                f = local_exec.fcl_path(state, "mubeam", 0)
                f.write_text("# resolved by mu2ejobfcl\n")
                f.with_suffix(".fcl.sha256").write_text("0" * 64)  # stale hash
                with contextlib.redirect_stdout(out):
                    pipeline.cmd_local_run(SimpleNamespace(
                        stage="mubeam", local_njobs=["1"],
                        local_events=["200"], local_pool=1))
        self.assertIn("FCL hand-edited: mubeam_00000.fcl", out.getvalue())

    def test_local_run_is_silent_about_an_untouched_fcl(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with self._local_run_env(tmp) as state:
                f = local_exec.fcl_path(state, "mubeam", 0)
                f.write_text("# resolved by mu2ejobfcl\n")
                f.with_suffix(".fcl.sha256").write_text(
                    local_exec._sha256(f.read_text()))
                with contextlib.redirect_stdout(out):
                    pipeline.cmd_local_run(SimpleNamespace(
                        stage="mubeam", local_njobs=["1"],
                        local_events=["200"], local_pool=1))
        self.assertNotIn("hand-edited", out.getvalue())

    def test_both_verbs_refuse_a_stage_the_local_executor_does_not_support(self):
        # Every stage in STAGES is supported today, so pin the GATE rather
        # than a particular stage -- a stage added to STAGES later must be
        # opted in deliberately, not inherited. This matters because
        # local-run writes state/<stage>_cluster.txt: a runid parked there
        # trips cmd_submit's idempotency guard and silently suppresses a REAL
        # grid submit of that stage.
        for verb in (pipeline.cmd_local_build, pipeline.cmd_local_run):
            with self.subTest(verb=verb.__name__), \
                 mock.patch.object(pipeline, "LOCAL_SUPPORTED_STAGES",
                                   ("mubeam",)), \
                 self.assertRaises(SystemExit):
                verb(SimpleNamespace(stage="concat", local_njobs=None,
                                     local_events=None, local_pool=None))

    def test_the_local_verbs_refuse_when_no_config_is_bound(self):
        # STATE's unbound default is Path() -- the CURRENT DIRECTORY. Reaching
        # these verbs without _bind_config scatters <stage>_cluster.txt,
        # _local.txt, _outputs.txt and a materialized template into cwd, which
        # is how they first landed in the repo root.
        for verb in (pipeline.cmd_local_build, pipeline.cmd_local_run):
            with self.subTest(verb=verb.__name__), \
                 mock.patch.object(pipeline, "CONFIG", ""), \
                 self.assertRaises(SystemExit) as cm:
                verb(SimpleNamespace(stage="mubeam", local_njobs=None,
                                     local_events=None, local_pool=None))
            self.assertIn("no config bound", str(cm.exception))

    def test_a_consuming_stage_refuses_when_its_input_stage_never_ran_local(self):
        # concat's inputs must come from a LOCAL mubeam run. Without the
        # marker, mubeam_outputs.txt holds /pnfs paths, and building against
        # those is a grid chain wearing a local hat.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 self.assertRaises(SystemExit) as cm:
                pipeline._local_stage_inputs("concat")
            self.assertIn("no local run", str(cm.exception))

    def test_concat_merge_factor_clamps_to_the_local_input_count(self):
        # mu2ejobdef emits ZERO jobs when the merge factor exceeds the input
        # count, and a zero-job cnf is not an error -- local-run would report
        # "0 ok, 0 failed", indistinguishable from a stage that found nothing.
        self.assertEqual(local_exec.clamp_merge_factor(200, 1), 1)
        self.assertEqual(local_exec.clamp_merge_factor(200, 350), 200)
        self.assertEqual(local_exec.clamp_merge_factor(200, 0), 1)

    def test_local_farm_collects_spread_outputs_into_one_dir(self):
        # --inputs takes basenames only and --default-loc dir:DIR assumes they
        # all live in DIR, but a local stage's outputs are spread one dir per
        # job index. Same constraint the /pnfs hardlink farm exists for.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            srcs = []
            for i in (0, 1):
                d = Path(tmp) / f"0000{i}"
                d.mkdir()
                f = d / f"sim.x.TargetStops.{i}.art"
                f.write_text("x")
                srcs.append(f)
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                staged, basenames = local_exec.local_farm(
                    "concat", "cfg001", srcs, state)
            self.assertEqual(sorted(p.name for p in staged.iterdir()),
                             ["sim.x.TargetStops.0.art",
                              "sim.x.TargetStops.1.art"])
            self.assertEqual(basenames.read_text().split(),
                             ["sim.x.TargetStops.0.art",
                              "sim.x.TargetStops.1.art"])
            # "staged" must not read as a run id
            self.assertEqual(local_exec.next_runid("cfg001"), 1)

    def test_sourced_env_drops_truncated_exported_shell_functions(self):
        # `env` prints an exported bash function across multiple lines, so a
        # line-based parser captures a body with no closing brace. Passing
        # that to a child yields "syntax error: unexpected end of file" ~10x
        # per shell spawn -- hundreds of lines per job log, which is what hid
        # the two real failures the first local smoke run turned up.
        out = ("PATH=/usr/bin\n"
               "BASH_FUNC_muse%%=() {  source ${MUSE_DIR}/bin/muse\n"
               "}\n"
               "MU2E_SEARCH_PATH=/cvmfs/x\n")
        with mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout=out, stderr="")):
            env = pipeline.sourced_env()
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["MU2E_SEARCH_PATH"], "/cvmfs/x")
        self.assertEqual([k for k in env if k.startswith("BASH_FUNC_")], [])

    def test_local_job_env_puts_the_geom_dir_on_the_search_path(self):
        # The FCL names the geom by basename; it resolves only via
        # MU2E_SEARCH_PATH. On the grid Code/setup_post.sh extends that path
        # when the worker unpacks Code.tar.bz2 -- nothing unpacks it locally.
        # Without this the job dies "Can't find file ..._geom.txt" after
        # producing zero events. Found by the first real local run, not a mock.
        with tempfile.TemporaryDirectory() as tmp:
            geom = Path(tmp) / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("x")
            with mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={"MU2E_SEARCH_PATH": "/pre"}):
                env = pipeline.local_job_env()
            self.assertEqual(env["MU2E_SEARCH_PATH"], f"{geom.parent}:/pre")
            self.assertEqual(env["FHICL_FILE_PATH"], str(geom.parent))

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
                 mock.patch.object(pipeline.px, "run_jobwait") as pc:
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                                  cap_hours=24.0))
        pc.assert_not_called()

    def test_a_forced_grid_submit_clears_the_local_runid_not_just_its_marker(self):
        # submit_stage_prodtools rewrites <stage>_cluster.txt only AFTER
        # submit_cnf parses a cluster id, so every grid path that never gets
        # there must not leave the local runid behind unmarked -- a later
        # poll would hand that small int to jobsub_q and wait out the 24h
        # cap. --dry-run is the cheapest such path (it still builds the cnf
        # but returns before submit_cnf); a raise anywhere before the submit
        # has the same shape. Asserted on the CLUSTER FILE, not the marker:
        # a test that checks only the marker passes against the bug this
        # pins.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("3\n")     # as local-run
            (state / "mubeam_cluster.txt").write_text("3\n")   # ... a runid
            with mock.patch.dict(os.environ), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" / "cnf.x.tar"):
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=True, dry_run=True, local=False))
            self.assertFalse(
                (state / "mubeam_cluster.txt").exists(),
                "the local runid survived a forced grid submit that never "
                "reached submit_cnf -- poll would send it to jobsub_q")
            self.assertFalse((state / "mubeam_local.txt").exists())

    def test_an_unforced_grid_submit_after_a_local_run_really_submits(self):
        # The un-forced path is the one a graph child takes. cmd_submit's
        # idempotency guard cannot tell a runid from a ClusterId, so with the
        # marker-clear placed after it a plain `submit mubeam` following any
        # local run printed "already submitted (cluster=1)" and did NOTHING --
        # the exact residue the marker was introduced to prevent, surviving in
        # the one verb that owns the marker. --force is not the fix; it is the
        # workaround nobody types.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")     # as local-run
            (state / "mubeam_cluster.txt").write_text("1\n")   # ... a runid
            with mock.patch.dict(os.environ), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "submit_stage_prodtools") as ss:
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=False))
            ss.assert_called_once()
            self.assertFalse((state / "mubeam_local.txt").exists())

    def test_a_local_submit_does_not_clear_its_own_marker(self):
        # The clear is gated on "this is a GRID submit". A `submit --local`
        # re-entry must leave the marker alone, or the window between the
        # clear and the runlocal branch's rewrite is a runid-shaped cluster
        # file with no marker -- the state the invariant forbids.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            (state / "mubeam_cluster.txt").write_text("1\n")
            with mock.patch.dict(os.environ), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   return_value=0), \
                 mock.patch.object(pipeline, "submit_stage_prodtools") as ss:
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=True, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))
            ss.assert_not_called()
            self.assertTrue((state / "mubeam_local.txt").exists())


class TestCmdSubmitLocalViaRunlocal(unittest.TestCase):
    """`submit --local` on a non-consuming stage: same prodtools render/build
    sequence the grid path uses, but at LOCAL njobs/events, executed here via
    prodtools runlocal instead of submitted to the grid. Zero grid contact:
    px.build_cnf and px.run_runlocal are mocked (real invocation is
    prodtools_exec's own responsibility, covered in test_prodtools_exec.py).
    """

    def _patches(self, tmp, *, build_cnf=None, run_runlocal=None):
        cnf = build_cnf or (Path(tmp) / "mubeam" / "cnf.x.tar")
        return [
            mock.patch.object(pipeline, "ROOT", Path(tmp)),
            mock.patch.object(pipeline, "CONFIG", "cfg001"),
            mock.patch.object(pipeline, "sourced_env",
                              return_value={"X": "1"}),
            mock.patch.object(pipeline, "_maybe_refresh_token"),
            mock.patch.object(pipeline, "write_code_tarball",
                              return_value=Path(tmp) / "Code.tar.bz2"),
            mock.patch.object(pipeline, "_materialize_template",
                              return_value=Path(tmp) / "t.fcl"),
            mock.patch.object(pipeline.px, "build_cnf", return_value=cnf),
            mock.patch.object(pipeline.px, "run_runlocal",
                              return_value=(run_runlocal
                                           if run_runlocal is not None
                                           else 0)),
        ]

    def test_a_consuming_stage_refuses_when_its_input_stage_never_ran_local(self):
        # concat/mustops_ce need the PREVIOUS stage's local marker -- the same
        # refusal _local_stage_inputs made for the old mu2ejobdef-based local
        # executor. Without it, <prev>_outputs.txt holds /pnfs paths, and
        # farming those locally is a grid chain wearing a local hat.
        for stage, prev in (("concat", "mubeam"), ("mustops_ce", "mubeam")):
            with self.subTest(stage=stage), \
                 tempfile.TemporaryDirectory() as tmp, \
                 mock.patch.object(pipeline, "STATE", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 self.assertRaises(SystemExit) as cm:
                pipeline.cmd_submit(SimpleNamespace(
                    stage=stage, force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))
            self.assertIn("no local run", str(cm.exception))
            self.assertIn(prev, str(cm.exception))

    def test_mustops_ce_refuses_when_prev_outputs_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 self.assertRaises(SystemExit) as cm:
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mustops_ce", force=False, dry_run=False,
                    local=True, local_njobs=None, local_events=None,
                    local_pool=None))
            self.assertIn("mubeam_outputs.txt", str(cm.exception))

    def test_mustops_ce_refuses_when_prev_outputs_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            (state / "mubeam_outputs.txt").write_text("")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 self.assertRaises(SystemExit) as cm:
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mustops_ce", force=False, dry_run=False,
                    local=True, local_njobs=None, local_events=None,
                    local_pool=None))
            self.assertIn("empty", str(cm.exception))

    def _consuming_stage_patches(self, tmp):
        return [
            mock.patch.object(pipeline, "ROOT", Path(tmp)),
            mock.patch.object(pipeline, "CONFIG", "cfg001"),
            mock.patch.object(pipeline, "sourced_env",
                              return_value={"X": "1"}),
            mock.patch.object(pipeline, "_maybe_refresh_token"),
            mock.patch.object(pipeline, "write_code_tarball",
                              return_value=Path(tmp) / "Code.tar.bz2"),
            mock.patch.object(pipeline, "_materialize_template",
                              return_value=Path(tmp) / "t.fcl"),
            mock.patch.object(pipeline.px, "build_cnf",
                              return_value=Path(tmp) / "x" / "cnf.x.tar"),
            mock.patch.object(pipeline.px, "run_runlocal", return_value=0),
        ]

    def test_concat_stages_a_local_farm_and_scales_njobs_to_source_count(self):
        # merge_factor patched small so 5 local sources yield njobs > 1 --
        # otherwise the default merge_factor (200) always clamps to
        # njobs=ceil(n/n)=1 and the scaling behavior is untestable.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            src_dir = Path(tmp) / "mubeam_out"
            src_dir.mkdir()
            sources = []
            for i in range(5):
                f = src_dir / f"sim.x.TargetStops.{i}.art"
                f.write_text("x")
                sources.append(f)
            (state / "mubeam_outputs.txt").write_text(
                "\n".join(str(s) for s in sources) + "\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.dict(pipeline.STAGES["concat"],
                                 {"merge_factor": 2}), \
                 contextlib.ExitStack() as stack:
                for p in self._consuming_stage_patches(tmp):
                    stack.enter_context(p)
                rr = stack.enter_context(
                    mock.patch.object(pipeline.px, "run_runlocal",
                                      return_value=0))
                pipeline.cmd_submit(SimpleNamespace(
                    stage="concat", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))

            entry = json.loads((state / "concat_entry.json").read_text())[0]
            merge = min(2, 5)  # clamped merge factor
            self.assertEqual(entry["input_data"],
                             {s.name: merge for s in sources})
            farm_dir = Path(tmp) / "concat" / "local_inputs"
            self.assertEqual(entry["inloc"], f"dir:{farm_dir}")
            self.assertEqual(sorted(p.name for p in farm_dir.iterdir()),
                             sorted(s.name for s in sources))
            self.assertEqual(entry["njobs"], math.ceil(5 / merge))
            call_args, _ = rr.call_args
            self.assertEqual(call_args[2], math.ceil(5 / merge))

    def test_concat_local_njobs_flag_overrides_the_computed_default(self):
        # Operator wins: an explicit --local-njobs beats the
        # ceil(len(sources)/merge) default this task adds.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            src_dir = Path(tmp) / "mubeam_out"
            src_dir.mkdir()
            sources = []
            for i in range(5):
                f = src_dir / f"sim.x.TargetStops.{i}.art"
                f.write_text("x")
                sources.append(f)
            (state / "mubeam_outputs.txt").write_text(
                "\n".join(str(s) for s in sources) + "\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.dict(pipeline.STAGES["concat"],
                                 {"merge_factor": 2}), \
                 contextlib.ExitStack() as stack:
                for p in self._consuming_stage_patches(tmp):
                    stack.enter_context(p)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="concat", force=False, dry_run=False, local=True,
                    local_njobs=["9"], local_events=None, local_pool=None))

            entry = json.loads((state / "concat_entry.json").read_text())[0]
            self.assertEqual(entry["njobs"], 9)

    def test_mustops_ce_stages_a_local_farm_with_merge_one_and_default_njobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            src_dir = Path(tmp) / "mubeam_out"
            src_dir.mkdir()
            sources = []
            for i in range(3):
                f = src_dir / f"sim.x.TargetStops.{i}.art"
                f.write_text("x")
                sources.append(f)
            (state / "mubeam_outputs.txt").write_text(
                "\n".join(str(s) for s in sources) + "\n")
            # No stage-chain stamp exists (the local branch never writes
            # one), so mustops_ce's prev-stage resolution falls back to the
            # module-level CONCATLESS constant -- force it True (mubeam) so
            # this test doesn't depend on which mode was live at import.
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 contextlib.ExitStack() as stack:
                for p in self._consuming_stage_patches(tmp):
                    stack.enter_context(p)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mustops_ce", force=False, dry_run=False,
                    local=True, local_njobs=None, local_events=None,
                    local_pool=None))

            entry = json.loads((state / "mustops_ce_entry.json").read_text())[0]
            self.assertEqual(entry["input_data"], {s.name: 1 for s in sources})
            farm_dir = Path(tmp) / "mustops_ce" / "local_inputs"
            self.assertEqual(entry["inloc"], f"dir:{farm_dir}")
            # njobs stays at the plain local-scale default (1) -- resolution
            # #3 keeps mustops_ce's local njobs as-is, unlike concat's
            # source-count scaling.
            self.assertEqual(entry["njobs"], 1)

    def test_renders_and_stamps_with_the_local_scale_not_the_grid_cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            patches = self._patches(tmp)
            with mock.patch.object(pipeline, "STATE", state), \
                 contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=["3"], local_events=["77"],
                    local_pool=None))

            # render_entry got the LOCAL njobs/events, not STAGES["mubeam"]'s
            # grid-scale 200 x 5000.
            entry = json.loads(
                (state / "mubeam_entry.json").read_text())[0]
            self.assertEqual(entry["njobs"], 3)
            self.assertEqual(entry["events"], 77)
            self.assertNotEqual(entry["njobs"],
                                pipeline.STAGES["mubeam"]["njobs"])

            # harvest's stamp carries the LOCAL events value.
            self.assertEqual(
                (state / "mubeam_events_per_job.txt").read_text().strip(),
                "77")

    def test_writes_marker_before_cluster_txt_with_the_literal_runid(self):
        order = []
        real_write_text = Path.write_text

        def spy(self, data, *a, **kw):
            order.append(self.name)
            return real_write_text(self, data, *a, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            patches = self._patches(tmp)
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(Path, "write_text", spy), \
                 contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))

            marker = state / "mubeam_local.txt"
            cluster = state / "mubeam_cluster.txt"
            self.assertTrue(marker.exists())
            self.assertTrue(cluster.exists())
            self.assertEqual(cluster.read_text().strip(), "1")
            self.assertEqual(marker.read_text().strip(), "1")
            self.assertIn("mubeam_local.txt", order)
            self.assertIn("mubeam_cluster.txt", order)
            self.assertLess(order.index("mubeam_local.txt"),
                            order.index("mubeam_cluster.txt"),
                            "the runid was written before its marker")

    def test_run_runlocal_gets_the_built_cnf_local_njobs_and_shared_wait_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            cnf = Path(tmp) / "mubeam" / "cnf.x.tar"
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={"X": "1"}), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=cnf), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   return_value=0) as rr:
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=["3"], local_events=["77"],
                    local_pool=None))
            call_args, call_kwargs = rr.call_args
        self.assertEqual(call_args[0], Path(tmp) / "mubeam")   # stage_dir
        self.assertEqual(call_args[1], cnf)
        self.assertEqual(call_args[2], 3)                      # LOCAL njobs
        # the SAME wait.json path the grid path (jobwait) writes -- what
        # makes cmd_list_outputs executor-blind.
        self.assertEqual(call_args[3],
                         pipeline.px.wait_json_path(state, "mubeam"))
        self.assertEqual(call_kwargs["code_tarball"],
                         Path(tmp) / "Code.tar.bz2")
        self.assertEqual(call_kwargs["pool"], 4)  # DEFAULT_POOL, unset flag

    def test_local_pool_flag_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={"X": "1"}), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   return_value=0) as rr:
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=2))
            _, call_kwargs = rr.call_args
        self.assertEqual(call_kwargs["pool"], 2)


class TestLocalInputFarm(unittest.TestCase):
    """pipeline.local_input_farm: the local analogue of stage_hardlink_farm
    (kept verbatim for the grid). Flat farm at ROOT/<stage>/local_inputs,
    hard-linking a prior local stage's spread-out outputs into one dir so
    inloc: dir:<farm> can see them."""

    def test_links_n_files_flat_and_returns_the_basenames_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            sources = []
            for i in range(3):
                f = src_dir / f"sim.x.MuminusStopsCat.{i}.art"
                f.write_text("x")
                sources.append(f)
            with mock.patch.object(pipeline, "ROOT", Path(tmp) / "root"), \
                 mock.patch.dict(pipeline.STAGES,
                                 {"concat": {"merge_factor": 200}},
                                 clear=True):
                farm_dir, input_map = pipeline.local_input_farm(
                    "concat", sources)
            self.assertEqual(farm_dir,
                             Path(tmp) / "root" / "concat" / "local_inputs")
            self.assertEqual(sorted(p.name for p in farm_dir.iterdir()),
                             sorted(s.name for s in sources))
            # merge_factor (200) CLAMPED to the input count (3).
            self.assertEqual(input_map, {s.name: 3 for s in sources})

    def test_mustops_ce_map_values_are_all_one(self):
        # mustops_ce has no merge_factor (TargetStopResampler, not a merge).
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            sources = []
            for i in range(5):
                f = src_dir / f"sim.x.TargetStops.{i}.art"
                f.write_text("x")
                sources.append(f)
            with mock.patch.object(pipeline, "ROOT", Path(tmp) / "root"), \
                 mock.patch.dict(pipeline.STAGES, {"mustops_ce": {}},
                                 clear=True):
                _, input_map = pipeline.local_input_farm(
                    "mustops_ce", sources)
            self.assertEqual(set(input_map.values()), {1})
            self.assertEqual(len(input_map), 5)

    def test_falls_back_to_copy_across_a_device_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.art"
            src.write_text("data")
            with mock.patch.object(pipeline, "ROOT", Path(tmp) / "root"), \
                 mock.patch.dict(pipeline.STAGES,
                                 {"concat": {"merge_factor": 200}},
                                 clear=True), \
                 mock.patch.object(
                     pipeline.os, "link",
                     side_effect=OSError(errno.EXDEV, "cross-device link")):
                farm_dir, input_map = pipeline.local_input_farm(
                    "concat", [src])
            linked = farm_dir / "src.art"
            self.assertFalse(linked.is_symlink())
            self.assertEqual(linked.read_text(), "data")
            self.assertEqual(input_map, {"src.art": 1})

    def test_a_non_exdev_oserror_still_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.art"
            src.write_text("data")
            with mock.patch.object(pipeline, "ROOT", Path(tmp) / "root"), \
                 mock.patch.dict(pipeline.STAGES,
                                 {"concat": {"merge_factor": 200}},
                                 clear=True), \
                 mock.patch.object(
                     pipeline.os, "link",
                     side_effect=OSError(errno.EACCES, "permission denied")):
                with self.assertRaises(OSError):
                    pipeline.local_input_farm("concat", [src])

    def test_a_second_call_clears_the_prior_farm_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            a = src_dir / "a.art"
            a.write_text("a")
            with mock.patch.object(pipeline, "ROOT", Path(tmp) / "root"), \
                 mock.patch.dict(pipeline.STAGES, {"mustops_ce": {}},
                                 clear=True):
                farm_dir, _ = pipeline.local_input_farm("mustops_ce", [a])
                b = src_dir / "b.art"
                b.write_text("b")
                farm_dir2, input_map = pipeline.local_input_farm(
                    "mustops_ce", [b])
            self.assertEqual(farm_dir, farm_dir2)
            self.assertEqual(sorted(p.name for p in farm_dir.iterdir()),
                             ["b.art"])
            self.assertEqual(input_map, {"b.art": 1})


class TestLocalScaleEnvSeam(unittest.TestCase):
    """The graph runner shells out to `pipeline.py submit` and cannot pass
    --local-njobs/--local-events, so without an env seam every local campaign
    is pinned to the argparse defaults (1 job x 200 events per stage)."""

    def test_env_var_supplies_the_default(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200),
                5000)

    def test_unset_or_blank_falls_back(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AUTORESEARCH_LOCAL_EVENTS", None)
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)
            os.environ["AUTORESEARCH_LOCAL_EVENTS"] = "   "
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)

    def test_a_junk_or_zero_value_raises_rather_than_silently_defaulting(self):
        # Silently falling back would run 200 events while the operator
        # believed they had asked for 5000 -- and every metric harvest
        # computes is scaled by that number.
        for bad in ("5k", "0", "-3", "2.5"):
            with self.subTest(bad=bad):
                with mock.patch.dict(os.environ,
                                     {"AUTORESEARCH_LOCAL_EVENTS": bad}):
                    with self.assertRaises(ValueError):
                        local_exec.scale_default(
                            "AUTORESEARCH_LOCAL_EVENTS", 200)

    def test_an_explicit_flag_still_beats_the_env_var(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            njobs, events = pipeline._local_scale(
                SimpleNamespace(local_njobs=None, local_events=["77"]),
                "mubeam")
        self.assertEqual((njobs, events), (1, 77))

    def test_both_verbs_resolve_the_scale_identically(self):
        # local-build, local-run, and submit --local's runlocal branch must
        # all resolve scale through the ONE function; a drift between them
        # runs a subset (or dies on a missing index).
        src = Path(pipeline.__file__).read_text()
        self.assertEqual(src.count("_local_scale(args, stage)"), 3)


class TestLocalRefusesToClobberAGridCluster(unittest.TestCase):
    def test_a_real_cluster_id_with_no_marker_is_refused(self):
        # Both verbs overwrite <stage>_cluster.txt AND the events-per-job
        # stamp harvest divides by, so running local over a finished grid
        # stage rewrites that Eval's provenance and loses the cluster id.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("70314159\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"):
                with self.assertRaises(SystemExit) as cm:
                    pipeline._require_local_stage("mubeam")
        self.assertIn("70314159", str(cm.exception))

    def test_a_local_runid_is_re_runnable(self):
        # Marker present => the int is a runid this executor wrote. Re-running
        # local is ordinary (it allocates the next runid), not a clobber.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("1\n")
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"):
                pipeline._require_local_stage("mubeam")  # must not raise


class TestSourcedEnvRefusesAPreSourcedShell(unittest.TestCase):
    def test_muse_already_set_up_fails_fast_instead_of_retrying(self):
        # `muse setup` is one-shot per shell and run_sourced_bash inherits
        # this env, so the prelude fails with "Muse already setup for
        # directory" -- then burns all four retries (~50s) on a condition no
        # retry can fix, surfacing as a bare CalledProcessError.
        with mock.patch.dict(os.environ,
                             {"MUSE_WORK_DIR": "/somewhere/Offline"}), \
             mock.patch.object(pipeline, "run_sourced_bash") as rsb:
            with self.assertRaises(SystemExit) as cm:
                pipeline.sourced_env()
        rsb.assert_not_called()
        self.assertIn("fresh shell", str(cm.exception))


class TestLocalScaleEnvSeam(unittest.TestCase):
    """The graph runner shells out to `pipeline.py submit` and cannot pass
    --local-njobs/--local-events, so without an env seam every local campaign
    is pinned to the argparse defaults (1 job x 200 events per stage)."""

    def test_env_var_supplies_the_default(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200),
                5000)

    def test_unset_or_blank_falls_back(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AUTORESEARCH_LOCAL_EVENTS", None)
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)
            os.environ["AUTORESEARCH_LOCAL_EVENTS"] = "   "
            self.assertEqual(
                local_exec.scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)

    def test_a_junk_or_zero_value_raises_rather_than_silently_defaulting(self):
        # Silently falling back would run 200 events while the operator
        # believed they had asked for 5000 -- and harvest scales every metric
        # it computes by that number.
        for bad in ("5k", "0", "-3", "2.5"):
            with self.subTest(bad=bad):
                with mock.patch.dict(os.environ,
                                     {"AUTORESEARCH_LOCAL_EVENTS": bad}):
                    with self.assertRaises(ValueError):
                        local_exec.scale_default(
                            "AUTORESEARCH_LOCAL_EVENTS", 200)

    def test_an_explicit_flag_still_beats_the_env_var(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            njobs, events = pipeline._local_scale(
                SimpleNamespace(local_njobs=None, local_events=["77"]),
                "mubeam")
        self.assertEqual((njobs, events), (1, 77))

    def test_both_verbs_resolve_the_scale_identically(self):
        # local-build, local-run, and submit --local's runlocal branch must
        # all resolve scale through the ONE function; a drift between them
        # silently runs a subset or dies on a missing index.
        src = Path(pipeline.__file__).read_text()
        self.assertEqual(src.count("_local_scale(args, stage)"), 3)


class TestLocalRefusesToClobberAGridCluster(unittest.TestCase):
    def test_a_real_cluster_id_with_no_marker_is_refused(self):
        # Both verbs overwrite <stage>_cluster.txt AND the events-per-job
        # stamp harvest divides by, so running local over a finished grid
        # stage rewrites that Eval's provenance and loses the cluster id.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("70314159\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"):
                with self.assertRaises(SystemExit) as cm:
                    pipeline._require_local_stage("mubeam")
        self.assertIn("70314159", str(cm.exception))

    def test_a_local_runid_is_re_runnable(self):
        # Marker present => the int is a runid this executor wrote. Re-running
        # local is ordinary (it allocates the next runid), not a clobber.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("1\n")
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"):
                pipeline._require_local_stage("mubeam")  # must not raise


class TestSourcedEnvRefusesAPreSourcedShell(unittest.TestCase):
    def test_muse_already_set_up_fails_fast_instead_of_retrying(self):
        # `muse setup` is one-shot per shell and run_sourced_bash inherits
        # this process's env, so the prelude fails with "Muse already setup
        # for directory" -- then burns all four retries (~50s) on a condition
        # no retry can fix, surfacing as a bare CalledProcessError.
        with mock.patch.dict(os.environ,
                             {"MUSE_WORK_DIR": "/somewhere/Offline"}), \
             mock.patch.object(pipeline, "run_sourced_bash") as rsb:
            with self.assertRaises(SystemExit) as cm:
                pipeline.sourced_env()
        rsb.assert_not_called()
        self.assertIn("fresh shell", str(cm.exception))
