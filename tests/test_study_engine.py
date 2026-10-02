import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import paths  # noqa: E402
import scheduler  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import (ENGINE_STUDIES, toy_doc,  # noqa: E402
                                   write_study)

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"
V = {"toykit": "1"}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)

    def load(self, doc):
        return st.load_study_file(write_study(doc, self.dir))


class TestLayout(_Tmp):
    def test_v2_loads(self):
        self.assertEqual(self.load(toy_doc(layout="v2")).layout, "v2")

    def test_other_layouts_are_refused(self):
        # "v1" included: retired on 2026-09-29, when nothing loaded used it.
        for layout in ("v1", "v3"):
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError) as cm:
                    self.load(toy_doc(layout=layout))
                self.assertIn("leaderboard.layout", str(cm.exception))

    def test_the_branin_fixture_loads(self):
        s = st.load_study_file(ENGINE_STUDIES / "branin.json")
        self.assertEqual((s.name, s.layout, len(s.objectives)),
                         ("branin", "v2", 2))


class TestMeasureSha(_Tmp):
    def sha(self, mutate=lambda d: None, versions=V):
        doc = toy_doc(layout="v2")
        mutate(doc)
        return self.load(doc).measure_sha(versions)

    def test_unchanged_by_what_does_not_measure(self):
        base = self.sha()
        for label, mutate in (
                ("note", lambda d: d.update(note="edited")),
                ("bounds", lambda d: d["knobs"][0].update(max=12.0)),
                ("fmt", lambda d: d["objectives"][0].update(fmt="{:.3f}")),
                ("noise", lambda d: d["objectives"][0].update(noise=0.5)),
                ("constraint", lambda d: d["constraints"][0].update(max=9.0)),
                ("leaderboard", lambda d: d["leaderboard"].update(
                    file="leaderboards/other.tsv"))):
            with self.subTest(edit=label):
                self.assertEqual(self.sha(mutate), base)

    def test_changed_by_what_measures(self):
        base = self.sha()
        for label, mutate in (
                ("kit setting", lambda d: d["kits"]["toykit"].update(
                    function="reject")),
                ("fixed", lambda d: d["evaluate"][0]["fixed"].update(delay_s=1.0)),
                ("params", lambda d: d["evaluate"][0]["params"].update(x2="x1")),
                ("metric", lambda d: d["objectives"][1].update(metric="toy.n_inputs",
                                                               transform="none")),
                ("transform", lambda d: d["objectives"][0].update(transform="log10"))):
            with self.subTest(edit=label):
                self.assertNotEqual(self.sha(mutate), base)

    def test_changed_by_the_kit_version(self):
        self.assertNotEqual(self.sha(), self.sha(versions={"toykit": "2"}))

    def test_a_missing_kit_version_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.sha(versions={})
        self.assertIn("toykit", str(cm.exception))

    def test_the_basis_sha_is_the_basis_alone(self):
        """point.json's measure_basis_sha: what measure_sha hashes minus the
        kit versions, which only a started kit knows."""
        s = self.load(toy_doc(layout="v2"))
        self.assertEqual(s.measure_basis_sha, hashlib.sha256(json.dumps(
            s.measure_basis, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest())
        edited = toy_doc(layout="v2")
        edited["note"] = "edited"
        self.assertEqual(self.load(edited).measure_basis_sha,
                         s.measure_basis_sha)
        edited["evaluate"][0]["fixed"]["delay_s"] = 1.0
        self.assertNotEqual(self.load(edited).measure_basis_sha,
                            s.measure_basis_sha)

    def test_an_artifact_path_hashes_the_same_for_every_operator(self):
        a = st.load_study_file(DEMO).measure_basis
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.dir):
            b = st.load_study_file(DEMO).measure_basis
        self.assertEqual(a, b)
        self.assertIn("${ARTIFACT}/", json.dumps(a["kits"]))


class TestStageTemplates(_Tmp):
    def test_a_named_entry_resolves_to_its_template(self):
        basis = st.load_study_file(DEMO).measure_basis
        step = next(s for s in basis["steps"] if s["step"] == "mubeam")
        repo = json.loads((ROOT / "stage_entries" / "mubeam.json").read_text())
        self.assertEqual(step["entry"], repo)

    def test_a_missing_template_is_a_load_error(self):
        doc = json.loads(DEMO.read_text())
        next(s for s in doc["evaluate"] if s["step"] == "mubeam")["entry"] = \
            "no_such_stage"
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        self.assertIn("no_such_stage", str(cm.exception))
        self.assertIn("stage_entries", str(cm.exception))


class TestDerivedEnv(unittest.TestCase):
    def test_env_carries_knobs_consts_and_profiles(self):
        study = modes.STUDIES["foilspf_ax"]
        x = [(lo + hi) / 2 for lo, hi in zip(study.bounds_lo, study.bounds_hi)]
        env = study.geom.derived_env(x)
        for name, v in zip(study.knob_names, x):
            self.assertEqual(env[name], v)
        for name in study.derive["consts"]:
            self.assertIn(name, env)
        for name in study.derive["profiles"]:
            self.assertIsInstance(env[name], list)

    def test_derive_without_geom_message_is_current(self):
        doc = toy_doc()
        doc["derive"]["consts"] = {"k": 1.0}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as cm:
                st.load_study_file(write_study(doc, Path(td)))
        self.assertIn("geom is null", str(cm.exception))
        self.assertNotIn("Phase B", str(cm.exception))


class TestLoadedStudies(unittest.TestCase):
    def test_the_repo_studies_and_the_engine_fixtures_load(self):
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        env = dict(os.environ, PYTHONPATH="", AUTORESEARCH_DATA_ROOT=data.name,
                   AUTORESEARCH_STUDY_PATH=str(ENGINE_STUDIES))
        script = "import modes; print(sorted(modes.STUDIES))"
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           cwd=str(ROOT / "core"), capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        # mode_specs/ ships ce_chain, the seven foilspf engine twins
        # (<name>_ax.json; the originals are archived since C3) and ptg4bl
        # (G4beamline through beamkit), and
        # ENGINE_STUDIES holds
        # branin, prodtools_smoke and the two C2b acceptance fixtures
        # (foilspfbpz_local, foilspf_nominal).
        self.assertEqual(r.stdout.strip().splitlines()[-1],
                         "['branin', 'ce_chain', 'foilsflash_ax', "
                         "'foilspf2k_ax', "
                         "'foilspf_ax', 'foilspf_nominal', 'foilspfbp_ax', "
                         "'foilspfbpx_ax', 'foilspfbpz_ax', "
                         "'foilspfbpz_local', 'foilspfbw_ax', "
                         "'prodtools_smoke', 'ptg4bl']")


X_GRIDPHASEA01 = [67.7974, 111.1044, 132.7585, 0.140557, 0.027008, 0.107443,
                  0.4844, 0.95, 0.95, 11.0982]


class TestProdtoolsSmoke(unittest.TestCase):
    def test_it_is_foilspfbpz_at_one_fixed_point(self):
        smoke = st.load_study_file(ENGINE_STUDIES / "prodtools_smoke.json")
        bpz = st.load_study_file(ROOT / "mode_specs" / "foilspfbpz_ax.json")
        self.assertEqual(smoke.knobs, ())
        self.assertEqual(smoke.geom.render([]),
                         bpz.geom.render(X_GRIDPHASEA01))
        self.assertEqual([s.step for s in smoke.steps],
                         ["mubeam", "mustops_ce"])
        self.assertEqual(smoke.kits["prodtools"]["dsconf"], "MDC2025ax_{cfg}")

    def test_it_gates_on_the_pre_check_with_foilspfbpzs_policy(self):
        smoke = st.load_study_file(ENGINE_STUDIES / "prodtools_smoke.json")
        bpz = st.load_study_file(ROOT / "mode_specs" / "foilspfbpz_ax.json")
        self.assertEqual(smoke.preflight, {"kit": "offline_preflight",
                                           "params": {}, "files": ["geom"]})
        pre = smoke.kits["offline_preflight"]
        self.assertEqual(pre["code_tarball"],
                         smoke.kits["prodtools"]["code_tarball"])
        self.assertTrue(pre["code_tarball"].endswith("Code_mdc2025ax.tar.bz2"))
        for flag in ("dumps_gdml", "verifies_foil_gdml",
                     "checks_managed_overlap", "require_zero_overlaps"):
            self.assertEqual(pre[flag], bpz.kits["offline_preflight"][flag],
                             flag)


class TestFixedPaths(_Tmp):
    """A step's fixed path follows the kit-settings rule: '${ARTIFACT}/'
    expands when the step's params are built, a personal user area and any
    other token are refused at load, and measure_basis keeps the raw value
    (C2b spec, section 4)."""

    RAW = "${ARTIFACT}/c2b/table.tbl"

    def doc(self, value):
        doc = toy_doc(layout="v2")
        doc["evaluate"][0]["fixed"]["fail"] = value
        return doc

    def test_the_raw_value_is_kept_and_expanded_for_the_kit(self):
        s = self.load(self.doc(self.RAW))
        self.assertEqual(s.steps[0].fixed["fail"], self.RAW)
        with mock.patch.multiple(paths, ARTIFACT_ROOT=self.dir / "art",
                                 BACKING=self.dir / "no_backing"):
            params = scheduler.step_params(s, s.steps[0],
                                           {"x1": 1.0, "x2": 2.0}, False)
        self.assertEqual(params["fail"],
                         str(self.dir / "art" / "c2b" / "table.tbl"))

    def test_measure_basis_does_not_depend_on_the_artifact_root(self):
        shas = []
        for root in ("a", "b"):
            with mock.patch.object(paths, "ARTIFACT_ROOT", self.dir / root):
                shas.append(self.load(self.doc(self.RAW)).measure_basis_sha)
        self.assertEqual(shas[0], shas[1])

    def test_a_personal_user_area_is_refused_at_load(self):
        with self.assertRaises(ValueError) as cm:
            self.load(self.doc("/exp/mu2e/app/users/somebody/t.tbl"))  # personal-path-ok: made-up name, exercises the refusal
        self.assertIn("[fixed][fail]", str(cm.exception))
        self.assertIn("personal", str(cm.exception))

    def test_another_token_is_refused_at_load(self):
        with self.assertRaises(ValueError) as cm:
            self.load(self.doc("${HOME}/t.tbl"))
        self.assertIn("[fixed][fail]", str(cm.exception))
        self.assertIn("ARTIFACT", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
