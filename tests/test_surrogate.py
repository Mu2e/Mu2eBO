"""Tests for the MCP surrogate door (adapter + server wiring).

Reuses the foilsflash fixture leaderboard from test_botorch_predict —
bo.MODES["foilsflash"].leaderboard is repointed at a tmp TSV; live
leaderboards are never touched. The MCP test is skipped where the `mcp`
SDK is absent (it ships in ana 2.8.0 but not in the dev venv).

The plain-Python facade these tests used to cover was deleted 2026-09-22
(zero callers); see surrogate/__init__.py."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_botorch_predict import (  # noqa: E402
    patched_leaderboard,
)

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


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

    def test_problems_refuse_a_removed_env_override(self):
        """The MCP door takes the same build_problem path, so a stale
        AUTORESEARCH_BUDGET_KSIGMA / AUTORESEARCH_FLASH_BUDGET export is
        fatal there too, not silently ignored."""
        from surrogate.adapter import AutoresearchAdapter
        for var in ("AUTORESEARCH_FLASH_BUDGET", "AUTORESEARCH_BUDGET_KSIGMA"):
            with self.subTest(var=var), \
                 mock.patch.dict(os.environ, {var: "0.5"}):
                with self.assertRaises(SystemExit) as cm:
                    AutoresearchAdapter().problems()
                self.assertIn(var, str(cm.exception))

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
            self.assertEqual([o["axis"] for o in meta["objectives"]],
                             ["sob", "-log10(flash_edep)"])

    def test_meta_carries_board_summary(self):
        """Champion + primary-objective range ride in history() meta, which
        is what the scaffold's `stats` tool returns. Ported from the deleted
        surrogate.board_stats facade (2026-09-22) -- same assertions."""
        from surrogate.adapter import AutoresearchAdapter
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            _, _, meta = AutoresearchAdapter().history("foilsflash")
            self.assertEqual(meta["best"]["config"], "cfg009")
            self.assertAlmostEqual(meta["best"]["sob"], 3.8, places=4)
            self.assertAlmostEqual(meta["primary_range"][0], 3.0, places=4)
            self.assertAlmostEqual(meta["primary_range"][1], 3.8, places=4)


if __name__ == "__main__":
    unittest.main()
