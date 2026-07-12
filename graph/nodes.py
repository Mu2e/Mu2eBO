"""Graph nodes for the BO iteration (Phase 1: mock grid).

Each node is a pure function: state in → partial state out. LangGraph merges
the returned dict into the running state and checkpoints it.
"""
from __future__ import annotations

import time
from typing import Literal

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langgraph.graph import END  # noqa: E402

import autoresearch_bo_michael as bo  # noqa: E402
import pipeline_io as pio  # noqa: E402
from config import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRID_DATA_ROOT,
    MAX_PROPOSE_RETRIES,
    PRESUBMIT_AFTER,
)
from state import BOIterationState  # noqa: E402


def _record_zero_row(config_name: str, cause: str, tail: str) -> None:
    """Append a row to <grid_root>/<config_name>/scan_logs/evaluate_zero_row.tsv.

    Sidecar survives state-dir cleanup so post-mortem of silent zero-objective
    closed-loop children doesn't depend on graph_data/state/<child>/. See #8.
    """
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
    """Ask the BO model for the next x; materialize the geom file.

    If state["x_point"] is already populated, skip the BO ask and force that
    point (used to evaluate GP-Pareto picks).
    """
    mode = state.get("mode", DEFAULT_MODE)
    alpha = state.get("alpha", DEFAULT_ALPHA)
    caller_pinned = bool(state.get("config_name"))
    name = state.get("config_name") or pio.next_config_name(mode)
    forced = state.get("x_point") or None

    try:
        x, geom = pio.propose_one(mode, name, alpha=alpha, x_override=forced)
    except ValueError:
        if caller_pinned:
            # Re-entry with the same caller-pinned name (preflight
            # ambiguous/fail_managed → route_after_preflight loops to
            # propose). The ValueError here can only be the pending-row
            # collision from our own prior attempt: graph topology never
            # lets a child reach leaderboard-append under a caller-pinned
            # name before re-entering propose. Drop the stale pending row
            # and retry under the SAME name — silent-renaming would break
            # the closed-loop --name-prefix contract and trip the
            # config_name swap guard in graph/run.py.
            bo.MODES[mode].remove_pending(name)
            x, geom = pio.propose_one(mode, name, alpha=alpha, x_override=forced)
        else:
            # Auto-named path (no --config-name on the CLI): a true name
            # collision means a concurrent runner picked the same auto-name;
            # fork to the next free name.
            retry_name = pio.next_config_name(mode)
            x, geom = pio.propose_one(mode, retry_name, alpha=alpha, x_override=forced)
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
        "mock": state.get("mock", True),
    }


def node_render_preflight(state: BOIterationState) -> dict:
    """Run mu2e -n 1 + surface-check on the proposal.

    Outcomes:
    - pass → real/mock grid chain
    - fail_managed → retry propose (managed-volume overlap, BO-fixable)
    - ambiguous (rc=3) → retry propose. rc=3 = subprocess died early
      without a regex-matchable G4 init signature (OOM under concurrent
      preflight load, transient FS, host load). Treated as retriable
      2026-05-29 after foilsX04 incident where 20/20 children died here;
      each propose retry draws a different `x` from skopt so a true geom
      bug doesn't infinite-loop. Bounded by MAX_PROPOSE_RETRIES (graph/config.py).
    - fail_init → terminal (real G4 init failure; geom is broken)
    """
    mode = state["mode"]
    name = state["config_name"]
    status, tail = pio.run_preflight(mode, name)
    errors = list(state.get("errors", []))
    if status not in ("pass",):
        # Keep last 8 lines for ambiguous/fail_init so the rc=3 retry loop
        # accumulates useful context across attempts instead of one opaque line.
        tail_msg = "\n".join(tail.splitlines()[-8:]) if tail else ""
        errors.append(f"preflight[{status}] {name}: {tail_msg}")
    return {"preflight": status, "errors": errors}


def make_stage_node(stage: str):
    """Build a graph node that runs one stage (submit→poll→list-outputs).

    Real-grid path only — the mock path is handled by `node_mock_grid`,
    which bypasses the entire stage chain (preflight routes to it directly).
    Per-stage idempotency lives in pipeline.py guards, so re-entry after a
    checkpoint kill is safe.
    """
    def _node(state: BOIterationState) -> dict:
        name = state["config_name"]
        errors = list(state.get("errors", []))
        stages = dict(state.get("stages", {}))
        try:
            stages[stage] = pio.run_stage(name, stage)
            # Overlap seam: early-submit data-independent downstream stages
            # (e.g. foilsflash elebeam_flash after mubeam) so their grid time
            # hides behind the intervening chain. Best-effort — on failure
            # the stage's own node submits sequentially (idempotent guards).
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
    """Run pipeline.py harvest; populate metrics from summary.json.

    Verb is mode-dispatched (ModeSpec.harvest_verb in modes.py): prodtarget
    runs `harvest-pot-only` (uproot, mu_per_POT); others run `harvest`
    (4-stage S/√B + calo).
    """
    name = state["config_name"]
    mode = state.get("mode")
    errors = list(state.get("errors", []))
    try:
        metrics = pio.run_harvest(name, mode=mode)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"harvest[{name}]: {exc}")
        _record_zero_row(name, "harvest_exception", str(exc))
        return {"metrics": None, "errors": errors}
    return {"metrics": metrics, "errors": errors}


def node_mock_grid(state: BOIterationState) -> dict:
    """Mock substitute for the real grid chain: synthesizes metrics from x."""
    return {"metrics": pio.mock_metrics(state["x_point"], state["mode"])}


def node_scan_logs(state: BOIterationState) -> dict:
    """End-of-workflow log scan. Gates the leaderboard append on broken runs.

    Walks every worker .log under the four stage outstage dirs and counts
    G4Exception / Stuck Track / Warning / FATAL / SEGV hits. Writes a TSV +
    JSON report under <grid_root>/<config_name>/scan_logs/. When the report
    trips a SCAN_BROKEN_CODES pattern (today: any GeomSolids1001 hit;
    see [[tessellated-solid-facet-orientation]]) the iteration's metrics
    are physics-broken — sets `scan_logs_broken=True` and writes
    `state/broken.txt`; node_evaluate then refuses to append the row.
    """
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
    """Append the (x, metrics) point to the leaderboard.

    Skips the append when scan_logs flagged the run as broken — the metrics
    in `state["metrics"]` are physics-invalid and including them would let
    the next BO refit chase a phantom Pareto frontier.
    """
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


# --- conditional edges ---


def route_after_preflight(state: BOIterationState) -> Literal["real", "mock", "propose", "__end__"]:
    """Branch after preflight.

    Both `fail_managed` (managed-overlap, BO-fixable) and `ambiguous`
    (rc=3 — subprocess died early without a parseable G4 init signature;
    typically OOM/transient under concurrent preflight load) re-propose
    up to MAX_PROPOSE_RETRIES. `fail_init` is terminal (real geom bug).
    Ambiguous-retriable added 2026-05-29 (foilsX04 incident).
    """
    status = state.get("preflight", "pending")
    attempts = state.get("attempts", {}).get("propose", 0)
    if status == "pass":
        return "mock" if state.get("mock", True) else "real"
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
    """Continue down the stage chain unless any stage is marked failed.

    Walks state["stages"] for any failure; conservative — one bad stage
    terminates the iteration so evaluate doesn't run with partial metrics.
    """
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
