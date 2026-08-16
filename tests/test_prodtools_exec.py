"""Unit tests for the prodtools execution seam (core/prodtools_exec.py).

Zero grid contact: every prodtools invocation is an injected fake runner.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths
import pipeline
import prodtools_exec as pex


class TestProdtoolsRoot(unittest.TestCase):
    def test_unset_env_names_the_variable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTORESEARCH_PRODTOOLS", None)
            with self.assertRaises(SystemExit) as cm:
                paths.prodtools_root()
            self.assertIn("AUTORESEARCH_PRODTOOLS", str(cm.exception))

    def test_valid_checkout_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bin").mkdir()
            (Path(td) / "bin" / "json2jobdef").touch()
            with mock.patch.dict(os.environ,
                                 {"AUTORESEARCH_PRODTOOLS": td}):
                self.assertEqual(paths.prodtools_root(), Path(td))

    def test_dir_without_json2jobdef_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ,
                                 {"AUTORESEARCH_PRODTOOLS": td}):
                with self.assertRaises(SystemExit):
                    paths.prodtools_root()


class TestRenderEntry(unittest.TestCase):
    def _base(self, **kw):
        args = dict(config="t001", dsconf="Run1Bak_t001",
                    desc="Run1A_MuBeam_t001", njobs=200,
                    code_tarball=Path("/data/t001/Code.tar.bz2"),
                    fcl_name="mubeam_template_materialized.fcl")
        args.update(kw)
        return args

    def test_resampler_stage_shape(self):
        e = pex.render_entry(
            "mubeam", {}, **self._base(
                events=5000, run=1800,
                resampler_name="beamResampler",
                input_data={"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                inloc="tape"))
        self.assertEqual(e["desc"], "Run1A_MuBeam_t001")
        self.assertEqual(e["dsconf"], "Run1Bak_t001")
        self.assertEqual(e["fcl"], "mubeam_template_materialized.fcl")
        self.assertEqual(e["code"], "/data/t001/Code.tar.bz2")
        self.assertEqual(e["events"], 5000)
        self.assertEqual(e["run"], 1800)
        self.assertEqual(e["resampler_name"], "beamResampler")
        self.assertEqual(e["inloc"], "tape")
        self.assertEqual(e["outloc"],
                         {"*.art": "outstage", "*.root": "outstage"})
        self.assertNotIn("simjob_setup", e)   # exactly one Offline source

    def test_merge_stage_no_events(self):
        e = pex.render_entry(
            "concat", {}, **self._base(
                desc="Run1A_MuStopsCat_t001", njobs=1,
                input_data={"sim.a.art": 200, "sim.b.art": 200},
                inloc="dir:/pnfs/stage/t001/concat_inputs"))
        self.assertNotIn("events", e)
        self.assertNotIn("run", e)
        self.assertNotIn("resampler_name", e)
        self.assertEqual(e["inloc"], "dir:/pnfs/stage/t001/concat_inputs")

    def test_memory_formatted(self):
        e = pex.render_entry("mustops_ce", {},
                             **self._base(memory_mb=3000, events=2500,
                                          run=1801))
        self.assertEqual(e["memory"], "3000MB")

    def test_write_entry_is_one_element_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = pex.write_entry(Path(td), "mubeam", {"desc": "d"})
            self.assertEqual(p.name, "mubeam_entry.json")
            data = json.loads(p.read_text())
            self.assertEqual(data, [{"desc": "d"}])


class TestOutstageRoot(unittest.TestCase):
    def test_matches_legacy_constant(self):
        self.assertEqual(
            pex.outstage_root(),
            f"/pnfs/mu2e/scratch/users/{pex.USER}/workflow/default/outstage")


_WAIT_GRID = {
    "jobdef": "cnf.t.tar", "cluster": "777@jobsub01.fnal.gov",
    "jobs": [
        {"index": 0, "proc": 0, "rc": 0,
         "outputs": ["/pnfs/out/777/0/sim.u.D.C.0.art"]},
        {"index": 1, "proc": 1, "rc": 1,
         "outputs": ["/pnfs/out/777/1/sim.u.D.C.1.art"]},
        {"index": 2, "proc": 2, "rc": None,
         "outputs": ["/pnfs/out/777/2/sim.u.D.C.2.art"]},
    ],
    "ok": 1, "failed": [1], "unknown": [2],
}

_WAIT_LOCAL = {
    "jobdef": "cnf.t.tar",
    "jobs": [
        {"index": 0, "rc": 0, "dir": "/data/local/j0",
         "outputs": ["sim.u.D.C.0.art", "nts.u.D.C.0.root"]},
        {"index": 1, "rc": 137, "dir": "/data/local/j1",
         "outputs": ["sim.u.D.C.1.art"]},
    ],
    "ok": 1, "failed": [1],
}


class TestWaitContract(unittest.TestCase):
    def test_ok_jobs_only(self):
        outs = pex.outputs_from_wait(_WAIT_GRID, "sim.*.art")
        self.assertEqual(outs, ["/pnfs/out/777/0/sim.u.D.C.0.art"])

    def test_unknown_is_not_ok(self):
        # rc None (condor history had no record) must never count as done.
        outs = pex.outputs_from_wait(_WAIT_GRID, "sim.*.art")
        self.assertNotIn("/pnfs/out/777/2/sim.u.D.C.2.art", outs)

    def test_glob_filters_secondary_streams(self):
        outs = pex.outputs_from_wait(_WAIT_LOCAL, "sim.*.art")
        self.assertEqual(outs, ["/data/local/j0/sim.u.D.C.0.art"])

    def test_relative_outputs_join_job_dir(self):
        outs = pex.outputs_from_wait(_WAIT_LOCAL, "nts.*.root")
        self.assertEqual(outs, ["/data/local/j0/nts.u.D.C.0.root"])

    def test_read_wait_missing_is_systemexit(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                pex.read_wait(Path(td), "mubeam")

    def test_contract_core_keys_shared(self):
        # The "same JSON either way" claim, pinned: consumers may key on
        # these and only these.
        for fx in (_WAIT_GRID, _WAIT_LOCAL):
            self.assertLessEqual({"jobdef", "jobs", "ok", "failed"},
                                 set(fx))
            for j in fx["jobs"]:
                self.assertLessEqual({"index", "rc", "outputs"}, set(j))


class TestListOutputsFromWait(unittest.TestCase):
    """Pipeline-level: cmd_list_outputs reads state/<stage>_wait.json via
    prodtools_exec, one code path for grid and local."""

    def test_outputs_txt_has_ok_jobs_only(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
             mock.patch.dict(pipeline.STAGES["mubeam"],
                             {"output_glob": "sim.*.art"}):
            pipeline._bind_config("cfg001")
            pipeline.STATE.mkdir(parents=True)
            (pipeline.STATE / "mubeam_wait.json").write_text(
                json.dumps(_WAIT_GRID))
            pipeline.cmd_list_outputs(
                SimpleNamespace(stage="mubeam", force=False))
            outputs_file = pipeline.STATE / "mubeam_outputs.txt"
            lines = [p for p in outputs_file.read_text().splitlines()
                     if p.strip()]
        self.assertEqual(lines, ["/pnfs/out/777/0/sim.u.D.C.0.art"])


class TestRunJobwait(unittest.TestCase):
    """AUTORESEARCH_PRODTOOLS is unset in a bare test shell (see
    TestProdtoolsRoot) -- every test here patches prodtools_root directly,
    same convention as TestBuildCnf."""

    def test_command_shape(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"

            def run(cmd, **kw):
                self.last_cmd = cmd
                self.last_kw = kw
                wait_json.write_text(json.dumps(_WAIT_GRID))
                return subprocess.CompletedProcess(cmd, 0)

            rc = pex.run_jobwait(Path(td), Path(td) / "cnf.t.tar",
                                 "777@jobsub01.fnal.gov", 200, wait_json,
                                 {"X": "1"}, runner=run, poll_s=15)
        self.assertEqual(rc, 0)
        joined = " ".join(str(c) for c in self.last_cmd)
        self.assertIn("jobwait", joined)
        for flag, val in (("--jobdef", str(Path(td) / "cnf.t.tar")),
                          ("--cluster", "777@jobsub01.fnal.gov"),
                          ("--njobs", "200"),
                          ("--outstage", pex.outstage_root()),
                          ("--poll-s", "15"),
                          ("--json", str(wait_json))):
            self.assertIn(flag, self.last_cmd)
            self.assertEqual(self.last_cmd[self.last_cmd.index(flag) + 1],
                             val)
        self.assertEqual(self.last_kw["cwd"], str(td))
        self.assertEqual(self.last_kw["env"], {"X": "1"})

    def test_nonzero_rc_returns_not_raises(self):
        # jobwait's rc reflects the cluster outcome (partial ok), not a
        # tool failure -- acceptance policy belongs to cmd_poll, not here.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"

            def run(cmd, **kw):
                wait_json.write_text(json.dumps(_WAIT_GRID))
                return subprocess.CompletedProcess(cmd, 7)

            rc = pex.run_jobwait(Path(td), Path(td) / "cnf.t.tar", "777@s",
                                 200, wait_json, {}, runner=run)
        self.assertEqual(rc, 7)

    def test_missing_wait_json_after_run_is_systemexit(self):
        # jobwait died before writing its summary -- callers have nothing
        # to read, so this IS a tool failure, unlike a plain nonzero rc.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"  # never written
            with self.assertRaises(SystemExit):
                pex.run_jobwait(Path(td), Path(td) / "cnf.t.tar", "777@s",
                                200, wait_json, {},
                                runner=lambda cmd, **kw:
                                    subprocess.CompletedProcess(cmd, 1))


class TestCmdPollViaJobwait(unittest.TestCase):
    """Pipeline-level: cmd_poll invokes prodtools jobwait (via a fake
    runner standing in for the real binary) and applies autoresearch's
    own quorum/zero-ok acceptance policy on the wait.json it writes."""

    def _run(self, tmp, njobs, quorum, wait_body, jobwait_rc=0):
        state = None

        def fake_run_jobwait(stage_dir, cnf, jobid, njobs_, wait_json,
                             env, **kw):
            self.jobwait_call = dict(stage_dir=stage_dir, cnf=cnf,
                                     jobid=jobid, njobs=njobs_,
                                     wait_json=wait_json, env=env)
            Path(wait_json).write_text(json.dumps(wait_body))
            return jobwait_rc

        with mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
             mock.patch.dict(pipeline.STAGES["mubeam"],
                             {"njobs": njobs, "quorum": quorum}), \
             mock.patch.object(pipeline, "sourced_env", return_value={}), \
             mock.patch.object(pipeline.px, "run_jobwait",
                               side_effect=fake_run_jobwait) as self.rj:
            pipeline._bind_config("cfg001")
            pipeline.STATE.mkdir(parents=True)
            (pipeline.STATE / "mubeam_cluster.txt").write_text("777\n")
            pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                              cap_hours=24.0))

    def test_ok_meets_quorum_proceeds_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, njobs=3, quorum=0.9,
                      wait_body={"jobdef": "cnf.t.tar", "jobs": [],
                                 "ok": 3, "failed": [], "unknown": []})
        self.rj.assert_called_once()

    def test_zero_ok_is_systemexit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                self._run(tmp, njobs=3, quorum=0.9,
                          wait_body={"jobdef": "cnf.t.tar", "jobs": [],
                                     "ok": 0, "failed": [0, 1, 2],
                                     "unknown": []})
        self.assertIn("0/3", str(cm.exception))

    def test_partial_below_quorum_warns_and_proceeds(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
             redirect_stdout(buf):
            # ok=1 < target=ceil(0.9*3)=2 -- below quorum but nonzero, so
            # this must print WARN and return normally (no exception).
            self._run(tmp, njobs=3, quorum=0.9,
                      wait_body={"jobdef": "cnf.t.tar", "jobs": [],
                                 "ok": 1, "failed": [1, 2], "unknown": []})
        self.assertIn("WARN", buf.getvalue())
        self.assertIn("1/3", buf.getvalue())

    def test_local_marker_no_ops_without_invoking_the_runner(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
             mock.patch.object(pipeline.px, "run_jobwait") as rj:
            pipeline._bind_config("cfg001")
            pipeline.STATE.mkdir(parents=True)
            (pipeline.STATE / "mubeam_local.txt").write_text("1\n")
            pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                              cap_hours=24.0))
        rj.assert_not_called()

    def test_jobsub_id_file_wins_over_cluster_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
                 mock.patch.dict(pipeline.STAGES["mubeam"],
                                 {"njobs": 3, "quorum": 0.9}), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={}), \
                 mock.patch.object(pipeline.px, "run_jobwait") as rj:
                pipeline._bind_config("cfg001")
                pipeline.STATE.mkdir(parents=True)
                (pipeline.STATE / "mubeam_cluster.txt").write_text("777\n")
                (pipeline.STATE / "mubeam_jobsub_id.txt").write_text(
                    "777@jobsub02.fnal.gov\n")

                def fake(stage_dir, cnf, jobid, njobs_, wait_json, env,
                         **kw):
                    Path(wait_json).write_text(json.dumps(
                        {"jobdef": "cnf.t.tar", "jobs": [], "ok": 3,
                         "failed": [], "unknown": []}))
                    return 0
                rj.side_effect = fake
                pipeline.cmd_poll(SimpleNamespace(
                    stage="mubeam", quorum=None, cap_hours=24.0))
            self.assertEqual(rj.call_args[0][2], "777@jobsub02.fnal.gov")


class TestBuildCnf(unittest.TestCase):
    """AUTORESEARCH_PRODTOOLS is unset in a bare test shell (see
    TestProdtoolsRoot), so every test here patches prodtools_root
    directly rather than relying on an ambient checkout -- build_cnf's
    own resolution of it is TestProdtoolsRoot's job, not this class's."""

    def _runner(self, rc=0, stdout="", stderr="", touch_cnf=None):
        def run(cmd, **kw):
            self.last_cmd = cmd
            self.last_kw = kw
            if touch_cnf is not None:
                touch_cnf.touch()
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
        return run

    def test_shells_out_to_json2jobdef_and_returns_the_cnf_path(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            expected_cnf = (Path(td) /
                            f"cnf.{pex.USER}.Run1A_MuBeam_t001.Run1Bak_t001.0.tar")
            cnf = pex.build_cnf(
                Path(td), Path(td) / "e.json", "Run1A_MuBeam_t001",
                "Run1Bak_t001", {},
                runner=self._runner(touch_cnf=expected_cnf))
        self.assertEqual(cnf.name,
                         f"cnf.{pex.USER}.Run1A_MuBeam_t001.Run1Bak_t001.0.tar")
        joined = " ".join(str(c) for c in self.last_cmd)
        self.assertIn("json2jobdef", joined)
        self.assertIn("--desc Run1A_MuBeam_t001", joined)
        self.assertIn("--dsconf Run1Bak_t001", joined)

    def test_nonzero_rc_is_systemexit_with_stderr(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            with self.assertRaises(SystemExit) as cm:
                pex.build_cnf(Path(td), Path(td) / "e.json", "d", "c", {},
                              runner=self._runner(rc=1, stderr="bad json"))
            self.assertIn("bad json", str(cm.exception))

    def test_rc_zero_but_missing_cnf_is_systemexit(self):
        # json2jobdef reported success but never wrote the tarball --
        # a silent lie must not propagate a nonexistent Path downstream.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            with self.assertRaises(SystemExit):
                pex.build_cnf(Path(td), Path(td) / "e.json", "d", "c", {},
                              runner=self._runner(rc=0))


class TestSubmitCnf(unittest.TestCase):
    """Same AUTORESEARCH_PRODTOOLS note as TestBuildCnf -- test_driver_cmd_shape
    is the one test that legitimately exercises the real env-var resolution
    (it asserts on the driver argv), so it sets AUTORESEARCH_PRODTOOLS itself
    instead of patching prodtools_root."""

    def _runner(self, stdout, rc=0, stderr=""):
        def run(cmd, **kw):
            self.last_cmd = cmd
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
        return run

    def test_parses_submit_result(self):
        out = ('noise\nSUBMIT_RESULT {"cluster_id": 86123999, '
               '"jobsub_id": "86123999.0@jobsub01.fnal.gov", '
               '"status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            cluster, jobsub_id = pex.submit_cnf(
                Path(td), Path(td) / "e.json", Path(td) / "l.db",
                "autoresearch:t001/mubeam", {}, runner=self._runner(out))
        self.assertEqual(cluster, 86123999)
        # jobwait wants NNNN@schedd -- proc stripped, schedd kept.
        self.assertEqual(jobsub_id, "86123999@jobsub01.fnal.gov")

    def test_no_result_line_is_systemexit(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            with self.assertRaises(SystemExit):
                pex.submit_cnf(Path(td), Path(td) / "e.json",
                               Path(td) / "l.db", "o", {},
                               runner=self._runner("boom", rc=1,
                                                   stderr="ledger sad"))

    def test_driver_cmd_shape(self):
        out = ('SUBMIT_RESULT {"cluster_id": 1, '
               '"jobsub_id": "1.0@s", "status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"AUTORESEARCH_PRODTOOLS": td}):
            (Path(td) / "bin").mkdir(); (Path(td) / "bin" / "json2jobdef").touch()
            pex.submit_cnf(Path(td), Path(td) / "e.json", Path(td) / "l.db",
                           "o", {}, runner=self._runner(out))
        joined = " ".join(str(c) for c in self.last_cmd)
        self.assertIn("prodtools_submit_driver.py", joined)
        self.assertIn("--entry", joined)
        self.assertIn("--ledger", joined)

    def test_cluster_id_present_but_jobsub_id_missing_is_systemexit(self):
        # A cluster_id with no derivable schedd can't be jobwait'd -- must
        # fail loudly here, at submit time, not silently degrade to a bare
        # cluster number that only surfaces as a confusing jobwait failure
        # later (review finding 2, 2026-08-16).
        out = ('SUBMIT_RESULT {"cluster_id": 86123999, '
               '"jobsub_id": null, "status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            with self.assertRaises(SystemExit) as cm:
                pex.submit_cnf(Path(td), Path(td) / "e.json",
                               Path(td) / "l.db", "o", {},
                               runner=self._runner(out))
        self.assertIn("86123999", str(cm.exception))

    def test_cluster_id_present_but_jobsub_id_malformed_is_systemexit(self):
        # A non-empty jobsub_id with no "@schedd" (e.g. a bare cluster
        # string, or garbage) is just as unusable as None -- same guard.
        out = ('SUBMIT_RESULT {"cluster_id": 86123999, '
               '"jobsub_id": "not-a-jobsub-id", "status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            with self.assertRaises(SystemExit):
                pex.submit_cnf(Path(td), Path(td) / "e.json",
                               Path(td) / "l.db", "o", {},
                               runner=self._runner(out))
