#!/usr/bin/env python3
"""toykit: the reference contract kit and the CI engine (generic-study
design, "toykit"). A native MCP kit with the contract tools submit, status,
results, check, describe and cancel, plus debug_* tools the kit-client
tests use.

Jobs live on disk under $TOYKIT_STATE_DIR (kits.toml sets it under
DATA_ROOT), so a restarted child talking to a fresh server process finds
the job it submitted before it was killed. A job completes delay_s seconds
after its submit; `fail` picks a failure (failed | cancelled | bad_state |
missing_metric | nonpositive). Functions: branin_currin (Branin and
Currin on x1 in [-5, 10], x2 in [0, 15]) and reject (the check fails).
Run as a script it serves stdio; imported, it exposes ToyStore.

No `from __future__ import annotations` here: the MCP SDK evaluates tool
annotations against module globals, and Context is imported inside
make_server.
"""
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "1"
FUNCTIONS = ("branin_currin", "reject")
FAILS = ("failed", "cancelled", "bad_state", "missing_metric", "nonpositive")
PARAMS = ("x1", "x2", "function", "delay_s", "fail", "submit_sleep_s")
METRICS = ("branin", "currin", "n_inputs")
POLL_MS = 100


def branin(x1: float, x2: float) -> float:
    b, c, t = 5.1 / (4 * math.pi ** 2), 5 / math.pi, 1 / (8 * math.pi)
    return (x2 - b * x1 ** 2 + c * x1 - 6) ** 2 + 10 * (1 - t) * math.cos(x1) + 10


def currin(x1: float, x2: float) -> float:
    """Currin's function on the unit square, mapped from the Branin box."""
    u1, u2 = (x1 + 5) / 15, x2 / 15
    factor = 1.0 if u2 == 0 else 1 - math.exp(-1 / (2 * u2))
    num = 2300 * u1 ** 3 + 1900 * u1 ** 2 + 2092 * u1 + 60
    den = 100 * u1 ** 3 + 500 * u1 ** 2 + 4 * u1 + 20
    return factor * num / den


class ToyStore:
    """The kit's jobs, one JSON file each. submits.jsonl logs every NEW job,
    which is where the tests count double submits."""

    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        (self.root / "out").mkdir(parents=True, exist_ok=True)

    def _path(self, handle: str) -> Path:
        return self.root / "jobs" / f"{handle}.json"

    def _load(self, handle: str) -> dict:
        path = self._path(handle)
        if not path.exists():
            raise ValueError(f"toykit: no job {handle!r}")
        return json.loads(path.read_text())

    def _save(self, job: dict) -> None:
        path = self._path(job["name"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job))
        tmp.replace(path)

    def submit(self, name, params, files, inputs):
        """(reply, created). Idempotent by name: the same name with the same
        params, files and inputs returns the existing handle; different ones
        are refused."""
        if params.get("function") not in FUNCTIONS:
            raise ValueError(f"toykit: unknown function "
                             f"{params.get('function')!r}; choose from "
                             f"{list(FUNCTIONS)}")
        fail = params.get("fail")
        if fail is not None and fail not in FAILS:
            raise ValueError(f"toykit: unknown fail {fail!r}; choose from "
                             f"{list(FAILS)}")
        job = {"name": name, "params": params, "files": files, "inputs": inputs}
        if self._path(name).exists():
            old = self._load(name)
            if {k: old[k] for k in job} != job:
                raise ValueError(f"toykit: {name!r} was already submitted "
                                 f"with different params, files or inputs")
            return {"handle": name}, False
        job.update(submitted_at=self.clock(), cancelled=False)
        self._save(job)
        with open(self.root / "submits.jsonl", "a") as f:
            f.write(json.dumps({"name": name}) + "\n")
        return {"handle": name}, True

    @staticmethod
    def _state(state: str, message: str) -> dict:
        return {"state": state, "message": message, "poll_ms": POLL_MS,
                "progress": None}

    def status(self, handle: str) -> dict:
        job = self._load(handle)
        params, fail = job["params"], job["params"].get("fail")
        if job["cancelled"] or fail == "cancelled":
            return self._state("cancelled", "toykit: cancelled")
        if fail == "failed":
            return self._state("failed", "toykit: asked to fail")
        if fail == "bad_state":
            return self._state("bogus", "toykit: a state outside the contract")
        elapsed = self.clock() - job["submitted_at"]
        done = elapsed >= float(params.get("delay_s", 0.0))
        return self._state("completed" if done else "working", "")

    def results(self, handle: str) -> dict:
        state = self.status(handle)["state"]
        if state != "completed":
            raise ValueError(f"toykit: {handle!r} is {state}, not completed")
        job = self._load(handle)
        params = job["params"]
        x1, x2 = float(params["x1"]), float(params["x2"])
        metrics = {"branin": branin(x1, x2), "currin": currin(x1, x2),
                   "n_inputs": float(len(job["inputs"]))}
        if params.get("fail") == "missing_metric":
            del metrics["currin"]
        if params.get("fail") == "nonpositive":
            metrics["currin"] = 0.0
        out = self.root / "out" / f"{handle}.txt"
        out.write_text(json.dumps(metrics))
        return {"metrics": metrics,
                "files": [{"name": "out", "uri": out.resolve().as_uri(),
                           "kind": "text"}],
                "metadata": {"function": params["function"]}}

    def cancel(self, handle: str) -> dict:
        job = self._load(handle)
        job["cancelled"] = True
        self._save(job)
        return {"state": "cancelled"}

    @staticmethod
    def check(name, params, files, inputs) -> dict:
        if params.get("function") == "reject":
            return {"ok": False,
                    "message": "toykit: function 'reject' fails the check"}
        return {"ok": True, "message": ""}

    @staticmethod
    def describe() -> dict:
        return {"params": list(PARAMS), "metrics": list(METRICS),
                "accepts_lists": False}


def make_server(store: ToyStore):
    from mcp.server.mcpserver import Context, MCPServer

    server = MCPServer(name="toykit", version=VERSION)

    @server.tool(structured_output=True)
    async def submit(name: str, params: dict[str, Any],
                     files: list[dict[str, Any]],
                     inputs: list[dict[str, Any]]) -> dict[str, Any]:
        reply, created = store.submit(name, params, files, inputs)
        sleep = float(params.get("submit_sleep_s", 0.0))
        if created and sleep:
            # Recorded BEFORE the sleep: a client that times out and
            # re-submits finds the job and gets the handle at once.
            await asyncio.sleep(sleep)
        return reply

    @server.tool(structured_output=True)
    def status(handle: str) -> dict[str, Any]:
        return store.status(handle)

    @server.tool(structured_output=True)
    def results(handle: str) -> dict[str, Any]:
        return store.results(handle)

    @server.tool(structured_output=True)
    def check(name: str, params: dict[str, Any], files: list[dict[str, Any]],
              inputs: list[dict[str, Any]]) -> dict[str, Any]:
        return store.check(name, params, files, inputs)

    @server.tool(structured_output=True)
    def describe() -> dict[str, Any]:
        return store.describe()

    @server.tool(structured_output=True)
    def cancel(handle: str) -> dict[str, Any]:
        return store.cancel(handle)

    @server.tool(structured_output=True)
    def debug_env(names: list[str]) -> dict[str, Any]:
        return {n: os.environ.get(n) for n in names}

    @server.tool(structured_output=True)
    def debug_meta(ctx: Context) -> dict[str, Any]:
        return {"meta": dict(ctx.request_context.meta or {})}

    @server.tool(structured_output=True)
    async def debug_sleep(seconds: float) -> dict[str, Any]:
        await asyncio.sleep(seconds)
        return {"slept": seconds}

    @server.tool(structured_output=True)
    def debug_exit() -> dict[str, Any]:
        os._exit(3)

    return server


def main() -> int:
    root = os.environ.get("TOYKIT_STATE_DIR")
    if not root:
        sys.stderr.write("toykit: TOYKIT_STATE_DIR is not set "
                         "(kits.toml sets it)\n")
        return 2
    make_server(ToyStore(Path(root))).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
