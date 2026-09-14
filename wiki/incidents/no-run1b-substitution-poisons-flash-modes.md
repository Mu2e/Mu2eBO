---
type: incident
title: AUTORESEARCH_NO_RUN1B substituted 0.0 for ANY mode's missing 2nd objective
description: cmd_evaluate's qlnei zero-substitution was ungated by stage chain, so a
  fail-soft elebeam failure on foilsflash could land a fake zero-flash row at good sob
  and dominate the Pareto front; gated on grid_stages 2026-07-26
status: resolved
status_note: 'resolved 2026-07-26 in b361e09 by gating the substitution on
  "run1b_mubeam in the mode''s own grid_stages"; latent while foilsflash was
  Python (FoilsFlashMode raised instead), became LIVE the moment that class was
  retired to JSON'
timestamp: '2026-07-26'
updated_note: found by the foilsflash Python→JSON retirement, not by a failure —
  the retirement removed the class whose raise was silently carrying the guarantee
---

# AUTORESEARCH_NO_RUN1B substituted 0.0 for ANY mode's missing 2nd objective

## Summary
`cmd_evaluate` (`core/bo_driver.py`) coerced a `None` second objective to `0.0`
whenever `AUTORESEARCH_NO_RUN1B=1`, for **every** mode. That substitution is
only justified for a mode whose chain contains `run1b_mubeam` — the stage the
qlnei picker deliberately drops. For [bo-foilsflash](/projects/bo-foilsflash.md),
whose chain is `mubeam / mustops_ce / elebeam_flash` and has **no
`run1b_mubeam` at all**, a missing second objective instead means the elebeam
stage failed fail-soft — and writing `0.0` appends a fake zero-flash row at
good sob that **dominates the entire Pareto front at the next GP refit**.

## Key facts
- **The substitution's justification is stage-specific, but the check was not.**
  qlnei stamps `AUTORESEARCH_NO_RUN1B=1` to drop `run1b_mubeam` (~40% wall-clock),
  which legitimately produces `calo=None`; the 0.0 keeps the row landing so
  `obj = sob - alpha*0 = sob` matches qlnei's sob-only objective. Without it,
  `run_evaluate` returns `obj=None` and SqliteSaver crashes serializing the
  None-bearing state (foilsf08R00, 10/10 children, 2026-06-08 —
  [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md)).
  So the substitution must stay — it just must not apply to modes that never
  had the stage.
- **The guarantee was being carried by a class body, invisibly.** The retired
  `FoilsFlashMode.extract_metrics` raised `SystemExit` on missing-or-zero flash,
  so the substitution branch was unreachable for foilsflash. Nothing named that
  dependency; deleting the class (2026-07-26) silently removed the protection
  while every test still passed. **A guarantee implemented as "this other code
  path raises first" is invisible to the code that depends on it.**
- **Blast radius was the live line.** foilsflash + `--picker qlnei` + a fail-soft
  elebeam stage → poison row in the 392-row production leaderboard. Same failure
  class as the **7 poison rows of 2026-07-10** (which landed via the direct-CLI
  evaluate path; the graph path was guarded in `node_evaluate`, that path was not).
- **Fix = derive the condition from the mode's own spec**, not from a mode-name
  list that can go stale:
  `_has_run1b = "run1b_mubeam" in _modes.SPECS[mode.name].grid_stages`.
  When false and the second objective is unresolved, `cmd_evaluate` refuses
  (rc=1) instead of substituting. Generic: correct for every present and future
  mode, including JSON-defined ones.
- **Distinguish UNRESOLVED from RESOLVED-TO-ZERO.** They are different bugs with
  different handling: a key that is absent/null is "unresolved" (this incident);
  a key present with value `<= 0` is a real measurement of zero and is refused
  outright by `JsonMode.extract_metrics` regardless of any env var. Both are
  separately tested.
- Mutation-verified: forcing `_has_run1b = True` turns exactly 2 tests red
  (`test_no_substitution_when_the_mode_never_had_a_run1b_stage`,
  `test_zero_flash_is_never_substituted_for_a_flash_mode`).

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md),
  [gp-free-noise-erases-champion](/incidents/gp-free-noise-erases-champion.md)
  (also a case of the GP being fed a surface with the truth distorted),
  [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md) (what stamps the env var),
  [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md)
  (why the substitution exists at all)
- Source files: `core/bo_driver.py` (`cmd_evaluate`, the `_has_run1b` gate),
  `tests/test_seam_protocol.py`, `tests/test_json_mode.py`
- Commit: `b361e09`

## Open questions / TODO
- The same "unresolved vs fail-soft" ambiguity exists wherever a stage can fail
  soft and still produce a summary. Worth auditing whether any other metric can
  arrive absent-but-tolerated.
