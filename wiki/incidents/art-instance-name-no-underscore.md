# art instance-name rejects underscore

**Type:** incident
**Status:** resolved (2026-06-07; patched in autoresearch_muse_prodtarget fork)
**Updated:** 2026-06-07

## Summary
Path D DPA wiring was hard-blocked because `art::OutputModule` rejects any
product instance name containing `_` (parsed as the field separator in
`Type_Producer_Instance_Process`). The Stickman plate sensitive-detector
collection inherits its instance name from the logical-volume name
`ProductionTargetPlate_<i>`, which contains the forbidden underscore. art
fails at module construction with:

```
Illegal character(s) found in instance name ProductionTargetPlate_0
```

rc=9 at module construction — never reaches G4 init.

## Key facts
- art parses `BranchKey` as 4 `_`-separated fields, so `_` in any field is
  fatal. Verified at `art::ProductRegistryHelper` / module construction.
- Stickman LV name is hardcoded at `constructTargetPS.cc:1667`:
  `"ProductionTargetPlate_" + std::to_string(ithPlate)`.
- `SensitiveDetectorHelper::instantiateLVSDs` uses the LV name verbatim as
  the StepPointMC product instance name → underscore propagates → art dies.
- **Fix (3-line patch in autoresearch_muse_prodtarget fork)**: replace
  with zero-padded `%02d` (no underscore, preserves lexicographic order):
  ```cpp
  char plateNameBuf[64];
  std::snprintf(plateNameBuf, sizeof(plateNameBuf),
                "ProductionTargetPlate%02d", ithPlate);
  std::string plateName = plateNameBuf;
  ```
  Add `#include <cstdio>` near the top of the file.
- Patched library: `autoresearch_muse_prodtarget/build/al9-prof-e29-p101/
  Offline/lib/libmu2e_Mu2eG4.so` (built via mgit + muse against
  v13_18_00 backing).
- **Production pipeline impact**: `pipeline.py:_render_pt_dumper_block`
  must emit the patched names (`%02d`); already updated in
  `pipeline.py:266`. The patched libmu2e_Mu2eG4.so must be shipped in
  the grid `Code.tar.bz2` for the new sensitiveVolumes list to work.

## Cross-links
- Related: [[dpa-scoring]], [[stickman-sd-unwired]],
  [[steppointmcdumper-no-edep]], [[prodtarget-spacer-supportring-overlap]], [[uproot-cannot-read-steppointmc]]
- Source files: `autoresearch_muse_prodtarget/Offline/Mu2eG4/src/constructTargetPS.cc:1667`
- External: [art ProductRegistryHelper](https://github.com/art-framework-suite/art/blob/develop/art/Framework/Core/ProductRegistryHelper.h)

## Open questions / TODO
- Decide whether the upstream Offline patch should go to Mu2e/Offline
  (rename `ProductionTargetPlate_<i>` → `ProductionTargetPlate<NN>`) or
  stay in our autoresearch fork. Upstream is cleaner long-term.
- The Code.tar.bz2 muse-tarball step still needs to be wired into
  `STAGES["pot_only"]["code_tarball"]` so closed-loop children pick it up.
