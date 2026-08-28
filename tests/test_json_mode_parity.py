"""Acceptance test: a JSON mode must produce the SAME GEOMETRY as the Python
renderer it reproduces.

Semantic equality, not byte equality. Byte equality would force the JSON to
reproduce cosmetic alignment (the renderer pads stoppingTarget.radii so '='
lines up with halfThicknesses), non-ASCII comment characters, and an inherited
header calling foilsflash "foils mode v2, 6D" -- none of which reaches Geant4.

Import convention: bare `bo_driver`/`mode_json` via sys.path.insert, matching
tests/test_modes.py, tests/test_mode_json.py, and tests/test_json_mode.py --
NOT `from core import bo_driver`/`from core.mode_json import ...`. A
qualified import here would load a SECOND, non-identical `core.modes` module
alongside the bare one bo_driver.py itself uses (the two-non-identical-classes
bug Task 4 fixed for GeomTemplate -- see core/modes.py's tail comment), and
tests.test_mode_json.TestSingleModeSpecClass asserts "core.modes" never lands
in sys.modules across the whole suite.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes as _modes  # noqa: E402
from bo_driver import MODES  # noqa: E402
from mode_json import load_mode_file  # noqa: E402


def has_python_renderer(mode: str) -> bool:
    """May this mode's golden be regenerated from live code?

    True only while a *Python* renderer still produces it. This is a REGISTRY
    fact -- `ModeSpec.geom` is non-None exactly for JSON-defined modes
    (core/modes.py) -- and must never be an attribute check:
    `hasattr(m, "_geom_text")` is True for every mode alive, because BOMode
    declares `_geom_text` abstract and JsonMode implements it from the JSON
    geom template. The attribute form silently stopped skipping JSON modes
    when foilsflash went JSON-only (2026-07-26), which would have let
    tools/capture_golden_geom.py rebuild those goldens from the very spec
    they exist to verify. Shared with that tool; pinned below by
    test_regeneration_guard_uses_the_registry_not_an_attribute.
    """
    spec = _modes.SPECS.get(mode)
    return MODES.get(mode) is not None and spec is not None and spec.geom is None

FIXTURES = Path(__file__).parent / "fixtures" / "modes"
# Frozen captures of the Python renderers, taken 2026-07-26 while every Python
# mode still existed. Re-capture with tools/capture_golden_geom.py if a
# surviving Python renderer legitimately changes.
GOLDEN = Path(__file__).parent / "fixtures" / "golden_geom"

# Captures the FHiCL type keyword (group 1), not just the key/value (groups
# 2/3): a fixture line whose type disagrees with the renderer -- e.g. `int`
# where the renderer emits `double` -- must NOT compare equal just because
# the numeric text matches. See wiki/incidents (Task 8 fix round 1): both
# fixtures originally declared `"type": "int"` for ds2.halfLength while
# FoilsMode._geom_text emits `double ds2.halfLength = 3825;`, and a
# non-capturing type group let that divergence through silently.
_ASSIGN_RX = re.compile(
    r"^\s*(bool|int|double|string|vector<double>|vector<string>)\s+"
    r"([A-Za-z0-9_.]+)\s*=\s*(.+?);\s*$")


def parse_assignments(text: str) -> dict:
    """geom text -> {key: (type, normalised value string)}. Comments and
    whitespace are dropped; every number is kept exactly as emitted, and the
    FHiCL type keyword travels with the value so a type mismatch fails."""
    out = {}
    for line in text.splitlines():
        line = line.split("//")[0]
        m = _ASSIGN_RX.match(line)
        if not m:
            continue
        type_, key, val = m.group(1), m.group(2), m.group(3).strip()
        if val.startswith("{"):
            inner = val.strip("{} ").strip()
            val = "{" + ",".join(p.strip() for p in inner.split(",")) + "}"
        out[key] = (type_, val)
    return out


# Interior point plus both box corners: corners are where formats and clipping
# are most likely to diverge.
SAMPLE_X = {
    "foilsflash": [
        [120.0, 130.0, 0.10, 0.20, 0.30, 0.40],
        [50.0, 250.0, 0.002, 1.0, 0.0, 0.95],
        [175.5, 62.25, 0.5289, 0.0031, 0.7654, 0.1234],
        [250.0, 50.0, 1.0, 0.002, 0.95, 0.0],
    ],
    # "foils" removed 2026-08-08: FoilsMode was archived (not converted to a
    # JSON mode -- the whole "foils" line was retired, per
    # docs/superpowers/specs/2026-08-08-leaderboard-module-design.md), so
    # TestFoilsParity below (which compared FoilsMode's live renderer against
    # a would-be JSON replacement) no longer has a subject. Its frozen
    # golden captures (fixtures/golden_geom/foils_*.txt) are left in place as
    # a historical record of the retired Python renderer's output.
}


class ParityMixin:
    """Renders the fixture and the Python mode of the same name, and requires
    the parsed assignments to match exactly."""
    mode_name = ""

    @classmethod
    def setUpClass(cls):
        # Used to also assert FoilsMode's env-driven class attributes
        # (BASE_HOLE_RADIUS_MM/FIXED_N_UP/FIXED_N_DOWN) matched the fixtures'
        # frozen assumptions -- moot since FoilsMode (and the "foils" line
        # entirely) was archived 2026-08-08; no Python renderer survives to
        # diverge from the golden captures. See TestFoilsParity's removal
        # note by SAMPLE_X above.
        cls.spec = load_mode_file(FIXTURES / f"{cls.mode_name}.json")

    def test_same_geometry_as_python_renderer(self):
        """Compares against the FROZEN golden capture of the Python renderer,
        not the live class.

        The oracle had to become data: retiring a Python mode (FoilsFlashMode,
        2026-07-26) deletes the very renderer this test compares against, so a
        live-object oracle would have to be deleted WITH it -- silently taking
        the parity proof along. The goldens in fixtures/golden_geom/ were
        captured from the Python renderers while they still existed, so parity
        remains provable for a mode whose Python implementation is gone.
        `test_golden_still_matches_the_live_python_mode` keeps the goldens
        honest for as long as a Python counterpart survives.
        """
        for i, x in enumerate(SAMPLE_X[self.mode_name]):
            golden = GOLDEN / f"{self.mode_name}_{i}.txt"
            self.assertTrue(golden.exists(), f"missing golden {golden}")
            want = parse_assignments(golden.read_text())
            got = parse_assignments(self.spec.geom.render(x))
            self.assertEqual(set(want), set(got), f"key sets differ at x={x}")
            for key in want:
                self.assertEqual(want[key], got[key], f"{key} differs at x={x}")

    def test_golden_still_matches_the_live_python_mode(self):
        """A frozen oracle can rot: if the Python mode still exists and its
        renderer changes, the golden must be re-captured, not silently left
        behind. Skips once the Python mode is retired -- at which point the
        golden IS the definition.

        The skip MUST key on the registry (`capture_golden_geom
        .has_python_renderer`), not on `hasattr(mode, "_geom_text")`: that
        attribute is present on every mode alive, so the old form stopped
        skipping when foilsflash went JSON-only (2026-07-26) and this test
        quietly became a golden-vs-JSON comparison while still reporting
        "STALE vs the live Python renderer -- re-capture it" on failure --
        advice that would have rebuilt the golden from the spec it verifies.
        """
        if not has_python_renderer(self.mode_name):
            self.skipTest(f"{self.mode_name} is JSON-defined or retired; the "
                          "golden is the sole oracle and must not be recaptured")
        python_mode = MODES[self.mode_name]
        for i, x in enumerate(SAMPLE_X[self.mode_name]):
            want = parse_assignments((GOLDEN / f"{self.mode_name}_{i}.txt").read_text())
            live = parse_assignments(python_mode._geom_text(x))
            self.assertEqual(want, live,
                             f"golden {self.mode_name}_{i}.txt is STALE vs the "
                             f"live Python renderer at x={x} -- re-capture it")

    def test_production_spec_still_matches_the_golden(self):
        """The PRODUCTION spec (mode_specs/<mode>.json, reached via MODES) must
        render the golden too -- not just the test fixture that
        test_same_geometry_as_python_renderer checks.

        This ran only by accident until 2026-08-02: the broken hasattr guard
        above let JSON modes fall through, so the shipped spec was being
        compared under the name of the staleness test. The coverage is real
        and worth keeping -- editing mode_specs/<mode>.json's geometry away
        from the proven-equal baseline is exactly the mistake that would
        otherwise reach the grid -- so it is now its own honest test.
        """
        if has_python_renderer(self.mode_name):
            self.skipTest(f"{self.mode_name} is Python-defined; it has no "
                          "mode_specs/*.json to check")
        shipped = MODES[self.mode_name]
        for i, x in enumerate(SAMPLE_X[self.mode_name]):
            want = parse_assignments((GOLDEN / f"{self.mode_name}_{i}.txt").read_text())
            got = parse_assignments(shipped._geom_text(x))
            self.assertEqual(want, got,
                             f"mode_specs/{self.mode_name}.json renders "
                             f"differently from golden {self.mode_name}_{i}.txt "
                             f"at x={x} -- the shipped spec drifted off the "
                             f"proven-equal baseline; do NOT re-capture")

    def test_regeneration_guard_uses_the_registry_not_an_attribute(self):
        """Pins the guard whose silent failure this whole file depends on.

        `hasattr(m, "_geom_text")` cannot discriminate -- assert that it is
        True even for a JSON mode -- so the guard must read ModeSpec.geom.
        """
        self.assertTrue(hasattr(MODES[self.mode_name], "_geom_text"),
                        "every live mode has _geom_text; an attribute check "
                        "can never mean 'has a Python renderer'")
        is_json = _modes.SPECS[self.mode_name].geom is not None
        self.assertEqual(has_python_renderer(self.mode_name), not is_json)

    def test_the_49_numbers_are_all_compared(self):
        """Guards the guard: a vector really does carry 49 entries."""
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        _type, radii = parse_assignments(text)["stoppingTarget.radii"]
        self.assertEqual(len(radii.strip("{}").split(",")), 49)

    def test_header_comment_names_this_mode(self):
        """F12: the rendered header comment travels into the geometry file of
        every line cloned from this fixture, and parse_assignments (rightly)
        ignores comments -- so nothing pinned it. tests/fixtures/modes/
        foils.json opened with '=== foilsflash (6D, hole = fraction of that
        side's rOut) ===': wrong mode name AND wrong semantics."""
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        header = next(ln for ln in text.splitlines() if ln.startswith("//"))
        m = re.match(r"^// === (\S+) ", header)
        self.assertIsNotNone(m, f"unrecognised header comment: {header!r}")
        self.assertEqual(m.group(1), self.mode_name, header)

    def test_poison_pill_scalar_survives(self):
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        self.assertEqual(
            parse_assignments(text)["stoppingTarget.holeRadius"],
            ("double", "1.0e6"))


class TestFoilsflashParity(ParityMixin, unittest.TestCase):
    mode_name = "foilsflash"


# TestFoilsParity (mode_name="foils") removed 2026-08-08: FoilsMode was
# archived along with the other four dormant Python-mode adapters, and
# "foils" was never converted to a JSON mode -- the whole line was retired,
# not migrated. See SAMPLE_X's removal note above.


if __name__ == "__main__":
    unittest.main()
