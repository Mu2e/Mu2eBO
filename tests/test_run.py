import contextlib
import dataclasses
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
import contract  # noqa: E402
import kit_config  # noqa: E402
import modes  # noqa: E402
import study as st  # noqa: E402
import run  # noqa: E402
from kits import KitError  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from tests import toykit  # noqa: E402
from tests.engine_fixtures import (EngineCase, TmpCase,  # noqa: E402
                                   board_rows, submits, toy_doc, toy_study,
                                   write_study)


class _Point(EngineCase):
    def add_study(self, mutate=lambda d: None, name="pointtoy"):
        doc = toy_doc(name=name, layout="v2")
        mutate(doc)
        write_study(doc, self.studies)
        return name

    @staticmethod
    def cmd(study, config, x):
        # "--x=" form: argparse reads "--x -3.0,2.0" as a flag, not a value.
        return [sys.executable, "-m", "graph.run", "--study", study,
                "--config", config, "--campaign", "t",
                "--x=" + ",".join(str(v) for v in x)]

    def run_point(self, study, config="p1", x=(1.0, 2.0)):
        return subprocess.run(self.cmd(study, config, x), cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=120)

    def state(self, config="p1"):
        return self.data / "autoresearch_grid" / config / "state"

    def board_rows(self, study):
        return board_rows(self.data, study)

    def submits(self):
        return submits(self.data)

    def kill_after(self, study, *names, config="p1"):
        """Start graph.run on `config`, then SIGKILL its process group (its
        kit server too; toykit's jobs live on disk) once every state file in
        `names` exists."""
        proc = subprocess.Popen(self.cmd(study, config, (1.0, 2.0)), cwd=ROOT,
                                env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        paths = [self.state(config) / name for name in names]
        deadline = time.monotonic() + 60
        while (not all(p.exists() for p in paths)
               and time.monotonic() < deadline):
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        self.assertEqual([p.name for p in paths if not p.exists()], [],
                         "the child never wrote them")


class TestAPoint(_Point):
    def test_a_point_lands_one_row(self):
        s = self.add_study()
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = self.board_rows(s)
        self.assertEqual(list(row.items())[:3],
                         [("config", "p1"), ("x1", "1.000000"),
                          ("x2", "2.000000")])
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
        self.assertEqual(list(row.items())[:3],
                         [("config", "p1"), ("x1", "-3.000000"),
                          ("x2", "2.000000")])


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

    def test_a_board_measured_another_way_refuses_the_launch(self):
        s = self.add_study()
        self.assertEqual(self.run_point(s).returncode, 0)
        self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=0.1))
        r = self.run_point(s, config="p2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("leaderboard.file", r.stdout)
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
        self.kill_after(study, "toy_cluster.txt")
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


def _with_slow(doc):
    """A second toykit step, slow, beside toy (which feeds the objectives)."""
    doc["evaluate"].append(dict(doc["evaluate"][0], step="slow",
                                fixed={"delay_s": 30.0}))
    doc["extra_metrics"] = [{"name": "slow_branin", "metric": "slow.branin",
                             "fmt": "{:.6f}"}]


class _VersionedKit:
    """toykit's stand-in for graph.run in this process, at the version a
    test sets: every job is complete at once, with toykit's metrics at
    x = (1, 2)."""
    name, accepts_lists, poll_s = "toykit", False, (0.0, 0.0)
    tools = frozenset({"submit", "status", "results"})

    def __init__(self, version):
        self.version = version
        self.submits = []

    def start(self):
        pass

    def describe(self):
        return None

    def close(self):
        pass

    def submit(self, name, params, files, inputs, workflow):
        self.submits.append(name)
        return name

    def status(self, handle, workflow):
        return contract.Status("completed", "", 0, None)

    def results(self, handle, workflow):
        return contract.Results({"branin": toykit.branin(1.0, 2.0),
                                 "currin": toykit.currin(1.0, 2.0),
                                 "n_inputs": 0.0}, (), {})


class TestAKitBumpInFlight(_Point):
    """A step submitted under one kit version and resumed under another.
    The version at submit is recorded (state/<step>_submit.json), so the
    launch check refuses the resume before anything runs, whatever the
    board holds; before, the board check alone let an empty board, or one
    at the new version, take the row stamped with the new version."""

    def bump(self, version="2"):
        """toykit reports `version` from its next start (tests/toykit.py)."""
        (self.data / "toykit" / "version").write_text(version)

    def assertRefusedUnwritten(self, r, study, *needles):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for needle in needles + ("new config name",):
            self.assertIn(needle, r.stdout)
        self.assertNotIn("leaderboard.file", r.stdout)
        self.assertEqual(self.board_rows(study), [])
        self.assertFalse((self.state() / "broken.txt").exists())

    def run_main(self, study, kit, before):
        """graph.run's main in this process: `kit` for every kit name, the
        point's state files staged by `before(state)`, and a board in the
        temp dir. (rc, stdout, board)."""
        grid = self.tmp / "grid"
        state = grid / "p1" / "state"
        state.mkdir(parents=True)
        before(state)
        board = Leaderboard.for_study(study, path=self.tmp / "board.tsv",
                                      archive_path=None)
        out = io.StringIO()
        with mock.patch.dict(modes.STUDIES, {study.name: study}), \
                mock.patch.object(run, "KitSet", lambda campaign, **kw:
                                  contract.KitSet(campaign,
                                                  opener=lambda n, c: kit)), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for",
                                  mock.Mock(return_value=board)), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", study.name, "--config", "p1",
                           "--campaign", "t", "--x=1.0,2.0"])
        return rc, out.getvalue(), board

    def test_a_bump_in_flight_on_an_empty_board_is_refused(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(
            delay_s=4.0))
        self.kill_after(s, "toy_cluster.txt")
        self.bump()
        r = self.run_point(s)
        self.assertRefusedUnwritten(
            r, s, "['toy'] were submitted under version '1'", "now '2'")
        self.assertEqual(self.submits(), ["p1.toy"])
        self.assertFalse((self.state() / "toy_results.json").exists())

    def test_a_bump_beside_a_step_of_the_kit_finished_before_it(self):
        s = self.add_study(_with_slow)
        self.kill_after(s, "toy_results.json", "slow_cluster.txt")
        self.bump()
        r = self.run_point(s)
        self.assertRefusedUnwritten(
            r, s, "['slow'] were submitted under version '1'", "now '2'")
        self.assertEqual(sorted(self.submits()), ["p1.slow", "p1.toy"])
        self.assertFalse((self.state() / "slow_results.json").exists())

    def test_a_bump_beside_a_step_of_the_kit_finished_after_it(self):
        """slow was submitted under 1, then the kit's server respawned at 2
        and toy ran under it: toy's record agrees with the kit, so only
        slow's submit record tells that the point spans the bump."""
        study = toy_study(self.studies, _with_slow, name="spantoy")

        def before(state):
            (state / "toy_results.json").write_text(json.dumps(
                {"step": "toy", "kit": "toykit", "kit_version": "2",
                 "handle": "p1.toy", "params": {}, "inputs": [],
                 "metrics": {"branin": 1.0, "currin": 2.0, "n_inputs": 0.0},
                 "files": [], "metadata": {}}))
            (state / "slow_submit.json").write_text(json.dumps(
                {"kit": "toykit", "kit_version": "1"}))
            (state / "slow_cluster.txt").write_text("p1.slow\n")

        kit = _VersionedKit("2")
        rc, out, board = self.run_main(study, kit, before)
        self.assertEqual(rc, 2, out)
        self.assertIn("['slow'] were submitted under version '1'", out)
        self.assertFalse(board.path.exists(), "a row was written")
        self.assertEqual(kit.submits, [])

    def test_a_handle_from_before_the_submit_records_resumes_as_before(self):
        """Written by the code before this record existed (as a point in
        flight at the upgrade has it): polled, recorded at the kit's
        version, never refused and never given a guessed record."""
        study = toy_study(self.studies, name="legacytoy")
        kit = _VersionedKit("1")
        rc, out, board = self.run_main(
            study, kit,
            lambda state: (state / "toy_cluster.txt").write_text("p1.toy\n"))
        self.assertEqual(rc, 0, out)
        self.assertIn("submitted by an earlier run", out)
        self.assertEqual(kit.submits, [])
        self.assertEqual(board.measure_shas(),
                         {study.measure_sha({"toykit": "1"})})
        state = self.tmp / "grid" / "p1" / "state"
        self.assertFalse((state / "toy_submit.json").exists())

    def test_a_point_upgraded_mid_flight_resumes_every_step(self):
        """The state a point started by the earlier code has when the new
        code resumes it (bpzup08/09 at the 2026-10-08 merge): one step
        finished, one in flight, one not yet submitted, and no submit
        record anywhere. The finished step is adopted, the in-flight one
        polled, and only the new submit gets a record."""
        def with_late(doc):
            _with_slow(doc)
            doc["evaluate"].append(dict(doc["evaluate"][0], step="late"))
            doc["extra_metrics"].append({"name": "late_branin",
                                         "metric": "late.branin",
                                         "fmt": "{:.6f}"})
        study = toy_study(self.studies, with_late, name="upgradetoy")

        def before(state):
            (state / "toy_results.json").write_text(json.dumps(
                {"step": "toy", "kit": "toykit", "kit_version": "1",
                 "handle": "p1.toy", "params": {}, "inputs": [],
                 "metrics": {"branin": 1.0, "currin": 2.0, "n_inputs": 0.0},
                 "files": [], "metadata": {}}))
            (state / "slow_cluster.txt").write_text("p1.slow\n")

        kit = _VersionedKit("1")
        rc, out, board = self.run_main(study, kit, before)
        self.assertEqual(rc, 0, out)
        self.assertEqual(kit.submits, ["p1.late"])
        self.assertEqual(board.measure_shas(),
                         {study.measure_sha({"toykit": "1"})})
        state = self.tmp / "grid" / "p1" / "state"
        self.assertFalse((state / "toy_submit.json").exists())
        self.assertFalse((state / "slow_submit.json").exists())
        self.assertEqual(json.loads((state / "late_submit.json").read_text()),
                         {"kit": "toykit", "kit_version": "1"})

    def test_a_resume_at_the_submit_version_adopts_the_job(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(
            delay_s=4.0))
        self.kill_after(s, "toy_cluster.txt")
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("submitted by an earlier run", r.stdout)
        self.assertEqual(self.submits(), ["p1.toy"])
        study = st.load_study_file(self.studies / f"{s}.json")
        (row,) = self.board_rows(s)
        self.assertEqual(row["measure_sha"],
                         study.measure_sha({"toykit": "1"}))
        self.assertEqual(json.loads(
            (self.state() / "toy_submit.json").read_text()),
            {"kit": "toykit", "kit_version": "1"})


class TestRunLock(_Point):
    """graph.run holds the point's state/run.lock while it runs."""

    def pd(self, config="p1"):
        from point_dir import PointDir
        return PointDir.of(self.data / "autoresearch_grid", config)

    def test_a_second_runner_on_a_running_point_is_refused(self):
        s = self.add_study()
        with self.pd().run_lock():
            r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("already running", r.stdout)
        self.assertFalse((self.state() / "toy_cluster.txt").exists())
        self.assertEqual(self.submits(), [])

    def test_a_killed_runner_frees_its_point(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(
            delay_s=30.0))
        proc = subprocess.Popen(self.cmd(s, "p1", (1.0, 2.0)), cwd=ROOT,
                                env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        self.addCleanup(lambda: (os.killpg(proc.pid, signal.SIGKILL)
                                 if proc.poll() is None else None,
                                 proc.wait()))
        handle = self.state() / "toy_cluster.txt"
        deadline = time.monotonic() + 60
        while not handle.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(handle.exists(), "the child never submitted")
        self.assertTrue(self.pd().running())
        os.kill(proc.pid, signal.SIGKILL)     # graph.run only: its kit lives
        proc.wait()
        deadline = time.monotonic() + 2
        while self.pd().running() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.pd().running())
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # the kit server, if alive
        except ProcessLookupError:
            pass


class _DeadKit:
    """A kit whose server won't start: every use raises KitError."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "0"

    def __init__(self, name):
        self.name = name

    def _dead(self, call):
        raise KitError(self.name, call, "server did not start: boom")

    def start(self):
        self._dead("start")

    @property
    def tools(self):
        self._dead("start")

    def submit(self, *args):
        self._dead("submit")

    def status(self, *args):
        self._dead("status")

    def check(self, *args):
        self._dead("check")


class _HookedKit:
    """A kit that starts but whose step hook finds a problem."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "1"
    tools = frozenset({"submit", "status", "results"})

    def __init__(self, name):
        self.name = name

    def start(self):
        pass

    def describe(self):
        return None

    def step_problems(self, study, step):
        return [f"step {step.step!r}: no analysis 'nosuch'"]


class _FakeKitSet:
    """run.KitSet stand-in: hands out kit(name) for every name, recording
    each kit asked for and whether it was closed; `made` lists the sets."""
    kit, made = None, []

    def __init__(self, campaign, *, executor="grid", parallel=None):
        self.gets = []
        self.closed = False
        type(self).made.append(self)

    def get(self, name):
        self.gets.append(name)
        return self.kit(name)

    def close(self):
        self.closed = True


class _DeadKitSet(_FakeKitSet):
    kit, made = _DeadKit, []


class _HookedKitSet(_FakeKitSet):
    kit, made = _HookedKit, []


class TestExecutorFlag(_Point):
    def run_with(self, study, *flags, config="p1"):
        return subprocess.run(self.cmd(study, config, (1.0, 2.0)) + list(flags),
                              cwd=ROOT, env=self.env, capture_output=True,
                              text=True, timeout=120)

    def test_local_is_recorded_and_a_switch_is_refused(self):
        s = self.add_study()
        r = self.run_with(s, "--executor", "local", "--parallel", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        point = json.loads((self.state() / "point.json").read_text())
        self.assertEqual(point["executor"], "local")
        r = self.run_with(s, "--executor", "grid")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--executor local", r.stdout)

    def test_parallel_with_grid_is_refused(self):
        r = self.run_with(self.add_study(), "--parallel", "2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--parallel", r.stdout)

    def test_a_point_json_without_an_executor_is_refused(self):
        s = self.add_study()
        study = st.load_study_file(self.studies / f"{s}.json")
        self.state().mkdir(parents=True)
        (self.state() / "point.json").write_text(json.dumps(
            {"study": s, "config": "p1", "campaign": "t", "x": [1.0, 2.0],
             "context": {}, "measure_basis_sha": study.measure_basis_sha}))
        r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("executor", r.stdout)

    def test_a_step_hook_problem_refuses_and_writes_nothing(self):
        study = toy_study(self.studies, name="hooktoy")
        grid = self.tmp / "grid"
        out = io.StringIO()
        _HookedKitSet.made = []
        with mock.patch.dict(modes.STUDIES, {"hooktoy": study}), \
                mock.patch.object(run, "KitSet", _HookedKitSet), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for", mock.Mock()), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", "hooktoy", "--config", "p1",
                           "--campaign", "t", "--x=1.0,2.0"])
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("REFUSED", out.getvalue())
        self.assertIn("no analysis 'nosuch'", out.getvalue())
        self.assertFalse((grid / "p1").exists(),
                         "state written for a point that never ran")
        self.assertTrue(_HookedKitSet.made[0].closed)

    def test_the_launch_check_gets_the_adopted_step_records(self):
        study = toy_study(self.studies, name="adoptoy")
        grid = self.tmp / "grid"
        state = grid / "p1" / "state"
        state.mkdir(parents=True)
        record = {"kit": "toykit", "kit_version": "V1", "handle": "h"}
        (state / "toy_results.json").write_text(json.dumps(record))
        with mock.patch.dict(modes.STUDIES, {"adoptoy": study}), \
                mock.patch.object(run, "KitSet", _HookedKitSet), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for", mock.Mock()), \
                mock.patch.object(run, "launch_problems",
                                  return_value=["stop"]) as launch, \
                contextlib.redirect_stdout(io.StringIO()):
            rc = run.main(["--study", "adoptoy", "--config", "p1",
                           "--campaign", "t", "--x=1.0,2.0"])
        self.assertEqual(rc, 2)
        self.assertEqual(launch.call_args.kwargs["adopted"],
                         {"toy": record})


class TestNothingStartsBeforeTheChecks(TmpCase):
    def refuse_toy(self, *args, decl_patch=None, before=None):
        study = toy_study(self.tmp / "studies", name="gatetoy")
        grid = self.tmp / "grid"
        if before:
            before(grid)
        out = io.StringIO()
        _HookedKitSet.made = []
        flat = sys.modules["kit_registry"]
        patched = {}
        if decl_patch:
            patched = {"toykit": dataclasses.replace(
                flat.KITS["toykit"], **decl_patch)}
        with mock.patch.dict(modes.STUDIES, {"gatetoy": study}), \
                mock.patch.dict(flat.KITS, patched), \
                mock.patch.object(run, "KitSet", _HookedKitSet), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for", mock.Mock()), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", "gatetoy", *args, "--campaign", "t",
                           "--x=1.0,2.0"])
        gets = [g for k in _HookedKitSet.made for g in k.gets]
        return rc, out.getvalue(), grid, gets

    def test_a_bad_config_name_refuses_and_writes_nothing(self):
        rc, out, grid, gets = self.refuse_toy(
            "--config", "bad.name",
            decl_patch={"names_runs_after_config": True})
        self.assertEqual(rc, 2, out)
        self.assertIn("REFUSED", out)
        self.assertIn("'.'", out)
        self.assertFalse((grid / "bad.name").exists())
        self.assertEqual(gets, [])

    def test_a_broken_point_starts_no_kit(self):
        def before(grid):
            state = grid / "p1" / "state"
            state.mkdir(parents=True)
            (state / "broken.txt").write_text("step toy failed")

        rc, out, grid, gets = self.refuse_toy("--config", "p1", before=before)
        self.assertEqual(rc, 2, out)
        self.assertIn("broken.txt", out)
        self.assertEqual(gets, [])


class TestKitStartCheck(TmpCase):
    """run starts every kit the study names before anything is written
    for the point: one that won't start is an environment problem, refused
    (exit 2), never recorded as a failed evaluation in broken.txt.
    In-process: the repo's kits.toml makes an unstartable toykit hard to
    stage in a subprocess."""

    def test_a_kit_that_will_not_start_refuses_and_writes_nothing(self):
        study = toy_study(self.tmp / "studies", name="deadtoy")
        grid = self.tmp / "grid"
        out = io.StringIO()
        _DeadKitSet.made = []
        with mock.patch.dict(modes.STUDIES, {"deadtoy": study}), \
                mock.patch.object(run, "KitSet", _DeadKitSet), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for", mock.Mock()), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", "deadtoy", "--config", "p1",
                           "--campaign", "t", "--x=1.0,2.0"])
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("REFUSED", out.getvalue())
        self.assertIn("'toykit'", out.getvalue())
        self.assertIn("boom", out.getvalue())
        self.assertFalse((grid / "p1").exists(),
                         "state written for a point that never ran")
        self.assertTrue(_DeadKitSet.made and _DeadKitSet.made[0].closed)


class _DiskFullKit:
    """A whole kit whose server is up but whose status call hits a full disk,
    as an adapter's OSError does mid-step."""
    name, version = "toykit", "1"
    accepts_lists, poll_s = False, (0.0, 0.0)
    tools = frozenset({"submit", "status", "results"})

    def start(self):
        pass

    def describe(self):
        return None

    def submit(self, name, params, files, inputs, workflow):
        return name

    def status(self, handle, workflow):
        raise OSError("[Errno 122] Disk quota exceeded")

    def close(self):
        pass


class _DiskFullKitSet(contract.KitSet):
    def __init__(self, campaign, *, executor="grid", parallel=None):
        super().__init__(campaign, opener=lambda name, campaign: _DiskFullKit())


class TestKitErrorContract(TmpCase):
    """A kit failure the adapters used to let escape as ValueError or
    OSError is a refusal at launch and a broken point mid-step, never a
    traceback."""

    def test_a_prodtools_kit_missing_a_server_timeout_refuses(self):
        study = st.load_study_file(
            ROOT / "tests/fixtures/engine_studies/prodtools_smoke.json")
        toml = self.tmp / "kits.toml"
        toml.write_text(
            "[servers.prodtools_write]\n"
            'command = ["w"]\nenv_passthrough = []\nset = {}\n'
            "timeouts = { start = 1, submit_once = 1 }\n"
            "[servers.prodtools_read]\n"
            'command = ["r"]\nenv_passthrough = []\nset = {}\n'
            "timeouts = { start = 1, run_status = 1 }\n")
        servers = kit_config.load_server_configs(toml)
        grid = self.tmp / "grid"
        out = io.StringIO()
        with mock.patch.dict(modes.STUDIES, {"prodtools_smoke": study}), \
                mock.patch.object(kit_config, "load_server_configs",
                                  return_value=servers), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for", mock.Mock()), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", "prodtools_smoke", "--config",
                           "smoke01", "--campaign", "t", "--executor",
                           "local"])
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("REFUSED", out.getvalue())
        self.assertIn("run_local", out.getvalue())
        self.assertFalse((grid / "smoke01").exists())

    def test_an_adapter_oserror_mid_step_breaks_the_point(self):
        study = toy_study(self.tmp / "studies", name="fulltoy")
        grid = self.tmp / "grid"
        board = mock.Mock()
        board.measure_shas.return_value = set()
        out = io.StringIO()
        with mock.patch.dict(modes.STUDIES, {"fulltoy": study}), \
                mock.patch.object(run, "KitSet", _DiskFullKitSet), \
                mock.patch.object(run, "GRID_DATA_ROOT", grid), \
                mock.patch.object(run, "board_for",
                                  mock.Mock(return_value=board)), \
                contextlib.redirect_stdout(out):
            rc = run.main(["--study", "fulltoy", "--config", "p1",
                           "--campaign", "t", "--x=1.0,2.0"])
        self.assertEqual(rc, 0, out.getvalue())
        broken = (grid / "p1" / "state" / "broken.txt").read_text()
        self.assertIn("step toy", broken)
        self.assertIn("OSError", broken)
        self.assertFalse(board.append.called, "a row was appended")


class TestAutoresearchLocalRefused(unittest.TestCase):
    """AUTORESEARCH_LOCAL was the deleted pipeline's grid-free activation
    switch (wiki/drivers/local-executor.md); nothing in the engine reads it
    any more. A stale export must refuse loudly, not be silently ignored --
    the engine's grid-free equivalent is --executor local."""

    def test_set_env_var_refuses_before_any_kit_starts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            study = st.load_study_file(write_study(
                toy_doc(name="localenvtoy", layout="v2"), tmp / "studies"))
            out = io.StringIO()
            with mock.patch.dict(modes.STUDIES, {"localenvtoy": study}), \
                    mock.patch.dict(os.environ, {"AUTORESEARCH_LOCAL": "1"}), \
                    contextlib.redirect_stdout(out):
                rc = run.main(["--study", "localenvtoy", "--config", "p1",
                              "--campaign", "t", "--x=1.0,2.0"])
            self.assertEqual(rc, 2, out.getvalue())
            self.assertIn("REFUSED", out.getvalue())
            self.assertIn("--executor local", out.getvalue())
            self.assertIn("AUTORESEARCH_LOCAL", out.getvalue())

    def test_env_var_absent_is_unaffected(self):
        """No regression: TestAPoint.test_a_point_lands_one_row and every
        other test in this file already run with AUTORESEARCH_LOCAL unset
        and land a row, so this only pins the negative explicitly."""
        self.assertNotIn("AUTORESEARCH_LOCAL", os.environ)


class TestOldAndArchivedShapes(unittest.TestCase):
    def test_the_old_pipeline_command_shape_is_refused(self):
        """The pipeline's `graph.run --mode foilspf --x-point ...` must fail
        loudly at argparse, not start anything."""
        with self.assertRaises(SystemExit) as cm, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            run.main(["--mode", "foilspf", "--x-point", "1,2,3"])
        self.assertEqual(cm.exception.code, 2)

    def test_an_archived_study_is_unknown_with_a_hint(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = run.main(["--study", "ipafix", "--config", "c3x01",
                              "--campaign", "c3x", "--x=1"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown study 'ipafix'", out.getvalue())
        self.assertIn("mode_specs/archive/", out.getvalue())


class TestLineBufferedStdout(unittest.TestCase):
    """An operator launches a runner with stdout sent to a log file, where
    print() is block-buffered: before this fix a live campaign's parent log
    showed no [pool] line until the process exited (c3loop01, 2026-09-29)."""

    def test_a_line_reaches_a_pipe_before_the_process_exits(self):
        code = (f"import sys, time; sys.path[:0] = [{str(ROOT / 'graph')!r}, "
                f"{str(ROOT / 'core')!r}]; import run; "
                f"run.line_buffered_stdout(); print('first'); time.sleep(120)")
        p = subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.PIPE, text=True)
        try:
            import select
            ready, _, _ = select.select([p.stdout], [], [], 60)
            self.assertTrue(ready, "no output within 60 s: stdout is buffered")
            self.assertEqual(p.stdout.readline().strip(), "first")
            self.assertIsNone(p.poll(), "the line must arrive while it runs")
        finally:
            p.kill()
            p.wait()
            p.stdout.close()

    def test_both_entry_points_call_it(self):
        for name in ("run.py", "closed_loop.py"):
            text = (ROOT / "graph" / name).read_text()
            tail = text.split('if __name__ == "__main__":')[1]
            self.assertIn("line_buffered_stdout()", tail, name)


if __name__ == "__main__":
    unittest.main()
