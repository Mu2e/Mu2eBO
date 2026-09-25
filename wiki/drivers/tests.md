---
type: driver
title: Self-tests (`tests/`)
description: '`tests/` regression suite (33 files, 704 tests), no grid contact;
  `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`;
  golden parity harness (manual, not in discover): `PYTHONPATH=
  "$AUTORESEARCH_PYTHON" tests/golden_parity.py check`'
status: active
timestamp: '2026-09-24'
updated_note: 'PR #34 simplification pass, stage 3: suite 726 -> 702;
  test_json_mode_parity.py renamed test_geom_golden_parity.py,
  test_evaluate_generic.py folded into test_json_mode.py, the foils/
  foilsflash mode fixtures deleted (tests read mode_specs/foilsflash.json),
  golden d stored one line per field'
---

# Self-tests (`tests/`)

## Summary
Regression tests for the Python drivers in this project. **33 `test_*.py`
files, 704 tests** (2026-09-24), run under `$AUTORESEARCH_PYTHON` with no grid contact
(all mocks/tempdirs) — plus `tests/golden_parity.py`, a manually-run byte/
tensor-parity harness (not picked up by `unittest discover`, same convention
as `tests/golden_parity.py`). Added 2026-05-29 alongside the
5-finding `/simplify` audit so future refactors that revert the audit fixes
fail loudly; grown since with the foils v2 6D round-trip suite, the shared
env-source helper, the 2026-07-17 reorg, the 2026-07-19 tests/schema/
protocol round (156 → 196 tests), and the same-day slimming round (196 → 211
tests: ChildTracker `STALE_CLUSTER` + launch-failed coverage, harvest.py
Steps 1+4 runner-seam tests, and B0-batch lockstep/seam-protocol tests).

## Key facts
- **`tests/test_no_hardcoded_paths.py` only sees files git tracks**
  (`git ls-files`, `tests/test_no_hardcoded_paths.py:57`). A new file
  carrying a personal path passes the suite until it is staged, then goes
  red at the commit. So run `git add` BEFORE the full suite, never after.
  This bit Phase A Task 1 on 2026-09-24: the new golden
  `spec_dump_baseline.json` held expanded `/exp/mu2e/app/users/<name>/`
  musing and tarball paths. The fix stores them as `${ARTIFACT}/` tokens.
- **Suite size (measured 2026-09-22): 31 `test_*.py`, 676 tests
  (1 skipped by design), ~60 s under `ana 2.8.0`.**
  The per-file breakdown further down is a 2026-07-20 snapshot (12 files /
  211) and has NOT been re-audited — trust these two numbers over it.
  **Superseded (measured 2026-09-24, Phase A Task 9): 34 `test_*.py`, 712
  tests (1 skipped)** — the generic-study refactor's Tasks 1-8 landed new
  test files between 2026-09-22 and today (not re-audited file-by-file
  here), and this task added `tests/test_generic_core.py` (2 tests, the
  gate that generic code never names physics quantities).
  **Superseded again (measured 2026-09-24, Phase A final fix wave): 34
  `test_*.py`, 735 tests (1 skipped), ~85 s.** +23: per-level
  unknown/missing-key table, `${ARTIFACT}` == `paths.artifact()` pins,
  loader edge cases (non-finite numbers, non-string params, relative
  `AUTORESEARCH_STUDY_PATH`) in `tests/test_study.py`; the
  removed-env-var tripwire (`tests/test_botorch_predict.py`,
  `tests/test_surrogate.py`); evaluate keeps the pending row on a format
  failure (`tests/test_json_mode.py`); the STUDY_PATH wiring test, which
  replaced the only test that wrote into the real `mode_specs/`
  (`tests/test_modes.py`); a regex self-test in the gate.
  **Current (measured 2026-09-24, PR #34 simplification pass): 33
  `test_*.py`, 704 tests (1 skipped), ~95 s.** Stages 1-2 took 735 -> 726;
  stage 3 took 726 -> 702 by merging duplicates and deleting checks; the
  unused-step rule (d95f034) added 2 -> 704
  that other tests already imply, keeping each distinct assertion:
  `extract_metrics` is one subTest table
  (`tests/test_json_mode.py`), `TestAxisValue` and
  `TestSingleModeSpecClass` are tables, `TestGenericRows`
  (`tests/test_leaderboard.py`) folded into `TestHistory`.
  File changes: `test_json_mode_parity.py` is now
  **`test_geom_golden_parity.py`** (one test,
  `test_live_spec_renders_the_golden`, is the geometry oracle);
  `test_evaluate_generic.py` is deleted (its refusal assertions live on
  the `test_json_mode.py` evaluate tests; its foilspfbpz metric-key
  mapping is pinned by golden d's `metrics`).
  **Fixtures:** `tests/fixtures/modes/foilsflash.json` (equal to
  `mode_specs/foilsflash.json` but for note/comment strings) and
  `foils.json` are deleted; foilsflash tests load the live
  `mode_specs/foilsflash.json`, and `template.json` is the only mode
  fixture left. `tests/test_modes.py` now ends with its `__main__` guard:
  `TestModeStamping` used to sit after it and never ran under
  `python tests/test_modes.py`.
- **`tools/capture_golden_geom.py` was DELETED 2026-08-22** (slim-down
  audit). Everything below about its skip guard is history, not a live
  recipe: the guard could no longer return True for any mode, so the tool
  skipped its only target and reported success while verifying nothing
  (`--check` → `0 drifted, 0 cosmetic, 1 mode(s) skipped`, rc=0; a bare run
  wrote zero goldens). `ModeSpec.geom` is non-Optional and
  `core/study_compat.py` builds it from the study's own required `geom`
  field (`core/mode_json.py`, which did this before the schema-2 study
  loader landed, was deleted 2026-09-24; replaced by `core/study.py` +
  `core/study_compat.py`), so a Python renderer cannot come back without a
  schema change. **The goldens
  in `tests/fixtures/golden_geom/` are now permanent and must never be
  regenerated** — rebuilding one from the JSON spec turns
  `tests/test_geom_golden_parity.py::test_live_spec_renders_the_golden`
  into a tautology. That test is the surviving oracle: 2026-09-24 merged
  `test_same_geometry_as_python_renderer` and
  `test_production_spec_still_matches_the_golden` into it, since with the
  fixture copy deleted both rendered the same spec.
  `test_golden_still_matches_the_live_python_mode` (always skipped) and
  `test_regeneration_guard_uses_the_registry_not_an_attribute` went with
  the tool. The bullets below are history and name the file by its old
  name, `test_json_mode_parity.py`.
- **`tools/capture_golden_geom.py`'s skip guard was BROKEN and would have
  destroyed the oracle it protects (found + fixed 2026-08-02).** The tool
  re-captures the frozen geometry goldens
  (`tests/fixtures/golden_geom/<mode>_<i>.txt`) that
  `test_json_mode_parity.py` compares JSON-defined modes against, and it is
  supposed to REFUSE any mode with no Python renderer — regenerating those
  from the JSON spec would compare the spec to itself. It detected "has a
  Python renderer" with `hasattr(mode, "_geom_text")`, which is **True for
  every mode alive**: `BOMode` declares `_geom_text` abstract and `JsonMode`
  implements it from the JSON `geom` template. So after foilsflash went
  JSON-only (2026-07-26) the tool reported `0 mode(s) skipped` and a plain
  run would have rewritten all four foilsflash goldens from the spec,
  silently turning that half of the parity test into a tautology. Fixed to
  key on the registry fact `ModeSpec.geom is not None` (non-None ⇔
  JSON-defined, per core/modes.py) — an attribute check can never express
  "no Python renderer" while the ABC declares the method.
- **`--check` also reported false DRIFT** (same fix): it diffed raw text
  while the parity test compares `parse_assignments()`, which drops
  comments and normalizes whitespace. All 4 foilsflash goldens were
  semantically identical to the current render (which is why the suite was
  green) yet `--check` exited 1, making it useless as a gate. It now
  compares the way the test does and reports cosmetic-only differences
  separately. Post-fix: `SKIP foilsflash`, `0 drifted, 0 cosmetic`, exit 0.
- **The identical broken guard was ALSO live in the suite**, at
  `test_json_mode_parity.py::test_golden_still_matches_the_live_python_mode`
  — it reported `ok` for foilsflash instead of `skipped`, so for a
  JSON-only mode it was comparing golden-vs-JSON while its failure message
  still read *"STALE vs the live Python renderer — re-capture it"*: advice
  that, followed, would have destroyed the oracle via the (then also
  broken) tool. Fixed 2026-08-02 by hoisting `has_python_renderer(mode)`
  into `test_json_mode_parity.py` (it owns `GOLDEN`/`SAMPLE_X`/
  `parse_assignments`; the tool imports it, keeping one tool→test
  dependency instead of a cycle) and keying both on it. Skips are now
  symmetric and correct: `foils` runs the staleness test, `foilsflash`
  runs the production-spec test.
- **Two tests added with that fix (428 → 432):**
  `test_production_spec_still_matches_the_golden` makes the coverage the
  broken guard had been providing *by accident* explicit and honest — it
  checks the SHIPPED `mode_specs/<mode>.json` (via `MODES`) against the
  golden, where the sibling `test_same_geometry_as_python_renderer` only
  checks the `tests/fixtures/modes/` copy; editing the production spec's
  geometry off the proven-equal baseline is the mistake that would
  otherwise reach the grid. And
  `test_regeneration_guard_uses_the_registry_not_an_attribute` pins the
  guard itself, asserting `hasattr(m, "_geom_text")` is True even for a
  JSON mode — i.e. that an attribute check can never mean "has a Python
  renderer". Nothing had pinned that invariant, which is why it could
  break in silence for a week.
- **Venv & invocation:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover
  -s tests -t .` (the published cvmfs env `ana 2.8.0` since 2026-08-20; it
  carries langgraph AND botorch, so there is no wrong venv anymore —
  `AUTORESEARCH_VENV=<path>` still selects a writable dev stack).
- **Golden parity harness:** `PYTHONPATH= "$AUTORESEARCH_PYTHON"
  tests/golden_parity.py check [a b c d e]` (capture with `... capture`).
  Since 2026-09-24 every section is one row of the `SECTIONS` table
  (label, compute, baseline, capture writer, capture pre-hook, check-time
  adjustment), and a mismatch prints each differing field (`key.field`).
  (d) `spec_dump_baseline.json` is stored **one line per ModeSpec field**
  (767 -> 163 lines, reformatted from the committed file, not
  re-captured, so its data is still the pre-Phase-A capture);
  `tests/test_golden_parity_harness.py` pins that layout. (c) was
  re-captured 2026-09-24 for the `evaluate_result.json` key change
  (`obj`/`sob`/`calo_or_flash` -> `primary` + `objectives`); `check c`
  first showed that ONLY those keys moved (appended row, rc and preflight
  PASS identical). It runs its own muse setup inside `cmd_preflight`, so
  no muse shell is needed, but it takes ~4 min; the full gate is
  `check a b c d e`. The original
  three sections, as first written: (a) per-mode
  `load_history()`→`format_row` round-trip vs the live leaderboards (byte-compared, all 6 modes); (b) a deterministic
  history-tensor fingerprint on a frozen `leaderboard_bo_foilsflash.tsv`
  copy (redesigned 2026-07-19 from the original fixed-seed-picks plan —
  the picker itself is non-deterministic at production scale, see
  [hybrid-picker-scipy-abnormal-retry-nondeterminism](/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md);
  golden (b) pins the loader seam only, no optimizer in the loop); (c) a
  preflight+evaluate replay (stdout, rc, obj, and the JSON files) on an
  already-completed config. Not part of the unittest suite — run manually before/after
  refactors that touch the schema or the graph↔driver seam.
- **Files (12 `test_*.py`, alphabetical, test-method counts via `grep -c
  "def test_"`):**
  - `tests/test_audit_fixes.py` (40) — pins the 5 /simplify audit fixes (#1-#5
    on `oksuzian/Mu2eBO`, closed 2026-05-29 in commit `5aeb22d`), PLUS
    `TestFoilsAsymmetric6D` (foils v2 6D `_geom_text`/`parse_geom`
    round-trip, 49-entry vectors) and `TestRunSourcedBash` (5 cases over
    `graph/sourced_bash.py:run_sourced_bash` — success/retry/exhaust/
    banner-blocks-retry/timeout-not-retried; mocks `sb.subprocess.run` +
    `sb.time.sleep`). See [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md).
  - `tests/test_botorch_predict.py` (12, NEW 2026-07-19, `1153a42`) —
    `_load_history_tensor` against tmp TSV fixtures (row parsing, width
    guard, sob-only path), seeding (`--round-idx` → `42^idx`), min-spacing
    filters, picks-JSON emit, plus one real GP fit + qNEHVI pick on ~10
    synthetic rows (CPU, seconds; the slowest test in the suite).
  - `tests/test_child_tracker.py` (17, was 13) — `ChildTracker` behind an
    injected Signals adapter; grew in the slimming round (2026-07-19) with
    `STALE_CLUSTER` resolution tests (556ac5c) and
    `test_launch_failed_resolves_immediately_no_grace` (1d37217, pins the
    first-tick-sticky `DEAD_UNRESOLVED` for a Popen-raise child — no
    dead-pid grace, since there's no in-flight process to race).
  - `tests/test_closed_loop.py` (47, was 45) — `graph/closed_loop.py`
    (Pareto hash, route_after_decide, decide_next, assign_names, renew_token,
    predict_picks, _child_is_broken, _build_outer_graph). After the
    2026-05-28 `_import_gp(mode)` refactor (helical/michael/foils), the
    two `TestPredictPicks` fixtures MUST set `state["mode"] = "helical"`
    or `_import_gp` raises KeyError. **`TestRenewToken` (2026-06-01) mocks
    `cl.run_sourced_bash` for getToken** (not `cl.subprocess.run`), since
    getToken now routes through the shared helper; `cl.subprocess.run` is
    mocked only for the `kinit -R` call.
  - `tests/test_flock.py` (4, NEW 2026-07-19, `b54b4d9`) — real `flock`
    acquisition on tmp files: `_flock_ex`/`_flock_sh` acquire/release/
    contention and the `_lock_path` anchor. Closes the gap that let the
    2026-07-17 lock-relocation seam break with the (then 158-green) suite
    still passing (see [simplification-audit-2026-07](/concepts/simplification-audit-2026-07.md)).
  - `tests/test_harvest.py` (32, was 26) — `harvest.py` parsers, stage-chain
    stamping, `EvalSummary`; grew +6 in the slimming round (2026-07-19,
    commit 1809635) for `run_edepana`/`run_sensitivity_macro` (Steps 1+4
    runner seams moved out of `cmd_harvest`): success, nonzero-rc
    `SystemExit` with log path, and unparseable-output parse for each.
  - `tests/test_input_probe.py` (7) — auxinput liveness probe (FP-5).
  - `tests/test_modes.py` (18, was 17) — `ModeSpec` registry; grew +4 in
    the tests/schema/protocol round (Phase 1 `knob_names`/`knob_fmts`/
    `metric_cols` lockstep spot-checks), +1 in the slimming round's B0
    batch (704682c, `test_format_row_rejects_non4_metric_tail`; the same
    commit re-pinned the lockstep test to `ValueError` instead of a bare
    `assert`).
  - `tests/test_nodes.py` (12) — graph node logging/terminating-edge cases.
  - `tests/test_pipeline_verbs.py` (9, NEW 2026-07-19, `d6e9f53`+`0644565`) —
    submit idempotency, stamp-at-submit, poll exit conditions, list-outputs
    gating; the jobsub/subprocess boundary is faked via an injected runner.
  - `tests/test_seam_protocol.py` (13, was 11, NEW-file 2026-07-19,
    `d07d668`+`4cd61b9`+`6b81a17`, +2 in the same-day slimming round's B0
    batch `704682c`) — the typed JSON preflight/evaluate seam:
    `run_preflight`/`run_evaluate` reading
    `state/<cfg>/{preflight_verdict,evaluate_result}.json`; valid JSON
    wins over exit code; crash-with-no-JSON decodes as `ambiguous`; B0
    added a stale-`evaluate_result.json`-not-reused case (symmetric to the
    preflight stale test) and the out-of-domain preflight rc→`ambiguous`
    fallback.
  - `tests/test_wal_multiwriter_stress.py` REMOVED 2026-08-19 (`be70827`) with the checkpointer (was: 0 `def test_` — a manual WAL
    stress script, tracked but NOT part of the 211; `unittest discover`
    picks up the file but finds no `TestCase`).
- **Off-tree module import recipe.** `gp_predict_helical.py` lives at
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/`
  (NOT in this git repo). To unit-test it, load via
  `importlib.util.spec_from_file_location("gp_predict_helical", path)`
  + `spec.loader.exec_module(mod)`. `setUpClass` should
  `raise unittest.SkipTest(...)` if the path is unavailable.
- **`@functools.lru_cache` test pollution gotcha.** `_is_broken` in
  `gp_predict_helical.py` is `@functools.lru_cache(maxsize=None)`. If
  multiple test methods stage different `scan_logs/report.tsv` contents
  under the **same** config name, the first call's return value is
  cached and all subsequent calls see stale results — `mock.patch.object(
  GRID_DATA_ROOT)` cannot override a cached call. Two-line fix:
    1. `setUp` calls `self.gp._is_broken.cache_clear()`,
    2. each test uses a unique config name (`cfg_parse_err`, `cfg_clean`,
       `cfg_overlap`, ...).
- **`_check_stage_config_sha` contract test pattern.** To exercise the
  helper in isolation:
    ```python
    mock.patch.object(pipeline, "STATE", tmp)
    mock.patch.dict(pipeline.STAGES, {"poke": {"events_per_job": 1}},
                    clear=False)
    pipeline._stamp_stage_config_sha("poke")    # write stamp
    pipeline.STAGES["poke"]["events_per_job"] = 2  # mutate after stamp
    # capture stderr — helper warns "WARN ... poke ..." and returns
    ```
  The helper writes to stderr and never raises; callers
  (`cmd_poll`/`cmd_list_outputs`/`cmd_harvest`) depend on that no-raise
  contract.
- **Static-source-pattern asserts** (regex on the file text instead of
  importing) are intentional in 6/15 audit tests: they cheaply pin
  argparse `choices=[...]`, ordering of `remove_pending` vs
  `append_history`, presence of `_check_stage_config_sha` at the top of
  `cmd_poll`/`cmd_list_outputs`, and the `MAX_RETRY = 20` literal —
  WITHOUT pulling skopt/langgraph/sqlite into the test import graph.
- **Audit-guard regex needs updating when a new `--mode` is added
  (2026-06-05).** `tests/test_audit_fixes.py:113`
  `test_argparse_choices_includes_three_modes` hardcodes the regex
  `r'choices\s*=\s*\[\s*"helical"\s*,\s*"michael"\s*,\s*"foils"\s*\]'`
  against `graph/closed_loop.py`. When `foilsf` was added as a 4th mode
  at `graph/closed_loop.py:636` (now `choices=["helical","michael","foils","foilsf"]`),
  the regex stopped matching — test fails with `unexpectedly None`. The
  guard's *intent* is "reject typos like `helcial`" (covered by
  `test_argparse_rejects_typo` below it), so the fix is to broaden the
  regex to allow trailing modes, NOT to revert the choices list. Same
  trap will recur for any future mode addition.

## Cross-links
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md), [graph-runner](/drivers/graph-runner.md),
  [bo-driver](/drivers/bo-driver.md), [pipeline](/drivers/pipeline.md),
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md),
  [hybrid-picker-scipy-abnormal-retry-nondeterminism](/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md)
  (golden (b) design context)
- Pins fixes for: [events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md) (poll+list-outputs
  SHA-check extension), [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md) (broken-unknown
  parse exception), [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)
  (`test_child_tracker.py` STALE_CLUSTER tests, `test_closed_loop.py`
  all-stale-round tests)
- Related: [mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md)
- Source files: `tests/test_closed_loop.py`, `tests/test_child_tracker.py`,
  `tests/test_audit_fixes.py`,
  `tests/test_flock.py`, `tests/test_pipeline_verbs.py`,
  `tests/test_botorch_predict.py`, `tests/test_seam_protocol.py`,
  `tests/test_harvest.py`, `tests/golden_parity.py`
- Off-tree under test:
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py:158`

## Open questions / TODO
- RESOLVED 2026-07-19: `pipeline.cmd_submit` topology (idempotency,
  stamp-at-submit, poll exit, list-outputs gating) now covered by
  `tests/test_pipeline_verbs.py`; the picker/`botorch_predict.py` gap by
  `tests/test_botorch_predict.py`; the flock seam by `tests/test_flock.py`.
  (`HelicalMode` is retired code as of 2026-07-12, so its old gap is moot.)
- Still no coverage for: `graph/pipeline_io.propose_one` end-to-end (only
  the retry loop's shape is pinned via static check).
- RESOLVED 2026-07-19 (slimming round, Task 5 — the "test_closed_loop
  acrobatics shrink" the design page's follow-up list flagged): audited
  `test_closed_loop.py`'s barrier/launch test classes against the
  injected-fake `test_child_tracker.py` coverage the tracker full-cut
  added — verdict **keep-all** (18 tests audited, none are pure
  tracker-level duplicates; each also pins closed_loop-side wiring —
  `_DiskSignals` binding, error-message routing, state plumbing). No
  commit (audit found nothing to shrink).
- Recorded follow-up (slimming round): `pipeline.py` and `harvest.py`
  duplicate the harvest log-path literals (`edep.log`,
  `rough_run1a_sensitivity.log`) rather than `harvest.py`'s runner
  functions returning the path they wrote — a return-the-path candidate
  for a future pass, not filed as a bug.
