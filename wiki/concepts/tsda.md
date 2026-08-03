---
type: concept
title: TSdA — Transport Solenoid downstream Absorber
description: TS downstream Absorber; dominant variance knob in mmackenz sweep
status: active
timestamp: '2026-07-17'
---

# TSdA — Transport Solenoid downstream Absorber

## Summary
Aluminum absorber located downstream of the muon stopping target inside the TS.
Its core dimensions (`tsda.rin`, `tsda.halfLength4`) are the dominant variance
knob across mmackenz's hand-designed configurations. Increasing the inner
radius lets more low-energy beam particles through (raising calo nuisance);
decreasing it kills calo stops but starts swallowing signal-side acceptance.

## Key facts
- **Pinned in this BO:** `tsda.r4 = 600 mm`, `tsda.z0 = 4195 mm`,
  `tsda.materialName = "StoppingTarget_Al"` (>85% of mmackenz configs).
- **Optimized:** `tsda.rin` ∈ [0.001, 130] mm (bimodal in priors, one cluster
  near 0, one near 130–135), `tsda.halfLength4` ∈ [7.5, 12.5] cm.
- **Best-known config:** v39 with `rin=130, halfLength4=8.75`.
- **Topology toggles** (`tsda.extra.build`, `tsda.tubes.build`,
  `tsda.helical.build`, `tsda.cutout.build`) — extracted in scraper but
  *was never varied* by [bo-michael](/projects/bo-michael.md) (mode retired 2026-07-12).

## Cross-links
- Used in: [bo-michael](/projects/bo-michael.md)
- Related: [col5-shield](/concepts/col5-shield.md), [degrader](/concepts/degrader.md), [bfield-at-helical-plug](/concepts/bfield-at-helical-plug.md), [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md)
- Source params: `Offline/Mu2eG4/geom/geom_run1_*.txt`
