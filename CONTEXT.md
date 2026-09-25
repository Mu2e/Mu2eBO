# Autoresearch — closed-loop BO over Mu2e geometry

Machinery that proposes detector-geometry variants (Bayesian optimization),
evaluates them on FermiGrid through Geant4 simulation chains, and accumulates
results in per-mode leaderboards. This file defines the domain language;
architecture decisions live in `docs/adr/`, operational knowledge in `wiki/`.

## Language

### Optimization

**Mode**:
One research line's complete definition — search space, geometry renderer, stage chain, environment, objectives (e.g. `foilsflash`, `foilspfbpz`). Declared by exactly one Study of the same name; "mode" names the running line (`--mode <name>`, `bo_driver.MODES`), "study" the file that defines it.
_Avoid_: campaign type

**Study**:
A schema-2 JSON file, `mode_specs/<name>.json` (or in a directory on `$AUTORESEARCH_STUDY_PATH`), loaded and validated by `core/study.py` into `core.modes.STUDIES`: knobs, derive, geom, kits, evaluate steps, objectives, constraint, leaderboard. The single source of every per-Mode fact.
_Avoid_: spec file, mode config

**ModeSpec**:
The Phase-A compat view of a Study (`core/study_compat.py`), held in `core.modes.SPECS` for the pipeline, runtime and preflight code that still read it; deleted in Phase C.
_Avoid_: mode config, mode table, per-mode dict

**Engine study**:
A Study every one of whose kits is an engine kit (`core.modes.ENGINE`, `core/kit_registry.py`'s `engine=True`); runs through `graph.study_run`/`graph.study_loop` (the contract engine), never the pipeline. `branin` (`tests/fixtures/engine_studies/branin.json`, on `toykit`) is the only one as of Phase B.

**Pipeline study**:
A Study that still runs through the pipeline (`core/bo_driver.py`, `graph/run.py`, `graph/closed_loop.py`) because none of its kits has an engine adapter yet. `foilspf` and its siblings, until Phase C gives `prodtools` an adapter. A study's kits are all engine kits or all pipeline kits: a mix runs on neither and is refused (`core/modes.py:runs_on_engine`), and a pipeline study must be layout `"v1"` (`core/study_compat.py` refuses `"v2"`). Both refusals happen when `core.modes` is imported, so one such file in `mode_specs/` or on `$AUTORESEARCH_STUDY_PATH` stops every command (`graph.run`, `graph.closed_loop`, the engine, the surrogate MCP server) for every study.

**JsonMode**:
The behavior half of a Mode (render geometry, recover x at evaluate time, read and append leaderboard rows), one driver object per ModeSpec (`core/bo_driver.py`). There is exactly one class — the five Python subclasses were archived 2026-08-08 (`4bc54cc`) and the `BOMode` ABC itself collapsed into `JsonMode` 2026-08-19 (`55168e7`).

**Eval**:
One geometry point evaluated end-to-end; identified by its config name, which keys the state dir, grid dirs, and leaderboard row.
_Avoid_: trial, run (overloaded)

**Campaign**:
One closed-loop invocation — a name-prefix, a pool width q, and an eval budget (e.g. `foilspf05`, `--q 20 --max-evals 40`).

**Pool**:
The campaign parent (`graph/pool.py::run_rolling`): keeps q Children in flight and launches exactly one replacement each time one exits, until the eval budget is spent and the pool drains. It has no rounds — the GP is refit per pick, against the leaderboard as it stands at that moment.
_Avoid_: round, batch, wave (all retired 2026-08-19)

**Picker**:
The proposal strategy that turns leaderboard history into the next point(s) — `hybrid`, `qnehvi`, `qlnei`, `budget_sob`, declared once as `core.modes.PICKER_CHOICES` and accepted by both the parent and the picker subprocess. Runs once per replacement launch, in a subprocess, over the current In-flight set as `X_pending`. The Engine-side name for `budget_sob` is `constrained_max`.

**Engine**:
The physics-agnostic surrogate/optimization core (`surrokit`, extracted from `core/botorch_predict.py`): GP fit, posterior predict, and the Pickers behind a `fit / predict / ask` API. Sees only numbers in math space — every Y axis maximized, axis 0 primary; never learns what "sob" or "flash" means.
_Avoid_: asktell (rejected name), surrogate library

**Problem**:
The Engine's search-space declaration — bounds, integer dims, per-axis noise sigmas, optional budget Constraint. The client (autoresearch) builds one per Mode from its Study (`core/botorch_predict.py:build_problem`).

**Adapter**:
Two distinct senses, kept apart by context — see Flagged ambiguities.
(1) The client bridge that names Problems and serves their history (X, Y, meta) to the Engine's MCP scaffold via `make_server(adapter)`; autoresearch's Adapter wraps Study + Leaderboards.
(2) Python that speaks the evaluator contract (see Kit) for a kit that doesn't speak it natively: a class registered in `core/contract.py`'s `ADAPTERS`, taking the Campaign name, with a `LAUNCH_STAGGER_S` attribute. None is registered yet — Phase C adds `prodtools`.

**Leaderboard**:
The append-only per-mode TSV of completed evals; the ONLY durable source of truth for BO history. There is no checkpointer (retired 2026-08-19) and no other resume state.

**measure_sha**:
On a `"v2"`-layout Leaderboard, the SHA-256 identifying HOW a row was measured: `derive`, `geom`, every kit's settings, each step's kit/entry/files/params/fixed, each objective's metric and transform, each extra metric's metric (an extra metric has no transform), and the reported version of each kit a step runs on (`core/study.py:Study.measure_sha`). The preflight Kit's version is excluded — it gates a point but produces none of its numbers. An append whose `measure_sha` differs from the board's is refused and the row quarantined (`core/leaderboard.py`): a board holds one measurement, never mixed ones. A point's `point.json` records the kit-version-free part (`Study.measure_basis_sha`), so rerunning a killed point after the study's measurement changed is refused rather than adopting jobs measured the old way.
_Avoid_: spec_sha (a coarser hash of the whole study file, including things like `note` that don't change a measurement)

### Execution

**Kit**:
An MCP server (or, for a kit with no adapter yet, Python that speaks the same interface — see Adapter) offering the evaluator contract a study's steps run on: `submit`/`status`/`results`, plus optional `check`/`describe`/`cancel` (`docs/superpowers/specs/2026-09-23-generic-study-design.md`, "The evaluator contract"). A study names its kits per step (`evaluate[].kit`) and, optionally, one for preflight.

**Native kit**:
A Kit that speaks the evaluator contract over MCP directly: one `kits.toml` entry (`core/kit_config.py`), no Python. The engine drives it through `core/contract.py`'s `NativeKit` and `core/kits.py`'s `KitClient`. `toykit` (`tests/toykit.py`) is the only one as of Phase B; grid kits (`prodtools` from Phase C, `beamkit` from Phase D, `anakit` from Phase E) arrive as Adapters instead.

**Stage**:
One grid-submission unit in an eval's chain (`mubeam`, `mustops_ce`, `elebeam_flash`) driven by idempotent submit/poll/list-outputs verbs.

**Stage chain**:
The ordered stages one eval runs; declared per Mode.

**Child**:
One `graph.run` subprocess evaluating one config for a Campaign. Detached (`start_new_session=True`), so it outlives its parent.

**In-flight set**:
The Children the Pool is currently waiting on; never larger than q. Its x-points are what the picker fantasizes over (`X_pending`).

**Outcome**:
A Child's result, decided at the moment its subprocess exits and never before: `ok`, `broken`, `child rc=N`, or `exit 0 but no leaderboard row` (`graph/pool.py::classify`). **A child resolves when its subprocess exits** — that one rule replaced a Barrier reconciling five signal sources.
_Avoid_: resolution, running/dead_unresolved/stale_cluster (the retired ChildTracker vocabulary)

**Busy name**:
A config name the Pool refuses to launch under because an earlier process already resolved it (leaderboard row, `broken.txt`) or still has work in flight for it (`state/*_cluster.txt`, an unresolved pending-TSV row). The Pool skips to the next index and says why (`graph/pool.py::_name_busy_reason`). This is what makes a same-prefix relaunch the safe crash-recovery move.

**Eval summary**:
The explicit, typed product of harvest (`harvest.EvalSummary` → `harvest/summary.json`): the primary sob chain plus fail-soft secondary objectives, with a `degraded` record of every extraction that fail-softed. The leaderboard row is derived from it.
_Avoid_: "the summary dict" (implicit 26-key contract)

**Preflight**:
The local 1-event G4 feasibility check gating grid submission; verdicts are `pass` / `fail_managed` / `fail_init` / `ambiguous`.

**Musing**:
The Mu2e Offline environment release (or patched local workdir) sourced for a Mode's preflight and harvest.

**Grid tarball**:
The `Code.tar.bz2` shipped to grid workers; must be built from the same patched Offline the Mode's musing sources, or geometry silently diverges (env-divergence).

## Relationships

- A **Campaign** runs a **Pool**; the Pool keeps q **Children** in its **In-flight set** and replaces each one as it exits; each Child performs one **Eval** and ends in one **Outcome**.
- A **Mode** = one **Study** (`mode_specs/<name>.json`) + one **JsonMode** instance (`core/bo_driver.py`); every Eval belongs to exactly one Mode.
- An Eval runs its Mode's **Stage chain**; **Preflight** gates the first Stage; harvest appends one **Leaderboard** row.
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
- **Adapter** names two unrelated bridges — not resolved, just documented in place (see the Adapter entry): the surrokit-facing one (Study+Leaderboards → the Engine's MCP scaffold, `core/botorch_predict.py`) and the contract-facing one (an existing kit family → the evaluator contract, `core/contract.py`'s `ADAPTERS`, Phase C on). Context disambiguates in practice; a rename was considered and rejected as more churn than the ambiguity is worth.
