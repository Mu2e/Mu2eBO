---
type: incident
title: Barrier false-positive on round >= 1 (closed-loop)
description: closed-loop FT05 round-1 children mis-resolved by `saver.get_tuple.next`;
  silent premature convergence; use `--max-rounds 1` until fixed
status: resolved
timestamp: '2026-07-17'
updated_note: 'CORRECTED foilsZ06 attribution: NOT a LangGraph replay bug — root
  cause was a stale `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP` flag file left from a prior interrupted
  bash chain; barrier''s STOP_FLAG exit branch did not print, so the trigger was
  invisible. Forensic SqliteSaver dump confirmed single linear checkpoint chain,
  no replay. Latent vacuous-`all([])==True` trap on empty `children` dict is fixed
  by adding `launched_names` field + hard guard in `node_barrier`. STOP_FLAG and
  timeout branches now also print before exit.'
---

# Barrier false-positive on round >= 1 (closed-loop)

## Summary
First `--max-rounds 2` real closed-loop run (`helicalFT05`, q=8) silently
declared convergence after only round 0 contributed real leaderboard
rows. Round-1 children were marked "resolved" by the barrier within
minutes of launch, refit hashed the unchanged leaderboard, hash matched
round 0 → converged → parent exited cleanly. The 8 round-1 children
continued running on the grid for >30 min after parent exit, eventually
writing rows that nobody refits on. Looks like a clean multi-round run
in logs; isn't.

## Key facts
- **Smoking gun in `closed_helicalFT05_r0.log`:**
  ```
  [closed_loop] launched helicalFT05R01_07 pid=1330575 ...
  [closed_loop] barrier: all 8 children resolved      ← within minutes
  [closed_loop] {"round_idx": 1, "completed": 9, ...}
  trained on 66 points (10 priors + 56 helical = 0 legacy + 56 v2)
  [closed_loop] refit: pareto_hash=9169827253d5fd2f
      (last 2: ['9169827253d5fd2f','9169827253d5fd2f']) converged=True
  [closed_loop] done.
  ```
  The two `9169827253d5fd2f` hashes are identical because round 1
  contributed ZERO new leaderboard rows when refit ran (round 0 only
  added 7 of 8 by then; round-1 children hadn't even hit mubeam harvest).
- **Children state at parent exit:** all 8 `helicalFT05R01_*` had
  `[run] {"config_name": ..., "preflight": "pass"|"pending",
  "objective": null}` and `ps` showed live python processes with 2–13 min
  ELAPSED — clearly mid-pipeline, not terminal.
- **Suspected mechanism:** `node_barrier` resolves a child if ANY of
  (a) leaderboard row, (b) `broken.txt`, (c)
  `saver.get_tuple(child_thread_id).next` is empty (per
  [closed-loop-runner](/drivers/closed-loop-runner.md)). For freshly-spawned round-1 children whose
  SqliteSaver checkpoint hasn't yet been written (or is read while a
  preflight-only checkpoint exists), `.next` likely evaluates to empty
  and the child is mis-classified as terminal.
- **`convergence_k=2` default makes the bug invisible:** two identical
  hashes in a row trigger convergence, so the spurious round-1 hash
  collapsing onto round-0's looks like the BO genuinely settled. With
  `convergence_k>=3` the parent would have looped one more round and
  exposed the issue. Don't trust `converged=True` from any 2-round run.
- **Workaround**: use `--max-rounds 1` and re-launch manually; or set
  `--convergence-k 99` and bound rounds. Skill
  `/closed-loop-launch` defaults to `--rounds 1` to avoid this.

## Cross-links
- Source files: `graph/closed_loop.py` (node_barrier + refit_and_check),
  `graph/config.py` (CLOSED_LOOP_BARRIER_* constants)
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md), [closed-loop-thread-id-checkpoint-collision](/incidents/closed-loop-thread-id-checkpoint-collision.md), [foilsx04-all-preflight-ambiguous](/incidents/foilsx04-all-preflight-ambiguous.md), [closed-loop-final-round-orphan-children](/incidents/closed-loop-final-round-orphan-children.md), [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)
- Log: `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/closed_loop_logs/closed_helicalFT05_r0.log`
- Affected children: `helicalFT05R01_00` through `helicalFT05R01_07`

## Resolution (2026-05-24)
Fixed in `graph/closed_loop.py:_child_terminal_via_checkpoint`. Root
cause: LangGraph's SqliteSaver returns
`StateSnapshot(next=(), values={}, metadata={'step': -1})` for a
thread_id that has never written a checkpoint. This is INDISTINGUISHABLE
from a genuine terminal state by `snap.next` alone, so freshly-spawned
round-N children (whose subprocess hadn't yet flushed any state) were
mis-classified as terminal on the very first barrier tick.

**Fix:** require ALL THREE of (a) `snap.next` empty, (b) `snap.values`
non-empty, AND (c) `snap.metadata.step >= 1`. Verified by smoke test
against the FT05 checkpoint DB: ghost thread → `terminal=False`; R00_*
and R01_* (now legitimately complete) → `terminal=True`; preflight-fail
path preserved because even a 2-super-step run satisfies `step >= 1`.

**Why `step >= 1` and not `>= 2`:** a preflight-fail child runs
`propose → render_preflight → END` via `route_after_preflight`. That's
two super-steps; LangGraph's step counter is 0-indexed, so the END
checkpoint records `step=1`. The threshold is the floor for "at least
one super-step executed."

**Live validation (2026-05-24, `helicalFT06`, q=8, max-rounds=2):**
round 0 closed with 8/8 real leaderboard rows and a non-degenerate
pareto_hash (`39d6c72a54ce5f80`); round 1 then launched fresh children
without any spurious "all resolved" barrier tick. End-to-end confirms
the smoke-test fix holds against an actual multi-round closed loop.

## Second false-positive (2026-05-24, same FT06 run) — distinct bug, fixed

The snapshot-step fix above was correct but only one of TWO compounding
bugs. FT06 round 1 still mis-resolved immediately after launching all
8 children, even though every R01_* child was mid-pipeline.

**Root cause:** `node_barrier` exit condition was
`if len(completed) >= len(children)`. `completed` is initialized from
`state.get("completed_names", [])`, which is PRESERVED across rounds
(intentional: a crashed-and-resumed parent should not re-check
round-0 children). Entering round 1, `completed` already contained
the 8 round-0 names. `state["children"]` is the round-1 list (8
names). `len(completed) >= len(children)` evaluated `8 >= 8 = True`
on the FIRST barrier tick → break before checking any R01_* child.

**Fix (`graph/closed_loop.py:390`):** replace count comparison with
`if all(n in completed for n in children)`. Count-based exit
conflates cumulative completion across rounds with current-round
completion.

**Observable smoking gun in the parent log:** `completed` went from
8 → 9 across the (instant) barrier — one round-1 child got added
(probably via a leaderboard or broken-marker race during the tick),
but the loop exited on count before checking the remaining 7. A
clean barrier on q=8 would show `completed: 16` at minimum (round-0
+ round-1 union); FT06 showed `completed: 9` at refit time.

**Why this didn't surface in FT05:** FT05 had the snapshot-step bug
masking it — the snapshot path resolved children before the count
check mattered. Once snapshot was patched, the count bug surfaced
nakedly on the next multi-round run.

## 2026-06-05 foilsZ06 incident — stale STOP_FLAG (not a barrier bug)

`foilsZ06` (qLogNEHVI, q=10×5) launched 2026-06-05 17:43 with the spack-cache
fix in place. R00: ALL 10 children PASS preflight (spack fix verified, see
[foilsx04-all-preflight-ambiguous](/incidents/foilsx04-all-preflight-ambiguous.md)). Parent exited at 17:57 via `zero_rows=True`
with `completed=0` — never refit, never launched R01.

**Actual root cause:** `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP` (0 bytes, mtime 14:55)
existed at launch time. It was left over from an interrupted `touch
/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP; pkill ...; sleep 2; rm -f /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP`
chain run from inside a Claude bash subshell several turns earlier; the user
interrupted before the `rm` ran. `node_barrier`'s STOP_FLAG branch
(`closed_loop.py:500-502`) caught the flag on the first poll and broke out
of the loop — but only appended to `errors`; it did NOT print anything to
the parent log. Operator saw no exit reason. Then `decide_next` ran
naturally, observed 0 new leaderboard rows (children hadn't completed yet),
flipped `zero_rows=True`, and routed to END.

**Initial mis-diagnosis (corrected here):** the duplicated `round_idx=0`
state lines in the parent log were narrated as "LangGraph replayed the round
from a stale checkpoint." That was wrong. They are normal
`stream_mode="values"` emissions — LangGraph emits state after every node,
so each super-step produces a state line. Forensic dump of
`graph_data/checkpoints.sqlite` for thread `closed-535222e1` showed 8
checkpoints in a single linear chain (no fork, no replay).

**Latent bug exposed:** even though foilsZ06's exit was caused by the stale
flag, the `node_barrier` loop has a vacuous-`all([])==True` trap: if
`state["children"]` is ever the empty dict when barrier polls,
`all(n in completed for n in [])` returns True instantly and breaks out
silently (the `print(f"barrier: all {len(children)} children resolved")`
would print `all 0 children resolved`, which is a meaningful but false
"success"). The fix below removes both the silent-STOP path and the
empty-children trap.

**Orphans:** all 10 R00 children continued as detached `graph.run` processes
after parent exit (verified via `pgrep`); they eventually landed leaderboard
rows that nobody refits on. Same orphan pattern as FT05.

**Differential vs prior variants:**
- FT05 (v1): snapshot-step bug — fixed by `step >= 1` gate.
- FT06 (v2): count-based exit — fixed by `all(n in completed for n in children)`.
- foilsX04 (v3): `_child_terminal_via_checkpoint` returning True before harvest.
- foilsZ06 (v4): **operator-induced** (stale STOP_FLAG); not a barrier bug.

## Resolution (2026-06-05) — silent-exit and empty-children hardening

`graph/closed_loop.py`:
- New `RoundState` field `launched_names: List[str]` (line ~109) written by
  `node_launch_children` (line ~457). Lets `node_barrier` validate it received
  the launch set from upstream, independent of the `children` dict (which
  gets cleared by `decide_next` between rounds).
- `node_barrier` (line ~460) hard-raises `RuntimeError` if `launched_names`
  is empty on entry — that situation is always a state-pipeline bug, not a
  legitimate "no children to wait on."
- STOP_FLAG branch (line ~500) and timeout branch (line ~503) now both
  `print(...)` before breaking out, so any future operator-induced exit
  shows in the parent log.
- `node_decide_next` (line ~540) clears `launched_names` alongside `children`
  so round N+1 starts clean.
- Regression test: `tests/test_closed_loop.py::TestBarrierRefusesEmptyChildren`.

**Operational note:** check for and delete `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP`
before every closed-loop launch. A 0-byte stale file silently aborts the run
even with the silent-exit fix above (the message will now print, but the
round still exits before doing useful work).

## 2026-05-29 foilsX04 regression (suspected third variant)

`foilsX04` (q=10, max-rounds=10) launched 2026-05-29 ~07:15 UTC. Parent log
shows `barrier: all 10 children resolved` for round 1 followed by refit
`converged=True` at completed=20, but the leaderboard `leaderboard_bo_foils_v1.tsv`
has **ZERO foilsX04 rows** (filtered `grep -c foilsX04` = 0). No
`<grid>/foilsX04R*/state/broken.txt` either. Both prior fixes
(snapshot-step gate + `all(n in completed for n in children)`) were already
in place, so a child can only get into `completed` via:
(a) a leaderboard row appearing — refuted (no X04 rows ever landed), or
(b) `<grid>/<name>/state/broken.txt` — refuted (none exist), or
(c) `_child_terminal_via_checkpoint` returning True.

That leaves (c) as the suspected culprit: foils-mode children's StateSnapshot
may legitimately reach `step >= 1` with non-empty values *before* the
leaderboard write, so the third-AND-only gate (`metadata.step >= 1`) is not
strict enough for foils-mode pacing. Both fixes for helical assumed `step >= 1`
+ non-empty values implied "harvest committed" but that may be helical-pacing-
specific. Next step: dump a stuck X04R01 child's StateSnapshot via
`saver.get_tuple()` to see at what step the snapshot first satisfies the gate.
