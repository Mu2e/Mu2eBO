---
type: incident
title: StepPointMCDumper has no totalEDep branch
description: stock StepPointMCDumper writes only a VirtualDetector hit struct (no
  totalEDep); `writeVDHit` gated off by default; harvest path switched to `art::RootOutput`
  drop/keep + PyROOT loop (2026-06-07)
status: resolved
status_note: 2026-06-08 (Path B chosen — custom TH1D analyzer)
timestamp: '2026-06-08'
---

# StepPointMCDumper has no totalEDep branch

## Summary
The original Path D harvest plan called for adding a
`StepPointMCDumper` analyzer per plate to dump per-step records into a
TTree readable by uproot. Discovered at first smoke run that the stock
upstream module exposes **only** a VirtualDetector-style hit struct
with no energy-deposit fields. The harvest path in `pipeline.py` that
relied on `ptPlate<i>/nt;1.totalEDep` was therefore broken from the
start — trees existed (540 entries) but had **zero branches**.

## Key facts
- Module path:
  `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_18_00/Offline/Analyses/src/StepPointMCDumper_module.cc`.
- Branch schema (line 175):
  ```
  "x/F:y/F:z/F:time/F:px/F:py/F:pz/F:pmag/F:ek/F:charge/F:pdgId/I:particleId/i:volumeCopy/i"
  ```
  No `totalEDep`, no `nonIonizingEdep`, no `edep`.
- Branch is `nt_` but only filled when `writeVDHit=true` (line 177) —
  **default false**, so even the kinematic fields are absent unless
  explicitly toggled.
- The dumper is designed for VirtualDetector particle flux, not for
  per-volume energy deposition. Wrong tool for DPA scoring.
- **Working harvest path (2026-06-07)**: use `art::RootOutput` with
  drop/keep to ship the StepPointMC collections in a small `.art` file,
  then read with PyROOT:
  ```fhicl
  outputs.PTOut : {
    module_type: RootOutput
    outputCommands: [ "drop *_*_*_*",
                      "keep mu2e::StepPointMCs_g4run_ProductionTargetPlate*_POT" ]
    fileName: "ptmc.art"
  }
  ```
  50 events → 1.4 MB ptmc.art with 35 plate collections.
- **PyROOT (not uproot)** is mandatory because uproot raises
  `NotImplementedError: memberwise serialization of AsVector(mu2e::StepPointMC)`.
  See [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md).
- Reference harvester:
  `/exp/mu2e/app/users/oksuzian/dpa_smoke/make_dpa_plot.py` — uses
  `events.SetBranchStatus` + per-branch loop to avoid loading all 35
  collections at once. Sums `totalEDep()` and `nonIonizingEDep()` per
  plate from the wrapper `std::vector<mu2e::StepPointMC>`.
- Long-term cleaner alternative: write a tiny custom
  `ProductionTargetEdepHist_module.cc` that books one `TH1D` via
  TFileService and increments per-event totals on EndJob → readable by
  uproot, no PyROOT dependency on grid. Deferred until current Path D
  proves stable.

## Cross-links
- Related: [dpa-scoring](/concepts/dpa-scoring.md), [art-instance-name-no-underscore](/incidents/art-instance-name-no-underscore.md),
  [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md), [stickman-sd-unwired](/incidents/stickman-sd-unwired.md)
- Source files: `pipeline.py:_render_pt_dumper_block` (legacy, retained
  for now but the analyzer block it emits returns empty trees and is
  not used by the working harvester)
- External: [StepPointMCDumper_module.cc](https://github.com/Mu2e/Offline/blob/main/Analyses/src/StepPointMCDumper_module.cc)

## 2026-06-08 — pt001 cluster 28344071 surfaced this end-to-end

Confirmed live on the grid output, not just at smoke time:
- `pt001/harvest/summary.json` from cluster 28344071 reported
  `files_seen: 0`, `edep_per_POT_MeV: 0.0` for **all 100 jobs**.
- Root cause inside `cmd_harvest_pot_only`
  (`pipeline.py:880-894`): the per-plate `t["totalEDep"].array(...)`
  uproot call raises `KeyInFileError not found: 'totalEDep'` (the
  `ptPlate<i>/nt` tree has the right num_entries but zero branches
  — see Key facts above). The broad `except Exception as e` at
  line 892 catches this and bumps `files_skipped`, so `files_seen`
  never increments and the loud `len(files_skipped)==len(files)`
  diagnostic is the only signal.
- Cross-impact: `readVD/ntvd` (mu_per_POT) reads fine via uproot —
  `mu_per_POT=0.002168` landed correctly for pt001 — so only the
  Path D edep half is broken. The mu-counting half is independent.

## 2026-06-08 fix — Path B (custom TH1D analyzer)

Shipped `ProductionTargetEdepHist` module in the patched
`autoresearch_muse_prodtarget` Offline fork. Books two TH1Ds via
TFileService — `edep_MeV` and `nielEdep_MeV` — with one bin per
sensitive ProductionTargetPlate<NN>. `analyze()` iterates the per-plate
StepPointMC collections and Fills the corresponding bin with
`totalEDep()` / `nonIonizingEDep()`. uproot harvest reads the
histograms with `.values()`; no PyROOT, no muse-env constraint.

### Gotcha — doubled TFileService folder

`tfs->mkdir("ptEdepHist")` nests *inside* art's auto-created
per-module folder (also named after the module label
`ptEdepHist`). The histograms therefore live at
**`ptEdepHist/ptEdepHist/edep_MeV`**, NOT
`ptEdepHist/edep_MeV`. uproot raises `KeyInFileError` on the
single-level path; the doubled-level path works. To avoid the
nesting entirely, drop the `tfs->mkdir(...)` and write to the
TFileService root (`tfs->make<TH1D>(...)`) — then the module's
auto-folder is the only level.

### Wired changes

- `Offline/Analyses/src/ProductionTargetEdepHist_module.cc`
  (new) + entry in `Offline/Analyses/CMakeLists.txt` after the
  `StepPointMCDumper` block.
- `pipeline_templates/pot_only/template.fcl` — replaced N
  per-plate `StepPointMCDumper` analyzer blocks with one
  `ptEdepHist` analyzer; single `__PT_PLATE_NAMES__` token
  feeds both `g4run.SDConfig.sensitiveVolumes` and
  `instanceNames`.
- `pipeline.py:_render_pt_plate_names_csv` (renamed from
  `_render_pt_dumper_block`); `_materialize_template`
  substitutes the one token.
- `pipeline.py:cmd_harvest_pot_only` — switched to reading
  TH1Ds at `ptEdepHist/ptEdepHist/edep_MeV` +
  `nielEdep_MeV`, accumulating per-plate arrays across
  files; writes `edep_per_plate_MeV` + `niel_per_plate_MeV`
  lists into `summary.json`. Old files (no histogram) degrade
  to `edep_per_POT_MeV=None` instead of skipping the file.
- Grid tarball
  `autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2`
  rebuilt via `muse tarball`; ships
  `libmu2e_Analyses_ProductionTargetEdepHist_module.so`.

Smoke: 3-event local mu2e at pt001 defaults → 33 nonzero plate
bins, 999.8 MeV total, 333 MeV/POT edep proxy. Preflight still
PASS (0 overlaps).

## Open questions / TODO
- Drop the doubled `tfs->mkdir("ptEdepHist")` and update the
  harvester path to single-level on the next workdir rebuild,
  so the trees live at `ptEdepHist/edep_MeV` like the FCL
  comment suggests.
