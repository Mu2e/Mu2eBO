# pareto-sob-picker

**Type:** concept
**Status:** active
**Updated:** 2026-06-22

## Summary
A third closed-loop picker (`--picker pareto_sob`) that submits the **highest-sob
points on the GP-predicted Pareto frontier** as real grid evals — the same
frontier the cloud renderer draws. Added 2026-06-22 to test empirically whether
the foils GP's high-sob envelope (~4.06) holds at specific geometries, staying in
`foilsf` and landing in the normal v3 leaderboard. It's a by-hand exploit of the
sob corner.

## Key facts
- **Mechanism** (`botorch_predict.py:_pareto_sob_picks`): Sobol-sample N=16384 in
  the mode's box (seed `42 ^ round_idx`), evaluate GP posterior MEAN for both
  objectives (output 0 = sob, output 1 = −log10 calo, both maximized), build the
  non-dominated mask, return the q frontier points with the **highest predicted
  sob**. Multi-objective fit (keeps calo) → runs the full 4-stage chain (does NOT
  stamp AUTORESEARCH_NO_RUN1B, unlike [[qlnei-sob-only-picker]]).
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
  at the sparse top ([[gp-cloud-rendering]]: envelope ~4.06 vs measured 3.91), so
  pareto_sob picks should **measure ~3.9, below their predicted ~4.0** — i.e. it
  confirms the over-extrapolation rather than breaking the ceiling.
- **Does NOT tie-break the flat top**: real evals at σ(sob)≈0.4%, so distinct
  high-sob picks remain indistinguishable within noise — that needs replicas
  ([[bo-noise-budget]]). pareto_sob answers "do the GP's top predictions hold up",
  not "is A > B".

## Cross-links
- Related: [[qlnei-sob-only-picker]], [[batch-bo]], [[gp-cloud-rendering]],
  [[bo-noise-budget]], [[bo-foils]]
- Source: `botorch_predict.py` (`_pareto_sob_picks`, `compute_explore_picks`),
  `graph/closed_loop.py` (`PICKER_CHOICES`, picker-route guards)

## First live run result (foilsfPS01 R0, 2026-06-23) — GP is WELL-CALIBRATED at the top
10 picks predicted sob 3.73–3.83 **measured 3.69–3.82** — essentially spot-on,
within σ(sob)≈0.4%. So the GP posterior MEAN is accurate at the high-sob corner;
it does NOT over-predict there. **But none beat 3.91** — picks cluster right at
the saturated plateau. Interpretation: the GP simply has no Sobol-sampled point
it *predicts* above ~3.83 (posterior-mean compression at the sparse rail, cf
[[gp-cloud-rendering]] — the rail-extrapolated 4.06 envelope is NOT reachable by
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
