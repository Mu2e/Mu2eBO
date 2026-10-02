"""beamkit as a contract kit: its registry entry and settings, the adapter
(core/adapters/beamkit.py) against tests/fakebeamkit.py, and the ptg4bl
study end to end against the fake (spec
docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md). No grid, no
Kerberos, no real beamkit."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import kit_registry  # noqa: E402
import study as st  # noqa: E402
from adapters import beamkit as bk  # noqa: E402
from kit_config import ServerConfig  # noqa: E402
from kits import KitError  # noqa: E402
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


def nts(path, rows, plane="Coll_01_Det"):
    """A g4bl-like ntuple file: NTuple/<plane> with (PDGid, EventID,
    TrackID) rows, stored as float32 as g4bl stores them."""
    import uproot
    cols = np.array(rows, dtype=np.float32).reshape(-1, 3)
    with uproot.recreate(path) as f:
        f[f"NTuple/{plane}"] = {"PDGid": cols[:, 0], "EventID": cols[:, 1],
                                "TrackID": cols[:, 2]}
    return str(path)


ROWS_A = [(13, 1, 5), (13, 1, 5), (-211, 1, 6), (211, 1, 7), (11, 2, 8)]
ROWS_B = [(13, 1, 5)]


def step_params(**over):
    p = {"Tlength": 160.0, "R_up": 3.1495, "R_mid": 3.1495, "R_dn": 3.1495,
         "deck_url": DECK_URL, "deck_ref": "a" * 40, "main_input": "Mu2E.in",
         "deck_params": {"Use_Proton_Target": 4, "epsMax": 0.01},
         "njobs": 20, "events_per_job": 1000, "quorum": 0.9,
         "plane": "Coll_01_Det", "pdg": [13, -211]}
    p.update(over)
    return p


class TestAdapter(_Tmp):
    """BeamkitKit against tests/fakebeamkit.py through the real KitClient."""

    def setUp(self):
        super().setUp()
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.now = [0.0]
        cfg = ServerConfig(
            name="beamkit",
            command=(sys.executable, str(ROOT / "tests" / "fakebeamkit.py")),
            env_passthrough=(), set_env={"FAKEBEAMKIT_STATE": str(self.state)},
            timeouts={"start": 60, "get_server_info": 30, "run_beamline": 30,
                      "beamline_status": 30, "beamline_outputs": 30})
        self.kit = bk.BeamkitKit("camp", server=cfg,
                                 grid_root=self.tmp / "grid",
                                 trace_dir=self.tmp / "trace",
                                 clock=lambda: self.now[0])
        self.addCleanup(self.kit.close)
        self.kit.start()

    def calls(self):
        path = self.state / "calls.jsonl"
        return ([json.loads(ln) for ln in path.read_text().splitlines()]
                if path.exists() else [])

    def run_state(self, name):
        run_id = f"{bk.tag_for(name)}.{'a' * 7}"
        return self.state / f"{run_id}.json"

    def set_run(self, name, **fields):
        path = self.run_state(name)
        doc = json.loads(path.read_text())
        doc.update(fields)
        path.write_text(json.dumps(doc))

    def test_tags_are_unique(self):
        a, b = bk.tag_for("a_bR00_00.g4bl"), bk.tag_for("abR00_00.g4bl")
        self.assertNotEqual(a, b)
        for tag in (a, b):
            self.assertRegex(tag, r"^[A-Za-z0-9]+$")

    def test_submit_is_idempotent_and_splits_params(self):
        for _ in range(2):
            self.assertEqual(self.kit.submit("cfgR00_00.g4bl", step_params(),
                                             [], [], "w"), "cfgR00_00.g4bl")
        runs = [c for c in self.calls() if c["tool"] == "run_beamline"]
        self.assertEqual(len(runs), 1)
        args = runs[0]["args"]
        self.assertEqual(args["params"], {
            "Tlength": "160.0", "R_up": "3.1495", "R_mid": "3.1495",
            "R_dn": "3.1495", "Use_Proton_Target": "4", "epsMax": "0.01"})
        self.assertEqual((args["njobs"], args["events_per_job"]), (20, 1000))
        self.assertEqual((args["run_as"], args["outloc"]), ("self", "scratch"))
        self.assertEqual(args["deck_ref"], "a" * 40)
        self.assertEqual(args["deck_url"], DECK_URL)

    def test_a_refused_submit_leaves_no_record(self):
        with self.assertRaises(KitError) as cm:
            self.kit.submit("cfgR00_00.g4bl", step_params(deck_ref="f" * 40),
                            [], [], "w")
        self.assertIn("deck sha not found", str(cm.exception))
        self.assertEqual(list((self.tmp / "grid").rglob("*_beamkit.json")), [])
        self.kit.submit("cfgR00_00.g4bl", step_params(), [], [], "w")
        self.assertEqual(len([c for c in self.calls()
                              if c["tool"] == "run_beamline"]), 2)

    def test_status_rule(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        self.set_run(name, queue={"state": "known", "idle": 3, "running": 2,
                                  "held": 0})
        self.assertEqual(self.kit.status(name, "w").state, "working")
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=[f"/x/{i}.root"
                                                     for i in range(18)])
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 3}, files=[f"/x/{i}.root"
                                                     for i in range(17)])
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("17 of 20 files", st.message)
        self.assertIn("3 held", st.message)

    def test_an_unreadable_queue_fails_after_the_limit(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        self.set_run(name, queue={"state": "unknown", "reason": "schedd"})
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "working")
        self.assertIn("schedd", st.message)
        self.now[0] = bk.UNKNOWN_LIMIT_S + 1
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("queue unreadable", st.message)

    def test_counts(self):
        a = nts(self.tmp / "a.root", ROWS_A)
        b = nts(self.tmp / "b.root", ROWS_B)
        self.assertEqual(bk.count_tracks([a, b], "Coll_01_Det", [13, -211]), 3)
        other = nts(self.tmp / "o.root", ROWS_B, plane="Other")
        with self.assertRaises(KitError) as cm:
            bk.count_tracks([a, other], "Coll_01_Det", [13])
        self.assertIn("o.root", str(cm.exception))

    def test_results(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(njobs=2, quorum=1.0), [], [], "w")
        files = [nts(self.tmp / "a.root", ROWS_A),
                 nts(self.tmp / "b.root", ROWS_B)]
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=files)
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        res = self.kit.results(name, "w")
        self.assertEqual(res.metrics, {"yield_per_pot": 3 / 2000,
                                       "n_selected": 3.0, "pot": 2000.0,
                                       "n_files": 2.0})
        self.assertEqual(len(res.files), 2)
        self.assertTrue(res.files[0]["uri"].startswith("file://"))

    def test_results_before_completion(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        with self.assertRaises(KitError) as cm:
            self.kit.results(name, "w")
        self.assertIn("not completed", str(cm.exception))

    def test_version_names_beamkit_and_fom(self):
        self.assertIn("beamkit-0.5.1-fake", self.kit.version)
        self.assertIn("fom1", self.kit.version)


if __name__ == "__main__":
    unittest.main()
