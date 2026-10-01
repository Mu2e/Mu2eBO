"""core/adapters/anakit.py: anakit (M. MacKenzie's analysis MCP server, our
fork) as a contract kit (Phase C2b spec, section 3). Unit tests drive the
adapter with a fake client; one test drives it through the real KitClient
against tests/fakeanakit.py over stdio."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
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

MDC = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax"
CATALOGUE = {
    "ce_sensitivity": {
        "metrics": ["s_over_sqrt_b", "ce_abs_eff"],
        "parameters": {"input_correction": {"required": True},
                       "dio_table": {"required": True},
                       "dio_fraction": {"required": False}},
        "takes_data_files": True, "input_kind": "art_files"},
    "approx_ce_sensitivity": {
        "metrics": ["sensitivity"],
        "parameters": {"sig_eff": {"required": True}},
        "takes_data_files": False, "input_kind": "root_file"},
}
SUCCESS = {"status": "success", "files": [], "message": "ce_sensitivity ok",
           "metadata": {"s_over_sqrt_b": 4.15, "ce_abs_eff": 6.67e-4,
                        "analysis": "ce_sensitivity", "log_path": "/x.log"}}


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


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.fork = git_repo(self.tmp / "fork", "analysis_mcp_server/__main__.py")
        self.wa = self.tmp / "wa"
        git_repo(self.wa / "Mu2eOptAna", "src/EdepAna_module.cc")
        os.symlink(MDC, self.wa / "backing")
        self.log = []
        self.inputs = []
        for name in ("sim.t.TargetStops.c.0.art", "dts.t.CeEndpoint.c.0.art"):
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
        p = {"work_area": str(self.wa), "analysis": "ce_sensitivity",
             "input_correction": 0.01278168, "dio_table": "/t.tbl"}
        p.update(over)
        return p

    def sdir(self, config="cfg1", step="sob"):
        return self.tmp / "grid" / config / "anakit" / step


class TestOpen(_Kit):
    def test_the_version_names_the_forks_commit(self):
        head = subprocess.run(["git", "-C", str(self.fork), "rev-parse",
                               "--short=12", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        self.assertEqual(self.kit().version, f"anakit-adapter/1+anakit-{head}")

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
        self.assertEqual(sorted(decl.study_keys), ["work_area"])
        self.assertEqual(decl.required_fixed, frozenset({"analysis"}))
        self.assertIs(ct.load_factory(decl), ak.AnakitKit)
        self.assertEqual(self.kit().tools,
                         frozenset({"submit", "status", "results"}))


class TestSubmit(_Kit):
    def test_submit_runs_the_analysis_and_writes_the_result(self):
        kit = self.kit()
        handle = kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(handle, "cfg1.sob")
        (list_call, run_call, close) = self.log
        self.assertEqual(list_call[0], "list_analyses")
        tool, args, timeout_s, command = run_call
        self.assertEqual(tool, "run_analysis")
        self.assertEqual(args, {
            "analysis": "ce_sensitivity", "output_dir": str(self.sdir()),
            "data_files": [str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"),
                           str(self.tmp / "in" / "dts.t.CeEndpoint.c.0.art")],
            "parameters": {"input_correction": 0.01278168,
                           "dio_table": "/t.tbl"},
            "timeout_s": ak.RUN_TIMEOUT_S})
        self.assertEqual(timeout_s, 3600)
        self.assertEqual(command[-2:], ("--work-area", str(self.wa)))
        self.assertEqual(close, ("close",))
        rec = json.loads((self.sdir() / ak.RESULT_NAME).read_text())
        self.assertEqual((rec["handle"], rec["analysis"], rec["metrics"]),
                         ("cfg1.sob", "ce_sensitivity",
                          ["s_over_sqrt_b", "ce_abs_eff"]))
        self.assertEqual(rec["reply"], SUCCESS)

    def test_a_root_file_analysis_gets_data_file(self):
        kit = self.kit()
        kit.submit("cfg1.l1", self.params(analysis="approx_ce_sensitivity",
                                          input_correction=None) | {"sig_eff": 1e-4},
                   [], self.inputs[:1], "w")
        args = self.log[1][1]
        self.assertNotIn("data_files", args)
        self.assertEqual(args["data_file"],
                         str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"))
        with self.assertRaises(ValueError) as cm:
            kit.submit("cfg1.l2", self.params(analysis="approx_ce_sensitivity"),
                       [], self.inputs, "w")
        self.assertIn("takes one ROOT file", str(cm.exception))

    def test_submit_refuses_what_it_cannot_run(self):
        kit = self.kit()
        cases = (
            (dict(params=self.params(work_area="")), "'work_area'"),
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
                    kit.submit("cfg1.sob", args["params"], args["files"],
                               args["inputs"], "w")
                self.assertIn(needle, str(cm.exception))

    def test_submit_empties_a_step_directory_left_by_an_earlier_run(self):
        self.sdir().mkdir(parents=True)
        (self.sdir() / "nts.stale.root").write_text("old\n")
        self.kit().submit("cfg1.sob", self.params(), [], self.inputs, "w")
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
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
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
            for step in ("sob", "flash")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        # Two SEPARATE clients (anakit runs one analysis at a time per
        # server), not just two closes of the same one.
        self.assertEqual(len(clients), 2)
        self.assertEqual(len({id(c) for c in clients}), 2)
        self.assertEqual(sum(1 for e in self.log if e == ("close",)), 2)
        for step in ("sob", "flash"):
            rec = json.loads((self.sdir(step=step) / ak.RESULT_NAME).read_text())
            self.assertEqual(rec["reply"]["message"], str(self.sdir(step=step)))

    def test_a_failed_call_leaves_no_result_and_closes_the_server(self):
        kit = self.kit(reply=KitError("anakit", "run_analysis", "timed out"))
        with self.assertRaises(KitError):
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(self.log[-1], ("close",))
        self.assertFalse((self.sdir() / ak.RESULT_NAME).exists())

    def test_a_catalogue_entry_missing_metrics_is_a_kit_error(self):
        catalogue = {"ce_sensitivity": {k: v for k, v in
                                        CATALOGUE["ce_sensitivity"].items()
                                        if k != "metrics"}}
        kit = self.kit(catalogue=catalogue)
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertIn("metrics", str(cm.exception))

    def test_a_root_file_analysis_needs_no_mu2eoptana(self):
        shutil.rmtree(self.wa / "Mu2eOptAna")
        self.kit().submit("cfg1.l1", self.params(analysis="approx_ce_sensitivity",
                                                 input_correction=None)
                          | {"sig_eff": 1e-4}, [], self.inputs[:1], "w")
        rec = json.loads((self.sdir(step="l1") / ak.RESULT_NAME).read_text())
        self.assertIsNone(rec["code"])

    def test_an_art_analysis_records_its_code(self):
        self.kit().submit("cfg1.sob", self.params(), [], self.inputs, "w")
        want = subprocess.run(
            ["git", "-C", str(self.wa / "Mu2eOptAna"), "describe", "--always",
             "--dirty"], capture_output=True, text=True,
            check=True).stdout.strip()
        rec = json.loads((self.sdir() / ak.RESULT_NAME).read_text())
        self.assertEqual(rec["code"], want)

    def test_a_catalogue_entry_without_input_kind_is_a_kit_error(self):
        entry = {k: v for k, v in CATALOGUE["ce_sensitivity"].items()
                 if k != "input_kind"}
        kit = self.kit(catalogue={"ce_sensitivity": entry})
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertIn("input_kind", str(cm.exception))

    def test_an_unknown_input_kind_is_a_kit_error(self):
        entry = {**CATALOGUE["ce_sensitivity"], "input_kind": "art_file"}
        kit = self.kit(catalogue={"ce_sensitivity": entry})
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        msg = str(cm.exception)
        self.assertIn("art_file", msg)
        self.assertIn("ce_sensitivity", msg)
        self.assertIn("root_file", msg)

    def test_a_fork_commit_that_moved_since_open_refuses_submit(self):
        kit = self.kit()
        (self.fork / "analysis_mcp_server" / "extra.py").write_text("y\n")
        run = lambda *a: subprocess.run(["git", "-C", str(self.fork), *a],
                                        check=True, capture_output=True)
        run("add", ".")
        run("-c", "user.name=t", "-c", "user.email=t@example.org", "commit",
            "-q", "-m", "second")
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertIn("moved", str(cm.exception))

    def test_a_fork_left_dirty_after_open_refuses_submit(self):
        kit = self.kit()
        (self.fork / "analysis_mcp_server" / "__main__.py").write_text(
            "changed\n")
        with self.assertRaises(KitError) as cm:
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertIn("uncommitted changes", str(cm.exception))


class TestStatusAndResults(_Kit):
    def submitted(self, reply=SUCCESS):
        kit = self.kit(reply=reply)
        kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        return kit

    def test_a_success_is_completed_with_its_metrics_and_files(self):
        nts = self.tmp / "nts.root"
        nts.write_text("")
        kit = self.submitted({**SUCCESS, "files": [str(nts)]})
        self.assertEqual(kit.status("cfg1.sob", "w").state, "completed")
        res = kit.results("cfg1.sob", "w")
        self.assertEqual(res.metrics, {"s_over_sqrt_b": 4.15,
                                       "ce_abs_eff": 6.67e-4})
        self.assertEqual(res.files, ({"name": "nts.root",
                                      "uri": nts.resolve().as_uri(),
                                      "kind": "root"},))
        self.assertEqual(res.metadata["log_path"], "/x.log")
        self.assertNotIn("s_over_sqrt_b", res.metadata)
        self.assertEqual(res.metadata["work_area"], str(self.wa))
        self.assertTrue(res.metadata["code"])
        self.assertEqual(res.metadata["adapter"], kit.version)

    def test_an_error_reply_is_failed_with_anakits_message(self):
        kit = self.submitted({"status": "error", "files": [], "metadata": {},
                              "message": "ce_sensitivity: no signal window"})
        st = kit.status("cfg1.sob", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("no signal window", st.message)

    def test_a_missing_result_file_is_failed(self):
        st = self.kit().status("cfg1.sob", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn(ak.RESULT_NAME, st.message)

    def test_results_refuses_a_result_written_by_another_build(self):
        # A step directory can outlive the kit that wrote it (a resumed
        # campaign that re-opened on a newer anakit commit); adopting that
        # stale result would label a new build's row with the old one's
        # measure_sha.
        kit = self.submitted()
        path = self.sdir() / ak.RESULT_NAME
        rec = json.loads(path.read_text())
        rec["version"] = "anakit-adapter/1+anakit-deadbeefcafe"
        path.write_text(json.dumps(rec))
        with self.assertRaises(ContractError) as cm:
            kit.results("cfg1.sob", "w")
        self.assertIn("anakit-adapter/1+anakit-deadbeefcafe", str(cm.exception))
        self.assertIn(kit.version, str(cm.exception))

    def test_results_refuses_a_missing_or_non_number_metric(self):
        # The second case's needle names both the key AND its (non-number)
        # value, so it can only match if ce_abs_eff -- not s_over_sqrt_b,
        # which stays a valid number here -- is the actual offender.
        cases = (({"s_over_sqrt_b": 4.15}, "ce_abs_eff"),
                ({"s_over_sqrt_b": 4.15, "ce_abs_eff": "6.67e-4"},
                 "'ce_abs_eff': '6.67e-4'"))
        for meta, needle in cases:
            kit = self.submitted({**SUCCESS, "metadata": meta})
            with self.subTest(needle=needle):
                with self.assertRaises(ContractError) as cm:
                    kit.results("cfg1.sob", "w")
                self.assertIn(needle, str(cm.exception))


class TestStepProblems(_Kit):
    def tarball(self, backing):
        path = self.tmp / f"Code_{abs(hash(backing))}.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            d = tarfile.TarInfo("Code")
            d.type, d.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(d)
            link = tarfile.TarInfo("Code/backing")
            link.type, link.linkname = tarfile.SYMTYPE, backing
            tf.addfile(link)
        return path

    def study(self, fixed, tarball=None, metric="sob.s_over_sqrt_b"):
        kits = {"anakit": {"work_area": str(self.wa)}}
        if tarball is not None:
            kits["prodtools"] = {"code_tarball": str(tarball)}
        step = types.SimpleNamespace(step="sob", kit="anakit", params={},
                                     fixed=fixed)
        study = types.SimpleNamespace(
            kits=kits, steps=(step,),
            objectives=(types.SimpleNamespace(metric=metric),),
            extra_metrics=())
        return study, step

    GOOD = {"analysis": "ce_sensitivity", "input_correction": 0.01,
            "dio_table": "${ARTIFACT}/t.tbl"}

    def test_a_right_step_has_no_problems(self):
        study, step = self.study(self.GOOD, self.tarball(MDC))
        self.assertEqual(self.kit().step_problems(study, step), [])

    def test_each_wrong_thing_is_named(self):
        cases = (
            ({**self.GOOD, "analysis": "nosuch"}, None, "sob.s_over_sqrt_b",
             "no analysis 'nosuch'"),
            ({**self.GOOD, "bogus": 1.0}, None, "sob.s_over_sqrt_b",
             "does not take ['bogus']"),
            ({"analysis": "ce_sensitivity", "dio_table": "/t"}, None,
             "sob.s_over_sqrt_b", "needs ['input_correction']"),
            (self.GOOD, None, "sob.flash_edep_per_pot",
             "does not return ['flash_edep_per_pot']"),
            (self.GOOD, self.tarball("/cvmfs/x/Musings/SimJob/Run1Bap"),
             "sob.s_over_sqrt_b", "backed by"),
        )
        for fixed, tarball, metric, needle in cases:
            study, step = self.study(fixed, tarball, metric)
            with self.subTest(needle=needle):
                problems = self.kit().step_problems(study, step)
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_a_root_file_analysis_ignores_the_backing(self):
        fixed = {"analysis": "approx_ce_sensitivity", "sig_eff": 1e-4}
        study, step = self.study(
            fixed, self.tarball("/cvmfs/x/Musings/SimJob/Run1Bap"),
            "sob.sensitivity")
        self.assertEqual(self.kit().step_problems(study, step), [])

    def test_a_catalogue_entry_without_input_kind_is_named(self):
        entry = {k: v for k, v in CATALOGUE["ce_sensitivity"].items()
                 if k != "input_kind"}
        study, step = self.study(self.GOOD, self.tarball(MDC))
        problems = self.kit(catalogue={"ce_sensitivity": entry}
                            ).step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("input_kind", problems[0])

    def test_an_unknown_input_kind_is_named(self):
        entry = {**CATALOGUE["ce_sensitivity"], "input_kind": "art_file"}
        study, step = self.study(self.GOOD, self.tarball(MDC))
        problems = self.kit(catalogue={"ce_sensitivity": entry}
                            ).step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("art_file", problems[0])
        self.assertIn("ce_sensitivity", problems[0])
        self.assertIn("root_file", problems[0])

    def test_a_work_area_that_is_not_a_directory(self):
        study, step = self.study(self.GOOD)
        study.kits["anakit"]["work_area"] = str(self.tmp / "missing")
        problems = self.kit().step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a directory", problems[0])

    def test_the_catalogue_is_asked_once_per_work_area(self):
        kit = self.kit()
        for _ in range(3):
            kit.step_problems(*self.study(self.GOOD))
        self.assertEqual(sum(1 for e in self.log if e[0] == "list_analyses"), 1)

    def test_backing_problem_normalizes_both_links(self):
        self.assertIsNone(ak.backing_problem(self.wa, self.tarball(MDC + "/")))
        self.assertIn("no Code/backing",
                      ak.backing_problem(self.wa, self._no_backing()))

    # Catalogues enriched with the `minimum`/`maximum`/`kind` fields the real
    # catalogue carries (ParamSpec.describe in analysis-mcp-server's
    # tools/spec.py) but the module-level CATALOGUE fixture above does not,
    # so these two checks stay isolated to the tests that exercise them.
    NUMERIC_CATALOGUE = {
        "ce_sensitivity": {
            **CATALOGUE["ce_sensitivity"],
            "parameters": {
                **CATALOGUE["ce_sensitivity"]["parameters"],
                "input_correction": {"required": True, "kind": "number",
                                     "minimum": 0.0, "maximum": 1.0},
            },
        },
    }
    TEXT_CATALOGUE = {
        "ce_sensitivity": {
            **CATALOGUE["ce_sensitivity"],
            "parameters": {
                **CATALOGUE["ce_sensitivity"]["parameters"],
                "dio_table": {"required": True, "kind": "text"},
            },
        },
    }

    def test_a_numeric_parameter_outside_its_bounds_is_named(self):
        study, step = self.study({**self.GOOD, "input_correction": 5.0},
                                 self.tarball(MDC))
        problems = self.kit(catalogue=self.NUMERIC_CATALOGUE).step_problems(
            study, step)
        self.assertTrue(any("input_correction" in p and "5" in p and "1" in p
                            for p in problems), problems)

    def test_a_text_parameter_expanding_to_a_missing_path_is_named(self):
        # GOOD's dio_table is the '${ARTIFACT}/' token study.py's own step
        # loader leaves raw in Step.fixed; ARTIFACT_ROOT is patched to an
        # empty temp dir so the expansion is guaranteed not to exist, rather
        # than trusting the real filesystem under the real ARTIFACT_ROOT.
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp), \
             mock.patch.object(paths, "BACKING", None):
            study, step = self.study(self.GOOD, self.tarball(MDC))
            problems = self.kit(catalogue=self.TEXT_CATALOGUE).step_problems(
                study, step)
        expanded = str(self.tmp / "t.tbl")
        self.assertTrue(any(expanded in p for p in problems), problems)

    def test_backing_problem_an_unreadable_link_is_named(self):
        # is_symlink() can pass and os.readlink() still fail (permissions, or
        # the link vanishing between the two calls); that OSError must become
        # a problem string, not an exception out of step_problems.
        with mock.patch.object(ak.os, "readlink",
                               side_effect=OSError("permission denied")):
            problem = ak.backing_problem(self.wa, self.tarball(MDC))
        self.assertIn(str(self.wa / "backing"), problem)
        self.assertIn("permission denied", problem)

    def _no_backing(self):
        path = self.tmp / "Code_empty.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            d = tarfile.TarInfo("Code")
            d.type, d.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(d)
        return path


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
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(kit.status("cfg1.sob", "w").state, "completed")
        res = kit.results("cfg1.sob", "w")
        self.assertEqual(res.metrics, {"s_over_sqrt_b": 4.0, "ce_abs_eff": 6.7e-4})
        self.assertEqual(res.metadata["work_area"], str(self.wa))
        self.assertEqual(res.files[0]["name"], "nts.fake.root")


if __name__ == "__main__":
    unittest.main()
