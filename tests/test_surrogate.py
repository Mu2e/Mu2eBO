"""Tests for the surrogate package (and a light MCP-adapter check).

Reuses the foilsflash fixture leaderboard from test_botorch_predict —
bo.MODES["foilsflash"].leaderboard is repointed at a tmp TSV; live
leaderboards are never touched. The MCP test is skipped where the `mcp`
SDK is absent (it ships in ana 2.8.0 but not in the dev venv)."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import surrogate  # noqa: E402
from tests.test_botorch_predict import (  # noqa: E402
    patched_leaderboard, write_fixture, in_bounds,
)

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


class TestModesInfo(unittest.TestCase):
    def test_foilsflash_entry_matches_spec(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            info = surrogate.modes_info()["foilsflash"]
            self.assertEqual(info["dims"], 6)
            self.assertEqual(info["objectives"], ["sob", "flash_edep"])
            self.assertEqual(info["n_rows"], 10)


class TestFitCache(unittest.TestCase):
    def test_cache_hit_and_row_count_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            surrogate._FITS.clear()
            m1 = surrogate.fit("foilsflash")
            self.assertIs(surrogate.fit("foilsflash"), m1)
            lb = Path(tmp) / "leaderboard_bo_foilsflash.tsv"
            write_fixture(lb, n=11)
            self.assertIsNot(surrogate.fit("foilsflash"), m1)

    def test_too_few_rows_raises(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patched_leaderboard(tmp, n=1):
            surrogate._FITS.clear()
            with self.assertRaises(RuntimeError):
                surrogate.fit("foilsflash")

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            surrogate.fit("nope")


class TestPredict(unittest.TestCase):
    def test_posterior_near_training_point(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            surrogate._FITS.clear()
            # Fixture row u=0: x as in write_fixture, sob=3.0, flash=1e-7.
            x0 = [50.0, 250.0, 0.002, 0.9, 0.05, 0.9]
            (r,) = surrogate.predict("foilsflash", [x0])
            self.assertAlmostEqual(r["sob_mean"], 3.0, delta=0.15)
            self.assertGreater(r["flash_edep_mean"], 0)
            self.assertLess(r["flash_edep_lo"], r["flash_edep_hi"])
            self.assertGreater(r["sob_sigma"], 0)

    def test_dim_mismatch_raises(self):
        with self.assertRaises(ValueError):
            surrogate.predict("foilsflash", [[1.0, 2.0]])


class TestSuggest(unittest.TestCase):
    def test_picks_in_bounds(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            surrogate._FITS.clear()
            picks = surrogate.suggest("foilsflash", q=2, picker="qnehvi")
            self.assertEqual(len(picks), 2)
            for p in picks:
                self.assertTrue(in_bounds(p))

    def test_unknown_picker_raises(self):
        with self.assertRaises(ValueError):
            surrogate.suggest("foilsflash", picker="nope")


class TestBoardStats(unittest.TestCase):
    def test_champion_and_range(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            s = surrogate.board_stats("foilsflash")
            self.assertEqual(s["n_rows"], 10)
            self.assertEqual(s["best_sob"]["config"], "cfg009")
            self.assertAlmostEqual(s["best_sob"]["sob"], 3.8, places=4)
            self.assertAlmostEqual(s["sob_range"][0], 3.0, places=4)


@unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
class TestMcpAdapter(unittest.TestCase):
    def test_tool_names(self):
        import surrogate.mcp_server as ms
        tools = asyncio.run(ms.server.list_tools())
        names = sorted(t.name for t in tools)
        self.assertEqual(names, ["list_problems", "predict", "refit",
                                 "stats", "suggest"])
        # The adapter provides suggest(), so the tool speaks round_idx
        # (production seed derivation), not a raw engine seed.
        sg = next(t for t in tools if t.name == "suggest")
        props = (sg.input_schema if hasattr(sg, "input_schema")
                 else sg.inputSchema)["properties"]
        self.assertIn("round_idx", props)
        self.assertNotIn("seed", props)


class TestAutoresearchAdapter(unittest.TestCase):
    def test_problems_cover_all_modes(self):
        from surrogate.adapter import AutoresearchAdapter
        import modes as _modes
        probs = AutoresearchAdapter().problems()
        self.assertEqual(sorted(probs), sorted(_modes.SPECS))
        for name, prob in probs.items():
            spec = _modes.SPECS[name]
            self.assertEqual(prob.dim, len(spec.knob_names))
            self.assertEqual(prob.noise, tuple(spec.obs_noise))
            self.assertIsNotNone(prob.constraint)

    def test_suggest_is_production_pick_path(self):
        from surrogate.adapter import AutoresearchAdapter
        import botorch_predict as bp
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            got = AutoresearchAdapter().suggest(
                "foilsflash", q=2, picker="qnehvi", round_idx=1)
            want = [list(t) for t in bp.compute_explore_picks(
                "foilsflash", q=2, round_idx=1, picker="qnehvi")]
            self.assertEqual(got, want)

    def test_suggest_rejects_unknowns(self):
        from surrogate.adapter import AutoresearchAdapter
        a = AutoresearchAdapter()
        with self.assertRaisesRegex(ValueError, "unknown problem"):
            a.suggest("nope")
        with self.assertRaisesRegex(ValueError, "unknown picker"):
            a.suggest("foilsflash", picker="qnparego")

    def test_history_shape_and_meta(self):
        from surrogate.adapter import AutoresearchAdapter
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, meta = AutoresearchAdapter().history("foilsflash")
            self.assertEqual(len(X), len(Y))
            self.assertEqual(len(Y[0]), 2)
            self.assertIn("objectives", meta)


if __name__ == "__main__":
    unittest.main()
