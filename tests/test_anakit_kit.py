"""core/adapters/anakit.py: anakit (M. MacKenzie's analysis MCP server) as
a contract kit (Phase C2b spec, section 3; on a Musing since
docs/superpowers/specs/2026-10-07-upstream-analyses-design.md). Unit tests
drive the adapter with a fake client; one test drives it through the real
KitClient against tests/fakeanakit.py over stdio."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
from adapters import anakit as ak  # noqa: E402
from contract import ContractError  # noqa: E402
from kit_config import ServerConfig  # noqa: E402
from kits import KitError  # noqa: E402
from study import Step  # noqa: E402
from tests.fakeanakit import CATALOGUE  # noqa: E402

MUSING = "SimJob MDC2025ay"
STOPS_METRICS = {"n_events": 296174.0, "n_gen_events": 3e6, "prescale": 1.0,
                 "stops_per_gen_event": 0.0987, "stops_per_pot": 1.26e-3}
SUCCESS = {"status": "success", "files": [], "message": "muon_stop_rate ok",
           "metadata": {**STOPS_METRICS, "analysis": "muon_stop_rate",
                        "log_path": "/x.log"}}


def server(**timeouts):
    t = {"start": 60, "list_analyses": 30, "run_analysis": 3600}
    t.update(timeouts)
    return ServerConfig(name="anakit", command=("python", "-P", "-m",
                                                 "analysis_mcp_server"),
                        env_passthrough=(), set_env={}, timeouts=t)


def git_repo(root, *files):
    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                    capture_output=True)
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@example.org", "commit",
        "-q", "-m", "init")
    return root


class FakeClient:
    def __init__(self, cfg, log, reply, catalogue=CATALOGUE, gate=None):
        self.cfg, self.log, self.reply = cfg, log, reply
        self.catalogue, self.gate = catalogue, gate

    def call(self, tool, args, *, timeout_s, workflow):
        self.log.append((tool, args, timeout_s, self.cfg.command))
        if tool == "list_analyses":
            return {"status": "success", "files": [], "message": "",
                    "metadata": {"analyses": self.catalogue}}
        if self.gate is not None:
            self.gate.wait(5)
        reply = self.reply(args) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.log.append(("close",))


def commit_in(root) -> str:
    """One more commit in the git checkout `root`; its 12-char hash."""
    (Path(root) / "analysis_mcp_server" / "extra.py").write_text(
        f"{os.urandom(4).hex()}\n")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a],
                                    check=True, capture_output=True,
                                    text=True)
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@example.org", "commit",
        "-q", "-m", "another")
    return run("rev-parse", "--short=12", "HEAD").stdout.strip()


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.fork = git_repo(self.tmp / "fork", "analysis_mcp_server/__main__.py")
        (self.tmp / "musings" / "SimJob" / "MDC2025ay").mkdir(parents=True)
        patcher = mock.patch.object(ak, "MUSINGS_ROOT", self.tmp / "musings")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = []
        self.inputs = []
        for name in ("sim.t.TargetStops.c.0.art", "sim.t.TargetStops.c.1.art"):
            p = self.tmp / "in" / name
            p.parent.mkdir(exist_ok=True)
            p.write_text("")
            self.inputs.append({"name": name, "uri": p.as_uri(), "kind": "art"})

    def kit(self, reply=SUCCESS, catalogue=CATALOGUE, gate=None, **kw):
        factory = lambda cfg: FakeClient(cfg, self.log, reply, catalogue, gate)
        return ak.AnakitKit("camp", server=kw.pop("server", server()),
                            client_factory=factory,
                            grid_root=kw.pop("grid_root", self.tmp / "grid"),
                            fork=self.fork, **kw)

    def params(self, **over):
        p = {"musing": MUSING, "analysis": "muon_stop_rate",
             "upstream_eff": 0.01278168}
        p.update(over)
        return p

    def sdir(self, config="cfg1", step="stops"):
        return self.tmp / "grid" / config / "anakit" / step

    def record(self, step="stops"):
        return json.loads((self.sdir(step=step) / ak.RESULT_NAME).read_text())

    def run_call(self):
        return next(e for e in self.log if e[0] == "run_analysis")


class TestOpen(_Kit):
    def test_the_version_is_the_hand_constant(self):
        """The checkout commit is the step's build, never in the version:
        an unrelated commit never splits a board (2026-10-05)."""
        head = subprocess.run(["git", "-C", str(self.fork), "rev-parse",
                               "--short=12", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        kit = self.kit()
        self.assertEqual(kit.version, "anakit-adapter/2")
        self.assertEqual(kit.build, head)

    def test_a_fork_with_uncommitted_changes_is_refused(self):
        (self.fork / "analysis_mcp_server" / "__main__.py").write_text("changed\n")
        with self.assertRaises(KitError) as cm:
            self.kit()
        self.assertIn("uncommitted changes", str(cm.exception))

    def test_the_fork_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": ""}):
            with self.assertRaises(KitError) as cm:
                ak.fork_root()
        self.assertIn("AUTORESEARCH_ANAKIT is not set", str(cm.exception))
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": str(self.tmp)}):
            with self.assertRaises(KitError) as cm:
                ak.fork_root()
        self.assertIn("not an anakit checkout", str(cm.exception))
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": str(self.fork)}):
            self.assertEqual(ak.fork_root(), self.fork)

    def test_the_servers_timeouts_must_cover_anakits_own_limit(self):
        for bad, needle in ((server(run_analysis=3000), "at least"),
                            (ServerConfig("anakit", ("p",), (), {},
                                          {"start": 1.0}), "lack")):
            with self.assertRaises(KitError) as cm:
                self.kit(server=bad)
            self.assertIn(needle, str(cm.exception))

    def test_a_git_timeout_when_opening_is_a_kit_error(self):
        with mock.patch.object(
                ak.subprocess, "run",
                side_effect=subprocess.TimeoutExpired("git", 60)):
            with self.assertRaises(KitError) as cm:
                self.kit()
        self.assertIn("timed out", str(cm.exception))

    def test_a_missing_git_binary_when_opening_is_a_kit_error(self):
        with mock.patch.object(
                ak.subprocess, "run",
                side_effect=OSError("no such file or directory")):
            with self.assertRaises(KitError) as cm:
                self.kit()
        self.assertIn("could not run", str(cm.exception))

    def test_it_is_a_registered_engine_adapter(self):
        decl = kit_registry.KITS["anakit"]
        self.assertEqual((decl.step_kit, decl.check_kit, decl.uses_entries),
                         (True, False, False))
        self.assertEqual(sorted(decl.study_keys), ["musing"])
        self.assertEqual(decl.required_fixed, frozenset({"analysis"}))
        self.assertIs(ct.load_factory(decl), ak.AnakitKit)
        self.assertEqual(self.kit().tools,
                         frozenset({"submit", "status", "results"}))


class TestSubmit(_Kit):
    def test_submit_runs_the_analysis_and_writes_the_result(self):
        kit = self.kit()
        handle = kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertEqual(handle, "cfg1.stops")
        (list_call, run_call, close) = self.log
        self.assertEqual(list_call[0], "list_analyses")
        tool, args, timeout_s, command = run_call
        self.assertEqual(tool, "run_analysis")
        self.assertEqual(args, {
            "analysis": "muon_stop_rate", "output_dir": str(self.sdir()),
            "data_files": [str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"),
                           str(self.tmp / "in" / "sim.t.TargetStops.c.1.art")],
            "parameters": {"upstream_eff": 0.01278168},
            "timeout_s": ak.RUN_TIMEOUT_S})
        self.assertEqual(timeout_s, 3600)
        self.assertEqual(close, ("close",))
        rec = self.record()
        self.assertEqual((rec["handle"], rec["analysis"], rec["metrics"]),
                         ("cfg1.stops", "muon_stop_rate",
                          CATALOGUE["muon_stop_rate"]["metrics"]))
        self.assertEqual(rec["reply"], SUCCESS)

    def test_the_server_starts_on_the_studys_musing(self):
        self.kit().submit("cfg1.stops", self.params(), [], self.inputs, "w")
        command = self.run_call()[3]
        self.assertEqual(command[-2:], ("--musing", MUSING))
        self.assertNotIn("--work-area", command)

    def test_neither_musing_nor_analysis_is_sent_as_a_parameter(self):
        self.kit().submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertEqual(self.run_call()[1]["parameters"],
                         {"upstream_eff": 0.01278168})

    def test_the_result_records_the_musing(self):
        kit = self.kit()
        kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        rec = self.record()
        self.assertEqual(rec["musing"], MUSING)
        self.assertNotIn("work_area", rec)
        self.assertNotIn("code", rec)
        self.assertEqual(kit.results("cfg1.stops", "w").metadata["musing"],
                         MUSING)

    def test_a_root_file_analysis_gets_data_file(self):
        kit = self.kit()
        approx = self.params(analysis="approx_ce_sensitivity")
        del approx["upstream_eff"]
        kit.submit("cfg1.l1", {**approx, "stops_per_pot": 1.26e-3}, [],
                   self.inputs[:1], "w")
        args = self.run_call()[1]
        self.assertNotIn("data_files", args)
        self.assertEqual(args["data_file"],
                         str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"))
        with self.assertRaises(ValueError) as cm:
            kit.submit("cfg1.l2", approx, [], self.inputs, "w")
        self.assertIn("takes one ROOT file", str(cm.exception))

    def test_an_anakit_result_file_is_the_next_steps_input(self):
        """ce_edep's ntuple is sob's input: the engine hands one anakit
        step's result files to the next as its inputs."""
        nts = self.sdir(step="ce_edep") / "nts.x.root"

        def reply(args):
            out = Path(args["output_dir"])
            if args["analysis"] == "edep":
                (out / "nts.x.root").write_text("")
                return {"status": "success", "files": [str(out / "nts.x.root")],
                        "message": "edep", "metadata": {
                            m: 1.0 for m in CATALOGUE["edep"]["metrics"]}}
            return {"status": "success", "files": [], "message": "approx",
                    "metadata": {m: 1.0 for m in
                                 CATALOGUE["approx_ce_sensitivity"]["metrics"]}}

        kit = self.kit(reply=reply)
        kit.submit("cfg1.ce_edep", {"musing": MUSING, "analysis": "edep"}, [],
                   self.inputs, "w")
        files = list(kit.results("cfg1.ce_edep", "w").files)
        self.log.clear()
        kit.submit("cfg1.sob", {"musing": MUSING,
                                "analysis": "approx_ce_sensitivity",
                                "stops_per_pot": 1.26e-3}, [], files, "w")
        self.assertEqual(self.run_call()[1]["data_file"], str(nts.resolve()))

    def test_submit_refuses_what_it_cannot_run(self):
        kit = self.kit()
        cases = (
            (dict(params=self.params(musing="")), "'musing'"),
            (dict(params=self.params(analysis="")), "'analysis'"),
            (dict(inputs=[]), "no input files"),
            (dict(inputs=[{"name": "r", "uri": "root://x//f.art",
                           "kind": "art"}]), "file://"),
            (dict(files=[{"name": "geom", "uri": "file:///g", "kind": "geom"}]),
             "takes no step files"),
            (dict(params=self.params(analysis="nosuch")), "no analysis 'nosuch'"),
        )
        for over, needle in cases:
            args = {"params": self.params(), "files": [], "inputs": self.inputs}
            args.update(over)
            with self.subTest(needle=needle):
                with self.assertRaises(ValueError) as cm:
                    kit.submit("cfg1.stops", args["params"], args["files"],
                               args["inputs"], "w")
                self.assertIn(needle, str(cm.exception))

    def test_submit_empties_a_step_directory_left_by_an_earlier_run(self):
        self.sdir().mkdir(parents=True)
        (self.sdir() / "nts.stale.root").write_text("old\n")
        self.kit().submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertFalse((self.sdir() / "nts.stale.root").exists())
        self.assertTrue((self.sdir() / ak.RESULT_NAME).exists())

    def test_an_oserror_preparing_the_step_directory_names_the_path(self):
        # GRID_DATA_ROOT sits on a quota-limited volume (EDQUOT has
        # happened). The adapter lets the OSError escape, naming the path;
        # KitSet.get turns it into a KitError. A grid_root that is itself a
        # regular file makes sdir.mkdir(parents=True) fail with a real
        # OSError.
        grid_root = self.tmp / "not_a_dir"
        grid_root.write_text("x\n")
        kit = self.kit(grid_root=grid_root)
        with self.assertRaises(OSError) as cm:
            kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertIn(str(grid_root), str(cm.exception))

    def test_two_steps_at_once_use_two_servers_and_two_directories(self):
        gate = threading.Barrier(2)
        clients = []

        def reply(args):
            return {**SUCCESS, "message": args["output_dir"]}

        def factory(cfg):
            client = FakeClient(cfg, self.log, reply, CATALOGUE, gate)
            clients.append(client)
            return client

        kit = ak.AnakitKit("camp", server=server(), client_factory=factory,
                           grid_root=self.tmp / "grid", fork=self.fork)
        threads = [threading.Thread(
            target=kit.submit,
            args=(f"cfg1.{step}", self.params(), [], self.inputs, "w"))
            for step in ("stops", "flash")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        # Two SEPARATE clients (anakit runs one analysis at a time per
        # server), not just two closes of the same one.
        self.assertEqual(len(clients), 2)
        self.assertEqual(len({id(c) for c in clients}), 2)
        self.assertEqual(sum(1 for e in self.log if e == ("close",)), 2)
        for step in ("stops", "flash"):
            self.assertEqual(self.record(step)["reply"]["message"],
                             str(self.sdir(step=step)))

    def test_a_failed_call_leaves_no_result_and_closes_the_server(self):
        kit = self.kit(reply=KitError("anakit", "run_analysis", "timed out"))
        with self.assertRaises(KitError):
            kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertEqual(self.log[-1], ("close",))
        self.assertFalse((self.sdir() / ak.RESULT_NAME).exists())

    def test_a_catalogue_entry_missing_a_field_is_a_kit_error(self):
        for field in ("metrics", "input_kind", "takes_data_files"):
            entry = {k: v for k, v in CATALOGUE["muon_stop_rate"].items()
                     if k != field}
            kit = self.kit(catalogue={"muon_stop_rate": entry})
            with self.subTest(field=field):
                with self.assertRaises(KitError) as cm:
                    kit.submit("cfg1.stops", self.params(), [], self.inputs,
                               "w")
                self.assertIn(field, str(cm.exception))

    def test_an_unknown_input_kind_is_a_kit_error(self):
        entry = {**CATALOGUE["muon_stop_rate"], "input_kind": "art_file"}
        kit = self.kit(catalogue={"muon_stop_rate": entry})
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        msg = str(cm.exception)
        self.assertIn("art_file", msg)
        self.assertIn("muon_stop_rate", msg)
        self.assertIn("root_file", msg)

    def test_a_newer_fork_commit_does_not_refuse_submit(self):
        kit = self.kit()
        new = commit_in(self.fork)
        kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        rec = self.record()
        self.assertEqual(rec["build"], new)
        self.assertEqual(rec["version"], "anakit-adapter/2")

    def test_a_fork_left_dirty_after_open_refuses_submit(self):
        kit = self.kit()
        (self.fork / "analysis_mcp_server" / "__main__.py").write_text(
            "changed\n")
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertIn("uncommitted changes", str(cm.exception))


class TestStatusAndResults(_Kit):
    def submitted(self, reply=SUCCESS):
        kit = self.kit(reply=reply)
        kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        return kit

    def test_a_success_is_completed_with_its_metrics_and_files(self):
        nts = self.tmp / "nts.root"
        nts.write_text("")
        kit = self.submitted({**SUCCESS, "files": [str(nts)]})
        self.assertEqual(kit.status("cfg1.stops", "w").state, "completed")
        res = kit.results("cfg1.stops", "w")
        self.assertEqual(res.metrics, STOPS_METRICS)
        self.assertEqual(res.files, ({"name": "nts.root",
                                      "uri": nts.resolve().as_uri(),
                                      "kind": "root"},))
        self.assertEqual(res.metadata["log_path"], "/x.log")
        self.assertNotIn("stops_per_pot", res.metadata)
        self.assertEqual(res.metadata["musing"], MUSING)
        self.assertNotIn("work_area", res.metadata)
        self.assertNotIn("code", res.metadata)
        self.assertEqual(res.metadata["adapter"], kit.version)

    def test_a_newer_fork_commit_does_not_break_results(self):
        kit = self.submitted()
        old = self.record()["build"]
        commit_in(self.fork)
        res = kit.results("cfg1.stops", "w")
        self.assertEqual(res.metadata["build"], old)
        self.assertEqual(res.metadata["adapter"], "anakit-adapter/2")

    def test_an_error_reply_is_failed_with_anakits_message(self):
        kit = self.submitted({"status": "error", "files": [], "metadata": {},
                              "message": "muon_stop_rate: no prescale filter"})
        st = kit.status("cfg1.stops", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("no prescale filter", st.message)

    def test_a_missing_result_file_is_failed(self):
        st = self.kit().status("cfg1.stops", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn(ak.RESULT_NAME, st.message)

    def test_results_refuses_a_result_written_by_another_version(self):
        # A step directory can outlive the kit that wrote it (a resumed
        # campaign that re-opened on a newer adapter); adopting that stale
        # result would label a new measurement's row with the old one's
        # measure_sha.
        kit = self.submitted()
        path = self.sdir() / ak.RESULT_NAME
        rec = json.loads(path.read_text())
        rec["version"] = "anakit-adapter/1+anakit-deadbeefcafe"
        path.write_text(json.dumps(rec))
        with self.assertRaises(ContractError) as cm:
            kit.results("cfg1.stops", "w")
        self.assertIn("anakit-adapter/1+anakit-deadbeefcafe", str(cm.exception))
        self.assertIn(kit.version, str(cm.exception))

    def test_a_result_from_version_1_is_refused_by_version(self):
        """A version-1 record has work_area and code and no musing: results
        refuses it by its version, never with a KeyError on 'musing'."""
        kit = self.submitted()
        path = self.sdir() / ak.RESULT_NAME
        rec = json.loads(path.read_text())
        del rec["musing"]
        rec.update(version="anakit-adapter/1", work_area="/wa", code="9b197e2")
        path.write_text(json.dumps(rec))
        with self.assertRaises(ContractError) as cm:
            kit.results("cfg1.stops", "w")
        self.assertIn("rerun the step", str(cm.exception))

    def test_results_refuses_a_missing_or_non_number_metric(self):
        # The second case's needle names both the key AND its (non-number)
        # value, so it can only match if stops_per_pot is the offender.
        others = {k: v for k, v in STOPS_METRICS.items() if k != "stops_per_pot"}
        cases = ((others, "stops_per_pot"),
                 ({**others, "stops_per_pot": "1.26e-3"},
                  "'stops_per_pot': '1.26e-3'"))
        for meta, needle in cases:
            kit = self.submitted({**SUCCESS, "metadata": meta})
            with self.subTest(needle=needle):
                with self.assertRaises(ContractError) as cm:
                    kit.results("cfg1.stops", "w")
                self.assertIn(needle, str(cm.exception))


class TestStepProblems(_Kit):
    def study(self, fixed, metric="sob.stops_per_pot", params_from=None,
              others=(), files_from=("mubeam",), musing=MUSING):
        kits = {"anakit": {"musing": musing}} if musing is not None \
            else {"anakit": {}}
        step = Step("sob", "anakit", None, (), tuple(files_from), {},
                    dict(params_from or {}), fixed)
        study = types.SimpleNamespace(
            kits=kits, steps=(step,) + tuple(others),
            objectives=(types.SimpleNamespace(metric=metric),),
            extra_metrics=())
        return study, step

    GOOD = {"analysis": "muon_stop_rate", "upstream_eff": 0.01278168}

    def test_a_right_step_has_no_problems(self):
        study, step = self.study(self.GOOD)
        self.assertEqual(self.kit().step_problems(study, step), [])

    def test_each_wrong_thing_is_named(self):
        cases = (
            ({**self.GOOD, "analysis": "nosuch"}, "sob.stops_per_pot",
             "no analysis 'nosuch'"),
            ({**self.GOOD, "bogus": 1.0}, "sob.stops_per_pot",
             "does not take ['bogus']"),
            ({"analysis": "muon_stop_rate"}, "sob.stops_per_pot",
             "needs ['upstream_eff']"),
            (self.GOOD, "sob.sensitivity", "does not return ['sensitivity']"),
            ({**self.GOOD, "upstream_eff": -1.0}, "sob.stops_per_pot",
             "below the minimum"),
        )
        for fixed, metric, needle in cases:
            study, step = self.study(fixed, metric)
            with self.subTest(needle=needle):
                problems = self.kit().step_problems(study, step)
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_a_params_from_param_satisfies_a_required_parameter(self):
        study, step = self.study({"analysis": "muon_stop_rate"},
                                 params_from={"upstream_eff": "pre.eff"})
        self.assertEqual(self.kit().step_problems(study, step), [])

    def test_a_step_with_no_input_files_is_refused_at_launch(self):
        """anakit runs on input files; a step fed only numbers would pass
        launch and fail at submit, after its upstream steps had run."""
        study, step = self.study({"analysis": "approx_ce_sensitivity"},
                                 metric="sob.sensitivity",
                                 params_from={"stops_per_pot": "stops.stops_per_pot"},
                                 files_from=())
        problems = self.kit().step_problems(study, step)
        self.assertTrue(any("no files_from" in p for p in problems), problems)

    def test_a_params_from_param_the_analysis_does_not_take(self):
        study, step = self.study(self.GOOD,
                                 params_from={"bogus": "stops.rate"})
        problems = self.kit().step_problems(study, step)
        self.assertTrue(any("does not take ['bogus']" in p for p in problems),
                        problems)

    def test_a_metric_another_step_reads_must_be_returned(self):
        reader = Step("c", "anakit", None, (), (), {}, {"x": "sob.nope"},
                      {"analysis": "approx_ce_sensitivity"})
        study, step = self.study(self.GOOD, others=(reader,))
        problems = self.kit().step_problems(study, step)
        self.assertTrue(any("does not return ['nope']" in p for p in problems),
                        problems)

    def test_a_catalogue_entry_without_input_kind_is_named(self):
        entry = {k: v for k, v in CATALOGUE["muon_stop_rate"].items()
                 if k != "input_kind"}
        study, step = self.study(self.GOOD)
        problems = self.kit(catalogue={"muon_stop_rate": entry}
                            ).step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("input_kind", problems[0])

    def test_an_unknown_input_kind_is_named(self):
        entry = {**CATALOGUE["muon_stop_rate"], "input_kind": "art_file"}
        study, step = self.study(self.GOOD)
        problems = self.kit(catalogue={"muon_stop_rate": entry}
                            ).step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("art_file", problems[0])
        self.assertIn("muon_stop_rate", problems[0])
        self.assertIn("root_file", problems[0])

    def test_a_missing_musing_setting_is_named(self):
        study, step = self.study(self.GOOD, musing=None)
        problems = self.kit().step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("kits.anakit.musing is not set", problems[0])

    def test_an_unpublished_musing_is_named(self):
        study, step = self.study(self.GOOD, musing="SimJob MDC2099zz")
        problems = self.kit().step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not published", problems[0])
        self.assertIn(str(self.tmp / "musings" / "SimJob" / "MDC2099zz"),
                      problems[0])

    def test_a_musing_needs_a_name_and_a_version(self):
        for bad in ("MDC2025ay", "SimJob MDC2025ay extra", ""):
            study, step = self.study(self.GOOD, musing=bad)
            with self.subTest(musing=bad):
                problems = self.kit().step_problems(study, step)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(
                    "kits.anakit.musing is not set" if not bad
                    else "a Musing and a version", problems[0])

    def test_a_slash_musing_is_accepted(self):
        for musing in ("SimJob/MDC2025ay", "  SimJob   MDC2025ay "):
            study, step = self.study(self.GOOD, musing=musing)
            with self.subTest(musing=musing):
                self.assertEqual(self.kit().step_problems(study, step), [])

    def test_musing_parts_splits_as_anakit_does(self):
        self.assertEqual(ak.musing_parts("SimJob MDC2025ay"),
                         ("SimJob", "MDC2025ay"))
        self.assertEqual(ak.musing_parts("SimJob/MDC2025ay"),
                         ("SimJob", "MDC2025ay"))
        self.assertIsNone(ak.musing_parts("SimJob"))
        self.assertIsNone(ak.musing_parts("a b c"))

    def test_the_catalogue_is_asked_once_per_musing(self):
        kit = self.kit()
        for _ in range(3):
            kit.step_problems(*self.study(self.GOOD))
        self.assertEqual(sum(1 for e in self.log if e[0] == "list_analyses"), 1)
        command = next(e for e in self.log if e[0] == "list_analyses")[3]
        self.assertEqual(command[-2:], ("--musing", MUSING))

    def test_a_text_parameter_expanding_to_a_missing_path_is_named(self):
        # The '${ARTIFACT}/' token study.py's own step loader leaves raw in
        # Step.fixed; ARTIFACT_ROOT is patched to an empty temp dir so the
        # expansion is guaranteed not to exist, rather than trusting the
        # real filesystem under the real ARTIFACT_ROOT.
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp), \
             mock.patch.object(paths, "BACKING", None):
            study, step = self.study(
                {**self.GOOD, "prescale_filter": "${ARTIFACT}/t.tbl"})
            problems = self.kit().step_problems(study, step)
        expanded = str(self.tmp / "t.tbl")
        self.assertTrue(any(expanded in p for p in problems), problems)


class TestOverStdio(_Kit):
    """The real KitClient against tests/fakeanakit.py."""

    def test_submit_status_results_through_the_real_client(self):
        cfg = ServerConfig(name="anakit",
                           command=(sys.executable, str(ROOT / "tests" / "fakeanakit.py")),
                           env_passthrough=(), set_env={},
                           timeouts={"start": 60, "list_analyses": 30,
                                     "run_analysis": 3600})
        with mock.patch.object(paths, "GRAPH_DATA", self.tmp / "graph"):
            kit = ak.AnakitKit("camp", server=cfg, grid_root=self.tmp / "grid",
                               fork=self.fork)
            kit.submit("cfg1.stops", self.params(), [], self.inputs, "w")
        self.assertEqual(kit.status("cfg1.stops", "w").state, "completed")
        res = kit.results("cfg1.stops", "w")
        self.assertEqual(res.metrics, {
            "n_events": 1.0, "n_gen_events": 1.0, "prescale": 1.0,
            "stops_per_gen_event": 1.0, "stops_per_pot": 1.26e-3})
        self.assertEqual(res.metadata["musing"], MUSING)
        self.assertEqual(res.files[0]["name"], "nts.fake.root")


if __name__ == "__main__":
    unittest.main()
