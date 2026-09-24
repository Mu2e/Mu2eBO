#!/usr/bin/env python3
"""BoTorch pickers for any study (objectives, transforms and the constraint from modes.STUDIES).

THE production picker: graph/closed_loop.py shells this CLI every round
(--emit-picks-json round-trip; keep argparse-compatible). Pickers: qnehvi,
qlnei, budget_sob, hybrid — see compute_explore_picks.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import REPO_ROOT as AUTORESEARCH  # noqa: E402,F401  (pinned by
import bo_driver as bo  # noqa: E402      tests/test_paths.py: every module
#                                          agrees on ONE resolved root)


# float64 + CPU: history is tiny (<200 pts), CPU beats GPU incl. transfer.
torch.set_default_dtype(torch.float64)
DEVICE = torch.device("cpu")


# Bounds + integer-dim mask come straight off the ModeSpec registry
# (ADR-0002). Order matches Point.x (= build_space); lockstep ENFORCED by
# tests/test_modes.py.
import modes as _modes  # noqa: E402

from paths import SURROKIT_ROOT  # noqa: E402
sys.path.insert(0, str(SURROKIT_ROOT))
import surrokit  # noqa: E402


def axis_value(obj, v):
    """Raw metric -> the maximized surrogate axis (surrokit's math space),
    or None when it is undefined (missing, non-finite, or <= 0 under log10).
    """
    if v is None or not math.isfinite(v):
        return None
    if obj.transform == "log10":
        if v <= 0:
            return None
        v = math.log10(v)
    return v if obj.direction == "max" else -v


def _objectives(study, primary_only):
    return study.objectives[:1] if primary_only else study.objectives


def load_history_tensor(mode: str, primary_only: bool = False):
    """(X, Y, bounds, int_dims) over the study's search space. Y has one
    maximized column per objective (primary_only: the first objective only);
    a row with any undefined axis value is left out."""
    if mode not in _modes.STUDIES:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(_modes.STUDIES)}.")
    study = _modes.STUDIES[mode]
    objs = _objectives(study, primary_only)
    X_rows, Y_rows = [], []
    for p in bo.MODES[mode].load_history():
        ys = [axis_value(o, p.y.get(o.name)) for o in objs]
        if any(y is None for y in ys):
            continue
        X_rows.append([float(v) for v in p.x])
        Y_rows.append(ys)
    lo = torch.tensor(list(study.bounds_lo), device=DEVICE)
    hi = torch.tensor(list(study.bounds_hi), device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)
    d = len(study.bounds_lo)
    if X_rows:
        X = torch.tensor(X_rows, device=DEVICE)
        Y = torch.tensor(Y_rows, device=DEVICE)
        if X.shape[1] != d:
            raise SystemExit(
                f"[botorch_predict] mode={mode} dim mismatch: history has "
                f"{X.shape[1]}D points but the study declares {d} knobs "
                f"({study.knob_names}).")
    else:
        X = torch.empty((0, d), device=DEVICE)
        Y = torch.empty((0, len(objs)), device=DEVICE)
    return X, Y, bounds, list(study.int_dims)


def _seed(round_idx: int) -> int:
    """Per-round seed `42 ^ round_idx` (xor, NOT pow — see
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md); single home."""
    return 42 ^ int(round_idx)


def _problem_from(study, primary_only: bool) -> "surrokit.Problem":
    objs = _objectives(study, primary_only)
    constraint = None
    for c in study.constraints:
        axes = [i for i, o in enumerate(objs) if o.name == c.name]
        if not axes:
            continue    # constrained objective not in this problem
        i = axes[0]
        # The loader fixed the bound's side so the transformed bound is a
        # LOWER bound on the maximized axis (surrokit: mean - k*sigma >= min).
        constraint = surrokit.Constraint(
            axis=i, min=axis_value(objs[i], c.value), k_sigma=c.k_sigma)
    return surrokit.Problem(
        bounds_lo=tuple(study.bounds_lo), bounds_hi=tuple(study.bounds_hi),
        int_dims=tuple(study.int_dims),
        noise=tuple(o.noise for o in objs), constraint=constraint)


def build_problem(mode: str, primary_only: bool = False) -> "surrokit.Problem":
    """The single home for surrokit.Problem assembly over a study."""
    return _problem_from(_modes.STUDIES[mode], primary_only)


def compute_explore_picks(mode: str,
                          q: int = 5,
                          round_idx: int = 0,
                          picker: str = "qnehvi",
                          x_pending: list | None = None,
                          ) -> list[tuple]:
    """Explore-pick engine: picker = qnehvi | qlnei | budget_sob | hybrid.

    Thin glue over surrokit.ask: this side owns leaderboard loading, the
    -log10 transform, env-tunable constants, and the 42^round_idx seed
    convention; the engine owns the GP and the pickers.
    """
    primary_only = (picker == "qlnei")
    X, Y, bounds, int_dims = load_history_tensor(mode, primary_only=primary_only)
    if x_pending:
        pend_width = len(x_pending[0])
        if pend_width != bounds.shape[-1]:
            raise SystemExit(
                f"[botorch_predict] x_pending dim {pend_width} != "
                f"search-space dim {bounds.shape[-1]} for mode={mode}")
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
    study = _modes.STUDIES[mode]
    if picker == "budget_sob" and not study.constraints:
        raise SystemExit(f"[botorch_predict] picker budget_sob needs a "
                         f"constraint, and study {mode!r} declares none")
    sk_picker = "constrained_max" if picker == "budget_sob" else picker
    problem = build_problem(mode, primary_only=primary_only)
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    try:
        picks = surrokit.ask(problem, X.tolist(), Y.tolist(), q=q,
                             picker=sk_picker, seed=_seed(round_idx),
                             pending=x_pending, hv_frac=hv_frac)
    except surrokit.InfeasibleError as e:
        c = study.constraints[0]
        op = "<=" if c.bound == "max" else ">="
        raise SystemExit(
            f"[botorch_predict] budget_sob: GP predicts NO point in the "
            f"search box with {c.name} {op} {c.value:.3e} ({e}); refusing "
            f"to submit blind picks.")
    return [tuple(row) for row in picks]


def main(argv=None):
    import logging
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[surrokit] %(message)s"))
    _sk = logging.getLogger("surrokit")
    if not _sk.handlers:
        _sk.addHandler(_h)
        _sk.setLevel(logging.INFO)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(_modes.SPECS), required=True,
                    help="BO mode to refit")
    ap.add_argument("--q", type=int, default=5,
                    help="Batch size (default 5)")
    ap.add_argument("--round-idx", type=int, default=0,
                    help="Round index; seeds MC sampler (default 0)")
    ap.add_argument("--picker", choices=_modes.PICKER_CHOICES,
                    default="qnehvi",
                    help="qnehvi = multi-obj Pareto-HV (default); "
                         "qlnei = single-obj qLogNoisyEI on sob only; "
                         "budget_sob = GP-mean sob corner constrained to the "
                         "deployed damage budget; "
                         "hybrid = ~60%% qnehvi + ~40%% qnparego "
                         "(recommended for new multi-objective lines)")
    ap.add_argument("--emit-picks-json", type=str, default=None,
                    help="If set, write picks as JSON to this path")
    ap.add_argument("--pending-json", type=str, default=None,
                    help="JSON file: list of x-lists for in-flight evals "
                         "(rolling closed-loop); pickers fantasize over them "
                         "via X_pending")
    ap.add_argument("--leaderboard", type=str, default=None,
                    help="Override the mode's leaderboard TSV path (tests + "
                         "golden harness only; live callers omit it)")
    ns = ap.parse_args(argv)
    if ns.leaderboard:
        bo.MODES[ns.mode].leaderboard = Path(ns.leaderboard)
        bo.MODES[ns.mode].leaderboard_archive = None
        print(f"[botorch_predict] leaderboard override: {ns.leaderboard}",
              flush=True)

    x_pending = None
    if ns.pending_json:
        x_pending = json.loads(Path(ns.pending_json).read_text())
        print(f"[botorch_predict] pending-aware: {len(x_pending)} in-flight "
              f"evals loaded from {ns.pending_json}", flush=True)

    picks = compute_explore_picks(q=ns.q, mode=ns.mode,
                                  round_idx=ns.round_idx, picker=ns.picker,
                                  x_pending=x_pending)

    if ns.emit_picks_json:
        Path(ns.emit_picks_json).write_text(json.dumps(picks, indent=2))
        print(f"[botorch_predict] mode={ns.mode} wrote {len(picks)} picks "
              f"-> {ns.emit_picks_json}")
    else:
        for i, p in enumerate(picks):
            print(f"pick {i} ({ns.mode}): {p}")


if __name__ == "__main__":
    main()
