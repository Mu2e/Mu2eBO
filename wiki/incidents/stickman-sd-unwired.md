---
# Stickman production target sensitive detectors are unwired

**Type:** incident
**Status:** active (root-caused 2026-06-07; no fix yet)
**Updated:** 2026-06-07

## Summary
Enabling the `ProductionTarget*Section`/`*EndRing` sensitive detectors in
`POT.fcl` via `SDConfig.enableSD` produces empty `StepPointMCCollection`s
and zero CPU overhead on the MDC2025aq default geometry (Stickman v1.0).
Root cause: the Stickman builder `constructStickmanTarget` does NOT call
`SetSensitiveDetector` on any plate logical volumes. The PT SD enum values
are wired by the Hayman segmented-core builder only.

## Key facts
- Diagnostic: ran POT.fcl with all 8 PT SDs in `enableSD`. Confirmed via
  `mu2e -c POT_with_edep.fcl -n 100`:
  - CPU 173 s / 100 evt = 1.73 s/evt (SAME as POT-only — SDs idle)
  - VmPeak 2.29 GB (vs 2.27 POT-only — no overhead)
  - `product_sizes_dumper` shows all 8 `mu2e::StepPointMCs_g4run_Production*_POT`
    branches present at ~1200 bytes each (10 entries × ~20 bytes overhead)
  - `StepPointMCDumper` on those collections → **0 entries** (empty vectors)
- Root cause: `Mu2eG4/src/constructTargetPS.cc:32` has commented
  `//#include "Mu2eG4/inc/SensitiveDetectorName.hh"`, and the function
  `constructStickmanTarget` (lines 1278-2305) contains zero matches for
  `SetSensitiveDetector` (grep confirmed). The plate `finishNesting`
  block (lines 1705-1713) places plates but never assigns an SD.
- The PT SD enum values (`ProductionTargetCoreSection`, etc.) ARE wired,
  but only by the **Hayman segmented-core** path around
  `constructTargetPS.cc:800` (`ithSection / ithSegment` loop with
  `coreCopyNumber`). Stickman doesn't take that path.
- Dispatch table: `constructTargetPS.cc:90` maps
  `{ProductionTargetMaker::stickman_v_1_0, &constructStickmanTarget}` —
  Stickman gets its own builder, unwired.
- Plate copy number IS set correctly (`ithPlate` passed as copy number to
  `finishNesting` at `constructTargetPS.cc:1710`) — so once SDs are
  wired, `StepPointMC::volumeId()` will map cleanly to plate index.

## Why it matters for bo-prodtarget
The v1 thermal proxy `peak_dose = max_i (Edep_i / mass_i)` (see
[[bo-prodtarget]] thermal-proxy section) requires per-plate Edep scoring.
With Stickman SDs unwired, the proxy is unobtainable from POT.fcl alone
— requires a source patch + muse rebuild (~10 lines, pattern same as
[[muse-backing-pattern]] used for [[calo-constant-across-helical]]).

## Diagnosis heuristic
**Empty StepPointMC collection + zero CPU overhead** when an SD is
enabled means the SD is unwired on the geometry side, NOT that the FCL
`enableSD` line is misspelled. Diagnose by `grep SetSensitiveDetector`
inside the builder function for the active `geom_run1_*.txt` selection,
not by trusting `SDConfig.enableSD`.

## Cross-links
- Related: [[bo-prodtarget]], [[production-target-stickman]],
  [[muse-backing-pattern]], [[calo-constant-across-helical]], [[art-instance-name-no-underscore]], [[g4nielcalculator-ctor-segfault]], [[prodtarget-spacer-supportring-overlap]], [[steppointmcdumper-no-edep]]
- Source files (read-only refs): `backing/Offline/Mu2eG4/src/constructTargetPS.cc:32`
  (commented include), `:90` (dispatch), `:800` (Hayman SD wiring),
  `:1278-2305` (Stickman builder), `:1705-1713` (plate finishNesting,
  needs SD assignment line)

## Open questions / TODO
- Patch + rebuild as part of bo-prodtarget, or upstream the fix via
  Mu2e core (PR to Offline)? Upstream is cleaner but slower; local
  patch (LD_PRELOAD) unblocks immediately.
- Should Stickman get a dedicated `ProductionTargetStickmanPlate` SD
  enum value, or just reuse `ProductionTargetCoreSection`? The latter
  has zero analyzer/downstream impact but conflates geometries.
