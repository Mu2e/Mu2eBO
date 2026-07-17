---
type: incident
title: geom_run1_a baseline missing TT_MidInner fix
description: '`geom_run1_a.txt` baseline missing TT_MidInner fix; fails in run1b_mubeam'
status: active
status_note: '(open; tracked as task #21)'
timestamp: '2026-05-15'
---

# geom_run1_a baseline missing TT_MidInner fix

## Summary
[autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)'s `render_geom()` emits geom override files that
`#include "Offline/Mu2eG4/geom/geom_run1_a.txt"` as the baseline. That file
lacks two settings present in `geom_run1_b_v06.txt`:
`tracker.inDS2Vacuum=true` and `ds2.halfLength=3825`. With the `bfgeom_DSOff`
field map used by the run1b_mubeam stage, the missing settings cause the
TT_MidInner virtual detector to overlap DS2Vacuum, surfacing as a
`G4Exception GeomMgt0002` overlap during BeginRun.

## Key facts
- **Symptom:** [preflight](/drivers/preflight.md) FAILS with `GeomMgt0002` on mike001-style proposals
- **Root cause:** baseline `#include` choice in `render_geom()`
- **Verified fix:** mimicking v39 with `#include geom_run1_b_v06.txt` instead
  passes preflight (BeginRun completes in ~36 CPU s; only fails later on
  expected `ProductNotFound` for missing GenParticle)
- **Workaround:** none yet — current proposals will fail in the run1b_mubeam
  stage on the grid
- **Fix options:**
  1. Switch `render_geom()` baseline to `geom_run1_b_v06.txt` for both stages
  2. Emit two files (one per stage) with stage-specific baselines
- **v06 baseline is NOT a drop-in replacement** even though it has the
  TT_MidInner fix built-in. v06 configures a single-plate stopping target
  (`halfThicknesses={5.0}, radii={600,600}, z0InMu2e=4195` — same z as TSdA!)
  for plate-target studies. Layering v111-style 38-foil overrides
  (`radii={125 × 38}`) on top is incoherent: the array sizes don't match
  `halfThicknesses`, and Geant4 fails with `VirtualDetector_ST_In outside
  DS2Vacuum`. Verified 2026-05-15 with helical001.
- **What works:** keep `geom_run1_a.txt` as baseline and explicitly emit the
  three patch lines (`tracker.inDS2Vacuum=true; ds2.halfLength=3825;
  ds.hasServicePipes=false`). [bo-helical](/projects/bo-helical.md) does this; preflight on
  helical001 PASSES (rc=1, past_init=True, no geom-fail signature).
- **michael-mode contamination:** `mike_load_priors()` does NOT exclude
  helical configs. v111 (helical) enters the michael GP as a low-calo point
  whose calo rejection actually comes from the helical plug, not foil stack.
  Separate concern from baseline fix; track in [bo-michael](/projects/bo-michael.md) open questions.

## Cross-links
- Related: [stickman-inds2vacuum-stmupstream-overlap](/incidents/stickman-inds2vacuum-stmupstream-overlap.md)
- Driver: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)
- Helper that surfaced it: [preflight](/drivers/preflight.md)
- Helical sibling: [bo-helical](/projects/bo-helical.md)
