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

Nothing here submits jobs, launches a campaign or writes a board: the only
writes are the draft (study_drafts/<name>.json under the data root) and the
job's own directory (check_jobs/<job_id>/).
"""

svc = CheckService()
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


if __name__ == "__main__":
    server.run("stdio")
