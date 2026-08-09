"""Picker tests for core/botorch_predict.py (main suite since the 2026-07-18
single-venv consolidation) + the botorch_ask subprocess seam smoke.

Fixtures repoint bo.MODES["foilsflash"].leaderboard at a tmp 10-row TSV
(foilsflash: load_priors()==[] so history is exactly the fixture). The live
leaderboards are never touched."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402

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
    return mock.patch.object(bo.MODES["foilsflash"], "leaderboard", lb)


BOUNDS_LO = bp.MODE_SPECS["foilsflash"]["lo"]
BOUNDS_HI = bp.MODE_SPECS["foilsflash"]["hi"]


def in_bounds(x):
    return all(lo - 1e-9 <= v <= hi + 1e-9
               for v, lo, hi in zip(x, BOUNDS_LO, BOUNDS_HI))


class TestLoadHistoryTensor(unittest.TestCase):
    def test_parses_rows_and_log_transforms_second_objective(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, int_dims = bp._load_history_tensor("foilsflash")
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
            X, Y, _, _ = bp._load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (10, 6))

    def test_sob_only_path_is_1d(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            _, Y, _, _ = bp._load_history_tensor("foilsflash", sob_only=True)
            self.assertEqual(tuple(Y.shape), (10, 1))

    def test_width_guard_systemexit_on_dim_mismatch(self):
        wrong = [bo.Point(cfg="w", x=[1.0, 2.0, 3.0], sob=1.0, calo=1e-7)]
        with mock.patch.object(bo.MODES["foilsflash"], "load_history",
                               return_value=wrong):
            with self.assertRaises(SystemExit):
                bp._load_history_tensor("foilsflash")

    def test_cold_start_returns_empty_with_correct_width(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            X, Y, _, _ = bp._load_history_tensor("foilsflash")
            self.assertEqual(tuple(X.shape), (0, 6))
            self.assertEqual(tuple(Y.shape), (0, 2))


class TestSeedAndEmit(unittest.TestCase):
    def test_seed_is_xor_not_pow(self):
        # 42^1=43, 42^2=40, 42^3=41 under XOR; pow would explode.
        self.assertEqual([bp._seed(i) for i in range(4)], [42, 43, 40, 41])

    def test_emit_picks_native_types_and_int_rounding(self):
        import torch
        out = bp._emit_picks(torch.tensor([[1.4, 2.6]]), int_dims=[1])
        self.assertEqual(out, [(1.4, 3)])
        self.assertIsInstance(out[0][0], float)
        self.assertIsInstance(out[0][1], int)

    def test_sobol_cold_start_deterministic_and_in_bounds(self):
        import torch
        bounds = torch.tensor([BOUNDS_LO, BOUNDS_HI])
        a = bp._sobol_cold_start(bounds, q=3, round_idx=5)
        b = bp._sobol_cold_start(bounds, q=3, round_idx=5)
        self.assertTrue(torch.equal(a, b))
        self.assertEqual(tuple(a.shape), (3, 6))
        for row in a.tolist():
            self.assertTrue(in_bounds(row))


class TestComputeExplorePicks(unittest.TestCase):
    def test_cold_start_path_returns_q_picks(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            picks = bp.compute_explore_picks(q=2, mode="foilsflash",
                                             round_idx=0)
            self.assertEqual(len(picks), 2)
            for p in picks:
                self.assertTrue(in_bounds(p))

    def test_obs_noise_reaches_the_likelihood(self):
        # The wiring this file exists to pin: modes.obs_noise must land in
        # the GP as train_Yvar, not be silently dropped. Recovering raw
        # sigma = sqrt(likelihood.noise) * Standardize.stdvs must return the
        # declared per-axis sigma. Dropping the kwarg makes the fit infer
        # noise ~12x too large (see _fit_gp docstring).
        import torch
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, _ = bp._load_history_tensor("foilsflash")
        declared = bp.MODE_SPECS["foilsflash"]["obs_noise"]
        model = bp._fit_gp(X, Y, bounds, obs_noise=declared)
        m = Y.shape[-1]
        noise = model.likelihood.noise.detach()
        # Fixed-noise likelihoods carry the full (m, n) train_Yvar, not (m,);
        # the audit print in _fit_gp collapses it the same way.
        per_axis = (noise.reshape(-1) if noise.numel() == m
                    else noise.reshape(m, -1)[:, 0]).sqrt()
        raw = per_axis * model.outcome_transform.stdvs.detach().reshape(-1)
        for got, want in zip(raw.tolist(), declared):
            self.assertAlmostEqual(got, want, places=6)
        self.assertIsInstance(
            model.likelihood,
            torch.nn.Module)  # sanity: real likelihood, not a stub

    def test_pinned_noise_does_not_shrink_a_high_observation(self):
        # Behavioural half: with honest noise the posterior must stay close
        # to what was measured at a training point. The production failure
        # was a 0.113 shrink on the best row, which demoted it to rank 16.
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, bounds, _ = bp._load_history_tensor("foilsflash")
        declared = bp.MODE_SPECS["foilsflash"]["obs_noise"]
        model = bp._fit_gp(X, Y, bounds, obs_noise=declared)
        best = int(Y[:, 0].argmax())
        mu = model.posterior(X).mean.detach()[:, 0]
        self.assertAlmostEqual(float(mu[best]), float(Y[best, 0]), delta=0.05)
        self.assertEqual(int(mu.argmax()), best,
                         "highest observed sob must also be the GP's argmax")

    # test_prodtarget_family_keeps_free_noise removed 2026-08-08: pinned
    # obs_noise=None (a deliberate declaration -- axis-1 units depend on
    # which fallback fired) for the ProdTarget family specifically. Both
    # "prodtarget" and "prodtarget6d" were archived (Python-mode adapters
    # deleted; no JSON replacement), and no surviving mode declares
    # obs_noise=None -- there is nothing left to pin this fact against.

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


if __name__ == "__main__":
    unittest.main()
