---
type: concept
title: ML/statistics stack review (2026-07)
description: 'ML/stats audit: acquisition layer SOTA (keep); ranked gaps = measured
  σ never fed to GP (train_Yvar), botorch 0.10 pre-Hvarfner defaults, ~~skopt EI~~
  (RESOLVED 2026-07-18: kernel retired, all asks via botorch_ask), high-sob-corner
  misfit → Warp; Ax/Optuna/neural surrogates explicitly rejected'
status: active
timestamp: '2026-07-18'
updated_note: 'adoption rule: 6D null does not transfer; new high-D lines default
  to 0.18'
---

# ML/statistics stack review (2026-07)

## Summary
Point-in-time audit of the ML/stats tooling: acquisition layer (qLogNEHVI /
qLogNEI / qNParEGO / hybrid, sequential-greedy, X_pending) is state of the art
— no tool swap warranted. The real gaps are statistical plumbing, ranked below.
Versions at review time: **botorch 0.10.0 / gpytorch 1.11 / torch 2.8.0**
(.venv-botorch); **skopt 0.10.2 / sklearn 1.8.0 / numpy 2.4.6** (.venv-graph).

## Key facts
- **Ranked gaps (payoff-ordered):**
  1. **Measured noise never reaches the GP** — `_fit_gp` (botorch_predict.py:215)
     infers one homoscedastic noise per output; we KNOW σ_sob≈0.4%,
     σ_flash≈2–4%@100j (+5–10% run-level systematic), σ_calo≈8%, and rows mix
     100-job and 400-job stats. Fix = per-row `train_Yvar` (needs njobs/σ column
     in leaderboard schema — friction-survey candidate 3 synergy). Cheap first
     step: log fitted `likelihood.noise` after fit (was already a bo-noise-budget
     TODO) to see if inferred σ matches the measured budget.
  2. **botorch 0.10.0 is pre-0.12 defaults** — 0.12+ SingleTaskGP uses RBF +
     dimension-scaled LogNormal lengthscale priors (Hvarfner et al. 2024),
     measurably better at 6–12D (foilsg 12D, prodtarget ~11D); also merges
     train_Yvar into SingleTaskGP and unlocks SAASBO. Upgrade between campaigns
     only (reproducibility churn).
  3. ~~skopt~~ **RESOLVED 2026-07-18 — skopt kernel RETIRED**: every BO ask
     (CLI propose, propose_one, preflight-retry) now routes through
     `bo_driver.botorch_ask()` into the botorch picker; retries bump the
     seed, pending rides as X_pending. Original finding (for the record):
     **skopt (EI, constant-liar) is the weakest optimizer left in production**:
     `build_optimizer` (bo_driver.py:245), `seed_optimizer`
     fake-y suppression (:264), and — load-bearing — the closed-loop
     **preflight-fail retry path re-draws from skopt**, not from the botorch
     picker (graph/nodes.py:114-119 fail_managed → node_propose → skopt ask).
     skopt = caretaker-revived abandonware (dead 2021–2024). Route q=1 proposes
     through botorch_predict + apply `is_buildable` rejection to emitted picks;
     retire skopt.
  4. **Known GP misfit in the high-sob corner is unaddressed** — forward-LOO
     log-calo bias −0.80 (2.3× underprediction, [gp-cloud-rendering](/concepts/gp-cloud-rendering.md)) is a
     stationarity failure; botorch's `Warp` input transform (Kumaraswamy) is the
     cheap targeted fix; TuRBO-style trust region only if warping fails.
  5. **qNEHVI ref point recomputed per round from the noisy observed nadir**
     (botorch_predict.py:252-254) — jitters the HV objective round-to-round and
     a single broken low-sob row drags it; pin per campaign (minor).
  6. Integer dims via round-after-optimize is standard-acceptable; probabilistic
     reparameterization only worth it if an integer-heavy line appears.
- **botorch 0.18 upgrade gotchas (hit live 2026-07-13, /exp/mu2e/data/users/oksuzian/autoresearch_tools/gp_loo_benchmark.py):**
  `Warp` is IMPOSSIBLE on a multi-output SingleTaskGP in 0.18.1, both ways:
  (a) unbatched Warp crashes the new batched scipy fit path
  (`_fit_gpytorch_mll_scipy_independent`: `RuntimeError: shape '[2, 1]' is
  invalid for input of size 6` — every param must carry the m-output batch);
  (b) `Warp(batch_shape=[m])` makes transformed X 3-D, which
  `_validate_tensor_args` rejects AT CONSTRUCTION ("X dim 3 vs Y dim 2") —
  with or without train_Yvar. Only fix: fit m single-output GPs (outputs of a
  batched SingleTaskGP are independent anyway, so this is equivalent).
  New venv: `.venv-botorch-new` (botorch 0.18.1/gpytorch 1.15.2/torch
  2.13.0+cpu, py3.11; CPU torch wheel = 183 MB vs ~2.5 GB CUDA) on /data,
  symlinked at project root like the other venvs.
- **LOO result #1 (2026-07-13, foilsflash n=274): version upgrade alone is a
  WASH at 6D** — 0.10-base (Matern-5/2+Gamma) beats 0.18-base (RBF+dim-scaled
  LogNormal, Hvarfner) on sob NLL overall (−0.69 vs −0.43) AND corner
  (−2.14 vs −1.35, RMSE 0.046 vs 0.062); flash axis ~identical (0.10 z_std
  0.998 = perfectly calibrated). 0.18 wins robustness (0 vs 3
  ModelFittingError folds) + ~15% faster. Consistent with Hvarfner gains
  growing with d: at 6D/n=274 data swamps priors — upgrade case is
  robustness+train_Yvar API, NOT accuracy; 12D foilsg/11D prodtarget are where
  new defaults should actually help. Both bases: sob axis OVERCONFIDENT
  (z_std 1.24–1.37), flash axis well-calibrated. warp/yvar verdict pending.
- **LOO result #2 (yvar = fixed measured train_Yvar, 0.18, n=274/0 failed):**
  best sob NLL of any variant (−0.824 vs −0.69/−0.43) despite WORSE sob RMSE
  (0.205 vs ~0.17) — honest variances beat sharper-but-overconfident point
  predictions. **10× faster fits** (398 s vs ~4,000 s sweep; no noise
  hyperparameter). Calibration readback (z_std under assumed σ): sob z_std
  1.21 → effective σ_sob ≈ 0.5% (assumed 0.4%, slightly optimistic); flash
  z_std 0.75 overall / 0.55 corner → **effective archive flash noise ≈ 4.5%,
  NOT the assumed 6%** → run-level systematic ≈ √(4.5²−2.5²) ≈ 3.7% — an
  independent confirmation of NC02's run-level estimate at its LOW end
  (caveat: same-data calibration readback, mildly circular as an NLL claim).
- **LOO result #3 (warp, 0.18, per-output fits, n=274/0 failed): the corner
  non-stationarity is REAL and warping fixes it** — best RMSE on BOTH axes
  (sob 0.153 vs 0.168–0.172; flash 0.0175 vs 0.0215–0.0230, −19%), corner
  flash bias ELIMINATED (z_mean −0.09 vs −0.18/−0.29/−0.30), best corner sob
  NLL (−2.47 vs −2.14/−2.08/−1.35). BUT sob z_std 1.78 = worst overconfidence
  (inferred noise collapses when the mean fits better) → NOT safe alone for
  qNEHVI (over-exploitation risk). Cost 2.6× base (37 s/fold; fine for a
  once-per-round picker fit).
- **LOO result #4 (warpyvar combo): the hoped-for synthesis FAILED** — sob
  NLL −0.327 = worst of all five, sob z_std 1.94 = worst overconfidence
  (fixed 0.4% noise forces the warped GP's collapsed latent variance to
  carry all residual scatter — warp's 12 extra hyperparameters shrink
  apparent uncertainty faster than actual error, textbook warping overfit at
  n=274); flash mean also went lazy (RMSE 0.0214 vs warp's 0.0175 — the
  too-wide fixed 6% noise stops MLL from pushing the fit). Fixed noise sped
  warp fits 6× (1717 s vs 10295 s sweep).
- **FINAL VERDICT (five-way table, JSONs in session scratchpad loo_results/;
  archived numbers above): NO variant dominates — and the incumbent
  (0.10-base = production _fit_gp) is solidly mid-table** (2nd-best sob NLL,
  perfectly calibrated flash z_std 1.00, best corner flash NLL). Per-axis
  winners: sob NLL = yvar; flash NLL + both means + corner-bias fix = warp
  (but acquisition-UNSAFE: z_std 1.78–1.94 overconfidence would make qNEHVI
  over-exploit). Production recommendation: (1) KEEP the 0.10 stack for the
  next campaign — no evidence-backed accuracy win from upgrading; (2) the
  one change worth wiring = per-row train_Yvar (env-flagged, A/B on the next
  line; needs the leaderboard njobs/σ column) — best sob NLL, honest
  uncertainties, 10× faster fits, and per-row noise handles 100-vs-400-job
  row mixing; (3) PARK warp — the corner non-stationarity is real (its
  diagnostic value stands) but calibration collapse disqualifies it for
  acquisition; corner exploitation is already covered by [pareto-sob-picker](/concepts/pareto-sob-picker.md)
  rounds. Honest-validation caveat: all variants scored on the same archive;
  the next campaign's fresh rows are the true held-out test (harness
  supports this trivially).
- **Explicitly NOT recommended:** Ax (its service layer duplicates our
  closed-loop orchestration), Optuna (TPE weaker than GP-BO at n<300), neural
  surrogates (<O(100D), see [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md)), replacing the sklearn
  viz GP (viz-only; but rendering the cloud from the botorch posterior would
  kill the dual-model inconsistency).
- **Confirmed right:** log-family acquisitions (Ament 2023) fix exactly our
  saturation flat-gradient regime; NEI-family (never trusts best-observed under
  noise) is correct for our σ; Normalize+Standardize+float64 CPU; −log10(calo)
  training; Sobol cold start; xor round seeding; acq budget (128 qMC / 16
  restarts / 512 raw) already past diminishing returns ([bo-noise-budget](/concepts/bo-noise-budget.md)).

- **HELD-OUT result (2026-07-14, 10 fresh foilsflash16 rows vs the 274-row
  archive, `--holdout-prefix`) — AUDITED with paired tests (independent
  agent, same day; harness re-run reproduced every number to the digit).
  Only ONE finding is statistically resolved:** uniform-yvar's sob-mean
  COLLAPSE (RMSE 0.330 vs base 0.072 = 4.5×, bootstrap 95% CI [2.0, 9.1],
  paired Wilcoxon p=0.037; driven by gross low-sob mispredictions) — the
  LOO favorite fails the honest test; do NOT wire uniform yvar. The two
  apparent "reversals" are WITHIN NOISE at n=10: 0.18-base's sob edge
  (RMSE 0.072 vs 0.109) has p=0.85, CI [0.70, 2.85]; the incumbent's
  "over-prediction" (z_mean −0.61) is a mean residual of only −0.015,
  p=0.69; warp's flash edge (0.0139 vs 0.0185) has p=0.16, CI [0.49, 1.01],
  and its sob RMSE is actually worse than 0.18-base. "Warp's overconfidence
  didn't materialize" is under-powered at n=10, not demonstrated. The
  methodological lesson STANDS: LOO on a self-collected archive rewards
  interpolation and can disagree with held-out generalization — but which
  variant generalizes best is UNRESOLVED. Test points are BO-proposed, not
  iid (span sob 2.72–3.83).
- **LIVE PICKER A/B + POOLED 20-ROW HOLDOUT (ff16=0.10 vs ff17=0.18, both
  rolling q=5/10 evals/hybrid, 2026-07-15).** Campaign level: identical
  throughput (8h16m vs 8h01m), best sob 3.83 (0.10) vs 3.77 (0.18) — no
  proposal-quality winner on a saturated line; behavioral difference: the
  0.18 picker EXPLORED first (2 low-sob corner evals in w0: 1.65/1.69, one
  high-flash 1.86e-6) then exploited (3.77/3.60 after refit), while 0.10
  stayed in the known-good region. Model level, paired stats on 20 pooled
  held-out rows (fit on 274): (a) **0.10-vs-0.18 base: NO difference**
  (sob p=0.43, flash p=0.73, CIs span 1) — the n=10 "0.18 decisively
  better" signal evaporated, audit vindicated twice; (b) **uniform-yvar sob
  collapse REPLICATED, now decisive** (RMSE ratio 0.34, CI [0.22,0.50],
  p=0.002); (c) **warp's flash-mean edge is the only positive trend**
  (RMSE 0.052 vs 0.087 ≈ 1.7×, bootstrap CI excludes 1 [1.06–1.09 low
  edge] but Wilcoxon p≈0.13-0.14 — a few large-error points carry it;
  suggestive, NOT adoption-grade); (d) ALL variants overconfident on flash
  for the exploratory ff17 points (z_std 1.29–1.53) — new-region
  extrapolation + run-level systematic. Per-point predictions now embedded
  in holdout JSONs (`per_point` field) so future paired tests need no
  re-run; `--holdout-prefix` accepts comma-separated prefixes.
- **WHY 0.10 is the default: historical accident, not merit.** The venv was
  built early in the project and never revisited; botorch 0.10 released
  **2024-03**, so it was already ~a year stale when installed. **ADOPTION
  RULE (2026-07-15): the 6D null does NOT transfer — do not read it as
  "0.18 never helps."** The A/B tested the LEAST favorable venue (foilsflash
  6D, n=274, saturated → data swamps the priors); the Hvarfner defaults are
  designed to pay at higher d, and **foilsg (12D) / prodtarget (~11D) were
  never tested**. So: keep 0.10 for the running 6D line (protects
  reproducibility, no measured gain), but **default any NEW line — especially
  d≥10 — to 0.18** via `AUTORESEARCH_BOTORCH_VENV`, where there is no
  reproducibility to protect. Operational tiebreak favors 0.18 regardless:
  3/274 `ModelFittingError` fits on 0.10 vs 0 on 0.18 (a picker-time fit
  failure stalls/degrades a round, which the accuracy test doesn't capture).
- **BOTTOM-LINE ANSWER to "is 0.18 better?": no evidence better, no
  evidence worse** — the upgrade case stays operational (0 fit failures,
  faster, train_Yvar API), not performance. Staying on 0.10 remains
  legitimate; the A/B seam + holdout tooling make continued tracking
  ~free (score each campaign's rows, revisit at ~30+).
- **REVISED recommendation (post-audit):** (1) keep accumulating held-out
  rows every campaign (one command: `--holdout-prefix <prefix>`) — the only
  resolved verdict so far is negative (uniform yvar out); (2) 0.18+warp are
  suggestive but unproven — do NOT switch pickers until ~30 held-out rows
  or a live picker A/B resolves it; (3) per-row train_Yvar still requires
  the leaderboard njobs column and fresh evidence before wiring.

## Cross-links
- Related: [bo-noise-budget](/concepts/bo-noise-budget.md), [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), [batch-bo](/concepts/batch-bo.md),
  [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md), [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md),
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md)
- Source files: `botorch_predict.py:215-231` (_fit_gp), `botorch_predict.py:252-254`
  (ref point), `bo_driver.py:245-320` (skopt path),
  `graph/nodes.py:114-119` (skopt on the retry path)

## Open questions / TODO
- ~~Log `likelihood.noise` post-fit~~ DONE 2026-07-13 (163bb2e; first reading in [bo-noise-budget](/concepts/bo-noise-budget.md)).
- Decide leaderboard σ/njobs column shape before wiring train_Yvar (the one
  adopted follow-up from the LOO verdict; env-flag the picker change for A/B).
- ~~LOO verdict pending~~ DONE 2026-07-13 — five-way table + verdict in Key facts;
  reference JSONs moved off /app on 2026-07-17 to
  `/exp/mu2e/data/users/oksuzian/autoresearch_benchmarks/{loo_results_2026-07-13,
  holdout_ff16_2026-07-14,holdout_ff16ff17_2026-07-15}/` (regenerable via
  `/exp/mu2e/data/users/oksuzian/autoresearch_tools/gp_loo_benchmark.py`; the verdict numbers live in Key facts above).
- Score the NEXT campaign's fresh rows through `/exp/mu2e/data/users/oksuzian/autoresearch_tools/gp_loo_benchmark.py`
  variants as the honest held-out test before adopting train_Yvar.
