import json
import sys
import tempfile
import unittest
from pathlib import Path

# Match the rest of the suite (tests/test_modes.py, test_harvest.py,
# test_input_probe.py): insert core/ onto sys.path and import `modes` bare,
# so exactly one `modes` module (and one ModeSpec class) is ever live in
# this process. `from core import modes` here as well would load a SECOND,
# non-identical copy under the `core.modes` sys.modules key -- see
# TestSingleModeSpecClass below, which pins this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
from mode_json import load_mode_dir, load_mode_file  # noqa: E402

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

    def test_dropping_a_knob_referenced_by_geom_is_rejected(self):
        """Dropping a knob leaves a geom formula referencing a name that no
        longer exists; GeomTemplate's own error must name it."""
        def drop_a_knob(d):
            d["knobs"] = d["knobs"][:-1]
        self._expect_error(drop_a_knob, "extra_f_dn")

    def test_missing_leaderboard_file_is_rejected(self):
        self._expect_error(lambda d: d["leaderboard"].pop("file"), "file")

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


class TestSingleModeSpecClass(unittest.TestCase):
    """Only ONE modes module may be live in the suite process.

    `core/modes.py` is importable two ways -- bare `modes` (core/ on sys.path,
    which is how bo_driver.py runs as a subprocess and how this suite imports)
    and qualified `core.modes`. If both load, Python builds two non-identical
    ModeSpec classes and any isinstance check across them silently returns
    False. Every test file here must therefore use the bare convention.
    """
    def test_qualified_modes_module_is_not_loaded(self):
        self.assertNotIn(
            "core.modes", sys.modules,
            "core.modes is loaded alongside bare `modes`, which creates two "
            "non-identical ModeSpec classes. Some test module is importing "
            "`from core import modes` -- switch it to the sys.path.insert + "
            "bare `import modes` convention used by tests/test_modes.py.")


if __name__ == "__main__":
    unittest.main()
