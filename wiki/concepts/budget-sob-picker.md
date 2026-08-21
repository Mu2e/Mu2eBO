---
type: concept
title: budget-sob-picker
description: '`--picker budget_sob`: maximizes GP-mean sob SUBJECT TO predicted
  flash <= the deployed damage budget (constraint applied at mean-k*sigma) — the
  deployment-facing sibling of pareto_sob, whose unconstrained picks land +50-70%
  over budget and are unbuildable; wired 2026-08-10'
status: active
status_note: 'first production round foilspfbpz07 launched 2026-08-10 (k=0.5,
  q=20, 40 evals); GP predicts ~4.13 reachable at budget vs 4.00 measured'
timestamp: '2026-08-10'
---

# budget-sob-picker

## Summary
`budget_sob` answers the only question that matters for deployment: *what is the
best S/√B we can get **without exceeding the radiation damage of the target
already in the beam**?* It is a small variant of
[pareto-sob-picker](/concepts/pareto-sob-picker.md) — same Sobol pushforward over
the GP posterior mean, same min-distance thinning — with one addition: candidates
must satisfy a constraint on the second objective before being ranked by sob.
It exists because three `pareto_sob` exploit rounds produced a 4.41 record that
**cannot be built** (+60% damage), while the best *buildable* design sat
untouched at 4.00.

## Key facts

- **The constraint is a lower bound on the maximized axis.** `Y[:,1]` is
  `-log10(flash per POT)` and botorch maximizes it, so `flash <= budget` is
  `Y1 >= -log10(budget)`. Implemented as `mean_1 - k*sigma_1 >= thr`, i.e.
  feasibility at the k-sigma level, NOT on the mean — a pick whose true damage
  lands above the line contributes nothing to the deployment question.
  `core/botorch_predict.py:_budget_sob_picks`.
- **`DEP_FLASH_PER_POT = 6.85443e-7` MeV/POT** — the deployed target's damage,
  the deployment constraint line (not a tuning knob). Env-overridable via
  `AUTORESEARCH_FLASH_BUDGET` for a different scenario or re-measured baseline.
- **`k` is the real tuning knob** (`AUTORESEARCH_BUDGET_KSIGMA`, default 1.0).
  MEASURED on the 337-row foilspfbpz board 2026-08-10, q=20:

  | k | feasible / 16384 | predicted sob | predicted flash |
  |---|---|---|---|
  | 0.0 | 9324 | 4.04–4.16 | 5.77e-7 – 6.85e-7 (on the line) |
  | 0.5 | 7557 | 3.99–4.13 | 5.08e-7 – 6.56e-7 |
  | 1.0 | 6061 | 3.93–4.06 | 4.93e-7 – 6.06e-7 |

  k=1 costs ~0.07 of predicted sob by aiming well under the line; k=0 puts about
  half the round over budget. **k=0.5 chosen for foilspfbpz07.**
- **Top-up is feasible-set-only.** `pareto_sob` tops a short batch up from the
  full sob ordering; doing that here would leak over-budget picks into a batch
  whose entire purpose is to stay under the line.
- **Refuses rather than guesses**: `SystemExit` if the GP predicts no feasible
  point anywhere in the box, instead of submitting 40 evals that answer nothing.
- **Why a dedicated round is justified at all**: "best-at-budget stalled at 4.00"
  was measured by campaigns whose acquisition (qNEHVI hypervolume, or pure
  max-sob) never aimed at the budget line — the same reasoning recorded in
  [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md)
  that made the max-sob exploit rounds break a supposed ceiling twice. The budget
  corner had never had a dedicated exploit round before foilspfbpz07.
- **Calibration caveat**: the GP was over-optimistic in the high-sob corner (see
  [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), holdout-refuted >4.4
  tail). The budget region is far more densely sampled by the bp campaigns, so
  better calibration is expected — but 4.13 is a HYPOTHESIS the round tests, not
  a forecast.

## Cross-links
- Related: [pareto-sob-picker](/concepts/pareto-sob-picker.md),
  [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md),
  [gp-cloud-rendering](/concepts/gp-cloud-rendering.md),
  [bo-noise-budget](/concepts/bo-noise-budget.md),
  [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)
- Used in: [bo-foilspf](/projects/bo-foilspf.md)
- Source files: `core/botorch_predict.py:_budget_sob_picks`,
  `core/botorch_predict.py:DEP_FLASH_PER_POT`, `graph/closed_loop.py:101`
  (PICKER_CHOICES), `tests/test_botorch_predict.py`
  (`test_budget_sob_picks_respect_the_damage_constraint`,
  `test_budget_sob_refuses_when_nothing_is_feasible`)

## Open questions / TODO
- Does the measured best-at-budget actually clear 4.00? foilspfbpz07 answers it.
- If picks systematically land ABOVE the budget once measured, the GP's flash
  posterior near the line is biased low and `k` should rise — check the
  in-budget fraction at drain before re-tuning.
