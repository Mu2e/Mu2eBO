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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))

import paths
import pipeline
import prodtools_exec as pex
import pipeline_io as pio


def _stage_cfg_override(stage, **overrides):
    """Patch pipeline.stage_cfg so `stage`'s merged config carries
    `overrides` on top of the REAL stage_entries/<stage>.json + mode-spec
    data -- the STAGES module dict this task retired used to be a plain
    dict any test could mock.patch.dict directly; stage_cfg() computes its
    return fresh on every call, so tests patch the function instead."""
    real = pipeline.stage_cfg

    def fake(s, mode=None):
        cfg = real(s, mode)
        if s == stage:
            cfg.update(overrides)
        return cfg

    return mock.patch.object(pipeline, "stage_cfg", side_effect=fake)


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
        args = dict(dsconf="Run1Bak_t001",
                    desc="Run1A_MuBeam_t001", njobs=200,
                    code_tarball=Path("/data/t001/Code.tar.bz2"),
                    # Task 13: `fcl` is the published Production FCL path,
                    # not a per-config materialized file's basename.
                    fcl_name="Production/JobConfig/pileup/MuBeamResampler.fcl")
        args.update(kw)
        return args

    def test_resampler_stage_shape(self):
        e = pex.render_entry(
            **self._base(
                events=5000, run=1800,
                resampler_name="beamResampler",
                input_data={"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                inloc="tape"))
        self.assertEqual(e["desc"], "Run1A_MuBeam_t001")
        self.assertEqual(e["dsconf"], "Run1Bak_t001")
        self.assertEqual(e["fcl"],
                         "Production/JobConfig/pileup/MuBeamResampler.fcl")
        self.assertEqual(e["code"], "/data/t001/Code.tar.bz2")
        self.assertEqual(e["events"], 5000)
        self.assertEqual(e["run"], 1800)
        self.assertEqual(e["resampler_name"], "beamResampler")
        self.assertEqual(e["inloc"], "tape")
        self.assertEqual(e["outloc"],
                         {"*.art": "outstage", "*.root": "outstage"})
        self.assertNotIn("simjob_setup", e)   # exactly one Offline source
        self.assertNotIn("fcl_overrides", e)  # not passed -> not present

    def test_fcl_overrides_copied_into_the_entry_when_given(self):
        overrides = {"#include": "epilog_1b.fcl",
                    "services.SeedService.baseSeed": 1}
        e = pex.render_entry(**self._base(fcl_overrides=overrides))
        self.assertEqual(e["fcl_overrides"], overrides)

    def test_fcl_overrides_is_a_copy_not_an_alias(self):
        # render_entry's caller (pipeline._render_fcl_overrides) already
        # deep-copies STAGE_FCL, but render_entry must not re-introduce
        # aliasing on top of whatever dict it's handed -- a caller mutating
        # its own overrides dict after the call must never leak into the
        # already-rendered entry.
        overrides = {"a": 1}
        e = pex.render_entry(**self._base(fcl_overrides=overrides))
        overrides["a"] = 2
        overrides["b"] = 3
        self.assertEqual(e["fcl_overrides"], {"a": 1})

    def test_merge_stage_no_events(self):
        e = pex.render_entry(
            **self._base(
                desc="Run1A_MuStopsCat_t001", njobs=1,
                input_data={"sim.a.art": 200, "sim.b.art": 200},
                inloc="dir:/pnfs/stage/t001/concat_inputs"))
        self.assertNotIn("events", e)
        self.assertNotIn("run", e)
        self.assertNotIn("resampler_name", e)
        self.assertEqual(e["inloc"], "dir:/pnfs/stage/t001/concat_inputs")

    def test_memory_formatted(self):
        e = pex.render_entry(**self._base(memory_mb=3000, events=2500,
                                          run=1801))
        self.assertEqual(e["memory"], "3000MB")

    def test_outloc_defaults_to_the_outstage_literal_when_omitted(self):
        e = pex.render_entry(**self._base())
        self.assertEqual(e["outloc"], {"*.art": "outstage", "*.root": "outstage"})

    def test_outloc_passed_in_wins_over_the_default(self):
        # Review finding: a stage_entries/<stage>.json "outloc" must
        # actually reach the rendered entry, not be shadowed by the
        # hardcoded literal -- the same silent-divergence class this task
        # closed for every other stage_entries key.
        custom = {"*.art": "tape", "*.root": "disk"}
        e = pex.render_entry(**self._base(outloc=custom))
        self.assertEqual(e["outloc"], custom)

    def test_outloc_is_a_copy_not_an_alias(self):
        custom = {"*.art": "tape"}
        e = pex.render_entry(**self._base(outloc=custom))
        custom["*.art"] = "disk"
        custom["*.root"] = "outstage"
        self.assertEqual(e["outloc"], {"*.art": "tape"})

    def test_write_entry_is_one_element_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = pex.write_entry(Path(td), "mubeam", {"desc": "d"})
            self.assertEqual(p.name, "mubeam_entry.json")
            data = json.loads(p.read_text())
            self.assertEqual(data, [{"desc": "d"}])


class TestLoadStageEntry(unittest.TestCase):
    """pex.load_stage_entry / pex._substitute_placeholders (Task 14):
    stage_entries/<stage>.json -> substituted entry template. Uses a
    throwaway `entries_dir` fixture, not the real stage_entries/ tree --
    the real files are covered end-to-end by
    tests/test_pipeline_verbs.py::TestStageEntries."""

    def _write(self, tmp, stage, payload):
        d = Path(tmp)
        (d / f"{stage}.json").write_text(json.dumps(payload))
        return d

    def test_substitutes_cfg_and_geom_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "x", {
                "fcl": "a/b.fcl",
                "fcl_overrides": {
                    "services.GeometryService.inputFile": "{geom}",
                    "nested": {"list": ["prefix_{cfg}_suffix", 3]},
                },
            })
            e = pex.load_stage_entry("x", cfg="cfg007", geom="g.txt",
                                     entries_dir=d)
        self.assertEqual(
            e["fcl_overrides"]["services.GeometryService.inputFile"], "g.txt")
        self.assertEqual(
            e["fcl_overrides"]["nested"]["list"][0], "prefix_cfg007_suffix")
        self.assertEqual(e["fcl_overrides"]["nested"]["list"][1], 3)  # untouched

    def test_unknown_placeholder_raises_naming_the_key_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "x", {
                "fcl_overrides": {"a": {"b": "{typo}"}},
            })
            with self.assertRaises(ValueError) as cm:
                pex.load_stage_entry("x", cfg="c", geom="g", entries_dir=d)
        self.assertIn("typo", str(cm.exception))
        self.assertIn("x.fcl_overrides.a.b", str(cm.exception))

    def test_missing_stage_file_is_a_system_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                pex.load_stage_entry("nope", cfg="c", geom="g",
                                     entries_dir=Path(tmp))
        self.assertIn("nope", str(cm.exception))

    def test_include_key_stays_first_through_json_load_and_substitution(self):
        # json.load preserves source key order; _substitute_placeholders'
        # dict comprehension must not reshuffle it.
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "x", {
                "fcl_overrides": {
                    "#include": ["a.fcl", "b.fcl"],
                    "services.SeedService.baseSeed": 1,
                    "services.GeometryService.inputFile": "{geom}",
                },
            })
            e = pex.load_stage_entry("x", cfg="c", geom="g.txt", entries_dir=d)
        self.assertEqual(list(e["fcl_overrides"].keys())[0], "#include")

    def test_repeated_calls_do_not_alias_or_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "x", {
                "fcl_overrides": {"services.GeometryService.inputFile": "{geom}"},
            })
            e1 = pex.load_stage_entry("x", cfg="c", geom="geom1.txt",
                                      entries_dir=d)
            e1["fcl_overrides"]["injected"] = "leak"
            e2 = pex.load_stage_entry("x", cfg="c", geom="geom2.txt",
                                      entries_dir=d)
        self.assertEqual(
            e2["fcl_overrides"]["services.GeometryService.inputFile"],
            "geom2.txt")
        self.assertNotIn("injected", e2["fcl_overrides"])

    def test_comment_key_rides_along_unsubstituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "x", {"_comment": "see pipeline.py",
                                       "fcl": "a.fcl"})
            e = pex.load_stage_entry("x", cfg="c", geom="g", entries_dir=d)
        self.assertEqual(e["_comment"], "see pipeline.py")

    def test_real_stage_entries_dir_all_five_stages_load_without_error(self):
        # Smoke-validates the checked-in JSON: any typo'd placeholder in
        # the real stage_entries/<stage>.json files fails here, not three
        # subprocesses deep inside a real submit.
        for stage in ("mubeam", "run1b_mubeam", "concat", "mustops_ce",
                     "elebeam_flash"):
            with self.subTest(stage=stage):
                pex.load_stage_entry(stage, cfg="x001", geom="geom.txt")


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
    # Real prodtools runlocal (utils/runlocal.py `summary()`, verified
    # against the checked-out prodtools 2026-08-16) ALWAYS joins each job's
    # `dir` with its bare output name before writing the JSON -- `outputs`
    # is absolute, never bare basenames, even though the per-job `JobResult`
    # it builds from stores bare names internally. M6 (2026-08-16 review):
    # this fixture used to carry bare names, implying relative-then-joined
    # was runlocal's normal shape; it isn't -- see
    # _WAIT_LOCAL_RELATIVE_OUTPUTS below for the (defense-in-depth, not the
    # common case) join-path test.
    "jobdef": "cnf.t.tar",
    "jobs": [
        {"index": 0, "rc": 0, "dir": "/data/local/j0",
         "outputs": ["/data/local/j0/sim.u.D.C.0.art",
                     "/data/local/j0/nts.u.D.C.0.root"]},
        {"index": 1, "rc": 137, "dir": "/data/local/j1",
         "outputs": ["/data/local/j1/sim.u.D.C.1.art"]},
    ],
    "ok": 1, "failed": [1],
}

# outputs_from_wait's `if not os.path.isabs(o) and job.get("dir")` branch
# exists for a producer that did NOT already join dir+name the way real
# runlocal does -- kept as an explicit, separately-fixtured case (not
# implied by _WAIT_LOCAL) since M6 retired the bare-name shape from the
# "this is what runlocal writes" fixture above.
_WAIT_LOCAL_RELATIVE_OUTPUTS = {
    "jobdef": "cnf.t.tar",
    "jobs": [
        {"index": 0, "rc": 0, "dir": "/data/local/j0",
         "outputs": ["nts.u.D.C.0.root"]},
    ],
    "ok": 1, "failed": [],
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
        # M6: a bare (relative) output name gets joined with the job's
        # `dir` -- exercised against _WAIT_LOCAL_RELATIVE_OUTPUTS, not
        # _WAIT_LOCAL (which, like real runlocal, is already absolute).
        outs = pex.outputs_from_wait(_WAIT_LOCAL_RELATIVE_OUTPUTS,
                                     "nts.*.root")
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
             _stage_cfg_override("mubeam", output_glob="sim.*.art"):
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
             _stage_cfg_override("mubeam", njobs=njobs, quorum=quorum), \
             mock.patch.object(pipeline, "sourced_env", return_value={}), \
             mock.patch.object(pipeline.px, "run_jobwait",
                               side_effect=fake_run_jobwait) as self.rj:
            pipeline._bind_config("cfg001")
            pipeline.STATE.mkdir(parents=True)
            (pipeline.STATE / "mubeam_cluster.txt").write_text("777\n")
            pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                              cap_hours=24.0))

    def test_cnf_path_matches_px_cnf_path(self):
        # M1: cmd_poll re-derives the cnf path (no entry.json to re-read at
        # poll time) via px.cnf_path -- pin that it's the SAME naming rule
        # build_cnf itself used, not a second inline f-string that could
        # silently drift from it.
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, njobs=3, quorum=0.9,
                      wait_body={"jobdef": "cnf.t.tar", "jobs": [],
                                 "ok": 3, "failed": [], "unknown": []})
        expected = pex.cnf_path(pipeline.ROOT / "mubeam",
                                pipeline._stage_desc("mubeam"),
                                pipeline._stage_dsconf("mubeam"))
        self.assertEqual(self.jobwait_call["cnf"], expected)

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

    def test_the_env_var_alone_does_not_make_poll_skip_a_live_grid_cluster(self):
        # AUTORESEARCH_LOCAL is an ACTIVATION switch (cmd_submit reads it to
        # choose local mode), never a DETECTION signal. An operator who
        # exported it for a study and then launched a campaign from the same
        # shell must still get a real poll: if the env var alone made
        # _is_local_stage true, this poll would silently no-op on a LIVE
        # cluster and the chain would march on to harvest jobs that have not
        # finished. Ported from tests/test_local_exec.py (added there before
        # the prodtools switch's run_jobwait rewrite).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_cluster.txt").write_text("70314159\n")  # a real one
            # ... and NO mubeam_local.txt.

            def fake_run_jobwait(stage_dir, cnf, jobid, njobs, wait_json,
                                 env, **kw):
                Path(wait_json).write_text(json.dumps(
                    {"jobdef": "cnf.t.tar", "jobs": [], "ok": 999999,
                     "failed": [], "unknown": []}))
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

    def test_jobsub_id_file_wins_over_cluster_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
                 _stage_cfg_override("mubeam", njobs=3, quorum=0.9), \
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


class TestRunRunlocal(unittest.TestCase):
    """AUTORESEARCH_PRODTOOLS is unset in a bare test shell (see
    TestProdtoolsRoot) -- every test here patches prodtools_root directly,
    same convention as TestRunJobwait/TestBuildCnf."""

    def test_command_shape(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"

            def run(cmd, **kw):
                self.last_cmd = cmd
                self.last_kw = kw
                wait_json.write_text(json.dumps(_WAIT_LOCAL))
                return subprocess.CompletedProcess(cmd, 0)

            rc = pex.run_runlocal(
                Path(td), Path(td) / "cnf.t.tar", 2, wait_json, {"X": "1"},
                code_tarball=Path(td) / "Code.tar.bz2", pool=3, runner=run)
        self.assertEqual(rc, 0)
        joined = " ".join(str(c) for c in self.last_cmd)
        self.assertIn("runlocal", joined)
        for flag, val in (("--jobdef", str(Path(td) / "cnf.t.tar")),
                          ("--first", "0"),
                          ("--num", "2"),
                          ("-j", "3"),
                          ("--workdir", str(Path(td) / "local")),
                          ("--code", str(Path(td) / "Code.tar.bz2")),
                          ("--json", str(wait_json))):
            self.assertIn(flag, self.last_cmd)
            self.assertEqual(self.last_cmd[self.last_cmd.index(flag) + 1],
                             val)
        self.assertNotIn("--inloc", self.last_cmd)
        self.assertNotIn("--nevts", self.last_cmd)
        self.assertEqual(self.last_kw["cwd"], str(td))
        self.assertEqual(self.last_kw["env"], {"X": "1"})

    def test_creates_the_workdir_before_invoking(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"
            workdir = Path(td) / "local"

            def run(cmd, **kw):
                self.assertTrue(workdir.is_dir(),
                               "runlocal invoked before --workdir existed")
                wait_json.write_text(json.dumps(_WAIT_LOCAL))
                return subprocess.CompletedProcess(cmd, 0)

            pex.run_runlocal(Path(td), Path(td) / "cnf.t.tar", 1, wait_json,
                             {}, code_tarball=Path(td) / "Code.tar.bz2",
                             runner=run)

    def test_inloc_appended_when_given(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mustops_ce_wait.json"

            def run(cmd, **kw):
                self.last_cmd = cmd
                wait_json.write_text(json.dumps(_WAIT_LOCAL))
                return subprocess.CompletedProcess(cmd, 0)

            pex.run_runlocal(Path(td), Path(td) / "cnf.t.tar", 1, wait_json,
                             {}, code_tarball=Path(td) / "Code.tar.bz2",
                             inloc="dir:/data/staged", runner=run)
        i = self.last_cmd.index("--inloc")
        self.assertEqual(self.last_cmd[i + 1], "dir:/data/staged")

    def test_missing_wait_json_after_run_is_systemexit(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"  # never written
            with self.assertRaises(SystemExit):
                pex.run_runlocal(
                    Path(td), Path(td) / "cnf.t.tar", 1, wait_json, {},
                    code_tarball=Path(td) / "Code.tar.bz2",
                    runner=lambda cmd, **kw:
                        subprocess.CompletedProcess(cmd, 1))

    def test_nonzero_rc_returns_not_raises(self):
        # A partial local cluster (some jobs failed) is not a tool failure --
        # same acceptance split run_jobwait makes.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            wait_json = Path(td) / "mubeam_wait.json"

            def run(cmd, **kw):
                wait_json.write_text(json.dumps(_WAIT_LOCAL))
                return subprocess.CompletedProcess(cmd, 5)

            rc = pex.run_runlocal(Path(td), Path(td) / "cnf.t.tar", 1,
                                  wait_json, {},
                                  code_tarball=Path(td) / "Code.tar.bz2",
                                  runner=run)
        self.assertEqual(rc, 5)


class TestListOutputsFromWaitLocal(unittest.TestCase):
    """The runlocal-shaped wait.json (relative outputs + a job 'dir') must
    read exactly like the grid one through cmd_list_outputs -- the whole
    point of the shared contract (spec decision 5)."""

    def test_outputs_txt_from_a_runlocal_shaped_wait_json(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "DATA_ROOT", Path(tmp)), \
             _stage_cfg_override("mubeam", output_glob="sim.*.art"):
            pipeline._bind_config("cfg001")
            pipeline.STATE.mkdir(parents=True)
            (pipeline.STATE / "mubeam_wait.json").write_text(
                json.dumps(_WAIT_LOCAL))
            pipeline.cmd_list_outputs(
                SimpleNamespace(stage="mubeam", force=False))
            outputs_file = pipeline.STATE / "mubeam_outputs.txt"
            lines = [p for p in outputs_file.read_text().splitlines()
                     if p.strip()]
        self.assertEqual(lines, ["/data/local/j0/sim.u.D.C.0.art"])


class TestCnfPath(unittest.TestCase):
    """M1 (2026-08-16 review): the `cnf.<user>.<desc>.<dsconf>.0.tar` naming
    rule lived inline, duplicated, at both build_cnf and core/pipeline.py's
    cmd_poll -- pex.cnf_path is now the one place that spells it out."""

    def test_matches_build_cnfs_naming(self):
        p = pex.cnf_path(Path("/data/t001/mubeam"), "Run1A_MuBeam_t001",
                         "Run1Bak_t001")
        self.assertEqual(
            p, Path("/data/t001/mubeam") /
            f"cnf.{pex.USER}.Run1A_MuBeam_t001.Run1Bak_t001.0.tar")

    def test_build_cnf_writes_where_cnf_path_says(self):
        # build_cnf derives its own expected path with the same rule --
        # pin that the two never drift apart.
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            expected = pex.cnf_path(Path(td), "d", "c")

            def run(cmd, **kw):
                expected.touch()
                return subprocess.CompletedProcess(cmd, 0)

            cnf = pex.build_cnf(Path(td), Path(td) / "e.json", "d", "c", {},
                                runner=run)
        self.assertEqual(cnf, expected)


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
        # The outstage convention rides the command line from this module's
        # WFTOP/WFPROJECT constants -- the driver holds no copy of its own.
        self.assertIn(f"--wftop {pex.WFTOP}", joined)
        self.assertIn(f"--wfproject {pex.WFPROJECT}", joined)

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


class TestWorkerLogPathsBothOutstageShapes(unittest.TestCase):
    """graph/pipeline_io.py's `_worker_log_paths` (Task 8): scan_logs must
    find worker logs whether the cluster was submitted by legacy mu2ejobsub
    (`<outstage>/<cluster>/00/<00000>/*.log`) or prodtools direct
    (`<outstage>/<cluster>/<proc>/*.log`, no zero-padded 00/ sublevel).

    All these fixtures have no `<stage>_outputs.txt` (i.e. every job in the
    cluster died before producing an .art) -- the case the outputs.txt-
    derived primary path goes blind on, forcing the cluster-dir fallback
    this task adds.
    """

    def _state_dir(self, root: Path, config: str) -> Path:
        state_dir = root / "grid_data" / config / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir

    def test_flat_shape_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outstage = root / "outstage"
            state_dir = self._state_dir(root, "cfgA")
            (state_dir / "mubeam_cluster.txt").write_text("42\n")
            log = outstage / "42" / "3" / "foo.log"
            log.parent.mkdir(parents=True)
            log.write_text("some log text\n")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", outstage):
                found = pio._worker_log_paths("cfgA", "mubeam")
            self.assertEqual(found, [log])

    def test_legacy_shape_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outstage = root / "outstage"
            state_dir = self._state_dir(root, "cfgB")
            (state_dir / "mubeam_cluster.txt").write_text("42\n")
            log = outstage / "42" / "00" / "00003" / "bar.log"
            log.parent.mkdir(parents=True)
            log.write_text("some log text\n")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", outstage):
                found = pio._worker_log_paths("cfgB", "mubeam")
            self.assertEqual(found, [log])

    def test_both_shapes_present_legacy_wins(self):
        # A cluster submitted pre-switch is legacy-only in practice, but the
        # documented tie-break (legacy checked first) should still hold if
        # both somehow have files.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outstage = root / "outstage"
            state_dir = self._state_dir(root, "cfgC")
            (state_dir / "mubeam_cluster.txt").write_text("42\n")
            flat_log = outstage / "42" / "3" / "foo.log"
            flat_log.parent.mkdir(parents=True)
            flat_log.write_text("flat\n")
            legacy_log = outstage / "42" / "00" / "00003" / "bar.log"
            legacy_log.parent.mkdir(parents=True)
            legacy_log.write_text("legacy\n")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", outstage):
                found = pio._worker_log_paths("cfgC", "mubeam")
            self.assertEqual(found, [legacy_log])

    def test_no_cluster_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._state_dir(root, "cfgD")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", root / "outstage"):
                found = pio._worker_log_paths("cfgD", "mubeam")
            self.assertEqual(found, [])

    def test_outputs_present_no_logs_yet_does_not_fall_back_to_cluster_glob(self):
        # Regression (review finding, 2026-08-16): outputs.txt has a valid
        # .art entry but its dir has zero .log files yet (a real race --
        # stage-out-lag / stage-out-rename-race), while an UNRELATED proc
        # in the same cluster happens to have a log. The primary
        # outputs.txt-derived result must be authoritative once outputs is
        # non-empty -- falling through to the cluster-wide glob here would
        # misattribute another proc's log (and its grep hits) to this stage.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outstage = root / "outstage"
            state_dir = self._state_dir(root, "cfgE")
            (state_dir / "mubeam_cluster.txt").write_text("42\n")
            art_dir = outstage / "42" / "3"
            art_dir.mkdir(parents=True)
            (art_dir / "sim.art").write_text("art\n")
            (state_dir / "mubeam_outputs.txt").write_text(
                str(art_dir / "sim.art") + "\n")
            stray_log = outstage / "42" / "7" / "stray.log"
            stray_log.parent.mkdir(parents=True)
            stray_log.write_text("stray\n")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", outstage):
                found = pio._worker_log_paths("cfgE", "mubeam")
            self.assertEqual(found, [])

    def test_flat_shape_with_outputs_happy_path(self):
        # Companion coverage gap: outputs.txt lists a flat-shape .art WITH
        # a .log beside it -- found via the primary per-.art-parent glob,
        # no cluster-dir fallback needed.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outstage = root / "outstage"
            state_dir = self._state_dir(root, "cfgF")
            art_dir = outstage / "42" / "3"
            art_dir.mkdir(parents=True)
            (art_dir / "sim.art").write_text("art\n")
            log = art_dir / "sim.log"
            log.write_text("log\n")
            (state_dir / "mubeam_outputs.txt").write_text(
                str(art_dir / "sim.art") + "\n")
            with mock.patch.object(pio, "GRID_DATA_ROOT", root / "grid_data"), \
                 mock.patch.object(pio, "OUTSTAGE_ROOT", outstage):
                found = pio._worker_log_paths("cfgF", "mubeam")
            self.assertEqual(found, [log])


class TestStaleCodeTreeInvalidation(unittest.TestCase):
    """runlocal unpacks the code tarball once per workdir and reuses it
    forever after (its `.unpack-complete` sentinel answers "complete?",
    never "from THIS tarball?"), so re-submitting the same (config, stage)
    after a rebuild silently ran the OLD code -- measured 2026-08-17 as a
    job failing rc=90 against a deleted include. These pin the
    invalidation without disabling the reuse (several GB per unpack)."""

    def _tarball(self, td, content):
        t = Path(td) / "Code.tar.bz2"
        t.write_text(content)
        return t

    def _tree(self, td):
        """An already-unpacked tree with a payload file to watch."""
        root = Path(td) / "local" / "code"
        (root / "Code").mkdir(parents=True)
        (root / "Code" / "payload.fcl").write_text("old")
        (root / ".unpack-complete").write_text("")
        return root

    def test_tree_from_a_different_tarball_is_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            first = self._tarball(td, "A")
            pex._invalidate_stale_code_tree(Path(td) / "local", first)
            # Second call with DIFFERENT content at the same path: the
            # geom-rebuild case, which the cache filename's extras-only
            # token cannot distinguish.
            os.utime(first, (1, 1))
            second = self._tarball(td, "BB")
            self.assertTrue(
                pex._invalidate_stale_code_tree(Path(td) / "local", second))
            self.assertFalse((root / "Code" / "payload.fcl").exists())

    def test_tree_from_the_same_tarball_is_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            t = self._tarball(td, "A")
            # The first call stamps the tree -- and discards it, since a
            # tree predating this guard is unstamped. Simulate the unpack
            # runlocal would then do, and check the SECOND call keeps it.
            pex._invalidate_stale_code_tree(Path(td) / "local", t)
            (root / "Code").mkdir(parents=True, exist_ok=True)
            (root / "Code" / "payload.fcl").write_text("kept")
            self.assertFalse(
                pex._invalidate_stale_code_tree(Path(td) / "local", t))
            self.assertEqual((root / "Code" / "payload.fcl").read_text(),
                             "kept")

    def test_unstamped_preexisting_tree_is_discarded_once(self):
        # A tree unpacked before this guard existed carries no stamp; it
        # must be treated as unknown-provenance, not silently trusted.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            t = self._tarball(td, "A")
            self.assertTrue(
                pex._invalidate_stale_code_tree(Path(td) / "local", t))
            self.assertFalse((root / "Code" / "payload.fcl").exists())
            self.assertFalse(
                pex._invalidate_stale_code_tree(Path(td) / "local", t))

    def test_missing_tarball_leaves_the_tree_for_runlocal_to_refuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            self.assertFalse(pex._invalidate_stale_code_tree(
                Path(td) / "local", Path(td) / "nope.tar.bz2"))
            self.assertTrue((root / "Code" / "payload.fcl").exists())

    def test_run_runlocal_invalidates_before_invoking(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(pex, "prodtools_root",
                               return_value=Path("/fake/prodtools")):
            root = self._tree(td)
            t = self._tarball(td, "A")
            wait_json = Path(td) / "mubeam_wait.json"

            def run(cmd, **kw):
                # By the time runlocal is invoked the stale tree must be
                # gone -- otherwise it reuses it and never reads the new
                # tarball at all.
                self.assertFalse((root / "Code" / "payload.fcl").exists())
                wait_json.write_text(json.dumps(_WAIT_LOCAL))
                return subprocess.CompletedProcess(cmd, 0)

            pex.run_runlocal(Path(td), Path(td) / "cnf.t.tar", 1, wait_json,
                             {}, code_tarball=t, runner=run)
