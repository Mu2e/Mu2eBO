"""Typed state shared across nodes of the BO iteration graph.

No PEP 604 unions: LangGraph's get_type_hints raises TypeError on `|` under
Python 3.9. TypedDict from typing_extensions: pydantic 2.13 rejects
typing.TypedDict on Python <3.12 (breaks Studio's input form)."""
from typing import Dict, List, Literal, Optional
from typing_extensions import TypedDict


PreflightStatus = Literal["pending", "pass", "fail_managed", "fail_init", "ambiguous"]


class StageStatus(TypedDict, total=False):
    cluster_id: Optional[str]
    n_done: int
    n_failed: int
    status: Literal["pending", "in_flight", "done", "failed"]
    last_poll_ts: Optional[float]


class BOIterationState(TypedDict, total=False):
    """Per-iteration state, merged by LangGraph between nodes; not persisted
    (no checkpointer), lives only in the child process for one eval."""

    config_name: str
    # Not a Literal: modes load dynamically from mode_specs/*.json.
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

    # scan_logs_broken=True gates the leaderboard append
    # (wiki/incidents/tessellated-solid-facet-orientation.md).
    scan_report: Optional[Dict[str, Dict[str, int]]]
    scan_report_path: Optional[str]
    scan_logs_broken: bool
