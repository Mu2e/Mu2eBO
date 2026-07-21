---
type: incident
title: Free-parameter GP noise erased the best eval and steered every picker
description: '`_fit_gp` fit noise by MLL with no `train_Yvar`; on foilsflash it
  landed at σ(sob)=0.0507 vs a replicate-measured 0.0051 (12×), shrinking the
  line''s best-ever eval (SOBX01, sob=3.90) to a predicted 3.787 and ranking it
  16th of 324 — so `pareto_sob` correctly optimized a surface with the optimum
  erased; resolved 2026-07-21 by ModeSpec.obs_noise → train_Yvar'
status: resolved
status_note: fixed 2026-07-21 (ModeSpec.obs_noise, foils family only; ProdTarget still MLL-fitted)
timestamp: '2026-07-21'
updated_note: created from the four-agent investigation of "why can't the optimizer reach 3.90"
---

# Free-parameter GP noise erased the best eval and steered every picker

## Summary

The foilsflash line could not reproduce its own best geometry. `foilsflashSOBX01`
(sob = 3.90) was imported from the sibling [bo-foils](/projects/bo-foils.md) line
and re-measured here; the optimizer's own best was 3.86, and a dedicated
10-eval `pareto_sob` corner campaign (foilsflash21) topped out at 3.84.

The cause was not the picker, the search box, or the geometry. `_fit_gp`
constructed `SingleTaskGP` with **no `train_Yvar`**, leaving observation noise a
free MLL hyperparameter. On the 324-row foilsflash history it converged to
**σ(sob) = 0.0507** against a replicate-measured **0.0051** — a 12× overestimate.
At that noise level a point sitting 0.05 above its neighbours is indistinguishable
from measurement scatter, so the GP shrank the observed 3.90 to a predicted
**3.787 and ranked it 16th of 324**, while *lifting* mediocre rows (one observed
3.69 predicted 3.743). Four of the ten geometries `pareto_sob` chose had a higher
posterior mean than the champion. **The picker executed correctly against a
surface on which the optimum had been erased.**

The generalization matters more than the single point: every acquisition
function on this line was fit on the same over-smoothed surface, which compressed
the entire top of the leaderboard into a 3.74–3.83 band.

## Key facts

- **Root cause:** `core/botorch_predict.py:_fit_gp` — `SingleTaskGP(train_X,
  train_Y, ...)` with noise as a free MLL hyperparameter. This was gap #1 in
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md) ("measured σ
  never fed to GP (train_Yvar)"); this incident is its live confirmation.
- **Measured noise (this is the number to reuse).** Pooled within-group sd over
  repeated geometries in the leaderboards — the same x re-evaluated under
  different campaigns:
  - foilsflash: **σ(sob) = 0.0059** raw over 9 groups (df=12); **0.0051** after
    removing the 0.01 leaderboard quantization. σ_rel(flash) = **2.31%**.
  - foils_v3: **σ(sob) = 0.0030** over 3 groups (df=8). σ_rel(calo) = 3.29%
    (df=8, dominated by one 11% group — the 8% budget in
    [bo-noise-budget](/concepts/bo-noise-budget.md) is the safer figure).
  - Recipe: group leaderboard rows on the rounded knob tuple, keep groups with
    n≥2, pool the within-group variance. Replicates exist because campaigns
    re-propose identical x; flash is *deterministic* for identical geometry +
    file count, so identical flash to 6 digits is the reliable duplicate marker.
- **Counterfactual (the proof).** Same fit, same data, only `train_Yvar` changed:

  | fit | posterior mean at SOBX01 | rank | ls(hT_up) |
  |---|---|---|---|
  | free MLL noise (σ=0.0507) | 3.787 | 16 / 324 | 0.589 |
  | pinned σ(sob)=0.006 | **3.896** | **0 / 324** | **0.078** |

  Under pinned noise the top-5 posterior order reproduces the observed
  leaderboard order exactly (3.90, 3.86, 3.84, 3.84, 3.84).
- **The conclusion is insensitive to the exact σ — only to whether it is free.**
  Sweeping the pinned value on the live 324-row history:

  | σ(sob) | mean at SOBX01 | rank | ls(hT_up) |
  |---|---|---|---|
  | free MLL (0.0507) | 3.787 | 16 | 0.589 |
  | 0.0200 | 3.868 | 1 | 0.062 |
  | 0.0152 (the 0.4% the LOO study assumed) | 3.879 | **0** | 0.060 |
  | 0.0060 (replicate-measured, deployed) | 3.896 | **0** | 0.078 |
  | 0.0050 | 3.898 | **0** | 0.081 |

  Any honest value in 0.005–0.02 fixes both the ranking and the lengthscale.
  This matters for the tension with LOO result #2 below: the choice is
  low-stakes, so if overconfidence bites, moving to 0.0152 keeps the fix.
- **Tension with the earlier LOO study, and why the replicate number wins.**
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md) LOO result #2
  already A/B'd fixed `train_Yvar` and found it gave the **best sob NLL of any
  variant** (−0.824) with 10× faster fits — but assumed σ_sob = 0.4% rel
  (≈0.0152) and read an "effective σ ≈ 0.5%" back out of z_std calibration.
  That readback conflates **model** error with **observation** noise; replicates
  isolate observation noise directly, and give 0.155% rel. Inflating observation
  noise to absorb model misspecification is exactly the pathology this incident
  documents, so the measured value is the principled one. The residual sob
  overconfidence (z_std 1.21–1.37 in that study) is a kernel problem — its fix
  is warping (LOO #3), which is PARKED for acquisition safety.
- **Deviation from the recorded recommendation, deliberately.** That review
  recommended per-row, env-flagged `train_Yvar` pending a leaderboard njobs/σ
  column. This change is global and unflagged for the foils family, because the
  failure is no longer a marginal NLL delta — it demoted the best eval to 16th.
  Per-row noise (to handle 100-vs-400-job row mixing) remains the right
  refinement and still needs that column.
- **The lengthscale collapse is the physics tell.** `extra_halfThickness_up`
  goes 0.589 → 0.078 (8×) once noise is honest: the free fit was spending real
  geometric structure in that knob as "noise". Independently, raw coverage
  statistics finger the same knob — inside the high-sob basin
  `hT_up ∈ [0.030, 0.050)` has **n=1** (scored 3.84, 3rd overall) and
  `[0.050, 0.080)` has **n=4** (max 3.90). Five evals cover the band holding
  ranks 1 and 3.
- **Why the noise inflated (inference, not measured).** foilsflash spans
  sob 1.5–3.9 with most of the box being bad geometry, fit by one stationary
  kernel. Variance the kernel cannot explain is absorbed by the noise term. The
  sibling foils line's rows cluster in the good basin, which may be why it does
  not suffer this — **untested**, and the natural follow-up.
- **The sibling comparison that reframed the question.** `foils` has 60 of 587
  rows at sob ≥ 3.85 (10.2%, best 3.91 at three distinct geometries);
  foilsflash has 2 of 325 (0.6%), and one of those was imported. 3.90 was never
  unreachable — foilsflash was aiming at a mis-specified surface. Some of the
  gap is legitimate (foilsflash is multi-objective and spends budget on the
  flash front), but ff21 was a *dedicated* sob-corner campaign and still missed.
- **The 3.90 measurement is clean.** Job counts, event budgets, denominator
  method, holeRadii patch and Musing/tarball all match or are stricter than the
  comparison rows (its quorum was 0.867 vs the later 0.8 standard). Automated
  `scan_logs` never ran (the manual-recovery path bypasses that node), so the
  identical scan was re-run by hand over its 201 still-live `/pnfs` worker logs:
  zero hits on every pattern.

## Refuted along the way

Recorded so they are not re-proposed:

- **`f_dn = 0` as a boundary optimum** — no. Zero vs small-nonzero gives
  Mann-Whitney **p = 0.72**; drop SOBX01 and the zero group's max falls *below*
  small-nonzero. No geometric discontinuity either: `rIn = f·rOut`
  (`core/bo_driver.py:561-564`) feeds `G4Tubs` with no branch or epsilon, so
  `f=0` is a solid disc as the exact limit.
- **A dedup step repelling proposals from already-evaluated points** — does not
  exist. `_pareto_sob_picks` never receives the training matrix; its
  `PARETO_SOB_MIN_SPACING=0.10` filter de-clusters a batch against itself and
  against in-flight children only.

## Secondary defects found (NOT fixed)

- **`pareto_sob` cannot find its own model's argmax.** It scores a fixed
  16,384-point scrambled Sobol grid and takes `argsort` with no refinement
  (`core/botorch_predict.py:400-451`) — no `optimize_acqf`, no L-BFGS-B. That is
  ~0.20 normalized spacing in 6-D, coarser than four of the six fitted
  lengthscales, and leaves 0.03–0.07 predicted sob on the table. It also can
  never return an exact box bound: **0 of 40** `pareto_sob` rows sit on a bound
  vs **242 of 278** acquisition-picker rows (whose L-BFGS-B clamps to the box).
- **`f` precision round-trip.** The leaderboard writes `f` at `{:.4f}`
  (`core/modes.py`) and `load_history_row` feeds that straight back as GP
  training input, so no eval exists with `f_dn ∈ (0, 0.0219)` and an `f=1e-5`
  point (a real 2.5 µm hole) trains as exactly `0.0000`.
- **`pareto_sob` silently drops every `flash_edep ≤ 0` row**
  (`core/botorch_predict.py:106`); `qlnei` (`sob_only=True`) keeps them.

## Cross-links

- Related: [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md) (this
  resolves its #1 ranked gap), [bo-noise-budget](/concepts/bo-noise-budget.md)
  (the measured-σ source; now has replicate numbers),
  [pareto-sob-picker](/concepts/pareto-sob-picker.md) (the picker that surfaced
  it), [gp-cloud-rendering](/concepts/gp-cloud-rendering.md) (the same GP
  under-predicting the high-sob corner — likely the same root cause),
  [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md)
  (this is the sharpest instance: "saturated" meant the noise model had flattened
  the signal), [botorch-tiny-output-log-training](/concepts/botorch-tiny-output-log-training.md)
- Projects: [bo-foilsflash](/projects/bo-foilsflash.md), [bo-foils](/projects/bo-foils.md)
- Source: `core/botorch_predict.py:_fit_gp` (the fix), `core/modes.py`
  (`ModeSpec.obs_noise`, `_SIGMA_SOB`, `_FOILS_FAMILY_NOISE`)
- Tests: `tests/test_botorch_predict.py` (obs_noise reaches the likelihood; a
  high observation is not shrunk; ProdTarget keeps free noise),
  `tests/test_modes.py` (per-family declaration + malformed rejection)

## Open questions / TODO

- **Expect aggressive extrapolation.** A sharper GP trusts its kernel more: with
  pinned noise the unconstrained posterior-mean argmax jumps to a far corner
  predicting sob 4.06 at normalized distance 0.81 from any data. Treat the first
  probe there as optimism, not a discovery — keep early probes inside the basin.
  This is plausibly the same failure already logged in
  [gp-cloud-rendering](/concepts/gp-cloud-rendering.md).
- Does the `foils` line's GP show the same inflated noise? If not, the
  stationary-kernel-misspecification story above is confirmed.
- ProdTarget family still fits noise freely (`obs_noise=None`) because its GP
  axis 1 is a raw negated value whose units depend on which fallback fired. Needs
  replicate evals before a σ can be declared.
- Fix the two secondary defects above (`pareto_sob` refinement; `f` precision).
- Probe `hT_up ∈ [0.03, 0.09]` near `rOut_dn ≈ 110`, `hT_dn ≈ 0.145` — the
  five-eval hole holding ranks 1 and 3. Physics gain independent of any model fix.
