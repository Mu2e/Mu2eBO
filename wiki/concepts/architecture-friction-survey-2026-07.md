# Architecture friction survey (2026-07)

**Type:** concept
**Status:** active
**Updated:** 2026-07-06

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

## Cross-links
- Related: [[closed-loop-bo-design]], [[bo-modes]]
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
