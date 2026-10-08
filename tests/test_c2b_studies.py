"""The C2b engine twins of the foilspf studies (mode_specs/<name>_ax.json):
foilspfbpz_ax's geometry guards, the deployed-target baseline
mode_specs/foilspf_nominal.json and the local acceptance fixture (Phase C2b
spec, section 4). The originals were retired in Phase C3 and deleted on
2026-10-08, with the five twins that never ran; git history keeps them."""
import itertools
import json
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
TWINS = ("foilsflash_ax", "foilspfbpz_ax")
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2"
# M. MacKenzie's four analyses (docs/superpowers/specs/
# 2026-10-07-upstream-analyses-design.md, section 3).
STEPS = ["mubeam", "mustops_ce", "elebeam_flash", "stops", "ce_edep", "sob",
         "flash"]


def _anakit(step, files_from, fixed, params_from=None):
    return {"step": step, "kit": "anakit", "entry": None, "files": [],
            "files_from": files_from, "params": {},
            "params_from": params_from or {}, "fixed": fixed}


ANAKIT_STEPS = {
    "stops": _anakit("stops", ["mubeam"], {"analysis": "muon_stop_rate",
                                           "upstream_eff": 0.01278168}),
    "ce_edep": _anakit("ce_edep", ["mustops_ce"], {"analysis": "edep"}),
    "sob": _anakit("sob", ["ce_edep"],
                   {"analysis": "approx_ce_sensitivity",
                    "cosmic_rate_per_s_per_mev": 0.0018181818181818182},
                   {"stops_per_pot": "stops.stops_per_pot"}),
    "flash": _anakit("flash", ["elebeam_flash"], {"analysis": "edep"}),
}


def doc(path):
    return json.loads(Path(path).read_text())


class TestTwinFacts(unittest.TestCase):
    """What makes each file an MDC2025ax engine twin (Phase C2b spec): the
    release's code tarball and run label, the anakit analyses with their
    constants, and its own v2 board. The comparison against the originals
    went with them in Phase C3; these are the twin-side facts it used to
    pin."""

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
                self.assertEqual(kits["anakit"], {"musing": "SimJob MDC2025ay"})
                self.assertEqual([s["step"] for s in twin["evaluate"]], STEPS)
                steps = {s["step"]: s for s in twin["evaluate"]}
                for name_, want in ANAKIT_STEPS.items():
                    self.assertEqual(steps[name_], want, name_)

    def test_each_twin_writes_its_own_v2_board(self):
        for name in TWINS:
            with self.subTest(study=name):
                board = doc(MODES / f"{name}.json")["leaderboard"]
                self.assertEqual(board["file"],
                                 f"leaderboards/leaderboard_bo_{name}_upstream.tsv")
                self.assertEqual(board["layout"], "v2")

    def test_the_objectives_read_michaels_metrics(self):
        for name in TWINS:
            with self.subTest(study=name):
                objs = modes.STUDIES[name].objectives
                self.assertEqual(tuple(o.metric for o in objs),
                                 ("sob.sensitivity",
                                  "flash.avg_trk_edep_per_gen_event_mev"))
                # log10 on flash: a zero flash is a failed evaluation in
                # core/score.py, never a row (the fork's analysis refused it
                # itself; his edep returns it).
                self.assertEqual(tuple(o.transform for o in objs),
                                 ("none", "log10"))

    def test_the_flash_budget_is_per_generated_electron(self):
        # The per-POT budget 6.50684e-07 times POT per resampled electron.
        self.assertLess(abs(7.506758e-06 - 6.50684e-07 * 11.536718606512062),
                        1e-12)
        for name in TWINS:
            with self.subTest(study=name):
                self.assertEqual(doc(MODES / f"{name}.json")["constraints"],
                                 [{"name": "flash_edep", "max": 7.506758e-06,
                                   "k_sigma": 1.0}])


class TestSpotFacts(unittest.TestCase):
    """Load-bearing values pinned individually -- the ones with incident
    history or active standards behind them (moved onto the loaded _ax
    studies in Phase C3, when the originals were archived)."""

    def test_obs_noise_is_the_replicate_measured_sigma(self):
        # Free MLL noise ranked the best-ever eval 16th of 324
        # (wiki/incidents/gp-free-noise-erases-champion.md).
        # sob: 0.006 (replicate-measured on the old scale) times 0.3474, the
        # new/old sensitivity at bpzax01R12_00 re-analysed on M. MacKenzie's
        # analyses (1.32707 / 3.82018, 2026-10-07), rounded to 0.0021; to be
        # re-measured from replicates.
        for name in TWINS:
            with self.subTest(study=name):
                self.assertEqual(
                    tuple(o.noise for o in modes.STUDIES[name].objectives),
                    (0.0021, 0.010))

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


# --- foilspfbpz_ax's geometry ----------------------------------------------
# The geometry guards that do not depend on a knob box, moved here from
# tests/test_foilspf_spec.py in Phase C3 and re-pointed to foilspfbpz_ax when
# the foilspf twin with an extent knob was deleted (2026-10-08). foilspfbpz_ax
# pins the extent at 1066.666667 mm (48 gaps of the deployed pitch) and has a
# zmid knob instead.
# Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md
N_FOILS = 49
# rOut, hT, f control points all equal (a flat profile), zmid 0.
FLAT = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 0.0]
EXTENT = 1066.666667


def _bpz():
    return modes.STUDIES["foilspfbpz_ax"]


def _render(x):
    return _bpz().geom.render(x)


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


class TestFoilspfbpzGeometry(unittest.TestCase):

    def test_the_knobs(self):
        self.assertEqual(_bpz().knob_names, (
            "rOut_0", "rOut_1", "rOut_2", "hT_0", "hT_1", "hT_2",
            "f_0", "f_1", "f_2", "zmid"))

    def test_every_per_foil_vector_has_49_entries(self):
        text = _render(FLAT)
        for key in ("stoppingTarget.radii",
                    "stoppingTarget.halfThicknesses",
                    "stoppingTarget.holeRadii",
                    "stoppingTarget.zVars"):
            self.assertEqual(len(_vec(text, key)), N_FOILS, key)

    def test_flat_control_points_render_a_flat_stack(self):
        """All three control points equal => a flat profile, centred at z0
        with no foil shifted. If this drifts, every comparison against the
        deployed target is meaningless."""
        text = _render(FLAT)
        self.assertEqual(set(_vec(text, "stoppingTarget.radii")), {75.0})
        self.assertEqual(set(_vec(text, "stoppingTarget.halfThicknesses")), {0.0528})
        self.assertEqual(set(_vec(text, "stoppingTarget.holeRadii")), {21.525})
        self.assertTrue(all(abs(z) < 1e-3 for z in
                            _vec(text, "stoppingTarget.zVars")))
        self.assertEqual(_scalar(text, "stoppingTarget.z0InMu2e"), "5871.0000")
        self.assertEqual(_scalar(text, "stoppingTarget.deltaZ"), "22.222222")

    def test_a_bent_profile_is_not_flat(self):
        """Guards against a wiring bug where all three control points feed
        the same slot and every profile silently renders flat."""
        x = [50.0, 85.0, 120.0] + FLAT[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertAlmostEqual(r[0], 50.0, places=3)
        self.assertAlmostEqual(r[48], 120.0, places=3)
        self.assertGreater(r[24], r[0])

    def test_clip_projects_the_quadratic_overshoot(self):
        """A quadratic through in-bounds control points overshoots BETWEEN
        them: (50, 150, 150) peaks at 162.5 at i=36. The clip must project
        it onto 150 rather than emit an out-of-bounds radius."""
        x = [50.0, 150.0, 150.0] + FLAT[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertLessEqual(max(r), 150.0)
        self.assertAlmostEqual(r[36], 150.0, places=4)

    def test_hole_is_strictly_inside_the_foil_at_every_bound_corner(self):
        """rIn < rOut must hold everywhere, or G4Tubs aborts. 64 corners of
        the (rOut, f) sub-box."""
        worst = float("inf")
        for c in itertools.product((30.0, 150.0), repeat=3):
            for f in itertools.product((0.0, 0.95), repeat=3):
                text = _render(list(c) + [0.0528] * 3 + list(f) + [0.0])
                rout = _vec(text, "stoppingTarget.radii")
                rin = _vec(text, "stoppingTarget.holeRadii")
                worst = min(worst, min(a - b for a, b in zip(rout, rin)))
        self.assertGreater(worst, 0.0)

    def test_absolute_pin_and_expression_agree(self):
        """protonabsorber.zStartInMu2e is rendered (authoritative under the
        patched GeometryService) AND agrees with the distFromTargetEnd
        expression (the fail-safe a stale/unpatched lib falls back to).
        If the two mechanisms ever disagree, a lib swap silently moves the
        absorber -- that divergence must be a test failure, not a physics
        surprise. Evidence: docs/ipa_zstart_evidence.md."""
        txt = _render(FLAT)
        z = float(_scalar(txt, "protonabsorber.zStartInMu2e"))
        d = float(_scalar(txt, "protonabsorber.distFromTargetEnd"))
        self.assertAlmostEqual(z, 6901.02, places=6)
        # targetEnd = z0 + extent/2 + 5 (tilt margin) + 0.02 (2*vdHL)
        self.assertAlmostEqual(5871.0 + EXTENT / 2 + 5.02 + d, z, places=3)

    def test_poison_pill_survives_the_json_number_grammar(self):
        """1.0e6 must reach the geometry verbatim. Rendered as 1000000.0 it
        still crashes, but the intent is unreadable; rendered as a
        'sensible' scalar it would silently build a uniform-hole stack --
        which is how 62 foilsg rows were lost."""
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;",
                      _render(FLAT))

    def test_no_geometry_key_is_emitted_twice(self):
        """Duplicate keys are last-write-wins in SimpleConfig, silently.
        GeomTemplate rejects duplicates at load, so this asserts the shipped
        render actually exercises that guarantee."""
        keys = []
        for line in _render(FLAT).splitlines():
            if line.startswith("//") or line.startswith("#") or not line.strip():
                continue
            keys.append(line.split(" = ")[0].split(" ", 1)[1])
        self.assertEqual(sorted(keys), sorted(set(keys)))


class TestFixtures(unittest.TestCase):
    def test_the_nominal_study_renders_the_deployed_stack(self):
        s = modes.STUDIES["foilspf_nominal"]
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
        nominal = doc(MODES / "foilspf_nominal.json")
        local = doc(ENGINE_STUDIES / "foilspfbpz_local.json")
        self.assertEqual(nominal["evaluate"], twin["evaluate"])
        self.assertEqual(nominal["kits"], twin["kits"])
        self.assertEqual(local["kits"], twin["kits"])
        self.assertEqual(local["knobs"], twin["knobs"])
        for fixture in (nominal, local):
            self.assertEqual([o["metric"] for o in fixture["objectives"]],
                             [o["metric"] for o in twin["objectives"]])
            self.assertEqual(fixture["constraints"], twin["constraints"])
            # A new measurement, a new board (as the twins): the old board
            # holds rows of the fork's measure_sha, so a launch onto it is
            # refused.
            self.assertEqual(
                fixture["leaderboard"]["file"],
                f"leaderboards/leaderboard_{fixture['name']}_upstream.tsv")
        for mine, theirs in zip(local["evaluate"], twin["evaluate"]):
            self.assertEqual({k: v for k, v in mine.items() if k != "fixed"},
                             {k: v for k, v in theirs.items() if k != "fixed"})
            if mine["kit"] == "anakit":
                self.assertEqual(mine["fixed"], theirs["fixed"])
            else:
                self.assertLess(mine["fixed"]["njobs"] * mine["fixed"]["events_per_job"],
                                theirs["fixed"]["njobs"] * theirs["fixed"]["events_per_job"])
        st.load_study_file(MODES / "foilspf_nominal.json")
        st.load_study_file(ENGINE_STUDIES / "foilspfbpz_local.json")


class TestTheChainRuns(unittest.TestCase):
    """Each _ax study's real seven steps through run_steps with a scripted
    kit: the producers run first, each anakit step reads the files of the
    step it names in files_from, and sob gets the stops step's
    stops_per_pot through params_from."""

    def test_each_twin_wires_its_seven_steps(self):
        import tempfile
        import time
        import scheduler as sch
        from tests.test_scheduler import FakeKit, Kits
        geom = {"name": "geom", "uri": "file:///tmp/geom", "kind": "geom"}
        for name in TWINS:
            with self.subTest(study=name), \
                    tempfile.TemporaryDirectory() as tmp:
                study = modes.STUDIES[name]
                x = [(lo + hi) / 2 for lo, hi in zip(study.bounds_lo,
                                                     study.bounds_hi)]
                kit = FakeKit(metrics={"stops": {"stops_per_pot": 1.26e-3}})
                out = sch.run_steps(
                    study, config="c", state_dir=Path(tmp) / "state",
                    env=study.geom.derived_env(x), files={"geom": geom},
                    kits=Kits(kit), workflow=lambda s: f"camp/c/{s}",
                    sleep=lambda s: time.sleep(0.001), log=lambda m: None)
                self.assertEqual(sorted(out), sorted(STEPS))
                bad = {s: o.message for s, o in out.items() if not o.ok}
                self.assertEqual(bad, {})
                ev = kit.events
                for consumer, producers in (
                        ("stops", ["mubeam"]), ("ce_edep", ["mustops_ce"]),
                        ("sob", ["stops", "ce_edep"]),
                        ("flash", ["elebeam_flash"])):
                    for producer in producers:
                        self.assertGreater(ev.index(("submit", consumer)),
                                           ev.index(("done", producer)),
                                           f"{consumer} after {producer}")
                sub = {n.split(".", 1)[1]: (params, inputs)
                       for n, params, _, inputs, _ in kit.submits}
                for consumer, producer in (("stops", "mubeam"),
                                           ("ce_edep", "mustops_ce"),
                                           ("sob", "ce_edep"),
                                           ("flash", "elebeam_flash")):
                    self.assertEqual([f["name"] for f in sub[consumer][1]],
                                     [producer], consumer)
                    self.assertEqual(sub[consumer][0]["musing"],
                                     "SimJob MDC2025ay")
                sob = sub["sob"][0]
                self.assertEqual(sob["stops_per_pot"], 1.26e-3)
                self.assertEqual(sob["analysis"], "approx_ce_sensitivity")
                self.assertEqual(sob["cosmic_rate_per_s_per_mev"],
                                 0.0018181818181818182)


if __name__ == "__main__":
    unittest.main()
