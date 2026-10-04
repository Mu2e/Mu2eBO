"""The live campaign dashboard (spec
docs/superpowers/specs/2026-10-04-dashboard-design.md): every campaign in
flight as a flow graph -- campaign, points, steps, result -- rebuilt from the
files every campaign leaves behind and written to snapshot.json, which
service/dashboard.html draws.

Monitoring only: it reads files (and this host's process table, through
CampaignService); it calls no kit, no grid tool and nothing that needs
Kerberos. Only the standard library and what service/campaigns.py imports:
never modes.

A step's state comes from its files in <grid data>/<point>/state/:
  done     <step>_results.json
  failed   <step>_status.json says failed or cancelled
  working  <step>_status.json says working (or completed, results not yet
           written), or <step>_cluster.txt alone (a run from before the
           status file)
  waiting  none of these
A working step of a running point stalls when its last poll is older than
max(3 * poll_s, STALL_FLOOR_S).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.campaigns import CampaignService, _flag, _last_line

STALL_FLOOR_S = 600.0
CHILD_RE = re.compile(r"(.+)R\d+_\d+")
POINT_STATES = {"scored": "scored", "broken": "broken",
                "running": "running", "ended without a row": "ended"}


def prefixes(svc: CampaignService, now: float, days: float) -> List[str]:
    """Campaigns to show: every live one, and any whose child logs or
    campaign.json changed within `days`."""
    cutoff = now - days * 86400
    newest: Dict[str, float] = {}
    if svc.logs_dir.is_dir():
        for log in svc.logs_dir.glob("*.log"):
            m = CHILD_RE.fullmatch(log.stem)
            if m:
                t = log.stat().st_mtime
                newest[m.group(1)] = max(newest.get(m.group(1), 0.0), t)
    keep = {p for p, t in newest.items() if t >= cutoff}
    for c in svc.campaign_status():
        record = svc.camp_dir(c["prefix"]) / "campaign.json"
        if c["alive"] or (record.exists()
                          and record.stat().st_mtime >= cutoff):
            keep.add(c["prefix"])
    return sorted(keep)


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _argv(svc: CampaignService, prefix: str) -> List[str]:
    """The campaign's closed_loop arguments: campaign.json's, else a live
    parent's argv."""
    record = svc._campaign_json(prefix)
    if record and record.get("args"):
        return list(record["args"])
    for _pid, argv in svc._processes():
        if ("graph.closed_loop" in argv
                and _flag(argv, "--name-prefix") == prefix):
            return argv
    return []


def _read_status(path: Path):
    """(record, error): the status file, or why it could not be read."""
    try:
        rec = json.loads(path.read_text())
        if not isinstance(rec, dict):
            raise ValueError("not a JSON object")
        return rec, None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, f"unreadable {path.name}: {exc}"


def _step(sd: Path, step: str, running: bool, now: float) -> Dict[str, Any]:
    cluster = sd / f"{step}_cluster.txt"
    rec, error = _read_status(sd / f"{step}_status.json")
    out = {"state": "waiting", "message": "", "progress": None,
           "age_s": None, "stall": False, "error": error}
    try:
        out["age_s"] = now - cluster.stat().st_mtime
    except OSError:
        pass
    if rec is not None:
        out["message"] = str(rec.get("message", ""))
        out["progress"] = rec.get("progress")
    if (sd / f"{step}_results.json").exists():
        out["state"] = "done"
    elif rec is not None and rec.get("state") in ("failed", "cancelled"):
        out["state"] = "failed"
    elif rec is not None or error is not None or cluster.exists():
        out["state"] = "working"
        if running and rec is not None:
            try:
                poll_age = now - float(rec["time"])
                limit = max(3 * float(rec.get("poll_s", 0)), STALL_FLOOR_S)
            except (KeyError, TypeError, ValueError) as exc:
                out["error"] = f"bad status record: {exc}"
            else:
                out["stall"] = poll_age > limit
    return out


def campaign_data(svc: CampaignService, prefix: str,
                  now: float) -> Dict[str, Any]:
    """One campaign as the dashboard shows it (keys: see the spec)."""
    status = svc.campaign_status(prefix)
    parent = status["parent"]
    argv = _argv(svc, prefix)
    study, error = None, status.get("board_error")
    if status["study"] is None:
        error = error or "no study found for this campaign"
    else:
        try:
            study = svc._load_study(status["study"])
        except (ValueError, OSError) as exc:
            error = error or str(exc)
    steps, best_label = [], None
    if study is not None:
        steps = [{"step": s.step, "kit": s.kit,
                  "files_from": list(s.files_from)} for s in study.steps]
        obj = study.objectives[0]
        best = status["best"]
        if best is not None and best["values"].get(obj.name) is not None:
            best_label = obj.fmt.format(best["values"][obj.name])
    points = []
    for child in status["children"]:
        name = child["name"]
        sd = svc.grid_data / name / "state"
        state = POINT_STATES[child["state"]]
        x = None
        if study is not None:
            try:
                point = json.loads((sd / "point.json").read_text())
                x = dict(zip(study.knob_names, point["x"]))
            except (OSError, ValueError, KeyError, TypeError):
                x = None
        points.append({
            "name": name, "state": state, "x": x,
            "last_line": child["last_line"],
            "steps": {s["step"]: _step(sd, s["step"], state == "running",
                                       now) for s in steps}})
    return {"prefix": prefix, "study": status["study"],
            "alive": parent["alive"], "exit_code": parent["exit_code"],
            "launched_by": parent["launched_by"], "host": status["host"],
            "stopping": status["stopping"],
            "q": _int(_flag(argv, "--q")),
            "max_evals": _int(_flag(argv, "--max-evals")),
            "rows": status["rows"], "best": status["best"],
            "best_label": best_label, "error": error, "steps": steps,
            "points": points}
