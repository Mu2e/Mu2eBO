---
type: driver
title: Surrogate package + MCP server
description: surrogate/ — the MCP door onto surrokit (the extracted ask/tell engine): AutoresearchAdapter + a thin mcp_server.py stdio wrapper (official mcp SDK 2.0, ships in ana 2.8.0); the importable plain-Python facade was deleted 2026-09-22
status: active
timestamp: '2026-09-22'
updated_note: facade deleted (zero callers); board summary ported into adapter meta
---

# Surrogate package + MCP server

## Summary
`surrogate/` is the **MCP door** onto the GP surrogate (the project's fast
sim — see
[fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md)). Two files
carry it: `adapter.py` (`AutoresearchAdapter` — `problems`/`history`/
`suggest` over the ModeSpec registry) and `mcp_server.py`
(`make_server(AutoresearchAdapter())` on stdio). The importable
plain-Python facade that also lived here — `fit`/`predict`/`suggest`/
`board_stats`/`modes_info` — was **DELETED 2026-09-22**; see "Facade
deletion" below. Underneath, the actual GP + picker logic now lives in **surrokit**, a sibling
engine repo extracted from this project's picker bodies (`asktell` renamed
`surrokit` mid-extraction per the 2026-08-28 `/grill-with-docs` spec session);
`core/botorch_predict.py` is thin glue (history loading, the `-log10`
transform, env-tunable constants, the `42^round_idx` seed convention) that
calls `surrokit.ask` directly, and the adapter shapes that glue for the MCP
scaffold. Neither this package nor `core/botorch_predict.py` contains a picker implementation any
more — see "Surrokit extraction" below. `surrogate/mcp_server.py` is a thin MCP
adapter over that same glue, so any Claude/LLM session can query the
surrogate as tools without importing the codebase. Agreed with Simon Corrodi
2026-08-28 (package seam + thin MCP wrapper; Ray to add an auth/logging layer
later — plugs into `MCPServer(middleware=[...])` without touching the tools).

## Surrokit extraction
- Engine repo: `/exp/mu2e/app/users/oksuzian/surrokit` (sibling checkout,
  NOT nested under this repo). Env seam `AUTORESEARCH_SURROKIT`
  (`core/paths.py:45 SURROKIT_ROOT`), default `../surrokit` relative to
  `REPO_ROOT`.
- **Pinned SHA: `4884aa662ff9f2bdb3a6ff54b93f0b1ee53e35ab`** ("docs: README
  states engine scope, Constraint semantics, adapter problem set",
  2026-08-28 line, verified 2026-09-22). The pin lives at
  `core/paths.py:51 SURROKIT_PIN_SHA` and the suite asserts the checkout
  matches it; bump DELIBERATELY after re-validating. (This page carried the
  stale `0a094421` through three pin bumps — read paths.py, not this line.)
- **The old picker bodies are DELETED from `core/botorch_predict.py`**
  (2026-08-28, refactor commit "delete picker bodies ported to surrokit"):
  `_sampler`, `ACQ_NUM_RESTARTS`/`ACQ_RAW_SAMPLES`/`ACQ_OPTIONS`,
  `SOB_CORNER_MIN_SPACING`, `_optimize`, `_sobol_cold_start`, `_fit_gp`,
  `_qnehvi_picks`, `_qlnei_picks`, `_qnparego_picks`, `_hybrid_picks`,
  `_emit_picks`, `_budget_sob_picks` are all gone. What remains in that
  module: module header/dtype setup, `_load_history_tensor`, `_seed`,
  `DEP_FLASH_PER_POT`, `BUDGET_SOB_K_SIGMA`, the surrokit import block,
  `compute_explore_picks`, `main`. `compute_explore_picks` is pure glue
  over `surrokit.ask`/`surrokit.Problem`/`surrokit.Constraint`.
- **Parity-gate result (retired, not re-run)**: at the Task 8 rewire commit
  (`e52a741`, "compute_explore_picks delegates to surrokit.ask") all 6
  comparisons were bit-identical on the 10-row fixture — qnehvi,
  qnehvi+round3+pending, qlnei sob-only, hybrid, budget_sob-as-
  constrained_max, cold start. The gate (`tests/test_surrokit_parity.py`)
  was then deleted at that same commit: past that point the comparison is
  self-vs-self (both sides call `surrokit.ask`), so it stopped being able to
  catch anything.
- **MCP tool renames**: `list_modes` -> `list_problems`, `board_stats` ->
  `stats`; `refit` is new (forces a fit-cache refresh — see
  `surrogate/mcp_server.py` docstring). `suggest` now calls `surrokit.ask`
  directly rather than going through the old `compute_explore_picks`
  picker-name switch.
- Tests that exercised the deleted internals directly were removed from
  `tests/test_botorch_predict.py` in the same commit (their surrokit-side
  ports exist in the surrokit repo's own suite since its Tasks 2-5):
  `test_emit_picks_native_types_and_int_rounding`,
  `test_sobol_cold_start_deterministic_and_in_bounds`,
  `test_obs_noise_reaches_the_likelihood`,
  `test_pinned_noise_does_not_shrink_a_high_observation`,
  `test_budget_sob_picks_respect_the_damage_constraint`,
  `test_budget_sob_refuses_when_nothing_is_feasible`. What's KEPT is the
  glue's regression net: `_load_history_tensor`, `_seed`,
  `compute_explore_picks`, and the CLI (JSON emit, seam smoke via
  `bo.botorch_ask`).

## Facade deletion (2026-09-22)
- `surrogate/__init__.py` exposed `fit`/`predict`/`suggest`/`board_stats`/
  `modes_info` as a "published plain-Python seam" per the 2026-08-28
  agreement with Simon Corrodi. Four weeks on, a repo-wide **and** off-repo
  sweep (mmackenz_table_plots, autoresearch_{tools,benchmarks,local,grid},
  autoresearch2, mcp/, aitools, prodtools, mu2e-review, both `.claude`
  trees, cron, bin, EAF, the surrokit checkout, crontab) found **zero
  callers** — only its own test file. It was deleted.
- 4 of its 5 functions twinned what `surrokit.mcp_scaffold.make_server`
  generates, including a byte-identical row-count fit cache. Its tool names
  were also the pre-surrokit ones the MCP door had already renamed.
- What survived the cut: `board_stats`'s champion + sob-range body, now
  `adapter._board_summary`, surfacing through the MCP `stats` tool. What
  did NOT: `predict`'s inverse-log10 reporting (see Key facts).
- `__init__.py` is now a package marker holding this record. Plain-Python
  clients should import `core/botorch_predict.py` directly —
  `build_problem` + `load_history_tensor` + `compute_explore_picks` are the
  same seam the adapter and the closed loop use.
- Suite after the cut: **676 tests green** (1 skipped) under ana 2.8.0;
  9 facade tests removed, 1 added for the ported summary.

## Key facts

- **Grid-validated 2026-08-29**: `foilspfSK01` (`--mode foilspf --picker budget_sob --q 3`) ran the surrokit path (`build_problem` -> `constrained_max`) through the real grid: 3/3 rows, ~4 h wall each, best `R00_00` sob 4.08 @ flash 6.00e-7 (ties the line's best-under-budget). MCP `list_problems` showed `n_rows` 90 -> 93 without a restart (row-count fit-cache key).
- **Zero new dependencies**: the official `mcp` SDK **2.0.0 ships in ana
  2.8.0** (the default `$AUTORESEARCH_PYTHON`), including the FastMCP-style
  API at `mcp.server.mcpserver.MCPServer` (`@server.tool()` decorator,
  `server.run("stdio")`, `middleware=` hook). The dev `.venv` does NOT have
  it (tests skip the adapter check there); `fastmcp` proper is nowhere and
  not needed.
- `structured_output=True` requires TYPED return annotations — a bare `dict`
  return raises `InvalidSignature: return type <class 'dict'> is not
  serializable`; `dict[str, Any]` / `list[dict[str, float]]` work. Results
  then arrive in `CallToolResult.structured_content` (snake_case in mcp 2.0;
  list returns are wrapped under key `"result"`).
- **Library prints cannot corrupt stdio JSON-RPC**: mcp 2.0's stdio server
  claims fd 1 and diverts `sys.stdout` for the whole process (their issue
  #1933 fix) — botorch_predict's chatty `print(..., flush=True)` lines are
  safe unmodified.
- Fit cache is keyed on leaderboard **row count** (append-only board, so
  same count == same history); a long-lived server picks up new evals on the
  next call; `refit` tool forces a refresh.
- MCP tool names as currently registered: `list_problems`, `predict`,
  `suggest`, `stats`, `refit` (renamed from the pre-surrokit adapter's
  `list_modes`/`board_stats` — see "Surrokit extraction" above).
- `predict` output axis 1 is `-log10(metric2)` and is returned **raw** —
  the scaffold's generic tool gives `mean`/`sigma` per axis and nothing
  else. The linear-units inversion with a 1-sigma interval went away with
  the facade (2026-09-22); clients invert with `10**(-mean)` and read the
  axis names from `stats`'s `objectives`.
- **`stats` carries the board summary**: the scaffold's `stats` is
  `n_rows` + whatever `adapter.history()` puts in meta, so
  `adapter._board_summary` rides there — `best_sob` (config name, x, sob,
  metric2) and `sob_range`. This is the ported body of the deleted
  `board_stats`, and the config NAME is why it re-reads the board
  (`load_history_tensor` keeps only X/Y).
- Registered in `.mcp.json` (repo root): command is the absolute ana 2.8.0
  python, args `["surrogate/mcp_server.py"]`, stdio transport.
- Validated 2026-08-28: 10 unit tests + full 685-test suite green under ana
  2.8.0; live round-trip via `stdio_client`+`ClientSession` — foilspf
  champion foilspf04R01_00 board sob=4.75/flash=1.458e-6 vs GP posterior at
  the same x 4.750±0.006 / 1.459e-6; `budget_sob` suggest returns
  in-budget picks.

## Cross-links
- Related: [bo-driver](/drivers/bo-driver.md), [closed-loop-runner](/drivers/closed-loop-runner.md), [tests](/drivers/tests.md)
- Concepts: [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md), [budget-sob-picker](/concepts/budget-sob-picker.md), [gp-free-noise-erases-champion fix carried via obs_noise](/incidents/gp-free-noise-erases-champion.md)
- External: [mu2e-cvmfs-python-envs](/external/mu2e-cvmfs-python-envs.md)
- Source files: `surrogate/adapter.py`, `surrogate/mcp_server.py`, `surrogate/__init__.py` (package marker + deletion record), `tests/test_surrogate.py`, `.mcp.json`

## Open questions / TODO
- Ray's auth/logging middleware layer (future; `MCPServer(middleware=[...])`).
- Consider exposing the GP over HTTP (`server.run("streamable-http")`) if a
  non-local client appears; stdio covers everything today.
