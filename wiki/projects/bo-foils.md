---
type: project
title: bo-foils — 5D extras-only stopping-target foil-stack BO
description: 5D BO over +12 extras (≤6 upstream, ≤6 downstream) of the 37-foil stopping-target
  base; no helical plug
status: active
status_note: (v3-only picker since 2026-06-06; foilsf01/02/03/06/07/08/09/10 complete
  + honest foilsf11/12/14, sob front 3.88→3.90 pre-fix and 3.85 honest plateau,
  SATURATED)
timestamp: '2026-07-17'
updated_note: foilsf17 broke honest ceiling 3.83→3.91, Pareto-dominant; NOT saturated
---

# bo-foils — 5D extras-only stopping-target foil-stack BO

## Honest-only sob ceiling — NOT saturated; foilsf17 broke 3.83 → 3.91 (2026-06-18)
Cumulative best sob by round end (honest qnehvi campaigns, calo>0):

| cohort | n | best sob | Δ |
|---|---|---|---|
| foilsf11R00 | 10 | 2.84 | — |
| foilsf11R01 | 20 | **3.81** | +0.97 |
| foilsf14R00 | 30 | **3.83** | +0.02 |
| foilsf14R01 | 40 | 3.83 | 0 |
| foilsf17R00 | +10 | 3.44 | (explore) |
| foilsf17R01 | +10 | **3.91** | **+0.08** |

**Verdict RESOLVED 2026-06-18: NOT saturated.** Two more rounds in the correct
`--mode foilsf` (foilsf17, qnehvi q=10 × 2) produced a new champion
**`foilsf17R01_07` sob=3.91 @ calo=2.08e-5**, which **Pareto-dominates** the old
`foilsf14R00_06` (3.83 @ 2.34e-5) — higher S/√B *and* lower calo. The gain
landed in R1 (exploit), exactly where the GP-honest envelope (sob_max≈4.06)
predicted headroom; the n=40 "4 cohorts is too few" caution was correct, the
front was NOT closed. Residual headroom toward ~4.06 may remain (foilsf18 could
test). NOTE: the honest cloud renderer's `re.match("foilsf1[14]")` filter still
EXCLUDES foilsf17 — widen it to include foilsf17 (same post-tarball-fix honest
holes) before the slide-4 champion will reflect 3.91. **Mode trap that delayed
this:** foilsf15/16 were launched `--mode foils` (v2) by mistake and never
touched this v3 search — see [leaderboards](/datasets/leaderboards.md) prefix≠mode gotcha.

**foilsf17 lifted the WHOLE honest front, and the top is geometrically diverse
(2026-06-18).** Recomputed honest-set (foilsf1[147], calo>0, n=60) calo-budget
champions — foilsf17 improved every budget, not just the max: ≤1e-6 0.58→**0.78**
(foilsf17R00_06), ≤1e-5 knee 2.02→**2.88** (foilsf17R00_03), unconstrained
3.83→**3.91** (foilsf17R01_07). Honest top-3 = foilsf17R01_07 (3.91, up
rOut112/rIn20/hT0.063, dn SOLID rOut110/hT0.145) > foilsf14R00_06 (3.83) >
foilsf11R01_05 (3.81). **This RETIRES the earlier "top-of-front converges to one
geometry family, upstream hT pinned at 0.050 mm" claim** (that was the pre-fix
tainted-hole foilsf03/06/07 era): the honest top-3 are geometrically diverse
(rOut 50→112, hT_up 0.063→0.095, the champion has a small upstream hole + SOLID
downstream discs f_dn=0). The single-family story was an artifact of the 0.05
hT-floor + tainted holes, not a real ridge.

**foilsf18 (2 more qnehvi rounds, 2026-06-19) did NOT beat 3.91 — but it's WEAK
evidence for saturation.** foilsf18 best = 3.44 (R01_07), *far* below the 3.91
champion; its picks clustered in the low-calo front (e.g. 1.31e-5 @ 3.32), i.e.
qNEHVI spent the budget **mapping the Pareto front, not re-exploiting the
high-sob corner** — so the champion's neighborhood was barely retested. Champion
unchanged: foilsf17R01_07 3.91. **To actually test whether 3.91 is the ceiling,
use the sob-only `qlnei` picker** ([qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)) which climbs sob
instead of spreading HV; a multi-objective qnehvi campaign is the wrong tool for
confirming a sob-max ceiling once the front is already mapped.

**Is the 3.91 champion real or a fluctuation? (selection-effect analysis, 2026-06-23.)**
3.91 is **6.3σ above the next-9 cluster mean (3.812, std 0.0155)** — and the cluster
std ≈ the measurement σ(sob) (~0.0156), so they coincide. Two readings:
(1) it's a real geometric optimum — then 6.3σ is fine (a 6σ *signal* is normal; only
a 6σ *noise* fluctuation is rare). (2) it's an up-fluctuation of a ~3.84 geometry —
that needs +4.5σ vs the runner-up, p≈3e-6, very unlikely. **BUT** the champion was
chosen as the MAX over ~160 BO evals: the expected max of 160 Gaussians is already
~2.5–2.8σ above the mean BY CHANCE (look-elsewhere/selection effect), so "6σ ⇒
definitely real" is too strong — the honest excess is ~3.5σ BEYOND the ~2.7σ
selection floor. Verdict: **probably a real optimum (pure-noise disfavored), but a
single unconfirmed point far above a tight 3.79–3.84 cluster → warrants a
confirmation re-run** (replicas of foilsf17R01_07, average). Same posture as the
prodtarget6d champion (+1.2 Poisson-σ over runner-up, "unresolved, confirm first").
Corrects the earlier loose "~5σ, too far to be noise" phrasing below.

**The 3.91 champion is a LONE OUTLIER above a 3.82 cluster (2026-06-23, n=160).**
Honest-set sob: max 3.91 is the ONLY row ≥3.88; the next nine are 3.79–3.84
(top-10 mean 3.822, std 0.033). So foilsf17R01_07's 3.91 sits ~5σ(sob) (σ≈0.4%≈
0.015) above the cluster mean — too far to be cluster noise, but as a SINGLE
measurement it carries its own ±0.015, so its true value is plausibly ~3.89–3.93.
**Empirical ceiling ≈ 3.84–3.91, no evidence of a real mean above ~3.84 except
that one point.** The pareto_sob run ([pareto-sob-picker](/concepts/pareto-sob-picker.md)) building the GP's 20
best-bet geometries measured ≤3.84 — bounds the achievable max well below the
cloud's spurious 4.22 GP-extrapolation ([gp-cloud-rendering](/concepts/gp-cloud-rendering.md)). Implication: a
high-stats re-measurement of foilsf17R01_07 would be worth it to confirm 3.91 is
real vs an up-fluctuation of a ~3.84 geometry.

**Wider honest set (140 rows, foilsf11–23, calo>0; 2026-06-22) — knee moved up.**
The honest calo-budget champions on the full post-fix set: ≤1e-6 **0.78**
(foilsf17R00_06, unchanged), ≤1e-5 **knee 3.06** (foilsf22R01_01, up from 2.88 —
upstream ring rIn82/rOut178/hT0.242, downstream solid disc rOut159/hT0.329),
unconstrained **3.91** (foilsf17R01_07, unchanged). So ~78% of max signal by
calo≤1e-5 (was ~74%). Honest cloud filter widened `foilsf1[147]`→`foilsf(1[1-9]|2[0-3])`
in `gp_predict_foils_v2v3_cloud.py:76`; deck slide-5 knee row updated.

**SATURATION CONFIRMED at sob=3.91 (2026-06-19, foilsf19 qlnei).** The dedicated
sob-climbing picker (qlnei, calo dropped) independently hit **3.91**
(foilsf19R00_00 AND R01_00) and could NOT beat it — reached it already in R0,
plateaued in R1. Two independent campaigns × two pickers now converge on the
same max: foilsf17 (qnehvi) 3.91, foilsf19 (qlnei) 3.91. **Verdict: the
honest-hole front IS saturated at sob≈3.91**; the foilsf18 "weak evidence"
caveat is resolved (foilsf18 just wasn't probing the corner, as predicted).
Pareto champion remains the qnehvi foilsf17R01_07 (3.91 @ calo 2.08e-5); qlnei
rows are sob-only (calo=0).

**Why the "best three" are geometrically DIVERSE despite saturation (2026-06-19).**
"Saturated" = the front stopped *advancing*, NOT a unique optimum. The top is a
flat/degenerate plateau because: (1) the 12 BO'd extras are a sub-dominant
perturbation on the pinned base-37 (shallow sob landscape over extras geometry);
(2) parameter sloppiness — stiff vs sloppy knob-combinations, sob ~flat along
sloppy directions; (3) σ(sob)≈0.4% ([bo-noise-budget](/concepts/bo-noise-budget.md)) makes the 3.81–3.91 top
cluster only a few σ apart → the ranking among the top-3 is partly noise (cf the
prodtarget champion +1.2 Poisson-σ over runner-up); (4) it's a Pareto front
(curve), so "top-3 by sob" just samples 3 points near the high-sob end at
different calo→different geometry. **Operational upshot: the optimum is robust
(engineering freedom). To actually DISCRIMINATE the flat-top geometries you must
lower σ(sob) with more events/config — NOT more BO rounds** (more rounds just
re-sample the plateau).

**AUDITED not-a-bug (harvest/metric side, 2026-06-27 agent).** Checked whether the
diverse-geometry/same-sob top is a config/metric artifact rather than physics:
sob is strongly geometry-sensitive — full honest range **0.56–3.91** (median 2.99),
monotonic in hT (thin 3.52→thick 2.33), rOut (100–150mm 3.61→200–250mm 2.33),
hole-f (0.1–0.3 →3.15, 0.7–0.9 →2.46); ce_seen/muminus_stops/calo track geometry
per-config; harvest attribution clean (each config reads its OWN /pnfs outstage
cluster — sampled 3 distinct cluster IDs, no rename-race/thread-collision); the
[harvest-denominator-bug](/incidents/harvest-denominator-bug.md) loss-aware denominator fix is in place. So the flat
top is a genuine optimum plateau, not metric insensitivity/mis-attribution.
**Config-BUILD fidelity also audited clean (2026-06-27 agent):** geom files encode
each config's DISTINCT geometry (holeRadii↔f exact to all digits, geometries differ
sharply between configs, no name-swap); foilsf is STRUCTURALLY IMMUNE to the
[foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md) silent-uniform-hole bug because
it emits a **poison-pill scalar `holeRadius=1.0e6`** (bo_driver.py
~:793) alongside the real per-foil vector — a fallback worker CRASHES loudly in
G4Tubs instead of silently building uniform holes; per-config ce_seen/mu_stops
differ → distinct builds. Caveat: the exact historical top-10 dirs (foilsf17/11/
PS01) were deleted in the /data cleanup so were traced via the identical in-flight
foilsf26 code path, not directly. **Both build AND harvest sides clean → flat top
is genuine degeneracy, not a config-switching bug.**

**Quantified — which knobs are STIFF vs SLOPPY (n=200 honest, 2026-06-27).**
Per-knob corr with sob, and how much of the search box the top-10 occupies:
| knob | corr(sob) | top-10 box-usage | verdict |
|---|---|---|---|
| hT_up | −0.63 | **9%** | STIFF — must be thin |
| hT_dn | −0.68 | **10%** | STIFF — must be thin |
| rOut_dn | −0.62 | 19% | fairly stiff (wide disc) |
| rOut_up | −0.59 | 35% | moderate |
| f_up (hole) | **+0.07** | 27% | **SLOPPY — sob ~independent** |
| f_dn (hole) | **+0.12** | 38% | **SLOPPY — sob ~independent** |
So the "large parameter spread" across the top-10 is **concentrated in the SLOPPY
knobs** (hole fractions, ~zero correlation → float freely 0–0.36; that's why some
top configs are solid discs, others big-hole) while the STIFF knobs (thickness,
both ~thin, 9–10% of box) are tightly pinned. sob is set by an AGGREGATE (thin +
right radial band of material), so (rOut,hT) trade-offs cancel → many distinct
geometries hit the same sob. The optimum is a broad MANIFOLD, not a point.

**Updated (older):** 2026-06-15

> **⚠ 2026-06-12 — hole knobs were physically inert in ALL v2/v3 rows.**
> No holeRadii-vector patch ever existed (the "patched lib" comments in
> `FoilsMode._geom_text` were aspirational); every grid job built every
> foil — base AND extras — with the scalar `holeRadius = 21.5` regardless
> of `f_up`/`f_dn` (rIn_up/rIn_dn). The 297 v3 rows are self-consistent
> measurements of the **hole-21.5 family**: the sob≈3.89 plateau is real
> for that family and the (rOut, hT) conclusions stand, but the f/rIn
> leaderboard columns describe geometry that was never built — champion
> descriptions like "ring rIn=29.1" (deck slides 5-7) are wrong; actual
> holes were 21.5 everywhere. The GP learned ~zero signal on the f dims
> (no bias, just two wasted dimensions). Root cause + detection chain:
> [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md) +
> [preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md). Whether per-foil holes can beat
> 3.89 is now an OPEN question pending the patched tarball.
> **Empirical confirmation (2026-06-13 pair test):** 694 row-pairs nearly
> identical in (rOut_up, rOut_dn, hT_up, hT_dn) (normalized L2 < 0.05)
> but with |Δf| up to 1.9 show median |Δsob| = 0.26% (below the 0.4%
> replicate noise) and median |Δcalo| = 0.0% — f from ~0 to ~0.95 (up to
> ~90% of foil area, had holes been real) measurably changed NOTHING.
> Inertness is proven from the data itself, independent of the code
> evidence. Corollary: the calo-budget-table champions' hole labels
> (deck slide 5 "solid disc" vs "thin ring") are picker-assigned noise —
> which row wins a budget bin is decided at the 0.2% level, so n=3
> champions cannot carry an f-vs-calo trend. Dataset-level check:
> Spearman(f_up, calo)=+0.075, Spearman(f_dn, calo)=−0.081 (null σ≈0.058,
> opposite signs) — zero association; mean f by calo regime is flat
> (clean 0.33/0.53, knee 0.48/0.63, uncon 0.52/0.50, n=11/184/101). The
> apparent champion pattern ("solid disc at clean, thin ring at knee")
> is bound-railing: with a flat posterior on f the acquisition parks the
> coordinate at its bounds (knee champion f_dn=0.95 is exactly F_MAX),
> producing dramatic-looking but meaningless hole labels.
> **Salvage APPLIED 2026-06-13**: all 346 v3 rows relabeled in place
> (`f = 21.5/rOut` per side; backup at
> `leaderboard_bo_foils_v3.tsv.bak-prerelabel-20260613`). Since
> rOut ≥ 50, relabeled f ≤ 0.43 — the f ∈ (0.43, 0.95] region is
> completely unexplored. **foilsf11 launched** (qnehvi — multi-objective
> WITH run1b/calo, deliberately not qlnei, to measure the hole-calo
> response; q=10, max-rounds=2, pid 1409629): the first foilsf campaign
> with physically real holes, on the patched tarball + 4-layer preflight.
> **R0 confirms the salvage worked**: relabeled history sits at f≤0.43,
> and qNEHVI's R0 picks span rIn 0→237.5 mm (f 0→0.95=F_MAX) — R00_05
> up-f=0.95, R00_03 up-f=0.87, several solid discs (rIn=0). The
> previously-blind hole axis is being swept for the first time; all 10
> R0 children passed the 4-layer preflight and archived as-built GDML.
> **R0 result (10/10, clean barrier — no orphans under pt6d contention,
> the liveness-wait fix working): top sob=2.84** (R00_07 f_up=0.60/f_dn=0,
> rOut=250 thick-ring exploration corner) — whole round ≤2.84, below the
> 3.89 plateau as expected for qNEHVI exploration. **Key physics signal:
> with real holes, calo now spans 1.4e-6→2.4e-5 (17×) and tracks the
> hole pattern** (R00_08 solid-up/big-down-hole: calo 1.4e-6 sob 0.79;
> R00_05 f_up=0.95: calo 2.4e-5) — vs the inert-f era where calo was
> pinned regardless of f. f is now a real signal/background lever; the
> R1 exploit round (last, max_rounds=2) tests whether it beats 3.89.
> **VERDICT (foilsf11 complete 2026-06-13, 20 evals): real holes do NOT
> help — the optimizer drives f→0.** R1 best sob=3.81 at **f_up=0,
> f_dn=0 (solid foils)**, rOut_up=50/rOut_dn=110, hT_up=0.095/hT_dn=0.186;
> calo 2.31e-5. Every high-f pick scored worse: f_up=0.95 picks landed
> sob 2.96–3.27. So given a free choice across f∈[0,0.95], qNEHVI removes
> the holes for best signal and large holes cost ~15% sob. 3.81 in 2
> rounds is within ~2% of the 3.89 plateau (would close with more
> rounds). **Conclusion: the 21.5 mm holes in the inert-f "champions"
> were never helping — they were neutral baggage; the real levers are
> rOut + hT, and solid foils are optimal.** This retroactively explains
> the earlier "no-hole at clean / hole at knee" champion pattern as
> acquisition bound-railing on a flat f-posterior, NOT physics. The
> max-significance geometry question is now settled on honest geometry.
> **CONFIRMED by an independent picker (foilsf12, qlnei sob-only,
> 2026-06-13):** R0 explored the high-f corner (qlnei noisy-EI: 10 picks
> at f_up=0.95/rOut=50, sob 3.15–3.38), then **R1 refit and pivoted to
> low f (0.0–0.2), jumping to sob=3.85** at the rOut≈90–115 / hT≈0.06–0.08
> champion family (R01_03: f_up=0.16/f_dn=0, sob 3.85). qlnei
> independently reaches foilsf11's qNEHVI conclusion (f→0, 3.81): minimal
> holes, classic geometry, ~3.81–3.85 just under the 3.89 plateau. The R0
> high-f picks were exploration, NOT a real picker disagreement.
> (foilsf12 ran qlnei because qNEHVI now times out on the post-fix
> non-degenerate calo front — see [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md).)
> **Salvage path (rationale, recorded before application):** every v3 row
> is a VALID measurement of the corrected geometry at `f′ = 21.5/rOut`
> (that's what was actually built). Relabeling `f_up → 21.5/rOut_up`,
> `f_dn → 21.5/rOut_dn` (y untouched) converts all 297 rows into honest
> training data concentrated on a 1-D slice of f-space — unlike the raw
> rows, which teach the GP the now-false claim "f has no effect" and
> suppress qlnei's f-exploration. Do the relabel BEFORE any post-fix
> foilsf campaign. (foilsg has no such salvage: its 12-D rows collapse
> many-to-one onto the uniform-hole manifold via the group-size-weighted
> mean, so per-row inversion is ambiguous — hence the .broken.tsv
> quarantine there.)

(**foilsf08 + foilsf09 COMPLETE** 2026-06-09: foilsf08R00 first qlnei live run crashed all 10 children at SqliteSaver.put_writes — root-caused to cmd_evaluate rejecting calo=None when AUTORESEARCH_NO_RUN1B=1 (see [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md)); fixed at `bo_driver.py:1338`; foilsf08R00 10 configs recovered via direct CLI evaluate (sob 3.75-3.89, calo=0 since run1b_mubeam dropped). **foilsf09 (qlnei, 2 rounds × 10 = 20 evals) clean end-to-end**: R0 sob 3.87-3.90, R1 sob 3.88-3.89 — qlnei picker now validated, and the 7th saturation campaign confirms front pinned at sob ≈3.88-3.89 with no calo channel.) (**foilsf07 COMPLETE** 2026-06-08: 5 rounds × 10 = 50 evals, leaderboard 247→297. New entry **foilsf07R00_00 sob=3.88 @ calo=2.15e-5** (rO_up=111.5 hT=0.060 rIn=39.0, rO_dn=114.5 hT=0.132 rIn=46.7) enters top-3 #2 (displaces foilsf06R04_04 to #3). Champion #1 foilsf03R01_09 sob=3.89 unchanged. **5 independent campaigns now saturate at sob≈3.88-3.89**; no hT<0.05 region champion despite widened floor.) (**foilsf06 COMPLETE** 2026-06-07: 5 rounds × 10 = 50 evals, leaderboard 197→247. New entry **foilsf06R04_04 sob=3.88 @ calo=2.13e-5** ties foilsf02R00_03 for top-3 #2. Champion #1 foilsf03R01_09 sob=3.89 still holds. **4 independent campaigns (foilsZ02/foilsf02/foilsf03/foilsf06) now converge at sob≈3.88-3.89** on the same geometry family (rOut≈115-137 mm, upstream hT≈0.05-0.10 mm, downstream hT≈0.11-0.20 mm). Picker explored widened 0.01-0.05 region: 5/50 foilsf06 picks at hT=0.010 floor (2 Sobol R00 + 3 GP-driven R01/R02), all scoring sob=2.4-3.8 (slightly worse calo at hT=0.01 than near hT=0.05); GP R01-R03 pivoted UP to hT≈0.08 confirming saturation at sob≈3.89 is genuine not bound-artefact.) (**top-3 sob convergence to single geometry family confirmed**: rank-1 foilsf03R01_09 sob=3.890, rank-2 foilsf02R00_03 sob=3.880, rank-3 foilsZ02R07_02 sob=3.870 — all within 0.5%, picked across 3 independent campaigns (foilsZ02/foilsf02/foilsf03), all with **upstream hT pinned at lower bound 0.050 mm**, rOut ≈ 115–137 mm, downstream slightly thicker (0.11–0.14 mm). The 0.05 floor was set at `bo_driver.py:913` `Real(0.05, 1.0, name="extra_halfThickness_up")` — chosen to sit just-below base hT=0.0528 mm (line 668), NOT physics-motivated. Upstream is binding (extras degrade beam → less mass = less scatter/early-stop = higher S); downstream is non-binding (picker chose 0.11–0.14, the floor doesn't bite). **2026-06-06: hT floor LOWERED 0.05 → 0.01 mm on BOTH FoilsMode (lines 729-730) and FoilsFracMode (lines 913-914)**. **2026-06-07 followup: foilsf05 (post-floor-change, 197 total rows after R00+R01) made ZERO picks below hT=0.05; two picks LANDED at hT_up=0.050 exactly (the old floor)** — the GP didn't refuse to go lower, it actively chose to STAY at the boundary because the training data says that's where champions are. Root cause is NOT "no data → no gradient" NOR length-scale rail-out NOR batch-diversity — those were red herrings. **ACTUAL ROOT CAUSE (2026-06-07 subagent investigation): bounds are duplicated between `bo_driver.py:913-914` (FoilsFracMode.build_space, the BO-mode declaration) AND `botorch_predict.py:74` (MODE_SPECS["foilsf"]["lo"], the qLogNEHVI picker's `optimize_acqf(bounds=...)` argument).** I edited only the first file when widening 0.05→0.01; the second file is STALE at 0.05. `optimize_acqf` therefore physically cannot propose hT<0.05 — the two picks at hT_up=0.050 EXACTLY are the picker hitting its (stale) lower bound, not "the GP choosing to stay." `Normalize(bounds=bounds)` at `botorch_predict.py:147` also uses the stale bounds. **Fix:** sync `botorch_predict.py:74` `[0.05, 0.05]` → `[0.01, 0.01]` to match `bo_driver.py:913`. **Lesson: MODE_SPECS in botorch_predict.py is a SEPARATE source-of-truth for picker bounds; any build_space() change must be mirrored there.** **VERIFIED 2026-06-07: post-fix campaign foilsf06 round-0 immediately picked 2 of 10 at hT_up=0.010 EXACTLY (the new floor) — foilsf06R00_01 sob=3.78 @ 2.17e-5 and foilsf06R00_07 sob=3.79 @ 2.28e-5. Confirms (a) picker now respects widened bound, (b) low hT IS a real Pareto-front region (not a dead zone), but (c) those first qLogNEHVI picks at hT=0.01 trade slightly higher calo for similar sob — not yet beating the 3.89 champion. **R01 GP refit (with hT=0.01 evidence now in training data) PIVOTED UP to hT_up ~0.08, NOT further down** — top R01 picks foilsf06R01_00 sob=3.86 @ 2.12e-5 (hT_up=0.078) and foilsf06R01_04 sob=3.85 @ 1.94e-5 (hT_up=0.086). Interpretation: the GP, after seeing the slightly-worse calo at hT=0.01, learned that **0.05 was already near-optimal** and is now searching slightly ABOVE it. Strong evidence the original 0.05 floor was not leaving sob on the table; saturation at sob≈3.89 is genuine (not a bound artefact). **What this does NOT prove:** that hT<0.05 is a dead region — only that the GP+acquisition extrapolation didn't find it interesting. **To actually test the new region needs a Sobol-seeded restart (or explicit init_points within [0.01, 0.05]) to deposit training data there.** Safe wrt history: each leaderboard row stamps its own hT at submit time (line 858), so old rows unchanged; GP refit absorbs new bounds without bias. **foilsf04 in flight at change time (pid 3786214) snapshotted old bounds at startup — it will finish under 0.05 floor**; clean cutover at next `--name-prefix` launch. CAVEAT: 10 µm Al may be unbuildable; treat any new champion at hT≤0.03 as physics-real-but-unbuildable until engineering confirms. Strong evidence the optimum is real, not single-run artefact; front is **flat at the top** so all three are operationally equivalent. Added as slide 7 "Top 3 by S/√B" to `docs/foils_talk.md`. foilsf03 complete 2026-06-06 ~20:50: 2 rounds × 10 = 20 evals, leaderboard 136→156. **NEW unconstrained sob champion: foilsf03R01_09 sob=3.890 @ calo=2.03e-5** — edges out prior foilsf02R00_03 (sob=3.88 @ 2.2e-5) AND at lower calo. Marginal +0.01 sob, ~10% calo reduction — front genuinely tightening at the unconstrained corner. Calo-budget table champions for B≤1e-6 and B≤1e-5 UNCHANGED (still foilsf01R03_04 0.73 and foilsZ06R00_04 2.90); the gain is corner-only. POLICY FLIP: foilsf picker is now v3-ONLY. `FoilsFracMode.load_priors` at `bo_driver.py:854` returns `[]` — v1 prior + 54 v2 evals intentionally NOT loaded. Operator direction: v2's rIn≤50 regime was suspected of dragging v3 GP toward v2 average; v3-only cloud envelopes the gold stars while v2+v3 does not. Trade-off accepted: GP is under-identified (length_scale rails to 1000 mm upper bound on 67-row v3-only fit); cloud is a diffuse blob — see revised [gp-cloud-rendering](/concepts/gp-cloud-rendering.md). **NEW v3 CHAMPION 2026-06-06**: `foilsf01R04_07` obj=**2.040**/sob=**3.54**/calo=1.50e-5 (f_up=0.49, f_dn=0.32, rOut_up=141.8, rOut_dn=141.3, hT_up=0.130, hT_dn=0.197) — first v3-only-trained pick to top the v3 leaderboard, beating prior champion foilsZ02R02_02 (obj=2.017/sob=3.40, v1+v2+v3 trained). Modest +1.1% obj gain across 5 rounds × 10 children = 50 evals; sob front advanced 3.40→3.54. v1/v2 leaderboards FROZEN. foilsZ07 (v2-leaderboard, 19 rows landed) killed 2026-06-06; foilsf01 ran thread closed-d2b73f22. Naming convention break: foilsZ prefix does NOT enforce v3 mode — check parent's `--mode` flag.)

## Summary
Third BO mode in `bo_driver.py` (select with `--mode foils`).
Opens a parallel BO line over the **stopping-target** foil stack, orthogonal
to [bo-helical](/projects/bo-helical.md)'s plug optimization. Motivation: 4D helical Pareto has
saturated (HV +1.6% over last 76 evals, hit-rate 62%→38%), so the next win
is a dimensionality lift, not more 4D evals. This mode pins the deployed
37-foil base (see [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md)) and explores adding
up to 6 extras upstream and/or 6 downstream — `n_up + 37 + n_down` total,
all extras sharing one (rOut, halfThickness) triple. The helical plug is
**off** (`tsda.helical.build = false`, `hasTSdA = false`) so any movement
in (sob, calo) is attributable to the +12 envelope alone.

## Key facts

- **"Extras identical to the default foil" is predicted +0.25 sob but Pareto-DOMINATED
  (2026-06-26, GP).** Setting the 6 extra knobs to the deployed base-foil values
  (rOut=75, halfThickness=0.0528 mm, hole f=21.5/75≈0.287 — i.e. just add 12 more
  standard foils) → GP-predicted **sob 3.55 ± 0.03** (σ tiny, point is in-data) at
  **calo 2.35e-5**. That beats the bare 37-foil base (~3.3 nominal Run1A) — more
  stopping material → more stops → more signal — but: (1) it's only ~40% of the
  available gain (optimized extras = champion 3.91), and (2) its calo (2.35e-5) is
  HIGHER than the champion's (2.1e-5), so it's **dominated** on the (sob, calo)
  front. The f=0.287 hole + rOut=75 base shape is wrong for the extra positions;
  BO prefers thin annuli at larger rOut. Concrete "why optimize vs duplicate" point.
- **Foil-to-foil z-spacing is NOT a BO knob.** `_geom_text`
  (`bo_driver.py:602-647`) emits only the `radii` and
  `halfThicknesses` vectors and inherits foil pitch from
  `Offline/Mu2eG4/geom/geom_run1_a.txt` via the include at line 625;
  `StoppingTargetMaker` distributes N foils on that single deployed
  pitch. So `n_up=6, n_down=6` means "6 extras continuing the base
  pitch upstream + 6 continuing it downstream," NOT arbitrarily placed.
  Stack-spacing as a parallel BO line is flagged in the deck's
  open-questions slide but unimplemented.

- **Search space (5D extras-only, locked):**
  - `n_up`                 ∈ Integer[0, 6]
  - `n_down`               ∈ Integer[0, 6]
  - `extra_rOut`           ∈ Real[50, 250] mm  (floor at 50 per operator decision; 80 was initial)
  - `extra_halfThickness`  ∈ Real[0.05, 1.0] mm  (half-thickness; full = 2×)
  - `extra_rIn`            ∈ Real[0, 50] mm
  - Source of truth: `bo_driver.py:FoilsMode.build_space`.

- **Base 37 foils pinned at deployed v02 spec** (NOT the documents-spec
  "100 µm" number — see [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md) for the
  deployed-vs-design mismatch):
  - `BASE_ROUT_MM = 75.0`, `BASE_HALFTHICK_MM = 0.0528` (≈105.6 µm full),
    `BASE_HOLE_RADIUS_MM = 21.5`, `BASE_N_FOILS = 37`.

- **`extra_rIn` is necessarily a GLOBAL override.** `stoppingTarget.holeRadius`
  is a single scalar at `StoppingTargetMaker.cc:41` (getDouble) — applies to
  every foil, not per-foil. So when `n_up + n_down > 0`, the emitted
  `holeRadius = extra_rIn` overrides the base 21.5 globally. When
  `n_up == n_down == 0`, emission of holeRadius is skipped and the v02
  include's 21.5 survives. `is_buildable` rejects `rIn >= BASE_ROUT_MM` to
  avoid vanishing the base annulus.
  - **2026-05-29 round-trip fix** (`bo_driver.py:696`):
    `parse_geom` previously returned `extra_rIn = 0.0` when no
    `holeRadius` line was present, but that's exactly the corner where
    the v02 baseline 21.5 mm is in force. Result: round-trip
    `render_proposal → parse_geom` corrupted the no-extras corner from
    21.5 → 0.0, biasing any leaderboard re-load and `cmd_show_priors`-
    style audits. Fix: fall back to `self.BASE_HOLE_RADIUS_MM` when the
    regex misses, matching what `_geom_text` actually emits.

- **Phase 0 preflight result (2026-05-28):** all three extreme-corner
  configs PASS:
  - `foilsP0_AU` (n_up=6, n_down=0, rOut=250, hT=1.0, rIn=50) → 43-entry radii
  - `foilsP0_AD` (n_up=0, n_down=6, rOut=250, hT=1.0, rIn=50) → 43-entry radii
  - `foilsP0_AS` (n_up=6, n_down=6, rOut=250, hT=1.0, rIn=50) → 49-entry radii
  - All `total_hits=1 baseline=1 managed=0` — no `StoppingTargetFoil_*` in
    managed-overlap output. The full 5D box is buildable; no defensive
    clamp on search space needed.
  - Logs: `bo_foils_preflight/foilsP0_{AU,AD,AS}.log`.

- **No mmackenz priors** (see [mmackenz-priors](/datasets/mmackenz-priors.md)). mmackenz's v22-v50 foil-stack runs (consumed by
  [bo-michael](/projects/bo-michael.md)) are 7D over different knobs (rIn / halfLength4 / holeRadius
  / col5) and don't project onto this extras-only space. In **v1 (5D)**
  `load_priors` returned `[]` outright.
- **v1→v2 prior reuse (6D migration, uncommitted WIP 2026-06-01):** v2
  `FoilsMode.load_priors` no longer returns `[]` — it projects the
  **n_up==6 AND n_down==6 subset of `leaderboard_bo_foils_v1.tsv`** into the
  new 6D space. Of **251 v1 rows, exactly 51 qualify** (the other 200 have a
  different foil count and are silently dropped — their geometry has no v2
  representation). Each qualifying v1 row had a single *coupled* extras triple,
  so it lands on the **up==dn diagonal**: `x = [rOut, rOut, hT, hT, rIn, rIn]`.
  Both v1 champions (`foilsX07R01_03`, `foilsX08R04_08`) are in the 51, so the
  v2 GP starts knowing the best v1 regions — but the **off-diagonal (up≠dn)
  half of the space is unseeded**, which is the whole point of going 6D. These
  51 enter as priors in BOTH picker paths (`seeds = priors + history` in
  `botorch_predict.py`; same in the sklearn `cl_min` shim) — without them a
  fresh v2 run with an empty `leaderboard_bo_foils_v2.tsv` has nothing to fit.

- **Empty-history bootstrap (gp_predict_foils.py):** because there are no
  priors and `BOMode.build_optimizer` uses `n_initial_points=0`, the
  closed-loop GP picker on round 0 builds its own Optimizer with
  `n_initial_points=q` (Sobol-seeded) — otherwise skopt raises
  "Random evaluations exhausted and no model has been fit". Smoke
  (`--mode foils --q 2 --max-rounds 1 --dry-run` on 2026-05-28) produced 2
  spatially-distinct picks across all 5 knobs.

- **Parallel strategy:** `cl_min` (matches [batch-bo](/concepts/batch-bo.md) helical default).
  skopt's `cl_mean` warns about fake-y collapse with mixed Integer+Real
  spaces — `cl_min` uses the running minimum which is more
  collapse-resistant for the n_up/n_down Integer dims.

- **Closed-loop wiring (Step 4 complete 2026-05-28):**
  - `graph/state.py:32` Literal extended to `["helical", "michael", "foils"]`.
  - `graph/closed_loop.py:_import_gp(mode)` dispatches on mode arg; threaded
    through `node_predict_picks`, `node_refit_and_check`, `_dry_run`.
  - `graph/pipeline_io.py:mock_metrics` widened to accept 5D x; uses
    `_FOILS_KNOB_RANGES` and dim-agnostic `u[-2] * u[-1]` for the calo
    "more-material" direction.
  - New `gp_predict_foils.py` shim in `mmackenz_table_plots/`.

- **Side-fix:** HelicalMode `FOIL_COUNT = 38 → 37` at
  `bo_driver.py:379` (2026-05-28) — matches deployed
  v02 base. Pre-existing helical leaderboard rows unaffected (each
  config carries its own geom snapshot).

- **foilsf14 honest-hole qNEHVI campaign (2026-06-14, +20 rows,
  386→406):** qNEHVI mapped the calo trade-off cleanly; R0 spread
  the front (sob 1.66 at calo 3.9e-6 through sob 3.08 at calo 1.8e-5),
  R1 picked the picker-favored corner (best sob = 3.21 at large holes
  `f_up=f_dn=0.95`, calo 2.4e-5). **R1 best sob 3.21 is BELOW the
  foilsf12 qlnei honest plateau of 3.85** — qNEHVI prioritized the
  calo-cheap end and never returned to the no-hole champion family,
  consistent with `f` being weakly informative and the multi-objective
  acquisition spending budget on diversity rather than peak sob.
  Verdict: peak champions remain foilsf12 (sob 3.85 at minimal holes);
  foilsf14 adds confidence to the calo Pareto curve.

- **Why R1 didn't re-pick near the R0 sob=3.83 needle (2026-06-15
  post-hoc):** three compounding reasons, useful when reading any
  qNEHVI campaign that lands one outlier champion and then walks away
  from it. (a) qNEHVI maximizes HVI not sob — once foilsf14R00_06
  joined the front, R1 gets ~zero HVI credit for resampling it; R1's
  q=10 went to f=0.95 (4 picks, sob~3.1-3.2) and f=0 low-calo end
  (3 picks at calo<1.6e-6). (b) `extra_f_up/dn` rail at
  length_scale=1000 on every v3 fit (see [gp-cloud-rendering](/concepts/gp-cloud-rendering.md)
  "Real mechanism" section): GP says f doesn't drive obj, so both
  f-corners look equally promising. (c) foilsf14R00_06 is a **single
  point**, not a basin — neighbors don't replicate, so GP posterior
  there has high mean + high variance and qNEHVI prefers front
  spread to noisy-peak chase. **If you actually want max-sob in this
  box, use qlnei** (foilsf12 is 20 qlnei evals fit on cumulative
  history=366 rows; best sob=3.85 at R01_03 with minimal holes —
  genuine local saturation given the GP's f-rail-uninformative
  fit, not necessarily a global ceiling).

- **Slide-5/6 honest-only regen (2026-06-15, n=40 = foilsf11+14
  calo>0 rows):** docs/foils_talk.md slides re-rendered against
  `gp_predict_foils_v2v3_cloud.py --honest-only` (new flag, filters
  regex `foilsf1[14]` ∧ calo>0). Honest calo-budget champions:
  | budget | sob | calo | upstream | downstream |
  |---|---|---|---|---|
  | ≤1e-6 | 0.58 | 7.3e-7 | solid disc rOut=250 hT=2.0 | ring rIn=62 rOut=250 |
  | ≤1e-5 | 2.02 | 9.0e-6 | ring rIn=135 rOut=183 hT=0.27 | solid disc rOut=175 |
  | unconstr | 3.83 | 2.3e-5 | ring rIn=8.3 rOut=55 hT=0.17 | ring rIn=8.8 rOut=105 hT=0.31 |
  At calo≤1e-5 best sob ≈ 53% of unconstrained (not the spurious 80%
  on the pre-fix uniform-disc-fallback dataset). Output PNG
  `docs/gp_predicted_foils_honest_cloud.png` (206 KB, separate from
  the cron-refreshed v3only cloud).

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md) (foilsf geometry, flash objective), [bo-helical](/projects/bo-helical.md) (parallel BO line; saturation motivated this),
  [bo-michael](/projects/bo-michael.md) (original 7D foil-stack mode this supersedes for
  extras-only),
  [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md) (load-bearing base + scalar-holeRadius
  gotcha),
  [batch-bo](/concepts/batch-bo.md) (cl_min strategy choice),
  [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (mode-generic barrier/leaderboard plumbing),
  [closed-loop-runner](/drivers/closed-loop-runner.md) (driver this rides on), [bo-foilsflash](/projects/bo-foilsflash.md), [bo-foilsg](/projects/bo-foilsg.md), [bo-ipa](/projects/bo-ipa.md), [bo-prodtarget](/projects/bo-prodtarget.md)
- Source files:
  `bo_driver.py` `FoilsMode` class (~L547),
  `bo_driver.py:379` (HelicalMode.FOIL_COUNT side-fix),
  `bo_driver.py:769` (SURFACE_OVERLAP_MANAGED regex with
  StoppingTargetFoil_),
  `bo_driver.py:790, 843` (cmd_preflight mode gate widened
  to foils),
  `graph/closed_loop.py` (_import_gp + 3 call sites),
  `graph/pipeline_io.py:mock_metrics` + `_FOILS_KNOB_RANGES`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_foils.py`,
  `botorch_predict.py` (standalone qNEHVI shim with `--mode {foils,helical}`;
  .venv-botorch; not wired into closed_loop; bounds + int-dim mask inlined
  in `MODE_SPECS` since .venv-botorch has no skopt; michael's mixed
  Real+Categorical space NOT supported),
  `leaderboard_bo_foils_v1.tsv` (created on first append)
- External: [mu2e-overlap-check](/external/mu2e-overlap-check.md) (Phase 0 preflight recipe)

- **First closed-loop round (`foilsX01`, 2026-05-28):** all 10 Sobol-bootstrap
  picks PASS preflight end-to-end through the real grid pipeline — confirms
  the +12 envelope is not just buildable at the extreme corners (Phase 0)
  but also at interior Sobol-sampled points. No managed-volume overlaps
  across any of the 10 picks. Per-child logs at
  `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/closed_loop_logs/foilsX01R00_{00..09}.log`.

- **Round 0 results (10 evals, 2026-05-28):** all 10 harvested cleanly,
  none rejected by scan_logs. Range: `sob ∈ [1.88, 3.32]`,
  `calo ∈ [8.2e-6, 2.4e-5]`, `obj ∈ [0.51, 1.55]` (α=1e5). Top by obj:
  - **R00_00**: n_up=2, n_down=4, rOut=236.6, hT=0.350, rIn=33.5 → sob=2.50, calo=9.5e-6, **obj=1.55**
  - R00_01: n_up=2, n_down=2, rOut=197.9, hT=0.339, rIn=32.4 → sob=2.81, calo=1.3e-5, obj=1.48
  - R00_05: n_up=4, n_down=2, rOut=164.5, hT=0.519, rIn=26.6 → sob=2.31, calo=9.9e-6, obj=1.32
  R00_07 (max extras: n_up=6, n_down=5, small rOut=64) gives highest
  sob=3.32 but worst-of-top calo=2.4e-5 → obj=0.94. Pattern: large-rOut /
  moderate-halfThick / mid-rIn picks dominate; max-extras-small-rOut
  trades into a worse calo penalty.

- **`numpy.int64` SqliteSaver crash (2026-05-28, foilsX01 round 0→1):**
  skopt's `Optimizer.ask` returns `np.int64` for `Integer` dims (n_up,
  n_down). closed_loop.py barrier + refit succeed, but the post-refit
  checkpoint write raises `TypeError: Type is not msgpack serializable:
  numpy.int64` in `langgraph/checkpoint/serde/jsonplus.py:_msgpack_enc`.
  Round 0 leaderboard is intact (written via flock-TSV, not the saver);
  only the round-1 state transition dies. Fix: cast Integer picks in
  `gp_predict_foils.compute_explore_picks` to native `int` before
  returning (e.g. `(int(p[0]), int(p[1]), float(p[2]), ...)`).
  Helical mode never hit this — all 4 dims are `Real`.

- **GP cloud at n=10 in 5D (`gp_predict_foils_cloud.png`, 2026-05-28):**
  Renders, but length-scales for dim 1 (`n_down`) and dim 4
  (`extra_rIn`) rail to the upper bound 1e3 — GP treats them as
  effectively flat. Honest under-training signal, not a bug.
  Predicted-cloud envelope `sob∈[1.86, 3.31]`, `calo∈[5.6e-6, 3.1e-5]`,
  82 Pareto pts. Use the rendered cloud as smoothed interpolation
  between the 10 obs, NOT for extrapolation. Re-render at n≥30 once
  more rounds land.
- **GP cloud at n=29 (foilsX01 + X02R00 + X02R01, 2026-05-28):**
  Dim 1 (`n_down`) length-scale freed up vs n=10, but dim 4
  (`extra_rIn`) still rails to upper bound 1e3 — rIn remains the
  worst-trained dim and the next to target with explicit picks.
  Frontier widened: `sob∈[0.86, 3.54]` (was 3.31), `calo∈[1.0e-6,
  3.6e-5]` (floor dropped ~5×), 97 Pareto pts.
  Renderer: `mmackenz_table_plots/gp_predict_foils_cloud.py` — must run
  under `.venv-botorch` (not `.venv-graph`; only botorch venv has
  matplotlib).
- **GIF re-render is byte-identical when leaderboard hasn't grown** (2026-05-29):
  `gp_predict_foils_cloud_anim.py` is deterministic given a fixed leaderboard.
  Running it twice with no intervening rows produces an md5-identical
  `gp_predicted_foils_cloud.gif` (frame contents AND ImageMagick stitch
  output stable). Practical: on a "remake the plot" request, check
  `wc -l leaderboard_bo_foils_v1.tsv` against last commit's row count
  before re-rendering — if equal, the re-render is wasted.

- **Marp slide rebuild via npx** (2026-05-29 update): in-place rebuild of
  `docs/foils_talk.md` → `.html` works on this host with
  `npx -y @marp-team/marp-cli@latest --html --allow-local-files
  docs/foils_talk.md -o docs/foils_talk.html`. (`--allow-local-files` is
  required for `![](relative.png)` refs to inline.) Earlier claim that
  "no marp CLI is installed" is superseded — npx auto-fetches. The
  `.html` also references the GIF by filename
  (`<img src="gp_predicted_foils_cloud.gif">` at foils_talk.html:299),
  so swapping the GIF on disk updates the served page without re-running
  Marp; only the `.pdf` goes stale and still needs an off-host rebuild.

- **Per-round GIF animation** (`gp_predict_foils_cloud_anim.py`,
  2026-05-29): renders one cumulative frame per `foils<X##>R##` cohort
  by regex-splitting leaderboard config names (leaderboard row order =
  harvest order, since flock-TSV is append-only). 4 frames at X02 end
  (10→19→29→39 evals). **Non-obvious:** Pareto-count can DROP between
  frames (97→80 across X02R01→R02) — new picks dominate old frontier
  points; the GP "moves" rather than just "extends." Output:
  `gp_predicted_foils_cloud.gif`. Run under `.venv-botorch`; uses
  ImageMagick `/usr/bin/convert` for stitching (`imageio` not installed).
- **foilsX07 saturated at R01 (2026-05-31, mid-run R05 of max-rounds=10):**
  `saturation_report.py --prefix foilsX07` on 164-eval leaderboard reports
  `R01 Δbest=+1.424 round_max=2.178` (foilsX07R01_03 the global champion),
  then R02/R03/R04 all undershoot prior_max: Δbest = −0.51 / −0.19 / −0.86;
  R03 and R04 flagged `[SAT]` against the round-1 anchor gain. 30 evals
  after R01 have not produced a new champion. **Operator implication:**
  the remaining 5 rounds (R05-R09, 50 budgeted evals) are unlikely to
  beat obj=2.178 without changing the picker or the search space. The
  closed_loop has no built-in SAT-kill gate; manual kill of pid 2475792
  is the way to stop without burning the budget.
- **foilsX03 complete (q=10, max-rounds=5, 2026-05-29):** all 5 rounds
  resolved cleanly; pareto_hash walked `a8f16932 → ddf0adc1 → b30ac643 →
  62608fc9 → 6459d20d` — 5 distinct hashes, never converged on k=2 repeat.
  50 new evals → leaderboard at 74 lines (73 data). New frontier highs:
  sob peak 3.87 (was 3.52 at X02 end), calo floor 8.3e-7 (was 1.0e-6 at
  X02 end). **Operator takeaway: 5D foils BO frontier still expanding
  at 5-round / 60-eval budget — convergence-by-hash is the wrong stop
  criterion in early phase; use HV-delta or eval-budget cap instead.**
- **foilsX02 complete (q=10, max-rounds=3, 2026-05-28):** all 3 rounds
  resolved cleanly; pareto_hash walked `6b50bc44 → e881587c → 6e15e014`
  — frontier still moving at round 2→3 boundary (no convergence by
  k=2 hash repeat). 30 new evals → leaderboard at 38 lines (37 data
  rows incl. foilsX01 R00_09 missing). np.int64 msgpack fix
  (`gp_predict_foils.compute_explore_picks` int/float cast) held
  through 3 predict_picks invocations. **Followed by foilsX03** (q=10,
  max-rounds=5, pid 29851, started 2026-05-28T23:50) — 50-eval budget
  to push past current non-convergence.

- **sob-only ridge ≠ obj ridge (n=251, 2026-06-01):** ranking by sob alone
  surfaces a different geometry cluster than ranking by joint obj. Top sob
  ties at **3.93** (foilsX08R04_08 and foilsX08R00_00, both n_up=6/n_down=6
  but rOut≈107-124, hT≈0.063-0.073, rIn≈1-4); obj-champion foilsX07R01_03
  sits at sob=3.60 with much larger rOut=160 and thicker hT=0.116. Pattern:
  the sob-maximizing ridge prefers thinner / smaller-rOut foils, which
  trade into higher calo and lose on joint obj. Operator takeaway: if a
  future question is "what maximizes S/√B alone" (e.g. CE-only physics
  case with calo deferred), the answer is NOT the obj-champion — it's
  foilsX08R04_08. Single-column sort: `awk -F'\t' 'NR>1' leaderboard_bo_foils_v1.tsv | sort -t$'\t' -k7,7gr | head`.

- **v2 6D first real-grid round PASS (`foilsY01`, q=3, 2026-06-01):** the
  6D schema ran end-to-end on the real grid for the first time — 6D geom
  built, preflight cleared, full pipeline (mubeam→run1b_mubeam→concat→
  mustops_ce→harvest), round-trip parse → `leaderboard_bo_foils_v2.tsv`
  (created on first append, 3 rows). Clean barrier, no orphans. Results
  (α=1e5): R00_01 obj=1.522 (sob=3.21), R00_02 sob=3.33/obj=1.349, R00_00
  obj=1.290 — **all well below v1 champions (obj=2.178, sob=3.93)**, as
  expected: cl_min round-0 railed every pick's downstream side to floor
  (`rOut_dn=50, rIn=0`) to probe the off-diagonal the 51 diagonal priors
  don't cover. **Physics read: all three cleared sob>2.8 with downstream
  extras collapsed → the upstream extras carry most of the S/√B signal;
  downstream contributes little at these picks.** Don't read R00 obj as
  competitive — it's information-buying about up≠ dn, not exploitation.
- **cl_min looks EXHAUSTED on the v2 6D surface (2026-06-02, strategic):**
  three consecutive cl_min campaigns have not beaten **obj=2.00**
  (`foilsY02R03_01`, itself below the v1 champ 2.178): Y02 climbed to 2.00,
  Y03 consolidated (best 1.899, no beat), **Y04 COMPLETE — per-round best obj
  1.39 / 0.68 / 1.90 / 1.96 / 1.89** (best 1.963, no beat). The R1=0.68 was a
  **transient** boundary dip, NOT a terminal collapse — cl_min escaped it on
  its own R2–R4 and recovered to the ridge. But the **plateau is now settled:
  four cl_min campaigns, none has cracked 2.00**, all topping ~1.9–2.0. The
  surface is mapped; cl_min reliably finds the ridge and reliably fails to
  exceed it. **Implication: the next lever is exploration (qnehvi) or a
  dimensionality lift (promote base holeRadius / halfThickness to a 7th knob,
  per the deck's "next steps"), NOT a 5th cl_min run.**
  - **Mechanism (diagnosed 2026-06-02 from Y04 geometry):** every Y04 pick
    railed `rOut` to **250** (the max), R1 also railed `hT` to **~1.0** — the
    big-thick-foil **boundary corner** — vs the champion's moderate rOut≈150 /
    thin hT≈0.05. The low obj is **low SOB (0.6–2.2), not a calo penalty**
    (calo is tiny there): big thick foils stop muons poorly → weak CE signal.
    This is the LIVE realization of the [batch-bo](/concepts/batch-bo.md) n=193 note ("CL-min
    spends 8/10 picks on the rOut=250, hT=1, rIn=0 boundary corner —
    mode-collapse to a GP-predicted safe extreme"), amplified by the
    running-min lie getting more pessimistic as low-obj rows accumulate.
    **NOT a prior effect** — the single filtered prior can't pull the GP off
    29 history rows. qnehvi scatters AWAY from this exact boundary, so it's
    the right escape lever.
- **foilsY03 5-round campaign COMPLETE (q=3, cl_min, 2026-06-02):** first
  campaign run with all of today's fixes committed (filtered priors,
  retry-protected preflight, consolidated env-source). **15/15 evals landed —
  ZERO losses across all 5 rounds** (vs foilsY02's 4 losses), a clean
  production validation of the preflight cvmfs-flake retry
  ([sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md)). **No new champion:** best
  foilsY03R01_00 obj=1.899; v2 leader stays foilsY02R03_01 obj=2.00. A
  consolidation run — filled in the 6D space, didn't exceed. Cloud refreshed
  to n=30 (1 prior + 29 foilsY), GP Pareto frontier 75→181. Deck (foils_talk)
  v2 coda updated to the n=30 numbers.
- **foilsY02 5-round campaign COMPLETE (q=3, cl_min, 2026-06-01→02):** the
  multi-round refit paid off — best obj climbed **1.71 (R0) → 2.00 (R3)**;
  champion **foilsY02R03_01 obj=2.00, sob=3.62** (approaches but doesn't beat
  the v1 obj champion foilsX07R01_03 at 2.178). Per-round best obj:
  R0 1.71 / R1 1.24 / R2 1.88 / **R3 2.00** / R4 0.61 — **R4 regressed hard**
  (obj 0.61/0.44), cl_min wandering into a low-signal corner late (the
  documented [batch-bo](/concepts/batch-bo.md) cl_min late-collapse). **11 of 15 evals landed**
  (2 lost to the R0 cvmfs preflight flake, R01_01 + an R04 child to harvest
  `metrics_none`). **Caveat: this run used the OLD cached `load_priors`**
  (51 base-hole-mismatched priors) — the parent launched before the prior
  filter fix and holds the cached module, so the picker/prior code change does
  NOT apply mid-campaign (same long-lived-parent nuance as
  [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md)); the next launch uses the corrected
  1-prior version.
- **v1→v2 priors are base-hole MISMATCHED (bug, found by /code-review
  2026-06-01).** `FoilsMode.load_priors` projects each v1 row to
  `x=[rOut,rOut,hT,hT,rIn,rIn]` and carries its `(sob,calo)` as the y-value.
  But v1 `_geom_text` emitted `stoppingTarget.holeRadius = extra_rIn`
  **globally** (base 37 + extras) whenever extras were present, while v2 pins
  the base 37 at `BASE_HOLE_RADIUS_MM=21.5` and only the extras get
  `rIn_up/dn`. So the prior's y was measured with base-hole = `extra_rIn`, but
  the v2 x-point it's attached to builds base-hole = 21.5. **50 of the 51
  reused priors have `extra_rIn != 21.5`** (range 0–50, mean 15.9; only 1 near
  21.5). Because the base 37 dominate the 49-foil stack and hole radius
  strongly changes stopping material, both pickers (cl_min seeds via
  `gp_predict_foils`, qNEHVI seeds via `botorch_predict`) are trained on
  systematically mismatched (x,y) pairs. Net effect: the rOut/hT prior
  dimensions are clean (base unchanged v1→v2) but the rIn dimension — and the
  shared y — is biased. **FIXED 2026-06-01:** `load_priors` now keeps only
  rows with `abs(extra_rIn - BASE_HOLE_RADIUS_MM) <= PRIOR_BASE_HOLE_TOL_MM`
  (1.5 mm; ~0.83%/mm base-area sensitivity → ≤1.3% mismatch). **Live effect:
  51 → 1 prior** (only `foilsX07R05_07`, rIn=21.93, survives). The v2
  leaderboard's own history is now the primary warm start; the 50 dropped
  rows simply don't transfer to v2's fixed-base parameterization. To rebuild
  a richer warm start the only sound path is re-measuring v1 champions under
  v2 geometry (grid work). Regression: `test_audit_fixes.py:
  test_load_priors_drops_base_hole_mismatch`.
  **Duplicate-logic warning (2026-06-02):** the v1→6D projection exists in a
  SECOND place — `mmackenz_table_plots/foils_v2_loader.py:_load_v1_projected`
  (on /data; feeds the static GP cloud `gp_predict_foils_cloud.py`). It had
  its own unfiltered copy; the same `abs(extra_rIn-21.5)<=1.5` filter was added
  there so the cloud's GP trains on the same data the optimizer sees (else the
  cloud shows a belief the optimizer no longer holds). A 3rd function,
  `foils_v2_loader.load_history_all_v1_symmetric`, is ANIMATION-ONLY and
  intentionally projects every v1 row (no filter). Any future change to which
  v1 rows project must touch `load_priors` AND `_load_v1_projected` in lockstep.
- **Asymmetric-rIn champion pattern CONFIRMED across the top-5 (n=50,
  2026-06-03):** the 5 best v2 configs all share a geometry v1's *coupled*
  triple could not express — **moderate rOut (≈130–195, NOT the rOut=250
  boundary cl_min drifts to), thin hT, and a sharp rIn split: upstream solid
  (rIn↑=0), downstream fully holed (rIn↓=50) in 4 of 5.** Physically the
  downstream extras want a big hole, the upstream extras want solid foils.
  This is the concrete payoff of the 5D→6D lift — the optima live in an up≠dn
  region v1 was blind to — **even though the scalar obj still caps at ~2.0**
  (`foilsY02R03_01` obj=2.003, sob=3.62; next `foilsY04R03_00` 1.963). Top-5
  rows: foilsY02R03_01 / foilsY04R03_00 / foilsY04R03_01 / foilsY02R03_02 /
  foilsY04R02_02. Upgrades the n=1 note below into a settled pattern.
  - **rIn pegs at the RANGE EXTREMES — and the two ends mean different things
    (diagnosed 2026-06-03, all 50 evals):** rIn↑ distribution 39 solid(0) / 6
    mid / 5 max(50); rIn↓ 30 max(50) / 14 solid(0) / 6 mid. Physics:
    upstream-solid stops muons; downstream-holed lets the CE (+ beam core)
    pass to the detector. **rIn↑=0 is a HARD physical floor** (can't be more
    solid than solid — not wideable). **rIn↓=50 is the SEARCH-RANGE CEILING**
    (`build_space` caps rIn at 50) — pegging there is the classic sign the
    optimum wants rIn_dn > 50 but can't reach it. **ACTIONABLE: widen the
    rIn_dn upper bound (e.g. 0–100 mm) — a bigger downstream hole may be the
    2.0-plateau breaker that lives OUTSIDE the current box, which no amount of
    cl_min rounds can find.** Caveat: cl_min also collapses to boundary
    corners, so some pegging is picker-artifact; the up≠dn asymmetry argues
    real signal underneath. qnehvi (interior probe) or the widened range would
    disentangle.
  - **Only rIn_dn warrants widening — NOT rOut (2026-06-03).** The discriminator
    is *which* configs sit at the bound: for **rIn_dn the CHAMPIONS** (top-5)
    are pegged at 50 → optimum likely outside the box → widen. For **rOut the
    bound-pegs are the BAD picks** — best configs are interior (rOut_up ~105–160,
    rOut_dn ~160–190, both well inside [50,250]); `rOut_up=50` floor → obj
    0.9/−0.03, and `rOut=250` ceiling is where cl_min boundary-collapses (low
    sob). So widening rOut just hands cl_min more boundary to collapse onto;
    if anything the rOut high end is a dead zone to NARROW. Next-campaign spec:
    change **only** `rIn_dn: 0–50 → 0–100`, leave the other 5 knobs as-is.
  - **BLOCKER before widening rIn (found 2026-06-03):** widening `rIn_dn` past
    `rOut_dn`'s floor (50) creates an INVERTED-foil region (`rIn_dn >= rOut_dn`,
    hole bigger than outer radius). `is_buildable` rejects it
    (`bo_driver.py:98`), BUT the **closed-loop picker does not
    enforce it** — `gp_predict_foils.compute_explore_picks` has no is_buildable
    call, and the `--x-point` child path bypasses `propose_one`'s guard
    (`graph/pipeline_io.py:86`). Current ranges are safe ONLY by accident
    (`max(rIn)=50 == min(rOut)=50`). So naive widening → cl_min (which pegs at
    boundaries) piles picks at `rIn_dn=100`, half infeasible → preflight
    failures, wasted evals. **Fix first:** either (1) reparameterize the hole as
    a FRACTION of rOut (`rIn = f·rOut`, `f∈[0,0.95]` — always valid, scale-free,
    arguably more physical), or (2) add the is_buildable retry loop to
    `gp_predict_foils.compute_explore_picks`. See [closed-loop-runner](/drivers/closed-loop-runner.md).
  - **The fraction reparam is LOSSLESS — opposite of v1→v2 (2026-06-03).**
    `rIn = f·rOut` is an invertible coordinate change of the SAME geometry, so
    every existing v2 row transfers EXACTLY: `f = rIn/rOut`, rOut/hT unchanged,
    `(sob,calo)` valid because the physical foil is identical (no base-hole
    mismatch). So a v3 mode's loader is a pure `rIn→rIn/rOut` conversion — NO
    filtering (vs v2's `load_priors` which had to drop 50/51 because the
    geometry changed). All ~47 v2 evals + the 1 v1 prior reuse; the old data
    fills the low-f region and the new `f≤0.95` range opens big holes (rIn up
    to ~0.95·rOut) with NO infeasible region (f<1 ⇒ hole<rOut). Bonus: fraction
    is likely better-conditioned for the GP than the under-trained absolute-mm
    rIn dims. (rOut≥50 always ⇒ no div-by-zero.)
- **v3 / `foilsf` mode BUILT + launched (`foilsZ01`, 2026-06-03).** New mode
  `FoilsFracMode(FoilsMode)` (name `foilsf`): hole = fraction `f=rIn/rOut`,
  `f∈[0,0.95]` (`F_MAX`), `is_buildable` ≡ True, writes
  `leaderboard_bo_foils_v3.tsv`. `_geom_text`/`parse_geom` just wrap the v2
  methods with the f↔rIn transform (geometry layer unchanged). `load_priors`
  returns **51 lossless priors** (all v2 evals + the 1 v1 prior, `f=rIn/rOut`).
  Validated: 51 priors load, round-trip exact, dry-run cl_min immediately pegs
  `f_dn=0.95`/`f_up=0` (wants the big downstream hole), and a **rIn_dn=180 mm
  geom — impossible in v2 — PASSES real G4 preflight**. **Naming: foilsX (v1
  5D) → foilsY (v2 6D abs) → foilsZ (v3 6D fractional).** **CAVEAT
  (2026-06-05): the foilsZ-prefix-implies-v3 convention has been BROKEN by
  foilsZ07, launched with `--mode foils` (v2 picker, FoilsMode at
  bo_driver.py:553) — so foilsZ07's rows land in
  `leaderboard_bo_foils_v2.tsv`, NOT `_v3.tsv`. The prefix is just a
  `--name-prefix` string and has no enforced link to the mode/leaderboard
  pair. To know which leaderboard a `foilsZ*` campaign feeds, check the
  parent's launch command (`--mode foils` → v2, `--mode foilsf` → v3).**
  foilsZ01 = q=3,
  max-rounds 5, cl_min, thread `closed-d163308e`. Tests the hypothesis: does a
  downstream hole bigger than v2's 50 mm cap break the obj≈2.0 ceiling?
  (Y05 was killed at round 2 to pivot here.) Uncommitted.
  - **foilsZ01 R0 (preliminary, n=3): the reparam MOVED cl_min's collapse but
    didn't kill it.** All 3 R0 picks peg `f_dn=0.95` (max fraction) AND collapse
    `rOut_dn` to its FLOOR (50) → `rIn_dn = 0.95·50 ≈ 48 mm` — basically v2's
    old cap, reached via small foils, NOT the big absolute hole v3 was built to
    test (which needs big rOut_dn × big f_dn → rIn_dn ~190 mm). Those
    small-foil/full-hole picks are high-sob (~3.43)/high-calo (~2.3e-5) → obj
    only ~1.1, no beat. So in fraction space cl_min corner-seeks a DIFFERENT
    corner than v2 (v2: rOut→250; v3: rOut→50 + f→0.95) but still doesn't reach
    the big-absolute-hole region. **Implication if R1–R2 don't pull rOut_dn up:
    the fraction reparam is necessary but NOT sufficient — qnehvi (interior
    explorer) is still needed to actually probe `large rOut_dn × large f_dn`.**
  - **foilsZ01 R1 PROBED the big hole — and it FAILED (key result, n=6,
    2026-06-03).** R1 best pick was `rOut_dn=250, f_dn=0.95 → rIn_dn=238 mm`
    (impossible in v2) and **sob collapsed to 1.69** (obj 1.11) vs ~3.4 for the
    small-hole picks. Physics: a thin ring (`f=0.95`) at large rOut sits far
    from the beam axis → misses the muons → low signal. **Implications that
    UPDATE the earlier "widen rIn_dn = plateau-breaker" hypothesis:** (a) the
    v2 `rIn_dn=50` pegging was mostly **cl_min boundary artifact, NOT a real
    out-of-box optimum** — the big-hole region is bad; (b) **obj≈2.0 looks like
    a real ceiling, not a box edge**; (c) cl_min STILL boundary-collapses in
    f-space (pegs `f_dn=0.95`, the wrong region — the v2 champion is at
    `f_dn≈0.31`, a MODERATE hole). So the real lever is **qnehvi to explore the
    moderate-hole interior (`f≈0.3`) cl_min won't reach**, NOT further box
    widening. Confirm if R2–R3 keep pegging f_dn=0.95.
  - **foilsZ01 R2–R3 RESOLVE the watch-item: the f_dn=0.95 peg SELF-CORRECTED
    (2026-06-04, n=12 thru R03).** Once R1's wide-hole probes harvested sob≈1.69,
    the GP learned big holes kill signal and cl_min **moved into the interior on
    its own** — R02 best `f_dn=0.11` (obj 1.317), R03 best `f_dn=0.66`
    (obj 1.409). So cl_min did NOT need qnehvi rescue *here*; boundary-collapse
    is GP-data-dependent, not a fixed cl_min pathology. **Per-round best obj
    climbs 1.120→1.110→1.317→1.409 (R00→R03)** but stays **far below the v2 bar
    obj=2.003** — every wide-hole config is low-sob, and the climb back toward
    1.4 comes from *retreating* to small/moderate holes. **Verdict: opening the
    downstream hole does NOT break the obj≈2.0 ceiling; the ceiling is real, not
    a v2 box-edge artifact** — which is exactly what foilsZ01 was built to test.
    R04 (final round of max-rounds 5) running 2026-06-04; an optimistic R04
    won't leap 1.4→2.0, so v3 is expected to confirm the ceiling, not break it.
  - **foilsZ01 COMPLETE (2026-06-04, 15 rows, all 5 rounds, parent exited
    clean).** R04 **regressed** — its 3 picks returned to the big-foil/big-hole
    corner (`rOut_dn=250, sob≈3.1, calo≈1.9e-5`) for obj≈1.20, beating nothing;
    the optimizer found nothing better in the final round. **v3 champion =
    `foilsZ01R03_00`, obj=1.409 (sob=2.37, f_dn=0.66)** — peaked at R03. Final
    standings across all foils campaigns: **v1 champion `foilsX07R01_03`
    obj=2.178 (sob=3.60, coupled up==dn diagonal) remains the ALL-TIME best**;
    v2 best 2.003; v3 best 1.409. **Conclusions the campaign settled:** (1) the
    obj≈2.0 ceiling is robust under v2 (abs rIn) AND v3 (fractional rIn); (2)
    cl_min DID reach the moderate-hole interior on its own (R02 f_dn=0.11, R03
    f_dn=0.66) yet still couldn't break 2.0 — so **qnehvi-interior is NO LONGER
    a compelling lever** (that region got sampled, ceiling held); (3) decoupling
    up≠down (the entire 6D v2+v3 effort) never beat the 5D coupled-diagonal v1
    champion. **The foil-stack GEOMETRY line (rIn/rOut/halfThickness) is
    saturated at obj=2.178.** The one genuinely unexplored lever is foil-to-foil
    **z-spacing/pitch**, which `FoilsMode` currently PINS to the v02 baseline
    (deck open-questions slide) — that, not another rIn reparam or picker swap,
    is the real next dimensionality lift.
  - **PARTIAL REVISION — foilsZ02 qNEHVI grazed PAST the v2 bar (2026-06-04,
    R02 of an in-flight 10-round run).** `foilsZ02R02_02` harvested
    **obj=2.017 > the v2 ceiling 2.003** — the FIRST v3 eval to beat v2, and the
    first sign the "obj≈2.0 is a hard wall" claim above is overstated. Geometry:
    **thin annulus at MODERATE rOut** — rOut_up/dn≈147/146, hT≈0.14/0.23,
    f_up=f_dn=0.95 ⇒ rIn≈140/139, i.e. an ~7 mm-wide ring at radius ~144 mm;
    sob=3.40, calo=1.38e-5. **Physics that reconciles this with foilsZ01's
    big-hole FAILURE:** f=0.95 is fine, what kills sob is the ABSOLUTE ring
    radius — f=0.95 at rOut=250 (foilsZ01 R1) puts the ring at ~244 mm, far
    off-axis, sob→1.69; f=0.95 at rOut=147 keeps it at ~144 mm, sob=3.40. So the
    lever is rOut (ring radius) × f jointly, NOT f alone, and cl_min never
    sampled the moderate-rOut/high-f corner (qNEHVI's exploration did).
    **CAVEATS:** +0.7% over 2.003 is marginal and may be within harvest noise
    (sob is 2 sig-figs); it's n=1, a spike (foilsZ02 R03–R05 fell back to
    1.4–1.7); and it STILL does not beat the v1 all-time champion (2.178). Deck
    slides 21 + 25 ("obj≈2.0 wall is real") are now slightly overstated —
    revise once foilsZ02 completes (confirms a soft-ceiling-qNEHVI-can-graze vs
    a noise spike).
  - **foilsZ02 COMPLETE (2026-06-04, 10 rounds, 30 rows) — the 2.017 was a
    ONE-OFF SPIKE.** Across the remaining 8 rounds qNEHVI **never reproduced or
    beat R02's 2.017** (per-round best R03–R09 ranged 1.4–1.95: R06 1.89, R07
    1.82, R08 1.87, R09 1.95). So the verdict resolves toward **noise spike**,
    not a robust new optimum — 10 rounds of the same picker couldn't re-hit it.
    foilsZ02 final best stays `foilsZ02R02_02` obj=2.017; all-time best remains
    the v1 `foilsX07R01_03` obj=2.178. Combined with the [scalarized-objective](/concepts/scalarized-objective.md)
    α-placeholder finding, the honest read is: **the (sob,calo) front is
    well-mapped/saturated (44 Pareto pts over 346 evals) and 2.017 is not a
    durable advance.** The deck was rewritten α-free accordingly (reports the
    front + best-S/√B-at-calo-budget, drops the obj/2.017 framing).
- **First asymmetric pick beats the diagonal (preliminary, n=1, 2026-06-01;
  note the prior bias above weakens this signal):**
  foilsY02R00_02 — up `(rOut=143, hT=0.05, rIn=23.96)`, dn `(rOut=250,
  hT=0.05, rIn=0)`, a genuinely up≠dn geometry — harvested **obj=1.711
  (sob=3.55, calo=1.84e-5)**, outscoring *every* foilsY01 row (best was the
  near-diagonal R00_01 at obj=1.522). First empirical signal that decoupling
  upstream/downstream extras (the reason for the 5D→6D lift) actually buys
  something the diagonal priors can't reach. **Caveat: single eval** — the
  remaining foilsY02 rounds confirm or overturn it; don't over-weight n=1.
- **v2 naming + leaderboard split (2026-06-01):** the **`foilsY` config-name
  series marks the 6D era**, parallel to `foilsX0N` = the v1 5D campaigns.
  v2 evals append to a **separate `leaderboard_bo_foils_v2.tsv`** (`v1` stays
  read-only prior source); don't `wc -l` v1 to gauge v2 progress. First v2
  campaign: `foilsY01` (q=3, `--max-rounds 1`, `--picker cl_min`,
  thread_id `closed-63c24563`) launched 2026-06-01 on uncommitted v2 code;
  round-0 cl_min picks all railed the downstream side to floor
  (`rOut_dn=50, rIn_dn=0`) and varied upstream — expected, since the 51
  priors all sit on the up==dn diagonal so EI probes the unseen off-diagonal.
- **A foils dim-count change must touch FOUR places in lockstep** (the v2
  6D cutover missed the last one): (1) `FoilsMode.build_space`, (2) the
  cl_min shim `mmackenz_table_plots/gp_predict_foils.py` (delegates to
  `build_space`, so auto-OK), (3) `botorch_predict.py` `MODE_SPECS["foils"]`
  lo/hi/int_dims, (4) `graph/closed_loop.py:_DRY_RUN_KNOB_LABELS["foils"]`.
  #4 was left at the old 5 labels → `_dry_run` threw
  `IndexError: tuple index out of range` at `closed_loop.py:593`
  (`labels[i]` for a 6-tuple pick) on the FIRST foils dry-run after cutover.
  Fixed to the 6D labels `(rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn)`;
  the generic `x{i}` fallback only fires for modes absent from the dict, so
  a stale-but-present entry silently mismatches.

## Open questions / TODO
- First closed-loop round (`foilsX01`) — children running mubeam/mustops_ce;
  Hand-seed 5-8 small-extras configs (n_up/n_down ∈ {0,1,2}, mid-range
  rOut/halfThick) in round 0 if the Sobol bootstrap proves too spread-out
  after eyeballing the picks vs the +12 envelope.
- No GP-cloud rendering for v1 (helical-side `cloud_plot.py` is GP+Sobol
  and 4D-specific; revisit after 20-30 evals if the leaderboard alone is
  hard to interpret).
- Convergence-poll gating: re-use helical's existing
  `pipeline.py` plumbing as-is — no foils-specific tuning until first
  round shows whether stage-out timing changes meaningfully when no
  helical plug is present.
