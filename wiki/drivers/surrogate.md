---
type: driver
title: Surrogate package + MCP server
description: '`surrogate/` = the MCP door onto surrokit: `adapter.py` + `mcp_server.py` stdio wrapper; `mcp` 2.0 ships in ana 2.8.0; the plain-Python facade was deleted 2026-09-22'
status: active
timestamp: '2026-10-08'
---

# Surrogate package + MCP server

## Summary
`surrogate/` is the **MCP door** onto the GP surrogate (the project's fast
sim — see [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md)).
`adapter.py` (`AutoresearchAdapter` — `problems`/`history`/`suggest` over
`modes.STUDIES`) and `mcp_server.py` (`make_server(AutoresearchAdapter())`
on stdio). The GP and pickers live in **surrokit**, a sibling repo;
`core/botorch_predict.py` is thin glue over `surrokit.ask`. Any Claude
session can query the surrogate as tools without importing the codebase.
Agreed with Simon Corrodi 2026-08-28 (Ray to add an auth/logging layer
later via `MCPServer(middleware=[...])`).

## Surrokit extraction (2026-08-28)
- Engine repo: sibling checkout `../surrokit` (env `AUTORESEARCH_SURROKIT`,
  `core/paths.py:SURROKIT_ROOT`). The pin is `core/paths.py:SURROKIT_PIN_SHA`
  and the suite asserts the checkout matches it; bump on purpose, after
  re-validating. Read the pin there, not from this page.
- All picker bodies moved to surrokit. `core/botorch_predict.py` keeps only
  glue: history loading, the `-log10` transform, `build_problem`, the
  `42^round_idx` seed, `compute_explore_picks` over `surrokit.ask`.
- MCP tools were renamed at the move: `list_modes` -> `list_problems`,
  `board_stats` -> `stats`; `refit` is new.

## Facade deletion (2026-09-22)
- The importable facade (`fit`/`predict`/`suggest`/`board_stats`/
  `modes_info` in `surrogate/__init__.py`) had zero callers in a repo-wide
  and off-repo sweep, and was deleted. Its champion + sob-range summary
  survives as `adapter._board_summary` (the `stats` tool). Plain-Python
  clients import `core/botorch_predict.py` (`build_problem`,
  `load_history_tensor`, `compute_explore_picks`).

## Key facts

- **A refused pick request is a `ValueError`, never `SystemExit`**
  (2026-10-05). The MCP SDK turns an `Exception` in a tool into a tool
  error, but `SystemExit` escaped and took the whole server down.
  `core/botorch_predict.py` raises `ValueError` for an unknown study, a
  history/knob width mismatch, `budget_sob` on a study with no constraint,
  and an infeasible budget. In `graph.closed_loop` the same error stops the
  campaign with a traceback.
- **Grid-validated 2026-08-29**: campaign `foilspfSK01` (the old
  pipeline's `foilspf` study, picker `budget_sob`, q=3) ran the surrokit
  path (`build_problem` -> `constrained_max`) on the grid: 3/3 rows, best
  sob 4.08 at flash 6.00e-7. MCP `list_problems` showed `n_rows` 90 -> 93
  without a restart (row-count fit-cache key).
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
- MCP tool names: `list_problems`, `predict`, `suggest`, `stats`, `refit`.
- `predict` output axes are returned **raw**, one per study objective in
  study order — the scaffold's generic tool gives `mean`/`sigma` per axis
  and nothing else. The linear-units inversion with a 1-sigma interval went
  away with the facade (2026-09-22); clients invert a `log10`-transform
  axis with `10**(-mean)` and read the axis label (e.g. `-log10(flash_edep)`)
  from `stats`'s `objectives[i].axis`.
- **`stats` meta is built entirely from the study (Phase A, 2026-09-24)**:
  `objectives` — one dict per study objective, `{name, direction,
  transform, axis}` (`axis` is the direction/transform-aware label, e.g.
  `sob` or `-log10(flash_edep)`); `knobs` — one dict per study knob,
  `{name, type, unit, min, max}`; `knob_names`; `leaderboard`. Plus, from
  `adapter._board_summary` (keyed on the study's first/primary objective,
  direction-aware max-or-min pick): `best` (`{config, x, values}`, where
  `values` is `{name: value}` for every objective and extra metric at the
  champion row) and `primary_range` (`[min, max]` of the primary objective
  over finite rows). The values are NESTED, not spread beside `config`/`x`:
  an objective a study legally names `x` or `config` would otherwise
  overwrite the knob vector or the config name. The MCP server
  `instructions` string describes this shape too. These replace the old
  ModeSpec-era `best_sob`/`sob_range` keys and the `objectives: ["sob",
  "neg_log10_<metric>"]` string list. The config NAME is why
  `_board_summary` re-reads the board (`load_history_tensor` keeps only
  X/Y).
- Registered in `.mcp.json` (repo root): command is the absolute ana 2.8.0
  python, args `["surrogate/mcp_server.py"]`, stdio transport.
## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (v2 boards the
  same `core/botorch_predict.py` history reads also serve), [tests](/drivers/tests.md)
- Concepts: [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md), [budget-sob-picker](/concepts/budget-sob-picker.md), [gp-free-noise-erases-champion fix carried via obs_noise](/incidents/gp-free-noise-erases-champion.md)
- External: [mu2e-cvmfs-python-envs](/external/mu2e-cvmfs-python-envs.md)
- Source files: `surrogate/adapter.py`, `surrogate/mcp_server.py`, `tests/test_surrogate.py`, `.mcp.json`

## Open questions / TODO
- Ray's auth/logging middleware layer (future; `MCPServer(middleware=[...])`).
- Consider exposing the GP over HTTP (`server.run("streamable-http")`) if a
  non-local client appears; stdio covers everything today.
