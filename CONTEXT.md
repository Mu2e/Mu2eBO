# Autoresearch — closed-loop BO over Mu2e geometry

Machinery that proposes detector-geometry variants (Bayesian optimization),
evaluates them on FermiGrid through Geant4 simulation chains, and accumulates
results in per-mode leaderboards. This file defines the domain language;
architecture decisions live in `docs/adr/`, operational knowledge in `wiki/`.

## Language

### Optimization

**Mode**:
One research line's complete definition — search space, geometry renderer, stage chain, environment, objectives (e.g. `foilsflash`, `foilspfbpz`).
_Avoid_: study, campaign type

**ModeSpec**:
The pure-data half of a Mode (musing, grid tarball, stage chain, stage targets, bounds, preflight policy, leaderboard schema), declared once per Mode as `mode_specs/<name>.json` and loaded into `core.modes.SPECS`.
_Avoid_: mode config, mode table, per-mode dict

**JsonMode**:
The behavior half of a Mode (render geometry, recover x at evaluate time, read and append leaderboard rows), one driver object per ModeSpec (`core/bo_driver.py`). There is exactly one class — the `BOMode` ABC and its five Python subclasses were retired 2026-08-08.

**Eval**:
One geometry point evaluated end-to-end; identified by its config name, which keys the state dir, grid dirs, and leaderboard row.
_Avoid_: trial, run (overloaded)

**Campaign**:
One closed-loop invocation — a name-prefix, a pool width q, and an eval budget (e.g. `foilspf05`, `--q 20 --max-evals 40`).

**Pool**:
The campaign parent (`graph/pool.py::run_rolling`): keeps q Children in flight and launches exactly one replacement each time one exits, until the eval budget is spent and the pool drains. It has no rounds — the GP is refit per pick, against the leaderboard as it stands at that moment.
_Avoid_: round, batch, wave (all retired 2026-08-19)

**Picker**:
The proposal strategy that turns leaderboard history into the next point(s) — `hybrid`, `qnehvi`, `qlnei`, `budget_sob`, declared once as `core.modes.PICKER_CHOICES` and accepted by both the parent and the picker subprocess. Runs once per replacement launch, in a subprocess, over the current In-flight set as `X_pending`.

**Leaderboard**:
The append-only per-mode TSV of completed evals; the ONLY durable source of truth for BO history. There is no checkpointer (retired 2026-08-19) and no other resume state.

### Execution

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
- A **Mode** = one **ModeSpec** (`mode_specs/<name>.json`) + one **JsonMode** instance (`core/bo_driver.py`); every Eval belongs to exactly one Mode.
- An Eval runs its Mode's **Stage chain**; **Preflight** gates the first Stage; harvest appends one **Leaderboard** row.
- The **Pool** learns a Child's **Outcome** from its exit code plus two artifacts (leaderboard row, `broken.txt`); it never polls, and it never resolves a Child that has not exited.
- The **Picker** consumes the **Leaderboard** and produces the next point, once per replacement launch.

## Example dialogue

> **Dev:** "foilspf05R07_00's process died — is the campaign stuck?"
> **Domain expert:** "No. Its subprocess exited, so the **Pool** has its **Outcome** — nonzero rc, no row — logs it, and launches a replacement. Nothing waits on it. If it had HUNG instead of died, the Pool would still be waiting, and would say so every 15 minutes in the parent log."
> **Dev:** "And if I add a new **Mode**, where do its stage targets go?"
> **Domain expert:** "Its **ModeSpec** — a new `mode_specs/<name>.json`. Every field is required, so forgetting the **Grid tarball** is a load error, not a silent fallback to another mode's."

## Flagged ambiguities

- "config" was used for both an Eval's identity and per-mode settings — resolved: an Eval has a *config name*; per-mode settings are the **ModeSpec**.
- "completed" in closed_loop.py mixed done-with-row, done-broken, and died-unresolved — resolved: use the specific **Outcome** reason. (The whole Barrier/ChildTracker/Resolution vocabulary this replaced was deleted 2026-08-19 with the parent rewrite; see `docs/superpowers/specs/2026-08-19-minimal-foilspf-workflow-design.md`.)
- "mode tables" (the scattered `*_BY_MODE` dicts) — superseded by **ModeSpec** (see ADR-0002).
