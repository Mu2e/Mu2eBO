"""service/: the autoresearch MCP server's study tools -- check a study as
`python -m graph.check_study` does, in a detached job polled for its report
(wiki/drivers/service.md)."""
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service.checks import CheckService  # noqa: E402
from service.jobs import lock_held, spawn_detached  # noqa: E402
from tests.engine_fixtures import (EngineCase, toy_pre,  # noqa: E402
                                   write_study)

LOCAL = dict(executor="local", parallel=1)


class _Svc(EngineCase):
    def setUp(self):
        super().setUp()
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


class TestSpawn(_Svc):
    def test_the_lock_lives_with_the_job(self):
        job = self.tmp / "job"
        job.mkdir()
        spawn_detached(job, 'sleep 2; echo done >"$1/out"', [],
                       dict(os.environ))
        self.assertTrue(lock_held(job / "lock"))
        deadline = time.time() + 15
        while lock_held(job / "lock"):
            self.assertLess(time.time(), deadline, "lock still held")
            time.sleep(0.2)
        self.assertEqual((job / "out").read_text(), "done\n")
        self.assertFalse(lock_held(job / "missing"))


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

    def test_a_study_that_looks_like_an_option_is_refused(self):
        # check_study would parse it as an option: "--help" printed its usage
        # into report.json and came back exit 0 with no report.
        for study in ("--help", "-h", "--x=1"):
            with self.assertRaises(ValueError, msg=study) as cm:
                self.svc.start_check(study)
            self.assertIn("starts with '-'", str(cm.exception))
        self.assertFalse(self.svc.jobs_dir.exists())


class TestStdio(_Svc):
    """service/server.py over stdio, through the SDK's own client."""

    def test_a_check_through_mcp(self):
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        write_study(toy_pre(), self.studies)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "service" / "server.py")],
            env=self.env, cwd=str(ROOT))

        async def session():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as s:
                    init = await s.initialize()
                    self.assertIn("check_result", init.instructions)
                    self.assertIn("submits", init.instructions)
                    # Exit 0 alone is not a pass: with `error` set there is no
                    # report and the exit code is not check_study's verdict.
                    self.assertIn("report.ok", init.instructions)
                    self.assertIn("`error` is set", init.instructions)
                    names = sorted(t.name for t in (await s.list_tools()).tools)
                    self.assertEqual(names, [
                        "campaign_status", "check_result", "leaderboard",
                        "list_studies", "show_study", "start_campaign",
                        "start_check", "stop_campaign", "study_guide"])
                    self.assertIn("confirm=false", init.instructions)
                    res = await s.call_tool("start_campaign", {
                        "study": "toystudy", "name_prefix": "mcpdry",
                        "q": 1, "max_evals": 2, "executor": "local",
                        "parallel": 1})
                    self.assertFalse(res.is_error, res.content)
                    self.assertTrue(res.structured_content["ok"],
                                    res.structured_content)
                    res = await s.call_tool("campaign_status", {})
                    self.assertFalse(res.is_error, res.content)
                    self.assertIn("campaigns", res.structured_content)
                    res = await s.call_tool("start_check", {
                        "study": "toystudy", "executor": "local",
                        "parallel": 1})
                    self.assertFalse(res.is_error, res.content)
                    job_id = res.structured_content["job_id"]
                    # The job must not write on this stream: the session
                    # keeps answering while it runs.
                    res = await s.call_tool("list_studies", {})
                    self.assertFalse(res.is_error, res.content)
                    self.assertIn("toystudy", [e["name"] for e in
                                               res.structured_content["result"]])
                    with anyio.fail_after(120):
                        while True:
                            res = await s.call_tool("check_result",
                                                    {"job_id": job_id})
                            self.assertFalse(res.is_error, res.content)
                            out = res.structured_content
                            if out["state"] != "running":
                                break
                            await anyio.sleep(0.5)
                    self.assertEqual(out["state"], "done", out)
                    self.assertEqual(out["exit_code"], 0, out)
                    self.assertTrue(out["report"]["ok"], out)
                    res = await s.call_tool("check_result", {"job_id": "nope"})
                    self.assertTrue(res.is_error)
                    self.assertIn("no check job", res.content[0].text)

        anyio.run(session)


if __name__ == "__main__":
    unittest.main()
