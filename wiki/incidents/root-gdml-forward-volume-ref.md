---
type: incident
title: ROOT TGDMLParse segfaults on forward `<volume>` references
description: ROOT TGDMLParse segfaults on forward `<volume>` refs (children must
  precede parents); Geant4 reader is order-tolerant, ROOT isn't; subset extractors
  must DFS post-order
status: resolved
timestamp: '2026-06-01'
---

# ROOT TGDMLParse segfaults on forward `<volume>` references

## Summary
ROOT's GDML reader (`TGDMLParse`) requires every `<volume>` to be defined
**before** any parent `<physvol>` that references it — i.e. children must
appear earlier in the file than their parents. Geant4's GDML reader is
order-tolerant; ROOT's is not. A forward reference triggers
`Error in <TGDMLParse::GetVolume>: Volume X not defined` followed by a
segfault in `TGDMLParse::VolProcess`. Surfaced when ROOT-loading the
extracted stopping-target subtree from [bo-foils](/projects/bo-foils.md) champion
`foilsX07R01_03`.

## Key facts
- **Symptom**: `.x geom.C("foo.gdml")` → `Error in <TGDMLParse::GetVolume>:
  Volume Foil_000x375fd00 not defined` → `Error in <TGeoVolume::AddNode>:
  Volume is NULL` → `*** Break *** segmentation violation` in
  `TGDMLParse::VolProcess` → `TGDMLParse::ParseGDML` → `GDMLReadFile`.
  Hits ROOT 6.36.06 (homebrew on macOS arm64); structural ROOT bug,
  not version-specific.
- **Geant4 ≠ ROOT order semantics**: the same GDML file loads cleanly in
  Geant4 (which is what Mu2e Offline writes the file with via
  `gdmldump.fcl`). Geant4 does a two-pass resolve; ROOT does single-pass
  forward-reference-intolerant parse.
- **Root cause in our extractor**: `extract_stopping_target.py` was
  emitting `<volume>` elements by iterating a Python `set` (`keep_vols`),
  which produces arbitrary order. The full Mu2e GDML happens to be
  topologically sorted by Geant4's writer so ROOT loads it; our subset
  did not preserve that order.
- **Fix** (`bo_foils_proposals/foilsX07R01_03_gdml/extract_stopping_target.py:85-103`):
  replace the `for n in keep_vols` loop with a DFS post-order walk from
  the root volume — children visited (and emitted) before their parents.
  Standalone subtree md5 changed from
  `9c11a7d9267037ae9f4d90a499720a78` →
  `edfa17abd37180a0274f3bbecbdc3cca` (47275 B, identical solid/material
  content, only `<volume>` element ordering changed).
- **Generalizes**: any future GDML-subset extractor for Mu2e geometry
  (e.g. tracker-only, calorimeter-only) must emit volumes in topological
  (leaves-first) order if the consumer is ROOT. Set/dict iteration order
  is not reliable across Python versions either.

## Cross-links
- Related: [bo-foils](/projects/bo-foils.md) (champion `foilsX07R01_03` is what triggered
  this; GDML lives at
  `bo_foils_proposals/foilsX07R01_03_gdml/`)
- Source files:
  `bo_foils_proposals/foilsX07R01_03_gdml/extract_stopping_target.py:85-103`
  (DFS post-order fix block)
- External: ROOT [TGDMLParse](https://root.cern.ch/doc/master/classTGDMLParse.html)

## Open questions / TODO
- None. Fix is local to the extractor; full mu2e GDML emitted by Geant4
  is already topologically sorted so the issue only affects hand-written
  extractors.
