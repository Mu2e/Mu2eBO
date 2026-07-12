"""Completeness + lockstep tests for the ModeSpec registry (ADR-0002).

These are the tests that turn "MUST stay in lockstep" comments into failures:
a new mode, a moved bound, or a renamed stage now breaks HERE instead of
silently falling back to michael's tarball on the grid.
"""
import typing
import unittest

import modes


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

    def test_ipa_tarball_explicit_not_fallback(self):
        # ipa used to reach Code_helical_base via the silent .get(...,
        # michael) fallback; now it is an explicit fact.
        self.assertEqual(modes.SPECS["ipa"].grid_tarball,
                         modes.SPECS["michael"].grid_tarball)

    def test_foils_family_needs_holeradii_tarball(self):
        for m in ("foils", "foilsf", "foilsflash", "foilsg"):
            self.assertIn("holeradii", modes.SPECS[m].grid_tarball, m)
        for m in ("michael", "helical", "ipa"):
            self.assertNotIn("holeradii", modes.SPECS[m].grid_tarball, m)

    def test_prodtarget6d_banner_drift_retired(self):
        # The old :2403 banner tuple omitted prodtarget6d; the flag is the
        # single source now and must include it.
        self.assertTrue(modes.SPECS["prodtarget6d"].checks_managed_overlap)

    def test_michael_is_the_only_plain_preflight(self):
        plain = [m for m, s in modes.SPECS.items()
                 if s.preflight_fcl == "preflight"]
        self.assertEqual(plain, ["michael"])


if __name__ == "__main__":
    unittest.main()
