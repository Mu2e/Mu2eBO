# Autoresearch — closed-loop BO over Mu2e geometry

Machinery that proposes detector-geometry variants (Bayesian optimization),
evaluates them on FermiGrid through Geant4 simulation chains, and accumulates
results in per-mode leaderboards. This file defines the domain language;
architecture decisions live in `docs/adr/`, operational knowledge in `wiki/`.

## Language

### Optimization

**Mode**:
One research line's complete definition — search space, geometry renderer, stage chain, environment, objectives (e.g. `foilsflash`, `ipa`).
_Avoid_: study, campaign type

**ModeSpec**:
The pure-data half of a Mode (musing, grid tarball, stage chain, harvest verb, stage targets, bounds, preflight policy), declared once in `core/modes.py`.
_Avoid_: mode config, mode table, per-mode dict

**BOMode**:
The behavior half of a Mode (render geometry, load priors, format leaderboard rows), a driver class bound to its ModeSpec.

**Eval**:
One geometry point evaluated end-to-end; identified by its config name, which keys the state dir, grid dirs, and leaderboard row.
_Avoid_: trial, run (overloaded)

**Campaign**:
One closed-loop invocation — a name-prefix, q parallel evals per round, a round budget (e.g. `foilsflash08`, q=20×2).

**Round**:
One propose → launch → barrier → refit cycle inside a campaign.

**Picker**:
The between-rounds proposal strategy that turns leaderboard history into the next round's points (`qnehvi`, `qlnei`, `pareto_sob`).

**Leaderboard**:
The append-only per-mode TSV of completed evals; the durable source of truth for BO history (checkpoints are resume-convenience only).

### Execution

**Stage**:
One grid-submission unit in an eval's chain (`mubeam`, `concat`, `mustops_ce`, `elebeam_flash`, …) driven by idempotent submit/poll/list-outputs verbs.

**Stage chain**:
The ordered stages one eval runs; declared per Mode.

**Child**:
One `graph.run` subprocess evaluating one config inside a round.

**Barrier**:
The campaign parent's wait until every launched child reaches a Resolution.

**Resolution**:
The ChildTracker's classification of a child: `running`, `done_row`, `done_broken`, `done_terminal_no_row`, `dead_unresolved`, or `stale_cluster`.
_Avoid_: completed/resolved (ambiguous — say which Resolution)

**ChildTracker**:
The per-round module that owns child Resolution — including the dead-PID grace ticks — behind a single `tick()` interface.

**Signals adapter**:
The injected reader of the five raw child signals (leaderboard row, broken.txt, terminal checkpoint, PID liveness, cluster.txt); production adapter reads disk/SQLite, tests inject a fake.

**Eval summary**:
The explicit, typed product of harvest (`harvest.EvalSummary` → `harvest/summary.json`): the primary sob chain plus fail-soft secondary objectives, with a `degraded` record of every extraction that fail-softed. The leaderboard row is derived from it.
_Avoid_: "the summary dict" (implicit 26-key contract)

**Stage-chain stamp**:
`state/stage_chain.txt`, written at first submit — the one owner of "which stages ran for THIS Eval" (e.g. did concat run). Harvest and template materialization read the stamp (legacy fallback: file presence), never the process env.

**Preflight**:
The local 1-event G4 feasibility check gating grid submission; verdicts are `pass` / `fail_managed` / `fail_init` / `ambiguous`.

**Musing**:
The Mu2e Offline environment release (or patched local workdir) sourced for a Mode's preflight and harvest.

**Grid tarball**:
The `Code.tar.bz2` shipped to grid workers; must be built from the same patched Offline the Mode's musing sources, or geometry silently diverges (env-divergence).

## Relationships

- A **Campaign** runs **Rounds**; each Round launches q **Children**; each Child performs one **Eval**.
- A **Mode** = one **ModeSpec** (data) + one **BOMode** (behavior); every Eval belongs to exactly one Mode.
- An Eval runs its Mode's **Stage chain**; **Preflight** gates the first Stage; harvest appends one **Leaderboard** row.
- The **Barrier** consumes only **Resolutions** from the **ChildTracker**, which reads raw signals through the **Signals adapter**.
- The **Picker** consumes the **Leaderboard** and produces the next Round's points.

## Example dialogue

> **Dev:** "foilsflash08R00_07's process died — is the round stuck?"
> **Domain expert:** "No. The **ChildTracker** gives it two grace ticks in case the **Leaderboard** append was racing the crash, then resolves it `dead_unresolved`; the **Barrier** counts it and the Round proceeds with 19 **Evals**."
> **Dev:** "And if I add a new **Mode**, where do its stage targets go?"
> **Domain expert:** "Its **ModeSpec** in `core/modes.py` — every field is required, so forgetting the **Grid tarball** is an import error, not a silent michael fallback."

## Flagged ambiguities

- "config" was used for both an Eval's identity and per-mode settings — resolved: an Eval has a *config name*; per-mode settings are the **ModeSpec**.
- "completed" in closed_loop.py mixed done-with-row, done-broken, and died-unresolved — resolved: use the specific **Resolution** value.
- "mode tables" (the scattered `*_BY_MODE` dicts) — superseded by **ModeSpec** (see ADR-0002).
