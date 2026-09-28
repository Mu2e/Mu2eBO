"""The C2b engine twins of the foilspf studies (mode_specs/<name>_ax.json)
and the two acceptance fixtures (Phase C2b spec, section 4)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES  # noqa: E402

MODES = ROOT / "mode_specs"
ORIGINALS = ("foilsflash", "foilspf", "foilspf2k", "foilspfbp", "foilspfbpx",
             "foilspfbpz", "foilspfbw")
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2"
WORK_AREA = "${ARTIFACT}/autoresearch_muse_ax"
SOB = {"step": "sob", "kit": "anakit", "entry": None, "files": [],
       "files_from": ["mubeam", "mustops_ce"], "params": {},
       "fixed": {"analysis": "ce_sensitivity", "input_correction": 0.01278168,
                 "cosmic_rate_per_s_per_mev": 0.0018181818181818182,
                 "dio_fraction": 0.39,
                 "dio_table": WORK_AREA + "/data/heeck_finer_binning_2016_szafron.tbl"}}
FLASH = {"step": "flash", "kit": "anakit", "entry": None, "files": [],
         "files_from": ["elebeam_flash"], "params": {},
         "fixed": {"analysis": "flash_edep_per_pot",
                   "pot_per_electron": 11.536718606512062}}
SAME = ("schema", "knobs", "derive", "geom", "preflight", "objectives",
        "extra_metrics", "extra_columns")


def doc(path):
    return json.loads(Path(path).read_text())


class TestTwins(unittest.TestCase):
    def test_each_twin_runs_on_the_engine_and_its_original_on_the_pipeline(self):
        for name in ORIGINALS:
            with self.subTest(name=name):
                self.assertIn(f"{name}_ax", modes.ENGINE)
                self.assertIn(name, modes.SPECS)
                self.assertNotIn(name, modes.ENGINE)

    def test_a_twin_differs_from_its_original_only_where_the_spec_says(self):
        for name in ORIGINALS:
            with self.subTest(name=name):
                orig, twin = doc(MODES / f"{name}.json"), doc(MODES / f"{name}_ax.json")
                for key in SAME:
                    self.assertEqual(twin[key], orig[key], key)
                self.assertEqual(twin["name"], f"{name}_ax")
                self.assertIn(f"mode_specs/{name}.json", twin["note"])
                self.assertEqual(twin["kits"], {
                    "prodtools": {**orig["kits"]["prodtools"],
                                  "code_tarball": TARBALL,
                                  "dsconf": "MDC2025ax_{cfg}"},
                    "offline_preflight": {**orig["kits"]["offline_preflight"],
                                          "code_tarball": TARBALL},
                    "anakit": {"work_area": WORK_AREA}})
                steps = {s["step"]: s for s in twin["evaluate"]}
                before = {s["step"]: s for s in orig["evaluate"]}
                self.assertEqual(list(steps), list(before))
                for step in ("mubeam", "mustops_ce", "elebeam_flash"):
                    self.assertEqual(steps[step], before[step])
                self.assertEqual(steps["sob"], SOB)
                self.assertEqual(steps["flash"], FLASH)
                self.assertEqual(
                    [(c["name"], c["k_sigma"]) for c in twin["constraints"]],
                    [(c["name"], c["k_sigma"]) for c in orig["constraints"]])
                self.assertEqual(twin["leaderboard"], {
                    "file": f"leaderboards/leaderboard_bo_{name}_ax.tsv",
                    "layout": "v2", "context": orig["leaderboard"]["context"]})


def geom_vector(text, key):
    m = re.search(rf"{re.escape(key)}\s*=\s*\{{([^}}]*)\}}", text)
    return [float(v) for v in m.group(1).split(",")]


def geom_double(text, key):
    m = re.search(rf"double\s+{re.escape(key)}\s*=\s*([-0-9.eE+]+)", text)
    return float(m.group(1))


class TestFixtures(unittest.TestCase):
    def test_the_nominal_fixture_renders_the_deployed_stack(self):
        s = st.load_study_file(ENGINE_STUDIES / "foilspf_nominal.json")
        self.assertEqual(s.knobs, ())
        text = s.geom.render([])
        self.assertEqual(geom_vector(text, "stoppingTarget.radii"), [75.0] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.halfThicknesses"),
                         [0.0528] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.holeRadii"),
                         [21.5] * 37)
        self.assertTrue(all(abs(z) < 1e-3 for z in
                            geom_vector(text, "stoppingTarget.zVars")))
        self.assertAlmostEqual(geom_double(text, "stoppingTarget.deltaZ"),
                               22.222222, places=6)
        self.assertAlmostEqual(
            geom_double(text, "protonabsorber.distFromTargetEnd"), 625.0,
            places=6)

    def test_the_fixtures_run_foilspfbpz_ax_steps(self):
        twin = doc(MODES / "foilspfbpz_ax.json")
        nominal = doc(ENGINE_STUDIES / "foilspf_nominal.json")
        local = doc(ENGINE_STUDIES / "foilspfbpz_local.json")
        self.assertEqual(nominal["evaluate"], twin["evaluate"])
        self.assertEqual(nominal["kits"], twin["kits"])
        self.assertEqual(local["kits"], twin["kits"])
        self.assertEqual(local["knobs"], twin["knobs"])
        for mine, theirs in zip(local["evaluate"], twin["evaluate"]):
            self.assertEqual({k: v for k, v in mine.items() if k != "fixed"},
                             {k: v for k, v in theirs.items() if k != "fixed"})
            if mine["kit"] == "anakit":
                self.assertEqual(mine["fixed"], theirs["fixed"])
            else:
                self.assertLess(mine["fixed"]["njobs"] * mine["fixed"]["events_per_job"],
                                theirs["fixed"]["njobs"] * theirs["fixed"]["events_per_job"])
        for fixture in (nominal, local):
            st.load_study_file(ENGINE_STUDIES / f"{fixture['name']}.json")


if __name__ == "__main__":
    unittest.main()
