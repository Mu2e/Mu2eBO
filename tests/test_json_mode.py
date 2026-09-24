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
import unittest
import unittest.mock
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
import bo_driver  # noqa: E402
from bo_driver import JsonMode  # noqa: E402
from study_compat import load_modespec as load_mode_file  # noqa: E402
from study import load_study_file  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "mode_specs" / "foilsflash.json"


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
        # extract_metrics reads _modes.STUDIES (Task 8: objectives/
        # extra_metrics come from the Study, not the ModeSpec).
        cls.study = dataclasses.replace(load_study_file(FIXTURE), name="demoflash")
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


    # test_parse_geom_refuses_clearly removed 2026-08-08: JsonMode.parse_geom
    # were deleted outright -- geometry round-trip is
    # no longer part of the interface at all (not even as a NotImplementedError
    # stub), now that no Python mode needs the round-trip default. See
    # docs/superpowers/specs/2026-08-08-leaderboard-module-design.md.

    def test_extract_metrics_values_by_name(self):
        """Task 8: extract_metrics returns {objective/extra-metric name:
        value}, read by the study's Objective.key -- no positional tuple, no
        per-mode metric_cols indexing."""
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}),
            {"sob": 3.9, "flash_edep": 1e-6})

    def test_extract_metrics_has_no_per_event_fallback(self):
        """Intended Phase-A change (generic-study spec, "Changed on
        purpose"): a schema-2 objective names ONE metric, so the flash column
        no longer falls back to flash_edep_per_event when flash_edep_per_pot
        is missing. A per-event-only summary leaves the column unresolved
        (None -> cmd_evaluate refuses the row, rc=1) instead of landing a
        per-event value in a per-POT column."""
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_event": 2e-6})
        self.assertEqual(out["sob"], 3.9)
        self.assertIsNone(out["flash_edep"])

    # -- F7: UNRESOLVED and RESOLVED-TO-ZERO are different cases ------------
    # A second-objective-less summary used to kill every child at evaluate
    # after the full wall-clock (raising in extract_metrics). Returning None
    # instead lets cmd_evaluate refuse the row with a diagnostic rc=1 -- and
    # keeps "unresolved" distinguishable from "resolved to a real zero",
    # which is a different (poison) case handled in cmd_evaluate.
    def test_extract_metrics_unresolved_second_objective_returns_none(self):
        self.assertEqual(
            self.mode.extract_metrics({"s_over_sqrt_b": 3.9}),
            {"sob": 3.9, "flash_edep": None})

    def test_extract_metrics_null_second_objective_returns_none(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": None,
                 "flash_edep_per_event": None}),
            {"sob": 3.9, "flash_edep": None})

    def test_extract_metrics_missing_sob_returns_none(self):
        """Task 8: extract_metrics is a pure by-name lookup now -- a missing
        objective value is None like any other key, never a raise.
        cmd_evaluate is the seam that turns a None into a refusal (rc=1);
        it used to be extract_metrics raising KeyError for column 0 only."""
        out = self.mode.extract_metrics({"flash_edep_per_pot": 1e-6})
        self.assertIsNone(out["sob"])
        self.assertEqual(out["flash_edep"], 1e-6)

    # -- The second objective must never silently collapse to a poison zero
    # row (mirrors the retired FoilsFlashMode.extract_metrics's SystemExit
    # guard). Task 8 moved this check out of extract_metrics (now a pure
    # lookup) and into cmd_evaluate's log10-transform check; the end-to-end
    # refusal is exercised by
    # TestJsonModeEvaluateEndToEnd.test_evaluate_still_refuses_a_second_objective_that_resolves_to_zero
    # below. Here we just confirm extract_metrics passes the raw value
    # through unrefused.
    def test_extract_metrics_zero_and_negative_pass_through(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0}
            )["flash_edep"], 0.0)
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": -1e-6}
            )["flash_edep"], -1e-6)

    def test_extract_metrics_valid_second_metric_passes(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}),
            {"sob": 3.9, "flash_edep": 1e-6})

    def test_extract_metrics_calo_per_pot_is_not_a_fallback(self):
        """Root-cause regression: the fixture's flash_edep fallback chain
        used to list calo_per_pot -- copied from the STALE comment above
        FoilsFlashMode.extract_metrics, which claims that fallback but never
        implements it. A calo-only summary must NOT put calo in the flash
        column (it reports the column as unresolved -- None)."""
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "calo_per_pot": 1.2e-6})
        self.assertEqual(out["sob"], 3.9)
        self.assertIsNone(out["flash_edep"])


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
        # modes.STUDIES / modes.SPECS / bo_driver.MODES, and
        # tests/test_modes.py asserts the SPECS and MODES keysets are equal
        # -- so every registration is undone by addCleanup even if this
        # setUp raises partway through. STUDIES is where leaderboard_io()
        # takes the row shape from.
        self.name = "evalprobe" + uuid.uuid4().hex[:8]
        study = dataclasses.replace(load_study_file(FIXTURE), name=self.name)
        modes.STUDIES[self.name] = study
        self.addCleanup(modes.STUDIES.pop, self.name, None)
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
    def test_no_substitution_for_an_unresolved_second_objective(self):
        """An absent second objective is NEVER coerced to a number.

        Every stage in every mode chain produces a real second objective, so
        None means its producing stage fail-softed. Coercing it to 0.0 writes
        a fake zero-flash row at good sob that dominates the Pareto front at
        the next GP refit (7 poison rows landed that way 2026-07-10). The
        retired FoilsFlashMode refused this by raising; with the last
        substitution path gone the guarantee is now structural.
        """
        self._propose("PROBE03B")
        summary = self._summary({"s_over_sqrt_b": 3.9})
        rc = bo_driver.cmd_evaluate(self._args("PROBE03B", summary))
        self.assertEqual(rc, 1)
        self.assertFalse(self.mode.leaderboard.exists(),
                         "a zero-flash poison row was appended")

    def test_evaluate_refuses_unresolved_second_objective(self):
        self._propose("PROBE04")
        summary = self._summary({"s_over_sqrt_b": 3.9})
        rc = bo_driver.cmd_evaluate(self._args("PROBE04", summary))
        self.assertEqual(rc, 1)
        self.assertFalse(self.mode.leaderboard.exists())

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
        self.assertFalse(self.mode.leaderboard.exists())

    # -- M1: the pending row is the ONLY record of x ------------------------
    def _register_variant(self, mutate):
        """Register a variant of FIXTURE (mutated JSON, own name and board)
        exactly like setUp does, and return its JsonMode."""
        doc = json.loads(FIXTURE.read_text())
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
        mode.leaderboard = self.tmp / f"leaderboard_bo_{name}.tsv"
        mode.leaderboard_archive = None
        mode.proposal_dir = self.tmp / "proposals"
        bo_driver.MODES[name] = mode
        self.addCleanup(bo_driver.MODES.pop, name, None)
        return mode

    def _variant_args(self, mode, cfg, summary):
        return argparse.Namespace(mode=mode.name, summary=str(summary),
                                  config_name=cfg, alpha=1.0e5,
                                  emit_json=None)

    def test_a_failing_extra_column_keeps_the_pending_row(self):
        """An extra-column expression that fails on this row's values (here
        a division by zero) must fail evaluate while the pending row -- the
        only record of x -- still exists. It used to be cleared first, and
        the append then raised: a finished eval's x was gone."""
        def zero_div(doc):
            obj = next(c for c in doc["extra_columns"] if c["name"] == "obj")
            obj["expr"] = "sob / (flash_edep - flash_edep)"
        mode = self._register_variant(zero_div)
        x = [120.0, 130.0, 0.1, 0.2, 0.3, 0.4]
        mode.render_proposal("FMT01", x)
        mode.append_pending("FMT01", x, 1.0e5)
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._variant_args(mode, "FMT01", summary))

        msg = str(cm.exception)
        self.assertIn("FMT01", msg)
        self.assertIn("ZeroDivisionError", msg)
        self.assertIn("pending row", msg)
        self.assertEqual(mode.load_pending(), [("FMT01", x)])
        self.assertFalse(mode.leaderboard.exists(),
                         "a failed format must not append anything")

    def test_an_unsourced_context_name_is_refused_before_anything(self):
        """leaderboard.context names a value the evaluate CLI cannot
        supply: refused up front, pending row and board untouched (it used
        to be hardcoded {"alpha": ...} and the append then raised)."""
        mode = self._register_variant(
            lambda doc: doc["leaderboard"]["context"].append("beta"))
        x = [120.0, 130.0, 0.1, 0.2, 0.3, 0.4]
        mode.render_proposal("CTX01", x)
        mode.append_pending("CTX01", x, 1.0e5)
        summary = self._summary(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1.5e-6})

        with self.assertRaises(SystemExit) as cm:
            bo_driver.cmd_evaluate(self._variant_args(mode, "CTX01", summary))

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
