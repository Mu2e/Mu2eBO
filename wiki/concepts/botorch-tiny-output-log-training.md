---
type: concept
title: BoTorch SingleTaskGP on tiny outputs needs -log10 training space
description: SingleTaskGP+Standardize on n<5 outputs ~1e-9 blows up extrapolation
  100×; train on `-log10(y)` and invert on predict
status: active
timestamp: '2026-06-09'
---

# BoTorch SingleTaskGP on tiny outputs needs -log10 training space

## Summary
With n<5 training points and outputs on the order of 1e-9 (e.g. peak dose
in Gy/POT), a SingleTaskGP with `Standardize` outcome-transform blows up
extrapolated posterior means by ~100×. Train on `-log10(y)` and invert on
predict. Mirrors the recipe foils calo cloud uses for the same reason.

## Key facts

- **Symptom**: with 4 prodtarget evals (dose range `[8e-10, 4e-9]`), raw-
  Gy/POT training produced a Sobol-mean prediction range of
  `[4.15e-7, 6.73e-7]` — two orders of magnitude above any observed
  point. Standardize normalized the 4 points but extrapolation in the
  10D space far from training data hit the un-renormalized posterior tail.
- **Fix**: train `Y = np.column_stack([mu_obs, -np.log10(dose_obs)])`,
  then on predict invert `dose_pred = 10 ** (-mean[:, 1])`. After fix:
  predicted dose range `[1.36e-9, 2.10e-9]` — in family with observations.
- **Why this matters specifically here**: `mu_per_POT` is O(1e-3) and
  fine on raw scale; `dose` is O(1e-9) and pathological. Branch the Y
  build per objective when magnitudes span >5 orders apart.
- **Foils precedent**: `botorch_predict.py:117-121` uses
  `[p.sob, -math.log10(p.calo)]` for the same stability reason on calo.
- **Active site**: `_load_history_tensor("prodtarget")` branch in
  `botorch_predict.py:117-121` builds Y as `[p.sob, -log10(edep)]` (Path D
  edep proxy) — same recipe. The cloud renderer
  `botorch_predict_prodtarget_cloud.py:165-170` does the same for
  `peak_dose_Gy_per_POT`.

## Cross-links
- Related: [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), [bo-prodtarget](/projects/bo-prodtarget.md)
- Source files: `botorch_predict.py:117-121`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/botorch_predict_prodtarget_cloud.py`

## Open questions / TODO
- Once n>20 in prodtarget leaderboard, retest raw-scale training —
  Standardize may stabilize with more data and let the second objective
  go back to raw `peak_dose_Gy_per_POT` for cleaner posterior variance.
