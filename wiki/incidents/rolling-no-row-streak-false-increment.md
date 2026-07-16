# Rolling no_row_streak falsely increments on SUCCESSFUL children

**Type:** incident
**Status:** resolved (name-based accounting landed 2026-07-16; regression test `test_decide_streak_immune_to_baseline_absorbed_row`, suite 162 green)
**Updated:** 2026-07-16

## Summary
In `--rolling` mode the `no_row_streak` abort guard counts a **wave-level row
delta** (`after - before`) but detects **child resolutions at the barrier**,
and the two are read at different instants. A child that resolves during a
wave transition has its leaderboard row absorbed into the NEXT wave's baseline
before its resolution is accounted — so `decide_next` sees `+0 rows` for a
child that actually succeeded, and increments the abort streak. Observed live
on foilsflash18 (streak 1/5 while both resolved children had valid rows).
Worst case: a synchronized burst of ≥q resolutions inside one transition
window could abort a perfectly healthy campaign.

## Key facts
- **Mechanism (foilsflash18, 2026-07-15, exact trace):** leaderboard 294 rows
  pre-campaign. `decide_next[w0]`: before=294, after=295 → **+1** ✓ (R00_00),
  streak=0 — and it does NOT return `history_len_before`. The next wave's
  node refreshes the baseline (`closed_loop.py:417`,
  `"history_len_before": _leaderboard_len(...)`) — by then R00_01's row had
  ALSO landed → baseline=**296**. `barrier[w1]` then detects R00_01's
  (already-completed) resolution → `decide_next[w1]`: before=296, after=296
  → **+0 rows**, `no_row_streak=1/5` — even though R00_01's row (sob 2.17) is
  in the leaderboard. Child exits: R00_00 23:15:23, R00_01 23:20:17 — 5 min
  apart, i.e. inside one wave transition.
- **Why rolling makes it structural, not rare:** in BARRIER mode all q
  children resolve, then one decide counts — resolutions and baseline refresh
  are synchronized. Under rolling, picks/resolutions interleave continuously,
  so any two children resolving within a wave transition trigger it. ff16/ff17
  already showed multi-resolution waves ("2 resolved"), so bursts are normal.
- **Danger scenario:** if N≥q children resolve+append inside one transition
  window, the baseline swallows all N rows, the barrier reports
  `resolved_wave=N`, and `streak += N` → `abort = streak >= q` fires on a
  HEALTHY campaign (all rows landed). Not yet observed.
- **Root cause = count-based accounting.** `decide_next` (closed_loop.py:686-701)
  compares LENGTHS; correctness requires the baseline and the resolution set to
  be read atomically, which they are not.
- **Correct fix = name-based accounting** (robust to every race): a resolved
  child produced a row iff its config name is in the leaderboard. The helper
  already exists — `_leaderboard_names(mode)` (closed_loop.py:217, returns
  `{p.cfg for p in _history(mode)}`) and is already used elsewhere in the
  barrier path. Increment the streak only for newly-resolved children whose
  name is ABSENT from that set. Makes `history_len_before` irrelevant to the
  rolling guard.
- **Mid-campaign safety:** `closed_loop.py` is the PARENT's own module, loaded
  once at launch — editing it does NOT affect a running parent (unlike
  `pipeline.py`/`botorch_predict.py`, which children/waves re-execute; see the
  freeze note in [[closed-loop-runner]]). A crash+relaunch would pick up the
  new code, which is desirable.

## Cross-links
- Related: [[closed-loop-runner]], [[foilsx04-all-preflight-ambiguous]] (the
  original zero-rows shape this guard generalizes),
  [[closed-loop-barrier-timeout-zero-rows-falsepos]] (sibling false-positive in
  the barrier-mode guard)
- Source files: `graph/closed_loop.py:686-701` (delta + streak),
  `graph/closed_loop.py:417` (baseline refresh), `graph/closed_loop.py:217`
  (`_leaderboard_names`, the fix's building block)

## Fix (landed 2026-07-16)
- `decide_next` rolling branch now tracks `prev_completed_names` (list) instead
  of `prev_completed_count` (int): `newly_resolved = completed - prev_names`,
  `streak = 0 if any(n in _leaderboard_names(mode) for n in newly_resolved)
  else prev_streak + len(rowless)`. Four coordinated sites (state annotation
  :143, streak logic, return dict, init). Regression test
  `test_decide_streak_immune_to_baseline_absorbed_row` reproduces the ff18 w1
  race (row present, baseline absorbed it, new_rows==0) and asserts streak==0
  — fails on the old count-based code (would read 1).

## Open questions / TODO
- Audit whether `zero_rows`/`new_rows` in the BARRIER branch (:730-743) has the
  same latent attribution issue (likely benign there: synchronized rounds).
