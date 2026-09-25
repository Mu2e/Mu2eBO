import json
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402
import study_loop  # noqa: E402
from tests import toykit  # noqa: E402
from tests.engine_fixtures import (ENGINE_STUDIES, engine_env,  # noqa: E402
                                   toy_doc, write_study)


def loop_cmd(study, q, max_evals, prefix, picker="budget_sob"):
    return [sys.executable, "-m", "graph.study_loop", "--study", study,
            "--q", str(q), "--max-evals", str(max_evals), "--picker", picker,
            "--name-prefix", prefix]


def board_rows(data, study):
    path = data / "autoresearch_leaderboards" / f"leaderboard_{study}.tsv"
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


def submits(data):
    path = data / "toykit" / "submits.jsonl"
    return ([json.loads(ln)["name"] for ln in path.read_text().splitlines()]
            if path.exists() else [])


class TestBusyNames(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        patch = mock.patch.object(paths, "GRID_DATA_ROOT", Path(self._td.name))
        patch.start()
        self.addCleanup(patch.stop)

    def touch(self, name, file):
        sd = study_loop.state_dir(name)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / file).write_text("x\n")

    def test_every_busy_signal(self):
        self.touch("pR01_00", "broken.txt")
        self.touch("pR02_00", "point.json")
        self.touch("pR03_00", "toy_cluster.txt")
        for name, needle in (("pR00_00", "leaderboard row"),
                             ("pR01_00", "broken.txt"),
                             ("pR02_00", "in flight"),
                             ("pR03_00", "in flight")):
            with self.subTest(name=name):
                self.assertIn(needle, study_loop.busy_reason(name, {"pR00_00"}))
        self.assertIsNone(study_loop.busy_reason("pR04_00", {"pR00_00"}))

    def test_the_in_flight_recovery_steers_to_a_new_prefix(self):
        """Removing the state dir re-picks the name with a new x, and the
        kit refuses the same <config>.<step> handle with other params: safe
        only when nothing was ever submitted."""
        self.touch("pR00_00", "toy_cluster.txt")
        reason = study_loop.busy_reason("pR00_00", set())
        self.assertIn("another --name-prefix", reason)
        self.assertIn("pgrep -f 'study_run.*pR00_00'", reason)
        self.assertIn("only", reason)
        self.assertIn("*_cluster.txt", reason)
        self.assertNotIn("or use another --name-prefix", reason)

    def test_the_pick_source_skips_busy_names_and_seeds_by_index(self):
        self.touch("pR00_00", "toy_cluster.txt")
        self.touch("pR01_00", "broken.txt")
        calls = []

        def pick(round_idx, picker, x_pending):
            calls.append((round_idx, picker, x_pending))
            return [0.0, 0.0]

        board = types.SimpleNamespace(load=lambda: [])
        with mock.patch.object(study_loop, "board_for", return_value=board):
            nxt = study_loop.make_pick_source(object(), "p", pick)
            self.assertEqual(nxt("s", "budget_sob", [])[1], "pR02_00")
            self.assertEqual(nxt("s", "budget_sob", [[1.0, 1.0]])[1], "pR03_00")
        self.assertEqual(calls, [(2, "budget_sob", []),
                                 (3, "budget_sob", [[1.0, 1.0]])])


class TestBraninCampaign(unittest.TestCase):
    """The Phase B acceptance: a toy study runs end to end from its JSON file
    alone (Branin, 2 objectives, 1 constraint, q = 2, 8 evaluations) in
    under a minute."""

    def test_eight_points_in_under_a_minute(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            t0 = time.monotonic()
            r = subprocess.run(loop_cmd("branin", 2, 8, "brn"), cwd=ROOT,
                               env=engine_env(data, ENGINE_STUDIES),
                               capture_output=True, text=True, timeout=180)
            elapsed = time.monotonic() - t0
            self.assertEqual(r.returncode, 0,
                             r.stdout[-3000:] + r.stderr[-3000:])
            rows = board_rows(data, "branin")
            names = [f"brnR{i:02d}_00" for i in range(8)]
            self.assertEqual(sorted(row["config"] for row in rows), names)
            self.assertEqual(len({row["measure_sha"] for row in rows}), 1)
            for row in rows:
                x1, x2 = float(row["x1"]), float(row["x2"])
                self.assertEqual(row["handles"], f"toy={row['config']}.toy")
                self.assertTrue(-5.0 <= x1 <= 10.0 and 0.0 <= x2 <= 15.0)
                self.assertAlmostEqual(float(row["branin"]),
                                       toykit.branin(x1, x2), places=3)
            self.assertEqual(sorted(submits(data)),
                             [f"{n}.toy" for n in names])
            self.assertLess(elapsed, 60, f"the campaign took {elapsed:.1f} s")


class TestRunnerRestart(unittest.TestCase):
    def test_a_killed_runner_restarts_without_reusing_a_name(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, studies = tmp / "data", tmp / "studies"
            doc = toy_doc(name="slowtoy", layout="v2")
            doc["evaluate"][0]["fixed"]["delay_s"] = 5.0
            write_study(doc, studies)
            env = engine_env(data, studies)
            cmd = loop_cmd("slowtoy", 2, 2, "rst")
            runner = subprocess.Popen(cmd, cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            handles = [data / "autoresearch_grid" / f"rstR0{i}_00" / "state"
                       / "toy_cluster.txt" for i in (0, 1)]
            deadline = time.monotonic() + 60
            while (not all(h.exists() for h in handles)
                   and time.monotonic() < deadline):
                time.sleep(0.2)
            self.assertTrue(all(h.exists() for h in handles))
            runner.kill()           # the parent only: children have own sessions
            runner.wait()
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                               text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
            self.assertIn("SKIP rstR00_00", r.stdout)
            self.assertIn("SKIP rstR01_00", r.stdout)
            deadline = time.monotonic() + 60
            while (len(board_rows(data, "slowtoy")) < 4
                   and time.monotonic() < deadline):
                time.sleep(0.2)
            names = sorted(row["config"] for row in board_rows(data, "slowtoy"))
            self.assertEqual(names, [f"rstR0{i}_00" for i in range(4)])
            self.assertEqual(sorted(submits(data)),
                             [f"rstR0{i}_00.toy" for i in range(4)])


class TestLaunchRefusals(unittest.TestCase):
    def test_a_study_its_kit_rejects_launches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, studies = tmp / "data", tmp / "studies"
            doc = toy_doc(name="badtoy", layout="v2")
            doc["evaluate"][0]["params"]["x3"] = "x1"
            write_study(doc, studies)
            r = subprocess.run(loop_cmd("badtoy", 1, 1, "bad"), cwd=ROOT,
                               env=engine_env(data, studies),
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("x3", r.stdout)
            self.assertFalse((data / "autoresearch_graph_data"
                              / "closed_loop_logs").exists())

    def test_a_bad_context_launches_nothing(self):
        """Validated once at launch, not by every child refusing."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, studies = tmp / "data", tmp / "studies"
            doc = toy_doc(name="ctxtoy", layout="v2")
            doc["leaderboard"]["context"] = ["alpha"]
            write_study(doc, studies)
            for study, extra, needle in (
                    ("ctxtoy", [], "needs --context"),
                    ("ctxtoy", ["--context", "beta=1"], "'beta'")):
                with self.subTest(context=extra):
                    r = subprocess.run(loop_cmd(study, 1, 1, "ctx") + extra,
                                       cwd=ROOT, env=engine_env(data, studies),
                                       capture_output=True, text=True,
                                       timeout=120)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("REFUSED", r.stdout)
                    self.assertIn(needle, r.stdout)
                    self.assertFalse((data / "autoresearch_graph_data"
                                      / "closed_loop_logs").exists())
                    self.assertEqual(submits(data), [])

    def test_a_pipeline_study_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(loop_cmd("foilspf", 1, 1, "pipe"), cwd=ROOT,
                               env=engine_env(Path(td), ENGINE_STUDIES),
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("graph.closed_loop", r.stdout)


if __name__ == "__main__":
    unittest.main()
