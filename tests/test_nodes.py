"""Self-tests for graph/nodes.py — pure-ish, no grid contact.

Run from project root:
  .venv-graph/bin/python -m unittest tests.test_nodes -v
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

import nodes as nd  # noqa: E402
from langgraph.graph import END  # noqa: E402


class TestRouteAfterPreflightLogs(unittest.TestCase):
    """Issue #6 Mode A: silent END after preflight must emit a classifier line."""

    def test_pass_returns_branch_no_log(self):
        # Happy path: no diagnostic line, just returns "mock" or "real".
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            br = nd.route_after_preflight({"preflight": "pass", "mock": True})
        self.assertEqual(br, "mock")
        self.assertNotIn("terminating", buf.getvalue())

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
