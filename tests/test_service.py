"""service/: the autoresearch MCP server's study tools -- check a study as
`python -m graph.check_study` does, in a detached job polled for its report
(spec docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md)."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service.checks import CheckService  # noqa: E402
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402

LOCAL = dict(executor="local", parallel=1)


def toy_pre(name="toystudy", **kits):
    doc = toy_doc(name)
    doc["preflight"] = {"kit": "toykit", "files": [], "params": {}}
    doc["kits"]["toykit"].update(kits)
    return doc


class _Svc(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.studies = self.tmp / "studies"
        self.studies.mkdir()
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.env = engine_env(self.data, self.studies)
        self.svc = CheckService(env=self.env)

    def wait(self, job_id, svc=None, timeout=120):
        svc = svc or self.svc
        deadline = time.time() + timeout
        while True:
            res = svc.check_result(job_id)
            if res["state"] != "running":
                return res
            if time.time() > deadline:
                self.fail(f"{job_id} still running after {timeout} s: {res}")
            time.sleep(0.5)

    def assertPassed(self, res):
        self.assertEqual(res["state"], "done", res)
        self.assertEqual(res["exit_code"], 0, res)
        self.assertIsNone(res["error"], res)
        self.assertTrue(res["report"]["ok"], res)


class TestQueries(_Svc):
    def test_list_has_good_and_broken_files(self):
        write_study(toy_pre(), self.studies)
        (self.studies / "broken.json").write_text("{}")
        by_name = {e["name"]: e for e in self.svc.list_studies()}
        toy = by_name["toystudy"]
        self.assertTrue(toy["loads"], toy)
        self.assertIsNone(toy["error"])
        self.assertEqual(toy["knobs"], ["x1", "x2"])
        self.assertEqual(toy["objectives"], ["branin", "currin"])
        self.assertEqual(toy["board"], "leaderboard_toystudy.tsv")
        self.assertEqual(toy["path"], str(self.studies / "toystudy.json"))
        broken = by_name["broken"]
        self.assertFalse(broken["loads"])
        self.assertTrue(broken["error"])
        self.assertIsNone(broken["knobs"])
        self.assertIsNone(broken["objectives"])
        self.assertIsNone(broken["board"])
        self.assertTrue(by_name["ce_chain"]["loads"], by_name["ce_chain"])

    def test_show_study(self):
        write_study(toy_pre(), self.studies)
        shown = self.svc.show_study("toystudy")
        self.assertEqual(shown["study"], toy_pre())
        self.assertEqual(shown["path"], str(self.studies / "toystudy.json"))
        with self.assertRaises(ValueError) as cm:
            self.svc.show_study("nope")
        self.assertIn("no study named 'nope'", str(cm.exception))
        self.assertIn("toystudy", str(cm.exception))

    def test_study_guide_is_the_readme(self):
        self.assertIn("### From draft to launch", self.svc.study_guide())

    def test_checks_never_imports_modes(self):
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys, service.checks; "
             "sys.exit('modes' in sys.modules or 'core.modes' in sys.modules)"],
            cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestJobs(_Svc):
    def test_a_good_study_by_name_passes(self):
        write_study(toy_pre(), self.studies)
        job = self.svc.start_check("toystudy", x=[1.5, 2], **LOCAL)
        self.assertTrue(job["job_id"].startswith("toystudy-"), job)
        self.assertEqual(job["target"], "toystudy")
        self.assertIn("--x=1.5,2.0 --executor local --parallel 1 --json",
                      job["command"])
        res = self.wait(job["job_id"])
        self.assertPassed(res)
        self.assertEqual(res["report"]["point"], {"x1": 1.5, "x2": 2.0})

    def test_a_good_study_by_relative_path_passes(self):
        write_study(toy_pre(), self.studies)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.tmp)
        job = self.svc.start_check("studies/toystudy.json", **LOCAL)
        self.assertEqual(job["target"],
                         str(self.tmp / "studies" / "toystudy.json"))
        self.assertPassed(self.wait(job["job_id"]))

    def test_study_json_writes_the_draft_and_passes(self):
        doc = toy_pre(name="drafty")
        job = self.svc.start_check(study_json=doc, **LOCAL)
        draft = self.data / "study_drafts" / "drafty.json"
        self.assertEqual(json.loads(draft.read_text()), doc)
        self.assertEqual(job["target"], str(draft))
        self.assertPassed(self.wait(job["job_id"]))

    def test_an_unknown_name_is_exit_2(self):
        job = self.svc.start_check("nope", **LOCAL)
        res = self.wait(job["job_id"])
        self.assertEqual(res["state"], "done", res)
        self.assertEqual(res["exit_code"], 2, res)
        self.assertIsNone(res["report"])
        self.assertIsNone(res["error"])
        self.assertIn("nope", res["stderr_tail"])

    def test_a_killed_job_is_lost(self):
        write_study(toy_pre(), self.studies)
        job = self.svc.start_check("toystudy", **LOCAL)
        rec = json.loads((self.svc.jobs_dir / job["job_id"] / "job.json")
                         .read_text())
        os.killpg(rec["pid"], signal.SIGKILL)
        res = self.wait(job["job_id"])
        self.assertEqual(res["state"], "lost", res)
        self.assertIsNone(res["exit_code"])

    def test_an_activate_failure_is_done_with_its_message(self):
        write_study(toy_pre(), self.studies)
        env = dict(self.env, AUTORESEARCH_PYENV="ana")
        env.pop("AUTORESEARCH_VENV", None)
        svc = CheckService(env=env)
        res = self.wait(svc.start_check("toystudy", **LOCAL)["job_id"], svc)
        self.assertEqual(res["state"], "done", res)
        self.assertEqual(res["exit_code"], 1, res)
        self.assertIsNone(res["report"])
        self.assertEqual(res["error"], "check_study's output is not JSON")
        self.assertIn("NAME VERSION", res["stderr_tail"])

    def test_a_job_id_that_is_a_path_is_unknown(self):
        for job_id in ("", ".", "..", "../check_jobs", "/etc/passwd",
                       "nope-1"):
            with self.assertRaises(ValueError, msg=job_id) as cm:
                self.svc.check_result(job_id)
            self.assertIn("no check job", str(cm.exception))

    def test_refusals(self):
        for kwargs in ({"study": "toystudy", "study_json": toy_pre()}, {}):
            with self.assertRaises(ValueError, msg=kwargs) as cm:
                self.svc.start_check(**kwargs)
            self.assertIn("exactly one of", str(cm.exception))
        for doc in ([], {}, {"name": ""}, {"name": "a-b"}):
            with self.assertRaises(ValueError, msg=doc) as cm:
                self.svc.start_check(study_json=doc)
            self.assertIn("study_json.name", str(cm.exception))
        self.assertFalse(self.svc.jobs_dir.exists())
        self.assertFalse(self.svc.drafts_dir.exists())


if __name__ == "__main__":
    unittest.main()
