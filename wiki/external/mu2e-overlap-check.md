---
type: external
title: Mu2e G4 overlap-check recipe
description: G4 surface-check recipe for detecting silent volume overlaps; pre-built
  FCL + per-config wrapper pattern
status: active
timestamp: '2026-07-17'
updated_note: added the ROOT `overlapCheck.sh` method — complementary to the G4
  surface check
---

# Mu2e G4 overlap-check recipe

## Summary
Geant4's `CheckOverlaps` flag samples points on each volume's surface and
verifies none land inside another volume. Mu2e Offline wires this into a
standalone FCL (`Offline/Mu2eG4/fcl/surfaceCheck.fcl`) that does
nothing but build the geometry, run the check, and exit. This is the
canonical sanity check for any new placement (e.g. helical-plug knob ranges
that might collide with the TSdA disc or DS2Vacuum walls).

mu2ewiki page (auth-walled, but FCL is in cvmfs):
https://mu2ewiki.fnal.gov/wiki/Validation#Overlaps

## Key facts
- **Driver FCL:** `Offline/Mu2eG4/fcl/surfaceCheck.fcl` — `process_name:
  SurfaceCheck`, `EmptyEvent maxEvents:1`, producers `generate` + `g4run`
  (`physicsListName:"Minimal"`), `services.GeometryService.inputFile:
  Offline/Mu2eG4/geom/geom_SurfaceCheck.txt`, no B-field.
- **Geom override:** `Offline/Mu2eG4/geom/geom_SurfaceCheck.txt` is
  `geom_common_current.txt` plus three knobs:
  ```
  bool g4.doSurfaceCheck            = true;
  int  g4.nSurfaceCheckPointsPercmsq =   1;
  int  g4.minSurfaceCheckPoints      = 100;
  int  g4.maxSurfaceCheckPoints      = 10000000;
  ```
- **Sampling is stochastic** at `1 pt/cm²`. Thin ribbons (e.g. helical plug
  at dx=0.1 mm → 0.2 mm wide × 290 mm long → 58 mm² lateral face) may sample
  <100 points without the `minSurfaceCheckPoints=100` floor. Raise the
  per-cm² density to 10 if the volume is sub-mm and a clean run still feels
  suspicious.
- **Hit detection:** any overlap emits a line of the form
  `"Overlap is detected for volume <NAME> (G4Type) with its mother volume <MOTHER> (G4Type)"`
  to the G4 log. Capture the child volume name with
  `re.compile(r"Overlap is detected for volume\s+(\S+)")`.
- **Baseline must be measured per-geom AND per-Musing (CRITICAL).** A
  previous revision of this page claimed "vanilla geom_common_current.txt +
  Run1Bak emits 117 overlap lines" as a universal floor. **That is wrong as
  of 2026-05-19.** Direct measurements:
  - Run1Bak / Offline v13_12_10, `geom_SurfaceCheck.txt` (=
    `geom_common_current.txt` + flags): **0 overlap lines.**
  - Run1Bak / Offline v13_12_10, `geom_run1_b_ds_on_v40.txt` (wrapped with
    flags): **120 overlap lines** — 111× `FoilSupportStructure_NN:NN →
    StoppingTargetMother`, 2× `{North,South}RailDS3:0 → DS3Vacuum`, 1×
    `VirtualDetector_EMC_0_Front → StoppingTargetMother`, 1× `Degrader:0
    → protonabs3:0`, 5× `degraderSupport{Plate,Arm0..3}:0 → Degrader:0`.
  - Run1Bak / Offline v13_12_10, raw `geom_run1_a.txt`: **G4 aborts**
    (SIGABRT, `VirtualDetector_TT_MidInner entirely outside DS2Vacuum`);
    117 lines emitted pre-abort: 111 FoilSupportStructure + 1 EMC_Front VD
    + 5 `VirtualDetector_TT_{Back,FrontHollow,InSurf,MidInner,OutSurf}`.
    Run1A *cannot* be surface-checked under Run1Bak without the patches
    `bo_driver.py:436` applies.
  - **MDC2025an / Offline v13_11_00**, `geom_SurfaceCheck_run1a.txt`
    (ships pre-built, wraps `geom_run1_a.txt`): **0 overlap lines, full
    check completes.** The TT_MidInner→DS2Vacuum fix is baked into
    MDC2025an's Offline. **Run1A overlap testing belongs under MDC2025an,
    not Run1Bak.**
  The 117-line "stock baseline" was almost certainly the count for a
  different geom file (likely `geom_run1_a.txt` or v40, not stock common)
  measured at some earlier date. The categories that previous text called
  "cosmetic / off-axis / pre-existing" (foil supports, DS3 rails, EMC VD)
  are NOT inherited from stock common — they are introduced by the run1-derived
  geom overrides, and they are real overlap warnings, not cosmetic noise.
- **Implication for the BO whitelist.** `SURFACE_OVERLAP_MANAGED =
  ^(TSdA|AbsorberPV|AbsorberS)` in `bo_driver.py:679` still
  identifies the volumes BO can move. But the comment at
  `bo_driver.py:674` ("Stock Mu2e geometry has ~117 baseline
  overlap lines") is stale by the same argument: the floor is whatever the
  *baseline geom the preflight wraps* emits (currently `geom_run1_a.txt`,
  not stock common), and that floor must be measured, not quoted from this
  page. Re-run the check against the unmodified baseline geom and treat its
  output as the geom-specific floor before subtracting.
- **Per-config wrapper pattern:** to check a BO-proposed geom, write a
  per-config wrapper FCL that includes the canonical `surfaceCheck.fcl` and
  overrides `services.GeometryService.inputFile` to point at the proposal's
  `autoresearch_<cfg>_geom.txt`. Sequence in our preflight:
  ```
  #include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"
  services.GeometryService.inputFile : "autoresearch_<cfg>_geom.txt"
  ```
  Run with `MU2E_SEARCH_PATH` extended to the proposal's geom dir.
- **Runtime:** measured 2026-05-19 — ~250s CPU / ~250s wall for default
  density on full Run1Bak Mu2e geometry (~10k volumes). The earlier "~30s
  wall" estimate on this page was wrong. Still cheap enough to run per
  proposal, but plan preflight budgets accordingly.
- **Environment recipe (load-bearing).** From a fresh shell:
  ```bash
  source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
  muse setup ops                  # <-- load-bearing; without this,
                                  # MU2E_SEARCH_PATH misses DataFiles/
                                  # and DbService can't find
                                  # Database/connections.txt
  muse setup SimJob <Musing>      # e.g. Run1Bak or MDC2025an
  mu2e -c surfaceCheck.fcl
  ```
  Three traps:
  1. **`muse setup` is one-shot per shell.** Cannot be re-run to switch
     Musings; start a fresh shell.
  2. **Never pipe `muse setup` output.** `muse setup … | tail` runs muse
     in a subshell so its `export`s die there and the parent shell sees
     `MUSE_STUB=`, `MU2E_SEARCH_PATH=`. Redirect to a file if you must
     trim output: `muse setup … > /tmp/m.log 2>&1`.
  3. **Skipping `muse setup ops`** is what gave my early MDC2025an runs
     the `Can't find file "Database/connections.txt"` error. The
     prodtools `/mu2e-run` slash command bakes this step in;
     `.claude/commands/mu2e-run.md` in this repo mirrors it.

## Second method: ROOT `overlapCheck.sh` on a GDML (complementary, 2026-06-17)

Distinct from the G4 surface-sampling check above — this is **ROOT TGeo
`CheckOverlaps`** on a GDML file. Use it when you already have an as-built
GDML (e.g. preflight's `asbuilt_<config>.gdml`, see [preflight](/drivers/preflight.md)) and want a
fast geometric check without re-running G4.

- **Tool:** `Offline/bin/overlapCheck.sh [-q|-b|-r] <file.gdml>` — ships in
  Offline, **on PATH after plain `muse setup`** (the `setup codetools` UPS
  product is NOT needed; codetools is the legacy home but Offline carries its
  own copy). `-r` prints `Overlaps result: <nodes>/<UIDs>, <N> illegal`;
  exit code 1 if any illegal overlap (or ROOT error / unexpected line count).
- **Tolerance is picometer-tight:** `overlapCheck.C` calls
  `gGeoManager->CheckOverlaps(res)` with **`res = 1e-12 cm`** (default arg).
  That is ~7 orders of magnitude below the 50–100 nm (5e-6…1e-5 cm)
  precision-tolerance overlaps documented in
  [prodtarget-spacer-supportring-overlap](/incidents/prodtarget-spacer-supportring-overlap.md) — so a **0-illegal result here
  genuinely rules them out**, unlike the stochastic G4 surface sampling which
  can miss thin features. Touching (flush) surfaces are NOT counted as
  overlaps; only true interpenetration is.
- **Subset trick for a focused check:** running on a `/exp/mu2e/data/users/oksuzian/autoresearch_tools/gdml_subset_*`
  extract (e.g. the [production-target-stickman](/concepts/production-target-stickman.md) `ProductionTargetMother`
  subset, 54 nodes) checks all *target-internal* daughter↔daughter overlaps
  in seconds, with the real local coordinates preserved. It does NOT see
  mother↔external overlaps — for that, run on the full-world
  `asbuilt_<config>.gdml` (~13.7k volumes, minutes).
- **Result on file:** `pt6d07R01_07` (6D champion) target subset = **0 illegal
  / 54 nodes** at 1e-12 cm — consistent with its clean 90/100 grid run; the
  3 R1 spacer↔plate-00 failures were *other* picks.

## Cross-links
- Related: [bo-helical](/projects/bo-helical.md) (preflight integration), [tsda-disc-helical-sibling-overlap](/incidents/tsda-disc-helical-sibling-overlap.md) (the bug class this catches), [preflight](/drivers/preflight.md), [production-target-stickman](/concepts/production-target-stickman.md), [prodtarget-spacer-supportring-overlap](/incidents/prodtarget-spacer-supportring-overlap.md), [mu2e-offline-radiation-damage](/external/mu2e-offline-radiation-damage.md)
- Source files: `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_12_10/Offline/Mu2eG4/fcl/surfaceCheck.fcl`, `Offline/Mu2eG4/geom/geom_SurfaceCheck.txt`
- External: [G4 CheckOverlaps docs](https://geant4-userdoc.web.cern.ch/UsersGuides/ForApplicationDeveloper/html/Detector/Geometry/geomChecking.html)

## Open questions / TODO
- Empirical: confirm a known-overlapping geom (e.g. force helical halflen
  large enough to bury the plug inside the TSdA4 disc) triggers a managed-
  volume hit. Whitelist is plausible but not yet validated against a true
  positive.
- Decide whether to bump `nSurfaceCheckPointsPercmsq` to 10 for helical
  preflights — the plug ribbon's per-face area is small enough that 1 pt/cm²
  may underweight it.
