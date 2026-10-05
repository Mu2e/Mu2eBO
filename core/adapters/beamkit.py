"""beamkit as a contract kit: the adapter the engine drives for every
`kit: "beamkit"` step, a G4beamline run on the Fermilab grid (spec
docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md).

beamkit (the MCP server in $AUTORESEARCH_BEAMKIT) runs a pinned
G4BeamlineScripts deck through prodtools. A step's params are deck params:
the knobs, given on the g4bl command line, which wins only over a deck's
`param -unset` lines. The adapter's own settings (BEAMKIT_OWN) say which
deck, how many jobs, and what to count.

- submit: run_beamline as run_as="self", outputs to scratch, under the
  host-wide submit lock the prodtools adapter uses (each run_beamline ends
  in a prodtools submissions tick, which refuses to run beside another).
  A per-step record written before the call makes a rerun adopt the run;
  a record without a run id (a crash mid-submit), or a failed call whose
  run was created anyway, is matched to beamkit's run by its unique tag
  (list_beamline_runs), so a rerun never submits a second run.
- status: beamkit has no "finished" state, so the verdict comes from the
  campaign's queue (prodtools campaign_status) and the output count:
  working while a job is idle or running, then completed when the files
  meet the quorum (prodtools.meets_quorum: files/njobs >= quorum), else
  failed. The verdict and the files it judged are kept in the record;
  results counts exactly those. A queue unreadable for 6 h in a row
  (counted from the first unreadable poll) fails. Read calls are retried
  as NativeKit's are. make_recoveries is never called; note that every
  run_beamline's own tick still runs prodtools' recovery pass over the
  whole personal ledger.
- results: the figure of merit, counted here from the job ntuples with
  uproot: unique (file, EventID, TrackID) in the tree at `plane` -- its
  path in the file: g4bl writes a virtualdetector under
  VirtualDetector/<name> and a zntuple under NTuple/<name> -- whose PDGid
  is listed, per proton on target (files x events_per_job). FOM_VERSION is in
  `version`, so a changed count changes measure_sha.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

if __package__ == "core.adapters":
    from core import kit_config, kit_registry, paths
    from core.adapters.prodtools import SUBMIT_LOCK, meets_quorum
    from core.contract import (ContractError, call_with_retries,
                               parse_results, parse_status)
    from core.kits import KitClient, KitError
    from core.scheduler import write_atomic
else:
    import kit_config
    import kit_registry
    import paths
    from adapters.prodtools import SUBMIT_LOCK, meets_quorum
    from contract import (ContractError, call_with_retries, parse_results,
                          parse_status)
    from kits import KitClient, KitError
    from scheduler import write_atomic

VERSION = "beamkit-adapter/1"
FOM_VERSION = 1                 # bump when the count would change
SERVER = "beamkit"              # kits.toml [servers.beamkit]
UNKNOWN_LIMIT_S = 6 * 3600      # an unreadable queue, as the prodtools adapter
HELD_LIMIT_S = 2 * 3600         # only held jobs left: in flight this long
POLL_MS = 120_000               # condor and SAM per poll: every 2 min
RECORD = "{step}_beamkit.json"


@contextlib.contextmanager
def _flock(path: Path):
    with open(path, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


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
    """Unique (file, EventID, TrackID) in the tree at path `plane` (e.g.
    VirtualDetector/Coll_01_DetIn) with a listed PDG id: a track looping in
    the solenoid field crosses a virtual detector more than once, and
    counts once."""
    import numpy as np
    import uproot
    wanted = np.array(sorted(set(int(p) for p in pdg)))
    key = plane
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


def _not_submitted(reply: dict) -> str:
    """Why beamkit's run is not running: its state and its last tick."""
    ticks = ((reply.get("fermilab") or {}).get("ticks") or [])
    summary = str(ticks[-1].get("summary", "")).strip() if ticks else ""
    tail = "\n".join(summary.splitlines()[-6:])
    return (f"run {reply.get('run_id')} is {reply.get('state')!r}, not "
            f"'submitted': its first tick submitted no jobs"
            + (f"; the tick said:\n{tail}" if tail else "")
            + "\nFix the cause, then make_recoveries on the run (or a "
              "prodtools tick) submits its jobs; rerun this point to adopt it")


class BeamkitKit:
    """One campaign child's handle on beamkit; run_steps' threads share it."""

    name = "beamkit"
    accepts_lists = False
    poll_s = (30.0, 300.0)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 server=None, client_factory=None, grid_root=None,
                 trace_dir=None, clock: Callable[[], float] = time.time,
                 submit_lock=None, pause=time.sleep):
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
        self._submit_lock = Path(submit_lock or SUBMIT_LOCK)
        self._pause = pause
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
        # No cancel: beamkit has none, and a kit that offers one has the
        # scheduler log "cancel requested" while its jobs keep running.
        return frozenset({"submit", "status", "results"})

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
        tag = tag_for(name)
        if path.exists():
            rec = json.loads(path.read_text())
            if rec.get("run_id"):
                return name                   # adopt: never submit twice
            run_id = self._find_run(tag, workflow)
            if run_id:                        # died before saving the id
                rec["run_id"] = run_id
                write_atomic(path, json.dumps(rec, indent=1) + "\n")
                return name
            path.unlink()                     # no run was made: submit
        own = {k: params[k] for k in kit_registry.BEAMKIT_OWN if k in params}
        deck = {k: repr(float(v)) for k, v in params.items()
                if k not in kit_registry.BEAMKIT_OWN}
        deck.update({k: str(v) for k, v in own["deck_params"].items()})
        record = {"name": name, "tag": tag, "run_id": None,
                  "njobs": int(own["njobs"]),
                  "events_per_job": int(own["events_per_job"]),
                  "quorum": float(own["quorum"]), "plane": own["plane"],
                  "pdg": list(own["pdg"]), "submitted": self._clock(),
                  "unknown_since": None, "held_since": None,
                  "verdict": None}
        path.parent.mkdir(parents=True, exist_ok=True)
        run_id = self._find_run(tag, workflow)    # a run whose record was lost
        if run_id is None:
            write_atomic(path, json.dumps(record, indent=1) + "\n")
            try:
                with _flock(self._submit_lock):
                    reply = self._call("run_beamline", {
                        "tag": tag, "run_as": "self",
                        "deck_url": own["deck_url"],
                        "deck_ref": own["deck_ref"],
                        "main_input": own["main_input"], "params": deck,
                        "njobs": record["njobs"],
                        "events_per_job": record["events_per_job"],
                        "outloc": "scratch", "submit": True}, workflow)
                run_id = (reply.get("run_id") if isinstance(reply, dict)
                          else None)
                if not run_id:
                    raise _error("run_beamline", f"reply has no run_id: "
                                 f"{str(reply)[:200]}")
                if reply.get("state") != "submitted":
                    # beamkit returns the record, not an error, when its
                    # first tick submits nothing (rc 2: needs_attention).
                    raise _error("run_beamline", _not_submitted(reply))
            except Exception as exc:
                # A run may exist although the call failed (a timeout, or
                # "created but the first tick failed"): keep it, so a rerun
                # adopts it instead of submitting a second one.
                try:
                    found = self._find_run(tag, workflow)
                except Exception:   # noqa: BLE001 - cannot tell: keep it
                    raise exc
                if found is None:
                    path.unlink(missing_ok=True)   # nothing was made
                    raise
                record["run_id"] = found
                write_atomic(path, json.dumps(record, indent=1) + "\n")
                raise _error("run_beamline", f"run {found} was created but "
                             f"the submit reported: {exc}; its record is "
                             f"kept, so a rerun adopts it instead of "
                             f"submitting a second run") from exc
        record["run_id"] = run_id
        write_atomic(path, json.dumps(record, indent=1) + "\n")
        return name

    def status(self, handle, workflow):
        rec, path = self._record(handle, workflow)
        if rec.get("verdict"):                # decided once, kept
            v = rec["verdict"]
            return self._status(v["state"], v["message"])
        reply = self._read("beamline_status", {"run_id": rec["run_id"]},
                           workflow)
        try:
            queue = reply["status"]["campaigns"][0]["queue"]
        except (KeyError, IndexError, TypeError):
            queue = {"state": "unknown",
                     "reason": f"beamline_status gave no queue block: "
                               f"{str(reply)[:200]}"}
        now = self._clock()
        if queue.get("state") != "known":
            reason = queue.get("reason", "unknown")
            if rec.get("unknown_since") is None:
                rec["unknown_since"] = now
                write_atomic(path, json.dumps(rec, indent=1) + "\n")
            if now - rec["unknown_since"] > UNKNOWN_LIMIT_S:
                return self._decide(rec, path, "failed", f"queue unreadable "
                                    f"for 6 h: {reason}")
            return self._status("working", f"queue unreadable: {reason}",
                                poll_ms=POLL_MS)
        if rec.get("unknown_since") is not None:
            rec["unknown_since"] = None
            write_atomic(path, json.dumps(rec, indent=1) + "\n")
        live = int(queue.get("idle", 0)) + int(queue.get("running", 0))
        held = int(queue.get("held", 0))
        files = self._files(rec, workflow)
        n_files = len(files)
        progress = {"done": n_files, "total": rec["njobs"], "ok": n_files}
        if live:
            if rec.get("held_since") is not None:
                rec["held_since"] = None
                write_atomic(path, json.dumps(rec, indent=1) + "\n")
            return self._status("working", f"{live} job(s) queued or "
                                f"running, {held} held, {n_files} file(s)",
                                progress, poll_ms=POLL_MS)
        quorum = f"quorum {rec['quorum']:g}"
        if meets_quorum(n_files, rec["njobs"], rec["quorum"]):
            return self._decide(rec, path, "completed", f"{n_files} of "
                                f"{rec['njobs']} files", files)
        if held:
            # jobsub can hold a just-submitted cluster for a moment (campaign
            # ptg5k01, 2026-10-03: 20 held, then 20 running a minute later):
            # held is in flight until it has been all that is left for
            # HELD_LIMIT_S.
            if rec.get("held_since") is None:
                rec["held_since"] = now
                write_atomic(path, json.dumps(rec, indent=1) + "\n")
            reasons = str(queue.get("hold_reasons", ""))[:300]
            if now - rec["held_since"] > HELD_LIMIT_S:
                return self._decide(rec, path, "failed", f"{held} job(s) "
                                    f"held for {HELD_LIMIT_S // 3600} h, "
                                    f"{n_files} of {rec['njobs']} files "
                                    f"({quorum}): {reasons}")
            return self._status("working", f"{held} held, {n_files} "
                                f"file(s): {reasons}", progress,
                                poll_ms=POLL_MS)
        return self._decide(rec, path, "failed", f"{n_files} of "
                            f"{rec['njobs']} files ({quorum}), 0 held")

    def results(self, handle, workflow):
        rec, _ = self._record(handle, workflow)
        verdict = rec.get("verdict") or {}
        if verdict.get("state") != "completed":
            raise _error("results", f"{handle} is not completed")
        files = list(verdict["files"])       # exactly what status judged
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

    # --- helpers -----------------------------------------------------------
    def _call(self, tool, args, workflow):
        if self._client is None:
            self.start()
        return self._client.call(tool, args,
                                 timeout_s=self._server.timeouts[tool],
                                 workflow=workflow)

    def _read(self, tool, args, workflow):
        """A read-only call, retried as NativeKit's status calls are: a
        failed step is never retried, so one schedd or SAM blip must not
        end a run hours into the grid."""
        return call_with_retries(lambda: self._call(tool, args, workflow),
                                 call="status", retry_tool_errors=True,
                                 pause=self._pause)

    def _find_run(self, tag, workflow) -> Optional[str]:
        """beamkit's newest run with this tag, or None."""
        reply = self._read("list_beamline_runs", {}, workflow)
        runs = reply.get("runs") if isinstance(reply, dict) else None
        if not isinstance(runs, list):
            raise _error("list_beamline_runs", f"reply has no runs: "
                         f"{str(reply)[:200]}")
        for run in runs:
            if isinstance(run, dict) and run.get("tag") == tag:
                return run.get("run_id")
        return None

    def _decide(self, rec, path, state, message, files=None):
        rec["verdict"] = {"state": state, "message": message,
                          "files": files or []}
        write_atomic(path, json.dumps(rec, indent=1) + "\n")
        return self._status(state, message)

    def _files(self, rec, workflow) -> list:
        reply = self._read("beamline_outputs", {"run_id": rec["run_id"]},
                           workflow)
        files = reply.get("files") if isinstance(reply, dict) else None
        if not isinstance(files, list):
            raise _error("beamline_outputs", f"reply has no files: "
                         f"{str(reply)[:200]}")
        return [str(f["path"]) for f in files]

    def _record_path(self, config, step) -> Path:
        return self._grid_root / config / "state" / RECORD.format(step=step)

    def _record(self, handle, workflow):
        config, step = split_handle(handle)
        path = self._record_path(config, step)
        if not path.exists():
            raise ContractError(self.name, "status", f"no step record "
                                f"{path} for {handle}")
        rec = json.loads(path.read_text())
        if rec.get("name") != handle:
            raise ContractError(self.name, "status", f"{path} records "
                                f"{rec.get('name')!r}, not {handle!r}")
        if not rec.get("run_id"):
            run_id = self._find_run(rec["tag"], workflow)
            if not run_id:
                raise ContractError(self.name, "status", f"{path} records "
                                    f"no run for {handle}, and beamkit has "
                                    f"none tagged {rec['tag']}")
            rec["run_id"] = run_id
            write_atomic(path, json.dumps(rec, indent=1) + "\n")
        return rec, path

    def _status(self, state, message, progress=None, poll_ms=0):
        return parse_status({"state": state, "message": message,
                             "poll_ms": poll_ms, "progress": progress},
                            self.name)
