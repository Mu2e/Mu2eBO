"""Behavioural tests for the shipped foilspf spec.

Separate from test_mode_json.py on purpose: that module tests the LOADER
(schema, rejection paths); this one tests that THIS spec renders the
geometry the design asked for. A loader bug and a spec bug fail different
files.

Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md
"""
import itertools
import math
import sys
import unittest
from pathlib import Path

# Match the rest of the suite: core/ on sys.path, import `modes` bare, so
# exactly one ModeSpec class is ever live in this process.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402

N_FOILS = 49
DEPLOYED = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 800.0]


def _render(x):
    return modes.SPECS["foilspf"].geom.render(x)


def _vec(text, key):
    """Pull one `vector<double> <key> = { ... };` line out of a render."""
    prefix = f"vector<double> {key} = {{"
    for line in text.splitlines():
        if line.startswith(prefix):
            body = line[len(prefix):].rsplit("}", 1)[0]
            return [float(v) for v in body.split(",")]
    raise KeyError(f"{key} not found in render")


def _scalar(text, key):
    for line in text.splitlines():
        if line.startswith("double ") and line.split(" = ")[0] == f"double {key}":
            return line.split(" = ")[1].rstrip(";")
    raise KeyError(f"{key} not found in render")


def _mass_g(x):
    """Aluminium mass of the rendered stack, grams. Al density 2.70e-3 g/mm^3."""
    text = _render(x)
    rout = _vec(text, "stoppingTarget.radii")
    rin = _vec(text, "stoppingTarget.holeRadii")
    ht = _vec(text, "stoppingTarget.halfThicknesses")
    return sum(math.pi * (a * a - b * b) * 2 * t * 2.70e-3
               for a, b, t in zip(rout, rin, ht))


class TestFoilspfRegistration(unittest.TestCase):

    def test_spec_loads_and_registers_as_a_json_mode(self):
        import bo_driver as bo
        self.assertIn("foilspf", modes.SPECS)
        self.assertIsInstance(bo.MODES["foilspf"], bo.JsonMode)

    def test_bounds_match_the_design(self):
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.knob_names, (
            "rOut_0", "rOut_1", "rOut_2",
            "hT_0", "hT_1", "hT_2",
            "f_0", "f_1", "f_2",
            "extent"))
        self.assertEqual(s.bounds_lo,
                         (50.0, 50.0, 50.0, 0.01, 0.01, 0.01, 0.0, 0.0, 0.0, 400.0))
        self.assertEqual(s.bounds_hi,
                         (120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.95, 0.95, 0.95, 1100.0))
        self.assertEqual(s.int_dims, ())

    def test_run_configuration_matches_foilsflash(self):
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.grid_stages, ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(s.presubmit_after, {"mubeam": ("elebeam_flash",)})
        self.assertEqual(s.obs_noise, (0.006, 0.01))
        self.assertIn("Code_helical_holeradii.tar.bz2", s.grid_tarball)

    def test_leaderboard_is_not_shared_with_any_other_mode(self):
        """Two modes writing one leaderboard interleaves incompatible schemas."""
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.leaderboard_rel,
                         "leaderboards/leaderboard_bo_foilspf.tsv")
        others = [m.leaderboard_rel for n, m in modes.SPECS.items() if n != "foilspf"]
        self.assertNotIn(s.leaderboard_rel, others)


class TestFoilspfGeometry(unittest.TestCase):

    def test_every_per_foil_vector_has_49_entries(self):
        text = _render(DEPLOYED)
        for key in ("stoppingTarget.radii",
                    "stoppingTarget.halfThicknesses",
                    "stoppingTarget.holeRadii"):
            self.assertEqual(len(_vec(text, key)), N_FOILS, key)

    def test_deployed_equivalent_control_points_reproduce_the_deployed_stack(self):
        """All three control points equal => a flat profile. This is the
        anchor: if it drifts, every comparison against the deployed target
        is meaningless."""
        text = _render(DEPLOYED)
        self.assertEqual(set(_vec(text, "stoppingTarget.radii")), {75.0})
        self.assertEqual(set(_vec(text, "stoppingTarget.halfThicknesses")), {0.0528})
        self.assertEqual(set(_vec(text, "stoppingTarget.holeRadii")), {21.525})
        self.assertEqual(_scalar(text, "stoppingTarget.z0InMu2e"), "5871.0000")

    def test_extent_knob_drives_deltaZ(self):
        for extent, expected in ((400.0, "8.333333"),
                                 (800.0, "16.666667"),
                                 (1100.0, "22.916667")):
            x = DEPLOYED[:9] + [extent]
            self.assertEqual(_scalar(_render(x), "stoppingTarget.deltaZ"), expected)

    def test_a_bent_profile_is_not_flat(self):
        """Guards against a wiring bug where all three control points feed
        the same slot and every profile silently renders flat."""
        x = [50.0, 85.0, 120.0] + DEPLOYED[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertAlmostEqual(r[0], 50.0, places=3)
        self.assertAlmostEqual(r[48], 120.0, places=3)
        self.assertGreater(r[24], r[0])

    def test_clip_projects_the_quadratic_overshoot(self):
        """A quadratic through in-bounds control points overshoots BETWEEN
        them: (50, 120, 120) peaks at 128.8 near i=36. The clip must project
        it onto 120 rather than emit an out-of-bounds radius."""
        x = [50.0, 120.0, 120.0] + DEPLOYED[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertLessEqual(max(r), 120.0)
        self.assertAlmostEqual(r[36], 120.0, places=4)

    def test_hole_is_strictly_inside_the_foil_at_every_bound_corner(self):
        """rIn < rOut must hold everywhere, or G4Tubs aborts. 64 corners of
        the (rOut, f) sub-box."""
        worst = float("inf")
        for c in itertools.product((50.0, 120.0), repeat=3):
            for f in itertools.product((0.0, 0.95), repeat=3):
                x = list(c) + [0.0528] * 3 + list(f) + [800.0]
                text = _render(x)
                rout = _vec(text, "stoppingTarget.radii")
                rin = _vec(text, "stoppingTarget.holeRadii")
                worst = min(worst, min(a - b for a, b in zip(rout, rin)))
        self.assertGreater(worst, 0.0)

    def test_poison_pill_survives_the_json_number_grammar(self):
        """1.0e6 must reach the geometry verbatim. Rendered as 1000000.0 it
        still crashes, but the intent is unreadable; rendered as a
        'sensible' scalar it would silently build a uniform-hole stack --
        which is how 62 foilsg rows were lost."""
        text = _render(DEPLOYED)
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;", text)

    def test_no_geometry_key_is_emitted_twice(self):
        """Duplicate keys are last-write-wins in SimpleConfig, silently. The
        live hazard is deltaZ: a leftover constant would override the extent
        knob and pin every eval at 800 mm while the leaderboard recorded a
        knob that did nothing. GeomTemplate rejects duplicates at load, so
        this asserts the shipped render actually exercises that guarantee."""
        keys = []
        for line in _render(DEPLOYED).splitlines():
            if line.startswith("//") or line.startswith("#") or not line.strip():
                continue
            keys.append(line.split(" = ")[0].split(" ", 1)[1])
        self.assertEqual(sorted(keys), sorted(set(keys)))


class TestFoilspfMassEnvelope(unittest.TestCase):
    """The bounds were chosen to cap stack mass. If someone widens them,
    these fire before any grid time is spent."""

    DEPLOYED_37_FOIL_MASS_G = 171.1

    def test_deployed_equivalent_mass_is_49_over_37_of_the_real_target(self):
        self.assertAlmostEqual(_mass_g(DEPLOYED), 226.6, delta=1.0)

    def test_worst_corner_stays_inside_the_designed_envelope(self):
        """Heaviest reachable stack: max radius, no hole, max thickness."""
        x = [120.0] * 3 + [0.15] * 3 + [0.0] * 3 + [800.0]
        mass = _mass_g(x)
        self.assertAlmostEqual(mass, 1795.5, delta=5.0)
        self.assertLess(mass / self.DEPLOYED_37_FOIL_MASS_G, 11.0)

    def test_extent_does_not_change_mass(self):
        """Spreading the same foils over more z adds no aluminium. If this
        fails, extent is wired to something it should not touch."""
        short = _mass_g(DEPLOYED[:9] + [400.0])
        long_ = _mass_g(DEPLOYED[:9] + [1100.0])
        self.assertAlmostEqual(short, long_, places=6)


if __name__ == "__main__":
    unittest.main()
