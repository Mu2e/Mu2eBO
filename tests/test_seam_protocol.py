"""Typed-JSON seam tests: preflight verdict (Phase 2a) and — from Task 7 —
evaluate result (Phase 2b). The driver subprocess is faked by writing (or
not writing) the JSON the way a real/crashed run would."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))
import bo_driver as bo  # noqa: E402
import pipeline_io as pio  # noqa: E402


class TestWriteJsonAtomic(unittest.TestCase):
    def test_writes_parseable_json_and_no_tmp_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "v.json"
            bo.write_json_atomic(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})
            self.assertEqual(list(p.parent.glob("*.tmp")), [])


class TestPreflightVerdictEmit(unittest.TestCase):
    def test_wrapper_emits_verdict_json(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(bo, "_cmd_preflight_impl", return_value=1):
            out = Path(tmp) / "preflight_verdict.json"
            rc = bo.cmd_preflight(SimpleNamespace(
                mode="foilsflash", config_name="cfgX", emit_json=str(out)))
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["verdict"], "fail_managed")
            self.assertEqual(payload["rc"], 1)
            self.assertEqual(payload["config"], "cfgX")
            self.assertTrue(payload["reasons"])
            self.assertIn("cfgX.log", payload["log_path"])

    def test_no_emit_json_attr_is_fine(self):
        with mock.patch.object(bo, "_cmd_preflight_impl", return_value=0):
            rc = bo.cmd_preflight(SimpleNamespace(mode="foilsflash",
                                                  config_name="cfgX"))
            self.assertEqual(rc, 0)


def _fake_run(write_json=None, rc=0):
    """subprocess.run stand-in: optionally writes the verdict JSON the way
    the driver would, then returns a completed-process shim."""
    def run(cmd, **kw):
        if write_json is not None:
            i = cmd.index("--emit-json")
            bo.write_json_atomic(Path(cmd[i + 1]), write_json)
        return SimpleNamespace(returncode=rc, stdout="tail line\n", stderr="")
    return run


class TestRunPreflightReadsJson(unittest.TestCase):
    def _call(self, tmp, runner):
        with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
             mock.patch.object(pio.subprocess, "run", side_effect=runner):
            return pio.run_preflight("foilsflash", "cfgX")

    def test_valid_json_wins(self):
        # JSON says pass while rc=2 (old rc-map would say fail_init):
        # only a JSON-reading implementation returns "pass" here.
        with tempfile.TemporaryDirectory() as tmp:
            status, _ = self._call(tmp, _fake_run(
                {"verdict": "pass", "rc": 2, "reasons": [],
                 "log_path": "x", "config": "cfgX"}, rc=2))
            self.assertEqual(status, "pass")

    def test_missing_json_decodes_ambiguous_with_loud_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, tail = self._call(tmp, _fake_run(None, rc=0))
            self.assertEqual(status, "ambiguous")
            self.assertIn("missing/unparseable", tail)

    def test_stale_verdict_from_prior_run_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "cfgX" / "state" / "preflight_verdict.json"
            bo.write_json_atomic(stale, {"verdict": "pass", "rc": 0})
            status, _ = self._call(tmp, _fake_run(None, rc=1))
            self.assertEqual(status, "ambiguous")  # stale "pass" not trusted


if __name__ == "__main__":
    unittest.main()
