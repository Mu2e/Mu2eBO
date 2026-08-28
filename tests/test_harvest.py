"""Unit tests for harvest.py — the Eval-summary module.

Tests the generic EvalSummary schema and utility functions.
"""
import json as _json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import harvest  # noqa: E402


def _write_outputs(state: Path, stage: str, names):
    (state / f"{stage}_outputs.txt").write_text(
        "\n".join(f"/pnfs/fake/{n}" for n in names) + "\n")


class TestReadOutputs(unittest.TestCase):
    def test_reads_non_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "mubeam",
                           ["sim.x.TargetStops.a.art", "nts.x.mubeam.a.root"])
            files = harvest.read_outputs(state, "mubeam")
            self.assertEqual(len(files), 2)

    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(harvest.read_outputs(Path(d), "mubeam"))

    def test_blank_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            (state / "mubeam_outputs.txt").write_text("\n\n")
            self.assertEqual(harvest.read_outputs(state, "mubeam"), [])


class TestEventsPerJob(unittest.TestCase):
    def test_stamp_wins(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            (state / "elebeam_flash_events_per_job.txt").write_text("110000\n")
            self.assertEqual(harvest.events_per_job(state, "elebeam_flash", 2500),
                             110000)

    def test_fallback_when_unstamped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(harvest.events_per_job(Path(d), "mubeam", 5000), 5000)


class TestEvalSummarySchema(unittest.TestCase):
    """Test the generic EvalSummary schema."""

    def _minimal(self):
        return harvest.EvalSummary.from_fields("testcfg", {
            "ce_seen": 576070,
            "muminus_stops": 238912,
            "mubeam_sim_total": 2800000,
            "ce_simulated_events": 1050000,
            "stopping_factor": 0.0853,
            "ce_abs_eff": 5.98e-4,
            "s_over_sqrt_b": 3.78,
        })

    def test_fields_flattened_to_top_level(self):
        """Fields from the generic harvest must appear at the top level of
        summary.json so that extract_metrics can read them by key name."""
        data = _json.loads(self._minimal().to_json())
        self.assertEqual(data["config"], "testcfg")
        self.assertEqual(data["s_over_sqrt_b"], 3.78)
        self.assertEqual(data["ce_seen"], 576070)
        self.assertEqual(data["degraded"], {})

    def test_write_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._minimal().write(Path(d))
            data = _json.loads(out.read_text())
            self.assertEqual(data["config"], "testcfg")
            self.assertEqual(data["s_over_sqrt_b"], 3.78)

    def test_from_fields_extracts_degraded(self):
        fields = {"metric_a": 1.0, "degraded": {"flash": "no outputs"}}
        summary = harvest.EvalSummary.from_fields("cfg", fields)
        self.assertEqual(summary.degraded, {"flash": "no outputs"})
        self.assertEqual(summary.fields["metric_a"], 1.0)
        self.assertNotIn("degraded", summary.fields)

    def test_from_fields_empty_degraded_default(self):
        summary = harvest.EvalSummary.from_fields("cfg", {"x": 42})
        self.assertEqual(summary.degraded, {})
        self.assertEqual(summary.fields["x"], 42)


if __name__ == "__main__":
    unittest.main()
