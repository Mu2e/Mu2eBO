# Harvest denominator hardcoded from STAGES.njobs

**Type:** incident
**Status:** resolved
**Updated:** 2026-05-16

## Summary
`cmd_harvest` and `_extract_calo_per_pot` previously computed denominators
(`mubeam_sim_total`, `ce_simulated_events`, `total_events` for calo) from
`STAGES[stage]["njobs"] * events_per_job` — i.e. the *configured* job count, not
the *actual* file count. When grid jobs OOM, are held, or otherwise fail to
produce output, the denominator over-counts and **`ce_abs_eff`, `s_over_sqrt_b`,
and `calo_per_pot` are biased LOW by the loss fraction** (numerator from actual
files, denominator from full configured count → ratio underestimated).

Detected on helical001 (2026-05-16): the A/B noise test reported
`half_A sob = 1.32` and `half_B sob = 1.31` with `1.32 + 1.31 ≈ 2.63 = full sob`.
That linear scaling is the bug's fingerprint — under correct normalization,
halving the *sample size* should leave `s_over_sqrt_b` (a per-POT extrapolation)
roughly constant, not halve it. The macro divides signal counts by the supplied
denominator, so a hardcoded full-stats denominator scales output linearly with
how much input you actually fed it.

**Fix landed 2026-05-16:** denominators now derived from
`len(<stage>_files) * events_per_job` in both `cmd_harvest` and
`_extract_calo_per_pot`.

## Key facts
- **Bias direction:** always *deflates* `s_over_sqrt_b` and `calo_per_pot`.
  Numerator depends on actual file count; denominator was hardcoded full count
  → ratio (signal-per-POT) is underestimated by `1 − actual/configured`.
- **Bias magnitude:** = (lost-job fraction). helical001 with 194/200 mustops_ce
  jobs and 200/200 mubeam jobs → `s_over_sqrt_b` was reported as 2.63;
  corrected = 2.71 (about 3% deflation from the 6/200 mustops_ce loss).
- **Affected metrics:** `s_over_sqrt_b`, `ce_abs_eff`, `calo_per_pot`. Not
  affected: `stopping_factor` (depends on actual `muminus_stops` counted from
  concat .art via `_count_events_art`, and `mubeam_sim_total` — now both
  use actual counts).
- **Detection signature:** when running the harvest on a subset of mustops_ce
  outputs (e.g. for A/B testing), if half-stats and quarter-stats produce
  proportionally-scaled `s_over_sqrt_b` values that *add up to* the full-stats
  value, the denominator is wrong.
- **Why prior runs didn't catch it:** all configs lost similar fractions of
  jobs (~0-5%), so the GP saw consistently-biased points and could still rank
  them — but the absolute objective values were 0-5% too high.
- **Re-harvest helical001 → leaderboard correction:** old objective +2.018,
  corrected +2.098 (s/√b 2.63 → 2.71); the loss-fraction deflation had been
  *masking* helical001's true gain over the v111 baseline.

## Cross-links
- Driver: [[pipeline]]
- Related: [[grid-job-completion-check]] (the `.art:.log` ratio diagnostic that
  tells you how many jobs were actually used), [[calo-constant-across-helical]], [[events-per-job-mid-flight-edit]]
- Source: `pipeline.py:cmd_harvest`, `pipeline.py:_extract_calo_per_pot`

## Open questions / TODO
- None — fix landed, helical001 leaderboard entry to be updated by re-harvest.
