---
name: stage-out-lag
description: pipeline.py list-outputs "outstage missing" when poll returns before /pnfs stage-out catches up; resolved by convergence-poll gate
type: incident
---

# Stage-out lag race on list-outputs

**Type:** incident
**Status:** resolved (2026-05-20; convergence-poll gate in `pipeline.py:poll_cluster`)
**Updated:** 2026-07-09 (added downstream rc=25 signature)

> **Downstream signature (2026-07-09, foilsflash10R00_01): empty captured path
> → `mu2ejobdef` rc=25.** A DIFFERENT face of the same class — instead of
> "outstage missing / rc=1", list-outputs concat wrote a **single BLANK line**
> to `state/concat_outputs.txt` (path not yet resolved at read time). The
> resampler-input hardlink farm then produced an empty
> `mustops_ce_basenames.txt` (1 byte), and the downstream `mu2ejobdef` submit
> died **rc=25** ("the line is empty or contains white spaces or other
> non-printable characters"). Diagnostic: compare the failed child's
> `concat_outputs.txt` (blank line) vs a healthy sibling's (real /pnfs path).
> Cosmetic spack/muse "syntax error / error importing function definition"
> lines above it are benign ([[sourced-env-stderr-swallowed]]) — the rc=25 +
> empty-basenames is the real cause. Single-child transient, not geometry-
> or box-related; not worth mid-round recovery on a q=8 probe.

## Summary
`list_outputs` raised `SystemExit("[<stage>] outstage missing: /pnfs/.../<cluster>/00")`
when invoked too soon after `poll_cluster` returned. Root cause: `poll_cluster`
declared success on a **proxy signal** — 90% of cluster jobs had left
`jobsub_q` — but stage-out (worker → /pnfs copy + jobsub_lite
hash → bare rename) is asynchronous to queue exit and lags by minutes.
When `list-outputs` ran immediately, the `00/` subdirectory under the cluster
outstage didn't exist yet (no job had committed its first stage-out), and the
existence guard hard-exited. The graph runner treated this as fatal and
terminated the iteration with `objective: null`. This was distinct from
the sibling [[stage-out-rename-race]] — that race fires *after* `00/` exists
while hash-form siblings are still renaming; this one fires *before* `00/`
exists at all.

## Key facts
- **Failure signature:** `[<stage>] outstage missing: /pnfs/.../<cluster>/00`
  in `state/graph_logs/list-outputs_<stage>_<unix>.log`, with rc=1. Graph
  runner records `errors: ['stage[<stage>/<cfg>]: list-outputs ... failed
  (rc=1)']` and `stages.<stage>.status = "failed"`.
- **Confirmed instances (2026-05-20):** `graph018` (concat list-outputs at
  ~11:17), `graph021` (mubeam list-outputs at 12:18). Both were timing-only
  failures — manual re-run of `list-outputs` 10-30 min later succeeded and
  recovered all 200/200 outputs. No held jobs, no worker pathology.
- **Why the 90% queue quorum lied:** jobs leave `jobsub_q` as soon as they
  start finishing; the worker-node → /pnfs copy and the jobsub_lite
  hash → bare rename happen *after* queue exit, asynchronously. The window
  is typically 1-10 min but is unbounded under filesystem load.
- **Original code (pre-fix):** `poll_cluster` returned on
  `finished_queue >= 0.9 * njobs`; `list_outputs` then ran one shot and
  hard-exited if `base.exists()` was False. Only 41% of the actual failure
  rate had nothing to do with held jobs — the `n_failed=83/200` reported
  in the LangGraph state was a mirage (computed as
  `target - len(outputs_file)`, where `outputs_file` was empty because
  `list-outputs` exited too early). True stage-out completion was 200/200
  in every case examined.

## The fix: convergence-poll gate
`poll_cluster` now requires BOTH signals before returning:

```
finished_queue >= target  AND  settled_bare_dirs >= target
```

where `settled_bare_dirs = sum(1 for d in base.iterdir() if d.name.isdigit())`
on the same `OUTSTAGE/<cluster>/00/` directory `list_outputs` will read.
Reasoning:
- The queue check still catches the genuine **held-tail** case — if 20 jobs
  go held forever they keep `in_queue=20`, `finished_queue=180 >= target`
  but `settled<200`, so the 24h cap fires (same as before the fix).
- The settled-dir check structurally guarantees `list_outputs`'s precondition.
  `list_outputs`'s `SystemExit` on missing base now indicates a real bug
  in the convergence gate, not a timing race.
- `iterdir()` on /pnfs is much cheaper than `jobsub_q` (no network); adding
  it to every poll cycle is negligible.
- Poll output line now reads
  `[<ts>] [<stage> cluster=<c>] queue:Q/N settled:S/N (target=T)`
  for clean diagnosability.

## Why retry-in-list_outputs was rejected
Pre-fix, the obvious bandaid was to bolt a `base.exists()` retry loop onto
`list_outputs`, mirroring the rename-race retry below it. Rejected because:
- The symptom is "the poll gate lied"; retrying downstream hides the lie.
- Two consecutive retry loops in one function compound latency caps in
  surprising ways (10 min + 10 min = 20 min) for what should be a
  single phenomenon.
- The fix belongs at the source-of-truth boundary: poll *should* be true
  when the stage is actually done, not when one proxy says it is.

## Cross-links
- Related: [[stage-out-rename-race]] (sibling race once `00/` exists),
  [[concurrent-token-contention]] (separate race at submit time),
  [[grid-job-completion-check]] (broader playbook on jobsub_q vs /pnfs)
- Source: `pipeline.py:poll_cluster` (convergence gate),
  `pipeline.py:list_outputs` (precondition assert)
- Consumer: `graph/pipeline_io.py:run_stage` (calls submit→poll→list-outputs
  as three CLI verbs in sequence; no changes needed)

## Open questions / TODO
- Should the 24h `cap_hours` warning escalate to a hard error? Today
  proceeding-with-whatever-landed silently under-samples the BO objective.
