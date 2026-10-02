#!/usr/bin/env python3
"""The autoresearch MCP server: study tools over stdio, each a thin wrapper
over service/checks.py's CheckService (spec
docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md). Registered in
.mcp.json. The campaign tools planned for this server come later.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from service.campaigns import CampaignService  # noqa: E402
from service.checks import CheckService  # noqa: E402

INSTRUCTIONS = """\
Study tools for autoresearch: write a study file and have it checked exactly
as `python -m graph.check_study` checks it (it loads, its ${ARTIFACT} paths
exist, the launch check passes, the geometry passes the pre-check at the
middle of the knob box).

The loop: read study_guide (mode_specs/README.md, "From draft to launch");
draft the study, starting from the nearest one (list_studies, show_study),
with a new name and a new leaderboard.file; start_check(study_json=...);
call check_result(job_id) every 30-60 s while its state is "running" (a
geometry pre-check takes about 6 minutes); fix the draft from each failed
check's "problems" and "detail" and start again. Install the file only with
the operator's OK, then check it again by name.

Exit codes in check_result: 0 every check passed; 1 a check failed (the
report says which and why); 2 a bad target, --x or executor (see
stderr_tail); 3 check_study itself broke (see report.error). A check passed
only when exit_code is 0 and report.ok is true. When `error` is set there is
no report, and the exit code is not check_study's verdict (activate.sh
failed, or the job was killed): read stderr_tail, and do not edit the draft
over it. A check that fails with "another check_study of '<name>' is
running" means wait and start again, not edit the draft. State "lost" means
the job was killed before it ended.

The study tools submit no job, launch no campaign and write no board: their
only writes are the draft (study_drafts/<name>.json under the data root) and
the job's own directory (check_jobs/<job_id>/).

Campaigns: always call start_campaign with confirm=false first. That is a dry
run: closed_loop's own launch checks, the exact command and the job budget,
with nothing launched. Show the operator its command, problems and budget,
and call confirm=true only with the operator's OK: a launched campaign
submits real grid jobs and writes leaderboard rows. One launch per prefix: a
refused launch spends it, so dry-run again under a new prefix. Follow a
campaign with campaign_status every few minutes, not seconds (a grid point
takes hours). stop_campaign stops new launches; running children finish.
leaderboard shows a study's rows, best first by its first objective.
"""

svc = CheckService()
campaigns = CampaignService()
server = MCPServer("autoresearch", instructions=INSTRUCTIONS)


@server.tool(structured_output=True)
def start_check(study: str = "", study_json: dict[str, Any] | None = None,
                x: list[float] | None = None, executor: str = "grid",
                parallel: int | None = None) -> dict[str, Any]:
    """Start checking a study; returns {job_id, target, command} at once.
    Give exactly one of `study` (a name on the study path, or a .json path)
    and `study_json` (the study itself, saved as study_drafts/<name>.json).
    `x`: knob values in the study's knob order (default the middle of each
    knob's bounds); `executor`: "grid" or "local"; `parallel`: with "local"
    only. Poll check_result(job_id) for the report."""
    return svc.start_check(study, study_json, x, executor, parallel)


@server.tool(structured_output=True)
def check_result(job_id: str) -> dict[str, Any]:
    """A check's {job_id, state ("running" | "done" | "lost"), exit_code,
    elapsed_s, report (check_study's JSON report), stderr_tail, error}."""
    return svc.check_result(job_id)


@server.tool(structured_output=True)
def list_studies() -> list[dict[str, Any]]:
    """Every study file on the study path (mode_specs/ and
    $AUTORESEARCH_STUDY_PATH): {name, path, loads, error, knobs, objectives,
    board}; a file that does not load has loads false and its error."""
    return svc.list_studies()


@server.tool(structured_output=True)
def show_study(name: str) -> dict[str, Any]:
    """One study file by name: {path, study (the file's JSON)}."""
    return svc.show_study(name)


@server.tool(structured_output=True)
def study_guide() -> str:
    """How to write a study: the text of mode_specs/README.md."""
    return svc.study_guide()


@server.tool(structured_output=True)
def start_campaign(study: str, name_prefix: str, q: int, max_evals: int,
                   picker: str = "hybrid", executor: str = "grid",
                   parallel: int | None = None,
                   context: list[str] | None = None,
                   stagger: float | None = None,
                   confirm: bool = False) -> dict[str, Any]:
    """A graph.closed_loop campaign. confirm=false (the default) is a dry
    run: {ok, problems, command, budget, output_tail, error}, nothing
    launched. confirm=true launches it detached and returns {state:
    "launched" | "refused" | "starting", ...}; only with the operator's OK.
    context: "name=value" strings."""
    return campaigns.start_campaign(study, name_prefix, q, max_evals, picker,
                                    executor, parallel, context, stagger,
                                    confirm)


@server.tool(structured_output=True)
def stop_campaign(name_prefix: str) -> dict[str, Any]:
    """Stop launching new children (the campaign's STOP file); running
    children finish. {stop_file, parent_alive, children_running, warning}."""
    return campaigns.stop_campaign(name_prefix)


@server.tool(structured_output=True)
def campaign_status(name_prefix: str | None = None) -> dict[str, Any]:
    """One campaign: {prefix, study, parent, stopping, children, rows, best,
    board_error}. With no prefix: {campaigns: [{prefix, study, alive,
    launched_by}]}, including campaigns started from a shell."""
    out = campaigns.campaign_status(name_prefix)
    return {"campaigns": out} if name_prefix is None else out


@server.tool(structured_output=True)
def leaderboard(study: str, name_prefix: str | None = None,
                top: int = 20) -> dict[str, Any]:
    """A study's board: {study, board, n_rows, objective, rows}, rows best
    first by the first objective, optionally one campaign's only."""
    return campaigns.leaderboard(study, name_prefix, top)


if __name__ == "__main__":
    server.run("stdio")
