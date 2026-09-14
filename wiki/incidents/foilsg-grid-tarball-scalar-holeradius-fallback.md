---
type: incident
title: foilsg grid tarball runs unpatched StoppingTargetMaker — scalar holeRadius
  fallback
description: grid tarball lacks holeRadii-vector patch; foilsg jobs silently build
  uniform-hole stacks (scalar mean) or crash G4Tubs when mean > min rOut; ALL 62
  foilsg rows tainted; foilsg05 7/10 'rename race' diagnosis retracted
status: resolved
status_note: 'fix landed + grid-verified 2026-06-12. Landed: patched `StoppingTargetMaker.{cc,hh}`
  in `Offline_helical/` (holeRadii vector + length validation + "holeRadii vector
  active (n=N)" canary print), `libmu2e_GeometryService.so` rebuilt clean; preflight
  of the crashing foilsg06R00_00 geom under the patched env = PASS with canary (n=49),
  0 GeomSolids; classifier fixed ([preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)); `MUSING_BY_MODE`
  foils/foilsf/foilsg → `Offline_helical/setup_local.sh` (preflight parity); `pipeline.py`
  `MUSE_TARBALL_BY_MODE` dispatch added (foils* → `Code_helical_holeradii.tar.bz2`,
  michael/helical stay on Code_helical_base because Offline_helical''s Mu2eG4 lib
  of May 16 predates the May-26 twistedbox fix); POISON-PILL scalar `holeRadius=1.0e6`
  now emitted by FoilsMode + FoilsGroupMode geoms (unpatched env crashes loudly
  instead of silently building uniform holes); foilsg leaderboard quarantined to
  `.broken.tsv`. Tarball built + installed (`Code_helical_holeradii.tar.bz2`, 710
  MB, packed lib verified to carry the canary string). **VERIFIED END-TO-END 2026-06-12:
  grid replay `foilsgV01` (forced-x of foilsg06R00_07) ran the full patched chain
  — preflight PASS with canary, mubeam 198/200, concat via cvmfs `--setup`, mustops_ce
  191/200, harvest — and scored sob=2.57 vs the broken uniform-hole 3.16 for the
  IDENTICAL x-point (19% difference = the holes are physically real now; real holes
  remove stopping material, hence lower sob for this x).** foilsgV01 is row 1 of
  the clean leaderboard. foilsg07 cleared to launch.'
timestamp: '2026-06-12'
---

# foilsg grid tarball runs unpatched StoppingTargetMaker — scalar holeRadius fallback

## Summary

The grid code tarball used by foilsg children does NOT contain the patched
`StoppingTargetMaker.cc` with per-foil `holeRadii` vector support. On the
grid, every foilsg job silently falls back to the scalar
`stoppingTarget.holeRadius` (which `_geom_text` emits as the *mean* hole
radius over all 49 foils) and builds a **uniform-hole stack** instead of
the intended per-group holes. Two consequences:

1. **Hard crash** when the scalar mean exceeds any group's `rOut`:
   `G4Tubs: Invalid values for radii in solid: Foil_00, pRMin=51.04,
   pRMax=50` → signal 6 → all 200 jobs of the affected child die → outstage
   dirs stay in `NNNNN.<hash>` form forever → `list-outputs` 0 files →
   empty concat jobdef → `mu2ejobfcl --index 0` rc=255 → "stage concat
   failed". Hit foilsg06 R0 3/10 (R00_00/_03/_06) and **foilsg05 R0 7/10**
   (verified identical G4Tubs signature on foilsg05R00_00, pRMin=52.39 >
   pRMax=50).
2. **Silent wrong geometry** for every foilsg row that *succeeded*: the
   12 knobs collapse — `f_g{0..3}` enter the real geometry only through
   their weighted mean. The entire foilsg leaderboard (62 rows incl. the
   sob=3.16 "champion" foilsg06R00_07) measured uniform-hole stacks, NOT
   the per-group geometries the x-points describe.

## Key facts

- **Detection chain (foilsg06R00_00, cluster 28372942):** preflight=pass
  but grid `poll_mubeam` WARN "all 200 dirs present but only 0/180 settled
  (bare-form). 200 dir(s) stuck in hash form — likely failed jobs";
  job log shows `G4Exception GeomSolids0002, G4Tubs Foil_00 pRMin=51.041
  pRMax=50, signal 6, exit code 134`.
- **CORRECTION (2026-06-12 team review): there is NO patched
  StoppingTargetMaker anywhere — local or grid.** The "patched lib"
  comments in `FoilsMode._geom_text` were aspirational; searches of
  `autoresearch_muse/` (sparse mgit checkout = Mu2eG4 only, no
  GeometryService) and all `/exp/mu2e/{app,data}` Offline checkouts found
  zero `holeRadii` support. Preflight "passing" was NOT a vector-aware
  local env — preflight crashed with the identical GeomSolids0002 abort
  and was misclassified PASS by the `past_init` classifier bug
  ([preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)).
- **Scope is bigger than foilsg: foils (v2) and foilsf (v3) are affected
  too.** `FoilsMode._geom_text` (shared by foilsf via `_frac_to_abs`)
  emits scalar `holeRadius = 21.5` + the holeRadii vector. With no patch,
  every foils/foilsf job built ALL foils (base + extras) with hole=21.5 —
  the `f_up`/`f_dn` (rIn) knobs were **physically inert** across all 297
  v3 rows. Never crashed because 21.5 < every rOut. The v3 rows are
  self-consistent measurements of the hole-21.5 family (the GP simply
  learned ~zero signal on the f dims); the sob=3.89 plateau is real for
  that family, but champion descriptions like "ring rIn=29.1" are wrong —
  actual built holes were 21.5. (foil v1 mode was fine: it emitted
  `holeRadius = extra_rIn` as the scalar.)
- **`_geom_text` emits BOTH** `stoppingTarget.holeRadius` (scalar = mean,
  for back-compat) and `stoppingTarget.holeRadii` (vector). The back-compat
  scalar is what makes the fallback *silent* when the mean is geometrically
  valid — without it the unpatched maker would fail on every config.
  [bo-foilsg](/projects/bo-foilsg.md) documented this hazard at wiring time ("verify the grid
  tarball is current before launching") but no verification was ever run.
- **Crash-vs-silent predictor:** child crashes iff
  `mean(holeRadii) > min_g(rOut_g)`. foilsg06 R0: 3/10 crashed, 7/10
  silently wrong. foilsg05 R0: 7/10 crashed, 3/10 silently wrong rows
  (R00_05/06/08).
- **Misdiagnosis corrected:** the foilsg05 7/10 failures were previously
  attributed to [stage-out-rename-race](/incidents/stage-out-rename-race.md) under grid contention (the
  rename-quiesce WARN text matches superficially). Wrong: dirs stay
  hash-form because the JOBS FAILED, not because the rename pass lagged.
  The rename-race page carries a retraction note for that recurrence
  section. Diagnostic discriminator for the future: rename-lag shows
  `settled` climbing over poll ticks and bare-form dirs appearing;
  job-failure shows `settled: 0/N` flat with ALL dirs hash-form — check a
  job .log inside a hash dir before blaming stage-out.
- **Leaderboard taint:** all 62 foilsg rows (foilsg01:4, foilsg02:40,
  foilsg03:8, foilsg05:3, foilsg06:7) measured uniform-hole geometry.
  They are internally consistent as samples of the *uniform-hole* family
  (hole = weighted mean of f_g·rOut_g), so the GP wasn't fed noise — but
  per-group hole structure was never actually explored, and any geometry
  sketch/interpretation of champions as per-group-hole stacks is wrong.
- **Campaign response 2026-06-12:** foilsg06 parent killed (SIGTERM)
  after R0 +7 rows, before R1 launched onto the broken tarball; no R1
  children exist; grid queue empty.

## Follow-on gotcha: MUSING leaks to the grid via `--setup` (2026-06-12)

The preflight-parity fix (MUSING_BY_MODE → local `setup_local.sh`) broke
the **concat** stage: stages without `ships_geom` are submitted with
`--setup MUSING` (`pipeline.py` submit_stage), and mu2ejobsub.sh sources
that path ON THE WORKER — `/exp/...` doesn't exist there. foilsgV01's
concat died at `mu2ejobquery --setup` / `mu2ejobsub.sh: line 156: ...
setup_local.sh: No such file or directory`; surface signature was again
"dir stuck in hash form → 0 outputs → empty mustops_ce basenames →
mu2ejobdef rc=25". **Fix:** `pipeline.py:_grid_setup_sh()` — when MUSING
is local, resolve the workdir's `backing` symlink to the cvmfs Musing and
hand the worker `<backing>/setup.sh` (concat runs no geometry code, so
the stock backing is always sufficient). Rule of thumb: **MUSING is a
LOCAL-shell concept (preflight, sourced_env); anything embedded in a
jobdef must be cvmfs-visible.**

Recovery gotcha: re-running `pipeline.py submit <stage>` after a FAILED
cluster silently skips ("already submitted (cluster=...); skip submit
(use --force to override)") because the stale `<stage>_cluster.txt`
satisfies the idempotency guard — then poll/list run against the dead
cluster and reproduce the original failure. Stalled-chain recovery after
a submit-side fix MUST pass `--force` on the failed stage (pipeline-level
cousin of [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)).

## Cross-links
- Related: [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md) (same tarball mode-key class), [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md) (same preflight-vs-grid env split),
  [stage-out-rename-race](/incidents/stage-out-rename-race.md) (the misdiagnosis), [bo-foilsg](/projects/bo-foilsg.md) (tainted
  leaderboard + original hazard warning),
  [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md) (foilsg05's 3
  survivors were orphaned by that bug *and* silently wrong from this one),
  [muse-backing-pattern](/external/muse-backing-pattern.md) (how the patched lib is built), [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md), [preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)
- Source files: `bo_driver.py` `FoilsGroupMode._geom_text`
  (dual scalar+vector emission), `pipeline.py:506 submit_stage` (where the
  empty-jobdef rc=255 surfaces)
- Job-log evidence: `/pnfs/mu2e/scratch/users/oksuzian/workflow/default/
  outstage/28372942/00/00000.9b6062b8/*.log` (foilsg06R00_00),
  `.../28093112/00/00000.bb9ccc23/*.log` (foilsg05R00_00)

## Open questions / TODO
- Rebuild the grid code tarball from a patched workdir (recipe in
  [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md)) and verify with a single-job smoke that a
  per-group-hole config builds Foil_00 with its OWN hole radius.
  **Patch site (verified 2026-06-12):**
  `/exp/mu2e/app/users/oksuzian/Offline_helical/` is a FULL Offline
  checkout already building `libmu2e_GeometryService.so` under
  `al9-prof-e29-p094` (the Run1Bak qualifier) — patch
  `Offline/GeometryService/src/StoppingTargetMaker.cc` there, no
  `mgit add` needed. (The `autoresearch_muse/` sparse workdir the current
  tarball was built from contains ONLY Mu2eG4 — it cannot host this
  patch. None of the 5 other StoppingTargetMaker.cc copies on
  /exp/mu2e/{app,data} has holeRadii; Offline_helical's built lib has 0
  holeRadii strings — confirmed unpatched.) Open implementation question:
  whether to rebuild the tarball wholly from Offline_helical (does it
  already carry the helical Mu2eG4 patch?) or layer the GeometryService
  lib into the existing Code_helical_base recipe.
- Decide what to do with the 62 tainted rows: keep as a uniform-hole
  dataset (they're valid samples of that family) vs archive the TSV and
  restart foilsg clean. Either way the sob=3.16 champion claim must not be
  quoted as a per-group-hole result.
- Was the foilsg01/02-era tarball ever patched? (If yes, find what
  rebuilt/reverted it; if no, the hazard warning in [bo-foilsg](/projects/bo-foilsg.md) was
  never acted on.)
