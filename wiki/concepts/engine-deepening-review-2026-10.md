---
type: concept
title: Engine deepening review (2026-10)
description: 'architecture review of the contract engine after the PR #36 cleanup (2026-10-08): 7 candidates, each reproduced in a sandbox and re-rated; 4 small fixes landed the same day (pool drain, beamkit run identity, per-kit job count, submit record); the step-params module is the next deepening; refuted claims listed so they are not re-proposed'
status: active
status_note: 4 small fixes landed 2026-10-08; C3, C6 step record, C2 rest and C5 board pin not started
timestamp: '2026-10-08'
---

# Engine deepening review (2026-10)

## Summary
On 2026-10-08 the engine (branch pr-cleanup, f50cb1f) was surveyed for
deepening opportunities: modules whose rules are decided in several places.
Seven candidates came out. One agent per candidate then reproduced it in a
sandbox (fakes and toykit, no grid, live data read only), searched logs,
wiki and git history, and re-rated it. Four size-S fixes landed the same
day. This page keeps what a future review should not have to re-derive or
re-propose.

## Key facts

### Landed 2026-10-08
- **Pool failure policy (C1, shape A).** A failing pick used to unwind
  through `ThreadPoolExecutor.__exit__`, which waits for every in-flight
  child: hours of silence, `parent.lock` held, no Outcomes recorded. It now
  logs `[pool] FATAL` at once, drains with heartbeats and one Outcome per
  child, then re-raises (exit 1). A failing row or `broken.txt` read is
  that child's Outcome (`outcome unknown: ...`); a landed row counts
  whatever the rc (`row landed but child rc=N`). Trigger measured on a
  copy of the `_upstream` board: `budget_sob` raises `InfeasibleError`
  for any set of 2-5 over-budget rows (feasible from 6). Near miss:
  bpzax01 R22 found 37 of 16384 feasible candidates at k=0.
- **beamkit run identity (part of C6).** beamkit adopted a run by its tag
  alone. Following the Busy-name recovery (remove `state/`, rerun the same
  config at another x) landed a row whose x was not the jobs' x. It now
  adopts only a run created after this step began submitting, with exactly
  the params, `njobs` and `events_per_job` sent, as prodtools already did.
- **Job count per kit (part of C2, with C7).** The dry-run budget counted
  only prodtools steps, so ptg5k01 and ptg5k02 were launched after dry runs
  showing 0 grid jobs (they ran 180 and 400). `KitDecl.jobs_of` now
  declares the count; a prodtools step without `njobs` counts its stage
  template's (it was undercounted 115 vs 315).
- **Submit record (C4, shape A).** The kit version was read with the
  results, so a step in flight across a hand bump was stamped with the new
  version, silently on an empty board or on the new board the launch check
  itself advises. `state/<step>_submit.json` now records it before
  `submit`, and a change is refused (`measure.in_flight_problem`).
  Stamping the submit version onto the row instead would be wrong for a
  change that touches only results (beamkit's `FOM_VERSION`).

### Next, by value
- **C3, one module for a kit call's params (Strong, M).** Seven divergences
  reproduced through the real load, launch and run code:
  - a beamkit profile `R` sent as `R_0..R_2` while `deck_params` sets
    `R_1`: the record says 3.0 and the deck gets 9.99, and `check_study`
    passes;
  - a `params_from` name equal to a profile's split name fails only after
    the upstream grid step;
  - a preflight param clashing with a kit setting breaks every point;
  - the `describe` check looks only at `{p}_0`;
  - anakit's own check uses unsplit names;
  - a knob mapped to `njobs` skips the 200-job cap;
  - `${ARTIFACT}` in nested values is neither expanded nor refused.

  Three review fixes (`015ac2d`, `9923d64`, `1b3db4a`) each patched one
  site, and the first three divergences are the sibling sites they missed.
- **C6, a step-record module (M).** These prodtools fixes never reached
  beamkit:
  - wait out stage-out lag: beamkit fails at once with 17 of 20 files and
    stays failed after 20 appear;
  - refuse a kit with no timeout: beamkit's first status raises
    `KeyError`.

  ptg5k01 R05 and R06 were falsely failed (`87a19a2`).
- **The rest of C2.**
  - A shell launch on a prefix with a stale STOP rewrites `campaign.json`,
    launches 0 and exits 0.
  - `budget_sob` on a study with no constraint passes every dry run.
  - The objective-count rule refuses a 1-objective study with a
    constraint.
  - `--q 0` and `--max-evals 0` pass the checks.
  - An invalid `--picker` gives empty `problems`.
- **C5, re-scoped to pinning the board.** `campaign.json` records only the
  study name and status re-reads the board from the study file as it is
  now, so a `leaderboard.file` change shows children that landed rows as
  "ended without a row". A child that exits during launch staggers shows
  "starting" for up to (q-1) x stagger.
- **C1 shape B:** an infeasible pick holds its slot and retries after the
  next resolution, instead of ending the campaign.
- **Path escape:** a toykit- or anakit-only study accepts the config name
  `../escaped`, which puts the point folder outside the grid root.

### Refuted (do not re-propose)
- Child-prefix collisions: `is_child` matches exactly. Only the
  `/closed-loop-status` command's shell glob collides (`helicalS` matches
  `helicalSR01`).
- Merging `pool.classify`, `busy_reason` and `campaigns.child_state`: they
  answer different questions (what happened at exit, may this name be
  relaunched, what is it now). Keep them apart.
- The three "best by primary" copies agree on every live board; they
  differ only on NaN, inf or ties.
- The four adapter executor checks never run (`launch_problems` refuses
  first). Delete them, but they cause no harm. beamkit's skipped
  config-name check is covered at launch.
- `study.py` holds no kit-name literals. The overlap policy and deck
  shadowing already sit beside the KitDecls.
- `GuardedKit` does not mask an `AttributeError` raised in a hook body.
  The silent skip is a misspelled or property hook found by
  `getattr(..., None)`; `b3d9c88` fixed the same pattern once.
- `MeasureMismatch` cannot come from the pool's row check: `load()` does
  not check `measure_sha`.

### Measured facts
- One hand kit-version bump ever (anakit 1 to 2, 2026-10-07); prodtools
  has never been bumped. Its build key is empty in all 188 step records.
- Campaign parent signals: one Ctrl-C waits silently for the children; two
  release the lock but the process lingers; three orphan the children;
  SIGTERM writes no `exit_code`. STOP is the only documented stop.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md),
  [service](/drivers/service.md),
  [engine-seam-friction-survey-2026-08](/concepts/engine-seam-friction-survey-2026-08.md),
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md)
- Source files: `graph/pool.py`, `core/adapters/beamkit.py`,
  `core/kit_registry.py:step_jobs`, `core/measure.py:in_flight_problem`,
  `core/point_dir.py`

## Open questions / TODO
- C3, the C6 step-record module, the rest of C2, and C5's board pin are
  not started.
