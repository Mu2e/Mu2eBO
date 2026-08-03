---
type: incident
title: G4NIELCalculator constructor segfaults at SD-construction time
description: G4NIELCalculator ctor's `SetNIELCalculator(this)` singleton write segfaults
  at SD-construction (pre-physics-list, Mu2eG4MT); fix is inline ComputeNIEL body
  + direct `G4ICRU49NuclearStoppingModel::ComputeDEDXPerVolume` call
status: resolved
timestamp: '2026-06-07'
---

# G4NIELCalculator constructor segfaults at SD-construction time

## Summary
Building `ProductionTargetNIELSD` (Path B) as a thin wrapper around
`G4NIELCalculator` segfaulted on the first event (SIGSEGV / exit 139) at
`Begin processing the 1st record. run: 1 subRun: 0 event: 1`. Root cause:
`G4NIELCalculator`'s constructor calls
`G4LossTableManager::Instance()->SetNIELCalculator(this)`, a shared-singleton
write that is unsafe when invoked from `instantiateLVSDs()`
(geometry-construction time, *before* the physics list is initialized) and
likely racy under `Mu2eG4MT`. Workaround: never instantiate
`G4NIELCalculator`; inline its `ComputeNIEL` body (6 lines) and call the
underlying `G4ICRU49NuclearStoppingModel::ComputeDEDXPerVolume` directly.

## Key facts
- **Smoke layout**: `dpa_smoke/test.fcl` uses `Production/JobConfig/beam/POT.fcl`
  prolog, which selects `Mu2eG4MT` (multi-threaded G4 runner).
- **Crash signature**: log ends at `Begin processing the 1st record`, no
  diagnostic frame, exit 139. Tail looks like the worker thread died inside
  G4's per-event setup, not in our `ProcessHits`.
- **First (wrong) hypothesis**: `G4ICRU49NuclearStoppingModel` was uninitialized.
  Refuted by reading the upstream source — `Initialise(particle, cuts)` body
  is **empty**; the model is fully set up by its constructor (sets
  `theZieglerFactor`, `g4calc`, populates static `Z23[]` under
  `ICRU49NuclearMutex`).
- **Actual root cause**: in `G4NIELCalculator::G4NIELCalculator(...)`:
  ```cpp
  G4LossTableManager::Instance()->SetNIELCalculator(this);
  ```
  This is a singleton write executed at SD-construction time
  (`SensitiveDetectorHelper::instantiateLVSDs`), which runs during geometry
  construction. The LossTableManager is not yet fully wired by the physics
  list at that point; also, with `Mu2eG4MT` the master thread builds the
  geometry and worker threads later try to use this state.
- **Fix shipped**: do NOT call `G4NIELCalculator` at all. Inline the body of
  `G4NIELCalculator::ComputeNIEL` (verified upstream — it's literally
  `length * fModel->ComputeDEDXPerVolume(...)` with a `pdgMass > 100 MeV`
  gate and a `T1`-cap clamp). Hold a `G4ICRU49NuclearStoppingModel*` directly
  and call its `ComputeDEDXPerVolume` per step. See
  `Offline/Mu2eG4/src/ProductionTargetNIELSD.cc:60-72` in fork
  `autoresearch_muse_prodtarget`.
- **Memory ownership**: `G4NIELCalculator` does NOT delete its model
  (upstream-confirmed). Our class owns `fModel` and deletes it in dtor.
- **Verification**: after the fix, the 50-event smoke runs to exit 0 in
  ~56 s, ptmc.art lands with non-zero `nonIonizingEDep` on multiple plates
  (e.g. plate 7 = 4×10⁻⁵ MeV summed over 50 events).

## Cross-links
- Related: [dpa-scoring](/concepts/dpa-scoring.md) (Path B section documents this constraint),
  [stickman-sd-unwired](/incidents/stickman-sd-unwired.md)
- Source files:
  - `autoresearch_muse_prodtarget/Offline/Mu2eG4/src/ProductionTargetNIELSD.cc`
    (the inlined ComputeNIEL is the load-bearing snippet)
  - `autoresearch_muse_prodtarget/Offline/Mu2eG4/src/SensitiveDetectorHelper.cc:140-152`
    (dispatch)
- External:
  - [G4NIELCalculator.cc (master)](https://github.com/Geant4/geant4/blob/master/source/processes/electromagnetic/utils/src/G4NIELCalculator.cc)
  - [G4ICRU49NuclearStoppingModel.cc (master)](https://github.com/Geant4/geant4/blob/master/source/processes/electromagnetic/standard/src/G4ICRU49NuclearStoppingModel.cc)

## Open questions / TODO
- Confirm whether the segfault is the singleton write itself or a
  later read on a partially-constructed `G4LossTableManager`. Not worth
  chasing — the inline workaround is correct regardless.
- If a future need arises to use Geant4's full `G4NIELCalculator` API
  (e.g. ion stopping with multiple EM models), construction must be
  deferred to first `ProcessHits` (after physics-list `Initialise`), with
  per-thread guards. The inline approach sidesteps both concerns.
