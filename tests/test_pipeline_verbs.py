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


class TestWriteCodeTarballExtraFiles(unittest.TestCase):
    """write_code_tarball's extra_files param (prodtools switch, Task 4):
    ships the per-stage materialized FCL beside the geom in Code/, the same
    search-path mechanism the geom already uses. Staleness for extra_files
    is CONTENT-based (_extra_files_digest), not mtime -- _materialize_template
    always rewrites the FCL fresh right before this is called, so an
    mtime-only gate can never observe a reuse (review finding 1, 2026-08-16).
    Real tar/bzip2 subprocess calls only -- no grid contact."""

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
            extra = root / "mubeam_template_materialized.fcl"
            extra.write_text('#include "geom.txt"\n')
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                cnf = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra])
            listing = self._tar_listing(cnf)
        self.assertIn("Code/mubeam_template_materialized.fcl", listing)
        self.assertIn("Code/geom.txt", listing)

    def test_a_cache_missing_a_newer_extra_file_is_rebuilt_not_reused(self):
        # The cache-freshness gate keyed only on (geom, base_tarball) would
        # silently reuse stage A's cached tarball for stage B -- shipping
        # A's FCL and never B's, so every non-first stage in a config's
        # chain would ship a Code.tar.bz2 missing its own template. Guard
        # against that regression directly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir = root / "mubeam"
            stage_dir.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                # Stage A's submit: no extra_files, seeds the shared cache.
                cnf_a = pipeline.write_code_tarball(stage_dir, base_tarball=base)
                # Stage B's submit: a freshly-materialized FCL not yet in
                # that cache must force a rebuild, not a silent reuse.
                extra_b = root / "run1b_mubeam_template_materialized.fcl"
                extra_b.write_text('#include "geom.txt"\n')
                cnf_b = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra_b])
            self.assertEqual(cnf_a, cnf_b)  # same shared per-config cache path
            listing = self._tar_listing(cnf_b)
        self.assertIn("Code/run1b_mubeam_template_materialized.fcl", listing)

    def test_identical_extra_files_content_reuses_the_cache(self):
        # The staleness signal must be CONTENT, not mtime:
        # _materialize_template always rewrites the per-stage FCL fresh
        # right before write_code_tarball is called, so its mtime is
        # always "now" -- an mtime-only gate can never observe a reuse and
        # silently reintroduces the full unpack+rebzip2 cost on every
        # single submit, including a same-stage retry with byte-identical
        # text (review finding 1, 2026-08-16). Proven here by spying on
        # the module-level `run` helper (the only thing that shells out to
        # tar/bzip2): a second call whose extra_files basename+bytes are
        # byte-identical to the first must NOT invoke it again.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg"
            stage_dir = root / "mubeam"
            stage_dir.mkdir(parents=True)
            geom = root / "geom.txt"
            geom.write_text("geom\n")
            extra = root / "mubeam_template_materialized.fcl"
            extra.write_text('#include "geom.txt"\n')
            base = self._make_base_tarball(tmp)
            with mock.patch.object(pipeline, "ROOT", root), \
                 mock.patch.object(pipeline, "GEOM_FILE", geom):
                cnf_1 = pipeline.write_code_tarball(
                    stage_dir, base_tarball=base, extra_files=[extra])
                with mock.patch.object(pipeline, "run",
                                       wraps=pipeline.run) as run_spy:
                    # Same basename, same bytes -- exactly what a real
                    # resubmit's _materialize_template call produces (a
                    # fresh mtime, identical text).
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
            template = state / "mubeam_template_materialized.fcl"
            template.write_text("x")

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
                 mock.patch.object(pipeline, "LEDGER_DB",
                                   Path(tmp) / "ledger" / "submissions.db"), \
                 mock.patch.object(pipeline, "write_code_tarball",
                                   return_value=Path(tmp) / "Code.tar.bz2"), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=template), \
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
            self.assertEqual(entry["fcl"], "mubeam_template_materialized.fcl")
            self.assertEqual(entry["code"], str(Path(tmp) / "Code.tar.bz2"))
            # events/run come from whatever mode's stage_tuning is live at
            # import time (foilsflash's tuning overrides the base 5000/1800
            # in a normal test run) -- assert against the live STAGES dict,
            # not the module's base literals, same convention as
            # TestCmdSubmitLocalViaRunlocal below.
            self.assertEqual(entry["events"],
                             pipeline.STAGES["mubeam"]["events_per_job"])
            self.assertEqual(entry["run"],
                             pipeline.STAGES["mubeam"]["run_number"])
            self.assertEqual(entry["resampler_name"], "beamResampler")
            self.assertEqual(
                entry["input_data"], {"sim.mu2e.MuBeamCat.Run1Baa.art": 1})
            self.assertEqual(entry["inloc"], "tape")

            # LEDGER_DB threaded through to submit_cnf, origin identifies
            # the (config, stage) for the ledger row.
            _, _, ledger_db, origin = self.submit_args
            self.assertEqual(ledger_db, Path(tmp) / "ledger" / "submissions.db")
            self.assertEqual(origin, "autoresearch:cfg001/mubeam")

    def test_staged_inputs_feed_input_data_and_inloc(self):
        # mustops_ce / concat shape: staged_inputs=(dir, {basename: count})
        # replaces the static Cat-dataset input_data with the hard-linked
        # farm's basenames, and inloc becomes dir:<staged_dir>.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            template = state / "mustops_ce_template_materialized.fcl"
            template.write_text("x")
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
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=template), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
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

    def test_build_cnf_env_carries_template_dir_on_fhicl_file_path(self):
        # Task 11 empirical finding (docs/superpowers/sdd/
        # 2026-08-16-prodtools-switch/task-11-report.md, finding 1): real
        # json2jobdef writes its own wrapper template.fcl containing
        # `#include "<fcl_name>"` (a bare basename) and resolves it via
        # fhicl-get, which consults ONLY $FHICL_FILE_PATH -- confirmed by
        # direct reproduction that fhicl-get does NOT fall back to cwd, even
        # though build_cnf's subprocess cwd is the stage dir. sourced_env()'s
        # `muse setup ops` has no way to know about our per-config STATE
        # dir, so without _cnf_build_env, json2jobdef always dies inside
        # fhicl-get with "Can't find file <stage>_template_materialized.fcl".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfg001"
            state = root / "state"
            state.mkdir(parents=True)
            template = state / "mubeam_template_materialized.fcl"
            template.write_text("x")
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
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=template), \
                 mock.patch.object(pipeline, "_maybe_refresh_token"), \
                 mock.patch.object(pipeline.px, "build_cnf",
                                   side_effect=fake_build_cnf), \
                 mock.patch.object(pipeline.px, "submit_cnf",
                                   side_effect=fake_submit_cnf):
                pipeline.submit_stage_prodtools(
                    "mubeam", {"FHICL_FILE_PATH": "/some/other/path"})

            self.assertEqual(len(seen_envs), 1)
            fcl_path = seen_envs[0]["FHICL_FILE_PATH"]
            self.assertEqual(fcl_path.split(":")[0], str(state))
            # the incoming env's own FHICL_FILE_PATH is preserved, not
            # clobbered -- just prepended to.
            self.assertIn("/some/other/path", fcl_path)


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
                               return_value=(Path("/pnfs/x/concat"),
                                            None)) as farm:
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
                               return_value=(Path("/pnfs/x/mustops_ce"),
                                            None)):
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
            mock.patch.object(pipeline, "_materialize_template",
                              return_value=Path(tmp) / "t.fcl"),
            mock.patch.object(pipeline.px, "build_cnf", return_value=cnf),
            mock.patch.object(pipeline.px, "run_runlocal",
                              return_value=(run_runlocal
                                           if run_runlocal is not None
                                           else 0)),
        ]

    def _consuming_stage_patches(self, tmp):
        # cmd_submit's local branch calls sourced_env()/_materialize_template
        # BEFORE the consuming-stage refusal checks (same order the old
        # cmd_local_build had -- see submit_stage_prodtools's docstring),
        # so even a refusal test needs these faked: sourced_env() for real
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
            mock.patch.object(pipeline, "_materialize_template",
                              return_value=Path(tmp) / "t.fcl"),
            mock.patch.object(pipeline.px, "build_cnf",
                              return_value=Path(tmp) / "x" / "cnf.x.tar"),
            mock.patch.object(pipeline.px, "run_runlocal", return_value=0),
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

    def test_build_cnf_env_carries_template_dir_on_fhicl_file_path(self):
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
            # FHICL_FILE_PATH of its own) and _materialize_template ->
            # Path(tmp)/"t.fcl", so the assertion below checks the fix adds
            # the template's directory even when the incoming env had no
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
            self.assertEqual(fcl_path.split(":")[0], str(Path(tmp)))
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
        self.assertEqual(call_kwargs["pool"], 4)  # DEFAULT_LOCAL_POOL, unset flag

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


if __name__ == "__main__":
    unittest.main()
