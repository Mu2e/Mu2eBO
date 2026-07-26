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
import argparse
import csv
import dataclasses
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
import bo_driver  # noqa: E402
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

    # -- Critical: the second objective must never silently collapse to a
    # poison zero row (mirrors FoilsFlashMode.extract_metrics's SystemExit
    # guard, which JsonMode lacked entirely).
    def test_extract_metrics_zero_second_metric_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0})
        msg = str(cm.exception)
        self.assertIn("demoflash", msg)
        self.assertIn("flash_edep_per_pot", msg)

    def test_extract_metrics_negative_second_metric_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": -1e-6})
        self.assertIn("flash_edep_per_pot", str(cm.exception))

    def test_extract_metrics_valid_second_metric_passes(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}),
            (3.9, 1e-6))

    def test_extract_metrics_calo_per_pot_no_longer_a_fallback(self):
        """Root-cause regression: the fixture's flash_edep fallback chain
        used to list calo_per_pot -- copied from the STALE comment above
        FoilsFlashMode.extract_metrics, which claims that fallback but never
        implements it. A calo-only summary must raise (missing key), not
        silently write calo into the flash column."""
        with self.assertRaises(KeyError) as cm:
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "calo_per_pot": 1.2e-6})
        self.assertIn("flash_edep", str(cm.exception))


class TestJsonModeEvaluateEndToEnd(unittest.TestCase):
    """F1: a JSON-defined mode must be able to LAND A LEADERBOARD ROW.

    Every earlier test in this file stops at a seam. The defect they all
    missed lived in `cmd_evaluate`, which called `mode.parse_geom(...)`
    unconditionally -- JsonMode raises NotImplementedError there, which is
    NOT in cmd_evaluate's `except (KeyError, TypeError)`. Propose, preflight,
    submit, ~4.5h of grid and harvest all succeed; evaluate then dies and
    graph/pipeline_io.run_evaluate records a zero-row for every child. This
    test drives the REAL cmd_evaluate against a scratch leaderboard and
    asserts the row is actually there.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jsonmode_eval_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Unique name: the probe is registered into the process-global
        # modes.SPECS / bo_driver.MODES, and tests/test_modes.py asserts
        # those two keysets are equal -- so both registrations are undone by
        # addCleanup even if this setUp raises partway through.
        self.name = "evalprobe" + uuid.uuid4().hex[:8]
        spec = dataclasses.replace(load_mode_file(FIXTURE), name=self.name)
        modes.SPECS[self.name] = spec
        self.addCleanup(modes.SPECS.pop, self.name, None)
        mode = JsonMode(self.name)
        # Never touch a real leaderboard under leaderboards/.
        mode.leaderboard = self.tmp / f"leaderboard_bo_{self.name}.tsv"
        mode.proposal_dir = self.tmp / "proposals"
        bo_driver.MODES[self.name] = mode
        self.addCleanup(bo_driver.MODES.pop, self.name, None)
        self.mode = mode

    def _args(self, config_name, summary_path, alpha=1.0e5, emit_json=None):
        return argparse.Namespace(
            mode=self.name, summary=str(summary_path),
            config_name=config_name, alpha=alpha, emit_json=emit_json)

    def _summary(self, payload) -> Path:
        p = self.tmp / "summary.json"
        p.write_text(json.dumps(payload))
        return p

    def test_evaluate_appends_a_leaderboard_row(self):
        x = [120.0, 130.0, 0.1, 0.2, 0.3, 0.4]
        self.mode.render_proposal("PROBE01", x)
        self.mode.append_pending("PROBE01", x, 1.0e5)
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        rc = bo_driver.cmd_evaluate(self._args("PROBE01", summary))

        self.assertEqual(rc, 0, "evaluate must succeed for a JSON mode")
        self.assertTrue(self.mode.leaderboard.exists(),
                        "no leaderboard file was written")
        with self.mode.leaderboard.open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["config"], "PROBE01")
        self.assertAlmostEqual(float(row["sob"]), 3.9, places=5)
        self.assertAlmostEqual(float(row["flash_edep"]), 1.5e-6, places=12)
        # The x recovered by evaluate must be the x that was proposed.
        for col, want in zip(self.mode.KNOB_NAMES, x):
            self.assertAlmostEqual(float(row[col]), want, places=4, msg=col)
        # And the row must read back through the normal history path.
        hist = self.mode.load_history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0].cfg, "PROBE01")
        for got, want in zip(hist[0].x, x):
            self.assertAlmostEqual(float(got), want, places=4)
        # Pending is cleared exactly as for a Python mode.
        self.assertEqual(self.mode.load_pending(), [])

    def test_evaluate_without_a_pending_row_fails_loudly(self):
        """The x is recovered from the pending TSV; if the config is not
        there (evaluate re-run after a successful one already cleared it),
        refuse with a message naming the pending file and the config --
        never a guessed or partial x."""
        x = [120.0, 130.0, 0.1, 0.2, 0.3, 0.4]
        self.mode.render_proposal("PROBE02", x)   # geom exists, pending does not
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._args("PROBE02", summary))

        msg = str(cm.exception)
        self.assertIn("PROBE02", msg)
        self.assertIn(str(self.mode.pending_path()), msg)
        self.assertFalse(self.mode.leaderboard.exists(),
                         "refused evaluate must not append anything")


if __name__ == "__main__":
    unittest.main()
