"""beamkit as a contract kit: its registry entry and settings, the adapter
(core/adapters/beamkit.py) against tests/fakebeamkit.py, and the ptg4bl
study end to end against the fake (wiki/projects/bo-ptg4bl.md). No grid,
no Kerberos, no real beamkit."""
import copy
import json
import os
import subprocess
import sys
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
from tests.engine_fixtures import EngineCase, TmpCase, write_study  # noqa: E402

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
            "params_from": {}, "fixed": {"njobs": 20, "events_per_job": 1000, "quorum": 0.9,
                      "plane": PLANE, "pdg": [13, -211]}}],
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


class _Tmp(TmpCase):
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

    def test_deck_params_may_not_shadow_a_knob(self):
        doc = ptg_doc()
        doc["kits"]["beamkit"]["deck_params"]["R_mid"] = 3.0
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        self.assertIn("R_mid", str(cm.exception))

    def test_job_counts_are_required(self):
        for key in ("njobs", "events_per_job"):
            doc = ptg_doc()
            del doc["evaluate"][0]["fixed"][key]
            with self.subTest(key=key), self.assertRaises(ValueError) as cm:
                self.load(doc)
            self.assertIn(key, str(cm.exception))

    def test_the_shipped_plane_is_the_ts_entrance(self):
        doc = json.loads((ROOT / "mode_specs" / "ptg4bl.json").read_text())
        # Basic_Detectors.txt places Coll_01_Det twice, renamed
        # Coll_01_DetIn and Coll_01_DetOut; a virtualdetector's tree is
        # VirtualDetector/<name> (seen in the first grid files, 2026-10-02).
        self.assertEqual(doc["evaluate"][0]["fixed"]["plane"],
                         "VirtualDetector/Coll_01_DetIn")

    def test_grid_only(self):
        decl = kit_registry.KITS["beamkit"]
        self.assertEqual(decl.launch_stagger_s, 90.0)
        self.assertEqual(decl.executors, ("grid",))
        self.assertTrue(decl.requires_kerberos)
        self.assertEqual(decl.factory, "adapters.beamkit:BeamkitKit")


PLANE = "VirtualDetector/Coll_01_DetIn"


def nts(path, rows, plane=PLANE):
    """A g4bl-like output file: the tree at `plane` (g4bl writes a
    virtualdetector under VirtualDetector/<name>, a zntuple under
    NTuple/<name>) with (PDGid, EventID, TrackID) rows, float32 as g4bl
    stores them."""
    import uproot
    cols = np.array(rows, dtype=np.float32).reshape(-1, 3)
    with uproot.recreate(path) as f:
        f[plane] = {"PDGid": cols[:, 0], "EventID": cols[:, 1],
                                "TrackID": cols[:, 2]}
    return str(path)


ROWS_A = [(13, 1, 5), (13, 1, 5), (-211, 1, 6), (211, 1, 7), (11, 2, 8)]
ROWS_B = [(13, 1, 5)]


def step_params(**over):
    p = {"Tlength": 160.0, "R_up": 3.1495, "R_mid": 3.1495, "R_dn": 3.1495,
         "deck_url": DECK_URL, "deck_ref": "a" * 40, "main_input": "Mu2E.in",
         "deck_params": {"Use_Proton_Target": 4, "epsMax": 0.01},
         "njobs": 20, "events_per_job": 1000, "quorum": 0.9,
         "plane": PLANE, "pdg": [13, -211]}
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
                      "beamline_status": 30, "beamline_outputs": 30,
                      "list_beamline_runs": 30})
        self.lock = self.tmp / "submit.lock"
        self.kit = bk.BeamkitKit("camp", server=cfg,
                                 grid_root=self.tmp / "grid",
                                 trace_dir=self.tmp / "trace",
                                 clock=lambda: self.now[0],
                                 submit_lock=self.lock, pause=lambda s: None)
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
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "working")
        self.assertEqual(st.poll_ms, 120000)
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=[f"/x/{i}.root"
                                                     for i in range(18)])
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        name = "cfgR01_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=[f"/x/{i}.root"
                                                     for i in range(17)])
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("17 of 20 files", st.message)
        self.assertIn("0 held", st.message)

    def test_an_unreadable_queue_fails_after_the_limit(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        unknown = {"state": "unknown", "reason": "schedd"}
        busy = {"state": "known", "idle": 1, "running": 0, "held": 0}
        # A run queued 7 h: the limit counts from the first unreadable
        # poll, not from the submit.
        self.now[0] = 7 * 3600
        self.set_run(name, queue=unknown)
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "working")
        self.assertIn("schedd", st.message)
        self.now[0] += bk.UNKNOWN_LIMIT_S - 1
        self.assertEqual(self.kit.status(name, "w").state, "working")
        # A readable queue in between resets the clock.
        self.set_run(name, queue=busy)
        self.assertEqual(self.kit.status(name, "w").state, "working")
        self.set_run(name, queue=unknown)
        self.now[0] += 10
        self.assertEqual(self.kit.status(name, "w").state, "working")
        self.now[0] += bk.UNKNOWN_LIMIT_S + 1
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("queue unreadable", st.message)

    def test_held_jobs_are_in_flight_until_the_limit(self):
        """jobsub can hold a just-submitted cluster for a moment (seen in
        campaign ptg5k01: 20 held at the first poll, 20 running a minute
        later). Held is in flight, not failed, until every remaining job
        has been held for HELD_LIMIT_S."""
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        held = {"state": "known", "idle": 0, "running": 0, "held": 20,
                "hold_reasons": {"transfer input files failed": 20}}
        self.set_run(name, queue=held)
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "working")
        self.assertIn("20 held", st.message)
        # Running again resets the clock.
        self.now[0] += bk.HELD_LIMIT_S - 1
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 20,
                                  "held": 0})
        self.assertEqual(self.kit.status(name, "w").state, "working")
        self.set_run(name, queue=held)
        self.now[0] += 10
        self.assertEqual(self.kit.status(name, "w").state, "working")
        self.now[0] += bk.HELD_LIMIT_S + 1
        st = self.kit.status(name, "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("held", st.message)
        self.assertIn("transfer input files failed", st.message)

    def test_a_transient_status_error_is_retried(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        self.set_run(name, fail_status=1)
        self.assertEqual(self.kit.status(name, "w").state, "working")

    def test_results_count_the_files_status_judged(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(njobs=2, quorum=1.0), [], [], "w")
        files = [nts(self.tmp / "a.root", ROWS_A),
                 nts(self.tmp / "b.root", ROWS_B)]
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=files)
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        # A recovery job queued later (prodtools' ledger-wide pass) must
        # not undo the verdict, nor change what is counted.
        self.set_run(name, queue={"state": "known", "idle": 1, "running": 0,
                                  "held": 0}, files=files[:1])
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        self.assertEqual(self.kit.results(name, "w").metrics["n_selected"], 3)

    def test_submits_are_serialized_by_the_host_lock(self):
        import fcntl
        import threading
        import time
        with open(self.lock, "w") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            th = threading.Thread(target=self.kit.submit, args=(
                "cfgR00_00.g4bl", step_params(), [], [], "w"))
            th.start()
            time.sleep(1.5)
            self.assertEqual([c for c in self.calls()
                              if c["tool"] == "run_beamline"], [])
        th.join(30)
        self.assertEqual(len([c for c in self.calls()
                              if c["tool"] == "run_beamline"]), 1)

    def test_a_created_run_survives_a_failed_submit(self):
        name = "cfgR00_00.g4bl"
        with self.assertRaises(KitError) as cm:
            self.kit.submit(name, step_params(deck_ref="e" * 40), [], [], "w")
        self.assertIn("first tick failed", str(cm.exception))
        rec = json.loads(next((self.tmp / "grid").rglob("*_beamkit.json"))
                         .read_text())
        self.assertEqual(rec["run_id"], f"{bk.tag_for(name)}.{'e' * 7}")
        self.kit.submit(name, step_params(deck_ref="e" * 40), [], [], "w")
        self.assertEqual(len([c for c in self.calls()
                              if c["tool"] == "run_beamline"]), 1)

    def test_a_run_whose_tick_submitted_nothing_is_refused(self):
        """beamkit returns the record, not an error, when the first tick
        submits nothing (state needs_attention): that is no submit."""
        name = "cfgR00_00.g4bl"
        with self.assertRaises(KitError) as cm:
            self.kit.submit(name, step_params(deck_ref="d" * 40), [], [], "w")
        self.assertIn("needs_attention", str(cm.exception))
        self.assertIn("queue count failed", str(cm.exception))
        rec = json.loads(next((self.tmp / "grid").rglob("*_beamkit.json"))
                         .read_text())
        self.assertEqual(rec["run_id"], f"{bk.tag_for(name)}.{'d' * 7}")
        # The run exists: a rerun adopts it rather than making a second.
        self.kit.submit(name, step_params(deck_ref="d" * 40), [], [], "w")
        self.assertEqual(len([c for c in self.calls()
                              if c["tool"] == "run_beamline"]), 1)

    def test_a_record_without_run_id_adopts_the_run(self):
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(), [], [], "w")
        path = next((self.tmp / "grid").rglob("*_beamkit.json"))
        rec = json.loads(path.read_text())
        run_id, rec["run_id"] = rec["run_id"], None
        path.write_text(json.dumps(rec))     # died before saving run_id
        self.kit.submit(name, step_params(), [], [], "w")
        self.assertEqual(len([c for c in self.calls()
                              if c["tool"] == "run_beamline"]), 1)
        self.assertEqual(json.loads(path.read_text())["run_id"], run_id)
        self.assertEqual(self.kit.status(name, "w").state, "working")

    def test_counts(self):
        a = nts(self.tmp / "a.root", ROWS_A)
        b = nts(self.tmp / "b.root", ROWS_B)
        self.assertEqual(bk.count_tracks([a, b], PLANE, [13, -211]), 3)
        other = nts(self.tmp / "o.root", ROWS_B, plane="NTuple/Coll_01_DetIn")
        with self.assertRaises(KitError) as cm:
            bk.count_tracks([a, other], PLANE, [13])
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

    def test_version_is_the_hand_constant(self):
        """The server version is the step's recorded build, never in the
        version: a beamkit release no longer splits a board (2026-10-05)."""
        self.kit.start()
        self.assertEqual(self.kit.version, "beamkit-adapter/1+fom1")
        self.assertIn("0.5.1-fake", self.kit.build)
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(njobs=1, quorum=1.0), [], [], "w")
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0},
                     files=[nts(self.tmp / "a.root", ROWS_A)])
        self.assertEqual(self.kit.status(name, "w").state, "completed")
        res = self.kit.results(name, "w")
        self.assertIn("0.5.1-fake", res.metadata["server"])
        self.assertEqual(res.metadata["adapter"], "beamkit-adapter/1+fom1")

    def test_cancel_is_not_offered(self):
        # beamkit has no cancel tool. Offering one made the scheduler log
        # "cancel requested" while the grid jobs kept running.
        self.assertNotIn("cancel", self.kit.tools)

    def test_quorum_is_the_prodtools_rule(self):
        # 7 of 100 files meets a 0.07 quorum, as in prodtools; in floats
        # ceil(0.07 * 100) is 8.
        name = "cfgR00_00.g4bl"
        self.kit.submit(name, step_params(njobs=100, quorum=0.07), [], [],
                        "w")
        self.set_run(name, queue={"state": "known", "idle": 0, "running": 0,
                                  "held": 0}, files=[f"/x/{i}.root"
                                                     for i in range(7)])
        self.assertEqual(self.kit.status(name, "w").state, "completed")


KLIST = """Ticket cache: FILE:/tmp/krb5cc_fake
Default principal: someone@FNAL.GOV

Valid starting       Expires              Service principal
01/01/2030 11:35:23  01/02/2099 13:35:19  krbtgt/FNAL.GOV@FNAL.GOV
"""


class TestEndToEnd(EngineCase):
    """check_study and graph.run on a copy of ptg4bl against the fake, with
    a fake klist: no grid, no ticket, no real beamkit."""

    def setUp(self):
        super().setUp()
        self.state = self.tmp / "state"
        self.state.mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "klist").write_text("#!/bin/bash\ncat <<'EOF'\n" + KLIST
                                      + "EOF\n")
        (bindir / "klist").chmod(0o755)
        venv = self.tmp / "beamkit" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "beamkit-mcp").write_text(
            f"#!/bin/bash\nexport FAKEBEAMKIT_STATE={self.state}\n"
            f"exec {sys.executable} {ROOT / 'tests' / 'fakebeamkit.py'} \"$@\"\n")
        (venv / "beamkit-mcp").chmod(0o755)
        doc = json.loads((ROOT / "mode_specs" / "ptg4bl.json").read_text())
        doc["name"] = "ptg4blfake"
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_bo_ptg4blfake.tsv"
        write_study(doc, self.studies)
        self.env.update(AUTORESEARCH_BEAMKIT=str(self.tmp / "beamkit"),
                        AUTORESEARCH_PRODTOOLS=str(self.tmp),
                        PATH=f"{bindir}:{os.environ['PATH']}")

    def run_module(self, *argv, timeout=180):
        return subprocess.run([sys.executable, "-m", *argv], cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=timeout)

    def test_check_study_passes_against_the_fake(self):
        r = self.run_module("graph.check_study", "ptg4blfake", "--json")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        checks = {c["name"]: c for c in json.loads(r.stdout)["checks"]}
        for name in ("load", "artifacts", "launch", "geometry"):
            self.assertEqual(checks[name]["status"], "passed", checks[name])

    def test_graph_run_lands_a_row(self):
        epj = json.loads((ROOT / "mode_specs" / "ptg4bl.json").read_text())[
            "evaluate"][0]["fixed"]["events_per_job"]
        files = [nts(self.tmp / f"nts.{i}.root", ROWS_A) for i in range(20)]
        (self.state / "preset.json").write_text(json.dumps({
            "queue": {"state": "known", "idle": 0, "running": 0, "held": 0},
            "files": files}))
        r = self.run_module("graph.run", "--study", "ptg4blfake", "--config",
                            "e2eR00_00", "--campaign", "e2e",
                            "--x=160,3.1495,3.1495,3.1495")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        board = (self.data / "autoresearch_leaderboards"
                 / "leaderboard_bo_ptg4blfake.tsv")
        lines = board.read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        row = dict(zip(lines[0].split("\t"), lines[1].split("\t")))
        self.assertEqual(row["config"], "e2eR00_00")
        # Two selected tracks per file (ROWS_A), 20 files of epj POT.
        self.assertAlmostEqual(float(row["mu_pi_per_pot"]), 40 / (20 * epj),
                               places=7)
        self.assertEqual(float(row["n_selected"]), 40)
        self.assertEqual(float(row["pot"]), 20 * epj)


if __name__ == "__main__":
    unittest.main()
