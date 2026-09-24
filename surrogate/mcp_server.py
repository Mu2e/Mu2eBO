#!/usr/bin/env python3
"""MCP adapter over the surrogate package — thin by design.

Rides surrokit's generic mcp_scaffold.make_server: every tool
(list_problems, predict, suggest, stats, refit) is generated from the
AutoresearchAdapter's problems()/history() over the studies (modes.STUDIES).
All GP logic lives in surrokit (core/botorch_predict.py stays the
production picker CLI). Uses the official `mcp` SDK (2.0, ships in the
ana 2.8.0 cvmfs env -- the project's default interpreter -- so there is
nothing to install). Transport is stdio; register in .mcp.json:

    {"mcpServers": {"surrogate": {
        "command": "/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python",
        "args": ["surrogate/mcp_server.py"]}}}

Tool names changed from the pre-surrokit adapter: list_modes -> list_problems,
board_stats -> stats; refit is unchanged. .mcp.json consumers re-learn the
new names on next session start.

Fits are cached in this process and refreshed automatically when the
leaderboard grows (row-count key inside surrokit.mcp_scaffold). A future
auth/logging layer plugs into make_server(middleware=[...]) without
touching the tools.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surrogate.adapter import AutoresearchAdapter  # noqa: E402
from surrokit.mcp_scaffold import make_server  # noqa: E402

server = make_server(
    AutoresearchAdapter(),
    name="autoresearch-surrogate",
    instructions=(
        "GP surrogate over the autoresearch leaderboards. Problems are the "
        "registered studies. Every output axis is MAXIMIZED; stats(problem)"
        ".objectives gives each axis's name, direction, transform and label "
        "(e.g. '-log10(flash_edep)'), .knobs gives names, units and "
        "bounds, and .best gives the champion by the primary objective as "
        "{config, x, values: {name: value}}, with .primary_range its "
        "observed [min, max]. suggest() IS the production pick path (qnehvi | qlnei | "
        "budget_sob | hybrid, seed derived from round_idx exactly as the "
        "closed loop does). Nothing here submits jobs or writes to "
        "leaderboards -- pure read + compute."
    ),
)

if __name__ == "__main__":
    server.run("stdio")
