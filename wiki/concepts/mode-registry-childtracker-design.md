---
type: concept
title: Mode registry + ChildTracker — refactor design
description: 'crystallized refactor design: ModeSpec registry in core/modes.py (all
  fields required, no silent defaults) + stateful ChildTracker with injected signals
  adapter; cl_min picker retired (ADR-0001/0002); FULL-CUT DONE 2026-07-19 —
  STALE_CLUSTER Resolution + launch/assign rewiring + launch-failed immediate
  resolution; ChildTracker is now the sole resolver of child state at the barrier'
status: resolved
timestamp: '2026-07-20'
updated_note: 'ChildTracker FULL-CUT landed (556ac5c + 1d37217) — the first-cut
  gap this page flagged (launch/assign still self-checking) is closed'
---

# Mode registry + ChildTracker — refactor design

## Summary
Crystallized design (2026-07-06 grilling session) for the two refactors picked
from [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md): (1) a single pure-data ModeSpec
registry in `core/modes.py` (was root `modes.py` until the 2026-07-17
reorg), and (2) a stateful ChildTracker owning child
resolution in the closed loop. Decisions are recorded in `docs/adr/0001` (retire
cl_min) and `docs/adr/0002` (registry home); domain terms in root `CONTEXT.md`.
**Implementation is gated on foilsflash08 completing** — the parent Popens fresh
`graph.run` children from on-disk code at R1, so editing graph/*, pipeline.py,
or the driver mid-campaign changes running code.

## Key facts
- **ModeSpec fields** (frozen dataclass, ALL required — no defaults): name,
  musing (abs. setup.sh path), grid_tarball, grid_stages (tuple), harvest_verb,
  stage_target_overrides (dict), bounds_lo/bounds_hi/int_dims, and 5 preflight
  policy flags replacing the 6 hand tuples: `preflight_fcl`
  ("surfacecheck"|"preflight", was :2187), `dumps_gdml` (:2195),
  `verifies_foil_gdml` (:2299), `preserves_gdml` (:2332),
  `checks_managed_overlap` (:2352; the :2386 banner derives from this flag,
  which auto-fixes the prodtarget6d banner drift).
- **Consumer rewiring**: graph/config.py keeps the env-presniff mechanism but
  every `*_BY_MODE` dict becomes `modes.SPECS[mode].<field>` (loud KeyError);
  pipeline.py `MUSE_BASE_TARBALL` loses the silent `.get(..., michael)`;
  botorch_predict.py deletes `MODE_SPECS` and reads bounds from the registry
  (works because bounds are plain data — skopt is only imported inside
  `build_space`, which is why botorch_predict.py:46 can already
  `import bo_driver`); `graph/state.py` keeps its Literal +
  a test pins `get_args(Literal) == set(modes.SPECS)`.
- **The env seams stay env**: `AUTORESEARCH_NO_RUN1B` remains a post-lookup
  stage filter; `AUTORESEARCH_ELEBEAM_NJOBS` remains an override on top of
  foilsflash's stage_target_overrides.
- **ChildTracker** (module, `graph/child_tracker.py`): per-round object
  holding the children dict, the SqliteSaver conn + once-compiled child graph,
  and the dead-PID grace set. Interface: `tick() -> dict[name, Resolution]`,
  `all_resolved()`, `close()`. Resolution enum: running / done_row /
  done_broken / done_terminal_no_row / dead_unresolved / **stale_cluster**
  (added in the full-cut, 556ac5c). `dead_unresolved` now has TWO paths: the
  original one-tick-grace dead-PID case, and an immediate (no-grace)
  `launch_failed` case (1d37217) for a child whose `subprocess.Popen` itself
  raised — see below.
- **Signals adapter** (Protocol, injected): `in_leaderboard(name)`,
  `is_broken(name)`, `is_terminal(thread_id)`, `pid_alive(pid)`,
  `has_cluster(name)`. Production adapter (`_DiskSignals` in closed_loop.py)
  wraps today's helpers; tests inject a fake — replaces the
  `mock.patch(build_graph)` / `is_child_terminal` acrobatics in the old
  test_closed_loop.py.
- **Consumers of Resolution — FULL-CUT DONE 2026-07-19 (556ac5c + 1d37217).**
  ChildTracker is now the ONLY resolver of child state; `node_launch_children`
  and `node_assign_names` no longer do their own presence/completed
  bookkeeping:
  - `node_assign_names`: does ONE `_leaderboard_names(mode)` read per call
    (was a per-name `_child_in_leaderboard` lookup) to skip already-landed
    names into `completed_names`.
  - `node_launch_children`: still skips the Popen for a name with an
    existing `*_cluster.txt` (double-submit guard) but no longer writes
    `completed_names`/`errors` for stale-cluster skips — it leaves those
    children `RUNNING`-shaped (pid=None, no cluster written by *this*
    parent) for the tracker to resolve. If `Popen` itself raises, the
    record is stamped `launch_failed=True` (pid stays None).
  - `node_barrier`: loops `tracker.tick()`; on `STALE_CLUSTER` prints a loud
    per-name message with the `rm state/*_cluster.txt` recipe and appends to
    `errors` (same operator-facing text the old launch-side code used) —
    the resolution now happens at the BARRIER, not at launch time. On
    `DEAD_UNRESOLVED` the message distinguishes `pid is None` ("launch
    failed, child never started") from `pid` set ("child process `<pid>`
    died without resolution").
  - **Barrier guard narrowed**: the old hard guard was `if not launched:
    raise RuntimeError(...)` (empty launched_names = state-corruption). An
    all-stale or all-resume round now legitimately has an empty `launched`
    with a non-empty `children` dict, so the raise moved to `if not
    children:` (children dict itself empty = the real corruption signal);
    an empty `launched` with children present just logs
    "nothing launched this round (... resume/stale) — tracker will resolve
    them" and proceeds into the tick loop.
  - `decide_next`: counts row vs rowless via its own name-based
    `_leaderboard_names` accounting, not tracker Resolutions (`rolling-no-row-streak-false-increment` fix, pre-existing);
    `history_len_before` zero-rows guard unchanged.
  - **Streak-move**: the plan's separately-scoped "zero-rows/streak
    accounting move" line item was found ALREADY LANDED (the 2026-07-16
    name-based `_leaderboard_names` fix, b98d5da) — dissolved as a no-op
    for this round, not re-touched. Regression-pinned by the existing
    ff18-w1 test.
- **cl_min retirement** (ADR-0001): delete `_import_gp` (closed_loop.py:168-191)
  + the cl_min branch in node_predict_picks; check for then-dead constants
  (NSTEPS_BUDGET, CLOSED_LOOP_MIN_PICK_SPACING, GP_SCRIPT_DIR, pessimistic_calo
  state field) and the tests that patch `_import_gp` (test_closed_loop.py:263,276).
- **Sequencing** (3 commits, each leaving 91 tests green + graph builds under
  all 9 modes): (1) modes.py + consumer rewiring + completeness tests,
  (2) ChildTracker + barrier/launch/assign rewiring, (3) cl_min deletion.
  Then one live single-eval smoke before the next campaign.
- **Verification item found during design**: `MUSE_TARBALL_BY_MODE` has no
  prodtarget keys, yet [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md) says the prodtarget grid
  tarball was rebuilt from the patched workdir — find where pipeline.py
  actually selects the prodtarget tarball (likely a separate path near
  write_code_tarball / pot_only stage config) before declaring the
  grid_tarball field for prodtarget*; the registry field type may need to be
  `path | build-from-workdir`.

## Implementation status (2026-07-11)
- **Commit 3 (cl_min retirement): DONE** — c72498b, plus shared acquisition
  budget constants. DEFAULT_PICKER=hybrid.
- **Commit 2 (ChildTracker): DONE** — 421b1fc (first cut, 2026-07-11),
  **FULL-CUT DONE 2026-07-19** — 556ac5c (STALE_CLUSTER Resolution +
  launch/assign rewiring) + 1d37217 (launch-failed immediate resolution,
  a review finding on the full-cut: Popen-raise previously fell through to
  the 24h `barrier_max_min` backstop instead of resolving loudly). `graph/
  child_tracker.py` (sticky Resolution, tick() returns transitions, dead-PID
  grace inside) + `_DiskSignals` production adapter (late-binds to module
  helpers so existing mock.patch tests keep working — deliberate compat
  choice) + injected-fake tests (13→17 across the two commits;
  test_closed_loop.py 45→47). ChildTracker is now the SOLE resolver of
  child state in closed_loop.py — the first-cut's "launch/assign still use
  their own presence checks" gap (flagged below under Open questions until
  today) is closed. Live validation = next campaign (unit tests exercise
  the real node_barrier through dead-pid/launch-failed/stale-cluster/
  timeout paths; no mock closed-loop round exists — `--no-mock` is
  hardcoded for real children, so this follows the same "live validation
  rides the next campaign" precedent the first cut set).
- **Commit 1 (modes.py registry): DONE** — af985c9. Root modes.py (frozen
  ModeSpec, all fields explicit incl. presubmit_after which post-dated the
  design); config.py dicts + botorch MODE_SPECS + pipeline tarball map are
  registry VIEWS (silent .get(...,michael) fallback deleted — ipa's
  Code_helical_base now explicit); 6 preflight tuples → 5 flags (prodtarget6d
  banner drift fixed by construction); state Literal → 9 modes (now **7** —
  michael/helical retired 2026-07-12, registry lockstep made the deletion a
  clean 11-file coordinated change verified green).
  **Prodtarget tarball question RESOLVED**: ships per-STAGE via
  STAGES["pot_only"]["code_tarball"] (pipeline.py:263-ish); spec records the
  same file, test pins equality — no path|build-from-workdir union needed.
  michael's Categorical (COL5) space carries EXPLICIT None bounds (the one
  field where "required" means "explicitly None"). Validation: one-time
  parity sweep vs all live dicts (zero diffs) BEFORE rewiring, byte-parity
  of botorch MODE_SPECS after, tests/test_modes.py (13: keys==driver
  MODES==state Literal + build_space↔spec bounds lockstep + spot facts),
  graph builds under all 9 modes, 146/146 suite, live dry-run.

## Cross-links
- Related: [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md), [simplification-audit-2026-07](/concepts/simplification-audit-2026-07.md)
- Incident evidence: see [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md) (8 incidents)
- Source files: `core/modes.py`, `graph/child_tracker.py`,
  `core/bo_driver.py:1854`, `graph/closed_loop.py` (node_assign_names,
  node_launch_children, node_barrier),
  `docs/adr/0001-retire-cl-min-picker.md`, `docs/adr/0002-mode-registry-root-modes-py.md`, `CONTEXT.md`
- External: [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

## Open questions / TODO
- RESOLVED 2026-07-19: the full-cut (commit 2's deferred scope) landed —
  see Implementation status. `decide_next`'s zero-rows guard did NOT move
  into ChildTracker (the streak-move item was found already landed via a
  different mechanism, `_leaderboard_names`, and left untouched).
- Recorded follow-up (slim round, 2026-07-19): `decide_next`'s "0/0
  pending — carrying forward" log line is now reachable for all-stale
  rounds and reads ambiguously — a log-clarity pass candidate, not filed
  as a bug.
- GATE: wait for foilsflash08 (launched 2026-07-06, ~15-16 h) before any edit.
- Resolve the prodtarget tarball-selection question above during commit 1.
- **/simplify deferred batch: APPLIED 2026-07-07** after foilsflash08 exited
  (40/40, clean). All items below landed except the seed_optimizer/ask_buildable
  return-signature change (skipped: interface churn across 2 callers + pinned
  tests for print-only values; only the double is_buildable scan was collapsed).
  91 tests green; extract_extras 6D-vs-10D equivalence + 624-row leaderboard
  round-trip + real-data harvest re-run (foilsflash08R00_00) verified. Original
  list, for the record:
  bo_michael: delete ProdTarget6DMode.extract_extras override (parent guards on
  N from `_expand`; differs by ONE token, :1733 vs :1469); drop never-read
  `mean_dose_Gy_per_POT` (:1495/:1751); dedup `load_history_row` extras-parse
  into `_parse_pt_extras` (:1645/:1820); stop recomputing fake_y/penalty_y/
  is_buildable in `_cmd_propose_locked` (:1910-1920 — return them from
  seed_optimizer/ask_buildable); drop duplicate GDML-preserved print (:2346);
  guard `_flock_sh`'s per-read mkdir (:86); shared numpy-scalar coercion helper
  (bo:330 + pipeline_io:102). pipeline.py: fold harvest Step 6/7 copy-paste
  (:1246-1310, same `_extract_trk_edep_per_pot` behind both) into one
  parametrized secondary-metric block; dedup mustops_pileup/mustops_ce
  resampler branches in cmd_submit via a `resamples_from` stage key.
- **Altitude notes feeding the registry design** (from the same review):
  (a) `AUTORESEARCH_NO_RUN1B` re-expresses "qlnei needs no calo" in 3 files
  (closed_loop presniff / config stage-drop / bo:1978 calo=0) — consider a
  picker/mode `needs_calo` declaration; (b) FoilsMode env-gated class attrs
  (`AUTORESEARCH_BASE_HOLE_RADIUS_MM`/`N_UP`/`N_DOWN`, bo:699-704) make
  variants invisible in recorded state — prefer named experimental submodes
  (ProdTarget6DMode pattern); (c) botorch `_load_history_tensor` inlines
  prodtarget objective rows + env box-filters (`AUTORESEARCH_CURRENT_BOX_ONLY`,
  hardcoded dims x[3..5]) — consider `mode.objective_row()` when specs move.
- Skipped deliberately: `--barrier-timeout-min` CLI flag KEPT (documented
  back-compat, docs/closed-loop-barrier-fix.md:299); `_leaderboard_len` full
  parse (once/round, immaterial); `_parse_n_plates_from_geom` cross-venv dedup.
