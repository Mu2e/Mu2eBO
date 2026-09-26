import copy
import datetime
import errno
import json
import os
import sys
import tarfile
import tempfile
import types
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import scheduler  # noqa: E402
from adapters import prodtools as pk  # noqa: E402
from adapters import prodtools_entry as pe  # noqa: E402
from kits import KitError, KitTimeout, KitToolError  # noqa: E402
from study import Step  # noqa: E402

USER = "tester"


def utc(t):
    """A time as prodtools stamps its receipts (utils/run_receipt.py:_now)."""
    return datetime.datetime.fromtimestamp(
        t, datetime.timezone.utc).isoformat(timespec="seconds")


class FakeServer:
    def __init__(self, tools, handler):
        self.tools, self.handler = frozenset(tools), handler
        self.started, self.server_version = True, "p9"
        self.config = SimpleNamespace(timeouts=defaultdict(lambda: 1.0))
        self.calls = []

    def start(self):
        pass

    def close(self):
        pass

    def call(self, tool, args, *, timeout_s, workflow):
        self.calls.append((tool, dict(args)))
        return self.handler(tool, dict(args))


class FakeProdtools:
    """Both prodtools servers over one table of runs, keyed by run name.
    Replies are JSON-shaped: `outputs` is keyed by string indices."""

    def __init__(self, root, clock):
        self.root, self.runs, self.entries = Path(root), {}, {}
        self.clock = clock
        self.raise_after_submit = None
        self.autofinish = False
        self.write = FakeServer({"submit_once", "run_local"}, self._write)
        self.read = FakeServer({"run_status"}, self._read)

    def _write(self, tool, args):
        if tool == "cancel_run":
            self.runs[args["name"]]["state"] = "cancelled"
            return {"name": args["name"], "state": "cancelled"}
        (entry,) = json.loads(Path(args["json"]).read_text())
        name = f"cnf.{entry['owner']}.{args['desc']}.{args['dsconf']}.0"
        if name in self.runs:
            raise KitToolError("prodtools-write", tool,
                               f"{name} exists: a desc+dsconf pair is used "
                               f"once")
        self.entries[name] = entry
        run_dir = self.root / "runs" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        self.runs[name] = {
            "name": name, "created_utc": utc(self.clock()),
            "njobs": entry["njobs"], "cluster_id": 77,
            "state": "submitted" if tool == "submit_once" else "running",
            "jobid": "77.0@schedd.example",
            "outstage": str(self.root / "outstage"),
            "host": "node.example", "pid": 4242,
            "receipt": str(run_dir / "receipt.json")}
        if self.raise_after_submit is not None:
            exc, self.raise_after_submit = self.raise_after_submit, None
            raise exc
        return copy.deepcopy(self.runs[name])

    def _read(self, tool, args):
        run = self.runs.get(args["name"])
        if run is None:
            return {"error": {"kind": "not_found",
                              "message": f"no run {args['name']!r}",
                              "remedy": ""}}
        if self.autofinish and run["state"] in ("submitted", "running"):
            self.finish(args["name"], {i: 0 for i in range(run["njobs"])},
                        grid=run["state"] == "submitted")
        return copy.deepcopy(run)

    def finish(self, name, rcs, *, pattern=None, log=True, grid=True):
        """Every job ended with rcs[index]; each ok job wrote one output."""
        run = self.runs[name]
        entry = self.entries[name]
        glob_word = entry["fcl_overrides"].get(
            "outputs.TargetStopOutput.fileName", "")
        pattern = pattern or ("sim.x.TargetStops.y.{i:08d}.art"
                              if glob_word else "dts.x.CeEndpoint.y.{i:08d}.art")
        outputs = {}
        for i, rc in rcs.items():
            d = (Path(run["outstage"]) / "77" / f"{i:05d}" if grid
                 else Path(run["receipt"]).parent / f"job_{i:06d}")
            d.mkdir(parents=True, exist_ok=True)
            if log:
                (d / "job.log").write_text("ok\n")
            if rc == 0:
                out = d / pattern.format(i=i)
                out.write_text("x")
                outputs[str(i)] = [str(out)]
        failed = [i for i, rc in rcs.items() if rc != 0]
        jobs = {"expected": len(rcs), "ok": len(outputs), "failed": failed,
                "unknown": []}
        if failed:
            jobs["exit_codes"] = {str(i): rcs[i] for i in failed}
        run.update(state="short" if failed else "done", jobs=jobs,
                   outputs=outputs)


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.clock = [1000.0]
        self.fake = FakeProdtools(self.tmp / "prodtools",
                                  lambda: self.clock[0])
        patch = mock.patch.object(pe, "USER", USER)
        patch.start()
        self.addCleanup(patch.stop)
        code = self.tmp / "src" / "Code"
        code.mkdir(parents=True)
        (code / "setup.sh").write_text("echo setup\n")
        self.base = self.tmp / "Code_base.tar.bz2"
        with tarfile.open(self.base, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text("// geom\n")

    def kit(self, executor="grid", cancel=False, parallel=None):
        if cancel:
            self.fake.write.tools = self.fake.write.tools | {"cancel_run"}
        return pk.ProdtoolsKit(
            "camp", executor=executor, parallel=parallel,
            clients={"write": self.fake.write, "read": self.fake.read},
            clock=lambda: self.clock[0], pause=lambda s: None,
            grid_root=self.tmp / "grid", pnfs_root=self.tmp / "pnfs",
            submit_lock=self.tmp / "submit.lock")

    def params(self, step="mubeam", **over):
        entry = json.loads((ROOT / "stage_entries" / f"{step}.json")
                           .read_text())
        p = {"entry": entry, "code_tarball": str(self.base),
             "fatal_log_codes": ["GeomSolids1001"], "njobs": 2,
             "events_per_job": 200, "memory_mb": 2000, "quorum": 0.5}
        p.update(over)
        return p

    def files(self):
        return [{"name": "geom", "uri": self.geom.as_uri(), "kind": "geom"}]

    def submit(self, kit, name="cfg1.mubeam", step="mubeam", inputs=(),
               **over):
        return kit.submit(name, self.params(step, **over), self.files(),
                          list(inputs), "camp/cfg1/mubeam")

    def run_name(self, desc="Run1A_MuBeam_cfg1"):
        return f"cnf.{USER}.{desc}.Run1Bak_cfg1.0"

    def record_path(self, step="mubeam"):
        return self.tmp / "grid" / "cfg1" / "prodtools" / step / "record.json"

    def record(self, step="mubeam"):
        return json.loads(self.record_path(step).read_text())

    def set_record(self, step="mubeam", **fields):
        rec = self.record(step)
        rec.update(fields)
        self.record_path(step).write_text(json.dumps(rec))


class TestSubmit(_Kit):
    def test_a_first_submit_renders_the_entry_and_records_the_run(self):
        self.assertEqual(self.submit(self.kit()), "cfg1.mubeam")
        entry = self.fake.entries[self.run_name()]
        self.assertEqual((entry["njobs"], entry["events"], entry["memory"]),
                         (2, 200, "2000MB"))
        self.assertEqual(
            entry["fcl_overrides"]["services.GeometryService.inputFile"],
            "autoresearch_cfg1_geom.txt")
        with tarfile.open(entry["code"]) as tf:
            names = set(tf.getnames())
        self.assertTrue({"Code/autoresearch_cfg1_geom.txt",
                         "Code/sim_kept_products_extras.fcl",
                         "Code/setup_post.sh"} <= names)
        rec = self.record()
        self.assertEqual((rec["state"], rec["run_name"], rec["executor"]),
                         ("submitted", self.run_name(), "grid"))
        self.assertTrue((self.tmp / "submit.lock").exists())
        self.assertEqual([c[0] for c in self.fake.write.calls],
                         ["submit_once"])

    def test_the_same_params_again_do_not_submit_twice(self):
        kit = self.kit()
        self.submit(kit)
        self.submit(kit)
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_different_params_are_refused(self):
        kit = self.kit()
        self.submit(kit)
        with self.assertRaises(ValueError) as cm:
            self.submit(kit, njobs=3)
        self.assertIn("other params", str(cm.exception))

    def test_a_crash_after_the_receipt_is_adopted(self):
        self.submit(self.kit())
        self.set_record(state="submitting")
        self.submit(self.kit())
        self.assertEqual(len(self.fake.write.calls), 1)
        self.assertEqual(self.record()["state"], "submitted")

    def test_a_crash_before_the_receipt_submits_again(self):
        self.submit(self.kit())
        del self.fake.runs[self.run_name()]
        self.set_record(state="submitting")
        self.submit(self.kit())
        self.assertEqual(len(self.fake.write.calls), 2)

    def test_a_receipt_stuck_in_submitting_fails_loudly(self):
        self.submit(self.kit())
        self.fake.runs[self.run_name()]["state"] = "submitting"
        self.set_record(state="submitting")
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assertIn("jobsub_q", str(cm.exception))

    def an_older_run(self):
        """A run of this step's name that prodtools created a minute
        before this step's submit: a config name used before."""
        older = utc(self.clock[0] - 60)
        self.fake.runs[self.run_name()] = {
            "name": self.run_name(), "created_utc": older, "state": "done",
            "njobs": 2}
        return older

    def assert_refused_as_older(self, cm, older, ours):
        msg = str(cm.exception)
        for needle in (self.run_name(), older, ours, "used before",
                       "new config name"):
            self.assertIn(needle, msg)

    def test_an_older_run_refusing_the_submit_is_not_adopted(self):
        older = self.an_older_run()
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assertNotIsInstance(cm.exception, KitToolError)
        self.assert_refused_as_older(cm, older, utc(self.clock[0]))
        self.assertEqual(self.record()["submitting_utc"], utc(self.clock[0]))
        self.assertEqual(self.record()["state"], "submitting")
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_a_rerun_does_not_adopt_an_older_run(self):
        self.submit(self.kit())
        ours = self.record()["submitting_utc"]
        older = self.an_older_run()
        self.set_record(state="submitting")
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assert_refused_as_older(cm, older, ours)
        self.assertEqual(self.record()["state"], "submitting")
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_a_tool_error_after_our_run_was_created_is_adopted(self):
        self.fake.raise_after_submit = KitToolError(
            "prodtools-write", "submit_once", "jobsub_submit: rc=1")
        self.clock[0] += 0.5    # prodtools stamps a moment after we do
        self.submit(self.kit())
        self.assertEqual(self.record()["state"], "submitted")

    def test_a_run_status_without_created_utc_is_not_adopted(self):
        self.fake.raise_after_submit = KitTimeout("prodtools", "submit_once",
                                                  "timed out")
        read = self.fake.read.handler
        self.fake.read.handler = lambda tool, args: {
            k: v for k, v in read(tool, args).items() if k != "created_utc"}
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assertIn("created_utc", str(cm.exception))
        self.assertEqual(self.record()["state"], "submitting")

    def test_a_record_without_submitting_utc_is_not_adopted(self):
        self.submit(self.kit())
        rec = self.record()
        del rec["submitting_utc"]
        rec["state"] = "submitting"
        self.record_path().write_text(json.dumps(rec))
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assertIn("submitting_utc", str(cm.exception))

    def test_a_timeout_whose_run_exists_is_adopted(self):
        self.fake.raise_after_submit = KitTimeout("prodtools", "submit_once",
                                                  "timed out")
        self.submit(self.kit())
        self.assertEqual(self.record()["state"], "submitted")

    def test_a_timeout_with_no_run_raises_and_stays_submitting(self):
        def boom(tool, args):
            raise KitTimeout("prodtools", tool, "timed out")
        self.fake.write.handler = boom
        with self.assertRaises(KitTimeout):
            self.submit(self.kit())
        self.assertEqual(self.record()["state"], "submitting")

    def test_local_runs_run_local_with_parallel(self):
        self.submit(self.kit(executor="local", parallel=3))
        tool, args = self.fake.write.calls[0]
        self.assertEqual((tool, args["parallel"]), ("run_local", 3))
        self.assertFalse((self.tmp / "submit.lock").exists())

    def upstream(self, n=2):
        d = self.tmp / "up"
        d.mkdir(exist_ok=True)
        refs = []
        for i in range(n):
            f = d / f"sim.x.TargetStops.y.{i}.art"
            f.write_text(str(i))
            refs.append({"name": f.name, "uri": f.as_uri(), "kind": "art"})
        return refs

    def test_inputs_are_hard_linked_into_the_staged_dir(self):
        refs = self.upstream()
        self.submit(self.kit(), name="cfg1.mustops_ce", step="mustops_ce",
                    inputs=refs)
        entry = self.fake.entries[self.run_name("Run1A_CeEndpoint_cfg1")]
        staged = self.tmp / "pnfs" / "cfg1" / "staged" / "mustops_ce"
        self.assertEqual(entry["inloc"], f"dir:{staged}")
        self.assertEqual(entry["input_data"], {r["name"]: 1 for r in refs})
        self.assertEqual(os.stat(staged / refs[0]["name"]).st_ino,
                         os.stat(self.tmp / "up" / refs[0]["name"]).st_ino)

    def test_grid_staging_never_copies(self):
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev), \
                self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=self.upstream())
        self.assertIn("staging", str(cm.exception))

    def test_local_staging_copies_across_devices(self):
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev):
            self.submit(self.kit(executor="local"), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=self.upstream(1))
        staged = (self.tmp / "grid" / "cfg1" / "prodtools" / "mustops_ce"
                  / "staged")
        self.assertTrue((staged / "sim.x.TargetStops.y.0.art").exists())

    def test_a_non_file_input_is_refused(self):
        ref = {"name": "a.art", "uri": "root://fndca/pnfs/a.art",
               "kind": "art"}
        with self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=[ref])
        self.assertIn("file://", str(cm.exception))

    def test_config_names_with_other_characters_are_refused(self):
        for name, needle in (("cfg-1.mubeam", "'-'"),
                             ("cfg.1.mubeam", "'.'"),
                             ("mubeam", "<config>.<step>")):
            with self.subTest(name=name), \
                    self.assertRaises(ValueError) as cm:
                self.kit().submit(name, self.params(), self.files(), [], "w")
            self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.fake.write.calls, [])

    def test_unknown_params_are_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), bogus=1)
        self.assertIn("bogus", str(cm.exception))

    def test_a_template_naming_geom_without_a_geom_file_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.kit().submit("cfg1.mubeam", self.params(), [], [], "w")
        self.assertIn("{geom}", str(cm.exception))


class TestStatus(_Kit):
    def submitted(self, executor="grid", **over):
        kit = self.kit(executor=executor)
        self.submit(kit, **over)
        return kit, self.run_name()

    def state(self, kit):
        return kit.status("cfg1.mubeam", "w")

    def test_running_is_working(self):
        kit, name = self.submitted()
        self.fake.runs[name]["state"] = "running"
        self.assertEqual(self.state(kit).state, "working")

    def test_unknown_is_working_until_six_hours_then_failed(self):
        kit, name = self.submitted()
        self.fake.runs[name].update(state="unknown", note="schedd away")
        self.assertEqual(self.state(kit).state, "working")
        self.clock[0] += 6 * 3600
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("6 h", s.message)

    def test_failed_carries_the_prodtools_error(self):
        kit, name = self.submitted()
        self.fake.runs[name].update(state="failed", error="json2jobdef died")
        s = self.state(kit)
        self.assertEqual((s.state, "json2jobdef died" in s.message),
                         ("failed", True))

    def test_done_is_completed_and_results_carry_files_and_metadata(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        self.assertEqual(self.state(kit).state, "completed")
        res = kit.results("cfg1.mubeam", "w")
        self.assertEqual(res.metrics, {"njobs": 2.0, "njobs_ok": 2.0})
        self.assertEqual(len(res.files), 2)
        self.assertTrue(res.files[0]["uri"].startswith("file://"))
        self.assertEqual(res.files[0]["kind"], "art")
        md = res.metadata
        self.assertEqual((md["events_per_job"], md["executor"], md["jobid"],
                          md["prodtools_version"]),
                         (200, "grid", "77.0@schedd.example", "p9"))

    def test_below_quorum_fails(self):
        kit, name = self.submitted(quorum=0.8)
        self.fake.finish(name, {0: 0, 1: 1})
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("1/2 jobs ok, below quorum 0.8", s.message)

    def test_zero_ok_fails_even_at_a_low_quorum(self):
        kit, name = self.submitted(quorum=0.01)
        self.fake.finish(name, {0: 1, 1: 1})
        self.assertEqual(self.state(kit).state, "failed")

    def test_missing_outputs_wait_for_stage_out_then_fail(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        Path(self.fake.runs[name]["outputs"]["1"][0]).unlink()
        s = self.state(kit)
        self.assertEqual(s.state, "working")
        self.assertIn("waiting for stage-out", s.message)
        self.clock[0] += 30 * 60
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("still missing", s.message)

    def test_a_fatal_log_code_fails_the_step(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        log = Path(self.fake.runs[name]["outputs"]["0"][0]).parent / "job.log"
        log.write_text("... GeomSolids1001 ...\n")
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("GeomSolids1001", s.message)

    def test_a_successful_job_without_a_log_fails_the_step(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0}, log=False)
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("no .log", s.message)

    def test_no_output_matching_the_glob_fails(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0}, pattern="dts.x.Other.y.{i}.art")
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("matches", s.message)

    def test_the_verdict_is_reused(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        self.state(kit)
        calls = len(self.fake.read.calls)
        self.assertEqual(self.state(kit).state, "completed")
        self.assertEqual(len(self.fake.read.calls), calls)

    def test_local_logs_are_read_from_the_job_dirs(self):
        kit, name = self.submitted(executor="local")
        self.fake.finish(name, {0: 0, 1: 0}, grid=False)
        log = Path(self.fake.runs[name]["outputs"]["1"][0]).parent / "job.log"
        log.write_text("GeomSolids1001\n")
        self.assertEqual(self.state(kit).state, "failed")

    def test_an_error_reply_other_than_not_found_is_raised_after_retries(self):
        kit, _ = self.submitted()
        self.fake.read.handler = lambda tool, args: {
            "error": {"kind": "auth_expired", "message": "token expired",
                      "remedy": "renew"}}
        with self.assertRaises(KitToolError) as cm:
            self.state(kit)
        self.assertIn("auth_expired", str(cm.exception))
        self.assertEqual(len(self.fake.read.calls), 3)
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_results_before_completed_are_refused(self):
        kit, _ = self.submitted()
        with self.assertRaises(KitError):
            kit.results("cfg1.mubeam", "w")


class TestCancelAndLaunch(_Kit):
    def test_cancel_is_offered_only_with_cancel_run(self):
        self.assertNotIn("cancel", self.kit().tools)
        self.assertIn("cancel", self.kit(cancel=True).tools)

    def test_cancel_calls_cancel_run_once(self):
        kit = self.kit(cancel=True)
        self.submit(kit)
        self.assertEqual(kit.cancel("cfg1.mubeam", "w"), "cancelled")
        self.assertEqual([c[0] for c in self.fake.write.calls],
                         ["submit_once", "cancel_run"])
        self.assertEqual(kit.status("cfg1.mubeam", "w").state, "cancelled")

    def test_a_write_server_without_the_executors_tool_is_refused(self):
        self.fake.write.tools = frozenset({"run_local"})
        with self.assertRaises(KitError) as cm:
            self.kit().tools
        self.assertIn("submit_once", str(cm.exception))
        self.fake.write.tools = frozenset({"submit_once"})
        with self.assertRaises(KitError) as cm:
            self.kit(executor="local").tools
        self.assertIn("run_local", str(cm.exception))

    def test_describe_and_version(self):
        kit = self.kit()
        self.assertIn("quorum", kit.describe().params)
        self.assertEqual(kit.describe().metrics, ("njobs", "njobs_ok"))
        self.assertEqual(kit.version, "prodtools-adapter/1")


class TestWithRunSteps(_Kit):
    def test_mubeam_then_mustops_ce_stages_the_mubeam_outputs(self):
        self.fake.autofinish = True
        entries = {s: json.loads((ROOT / "stage_entries" / f"{s}.json")
                                 .read_text())
                   for s in ("mubeam", "mustops_ce")}
        settings = {"code_tarball": str(self.base),
                    "fatal_log_codes": ["GeomSolids1001"]}
        fixed = {"njobs": 2, "events_per_job": 200, "memory_mb": 2000,
                 "quorum": 1.0}
        study = types.SimpleNamespace(
            steps=(Step("mubeam", "prodtools", "mubeam", ("geom",), (), {},
                        dict(fixed)),
                   Step("mustops_ce", "prodtools", "mustops_ce", ("geom",),
                        ("mubeam",), {}, dict(fixed))),
            kits={"prodtools": settings},
            entry_template=lambda step: copy.deepcopy(entries[step]))

        class Kits:
            def __init__(self, kit):
                self.kit = kit

            def get(self, name):
                return self.kit

        out = scheduler.run_steps(
            study, config="cfg1", state_dir=self.tmp / "state", env={},
            files={"geom": self.files()[0]}, kits=Kits(self.kit()),
            workflow=lambda s: f"camp/cfg1/{s}", sleep=lambda s: None,
            log=lambda m: None)
        self.assertTrue(all(o.ok for o in out.values()),
                        {k: o.message for k, o in out.items()})
        ce = self.fake.entries[self.run_name("Run1A_CeEndpoint_cfg1")]
        mubeam_files = sorted(Path(p).name for p in sum(
            self.fake.runs[self.run_name()]["outputs"].values(), []))
        self.assertEqual(sorted(ce["input_data"]), mubeam_files)


class TestRegistration(unittest.TestCase):
    def test_prodtools_opens_as_the_adapter(self):
        kit = ct.open_kit("prodtools", "camp", executor="local", parallel=2)
        self.assertIsInstance(kit, pk.ProdtoolsKit)
        self.assertEqual((kit.executor, kit.parallel), ("local", 2))

    def test_prodtools_is_an_engine_and_a_pipeline_kit(self):
        d = kit_registry.KITS["prodtools"]
        self.assertTrue(d.engine and d.pipeline)


if __name__ == "__main__":
    unittest.main()
