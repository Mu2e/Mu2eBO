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
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from bo_driver import MODES  # noqa: E402
from mode_json import load_mode_file  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "modes"

# FoilsMode reads these; the JSON freezes them, so parity is defined at default.
_ENV_OVERRIDES = ("AUTORESEARCH_BASE_HOLE_RADIUS_MM",
                  "AUTORESEARCH_N_UP", "AUTORESEARCH_N_DOWN")

_ASSIGN_RX = re.compile(
    r"^\s*(?:bool|int|double|string|vector<double>|vector<string>)\s+"
    r"([A-Za-z0-9_.]+)\s*=\s*(.+?);\s*$")


def parse_assignments(text: str) -> dict:
    """geom text -> {key: normalised value string}. Comments and whitespace
    are dropped; every number is kept exactly as emitted."""
    out = {}
    for line in text.splitlines():
        line = line.split("//")[0]
        m = _ASSIGN_RX.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("{"):
            inner = val.strip("{} ").strip()
            val = "{" + ",".join(p.strip() for p in inner.split(",")) + "}"
        out[key] = val
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
        cls._saved = {k: os.environ.pop(k, None) for k in _ENV_OVERRIDES}
        cls.spec = load_mode_file(FIXTURES / f"{cls.mode_name}.json")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            if v is not None:
                os.environ[k] = v

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
        radii = parse_assignments(text)["stoppingTarget.radii"]
        self.assertEqual(len(radii.strip("{}").split(",")), 49)

    def test_poison_pill_scalar_survives(self):
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        self.assertEqual(
            parse_assignments(text)["stoppingTarget.holeRadius"], "1.0e6")


class TestFoilsflashParity(ParityMixin, unittest.TestCase):
    mode_name = "foilsflash"


class TestFoilsParity(ParityMixin, unittest.TestCase):
    mode_name = "foils"


if __name__ == "__main__":
    unittest.main()
