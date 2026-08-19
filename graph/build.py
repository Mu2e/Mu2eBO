"""Compile the BO iteration graph and expose it as `graph` for langgraph dev.

Note: when run under `langgraph dev`, the LangGraph platform supplies the
checkpointer (an in-memory SQLite/Postgres store), so the graph is compiled
WITHOUT one. For standalone use (`python -m graph.run` or scripted invokes),
the caller is responsible for wiring a checkpointer at compile time.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling modules importable both as `graph.X` (under `python -m`) and as
# plain `X` (when langgraph_api loads this file as a standalone module).
sys.path.insert(0, str(Path(__file__).parent))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from config import GRID_STAGES  # noqa: E402
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


# Stable node names for each stage; mirrors GRID_STAGES so the checkpointer
# can resume across edits.
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
