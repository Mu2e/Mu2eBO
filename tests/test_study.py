import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import study as st  # noqa: E402
import kit_registry  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


def _doc():
    return json.loads(FIXTURE.read_text())


def _step(doc, name):
    return next(s for s in doc["evaluate"] if s["step"] == name)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def write(self, doc, name=None, directory=None):
        d = directory or self.tmp
        d.mkdir(parents=True, exist_ok=True)
        # doc.get, not doc[...]: test_every_top_key_required deletes "name"
        # itself to prove the loader rejects that, and the write must not
        # KeyError before load_study_file ever sees the doc.
        p = d / f"{name or doc.get('name', 'study')}.json"
        p.write_text(json.dumps(doc))
        return p

    def load(self, doc):
        return st.load_study_file(self.write(doc))

    def assertRejects(self, doc, *needles):
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        for n in needles:
            self.assertIn(n, str(cm.exception))


class TestFixtureLoads(_Tmp):
    def test_fields(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.name, "demo")
        self.assertEqual(s.knob_names, ("a", "b"))
        self.assertEqual(s.bounds_lo, (1.0, 0.0))
        self.assertEqual(s.int_dims, ())
        self.assertEqual([o.name for o in s.objectives], ["sob", "flash_edep"])
        self.assertEqual(s.objectives[1].step, "flash")
        self.assertEqual(s.objectives[1].key, "flash_edep_per_pot")
        self.assertEqual(s.constraints[0].bound, "max")
        self.assertEqual(s.value_names, ("sob", "flash_edep"))
        self.assertEqual(s.layout, "v1")
        self.assertEqual(s.context, ("alpha",))
        self.assertEqual(s.consts, {"n_el": 5, "z0": 100.0})
        self.assertEqual([x.step for x in s.steps],
                         ["mubeam", "mustops_ce", "elebeam_flash", "sob", "flash"])
        self.assertEqual(s.kits["prodtools"]["code_tarball"][-len("Code_demo.tar.bz2"):],
                         "Code_demo.tar.bz2")
        self.assertNotIn("${", s.kits["prodtools"]["code_tarball"])

    def test_geom_renders_profile(self):
        s = st.load_study_file(FIXTURE)
        text = s.geom.render([2.0, 0.5])
        self.assertIn("double demo.ab = 1.000000;", text)
        self.assertIn("vector<double> demo.radii = {", text)

    def test_extra_column_evaluates(self):
        s = st.load_study_file(FIXTURE)
        obj = next(c for c in s.extra_columns if c.name == "obj")
        self.assertAlmostEqual(
            obj.evaluate({"sob": 3.0, "flash_edep": 1e-6, "alpha": 1e5, **s.consts}),
            2.9)

    def test_spec_sha_is_stable_and_content_sensitive(self):
        a = self.load(_doc())
        doc = _doc()
        doc["note"] = "changed"
        b = self.load(doc)
        self.assertEqual(a.spec_sha, st.load_study_file(FIXTURE).spec_sha)
        self.assertNotEqual(a.spec_sha, b.spec_sha)


class TestTopLevel(_Tmp):
    def test_every_top_key_required(self):
        for key in st._TOP:
            doc = _doc()
            del doc[key]
            with self.subTest(key=key):
                self.assertRejects(doc, key)

    def test_unknown_top_key(self):
        doc = _doc()
        doc["stages"] = []
        self.assertRejects(doc, "stages")

    def test_schema_must_be_2(self):
        doc = _doc()
        doc["schema"] = 1
        self.assertRejects(doc, "schema")

    def test_duplicate_json_key(self):
        p = self.tmp / "demo.json"
        p.write_text(FIXTURE.read_text().replace(
            '"note":', '"note": "x", "note":', 1))
        with self.assertRaises(ValueError) as cm:
            st.load_study_file(p)
        self.assertIn("duplicate JSON key", str(cm.exception))


class TestKnobs(_Tmp):
    def test_int_knob_needs_integer_bounds(self):
        doc = _doc()
        doc["knobs"][0]["type"] = "int"
        doc["knobs"][0]["min"] = 1.5
        self.assertRejects(doc, "integer bounds")

    def test_int_dims_from_type(self):
        doc = _doc()
        doc["knobs"][0]["type"] = "int"
        self.assertEqual(self.load(doc).int_dims, (0,))

    def test_min_below_max(self):
        doc = _doc()
        doc["knobs"][1]["min"] = 2.0
        self.assertRejects(doc, "min")

    def test_knob_name_collides_with_column(self):
        doc = _doc()
        doc["knobs"][0]["name"] = "sob"
        # The rename must carry through everywhere `derive` still says "a",
        # or the load fails inside GeomTemplate before it ever reaches the
        # column-collision check (ruling R3, task-2 brief).
        doc["derive"]["exprs"] = {"ab": "sob * b"}
        doc["derive"]["profiles"]["a_p"]["control"] = ["sob", "ab", "sob"]
        self.assertRejects(doc, "sob", "appears", "twice")

    def test_reserved_elementwise_name(self):
        doc = _doc()
        doc["knobs"][0]["name"] = "i"
        self.assertRejects(doc, "reserved")


class TestDeriveAndGeom(_Tmp):
    def test_profile_kind_must_be_lagrange(self):
        doc = _doc()
        doc["derive"]["profiles"]["a_p"]["kind"] = "spline"
        self.assertRejects(doc, "lagrange")

    def test_derive_without_geom_rejected_in_phase_a(self):
        doc = _doc()
        doc["geom"] = None
        for s in doc["evaluate"]:
            s["files"] = []
        doc["preflight"]["files"] = []
        self.assertRejects(doc, "derive")

    def test_unknown_writer(self):
        doc = _doc()
        doc["geom"]["writer"] = "g4bl_include"
        self.assertRejects(doc, "writer")

    def test_geom_file_without_geom(self):
        doc = _doc()
        doc["geom"] = None
        doc["derive"] = {"consts": {}, "exprs": {}, "profiles": {}}
        self.assertRejects(doc, "geom")


class TestSteps(_Tmp):
    def test_unknown_kit(self):
        doc = _doc()
        _step(doc, "sob")["kit"] = "anakit"
        self.assertRejects(doc, "anakit")

    def test_files_from_unknown_step(self):
        doc = _doc()
        _step(doc, "mustops_ce")["files_from"] = ["nope"]
        self.assertRejects(doc, "nope")

    def test_cycle(self):
        doc = _doc()
        _step(doc, "mubeam")["files_from"] = ["mustops_ce"]
        self.assertRejects(doc, "cycle")

    def test_duplicate_step_name(self):
        doc = _doc()
        _step(doc, "flash")["step"] = "sob"
        self.assertRejects(doc, "duplicate")

    def test_prodtools_step_needs_entry(self):
        doc = _doc()
        _step(doc, "mubeam")["entry"] = None
        self.assertRejects(doc, "entry")

    def test_plugin_step_takes_no_entry(self):
        doc = _doc()
        _step(doc, "sob")["entry"] = "x"
        self.assertRejects(doc, "entry")

    def test_unknown_fixed_key(self):
        doc = _doc()
        _step(doc, "mubeam")["fixed"]["njob"] = 3
        self.assertRejects(doc, "njob")

    def test_fixed_value_type(self):
        doc = _doc()
        _step(doc, "mubeam")["fixed"]["quorum"] = 1.5
        self.assertRejects(doc, "quorum")

    def test_params_name_must_exist(self):
        doc = _doc()
        _step(doc, "mubeam")["params"] = {"x": "nope"}
        self.assertRejects(doc, "nope")


class TestKits(_Tmp):
    def test_missing_kit_setting(self):
        doc = _doc()
        del doc["kits"]["offline_preflight"]["require_zero_overlaps"]
        self.assertRejects(doc, "require_zero_overlaps")

    def test_configured_but_unused_kit(self):
        doc = _doc()
        doc["preflight"] = None   # offline_preflight keeps its settings
        self.assertRejects(doc, "unused")

    def test_used_kit_needs_settings(self):
        doc = _doc()
        del doc["kits"]["prodtools"]
        self.assertRejects(doc, "prodtools")

    def test_preflight_kit_must_offer_check(self):
        doc = _doc()
        doc["preflight"]["kit"] = "prodtools"
        self.assertRejects(doc, "check")

    def test_personal_path_refused(self):
        doc = _doc()
        doc["kits"]["prodtools"]["code_tarball"] = "/exp/mu2e/app/users/somebody/x.tar"  # personal-path-ok: made-up name, exercises the refusal
        self.assertRejects(doc, "personal")

    def test_registry_declares_the_zero_overlap_flag(self):
        self.assertIn("require_zero_overlaps",
                      kit_registry.KITS["offline_preflight"].study_keys)


class TestObjectivesAndConstraints(_Tmp):
    def test_at_least_one_objective(self):
        doc = _doc()
        doc["objectives"] = []
        doc["constraints"] = []
        doc["extra_columns"] = []
        self.assertRejects(doc, "objective")

    def test_metric_names_a_step(self):
        doc = _doc()
        doc["objectives"][0]["metric"] = "nostep.s_over_sqrt_b"
        self.assertRejects(doc, "nostep")

    def test_metric_needs_step_dot_key(self):
        doc = _doc()
        doc["objectives"][0]["metric"] = "s_over_sqrt_b"
        self.assertRejects(doc, "step.key")

    def test_direction_and_transform_enums(self):
        doc = _doc()
        doc["objectives"][0]["direction"] = "up"
        self.assertRejects(doc, "direction")
        doc = _doc()
        doc["objectives"][0]["transform"] = "ln"
        self.assertRejects(doc, "transform")

    def test_at_most_one_constraint(self):
        doc = _doc()
        doc["constraints"].append({"name": "sob", "min": 3.0, "k_sigma": 1.0})
        self.assertRejects(doc, "at most one")

    def test_constraint_needs_exactly_one_bound(self):
        doc = _doc()
        doc["constraints"][0]["min"] = 1e-9
        self.assertRejects(doc, "exactly one")

    def test_constraint_side_must_match_direction(self):
        doc = _doc()
        doc["constraints"] = [{"name": "flash_edep", "min": 1e-9, "k_sigma": 1.0}]
        self.assertRejects(doc, "'max'")

    def test_log10_bound_must_be_positive(self):
        doc = _doc()
        doc["constraints"][0]["max"] = 0.0
        self.assertRejects(doc, "positive")

    def test_extra_column_unknown_name(self):
        doc = _doc()
        doc["extra_columns"][1]["expr"] = "sob - beta"
        self.assertRejects(doc, "beta")


class TestLeaderboard(_Tmp):
    def test_layout_v2_arrives_in_phase_b(self):
        doc = _doc()
        doc["leaderboard"]["layout"] = "v2"
        self.assertRejects(doc, "Phase B")

    def test_dotdot_rejected(self):
        doc = _doc()
        doc["leaderboard"]["file"] = "../x.tsv"
        self.assertRejects(doc, "..")

    def test_context_collides_with_column(self):
        doc = _doc()
        # Keep "alpha" in context: extra_columns[0] ("alpha") passes it
        # through by name, and dropping it here would make the load fail
        # earlier, in _extras (unknown name 'alpha'), never reaching the
        # leaderboard.context collision check this test targets. Adding
        # "sob" (an objective name) is the actual collision under test.
        doc["leaderboard"]["context"] = ["alpha", "sob"]
        self.assertRejects(doc, "context")


class TestDirs(_Tmp):
    def test_name_must_match_stem(self):
        self.write(_doc(), name="other")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp, None)
        self.assertIn("file name", str(cm.exception))

    def test_study_path_adds_a_directory(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["name"] = "extra"
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_extra.tsv"
        self.write(doc, directory=self.tmp / "mine")
        out = st.load_study_dirs(self.tmp / "main", str(self.tmp / "mine"))
        self.assertEqual(sorted(out), ["demo", "extra"])

    def test_duplicate_name_across_dirs(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_other.tsv"
        self.write(doc, directory=self.tmp / "mine")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp / "main", str(self.tmp / "mine"))
        self.assertIn("defined twice", str(cm.exception))

    def test_missing_study_path_dir(self):
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp, str(self.tmp / "nope"))
        self.assertIn("AUTORESEARCH_STUDY_PATH", str(cm.exception))

    def test_shared_leaderboard_rejected(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["name"] = "twin"
        self.write(doc, directory=self.tmp / "main")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp / "main", None)
        self.assertIn("leaderboard", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
