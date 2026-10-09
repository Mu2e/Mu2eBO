---
type: concept
title: Engine seam friction survey (2026-08)
description: 'friction map of surrokit + the autoresearch glue (2026-08-28): 4 ranked candidates, all executed 2026-08-28; the surrogate facade was deleted 2026-09-22'
status: resolved
status_note: all 4 candidates executed 2026-08-28; facade deleted 2026-09-22
timestamp: '2026-10-08'
---

# Engine seam friction survey (2026-08)

## Summary
An architecture walk of surrokit and its autoresearch glue, three weeks
after the extraction ([surrogate](/drivers/surrogate.md)). The engine core
was sound; the friction sat at the client seam. Four candidates were
ranked and all four were done on 2026-08-28.

## Key facts — the four candidates (all done)
1. **One place builds a `Problem`.** It had been built three ways with
   three constraint policies. Now `core/botorch_predict.py:build_problem`
   is the one seam; the caller-less `surrogate/` facade was deleted
   2026-09-22 after a 15-location sweep found zero callers.
2. **surrokit enforces its own contract:** `fit()` checks
   `len(noise) == Y axes` (the old silent `noise[:m]` slice had been
   load-bearing for qlnei sob-only), picks are clamped in-box,
   integer-free int boxes are refused.
3. **One picker vocabulary.** The MCP `suggest` goes through
   `compute_explore_picks`, so MCP picks are what a closed-loop round
   would submit (`budget_sob` -> `constrained_max`, sob-only qlnei, the
   `42^round_idx` seed).
4. **Test through interfaces:** cherry-picked to two tests (constrained_max
   on a real fitted GP; fit-cache refresh after a same-count rewrite).

## Key facts — still true
- `.mcp.json` passes a relative server path, so servers start from the repo
  root only. The surrokit checkout + `SURROKIT_PIN_SHA` drift test is the
  version contract (the cvmfs interpreter is read-only).
- The MCP stdio client strips the env for spawned servers; a broken env
  shows up as an opaque "Connection closed".

## Cross-links
- Related: [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md),
  [budget-sob-picker](/concepts/budget-sob-picker.md),
  [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)
- Driver: [surrogate](/drivers/surrogate.md)
- Source files: `surrogate/adapter.py`, `core/botorch_predict.py`

## Open questions / TODO
- Whether the `-log10` transform pair should become a surrokit helper or
  stay a client recipe.
