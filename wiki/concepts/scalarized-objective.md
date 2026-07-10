# Scalarized objective — `obj = S/√B − α·calo/POT`

**Type:** concept
**Status:** active
**Updated:** 2026-06-19 (recorded why α removal was declined)

## Summary
[[bo-michael]] is a multi-objective problem (maximize Run1A CE S/√B, minimize
Run1B calo_stop_per_pot) collapsed to a single scalar so a stock GP-EI
optimizer can drive it. The weight α controls the trade-off rate: how many
units of S/√B we are willing to give up to halve the calo nuisance.

## Key facts
- **Definition:** `obj = sob − α · calo`, maximized.
- **α default:** `1.0e5` (CLI flag, can be swept)
- **Why 1e5:** mmackenz calo range is 4e-8 .. 2.5e-5; with α=1e5,
  a 1e-5 reduction in calo equals 1.0 unit of S/√B. This is the natural
  cross-over given observed scales.
- **GP convention:** `opt.tell` minimizes, so we feed it `-obj`.
- **Reported alongside obj:** raw `sob` and `calo` are always logged in the
  leaderboard so we can re-scalarize post-hoc with a different α.
- **α moves the CHAMPION, not the FRONT (2026-06-04).** The achievable Pareto
  front (sob vs calo) is set by geometry+physics — **α-independent**. α only
  selects which point on it is obj-argmax. Concrete re-rank of the 251-row v1
  leaderboard (all already on the same front):

  | α | champion | sob | calo |
  |---|---|---|---|
  | 1e4 | foilsX08R04_08 | 3.93 | 1.96e-5 (max-signal corner) |
  | **1e5 (ours)** | foilsX07R01_03 | 3.60 | 1.42e-5 (**the knee**) |
  | 1e6 | foilsX07R09_07 | 0.74 | 9.1e-7 (min-calo corner, signal gone) |

  A 10× α bump (1e5→1e6) slides the champion from the knee to the min-calo
  corner, sacrificing essentially all signal. **α=1e5 sits at the knee** —
  strong sob with a meaningful calo penalty.
- **Picker α-dependence (load-bearing, 2026-06-04):** the SAMPLED saturated
  leaderboard's α-sensitivity depends on the picker:
  - **cl_min / scalarized EI is α-STEERED** — it optimizes `sob − α·calo`
    directly, so a different α drives it to densely sample a different region of
    the front (may never visit the high-sob corner).
  - **qNEHVI / qLogNEHVI is α-INDEPENDENT** — it maximizes the
    `(sob, −log10 calo)` Pareto hypervolume and **ignores α entirely**. Code
    gotcha: `botorch_predict.py:compute_explore_picks` accepts `alpha` (param at
    `:215`, called from `main` at `:247`) but **never references it** in the body
    (`:224-227` = load-history → fit-GP → `_qnehvi_picks` → emit; `_qnehvi_picks`
    is not passed α). Help string says "passed through for **shim compatibility**"
    (`:240`). (NB there is **no `predict_picks`** in this file; `node_predict_picks`
    lives in `graph/closed_loop.py`.) α is vestigial on the qNEHVI path, used only
    for the post-hoc leaderboard `obj` column. So a
    saturated qNEHVI/qLogNEHVI run maps the same front at any α; re-rank for
    free afterward. See [[batch-bo]].
- **α-FREE reporting alternative: best-sob-at-calo-budget (2026-06-04).** Instead
  of a single α-champion, report the empirical front as `max sob s.t. calo ≤ B`
  at a few interpretable calo budgets `B` — no α. Over **all 343 foils evals
  (v1+v2+v3)**, `calo ∈ [8.2e-7, 2.6e-5]`, `sob ∈ [0.59, 3.93]`:

  | calo budget B | best sob | at calo | n elig |
  |---|---|---|---|
  | ≤ 1e-6 (clean) | **0.74** | 9.07e-7 | 5 |
  | ≤ 2e-6 | 1.43 | 1.99e-6 | 24 |
  | ≤ 5e-6 | 2.05 | 4.68e-6 | 56 |
  | ≤ 1e-5 (knee) | **3.05** | 9.94e-6 | 120 |
  | ≤ 2e-5 | 3.62 | 1.48e-5 | 196 |
  | unconstrained | **3.93** | 2.14e-5 | 343 |

  Recommended scoreboard = **clean/knee/max = `sob @ calo≤{1e-6,1e-5,∞} =
  {0.74, 3.05, 3.93}`**. Shape is **steep then flat**: sob climbs 0.74→3.05 over
  1e-6→1e-5, then only 3.05→3.93 to 2e-5 → **~80% of max signal is reached by
  calo ≤ 1e-5** (the operational sweet spot). The `1e-6` point is sparse (n=5,
  at the calo floor) and extreme — "near-background-free ⇒ almost no CE signal."
  - **The "knee" is SOFT, not a sharp inflection (2026-06-04).** The empirical
    Pareto front is **44 non-dominated points** (over 346 evals); the marginal
    slope `ΔS/√B per 1e-6 calo` drops only **~3×** across calo≈1e-5
    (**≈0.26 below → ≈0.083 above**), and per-segment slopes are noisy
    (0.01–1.7) on the discrete pooled data. So "1e-5 = knee" is a round-number
    stand-in for "where the return drops off," NOT a rigorously located
    max-curvature point — prefer stating the defensible "~80% of max signal by
    calo≤1e-5" over asserting a sharp knee. Provisional: the front shifts as
    new evals land.
  Picking the budget `B` that matches the real Run1B detector spec is the
  *interpretable* version of "pin α" (a calo budget, not an abstract weight).
  Re-derive: `max(sob)` over each leaderboard subset with `calo<=B`.

## Why α is NOT removed from the code (decided 2026-06-19: leave as-is)
Tempting to delete α to avoid confusion (it's qNEHVI-irrelevant), but a clean
removal is high-blast-radius and was declined:
- **Not purely cosmetic** — the skopt `cl_min`/EI fallback picker AND the CLI
  `propose`/`evaluate` verbs genuinely optimize `sob − α·cost` (only qNEHVI
  ignores it). Removing α means also deciding the fallback's fate.
- **Schema-locked** — every mode's `format_row` writes `alpha`+`obj` columns and
  the leaderboard header is locked at first write (`append_history`). Dropping
  the columns desyncs the writer from EVERY existing leaderboard's header →
  misaligned TSVs unless all are migrated (~10+ files).
- **Live-campaign hazard** — changing the schema while campaigns append (ipa02,
  pt6d11, …) corrupts in-progress files.
Resolution: keep α, rely on this page + [[bo-ipa]] documenting it as vestigial.
Don't re-propose removal as a quick edit.

## Open questions / TODO
- **α=1e5 is a scale-matching PLACEHOLDER, not physics-derived (flagged
  2026-06-04).** It was set so `α·calo ≈ 1–2` is numerically comparable to
  `sob ≈ 3` — a normalization, NOT a measured trade-off ("1 unit of S/√B is
  *worth* a 1e-5 calo reduction" was never established). Consequence: the
  **champion is α-contingent and genuinely flips** — across α ∈ [1e4, 1e6] the
  argmax moves twice (1e4→`foilsX08R04_08` sob 3.93 → 1e5→`foilsX07R01_03` sob
  3.60 → 1e6→`foilsX07R09_07` sob 0.74), so `obj=2.017`/`2.178` and the whole
  ranking are placeholder slices. **The α-independent Pareto FRONT is the
  durable result; the champion is the shaky part.** The BO itself is unaffected
  (qLogNEHVI is α-free — see Key facts). **Principled fix is PHYSICS, not a BO
  knob:** derive α from `d(CE sensitivity)/d(calo_stop_per_pot)` — how much real
  signal significance you'd trade to cut the Run1B calo background — an analysis
  / sensitivity-calc question (mmackenz / Run1BAna). Until then, report the
  front + a champion *band* over α, don't oversell a single `obj`.

## Cross-links
- Related: [[g4-speed-knobs]]
- Driver: [[autoresearch-bo-michael]]
- See also: [[bo-modes]] (which `sob` value the optimizer reads vs the report),
  [[batch-bo]] (qNEHVI explores the front α-free; defer-α two-phase strategy)
