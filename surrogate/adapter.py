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

    def suggest(self, name: str, q: int = 5, picker: str | None = None,
                round_idx: int = 0, pending: list | None = None):
        """The production pick path: same vocabulary (qnehvi | qlnei |
        budget_sob | hybrid), same sob-only history policy for qlnei, and
        the closed loop's 42^round_idx seed -- picks are what a real
        round would submit. picker=None means the registry default."""
        if name not in _modes.SPECS:
            raise ValueError(f"unknown problem {name!r}; choose from "
                             f"{sorted(_modes.SPECS)}")
        picker = picker or _modes.DEFAULT_PICKER
        if picker not in _modes.PICKER_CHOICES:
            raise ValueError(f"unknown picker {picker!r}; choose from "
                             f"{_modes.PICKER_CHOICES}")
        picks = bp.compute_explore_picks(name, q=q, round_idx=round_idx,
                                         picker=picker, x_pending=pending)
        return [list(p) for p in picks]

    def history(self, name: str):
        spec = _modes.SPECS[name]
        X, Y, _, _ = bp.load_history_tensor(name)
        meta = {
            "objectives": ["sob", f"neg_log10_{spec.metric_cols[1]}"],
            "knob_names": list(spec.knob_names),
            "leaderboard": spec.leaderboard_rel,
        }
        return X.tolist(), Y.tolist(), meta
