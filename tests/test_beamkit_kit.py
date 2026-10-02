"""beamkit as a contract kit: its registry entry and settings, the adapter
(core/adapters/beamkit.py) against tests/fakebeamkit.py, and the ptg4bl
study end to end against the fake (spec
docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md). No grid, no
Kerberos, no real beamkit."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import kit_registry  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import write_study  # noqa: E402

DECK_URL = "https://github.com/oksuzian/G4BeamlineScripts"
KNOBS = ("Tlength", "R_up", "R_mid", "R_dn")


def ptg_doc(name="ptg4bltest", deck_ref="a" * 40):
    """The ptg4bl study, in memory (mode_specs/ptg4bl.json's shape)."""
    knob = lambda n, lo, hi: {"name": n, "type": "real", "min": lo,
                              "max": hi, "unit": "mm", "fmt": "{:.3f}"}
    return {
        "schema": 2, "name": name,
        "note": "G4beamline production target through beamkit (test)",
        "knobs": [knob("Tlength", 100.0, 220.0), knob("R_up", 2.0, 4.5),
                  knob("R_mid", 2.0, 4.5), knob("R_dn", 2.0, 4.5)],
        "derive": {"consts": {}, "exprs": {}, "profiles": {}},
        "geom": None,
        "kits": {"beamkit": {
            "deck_url": DECK_URL, "deck_ref": deck_ref,
            "main_input": "Mu2E.in",
            "deck_params": {"Use_Proton_Target": 4, "epsMax": 0.01}}},
        "preflight": None,
        "evaluate": [{
            "step": "g4bl", "kit": "beamkit", "entry": None, "files": [],
            "files_from": [], "params": {k: k for k in KNOBS},
            "fixed": {"njobs": 20, "events_per_job": 1000, "quorum": 0.9,
                      "plane": "Coll_01_Det", "pdg": [13, -211]}}],
        "objectives": [{"name": "mu_pi_per_pot",
                        "metric": "g4bl.yield_per_pot", "direction": "max",
                        "transform": "none", "noise": 0.002,
                        "fmt": "{:.5f}"}],
        "constraints": [],
        "extra_metrics": [
            {"name": "n_selected", "metric": "g4bl.n_selected",
             "fmt": "{:.0f}"},
            {"name": "pot", "metric": "g4bl.pot", "fmt": "{:.0f}"}],
        "extra_columns": [],
        "leaderboard": {"file": f"leaderboards/leaderboard_bo_{name}.tsv",
                        "layout": "v2", "context": []},
    }


class _Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    def load(self, doc):
        return st.load_study_file(write_study(doc, self.tmp / "studies"))


class TestRegistry(_Tmp):
    def test_a_good_beamkit_study_loads(self):
        study = self.load(ptg_doc())
        self.assertEqual(study.steps[0].kit, "beamkit")
        self.assertEqual(study.knob_names, KNOBS)

    def test_settings_are_checked(self):
        cases = [
            (("kits", "beamkit", "deck_ref"), "abc", "deck_ref"),
            (("evaluate", 0, "fixed", "pdg"), [], "pdg"),
            (("evaluate", 0, "fixed", "pdg"), [13, True], "pdg"),
            (("kits", "beamkit", "deck_params"), {"Num_Events": 5},
             "Num_Events"),
            (("kits", "beamkit", "deck_params"), {"1x": 5}, "1x"),
        ]
        for keys, value, needle in cases:
            doc = ptg_doc()
            node = doc
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = value
            with self.subTest(needle=needle), \
                    self.assertRaises(ValueError) as cm:
                self.load(doc)
            self.assertIn(needle, str(cm.exception))
        doc = ptg_doc()
        del doc["evaluate"][0]["fixed"]["quorum"]
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        self.assertIn("quorum", str(cm.exception))

    def test_a_knob_named_like_a_setting_is_refused(self):
        for name in ("njobs", "plane", "Num_Events"):
            doc = ptg_doc()
            doc["evaluate"][0]["params"] = {name: "Tlength", "R_up": "R_up",
                                            "R_mid": "R_mid", "R_dn": "R_dn"}
            with self.subTest(name=name), self.assertRaises(ValueError) as cm:
                self.load(doc)
            self.assertIn("a beamkit setting, not a deck param",
                          str(cm.exception))

    def test_grid_only(self):
        decl = kit_registry.KITS["beamkit"]
        self.assertEqual(decl.executors, ("grid",))
        self.assertTrue(decl.requires_kerberos)
        self.assertEqual(decl.factory, "adapters.beamkit:BeamkitKit")


if __name__ == "__main__":
    unittest.main()
