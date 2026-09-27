"""prodtools as a contract kit: the adapter the engine drives for every
`kit: "prodtools"` step (Phase C1 spec,
docs/superpowers/specs/2026-09-25-prodtools-kit-design.md, "The adapter").

submit renders the step's stage template into a json2jobdef entry, builds
the per-config code tarball, hard-links the upstream outputs into a dir:
area, and hands the entry to prodtools' submit_once (grid) or run_local
(local) over MCP. status and results read prodtools' run_status and apply
autoresearch's acceptance: quorum, stage-out, the fatal-log scan.

A step's record, <GRID_DATA_ROOT>/<config>/prodtools/<step>/record.json,
is written before the submit and updated after, so a killed child re-run
on the same point adopts the run instead of submitting it twice; the
completion verdict is kept there too.
"""
from __future__ import annotations

import datetime
import fcntl
import fnmatch
import hashlib
import json
import os
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

if __package__ == "core.adapters":
    from core import kit_config, kit_registry, paths
    from core.adapters import prodtools_entry as pe
    from core.contract import (Describe, call_with_retries, parse_cancel,
                               parse_results, parse_status)
    from core.kits import KitClient, KitError, KitToolError
else:
    import kit_config
    import kit_registry
    import paths
    from adapters import prodtools_entry as pe
    from contract import (Describe, call_with_retries, parse_cancel,
                          parse_results, parse_status)
    from kits import KitClient, KitError, KitToolError

VERSION = "prodtools-adapter/1"      # bump when a step would measure anew
PARAMS = ("entry", "code_tarball", "dsconf", "fatal_log_codes", "njobs",
          "events_per_job", "memory_mb", "quorum")
METRICS = ("njobs", "njobs_ok")
DEFAULT_PARALLEL = 4
UNKNOWN_LIMIT_S = 6 * 3600
STAGEOUT_LIMIT_S = 30 * 60
WORKING = ("building", "submitting", "starting", "submitted", "running")
# Every tool the adapter calls, per server role: each needs a timeout.
TOOLS = {"write": ("submit_once", "run_local", "cancel_run"),
         "read": ("run_status",)}
# The file core/pipeline.py's _submit_lock uses, so both runners serialize
# their grid submits on a host (wiki/incidents/concurrent-token-contention.md).
SUBMIT_LOCK = Path(f"/tmp/mu2e_submit.{pe.USER}.lock")
PNFS_STAGE_ROOT = Path(f"/pnfs/mu2e/scratch/users/{pe.USER}/autoresearch_grid")
_POLL = {"grid": ((30.0, 600.0), 60_000), "local": ((5.0, 60.0), 10_000)}


def split_handle(name: str):
    """'<config>.<step>' -> (config, step). The config becomes part of
    prodtools' dot-separated run name, so it must pass
    kit_registry.config_name_problem."""
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"prodtools: {name!r} is not <config>.<step>")
    why = kit_registry.config_name_problem(config)
    if why:
        raise ValueError(f"prodtools: {why}")
    return config, step


def _digest(blob) -> str:
    return hashlib.sha256(json.dumps(blob, sort_keys=True,
                                     separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None


def _write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


def _utc_of(value, what, run_name) -> datetime.datetime:
    """An ISO 8601 time with a UTC offset, as prodtools stamps its
    receipts. Anything else is an error: whose run it is is never
    guessed."""
    try:
        t = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        t = None
    if t is None or t.tzinfo is None:
        raise KitError("prodtools", "submit",
                       f"{run_name}: {what} is {value!r}, not an ISO 8601 "
                       f"time with a UTC offset, so whether prodtools' run "
                       f"is this step's cannot be told")
    return t


def _check_timeouts(config, tools) -> None:
    """A server config must time every tool the adapter calls on it; a
    missing one is refused at construction, not as a KeyError mid-run.
    Looked up the way _call reads it, `timeouts[tool]`."""
    missing = []
    for tool in tools:
        try:
            config.timeouts[tool]
        except KeyError:
            missing.append(tool)
    if missing:
        raise ValueError(f"prodtools: server {config.name!r} has no timeout "
                         f"for {missing}, which the adapter calls on it; add "
                         f"them to its kits.toml `timeouts`")


def _jobs_without_log(outputs) -> list:
    """(index, job dir) of each successful job whose dir holds no .log
    yet; the dir is None for a job that listed no output."""
    out = []
    for index, job_paths in sorted(outputs.items()):
        job_dir = Path(job_paths[0]).parent if job_paths else None
        if job_dir is None or not any(job_dir.glob("*.log")):
            out.append((index, job_dir))
    return out


@contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _progress(reply):
    jobs = reply.get("jobs")
    if not jobs:
        return None
    ok = int(jobs.get("ok", 0))
    failed = int((jobs.get("truncated") or {}).get(
        "failed", len(jobs.get("failed") or [])))
    return {"done": ok + failed, "total": int(jobs.get("expected", 0)),
            "ok": ok}


class ProdtoolsKit:
    """One campaign child's handle on prodtools. run_steps' threads share
    it, one step each; every write is per step or content-addressed."""

    name = "prodtools"
    accepts_lists = False
    EXECUTORS = ("grid", "local")
    REQUIRES_KERBEROS = True
    LAUNCH_STAGGER_S = 90.0

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 clients=None, clock=time.time, pause=time.sleep,
                 grid_root=None, pnfs_root=None, templates_root=None,
                 submit_lock=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"prodtools: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign, self.executor = campaign, executor
        self.parallel = DEFAULT_PARALLEL if parallel is None else parallel
        self.poll_s, self._poll_ms = _POLL[executor]
        if clients is None:
            servers = kit_config.load_server_configs()
            trace = paths.GRAPH_DATA / campaign
            clients = {role: KitClient(servers[f"prodtools_{role}"],
                                       campaign=campaign, trace_dir=trace)
                       for role in ("write", "read")}
        self._write, self._read = clients["write"], clients["read"]
        for role, client in (("write", self._write), ("read", self._read)):
            _check_timeouts(client.config, TOOLS[role])
        self._clock, self._pause = clock, pause
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._pnfs_root = Path(pnfs_root or PNFS_STAGE_ROOT)
        self._templates = Path(templates_root or pe.TEMPLATES_ROOT)
        self._submit_lock = Path(submit_lock or SUBMIT_LOCK)

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return VERSION

    @property
    def tools(self) -> frozenset:
        self._ensure_started()
        out = {"submit", "status", "results", "describe"}
        if "cancel_run" in self._write.tools:
            out.add("cancel")
        return frozenset(out)

    def describe(self):
        return Describe(PARAMS, METRICS, False)

    def close(self) -> None:
        for client in (self._write, self._read):
            client.close()

    def submit(self, name, params, files, inputs, workflow) -> str:
        config, step = split_handle(name)
        unknown = sorted(set(params) - set(PARAMS))
        if unknown:
            raise ValueError(f"prodtools: unknown param(s) {unknown}; it "
                             f"accepts {list(PARAMS)}")
        for key in ("entry", "code_tarball", "dsconf", "fatal_log_codes",
                    "quorum"):
            if key not in params:
                raise ValueError(f"prodtools: param {key!r} is missing")
        sdir = self._step_dir(config, step)
        digest = _digest({"params": params, "files": list(files),
                          "inputs": list(inputs), "executor": self.executor})
        rec = _read_json(sdir / "record.json")
        if rec is not None:
            if rec["digest"] != digest:
                raise ValueError(
                    f"prodtools: {name!r} was already submitted with other "
                    f"params, files, inputs or executor "
                    f"({sdir / 'record.json'}: digest {rec['digest'][:12]}, "
                    f"now {digest[:12]}); the same name with different "
                    f"params is an error")
            if rec["state"] == "submitted":
                return name
            if self._adopt(rec, workflow):
                self._save(sdir, rec, state="submitted")
                return name
        rec = self._prepare(name, config, step, params, files, inputs, sdir,
                            digest)
        # "submitting", before prodtools acts; _adopt takes only a run
        # prodtools created at or after this moment.
        self._save(sdir, rec, submitting_utc=self._utc_now())
        try:
            self._launch(rec, workflow)
        except KitError:
            if not self._adopt(rec, workflow):
                raise
        self._save(sdir, rec, state="submitted")
        return name

    def status(self, handle, workflow):
        sdir, rec = self._submitted(handle, "status")
        if "verdict" in rec:
            return self._status_of(rec["verdict"])
        reply = self._run_status(rec["run_name"], workflow, call="status")
        if reply is None:
            raise KitError(self.name, "status",
                           f"prodtools has no run {rec['run_name']!r}, though "
                           f"{sdir / 'record.json'} says it was submitted")
        state, progress = reply.get("state"), _progress(reply)
        if state == "unknown":
            since = rec.setdefault("unknown_since", self._clock())
            self._save(sdir, rec)
            note = reply.get("note")
            if self._clock() - since >= UNKNOWN_LIMIT_S:
                return self._decide(
                    sdir, rec, "failed",
                    f"run_status has said unknown for "
                    f"{UNKNOWN_LIMIT_S // 3600} h"
                    + (f": {note}" if note else ""))
            return self._working(f"unknown: {note or 'no note'}", progress)
        if rec.pop("unknown_since", None) is not None:
            self._save(sdir, rec)
        if state in WORKING:
            return self._working(state, progress)
        if state == "failed":
            return self._decide(sdir, rec, "failed", "prodtools: " + str(
                reply.get("error") or reply.get("note") or "failed"))
        if state == "cancelled":
            return self._decide(sdir, rec, "cancelled", "prodtools: cancelled")
        if state in ("done", "short"):
            return self._complete(sdir, rec, reply, progress)
        raise KitError(self.name, "status",
                       f"run_status returned state {state!r} for "
                       f"{rec['run_name']}, which this adapter does not know")

    def results(self, handle, workflow):
        _sdir, rec = self._submitted(handle, "results")
        verdict = rec.get("verdict") or {}
        if verdict.get("state") != "completed":
            raise KitError(self.name, "results",
                           f"{handle} is {verdict.get('state', 'unfinished')}"
                           f", not completed")
        return parse_results({"metrics": {"njobs": rec["njobs"],
                                          "njobs_ok": verdict["ok"]},
                              "files": rec["files"],
                              "metadata": rec["metadata"]}, self.name)

    def cancel(self, handle, workflow) -> str:
        _sdir, rec = self._submitted(handle, "cancel")
        if "cancel_run" not in self._write.tools:
            raise KitError(self.name, "cancel",
                           "the prodtools write server has no cancel_run tool")
        reply = call_with_retries(
            lambda: self._call(self._write, "cancel_run",
                               self._cancel_args(rec["run_name"]), workflow),
            call="cancel", retry_tool_errors=False, pause=self._pause)
        return parse_cancel({"state": reply.get("state")}, self.name)

    # --- submit ------------------------------------------------------------
    def _ensure_started(self) -> None:
        for client in (self._write, self._read):
            if not client.started:
                client.start()
        need = "submit_once" if self.executor == "grid" else "run_local"
        if need not in self._write.tools:
            raise KitError(self.name, "start",
                           f"the prodtools write server has no {need!r} tool "
                           f"(it has {sorted(self._write.tools)}); point "
                           f"AUTORESEARCH_PRODTOOLS at a checkout with code "
                           f"entries and run_local")
        if "run_status" not in self._read.tools:
            raise KitError(self.name, "start",
                           f"the prodtools read server has no 'run_status' "
                           f"tool (it has {sorted(self._read.tools)})")

    def _step_dir(self, config, step) -> Path:
        return self._grid_root / config / "prodtools" / step

    def _prepare(self, name, config, step, params, files, inputs, sdir,
                 digest) -> dict:
        geom = [f for f in files if f.get("name") == "geom"]
        geom_path = pe.local_path(geom[0], "prodtools: file") if geom else None
        geom_name = f"autoresearch_{config}_geom.txt" if geom else None
        template = params["entry"]
        staged = None
        if inputs:
            sources = [pe.local_path(ref, "prodtools: input")
                       for ref in inputs]
            dest = (self._pnfs_root / config / "staged" / step
                    if self.executor == "grid" else sdir / "staged")
            try:
                staged = (dest, pe.link_inputs(
                    sources, dest, allow_copy=self.executor == "local"))
            except OSError as exc:
                raise ValueError(f"prodtools: staging {len(sources)} "
                                 f"input(s) into {dest} failed: {exc}") from exc
        tarball = pe.build_code_tarball(
            Path(params["code_tarball"]), geom_path=geom_path,
            geom_name=geom_name,
            extra_files=pe.include_files(template, self._templates),
            out_dir=self._grid_root / config / "prodtools")
        fixed = {k: params[k] for k in ("njobs", "events_per_job",
                                        "memory_mb") if k in params}
        entry, facts = pe.entry_for_step(template, config=config, fixed=fixed,
                                         code_tarball=str(tarball),
                                         dsconf=params["dsconf"],
                                         geom_name=geom_name, staged=staged)
        entry_path = pe.write_entry_file(sdir / "entry.json", entry)
        return {"name": name, "digest": digest, "executor": self.executor,
                "state": "submitting", "entry_path": str(entry_path),
                "run_name": (f"cnf.{entry['owner']}.{facts['desc']}."
                             f"{facts['dsconf']}.0"),
                "desc": facts["desc"], "dsconf": facts["dsconf"],
                "njobs": facts["njobs"],
                "events_per_job": facts["events_per_job"],
                "output_glob": facts["output_glob"],
                "quorum": params["quorum"],
                "fatal_log_codes": list(params["fatal_log_codes"])}

    def _launch(self, rec, workflow) -> None:
        tool, args = self._launch_call(rec)
        lock = (_flock(self._submit_lock) if self.executor == "grid"
                else nullcontext())
        with lock:
            receipt = self._call(self._write, tool, args, workflow)
        if receipt.get("name") != rec["run_name"]:
            raise KitError(self.name, "submit",
                           f"prodtools named the run {receipt.get('name')!r}; "
                           f"expected {rec['run_name']!r}")

    def _adopt(self, rec, workflow) -> bool:
        """True when prodtools already has this step's run, past
        submission; False when it has none. A run created before the
        record's submitting_utc is not this step's (the config name was
        used before) and is an error, as is a receipt stuck in submitting
        or building: whether jobs reached the grid is unknown."""
        reply = self._run_status(rec["run_name"], workflow, call="submit")
        if reply is None:
            return False
        created, ours = reply.get("created_utc"), rec.get("submitting_utc")
        if (_utc_of(created, "run_status's created_utc", rec["run_name"])
                < _utc_of(ours, "the record's submitting_utc",
                          rec["run_name"])):
            config, _step = split_handle(rec["name"])
            raise KitError(
                self.name, "submit",
                f"{rec['run_name']} was created at {created}, before this "
                f"step started submitting at {ours}, so it is not this "
                f"step's run: the config name {config!r} was used before. "
                f"Pick a new config name")
        if reply.get("state") in ("submitting", "building"):
            raise KitError(
                self.name, "submit",
                f"{rec['run_name']}: its receipt is stuck in "
                f"{reply['state']!r}, so whether its jobs reached the grid "
                f"cannot be told. Look for its cluster in jobsub_q; this "
                f"point needs a new config name")
        return True

    # --- status ------------------------------------------------------------
    def _submitted(self, handle, call):
        config, step = split_handle(handle)
        sdir = self._step_dir(config, step)
        rec = _read_json(sdir / "record.json")
        if rec is None or rec.get("state") != "submitted":
            raise KitError(self.name, call, f"{handle}: no submitted run is "
                           f"recorded in {sdir / 'record.json'}")
        return sdir, rec

    def _complete(self, sdir, rec, reply, progress):
        jobs = reply.get("jobs") or {}
        njobs, ok = int(rec["njobs"]), int(jobs.get("ok", 0))
        if reply.get("outputs_truncated") is not None:
            return self._decide(
                sdir, rec, "failed",
                f"run_status truncated the output list "
                f"({reply['outputs_truncated']} ok jobs), so not every "
                f"output can be seen")
        if ok == 0 or ok / njobs < rec["quorum"]:
            return self._decide(sdir, rec, "failed",
                                f"{ok}/{njobs} jobs ok, below quorum "
                                f"{rec['quorum']}", progress=progress)
        outputs = {int(i): list(p)
                   for i, p in (reply.get("outputs") or {}).items()}
        every = [p for ps in outputs.values() for p in ps]
        missing = [p for p in every if not os.path.exists(p)]
        unlogged = _jobs_without_log(outputs)
        if missing or unlogged:
            # A successful job's .log lags on /pnfs like its outputs do.
            since = rec.setdefault("missing_since", self._clock())
            self._save(sdir, rec)
            waited = self._clock() - since >= STAGEOUT_LIMIT_S
            if waited and missing:
                return self._decide(
                    sdir, rec, "failed",
                    f"{len(missing)} of {len(every)} outputs still missing "
                    f"{STAGEOUT_LIMIT_S // 60} min after the jobs ended, "
                    f"e.g. {missing[0]}")
            if not waited:
                what = ([f"{len(missing)} of {len(every)} outputs missing"]
                        if missing else [])
                if unlogged:
                    what.append(f"{len(unlogged)} of {len(outputs)} "
                                f"successful jobs have no .log")
                return self._working("waiting for stage-out: "
                                     + "; ".join(what), progress)
        problem = self._scan_logs(rec, reply, unlogged)
        if problem:
            return self._decide(sdir, rec, "failed", problem,
                                progress=progress)
        files = [{"name": Path(p).name, "uri": Path(p).absolute().as_uri(),
                  "kind": Path(p).suffix.lstrip(".") or "file"}
                 for p in sorted(every)
                 if fnmatch.fnmatch(Path(p).name, rec["output_glob"])]
        if not files:
            return self._decide(
                sdir, rec, "failed",
                f"no output of the {ok} successful jobs matches "
                f"{rec['output_glob']!r}, so a downstream step would get no "
                f"inputs")
        rec["files"], rec["metadata"] = files, self._metadata(rec, reply)
        return self._decide(sdir, rec, "completed",
                            f"{ok}/{njobs} jobs ok", ok=ok, progress=progress)

    def _scan_logs(self, rec, reply, unlogged):
        if unlogged:        # still, after the stage-out wait
            index, job_dir = unlogged[0]
            where = f" in {job_dir}" if job_dir else ""
            return (f"job {index} succeeded but has no .log file{where}, "
                    f"so the fatal-log scan could not run")
        if self.executor == "grid":
            # prodtools' flat <outstage>/<cluster>/<proc>/ layout.
            logs = (Path(reply["outstage"]) / str(reply["cluster_id"])).glob(
                "*/*.log")
        else:
            logs = Path(reply["receipt"]).parent.glob("job_*/*.log")
        for log in sorted(logs):
            text = log.read_text(errors="replace")
            for code in rec["fatal_log_codes"]:
                if code in text:
                    return f"fatal log code {code} in {log}"
        return None

    def _metadata(self, rec, reply) -> dict:
        codes = (reply.get("jobs") or {}).get("exit_codes") or {}
        md = {"events_per_job": rec["events_per_job"],
              "executor": self.executor, "run_name": rec["run_name"],
              "desc": rec["desc"], "dsconf": rec["dsconf"],
              "failed_exit_codes": {str(k): v for k, v in codes.items()},
              "prodtools_version": self._write.server_version}
        if self.executor == "grid":
            md.update(jobid=reply.get("jobid"), outstage=reply.get("outstage"))
        else:
            md.update(host=reply.get("host"), pid=reply.get("pid"),
                      run_dir=str(Path(reply["receipt"]).parent))
        return md

    # --- call arguments ----------------------------------------------------
    # Built here only, so the opt-in real-server test in
    # tests/test_prodtools_adapter.py checks exactly what is sent.
    def _launch_call(self, rec):
        """(tool, args) of this executor's submit."""
        args = {"json": rec["entry_path"], "desc": rec["desc"],
                "dsconf": rec["dsconf"], "run_as": "self"}
        if self.executor == "grid":
            return "submit_once", args
        return "run_local", dict(args, parallel=self.parallel)

    @staticmethod
    def _cancel_args(run_name) -> dict:
        return {"name": run_name, "run_as": "self"}

    @staticmethod
    def _run_status_args(run_name) -> dict:
        return {"name": run_name, "user": pe.USER}

    # --- plumbing ----------------------------------------------------------
    def _call(self, client, tool, args, workflow):
        return client.call(tool, args, timeout_s=client.config.timeouts[tool],
                           workflow=workflow)

    def _run_status(self, run_name, workflow, *, call):
        """run_status for one run, or None when prodtools has no such run.
        The read server reports failures as a REPLY of exactly
        {"error": {kind, ...}}; any kind but not_found is raised, after the
        read-only retries. A run's own `error` field (a plain string, set
        alongside state="failed") is a different thing and must not be
        mistaken for this sentinel -- only a dict-shaped "error" is it.
        `call` names the contract call it serves, which sets its retry
        budget (contract.RETRY_PAUSES_S)."""
        def once():
            reply = self._call(self._read, "run_status",
                               self._run_status_args(run_name), workflow)
            err = reply.get("error")
            if isinstance(err, dict) and err.get("kind") != "not_found":
                raise KitToolError(
                    self.name, "run_status",
                    f"{err.get('kind')}: {err.get('message')} "
                    f"{err.get('remedy') or ''}".strip())
            return reply
        reply = call_with_retries(once, call=call, retry_tool_errors=True,
                                  pause=self._pause)
        return None if isinstance(reply.get("error"), dict) else reply

    def _utc_now(self) -> str:
        """Now, in prodtools' receipt format (utils/run_receipt.py:_now)."""
        return datetime.datetime.fromtimestamp(
            self._clock(), datetime.timezone.utc).isoformat(timespec="seconds")

    def _save(self, sdir, rec, **fields) -> None:
        rec.update(fields)
        _write_json(sdir / "record.json", rec)

    def _working(self, message, progress):
        return parse_status({"state": "working", "message": message,
                             "poll_ms": self._poll_ms, "progress": progress},
                            self.name)

    def _decide(self, sdir, rec, state, message, **extra):
        rec["verdict"] = {"state": state, "message": message, **extra}
        self._save(sdir, rec)
        return self._status_of(rec["verdict"])

    def _status_of(self, verdict):
        return parse_status({"state": verdict["state"],
                             "message": verdict["message"], "poll_ms": 0,
                             "progress": verdict.get("progress")}, self.name)
