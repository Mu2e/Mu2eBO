import dataclasses
import json
import sys
import threading
import time
import types
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import scheduler as sch  # noqa: E402
import study as st_mod  # noqa: E402
from contract import ContractError, Results, Status  # noqa: E402
from contract import KitSet as ContractKits  # noqa: E402
from kits import KitError  # noqa: E402
from study import Step  # noqa: E402
from tests.engine_fixtures import Kits, TmpCase  # noqa: E402

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"


def step(name, files_from=(), params=None, fixed=None, kit="fake",
         params_from=None):
    return Step(name, kit, None, (), tuple(files_from), dict(params or {}),
                dict(params_from or {}), dict(fixed or {}))


def study(*steps, kits=None):
    return types.SimpleNamespace(steps=tuple(steps), kits=dict(kits or {}))


class FakeKit:
    """A scripted contract kit: each handle walks its step's states, one per
    status call; an exception in the script is raised instead."""

    def __init__(self, scripts=None, poll_s=(0.0, 0.0), poll_ms=0,
                cancellable=False, metrics=None):
        self.name, self.version, self.accepts_lists = "fake", "f1", False
        self.poll_s, self.poll_ms = poll_s, poll_ms
        self.scripts = scripts or {}
        self.metrics = metrics or {}     # {step: {name: value}}; else {"v": 1.0}
        self.tools = frozenset({"submit", "status", "results"}
                               | ({"cancel"} if cancellable else set()))
        self.events, self.submits = [], []
        self.cancelled = set()
        self._pos = {}
        self._lock = threading.Lock()

    def submit(self, name, params, files, inputs, workflow):
        with self._lock:
            self.events.append(("submit", name.split(".", 1)[1]))
            self.submits.append((name, params, files, inputs, workflow))
        return name

    def status(self, handle, workflow):
        s = handle.split(".", 1)[1]
        if handle in self.cancelled:
            return Status("cancelled", f"{s} cancelled", self.poll_ms, None)
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
        return Results(dict(self.metrics.get(s, {"v": 1.0})),
                       ({"name": s, "uri": f"file:///tmp/{s}", "kind": "text"},),
                       {})

    def cancel(self, handle, workflow):
        with self._lock:
            self.cancelled.add(handle)
            self.events.append(("cancel", handle.split(".", 1)[1]))
        return "cancelled"

    def start(self):
        pass

    def describe(self):
        return None

    def close(self):
        pass


class RaisingToolsKit:
    """Wraps a FakeKit but raises KitError from `tools`, like a NativeKit
    whose MCP server died and could not be restarted (contract.py's
    NativeKit.tools calls start() -> client.start())."""

    def __init__(self, inner):
        self._inner = inner
        self.name, self.version = inner.name, inner.version
        self.accepts_lists, self.poll_s = inner.accepts_lists, inner.poll_s

    @property
    def tools(self):
        raise KitError(self.name, "tools", "server lost")

    def submit(self, *a, **kw):
        return self._inner.submit(*a, **kw)

    def status(self, *a, **kw):
        return self._inner.status(*a, **kw)

    def results(self, *a, **kw):
        return self._inner.results(*a, **kw)

    def cancel(self, *a, **kw):
        return self._inner.cancel(*a, **kw)

    def start(self):
        pass

    def describe(self):
        return None

    def close(self):
        self._inner.close()


class FlakyKits:
    """kits.get(name) returns the mapped kit the first time it is asked
    for a flaky name, then raises KitError on every later call: models a
    kit whose server was up when its step submitted (kits.get inside
    _run_one) but is gone by the time cancellation asks for it again
    (kits.get inside _cancel_running)."""

    def __init__(self, by_name, flaky_names):
        self.by_name = dict(by_name)
        self.flaky_names = set(flaky_names)
        self.calls = {}
        self._lock = threading.Lock()

    def get(self, name):
        with self._lock:
            seen = self.calls.get(name, 0)
            self.calls[name] = seen + 1
        if name in self.flaky_names and seen >= 1:
            raise KitError(name, "get", "kit lost")
        return self.by_name[name]


class _Run(TmpCase):
    def setUp(self):
        super().setUp()
        self.state = self.tmp / "state"

    def run_steps(self, st, kit=None, env=None, sleep=None, state=None,
                 log=None, kits=None):
        return sch.run_steps(st, config="c", state_dir=state or self.state,
                             env=env or {}, files={}, kits=kits or Kits(kit),
                             workflow=lambda s: f"camp/c/{s}",
                             sleep=sleep or (lambda s: time.sleep(0.001)),
                             log=log or (lambda m: None))


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

    def test_an_adapter_oserror_mid_step_fails_the_step(self):
        class DiskFullKit(FakeKit):
            def status(self, handle, workflow):
                raise OSError("[Errno 122] Disk quota exceeded")

        kits = ContractKits("c", opener=lambda name, campaign: DiskFullKit())
        self.addCleanup(kits.close)
        out = self.run_steps(study(step("a")), kits=kits)
        self.assertFalse(out["a"].ok)
        self.assertIn("OSError", out["a"].message)
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_a_reply_outside_the_contract_fails_the_step(self):
        kit = FakeKit({"a": [ContractError("fake", "status", "bad state")]})
        out = self.run_steps(study(step("a")), kit)
        self.assertIn("outside the contract", out["a"].message)

    def test_a_failure_stops_launches_even_once_an_unrelated_dep_finishes(self):
        # "a" fails immediately; "d" is unrelated and slow but succeeds; "e"
        # depends only on "d", so a dependency-graph check alone would let it
        # launch once "d" completes. It must not: a failure anywhere stops
        # every new launch, not just ones downstream of the failed step.
        kit = FakeKit({"a": ["failed"], "d": ["working"] * 1500 + ["completed"]})
        out = self.run_steps(study(step("a"), step("d"), step("e", ["d"])), kit)
        self.assertTrue(out["d"].ok)
        self.assertNotIn("e", out)
        self.assertNotIn(("submit", "e"), kit.events)


class TestCrash(_Run):
    def test_an_uncaught_exception_logs_and_breaks_before_a_sibling_finishes(self):
        kit = FakeKit({"a": [OSError(122, "Disk quota exceeded")],
                       "c": ["working"] * 1500 + ["completed"]})
        order = []

        def log(msg):
            order.append(("log", msg))

        def sleep(s):
            # A real (tiny) delay -- not a no-op -- is what actually yields
            # the GIL/CPU to "a"'s thread between "c"'s polls; a busy no-op
            # loop can run all 1500 iterations before "a" is ever scheduled,
            # especially under a loaded test suite (this flaked in exactly
            # that way at full-suite scale before this was added).
            time.sleep(0.001)
            order.append(("sleep", s))

        with self.assertRaises(OSError):
            self.run_steps(study(step("a"), step("c")), kit, sleep=sleep,
                           log=log)

        failed_idx = next(i for i, e in enumerate(order)
                          if e[0] == "log" and e[1].startswith(
                              "[steps] a: FAILED"))
        self.assertIn("OSError", order[failed_idx][1])
        sleeps_before = sum(1 for e in order[:failed_idx] if e[0] == "sleep")
        self.assertLess(sleeps_before, 1500)
        self.assertTrue((self.state / "c_results.json").exists())
        broken = (self.state / "broken.txt").read_text()
        self.assertIn("step a", broken)
        self.assertIn("OSError", broken)

    def test_broken_txt_exists_while_a_sibling_is_still_running(self):
        # "a" fails on its very first (unslept) status call, so it is
        # essentially instant; a real, small per-poll delay for "c" (rather
        # than a no-op sleep) is what actually yields the GIL/CPU to "a"'s
        # thread, so this checks real ordering, not a busy race.
        kit = FakeKit({"a": ["failed"], "c": ["working"] * 30 + ["completed"]})
        seen = []

        def sleep(s):
            time.sleep(0.005)
            path = self.state / "broken.txt"
            if path.exists():
                seen.append(path.read_text())

        self.run_steps(study(step("a"), step("c")), kit, sleep=sleep)
        self.assertTrue(seen)
        self.assertIn("step a", seen[0])
        self.assertIn("a failed", seen[0])


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


class TestStatusFile(_Run):
    """Each poll lands in <step>_status.json for the dashboard."""

    def status(self, step_name="a"):
        return json.loads((self.state / f"{step_name}_status.json")
                          .read_text())

    def test_each_poll_is_recorded(self):
        kit = FakeKit({"a": ["working", "completed"]}, poll_s=(0.5, 2.0),
                      poll_ms=1500)
        seen = []
        before = time.time()
        self.run_steps(study(step("a")), kit,
                       sleep=lambda s: seen.append(self.status()))
        after = time.time()
        self.assertEqual(len(seen), 1)
        rec = seen[0]
        self.assertEqual((rec["state"], rec["message"], rec["progress"],
                          rec["poll_s"]), ("working", "a working", None, 1.5))
        self.assertTrue(before <= rec["time"] <= after, rec)

    def test_the_last_write_is_terminal(self):
        self.run_steps(study(step("a")), FakeKit({"a": ["working",
                                                       "completed"]}))
        rec = self.status()
        self.assertEqual((rec["state"], rec["poll_s"]), ("completed", 0.0))
        state = self.state / "f"
        self.run_steps(study(step("a")), FakeKit({"a": ["failed"]}),
                       state=state)
        rec = json.loads((state / "a_status.json").read_text())
        self.assertEqual((rec["state"], rec["poll_s"]), ("failed", 0.0))

    def test_a_failed_status_write_does_not_fail_the_step(self):
        lines = []
        # The status write goes through the point record (core/point_dir.py).
        with unittest.mock.patch.object(
                sch.PointDir, "write_status",
                side_effect=OSError(122, "Disk quota exceeded")):
            out = self.run_steps(study(step("a")), FakeKit(
                {"a": ["working", "working", "completed"]}),
                log=lines.append)
        self.assertTrue(out["a"].ok)
        self.assertFalse((self.state / "broken.txt").exists())
        warned = [ln for ln in lines if "status file not written" in ln]
        self.assertEqual(len(warned), 1, lines)
        self.assertIn("Disk quota exceeded", warned[0])

    def test_a_resume_does_not_read_it(self):
        self.state.mkdir(parents=True)
        (self.state / "a_cluster.txt").write_text("c.a\n")
        (self.state / "a_status.json").write_text("not json")
        kit = FakeKit()
        out = self.run_steps(study(step("a")), kit)
        self.assertTrue(out["a"].ok)
        self.assertEqual(kit.submits, [])


class TestParamsFrom(_Run):
    def adopt(self, name, metrics):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"{name}_results.json").write_text(json.dumps(
            {"step": name, "kit": "fake", "kit_version": "f1",
             "handle": f"c.{name}", "params": {}, "inputs": [],
             "metrics": metrics, "files": [], "metadata": {}}))

    def submitted(self, kit, name):
        return [s for s in kit.submits if s[0] == f"c.{name}"]

    def test_a_params_from_value_reaches_the_consumer(self):
        kit = FakeKit(metrics={"a": {"rate": 0.25}})
        out = self.run_steps(study(step("a"),
                                   step("b", params_from={"r": "a.rate"})), kit)
        self.assertTrue(out["b"].ok, out["b"].message)
        self.assertEqual(self.submitted(kit, "b")[0][1]["r"], 0.25)
        rec = json.loads((self.state / "b_results.json").read_text())
        self.assertEqual(rec["params"]["r"], 0.25)

    def test_the_consumer_waits_for_the_producer(self):
        kit = FakeKit({"a": ["working"] * 3 + ["completed"]})
        self.run_steps(study(step("a"), step("b", params_from={"r": "a.v"})),
                       kit)
        self.assertGreater(kit.events.index(("submit", "b")),
                           kit.events.index(("done", "a")))

    def test_a_missing_metric_fails_the_step(self):
        kit = FakeKit()
        out = self.run_steps(study(step("a"),
                                   step("b", params_from={"r": "a.rate"})), kit)
        self.assertFalse(out["b"].ok)
        self.assertIn("params_from r='a.rate': step 'a' returned no metric "
                      "'rate' (it returned ['v'])", out["b"].message)
        self.assertIn("step b", (self.state / "broken.txt").read_text())
        self.assertEqual(self.submitted(kit, "b"), [])

    def test_a_non_finite_metric_fails_the_step(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                state = self.state.parent / f"s{bad}"
                kit = FakeKit(metrics={"a": {"rate": bad}})
                out = self.run_steps(
                    study(step("a"), step("b", params_from={"r": "a.rate"})),
                    kit, state=state)
                self.assertFalse(out["b"].ok)
                self.assertIn("not a finite number", out["b"].message)
                self.assertEqual(self.submitted(kit, "b"), [])

    def test_a_non_number_metric_fails_the_step(self):
        for bad in ("0.5", True, None):
            with self.subTest(bad=bad):
                self.state = self.state.parent / f"s{bad!r}"
                self.adopt("a", {"rate": bad})
                kit = FakeKit()
                out = self.run_steps(
                    study(step("a"), step("b", params_from={"r": "a.rate"})),
                    kit)
                self.assertFalse(out["b"].ok)
                self.assertIn(f"returned {bad!r}, not a finite number",
                              out["b"].message)

    def test_an_adopted_producer_passes_its_recorded_value(self):
        self.adopt("a", {"rate": 0.125})
        kit = FakeKit()
        out = self.run_steps(study(step("a"),
                                   step("b", params_from={"r": "a.rate"})), kit)
        self.assertTrue(out["b"].ok, out["b"].message)
        self.assertEqual([s[0] for s in kit.submits], ["c.b"])
        self.assertEqual(kit.submits[0][1]["r"], 0.125)

    def test_a_failed_producer_never_submits_the_consumer(self):
        kit = FakeKit({"a": ["failed"]})
        out = self.run_steps(study(step("a"),
                                   step("b", params_from={"r": "a.v"})), kit)
        self.assertFalse(out["a"].ok)
        self.assertNotIn("b", out)
        self.assertEqual(self.submitted(kit, "b"), [])
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_one_step_in_files_from_and_params_from(self):
        kit = FakeKit()
        out = self.run_steps(study(step("a"), step("b", ["a"],
                                                   params_from={"r": "a.v"})),
                             kit)
        self.assertTrue(out["b"].ok, out["b"].message)
        b = self.submitted(kit, "b")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0][3], [{"name": "a", "uri": "file:///tmp/a",
                                    "kind": "text"}])
        self.assertEqual(b[0][1]["r"], 1.0)


class TestParams(unittest.TestCase):
    def test_a_params_from_value_may_not_replace_a_flattened_profile_element(self):
        st_ = study(step("b", params={"r": "prof"},
                         params_from={"r_1": "a.v"}))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(st_, st_.steps[0], {"prof": [1.0, 2.0, 3.0]},
                            False, {"a": {"metrics": {"v": 99.0}}})
        self.assertIn("['r_1']", str(cm.exception))
        self.assertIn("params_from", str(cm.exception))

    def test_a_params_from_value_joins_the_mapped_params(self):
        st_ = study(step("b", params={"p": "x"},
                         params_from={"r": "a.rate"}))
        self.assertEqual(
            sch.step_params(st_, st_.steps[0], {"x": 1.5}, False,
                            {"a": {"metrics": {"rate": 2.0}}}),
            {"p": 1.5, "r": 2.0})

    def test_mapped_then_settings_then_fixed(self):
        st_ = study(step("a", params={"p": "x"}, fixed={"n": 3, "mode": "fast"}),
                    kits={"fake": {"mode": "slow", "tag": "t"}})
        self.assertEqual(sch.step_params(st_, st_.steps[0], {"x": 1.5}, False, {}),
                         {"p": 1.5, "mode": "fast", "tag": "t", "n": 3})

    def test_a_profile_is_flattened_for_a_kit_without_lists(self):
        st_ = study(step("a", params={"r": "prof"}))
        env = {"prof": [1.0, 2.0]}
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, False, {}),
                         {"r_0": 1.0, "r_1": 2.0})
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, True, {}),
                         {"r": [1.0, 2.0]})

    def test_a_mapped_param_may_not_clash_with_a_setting(self):
        st_ = study(step("a", params={"n": "x"}, fixed={"n": 3}))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(st_, st_.steps[0], {"x": 1.0}, False, {})
        self.assertIn("['n']", str(cm.exception))

    def test_the_preflight_shares_the_clash_rule(self):
        """graph/study_graph.py's preflight merges through the same helper:
        a kit setting never silently replaces a mapped param."""
        self.assertEqual(sch.merge_params("preflight", {"p": 1.5}, {"tag": "t"}),
                         {"p": 1.5, "tag": "t"})
        with self.assertRaises(ValueError) as cm:
            sch.merge_params("preflight", {"function": 1.0},
                             {"function": "branin_currin"})
        self.assertIn("preflight", str(cm.exception))
        self.assertIn("['function']", str(cm.exception))
        self.assertIn("may not share a name", str(cm.exception))


class TestCancelOnFailure(_Run):
    def test_a_failure_cancels_the_running_steps(self):
        # b ends on its own (~0.5 s of 1 ms polls, long after a fails), so a
        # cancel that regresses fails this test instead of hanging it.
        kit = FakeKit({"a": ["working", "failed"],
                       "b": ["working"] * 500 + ["completed"]},
                      cancellable=True)
        out = self.run_steps(study(step("a"), step("b")), kit)
        self.assertFalse(out["a"].ok)
        self.assertFalse(out["b"].ok)
        self.assertIn("cancelled", out["b"].message)
        self.assertIn(("cancel", "b"), kit.events)
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_a_kit_that_cannot_cancel_runs_to_completion(self):
        logs = []
        kit = FakeKit({"a": ["working", "failed"],
                       "b": ["working"] * 5 + ["completed"]})
        out = self.run_steps(study(step("a"), step("b")), kit,
                             log=logs.append)
        self.assertTrue(out["b"].ok)
        self.assertTrue(any("cannot cancel" in m for m in logs), logs)

    def test_a_kit_whose_tools_check_raises_still_returns(self):
        # A step's kit.tools raising (a NativeKit whose MCP server died and
        # could not respawn) must not escape run_steps: the cancel is
        # logged as failed and the step runs to completion. "b"'s script
        # has a terminal state so a regression (the loop never even
        # attempting cancellation) fails the assertions instead of hanging.
        kit_a = FakeKit({"a": ["working", "failed"]})
        kit_b = RaisingToolsKit(FakeKit({"b": ["working"] * 200 + ["completed"]}))
        logs = []
        out = self.run_steps(
            study(step("a", kit="ka"), step("b", kit="kb")),
            log=logs.append, kits=FlakyKits({"ka": kit_a, "kb": kit_b}, ()))
        self.assertFalse(out["a"].ok)
        self.assertTrue(out["b"].ok)
        self.assertTrue(any("cancel failed" in m for m in logs), logs)

    def test_cancel_running_skips_a_kit_whose_get_raises(self):
        # kits.get() itself raising for one running step's kit (distinct
        # from a resolved kit's .tools raising, above) must not stop
        # _cancel_running from reaching the other running steps. Both "b1"
        # and "b2" have a terminal state so a regression that never
        # reaches "b2" fails the assertions instead of hanging.
        kit_a = FakeKit({"a": ["working", "failed"]})
        kit_b1 = FakeKit({"b1": ["working"] * 5 + ["completed"]})
        kit_b2 = FakeKit({"b2": ["working"] * 200 + ["completed"]},
                         cancellable=True)
        kits = FlakyKits({"ka": kit_a, "kb1": kit_b1, "kb2": kit_b2},
                         flaky_names=("kb1",))
        logs = []
        out = self.run_steps(
            study(step("a", kit="ka"), step("b1", kit="kb1"),
                 step("b2", kit="kb2")),
            log=logs.append, kits=kits)
        self.assertFalse(out["a"].ok)
        self.assertTrue(out["b1"].ok)
        self.assertFalse(out["b2"].ok)
        self.assertIn("cancelled", out["b2"].message)
        self.assertIn(("cancel", "b2"), kit_b2.events)
        self.assertTrue(any("cancel failed" in m for m in logs), logs)

    def test_a_step_not_submitted_yet_never_submits(self):
        kit = FakeKit()
        stop = threading.Event()
        stop.set()
        out = sch._run_one(study(step("a")), step("a"), "c", self.state, {},
                           {}, Kits(kit), {}, "camp/c/a",
                           lambda s: None, lambda m: None, stop)
        self.assertFalse(out.ok)
        self.assertIn("not submitted", out.message)
        self.assertEqual(kit.submits, [])


class TestEntryParam(unittest.TestCase):
    def test_an_entry_kit_gets_the_resolved_template(self):
        s = st_mod.load_study_file(DEMO)
        mubeam = next(x for x in s.steps if x.step == "mubeam")
        params = sch.step_params(s, mubeam, {}, False, {})
        self.assertEqual(params["entry"], s.entry_template("mubeam"))
        self.assertEqual(params["quorum"], 0.8)

    def test_entry_is_reserved_for_an_entry_kit(self):
        s = st_mod.load_study_file(DEMO)
        mubeam = next(x for x in s.steps if x.step == "mubeam")
        clash = dataclasses.replace(mubeam, fixed=dict(mubeam.fixed, entry=1))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(s, clash, {}, False, {})
        self.assertIn("entry", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
