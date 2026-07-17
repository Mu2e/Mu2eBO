# Architecture friction survey (2026-07)

**Type:** concept
**Status:** active
**Updated:** 2026-07-12 (size-reduction sweep executed: −348 production lines, 10 commits)

## Summary
Codebase-wide friction map produced by the 2026-07-06 `/improve-codebase-architecture`
review (Explore-agent sweep with file:line evidence). Captures where per-mode
configuration, child-status logic, leaderboard schema, and the graph↔driver seam are
scattered — the structural soil under ~8 root-caused campaign failures. Use this page
before adding a mode or refactoring; the line numbers date from 2026-07-06.

## Key facts
- **9 canonical modes** (michael, helical, foils, foilsf, foilsflash, foilsg, ipa,
  prodtarget, prodtarget6d); mode identity is dispatched at **~20 sites across 6 files**.
- Mode-keyed dicts and their key counts (divergence = drift): `autoresearch_bo_michael.py:1854`
  MODES (9), `graph/config.py:35` MUSING_BY_MODE (9), `:64` GRID_STAGES_BY_MODE (9),
  `:94` HARVEST_VERB_BY_MODE (9), `botorch_predict.py:63` MODE_SPECS (8, no michael —
  intentional), `pipeline.py:98` MUSE_TARBALL_BY_MODE (6 — ipa/prodtarget* fall through
  a **silent** `.get(..., michael)` default at `pipeline.py:106-108`),
  `graph/closed_loop.py:168` `_import_gp` if/elif (6 — no prodtarget*, so `cl_min`
  picker cannot serve prodtarget), `graph/state.py:32` mode Literal (7 — missing
  prodtarget/prodtarget6d: type-annotation drift).
- **6 hand-listed preflight mode-tuples** in `autoresearch_bo_michael.py`:
  `:2187` (8), `:2195` (6), `:2299` (4), `:2332` (2), `:2352` (7), `:2386` (6).
  `:2352` vs `:2386` differ only by prodtarget6d — latent inconsistency of the
  [[preflight-mode-tuple-prodtarget6d-omission]] class.
- `_presniff_mode` (argv scan to stamp AUTORESEARCH_MODE before `graph.config` import)
  is duplicated: `graph/run.py:28-38` and `graph/closed_loop.py:61-83`. foilsflash-specific
  env branches hardcoded at `pipeline.py:265-274` and `graph/config.py:140-151`.
- **closed_loop barrier has 5 sources of truth** for "is this child done": SqliteSaver
  checkpoint, leaderboard row (`_child_in_leaderboard:230`), `state/broken.txt`
  (`:226`), PID liveness (`:198`), `cluster.txt` existence (`:428`); hand-reconciled at
  `:408/:436/:495/:572-598` with grace-tick logic. Five incidents trace here.
- **Leaderboard schema is authored in ~9 per-subclass `format_row` header string
  literals**; three independent readers (driver `load_history`, `botorch_predict.py`
  with a runtime `SystemExit` width guard at `:214-217`, `graph/pipeline_io.py:62/:459`
  naming scans). No shared schema constant.
- **Graph↔driver seam carries structured data as bare exit codes + stdout regex**:
  preflight verdict = exit code `{0:pass,1:fail_managed,2:fail_init,3:ambiguous}`
  encoded at `autoresearch_bo_michael.py:2169`, decoded at `graph/pipeline_io.py:134`,
  re-listed in `graph/nodes.py:276`; `run_evaluate` scrapes `obj` from stdout via regex
  at `pipeline_io.py:449`. pipeline_io ALSO reach-around-reads `state/*_cluster.txt`
  directly (`:255`), so two coupling contracts exist to the same on-disk protocol.
- **Test coverage gaps**: `pipeline.py` and `botorch_predict.py` have ZERO test imports
  (grep-confirmed) — grid submission and the qNEHVI picker are the two largest untested
  modules. `cmd_harvest` is a 205-line inline procedure (`pipeline.py:1137-1341`) with a
  wholly parallel `cmd_harvest_pot_only:1055`; `STAGES` global is mutated at runtime
  (`:266/:808/:820`). `tests/test_wal_multiwriter_stress.py` has 0 `def test_` (a
  stress script, not part of the 91).
- **Search-space bounds are triplicated**: skopt `build_space` (per BOMode subclass),
  botorch `MODE_SPECS` (`botorch_predict.py:63-133`, inlined because the venv can't
  import the driver), and 12 external `gp_predict_*.py` files in mmackenz_table_plots
  (consumed by `_import_gp`).
- Review verdict (candidates presented 2026-07-06, none yet chosen): (1) single Mode
  registry, (2) one child-status resolver, (3) shared leaderboard schema, (4) typed
  JSON result protocol across the subprocess seam, (5) unified mode-parameterized
  harvest. Implementation deferred until foilsflash08 completes (no `graph/*.py` /
  `pipeline.py` edits mid-campaign).

## 2026-07-12 size-reduction sweep (executed) — −348 production lines

A 4-agent read-only survey (driver, pipeline/graph, small modules, cross-file
dup) fed a batched deletion pass, each batch suite-green (152/152) + committed
separately. Net **−348 production-python lines** (536 deleted, 188 added-back
as explanatory comments + `KNOB_NAMES` data), zero behavior change. Method: a
**golden parity harness** (`format_row`/`load_history_row`/`build_space`/
`_geom_text` for all 9 modes, diffed byte-for-byte before/after) guarded the
driver rewrites; every leaderboard round-tripped with zero dropped rows.

What landed (commit → win):
- `e16ad80` dead code: `materialize` verb, `run_grid_real` shim, `list-pending`
  verb, `leaderboard_v2` vestige, `MOCK_SOB_PEAK/FLOOR`, unused imports/params.
- `c247d4a` **registry directness**: `graph/config.py` resolves `_SPEC` once;
  `MUSING_BY_MODE`/`HARVEST_VERB_BY_MODE` pass-through dicts deleted (consumers
  read `_modes.SPECS[m].musing`/`.harvest_verb`); `--mode` choices = `sorted(SPECS)`.
- `8378f28` dead `alpha` plumbing removed across the botorch picker subprocess seam.
- `51d47a1` single homes: `config.open_saver_conn`, `closed_loop._history`,
  `hv.read_outputs` (was 3 hand-rolled outputs.txt parsers).
- `4ab04c8` **dead `auto_continue` inner-graph loop deleted** (`node_decide_next`/
  `route_after_decide`/`iter`/`max_iter` — no writer; closed_loop owns rounds).
- `da14690` `mock_metrics` dimension-generic from `SPECS` bounds (was 4D/5D-only,
  raised ValueError for every higher-D mode — `--mock` smoke silently broken).
- `fe7d83f` **`show-priors` verb + 8 `print_top` methods deleted** (~110 lines,
  display-only, zero callers) + dead `--strategy` cl flag.
- `3b626d1` **`build_space` from `SPECS` bounds + `KNOB_NAMES`** (8 overrides → 1
  base method; deletes dead `F_MAX`/`HT_FLOOR`).
- `52165d8` Foils-family `format_row`/`load_history_row` collapse (`KNOB_NAMES` +
  `KNOB_FMTS` + `CALO_COL`; foils/foilsf/foilsflash share one pair).
- `3ac797e` `cmd_harvest` `_note_degraded` fold + `EvalSummary.write()`.

A second independent survey (2026-07-12) confirmed the **cross-file / tools/ /
pipeline_templates/ angle is exhausted (~0 further low-risk lines)**: every
shared helper is already single-homed (to_py_scalars, read_outputs,
parse_edepana_saw, _seed, run_sourced_bash, open_saver_conn, load_history),
the two flock helpers are correctly distinct (per-leaderboard SH/EX vs
host-wide submit-token lock), the two inline PyROOT extractor scripts share
only trivial imports, and no template pair is a sed-variant. Don't re-run that
angle. The one non-size follow-up it found: `tools/refresh_foils_*` (3 scripts,
last touched `90f3e7f` "foils v2") still hardcode `leaderboard_bo_foils_v1.tsv`
+ `docs/foils_talk.md` while the live foils line is v3 and the active deck is
foilsflash — a staleness bug already logged at [[refresh-foils-slides]]:77;
KEEP (skill + wiki reference them), fix only if the foils deck is still built.

Candidates 3-5 (leaderboard schema, typed subprocess protocol, unified harvest)
still unpicked.
- **Dormant-mode retirement** (`MichaelMode`+`HelicalMode`) — **DONE 2026-07-12**
  (user picked it): −325 more production lines, registry now 7 modes. The
  coordinated 11-file change (2 classes + 4 michael/helical-only helpers +
  MODES/SPECS/state.Literal + every default repointed foils + ~30 test-fixture
  migrations + 3 test rewrites) landed green because the registry lockstep
  turned each omission into a loud KeyError/argparse-reject, not a silent
  wrong-geometry run. michael was the only Categorical space AND the only
  non-surfacecheck preflight, so those special cases died with it. Golden
  harness: 7 survivors byte-identical bar one inert //-comment. Off-repo
  mmackenz_table_plots helical scripts break at `bo.HelicalMode()` (retired
  line, acceptable). Total session size cut now **−673 production lines**.
- **A14** (`cmd_propose` vs `pipeline_io.propose_one` ~25-line shared kernel) —
  still skipped: pinned by `test_audit_fixes.py:268-284` source-regex ordering.

## Cross-links
- Related: [[closed-loop-bo-design]], [[bo-modes]], [[mode-registry-childtracker-design]], [[simplification-audit-2026-07]]
- Incident evidence: [[foilsflash-tarball-mode-key-omission]], [[preflight-mode-tuple-prodtarget6d-omission]], [[foilsg-grid-tarball-scalar-holeradius-fallback]], [[barrier-false-positive-round1]], [[closed-loop-barrier-timeout-zero-rows-falsepos]], [[closed-loop-final-round-orphan-children]], [[foilsx04-all-preflight-ambiguous]], [[closed-loop-stale-cluster-silent-no-launch]], [[preflight-past-init-false-pass]], [[events-per-job-mid-flight-edit]]
- Source files: `pipeline.py:98`, `autoresearch_bo_michael.py:1854`, `graph/config.py:35`, `graph/closed_loop.py:168`, `botorch_predict.py:63`

## Open questions / TODO
- RESOLVED 2026-07-06: user picked candidates 1+2; design crystallized in
  [[mode-registry-childtracker-design]] (+ ADR-0001/0002, root CONTEXT.md).
  The botorch-venv question dissolved: botorch_predict.py:46 already imports
  the driver — only skopt-dependent build_space is off-limits, so bounds as
  plain ModeSpec data need no JSON snapshot.
- Candidates 3-5 (leaderboard schema, typed subprocess protocol, unified
  harvest) remain unpicked.

## 2026-07-11 re-survey (post speed-stack) — new friction, Explore-agent verified

Context: ModeSpec registry (ADR-0002), ChildTracker, and ADR-0001's
`_import_gp` deletion all STILL unimplemented (closed_loop.py:148-171 keeps
_import_gp; mode-scatter widened by foilsflash entries in `_DRY_RUN_KNOB_LABELS`
:734-747). New ranked findings:

1. **cmd_harvest god-function** (pipeline.py:1244-1478): ~11 responsibilities,
   235 lines, implicit 24-key summary dict as the real interface; Steps 5/6/7
   (calo/trk/flash extract) near-copies with 3 fail-soft swallow copies
   (:1355, :932, :1219); 3 of last 4 feature commits landed here; ZERO tests.
2. **CONCATLESS smear** (pipeline.py:82, :386-394 vs :1268-1285): submit half
   keys MaxEventsToSkip=8000 off ENV, harvest half off FILE PRESENCE — the
   env-keyed version already biased ff11R00_07 sob +1.5%; magic 8000 is
   geometry-coupled with no assertion. Fix pattern = stamp stage chain at
   submit (events_per_job precedent).
3. **Winsor flash estimator is DEAD OUTPUT** (pipeline.py:1415-1436 computes +
   :1464 writes; zero readers repo-wide — FoilsFlashMode.extract_metrics
   :1078-1094 still reads the plain mean). Wire-or-delete decision pending.
4. **Picker optimize-budget divergence** (botorch_predict.py): _qnparego_picks
   :392-396 inlines optimize_acqf with copy-pasted budget (num_restarts=16,
   raw_samples=512) — tuning _optimize:246-266 misses qnparego+hybrid; THREE
   min-spacing implementations (0.10 @:484-490 vs CLOSED_LOOP_MIN_PICK_SPACING
   =0.05). Seed/fit/bounds ARE properly shared (_seed/_fit_gp).
5. **[FIXED e7c3e60 2026-07-11] Auxinput-liveness split-brain** (pipeline.py:611-640 probe = fail-open,
   ≤2 files, fndcadoor-regex-only, GATES; pipeline_io.py:305-319 scan = sees
   all, does NOT gate). A door rename recreates the tape-wipeout with both
   defenses green.
6. **Test gap multiplier**: the 2 new picker tests mock _botorch_picks_subprocess
   and assert only the picker STRING forwards; picker math / harvest / tarball
   cache / probe have zero coverage (botorch venv disjoint from test venv).

## 2026-07-11 PROCEEDING on FP-1+FP-2: the Eval-summary module

Decision (user: "review and proceed"): deepen cmd_harvest first, fold the
CONCATLESS stamp in; ModeSpec registry second; ChildTracker third. Winsor
verdict = demote-to-diagnostic (its body comment already said
recorded-not-substituted; only the "Robust decision metric" headline misled —
per-file stats stay, they are the sigma_flash QA data).

Landed NOW (safe mid-campaign — new files only, nothing in flight imports
them): root `harvest.py` (stdlib-only, subprocess-free; parsers incl.
sci-notation, stage-chain stamp owner `stamp_stage_chain`/`stamped_stage_chain`,
presence+stamp `resolve_muminus_inputs`, ONE fail-soft wrapper
`extract_secondary_edep` with injected runner, `per_pot`, winsor diagnostics,
typed `EvalSummary` with additive keys `muminus_source` + `degraded`) +
`tests/test_harvest.py` (26 tests: both incident regressions — sci-notation
parse, concat-presence-beats-env — plus blank-outputs-is-error,
winsor bit-parity with the inline pipeline.py:1421-1436 math, legacy-key
schema pin). All pass.

UPDATE 2026-07-11 ~13:30: user authorized stopping ff14 early ("we can
restart jobs later") — 6/10 R0 rows had already landed (incl. R00_00 3.81 @
8.97e-7 and R00_03 3.76 @ 8.27e-7, both new front points); 4 in-flight
children killed by PID, their clusters left flying, recovery driver walking
them through idempotent verbs + NEW harvest + evaluate. SWITCHOVER APPLIED:
cmd_harvest now delegates to harvest.py (resolve_muminus_inputs, parsers,
extract_secondary_edep for Steps 6/7, per_pot, winsorized_diagnostics,
EvalSummary + degraded record); cmd_submit stamps the stage chain (AFTER the
idempotency guard — no-op submits don't stamp legacy configs);
_materialize_template is stamp-aware. _edep_from_stage_outputs + inline winsor
+ regex defs deleted; constants single-sourced from harvest.py. ADR-0001
EXECUTED (cl_min/_import_gp/GP_SCRIPT_DIR deleted; DEFAULT_PICKER=hybrid; 4
tests rewritten). FP-4 done as budget-constant concentration
(ACQ_NUM_RESTARTS/ACQ_RAW_SAMPLES/ACQ_OPTIONS shared by _optimize +
_qnparego inline; PARETO_SOB_MIN_SPACING named with intent comment —
structural unification rejected: qnparego's per-candidate scalarization +
growing X_pending can't ride _optimize, per its docstring). 119/119 tests;
live --dry-run hybrid q=2 on 254 rows OK. Golden re-harvest of
foilsflash13R00_02: **GOLDEN MATCH — all 26 legacy keys bit-identical**,
additive keys correct (muminus_source="mubeam", degraded={}). The
Eval-summary refactor is fully validated (unit + live dry-run + bit-identical
production re-harvest).

The original gated plan for reference: the pipeline.py
switchover diff — cmd_harvest delegates to harvest.py (Steps 5/6/7 through
extract_secondary_edep; parsers + winsor replaced; summary via EvalSummary),
cmd_submit stamps the stage chain on first submit, _materialize_template
consults the stamp instead of module-global CONCATLESS. Validation = re-run
`pipeline.py --config foilsflash13R00_02 harvest` post-switchover and diff
summary.json against the frozen golden
`<GRID>/foilsflash13R00_02/harvest/summary.json.pre-evalsummary-refactor`
(expect identical except additive keys muminus_source/degraded). EdepAna/sensitivity subprocess steps stay in pipeline.py this pass
(phase 2 candidate: runner-seam them too).
