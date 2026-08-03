---
type: incident
title: concat-stage xrootd FileOpenError in PostEndJob
description: concat-stage art exits 1 in PostEndJob with xrootd FileOpenError under
  high concurrent IO; outstage has .log but no .art
status: active
status_note: (transient — recurs whenever many concat jobs read inputs simultaneously;
  no code fix, just retry)
timestamp: '2026-05-18'
---

# concat-stage xrootd FileOpenError in PostEndJob

## Summary
Under heavy concurrent IO (several `q=5` chains all running their `concat`
stage at once), individual concat-stage art jobs finish their event loop
cleanly (`TrigReport` shows the expected ~12.5k events passing) but then die
in `PostEndJob` with a chain of `xrootd [ERROR] Operation expired` followed
by `FileOpenError ... was not found or could not be opened`. The job exits 1.
The outstage NNNNN.<hash>/ directory contains the `.log` but no `.art` file,
which causes `list-outputs concat` to silently produce a short/empty
`concat_outputs.txt`, which in turn causes `submit mustops_ce` to fail
parsing or to submit with zero inputs (manifesting as `FAIL submit-mustops_ce`
in the chain script — same surface as token contention, different root cause).

## Key facts
- **Failure signature in worker `.log`:**
  ```
  [ERROR] Operation expired
  art exception ... FileOpenError
    xroot://fndcadoor.fnal.gov:1094//.../sim.oksuzian.TargetStops.Run1Bak_<cfg>.NNN_NNN.art
    was not found or could not be opened
  PostEndJob: exit status 1
  ```
  `TrigReport` immediately above shows the event loop completed successfully
  (e.g. `Events total = 12561  passed = 12561`).
- **Outstage symptom:** the job's NNNNN.<hash>/ subdir under
  `/pnfs/mu2e/scratch/users/$USER/workflow/<DSCONF>.concat.../outstage/<cluster>/`
  contains only a `.log` (and maybe stub fcl/cnf), no `.art` product.
- **Affected jobs in dx-widening probe (helical043-047, 2026-05-18):**
  4 of 5 configs lost their concat output (043, 045, 046 fully; 044
  survived). Recovery via re-submit of just the concat stage worked first
  try for all three — confirming the failure is a transient dCache hiccup,
  not a config issue.
- **Why it presents as `FAIL submit-mustops_ce`:** the chain script's
  per-step success check is `mu2ejobsub` exit code, but the *input* to the
  mustops_ce submit is `state/mustops_ce_basenames.txt`, which is empty when
  the upstream concat outputs are missing. Three distinct things now share
  the `FAIL submit-mustops_ce` surface:
  1. token race ([concurrent-token-contention](/incidents/concurrent-token-contention.md))
  2. stage-out rename race ([stage-out-rename-race](/incidents/stage-out-rename-race.md))
  3. empty inputs file because concat outputs never landed (this incident)
- **Diagnostic ladder when `FAIL submit-mustops_ce` hits:**
  1. Check `state/mustops_ce_basenames.txt` size — empty → this incident or
     stage-out rename race
  2. Check `state/concat_outputs.txt` size — empty → upstream concat lost art
  3. `ls /pnfs/.../<concat-cluster>/00/*/sim.*.MuminusStopsCat.*.art` —
     missing → walk into a job subdir, grep its .log for `FileOpenError`
- **Recovery:** re-run `submit concat`. Use
  `/tmp/helical_resume_concat_full.sh <cfg>` which chains
  `submit concat → poll → sleep 60 → list-outputs → submit mustops_ce → ...`
  through to `evaluate`.
- **Probable trigger:** dCache/xrootd doors throttle or expire reads when
  many concurrent concat jobs (each reading several input art files for the
  merge) hit the same pool simultaneously. The PostEndJob phase re-opens
  files for output finalization and is where the timeout shows up.

## Cross-links
- Related: [concurrent-token-contention](/incidents/concurrent-token-contention.md) (shares failure surface),
  [stage-out-rename-race](/incidents/stage-out-rename-race.md) (also shares surface), [bo-helical](/projects/bo-helical.md)
  (dx-widening probe), [grid-job-completion-check](/incidents/grid-job-completion-check.md), [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md), [elebeamcat-tape-migration-elebeam-wipeout](/incidents/elebeamcat-tape-migration-elebeam-wipeout.md), [harvest-pyroot-nfs-rpc-hang](/incidents/harvest-pyroot-nfs-rpc-hang.md)
- Source: `pipeline.py:submit_stage` (submits), `pipeline.py:list_outputs`
  (silently emits empty file when no .art present)
- Recovery script: `/tmp/helical_resume_concat_full.sh`

## Open questions / TODO
- `list-outputs` should warn (or refuse) when 0 outputs found for a stage
  with non-zero submitted job count — would catch this class of failure at
  the right step instead of leaking into the next stage's submit.
- Long-term: retry the concat job's PostEndJob output upload with backoff
  (job-level), or shrink the concat merge factor under high load.
