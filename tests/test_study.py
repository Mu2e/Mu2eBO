import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
import kit_registry  # noqa: E402
from tests.engine_fixtures import TmpCase  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


def _doc():
    return json.loads(FIXTURE.read_text())


def _add_digi(doc):
    """A third prodtools step with its own desc_fmt (one per study)."""
    template = json.loads((ROOT / "stage_entries" / "elebeam_flash.json").read_text())
    template["desc_fmt"] = "Run1A_Digi_{cfg}"
    doc["evaluate"].append(dict(_step(doc, "elebeam_flash"), step="digi",
                                entry=template))


def _step(doc, name):
    return next(s for s in doc["evaluate"] if s["step"] == name)


def _template(name):
    return json.loads((ROOT / "stage_entries" / f"{name}.json").read_text())


def _rename_knob_a(name):
    """Knob 'a' renamed to `name`, carried through everywhere `derive`
    still says "a" -- or the load fails inside GeomTemplate before it ever
    reaches the column-collision check (ruling R3, task-2 brief)."""
    def mutate(d):
        d["knobs"][0]["name"] = name
        d["derive"]["exprs"] = {"ab": f"{name} * b"}
        d["derive"]["profiles"]["a_p"]["control"] = [name, "ab", name]
    return mutate


class _Tmp(TmpCase):
    def write(self, doc, name=None, directory=None):
        d = directory or self.tmp
        d.mkdir(parents=True, exist_ok=True)
        # doc.get, not doc[...]: test_missing_key_at_every_level deletes
        # "name" itself to prove the loader rejects that, and the write must
        # not KeyError before load_study_file ever sees the doc.
        p = d / f"{name or doc.get('name', 'study')}.json"
        p.write_text(json.dumps(doc))
        return p

    def load(self, doc):
        return st.load_study_file(self.write(doc))

    def _reject(self, doc):
        """Load `doc`, expecting a ValueError; return (path, message)."""
        path = self.write(doc)
        with self.assertRaises(ValueError) as cm:
            st.load_study_file(path)
        return str(path), str(cm.exception)

    def assertRejects(self, doc, *needles):
        _path, msg = self._reject(doc)
        for n in needles:
            self.assertIn(n, msg)

    def assertRefusesEach(self, cases):
        """One subTest per (label, mutate, *needles): `mutate` edits a fresh
        demo doc, whose load must fail naming every needle."""
        for label, mutate, *needles in cases:
            with self.subTest(label):
                doc = _doc()
                mutate(doc)
                self.assertRejects(doc, *needles)


class TestFixtureLoads(_Tmp):
    def test_fields(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.name, "demo")
        self.assertEqual(s.knob_names, ("a", "b"))
        self.assertEqual(s.bounds_lo, (1.0, 0.0))
        self.assertEqual(s.int_dims, ())
        self.assertEqual([o.name for o in s.objectives], ["sob", "flash_edep"])
        self.assertEqual(s.objectives[1].metric, "flash.flash_edep_per_pot")
        self.assertEqual(s.constraints[0].bound, "max")
        self.assertEqual(s.layout, "v2")
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
    # Missing and unknown top-level keys: _LEVELS' "top" row.
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
# kit_registry.validate, not study._obj, hence two entries.
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

    def test_the_every_level_doc_loads(self):
        # Otherwise a rejection below could come from the base doc itself.
        s = self.load(_doc_every_level())
        self.assertEqual([m.name for m in s.extra_metrics], ["aux"])

    def test_unknown_key_at_every_level(self):
        for level, get, _keys, field in _LEVELS:
            doc = _doc_every_level()
            get(doc)["typo_key"] = 1
            with self.subTest(level=level):
                path, msg = self._reject(doc)
                self.assertIn("'typo_key'", msg)
                self.assertIn("unknown", msg)
                self.assertIn(path + field, msg)

    def test_missing_key_at_every_level(self):
        for level, get, keys, field in _LEVELS:
            for key in keys:
                doc = _doc_every_level()
                del get(doc)[key]
                with self.subTest(level=level, key=key):
                    path, msg = self._reject(doc)
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
        doc["kits"]["offline_preflight"]["code_tarball"] = "${ARTIFACT}/" + rel
        return self.load(doc).kits["prodtools"]["code_tarball"]

    def test_local_then_backing_then_intended_local(self):
        # (roots holding the file, root the expansion must land in)
        cases = ((("local", "backing"), "local"),
                 (("backing",), "backing"),
                 ((), "local"))
        for i, (holders, want) in enumerate(cases):
            roots = {r: self.tmp / f"case{i}" / r
                     for r in ("local", "backing")}
            for r in holders:
                (roots[r] / self.REL).parent.mkdir(parents=True)
                (roots[r] / self.REL).write_text("")
            with self.subTest(holders=holders):
                with mock.patch.multiple(st.paths,
                                         ARTIFACT_ROOT=roots["local"],
                                         BACKING=roots["backing"]):
                    got = self._expanded(self.REL)
                    self.assertEqual(got, str(st.paths.artifact(self.REL)))
                self.assertEqual(got, str(roots[want] / self.REL))


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

    def test_preflight_params_name_must_exist(self):
        # The design's params rule (a knob, const, expr or profile name)
        # holds for the preflight as for a step.
        doc = _doc()
        doc["preflight"]["params"] = {"radius": "nope"}
        path, msg = self._reject(doc)
        self.assertIn(path + "[preflight][params.radius]", msg)
        self.assertIn("'nope'", msg)

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


class TestKnobs(_Tmp):
    def test_refusals(self):
        self.assertRefusesEach([
            ("int knob needs integer bounds",
             lambda d: d["knobs"][0].update(type="int", min=1.5),
             "integer bounds"),
            ("min below max", lambda d: d["knobs"][1].update(min=2.0), "min"),
            ("duplicate knob name",
             lambda d: d["knobs"].append(dict(d["knobs"][0])),
             "[knobs.a]", "appears twice"),
            ("reserved elementwise name",
             lambda d: d["knobs"][0].update(name="i"), "reserved"),
            # Ported from the old loader tests (R1): fmt "75.0" writes a
            # CONSTANT into every knob column, so every past eval collapses
            # to one point and the GP trains on garbage -- silently.
            ("knob fmt without replacement field",
             lambda d: d["knobs"][0].update(fmt="75.0"),
             "75.0", "replacement field"),
            # A knob named after any leaderboard column (F11, ported from
            # the old loader tests): sob is an objective, `config` a literal
            # column, alpha/obj come from extra_columns, and the board
            # appends handles/spec_sha/measure_sha/time to every row
            # (leaderboard.V2_META) -- a study column of one of those names
            # loaded fine, then its header held the name twice,
            # csv.DictReader kept the last one, and every load after the
            # first append raised RowParseError. Each source is checked.
            *[(f"knob named {name!r}", _rename_knob_a(name),
               name, "appears", "twice")
              for name in ("sob", "config", "flash_edep", "alpha", "obj",
                           "handles", "spec_sha", "measure_sha", "time")],
        ])

    def test_int_dims_from_type(self):
        doc = _doc()
        doc["knobs"][0]["type"] = "int"
        self.assertEqual(self.load(doc).int_dims, (0,))


def _derive_without_geom(d):
    d["geom"] = None
    for step in d["evaluate"]:
        step["files"] = []
    d["preflight"]["files"] = []


def _knob_profile(clip):
    """a_p controlled by the knob alone, with this clip."""
    return lambda d: d["derive"]["profiles"]["a_p"].update(
        control=["a", "a", "a"], clip=clip)


class TestDeriveAndGeom(_Tmp):
    def test_refusals(self):
        self.assertRefusesEach([
            ("profile kind must be lagrange",
             lambda d: d["derive"]["profiles"]["a_p"].update(kind="spline"),
             "lagrange"),
            # Knob bounds narrowed but the clip left as it was: the profile
            # leaves the search box between control points.
            ("knob profile clip wider than its knobs", _knob_profile([0.0, 10.0]),
             "a_p", "clip", "[1.0, 3.0]"),
            # A knob value outside the clip is clamped: a flat region the
            # search cannot see.
            ("knob profile clip narrower than its knobs",
             _knob_profile([1.5, 2.5]), "a_p", "clip", "[1.0, 3.0]"),
            ("derive without geom (phase A)", _derive_without_geom, "derive"),
            ("unknown writer",
             lambda d: d["geom"].update(writer="g4bl_include"), "writer"),
            ("geom file without geom",
             lambda d: d.update(geom=None, derive={"consts": {}, "exprs": {},
                                                   "profiles": {}}),
             "geom"),
        ])

    def test_a_knob_profile_clip_equal_to_its_knobs_loads(self):
        doc = _doc()
        _knob_profile([1.0, 3.0])(doc)
        self.assertIn("a_p", self.load(doc).derive["profiles"])

    def test_a_profile_with_an_expression_control_keeps_its_clip(self):
        doc = _doc()          # a_p controls a, ab (an expression), a
        self.assertEqual(doc["derive"]["profiles"]["a_p"]["clip"], [0.0, 10.0])
        self.load(doc)


class TestSteps(_Tmp):
    def test_refusals(self):
        def fixed(step, **kv):
            return lambda d: _step(d, step)["fixed"].update(kv)

        self.assertRefusesEach([
            ("two steps with one desc_fmt",
             lambda d: _step(d, "mustops_ce").update(entry="mubeam"),
             "mubeam", "mustops_ce", "desc_fmt"),
            ("an inline entry sharing a desc_fmt",
             lambda d: _step(d, "mustops_ce").update(entry=_template("mubeam")),
             "mubeam", "mustops_ce", "desc_fmt"),
            ("unknown kit", lambda d: _step(d, "sob").update(kit="nosuchkit"),
             "nosuchkit"),
            ("files_from an unknown step",
             lambda d: _step(d, "mustops_ce").update(files_from=["nope"]),
             "nope"),
            ("cycle",
             lambda d: _step(d, "mubeam").update(files_from=["mustops_ce"]),
             "cycle"),
            ("duplicate step name",
             lambda d: _step(d, "flash").update(step="sob"), "duplicate"),
            ("prodtools step needs an entry",
             lambda d: _step(d, "mubeam").update(entry=None), "entry"),
            ("plugin step takes no entry",
             lambda d: _step(d, "sob").update(entry="x"), "entry"),
            ("fixed value type", fixed("mubeam", quorum=1.5), "quorum"),
            ("params name must exist",
             lambda d: _step(d, "mubeam").update(params={"x": "nope"}), "nope"),
            ("a step nothing uses", _add_digi, "evaluate.digi", "nothing uses"),
            # Ported from the old loader tests (run.stages / presubmit_after
            # as a bare string): tuple("mubeam") would silently be its
            # characters.
            ("files_from as a bare string",
             lambda d: _step(d, "mustops_ce").update(files_from="mubeam"),
             "files_from", "must be a list"),
            # Ported from the old loader tests (F6): njobs reaches the
            # jobsub command line unchanged, and isinstance(True, int) is
            # True.
            *[(f"njobs={bad!r}", fixed("mubeam", njobs=bad),
               "njobs", "positive int") for bad in (True, 15.5, "20", 0)],
            # `entry` is reserved for a kit that takes templates.
            ("entry as a param",
             lambda d: _step(d, "mubeam")["params"].update(entry="a"),
             "[evaluate[0]][params.entry]", "reserved"),
            ("entry as a fixed value", fixed("mubeam", entry=1),
             "[evaluate[0]][fixed.entry]", "reserved"),
            ("entry as a kit setting",
             lambda d: d["kits"]["prodtools"].update(entry="x"),
             "[kits.prodtools][entry]", "reserved"),
        ])

    def test_an_extra_metric_makes_a_step_used(self):
        doc = _doc()
        _add_digi(doc)
        doc["extra_metrics"].append({"name": "digi_jobs",
                                     "metric": "digi.njobs_ok", "fmt": "{:.0f}"})
        self.assertEqual(self.load(doc).steps[-1].step,
                         "digi")


class TestKits(_Tmp):
    # Missing and unknown kit settings: _LEVELS' kits.* rows.
    def test_refusals(self):
        self.assertRefusesEach([
            # offline_preflight keeps its settings
            ("configured but unused kit", lambda d: d.update(preflight=None),
             "unused"),
            ("used kit needs settings", lambda d: d["kits"].pop("prodtools"),
             "prodtools"),
            ("preflight kit must offer check",
             lambda d: d["preflight"].update(kit="prodtools"), "check"),
            ("personal path",
             lambda d: d["kits"]["prodtools"].update(code_tarball="/exp/mu2e/app/users/somebody/x.tar"),  # personal-path-ok: made-up name, exercises the refusal
             "personal"),
            # Ported from the old loader tests: only '${ARTIFACT}/' expands.
            ("unknown variable token",
             lambda d: d["kits"]["offline_preflight"].update(
                 code_tarball="${HOME}/x/Code.tar.bz2"),
             "ARTIFACT"),
            # classify() (core/adapters/preflight_checks.py) only reads
            # require_zero_overlaps INSIDE the `if checks_managed_overlap:`
            # block, so this combination silently never enforces the policy
            # (F3, 2026-09-26; tests/test_zero_overlap_policy.py pins the
            # same rule on the loaded studies' settings).
            ("zero-overlap policy needs the managed-overlap check",
             lambda d: d["kits"]["offline_preflight"].update(
                 require_zero_overlaps=True, checks_managed_overlap=False),
             "checks_managed_overlap", "require_zero_overlaps"),
            # MATCHING_SETTINGS: the pre-check and the jobs must name one
            # code tarball.
            ("the pre-check names another code tarball",
             lambda d: d["kits"]["offline_preflight"].update(
                 code_tarball="${ARTIFACT}/demo/Other.tar.bz2"),
             "[kits.offline_preflight.code_tarball]",
             "${ARTIFACT}/demo/Other.tar.bz2", "kits.prodtools.code_tarball",
             "${ARTIFACT}/demo/Code_demo.tar.bz2"),
        ])

    def test_registry_declares_the_zero_overlap_flag(self):
        self.assertIn("require_zero_overlaps",
                      kit_registry.KITS["offline_preflight"].study_keys)


class TestMatchingSettings(_Tmp):
    # The refusal of two tarballs is a TestKits case.
    def test_the_fixture_names_one_tarball_for_both(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.kits["offline_preflight"]["code_tarball"],
                         s.kits["prodtools"]["code_tarball"])
        self.assertNotIn("musing", s.kits["offline_preflight"])

    def test_the_rule_needs_both_kits(self):
        # A study that doesn't use offline_preflight at all names only one
        # side of the MATCHING_SETTINGS pair in kits_raw; the rule must not
        # fire (nothing to compare against), and the lone kit still loads
        # with its own settings intact.
        doc = _doc()
        doc["preflight"] = None
        del doc["kits"]["offline_preflight"]
        s = self.load(doc)
        self.assertEqual(set(s.kits), {"prodtools", "anakit"})
        self.assertTrue(
            s.kits["prodtools"]["code_tarball"].endswith("Code_demo.tar.bz2"))


def _obj(**kv):
    return lambda d: d["objectives"][0].update(kv)


class TestObjectivesAndConstraints(_Tmp):
    def test_refusals(self):
        self.assertRefusesEach([
            ("at least one objective",
             lambda d: d.update(objectives=[], constraints=[], extra_columns=[]),
             "objective"),
            ("metric names a step", _obj(metric="nostep.s_over_sqrt_b"),
             "nostep"),
            ("metric needs step.key", _obj(metric="s_over_sqrt_b"), "step.key"),
            ("direction enum", _obj(direction="up"), "direction"),
            ("transform enum", _obj(transform="ln"), "transform"),
            ("at most one constraint",
             lambda d: d["constraints"].append(
                 {"name": "sob", "min": 3.0, "k_sigma": 1.0}),
             "at most one"),
            ("constraint needs exactly one bound",
             lambda d: d["constraints"][0].update(min=1e-9), "exactly one"),
            ("constraint side must match direction",
             lambda d: d.update(constraints=[
                 {"name": "flash_edep", "min": 1e-9, "k_sigma": 1.0}]),
             "'max'"),
            ("log10 bound must be positive",
             lambda d: d["constraints"][0].update(max=0.0), "positive"),
            ("extra column unknown name",
             lambda d: d["extra_columns"][1].update(expr="sob - beta"), "beta"),
        ])


class TestLeaderboard(_Tmp):
    def test_refusals(self):
        def board(**kv):
            return lambda d: d["leaderboard"].update(kv)

        self.assertRefusesEach([
            ("dotdot", board(file="../x.tsv"), ".."),
            # Ported from the old loader tests: pathlib's '/' discards the
            # left side when the right is absolute, so the board would
            # escape the repo.
            ("absolute path", board(file="/abs/escaped.tsv"),
             "/abs/escaped.tsv", "repo-relative"),
            # Keep "alpha" in context: extra_columns[0] ("alpha") passes it
            # through by name, and dropping it here would make the load fail
            # earlier, in _extras (unknown name 'alpha'), never reaching the
            # leaderboard.context collision check this case targets. Adding
            # "sob" (an objective name) is the actual collision under test.
            ("context collides with a column",
             board(context=["alpha", "sob"]), "context"),
        ])


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


class TestEntryTemplate(_Tmp):
    def test_the_resolved_template_is_a_copy(self):
        s = st.load_study_file(FIXTURE)
        want = json.loads((Path(__file__).resolve().parent.parent
                           / "stage_entries" / "mubeam.json").read_text())
        got = s.entry_template("mubeam")
        self.assertEqual(got, want)
        got["njobs"] = -1
        self.assertEqual(s.entry_template("mubeam")["njobs"], want["njobs"])

    def test_an_unknown_step(self):
        with self.assertRaises(KeyError):
            st.load_study_file(FIXTURE).entry_template("nope")


class TestProdtoolsKeys(_Tmp):
    def test_refusals(self):
        def prodtools(**kv):
            return lambda d: d["kits"]["prodtools"].update(kv)

        self.assertRefusesEach([
            ("a prodtools step without quorum",
             lambda d: _step(d, "mubeam")["fixed"].pop("quorum"),
             "evaluate[0]", "quorum"),
            ("njobs over 200",
             lambda d: _step(d, "elebeam_flash")["fixed"].update(njobs=201),
             "njobs", "200"),
            # fatal_log_codes must be a list of strings
            *[(f"fatal_log_codes={bad!r}", prodtools(fatal_log_codes=bad),
               "fatal_log_codes") for bad in ("GeomSolids1001", [""], [3])],
            # dsconf holds {cfg} and only name characters
            *[(f"dsconf={bad!r}", prodtools(dsconf=bad),
               "[kits.prodtools][dsconf]", needle)
              for bad, needle in (("Run1Bak", "{cfg}"), (7, "{cfg}"),
                                  ("Run1Bak-{cfg}", "'-'"),
                                  ("Run1Bak_{cfg}_{geom}", "'{'"))],
        ])

    def test_the_fixture_carries_the_codes_and_every_quorum(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.kits["prodtools"]["fatal_log_codes"],
                         ["GeomSolids1001"])
        for step in s.steps:
            if step.kit == "prodtools":
                self.assertIn("quorum", step.fixed, step.step)

    def test_the_fixture_names_the_pipelines_run_label(self):
        self.assertEqual(st.load_study_file(FIXTURE).kits["prodtools"]["dsconf"],
                         "Run1Bak_{cfg}")


# measure_basis_sha of every study: a change moves its board, so re-pin only
# on purpose. ptg4bl's is still the one from 8cea00a, before params_from
# existed (an empty params_from left every study as it was); the anakit
# studies were re-pinned on 2026-10-07 for M. MacKenzie's analyses.
# foilspf_nominal moved here from tests/fixtures/engine_studies/ on
# 2026-10-08 with its sha unchanged (its board holds the damage budget).
PINNED = {
    "ce_chain": "3a300aecbea8dba8d289c4f78c4a941b01ec18c2293a14a793b86f7263e59189",
    "foilsflash_ax": "b96e6c99648c677b5046f7f223df5477eba156dc27ecb15aaed57d31e6b904bd",
    "foilspf_nominal": "f0a9aa00d9d06eeb8235281fc035ad78b0852b4cdf3e487c919412e247539310",
    "foilspfbpz_ax": "fa84cd6e195e4ef865d62c42f8085deb24a81213197a814e23aab49f8856c570",
    "ptg4bl": "b52fce7c37525597cae53862efe0f272af28f766c6deaefa22b71f08a6861689",
}


def _params_from(step, value):
    return lambda d: _step(d, step).update(params_from=value)


def _drop_params_from(d):
    for step in d["evaluate"]:
        del step["params_from"]


def _clash(params_from, params):
    def mutate(d):
        s = _step(d, "sob")
        s["params_from"], s["params"] = params_from, params
    return mutate


class TestParamsFrom(_Tmp):
    def test_existing_studies_keep_their_measure_basis_sha(self):
        got = {}
        for path in sorted((ROOT / "mode_specs").glob("*.json")):
            s = st.load_study_file(path)
            got[s.name] = s.measure_basis_sha
        self.assertEqual(got, PINNED)

    def test_refusals(self):
        self.assertRefusesEach([
            ("params_from is required", _drop_params_from,
             "missing required field(s) ['params_from']"),
            ("params_from must be an object", _params_from("sob", ["flash.v"]),
             "params_from", "must be an object"),
            *[(f"source {bad!r}", _params_from("sob", {"x": bad}),
               "params_from.x", "must be 'step.key'")
              for bad in ("flash", "flash.a.b", 3)],
            ("an unknown source step", _params_from("sob", {"x": "nope.v"}),
             "params_from.x", "'nope'"),
            ("a self reference", _params_from("sob", {"x": "sob.v"}),
             "params_from.x", "its own result"),
            # The fork's analyses took these; M. MacKenzie's do not
            # (docs/superpowers/specs/2026-10-07-upstream-analyses-design.md).
            *[(f"retired anakit setting {key}",
               lambda d, key=key: _step(d, "sob")["fixed"].update(
                   {key: "/t.tbl" if key == "dio_table" else 0.5}),
               key)
              for key in ("input_correction", "dio_fraction", "dio_table",
                          "pot_per_electron")],
            # The setting is hashed as written, so a second spelling of the
            # same Musing would give a second measure_sha (a board refused
            # at launch).
            *[(f"musing {bad!r}",
               lambda d, bad=bad: d["kits"]["anakit"].update(musing=bad),
               "[kits.anakit][musing]", "'SimJob MDC2025ay'")
              for bad in ("SimJob/MDC2025ay", "SimJob  MDC2025ay",
                          " SimJob MDC2025ay", "SimJob",
                          "SimJob MDC2025ay extra", 3)],
            # A name sent twice: params_from, params, fixed, kit settings.
            *[(label, _clash(params_from, params),
               "evaluate.sob", f"['{name}']", "more than once")
              for label, params_from, params, name in (
                  ("params_from vs fixed", {"analysis": "flash.v"}, {},
                   "analysis"),
                  ("params_from vs setting", {"musing": "flash.v"}, {},
                   "musing"),
                  ("params_from vs params", {"k": "flash.v"}, {"k": "a"}, "k"),
                  ("params vs fixed", {}, {"analysis": "a"}, "analysis"))],
            ("a cycle through params_from",
             _params_from("mubeam", {"x": "mustops_ce.v"}), "cycle"),
            ("a reserved name in params_from",
             _params_from("mubeam", {"entry": "elebeam_flash.v"}),
             "params_from.entry", "'entry' is reserved"),
        ])

    def test_a_step_read_only_by_params_from_is_used(self):
        doc = _doc()
        doc["evaluate"].append({
            "step": "stops", "kit": "anakit", "entry": None, "files": [],
            "files_from": ["mubeam"], "params": {}, "params_from": {},
            "fixed": {"analysis": "ce_sensitivity"}})
        _step(doc, "sob")["params_from"] = {"x": "stops.v"}
        self.assertEqual(self.load(doc).steps[-1].step, "stops")

    def test_beamkit_reserved_names_are_refused_in_params_from(self):
        # The demo doc's case ('entry') is in test_refusals.
        g4bl = json.loads((ROOT / "mode_specs" / "ptg4bl.json").read_text())
        cases = (("Num_Events", "a beamkit setting"),
                 ("epsMax", "deck_params"),
                 ("bad-name", "deck parameter names"))
        for name, needle in cases:
            with self.subTest(name=name):
                doc = json.loads(json.dumps(g4bl))
                # a second beamkit step to take the param from
                doc["evaluate"].insert(0, dict(doc["evaluate"][0], step="pre"))
                doc["evaluate"][1]["params_from"] = {name: "pre.v"}
                self.assertRejects(doc, name, needle)

    def test_upstream_and_sent_params(self):
        s = st.Step("c", "toykit", None, (), ("a",), {"p": "x"},
                    {"z": "b.m", "y": "d.n", "w": "a.k"}, {"f": 1})
        self.assertEqual(s.upstream, ("a", "d", "b"))
        self.assertEqual(s.sent_params, frozenset({"p", "z", "y", "w", "f"}))

    def test_metrics_read(self):
        doc = _doc()
        _step(doc, "flash")["params_from"] = {"x": "sob.ce_abs_eff"}
        study = self.load(doc)
        self.assertEqual(st.metrics_read(study, "sob"),
                         frozenset({"s_over_sqrt_b", "ce_abs_eff"}))
        self.assertEqual(st.metrics_read(study, "flash"),
                         frozenset({"flash_edep_per_pot"}))
        self.assertEqual(st.metrics_read(study, "mubeam"), frozenset())

    def test_params_from_changes_measure_sha(self):
        base = self.load(_doc())
        self.assertTrue(all("params_from" not in s
                            for s in base.measure_basis["steps"]))
        doc = _doc()
        _step(doc, "flash")["params_from"] = {"x": "sob.ce_abs_eff"}
        wired = self.load(doc)
        self.assertNotEqual(base.measure_basis_sha, wired.measure_basis_sha)
        flash = next(s for s in wired.measure_basis["steps"]
                     if s["step"] == "flash")
        self.assertEqual(flash["params_from"], {"x": "sob.ce_abs_eff"})


if __name__ == "__main__":
    unittest.main()
