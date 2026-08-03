---
type: incident
title: closed-loop barrier-timeout + zero-rows early-exit false-positive
description: foilsg03 R0 exited at 240-min barrier timeout with only 2/10 children
  resolved (both concat-failed); `decide_next` "0 new rows → all failed → exit"
  guard misreads barrier-timeout as all-failed; 8 orphan children kept running,
  rows landed, but no R1 picker; fix = gate exit on `completed == q`
status: resolved
status_note: fix landed 2026-06-12 (corrected zero_rows gate + liveness-wait barrier
  [no pacing timeout; lone 24h backstop `--barrier-max-min`] + dead-pid detection
  + stop_seen propagation); design narrative + simplification addendum in `docs/closed-loop-barrier-fix.md`;
  all tests green
timestamp: '2026-06-12'
---

# closed-loop barrier-timeout + zero-rows early-exit false-positive

## Summary

foilsg03 R0 exited after 240 min with `decide_next[r0]: 0 new leaderboard
rows this round (before=43 after=43) — all children failed; exiting early`
even though **only 2 of 10 children had actually resolved** (both at the
`concat` stage). The remaining 8 children were still running normally and
would land rows ~hours later — but the parent had already triggered its
"all children failed → bail" guard and exited. The 8 orphans continued
running unsupervised; their rows landed in the leaderboard but no
subsequent round was picked.

## Key facts

- **Trigger:** `barrier_timeout_min` (default **240 min**) elapsed at R0.
  Parent logged `barrier[r0]: timeout after 240min; 8 children still
  pending` and immediately advanced to `decide_next`.
- **`decide_next`'s "all children failed" guard** misinterprets a barrier
  *timeout* as "all children failed." The guard's input is "0 new
  leaderboard rows this round" — it cannot distinguish *failed* from
  *still running*. With only 2 fast-failing children (both `concat`
  failures) and 8 slow successes still inflight, the leaderboard sees no
  new rows and the parent exits. Found in
  `graph/closed_loop.py` (`decide_next` zero-rows branch).
- **Wall-clock budget**: 240 min is not enough for foilsg's full
  mubeam+downstream+harvest chain when grid contention is high (3758
  user jobs in queue at the time of incident). foilsg02 R3→R4 took ~3 h
  with cleaner grid load; under contention you need 5-6 h.
- **Orphan behavior is benign for the leaderboard**: orphaned
  graph.run children keep running, complete their grid chains, harvest,
  and write rows. The damage is procedural — no next-round picker is
  spawned, so the campaign stalls at R0 even though the data is there.
- **Concat-stage failures (2/10 at R0)**: `[graph] terminating
  foilsg03R00_{03,08}: stage concat failed (failed_stages=['concat'])`.
  Likely the [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md) failure mode —
  xrootd FileOpenError under high concurrent IO. Not the root cause of
  the campaign loss, but it was the trigger for the false-positive
  early-exit (those 2 quick failures plus 8 slow successes = "0 rows by
  deadline").
- **Distinct from**: [closed-loop-final-round-orphan-children](/incidents/closed-loop-final-round-orphan-children.md) which
  is about the *final* round exiting cleanly while a child is still
  running. This is the *first* round exiting on a barrier timeout
  whose "0 rows" signal is then misread as "all failed."

## Recovery / mitigation

- **Don't kill the orphans** — they will finish and contribute leaderboard
  rows. Relaunch under a new `--name-prefix` (e.g. `foilsg04`) after the
  orphans land. Reusing `foilsg03` triggers
  [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md).
- **Raise barrier timeout** for the next launch:
  `--barrier-timeout-min 360` (or 480 under heavy grid contention) so the
  zero-rows guard isn't tripped by slow successes.
- **Code fix (not yet applied)**: `decide_next` should distinguish
  "barrier timed out with N pending" from "barrier resolved with all-fail."
  One-liner: if the barrier exited via timeout AND `completed < q`, treat
  as transient and either re-poll once or carry the round forward without
  the "exiting early" guard. The "0 rows → exit" rule is correct only
  when `completed == q`.

## Recurrence 2026-06-11 (foilsg05 R0) — 360-min cap also too tight

foilsg05 was launched with `--barrier-timeout-min 360` (raised per foilsg03
recommendation). **Same outcome at the higher cap**:

- 7/10 children fast-failed at `concat` (same [stage-out-rename-race](/incidents/stage-out-rename-race.md) —
  10-min rename-quiesce cap exceeded under heavy /pnfs contention).
- 3 survivors (R00_05, _06, _08) **still in `mustops_ce` stage** at the
  360-min mark — 487 grid jobs inflight across the three clusters when the
  barrier tripped.
- `barrier[r0]: timeout after 360min; 3 children still pending` →
  `decide_next[r0]: 0 new leaderboard rows … all children failed; exiting
  early` (parent exited `done`, leaving the 3 survivors orphaned exactly
  like foilsg03's 8 orphans).
- Grid context: 1222 jobs / 46 running / 1174 idle — workers severely
  starved (same picture as the recurrence section in
  [stage-out-rename-race](/incidents/stage-out-rename-race.md)).
- **Implication**: a per-round wall-clock cap can't be the only guard.
  Even 6h is insufficient when stage-out workers are saturated. The
  code fix (gate exit on `completed == q`, not "0 rows") is now load-
  bearing — two foilsg launches (foilsg03, foilsg05) hit this in 48h.
  (foilsg04 is NOT an instance: its all-10 wipeout was the RCDS
  disk-quota failure — all children genuinely failed fast, so the
  zero-rows exit there was *correct* behavior, see
  [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md).)

## Cross-links
- Related: [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (barrier source-of-truth),, [rolling-no-row-streak-false-increment](/incidents/rolling-no-row-streak-false-increment.md)
  [closed-loop-final-round-orphan-children](/incidents/closed-loop-final-round-orphan-children.md) (orphan pattern at end vs
  here at start), [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)
  (why reusing the prefix doesn't work),
  [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md) (likely cause of the 2 quick
  failures that triggered the misread), [closed-loop-parent-signal-kill-midlaunch](/incidents/closed-loop-parent-signal-kill-midlaunch.md), [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md), [pipeline-poll-rc120-atexit-death](/incidents/pipeline-poll-rc120-atexit-death.md)
- Source files: `graph/closed_loop.py` `barrier_round`,
  `graph/closed_loop.py` `decide_next` zero-rows branch
- Project: [bo-foilsg](/projects/bo-foilsg.md) (foilsg03 launch that hit this)

## Open questions / TODO
- Patch `decide_next` to gate the early-exit on `completed == q` (not on
  `zero rows`). **Implementation gotcha (caught in 2026-06-12 review):**
  `completed_names` is **cumulative across rounds** — `node_barrier:510`
  seeds `completed = set(state.get("completed_names", []))` from prior
  state, and `:561` returns the union. Naive `len(completed) >= len(launched)`
  is trivially true at round N>0 → the guard collapses to current behavior.
  Correct shape: intersect with this-round's launched set,
  `this_round_done = sum(1 for n in launched_names if n in completed_names)`,
  then `all_resolved = launched_names and this_round_done >= len(launched_names)`.
  Tests must include a "completed has prior-round names, launched is this-round
  only" scenario to pin this — none of the existing `TestDecideNext` cases
  set `launched_names`, so a regression here would pass current tests.
- **Two more landmines in the decide_next fix (2026-06-12 review #2):**
  - **STOP_FLAG race**: if `node_barrier:541` exits via STOP_FLAG with
    `completed < launched`, the "gate zero_rows on all_resolved" fix lets
    the flow fall through to `route_after_decide:599 _stop_requested()`.
    Operator removing STOP_FLAG between barrier exit and the route check
    (~ms gap) silently continues. Pre-fix this exited via zero_rows. Fix:
    propagate `stop_seen: bool` from `node_barrier` into state and key
    `route_after_decide` on that, not on re-reading the flag file.
  - **Adaptive-doubling regression vs the foilsf08 crash shape (2026-06-12
    deep review)**: children are Popen'd with pid recorded
    (`closed_loop.py:448`) but the barrier never checks process liveness.
    A child that dies without terminal checkpoint / leaderboard row /
    broken.txt (the [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md)
    shape — 10/10 crashed at put_writes, parent hung with completed=0)
    stays "pending" forever. Raising the barrier cap to 24h via adaptive
    doubling turns that 4h hang into a 24h-per-round zombie. Required
    companion fix: barrier poll loop checks `os.kill(pid, 0)` on pending
    children; dead pid + no row + no broken + non-terminal checkpoint
    (after one poll tick of grace) → mark completed-failed loudly. PID
    reuse can only make a dead child look alive (falls back to timeout),
    never falsely-dead. Full design in `docs/closed-loop-barrier-fix.md`.
  - **Empty `launched_names` RuntimeError on round N+1**: `node_barrier:504-509`
    raises hard if `launched_names` is empty. If decide_next "carries the
    round forward" (returns `children={}, launched_names=[]`) and the
    picker on round N+1 happens to propose only already-evaluated configs,
    the barrier crashes. Cleaner choice: extend the barrier deadline once
    in-place (one re-poll) rather than advancing the round. Also avoids
    crediting round-N orphans' eventual rows to round N+1's
    `history_len_before` (which would mask the picker's true contribution).
- Default `barrier_timeout_min` of 240 is too tight for 12-D foilsg under
  grid contention; consider raising the default to 360 or making it
  mode-aware.
