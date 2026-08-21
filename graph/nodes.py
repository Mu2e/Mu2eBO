"""Graph nodes for the BO iteration: pure functions, state in → partial
state out (LangGraph merges). Nothing is checkpointed -- durability is the
on-disk artifacts each node writes (cluster.txt, harvest/summary.json, the
leaderboard row)."""
from __future__ import annotations

import time
from typing import Literal

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))  # BO/pipeline modules

from langgraph.graph import END  # noqa: E402

import bo_driver as bo  # noqa: E402
import pipeline_io as pio  # noqa: E402
from paths import GRID_DATA_ROOT  # noqa: E402
from runtime import (  # noqa: E402
    DEFAULT_ALPHA,
    MAX_PROPOSE_RETRIES,
    PRESUBMIT_AFTER,
)
from state import BOIterationState  # noqa: E402


def _record_zero_row(config_name: str, cause: str, tail: str) -> None:
    """Append to <grid_root>/<cfg>/scan_logs/evaluate_zero_row.tsv -- a
    post-mortem sidecar that survives state-dir cleanup."""
    out_dir = GRID_DATA_ROOT / config_name / "scan_logs"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "evaluate_zero_row.tsv"
        new_file = not path.exists()
        tail_clean = (tail or "").replace("\t", " ").replace("\n", " ")[:500]
        with path.open("a") as fh:
            if new_file:
                fh.write("config_name\tcause\ttail\n")
            fh.write(f"{config_name}\t{cause}\t{tail_clean}\n")
        print(
            f"[graph] zero_row[{config_name}] cause={cause} → {path}",
            flush=True,
        )
    except OSError as exc:
        # Sidecar is best-effort — don't break the graph if disk is full.
        print(
            f"[graph] zero_row[{config_name}] sidecar write FAILED: {exc}",
            flush=True,
        )


def node_propose(state: BOIterationState) -> dict:
    """Ask BO for the next x (a populated state["x_point"] forces that point);
    materialize the geom. The attempt counter feeds picker seed_idx so each
    preflight-driven retry draws a fresh point."""
    # Not .get(..., DEFAULT_MODE): a default here would be a second, silent
    # mode-resolution path that could disagree with run.py's stamp.
    mode = state["mode"]
    alpha = state.get("alpha", DEFAULT_ALPHA)
    caller_pinned = bool(state.get("config_name"))
    name = state.get("config_name") or pio.next_config_name(mode)
    forced = state.get("x_point") or None
    seed_idx = state.get("attempts", {}).get("propose", 0)

    try:
        x, geom = pio.propose_one(mode, name, alpha=alpha, x_override=forced,
                                  seed_idx=seed_idx)
    except ValueError:
        if caller_pinned:
            # Re-entry under a pinned name: the ValueError is our own prior
            # pending row. Retry under the SAME name -- renaming would break
            # the --name-prefix contract and trip run.py's swap guard.
            bo.MODES[mode].remove_pending(name)
            x, geom = pio.propose_one(mode, name, alpha=alpha, x_override=forced,
                                      seed_idx=seed_idx)
        else:
            retry_name = pio.next_config_name(mode)
            x, geom = pio.propose_one(mode, retry_name, alpha=alpha,
                                      x_override=forced, seed_idx=seed_idx)
            name = retry_name

    return {
        "config_name": name,
        "mode": mode,
        "alpha": alpha,
        "x_point": x,
        "geom_path": geom,
        "preflight": "pending",
        "stages": {},
        "metrics": None,
        "objective": None,
        "attempts": {**state.get("attempts", {}), "propose": state.get("attempts", {}).get("propose", 0) + 1},
        "errors": state.get("errors", []),
    }


def node_render_preflight(state: BOIterationState) -> dict:
    """Run mu2e -n 1 + surface-check on the proposal.

    pass → grid chain; fail_managed/ambiguous → re-propose bounded by
    MAX_PROPOSE_RETRIES with seed_idx bumped so a real geom bug can't
    infinite-loop on one x
    (wiki/incidents/foilsx04-all-preflight-ambiguous.md); fail_init terminal."""
    mode = state["mode"]
    name = state["config_name"]
    status, tail = pio.run_preflight(mode, name)
    errors = list(state.get("errors", []))
    if status not in ("pass",):
        # Last 8 lines: context across rc=3 retries without one opaque line.
        tail_msg = "\n".join(tail.splitlines()[-8:]) if tail else ""
        errors.append(f"preflight[{status}] {name}: {tail_msg}")
    return {"preflight": status, "errors": errors}


def make_stage_node(stage: str):
    """Build a graph node that runs one stage (submit→poll→list-outputs).
    Idempotency lives in pipeline.py's cluster.txt re-attach -- the only
    resume mechanism (no checkpointer)."""
    def _node(state: BOIterationState) -> dict:
        name = state["config_name"]
        errors = list(state.get("errors", []))
        stages = dict(state.get("stages", {}))
        try:
            stages[stage] = pio.run_stage(name, stage)
            for ps in PRESUBMIT_AFTER.get(stage, ()):
                try:
                    pio.presubmit_stage(name, ps)
                    print(f"[graph] presubmit[{ps}/{name}] submitted early "
                          f"(overlaps rest of chain)", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[graph] presubmit[{ps}/{name}] failed ({exc}); "
                          f"will submit sequentially", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[graph] stage[{stage}/{name}] FAILED: {exc}", flush=True)
            errors.append(f"stage[{stage}/{name}]: {exc}")
            stages[stage] = {
                "cluster_id": None, "status": "failed",
                "n_done": 0, "n_failed": 0, "last_poll_ts": time.time(),
            }
        return {"stages": stages, "errors": errors}
    _node.__name__ = f"node_stage_{stage}"
    return _node


def node_harvest(state: BOIterationState) -> dict:
    """Run pipeline.py harvest; populate metrics from summary.json."""
    name = state["config_name"]
    mode = state["mode"]
    errors = list(state.get("errors", []))
    try:
        metrics = pio.run_harvest(name, mode=mode)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"harvest[{name}]: {exc}")
        _record_zero_row(name, "harvest_exception", str(exc))
        return {"metrics": None, "errors": errors}
    return {"metrics": metrics, "errors": errors}




def node_scan_logs(state: BOIterationState) -> dict:
    """End-of-workflow log scan (pipeline_io.scan_worker_logs); a
    SCAN_BROKEN_CODES hit sets scan_logs_broken=True and node_evaluate then
    refuses to append."""
    name = state["config_name"]
    errors = list(state.get("errors", []))
    try:
        report, report_path, broken = pio.scan_worker_logs(name)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"scan_logs[{name}]: {exc}")
        return {
            "scan_report": None,
            "scan_report_path": None,
            "scan_logs_broken": False,
            "errors": errors,
        }
    if broken:
        errors.append(
            f"scan_logs[{name}]: broken-run patterns detected; leaderboard "
            f"append suppressed (see {report_path})"
        )
    return {
        "scan_report": report,
        "scan_report_path": str(report_path),
        "scan_logs_broken": broken,
        "errors": errors,
    }


def node_evaluate(state: BOIterationState) -> dict:
    """Append the (x, metrics) point to the leaderboard; skipped when
    scan_logs flagged the run broken (physics-invalid metrics would let the
    next BO refit chase a phantom Pareto frontier)."""
    name = state["config_name"]
    errors = list(state.get("errors", []))
    if state.get("scan_logs_broken"):
        errors.append(f"evaluate[{name}]: skipped (scan_logs_broken=True)")
        _record_zero_row(name, "scan_logs_broken",
                         str(state.get("scan_report_path") or ""))
        return {"objective": None, "errors": errors}
    mode = state["mode"]
    alpha = state.get("alpha", DEFAULT_ALPHA)
    metrics = state["metrics"]
    if metrics is None:
        errors.append(f"evaluate[{name}]: metrics is None (harvest produced no row)")
        _record_zero_row(name, "metrics_none", "")
        return {"objective": None, "errors": errors}
    obj, tail = pio.run_evaluate(mode, name, metrics, alpha=alpha)
    if obj is None:
        errors.append(f"evaluate[{name}]: could not parse objective; tail={tail}")
        _record_zero_row(name, "obj_unparseable", tail or "")
    return {"objective": obj, "errors": errors}


def route_after_preflight(state: BOIterationState) -> Literal["real", "propose", "__end__"]:
    """Branch after preflight: pass → real; fail_managed/ambiguous re-propose
    up to MAX_PROPOSE_RETRIES; fail_init terminal."""
    status = state.get("preflight", "pending")
    attempts = state.get("attempts", {}).get("propose", 0)
    if status == "pass":
        return "real"
    if status in ("fail_managed", "ambiguous") and attempts < MAX_PROPOSE_RETRIES:
        return "propose"
    name = state.get("config_name", "?")
    print(
        f"[graph] terminating {name}: preflight={status} "
        f"attempts={attempts}/{MAX_PROPOSE_RETRIES}",
        flush=True,
    )
    return END


def route_after_stage(state: BOIterationState) -> Literal["next", "__end__"]:
    """Fail-fast: one failed stage terminates the iteration so evaluate never
    runs on partial metrics."""
    stages = state.get("stages", {}) or {}
    failed = [k for k, s in stages.items() if (s or {}).get("status") == "failed"]
    if failed:
        name = state.get("config_name", "?")
        print(
            f"[graph] terminating {name}: stage {failed[0]} failed "
            f"(failed_stages={failed})",
            flush=True,
        )
        return END
    return "next"
