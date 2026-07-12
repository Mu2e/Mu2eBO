# Mode registry + ChildTracker — refactor design

**Type:** concept
**Status:** resolved
**Updated:** 2026-07-11 (ALL THREE COMMITS DONE — design fully implemented)

## Summary
Crystallized design (2026-07-06 grilling session) for the two refactors picked
from [[architecture-friction-survey-2026-07]]: (1) a single pure-data ModeSpec
registry in root `modes.py`, and (2) a stateful ChildTracker owning child
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
  `import autoresearch_bo_michael`); `graph/state.py` keeps its Literal +
  a test pins `get_args(Literal) == set(modes.SPECS)`.
- **The env seams stay env**: `AUTORESEARCH_NO_RUN1B` remains a post-lookup
  stage filter; `AUTORESEARCH_ELEBEAM_NJOBS` remains an override on top of
  foilsflash's stage_target_overrides.
- **ChildTracker** (new module, `graph/child_tracker.py`): per-round object
  holding the children dict, the SqliteSaver conn + once-compiled child graph,
  and the dead-PID grace set. Interface: `tick() -> dict[name, Resolution]`,
  `all_resolved()`, `close()`. Resolution enum: running / done_row /
  done_broken / done_terminal_no_row / dead_unresolved / stale_cluster.
- **Signals adapter** (Protocol, injected): `in_leaderboard(name)`,
  `is_broken(name)`, `is_terminal(thread_id)`, `pid_alive(pid)`,
  `has_cluster(name)`. Production adapter wraps today's helpers
  (closed_loop.py:198-242 + build.is_child_terminal); tests inject a fake —
  replaces the `mock.patch(build_graph)` / `is_child_terminal` acrobatics in
  test_closed_loop.py:484-518.
- **Consumers of Resolution**: node_assign_names (skip done), node_launch_children
  (`_already_running` + stale_cluster routing), node_barrier (loop over tick()),
  decide_next (counts done_row vs rest; `history_len_before` zero-rows guard
  kept in first cut).
- **cl_min retirement** (ADR-0001): delete `_import_gp` (closed_loop.py:168-191)
  + the cl_min branch in node_predict_picks; check for then-dead constants
  (NSTEPS_BUDGET, CLOSED_LOOP_MIN_PICK_SPACING, GP_SCRIPT_DIR, pessimistic_calo
  state field) and the tests that patch `_import_gp` (test_closed_loop.py:263,276).
- **Sequencing** (3 commits, each leaving 91 tests green + graph builds under
  all 9 modes): (1) modes.py + consumer rewiring + completeness tests,
  (2) ChildTracker + barrier/launch/assign rewiring, (3) cl_min deletion.
  Then one live single-eval smoke before the next campaign.
- **Verification item found during design**: `MUSE_TARBALL_BY_MODE` has no
  prodtarget keys, yet [[prodtarget-env-divergence]] says the prodtarget grid
  tarball was rebuilt from the patched workdir — find where pipeline.py
  actually selects the prodtarget tarball (likely a separate path near
  write_code_tarball / pot_only stage config) before declaring the
  grid_tarball field for prodtarget*; the registry field type may need to be
  `path | build-from-workdir`.

## Implementation status (2026-07-11)
- **Commit 3 (cl_min retirement): DONE** — c72498b, plus shared acquisition
  budget constants. DEFAULT_PICKER=hybrid.
- **Commit 2 (ChildTracker): DONE** — 421b1fc. `graph/child_tracker.py`
  (sticky Resolution, tick() returns transitions, dead-PID grace inside) +
  `_DiskSignals` production adapter (late-binds to module helpers so existing
  mock.patch tests keep working — deliberate compat choice) + 14 injected-fake
  tests. First cut scope: BARRIER only; launch/assign still use their own
  presence checks (they are one-shot, not stateful) — full-cut rewiring +
  moving decide_next's zero-rows guard remain optional follow-ups. Live
  validation = next campaign (unit tests exercise the real node_barrier
  through dead-pid/timeout/stale paths).
- **Commit 1 (modes.py registry): DONE** — af985c9. Root modes.py (frozen
  ModeSpec, all fields explicit incl. presubmit_after which post-dated the
  design); config.py dicts + botorch MODE_SPECS + pipeline tarball map are
  registry VIEWS (silent .get(...,michael) fallback deleted — ipa's
  Code_helical_base now explicit); 6 preflight tuples → 5 flags (prodtarget6d
  banner drift fixed by construction); state Literal → 9 modes.
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
- Related: [[architecture-friction-survey-2026-07]], [[closed-loop-bo-design]]
- Incident evidence: see [[architecture-friction-survey-2026-07]] (8 incidents)
- Source files: `modes.py` (to be created), `graph/child_tracker.py` (to be
  created), `autoresearch_bo_michael.py:1854`, `graph/closed_loop.py:520`,
  `docs/adr/0001-retire-cl-min-picker.md`, `docs/adr/0002-mode-registry-root-modes-py.md`, `CONTEXT.md`
- External: [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

## Open questions / TODO
- GATE: wait for foilsflash08 (launched 2026-07-06, ~15-16 h) before any edit.
- Resolve the prodtarget tarball-selection question above during commit 1.
- Decide during commit 2 whether decide_next's zero-rows guard can also move
  into ChildTracker (out of first-cut scope).
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
