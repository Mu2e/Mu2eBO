# TSdA — Transport Solenoid downstream Absorber

**Type:** concept
**Status:** active
**Updated:** 2026-07-17

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
  *was never varied* by [[bo-michael]] (mode retired 2026-07-12).

## Cross-links
- Used in: [[bo-michael]]
- Related: [[col5-shield]], [[degrader]], [[bfield-at-helical-plug]], [[stopping-target-foil-base-spec]]
- Source params: `Offline/Mu2eG4/geom/geom_run1_*.txt`
