"""Picker tests for core/botorch_predict.py (main suite since the 2026-07-18
single-venv consolidation) + the botorch_ask subprocess seam smoke.

Fixtures repoint bo.MODES["foilsflash"].leaderboard at a tmp 10-row TSV
(history is exactly the fixture leaderboard). The live
leaderboards are never touched."""
import json
import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402
import study as st  # noqa: E402

HEADER = ("config\textra_rOut_up\textra_rOut_dn\textra_halfThickness_up"
          "\textra_halfThickness_dn\textra_f_up\textra_f_dn"
          "\tsob\tflash_edep\talpha\tobj\n")


def write_fixture(path: Path, n: int = 10, header_only: bool = False):
    rows = []
    for i in range(n):
        u = i / max(1, n - 1)
        x = [50 + 200 * u, 250 - 200 * u, 0.002 + 0.9 * u, 0.9 - 0.8 * u,
             0.05 + 0.9 * u, 0.9 - 0.85 * u]
        sob, flash = 3.0 + 0.8 * u, 1e-7 * (1 + 9 * u)
        rows.append(f"cfg{i:03d}\t{x[0]:.4f}\t{x[1]:.4f}\t{x[2]:.6f}"
                    f"\t{x[3]:.6f}\t{x[4]:.4f}\t{x[5]:.4f}"
                    f"\t{sob:.5f}\t{flash:.5e}\t100000.000\t{sob:.5f}\n")
    path.write_text(HEADER + ("" if header_only else "".join(rows)))


def patched_leaderboard(tmp: str, **kw):
    lb = Path(tmp) / "leaderboard_bo_foilsflash.tsv"
    write_fixture(lb, **kw)
    return mock.patch.multiple(bo.MODES["foilsflash"],
                               leaderboard=lb, leaderboard_archive=None)


BOUNDS_LO = list(bp._modes.SPECS["foilsflash"].bounds_lo)
BOUNDS_HI = list(bp._modes.SPECS["foilsflash"].bounds_hi)


def in_bounds(x):
    return all(lo - 1e-9 <= v <= hi + 1e-9
               for v, lo, hi in zip(x, BOUNDS_LO, BOUNDS_HI))


class TestLoadHistoryTensor(unittest.TestCase):
    def test_parses_rows_and_log_transforms_second_objective(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, int_dims = bp.load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (10, 6))
            self.assertEqual(tuple(Y.shape), (10, 2))
            self.assertAlmostEqual(float(Y[0, 1]), -math.log10(1e-7), places=6)
            self.assertEqual(bounds.shape[-1], 6)
            self.assertEqual(int_dims, [])

    def test_nonpositive_calo_rows_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp) as _:
            lb = bo.MODES["foilsflash"].leaderboard
            with lb.open("a") as f:
                f.write("bad\t100.0\t100.0\t0.5\t0.5\t0.5\t0.5"
                        "\t3.0\t0.00000e+00\t100000.000\t3.0\n")
            X, Y, _, _ = bp.load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (10, 6))

    def test_primary_only_path_is_1d(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            _, Y, _, _ = bp.load_history_tensor("foilsflash", primary_only=True)
            self.assertEqual(tuple(Y.shape), (10, 1))

    def test_width_guard_systemexit_on_dim_mismatch(self):
        wrong = [bo.Point(cfg="w", x=[1.0, 2.0, 3.0],
                          y={"sob": 1.0, "flash_edep": 1e-7})]
        with mock.patch.object(bo.MODES["foilsflash"], "load_history",
                               return_value=wrong):
            with self.assertRaises(SystemExit):
                bp.load_history_tensor("foilsflash")

    def test_cold_start_returns_empty_with_correct_width(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            X, Y, _, _ = bp.load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (0, 6))
            self.assertEqual(tuple(Y.shape), (0, 2))


def _obj(direction, transform):
    return st.Objective("m", "s.m", direction, transform, 0.1, "{:.3f}")


class TestAxisValue(unittest.TestCase):
    def test_axis_value(self):
        # (direction, transform, value, GP axis value; None = undefined)
        rows = [("max", "none", 3.0, 3.0),
                ("min", "none", 3.0, -3.0),
                ("min", "log10", 1e-6, 6.0),
                ("max", "log10", 100.0, 2.0),
                ("min", "log10", 0.0, None),
                ("max", "none", float("nan"), None),
                ("max", "none", None, None)]
        for direction, transform, value, want in rows:
            with self.subTest(direction=direction, transform=transform,
                              value=value):
                got = bp.axis_value(_obj(direction, transform), value)
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertAlmostEqual(got, want)


class TestThreeObjectiveProblem(unittest.TestCase):
    """A synthetic 3-objective study builds a 3-axis Problem, fits, and
    picks (spec Phase A acceptance)."""

    @staticmethod
    def _study(n_objectives, n_knobs):
        """The first n of y1 max/none, y2 min/log10, y3 min/none (noise
        0.01/0.02/0.03), plus a y2 <= 1e-3 constraint at k_sigma=1."""
        objs = (st.Objective("y1", "s.a", "max", "none", 0.01, "{:.4f}"),
                st.Objective("y2", "s.b", "min", "log10", 0.02, "{:.4e}"),
                st.Objective("y3", "s.c", "min", "none", 0.03, "{:.4f}"))
        return types.SimpleNamespace(
            objectives=objs[:n_objectives],
            constraints=(st.StudyConstraint("y2", "max", 1e-3, 1.0),),
            bounds_lo=(0.0,) * n_knobs, bounds_hi=(1.0,) * n_knobs,
            int_dims=())

    def test_three_axes(self):
        prob = bp._problem_from(self._study(3, 2), primary_only=False)
        self.assertEqual(prob.noise, (0.01, 0.02, 0.03))
        self.assertEqual(prob.constraint.axis, 1)
        self.assertAlmostEqual(prob.constraint.min, 3.0)
        X = [[0.1 * i, 0.05 * i] for i in range(8)]
        Y = [[x0, -math.log10(1e-4 + x1), -x0 * x1] for x0, x1 in X]
        picks = bp.surrokit.ask(prob, X, Y, q=2, picker="qnehvi", seed=42)
        self.assertEqual(len(picks), 2)

    def test_primary_only_drops_other_axes_and_their_constraint(self):
        prob = bp._problem_from(self._study(2, 1), primary_only=True)
        self.assertEqual(prob.noise, (0.01,))
        self.assertIsNone(prob.constraint)


class TestSeed(unittest.TestCase):
    def test_seed_is_xor_not_pow(self):
        # 42^1=43, 42^2=40, 42^3=41 under XOR; pow would explode.
        self.assertEqual([bp._seed(i) for i in range(4)], [42, 43, 40, 41])


class TestComputeExplorePicks(unittest.TestCase):
    def test_cold_start_path_returns_q_picks(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            picks = bp.compute_explore_picks(q=2, mode="foilsflash",
                                             round_idx=0)
            self.assertEqual(len(picks), 2)
            for p in picks:
                self.assertTrue(in_bounds(p))

    def test_real_gp_qnehvi_pick_on_fixture(self):
        # The one real GP fit in the suite (CPU, ~seconds on 10 rows).
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            picks = bp.compute_explore_picks(q=1, mode="foilsflash",
                                             round_idx=0, picker="qnehvi")
            self.assertEqual(len(picks), 1)
            self.assertEqual(len(picks[0]), 6)
            self.assertTrue(in_bounds(picks[0]))

    def test_main_emits_picks_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            lb = Path(tmp) / "lb.tsv"
            write_fixture(lb, header_only=True)  # cold start = fast
            out = Path(tmp) / "picks.json"
            bp.main(["--mode", "foilsflash", "--q", "2", "--round-idx", "0",
                     "--leaderboard", str(lb),
                     "--emit-picks-json", str(out)])
            picks = json.loads(out.read_text())
            self.assertEqual(len(picks), 2)


_REMOVED = (("AUTORESEARCH_FLASH_BUDGET", "max"),
            ("AUTORESEARCH_BUDGET_KSIGMA", "k_sigma"))


def _env_without_removed():
    return {k: v for k, v in os.environ.items()
            if k not in dict(_REMOVED)}


class TestRemovedEnvOverrides(unittest.TestCase):
    """The budget/k env overrides were removed in Phase A (the study's
    constraints[0] is the only source). A stale export must be FATAL: the
    last production budget_sob round ran with AUTORESEARCH_BUDGET_KSIGMA=0.5,
    and silently ignoring that export would run at the study's k while the
    operator believes it runs at theirs."""

    def test_each_removed_variable_is_fatal_in_build_problem(self):
        study = bp._modes.STUDIES["foilspfbpz"]
        for var, field in _REMOVED:
            with self.subTest(var=var), \
                 mock.patch.dict(os.environ, {var: "0.5"}):
                with self.assertRaises(SystemExit) as cm:
                    bp.build_problem("foilspfbpz")
                msg = str(cm.exception)
                self.assertIn(var, msg)
                self.assertIn("removed in Phase A", msg)
                self.assertIn(f"constraints[0].{field}", msg)
                self.assertIn(str(study.path), msg)

    def test_compute_explore_picks_hits_it(self):
        for var, _field in _REMOVED:
            with self.subTest(var=var), \
                 tempfile.TemporaryDirectory() as tmp, \
                 patched_leaderboard(tmp), \
                 mock.patch.dict(os.environ, {var: "6.8e-7"}):
                with self.assertRaises(SystemExit) as cm:
                    bp.compute_explore_picks("foilsflash", q=1,
                                             picker="budget_sob")
                self.assertIn(var, str(cm.exception))

    def test_unset_builds_the_study_constraint(self):
        with mock.patch.dict(os.environ, _env_without_removed(), clear=True):
            prob = bp.build_problem("foilspfbpz")
        c = bp._modes.STUDIES["foilspfbpz"].constraints[0]
        self.assertEqual(prob.constraint.k_sigma, c.k_sigma)


class TestBotorchAskSeamSmoke(unittest.TestCase):
    def test_ask_q2_roundtrip_through_subprocess(self):
        # End-to-end: bo_driver.botorch_ask -> .venv python botorch_predict.py
        # --leaderboard <tmp fixture> --emit-picks-json. The only slow test
        # in the suite (one real 10-row GP fit in a fresh interpreter).
        with tempfile.TemporaryDirectory() as tmp:
            lb = Path(tmp) / "lb.tsv"
            write_fixture(lb)
            xs = bo.botorch_ask("foilsflash", q=2, seed_idx=0,
                                picker="qnehvi", leaderboard=lb)
            self.assertEqual(len(xs), 2)
            for x in xs:
                self.assertEqual(len(x), 6)
                self.assertTrue(in_bounds(x))


class TestSurrokitPin(unittest.TestCase):
    def test_checkout_matches_pin(self):
        import subprocess
        from paths import SURROKIT_PIN_SHA, SURROKIT_ROOT
        if not (SURROKIT_ROOT / ".git").exists():
            self.skipTest("surrokit checkout has no .git (deployed copy)")
        head = subprocess.run(
            ["git", "-C", str(SURROKIT_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(head, SURROKIT_PIN_SHA,
                         "surrokit checkout drifted from the validated pin; "
                         "re-validate and bump SURROKIT_PIN_SHA deliberately")


if __name__ == "__main__":
    unittest.main()
