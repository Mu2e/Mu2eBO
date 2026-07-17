---
type: incident
title: COL5 categorical misclassified COL5Poly as "air"
description: '`COL5Poly` material was being misclassified as "air" in prior loader'
status: resolved
timestamp: '2026-05-15'
---

# COL5 categorical misclassified COL5Poly as "air"

## Summary
The first version of `load_priors()` mapped only `G4_POLYETHYLENE` to the
"poly" categorical bucket, sending mmackenz's dominant `COL5Poly` material
(93/104 configs) into the "air" bucket. This corrupted the GP's understanding
of the COL5 dimension entirely.

## Key facts
- **Symptom:** GP couldn't distinguish poly vs air; COL5 axis looked irrelevant.
- **Root cause:** `mat == "G4_POLYETHYLENE"` predicate missed the `COL5Poly`
  custom material name.
- **Fix:** changed projection to
  `col5 = "poly" if mat in ("COL5Poly", "G4_POLYETHYLENE") else "air"`
- **Render correction:** `render_geom()` now emits `"COL5Poly"` (not
  `"G4_POLYETHYLENE"`) for the "poly" bucket since `COL5Poly` is the
  prior-dominant choice.

## Cross-links
- Concept: [col5-shield](/concepts/col5-shield.md)
- Driver: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)
