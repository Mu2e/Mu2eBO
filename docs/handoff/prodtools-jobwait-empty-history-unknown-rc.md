# prodtools: `jobwait` reports a fully successful cluster as `0/N ok, unknown`

**Repo:** `oksuzian/prodtools` (branch `code-tarball`; also shipped as
`/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0`)
**Files in scope:** `utils/jobwait.py`, `docs/superpowers/specs/2026-08-16-jobwait-design.md`
**Reported:** 2026-08-20, from the autoresearch closed-loop grid path
**Severity:** loses an entire completed cluster; schedd-dependent, so it can
strike any campaign

**Read this one second.** It is a different defect from
`prodtools-check-inputs-dir-inloc.md` and was only reachable after that one
was fixed.

---

## Summary

`jobwait` watched a 15-job cluster to `drained`, then reported:

```
[jobwait] cluster 29868598@jobsub05.fnal.gov: drained
[jobwait] 0/15 ok, failed: -, unknown: [0, 1, ..., 14]
```

Every one of those 15 jobs had in fact succeeded. All 15 outstage
directories are present and complete, and each worker log ends with

```
=== Mu2e execution completed successfully ===
Art has completed and will exit with status 0.
```

with all six output files copied to outstage. The physics ran and the data
landed; only the *verdict* was lost. The caller (autoresearch) correctly
refuses to treat `unknown` as `ok`, so the chain terminated and a ~1 h
cluster was wasted.

`collect_exit_codes` (`utils/jobwait.py:88`) makes one history call and
treats an empty result as unknown, which is what the design says to do:

```
jobsub_history -G mu2e -J <cluster>@<schedd> -limit <njobs> -af ProcId ExitCode
```

For this cluster that call returns the table header and **zero data rows**.

## The part that matters: it is schedd-dependent, not age-dependent

The design assumes history is reliable at drain time and only *fades* with
age (spec line 21: "condor history is a fading record"). That assumption does
not hold here. Two clusters, same user, same day, same prodtools:

| cluster | `-af ProcId ExitCode` result |
|---|---|
| `86299508@jobsub01.fnal.gov` (11:00) | clean `proc rc` rows, as designed |
| `29868598@jobsub05.fnal.gov` (12:26) | header only, zero rows |

The jobsub05 cluster was still returning zero rows **50 minutes after its
jobs finished**, so this is not stage-out lag or a slow history write. Tried
and all equally empty: schedd-qualified (`29868598@jobsub05.fnal.gov`),
proc-qualified (`29868598.0@jobsub05.fnal.gov`), and bare (`29868598`).
The `-af` flag itself is fine — it returns correct rows for the jobsub01
cluster.

Since schedd assignment at submit is effectively arbitrary from the
submitter's side, **any** campaign can draw a schedd whose history does not
answer, and lose a complete cluster to it.

## Reproduction

Submit any cluster, wait for it to drain, then:

```bash
jobsub_history -G mu2e -J <cluster>@<schedd> -limit <njobs> -af ProcId ExitCode
```

If that prints only the header, `jobwait` on that cluster will report
`0/N ok` with every index `unknown` and exit nonzero, regardless of how the
jobs actually ended. Compare against a cluster on a different schedd to see
the asymmetry.

## What to investigate first

**This may not be a prodtools defect at all.** The first question is why
`jobsub_history` returns nothing for a jobsub05 cluster that demonstrably
ran: whether that schedd's history is queryable through `jobsub_history` at
all, whether it needs different arguments, or whether this is a jobsub /
schedd-configuration issue to raise with the jobsub maintainers rather than
fix here. Please establish that before changing `jobwait` — a workaround
built on a misdiagnosis is worse than the current honest failure.

If the query can be made to work (different flags, a retry with a delay that
actually converges, a second schedd endpoint), that is the clean fix and
nothing below is needed.

## If the query cannot be made reliable

Then the design decision at spec lines 61-67 deserves reopening — and that
section opens with "All operator decisions from the 2026-08-16 design
conversation; recorded so they are not 'improved' back in later" (spec
lines 58-59). That stopper is doing its job and should not be stepped over
lightly: if you are reading this brief and the evidence below does not
convince you, the correct action is to leave the design alone and report back,
not to relax it. What the spec records:

> **No file checking, primary or fallback.** Pre-drain file checks race
> condor's evict-and-rerun … Post-drain fallback counting was rejected as
> guessing: empty history → honest `unknown` + nonzero exit beats inferred
> success. It also keeps jobwait free of any /pnfs or xrootd dependency.

Every one of those reasons still stands, and none of the evidence here
contradicts any of them. What has changed is only the *frequency and cost* of
the case they trade against: the spec treats empty history as a
rare degraded corner, and it turns out to be a reproducible whole-cluster
loss on at least one schedd in normal rotation. "Honest unknown" is the right
answer when history is merely unavailable for a few procs; it is an expensive
answer when it is unavailable for every proc of every cluster on a schedd.

Two candidate directions, both of which weaken the current guarantees and
should be weighed rather than assumed:

1. **Post-drain worker-log parse, fallback only.** Each proc's outstage log
   ends with `Art has completed and will exit with status 0`. This is a
   stronger signal than file existence — it is the job reporting its own
   exit, not an inference from artifacts — so the evict-and-rerun objection
   does not apply the same way (an evicted-and-rerun job overwrites its log
   with the rerun's outcome). It does introduce the /pnfs dependency the spec
   deliberately avoided, so it must be strictly a fallback: only when history
   returned nothing, never in the normal path.
2. **Report the distinction rather than resolving it.** Keep `rc: null`, but
   add a summary field distinguishing "history had no record" from "history
   answered and this proc was absent", and let the caller decide. This
   preserves jobwait's no-filesystem property and moves the policy to the
   caller — at the cost of every caller needing to implement it.

If direction 1 is taken, note the JSON already carries each job's expected
`outputs` (derived from the cnf by `job_output_names`, not from the
filesystem), so the log path is derivable without new naming logic.

## Acceptance

Whichever direction: a cluster whose jobs all exited 0 must not be reported
as `0/N ok`. If the outcome genuinely cannot be determined, the failure
should name the schedd and the empty-history condition explicitly, so an
operator reads "history unavailable on <schedd>" rather than a bare
`unknown` list that looks like the jobs failed.

## Tests

Extend `test/test_jobwait.py`:

1. History returns zero rows for every proc → the summary distinguishes this
   from a genuine per-proc absence (whichever field the chosen direction
   adds), and the log/CLI output names the empty-history condition.
2. If direction 1 is implemented: history empty + worker logs present and
   reporting status 0 → `ok == njobs`; history empty + a log reporting
   nonzero or truncated → that index stays `unknown` or `failed`, never `ok`.
3. Regression: history answering normally must not consult the filesystem at
   all (inject a log reader that raises if called).

## Context for the reporter

Observed from the autoresearch closed loop, config `gridsmoke04`, mode
foilspf, stage `mubeam`, cluster `29868598@jobsub05.fnal.gov`, 15 jobs at
200k events. Outstage preserved at
`/pnfs/mu2e/scratch/users/oksuzian/workflow/default/outstage/29868598/` with
all 15 proc directories intact if you want to inspect the logs directly. The
caller's behaviour is not in question: it follows the documented contract
that `unknown`/`rc: null` never counts as `ok`, and that guard is what turned
a silent wrong answer into a visible failure.
