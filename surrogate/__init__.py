"""Package marker for the MCP surrogate door.

The importable plain-Python facade that used to live here (`fit`,
`predict`, `suggest`, `board_stats`, `modes_info`) was DELETED
2026-09-22: a repo-wide plus off-repo sweep found zero callers outside
its own test file four weeks after the 2026-08-28 agreement that made it
a published seam, and 4 of its 5 functions duplicated what
surrokit.mcp_scaffold.make_server generates (including a byte-identical
fit cache). Its one piece of unique behavior, the leaderboard summary,
moved to adapter._board_summary and now rides the MCP `stats` tool.

What remains:
    adapter.py     AutoresearchAdapter -- problems/history/suggest over
                   the studies (modes.STUDIES), the production pick path.
    mcp_server.py  make_server(AutoresearchAdapter()) on stdio.

Plain-Python clients should import core/botorch_predict.py directly
(build_problem + load_history_tensor + compute_explore_picks are the
same seam the adapter and the closed loop use).
"""
