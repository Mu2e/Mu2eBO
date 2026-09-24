"""Acceptance test: the live foilsflash spec must render the SAME GEOMETRY as
the frozen golden captures of the Python renderer it replaced.

Semantic equality, not byte equality. Byte equality would force the JSON to
reproduce cosmetic alignment (the renderer pads stoppingTarget.radii so '='
lines up with halfThicknesses), non-ASCII comment characters, and an inherited
header calling foilsflash "foils mode v2, 6D" -- none of which reaches Geant4.

Import convention: bare `bo_driver` via sys.path.insert, matching
tests/test_modes.py, tests/test_study.py, and tests/test_json_mode.py -- NOT
`from core import bo_driver`. A qualified import here would load a SECOND,
non-identical `core.modes` module alongside the bare one bo_driver.py itself
uses (the two-non-identical-classes bug Task 4 fixed for GeomTemplate -- see
core/modes.py's tail comment), and tests.test_modes.TestSingleModeSpecClass
asserts "core.modes" never lands in sys.modules across the whole suite.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from bo_driver import MODES  # noqa: E402


# Frozen captures of the Python renderer, taken 2026-07-26 while
# FoilsFlashMode still existed and verified equal BEFORE it was deleted --
# which is what makes them trustworthy. No Python renderer survives
# (ModeSpec.geom is required and built from the study's own `geom`), so the
# goldens are the sole oracle. Never regenerate them: rebuilding a golden from
# the JSON spec turns parity into a tautology.
GOLDEN = Path(__file__).parent / "fixtures" / "golden_geom"

# Captures the FHiCL type keyword (group 1), not just the key/value (groups
# 2/3): a spec line whose type disagrees with the renderer -- e.g. `int`
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
# are most likely to diverge. Index i pairs with golden foilsflash_<i>.txt.
SAMPLE_X = [
    [120.0, 130.0, 0.10, 0.20, 0.30, 0.40],
    [50.0, 250.0, 0.002, 1.0, 0.0, 0.95],
    [175.5, 62.25, 0.5289, 0.0031, 0.7654, 0.1234],
    [250.0, 50.0, 1.0, 0.002, 0.95, 0.0],
]


class TestFoilsflashGoldenParity(unittest.TestCase):
    """mode_specs/foilsflash.json, reached through MODES as production
    reaches it, against the frozen goldens."""

    def render(self, x):
        return MODES["foilsflash"]._geom_text(x)

    def test_live_spec_renders_the_golden(self):
        """Editing mode_specs/foilsflash.json's geometry off the proven-equal
        baseline is exactly the mistake that would otherwise reach the grid.
        Every golden line is compared with its FHiCL type, so the
        `double stoppingTarget.holeRadius = 1.0e6;` poison pill (the scalar
        an unpatched StoppingTargetMaker would read) is pinned here too."""
        for i, x in enumerate(SAMPLE_X):
            golden = GOLDEN / f"foilsflash_{i}.txt"
            self.assertTrue(golden.exists(), f"missing golden {golden}")
            want = parse_assignments(golden.read_text())
            got = parse_assignments(self.render(x))
            self.assertEqual(set(want), set(got), f"key sets differ at x={x}")
            for key in want:
                self.assertEqual(
                    want[key], got[key],
                    f"{key} differs from golden foilsflash_{i}.txt at x={x} "
                    f"-- the shipped spec drifted off the proven-equal "
                    f"baseline; do NOT re-capture")

    def test_the_49_numbers_are_all_compared(self):
        """Guards the guard: a vector really does carry 49 entries."""
        _type, radii = parse_assignments(
            self.render(SAMPLE_X[0]))["stoppingTarget.radii"]
        self.assertEqual(len(radii.strip("{}").split(",")), 49)

    def test_header_comment_names_this_mode(self):
        """F12: the rendered header comment travels into the geometry file of
        every line cloned from this spec, and parse_assignments (rightly)
        ignores comments -- so nothing else pins it. A cloned fixture once
        opened with '=== foilsflash (6D, hole = fraction of that side's
        rOut) ===': wrong mode name AND wrong semantics."""
        header = next(ln for ln in self.render(SAMPLE_X[0]).splitlines()
                      if ln.startswith("//"))
        m = re.match(r"^// === (\S+) ", header)
        self.assertIsNotNone(m, f"unrecognised header comment: {header!r}")
        self.assertEqual(m.group(1), "foilsflash", header)


if __name__ == "__main__":
    unittest.main()
