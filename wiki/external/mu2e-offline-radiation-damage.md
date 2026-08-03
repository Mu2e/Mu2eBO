---
type: external
title: mu2e-offline-radiation-damage
description: Offline has NO DPA/NIEL scorer (2026-06-07); only G4PSDoseDeposit3D
  + custom scorerDose{Prompt,Residual} in Mu2eG4ScoringManager.cc
status: active
timestamp: '2026-06-07'
---

# mu2e-offline-radiation-damage

## Summary
Inventory of radiation-damage / dose scoring primitives implemented in
`Mu2e/Offline` as of 2026-06-07. **DPA (displacements per atom) and NIEL
(non-ionizing energy loss) are NOT implemented in Offline**: there is no
`G4NIELCalculator`-based scorer, no Norgett-Robinson-Torrens / Lindhard model,
and no post-processor in Offline that converts `StepPointMC` to DPA. What
Offline *does* have is **ICRP-116 fluence-to-dose conversion** (effective +
ambient dose, prompt + residual) — radiation-protection grade, not
displacement-damage. Calorimeter DPA studies in the experiment have
historically been done with **MARS** (FORTRAN legacy, repo `Mu2e/MARS`,
file `m1519.f` is the org's only `"displacement damage"` hit), not Offline.
Any DPA calculation inside Offline requires a custom `G4VPrimitiveScorer` or
offline post-processing of step records.

## Key facts

- **Search evidence (2026-06-07, `gh api search/code repo:Mu2e/Offline`):**
  - `"displacements per atom"` → 0 hits
  - `"radiation damage"` → 0 hits
  - `"displacement damage"` → 0 hits
  - `NIEL` → 1 hit (`TrackerConditions/data/ElementsList.data`, a Geant4-style
    element table — NOT a NIEL calculator)
  - `filename:DPA` → 7 hits, all substring noise inside `StoppedParticles*`
    module names

- **Central scorer wiring is `Mu2eG4/src/Mu2eG4ScoringManager.cc` (~10.7 kB).
  Registered G4 primitive scorers (exhaustive list):**
  - `G4PSCellFlux3D`
  - `G4PSDoseDeposit3D`
  - `G4PSEnergyDeposit3D`
  - `G4PSFlatSurfaceFlux3D`
  - `G4PSPassageCellFlux3D`
  - `G4PSTrackCounter3D`
  - `G4PSVolumeFlux3D`

- **Mu2e-custom scorers (also in `Mu2eG4ScoringManager.cc`):**
  - `scorerDosePrompt` (Effective + Ambient dose variants)
  - `scorerDoseResidual` (Effective + Ambient dose variants)
  - Backed by **`Mu2eG4/inc/scorerFTDConverter.hh`** — Fluence-to-Dose using
    ICRP-116 coefficients. Particles supported: γ, e±, μ±, π±, p, n. Lookup
    tables in `Mu2eG4/data/Neutron_ambient_dose.dat` + `Neutron_effective_dose.dat`.
    `method="ISO"` default (isotropic irradiation geometry).
  - No DPA / NIEL / displacement-damage custom scorer.

- **Where DPA *does* live in the Mu2e GitHub org:** **`Mu2e/MARS` repo, file
  `m1519.f`** is the org's only `"displacement damage"` hit. MARS is the
  legacy FORTRAN transport code; calorimeter rad-damage studies for the CsI/
  BaF₂ choice were run there (or in external Geant4 standalones / FLUKA), NOT
  in Offline. The 25 org-wide `NIEL` hits are all FPGA/firmware noise
  (TDAQFirmware, CRV_FEB, FEB_ArtyS7-50 Xilinx FIFO netlists) — no physics.

- **Tempting-but-broken existing surface:** `Mu2eG4SensitiveDetector::ProcessHits`
  writes a `nonIonizingEdep` field on `StepPointMC` from the G4 step's
  `GetNonIonizingEnergyDeposit()`. **In QGSP_BERT this is silently zero**
  for protons on heavy nuclei because the relevant inelastic processes never
  call `G4Step::ProposeNonIonizingEnergyDeposit`. Cross-ref: ruled out as
  Path A for bo-prodtarget DPA scoring (2026-06-07, see [bo-prodtarget](/projects/bo-prodtarget.md)).
  Do not use as a DPA proxy without confirming non-zero on your physics list.

- **Adding DPA would require:** writing a `G4VPrimitiveScorer` subclass that
  invokes `G4NIELCalculator` (available in Geant4 ≥10.4) inside `ProcessHits`,
  registering it in `Mu2eG4ScoringManager::initialize`, and wiring a scoring
  mesh through a `surfaceCheck.fcl`-style geometry placement. OR post-process
  per-step `StepPointMC` records offline with a Norgett-Robinson-Torrens model
  (no Offline infrastructure exists for this today).

## Cross-links
- Related: [mu2e-offline](/external/mu2e-offline.md), [mu2e-overlap-check](/external/mu2e-overlap-check.md)
- Source files: `Mu2e/Offline/Mu2eG4/src/Mu2eG4ScoringManager.cc`
- External: [Mu2e/Offline](https://github.com/Mu2e/Offline), [G4NIELCalculator docs](https://geant4-userdoc.web.cern.ch/UsersGuides/PhysicsReferenceManual/html/electromagnetic/utilities/niel.html)

## Open questions / TODO
- Confirm whether mmackenz workflows or `Run1BAna` have any external DPA
  post-processor — search there too if it ever becomes relevant.
