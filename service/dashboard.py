"""The live campaign dashboard (spec
docs/superpowers/specs/2026-10-04-dashboard-design.md): every campaign in
flight as a flow graph -- campaign, points, steps, result -- rebuilt from the
campaign and point records every campaign leaves behind and written to
snapshot.json, which service/dashboard.html draws.

Monitoring only: it reads files through CampaignService and the records
(core/campaign_dir.py, core/point_dir.py, spec
docs/superpowers/specs/2026-10-05-point-campaign-records-design.md); it
calls no kit, no grid tool and nothing that needs Kerberos. Only the
standard library and what service/campaigns.py imports: never modes.

A step's state (done, failed, working, waiting) is PointDir.step_state's.
The one rule kept here is a display rule: a working step of a running point
stalls when its last poll is older than max(3 * poll_s, STALL_FLOOR_S).
"""
from __future__ import annotations

import argparse
import fcntl
import functools
import json
import os
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

from service.campaigns import CampaignService
from campaign_dir import RECORD, parse_child  # noqa: E402  (core/ via campaigns)

STALL_FLOOR_S = 600.0
POINT_STATES = {"scored": "scored", "broken": "broken",
                "running": "running", "starting": "running",
                "ended without a row": "ended"}


def prefixes(svc: CampaignService, now: float, days: float) -> List[str]:
    """Campaigns to show: every live one, and any whose child logs or
    campaign.json changed within `days`."""
    cutoff = now - days * 86400
    newest: Dict[str, float] = {}
    if svc.logs_dir.is_dir():
        for log in svc.logs_dir.glob("*.log"):
            parsed = parse_child(log.stem)
            if parsed:
                prefix = parsed[0]
                newest[prefix] = max(newest.get(prefix, 0.0),
                                     log.stat().st_mtime)
    keep = {p for p, t in newest.items() if t >= cutoff}
    for c in svc.campaign_status():
        record = svc.camp(c["prefix"]).path / RECORD
        if c["alive"] or (record.exists()
                          and record.stat().st_mtime >= cutoff):
            keep.add(c["prefix"])
    return sorted(keep)


def _step(view: Dict[str, Any], running: bool, now: float) -> Dict[str, Any]:
    """PointDir.step_state as the page shows it: the handle's age, and the
    stall rule."""
    out = {"state": view["state"], "message": view["message"],
           "progress": view["progress"], "error": view["error"],
           "age_s": (None if view["handle_mtime"] is None
                     else now - view["handle_mtime"]),
           "stall": False}
    if (running and view["state"] == "working"
            and view["poll_time"] is not None):
        limit = max(3 * view["poll_s"], STALL_FLOOR_S)
        out["stall"] = now - view["poll_time"] > limit
    return out


def campaign_data(svc: CampaignService, prefix: str,
                  now: float) -> Dict[str, Any]:
    """One campaign as the dashboard shows it (keys: see the spec)."""
    status = svc.campaign_status(prefix)
    parent = status["parent"]
    errors = [e for e in (status.get("board_error"), status.get("error"))
              if e]
    try:
        record = svc.camp(prefix).record() or {}
    except (OSError, ValueError):
        record = {}             # campaign_status already reported it
    study = None
    if status["study"] is None:
        errors.append("no study found for this campaign")
    else:
        try:
            study = svc.load_study(status["study"])
        except (ValueError, OSError) as exc:
            if str(exc) not in errors:
                errors.append(str(exc))
    steps, best_label, direction, obj = [], None, None, None
    if study is not None:
        # upstream: the steps each one waits for, by files_from or
        # params_from, so a number-only feed is drawn as an edge too.
        steps = [{"step": s.step, "kit": s.kit,
                  "upstream": list(s.upstream)} for s in study.steps]
        obj = study.objectives[0]
        direction = obj.direction
        best = status["best"]
        if best is not None and best["values"].get(obj.name) is not None:
            best_label = obj.fmt.format(best["values"][obj.name])
    points = []
    for child in status["children"]:
        name = child["name"]
        state = POINT_STATES[child["state"]]
        value = (child["values"] or {}).get(obj.name) if obj else None
        pd = svc.point(name)
        step_recs = {s["step"]: _step(pd.step_state(s["step"]),
                                      state == "running", now)
                     for s in steps}
        points.append({
            "name": name, "state": state, "x": child["x"],
            "last_line": child["last_line"], "value": value,
            "value_label": (None if value is None
                            else obj.fmt.format(value)),
            "steps": step_recs})
    return {"prefix": prefix, "study": status["study"],
            "alive": parent["alive"], "exit_code": parent["exit_code"],
            "launched_by": parent["launched_by"], "host": status["host"],
            "stopping": status["stopping"],
            "q": record.get("q"), "max_evals": record.get("max_evals"),
            "rows": status["rows"], "best": status["best"],
            "best_label": best_label, "error": "; ".join(errors) or None,
            "direction": direction, "steps": steps, "points": points}


# -- the graph -------------------------------------------------------------

ORDER = {"running": 0, "scored": 1, "broken": 2, "ended": 3}


def _depths(steps: List[Dict[str, Any]]) -> Dict[str, int]:
    """Each step's longest path from a root step (the study loader has
    already refused cycles)."""
    ups = {s["step"]: s["upstream"] for s in steps}
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
    consumed = {u for s in steps for u in s["upstream"]}
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
            ups = s["upstream"] or [None]
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
