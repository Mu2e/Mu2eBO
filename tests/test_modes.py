"""Completeness + lockstep tests for the ModeSpec registry (ADR-0002).

These are the tests that turn "MUST stay in lockstep" comments into failures:
a new mode, a moved bound, or a renamed stage now breaks HERE instead of
silently building the wrong geometry on the grid.
"""
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402

# The Python-mode names -- frozen here, deliberately NOT derived from
# modes.SPECS. Dropping a real mode_specs/*.json file in (the entire
# point of the json-modes branch) adds a SPECS entry; tests that assert
# facts about "the Python modes" must key off this frozen set, not "every key
# in SPECS", or they break the moment the feature they exist to enable is
# first used. See I6 in the json-configurable-modes final review.
# Empty since 2026-08-08: the last five Python-mode adapters (foils, foilsf,
# foilsg, prodtarget, prodtarget6d) were archived that day -- see
# docs/superpowers/specs/2026-08-08-leaderboard-module-design.md. Every mode
# is JSON-defined now (JsonMode); test_python_mode_names_matches_the_live_registry
# below derives the truth from the registry so a stale name cannot linger
# unnoticed if a Python mode adapter is ever reintroduced.
PYTHON_MODE_NAMES = frozenset()


class TestRegistryCompleteness(unittest.TestCase):
    def test_keys_match_driver_modes(self):
        import bo_driver as bo
        self.assertEqual(set(modes.SPECS), set(bo.MODES),
                         "modes.SPECS and driver MODES diverged")

    def test_name_field_matches_key(self):
        for name, spec in modes.SPECS.items():
            self.assertEqual(spec.name, name)

    def test_python_mode_names_matches_the_live_registry(self):
        """PYTHON_MODE_NAMES drives which modes are asserted to carry no JSON
        fields. Derive the truth from the registry rather than trusting the
        hand-maintained set: when foilsflash was retired to JSON (2026-07-26)
        a stale entry here turned into a confusing failure in a test that was
        not about retirement at all."""
        import bo_driver as bo
        live = {n for n, m in bo.MODES.items()
                if not isinstance(m, bo.JsonMode)}
        self.assertEqual(set(PYTHON_MODE_NAMES), live,
                         "PYTHON_MODE_NAMES is stale: a mode was retired to "
                         "JSON (or added) without updating this set")

    def test_every_fact_populated(self):
        for name, spec in modes.SPECS.items():
            self.assertTrue(spec.musing.startswith("/"), name)
            self.assertTrue(spec.grid_tarball.endswith(".tar.bz2"), name)
            self.assertGreater(len(spec.grid_stages), 0, name)
            # "harvest-pot-only" retired 2026-08-08 with the ProdTarget
            # family (its only user); "harvest" is the sole verb now.
            self.assertEqual(spec.harvest_verb, "harvest", name)

    def test_obs_noise_declared_per_family(self):
        # The foils/flash family has replicate-measured sigma and MUST pin
        # it (free MLL noise ranked the best-ever eval 16th of 324).
        # "foils"/"foilsf"/"foilsg" (the original Python-mode family) and
        # the ProdTarget family (which declared obs_noise=None EXPLICITLY,
        # since its GP axis 1 is a raw negated value whose units depend on
        # which fallback fired) were both archived 2026-08-08; foilsflash is
        # the sole surviving anchor of this pin.
        noise = modes.SPECS["foilsflash"].obs_noise
        self.assertIsNotNone(noise)
        self.assertEqual(len(noise), 2)
        self.assertTrue(all(v > 0 for v in noise))

    def test_obs_noise_malformed_rejected_at_construction(self):
        import dataclasses
        spec = modes.SPECS["foilsflash"]
        for bad in ((0.006,), (0.006, 0.0), (0.006, -1.0), (0.006, 0.01, 0.02)):
            with self.assertRaises(ValueError, msg=repr(bad)):
                dataclasses.replace(spec, obs_noise=bad)


class TestBoundsLockstep(unittest.TestCase):
    def test_build_space_matches_spec(self):
        # THE lockstep test: build_space pairs the driver's KNOB_NAMES with
        # the registry bounds and must raise loudly on a length mismatch;
        # the SpaceDim rows it returns must mirror the spec exactly (the
        # spec is what the botorch picker and cloud plots read).
        import bo_driver as bo
        for name, spec in modes.SPECS.items():
            dims = bo.MODES[name].build_space()
            lo = tuple(d.low for d in dims)
            hi = tuple(d.high for d in dims)
            intd = tuple(i for i, d in enumerate(dims) if d.is_int)
            self.assertEqual(spec.bounds_lo, lo, name)
            self.assertEqual(spec.bounds_hi, hi, name)
            self.assertEqual(spec.int_dims, intd, name)
            self.assertEqual(tuple(d.name for d in dims),
                             tuple(bo.MODES[name].KNOB_NAMES), name)

    def test_leaderboard_row_roundtrips(self):
        # format_row writes the leaderboard header + line; load_history_row
        # must read exactly those columns back. This pins the KNOB_NAMES /
        # header / CALO_COL contract the 2026-07-12 driver collapse introduced:
        # a renamed knob column silently breaks reading EXISTING rows (dropped
        # via load_history's except-continue). Round-trips build_space midpoints
        # through format_row and back for every mode.
        import csv
        import io
        import bo_driver as bo
        extras = {"edep_per_POT_MeV": 1.2e-9, "peak_dose_Gy_per_POT": 3.4e-12,
                  "peak_dose_plate_idx": 5}
        for name, mode in bo.MODES.items():
            x0 = []
            for d in mode.build_space():
                if d.is_int:
                    x0.append(int(round((d.low + d.high) / 2)))
                else:
                    x0.append((d.low + d.high) / 2.0)
            p = bo.Point(cfg="RT01", x=x0, sob=3.21, calo=6.5e-7, extras=extras)
            header, line = mode.format_row(p, alpha=1.0e5)
            row = next(csv.DictReader(io.StringIO(header + line), delimiter="\t"))
            back = mode.load_history_row(row)
            self.assertEqual(back.cfg, "RT01", name)
            self.assertEqual(len(back.x), len(x0), name)
            for got, want in zip(back.x, x0):
                if isinstance(want, str):
                    self.assertEqual(got, want, name)
                else:
                    self.assertAlmostEqual(float(got), float(want), places=3, msg=name)

    def test_prodtarget_tarball_matches_stage_config(self):
        # ProdTargetMode was archived 2026-08-08; modes._PRODTARGET_TARBALL
        # is the surviving single source for this fact (core/mode_json.py's
        # pot_only-stage guard also reads it), not modes.SPECS["prodtarget"]
        # (that key is gone).
        #
        # Re-assert worktree core/ at sys.path[0] before this bare `import
        # pipeline`: an earlier test in this class already imports bo_driver,
        # whose hardcoded ROOT (core/bo_driver.py:95, out of scope here)
        # inserts the LIVE tree's graph/ ahead of us -- and the LIVE tree's
        # graph/config.py (once that resolves "config") inserts the LIVE
        # tree's core/ at position 0 too, self-relative to its own __file__.
        # If "pipeline" has not been cached yet, a fresh sys.path search
        # then finds the LIVE tree's UNPATCHED core/pipeline.py (which still
        # reads the now-deleted modes.SPECS["prodtarget"]) ahead of this
        # worktree's fixed copy -- a KeyError that has nothing to do with
        # this test's own assertion. Standalone `-m unittest tests.test_modes`
        # hits this deterministically (TestBoundsLockstep.
        # test_build_space_matches_spec imports bo_driver first,
        # alphabetically, within the same class); the full `discover` suite
        # does not, because some earlier file caches "pipeline" from the
        # worktree first.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
        import pipeline
        self.assertEqual(modes._PRODTARGET_TARBALL,
                         pipeline.STAGES["pot_only"]["code_tarball"])


class TestSpotFacts(unittest.TestCase):
    """Load-bearing values pinned individually — the ones with incident
    history or active standards behind them."""

    def test_foilsflash_thickness_floor(self):
        self.assertEqual(modes.SPECS["foilsflash"].bounds_lo[2], 0.002)
        self.assertEqual(modes.SPECS["foilsflash"].bounds_lo[3], 0.002)

    def test_foilsflash_elebeam_standard_100(self):
        self.assertEqual(
            modes.SPECS["foilsflash"].stage_target_overrides["elebeam_flash"], 100)

    def test_foilsflash_presubmit_overlap(self):
        self.assertEqual(modes.SPECS["foilsflash"].presubmit_after,
                         {"mubeam": ("elebeam_flash",)})

    def test_foils_family_needs_holeradii_tarball(self):
        # (ipa — the last non-holeradii CE/calo mode — retired 2026-07-18;
        # its base-tarball regression pin went with it. "foils"/"foilsf"/
        # "foilsg" -- the Python-mode family -- archived 2026-08-08;
        # foilsflash is the sole surviving anchor.)
        self.assertIn("holeradii", modes.SPECS["foilsflash"].grid_tarball)

    # test_prodtarget6d_banner_drift_retired removed 2026-08-08: pinned
    # `modes.SPECS["prodtarget6d"].checks_managed_overlap` as a regression
    # guard against the old hand-listed preflight-mode-tuple omission bug.
    # prodtarget6d itself was archived (Python-mode adapter deleted, no JSON
    # replacement); nothing named "prodtarget6d" is left to omit from a
    # tuple that no longer exists either (checks_managed_overlap is a
    # per-ModeSpec field, not a hand-listed mode-name tuple).


class TestSchemaFields(unittest.TestCase):
    def test_lockstep_enforced_at_construction(self):
        import dataclasses
        with self.assertRaises(ValueError):
            dataclasses.replace(modes.SPECS["foilsflash"], knob_names=("one",))

    def test_metric_cols_spot_pins(self):
        # "foils" (plain "calo" tail) and "prodtarget" (5-column mu_per_POT
        # tail) were archived 2026-08-08; every surviving mode shares the
        # foilsflash-family "flash_edep" tail, so there is no longer a
        # second shape to contrast against.
        self.assertEqual(modes.SPECS["foilsflash"].metric_cols,
                         ("sob", "flash_edep", "alpha", "obj"))

    def test_driver_reads_registry(self):
        import bo_driver as bo
        for name, mode in bo.MODES.items():
            self.assertEqual(mode.KNOB_NAMES, modes.SPECS[name].knob_names)
            self.assertEqual(mode.KNOB_FMTS, modes.SPECS[name].knob_fmts)

    def test_calo_col_derives_from_metric_cols(self):
        import bo_driver as bo
        self.assertEqual(bo.MODES["foilsflash"].CALO_COL, "flash_edep")

    def test_format_row_rejects_non4_metric_tail(self):
        import dataclasses
        import bo_driver as bo
        bad = dataclasses.replace(modes.SPECS["foilsflash"],
                                  metric_cols=("sob", "calo", "obj"))
        with mock.patch.dict(modes.SPECS, {"foilsflash": bad}):
            with self.assertRaises(ValueError):
                bo.MODES["foilsflash"].format_row(
                    bo.Point(cfg="x", x=[0.0] * 6, sob=0.0, calo=1.0), 1.0)


class TestGeomField(unittest.TestCase):
    # test_python_modes_declare_the_json_fields_as_none removed 2026-08-08:
    # asserted geom/metrics/leaderboard_rel are None and stage_tuning={} for
    # every name in PYTHON_MODE_NAMES. That set is now permanently empty (no
    # Python-mode adapters survive), so the loop body could never execute --
    # a vacuously-passing test is worse than no test.

    def test_the_new_fields_are_required_not_defaulted(self):
        """A missing fact must be a TypeError, never a silent default."""
        import dataclasses
        by_name = {f.name: f for f in dataclasses.fields(modes.ModeSpec)}
        for field in ("geom", "metrics", "leaderboard_rel"):
            self.assertIn(field, by_name)
            self.assertIs(by_name[field].default, dataclasses.MISSING,
                          f"{field} must not have a default")
            self.assertIs(by_name[field].default_factory, dataclasses.MISSING,
                          f"{field} must not have a default_factory")
        with self.assertRaises(TypeError):
            modes.ModeSpec(name="x")  # type: ignore[call-arg]


class TestSubprocessImport(unittest.TestCase):
    def test_imports_with_only_core_on_syspath(self):
        """Verify modes imports cleanly with only core/ on sys.path
        (the production path when bo_driver is invoked as a subprocess).
        TYPE_CHECKING guard ensures this works despite GeomTemplate annotation.
        """
        import subprocess
        core = Path(__file__).resolve().parent.parent / "core"
        # Was: counted the six frozen Python-mode names against modes.SPECS
        # (all archived 2026-08-08). "foilsflash" is the stable, long-lived
        # JSON mode (mode_specs/foilsflash.json) -- a fixed anchor to check
        # instead, unlike the shipped-specs set as a whole (IPA A/B clones
        # and similar throwaway modes come and go, see
        # TestModeSpecsDirectoryWiring.SHIPPED_SPECS).
        script = "import modes; print('foilsflash' in modes.SPECS)"
        r = subprocess.run([sys.executable, "-c", script],
                           cwd=str(core), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"import failed: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "True",
                         "modes.SPECS must expose the foilsflash JSON spec")


class TestModeSpecsDirectoryWiring(unittest.TestCase):
    """F8: the two lines that ARE the json-modes feature had zero coverage.

    Deleting either `SPECS.update(load_mode_dir(MODES_DIR, SPECS))` at the
    tail of core/modes.py or the `MODES[_name] = JsonMode(_name)` loop in
    core/bo_driver.py left the whole suite green -- verified by mutation,
    twice. Every other test registers its spec by hand into modes.SPECS and
    so deliberately bypasses the real mode_specs/ directory; nothing
    exercised "drop a JSON file in mode_specs/, get a runnable mode".

    This test does exactly that, in a fresh subprocess (core/modes.py's
    MODES_DIR is a hardcoded path resolved at import, not overridable), and
    checks all three links of the chain: the spec is discovered, a JsonMode
    is registered under that name in the driver, and it renders geometry.
    """

    def test_a_json_file_in_mode_specs_becomes_a_runnable_mode(self):
        root = Path(__file__).resolve().parent.parent
        name = "wiringprobe" + uuid.uuid4().hex[:8]
        doc = json.loads(
            (Path(__file__).parent / "fixtures" / "modes" / "foils.json").read_text())
        doc["name"] = name
        # Its own leaderboard: the loader now rejects a spec that claims one
        # already owned by another mode (F4).
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_bo_{name}.tsv"

        target = root / "mode_specs" / f"{name}.json"
        # addCleanup (not a trailing unlink): mode_specs/ is the REAL
        # directory the production loader reads, and it must be left exactly
        # as found even if an assertion below fails.
        self.addCleanup(target.unlink, True)   # missing_ok=True
        target.write_text(json.dumps(doc))

        script = (
            "import sys\n"
            "sys.path.insert(0, 'core')\n"
            "import modes, bo_driver\n"
            f"n = {name!r}\n"
            "print('SPEC_DISCOVERED', n in modes.SPECS)\n"
            "m = bo_driver.MODES.get(n)\n"
            "print('DRIVER_CLASS', type(m).__name__)\n"
            "print('GEOM_RENDERS', bool(m) and 'stoppingTarget.radii' in "
            "m._geom_text([120.0, 130.0, 0.1, 0.2, 15.0, 40.0]))\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        r = subprocess.run([sys.executable, "-c", script], cwd=str(root),
                           capture_output=True, text=True, env=env, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(),
                         ["SPEC_DISCOVERED True",
                          "DRIVER_CLASS JsonMode",
                          "GEOM_RENDERS True"], r.stdout)

    # Specs deliberately shipped in the real mode_specs/ directory. Every file
    # here is loaded by EVERY process that imports modes, so the point of the
    # test below is that nothing arrives unnoticed -- adding a line here is a
    # conscious act, which is exactly the review checkpoint we want.
    SHIPPED_SPECS = {"foilsflash.json", "foilspf.json", "foilspf2k.json"}

    # TEMPORARY -- IPA-position A/B (2026-07-28), NOT shipped modes. Two
    # throwaway clones of foilsflash differing in exactly one number,
    # protonabsorber.distFromTargetEnd: `ipafix` (491.666672, absorber at its
    # true 6901-7901) vs `ipa625` (stock 625, absorber 133.33 mm downstream --
    # the geometry all 414 historical foilsflash rows were taken with). They
    # own separate leaderboards so the known-wrong arm cannot reach the
    # production GP. DELETE both specs and this block once the A/B lands;
    # they are deliberately not committed.
    # `ipaovr.json` is arm C: today's code with the historical
    # tracker.inDS2Vacuum + ds2.halfLength=3825 pair restored, isolating that
    # pair from the Offline v13_12_10 -> v13_32_10 bump as the cause of the
    # measured +4.9% sob shift. Same delete-when-done rule.
    # `nominal.json` is arm D: the DEPLOYED 37-foil target under Run1Bap in
    # the same environment, i.e. the baseline the BO rows are measured against.
    # Its 6 knobs are inert (no geom line references them). Same delete rule.
    SHIPPED_SPECS = SHIPPED_SPECS | {"ipafix.json", "ipa625.json",
                                     "ipaovr.json", "nominal.json"}

    def test_mode_specs_directory_holds_only_the_readme(self):
        """The real directory holds the README plus exactly the shipped specs:
        a STRAY *.json checked in here would be loaded by every process that
        imports modes.

        Was "only the README" until foilsflash became JSON-defined
        (2026-07-26). Kept as an explicit allow-list rather than relaxed to
        "any *.json": the whole value of this guard is that an unintended file
        fails loudly, and `assertEqual` against a named set preserves that
        while a laxer check would not.

        `wiringprobe*.json` is excluded deliberately. The test above stages
        one into this same real directory, and a SECOND suite process running
        concurrently (observed in this environment) would otherwise see the
        other run's in-flight probe and fail here for no reason. Within one
        serial `unittest discover` that cannot happen -- the probe's
        addCleanup fires before this test runs -- but the exclusion costs
        nothing and only blinds this check to a committed file that is
        already self-evidently a test artifact by name."""
        root = Path(__file__).resolve().parent.parent
        stray = sorted(p.name for p in (root / "mode_specs").iterdir()
                       if not p.name.startswith("wiringprobe"))
        self.assertEqual(stray, sorted({"README.md"} | self.SHIPPED_SPECS))

    def test_every_shipped_spec_is_a_registered_json_mode(self):
        """A file in mode_specs/ that never became a live mode means the
        loader silently skipped it."""
        import bo_driver as bo
        for fname in self.SHIPPED_SPECS:
            name = fname[:-len(".json")]
            self.assertIn(name, modes.SPECS, f"{fname} did not reach SPECS")
            self.assertIsInstance(bo.MODES[name], bo.JsonMode)


if __name__ == "__main__":
    unittest.main()
