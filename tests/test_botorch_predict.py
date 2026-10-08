"""Picker tests for core/botorch_predict.py (main suite since the 2026-07-18
single-venv consolidation).

Fixtures patch botorch_predict.boards.board_for to read a tmp v2 board for
foilsflash_ax (history is exactly the fixture board). The live leaderboards
are never touched."""
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import botorch_predict as bp  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Leaderboard, Point  # noqa: E402

# The engine twin of the old foilsflash study: same knobs and objectives.
STUDY = "foilsflash_ax"


def _board(path: Path) -> Leaderboard:
    return Leaderboard.for_study(bp._modes.STUDIES[STUDY], path=path,
                                 archive_path=None)


def write_fixture(path: Path, n: int = 10, header_only: bool = False):
    lb = _board(path)
    cols = lb.header().rstrip("\n").split("\t")
    lines = [lb.header()]
    for i in range(0 if header_only else n):
        u = i / max(1, n - 1)
        x = [50 + 200 * u, 250 - 200 * u, 0.002 + 0.9 * u, 0.9 - 0.8 * u,
             0.05 + 0.9 * u, 0.9 - 0.85 * u]
        vals = {"config": f"cfg{i:03d}",
                **{k: f"{v:.6f}" for k, v in zip(lb.knob_names, x)},
                "sob": f"{3.0 + 0.8 * u:.5f}",
                "flash_edep": f"{1e-7 * (1 + 9 * u):.5e}"}
        lines.append("\t".join(vals.get(c, "0") for c in cols) + "\n")
    path.write_text("".join(lines))


def patched_leaderboard(tmp: str, **kw):
    lb = Path(tmp) / f"leaderboard_bo_{STUDY}.tsv"
    write_fixture(lb, **kw)

    def board_for(s):
        # The fixture is STUDY's board: another study reaching board_for under
        # this patch would silently train on the wrong schema's rows.
        if s.name != STUDY:
            raise AssertionError(
                f"patched_leaderboard serves only {STUDY!r}'s fixture board, "
                f"but board_for was called for study {s.name!r}")
        return _board(lb)
    return mock.patch.object(bp.boards, "board_for", board_for)


BOUNDS_LO = list(bp._modes.STUDIES[STUDY].bounds_lo)
BOUNDS_HI = list(bp._modes.STUDIES[STUDY].bounds_hi)


def in_bounds(x):
    return all(lo - 1e-9 <= v <= hi + 1e-9
               for v, lo, hi in zip(x, BOUNDS_LO, BOUNDS_HI))


class TestLoadHistoryTensor(unittest.TestCase):
    def test_parses_rows_and_log_transforms_second_objective(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, int_dims = bp.load_history_tensor(STUDY)
            self.assertEqual(tuple(X.shape), (10, 6))
            self.assertEqual(tuple(Y.shape), (10, 2))
            self.assertAlmostEqual(float(Y[0, 1]), -math.log10(1e-7), places=6)
            self.assertEqual(bounds.shape[-1], 6)
            self.assertEqual(int_dims, [])

    def test_nonpositive_calo_rows_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            path = Path(tmp) / f"leaderboard_bo_{STUDY}.tsv"
            cols = _board(path).header().rstrip("\n").split("\t")
            vals = {"config": "bad", "extra_rOut_up": "100.0",
                    "extra_rOut_dn": "100.0", "sob": "3.0",
                    "flash_edep": "0.00000e+00"}
            with path.open("a") as f:
                f.write("\t".join(vals.get(c, "0.5") for c in cols) + "\n")
            X, Y, _, _ = bp.load_history_tensor(STUDY)
            self.assertEqual(tuple(X.shape), (10, 6))

    def test_primary_only_path_is_1d(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            _, Y, _, _ = bp.load_history_tensor(STUDY, primary_only=True)
            self.assertEqual(tuple(Y.shape), (10, 1))

    def test_width_guard_raises_on_dim_mismatch(self):
        wrong = [Point(cfg="w", x=[1.0, 2.0, 3.0],
                       y={"sob": 1.0, "flash_edep": 1e-7})]
        with mock.patch.object(bp, "history_points", return_value=wrong):
            with self.assertRaises(ValueError):
                bp.load_history_tensor(STUDY)

    def test_cold_start_returns_empty_with_correct_width(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            X, Y, _, _ = bp.load_history_tensor(STUDY)
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
            picks = bp.compute_explore_picks(q=2, mode=STUDY,
                                             round_idx=0)
            self.assertEqual(len(picks), 2)
            for p in picks:
                self.assertTrue(in_bounds(p))

    def test_real_gp_qnehvi_pick_on_fixture(self):
        # The one real GP fit in the suite (CPU, ~seconds on 10 rows).
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            picks = bp.compute_explore_picks(q=1, mode=STUDY,
                                             round_idx=0, picker="qnehvi")
            self.assertEqual(len(picks), 1)
            self.assertEqual(len(picks[0]), 6)
            self.assertTrue(in_bounds(picks[0]))


class TestBuildProblem(unittest.TestCase):
    def test_it_builds_the_study_constraint(self):
        """The constraint comes from the study file alone (its
        constraints[0]), as surrokit's Problem."""
        prob = bp.build_problem("foilspfbpz_ax")
        c = bp._modes.STUDIES["foilspfbpz_ax"].constraints[0]
        self.assertEqual(prob.constraint.k_sigma, c.k_sigma)


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


class TestMissingBoard(unittest.TestCase):
    def test_a_study_with_no_board_file_has_empty_history(self):
        """A new study has no board yet; neither the live nor the archive
        file exists. That is an empty history, not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.tsv"
            with mock.patch.object(
                    bp.boards, "board_for",
                    lambda s: Leaderboard.for_study(s, path=missing,
                                                    archive_path=None)):
                self.assertEqual(bp.history_points(STUDY), [])
                X, Y, _, _ = bp.load_history_tensor(STUDY)
        self.assertEqual(X.shape[0], 0)
        self.assertEqual(Y.shape[0], 0)


if __name__ == "__main__":
    unittest.main()
