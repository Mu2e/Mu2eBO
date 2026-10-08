"""service/dashboard.py: the live campaign dashboard -- its data from the
campaign files, the flow graph, the snapshot loop (spec
docs/superpowers/specs/2026-10-04-dashboard-design.md)."""
import contextlib
import copy
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
import unittest.mock
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service import dashboard as dash  # noqa: E402
from service.campaigns import CampaignService  # noqa: E402
from campaign_dir import parse_child  # noqa: E402
from leaderboard import Point  # noqa: E402  (core/ is on sys.path now)
from tests.engine_fixtures import (META, EngineCase, toy_doc,  # noqa: E402
                                   write_study)


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


class _Dash(EngineCase):
    def setUp(self):
        super().setUp()
        write_study(toy_doc("toystudy"), self.studies)
        write_study(dag_doc(), self.studies)
        self.svc = CampaignService(env=self.env)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.now = time.time()

    def live(self, prefix, **record):
        """A live campaign: its record written and parent.lock held."""
        self.stack.enter_context(self.svc.camp(prefix).start(
            dict(record, prefix=prefix)))

    def run_lock(self, name, stack=None):
        """A running point: its run.lock held."""
        (stack or self.stack).enter_context(self.svc.point(name).run_lock())

    def child(self, name, study="toystudy", x=(1.0, 2.0), last="[run] x"):
        """A child that ran (its log and point.json), and its campaign's
        record, naming `study`, when the campaign has none yet."""
        self.svc.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.svc.logs_dir / f"{name}.log").write_text(last + "\n")
        sd = self.svc.grid_data / name / "state"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "point.json").write_text(json.dumps(
            {"config": name, "study": study, "x": list(x)}))
        parsed = parse_child(name)
        if parsed and not (self.svc.camp(parsed[0]).path
                           / "campaign.json").exists():
            self.record(parsed[0], study)
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
        s = self.svc.load_study(study)
        self.svc._board(s).append(Point(name, list(x), y), {}, META)

    def record(self, prefix, study, **fields):
        """A campaign record, as closed_loop writes it; no parent alive."""
        d = self.svc.camp(prefix).path
        d.mkdir(parents=True, exist_ok=True)
        (d / "campaign.json").write_text(json.dumps(
            dict(fields, prefix=prefix, study=study)))
        return d

    def data_of(self, prefix):
        return dash.campaign_data(self.svc, prefix, self.now)

    def point(self, data, name):
        return next(p for p in data["points"] if p["name"] == name)


class TestData(_Dash):
    def test_prefixes(self):
        self.child("aaR00_00")
        old = self.child("bbR00_00")
        for path in (self.svc.logs_dir / "bbR00_00.log",
                     self.svc.camp("bb").path / "campaign.json"):
            os.utime(path, (self.now - 8 * 86400,) * 2)
        self.child("single_config")
        self.record("cc", "toystudy")
        stale = self.record("oo", "toystudy") / "campaign.json"
        os.utime(stale, (self.now - 8 * 86400,) * 2)
        self.assertTrue(old.is_dir())
        self.assertEqual(dash.prefixes(self.svc, self.now, 7), ["aa", "cc"])
        self.live("dd", study="toystudy", q=2, max_evals=6)
        self.assertEqual(dash.prefixes(self.svc, self.now, 7),
                         ["aa", "cc", "dd"])

    def test_a_params_from_source_is_consumed(self):
        """b takes x2 from a's branin (params_from) and no file from it: a
        still feeds b, and is not a dead end into the result."""
        doc = toy_doc("pfstudy")
        a = dict(doc["evaluate"][0], step="a")
        b = dict(a, step="b", files_from=[], params={"x1": "x1"},
                 params_from={"x2": "a.branin"})
        doc["evaluate"] = [a, b]
        for o in doc["objectives"]:
            o["metric"] = "b." + o["metric"].split(".", 1)[1]
        write_study(doc, self.studies)
        self.child("pfR00_00", "pfstudy")
        d = self.data_of("pf")
        self.assertEqual(d["steps"], [
            {"step": "a", "kit": "toykit", "upstream": []},
            {"step": "b", "kit": "toykit", "upstream": ["a"]}])
        edges = [tuple(e) for e in dash.layout(d)["edges"]]
        self.assertIn(("pfR00_00/a", "pfR00_00/b"), edges)
        self.assertNotIn(("pfR00_00/a", "pfR00_00/result"), edges)
        self.assertIn(("pfR00_00/b", "pfR00_00/result"), edges)

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
            {"step": "a", "kit": "toykit", "upstream": []},
            {"step": "b", "kit": "toykit", "upstream": []},
            {"step": "c", "kit": "toykit", "upstream": ["a", "b"]}])
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
        held = contextlib.ExitStack()
        self.run_lock("stR00_00", held)
        for age, poll_s, stall in ((601, 120, True), (599, 120, False),
                                   (899, 300, False), (901, 300, True)):
            with self.subTest(age=age, poll_s=poll_s):
                self.status("stR00_00", "toy", age=age, poll_s=poll_s)
                p = self.point(self.data_of("st"), "stR00_00")
                self.assertEqual(p["state"], "running")
                self.assertEqual(p["steps"]["toy"]["stall"], stall)
        held.close()
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
        self.record("mm", "toystudy", q=3, max_evals=9)
        for i, v in enumerate((2.0, 1.0)):
            self.child(f"mmR0{i}_00")
            self.row("toystudy", f"mmR0{i}_00", (1.0, 2.0),
                     {"branin": v, "currin": 3.0})
        d = self.data_of("mm")
        self.assertEqual((d["q"], d["max_evals"], d["rows"]), (3, 9, 2))
        self.assertEqual(d["best"]["config"], "mmR01_00")
        self.assertEqual(d["best_label"], "1.000000")
        self.assertEqual(d["direction"], "min")
        p = self.point(d, "mmR01_00")
        self.assertEqual((p["state"], p["value"], p["value_label"]),
                         ("scored", 1.0, "1.000000"))
        self.child("shR00_00")
        self.live("sh", study="toystudy", q=2, max_evals=6)
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

    def test_an_unreadable_board_keeps_the_points(self):
        self.child("ubR00_00")
        self.row("toystudy", "ubR00_00", (1.0, 2.0),
                 {"branin": 1.0, "currin": 3.0})
        board = self.svc._board(self.svc.load_study("toystudy")).path
        with open(board, "a") as fh:
            fh.write("ubR01_00\tnot-a-number\n")
        snap = dash.build_snapshot(self.svc, self.now, 7, 120)
        self.assertEqual([c["prefix"] for c in snap["campaigns"]], ["ub"])
        d = snap["campaigns"][0]
        self.assertTrue(d["error"])
        self.assertEqual([p["name"] for p in d["points"]], ["ubR00_00"])

    def test_the_step_that_broke_a_point_is_failed(self):
        sd = self.child("fbR00_00", "dagstudy")
        self.step_file("fbR00_00", "a", "results.json", {})
        self.step_file("fbR00_00", "b", "cluster.txt")
        self.status("fbR00_00", "b")
        (sd / "broken.txt").write_text("step b: KitError: boom\n")
        p = self.point(self.data_of("fb"), "fbR00_00")
        self.assertEqual(p["state"], "broken")
        self.assertEqual({s: v["state"] for s, v in p["steps"].items()},
                         {"a": "done", "b": "failed", "c": "waiting"})
        self.assertIn("boom", p["steps"]["b"]["message"])

    def test_a_starting_point_is_running(self):
        # A child still in graph.run's launch checks: a log, nothing in
        # state/ yet (run.lock and point.json come after the checks).
        self.live("sp", study="toystudy")
        self.svc.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.svc.logs_dir / "spR00_00.log").write_text("[run] x\n")
        p = self.point(self.data_of("sp"), "spR00_00")
        self.assertEqual(p["state"], "running")

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


def step_rec(state="working", stall=False):
    return {"state": state, "message": f"{state} msg", "progress": None,
            "age_s": 60.0, "stall": stall, "error": None}


def camp(steps, points, best=None, direction="min", alive=True):
    """A campaign_data dict built by hand: steps as (name, upstream),
    points as (name, state, value, {step: step_rec})."""
    return {"prefix": "p", "study": "s", "alive": alive, "exit_code": None,
            "launched_by": "shell", "host": "h", "stopping": False,
            "q": 2, "max_evals": 4, "rows": 0,
            "best": {"config": best} if best else None, "best_label": None,
            "error": None, "direction": direction,
            "steps": [{"step": s, "kit": "k", "upstream": list(f)}
                      for s, f in steps],
            "points": [{"name": n, "state": st, "x": {"x1": 1.0},
                        "last_line": "[run] x", "value": v,
                        "value_label": None if v is None else f"{v:.6f}",
                        "steps": recs} for n, st, v, recs in points]}


def nodes(graph):
    return {n["id"]: n for b in graph["bands"] for n in b["nodes"]}


class TestGraph(unittest.TestCase):
    def test_one_step_layers(self):
        g = dash.layout(camp([("toy", [])],
                             [("p1", "running", None,
                               {"toy": step_rec()})]))
        self.assertEqual(g["columns"], 4)
        n = nodes(g)
        self.assertEqual((n["p1"]["layer"], n["p1/toy"]["layer"],
                          n["p1/result"]["layer"]), (1, 2, 3))
        self.assertEqual(sorted(map(tuple, g["edges"])),
                         [("campaign", "p1"), ("p1", "p1/toy"),
                          ("p1/toy", "p1/result")])

    def test_dag_layers_and_subrows(self):
        recs = {s: step_rec("waiting") for s in "abc"}
        g = dash.layout(camp([("a", []), ("b", []), ("c", ["a", "b"])],
                             [("p1", "running", None, recs)]))
        n = nodes(g)
        self.assertEqual([(n[f"p1/{s}"]["layer"], n[f"p1/{s}"]["subrow"])
                          for s in "abc"], [(2, 0), (2, 1), (3, 0)])
        self.assertEqual(n["p1/result"]["layer"], 4)
        self.assertEqual(g["columns"], 5)
        self.assertEqual(g["bands"][0]["height"], 2)
        self.assertEqual(sorted(map(tuple, g["edges"])),
                         [("campaign", "p1"), ("p1", "p1/a"), ("p1", "p1/b"),
                          ("p1/a", "p1/c"), ("p1/b", "p1/c"),
                          ("p1/c", "p1/result")])

    def test_band_order_and_fold(self):
        done = {"toy": step_rec("done")}
        g = dash.layout(camp([("toy", [])], [
            ("e1", "ended", None, done), ("s1", "scored", 1.0, done),
            ("r2", "running", None, {"toy": step_rec()}),
            ("b1", "broken", None, {"toy": step_rec("failed")}),
            ("s2", "scored", 0.5, done),
            ("r1", "running", None, {"toy": step_rec()})], best="s2"))
        self.assertEqual([b["point"] for b in g["bands"]],
                         ["r1", "r2", "s2", "s1", "b1", "e1"])
        self.assertEqual([b["fold"] for b in g["bands"]],
                         [None, None, "scored", "scored", None, None])
        res = nodes(g)["s2/result"]
        self.assertEqual((res["best"], res["label"], res["state"]),
                         (True, "0.500000", "scored"))
        self.assertFalse(nodes(g)["s1/result"]["best"])
        g = dash.layout(camp([("toy", [])], [
            ("s1", "scored", 1.0, done), ("s2", "scored", 0.5, done)],
            direction="max"))
        self.assertEqual([b["point"] for b in g["bands"]], ["s1", "s2"])

    def test_stall_state(self):
        g = dash.layout(camp([("toy", [])], [
            ("p1", "running", None, {"toy": step_rec(stall=True)})]))
        step = nodes(g)["p1/toy"]
        self.assertEqual(step["state"], "stall")
        self.assertIn("working msg", step["detail"])
        self.assertEqual(step["age_s"], 60.0)

    def test_no_steps_known(self):
        g = dash.layout(camp([], [("p1", "broken", None, {})]))
        self.assertEqual(g["columns"], 3)
        self.assertEqual(sorted(map(tuple, g["edges"])),
                         [("campaign", "p1"), ("p1", "p1/result")])


class TestSnapshot(_Dash):
    def test_build_snapshot(self):
        self.child("enR00_00")
        self.child("lvR00_00")
        self.child("xxR00_00")
        self.live("lv", study="toystudy")
        real = dash.campaign_data

        def flaky(svc, prefix, now):
            if prefix == "xx":
                raise RuntimeError("boom")
            return real(svc, prefix, now)
        with unittest.mock.patch.object(dash, "campaign_data", flaky):
            snap = dash.build_snapshot(self.svc, self.now, 7, 120)
        self.assertEqual([c["prefix"] for c in snap["campaigns"]],
                         ["lv", "en"])
        self.assertEqual([c["collapsed"] for c in snap["campaigns"]],
                         [False, True])
        self.assertIn("graph", snap["campaigns"][0])
        self.assertEqual((snap["every_s"], snap["time"]), (120, self.now))
        self.assertTrue(snap["host"])
        self.assertEqual(len(snap["errors"]), 1)
        self.assertIn("xx", snap["errors"][0])
        self.assertIn("boom", snap["errors"][0])
        json.dumps(snap)


class TestMain(_Dash):
    """python -m service.dashboard, as the operator starts it."""

    def cmd(self, *args):
        return [sys.executable, "-m", "service.dashboard", "--out",
                str(self.out), *args]

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "dash"
        self.child("aaR00_00")

    def run_cmd(self, *args, timeout=120):
        return subprocess.run(self.cmd(*args), cwd=ROOT, env=self.env,
                              capture_output=True, text=True,
                              timeout=timeout)

    def start(self, *args):
        p = subprocess.Popen(self.cmd(*args), cwd=ROOT, env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        self.addCleanup(self._stop, p)
        return p

    @staticmethod
    def _stop(p):
        if p.poll() is None:
            p.kill()
        p.communicate()

    def wait_for(self, cond, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.2)
        self.fail("timed out")

    @staticmethod
    def free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_once(self):
        r = self.run_cmd("--once")
        self.assertEqual(r.returncode, 0, r.stderr)
        snap = json.loads((self.out / "snapshot.json").read_text())
        self.assertEqual([c["prefix"] for c in snap["campaigns"]], ["aa"])
        self.assertTrue((self.out / "index.html").is_file())
        self.assertFalse((self.out / "snapshot.json.tmp").exists())

    def test_a_second_instance_exits(self):
        first = self.start("--no-serve", "--every", "60")
        self.wait_for(lambda: (self.out / "snapshot.json").exists())
        r = self.run_cmd("--once")
        self.assertEqual(r.returncode, 1)
        self.assertIn(str(first.pid), r.stderr)

    def test_a_busy_port_exits(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            r = self.run_cmd("--port", str(s.getsockname()[1]), "--every",
                             "60")
        self.assertEqual(r.returncode, 1)
        self.assertIn("port", r.stderr)

    def test_serves_the_snapshot(self):
        port = self.free_port()
        p = self.start("--port", str(port), "--every", "60")
        url = f"http://127.0.0.1:{port}/snapshot.json"

        def fetched():
            try:
                with urllib.request.urlopen(url, timeout=5) as r:
                    self.body = r.read()
                    return r.status == 200
            except OSError:
                return False
        self.wait_for(fetched)
        self.assertIn("campaigns", json.loads(self.body))
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=30), 0)


if __name__ == "__main__":
    unittest.main()
