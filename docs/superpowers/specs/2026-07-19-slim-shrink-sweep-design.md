# Design: slimming round — giant-file shrink + non-production sweep

Date: 2026-07-19
Status: approved (brainstorming session 2026-07-19)
Predecessors: `2026-07-18-tests-schema-protocol-design.md` (prerequisite —
lands first), wiki `concepts/mode-registry-childtracker-design` (A1 is its
recorded follow-up), `concepts/architecture-friction-survey-2026-07` (A2 is
its harvest phase-2 candidate), `concepts/simplification-audit-2026-07`
(refutations honored; B executes its last open items).

## Context

The user asked for a codebase review "to make it slimmer". The July campaign
already took the cheap slimming: −673 production lines of mode retirements
(michael, helical, ipa), skopt kernel, streamlit overlay, `tools/`, three
venvs → one, with audit refutations recorded against re-proposals. In this
brainstorm the user was offered the one big remaining line-count lever —
retiring dormant research lines (foils/foilsf, foilsg, prodtarget*) — and
declined it: **all six modes stay**. What remains is:

1. **Finish the designed-but-unexecuted refactors that shrink the hardest
   files.** `graph/closed_loop.py` (925 L) still hand-rolls child presence
   checks outside the ChildTracker barrier first-cut (421b1fc);
   `core/pipeline.py` (1,447 L) still inlines the EdepAna and
   sensitivity-macro subprocess steps in `cmd_harvest`.
2. **Execute the audit's last open hygiene items** — honest small yield;
   the 2026-07-17 rounds already took the bulk.

## Goals

- closed_loop.py has ONE resolver of child state (ChildTracker), including
  stale-cluster detection and the rows/streak accounting.
- cmd_harvest is an orchestration shell; every subprocess it runs is behind
  an injected-runner seam in `harvest.py`, testable with fakes.
- The audit's open hygiene items get executed or a recorded verdict.
- Every commit leaves the repo green and launch-ready; TSV bytes never
  change.

## Non-goals

- No mode retirements (user decision 2026-07-19: keep all six).
- No bo_driver.py work — its dedup angle is recorded exhausted; its schema
  literals belong to the pending spec's Phase 1.
- No re-litigation of audit refutations (deck trio, slides/, Run1BAna
  location, qlnei, satellite truth-sites, etc.).
- No behavior change except the zero-rows/streak accounting move (isolated
  in its own commit).

## Block A1 — ChildTracker full-cut (`graph/closed_loop.py`)

The barrier already delegates to `graph/child_tracker.py` (first cut,
2026-07-11). The full-cut is the design page's recorded follow-up list:

- `node_launch_children` and `node_assign_names` stop doing their own
  presence checks and consume tracker Resolutions. Stale-cluster detection
  (`_already_running` reading `state/*_cluster.txt`) becomes a first-class
  `STALE_CLUSTER` Resolution instead of a pre-filter — the mechanism behind
  `closed-loop-stale-cluster-silent-no-launch` gains a name and a test.
- The zero-rows/streak accounting in `decide_next` (and rolling mode's
  `no_row_streak`) moves onto the tracker's name-based `done_names()` /
  `DONE_ROW` counts. This closes the
  `rolling-no-row-streak-false-increment` class (wave-level row deltas
  vs barrier-time resolutions) by construction; a regression test pins the
  ff18-w1 scenario: a child resolving during a wave transition must not
  increment the streak.
- Delete the superseded hand-rolled set logic; shrink the
  `test_closed_loop.py` mock-patch acrobatics that the injected-fake
  Signals pattern replaces.

## Block A2 — harvest phase-2 runner seams (`core/pipeline.py`)

The EdepAna run (Step 1, `pipeline.py:1265-1282`) and the
sensitivity-macro run (Step 4, `pipeline.py:1302+`) move into `harvest.py`
behind the injected-runner pattern `extract_secondary_edep` established.
`cmd_harvest` keeps only sequencing; the moved steps get fake-runner tests
in `tests/test_harvest.py` (success, nonzero-rc SystemExit with log path,
parse of the 'S/sqrt(B) =' line). `EDEP_FCL` / `SENSITIVITY_MACRO`
constants move with their consumers.

## Block B — non-production sweep (hygiene, small yield)

1. `.claude/commands/closed-loop-status.md` re-audit (the audit's open
   item): verify column indices/prefixes against the current layout; fix
   or delete with a recorded verdict.
2. `Run1BAna/workflows/config_bo000..002/` — delete the three untracked
   early-era config dirs only. The clone itself is load-bearing
   (`EDEP_FCL`, `SENSITIVITY_MACRO`) and untouchable.
3. Root gitignored `.bak` sediment: named-path `rm` each; the zero-byte
   `.lock` files stay (permanent by design).
4. Orphan-reference grep over `.claude/` skills/commands + tracked docs
   for strings retired since the last sweep (skopt flags, `pending/`,
   per-venv names); fix hits, expect few.

## Sequencing

0. **Prerequisite (separate document):** the pending tests/schema/protocol
   spec is reviewed by the user, gets its own plan, and lands first. Its
   suite and golden harness are the protection for A2 and the TSV pin for
   everything.
1. **Block B** — independent, zero behavior risk, may land immediately
   (before the prerequisite if convenient).
2. **Block A2** — after the prerequisite. Gate: golden re-harvest of a
   completed foilsflash config (e.g. foilsflash13R00_02) with all 26
   legacy summary.json keys bit-identical.
3. **Block A1** — last; it touches launch/barrier semantics. Hard
   precondition re-verified at execution time: no campaign running
   (`ps -fu $USER -ww | grep "[c]losed_loop"`).

## Verification

- Suite green after every commit; zero TSV byte changes (golden (a) of the
  prerequisite's harness).
- A2: fake-runner unit tests + the golden re-harvest gate.
- A1: injected-fake tests for STALE_CLUSTER and the moved streak/zero-rows
  accounting (incl. the ff18-w1 regression pin); one mock closed-loop
  round (q=2, `--mock` children, `--max-rounds 1`) end-to-end; live
  validation rides the next real campaign, as the barrier first-cut did.

## Commit sequence

Each commit leaves the repo green and launch-ready:

1. Block B sweep batch (+ any `.claude` deletions, named paths only).
2. A2: harvest.py runner seams + test_harvest.py additions + cmd_harvest
   Steps 1/4 delegation; golden re-harvest verified.
3. A1: STALE_CLUSTER + launch/assign rewiring + tests.
4. A1: zero-rows/streak accounting move — its own commit; the round's one
   behavior-adjacent change, revertible alone.
5. test_closed_loop.py acrobatics shrink.
6. Wiki sweep: friction-survey (harvest phase-2 done) +
   childtracker-design (full-cut done) pages, `drivers/tests.md` counts,
   `log.md`.

## Risks

- **Mid-campaign edit hazard**: A1/A2 touch closed_loop/pipeline — the
  no-campaign precondition is checked at execution, not assumed from
  planning time.
- **Streak semantics (commit 4)**: the one intended behavior change;
  isolated, regression-pinned, revertible without touching the
  structural commits.
- **Golden coverage**: the re-harvest golden only covers foilsflash;
  prodtarget-family harvest paths are exercised by unit tests with fake
  runners (their live paths are dormant — acceptable, recorded here).

## Success criteria

Suite green; goldens byte-identical; mock closed-loop round passes;
ChildTracker is the only resolver of child state in closed_loop.py;
cmd_harvest contains no inline subprocess calls; audit open-items executed
or adjudicated; wiki records the round.
