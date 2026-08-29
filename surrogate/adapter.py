"""AutoresearchAdapter: serve ModeSpec registry + leaderboards to surrokit.

Problem assembly and the -log10 transform live in core/botorch_predict.py
(build_problem / load_history_tensor -- the same seam production picks
use); this adapter only shapes them for surrokit.mcp_scaffold and adds
the axis labels so MCP clients can interpret the numbers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from paths import SURROKIT_ROOT  # noqa: E402
sys.path.insert(0, str(SURROKIT_ROOT))

import surrokit  # noqa: E402
import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402


class AutoresearchAdapter:
    def problems(self) -> dict[str, surrokit.Problem]:
        return {name: bp.build_problem(name) for name in _modes.SPECS}

    def history(self, name: str):
        spec = _modes.SPECS[name]
        X, Y, _, _ = bp.load_history_tensor(name)
        meta = {
            "objectives": ["sob", f"neg_log10_{spec.metric_cols[1]}"],
            "knob_names": list(spec.knob_names),
            "leaderboard": spec.leaderboard_rel,
        }
        return X.tolist(), Y.tolist(), meta
