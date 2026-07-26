import json
import tempfile
import unittest
from pathlib import Path

from core import modes
from core.mode_json import load_mode_dir, load_mode_file

FIXTURE = Path(__file__).parent / "fixtures" / "modes" / "foilsflash.json"


def _write(tmp: Path, name: str, doc: dict) -> Path:
    p = tmp / f"{name}.json"
    p.write_text(json.dumps(doc))
    return p


def _valid_doc() -> dict:
    doc = json.loads(FIXTURE.read_text())
    doc["name"] = "demo"
    return doc


class TestLoadFixture(unittest.TestCase):
    def test_fixture_loads_into_a_modespec(self):
        spec = load_mode_file(FIXTURE)
        self.assertEqual(spec.name, "foilsflash")
        self.assertIsNotNone(spec.geom)
        self.assertEqual(spec.grid_stages,
                         ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(spec.metric_cols, ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(spec.obs_noise, (0.006, 0.010))
        self.assertEqual(spec.metrics["sob"], ("s_over_sqrt_b",))

    def test_fixture_matches_the_python_spec(self):
        """The fixture is the acceptance target: its facts must equal the live spec."""
        spec, live = load_mode_file(FIXTURE), modes.SPECS["foilsflash"]
        for field in ("musing", "grid_tarball", "grid_stages", "harvest_verb",
                      "stage_target_overrides", "presubmit_after", "bounds_lo",
                      "bounds_hi", "knob_names", "knob_fmts", "metric_cols",
                      "obs_noise", "preflight_fcl", "dumps_gdml",
                      "verifies_foil_gdml", "preserves_gdml",
                      "checks_managed_overlap"):
            self.assertEqual(getattr(spec, field), getattr(live, field), field)


class TestRejections(unittest.TestCase):
    def _expect_error(self, mutate, *needles):
        doc = _valid_doc()
        mutate(doc)
        with tempfile.TemporaryDirectory() as td:
            p = _write(Path(td), "demo", doc)
            with self.assertRaises(ValueError) as cm:
                load_mode_file(p)
        msg = str(cm.exception)
        for needle in needles:
            self.assertIn(needle, msg)

    def test_missing_required_field(self):
        self._expect_error(lambda d: d.pop("software"), "software")

    def test_unknown_name_in_formula(self):
        self._expect_error(
            lambda d: d["geom"]["derived"].update({"rIn_up": "nope * 2"}),
            "nope")

    def test_metric_column_count_must_be_four(self):
        self._expect_error(
            lambda d: d["leaderboard"].update({"columns": ["sob", "obj"]}),
            "columns")

    def test_knob_bounds_lockstep(self):
        def drop_a_knob(d):
            d["knobs"] = d["knobs"][:-1]
        self._expect_error(drop_a_knob, "lockstep")

    def test_profile_without_clip_rejected(self):
        def add_bad_profile(d):
            d["geom"]["profiles"] = {
                "p": {"count": 3, "control": ["extra_f_up"] * 3}}
        self._expect_error(add_bad_profile, "clip")


class TestCollision(unittest.TestCase):
    def test_name_collision_with_python_mode_is_hard_error(self):
        with tempfile.TemporaryDirectory() as td:
            _write(Path(td), "foilsflash", json.loads(FIXTURE.read_text()))
            with self.assertRaises(ValueError) as cm:
                load_mode_dir(Path(td), modes.SPECS)
            self.assertIn("foilsflash", str(cm.exception))
            self.assertIn("collides", str(cm.exception))

    def test_missing_directory_yields_no_modes(self):
        self.assertEqual(load_mode_dir(Path("/nonexistent/modes"), {}), {})


if __name__ == "__main__":
    unittest.main()
