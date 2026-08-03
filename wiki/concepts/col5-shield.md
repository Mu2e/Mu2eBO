---
type: concept
title: COL5 — TS COL5 polyethylene shield
description: TS COL5 polyethylene shield categorical
status: active
timestamp: '2026-05-15'
---

# COL5 — TS COL5 polyethylene shield

## Summary
The fifth Transport Solenoid collimator's inner material. mmackenz uses three
variants. For [bo-michael](/projects/bo-michael.md) we collapse them into a binary categorical
{air, poly} because the two poly variants behave indistinguishably to first
order.

## Key facts
- **Material values seen in priors:**
  - `COL5Poly` — custom poly mix; mmackenz default (93 / 104 configs)
  - `G4_POLYETHYLENE` — pure poly variant (4 configs)
  - `DSVacuum` — no shield, vacuum (7 configs)
- **Projection rule** (used by `load_priors` and `evaluate`):
  `col5 = "poly" if mat in ("COL5Poly", "G4_POLYETHYLENE") else "air"`
- **Render rule** (used by `render_geom`): emit `"COL5Poly"` for the "poly"
  bucket (not `G4_POLYETHYLENE`), since `COL5Poly` is the dominant prior.
- **Knob:** `ts.coll5.material1Name`

## Cross-links
- Related: [tsda](/concepts/tsda.md)
- Used in: [bo-michael](/projects/bo-michael.md)
- Bug history: [col5-projection-bug](/incidents/col5-projection-bug.md)
