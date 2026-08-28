#!/usr/bin/env python3
"""MCP adapter over the surrogate package — thin by design.

Every tool is a one-line delegation to surrogate/__init__.py; all GP logic
stays in core/botorch_predict.py. Uses the official `mcp` SDK (2.0, ships in
the ana 2.8.0 cvmfs env — the project's default interpreter — so there is
nothing to install). Transport is stdio; register in .mcp.json:

    {"mcpServers": {"surrogate": {
        "command": "/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python",
        "args": ["surrogate/mcp_server.py"]}}}

Fits are cached in this process and refreshed automatically when the
leaderboard grows (row-count key in surrogate.fit). A future auth/logging
layer plugs into MCPServer(middleware=[...]) without touching the tools.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import surrogate  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer(
    name="autoresearch-surrogate",
    instructions=(
        "GP surrogate over the autoresearch BO leaderboards (Mu2e geometry "
        "optimization). The GP is the project's fast sim: predict() gives "
        "posterior mean/sigma for sob and the mode's second objective "
        "(calo/flash) at any x in the mode's search box; suggest() runs the "
        "production acquisition pickers. Call list_modes first to see knob "
        "names, bounds and dimensionality. Nothing here submits jobs or "
        "writes to leaderboards — pure read + compute."
    ),
)


@server.tool(structured_output=True)
def list_modes() -> dict[str, Any]:
    """Registered BO modes: dims, knob names, bounds, objectives, row counts."""
    return surrogate.modes_info()


@server.tool(structured_output=True)
def predict(mode: str, points: list[list[float]]) -> list[dict[str, float]]:
    """GP posterior at each point (list of knob-vectors in mode order):
    sob mean/sigma and second-objective mean with 1-sigma interval."""
    return surrogate.predict(mode, points)


@server.tool(structured_output=True)
def suggest(mode: str, q: int = 5, picker: str = "hybrid",
            round_idx: int = 0) -> list[list[float]]:
    """Candidate x-points from the production pickers
    (qnehvi | qlnei | budget_sob | hybrid). Pure computation, no submission."""
    return surrogate.suggest(mode, q=q, picker=picker, round_idx=round_idx)


@server.tool(structured_output=True)
def board_stats(mode: str) -> dict[str, Any]:
    """Leaderboard summary for a mode: row count, champion, sob range."""
    return surrogate.board_stats(mode)


@server.tool(structured_output=True)
def refit(mode: str) -> dict[str, Any]:
    """Force a GP refit on the current leaderboard (cache bypass)."""
    surrogate.fit(mode, refresh=True)
    return {"mode": mode, "refit": True,
            "n_rows": surrogate.board_stats(mode)["n_rows"]}


if __name__ == "__main__":
    server.run("stdio")
