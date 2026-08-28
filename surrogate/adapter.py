"""AutoresearchAdapter: serve ModeSpec registry + leaderboards to surrokit.

The physics stays here: Y axis 1 is -log10(metric2), the budget
constraint is -log10(AUTORESEARCH_FLASH_BUDGET), and meta carries the
axis labels so MCP clients can interpret the numbers.
"""
from __future__ import annotations

import math
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
        out = {}
        for name, spec in _modes.SPECS.items():
            out[name] = surrokit.Problem(
                bounds_lo=tuple(spec.bounds_lo),
                bounds_hi=tuple(spec.bounds_hi),
                int_dims=tuple(spec.int_dims),
                noise=tuple(spec.obs_noise),
                constraint=surrokit.Constraint(
                    axis=1, min=-math.log10(bp.DEP_FLASH_PER_POT),
                    k_sigma=bp.BUDGET_SOB_K_SIGMA),
            )
        return out

    def history(self, name: str):
        spec = _modes.SPECS[name]
        X, Y, _, _ = bp._load_history_tensor(name)
        meta = {
            "objectives": ["sob", f"neg_log10_{spec.metric_cols[1]}"],
            "knob_names": list(spec.knob_names),
            "leaderboard": spec.leaderboard_rel,
        }
        return X.tolist(), Y.tolist(), meta
