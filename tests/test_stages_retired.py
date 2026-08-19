"""The STAGES literal is gone; stage-level data lives in stage_entries/.

The bug being removed is a SILENT SHADOW: stage_entries/<stage>.json already
carried `events` with the same values as STAGES[...]["events_per_job"], and
pipeline.py resolved STAGES first -- so editing the JSON did nothing, with no
error. Same failure shape as the outloc precedence bug and
events-per-job-mid-flight-edit.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

STAGES = ["mubeam", "run1b_mubeam", "concat", "mustops_ce", "elebeam_flash"]


class TestStagesRetired(unittest.TestCase):
    def test_pipeline_has_no_STAGES_literal(self):
        import pipeline
        self.assertFalse(hasattr(pipeline, "STAGES"))

    def test_every_stage_entry_carries_stage_level_fields(self):
        for s in STAGES:
            d = json.loads((ROOT / "stage_entries" / f"{s}.json").read_text())
            self.assertIn("desc_fmt", d, s)
            self.assertIn("output_glob", d, s)
            self.assertIn("njobs", d, s)

    def test_no_duplicated_events_per_job_key(self):
        """`events` is the only spelling. Two files holding one number, with
        one silently winning, is the bug this task removes."""
        for s in STAGES:
            d = json.loads((ROOT / "stage_entries" / f"{s}.json").read_text())
            self.assertNotIn("events_per_job", d, s)

    def test_mode_spec_overrides_stage_entry(self):
        import pipeline
        cfg = pipeline.stage_cfg("mubeam", mode="foilspf")
        self.assertEqual(cfg["events"], 200000)
        self.assertEqual(cfg["njobs"], 15)

    def test_stage_entry_supplies_the_default(self):
        import pipeline
        cfg = pipeline.stage_cfg("mubeam", mode=None)
        self.assertEqual(cfg["events"], 5000)
        self.assertEqual(cfg["desc_fmt"], "Run1A_MuBeam_{cfg}")
        self.assertEqual(cfg["output_glob"], "sim.*.TargetStops.*.art")

    def test_foilsflash_live_spec_tuning_reaches_stage_cfg(self):
        """test_mode_spec_overrides_stage_entry above only exercises the
        live-spec path for foilspf; the retired
        test_foilsflash_python_mode_stage_tuning_is_a_noop
        (tests/test_pipeline_verbs.py) had been the one test naming
        foilsflash's live tuning values, and it was retired (Task 6 fix
        round) because its premise -- foilsflash's stage_tuning is {} -- had
        been false since foilsflash became a JSON mode; it passed by
        coincidental value-identity (it hand-built a dict already holding
        the live numbers, then applied the live tuning to it), never by
        actually checking a no-op. This pins the SHIPPED mode_specs/
        foilsflash.json run.stage_tuning values directly through
        pipeline.stage_cfg(), so the live-spec merge mechanism is covered
        for a second real mode, not just foilspf."""
        import pipeline
        self.assertEqual(
            pipeline.stage_cfg("mubeam", mode="foilsflash")["events"], 200000)
        self.assertEqual(
            pipeline.stage_cfg("mustops_ce", mode="foilsflash")["events"], 75000)
        self.assertEqual(
            pipeline.stage_cfg("elebeam_flash", mode="foilsflash")["events"],
            110000)


if __name__ == "__main__":
    unittest.main()
