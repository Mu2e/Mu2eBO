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
from bo_driver import MODES, FoilsMode  # noqa: E402
from mode_json import load_mode_file  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "modes"

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
    "foils": [
        [120.0, 130.0, 0.10, 0.20, 15.0, 40.0],
        [50.0, 250.0, 0.01, 1.0, 0.0, 50.0],
        [175.5, 62.25, 0.5289, 0.0131, 33.75, 4.5],
        [250.0, 50.0, 1.0, 0.01, 50.0, 0.0],
    ],
}


class ParityMixin:
    """Renders the fixture and the Python mode of the same name, and requires
    the parsed assignments to match exactly."""
    mode_name = ""

    @classmethod
    def setUpClass(cls):
        # FoilsMode.BASE_HOLE_RADIUS_MM / FIXED_N_UP / FIXED_N_DOWN
        # (core/bo_driver.py:353,357-358) are CLASS attributes evaluated
        # from os.environ exactly once, at bo_driver import time -- which
        # happens during unittest discover's module-import pass, well
        # before this method ever runs. Popping the env vars here cannot
        # un-bake a value that is already materialised on the class, so a
        # pop/restore dance in setUpClass/tearDownClass would silently do
        # nothing (this was tried and looked like a fix; it wasn't -- it
        # only "passed" because the ambient shell happened not to set these).
        # The fixtures freeze base_hole=21.5, n_up=6, n_down=6, so parity is
        # only DEFINED while the live class is still at those same defaults.
        # Assert that precondition loudly instead of performing a no-op
        # cleanup that implies a guarantee it cannot provide.
        assert FoilsMode.BASE_HOLE_RADIUS_MM == 21.5, (
            f"FoilsMode.BASE_HOLE_RADIUS_MM == {FoilsMode.BASE_HOLE_RADIUS_MM}, "
            "not the 21.5 the fixtures freeze. This is a class attribute "
            "baked from AUTORESEARCH_BASE_HOLE_RADIUS_MM at bo_driver IMPORT "
            "time, so unsetting it mid-test cannot fix this -- unset "
            "AUTORESEARCH_BASE_HOLE_RADIUS_MM and start a fresh interpreter.")
        assert FoilsMode.FIXED_N_UP == 6, (
            f"FoilsMode.FIXED_N_UP == {FoilsMode.FIXED_N_UP}, not the 6 the "
            "fixtures freeze. Baked from AUTORESEARCH_N_UP at bo_driver "
            "IMPORT time -- unset it and start a fresh interpreter.")
        assert FoilsMode.FIXED_N_DOWN == 6, (
            f"FoilsMode.FIXED_N_DOWN == {FoilsMode.FIXED_N_DOWN}, not the 6 "
            "the fixtures freeze. Baked from AUTORESEARCH_N_DOWN at "
            "bo_driver IMPORT time -- unset it and start a fresh interpreter.")
        cls.spec = load_mode_file(FIXTURES / f"{cls.mode_name}.json")

    def test_same_geometry_as_python_renderer(self):
        python_mode = MODES[self.mode_name]
        for x in SAMPLE_X[self.mode_name]:
            want = parse_assignments(python_mode._geom_text(x))
            got = parse_assignments(self.spec.geom.render(x))
            self.assertEqual(set(want), set(got), f"key sets differ at x={x}")
            for key in want:
                self.assertEqual(want[key], got[key], f"{key} differs at x={x}")

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


class TestFoilsParity(ParityMixin, unittest.TestCase):
    mode_name = "foils"

    def test_comments_describe_absolute_hole_radii_not_fractions(self):
        """foils holes are absolute radii (extra_rIn_*, mm); only the
        foilsf/foilsflash family parameterises them as a fraction of that
        side's rOut. The fixture's header claimed the fraction semantics
        (F12)."""
        text = self.spec.geom.render(SAMPLE_X["foils"][0])
        comments = "\n".join(ln for ln in text.splitlines()
                             if ln.startswith("//"))
        self.assertNotIn("fraction", comments)
        self.assertNotIn("foilsflash", comments)


if __name__ == "__main__":
    unittest.main()
