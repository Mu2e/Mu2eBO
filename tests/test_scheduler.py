import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import scheduler as sch  # noqa: E402
from contract import ContractError, Results, Status  # noqa: E402
from kits import KitError  # noqa: E402
from study import Step  # noqa: E402


def step(name, files_from=(), params=None, fixed=None, kit="fake"):
    return Step(name, kit, None, (), tuple(files_from), dict(params or {}),
                dict(fixed or {}))


def study(*steps, kits=None):
    return types.SimpleNamespace(steps=tuple(steps), kits=dict(kits or {}))


class FakeKit:
    """A scripted contract kit: each handle walks its step's states, one per
    status call; an exception in the script is raised instead."""

    def __init__(self, scripts=None, poll_s=(0.0, 0.0), poll_ms=0):
        self.name, self.version, self.accepts_lists = "fake", "f1", False
        self.poll_s, self.poll_ms = poll_s, poll_ms
        self.scripts = scripts or {}
        self.events, self.submits = [], []
        self._pos = {}
        self._lock = threading.Lock()

    def submit(self, name, params, files, inputs, workflow):
        with self._lock:
            self.events.append(("submit", name.split(".", 1)[1]))
            self.submits.append((name, params, files, inputs, workflow))
        return name

    def status(self, handle, workflow):
        s = handle.split(".", 1)[1]
        seq = self.scripts.get(s, ["completed"])
        with self._lock:
            i = self._pos.get(handle, 0)
            self._pos[handle] = i + 1
        state = seq[min(i, len(seq) - 1)]
        if isinstance(state, Exception):
            raise state
        return Status(state, f"{s} {state}", self.poll_ms, None)

    def results(self, handle, workflow):
        s = handle.split(".", 1)[1]
        with self._lock:
            self.events.append(("done", s))
        return Results({"v": 1.0},
                       ({"name": s, "uri": f"file:///tmp/{s}", "kind": "text"},),
                       {})

    def close(self):
        pass


class Kits:
    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class _Run(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.state = Path(self._td.name) / "state"

    def run_steps(self, st, kit, env=None, sleep=None, state=None):
        return sch.run_steps(st, config="c", state_dir=state or self.state,
                             env=env or {}, files={}, kits=Kits(kit),
                             workflow=lambda s: f"camp/c/{s}",
                             sleep=sleep or (lambda s: time.sleep(0.001)),
                             log=lambda m: None)


class TestScheduling(_Run):
    def test_a_dependent_step_starts_before_a_slow_unrelated_step_ends(self):
        kit = FakeKit({"a": ["working"] * 3 + ["completed"],
                       "slow": ["working"] * 300 + ["completed"]})
        out = self.run_steps(study(step("a"), step("b", ["a"]), step("slow")),
                             kit)
        self.assertTrue(all(o.ok for o in out.values()))
        self.assertLess(kit.events.index(("submit", "b")),
                        kit.events.index(("done", "slow")))

    def test_inputs_are_the_upstream_files(self):
        kit = FakeKit()
        self.run_steps(study(step("a"), step("b", ["a"])), kit)
        b = next(s for s in kit.submits if s[0] == "c.b")
        self.assertEqual(b[3], [{"name": "a", "uri": "file:///tmp/a",
                                 "kind": "text"}])

    def test_handle_file_and_workflow(self):
        kit = FakeKit()
        self.run_steps(study(step("a")), kit)
        self.assertEqual((kit.submits[0][0], kit.submits[0][4]),
                         ("c.a", "camp/c/a"))
        self.assertEqual((self.state / "a_cluster.txt").read_text(), "c.a\n")

    def test_the_results_record_carries_provenance(self):
        self.run_steps(study(step("a", params={"p": "x1"}, fixed={"n": 2})),
                       FakeKit(), env={"x1": 0.5})
        rec = json.loads((self.state / "a_results.json").read_text())
        self.assertEqual((rec["kit"], rec["kit_version"], rec["handle"]),
                         ("fake", "f1", "c.a"))
        self.assertEqual(rec["params"], {"p": 0.5, "n": 2})
        self.assertEqual((rec["metrics"], rec["inputs"]), ({"v": 1.0}, []))


class TestFailures(_Run):
    def test_a_failed_step_stops_new_launches_and_writes_broken(self):
        kit = FakeKit({"a": ["failed"]})
        out = self.run_steps(study(step("a"), step("b", ["a"])), kit)
        self.assertFalse(out["a"].ok)
        self.assertNotIn("b", out)
        self.assertNotIn(("submit", "b"), kit.events)
        broken = (self.state / "broken.txt").read_text()
        self.assertIn("step a", broken)
        self.assertIn("a failed", broken)

    def test_running_steps_finish_after_a_failure(self):
        kit = FakeKit({"a": ["failed"], "c": ["working"] * 50 + ["completed"]})
        out = self.run_steps(study(step("a"), step("c")), kit)
        self.assertTrue(out["c"].ok)
        self.assertTrue((self.state / "c_results.json").exists())
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_a_cancelled_step(self):
        out = self.run_steps(study(step("a")), FakeKit({"a": ["cancelled"]}))
        self.assertFalse(out["a"].ok)
        self.assertIn("cancelled", out["a"].message)

    def test_a_kit_error_fails_the_step(self):
        kit = FakeKit({"a": [KitError("fake", "status", "boom")]})
        out = self.run_steps(study(step("a")), kit)
        self.assertFalse(out["a"].ok)
        self.assertIn("boom", out["a"].message)

    def test_a_reply_outside_the_contract_fails_the_step(self):
        kit = FakeKit({"a": [ContractError("fake", "status", "bad state")]})
        out = self.run_steps(study(step("a")), kit)
        self.assertIn("outside the contract", out["a"].message)


class TestResume(_Run):
    def test_a_results_file_skips_the_step(self):
        self.state.mkdir(parents=True)
        rec = {"step": "a", "kit": "fake", "kit_version": "f1", "handle": "c.a",
               "params": {}, "inputs": [], "metrics": {"v": 2.0},
               "files": [{"name": "old", "uri": "file:///old", "kind": "text"}],
               "metadata": {}}
        (self.state / "a_results.json").write_text(json.dumps(rec))
        kit = FakeKit()
        out = self.run_steps(study(step("a"), step("b", ["a"])), kit)
        self.assertEqual([s[0] for s in kit.submits], ["c.b"])
        self.assertEqual(out["a"].record["metrics"], {"v": 2.0})
        self.assertEqual(kit.submits[0][3], rec["files"])

    def test_a_handle_file_is_polled_not_resubmitted(self):
        self.state.mkdir(parents=True)
        (self.state / "a_cluster.txt").write_text("c.a\n")
        kit = FakeKit()
        out = self.run_steps(study(step("a")), kit)
        self.assertEqual(kit.submits, [])
        self.assertTrue(out["a"].ok)


class TestPolling(_Run):
    def test_the_poll_hint_is_clamped_to_the_kit_bounds(self):
        for poll_ms, expected in ((10, 0.5), (1500, 1.5), (10000, 2.0)):
            with self.subTest(poll_ms=poll_ms):
                slept = []
                kit = FakeKit({"a": ["working", "completed"]}, poll_s=(0.5, 2.0),
                              poll_ms=poll_ms)
                self.run_steps(study(step("a")), kit, sleep=slept.append,
                               state=self.state / str(poll_ms))
                self.assertEqual(slept, [expected])


class TestParams(unittest.TestCase):
    def test_mapped_then_settings_then_fixed(self):
        st_ = study(step("a", params={"p": "x"}, fixed={"n": 3, "mode": "fast"}),
                    kits={"fake": {"mode": "slow", "tag": "t"}})
        self.assertEqual(sch.step_params(st_, st_.steps[0], {"x": 1.5}, False),
                         {"p": 1.5, "mode": "fast", "tag": "t", "n": 3})

    def test_a_profile_is_flattened_for_a_kit_without_lists(self):
        st_ = study(step("a", params={"r": "prof"}))
        env = {"prof": [1.0, 2.0]}
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, False),
                         {"r_0": 1.0, "r_1": 2.0})
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, True),
                         {"r": [1.0, 2.0]})

    def test_a_mapped_param_may_not_clash_with_a_setting(self):
        st_ = study(step("a", params={"n": "x"}, fixed={"n": 3}))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(st_, st_.steps[0], {"x": 1.0}, False)
        self.assertIn("['n']", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
