#!/usr/bin/env python3
"""BoTorch pickers for any pure-numeric BOMode (bounds from modes.SPECS).

THE production picker: graph/closed_loop.py shells into this CLI every
round (disjoint venvs — this runs under .venv-botorch, the graph under
.venv-graph; picks round-trip via --emit-picks-json). Pickers: qnehvi,
qlnei, pareto_sob, qnparego, hybrid — details in compute_explore_picks.
`michael` is unsupported (mixed Real+Categorical space needs a different
model). Acquisition budget + seeding: see ACQ_* constants and _seed().

CLI (used by _botorch_picks_subprocess; keep argparse-compatible):
  .venv-botorch/bin/python botorch_predict.py \\
      --mode foils --q 5 --round-idx 0 --emit-picks-json picks.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import torch

AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
sys.path.insert(0, str(AUTORESEARCH / "core"))  # BO/pipeline modules (2026-07-17 reorg)
import bo_driver as bo  # noqa: E402


# torch defaults: float64 + CPU. The history matrix is tiny (<200 pts), so
# CPU is faster than GPU once you account for transfer; float64 matches
# botorch's recommended SingleTaskGP precision.
torch.set_default_dtype(torch.float64)
DEVICE = torch.device("cpu")


# Per-mode bounds + integer-dim mask come from the ModeSpec registry
# (root modes.py, ADR-0002) — stdlib-only, so .venv-botorch (no skopt) can
# import it. Order matches the Point.x layout (= build_space order); the
# lockstep is ENFORCED by tests/test_modes.py (driver build_space bounds ==
# spec bounds per mode), retiring the "MUST mirror build_space" comments.
# Modes without a numeric box (michael's Categorical COL5 space) are absent.
import modes as _modes  # noqa: E402

MODE_SPECS = {
    name: {"lo": list(s.bounds_lo), "hi": list(s.bounds_hi),
           "int_dims": list(s.int_dims)}
    for name, s in _modes.SPECS.items() if s.bounds_lo is not None
}


def _load_history_tensor(mode: str, sob_only: bool = False):
    """Return (X, Y, bounds, int_dims) tensors over the mode's search space.

    X shape (n, d): per-mode x vector as floats (Integer dims coerced).
    Y shape (n, 2): [sob, -log10(calo)] — botorch maximizes both.
    If sob_only=True: Y shape (n, 1) = [sob]; rows with missing/invalid
      calo are kept (calo not consulted). For the qlnei single-objective
      picker.
    bounds shape (2, d): from MODE_SPECS.
    int_dims: list of column indices to round on emit.
    """
    if mode not in MODE_SPECS:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(MODE_SPECS)}. "
                         "michael's Real+Categorical space needs a mixed model.")
    spec = MODE_SPECS[mode]
    bo_mode = bo.MODES[mode]
    # Seeds = priors + history.
    # For foils v2, priors are the projected v1 n=6/6 subset (~51 rows);
    # without them an early v2 run with zero leaderboard rows has nothing
    # to fit on.
    priors = bo_mode.load_priors() if hasattr(bo_mode, "load_priors") else []
    history = bo_mode.load_history()
    seeds = priors + history

    X_rows = []
    Y_rows = []
    for p in seeds:
        if mode in ("prodtarget", "prodtarget6d"):
            # Pareto objectives: maximize mu_per_POT, minimize the right
            # thermal proxy. Prefer peak specific dose [Gy/POT] (peak
            # plate, scales as 1/rOut^2 — the dominant thermal coupling);
            # fall back to stack-total edep_per_POT_MeV for legacy rows
            # written before peak_dose wiring landed. Negate so botorch
            # maximizes both axes.
            ex = p.extras or {}
            peak = ex.get("peak_dose_Gy_per_POT")
            edep = ex.get("edep_per_POT_MeV")
            if peak is not None and peak > 0:
                y2 = -float(peak)
            elif edep is not None and edep > 0:
                y2 = -float(edep)
            else:
                continue  # row predates Path D wiring or harvest broken
            X_rows.append([float(v) for v in p.x])
            Y_rows.append([p.sob, y2])
        elif sob_only:
            # 1D objective: only need sob. Drop rows with missing sob.
            if p.sob is None or not math.isfinite(p.sob):
                continue
            X_rows.append([float(v) for v in p.x])
            Y_rows.append([p.sob])
        else:
            if p.calo <= 0:
                continue  # log10 undefined; rare but possible on broken harvest
            X_rows.append([float(v) for v in p.x])
            Y_rows.append([p.sob, -math.log10(p.calo)])
    lo = torch.tensor(spec["lo"], device=DEVICE)
    hi = torch.tensor(spec["hi"], device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)

    if X_rows:
        X = torch.tensor(X_rows, device=DEVICE)
        Y = torch.tensor(Y_rows, device=DEVICE)
        if X.shape[1] != len(spec["lo"]):
            raise SystemExit(f"[botorch_predict] mode={mode} dim mismatch: "
                             f"history has {X.shape[1]}D points but MODE_SPECS "
                             f"declares {len(spec['lo'])}D bounds. Check "
                             "leaderboard schema vs MODE_SPECS in this file.")
    else:
        # Cold start: return empty (n=0, d) tensors. The caller switches to a
        # Sobol cold-start path when X is empty so the very first launch of a
        # brand-new mode doesn't need any seeding (no propose+evaluate, no
        # projected priors). MUST emit empty with correct d so downstream
        # shape-checks against `bounds` still pass.
        d = len(spec["lo"])
        m = 1 if sob_only else 2
        X = torch.empty((0, d), device=DEVICE)
        Y = torch.empty((0, m), device=DEVICE)
    return X, Y, bounds, spec["int_dims"]


def _seed(round_idx: int) -> int:
    """Per-round RNG seed: `42 ^ round_idx` (xor, NOT pow — see
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md). Single home for the
    formula; every picker/cold-start path calls this."""
    return 42 ^ int(round_idx)


def _sampler(round_idx: int):
    """The shared qMC sampler all acquisition pickers use."""
    from botorch.sampling.normal import SobolQMCNormalSampler
    return SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=_seed(round_idx))


# Acquisition-optimization budget — ONE tuning point for every picker.
# _qnparego_picks structurally bypasses _optimize (per-candidate scalarization
# + growing X_pending, see its docstring) but MUST share this budget; these
# were previously copy-pasted (friction-survey FP-4, 2026-07-11).
ACQ_NUM_RESTARTS = 16
ACQ_RAW_SAMPLES = 512
ACQ_OPTIONS = {"batch_limit": 5, "maxiter": 200}
# pareto_sob front-thinning spread (normalized-space euclidean); see the
# comment at its use site for why it differs from the closed-loop 0.05.
PARETO_SOB_MIN_SPACING = 0.10


def _optimize(acq, bounds, q: int) -> torch.Tensor:
    """Shared optimize_acqf call for all acquisition pickers; returns (q, d).

    sequential greedy: optimize the q candidates one-at-a-time (each a
    cheap d-dim problem) instead of jointly (one q*d-dim problem). For
    qNEHVI/qLogNEHVI this is the recommended batch mode AND the only
    tractable one at large q — joint (sequential=False) is ~q*d dims and
    blew past a 10-min wall at q=10 (botorch_predict q=10 smoke-test,
    2026-06-04). The "N" handles pending picks correctly via fantasies.
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
    """Draw q Sobol points over `bounds` for the very-first batch.

    Used when load_priors()+load_history() is empty: there's nothing for the
    GP to fit on. Sobol is the standard cold-start for BO and matches what
    skopt does internally via N_INITIAL_POINTS. Seed via the shared _seed().
    (int rounding happens in the caller's _emit_picks.)
    """
    from botorch.utils.sampling import draw_sobol_samples
    seed = _seed(round_idx)
    # draw_sobol_samples returns (n=1, q, d); squeeze the leading dim.
    cands = draw_sobol_samples(bounds=bounds, n=1, q=q, seed=seed).squeeze(0)
    return cands.detach()


def _fit_gp(X, Y, bounds):
    """Fit a 2-output SingleTaskGP with input normalization + output stdize."""
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    model = SingleTaskGP(
        train_X=X,
        train_Y=Y,
        input_transform=Normalize(d=X.shape[-1], bounds=bounds),
        outcome_transform=Standardize(m=Y.shape[-1]),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    # Noise audit: likelihood.noise is in Standardize'd units; × stdvs
    # recovers raw-output σ, comparable to the measured budget in
    # wiki/concepts/bo-noise-budget.md (σ_sob≈0.4% rel, σ_calo≈8%).
    noise_std = model.likelihood.noise.detach().sqrt().reshape(-1)
    stdvs = model.outcome_transform.stdvs.detach().reshape(-1)
    raw = [f"{v:.3e}" for v in (noise_std * stdvs).tolist()]
    print(f"[botorch_predict] fitted GP noise sigma per output: raw={raw} "
          f"standardized={[f'{v:.3f}' for v in noise_std.tolist()]}", flush=True)
    return model


def _qnehvi_picks(model, X, Y, bounds, q: int, round_idx: int, x_pending=None):
    """Optimize qLogNEHVI for q candidates; return shape (q, d) tensor.

    qLogNEHVI = log-stabilized qNEHVI (Ament et al. 2023): same Pareto-HV
    objective, fixes the vanishing acquisition-value / flat-gradient failure of
    the plain MC version so optimize_acqf finds better candidates near
    saturation. Drop-in: identical constructor args.

    x_pending: optional (k, d) tensor of in-flight evals (rolling closed-loop);
    the acqf fantasizes over them so replacements don't re-pick a running point.
    """
    from botorch.acquisition.multi_objective.logei import (
        qLogNoisyExpectedHypervolumeImprovement,
    )

    # Per-round ref-point: nadir of the observed front, pushed out 10% of
    # the span. For maximization, "dominated" = smaller — so subtract the
    # offset (sign-robust; "× 1.1" only works when nadir is negative).
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
    """Optimize qLogNoisyExpectedImprovement for q candidates over 1D Y (sob).

    Single-objective picker — use when you want to push sob ceiling and
    don't care about calo trade-off. Drops the entire run1b_mubeam stage
    (calo measurement is unused) and converges much faster on the plateau.
    x_pending: as in _qnehvi_picks.
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
    """Optimize qNParEGO for q candidates; return shape (q, d) tensor.

    qNParEGO (Daulton et al. 2020) = qLogNoisyExpectedImprovement over a
    *random augmented-Chebyshev scalarization* drawn fresh per candidate. Each
    of the q candidates gets its own simplex weight vector, so the batch fans
    out along the WHOLE Pareto front — including the corners qNEHVI's
    hypervolume economics underprice near saturation (see
    wiki/concepts/saturation-is-acquisition-relative.md). No HV box
    decomposition either, so it degrades gracefully on big fronts where qNEHVI
    times out.

    Weights are drawn inside ONE torch.manual_seed(_seed(round_idx)) block: the
    q scalarizations are DISTINCT per candidate (each sample_simplex call
    advances the RNG) yet REPRODUCIBLE per round (seed is XOR, never pow — see
    wiki/incidents/botorch-predict-seed-pow-vs-xor.md). Candidates are chosen
    sequentially-greedy, each conditioned on the ones already picked via
    X_pending so the batch stays diverse. NOT via the shared _optimize: its
    single-acq sequential=True path can't take a per-candidate scalarization +
    a growing X_pending.

    x_pending: optional (k, d) tensor of already-committed picks (e.g. the
    qnehvi half of a hybrid batch) pre-loaded into X_pending before the loop;
    those k rows are NOT returned (only the q fresh parego candidates are).
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
    """One batch = ~60% qnehvi (HV efficiency) + ~40% qnparego (tail coverage).

    q_hv = max(1, round(0.6*q)) qnehvi picks first (mines the useful region);
    the remaining q_pe = q - q_hv qnparego picks then patrol the front's tails,
    conditioned on the qnehvi picks via X_pending so the two halves don't
    collide. One GP fit / one subprocess call (the caller already fit `model`).
    Recommended default for new multi-objective lines. If q_pe == 0 (small q)
    this is pure qnehvi. Batch order: qnehvi picks first, parego picks after.

    The hv fraction is an env seam (AUTORESEARCH_HYBRID_HV_FRAC, default
    0.6): two rounds of live attribution (ff09+ff11, 2026-07-10) showed
    qnehvi's front hit-rate collapsing at deep saturation (4/6 → 0/6) while
    parego kept delivering (3/4 → 2/4 incl. the new champion) — drop toward
    0.3-0.4 for end-of-line campaigns; 0.0 is valid (pure qnparego).
    See wiki saturation-is-acquisition-relative.
    """
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    q_hv = min(q, max(0, round(hv_frac * q)))
    q_pe = q - q_hv
    if q_hv == 0:
        return _qnparego_picks(model, X, Y, bounds, q=q, round_idx=round_idx,
                               x_pending=x_pending)
    hv_cands = _qnehvi_picks(model, X, Y, bounds, q=q_hv, round_idx=round_idx,
                             x_pending=x_pending)
    # parego half conditions on BOTH the external pending set and the fresh
    # qnehvi half, so no part of the batch collides with anything in flight.
    pe_pending = (torch.cat([x_pending, hv_cands])
                  if x_pending is not None else hv_cands)
    if q_pe == 0:
        return hv_cands
    pe_cands = _qnparego_picks(model, X, Y, bounds, q=q_pe,
                               round_idx=round_idx, x_pending=pe_pending)
    return torch.cat([hv_cands, pe_cands])


def _emit_picks(cands, int_dims):
    """Cast (q, d) tensor -> list of native-typed tuples.

    int_dims get round() + int(); other dims get float(). Native types only:
    LangGraph's SqliteSaver checkpoint serializer (msgpack) rejects numpy
    scalars — see wiki/incidents/langgraph-checkpoint-numpy-int64.md.
    """
    int_set = set(int_dims)
    out = []
    for row in cands.cpu().numpy().tolist():
        tup = tuple(int(round(v)) if i in int_set else float(v)
                    for i, v in enumerate(row))
        out.append(tup)
    return out


def _pareto_sob_picks(model, bounds, q: int, round_idx: int, x_pending=None):
    """Return the q highest-sob points on the GP-predicted Pareto frontier.

    x_pending (k, d): in-flight evals; they seed the min-distance filter so
    exploit picks don't re-measure a corner already being measured (they are
    NOT returned).

    Mirrors the cloud renderer's pushforward (gp_predict_foils_v2v3_cloud.py):
    Sobol-sample the input box, evaluate the GP posterior MEAN for both
    objectives (sob = output 0, -log10(calo) = output 1; both maximized), keep
    the non-dominated set, and return the q frontier points with the highest
    predicted sob. This submits the GP's own best-sob predictions as real evals
    — a by-hand exploit of the sob corner. Tests whether the GP's high-sob
    envelope (~4.06) holds at specific geometries (expect regression to ~3.9 on
    the saturated foilsf front; see wiki/concepts/gp-cloud-rendering.md).
    """
    from scipy.stats import qmc

    N = 16384
    seed = _seed(round_idx)
    # Bulk Sobol via scipy (matches the cloud renderer); botorch's
    # draw_sobol_samples builds SobolEngine(q*d) and caps at 21201 dims, so it
    # can't bulk-sample N points. Draw in [0,1]^d then scale to bounds.
    d = bounds.shape[-1]
    unit = qmc.Sobol(d=d, scramble=True, seed=seed).random(N)  # (N, d)
    lo = bounds[0].cpu().numpy()
    hi = bounds[1].cpu().numpy()
    Xs = torch.tensor(lo + unit * (hi - lo), dtype=bounds.dtype, device=bounds.device)
    with torch.no_grad():
        mean = model.posterior(Xs).mean  # (N, m), already un-standardized
    sob = mean[:, 0]
    # "highest sob" = top-q by predicted sob directly. NOTE: do NOT pre-filter to
    # the Pareto frontier — the (sob, -log10 calo) frontier deliberately includes
    # low-sob/low-calo corners (big-hole rings), so "top-q-sob among frontier
    # points" leaks those in. The single max-sob Sobol point IS on the frontier
    # anyway (it's non-dominated on the sob axis), so direct top-q-sob is both
    # correct and simpler. Spread: take top candidates and thin to q by a
    # min-distance filter so the batch isn't all one near-duplicate cluster.
    order = torch.argsort(sob, descending=True)
    norm = (Xs - bounds[0]) / (bounds[1] - bounds[0])  # (N,d) in [0,1]
    # The min-distance "avoid" set starts with the normalized in-flight
    # pending points (rolling mode), so the batch spreads away from them
    # exactly as it spreads away from its own accepted picks. With no
    # pending this reduces to the original behavior (first pick = top sob).
    avoid = []
    if x_pending is not None and len(x_pending):
        avoid = list((x_pending - bounds[0]) / (bounds[1] - bounds[0]))
    picks: list[int] = []
    for idx in order.tolist():
        if len(picks) >= q:
            break
        dmin = min((float((norm[idx] - a).pow(2).sum().sqrt()) for a in avoid),
                   default=float("inf"))
        # PARETO_SOB_MIN_SPACING is deliberately looser than the closed-loop
        # duplicate-guard (0.05, retired with cl_min): this thins the
        # GP-MEAN front so q exploit picks don't re-measure one corner point,
        # a different job than de-duplicating acquisition picks.
        if dmin >= PARETO_SOB_MIN_SPACING:
            picks.append(idx)
            avoid.append(norm[idx])
    # if min-distance thinning didn't yield q, top up with the next-highest sob
    if len(picks) < q:
        for idx in order.tolist():
            if idx not in picks:
                picks.append(idx)
            if len(picks) >= q:
                break
    return Xs[torch.tensor(picks[:q])].detach()


def compute_explore_picks(q: int = 5,
                          mode: str = "foils",
                          round_idx: int = 0,
                          picker: str = "qnehvi",
                          x_pending: list | None = None,
                          ) -> list[tuple]:
    """Explore-pick engine.

    picker = "qnehvi" (default, multi-objective Pareto-HV), "qlnei"
    (single-objective qLogNoisyExpectedImprovement on sob only — drops calo
    entirely; closed_loop stamps AUTORESEARCH_NO_RUN1B=1 so the DS-off stage
    is skipped and the grid time is actually saved), "pareto_sob"
    (GP-mean sob corner), "qnparego"
    (qLogNEI over random Chebyshev scalarizations — spreads across the whole
    front) or "hybrid" (~60% qnehvi + ~40% qnparego; recommended for new
    multi-objective lines). qnparego/hybrid use the same 2-objective path as
    qnehvi.

    x_pending: optional list of x-lists for evals currently IN FLIGHT (rolling
    closed-loop). Acquisition pickers fantasize over them (X_pending); the
    pareto_sob exploit spreads away from them. Cold-start Sobol ignores it.
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
    # Cold-start guard: SingleTaskGP needs >= 2 points to fit; <2 makes
    # fit_gpytorch_mll either crash or fit to a degenerate posterior that
    # collapses the acquisition. Fall back to Sobol so a brand-new mode
    # (empty leaderboard, no load_priors override) launches cleanly.
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
        cands = _sobol_cold_start(bounds, q=q, round_idx=round_idx)
        return _emit_picks(cands, int_dims)
    model = _fit_gp(X, Y, bounds)
    if picker == "qlnei":
        cands = _qlnei_picks(model, X, bounds, q=q, round_idx=round_idx,
                             x_pending=pend)
    elif picker == "pareto_sob":
        cands = _pareto_sob_picks(model, bounds, q=q, round_idx=round_idx,
                                  x_pending=pend)
    elif picker == "qnparego":
        cands = _qnparego_picks(model, X, Y, bounds, q=q, round_idx=round_idx,
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
                    choices=("qnehvi", "qlnei", "pareto_sob", "qnparego", "hybrid"),
                    default="qnehvi",
                    help="qnehvi = multi-obj Pareto-HV (default); "
                         "qlnei = single-obj qLogNoisyEI on sob only; "
                         "pareto_sob = highest-sob points on the GP Pareto frontier; "
                         "qnparego = qLogNEI over random Chebyshev scalarizations "
                         "(spreads across the whole front); "
                         "hybrid = ~60%% qnehvi + ~40%% qnparego "
                         "(recommended for new multi-objective lines)")
    ap.add_argument("--emit-picks-json", type=str, default=None,
                    help="If set, write picks as JSON to this path")
    ap.add_argument("--pending-json", type=str, default=None,
                    help="JSON file: list of x-lists for in-flight evals "
                         "(rolling closed-loop); pickers fantasize over them "
                         "via X_pending")
    ns = ap.parse_args(argv)

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
