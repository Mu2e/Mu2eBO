---
type: concept
title: pareto-sob-picker
description: '`--picker pareto_sob`: submits the GP-predicted highest-sob points
  (top-q by posterior-mean sob, min-distance spread; the Pareto mask was removed — name is a misnomer) as real evals; multi-obj (keeps
  calo); by-hand sob-corner exploit; wired 2026-06-22'
status: superseded
status_note: code RETIRED 2026-08-19 — subsumed by budget-sob-picker (same corner scan, budget-constrained); unconstrained picks landed +50-70% over the damage budget
timestamp: '2026-08-19'
updated_note: picker deleted from botorch_predict.py/PICKER_CHOICES; do NOT re-add — budget_sob with a raised AUTORESEARCH_FLASH_BUDGET reproduces it
---

# pareto-sob-picker

## Summary
(**CODE RETIRED 2026-08-19** — `_pareto_sob_picks` deleted; [budget-sob-picker](/concepts/budget-sob-picker.md)
subsumes it: identical Sobol posterior-mean-sob corner scan + min-distance
spread, plus the flash-budget constraint. An unconstrained corner round is
`budget_sob` with `AUTORESEARCH_FLASH_BUDGET` raised. History below kept for
the leaderboard rows this picker produced.)

A third closed-loop picker (`--picker pareto_sob`) that submits the **highest-sob
points on the GP-predicted Pareto frontier** as real grid evals — the same
frontier the cloud renderer draws. Added 2026-06-22 to test empirically whether
the foils GP's high-sob envelope (~4.06) holds at specific geometries, staying in
`foilsf` and landing in the normal v3 leaderboard. It's a by-hand exploit of the
sob corner.

## Key facts
- **Mechanism** (`botorch_predict.py:_pareto_sob_picks`): Sobol-sample N=16384 in
  the mode's box (seed `42 ^ round_idx`), evaluate GP posterior MEAN for both
  objectives (output 0 = sob, output 1 = −log10 calo, both maximized) and return
  the **top-q by posterior-mean sob directly**. NOTE the name is now a misnomer:
  the non-dominated (Pareto) mask this page originally documented was REMOVED as
  a dev-time bug fix (see the explicit "do NOT pre-filter to the Pareto frontier"
  comment at `botorch_predict.py:415-421`); nothing Pareto remains in the picker.
  A `PARETO_SOB_MIN_SPACING = 0.10` filter de-clusters the batch against itself
  and against in-flight `x_pending` points — NOT against history, which the
  function never receives.
- **KNOWN LIMITATION (2026-07-21): it cannot find its own model's argmax.** The
  N=16384 Sobol pool is scored by plain `argsort` with NO refinement — no
  `optimize_acqf`, no L-BFGS-B — which is ~0.20 normalized spacing in 6-D,
  coarser than four of the six fitted lengthscales, leaving 0.03–0.07 predicted
  sob on the table. It also can never return an exact box bound (scrambled Sobol
  is open on the bounds): **0 of 40** pareto_sob rows sit on a bound vs **242 of
  278** acquisition-picker rows. See
  [gp-free-noise-erases-champion](/incidents/gp-free-noise-erases-champion.md). Multi-objective fit (keeps calo) → runs the full 4-stage chain (does NOT
  stamp AUTORESEARCH_NO_RUN1B, unlike [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)).
- **Registry wiring**: dispatched in `compute_explore_picks` alongside
  qnehvi/qlnei; added to `botorch_predict.py` `--picker` choices, closed_loop
  `PICKER_CHOICES` (`graph/closed_loop.py:119`), and the two
  `picker in (...)` subprocess-route guards (`:360`, `:749`). The subprocess
  already forwards `--picker`, so no other change.
- **vs qnehvi**: qnehvi optimizes the acquisition (Expected HV improvement) — it
  explores where the front *could* extend. pareto_sob ignores acquisition and
  just takes the GP's current best-sob mean predictions — pure exploit, no
  exploration value. Use it to *probe/confirm* the top, not to *advance* it.
- **Expected behavior**: on the saturated foilsf front the GP over-extrapolates
  at the sparse top ([gp-cloud-rendering](/concepts/gp-cloud-rendering.md): envelope ~4.06 vs measured 3.91), so
  pareto_sob picks should **measure ~3.9, below their predicted ~4.0** — i.e. it
  confirms the over-extrapolation rather than breaking the ceiling.
- **Does NOT tie-break the flat top**: real evals at σ(sob)≈0.4%, so distinct
  high-sob picks remain indistinguishable within noise — that needs replicas
  ([bo-noise-budget](/concepts/bo-noise-budget.md)). pareto_sob answers "do the GP's top predictions hold up",
  not "is A > B".

## Cross-links
- Related: [budget-sob-picker](/concepts/budget-sob-picker.md) (the deployment-facing sibling: same sob corner, constrained to the damage budget), [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md), [batch-bo](/concepts/batch-bo.md), [gp-cloud-rendering](/concepts/gp-cloud-rendering.md),
  [bo-noise-budget](/concepts/bo-noise-budget.md), [bo-foils](/projects/bo-foils.md), [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md)
- Source: `botorch_predict.py` (`_pareto_sob_picks`, `compute_explore_picks`),
  `graph/closed_loop.py` (`PICKER_CHOICES`, picker-route guards)

## First live run result (foilsfPS01 R0, 2026-06-23) — GP is WELL-CALIBRATED at the top
10 picks predicted sob 3.73–3.83 **measured 3.69–3.82** — essentially spot-on,
within σ(sob)≈0.4%. So the GP posterior MEAN is accurate at the high-sob corner;
it does NOT over-predict there. **But none beat 3.91** — picks cluster right at
the saturated plateau. Interpretation: the GP simply has no Sobol-sampled point
it *predicts* above ~3.83 (posterior-mean compression at the sparse rail, cf
[gp-cloud-rendering](/concepts/gp-cloud-rendering.md) — the rail-extrapolated 4.06 envelope is NOT reachable by
actual sampled means). Net: pareto_sob confirms 3.91 is the real ceiling AND that
the GP's top predictions are trustworthy — two useful results in one batch.

**Full campaign (foilsfPS01 R0+R1, 20 evals, 2026-06-23):** best 3.84
(R01_01), did not beat 3.91. **All 20 evals clustered tightly at the top
(measured 3.69–3.84)** — vs a normal qnehvi run that spans ~0.5–3.9 across the
whole front. That tight clustering is the picker working as designed: pure
exploit of the sob corner, zero front-mapping. Use qnehvi to map the front,
pareto_sob to densely confirm the top.

## Open questions / TODO
- (resolved) picks measured ≈ predicted, clustered 3.69–3.84, did not beat 3.91.
