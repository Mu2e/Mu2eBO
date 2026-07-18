# Design: live-path tests + schema single-sourcing + typed subprocess protocol

Date: 2026-07-18
Status: approved (brainstorming session 2026-07-18)
Predecessors: wiki `concepts/architecture-friction-survey-2026-07` (candidates
3+4, unpicked since 2026-07-06), `concepts/simplification-audit-2026-07`
(deletion angle exhausted; "suite green while live path broken" bitten twice).

## Context

Last week's simplification campaign closed the deletion angle: every
delete/keep candidate has a recorded disposition. What remains is structural:

1. **Untested live paths.** `core/botorch_predict.py` (~600 lines: history
   loading, GP fit, qNEHVI/pareto_sob/qlnei pickers, picks-JSON emit) has zero
   tests — structurally, because the main suite runs under `.venv-graph`,
   which deliberately has no torch/botorch. `core/pipeline.py`'s grid verbs
   (submit idempotency, cluster-file writes, stage-chain stamping, poll exit
   logic) and the `_flock_ex`/`_flock_sh` lock helpers are likewise untested.
   Twice in the week of 2026-07-14 a 156-green suite hid a broken live path
   (`cur_box` NameError in the picker; a TypeError that disabled the flock
   seam entirely); only live smokes caught them.
2. **Leaderboard schema is not single-sourced.** After the 2026-07-12
   refactor the Foils family writes rows via `KNOB_NAMES`/`KNOB_FMTS`/
   `CALO_COL` class attrs on the driver, but `botorch_predict.
   _load_history_tensor` keeps its own inlined column-width expectations
   (guard at `botorch_predict.py:121`), and the ProdTarget family keeps a
   divergent writer pair with literal headers (`bo_driver.py:1024,1039`).
   Nothing enforces writer/reader agreement.
3. **The graph↔driver seam passes structured data as exit codes + stdout
   regex.** Preflight verdicts are bare return codes 0/1/2/3
   (pass/fail_managed/fail_init/ambiguous); `graph/pipeline_io.py:420-426`
   regex-scrapes `obj=` from evaluate stdout. A reworded print silently
   breaks the parse.

No campaign is running and none is planned, so the work proceeds as one
uninterrupted block; each commit still leaves the repo green and
launch-ready.

## Goals

- A green suite means the live path works: pickers, grid verbs, and locks
  are exercised by tests, not only by live smokes.
- `modes.SPECS` becomes the single authority for per-mode leaderboard
  columns (as it already is for bounds, stages, tarballs).
- Preflight and evaluate results cross the subprocess seam as typed JSON.
- TSV bytes on disk never change (off-repo plotters depend on them).

## Non-goals

- No behavior change to picking, harvesting, or the leaderboard record.
- No file-level leaderboard/pending schema merge (rejected 2026-07-18,
  recorded in the simplification audit).
- No ChildTracker full-cut, no altitude cleanups (`needs_calo`, named
  submodes) — separate future rounds.
- No CI system; both suites remain manually invoked.

## Approach: golden-harness-led

Capture golden outputs before refactoring; require byte-identical parity
after each refactor commit; write durable tests against the new interfaces
only. Code the refactor does not touch gets durable tests up front. This is
the method that landed the 9-mode driver rewrites green.

## Phase 0 — durable tests for untouched code

**`tests_botorch/`** — a second small suite, run with
`PYTHONPATH= .venv-botorch/bin/python -m unittest discover -s tests_botorch -v`
(the venv split makes a second suite the only way to import the picker).
Covers the pure parts of `botorch_predict.py`: `_load_history_tensor`
against tmp TSV fixtures (row parsing, width guard, sob-only path), seeding
(`--round-idx` → 42^idx), min-spacing filters, picks-JSON emit; plus one
tiny real GP fit + qNEHVI pick on ~10 synthetic rows (CPU, seconds).

**`tests/test_pipeline_verbs.py`** — main suite. Submit idempotency
(existing `state/<cfg>/<stage>_cluster.txt` → no-op), stamp-at-submit
(`stamp_stage_chain` written only on first real submit), poll exit
conditions, list-outputs gating. The jobsub/subprocess boundary is faked via
an injected runner; where `pipeline.py` needs a seam, the extraction is a
minimal behavior-preserving parameter (default = today's subprocess call).

**`tests/test_flock.py`** — main suite. Real `flock` acquisition on tmp
files: `_flock_ex`/`_flock_sh` acquire/release/contention and the
`_lock_path` anchor (`<target's dir>/locks/<name>.lock`). Closes the gap
that let the lock seam break with the suite green.

**Cross-venv smoke** — main suite, one test: `bo_driver.botorch_ask()`
q=2 against a tmp ~10-row leaderboard, `unittest.skipUnless` the botorch
venv exists. The only slow test in the main suite.

## Phase 1 — schema single-sourcing into ModeSpec

`core/modes.py` `ModeSpec` gains three required fields per mode:

- `knob_names: Tuple[str, ...]` (moves from driver class attr)
- `knob_fmts: Tuple[str, ...]` (moves from driver class attr)
- `metric_cols: Tuple[str, ...]` — the full post-knob column tail. Foils
  family: `("sob", "calo", "alpha", "obj")` (foilsflash:
  `("sob", "flash_edep", "alpha", "obj")`). ProdTarget family:
  `("mu_per_POT", "edep_per_POT_MeV", "peak_dose_Gy_per_POT",
  "peak_plate_idx", "obj")` — its divergence is data, not a special case.
  (The leading identifier column — `name` vs `config` — stays a writer
  detail, pinned by golden (a).)

Validation moves to construction: `__post_init__` asserts
`len(knob_names) == len(knob_fmts) == len(bounds_lo)`. The existing
lockstep test becomes true by construction; `test_modes.py` shrinks to
spot-checks plus the new-field pins.

Consumers:

- Driver `KNOB_NAMES`/`KNOB_FMTS` become reads from `SPECS[self.name]`;
  `CALO_COL` derives as `metric_cols[1]` for the Foils family;
  `FoilsMode.format_row`/`load_history_row` logic unchanged. The ProdTarget
  family keeps its own implementation but derives header strings from
  `knob_names + metric_cols` instead of literals.
- `botorch_predict._load_history_tensor` derives expected width and
  knob-column indices from the spec; the width guard's `SystemExit`
  behavior stays, message now spec-derived.

TSV bytes are unchanged — pinned by golden (a).

## Phase 2 — typed JSON result protocol

Both verbs gain `--emit-json <path>` (pattern:
`botorch_predict --emit-picks-json`). Files are written atomically
(tmp + rename) into the config's state dir, which also aids autopsy
forensics:

- `state/<cfg>/preflight_verdict.json`:
  `{"verdict": "pass"|"fail_managed"|"fail_init"|"ambiguous", "rc": int,
  "reasons": [str], "log_path": str, "config": str}`
- `state/<cfg>/evaluate_result.json`:
  `{"config": str, "obj": float, "sob": float, "calo_or_flash": float|null,
  "row_appended": bool}`

`graph/pipeline_io.py`: `run_preflight` reads the verdict JSON;
`run_evaluate` reads `obj` from JSON. The `obj=` stdout regex
(`pipeline_io.py:420-426`) and the exit-code verdict decode are deleted;
exit codes remain only as a transport-failure backstop.

Error handling at the seam:

- Preflight: valid JSON wins over the exit code. Process crash with no JSON
  decodes as `ambiguous` with a loud reason string — fail-safe, since
  `ambiguous` already routes to retry/human review and never silently
  passes.
- Evaluate: missing or unparseable JSON is a hard error (a run that cannot
  prove it recorded a row already is one).
- No compatibility window needed: both ends of the seam are in this repo
  and children launch from on-disk code.

## Golden parity harness

`tests/golden_parity.py` — a manually-run script (same convention as
`test_wal_multiwriter_stress.py`; no `test_` defs, not in unittest
discover). Three captures, taken once before Phase 1 and re-compared after
every refactor commit:

- (a) per-mode: `load_history()` → `format_row` round-trip, byte-compared
  against the live leaderboards (pins reader and writer at once, all 6
  modes).
- (b) picker: fixed-seed hybrid q=2 picks on a frozen copy of
  `leaderboards/leaderboard_bo_foilsflash.tsv`.
- (c) seam: preflight + evaluate replay on an already-completed config
  against a tmp leaderboard copy (stdout, rc, obj — and after Phase 2, the
  JSON files).

## Verification

- Main suite green under `.venv-graph` (156 + ~30 new tests);
  `tests_botorch/` green under `.venv-botorch` (~12 tests).
- Goldens byte-identical after commits 4–6.
- Live smokes at end of round: real `botorch_ask` q=2 on the live
  foilsflash leaderboard; one full `graph.run --mock` chain (exercises
  preflight-JSON → evaluate-JSON end-to-end, zero grid contact).

## Commit sequence

Each commit leaves the repo green and launch-ready:

1. `tests/test_flock.py` + `tests/test_pipeline_verbs.py` (+ minimal
   runner seams in `pipeline.py`)
2. `tests_botorch/` suite + cross-venv `botorch_ask` smoke
3. `tests/golden_parity.py` + captured baseline
4. Phase 1: schema fields → ModeSpec; driver + picker rewired; goldens
   re-verified
5. Phase 2a: preflight verdict JSON
6. Phase 2b: evaluate result JSON; stdout regex deleted
7. Wiki sweep: friction-survey candidates 3+4 → resolved; ml-stack test-gap
   note; `drivers/tests.md` (both suite commands); audit-page pointer;
   `log.md`

## Risks

- **Off-repo plotters** (~20 unversioned scripts read the TSVs): untouched;
  TSV bytes never change, enforced by golden (a).
- **Second test suite discoverability**: run command documented in
  `wiki/drivers/tests.md` and the project test notes; the cross-venv smoke
  in the main suite fails loudly if the picker seam breaks even when
  `tests_botorch/` is forgotten.
- **Seam extractions in `pipeline.py`**: minimal, behavior-preserving,
  golden-gated like everything else.
- **Mid-campaign edit hazard**: void — nothing running, none planned; each
  phase is one revertible commit.

## Success criteria

Both suites green; goldens byte-identical; live smokes pass; zero TSV byte
changes; `modes.SPECS` is the only place a mode's columns are declared; no
stdout regex or exit-code decode remains on the graph↔driver seam; wiki
records the round.
