import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import study as st  # noqa: E402
from kits import KitClient, KitError, KitTimeout, KitToolError  # noqa: E402
from tests.engine_fixtures import toy_config, toy_doc, write_study  # noqa: E402

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"
STATUS = {"state": "working", "message": "", "poll_ms": 100, "progress": None}
RESULTS = {"metrics": {"a": 1.0}, "files": [], "metadata": {}}


class TestParsers(unittest.TestCase):
    def assertViolation(self, fn, *needles):
        with self.assertRaises(ct.ContractError) as cm:
            fn()
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_status(self):
        s = ct.parse_status(dict(STATUS, progress={"done": 1, "total": 3,
                                                   "ok": 1}, extra=1), "k")
        self.assertEqual((s.state, s.poll_ms, s.progress["total"]),
                         ("working", 100, 3))

    def test_status_violations(self):
        for bad, needle in ((dict(STATUS, state="bogus"), "state"),
                            (dict(STATUS, poll_ms=True), "poll_ms"),
                            (dict(STATUS, poll_ms=-1), "poll_ms"),
                            (dict(STATUS, message=3), "message"),
                            (dict(STATUS, progress={"done": 1}), "total"),
                            ({"state": "working"}, "missing")):
            with self.subTest(needle=needle):
                self.assertViolation(lambda: ct.parse_status(bad, "k"), needle)

    def test_results(self):
        r = ct.parse_results({"metrics": {"a": 1, "b": 2.5},
                              "files": [{"name": "o", "uri": "file:///o",
                                         "kind": "text"}],
                              "metadata": {"m": 1}}, "k")
        self.assertEqual(r.metrics, {"a": 1.0, "b": 2.5})
        self.assertEqual(r.files, ({"name": "o", "uri": "file:///o",
                                    "kind": "text"},))

    def test_results_violations(self):
        ref = {"name": "o", "uri": "http://x", "kind": "t"}
        for bad, needle in ((dict(RESULTS, metrics={"a": "1"}), "metrics"),
                            (dict(RESULTS, metrics={"a": None}), "metrics"),
                            (dict(RESULTS, metrics={"a": True}), "metrics"),
                            (dict(RESULTS, files=[ref]), "uri"),
                            (dict(RESULTS, files="x"), "files"),
                            (dict(RESULTS, metadata=[]), "metadata")):
            with self.subTest(needle=needle):
                self.assertViolation(lambda: ct.parse_results(bad, "k"), needle)

    def test_submit_handle_must_be_the_name(self):
        self.assertEqual(ct.parse_submit({"handle": "c.s"}, "k", "c.s"), "c.s")
        self.assertViolation(
            lambda: ct.parse_submit({"handle": "other"}, "k", "c.s"), "c.s")

    def test_check_describe_cancel(self):
        self.assertEqual(ct.parse_check({"ok": False, "message": "m"}, "k"),
                         (False, "m"))
        self.assertViolation(lambda: ct.parse_check({"ok": 1, "message": ""},
                                                    "k"), "ok")
        d = ct.parse_describe({"params": ["a"], "metrics": ["m"],
                               "accepts_lists": True}, "k")
        self.assertEqual(d, ct.Describe(("a",), ("m",), True))
        self.assertEqual(ct.parse_cancel({"state": "cancelled"}, "k"),
                         "cancelled")
        self.assertViolation(lambda: ct.parse_cancel({"state": "x"}, "k"),
                             "state")


class FakeClient:
    """A scripted KitClient: one reply or exception per call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.started = True
        self.server_version = "9"
        self.tools = frozenset(ct.REQUIRED_TOOLS)
        self.campaign = "c"

    def start(self):
        pass

    def call(self, tool, args, *, timeout_s, workflow):
        self.calls.append(tool)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class TestRetryPolicy(unittest.TestCase):
    CFG = kit_registry.NATIVE["toykit"]
    DONE = dict(STATUS, state="completed")

    def kit(self, script):
        client = FakeClient(script)
        return ct.NativeKit(self.CFG, client, pause=lambda s: None), client

    def test_status_retries_transport_and_tool_errors(self):
        kit, c = self.kit([KitError("k", "status", "lost"),
                           KitToolError("k", "status", "ticket expired"),
                           self.DONE])
        self.assertEqual(kit.status("h", "w").state, "completed")
        self.assertEqual(len(c.calls), 3)

    def test_status_gives_up_after_three_attempts(self):
        kit, c = self.kit([KitError("k", "status", "lost")] * 3)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(len(c.calls), 3)

    def test_submit_retries_a_timeout(self):
        kit, c = self.kit([KitTimeout("k", "submit", "timed out"),
                           {"handle": "c.s"}])
        self.assertEqual(kit.submit("c.s", {}, [], [], "w"), "c.s")
        self.assertEqual(len(c.calls), 2)

    def test_submit_never_repeats_a_refusal(self):
        kit, c = self.kit([KitToolError("k", "submit", "different params")])
        with self.assertRaises(KitToolError):
            kit.submit("c.s", {}, [], [], "w")
        self.assertEqual(len(c.calls), 1)

    def test_cancel_is_never_retried(self):
        kit, c = self.kit([KitError("k", "cancel", "lost")])
        with self.assertRaises(KitError):
            kit.cancel("h", "w")
        self.assertEqual(len(c.calls), 1)

    def test_pauses_grow_between_attempts(self):
        pauses = []
        client = FakeClient([KitError("k", "status", "lost")] * 3)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(pauses, [5.0, 20.0])


class _Toy(unittest.TestCase):
    P = {"x1": 1.0, "x2": 2.0, "function": "branin_currin"}

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.cfg = toy_config(self.tmp / "toy")

    def open(self, name="toykit", campaign="c", cfg=None):
        cfg = cfg or self.cfg
        kit = ct.NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                          trace_dir=self.tmp / "trace"))
        self.addCleanup(kit.close)
        return kit

    def submits(self):
        path = self.tmp / "toy" / "submits.jsonl"
        return path.read_text().splitlines() if path.exists() else []


class TestNativeKitOnToykit(_Toy):
    def test_submit_status_results(self):
        kit = self.open()
        handle = kit.submit("c.toy", self.P, [], [], "c/c/toy")
        self.assertEqual(kit.status(handle, "w").state, "completed")
        self.assertIn("branin", kit.results(handle, "w").metrics)
        self.assertEqual(kit.version, "1")

    def test_resubmit_is_idempotent(self):
        kit = self.open()
        kit.submit("c.toy", self.P, [], [], "w")
        kit.submit("c.toy", self.P, [], [], "w")
        self.assertEqual(len(self.submits()), 1)

    def test_submit_timeout_then_idempotent_resubmit(self):
        cfg = replace(self.cfg, timeouts=dict(self.cfg.timeouts, submit=0.5))
        kit = self.open(cfg=cfg)
        handle = kit.submit("c.toy", dict(self.P, submit_sleep_s=3), [], [], "w")
        self.assertEqual(handle, "c.toy")
        self.assertEqual(len(self.submits()), 1)
        lines = (self.tmp / "trace" / "kit_trace.jsonl").read_text().splitlines()
        oks = [json.loads(ln)["ok"] for ln in lines
               if json.loads(ln)["tool"] == "submit"]
        self.assertEqual(oks, [False, True])

    def test_a_state_outside_the_contract(self):
        kit = self.open()
        handle = kit.submit("c.toy", dict(self.P, fail="bad_state"), [], [], "w")
        with self.assertRaises(ct.ContractError):
            kit.status(handle, "w")

    def test_check_and_describe(self):
        kit = self.open()
        self.assertEqual(kit.check("c.pre", self.P, [], [], "w"), (True, ""))
        self.assertFalse(kit.check("c.pre", dict(self.P, function="reject"),
                                   [], [], "w")[0])
        self.assertIn("x1", kit.describe().params)


class TestKitSet(unittest.TestCase):
    def test_opens_each_kit_once_and_closes_all(self):
        opened = []

        class K:
            def __init__(self, name):
                self.name, self.closed = name, False

            def close(self):
                self.closed = True

        def opener(name, campaign):
            opened.append(K(name))
            return opened[-1]

        kits = ct.KitSet("c", opener=opener)
        first = kits.get("a")
        self.assertIs(kits.get("a"), first)
        kits.get("b")
        kits.close()
        self.assertEqual([k.name for k in opened], ["a", "b"])
        self.assertTrue(all(k.closed for k in opened))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        decl = kit_registry.KitDecl("fakeadapter", study_keys={},
                                    fixed_keys={}, required_fixed=frozenset(),
                                    uses_entries=False, step_kit=True,
                                    check_kit=False, engine=True,
                                    pipeline=False)
        for patch in (mock.patch.dict(ct.ADAPTERS, {}, clear=True),
                      mock.patch.dict(kit_registry.KITS,
                                      {"fakeadapter": decl})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_register_and_open(self):
        class Fake:
            EXECUTORS = ("grid",)
            LAUNCH_STAGGER_S = 7

            def __init__(self, campaign, *, executor, parallel):
                self.campaign, self.executor, self.parallel = (
                    campaign, executor, parallel)

        ct.register_adapter("fakeadapter", Fake)
        kit = ct.open_kit("fakeadapter", "camp", executor="local", parallel=3)
        self.assertEqual((kit.campaign, kit.executor, kit.parallel),
                         ("camp", "local", 3))
        with self.assertRaises(ValueError):
            ct.register_adapter("fakeadapter", Fake)

    def test_only_an_engine_kit_without_a_kits_toml_entry_takes_an_adapter(self):
        for name in ("toykit", "nosuchkit", "offline_preflight"):
            with self.subTest(kit=name):
                with self.assertRaises(ValueError):
                    ct.register_adapter(name, object)

    def test_a_kit_with_neither_is_refused(self):
        with self.assertRaises(KeyError) as cm:
            ct.open_kit("offline_preflight", "c")
        self.assertIn("kits.toml", str(cm.exception))

    def test_launch_stagger(self):
        with tempfile.TemporaryDirectory() as td:
            study = st.load_study_file(write_study(toy_doc(), Path(td)))
        self.assertEqual(ct.launch_stagger(study), 0.0)


class TestExecutors(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.study = st.load_study_file(write_study(toy_doc(), Path(td.name)))

    def test_toykit_runs_either_way(self):
        for executor in ("grid", "local"):
            self.assertEqual(ct.executor_problems(self.study, executor, None),
                             [])

    def test_parallel_only_with_local_and_bounded(self):
        self.assertTrue(ct.executor_problems(self.study, "grid", 2))
        self.assertTrue(ct.executor_problems(self.study, "local", 17))
        self.assertEqual(ct.executor_problems(self.study, "local", 16), [])

    def test_an_unknown_executor(self):
        self.assertIn("cloud", ct.executor_problems(self.study, "cloud",
                                                    None)[0])

    def test_a_kit_that_runs_only_on_the_grid(self):
        cfg = replace(kit_registry.NATIVE["toykit"], executors=("grid",))
        with mock.patch.dict(kit_registry.NATIVE, {"toykit": cfg}):
            (problem,) = ct.executor_problems(self.study, "local", None)
        self.assertIn("toykit", problem)

    def test_kerberos_only_for_a_grid_adapter_that_asks(self):
        self.assertFalse(ct.requires_kerberos(self.study, "grid"))
        doc = toy_doc()

        class Grid:
            EXECUTORS = ("grid", "local")
            REQUIRES_KERBEROS = True
            LAUNCH_STAGGER_S = 0

        with mock.patch.dict(ct.ADAPTERS, {"toykit": Grid}):
            self.assertTrue(ct.requires_kerberos(self.study, "grid"))
            self.assertFalse(ct.requires_kerberos(self.study, "local"))


class TestCheckKits(_Toy):
    def study(self, mutate=lambda doc: None):
        doc = toy_doc()
        mutate(doc)
        return st.load_study_file(write_study(doc, self.tmp / "studies"))

    def check(self, study, cfg=None):
        return ct.check_kits(study, campaign="c",
                             opener=lambda n, c: self.open(n, c, cfg=cfg))

    def test_a_good_study_passes(self):
        self.assertEqual(self.check(self.study()), [])

    def test_an_unknown_param(self):
        study = self.study(lambda d: d["evaluate"][0]["params"].update(x3="x1"))
        self.assertTrue(any("x3" in p for p in self.check(study)))

    def test_an_unknown_metric(self):
        study = self.study(lambda d: d["objectives"][0].update(metric="toy.nope"))
        self.assertTrue(any("nope" in p for p in self.check(study)))

    def test_a_server_that_cannot_start(self):
        problems = self.check(self.study(), cfg=replace(self.cfg, set_env={}))
        self.assertEqual(len(problems), 1)
        self.assertIn("TOYKIT_STATE_DIR", problems[0])

    def test_an_unset_passthrough_variable(self):
        cfg = replace(self.cfg, env_passthrough=("TOYKIT_NOT_SET_ANYWHERE",))
        with mock.patch.dict(os.environ):
            os.environ.pop("TOYKIT_NOT_SET_ANYWHERE", None)
            problems = self.check(self.study(), cfg=cfg)
        self.assertEqual(len(problems), 1)
        self.assertIn("TOYKIT_NOT_SET_ANYWHERE", problems[0])
        self.assertIn("'toykit'", problems[0])

    def test_pipeline_kits_are_refused_without_starting_anything(self):
        # prodtools is now BOTH an engine kit (an adapter) and a pipeline
        # kit: its refusal reads differently from the other three, which
        # still have no adapter and no kits.toml entry. Force
        # AUTORESEARCH_PRODTOOLS unset regardless of the ambient
        # environment, so the adapter fails at command resolution (a
        # string substitution) and never spawns a subprocess either way.
        with mock.patch.dict(os.environ):
            os.environ.pop("AUTORESEARCH_PRODTOOLS", None)
            problems = ct.check_kits(st.load_study_file(DEMO), campaign="c")
        self.assertTrue(problems)
        self.assertTrue(all("kits.toml" in p or "AUTORESEARCH_PRODTOOLS" in p
                            for p in problems))


if __name__ == "__main__":
    unittest.main()
