---
name: concurrent-token-contention
description: jobsub_lite mu2ejobsub races when N>1 chains submit within ~10s; need 60-90s stagger
type: incident
---

# Concurrent token contention on mu2ejobsub

**Type:** incident
**Status:** resolved (mitigated 2026-05-20: host-wide `fcntl.flock` on
`/tmp/mu2e_submit.$USER.lock` wraps the token-refresh + `mu2ejobsub`
critical section in `pipeline.py:_submit_lock`; serializes all submits
across all concurrent chains)
**Updated:** 2026-06-18

## Summary
When two or more pipeline.py chains run concurrently and both reach a
`submit <stage>` step within a few seconds of each other, `mu2ejobsub`
intermittently fails with no cluster ID returned (token / vault / htgettoken
race in jobsub_lite). The bash chain script `run` wrapper then emits
`FAIL submit-<stage> rc=1` and the chain dies at `CHAIN_FAIL submits`.

8-second stagger between launches is **not enough**. Empirically a
**60-90s stagger** between concurrent `mu2ejobsub` invocations avoids the
collision in steady-state; under heavier load (q=5 with retries piling up),
**300s** is more reliable. The other observed collision is two chains writing
into the same jobsub_lite cache dir bucketed by `YYYY_MM_DD_HHMMSS_*` — if
they hit the same second they overwrite each other's submission cnf. The race
affects **every** stage submit (mubeam, run1b_mubeam, concat, mustops_ce);
mustops_ce was thought to be safer because it submits later in the chain when
others have moved on, but the q=5 2026-05-18 batch had all five chains hit
mustops_ce within a 5-minute window — three of five failed.

## Key facts
- **Failure signature:** stderr/log shows `Submitting job(s)` with no
  `Job <cluster>.0 submitted` line; rc=1.
- **Recurrences in q=5 helical batch (2026-05-17):**
  - 21:10:04 helical015 submit-run1b_mubeam (token race) — resumed via
    `/tmp/helical_resume_run1b.sh`.
  - 21:12:45 + 21:15:08 helical014 submit-run1b_mubeam (auth + parse fail) —
    resumed manually with extra delay; eventually cluster 70097980.
  - 21:20:01 helical013 + helical016 both submit-concat (same jobsub_lite
    cache dir `2026_05_17_211958_*`) — resumed serially with 90s gap
    (`/tmp/helical_resume_concat.sh`).
- **Recurrences in q=5 helical018-022 batch (2026-05-18):**
  - 00:48-00:57 four submit-mubeam/run1b/concat failures across configs;
    all resumed via the existing resume scripts with 90s buffers.
  - 01:14:44 helical018 submit-mustops_ce — first time mustops_ce hit the
    race; NEW resume script `/tmp/helical_resume_mustops.sh` created.
  - 01:31:35 helical019 submit-mustops_ce — token race.
  - 00:59:48 + 01:03:44 + 01:09:33 helical019 submit-concat needed three
    retries; 90s and 180s buffers both insufficient, 300s finally worked.
  - **Empirical pacing for q=5 in same minute:** 300s stagger between
    retries of the same stage clears the race more reliably than 90s.
- **Recurrences in q=5 helical023-027 batch (2026-05-18 morning):**
  - 300s launch stagger (FULL_START every ~4 min) **was clean through
    SUBMITS_DONE for all 5 chains** — no submit collisions at the initial
    mubeam/run1b_mubeam fork. First time we've seen q=5 launches all hit
    the grid without a retry.
  - BUT: chains drifted into sync at the concat→mustops_ce transition.
    helical026 hit submit-concat at 09:50:07 (stage-out rename race —
    [[stage-out-rename-race]] variant 2), and on its 10:02:09 retry it
    collided with helical025's submit-mustops_ce → htgettoken failed.
  - **Lesson:** launch-time stagger does not propagate. Stage wall times
    are nearly identical across configs (mubeam ~6 min, run1b_mubeam
    ~5 min), so chains that start staggered re-converge at every stage
    boundary. The token-race window is per-stage-submit, not per-chain.
- **Resume pattern that works:** wait ≥90s, then re-run *only* the failed
  submit and continue the chain from that point.
- **Recoverability:** every observed instance was recoverable; no data loss.

- **Preemptive token renewal landed 2026-05-18** (`pipeline.py:319-326`):
  `submit_stage` now runs `mu2einit && getToken` immediately before
  `mu2ejobsub`. `getToken` is idempotent and very cheap; refreshing it on
  every submit eliminates the "stale cached bearer token" sub-flavor of the
  race. It does NOT fix the jobsub_lite cache-dir same-second collision —
  for that, the 90-300s submit stagger between *concurrent chains* is still
  required.
- **Failure-mode disambiguation (post-2026-05-18):** `FAIL submit-<stage>
  rc=1` is no longer presumed to be token contention. Three causes share
  the surface:
  1. Token race (this page) — stderr mentions htgettoken / vault / no
     cluster ID parsed.
  2. Stage-out rename race ([[stage-out-rename-race]]) — `FileNotFoundError`
     inside `stage_hardlink_farm` because /pnfs `NNNNN.<hash>` dir renamed
     to bare-index mid-glob.
  3. Empty inputs file ([[concat-xrootd-fileopen-postendjob]]) — upstream
     concat job lost its .art in PostEndJob xrootd timeout, so
     `<stage>_basenames.txt` is empty.
  See [[concat-xrootd-fileopen-postendjob]] for the diagnostic ladder.

## Cross-links
- Related: [[stage-out-rename-race]], [[grid-job-completion-check]],
  [[bo-helical]], [[concat-xrootd-fileopen-postendjob]]
- Source: `pipeline.py:submit_stage` (preemptive `getToken` landed
  2026-05-18; still no flock for cache-dir race)
- Resume scripts (ad-hoc, /tmp): `helical_resume_run1b.sh`,
  `helical_resume_concat.sh`, `helical_resume_concat_full.sh`,
  `helical_resume_mustops.sh`

- **Submit lock landed 2026-05-20** (`pipeline.py:_submit_lock`):
  motivated by graph014 (q=5 pareto pick batch 1) and graph019 (batch 2)
  both crashing at run1b_mubeam submit with `condor_vault_storer: Failed
  to obtain weakened token` when 4 concurrent graph chains converged on
  the submit window. The lock is a single host-wide `fcntl.flock`
  exclusive blocking acquire on `/tmp/mu2e_submit.$USER.lock`, held
  across `getToken` + `mu2ejobsub` + cluster-parse + cluster.txt write
  (~30-90s typical). Effect: chains run their pipelines in parallel but
  serialize through submit. Eliminates **both** the bearer-token race
  and the jobsub_lite cache-dir same-second collision in one stroke,
  since the cache dir is keyed on submit start time and only one process
  starts a submit at a time. Throughput cost: ~4 chains × 4 stages × 60s =
  ~16 min total serialized submit time over a ~2-hour run — negligible.

- **Gauging submit activity before launching a 2nd concurrent campaign (2026-06-18):**
  the closed-loop child logs (`graph_data/closed_loop_logs/<cfg>.log`) only
  snapshot the **preflight** state (`{"preflight": "pass", "objective": null}`)
  and never log mubeam/run1b_mubeam submit or grid-poll progress — they are
  **useless** for telling whether a campaign is mid-submit. The reliable
  in-flight signal is the process tree: `pgrep -f "mu2ejobsub|jobsub_submit"`
  (live grid submit) and `pgrep -f "pipeline.py.*submit <stage>"` (which child +
  stage). A running campaign cycles through submit bursts at **every** stage
  boundary (per the per-stage-submit point above), so there is no single "drain"
  moment until it nears completion. **But:** because the host-wide submit lock
  above serializes `getToken`+`mu2ejobsub` across *all* chains on the host
  (including a different-prefix/different-mode campaign), a 2nd concurrent
  closed-loop is **token-safe regardless of launch timing** — the lock, not
  launch-time quiet-window picking, is what prevents the race. Waiting for a
  quiet `pgrep` window only avoids queueing latency, not failures.

## Open questions / TODO
- (none — closed by the 2026-05-20 lock)
