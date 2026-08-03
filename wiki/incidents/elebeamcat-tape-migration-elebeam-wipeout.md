---
type: incident
title: EleBeamCat persistent→tape migration wipes out a whole elebeam round
description: 'EleBeamCat Run1Baa moved persistent→tape mid-campaign (2026-07-09):
  all foilsflash10 elebeam jobs FileOpenError → blank outputs.txt → fail-soft flash=None
  → 0 rows despite valid sob; basename filelists mean fresh `submit --force` auto-resolves
  via SAM; MuBeamCat still on persistent (WATCH — **FIRED 2026-07-13**, fixed 6906cb8)'
status: resolved
status_note: '(MuBeamCat recurrence fixed 6906cb8 + verified: foilsflash16 mubeam
  cluster 70879403 submitted clean on tape URLs 2026-07-13)'
timestamp: '2026-07-17'
updated_note: recovery-recipe lock path updated after pending/ merged into leaderboards/
---

# EleBeamCat persistent→tape migration wipes out a whole elebeam round

## Summary
foilsflash10 (widened-box probe, q=8) produced ZERO leaderboard rows: every
child's elebeam_flash cluster (200 jobs each) died ~30 s in with art
`FileOpenError` opening the EleBeamCat auxinput via xrootd. Root cause:
the `sim.mu2e.EleBeamCat.Run1Baa` dataset (2 files, ~5 GB each) was
**migrated from /pnfs/mu2e/persistent to /pnfs/mu2e/tape at 10:05 the same
day** (file mtimes) — hours before the round's elebeam submits. The sob
chain (mubeam→concat→mustops_ce) was untouched and every child's sob
landed in `harvest/summary.json` (best 3.78), but harvest's fail-soft
flash extraction returned None → `evaluate` zero-rowed all 8 as
`obj_unparseable`. The eval money is recoverable: only the elebeam stage
needs resubmission.

## Key facts
- **WATCH FIRED 2026-07-13: MuBeamCat Run1Baa migrated persistent→tape too**
  (file gone from `/pnfs/mu2e/persistent/datasets/phy-sim/sim/mu2e/MuBeamCat/
  Run1Baa/...`, present at the `/pnfs/mu2e/tape/...` counterpart). Killed
  foilsflash15 (first rolling A/B): 5/5 children + replacements died at
  `submit mubeam failed (rc=1)` — the post-incident INPUT PROBE (pipeline.py
  ~:615-660) hard-failed BEFORE submission with the exact remediation
  message, so ZERO grid jobs were wasted (vs ff10's 1,600 dead jobs — the
  probe paid for itself on first firing). Fix = `STAGES["mubeam"]
  ["default_loc"]` AND `STAGES["run1b_mubeam"]["default_loc"]` (both read
  MuBeamCat) `"disk"` → `"tape"` (pipeline.py:157,167); elebeam_flash already
  tape since 07-10. Bonus live validation: the rolling no_row_streak guard
  counted 4/5 toward abort exactly as designed while replenish waves kept
  launching into the dead submit.
- **Failure signature:** job log tail shows `FileOpenError ... Unable to open
  specified secondary event stream file xroot://fndcadoor.fnal.gov//pnfs/
  fnal.gov/usr/mu2e/persistent/.../EleBeamCat/Run1Baa/...art` inside
  `ResamplingMixer/beamResampler`; job dies in ~30 s; ALL outstage job dirs
  stay in hash form (`00000.9f8bd703`) = nonzero exit.
- **Failure chain to zero rows:** all-jobs-crash → poll failure-aware exit
  ("queue drained, 200 dirs present, 0 settled") → list-outputs writes a
  **single blank line** to `elebeam_flash_outputs.txt` → harvest fail-soft
  flash=None → summary.json has valid sob but None flash → node_evaluate
  `obj_unparseable` → closed_loop "0 new rows + all resolved → all failed;
  exiting early". Every layer behaved as designed; no code bug.
- **Diagnosis kit:** `samweb -e mu2e locate-file <basename>` (needs
  `setup sam_web_client`) shows `enstore:/pnfs/mu2e/tape/...(nearline)`;
  live dCache state via the dot-command
  `cat "/pnfs/.../.(get)(<basename>)(locality)"` → `ONLINE_AND_NEARLINE`
  means staged (readable now), bare `NEARLINE` means tape-only (prestage
  first, e.g. background `dd` of the first MBs triggers recall).
- **CORRECTED 2026-07-10 — resubmit alone does NOT fix it.** The v1 recovery
  (fresh jobdefs) baked the SAME persistent URL: basename→URL resolution
  does NOT go through SAM. It is `mu2efilename` convention driven by OUR
  submit flag — `pipeline.py` passes `--default-location <STAGES[s]
  ["default_loc"]>` and **`disk` literally means /pnfs/mu2e/persistent**
  (Mu2eInSpecs.pm:181; valid values `disk|tape|scratch` from
  Mu2eFNBase::mu2eDSL, env `MU2E_DSROOT_*`). Real fix: set the stage's
  `default_loc: "tape"` (done for elebeam_flash, pipeline.py) — or
  surgically per-dataset via `--location <dataset>:<location>`
  (Mu2eInSpecs supports it; mu2ejobsub passes it through).
- **Pre-flood verification recipe (used before v2's 1400 jobs):**
  `mu2ejobfcl --jobdef <cnf.tar> --index 0 --default-protocol root
  --default-location tape | grep -o "xroot[^\"]*"` prints the URL workers
  will open — confirm it matches where the files actually live BEFORE
  letting a 200-job cluster loose. (setup mu2ejobtools first.)
- **SECOND BUG — flash=0 leaderboard poison:** the driver's `evaluate` verb
  (called directly, outside the graph) accepts a summary with
  `flash_edep_per_pot: null` and appends the row with **flash=0.0** — a
  fake zero-flash point at sob 3.78 that would dominate the whole Pareto
  front at the next GP fit (graph path is guarded in node_evaluate; the
  direct-CLI path is not — TODO add the guard in FoilsFlashMode, post-
  campaign). Cleanup recipe: quarantine rows to a sidecar TSV + restore the
  consumed pending entries (name/[x]/alpha/ts format) under
  `flock leaderboards/locks/pending_bo_foilsflash.tsv.lock` (pending TSVs
  merged into `leaderboards/` 2026-07-17); evaluate consumes pending at
  append so re-evaluate NEEDS them restored. Recovery v2 guards with a
  flash-null check before calling evaluate.
- **Post-hoc row append (children dead):** after
  `poll` + `list-outputs --force` + `harvest`, run the driver verb directly:
  `.venv-graph/bin/python bo_driver.py --mode foilsflash
  --alpha 1e5 evaluate <cfg> <ROOT>/harvest/summary.json` — this is exactly
  what `graph/pipeline_io.py:run_evaluate` shells out to; it owns the
  leaderboard append + pending cleanup (schema stays in one place).
- **Env needed for recovery driver:** `AUTORESEARCH_MODE=foilsflash`
  (tarball dispatch), `AUTORESEARCH_NO_RUN1B=1`,
  `AUTORESEARCH_ELEBEAM_NJOBS=200` (env seam, default 100 — ff08/09/10 ran
  200; poll target must see the same value as submit).
- **R00_01 doubly dead:** it had already died at mustops_ce submit (rc=25
  blank-line face, see [stage-out-lag](/incidents/stage-out-lag.md)) — no ce outputs, not recoverable
  by elebeam resubmit alone. 7/8 recovered.
- **WATCH ITEM:** `MuBeamCat.Run1Baa` (mubeam + run1b_mubeam auxinput) is
  still on **persistent** disk (samweb 2026-07-09). The same migration will
  eventually hit it and kill every mubeam stage the same way. Same recovery
  applies (basename filelists + fresh submit); check its locality when an
  unexplained all-jobs-fast-crash appears in mubeam.
- **scan_logs blind spot:** the 200 FileOpenError logs sailed through
  scan_logs (patterns are geometry-only, see
  [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md)); the round was classified by the
  barrier as "all failed" only via zero rows.

## Cross-links
- Related: [stage-out-lag](/incidents/stage-out-lag.md) (blank outputs.txt face), [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md),
  [mmackenz-edepana-lib-qualifier-bump](/incidents/mmackenz-edepana-lib-qualifier-bump.md) (same class: external dependency
  rots under us), [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md) (different xrootd
  FileOpen face: transient under IO load, not missing file)
- Project: [bo-foilsflash](/projects/bo-foilsflash.md)
- Source: `pipeline.py:poll_cluster` (failure-aware exit), `graph/nodes.py:node_evaluate`,
  `graph/config.py` (`AUTORESEARCH_ELEBEAM_NJOBS` seam)

## Open questions / TODO
- Consider a submit-time auxinput liveness probe (samweb locate + locality
  on first filelist entry) — would have turned 1,600 dead jobs into one
  clear preflight error.
- Add `FileOpenError` to scan_logs patterns?
