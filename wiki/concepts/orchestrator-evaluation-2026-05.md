---
type: concept
title: orchestrator-evaluation-2026-05 — choosing a workflow engine for the BO loop
description: why LangGraph (vs Prefect 3) was chosen for Phase 1; revisit at end
  of Phase 2
status: active
timestamp: '2026-05-19'
---

# orchestrator-evaluation-2026-05 — choosing a workflow engine for the BO loop

## Summary
Notes from the 2026-05 evaluation of three orchestrator options for the BO
loop (LangGraph vs Prefect 3 vs LangGraph+Prefect hybrid). LangGraph was
chosen for Phase 1 with the caveat that Prefect 3 may be re-evaluated if Phase
2 friction is high. Key shape of the workload: ~95–140 min/iteration across
four grid stages, multi-day wall, single operator, no LLM nodes today.

## Key facts
- **3 parallel research agents** (official patterns, community examples, HEP comparative)
  surveyed the choice. 2 of 3 recommended Prefect 3; the user chose LangGraph anyway
  to keep open the door to LLM-driven decision nodes later.
- **Why Prefect was the consensus pick**: it has scheduling, retry policies, run
  history, dashboards, SLAs out of the box; LangGraph is shaped for in-agent
  control flow, not top-level orchestration. The HEP comparative agent flagged
  no LangGraph BO/HPO closed-loop examples in the wild; closest HEP precedent
  is `SNIFS-science/prefect-hpc-worker` (SLURM, adaptable to Condor).
- **Why LangGraph still works for this**: `interrupt()` + `Command(resume=...)`
  pattern covers multi-hour waits; `SqliteSaver` checkpointer survives crashes;
  Studio gives visual step-through. The minor patterns we're missing (cron,
  retry policy, dashboards) are easy to add ourselves.
- **Python 3.11+ required**: `langgraph dev` (the in-mem server) hard-fails on
  3.9 with "Note: The in-mem server requires Python 3.11 or higher". The Mu2e
  GPVM is RHEL 9 / Python 3.9.25; we installed CPython 3.11.15 via `uv venv
  --python 3.11`.
- **uv cache must live in `/exp` not `/nashome`**: `/nashome` quota is ~2 GB
  available (94% used); a fresh langgraph venv pulls ~300 MB of grpcio +
  langchain-core. Set `UV_CACHE_DIR=/exp/mu2e/app/users/oksuzian/uv_cache`.
- **`langgraph dev` loads entrypoint as a standalone file** (not as a package),
  so `from .nodes import ...` fails with "attempted relative import with no
  known parent package". Use `sys.path.insert(0, str(Path(__file__).parent))`
  + absolute imports.
- **No checkpointer at compile under `langgraph dev`** — the platform supplies
  one. Headless invocation (`graph/run.py`) wires `SqliteSaver` itself.
- **Studio over SSH**: `ssh -L 2024:127.0.0.1:2024 mu2egpvm03` then open
  `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`.
- **`--allow-blocking` flag required** because `pipeline_io.run_preflight`
  is synchronous `subprocess.run`.

## Cross-links
- Related: [graph-runner](/drivers/graph-runner.md), [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md), [batch-bo](/concepts/batch-bo.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md)
- External: [LangGraph docs](https://langchain-ai.github.io/langgraph/),
  [Prefect 3 docs](https://docs.prefect.io/), [SNIFS-science/prefect-hpc-worker](https://github.com/SNIFS-science/prefect-hpc-worker)

## Open questions / TODO
- Re-evaluate at end of Phase 2 (real grid wiring): is the per-stage submit/poll
  retry logic clean in LangGraph, or are we reaching for Prefect's cron + retry
  policy + run history? If yes → migrate.
