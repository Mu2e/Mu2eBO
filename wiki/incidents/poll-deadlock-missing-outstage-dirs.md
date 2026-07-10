# poll_cluster deadlocks 24h when workers vanish without /pnfs dirs

**Type:** incident
**Status:** open (recovery recipe documented, no code fix yet)
**Updated:** 2026-06-08

## Summary
`pipeline.py:550 poll_cluster` waits for two convergence conditions:
(a) queue drained `(finished_q >= target)` and
(b) settled bare-form outstage dirs `(settled >= target)` (`target =
0.9*njobs` by default).

There is a **failure-aware short-circuit** at `pipeline.py:612` that
breaks the loop early if the queue is fully empty AND `all_dirs >=
njobs` (bare + hash). But the short-circuit requires *every* job to
leave **some** /pnfs subdir (bare or hash). When workers die before
stage-out even creates the hash-form dir (e.g. worker eviction, lost
output stream, jobsub_lite stage-out crash pre-rename), `all_dirs <
njobs` permanently and the loop sits in the 120s sleep until the
24h `cap_hours` deadline fires.

**Observed pt001 2026-06-08 16:00 → 20:47** (5h elapsed when noticed):
cluster 70267542 had 100/100 left the queue, but only 36/100 outstage
dirs ever appeared on /pnfs. Poll log
`graph_logs/poll_pot_only_1780952431.log` shows
`queue:100/100 settled:36/100 (target=90)` repeating every 2 min.
No log diagnostic about the 64 missing dirs — just the same
benign-looking line for hours.

## Key facts
- **Deadlock condition (pipeline.py:605-619):** loop exits on
  `(finished_q >= target AND settled >= target)` OR
  `(in_queue == 0 AND all_dirs >= njobs AND settled < target)`. If
  workers vanish before writing any /pnfs subdir, neither branch fires
  and the loop runs to the 24h `cap_hours` wall.
- **No mid-poll diagnostic when all_dirs < njobs and in_queue == 0.**
  Adding a 3rd branch that logs `"queue empty, only X/N dirs on /pnfs;
  N-X workers vanished without stage-out"` at first detection would
  surface this in seconds instead of hours.
- **Recovery path A (wait for cap):** 24h from poll start. Harvest then
  proceeds on whatever landed; for `prodtarget` mode where the
  objective is `total_edep / total_POT` (POT scales with the divisor),
  a 36/100 sample is still numerically valid — just noisier and with
  a shifted POT denominator.
- **Recovery path B (manual short-circuit) — VERIFIED 2026-06-08:** kill
  graph.run + its poll child, drop `--quorum` from 0.9 to e.g. 0.35,
  re-`poll` directly via
  `pipeline.py --config <cfg> poll <stage> --quorum 0.35`. The poll
  resumes from the existing `state/<stage>_cluster.txt` (idempotent),
  hits the lowered target, and exits in seconds. Then run
  `pipeline.py --config <cfg> list-outputs <stage>` (writes
  `state/<stage>_outputs.txt`).
- **Resume-graph.run-after-manual-poll does NOT honor outputs.txt
  (2026-06-08).** Relaunching `python -m graph.run` after manual poll
  + list-outputs starts a FRESH `state.stages` from the SqliteSaver
  checkpoint (or from scratch on new thread_id) and re-enters
  `stage_pot_only` from the top — which calls `pio.run_stage` which
  shells `pipeline.py poll` with the DEFAULT `--quorum=0.9`, ignoring
  the outputs.txt on disk. Result: graph.run deadlocks AGAIN on the
  same 36/100 dirs even though list-outputs already converged. Don't
  retry via graph.run after manual poll — skip straight to manual
  harvest + evaluate.
- **Manual harvest + evaluate recipe (skips graph.run entirely):**
  ```bash
  cd /exp/mu2e/app/users/oksuzian/autoresearch
  # 1. harvest (reads outputs.txt → summary.json)
  .venv-graph/bin/python pipeline.py --config pt001 harvest-pot-only
  # 2. evaluate (lands leaderboard row). Mode goes BEFORE subcommand;
  #    args are POSITIONAL config_name + summary_path:
  .venv-graph/bin/python autoresearch_bo_michael.py --mode prodtarget \
      evaluate pt001 \
      /exp/mu2e/data/users/oksuzian/autoresearch_grid/pt001/harvest/summary.json
  ```
  pt001 landed `mu_per_POT=2.16e-3, edep_per_POT_MeV=421.9, obj=2.16e-3`
  on this recipe from 36/100 jobs (180k POT).
- **Recovery path C (resubmit fresh cluster):** appropriate if you
  suspect the 64 missing jobs hit a systemic issue (worker-pool
  outage, /pnfs write storm, jobsub_lite bug). Wipe
  `state/<stage>_{cluster,outputs}.txt` per the [[graph-runner]]
  resubmit recipe.
- **Cause confirmed for pt001 cluster 70267542 (2026-06-08):** 65/100
  jobs were `condor_rm`'d by user (status=3, `RemoveReason = "via
  condor_rm (by user oksuzian)"`) in a 45-second window
  (EnteredCurrentStatus 1780964366–1780964411 = 19:19:26–19:20:11 CT)
  after the first batch of 35 had begun completing. The 35 status=4
  jobs returned cleanly; only 36 reached /pnfs because 1 status=3
  squeaked through stage-out before the kill. Source of the rm is NOT
  this codebase (`grep -rn "condor_rm\|jobsub_rm" pipeline.py graph/`
  returns zero hits) — it was an out-of-band `jobsub_rm` invocation in
  a separate shell.
- **Forensic recipe for classifying lost jobs after the fact:**
  ```bash
  # 1. count by status (3=Removed, 4=Completed, 5=Held)
  condor_history -name <schedd> -constraint 'ClusterId==N' -af JobStatus | sort | uniq -c
  # 2. removal reasons
  condor_history -name <schedd> -constraint 'ClusterId==N && JobStatus==3' \
    -af ProcId ExitCode RemoveReason
  # 3. timing — clustered removals (Δ<60s) = single `jobsub_rm` batch;
  #    spread-out removals = periodic_remove / time-cap / per-worker eviction
  condor_history -name <schedd> -constraint 'ClusterId==N && JobStatus==3' \
    -af EnteredCurrentStatus | sort -n | awk 'NR==1{f=$1}END{print "spread:",$1-f}'
  # 4. full classad for one removed job
  condor_history -name <schedd> -constraint 'ClusterId==N && ProcId==0' -long
  ```
  The schedd name is in submit-log line `Use job id N.0@jobsub03.fnal.gov`.
  Without `-name <schedd>`, condor_history queries the local schedd and
  returns nothing for jobsub_lite clusters. Plain `jobsub_history` is
  truncated/unreliable — the raw condor_history path is authoritative.
- **Other cause hypotheses (unobserved so far) worth knowing if the
  RemoveReason isn't `condor_rm`:**
  - Worker eviction mid-art before any stage-out write
  - jobsub_lite stage-out crash before hash-dir create
  - Output filename mismatch — dir exists but invisible to
    `list_outputs` (`poll_cluster` counts the dir itself, not the
    files in it, so this is NOT the deadlock cause)

## Cross-links
- Related: [[stage-out-rename-race]] (similar /pnfs convergence
  hazard, different failure mode — there the dir IS on /pnfs, just in
  hash form), [[stage-out-lag]] (the original motivator for the
  two-condition convergence gate), [[graph-runner]] (per-stage
  idempotency means resume after wipe is safe)
- Source: `pipeline.py:550-621` (poll_cluster), particularly:551
  (`quorum=0.9`), :564 (`target = quorum * njobs`), :612 (early-exit
  guard), :619 (`cap_hours=24.0` default)

## Open questions / TODO
- Add a 3rd loop branch: when `in_queue == 0 AND all_dirs <
  cfg['njobs']` for ≥ K iterations (e.g. 3 → 6 min), log a clear
  `"WORKERS VANISHED: X/N jobs left no /pnfs subdir"` diagnostic so
  this surfaces in seconds.
- Decide whether the diagnostic should also auto-bail (proceed with
  lowered effective quorum) or remain pure-report. Auto-bail risks
  declaring success on a cluster where most workers died; pure-report
  preserves operator gate but pays the 24h cap.
- Verify if jobsub_lite leaves a `.condor.log`-only dir on /pnfs
  when stage-out crashes pre-rename. If so, that's a different kind
  of stale dir to count and the failure-aware branch could be widened.
