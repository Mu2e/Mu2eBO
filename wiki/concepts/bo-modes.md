# BO modes — which S/√B the optimizer reads

**Type:** concept
**Status:** active
**Updated:** 2026-05-15

## Summary
The Run1A sensitivity report emits S/√B for multiple background hypotheses
(`flat_gamma`, `flat_electron`, etc.). The BO objective uses the **CE-only**
value, *not* the headline number from the report. This is a known sharp edge.

## Key facts
- The optimizer reads `s_over_sqrt_b` from the harvest `summary.json`, which
  is wired to the CE channel.
- `flat_gamma` / `flat_electron` rows in the report are informational —
  changing them does not move the BO.
- Memory pointer: `~/.claude/.../memory/project_bo_modes.md`

## Cross-links
- Related: [[batch-bo]], [[architecture-friction-survey-2026-07]], [[saturation-is-acquisition-relative]]
- Used in: [[scalarized-objective]], [[bo-michael]]
