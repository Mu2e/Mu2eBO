"""anakit as a contract kit: the adapter the engine drives for every
`kit: "anakit"` step (Phase C2b spec,
docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md, "3. The
anakit adapter").

anakit is M. MacKenzie's analysis MCP server; we run our fork, the checkout
$AUTORESEARCH_ANAKIT names. A step names the analysis in its fixed
`analysis`; every other param except the study's `work_area` setting is
passed to that analysis as a parameter. The physics lives in anakit; this
module holds none.

anakit runs an analysis synchronously, and one server runs one at a time
(FastMCP calls a sync tool on its event loop). So submit starts a server of
its own on the study's work area, runs the analysis to the end, writes the
reply to <GRID_DATA_ROOT>/<config>/anakit/<step>/anakit_result.json and
closes the server. The engine runs every step in its own thread, so the
wait holds up nothing else. status and results only read that file. A point
resumed after a crash mid-analysis has no handle for the step yet, so the
analysis runs again.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

if __package__ == "core.adapters":
    from core import kit_config, paths
    from core.adapters import prodtools_entry as pe
    from core.contract import ContractError, parse_results, parse_status
    from core.kits import KitClient, KitError
    from core.study import expand_artifact
else:
    import kit_config
    import paths
    from adapters import prodtools_entry as pe
    from contract import ContractError, parse_results, parse_status
    from kits import KitClient, KitError
    from study import expand_artifact

VERSION = "anakit-adapter/1"          # bump when a step would measure anew
SERVER = "anakit"                      # kits.toml [servers.anakit]
FORK_ENV = "AUTORESEARCH_ANAKIT"       # the anakit checkout
RESULT_NAME = "anakit_result.json"
# anakit's own limit on one run (its run_analysis allows at most 7200 s).
# The MCP call's timeout (kits.toml) must leave CALL_MARGIN_S above it, so
# anakit reports its own timeout instead of the call being cut off.
RUN_TIMEOUT_S = 3000
CALL_MARGIN_S = 300
OWN_PARAMS = ("work_area", "analysis")  # read here, never sent to anakit


def _error(call, message) -> KitError:
    return KitError(SERVER, call, message)


def fork_root() -> Path:
    """The anakit checkout $AUTORESEARCH_ANAKIT names."""
    root = os.environ.get(FORK_ENV)
    if not root:
        raise _error("open", f"{FORK_ENV} is not set; export it to the "
                     f"anakit checkout (the directory holding "
                     f"analysis_mcp_server/)")
    root = Path(root)
    if not (root / "analysis_mcp_server" / "__main__.py").is_file():
        raise _error("open", f"{FORK_ENV}={root} is not an anakit checkout "
                     f"(no analysis_mcp_server/__main__.py)")
    return root


def _git(root, *args, call) -> str:
    # A quota-limited or flaky filesystem under `root`, or a missing git
    # binary, must not crash the engine child: core/scheduler.py's run_steps
    # only catches (KitError, ContractError, KeyError, ValueError), so both
    # failures are rewrapped as KitError, naming the git command (as the
    # sibling adapters rewrap OSError -- core/adapters/offline_preflight.py
    # check(), core/adapters/prodtools.py _prepare()).
    try:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise _error(call, f"git {' '.join(args)} in {root} timed out after "
                     f"60 s") from exc
    except OSError as exc:
        raise _error(call, f"git {' '.join(args)} in {root} could not run: "
                     f"{exc}") from exc
    if r.returncode != 0:
        raise _error(call, f"git {' '.join(args)} in {root} failed: "
                     f"{r.stderr.strip()}")
    return r.stdout.strip()


def fork_commit(root) -> str:
    """The checkout's commit, refused when it has uncommitted changes:
    measure_sha tells builds of the analyses apart by this commit alone."""
    dirty = _git(root, "status", "--porcelain", call="open")
    if dirty:
        raise _error("open", f"the anakit checkout {root} has uncommitted "
                     f"changes, so measure_sha could not tell this build of "
                     f"the analyses from the committed one; commit them "
                     f"first:\n{dirty}")
    return _git(root, "rev-parse", "--short=12", "HEAD", call="open")


def code_commit(work_area) -> str:
    """Which Mu2eOptAna the work area's EdepAna was built from, for the
    record. Not part of measure_sha: a rebuilt EdepAna gets a new work-area
    directory, and the work area's path is a study setting."""
    return _git(Path(work_area) / "Mu2eOptAna", "describe", "--always",
                "--dirty", call="submit")


def backing_problem(work_area, code_tarball):
    """Why the work area's EdepAna is not built on the release the study's
    jobs run, or None: its `backing` link against the code tarball's
    `Code/backing` link, read from the archive without unpacking it."""
    link = Path(work_area) / "backing"
    if not link.is_symlink():
        return f"work area {work_area} has no backing link"
    try:
        mine = os.path.normpath(os.readlink(link))
    except OSError as exc:
        return f"cannot read backing link {link}: {exc}"
    try:
        with tarfile.open(code_tarball) as tf:
            member = tf.getmember("Code/backing")
    except KeyError:
        return f"code tarball {code_tarball} has no Code/backing"
    except (OSError, tarfile.TarError) as exc:
        return f"cannot read code tarball {code_tarball}: {exc}"
    if not member.issym():
        return f"Code/backing in {code_tarball} is not a link"
    theirs = os.path.normpath(member.linkname)
    if mine != theirs:
        return (f"work area {work_area} is backed by {mine}, but the code "
                f"tarball {code_tarball} by {theirs}: EdepAna must be built "
                f"on the release the jobs run")
    return None


def split_handle(name: str):
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"anakit: {name!r} is not <config>.<step>")
    return config, step


def _check_timeouts(server) -> None:
    missing = [k for k in ("list_analyses", "run_analysis")
               if k not in server.timeouts]
    if missing:
        raise _error("open", f"kits.toml [servers.{SERVER}] timeouts lack "
                     f"{missing}")
    need = RUN_TIMEOUT_S + CALL_MARGIN_S
    if server.timeouts["run_analysis"] < need:
        raise _error("open", f"kits.toml [servers.{SERVER}] run_analysis "
                     f"timeout {server.timeouts['run_analysis']:g} s must be "
                     f"at least {need} s: the adapter stops a run at "
                     f"{RUN_TIMEOUT_S} s")


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


class AnakitKit:
    """One campaign child's handle on anakit. run_steps' threads share it,
    one step each; each submit has its own server and step directory."""

    name = "anakit"
    accepts_lists = False
    EXECUTORS = ("grid", "local")     # every analysis runs on this node
    LAUNCH_STAGGER_S = 0.0
    poll_s = (1.0, 5.0)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 server=None, client_factory=None, grid_root=None,
                 fork=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"anakit: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign = campaign
        self._fork_root = Path(fork) if fork is not None else fork_root()
        # Read again at the start of every submit (measure_sha must label
        # the build that actually ran; a step can run hours after open).
        self._open_commit = fork_commit(self._fork_root)
        self._version = f"{VERSION}+anakit-{self._open_commit}"
        if server is None:
            servers = kit_config.load_server_configs()
            if SERVER not in servers:
                raise _error("open", f"kits.toml has no [servers.{SERVER}]")
            server = servers[SERVER]
        _check_timeouts(server)
        self._server = server
        trace = paths.GRAPH_DATA / campaign
        self._factory = client_factory or (
            lambda cfg: KitClient(cfg, campaign=campaign, trace_dir=trace))
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._catalogues = {}
        self._lock = threading.Lock()

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return self._version

    @property
    def tools(self) -> frozenset:
        return frozenset({"submit", "status", "results"})

    def describe(self):
        return None     # per analysis, not per kit: see step_problems

    def close(self) -> None:
        pass            # each server is closed by the call that started it

    def submit(self, name, params, files, inputs, workflow) -> str:
        # The fork's commit is read once at open (self._version); a step can
        # run hours later, so re-check it here rather than trust a stale
        # label. fork_commit itself raises when the checkout has gone dirty
        # since open; a clean checkout on a DIFFERENT commit is caught below.
        current = fork_commit(self._fork_root)
        if current != self._open_commit:
            raise _error("submit", f"the anakit checkout {self._fork_root} "
                         f"moved from commit {self._open_commit} (read when "
                         f"this campaign's kit opened) to {current}: "
                         f"measure_sha must label the build that actually "
                         f"ran, so submit refuses; restart the campaign to "
                         f"pick up the new commit")
        config, step = split_handle(name)
        if files:
            raise ValueError(f"anakit: takes no step files, got "
                             f"{[f.get('name') for f in files]}")
        params = dict(params)
        for key in OWN_PARAMS:
            if not params.get(key):
                raise ValueError(f"anakit: param {key!r} is missing")
        work_area, analysis = params.pop("work_area"), params.pop("analysis")
        if not inputs:
            raise ValueError(f"anakit: {name} has no input files (its "
                             f"files_from steps gave none)")
        data = [str(pe.local_path(ref, "anakit: input")) for ref in inputs]
        code = code_commit(work_area)
        sdir = self._step_dir(config, step)
        # GRID_DATA_ROOT sits on a quota-limited volume (EDQUOT has
        # happened); an OSError here must not crash the engine child (see
        # the note on _git).
        try:
            if sdir.exists():
                shutil.rmtree(sdir)  # this step's own directory, from a rerun
            sdir.mkdir(parents=True)
        except OSError as exc:
            raise ValueError(f"anakit: preparing step directory {sdir} "
                             f"failed: {exc}") from exc
        client = self._client(work_area)
        try:
            spec = self._analyses(client, workflow).get(analysis)
            if spec is None:
                raise ValueError(f"anakit: no analysis {analysis!r} in "
                                 f"{work_area}")
            # No silent fallback: a catalogue entry missing either field is
            # anakit's list_analyses reply breaking the contract, not a
            # reasonable default to assume.
            if "takes_data_files" not in spec:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has no 'takes_data_files'")
            if "metrics" not in spec:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has no 'metrics'")
            args = {"analysis": analysis, "output_dir": str(sdir),
                    "parameters": params, "timeout_s": RUN_TIMEOUT_S}
            if spec["takes_data_files"]:
                args["data_files"] = data
            elif len(data) == 1:
                args["data_file"] = data[0]
            else:
                raise ValueError(f"anakit: {analysis} takes one ROOT file, "
                                 f"got {len(data)}")
            reply = self._call(client, "run_analysis", args, workflow)
        finally:
            client.close()
        result_path = sdir / RESULT_NAME
        try:
            _write_json(result_path, {
                "handle": name, "analysis": analysis,
                "work_area": str(work_area), "code": code,
                "version": self._version, "metrics": list(spec["metrics"]),
                "reply": reply})
        except OSError as exc:
            raise ValueError(f"anakit: writing {result_path} failed: "
                             f"{exc}") from exc
        return name

    def status(self, handle, workflow):
        rec = self._record(handle)
        if rec is None:
            return self._status(
                "failed", f"anakit: no {RESULT_NAME} for {handle}: the step "
                f"directory was removed after the analysis ran; delete the "
                f"point's state/<step>_cluster.txt and broken.txt to run it "
                f"again")
        reply = rec["reply"]
        if isinstance(reply, dict) and reply.get("status") == "success":
            return self._status("completed", str(reply.get("message", "")))
        message = reply.get("message") if isinstance(reply, dict) else reply
        return self._status("failed", f"anakit {rec['analysis']}: {message}")

    def results(self, handle, workflow):
        rec = self._record(handle)
        if rec is None or rec["reply"].get("status") != "success":
            raise ContractError(self.name, "results",
                                f"{handle} has no successful result")
        if rec["version"] != self._version:
            raise ContractError(self.name, "results", f"{handle}'s result "
                                f"was written by build {rec['version']!r}, "
                                f"not this campaign's {self._version!r}: "
                                f"rerun the step")
        reply = rec["reply"]
        meta = dict(reply.get("metadata") or {})
        missing = [m for m in rec["metrics"] if m not in meta]
        if missing:
            raise ContractError(self.name, "results", f"anakit's reply "
                                f"lacks declared metric(s) {missing}")
        metrics = {m: meta.pop(m) for m in rec["metrics"]}
        files = [{"name": Path(p).name, "uri": Path(p).resolve().as_uri(),
                  "kind": Path(p).suffix.lstrip(".") or "file"}
                 for p in reply.get("files", [])]
        meta.update(message=reply.get("message"), work_area=rec["work_area"],
                    code=rec["code"], adapter=rec["version"])
        return parse_results({"metrics": metrics, "files": files,
                              "metadata": meta}, self.name)

    # --- the launch check (contract.kit_step_problems) ---------------------
    def step_problems(self, study, step) -> list:
        where = f"step {step.step!r} (kit anakit)"
        work_area = study.kits.get(self.name, {}).get("work_area")
        if not work_area:
            return [f"{where}: kits.anakit.work_area is not set"]
        if not Path(work_area).is_dir():
            return [f"{where}: work area {work_area} is not a directory"]
        problems = []
        tarball = study.kits.get("prodtools", {}).get("code_tarball")
        if tarball is not None:
            why = backing_problem(work_area, tarball)
            if why:
                problems.append(f"{where}: {why}")
        analyses = self._catalogue(work_area,
                                   f"{self.campaign}/launch/{self.name}")
        analysis = step.fixed.get("analysis")
        spec = analyses.get(analysis)
        if spec is None:
            return problems + [f"{where}: anakit has no analysis "
                               f"{analysis!r}; it has {sorted(analyses)}"]
        declared = spec.get("parameters", {})
        sent = (set(step.fixed) | set(step.params)) - set(OWN_PARAMS)
        unknown = sorted(sent - set(declared))
        if unknown:
            problems.append(f"{where}: {analysis} does not take {unknown} "
                            f"(it takes {sorted(declared)})")
        needed = sorted(n for n, p in declared.items()
                        if p.get("required") and n not in sent)
        if needed:
            problems.append(f"{where}: {analysis} needs {needed}")
        # Two cheap, generic launch checks on the step's literal (fixed)
        # values -- generic because they only compare against the
        # catalogue's own declared kind/bounds, never anakit's physics, so
        # the adapter stays physics-free. step.params values are knob names
        # resolved only at run time, so only fixed values can be checked here.
        for pname, value in sorted(step.fixed.items()):
            if pname in OWN_PARAMS or pname not in declared:
                continue
            decl = declared[pname]
            if decl.get("kind") == "text":
                if not isinstance(value, str):
                    continue
                expanded = expand_artifact(value, f"{where}[{pname}]")
                if os.path.isabs(expanded) and not Path(expanded).exists():
                    problems.append(f"{where}: {pname}={expanded!r} does "
                                    f"not exist")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum, maximum = decl.get("minimum"), decl.get("maximum")
                if minimum is not None and value < minimum:
                    problems.append(f"{where}: {pname}={value!r} is below "
                                    f"the minimum {minimum!r}")
                elif maximum is not None and value > maximum:
                    problems.append(f"{where}: {pname}={value!r} is above "
                                    f"the maximum {maximum!r}")
        if "metrics" not in spec:
            # No silent fallback: a catalogue entry with no 'metrics' is
            # anakit's list_analyses reply breaking the contract, not an
            # analysis that returns nothing.
            problems.append(f"{where}: anakit's list_analyses reply for "
                            f"analysis {analysis!r} has no 'metrics'")
            return problems
        wanted = sorted({m.metric.split(".", 1)[1]
                         for m in tuple(study.objectives)
                         + tuple(study.extra_metrics)
                         if m.metric.split(".", 1)[0] == step.step})
        absent = [m for m in wanted if m not in spec["metrics"]]
        if absent:
            problems.append(f"{where}: {analysis} does not return {absent}")
        return problems

    # --- plumbing ----------------------------------------------------------
    def _client(self, work_area):
        cfg = dataclasses.replace(
            self._server,
            command=tuple(self._server.command) + ("--work-area",
                                                   str(work_area)))
        return self._factory(cfg)

    def _call(self, client, tool, args, workflow):
        return client.call(tool, args, timeout_s=self._server.timeouts[tool],
                           workflow=workflow)

    def _analyses(self, client, workflow) -> dict:
        reply = self._call(client, "list_analyses", {}, workflow)
        analyses = (reply.get("metadata") or {}).get("analyses") \
            if isinstance(reply, dict) else None
        if not isinstance(analyses, dict):
            raise KitError(SERVER, "list_analyses", f"reply has no "
                           f"metadata.analyses: {str(reply)[:200]}")
        return analyses

    def _catalogue(self, work_area, workflow) -> dict:
        with self._lock:
            if work_area not in self._catalogues:
                client = self._client(work_area)
                try:
                    self._catalogues[work_area] = self._analyses(client,
                                                                 workflow)
                finally:
                    client.close()
            return self._catalogues[work_area]

    def _step_dir(self, config, step) -> Path:
        return self._grid_root / config / "anakit" / step

    def _record(self, handle):
        config, step = split_handle(handle)
        path = self._step_dir(config, step) / RESULT_NAME
        if not path.exists():
            return None
        try:
            text = path.read_text()
        except OSError as exc:
            raise ValueError(f"anakit: reading {path} failed: {exc}") from exc
        rec = json.loads(text)
        if rec.get("handle") != handle:
            raise ContractError(self.name, "status", f"{path} holds "
                                f"{rec.get('handle')!r}, not {handle!r}")
        return rec

    def _status(self, state, message):
        return parse_status({"state": state, "message": message,
                             "poll_ms": 0, "progress": None}, self.name)
