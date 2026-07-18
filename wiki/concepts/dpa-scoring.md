---
type: concept
title: DPA scoring for the Mu2e production target
description: Mu2e Stickman design point = peak 10 DPA/yr Inconel 718 (arXiv 2508.18450);
  Geant4 11.3 has no DPA scorer but ships G4NIELCalculator; recommended path is
  custom SD + NRT (E_d=40 eV) piggybacked on stickman-sd-unwired fix
status: active
timestamp: '2026-06-07'
updated_note: Path B shipped; Path A failure mechanism corrected — ShieldingM (not
  QGSP_BERT) IS the Mu2e physics list, but tracking-cutoff strands recoils in totalEdep
  so stock-SD NIEL still ≡ 0
---

# DPA scoring for the Mu2e production target

## Summary
Displacements-per-atom (DPA) is the radiation-damage figure of merit for the
Inconel 718 production target. Mu2e's published design point is **peak ~10
DPA/year** (arXiv 2508.18450, MEDSI 2025) — anchored to SNS measurements
showing solution-annealed Inconel 718 *gains* ductility up to 10 DPA proton
irradiation. This page captures the conventions and the implementation menu
for adding a DPA scoring channel to [bo-prodtarget](/projects/bo-prodtarget.md) (currently only
`mu_per_POT` is wired).

## Key facts
- **Mu2e design number**: **peak 10 DPA/year** Inconel 718 in Stickman v1.0
  (arXiv 2508.18450). This is the motivation for picking Inconel 718 over WL10
  tungsten — W embrittles, In718 anneals/ductilizes under proton irradiation.
- **PS coil DPA limit** is the binding number on integrated beam power, not
  the target plates: **~5×10⁻⁵ DPA before annealing** on PS superconducting
  coils (arXiv 1710.03591); coils annealed yearly to keep RRR ≥ 100. Target
  plate lifetime is comfortably above 1 year at design current.
- **Standard formula — NRT-DPA** (Norgett-Robinson-Torrens, 1975):
  `DPA = 0.8·T_damage / (2·E_d)` per recoil, summed and divided by N_atoms.
  Used by MARS15 (FermiDPA 1.0 / NJOY ENDFB-VII) and FLUKA.
- **Modern improvement — arc-DPA** (athermal-recombination-corrected;
  Iwamoto JNM 2020, doi:10.1016/j.jnucmat.2020.152261) — NRT systematically
  over-counts metals by ~3×. Use if comparing to published numbers; for
  *relative* BO ranking either is fine.
- **Threshold displacement energy** for Inconel 718: **E_d ≈ 40 eV** (Fe/Ni
  dominant, ASTM E521).
- **Geant4 11.3 has NO `/score/quantity/dpa`** — only 17 primitives, none
  NIEL/displacement. Confirmed against the official command-scoring table.
- **Geant4 11.3 DOES ship `G4NIELCalculator`** (Ivanchenko, 2019). Exposes
  `ComputeNIEL(G4Step*)` + `RecoilEnergy(G4Step*)` per step. Returns MeV
  (Geant4 internal units). Does **not** apply the NRT conversion — user
  multiplies by `0.8 / (2·E_d·N_atoms_in_volume)`.
- **G4NIELCalculator wiring (canonical pattern from TestEm1)**: constructor
  `G4NIELCalculator(G4VEmModel*, G4int verb)`; pass
  `new G4ICRU49NuclearStoppingModel()` (NOT `G4ScreenedNuclearRecoil` — that
  was the wrong guess from round-1 research). **No physics list change
  required** — the calculator owns its model directly, doesn't query
  `G4LossTableManager`. Works for protons in QGSP_BERT out-of-the-box.
- **`AddEmModel` is misnamed — REPLACES `fModel`, doesn't accumulate.**
  Calling it twice silently overwrites. For ion+hadron split, instantiate
  TWO separate `G4NIELCalculator` objects and sum.
- **Particle coverage (`G4NIELCalculator.cc` hard gate `PDGMass > 100 MeV`)**:
  proton ✓, alpha/heavy ion ✓, pion± ✓ (140 MeV, barely); neutron ✗
  (passes mass cut but `G4ICRU49NuclearStoppingModel::ComputeDEDXPerVolume`
  returns 0 for neutrals — use `G4NeutronHPDPA` separately); e±/γ/µ± ✗
  (mass-gated). Neutron damage is the dominant channel in a thick target —
  if neutrons aren't scored, the DPA result is biased LOW.
- **Silent zero trap**: passing the wrong EM model (e.g.
  `G4eCoulombScatteringModel`, `G4hCoulombScatteringModel`) returns 0.0
  with no warning. Only nuclear-stopping models work
  (`G4ICRU49NuclearStoppingModel` preferred).
- **Reference example: Geant4 TestEm7 `PhysListEmStandardNR.cc`** registers
  `G4ScreenedNuclearRecoil` (Mendenhall-Weller) for p/d/t/α/He3/GenericIon
  up to 100 MeV; deactivates Urban MSC below that limit. Closest shipped
  Geant4 example with explicit nuclear-recoil tracking (but doesn't score
  DPA itself — user adds SD).
- **MARS15/FLUKA/PHITS score DPA natively** — Pronskikh's Mu2e-II target
  papers use MARS15; the **Stickman MEDSI 2025 paper (arXiv 2508.18450)
  uses FLUKA** (not MARS15/FermiDPA as round-1 research assumed). Geant4
  groups (us) roll their own.
- **Cross-section tables**: no drop-in CSV exists for proton σ_d(E) on
  Ni/Cr above ENDF cutoff (20 MeV p / 150 MeV n). FLUKA/MARS15/PHITS
  compute σ_d on-the-fly from intranuclear-cascade recoils + Lindhard
  partition. Iwamoto JNM 2020 (arc-DPA) and Matsuda JNST 2020 (0.4–3 GeV
  p on Cu/Fe) publish curves but not numerical tables. **Shortcut**: run
  PHITS with `[t-dpa]` tally on Inconel718 slab @ 8 GeV → dump σ_d(E) per
  element → fold against Geant4 spectrum (half-day task vs multi-week NJOY).
- **σ_d magnitude check**: for protons above ~1 GeV, σ_d is nearly flat
  across metals; Cu at 120 GeV ≈ 2000 b (arc-dpa) / 3500 b (NRT-dpa);
  **expect Ni at 8 GeV ≈ 1500–2500 b (arc-dpa)**, ~2× for NRT.
- **De-facto practice** (RaDIATE / LBNF / T2K with Geant4): online NIEL
  accumulation in a custom `G4VSensitiveDetector` on target volumes, NRT
  applied offline. Offline post-processing of full StepPointMC dumps is the
  fallback when SDs aren't wired.
- **Mu2e Offline DPA infrastructure score**: **0**. Verified in
  `Mu2eG4/src/constructTargetPS.cc` (v13_18_00 backing) — no
  `SetSensitiveDetector` calls on PT plates, no `#include`
  `SensitiveDetectorName.hh` (commented out). Confirms [stickman-sd-unwired](/incidents/stickman-sd-unwired.md)
  still holds in the MDC2025aq Musing.

## Canonical SD snippet (≤30 lines, from TestEm1 + NRT)

```cpp
// SD ctor:
fNIEL = new G4NIELCalculator(new G4ICRU49NuclearStoppingModel(), /*verb*/0);
fEd_eV = 40.0;   // Inconel718 displacement threshold

// In ProcessHits():
G4double Tdam_MeV = fNIEL->ComputeNIEL(step);              // damage energy
if (Tdam_MeV <= 0.0) return false;
G4double T_eV = Tdam_MeV * 1.0e6;
G4double n_NRT = (T_eV < 2.0*fEd_eV) ? 0.0
                                     : 0.8 * T_eV / (2.0 * fEd_eV);
G4LogicalVolume* lv = step->GetPreStepPoint()->GetTouchableHandle()
                          ->GetVolume()->GetLogicalVolume();
G4double Natoms = lv->GetMaterial()->GetTotNbOfAtomsPerVolume()
                * lv->GetSolid()->GetCubicVolume();
fDpaAccum += n_NRT / Natoms;   // dimensionless DPA / event
// Normalize at end-of-run by total POT to get DPA / POT.
```

## Shipped implementation — Path D (dose proxy, FCL-only)

**Decision 2026-06-07**: BO ranks on `total_edep_per_POT` (Inconel plate sum)
rather than true DPA. Ranking-stable correlate; no muse rebuild. Wired via:

- `pipeline_templates/pot_only/template.fcl` — `__PT_SENSITIVE_VOLUMES__` +
  `__PT_DUMPER_BLOCK__` + `__PT_DUMPER_PATH__` tokens.
- `pipeline.py:_parse_n_plates_from_geom` parses `targetPS_numberOfPlates`
  from the materialized geom; `_render_pt_dumper_block(n)` emits N
  `physics.analyzers.ptPlate<i> { module_type: StepPointMCDumper ... }`
  blocks + an N-name `sensitiveVolumes` list.
- `cmd_harvest_pot_only` sums `totalEDep` across all `ptPlate*/nt;1`
  trees → `summary.json` keys `edep_per_POT_MeV` + `total_edep_MeV`.
- `bo_driver.py` — `Point.extras` side channel (NOT calo,
  to avoid `DEFAULT_ALPHA=1e5` drowning the muon objective);
  `ProdTargetMode.extract_extras` populates from summary;
  `format_row` / `load_history_row` thread `edep_per_POT_MeV` through
  the TSV.

**Why Path A doesn't work** (corrected 2026-06-07 after user pointed out
the Mu2e physics list is **ShieldingM**, not QGSP_BERT):
stock `Mu2eG4SensitiveDetector::ProcessHits` writes
`aStep->GetNonIonizingEnergyDeposit()` into `StepPointMC.nonIonizingEdep`
on every step. ShieldingM *does* include `G4NeutronHP`, which *does* call
`ProposeNonIonizingEnergyDeposit` — but only for **sub-tracking-cutoff
recoils** deposited locally at the neutron-interaction vertex. At Mu2e's
default 1 keV production cut, the bulk of displacement-relevant heavy
recoils (Ni/Cr/Fe from elastic + (n,xn) reactions) are tracked as separate
`G4Ion` secondaries — their kinetic energy lands in `totalEdep` on the
ion's own steps, with no `ProposeNonIonizingEnergyDeposit` call (the ion's
own ionization vs nuclear-stopping split isn't populated by ShieldingM's
ion physics). Proton channel adds nothing either (Bertini + QGS leave the
field at 0; their secondary recoils are tracked ions, same trap).
Empirical result: stock-SD smoke (Path D run) gave NIEL = 0 on every
plate across 50 events. Net: Path A is unusable not because no process
calls the setter, but because tracking-cutoff strands the displacement
energy in `totalEdep`.

## Shipped implementation — Path B (real NIEL via custom SD)

**Shipped 2026-06-07** in fork `autoresearch_muse_prodtarget`. New class
`ProductionTargetNIELSD` (`Offline/Mu2eG4/{inc,src}/ProductionTargetNIELSD.{hh,cc}`)
subclasses `Mu2eG4SensitiveDetector`. Dispatch in
`SensitiveDetectorHelper::instantiateLVSDs` (`src/SensitiveDetectorHelper.cc:140-152`)
instantiates the NIEL subclass for any LV named with prefix
`ProductionTargetPlate`; everything else gets the stock SD. No FCL change
required — `sensitiveVolumes: [ProductionTargetPlate00, ...]` is the trigger.

**Critical implementation note — DO NOT use `G4NIELCalculator` directly.**
Its constructor calls `G4LossTableManager::Instance()->SetNIELCalculator(this)`,
a shared-singleton write that segfaults on first event when called from
`instantiateLVSDs` (geometry-construction time, before physics-list init) and
is unsafe under Mu2eG4MT. Workaround: inline the `ComputeNIEL` body
(only ~6 lines) and call `G4ICRU49NuclearStoppingModel::ComputeDEDXPerVolume`
directly. See `src/ProductionTargetNIELSD.cc:60-72`. This bypasses the
singleton entirely.

**Other gotchas surfaced this turn:**
- `G4NIELCalculator` does NOT own its EM model — caller must `delete fModel`
  separately in dtor (verified upstream).
- `G4ICRU49NuclearStoppingModel::Initialise(...)` body is **empty** — calling
  it is a no-op. Constructor sets all needed state (`theZieglerFactor`,
  `g4calc`, static `Z23[]`).
- `MU2E_SEARCH_PATH` (NOT `FHICL_FILE_PATH`) controls geom-file lookup —
  needed when running with `g.txt` in cwd.

**Smoke result (50 events, nominal Stickman pt001)**:
`/exp/mu2e/app/users/oksuzian/dpa_smoke/dpa_summary.json` →
total NIEL 2×10⁻⁴ MeV/POT across 35 plates, peak DPA/yr = 0. That is
**expected for ICRU49 alone**: nuclear stopping is essentially 0 for 8 GeV
primary protons (relativistic), and ICRU49 doesn't model neutron recoils —
which are the dominant DPA channel in a thick Inconel target (this is why
FLUKA in Mu2e Stickman paper gets 10 DPA/yr — it does the full intra-nuclear
cascade + neutron transport). Path B is **plumbing-complete**; getting to
published-magnitude DPA requires either (a) parallel neutron SD, or
(b) inclusion of secondary ion stopping in the cascade output.

Path B does NOT yet feed the BO objective — `total_edep_per_POT` from
[stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md) / Path D remains the ranking channel.

**Grid-harvest gap (2026-06-07)**: even though the patched
`ProductionTargetNIELSD` dispatch is in the autoresearch_muse_prodtarget
fork, `pipeline_templates/pot_only/template.fcl` + `pipeline.py:260-280`
only render `StepPointMCDumper` analyzers for the regular
`g4run:ProductionTargetPlate{i:02d}` product instance (sums to
`totalEDep` → `edep_per_POT_MeV`). The NIEL SD's output instance
(whatever name it writes under) has **no dumper wired**, so the NIEL
StepPointMCs are silently dropped on the grid. `summary.json` carries
only `mu_per_POT`, `edep_per_POT_MeV`, `total_mu`, `total_edep_MeV`,
`total_pot`, `files_seen`, `files_skipped` — no `niel_per_POT_MeV`
column anywhere in the leaderboard pipeline. To capture NIEL on grid
we need: (1) add NIEL-instance dumper to `_render_pt_dumper_block`,
(2) extend `cmd_harvest_pot_only` to sum NIEL totals, (3) extend
`ProdTargetMode.extract_extras` + leaderboard format.

## Implementation menu (deferred — see Path D above)

| | A. Built-in scorer | B. Custom SD + G4NIELCalculator | C. Offline post-process |
|---|---|---|---|
| Viable in Geant4 11.x | **No** | **Yes (recommended)** | Yes (fallback) |
| Where it lives | n/a | `Mu2eG4/src/ProductionTargetSD.cc` + wire in `constructTargetPS`; enable in `POT.fcl` `g4.sensitiveDetectors` | StepPointMC producer on PT plates → python NRT fold |
| Per-step physics | — | `niel = NIELcalc.ComputeNIEL(step)`; `dpa += 0.8·niel/(2·E_d·N_atoms)` | dump (PDG, E_kin, step, vol) → fold σ_d(E,Z) offline |
| CPU overhead | — | **~5–10%** (PT is <0.1% of event volume) | ~30–80% (StepPointMC I/O dominates) |
| Effort | — | ~150 LOC + 1 muse rebuild; reuses missing SD plumbing from [stickman-sd-unwired](/incidents/stickman-sd-unwired.md) | ~50 LOC G4 + 200 LOC Python; needs NJOY/SPECTER σ_d table |
| Per-geometry scalar | — | `sum(dpa_per_plate) / N_POT` | same, in pandas |

**Recommendation: Option B.** The SD plumbing has to be built anyway to unblock
per-plate Edep ([stickman-sd-unwired](/incidents/stickman-sd-unwired.md)); DPA piggybacks on the same
`ProcessHits`. `G4NIELCalculator` already ships in 11.3 — just instantiate
with `G4ScreenedNuclearRecoil`. Hard-code E_d = 40 eV (BO ranking is
invariant to that constant). CPU overhead is a rounding error vs. the
cascade itself, so the 30 s/job [bo-prodtarget](/projects/bo-prodtarget.md) pot_only budget survives.

Option C only wins if you later want to swap NRT ↔ arc-DPA ↔ athermal models
without re-simulating. Defer until BO closes.

## Cross-links
- Related: [bo-prodtarget](/projects/bo-prodtarget.md), [production-target-stickman](/concepts/production-target-stickman.md),
  [stickman-sd-unwired](/incidents/stickman-sd-unwired.md)
- Source files (to-be-created):
  - `backing/Offline/Mu2eG4/src/ProductionTargetSD.cc` (new)
  - `backing/Offline/Mu2eG4/src/constructTargetPS.cc` (wire SD)
  - `Production/JobConfig/beam/POT.fcl` (`enableSD` += `productionTarget`)
- External:
  - [arXiv 2508.18450](https://arxiv.org/abs/2508.18450) — Mu2e Stickman, 10 DPA/yr
  - [arXiv 1710.03591](https://arxiv.org/abs/1710.03591) — Mu2e PS-coil DPA limit
  - [G4 11.3 command scoring (no DPA primitive)](https://geant4-userdoc.web.cern.ch/UsersGuides/ForApplicationDeveloper/html/Detector/commandScore.html)
  - [G4NIELCalculator header (11.3.0)](https://geant4.kek.jp/Reference/11.3.0/G4NIELCalculator_8hh_source.html)
  - [G4NIELCalculator source (master)](https://github.com/Geant4/geant4/blob/master/source/processes/electromagnetic/utils/src/G4NIELCalculator.cc)
  - [TestEm1 SteppingAction.cc — canonical G4NIELCalculator usage](https://github.com/Geant4/geant4/blob/master/examples/extended/electromagnetic/TestEm1/src/SteppingAction.cc)
  - [TestEm7 PhysListEmStandardNR — G4ScreenedNuclearRecoil recipe](https://github.com/Geant4/geant4/tree/master/examples/extended/electromagnetic/TestEm7)
  - [Iwamoto JNM 2020 — arc-DPA](https://doi.org/10.1016/j.jnucmat.2020.152261)
  - [Iwamoto NIMB 2024 — 120 GeV proton DPA measurements](https://doi.org/10.1016/j.nimb.2024.165543)
  - [Matsuda JNST 2020 — Cu/Fe at 0.4–3 GeV p (tabulated)](https://doi.org/10.1080/00223131.2020.1771456)
  - [PHITS (JAEA) — `[t-dpa]` tally, arc-dpa built in](https://phits.jaea.go.jp/)
  - [RaDIATE publications](https://radiate.fnal.gov/publications/)

## Open questions / TODO
- Pick NRT vs arc-DPA. Recommend **NRT** for first cut (matches FLUKA
  published Mu2e numbers in arXiv 2508.18450; ranking is invariant under
  the 3× scale factor).
- **Neutron DPA channel**: G4NIELCalculator does NOT cover neutrons. For
  a thick Inconel target the neutron channel is non-negligible. Options:
  (a) accept proton-only DPA as a lower bound (cheapest, OK for BO
  ranking if neutron-to-proton DPA ratio is geometry-stable), (b) add
  parallel `G4NeutronHPDPA` SD, (c) post-process StepPointMC neutron
  spectrum with PHITS-derived σ_d table.
- Wire `enableSD = [virtualdetector, productionTarget]` in `POT.fcl` without
  inflating `nts.*.POT_vd.root` size more than ~10%.
- Decide BO objective form: **constraint** (`dpa_per_year ≤ 10`, a hard wall)
  or **secondary objective** (Pareto front mu_per_POT vs dpa_per_year). The
  10-DPA wall is well clear of expected variation, so constraint is cheaper.
- arc-DPA vs NRT cross-check on champion geometry (defer until BO closes).
- **`gh search code "G4NIELCalculator" --limit 50`** to find downstream
  HEP/space-radiation repos that already wrap this into an SD (WebFetch
  was sign-in-blocked for GitHub code search in round-2 research).
