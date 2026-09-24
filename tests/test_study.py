import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _doc_every_level():
    """The demo fixture plus one extra metric, so every schema level the
    loader parses has an object to break."""
    doc = _doc()
    doc["extra_metrics"] = [{"name": "aux", "metric": "sob.aux_value",
                             "fmt": "{:.4e}"}]
    return doc


# (level, getter for the object at that level, its required keys, a needle
# naming that level in the error's field path). `fixed` has no required
# keys: every key is optional by declaration (kit_registry.KitDecl
# fixed_keys), so only its unknown-key case applies; `fixed` itself missing
# from a step is the step level's case. Kit settings are checked by
# kit_registry.validate_study_settings, not study._obj, hence two entries.
_LEVELS = (
    ("top", lambda d: d, st._TOP, ""),
    ("knob", lambda d: d["knobs"][0], st._KNOB, "[knobs[0]]"),
    ("derive", lambda d: d["derive"], st._DERIVE, "[derive]"),
    ("profile", lambda d: d["derive"]["profiles"]["a_p"], st._PROFILE,
     "[derive.profiles.a_p]"),
    ("geom", lambda d: d["geom"], st._GEOM, "[geom]"),
    ("kits.prodtools", lambda d: d["kits"]["prodtools"],
     tuple(kit_registry.KITS["prodtools"].study_keys), "[kits.prodtools]"),
    ("kits.offline_preflight", lambda d: d["kits"]["offline_preflight"],
     tuple(kit_registry.KITS["offline_preflight"].study_keys),
     "[kits.offline_preflight]"),
    ("preflight", lambda d: d["preflight"], st._PREFLIGHT, "[preflight]"),
    ("step", lambda d: d["evaluate"][0], st._STEP, "[evaluate[0]]"),
    ("fixed", lambda d: d["evaluate"][0]["fixed"], (),
     "[evaluate[0]][fixed]"),
    ("objective", lambda d: d["objectives"][0], st._OBJECTIVE,
     "[objectives[0]]"),
    ("constraint", lambda d: d["constraints"][0], ("name", "max", "k_sigma"),
     "[constraints[0]]"),
    ("extra_metric", lambda d: d["extra_metrics"][0], st._EXTRA_METRIC,
     "[extra_metrics[0]]"),
    ("extra_column", lambda d: d["extra_columns"][0], st._EXTRA_COLUMN,
     "[extra_columns[0]]"),
    ("leaderboard", lambda d: d["leaderboard"], st._LEADERBOARD,
     "[leaderboard]"),
)


class TestEveryLevelRejectsUnknownAndMissingKeys(_Tmp):
    """ADR-0002 at every schema level: a typo'd key and a dropped key are
    load errors naming the file, the field path and the offending key.
    Restores the per-level coverage the deleted tests/test_mode_json.py
    had for the old loader."""

    def _message(self, doc):
        path = self.write(doc)
        with self.assertRaises(ValueError) as cm:
            st.load_study_file(path)
        return str(path), str(cm.exception)

    def test_the_every_level_doc_loads(self):
        # Otherwise a rejection below could come from the base doc itself.
        s = self.load(_doc_every_level())
        self.assertEqual([m.name for m in s.extra_metrics], ["aux"])

    def test_unknown_key_at_every_level(self):
        for level, get, _keys, field in _LEVELS:
            doc = _doc_every_level()
            get(doc)["typo_key"] = 1
            with self.subTest(level=level):
                path, msg = self._message(doc)
                self.assertIn("'typo_key'", msg)
                self.assertIn("unknown", msg)
                self.assertIn(path + field, msg)

    def test_missing_key_at_every_level(self):
        for level, get, keys, field in _LEVELS:
            for key in keys:
                doc = _doc_every_level()
                del get(doc)[key]
                with self.subTest(level=level, key=key):
                    path, msg = self._message(doc)
                    self.assertIn(f"'{key}'", msg)
                    self.assertIn(path + field, msg)

    def test_every_level_has_a_required_key_case(self):
        # Guard against the table silently losing a level's keys.
        empty = [lvl for lvl, _g, keys, _f in _LEVELS if not keys]
        self.assertEqual(empty, ["fixed"])


class TestArtifactExpansion(_Tmp):
    """A kits setting '${ARTIFACT}/<rel>' expands to exactly
    paths.artifact(rel): the local artifact root first, then the backing,
    and -- artifact() is total -- the intended local path when neither has
    the file (preflight/submit, not the loader, turn that into a failure).
    Guards the local-vs-backing resolution behind the prodtarget
    env-divergence incident class."""

    REL = "autoresearch_muse/Code_helical_holeradii.tar.bz2"

    def _expanded(self, rel):
        doc = _doc()
        doc["kits"]["prodtools"]["code_tarball"] = "${ARTIFACT}/" + rel
        return self.load(doc).kits["prodtools"]["code_tarball"]

    def test_equals_paths_artifact_for_a_real_looking_rel(self):
        # Environment-independent: whatever this checkout's roots hold.
        self.assertEqual(self._expanded(self.REL),
                         str(st.paths.artifact(self.REL)))

    def test_equals_paths_artifact_for_a_missing_rel(self):
        rel = "no_such_dir_4f1c/Code_missing.tar.bz2"
        got = self._expanded(rel)
        self.assertEqual(got, str(st.paths.artifact(rel)))
        self.assertEqual(got, str(st.paths.ARTIFACT_ROOT / rel))

    def _roots(self):
        local, backing = self.tmp / "local", self.tmp / "backing"
        return local, backing, mock.patch.multiple(
            st.paths, ARTIFACT_ROOT=local, BACKING=backing)

    def _touch(self, root, rel):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")

    def test_local_file_wins(self):
        local, backing, roots = self._roots()
        self._touch(local, self.REL)
        self._touch(backing, self.REL)
        with roots:
            got = self._expanded(self.REL)
            self.assertEqual(got, str(st.paths.artifact(self.REL)))
        self.assertEqual(got, str(local / self.REL))

    def test_backing_fills_in(self):
        local, backing, roots = self._roots()
        self._touch(backing, self.REL)
        with roots:
            got = self._expanded(self.REL)
            self.assertEqual(got, str(st.paths.artifact(self.REL)))
        self.assertEqual(got, str(backing / self.REL))

    def test_missing_everywhere_is_the_local_path(self):
        local, _backing, roots = self._roots()
        with roots:
            got = self._expanded(self.REL)
            self.assertEqual(got, str(st.paths.artifact(self.REL)))
        self.assertEqual(got, str(local / self.REL))


class TestLoaderEdgeCases(_Tmp):
    """Values that used to escape the ADR-0002 messages: a non-string
    params value (was a bare TypeError: unhashable) and the JSON literals
    NaN/Infinity (every comparison with NaN is False, so "> 0" checks
    passed them)."""

    def test_step_params_value_must_be_a_string(self):
        for bad in (["a"], {"k": "a"}, 3, None):
            doc = _doc()
            _step(doc, "mubeam")["params"] = {"radius": bad}
            with self.subTest(value=bad):
                path, msg = self._reject(doc)
                self.assertIn(path + "[evaluate[0]][params.radius]", msg)
                self.assertIn("must be a string", msg)

    def test_preflight_params_value_must_be_a_string(self):
        for bad in (["a"], 3, None):
            doc = _doc()
            doc["preflight"]["params"] = {"radius": bad}
            with self.subTest(value=bad):
                path, msg = self._reject(doc)
                self.assertIn(path + "[preflight][params.radius]", msg)
                self.assertIn("must be a string", msg)

    def test_non_finite_numbers_rejected(self):
        cases = (
            ("[objectives[0]][noise]",
             lambda d, v: d["objectives"][0].__setitem__("noise", v)),
            ("[constraints[0]][k_sigma]",
             lambda d, v: d["constraints"][0].__setitem__("k_sigma", v)),
            ("[constraints[0]][max]",
             lambda d, v: d["constraints"][0].__setitem__("max", v)),
            ("[knobs[0]][min]",
             lambda d, v: d["knobs"][0].__setitem__("min", v)),
            ("[knobs[0]][max]",
             lambda d, v: d["knobs"][0].__setitem__("max", v)),
        )
        for field, put in cases:
            for bad in (float("nan"), float("inf"), float("-inf")):
                doc = _doc()
                put(doc, bad)
                with self.subTest(field=field, value=bad):
                    path, msg = self._reject(doc)
                    self.assertIn(path + field, msg)
                    self.assertIn("finite", msg)

    def test_the_json_literals_reach_the_check(self):
        # json.dumps writes NaN/Infinity literals and json.loads reads them
        # back as floats: the case above is a real file, not a Python-only
        # value.
        doc = _doc()
        doc["objectives"][0]["noise"] = float("nan")
        self.assertIn('"noise": NaN', json.dumps(doc))

    def _reject(self, doc):
        path = self.write(doc)
        with self.assertRaises(ValueError) as cm:
            st.load_study_file(path)
        return str(path), str(cm.exception)


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

    def test_knob_named_after_any_leaderboard_column(self):
        # Ported from the old loader tests (F11); the sob case is
        # test_knob_name_collides_with_column. `config` is a literal column,
        # alpha/obj come from extra_columns: each source must be checked.
        for name in ("config", "flash_edep", "alpha", "obj"):
            doc = _doc()
            doc["knobs"][0]["name"] = name
            doc["derive"]["exprs"] = {"ab": f"{name} * b"}
            doc["derive"]["profiles"]["a_p"]["control"] = [name, "ab", name]
            with self.subTest(name=name):
                self.assertRejects(doc, name, "appears", "twice")

    def test_knob_fmt_without_replacement_field(self):
        # Ported from the old loader tests (R1): fmt "75.0" writes a CONSTANT
        # into every knob column, so every past eval collapses to one point
        # and the GP trains on garbage -- silently.
        doc = _doc()
        doc["knobs"][0]["fmt"] = "75.0"
        self.assertRejects(doc, "75.0", "replacement field")


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

    def test_files_from_bare_string_rejected(self):
        # Ported from the old loader tests (run.stages / presubmit_after as a
        # bare string): tuple("mubeam") would silently be its characters.
        doc = _doc()
        _step(doc, "mustops_ce")["files_from"] = "mubeam"
        self.assertRejects(doc, "files_from", "must be a list")

    def test_fixed_njobs_must_be_a_positive_int(self):
        # Ported from the old loader tests (F6): njobs reaches the jobsub
        # command line unchanged, and isinstance(True, int) is True.
        for bad in (True, 15.5, "20", 0):
            doc = _doc()
            _step(doc, "mubeam")["fixed"]["njobs"] = bad
            with self.subTest(njobs=bad):
                self.assertRejects(doc, "njobs", "positive int")


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

    def test_unknown_variable_token_refused(self):
        # Ported from the old loader tests: only '${ARTIFACT}/' expands.
        doc = _doc()
        doc["kits"]["offline_preflight"]["musing"] = "${HOME}/x/setup.sh"
        self.assertRejects(doc, "ARTIFACT")

    def test_unknown_kit_setting(self):
        # Ported from the old loader tests (unknown software/preflight key):
        # those fields now live in kits.<kit>, whose unknown-key check is
        # kit_registry.validate_study_settings, not the _obj helper.
        doc = _doc()
        doc["kits"]["offline_preflight"]["typo_key"] = True
        self.assertRejects(doc, "typo_key")

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

    def test_absolute_path_rejected(self):
        # Ported from the old loader tests: pathlib's '/' discards the left
        # side when the right is absolute, so the board would escape the repo.
        doc = _doc()
        doc["leaderboard"]["file"] = "/abs/escaped.tsv"
        self.assertRejects(doc, "/abs/escaped.tsv", "repo-relative")

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

    def test_relative_study_path_entry_rejected(self):
        # A relative entry resolves against each process's cwd, and
        # campaign children run elsewhere: refused even if it exists here.
        (self.tmp / "rel").mkdir()
        for extra in ("rel", f"{self.tmp}:rel", "./rel"):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError) as cm:
                    st.load_study_dirs(self.tmp, extra)
                msg = str(cm.exception)
                self.assertIn("AUTORESEARCH_STUDY_PATH", msg)
                self.assertIn("absolute", msg)
                self.assertIn(extra.split(":")[-1], msg)

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

    def test_shared_leaderboard_basename_rejected(self):
        # Ported from the old loader tests: paths.leaderboard_live flattens
        # to the basename, so boards that differ only in directory or by a
        # './' prefix are one live file.
        pairs = (("a/lb_dup.tsv", "b/lb_dup.tsv"),
                 ("leaderboards/lb_dot.tsv", "./leaderboards/lb_dot.tsv"))
        for i, (one, two) in enumerate(pairs):
            d = self.tmp / f"case{i}"
            for name, rel in (("lineone", one), ("linetwo", two)):
                doc = _doc()
                doc["name"] = name
                doc["leaderboard"]["file"] = rel
                self.write(doc, directory=d)
            with self.subTest(pair=(one, two)):
                with self.assertRaises(ValueError) as cm:
                    st.load_study_dirs(d, None)
                self.assertIn("basename", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
