"""beamkit as a contract kit: the adapter the engine drives for every
`kit: "beamkit"` step, a G4beamline run on the Fermilab grid (spec
docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md).

beamkit (the MCP server in $AUTORESEARCH_BEAMKIT) runs a pinned
G4BeamlineScripts deck through prodtools. A step's params are deck params:
the knobs, given on the g4bl command line, which wins only over a deck's
`param -unset` lines. The adapter's own settings (BEAMKIT_OWN) say which
deck, how many jobs, and what to count.

- submit: run_beamline as run_as="self", outputs to scratch. A per-step
  record written before the call makes a rerun adopt the run.
- status: beamkit has no "finished" state, so the verdict comes from the
  campaign's queue (prodtools campaign_status) and the output count:
  working while a job is idle or running, then completed when at least
  ceil(quorum * njobs) files exist, else failed. make_recoveries is never
  called: it acts on the whole ledger.
- results: the figure of merit, counted here from the job ntuples with
  uproot: unique (file, EventID, TrackID) at NTuple/<plane> whose PDGid is
  listed, per proton on target (files x events_per_job). FOM_VERSION is in
  `version`, so a changed count changes measure_sha.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

if __package__ == "core.adapters":
    from core import kit_config, kit_registry, paths
    from core.contract import ContractError, parse_results, parse_status
    from core.kits import KitClient, KitError
    from core.scheduler import write_atomic
else:
    import kit_config
    import kit_registry
    import paths
    from contract import ContractError, parse_results, parse_status
    from kits import KitClient, KitError
    from scheduler import write_atomic

VERSION = "beamkit-adapter/1"
FOM_VERSION = 1                 # bump when the count would change
SERVER = "beamkit"              # kits.toml [servers.beamkit]
UNKNOWN_LIMIT_S = 6 * 3600      # an unreadable queue, as the prodtools adapter
RECORD = "{step}_beamkit.json"


def _error(call, message) -> KitError:
    return KitError(SERVER, call, message)


def tag_for(name: str) -> str:
    """beamkit's desc for a step (letters and digits only): the name's
    letters and digits plus 6 hex of its sha256, unique per name."""
    return (re.sub(r"[^A-Za-z0-9]", "", name)
            + hashlib.sha256(name.encode()).hexdigest()[:6])


def split_handle(name: str):
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"beamkit: {name!r} is not <config>.<step>")
    return config, step


def count_tracks(paths_: Sequence[str], plane: str, pdg: Sequence[int]) -> int:
    """Unique (file, EventID, TrackID) in NTuple/<plane> with a listed PDG
    id: a track looping in the solenoid field crosses a virtual detector
    more than once, and counts once."""
    import numpy as np
    import uproot
    wanted = np.array(sorted(set(int(p) for p in pdg)))
    key = f"NTuple/{plane}"
    total = 0
    for path in paths_:
        try:
            f = uproot.open(path)
        except Exception as exc:  # noqa: BLE001 - reported, never a guess
            raise _error("results", f"{path}: cannot open: {exc}") from exc
        with f:
            if key not in f:
                raise _error("results", f"{path}: no {key} tree")
            a = f[key].arrays(["PDGid", "EventID", "TrackID"], library="np")
        sel = np.isin(a["PDGid"].astype(np.int64), wanted)
        ids = set(zip(a["EventID"][sel].astype(np.int64).tolist(),
                      a["TrackID"][sel].astype(np.int64).tolist()))
        total += len(ids)
    return total


class BeamkitKit:
    """One campaign child's handle on beamkit; run_steps' threads share it."""

    name = "beamkit"
    accepts_lists = False
    poll_s = (30.0, 300.0)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 server=None, client_factory=None, grid_root=None,
                 trace_dir=None, clock: Callable[[], float] = time.time):
        executors = kit_registry.KITS[self.name].executors
        if executor not in executors:
            raise ValueError(f"{self.name}: executor must be one of "
                             f"{list(executors)}, got {executor!r}")
        if server is None:
            servers = kit_config.load_server_configs()
            if SERVER not in servers:
                raise _error("open", f"kits.toml has no [servers.{SERVER}]")
            server = servers[SERVER]
        self.campaign = campaign
        self._server = server
        trace = Path(trace_dir) if trace_dir else paths.GRAPH_DATA / campaign
        self._factory = client_factory or (
            lambda cfg: KitClient(cfg, campaign=campaign, trace_dir=trace))
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._clock = clock
        self._client = None
        self._version = None
        self._lock = threading.Lock()

    # --- the Kit interface -------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            self._client = self._factory(self._server)
        info = self._call("get_server_info", {}, "start")
        server_version = info.get("version") if isinstance(info, dict) else None
        if not server_version:
            raise _error("get_server_info", f"reply has no version: "
                         f"{str(info)[:200]}")
        self._version = (f"{VERSION}+beamkit-{server_version}"
                         f"+fom{FOM_VERSION}")

    @property
    def version(self) -> Optional[str]:
        return self._version

    @property
    def tools(self) -> frozenset:
        return frozenset({"submit", "status", "results", "cancel"})

    def describe(self):
        return None

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()

    def submit(self, name, params, files, inputs, workflow) -> str:
        config, step = split_handle(name)
        path = self._record_path(config, step)
        if path.exists():
            return name                       # adopt: never submit twice
        own = {k: params[k] for k in kit_registry.BEAMKIT_OWN if k in params}
        deck = {k: repr(float(v)) for k, v in params.items()
                if k not in kit_registry.BEAMKIT_OWN}
        deck.update({k: str(v) for k, v in own["deck_params"].items()})
        record = {"name": name, "tag": tag_for(name), "run_id": None,
                  "njobs": int(own.get("njobs", 1)),
                  "events_per_job": int(own.get("events_per_job", 1000)),
                  "quorum": float(own["quorum"]), "plane": own["plane"],
                  "pdg": list(own["pdg"]), "submitted": self._clock()}
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps(record, indent=1) + "\n")
        try:
            reply = self._call("run_beamline", {
                "tag": record["tag"], "run_as": "self",
                "deck_url": own["deck_url"], "deck_ref": own["deck_ref"],
                "main_input": own["main_input"], "params": deck,
                "njobs": record["njobs"],
                "events_per_job": record["events_per_job"],
                "outloc": "scratch", "submit": True}, workflow)
            run_id = reply.get("run_id") if isinstance(reply, dict) else None
            if not run_id:
                raise _error("run_beamline", f"reply has no run_id: "
                             f"{str(reply)[:200]}")
        except Exception:
            path.unlink(missing_ok=True)      # a fixed rerun submits again
            raise
        record["run_id"] = run_id
        write_atomic(path, json.dumps(record, indent=1) + "\n")
        return name

    def status(self, handle, workflow):
        rec = self._record(handle)
        reply = self._call("beamline_status", {"run_id": rec["run_id"]},
                           workflow)
        try:
            queue = reply["status"]["campaigns"][0]["queue"]
        except (KeyError, IndexError, TypeError):
            queue = {"state": "unknown",
                     "reason": f"beamline_status gave no queue block: "
                               f"{str(reply)[:200]}"}
        if queue.get("state") != "known":
            reason = queue.get("reason", "unknown")
            if self._clock() - rec["submitted"] > UNKNOWN_LIMIT_S:
                return self._status("failed", f"queue unreadable for 6 h: "
                                    f"{reason}")
            return self._status("working", f"queue unreadable: {reason}")
        live = int(queue.get("idle", 0)) + int(queue.get("running", 0))
        n_files = len(self._files(rec, workflow))
        progress = {"done": n_files, "total": rec["njobs"], "ok": n_files}
        if live:
            return self._status("working", f"{live} job(s) queued or "
                                f"running, {n_files} file(s)", progress)
        need = math.ceil(rec["quorum"] * rec["njobs"])
        if n_files >= need:
            return self._status("completed", f"{n_files} of {rec['njobs']} "
                                f"files", progress)
        return self._status("failed", f"{n_files} of {rec['njobs']} files "
                            f"(quorum {need}), {int(queue.get('held', 0))} "
                            f"held", progress)

    def results(self, handle, workflow):
        rec = self._record(handle)
        if self.status(handle, workflow).state != "completed":
            raise _error("results", f"{handle} is not completed")
        files = self._files(rec, workflow)
        pot = len(files) * rec["events_per_job"]
        if pot <= 0:
            raise _error("results", f"{handle}: zero protons on target")
        n = count_tracks(files, rec["plane"], rec["pdg"])
        return parse_results({
            "metrics": {"yield_per_pot": n / pot, "n_selected": float(n),
                        "pot": float(pot), "n_files": float(len(files))},
            "files": [{"name": Path(p).name, "uri": "file://" + p,
                       "kind": "nts"} for p in files],
            "metadata": {"run_id": rec["run_id"], "plane": rec["plane"],
                         "pdg": rec["pdg"], "adapter": self._version}},
            self.name)

    def cancel(self, handle, workflow):
        state = self.status(handle, workflow).state
        return state  # beamkit has no cancel: remove the jobs with jobsub_rm

    # --- helpers -----------------------------------------------------------
    def _call(self, tool, args, workflow):
        if self._client is None:
            self.start()
        return self._client.call(tool, args,
                                 timeout_s=self._server.timeouts[tool],
                                 workflow=workflow)

    def _files(self, rec, workflow) -> list:
        reply = self._call("beamline_outputs", {"run_id": rec["run_id"]},
                           workflow)
        files = reply.get("files") if isinstance(reply, dict) else None
        if not isinstance(files, list):
            raise _error("beamline_outputs", f"reply has no files: "
                         f"{str(reply)[:200]}")
        return [str(f["path"]) for f in files]

    def _record_path(self, config, step) -> Path:
        return self._grid_root / config / "state" / RECORD.format(step=step)

    def _record(self, handle) -> dict:
        config, step = split_handle(handle)
        path = self._record_path(config, step)
        if not path.exists():
            raise ContractError(self.name, "status", f"no step record "
                                f"{path} for {handle}")
        rec = json.loads(path.read_text())
        if rec.get("name") != handle or not rec.get("run_id"):
            raise ContractError(self.name, "status", f"{path} does not "
                                f"record a submitted {handle}")
        return rec

    def _status(self, state, message, progress=None):
        return parse_status({"state": state, "message": message,
                             "poll_ms": 0, "progress": progress}, self.name)
