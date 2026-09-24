import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.mode = bo.MODES["foilspfbpz"]

    def test_values_by_name(self):
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 6e-7})
        self.assertEqual(out, {"sob": 3.9, "flash_edep": 6e-7})

    def test_no_per_event_fallback(self):
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_event": 0.2})
        self.assertIsNone(out["flash_edep"])


class TestEvaluateRefusals(unittest.TestCase):
    """cmd_evaluate never appends a row with a missing objective or a
    non-positive log10 objective.

    Both refusals fire before the geom-existence check, on config_name
    "nosuchcfg" -- a name with no rendered geom and no pending row. Without
    inspecting the refusal's own evidence (message text / exception), these
    tests would pass even with the refusal deleted: cmd_evaluate ALSO
    returns 1 when the geom file is missing, so rc==1 alone is vacuous here
    (R4 controller ruling). Each test below asserts the specific "refusing"
    text or SystemExit that only the intended guard produces, and Step 4 of
    the task-8 report records a mutation check proving each test fails when
    its guard is commented out.
    """

    def _run(self, summary):
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "summary.json"
            sp.write_text(json.dumps(summary))
            args = SimpleNamespace(mode="foilspfbpz", alpha=1e5,
                                   config_name="nosuchcfg", summary=str(sp),
                                   emit_json=None)
            try:
                return bo.cmd_evaluate(args)
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 1

    def test_missing_objective(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run({"s_over_sqrt_b": 3.9})
        self.assertEqual(rc, 1)
        out = buf.getvalue()
        self.assertIn("refusing", out)
        self.assertIn("flash_edep", out)

    def test_zero_log10_objective(self):
        # Not routed through _run(): a SystemExit must escape here, not be
        # swallowed into an rc, so the message text is inspectable.
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "summary.json"
            sp.write_text(json.dumps(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0}))
            args = SimpleNamespace(mode="foilspfbpz", alpha=1e5,
                                   config_name="nosuchcfg", summary=str(sp),
                                   emit_json=None)
            with self.assertRaises(SystemExit) as cm:
                bo.cmd_evaluate(args)
        msg = str(cm.exception)
        self.assertIn("log10", msg)
        self.assertIn("flash_edep", msg)


if __name__ == "__main__":
    unittest.main()
