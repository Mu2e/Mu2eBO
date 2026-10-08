# Autoresearch — closed-loop BO over Mu2e geometry

Machinery that proposes detector-geometry variants (Bayesian optimization),
evaluates them on FermiGrid through Geant4 simulation chains, and accumulates
results in per-mode leaderboards. This file defines the domain language;
architecture decisions live in `docs/adr/`, operational knowledge in `wiki/`.

## Language

### Optimization

**Mode**:
One research line's complete definition — search space, geometry renderer, stage chain, environment, objectives (e.g. `foilsflash`, `foilspfbpz`). Declared by exactly one Study of the same name; "mode" names the running line, "study" the file that defines it. A study is selected with `--study <name>` and listed in `core.modes.STUDIES`; the `--mode` flag and `bo_driver.MODES` were deleted in Phase C3 (2026-09-28) with the pipeline.
_Avoid_: campaign type

**Study**:
A schema-2 JSON file, `mode_specs/<name>.json` (or in a directory on `$AUTORESEARCH_STUDY_PATH`), loaded and validated by `core/study.py` into `core.modes.STUDIES`: knobs, derive, geom, kits, evaluate steps, objectives, constraint, leaderboard. The single source of every per-Mode fact.
_Avoid_: spec file, mode config

**ModeSpec**:
Retired. Was the Phase-A compat view of a Study (`core/study_compat.py`), held in `core.modes.SPECS` for the pipeline, runtime and preflight code that read it. Deleted in Phase C3 (2026-09-28) with the rest of the pipeline: `core/study_compat.py`, `core.modes.SPECS` and `core.modes.ENGINE` are gone; `core/modes.py` now holds only `STUDIES`, `PICKER_CHOICES`, `DEFAULT_PICKER` and `MODES_DIR`.
_Avoid_: mode config, mode table, per-mode dict

**Engine study**:
A Study, run through `graph.run`/`graph.closed_loop` (the contract engine). Since Phase C3 (2026-09-28) deleted the pipeline, every loaded study is an engine study — the "engine kit" test (`core.modes.ENGINE`, `KitDecl`'s `engine=True`) and the "Pipeline study" distinction below are both retired. `branin` (`tests/fixtures/engine_studies/branin.json`, on `toykit`) and `prodtools_smoke` (the Phase C1 acceptance study, on `prodtools`, gated by the `offline_preflight` pre-check since Phase C2a) are the toy/smoke examples; the `<name>_ax` studies (Phase C2b) are the production ones, with `foilspf_nominal` (the deployed target) as their baseline.

**Pipeline study**:
Retired. Was a Study that ran through the pipeline (`core/bo_driver.py`, the old `graph/run.py`/`graph/closed_loop.py`) because at least one of its kits — `ce_sensitivity` or `flash_edep_per_pot` — had no engine adapter. The seven `foilspf` studies were the last of these; Phase C3 (2026-09-28) deleted the pipeline (`core/bo_driver.py` and the two pipeline-only kits with it) and archived them to `mode_specs/archive/` (deleted 2026-10-08, kept in git history; their v1 boards stay in `leaderboards/`). The routing rule this entry described (`core/modes.py:runs_on_engine`, the `"v1"`/`"v2"` layout split in `core/study_compat.py`) went with it: `core.modes` now refuses any study it cannot run on the engine, full stop — one such file in `mode_specs/` or on `$AUTORESEARCH_STUDY_PATH` still stops every command (`graph.run`, `graph.closed_loop`, the surrogate MCP server) for every study, since the refusal happens when `core.modes` is imported.

**JsonMode**:
Retired. Was the behavior half of a pipeline Mode (render geometry, recover x at evaluate time, read and append leaderboard rows), one driver object per ModeSpec (`core/bo_driver.py`); collapsed from the `BOMode` ABC 2026-08-19 (`55168e7`, the five Python subclasses had already been archived 2026-08-08, `4bc54cc`) and deleted with `core/bo_driver.py` in Phase C3 (2026-09-28). The engine's equivalent behavior — run a study's steps and score the result — is `core/scheduler.py`'s `run_steps` plus `core/score.py`, driven through `core/contract.py`.

**Eval**:
One geometry point evaluated end-to-end; identified by its config name, which keys the state dir, grid dirs, and leaderboard row.
_Avoid_: trial, run (overloaded)

**Campaign**:
One closed-loop invocation — a name-prefix, a pool width q, and an eval budget (e.g. `foilspf05`, `--q 20 --max-evals 40`).

**Pool**:
The campaign parent (`graph/pool.py::run_rolling`): keeps q Children in flight and launches exactly one replacement each time one exits, until the eval budget is spent and the pool drains. It has no rounds — the GP is refit per pick, against the leaderboard as it stands at that moment.
_Avoid_: round, batch, wave (all retired 2026-08-19)

**Picker**:
The proposal strategy that turns leaderboard history into the next point(s) — `hybrid`, `qnehvi`, `qlnei`, `budget_sob`, declared once as `core.modes.PICKER_CHOICES`. Runs once per replacement launch, in the campaign process itself — no subprocess: `graph/closed_loop.py:surrokit_pick` calls `core/botorch_predict.py` directly — over the current In-flight set as `X_pending`. The Engine-side name for `budget_sob` is `constrained_max`.

**Engine**:
The physics-agnostic surrogate/optimization core (`surrokit`, extracted from `core/botorch_predict.py`): GP fit, posterior predict, and the Pickers behind a `fit / predict / ask` API. Sees only numbers in math space — every Y axis maximized, axis 0 primary; never learns what "sob" or "flash" means.
_Avoid_: asktell (rejected name), surrogate library

**Problem**:
The Engine's search-space declaration — bounds, integer dims, per-axis noise sigmas, optional budget Constraint. The client (autoresearch) builds one per Mode from its Study (`core/botorch_predict.py:build_problem`).

**Adapter**:
Two distinct senses, kept apart by context — see Flagged ambiguities.
(1) The client bridge that names Problems and serves their history (X, Y, meta) to the Engine's MCP scaffold via `make_server(adapter)`; autoresearch's Adapter wraps Study + Leaderboards.
(2) Python that speaks the evaluator contract (see Kit) for a kit that doesn't speak it natively: a class named by the `factory` string of its `KitDecl` in `core/kit_registry.py` (imported by `core/contract.py:load_factory`), taking the Campaign name; the launch stagger, Kerberos need, executors and config-name rule are declared on the `KitDecl`, not on the class. `prodtools` (`core/adapters/prodtools.py`, Phase C1), `offline_preflight` (`core/adapters/offline_preflight.py`, Phase C2a) and `anakit` (`core/adapters/anakit.py`, Phase C2b) are the three; a `KitDecl` with `names_runs_after_config` has its config-name rule checked by `contract.launch_problems` before launching, against `graph.run --config` and against the first child name of `graph.closed_loop`.

**Leaderboard**:
The append-only per-mode TSV of completed evals; the ONLY durable source of truth for BO history. There is no checkpointer (retired 2026-08-19); the engine's own resume state is per-point, not per-campaign — `state/point.json`, `state/<step>_cluster.txt` and `state/<step>_results.json` under `<GRID_DATA_ROOT>/<config>/state/`, read by `core/scheduler.py:run_steps` so a rerun of `graph.run` with the same `--config` adopts steps already submitted or done instead of resubmitting them.

**measure_sha**:
On a Leaderboard (every one is layout `"v2"`; `"v1"` was retired 2026-09-29), the SHA-256 identifying HOW a row was measured: `derive`, `geom`, every kit's settings, each step's kit/entry/files/params/fixed, each objective's metric and transform, each extra metric's metric (an extra metric has no transform), and the reported version of each kit a step runs on (`core/study.py:Study.measure_sha`). A kit's version is hand-bumped (2026-10-05): it changes only when its author decides a step measures anew; a build (the anakit checkout commit, the beamkit server) is recorded with each step, never in the version. One module decides a point's versions and the board match (`core/measure.py`). The preflight Kit's version is excluded — it gates a point but produces none of its numbers. An append whose `measure_sha` differs from the board's is refused and the row quarantined (`core/leaderboard.py`): a board holds one measurement, never mixed ones. A point's `point.json` records the kit-version-free part (`Study.measure_basis_sha`), so rerunning a killed point after the study's measurement changed is refused rather than adopting jobs measured the old way.
_Avoid_: spec_sha (a coarser hash of the whole study file, including things like `note` that don't change a measurement)

### Execution

**Kit**:
An MCP server (or, for a kit with no adapter yet, Python that speaks the same interface — see Adapter) offering the evaluator contract a study's steps run on: `submit`/`status`/`results`, plus optional `check`/`describe`/`cancel` (`docs/superpowers/specs/2026-09-23-generic-study-design.md`, "The evaluator contract"). A study names its kits per step (`evaluate[].kit`) and, optionally, one for preflight.

**Native kit**:
A Kit that speaks the evaluator contract over MCP directly: one `kits.toml` entry (`core/kit_config.py`), no Python. The engine drives it through `core/contract.py`'s `NativeKit` and `core/kits.py`'s `KitClient`. `toykit` (`tests/toykit.py`) is the only one as of Phase B; grid kits (`prodtools` from Phase C, `beamkit` from Phase D, `anakit` from Phase E) arrive as Adapters instead.

**Executor**:
Where a point's jobs run: `grid` (the default) or `local` (this node), chosen by `graph.run --executor` / `graph.closed_loop --executor` and recorded in the point's `point.json`. Not part of `measure_sha`: the physics is the same. A small test is its own study file with its own board, not a scale-down of a real one.

**Stage**:
One grid-submission unit in an eval's chain (`mubeam`, `mustops_ce`, `elebeam_flash`) driven through the evaluator contract's `submit`/`status`/`results` verbs (plus optional `check`/`describe`/`cancel`) that every Kit speaks — see Kit, below.

**Stage chain**:
The ordered stages one eval runs; declared per Mode.

**Child**:
One `graph.run` subprocess evaluating one config for a Campaign — the contract engine's per-point runner, renamed from `graph.study_run` in Phase C3 (2026-09-28). Detached (`start_new_session=True`), so it outlives its parent.

**In-flight set**:
The Children the Pool is currently waiting on; never larger than q. Its x-points are what the picker fantasizes over (`X_pending`).

**Outcome**:
A Child's result, decided at the moment its subprocess exits and never before: `ok`, `broken`, `child rc=N`, or `exit 0 but no leaderboard row` (`graph/pool.py::classify`). **A child resolves when its subprocess exits** — that one rule replaced a Barrier reconciling five signal sources.
_Avoid_: resolution, running/dead_unresolved/stale_cluster (the retired ChildTracker vocabulary)

**Busy name**:
A config name the Pool refuses to launch under because an earlier process already resolved it (a leaderboard row, `broken.txt`) or still has work in flight for it (`state/point.json`, `state/*_cluster.txt`). The Pool skips to the next index and says why (`graph/closed_loop.py::busy_reason`). Recovery is "relaunch under another --name-prefix" (the code's own advice, `busy_reason`'s docstring) — NOT a same-prefix relaunch: once a `*_cluster.txt` exists the kit refuses the same `<config>.<step>` handle with other params, so removing the state dir is safe only once nothing still runs under that name (its `state/run.lock` is free: `flock -n <state>/run.lock true` succeeds) and it never held a `*_cluster.txt` (nothing was submitted).

**Point record**:
A point's `<GRID_DATA_ROOT>/<config>/state/` folder, owned by `core/point_dir.py` (`PointDir`): `point.json`, each step's handle/status/results, `broken.txt` (first writer wins; `PointDir.broken()` its only parser), `summary.json`, `evaluate_result.json`, the pre-check's files and `run.lock`, the flock its `graph.run` holds while it runs. Every writer and reader goes through `PointDir` (2026-10-05).
_Avoid_: state dir rules written inline (`state_dir / "broken.txt"`)

**Campaign record**:
A campaign's `<GRAPH_DATA>/<prefix>/` folder, owned by `core/campaign_dir.py` (`CampaignDir`): `campaign.json` (written by every `graph.closed_loop` once its launch checks pass), `outcomes.jsonl` (one Outcome per finished Child), `parent.lock` (held while the Pool runs), `STOP`, and for an MCP launch `launch.json`, `lock`, `parent.log`, `rc`. Child names are built and parsed there (`child_name`, `parse_child`). Liveness is these flocks, never a process scan (2026-10-05).

**Eval summary**:
Retired term. Was the explicit, typed product of the pipeline's harvest (`harvest.EvalSummary` → `harvest/summary.json`): the primary sob chain plus fail-soft secondary objectives, with a `degraded` record of every extraction that fail-softed. Deleted with `harvest.py` in Phase C3 (2026-09-28). The engine's equivalent: each step's kit reports its metrics into `state/<step>_results.json` (`core/scheduler.py`); `core/score.py:score` collects them by name into the study's objectives and extra metrics, writes `state/summary.json` (`{config, x, steps: {step: metrics}}` — a much smaller schema, with no `degraded` record) and `state/evaluate_result.json` (`{config, primary, objectives, row_appended}`), and appends the leaderboard row.
_Avoid_: "the summary dict" (the pipeline's implicit 26-key contract)

**Preflight**:
The local 1-event G4 feasibility check gating a point before anything is submitted: `mu2e -n 1` with G4's surface check, the as-built GDML comparison and the overlap policy, run on this node from the study's code tarball (`kits.offline_preflight.code_tarball`, which must equal `kits.prodtools.code_tarball`). Its rules live in `core/adapters/preflight_checks.py`, used by the engine's `offline_preflight` kit (shared with the pipeline's `bo_driver preflight` until Phase C3, 2026-09-28, deleted it); its workdir is `<GRID_DATA_ROOT>/<config>/preflight/`. Verdicts are `pass` / `fail_managed` / `ambiguous`; only `pass` passes.

**Musing**:
The Mu2e Offline release a code tarball builds against (its `Code/backing` link: SimJob MDC2025ax for the production studies, Run1Bap for the retired foilspf family). Since Phase C2a no study names one: the pre-check and the jobs all source the code tarball's own `Code/setup.sh`.

**Grid tarball**:
The `Code.tar.bz2` shipped to grid workers (`kits.prodtools.code_tarball`). The pre-check unpacks and runs the same file (`prodtools_entry.unpacked`, cached by content under `<GRID_DATA_ROOT>/_code/`), so the geometry it passes is the geometry the jobs build (the env-divergence incidents).

## Relationships

- A **Campaign** runs a **Pool**; the Pool keeps q **Children** in its **In-flight set** and replaces each one as it exits; each Child performs one **Eval** and ends in one **Outcome**.
- A **Mode** = one **Study** (`mode_specs/<name>.json`), run through the contract engine (`core/contract.py`, `core/scheduler.py`); every Eval belongs to exactly one Mode. (Before Phase C3 a Mode also had a **JsonMode** instance for the pipeline path; that class and the pipeline are both gone.)
- An Eval runs its Mode's **Stage chain**; **Preflight** gates the first Stage; `core/score.py:score` appends one **Leaderboard** row (harvest is retired terminology — see Eval summary).
- The **Pool** learns a Child's **Outcome** from its exit code plus two artifacts (leaderboard row, `broken.txt`); it never polls, and it never resolves a Child that has not exited.
- The **Picker** consumes the **Leaderboard** and produces the next point, once per replacement launch.

## Example dialogue

> **Dev:** "foilspf05R07_00's process died — is the campaign stuck?"
> **Domain expert:** "No. Its subprocess exited, so the **Pool** has its **Outcome** — nonzero rc, no row — logs it, and launches a replacement. Nothing waits on it. If it had HUNG instead of died, the Pool would still be waiting, and would say so every 15 minutes in the parent log."
> **Dev:** "And if I add a new **Mode**, where do its stage targets go?"
> **Domain expert:** "Its **Study** — a new `mode_specs/<name>.json`. Every field is required, so forgetting the **Grid tarball** is a load error, not a silent fallback to another mode's."

## Flagged ambiguities

- "config" was used for both an Eval's identity and per-mode settings — resolved: an Eval has a *config name*; per-mode settings are the **Study**.
- "completed" in closed_loop.py mixed done-with-row, done-broken, and died-unresolved — resolved: use the specific **Outcome** reason. (The whole Barrier/ChildTracker/Resolution vocabulary this replaced was deleted 2026-08-19 with the parent rewrite; see `docs/superpowers/specs/2026-08-19-minimal-foilspf-workflow-design.md`.)
- "mode tables" (the scattered `*_BY_MODE` dicts) — superseded by **ModeSpec** (see ADR-0002), itself now the **Study**.
- **Adapter** names two unrelated bridges — not resolved, just documented in place (see the Adapter entry): the surrokit-facing one (Study+Leaderboards → the Engine's MCP scaffold, `core/botorch_predict.py`) and the contract-facing one (an existing kit family → the evaluator contract, declared by a `KitDecl` `factory` in `core/kit_registry.py`, Phase C on). Context disambiguates in practice; a rename was considered and rejected as more churn than the ambiguity is worth.
