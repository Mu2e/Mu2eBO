---
type: concept
title: budget-sob-picker
description: '`--picker budget_sob`: maximizes GP-mean sob SUBJECT TO predicted
  flash <= the deployed damage budget (constraint applied at mean-k*sigma) — the
  deployment-facing sibling of pareto_sob, whose unconstrained picks land +50-70%
  over budget and are unbuildable; wired 2026-08-10'
status: active
status_note: 'first production round foilspfbpz07 launched 2026-08-10 (k=0.5,
  q=20, 40 evals) via AUTORESEARCH_BUDGET_KSIGMA=0.5, an env override REMOVED
  2026-09-24 (Phase A); GP predicts ~4.13 reachable at budget vs 4.00 measured'
timestamp: '2026-09-24'
updated_note: 'Phase A (2026-09-24): AUTORESEARCH_FLASH_BUDGET and
  AUTORESEARCH_BUDGET_KSIGMA are gone; the budget and k now come from the
  study''s constraints[0].max / k_sigma'
---

# budget-sob-picker

## Summary
`budget_sob` answers the only question that matters for deployment: *what is the
best S/√B we can get **without exceeding the radiation damage of the target
already in the beam**?* It is a small variant of
[pareto-sob-picker](/concepts/pareto-sob-picker.md) — same Sobol pushforward over
the GP posterior mean, same min-distance thinning — with one addition: candidates
must satisfy a constraint on the second objective before being ranked by sob.
Since 2026-08-19 it is the ONLY sob-corner picker (`pareto_sob` retired,
subsumed). It exists because three `pareto_sob` exploit rounds produced a 4.41 record that
**cannot be built** (+60% damage), while the best *buildable* design sat
untouched at 4.00.

## Key facts

- **The constraint is a lower bound on the maximized axis.** The constrained
  objective (e.g. `flash_edep`, `transform: log10`, `direction: min`) is
  carried on a maximized GP axis, so `flash <= budget` becomes a lower bound
  on that axis. `core/botorch_predict.py:_problem_from` turns the study's
  `constraints[0]` into a `surrokit.Constraint(axis=i, min=axis_value(...),
  k_sigma=c.k_sigma)`; feasibility is checked at `mean - k*sigma >= min`,
  i.e. at the k-sigma level, NOT on the mean — a pick whose true damage lands
  above the line contributes nothing to the deployment question. Picker name
  `budget_sob` maps to surrokit picker `constrained_max`
  (`core/botorch_predict.py:147`).
- **Since Phase A (2026-09-24) the budget and k are STUDY DATA, not env
  vars.** `AUTORESEARCH_FLASH_BUDGET` and `AUTORESEARCH_BUDGET_KSIGMA` are
  GONE — there is no code left that reads them. A study's
  `constraints[0].value` (JSON key `max`) is the damage-budget line and
  `constraints[0].k_sigma` is `k`. Every live foilspf-family study
  (`foilspf`, `foilspfbp`, `foilspfbpx`, `foilspfbpz`, `foilspf2k`,
  `foilspfbw`, `foilsflash`) carries the SAME deployed-target line, `max:
  6.85443e-07` (MeV/POT, was the old code constant `DEP_FLASH_PER_POT`), and
  `k_sigma: 1.0` (the old code default). To reproduce an UNCONSTRAINED corner
  round, or a different `k`, copy the study directory to a new name +
  leaderboard on `$AUTORESEARCH_STUDY_PATH` and edit `max`/`k_sigma` there —
  editing the live study in place is not the pattern (it would also move
  the deployment line for every other picker/round reading it).
- **foilspfbpz07 (2026-08-10) ran with `k=0.5` via the now-removed
  `AUTORESEARCH_BUDGET_KSIGMA=0.5` env override.** Reproducing that k today
  means a study copy with `k_sigma: 0.5`, not an env var.
- **`k` is the real tuning knob.** MEASURED on the 337-row foilspfbpz board
  2026-08-10, q=20 (numbers below predate the env->study-field move and are
  unaffected by it — same GP, same math):

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
- Source files: `core/botorch_predict.py:_problem_from` (constraint
  assembly), `core/botorch_predict.py:compute_explore_picks` (`budget_sob`
  -> `constrained_max` mapping), `core/study.py` (`StudyConstraint`,
  `constraints` parsing), `mode_specs/foilspfbpz.json` (a live study's
  `constraints` block), `graph/closed_loop.py:52` (`PICKER_CHOICES`). The
  picker BODY (`constrained_max`) itself lives in the surrokit engine repo,
  not here (see [surrogate](/drivers/surrogate.md) "Surrokit extraction");
  the old `_budget_sob_picks`/`DEP_FLASH_PER_POT` symbols and their direct
  unit tests (`test_budget_sob_picks_respect_the_damage_constraint`,
  `test_budget_sob_refuses_when_nothing_is_feasible`) were deleted with
  that extraction (2026-08-28).

## Open questions / TODO
- Does the measured best-at-budget actually clear 4.00? foilspfbpz07 answers it.
- If picks systematically land ABOVE the budget once measured, the GP's flash
  posterior near the line is biased low and `k` should rise — check the
  in-budget fraction at drain before re-tuning.
