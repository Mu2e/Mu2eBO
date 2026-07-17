---
# bo-prodtarget — profile-mode BO over Stickman PS production target

**Type:** project
**Status:** active (ptX01–ptX04 shipped; ptX05 launched 2026-06-10 with lug-overhang cap)
**Updated:** 2026-06-23 (champion significance + GP-underfit analysis added)

## Summary
Proposed BO line over the **production target** (MDC2025aq Stickman v1.0,
[[production-target-stickman]]), focused on the four thermal-coupled
geometric knobs `{rOut, plateThickness, numberOfPlates, plateLugThickness}`
(NOT `spacerHalfLength` — confirmed dead-on-arrival in
[[production-target-stickman]] z-march).

Per-plate parameterization (35×4 = 140-D) is too large for BO; this design
uses **profile-mode parameterization**: each per-plate quantity is a smooth
`f(u)` in normalized plate index `u = i/(N-1)`, defined by K=3 control points
at `u ∈ {0, 0.5, 1}` interpolated through a Lagrange quadratic. Total
search dim ≈ 11D (10 continuous + 1 int).

Pure config change — no source code modifications needed
(`ProductionTargetMaker.cc` already reads all four knobs as length-N vectors;
see [[production-target-stickman]] for file:line refs).

## Key facts

### Lug dims are effectively redundant (2026-06-10)

`l0/l1/l2` are nominally `Real(4.0, 12.0)` but `_expand` post-clips each
plate to `lPlate[i] ∈ [tPlate[i]+0.5, tPlate[i]+1.0]` — a 0.5 mm window
fully determined by the thickness profile. The picker still proposes
over [4,12]; we just snap. Net: the three lug knobs carry near-zero
independent information. The lug is a structural annular ring
(rIn=1.525, rOut=3.0 mm) outside the plate core — beam hits the core,
not the lug, so lug magnitude doesn't move mu_per_POT meaningfully.
Candidate ptX06 simplification: drop l0/l1/l2 from BO (10D→7D), keep
the `tPlate+0.75` mid-window snap as a deterministic post-projection.
Would also implicitly eliminate the lug-overhang failure class.

### pt6d01 cold-start gotcha (2026-06-10)

`prodtarget6d` mode uses a fresh leaderboard
(`leaderboard_bo_prodtarget6d_v0.tsv`) with a different schema (6 knob
columns vs 10) than the 10D `prodtarget` leaderboard — they are NOT
cross-loadable via `load_history` (column set differs). First launch of
pt6d01 with `--picker qnehvi` crashed at `node_predict_picks` with
`[botorch_predict] empty history for mode=prodtarget6d`
(botorch_predict.py:138-143 hard-fails when `load_priors() +
load_history()` is empty).

**False-friend fix (don't):** `--picker cl_min` does NOT save you —
`_import_gp` at `graph/closed_loop.py:165-174` only registers
gp_predict shims for `helical/foils/foilsf/foilsg`. Neither
`prodtarget` nor `prodtarget6d` has one (the 10D mode worked with
qnehvi only because its leaderboard already had 19 rows from
pt001/pt002 propose+evaluate seeding). cl_min crashes with
`ValueError: _import_gp: no GP picker registered for mode=
'prodtarget6d'`.

### pt6d01 barrier-timeout outcome (2026-06-10)

pt6d01 (q=10 max-rounds=2 qnehvi) launched 08:03, parent died at
12:18 (~4h15m) on **barrier timeout** at R0 ("barrier[r0]: timeout
after 240min; 10 children still pending"), then `decide_next` saw
`before=0 after=0` and exited early. 2 rows landed in the leaderboard
AFTER the parent exited (`pt6d01R00_00` sob=2.268e-3,
`pt6d01R00_03` sob=2.254e-3); 8 children continued as **orphans**
with no R1 to consume their results.

**Root cause:** `CLOSED_LOOP_BARRIER_TIMEOUT_MIN=240` (4h) in
`graph/config.py:133` is too short for `prodtarget*` modes. The
`pot_only` stage with N=35 plates × ~100 jobs runs ~3.5-4h end-to-end
(observed: cluster 28086133 R-state for 3h27m at parent kill, jobs
still finishing). The first 2 children that crossed the finish line
made it under the wire; the other 8 didn't.

**Compounding bug:** `decide_next` sampled `history_len_before/after`
at barrier-exit time, NOT including in-flight writes. The 2 rows that
DID arrive came in seconds-to-minutes AFTER the parent's snapshot,
so `decide_next` saw `0 new` and triggered the early-exit path.
Same pattern as the [[closed-loop-final-round-orphan-children]]
incident but on R0 instead of final round.

**Mitigations (for pt6d02 relaunch):**
- `--barrier-timeout-min 360` (or 480) — give `pot_only` enough wall
- 8 R0 orphans will keep writing rows until they finish; relaunching
  with same `--name-prefix pt6d01` would hit
  [[closed-loop-stale-cluster-silent-no-launch]] (state/*_cluster.txt
  lingers → `_already_running()` returns true). Use a new prefix
  (`pt6d02`) or wait + rm the stale state files.
Sobol cold-start path. `_load_history_tensor` returns empty
`X` (shape `(0, d)`) when `priors + history` is empty (instead of
SystemExit). `compute_explore_picks` guards `if X.shape[0] < 2`:
draws `q` Sobol picks from `MODE_SPECS[mode]` bounds via
`botorch.utils.sampling.draw_sobol_samples` with seed `42 ^ round_idx`
(matches qnehvi seed contract — see
[[botorch-predict-seed-pow-vs-xor]]). `_emit_picks` int_dim cast
applies, so integer dims (e.g. `N` for prodtarget 10D) round
correctly. The `< 2` threshold is set by SingleTaskGP's Cholesky fit
needing ≥2 points to avoid a degenerate posterior.

Net: any **new** mode added to `MODE_SPECS` works cold on first
launch with no `load_priors` override, no propose+evaluate seeding,
no projection from sibling leaderboards. The lossy 10D→6D projection
attempted earlier (filter t-knot ≤ 7.0 → 7 of 19 rows survive) was
reverted — `ProdTarget6DMode.load_priors` is back to the inherited
`return []`.

### pt6d02 R0 first-batch dominator (2026-06-12)

`pt6d02` (q=10 max-rounds=2 qNEHVI, warm-started on 10 pt6d01 Sobol
rows) launched 2026-06-11, R0 barrier resolved next morning.
**`pt6d02R00_06` landed μ=2.320×10⁻³ / dose=1.300×10⁻⁹ Gy/POT** —
a Stickman dominator (+7.1% μ, −14% dose) in the very **first**
qNEHVI batch. The matching 10D dominator `ptX05R02_07`
(2.313×10⁻³ / 1.387×10⁻⁹) took 3 full rounds (q=10) to find.

**Implication:** for thermal-coupled optimization, fixing `N=35` +
deriving `lug = tPlate + 0.75` (the 6D restriction) does not cost
Pareto coverage near the knee — it converges faster per CPU-hour.
Lug-profile + plate-count axes in the 10D variant were largely
exploration noise around Stickman's natural sweet spot at `N≈35`.

**Caveat:** 6D's t-upper is capped at 7.0 mm (vs 10D's 8.0 mm) to
dodge the spacer-overlap regime; the dose-favorable corner
(`ptX01R00_00` at 8.0×10⁻¹⁰ Gy/POT, t=very low) is still reachable
in 6D since its t-lower is 3.0 mm.

### pt6d03 R0+R1: dose-frontier extension (2026-06-12)

`pt6d03` (q=10 max-rounds=2 qNEHVI, warm-started on the 20-row
pt6d01+pt6d02 history) cleanly completed both rounds the same day,
adding 20 evals (campaign total: 50). Five more Stickman dominators
beyond pt6d02R00_06:

| config | μ [10⁻³] | dose [10⁻⁹ Gy/POT] | vs Stickman |
|---|---|---|---|
| pt6d03R00_03 | 2.184 | 1.171 | +0.8% μ / −23% dose |
| **pt6d03R00_08** | **2.193** | **0.993** | **+1.2% μ / −35% dose (best dose-dominator)** |
| pt6d03R01_00 | 2.178 | 1.455 | +0.6% μ / −4% dose |
| pt6d03R01_03 | 2.298 | 1.510 | +6.1% μ / −0.7% dose |
| pt6d03R01_08 | 2.259 | 1.494 | +4.3% μ / −1.7% dose |

**`pt6d03R00_08` is the first 6D row to break below 1.0×10⁻⁹ Gy/POT**
while still beating Stickman μ; previous low was pt6d02R00_06 at
1.301×10⁻⁹. Best-μ dominator unchanged (`pt6d02R00_06` at 2.320e-3).
qNEHVI's R1 picks are saturating the t-cap (5 of 10 at t=7.000) —
consistent with my pre-launch read that pt6d03 would be a t-cap
exploration round without a bounds expansion.

### pt6d04 → pt6d06: μ-axis push, ceiling at 2.39e-3 (2026-06-13 → 2026-06-15)

After pt6d03 saturated the dose-frontier, pt6d04/pt6d05/pt6d06 ran
sequentially. Net result over 46 qNEHVI evals: **μ ceiling holds at
2.39×10⁻³** — no new champion in the last 19 evals despite 16/19 picks
at the t1=7.000 cap.

| campaign | evals | best new μ | t1=7.000 picks | notes |
|---|---|---|---|---|
| pt6d04 R0 | 10/10 | `pt6d04R00_00` 2.376e-3 / 1.89e-9 | 10/10 | clean |
| pt6d04 R1 | 0/10 | (n/a) | n/a | 10/10 `fail_managed` from [[preflight-mode-tuple-prodtarget6d-omission]]; fixed |
| pt6d05 R0 | 10/10 | `pt6d05R00_07` 2.364e-3 / 2.12e-9 | 10/10 | clean |
| pt6d05 R1 | 6/10 | **`pt6d05R01_05` 2.390e-3 / 2.38e-9** | 8/10 | 7/10 orphaned by rc=120 ([[pipeline-poll-rc120-atexit-death]]), manually harvested 6/7; 3/10 real spacer↔plate-00 |
| pt6d06 R0 | 9/10 | `pt6d06R00_02` 2.340e-3 / 2.31e-9 | 8/9 | 1 preflight-fail (real spacer↔plate-00) |
| pt6d06 R1 | 10/10 | `pt6d06R01_03` 2.293e-3 / 2.61e-9 | 8/10 | clean — first end-to-end success after rc=120 mitigations |

**Verdict:** 6D is converged within its bounds. The μ-axis frontier sits
at `pt6d05R01_05` (2.39×10⁻³), the dose-axis frontier at `pt6d03R00_08`
(9.93×10⁻¹⁰). 8 strict Stickman dominators (μ>2.169e-3 AND dose<1.527e-9)
across 96 evals — same count as at 76 evals. Next campaign needs **t_upper
raised to 8.0** OR the **spacer↔plate-00 overlap fixed** to lift the
implicit cap. The looser AND-dominance count (μ>baseline AND dose<baseline)
is 30 — useful for Pareto-front breadth, not for single-axis records.

**pt6d06-specific (2026-06-15):** ran clean end-to-end (no rc=120, no
fail_managed) under the [[pipeline-poll-rc120-atexit-death]] mitigations:
fresh `--name-prefix pt6d06`, mu2esrv01 idle at 13 GB / 173 GB free
(vs the 170 GiB peak that killed pt6d05 R1 + foilsf12 R2 on 2026-06-13).
First exploratory low-t2=3.0 pick (`pt6d06R01_08`) landed at μ=2.174e-3
/ dose=1.638e-9 — joins the dominator family but not the front.

### DECISION: high-stats going forward, switch the PICKER later (2026-06-24)
- **New evals: already all high-stats** — `pot_only` njobs=800 (2M events/eval) is
  the default, so every new prodtarget6d eval is ~1.5% Poisson, not 3%.
- **Picker (GP that proposes): keep training on ALL data FOR NOW, switch to
  high-stats-only LATER.** Rationale: hard-filtering the picker to pt6d15+ today
  (n≈31) trades 3%→1.5% noise for a catastrophic coverage loss (291→31 pts in 6D
  → GP extrapolates badly in unsampled regions → worse exploration). Noise-vs-
  coverage: at n≈31 coverage wins. The noisy 1× data ages out on its own as
  high-stats campaigns accumulate.
- **TRIGGER to flip the picker to high-stats-only: ~80–100 high-stats points**
  (≈2–3 more 4× campaigns at ~30–40 each). Implementation when ready: add a
  history filter in `botorch_predict._load_history_tensor` (mode=prodtarget6d)
  mirroring the cloud's `--highstats-only` (`HISTATS_PREFIXES`). NOT done yet.
- Alternative considered (rejected for now as more work): heteroskedastic
  FixedNoiseGP with per-point variance ∝ 1/events — keeps coverage AND downweights
  noisy points (statistically optimal); revisit if the accumulate-then-switch plan
  proves too slow.

### 4×-stats CONFIRMS the noise diagnosis — stars sit 1.8× tighter (pt6d15, 2026-06-24)
pt6d15 (njobs 800, 2M events/eval, 29 t8 rows) tested whether more stats pulls the
stars onto the GP cloud. **Apples-to-apples test (ONE GP fit on combined 1×+4× t8
data, n=185, to control sample size):** pt6d15 (4×) points' in-sample residual
**1.28%** vs pre-pt6d15 (1×) **2.33%** → **1.8× tighter**, ≈ the √4=2× Poisson
prediction. (Naive SEPARATE-fit gave a misleading 0.03% vs 2.31% / ~70× because
n=29 in 6D near-interpolates regardless of noise — always use the COMBINED fit to
compare noise across subsets.) Confirms: (1) "stars off cloud" was real ~3%
measurement noise, (2) 4× stats cuts it ~2× exactly as theory says, (3) stats lever
not model lever. Full coverage needs ~16× stats (~0.6% resid) — diminishing returns
vs grid cost. (Campaign: pt6d15 best μ did NOT beat champion 2.493.)
**BUT the RENDERED cloud barely widened (2026-06-24):** adding pt6d15's 29 clean
points to the t8 fit moved the cloud's pred-μ width only 1.61e-4→1.67e-4 (~4%),
combined fitnoise 2.19%→2.10% — still ~2.6× narrower than the obs-μ spread
(4.32e-4), stars still scatter outside. Reason: the 29 low-noise points are only
16% of the n=185 fit; the 156 noisy (3%) points DOMINATE, so the GLOBAL fit still
smooths ~2.1%. **The cloud's width tracks the WHOLE dataset's noise, not the few
clean points** — so widening the rendered cloud needs MOST of the data at high
stats (several 4× campaigns or re-measuring existing points), not one batch. The
per-subset 1.8×-tighter result is real but those points are outvoted globally.

### pot_only njobs 200→800 SATURATES grid slots (2026-06-24, pt6d15)
The 4× njobs bump (`STAGE_TARGETS["pot_only"]` 200→800, for 2M events/eval to halve
μ_per_POT Poisson noise) means **800 jobs/eval × q=10 = 8,000 jobs/round** — observed
to EXCEED available grid slots: pt6d15 R2 showed 4762 queued total, **2892 idle vs
1870 running**. So the "wall-clock stays ~3h if slots available" assumption does NOT
hold at q=10 — the round stretches via queueing (idle jobs wait). Net: 4× stats at
q=10 trades wall-clock, not just CPU. Mitigation if speed matters: lower q, or keep
800 only for targeted few-config re-measures (not full q=10 campaigns). Also 4×
/pnfs output — watch /data quota (was climbing 993→1045 GB during pt6d15).

### GP UNDERFITS the μ surface — stars far from cloud (2026-06-23, measured)
The prodtarget6d GP does NOT reproduce its own training points: GP-mean evaluated
AT each training star has mean |resid| **2.3%** (champion 2.493e-3 dragged DOWN to
2.343, −6%), fitting obs-noise ~5.1e-5 (~2.3% of μ). Contrast: the SAME
SingleTaskGP+Standardize on foilsf gives 0.11% residual and on ipa 0.07% — both
INTERPOLATE their stars. So prodtarget6d stars scatter off the cloud because the
GP underfits, not framing/compression. **RESOLVED 2026-06-23 (team-tested): CORRECT behavior, real ~3% measurement noise,
not a bug.** Fitted GP noise = 3.1% of μ = the μ_per_POT Poisson floor
([[bo-noise-budget]]); forcing noise→1e-6 drops residual 2.27%→0.00% (GP CAN
interpolate, correctly chooses not to); ARD refuted (already ARD Matern-5/2,
lengthscales non-railed, explicit ARD worse). prodtarget6d's μ is ~7× noisier than
foils sob (0.4%)/ipa (0.6%), so its GP correctly de-noises and the noisy stars
scatter ±3% off the de-noised cloud. **Only lever = more stats/eval (500k→2M POT
≈ ½ Poisson σ); NOT ARD/kernel/basis/render.** Leave GP as-is. See
[[gp-cloud-rendering]]. (Surrogate-fit story only; champion/ceiling robust, below.)

### Champion significance — robust multi-campaign cluster, NOT a lone outlier (2026-06-23, n=260)
Unlike the foils 3.91 champion (a 6.3σ lone outlier — [[bo-foils]]), the
prodtarget6d μ champion sits at the top of a WELL-POPULATED cluster:
- champion `pt6d07R01_07` 2.493e-3 vs runner-up `pt6d09R01_02` 2.488e-3 =
  **0.1 Poisson-σ** apart (Poisson σ≈3%≈7.5e-5) — statistically TIED.
- only **1.8σ above the next-10 cluster** (mean 2.437e-3, std 3.05e-5); 2.5σ
  above the all-eval mean.
- top pack 2.493/2.488/2.474/2.473/2.450 spans **four independent campaigns**
  (pt6d07/08/09/12) → the ~2.45–2.49e-3 ceiling is reproduced, robust.
**So the +4% #1 lead is unresolved (champion interchangeable with the next few);
no confirmation-re-run concern like foils.** The champion being OUTSIDE the GP
cloud (+2.6%) is the SEPARATE t>7 box-edge mean-reversion ([[gp-cloud-rendering]]),
not a statistical-outlier issue — don't conflate the two.

### pt6d07: t_upper 7→8 raise breaks the cap; new μ champion (2026-06-17/18)

Acting on the pt6d06 verdict, pt6d07 raised **t_upper 7→8** and added an
end-plate lug clamp (`lPlate[0]=lPlate[-1]=tPlate` in `_expand`, to kill the
upstream/downstream lug-overhang that had forced the 7.0 cap; see
[[prodtarget-spacer-supportring-overlap]]). Result: the μ "plateau" was
**box-edge, not physics** — μ kept climbing the moment the box opened.

- **New μ champion `pt6d07R01_07` = 2.493×10⁻³** (+15% over Stickman) /
  dose 2.51×10⁻⁹, at t=(7.15, 7.51, 7.71) — all three control points ABOVE
  the old 7.0 cap. R0 10/10 clean; R1 7/10 (3 lost to `SpacerNegZ_0 × Plate00`,
  the 50-100 nm precision-tolerance class). 11/17 picks at t1≥7.5.
- Only **17/112** evals sit in the new t>7 region but it carries real signal:
  mean μ **2.295e-3 (t>7) vs 2.186e-3 (≤7) = +5%**. Strict-dominator count
  unchanged — the front extended up-right (more μ, more dose), not up-left;
  dose-axis floor (`pt6d03R00_08` 9.93e-10) still the binding "beat-both" constraint.
- The champion's out-of-GP-cloud / forward-LOO "surprise" is a direct
  consequence of this raise (sparse new corner, GP mean extrapolates down
  from the 95 ≤7 rows). Full analysis in [[gp-cloud-rendering]].

**Length side-effect (unenforced engineering constraint, 2026-06-18):** because
plate pitch = `plateLugThickness` and 6D ties `lug = t + 0.75`, pushing
thickness to the t_upper edge **lengthens the whole target**. Via the envelope
identity (`2·halfStickmanLength = 2·supportRingLength + 4·spacerHalfLength +
Σ plateLugThickness`, see [[production-target-stickman]]): champion full length
= **308.9 mm vs nominal 232.2 mm = +33% (+76.7 mm)** (Σlug 286.7 vs 210.0;
cores +50%, 261.9 vs 175.0 mm). The forker auto-grows the envelope to fit
(`halfStickmanLength=154.44`, `productionTargetMotherHalfLength=174.44` vs
nominal 116.1/~136), so the sim is self-consistent — but **the BO never checks
the +77 mm target against the real PS envelope or beam optics.** Any t_upper
optimum is systematically longer; a real build needs that fit verified.

**What actually drives μ — mid-target thickness, NOT length (n=112 regression, 2026-06-18).**
Pearson corr of `mu_per_POT` with each knob: **`t1`=+0.67** (mid-plate thickness,
u=0.5≈plate 17) dwarfs all others; t2=+0.16, t0=+0.04, r0=+0.36, r1=+0.29,
r2=−0.07. Standardized OLS β: **t1=+0.62**, then t2=+0.22, r0=+0.20, t0=+0.15,
r1=+0.11, r2=−0.13 (R²=0.57). Consequences: (a) the gain is **where** the
material is (mid-target, at shower/pion-production max), not total length —
up/downstream thickness barely move μ; (b) among the longest-third targets μ
still spans the *full* 2.00–2.49e-3 range, so length is permissive, not
determinative, and `r0` (upstream radius) contributes independently. **Caveat:**
`lug=t+0.75` welds thickness↔material↔length onto one collinear axis, so the data
can't fully separate "length" from "mid-thickness"; isolating length would need a
controlled `halfStickmanLength`-at-fixed-thickness scan this 6D box can't express.
The +33% length is a **byproduct** of thickening the middle plates, not the cause
of the μ gain.

### pt6d08: current-box-only picker (GP fit on 17 t-upper=8 evals) — launched 2026-06-18

To stop the 95 retired t≤7 rows from range-compressing the GP over the high-μ
corner, pt6d08 refits the **picker** GP on only the 17 t-upper=8 (pt6d07) evals.
Mechanism (env-gated, NO `closed_loop.py` change): set
**`AUTORESEARCH_CURRENT_BOX_ONLY=1`** (+ optional `AUTORESEARCH_TMAX_MIN`,
default 7.0) on the closed-loop launch → `botorch_predict.py:_load_history_tensor`
drops prodtarget rows with `max(t0,t1,t2) ≤ tmax_min`. It reaches every round
because `closed_loop.py:_qnehvi_picks_subprocess` calls `subprocess.run(cmd)`
**without `env=`**, so the picker subprocess inherits the parent env (R0 launch-pick
at :746 + later rounds at :359). The picker still proposes over the full box
(t∈[3,8]); only the *fit* is restricted. Same idea as the cloud renderer's
`--current-box-only` flag ([[gp-cloud-rendering]]) but env-gated for the picker.

Launch: `AUTORESEARCH_CURRENT_BOX_ONLY=1 nohup .venv-graph/bin/python -m
graph.closed_loop --mode prodtarget6d --picker qnehvi --q 10 --max-rounds 2
--name-prefix pt6d08 --stagger 150`. Dry-run confirmed `kept 17 rows`. Ran
concurrently with the foilsf16 foils closed-loop (different mode+prefix → no
collision). **Caveat:** n=17 in 6D is a sparse fit (GP rails) → R0 picks may
cluster.

**R0 result (2026-06-18): restricted fit explored the high-t corner but found NO
new champion; clustering confirmed.** 10/10 children completed, **6 landed
leaderboard rows** (loop advanced to R1 cleanly). **The 4 no-row children
(`pt6d08R00_{03,04,08,09}`) died at `preflight=fail_managed` (3/3 attempts),
never submitted to grid** — config dirs hold only `geom/` (no `pot_only/`); the
barrier counts them "completed" because the graph reached `done` via the
terminate-at-preflight path (final-state keys end `…geom_path, metrics…` vs the
successful `…geom_path, iter…`). `fail_managed` = a real BO-movable-volume
overlap, the spacer↔plate / support-ring class ([[prodtarget-spacer-supportring-overlap]],
same as pt6d07 R1's SpacerNegZ_0×Plate00); NOT the old false-positive bug
([[preflight-mode-tuple-prodtarget6d-omission]] — that failed all 10; here 6
passed). **Key consequence: the current-box (high-t) restriction RAISES the
overlap-rejection rate** — 3 of the 4 failures sit at the t=8.0 ceiling (thick
plates + lug=t+0.75 pack the stack until spacers/plates collide), so 4/10 here
vs 3/10 in pt6d07 R1. ~30-40% of high-t-corner picks are geometrically
infeasible and rejected pre-grid; the 2026-06-08 spacerHalfLength shrink does
NOT cover these extreme-t geometries. Best R0 pick `pt6d08R00_01` μ=**2.410e-3**
(tmax=7.45) — **below** the prior champion 2.493e-3 (still +11% over Stickman).
All 6 picks clustered high-μ / **high-dose** (μ 2.07–2.41e-3, dose 2.2–3.3e-9),
5/6 at tmax>7 — exactly the predicted n=17-sparse-fit behavior: the GP concentrated
where the champion already lives instead of finding a new record. Confirms that
restricting the fit to the current box reproduces/explores the corner but does not,
on its own, push past the existing max in one batch.

**R1 result + FINAL (2026-06-18): loop done at max_rounds=2; restricted-fit round
plateaued ~0.8% under the champion — did NOT beat it.** R1 barrier resolved all 10;
**8 landed rows** (2 more preflight deaths `pt6d08R01_{03,04}` → **14/20 children
survived preflight overall, 6 killed at spacer↔plate overlap = 30%**, confirming
the high-t-box hazard). Best pt6d08 = **`pt6d08R01_08` μ=2.4739e-3** at
r=(4.026,4.500,2.174) t=(7.076,7.615,7.903), dose 2.87e-9, peak plate 34
(runner-up `R01_00` 2.4731e-3). R1 improved over R0 (2.410→2.474) as the GP got
more high-t data, but **stayed −0.78% below champion `pt6d07R01_07` (2.4933e-3)**
and ran HOTTER (dose 2.87e-9 vs champion's 2.51e-9 — pushed r1 to the 4.5 rail,
thinner-radius ⇒ higher specific dose). **Conclusion: the 17-point current-box
fit concentrated proposals exactly where the champion lives but could not exceed
it — evidence of genuine saturation of the t-upper=8 regime, not a full-history
range-compression artifact.** The champion's slightly *lower* radii (3.77/3.79/2.36)
beat pt6d08's rail-pushed (4.03/4.50/2.17) on both μ and dose, so the next gain (if
any) is unlikely to come from more high-t exploration in the same box.

### pt6d09: full-history fit (the control for pt6d08) — DONE 2026-06-19
After pt6d08 showed the **box-restricted** fit couldn't beat the champion, pt6d09 ran
the complementary test: **standard full-history qNEHVI** (no `AUTORESEARCH_CURRENT_BOX_ONLY`;
GP fit on all 126→140 evals over the whole box), q=10, max-rounds=2, launched 2026-06-18
on mu2esrv01 concurrent with the foilsf17 foils loop. (Launch-timing note: foilsf17 was
mid-submit; the host-wide `/tmp/mu2e_submit` lock serializes submits across campaigns so
concurrency is token-safe regardless of timing — see [[concurrent-token-contention]].)
**Result: still did NOT beat the champion, but got closer than pt6d08.** R0 6/10 + R1 8/10
= **14 rows** (6/20 preflight deaths, ~30%, same high-t spacer↔plate overlap). Best =
**`pt6d09R01_02` μ=2.4879e-3** at r=(3.33,4.24,2.00) t=(7.64,8.00,5.81), dose **3.20e-9**
(hot), peak plate 34 — **−0.22% under champion `pt6d07R01_07` (2.4933e-3)** (vs pt6d08's
−0.78%). The full-history fit spread R0 picks wider/lower (μ 2.18–2.42e-3, incl. the
dose-floor region) as intended, but its best-μ point still landed in the high-t/high-dose
corner. **Combined verdict (pt6d07/08/09): `pt6d07R01_07` 2.4933e-3 (+15% over Stickman)
is a robust μ ceiling for this 6D box — two independent follow-ups (box-only fit, full
fit) both plateaued just under it.** Further μ gain needs a different lever (rOut/N/material
or the dose-floor corner), not more sampling of the saturated t-upper=8 region. Leaderboard
= 140 evals; strict Stickman dominators still 8 (pt6d08/09 added none — all ran hot).

### pt6d10: pot_only throughput change (200×2500) — DONE 2026-06-19
Not a science run — a **grid-throughput test**. Switched pot_only from **100 jobs × 5000 events**
to **200 × 2500** (`graph/config.py` STAGE_TARGETS + `pipeline.py` STAGES; constant 500k total
→ 3% noise budget preserved), mirroring the long-standing mustops_ce 200×2500 fix, to halve
per-job wall + double parallelism. **Result: round wall-clock dropped ~4.8 h → ~3.1 h (−35%)**
(pt6d10 R0 3h00m / R1 3h13m, total 6h13m vs pt6d09 9h35m); −35% not −50% because the fixed
poll/harvest/stage-out portion doesn't shrink. Config (full-history qNEHVI, q=10×2) otherwise
identical to pt6d09. Science result unremarkable (BO draw): 16 rows, best `pt6d10R01_06`
2.396e-3 — below champion (this round's picks landed low; stats unaffected by the split).
**The 200×2500 pot_only config is now the default for all future prodtarget runs.** See
[[closed-loop-runner]] for the measured round wall-clock.

### Length↔μ coupling: no within-nominal-length config beats Stickman (2026-06-19)
Target full length `L = 2·(SUPPORT_RING_LEN + 2·SPACER_HALFLEN + Σ lPlate/2)`
(`autoresearch_bo_michael.py:1692`); with `SUPPORT_RING_LEN=8.1`, `SPACER_HALFLEN=1.5`,
35 plates, lug=tPlate+0.75, the **nominal stock Stickman length is L_nom = 2·8.1 + 4·1.5
+ 35·6.0 = 232.2 mm** (lug=6.0 uniform). The μ champion `pt6d07R01_07` is **308.9 mm
(+33%)**. **Filtering all 156 evals to L ≤ 232.2 leaves only 4 configs, and ALL FOUR are
below the Stickman baseline (2.169e-3):** best is `pt6d06R01_06` μ=**2.004e-3** @ 222.3 mm
(t=6.70/4.95/3.53), then pt6d03R01_02 1.956e-3 @224 mm, pt6d02R00_09 1.796e-3 @201 mm,
pt6d02R00_00 1.746e-3 @177 mm. **Root cause: μ is coupled to plate thickness (more Inconel
⇒ more stops ⇒ higher μ), and length ∝ Σ plate thickness, so the unconstrained BO traded
length for μ freely — the +15% μ champion "costs" +33% length.** The short configs are just
early Sobol points, never high-μ. **Consequence: within a buildable (≤ nominal) length the
current campaigns offer NO improvement over the existing design** — to find a good *short*
target needs length added as an explicit constraint or 3rd Pareto objective (the optimizer
never explored a short+high-μ frontier; it may not exist, but it was never sampled).
Compute per-config length: `m._expand(x)` → `2·(SR+2·SP+ΣlPlate/2)`.

### Search space (v1)
| Quantity | K | Knot positions | Default-equivalent | Proposed bounds |
|---|---|---|---|---|
| `rOut(u)`             | 3 | u={0,0.5,1} | (3.15, 3.15, 3.15) | [2.0, 4.5] mm |
| `plateThickness(u)`   | 3 | u={0,0.5,1} | (5.0, 5.0, 5.0)    | [3.0, 8.0] mm |
| `plateLugThickness(u)`| 3 | u={0,0.5,1} | (6.0, 6.0, 6.0)    | [4.0, 12.0] mm |
| `numberOfPlates` (int)| — | scalar      | 35                  | [20, 50] |
| `plateMaterial`       | — | scalar (v1) | "Inconel718"        | fixed v1; categorical v2 |

= **10 continuous + 1 integer** dimensions. Manageable with skopt/BoTorch
+ O(50-100) evaluations.

### Profile evaluator (Lagrange quadratic through 3 knots)
```python
def profile(c, N):                 # c = (c0, c1, c2); knots at u=0,0.5,1
    u = np.linspace(0, 1, N)
    return c[0]*(1-2*u)*(1-u) + c[1]*4*u*(1-u) + c[2]*u*(2*u-1)
```
- Reduces to constant when c0=c1=c2 (recovers baseline).
- Reduces to linear ramp when c1 = (c0+c2)/2.
- Quadratic captures upstream/downstream + center-vs-edges in 3 numbers.
- v2 upgrade path: K=5 PCHIP (monotone cubic, no ringing) if v1 pins to
  parabolic edges of the box (same staged pattern as
  [[bo-foils]] v1→v2→v3).

### Hard constraints the forker must enforce
1. **Vector length**: all four per-plate vectors length-N
   (`PTM.cc:419-438` asserts; see [[production-target-stickman]]).
2. **Per-plate overlap**: `plateLugThickness[i] ≥ plateThickness[i] + ε`
   (default ε=0.5 mm). NOT asserted by geom maker; silent overlap if
   violated. Project after profile evaluation:
   `lPlate = np.maximum(lPlate, tPlate + 0.5)`.
3. **Envelope identity** (`ProductionTarget.cc:230`):
   `halfStickmanLength = supportRingLength + 2·spacerHalfLength
                       + Σ plateLugThickness / 2`
   Forker recomputes per config; bumps
   `productionTargetMotherHalfLength ≥ halfStickmanLength + margin`.
4. **Beam clearance**: `min(rOut) ≥ ~3·beamSpotSigma = 3 mm` (with σ=1 mm
   default) to avoid clipping the proton beam against the plate edge.

### Forker recipe
1. Copy `backing/Offline/Mu2eG4/geom/ProductionTarget_Stickman_v1_0.txt`.
2. Substitute the four vectors (`rOut`, `plateThickness`, `plateLugThickness`,
   `plateMaterial = [m]*N`) via profile evaluator + projection.
3. Recompute and substitute `targetPS_halfStickmanLength`,
   `targetPS_productionTargetMotherHalfLength`,
   `targetPS_numberOfPlates`.
4. Include the patched file from a derived
   `geom_run1_a_bo_prodtarget_XXX.txt` (parallel to
   `geom_run1_a_stickman.txt:69`).
5. Hand to [[pipeline]] / [[graph-runner]] like any other config.

### POT.fcl single-stage cost (benchmarked 2026-06-06, MDC2025aq defaults)
Ran `mu2e -c Production/JobConfig/beam/POT.fcl -n {1,100}` after
`muse setup /cvmfs/.../Musings/SimJob/MDC2025aq`:
- Init cost (1-evt): 67 s wall, 43 s CPU, **VmPeak 2.27 GB** — needs ≥2.5 GB
  request (see `mu2e-memory-request-norm` (user-memory note) community default).
- Steady-state (100-evt minus init): **~1.8 s CPU/event**, VmPeak unchanged
  at 2.28 GB.
- **BeamFilter pass = 10/100 (10%)** at defaults — events where ≥1 charged
  particle reaches DS2Vacuum. NOT muon-specific (mix of π±/μ±/e±). To
  separate muons, would need a `ParticleCodeFilter` added downstream of
  `BeamFilter` (pattern: `PionSelector` in `beam/prolog.fcl:48-55`).
- **NeutralsFilter pass = 54/100 (54%)** — neutrals into CRV envelope.
- Outputs: `sim.*.Beam.*.art` (159 KB @100evt) + `sim.*.Neutrals.*.art`
  (210 KB @100evt). These are the inputs the downstream `mubeam` stage
  consumes — POT itself does NOT produce stopped-muon counts.
- **Critical**: POT.fcl alone gives a charged-fraction proxy, not stopped
  muons. Stopped-muon yield requires the full POT → mubeam chain — same
  reason the current [[pipeline]] starts at `mubeam` (consuming a frozen
  POT-stage prior `MuBeamCat.txt`) and never re-runs POT per config.
  Optimizing the PT geometry means we MUST re-run POT per config.
- Budget estimate at σ=1% on a charged-fraction proxy:
  N≈900 events × 1.8 s = ~27 min/eval × 100 evals × 1 core = ~50 core-hours
  (≈30 min wall if 50 jobs parallel). Versus ~5× that for stopped-muon
  proxy (needs POT→mubeam chain per eval).

### Combined POT + analyzer in one fcl (benchmarked 2026-06-07)
Wrapper extends POT.fcl by appending `ReadVirtualDetector` to a new
`AnaPath` in `end_paths` (no intermediate .art read needed):
```fcl
#include "Production/JobConfig/beam/POT.fcl"
physics.analyzers.readVD : {
  module_type   : ReadVirtualDetector
  vdStepPoints  : "g4run:virtualdetector"   # in-memory, before BeamFilter
  tvdStepPoints : "g4run:timeVD"
  saveAllPDG    : true   # CAUTION: see size warning below
  savePDG       : ["mu_minus","mu_plus","pi_minus","pi_plus"]  # use this in prod
  maxPrint      : 0
}
physics.AnaPath   : [ readVD ]
physics.end_paths : [ OutputPath, LogPath, AnaPath ]
services.TFileService.fileName : "pot_vd.root"
```
- Cost (100-evt, defaults): 225 s wall, 219 s CPU (**~2.2 s/evt**, +22% over
  POT-only's 1.8 s); **VmPeak 3.04 GB** (+770 MB over POT-only) — needs
  ≥3.5 GB grid request.
- **Output size warning**: `saveAllPDG:true` → `pot_vd.root` = 235 MB / 100
  evt = **2.4 MB/evt** (e± dominate). For production use, restrict via
  `savePDG: ["mu_minus","mu_plus","pi_minus","pi_plus"]`.
- **Branch naming gotcha**: `ReadVirtualDetector::ntvd` uses branch name
  `sid` (StepInstance ID) for the VD id, NOT `vdid` as the variable name
  in the C++ source suggests. ROOT queries on `vdid` fail with
  `TTreeFormula::Compile: Bad numerical expression`.
- Muon counts at defaults (100 POT events): 19 μ± total VD hits, mostly
  upstream (Coll1=3, Coll3x=4, Coll5=1, PS_FrontExit=4, PSPbar=4,
  TS2/4_Bend=2). Downstream Coll5_Out=1, ST_In=0 — too sparse for
  single-job BO objective; need ~10k POT events for ~1% σ on a downstream
  muon-count proxy.

### v1 thermal proxy: peak specific dose (Edep / mass) per plate
**Choice**: `max_i (Edep_i / mass_i)` over plates, units Gy/POT
(= J/(kg·POT)). Rationale: peak temperature in steady-state radiative
cooling scales monotonically with peak volumetric power density, which =
ρ · (Edep/mass). Raw Edep alone (per plate) sizes the cooling system as a
whole but does NOT protect against a single hot plate. Sum Edep / sum mass
(volume-averaged) is too forgiving — lets BO trade hot plates against cool
neighbors.

**Why Edep/mass and not Edep**: two plates with identical Edep but
different mass have different peak T. Shrinking `rOut` at fixed beam
profile keeps Edep ≈ constant but divides by smaller mass → specific dose
scales as **1/rOut²** (mass ∝ rOut²). This is why rOut is the dominant
thermal knob even though it doesn't change DPA ([[production-target-stickman]]
DPA vs thermal coupling section).

**Edep/mass is NOT DPA** — total ionizing+non-ionizing Edep overestimates
DPA by ~10-100× at Mu2e proton energies. But correlation is strong for
fixed material, so it's a fine *relative* proxy across BO configs at
fixed plate material. Material-mixed v2 needs post-hoc NIEL correction.

**Forker computes mass from geom knobs** (no need to round-trip through G4):
`mass_i = π · rOut[i]² · plateThickness[i] · ρ_material[i]`. The forker
already substitutes all four into the geom file → all info is in hand
without a geom read-back.

**Reported per-job tuple** (extends current STAGES harvest pattern):
- `muons_per_POT` — primary objective
- `peak_dose_per_POT = max_i (Edep_i / mass_i)` — thermal soft constraint
- `mean_dose_per_POT = Σ Edep / Σ mass` — secondary diagnostic
- `plate_edep[N]` — full per-plate Edep array (debug/post-hoc analysis)

**Bi-objective BO setup** (mirrors foilsf v3 qNEHVI):
`maximize (muons_per_POT, −peak_dose_per_POT)` → Pareto front of
yield-vs-thermal-headroom, picks engineering-relevant champions
automatically without an α to tune.

**Implementation cost** (CORRECTED 2026-06-07): enabling the PT SDs in
FCL is a **no-op** for Stickman. Adding all 8 PT SD names to
`SDConfig.enableSD` produced empty StepPointMC collections and zero CPU
overhead (1.73 s/evt = same as POT-only). Root cause: the Stickman
builder `constructStickmanTarget` (`Mu2eG4/src/constructTargetPS.cc:1278-2305`)
does NOT call `SetSensitiveDetector` on the plate logicals; the SD enum
values `ProductionTargetCoreSection`/`FinSection`/etc. are only wired by
the older Hayman segmented-core builder around `constructTargetPS.cc:800`.
The Stickman SD `#include "SensitiveDetectorName.hh"` is in fact
commented out at `constructTargetPS.cc:32`.

**Source patch needed** (~10 lines):
1. Uncomment `constructTargetPS.cc:32` `#include
   "Offline/Mu2eG4/inc/SensitiveDetectorName.hh"`.
2. After `finishNesting(plateInfo, ...)` at lines 1705-1713, call
   `plateInfo.logical->SetSensitiveDetector(...)` with an SDManager
   lookup for a Stickman SD (either reuse `ProductionTargetCoreSection`
   or define new `ProductionTargetStickmanPlate`).
3. Plate copy number is already set (`ithPlate` passed to `finishNesting`
   at `constructTargetPS.cc:1710`) → maps StepPointMC `volumeId` to plate
   index for free.
4. Rebuild patched `libmu2e_Mu2eG4.so` against MDC2025aq Musing + ship
   via LD_PRELOAD — same recipe as [[muse-backing-pattern]] used to fix
   [[calo-constant-across-helical]] for the helical plug.

**Surprise gotcha** (worth bumping any future "is the SD enabled?" check):
empty StepPointMC collection in art file + zero CPU overhead means the
SD is unwired on the geometry side, NOT that the FCL `enableSD` line is
wrong. Diagnose by `grep SetSensitiveDetector` inside the builder
function for the relevant geom_run1_*.txt selection, not by trusting
`SDConfig.enableSD`.

**Analyzer side** (after SDs wire up): `StepPointMCDumper` (shipped) writes
`volumeCopy` but NOT `eDep` — so even after patching SDs, a custom
analyzer is required to sum eDep per plate copy. ~30 lines patterned on
`StepPointMCDumper_module.cc` adding `i.totalEDep()` to the VDHit struct.
Build into [[mmackenz-workflow]]-style autoresearch_muse area.

### DPA / NIEL support in Mu2e Offline (checked 2026-06-07)
- `grep -rln "dpa|DPA|displacementPer|nielFactor|NIEL|kermaToD"` over
  `backing/Offline/` → **zero hits**. There is no built-in DPA calculation
  module.
- What DOES exist: per-plate sensitive-detector regions in
  `Mu2eG4/inc/SensitiveDetectorName.hh:54-78` —
  `ProductionTargetCoreSection`, `FinSection`, `PositiveEndRing` etc. score
  StepPointMC hits per plate region, but **are OFF by default in POT.fcl**
  (`SDConfig.enableSD: [virtualdetector]` only — see [[g4-speed-knobs]]).
- Feasible thermal/rad-damage proxy without source patch: enable
  `ProductionTargetCoreSection`/`FinSection` in `enableSD`, sum
  `StepPointMC::eDep()` per plate copy in an analyzer → Edep [MeV] per
  plate per POT → ÷ mass = dose [Gy]. To convert to DPA, multiply by
  published NIEL tables for p/n/π on Inconel718 (table-based
  post-processing, not in Offline).
Likely candidates:
- `stoppedMuons / POT` measured at the muon stopping target (cleanest, but
  requires running POT → mubeam → muStops chain — multi-stage, expensive
  per eval, much costlier than [[bo-foils]] which is single-stage)
- Pion flux at PS exit (cheaper, one-stage POT; less directly meaningful)
- Scalarized `obj = stoppedMu/POT − α · (peakPowerProxy)` if a thermal
  surrogate is added

### Thermal/DPA safety
This box **touches the thermal design point** — all four knobs are
thermal-coupled per [[production-target-stickman]]. v1 should either:
(a) hard-clip the box to ±20% of defaults (no engineering check needed,
small thermal perturbation), or
(b) post-hoc filter champions through a thermal/DPA check before any
hardware-relevant claim.

DPA is **not** dominated by this box (σ is excluded). Local DPA stays
~constant as long as `min(rOut) ≥ few·σ`.

## Cross-links
- Related: [[production-target-stickman]] (knob inventory, z-march,
  per-plate semantics), [[bo-foils]] (precedent for staged
  v1→v2→v3 dim growth), [[closed-loop-bo-design]] (runner constraints
  if reused), [[scalarized-objective]] (objective family pattern),
  [[batch-bo]] (q>1 if/when launching)
- Source files (read-only refs, no edits):
  `backing/Offline/Mu2eG4/geom/ProductionTarget_Stickman_v1_0.txt`,
  `backing/Offline/GeometryService/src/ProductionTargetMaker.cc:407-438`,
  `backing/Offline/Mu2eG4/src/constructTargetPS.cc:1655-1717`,
  `backing/Offline/ProductionTargetGeom/src/ProductionTarget.cc:230`

## M1 — forker (DONE 2026-06-07)

Implemented as `ProdTargetMode` class in `autoresearch_bo_michael.py`
(parallel to MichaelMode/HelicalMode/FoilsMode/FoilsFracMode; registered
in `MODES["prodtarget"]`). Reuses the existing `BOMode` ABC + CLI
(`propose | preflight | evaluate | show-priors`).

**Two design choices forced by reuse**:
- `Point.sob` carries `mu_per_POT` (objective), `Point.calo` stays 0.0
  (avoids `DEFAULT_ALPHA=1e5` drowning the muon signal). Pareto second
  objective `edep_per_POT_MeV` rides in `Point.extras` (NOT `Point.calo`)
  and is consumed by `botorch_predict._load_history_tensor` via a
  `mode == "prodtarget"` branch that builds Y as `[mu_per_POT, -edep]`;
  qLogNEHVI then handles both axes. Wired 2026-06-07.
- Leaderboard column is named `mu_per_POT` in the header; internally
  stored as `sob`. Diagnostic only — `load_history_row` maps the column
  back to `Point.sob`.

**Required project-wide overlay** the forker MUST emit (not optional, even
though it has nothing to do with the PT geometry — Stickman base file
inherits the same broken `TT_MidInner -> DS2Vacuum` placement as plain
`geom_run1_a.txt`, see [[geom-run1a-vs-run1b]]):
```
bool   tracker.inDS2Vacuum   = true;
double ds2.halfLength        = 3825;
bool   ds.hasServicePipes    = false;
```
Without these, `mu2e -n 1` aborts with `G4Exception GeomMgt0002 /
G4SmartVoxelHeader::BuildNodes() / "Daughter physical volume
VirtualDetector_TT_MidInner is entirely outside mother logical volume
DS2Vacuum"`. Mirrors what FoilsMode/HelicalMode `_geom_text` already
append. Same v111 patch.

**Preflight wiring confirmed**: cmd_preflight copies the rendered geom
into a workdir, sets `MU2E_SEARCH_PATH=<workdir>:$MU2E_SEARCH_PATH`, then
uses the bare basename in `services.GeometryService.inputFile`. Absolute
paths in `inputFile` fail with `search_path: Can't find file "..."` —
GeometryService only honors basenames found on the search path. Same
wiring works unchanged for prodtarget mode.

**Smoke tests (rc=1 PASS init=True, no geom-fail signature)**:
- `prodtarget_smoke1`: defaults (3.15/5/6/35) -> halfStickmanLength
  exactly 116.1 mm (matches Stickman file's documented total length 232.2 mm).
- `prodtarget_smoke2`: asymmetric (rOut 4.0->2.5, t 3.5->7, lug 5->9,
  N=40) -> envelope recomputed correctly; preflight passes.

**Known minor**: `parse_geom` round-trip is exact only when N is odd
(midpoint sample lands exactly at u=0.5). For even N (e.g. 40), the
recovered middle control point is off by <1% (u=N//2/(N-1) = 0.513 at
N=40). Cosmetic only; parse is diagnostic, not load-bearing.

## POT denominator: genCountLogger.makeHistograms (exact, per-file)
POT.fcl already runs `genCountLogger` (`module_type: GenEventCountReader`)
with `makeHistograms: false`. Flipping it to `true` in the wrapper FCL
writes a 1-bin TH1D `genCountLogger/numEvents` with the exact integer
POT count for the job (`CommonMC/src/GenEventCountReader_module.cc:95-101`,
fills `(0., numEvents_)`).

uproot read:
```python
n_pot = int(uproot.open(path)["genCountLogger/numEvents"].values()[0])
```

This makes the harvest denominator EXACT per file (vs the
`len(files_seen)·events_per_job` proxy used elsewhere — see
[[harvest-denominator-bug]]). No new module needed; existing
infrastructure. Also robust against a partial-job that emitted an output
file with fewer events than `events_per_job` (the count reflects what
was actually generated, not what was requested at submit).

## M2 — pipeline integration (issues filed, work pending)
GitHub issues `oksuzian/Mu2eBO#10-#16` track the M2 build order with
explicit `Blocked by` / `Blocks` links in the bodies:
- #10 **DONE 2026-06-07**: Built `Code_MDC2025aq_prodtarget.tar.bz2`
  (377 B, backing-only — no source overlay needed for pure-config
  Stickman knobs; see [[muse-backing-pattern]] "Backing-only tarball"
  section). Working dir:
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/`.
  Installed at
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2`.
  Backs onto MDC2025aq → Offline v13_18_00, envset p101 (vs helical's
  p094 — different envset across modes is expected).
- #11 **DONE 2026-06-07**: uproot 5.7.4 + awkward 2.9.0 installed in
  `.venv-graph` via `uv pip` (venv is uv-managed, has no `pip` binary —
  see [[venv-relocated-to-data-volume]]). Added to
  `requirements-graph.txt`.
- #12 **DONE 2026-06-07**: `pot_only` stage wired into pipeline.
  `pipeline_templates/pot_only/template.fcl` (POT + ReadVirtualDetector +
  `genCountLogger.makeHistograms:true`); `STAGES["pot_only"]` with
  `code_tarball` + new `dsconf_musing: "MDC2025aq"` key;
  `write_code_tarball(stage_dir, base_tarball=None)` honors per-stage
  override; `_stage_dsconf(stage)` returns `f"{musing}_{cfg}"` when
  `dsconf_musing` is set (output: `nts.…POT_vd.MDC2025aq_pt001.…root`).
  STAGE_TARGETS["pot_only"]=100 in `graph/config.py`. Dry-run passes
  end-to-end (mu2ejobdef + mu2ejobfcl smoke).
- #12 Add `pot_only` stage + template + per-stage `code_tarball` key
- #13 New `harvest-pot-only` subcommand (uproot-based)
- #14 `BOMode.extract_metrics(summary)` ABC seam
- #15 `GRID_STAGES_BY_MODE` + `AUTORESEARCH_MODE` env var dispatch
- #16 Step A smoke (defaults `pt001`) + Step B closed-loop
  (`--name-prefix ptX01 --max-rounds 1 --q 2`)

**Repo label gap**: `oksuzian/Mu2eBO` only has the GitHub defaults
(bug/enhancement/etc.). The triage vocabulary documented in
`docs/agents/triage-labels.md` (needs-triage/ready-for-agent/etc.) does
not exist as gh labels — created with `enhancement` as a placeholder.
Worth a follow-up `gh label create` batch.

**Cold-start decision** (REVISED 2026-06-07): the "skip Sobol seeding"
plan crashed on contact with skopt (see
[[prodtarget-propose-skopt-empty-init]]) — `n_initial_points=0` requires
≥1 prior, which prodtarget doesn't have. Decision flipped to use skopt's
built-in Sobol-init: `ProdTargetMode.N_INITIAL_POINTS = 10`. First 10
`ask()`s are Sobol-random, then GP takes over. ~5 closed-loop rounds at
q=2 spent on Sobol; cheap relative to the 50-eval target.

## peak_dose_Gy_per_POT — 2nd BO objective (wired 2026-06-09)
Replaces the stack-total `edep_per_POT_MeV` axis. Formula:
```
peak_dose_Gy_per_POT = max_i (Edep_i / mass_i) * 1.602e-13 [J/MeV] / 1e-3 [kg/g]
mass_i = pi * rOut[i]^2 * tPlate[i] / 1000 [cm^3] * RHO_INCONEL718 [g/cm^3]
```
where `Edep_i` (MeV) comes from `summary["edep_per_plate_MeV"][i] / total_pot`
and `rOut[i]`, `tPlate[i]` are reconstructed from `x` via `_expand`.
**`RHO_INCONEL718 = 8.19 g/cm^3`** (constant on `ProdTargetMode`).

**Why peak/mass, not total edep**: temperature scales with peak volumetric
power density. Stack-total has two failure modes:
1. **N-scaling artifact**: more plates → higher total even when per-plate drops
2. **Hot-plate masking**: 1 plate near melt + 32 cool plates ≈ uniform stack
**1/rOut² coupling**: shrinking rOut keeps Edep ≈ const but divides by smaller
mass → specific dose ∝ 1/rOut². Makes rOut the dominant thermal knob.

**Empirical confirmation (4-row leaderboard 2026-06-09)**:
| config        | mu/POT  | edep_total | peak_dose | peak_idx | rOut profile |
|---|---|---|---|---|---|
| pt001/pt002 baseline | 2.17e-3 | 422 MeV | 1.52e-9 | 24 | 3.35→3.87 |
| ptX01R00_00          | 1.98e-3 | 412 MeV | **0.80e-9** | 0  | 2.0→4.5 (wide center) |
| ptX01R00_01          | 1.27e-3 | 179 MeV | **3.99e-9** | 22 | 4.5→2.0 (taper down) |

ptX01R00_01 has lowest edep-total (179) but **highest peak dose** (2.6× baseline)
— small r2=2.0 mm downstream plate concentrates beam. Stack-total alone
would have ranked it most thermally favorable — wrong sign.

**Wiring**: `ProdTargetMode.extract_extras(summary, x=None)` ABC seam updated
to take x; `cmd_evaluate` passes x. `format_row` adds
`peak_dose_Gy_per_POT` + `peak_plate_idx` columns. `botorch_predict.py`
mode-branch swaps Y[1] to `-peak_dose` with `-edep` fallback for legacy
rows. `edep_per_POT_MeV` kept as diagnostic column.

**Magnitude sanity**: ~1.5e-9 Gy/POT × 6e15 POT/yr (Mu2e nominal) ≈ 9 MGy/yr.
Order-of-magnitude consistent with Stickman design point (peak dose drives
~10 DPA/yr per [[dpa-scoring]] — different quantity, similar magnitude
class). Real DPA needs NIEL channel ([[bo-prodtarget]] §"Path B").

## Noise floor (measured 2026-06-09)
pt001 + pt002 are noise replicates at the baseline x_point (3.87, 3.35,
3.47, 7.83, 6.04, 4.38, 8.33, 6.54, 4.88, N=33):
| config | files | total_pot | mu_per_POT | edep_per_POT_MeV |
|---|---|---|---|---|
| pt001 | 36/100  | 180k | 2.161e-3 | 421.90 |
| pt002 | 92/100  | 460k | 2.174e-3 | 421.67 |

- σ(mu_per_POT)/μ ≈ 0.6% (pt001 was harvested off only 36 jobs due to
  [[poll-deadlock-missing-outstage-dirs]]; pt002 is full 92).
- σ(edep_per_POT_MeV)/μ ≈ 0.05% — edep is essentially noise-free at this
  job budget. Sets a useful lower bound for BO acquisition resolution.
- Implication: 92 jobs × 50 evt = 4600 evt is more than enough on the edep
  axis; could probably halve njobs for the same edep precision. mu axis
  is the binding constraint for noise budget (still ≪ 8% calo noise of
  the foils campaign — [[bo-noise-budget]]).

## Open questions / TODO
- **Objective**: stopped-muons-per-POT (needs full POT→mubeam→muStops chain
  per evaluation — very expensive) vs pion flux at PS exit (cheap proxy).
  Cost-vs-fidelity decision is the gating question.
- **Engineering envelope**: max/min on `numberOfPlates`, `plateThickness`,
  `rOut`, `plateLugThickness` set by the Stickman mechanical design — need
  the docDB / thermal study. Current bounds are placeholders.
- **Whether to run inside [[closed-loop-bo-design]]** (multi-round
  GP-refit) or as a single Sobol sweep first to scope. Closed-loop has
  several gotchas ([[barrier-false-positive-round1]],
  [[closed-loop-thread-id-checkpoint-collision]],
  [[foilsx04-all-preflight-ambiguous]]) — a Sobol scoping pass would
  surface those before committing to multi-round.
- **`plateMaterial` v2**: small categorical (W, Ta, Inconel718) with
  potential `[W, W, …, Inconel, Inconel]` upstream/downstream split.
  Adds discrete dimensions — needs a BO variant that handles mixed
  cat+continuous.
