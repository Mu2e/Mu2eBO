"""Recorded pre-check log shapes and GDML builders, shared by
tests/test_preflight_checks.py and tests/test_offline_preflight_kit.py.
Not a test module: unittest discovers test*.py only.

FATAL_LOG and ADVISORY_LOG are the foilsg06R00_00 preflight log shapes
(moved from tests/test_audit_fixes.py with G4_FATAL_RX); MANAGED_LOG uses
the volume name SURFACE_OVERLAP_MANAGED matches; each log ends the way
run_check joins stdout and stderr."""
import re

FATAL_LOG = (
    "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
    "... geometry construction ...\n"
    "-------- EEEE ------- G4Exception-START -------- EEEE -------\n"
    "*** G4Exception : GeomSolids0002\n"
    "      issued by : G4Tubs::G4Tubs()\n"
    "Invalid values for radii in solid: Foil_00\n"
    "        pRMin = 51.041, pRMax = 50\n"
    "*** Fatal Exception *** core dump ***\n"
)

# Advisory surface-check noise from a stock-geometry overlap.
ADVISORY_LOG = (
    "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
    "-------- WWWW ------- G4Exception-START -------- WWWW -------\n"
    "*** G4Exception : GeomVol1002\n"
    "      issued by : G4PVPlacement::CheckOverlaps()\n"
    "Overlap is detected for volume TT_MidInner\n"
    "-------- WWWW -------- G4Exception-END --------- WWWW -------\n"
    "Begin processing the 1st record\n"
    "Art has completed and will exit with status 0.\n"
)

CLEAN_LOG = (
    "Geant4 version Name: geant4-11-02-patch-01    (16-February-2024)\n"
    "%MSG-i MF_INIT_OK:  Early 26-Sep-2026 10:00:00 CDT JobSetup\n"
    "Begin processing the 1st record. run: 1803 subRun: 0 event: 1\n"
    "Art has completed and will exit with status 0.\n"
    "\n--- STDERR ---\n"
)

MANAGED_LOG = (
    "Begin processing the 1st record\n"
    "Overlap is detected for volume StoppingTargetFoil_07:0 (G4Tubs) with "
    "its mother volume StoppingTargetMother (G4Tubs)\n"
    "          protrusion at mother local point (0,0,0) by 1.2 mm\n"
    "Art has completed and will exit with status 0.\n"
)

# A construction error before art reached the event loop, not fatal-marked.
PRE_INIT_GEOM_LOG = (
    "Geant4 version Name: geant4-11-02-patch-01    (16-February-2024)\n"
    "-------- EEEE ------- G4Exception-START -------- EEEE -------\n"
    "*** G4Exception : GeomMgt0002\n"
    "      issued by : G4PVPlacement::G4PVPlacement()\n"
    "Volume VirtualDetector_TT_MidInner is outside mother DS2Vacuum\n"
    "-------- EEEE -------- G4Exception-END --------- EEEE -------\n"
)

# The env flake: `mu2e` never started.
NO_MU2E_LOG = "\n--- STDERR ---\nbash: line 1: mu2e: command not found\n"

GEOM = (
    "vector<double> stoppingTarget.radii          = { 100.0, 200.0 };\n"
    "vector<double> stoppingTarget.halfThicknesses = { 0.5, 0.25 };\n"
    "double stoppingTarget.holeRadius = 1.0e6;\n"
    "vector<double> stoppingTarget.holeRadii      = { 10.0, 0.0 };\n"
)


def gdml(tubes):
    """A GDML document holding the given (name, rmin, rmax, z, lunit)
    tubes."""
    items = "".join(
        f'<tube name="{n}" rmin="{rmin}" rmax="{rmax}" z="{z}" '
        f'lunit="{lunit}" deltaphi="6.28" aunit="rad"/>'
        for n, rmin, rmax, z, lunit in tubes)
    return f'<?xml version="1.0"?><gdml><solids>{items}</solids></gdml>'


def _vector(geom_text, key):
    m = re.search(rf"vector<double>\s+stoppingTarget\.{key}\s*=\s*"
                  rf"\{{([^}}]*)\}}", geom_text)
    return [float(v) for v in m.group(1).split(",")]


def gdml_matching(geom_text):
    """The GDML a correct G4 build of `geom_text`'s stopping target writes:
    one pointer-suffixed Foil_NN tube per foil (rIn = holeRadii[i], rOut =
    radii[i], full length = 2 * halfThicknesses[i])."""
    radii = _vector(geom_text, "radii")
    half = _vector(geom_text, "halfThicknesses")
    holes = _vector(geom_text, "holeRadii")
    return gdml([(f"Foil_{i:02d}0x55d1a2b3", holes[i], r, 2 * half[i], "mm")
                 for i, r in enumerate(radii)])
