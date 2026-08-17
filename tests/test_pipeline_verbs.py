"""Grid-verb tests for core/pipeline.py: submit idempotency, stamp-at-submit,
list-outputs gating, submit_stage_prodtools state writes, the local
executor (cmd_submit --local via prodtools runlocal), and the small
free-standing helpers (_require_local_stage, stamp_local_events,
sourced_env guards, local scale resolution, local_input_farm).
No grid contact: STATE/STAGES/ROOT are patched to tmp dirs and the
prodtools_exec (px) / subprocess boundary is faked."""
import contextlib
import copy
import errno
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import pipeline  # noqa: E402
import harvest as hv  # noqa: E402


def _stub_run_runlocal(rc=0, ok=None):
    """A px.run_runlocal side_effect that writes a real (minimal) wait.json.

    cmd_submit's --local branch reads the wait.json back right after
    run_runlocal returns (M5, 2026-08-16 review: WARN when ok < njobs) --
    a bare `return_value=...` mock leaves nothing for that px.read_wait
    call to find, which would raise SystemExit (missing wait.json) in every
    test that mocks run_runlocal wholesale. `ok` defaults to the call's own
    `njobs` argument (i.e. "every job ok") so tests that don't care about
    M5's WARN path don't trip it by accident.
    """
    def _fn(stage_dir, cnf, njobs, wait_json, env, **kw):
        Path(wait_json).write_text(json.dumps({
            "jobdef": "cnf.t.tar", "jobs": [],
            "ok": njobs if ok is None else ok, "failed": []}))
        return rc
    return _fn


class TestSubmitIdempotency(unittest.TestCase):
    def test_noop_when_cluster_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "submit_stage_prodtools") as sub, \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            (Path(tmp) / "poke_cluster.txt").write_text("123\n")
            pipeline.cmd_submit(SimpleNamespace(stage="poke", force=False,
                                                dry_run=False))
            sub.assert_not_called()

    def test_stamps_chain_then_submits_on_first_submit(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES", ("poke", "harvest2")), \
             mock.patch.object(pipeline, "submit_stage_prodtools") as sub, \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            pipeline.cmd_submit(SimpleNamespace(stage="poke", force=False,
                                                dry_run=False))
            stamp = Path(tmp) / hv.STAGE_CHAIN_STAMP
            self.assertTrue(stamp.exists())
            self.assertEqual(hv.stamped_stage_chain(Path(tmp)),
                             ["poke", "harvest2"])
            sub.assert_called_once()

    def test_existing_stamp_not_overwritten(self):
        # Stamp-once semantics: a legacy config resubmitted under a new env
        # keeps ITS chain (the ff11R00_07 +1.5% sob bias class).
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES", ("newchain",)), \
             mock.patch.object(pipeline, "submit_stage_prodtools"), \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            hv.stamp_stage_chain(Path(tmp), ["oldchain"])
            pipeline.cmd_submit(SimpleNamespace(stage="newchain", force=False,
                                                dry_run=False))
            self.assertEqual(hv.stamped_stage_chain(Path(tmp)), ["oldchain"])


class TestListOutputsGating(unittest.TestCase):
    def test_noop_when_outputs_listed_and_resolvable(self):
        # cmd_list_outputs' idempotency guard: when the listed paths already
        # resolve, it must skip re-deriving from state/<stage>_wait.json
        # (px.read_wait) entirely -- retired mu2ejobsub-era coverage used to
        # assert this against the module-level `list_outputs` glob-walker,
        # which cmd_list_outputs no longer calls at all (Task 3).
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline.px, "read_wait") as rw:
            f = Path(tmp) / "some.art"
            f.write_text("x")
            (Path(tmp) / "poke_outputs.txt").write_text(f"{f}\n")
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            rw.assert_not_called()

    def test_reglobs_when_listed_paths_vanished(self):
        # Re-derivation now reads state/<stage>_wait.json (prodtools_exec,
        # Task 3) instead of re-globbing /pnfs via list_outputs -- one code
        # path for grid and local.
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.dict(pipeline.STAGES,
                             {"poke": {"output_glob": "sim.*.art"}}):
            (Path(tmp) / "poke_outputs.txt").write_text(
                f"{tmp}/gone.art\n")
            (Path(tmp) / "poke_wait.json").write_text(json.dumps({
                "jobdef": "cnf.t.tar",
                "jobs": [{"index": 0, "rc": 0,
                         "outputs": ["/pnfs/out/1/sim.u.D.C.0.art"]}],
                "ok": 1, "failed": [],
            }))
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            self.assertEqual(
                (Path(tmp) / "poke_outputs.txt").read_text().strip(),
                "/pnfs/out/1/sim.u.D.C.0.art")


class TestStageTuning(unittest.TestCase):
    """core/mode_json.py `run.stage_tuning` -> pipeline.STAGES wiring (I4 in
    the json-configurable-modes final review). All tests operate on a local
    deepcopy of pipeline.STAGES, never the live module dict -- STAGES is
    shared mutable module state and mock.patch.dict only shallow-restores
    it, so mutating the nested per-stage dicts in place would leak into
    other tests."""

    def test_stage_tuning_lands_on_stages(self):
        local_stages = {
            "mubeam": {"events_per_job": 5000, "memory_mb": 2500, "quorum": 0.9},
            "mustops_ce": {"events_per_job": 2500},
        }
        pipeline._apply_stage_tuning(
            local_stages,
            {"mubeam": {"events_per_job": 200000, "memory_mb": 2000, "quorum": 0.8}})
        self.assertEqual(local_stages["mubeam"]["events_per_job"], 200000)
        self.assertEqual(local_stages["mubeam"]["memory_mb"], 2000)
        self.assertEqual(local_stages["mubeam"]["quorum"], 0.8)
        # Untouched: stage_tuning only had a "mubeam" key.
        self.assertEqual(local_stages["mustops_ce"]["events_per_job"], 2500)

    def test_stage_tuning_unknown_stage_name_rejected(self):
        with self.assertRaises(ValueError) as cm:
            pipeline._apply_stage_tuning({"mubeam": {}}, {"not_a_stage": {"memory_mb": 1}})
        self.assertIn("not_a_stage", str(cm.exception))

    def test_json_spec_stage_tuning_applies_to_real_stages(self):
        """End-to-end: the foilsflash fixture's run.stage_tuning (mirrors
        the live Python foilsflash mode's hardcoded values) actually lands
        on a copy of pipeline.STAGES for its stages."""
        from mode_json import load_mode_file  # noqa: E402 (bare, core/ on sys.path)
        fixture = Path(__file__).parent / "fixtures" / "modes" / "foilsflash.json"
        spec = load_mode_file(fixture)
        local_stages = copy.deepcopy(pipeline.STAGES)
        pipeline._apply_stage_tuning(local_stages, spec.stage_tuning)
        self.assertEqual(local_stages["mubeam"]["events_per_job"], 200000)
        self.assertEqual(local_stages["mustops_ce"]["events_per_job"], 75000)
        self.assertEqual(local_stages["elebeam_flash"]["events_per_job"], 110000)
        self.assertEqual(local_stages["mubeam"]["memory_mb"], 2000)
        self.assertEqual(local_stages["mubeam"]["quorum"], 0.8)

    def test_foilsflash_python_mode_stage_tuning_is_a_noop(self):
        """The Python foilsflash mode's stage_tuning is {} (core/modes.py);
        applying it must not touch STAGES at all -- the hardcoded
        AUTORESEARCH_MODE == "foilsflash" block (core/pipeline.py, above
        _apply_stage_tuning) owns that mode's tuning instead.

        R2 in the json-configurable-modes final review: the ORIGINAL version
        of this test built local_stages from copy.deepcopy(pipeline.STAGES)
        (whatever ambient values that happened to hold under the unittest
        process's AUTORESEARCH_MODE, which is normally unset -- so NOT the
        foilsflash hardcoded values at all) and asserted before == after
        applying {}. That is trivially true for ANY starting dict and ANY
        correct-or-broken _apply_stage_tuning, since updating with {} is a
        no-op regardless -- it never actually checked the hardcoded
        foilsflash tuning was present. This version seeds local_stages with
        those literal hardcoded values (mirroring the pipeline.py block) and
        asserts they are both PRESENT beforehand and UNMODIFIED afterward."""
        import modes as _modes  # noqa: E402 (bare, core/ on sys.path)
        local_stages = {
            "mubeam": {"events_per_job": 200000, "memory_mb": 2000, "quorum": 0.8},
            "mustops_ce": {"events_per_job": 75000, "memory_mb": 2000, "quorum": 0.8},
            "elebeam_flash": {"events_per_job": 110000, "memory_mb": 2000},
        }
        # Present beforehand (the premise this test is checking).
        self.assertEqual(local_stages["mubeam"]["events_per_job"], 200000)
        self.assertEqual(local_stages["mustops_ce"]["events_per_job"], 75000)
        self.assertEqual(local_stages["elebeam_flash"]["events_per_job"], 110000)

        pipeline._apply_stage_tuning(local_stages, _modes.SPECS["foilsflash"].stage_tuning)

        # Unmodified afterward.
        self.assertEqual(local_stages["mubeam"]["events_per_job"], 200000)
        self.assertEqual(local_stages["mustops_ce"]["events_per_job"], 75000)
        self.assertEqual(local_stages["elebeam_flash"]["events_per_job"], 110000)
        self.assertEqual(local_stages["mubeam"]["memory_mb"], 2000)
        self.assertEqual(local_stages["mubeam"]["quorum"], 0.8)


class TestStageTuningModuleLevelWiring(unittest.TestCase):
    """R2 in the json-configurable-modes final review: every test in
    TestStageTuning above calls `pipeline._apply_stage_tuning` directly on a
    local dict, so deleting the MODULE-LEVEL call in core/pipeline.py
    (~line 319, right after `_apply_stage_tuning` is defined) fails nothing
    in that class.

    This test genuinely exercises that module-level call: it hand-registers
    a throwaway ModeSpec carrying a non-empty run.stage_tuning directly into
    a fresh subprocess's `modes.SPECS` (bypassing mode_specs/ directory
    discovery entirely -- core/modes.py's MODES_DIR is a hardcoded path, not
    overridable via env, and the real mode_specs/ directory must stay
    clean), then imports core/pipeline.py under that mode and reads back the
    REAL module-level pipeline.STAGES dict. If the module-level
    `_apply_stage_tuning(STAGES, ...)` call is ever deleted, this fails."""

    def test_json_mode_stage_tuning_lands_on_real_stages_at_import(self):
        root = Path(__file__).resolve().parent.parent
        mode_name = f"stagetuningprobe{uuid.uuid4().hex[:8]}"
        doc = json.loads(
            (Path(__file__).parent / "fixtures" / "modes" / "foils.json").read_text())
        doc["name"] = mode_name
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_bo_{mode_name}.tsv"
        doc["run"]["stage_tuning"] = {"mubeam": {"events_per_job": 424242}}

        with tempfile.TemporaryDirectory() as td:
            tmp_json = Path(td) / f"{mode_name}.json"
            tmp_json.write_text(json.dumps(doc))
            script = (
                "import sys, os\n"
                "sys.path.insert(0, 'core')\n"
                "from pathlib import Path\n"
                "import modes\n"
                "from mode_json import load_mode_file\n"
                f"spec = load_mode_file(Path({str(tmp_json)!r}))\n"
                "modes.SPECS[spec.name] = spec\n"
                "os.environ['AUTORESEARCH_MODE'] = spec.name\n"
                "import pipeline\n"
                "print(pipeline.STAGES['mubeam']['events_per_job'])\n"
            )
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            r = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(root), capture_output=True, text=True,
                env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "424242")


class TestGetTokenMtimeGate(unittest.TestCase):
    """_maybe_refresh_token: run getToken only when the shared bearer token
    file is older than TOKEN_REFRESH_AGE_S (1h). Fail-open on unknown age.
    Spec: docs/superpowers/specs/2026-07-31-nfs-lock-mitigation-design.md."""

    def _token_file(self, age_s):
        d = tempfile.mkdtemp(prefix="tokgate_")
        p = Path(d) / "bt_u12345"
        p.write_text("header.payload.sig\n")
        past = time.time() - age_s
        os.utime(p, (past, past))
        return str(p)

    def _ok(self):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_fresh_token_skips_gettoken(self):
        p = self._token_file(120)
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash") as rt:
            pipeline._maybe_refresh_token("stageX")
        rt.assert_not_called()

    def test_old_token_refreshes(self):
        p = self._token_file(pipeline.TOKEN_REFRESH_AGE_S + 100)
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=self._ok()) as rt:
            pipeline._maybe_refresh_token("stageX")
        self.assertEqual(rt.call_count, 1)
        self.assertIn("getToken", rt.call_args[0][0])

    def test_missing_token_file_refreshes(self):
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": "/nonexistent/bt"}), \
             mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=self._ok()) as rt:
            pipeline._maybe_refresh_token("stageX")
        self.assertEqual(rt.call_count, 1)

    def test_gettoken_failure_still_raises(self):
        p = self._token_file(pipeline.TOKEN_REFRESH_AGE_S + 100)
        bad = SimpleNamespace(returncode=1, stdout="", stderr="denied")
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash", return_value=bad):
            with self.assertRaises(subprocess.CalledProcessError):
                pipeline._maybe_refresh_token("stageX")

    def test_token_age_inf_when_missing(self):
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": "/nonexistent/bt"}):
            self.assertEqual(pipeline._token_age_s(), float("inf"))


class TestStageEntries(unittest.TestCase):
    """stage_entries/<stage>.json / px.load_stage_entry / pipeline.
    _render_fcl_overrides / _stage_extra_files (Task 14, lifting Task 13's
    STAGE_FCL dict out to checked-in JSON, in json2jobdef's native entry
    schema): golden per-stage entry data (loaded through the real
    stage_entries/ tree -- no fixture dir, so a checked-in JSON typo fails
    this suite) + the two per-call substitution points ({geom} placeholder,
    mustops_ce's concat-less MaxEventsToSkip)."""

    def _entry(self, stage, *, cfg="x001", geom="autoresearch_x001_geom.txt"):
        return pipeline.px.load_stage_entry(stage, cfg=cfg, geom=geom)

    def test_every_stage_has_a_published_fcl_and_overrides_dict(self):
        for stage in pipeline.STAGES:
            with self.subTest(stage=stage):
                entry = self._entry(stage)
                self.assertTrue(entry["fcl"].startswith("Production/JobConfig/"))
                self.assertIsInstance(entry.get("fcl_overrides", {}), dict)

    def test_mubeam_include_key_is_first_and_carries_epilog_and_extras(self):
        overrides = self._entry("mubeam")["fcl_overrides"]
        self.assertEqual(list(overrides.keys())[0], "#include")
        self.assertEqual(
            overrides["#include"],
            ["Production/JobConfig/pileup/epilog_1b.fcl",
             "sim_kept_products_extras.fcl", "mubeam_targetstop_path.fcl"])

    def test_run1b_mubeam_include_key_is_first_and_carries_epilog_and_extras(self):
        overrides = self._entry("run1b_mubeam")["fcl_overrides"]
        self.assertEqual(list(overrides.keys())[0], "#include")
        self.assertEqual(
            overrides["#include"],
            ["Production/JobConfig/pileup/epilog_1b.fcl",
             "sim_kept_products_extras.fcl"])

    def test_both_resampler_stages_share_one_kept_products_file(self):
        # The dedupe's whole point (2026-08-17): the outputCommands blocks
        # were byte-identical in the two former per-stage extras files, so a
        # change to the kept-products shape had to be made twice or silently
        # diverge. Pin that they now name the SAME file, and that only
        # mubeam carries the targetStopPath override -- Run1B keeps the
        # published path.
        mubeam = self._entry("mubeam")["fcl_overrides"]["#include"]
        run1b = self._entry("run1b_mubeam")["fcl_overrides"]["#include"]
        shared = "sim_kept_products_extras.fcl"
        self.assertIn(shared, mubeam)
        self.assertIn(shared, run1b)
        self.assertIn("mubeam_targetstop_path.fcl", mubeam)
        self.assertNotIn("mubeam_targetstop_path.fcl", run1b)

    def test_concat_has_no_include_key_and_no_geom_key(self):
        # concat's base FCL (MuonStopSelector.fcl) had only ONE #include in
        # the old template -- nothing to carry as a '#include' override --
        # and no G4 stage, so no services.GeometryService key either.
        overrides = self._entry("concat")["fcl_overrides"]
        self.assertNotIn("#include", overrides)
        self.assertNotIn("services.GeometryService.inputFile", overrides)

    def test_mustops_ce_has_no_include_key(self):
        # mustops_ce's base FCL (CeEndpoint.fcl) also had only one #include.
        overrides = self._entry("mustops_ce")["fcl_overrides"]
        self.assertNotIn("#include", overrides)

    def test_elebeam_flash_include_key_is_epilog_only_no_extras(self):
        # elebeam_flash has no @sequence::-bearing override -- its
        # '#include' key carries only epilog_1b.fcl, as a bare string (not
        # a list), unlike mubeam/run1b_mubeam.
        overrides = self._entry("elebeam_flash")["fcl_overrides"]
        self.assertEqual(list(overrides.keys())[0], "#include")
        self.assertEqual(overrides["#include"],
                         "Production/JobConfig/pileup/epilog_1b.fcl")

    def test_cat_resampler_stages_never_carry_max_events_to_skip(self):
        # mubeam/run1b_mubeam/elebeam_flash resample a static SAM Cat
        # dataset -- json2jobdef auto-computes MaxEventsToSkip and appends
        # it as a post_line that beats fcl_overrides, so carrying the old
        # templates' hardcoded 319542 forward would be a silent lie.
        for stage in ("mubeam", "run1b_mubeam", "elebeam_flash"):
            with self.subTest(stage=stage):
                overrides = self._entry(stage)["fcl_overrides"]
                self.assertFalse(
                    any(k.endswith("MaxEventsToSkip") for k in overrides),
                    f"{stage} fcl_overrides must not carry MaxEventsToSkip "
                    f"-- the SAM auto-compute post_line always wins anyway")

    def test_mustops_ce_carries_max_events_to_skip(self):
        # mustops_ce IS a dir:-inloc resampler -- json2jobdef's auto-compute
        # is skipped for dir: input_data, so this value MUST ride
        # fcl_overrides or art aborts at ResamplingMixer construction.
        overrides = self._entry("mustops_ce")["fcl_overrides"]
        self.assertEqual(
            overrides["physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"],
            100720)

    def test_every_stage_json_carries_the_static_entry_fields(self):
        # resampler_name/input_data/inloc/outloc/run/memory/events: whatever
        # subset each stage's real json2jobdef entry needs (Task 13's
        # per-stage transcription table -- see task-13-report.md).
        expect = {
            "mubeam": {"resampler_name": "beamResampler",
                      "input_data": {"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                      "inloc": "tape", "run": 1800, "events": 5000},
            "run1b_mubeam": {"resampler_name": "beamResampler",
                            "input_data": {"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                            "inloc": "tape", "run": 1810, "events": 5000},
            "concat": {"inloc": "disk"},
            "mustops_ce": {"resampler_name": "TargetStopResampler",
                          "inloc": "disk", "run": 1801, "memory": 3000,
                          "events": 2500},
            "elebeam_flash": {"resampler_name": "beamResampler",
                              "input_data": {"sim.mu2e.EleBeamCat.Run1Baa.art": 1},
                              "inloc": "tape", "run": 1803, "memory": 3000,
                              "events": 2500},
        }
        for stage, fields in expect.items():
            with self.subTest(stage=stage):
                entry = self._entry(stage)
                for key, val in fields.items():
                    self.assertEqual(entry.get(key), val,
                                     f"{stage}[{key}]")
                self.assertEqual(
                    entry["outloc"], {"*.art": "outstage", "*.root": "outstage"})

    def test_concat_and_mustops_ce_have_no_run_or_events_default(self):
        # concat has neither (no G4, no run number); mustops_ce's input_data
        # is always staged (no static Cat dataset).
        self.assertNotIn("run", self._entry("concat"))
        self.assertNotIn("events", self._entry("concat"))
        self.assertNotIn("input_data", self._entry("concat"))
        self.assertNotIn("input_data", self._entry("mustops_ce"))
        self.assertNotIn("resampler_name", self._entry("concat"))

    def test_load_stage_entry_substitutes_geom_placeholder(self):
        entry = pipeline.px.load_stage_entry(
            "mubeam", cfg="x001", geom="autoresearch_x001_geom.txt")
        self.assertEqual(entry["fcl_overrides"]["services.GeometryService.inputFile"],
                         "autoresearch_x001_geom.txt")
        # concat has no geom key to substitute -- a no-op, not an error.
        self.assertNotIn(
            "services.GeometryService.inputFile",
            pipeline.px.load_stage_entry(
                "concat", cfg="x001", geom="g.txt")["fcl_overrides"])

    def test_render_fcl_overrides_substitutes_the_geom_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            geom = Path(tmp) / "autoresearch_x001_geom.txt"
            with mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "STATE", Path(tmp)):
                overrides = pipeline._render_fcl_overrides("mubeam")
        self.assertEqual(overrides["services.GeometryService.inputFile"],
                         "autoresearch_x001_geom.txt")

    def test_render_fcl_overrides_never_mutates_the_checked_in_json(self):
        # px.load_stage_entry rebuilds fresh from disk every call (no cached
        # shared object) -- one caller's substitution must never leak into
        # another's, or into the file on disk.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "GEOM_FILE", Path(tmp) / "g.txt"), \
                 mock.patch.object(pipeline, "STATE", Path(tmp)):
                pipeline._render_fcl_overrides("mubeam")
                second = pipeline._render_fcl_overrides("mubeam")
        self.assertEqual(second["services.GeometryService.inputFile"], "g.txt")
        raw = json.loads(
            (pipeline.px.STAGE_ENTRIES_DIR / "mubeam.json").read_text())
        self.assertEqual(
            raw["fcl_overrides"]["services.GeometryService.inputFile"],
            "{geom}")

    def test_render_fcl_overrides_mustops_ce_concatless_toggle(self):
        key = "physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "GEOM_FILE", Path(tmp) / "g.txt"), \
                 mock.patch.object(pipeline, "STATE", Path(tmp)), \
                 mock.patch.object(pipeline, "CONCATLESS", False):
                self.assertEqual(
                    pipeline._render_fcl_overrides("mustops_ce")[key], 100720)
            with mock.patch.object(pipeline, "GEOM_FILE", Path(tmp) / "g.txt"), \
                 mock.patch.object(pipeline, "STATE", Path(tmp)), \
                 mock.patch.object(pipeline, "CONCATLESS", True):
                self.assertEqual(
                    pipeline._render_fcl_overrides("mustops_ce")[key], 8000)

    def test_stage_extra_files_only_mubeam_and_run1b_mubeam(self):
        # Derived from the entry's '#include' (bare basenames ship,
        # published Production/... paths don't), so the JSON is the single
        # declaration of "this stage needs this extra include".
        for stage in pipeline.STAGES:
            with self.subTest(stage=stage):
                extras = pipeline._stage_extra_files(self._entry(stage))
                # mubeam ships two since the 2026-08-17 dedupe (the shared
                # kept-products file + its own targetStopPath); run1b_mubeam
                # ships only the shared one.
                expected = {"mubeam": 2, "run1b_mubeam": 1}.get(stage, 0)
                self.assertEqual(len(extras), expected)
                for f in extras:
                    self.assertTrue(f.exists(), f"{f} must exist on disk")
                    self.assertIn("@sequence::", f.read_text())

    def test_extras_fcl_basenames_match_the_include_key_in_order(self):
        # Every bare basename in '#include' must ship, in the same order:
        # FHiCL is last-wins, so a shipped-but-reordered include could
        # silently change which override survives. Published Production/...
        # paths resolve from the release and ship nothing.
        for stage in ("mubeam", "run1b_mubeam"):
            with self.subTest(stage=stage):
                entry = self._entry(stage)
                inc = entry["fcl_overrides"]["#include"]
                self.assertEqual(
                    [f.name for f in pipeline._stage_extra_files(entry)],
                    [i for i in inc if "/" not in i])

    def test_stage_extra_files_string_include_and_missing_overrides(self):
        # A single-string '#include' (elebeam_flash's shape) and an entry
        # with no fcl_overrides at all must both work.
        self.assertEqual(
            pipeline._stage_extra_files({"fcl_overrides":
                                         {"#include": "a/published.fcl"}}),
            [])
        self.assertEqual(pipeline._stage_extra_files({}), [])

    def test_stages_never_carry_the_dead_pre_task14_fields(self):
        # run_number/memory_mb/default_loc/ships_geom/auxinput all moved to
        # stage_entries/<stage>.json (or were dropped as dead -- see the
        # comment above STAGES); a regression that reintroduces one of
        # these onto STAGES defeats the point of the shrink.
        for stage, cfg in pipeline.STAGES.items():
            with self.subTest(stage=stage):
                for dead in ("run_number", "default_loc", "ships_geom",
                            "auxinput"):
                    self.assertNotIn(dead, cfg)


class TestWriteCodeTarballExtraFiles(unittest.TestCase):
    """write_code_tarball's extra_files param (prodtools switch, Task 4;
    Task 13 changed WHAT ships here -- a static mubeam/run1b_mubeam extras
    fcl instead of a per-config materialized template -- but not the
    mechanism): ships extra files beside the geom in Code/, the same
    search-path mechanism the geom already uses. Staleness for extra_files
    is CONTENT-based (_extra_files_digest), not mtime -- see that function's
    docstring for why an mtime-only gate can't distinguish "same stage,
    reuse" from "different stage, must rebuild" (review finding 1,
    2026-08-16). Real tar/bzip2 subprocess calls only -- no grid contact."""

    def _make_base_tarball(self, tmp):
        src = Path(tmp) / "basesrc"
        (src / "Code").mkdir(parents=True)
        (src / "Code" / "setup.sh").write_text("# stub\n")
        base = Path(tmp) / "Code.base.tar.bz2"
        subprocess.run(
            ["bash", "-c", f"cd {src} && tar cf - Code/ | bzip2 > {base}"],
            check=True)
        return base

    def _tar_listing(self, cnf):
        return subprocess.run(["tar", "tjf", str(cnf)], capture_output=True,
                              text=True, check=True).stdout

    def test_extra_files_land_in_the_shipped_code_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir = root / "mubeam"
            stage_dir.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            extra = root / "mubeam_extras.fcl"
            extra.write_text('#include "geom.txt"\n')
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                cnf = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra])
            listing = self._tar_listing(cnf)
        self.assertIn("Code/mubeam_extras.fcl", listing)
        self.assertIn("Code/geom.txt", listing)

    def test_a_cache_missing_a_newer_extra_file_is_rebuilt_not_reused(self):
        # Pre-I1, the cache-freshness gate keyed the cache PATH only on
        # (config, base_tarball) -- so stage A's submit (no extras) and
        # stage B's submit (an extras fcl) fought over the SAME cache file,
        # each rebuild silently evicting the other's. I1 (2026-08-16 review)
        # folds the extras digest into the cache FILENAME instead, so A and
        # B now land in different cache files by construction and neither
        # ever gets shipped missing its own extras -- see
        # test_two_stages_with_different_extras_cache_independently for the
        # thrash-elimination half of this fix.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir = root / "mubeam"
            stage_dir.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                # Stage A's submit: no extra_files.
                cnf_a = pipeline.write_code_tarball(stage_dir, base_tarball=base)
                # Stage B's submit: an extras fcl not yet cached under ANY
                # name -- must build its own cache file, not overwrite A's.
                extra_b = root / "run1b_mubeam_extras.fcl"
                extra_b.write_text('#include "geom.txt"\n')
                cnf_b = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra_b])
            self.assertNotEqual(cnf_a, cnf_b)  # I1: distinct cache files
            self.assertTrue(cnf_a.exists())    # A's cache untouched by B's build
            listing_a = self._tar_listing(cnf_a)
            listing_b = self._tar_listing(cnf_b)
        self.assertNotIn("Code/run1b_mubeam_extras.fcl", listing_a)
        self.assertIn("Code/run1b_mubeam_extras.fcl", listing_b)

    def test_two_stages_with_different_extras_cache_independently(self):
        # I1 [Important]: pre-fix, the per-config cache filename was
        # `Code.<base>.tar.bz2` regardless of extra_files -- ONE name shared
        # by every stage in a config, so mubeam's submit (extras=
        # mubeam_extras.fcl) and mustops_ce's submit (no extras) evicted and
        # rebuilt each other's cache on every submit within a config
        # (~7-12 min of unpack+rebzip2 lost nearly every stage). Folding the
        # extras digest into the filename (_cache_token) gives each variant
        # its own cache slot: assert two different-extras builds land at
        # different paths AND each reuses (no tar/bzip2 re-invoked) on a
        # same-extras repeat.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir_a = root / "mubeam"
            stage_dir_a.mkdir(parents=True)
            stage_dir_b = root / "mustops_ce"
            stage_dir_b.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            extra_a = root / "mubeam_extras.fcl"
            extra_a.write_text('#include "geom.txt"\n')
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                # mubeam-shaped submit (extras), then mustops_ce-shaped
                # submit (no extras) for the SAME config -- the exact
                # sequence that thrashed pre-fix.
                cnf_mubeam_1 = pipeline.write_code_tarball(
                    stage_dir_a, base_tarball=base, extra_files=[extra_a])
                cnf_mustops_1 = pipeline.write_code_tarball(
                    stage_dir_b, base_tarball=base)
                self.assertNotEqual(cnf_mubeam_1, cnf_mustops_1)
                self.assertTrue(cnf_mubeam_1.exists())
                self.assertTrue(cnf_mustops_1.exists())
                # A second submit of EACH must reuse its own cache -- no
                # tar/bzip2 invocation for either.
                with mock.patch.object(pipeline, "run",
                                       wraps=pipeline.run) as run_spy:
                    cnf_mubeam_2 = pipeline.write_code_tarball(
                        stage_dir_a, base_tarball=base,
                        extra_files=[extra_a])
                    cnf_mustops_2 = pipeline.write_code_tarball(
                        stage_dir_b, base_tarball=base)
                run_spy.assert_not_called()
            self.assertEqual(cnf_mubeam_1, cnf_mubeam_2)
            self.assertEqual(cnf_mustops_1, cnf_mustops_2)

    def test_identical_extra_files_content_reuses_the_cache(self):
        # The staleness signal must be CONTENT, not mtime: a real resubmit
        # re-passes the SAME static extras fcl path (_stage_extra_files) on
        # every call -- an mtime-only gate would see that file's on-disk
        # mtime never changes between submits either, which happens to work
        # today only by accident (mtime-based freshness is still wrong in
        # general -- see _extra_files_digest's docstring) and would
        # silently reintroduce the full unpack+rebzip2 cost the moment
        # anything touched the extras fcl's mtime without changing its
        # content (e.g. a checkout/rsync). Proven here by spying on the
        # module-level `run` helper (the only thing that shells out to
        # tar/bzip2): a second call whose extra_files basename+bytes are
        # byte-identical to the first must NOT invoke it again.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir = root / "mubeam"
            stage_dir.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            extra = root / "mubeam_extras.fcl"
            extra.write_text('#include "geom.txt"\n')
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                cnf_1 = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra])
                with mock.patch.object(pipeline, "run",
                                       wraps=pipeline.run) as run_spy:
                    # Same basename, same bytes -- exactly what a real
                    # resubmit's _stage_extra_files(entry) call produces
                    # (the identical static file, every time).
                    extra.write_text('#include "geom.txt"\n')
                    cnf_2 = pipeline.write_code_tarball(
                        stage_dir, base_tarball=base, extra_files=[extra])
                run_spy.assert_not_called()
            self.assertEqual(cnf_1, cnf_2)


class TestSubmitStageProdtools(unittest.TestCase):
    """submit_stage_prodtools (prodtools switch, Task 4): entry ->
    json2jobdef -> submit_entry, writing the same state files the retired
    mu2ejobsub path wrote plus the new jobsub id. build_cnf/submit_cnf
    themselves are unit-tested against injected runners in
    tests/test_prodtools_exec.py; here they're faked wholesale (the brief's
    "touch the expected cnf path" / "emit SUBMIT_RESULT" fakes) so this test
    is about the STATE FILES submit_stage_prodtools writes, not prodtools'
    own argv shape."""

    def test_state_files_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            def fake_submit_cnf(stage_dir, entry_path, ledger_db, origin,
                                env, runner=None, dry_run=False):
                self.submit_args = (stage_dir, entry_path, ledger_db, origin)
                return 86123999, "86123999@jobsub01.fnal.gov"

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   side_effect=fake_submit_cnf):
                cluster = pipeline.submit_stage_prodtools("mubeam", {})

            self.assertEqual(cluster, 86123999)
            self.assertEqual(
                (state / "mubeam_cluster.txt").read_text().strip(),
                "86123999")
            self.assertEqual(
                (state / "mubeam_jobsub_id.txt").read_text().strip(),
                "86123999@jobsub01.fnal.gov")
            self.assertEqual(
                (state / "mubeam_events_per_job.txt").read_text().strip(),
                str(pipeline.STAGES["mubeam"]["events_per_job"]))
            self.assertTrue((state / "mubeam_config_sha.txt").exists())

            entry = json.loads((state / "mubeam_entry.json").read_text())[0]
            self.assertEqual(entry["desc"], "Run1A_MuBeam_cfg001")
            self.assertEqual(entry["dsconf"], "Run1Bak_cfg001")
            # `fcl` is the PUBLISHED Production FCL path (Task 13), not a
            # per-config materialized basename.
            self.assertEqual(entry["fcl"],
                             "Production/JobConfig/pileup/MuBeamResampler.fcl")
            self.assertEqual(entry["code"], str(Path(tmp) / "Code.tar.bz2"))
            # `events` comes from whatever mode's stage_tuning is live at
            # import time (foilsflash's tuning overrides the base 5000 in a
            # normal test run) -- assert against the live STAGES dict, not
            # the module's base literal, same convention as
            # TestCmdSubmitLocalViaRunlocal below. `run` is never
            # stage_tuning-tunable (not in mode_json._STAGE_TUNING_KEYS) --
            # it's the static stage_entries/mubeam.json default.
            self.assertEqual(entry["events"],
                             pipeline.STAGES["mubeam"]["events_per_job"])
            self.assertEqual(entry["run"], 1800)
            self.assertEqual(entry["resampler_name"], "beamResampler")
            self.assertEqual(
                entry["input_data"], {"sim.mu2e.MuBeamCat.Run1Baa.art": 1})
            self.assertEqual(entry["inloc"], "tape")

            # fcl_overrides: '#include' is FIRST (write_fcl_template dict
            # order), carries both epilog_1b.fcl and the extras fcl; the
            # geom sentinel is substituted with the real basename; the
            # physics-list override survives; MaxEventsToSkip is
            # DELIBERATELY absent (Cat-resampler auto-compute post_line
            # beats it -- see the mubeam.json comment block above pipeline._render_fcl_overrides).
            overrides = entry["fcl_overrides"]
            self.assertEqual(list(overrides.keys())[0], "#include")
            self.assertEqual(
                overrides["#include"],
                ["Production/JobConfig/pileup/epilog_1b.fcl",
                 "sim_kept_products_extras.fcl",
                 "mubeam_targetstop_path.fcl"])
            self.assertEqual(
                overrides["services.GeometryService.inputFile"],
                "autoresearch_cfg001_geom.txt")
            self.assertEqual(
                overrides["physics.producers.g4run.physics.physicsListName"],
                "FTFP_BERT")
            self.assertNotIn(
                "physics.filters.beamResampler.mu2e.MaxEventsToSkip",
                overrides)

            # LEDGER_DB threaded through to submit_cnf, origin identifies
            # the (config, stage) for the ledger row.
            _, _, ledger_db, origin = self.submit_args
            self.assertEqual(ledger_db, Path(tmp) / "ledger" / "submissions.db")
            self.assertEqual(origin, "autoresearch:cfg001/mubeam")

    def test_no_materialized_fcl_is_written_anywhere_under_state(self):
        # Task 13: _materialize_template and the __GEOM_FILE__ text
        # substitution it did are gone -- nothing under STATE should ever
        # be named *_template_materialized.fcl again.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools("mubeam", {})

            materialized = list(root.rglob("*_template_materialized.fcl"))
            self.assertEqual(materialized, [])
            self.assertFalse(hasattr(pipeline, "_materialize_template"))

    def test_mubeam_submit_ships_the_extras_fcl_via_write_code_tarball(self):
        # The mubeam entry test the brief asks for: the extras fcl rides
        # '#include' (checked in test_state_files_written) AND is actually
        # in the tarball's extra_files -- spy on write_code_tarball to
        # check what submit_stage_prodtools passes it, not just what
        # _stage_extra_files returns in isolation.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")
            seen_extra_files = []

            def fake_write_code_tarball(stage_dir, base_tarball=None,
                                        extra_files=None):
                seen_extra_files.append(extra_files)
                return Path(tmp) / "Code.tar.bz2"

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   side_effect=fake_write_code_tarball), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools("mubeam", {})

            self.assertEqual(len(seen_extra_files), 1)
            self.assertEqual(
                [p.name for p in seen_extra_files[0]],
                ["sim_kept_products_extras.fcl",
                 "mubeam_targetstop_path.fcl"])

    def test_mustops_ce_concatless_overrides_max_events_to_skip_to_8000(self):
        # Folded-in from the old _materialize_template's stamp-first
        # conditional (concat-less chains resample ONE mubeam file instead
        # of the merged concat file, so the random skip must stay below the
        # smallest plausible file -- see the mustops_ce.json comment block above pipeline._render_fcl_overrides).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            staged_dir = Path(tmp) / "staged" / "mustops_ce"

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools(
                    "mustops_ce", {},
                    staged_inputs=(staged_dir, {"sim.a.art": 1}))

            entry = json.loads(
                (state / "mustops_ce_entry.json").read_text())[0]
            self.assertEqual(
                entry["fcl_overrides"][
                    "physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"],
                8000)

    def test_staged_inputs_feed_input_data_and_inloc(self):
        # mustops_ce / concat shape: staged_inputs=(dir, {basename: count})
        # replaces the static Cat-dataset input_data with the hard-linked
        # farm's basenames, and inloc becomes dir:<staged_dir>.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            staged_dir = Path(tmp) / "staged" / "mustops_ce"

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            def fake_submit_cnf(*a, **kw):
                return 1, "1@s"

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "CONCATLESS", False), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   side_effect=fake_submit_cnf):
                pipeline.submit_stage_prodtools(
                    "mustops_ce", {},
                    staged_inputs=(staged_dir, {"sim.a.art": 1, "sim.b.art": 1}))

            entry = json.loads(
                (state / "mustops_ce_entry.json").read_text())[0]
            self.assertEqual(entry["input_data"],
                             {"sim.a.art": 1, "sim.b.art": 1})
            self.assertEqual(entry["inloc"], f"dir:{staged_dir}")
            self.assertEqual(entry["resampler_name"], "TargetStopResampler")
            self.assertEqual(entry["fcl"],
                             "Production/JobConfig/primary/CeEndpoint.fcl")
            # mustops_ce is a dir:-inloc resampler -- no auto-compute
            # post_line, so MaxEventsToSkip MUST ride fcl_overrides (unlike
            # mubeam above). No stage-chain stamp exists in this fresh
            # STATE, so the module-level CONCATLESS fallback (forced False
            # above) decides: a concat-bearing chain keeps 100720.
            self.assertEqual(
                entry["fcl_overrides"][
                    "physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"],
                100720)

    def test_build_cnf_env_carries_templates_root_on_fhicl_file_path(self):
        # Task 11 empirical finding (docs/superpowers/sdd/
        # 2026-08-16-prodtools-switch/task-11-report.md, finding 1): real
        # json2jobdef writes its own wrapper template.fcl and resolves every
        # #include via fhicl-get, which consults ONLY $FHICL_FILE_PATH --
        # confirmed by direct reproduction that fhicl-get does NOT fall back
        # to cwd, even though build_cnf's subprocess cwd is the stage dir.
        # Since Task 13, the bare-basename include that needs this is the
        # mubeam/run1b_mubeam extras fcl (stage_entries/<stage>.json's '#include' key), which
        # lives permanently in TEMPLATES_ROOT, not a per-config STATE dir.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            seen_envs = []

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                seen_envs.append(env)
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            def fake_submit_cnf(*a, **kw):
                return 1, "1@s"

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   side_effect=fake_submit_cnf):
                pipeline.submit_stage_prodtools(
                    "mubeam", {"FHICL_FILE_PATH": "/some/other/path"})

            self.assertEqual(len(seen_envs), 1)
            fcl_path = seen_envs[0]["FHICL_FILE_PATH"]
            self.assertEqual(fcl_path.split(":")[0], str(pipeline.TEMPLATES_ROOT))
            # the incoming env's own FHICL_FILE_PATH is preserved, not
            # clobbered -- just prepended to.
            self.assertIn("/some/other/path", fcl_path)

    def test_stage_tuning_memory_override_flows_into_the_rendered_entry(self):
        # memory_mb moved OUT of STAGES' static literals (Task 14) --
        # _apply_stage_tuning's dict.update() still works on a stage dict
        # that never had the key (see core/mode_json.py
        # _STAGE_TUNING_KEYS): stage_tuning={"mustops_ce":
        # {"memory_mb": 4200}} injects it, and that tuned value must win
        # over stage_entries/mustops_ce.json's static default (3000).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            tuned_cfg = dict(pipeline.STAGES["mustops_ce"])
            pipeline._apply_stage_tuning(
                {"mustops_ce": tuned_cfg}, {"mustops_ce": {"memory_mb": 4200}})
            self.assertEqual(tuned_cfg["memory_mb"], 4200)  # sanity

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "STAGES",
                                   {**pipeline.STAGES,
                                    "mustops_ce": tuned_cfg}), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "CONCATLESS", False), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools(
                    "mustops_ce", {},
                    staged_inputs=(Path(tmp) / "staged", {"sim.a.art": 1}))

            entry = json.loads(
                (state / "mustops_ce_entry.json").read_text())[0]
            self.assertEqual(entry["memory"], "4200MB")

    def test_untuned_memory_falls_back_to_the_stage_entries_json_default(self):
        # Same shape, no tuning: STAGES carries no memory_mb key at all for
        # a stage never mentioned in a mode's stage_tuning, so the entry
        # must fall back to stage_entries/mustops_ce.json's static "memory".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            untuned_cfg = {k: v for k, v in pipeline.STAGES["mustops_ce"].items()
                          if k != "memory_mb"}
            self.assertNotIn("memory_mb", untuned_cfg)  # sanity

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "STAGES",
                                   {**pipeline.STAGES,
                                    "mustops_ce": untuned_cfg}), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "CONCATLESS", False), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools(
                    "mustops_ce", {},
                    staged_inputs=(Path(tmp) / "staged", {"sim.a.art": 1}))

            entry = json.loads(
                (state / "mustops_ce_entry.json").read_text())[0]
            self.assertEqual(entry["memory"], "3000MB")  # stage_entries default

    def test_events_falls_back_to_the_stage_entries_json_default_when_stages_lacks_it(self):
        # mubeam always carries events_per_job in STAGES today, so this
        # fallback is dormant in normal operation -- exercise it directly
        # by mocking a STAGES entry that (hypothetically) doesn't.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")
            no_events_cfg = {k: v for k, v in pipeline.STAGES["mubeam"].items()
                             if k != "events_per_job"}
            self.assertNotIn("events_per_job", no_events_cfg)  # sanity

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "STAGES",
                                   {**pipeline.STAGES, "mubeam": no_events_cfg}), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools("mubeam", {})

            entry = json.loads((state / "mubeam_entry.json").read_text())[0]
            self.assertEqual(entry["events"], 5000)  # stage_entries default

    def test_stage_entries_outloc_flows_into_the_rendered_entry(self):
        # Review finding (task-14 fix round): outloc was in every
        # stage_entries/<stage>.json but render_entry hardcoded its own
        # literal and neither call site read entry_tmpl["outloc"] -- editing
        # the JSON's outloc silently did nothing. Prove a changed outloc in
        # a (fixture) stage entry actually lands in the RENDERED entry, not
        # just the loaded template (TestStageEntries only checked the latter).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")

            entries_dir = Path(tmp) / "stage_entries"
            entries_dir.mkdir()
            custom_outloc = {"*.art": "tape", "*.root": "disk"}
            (entries_dir / "mubeam.json").write_text(json.dumps({
                "fcl": "Production/JobConfig/pileup/MuBeamResampler.fcl",
                "outloc": custom_outloc,
            }))

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline.px, "STAGE_ENTRIES_DIR", entries_dir), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools("mubeam", {})

            entry = json.loads((state / "mubeam_entry.json").read_text())[0]
            self.assertEqual(entry["outloc"], custom_outloc)

    def test_local_branch_stage_entries_outloc_also_flows_into_the_entry(self):
        # Same finding, the OTHER call site (cmd_submit's --local branch).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            entries_dir = Path(tmp) / "stage_entries"
            entries_dir.mkdir()
            custom_outloc = {"*.art": "scratch", "*.root": "outstage"}
            (entries_dir / "mubeam.json").write_text(json.dumps({
                "fcl": "Production/JobConfig/pileup/MuBeamResampler.fcl",
                "outloc": custom_outloc,
            }))

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / "cnf.x.tar"
                cnf.parent.mkdir(parents=True, exist_ok=True)
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={"X": "1"}), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline.px, "STAGE_ENTRIES_DIR", entries_dir), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()):
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))

            entry = json.loads((state / "mubeam_entry.json").read_text())[0]
            self.assertEqual(entry["outloc"], custom_outloc)

    def test_submit_stage_prodtools_loads_the_stage_entry_only_once(self):
        # _render_fcl_overrides now takes the caller's already-loaded
        # entry_tmpl instead of reloading -- pin the call count so this
        # doesn't regress back to two disk reads per submit.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            geom = root / "geom" / "autoresearch_cfg001_geom.txt"
            geom.parent.mkdir(parents=True)
            geom.write_text("geom\n")

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.touch()
                return cnf

            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "DSCONF", "Run1Bak_cfg001"), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom), \
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "load_stage_entry",
                                   wraps=pipeline.px.load_stage_entry) as spy, \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   return_value=(1, "1@s")):
                pipeline.submit_stage_prodtools("mubeam", {})

            self.assertEqual(spy.call_count, 1)


class TestCmdSubmitGridConsumingStageStaging(unittest.TestCase):
    """cmd_submit's grid concat/mustops_ce branches: stage_hardlink_farm is
    kept verbatim (mocked out here -- its own behavior is untested by this
    class), but the input_map built around it must carry the CLAMPED merge
    factor (Task 7 controller resolution #2): mu2ejobdef used to yield ZERO
    jobs when the merge factor exceeded the input count, and prodtools'
    behavior at that corner is unvalidated, so cmd_submit clamps as a guard.
    """

    def test_concat_input_map_clamps_merge_factor_to_source_count(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES",
                               ("mubeam", "concat", "mustops_ce")), \
             mock.patch.object(pipeline, "sourced_env", return_value={}), \
             mock.patch.object(pipeline, "submit_stage_prodtools") as sub, \
             mock.patch.object(pipeline, "stage_hardlink_farm",
                               return_value=Path("/pnfs/x/concat")) as farm:
            sources = [f"/pnfs/mu2e/x/sim.a{i}.art" for i in range(3)]
            (Path(tmp) / "mubeam_outputs.txt").write_text(
                "\n".join(sources) + "\n")
            pipeline.cmd_submit(SimpleNamespace(stage="concat", force=False,
                                                dry_run=False))
            farm.assert_called_once()
            _, kwargs = sub.call_args
            staged_dir, input_map = kwargs["staged_inputs"]
            self.assertEqual(staged_dir, Path("/pnfs/x/concat"))
            # merge_factor is 200 by default; clamped to the 3 sources.
            self.assertEqual(input_map,
                             {Path(s).name: 3 for s in sources})

    def test_mustops_ce_input_map_values_are_all_one(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES",
                               ("mubeam", "concat", "mustops_ce")), \
             mock.patch.object(pipeline, "sourced_env", return_value={}), \
             mock.patch.object(pipeline, "submit_stage_prodtools") as sub, \
             mock.patch.object(pipeline, "stage_hardlink_farm",
                               return_value=Path("/pnfs/x/mustops_ce")):
            sources = [f"/pnfs/mu2e/x/sim.a{i}.art" for i in range(4)]
            (Path(tmp) / "concat_outputs.txt").write_text(
                "\n".join(sources) + "\n")
            pipeline.cmd_submit(SimpleNamespace(stage="mustops_ce",
                                                force=False, dry_run=False))
            _, kwargs = sub.call_args
            _, input_map = kwargs["staged_inputs"]
            self.assertEqual(set(input_map.values()), {1})
            self.assertEqual(len(input_map), 4)


class TestRequireLocalStage(unittest.TestCase):
    """pipeline._require_local_stage: the three refusals shared by
    cmd_submit's --local branch (its sole caller since local-build/
    local-run were retired in the prodtools-switch deletion sweep) --
    stage support, config-bound, and grid-cluster overwrite. Ported from
    tests/test_local_exec.py (TestLocalRefusesToClobberAGridCluster plus
    the two local-build/local-run refusal tests, now calling the helper
    directly instead of through a dead verb)."""

    def test_a_real_cluster_id_with_no_marker_is_refused(self):
        # Both a local submit and a direct call overwrite <stage>_cluster.txt
        # AND the events-per-job stamp harvest divides by, so running local
        # over a finished grid stage rewrites that Eval's provenance and
        # loses the cluster id.
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

    def test_unsupported_stage_is_refused(self):
        # Every stage in STAGES is supported today, so pin the GATE rather
        # than a particular stage -- a stage added to STAGES later must be
        # opted in deliberately, not inherited. This matters because a local
        # submit writes state/<stage>_cluster.txt: a runid parked there trips
        # cmd_submit's idempotency guard and silently suppresses a REAL grid
        # submit of that stage.
        with mock.patch.object(pipeline, "LOCAL_SUPPORTED_STAGES",
                               ("mubeam",)), \
             self.assertRaises(SystemExit):
            pipeline._require_local_stage("concat")

    def test_refuses_when_no_config_is_bound(self):
        # STATE's unbound default is Path() -- the CURRENT DIRECTORY. Reaching
        # this without _bind_config scatters <stage>_cluster.txt, _local.txt,
        # _outputs.txt and a materialized template into cwd, which is how
        # they first landed in the repo root.
        with mock.patch.object(pipeline, "CONFIG", ""), \
             self.assertRaises(SystemExit) as cm:
            pipeline._require_local_stage("mubeam")
        self.assertIn("no config bound", str(cm.exception))


class TestSourcedEnvGuards(unittest.TestCase):
    """pipeline.sourced_env: shell-function parsing + the pre-sourced-shell
    refusal. Ported verbatim from tests/test_local_exec.py."""

    def test_sourced_env_keeps_exported_shell_functions_whole(self):
        # `muse` is a bash FUNCTION, not a binary, and a local job needs it:
        # runlocal runs `bash -c 'source Code/setup.sh && mu2e ...'` and that
        # script's line 4 is `muse setup ...`. Its exported form spans
        # multiple LINES, so sourced_env reads NUL-delimited `env -0` records
        # -- a line-based read would truncate the body at the newline (child
        # shells then reject it: "syntax error: unexpected end of file") or,
        # if dropped outright, kill the job rc=127 "muse: command not found".
        out = ("PATH=/usr/bin\0"
               "BASH_FUNC_muse%%=() {  source ${MUSE_DIR}/bin/muse\n}\0"
               "MU2E_SEARCH_PATH=/cvmfs/x\0")
        with mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout=out, stderr="")):
            env = pipeline.sourced_env()
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["MU2E_SEARCH_PATH"], "/cvmfs/x")
        self.assertEqual(env["BASH_FUNC_muse%%"],
                         "() {  source ${MUSE_DIR}/bin/muse\n}")

    def test_sourced_env_asks_for_nul_delimited_records(self):
        # The whole-function guarantee above rests on `env -0`; a plain `env`
        # cannot distinguish a value's second line from the next variable.
        with mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout="", stderr="")) as rsb:
            pipeline.sourced_env()
        self.assertTrue(rsb.call_args[0][0].rstrip().endswith("env -0"))

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


class TestStampLocalEvents(unittest.TestCase):
    def test_events_stamp_carries_the_local_value_not_the_configured_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state):
                pipeline.stamp_local_events("mustops_ce", 200)
            self.assertEqual(
                (state / "mustops_ce_events_per_job.txt").read_text().strip(),
                "200")


class TestLocalScaleResolution(unittest.TestCase):
    """pipeline._resolve_scale / _scale_default / _local_scale: the
    free-standing scale-dial resolver (Task 6's lx-free rewrite) backing
    cmd_submit's --local branch. Ported from tests/test_local_exec.py's
    TestScaleDials/TestLocalScaleEnvSeam, which exercised the byte-for-byte
    identical retired local_exec.resolve_scale/scale_default twins -- these
    now point directly at the live functions so the validation logic (loud
    ValueErrors on malformed/negative/zero input, order-independent
    per-stage override) keeps coverage now that module is gone.

    test_both_verbs_resolve_the_scale_identically (the "N call sites agree"
    invariant, asserted by grepping pipeline.py's source for
    `_local_scale(args, stage)`) is dropped rather than ported: its premise
    was multiple verbs (local-build, local-run, submit --local) sharing one
    resolver; with local-build/local-run retired there is exactly one call
    site left, so the invariant it pinned no longer applies.
    """

    def test_none_gives_the_default(self):
        self.assertEqual(pipeline._resolve_scale(None, 1, "mubeam"), 1)

    def test_bare_value_applies_to_every_stage(self):
        self.assertEqual(pipeline._resolve_scale(["4"], 1, "mubeam"), 4)
        self.assertEqual(pipeline._resolve_scale(["4"], 1, "concat"), 4)

    def test_per_stage_override_wins_regardless_of_order(self):
        self.assertEqual(
            pipeline._resolve_scale(["1", "elebeam_flash=4"], 1,
                                    "elebeam_flash"), 4)
        self.assertEqual(
            pipeline._resolve_scale(["elebeam_flash=4", "1"], 1,
                                    "elebeam_flash"), 4)
        self.assertEqual(
            pipeline._resolve_scale(["1", "elebeam_flash=4"], 1, "mubeam"), 1)

    def test_a_malformed_entry_is_a_loud_error(self):
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["notanumber"], 1, "mubeam")
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["mubeam=x"], 1, "mubeam")

    def test_whitespace_around_equals_is_stripped(self):
        self.assertEqual(
            pipeline._resolve_scale(["mubeam = 4"], 1, "mubeam"), 4)

    def test_empty_key_after_strip_raises(self):
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["=4"], 1, "mubeam")

    def test_negative_bare_value_raises(self):
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["-4"], 1, "mubeam")

    def test_zero_bare_value_raises(self):
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["0"], 1, "mubeam")

    def test_negative_per_stage_value_raises(self):
        with self.assertRaises(ValueError):
            pipeline._resolve_scale(["mubeam=-1"], 1, "mubeam")

    def test_env_var_supplies_the_default(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            self.assertEqual(
                pipeline._scale_default("AUTORESEARCH_LOCAL_EVENTS", 200),
                5000)

    def test_unset_or_blank_falls_back(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AUTORESEARCH_LOCAL_EVENTS", None)
            self.assertEqual(
                pipeline._scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)
            os.environ["AUTORESEARCH_LOCAL_EVENTS"] = "   "
            self.assertEqual(
                pipeline._scale_default("AUTORESEARCH_LOCAL_EVENTS", 200), 200)

    def test_a_junk_or_zero_value_raises_rather_than_silently_defaulting(self):
        # Silently falling back would run 200 events while the operator
        # believed they had asked for 5000 -- and harvest scales every metric
        # it computes by that number.
        for bad in ("5k", "0", "-3", "2.5"):
            with self.subTest(bad=bad):
                with mock.patch.dict(os.environ,
                                     {"AUTORESEARCH_LOCAL_EVENTS": bad}):
                    with self.assertRaises(ValueError):
                        pipeline._scale_default(
                            "AUTORESEARCH_LOCAL_EVENTS", 200)

    def test_an_explicit_flag_still_beats_the_env_var(self):
        with mock.patch.dict(os.environ,
                             {"AUTORESEARCH_LOCAL_EVENTS": "5000"}):
            njobs, events = pipeline._local_scale(
                SimpleNamespace(local_njobs=None, local_events=["77"]),
                "mubeam")
        self.assertEqual((njobs, events), (1, 77))


class TestLocalInputFarm(unittest.TestCase):
    """pipeline.local_input_farm: the local analogue of stage_hardlink_farm
    (kept verbatim for the grid). Flat farm at ROOT/<stage>/local_inputs,
    hard-linking a prior local stage's spread-out outputs into one dir so
    inloc: dir:<farm> can see them. Ported verbatim from
    tests/test_local_exec.py."""

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


class TestCmdSubmitLocalMarkerHandling(unittest.TestCase):
    """cmd_submit's marker write/clear invariants around a local run,
    exercised at the (grid-branch dry-run, grid-branch real) / (local-branch
    re-entry) seams. Ported verbatim from tests/test_local_exec.py's
    TestPipelineLocalWiring."""

    def test_a_forced_grid_submit_clears_the_local_runid_not_just_its_marker(self):
        # submit_stage_prodtools rewrites <stage>_cluster.txt only AFTER
        # submit_cnf parses a cluster id, so every grid path that never gets
        # there must not leave the local runid behind unmarked -- a later
        # poll would hand that small int to px.run_jobwait as a bogus jobid.
        # --dry-run is the cheapest such path (it still builds the cnf but
        # returns before submit_cnf); a raise anywhere before the submit has
        # the same shape. Asserted on the CLUSTER FILE, not the marker: a
        # test that checks only the marker passes against the bug this pins.
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
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" / "cnf.x.tar"):
                os.environ.pop("AUTORESEARCH_LOCAL", None)
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=True, dry_run=True, local=False))
            self.assertFalse(
                (state / "mubeam_cluster.txt").exists(),
                "the local runid survived a forced grid submit that never "
                "reached submit_cnf -- poll would send it to run_jobwait")
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
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()), \
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
    Ported verbatim from tests/test_local_exec.py (added there in Task 6/7).
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
            mock.patch.object(pipeline.px, "build_cnf", return_value=cnf),
            mock.patch.object(pipeline.px, "run_runlocal",
                              side_effect=_stub_run_runlocal(
                                  rc=(run_runlocal
                                     if run_runlocal is not None else 0))),
        ]

    def _consuming_stage_patches(self, tmp):
        # cmd_submit's local branch calls sourced_env() BEFORE the
        # consuming-stage refusal checks (same order the old
        # cmd_local_build had -- see submit_stage_prodtools's docstring),
        # so even a refusal test needs it faked: sourced_env() for real
        # shells out to setupmu2e-art.sh (~20s, and only succeeds in a
        # pre-configured interactive shell), and an unmocked ROOT defaults
        # to Path() (cwd), leaving stray <stage>/ dirs in the repo checkout.
        return [
            mock.patch.object(pipeline, "ROOT", Path(tmp)),
            mock.patch.object(pipeline, "CONFIG", "cfg001"),
            mock.patch.object(pipeline, "sourced_env",
                              return_value={"X": "1"}),
            mock.patch.object(pipeline, "_maybe_refresh_token"),
            mock.patch.object(pipeline, "write_code_tarball",
                              return_value=Path(tmp) / "Code.tar.bz2"),
            mock.patch.object(pipeline.px, "build_cnf",
                              return_value=Path(tmp) / "x" / "cnf.x.tar"),
            mock.patch.object(pipeline.px, "run_runlocal",
                              side_effect=_stub_run_runlocal()),
        ]

    def test_a_consuming_stage_refuses_when_its_input_stage_never_ran_local(self):
        # concat/mustops_ce need the PREVIOUS stage's local marker -- the same
        # refusal the retired mu2ejobdef-based local executor made. Without
        # it, <prev>_outputs.txt holds /pnfs paths, and farming those locally
        # is a grid chain wearing a local hat.
        for stage, prev in (("concat", "mubeam"), ("mustops_ce", "mubeam")):
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "state"
                state.mkdir()
                with self.subTest(stage=stage), \
                     mock.patch.object(pipeline, "STATE", state), \
                     mock.patch.object(pipeline, "CONCATLESS", True), \
                     contextlib.ExitStack() as stack:
                    for p in self._consuming_stage_patches(tmp):
                        stack.enter_context(p)
                    with self.assertRaises(SystemExit) as cm:
                        pipeline.cmd_submit(SimpleNamespace(
                            stage=stage, force=False, dry_run=False,
                            local=True, local_njobs=None, local_events=None,
                            local_pool=None))
                self.assertIn("no local run", str(cm.exception))
                self.assertIn(prev, str(cm.exception))

    def test_mustops_ce_refuses_when_prev_outputs_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "mubeam_local.txt").write_text("1\n")
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 contextlib.ExitStack() as stack:
                for p in self._consuming_stage_patches(tmp):
                    stack.enter_context(p)
                with self.assertRaises(SystemExit) as cm:
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
                 mock.patch.object(pipeline, "CONCATLESS", True), \
                 contextlib.ExitStack() as stack:
                for p in self._consuming_stage_patches(tmp):
                    stack.enter_context(p)
                with self.assertRaises(SystemExit) as cm:
                    pipeline.cmd_submit(SimpleNamespace(
                        stage="mustops_ce", force=False, dry_run=False,
                        local=True, local_njobs=None, local_events=None,
                        local_pool=None))
            self.assertIn("empty", str(cm.exception))

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
                                      side_effect=_stub_run_runlocal()))
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
            call_args, call_kwargs = rr.call_args
            self.assertEqual(call_args[2], math.ceil(5 / merge))
            # C1 regression: a consuming stage's runlocal call must carry
            # the SAME dir:<farm> inloc the rendered entry got -- without
            # it, runlocal defaults to --inloc tape and resolves this
            # locally-farmed basename against /pnfs/mu2e/tape.
            self.assertEqual(call_kwargs["inloc"], f"dir:{farm_dir}")

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

    def test_build_cnf_env_carries_templates_root_on_fhicl_file_path(self):
        # Same Task 11 finding as TestSubmitStageProdtools's twin test, but
        # for cmd_submit's --local branch, which builds its own env/build_cnf
        # call independently of submit_stage_prodtools (see core/pipeline.py
        # cmd_submit's `if want_local:` branch).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            seen_envs = []

            def fake_build_cnf(stage_dir, entry_path, desc, dsconf, env,
                               runner=None):
                seen_envs.append(env)
                cnf = Path(stage_dir) / f"cnf.u.{desc}.{dsconf}.0.tar"
                cnf.parent.mkdir(parents=True, exist_ok=True)
                cnf.touch()
                return cnf

            # _patches(tmp) supplies sourced_env()={"X": "1"} (no
            # FHICL_FILE_PATH of its own), so the assertion below checks
            # the fix adds TEMPLATES_ROOT even when the incoming env had no
            # FHICL_FILE_PATH to preserve.
            patches = self._patches(tmp)
            with mock.patch.object(pipeline, "STATE", state), \
                 contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                stack.enter_context(
                    mock.patch.object(pipeline.px, "build_cnf",
                                      side_effect=fake_build_cnf))
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=None))

            self.assertEqual(len(seen_envs), 1)
            fcl_path = seen_envs[0]["FHICL_FILE_PATH"]
            self.assertEqual(fcl_path.split(":")[0], str(pipeline.TEMPLATES_ROOT))
            self.assertEqual(seen_envs[0]["X"], "1")

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
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=cnf), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()) as rr:
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
        self.assertEqual(call_kwargs["pool"], 4)  # DEFAULT_LOCAL_POOL, unset flag
        # C1 regression: a non-consuming stage (mubeam resamples an
        # external SAM Cat dataset, staged_inputs=None) must still carry
        # the stage_entries/mubeam.json default inloc ("tape") through to
        # runlocal, not silently omit --inloc.
        self.assertEqual(call_kwargs["inloc"], "tape")

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
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()) as rr:
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=False, local=True,
                    local_njobs=None, local_events=None, local_pool=2))
            _, call_kwargs = rr.call_args
        self.assertEqual(call_kwargs["pool"], 2)

    def test_partial_local_ok_warns_but_does_not_raise(self):
        # M5 (2026-08-16 review): wait.json stays authoritative for a
        # partial local run (list-outputs still divides by the true ok
        # count), but an operator watching the console needs to SEE which
        # indices came up short -- mirrors the retired (pre-prodtools-switch)
        # cmd_local_run's "WARNING: N job(s) failed: [...]" print.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()

            def partial_run_runlocal(stage_dir, cnf, njobs, wait_json, env,
                                     **kw):
                Path(wait_json).write_text(json.dumps({
                    "jobdef": "cnf.t.tar", "jobs": [],
                    "ok": 1, "failed": [1, 2]}))
                return 1

            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env",
                                   return_value={"X": "1"}), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=partial_run_runlocal):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    # No SystemExit: a partial local run is still a normal
                    # return, exactly like cmd_poll's below-quorum WARN path.
                    pipeline.cmd_submit(SimpleNamespace(
                        stage="mubeam", force=False, dry_run=False,
                        local=True, local_njobs=["3"], local_events=None,
                        local_pool=None))
            out = buf.getvalue()
        self.assertIn("WARN", out)
        self.assertIn("1/3", out)
        self.assertIn("[1, 2]", out)   # failed indices named

    def test_full_local_ok_prints_no_warn(self):
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
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "mubeam" /
                                   "cnf.x.tar"), \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    pipeline.cmd_submit(SimpleNamespace(
                        stage="mubeam", force=False, dry_run=False,
                        local=True, local_njobs=None, local_events=None,
                        local_pool=None))
            out = buf.getvalue()
        self.assertNotIn("WARN", out)


if __name__ == "__main__":
    unittest.main()


class TestLocalDryRun(unittest.TestCase):
    """`submit <stage> --local --dry-run` must build and NOT run.

    Until 2026-08-17 the local branch never read args.dry_run, so a
    "dry run" executed the jobs for real -- found while validating an
    unrelated change, after several supposedly-inert invocations had each
    started a genuine mu2e job.
    """

    def _submit_dry(self, tmp):
        state = Path(tmp) / "state"
        state.mkdir()
        cnf = Path(tmp) / "mubeam" / "cnf.x.tar"
        with mock.patch.object(pipeline, "STATE", state), \
             mock.patch.object(pipeline, "ROOT", Path(tmp)), \
             mock.patch.object(pipeline, "CONFIG", "cfg001"), \
             mock.patch.object(pipeline, "sourced_env",
                               return_value={"X": "1"}), \
             mock.patch.object(pipeline, "_maybe_refresh_token") as tok, \
             mock.patch.object(pipeline, "write_code_tarball",
                               return_value=Path(tmp) / "Code.tar.bz2"), \
             mock.patch.object(pipeline.px, "build_cnf", return_value=cnf), \
             mock.patch.object(pipeline.px, "run_runlocal",
                               side_effect=_stub_run_runlocal()) as rr:
            pipeline.cmd_submit(SimpleNamespace(
                stage="mubeam", force=False, dry_run=True, local=True,
                local_njobs=["3"], local_events=["77"], local_pool=None))
        return state, rr, tok

    def test_dry_run_does_not_execute_the_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _state, rr, _tok = self._submit_dry(tmp)
            rr.assert_not_called()

    def test_dry_run_leaves_no_state_claiming_the_stage_ran(self):
        # The marker and cluster file are what make _is_local_stage and
        # cmd_poll believe a local run happened; written without one, poll
        # and list-outputs hunt a wait.json that will never exist.
        with tempfile.TemporaryDirectory() as tmp:
            state, _rr, _tok = self._submit_dry(tmp)
            self.assertFalse((state / "mubeam_local.txt").exists())
            self.assertFalse((state / "mubeam_cluster.txt").exists())
            self.assertFalse(
                pipeline.px.wait_json_path(state, "mubeam").exists())

    def test_dry_run_does_not_refresh_the_token(self):
        # Nothing streams from /pnfs when nothing runs; a dry run should
        # not touch the operator's credentials.
        with tempfile.TemporaryDirectory() as tmp:
            _state, _rr, tok = self._submit_dry(tmp)
            tok.assert_not_called()

    def test_dry_run_still_builds_the_cnf_and_code_tarball(self):
        # The point of the flag: everything up to dispatch must happen, so
        # a build failure still surfaces.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "CONFIG", "cfg001"), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2") as wct, \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   return_value=Path(tmp) / "c.tar") as bc, \
                 mock.patch.object(pipeline.px, "run_runlocal",
                                   side_effect=_stub_run_runlocal()):
                pipeline.cmd_submit(SimpleNamespace(
                    stage="mubeam", force=False, dry_run=True, local=True,
                    local_njobs=["1"], local_events=["200"], local_pool=None))
            wct.assert_called_once()
            bc.assert_called_once()
