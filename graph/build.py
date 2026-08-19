"""Compile the BO iteration graph: one eval, one chain.

There is no checkpointer anywhere. `graph/run.py` compiles this graph bare
(the SqliteSaver was retired 2026-08-19; the `langgraph dev` Studio overlay
that used to supply its own was retired 2026-07-17). Durability is the
on-disk artifacts the nodes write, and the only resume is per-stage
cluster.txt idempotency in core/pipeline.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling modules importable both as `graph.X` (under `python -m`) and as
# plain `X` (when langgraph_api loads this file as a standalone module).
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from runtime import GRID_STAGES  # noqa: E402
from nodes import (  # noqa: E402
    make_stage_node,
    node_evaluate,
    node_harvest,
    node_propose,
    node_render_preflight,
    node_scan_logs,
    route_after_preflight,
    route_after_stage,
)
from state import BOIterationState  # noqa: E402


# Stable node names for each stage; mirrors GRID_STAGES. Note GRID_STAGES is
# resolved from AUTORESEARCH_MODE at core/runtime.py import time, so the
# child's stage chain IS mode-dependent -- which is why graph/run.py must
# stamp the mode from --mode before importing this module
# (core/modes.py::stamp_mode_from_argv).
STAGE_NODES = {stage: f"stage_{stage}" for stage in GRID_STAGES}


def build_graph() -> StateGraph:
    g = StateGraph(BOIterationState)
    g.add_node("propose", node_propose)
    g.add_node("render_preflight", node_render_preflight)
    for stage, node_name in STAGE_NODES.items():
        g.add_node(node_name, make_stage_node(stage))
    g.add_node("harvest", node_harvest)
    g.add_node("scan_logs", node_scan_logs)
    g.add_node("evaluate", node_evaluate)

    g.add_edge(START, "propose")
    g.add_edge("propose", "render_preflight")
    g.add_conditional_edges(
        "render_preflight",
        route_after_preflight,
        {
            "real": STAGE_NODES[GRID_STAGES[0]],
            "propose": "propose",
            END: END,
        },
    )

    # Linear stage chain with a shared "fail-fast" guard.
    stage_names = list(STAGE_NODES.values())
    for prev, nxt in zip(stage_names, stage_names[1:]):
        g.add_conditional_edges(prev, route_after_stage, {"next": nxt, END: END})
    g.add_conditional_edges(
        stage_names[-1], route_after_stage, {"next": "harvest", END: END}
    )

    g.add_edge("harvest", "scan_logs")
    g.add_edge("scan_logs", "evaluate")
    # evaluate is terminal for a single iteration; the OUTER round loop
    # (graph/closed_loop.py) drives multi-round BO. The inner graph never
    # loops back — the old auto_continue/decide_next path had no writer and
    # was removed 2026-07-12.
    g.add_edge("evaluate", END)
    return g


graph = build_graph().compile()
