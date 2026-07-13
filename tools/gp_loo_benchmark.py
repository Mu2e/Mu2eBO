#!/usr/bin/env python3
"""Offline leave-one-out benchmark for GP model variants.

Model-selection harness for the proposal GP (wiki ml-stack-review-2026-07):
scores model classes on the REAL leaderboard archive by LOO predictive
quality — no grid cost. Run it under BOTH botorch venvs to A/B versions:

  .venv-botorch/bin/python     tools/gp_loo_benchmark.py --mode foilsflash --variant base
  .venv-botorch-new/bin/python tools/gp_loo_benchmark.py --mode foilsflash --variant warp

Variants (each = production _fit_gp shape + one delta):
  base — SingleTaskGP with the RUNNING botorch's defaults + Normalize+Standardize
         (0.10 = Matern-5/2 + Gamma priors; >=0.12 = RBF + dim-scaled LogNormal)
  warp — base + Kumaraswamy input warping (Normalize -> Warp chain), fit as
         m SINGLE-OUTPUT GPs per fold. Warp is impossible on a multi-output
         SingleTaskGP in botorch 0.18: unbatched Warp crashes the batched
         scipy fit ("shape [2,1] invalid for input of size 6") and
         batch_shape=[m] Warp makes transformed X 3-D, which
         _validate_tensor_args rejects at construction. Outputs of a batched
         SingleTaskGP are independent, so per-output fits are equivalent.
  yvar — base + fixed per-row train_Yvar from the measured noise budget
         (bo-noise-budget: sob 0.4% rel; flash ~6% rel = 2.5% within-run
         (+) run-level systematic; calo 8% rel). Uniform per mode — the
         leaderboard has no per-row njobs column yet. No warp (see above).
  warpyvar — warp + yvar combined, fit per-output like warp (the only way
         botorch 0.18 allows Warp+train_Yvar together). Uses the SAME
         REL_NOISE as yvar for apples-to-apples comparability — do NOT
         recalibrate sigma from a previous run's z_std and re-score on the
         same archive (circular); fresh campaign rows are the honest test.

Per output it reports: LOO Gaussian NLL (predictive, latent var + noise var),
RMSE, z-mean (bias), z-std (calibration; 1.0 = calibrated), |z|<2 coverage,
and the same restricted to the top-decile-sob "corner" (the documented misfit
region, gp-cloud-rendering: forward-LOO log-calo bias -0.80). Lower NLL and
z-std closer to 1 win. Emits one JSON per run into --out-dir.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import torch

AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
sys.path.insert(0, str(AUTORESEARCH))
import botorch_predict as bp  # noqa: E402  (reuses _load_history_tensor)

torch.set_default_dtype(torch.float64)

# Relative measurement noise per output channel (bo-noise-budget). Output 1
# is -log10(raw) for the foils family, so its sigma is rel/ln(10) ABSOLUTE
# in log10 units, independent of y.
REL_NOISE = {
    # mode: (rel_y0_sob, rel_y1_raw)
    "foilsflash": (0.004, 0.06),   # flash: 2.5% within-run (+) ~5% run-level
    "foils": (0.004, 0.08),        # calo 8%
    "foilsf": (0.004, 0.08),
    "foilsg": (0.004, 0.08),
    "ipa": (0.004, 0.08),
}


def _make_yvar(mode: str, Y: torch.Tensor) -> torch.Tensor:
    rel0, rel1 = REL_NOISE[mode]
    var0 = (rel0 * Y[:, 0].abs()) ** 2
    var1 = torch.full_like(Y[:, 1], (rel1 / math.log(10)) ** 2)
    return torch.stack([var0, var1], dim=-1)


def _make_model(X, Y, bounds, variant: str, yvar=None):
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import (ChainedInputTransform,
                                                 Normalize, Warp)
    from botorch.models.transforms.outcome import Standardize

    d = X.shape[-1]
    norm = Normalize(d=d, bounds=bounds)
    if variant in ("warp", "warpyvar"):
        # Only reachable with single-output Y (see module docstring).
        assert Y.shape[-1] == 1, "warp variants require per-output fits"
        idx = list(range(d))
        try:
            warp = Warp(d=d, indices=idx)  # botorch >= 0.12 signature
        except TypeError:
            warp = Warp(indices=idx)       # botorch 0.10 signature
        tf = ChainedInputTransform(normalize=norm, warp=warp)  # exec in order
    else:  # base and yvar share the plain-Normalize input path
        tf = norm

    kwargs = dict(train_X=X, train_Y=Y, input_transform=tf,
                  outcome_transform=Standardize(m=Y.shape[-1]))
    if variant in ("yvar", "warpyvar"):
        try:
            return SingleTaskGP(train_Yvar=yvar, **kwargs)
        except TypeError:  # botorch 0.10: SingleTaskGP has no train_Yvar
            from botorch.models import FixedNoiseGP
            return FixedNoiseGP(train_Yvar=yvar, **kwargs)
    return SingleTaskGP(**kwargs)


def _fit(model):
    from botorch.fit import fit_gpytorch_mll
    from gpytorch.mlls import ExactMarginalLogLikelihood
    fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
    return model


def _noise_var_raw(model, m: int) -> torch.Tensor:
    """Learned observation-noise variance per output, in RAW output units."""
    noise = model.likelihood.noise.detach().reshape(-1)[:m]  # standardized
    stdvs = model.outcome_transform.stdvs.detach().reshape(-1)[:m]
    return noise * stdvs**2


def run_loo(mode: str, variant: str, seed: int = 42):
    X, Y, bounds, _ = bp._load_history_tensor(mode)
    n, m = Y.shape
    yvar_all = _make_yvar(mode, Y) if variant in ("yvar", "warpyvar") else None

    mu = torch.zeros(n, m)
    var = torch.zeros(n, m)  # predictive variance (latent + observation)
    failed = []
    t0 = time.time()
    for i in range(n):
        keep = torch.arange(n) != i
        torch.manual_seed(seed)
        try:
            if variant in ("warp", "warpyvar"):  # m single-output fits
                for j in range(m):
                    yv = (yvar_all[keep, j:j + 1]
                          if yvar_all is not None else None)
                    mj = _fit(_make_model(X[keep], Y[keep, j:j + 1], bounds,
                                          variant, yvar=yv))
                    with torch.no_grad():
                        post = mj.posterior(X[i:i + 1])
                        mu[i, j] = post.mean.reshape(-1)[0]
                        lat_j = post.variance.reshape(-1)[0]
                    var[i, j] = lat_j + (yvar_all[i, j] if yvar_all is not None
                                         else _noise_var_raw(mj, 1)[0])
            else:
                model = _fit(_make_model(
                    X[keep], Y[keep], bounds, variant,
                    yvar=yvar_all[keep] if yvar_all is not None else None))
                with torch.no_grad():
                    post = model.posterior(X[i:i + 1])
                    mu[i] = post.mean.reshape(-1)[:m]
                    lat = post.variance.reshape(-1)[:m]
                obs = (yvar_all[i] if yvar_all is not None
                       else _noise_var_raw(model, m))
                var[i] = lat + obs
        except Exception as e:  # record, don't abort the sweep
            if not failed:  # surface the first failure loudly for debugging
                print(f"[loo] FIRST FOLD FAILURE (fold {i}): {e!r}", flush=True)
            failed.append((i, repr(e)))
            mu[i] = float("nan")
            var[i] = float("nan")
        if (i + 1) % 25 == 0:
            print(f"[loo] {mode}/{variant}: {i + 1}/{n} folds "
                  f"({time.time() - t0:.0f}s)", flush=True)

    ok = ~torch.isnan(mu[:, 0])
    if not ok.any():
        raise SystemExit(f"[loo] {mode}/{variant}: ALL {n} folds failed; "
                         f"first error: {failed[0][1]}")
    z = (Y - mu) / var.sqrt()
    nll = 0.5 * (torch.log(2 * math.pi * var) + (Y - mu) ** 2 / var)
    corner = Y[:, 0] >= torch.quantile(Y[ok, 0], 0.9)  # top-decile sob

    def stats(mask, j):
        sel = mask & ok
        zz = z[sel, j]
        return {
            "n": int(sel.sum()),
            "nll": float(nll[sel, j].mean()),
            "rmse": float(((Y[sel, j] - mu[sel, j]) ** 2).mean().sqrt()),
            "z_mean": float(zz.mean()),
            "z_std": float(zz.std()),
            "cov2": float((zz.abs() < 2).double().mean()),
        }

    import botorch
    every = torch.ones(n, dtype=torch.bool)
    out = {
        "mode": mode, "variant": variant, "botorch": botorch.__version__,
        "n": n, "n_failed": len(failed), "wall_s": round(time.time() - t0),
        "outputs": [{"name": f"y{j}", "all": stats(every, j),
                     "corner_top_decile_sob": stats(corner, j)}
                    for j in range(m)],
        "failed_folds": failed[:10],
    }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="foilsflash", choices=sorted(REL_NOISE))
    ap.add_argument("--variant", default="base", choices=("base", "warp", "yvar", "warpyvar"))
    ap.add_argument("--out-dir", default=None,
                    help="Where to write the result JSON (default: cwd)")
    ns = ap.parse_args(argv)

    res = run_loo(ns.mode, ns.variant)
    import botorch
    tag = f"loo_{ns.mode}_{ns.variant}_botorch{botorch.__version__}"
    out_dir = Path(ns.out_dir) if ns.out_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{tag}.json"
    path.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print(f"[loo] wrote {path}", flush=True)


if __name__ == "__main__":
    main()
