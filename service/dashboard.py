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

import argparse
import fcntl
import functools
import json
import os
import re
import shutil
import signal
import socket
import sys
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.campaigns import CampaignService, _flag

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
    steps, best_label, direction, values = [], None, None, {}
    if study is not None:
        steps = [{"step": s.step, "kit": s.kit,
                  "files_from": list(s.files_from)} for s in study.steps]
        obj = study.objectives[0]
        direction = obj.direction
        best = status["best"]
        if best is not None and best["values"].get(obj.name) is not None:
            best_label = obj.fmt.format(best["values"][obj.name])
        if status["rows"]:
            rows = svc.leaderboard(study.name, prefix,
                                   top=status["rows"])["rows"]
            values = {r["config"]: r["values"].get(obj.name) for r in rows}
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
        value = values.get(name)
        points.append({
            "name": name, "state": state, "x": x,
            "last_line": child["last_line"], "value": value,
            "value_label": (None if value is None
                            else study.objectives[0].fmt.format(value)),
            "steps": {s["step"]: _step(sd, s["step"], state == "running",
                                       now) for s in steps}})
    return {"prefix": prefix, "study": status["study"],
            "alive": parent["alive"], "exit_code": parent["exit_code"],
            "launched_by": parent["launched_by"], "host": status["host"],
            "stopping": status["stopping"],
            "q": _int(_flag(argv, "--q")),
            "max_evals": _int(_flag(argv, "--max-evals")),
            "rows": status["rows"], "best": status["best"],
            "best_label": best_label, "error": error, "direction": direction,
            "steps": steps, "points": points}


# -- the graph -------------------------------------------------------------

ORDER = {"running": 0, "scored": 1, "broken": 2, "ended": 3}


def _depths(steps: List[Dict[str, Any]]) -> Dict[str, int]:
    """Each step's longest path from a root step (the study loader has
    already refused cycles)."""
    ups = {s["step"]: s["files_from"] for s in steps}
    depth: Dict[str, int] = {}

    def of(name: str) -> int:
        if name not in depth:
            depth[name] = 1 + max((of(u) for u in ups[name]), default=-1)
        return depth[name]
    for s in steps:
        of(s["step"])
    return depth


def _band_key(point: Dict[str, Any], direction: Optional[str]):
    rank = ORDER[point["state"]]
    if point["state"] == "scored" and point["value"] is not None:
        v = point["value"]
        return (rank, 0, -v if direction == "max" else v, point["name"])
    return (rank, 1, 0.0, point["name"])


def layout(camp: Dict[str, Any]) -> Dict[str, Any]:
    """The campaign's flow graph, laid out: column (layer) 0 campaign, 1
    point, 2.. steps by depth, last the result; each point a band whose
    height is its widest layer. The page only draws it."""
    steps = camp["steps"]
    depth = _depths(steps)
    width = 1 + max(depth.values(), default=-1)
    result_layer = 2 + width
    subrow, seen = {}, {}
    for s in steps:
        d = depth[s["step"]]
        subrow[s["step"]] = seen.get(d, 0)
        seen[d] = seen.get(d, 0) + 1
    height = max(seen.values(), default=1)
    consumed = {u for s in steps for u in s["files_from"]}
    best = (camp.get("best") or {}).get("config")
    bands, edges = [], []
    for p in sorted(camp["points"],
                    key=lambda p: _band_key(p, camp.get("direction"))):
        name = p["name"]
        x = "\n".join(f"{k}={v}" for k, v in (p["x"] or {}).items())
        nodes = [{"id": name, "kind": "point", "layer": 1, "subrow": 0,
                  "label": name, "state": p["state"],
                  "detail": "\n".join(t for t in (x, p["last_line"]) if t)}]
        edges.append(["campaign", name])
        for s in steps:
            rec = p["steps"].get(s["step"]) or {}
            sid = f"{name}/{s['step']}"
            detail = f"{s['kit']}: {rec.get('message', '')}"
            if rec.get("error"):
                detail += f"\n{rec['error']}"
            nodes.append({"id": sid, "kind": "step",
                          "layer": 2 + depth[s["step"]],
                          "subrow": subrow[s["step"]], "label": s["step"],
                          "state": ("stall" if rec.get("stall")
                                    else rec.get("state", "waiting")),
                          "detail": detail, "progress": rec.get("progress"),
                          "age_s": rec.get("age_s")})
            ups = s["files_from"] or [None]
            edges.extend([f"{name}/{u}" if u else name, sid] for u in ups)
            if s["step"] not in consumed:
                edges.append([sid, f"{name}/result"])
        if not steps:
            edges.append([name, f"{name}/result"])
        label = (p["value_label"] if p["state"] == "scored"
                 and p["value_label"] is not None else p["state"])
        nodes.append({"id": f"{name}/result", "kind": "result",
                      "layer": result_layer, "subrow": 0, "label": label,
                      "state": p["state"], "detail": label,
                      "best": name == best})
        bands.append({"point": name, "height": height, "nodes": nodes,
                      "fold": "scored" if p["state"] == "scored" else None})
    return {"columns": result_layer + 1, "bands": bands, "edges": edges}


def build_snapshot(svc: CampaignService, now: float, days: float,
                   every_s: float) -> Dict[str, Any]:
    """Everything the page draws. A campaign that cannot be read becomes a
    line in `errors`; the others are still built."""
    errors: List[str] = []
    campaigns = []
    try:
        names = prefixes(svc, now, days)
    except OSError as exc:
        errors.append(f"listing campaigns: {exc}")
        names = []
    for prefix in names:
        try:
            camp = campaign_data(svc, prefix, now)
            camp["collapsed"] = not camp["alive"]
            camp["graph"] = layout(camp)
        except Exception as exc:    # one campaign never hides the others
            errors.append(f"{prefix}: {type(exc).__name__}: {exc}")
            continue
        campaigns.append(camp)
    campaigns.sort(key=lambda c: (not c["alive"], c["prefix"]))
    return {"time": now, "host": socket.gethostname(), "every_s": every_s,
            "errors": errors, "campaigns": campaigns}


# -- the process -----------------------------------------------------------

PAGE = Path(__file__).with_name("dashboard.html")


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def write_snapshot(svc: CampaignService, out: Path, days: float,
                   every_s: float) -> None:
    snap = build_snapshot(svc, time.time(), days, every_s)
    tmp = out / "snapshot.json.tmp"
    tmp.write_text(json.dumps(snap))
    os.replace(tmp, out / "snapshot.json")


def _lock(out: Path) -> Optional[int]:
    """Hold <out>/lock for this process's life; None if another holds it."""
    fd = os.open(out / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()} {socket.gethostname()}\n".encode())
    return fd


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m service.dashboard",
        description="Rebuild the campaign dashboard's snapshot.json every "
                    "--every seconds and serve it on 127.0.0.1.")
    ap.add_argument("--every", type=float, default=120.0)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-serve", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    svc = CampaignService()
    out = args.out or svc.data_root / "autoresearch_dashboard"
    out.mkdir(parents=True, exist_ok=True)
    fd = _lock(out)
    if fd is None:
        owner = (out / "lock").read_text().strip() or "unknown pid"
        print(f"[dashboard] another dashboard (pid host: {owner}) owns "
              f"{out}", file=sys.stderr)
        return 1
    shutil.copyfile(PAGE, out / "index.html")
    if not (args.once or args.no_serve):
        handler = functools.partial(_Quiet, directory=str(out))
        try:
            server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        except OSError as exc:
            print(f"[dashboard] cannot serve on 127.0.0.1 port {args.port}: "
                  f"{exc}", file=sys.stderr)
            return 1
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"[dashboard] serving {out} at http://127.0.0.1:{args.port}/",
              flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            try:
                write_snapshot(svc, out, args.days, args.every)
            except Exception:       # keep the last snapshot; its age shows
                traceback.print_exc()
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.every)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
