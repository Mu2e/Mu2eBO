"""Compile the BO iteration graph: one eval, one chain.

No checkpointer: this graph compiles bare. Durability comes from the
on-disk artifacts the nodes write; the only resume is per-stage
cluster.txt idempotency in core/pipeline.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Importable both as `graph.X` (python -m) and plain `X` (langgraph_api
# loading this file standalone).
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


# GRID_STAGES resolves from AUTORESEARCH_MODE at core/runtime.py import
# time -- mode-dependent, so graph/run.py must stamp --mode before
# importing this module (core/modes.py::stamp_mode_from_argv).
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
    # evaluate is terminal for one iteration; graph/closed_loop.py drives
    # multi-round BO from outside.
    g.add_edge("evaluate", END)
    return g

