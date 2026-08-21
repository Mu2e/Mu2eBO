#!/usr/bin/env python3
"""BoTorch pickers for any pure-numeric mode (bounds from modes.SPECS).

THE production picker: graph/closed_loop.py shells this CLI every round
(--emit-picks-json round-trip; keep argparse-compatible). Pickers: qnehvi,
qlnei, budget_sob, hybrid — see compute_explore_picks. `michael` is
unsupported (mixed Real+Categorical space).
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


# Per-mode bounds + integer-dim mask from the ModeSpec registry (ADR-0002).
# Order matches Point.x (= build_space); lockstep ENFORCED by
# tests/test_modes.py. Modes without a numeric box (michael) are absent.
import modes as _modes  # noqa: E402

MODE_SPECS = {
    name: {"lo": list(s.bounds_lo), "hi": list(s.bounds_hi),
           "int_dims": list(s.int_dims),
           "obs_noise": None if s.obs_noise is None else list(s.obs_noise)}
    for name, s in _modes.SPECS.items() if s.bounds_lo is not None
}


def _load_history_tensor(mode: str, sob_only: bool = False):
    """Return (X, Y, bounds, int_dims) tensors over the mode's search space.

    Y is (n, 2) [sob, -log10(calo)], both maximized; sob_only=True gives
    (n, 1) [sob] and keeps rows with invalid calo (qlnei picker).
    """
    if mode not in MODE_SPECS:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(MODE_SPECS)}. "
                         "michael's Real+Categorical space needs a mixed model.")
    spec = MODE_SPECS[mode]
    bo_mode = bo.MODES[mode]
    priors = bo_mode.load_priors() if hasattr(bo_mode, "load_priors") else []
    history = bo_mode.load_history()
    seeds = priors + history

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
    lo = torch.tensor(spec["lo"], device=DEVICE)
    hi = torch.tensor(spec["hi"], device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)

    if X_rows:
        X = torch.tensor(X_rows, device=DEVICE)
        Y = torch.tensor(Y_rows, device=DEVICE)
        if X.shape[1] != len(spec["lo"]):
            raise SystemExit(
                f"[botorch_predict] mode={mode} dim mismatch: history has "
                f"{X.shape[1]}D points but modes.SPECS[{mode!r}] declares "
                f"{len(spec['lo'])}D bounds (knobs: "
                f"{_modes.SPECS[mode].knob_names}). Leaderboard schema and "
                f"registry disagree.")
    else:
        # Cold start: empty (0, d) tensors with correct d so downstream
        # shape-checks against `bounds` pass; caller switches to Sobol.
        d = len(spec["lo"])
        m = 1 if sob_only else 2
        X = torch.empty((0, d), device=DEVICE)
        Y = torch.empty((0, m), device=DEVICE)
    return X, Y, bounds, spec["int_dims"]


def _seed(round_idx: int) -> int:
    """Per-round seed `42 ^ round_idx` (xor, NOT pow — see
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md); single home."""
    return 42 ^ int(round_idx)


def _sampler(round_idx: int):
    """The shared qMC sampler all acquisition pickers use."""
    from botorch.sampling.normal import SobolQMCNormalSampler
    return SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=_seed(round_idx))


# Acquisition-optimization budget — ONE tuning point for every picker.
# _qnparego_picks bypasses _optimize but MUST share this budget (was
# copy-pasted; friction-survey FP-4).
ACQ_NUM_RESTARTS = 16
ACQ_RAW_SAMPLES = 512
ACQ_OPTIONS = {"batch_limit": 5, "maxiter": 200}
# budget_sob front-thinning spread (normalized euclidean; wider than the
# closed-loop 0.05 on purpose).
SOB_CORNER_MIN_SPACING = 0.10


def _optimize(acq, bounds, q: int) -> torch.Tensor:
    """Shared optimize_acqf call for all acquisition pickers; returns (q, d).

    sequential=True is REQUIRED: joint mode is a ~q*d-dim problem and blew
    past a 10-min wall at q=10 (smoke-test 2026-06-04). The "N" handles
    pending picks via fantasies.
    """
    from botorch.optim import optimize_acqf
    candidates, _ = optimize_acqf(
        acq_function=acq,
        bounds=bounds,
        q=q,
        num_restarts=ACQ_NUM_RESTARTS,
        raw_samples=ACQ_RAW_SAMPLES,
        options=dict(ACQ_OPTIONS),
        sequential=True,
    )
    return candidates.detach()


def _sobol_cold_start(bounds: torch.Tensor, q: int, round_idx: int) -> torch.Tensor:
    """Draw q Sobol points over `bounds` for the very-first (no-history) batch."""
    from botorch.utils.sampling import draw_sobol_samples
    seed = _seed(round_idx)
    cands = draw_sobol_samples(bounds=bounds, n=1, q=q, seed=seed).squeeze(0)
    return cands.detach()


def _fit_gp(X, Y, bounds, obs_noise=None):
    """Fit a SingleTaskGP (input Normalize + outcome Standardize).

    obs_noise (ModeSpec.obs_noise, ABSOLUTE per-output sigma) squares into
    train_Yvar -> fixed-noise likelihood. Left free, the foilsflash fit found
    sigma(sob)=0.0507 vs replicate-measured 0.0051 (12x), demoting the best
    eval (SOBX01, 3.90) to rank 16/324 — wiki/incidents/
    gp-free-noise-erases-champion.md. Pinning restores rank 1.
    """
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    m = Y.shape[-1]
    train_Yvar = None
    if obs_noise is not None:
        # Broadcast sigma^2 across rows: noise is a property of the
        # pipeline's event budget, not the point.
        sig = torch.tensor([float(v) for v in obs_noise[:m]],
                           dtype=Y.dtype, device=Y.device)
        train_Yvar = (sig ** 2).expand(Y.shape[0], m).contiguous()

    model = SingleTaskGP(
        train_X=X,
        train_Y=Y,
        train_Yvar=train_Yvar,
        input_transform=Normalize(d=X.shape[-1], bounds=bounds),
        outcome_transform=Standardize(m=m),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    # Noise audit vs wiki/concepts/bo-noise-budget.md (σ_sob≈0.4%, σ_calo≈8%):
    # likelihood noise is standardized (× stdvs = raw); fixed-noise carries
    # (m, n) — collapse to per-output (constant within an output).
    noise = model.likelihood.noise.detach()
    noise_std = (noise.reshape(-1) if noise.numel() == m
                 else noise.reshape(m, -1)[:, 0]).sqrt()
    stdvs = model.outcome_transform.stdvs.detach().reshape(-1)
    raw = [f"{v:.3e}" for v in (noise_std * stdvs).tolist()]
    src = "FIXED (modes.obs_noise)" if train_Yvar is not None else "MLL-fitted"
    print(f"[botorch_predict] GP noise sigma per output [{src}]: raw={raw} "
          f"standardized={[f'{v:.3f}' for v in noise_std.tolist()]}", flush=True)
    return model


def _qnehvi_picks(model, X, Y, bounds, q: int, round_idx: int, x_pending=None):
    """Optimize qLogNEHVI (log-stabilized qNEHVI, Ament 2023) for q candidates.

    x_pending: optional (k, d) in-flight evals; the acqf fantasizes over them
    so replacements don't re-pick a running point.
    """
    from botorch.acquisition.multi_objective.logei import (
        qLogNoisyExpectedHypervolumeImprovement,
    )

    # Ref point = observed nadir pushed out 10% of span; subtract the offset
    # (sign-robust — "× 1.1" only works when nadir is negative).
    nadir = Y.min(dim=0).values
    span = (Y.max(dim=0).values - nadir).abs().clamp(min=1e-9)
    ref_point = (nadir - 0.1 * span).tolist()

    acq = qLogNoisyExpectedHypervolumeImprovement(
        model=model,
        ref_point=ref_point,
        X_baseline=X,
        sampler=_sampler(round_idx),
        prune_baseline=True,
        X_pending=x_pending,
    )
    return _optimize(acq, bounds, q)


def _qlnei_picks(model, X, bounds, q: int, round_idx: int, x_pending=None):
    """qLogNoisyExpectedImprovement over 1D Y (sob only); the second
    objective is unused. x_pending: as in _qnehvi_picks.
    """
    from botorch.acquisition.logei import qLogNoisyExpectedImprovement

    acq = qLogNoisyExpectedImprovement(
        model=model,
        X_baseline=X,
        sampler=_sampler(round_idx),
        prune_baseline=True,
        X_pending=x_pending,
    )
    return _optimize(acq, bounds, q)


def _qnparego_picks(model, X, Y, bounds, q: int, round_idx: int, x_pending=None):
    """qNParEGO: qLogNEI over a fresh random Chebyshev scalarization per
    candidate — fans the batch across the WHOLE front, incl. corners qNEHVI
    underprices near saturation (wiki/concepts/saturation-is-acquisition-relative.md).

    Seed discipline: weights drawn inside ONE torch.manual_seed(_seed(round_idx))
    block — DISTINCT per candidate, REPRODUCIBLE per round (XOR, never pow:
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md). Sequential-greedy via
    a growing X_pending; can't use the shared _optimize (per-candidate
    scalarization). x_pending rows are conditioned on but NOT returned.
    """
    from botorch.acquisition.logei import qLogNoisyExpectedImprovement
    from botorch.acquisition.objective import GenericMCObjective
    from botorch.utils.multi_objective.scalarization import get_chebyshev_scalarization
    from botorch.utils.sampling import sample_simplex
    from botorch.optim import optimize_acqf

    torch.manual_seed(_seed(round_idx))
    pending = [x_pending] if x_pending is not None else []  # feeds X_pending
    picks = []  # only the fresh parego candidates (x_pending excluded)
    for _ in range(q):
        w = sample_simplex(d=Y.shape[-1], n=1, dtype=Y.dtype).squeeze(0)
        obj = GenericMCObjective(get_chebyshev_scalarization(weights=w, Y=Y))
        acq = qLogNoisyExpectedImprovement(
            model=model, X_baseline=X, sampler=_sampler(round_idx),
            objective=obj, prune_baseline=True,
            X_pending=torch.cat(pending) if pending else None,
        )
        cand, _ = optimize_acqf(
            acq_function=acq, bounds=bounds, q=1,
            num_restarts=ACQ_NUM_RESTARTS, raw_samples=ACQ_RAW_SAMPLES,
            options=dict(ACQ_OPTIONS),
        )
        pending.append(cand)
        picks.append(cand)
    return torch.cat(picks).detach()


def _hybrid_picks(model, X, Y, bounds, q: int, round_idx: int, x_pending=None):
    """One batch = hv_frac qnehvi + rest qnparego; parego conditions on the
    qnehvi picks via X_pending so the halves don't collide. qnehvi first.

    AUTORESEARCH_HYBRID_HV_FRAC default 0.6: live attribution (ff09+ff11,
    2026-07-10) showed qnehvi's front hit-rate collapsing at deep saturation
    (4/6 → 0/6) while parego kept delivering (3/4 → 2/4 incl. the new
    champion) — drop toward 0.3-0.4 for end-of-line campaigns; 0.0 = pure
    qnparego. See wiki saturation-is-acquisition-relative.
    """
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    q_hv = min(q, max(0, round(hv_frac * q)))
    q_pe = q - q_hv
    if q_hv == 0:
        return _qnparego_picks(model, X, Y, bounds, q=q, round_idx=round_idx,
                               x_pending=x_pending)
    hv_cands = _qnehvi_picks(model, X, Y, bounds, q=q_hv, round_idx=round_idx,
                             x_pending=x_pending)
    pe_pending = (torch.cat([x_pending, hv_cands])
                  if x_pending is not None else hv_cands)
    if q_pe == 0:
        return hv_cands
    pe_cands = _qnparego_picks(model, X, Y, bounds, q=q_pe,
                               round_idx=round_idx, x_pending=pe_pending)
    return torch.cat([hv_cands, pe_cands])


def _emit_picks(cands, int_dims):
    """Cast (q, d) tensor -> native-typed tuples (int_dims rounded).

    Native types only: SqliteSaver's msgpack rejects numpy scalars — see
    wiki/incidents/langgraph-checkpoint-numpy-int64.md.
    """
    int_set = set(int_dims)
    out = []
    for row in cands.cpu().numpy().tolist():
        tup = tuple(int(round(v)) if i in int_set else float(v)
                    for i, v in enumerate(row))
        out.append(tup)
    return out


# The DEPLOYED stopping target's damage in MeV/POT — the deployment
# constraint line, not a tuning knob. Env-overridable for other scenarios.
DEP_FLASH_PER_POT = float(os.environ.get("AUTORESEARCH_FLASH_BUDGET", "6.85443e-7"))
# budget_sob feasibility margin in posterior sigmas: k=0 constrains the MEAN
# (~50% of picks land over budget once measured); k=1 ≈ 84% feasibility at
# the cost of aiming slightly under the line.
BUDGET_SOB_K_SIGMA = float(os.environ.get("AUTORESEARCH_BUDGET_KSIGMA", "1.0"))


def _budget_sob_picks(model, bounds, q: int, round_idx: int, x_pending=None,
                      flash_budget: float | None = None,
                      k_sigma: float | None = None):
    """Return the q highest-sob points the GP believes stay INSIDE the damage budget.

    An unconstrained max-sob exploit walks off to +60% damage — three
    pareto_sob exploit rounds did exactly that (picker retired 2026-08-19: a
    4.41 record that cannot be built). Constraint: Y[:,1] = -log10(flash/POT)
    is maximized, so "flash <= budget" is  mean_1 - k*sigma_1 >= -log10(budget)
    — k-sigma feasibility, not mean-only, because a pick whose TRUE damage
    lands over the line contributes nothing. Max-sob presses the batch up
    against the line from below.
    x_pending (k, d): in-flight evals, seeding the min-distance filter
    (NOT returned).
    """
    from scipy.stats import qmc

    budget = DEP_FLASH_PER_POT if flash_budget is None else float(flash_budget)
    k = BUDGET_SOB_K_SIGMA if k_sigma is None else float(k_sigma)
    thr = -math.log10(budget)

    N = 16384
    seed = _seed(round_idx)
    d = bounds.shape[-1]
    unit = qmc.Sobol(d=d, scramble=True, seed=seed).random(N)
    lo = bounds[0].cpu().numpy()
    hi = bounds[1].cpu().numpy()
    Xs = torch.tensor(lo + unit * (hi - lo), dtype=bounds.dtype, device=bounds.device)
    with torch.no_grad():
        post = model.posterior(Xs)
        mean = post.mean                      # (N, 2), un-standardized
        std = post.variance.clamp_min(0).sqrt()
    sob = mean[:, 0]
    feas_margin = mean[:, 1] - k * std[:, 1]

    # Relax k rather than return an empty batch (0 picks would silently
    # stall the campaign).
    used_k = k
    feasible = feas_margin >= thr
    for relaxed in (k * 0.5, 0.0):
        if int(feasible.sum()) >= q:
            break
        used_k = relaxed
        feasible = (mean[:, 1] - relaxed * std[:, 1]) >= thr
    n_feas = int(feasible.sum())
    if used_k != k:
        print(f"[botorch_predict] budget_sob: only {int((feas_margin >= thr).sum())} "
              f"candidates at k={k}sigma; relaxed to k={used_k}sigma "
              f"({n_feas} candidates)", flush=True)
    if n_feas == 0:
        raise SystemExit(
            "[botorch_predict] budget_sob: GP predicts NO point in the search box "
            f"with flash <= {budget:.3e} MeV/POT. Either the budget is wrong or the "
            "box has moved off the feasible region; refusing to submit blind picks.")

    idx_feas = torch.nonzero(feasible, as_tuple=False).squeeze(-1)
    order = idx_feas[torch.argsort(sob[idx_feas], descending=True)]
    norm = (Xs - bounds[0]) / (bounds[1] - bounds[0])
    avoid = []
    if x_pending is not None and len(x_pending):
        avoid = list((x_pending - bounds[0]) / (bounds[1] - bounds[0]))
    picks: list[int] = []
    for idx in order.tolist():
        if len(picks) >= q:
            break
        dmin = min((float((norm[idx] - a).pow(2).sum().sqrt()) for a in avoid),
                   default=float("inf"))
        if dmin >= SOB_CORNER_MIN_SPACING:
            picks.append(idx)
            avoid.append(norm[idx])
    # Top up ONLY from the feasible set — never leak over-budget picks.
    if len(picks) < q:
        for idx in order.tolist():
            if idx not in picks:
                picks.append(idx)
            if len(picks) >= q:
                break
    sel = torch.tensor(picks[:q])
    print(f"[botorch_predict] budget_sob: {n_feas}/{N} candidates feasible at "
          f"k={used_k}sigma (flash <= {budget:.3e}); picked q={len(sel)}, "
          f"predicted sob {float(sob[sel].min()):.3f}-{float(sob[sel].max()):.3f}, "
          f"predicted flash {10**-float(mean[sel, 1].max()):.3e}-"
          f"{10**-float(mean[sel, 1].min()):.3e}", flush=True)
    return Xs[sel].detach()


def compute_explore_picks(q: int = 5,
                          mode: str = "foils",
                          round_idx: int = 0,
                          picker: str = "qnehvi",
                          x_pending: list | None = None,
                          ) -> list[tuple]:
    """Explore-pick engine: picker = qnehvi | qlnei | budget_sob | hybrid
    (see the picker functions).

    x_pending: optional list of x-lists for evals IN FLIGHT — acquisition
    pickers fantasize over them (X_pending); budget_sob spreads away from
    them; cold-start Sobol ignores them.
    """
    X, Y, bounds, int_dims = _load_history_tensor(mode, sob_only=(picker == "qlnei"))
    pend = None
    if x_pending:
        pend = torch.tensor([[float(v) for v in row] for row in x_pending],
                            dtype=X.dtype)
        if pend.shape[-1] != bounds.shape[-1]:
            raise SystemExit(
                f"[botorch_predict] x_pending dim {pend.shape[-1]} != "
                f"search-space dim {bounds.shape[-1]} for mode={mode}")
    # <2 points: fit_gpytorch_mll crashes or fits a degenerate posterior —
    # fall back to Sobol.
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
        cands = _sobol_cold_start(bounds, q=q, round_idx=round_idx)
        return _emit_picks(cands, int_dims)
    model = _fit_gp(X, Y, bounds, obs_noise=MODE_SPECS[mode]["obs_noise"])
    if picker == "qlnei":
        cands = _qlnei_picks(model, X, bounds, q=q, round_idx=round_idx,
                             x_pending=pend)
    elif picker == "budget_sob":
        cands = _budget_sob_picks(model, bounds, q=q, round_idx=round_idx,
                                  x_pending=pend)
    elif picker == "hybrid":
        cands = _hybrid_picks(model, X, Y, bounds, q=q, round_idx=round_idx,
                              x_pending=pend)
    else:
        cands = _qnehvi_picks(model, X, Y, bounds, q=q, round_idx=round_idx,
                              x_pending=pend)
    return _emit_picks(cands, int_dims)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(MODE_SPECS), default="foils",
                    help="BO mode to refit (default foils)")
    ap.add_argument("--q", type=int, default=5,
                    help="Batch size (default 5)")
    ap.add_argument("--round-idx", type=int, default=0,
                    help="Round index; seeds MC sampler (default 0)")
    ap.add_argument("--picker",
                    choices=("qnehvi", "qlnei", "budget_sob", "hybrid"),
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
