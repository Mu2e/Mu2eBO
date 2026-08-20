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
import unittest.mock
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

    # test_parse_geom_refuses_clearly removed 2026-08-08: JsonMode.parse_geom
    # were deleted outright -- geometry round-trip is
    # no longer part of the interface at all (not even as a NotImplementedError
    # stub), now that no Python mode needs the round-trip default. See
    # docs/superpowers/specs/2026-08-08-leaderboard-module-design.md.

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

    # -- F7: UNRESOLVED and RESOLVED-TO-ZERO are different cases ------------
    # JsonMode used to raise KeyError when no candidate key resolved. That
    # broke the sob-only / qlnei path the Python modes support: cmd_evaluate's
    # deliberate `calo is None and AUTORESEARCH_NO_RUN1B == "1" -> 0.0`
    # substitution depends on extract_metrics RETURNING None, and KeyError is
    # not that. A JSON mode launched with --picker qlnei (which drops the calo
    # stage BY DESIGN) failed at evaluate on every child -- zero rows after
    # the full wall-clock.
    def test_extract_metrics_unresolved_second_objective_returns_none(self):
        self.assertEqual(
            self.mode.extract_metrics({"s_over_sqrt_b": 3.9}), (3.9, None))

    def test_extract_metrics_null_second_objective_returns_none(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": None,
                 "flash_edep_per_event": None}),
            (3.9, None))

    def test_extract_metrics_missing_sob_still_raises(self):
        """Column 0 keeps the Python modes' behaviour (KeyError), which
        cmd_evaluate's `except (KeyError, TypeError)` turns into rc=1."""
        with self.assertRaises(KeyError) as cm:
            self.mode.extract_metrics({"flash_edep_per_pot": 1e-6})
        self.assertIn("sob", str(cm.exception))

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
        implements it. A calo-only summary must NOT put calo in the flash
        column. (It now reports the column as unresolved -- None -- rather
        than raising; see the F7 block above. The guarantee this test exists
        for is unchanged: the calo value must never appear.)"""
        sob, second = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "calo_per_pot": 1.2e-6})
        self.assertEqual(sob, 3.9)
        self.assertIsNone(second)


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
        mode.leaderboard_archive = None
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

    def _propose(self, cfg, x=(120.0, 130.0, 0.1, 0.2, 0.3, 0.4)):
        self.mode.render_proposal(cfg, list(x))
        self.mode.append_pending(cfg, list(x), 1.0e5)
        return list(x)

    # -- F7 case 1: UNRESOLVED second objective ----------------------------
    def test_evaluate_substitutes_zero_for_an_unresolved_second_objective(self):
        """AUTORESEARCH_NO_RUN1B=1 drops the run1b_mubeam stage BY DESIGN.
        It is a MANUAL env seam: the `--picker qlnei` auto-stamp that used
        to set it died with graph/presniff.py (2026-08-19) and was not
        restored. Python modes return None there and
        cmd_evaluate substitutes 0.0 so the row still lands; JsonMode used to
        raise KeyError instead, so every child failed at evaluate.

        Requires a chain that actually CONTAINS run1b_mubeam — the fixture is
        foilsflash-shaped and has none, and for such a mode the substitution
        is a poison row rather than a design choice (see the companion test
        below). So this registers a run1b-bearing variant.
        """
        spec = modes.SPECS[self.name]
        variant = dataclasses.replace(
            spec, grid_stages=("mubeam", "run1b_mubeam", "mustops_ce"))
        with unittest.mock.patch.dict(modes.SPECS, {self.name: variant}):
            self._propose("PROBE03")
            summary = self._summary({"s_over_sqrt_b": 3.9})
            with unittest.mock.patch.dict(
                    bo_driver.os.environ, {"AUTORESEARCH_NO_RUN1B": "1"}):
                rc = bo_driver.cmd_evaluate(self._args("PROBE03", summary))
        self.assertEqual(rc, 0)
        with self.mode.leaderboard.open() as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertAlmostEqual(float(row["sob"]), 3.9, places=5)
        self.assertEqual(float(row["flash_edep"]), 0.0)

    def test_no_substitution_when_the_mode_never_had_a_run1b_stage(self):
        """The substitution is justified ONLY by "qlnei removed the stage that
        produces this metric". For a flash-shaped chain (mubeam/mustops_ce/
        elebeam_flash — no run1b_mubeam) an absent second objective instead
        means the elebeam stage failed fail-soft, and coercing it to 0.0
        writes a fake zero-flash row at good sob that dominates the Pareto
        front at the next GP refit. The retired FoilsFlashMode refused this by
        raising; the stage-chain gate restores that guarantee generically.
        """
        self.assertNotIn("run1b_mubeam", modes.SPECS[self.name].grid_stages)
        self._propose("PROBE03B")
        summary = self._summary({"s_over_sqrt_b": 3.9})
        with unittest.mock.patch.dict(
                bo_driver.os.environ, {"AUTORESEARCH_NO_RUN1B": "1"}):
            rc = bo_driver.cmd_evaluate(self._args("PROBE03B", summary))
        self.assertEqual(rc, 1)
        self.assertFalse(self.mode.leaderboard.exists(),
                         "a zero-flash poison row was appended")

    def test_evaluate_refuses_unresolved_second_objective_without_no_run1b(self):
        self._propose("PROBE04")
        summary = self._summary({"s_over_sqrt_b": 3.9})
        env = dict(bo_driver.os.environ)
        env.pop("AUTORESEARCH_NO_RUN1B", None)
        with unittest.mock.patch.dict(bo_driver.os.environ, env, clear=True):
            rc = bo_driver.cmd_evaluate(self._args("PROBE04", summary))
        self.assertEqual(rc, 1)
        self.assertFalse(self.mode.leaderboard.exists())

    # -- F7 case 2: RESOLVED-TO-ZERO must still be refused -----------------
    def test_evaluate_still_refuses_a_second_objective_that_resolves_to_zero(self):
        """The zero-refusal guard must NOT weaken: a second objective that
        RESOLVES to 0.0 from a real summary key is a fake row that dominates
        the entire Pareto front at the next GP refit (7 poison rows landed
        this way 2026-07-10). Distinct from 'unresolved' above -- and it is
        refused even under AUTORESEARCH_NO_RUN1B=1, because the key WAS
        there."""
        self._propose("PROBE05")
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0})
        with unittest.mock.patch.dict(
                bo_driver.os.environ, {"AUTORESEARCH_NO_RUN1B": "1"}):
            with self.assertRaises(SystemExit) as cm:
                bo_driver.cmd_evaluate(self._args("PROBE05", summary))
        self.assertIn("flash_edep_per_pot", str(cm.exception))
        self.assertFalse(self.mode.leaderboard.exists())

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
