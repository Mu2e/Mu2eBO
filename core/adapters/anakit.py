"""anakit as a contract kit: the adapter the engine drives for every
`kit: "anakit"` step (Phase C2b spec,
docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md, "3. The
anakit adapter"; on a Musing since
docs/superpowers/specs/2026-10-07-upstream-analyses-design.md).

anakit is M. MacKenzie's analysis MCP server, run from the checkout of his
main that $AUTORESEARCH_ANAKIT names. Its mu2e jobs set up the published
Musing the study's `musing` setting names (e.g. "SimJob MDC2025ay"), which
the server is started on with --musing. A step names the analysis in its
fixed `analysis`; every other param except the study's `musing` setting is
passed to that analysis as a parameter. The physics lives in anakit; this
module holds none.

anakit runs an analysis synchronously, and one server runs one at a time
(FastMCP calls a sync tool on its event loop). So submit starts a server of
its own on the study's Musing, runs the analysis to the end, writes the
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
import threading
from functools import partial
from pathlib import Path

import kit_config
import kit_registry
import paths
from adapters import prodtools_entry as pe
from contract import ContractError, make_status, parse_results
from kits import KitClient, KitError
from point_dir import write_atomic
from study import expand_artifact, metrics_read

# The kit's version, hand-bumped (2026-10-05): bump when a step would
# measure anew, INCLUDING a checkout change that alters what an analysis
# computes. The checkout commit is not part of it: it is the step's recorded
# build (anakit_result.json "build", the results metadata "build"), so an
# unrelated commit never splits a board. 2: the server runs on a Musing
# (--musing), not on our work area (2026-10-07).
VERSION = "anakit-adapter/2"
# The checkout of M. MacKenzie's main the anakit studies were accepted
# against (2026-10-07). The suite asserts the checkout matches: his
# analyses' defaults and the DIO constants sit outside measure_basis, so a
# moved checkout is caught there. Bump it deliberately after re-validating,
# and bump VERSION too when an analysis now computes differently.
ANAKIT_PIN_SHA = "3ba8d23bbf47f97b5b11c36a0e20ce695a1089af"
SERVER = "anakit"                      # kits.toml [servers.anakit]
CHECKOUT_ENV = "AUTORESEARCH_ANAKIT"       # the anakit checkout
RESULT_NAME = "anakit_result.json"
# anakit's own limit on one run (its run_analysis allows at most 7200 s).
# The MCP call's timeout (kits.toml) must leave CALL_MARGIN_S above it, so
# anakit reports its own timeout instead of the call being cut off.
RUN_TIMEOUT_S = 3000
CALL_MARGIN_S = 300
# The input_kind values list_analyses may report; "art_files" is a mu2e
# job over art files, "root_file" a Python analysis.
INPUT_KINDS = ("art_files", "root_file")
OWN_PARAMS = ("musing", "analysis")  # read here, never sent to anakit
# Where published Musings live: <root>/<Musing>/<version> (anakit's own
# tools/mu2e_env.py MUSINGS_ROOT). Read to refuse an unpublished Musing at
# launch; never searched.
MUSINGS_ROOT = Path("/cvmfs/mu2e.opensciencegrid.org/Musings")


def _error(call, message) -> KitError:
    return KitError(SERVER, call, message)


def checkout_root() -> Path:
    """The anakit checkout $AUTORESEARCH_ANAKIT names."""
    root = os.environ.get(CHECKOUT_ENV)
    if not root:
        raise _error("open", f"{CHECKOUT_ENV} is not set; export it to the "
                     f"anakit checkout (the directory holding "
                     f"analysis_mcp_server/)")
    root = Path(root)
    if not (root / "analysis_mcp_server" / "__main__.py").is_file():
        raise _error("open", f"{CHECKOUT_ENV}={root} is not an anakit checkout "
                     f"(no analysis_mcp_server/__main__.py)")
    return root


def _git(root, *args, call) -> str:
    # A timeout or a missing git binary is rewrapped as KitError to name
    # the git command and the checkout, which the bare exception does not.
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


def checkout_commit(root) -> str:
    """The checkout's commit, refused when it has uncommitted changes: a
    step's recorded build tells builds of the analyses apart by this commit
    alone."""
    dirty = _git(root, "status", "--porcelain", call="open")
    if dirty:
        raise _error("open", f"the anakit checkout {root} has uncommitted "
                     f"changes, so the step's recorded build could not tell "
                     f"this build of the analyses from the committed one; "
                     f"commit them first:\n{dirty}")
    return _git(root, "rev-parse", "--short=12", "HEAD", call="open")


def musing_parts(musing: str):
    """(Musing, version) from "SimJob MDC2025ay" or "SimJob/MDC2025ay", as
    anakit's Mu2eEnv.for_musing splits it; None unless exactly two."""
    parts = str(musing).replace("/", " ").split()
    return tuple(parts) if len(parts) == 2 else None


split_handle = partial(kit_registry.split_handle, "anakit")


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


class AnakitKit:
    """One campaign child's handle on anakit. run_steps' threads share it,
    one step each; each submit has its own server and step directory."""

    name = "anakit"
    accepts_lists = False
    poll_s = (1.0, 5.0)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 server=None, client_factory=None, grid_root=None,
                 checkout=None):
        executors = kit_registry.KITS[self.name].executors
        if executor not in executors:
            raise ValueError(f"{self.name}: executor must be one of "
                             f"{list(executors)}, got {executor!r}")
        self.campaign = campaign
        self._checkout_root = Path(checkout) if checkout is not None else checkout_root()
        # A dirty checkout is refused at open (and again at every submit,
        # which records the commit it ran as the step's build).
        checkout_commit(self._checkout_root)
        self._version = VERSION
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
    def start(self) -> None:
        """Nothing to start: each call starts and closes its own server."""

    @property
    def version(self) -> str:
        return self._version

    @property
    def build(self) -> str:
        """The checkout's commit now (a dirty checkout is refused)."""
        return checkout_commit(self._checkout_root)

    @property
    def tools(self) -> frozenset:
        return frozenset({"submit", "status", "results"})

    def describe(self):
        return None     # per analysis, not per kit: see step_problems

    def close(self) -> None:
        pass            # each server is closed by the call that started it

    def submit(self, name, params, files, inputs, workflow) -> str:
        # Every submit starts its own analysis server from the checkout, so
        # the commit read here is the build this step runs: recorded as its
        # build. A dirty checkout raises (checkout_commit).
        build = checkout_commit(self._checkout_root)
        config, step = split_handle(name)
        if files:
            raise ValueError(f"anakit: takes no step files, got "
                             f"{[f.get('name') for f in files]}")
        params = dict(params)
        for key in OWN_PARAMS:
            if not params.get(key):
                raise ValueError(f"anakit: param {key!r} is missing")
        musing, analysis = params.pop("musing"), params.pop("analysis")
        if not inputs:
            raise ValueError(f"anakit: {name} has no input files (its "
                             f"files_from steps gave none)")
        data = [str(pe.local_path(ref, "anakit: input")) for ref in inputs]
        sdir = self._step_dir(config, step)
        # GRID_DATA_ROOT sits on a quota-limited volume (EDQUOT has
        # happened); KitSet.get turns the OSError into a KitError.
        if sdir.exists():
            shutil.rmtree(sdir)  # this step's own directory, from a rerun
        sdir.mkdir(parents=True)
        client = self._client(musing)
        try:
            spec = self._analyses(client, workflow).get(analysis)
            if spec is None:
                raise ValueError(f"anakit: no analysis {analysis!r} on "
                                 f"Musing {musing}")
            # No silent fallback: a catalogue entry missing either field is
            # anakit's list_analyses reply breaking the contract, not a
            # reasonable default to assume.
            if "takes_data_files" not in spec:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has no 'takes_data_files'")
            if "metrics" not in spec:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has no 'metrics'")
            if "input_kind" not in spec:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has no 'input_kind'")
            if spec["input_kind"] not in INPUT_KINDS:
                raise _error("list_analyses", f"anakit's reply for analysis "
                             f"{analysis!r} has input_kind "
                             f"{spec['input_kind']!r}; known kinds "
                             f"{list(INPUT_KINDS)}")
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
        write_atomic(result_path, json.dumps({
            "handle": name, "analysis": analysis, "musing": musing,
            "version": self._version, "build": build,
            "metrics": list(spec["metrics"]),
            "reply": reply}, indent=1, sort_keys=True))
        return name

    def status(self, handle, workflow):
        rec = self._record(handle)
        if rec is None:
            return make_status(
                self.name, "failed",
                f"anakit: no {RESULT_NAME} for {handle}: the step "
                f"directory was removed after the analysis ran; delete the "
                f"point's state/<step>_cluster.txt and broken.txt to run it "
                f"again")
        reply = rec["reply"]
        if isinstance(reply, dict) and reply.get("status") == "success":
            return make_status(self.name, "completed",
                               str(reply.get("message", "")))
        message = reply.get("message") if isinstance(reply, dict) else reply
        return make_status(self.name, "failed",
                           f"anakit {rec['analysis']}: {message}")

    def results(self, handle, workflow):
        rec = self._record(handle)
        if rec is None or rec["reply"].get("status") != "success":
            raise ContractError(self.name, "results",
                                f"{handle} has no successful result")
        if rec["version"] != self._version:
            step = split_handle(handle)[1]
            raise ContractError(self.name, "results", f"{handle}'s result "
                                f"was written by version "
                                f"{rec['version']!r}, not this kit's "
                                f"{self._version!r}: rerun the step (delete "
                                f"the point's state/{step}_cluster.txt and "
                                f"broken.txt to run it again)")
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
        meta.update(message=reply.get("message"), musing=rec["musing"],
                    adapter=rec["version"], build=rec.get("build"))
        return parse_results({"metrics": metrics, "files": files,
                              "metadata": meta}, self.name)

    # --- the launch check (contract.kit_step_problems) ---------------------
    def step_problems(self, study, step) -> list:
        where = f"step {step.step!r} (kit anakit)"
        musing = study.kits.get(self.name, {}).get("musing")
        if not musing:
            return [f"{where}: kits.anakit.musing is not set"]
        parts = musing_parts(musing)
        if parts is None:
            return [f"{where}: kits.anakit.musing {musing!r}: expected a "
                    f"Musing and a version, e.g. 'SimJob MDC2025ay'"]
        published = MUSINGS_ROOT.joinpath(*parts)
        if not published.is_dir():
            return [f"{where}: Musing {musing!r} is not published (no "
                    f"{published})"]
        problems = []
        if not step.files_from:
            # submit refuses a step with no input files; say so before any
            # upstream step runs
            problems.append(f"{where}: anakit runs an analysis on input "
                            f"files, and this step has no files_from (a "
                            f"params_from value is not an input file)")
        analyses = self._catalogue(musing,
                                   f"{self.campaign}/launch/{self.name}")
        analysis = step.fixed.get("analysis")
        spec = analyses.get(analysis)
        if spec is None:
            return [f"{where}: anakit has no analysis "
                    f"{analysis!r}; it has {sorted(analyses)}"]
        if "input_kind" not in spec:
            # No silent fallback, as for 'metrics' below.
            return [f"{where}: anakit's list_analyses reply for analysis "
                    f"{analysis!r} has no 'input_kind'"]
        if spec["input_kind"] not in INPUT_KINDS:
            # A typo or a new upstream kind must not skip the art checks.
            return [f"{where}: anakit's list_analyses reply for analysis "
                    f"{analysis!r} has input_kind {spec['input_kind']!r}; "
                    f"known kinds {list(INPUT_KINDS)}"]
        declared = spec.get("parameters", {})
        sent = set(step.sent_params) - set(OWN_PARAMS)
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
        wanted = sorted(metrics_read(study, step.step))
        absent = [m for m in wanted if m not in spec["metrics"]]
        if absent:
            problems.append(f"{where}: {analysis} does not return {absent}")
        return problems

    # --- plumbing ----------------------------------------------------------
    def _client(self, musing):
        cfg = dataclasses.replace(
            self._server,
            command=tuple(self._server.command) + ("--musing", str(musing)))
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

    def _catalogue(self, musing, workflow) -> dict:
        with self._lock:
            if musing not in self._catalogues:
                client = self._client(musing)
                try:
                    self._catalogues[musing] = self._analyses(client,
                                                              workflow)
                finally:
                    client.close()
            return self._catalogues[musing]

    def _step_dir(self, config, step) -> Path:
        return self._grid_root / config / "anakit" / step

    def _record(self, handle):
        config, step = split_handle(handle)
        path = self._step_dir(config, step) / RESULT_NAME
        if not path.exists():
            return None
        rec = json.loads(path.read_text())
        if rec.get("handle") != handle:
            raise ContractError(self.name, "status", f"{path} holds "
                                f"{rec.get('handle')!r}, not {handle!r}")
        return rec

