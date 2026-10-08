"""core/adapters/preflight_checks.py: the geometry pre-check's files, its
run, and the log -> verdict rules the offline_preflight kit runs on
(Phase C2a)."""
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
from adapters import preflight_checks as pc  # noqa: E402
from adapters import prodtools_entry as pe  # noqa: E402
from tests.preflight_logs import (ADVISORY_LOG, CLEAN_LOG, FATAL_LOG,  # noqa: E402
                                  GEOM, MANAGED_LOG, NO_MU2E_LOG,
                                  PRE_INIT_GEOM_LOG, gdml, gdml_matching)


class TestFatalAbortRegexes(unittest.TestCase):
    """Regression for wiki/incidents/preflight-past-init-false-pass.md
    (moved from tests/test_audit_fixes.py): a fatal GeomSolids0002 abort
    AFTER pre-geometry strings (BeginRun / GenParticle) was classified
    PASS because past_init short-circuited the geom-fail check."""

    def test_fatal_abort_matches(self):
        self.assertTrue(pc.G4_FATAL_RX.search(FATAL_LOG))

    def test_advisory_overlap_does_not_match_fatal(self):
        self.assertFalse(pc.G4_FATAL_RX.search(ADVISORY_LOG))

    def test_geom_fail_rx_includes_geomsolids(self):
        self.assertTrue(pc.G4_GEOM_FAIL_RX.search(FATAL_LOG))

    def test_past_init_would_have_masked_it(self):
        # The fatal log carries a past_init string (BeginRun), which is why
        # the old classifier passed it. With every other gate off and rc=0,
        # only the fatal-abort rule stands between it and a PASS.
        self.assertIn("BeginRun", FATAL_LOG)
        v = pc.classify(FATAL_LOG, 0, False, geom_text=GEOM,
                        gdml_path="/nonexistent.gdml",
                        verifies_foil_gdml=False,
                        checks_managed_overlap=False,
                        require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))


class TestVerifyStoppingTargetGdml(unittest.TestCase):
    """As-built GDML geometry assertion (moved from
    tests/test_audit_fixes.py; prelaunch gate added 2026-06-13 after the
    foilsg uniform-hole incident)."""

    def _run(self, tubes, geom=None):
        with tempfile.NamedTemporaryFile("w", suffix=".gdml",
                                         delete=False) as f:
            f.write(gdml(tubes))
            path = f.name
        try:
            return pc.verify_stopping_target_gdml(path, geom or GEOM)
        finally:
            Path(path).unlink()

    def test_matching_geometry_passes(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_wrong_hole_radius_fails(self):
        # The uniform-hole incident shape: built rIn != geom holeRadii.
        errs = self._run([("Foil_00", 51.041, 100.0, 1.0, "mm"),
                          ("Foil_01", 51.041, 200.0, 0.5, "mm")])
        self.assertEqual(len(errs), 2)
        self.assertIn("Foil_00 rIn", errs[0])

    def test_foil_count_mismatch_fails(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm")])
        self.assertTrue(any("1 Foil_* tubes" in e and "2 foils" in e
                            for e in errs))

    def test_scalar_fallback_geom_uses_scalar(self):
        # Geom with no holeRadii vector: expected rIn is the scalar.
        geom = ("vector<double> stoppingTarget.radii = { 100.0 };\n"
                "double stoppingTarget.holeRadius = 21.5;\n")
        errs = self._run([("Foil_00", 21.5, 100.0, 0.0, "mm")], geom=geom)
        self.assertEqual(errs, [])

    def test_cm_units_scaled(self):
        errs = self._run([("Foil_00", 1.0, 10.0, 0.1, "cm"),
                          ("Foil_01", 0.0, 20.0, 0.05, "cm")])
        self.assertEqual(errs, [])

    def test_pointer_suffixed_names_parse_correctly(self):
        # G4's GDML writer appends 0x<addr> to every name. A greedy digit
        # match turns "Foil_020x55d..." into foil 20 -- the live-preflight
        # bug of 2026-06-13. Indices must parse exactly.
        errs = self._run([("Foil_000x55d1a2b3", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_010x55d1c4d5", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_missing_foil_indices_reported(self):
        # Spurious/scrambled indices must surface as "missing", not be
        # silently skipped by the per-index compare loop.
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_07", 0.0, 200.0, 0.5, "mm")])
        self.assertTrue(any("missing from GDML: [1]" in e for e in errs))

    def test_repeat_last_half_thickness(self):
        # StoppingTargetMaker repeats the final halfThickness entry.
        geom = ("vector<double> stoppingTarget.radii = { 100.0, 200.0 };\n"
                "vector<double> stoppingTarget.halfThicknesses = { 0.5 };\n"
                "vector<double> stoppingTarget.holeRadii = { 0.0, 0.0 };\n")
        errs = self._run([("Foil_00", 0.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 1.0, "mm")], geom=geom)
        self.assertEqual(errs, [])


STRICT = dict(verifies_foil_gdml=False, checks_managed_overlap=True,
              require_zero_overlaps=True)


class TestClassify(unittest.TestCase):
    """One recorded log per verdict, the rules in their order."""

    def classify(self, out, rc, *, timed_out=False, gdml_path=None,
                 geom_text=GEOM, **flags):
        return pc.classify(out, rc, timed_out, geom_text=geom_text,
                           gdml_path=gdml_path or "/nonexistent.gdml",
                           **{**STRICT, **flags})

    def gdml_file(self, text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / pc.PREFLIGHT_GDML_NAME
        path.write_text(text)
        return path

    def test_a_clean_run_passes_and_names_the_policy(self):
        v = self.classify(CLEAN_LOG, 0)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertEqual(v.reason, "init=True; no geom-fail signature and "
                                   "zero surface-check overlaps.")
        self.assertIn("surface-check total_hits=0 unique_volumes=0 "
                      "baseline=0 managed=0", v.notes)
        self.assertFalse(v.gdml_verified)

    def test_the_holeradii_printout_is_no_longer_required(self):
        # The retired canary failed any geometry naming holeRadii whose log
        # lacked "holeRadii vector active", whatever the other gates said.
        # With every other gate off, such a geometry now passes.
        self.assertIn("stoppingTarget.holeRadii", GEOM)
        self.assertNotIn("holeRadii vector active", CLEAN_LOG)
        v = self.classify(CLEAN_LOG, 0, checks_managed_overlap=False,
                          require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code, v.reason),
                         (True, "pass", "init=True; no geom-fail signature."))

    def test_a_fatal_abort_fails_even_past_init(self):
        v = self.classify(FATAL_LOG, 134)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith("fatal G4/art abort:\n"))
        self.assertIn("GeomSolids0002", v.reason)

    def test_a_missing_gdml_dump_fails(self):
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertIn(f"GDML dump {Path('/nonexistent.gdml').name} not "
                      f"produced", v.reason)
        self.assertFalse(v.gdml_verified)

    def test_an_as_built_geometry_that_differs_fails(self):
        wrong = self.gdml_file(gdml([("Foil_00", 51.0, 100.0, 1.0, "mm"),
                                     ("Foil_01", 51.0, 200.0, 0.5, "mm")]))
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=wrong)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "as-built geometry differs from geom file (2 mismatches):\n"))
        self.assertIn("    Foil_00 rIn", v.reason)
        self.assertFalse(v.gdml_verified)

    def test_a_malformed_gdml_dump_fails_with_the_parse_error(self):
        # A dump cut short by a timeout or a crash mid-write is truncated
        # XML: ET.iterparse raises ParseError, which must not escape
        # classify() as an unhandled exception (F2, 2026-09-26).
        truncated = self.gdml_file('<?xml version="1.0"?>\n<gdml><solids>'
                                   '<tube name="Foil_00" rmin="10.0"')
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=truncated)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertIn("could not be parsed", v.reason)
        self.assertIn("unclosed token", v.reason)
        self.assertFalse(v.gdml_verified)

    def test_a_matching_gdml_passes_and_counts_the_foils(self):
        good = self.gdml_file(gdml_matching(GEOM))
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=good)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertIn("geometry assertion: 2 foils verified against as-built "
                      "GDML (rIn/rOut/thickness)", v.notes)
        self.assertTrue(v.gdml_verified)

    def test_a_verified_gdml_stays_verified_when_a_later_rule_fails(self):
        good = self.gdml_file(gdml_matching(GEOM))
        v = self.classify(ADVISORY_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=good)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith("zero-overlap policy:"))
        self.assertTrue(v.gdml_verified)

    def test_any_overlap_fails_under_the_zero_overlap_policy(self):
        v = self.classify(ADVISORY_LOG, 0)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "zero-overlap policy: 1 overlap(s) in 1 volume(s):\n"
            "    TT_MidInner"))
        self.assertIn("\ncontext:\n", v.reason)

    def test_stock_overlaps_pass_under_the_managed_policy(self):
        v = self.classify(ADVISORY_LOG, 0, require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertTrue(v.reason.endswith("and no managed-volume overlap."))
        self.assertIn("(info) 1 known stock-geometry overlaps (1 unique "
                      "volumes); ignored — not managed by BO knobs.", v.notes)

    def test_a_managed_volume_overlap_fails(self):
        v = self.classify(MANAGED_LOG, 0, require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "managed-volume overlap detected:\n    StoppingTargetFoil_07:0"))
        self.assertIn("\ncontext:\n", v.reason)

    def test_a_geometry_error_before_init_fails(self):
        v = self.classify(PRE_INIT_GEOM_LOG, 65,
                          checks_managed_overlap=False)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith("Geant4 geometry error:\n"))
        self.assertIn("GeomMgt0002", v.reason)

    def test_no_banner_and_a_failed_run_is_ambiguous_with_the_log_tail(self):
        v = self.classify(NO_MU2E_LOG, 127)
        self.assertEqual((v.ok, v.code), (False, "ambiguous"))
        self.assertTrue(v.reason.startswith(
            "rc=127, no geom-fail signature. Last 40 lines of log:\n"))
        self.assertIn("mu2e: command not found", v.reason)

    def test_a_timeout_passes_as_it_always_has(self):
        v = self.classify("Geant4 version Name: geant4-11-02\n", -1,
                          timed_out=True)
        self.assertEqual((v.ok, v.code), (True, "pass"))

    def test_every_code_is_a_verdict_value(self):
        for out, rc in ((CLEAN_LOG, 0), (FATAL_LOG, 134), (NO_MU2E_LOG, 127)):
            self.assertIn(self.classify(out, rc).code,
                          pc.PREFLIGHT_VERDICTS)


class TestFiles(unittest.TestCase):
    def test_geom_name_is_the_grid_jobs_name(self):
        self.assertEqual(pc.geom_name("cfg1"), "autoresearch_cfg1_geom.txt")

    def test_the_overlay_includes_the_geometry_and_the_fcl_names_it(self):
        files = pc.check_files("autoresearch_cfg1_geom.txt", dumps_gdml=False)
        self.assertEqual(sorted(files),
                         ["surfacecheck.fcl",
                          "surfacecheck_autoresearch_cfg1_geom.txt"])
        overlay = files["surfacecheck_autoresearch_cfg1_geom.txt"]
        self.assertTrue(overlay.startswith(
            '#include "autoresearch_cfg1_geom.txt"\n'))
        self.assertIn("bool g4.doSurfaceCheck             = true;", overlay)
        fcl = files[pc.FCL_NAME]
        self.assertIn('#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"', fcl)
        self.assertIn('services.GeometryService.inputFile : '
                      '"surfacecheck_autoresearch_cfg1_geom.txt"', fcl)
        self.assertNotIn("writeGDML", fcl)

    def test_dumps_gdml_adds_the_gdml_lines(self):
        fcl = pc.check_files("g.txt", dumps_gdml=True)[pc.FCL_NAME]
        self.assertTrue(fcl.endswith(pc.PREFLIGHT_GDML_FCL_LINES))

    def test_stage_workdir_empties_it_then_writes_the_files(self):
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "cfg1" / "preflight"
            w.mkdir(parents=True)
            (w / pc.PREFLIGHT_GDML_NAME).write_text("stale")
            pc.stage_workdir(w, geom_text="// g\n",
                             geom_basename="autoresearch_cfg1_geom.txt",
                             dumps_gdml=True)
            self.assertEqual(sorted(p.name for p in w.iterdir()),
                             ["autoresearch_cfg1_geom.txt", "surfacecheck.fcl",
                              "surfacecheck_autoresearch_cfg1_geom.txt"])
            self.assertEqual((w / "autoresearch_cfg1_geom.txt").read_text(),
                             "// g\n")


class TestRunCheck(unittest.TestCase):
    def run_check(self, stdout="out", stderr="err", rc=0):
        seen = {}

        def fake(cmd, **kw):
            seen.update(cmd=cmd, **kw)
            p = subprocess.CompletedProcess(["bash"], rc, stdout=stdout,
                                            stderr=stderr)
            p.timed_out = False
            return p

        with mock.patch.object(pc, "run_sourced_bash", fake):
            result = pc.run_check(Path("/c/abc"), Path("/w/cfg1/preflight"),
                                  "surfacecheck.fcl", timeout_s=60,
                                  log=io.StringIO())
        return result, seen

    def test_the_command_unsets_muse_work_dir_first(self):
        _result, seen = self.run_check()
        self.assertTrue(seen["cmd"].startswith("unset MUSE_WORK_DIR && "))

    def test_the_command_sources_the_tarballs_setup_and_prepends_the_workdir(self):
        (out, rc, timed_out), seen = self.run_check()
        cmd = seen["cmd"]
        self.assertIn(f"source {pc.SETUPMU2E} >/dev/null && ", cmd)
        self.assertIn("source /c/abc/Code/setup.sh >/dev/null && ", cmd)
        self.assertIn('export MU2E_SEARCH_PATH="/w/cfg1/preflight:'
                      '$MU2E_SEARCH_PATH"', cmd)
        self.assertIn('export FHICL_FILE_PATH="/w/cfg1/preflight:'
                      '$FHICL_FILE_PATH"', cmd)
        self.assertTrue(cmd.endswith(
            "cd /w/cfg1/preflight && mu2e -c surfacecheck.fcl -n 1"))
        self.assertEqual(seen["timeout"], 60)
        self.assertIs(seen["should_retry"], pc.retry_if_mu2e_never_started)
        self.assertEqual((out, rc, timed_out),
                         ("out\n--- STDERR ---\nerr", 0, False))

    def test_only_a_run_that_never_started_is_retried(self):
        def proc(rc, out=""):
            return subprocess.CompletedProcess(["bash"], rc, stdout=out,
                                               stderr="")
        self.assertTrue(pc.retry_if_mu2e_never_started(proc(127)))
        self.assertFalse(pc.retry_if_mu2e_never_started(
            proc(3, "Geant4 version Name")))
        self.assertFalse(pc.retry_if_mu2e_never_started(proc(0)))


class TestRunPreflight(unittest.TestCase):
    """run_preflight: the sequence the offline_preflight kit calls -- unpack
    the code tarball, stage the emptied workdir, run, keep preflight.log,
    classify."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.workdir = self.tmp / "grid" / "cfg1" / "preflight"
        self.calls = []
        patch = mock.patch.object(pe, "unpacked",
                                  return_value=self.tmp / "code")
        patch.start()
        self.addCleanup(patch.stop)

    def runner(self, out, rc, *, timed_out=False, gdml_text=None):
        def fake(code_dir, workdir, fcl, *, timeout_s, label, log=None):
            self.calls.append((code_dir, workdir, fcl, timeout_s, label, log))
            if gdml_text is not None:
                (workdir / pc.PREFLIGHT_GDML_NAME).write_text(gdml_text)
            return out, rc, timed_out
        return fake

    def run_preflight(self, runner, **over):
        kw = dict(cache_root=self.tmp / "grid" / "_code", dumps_gdml=False,
                  **STRICT, label="preflight/t", runner=runner)
        kw.update(over)
        return pc.run_preflight(self.tmp / "Code.tar.bz2", GEOM, "cfg1",
                                self.workdir, **kw)

    def test_it_unpacks_stages_runs_keeps_the_log_and_classifies(self):
        log = io.StringIO()
        verdict, out = self.run_preflight(self.runner(CLEAN_LOG, 0),
                                          timeout_s=60, log=log)
        pe.unpacked.assert_called_once_with(self.tmp / "Code.tar.bz2",
                                            self.tmp / "grid" / "_code")
        self.assertEqual(self.calls, [(self.tmp / "code", self.workdir,
                                       pc.FCL_NAME, 60, "preflight/t", log)])
        self.assertEqual(out, CLEAN_LOG)
        self.assertEqual((verdict.ok, verdict.code), (True, "pass"))
        self.assertEqual(verdict.reason, "init=True; no geom-fail signature "
                                         "and zero surface-check overlaps.")
        self.assertEqual(sorted(p.name for p in self.workdir.iterdir()),
                         ["autoresearch_cfg1_geom.txt", pc.LOG_NAME,
                          "surfacecheck.fcl",
                          "surfacecheck_autoresearch_cfg1_geom.txt"])
        self.assertEqual((self.workdir / pc.geom_name("cfg1")).read_text(),
                         GEOM)
        self.assertEqual((self.workdir / pc.LOG_NAME).read_text(), CLEAN_LOG)

    def test_the_timeout_defaults_to_the_pre_checks_cap(self):
        self.run_preflight(self.runner(CLEAN_LOG, 0))
        self.assertEqual(self.calls[0][3], pc.TIMEOUT_S)

    def test_the_return_code_is_the_first_note(self):
        verdict, _out = self.run_preflight(self.runner(FATAL_LOG, 134))
        self.assertEqual(verdict.code, "fail_managed")
        self.assertEqual(verdict.notes[0], "return code: 134  timed_out=False")

    def test_the_run_checks_its_own_dump_not_a_stale_one(self):
        # A dump left by the last run must not verify this one: the workdir
        # is emptied before the run.
        self.workdir.mkdir(parents=True)
        (self.workdir / pc.PREFLIGHT_GDML_NAME).write_text(gdml_matching(GEOM))
        verdict, _out = self.run_preflight(self.runner(CLEAN_LOG, 0),
                                           dumps_gdml=True,
                                           verifies_foil_gdml=True)
        self.assertEqual(verdict.code, "fail_managed")
        self.assertIn("GDML dump preflight_geom.gdml not produced",
                      verdict.reason)
        self.assertIn("writeGDML",
                      (self.workdir / pc.FCL_NAME).read_text())

    def test_the_workdirs_dump_is_the_one_verified(self):
        verdict, _out = self.run_preflight(
            self.runner(CLEAN_LOG, 0, gdml_text=gdml_matching(GEOM)),
            dumps_gdml=True, verifies_foil_gdml=True)
        self.assertEqual((verdict.ok, verdict.code), (True, "pass"))
        self.assertTrue(verdict.gdml_verified)

    def test_the_run_check_in_force_at_call_time_is_the_default_runner(self):
        with mock.patch.object(pc, "run_check",
                               side_effect=self.runner(CLEAN_LOG, 0)):
            verdict, _out = self.run_preflight(None)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(verdict.ok)

    def test_a_missing_tarball_fails_naming_it_and_runs_nothing(self):
        pe.unpacked.side_effect = ValueError(
            f"code_tarball {self.tmp / 'Code.tar.bz2'} does not exist")
        with self.assertRaisesRegex(ValueError, "Code.tar.bz2 does not exist"):
            self.run_preflight(self.runner(CLEAN_LOG, 0))
        self.assertEqual(self.calls, [])
        self.assertFalse(self.workdir.exists())


if __name__ == "__main__":
    unittest.main()
