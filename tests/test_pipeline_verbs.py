"""Grid-verb tests for core/pipeline.py: submit idempotency, stamp-at-submit,
poll exit conditions (via injected jobsub_q runner), list-outputs gating.
No grid contact: STATE/STAGES/OUTSTAGE are patched to tmp dirs and the
jobsub/subprocess boundary is faked."""
import contextlib
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


if __name__ == "__main__":
    unittest.main()
