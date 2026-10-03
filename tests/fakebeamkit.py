#!/usr/bin/env python3
"""fakebeamkit: a stand-in for beamkit's MCP server (get_server_info,
run_beamline, beamline_status, beamline_outputs) for
tests/test_beamkit_kit.py, driven through the real KitClient over stdio.

State lives in $FAKEBEAMKIT_STATE: calls.jsonl (every call, in order) and
<run_id>.json per run, holding the queue block and the output file paths a
test sets (or preset.json, copied into every new run: a finished run). The
reply shapes follow beamkit's: beamline_status wraps prodtools'
campaign_status ({campaigns: [{queue: ...}]}), beamline_outputs
lists {path, size}. A deck_ref of forty "f" is refused, as an unfetchable
sha would be; forty "e" creates the run and then fails, as beamkit does
when the first tick loses prodtools' ledger lock. A run's "fail_status": n
fails the next n beamline_status calls (a transient error).

No `from __future__ import annotations` here (see tests/toykit.py).
"""
import json
import os
from pathlib import Path
from typing import Optional

STATE = Path(os.environ["FAKEBEAMKIT_STATE"])
BAD_SHA = "f" * 40          # refused before anything exists
HALF_SHA = "e" * 40         # the run is created, then its first tick fails


def _log(tool, args):
    with open(STATE / "calls.jsonl", "a") as fh:
        fh.write(json.dumps({"tool": tool, "args": args}) + "\n")


def _run(run_id):
    path = STATE / f"{run_id}.json"
    if not path.exists():
        raise ValueError(f"no beamkit run {run_id!r}")
    return json.loads(path.read_text())


def make_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fakebeamkit")

    @server.tool()
    def get_server_info() -> dict:
        return {"name": "beamkit", "version": "0.5.1-fake"}

    @server.tool()
    def run_beamline(tag: str, run_as: str, deck_ref: Optional[str] = None,
                     params: Optional[dict] = None, events_per_job: int = 1000,
                     njobs: int = 1, main_input: str = "Mu2E.in",
                     outloc: str = "scratch", submit: bool = True,
                     deck_url: str = "https://github.com/Mu2e/G4BeamlineScripts"
                     ) -> dict:
        args = {"tag": tag, "run_as": run_as, "deck_ref": deck_ref,
                "params": params, "events_per_job": events_per_job,
                "njobs": njobs, "main_input": main_input, "outloc": outloc,
                "submit": submit, "deck_url": deck_url}
        _log("run_beamline", args)
        if deck_ref == BAD_SHA:
            raise ValueError(f"deck sha not found: {deck_ref} at {deck_url}")
        run_id = f"{tag}.{deck_ref[:7]}"
        run = {"args": args, "files": [],
               "queue": {"state": "known", "idle": njobs, "running": 0,
                         "held": 0}}
        preset = STATE / "preset.json"
        if preset.exists():     # a test's finished run: queue and files
            run.update(json.loads(preset.read_text()))
        (STATE / f"{run_id}.json").write_text(json.dumps(run))
        if deck_ref == HALF_SHA:
            raise ValueError("campaign 7 was created but the first tick "
                             "failed: another submissions run holds the lock")
        return {"run_id": run_id, "tag": tag, "state": "submitted"}

    @server.tool()
    def list_beamline_runs(state: Optional[str] = None) -> dict:
        _log("list_beamline_runs", {"state": state})
        runs = sorted((p for p in STATE.glob("*.json")
                       if p.name not in ("preset.json",)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        out = [{"run_id": p.stem, "tag": json.loads(p.read_text())
                ["args"]["tag"]} for p in runs]
        return {"records_dir": str(STATE), "count": len(out), "runs": out}

    @server.tool()
    def beamline_status(run_id: str) -> dict:
        _log("beamline_status", {"run_id": run_id})
        run = _run(run_id)
        if run.get("fail_status", 0) > 0:     # a transient failure
            run["fail_status"] -= 1
            (STATE / f"{run_id}.json").write_text(json.dumps(run))
            raise ValueError("transient: schedd query failed")
        return {"record": {"run_id": run_id}, "site": "fermilab",
                "status": {"db_path": "fake",
                           "campaigns": [{"id": 1, "state": "complete",
                                          "queue": run["queue"]}]}}

    @server.tool()
    def beamline_outputs(run_id: str) -> dict:
        _log("beamline_outputs", {"run_id": run_id})
        files = _run(run_id)["files"]
        return {"run_id": run_id, "dataset": f"nts.fake.{run_id}.root",
                "location": "scratch", "n_files": len(files),
                "total_size": 0,
                "files": [{"path": p, "size": 0} for p in files]}

    return server


if __name__ == "__main__":
    make_server().run("stdio")
