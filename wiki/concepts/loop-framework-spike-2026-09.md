---
type: concept
title: loop-framework-spike-2026-09 — can libEnsemble or Xopt replace our BO loop?
description: 'throwaway spike (2026-09-23): libEnsemble 1.6.1 and Xopt 3.2.2 both drive surrokit (as a gest-api generator) + an MCP kit evaluator asynchronously with pending points; both lose in-flight evals on a kill until ~20 lines of re-queue code are added, then 0 orphans / 0 duplicate submits; libEnsemble stops exactly at target and refuses a bad restart loudly, Xopt overshoots by up to q-1 and never dumps data in async mode'
status: active
timestamp: '2026-09-23'
---

# loop-framework-spike-2026-09

## Summary
Question: can a standard optimization-loop framework replace
`graph/closed_loop.py` + `graph/pool.py`, with surrokit as the generator and
MCP kits doing the evaluations? Both candidates pass once a small re-queue
fix is added. libEnsemble is the better fit. Code is throwaway, in
`/exp/mu2e/data/users/oksuzian/spike_loopfw/` (not in the repo).

## Setup
- Venv on top of ana 2.8.0 (`uv venv --system-site-packages`), `uv pip
  install xopt libensemble` -> Xopt 3.2.2, libEnsemble 1.6.1, gest-api 0.2.
  `uv pip` ignored ana's site-packages and installed a fresh torch 2.14
  (5.5 GB venv) — an artifact of the install method, not a framework need.
- Fake grid kit: stdio MCP server (mcp 2.0 `MCPServer`), jobs on disk,
  6-19 s wall time standing in for hours, `submit` refuses a reused name
  (like prodtools `submit_once` RunExists).
- One evaluator for both: deterministic job name from x, `status` first
  (adopt if it exists), else `submit`, poll, append one leaderboard row
  (idempotent by config name).
- surrokit wrapped as a gest-api `Generator` (suggest/ingest) that tracks
  pending points itself and passes them to `surrokit.ask(pending=...)`;
  seed `42 ^ round`. q=4, target 16, toy 3D, picker `qnehvi`.

## Results
| test | Xopt (AsynchronousXopt) | libEnsemble (gen on manager, async_return) |
|---|---|---|
| async: new pick while others run | yes | yes |
| pending points reach surrokit | yes (generator tracks) | yes |
| kill -9 mid-run, resume history | yes (after adding a CSV dump) | yes (saved `H` .npy as `H0`) |
| in-flight evals at the kill | orphaned (4 of 4) | orphaned (2 of 2) |
| with re-queue fix | 4/4 adopted, 0 orphans, 0 dup submits | 1/1 adopted, 0 orphans, 0 dup submits |
| stop at target 16 | overshoots: 19 board rows (does not drain) | exactly 16 |
| MCP inside the evaluator | threads share one session | one session per worker process |

## Gotchas found (each cost a run)
- **Xopt deep-copies the generator** at construction; any outside
  reference (hooks, loggers) goes stale.
- **Xopt accepts only its own pydantic `Generator` subclasses**, not a
  plain gest-api generator; libEnsemble takes the plain one.
- **`AsynchronousXopt.add_data` never dumps** (`data_dump_file` is only
  written by the sync path); a killed async run keeps nothing unless you
  dump yourself.
- **Xopt calls `generate(0)`** when every worker is busy; surrokit's Sobol
  cold start raises on n=0.
- **libEnsemble refuses a raw restart**: `H0 contains unreturned or invalid
  points` when the saved history has in-flight rows. Loud, good.
- **libEnsemble hands re-queued H0 rows to the generator with zeroed
  objectives**; set them NaN and have the generator treat non-finite rows
  as pending, or the GP ingests fake zeros.
- surrokit `constrained_max` raises `InfeasibleError` on a 2-row cold
  start with no feasible point; production has priors, the spike used
  `qnehvi`.

## What the fix is
On resume, re-queue the points that were in flight: libEnsemble keeps
those `H0` rows but marks them unstarted (and NaN objectives); Xopt
persists the generator's pending list and `submit_data`s it before `run()`.
The evaluator's adopt-by-name then picks the still-running job up. About
20 lines per framework.

## Not tested
- Real hour-long evaluations and real grid jobs.
- q=20 with libEnsemble `local` comms: workers are forked (`fork` start
  method) processes that each hold a torch import and an MCP session.
- A real MCP kit (prodtools, beamkit) and Kerberos env passthrough inside
  workers.

## Cross-links
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md),
  [surrogate](/drivers/surrogate.md),
  [orchestrator-evaluation-2026-05](/concepts/orchestrator-evaluation-2026-05.md),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md)
- Spec that asked the question: `docs/superpowers/specs/2026-09-22-kit-seam-design.md`
- External: [libEnsemble](https://github.com/Libensemble/libensemble),
  [Xopt](https://github.com/xopt-org/Xopt),
  [gest-api](https://github.com/campa-consortium/gest-api),
  [ensemble_agent](https://github.com/Libensemble/ensemble_agent)

## Open questions / TODO
- Adopt libEnsemble as the loop? Recommendation (2026-09-23): no. Keep
  our loop, make surrokit a gest-api generator, and revisit if HPC
  dispatch, a partner workflow, or recurring loop incidents call for it.
  Awaiting operator sign-off; reasoning in
  `docs/superpowers/specs/2026-09-23-mcp-framework-plan.md` §5.
