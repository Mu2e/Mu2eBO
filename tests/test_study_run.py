import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import study as st  # noqa: E402
import study_run  # noqa: E402
from kits import KitError  # noqa: E402
from tests import toykit  # noqa: E402
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402


class _Point(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.studies = self.tmp / "studies"
        self.studies.mkdir(parents=True)
        self.data = self.tmp / "data"
        self.env = engine_env(self.data, self.studies)

    def add_study(self, mutate=lambda d: None, name="pointtoy"):
        doc = toy_doc(name=name, layout="v2")
        mutate(doc)
        write_study(doc, self.studies)
        return name

    @staticmethod
    def cmd(study, config, x):
        # "--x=" form: argparse reads "--x -3.0,2.0" as a flag, not a value.
        return [sys.executable, "-m", "graph.study_run", "--study", study,
                "--config", config, "--campaign", "t",
                "--x=" + ",".join(str(v) for v in x)]

    def run_point(self, study, config="p1", x=(1.0, 2.0)):
        return subprocess.run(self.cmd(study, config, x), cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=120)

    def state(self, config="p1"):
        return self.data / "autoresearch_grid" / config / "state"

    def board_rows(self, study):
        path = (self.data / "autoresearch_leaderboards"
                / f"leaderboard_{study}.tsv")
        return path.read_text().splitlines()[1:] if path.exists() else []

    def submits(self):
        path = self.data / "toykit" / "submits.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln)["name"] for ln in path.read_text().splitlines()]


class TestAPoint(_Point):
    def test_a_point_lands_one_row(self):
        s = self.add_study()
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = self.board_rows(s)
        self.assertTrue(row.startswith("p1\t1.000000\t2.000000\t"))
        res = json.loads((self.state() / "evaluate_result.json").read_text())
        self.assertAlmostEqual(res["primary"], toykit.branin(1.0, 2.0),
                               places=5)
        for name in ("point.json", "derived.json", "toy_cluster.txt",
                     "toy_results.json", "summary.json"):
            self.assertTrue((self.state() / name).exists(), name)
        trace = (self.data / "autoresearch_graph_data" / "t"
                 / "kit_trace.jsonl").read_text()
        self.assertIn('"workflow": "t/p1/toy"', trace)
        self.assertEqual(self.submits(), ["p1.toy"])

    def test_a_negative_knob_value(self):
        s = self.add_study()
        r = self.run_point(s, x=(-3.0, 2.0))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = self.board_rows(s)
        self.assertTrue(row.startswith("p1\t-3.000000\t2.000000\t"))


class TestFailedPoints(_Point):
    def assertBroken(self, r, *needles):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.state() / "broken.txt").read_text()
        for n in needles:
            self.assertIn(n, text)

    def test_a_failed_step(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(fail="failed"))
        self.assertBroken(self.run_point(s), "step toy", "asked to fail")
        self.assertEqual(self.board_rows(s), [])

    def test_a_missing_metric(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(
            fail="missing_metric"))
        self.assertBroken(self.run_point(s), "score", "currin")
        self.assertEqual(self.board_rows(s), [])

    def test_a_rejected_preflight_submits_nothing(self):
        def reject(d):
            d["preflight"] = {"kit": "toykit", "params": {"x1": "x1"},
                              "files": []}
            d["kits"]["toykit"]["function"] = "reject"
        s = self.add_study(reject)
        self.assertBroken(self.run_point(s), "preflight", "reject")
        self.assertEqual(self.submits(), [])
        verdict = json.loads((self.state() / "preflight_verdict.json").read_text())
        self.assertFalse(verdict["ok"])

    def test_a_preflight_param_may_not_clash_with_a_kit_setting(self):
        """The same clash rule as a step's params: the kit setting
        `function` must not silently replace the mapped value."""
        def clash(d):
            d["preflight"] = {"kit": "toykit", "params": {"function": "x1"},
                              "files": []}
        s = self.add_study(clash)
        self.assertBroken(self.run_point(s), "preflight", "['function']")
        self.assertEqual(self.submits(), [])
        self.assertEqual(self.board_rows(s), [])

    def test_a_board_measured_another_way_refuses_the_row(self):
        s = self.add_study()
        self.assertEqual(self.run_point(s).returncode, 0)
        self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=0.1))
        r = self.run_point(s, config="p2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("measure_sha",
                      (self.state("p2") / "broken.txt").read_text())
        self.assertEqual(len(self.board_rows(s)), 1)


class TestRefusals(_Point):
    def assertRefused(self, r, *needles):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for n in needles:
            self.assertIn(n, r.stdout)
        self.assertEqual(self.submits(), [])

    def test_x_outside_the_box(self):
        self.assertRefused(self.run_point(self.add_study(), x=(11.0, 2.0)),
                           "x1", "outside")

    def test_x_of_the_wrong_length(self):
        self.assertRefused(self.run_point(self.add_study(), x=(1.0,)),
                           "2 knobs")

    def test_a_pipeline_study(self):
        self.assertRefused(self.run_point("foilspf"), "graph.run")

    def test_a_broken_point_is_not_rerun(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(fail="failed"))
        self.run_point(s)
        r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("broken.txt", r.stdout)

    def test_a_different_x_under_the_same_name(self):
        s = self.add_study()
        self.run_point(s)
        r = self.run_point(s, x=(3.0, 4.0))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("point.json", r.stdout)
        self.assertEqual(self.submits(), ["p1.toy"])

    def test_a_point_json_without_the_measure_basis_sha_is_refused(self):
        """Written before point.json recorded the measurement: a resume
        cannot tell whether it changed, so it is refused, never assumed."""
        s = self.add_study()
        self.state().mkdir(parents=True)
        (self.state() / "point.json").write_text(json.dumps(
            {"study": s, "config": "p1", "campaign": "t", "x": [1.0, 2.0],
             "context": {}}))
        self.assertRefused(self.run_point(s), "point.json",
                           "measure_basis_sha")
        self.assertEqual(self.board_rows(s), [])


class TestResume(_Point):
    def kill_after_submit(self, study):
        proc = subprocess.Popen(self.cmd(study, "p1", (1.0, 2.0)), cwd=ROOT,
                                env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        handle = self.state() / "toy_cluster.txt"
        deadline = time.monotonic() + 60
        while not handle.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(handle.exists(), "the child never submitted")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        self.assertEqual(self.board_rows(study), [])

    def test_a_child_killed_mid_step_resumes_without_a_second_submit(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=4.0))
        self.kill_after_submit(s)
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("submitted by an earlier run", r.stdout)
        self.assertEqual(self.submits(), ["p1.toy"])
        self.assertEqual(len(self.board_rows(s)), 1)

    def test_a_resume_after_the_study_changed_how_it_measures_is_refused(self):
        """The killed child's job was measured the old way: adopting it
        would land old numbers stamped with the edited study's
        measure_sha."""
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=4.0))
        self.kill_after_submit(s)
        self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=4.5))
        r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("point.json", r.stdout)
        self.assertIn("measurement changed", r.stdout)
        self.assertEqual(self.board_rows(s), [])
        self.assertEqual(self.submits(), ["p1.toy"])
        self.assertFalse((self.state() / "toy_results.json").exists())


class _DeadKit:
    """A kit whose server won't start: every use raises KitError."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "0"

    def __init__(self, name):
        self.name = name

    def _dead(self, call):
        raise KitError(self.name, call, "server did not start: boom")

    @property
    def tools(self):
        self._dead("start")

    def submit(self, *args):
        self._dead("submit")

    def status(self, *args):
        self._dead("status")

    def check(self, *args):
        self._dead("check")


class _DeadKitSet:
    made = []

    def __init__(self, campaign):
        self.closed = False
        _DeadKitSet.made.append(self)

    def get(self, name):
        return _DeadKit(name)

    def close(self):
        self.closed = True


class TestKitStartCheck(unittest.TestCase):
    """study_run starts every kit the study names before anything is written
    for the point: one that won't start is an environment problem, refused
    (exit 2), never recorded as a failed evaluation in broken.txt.
    In-process: the repo's kits.toml makes an unstartable toykit hard to
    stage in a subprocess."""

    def test_a_kit_that_will_not_start_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            study = st.load_study_file(write_study(
                toy_doc(name="deadtoy", layout="v2"), tmp / "studies"))
            grid = tmp / "grid"
            out = io.StringIO()
            _DeadKitSet.made = []
            with mock.patch.dict(modes.STUDIES, {"deadtoy": study}), \
                    mock.patch.object(modes, "ENGINE",
                                      modes.ENGINE | {"deadtoy"}), \
                    mock.patch.object(study_run, "KitSet", _DeadKitSet), \
                    mock.patch.object(study_run, "GRID_DATA_ROOT", grid), \
                    mock.patch.object(study_run, "board_for", mock.Mock()), \
                    contextlib.redirect_stdout(out):
                rc = study_run.main(["--study", "deadtoy", "--config", "p1",
                                     "--campaign", "t", "--x=1.0,2.0"])
            self.assertEqual(rc, 2, out.getvalue())
            self.assertIn("REFUSED", out.getvalue())
            self.assertIn("'toykit'", out.getvalue())
            self.assertIn("boom", out.getvalue())
            self.assertFalse((grid / "p1").exists(),
                             "state written for a point that never ran")
            self.assertTrue(_DeadKitSet.made and _DeadKitSet.made[0].closed)


if __name__ == "__main__":
    unittest.main()
