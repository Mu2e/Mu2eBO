---
type: concept
title: GP density-cloud rendering gotchas
description: 'GP density cloud silently fails to envelope top-3 champions: <1.1%
  of Sobol samples at sob≥3.2 (invisible under LogNorm) + GP under-predicts calo
  there by 2.3× (matches forward-LOO log-calo bias −0.80)'
status: active
timestamp: '2026-07-17'
updated_note: '2^22 pushforward: chunked predict + O(N log N) pareto2d_idx required'
---

# GP density-cloud rendering gotchas

## Scaling the pushforward past 2^20 needs two mechanical fixes (2026-07-10)
Bumping `N` in `gp_predict_foilsflash_perpot_cloud.py` beyond 2^20 hits two
walls: (1) sklearn `gp.predict()` materializes K(X*,Xtrain) in one shot —
2^22×239 float64 ≈ 8 GB → predict in 2^19 chunks (`_pred` helper in main());
(2) the naive O(N²) `pareto()` python loop is ~minutes at 2^20 and ~an hour at
2^22 → `pareto2d_idx()` (sort desc by sob + `np.minimum.accumulate` running-min
sweep, O(N log N), seconds at any N; exact same front modulo exact-duplicate
ties). Both scripts (plot + design dump) moved to N=2^22 in lockstep 2026-07-10;
pre-edit backup `gp_predict_foilsflash_perpot_cloud.py.bak-pre2e22` (dir is
UNVERSIONED). Reminder: the cyan-front point count changes with N
(render-dependent, see gotcha below) — expect n≠55 in the new legend.

## The cyan "GP Pareto" dots ARE concrete designs — dump script (2026-07-10)
Every cyan dot in `docs/foilsflash_perpot_cloud.png` is a GP *prediction at a
specific 6D Sobol point* — the x-points exist but the plot script discards them.
`mmackenz_table_plots/dump_gp_pareto_foilsflash_designs.py` regenerates the
pushforward with the SAME seeds (GP random_state=42, Sobol seed=42, N=2^20,
imports `load/make_gp/pareto/norm/BOUNDS` from the plot module so it can't
drift) and writes the full frontier to `gp_pareto_foilsflash_designs.tsv`
(sob_pred, flash_pred, 6 knobs). Matched the rendered n=55 exactly on first
run. Findings (n=239 fit, 2026-07-10): best-sob end (3.88/1.07e-6 @ 114.6,
100.2, hT 0.071/0.185, f 0.17/0.10) ≈ the SOBX01 transplant design (measured
3.90 — that corner is VERIFIED); the **knee (~3.55-3.57 @ 6.7-6.8e-7: thin
upstream ~30-70 µm half-thk + moderate downstream hole f_dn~0.4-0.5) predicts
slightly better sob than the measured champion at equal flash — best
unevaluated probe candidates**. Any row is launchable via forced `--x-point`.

## foilsflash has TWO cloud scripts — use the flash-per-POT one for the deck (2026-06-30)
There are now two foilsflash cloud renderers; the deck (`docs/foilsflash_talk.html`) uses the SECOND:
- `gp_predict_foilsflash_cloud.py` → `docs/foilsflash_predicted_cloud.png`: y-axis = per-event MEAN
  flash. **SUPERSEDED / do not use for the deck** — the mean is blind to the flash lever (see
  [bo-foilsflash](/projects/bo-foilsflash.md) metric bug). Left on disk for reference only.
- `gp_predict_foilsflash_perpot_cloud.py` → `docs/foilsflash_perpot_cloud.png`: y-axis = **total
  flash edep per POT** (the correct metric). Self-contained: joins each config's `summary.json`
  `flash_edep_total_MeV` + `state/elebeam_flash_outputs.txt` line-count ×110000 ×(1/11.53
  POT-per-e⁻). Colored by `extra_rOut_dn` (dominant knob, corr −0.60).
  Uses the capped length-scale `make_gp` (`length_scale_bounds=(0.05,0.5)`) per the fix below.
  **This is the one in the deck.** `.venv-botorch`.
  - **GOTCHA — the scatter set is a HARDCODED campaign-prefix allow-list in `load()` (~line 44):**
    `if not (cfg.startswith("foilsflash02") or ...03 or ...04): continue`. New rounds do NOT appear
    until you add their prefix there — silently missing rows, not an error. Extended to ff04
    2026-07-01 (n=45→55), then ff05+ff06 2026-07-03 (n=121, filter now ff02–06 at lines ~44–46).
    Now a `range()` form: `tuple(f"foilsflash{i:02d}" for i in range(2, N+1))` at line ~44 —
    still needs the upper bound bumped per round (range(2,14) for ff13, 2026-07-11); SOBX01 is
    a separate explicit `or`. The deployed-default gold star is added separately via `_one("foilsflashHOLEDhi")`
    and is NOT in the allow-list (it's a one-off n=0-extras A/B point, deliberately excluded from the
    BO scatter). Convergence warnings ("length_scale close to upper bound 0.5") are EXPECTED (the
    intentional cap), not a fit failure.
  - **"Better stats" render bump (2026-07-03): Sobol pushforward `N` 16384→131072 (8×, line ~77) +
    `n_restarts_optimizer` 5→10 (line ~61).** Smoother density + tighter GP fit (~5–6 min runtime).
    GOTCHA: the drawn **GP-Pareto point count is RENDER-dependent, not a data signal** — it rose
    n=20→37 purely from the denser pushforward + more restarts on the SAME 121 evals, NOT because the
    optimizer found new front points. Don't read a bigger cyan front as "more Pareto solutions."

## foilsflash "narrow flash band vs wide dots" is NOT a bug — a 3rd distinct narrowing mode (2026-06-29, 3-agent audit)
`gp_predict_foilsflash_cloud.py` (sob on x, tracker e-flash `flash_edep` on log-y).
User flagged the viridis density as a thin horizontal band while the 48 eval dots
scatter ~3× wider in flash — "looks like a bug." Three parallel agents (framing,
GP-fit, data) all returned **NOT a bug**; the band faithfully shows the GP found
**no smooth geometry signal in flash**.

- **NOT y-clipping (framing agent).** Histogram y-range `[-2.72,-2.44]`
  (`gp_predict_foilsflash_cloud.py:102`, ≈flash[1.91e-3,3.63e-3]) brackets BOTH the
  dot extent [-2.616,-2.501] and the GP-mean pushforward [-2.559,-2.525]. **0/48
  dots and 0/16384 Sobol-mean points clipped in y.** The band is genuinely thin
  (pushforward width 0.035 dex ≈8%) vs dots 0.115 dex ≈30%.
- **NOT a fit/transform/box bug (GP-fit agent).** `10**predict` inverts log10
  correctly, `normalize_y` not double-applied, all 6 dims' data inside BOUNDS (no
  v3-style box mismatch).
- **NOT a data bug (data agent).** 48 `flash_edep` all clean, max/min=1.30 (no ×1000
  prescale discontinuity), cross-campaign harvest identical (`flash_total/flash_events`,
  nPrescale=1), zero residual rows from [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
  or [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md). Dot CoV 5.1% (production ff02/ff03 rows
  3.5–4.3%; smoke 14.8% at ~700 flash events — low-stats, not biased). **Linear fit of
  flash on all 6 knobs R²=0.17** → only ~17% of flash variance is geometry; the rest
  is per-eval noise on a near-flat response.

**The real mechanism = a THIRD narrowing mode distinct from the two below.** The flash
GP's Matérn length-scales **rail at the FLOOR**: 5 of 6 at the 1e-1 lower bound (6th
=0.123), and WhiteKernel noise **rails at the 3e-2 CAP** (both fire sklearn
ConvergenceWarnings). With correlation length ≈0.1 in the normalized [0,1]⁶ box, a
generic Sobol point is essentially never within range of any of the 48 training
points → posterior mean **reverts to the prior/bulk mean everywhere** → flat band.
The dots are **isolated interpolation spikes** the Sobol grid almost never lands on
(in-sample residual at the 48 coords ~**0.1%**, NOT shrunk). So dots and cloud occupy
*different regions of input space* — this is NOT the prodtarget6d denoising/shrink
story (that shrinks training points ~2.3%; here the GP interpolates them to 0.1%) and
NOT the foils-v3 Sobol-box mismatch (box coverage is clean). It is length-scale
collapse → mean-reversion, with a clean box.

**Decisive control: the sob GP through the IDENTICAL pipeline.** Healthy O(1)
length-scales (`[2.27,1.13,1.31,0.55,0.54,7.2]`, none railed), noise floored at 1e-5,
perfect interpolation, pushforward std = **104% of the dot std** → it DOES envelope
its dots. Same renderer, same Sobol grid, wide cloud. Code can't be the cause when one
axis works and the other doesn't → the flat flash band is a property of the flash
DATA (weak geometry dependence), corroborating the [bo-foilsflash](/projects/bo-foilsflash.md) null result.

**How many σ are the dots from the cloud? ~1σ (quantified 2026-06-29).** The
"wide dots vs thin band" is purely a mean-only render: the visible band (GP-MEAN
pushforward) has log10-std **0.12%**, but the GP's PREDICTIVE σ averaged over the box
is **5.45%** — ~**45× wider** than the band. Dot scatter (CoV 5.07%) ÷ mean
predictive-σ (5.45%) = **0.99** → dots sit ~1σ around the mean; a `mean±1σ` render
(~±5.5%) would envelope essentially all of them. In-sample the dots are ~0σ (mean
|z|=0.10, they interpolate to 0.125% at their own coords). Forward-LOO (refit on the
other 47): **mean|z|=0.97, median|z|=0.71**, only **3/48 exceed 2σ** (all 3 also >3σ,
max |z|=6.6, max LOO resid 22%) — the sparse high-sob thin-foil corner the GP can't
extrapolate to from interior data (same corner-undersampling surprise family as the
prodtarget6d/foils clouds, not foilsflash-specific). So the dots are NOT far from the
GP — they're exactly within its (large) predictive σ; the band only LOOKS narrow
because it shows the mean. Script: `scratchpad/sigma_dots.py` (LOO + predictive-σ).
**It is NOT the log y-axis.** flash spans only 1.9× across the panel, so log≈linear
(log compression only bites across decades): band occupies 12.4% (log) vs 13.3%
(linear) of panel height, dots 41.2% vs 42.7%, dots/band ratio **3.3× (log) vs 3.2×
(linear)** — switching to linear moves nothing. The wide-vs-thin look is the
mean-without-σ render, not the axis.

**The one genuine defect was cosmetic and on X, not Y.** 6/48 dots have sob>3.4 (the
thin-foil `foilsflash03R02_*`, up to 3.77) and fell outside the histogram x-range
`[1.2,3.4]`; with no `set_xlim` the axis autoscaled and plotted them right of the cloud
over empty density — same XLIM-framing class as the prodtarget6d/foils precedents below.
**Fixed 2026-06-29:** `gp_predict_foilsflash_cloud.py:102` x-upper `3.4→3.9` (dot sob
max 3.77; y-range unchanged); PNG + `docs/foilsflash_talk.html` re-rendered.
**Optional, NOT done:** a mean±predictive-σ render would cover the dots (the degenerate
fit dumps unexplained variance into wide posterior σ away from data) — but
predictive-spread was REJECTED for prodtarget6d (see that section); same reasoning,
leave mean-only.

## n=112 re-measurement (2026-06-17) — mean-range compression DOMINATES; supersedes the n=105 ranking below

Three-fork team re-measured the prodtarget6d cloud/star mismatch on the **current n=112 fit** (calo>0 rows of `leaderboard_bo_prodtarget6d_v0.tsv`, fit reproduced from `botorch_predict_prodtarget6d_cloud.py`). The ranking in "What the cloud actually IS" below is **corrected**:

1. **DOMINANT — GP posterior-MEAN range compression (not σ, not corner sampling).** Sobol-predicted μ spans **[1.813, 2.384]×10⁻³** but observed μ spans **[1.746, 2.493]×10⁻³** — the cloud's μ-extent is *strictly inside* the observed extent on BOTH ends. Best star `pt6d07R01_07` (μ=2.493) sits to the **right of the cloud's right edge**; no Sobol pixel can reach it because the GP mean reverts toward bulk (Standardize + Matern smoothing). Any star at the μ-extremes is outside the cloud **by construction**. The Layer-1 acq-heatmap does NOT fix this — re-weighting what's plotted can't extend the GP-mean μ-ceiling.
2. **SECONDARY — box-corner Sobol under-sampling (visual thinning only).** 9/17 pt6d07 picks have ≤1 of 65,536 Sobol draws within normalized-L2=0.15 (board-wide 52/112 picks have ≤1); those bins hold ~1 count and vanish under LogNorm vmin=1. Real but widespread, not pt6d07-specific.
3. **REFUTED (harder than before) — high-σ exploration.** σ at picks is much LOWER than bulk: **σ_μ = 0.40× bulk, σ_logdose = 0.093× bulk** (dose axis: GP is extremely confident everywhere the picker went). More extreme than the documented n=105 numbers (0.70× / 0.40×).

**z-score distribution (forward-LOO, n=112 fit) — MAGNITUDES ARE NOISE-CONVENTION-SENSITIVE (corrected 2026-06-17, 3-fork re-review):** the exact z depends on whether the GP's observation noise is in the denominator. Honest refit-on-(n−1) both ways:
- **noise-inclusive** `√(predvar+noise)` (the formula the prose states): z(R01_07)=**2.29**, pt6d05R01_05=**3.35**, **1** row >3σ.
- **latent-only** `observation_noise=False`: z(R01_07)=**3.42**, pt6d05R01_05=**6.41**, **17** rows >3σ.
The previously-quoted "z=2.57 / 5.39 / 4 rows >3σ" set reproduces under **neither** convention — it was an internally-inconsistent mix plus fit stochasticity; **do not quote z to that precision.** What is **robust under both conventions**: `pt6d05R01_05` is unambiguously the **largest** mu-axis outlier; `pt6d07R01_07` is a **modest** surprise ranking ~3rd–4th, **never the biggest**; top-3 latent ranking = pt6d05R01_05 > pt6d04R00_00 > pt6d05R00_07. The deck's old "+3.2σ, only such surprise" R01_07 claim is **stale and was removed from the deck 2026-06-17**.

**Do not confuse this LOO z with measurement noise.** The LOO z is *GP-prediction surprise*. The separate measurement-Poisson σ on `mu_per_POT` is ~3% rel (√N/POT on the ~1000-count VD numerator; see [bo-noise-budget](/concepts/bo-noise-budget.md)). As a pure measurement fluctuation the champion is **+6.6 Poisson-σ above the 2.0e-3 bulk** (real high-t-corner signal) but only **+1.2 Poisson-σ over runner-up** pt6d07R00_03 (2.402e-3) → the **+4% #1 lead is statistically unresolved** at 500k POT; a confirmation re-run is warranted before trusting the ranking. Data-integrity fork separately CONFIRMED the eval is clean (90/100 jobs landed, denominator from landed files so unbiased, geometry built correctly, internally exact).

**Root cause of the champion's out-of-cloud surprise = the pt6d07 t-upper box raise 7→8 (2026-06-18).** The champion sits at t=(7.15,7.51,7.71) — entirely inside the t>7 region that NO eval could reach before pt6d07 (cap was 7.0). Only **17 of 112** rows are in this new region and it carries genuine signal: mean μ = **2.295e-3 (new, t>7) vs 2.186e-3 (old, ≤7) = +5%**. The top-2 μ rows (champion 2.493 @tmax=7.71; pt6d07R00_03 2.402 @tmax=7.91) are BOTH new-region. The GP mean over this sparse new corner extrapolates from the 95 old-regime rows that anchor a lower surface → reverts down → under-predicts the champion → it reads as a +z surprise AND falls right of the mean-pushforward cloud edge. So the box raise is the DIRECT cause for *this* champion. **Two caveats:** (a) it is NOT the whole "surprise" story — the largest forward-LOO outlier `pt6d05R01_05` is an *old*-regime pick pinned at t1=7.00 (the old cap edge); box-EDGE under-sampling produced surprises before the raise too, the raise just relocated the binding edge. (b) The pt6d07 end-plate lug clamp (`lPlate[0]=lPlate[-1]=tPlate`, 2 of 35 plates) is a negligible μ effect — the μ lift tracks tmax, not the clamp. General mechanism: GP mean reverts at any under-sampled box edge; the 7→8 raise is the latest instance.

**Controlled test — subsetting to raised-limit data only HALF-fixes it (2026-06-18).** Refit the cloud on ONLY the 17 pt6d07 (all t>7) evals — now a first-class flag: **`botorch_predict_prodtarget6d_cloud.py --current-box-only [--tmax-min 7.0]`** filters to rows with `max(t0,t1,t2) > tmax_min` and writes `*_t8only.png` (default behavior unchanged = full n=112; suffix keeps it from clobbering the full clouds): GP-mean μ-max moves **2.384e-3 (full n=112) → 2.442e-3 (raised-limit n=17)**, but the champion (2.493e-3) is **STILL outside** (gap 0.109 → 0.051). So dropping the old t≤7 rows closes only **~53%** of the out-of-cloud gap (confirms the old-data drag was real, ~half the effect); the residual **~47% is intrinsic GP posterior-MEAN range compression** — the max *observed* (noisy) point is pulled below itself by Standardize+Matern even when it IS the max of its own training set. **Conclusion: no data-subsetting can envelope the champion; only a predictive-spread render (`y~N(mean,σ²+noise)`, see Open questions) can.** (Caveat: n=17 in 6D rails/overfits — treat the 2.442 edge loosely; the subset cloud is a tiny high-μ/high-dose blob since it contains only thick-plate configs, Stickman baseline outside it lower-left.) **Re-fit after pt6d08 (2026-06-18, n grew): conclusion HOLDS.** Box now 30 rows (t8only) of 126 total: t8only GP-mean edge **2.442 (n=17) → 2.458 (n=30)**; full-fit edge **2.384 (n=112) → 2.440 (n=126)** — as high-t data accumulates the full fit's edge rises toward the t8only fit (gap between the two narrows 0.058→0.018), but the champion (2.493) stays **outside both**. Confirms the residual is intrinsic mean-compression, not a transient small-sample artifact: more data does not envelope the max. **Re-fit through pt6d16 (2026-06-26, n=322 / t8only=213): the t8only edge is NON-MONOTONIC — it rose then FELL: 2.442 (n=17) → 2.458 (n=30) → 2.482 (n=92) → 2.350 (n=213).** As the box fills with mid-μ rows the GP mean compresses *harder*, pulling the edge DOWN and *away* from the champion (2.493) — i.e. more data makes the out-of-cloud gap WIDEN, not close. Definitive: no amount of in-box data envelopes the champion via the mean pushforward; only a predictive-spread render can.

**Renderer-honesty fork — acq-heatmap star coverage (2026-06-17).** Quantified fraction of pt6d07 stars landing in a histogram bin above the 50th-pct of nonzero bins: density baseline **24%**, shipped **acq-heatmap 65%**, PowerNorm(γ=0.3) **24%** (no-op — only recolors empty bins, doesn't add coverage), importance-Sobol **65% (71% all-board)** but self-referential so not a more *honest* panel. **Verdict: keep the deck's density + acq-heatmap pairing.** The residual ~35% uncovered pt6d07 stars are the mean-range-compression / corner mean-bias — no renderer can fix it.

**Layer-3 fixability fork — the corner mean-bias is NOT a fixable model defect (2026-06-17). Layer-3 is RETIRED, do not attempt.** Forward-LOO on the 14 high-t corner picks (t≥7.5): baseline default SingleTaskGP gives mu LOO-z mean +0.87, range [−2.20, +3.42] (the +3.42 max IS pt6d07R01_07 — reproduces the surprise). Bias is **mu-only**; dose LOO-z is well-calibrated (mean +0.04, range [−1.02, +1.77]). **Mechanism:** fitted mu noise = **0.304 in standardized units** (σ_noise≈0.55) — the GP attributes ~30% of standardized mu-variance to noise → heavy smoothing → corner extrapolations revert to global mean → genuine corner gains read as +Nσ. Lengthscales do NOT rail (mu dims [0.52,0.72,0.60,0.73,0.39,0.70], all interior) so this is NOT under-identification, and the dose −log10 span (0.624) is NOT degenerate (so the [botorch-tiny-output-log-training](/concepts/botorch-tiny-output-log-training.md) incident does not apply here — dose is the well-behaved axis). **No lever helps; several hurt:** ARD Matern + GammaPrior(3,6) lengthscale → mu |max|z 6.88 (2× worse, shorter LS → sharper reversion); noise_lb=1e-6 → 6.85 (worse); Kumaraswamy input warping w/o normalize → 29.35 (catastrophic, destroyed dose channel). Default kernel is the best of everything tested. **Conclusion: the corner picks are genuine physics surprises the GP cannot anticipate from interior data** — the 0.30 fitted mu-noise is real per-config Poisson scatter, the high-t corner is unsupported, the GP correctly reverts to mean. The ONLY thing that shrinks corner z-scores is more evals in the corner (the picker is already doing this). Layer-1 acq-heatmap (shipped) is the right and final response; chasing mean-bias via kernel tuning would only inflate the surprises.

## The frontier reaching >1.18 norm (sob>3.91) is GP OVER-EXTRAPOLATION, not real (2026-06-23)
The cloud's Pareto-frontier line extends past the measured max (3.91 = 1.18 norm)
because the **sklearn cloud GP extrapolates above its training data**: fitting
the honest set (n=160), `gp.predict` over 65 k Sobol reaches **sob max 4.22**
(training max 3.91), but only **0.26% of Sobol points exceed 3.91** — invisible
under LogNorm density, yet the frontier LINE connects them, so the eye sees a
frontier reaching ~1.2+ backed by ~no density. **Root cause (CORRECTED 2026-06-23, agent-tested): it's the LENGTH SCALES, not
the noise.** Empirical test on the honest set (n=160): free-noise pred max 4.22;
fixing noise to measured σ²=0.015² (drop WhiteKernel) → 4.21 (NO help — the noise
rail was a red herring); **capping Matern `length_scale_bounds` upper 1e3→0.5 →
3.87, 0% of Sobol >3.91** ✓. The fitted length scales are ~1–2 in the UNIT cube
(`norm` maps each dim to [0,1]), i.e. ≥ the domain width → the kernel is
near-linear along each axis → the posterior mean ramps past the data into
unobserved corners. **78% of the 65k Sobol points lie OUTSIDE the convex hull of
the training data** — most of the cloud is extrapolation, and long length scales
let the GP confidently ramp the mean there. The botorch picker GP avoids this via
its GammaPrior regularizing the lengthscale shorter (caps ~3.83). The botorch
PICKER GP (Standardize + stronger learned noise) reverts to mean and caps
sampled predictions at ~3.83 — same data, different extrapolation. **Empirically
disproven as achievable:** the pareto_sob run ([pareto-sob-picker](/concepts/pareto-sob-picker.md)) built the
GP's top-predicted points → measured 3.69–3.84, NEVER above 3.91. **Not a code
bug** (the cloud is the GP-mean pushforward by definition) but MISLEADING — the
frontier implies reachable sob>3.91 that doesn't exist. **PROPER FIX (APPLIED 2026-06-23, `make_gp`):** `Matern(length_scale=[0.3]*NDIM,
length_scale_bounds=(0.05, 0.5))` + WhiteKernel `noise_level_bounds=(1e-3, 3e-2)`
(floor raised 1e-5→1e-3 so noise can't rail to near-interpolation). Verified on
the honest cloud (n=160): sob range **0.62–4.07 → 0.54–3.85** (spurious >3.91
extrapolation GONE, frontier ends just below measured max), calo range sane
(7.5e-7–2.75e-5, shared-`make_gp` calo GP not degenerate). NOTE: kept the
WhiteKernel rather than a hard `alpha=σ²` because alpha is in normalized-y space
(normalize_y=True) and sob vs calo have different scales — raising the noise
*floor* is the scale-safe equivalent and the length-scale cap is what actually
kills the artifact anyway. Caveats: the **calo GP shares `make_gp`** — validate its
pred range too (log10-calo may want a different scale); the deeper upgrade
(separate) is σ-shading / convex-hull masking so the 78%-extrapolation region
reads as uncertain. Rejected: raise-noise-floor alone (doesn't address cause) and
clip-the-frontier (cosmetic patch).

## "Stars outside the cloud" (prodtarget6d) is NOT a bug to fix — predictive-spread REJECTED (2026-06-23)
The prodtarget6d cloud being "too narrow" (champion pt6d07R01_07 sits right of the
density edge) is the honest dual of foils over-extrapolation: it's a posterior-MEAN
pushforward, and the botorch GP (fitted obs-noise ~0.30 std) reverts the mean
toward the bulk, so predicted μ [1.83,2.38]e-3 ⊂ observed [1.75,2.49]e-3 → no
Sobol mean reaches the champion BY CONSTRUCTION. A proposed fix — re-histogram a
sampled predictive spread y~N(mean, var+noise) — was **REVIEWED AND REJECTED**:
(1) a ±2σ band on all 65k points smears the whole cloud uniformly (covers the
champion only by making everything fuzzy incl. zero-data regions → "where the GP
can't rule anything out", low info); (2) adding MEASUREMENT noise (Poisson ~3%,
a property of one realized eval) to the *displayed* design-performance cloud is
dishonest framing — epistemic var is the only defensible widener; (3) a band
MASKS the real cause (champion in the sparse t>7 box edge where the mean reverts).
**Decision: leave as-is** — the mean-cloud + the existing prose annotation +
stars-plotted-on-top is correct. At most a thin EPISTEMIC-σ-only contour (no
measurement noise) could be overlaid, but it's cosmetic. Do NOT re-propose
sampled predictive-spread.

## prodtarget6d GP does NOT reproduce its own training points — UNDERFIT (2026-06-23, measured)
The deepest "stars far from cloud" cause, measured by evaluating GP-mean AT each
training star vs its observed value (all 3 modes use the same SingleTaskGP+Standardize):
| mode | mean |resid| at training stars | GP-at-stars range vs observed |
|---|---|---|
| foilsf (n=456) | **0.11%** | 0.55–3.91 = obs 0.56–3.91 (interpolates) |
| ipa (n=50) | **0.07%** | 2.45–3.31 = obs (interpolates) |
| prodtarget6d t8 (n=156) | **2.3%** | 2.18–2.35 ≪ obs 2.06–2.49 (SHRINKS) |
foils/ipa GPs **pass through** their training points (residual ~0.1%) → stars sit
ON the cloud. The prodtarget6d GP **cannot fit its own training points** — pulls
them toward the mean by ~2.3% (champion dragged DOWN 6%, 2.493→2.343e-3), fits
obs-noise 5.1e-5 (~2.3% of μ, vs ipa 0.6%). So prodtarget6d stars scatter off the
cloud because the GP UNDERFITS, not (only) framing/compression. **Two candidate
causes:** (1) μ_per_POT genuinely ~3% Poisson-noisy ([bo-noise-budget](/concepts/bo-noise-budget.md)) → GP
correctly smooths, stars are noisy draws; (2) the 6D quadratic-profile
parameterization can't represent the μ surface → GP dumps unexplained signal into
noise. **RESOLVED 2026-06-23 (team-tested): it's CORRECT behavior — real ~3% measurement
noise, NOT misspecification.** (My earlier "favors misspecification" guess above
was WRONG.) Decisive tests: (a) fitted GP noise = **3.1% of μ**, exactly the
μ_per_POT Poisson floor (~3% at 500k POT, [bo-noise-budget](/concepts/bo-noise-budget.md)); (b) forcing
noise→1e-6 drops in-sample residual 2.27%→**0.00%** — the GP CAN interpolate, it
correctly CHOOSES not to because ~3% of the μ scatter is genuine noise; (c) ARD
refuted — SingleTaskGP already uses ARD Matern-5/2, lengthscales short/non-railed
(0.34–0.62), explicit ARD refit made residual WORSE (2.44%); (d) no near-duplicate
geometries so aliasing untestable but no residual variance left to attribute to it.
**The real reason prodtarget6d differs from foils/ipa: its measurement is ~7×
noisier (μ_per_POT 3% Poisson vs foils sob 0.4% / ipa 0.6%)** — same GP code, the
GP correctly de-noises, so noisy stars scatter ±3% off the de-noised cloud while
foils/ipa near-noise-free stars sit on theirs. **Only fix is PHYSICS: more
stats/eval (500k→2M POT ≈ ½ the Poisson σ), NOT ARD/kernel/richer-basis/render
changes.** Leave the GP as-is; xlim-zoom + "stars are ±3% noisy draws" annotation
is the honest presentation.

## "Cloud too narrow" was an XLIM-FRAMING bug, not a data bug (2026-06-23, full audit)
A fresh-eyes audit of `botorch_predict_prodtarget6d_cloud.py` cleared all
data-narrowing hypotheses: NO histogram-range clipping (data fits inside),
stars+density on MATCHING axes/transforms, Standardize round-trip correct
(`post.mean` auto-un-standardizes; `mu_pred=mean[:,0]`, `dose_pred=10**(-mean[:,1])`),
Sobol N=65536 covers the box. The distribution narrowness IS real mean-compression
(pred μ [1.849,2.356]e-3 ⊂ obs [1.746,2.493]e-3). **BUT the REAL defect: the x-axis
range was hardcoded `[0.5, 3.0]` (μ·1e3) while ALL data lives in [1.75, 2.49]** —
so the cloud occupied only ~20% of the panel in a mostly-empty plot, which is what
read as "too narrow." Fixed 2026-06-23: `range=[[0.5,3.0],...]` → `[[1.6,2.6],...]`
at both `histogram2d` calls (lines 155, 171) + `ax.set_xlim(0.5,3.0)→(1.6,2.6)`
(line 205). Honest (just zooms to the data, Stickman μ≈2.17 stays in frame); does
NOT touch the distribution. **Lesson: "looks too narrow" can be a panel-framing
artifact — check xlim vs data extent BEFORE diagnosing the model.**

## "Champion outside the cloud" appears in ALL clouds where the best point is an outlier (2026-06-23)
The mean-pushforward puts the champion OUTSIDE the density wherever the best
measured point is under-sampled (GP mean reverts toward the bulk there). Measured:
- **prodtarget6d**: GP-mean edge 2.428 vs champion 2.493 → **outside +2.6%** (sparse
  t>7 box edge + strong fitted noise = biggest reversion).
- **foils (POST length-scale-fix)**: edge ~3.85 vs champion 3.91 → **outside +1.5%**.
  The fix CAUSED this — capping the length scale stopped the over-extrapolation
  to 4.07, so the mean now reverts and the 3.91 lone-outlier champion (≈5σ above
  the 3.82 cluster) sits just past the edge. Traded "too wide / false headroom"
  for the honest "ends at mean-max, outlier escapes". Correct, same as prodtarget6d.
- **IPA**: edge 3.31 = champion 3.31 → **at edge (~0%)**. TWO reasons (review-verified
  2026-06-23): (a) its top is NOT an isolated outlier — champion only **1.5σ** above
  its next-4 (3.31 vs 3.297±0.008) vs foils' champion **6.3σ** above its next-9
  (3.91 vs 3.812±0.015); AND (b) IPA's GP is STILL UNFIXED — fitted length scales
  huge (4–52), so it over-extrapolates (like pre-fix foils) and the inflated edge
  rises to meet the champion. So IPA's 0% is PARTLY luck: if IPA gets the same
  length-scale cap, its champion would likely pop slightly outside too. The rule
  "magnitude tracks outlier-ness" holds only for properly-CAPPED GPs; an unfixed
  long-length-scale GP can mask the gap regardless of outlier-ness.
  (Foils post-fix verified: pre-fix uncapped pred max 4.22 → champion masked
  INSIDE; post-fix capped pred max 3.852 → champion OUTSIDE — the cap CAUSED the
  flip, all 6 length scales rail to the 0.5 cap.)
**Rule:** champion-outside-cloud is normal mean-pushforward behavior when the best
point is an under-sampled outlier; magnitude tracks how outlier-ish the champion
is, not a per-cloud bug. Not something to "fix" (see rejected predictive-spread
above).

## Which clouds need the length-scale fix (2026-06-23 audit)
- **foils** (`gp_predict_foils_v2v3_cloud.py`, sklearn `make_gp`): HAD the bug,
  FIXED (length_scale_bounds 1e3→0.5). 
- **IPA** (`gp_predict_ipa_cloud.py`, sklearn `make_gp`): IDENTICAL unfixed
  `length_scale_bounds=(1e-1,1e3)` code, BUT empirically NOT over-extrapolating —
  pred sob max = 3.31 = exactly the measured max (n=50, denser data rel. to its 5D
  box, no sharp high-sob corner like foils 6D). Not broken now; apply the same cap
  only as future-proofing if its high-sob corner sparsens. (Decision left to user.)
- **prodtarget6d** (`botorch_predict_prodtarget6d_cloud.py`, botorch
  `SingleTaskGP`+Standardize): different backend, GammaPrior already regularizes
  the lengthscale short → NO over-extrapolation; it *compresses* instead
  (champion sits past the GP-mean edge). NO fix needed.
- **Takeaway:** the bug is specific to the sklearn `make_gp` with unbounded
  length_scale on a SPARSE high-value corner; botorch clouds are immune.

## Cloud x-axis is NORMALIZED sob (÷ nominal Run1A ≈ 3.3), not raw sob (2026-06-22)
The foils/helical cloud x-axis is **`sob / x_scale`** where `x_scale =
get_x_scale(table_rows)` = the "Nominal Run 1A" sob from table.org, **fallback
3.3** (`cloud_plot.py:102`). So a frontier value of **1.2 on the plot = ~3.96
raw sob** (1.2×3.3); the GP envelope max ~4.06 = ~1.23 norm; the measured 3.91
champion ≈ 1.18 norm. **Easy to misread the frontier as "sob>1.2"** — it's
normalized. The frontier sitting at ~1.2 while real evals top out ~1.18 is the
GP sparse-fit over-extrapolation (predicts a hair above anything built), NOT a
measured config above 3.91. (The IPA cloud `gp_predict_ipa_cloud.py` uses RAW
sob on x — no x_scale — so this caveat is foils/helical-only.)

## What the cloud actually IS — and why picks land in sparse regions (2026-06-17)

The "GP cloud" image (foils, helical, prodtarget, prodtarget6d — all renderers under `mmackenz_table_plots/`) is mathematically the **pushforward of Lebesgue measure on the input box** through the **GP posterior MEAN only**, binned into a `histogram2d(200×200)` and color-mapped by `LogNorm(count)`. One pixel value = "how many of N=65,536 uniform-Sobol input-space draws have posterior-mean output landing here."

**Empirical-fork verdict (2026-06-17, pt6d07 R1 picks vs n=105 GP fit) — high-σ-at-picks intuition is WRONG.** The cloud actually discards three things, and σ_pred is NOT the main one:

1. **Box-corner Sobol under-sampling.** Lebesgue volume near a 6D box vertex shrinks geometrically; corners are vanishingly rare in 65 k uniform Sobol. 3 of 7 pt6d07 R1 picks have ≤1 Sobol neighbor within normalized-r=0.15 ball. Picks LOOK sparse in the cloud because input-volume sampling under-represents corners, not because the GP is uncertain there.

2. **GP under-identification + mean bias near box edges (the real surprise).** σ_μ at pt6d07 R1 pick locations is **0.70× the bulk** (6.2e-5 vs 8.8e-5); σ_logdose is **0.40× the bulk**. The GP is *confident* at the corners qNEHVI picked. But `pt6d07R01_07` came in at observed μ=2.493×10⁻³ vs GP-predicted μ=2.289×10⁻³ ± σ=6.4×10⁻⁵ — a **+3.2 σ surprise** (only such surprise in the batch). The GP's predicted MEAN is biased low at the box edge (length-scale rails / kernel under-identification), and the σ-envelope is too tight to cover the truth. So even a "cloud + σ-band" overlay would miss R01_07.

3. **Acquisition value.** qNEHVI optimizes Expected HVI, which here was driven by *mean uncertainty about whether the front extended* on a confident-but-biased mean, not by σ being large. Cloud is Lebesgue-weighted on input box; picker is HVI-weighted on the (biased) belief — orthogonal objectives.

So "picks land where cloud is sparse" is the expected mode, but for two layered reasons: (a) corner under-sampling visually, (b) GP mean-bias + tight σ at corners gives HVI free apparent improvement that the cloud renderer hides. Same family as the foils sob≥3.2 <1.1%-Sobol-coverage case (below) and the v3-only length-scale rail story; the R01_07 +3.2 σ surprise is the prodtarget6d-specific instance.

**Fix (proposed, not landed):** swap the density histogram for an **acquisition heatmap** — evaluate qLogNEHVI on the same Sobol grid and color by `log10(HVI)` instead of count. Picks then land in the bright region by construction (driven by HVI, not by σ). Cost: one extra `acq(Xs_t)` call per render (~30 s on N=65 k), no refit. Keep current density layer as faint underlay if "where does an unweighted sample land" still wanted. Note: this DOES NOT fix the underlying GP mean-bias at corners; it just makes the picture honest about what the picker is doing.

## Honest-only mode is now self-contained (2026-06-17)
`gp_predict_foils_v2v3_cloud.py --honest-only` (lines 116-122) was leaking "previous knowledge" two ways: (a) still called `cp.render_mmackenz_overlay` (the table.org background scatter), and (b) gold-star label hardcoded `"v3 foilsZ obs"` even though the kept rows are foilsf11/14 only. Fixed 2026-06-17: mmackenz overlay gated off under `--honest-only`, star label switches to `f"honest-hole obs (n={len(s3)})"`. Means the n=40 honest cloud now uses *zero* v1/v2/older-v3/mmackenz info — GP fit, Pareto frontier, density, and the only stars on it all derive solely from foilsf11+14 calo>0 rows. Caveat from header: with n=40, GP length_scale rails at 1000 on dim 2 and noise_level rails at 1e-5 — sob_max reaches 4.06 (vs obs_max 3.83), still the sparse-fit extrapolation pathology documented elsewhere on this page.

**Run1A movable-target overlay added 2026-06-17 (lines 117-130).** `--honest-only` now re-introduces ONE class from `table.org` for physics context: the 20 "Movable target" (degrader) configs `v22`–`v41` (blue squares, `cp.CLASS_MARKERS/COLORS["Movable target"]`, zorder 8). These sit at sob≈nominal (~3.3) but calo≈1e-7–1e-6 — ~20–200× lower calo than the honest-hole foil champions (~2e-5). Filtered to `c > 0` (drops v22/v24 which have calo=0 in the table). The GP fit / Pareto / density / gold stars still derive solely from foilsf11+14, so this is a context overlay only, not a training input.

## Foils cloud renderers never plot picks (2026-06-17)
Structural asymmetry: `cp.render_picks()` (cyan diamonds) is called ONLY by the **helical** scripts (`gp_predict_helical.py`, `botorch_predict_helical.py`, `overlay_gp_predictions_helical_mpl.py`, `overlay_gp_with_rin80_pin.py`). The **foils** cloud scripts (`gp_predict_foils_cloud.py`, `gp_predict_foils_cloud_anim.py`, `gp_predict_foils_v2v3_cloud.py`, `botorch_predict_foils_cloud.py`) only call `render_density` + `render_pareto` + `render_star` — no picks layer, no read of any `gp_explore_picks.tsv` for foils. So slide 4 of `docs/foils_talk.html` shows magenta evaluated stars on the GP-predicted Pareto line by *coincidence* (BO drove evals onto the front), not because the current round's proposals are overlaid. To add cyan-diamond picks to a foils cloud: (a) emit a `gp_explore_picks.tsv` from the foils picker (historically written only by the helical picker via `compute_explore_picks` — mode retired 2026-07-12, so nothing produces the file today), and (b) wire `cp.render_picks(...)` after `render_pareto` in the chosen renderer.

## Anim wall-time (2026-06-17) — `gp_predict_foils_cloud_anim.py` ~2-3h single-core
`mmackenz_table_plots/gp_predict_foils_cloud_anim.py` re-fits **two GPs** (sob + log-calo) **from scratch per cumulative cohort** (`main()` loop at `:124-134`), then predicts on **N=65,536 Sobol** (`:83`). 16-20 cohorts × growing n (3 → 73 v1+v2 rows) at `O(n³)` fit + `O(N·n²)` predict ⇒ ~7-8 min/frame, ~134 min wall on 1 core (observed 2026-06-17: 2:13 CPU at frame ~last). No fit caching, no parallelism. **Cheap wins (none landed):** drop N to 8192 (8×), `n_restarts_optimizer=0` in `make_gp()` (`:29-33`) — restart loop dominates on small-n fits — or skip early `n<10` cohorts. Not a bug, just a perf gotcha when invoking outside the 4-hourly cron.

**Updated (older):** 2026-06-06 (purple low-calo tail overlay REMOVED from `cloud_plot.py:render_density` 2026-06-06 — was scattering bottom-p5 GP-predicted calo points at alpha=0.15 to compensate for LogNorm density saturation at count=1, but it shaded the deck cloud with a distracting purple band. Just deleted (no replacement); the LogNorm viridis density + Pareto frontier + observation stars carry the message without it. Affects every cloud script that calls `cp.render_density` — `gp_predict_foils_v2v3_cloud.py`, `gp_predict_foils_cloud{,_anim}.py`, `botorch_predict_foils_cloud.py`. v3-only-vs-v2+v3 cloud envelope discrepancy — dilution narrative DEMOTED 2026-06-06. The sob ranges match within 1% [v2v3 0.62-3.84 vs v3-only 0.63-3.88], so v2 is NOT suppressing the v3 posterior tail. **Leading explanation (candidate, not confirmed):** GP under-identification on the smaller v3-only training set (67 rows) — Matern length_scale saturates at the 1000 mm upper bound, over-smooths, paints a big diffuse cloud blob that *happens* to spread over the gold stars. v2+v3 (131 rows) better identifies length scales → tighter cloud that doesn't smear over the high-rIn corner stars even though the GP can still predict their sob. **Refit on n=117 v3-only (2026-06-06, post-foilsf01) sharpens the picture:** only dims 4 and 5 — `extra_f_up`, `extra_f_dn` — rail length_scale at 1000. The four absolute dims (rOut_up/dn, halfThickness_up/dn) identify fine. So under-identification is **fractional-hole-specific**, not global, and likely reflects a *genuine* GP statement that f doesn't drive obj in the explored region — not a kernel pathology. Sob range matches v2+v3 to within 1% (v3-only 0.62-3.83). Same family as the original sob≥3.2 <1.1% Sobol-coverage gotcha.)

## Root cause (2026-05-26): N_crit gate threshold mismatch
The "GP fit bias" framing below is INCOMPLETE — the dominant cause is that
top-3 champions are **excluded from GP training** by an over-aggressive
N_crit gate. Two filters use different thresholds:

- **Training** (`gp_predict_helical.py:131`): drops rows where
  `_ncrit(dx, dy, angle) > nsteps` with `nsteps = KNOWN_NSTEPS.get(cfg,
  DEFAULT_NSTEPS=100)`. So the gate is effectively `ncrit > 100`.
- **Sobol cloud** (`gp_predict_helical.py:202`): drops rows where
  `ncrit > nsteps_budget = 2000`.

Top-3 ncrit values (helicalL02=11,179 / graph023=1,551 / helical041a=227)
**all exceed 100**, so the GP never sees them during fit. Direct probe
(2026-05-26): GP's nearest Sobol neighbor to L02 (normalized-L2 = 0.016)
predicts calo=7.39e-6 vs observed 2.46e-6 (2.2× over) — and the 133 Sobol
samples within 0.05 of L02 all predict calo ∈ [5.3e-6, 8.6e-6], a band
that never touches the true value. Bias is structural training
exclusion, not kernel under-fit.

Deeper issue: `_ncrit` measures tessellated-solid self-intersection only.
After the 2026-05-21 G4TwistedBox dispatcher landed
([tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) / `tsda.helical.useTwistedBox`),
the constraint is moot for twisted-box runs (analytic solid, no facets).
The gate currently filters real twisted-box results en masse.

**Fix landed 2026-05-26** (`gp_predict_helical.py`): added
`_use_twisted_box(config)` helper that reads
`<grid>/<config>/geom/autoresearch_<config>_geom.txt` — absent or
key-missing means twisted-box (deployed-lib default since May 21).
Training-side N_crit gate now skipped when twisted-box. Sobol-side
gate dropped entirely (`buildable = np.ones(...)`); future tessellated
A/B would need per-pick re-gating. Empirical impact: GP training
**125 → 189 rows** (+64 previously dropped), Pareto frontier **630 → 85**
(GP no longer extrapolating into unanchored regions), new picks reach
sob=3.30 / calo=1.44e-6 (vs L02's 3.33 / 2.46e-6 — GP now predicts a
better champion exists at that region but it's an unverified prediction).

## Summary
The Sobol-sampled GP cloud in `overlay_gp_predictions_helical_mpl.py` can
silently *fail to envelope* the actual top-3 obj points (helicalL02,
graph023, helical050a) even though the GP technically predicts that region.
Two compounding effects: (1) the high-sob tail of Sobol samples is too
sparse to register against the LogNorm density colormap, and (2) the GP
under-predicts calo in the high-sob region (the same late-half log-calo
bias of −0.80 that forward-LOO calibration found). Result: gold-star
overlays of true champions sit "beyond" the visible cloud — but that's a
rendering artifact, not a GP-extrapolation failure.

## Key facts

### Sparse-tail invisibility
- Of 8.4M Sobol predictions (`PRED_TSV = gp_predictions_helical.tsv`):
  - GP sob range: [0.24, 3.71], 99th percentile = 3.23
  - **Only 1.1% (93,393 samples)** land at sob ≥ 3.2
  - `np.histogram2d` bins [230, 200] over [0,1.15] × [−8,−4] log calo;
    rare bins hold ~1 count and disappear under viridis+LogNorm
- Top-3 obj sob/x_scale values: L02 ≈ 1.0+, graph023 ≈ 1.0+, helical050a ≈ 1.0+
  — at or just past the visible density falloff at x ≈ 0.95

### GP under-predicts calo at high sob
- At sob ≥ 3.2: GP-min calo = **3.14e−6**
- Actual top-3 calo: **2.46e−6 (L02), 2.62e−6 (graph023), 3.08e−6 (helical050a)**
- Two of three sit *below* the GP envelope's lower edge
- Magnitude (≈2.3× under-prediction in linear calo) matches the late-half
  log-calo bias of −0.80 measured by `/tmp/residuals_over_iter.py`

### Why the visualization mismatch is structural, not a bug
- Density colormap rewards bulk; champions live in tails → invisible by
  construction unless you switch to scatter+alpha or contour-of-percentile
- Even with a perfect renderer, the GP-predicted lower-calo envelope at
  high sob is biased high — true champions can punch through the floor
- These two effects compound: the cloud is faint where champions live,
  AND its lower edge is too high there

### Low-calo asymmetry (2026-05-26): why no cloud below ~1e-7
The mirror of the high-sob blind spot, with one extra failure mode:

1. **calo=0 rows silently dropped from log-calo fit.** `gp_predict_helical.py:218`
   masks `pos = y_calo > 0` because `log(0)` is undefined. Currently 1
   leaderboard row (sob=1.04, calo=0) is excluded without further
   accounting — just a `dropping 1 rows with calo<=0` print at fit time.
2. **Sparse-tail invisibility (low end).** 15 observed configs sit in
   `0 < calo ≤ 5e-7` (sob 0.19–1.04). GP predictions can reach there:
   2,530 of 8.4M Sobol samples have predicted calo ≤ 5e-7 — but at
   **0.03% of the cloud**, the histogram bins hold ~1 count and vanish
   under LogNorm exactly like the high-sob tail does.
3. **Hard predicted floor at 2.34e-7.** Cloud min predicted calo = 2.34e-7;
   **zero** Sobol samples predict ≤ 1e-7. The WhiteKernel sits at its
   upper rail (`noise_level_bounds=(1e-5, 1e-1)`, rails to 1e-1) which
   noise-floors log-calo predictions. The GP cannot drive predicted calo
   arbitrarily low because the absorbed noise term dominates at that scale.
   Same kernel pathology already documented in `bo-helical` for the high-sob
   end.

### Mechanism of the 2.34e-7 floor (2026-05-26, agentic investigation)
Re-fit on current 188-positive-row training set confirms:
- Fitted kernel: `0.962^2 * Matern(length_scale=[0.1,0.1,0.1,0.1], nu=2.5)
  + WhiteKernel(noise_level=0.1)` — every length-scale railed to lower
  bound 0.1, noise railed to upper 0.1 (dual rail).
- `_y_train_mean = -12.657` ⇒ `exp(-12.657) = 3.18e-6`. With
  `normalize_y=True`, posterior mean far from any support point reverts
  toward `_y_train_mean`, NOT toward the low-calo cluster mean.
- 16 low-calo rows (calo ≤ 5e-7) cluster in a **narrow dy basin**:
  `dy_norm ∈ [0.0, 0.23]` (i.e. `dy ∈ [40, 123]` raw). With length_scale=0.1,
  only Sobol points within ~0.3 normalized of this basin feel any pull;
  outside, the noise rail (σ²=0.1 in normalized log-space) damps each
  row's leverage on μ.
- At the low-calo support points themselves, GP under-predicts by up to
  +3.5 nats (e.g. `graph002` neighbor of low-calo `graph015`: observed
  log=−16.00 vs predicted log=−12.46). Same mechanism the forward-LOO
  calibration found at the champion regime: GP reads sub-population rows
  as "high-variance scatter around bulk mean" rather than fitting them.
- The 2.34e-7 floor isn't a mathematical bound — it's the closest a Sobol
  point gets to the dy-basin cluster, partially pulled toward 3.18e-6 by
  the noise rail.

### `graph015` is the calo=0 row
`dx=0.456, dy=307.1, hl=184.9, ang=476.7, sob=1.04, calo=0.0`. Mid-range
params, meaningful sob — almost certainly a harvest artifact (zero events
survived the calo branch), not a feasibility-zero. Silently dropped by
`pos = y_calo > 0` mask at `gp_predict_helical.py:218`. **Open**: re-harvest
to confirm, then decide impute (0.5×min positive) vs broken-flag.

### Renderer bin occupancy (low-calo end)
For the 2,530 Sobol predictions with calo ≤ 5e-7:
- They concentrate in `sob/x_scale ∈ [0.12, 0.68]` (low-sob region, not
  the champion regime) → only **374 of 19,320 candidate bins** occupied
  (1.9%), max count = 24, 39% of occupied bins hold a single count.
- `LogNorm(vmin=1, vmax=527682)` (`overlay_gp_predictions_helical_mpl.py:182`)
  has 5.7-decade dynamic range; count=1 to 5 bins sit in dark-purple
  bottom-of-cmap, indistinguishable from masked-zero at 140 dpi.
- v2 magenta-star observations themselves ARE visible (15/16 with
  `calo ∈ [1.12e-7, 5e-7]` clear of `ylim` floor 1e-8); only `graph015`
  (calo=0) is unplottable on log-y.

### Fix path — Step A + C landed 2026-05-26
**Step A (WhiteKernel cap, landed).** `gp_predict_helical.py` line ~53
`noise_level_bounds=(1e-5, 3e-2)`. Empirical calibration:
- cap=1e-1 (baseline): floor 2.34e-7, Pareto 85, sob∈[0.24, 3.71]
- cap=1e-2 (overshoot): floor 1.13e-8, Pareto 312, BUT sob∈[−1.06, 9.56]
  and calo_max=1.44 — kernel unconstrained, picks 4–7 had sob<1 (broken)
- **cap=3e-2 (sweet spot, landed):** floor 5.47e-8, Pareto 169,
  sob∈[0.03, 4.67] (clean). Low-calo rows pull μ near the dy<0.23 basin
  without freeing the GP to extrapolate beyond training range.

**Step C (graph015 imputation, landed).** `gp_predict_helical.py`
`_fit_and_sample` imputes calo=0 rows as `0.5 × min(positive y_calo)` =
5.60e-8 before log-fit. Direct ROOT probe (`/tmp/probe_calo_bins.py`)
confirmed graph015's `TargetMuonFinder/stopmat` has 8 bins with **no**
calo crystal materials (vs helicalL02 16 bins with `CarbonFiber=1`).
Real physics zero — geometry absorbs all calo-bound muons (dy=307,
hl=185, ang=477 — full helical plug fills the muon path). The imputed
anchor seeds a new low-calo basin in the picker around dy≈300.

**Post-fix picker behavior** (8 picks from `gp_explore_picks.tsv`):
picks 0–1 sit in the established dy∈[112, 119] champion regime
(sob 2.4–3.8, calo 6.1e-7 to 1.94e-6); picks 2–7 cluster at dy∈[295, 326]
mirroring graph015's geometry, with calo dropping monotonically to
5.47e-8 (pick 7). The cloud now reaches the low-calo gold stars
visually — see `gp_predicted_helical_cloud_mpl.png` regen 2026-05-26.

**Step B (renderer, not landed).** PowerNorm(gamma=0.3) instead of LogNorm
+ scatter+alpha pass for `calo_pred ≤ P1`. Deferred: Step A alone closed
the gap; Step B is cosmetic polish.

**Heteroscedastic `alpha=1/N_jobs`** is still the "right" long-term fix
per `bo-helical.md:656-657`, but requires plumbing `n_jobs_harvested`
into leaderboard columns — significant effort for marginal gain.

### Frontier scope: background points can sit "beyond" the GP Pareto
The Pareto line in both PNGs (`gp_predicted_helical_cloud_mpl.png`,
`botorch_predicted_helical_cloud.png`) is computed **only over GP/BoTorch
posterior mean on the 4D helical space** (`cloud_plot.render_pareto` from
the Sobol prediction grid). mmackenz table.org background points are
real configs from *different topologies* — they can dominate the helical
frontier without violating optimality.

Concrete example (2026-05-27): the point at `(sob_rel≈0.48, calo≈1.07e-6)`
is **v111** — `config_v111: 2.50 cm Al plate with 80 mm hole, 4 mm × 170 mm
× 300 mm helical plug, 360 degree turn, 125 mm radius target with no hole`.
**Correction 2026-05-27 (later same day):** v111's no-hole target is NOT
the off-manifold knob — `HelicalMode.HOLE_RADIUS = 0.0`
(`bo_driver.py:380`) pins **every** v2 emit to
`stoppingTarget.holeRadius = 0.0000` with 38 foils @ 125 mm (verified on
`helicalFT06R00_00/geom/autoresearch_helicalFT06R00_00_geom.txt`). v111
lives on the same target manifold as the magenta v2 cloud.

**Root cause identified (2026-05-27, multi-agent investigation; supersedes
earlier same-day `tsda.rin` claim):** the dominant off-manifold knob is the
**helical solid implementation** — v111 was measured pre-2026-05-21 under
the broken tessellated `G4TessellatedSolid` (see
[tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md)). Stuck-track absorption at facet
self-intersections killed background before it reached the calo, biasing
v111's calo low by ~2×. v2 runs under the twisted-box dispatcher
(`tsda.helical.useTwistedBox = true` default since 2026-05-21).

**Quantitative match:** the helical041a A/B re-run documented in
[tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) shows the same knobs giving
**tessellated calo=2.97e-6** vs **twisted-box calo=6.49e-6** — a **2.2×
inflation** that matches the v111-to-v2 offset exactly. The tessellated
v111 underreports calo by the same multiplicative factor.

**`tsda.rin` hypothesis REFUTED:** earlier same-day claim that Option A
coupling was the dominant knob does not survive leaderboard data. Configs
that happen to render at rin=80 mm (small-dy region; rin formula =
`ceil(√(dx²+dy²)) + 2`) have **lower** median calo (3.62e-6) than the
rin>110 cluster (4.44e-6) — opposite direction from the hypothesis. The
FT06R00_00 reference (rin=115, dy=112) is at calo=1.04e-5, an order of
magnitude above the rin=80 cluster. Direction of rin → calo coupling in the
leaderboard is the inverse of what the "absorber annulus" story predicts.

| Knob | v111 | v2 emit | Effect |
|---|---|---|---|
| Helical solid impl | tessellated (pre-2026-05-21, nsteps=5000) | twisted-box (May-21 dispatcher) | **Dominant**: ~2.2× calo inflation when stuck-track absorption removed |
| `tsda.rin` | 80 mm (fixed) | Option A `ceil(√(dx²+dy²))+2` (range 43–367 mm; median 95 mm in leaderboard n=174) | **Refuted dominance** — leaderboard rin∈[80] subset has *lower* calo than rin>110 |
| `stoppingTarget.foilTarget_supportStructure` | default `true` | `false` (overlap-suppression) | Minor: <5% — W wires at r=125 mm outside forward muon path |
| `ds.lengthRail2/3` | default (4160/5500 mm) | 0.1 (overlap-suppression) | Minor: <2% — rails at z=4400+ mm catch only fastest escape muons |

**Action implication:** rin promotion is NOT recommended. rin is the only
defense against silent disc/plug sibling overlap
([tsda-disc-helical-sibling-overlap](/incidents/tsda-disc-helical-sibling-overlap.md)); promoting it back to a free knob
re-opens the failure surface that drove the leaderboard purge. Current top-3
champions live at rin∈[111, 149] — they'd fail an `rin=80` pin. Sequencing
remains task #147 (hl4) → #146 (COL5).

**Cheap rin-pin Sobol test (2026-05-27):** filtered the existing 8.4M-row
`gp_predictions_helical.tsv` to the rin≤80 mm subset (`dx²+dy² ≤ 78²`).
Feasible fraction = 884,215 / 8,388,608 = 10.5%. Predicted ceiling drops:

| | sob_max | Pareto n | calo_min on frontier |
|---|---|---|---|
| Unconstrained (Option A) | 4.075 (dy≈132, rin≈135) | 772 | 2.66e-7 |
| rin≤80 pin (v111 style)  | 3.013 (dy=77–78, rin=80) | 611 | 2.66e-7 |
| Δ                         | **−1.063 (−26%)**       |     | unchanged |

The high-sob ridge clusters at dy∈[125, 138] (rin∈[128, 141]); pinning
rin=80 forces dy≤78 and the rin=80 top-10 saturates exactly at the
boundary, confirming the constraint is binding not redundant. Low-calo
end is unaffected (basin already lives at small dy). Net: pin costs 26%
of predicted sob ceiling without buying any calo improvement → rin must
remain free under Option A coupling.
Source files: `bo_driver.py:380` (HOLE_RADIUS pin),
`:410-413` (derive_rin Option A formula),
`leaderboard_bo_helical_v2.tsv` (rin_derived col 7), `/tmp/rin_pin_sobol_test.py`
(the filter script used for this test).

**Companion overlay:** `overlay_gp_with_rin80_pin.py` (next to
`overlay_gp_predictions_helical_mpl.py`) renders the rin≤80 Pareto as a
red dashed line on the standard cloud → `gp_predicted_helical_cloud_rin80_overlay.png`.
Gotcha: must invoke with `/usr/bin/python3` or the `.venv-botorch` interpreter —
`.venv-graph` has sklearn but NOT matplotlib (per
[graph-runner](/drivers/graph-runner.md):78-82), so the cloud_plot import dies with
`ModuleNotFoundError: No module named 'matplotlib'`.

Implication: when reading the PNGs, **magenta v2 stars** and
**cyan-diamond picks** live strictly on the BO's 4D search manifold;
mmackenz class markers and the orange **prior stars** do not. Orange
priors come from `HelicalMode.load_priors()`
(`bo_driver.py:415`) — these are 10 mmackenz hand-designed
`config_v100`–`v109`, `v111` configs scraped from
`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/config_v###/run1b_beam/geom.txt`.
Their `(dx, dy, halflength, angle)` values are in-domain, but the rest of
their geometry (target topology, COL5 material, foils) is NOT controlled
by the 4D BO — so v111 (the only prior with no-hole target, sob≈2.12,
calo≈1.62e-6) sits "beyond" the GP Pareto by the same mechanism as the
table.org background. "Beating the Pareto line" by any orange star is
**not** a GP failure mode and **not** a bad geometry — it's a ceiling
indicator hinting which off-axis knob to promote next.

### Mitigation options (not yet implemented)
- Add scatter+alpha layer for predicted points with `sob > P95` to make
  the tail visible alongside the density
- Plot calo-at-sob percentile bands (5th, 50th, 95th of predicted calo per
  sob bin) instead of pure density
- Apply the −0.80 log-calo bias correction to GP predictions before
  rendering (caveat: invalidates uncertainty quantification)

### Shared x-axis chokepoint (2026-05-30)
`cloud_plot.py:192` `ax.set_xlim(0, 1.4)` is the **single line** controlling
the x-limit on BOTH the static (`gp_predict_foils_cloud.py`) and animated
(`gp_predict_foils_cloud_anim.py`) renders, plus the helical equivalents
(`overlay_gp_predictions_helical_mpl.py`, `botorch_predict_helical.py`). All
four scripts import `cloud_plot.finalize(...)`, which calls `ax.set_xlim`.
Was 1.15 until 2026-05-30; widened to 1.4 so the GP-predicted Pareto frontier
stops railing the right edge of the foils cloud.

### Density-bin range chokepoint (2026-06-06) — `xlim` widening was a HALF-FIX
`cloud_plot.py:115-116` `render_density` calls
`np.histogram2d(..., range=[[0, 1.15], [-8, -4]])` — the binning range is
**still hardcoded to 1.15** even though `set_xlim` is 1.4. Consequence: any
Sobol prediction (and any obs-star) with `sob/x_scale > 1.15` is **dropped
from the density histogram entirely** and renders as empty cloud, while the
star itself still plots on the axes. With `x_scale = 3.3` (Nominal Run 1A
sob from table.org), that's `sob > 3.795` raw. On the v3 foilsf01 cloud
(2026-06-06), **5 of 117 v3 stars** sit past x=1.15 (e.g. `foilsZ02R07_02`,
sob=3.87) and read as "GP doesn't envelope my dot" — but it's a binning
artifact, not a GP failure. **Fix landed 2026-06-06:** `cloud_plot.py:116`
density-bin x-range bumped `1.15 → 1.4` to match `set_xlim`. Rule for
future bumps: `set_xlim` on `cloud_plot.py:192` and the `histogram2d`
`range[0]` on `:116` are TWO separate constants — bump them together.

**CORRECTION 2026-06-06:** the bin-range bump above was a **red herring
for the foils v3-only cloud** — direct measurement showed all 117 v3 obs
already lived inside `sob/x_scale ∈ [0.177, 1.173]`, well within the
original `[0, 1.15]` (just 1 star at 1.173 grazed the edge). The bump is
still correct (the GP-Pareto frontier can rail past 1.15), but it did NOT
explain the visible "cloud doesn't cover my dot" complaint. The REAL
mechanism for the foils v3 cloud is the same noise-rail under-prediction
documented for helical above:

- GP predicted calo min on the v3-only fit = **9.05e-7**
- **4 v3 obs sit below that:** `foilsZ03R00_03` (calo=8.95e-7),
  `foilsf01R02_06` (7.40e-7), `foilsf01R03_04` (8.95e-7),
  `foilsf01R03_09` (8.09e-7) — real low-calo wins the GP can't predict
- 1 v3 obs sits above GP sob max: `foilsZ02R07_02` (sob=3.870 vs GP
  max 3.832), barely outside

**WhiteKernel-rail hypothesis REFUTED 2026-06-06 (agentic probe).**
Direct sweep on the n=117 v3-only fit: noise upper bound `1e-1`, `3e-2`,
`1e-3` all converge to **fitted WhiteKernel noise_level = 1.09e-3** —
non-binding, the 3e-2 cap is **not** absorbing low-calo scatter. Lowering
the cap does NOT change the calo floor (9.05e-7 in all three variants).
Fitted Matern length_scales `[2.87, 3.21, 0.62, 1.78, 1000, 1000]` —
only dims 4+5 (extra_f_up/dn) rail at 1000, confirming the
fractional-hole-specific under-identification noted in the Updated header.

**Real mechanism — Sobol sampling box mismatch.** The renderer samples
`[0,1]^6` of the **v2 BOUNDS box** (`foils_v2_loader.py:34-41` defines
`extra_rIn_up/dn ∈ [0, 50]` mm), but the v3 outliers have downstream
`rIn = f × rOut = 0.95 × 250 = 237.5` mm — normalized to **4.04**, way
outside the sampling box. The 65536 Sobol draws **never visit** the
outliers' coordinates, so the cloud cannot represent them by construction.
Forward-LOO on the 4 low-calo configs predicts them within **8-11%** —
the GP *knows* about them, but only when they're in the training set.

**Fix landed (2026-06-06):** widened `foils_v2_loader.BOUNDS[4,5]` from
`[0, 50]` to `[0, 240]` mm so Sobol covers the full picker-reachable
region (`f_max × rOut_max = 0.95 × 250 = 237.5`). Critical clarification:
`foils_v2_loader.BOUNDS` is a **diagnostic-only GP-normalization frame**
used by 5 cloud renderers in `mmackenz_table_plots/`, NOT the picker's
search box. The picker is `bo_driver.py:FoilsFracMode`
(line 800-832) which defines its own `build_space()` with `f ∈ [0, 0.95]`
and `rOut ∈ [50, 250]` — does not import `foils_v2_loader`. So BOUNDS
can be reshaped freely for diagnostic coverage without touching what the
optimizer actually searches.

**Option A overlay (2026-06-06):** `cloud_plot.py:render_density` now
plots GP-predicted points with `calo ≤ p5` (5th percentile of cloud calo)
as faint purple scatter (s=2, alpha=0.15) under the LogNorm density.
Surfaces the low-calo tail that LogNorm `vmin=1` renders identical to
empty bins. Independent of the BOUNDS fix.

## Slide-4 "regression" — framing change, not data (2026-06-06)
User's "we never had this issue before" is correct, but the cause is the
**training set**, not contamination:
- `docs/gp_predicted_foilsY_cloud.png` before commit `379f56a` (2026-06-04)
  was a v2-only GP density (n=30, foilsY03 era) with v3 stars overlaid on
  top — stars were *extrapolations into untrained space* and visually
  "looked fine" because the v2 cloud was tight and stars were "extras."
- Switch to v3-only training on 2026-06-04 (and again on 2026-06-06 with
  v1+v2 priors retired in `FoilsFracMode.load_priors → []`) is the FIRST
  time the GP is asked to fit v3 data. The 4 low-calo outliers always
  existed in v3; they're just visible as failures now.
- v2+v3 joint fit doesn't rescue coverage: predicted `calo_min=8.85e-7`
  vs v3-only `9.06e-7`, both well above the outliers (7.4-9.0e-7). v2
  priors never sampled the corner.

## foilsf01 corner-clustering (2026-06-06)
qLogNEHVI in the foilsf01 round (R00-R04, n=50) heavily over-sampled the
(rOut_up=250, hT_up=1.0, f_up=0.0) corner — thick, maxed-radius, **solid**
upstream extras:
- `rOut_up=250`: 24/50 (48%) of foilsf01 evals
- `hT_up=1.0`:   14/50 (28%)
- `f_up=0.0`:    26/50 (52%)
- triple-corner: **7/50 (14%)** of foilsf01 vs **2/67 (3%)** of earlier foilsZ
- All 4 cloud-escaping outliers are foilsf01 evals at exactly this triple

**Physics — why the corner has low calo:** thick solid upstream disc
**blocks the muon beam**. Outliers' `ce_seen=76k-96k` vs reference
`235k` (~3× lower); `stopping_factor=0.158` vs `0.119` (muons that get
through stop in the dense upstream extras). This is real Pareto-relevant
signal that qLogNEHVI correctly identified — NOT noise, NOT contamination,
NOT a harvest bug. Confirmed via two-agent audit 2026-06-06 (full
schema/provenance/base-geometry checks all pass).

## Forward-LOO confirms: GP DOES predict the outliers (2026-06-06)
Per-outlier in-training and leave-one-out predictions on the v3-only n=117 fit:

| config | calo_obs | in-train pred | ratio | LOO pred | ratio |
|---|---|---|---|---|---|
| foilsZ03R00_03 | 8.95e-7 | 8.91e-7 | 1.00 | 8.83e-7 | 0.99 |
| foilsf01R02_06 | 7.40e-7 | 7.82e-7 | 1.06 | 8.22e-7 | 1.11 |
| foilsf01R03_04 | 8.95e-7 | 9.11e-7 | 1.02 | 9.67e-7 | 1.08 |
| foilsf01R03_09 | 8.09e-7 | 7.83e-7 | 0.97 | 7.57e-7 | 0.94 |

Sob predictions agree to within 1.5% on the same configs. **The GP fits
these points to within ~10% even when hidden** — the other 6 corner siblings
provide enough nearby support. This matches the ~8% calorimeter Poisson noise.

**Implication:** the picker (qLogNEHVI reading the same GP) was correctly
exploiting the corner — 7/50 of foilsf01 evals at the triple-corner is
*deliberate* exploitation of a posterior the GP has identified. The slide-4
"stars outside the cloud" complaint is a **pure Sobol-density rendering
artifact**: the corner is ~6% of the 6D volume so random Sobol scatters thinly
through it, and LogNorm vmin=1 hides bins with <1 hit. The model is not
under-predicting; the random grid just doesn't ask the GP about that corner
often enough to register on the density. Right fix is **stratified Sobol
densification** in the picker-exploited region, not retraining or more data.

## Sobol-cloud floor sweep — kernel knobs do not move it
Earlier (before forward-LOO above), I swept kernel knobs to try to lower the
Sobol-predicted calo_min (the cloud "envelope"):
- Matern `length_scale_bounds` 1e3 → 1e4: calo_min unchanged (9.06e-7)
- Drop dims 4-5 (extra_f_up/dn) from kernel (4D fit): 8.89e-7
- WhiteKernel `noise_level_bounds` cap 3e-2 → 1e-6: 8.40e-7

**Reading those results correctly:** these are the *minima of 65k random
Sobol predictions*, NOT the GP posterior at the outlier coords. The forward-
LOO table above shows the GP DOES predict the outliers to within 1-11% when
asked at their actual coordinates. The Sobol-min floor is high because the
corner is ~6% of the 6D volume — Sobol scatters thinly through it, the GP
correctly returns higher calo at the random Sobol points that miss the
corner. Both observations are simultaneously true.

**Harvest sanity (parallel agent probe, 2026-06-06).** All 4 outliers
healthy: `stopping_factor≈0.158`, `ce_simulated_events≈465k-497k`,
`calo_files_seen=183-200`, `calo_total=53-70` (low but nonzero — not
graph015 calo=0, not [calo-constant-across-helical](/incidents/calo-constant-across-helical.md) bit-identical, not
[stage-out-rename-race](/incidents/stage-out-rename-race.md) partial). Genuine geometry sweet spots — all 4
share signature `rOut_up=250, rOut_dn=250, hT_up=1.0, f_up=0.0` (thick
maxed-radius upstream foils, zero up-extras, varying downstream). Basin
contains ~5 of 117 leaderboard rows; nearest neighbors at L2≥0.26 have
calo 1.1e-6 → 1.4e-6 (smooth tail to gap at 8.95e-7 → 1.05e-6).
**No re-runs needed.**

**Real fix:** widen the v3-only sampling box to v3-derived bounds (max
observed `rIn_up/dn` instead of v2's 50 mm cap). Cosmetic alternatives
(scatter overlay, PowerNorm) cannot rescue points the Sobol grid never
visits. PowerNorm `gamma=0.3` (1-line swap at `cloud_plot.py:119`)
widens visible tails for the *high-sob* star (sob=3.87, GP-predicted-3.83)
but is useless for the 4 low-calo outliers.

### Foils cloud PNG file-map (2026-06-04) — which script writes which deck image
(Slide numbers below refer to the PRE-SPLIT 26-slide deck, archived same-day
to `docs/foils_talk_full.md` when the concise 8-slide `docs/foils_talk.md`
split off — see [refresh-foils-slides](/drivers/refresh-foils-slides.md).)
That pre-split deck embeds TWO near-identical-looking foils clouds
from confusingly-named files; disambiguated by reading each PNG's embedded
title:
- **slide 11** `gp_predicted_foils_cloud.png` — written by
  `gp_predict_foils_cloud.py`; **cron-refreshed** (`refresh_foils_slides.sh`
  copies plots-dir → `docs/`). Despite the v1-stamped highlights caption
  ("251 evals"), the *image* is the **v2 6D** render (title: "trained on N
  v1(6/6)+v2 evals").
- **slide 21** `gp_predicted_foilsY_cloud.png` — **NO script writes this name**;
  it is a **manual `cp`** of a cloud render. The refresh cron does NOT touch it,
  so it must be updated by hand.
- **Folding v3 (foilsf) into the 6D cloud (2026-06-04):** `foils_v2_loader.py`
  gained `_load_v3()` (reads `leaderboard_bo_foils_v3.tsv`, converts
  `f→rIn = f·rOut`, lossless) + an **opt-in `include_v3=False`** param —
  default OFF so the v2 picker (`gp_predict_foils.py`) training set is
  unchanged. Render via the separate `gp_predict_foils_v2v3_cloud.py` (writes
  its OWN `gp_predicted_foils_v2v3_cloud.png`) so slide 11 + the cron stay
  untouched; then `cp` that onto `docs/gp_predicted_foilsY_cloud.png`. v3 holes
  (`f` up to 0.95) **exceed the v2 `rIn≤50` BOUNDS**, so v3 rows normalize >1 on
  the rIn dims and plot as stars OUTSIDE the Sobol cloud (the cloud samples only
  the v2 box) — intended, shows where v3 reached beyond the envelope.

## Cross-links
- Related: [bfield-at-helical-plug](/concepts/bfield-at-helical-plug.md), [bo-helical](/projects/bo-helical.md), [batch-bo](/concepts/batch-bo.md), [refresh-foils-slides](/drivers/refresh-foils-slides.md), [bo-foils](/projects/bo-foils.md), [bo-noise-budget](/concepts/bo-noise-budget.md), [botorch-tiny-output-log-training](/concepts/botorch-tiny-output-log-training.md), [pareto-sob-picker](/concepts/pareto-sob-picker.md)
- Source files: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/overlay_gp_predictions_helical_mpl.py`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/cloud_plot.py`,
  `/tmp/residuals_over_iter.py`
- Data: `gp_predictions_helical.tsv` (8.4M Sobol), `leaderboard_bo_helical_v2.tsv`

## Downstream consequence: picker collapse
The same −0.80 log-calo bias that hides champions in the cloud also
*biases the picker*. `compute_explore_picks` does Pareto-of-mean on the
GP posterior; if GP overstates calo by 2.3× in the L02-type basin, that
basin appears to violate the 2e−6 feasibility cap and gets skipped.
This is the mechanistic explanation for the empirical observation that
explore picks collapse into `dx∈[1.9, 2.4], dy∈[81, 110]` instead of
finding regions near the actual top-3 (`bo-helical` smoke A/B, see
`/tmp/picker_smoke_ab.py`). The pessimistic-calo plan
(`~/.claude/plans/zazzy-booping-ladybug.md`) only patches the *fallback*
prior for unobserved regions — it does NOT fix the fitted-bias on
in-distribution observations, so the picker keeps mis-ranking even
under that flag.

## Impl-tracing rule (2026-05-27): geom-file grep is NOT a reliable impl tracer
Grep for `useTwistedBox` in `<grid>/<config>/geom/autoresearch_<config>_geom.txt`
ONLY works for configs whose geom was emitted on/after **2026-05-26** when both
the C++ dispatcher and the Python FCL-emission line landed (tasks #134–136;
source mtimes `autoresearch_muse/.../constructTSdA.cc` 2026-05-26 10:46,
lib 10:51, tarball 10:56; `bo_driver.py:377` HELICAL_USE_TWISTED_BOX
env-gated, `:490-491` emits the FCL key). Pre-2026-05-26 geom files lack the
key entirely — the impl actually used at runtime is whatever
`Code_helical_base.tar.bz2` shipped to the worker.

### Deployed `Code_helical_base.tar.bz2` timeline (verified via .snap audit)
Daily NetApp snapshots of `/exp/mu2e/app/users/oksuzian/autoresearch_muse/.snap/`
preserve the actually-shipped tarball state at end-of-day. Tarball size +
mtime tracks impl:

| Snap | size | mtime | inferred impl |
|---|---:|---|---|
| ≤ 2026-05-21 | 56,081,079 | May 17 11:19 | tessellated (broken) — matches `.bak-2026-05-17-broken` exactly |
| 2026-05-22 → 2026-05-26 | **56,081,079** | May 21 00:29 | **still tessellated** (same size as broken-bak; the `.patched-twistedbox` sidecar was 59,813,044 bytes — clearly NOT what was deployed) |
| ≥ 2026-05-27 | 59,825,830 | May 26 10:56 | dispatcher tarball |

The `.patched-twistedbox` sidecar (59.8 MB, built 2026-05-20 23:19) was a
ready-to-ship build of the stacked-G4TwistedBox lib that **was not actually
deployed** until the 2026-05-26 dispatcher repackage. Consistent with
[tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) Key facts line 193-198:
*"The production Code_helical_base.tar.bz2 is the OLD tessellated lib
(swapped in for the helical050a_n5000 test on 2026-05-21, not yet swapped
back)"* and the defensive HELICAL_NSTEPS 100 → 5000 → 2000 flips were
nsteps bumps under the broken lib, not a flip to a clean lib.

### Corrected impl per geom-emit-date

| Geom emit date | Deployed lib | Actual impl |
|---|---|---|
| ≤ 2026-05-20 | tessellated (broken), `nsteps=100` | **tessellated**, all configs floored on GeomSolids1001 |
| 2026-05-21 → 2026-05-25 | tessellated (broken), `nsteps=5000` then `nsteps=2000` defensive | **tessellated under N_crit gate**; scan_logs blocks rows where N_crit > nsteps from leaderboard |
| ≥ 2026-05-26 | dispatcher tarball (default `useTwistedBox = true`) | per FCL key, default twisted-box |

**Confirmed via direct inspection (2026-05-27):** FT01–FT07, SR01/02, QR00,
PC01–03, F01, NG/CB/P, helical050a_n5000, graph015 geom files all **lack
the `useTwistedBox` key** because the FCL emitter didn't land until 2026-05-26.
Only FT08R00_00 (geom mtime 2026-05-26 17:20) onward carries the key.

### `leaderboard_bo_helical_v2.tsv` impl mixture (175 rows) — CORRECTED
- **Pre-2026-05-21 broken-tessellated rows:** ~10 (`graph*`, `helical050a_n`,
  `helicalH01`); mostly retro-scan flagged → `.broken.tsv` sidecar (#150–151).
- **2026-05-21 → 2026-05-26 tessellated-under-N_crit-gate rows:** ~120
  (FT01–FT07, SR/QR/PC/F01/NG/CB/P cohorts). These were run under the SAME
  broken tessellated lib, but the scan_logs gate + nsteps=5000→2000 ceiling
  was supposed to reject configs whose N_crit exceeded the nsteps budget.
  scan_logs imperfections (per [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md) and the
  retro-scan flip in tasks #143-144) mean some are still tainted at lower
  severity than the pre-May-21 cohort.
- **Post-2026-05-26 dispatcher-era rows:** ~12 (FT08, TWB A/B pairs) —
  explicit per-row tracer via `useTwistedBox` key; the only era with
  guaranteed-clean twisted-box.
- **mmackenz priors** ([mmackenz-priors](/datasets/mmackenz-priors.md) — 10 rows `v100`–`v109`, `v111` via
  `HelicalMode.load_priors()` at `bo_driver.py:415`) are
  tessellated-era. The v111 "beyond Pareto" anomaly is the tessellated-vs-
  twisted-box 2.2× calo offset documented in
  [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md), not an off-manifold geometry.

**GP training-set implication:** the dominant ~130/175 rows are tessellated
(broken-lib regime, modulated by N_crit gating after 2026-05-21). The
twisted-box regime is the small minority (~12 dispatcher-era rows). GP cloud
predicted calo therefore reflects mostly the tessellated regime; v111
"sitting below the Pareto" is consistent with v111 being in that same
regime, not below it. Cross-era twisted-box rows (FT08, TWB) read ~2.2×
higher calo per [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) TWB01 A/B and
helical041a tess-vs-twist measurement.

**Operational consequence:** for any cross-era leaderboard comparison,
infer impl from the geom-emit *date* (against the 2026-05-21 / 2026-05-26
cuts above), not from the `useTwistedBox` key. Treat pre-2026-05-26 rows
as tessellated under varying N_crit gates; treat post-2026-05-26 rows as
twisted-box per FCL key.

## v111 anomaly status (2026-05-27): ruled-out chain, still unexplained
After correcting the lib-deployment timeline (`.snap` audit showed deployed
`Code_helical_base.tar.bz2` was tessellated through 2026-05-26, not
twisted-box), v111 sits in the same tessellated regime as ~130/175 v2
leaderboard rows, so impl-mismatch cannot be the 6× calo gap. Cumulative
ruled-out list (in order of elimination, with refuting evidence):

| Hypothesis | Status | Why ruled out |
|---|---|---|
| `tsda.rin` Option A coupling (rin=80 forced pin) | **Refuted** | rin=80 leaderboard subset has *lower* median calo (3.62e-6) than rin>110 cluster (4.44e-6); cheap Sobol rin-pin test costs 26% sob but doesn't move calo floor |
| Target hole topology (v111 no-hole vs v2 default) | **Ruled out** | `HelicalMode.HOLE_RADIUS = 0.0` at `bo_driver.py:380` pins every v2 emit to 0 (verified on FT06R00_00/geom) |
| Broken-tessellated stuck-track absorption (helical041a-style 2.2×) | **Ruled out** | v111 N_crit ≈ 33 (dx=4, dy=170, hl=300, angle=360) is far below nsteps=2000 budget → no GeomSolids1001, no stuck-track flood. Wrong regime. |
| Clean-tess kCarTolerance halo bias (TWB01-03 mechanism) | **Wrong sign + too small** | Tess clean A/B shows tess +1-12% *higher* calo than twist (TWB01: 6.55e-6 vs 6.49e-6). v111 is tess; if the bias applied, v111 would be slightly *over*-reported, not 6× under-reported. Direction inverted from what would explain v111. |

**Remaining live candidates** (next investigation steps when this priority resurfaces):
1. **Non-4D knobs**: v111 spec has degrader=2.5 cm Al plate (vs v2 default), COL5 material categorical (task #146 still pending promotion), `stoppingTarget.foilTarget_supportStructure` true (v2 forces false for overlap suppression), `ds.lengthRail2/3` default (v2 forces 0.1). Per-knob effect in earlier section ranked <5% individually but **never measured in combination at v111's knob set**.
2. **Cross-pipeline metric incompatibility**: v111's sob/calo come from mmackenz's `table.org`, not our v2 grid harvest. Different stage chain, different physics list, different denominators, different event counts. Numbers may not be cross-comparable.

**Cheapest discriminator next:** rerun v111's exact knob set through our v2
pipeline (current dispatcher tarball, `useTwistedBox=true`, force the 4D + degrader thickness + COL5 + target topology to v111 values). If calo lands at v111's ~1e-6, gap is a real non-4D-knob effect → promote degrader (or COL5) to BO knob. If calo lands at cloud ~6e-6, gap is cross-pipeline metric incompatibility → v111 is not actually a champion under our methodology and the orange star should be re-labeled.

**v111repro A/B result (2026-05-28):** `v111repro_twist` at v111's 4D point
(dx=2, dy=85, hl=150, ang=360) landed **sob=1.53, calo=2.09e-6, obj=1.321**
on the v2 pipeline (twisted-box, current dispatcher tarball, only the 4D
knobs forced to v111 values — degrader/COL5/topology left at HelicalMode
defaults). v111's mmackenz `table.org` spec is sob=2.12, calo=1.62e-6.
Twist landed near the GP cloud mean (sob~1.5-2.0, calo~3-6e-6) rather
than near v111's spec.
Implications:
- **Cross-pipeline metric incompatibility is the dominant hypothesis.**
  Even keeping degrader/COL5/topology at v2 defaults (which v111 spec
  varies), the v2-grid harvest reproduces the cloud envelope, not v111's
  ~1e-6 calo. Most of the 6× gap appears to come from pipeline
  differences (event counts, denominators, physics list, mu_beam stage
  chain), not from a missing geometry knob.
- **Orange-star "v111 = champion" claim is suspect under our methodology.**
  When recomputed under v2 grid harvest at the same 4D knobs, v111
  becomes a midpack point.
- **Non-4D knobs cannot be fully ruled out yet** — the v111repro_twist
  chain only forced the 4D, not the degrader/COL5/topology. To close that
  loop, a follow-up "v111repro_full" with all v111 non-4D knobs pinned
  would be needed; deprioritized because the dominant gap already closed
  to 2-3× with just the 4D match.
- **Tess A/B half closed:** `v111repro_tess` landed sob=1.55, calo=2.33e-6,
  obj=1.317. Tess +11% calo over twist (within TWB01-03 1-12% halo,
  direction matches); sob statistically identical. Both fall on cloud
  envelope; neither approaches v111 spec. Conclusion firm:
  cross-pipeline metric incompatibility, not tess/twist.

## Open questions / TODO
- **Predictive-spread cloud (candidate render to envelope μ-extreme stars, 2026-06-17).**
  Both the density (slide 6) and acq-heatmap (slide 7) clouds place every pixel
  at the SAME (μ,dose) = pushforward of Sobol through the GP posterior **mean**;
  recoloring (density→acq) changes pixel COLOR, never pixel POSITION, so the
  cloud's spatial *extent* is identical on both. The champion `pt6d07R01_07`
  (obs μ=2.493e-3) is right of the rightmost column on BOTH because max
  mean-prediction μ=2.384e-3 < 2.493e-3 — outside by construction, unfixable by
  recoloring. The ONLY render that extends the extent to cover it is a
  **predictive pushforward**: draw `y ~ N(GP_mean, σ²_pred + noise)` per Sobol
  point instead of plotting the mean. Its μ-edge then reflects predictive spread
  (champion forward-LOO z≈2–3 ⇒ within the band). Trade-off: blurrier, less
  "where the picker thinks the optimum is." Not yet built.
- Implement scatter-tail overlay so champions are visible without needing
  a separate gold-star pass.
- Refit GP on log(calo) with target-rebalanced training weight on the
  high-sob slice; check if the late-half bias collapses.
- Decide whether to report calo-bias-corrected predictions in the
  closed-loop picker (`compute_explore_picks`) — currently it uses raw
  GP mean and so inherits the same optimistic bias for unobserved
  high-sob regions.
- Diagnostic to run before refit: residual-vs-dim + residual-vs-magnitude
  on current leaderboard to isolate which of {heteroscedastic noise,
  kernel over-smoothing, target transform, train-distribution shift} is
  driving the −0.80 late-half log-bias.
