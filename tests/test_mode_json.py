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
                      "obs_noise", "dumps_gdml",
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

    # -- F5: stage_tuning keys are validated against run.stages, exactly as
    # its two siblings (_validate_jobs_per_stage/_validate_presubmit_after)
    # already do. Values were strictly checked; the STAGE NAME was not. ------
    def test_stage_tuning_typo_stage_rejected(self):
        """A pure typo loads fine today and raises only at core/pipeline.py
        module import -- i.e. inside every child at first submit, AFTER
        propose and preflight have already passed (F5)."""
        def mutate(d):
            d["run"]["stage_tuning"]["mubeem"] = {"memory_mb": 2000}
        self._expect_error(mutate, "mubeem")

    def test_stage_tuning_stage_outside_this_chain_rejected(self):
        """'concat' is a real core/pipeline.py STAGES entry but is NOT in
        foilsflash's chain, so the tuning loads clean and is SILENTLY INERT
        forever -- the intended events_per_job never applies, no error (F5)."""
        def mutate(d):
            d["run"]["stage_tuning"]["concat"] = {"events_per_job": 424242}
        self._expect_error(mutate, "concat")

    # -- F6: jobs_per_stage VALUES are validated (keys already were) ---------
    def test_jobs_per_stage_bool_value_rejected(self):
        """Verified: {"mubeam": true} loaded OK. The value flows to
        pipeline.STAGES[...]['njobs'] and then to str(cfg['njobs']) in the
        jobsub command -- loud, but only after the earlier stages' hours have
        already run. isinstance(True, int) is True, so bool needs its own
        rejection (F6)."""
        def mutate(d):
            d["run"]["jobs_per_stage"]["mubeam"] = True
        self._expect_error(mutate, "mubeam", "positive int")

    def test_jobs_per_stage_float_value_rejected(self):
        def mutate(d):
            d["run"]["jobs_per_stage"]["mubeam"] = 15.5
        self._expect_error(mutate, "15.5")

    def test_jobs_per_stage_string_value_rejected(self):
        def mutate(d):
            d["run"]["jobs_per_stage"]["mubeam"] = "20"
        self._expect_error(mutate, "'20'")

    def test_jobs_per_stage_zero_rejected(self):
        def mutate(d):
            d["run"]["jobs_per_stage"]["mubeam"] = 0
        self._expect_error(mutate, "mubeam", "positive int")

    # -- F11: a knob may not be named after a leaderboard column ------------
    def test_knob_named_after_the_sob_column_rejected(self):
        """Verified: a knob named 'sob' makes format_row write a DUPLICATE
        'sob' column; csv.DictReader keeps the last, so load_history_row
        reads the METRIC into that knob coordinate and the GP trains on
        garbage (F11)."""
        def mutate(d):
            d["knobs"][0]["name"] = "sob"
        self._expect_error(mutate, "sob", "reserved leaderboard column")

    def test_knob_named_after_the_second_objective_column_rejected(self):
        def mutate(d):
            d["knobs"][0]["name"] = "flash_edep"
        self._expect_error(mutate, "flash_edep", "reserved leaderboard column")

    def test_knob_named_config_rejected(self):
        def mutate(d):
            d["knobs"][0]["name"] = "config"
        self._expect_error(mutate, "config", "reserved leaderboard column")

    def test_knob_named_alpha_rejected(self):
        def mutate(d):
            d["knobs"][0]["name"] = "alpha"
        self._expect_error(mutate, "alpha", "reserved leaderboard column")

    def test_knob_named_obj_rejected(self):
        def mutate(d):
            d["knobs"][0]["name"] = "obj"
        self._expect_error(mutate, "obj", "reserved leaderboard column")

    # -- F2: `i`/`n` are reserved (the per_index loop scope) -----------------
    def test_knob_named_n_rejected_with_the_knob_locator(self):
        def mutate(d):
            d["knobs"][0]["name"] = "n"
        self._expect_error(mutate, "knobs[0]", "reserved")

    # -- F13: pot_only ships prodtarget's tarball, hardcoded ----------------
    def test_pot_only_chain_with_a_foreign_tarball_rejected(self):
        """core/pipeline.py sets STAGES['pot_only']['code_tarball'] to
        prodtarget's tarball and the per-stage value WINS over the
        SPECS-driven one. A JSON mode declaring run.stages: ['pot_only']
        would silently ship prodtarget's code to the grid while preflight
        validated its OWN musing -- the preflight-passes/grid-diverges
        mechanism of the foilsflash-tarball and foilsg-tarball incidents
        (F13)."""
        def mutate(d):
            d["run"]["stages"] = ["pot_only"]
        self._expect_error(mutate, "pot_only", "code_tarball")


class TestDuplicateJsonKeys(unittest.TestCase):
    """F3(a): plain json.loads accepts duplicate object keys and keeps the
    LAST silently. Editing the first of two duplicated blocks then has no
    effect and no error -- the same silent-wrong-geometry class that tainted
    62 foilsg rows."""

    def _load_text(self, text: str):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "demo.json"
            p.write_text(text)
            return load_mode_file(p)

    def test_plain_json_loads_would_keep_the_last(self):
        """Premise check: this is what the loader used to do."""
        self.assertEqual(
            json.loads('{"consts": {"n_up": 6}, "consts": {"n_up": 7}}'),
            {"consts": {"n_up": 7}})

    def test_duplicate_top_level_key_rejected(self):
        doc = _valid_doc()
        text = json.dumps(doc)
        # splice a second "name" in at the top level
        dup = "{" + json.dumps("name") + ": \"other\", " + text[1:]
        with self.assertRaises(ValueError) as cm:
            self._load_text(dup)
        msg = str(cm.exception)
        self.assertIn("name", msg)
        self.assertIn("duplicate", msg.lower())

    def test_duplicate_nested_key_rejected(self):
        doc = _valid_doc()
        text = json.dumps(doc)
        dup = text.replace('"consts": {', '"consts": {"n_up": 99}, "consts": {', 1)
        with self.assertRaises(ValueError) as cm:
            self._load_text(dup)
        msg = str(cm.exception)
        self.assertIn("consts", msg)
        self.assertIn("duplicate", msg.lower())


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


class TestLeaderboardUniqueness(unittest.TestCase):
    """F4: nothing stopped two modes from writing the SAME leaderboard.

    The copy-paste failure is concrete: clone a fixture into mode_specs/,
    change the name and a knob, miss the leaderboard line (it looks
    plausible) -- and the new line appends into the LIVE foils TSV under an
    identical column schema, which FoilsMode.load_history() then parses as
    foils evals. Silent cross-mode GP contamination, in both directions.
    """

    def _spec_doc(self, name: str, leaderboard: str) -> dict:
        doc = json.loads(FIXTURE.read_text())
        doc["name"] = name
        doc["leaderboard"]["file"] = leaderboard
        return doc

    def test_two_json_modes_sharing_a_leaderboard_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "lineone", self._spec_doc(
                "lineone", "leaderboards/leaderboard_bo_shared.tsv"))
            _write(tmp, "linetwo", self._spec_doc(
                "linetwo", "leaderboards/leaderboard_bo_shared.tsv"))
            with self.assertRaises(ValueError) as cm:
                load_mode_dir(tmp, {})
        msg = str(cm.exception)
        self.assertIn("leaderboard_bo_shared.tsv", msg)
        self.assertIn("lineone", msg)

    def test_json_mode_pointing_at_a_live_python_leaderboard_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "myline", self._spec_doc(
                "myline", "leaderboards/leaderboard_bo_foils_v2.tsv"))
            with self.assertRaises(ValueError) as cm:
                load_mode_dir(tmp, modes.SPECS)
        msg = str(cm.exception)
        self.assertIn("leaderboard_bo_foils_v2.tsv", msg)
        self.assertIn("foils", msg)

    def test_dotted_path_does_not_defeat_the_check(self):
        # foils, not foilsflash: foilsflash became JSON-defined 2026-07-26 and
        # its leaderboard is no longer Python-owned, so it can no longer serve
        # as the "belongs to a Python mode" example here.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "myline", self._spec_doc(
                "myline", "./leaderboards/leaderboard_bo_foils_v2.tsv"))
            with self.assertRaises(ValueError) as cm:
                load_mode_dir(tmp, modes.SPECS)
        self.assertIn("foils", str(cm.exception))

    def test_parent_traversal_in_leaderboard_path_rejected(self):
        doc = self._spec_doc("myline", "../elsewhere/leaderboard.tsv")
        with tempfile.TemporaryDirectory() as td:
            p = _write(Path(td), "myline", doc)
            with self.assertRaises(ValueError) as cm:
                load_mode_file(p)
        self.assertIn("..", str(cm.exception))

    def test_distinct_leaderboards_load_fine(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "lineone", self._spec_doc(
                "lineone", "leaderboards/leaderboard_bo_lineone.tsv"))
            _write(tmp, "linetwo", self._spec_doc(
                "linetwo", "leaderboards/leaderboard_bo_linetwo.tsv"))
            out = load_mode_dir(tmp, modes.SPECS)
        self.assertEqual(sorted(out), ["lineone", "linetwo"])

    def test_python_leaderboard_table_matches_the_driver_classes(self):
        """The loader cannot import bo_driver (bo_driver -> modes ->
        mode_json is already a cycle), so the live Python leaderboard paths
        are frozen in core/mode_json.py. This is the lockstep test that makes
        a renamed Python leaderboard fail HERE instead of re-opening the hole.

        The mode list is DERIVED, not hardcoded: retiring a Python mode must
        also prune its entry from PYTHON_MODE_LEADERBOARDS, or the JSON spec
        that replaces it is locked out of the very leaderboard it is meant to
        inherit. A hardcoded list made that a silent trap (hit for real when
        foilsflash was retired 2026-07-26); deriving it means the retirement
        and the pruning are checked against each other automatically.
        """
        import bo_driver as bo
        import mode_json
        root = Path(__file__).resolve().parent.parent
        # CLASS attribute, not the instance one: botorch_predict.main's
        # --leaderboard override (exercised by tests/test_botorch_predict.py)
        # assigns bo.MODES[...].leaderboard on the INSTANCE and never puts it
        # back, so reading the instance here makes this test order-dependent.
        live = {
            str(type(m).leaderboard.relative_to(root)): n
            for n, m in bo.MODES.items()
            if not isinstance(m, bo.JsonMode)
        }
        self.assertEqual(dict(mode_json.PYTHON_MODE_LEADERBOARDS), live)
        self.assertNotIn("foilsflash", live.values(),
                         "foilsflash is JSON-defined; it must not appear in "
                         "the Python-owned leaderboard table")


class TestCopyPasteTemplate(unittest.TestCase):
    """F4 (second half): mode_specs/README.md advertised
    tests/fixtures/modes/foilsflash.json as the thing to copy -- and that
    file declares the LIVE foilsflash leaderboard, because it exists to prove
    parity against the Python renderer. Copy it, miss the leaderboard line
    (it looks plausible) and the new line appends into a live TSV. The
    loader now rejects that outright, but what the README hands an author
    must not be a live-leaderboard file in the first place.
    """

    ROOT = Path(__file__).resolve().parent.parent
    TEMPLATE = Path(__file__).parent / "fixtures" / "modes" / "template.json"

    def readme(self) -> str:
        return (self.ROOT / "mode_specs" / "README.md").read_text()

    def test_readme_advertises_the_template(self):
        self.assertIn("tests/fixtures/modes/template.json", self.readme())

    def test_template_loads(self):
        spec = load_mode_file(self.TEMPLATE)
        self.assertEqual(spec.name, "template")
        self.assertIsNotNone(spec.geom)
        self.assertTrue(spec.geom.render([v for v in spec.bounds_lo]))

    def test_template_leaderboard_is_not_a_live_one(self):
        import mode_json
        spec = load_mode_file(self.TEMPLATE)
        self.assertNotIn(spec.leaderboard_rel,
                         mode_json.PYTHON_MODE_LEADERBOARDS)

    def test_readme_documents_the_int_fmt_limitation(self):
        """F14: _validate_fmt probes with a float, so "{:d}" is rejected at
        load even for a knob listed in int_dims -- authors must write
        "{:.0f}". Loud, not silent; documented rather than changed (a {:d}
        fmt genuinely breaks on the float path)."""
        readme = self.readme()
        self.assertIn("{:d}", readme)
        self.assertIn("{:.0f}", readme)


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
