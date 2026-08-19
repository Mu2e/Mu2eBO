"""Self-tests for graph/nodes.py — pure-ish, no grid contact.

Run from project root:
  .venv/bin/python -m unittest tests.test_nodes -v
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "graph"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))  # BO/pipeline modules (2026-07-17 reorg)

import nodes as nd  # noqa: E402
from langgraph.graph import END  # noqa: E402


class TestRouteAfterPreflightLogs(unittest.TestCase):
    """Issue #6 Mode A: silent END after preflight must emit a classifier line."""

    def test_fail_init_logs_termination(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({
                "preflight": "fail_init",
                "config_name": "fooR00_03",
                "attempts": {"propose": 0},
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("[graph] terminating fooR00_03", out)
        self.assertIn("preflight=fail_init", out)

    def test_retries_exhausted_logs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({
                "preflight": "ambiguous",
                "config_name": "fooR00_07",
                "attempts": {"propose": nd.MAX_PROPOSE_RETRIES},
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("fooR00_07", out)
        self.assertIn("ambiguous", out)
        self.assertIn(f"{nd.MAX_PROPOSE_RETRIES}/{nd.MAX_PROPOSE_RETRIES}", out)


class TestRouteAfterStageLogs(unittest.TestCase):
    """route_after_stage must say which stage triggered the END."""

    def test_no_failure_returns_next(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_stage({
                "stages": {"mubeam": {"status": "succeeded"}},
            })
        self.assertEqual(br, "next")
        self.assertNotIn("terminating", buf.getvalue())

    def test_failed_stage_logs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_stage({
                "config_name": "fooR00_02",
                "stages": {
                    "mubeam": {"status": "succeeded"},
                    "mustops_ce": {"status": "failed"},
                },
            })
        self.assertEqual(br, END)
        out = buf.getvalue()
        self.assertIn("[graph] terminating fooR00_02", out)
        self.assertIn("mustops_ce", out)


class TestMakeStageNodeLogs(unittest.TestCase):
    """make_stage_node's silent except clause must emit a stage failure line."""

    def test_exception_prints_and_marks_failed(self):
        node = nd.make_stage_node("mubeam")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
             mock.patch.object(nd.pio, "run_stage",
                                side_effect=RuntimeError("boom")):
            out = node({"config_name": "fooR00_05", "stages": {}, "errors": []})
        self.assertEqual(out["stages"]["mubeam"]["status"], "failed")
        self.assertTrue(any("boom" in e for e in out["errors"]))
        log = buf.getvalue()
        self.assertIn("[graph] stage[mubeam/fooR00_05] FAILED", log)
        self.assertIn("boom", log)

    def test_no_exception_silent(self):
        node = nd.make_stage_node("mubeam")
        buf = io.StringIO()
        ok = {"cluster_id": "abc", "status": "succeeded", "n_done": 1,
              "n_failed": 0, "last_poll_ts": 0.0}
        with contextlib.redirect_stdout(buf), \
             mock.patch.object(nd.pio, "run_stage", return_value=ok):
            out = node({"config_name": "fooR00_05", "stages": {}, "errors": []})
        self.assertEqual(out["stages"]["mubeam"]["status"], "succeeded")
        self.assertNotIn("FAILED", buf.getvalue())


class TestEvaluateZeroRowClassifier(unittest.TestCase):
    """Issue #8: evaluate/harvest zero-objective paths must classify the cause
    AND persist it to a sidecar TSV that survives state-dir cleanup."""

    def _read_sidecar(self, td: Path, name: str):
        path = td / name / "scan_logs" / "evaluate_zero_row.tsv"
        if not path.exists():
            return None
        return path.read_text().strip().splitlines()

    def test_scan_logs_broken_records_cause(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(nd, "GRID_DATA_ROOT", tmp):
                out = nd.node_evaluate({
                    "config_name": "fooR00_00",
                    "mode": "foils",
                    "errors": [],
                    "scan_logs_broken": True,
                    "scan_report_path": "/some/report.tsv",
                    "metrics": {"a": 1},
                })
            self.assertIsNone(out["objective"])
            lines = self._read_sidecar(tmp, "fooR00_00")
            self.assertIsNotNone(lines)
            self.assertEqual(lines[0], "config_name\tcause\ttail")
            self.assertIn("scan_logs_broken", lines[1])

    def test_metrics_none_records_cause(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(nd, "GRID_DATA_ROOT", tmp):
                out = nd.node_evaluate({
                    "config_name": "fooR00_01",
                    "mode": "foils",
                    "errors": [],
                    "scan_logs_broken": False,
                    "metrics": None,
                })
            self.assertIsNone(out["objective"])
            lines = self._read_sidecar(tmp, "fooR00_01")
            self.assertIsNotNone(lines)
            self.assertIn("metrics_none", lines[1])

    def test_obj_unparseable_records_cause(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(nd, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(nd.pio, "run_evaluate",
                                    return_value=(None, "bad tail")):
                out = nd.node_evaluate({
                    "config_name": "fooR00_02",
                    "mode": "foils",
                    "errors": [],
                    "scan_logs_broken": False,
                    "metrics": {"a": 1},
                })
            self.assertIsNone(out["objective"])
            lines = self._read_sidecar(tmp, "fooR00_02")
            self.assertIsNotNone(lines)
            self.assertIn("obj_unparseable", lines[1])
            self.assertIn("bad tail", lines[1])

    def test_harvest_exception_records_cause(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(nd, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(nd.pio, "run_harvest",
                                    side_effect=RuntimeError("disk full")):
                out = nd.node_harvest({
                    "config_name": "fooR00_03",
                    "mode": "foilspf",
                    "errors": [],
                })
            self.assertIsNone(out["metrics"])
            lines = self._read_sidecar(tmp, "fooR00_03")
            self.assertIsNotNone(lines)
            self.assertIn("harvest_exception", lines[1])
            self.assertIn("disk full", lines[1])

    def test_happy_path_no_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(nd, "GRID_DATA_ROOT", tmp), \
                 mock.patch.object(nd.pio, "run_evaluate",
                                    return_value=(1.23, "")):
                out = nd.node_evaluate({
                    "config_name": "fooR00_04",
                    "mode": "foils",
                    "errors": [],
                    "scan_logs_broken": False,
                    "metrics": {"a": 1},
                })
            self.assertEqual(out["objective"], 1.23)
            self.assertIsNone(self._read_sidecar(tmp, "fooR00_04"))


class TestPresubmitOverlapSeam(unittest.TestCase):
    """The elebeam_flash overlap (config.PRESUBMIT_AFTER) — worth ~40% of eval
    wall on foilsflash, and until 2026-07-26 it had NO behavioral test.

    The load-bearing property is the DEGRADATION path: a presubmit is
    best-effort, so a failing early submit must leave the eval untouched and
    let the stage's own node submit sequentially. If that ever regresses into
    a raise, a transient jobsub hiccup would kill the whole child instead of
    costing it the overlap.
    """

    OK = {"cluster_id": "abc", "status": "succeeded", "n_done": 1,
          "n_failed": 0, "last_poll_ts": 0.0}

    def _run(self, stage, presubmit_map, presubmit_side_effect=None):
        node = nd.make_stage_node(stage)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
             mock.patch.dict(nd.PRESUBMIT_AFTER, presubmit_map, clear=True), \
             mock.patch.object(nd.pio, "run_stage", return_value=self.OK), \
             mock.patch.object(nd.pio, "presubmit_stage",
                               side_effect=presubmit_side_effect) as ps:
            out = node({"config_name": "ffR00_03", "stages": {}, "errors": []})
        return out, ps, buf.getvalue()

    def test_fires_for_the_mapped_after_stage(self):
        out, ps, log = self._run("mubeam", {"mubeam": ["elebeam_flash"]})
        ps.assert_called_once_with("ffR00_03", "elebeam_flash")
        self.assertEqual(out["stages"]["mubeam"]["status"], "succeeded")
        self.assertIn("presubmit[elebeam_flash/ffR00_03] submitted early", log)

    def test_does_not_fire_for_an_unmapped_stage(self):
        # mustops_ce carries no overlap: nothing may be submitted early.
        _, ps, log = self._run("mustops_ce", {"mubeam": ["elebeam_flash"]})
        ps.assert_not_called()
        self.assertNotIn("presubmit", log)

    def test_presubmit_failure_degrades_instead_of_failing_the_eval(self):
        out, ps, log = self._run("mubeam", {"mubeam": ["elebeam_flash"]},
                                 presubmit_side_effect=RuntimeError("jobsub hiccup"))
        ps.assert_called_once()
        # The eval is untouched: stage succeeded, and the failure is NOT
        # recorded in errors (which would mark the child degraded).
        self.assertEqual(out["stages"]["mubeam"]["status"], "succeeded")
        self.assertEqual(out["errors"], [])
        self.assertIn("jobsub hiccup", log)
        self.assertIn("will submit sequentially", log)

    def test_not_reached_when_the_stage_itself_fails(self):
        # No cluster to overlap with if the after-stage never landed.
        node = nd.make_stage_node("mubeam")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
             mock.patch.dict(nd.PRESUBMIT_AFTER,
                             {"mubeam": ["elebeam_flash"]}, clear=True), \
             mock.patch.object(nd.pio, "run_stage",
                               side_effect=RuntimeError("boom")), \
             mock.patch.object(nd.pio, "presubmit_stage") as ps:
            out = node({"config_name": "ffR00_03", "stages": {}, "errors": []})
        ps.assert_not_called()
        self.assertEqual(out["stages"]["mubeam"]["status"], "failed")

    def test_foilsflash_declares_the_overlap_in_its_spec(self):
        """The map is a ModeSpec field, so this is the real production value —
        not a graph/ constant. Guards against a silent drop to {}."""
        import modes as _modes
        self.assertEqual(_modes.SPECS["foilsflash"].presubmit_after,
                         {"mubeam": ("elebeam_flash",)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
