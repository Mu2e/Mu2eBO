"""Unit tests for the prodtools execution seam (core/prodtools_exec.py).

Zero grid contact: every prodtools invocation is an injected fake runner.
"""
import json
import os
import sys
import tempfile
import unittest
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
