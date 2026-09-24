import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import study as st  # noqa: E402
import study_compat as sc  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


class TestView(unittest.TestCase):
    def setUp(self):
        self.spec = sc.load_modespec(FIXTURE)

    def test_pipeline_fields(self):
        s = self.spec
        self.assertEqual(s.grid_stages, ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(s.presubmit_after, {"mubeam": ("elebeam_flash",)})
        self.assertEqual(s.stage_target_overrides,
                         {"mubeam": 15, "mustops_ce": 15, "elebeam_flash": 100})
        self.assertEqual(s.stage_tuning["elebeam_flash"],
                         {"events_per_job": 110000, "memory_mb": 2000})
        self.assertEqual(s.stage_tuning["mubeam"]["quorum"], 0.8)
        self.assertTrue(s.require_zero_overlaps)
        self.assertTrue(s.musing.endswith("demo/setup_local.sh"))
        self.assertTrue(s.grid_tarball.endswith("demo/Code_demo.tar.bz2"))

    def test_leaderboard_fields(self):
        s = self.spec
        self.assertEqual(s.metric_cols, ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(s.obs_noise, (0.006, 0.01))
        self.assertEqual(s.metrics, {"sob": ("s_over_sqrt_b",),
                                     "flash_edep": ("flash_edep_per_pot",)})
        self.assertEqual(s.knob_names, ("a", "b"))
        self.assertEqual(s.leaderboard_rel, "leaderboards/leaderboard_demo_study.tsv")

    def test_geom_is_the_studys(self):
        study = st.load_study_file(FIXTURE)
        self.assertEqual(self.spec.geom.render([2.0, 0.5]),
                         study.geom.render([2.0, 0.5]))


class TestRefusals(unittest.TestCase):
    """A study the Phase-A pipeline cannot run must fail loudly at load."""

    def _load(self, mutate):
        doc = json.loads(FIXTURE.read_text())
        mutate(doc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "demo.json"
            p.write_text(json.dumps(doc))
            with self.assertRaises(ValueError) as cm:
                sc.load_modespec(p)
        return str(cm.exception)

    def test_three_objectives(self):
        def m(d):
            d["objectives"].append({"name": "third", "metric": "sob.x",
                                    "direction": "max", "transform": "none",
                                    "noise": 0.1, "fmt": "{:.3f}"})
        self.assertIn("Phase-A pipeline", self._load(m))

    def test_input_rule(self):
        def m(d):
            d["evaluate"][1]["files_from"] = ["elebeam_flash"]
        self.assertIn("files_from", self._load(m))


if __name__ == "__main__":
    unittest.main()
