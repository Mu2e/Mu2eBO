# foilsflash mubeam GeomSolids crash — MUSE_TARBALL_BY_MODE mode-key omission

**Type:** incident
**Status:** resolved
**Updated:** 2026-06-27

## Summary
The first foilsflash live smoke (foilsflashSMOKE3, 2026-06-27) had **all 40 mubeam
jobs of every child crash in G4** with `GeomSolids0002 / G4Tubs::G4Tubs() Invalid
values for radii in solid: Foil_00, pRMin=1e+06, pRMax=249.5` (exit 134). Root
cause: `foilsflash` was **missing from `pipeline.py:MUSE_TARBALL_BY_MODE`**, so it
fell through to the `michael` default `Code_helical_base.tar.bz2` (UNPATCHED stock
`StoppingTargetMaker`). The stock maker reads the **poison-pill scalar
`stoppingTarget.holeRadius = 1.0e6`** (emitted alongside the per-foil `holeRadii`
vector) instead of the vector → G4Tubs pRMin=1e6 > pRMax → fatal. The poison pill
did its intended job ([[foilsg-grid-tarball-scalar-holeradius-fallback]]): crash
loudly instead of silently building uniform holes.

## Key facts
- **Fix:** add `"foilsflash": _HOLERADII_TARBALL` to `MUSE_TARBALL_BY_MODE`
  (pipeline.py:~98). foilsflash varies the foil holeRadii vector → needs the
  patched `Code_helical_holeradii.tar.bz2` (patched `libmu2e_GeometryService.so`),
  exactly like foils/foilsf/foilsg.
- **Why preflight didn't catch it ([[preflight-past-init-false-pass]]):** preflight
  runs LOCALLY under the patched `Offline_helical` musing (holeRadii honored) → it
  reported PASS; the GRID worker ships a SEPARATE tarball (the unpatched one) →
  crashed. Local-preflight-vs-grid-tarball env divergence (cf
  [[prodtarget-env-divergence]]). Also the per-foil **GDML as-built assertion**
  (autoresearch_bo_michael.py:~2289) that WOULD verify foil radii had `foilsflash`
  omitted from its mode tuple, so it never ran (and even if it had, it runs in the
  patched preflight env, so it'd pass — the bug is grid-only).
- **THREE preflight consumer tuples also lacked foilsflash** (fixed same commit):
  autoresearch_bo_michael.py ~2289 (GDML per-foil assertion), ~2342 (managed-overlap
  detection), ~2376 (PASS-message text). I had added foilsflash to the FCL-
  *generation* tuples (which preflight FCL path + GDML-dump) but not these
  *consumer* tuples — so the GDML was dumped but never verified.
- **Diagnosis trail:** mubeam_outputs.txt = 1 blank line → concat jobdef built with
  0 inputs → `mu2ejobfcl: job_primary_inputs(): invalid index 0` → `submit concat
  failed (rc=1)`. The TRUE failure is upstream: poll WARN "40 dirs present but
  0/36 settled — stuck in hash form — likely failed jobs"; the failed-job logs at
  `/pnfs/mu2e/scratch/users/$USER/workflow/default/outstage/<cluster>/00/<hash>/`
  show the G4 crash. (Outstage is `…/workflow/default/outstage/`, NOT
  `…/autoresearch_grid/<cfg>/` which is the staged-INPUTS path.)
- **General lesson (3rd occurrence):** adding a BO mode as a SUBCLASS inherits
  methods but NOT mode-key/tuple membership — every `*_BY_MODE` dict and every
  `mode.name in (...)` tuple across pipeline.py + autoresearch_bo_michael.py +
  graph/config.py must be audited. Same trap as
  [[preflight-mode-tuple-prodtarget6d-omission]]. Audit grep:
  `grep -nE '"foilsf"' pipeline.py graph/*.py autoresearch_bo_michael.py` and check
  each hit includes the new mode.

## Cross-links
- Related: [[bo-foilsflash]], [[foilsg-grid-tarball-scalar-holeradius-fallback]],
  [[preflight-past-init-false-pass]], [[preflight-mode-tuple-prodtarget6d-omission]],
  [[prodtarget-env-divergence]]
- Source files: `pipeline.py` (MUSE_TARBALL_BY_MODE),
  `autoresearch_bo_michael.py` (preflight consumer tuples ~2289/2342/2376)

## Open questions / TODO
- The local-preflight-vs-grid-tarball divergence means preflight CANNOT catch a
  wrong-tarball mode-key omission. A cheap guard: assert the resolved
  `MUSE_BASE_TARBALL` is the holeRadii one for any foils-family mode at submit.
