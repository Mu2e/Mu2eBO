---
type: incident
title: closed-loop relaunch silently skips all children when stale cluster.txt files
  survive
description: 'relaunching closed-loop with same `--name-prefix` after a crash silently
  launches 0 children: `_already_running()` reads stale `state/*_cluster.txt` from
  prior run → `pending=[]` → barrier-polls forever. Fix: use new name-prefix or
  rm the stale cluster files'
status: resolved
timestamp: '2026-07-19'
updated_note: 'ChildTracker full-cut (2026-07-19, 556ac5c): the pathology now
  resolves as a first-class STALE_CLUSTER Resolution at the barrier, not via
  launch-side bookkeeping — see Resolution update below'
---

# closed-loop relaunch silently skips all children when stale cluster.txt files survive

## Summary
Relaunching a closed-loop with the same `--name-prefix` after a prior run that submitted grid jobs but never wrote a leaderboard row results in **zero children launched and the parent barrier-polling forever**. Root cause is `node_launch_children._already_running(name)` returning True for every child because `*_cluster.txt` files from the prior aborted run survived in the per-config grid state dir.

Surfaced 2026-06-08 during foilsf08 recovery: after the first foilsf08R00 SqliteSaver crash (see [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md)), the relaunch `--name-prefix foilsf08 --thread-id foilsf08b` computed picks (`got=10`), reached `launch_children`, found `pending=[]`, Popened 0 children, and entered `barrier_poll` waiting on 10 children that were never started. No error, no log line, just the barrier-poll loop running forever.

## Key facts
- `graph/closed_loop.py:389-410` — `node_launch_children` filters `pending` via `_already_running(name)`:
  ```python
  def _already_running(name: str) -> bool:
      state_dir = _child_state_dir(name)
      if any(state_dir.glob("*_cluster.txt")):
          return True
      return _child_in_leaderboard(name, mode) or _child_is_broken(name)
  ```
- The guard is intentional (prevents double-Popen on crashed-parent resume); the gotcha is it has **no recency check** — a `mubeam_cluster.txt` from 4 hours ago counts the same as one from 4 minutes ago.
- After the gate skips every child, `launch_children` returns with an empty Popen set, but `node_barrier` still gets called and blocks for `CLOSED_LOOP_BARRIER_TIMEOUT_MIN` (default 240 min) waiting on terminal state for children that were never launched.
- The `launched_names` field in state IS populated from `sorted(children.keys())` (closed_loop.py:456), so it looks non-empty to the barrier — masking the "0 actually launched" condition.
- **No log line** is emitted for the "skipped because already running" case. A future fix should emit `[closed_loop] skip {name} (cluster files present, age=Xs)` and refuse to enter the barrier when `pending` was empty AND no `[closed_loop] launched ...` lines fired this round.
- Per-config state files that trigger this: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<config_name>/state/{mubeam,concat,mustops_ce}_cluster.txt`. Removing them (or using a different `--name-prefix`) clears the gate.
- **Workaround** for an aborted run with stale clusters: relaunch with a NEW `--name-prefix` so the child config_names don't collide (e.g. `foilsf08` → `foilsf08c`).
- **Recovery** for the same prefix: `rm /exp/mu2e/data/users/oksuzian/autoresearch_grid/<prefix>R*_*/state/*_cluster.txt` before relaunch (only safe when the grid cluster has been `jobsub_rm`'d and there are no in-flight jobs that would land outputs into the dir afterwards).

## Verified defeat-mechanism (agent investigation 2026-06-09)
The existing empty-launch guard at `closed_loop.py:474-479` (`if not launched: raise RuntimeError(...)`) SHOULD have caught this, but is defeated because:

1. `node_assign_names` (`:362-386`) skip-check at `:377` only consults `_child_in_leaderboard` and `_child_is_broken` — **does NOT consult `*_cluster.txt`**. Stale clusters from the crashed prior run yielded no leaderboard rows and no `broken.txt`, so all 10 names land in `children`.
2. `node_launch_children` copies `children = dict(state["children"])` at `:394`, then the Popen for-loop (`:412`) never executes because `pending=[]` (all 10 filtered by `_already_running`). The line `children[name] = rec` at `:451` is INSIDE the for-loop, so the dict is returned unchanged with all 10 names.
3. `:456` returns `launched_names = sorted(children.keys())` — 10 names. Barrier's empty-guard checks this, sees 10, does not fire. Barrier then polls 240 min for children that were never Popened.

## Fix proposal (minimal diff at closed_loop.py:454-458)
Source `launched_names` from "actually Popened this round"; route stale-cluster skips to `completed_names` with a loud per-name error so the operator sees them. Leaderboard-present and broken cases still short-circuit silently (legit resume contract preserved).

```python
launched_this_round = [n for n, rec in children.items() if rec.get("pid")]
completed = list(state.get("completed_names", []))
for name in sorted(children):
    if children[name].get("pid"): continue
    if _child_in_leaderboard(name, mode) or _child_is_broken(name): continue
    msg = (f"launch_children[r{state['round_idx']}]: SKIP {name} — stale *_cluster.txt "
           f"in {_child_state_dir(name)} (prior aborted submit, no leaderboard row). "
           f"rm {_child_state_dir(name)}/*_cluster.txt and relaunch, or use a different --name-prefix.")
    print(f"[closed_loop] {msg}", flush=True); errors.append(msg); completed.append(name)
return {"children": children, "launched_names": sorted(launched_this_round),
        "completed_names": completed, "errors": errors}
```

The existing empty-guard at `:474-479` then fires correctly within seconds when ALL children are stale-skipped, instead of a 240-min silent hang. Unit-test pattern mirrors `TestUniqueThreadIdPerLaunch` at `tests/test_closed_loop.py:239-298`.

## Adjacent risks the same fix collapses
- All children already in leaderboard between assign_names and launch_children: today's barrier resolves on first tick but `launched_names` semantics are wrong.
- All children have `broken.txt`: same shape.
- **All Popens raise** (e.g. log_path permission denied): today, barrier hangs full 240 min; fix correctly empties `launched_names` and the guard fires.

## Cross-links
- Related: [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (scan_logs gating + cluster-file idempotency design), [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md) (the crash that triggered the recovery scenario), [closed-loop-thread-id-checkpoint-collision](/incidents/closed-loop-thread-id-checkpoint-collision.md) (separate but adjacent collision-on-resume hazard), [barrier-false-positive-round1](/incidents/barrier-false-positive-round1.md) (other barrier silent-failure mode), [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md), [mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md) (2026-07-19 full-cut moved the resolution mechanism to the barrier), [closed-loop-runner](/drivers/closed-loop-runner.md)
- Source files: `graph/child_tracker.py` (`STALE_CLUSTER` Resolution, current), `graph/closed_loop.py` (`node_barrier`, current); historical: `graph/closed_loop.py:401-410` (`_already_running`), `graph/closed_loop.py:407-410` (`pending` filter), `graph/closed_loop.py:454-457` (returns `launched_names` from `children.keys()` even when `pending` was empty)

## Resolution (2026-06-09)
Applied at `graph/closed_loop.py:454-481`: `launched_names` now sourced from `rec.get("pid")` only; stale-cluster skips route to `completed_names` with a loud per-name SKIP error; leaderboard/broken resumes stay silent (preserves the legit crash-resume contract). The existing empty-launch guard at `:474-479` now fires correctly within seconds when ALL children are stale-skipped instead of a 240-min silent hang. Regression tests at `tests/test_closed_loop.py::TestStaleClusterSkipIsLoud` (3 tests: mixed stale+fresh, all-stale-then-barrier-raises, leaderboard-resume-is-silent). All 28 closed-loop tests pass.

## Resolution mechanism superseded (2026-07-19, ChildTracker full-cut)
The 2026-06-09 fix lived at LAUNCH time (`node_launch_children` did its own
stale-cluster bookkeeping, wrote `completed_names`/`errors`, and the barrier's
empty-`launched_names` guard was the trigger for the loud failure). The
[mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md)
full-cut (commit 556ac5c) moved this to the BARRIER: `ChildTracker` gained a
first-class `STALE_CLUSTER` `Resolution` (a pid-`None` child whose state dir
has a `*_cluster.txt` from a prior aborted run), and `node_launch_children`
now only skips the Popen (double-submit guard) — it no longer writes
`completed_names`/`errors` itself. `node_barrier`'s hard guard also changed:
`if not launched: raise RuntimeError(...)` (empty launched_names = always a
bug) became `if not children: raise RuntimeError(...)` (empty children DICT
is the real corruption signal; an all-stale round legitimately has empty
`launched_names` with children present, and now resolves cleanly through the
tracker's tick loop instead of raising). **Operator-facing behavior is
unchanged**: same `rm <grid>/<name>/state/*_cluster.txt`-and-relaunch (or
fresh `--name-prefix`) recipe, same loud per-name message, now printed from
`node_barrier` instead of `node_launch_children`. A companion fix the same
day (1d37217) closed an adjacent gap the full-cut review found: a child
whose `Popen` itself raises (`launch_failed=True`, pid stays `None`) now
resolves `DEAD_UNRESOLVED` on the first tick (no two-tick dead-pid grace),
instead of falling through to the 24h `barrier_max_min` backstop. Status
stays `resolved` — the pathology described above cannot recur; only its
resolution site moved. Regression tests: `tests/test_child_tracker.py`
(STALE_CLUSTER cases, `test_launch_failed_resolves_immediately_no_grace`),
`tests/test_closed_loop.py` (all-stale-round-resolves-clean,
`test_popen_failure_resolves_at_barrier`).

## Open questions / TODO
- Consider: time-based cluster-file freshness check (e.g. cluster files >4h old → treat as stale, don't gate). Deferred — current loud-fail + operator-visible message is sufficient.
