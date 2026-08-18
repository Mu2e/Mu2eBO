---
type: concept
title: Saturation is acquisition-relative
description: '"saturated" = flat acquisition signal, NOT fully-mapped front (foilsflash
  tail sat ~9σ beyond evals while the GP knew); the scalar record is the WRONG stop test
  (foilspfbp 2026-08-06) — use budget-conditioned best-sob + Pareto-front bound-hitting;
  end-of-campaign checklist: corner-picker round + sibling-champion transplant probes'
status: active
timestamp: '2026-08-09'
updated_note: 'second production confirmation: foilspfbpz04 pareto_sob round broke the 4.33 "ceiling" to 4.37'
---

# Saturation is acquisition-relative

## Summary
Lesson crystallized by the foilsflashSOBX01 transplant (2026-07-08): a
declared "saturated" BO line means the *acquisition signal* went flat, NOT
that the Pareto front's extremes are mapped. Seven foilsflash campaigns
(201 evals) saturated qNEHVI's hypervolume gradient while the front's true
sob tail sat 3.4% (~9σ) beyond every observed eval — and the GP already
knew it.

## Key facts
- **★★ SECOND PRODUCTION CONFIRMATION — the corner-picker round WORKS
  (foilspfbpz04, 2026-08-09/10).** After 257 evals of hypervolume-driven
  picking had "saturated" the sob record at 4.33, a single `pareto_sob`
  exploit round (q=20 rolling, 40 evals, warm start) scored **mean sob
  4.293 across all 40 picks** (the picker essentially never missed), put
  **12 evals at ≥ 4.33**, and broke the record to **4.37 — three
  independent geometries** (R11_00 zmid +8 / R08_00 +15 / R14_01 +53),
  with 4.36 + three 4.35s behind them: a new, tighter plateau at
  ~4.36±0.01, +1.2% above the qNEHVI-era ceiling. Two of the three record
  geometries sit at |zmid| ≤ 15 — the gain is SHAPE at near-uniform pitch,
  not the pitch rail. All 40 rows are damage-expensive (cheapest 4.37 at
  +52% flash; 0/40 inside the deployed budget), so the budget-conditioned
  verdict (best-at-budget 4.00, search closed) is UNTOUCHED — this maps
  the ceiling, it does not reopen deployment. Checklist status: the
  end-of-campaign corner-picker round is now 2-for-2 (SOBX01 transplant,
  bpz04) at finding tail the acquisition had abandoned.
- **★ THE SCALAR RECORD IS THE WRONG SATURATION TEST (foilspfbp, 2026-08-06).**
  Four campaigns at a fixed 9D box (83 evals) moved the sob ceiling
  4.16 → 4.33 (+4%) — but the ceiling is a 1-D shadow of a 2-D problem, and
  reading it alone gets the stop/continue call **wrong in both directions**:
  - *False "keep going"*: the Pareto front grew 6 → 28 points and the count of
    designs beating the deployed target on both objectives grew 4 → 24, which
    looks like healthy progress. Decomposed by damage budget it is mostly
    **densification, not advance**.
  - *False "stop"*: foilspfbp02 returned 0/20 on sob and looked like a pure
    null, yet foilspfbp03 then displaced the record **by domination** — same
    sob (4.29→4.30, 0.4σ) at **−32% damage** — knocking the old record off
    the front entirely. A repeat campaign never raises the ceiling; it can
    still replace the champion.
  - **The right metric is budget-conditioned**: `best sob subject to
    damage ≤ B`, tabulated for the B values a decision would actually use.
    At B = the deployed target's damage, foilspfbp sat at **3.99 for 70
    evals** (seeds 3.99 → bp04 4.00, i.e. +0.3%, inside the 0.6% noise) —
    and that 3.99 came from a *transplanted seed*, not from any campaign.
    Flat there = saturated for decision purposes, whatever the ceiling does.
  See [bo-foilspf](/projects/bo-foilspf.md).
- **Diagnose the next box by bound-hitting, not by intuition** (same line):
  tally how many *Pareto-front* designs sit within 2% of each box edge. For
  foilspfbp: `rOut_{0,1,2}` pinned at the 120 mm ceiling in **12–15 of 28**
  front designs and `hT_0` at its 20 µm floor in **15 of 28**, while every
  `f_*` sat comfortably interior. That is the optimizer naming its own next
  box — and it costs one pass over the leaderboard.
- **★ TESTING A PINNED BOUND: DESIGN THE TEST TO ISOLATE IT (foilspfbw,
  2026-08-07 — a CONFOUNDED test, recorded as a method lesson).** The
  foilspfbp tally above was acted on directly, but foilspfbw changed **two
  things at once**: the ceiling 120 → 150 mm **and** the parameterization
  (`f × rOut` → `bore + width`, rOut derived as a sum). The campaign did not
  clear foilspfbp's budget-conditioned 4.00 (it reached 3.79) — but **that
  outcome cannot be attributed to either change**, and no conclusion about
  whether the 120 wall binds is available from it.
  - **A first reading of it was wrong and is recorded to stop the repeat.**
    Tallying only the **Pareto front** (7 points) suggested the extra radius
    went unused — but a 7-point front at this stage is dominated by
    *low-damage corner* designs, which is the wrong slice for a question
    about radius. Tallying **high-sob** designs instead: 3 of the top 5
    exceed 120, including one at rOut **150.0** that beats the deployed
    target on both axes (sob 3.46 at −5% damage). Sampling was not the
    limiter either — 5 of 20 evals exceeded 120 against 5.4 expected from
    the prior, and the picker put two picks at exactly 150.
  - **Method rules this justifies.** (1) **Change one thing.** To test a
    bound, move the bound and nothing else; re-parameterizing at the same
    time forfeits the answer. (2) **Pick the right slice**: judge a bound by
    the designs that are *good on the objective the bound was supposed to
    help*, not by front membership. (3) **Check the induced prior**: when a
    knob becomes *derived* (here rOut = bore + w, a sum of uniforms), its
    box edges are corners of the sampling distribution rather than directly
    addressable coordinates — verify the region is actually being offered
    before concluding it was declined.
  - Still open, therefore: whether the 120 mm `rOut` ceiling binds, and
    whether `bore`-direct beats `f × rOut` as a parameterization. See
    [bo-foilspf](/projects/bo-foilspf.md).
- **MEASURED CONFIRMATION (2026-07-27): two identical campaigns, 40 evals, ceiling untouched.**
  `foilsflash23` and `foilsflash25` both ran `hybrid` q=10 rolling ×20 on the noise-fixed GP
  against a leaderboard already dense in the high-sob basin. Neither approached
  `foilsflashBASIN01_00` (sob 3.91): ff25 topped out at 3.76, ff23 at 3.57. Both, however,
  **advanced the Pareto front on the flash axis** (ff25 added 2 of 23 front points). This is
  Mechanism 1 seen from the inside — the acquisition was not idle, it was correctly spending
  its budget where HV was still purchasable, which is exactly NOT the sob corner. **Cost of
  the lesson: ~40 evals × ~4.5 h.** The operational rule this justifies: once a ceiling has
  survived two picker-driven campaigns, a third is a purchase of the same negative result —
  switch to the end-of-campaign checklist below, or redirect the picker to the axis where
  the front still moves. See [bo-foilsflash](/projects/bo-foilsflash.md).
- Mechanism 1 — **HV economics**: extending the front at a corner (sob
  3.77→3.90 while flash worsens 9.9e-7→1.08e-6) adds only a thin sliver of
  hypervolume; once the useful region is mapped, EVERY candidate has
  near-zero expected HV gain, so q-batches spread instead of pushing tails.
  Flat acquisition = what our convergence checks measure = "saturation".
- Mechanism 2 — **interaction pockets**: the max-sob recipe (in-beam thin
  upstream degrader) only pays off when downstream is already optimal;
  ~4/6 knobs must be right simultaneously. Spread sampling rarely lands
  there; the foils line needed its dedicated qlnei era to find it.
- **Acquisition gap, not model gap**: the GP's predicted front tip already
  extended to ~3.9 pre-transplant; foilsflashSOBX01 landed ON the cyan tip
  (see docs/foilsflash_perpot_cloud.png). The surrogate extrapolated
  correctly; no eval was ever *bought* there because HV didn't value it.
- What saturation DID legitimately certify: the flash-relevant region
  (floor corner re-found independently 7×; deployed-optimality conclusion
  untouched — the tail sits at +68% flash).
- **End-of-campaign checklist before declaring a front mapped**: (a) run one
  round of a corner-exploit picker ([qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md) /
  [pareto-sob-picker](/concepts/pareto-sob-picker.md)) to stress the tails, and/or (b) transplant sibling
  lines' champions as 1-eval blind-spot probes ([bo-foilsflash](/projects/bo-foilsflash.md)
  transplant moved the measured ceiling +3.4% for one eval).
- **"Just run more evals" does NOT fix it at any sane budget**: the tail
  incentive SHRINKS as the plateau fills (no fixed hit-rate to buy) —
  empirically the last ~70 foilsflash evals (ff07+ff08, fully warm-started)
  added zero sob-tail extension. **More stats per eval is counterproductive**
  for discovery: 3.77 vs 3.90 was already ~9σ (noise never hid it), and
  tighter posteriors shrink the exploration bonus → faster acquisition
  flat-lining. More jobs buys confirmation, not discovery.
- **Native single-campaign fixes if tails are decision-relevant from day 0**
  (e.g. a budget-scan deliverable like foils_talk slide 6): (1) generous/fixed
  HV ref point (one line in botorch_predict — nadir−10% underprices sob
  strips), (2) **qNParEGO** (botorch drop-in; random scalarization per
  candidate naturally spreads picks along the whole front incl. corners),
  (3) mixed batches (e.g. q=16 qnehvi + 4 qlnei per round), (4) entropy-based
  Pareto acquisitions (principled, heavy). If tails are only
  physics-curiosities (foilsflash: the 3.90 corner costs +68% flash),
  sliver-blindness is qNEHVI working AS DESIGNED — use the checklist instead.

## Cross-links
- Related: [batch-bo](/concepts/batch-bo.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md), [bo-modes](/concepts/bo-modes.md),, [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md)
  [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md), [pareto-sob-picker](/concepts/pareto-sob-picker.md), [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md)
- Evidence: [bo-foilsflash](/projects/bo-foilsflash.md) (foilsflashSOBX01), [bo-foils](/projects/bo-foils.md) (foilsf17R01_07)
- Source files: `botorch_predict.py` (qNEHVI ref-point/HV construction;
  `_qnparego_picks` at :348, `_hybrid_picks` at :400, dispatch at :529-532),
  `graph/closed_loop.py:99` (`PICKER_CHOICES` incl. `qnparego`/`hybrid`)

- **RECOMMENDED default for future multi-objective lines (2026-07-08): hybrid
  batches — e.g. q = 12 qnehvi + 8 qNParEGO per round.** qNParEGO (qLogNEI
  over random Chebyshev scalarizations; botorch ships `sample_simplex` +
  `get_chebyshev_scalarization`) makes every batch a trade-off-preference
  sweep, so tails are patrolled natively; qNEHVI keeps HV efficiency in the
  useful region. Bonus: ParEGO does no HV box decomposition, so a hybrid
  degrades gracefully where pure qNEHVI times out on big fronts (foilsf12
  @history≈366, see [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)). Implementation ≈40 lines in
  botorch_predict.py (per-candidate scalarization loop with X_pending — NOT
  the shared `_optimize(sequential=True)` shape) + a PICKER_CHOICES entry.
  Complementary: fix the HV ref point physically instead of nadir−10%.

## Open questions / TODO
- Adopt the checklist for the next line's wind-down (whatever follows foilsflash).
- **LIVE-VALIDATED 2026-07-08: foilsflash09 (q=10×1, `--picker hybrid`, 10/10
  rows, 0 losses).** Batch spanned the whole front (sob 2.07→3.82, flash
  6.20e-7→1.04e-6). TWO non-obvious findings: (1) **the corners came from the
  qNEHVI half, not the qNParEGO half** — at a well-mapped/saturated front,
  HV-improvement is maximized AT the extremes, so the 6 qnehvi picks took both
  the high-sob (3.81/3.82) and low-sob (2.07) corners, while the 4 qnparego
  picks' uniform-simplex weights landed on the KNEE (3.38-3.58 / near-floor
  flash) — extreme scalarization weights are rare in only 4 draws. So at
  saturation qNEHVI already explores tails; qNParEGO's value is denser knee
  coverage. (Prediction that parego→tails / qnehvi→cluster was backwards for a
  saturated front — likely reverses on an UNsaturated front where the useful
  region isn't the corners.) (2) **the optimizer found sob=3.82 on its own**,
  pushing the campaign-found ceiling 3.77→3.82 (was stuck at 3.77 across 7
  prior qNEHVI campaigns) — almost certainly because the [bo-foilsflash](/projects/bo-foilsflash.md)
  transplant (SOBX01=3.90) is now IN the 206-row training set, re-shaping the
  GP's beliefs so acquisition confidently pushed the upstream-degrader region.
  The transplant didn't just measure a point; it moved where the next
  campaign's acquisition went. Champion corner (3.28/6.28e-7) still
  undominated (all high-sob points cost +60-66% flash).
  **Quantified Pareto attribution (2026-07-09):** qNEHVI half (children
  00-05): 4/6 new-nondominated vs the prior front, all 4 still ON the final
  front (incl. 3.82/3.81), landing at sob 3.66-3.82 / flash 0.74-1.04e-6.
  qNParEGO half (06-09): 3/4 new-nondominated, 2 still on front (07:
  3.58/7.12e-7, 09: 3.55/6.68e-7; 08 sibling-dominated by 09), landing on the
  KNEE that the qnehvi six left EMPTY. R00_09 (parego) = arguably the best
  engineering trade-point of the line: within 6% of champion flash at +0.27
  sob. Verdict: hybrid GAINS — comparable per-pick hit-rate, disjoint front
  coverage; the 60/40 split pays no quality tax. Single-round evidence;
  re-run attribution on foilsflash11.
  **Round 2 (foilsflash11, 2026-07-10): parego delivered EVERYTHING.**
  qNEHVI 0/6 on front (its corner picks re-treaded 3.77/3.75 — the high-sob
  corner is exhausted); parego 2/4 on front including the NEW LINE CHAMPION
  (R00_07, 3.31/5.976e-7, first-ever strict domination of ff05R00_04).
  Two-round tally: qnehvi 4/12 front hits (all round 1), parego 4/8
  (delivered rounds in BOTH, incl. the champion). At deep saturation the
  hybrid's parego fraction is the only part still finding new front — if a
  round 3 repeats this, consider flipping the split toward parego (or
  qnparego-only) for end-of-line campaigns.
- DONE 2026-07-08: `qnparego` + `hybrid` pickers shipped in
  `botorch_predict.py` (`_qnparego_picks` :348, `_hybrid_picks` :400) and wired
  into `graph/closed_loop.py` `PICKER_CHOICES` (:99). Both use the 2-objective
  path; per-candidate simplex weights under one `_seed(round_idx)` block (XOR).
  Validated by foilsflash dry-run smokes (real GP, n=206): qnparego picks spread
  across the front. Still un-battle-tested on a live grid campaign — first
  real multi-objective line to launch should use `--picker hybrid`.
- Complementary and still open: replace the nadir−10% HV ref point with a
  physically-fixed one (one line in `_qnehvi_picks`).
