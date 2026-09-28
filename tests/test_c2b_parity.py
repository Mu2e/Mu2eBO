"""tools/c2b_parity.py's pure parts: the comparison rules, the Level 1
input scan, and the hand-written prodtools record the engine adopts."""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("c2b_parity",
                                               ROOT / "tools" / "c2b_parity.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


class TestRules(unittest.TestCase):
    def test_sob_matches_the_macros_three_figures(self):
        for old, new, want in ((4.15, 4.150673260012092, True),
                               (1.69, 1.6921788497327521, True),
                               (4.03, 4.027245662773131, True),
                               (4.15, 4.1549, True),
                               (4.15, 4.1560, False),
                               (4.15, 4.1440, False),
                               (0.912, 0.9125, True),
                               (0.912, 0.9131, False),
                               (-1.0, 1.0, False)):
            with self.subTest(old=old, new=new):
                self.assertIs(cp.sob_matches(old, new), want)

    def test_rel_close(self):
        self.assertTrue(cp.rel_close(6.695048428749645e-07, 6.695048e-07 * (1 + 5e-7)))
        self.assertFalse(cp.rel_close(6.695e-07, 6.695e-07 * (1 + 2e-6)))
        self.assertFalse(cp.rel_close(0.0, 0.0))

    def test_compare_level2_names_each_quantity(self):
        summary = {"muminus_stops": 97520, "mubeam_sim_total": 3.0e6,
                   "ce_seen": 588681, "ce_simulated_events": 1.125e6,
                   "ce_abs_eff": 2.174141844862464e-4,
                   "flash_edep_per_pot": 1.7795659934565772e-07,
                   "s_over_sqrt_b": 1.69}
        sob = {"muminus_stops": 97520.0, "mubeam_sim_total": 3.0e6,
               "ce_seen": 588681.0, "ce_simulated_events": 1.125e6,
               "ce_abs_eff": 2.174141844862464e-4, "s_over_sqrt_b": 1.692}
        flash = {"flash_edep_per_pot": 1.7795659934565772e-07}
        rows = cp.compare_level2(summary, sob, flash)
        self.assertEqual([r[0] for r in rows],
                         ["muminus_stops", "mubeam_sim_total", "ce_seen",
                          "ce_simulated_events", "ce_abs_eff",
                          "flash_edep_per_pot", "s_over_sqrt_b"])
        self.assertTrue(all(r[3] for r in rows), rows)
        bad = cp.compare_level2(summary, {**sob, "ce_seen": 588680.0}, flash)
        self.assertEqual([r[0] for r in bad if not r[3]], ["ce_seen"])


class TestLevel1Inputs(unittest.TestCase):
    def test_level1_inputs_counts_every_skip_with_its_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def harvest(config, summary, nts=True):
                d = root / config / "harvest"
                d.mkdir(parents=True)
                (d / "summary.json").write_text(summary)
                if nts:
                    (d / "nts.ce.root").write_text("")
                return d / "summary.json"

            good = harvest("foilspfA", json.dumps(
                {"ce_abs_eff": 6.6e-4, "s_over_sqrt_b": 4.15}))
            paths = [good,
                     harvest("foilspfB", json.dumps({"s_over_sqrt_b": 4.0})),
                     harvest("foilspfC", json.dumps(
                         {"ce_abs_eff": 6e-4, "s_over_sqrt_b": 4.0}), nts=False),
                     harvest("foilspfD", "{not json")]
            rows, skipped = cp.level1_inputs(paths)
        self.assertEqual([(r[0], r[2], r[3]) for r in rows],
                         [("foilspfA", 6.6e-4, 4.15)])
        reasons = {Path(p).parent.parent.name: why for p, why in skipped}
        self.assertEqual(sorted(reasons), ["foilspfB", "foilspfC", "foilspfD"])
        self.assertIn("ce_abs_eff", reasons["foilspfB"])
        self.assertIn("nts.ce.root", reasons["foilspfC"])
        self.assertIn("unreadable", reasons["foilspfD"])


class TestAdoptedRecord(unittest.TestCase):
    def test_it_is_what_the_scheduler_adopts(self):
        rec = cp.adopted_record("gridphaseA01", "mubeam",
                                ["/pnfs/a/sim.x.TargetStops.y.0.art"], 200000)
        self.assertEqual(rec["step"], "mubeam")
        self.assertEqual(rec["kit"], "prodtools")
        self.assertEqual(rec["handle"], "gridphaseA01.mubeam")
        self.assertEqual(rec["metrics"], {"njobs": 1, "njobs_ok": 1})
        self.assertEqual(rec["files"], [{
            "name": "sim.x.TargetStops.y.0.art",
            "uri": "file:///pnfs/a/sim.x.TargetStops.y.0.art", "kind": "art"}])
        self.assertEqual(rec["metadata"]["events_per_job"], 200000)
        self.assertTrue(rec["kit_version"].startswith("prodtools-adapter/"))


class TestLevel1Refusal(unittest.TestCase):
    def test_level1_refuses_loudly_when_nothing_matches(self):
        # An empty (or otherwise non-matching) grid root must not report a
        # vacuous "0 compared, 0 mismatched" success; it must refuse,
        # name the root, and exit 2.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(cp.paths, "GRID_DATA_ROOT", root):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cp.level1(argparse.Namespace(limit=0, workers=4))
        self.assertEqual(rc, 2)
        self.assertIn(str(root), buf.getvalue())

    def test_level1_reports_the_total_summary_count_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "foilspfA" / "harvest"
            d.mkdir(parents=True)
            (d / "summary.json").write_text(json.dumps(
                {"ce_abs_eff": 6.6e-4, "s_over_sqrt_b": 4.15}))
            (d / "nts.ce.root").write_text("")
            with mock.patch.object(cp.paths, "GRID_DATA_ROOT", root), \
                 mock.patch.object(cp, "study_params",
                                   return_value={"work_area": "/wa",
                                                 "cosmic_rate_per_s_per_mev": 1.0,
                                                 "dio_fraction": 0.39,
                                                 "dio_table": "/t.tbl"}), \
                 mock.patch.object(cp, "_kit", return_value=None), \
                 mock.patch.object(cp, "analyze",
                                   return_value=({"sensitivity": 4.15}, None)), \
                 mock.patch.object(cp, "_write_report",
                                   return_value=root / "level1.json"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cp.level1(argparse.Namespace(limit=0, workers=4))
        self.assertEqual(rc, 0)
        self.assertIn("1 summary file", buf.getvalue())


class TestAnalyzeCatchesEveryCall(unittest.TestCase):
    class FakeKit:
        def __init__(self, status_exc=None, results_exc=None):
            self.status_exc, self.results_exc = status_exc, results_exc

        def submit(self, *a, **kw):
            return None

        def status(self, *a, **kw):
            if self.status_exc:
                raise self.status_exc
            return types.SimpleNamespace(state="completed", message="ok")

        def results(self, *a, **kw):
            if self.results_exc:
                raise self.results_exc
            return types.SimpleNamespace(metrics={"x": 1.0})

    def test_a_status_exception_is_a_per_point_error(self):
        kit = self.FakeKit(status_exc=ValueError("status boom"))
        metrics, why = cp.analyze(kit, "cfg.sob", {}, [])
        self.assertIsNone(metrics)
        self.assertIn("status boom", why)

    def test_a_results_exception_is_a_per_point_error(self):
        kit = self.FakeKit(results_exc=OSError("disk full"))
        metrics, why = cp.analyze(kit, "cfg.sob", {}, [])
        self.assertIsNone(metrics)
        self.assertIn("disk full", why)


if __name__ == "__main__":
    unittest.main()
