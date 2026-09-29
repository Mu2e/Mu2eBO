"""core/adapters/offline_preflight.py: the geometry pre-check as a contract
kit (Phase C2a). The check's runner (preflight_checks.run_preflight's
`runner`, run_check by default) is replaced by a fake returning recorded
output; the unpack cache, the workdir and the verdict are real."""
import json
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402
from adapters import offline_preflight as op  # noqa: E402
from adapters import preflight_checks as pc  # noqa: E402
from study_graph import build_study_graph  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES, write_study  # noqa: E402
from tests.preflight_logs import (CLEAN_LOG, FATAL_LOG, GEOM,  # noqa: E402
                                  NO_MU2E_LOG, gdml_matching)


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.base = self.tarball(self.tmp / "Code_base.tar.bz2")
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text(GEOM)
        self.runs = []

    def tarball(self, path, *, with_setup=True):
        code = self.tmp / "src" / path.name / "Code"
        code.mkdir(parents=True)
        (code / ("setup.sh" if with_setup else "README")).write_text("x\n")
        with tarfile.open(path, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        return path

    def fake(self, out, rc, *, gdml_text=None, timed_out=False):
        """A run_check stand-in: records its call, optionally writes the
        GDML dump G4 would have written, returns the recorded output."""
        def run(code_dir, workdir, fcl, *, timeout_s, label, log=None):
            self.runs.append((Path(code_dir), Path(workdir), fcl, timeout_s,
                              label))
            if gdml_text is not None:
                (Path(workdir) / pc.PREFLIGHT_GDML_NAME).write_text(gdml_text)
            return out, rc, timed_out
        return run

    def kit(self, runner=None, **kw):
        return op.OfflinePreflightKit(
            "camp", executor="local", grid_root=self.tmp / "grid",
            runner=runner or self.fake(CLEAN_LOG, 0), **kw)

    def params(self, **over):
        p = {"code_tarball": str(self.base), "dumps_gdml": False,
             "verifies_foil_gdml": False, "checks_managed_overlap": True,
             "require_zero_overlaps": False}
        p.update(over)
        return p

    def files(self, uri=None):
        return [{"name": "geom", "uri": uri or self.geom.as_uri(),
                 "kind": "geom"}]

    def check(self, kit=None, name="cfg1.preflight", files=None, inputs=(),
              **over):
        return (kit or self.kit()).check(
            name, self.params(**over), self.files() if files is None else files,
            list(inputs), "camp/cfg1/preflight")

    def workdir(self, config="cfg1"):
        return self.tmp / "grid" / config / "preflight"


class TestCheck(_Kit):
    def test_a_passing_geometry_runs_from_the_unpacked_tarball(self):
        ok, message = self.check()
        self.assertTrue(ok, message)
        self.assertTrue(message.startswith("pass: init=True"), message)
        ((code_dir, workdir, fcl, timeout_s, label),) = self.runs
        self.assertEqual(code_dir.parent, self.tmp / "grid" / "_code")
        self.assertTrue((code_dir / "Code" / "setup.sh").is_file())
        self.assertEqual((workdir, fcl, timeout_s),
                         (self.workdir(), "surfacecheck.fcl", pc.TIMEOUT_S))
        self.assertIn("cfg1", label)

    def test_the_message_carries_the_verdicts_notes(self):
        ok, message = self.check()
        self.assertTrue(ok, message)
        first, *notes = message.split("\n")
        self.assertTrue(first.startswith("pass: init=True"), first)
        self.assertIn("  return code: 0  timed_out=False", notes)
        self.assertTrue(any(n.startswith("  surface-check total_hits=")
                            for n in notes), notes)

    def test_the_timeout_is_the_kits(self):
        self.check(self.kit(timeout_s=7))
        self.assertEqual(self.runs[0][3], 7)

    def test_without_a_runner_it_runs_run_check(self):
        """runner=None means preflight_checks.run_check, looked up when the
        check runs."""
        kit = op.OfflinePreflightKit("camp", executor="local",
                                     grid_root=self.tmp / "grid")
        with mock.patch.object(pc, "run_check", self.fake(CLEAN_LOG, 0)):
            ok, message = self.check(kit)
        self.assertTrue(ok, message)
        self.assertEqual(len(self.runs), 1)

    def test_the_workdir_holds_the_geometry_the_check_files_and_the_log(self):
        stale = self.workdir() / "left_over.txt"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")
        self.check()
        self.assertEqual(sorted(p.name for p in self.workdir().iterdir()),
                         ["autoresearch_cfg1_geom.txt", "preflight.log",
                          "surfacecheck.fcl",
                          "surfacecheck_autoresearch_cfg1_geom.txt"])
        self.assertEqual(
            (self.workdir() / "autoresearch_cfg1_geom.txt").read_text(), GEOM)
        self.assertEqual((self.workdir() / "preflight.log").read_text(),
                         CLEAN_LOG)

    def test_a_fatal_abort_fails_with_the_verdict_code(self):
        ok, message = self.check(self.kit(self.fake(FATAL_LOG, 134)))
        self.assertFalse(ok)
        self.assertTrue(message.startswith("fail_managed: fatal G4/art abort:"),
                        message)

    def test_ambiguous_fails_and_carries_the_log_tail(self):
        ok, message = self.check(self.kit(self.fake(NO_MU2E_LOG, 127)))
        self.assertFalse(ok)
        self.assertTrue(message.startswith("ambiguous: rc=127"), message)
        self.assertIn("mu2e: command not found", message)

    def test_the_as_built_gdml_is_verified_and_kept(self):
        ok, message = self.check(
            self.kit(self.fake(CLEAN_LOG, 0, gdml_text=gdml_matching(GEOM))),
            dumps_gdml=True, verifies_foil_gdml=True)
        self.assertTrue(ok, message)
        self.assertTrue((self.workdir() / op.ASBUILT_NAME).is_file())
        self.assertFalse((self.workdir() / pc.PREFLIGHT_GDML_NAME).exists())
        self.assertIn("writeGDML",
                      (self.workdir() / "surfacecheck.fcl").read_text())

    def test_a_stale_gdml_in_the_workdir_is_not_read(self):
        """A rerun whose G4 run wrote no GDML must not verify against the
        last run's dump: the workdir is emptied first."""
        self.workdir().mkdir(parents=True)
        for name in (pc.PREFLIGHT_GDML_NAME, op.ASBUILT_NAME):
            (self.workdir() / name).write_text(gdml_matching(GEOM))
        ok, message = self.check(dumps_gdml=True, verifies_foil_gdml=True)
        self.assertFalse(ok)
        self.assertIn("not produced", message)
        self.assertFalse((self.workdir() / op.ASBUILT_NAME).exists())

    def test_two_checks_at_once_share_one_unpacked_tree(self):
        kit = self.kit()
        results, errors = [], []

        def check(config):
            try:
                results.append(self.check(kit, name=f"{config}.preflight"))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=check, args=(c,))
                   for c in ("cfgA", "cfgB")]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertTrue(all(ok for ok, _m in results), results)
        self.assertEqual(len(list((self.tmp / "grid" / "_code").iterdir())), 1)


class TestRefusals(_Kit):
    def assertRefused(self, *needles, **kw):
        with self.assertRaises(ValueError) as cm:
            self.check(**kw)
        for needle in needles:
            self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.runs, [])

    def test_a_config_name_prodtools_cannot_carry(self):
        self.assertRefused("'-'", "only letters, digits and _",
                           name="cfg-1.preflight")

    def test_a_name_that_is_not_config_dot_preflight(self):
        self.assertRefused("<config>.preflight", name="cfg1.mubeam")
        self.assertRefused("<config>.preflight", name="preflight")

    def test_a_geometry_that_is_not_a_local_file(self):
        self.assertRefused("file://",
                           files=self.files("root://fndca/pnfs/geom.txt"))

    def test_no_geometry_file(self):
        self.assertRefused("'geom'", files=[])

    def test_inputs(self):
        self.assertRefused("no inputs", inputs=[self.files()[0]])

    def test_an_unknown_or_missing_param(self):
        self.assertRefused("musing", musing="/x/setup.sh")
        with self.assertRaises(ValueError) as cm:
            self.kit().check("cfg1.preflight", {"code_tarball": str(self.base)},
                             self.files(), [], "w")
        self.assertIn("dumps_gdml", str(cm.exception))

    def test_a_flag_that_is_not_a_bool(self):
        self.assertRefused("dumps_gdml", "true or false", dumps_gdml="false")

    def test_a_missing_or_codeless_tarball_names_it(self):
        self.assertRefused("gone.tar.bz2",
                           code_tarball=str(self.tmp / "gone.tar.bz2"))
        bare = self.tarball(self.tmp / "Bare.tar.bz2", with_setup=False)
        self.assertRefused(str(bare), "Code/setup.sh", code_tarball=str(bare))


class TestPreCheckOSError(_Kit):
    """EDQUOT/ENOSPC in stage_workdir, a failed mkdtemp/rename in
    pe.unpacked, or a read of the geometry file all surface as a bare
    OSError from pc.run_preflight. node_preflight (graph/study_graph.py)
    only catches (KitError, ContractError, KeyError, ValueError), so an
    unwrapped OSError would crash the engine child instead of breaking the
    point (F2, 2026-09-26)."""

    def test_an_oserror_in_the_pre_check_is_rewrapped_as_a_valueerror(self):
        err = OSError(28, "No space left on device")
        with mock.patch.object(op.pc, "run_preflight", side_effect=err):
            with self.assertRaises(ValueError) as cm:
                self.check()
        msg = str(cm.exception)
        self.assertIn("cfg1", msg)
        self.assertIn("No space left on device", msg)
        self.assertIn(str(self.workdir()), msg)


class TestKitInterface(_Kit):
    def test_describe_tools_version_and_launch_attributes(self):
        kit = self.kit()
        self.assertEqual(kit.tools, frozenset({"check", "describe"}))
        self.assertEqual(kit.describe(),
                         ct.Describe(op.PARAMS, (), False))
        self.assertEqual(op.PARAMS,
                         ("code_tarball", "dumps_gdml", "verifies_foil_gdml",
                          "checks_managed_overlap", "require_zero_overlaps"))
        self.assertEqual(kit.version, "offline-preflight-adapter/1")
        self.assertEqual((op.OfflinePreflightKit.EXECUTORS,
                          op.OfflinePreflightKit.REQUIRES_KERBEROS,
                          op.OfflinePreflightKit.LAUNCH_STAGGER_S),
                         (("grid", "local"), False, 0))

    def test_an_unknown_executor_is_refused(self):
        with self.assertRaises(ValueError):
            op.OfflinePreflightKit("camp", executor="cloud")

    def test_it_opens_as_the_adapter(self):
        kit = ct.open_kit("offline_preflight", "camp", executor="local")
        self.assertIsInstance(kit, op.OfflinePreflightKit)
        d = kit_registry.KITS["offline_preflight"]
        self.assertTrue(d.check_kit)
        self.assertFalse(d.step_kit)


class TestInThePointGraph(_Kit):
    def test_a_failing_pre_check_marks_the_point_broken_and_submits_nothing(self):
        """The engine's node_preflight, unchanged, hands the kit the study's
        settings as params and turns its verdict into broken.txt."""
        doc = json.loads((ENGINE_STUDIES / "prodtools_smoke.json").read_text())
        doc["name"] = "pcgraph"
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_pcgraph.tsv"
        code = "${ARTIFACT}/Code_base.tar.bz2"
        doc["kits"]["prodtools"]["code_tarball"] = code
        doc["kits"]["offline_preflight"] = {
            "code_tarball": code, "dumps_gdml": False,
            "verifies_foil_gdml": False, "checks_managed_overlap": True,
            "require_zero_overlaps": True}
        doc["preflight"] = {"kit": "offline_preflight", "params": {},
                            "files": ["geom"]}
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp):
            study = st.load_study_file(write_study(doc, self.tmp / "studies"))
        kit = self.kit(self.fake(FATAL_LOG, 134))
        opened = []

        class Kits:
            def get(self, name):
                opened.append(name)
                if name != "offline_preflight":
                    raise AssertionError(f"kit {name!r} was opened")
                return kit

        state = self.tmp / "grid" / "pcg01" / "state"
        build_study_graph(study, config="pcg01", campaign="c", context={},
                          kits=Kits(), state_dir=state, board=None,
                          log=lambda m: None, executor="local").compile() \
            .invoke({"config_name": "pcg01", "x_point": []})
        self.assertTrue((state / "broken.txt").read_text().startswith(
            "preflight: fail_managed: fatal G4/art abort:"))
        verdict = json.loads((state / "preflight_verdict.json").read_text())
        self.assertFalse(verdict["ok"])
        self.assertEqual(opened, ["offline_preflight"])
        self.assertFalse((self.tmp / "grid" / "pcg01" / "prodtools").exists())


if __name__ == "__main__":
    unittest.main()
