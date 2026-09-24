"""JsonMode: the single generic driver class behind every JSON-defined mode.

Import convention: bare `modes`/`bo_driver`/`study_compat` via
sys.path.insert, matching tests/test_modes.py and tests/test_study.py --
NOT `from core import modes`. bo_driver.py itself does `import modes as
_modes` (bare); a qualified `from core import modes` here would load a
SECOND, non-identical `core.modes` module alongside it (the
two-non-identical-classes bug Task 4 fixed for GeomTemplate -- see
core/modes.py's tail comment), and
tests.test_modes.TestSingleModeSpecClass asserts "core.modes" never
lands in sys.modules across the whole suite.
"""
import argparse
import csv
import dataclasses
import json
import shutil
import sys
import tempfile
import contextlib
import io
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
import bo_driver  # noqa: E402
from bo_driver import JsonMode  # noqa: E402
from study_compat import load_modespec as load_mode_file  # noqa: E402
from study import load_study_file  # noqa: E402

LIVE_SPEC = Path(__file__).resolve().parent.parent / "mode_specs" / "foilsflash.json"


class TestJsonMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Register under a non-colliding name so SPECS/MODES stay clean.
        # addClassCleanup (not tearDownClass) so the pop still runs even if
        # JsonMode(...) itself raises partway through setUpClass -- a plain
        # tearDownClass is SKIPPED by unittest when setUpClass raises, which
        # would leak "demoflash" into the process-global modes.SPECS for the
        # rest of `unittest discover`.
        cls.spec = dataclasses.replace(load_mode_file(LIVE_SPEC), name="demoflash")
        modes.SPECS["demoflash"] = cls.spec
        cls.addClassCleanup(modes.SPECS.pop, "demoflash", None)
        # extract_metrics reads _modes.STUDIES (Task 8: objectives/
        # extra_metrics come from the Study, not the ModeSpec).
        cls.study = dataclasses.replace(load_study_file(LIVE_SPEC), name="demoflash")
        modes.STUDIES["demoflash"] = cls.study
        cls.addClassCleanup(modes.STUDIES.pop, "demoflash", None)
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

    def test_extract_metrics_reads_each_value_by_its_study_key(self):
        """extract_metrics is `summary.get(key)` per study objective/extra
        metric: {name: value or None}. No fallback between keys, never a
        raise, never a refusal: cmd_evaluate is the seam that refuses a None
        (rc=1) or a zero/negative log10 value (SystemExit) -- see
        TestJsonModeEvaluateEndToEnd."""
        ok = {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}
        rows = [
            (ok, {"sob": 3.9, "flash_edep": 1e-6}),
            # Intended Phase-A change ("Changed on purpose"): an objective
            # names ONE metric, so a per-event-only summary leaves the
            # per-POT column unresolved instead of landing a per-event value.
            ({"s_over_sqrt_b": 3.9, "flash_edep_per_event": 2e-6},
             {"sob": 3.9, "flash_edep": None}),
            # Nor is calo_per_pot a fallback (the old fixture's chain once
            # listed it, copied from a stale comment).
            ({"s_over_sqrt_b": 3.9, "calo_per_pot": 1.2e-6},
             {"sob": 3.9, "flash_edep": None}),
            # F7, UNRESOLVED (absent or null): None, not a raise -- raising
            # here killed every child at evaluate after the full wall-clock.
            ({"s_over_sqrt_b": 3.9}, {"sob": 3.9, "flash_edep": None}),
            ({"s_over_sqrt_b": 3.9, "flash_edep_per_pot": None,
              "flash_edep_per_event": None},
             {"sob": 3.9, "flash_edep": None}),
            # The primary is looked up the same way: None, not a KeyError.
            ({"flash_edep_per_pot": 1e-6}, {"sob": None, "flash_edep": 1e-6}),
            # F7, RESOLVED-TO-ZERO (or negative) passes through; the
            # poison-row refusal is cmd_evaluate's log10 check.
            ({**ok, "flash_edep_per_pot": 0.0}, {"sob": 3.9, "flash_edep": 0.0}),
            ({**ok, "flash_edep_per_pot": -1e-6},
             {"sob": 3.9, "flash_edep": -1e-6}),
        ]
        for summary, want in rows:
            with self.subTest(summary=summary):
                self.assertEqual(self.mode.extract_metrics(summary), want)


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
        self.mode = self._register_variant(lambda doc: None)

    def _register_variant(self, mutate):
        """Register a copy of the live foilsflash spec (mutated JSON, own
        name and scratch board) and return its JsonMode.

        Unique name: the probe is registered into the process-global
        modes.STUDIES / modes.SPECS / bo_driver.MODES, and
        tests/test_modes.py asserts the SPECS and MODES keysets are equal
        -- so every registration is undone by addCleanup even if this
        raises partway through. STUDIES is where leaderboard_io() takes the
        row shape from."""
        doc = json.loads(LIVE_SPEC.read_text())
        mutate(doc)
        name = "evalvariant" + uuid.uuid4().hex[:8]
        doc["name"] = name
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_bo_{name}.tsv"
        path = self.tmp / f"{name}.json"
        path.write_text(json.dumps(doc))
        modes.STUDIES[name] = load_study_file(path)
        self.addCleanup(modes.STUDIES.pop, name, None)
        modes.SPECS[name] = load_mode_file(path)
        self.addCleanup(modes.SPECS.pop, name, None)
        mode = JsonMode(name)
        # Never touch a real leaderboard under leaderboards/.
        mode.leaderboard = self.tmp / f"leaderboard_bo_{name}.tsv"
        mode.leaderboard_archive = None
        mode.proposal_dir = self.tmp / "proposals"
        bo_driver.MODES[name] = mode
        self.addCleanup(bo_driver.MODES.pop, name, None)
        return mode

    def _args(self, config_name, summary_path, alpha=1.0e5, mode=None):
        return argparse.Namespace(
            mode=(mode or self.mode).name, summary=str(summary_path),
            config_name=config_name, alpha=alpha, emit_json=None)

    def _summary(self, payload) -> Path:
        p = self.tmp / "summary.json"
        p.write_text(json.dumps(payload))
        return p

    def _propose(self, cfg, x=(120.0, 130.0, 0.1, 0.2, 0.3, 0.4), mode=None):
        """What propose leaves for evaluate: the pending row, the ONLY
        record of x. evaluate reads no geometry."""
        (mode or self.mode).append_pending(cfg, list(x), 1.0e5)
        return list(x)

    def test_evaluate_appends_a_leaderboard_row(self):
        x = self._propose("PROBE01")
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

    # -- F7 case 1: UNRESOLVED second objective ----------------------------
    def test_no_substitution_for_an_unresolved_second_objective(self):
        """An absent second objective is NEVER coerced to a number.

        Every stage in every mode chain produces a real second objective, so
        None means its producing stage fail-softed. Coercing it to 0.0 writes
        a fake zero-flash row at good sob that dominates the Pareto front at
        the next GP refit (7 poison rows landed that way 2026-07-10). The
        retired FoilsFlashMode refused this by raising; with the last
        substitution path gone the guarantee is now structural. The printed
        refusal names the missing objective (rc=1 alone would also fit an
        unrelated failure).
        """
        self._propose("PROBE03B")
        summary = self._summary({"s_over_sqrt_b": 3.9})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bo_driver.cmd_evaluate(self._args("PROBE03B", summary))
        self.assertEqual(rc, 1)
        self.assertIn("refusing", buf.getvalue())
        self.assertIn("flash_edep", buf.getvalue())
        self.assertFalse(self.mode.leaderboard.exists(),
                         "a zero-flash poison row was appended")

    # -- F7 case 2: RESOLVED-TO-ZERO must still be refused -----------------
    def test_evaluate_still_refuses_a_second_objective_that_resolves_to_zero(self):
        """The zero-refusal guard must NOT weaken: a second objective that
        RESOLVES to 0.0 from a real summary key is a fake row that dominates
        the entire Pareto front at the next GP refit (7 poison rows landed
        this way 2026-07-10). Distinct from 'unresolved' above: the key WAS
        there."""
        self._propose("PROBE05")
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0})
        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._args("PROBE05", summary))
        self.assertIn("flash_edep_per_pot", str(cm.exception))
        self.assertIn("log10", str(cm.exception))
        self.assertFalse(self.mode.leaderboard.exists())

    # -- M1: the pending row is the ONLY record of x ------------------------
    def test_a_failing_extra_column_keeps_the_pending_row(self):
        """An extra-column expression that fails on this row's values (here
        a division by zero) must fail evaluate while the pending row -- the
        only record of x -- still exists. It used to be cleared first, and
        the append then raised: a finished eval's x was gone."""
        def zero_div(doc):
            obj = next(c for c in doc["extra_columns"] if c["name"] == "obj")
            obj["expr"] = "sob / (flash_edep - flash_edep)"
        mode = self._register_variant(zero_div)
        x = self._propose("FMT01", mode=mode)
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._args("FMT01", summary, mode=mode))

        msg = str(cm.exception)
        self.assertIn("FMT01", msg)
        self.assertIn("ZeroDivisionError", msg)
        self.assertIn("pending row", msg)
        self.assertEqual(mode.load_pending(), [("FMT01", x)])
        self.assertFalse(mode.leaderboard.exists(),
                         "a failed format must not append anything")

    def test_an_unsourced_context_name_keeps_the_pending_row(self):
        """leaderboard.context names a value the evaluate CLI cannot
        supply: the row is formatted before pending is cleared, so the
        refusal leaves the pending row and the board untouched (it used to
        be hardcoded {"alpha": ...} and the append then raised)."""
        mode = self._register_variant(
            lambda doc: doc["leaderboard"]["context"].append("beta"))
        x = self._propose("CTX01", mode=mode)
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._args("CTX01", summary, mode=mode))

        msg = str(cm.exception)
        self.assertIn("'beta'", msg)
        self.assertIn("leaderboard.context", msg)
        self.assertEqual(mode.load_pending(), [("CTX01", x)])
        self.assertFalse(mode.leaderboard.exists())

    def test_the_row_context_comes_from_the_study(self):
        """The alpha column is the CLI --alpha, routed through the study's
        leaderboard.context (not a hardcoded dict)."""
        self._propose("CTX02")
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})
        rc = bo_driver.cmd_evaluate(self._args("CTX02", summary, alpha=2.5e4))
        self.assertEqual(rc, 0)
        with self.mode.leaderboard.open() as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertAlmostEqual(float(row["alpha"]), 2.5e4, places=3)

    def test_evaluate_without_a_pending_row_fails_loudly(self):
        """The x is recovered from the pending TSV; if the config is not
        there (evaluate re-run after a successful one already cleared it),
        refuse with a message naming the pending file and the config --
        never a guessed or partial x."""
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
