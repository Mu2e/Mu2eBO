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

# The six hand-written Python modes -- frozen here, deliberately NOT derived
# from modes.SPECS. Dropping a real mode_specs/*.json file in (the entire
# point of the json-modes branch) adds a 7th SPECS entry; tests that assert
# facts about "the Python modes" must key off this frozen set, not "every key
# in SPECS", or they break the moment the feature they exist to enable is
# first used. See I6 in the json-configurable-modes final review.
PYTHON_MODE_NAMES = frozenset({
    "foils", "foilsf", "foilsflash", "foilsg", "prodtarget", "prodtarget6d",
})


class TestRegistryCompleteness(unittest.TestCase):
    def test_keys_match_driver_modes(self):
        import bo_driver as bo
        self.assertEqual(set(modes.SPECS), set(bo.MODES),
                         "modes.SPECS and driver MODES diverged")

    def test_name_field_matches_key(self):
        for name, spec in modes.SPECS.items():
            self.assertEqual(spec.name, name)

    def test_every_fact_populated(self):
        for name, spec in modes.SPECS.items():
            self.assertTrue(spec.musing.startswith("/"), name)
            self.assertTrue(spec.grid_tarball.endswith(".tar.bz2"), name)
            self.assertGreater(len(spec.grid_stages), 0, name)
            self.assertIn(spec.harvest_verb, ("harvest", "harvest-pot-only"), name)
            self.assertIn(spec.preflight_fcl, ("surfacecheck", "preflight"), name)

    def test_obs_noise_declared_per_family(self):
        # The foils family has replicate-measured sigma and MUST pin it
        # (free MLL noise ranked the best-ever eval 16th of 324). The
        # ProdTarget family declares None EXPLICITLY because its GP axis 1
        # is a raw negated value whose units depend on which fallback fired.
        for name in ("foils", "foilsf", "foilsflash", "foilsg"):
            noise = modes.SPECS[name].obs_noise
            self.assertIsNotNone(noise, name)
            self.assertEqual(len(noise), 2, name)
            self.assertTrue(all(v > 0 for v in noise), name)
        for name in ("prodtarget", "prodtarget6d"):
            self.assertIsNone(modes.SPECS[name].obs_noise, name)

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
        import pipeline
        self.assertEqual(modes.SPECS["prodtarget"].grid_tarball,
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
        # its base-tarball regression pin went with it.)
        for m in ("foils", "foilsf", "foilsflash", "foilsg"):
            self.assertIn("holeradii", modes.SPECS[m].grid_tarball, m)

    def test_prodtarget6d_banner_drift_retired(self):
        # The old :2403 banner tuple omitted prodtarget6d; the flag is the
        # single source now and must include it.
        self.assertTrue(modes.SPECS["prodtarget6d"].checks_managed_overlap)

    def test_all_modes_use_surfacecheck_preflight(self):
        # michael was the only "preflight" (non-surfacecheck) mode; with it
        # retired (2026-07-12), every surviving mode uses the surface-check
        # preflight path.
        self.assertTrue(all(s.preflight_fcl == "surfacecheck"
                            for s in modes.SPECS.values()))


class TestSchemaFields(unittest.TestCase):
    def test_lockstep_enforced_at_construction(self):
        import dataclasses
        with self.assertRaises(ValueError):
            dataclasses.replace(modes.SPECS["foils"], knob_names=("one",))

    def test_metric_cols_spot_pins(self):
        self.assertEqual(modes.SPECS["foilsflash"].metric_cols,
                         ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(modes.SPECS["foils"].metric_cols,
                         ("sob", "calo", "alpha", "obj"))
        self.assertEqual(
            modes.SPECS["prodtarget"].metric_cols,
            ("mu_per_POT", "edep_per_POT_MeV", "peak_dose_Gy_per_POT",
             "peak_plate_idx", "obj"))

    def test_driver_reads_registry(self):
        import bo_driver as bo
        for name, mode in bo.MODES.items():
            self.assertEqual(mode.KNOB_NAMES, modes.SPECS[name].knob_names)
            self.assertEqual(mode.KNOB_FMTS, modes.SPECS[name].knob_fmts)

    def test_calo_col_derives_from_metric_cols(self):
        import bo_driver as bo
        self.assertEqual(bo.MODES["foilsflash"].CALO_COL, "flash_edep")
        self.assertEqual(bo.MODES["foils"].CALO_COL, "calo")

    def test_format_row_rejects_non4_metric_tail(self):
        import dataclasses
        import bo_driver as bo
        bad = dataclasses.replace(modes.SPECS["foils"],
                                  metric_cols=("sob", "calo", "obj"))
        with mock.patch.dict(modes.SPECS, {"foils": bad}):
            with self.assertRaises(ValueError):
                bo.MODES["foils"].format_row(
                    bo.Point(cfg="x", x=[0.0] * 6, sob=0.0, calo=1.0), 1.0)


class TestGeomField(unittest.TestCase):
    def test_python_modes_declare_the_json_fields_as_none(self):
        for name in PYTHON_MODE_NAMES:
            spec = modes.SPECS[name]
            self.assertIsNone(spec.geom, f"{name} should have no geom template")
            self.assertIsNone(spec.metrics, f"{name} should have no metrics map")
            self.assertIsNone(spec.leaderboard_rel, f"{name} sets leaderboard on the class")
            self.assertEqual(spec.stage_tuning, {},
                             f"{name} (Python mode) must declare stage_tuning={{}} explicitly")

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
        # Count only the frozen Python-mode names (see PYTHON_MODE_NAMES
        # above), not len(modes.SPECS): a live mode_specs/*.json file adds
        # extra SPECS entries and must not break this pin.
        script = (
            "import modes; "
            "python_names = {'foils', 'foilsf', 'foilsflash', 'foilsg', "
            "'prodtarget', 'prodtarget6d'}; "
            "print(len(python_names & set(modes.SPECS)))"
        )
        r = subprocess.run([sys.executable, "-c", script],
                           cwd=str(core), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"import failed: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "6", "must expose all six python specs")


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

    def test_mode_specs_directory_holds_only_the_readme(self):
        """The real directory stays clean: a stray *.json checked in here
        would be loaded by every process that imports modes."""
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(
            sorted(p.name for p in (root / "mode_specs").iterdir()),
            ["README.md"])


if __name__ == "__main__":
    unittest.main()
