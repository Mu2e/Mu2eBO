"""The evaluator contract (generic-study design, "The evaluator contract"):
reply validation, the Kit interface the engine drives, NativeKit (a kit
that speaks the contract over MCP), KitSet (the kits one child uses) and
launch_problems (the launch check both runners call).

A reply outside the contract raises ContractError: a failed evaluation,
never success. Replies must carry the keys the contract names, with the
right types; keys it doesn't name are ignored, so a kit can add fields.

The Kit interface, which NativeKit and every adapter implement:
  name, version, tools, accepts_lists, poll_s
  start() -> None   (idempotent; raises KitError when the kit cannot start)
  submit(name, params, files, inputs, workflow) -> handle
  status(handle, workflow) -> Status
  results(handle, workflow) -> Results
  check(name, params, files, inputs, workflow) -> (ok, message)
  describe() -> Describe | None
  cancel(handle, workflow) -> state
  close()
  step_problems(study, step) -> [str]   (optional; the launch check)

A kit raises only KitError or ContractError for a failure it expects: a
server that died, a refused call, a missing timeout, a full disk. KitSet.get
enforces this: it returns each kit inside a GuardedKit, which turns the
OSError, ValueError, KeyError and SubprocessError a kit's own code lets
escape (from its factory and from every attribute and method) into a
KitError naming the kit and the call. A programming error (TypeError,
AttributeError, ...) is not translated and crashes. Callers therefore catch
(KitError, ContractError) around kit calls; engine-side code keeps its own
ValueError/KeyError handling. A KitError the guard makes from a kit-side
ValueError, KeyError or OSError is a refusal or an environment failure, not
a transport failure, so it must not be fed to call_with_retries (which
retries a plain KitError); retries live inside the kits.

A kit is declared once, in kit_registry.KITS (an adapter kit there, a
native kit from kits.toml): its executors, launch stagger, Kerberos need,
config-name rule and, for an adapter, the factory string load_factory
imports.
"""
from __future__ import annotations

import functools
import importlib
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

if __package__:
    from core import kit_registry, paths
    from core.kit_config import EXECUTORS, _is_number
    from core.kits import KitClient, KitError, KitToolError
    from core.leaderboard import SchemaMismatch
else:
    import kit_registry
    import paths
    from kit_config import EXECUTORS, _is_number
    from kits import KitClient, KitError, KitToolError
    from leaderboard import SchemaMismatch

STATES = ("working", "completed", "failed", "cancelled")
REQUIRED_TOOLS = ("submit", "status", "results")
# Pauses between attempts, per contract call; a call makes one attempt
# more than it has pauses. submit, check and describe: a credential blip
# lasts seconds. status, results and cancel: read-only or idempotent, on a
# point that may have waited hours, so they ride out a server outage of
# minutes (5 attempts, about 4.5 min).
_BRIEF = (5.0, 20.0)
_PATIENT = (5.0, 20.0, 60.0, 180.0)
RETRY_PAUSES_S = {"submit": _BRIEF, "check": _BRIEF, "describe": _BRIEF,
                  "status": _PATIENT, "results": _PATIENT,
                  "cancel": _PATIENT}
MAX_PARALLEL = 16              # prodtools' MAX_LOCAL_PARALLEL
_URI_SCHEMES = ("file://", "root://")


def call_with_retries(fn, *, call, retry_tool_errors, pause=time.sleep):
    """fn() up to len(RETRY_PAUSES_S[call]) + 1 times, `call` being the
    contract call it serves. Transport failures and timeouts are retried;
    a tool error only when retry_tool_errors (a refused submit -- same
    name, different params -- must never be repeated). Between attempts
    it pauses RETRY_PAUSES_S[call]."""
    pauses = RETRY_PAUSES_S[call]
    for attempt in range(len(pauses) + 1):
        try:
            return fn()
        except KitToolError:
            if not retry_tool_errors or attempt == len(pauses):
                raise
        except KitError:
            if attempt == len(pauses):
                raise
        pause(pauses[attempt])


class ContractError(RuntimeError):
    def __init__(self, kit: str, call: str, message: str):
        super().__init__(f"kit {kit!r} {call}: reply outside the contract: "
                         f"{message}")
        self.kit, self.call, self.message = kit, call, message


@dataclass(frozen=True)
class Status:
    state: str
    message: str
    poll_ms: int
    progress: Optional[Dict[str, int]]


@dataclass(frozen=True)
class Results:
    metrics: Dict[str, float]
    files: Tuple[Dict[str, str], ...]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class Describe:
    params: Tuple[str, ...]
    metrics: Tuple[str, ...]
    accepts_lists: bool


def _fields(reply, keys, kit, call) -> dict:
    if not isinstance(reply, dict):
        raise ContractError(kit, call, f"expected an object, got {reply!r}")
    missing = [k for k in keys if k not in reply]
    if missing:
        raise ContractError(kit, call, f"missing key(s) {missing}")
    return reply


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_file_ref(v, kit, call) -> dict:
    ref = _fields(v, ("name", "uri", "kind"), kit, call)
    if not all(isinstance(ref[k], str) and ref[k]
               for k in ("name", "uri", "kind")):
        raise ContractError(kit, call, f"a FileRef's name, uri and kind are "
                            f"non-empty strings, got {ref!r}")
    if not ref["uri"].startswith(_URI_SCHEMES):
        raise ContractError(kit, call, f"a FileRef uri starts with "
                            f"{list(_URI_SCHEMES)}, got {ref['uri']!r}")
    return {"name": ref["name"], "uri": ref["uri"], "kind": ref["kind"]}


def parse_submit(reply, kit, name) -> str:
    handle = _fields(reply, ("handle",), kit, "submit")["handle"]
    if handle != name:
        raise ContractError(kit, "submit", f"the handle must be the submitted "
                            f"name {name!r} (handles are <config>.<step>), "
                            f"got {handle!r}")
    return handle


def parse_status(reply, kit) -> Status:
    r = _fields(reply, ("state", "message", "poll_ms", "progress"), kit,
                "status")
    if r["state"] not in STATES:
        raise ContractError(kit, "status", f"state must be one of "
                            f"{list(STATES)}, got {r['state']!r}")
    if not isinstance(r["message"], str):
        raise ContractError(kit, "status", "message must be a string")
    if not _is_int(r["poll_ms"]) or r["poll_ms"] < 0:
        raise ContractError(kit, "status", f"poll_ms must be an int >= 0, "
                            f"got {r['poll_ms']!r}")
    progress = r["progress"]
    if progress is not None:
        p = _fields(progress, ("done", "total", "ok"), kit, "status")
        if not all(_is_int(p[k]) and p[k] >= 0 for k in ("done", "total", "ok")):
            raise ContractError(kit, "status", "progress done, total and ok "
                                "must be ints >= 0")
        progress = {k: p[k] for k in ("done", "total", "ok")}
    return Status(r["state"], r["message"], r["poll_ms"], progress)


def parse_results(reply, kit) -> Results:
    r = _fields(reply, ("metrics", "files", "metadata"), kit, "results")
    metrics = r["metrics"]
    if not isinstance(metrics, dict) or not all(
            isinstance(k, str) and _is_number(v) for k, v in metrics.items()):
        raise ContractError(kit, "results", f"metrics must map names to "
                            f"numbers, got {metrics!r}")
    if not isinstance(r["files"], list):
        raise ContractError(kit, "results", "files must be a list of FileRefs")
    files = tuple(parse_file_ref(f, kit, "results") for f in r["files"])
    if not isinstance(r["metadata"], dict):
        raise ContractError(kit, "results", "metadata must be an object")
    return Results({k: float(v) for k, v in metrics.items()}, files,
                   dict(r["metadata"]))


def parse_check(reply, kit) -> Tuple[bool, str]:
    r = _fields(reply, ("ok", "message"), kit, "check")
    if not isinstance(r["ok"], bool) or not isinstance(r["message"], str):
        raise ContractError(kit, "check", "ok must be true or false and "
                            "message a string")
    return r["ok"], r["message"]


def parse_describe(reply, kit) -> Describe:
    r = _fields(reply, ("params", "metrics", "accepts_lists"), kit, "describe")
    for key in ("params", "metrics"):
        if not isinstance(r[key], list) or not all(isinstance(v, str)
                                                   for v in r[key]):
            raise ContractError(kit, "describe", f"{key} must be a list of "
                                f"names")
    if not isinstance(r["accepts_lists"], bool):
        raise ContractError(kit, "describe", "accepts_lists must be true or "
                            "false")
    return Describe(tuple(r["params"]), tuple(r["metrics"]),
                    r["accepts_lists"])


def parse_cancel(reply, kit) -> str:
    state = _fields(reply, ("state",), kit, "cancel")["state"]
    if state not in STATES:
        raise ContractError(kit, "cancel", f"state must be one of "
                            f"{list(STATES)}, got {state!r}")
    return state


class NativeKit:
    """A kit that speaks the contract over MCP: one kits.toml entry."""

    def __init__(self, config, client, *, pause=time.sleep):
        self.name = config.name
        self.config = config
        self.client = client
        self.accepts_lists = config.accepts_lists
        self.poll_s = config.poll_s
        self._pause = pause

    def start(self) -> None:
        """Start the server if it is not running; idempotent."""
        if not self.client.started:
            self.client.start()

    @property
    def version(self) -> str:
        self.start()
        return self.client.server_version or ""

    @property
    def tools(self) -> frozenset:
        self.start()
        return self.client.tools

    def _call(self, tool, args, workflow, *, retry_tool_errors):
        """Transport failures and timeouts are retried (the client respawns
        a lost server before the next call), with the pauses of the call's
        RETRY_PAUSES_S; see call_with_retries."""
        return call_with_retries(
            lambda: self.client.call(tool, args,
                                     timeout_s=self.config.timeouts[tool],
                                     workflow=workflow),
            call=tool, retry_tool_errors=retry_tool_errors,
            pause=self._pause)

    def submit(self, name, params, files, inputs, workflow) -> str:
        # Safe to repeat after a timeout: submit is idempotent by name.
        reply = self._call("submit", {"name": name, "params": params,
                                      "files": list(files),
                                      "inputs": list(inputs)},
                           workflow, retry_tool_errors=False)
        return parse_submit(reply, self.name, name)

    def status(self, handle, workflow) -> Status:
        return parse_status(self._call("status", {"handle": handle}, workflow,
                                       retry_tool_errors=True), self.name)

    def results(self, handle, workflow) -> Results:
        return parse_results(self._call("results", {"handle": handle},
                                        workflow, retry_tool_errors=True),
                             self.name)

    def check(self, name, params, files, inputs, workflow) -> Tuple[bool, str]:
        return parse_check(self._call("check", {"name": name, "params": params,
                                                "files": list(files),
                                                "inputs": list(inputs)},
                                      workflow, retry_tool_errors=True),
                           self.name)

    def describe(self) -> Optional[Describe]:
        if "describe" not in self.tools:
            return None
        workflow = f"{self.client.campaign}/launch/describe"
        return parse_describe(self._call("describe", {}, workflow,
                                         retry_tool_errors=True), self.name)

    def cancel(self, handle, workflow) -> str:
        return parse_cancel(self._call("cancel", {"handle": handle}, workflow,
                                       retry_tool_errors=False),
                            self.name)

    def close(self) -> None:
        self.client.close()


def load_factory(decl):
    """The adapter class `decl.factory` names ("module.path:Name", relative
    to core/). Imported here, not at module top: an adapter module imports
    this one. The module gets a `core.` prefix only when this module was
    itself imported as core.contract, so a flat import (graph/run.py)
    never loads a second copy of contract."""
    module, _, attr = decl.factory.partition(":")
    if __package__:
        module = f"core.{module}"
    return getattr(importlib.import_module(module), attr)


def open_kit(name: str, campaign: str, *, executor: str = "grid",
             parallel=None):
    decl = kit_registry.KITS.get(name)
    if decl is None:
        raise KeyError(f"kit {name!r} is not declared in "
                       f"core/kit_registry.py or kits.toml, so the contract "
                       f"engine cannot run it")
    if decl.factory is not None:
        return load_factory(decl)(campaign, executor=executor,
                                  parallel=parallel)
    cfg = kit_registry.NATIVE[name]
    return NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                    trace_dir=paths.GRAPH_DATA / campaign))


def launch_stagger(study) -> float:
    """Seconds between a campaign's child launches: the largest any of the
    study's kits asks for."""
    return max([0.0] + [kit_registry.KITS[name].launch_stagger_s
                        for name in kit_registry.kits_of(study)])


def _executors_of(name: str) -> tuple:
    return kit_registry.KITS[name].executors


def executor_problems(study, executor: str, parallel) -> List[str]:
    """Why the study cannot run with this --executor / --parallel; an empty
    list means it can."""
    if executor not in EXECUTORS:
        return [f"--executor must be one of {list(EXECUTORS)}, got "
                f"{executor!r}"]
    problems = []
    if parallel is not None:
        if executor != "local":
            problems.append("--parallel applies to --executor local only")
        elif not 1 <= parallel <= MAX_PARALLEL:
            problems.append(f"--parallel must be 1..{MAX_PARALLEL}, got "
                            f"{parallel}")
    for name in sorted(kit_registry.kits_of(study)):
        supported = _executors_of(name)
        if executor not in supported:
            problems.append(f"kit {name!r} cannot run with --executor "
                            f"{executor} (it supports {list(supported)})")
    return problems


def requires_kerberos(study, executor: str) -> bool:
    """True when a grid launch of this study needs a Kerberos ticket: some
    kit of it declares it (the prodtools kit does)."""
    if executor != "grid":
        return False
    return any(kit_registry.KITS[n].requires_kerberos
               for n in kit_registry.kits_of(study))


# A grid launch submits steps for HOURS, not once at the start, so validity
# now is not enough -- the ticket has to outlive the run (moved from the
# pipeline's core/launch_checks.py in Phase C3).
GRID_TICKET_SECONDS = 4 * 3600


def _klist_text() -> Optional[str]:
    """Raw `klist` output, or None when there is no usable ticket cache."""
    try:
        p = subprocess.run(["klist"], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _parse_klist_time(stamp: str) -> Optional[int]:
    """klist's local-time stamp as an epoch, or None if it does not parse.
    Both a 4- and 2-digit year are in the wild."""
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return int(datetime.strptime(stamp, fmt).timestamp())
        except ValueError:
            continue
    return None


def check_kerberos(min_seconds: int, *, klist_text=_klist_text,
                   now=time.time) -> Optional[str]:
    """Ticket present, and with `min_seconds` of life left.

    A ticket that expires mid-run kills the run at the next submit
    (wiki/incidents/kerberos-mid-run-expiry.md), and the prodtools input
    gate reports the resulting auth failure as "absent from dCache tape" --
    which reads as missing data, sending you to look at SAM instead of at
    your ticket.
    """
    text = klist_text()
    if not text:
        return "no valid Kerberos ticket -- run kinit first."
    krbtgt = [ln for ln in text.splitlines() if "krbtgt" in ln]
    if not krbtgt:
        return "no valid Kerberos ticket -- run kinit first."
    if min_seconds <= 0:
        return None
    # `MM/DD/YYYY HH:MM:SS  MM/DD/YYYY HH:MM:SS  krbtgt/...`: fields 3+4 are
    # the expiry. An unparseable line is NOT fatal -- klist's format is
    # locale-dependent, and refusing to launch over a date format would be
    # worse than the risk it guards.
    fields = krbtgt[0].split()
    if len(fields) < 4:
        return None
    expiry = _parse_klist_time(f"{fields[2]} {fields[3]}")
    if expiry is None:
        return None
    left = expiry - int(now())
    if left < min_seconds:
        return (f"Kerberos ticket has under {min_seconds // 3600} h left "
                f"({left // 60} min) -- a chain submits stages for hours and "
                f"will die at a later submit. Run 'kinit' before launching.")
    return None


KIT_FAILURES = (OSError, ValueError, KeyError, subprocess.SubprocessError)


class GuardedKit:
    """A kit seen through the error contract: any attribute read or call
    that raises one of KIT_FAILURES raises KitError(kit name, attribute
    name, "<type>: <message>") instead, chained from the original. KitError
    and ContractError (and every other exception, including AttributeError,
    so getattr(kit, "step_problems", None) still works) pass unchanged.
    Non-callable attributes are returned as they are."""

    def __init__(self, name: str, kit):
        self._name = name
        self._kit = kit

    def __getattr__(self, attr):
        try:
            value = getattr(self._kit, attr)
        except KIT_FAILURES as exc:
            raise self._as_kit_error(attr, exc) from exc
        if not callable(value):
            return value

        @functools.wraps(value)
        def guarded(*args, **kwargs):
            try:
                return value(*args, **kwargs)
            except KIT_FAILURES as exc:
                raise self._as_kit_error(attr, exc) from exc
        return guarded

    def close(self) -> None:
        try:
            self._kit.close()
        except KIT_FAILURES as exc:
            raise self._as_kit_error("close", exc) from exc

    def _as_kit_error(self, attr, exc) -> KitError:
        return KitError(self._name, attr, f"{type(exc).__name__}: {exc}")


class KitSet:
    """The kits one child uses: opened on first use (one server per kit),
    closed together. Thread-safe: run_steps' threads share it. get returns
    each kit as a GuardedKit, so a caller sees only KitError or
    ContractError from a kit."""

    def __init__(self, campaign: str, opener=None, *, executor: str = "grid",
                parallel=None):
        self.campaign = campaign
        self._opener = opener or functools.partial(
            open_kit, executor=executor, parallel=parallel)
        self._kits: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, name: str):
        with self._lock:
            if name not in self._kits:
                try:
                    kit = self._opener(name, self.campaign)
                except KIT_FAILURES as exc:
                    raise KitError(name, "open",
                                   f"{type(exc).__name__}: {exc}") from exc
                self._kits[name] = GuardedKit(name, kit)
            return self._kits[name]

    def close(self) -> None:
        with self._lock:
            kits, self._kits = list(self._kits.values()), {}
        first = None
        for kit in kits:
            try:
                kit.close()
            except Exception as exc:
                first = first or exc
        if first is not None:
            raise first


def _needs(study, kit_name):
    """(param names sent, metric keys read, params that carry a profile)
    for one kit of the study."""
    settings = set(study.kits.get(kit_name, {}))
    profiles = set(study.derive["profiles"])
    steps = [s for s in study.steps if s.kit == kit_name]
    mappings = [s.params for s in steps]
    params = set(settings)
    for s in steps:
        params |= set(s.params) | set(s.fixed)
    pre = study.preflight
    if pre is not None and pre["kit"] == kit_name:
        params |= set(pre["params"])
        mappings.append(pre["params"])
    profile_params = {k for m in mappings for k, v in m.items() if v in profiles}
    step_names = {s.step for s in steps}
    metrics = set()
    for m in tuple(study.objectives) + tuple(study.extra_metrics):
        step, key = m.metric.split(".", 1)
        if step in step_names:
            metrics.add(key)
    return params, metrics, profile_params


def kit_step_problems(kit, study, name: str) -> List[str]:
    """What kit `name`'s optional step_problems(study, step) hook says about
    each step of the study that uses it: an adapter's per-step launch check
    (a wrong analysis name or parameter, refused before any job runs). A kit
    without the hook has nothing to say."""
    hook = getattr(kit, "step_problems", None)
    if hook is None:
        return []
    return [p for s in study.steps if s.kit == name for p in hook(study, s)]


def board_problems(study, board, kit_versions: Dict[str, str]) -> List[str]:
    """The board must not hold rows measured differently from this launch:
    a row carrying another measure_sha is refused at `score`, after every
    step has run. One problem when it does, or when the board's header is
    not the study's; none for an empty or missing board."""
    try:
        found = board.measure_shas()
    except SchemaMismatch as exc:
        return [str(exc)]
    this = study.measure_sha(kit_versions)
    if not found or found == {this}:
        return []
    return [f"{board.path} holds rows measured as "
            f"{sorted(sha[:12] for sha in found)}, but this launch measures "
            f"as {this[:12]} (the study's measurement or a kit's version "
            f"changed); set a new leaderboard.file to start a new board"]


def board_versions(study, current: Dict[str, str],
                   adopted: Optional[Dict[str, Dict[str, Any]]] = None
                   ) -> Tuple[Dict[str, str], List[str]]:
    """The kit versions `score` will use for this point, and the problems
    that make it unable to complete as measured. `current` is each kit's
    running version; `adopted` is {step: record} for steps already finished
    (resume), each record carrying "kit" and "kit_version". A kit whose
    steps were all adopted keeps the recorded version (score.kit_versions
    decides disagreement); one adopted in part at a version other than
    the current one would be measured on two builds, which score refuses
    after running the rest; any other kit measures at its current version."""
    # score imports the scheduler, which imports this module: import late.
    if __package__:
        from core import score
    else:
        import score
    versions = dict(current)
    mine = {s.step: adopted[s.step] for s in study.steps
            if adopted and s.step in adopted}
    if not mine:
        return versions, []
    try:
        recorded = score.kit_versions(mine)
    except score.ScoreError as exc:
        return versions, [f"adopted steps of {sorted(mine)}: {exc}"]
    problems = []
    for kit, version in sorted(recorded.items()):
        steps = [s.step for s in study.steps if s.kit == kit]
        if all(step in mine for step in steps):
            versions[kit] = version
        elif version != current[kit]:
            todo = [step for step in steps if step not in mine]
            done = [step for step in steps if step in mine]
            problems.append(
                f"kit {kit!r}: step(s) {done} finished under version "
                f"{version!r} but the kit is now {current[kit]!r} with "
                f"{todo} still to run, so this point cannot complete as "
                f"measured (score refuses a kit measured on two builds); "
                f"use a new config name")
    return versions, problems


def launch_problems(study, kits, *, executor: str, parallel,
                    config_names, kerberos=None, board=None,
                    adopted=None) -> List[str]:
    """The launch check both runners make. Static rules first, opening no
    kit: the executor rules (a problem here returns at once), a Kerberos
    ticket with GRID_TICKET_SECONDS left when a kit of the study asks for
    one (`kerberos` is a callable returning a problem or None; it defaults
    to check_kerberos), and each config name against the rule of every kit
    that names its runs after the config. If any of those found a problem,
    return them. Then every kit the study names, from `kits`, must start,
    offer the contract's step tools when it runs a step (and `check` when
    it runs the preflight), and report a server version, which measure_sha
    needs. When a kit offers `describe`, the study's params must be ones it
    accepts and its metrics ones it returns. Returns the problems; an empty
    list means launch. With `board`, and no problem found so far, the board's
    rows must carry the measure_sha this launch would write (board_problems),
    computed from the versions `score` will use: `adopted` ({step: record},
    a resumed point's finished steps; None for a fresh one) keeps the
    versions its steps ran under (board_versions).
    `kits` stays open: the caller closes it."""
    problems = executor_problems(study, executor, parallel)
    if problems:
        return problems
    if requires_kerberos(study, executor):
        err = (kerberos or (lambda: check_kerberos(GRID_TICKET_SECONDS)))()
        if err:
            problems.append(err)
    kit_names = sorted(kit_registry.kits_of(study))
    for config in config_names:
        for name in kit_names:
            if not kit_registry.KITS[name].names_runs_after_config:
                continue
            why = kit_registry.config_name_problem(config)
            if why:
                problems.append(f"kit {name!r}: {why}")
    if problems:
        return problems
    for name in kit_names:
        try:
            kit = kits.get(name)
            kit.start()
            # A kit that runs a step needs the step calls; a kit used only
            # for the preflight needs only `check`.
            need = (set(REQUIRED_TOOLS)
                    if any(s.kit == name for s in study.steps) else set())
            if study.preflight is not None and study.preflight["kit"] == name:
                need.add("check")
            missing = sorted(need - set(kit.tools))
            if missing:
                problems.append(f"kit {name!r} lacks contract tool(s) "
                                f"{missing}")
            if not kit.version:
                problems.append(f"kit {name!r} reports no server version, so "
                                f"measure_sha could not tell its builds apart")
            described = kit.describe()
            if described is not None:
                params, metrics, profile_params = _needs(study, name)
                if described.accepts_lists != kit.accepts_lists:
                    problems.append(
                        f"kit {name!r}: describe says accepts_lists="
                        f"{described.accepts_lists}, its registry entry says "
                        f"{kit.accepts_lists}")
                sent = {f"{p}_0" if p in profile_params and not kit.accepts_lists
                        else p for p in params}
                unknown = sorted(sent - set(described.params))
                if unknown:
                    problems.append(f"kit {name!r} does not accept param(s) "
                                    f"{unknown} (it accepts "
                                    f"{list(described.params)})")
                absent = sorted(metrics - set(described.metrics))
                if absent:
                    problems.append(f"kit {name!r} does not return metric(s) "
                                    f"{absent} (it returns "
                                    f"{list(described.metrics)})")
            problems.extend(kit_step_problems(kit, study, name))
        except (KitError, ContractError) as exc:
            problems.append(str(exc))
    if board is not None and not problems:
        versions, problems = board_versions(study, {
            name: kits.get(name).version
            for name in {s.kit for s in study.steps}}, adopted)
        if not problems:
            problems = board_problems(study, board, versions)
    return problems
