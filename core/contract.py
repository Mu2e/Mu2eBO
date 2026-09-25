"""The evaluator contract (generic-study design, "The evaluator contract"):
reply validation, the Kit interface the engine drives, NativeKit (a kit
that speaks the contract over MCP), the adapter registry, KitSet (the kits
one child uses) and check_kits (the launch check).

A reply outside the contract raises ContractError: a failed evaluation,
never success. Replies must carry the keys the contract names, with the
right types; keys it doesn't name are ignored, so a kit can add fields.

The Kit interface, which NativeKit and every adapter implement:
  name, version, tools, accepts_lists, poll_s
  submit(name, params, files, inputs, workflow) -> handle
  status(handle, workflow) -> Status
  results(handle, workflow) -> Results
  check(name, params, files, inputs, workflow) -> (ok, message)
  describe() -> Describe | None
  cancel(handle, workflow) -> state
  close()
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

if __package__:
    from core import kit_registry, paths
    from core.kits import KitClient, KitError, KitToolError
else:
    import kit_registry
    import paths
    from kits import KitClient, KitError, KitToolError

STATES = ("working", "completed", "failed", "cancelled")
REQUIRED_TOOLS = ("submit", "status", "results")
ATTEMPTS = 3            # bounded retries of the calls safe to repeat
_URI_SCHEMES = ("file://", "root://")


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


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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

    def __init__(self, config, client):
        self.name = config.name
        self.config = config
        self.client = client
        self.accepts_lists = config.accepts_lists
        self.poll_s = config.poll_s

    def _ensure_started(self) -> None:
        if not self.client.started:
            self.client.start()

    @property
    def version(self) -> str:
        self._ensure_started()
        return self.client.server_version or ""

    @property
    def tools(self) -> frozenset:
        self._ensure_started()
        return self.client.tools

    def _call(self, tool, args, workflow, *, retry_tool_errors,
              attempts=ATTEMPTS):
        """Transport failures and timeouts are retried (the client respawns
        a lost server before the next call). A tool error is retried only
        for read-only calls: a refused submit (same name, different params)
        must never be repeated."""
        for attempt in range(1, attempts + 1):
            try:
                return self.client.call(tool, args,
                                        timeout_s=self.config.timeouts[tool],
                                        workflow=workflow)
            except KitToolError:
                if not retry_tool_errors or attempt == attempts:
                    raise
            except KitError:
                if attempt == attempts:
                    raise

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
                                       retry_tool_errors=False, attempts=1),
                            self.name)

    def close(self) -> None:
        self.client.close()


# Kits implemented in Python: Phase C registers prodtools and the three
# plugins. A factory is a class taking the campaign name, with a
# LAUNCH_STAGGER_S attribute; its kit needs a kit_registry declaration with
# engine=True and no kits.toml entry.
ADAPTERS: Dict[str, Callable[[str], Any]] = {}


def register_adapter(name: str, factory) -> None:
    if name in ADAPTERS:
        raise ValueError(f"adapter {name!r} is registered twice")
    decl = kit_registry.KITS.get(name)
    if decl is None or not decl.engine or name in kit_registry.NATIVE:
        raise ValueError(f"adapter {name!r} needs a kit_registry declaration "
                         f"with engine=True and no kits.toml entry")
    ADAPTERS[name] = factory


def open_kit(name: str, campaign: str):
    if name in ADAPTERS:
        return ADAPTERS[name](campaign)
    cfg = kit_registry.NATIVE.get(name)
    if cfg is None:
        raise KeyError(f"kit {name!r} has no adapter and no kits.toml entry, "
                       f"so the contract engine cannot run it (the pipeline "
                       f"kits run through graph.run until Phase C)")
    return NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                    trace_dir=paths.GRAPH_DATA / campaign))


def launch_stagger(study) -> float:
    """Seconds between a campaign's child launches: the largest any of the
    study's kits asks for."""
    gap = 0.0
    for name in kit_registry.kits_of(study):
        if name in ADAPTERS:
            gap = max(gap, float(ADAPTERS[name].LAUNCH_STAGGER_S))
        else:
            gap = max(gap, kit_registry.NATIVE[name].launch_stagger_s)
    return gap


class KitSet:
    """The kits one child uses: opened on first use (one server per kit),
    closed together. Thread-safe: run_steps' threads share it."""

    def __init__(self, campaign: str, opener=open_kit):
        self.campaign = campaign
        self._opener = opener
        self._kits: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, name: str):
        with self._lock:
            if name not in self._kits:
                self._kits[name] = self._opener(name, self.campaign)
            return self._kits[name]

    def close(self) -> None:
        with self._lock:
            kits, self._kits = list(self._kits.values()), {}
        for kit in kits:
            kit.close()


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


def check_kits(study, *, campaign: str, opener=open_kit) -> List[str]:
    """The launch check. Every kit the study names must start, offer the
    contract's tools (and `check` when it runs the preflight), and report a
    server version, which measure_sha needs. When a kit offers `describe`,
    the study's params must be ones it accepts and its metrics ones it
    returns. Returns the problems; an empty list means launch."""
    problems = []
    for name in sorted(kit_registry.kits_of(study)):
        try:
            kit = opener(name, campaign)
        except (KeyError, KitError) as exc:
            problems.append(str(exc).strip("\"'"))
            continue
        try:
            need = set(REQUIRED_TOOLS)
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
        except (KitError, ContractError) as exc:
            problems.append(str(exc))
        finally:
            kit.close()
    return problems
