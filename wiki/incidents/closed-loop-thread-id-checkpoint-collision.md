---
type: incident
title: Closed-loop thread-ID checkpoint collision
description: SqliteSaver thread_id reuse silently swapped foilsX05R01_07's config_name
  to graph001 (2026-05-30); leaderboard row never landed under intended name
status: resolved
timestamp: '2026-05-30'
---

# Closed-loop thread-ID checkpoint collision

## Summary
SqliteSaver in `graph/closed_loop.py` keys checkpoints by `thread_id`. A child
launched with a fresh `<prefix>R##_##` name CAN resume an unrelated prior
thread's state if the SqliteSaver DB still has a row for that thread_id —
silently swapping the child's identity. Observed once in foilsX05R01_07
(2026-05-30): final log shows `config_name: "graph001"` and `objective: 2.022`
even though parent log records `launched foilsX05R01_07`. The "graph001" row
is the one persisted to the leaderboard, not foilsX05R01_07.

## Key facts
- **Symptom**: child log's `[run] done. final keys: [...]` block includes
  `config_name` set to an OLD prefix (e.g. `graph001`), and the
  leaderboard never gains a row for the *intended* child name.
- **Mechanism**: child graph reads from `checkpoints.sqlite` at
  startup; if a checkpoint exists for that thread_id (collision via reuse
  or via parent passing the wrong id), the resumed state overrides the
  new `config_name`/`x_point`.
- **Trigger conditions** (unconfirmed, hypothesis):
  - thread_id derived from name_prefix slice → collision if prefixes share
    a tail.
  - SqliteSaver DB not wiped between unrelated parent runs sharing the
    same `--thread-id` root.
- **Detection**: grep child logs for `"config_name":` mismatch vs filename:
  `for f in graph_data/closed_loop_logs/<prefix>R*.log; do
    grep -E '"config_name": "(?!'$(basename $f .log)')"' "$f"; done`.
- **Cost**: silent yield loss (counted as "ran" by parent, drops out of
  leaderboard cohort). Worse: if the colliding old config had a valid
  objective, it can DUPLICATE-write to the leaderboard under the old
  name (didn't happen in X05R01_07 — graph001 row was already present).
- **Fix landed 2026-05-30 (commit 27cd08a, local)**: `graph/nodes.py`
  `node_propose` now branches on `caller_pinned = bool(state.get("config_name"))`.
  Pinned callers (closed_loop children) call `bo.MODES[mode].remove_pending(name)`
  on the `ValueError` re-raise and retry under the SAME name. Auto-named
  CLI-smoke path keeps the legacy `next_config_name` fork so a concurrent
  same-name pick is still detected. Test coverage:
  `tests/test_audit_fixes.py::TestProposeReentryPreservesCallerName` (5 cases:
  pinned+stale, pinned+clean, pinned+x_point forwarded, auto-named collision
  fork, attempts.propose counter). Full suite 56/56 OK.
- **Cross-ref**: 1 of 5 missing-leaderboard children in foilsX05 (25/30
  yield); the other 4 (R00_04, R01_05, R01_06, R02_00) are different
  failure modes (early-exit before harvest, or null-metric harvest).
- **Runtime guard validated 2026-05-30**: foilsX06 (launched 10:21 — pre-
  PR1-merge; old `--thread-id <prefix>` path) hit the swap on R02_08
  (`got='graph003'`) and R02_09 (`got='graph004'`). `graph/run.py` config-
  name guard raised `RuntimeError [run] FATAL config_name swapped` for
  both, loud-crashing the child instead of silently misattributing
  leaderboard rows.
- **Root cause is NOT thread-id collision** (2026-05-30 forensic): the
  unique-thread-id fix landed before foilsX06 launched (log shows
  `[run] thread_id=foilsX06R02_08_adb6ab5b` — uuid suffix in place).
  Actual mechanism is in `graph/nodes.py:67-73` `node_propose` except-
  branch: when `route_after_preflight` re-loops to propose after
  `preflight=ambiguous` (rc=3), `pio.propose_one(name, ...)` raises
  `ValueError "config name foilsX06R02_08 already in leaderboard or
  pending"` because the pending row from attempt 1 still exists. The
  except branch silently calls `pio.next_config_name(mode)` → returns
  `graph003`/`graph004` → state-merge swaps `config_name` → next
  `graph.stream` yield trips the swap guard. Fix: in the
  except branch, if caller pinned `config_name` (closed-loop case),
  call `bo.MODES[mode].remove_pending(name)` and retry under same
  name; only fork to next_config_name on the legacy auto-name path
  where there was no caller-supplied name. The unique-thread-id PR
  is still load-bearing for its OWN failure mode (cross-session
  SqliteSaver checkpoint reuse) — both bugs converge on the same
  swap-guard symptom.

## Cross-links
- Related: [barrier-false-positive-round1](/incidents/barrier-false-positive-round1.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md),
  [closed-loop-runner](/drivers/closed-loop-runner.md), [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md), [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md)
- Source files: `graph/closed_loop.py`, `graph/state.py`
- Detection log: `graph_data/closed_loop_logs/foilsX05R01_07.log`

## Resolution (PR for #7, committed locally 2026-05-30; not yet merged)
Per-launch unique thread_id, decoupled from `config_name`. Three load-bearing
constraints to know before touching this code:
- `thread_id = f"{config_name}_{uuid.uuid4().hex[:8]}"` is generated in
  `node_launch_children` and persisted onto the child record under
  `rec["thread_id"]`. `config_name` keeps the user-visible identity / leaderboard
  key — do NOT collapse them again.
- `ChildRecord` TypedDict carries a `thread_id: str` field; the barrier's
  `_child_terminal_via_checkpoint(name, child_graph, thread_id=...)` MUST be
  passed the recorded thread_id, otherwise checkpoint-fallback lookup returns
  no state and the barrier deadlocks until timeout. Legacy `thread_id=None`
  falls back to `name` (for in-flight resume after upgrade).
- Resume path: if `rec.get("thread_id")` is set on re-entry, REUSE it. A new
  uuid would orphan the still-running child's checkpoint AND the barrier's
  lookup. Tested by `TestUniqueThreadIdPerLaunch.test_thread_id_reused_on_resume`.
- `graph/run.py` adds a config_name swap guard: if `state["config_name"]` mid-
  stream differs from `--config-name`, raise `RuntimeError` immediately. Loud
  crash beats silent leaderboard misattribution.
