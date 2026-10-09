---
type: driver
title: Self-tests (`tests/`)
description: '`tests/` regression suite (44 files, 935 tests OK, 4 skipped), no grid contact; `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`'
status: active
timestamp: '2026-10-09'
---

# Self-tests (`tests/`)

## Summary
Regression tests for the engine, the kit adapters, the service and the
surrogate. **44 `test_*.py` files, 935 tests OK (skipped=4)** after the
2026-10-08 cleanup and the four review fixes (PR #37), about 9 minutes under `ana 2.8.0`. No grid
contact: everything runs on mocks, temp dirs, fake kits
(`tests/toykit.py`, `tests/fakeanakit.py`, `tests/fakebeamkit.py`), or a
temp `AUTORESEARCH_DATA_ROOT`.

## Key facts
- **Run it:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s
  tests -t .` (`$AUTORESEARCH_PYTHON` is the cvmfs `ana 2.8.0` env since
  2026-08-20; `AUTORESEARCH_VENV=<path>` still picks a writable dev stack).
- **Engine subprocess tests write nowhere real.** `test_run.py` and
  `test_closed_loop.py` start `graph.run` / `graph.closed_loop` with
  `AUTORESEARCH_DATA_ROOT` set to a per-test temp dir
  (`tests/engine_fixtures.py:engine_env`). They are most of the wall time.
- **Skips are environment checks**, not broken tests: no `.venv`, no
  `/cvmfs`, no anakit or surrokit git checkout, no real prodtools servers
  (`test_activate.py`, `test_setup_sh.py`, `test_anakit_kit.py`,
  `test_botorch_predict.py`, `test_prodtools_adapter.py`).
- **`tests/test_no_hardcoded_paths.py` only sees files git tracks**
  (`git ls-files` over `SCANNED`: `core`, `graph`, `surrogate`, `tests`,
  `mode_specs` plus `setup.sh`, `activate.sh`, `README.md`,
  `requirements.txt`, `CONTEXT.md`, `CLAUDE.md`). A new file with a personal
  path passes until it is staged, then fails at the commit. Run `git add`
  BEFORE the full suite. Store paths as `${ARTIFACT}/` tokens.
- **The geometry goldens in `tests/fixtures/golden_geom/` are permanent —
  never regenerate them.** They were captured from the Python renderer
  before it was deleted (2026-07-26). `tests/test_geom_golden_parity.py`
  checks that the live `foilsflash_ax` study renders the same geometry
  (semantic compare, not bytes). Rebuilding a golden from the JSON spec
  would make that test compare the spec to itself.
- **`tests/test_sourced_bash.py`** pins
  `core/adapters/preflight_checks.py:run_sourced_bash` (retry, give-up,
  banner-blocks-retry, timeout-not-retried); see
  [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md).
- **The suite can hang with no output** on a stale torch extension lock:
  see [torch-cpp-extension-stale-filebaton-suite-hang](/incidents/torch-cpp-extension-stale-filebaton-suite-hang.md).

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (what the engine
  tests cover), [service](/drivers/service.md),
  [surrogate](/drivers/surrogate.md),
  [pipeline](/drivers/pipeline.md) (deleted; its tests went with it)
- Source files: `tests/engine_fixtures.py`, `tests/test_run.py`,
  `tests/test_closed_loop.py`, `tests/test_no_hardcoded_paths.py`,
  `tests/test_geom_golden_parity.py`

## Open questions / TODO
