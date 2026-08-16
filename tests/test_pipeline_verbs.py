"""Grid-verb tests for core/pipeline.py: submit idempotency, stamp-at-submit,
poll exit conditions (via injected jobsub_q runner), list-outputs gating.
No grid contact: STATE/STAGES/OUTSTAGE are patched to tmp dirs and the
jobsub/subprocess boundary is faked."""
import contextlib
import copy
import io
import json
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


def _q_result(rc=0, stdout=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")


def _queue_lines(cluster, n):
    return "\n".join(f"{cluster}.{i}@jobsub01.fnal.gov" for i in range(n))


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


class TestPollExitConditions(unittest.TestCase):
    def _outstage(self, tmp, cluster, bare, hashed):
        base = Path(tmp) / str(cluster) / "00"
        base.mkdir(parents=True)
        for i in range(bare):
            (base / f"{i:05d}").mkdir()
        for i in range(hashed):
            (base / f"{bare + i:05d}.6d475c59").mkdir()

    def test_returns_on_convergence_without_sleeping(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep",
                               side_effect=AssertionError("slept")):
            self._outstage(tmp, 123, bare=4, hashed=0)
            runner = mock.Mock(return_value=_q_result(0, ""))  # queue drained
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pipeline.poll_cluster("poke", 123, runner=runner)  # returns, no sleep
            self.assertEqual(runner.call_count, 1)
            self.assertIn("converged", buf.getvalue())

    def test_failure_aware_exit_queue_drained_all_dirs_but_unsettled(self):
        # 2 bare + 2 perma-hash = all 4 dirs present, settled < target=3:
        # must return (WARN) so list_outputs/harvest fail loudly, not hang.
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep",
                               side_effect=AssertionError("slept")):
            self._outstage(tmp, 123, bare=2, hashed=2)
            runner = mock.Mock(return_value=_q_result(0, ""))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pipeline.poll_cluster("poke", 123, runner=runner)
            self.assertEqual(runner.call_count, 1)
            output = buf.getvalue()
            self.assertIn("stuck in hash form", output)
            self.assertNotIn("converged", output)

    def test_not_yet_converged_sleeps_then_retries(self):
        # 2 still in queue: finished_q=2 < target=3 -> not converged; in_queue
        # != 0 so the failure-aware exit can't fire either -> sleeps once,
        # then the second poll sees a drained queue and converges.
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep") as slept:
            self._outstage(tmp, 123, bare=4, hashed=0)
            runner = mock.Mock(side_effect=[_q_result(0, _queue_lines(123, 2)),
                                            _q_result(0, "")])
            pipeline.poll_cluster("poke", 123, runner=runner)
            self.assertEqual(runner.call_count, 2)
            slept.assert_called_once_with(120)

    def test_jobsub_q_failure_is_retried_not_treated_as_empty_queue(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(pipeline.STAGES, {"poke": {"njobs": 4}}), \
             mock.patch.object(pipeline, "OUTSTAGE", Path(tmp)), \
             mock.patch.object(pipeline.time, "sleep") as slept:
            self._outstage(tmp, 123, bare=4, hashed=0)
            runner = mock.Mock(side_effect=[_q_result(1, ""),
                                            _q_result(0, "")])
            pipeline.poll_cluster("poke", 123, runner=runner)
            self.assertEqual(runner.call_count, 2)
            slept.assert_called_once_with(60)


class TestListOutputsGating(unittest.TestCase):
    def test_noop_when_outputs_listed_and_resolvable(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "list_outputs") as lo:
            f = Path(tmp) / "some.art"
            f.write_text("x")
            (Path(tmp) / "poke_outputs.txt").write_text(f"{f}\n")
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            lo.assert_not_called()

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
    search-path mechanism the geom already uses. Real tar/bzip2 subprocess
    calls only -- no grid contact."""

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
            # TestPipelineLocalWiring in test_local_exec.py.
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


if __name__ == "__main__":
    unittest.main()
