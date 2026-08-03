"""Typed state shared across nodes of the BO iteration graph.

Note: PEP 604 union syntax (`X | None`) is not used here because LangGraph's
`StateGraph` calls `typing.get_type_hints` which re-evaluates annotations at
runtime; on Python 3.9 that raises `TypeError: unsupported operand type(s)
for |`. Use `Optional[X]` / `Union[X, Y]` instead until we drop 3.9.

`TypedDict` is imported from `typing_extensions`, not `typing`: pydantic 2.13
(used by langgraph_api for schema introspection) rejects `typing.TypedDict`
on Python <3.12, which prevents Studio from rendering the input form.
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
    """Per-iteration state. Persisted by SqliteSaver between node transitions."""

    config_name: str
    # Mode name. NOT a Literal: JSON-defined modes (mode_specs/*.json) are
    # discovered at import, so the set is not knowable statically. The real
    # completeness check is tests/test_modes.py::test_keys_match_driver_modes,
    # which asserts set(modes.SPECS) == set(bo_driver.MODES).
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

    mock: bool

    # End-of-workflow log scan. `scan_report` is {stage: {pattern_code:
    # total_count}}; `scan_report_path` points at the per-iteration TSV under
    # <grid_root>/<config_name>/scan_logs/. `scan_logs_broken` is set True
    # when scan_logs detects physics-breaking patterns (tessellated-facet
    # GeomSolids1001 floods, see [[tessellated-solid-facet-orientation]]);
    # node_evaluate refuses to append the leaderboard row when set, and the
    # closed-loop refit filters chains whose run dir has state/broken.txt.
    scan_report: Optional[Dict[str, Dict[str, int]]]
    scan_report_path: Optional[str]
    scan_logs_broken: bool
