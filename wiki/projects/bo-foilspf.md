---
type: project
title: bo-foilspf — 10D profile-parameterized stopping target
description: (SEARCH CLOSED 2026-08-08) 10D+ BO over a profile-parameterized
  all-foils stopping target vs the foilsflash objectives, Run1Bap + IPA-fix
  stack; bp/bpx/bpz (shape, box, spacing) all stalled best-at-budget at
  exactly 4.00 — physical ceiling at the deployed damage budget; critical
  path is full-sim validation of bp04R00_02
status: dormant
status_note: 'SEARCH CLOSED 2026-08-08 on all three axes (shape, box,
  spacing): foilspfbp, bpx, and bpz all stalled best-at-budget at exactly
  4.00. Remaining critical path is full-sim validation of bp04R00_02, not
  more search'
timestamp: '2026-08-10'
updated_note: 'foilspfbpz06 (exploit round 3) drained 40/40, 0 failures —
  THE CLIMB STOPPED, exploit line CLOSED. Round mean 4.326 vs bpz05''s
  4.323 (flat to 0.003 = statistically identical at σ=0.006) and NO new
  record: the round''s only 4.41 is the bit-identical REPLICATE of
  bpz05R01_00 (free cross-family σ check — see bo-noise-budget), best
  genuinely-new design 4.40. Trajectory 4.33→4.37→4.41→4.41: the +0.04
  per re-aim that held twice did not repeat, so the damage-unconstrained
  ceiling is 4.41 ± 0.01, REPLICATED. 0/40 in budget for the third round
  running (+22…+78% flash) → best-at-budget stays 4.000, search closed for
  deployment. Program: 337 evals, 42 dominating, 42 Pareto points. Top-5
  DISTINCT designs span 4.38–4.41 with 3 independently reproduced and two
  OPPOSITE hole strategies (bore ≤5 mm vs a 44 mm funnel) tying — a
  degenerate ridge top, the affirmative evidence the ceiling is mapped.
  Decision: stop the ceiling map'
---

# bo-foilspf — 10D profile-parameterized stopping target

## Summary
The successor line to [bo-foilsflash](/projects/bo-foilsflash.md): instead of
37 pinned foils + 12 free extras (6D), the whole stack is generated from
K=3 profile control points for each of rOut, halfThickness, and hole
fraction f, plus a total-extent knob — 10 dims covering 400–1100 mm freely,
which geometrically subsumes foilsflash's fixed 1066.7 mm envelope. It is a
pure JSON mode (`mode_specs/foilspf.json`, no Python mode class) and the
first line born on the corrected stack: Run1Bap Musing, IPA
absolute-position fix, and `require_zero_overlaps=true`. Its first
production campaign matched the old champion's sob at lower flash with the
absorber in the *right* place — something no foilsflash row can claim.

## Key facts
- **★★ SEARCH CLOSED (2026-08-08): foilspfbpz01 drained 40/40 with 0
  failures and best-at-budget stalled at EXACTLY 4.00 for the third
  consecutive campaign** — still the seed `bp04R00_09` (4.000); bpz's own
  best in-budget 3.90 (`R04_07`). Per the decision rule pre-registered in
  the spec note before launch, the stopping-target search is closed on all
  three axes: shape (bp, f×rOut profiles), box (bpx, rOut 30–150), spacing
  (bpz, linear pitch via `zmid`). Three independent parameterizations
  stalling at the same number is evidence of a physical ceiling at the
  deployed damage budget, not an acquisition artifact. The pitch lever IS
  real above budget: 10 bpz evals cleared sob 4.00, `R03_05` at 4.10 @
  **+1.1%** damage (vs bpx's cheapest-above-4.00 at +11%), campaign-max
  4.25 @ +56% (`R05_00`, zmid pinned +150). Near-budget optima sit interior
  in zmid (+114…+118, downstream-packed), so the stall is not a zmid-box
  artifact. Final recommendation: no further stopping-target campaigns;
  critical path is full-sim validation of `bp04R00_02`.
- **★ foilspfbw CLOSED at 20 evals / 1 campaign (2026-08-07) — NEGATIVE, and
  CONFOUNDED BY DESIGN.** foilspfbw01 drained 20/20 with zero failures. Best sob
  at the deployed damage budget = **3.79** vs foilspfbp's **4.00** — it did not
  clear. Max sob overall is also 3.79, from the **round-0 Sobol draw**; across
  10 GP-picked evals the optimizer never beat its own cold start (GP-era best
  3.46).
  - **The campaign changed TWO things at once**, so it cannot attribute its own
    result: the `rOut` ceiling 120 → 150 mm **and** the parameterization
    (`f × rOut` → `bore + width`, with rOut *derived* as the sum). Neither "the
    wall does not bind" nor "bore is the worse parameterization" is established
    by it. Designing it that way was the mistake; see the method rules in
    [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md).
  - **The wider radius WAS offered and WAS used** (checked 2026-08-07 after an
    operator challenge): 5 of 20 evals exceeded rOut 120, against 5.4 expected
    from the induced prior, and the picker placed two picks at exactly 150.
    Among the **top 5 by sob, 3 exceed 120** — `bw01R00_01` (3.59, rOut 127.0),
    `bw01R04_04` (3.46, rOut **150.0**), `bw01R00_00` (3.41, rOut 120.7) — and
    `bw01R04_04` beats the deployed target on both axes. **An earlier entry
    here claimed the opposite** ("high-sob designs stay inside the old box");
    that came from tallying the 7-point Pareto front, which at this stage is
    dominated by low-damage corner designs and is the wrong slice for a
    question about radius.
  - **What the campaign DID buy:** 4 of 20 designs beat the deployed target on
    both axes — `bw01R00_09` (sob 3.79, **+16%**, damage **−7%**),
    `bw01R00_02` (3.63, +11%, −26%), `bw01R00_01` (3.59, +10%, −13%),
    `bw01R04_04` (3.46, +6%, −5%). None beats foilspfbp's deployable trio.
  - **Budget caveat:** 20 cold-start evals in 9D against a 93-eval line is a
    thin test of anything. foilspf01 cold-started to 4.09 in 16 evals, so
    bore+w did not start faster — but that is the whole of what is shown.
  - **Recommendation on record: do NOT launch foilspfbw02** — not because the
    ceiling question is settled (it is NOT), but because the design deliverable
    does not depend on the answer: foilspfbp's trio wins either way. If the
    ceiling question is ever worth settling, the clean test is foilspfbp's
    parameterization with `rOut` bounds raised and **nothing else changed**.
- **Per-eval grid cost (measured 2026-08-03**; TimeReport from job logs of
  foilspf03R02_00 + foilspf01R00_00, consistent): **~150–155 CPU-h/point**,
  wall ~3.4 h. mubeam 15×200k ev ≈ 18 CPU-h, mustops_ce 15×75k ≈ 20,
  elebeam_flash 100×110k ≈ **115 (75% of total)**. Wall critical path is the
  serial mubeam (~93 min) → mustops_ce (~96 min) legs + ~10 min harvest;
  elebeam_flash is fully hidden by `presubmit_after: mubeam`. Actual
  per-event CPU is 2.4–2.6× the sizing basis in `core/pipeline.py`'s tuning
  comment (foilsflash-6D-measured 9.1/24.1/16.6 ms/ev → foilspf actual
  ~23/63/38): the "~30-min payload" design runs 60–90-min payloads on
  49-foil profile stacks. Resizing events_per_job×njobs at constant events
  would ~halve wall — fresh-campaign-only (stamped at submit).
- **Knobs (10):** `rOut_{0,1,2}` ∈ [50, 120], `hT_{0,1,2}` ∈ [0.01, 0.15],
  `f_{0,1,2}` ∈ [0, 0.95], `extent` ∈ [400, 1100]. Constants/derived in
  `mode_specs/foilspf.json` `geom`: `z0 = 5871` (plain constant — the
  2026-07-31 z0-slide was reverted as backwards), `ipa_dist =
  625 − (extent − 800)/2` (compensation expression kept as fail-safe under
  the `zStartInMu2e` option — see 2026-08-01 log ★ entry).
- **Software stack:** musing `Offline_run1bap_partial/setup_local.sh`,
  tarball `Code_run1bap_holeradii_ipafix.tar.bz2` (strings-gated),
  `require_zero_overlaps: true` — zero-overlap preflight is reachable and
  enforced (foilsflash-family Run1Bak modes can't demand this).
- **Objectives:** identical machinery to foilsflash — sob (Run1A CE S/√B
  via EdepAna + sensitivity macro) + `flash_edep` (elebeam early-flash
  tracker StrawGasStep edep/POT), hybrid picker (qNEHVI+qNParEGO),
  `obs_noise → train_Yvar`. Numbers are **Run1Bap-scale**: the foilsflash
  champion (3.90 Run1Bak) reads ≈4.10 here
  ([run1bak-run1bap-sob-shift](/concepts/run1bak-run1bap-sob-shift.md)).
- **Leaderboard:** `leaderboards/leaderboard_bo_foilspf.tsv` started at 0
  rows 2026-08-01; the smoke row `foilspfSMOKER00_00` (extent 894, flash
  4.81e-7) is archived in
  `leaderboard_bo_foilspf_pre_ipafix_archive.tsv` — it ran pre-IPA-fix
  with the absorber displaced 47 mm, not comparable.
- **foilspf01 (2026-08-01→02, first production campaign):** hybrid, q=10,
  rolling, max-evals 20 — **20/20 rows, 0 failures, 20/20 preflight PASS
  at zero overlaps** (first campaign ever to clear the strict gate), clean
  `rolling_done`. sob ∈ [1.12, 4.09], flash ∈ [1.58e-7, 1.41e-6].
- **Headline: `foilspf01R03_00` sob 4.09 / flash 9.68e-7 at extent 1015**
  — the picker's first targeted exploit (chosen right after Sobol row
  `R00_09` hit 4.04 at extent 947) **matched the foilsflash
  champion-equivalent (4.10 ± σ_sob) in 16 evals at ~6% lower flash**
  (champion-x Run1Bap arms measured 1.03e-6), on clean geometry.
- **Flash frontier collapsed:** `R05_00` flash **1.58e-7** (sob 2.17) and
  `R06_00` 1.68e-7 (sob 1.84) sit ~4× below foilsflash's flash floor
  (~6.2e-7) — the profile parameterization reaches flash territory the 6D
  line never touched.
- **foilspf02 (2026-08-02, second campaign — first seeded on real history):**
  same settings as foilspf01 (hybrid, q=10, rolling, max-evals 20, elebeam
  100), **20/20 rows, 0 failures**, clean `rolling_done`, ~7 h wall. sob ∈
  [0.31, 3.87], flash ∈ [**5.93e-8**, 8.27e-7]. It did exactly what it was
  launched for — work the thin 3.4–4.1 front gap — and then some: **9 of the
  10 global Pareto points are now foilspf02's**; every foilspf01 front point
  except the 4.09 champion is dominated.
- **foilspf03 (2026-08-02/03, first campaign on the extended 400–2000
  range):** same settings again (hybrid, q=10, rolling, max-evals 20),
  **20/20 rows, 0 failures**, 20/20 preflight PASS at zero overlaps
  *including four children at the brand-new 2000 ceiling*. sob ∈ [0.13,
  **4.41**], flash ∈ [6.57e-8, 1.18e-6], and it swept the FULL new range
  (extent ∈ [400, 2000], **13/20 rows above the old 1100 bound**).
- **★ NEW CHAMPION `foilspf03R02_00`: sob 4.41 / flash 9.15e-7 at extent
  1975 — it STRICTLY DOMINATES the old champion** `foilspf01R03_00`
  (4.09 / 9.68e-7): **+7.8% sob AND −5.5% flash simultaneously**. The
  2026-08-02 bound extension is what made it reachable; `01R03_00` has now
  dropped off the Pareto front entirely. At σ_sob = 0.4% the sob gain is
  ~20σ — not noise.
- **Extent is permissive, not sufficient.** `corr(extent, sob) = +0.48`
  over foilspf03's 20 rows — real but far from deterministic. The four
  round-0 points at extent 2000 came out 4.35 / 3.85 / 2.01 / 0.97, i.e.
  the campaign's full range. Length *allows* a better optimum; the nine
  profile knobs decide whether you get one. The old 1100 bound was not
  clipping a simple "longer is better" gradient — it was clipping a corner
  of the space that happens to contain a better optimum.
- **Pareto front after THREE campaigns (18 points over 60 rows; foilspf03
  holds 14):** `03R02_00` **4.41/9.15e-7** · `03R08_01` 3.89/9.14e-7 ·
  `02R07_00` 3.87/6.53e-7 · `03R00_02` 3.85/5.31e-7 · `03R01_00`
  3.71/4.56e-7 · `03R06_00` 3.70/4.31e-7 · `02R00_09` 3.42/4.07e-7 ·
  `03R00_08` 3.39/3.25e-7 · `03R00_09` 3.28/2.93e-7 · `03R00_01`
  2.93/2.05e-7 · `02R01_00` 2.43/1.53e-7 · `03R00_04` 2.01/1.17e-7 ·
  `03R00_00` 1.96/1.12e-7 · `03R00_07` 1.49/1.05e-7 · `03R03_00`
  1.47/9.48e-8 · `03R00_05` 0.97/8.72e-8 · `03R00_06` 0.95/8.19e-8 ·
  `02R02_00` 0.86/5.93e-8.
- Note `03R08_01` (sob 3.89 at extent **857**) — a strong SHORT-stack front
  point, so the front is not simply "longer is better" at the top either.
- **The trade the front now offers:** `foilspf02R07_00` gives up **5.4% of
  sob for 33% less flash** vs the champion (3.87/6.53e-7 vs 4.09/9.68e-7);
  `02R03_00` gives up 10% of sob for **55% less flash**. Both are cleaner
  flash-per-sob than anything the 6D line reached.
- **★ EXTENT CEILING IS NOW PINNED — the documented revisit trigger fired.**
  `02R07_00` and `02R03_00` both sit at **extent = 1100.0**, exactly the box
  bound, and they are the two best new front points. The 2026-07-31 decision
  was "revisit the ceiling only if a campaign pins it"; it has. The front's
  upper limb is now bounded by the box, not by physics — a third campaign
  should raise the bound (or the line is optimizing against an artificial
  wall). foilspf01's best sat at 1015/1033, below the bound, which is why
  this was not visible after one campaign.
- **Low-flash limb question ANSWERED (it was open after foilspf01):** the
  limb does extend toward useful sob. `02R01_00` reaches sob 2.43 at
  1.53e-7 — strictly better than foilspf01's `R05_00` (2.17 at 1.58e-7) on
  both axes — and the new absolute floor `02R02_00` 5.93e-8 (sob 0.86, thin
  foils + wide holes: physics-useless, but it maps the limb's end) sits
  **~10× below the 6D line's flash floor**.
- Sobol cold start is deterministic per mode+seed: round-0 pick `_00`
  reproduced the SMOKER00_00 shape in 9/10 dims (extent differs — bounds
  history), a free cross-check that the knob mapping is stable.
- **foilspf04 (2026-08-03, second campaign on the 2000 range):** same
  settings, **20/20 rows, 0 failures**. Set the line's **sob record
  `foilspf04R01_00` 4.75 / 1.458e-6** (+0.34 over the 03 champion) and the
  flash-matched front point `foilspf04R03_00` **4.07 / 6.77e-7** — champion
  sob at the deployed target's own flash (+25% sob for free vs `nominalAB01`
  3.26 / 6.85e-7). 15 of 80 total rows now sit at exactly extent=2000: the
  optimizer is pinned to the wall again.
- **★ foilspf2k01 VERDICT (2026-08-03, 9D shape-only satellite at extent
  pinned 2000 — `mode_specs/foilspf2k.json`, own leaderboard
  `leaderboard_bo_foilspf2k.tsv`, seeded with 15 transplanted foilspf
  rows):** hybrid q=10 rolling 20 — **20/20 rows, 0 failures, clean
  `rolling_done` — and 0 of 20 beat the best seed (4.75); best new row
  `foilspf2k01R05_00` only 4.09 / 7.95e-7**, below even the transplanted
  4.41 champion. Same signature as foilspf02 at the 1100 wall (+0.00 sob in
  20 evals): **a fixed box saturates this problem in ~20 evals. Shape at
  fixed length is exhausted; the remaining lever is length itself.** More
  within-box BO evals answer nothing about the optimum.
- **★ DESIGNED EXTENT SCAN COMPLETE (2026-08-03, 10/10 rows, 0 failures —
  the extent question is CLOSED).** 10 `graph.run --x-point` evals
  `foilspfSCAN{A,B}{0800,1100,1400,1700,2000}`: shape A = `foilspf03R02_00`
  (champion), shape B = `foilspf04R03_00` (flash-matched), shape byte-fixed,
  only `extent` varies; rows name-tagged in the foilspf leaderboard (NOT a
  clone mode — a new spec file would go live in every registry-importing
  process incl. in-flight children); per-chain checkpoint DBs under
  `/tmp/oksuzian/<name>/`. 10/10 preflight PASS at zero overlaps. Measured
  (sob / flash·1e-7):

  | extent | shape A | shape B |
  |---|---|---|
  | 800  | 4.02 / 7.74 | 3.87 / 6.09 |
  | 1100 | 4.16 / 8.27 | 3.99 / 6.34 |
  | 1400 | 4.26 / 8.12 | 4.03 / 6.33 |
  | 1700 | 4.36 / 8.58 | 4.06 / 6.54 |
  | 2000 | 4.40 / 9.27 | 4.08 / 6.17 |

  **A's sob steps decelerate +0.14 → +0.10 → +0.10 → +0.04 (last step
  1.1σ_pair); B is flat from 1400 (+0.03, +0.02, ≤0.9σ).** Marginal trade at
  A's top: 1700→2000 buys **+0.9% sob for +8.0% flash** — a bad trade.
  Corridor work to ~2400 (upstream shift) would buy ≲0.04 sob and is **NOT
  justified**; 1.4–1.7 m captures 97–99% of the length gain. **Deployable
  headline: B@800 = 3.87/6.09e-7 STRICTLY DOMINATES the deployed target in
  its own 800 mm footprint** (`nominalAB01` 3.26/6.85e-7: +19% sob at −11%
  flash, no corridor change); A@800 = 4.02/7.74e-7 (+23% sob, +13% flash,
  −25% flash vs the 6D champion at −2% sob).
- **★ EXTENT MECHANISM CORRECTED (2026-08-03, from the scan's own harvest
  decomposition — refutes "the gain is in stopping"):** across 800→2000 at
  fixed shape, `stopping_factor` is FLAT (±0.3% A, +1.8% B) and fixed-box
  `ce_abs_eff` is flat — physically expected, since extent only changes
  pitch and a traversing muon integrates the same total areal density. The
  entire sob gain is **spectral: the CE low-momentum tail retreats, the
  macro's optimal box narrows** (low edge 103.1 → 103.3 → 103.5 MeV/c, in
  its 0.2 MeV quantization — the curve is partly a staircase), signal S
  stays ~constant (75-77 A / 67-71 B) while the **cosmic background tracks
  box width** (~220/MeV: 350→310→270). Arithmetic closes exactly:
  4.02·(77/75)·√(350/310) = 4.39 ≈ 4.40 measured (A);
  3.87·(67/68)·√(310/270) = 4.08 (B). Leading mechanism for the tail: CE
  self-absorption — exit-path re-crossings of neighboring foils scale as
  1/pitch and stop mattering once spacing exceeds the helix escape length
  (the ~1400-1700 knee); testable from `nts.ce.root` low-edge shapes,
  not yet tested. This gain is GENUINE for Run 1 because Run1A is
  cosmic-dominated with B ∝ window width
  ([mu2e-run1-sensitivity](/concepts/mu2e-run1-sensitivity.md)) — but it
  is **REGIME-SCOPED: in a background-poor scenario (full CRV shield,
  2022-paper baseline) window economics vanish and the extent lever
  largely evaporates**, while shape gains (stops×acceptance, the ~+9%
  A-over-B product at every length) survive in both regimes. The old
  corr(stops,extent)=+0.35 across BO rows was shape-confounded. The
  foilspf deck's "Why longer helps → the gain is in stopping" slide is now
  WRONG — fix at next deck refresh.
- **★ REGIME RE-RANKING (2026-08-04, free — all 110 archive rows re-scored
  under the regime-robust FoM `stopping_factor × ce_abs_eff` from
  summary.json):** global Spearman vs sob is 0.946, but the TOP is
  regime-fragile: the sob champion `foilspf03R02_00` falls to robust-rank
  **22**; robust **#1 is the never-headlined `foilspf04R05_00`** (extent
  1680, sob only 3.98, flash 1.21e-6) with stop_frac 0.1305 + eff 8.59e-4 =
  **+70% signal yield over the sob champion** (0.0969/6.81e-4) — Run-1
  cosmic-window economics deliberately traded yield for spectral sharpness,
  and background-poor scaling reverses the trade. **`foilspf04R00_03` (sob
  4.49, flash 1.34e-6, extent 2000) is #2 under BOTH FoMs** — the
  dual-regime compromise candidate. Any hardware recommendation must state
  its regime weighting; the per-regime candidate set is {03R02_00 Run-1 /
  04R05_00 robust / 04R00_03 both / SCANB0800 in-footprint}. (frozen before any row
  landed; scratchpad `extent_prediction_prereg.json`): **8/8 extrapolation
  points within 0.43σ**; both 2000-point replicates within 0.3% sob of their
  source rows (A: 4.40 vs 4.41, B: 4.08 vs 4.07). **The surrogate knew the
  curve** — designed scans can lean on GP predictions where σ is quoted.
  Graded claims: A decelerating-monotone CONFIRMED; B "turnover ~1750" reads
  as *flat-from-1400* (measured +0.02±0.035 over 1700→2000, consistent with
  the GP's −0.012 inversion and with zero); A@800 "within noise of 6D
  champion" NOT quite — measured −2.0% (−2.3σ_pair), flash −25% confirmed.
  Two systematics worth carrying: (1) **all 8 extrapolation pulls are
  negative** (sign-test p≈0.008) — the GP runs ~1–2% optimistic away from
  its training data (same direction as the known high-sob-corner misfit);
  (2) **flash replicate wobble**: B2000 vs its source = −8.9% (~2.7σ at the
  2.33%/point budget) while A2000 = +1.3% — one of two pairs hot, so
  σ(flash)=0.01 in log10 may be ~1.5–2× underestimated; re-check before the
  next obs_noise-sensitive fit.
- **Baseline-pitch line (foilspfbp), state at 2026-08-05: 53 evals, 0
  failures, best sob 4.29, damage floor 5.58e-8, 22× damage span, 17
  Pareto points.** foilspfbp01 20/20 (winner `R00_03` in wave 0),
  foilspfbp02 20/20 (**0 of 20 beat it**, but supplied **7 of the 17 front
  points**), foilspfbp03 launched 22:12:40. Fourth consecutive
  reproduction of the fixed-box ~20-eval saturation signature, and the
  first one **pre-registered before launch** — the rule "one campaign
  saturates a fixed box; a second buys front coverage, never a champion"
  is now predictive.
- **The best-trade point saves damage by PLACEMENT, not by mass.**
  `bp02R03_00` (4.09 / 7.87e-7 — the 6D champion's 4.10 at −24% damage)
  carries **9% more aluminium** than the max-sob `bp01R00_03` (166 vs
  153 cm³), but Al inside r<40 mm drops **22.0% → 9.2%**. Holes open from
  foil 25 of 49 and exceed 50 mm from foil 39, so the downstream foils
  become 6 mm rings at r = 114–120 mm — fully out of the beam — where the
  max-sob point puts solid r<50 mm disks. Costs 4.7% sob for 36% less
  damage. Consistent with Edmonds DocDB-10898 (flash parents central,
  RMS 24 mm), reached by search and via the downstream taper rather than a
  central hole. Derived from the rendered geom txt (G4 truth), not from
  re-evaluating the profile.
- **Extent lever, damage-matched (closes the extent-scan record).** At
  fixed shape: 800→2000 mm = +9.5% sob (A) / +5.4% (B); 1067→2000 = +6.2%
  / +2.6%. With shape re-optimized at each length the headline is +10.7%
  (4.29 at 1067 → 4.75 at 2000) — but that buys **+19% damage**, and at
  matched damage (~1.2e-6) the 2 m advantage is only **+1.4%, ~2σ**
  (`foilspf03R00_03` 4.35 at 1.185e-6 vs `bp01R00_03` 4.29 at 1.227e-6).
  Length mostly buys permission to spend material, not stopping. Caveat:
  the free-extent line has 90 evals vs 53 at pinned pitch, so +1.4% is an
  upper bound on the real length advantage.

- **★ DAMAGE TRACKS *PLACEMENT*, NOT MASS (measured 2026-08-06, n=83 rendered
  geometries).** Spearman(Al inside r<40 mm, flash) = **+0.84**;
  Spearman(total Al volume, flash) = **+0.57**; Spearman(min bore radius,
  flash) = **−0.83**, i.e. the bore beats either of its own component knobs
  (`f_1` −0.78, `rOut_1` −0.23) because bore = f × rOut is a *product* the GP
  must learn rather than a coordinate it is given. Concretely: the two
  LOWEST-damage designs carry the MOST aluminium. `bp01R00_03` tripled the
  deployed mass while keeping the deployed 22.0% core fraction → **+79%**
  damage; `bp04R00_02` carried *more* mass at a 1.5% core → **−13%**.
  Independent rediscovery-by-search of
  [edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md)
  (flash parents central, RMS ≈24 mm), reached via a downstream taper rather
  than a central hole. Metric is computed from the *rendered* geom txt
  (G4 truth), not from re-evaluating the profile.
- **The knob is BORE WIDTH + a bore PROFILE — not "rings vs discs".** Careful:
  the deployed target is ALREADY annular — 37 foils, rOut 75 mm constant,
  hole **21.5 mm constant** (that *is* the Edmonds DocDB-10898 central hole,
  and it is a single scalar in stock `StoppingTargetMaker`). What the
  optimizer adds is (a) a **much wider** bore and (b) a bore that **varies
  along z**. Measured bores: `bp04R00_02` 33–69 mm (−13% damage, +19% sob) ·
  `bp02R08_00` 16–42 mm (+6%, +24%) · `bp03R03_00` 0–24 mm (+22%, +32%) vs
  deployed 21.5 mm flat. Bore shrinks monotonically as damage rises across
  the headline trio. Lost near-axis stopping mass is clawed back by growing
  OUTWARD (rOut to 120 mm, 3.4× the deployed Al volume).
- **24 of 83 designs beat the DEPLOYED target on both objectives** — the
  "trade-off" framing is wrong at this pitch. Headline trio (all at the
  deployed 22.2 mm pitch, Run1Bap stack): `bp03R03_00` 4.30/8.37e-7 (+32%
  sob, +22% damage) · `bp02R08_00` 4.05/7.27e-7 (+24%, **+6%**) ·
  `bp04R00_02` 3.87/5.94e-7 (+19%, **−13%**, strictly dominating).
  Deployed reference `nominalAB01` = 3.26 / 6.854e-7 / 63 cm³ Al / 22.0% core.
- **STOP CRITERION for this box (2026-08-06): saturated.** Budget-conditioned
  best-sob is flat — at the deployed damage budget the line has sat at
  **3.99 since the seeds** (bp04: 4.00, +0.3% over 70 evals, inside noise),
  and the 3.99 is `SCANB1100`, a *transplanted seed*. Front growth 6→28 points
  is densification. Next box named by the front's own bound-hitting:
  `rOut_{0,1,2}` pinned at the 120 mm ceiling in 12–15 of 28 front designs
  (needs an IPA/DS2Vacuum clearance check before raising), `hT_0` at its 20 µm
  floor in 15 of 28 (manufacturability question, not a simulation one).
  Untested structural DOF: **non-uniform foil pitch** (`deltaZ` is uniform by
  construction = extent/n_foils) and K>3 profiles.

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md),
  [bo-foilsg](/projects/bo-foilsg.md)
- Concepts: [run1bak-run1bap-sob-shift](/concepts/run1bak-run1bap-sob-shift.md),
  [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md),
  [bo-noise-budget](/concepts/bo-noise-budget.md)
- Drivers: [closed-loop-runner](/drivers/closed-loop-runner.md),
  [bo-driver](/drivers/bo-driver.md)
- Source files: `mode_specs/foilspf.json`;
  `docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md`
- Deck figures (2026-08-02, foilsflash-beamer style): `docs/foilspf_perpot_cloud.png`
  ← `mmackenz_table_plots/gp_predict_foilspf_perpot_cloud.py`;
  `docs/foilspf_bestsob_sketch.png` ← `mmackenz_table_plots/sketch_foilspf_bestsob_target.py`;
  `docs/foilspf_langgraph.png` ← `draw_mermaid()` under `AUTORESEARCH_MODE=foilspf` + mmdc.
  Deployed/champion reference markers are the measured A/B arms `nominalAB01` /
  `ipafixAB01` (Run1Bap stack), NOT the Run1Bak deck numbers.
- Data: [leaderboards](/datasets/leaderboards.md)

## Open questions / TODO
- Confirm `R03_00` at N=400 elebeam jobs (σ_flash 2.52% @ N=100) before
  calling the champion-match final — same protocol as foilsflash's
  BASIN01/C400 confirmations.
- ~~Does the low-flash limb extend toward useful sob?~~ **ANSWERED by
  foilspf02** — yes; see the limb facts above.
- ~~Extent pinning watch~~ **FIRED, MEASURED, AND RESOLVED 2026-08-02:
  ceiling raised 1100 → 1700 → 2000** (5× the deployed 800 mm span, 2.5×
  what foilspf01/02 could reach). foilspf02's two best new Pareto points
  both sat exactly on the 1100 bound. Worst-corner preflight (rOut
  120/120/120, hT .15/.15/.15, solid `f=0` — maximal material, so a PASS
  certifies the whole box at that extent) measured every step:

  | extent | upstream edge | verdict |
  |---|---|---|
  | 1100 | 5321 | PASS, 0 overlaps |
  | 1400 | 5171 | PASS, 0 overlaps |
  | 1700 | 5021 | PASS, 0 overlaps |
  | 1800 | 4971 | **FAIL** — `EMC_Source` vs `StoppingTargetMother`, 3.401 cm |
  | *(EMC_Source walked 5000 → 4850)* | | |
  | 1900 | 4921 | PASS, 0 overlaps |
  | 2000 | 4871 | PASS, 0 overlaps |
  | 2100 | 4821 | **FAIL** — 2 overlaps, see below |

  2000 keeps 42 mm below the 2042 wall — the same margin convention as the
  1100/1142 and 1700/1742 pairs.
- **★ THE STOPPING RULE, and why 2000 is the end of the line.** Extend only
  by moving **massless bookkeeping volumes**, never real material.
  `EMC_Source` is a 20 µm vacuum disc nothing in this chain reads, so it was
  walked 5300 → 5000 → 4850 (staying above `EMC_Source2` at 4800, so VD
  ordering survives — 4800 is the floor for that key). It is now done
  moving, because the extent-2100 failure names **two** walls:

  | volume pair | depth | side | movable? |
  |---|---|---|---|
  | `EMC_Source` vs `StoppingTargetMother` | 3.401 cm | upstream | yes (relocatable VD) |
  | **`ST_Out` vs `protonabs1`** | 250 µm | downstream | **NO — material** |

  `VirtualDetector_ST_Out` is placed FROM the target's own downstream end
  (`VirtualDetectorMaker.cc`, `targetOffset + shift`), so it rides the stack
  outward and reaches the proton absorber at extent ≈ 2060. Unlike
  `EMC_Source` it cannot be relocated out of the way — it is *defined by the
  object under study*, and what it hits is real. So further upstream VD
  moves buy nothing past ~2042.
- **Why the wall moved, and the two claims it corrects.** The stack is
  CENTRE-pinned at z0=5871 and grows SYMMETRICALLY, so the ceiling is set by
  whichever edge hits first: upstream `2·(5871−5000) = 1742` (EMC_Source),
  downstream `2·(6901.02−5871) = 2060` (IPA). Both earlier stories were
  wrong:
  - **The IPA is not the constraint.** `protonabsorber.zStartInMu2e =
    6901.02` pins the absorber ABSOLUTELY (measured identical at extent
    400/800/1100); the `ipa_dist = 625 − (extent−800)/2` expression varies
    precisely SO THAT it does not move. At extent 1100 the downstream edge
    is 6421 — 480 mm clear.
  - **`extent ≈ 1142` was stale.** It assumed `EMC_Source` at its stock
    z=5300. The spec already relocates it to **5000**
    (`zEMCSourceInMu2e`, a plain `c.getDouble` default — one config line,
    no source patch), because at 5300 it was the upstream wall. The VD is a
    20 µm disc of `ds.vacuumMaterial` (`vd.halfLength=0.01`): zero mass, no
    scattering, and NO foils-family stage reads virtual detectors (only
    `pot_only` instantiates `ReadVirtualDetector`), so relocating it is
    physics-neutral. Moving it beats disabling it — the VD and its ordering
    against `EMC_Source2` (4800) are preserved.
  - The 2026-07-27 design spec §"The 1100 ceiling is measured, not round"
    still documents the pre-relocation state; it now carries a SUPERSEDED
    banner. `tests/test_foilspf_spec.py`'s corridor assertion
    (`extent ≤ 6271 − vd` = 1271) was ALSO wrong — it mixed the current
    upstream wall with 6271, a downstream z_end from the pre-pin regime,
    and would have blocked this extension. Replaced with the symmetric
    two-wall model derived from the rendered spec.
- **Still open — z0.** Growth is symmetric, so the upstream edge pays the
  whole cost while ~180 mm still sits unused downstream at extent 1700
  (edge 6721 vs IPA 6901). Sliding the centre downstream would buy more,
  but that is a deliberate design question (a z0 slide was tried 2026-07-31
  and reverted as backwards), not a bound bump.
- ~~Deck staleness~~ RESOLVED 2026-08-03: `docs/foilspf_beamer.pdf` rebuilt
  at n=80 (commit `ffc5617`) with the 03R02_00 champion, 04R01_00 record,
  and the extent-ceiling story. Goes stale again when the extent scan +
  foilspf2k verdicts land — refresh as one unit (text + figures).
- ~~Score the designed extent scan / extent gate~~ **CLOSED 2026-08-03**:
  scan measured, GP graded 8/8 within 0.43σ, curve flattens by 1700–2000
  (A's last step +0.04 at 1.1σ for +8% flash) ⇒ **no upstream-shift
  corridor work, no further extent campaigns**. See the ★ scan bullets in
  Key facts.
