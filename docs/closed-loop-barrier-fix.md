# closed-loop barrier-timeout false-positive — fix design

**Status:** implemented 2026-06-12, including the liveness-wait
simplification (see Addendum) — sections 1/1b below describe the
adaptive-doubling design as originally approved; the Addendum supersedes
the ladder part of section 1
**Date:** 2026-06-12
**File:** `graph/closed_loop.py` (lines 491-601 + RoundState TypedDict 130-149)
**Incident:** `wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md`

## Issue

`node_barrier` blocks until every child resolves OR `barrier_timeout_min`
elapses; on timeout it returns silently. `node_decide_next` then reads
`new_rows = leaderboard_len(after) - leaderboard_len(before)`. If
`new_rows <= 0`, it sets `zero_rows = True` and `route_after_decide`
exits the campaign.

The failure mode: barrier times out while children are still running
normally on the grid. Leaderboard has 0 new rows because the slow
successes haven't finished yet — not because they failed. Parent exits
`done`, orphan children keep running unsupervised, their rows land
hours later with no R1 picker to consume them.

**Two occurrences in 48h:** foilsg03 (240-min cap, 8 orphans) and
foilsg05 (360-min cap raised per foilsg03 recommendation, still
insufficient — 3 orphans under 1186-idle queue starvation). Plus the
foilsX04 historical analog (2026-05-29). foilsg04 is NOT an instance:
its all-10 wipeout was the RCDS disk-quota failure — every child
genuinely failed fast, so the zero-rows exit there was correct
behavior that must be preserved.

## Root cause

`decide_next`'s "0 new rows → all failed → exit" rule cannot distinguish:
- **all-failed**: every child resolved (preflight-fail / stage-fail /
  broken.txt), no rows landed → legitimate bail
- **barrier-timeout**: some children still pending, no rows yet →
  transient, must NOT bail

## Solution

Four-part change. All edits to `graph/closed_loop.py` unless noted.

### 1. `node_barrier` (lines 491-561) — adaptive doubling re-poll + explicit exit reasons

Replace single-shot deadline + silent break with:

- `barrier_max_min` (new knob, default 1440 = 24h) is a **cumulative
  elapsed-time cap** for the whole barrier, measured from barrier entry
  (`start = time.time()`). Not a per-window cap — the knob name must
  match what it bounds.
- Initial window: `window_min = min(barrier_timeout_min, barrier_max_min)`;
  `deadline = start + window_min * 60` (clamped so a user-supplied
  `--barrier-timeout-min` larger than the cap can't overshoot it)
- On timeout when `not all_resolved`:
  - If `elapsed < barrier_max_min * 60`: double `window_min`, set
    `deadline = min(time.time() + window_min * 60,
    start + barrier_max_min * 60)` (final window clamped to the cap),
    log `barrier[rN]: timeout at {elapsed_min}min — extending window to
    {window_min}min (cumulative cap {barrier_max_min}min; pending: ...)`,
    continue the loop
  - Else: break with `timeout_seen=True`
- Track `stop_seen: bool` for the STOP_FLAG break (line 541)
- Return: `{"completed_names": sorted(completed), "errors": errors,
  "stop_seen": stop_seen, "timeout_seen": timeout_seen}`

Wait ladder from default 240min: timeout at 240 elapsed → +480 window
(720 cumulative) → +960 window clamped to 1440 cumulative → final
timeout at 24h. Two full extensions + one clamped. Single re-poll
covers a concat hiccup (review #1's first suggestion); adaptive
doubling covers the foilsg05 5h+ queue-starvation shape (review #3's
correction).

### 1b. `node_barrier` — pid-liveness check (companion fix, REQUIRED)

Without this, adaptive doubling **regresses** the foilsf08 crash shape
(`wiki/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md`):
children that die without writing a terminal checkpoint, leaderboard
row, or broken.txt stay "pending" forever. Today that burns one 240-min
timeout; under adaptive doubling it burns 24h per round, then carries
forward and relaunches children that likely crash the same way — up to
`max_rounds × 24h` of zombie campaign.

In the barrier poll loop, for each still-pending child whose record has
a pid (`rec.get("pid")`, recorded at `launch_children:448`):

- Check `os.kill(pid, 0)`. If it raises `ProcessLookupError`, the child
  process is dead.
- Dead pid + no leaderboard row + no broken.txt + non-terminal
  checkpoint → wait **one extra poll tick** (grace against racing the
  final leaderboard append), re-check, then mark completed-failed with
  a loud error: `barrier[{name}]: child process {pid} died without
  resolution (no row / broken.txt / terminal checkpoint)`.
- PID-reuse hazard is one-directional: a reused pid makes a dead child
  look *alive*, which just falls back to timeout behavior. A live child
  can never look dead. Safe.
- Children with `pid=None` (resume path, stale-cluster skips) are not
  checked — they resolve via the existing leaderboard/broken/terminal
  paths or the timeout.

With this in place, a foilsf08-shape round resolves in ~2 poll ticks:
all children marked completed, 0 rows, `all_resolved=True` →
legitimate zero_rows exit. Strictly better than both the current
behavior (4h hang) and adaptive doubling alone (24h hang).

### 2. `node_decide_next` (lines 564-591) — corrected zero_rows gate

Replace:
```python
zero_rows = new_rows <= 0
```
with:
```python
launched = state.get("launched_names", []) or []
completed = set(state.get("completed_names", []))
this_round_done = sum(1 for n in launched if n in completed)
all_resolved = bool(launched) and this_round_done >= len(launched)
zero_rows = (new_rows <= 0) and all_resolved
```

**Why `this_round_done` instead of raw `len(completed)`:**
`completed_names` is **cumulative across rounds** —
`node_barrier:510` seeds `completed = set(state.get("completed_names", []))`
from prior state, and `:561` returns the union. Naive
`len(completed) >= len(launched)` is trivially true at round N>0 and the
guard collapses to current behavior (review #1).

Three log branches:
- zero_rows TRUE: `decide_next[rN]: 0 new rows + all {N} children
  resolved — all failed; exiting early`
- new_rows≤0 but pending: `decide_next[rN]: 0 new rows but {K}/{N}
  children still pending after barrier — carrying round forward (NOT
  exiting)`
- happy: `decide_next[rN]: +{N} new rows (before=A after=B)`

Return now includes:
```python
"stop_seen": state.get("stop_seen", False),
"timeout_seen": state.get("timeout_seen", False),
```

### 3. `route_after_decide` (lines 594-601) — belt-and-suspenders STOP_FLAG

Replace:
```python
if _stop_requested():
    return END
```
with:
```python
if state.get("stop_seen") or _stop_requested():
    return END
```

Closes the ~ms-gap race where the operator removes STOP_FLAG between
`node_barrier`'s flag check and `route_after_decide`'s flag check
(review #2).

### 4. `RoundState` TypedDict (lines 130-149) — declare new keys

Add:
```python
stop_seen: bool
timeout_seen: bool
```

Add to the `--barrier-max-min` argparse (line ~717) with default 1440.

### 5. Telemetry (line ~742) — emit timeout_seen

Currently the round-tick event includes `"zero_rows": ev.get("zero_rows")`.
Add both `"timeout_seen": ev.get("timeout_seen")` and
`"stop_seen": ev.get("stop_seen")` so post-mortem log analysis can
distinguish all three exit modes (zero-rows all-fail, cap-exhausted
timeout, operator stop) from stdout alone.

## Test plan

`tests/test_closed_loop.py` — six new cases, five in `TestDecideNext`
plus one in `TestBarrier`:

1. `test_barrier_timeout_pending_does_not_set_zero_rows`
   launched=["a","b","c"], completed_names=["a"], new_rows=0
   → `zero_rows=False` (carry-forward path)

2. `test_all_completed_zero_rows_still_exits`
   launched=["a","b"], completed_names=["a","b"], new_rows=0
   → `zero_rows=True` (foilsX04 all-fail preserved)

3. `test_completed_cumulative_across_rounds_doesnt_mask_pending`
   launched=["c"], completed_names=["prev_a","prev_b"], new_rows=0
   → `zero_rows=False` (pins the cumulative-names bug from review #1)

4. `test_completed_includes_this_round_failure_exits`
   launched=["c"], completed_names=["prev_a","prev_b","c"], new_rows=0
   → `zero_rows=True` (c failed broken.txt path, no leaderboard row;
   pins review #3's gap in case 3)

5. `test_stop_seen_exits_even_with_pending_children`
   launched=["a","b"], completed=["a"], stop_seen=True
   → asserts BOTH: returned state has `stop_seen=True` AND
   `route_after_decide` returns END (not "renew_token")

6. `test_barrier_raises_on_empty_launched` (in TestBarrier)
   launched_names=[], children={} → `RuntimeError` (preserves the
   :504 guard against state-corruption bugs; covers the
   "picker proposes only already-evaluated configs" edge case)

7. `test_barrier_dead_pid_marks_completed_failed` (in TestBarrier)
   pending child with pid of a dead process, no leaderboard row, no
   broken.txt, non-terminal checkpoint → after one grace tick, child
   appears in `completed_names` and an error line is recorded
   (pins the pid-liveness companion fix; foilsf08 shape)

## Post-cap behavior and known limitation

When the cumulative cap (`barrier_max_min`) is exhausted with children
still pending, `zero_rows` stays False (pending ≠ resolved), so the
campaign **continues to round N+1** with the round-N stragglers
orphaned. This is intentional: the alternative (exit at cap) reproduces
the original incident at a longer fuse.

**Known limitation:** round-level attribution of orphan rows is
distorted, in one of two directions depending on landing time.
`history_len_before` is snapshotted in `predict_picks`
(`closed_loop.py:360`) at round start. An orphan row landing *before*
round N+1's predict_picks is absorbed into N+1's `before` (the round-N
picker gets no credit); one landing *during* N+1's barrier inflates
N+1's `new_rows` (mis-credited to the N+1 picker). Either way the rows
still enter the GP fit for subsequent rounds, which is what matters for
optimization; only the round-level bookkeeping is off. Accepted for
now — fixing it would require the parent to track orphans past
`decide_next`, which is a bigger change than this incident justifies.

## What stays the same

- `route_after_decide` END branches on max_rounds, on (stop_seen OR
  STOP_FLAG), and on zero_rows.
- `node_barrier:504` empty-launched_names RuntimeError preserved
  unchanged. Carry-forward is safe: round N+1 uses fresh `R{N+1}_*`
  names that can't already be in the leaderboard, so
  `predict_picks → assign_names → launch_children` always repopulates
  `launched_names`. (Out of scope, pre-existing: *resuming* a prefix
  whose round names all already resolved makes `assign_names:379-381`
  skip every pick → `launched_names=[]` → barrier RuntimeError. That
  crash predates this fix and is loud, not silent — left alone.)
- Leaderboard / SqliteSaver / WAL semantics unchanged.
- Default `barrier_timeout_min=240` unchanged (just the new
  `barrier_max_min=1440` knob).

## Review history

- **Review #1** caught the load-bearing bug: cumulative `completed_names`
  makes naive `len(completed) >= len(launched)` trivially true at round
  N>0. Without this catch the patch would have been a no-op.
- **Review #2** caught the STOP_FLAG race (mid-ms removal) and the
  empty-launched_names crash on carry-forward (if N+1 picker proposes
  only already-evaluated configs).
- **Review #3** upgraded "re-poll once" to "adaptive doubling cap 24h"
  (foilsg05's 5h+ queue starvation would have escaped a 2× extension),
  added belt-and-suspenders STOP_FLAG check, flagged the test gap
  closed by case 4.
- **Deep review (2026-06-12, inline code walk)** caught: (a) adaptive
  doubling alone regresses the foilsf08 crash shape from a 4h hang to
  24h-per-round zombie → added the REQUIRED pid-liveness companion fix
  (change 1b + test 7); (b) initial deadline needed the same cap clamp;
  (c) the orphan-attribution limitation runs in both directions
  depending on row-landing time; (d) telemetry should emit `stop_seen`
  too; (e) confirmed the gate correctly keys on `launched_names` (which
  only counts actually-fired Popens, `closed_loop.py:461`), not `q`.

## Open questions

- Should `barrier_max_min` be exposed via env var like `CLOSED_LOOP_*`
  constants near the top of the file, or left argparse-only?
- The four log branches in `decide_next` are verbose. Worth condensing
  to one structured `print` with all signals?

## Addendum 2026-06-12: adaptive ladder replaced by liveness-wait

Shortly after the adaptive-doubling version landed, the operator asked
"do we really need that many timeouts?" — and the answer was no. The
dead-pid check changed the problem underneath the ladder: once process
liveness is observable, the wall-clock window is a redundant (and
incident-prone) proxy for "will this child resolve?". An alive
`graph.run` child always progresses toward resolution because every
grid stage inside it is bounded by pipeline.py's poll `cap_hours`; a
dead child resolves via the pid check in two poll ticks.

**Landed simplification:**
- The barrier has NO per-round pacing timeout. It waits until every
  child resolves (row / broken.txt / terminal checkpoint / dead pid)
  or STOP_FLAG appears.
- `--barrier-max-min` (default 1440) remains as the single loud
  BACKSTOP for the one remaining pathology — a child that is alive but
  hung. Tripping it is rare and always worth investigating; the log
  message says so.
- `--barrier-timeout-min` is deprecated and ignored (flag still parses
  so existing launch recipes don't break); `barrier_timeout_min`
  removed from RoundState and the init dict (old checkpoints carrying
  the key are unaffected — TypedDict is total=False).
- The doubling ladder, `window_min` state, and clamp arithmetic are
  gone. The decide_next gate, stop_seen propagation, dead-pid grace,
  and all tests are unchanged (the two barrier tests now drive the
  backstop directly via `barrier_max_min`).

Net effect on the incidents: foilsg03/05 shapes now simply wait the
extra hours and collect every child — zero orphans, no carry-forward,
no attribution distortion (that limitation now only applies on a rare
backstop trip).
