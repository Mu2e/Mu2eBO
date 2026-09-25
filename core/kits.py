"""KitClient: a synchronous handle on one kit's MCP server over stdio
(generic-study design, "Rules for every kit call"; kit-seam spec §1).

A nested asyncio.run is impossible under a caller's own loop, so the session
lives on a private loop in a daemon thread, and its whole lifetime runs in
ONE task there (anyio cancel scopes must be exited by the task that entered
them). Lifted from beamkit's src/beamkit/mcpclient.py, plus: named timeouts,
the workflow meta tag, the trace log, and the kits.toml environment.

The client never retries a call. A timeout keeps the session (the server
may still be working); any other transport failure closes it, and the next
call respawns the server. Retries belong to core/contract.py's NativeKit,
which knows which calls are safe to repeat.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

if __package__:
    from core.kit_config import KitConfig, KitConfigError
else:
    from kit_config import KitConfig, KitConfigError

WORKFLOW_META_KEY = "gov.fnal.mu2e/workflow"
STDERR_TAIL = 20
_GRACE_S = 5.0          # future.result() margin over the MCP read timeout
_TRACE_LOCK = threading.Lock()


class KitError(RuntimeError):
    """A kit call failed: start, transport, timeout or tool error."""

    def __init__(self, kit: str, tool: str, message: str):
        super().__init__(f"kit {kit!r} {tool}: {message}")
        self.kit, self.tool, self.message = kit, tool, message


class KitToolError(KitError):
    """The server answered is_error; `message` is the server's own text."""


class KitTimeout(KitError):
    """The call timed out. The session is kept: the server may still be
    working on it."""


def _strip_prefix(text: str, tool: str) -> str:
    prefix = f"Error executing tool {tool}: "
    return text[len(prefix):] if text.startswith(prefix) else text


class KitClient:
    def __init__(self, config: KitConfig, *, campaign: str, trace_dir: Path):
        self.config = config
        self.campaign = campaign
        self.trace_path = Path(trace_dir) / "kit_trace.jsonl"
        self.server_name = None
        self.server_version = None
        self.tools = frozenset()
        self._stderr_tail = deque(maxlen=STDERR_TAIL)
        self._pump = None
        self._lock = threading.RLock()
        self._loop = self._thread = None
        self._serve_fut = self._task = self._stop = None
        self._session = None
        self._generation = 0    # bumped on each successful start; see _lost
        atexit.register(self.close)

    @property
    def started(self) -> bool:
        return self._session is not None

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        name = self.config.name
        with self._lock:
            if self._session is not None:
                return
            if self._loop is not None:
                # The serve task ended on its own between calls (the
                # server died with nobody waiting on it): _session is
                # already cleared, but its loop and thread are not.
                # Tear them down before building a fresh one, or the old
                # `kit-<name>` thread spins forever.
                self._teardown()
            try:
                from mcp.client.stdio import get_default_environment
                command = self.config.resolve_command()
                env = self.config.resolve_env(get_default_environment())
            except KitConfigError as exc:
                raise KitError(name, "start", str(exc)) from None
            self._stderr_tail.clear()
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever,
                                            name=f"kit-{name}", daemon=True)
            self._thread.start()
            ready = concurrent.futures.Future()
            self._serve_fut = asyncio.run_coroutine_threadsafe(
                self._serve(ready, command, env), self._loop)
            timeout = self.config.timeouts["start"]
            try:
                ready.result(timeout)
            except concurrent.futures.TimeoutError:
                self._teardown()
                raise KitError(name, "start", f"server did not start within "
                               f"{timeout:g} s ({command})") from None
            except Exception as exc:  # noqa: BLE001 - reported with stderr
                self._teardown()
                if self._pump is not None:
                    self._pump.join(2)
                tail = " | ".join(self._stderr_tail)
                raise KitError(name, "start", f"server did not start "
                               f"({command}): {type(exc).__name__}: {exc}; "
                               f"child stderr: {tail}") from exc

    async def _serve(self, ready, command, env):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._task = asyncio.current_task()
        self._stop = asyncio.Event()
        params = StdioServerParameters(command=command[0], args=command[1:],
                                       env=env)
        errlog = self._stderr_tee()
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                errlog.close()      # the child holds its own copy
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.server_name = init.server_info.name
                    self.server_version = init.server_info.version
                    listing = await session.list_tools()
                    self.tools = frozenset(t.name for t in listing.tools)
                    self._session = session
                    self._generation += 1
                    ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - via ready, or on stop
            if not ready.done():
                ready.set_exception(exc)
            elif not isinstance(exc, asyncio.CancelledError):
                # Started, then ended on its own with nobody waiting (no
                # `ready` to report to): the cause must not be swallowed.
                sys.stderr.write(f"kit {self.config.name}: server ended "
                                 f"unexpectedly between calls: "
                                 f"{type(exc).__name__}: {exc}\n")
                sys.stderr.flush()
        finally:
            if not errlog.closed:
                errlog.close()
            self._session = None
            self.tools = frozenset()

    def _stderr_tee(self):
        """A pipe the child writes to; a pump thread keeps the last lines
        and forwards everything to our stderr."""
        r, w = os.pipe()

        def pump():
            with os.fdopen(r, "rb", buffering=0) as fh:
                for raw in iter(fh.readline, b""):
                    line = raw.decode("utf-8", "replace")
                    self._stderr_tail.append(line.rstrip("\n"))
                    sys.stderr.write(line)
                    sys.stderr.flush()
        self._pump = threading.Thread(target=pump, daemon=True,
                                      name=f"kit-{self.config.name}-stderr")
        self._pump.start()
        return os.fdopen(w, "w")

    def close(self) -> None:
        with self._lock:
            if self._loop is None:
                return
            if (self._stop is not None and self._serve_fut is not None
                    and not self._serve_fut.done()):
                self._loop.call_soon_threadsafe(self._stop.set)
                try:
                    self._serve_fut.result(10)
                except Exception:  # noqa: BLE001 - shutting down regardless
                    pass
            self._teardown()

    def _teardown(self) -> None:
        loop, thread, task = self._loop, self._thread, self._task
        self._session = None
        self.tools = frozenset()
        if task is not None and not task.done():
            # Cancel and await the REAL task on its own loop, so
            # stdio_client's shutdown (close stdin, wait, SIGTERM/SIGKILL)
            # runs before the loop stops and the child cannot survive.
            async def _cancel_and_wait():
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001 - tearing down
                    pass
            try:
                asyncio.run_coroutine_threadsafe(_cancel_and_wait(),
                                                 loop).result(5)
            except Exception:  # noqa: BLE001 - best effort
                sys.stderr.write(f"kit {self.config.name}: serve task did "
                                 f"not finish within 5 s; its server may "
                                 f"still be running\n")
        self._serve_fut = self._stop = self._task = None
        self._loop = self._thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(5)
            if not loop.is_running():
                loop.close()

    # --- calls -------------------------------------------------------------
    def call(self, tool: str, args: dict, *, timeout_s: float,
             workflow: str) -> dict:
        t0 = time.monotonic()
        error = None
        try:
            return self._call(tool, args, timeout_s, workflow)
        except BaseException as exc:
            error = getattr(exc, "message", None) or repr(exc)
            raise
        finally:
            self._trace(tool, args, workflow, time.monotonic() - t0, error)

    def _call(self, tool, args, timeout_s, workflow) -> dict:
        from mcp.shared.exceptions import MCPError
        from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT
        name = self.config.name
        with self._lock:
            if self._session is None:
                self.start()
            if tool not in self.tools:
                raise KitError(name, tool, f"server has no tool {tool!r}; it "
                               f"has {sorted(self.tools)}")
            # Captured under the lock, at the moment THIS call is scheduled:
            # a stale generation tells _lost that a concurrent call already
            # respawned the server, so it must not tear down the new one.
            generation = self._generation
            coro = self._session.call_tool(
                tool, args, read_timeout_seconds=timeout_s,
                meta={WORKFLOW_META_KEY: workflow})
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        # The MCP session multiplexes requests over the one connection, so
        # the wait itself must happen OUTSIDE the lock: otherwise a slow
        # call from one thread would hold every other thread's `timeout_s`
        # hostage on a client several kits.toml callers share.
        try:
            res = fut.result(timeout_s + _GRACE_S)
        except MCPError as exc:
            if exc.code == REQUEST_TIMEOUT:
                raise KitTimeout(name, tool, f"timed out after "
                                 f"{timeout_s:g} s") from exc
            if exc.code == CONNECTION_CLOSED:
                self._lost(tool, exc, generation)
            # Any other JSON-RPC error (bad params, tool-side crash the
            # server itself reported at the protocol level, ...) is the
            # server answering, not losing it: keep the session.
            raise KitError(name, tool,
                           f"error {exc.code}: {exc.message}") from exc
        except Exception as exc:  # noqa: BLE001 - transport state unknown
            fut.cancel()
            self._lost(tool, exc, generation)
        text = "".join(c.text for c in res.content
                       if getattr(c, "type", None) == "text")
        if res.is_error:
            raise KitToolError(name, tool, _strip_prefix(text, tool))
        if res.structured_content is None:
            raise KitError(name, tool, f"reply has no structured content: "
                           f"{text[:200]!r}")
        return res.structured_content

    def _lost(self, tool, exc, generation):
        """The session is gone or in an unknown state. Close it so the next
        call respawns the server -- UNLESS a concurrent call already did:
        if `generation` is stale (some other call has since started a new
        session), this call's own failure must never tear that new one
        down."""
        with self._lock:
            stale = generation != self._generation
            if not stale:
                self.close()
        if stale:
            raise KitError(self.config.name, tool, f"server lost: "
                           f"{type(exc).__name__}: {exc} (a concurrent call "
                           f"already respawned the server)") from exc
        if self._pump is not None:
            self._pump.join(2)
        tail = " | ".join(self._stderr_tail)
        raise KitError(self.config.name, tool, f"server lost: "
                       f"{type(exc).__name__}: {exc}; child stderr: "
                       f"{tail}") from exc

    def _trace(self, tool, args, workflow, duration, error) -> None:
        line = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "workflow": workflow, "kit": self.config.name, "tool": tool,
            "args_sha256": hashlib.sha256(json.dumps(
                args, sort_keys=True, default=str).encode()).hexdigest(),
            "duration_s": round(duration, 3), "ok": error is None,
            "error": error,
            "server": {"name": self.server_name,
                       "version": self.server_version},
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_LOCK, open(self.trace_path, "a") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
