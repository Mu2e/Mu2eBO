"""Completeness + lockstep tests for the ModeSpec registry (ADR-0002).

These are the tests that turn "MUST stay in lockstep" comments into failures:
a new mode, a moved bound, or a renamed stage now breaks HERE instead of
silently building the wrong geometry on the grid.
"""
import sys
import typing
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402


class TestRegistryCompleteness(unittest.TestCase):
    def test_keys_match_driver_modes(self):
        import autoresearch_bo_michael as bo
        self.assertEqual(set(modes.SPECS), set(bo.MODES),
                         "modes.SPECS and driver MODES diverged")

    def test_keys_match_state_literal(self):
        from graph.state import BOIterationState
        lit = typing.get_type_hints(BOIterationState)["mode"]
        self.assertEqual(set(typing.get_args(lit)), set(modes.SPECS),
                         "graph/state.py mode Literal diverged from modes.SPECS")

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


class TestBoundsLockstep(unittest.TestCase):
    def test_build_space_matches_spec(self):
        # THE lockstep test: driver build_space is the behavioral source of
        # the search box; the spec is the data copy every other consumer
        # (botorch picker, cloud plots) reads. They must be identical.
        import autoresearch_bo_michael as bo
        for name, spec in modes.SPECS.items():
            dims = bo.MODES[name].build_space()
            if any(type(d).__name__ == "Categorical" for d in dims):
                self.assertIsNone(spec.bounds_lo,
                                  f"{name}: categorical space must carry None bounds")
                continue
            lo = tuple(float(d.low) for d in dims)
            hi = tuple(float(d.high) for d in dims)
            intd = tuple(i for i, d in enumerate(dims)
                         if type(d).__name__ == "Integer")
            self.assertEqual(spec.bounds_lo, lo, name)
            self.assertEqual(spec.bounds_hi, hi, name)
            self.assertEqual(spec.int_dims, intd, name)

    def test_leaderboard_row_roundtrips(self):
        # format_row writes the leaderboard header + line; load_history_row
        # must read exactly those columns back. This pins the KNOB_NAMES /
        # header / CALO_COL contract the 2026-07-12 driver collapse introduced:
        # a renamed knob column silently breaks reading EXISTING rows (dropped
        # via load_history's except-continue). Round-trips build_space midpoints
        # through format_row and back for every mode.
        import csv
        import io
        import autoresearch_bo_michael as bo
        extras = {"edep_per_POT_MeV": 1.2e-9, "peak_dose_Gy_per_POT": 3.4e-12,
                  "peak_dose_plate_idx": 5}
        for name, mode in bo.MODES.items():
            x0 = []
            for d in mode.build_space():
                t = type(d).__name__
                if t == "Categorical":
                    x0.append(d.categories[0])
                elif t == "Integer":
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

    def test_ipa_tarball_is_base_not_holeradii(self):
        # ipa used to reach Code_helical_base via the silent .get(..., michael)
        # fallback; now it is an explicit fact. It uses the base tarball (patched
        # Mu2eG4 only, no holeRadii) — the last non-holeradii CE/calo mode after
        # michael/helical retired (2026-07-12).
        self.assertEqual(modes.SPECS["ipa"].grid_tarball, modes._BASE_TARBALL)
        self.assertNotIn("holeradii", modes.SPECS["ipa"].grid_tarball)

    def test_foils_family_needs_holeradii_tarball(self):
        for m in ("foils", "foilsf", "foilsflash", "foilsg"):
            self.assertIn("holeradii", modes.SPECS[m].grid_tarball, m)
        self.assertNotIn("holeradii", modes.SPECS["ipa"].grid_tarball)

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


if __name__ == "__main__":
    unittest.main()
