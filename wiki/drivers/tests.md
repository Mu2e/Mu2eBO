---
type: driver
title: Self-tests (`tests/`)
description: '`tests/` regression suite (12 files, 196 tests; test_wal_multiwriter_stress.py
  is a manual stress script with 0 TestCase), no grid contact; `PYTHONPATH=
  .venv/bin/python -m unittest discover -s tests -v`; golden parity harness
  (manual, not in discover): `PYTHONPATH= .venv/bin/python tests/golden_parity.py check`'
status: active
timestamp: '2026-07-19'
updated_note: 'tests/schema/protocol round: +4 test files (flock, pipeline_verbs,
  botorch_predict, seam_protocol) + golden_parity.py harness; 156 → 196 tests'
---

# Self-tests (`tests/`)

## Summary
Regression tests for the Python drivers in this project. **12 `test_*.py`
files, 196 tests**, run under the single project `.venv` with no grid contact
(all mocks/tempdirs) — plus `tests/golden_parity.py`, a manually-run byte/
tensor-parity harness (not picked up by `unittest discover`, same convention
as `test_wal_multiwriter_stress.py`). Added 2026-05-29 alongside the
5-finding `/simplify` audit so future refactors that revert the audit fixes
fail loudly; grown since with the foils v2 6D round-trip suite, the shared
env-source helper, the 2026-07-17 reorg, and the 2026-07-19 tests/schema/
protocol round (156 → 196 tests: real-flock coverage, injectable-runner
grid-verb coverage, picker unit tests + a `botorch_ask()` seam smoke, and
typed preflight/evaluate JSON seam tests).

## Key facts
- **Venv & invocation:** `PYTHONPATH= .venv/bin/python -m unittest discover
  -s tests -v` (single project venv since the 2026-07-18 consolidation —
  it carries langgraph AND botorch, so there is no wrong venv anymore).
- **Golden parity harness:** `PYTHONPATH= .venv/bin/python
  tests/golden_parity.py check` (capture with `... capture`) — three
  sections: (a) per-mode `load_history()`→`format_row` round-trip vs the
  live leaderboards (byte-compared, all 6 modes); (b) a deterministic
  history-tensor fingerprint on a frozen `leaderboard_bo_foilsflash.tsv`
  copy (redesigned 2026-07-19 from the original fixed-seed-picks plan —
  the picker itself is non-deterministic at production scale, see
  [hybrid-picker-scipy-abnormal-retry-nondeterminism](/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md);
  golden (b) pins the loader seam only, no optimizer in the loop); (c) a
  preflight+evaluate replay (stdout, rc, obj, and the JSON files) on an
  already-completed config. Not part of the 196 — run manually before/after
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
  - `tests/test_child_tracker.py` (13) — `ChildTracker` behind an injected
    Signals adapter.
  - `tests/test_closed_loop.py` (45) — `graph/closed_loop.py`
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
  - `tests/test_harvest.py` (26) — `harvest.py` parsers, stage-chain
    stamping, `EvalSummary`.
  - `tests/test_input_probe.py` (7) — auxinput liveness probe (FP-5).
  - `tests/test_modes.py` (17) — `ModeSpec` registry; grew +4 in the
    2026-07-19 round (Phase 1 `knob_names`/`knob_fmts`/`metric_cols`
    lockstep spot-checks).
  - `tests/test_nodes.py` (12) — graph node logging/terminating-edge cases.
  - `tests/test_pipeline_verbs.py` (9, NEW 2026-07-19, `d6e9f53`+`0644565`) —
    submit idempotency, stamp-at-submit, poll exit conditions, list-outputs
    gating; the jobsub/subprocess boundary is faked via an injected runner.
  - `tests/test_seam_protocol.py` (11, NEW 2026-07-19, `d07d668`+`4cd61b9`+`6b81a17`) —
    the typed JSON preflight/evaluate seam: `run_preflight`/`run_evaluate`
    reading `state/<cfg>/{preflight_verdict,evaluate_result}.json`; valid
    JSON wins over exit code; crash-with-no-JSON decodes as `ambiguous`.
  - `tests/test_wal_multiwriter_stress.py` (0 `def test_` — a manual WAL
    stress script, tracked but NOT part of the 196; `unittest discover`
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
  parse exception)
- Source files: `tests/test_closed_loop.py`, `tests/test_audit_fixes.py`,
  `tests/test_flock.py`, `tests/test_pipeline_verbs.py`,
  `tests/test_botorch_predict.py`, `tests/test_seam_protocol.py`,
  `tests/golden_parity.py`
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
