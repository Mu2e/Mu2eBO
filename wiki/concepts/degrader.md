---
type: concept
title: Pion degrader — topology toggle
description: pion degrader Al plate; topology toggle (in-beam vs parked)
status: active
status_note: (pin under review)
timestamp: '2026-05-15'
---

# Pion degrader — topology toggle

## Summary
A 1.75 cm Al plate that can be rotated in/out of the beam line. When IN
(`degrader.rotation < 90°`), it serves as the muon stopping target itself
(*Al-plate topology*). When OUT (rotation = 180°), the conventional foil-stack
acts as the stopping target. These are physically distinct topologies, not
small perturbations, so flipping this changes which prior cluster is relevant.

## Key facts
- **Knobs:** `degrader.build` (true/false), `degrader.rotation` (deg)
- **In-beam if:** `build=true AND rotation < 90.0`
- **Currently pinned:** `build=false, rotation=180.0` (degrader OUT)
- **Cluster sizes in priors** (after metric-completeness filter):
  - degrader=OFF: 76 configs, ceiling obj ≈ 2.10
  - degrader=ON: 20 configs, ceiling obj ≈ 3.46 (v39)
- **Why pinned OFF (current):** keep search space comparable to mmackenz's
  foil-target sweep and to preserve a clean run1a→run1b mapping.
- **Why we may flip to ON:** the obj ceiling is ~1.4 units higher with
  degrader IN, and the priors cluster tightly in
  `rin∈[130,135], hL4∈[7.5,10], hole=21.5`, leaving room for BO to interpolate.

## Cross-links
- Related: [tsda](/concepts/tsda.md)
- Used in: [bo-michael](/projects/bo-michael.md)
- Best degrader-ON candidate: mmackenz v39 (see [mmackenz-priors](/datasets/mmackenz-priors.md))
