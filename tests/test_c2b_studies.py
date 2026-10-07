"""The C2b engine twins of the foilspf studies (mode_specs/<name>_ax.json):
foilspf_ax's geometry guards and the two acceptance fixtures (Phase C2b
spec, section 4). The originals are archived since Phase C3."""
import itertools
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES  # noqa: E402

MODES = ROOT / "mode_specs"
TWINS = ("foilsflash_ax", "foilspf_ax", "foilspf2k_ax", "foilspfbp_ax",
         "foilspfbpx_ax", "foilspfbpz_ax", "foilspfbw_ax")
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2"
WORK_AREA = "${ARTIFACT}/autoresearch_muse_ax"
SOB = {"step": "sob", "kit": "anakit", "entry": None, "files": [],
       "files_from": ["mubeam", "mustops_ce"], "params": {}, "params_from": {},
       "fixed": {"analysis": "ce_sensitivity", "input_correction": 0.01278168,
                 "cosmic_rate_per_s_per_mev": 0.0018181818181818182,
                 "dio_fraction": 0.39,
                 "dio_table": WORK_AREA + "/data/heeck_finer_binning_2016_szafron.tbl"}}
FLASH = {"step": "flash", "kit": "anakit", "entry": None, "files": [],
         "files_from": ["elebeam_flash"], "params": {}, "params_from": {},
         "fixed": {"analysis": "flash_edep_per_pot",
                   "pot_per_electron": 11.536718606512062}}


def doc(path):
    return json.loads(Path(path).read_text())


class TestTwinFacts(unittest.TestCase):
    """What makes each file an MDC2025ax engine twin (Phase C2b spec): the
    release's code tarball and run label, the anakit analyses with their
    constants, and its own v2 board. The comparison against the originals
    went with them to mode_specs/archive/ in Phase C3; these are the
    twin-side facts it used to pin."""

    def test_each_twin_runs_mdc2025ax_and_anakit(self):
        for name in TWINS:
            with self.subTest(study=name):
                twin = doc(MODES / f"{name}.json")
                self.assertEqual(twin["name"], name)
                kits = twin["kits"]
                self.assertEqual(kits["prodtools"]["code_tarball"], TARBALL)
                self.assertEqual(kits["prodtools"]["dsconf"],
                                 "MDC2025ax_{cfg}")
                self.assertEqual(kits["offline_preflight"]["code_tarball"],
                                 TARBALL)
                self.assertEqual(kits["anakit"], {"work_area": WORK_AREA})
                steps = {s["step"]: s for s in twin["evaluate"]}
                self.assertEqual(steps["sob"], SOB)
                self.assertEqual(steps["flash"], FLASH)

    def test_each_twin_writes_its_own_v2_board(self):
        for name in TWINS:
            with self.subTest(study=name):
                board = doc(MODES / f"{name}.json")["leaderboard"]
                self.assertEqual(board["file"],
                                 f"leaderboards/leaderboard_bo_{name}.tsv")
                self.assertEqual(board["layout"], "v2")


class TestSpotFacts(unittest.TestCase):
    """Load-bearing values pinned individually -- the ones with incident
    history or active standards behind them (moved onto the loaded _ax
    studies in Phase C3, when the originals were archived)."""

    def test_obs_noise_is_the_replicate_measured_sigma(self):
        # Free MLL noise ranked the best-ever eval 16th of 324
        # (wiki/incidents/gp-free-noise-erases-champion.md).
        for name in ("foilsflash_ax", "foilspf_ax"):
            with self.subTest(study=name):
                self.assertEqual(
                    tuple(o.noise for o in modes.STUDIES[name].objectives),
                    (0.006, 0.010))

    def test_foilsflash_thickness_floor(self):
        s = modes.STUDIES["foilsflash_ax"]
        self.assertEqual(s.bounds_lo[2], 0.002)
        self.assertEqual(s.bounds_lo[3], 0.002)

    def test_foilsflash_elebeam_standard_100(self):
        step = next(s for s in modes.STUDIES["foilsflash_ax"].steps
                    if s.step == "elebeam_flash")
        self.assertEqual(step.fixed["njobs"], 100)


def geom_vector(text, key):
    m = re.search(rf"{re.escape(key)}\s*=\s*\{{([^}}]*)\}}", text)
    return [float(v) for v in m.group(1).split(",")]


def geom_double(text, key):
    m = re.search(rf"double\s+{re.escape(key)}\s*=\s*([-0-9.eE+]+)", text)
    return float(m.group(1))


# --- foilspf_ax's geometry -------------------------------------------------
# Moved from tests/test_foilspf_spec.py in Phase C3, when the original
# foilspf study was archived: its twin foilspf_ax renders the same geometry
# from the same knobs, and these are the guards on it.
# Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md
N_FOILS = 49
DEPLOYED = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 800.0]


def _foilspf():
    return modes.STUDIES["foilspf_ax"]


def _render(x):
    return _foilspf().geom.render(x)


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


class TestFoilspfBox(unittest.TestCase):

    def test_bounds_match_the_design(self):
        s = _foilspf()
        self.assertEqual(s.knob_names, (
            "rOut_0", "rOut_1", "rOut_2",
            "hT_0", "hT_1", "hT_2",
            "f_0", "f_1", "f_2",
            "extent"))
        self.assertEqual(s.bounds_lo,
                         (50.0, 50.0, 50.0, 0.01, 0.01, 0.01, 0.0, 0.0, 0.0, 400.0))
        # extent max went 1100 -> 800 -> 950 -> 1100 over 2026-07-27/28, then
        # 1100 -> 1700 -> 2000 on 2026-08-02 after foilspf02 PINNED the 1100
        # bound (its two best new Pareto points both sat exactly on it). Every
        # step is worst-corner preflight measured: PASS at 0 overlaps through
        # 1700, FAIL at 1800; then with the massless EMC_Source walked
        # 5000 -> 4850, PASS at 1900 and 2000, FAIL at 2100. 2000 is the end of
        # the line -- past ~2042 the wall is DOWNSTREAM and material (ST_Out vs
        # protonabs1), not a relocatable VD. See
        # test_extent_ceiling_stays_inside_the_zero_overlap_corridor.
        self.assertEqual(s.bounds_hi,
                         (120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.95, 0.95, 0.95, 2000.0))
        self.assertEqual(s.int_dims, ())

    def test_extent_ceiling_stays_inside_the_zero_overlap_corridor(self):
        """The stack is CENTRE-pinned at z0 and grows SYMMETRICALLY, so the
        ceiling is set by whichever edge reaches a wall first -- not by a
        corridor width.

        This previously asserted `extent <= 6271 - vd` (= 1271), mixing the
        current upstream wall with 6271: the maximum target z_end from the
        OLD uncompensated regime, before the absorber was pinned to its own
        absolute position. That model is over-conservative and measurably
        wrong -- worst-corner preflight PASSes at 0 overlaps at extent 1700
        (upstream edge 5021) and only FAILs at 1800 (edge 4971) on
        EMC_Source, consistent with the symmetric model's 1742, not 1271.

        Walls: EMC_Source upstream (a 20um vacuum disc, relocated 5300 ->
        5000) and the proton absorber downstream (pinned at z=6901-7901
        regardless of extent). Both are derived from the spec's own rendered
        placement, so moving either cannot silently desync this.
        """
        s = _foilspf()
        x = [120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, 800.0]
        txt = s.geom.render(x)
        z0 = float(re.search(r"z0InMu2e = ([\d.]+)", txt).group(1))
        vd = float(re.search(r"zEMCSourceInMu2e = ([\d.]+)", txt).group(1))
        ipa = float(re.search(r"zStartInMu2e = ([\d.]+)", txt).group(1))
        ceiling = s.bounds_hi[s.knob_names.index("extent")]
        # upstream: z0 - extent/2 must stay clear of the (massless) VD
        self.assertLessEqual(ceiling, 2.0 * (z0 - vd))
        # downstream: z0 + extent/2 must stay clear of the pinned absorber
        self.assertLessEqual(ceiling, 2.0 * (ipa - z0))

    def test_target_position_is_fixed_and_the_absorber_is_compensated(self):
        """The target must NOT move. Offline places the IPA at
        targetEnd+distFromTargetEnd -- relative to the stopping target -- but the
        IPA is fixed hardware at z=6901-7901. An earlier fix (2026-07-28) slid the
        TARGET upstream to stop it squeezing the absorber; that was backwards. It
        distorted the object under study to work around a distortion in a fixed
        object. The correct fix holds the target still and compensates
        distFromTargetEnd so the absorber stays at its true absolute position.
        """
        s = _foilspf()
        self.assertNotIn("z0", s.knob_names)            # still 10D
        def rendered(ext):
            x = [120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, ext]
            txt = s.geom.render(x)
            z0 = float(re.search(r"z0InMu2e = ([\d.]+)", txt).group(1))
            d = float(re.search(r"distFromTargetEnd = ([\d.]+)", txt).group(1))
            return z0, d
        # the target centre never moves, at any extent
        for ext in (400.0, 800.0, 1100.0):
            self.assertAlmostEqual(rendered(ext)[0], 5871.0, places=3, msg=f"extent {ext}")
        # at the deployed span the compensation is a no-op: stock 625 exactly
        self.assertAlmostEqual(rendered(800.0)[1], 625.0, places=3)
        # targetEnd + distFromTargetEnd is invariant => absorber pinned in space
        base = 800.0 / 2 + rendered(800.0)[1]
        for ext in (400.0, 950.0, 1100.0):
            self.assertAlmostEqual(ext / 2 + rendered(ext)[1], base, places=3,
                                   msg=f"absorber moved at extent {ext}")

    def test_absolute_pin_and_expression_agree(self):
        """protonabsorber.zStartInMu2e is rendered (authoritative under the
        patched GeometryService) AND agrees with the distFromTargetEnd
        expression (the fail-safe a stale/unpatched lib falls back to).
        If the two mechanisms ever disagree, a lib swap silently moves the
        absorber -- that divergence must be a test failure, not a physics
        surprise. Evidence: docs/ipa_zstart_evidence.md."""
        s = _foilspf()
        for ext in (400.0, 800.0, 1100.0):
            x = [120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, ext]
            txt = s.geom.render(x)
            z = float(_scalar(txt, "protonabsorber.zStartInMu2e"))
            d = float(re.search(r"distFromTargetEnd = ([\d.]+)", txt).group(1))
            self.assertAlmostEqual(z, 6901.02, places=6, msg=f"extent {ext}")
            # targetEnd = z0 + extent/2 + 5 (tilt margin) + 0.02 (2*vdHL)
            self.assertAlmostEqual(5871.0 + ext / 2 + 5.02 + d, z, places=3,
                                   msg=f"mechanisms disagree at extent {ext}")

    def test_upstream_end_never_reaches_emc_source(self):
        """The other wall. At the ceiling the stack must stay clear of the VD,
        wherever the spec currently places it."""
        s = _foilspf()
        ext = s.bounds_hi[s.knob_names.index("extent")]
        x = [120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, ext]
        text = s.geom.render(x)
        z0 = float(re.search(r"z0InMu2e = ([\d.]+)", text).group(1))
        vd = float(re.search(r"zEMCSourceInMu2e = ([\d.]+)", text).group(1))
        self.assertGreater(z0 - ext / 2, vd)


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


class TestFixtures(unittest.TestCase):
    def test_the_nominal_fixture_renders_the_deployed_stack(self):
        s = st.load_study_file(ENGINE_STUDIES / "foilspf_nominal.json")
        self.assertEqual(s.knobs, ())
        text = s.geom.render([])
        self.assertEqual(geom_vector(text, "stoppingTarget.radii"), [75.0] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.halfThicknesses"),
                         [0.0528] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.holeRadii"),
                         [21.5] * 37)
        self.assertTrue(all(abs(z) < 1e-3 for z in
                            geom_vector(text, "stoppingTarget.zVars")))
        self.assertAlmostEqual(geom_double(text, "stoppingTarget.deltaZ"),
                               22.222222, places=6)
        self.assertAlmostEqual(
            geom_double(text, "protonabsorber.distFromTargetEnd"), 625.0,
            places=6)

    def test_the_fixtures_run_foilspfbpz_ax_steps(self):
        twin = doc(MODES / "foilspfbpz_ax.json")
        nominal = doc(ENGINE_STUDIES / "foilspf_nominal.json")
        local = doc(ENGINE_STUDIES / "foilspfbpz_local.json")
        self.assertEqual(nominal["evaluate"], twin["evaluate"])
        self.assertEqual(nominal["kits"], twin["kits"])
        self.assertEqual(local["kits"], twin["kits"])
        self.assertEqual(local["knobs"], twin["knobs"])
        for mine, theirs in zip(local["evaluate"], twin["evaluate"]):
            self.assertEqual({k: v for k, v in mine.items() if k != "fixed"},
                             {k: v for k, v in theirs.items() if k != "fixed"})
            if mine["kit"] == "anakit":
                self.assertEqual(mine["fixed"], theirs["fixed"])
            else:
                self.assertLess(mine["fixed"]["njobs"] * mine["fixed"]["events_per_job"],
                                theirs["fixed"]["njobs"] * theirs["fixed"]["events_per_job"])
        for fixture in (nominal, local):
            st.load_study_file(ENGINE_STUDIES / f"{fixture['name']}.json")


if __name__ == "__main__":
    unittest.main()
