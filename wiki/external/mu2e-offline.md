# Mu2e Offline / Musings on CVMFS

**Type:** external
**Status:** active
**Updated:** 2026-05-15

## Summary
The released Mu2e Offline + production FCL config tree, mounted via CVMFS.
All grid jobs and [[preflight]] runs source these.

## Key facts
- **Setup script:** `/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh`
- **Musing setup:** `/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh`
- **Offline baseline:** `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_06_10/`
  (used by mmackenz scraper as include-resolution fallback)
- **Geom files of interest:**
  - `Offline/Mu2eG4/geom/geom_run1_a.txt` — Run1A baseline (lacks TT_MidInner fix
    for DSOff field; see [[geom-run1a-vs-run1b]])
  - `Offline/Mu2eG4/geom/geom_run1_b_v06.txt` — Run1B v06 baseline (has the fix)
  - `Offline/Mu2eG4/geom/bfgeom_DSOff.txt` — DS-off field map used by run1b_mubeam
- **FCL prologs:**
  - `Offline/fcl/standardServices.fcl`
  - `Production/JobConfig/common/prolog.fcl`

## Cross-links
- Related: [[mu2e-offline-radiation-damage]], [[pyutils-analysis-env]]
- Bug it caused: [[geom-run1a-vs-run1b]]
- Driver that exercises it: [[preflight]]
