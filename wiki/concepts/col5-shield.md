# COL5 — TS COL5 polyethylene shield

**Type:** concept
**Status:** active
**Updated:** 2026-05-15

## Summary
The fifth Transport Solenoid collimator's inner material. mmackenz uses three
variants. For [[bo-michael]] we collapse them into a binary categorical
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
- Related: [[tsda]]
- Used in: [[bo-michael]]
- Bug history: [[col5-projection-bug]]
