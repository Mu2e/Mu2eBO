---
type: incident
title: template.fcl staleness after rsync+sed fork
description: '`rsync+sed` fork misses `template.fcl`; G4 init fails on stale geom
  basename'
status: resolved
timestamp: '2026-05-15'
---

# template.fcl staleness after rsync+sed fork

## Summary
The per-config fork pattern (`rsync smoke_<oldcfg>/ smoke_<newcfg>/` + `sed s/<oldcfg>/<newcfg>/g pipeline.py`)
silently leaves stale geom-file basenames in the per-stage `template.fcl` files.
mu2ejobdef bakes the wrong filename into the cnf tarball, the grid jobs ship
the *correct* `Code/autoresearch_<newcfg>_geom.txt` but G4 tries to load
`autoresearch_<oldcfg>_geom.txt` and fails at init. All jobs die with no `.art`
output, only a `.log`. 400 helical001 grid jobs were lost this way before
detection.

**Resolved 2026-05-15** by refactoring [pipeline](/drivers/pipeline.md) to be parametric: one
canonical pipeline.py + one shared template tree with a `__GEOM_FILE__`
sentinel. No more rsync+sed; the failure mode no longer reachable.

## Key facts
- **Failure signature:** in each job's `.log`, `cet::exception caught: GeometryService:
  Can't find file "autoresearch_<oldcfg>_geom.txt"`. Output staging dir contains only
  the `.log`, no `.art`.
- **Root files at fault** (per stage, all in the smoke_helical001 tree before the fix):
  - `mubeam/template.fcl:30` — `services.GeometryService.inputFile`
  - `run1b_mubeam/template.fcl:37` — same key
  - `mustops_ce/template.fcl:12` — same key
  - `concat/template.fcl` — no geom dependency, immune
- **Why sed missed them:** the original fork command only ran sed on `pipeline.py`;
  the substitution scope did not include the per-stage `template.fcl` files even
  though they hard-code the geom basename.
- **Why mu2ejobdef doesn't catch it:** `--inloc` only verifies the *Code tarball*
  exists; the FHiCL contents are opaque to the cnf builder. The mismatch only
  surfaces inside G4 init on the grid.
- **Pre-flight does not catch it:** `preflight` runs against the proposal geom
  directly, not against the `template.fcl`. Preflight passing tells you the geom
  is valid; it tells you nothing about whether the grid job will load it.
- **Fix landed:** see [pipeline](/drivers/pipeline.md). The shared `pipeline_templates/<stage>/template.fcl`
  files use `__GEOM_FILE__` as the substitution sentinel; `submit_stage`
  materializes them per-config before mu2ejobdef sees them. No `template.fcl`
  on disk contains a per-config basename anymore.

## Cross-links
- Driver: [pipeline](/drivers/pipeline.md)
- Related: [grid-job-completion-check](/incidents/grid-job-completion-check.md) (the `.log`-without-`.art` signature
  is exactly what an init failure looks like), [fcl-unicode-parse-error](/incidents/fcl-unicode-parse-error.md)
- Source: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/smoke_helical001/`
  (the failing tree, as of 2026-05-15)

## Open questions / TODO
- (resolved) Lint for hardcoded `autoresearch_*_geom.txt` literals in
  `pipeline_templates/` would fail-fast if the sentinel is ever removed; not
  yet written, but the failure window is now much narrower.
