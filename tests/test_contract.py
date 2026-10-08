import inspect
import json
import os
import subprocess
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from adapters import offline_preflight as op  # noqa: E402
from kits import KitClient, KitError, KitTimeout, KitToolError  # noqa: E402
from tests.engine_fixtures import (TmpCase, toy_config,  # noqa: E402
                                   toy_study, write_board)

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

    def test_status_gives_up_after_five_attempts(self):
        kit, c = self.kit([KitError("k", "status", "lost")] * 5)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(len(c.calls), 5)

    def test_status_pauses_about_four_and_a_half_minutes_in_all(self):
        pauses = []
        client = FakeClient([KitError("k", "status", "lost")] * 5)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(pauses, [5.0, 20.0, 60.0, 180.0])

    def test_results_and_cancel_share_the_long_budget(self):
        for call in ("results", "cancel"):
            self.assertEqual(ct.RETRY_PAUSES_S[call], (5.0, 20.0, 60.0, 180.0))

    def test_every_timed_call_but_start_has_a_retry_budget(self):
        # kits.toml times each contract call (kit_config.TIMEOUT_KEYS) plus
        # "start", the server launch, which is not a retried call. A call
        # added to one table and not the other would surface only as a
        # KeyError the first time a kit makes it.
        import kit_config
        self.assertEqual(set(ct.RETRY_PAUSES_S),
                         set(kit_config.TIMEOUT_KEYS) - {"start"})

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

    def test_submit_keeps_three_attempts_and_short_pauses(self):
        pauses = []
        client = FakeClient([KitTimeout("k", "submit", "timed out")] * 3)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitTimeout):
            kit.submit("c.s", {}, [], [], "w")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(pauses, [5.0, 20.0])

    def test_cancel_retries_a_lost_server_but_never_a_refusal(self):
        kit, c = self.kit([KitError("k", "cancel", "lost"),
                           {"state": "cancelled"}])
        self.assertEqual(kit.cancel("h", "w"), "cancelled")
        self.assertEqual(len(c.calls), 2)
        kit, c = self.kit([KitToolError("k", "cancel", "no such handle")])
        with self.assertRaises(KitToolError):
            kit.cancel("h", "w")
        self.assertEqual(len(c.calls), 1)


class _Toy(TmpCase):
    P = {"x1": 1.0, "x2": 2.0, "function": "branin_currin"}

    def setUp(self):
        super().setUp()
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

    def _close_order(self, failure):
        closed = []

        def make(name, exc):
            def close():
                closed.append(name)
                if exc is not None:
                    raise exc
            return types.SimpleNamespace(close=close)

        kits_by_name = {"a": make("a", failure), "b": make("b", None)}
        kits = ct.KitSet("c", opener=lambda n, c: kits_by_name[n])
        kits.get("a")
        kits.get("b")
        return kits, closed

    def test_close_guards_a_kit_failure_and_closes_every_kit(self):
        kits, closed = self._close_order(OSError("gone"))
        with self.assertRaises(KitError) as caught:
            kits.close()
        self.assertEqual((caught.exception.kit, caught.exception.tool),
                         ("a", "close"))
        self.assertEqual(closed, ["a", "b"])

    def test_close_lets_a_programming_error_through_after_closing_all(self):
        kits, closed = self._close_order(TypeError("bug"))
        with self.assertRaises(TypeError):
            kits.close()
        self.assertEqual(closed, ["a", "b"])


class TestKitErrorContract(unittest.TestCase):
    """KitSet.get hands out kits inside a guard: a kit raises only KitError
    or ContractError."""

    def kits_of(self, kit):
        kits = ct.KitSet("c", opener=lambda name, campaign: kit)
        self.addCleanup(kits.close)
        return kits

    def test_an_open_failure_becomes_a_kit_error(self):
        original = ValueError("no timeout")

        def opener(name, campaign):
            raise original

        with self.assertRaises(KitError) as caught:
            ct.KitSet("c", opener=opener).get("k")
        self.assertEqual((caught.exception.kit, caught.exception.tool),
                         ("k", "open"))
        self.assertIn("ValueError: no timeout", caught.exception.message)
        self.assertIs(caught.exception.__cause__, original)

    def test_a_failed_open_is_not_cached(self):
        calls = []

        def opener(name, campaign):
            calls.append(name)
            if len(calls) == 1:
                raise OSError("first try")
            return types.SimpleNamespace(close=lambda: None)

        kits = ct.KitSet("c", opener=opener)
        with self.assertRaises(KitError):
            kits.get("k")
        self.assertIsNotNone(kits.get("k"))
        self.assertEqual(calls, ["k", "k"])

    def test_a_method_failure_becomes_a_kit_error(self):
        for exc in (OSError("disk"), KeyError("k"),
                    subprocess.TimeoutExpired(["x"], 1)):
            with self.subTest(exc=type(exc).__name__):
                class K:
                    def submit(self, *args):
                        raise exc

                    def close(self):
                        pass

                with self.assertRaises(KitError) as caught:
                    self.kits_of(K()).get("k").submit("n")
                self.assertEqual(caught.exception.kit, "k")
                self.assertEqual(caught.exception.tool, "submit")
                self.assertIn(type(exc).__name__, caught.exception.message)
                self.assertIs(caught.exception.__cause__, exc)

    def test_a_property_failure_becomes_a_kit_error(self):
        class K:
            @property
            def tools(self):
                raise OSError("gone")

            def close(self):
                pass

        with self.assertRaises(KitError) as caught:
            self.kits_of(K()).get("k").tools
        self.assertEqual(caught.exception.tool, "tools")

    def test_a_programming_error_passes_through(self):
        class K:
            def submit(self, *args):
                raise TypeError("bug")

            def close(self):
                pass

        with self.assertRaisesRegex(TypeError, "bug"):
            self.kits_of(K()).get("k").submit("n")

    def test_contract_and_tool_errors_pass_through_unchanged(self):
        tool_error = KitToolError("k", "status", "refused")
        contract_error = ct.ContractError("k", "results", "bad reply")

        class K:
            def status(self, *args):
                raise tool_error

            def results(self, *args):
                raise contract_error

            def close(self):
                pass

        kit = self.kits_of(K()).get("k")
        with self.assertRaises(KitError) as caught:
            kit.status("h")
        self.assertIs(caught.exception, tool_error)
        with self.assertRaises(ct.ContractError) as caught:
            kit.results("h")
        self.assertIs(caught.exception, contract_error)

    def test_a_missing_optional_hook_reads_as_none(self):
        kit = self.kits_of(types.SimpleNamespace(close=lambda: None)).get("k")
        self.assertIsNone(getattr(kit, "step_problems", None))

    def test_plain_attributes_pass_through(self):
        inner = types.SimpleNamespace(accepts_lists=True, poll_s=(1.0, 2.0),
                                      close=lambda: None)
        kits = self.kits_of(inner)
        self.assertEqual(kits.get("k").accepts_lists, True)
        self.assertEqual(kits.get("k").poll_s, (1.0, 2.0))
        self.assertIs(kits.get("k"), kits.get("k"))


class TestRegistry(TmpCase):
    def test_open_calls_the_declared_factory(self):
        class Fake:
            def __init__(self, campaign, *, executor, parallel):
                self.campaign, self.executor, self.parallel = (
                    campaign, executor, parallel)

        decl = replace(kit_registry.KITS["toykit"], name="fakeadapter",
                       factory="x:Fake")
        with mock.patch.dict(kit_registry.KITS, {"fakeadapter": decl}), \
                mock.patch.object(ct, "load_factory", return_value=Fake):
            kit = ct.open_kit("fakeadapter", "camp", executor="local",
                              parallel=3)
        self.assertEqual((kit.campaign, kit.executor, kit.parallel),
                         ("camp", "local", 3))

    def test_an_undeclared_kit_is_refused(self):
        with self.assertRaises(KeyError) as cm:
            ct.open_kit("nosuchkit", "c")
        self.assertIn("kits.toml", str(cm.exception))
        self.assertIn("core/kit_registry.py", str(cm.exception))

    def test_every_declared_factory_imports_and_names_a_class(self):
        with_factory = [d for d in kit_registry.KITS.values() if d.factory]
        self.assertTrue(with_factory, "no adapter kits declared")
        for decl in with_factory:
            with self.subTest(kit=decl.name):
                cls = ct.load_factory(decl)
                self.assertTrue(inspect.isclass(cls))
                self.assertEqual(cls.name, decl.name)
        for decl in kit_registry.KITS.values():
            if not decl.factory:
                self.assertIn(decl.name, kit_registry.NATIVE)

    def test_a_flat_import_loads_the_flat_adapter(self):
        code = ("import contract, kit_registry, sys; "
                "cls = contract.load_factory(kit_registry.KITS['prodtools']); "
                "print(cls.__module__, 'core.contract' in sys.modules)")
        # PYTHONPATH is core/ alone: graph/run.py's flat import mode.
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True,
            text=True, check=True,
            env=dict(os.environ, PYTHONPATH=str(ROOT / "core")))
        self.assertEqual(out.stdout.strip(), "adapters.prodtools False")

    def test_launch_stagger(self):
        self.assertEqual(ct.launch_stagger(toy_study(self.tmp)), 0.0)

    def test_launch_stagger_is_the_largest_declared(self):
        study = toy_study(self.tmp)
        decl = replace(kit_registry.KITS["toykit"], launch_stagger_s=7.0)
        with mock.patch.dict(kit_registry.KITS, {"toykit": decl}):
            self.assertEqual(ct.launch_stagger(study), 7.0)


class TestExecutors(TmpCase):
    def setUp(self):
        super().setUp()
        self.study = toy_study(self.tmp)

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
        decl = replace(kit_registry.KITS["toykit"], executors=("grid",))
        with mock.patch.dict(kit_registry.KITS, {"toykit": decl}):
            (problem,) = ct.executor_problems(self.study, "local", None)
        self.assertIn("toykit", problem)

    def test_kerberos_only_for_a_grid_adapter_that_asks(self):
        self.assertFalse(ct.requires_kerberos(self.study, "grid"))
        decl = replace(kit_registry.KITS["toykit"], requires_kerberos=True)
        with mock.patch.dict(kit_registry.KITS, {"toykit": decl}):
            self.assertTrue(ct.requires_kerberos(self.study, "grid"))
            self.assertFalse(ct.requires_kerberos(self.study, "local"))


class TestLaunchProblems(_Toy):
    def study(self, mutate=None):
        return toy_study(self.tmp / "studies", mutate)

    def kit_set(self, opener):
        kits = ct.KitSet("c", opener=opener)
        self.addCleanup(kits.close)
        return kits

    def launch(self, study, opener, **kw):
        kw.setdefault("executor", "grid")
        kw.setdefault("config_names", ["c1"])
        return ct.launch_problems(study, self.kit_set(opener), parallel=None,
                                  **kw)

    def check(self, study, cfg=None):
        return self.launch(study, lambda n, c: self.open(n, c, cfg=cfg))

    def test_a_good_study_passes(self):
        self.assertEqual(self.check(self.study()), [])

    def test_an_unknown_param(self):
        study = self.study(lambda d: d["evaluate"][0]["params"].update(x3="x1"))
        self.assertTrue(any("x3" in p for p in self.check(study)))

    def test_an_unknown_metric(self):
        study = self.study(lambda d: d["objectives"][0].update(metric="toy.nope"))
        self.assertTrue(any("nope" in p for p in self.check(study)))

    def chained(self, params_from):
        """toy -> toy2: toy2 takes x1 from the point and params_from from
        toy; the objectives read toy2."""
        def mutate(doc):
            doc["evaluate"].append(dict(doc["evaluate"][0], step="toy2",
                                        params={"x1": "x1"},
                                        params_from=params_from))
            for o in doc["objectives"]:
                o["metric"] = "toy2." + o["metric"].split(".", 1)[1]
        return self.study(mutate)

    def test_a_params_from_study_passes(self):
        self.assertEqual(self.check(self.chained({"x2": "toy.branin"})), [])

    def test_a_params_from_metric_the_producer_does_not_return(self):
        problems = self.check(self.chained({"x2": "toy.nope"}))
        self.assertTrue(any("does not return metric(s) ['nope']" in p
                            for p in problems), problems)

    def test_a_params_from_param_the_consumer_does_not_take(self):
        problems = self.check(self.chained({"zz": "toy.branin"}))
        self.assertTrue(any("does not accept param(s)" in p and "zz" in p
                            for p in problems), problems)

    def board(self, study, *shas, header=None):
        return write_board(study, self.tmp / "b.tsv", *shas, header=header)

    def with_board(self, study, board, cfg=None):
        return self.launch(study, lambda n, c: self.open(n, c, cfg=cfg),
                           board=board)

    def toy_sha(self, study):
        kit = self.kit_set(lambda n, c: self.open(n, c)).get("toykit")
        kit.start()
        return study.measure_sha({"toykit": kit.version})

    def test_no_board_passes(self):
        study = self.study()
        lb = Leaderboard.for_study(study, path=self.tmp / "b.tsv",
                                   archive_path=None)
        self.assertEqual(self.with_board(study, lb), [])

    def test_a_header_only_board_passes(self):
        study = self.study()
        self.assertEqual(self.with_board(study, self.board(study)), [])

    def test_a_board_of_another_measure_sha_is_refused(self):
        study = self.study()
        problems = self.with_board(study, self.board(study, "a" * 64))
        self.assertEqual(len(problems), 1)
        self.assertIn("aaaaaaaaaaaa", problems[0])
        self.assertIn(self.toy_sha(study)[:12], problems[0])
        self.assertIn("leaderboard.file", problems[0])

    def test_an_archive_of_another_measure_sha_is_refused(self):
        study = self.study()
        arch = self.board(study, "b" * 64)
        arch.path.rename(self.tmp / "arch.tsv")
        lb = Leaderboard.for_study(study, path=self.tmp / "b.tsv",
                                   archive_path=self.tmp / "arch.tsv")
        problems = self.with_board(study, lb)
        self.assertEqual(len(problems), 1)
        self.assertIn("bbbbbbbbbbbb", problems[0])
        self.assertIn("leaderboard.file", problems[0])

    def test_a_board_of_this_measure_sha_passes(self):
        study = self.study()
        board = self.board(study, self.toy_sha(study))
        self.assertEqual(self.with_board(study, board), [])

    def test_a_board_with_the_wrong_header_is_refused(self):
        study = self.study()
        board = self.board(study, "a" * 64, header="config\tx\n")
        problems = self.with_board(study, board)
        self.assertEqual(len(problems), 1)
        self.assertIn("header", problems[0])

    def two_steps(self, doc):
        doc["evaluate"].append(dict(doc["evaluate"][0], step="toy2"))
        doc["extra_metrics"].append({"name": "b2", "metric": "toy2.branin",
                                     "fmt": "{:.6f}"})

    def adopted(self, **versions):
        return {step: {"kit": "toykit", "kit_version": v}
                for step, v in versions.items()}

    def test_a_resumed_point_keeps_the_version_its_steps_ran_under(self):
        study = self.study(self.two_steps)
        board = self.board(study, study.measure_sha({"toykit": "V1"}))
        problems = self.launch(
            study, lambda n, c: self.open(n, c), board=board,
            adopted=self.adopted(toy="V1", toy2="V1"))
        self.assertEqual(problems, [])

    def test_a_point_adopted_in_part_on_an_old_version_is_refused(self):
        study = self.study(self.two_steps)
        board = self.board(study, study.measure_sha({"toykit": "V1"}))
        problems = self.launch(
            study, lambda n, c: self.open(n, c), board=board,
            adopted=self.adopted(toy="V1"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("toykit", problems[0])
        self.assertIn("new config name", problems[0])

    def test_adopted_steps_of_a_kit_that_disagree_are_refused(self):
        study = self.study(self.two_steps)
        board = self.board(study, study.measure_sha({"toykit": "V1"}))
        problems = self.launch(
            study, lambda n, c: self.open(n, c), board=board,
            adopted=self.adopted(toy="V1", toy2="V2"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("toykit", problems[0])
        self.assertIn("V1", problems[0])
        self.assertIn("V2", problems[0])

    def test_a_partly_adopted_point_at_the_current_version_passes(self):
        study = self.study(self.two_steps)
        board = self.board(study, self.toy_sha(study))
        kit = self.kit_set(lambda n, c: self.open(n, c)).get("toykit")
        kit.start()
        problems = self.launch(
            study, lambda n, c: self.open(n, c), board=board,
            adopted=self.adopted(toy=kit.version))
        self.assertEqual(problems, [])

    def test_no_board_check_when_a_kit_fails(self):
        study = self.study()
        problems = self.with_board(study, self.board(study, "a" * 64),
                                   cfg=replace(self.cfg, set_env={}))
        self.assertEqual(len(problems), 1)
        self.assertIn("TOYKIT_STATE_DIR", problems[0])

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

    def preflight_only(self, doc):
        doc["kits"]["offline_preflight"] = {
            "code_tarball": "${ARTIFACT}/Code_x.tar.bz2", "dumps_gdml": False,
            "verifies_foil_gdml": False, "checks_managed_overlap": True,
            "require_zero_overlaps": False}
        doc["preflight"] = {"kit": "offline_preflight", "params": {},
                            "files": []}

    def test_a_kit_used_only_for_the_preflight_needs_only_check(self):
        study = self.study(self.preflight_only)

        def opener(name, campaign):
            if name == "offline_preflight":
                return op.OfflinePreflightKit(campaign)
            return self.open(name, campaign)

        self.assertEqual(self.launch(study, opener), [])

    def test_a_preflight_only_kit_without_check_is_refused(self):
        study = self.study(self.preflight_only)

        class NoCheck:
            accepts_lists = False
            tools = frozenset({"describe"})
            version = "1"

            def start(self):
                pass

            def describe(self):
                return None

            def close(self):
                pass

        def opener(name, campaign):
            if name == "offline_preflight":
                return NoCheck()
            return self.open(name, campaign)

        problems = self.launch(study, opener)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("['check']", problems[0])

    def test_a_kit_with_a_step_hook_is_asked_about_each_of_its_steps(self):
        study = self.study()
        asked = []

        class Hooked:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, attr):
                return getattr(self.inner, attr)

            def step_problems(self, study_, step):
                asked.append(step.step)
                return [f"step {step.step!r}: wrong analysis"]

        def opener(name, campaign):
            return Hooked(self.open(name, campaign))

        problems = self.launch(study, opener)
        self.assertEqual(asked, [s.step for s in study.steps
                                 if s.kit == "toykit"])
        self.assertIn("step 'toy': wrong analysis", problems)

    def test_a_kit_without_the_hook_reports_nothing_from_it(self):
        study = self.study()
        kit = types.SimpleNamespace()
        self.assertEqual(ct.kit_step_problems(kit, study, "toykit"), [])

    def test_a_static_problem_opens_no_kit(self):
        study = self.study()
        opened = []

        def opener(name, campaign):
            opened.append(name)
            return self.open(name, campaign)

        toy = kit_registry.KITS["toykit"]
        cases = {
            "executor": (kit_registry.KITS, dict(executor="cloud"),
                         "executor"),
            "ticket": (replace(toy, requires_kerberos=True),
                       dict(kerberos=lambda: "no ticket"), "no ticket"),
            "config name": (replace(toy, names_runs_after_config=True),
                            dict(config_names=["bad.name"]), "'.'"),
        }
        for label, (decl, kw, needle) in cases.items():
            with self.subTest(label), mock.patch.dict(
                    kit_registry.KITS, {"toykit": decl}
                    if label != "executor" else {}):
                problems = self.launch(study, opener, **kw)
                self.assertTrue(problems)
                self.assertIn(needle, " ".join(problems))
                self.assertEqual(opened, [])

    def test_an_executor_problem_skips_the_ticket(self):
        toy = replace(kit_registry.KITS["toykit"], requires_kerberos=True)
        asked = []
        with mock.patch.dict(kit_registry.KITS, {"toykit": toy}):
            problems = self.launch(self.study(), lambda n, c: self.open(n, c),
                                   executor="cloud",
                                   kerberos=lambda: asked.append(1))
        self.assertTrue(problems)
        self.assertEqual(asked, [])

    def test_start_runs_before_the_tool_check(self):
        order = []

        class Fake:
            accepts_lists = False
            version = "1"

            def start(self):
                order.append("start")

            @property
            def tools(self):
                order.append("tools")
                return frozenset({"submit", "status", "results"})

            def describe(self):
                return None

            def close(self):
                pass

        self.assertEqual(self.launch(self.study(), lambda n, c: Fake()), [])
        self.assertEqual(order[:2], ["start", "tools"])

    def test_a_kit_that_will_not_start_is_one_problem(self):
        def mutate(doc):
            self.preflight_only(doc)

        study = self.study(mutate)
        started = []

        class Broken:
            accepts_lists = False
            version = "1"
            tools = frozenset({"check"})

            def start(self):
                raise KitError("offline_preflight", "start", "boom")

            def describe(self):
                return None

            def close(self):
                pass

        def opener(name, campaign):
            if name == "offline_preflight":
                return Broken()
            started.append(name)
            return self.open(name, campaign)

        problems = self.launch(study, opener)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("offline_preflight", problems[0])
        self.assertIn("boom", problems[0])
        self.assertEqual(started, ["toykit"])

    def test_the_prodtools_rule_covers_its_steps_and_the_pre_check(self):
        study = types.SimpleNamespace(
            steps=(types.SimpleNamespace(kit="prodtools"),),
            preflight={"kit": "offline_preflight"})
        opened = []
        kits = ct.KitSet("c", opener=lambda n, c: opened.append(n))
        problems = ct.launch_problems(
            study, kits, executor="local", parallel=None,
            config_names=["smoke-1R00_00"])
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("'-'" in p for p in problems))
        self.assertEqual(opened, [])

    def test_a_kit_without_a_rule_accepts_any_name(self):
        self.assertEqual(self.launch(self.study(), lambda n, c: self.open(n, c),
                                     config_names=["a-b.c"]), [])


# A krbtgt line in klist's real shape; the expiry is far enough out that only
# an absurd min_seconds trips it.
KLIST_OK = """Ticket cache: FILE:/tmp/krb5cc_1000
Default principal: someone@FNAL.GOV

Valid starting       Expires              Service principal
01/01/2030 11:35:23  01/02/2030 13:35:19  krbtgt/FNAL.GOV@FNAL.GOV
"""


class TestKerberos(unittest.TestCase):
    """The engine's grid-launch ticket gate (moved from the pipeline's
    core/launch_checks.py in Phase C3)."""

    def setUp(self):
        # Computed the way the module does, so the test is independent of
        # the machine's timezone.
        self.expiry = ct._parse_klist_time("01/02/2030 13:35:19")

    def test_no_ticket_is_a_problem(self):
        self.assertIn("kinit", ct.check_kerberos(0, klist_text=lambda: None))

    def test_ticket_cache_without_krbtgt_is_a_problem(self):
        """An expired cache still prints a header; only a krbtgt line counts."""
        header = "Ticket cache: FILE:/tmp/krb5cc_1000\n\nValid starting\n"
        self.assertIn("kinit", ct.check_kerberos(0, klist_text=lambda: header))

    def test_zero_seconds_accepts_any_live_ticket(self):
        self.assertIsNone(ct.check_kerberos(0, klist_text=lambda: KLIST_OK))

    def test_long_ticket_passes_the_grid_life_check(self):
        self.assertIsNone(ct.check_kerberos(
            ct.GRID_TICKET_SECONDS, klist_text=lambda: KLIST_OK,
            now=lambda: self.expiry - 86400))

    def test_short_ticket_fails_the_grid_life_check(self):
        """The gate is REMAINING life, not validity."""
        problem = ct.check_kerberos(
            ct.GRID_TICKET_SECONDS, klist_text=lambda: KLIST_OK,
            now=lambda: self.expiry - 3600)
        self.assertIsNotNone(problem)
        self.assertIn("4 h left", problem)

    def test_unparseable_expiry_does_not_block_a_launch(self):
        """klist's stamp is locale-dependent; refusing to launch over a date
        format would be worse than the risk the gate guards."""
        odd = KLIST_OK.replace("01/02/2030 13:35:19", "2030-01-02T13:35:19")
        self.assertIsNone(ct.check_kerberos(ct.GRID_TICKET_SECONDS,
                                            klist_text=lambda: odd))

    def test_two_digit_year_parses(self):
        self.assertEqual(ct._parse_klist_time("01/02/30 13:35:19"),
                         self.expiry)

    def test_grid_seconds_is_four_hours(self):
        self.assertEqual(ct.GRID_TICKET_SECONDS, 4 * 3600)


if __name__ == "__main__":
    unittest.main()
