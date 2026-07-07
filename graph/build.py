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
    node_decide_next,
    node_evaluate,
    node_harvest,
    node_mock_grid,
    node_propose,
    node_render_preflight,
    node_scan_logs,
    route_after_decide,
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
    g.add_node("mock_grid", node_mock_grid)
    g.add_node("evaluate", node_evaluate)
    g.add_node("decide_next", node_decide_next)

    g.add_edge(START, "propose")
    g.add_edge("propose", "render_preflight")
    g.add_conditional_edges(
        "render_preflight",
        route_after_preflight,
        {
            "real": STAGE_NODES[GRID_STAGES[0]],
            "mock": "mock_grid",
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
    g.add_edge("mock_grid", "evaluate")
    g.add_edge("evaluate", "decide_next")
    g.add_conditional_edges(
        "decide_next",
        route_after_decide,
        {"propose": "propose", END: END},
    )
    return g


def is_child_terminal(thread_id: str, child_graph) -> bool:
    """True iff the child thread has reached a real terminal state.

    `CheckpointTuple` does not expose `next`; only `StateSnapshot` (returned
    by `compiled_graph.get_state(cfg)`) does. The caller compiles the inner
    graph once against the shared SqliteSaver and passes it in — per-tick
    recompile costs ~O(q * ticks_per_round) wasted compiles (see
    wiki/concepts/closed-loop-bo-design.md).

    Empty `snap.next` is ambiguous: it means the graph is terminal OR the
    thread has no checkpoint at all (freshly-spawned subprocess that
    hasn't flushed its first state yet). Round-N children are launched
    in parallel and the barrier polls within seconds; without
    disambiguation, every fresh child is mis-resolved on the first
    barrier tick — closed-loop declares premature convergence and exits.
    See wiki/incidents/barrier-false-positive-round1.md.

    Disambiguation: a real terminal state has both populated `values` AND
    `metadata.step >= 1` (at least one super-step executed). Fresh threads
    return empty `values` and `step == -1` from LangGraph's SqliteSaver.
    """
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        snap = child_graph.get_state(cfg)
    except Exception:
        return False
    if snap is None or snap.next:
        return False
    if not snap.values:
        return False
    meta = getattr(snap, "metadata", None) or {}
    return meta.get("step", -1) >= 1


graph = build_graph().compile()
