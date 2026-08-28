"""BIT-PARITY GATE: old compute_explore_picks vs surrokit.ask.

Retired (deleted) in the same commit that rewires compute_explore_picks
to call surrokit -- after that the comparison is trivially self-vs-self.
Runs on the small in-repo fixtures where the hybrid/scipy ABNORMAL-retry
nondeterminism (wiki incident) is invisible.
"""
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import paths  # noqa: E402
import torch  # noqa: E402

sys.path.insert(0, str(paths.SURROKIT_ROOT))
import surrokit  # noqa: E402

import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402

from tests.test_botorch_predict import patched_leaderboard  # noqa: E402

MODE = "foilsflash"


def _problem(sob_only=False, constraint=None):
    spec = _modes.SPECS[MODE]
    return surrokit.Problem(
        bounds_lo=tuple(spec.bounds_lo),
        bounds_hi=tuple(spec.bounds_hi),
        int_dims=tuple(spec.int_dims),
        noise=tuple(spec.obs_noise),
        constraint=constraint,
    )


class TestBitParity(unittest.TestCase):
    def _compare(self, picker, *, q=2, round_idx=0, pending=None,
                 sob_only=False, constraint=None, sk_picker=None):
        # Ambient-RNG alignment (controller ruling): surrokit.ask() calls
        # torch.manual_seed(seed) at entry so an identical call is
        # reproducible regardless of prior torch global-RNG state (added
        # in a fix round -- otherwise ambient state leaks into
        # fit_gpytorch_mll/optimize_acqf draws and identical calls
        # diverge). The legacy bp.compute_explore_picks has NO such entry
        # seed, so it inherits whatever the *ambient* torch RNG happens to
        # be at call time. To compare like for like we pin that ambient
        # stream ourselves, immediately before the OLD call, to the same
        # seed surrokit will use internally on its own -- otherwise
        # old-vs-new diverges for reasons unrelated to port correctness.
        torch.manual_seed(bp._seed(round_idx))
        old = bp.compute_explore_picks(MODE, q=q, round_idx=round_idx,
                                       picker=picker, x_pending=pending)
        X, Y, _, _ = bp._load_history_tensor(MODE, sob_only=sob_only)
        new = surrokit.ask(_problem(sob_only, constraint),
                           X.tolist(), Y.tolist(), q=q,
                           picker=sk_picker or picker,
                           seed=bp._seed(round_idx), pending=pending)
        self.assertEqual([list(t) for t in old], new,
                         f"parity broken for picker={picker}")

    def test_qnehvi(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qnehvi")

    def test_qnehvi_nonzero_round_and_pending(self):
        spec = _modes.SPECS[MODE]
        mid = [ (lo + hi) / 2.0 for lo, hi in
                zip(spec.bounds_lo, spec.bounds_hi) ]
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qnehvi", round_idx=3, pending=[mid])

    def test_qlnei(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qlnei", sob_only=True)

    def test_hybrid(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("hybrid")

    def test_budget_sob_as_constrained_max(self):
        budget = 1.0e-3  # generous: fixture flash values are well inside
        c = surrokit.Constraint(axis=1, min=-math.log10(budget),
                                k_sigma=bp.BUDGET_SOB_K_SIGMA)
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp), \
             mock.patch.object(bp, "DEP_FLASH_PER_POT", budget):
            self._compare("budget_sob", constraint=c,
                          sk_picker="constrained_max")

    def test_cold_start(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            self._compare("qnehvi", q=4, round_idx=1)


if __name__ == "__main__":
    unittest.main()
