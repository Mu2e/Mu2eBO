---
name: stage-out-rename-race
description: pipeline.py list-outputs FileNotFoundError when /pnfs hash-suffix dirs rename to bare-index mid-glob
type: incident
---

# Stage-out rename race on list-outputs

**Type:** incident
**Status:** recurring — 10-min rename-quiesce cap exceeded under heavy grid contention (foilsg03 R0 2026-06-10 → foilsg05 R0 2026-06-11, **6/10 children lost** at higher hit rate)
**Updated:** 2026-06-11

## Summary
After a grid stage finishes, its outstage tree under
`/pnfs/mu2e/scratch/users/$USER/workflow/default/outstage/<CLUSTER>/00/`
contains per-job subdirs named `NNNNN.<hash>` (e.g. `00137.f2ffbfda`).
The jobsub_lite stage-out daemon renames these to the bare 5-digit form
(`NNNNN`) once the job's files have settled. If `list-outputs` runs while
that rename is in progress, the Python `Path.glob` enumerates a name like
`00137.f2ffbfda`, then `Path.iterdir` on it raises FileNotFoundError because
the dir has already been renamed to `00137`. The pipeline.py stage dies and
the chain emits `FAIL list-<stage>` → `CHAIN_FAIL arm_*`.

A **60-second sleep before retry** is the empirically reliable fix:
once the rename pass completes, every dir is in its bare form and the next
list-outputs sees a clean tree.

## Key facts
- **Failure signature:** Python traceback ending in
  `FileNotFoundError: [Errno 2] No such file or directory:
  '/pnfs/.../00/<NNNNN>.<hash>'` from inside `cmd_list_outputs` /
  `list_outputs` (`pipeline.py:430` / `:388`).
- **Recurrences in q=5 helical batch (2026-05-17/18):**
  - 21:17:41 helical017 list-mubeam — resumed via
    `/tmp/helical_resume_listmubeam.sh` (60s sleep then retry).
  - 22:53:00 helical014 list-run1b_mubeam (cluster 70097980, dir
    `00024.3da6ea97`) — resumed via in-line nohup with 30s sleep.
  - At least 2 more during the same batch window; all resumed.
- **Recurrence 2026-05-19 (graph006, first LangGraph real-grid iteration):**
  list-outputs mubeam dropped on `/pnfs/.../84360860/00/00080.e19a21e2`. The
  Phase 2b `--force`/idempotency guards added that morning **did not help**:
  guards only fire when `<stage>_outputs.txt` exists, but the race triggers
  on the *first* list-outputs of a fresh cluster, before any outputs file is
  written. `route_after_stage` (see [[graph-runner]]) marked
  `stages.mubeam.status="failed"` and terminated the iteration. Recovery was
  manual: rename settled within seconds, then drove the remaining three
  stages + harvest via `pio.run_stage`/`run_harvest` directly. Phase 2c
  candidate: have the graph stage node catch this specific FileNotFoundError
  signature on list-outputs and `time.sleep(60); retry` once before marking
  the stage failed.
- **Latent variant 1 (2026-05-18 helical019):** list-outputs *succeeded* but
  captured one stale hash-suffix path (`00191.d456a2f3/...`) into
  `state/run1b_mubeam_outputs.txt`. The rename completed seconds later. Harvest
  then ran 4 hours after list-outputs and the calo extraction subprocess hit
  `Error in <TFile::TFile>: file ... does not exist`. Failure mode at the user
  level: `summary.json` shows `calo_per_pot: null`, evaluate refuses with
  "missing s_over_sqrt_b or calo_per_pot". **Fix is to re-run `list-outputs`
  (refreshes the state file with bare-index paths) then re-run harvest.** Only
  1 of 200 paths was stale, but the calo extract aborts on first OSError.
- **Latent variant 2 (2026-05-18 helical026 + helical027):** list-outputs of
  the *mubeam* stage cached stale `NNNNN.<hash>/...` paths into
  `state/mubeam_outputs.txt`. Minutes later `pipeline.py:stage_hardlink_farm`
  walked that state file at submit-concat time and called `os.link(src, dst)`
  on the stale source → FileNotFoundError → `FAIL submit-concat rc=1`. Both
  configs failed in the same 5-minute window (09:50:07 and 09:54:35). Stale
  basenames captured: `00044.e6690bac` (helical026), `00053.f5446e21`
  (helical027). **Fix is the same as variant 1:** re-run
  `pipeline.py --config <cfg> list-outputs mubeam` to refresh state with bare
  paths, then re-trigger `submit concat`. This proves the race window is wider
  than originally thought — *any* downstream code that re-reads the state file
  is vulnerable, not just harvest.
- **Why bash retry works but the original script dies:** the bash `run`
  wrapper just runs `python3 pipeline.py ... list-outputs` once, no retry.
  The race window is short (seconds, not minutes) so any 30-60s wait clears
  it.
- **Recoverability:** every observed instance was recoverable; no data loss.
- **Misleading CHAIN_FAIL noise:** the original `/tmp/helical_full.sh`
  chain script emits `CHAIN_FAIL arm_a=N arm_b=M` whenever an arm's
  list-outputs or submit step returns nonzero. The parallel recovery
  script then succeeds and emits its own `CHAIN_DONE`. Future sessions
  reading `/tmp/helical_chain_events.log` should treat per-config events
  as latest-event-wins, NOT first-event-wins. A `CHAIN_FAIL` preceded by
  a `RESUME_*` or `RECOVER_*` for the same config is not a real failure.

## Cross-links
- Related: [[stage-out-lag]], [[concurrent-token-contention]], [[grid-job-completion-check]],
  [[concat-xrootd-fileopen-postendjob]], [[stage-out-lag]], [[bo-helical]], [[foilsg-grid-tarball-scalar-holeradius-fallback]], [[harvest-pyroot-nfs-rpc-hang]], [[poll-deadlock-missing-outstage-dirs]]
- Source: `pipeline.py:list_outputs` (function), `pipeline.py:cmd_list_outputs`,
  `pipeline.py:stage_hardlink_farm` (line 260, the `os.link` call that fails
  on stale paths during submit-concat)
- Resume scripts (ad-hoc, /tmp): `helical_resume_listmubeam.sh`,
  `helical_resume_concat.sh` (post-relist retry pattern is `list-outputs
  mubeam` → re-submit concat → continue chain),
  `helical_recover_listrun1b.sh` (NEW 2026-05-18: arm-B-only recovery —
  relist run1b_mubeam, emit ARM_B_DONE, then idle-poll for arm-A's
  `state/mustops_ce_outputs.txt` before triggering harvest+evaluate; used
  when run1b list races while arm_a is still running),
  `helical_recover_evaluate.sh` (NEW 2026-05-18: variant-1 recovery —
  relist run1b_mubeam → reharvest → reevaluate; fixes `calo_per_pot: null`
  in summary.json caused by one stale path silently aborting the calo
  extraction subprocess)

## Resolution

Landed 2026-05-19 in `pipeline.py:list_outputs`:

- **Bare-form-only glob**: pattern changed from `*/<output_glob>` to
  `[0-9][0-9][0-9][0-9][0-9]/<output_glob>`. The hash-suffix subdirs
  (`NNNNN.<hash>`) are no longer enumerated or persisted, eliminating
  both the crash mode (FileNotFoundError mid-iterdir) and latent
  variants 1+2 (stale paths in `state/<stage>_outputs.txt` that break
  downstream harvest / submit-concat seconds later) at the source.
- **Wait-for-rename guard**: before globbing, `base.iterdir()` scans for
  any subdir still in `NNNNN.<hash>` form. If found, `time.sleep(30)`
  and re-check (up to 10 min cap) — otherwise the bare-only glob would
  silently undercount during the rename pass. Happy path (rename
  already complete): one `iterdir`, zero sleep.

Why this is better than the initial fix (a try/except + post-hoc stale
filter): no retry gymnastics, no path filtering after the fact, no
ambiguity about what gets persisted. The persisted state file is
*structurally* guaranteed to contain only bare-form paths.

## Recurrence 2026-06-10 (foilsg03 R0) — 10-min cap exceeded

2/10 foilsg03 R0 children (`R00_03`, `R00_08`) died at submit-concat
because the wait-for-rename guard's **20 × 30s = 10 min cap was reached
without quiescence** under heavy contention:

- `list-outputs mubeam` logged `200 job dir(s) still mid-rename (e.g.
  00001.2cfafda0)` for all 20 attempts, then `WARN: rename pass did not
  quiesce after 10 min; globbing bare form anyway (may undercount)`.
- Result: `0 output file(s) -> state/mubeam_outputs.txt` (every dir was
  still hash-form), then submit-concat fired `mu2ejobfcl --jobdef ... --
  index 0` against an empty input list → `job_primary_inputs(): invalid
  index 0` → rc=255 → `[graph] terminating ... stage concat failed`.
- Grid context: user had **3758 jobs in queue concurrently** (other
  campaigns + foilsg03), saturating jobsub_lite stage-out worker pool.
- The OTHER 8/10 children of the same R0 batch saw their mubeam
  outstages rename cleanly within the 10 min window — pure stage-out
  rate-jitter under load, not a per-config issue.
- **Triggered the foilsg03 false-positive early-exit** (see
  [[closed-loop-barrier-timeout-zero-rows-falsepos]]): these 2 quick
  failures plus 8 slow successes = "0 new rows by 240-min barrier" →
  `decide_next` killed the campaign.
- Lesson: the 10-min cap is **not enough** under heavy grid contention.
  Either raise it (configurable env knob, e.g. `RENAME_QUIESCE_MAX_MIN`)
  or — better — change the WARN-and-continue branch to FAIL hard so the
  stage retries from a clean slate rather than submitting an empty
  concat jobdef.

## ~~Recurrence 2026-06-11 (foilsg05 R0)~~ — RETRACTED 2026-06-12: not this incident

foilsg05 R0's 7/10 `submit concat` / `job_primary_inputs(): invalid
index 0` failures (R00_00,01,02,03,04,07,09) were originally attributed
here. **Wrong.** Verified 2026-06-12: foilsg05R00_00's mubeam job logs show
`G4Tubs: Invalid values for radii in solid: Foil_00, pRMin=52.39, pRMax=50`
→ all 200 jobs crashed at G4 init → outstage dirs stay in hash form
*because the jobs failed*, not because the rename pass lagged. Root cause
is [[foilsg-grid-tarball-scalar-holeradius-fallback]] (grid tarball lacks
the holeRadii-vector patch; scalar-mean fallback exceeds group-0 rOut).

**Diagnostic discriminator for next time** (the two failure modes share
the rename-quiesce WARN + empty-jobdef rc=255 surface signature):
- rename-LAG (this incident): poll shows `settled` *climbing* across
  ticks; bare-form dirs appear progressively; job logs are healthy.
- job-FAILURE (not this incident): poll shows `settled: 0/N` flat with
  ALL dirs hash-form (`poll_mubeam` even prints "likely failed jobs");
  check a job `.log` inside a hash dir BEFORE blaming stage-out.

The grid-contention narrative (1220 queued / 1186 idle) was real but
coincidental. foilsg03's 2/10 (genuine 10-min-cap exceedance with healthy
jobs under a 3758-job queue) remains a true instance of this incident.
