"""service/campaigns.py: the autoresearch MCP server's campaign tools --
start (a dry run, then confirm), stop, status and the leaderboard -- on the
branin engine study, locally."""
import dataclasses
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service.campaigns import CampaignService, is_child  # noqa: E402
from adapters import prodtools_entry  # noqa: E402  (core/, via the service)
from tests.engine_fixtures import (ENGINE_STUDIES, EngineCase,  # noqa: E402
                                   engine_env, toy_doc, write_study)

LOCAL = ["--picker", "budget_sob", "--executor", "local", "--parallel", "1"]


class _Camp(EngineCase):
    """The branin engine study (tests/fixtures/engine_studies) on a temp
    data root."""

    def setUp(self):
        super().setUp()
        self.env = engine_env(self.data, ENGINE_STUDIES)
        self.svc = CampaignService(env=self.env)

    def shell_loop(self, prefix, max_evals, q=1):
        """graph.closed_loop started directly, as an operator would."""
        log = open(self.tmp / f"{prefix}.out", "w")
        self.addCleanup(log.close)
        p = subprocess.Popen(
            [sys.executable, "-m", "graph.closed_loop", "--study", "branin",
             "--q", str(q), "--max-evals", str(max_evals),
             "--name-prefix", prefix, *LOCAL],
            cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        self.addCleanup(self._kill, p)
        p.out = self.tmp / f"{prefix}.out"
        return p

    @staticmethod
    def _kill(p):
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()

    def wait_exit(self, p, timeout=180):
        rc = p.wait(timeout=timeout)
        self.assertEqual(rc, 0, p.out.read_text()[-3000:])
        return rc

    def child_log(self, name, text="[run] something\n"):
        logs = self.svc.graph_data / "closed_loop_logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"{name}.log").write_text(text)


class TestStatus(_Camp):
    def test_a_shell_campaign(self):
        p = self.shell_loop("shl", 2)
        # Alive once closed_loop has passed its launch checks and written
        # its record (it holds parent.lock from then on).
        deadline = time.time() + 60
        while not self.svc.campaign_status("shl")["parent"]["alive"]:
            self.assertIsNone(p.poll(), p.out.read_text()[-3000:])
            self.assertLess(time.time(), deadline, "never alive")
            time.sleep(0.2)
        parent = self.svc.campaign_status("shl")["parent"]
        self.assertTrue(parent["alive"], parent)
        self.assertEqual(parent["launched_by"], "shell")
        self.assertEqual(parent["pid"], p.pid)
        self.assertIn("shl", [c["prefix"] for c in
                              self.svc.campaign_status()])
        self.wait_exit(p)
        st = self.svc.campaign_status("shl")
        self.assertFalse(st["parent"]["alive"], st)
        self.assertEqual(st["study"], "branin")
        self.assertEqual([c["name"] for c in st["children"]],
                         ["shlR00_00", "shlR01_00"])
        self.assertEqual({c["state"] for c in st["children"]}, {"scored"})
        self.assertEqual(st["rows"], 2)
        rows = self.svc.leaderboard("branin", "shl")["rows"]
        self.assertEqual(len(rows), 2)
        values = [r["values"]["branin"] for r in rows]
        self.assertEqual(values, sorted(values))
        self.assertEqual(st["best"]["values"]["branin"], values[0])
        self.assertEqual(set(rows[0]["x"]), {"x1", "x2"})

    def test_prefixes_are_exact(self):
        self.child_log("fooR00_00")
        self.child_log("foo2R00_00")
        st = self.svc.campaign_status("foo")
        self.assertEqual([c["name"] for c in st["children"]], ["fooR00_00"])
        self.assertTrue(is_child("foo", "fooR12_00"))
        self.assertFalse(is_child("foo", "foo2R00_00"))
        self.assertFalse(is_child("foo", "fooR00_00x"))

    def test_child_states(self):
        self.child_log("cstR00_00", "[run] a\n\n")
        sd = self.svc.grid_data / "cstR00_00" / "state"
        sd.mkdir(parents=True)
        (sd / "broken.txt").write_text("broken\n")
        self.child_log("cstR01_00")
        children = {c["name"]: c for c in
                    self.svc.campaign_status("cst")["children"]}
        self.assertEqual(children["cstR00_00"]["state"], "broken")
        self.assertEqual(children["cstR00_00"]["last_line"], "[run] a")
        self.assertEqual(children["cstR01_00"]["state"],
                         "ended without a row")

    def test_a_starting_child(self):
        with self.svc.camp("sta").start({"study": "branin"}):
            self.child_log("staR00_00")
            st = self.svc.campaign_status("sta")
            self.assertEqual(st["children"][0]["state"], "starting")
        st = self.svc.campaign_status("sta")
        self.assertEqual(st["children"][0]["state"], "ended without a row")

    def test_an_old_child_under_a_relaunch_is_not_starting(self):
        """A child from before the records (point.json and a handle, no
        run.lock, no outcome) under a live relaunch of its prefix is not
        starting: a starting child has not written point.json yet."""
        self.child_log("oldrR00_00")
        sd = self.svc.grid_data / "oldrR00_00" / "state"
        sd.mkdir(parents=True)
        (sd / "point.json").write_text('{"study": "branin", "x": [1.0, 2.0]}')
        (sd / "toy_cluster.txt").write_text("oldrR00_00.toy\n")
        with self.svc.camp("oldr").start({"study": "branin"}):
            st = self.svc.campaign_status("oldr")
        self.assertEqual(st["children"][0]["state"], "ended without a row")

    def test_a_bad_point_json_is_reported(self):
        d = self.svc.camp("bp").path
        d.mkdir(parents=True)
        (d / "campaign.json").write_text('{"study": "branin"}')
        for name, text in (("bpR00_00", "{"), ("bpR01_00", "[1, 2]")):
            self.child_log(name)
            sd = self.svc.grid_data / name / "state"
            sd.mkdir(parents=True)
            (sd / "point.json").write_text(text)
        st = self.svc.campaign_status("bp")
        self.assertEqual(st["study"], "branin")
        self.assertIn("bpR00_00", st["error"])
        self.assertIn("bpR01_00", st["error"])
        self.assertEqual(len(st["children"]), 2)

    def test_a_running_child_by_its_lock(self):
        self.child_log("rnR00_00")
        with self.svc.point("rnR00_00").run_lock():
            st = self.svc.campaign_status("rn")
            self.assertEqual(st["children"][0]["state"], "running")
            self.assertEqual(
                self.svc.stop_campaign("rn")["children_running"], 1)
        self.assertEqual(self.svc.campaign_status("rn")["children"][0]
                         ["state"], "ended without a row")

    def test_a_bad_record_is_reported(self):
        self.child_log("badR00_00")
        d = self.svc.camp("bad").path
        d.mkdir(parents=True)
        (d / "campaign.json").write_text("{")
        st = self.svc.campaign_status("bad")
        self.assertIn("campaign.json", st["error"])
        self.assertEqual([c["name"] for c in st["children"]], ["badR00_00"])
        listed = {c["prefix"]: c for c in self.svc.campaign_status()}
        self.assertIn("campaign.json", listed["bad"]["error"])

    def test_a_truncated_outcome_line_is_reported(self):
        self.child_log("trR00_00")
        with self.svc.camp("tr").start({"study": "branin"}):
            pass
        (self.svc.camp("tr").path / "outcomes.jsonl").write_text(
            '{"name": "trR00_')
        st = self.svc.campaign_status("tr")
        self.assertIn("outcomes.jsonl", st["error"])
        self.assertEqual([c["name"] for c in st["children"]], ["trR00_00"])
        # The good lines stay readable around a truncated one.
        self.svc.camp("tr").append_outcome({"name": "trR00_00",
                                            "reason": "child rc=1"})
        st = self.svc.campaign_status("tr")
        self.assertEqual(st["children"][0]["outcome"], "child rc=1")
        self.assertIn("outcomes.jsonl:1", st["error"])

    def test_a_prefix_that_is_a_path_is_refused(self):
        for prefix in ("", "..", "../x", "/etc", "a-b"):
            with self.assertRaises(ValueError, msg=prefix):
                self.svc.campaign_status(prefix)

    def test_an_unknown_prefix(self):
        st = self.svc.campaign_status("nothing")
        self.assertEqual(st["host"], socket.gethostname())
        self.assertIsNone(st["study"])
        self.assertEqual(st["children"], [])
        self.assertEqual(st["rows"], 0)
        self.assertIsNone(st["best"])
        self.assertFalse(st["parent"]["alive"])
        out = self.svc.stop_campaign("nothing")
        self.assertIn("no sign of a campaign", out["warning"])
        self.assertTrue((self.svc.graph_data / "nothing" / "STOP").exists())


class TestLeaderboard(_Camp):
    def test_leaderboard_of_an_empty_board(self):
        out = self.svc.leaderboard("branin")
        self.assertEqual(out["n_rows"], 0)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["objective"],
                         {"name": "branin", "direction": "min"})

    def test_leaderboard_errors(self):
        with self.assertRaises(ValueError) as cm:
            self.svc.leaderboard("nope")
        self.assertIn("no study named 'nope'", str(cm.exception))
        with self.assertRaises(ValueError):
            self.svc.stop_campaign("a-b")


class TestStart(_Camp):
    KW = dict(picker="budget_sob", executor="local", parallel=1)

    def launch(self, prefix, max_evals, **kw):
        out = self.svc.start_campaign("branin", prefix, 1, max_evals,
                                      confirm=True, **dict(self.KW, **kw))
        self.addCleanup(self._stop_launch, prefix)
        return out

    def _stop_launch(self, prefix):
        """A failed test must not leave a campaign running into a deleted
        data root."""
        cdir = self.svc.camp(prefix).path
        try:
            pid = __import__("json").loads(
                (cdir / "launch.json").read_text()).get("pid")
        except (OSError, ValueError):
            return
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def wait_parent(self, prefix, timeout=180):
        deadline = time.time() + timeout
        while True:
            st = self.svc.campaign_status(prefix)
            if not st["parent"]["alive"]:
                return st
            self.assertLess(time.time(), deadline, st)
            time.sleep(1)

    def test_a_dry_run(self):
        out = self.svc.start_campaign("branin", "dry", 1, 2, **self.KW)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["budget"],
                         {"grid_jobs_per_point": 0, "grid_jobs_total": 0,
                          "local_jobs_per_point": 0, "jobs_vary": []})
        self.assertNotIn("--check-only", out["command"])
        self.assertIn("--name-prefix dry", out["command"])
        # The server writes nothing (closed_loop's launch check leaves its
        # kit trace in that folder, as any launch check does).
        for name in ("campaign.json", "launch.json", "parent.log", "lock",
                     "STOP"):
            self.assertFalse((self.svc.camp("dry").path / name).exists(), name)

    def test_a_job_count_error_is_a_problem_of_the_dry_run(self):
        """A budget its kits cannot count fails the dry run loudly, and the
        check's own output still comes back with it."""
        why = "step 'mubeam': no njobs in the step or its stage template"
        with mock.patch.object(self.svc, "budget",
                               side_effect=ValueError(why)):
            out = self.svc.start_campaign("branin", "dry", 1, 2, **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertIsNone(out["budget"])
        self.assertTrue(any(why in p for p in out["problems"]), out)
        self.assertIn("--name-prefix dry", out["command"])
        self.assertTrue(out["output_tail"], out)

    def test_a_refused_dry_run(self):
        out = self.svc.start_campaign("branin", "dry", 1, 2,
                                      context=["alpha=1"], **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertIn("--context 'alpha'", out["problems"][0])

    def test_a_hung_dry_run_times_out(self):
        self.svc.check_timeout_s = 0.01
        out = self.svc.start_campaign("branin", "dry", 1, 2, **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertIn("did not finish (timed out)", out["error"])

    def test_an_activate_failure_in_a_dry_run(self):
        env = dict(self.env, AUTORESEARCH_PYENV="ana")
        env.pop("AUTORESEARCH_VENV", None)
        out = CampaignService(env=env).start_campaign("branin", "dry", 1, 2,
                                                      **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertIn("did not finish (exit 1)", out["error"])
        self.assertIn("NAME VERSION", out["output_tail"])

    def test_a_launch_runs_to_the_end(self):
        out = self.launch("mcpa", 2)
        self.assertEqual(out["state"], "launched", out)
        st = self.wait_parent("mcpa")
        self.assertEqual(st["parent"]["launched_by"], "mcp")
        self.assertEqual(st["parent"]["exit_code"], 0, st)
        self.assertEqual([c["state"] for c in st["children"]],
                         ["scored", "scored"])
        self.assertEqual(st["rows"], 2)
        self.assertIn("[closed_loop] done", st["parent"]["log_tail"])

    def test_launch_refusals(self):
        self.assertEqual(self.launch("dup", 1)["state"], "launched")
        with self.assertRaises(ValueError) as cm:
            self.launch("dup", 1)
        self.assertIn("already running", str(cm.exception))
        self.wait_parent("dup")
        with self.assertRaises(ValueError) as cm:
            self.launch("dup", 1)
        self.assertIn("already launched", str(cm.exception))
        self.svc.stop_campaign("stp")
        with self.assertRaises(ValueError) as cm:
            self.launch("stp", 1)
        self.assertIn("STOP", str(cm.exception))
        # A stand-in parent: a live one holds parent.lock.
        with self.svc.camp("busy").start({"study": "branin"}):
            with self.assertRaises(ValueError) as cm:
                self.launch("busy", 1)
        self.assertIn("already running", str(cm.exception))
        self.assertIsNone(self.svc.camp("busy").launch())

    def test_the_dry_run_sees_the_launch_refusals(self):
        # Whatever confirm would refuse, the dry run already says.
        self.svc.stop_campaign("stp2")
        out = self.svc.start_campaign("branin", "stp2", 1, 1, **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertTrue(any("STOP" in p for p in out["problems"]), out)
        self.child_log("oldR00_00")
        out = self.svc.start_campaign("branin", "old", 1, 1, **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertTrue(any("already has children" in p
                            for p in out["problems"]), out)
        with self.assertRaises(ValueError) as cm:
            self.launch("old", 1)
        self.assertIn("already has children", str(cm.exception))
        self.assertEqual(self.launch("spt", 1, context=["alpha=1"])["state"],
                         "refused")
        out = self.svc.start_campaign("branin", "spt", 1, 1, **self.KW)
        self.assertFalse(out["ok"], out)
        self.assertTrue(any("already launched" in p
                            for p in out["problems"]), out)

    def test_a_refused_launch_spends_the_prefix(self):
        out = self.launch("ctx", 1, context=["alpha=1"])
        self.assertEqual(out["state"], "refused", out)
        self.assertIn("--context 'alpha'", out["problems"][0])
        self.assertIn("spent", out["note"])
        with self.assertRaises(ValueError) as cm:
            self.launch("ctx", 1)
        self.assertIn("already launched", str(cm.exception))

    def test_stop_drains_a_launch(self):
        self.assertEqual(self.launch("drn", 6)["state"], "launched")
        self.assertTrue(self.svc.stop_campaign("drn")["parent_alive"])
        st = self.wait_parent("drn")
        self.assertLess(len(st["children"]), 6, st)
        self.assertTrue(st["stopping"])
        self.assertEqual(st["parent"]["exit_code"], 0, st)


class TestBudget(_Camp):
    """The jobs the start_campaign dry run shows: each step counted by its
    own kit's declaration, whichever kit that is."""

    def with_studies(self, *docs):
        """A service that also sees `docs`, written to self.studies."""
        for doc in docs:
            write_study(doc, self.studies)
        return CampaignService(env=engine_env(
            self.data, f"{ENGINE_STUDIES}:{self.studies}"))

    @staticmethod
    def smoke(name, mutate):
        """prodtools_smoke (mubeam then mustops_ce, one job each) as
        `name`, edited by `mutate(doc, steps by name)`."""
        doc = json.loads((ENGINE_STUDIES / "prodtools_smoke.json")
                         .read_text())
        doc["name"] = name
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_{name}.tsv"
        mutate(doc, {s["step"]: s for s in doc["evaluate"]})
        return doc

    def test_budget(self):
        self.assertEqual(self.svc.budget("branin", 4, "local"),
                         {"grid_jobs_per_point": 0, "grid_jobs_total": 0,
                          "local_jobs_per_point": 0, "jobs_vary": []})
        self.assertEqual(self.svc.budget("foilspfbpz_ax", 10, "grid"),
                         {"grid_jobs_per_point": 130,
                          "grid_jobs_total": 1300, "jobs_vary": []})

    def test_a_beamkit_study_counts_its_jobs(self):
        # ptg5k01 and ptg5k02 launched after dry runs that showed 0 grid
        # jobs; they ran 20 per point (180 and 400 in all).
        self.assertEqual(self.svc.budget("ptg4bl", 10, "grid"),
                         {"grid_jobs_per_point": 20, "grid_jobs_total": 200,
                          "jobs_vary": []})

    def test_a_step_without_njobs_counts_its_stage_template(self):
        svc = self.with_studies(self.smoke(
            "tmplnjobs", lambda doc, s: s["mubeam"]["fixed"].pop("njobs")))
        # stage_entries/mubeam.json's njobs is 200, plus mustops_ce's 1.
        self.assertEqual(svc.budget("tmplnjobs", 3, "grid"),
                         {"grid_jobs_per_point": 201, "grid_jobs_total": 603,
                          "jobs_vary": []})
        # The count prodtools submits for the same steps.
        study = svc.load_study("tmplnjobs")
        submitted = sum(prodtools_entry.entry_for_step(
            study.entry_template(s.step), config="c", fixed=s.fixed,
            code_tarball="c.tar.bz2", dsconf="d_{cfg}",
            geom_name="g.txt")[1]["njobs"] for s in study.steps)
        self.assertEqual(submitted, 201)

    def test_an_analysis_only_study_counts_no_jobs(self):
        doc = toy_doc("anaonly")
        doc["kits"] = {"anakit": {"musing": "SimJob MDC2025ay"}}
        doc["evaluate"] = [
            {"step": "ana", "kit": "anakit", "entry": None, "files": [],
             "files_from": [], "params": {}, "params_from": {},
             "fixed": {"analysis": "edep"}}]
        for obj in doc["objectives"]:
            obj["metric"] = f"ana.{obj['name']}"
        svc = self.with_studies(doc)
        self.assertEqual(svc.budget("anaonly", 10, "grid"),
                         {"grid_jobs_per_point": 0, "grid_jobs_total": 0,
                          "jobs_vary": []})

    def test_a_mapped_job_count_is_no_one_number(self):
        def from_knob(doc, s):
            doc["knobs"] = [{"name": "nj", "type": "int", "min": 1,
                             "max": 50, "unit": "", "fmt": "{:.0f}"}]
            del s["mubeam"]["fixed"]["njobs"]
            s["mubeam"]["params"] = {"njobs": "nj"}

        def from_step(doc, s):
            del s["mustops_ce"]["fixed"]["njobs"]
            s["mustops_ce"]["params_from"] = {"njobs": "mubeam.njobs_ok"}

        svc = self.with_studies(self.smoke("knobnjobs", from_knob),
                                self.smoke("stepnjobs", from_step))
        for name, step, source in (("knobnjobs", "mubeam", "'nj'"),
                                   ("stepnjobs", "mustops_ce",
                                    "'mubeam.njobs_ok'")):
            with self.subTest(name):
                out = svc.budget(name, 10, "grid")
                self.assertIsNone(out["grid_jobs_per_point"], out)
                self.assertIsNone(out["grid_jobs_total"], out)
                self.assertEqual(len(out["jobs_vary"]), 1, out)
                self.assertIn(repr(step), out["jobs_vary"][0])
                self.assertIn(source, out["jobs_vary"][0])
                local = svc.budget(name, 10, "local")
                self.assertIsNone(local["local_jobs_per_point"], local)
                self.assertEqual(local["grid_jobs_total"], 0, local)

    def test_a_job_count_set_nowhere_is_an_error(self):
        def no_njobs(doc, s):
            template = json.loads(
                (ROOT / "stage_entries" / "mubeam.json").read_text())
            del template["njobs"]
            s["mubeam"]["entry"] = template
            del s["mubeam"]["fixed"]["njobs"]

        svc = self.with_studies(self.smoke("nonjobs", no_njobs))
        with self.assertRaises(ValueError) as cm:
            svc.budget("nonjobs", 1, "grid")
        self.assertIn("'mubeam'", str(cm.exception))
        self.assertIn("njobs", str(cm.exception))

    def test_an_undeclared_kit_is_an_error(self):
        study = self.svc.load_study("branin")
        bad = dataclasses.replace(study, steps=tuple(
            dataclasses.replace(s, kit="nokit") for s in study.steps))
        with mock.patch.object(self.svc, "load_study", return_value=bad):
            with self.assertRaises(ValueError) as cm:
                self.svc.budget("branin", 1, "grid")
        self.assertIn("'nokit'", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
