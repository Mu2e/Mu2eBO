"""service/dashboard.py: the live campaign dashboard -- its data from the
campaign files, the flow graph, the snapshot loop (spec
docs/superpowers/specs/2026-10-04-dashboard-design.md)."""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service import dashboard as dash  # noqa: E402
from service.campaigns import CampaignService  # noqa: E402
from leaderboard import Point  # noqa: E402  (core/ is on sys.path now)
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402
from tests.test_boards import META  # noqa: E402


def dag_doc():
    """toystudy with steps a, b -> c: two roots feeding a third."""
    doc = toy_doc("dagstudy")
    base = doc["evaluate"][0]
    doc["evaluate"] = []
    for name, ups in (("a", []), ("b", []), ("c", ["a", "b"])):
        s = copy.deepcopy(base)
        s.update(step=name, files_from=ups)
        doc["evaluate"].append(s)
    for o in doc["objectives"]:
        o["metric"] = "c." + o["metric"].split(".", 1)[1]
    return doc


class _Dash(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.data = self.tmp / "data"
        self.data.mkdir()
        studies = self.tmp / "studies"
        write_study(toy_doc("toystudy"), studies)
        write_study(dag_doc(), studies)
        self.svc = CampaignService(env=engine_env(self.data, studies))
        self.procs = []
        self.svc._processes = lambda: list(self.procs)
        self.now = time.time()

    def child(self, name, study="toystudy", x=(1.0, 2.0), last="[run] x"):
        self.svc.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.svc.logs_dir / f"{name}.log").write_text(last + "\n")
        sd = self.svc.grid_data / name / "state"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "point.json").write_text(json.dumps(
            {"config": name, "study": study, "x": list(x)}))
        return sd

    def step_file(self, name, step, kind, payload="h\n"):
        sd = self.svc.grid_data / name / "state"
        sd.mkdir(parents=True, exist_ok=True)
        path = sd / f"{step}_{kind}"
        path.write_text(payload if isinstance(payload, str)
                        else json.dumps(payload))
        return path

    def status(self, name, step, state="working", age=0.0, poll_s=120.0,
               progress=None, message=None):
        return self.step_file(name, step, "status.json", {
            "state": state, "message": message or f"{step} {state}",
            "progress": progress, "time": self.now - age, "poll_s": poll_s})

    def row(self, study, name, x, y):
        s = self.svc._load_study(study)
        self.svc._board(s).append(Point(name, list(x), y), {}, META)

    def mcp(self, prefix, study, args=()):
        d = self.svc.camp_dir(prefix)
        d.mkdir(parents=True, exist_ok=True)
        (d / "campaign.json").write_text(json.dumps(
            {"prefix": prefix, "study": study, "args": list(args)}))
        return d

    def run_proc(self, name):
        self.procs.append((1000 + len(self.procs),
                           ["python", "-m", "graph.run", "--config", name]))

    def data_of(self, prefix):
        return dash.campaign_data(self.svc, prefix, self.now)

    def point(self, data, name):
        return next(p for p in data["points"] if p["name"] == name)


class TestData(_Dash):
    def test_prefixes(self):
        self.child("aaR00_00")
        old = self.child("bbR00_00")
        log = self.svc.logs_dir / "bbR00_00.log"
        os.utime(log, (self.now - 8 * 86400,) * 2)
        self.child("single_config")
        self.mcp("cc", "toystudy")
        stale = self.mcp("oo", "toystudy") / "campaign.json"
        os.utime(stale, (self.now - 8 * 86400,) * 2)
        self.assertTrue(old.is_dir())
        self.assertEqual(dash.prefixes(self.svc, self.now, 7), ["aa", "cc"])
        self.procs.append((99, ["python", "-m", "graph.closed_loop",
                                "--study", "toystudy", "--name-prefix", "dd",
                                "--q", "2", "--max-evals", "6"]))
        self.assertEqual(dash.prefixes(self.svc, self.now, 7),
                         ["aa", "cc", "dd"])

    def test_point_and_step_states(self):
        self.child("dgR00_00", "dagstudy")
        self.step_file("dgR00_00", "a", "cluster.txt")
        self.step_file("dgR00_00", "a", "results.json", {})
        self.step_file("dgR00_00", "b", "cluster.txt")
        self.status("dgR00_00", "b", progress={"done": 3, "total": 10,
                                               "ok": 3})
        self.child("dgR01_00", "dagstudy")
        self.step_file("dgR01_00", "a", "cluster.txt")
        self.child("dgR02_00", "dagstudy")
        self.step_file("dgR02_00", "b", "cluster.txt")
        self.status("dgR02_00", "b", state="failed")
        d = self.data_of("dg")
        self.assertEqual(d["study"], "dagstudy")
        self.assertEqual(d["steps"], [
            {"step": "a", "kit": "toykit", "files_from": []},
            {"step": "b", "kit": "toykit", "files_from": []},
            {"step": "c", "kit": "toykit", "files_from": ["a", "b"]}])
        p0 = self.point(d, "dgR00_00")
        self.assertEqual(p0["x"], {"x1": 1.0, "x2": 2.0})
        self.assertEqual({s: v["state"] for s, v in p0["steps"].items()},
                         {"a": "done", "b": "working", "c": "waiting"})
        self.assertEqual(p0["steps"]["b"]["message"], "b working")
        self.assertEqual(p0["steps"]["b"]["progress"],
                         {"done": 3, "total": 10, "ok": 3})
        a1 = self.point(d, "dgR01_00")["steps"]["a"]
        self.assertEqual((a1["state"], a1["stall"]), ("working", False))
        self.assertEqual(self.point(d, "dgR02_00")["steps"]["b"]["state"],
                         "failed")
        self.assertEqual(p0["state"], "ended")
        self.assertEqual(p0["last_line"], "[run] x")

    def test_stall(self):
        self.child("stR00_00")
        self.step_file("stR00_00", "toy", "cluster.txt")
        self.run_proc("stR00_00")
        for age, poll_s, stall in ((601, 120, True), (599, 120, False),
                                   (899, 300, False), (901, 300, True)):
            with self.subTest(age=age, poll_s=poll_s):
                self.status("stR00_00", "toy", age=age, poll_s=poll_s)
                p = self.point(self.data_of("st"), "stR00_00")
                self.assertEqual(p["state"], "running")
                self.assertEqual(p["steps"]["toy"]["stall"], stall)
        self.procs.clear()
        self.status("stR00_00", "toy", age=5000)
        p = self.point(self.data_of("st"), "stR00_00")
        self.assertEqual(p["steps"]["toy"]["stall"], False)

    def test_age_in_step(self):
        self.child("agR00_00")
        c = self.step_file("agR00_00", "toy", "cluster.txt")
        os.utime(c, (self.now - 3600,) * 2)
        self.status("agR00_00", "toy")
        step = self.point(self.data_of("ag"), "agR00_00")["steps"]["toy"]
        self.assertAlmostEqual(step["age_s"], 3600, delta=1)

    def test_budget_and_best(self):
        self.mcp("mm", "toystudy", ["--study", "toystudy", "--q", "3",
                                    "--max-evals", "9", "--name-prefix",
                                    "mm"])
        for i, v in enumerate((2.0, 1.0)):
            self.child(f"mmR0{i}_00")
            self.row("toystudy", f"mmR0{i}_00", (1.0, 2.0),
                     {"branin": v, "currin": 3.0})
        d = self.data_of("mm")
        self.assertEqual((d["q"], d["max_evals"], d["rows"]), (3, 9, 2))
        self.assertEqual(d["best"]["config"], "mmR01_00")
        self.assertEqual(d["best_label"], "1.000000")
        self.assertEqual(self.point(d, "mmR01_00")["state"], "scored")
        self.child("shR00_00")
        self.procs.append((77, ["python", "-m", "graph.closed_loop",
                                "--study", "toystudy", "--name-prefix", "sh",
                                "--q", "2", "--max-evals", "6"]))
        d = self.data_of("sh")
        self.assertEqual((d["q"], d["max_evals"], d["alive"]), (2, 6, True))
        self.assertIsNone(d["best_label"])

    def test_a_study_that_does_not_load(self):
        sd = self.child("goR00_00", "gone")
        (sd / "broken.txt").write_text("broken\n")
        d = self.data_of("go")
        self.assertIn("gone", d["error"])
        self.assertEqual(d["steps"], [])
        p = self.point(d, "goR00_00")
        self.assertEqual((p["state"], p["x"], p["steps"]),
                         ("broken", None, {}))

    def test_a_bad_status_file(self):
        self.child("bdR00_00", "dagstudy")
        self.step_file("bdR00_00", "b", "cluster.txt")
        bad = self.step_file("bdR00_00", "b", "status.json", "{")
        self.child("bdR01_00", "dagstudy")
        self.step_file("bdR01_00", "a", "results.json", {})
        d = self.data_of("bd")
        b = self.point(d, "bdR00_00")["steps"]["b"]
        self.assertEqual(b["state"], "working")
        self.assertIn(bad.name, b["error"])
        self.assertEqual(self.point(d, "bdR01_00")["steps"]["a"]["state"],
                         "done")
        self.assertIsNone(d["error"])


if __name__ == "__main__":
    unittest.main()
