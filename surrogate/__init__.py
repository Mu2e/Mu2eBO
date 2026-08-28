"""The GP surrogate behind the BO pickers, as a clean importable seam.

Plain-Python clients (plotting scripts, orchestrators) import this module;
LLM agents reach the same functions through surrogate/mcp_server.py, a thin
MCP adapter. First-order wrapper per the 2026-08-28 agreement with Simon
Corrodi: no logic moves — everything delegates to core/botorch_predict.py
(the production picker stack) so the surrogate can never drift from what
the closed loop actually optimizes.

API:
    modes_info()                      -> registry snapshot (dims, bounds, ...)
    fit(mode, refresh=False)          -> fitted SingleTaskGP (cached per mode)
    predict(mode, points)             -> posterior mean/sigma per point
    suggest(mode, q, picker, ...)     -> candidate x-points (the real pickers)
    board_stats(mode)                 -> leaderboard summary

The GP is fit on the mode's live leaderboard exactly as the closed loop fits
it (train_Yvar from ModeSpec.obs_noise; Y = [sob, -log10(metric2)]). The fit
cache is invalidated by leaderboard row count, so a long-lived process (the
MCP server) picks up new evals on the next call.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import torch  # noqa: E402

import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402

# mode -> (model, n_rows_at_fit). Row count is the invalidation key: the
# leaderboard is append-only, so "same count" == "same history".
_FITS: dict[str, tuple[object, int]] = {}


def _spec(mode: str) -> _modes.ModeSpec:
    if mode not in _modes.SPECS:
        raise ValueError(f"unknown mode {mode!r}; choose from "
                         f"{sorted(_modes.SPECS)}")
    return _modes.SPECS[mode]


def modes_info() -> dict:
    """One entry per registered mode: dimensionality, knobs, bounds, metrics."""
    out = {}
    for name, spec in sorted(_modes.SPECS.items()):
        out[name] = {
            "dims": len(spec.knob_names),
            "knob_names": list(spec.knob_names),
            "bounds_lo": list(spec.bounds_lo),
            "bounds_hi": list(spec.bounds_hi),
            "int_dims": list(spec.int_dims),
            "objectives": ["sob", spec.metric_cols[1]],
            "obs_noise": list(spec.obs_noise),
            "n_rows": len(bo.MODES[name].load_history()),
        }
    return out


def fit(mode: str, refresh: bool = False):
    """Fit (or return the cached) GP for `mode` on its current leaderboard.

    Same fit as production: bp._load_history_tensor + bp._fit_gp with the
    mode's pinned obs_noise (wiki/incidents/gp-free-noise-erases-champion.md).
    Raises RuntimeError below 2 usable history rows — the surrogate has
    nothing to say there (the pickers fall back to Sobol; prediction cannot).
    """
    spec = _spec(mode)
    X, Y, bounds, _ = bp._load_history_tensor(mode)
    n = X.shape[0]
    cached = _FITS.get(mode)
    if cached is not None and cached[1] == n and not refresh:
        return cached[0]
    if n < 2:
        raise RuntimeError(f"mode={mode}: only {n} usable history rows; "
                           "need >= 2 to fit a GP")
    model = bp._fit_gp(X, Y, bounds, obs_noise=list(spec.obs_noise))
    _FITS[mode] = (model, n)
    return model


def predict(mode: str, points: list[list[float]]) -> list[dict]:
    """GP posterior at each point. Returns one dict per point.

    Output axis 0 is sob (direct). Axis 1 is -log10(metric2); it is reported
    both in log space (mean/sigma) and inverted to linear units as a point
    estimate with a 1-sigma interval [lo, hi]. metric2 is named from the
    mode's metric_cols (calo_per_pot or flash_edep).
    """
    spec = _spec(mode)
    d = len(spec.knob_names)
    for i, p in enumerate(points):
        if len(p) != d:
            raise ValueError(f"point {i} has {len(p)} values; mode={mode} "
                             f"needs {d} ({', '.join(spec.knob_names)})")
    model = fit(mode)
    Xq = torch.tensor([[float(v) for v in p] for p in points],
                      dtype=torch.float64)
    with torch.no_grad():
        post = model.posterior(Xq)
        mean = post.mean
        sig = post.variance.clamp_min(0).sqrt()
    m2 = spec.metric_cols[1]
    out = []
    for i in range(len(points)):
        lm, ls = float(mean[i, 1]), float(sig[i, 1])
        out.append({
            "sob_mean": float(mean[i, 0]),
            "sob_sigma": float(sig[i, 0]),
            f"{m2}_mean": 10.0 ** (-lm),
            f"{m2}_lo": 10.0 ** (-(lm + ls)),
            f"{m2}_hi": 10.0 ** (-(lm - ls)),
            f"neg_log10_{m2}_mean": lm,
            f"neg_log10_{m2}_sigma": ls,
        })
    return out


def suggest(mode: str, q: int = 5, picker: str = _modes.DEFAULT_PICKER,
            round_idx: int = 0, x_pending: list | None = None) -> list[list]:
    """Candidate x-points from the production pickers (compute_explore_picks).

    Exactly what a closed-loop round would submit: qnehvi | qlnei |
    budget_sob | hybrid, Sobol cold-start below 2 history rows. Pure
    computation — nothing is submitted or written anywhere.
    """
    _spec(mode)
    if picker not in _modes.PICKER_CHOICES:
        raise ValueError(f"unknown picker {picker!r}; choose from "
                         f"{_modes.PICKER_CHOICES}")
    picks = bp.compute_explore_picks(mode, q=q, round_idx=round_idx,
                                     picker=picker, x_pending=x_pending)
    return [list(p) for p in picks]


def board_stats(mode: str) -> dict:
    """Leaderboard summary: row count, champion, objective ranges."""
    spec = _spec(mode)
    pts = bo.MODES[mode].load_history()
    out = {"mode": mode, "n_rows": len(pts),
           "objectives": ["sob", spec.metric_cols[1]],
           "leaderboard": spec.leaderboard_rel}
    finite = [p for p in pts if p.sob is not None and math.isfinite(p.sob)]
    if finite:
        best = max(finite, key=lambda p: p.sob)
        out["best_sob"] = {"config": best.cfg, "x": list(best.x),
                           "sob": best.sob, spec.metric_cols[1]: best.calo}
        out["sob_range"] = [min(p.sob for p in finite),
                            max(p.sob for p in finite)]
    return out
