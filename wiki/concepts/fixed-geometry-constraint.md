---
name: fixed-geometry-constraint
description: All BO proposals must use the same hardware position for Run1A and Run1B — no moving parts between data-taking periods
type: concept
---

# Fixed-geometry constraint

**Type:** concept
**Status:** active
**Updated:** 2026-05-15

## Summary
A load-bearing design constraint on every BO mode in this project: the
proposed geometry must be **identical** in the Run1A and Run1B data-taking
stages — no part may be physically moved or reconfigured between runs.
This rules out the rotating-degrader trick used by v39 and similar
mmackenz configs, and is why the achievable ceiling under our BO is
substantially below v39's reported obj=3.459.

## Key facts
- **What "moving parts" means in mmackenz workflows:** each config has
  separate `run1a_beam/geom.txt` and `run1b_beam/geom.txt` files. Configs
  that override the same geometry parameter to *different values* in the
  two stages encode an operational rotation/swap between runs, not a
  single static design.
- **Canonical violator: v39.** Its `run1b_beam/geom.txt` sets
  `degrader.build=true, degrader.rotation=60.0` (degrader rotated into
  beam, used as Al stopping target). Its `run1a_beam/geom.txt`
  `#include`s the same file but *overrides* `degrader.rotation=120.0`
  (rotated out of beam). Same physical hardware, two operational
  positions → not allowed under this constraint.
- **What complies:** v98, v111, and all configs that either pin the
  degrader off in both stages or do not override stage-specific values
  at all.
- **Fixed-geometry ceilings in mmackenz priors (joint obj, α=1e5):**
  - degrader=off, foil-stack: v98 → obj 2.095
  - degrader=off, helical: v111 → obj 1.958
  - (For comparison, v39 with moving degrader: obj 3.459 — excluded.)
- **How our BO modes ([[bo-modes]]) enforce it:** [[bo-michael]] emits
  `degrader.build=false` and never overrides any other stage-specific
  value, so the same proposal geom is valid in both Run1A and Run1B
  stages. [[bo-helical]] does the same plus pins helical knobs that
  apply identically to both stages.

## Cross-links
- Related: [[production-target-stickman]]
- Constrains: [[bo-michael]], [[bo-helical]]
- Excluded best: discussed in [[mmackenz-priors]]
- Source: project design choice (no formal spec — recorded here)

## Open questions / TODO
- If at some point the experiment commits to the rotating-degrader
  operational mode, this constraint can be relaxed and the
  v39-regime search space (degrader=on + smaller foils) becomes
  accessible. Re-evaluate then.
