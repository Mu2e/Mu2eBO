---
type: incident
title: Grid job completion check tooling
description: use `jobsub_q` + plain `/pnfs ls`; avoid `condor_q` and `ifdh`
status: resolved
timestamp: '2026-05-17'
---

# Grid job completion check tooling

## Summary
For checking whether a Mu2e grid submission has completed, use `jobsub_q` and
plain `/pnfs ls`. Avoid `condor_q` (wrong scheduler view) and `ifdh` (heavyweight
and unreliable for simple existence checks).

## Key facts
- **Use:** `jobsub_q -G mu2e --user $USER` for queue state; `ls /pnfs/.../<output>` for
  product existence
- **`-G mu2e` (or `$GROUP=mu2e`) is required.** Without it `jobsub_q` errors
  `NameError: needs -G group or $GROUP`. The error is easy to miss when the
  call sits inside an `awk` filter — the pipeline runs to completion with
  *zero* results and looks like "queue drained." Caused a false-positive on
  2026-05-17 that almost let a broken 400-job run go unnoticed.
- **Avoid:** `condor_q`, `ifdh ls`
- Memory pointer: `~/.claude/.../memory/feedback_grid_completion_check.md`
- **Success signature (mubeam/run1b_mubeam):** outstage shows `.art:.log = 5:1`
  per job (5 outputs blocks: EarlyFlash, Flash, IPAStops, TargetStops, PolyStops).
  A drained 200-job cluster healthy = 1000 .art + 200 .log under
  `/pnfs/.../outstage/<cid>/`. mustops_ce is 1:1, concat is 2:1.
- **Failure signature:** `.log` files with **no** `.art` siblings means jobs
  died before any module produced output — almost always G4 init failure.
  See [template-fcl-staleness](/incidents/template-fcl-staleness.md) for the canonical example.

## Cross-links
- Driver: [pipeline](/drivers/pipeline.md)
- Related: [template-fcl-staleness](/incidents/template-fcl-staleness.md), [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md), [concurrent-token-contention](/incidents/concurrent-token-contention.md), [stage-out-rename-race](/incidents/stage-out-rename-race.md), [stage-out-lag](/incidents/stage-out-lag.md), [harvest-denominator-bug](/incidents/harvest-denominator-bug.md), [calo-constant-across-helical](/incidents/calo-constant-across-helical.md), [kerberos-mid-run-expiry](/incidents/kerberos-mid-run-expiry.md)
