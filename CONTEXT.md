# Autoresearch — closed-loop BO over Mu2e geometry

Machinery that proposes detector-geometry variants (Bayesian optimization),
evaluates them on FermiGrid through Geant4 simulation chains, and accumulates
results in per-study leaderboards. This file defines the domain language;
architecture decisions live in `docs/adr/`, operational knowledge in `wiki/`.

## Language

### Optimization

**Mode**:
One research line's complete definition — search space, geometry renderer, steps, environment, objectives (e.g. `foilsflash_ax`, `foilspfbpz_ax`). Declared by exactly one Study of the same name; "mode" names the running line, "study" the file that defines it. A study is selected with `--study <name>` and listed in `core.modes.STUDIES`.
_Avoid_: campaign type

**Study**:
A schema-2 JSON file, `mode_specs/<name>.json` (or in a directory on `$AUTORESEARCH_STUDY_PATH`), loaded and validated by `core/study.py` into `core.modes.STUDIES`: knobs, derive, geom, kits, evaluate steps, objectives, constraint, leaderboard. The single source of every per-Mode fact.
_Avoid_: spec file, mode config

**Engine study**:
A Study, run through `graph.run`/`graph.closed_loop` (the contract engine); every loaded study is one. `branin` (`tests/fixtures/engine_studies/branin.json`, on `toykit`) and `prodtools_smoke` (on `prodtools`, gated by the `offline_preflight` pre-check) are the toy/smoke examples; `foilspfbpz_ax` and `foilsflash_ax` are the production ones, with `foilspf_nominal` (the deployed target) as their baseline.

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
(2) Python that speaks the evaluator contract (see Kit) for a kit that doesn't speak it natively: a class named by the `factory` string of its `KitDecl` in `core/kit_registry.py` (imported by `core/contract.py:load_factory`), taking the Campaign name; the launch stagger, Kerberos need, executors and config-name rule are declared on the `KitDecl`, not on the class. There are four: `prodtools` (`core/adapters/prodtools.py`), `offline_preflight` (`core/adapters/offline_preflight.py`), `anakit` (`core/adapters/anakit.py`) and `beamkit` (`core/adapters/beamkit.py`); a `KitDecl` with `names_runs_after_config` has its config-name rule checked by `contract.launch_problems` before launching, against `graph.run --config` and against the first child name of `graph.closed_loop`.

**Leaderboard**:
The append-only per-mode TSV of completed evals; the ONLY durable source of truth for BO history. There is no checkpointer; the engine's own resume state is per-point, not per-campaign — `state/point.json`, `state/<step>_cluster.txt` and `state/<step>_results.json` under `<GRID_DATA_ROOT>/<config>/state/`, read by `core/scheduler.py:run_steps` so a rerun of `graph.run` with the same `--config` adopts steps already submitted or done instead of resubmitting them.

**measure_sha**:
On a Leaderboard (every one is layout `"v2"`), the SHA-256 identifying HOW a row was measured: `derive`, `geom`, every kit's settings, each step's kit/entry/files/params/fixed, each objective's metric and transform, each extra metric's metric (an extra metric has no transform), and the reported version of each kit a step runs on (`core/study.py:Study.measure_sha`). A kit's version is hand-bumped: it changes only when its author decides a step measures anew; a build (the anakit checkout commit, the beamkit server) is recorded with each step, never in the version. One module decides a point's versions and the board match (`core/measure.py`). The preflight Kit's version is excluded — it gates a point but produces none of its numbers. An append whose `measure_sha` differs from the board's is refused and the row quarantined (`core/leaderboard.py`): a board holds one measurement, never mixed ones. A point's `point.json` records the kit-version-free part (`Study.measure_basis_sha`), so rerunning a killed point after the study's measurement changed is refused rather than adopting jobs measured the old way.
_Avoid_: spec_sha (a coarser hash of the whole study file, including things like `note` that don't change a measurement)

### Execution

**Kit**:
An MCP server (or Python that speaks the same interface — see Adapter) offering the evaluator contract a study's Steps run on: `submit`/`status`/`results`, plus optional `check`/`describe`/`cancel` (`core/contract.py`; `wiki/drivers/contract-engine.md`). A study names its kits per step (`evaluate[].kit`) and, optionally, one for preflight.

**Native kit**:
A Kit that speaks the evaluator contract over MCP directly: one `kits.toml` entry (`core/kit_config.py`), no Python. The engine drives it through `core/contract.py`'s `NativeKit` and `core/kits.py`'s `KitClient`. `toykit` (`tests/toykit.py`) is the only one; the grid kits are Adapters.

**Executor**:
Where a point's jobs run: `grid` (the default) or `local` (this node), chosen by `graph.run --executor` / `graph.closed_loop --executor` and recorded in the point's `point.json`. Not part of `measure_sha`: the physics is the same. A small test is its own study file with its own board, not a scale-down of a real one.

**Step**:
One entry of a study's `evaluate` list: a Kit, its job template or analysis, its input files and params. Grid steps run Geant4 jobs (`mubeam`, `mustops_ce`, `elebeam_flash`); analysis steps read an earlier step's files (`stops`, `ce_edep`, `sob`, `flash`). The engine runs each one through the Kit's `submit`/`status`/`results` (`core/scheduler.py:run_steps`), in the order `files_from` and `params_from` set.
_Avoid_: stage (the pipeline's word; it survives only in `stage_entries/` and "stage template", the prodtools job template a grid step names as its `entry`)

**Child**:
One `graph.run` subprocess evaluating one config for a Campaign — the contract engine's per-point runner. Detached (`start_new_session=True`), so it outlives its parent.

**In-flight set**:
The Children the Pool is currently waiting on; never larger than q. Its x-points are what the picker fantasizes over (`X_pending`).

**Outcome**:
A Child's result, decided at the moment its subprocess exits and never before: `ok`, `broken`, `child rc=N`, or `exit 0 but no leaderboard row` (`graph/pool.py::classify`). **A child resolves when its subprocess exits** — that one rule replaced a Barrier reconciling five signal sources.
_Avoid_: resolution, running/dead_unresolved/stale_cluster (the retired ChildTracker vocabulary)

**Busy name**:
A config name the Pool refuses to launch under because an earlier process already resolved it (a leaderboard row, `broken.txt`) or still has work in flight for it (`state/point.json`, `state/*_cluster.txt`). The Pool skips to the next index and says why (`graph/closed_loop.py::busy_reason`). Recovery is "relaunch under another --name-prefix" (the code's own advice, `busy_reason`'s docstring) — NOT a same-prefix relaunch: once a `*_cluster.txt` exists the kit refuses the same `<config>.<step>` handle with other params, so removing the state dir is safe only once nothing still runs under that name (its `state/run.lock` is free: `flock -n <state>/run.lock true` succeeds) and it never held a `*_cluster.txt` (nothing was submitted).

**Point record**:
A point's `<GRID_DATA_ROOT>/<config>/state/` folder, owned by `core/point_dir.py` (`PointDir`): `point.json`, each step's handle/status/results, `broken.txt` (first writer wins; `PointDir.broken()` its only parser), `summary.json`, `evaluate_result.json`, the pre-check's files and `run.lock`, the flock its `graph.run` holds while it runs. Every writer and reader goes through `PointDir`.
_Avoid_: state dir rules written inline (`state_dir / "broken.txt"`)

**Campaign record**:
A campaign's `<GRAPH_DATA>/<prefix>/` folder, owned by `core/campaign_dir.py` (`CampaignDir`): `campaign.json` (written by every `graph.closed_loop` once its launch checks pass), `outcomes.jsonl` (one Outcome per finished Child), `parent.lock` (held while the Pool runs), `STOP`, and for an MCP launch `launch.json`, `lock`, `parent.log`, `rc`. Child names are built and parsed there (`child_name`, `parse_child`). Liveness is these flocks, never a process scan.

**Preflight**:
The local 1-event G4 feasibility check gating a point before anything is submitted: `mu2e -n 1` with G4's surface check, the as-built GDML comparison and the overlap policy, run on this node from the study's code tarball (`kits.offline_preflight.code_tarball`, which must equal `kits.prodtools.code_tarball`). Its rules live in `core/adapters/preflight_checks.py`, used by the engine's `offline_preflight` kit; its workdir is `<GRID_DATA_ROOT>/<config>/preflight/`. Verdicts are `pass` / `fail_managed` / `ambiguous`; only `pass` passes.

**Musing**:
The Mu2e Offline release a code tarball builds against (its `Code/backing` link: SimJob MDC2025ax for the production studies). The pre-check and the jobs source the code tarball's own `Code/setup.sh`; the only Musing a study names is `kits.anakit.musing` (`SimJob MDC2025ay`), where the analysis server runs its mu2e jobs.

**Grid tarball**:
The `Code.tar.bz2` shipped to grid workers (`kits.prodtools.code_tarball`). The pre-check unpacks and runs the same file (`prodtools_entry.unpacked`, cached by content under `<GRID_DATA_ROOT>/_code/`), so the geometry it passes is the geometry the jobs build (the env-divergence incidents).

## Relationships

- A **Campaign** runs a **Pool**; the Pool keeps q **Children** in its **In-flight set** and replaces each one as it exits; each Child performs one **Eval** and ends in one **Outcome**.
- A **Mode** = one **Study** (`mode_specs/<name>.json`), run through the contract engine (`core/contract.py`, `core/scheduler.py`); every Eval belongs to exactly one Mode.
- An Eval runs its Study's **Steps**; **Preflight** gates the first one; `core/score.py:score` collects the steps' metrics into the objectives and appends one **Leaderboard** row.
- The **Pool** learns a Child's **Outcome** from its exit code plus two artifacts (leaderboard row, `broken.txt`); it never polls, and it never resolves a Child that has not exited.
- The **Picker** consumes the **Leaderboard** and produces the next point, once per replacement launch.

## Example dialogue

> **Dev:** "foilspf05R07_00's process died — is the campaign stuck?"
> **Domain expert:** "No. Its subprocess exited, so the **Pool** has its **Outcome** — nonzero rc, no row — logs it, and launches a replacement. Nothing waits on it. If it had HUNG instead of died, the Pool would still be waiting, and would say so every 15 minutes in the parent log."
> **Dev:** "And if I add a new **Mode**, where do its steps go?"
> **Domain expert:** "Its **Study** — a new `mode_specs/<name>.json`. Every field is required, so forgetting the **Grid tarball** is a load error, not a silent fallback to another mode's."

## Flagged ambiguities

- "config" was used for both an Eval's identity and per-mode settings — resolved: an Eval has a *config name*; per-mode settings are the **Study**.
- "completed" in closed_loop.py mixed done-with-row, done-broken, and died-unresolved — resolved: use the specific **Outcome** reason. (The whole Barrier/ChildTracker/Resolution vocabulary this replaced was deleted 2026-08-19 with the parent rewrite; see `docs/superpowers/specs/2026-08-19-minimal-foilspf-workflow-design.md`.)
- "mode tables" (the scattered `*_BY_MODE` dicts) — superseded by the **Study** (see ADR-0002).
- **Adapter** names two unrelated bridges — not resolved, just documented in place (see the Adapter entry): the surrokit-facing one (Study+Leaderboards → the Engine's MCP scaffold, `core/botorch_predict.py`) and the contract-facing one (an existing kit family → the evaluator contract, declared by a `KitDecl` `factory` in `core/kit_registry.py`). Context disambiguates in practice; a rename was considered and rejected as more churn than the ambiguity is worth.
