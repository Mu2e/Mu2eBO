---
type: driver
title: preflight — local G4 init feasibility check
description: local `mu2e -n 1` G4 init feasibility check
status: active
timestamp: '2026-06-13'
updated_note: fatal-abort gate + holeRadii canary + as-built GDML geometry assertion
  added after the foilsg uniform-hole incident; documented foils-only GDML emission
  scope
---

# preflight — local G4 init feasibility check

> **2026-06-13 — preflight is now a 4-layer gate (foils family):**
> 1. **Fatal-abort check** (`G4_FATAL_RX`): GeomSolids00xx / `*** Fatal
>    Exception ***` / "Aborting execution" FAIL unconditionally — before
>    `past_init` can mask them ([preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)).
> 2. **holeRadii canary**: geom requests `stoppingTarget.holeRadii` but
>    output lacks "holeRadii vector active" → FAIL (unpatched env,
>    [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md)).
> 3. **As-built GDML assertion** (foils/foilsf/foilsg): surfacecheck FCL
>    also sets `physics.producers.g4run.debug.writeGDML` →
>    `preflight_geom.gdml` in the workdir;
>    `verify_stopping_target_gdml()` parses the `Foil_NN` tubes with
>    plain XML (NOT ROOT TGDMLParse — [root-gdml-forward-volume-ref](/incidents/root-gdml-forward-volume-ref.md))
>    and compares per-foil rIn/rOut/fullThickness against the geom file
>    (tol 1e-3 mm, GDML z = FULL length, lunit-aware, repeat-last
>    halfThickness semantics). Any mismatch or missing GDML → FAIL.
>    **Name-parsing gotcha**: G4's GDML writer appends a pointer suffix
>    to EVERY name (`Foil_020x55d1...`); a greedy `Foil_(\d+)` regex
>    swallows the leading 0 of `0x` and scrambles indices (foil 02 →
>    "20") — bit the first live run 2026-06-13. Use non-greedy digits +
>    anchored optional `0x[0-9a-f]+$` suffix, and report missing foil
>    indices instead of skipping them.
>    On PASS the verified GDML is preserved at
>    `autoresearch_grid/<config>/geom/asbuilt_<config>.gdml` (the /tmp
>    workdir is node-local and tmpwatch-cleaned).
>    **`<tube>` name-attribute ordering**: G4's GDML writer does NOT put
>    `name=` first (`<tube aunit="deg" deltaphi=... name="Foil_NN0x..">`),
>    so a `grep '<tube name="Foil_'` returns 0 and looks like the foils
>    vanished — but ElementTree's `el.get("name")` reads attributes
>    order-independently, so the verifier is correct. Don't "sanity check"
>    the foil count with a grep anchored on attribute order.
>    **Viewer foil-count gotcha**: a GDML viewer may show FEWER foils than
>    the 49 placements actually present (e.g. 42) — the base foils are
>    0.106 mm thick vs 2 mm extras (19×), so vis-level depth caps (ROOT
>    `SetVisLevel`) or sub-pixel culling drop thin base foils at full-stack
>    zoom. Authoritative count: `volumeref` / distinct-Z / solidref all = 49
>    in the GDML; viewer rendering is not the source of truth. To view
>    the foils alone, `tools/gdml_subset_stopping_target.py <asbuilt.gdml>`
>    extracts StoppingTargetMother + its 49 foils into a ~25 KB standalone
>    GDML whose world volume IS the foil mother (leaves emitted before the
>    mother so ROOT TGDMLParse doesn't segfault on forward refs — see
>    [root-gdml-forward-volume-ref](/incidents/root-gdml-forward-volume-ref.md)).
>    This is the value-level guarantee the canary can't give: the
>    geometry G4 built IS the geometry x describes.
> 4. Managed-volume surface-check overlap scan (pre-existing).
> Tests: `tests/test_audit_fixes.py` `TestPreflightFatalAbortClassification`
> + `TestVerifyStoppingTargetGdml` (10 cases).
>
> **Mode dispatch (autoresearch_bo_michael.py:1982-1993):** modes in
> `("helical","foils","foilsf","foilsg","prodtarget","prodtarget6d")`
> use `surfacecheck.fcl` (overlap scan). GDML emission tier:
> - **foils / foilsf / foilsg** — emit `preflight_geom.gdml` AND run the
>   per-foil layer-3 verifier (rIn/rOut/thickness against geom).
> - **prodtarget / prodtarget6d** (added 2026-06-13) — emit
>   `preflight_geom.gdml` AND preserve to
>   `autoresearch_grid/<config>/geom/asbuilt_<config>.gdml`, but NO
>   per-plate verifier yet. **Why a foils-style verifier can't be
>   copy-pasted:** PT plate solids are named by a *parameter-hash cache
>   key* — `StickmanPlate_{rOut}_{thick}_{lug}_{flagC}_{flagL}_{filletR}_Core`
>   (`constructTargetPS.cc:1369-1411`) — NOT by plate index. So tube
>   names give you the unordered set of (rOut, thick) pairs but not the
>   index→z mapping. Set-comparison (Tier A) catches wrong-N /
>   wrong-rOut / wrong-thickness; per-index assertion (Tier B) requires
>   walking `<physvol>` refs inside `ProductionTargetMother` and sorting
>   by `<position z>`. Foils don't have this problem because each foil
>   gets a unique `Foil_NN` G4Tubs (no caching, no dedup).
> - **helical** — surface-check only, no GDML emission.

## Summary
Runs a single `mu2e -n 1` locally (Musing setup) on a BO proposal's geom file
to verify that Geant4 geometry construction succeeds before paying for grid
submission. Catches overlapping-volume errors, bad placements, and
missing-include-chain issues. Subcommand of [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md).

## Key facts
- **Path:** `autoresearch_bo_michael.py cmd_preflight`
- **FCL selection (single G4 init, landed 2026-05-19):**
  - helical mode → `surfacecheck.fcl` (init + surface-check overlap scan).
  - non-helical modes → `preflight.fcl` (init only — no overlap diagnostics needed).
  - Replaces the prior two-pass design (preflight.fcl, then surfacecheck.fcl)
    which paid G4 geometry construction ~3 min twice per iteration. Single-pass
    wall is ~4m20s (slightly more than plain init because surface-check
    samples ~1k points per volume) but ~33% faster overall than the two-pass
    chain. For q=5 batches this saves ~15 min/iteration.
- **Templates:** inline `PREFLIGHT_FCL_TEMPLATE` + `SURFACE_CHECK_FCL` +
  `SURFACE_CHECK_GEOM_OVERLAY` constants. **No `#` comments** (fhicl
  interprets `#` as include); also no `//` comments — bare statements only.
- **Geom-fail regex:** `G4Exception.*?(GeomMgt000\d|GeomVol1002|placement|outside mother|overlap)`.
  **Only consulted when `past_init=False`** — surface-check emits ~117
  `GeomVol1002` WWWW advisory warnings on every baseline overlap, which
  would falsely trip this regex during the single-pass design. If the run
  reached the event loop, geometry constructed successfully; surface-check
  WWWW lines are diagnostic, not failures.
- **Surface-check parse:** `SURFACE_OVERLAP_RX` collects every "Overlap is
  detected for volume X" line; `SURFACE_OVERLAP_MANAGED` filters to volumes
  our BO knobs touch (TSdA region). Baseline overlaps (~117 stock-geometry
  hits like FoilSupportStructure, DS3 rails) are reported as info and
  ignored.
- **Pass condition:** `rc==0` OR `past_init` (BeginRun / event-loop tokens
  in stdout) OR timed-out, AND (helical only) no managed-volume overlap.
  `rc != 0` is *expected* because g4run.produce() needs a primary particle
  source we don't supply — beginRun (geom build) ran first, which is what
  we test.
- **Timeout:** 600 s (G4 init failures usually surface in <60 s)
- **Logs:** `bo_michael_preflight/<cfg>.log` (non-helical),
  `bo_helical_preflight/<cfg>.log` (helical). Single log per run since 2026-05-19;
  the prior two-pass design wrote `<cfg>.log` + `<cfg>_surfacecheck.log`.
- **Setup:** sources `setupmu2e-art.sh` then `Musings/SimJob/Run1Bak/setup.sh`
- **MAJOR CAVEAT — patched lib NOT loaded (2026-05-20).** `cmd_preflight`
  sources only the stock CVMFS `Run1Bak/setup.sh`; it does NOT source
  `autoresearch_muse/`'s muse setup or the shipped `Code/setup.sh`. So the
  helical plug (`TSdAHelicalTube`) is constructed using the **stock** Offline
  code, not the patched library that grid jobs use. Helical-plug-specific
  bugs (e.g. the negative-volume defect — see
  [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md)) are therefore invisible to
  preflight. To fix: source the local muse setup before running `mu2e -n 1`,
  or extract `Code_helical_base.tar.bz2` and source its `setup.sh`. Until
  then, helical-plug failures only surface in grid worker logs (and the
  end-of-workflow scan_logs node).

## Cross-links
- Used by: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md), [graph-runner](/drivers/graph-runner.md) (per-iteration preflight node)
- Surfaced bug: [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md)
