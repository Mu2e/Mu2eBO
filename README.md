# autoresearch — closed-loop Bayesian optimization of Mu2e geometry

A botorch GP proposes candidate Mu2e geometries. The contract engine
evaluates each one end to end — geometry render, a local 1-event Geant4
pre-check, grid (or local) Geant4 steps, and the analysis — and the result
lands as a row on the study's leaderboard. The GP refits against the board
and the loop goes on.

**Start here: [QUICKSTART.md](QUICKSTART.md)** — install, check a study,
run a point and a campaign, follow it, read the results.

## How it fits together

- **Study** — one research line in one JSON file, `mode_specs/<name>.json`:
  knobs, geometry, kits, evaluate steps, objectives, leaderboard. Every key
  is required. Format and rules: [mode_specs/README.md](mode_specs/README.md).
- **Kit** — what a step runs on. It speaks one contract,
  `submit`/`status`/`results`. A native kit is an MCP server with one
  `kits.toml` entry (`toykit`, the test kit). The others are in-process
  adapters declared in `core/kit_registry.py`:
  - `prodtools` — builds and submits the Geant4 jobs, grid or local
    ([Mu2e/prodtools](https://github.com/Mu2e/prodtools));
  - `offline_preflight` — the 1-event geometry pre-check (`mu2e -n 1` with
    G4's surface check) from the study's code tarball;
  - `anakit` — M. MacKenzie's analysis server (sob, flash, ce_chain's plot);
  - `beamkit` — G4beamline jobs for `ptg4bl`.
- **Runners** — `graph.run` evaluates one point; `graph.closed_loop` runs a
  campaign (a pool of points, a picker per replacement); `graph.check_study`
  checks a study without submitting anything.
- **Leaderboard** — one TSV per study. Each row carries `measure_sha`, and
  a board holds one measurement only.

## Layout

| path | what |
|---|---|
| `core/` | study loader, engine (contract, scheduler, score), boards, adapters |
| `graph/` | the runners: `run`, `closed_loop`, `check_study` |
| `service/` | the `autoresearch` MCP server (study and campaign tools) and the dashboard |
| `surrogate/` | the `surrogate` MCP server (GP fit, predict, suggest over the boards) |
| `mode_specs/` | the studies |
| `stage_entries/` | the prodtools job templates a step names as its `entry` (hashed into `measure_sha`) |
| `kits.toml` | native kits and the servers the adapters start |
| `tests/` | the test suite (no grid contact) |
| `wiki/` | background, decisions and incidents ([index](wiki/index.md)) |

Domain words are defined in [CONTEXT.md](CONTEXT.md). The engine's design
record is [wiki/drivers/contract-engine.md](wiki/drivers/contract-engine.md).
