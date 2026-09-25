"""AutoresearchAdapter: serve schema-2 studies + leaderboards to surrokit.

Problem assembly and the -log10 transform live in core/botorch_predict.py
(build_problem / load_history_tensor -- the same seam production picks
use); this adapter only shapes them for surrokit.mcp_scaffold and adds
the axis labels so MCP clients can interpret the numbers.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402

if TYPE_CHECKING:  # annotation only; botorch_predict puts surrokit on sys.path
    import surrokit


def _board_summary(name: str) -> dict:
    """Champion by the primary objective (direction-aware) and its observed
    range, for the MCP `stats` tool (the scaffold's stats is n_rows + meta).
    The champion's values are nested under "values" so no objective name
    (a study may legally name one `x` or `config`) can overwrite a key."""
    study = _modes.STUDIES[name]
    prim = study.objectives[0]
    pts = [p for p in bp.history_points(name)
           if p.y.get(prim.name) is not None and math.isfinite(p.y[prim.name])]
    if not pts:
        return {}
    pick = max if prim.direction == "max" else min
    best = pick(pts, key=lambda p: p.y[prim.name])
    vals = [p.y[prim.name] for p in pts]
    return {"best": {"config": best.cfg, "x": list(best.x),
                     "values": dict(best.y)},
            "primary_range": [min(vals), max(vals)]}


def _axis_label(o) -> str:
    inner = f"log10({o.name})" if o.transform == "log10" else o.name
    return inner if o.direction == "max" else f"-{inner}"


class AutoresearchAdapter:
    def problems(self) -> dict[str, surrokit.Problem]:
        return {name: bp.build_problem(name) for name in _modes.STUDIES}

    def suggest(self, name: str, q: int = 5, picker: str | None = None,
                round_idx: int = 0, pending: list | None = None):
        """The production pick path: same vocabulary (qnehvi | qlnei |
        budget_sob | hybrid), same sob-only history policy for qlnei, and
        the closed loop's 42^round_idx seed -- picks are what a real
        round would submit. picker=None means the registry default."""
        if name not in _modes.STUDIES:
            raise ValueError(f"unknown problem {name!r}; choose from "
                             f"{sorted(_modes.STUDIES)}")
        picker = picker or _modes.DEFAULT_PICKER
        if picker not in _modes.PICKER_CHOICES:
            raise ValueError(f"unknown picker {picker!r}; choose from "
                             f"{_modes.PICKER_CHOICES}")
        picks = bp.compute_explore_picks(name, q=q, round_idx=round_idx,
                                         picker=picker, x_pending=pending)
        return [list(p) for p in picks]

    def history(self, name: str):
        study = _modes.STUDIES[name]
        X, Y, _, _ = bp.load_history_tensor(name)
        meta = {
            "objectives": [{"name": o.name, "direction": o.direction,
                            "transform": o.transform, "axis": _axis_label(o)}
                           for o in study.objectives],
            "knobs": [{"name": k.name, "type": k.type, "unit": k.unit,
                       "min": k.min, "max": k.max} for k in study.knobs],
            "knob_names": list(study.knob_names),
            "leaderboard": study.leaderboard_rel,
        }
        meta.update(_board_summary(name))
        return X.tolist(), Y.tolist(), meta
