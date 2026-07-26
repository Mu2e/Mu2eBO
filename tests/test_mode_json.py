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

    # -- C1: columns[0] must be exactly "sob" ------------------------------
    def test_columns_first_entry_must_be_sob(self):
        """Verified bug: any other first-column name is silently swallowed by
        BOMode.load_history's `except (KeyError, ValueError): continue`,
        yielding ZERO history rows and an eternal BO cold-start (Critical
        finding #1)."""
        self._expect_error(
            lambda d: d["leaderboard"].update(
                {"columns": ["s_over_sqrt_b", "flash_edep", "alpha", "obj"]}),
            "sob", "load_history_row")

    # -- I4: run.stage_tuning keys are validated ----------------------------
    def test_stage_tuning_unknown_key_rejected(self):
        def mutate(d):
            d["run"]["stage_tuning"]["mubeam"]["njobs"] = 99
        self._expect_error(mutate, "njobs")

    def test_stage_tuning_events_per_job_must_be_positive_int(self):
        def mutate(d):
            d["run"]["stage_tuning"]["mubeam"]["events_per_job"] = -1
        self._expect_error(mutate, "events_per_job")

    def test_stage_tuning_quorum_must_be_in_unit_interval(self):
        def mutate(d):
            d["run"]["stage_tuning"]["mubeam"]["quorum"] = 1.5
        self._expect_error(mutate, "quorum")

    # -- I5: unknown keys are rejected at every level -----------------------
    def test_unknown_top_level_key_rejected(self):
        self._expect_error(
            lambda d: d.update({"intdims": [0]}),  # typo of int_dims
            "intdims")

    def test_unknown_run_key_rejected(self):
        """Verified bug: 'jobs_per_stagez' (typo of jobs_per_stage) silently
        no-ops to stage_target_overrides={} with no error (Important
        finding #5)."""
        self._expect_error(
            lambda d: d["run"].update({"jobs_per_stagez": {"mubeam": 5}}),
            "jobs_per_stagez")

    def test_unknown_software_key_rejected(self):
        self._expect_error(
            lambda d: d["software"].update({"typo_key": "x"}), "typo_key")

    def test_unknown_leaderboard_key_rejected(self):
        self._expect_error(
            lambda d: d["leaderboard"].update({"typo_key": "x"}), "typo_key")

    def test_unknown_preflight_key_rejected(self):
        self._expect_error(
            lambda d: d["preflight"].update({"typo_key": "x"}), "typo_key")

    def test_unknown_knob_key_rejected(self):
        def mutate(d):
            d["knobs"][0]["typo_key"] = 1
        self._expect_error(mutate, "typo_key")

    def test_unknown_geom_top_level_key_rejected(self):
        self._expect_error(
            lambda d: d["geom"].update({"typo_key": {}}), "typo_key")

    # -- Minor: run.stages must be a list, not a bare string ----------------
    def test_run_stages_as_string_rejected(self):
        """A bare string silently becomes a tuple of its characters via
        tuple(str) (Minor finding)."""
        self._expect_error(
            lambda d: d["run"].update({"stages": "mubeam"}), "stages")

    # -- Minor: leaderboard.file must be repo-relative ----------------------
    def test_leaderboard_file_absolute_path_rejected(self):
        """An absolute path silently escapes ROOT: pathlib's '/' operator
        discards the left operand when the right is absolute (Minor
        finding)."""
        self._expect_error(
            lambda d: d["leaderboard"].update({"file": "/tmp/escaped.tsv"}),
            "/tmp/escaped.tsv", "repo-relative")

    # -- R1: knob fmt is validated the same way geom lines are --------------
    def test_knob_fmt_without_replacement_field_rejected(self):
        """Verified bug: fmt='75.0' (no replacement field) writes a CONSTANT
        into every knob column of the leaderboard; load_history_row parses
        it back as a valid float, so every past eval collapses to the same
        point and the GP trains on garbage -- silently (R1 in the final
        review)."""
        def mutate(d):
            d["knobs"][0]["fmt"] = "75.0"
        self._expect_error(mutate, "75.0", "replacement field")

    def test_knob_fmt_malformed_rejected(self):
        def mutate(d):
            d["knobs"][0]["fmt"] = "{:.4q}"
        self._expect_error(mutate, "{:.4q}")

    # -- X3: jobs_per_stage / presubmit_after / metrics validated against
    # declared stages / required list shape ----------------------------------
    def test_jobs_per_stage_unknown_stage_rejected(self):
        """Verified bug: a typo'd stage ('mubeem') loads fine and silently
        adds a dead key to STAGE_TARGETS, leaving the real stage at its
        default job count (X3 in the final review)."""
        self._expect_error(
            lambda d: d["run"]["jobs_per_stage"].update({"mubeem": 15}),
            "mubeem")

    def test_presubmit_after_unknown_stage_key_rejected(self):
        self._expect_error(
            lambda d: d["run"]["presubmit_after"].update(
                {"mubeem": ["elebeam_flash"]}),
            "mubeem")

    def test_presubmit_after_bare_string_value_rejected(self):
        """A bare string value silently becomes a tuple of its characters
        via tuple(str) (X3)."""
        def mutate(d):
            d["run"]["presubmit_after"]["mubeam"] = "elebeam_flash"
        self._expect_error(mutate, "presubmit_after")

    def test_metrics_bare_string_value_rejected(self):
        """A bare string value here fails the same way, but only after a
        ~4.5h grid evaluation (X3)."""
        def mutate(d):
            d["leaderboard"]["metrics"]["sob"] = "s_over_sqrt_b"
        self._expect_error(mutate, "metrics")

    # -- Minor: int_dims index must be within the knob count -----------------
    def test_int_dims_out_of_range_rejected(self):
        self._expect_error(lambda d: d.update({"int_dims": [99]}), "99")

    # -- Minor: knob min must be < max ---------------------------------------
    def test_knob_min_ge_max_rejected(self):
        def mutate(d):
            d["knobs"][0]["min"] = 300.0
            d["knobs"][0]["max"] = 250.0
        self._expect_error(mutate, "min", "max")


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
    """Only ONE copy of each of these modules may be live in the suite process.

    `core/modes.py` (and its siblings core/geom_template.py, core/bo_driver.py)
    are importable two ways -- bare (core/ on sys.path, which is how
    bo_driver.py runs as a subprocess and how this suite imports) and
    qualified `core.<module>`. If both load, Python builds two non-identical
    copies of the same class (ModeSpec, GeomTemplate, ...) and any isinstance
    check or `is`-identity across them silently returns False. Every test
    file here must therefore use the bare convention. tests/test_geom_template.py
    was the gap that motivated the geom_template/bo_driver entries below (I7
    in the json-configurable-modes final review) -- it used qualified
    `core.geom_template`/`core.bo_driver` imports until fixed.
    """
    def test_qualified_modes_module_is_not_loaded(self):
        self.assertNotIn(
            "core.modes", sys.modules,
            "core.modes is loaded alongside bare `modes`, which creates two "
            "non-identical ModeSpec classes. Some test module is importing "
            "`from core import modes` -- switch it to the sys.path.insert + "
            "bare `import modes` convention used by tests/test_modes.py.")

    def test_qualified_geom_template_module_is_not_loaded(self):
        self.assertNotIn(
            "core.geom_template", sys.modules,
            "core.geom_template is loaded alongside bare `geom_template`, "
            "which creates two non-identical GeomTemplate/ExprError classes. "
            "Some test module is importing `from core.geom_template import "
            "...` -- switch it to the sys.path.insert + bare `import "
            "geom_template` convention used by tests/test_mode_json.py.")

    def test_qualified_bo_driver_module_is_not_loaded(self):
        self.assertNotIn(
            "core.bo_driver", sys.modules,
            "core.bo_driver is loaded alongside bare `bo_driver`, which "
            "creates two non-identical MODES/ModeSpec-consuming classes. "
            "Some test module is importing `from core.bo_driver import "
            "...` -- switch it to the sys.path.insert + bare `import "
            "bo_driver` convention used by tests/test_json_mode.py.")


if __name__ == "__main__":
    unittest.main()
