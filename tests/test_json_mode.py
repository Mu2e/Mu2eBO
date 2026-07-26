"""JsonMode: the single generic driver class behind every JSON-defined mode.

Import convention: bare `modes`/`bo_driver`/`mode_json` via sys.path.insert,
matching tests/test_modes.py and tests/test_mode_json.py -- NOT `from core
import modes`. bo_driver.py itself does `import modes as _modes` (bare); a
qualified `from core import modes` here would load a SECOND, non-identical
`core.modes` module alongside it (the two-non-identical-classes bug Task 4
fixed for GeomTemplate -- see core/modes.py's tail comment), and
tests.test_mode_json.TestSingleModeSpecClass asserts "core.modes" never
lands in sys.modules across the whole suite.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
from bo_driver import JsonMode  # noqa: E402
from mode_json import load_mode_file  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "modes" / "foilsflash.json"


class TestJsonMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Register under a non-colliding name so SPECS/MODES stay clean.
        # addClassCleanup (not tearDownClass) so the pop still runs even if
        # JsonMode(...) itself raises partway through setUpClass -- a plain
        # tearDownClass is SKIPPED by unittest when setUpClass raises, which
        # would leak "demoflash" into the process-global modes.SPECS for the
        # rest of `unittest discover`.
        cls.spec = dataclasses.replace(load_mode_file(FIXTURE), name="demoflash")
        modes.SPECS["demoflash"] = cls.spec
        cls.addClassCleanup(modes.SPECS.pop, "demoflash", None)
        cls.mode = JsonMode("demoflash")

    def test_knob_names_and_space_come_from_the_spec(self):
        self.assertEqual(self.mode.KNOB_NAMES, self.spec.knob_names)
        space = self.mode.build_space()
        self.assertEqual(len(space), 6)
        self.assertEqual(space[0].low, 50.0)
        self.assertEqual(space[0].high, 250.0)

    def test_geom_text_renders(self):
        text = self.mode._geom_text([120.0, 130.0, 0.1, 0.2, 0.3, 0.4])
        self.assertIn("#include", text)
        self.assertIn("stoppingTarget.radii", text)
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;", text)

    def test_no_priors(self):
        self.assertEqual(self.mode.load_priors(), [])

    def test_parse_geom_refuses_clearly(self):
        with self.assertRaises(NotImplementedError) as cm:
            self.mode.parse_geom("anything")
        self.assertIn("demoflash", str(cm.exception))

    def test_extract_metrics_uses_the_fallback_chain(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}),
            (3.9, 1e-6))
        # falls through to the second key when the first is absent
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_event": 2e-6}),
            (3.9, 2e-6))

    def test_extract_metrics_missing_key_names_the_column(self):
        with self.assertRaises(KeyError) as cm:
            self.mode.extract_metrics({"s_over_sqrt_b": 3.9})
        self.assertIn("flash_edep", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
