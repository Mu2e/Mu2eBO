#!/usr/bin/env python3
"""BoTorch pickers for any pure-numeric mode (bounds from modes.SPECS).

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


def load_history_tensor(mode: str, sob_only: bool = False):
    """Return (X, Y, bounds, int_dims) tensors over the mode's search space.

    Y is (n, 2) [sob, -log10(calo)], both maximized; sob_only=True gives
    (n, 1) [sob] and keeps rows with invalid calo (qlnei picker).
    """
    if mode not in _modes.SPECS:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(_modes.SPECS)}.")
    spec = _modes.SPECS[mode]
    seeds = bo.MODES[mode].load_history()

    X_rows = []
    Y_rows = []
    for p in seeds:
        if sob_only:
            if p.sob is None or not math.isfinite(p.sob):
                continue
            X_rows.append([float(v) for v in p.x])
            Y_rows.append([p.sob])
        else:
            if p.calo <= 0:
                continue  # log10 undefined (broken harvest)
            X_rows.append([float(v) for v in p.x])
            Y_rows.append([p.sob, -math.log10(p.calo)])
    lo = torch.tensor(list(spec.bounds_lo), device=DEVICE)
    hi = torch.tensor(list(spec.bounds_hi), device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)

    if X_rows:
        X = torch.tensor(X_rows, device=DEVICE)
        Y = torch.tensor(Y_rows, device=DEVICE)
        if X.shape[1] != len(spec.bounds_lo):
            raise SystemExit(
                f"[botorch_predict] mode={mode} dim mismatch: history has "
                f"{X.shape[1]}D points but modes.SPECS[{mode!r}] declares "
                f"{len(spec.bounds_lo)}D bounds (knobs: "
                f"{spec.knob_names}). Leaderboard schema and "
                f"registry disagree.")
    else:
        # Cold start: empty (0, d) tensors with correct d so downstream
        # shape-checks against `bounds` pass; caller switches to Sobol.
        d = len(spec.bounds_lo)
        m = 1 if sob_only else 2
        X = torch.empty((0, d), device=DEVICE)
        Y = torch.empty((0, m), device=DEVICE)
    return X, Y, bounds, list(spec.int_dims)


def _seed(round_idx: int) -> int:
    """Per-round seed `42 ^ round_idx` (xor, NOT pow — see
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md); single home."""
    return 42 ^ int(round_idx)


# Env-tunable budget knobs are read at CALL time (not import) so a
# long-lived process (the MCP server) honors the environment it runs in.
def flash_budget() -> float:
    """The DEPLOYED stopping target's damage in MeV/POT — the deployment
    constraint line, not a tuning knob. Env-overridable for other scenarios."""
    return float(os.environ.get("AUTORESEARCH_FLASH_BUDGET", "6.85443e-7"))


def budget_k_sigma() -> float:
    """budget_sob feasibility margin in posterior sigmas: k=0 constrains the
    MEAN (~50% of picks land over budget once measured); k=1 ≈ 84%
    feasibility at the cost of aiming slightly under the line."""
    return float(os.environ.get("AUTORESEARCH_BUDGET_KSIGMA", "1.0"))


def build_problem(mode: str, sob_only: bool = False) -> "surrokit.Problem":
    """The single home for surrokit.Problem assembly over a ModeSpec.

    Every 2-axis problem carries the flash-budget Constraint (the engine
    consults it only under constrained_max; fit/predict and the other
    pickers ignore it). sob_only slices noise with Y to 1 axis and drops
    the constraint (axis 1 does not exist there).
    """
    spec = _modes.SPECS[mode]
    if sob_only:
        noise, constraint = tuple(spec.obs_noise)[:1], None
    else:
        noise = tuple(spec.obs_noise)
        constraint = surrokit.Constraint(
            axis=1, min=-math.log10(flash_budget()), k_sigma=budget_k_sigma())
    return surrokit.Problem(
        bounds_lo=tuple(spec.bounds_lo), bounds_hi=tuple(spec.bounds_hi),
        int_dims=tuple(spec.int_dims), noise=noise, constraint=constraint)


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
    sob_only = (picker == "qlnei")
    X, Y, bounds, int_dims = load_history_tensor(mode, sob_only=sob_only)
    if x_pending:
        pend_width = len(x_pending[0])
        if pend_width != bounds.shape[-1]:
            raise SystemExit(
                f"[botorch_predict] x_pending dim {pend_width} != "
                f"search-space dim {bounds.shape[-1]} for mode={mode}")
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
    sk_picker = "constrained_max" if picker == "budget_sob" else picker
    problem = build_problem(mode, sob_only=sob_only)
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    try:
        picks = surrokit.ask(problem, X.tolist(), Y.tolist(), q=q,
                             picker=sk_picker, seed=_seed(round_idx),
                             pending=x_pending, hv_frac=hv_frac)
    except surrokit.InfeasibleError as e:
        raise SystemExit(
            f"[botorch_predict] budget_sob: GP predicts NO point in the "
            f"search box with flash <= {flash_budget():.3e} MeV/POT "
            f"({e}); refusing to submit blind picks.")
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
