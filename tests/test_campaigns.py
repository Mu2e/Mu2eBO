"""service/campaigns.py: the autoresearch MCP server's campaign tools --
start (a dry run, then confirm), stop, status and the leaderboard -- on the
branin engine study, locally (spec
docs/superpowers/specs/2026-10-02-campaign-tools-design.md)."""
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
from service.campaigns import CampaignService, is_child  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES, engine_env  # noqa: E402

LOCAL = ["--picker", "budget_sob", "--executor", "local", "--parallel", "1"]


class _Camp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.data = self.tmp / "data"
        self.data.mkdir()
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

    def test_an_unknown_prefix(self):
        st = self.svc.campaign_status("nothing")
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


if __name__ == "__main__":
    unittest.main()
