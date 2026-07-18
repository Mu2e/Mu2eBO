---
type: driver
title: graph-runner — LangGraph orchestrator for the BO loop
description: LangGraph state-machine orchestrator (Phase 1 mock-grid); Studio +
  Streamlit overlay
status: active
timestamp: '2026-07-08'
updated_note: headless-log format gotcha
---

# graph-runner — LangGraph orchestrator for the BO loop

> **Monitoring gotcha (2026-07-08):** a headless `graph.run` log contains ONLY
> `[run] {...}` JSON status lines (config_name / preflight / objective) — node
> names like `propose` / `render_preflight` / `stage_mubeam` never appear, so
> log-grep monitors keyed on node names silently never fire (foilsflashSOBX01:
> preflight had passed while a `grep "propose|render_preflight"` watcher was
> still waiting). Watch the JSON fields (`"preflight": "pass"`), the
> `state/<cfg>/*_cluster.txt`/`*_outputs.txt` files, or the leaderboard row —
> not node names.

## Summary
LangGraph runner that replaces the manual `propose → preflight → submit → poll
→ harvest → evaluate` script chain with a state-machine graph. Provides
checkpointed iteration state, visual step-through in LangGraph Studio, and a
Streamlit read-only overlay (leaderboard, threads, GP surface). Phase 2b ships
the real four-stage grid path (one node per stage) alongside the Phase 1
mock-grid branch; helical mode only.

## Key facts
- **Code**: `graph/{state,nodes,pipeline_io,build,config,run}.py` + `graph_app/streamlit_app.py`.
- **Topology (Phase 2b + scan_logs)**: `START → propose → render_preflight →
  {stage_mubeam → stage_run1b_mubeam → stage_concat → stage_mustops_ce → harvest → scan_logs, OR mock_grid}
  → evaluate → decide_next → END`. Mock path bypasses `scan_logs` (no grid
  logs exist). Each `stage_X` node calls
  `pio.run_stage(cfg, X)` which shells out to `pipeline.py --config CFG submit|poll|list-outputs X`
  in series. `route_after_stage` (between every pair of stages) terminates the
  iteration on the first stage that returns `status="failed"`, so `evaluate`
  never runs with partial metrics.
- **Mode-aware stage chain (Mu2eBO #15, 2026-06-07):** `config.GRID_STAGES`
  is selected from `GRID_STAGES_BY_MODE` at module-load time via
  `os.environ.get("AUTORESEARCH_MODE","michael")`. `build.STAGE_NODES` and
  `build.build_graph()` freeze that selection at import time, so the env var
  MUST be stamped BEFORE `from config import …`. Both `graph/run.py` and
  `graph/closed_loop.py` have a `_presniff_mode()` that scans `sys.argv` for
  `--mode foo` / `--mode=foo` and stamps `AUTORESEARCH_MODE` before the
  config import — argparse runs in `main()` which is too late. Forgetting
  this stamp = silent fallback to michael's 4-stage chain regardless of
  `--mode` value. `prodtarget` → `["pot_only"]`; all others (michael,
  helical, foils, foilsf) → the 4-stage CE chain. Harvest verb also
  dispatches: `HARVEST_VERB_BY_MODE["prodtarget"] = "harvest-pot-only"`
  (others use `"harvest"`); `pio.run_harvest(name, mode=…)` picks the verb.
- **Per-stage idempotency lives in pipeline.py, not in the graph node.** Re-entering
  `stage_X` after a checkpoint kill or a hot-reload re-runs submit/poll/list-outputs;
  pipeline.py's submit/list-outputs guards no-op when the cluster file already
  exists (and, for list-outputs, every basename in `<stage>_outputs.txt` still
  resolves on /pnfs). Override with `--force`. See [pipeline](/drivers/pipeline.md).
- **Idempotency corollary — rebuilt base tarballs are invisible on resubmit.**
  `write_code_tarball` (`pipeline.py:387-423`) re-extracts `MUSING_BY_MODE`'s
  base tarball into `<stage>/Code/` every time submit runs, BUT submit itself
  no-ops if `state/<stage>_cluster.txt` exists. So a graph.run that picks up
  an old cluster.txt also harvests the prior grid outputs, which were built
  against the *previous* base tarball. Symptom on pt001 (2026-06-08): rebuilt
  `Code_MDC2025aq_prodtarget.tar.bz2` (15:03, ships `ProductionTargetEdepHist`
  .so) was ignored; harvest read 100 stale files, all reported zero edep,
  leaderboard row landed as `edep_per_POT_MeV=nan`. Fix: wipe
  `<workdir>/state/<stage>_cluster.txt` AND `<workdir>/state/<stage>_outputs.txt`
  AND `<workdir>/harvest/summary.json` (so the next harvest re-runs). The
  `<workdir>/<stage>/` directory holds only tarball artifacts (`Code.tar.bz2`,
  `Code/`, `cnf.*.tar`); wiping those alone does NOT clear the gating
  state — that lives in `state/`, a separate sibling dir. **Wrong-dir wipe
  trap**: I burned a 4-min preflight cycle on 2026-06-08 wiping
  `<workdir>/pot_only/` thinking it held the cluster file; the file is
  actually at `<workdir>/state/pot_only_cluster.txt`. Confirm with
  `ls <workdir>/state/<stage>_*.txt` before wiping.
- **`langgraph dev` hot-reload is hostile to long-running subprocess nodes.**
  The dev server watches `graph/` and SIGKILLs the worker on file change, mid-`subprocess.run`.
  graph007 (2026-05-19) suffered three double-submits of `stage_mubeam` because
  successive edits during the run aborted the in-flight verb between cluster-file
  write and graph state-update. Mitigation: never edit `graph/` while a real-grid
  thread is mid-flight, OR rely on the Phase 2b per-stage idempotency to absorb
  re-entry. The dev server itself has no `--no-reload` flag we've found.
- **Python version**: 3.11+ required for `langgraph dev` (the in-mem server hard-fails on 3.9).
  Venv built with `uv venv --python 3.11 .venv-graph`.
- **uv cache**: `/exp/mu2e/app/users/oksuzian/uv_cache` — `/nashome` quota is too tight
  (~2 GB available) for langgraph's dep tree (grpcio + langchain-core pull >300 MB).
- **State**: `BOIterationState` TypedDict at `graph/state.py`. `stages: Dict[str, StageStatus]`
  is the per-iteration scoreboard; each `StageStatus` has `cluster_id`, `status`,
  `n_done`, `n_failed`, `last_poll_ts`. `STAGE_TARGETS` in `graph/config.py`
  (`mubeam=200, run1b_mubeam=200, concat=1, mustops_ce=200`) drives the
  `n_failed = max(0, target - n_done)` inference in `read_stage_status`.
- **Conditional retry edge** `render_preflight → propose` on `fail_managed` (max 3 attempts).
- **Resume gotcha — same-config_name does NOT recover a stalled chain.** Launching
  a fresh thread_id with `--config-name graphNNN` (where graphNNN already exists in
  leaderboard or pending) triggers `pio.propose_one`'s collision guard
  (`graph/pipeline_io.py:57`); the except branch falls through to
  `next_config_name()` and the iteration silently morphs into a FRESH config
  (`graph022/023/024` minted at the auto-increment boundary). Log signature:
  `[run] {"config_name": "graph018"}` immediately followed by
  `[run] {"config_name": "graph022", "preflight": "pending"}`. The fresh chain
  reuses the passed `--x-point`, so the new config is a noise-replicate of
  the stalled one — not a recovery. **To actually recover a stalled chain**,
  drive `pipeline.py --config <stalled_cfg>` directly for each missing
  stage (per-stage idempotency means submit/poll/list-outputs reuse existing
  `<stage>_cluster.txt` and only re-do the missing tail). Or: delete the
  pending row for `<stalled_cfg>` from the BO mode's pending TSV so propose
  doesn't see a collision (untested 2026-05-20).
- **The collision-silent-rename also fires when you pass `--config-name
  <existing>` from the CLI**, not just on resume (2026-05-23). Passed
  `--config-name helicalQR00_02_ftfp` to relaunch the FTFP_BERT A/B chain
  for the same name as a prior pending row; propose_one raised ValueError,
  the except branch swallowed it, and the iteration silently became
  `graph027`. Same root cause as the resume gotcha above. **Always clear
  the pending TSV row for `<name>` before reusing the name from the CLI
  (or accept that `--config-name` is best-effort, not authoritative).**
- **`--x-point` bypasses `is_buildable` and BOUNDS** (2026-05-25).
  `propose_one` with `x_override` (`graph/pipeline_io.py:61-62`) skips the
  BO `opt.ask()` path, so the N_crit / BOUNDS-rail guards at
  `bo_driver.py:623` (which only fire on BO-asked picks)
  never run. Hand-curated x-points outside `BOUNDS` (e.g. angle > 720°)
  are accepted silently; only G4-build-time pathologies (broken-plug
  scan_logs gate, preflight fail) catch unbuildable picks. **Operator
  consequence**: when forcing x-points outside production BOUNDS, hand-
  check `N_crit = dy·angle_rad/(8·dx) ≤ N_crit budget (2000)` AND
  avoid angle nodes (sin=0 at 180/360/540/720/900) BEFORE launching;
  framework will not save you.
  graph027 == helicalQR00_02 baseline x_point (dx=0.134, dy=117.2,
  halflen=351.2, angle=361) with FTFP_BERT physics list — keep this mapping
  in mind reading the leaderboard.
- **`--config-name` works clean for genuinely-new names** (2026-05-23).
  Counter-example to the silent-rename footgun: launched
  `--config-name helicalQR00_02_noise` (no prior pending row, no leaderboard
  row) and propose_one accepted it without rename. The footgun ONLY fires on
  pre-existing collisions — `--config-name` is safe for fresh names.
- **`.venv-graph` has sklearn/scipy but NO matplotlib AND no pip**
  (`No module named pip` on `python -m pip`). For any plot-generation script
  (`overlay_gp_predictions_helical_mpl.py`, GP cloud regen, etc.) use
  `.venv-botorch/bin/python` — matplotlib 3.9.4 + sklearn 1.6.1 both live
  there. Default mental model "use .venv-graph for everything graph-adjacent"
  is wrong for plotting.
- **Python version**: 3.11+ required for `langgraph dev` (the in-mem server hard-fails on 3.9).
  Venv built with `uv venv --python 3.11 .venv-graph`.
- **uv cache**: `/exp/mu2e/app/users/oksuzian/uv_cache` — `/nashome` quota is too tight
  (~2 GB available) for langgraph's dep tree (grpcio + langchain-core pull >300 MB).
- **State**: `BOIterationState` TypedDict at `graph/state.py`. Uses `Optional[X]` not
  `X | None` because LangGraph re-evaluates annotations via `get_type_hints` at
  StateGraph construction; PEP 604 union syntax fails on 3.9 even with
  `from __future__ import annotations` (we no longer target 3.9 but the doc-note remains).
- **Imports**: `build.py` and `nodes.py` use `sys.path.insert + absolute imports`
  (not `from .nodes import …`) because `langgraph dev` loads the entrypoint as a
  standalone file path, breaking package-relative imports.
- **No checkpointer at compile under `langgraph dev`**: the platform supplies one.
  `graph/build.py` calls `compile()` with no args. Headless `graph/run.py` wires
  `SqliteSaver(sqlite3.connect(CHECKPOINT_DB))` itself.
- **REST API**: `http://127.0.0.1:2024` (assistants, threads, runs, docs at `/docs`).
  Studio UI at `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`
  (browser must reach 127.0.0.1:2024 — use `ssh -L 2024:127.0.0.1:2024 <gpvm>`).
- **Smoke command**: `curl -sS http://127.0.0.1:2024/runs/wait -X POST -H 'Content-Type: application/json' -d '{"assistant_id":"bo_helical","input":{"mode":"helical","alpha":100000.0,"mock":true,"config_name":"graphsmoke001"}}'`
- **`--allow-blocking` is required** in dev because `pipeline_io.run_preflight` is
  a synchronous `subprocess.run` that blocks the worker's event loop. Without
  it, langgraph_api raises on every node call.
- **`scan_logs` end-of-workflow node (2026-05-20)** — between `harvest` and
  `evaluate`. Walks every worker `.log` derived from each `<stage>_outputs.txt`,
  fans out `xargs -P 16 grep -cE` over patterns: `G4Exception`, `Stuck Track`,
  `Likely geometry overlap`, `GeomSolids1001`, `GeomNav1002`, `Error`,
  `Warning`, `FATAL`, `SEGV`. Writes `<grid_root>/<config>/scan_logs/report.tsv`
  + `report.json`; populates `state.scan_report` (dict of `{stage:
  {code: count}}`) and `state.scan_report_path`. **Report-only** — never
  raises, never fails the iteration, no leaderboard mutation. Cost: ~4 min on
  helical050a (which has 28M GeomNav1002 hits making `grep -c` outputs huge);
  near-zero on clean iterations. `n_logs` in the report counts only workers
  whose `.art` made it to `<stage>_outputs.txt`, not raw outstage dirs —
  matches the scope of data actually being harvested. See
  [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) for the first issue this caught.

## Cross-links
- Related: [bo-driver](/drivers/bo-driver.md), [preflight](/drivers/preflight.md), [bo-helical](/projects/bo-helical.md), [orchestrator-evaluation-2026-05](/concepts/orchestrator-evaluation-2026-05.md), [closed-loop-runner](/drivers/closed-loop-runner.md)
- Wrapped by: [closed-loop-runner](/drivers/closed-loop-runner.md) (multi-round driver spawns q parallel `graph.run` children per round)
- Per-stage I/O: [pipeline](/drivers/pipeline.md) (idempotent submit/poll/list-outputs/harvest)
- Regression tests: [tests](/drivers/tests.md)
- Source files: `graph/build.py`, `graph/nodes.py`, `graph/pipeline_io.py`, `graph_app/streamlit_app.py`
- Config: `langgraph.json`, `requirements-graph.txt`
- External: [LangGraph docs](https://langchain-ai.github.io/langgraph/)

## Open questions / TODO
- **Multi-round driver lives in [closed-loop-runner](/drivers/closed-loop-runner.md)** — `graph.run` remains
  the single-iteration entrypoint; `graph.closed_loop` wraps q parallel
  `graph.run` children per round and refits the GP between rounds.
- Supervisor loop to re-invoke pending threads every N min (Phase 3).
- michael mode in `build.py` (one-line change once Phase 2b stabilizes).
- Studio observability for the SQLite checkpoint produced by `graph/run.py`
  (Studio currently only sees the dev server's in-memory store).
- Per-stage `submit` retry edge inside the graph (currently any failure
  inside `pio.run_stage` terminates the iteration; we rely on the next manual
  re-resume to recover).
