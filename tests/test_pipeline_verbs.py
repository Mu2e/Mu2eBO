"""Grid-verb tests for core/pipeline.py: submit idempotency, stamp-at-submit,
poll exit conditions (via injected jobsub_q runner), list-outputs gating.
No grid contact: STATE/STAGES/OUTSTAGE are patched to tmp dirs and the
jobsub/subprocess boundary is faked."""
import contextlib
import copy
import io
import sys
import tempfile
import unittest
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
             mock.patch.object(pipeline, "submit_stage") as sub, \
             mock.patch.object(pipeline, "sourced_env", return_value={}):
            (Path(tmp) / "poke_cluster.txt").write_text("123\n")
            pipeline.cmd_submit(SimpleNamespace(stage="poke", force=False,
                                                dry_run=False))
            sub.assert_not_called()

    def test_stamps_chain_then_submits_on_first_submit(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "GRID_STAGES", ("poke", "harvest2")), \
             mock.patch.object(pipeline, "submit_stage") as sub, \
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
             mock.patch.object(pipeline, "submit_stage"), \
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
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "STATE", Path(tmp)), \
             mock.patch.object(pipeline, "list_outputs") as lo:
            (Path(tmp) / "poke_outputs.txt").write_text(
                f"{tmp}/gone.art\n")
            (Path(tmp) / "poke_cluster.txt").write_text("123\n")
            pipeline.cmd_list_outputs(SimpleNamespace(stage="poke",
                                                      force=False))
            lo.assert_called_once_with("poke", 123)


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
        AUTORESEARCH_MODE == "foilsflash" block owns that mode's tuning."""
        import modes as _modes  # noqa: E402 (bare, core/ on sys.path)
        local_stages = copy.deepcopy(pipeline.STAGES)
        before = copy.deepcopy(local_stages)
        pipeline._apply_stage_tuning(local_stages, _modes.SPECS["foilsflash"].stage_tuning)
        self.assertEqual(local_stages, before)


if __name__ == "__main__":
    unittest.main()
