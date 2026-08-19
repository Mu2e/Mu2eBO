"""Typed state shared across nodes of the BO iteration graph.

No PEP 604 unions (`X | None`): LangGraph's `get_type_hints` call raises
TypeError on `|` under Python 3.9. Use `Optional`/`Union` until 3.9 drops.

`TypedDict` comes from `typing_extensions`, not `typing`: pydantic 2.13
rejects `typing.TypedDict` on Python <3.12, breaking Studio's input form.
"""
from typing import Dict, List, Literal, Optional
from typing_extensions import TypedDict


PreflightStatus = Literal["pending", "pass", "fail_managed", "fail_init", "ambiguous"]


class StageStatus(TypedDict, total=False):
    cluster_id: Optional[str]
    n_done: int
    n_failed: int
    # Values actually emitted: read_stage_status → "pending"/"in_flight"/
    # "done"; node failure paths → "failed".
    status: Literal["pending", "in_flight", "done", "failed"]
    last_poll_ts: Optional[float]


class BOIterationState(TypedDict, total=False):
    """Per-iteration state, merged by LangGraph between node transitions.

    Not persisted (no checkpointer: 51 campaigns audited, 0 resumes, 5
    incidents caused). Lives only in the child process's memory for one
    eval.
    """

    config_name: str
    # Not a Literal: modes load dynamically from mode_specs/*.json (see
    # tests/test_modes.py::test_keys_match_driver_modes).
    mode: str
    alpha: float

    x_point: List[float]
    geom_path: Optional[str]

    preflight: PreflightStatus

    stages: Dict[str, StageStatus]

    metrics: Optional[dict]
    objective: Optional[float]

    attempts: Dict[str, int]
    errors: List[str]

    # scan_report: {stage: {pattern_code: count}}; scan_report_path is its
    # TSV under scan_logs/. scan_logs_broken=True (physics-breaking
    # patterns, wiki/incidents/tessellated-solid-facet-orientation.md)
    # gates the leaderboard append.
    scan_report: Optional[Dict[str, Dict[str, int]]]
    scan_report_path: Optional[str]
    scan_logs_broken: bool
