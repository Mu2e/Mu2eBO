---
type: driver
title: Self-tests (`tests/`)
description: '`tests/` regression suite (7 files, 156 tests), no grid contact;
  `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v`'
status: active
timestamp: '2026-07-18'
---

# Self-tests (`tests/`)

## Summary
Regression tests for the Python drivers in this project. Two files today;
**68 tests** run in ~1.1 s and require no grid contact (all mocks/tempdirs).
Added 2026-05-29 alongside the 5-finding `/simplify` audit so future
refactors that revert the audit fixes fail loudly; grown since with the
foils v2 6D round-trip suite and the shared env-source helper.

## Key facts
- **Venv & invocation:** `PYTHONPATH= .venv/bin/python -m unittest discover
  -s tests -v` (single project venv since the 2026-07-18 consolidation —
  it carries langgraph AND botorch, so there is no wrong venv anymore).
- **Files:**
  - `tests/test_closed_loop.py` — 22 tests over `graph/closed_loop.py`
    (Pareto hash, route_after_decide, decide_next, assign_names, renew_token,
    predict_picks, _child_is_broken, _build_outer_graph). After the
    2026-05-28 `_import_gp(mode)` refactor (helical/michael/foils), the
    two `TestPredictPicks` fixtures MUST set `state["mode"] = "helical"`
    or `_import_gp` raises KeyError. **`TestRenewToken` (2026-06-01) mocks
    `cl.run_sourced_bash` for getToken** (not `cl.subprocess.run`), since
    getToken now routes through the shared helper; `cl.subprocess.run` is
    mocked only for the `kinit -R` call.
  - `tests/test_audit_fixes.py` — pins the 5 /simplify audit fixes (#1-#5
    on `oksuzian/Mu2eBO`, closed 2026-05-29 in commit `5aeb22d`), PLUS
    `TestFoilsAsymmetric6D` (foils v2 6D `_geom_text`/`parse_geom`
    round-trip, 49-entry vectors) and `TestRunSourcedBash` (5 cases over
    `graph/sourced_bash.py:run_sourced_bash` — success/retry/exhaust/
    banner-blocks-retry/timeout-not-retried; mocks `sb.subprocess.run` +
    `sb.time.sleep`). See [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md).
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
  [bo-driver](/drivers/bo-driver.md), [pipeline](/drivers/pipeline.md)
- Pins fixes for: [events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md) (poll+list-outputs
  SHA-check extension), [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md) (broken-unknown
  parse exception)
- Source files: `tests/test_closed_loop.py`, `tests/test_audit_fixes.py`
- Off-tree under test:
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py:158`

## Open questions / TODO
- No coverage yet for: `bo_driver.HelicalMode` /
  `FoilsMode` (`_geom_text`, `parse_geom` round-trip),
  `pipeline.cmd_submit` topology, `graph/pipeline_io.propose_one`
  end-to-end (only the retry loop's shape is pinned via static check).
  Add when next refactor lands.
