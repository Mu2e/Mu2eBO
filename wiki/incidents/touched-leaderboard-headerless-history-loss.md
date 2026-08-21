---
type: incident
title: '`touch`-ing a new leaderboard silently disables history for that mode'
description: Creating a leaderboard TSV with `touch` means append_history never
  writes the header (`new_file = not exists()`), so csv.DictReader eats data row 1
  as the header and load_history() returns 0 points FOREVER — GP cold-starts every
  round and no_row_streak marches to a spurious ABORT
status: resolved
status_note: 'hit on foilspfbw01 2026-08-07, repaired in-flight at 3 rows; the
  one-line code fix is proposed, not yet applied'
timestamp: '2026-08-07'
---

# `touch`-ing a new leaderboard silently disables history for that mode

## Summary
Bringing up a new BO mode, the leaderboard TSV was created with `touch` before
the first launch. That single command silently destroyed the mode's entire
history channel: `load_history()` returned **0 points while rows sat on disk**,
so every round cold-started with Sobol (random search, not BO) and every
successful child was counted "rowless", driving `no_row_streak` toward a
spurious `ABORT` at `streak >= q`. Nothing logged an error at any layer.

## Key facts
- **Root cause is a two-line interaction, neither line wrong on its own:**
  - `bo_driver.py:288` — `append_history` writes the header only
    `if new_file`, where `new_file = not self.leaderboard.exists()`. `touch`
    makes the file *exist*, so the header is **never** written — not on the
    first append, not ever.
  - `bo_driver.py:271` — `load_history` reads with
    `csv.DictReader(f, delimiter="\t")`, which consumes **line 1 as the
    header**. With no header, data row 1 becomes the column names.
- **The failure is SILENT by construction.** `load_history_row` raises
  `KeyError` on `row["config"]` for every subsequent row, and
  `bo_driver.py:273-274` swallows it: `except (KeyError, ValueError): continue`.
  That guard exists to tolerate partial/corrupt rows, and here it converts a
  total-loss condition into an empty list with no message.
- **Three downstream symptoms, none of which names the cause:**
  1. `botorch_predict` sees `X.shape[0] < 2` → Sobol cold-start **every
     round**. The campaign looks healthy and is doing random search.
  2. `_leaderboard_names()` is always empty → in
     `graph/closed_loop.py:680-684` every newly-resolved child is `rowless`,
     so `no_row_streak` increments on **successful** children and never
     resets. At `streak >= q` the rolling guard aborts a healthy campaign.
  3. `_leaderboard_len()` is always 0 → `decide_next` prints `+0 rows` forever.
- **Misdiagnosis trap (recorded because it cost a diagnosis cycle):** symptom 2
  is a *perfect* impostor of
  [rolling-no-row-streak-false-increment](/incidents/rolling-no-row-streak-false-increment.md)
  — same `+0 rows` with a real row on disk. The discriminator is
  `load_history()`: run it directly. Wave-transition artifact → returns the
  rows; this bug → returns `0`. The name-based `_leaderboard_names` fix for
  that older incident is present and correct; it cannot help when the name
  set is empty for an unrelated reason.
- **Repair (safe while the campaign runs):** derive the canonical header from
  the mode (`m.format_row(...)` — never hand-type the columns), then prepend it
  under the same `bo._flock_ex(lb)` the children use, writing to a temp file and
  `Path.replace()` so a concurrent append cannot be lost. History is re-read
  every round, so the running campaign self-heals: on foilspfbw01 the very next
  `decide_next` printed `+4 rows, no_row_streak=0/10`.
- **Cost when caught early is ~one pick.** `botorch_predict` falls back to
  Sobol below 2 rows anyway, so only rounds with >= 2 real rows are actually
  degraded. Caught at 3 rows on foilspfbw01; had it reached eval 10 the whole
  campaign would have been random search *and* then aborted itself.
- **Durable fix (PROPOSED, not applied — a live campaign spawns fresh
  `bo_driver` subprocesses, so mid-flight edits change code under running
  children):** test for an *empty* file, not an absent one —
  `new_file = not self.leaderboard.exists() or self.leaderboard.stat().st_size == 0`.
- **Prevention:** do NOT pre-create a leaderboard. `append_history` creates it
  with its header on first write. If a file must exist ahead of time (e.g. to
  seed rows), write the header line first.

## Cross-links
- Related: [rolling-no-row-streak-false-increment](/incidents/rolling-no-row-streak-false-increment.md)
  (the impostor), [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md)
  (another false "all failed" read), [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md)
  (same family: a silent default that poisons a whole line's rows)
- Source files: `core/bo_driver.py:266-290` (`load_history` / `append_history`),
  `graph/closed_loop.py:220` (`_leaderboard_names`), `:680-684` (streak)
- Evidence: [bo-foilspf](/projects/bo-foilspf.md) (foilspfbw01, 2026-08-07)

## Open questions / TODO
- Apply the `st_size == 0` fix to `append_history` once foilspfbw01 drains.
- Consider making `load_history` loud: if the file is non-empty and **every**
  row fails to parse, that is never legitimate — warn rather than return `[]`.
