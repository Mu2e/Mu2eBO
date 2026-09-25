import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
from kits import (KitClient, KitError, KitTimeout, KitToolError,  # noqa: E402
                  WORKFLOW_META_KEY)
from tests.engine_fixtures import toy_config  # noqa: E402

WF = "camp/cfg/step"


class _Client(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def client(self, **overrides):
        c = KitClient(toy_config(self.tmp / "toy", **overrides),
                      campaign="camp", trace_dir=self.tmp / "trace")
        self.addCleanup(c.close)
        return c

    @staticmethod
    def call(client, tool, args=None, timeout_s=30):
        return client.call(tool, args or {}, timeout_s=timeout_s, workflow=WF)

    def trace(self):
        path = self.tmp / "trace" / "kit_trace.jsonl"
        return [json.loads(ln) for ln in path.read_text().splitlines()]


class TestCalls(_Client):
    def test_describe_round_trip(self):
        c = self.client()
        reply = self.call(c, "describe")
        self.assertIn("x1", reply["params"])
        self.assertEqual((c.server_name, c.server_version), ("toykit", "1"))
        self.assertIn("submit", c.tools)

    def test_tool_error_is_a_kit_tool_error_with_the_server_text(self):
        c = self.client()
        with self.assertRaises(KitToolError) as cm:
            self.call(c, "status", {"handle": "nope"})
        self.assertIn("no job 'nope'", cm.exception.message)
        self.assertNotIn("Error executing tool", cm.exception.message)
        self.assertEqual((cm.exception.kit, cm.exception.tool),
                         ("toykit", "status"))

    def test_unknown_tool(self):
        with self.assertRaises(KitError) as cm:
            self.call(self.client(), "frobnicate")
        self.assertIn("no tool 'frobnicate'", cm.exception.message)

    def test_meta_is_forwarded(self):
        reply = self.call(self.client(), "debug_meta")
        self.assertEqual(reply["meta"][WORKFLOW_META_KEY], WF)


class TestFailures(_Client):
    def test_timeout_keeps_the_session(self):
        c = self.client()
        self.call(c, "describe")
        with self.assertRaises(KitTimeout) as cm:
            self.call(c, "debug_sleep", {"seconds": 5}, timeout_s=0.5)
        self.assertIn("timed out", cm.exception.message)
        self.assertTrue(c.started)
        self.assertIn("x1", self.call(c, "describe")["params"])

    def test_server_death_respawns_on_the_next_call(self):
        c = self.client()
        with self.assertRaises(KitError) as cm:
            self.call(c, "debug_exit")
        self.assertNotIsInstance(cm.exception, KitTimeout)
        self.assertFalse(c.started)
        self.assertIn("x1", self.call(c, "describe")["params"])

    def test_start_failure_carries_the_child_stderr(self):
        c = self.client(set_env={})       # no TOYKIT_STATE_DIR
        with self.assertRaises(KitError) as cm:
            self.call(c, "describe")
        self.assertEqual(cm.exception.tool, "start")
        self.assertIn("TOYKIT_STATE_DIR is not set", cm.exception.message)

    def test_unset_passthrough_fails_at_start_naming_kit_and_variable(self):
        c = self.client(env_passthrough=("TOYKIT_NOT_SET_ANYWHERE",))
        with mock.patch.dict(os.environ):
            os.environ.pop("TOYKIT_NOT_SET_ANYWHERE", None)
            with self.assertRaises(KitError) as cm:
                self.call(c, "describe")
        self.assertEqual(cm.exception.tool, "start")
        self.assertIn("TOYKIT_NOT_SET_ANYWHERE", cm.exception.message)
        self.assertIn("'toykit'", cm.exception.message)


class TestConcurrency(_Client):
    def test_short_call_is_not_blocked_by_a_long_call_on_the_same_client(self):
        """Fix round 1, I1: the lock must be held only for start / the tool
        check / scheduling, not across the wait -- the MCP session
        multiplexes requests, so a slow call on one thread must not hold
        every other thread's `timeout_s` hostage on a client several
        callers share (Task 4's KitSet shares one KitClient per kit across
        Task 7's scheduler threads)."""
        c = self.client()
        self.call(c, "describe")  # start the server before threading in
        result = {}

        def slow():
            result["reply"] = self.call(c, "debug_sleep", {"seconds": 2.0},
                                        timeout_s=10)

        t = threading.Thread(target=slow)
        t.start()
        try:
            time.sleep(0.3)  # let the slow call actually reach the server
            t0 = time.monotonic()
            reply = self.call(c, "describe", timeout_s=1.0)
            elapsed = time.monotonic() - t0
        finally:
            t.join(10)
        self.assertLess(elapsed, 1.0,
                        f"describe took {elapsed:.2f}s behind a slow call "
                        f"on the same client -- the lock is held too long")
        self.assertIn("x1", reply["params"])
        self.assertEqual(result["reply"]["slept"], 2.0)


class TestServerDeathBetweenCalls(_Client):
    def test_death_with_no_call_in_flight_raises_then_respawns(self):
        """Fix round 1, review finding for M1/M4: the server dies with no
        KitClient.call() tracking it as in flight, unlike
        test_server_death_respawns_on_the_next_call (which kills it via a
        normal call() and so is indistinguishable from a mid-call death).

        There is no clean handle on the child's OS pid to kill from outside
        the client: stdio_client's subprocess is private to its own async
        context and is never surfaced on KitClient or ClientSession. So this
        fires debug_exit directly at the raw session -- the client's own
        internals -- bypassing KitClient.call() entirely, which is the
        least invasive way to make the server die while nothing is counted
        as "in flight" from the client's own bookkeeping, without changing
        toykit.
        """
        c = self.client()
        self.call(c, "describe")
        fut = asyncio.run_coroutine_threadsafe(
            c._session.call_tool("debug_exit", {}, read_timeout_seconds=10,
                                 meta={WORKFLOW_META_KEY: WF}),
            c._loop)
        self.addCleanup(fut.cancel)
        time.sleep(0.5)  # let the child actually exit
        # Empirically (mcp 2.0.0): neither stdio_client's stdout reader nor
        # the session's own reader raises on a mid-idle EOF, so the client
        # does not notice the death on its own -- only an actual call does.
        self.assertTrue(c.started)

        with self.assertRaises(KitError) as cm:
            self.call(c, "describe")
        self.assertNotIsInstance(cm.exception, KitTimeout)
        self.assertIn("toykit", str(cm.exception))
        self.assertFalse(c.started)
        self.assertIn("x1", self.call(c, "describe")["params"])


class TestLeakedLoop(_Client):
    def test_a_session_cleared_without_teardown_does_not_leak_the_loop(self):
        """Fix round 1, M1: reproduces the exact state _serve's `finally`
        would leave behind if the serve task ever ended on its own between
        calls -- `_session` cleared but the private loop, its thread and
        the (still healthy) server process all still alive. `start()` must
        tear the stale loop down before building a fresh one, or the old
        `kit-<name>` thread -- and the server it still owns -- leak
        forever. (Real toykit death does not spontaneously clear `_session`
        with the loop left running; see TestServerDeathBetweenCalls's
        docstring. This directly reproduces the state the fix guards.)
        """
        c = self.client()
        self.call(c, "describe")
        old_loop, old_thread = c._loop, c._thread
        self.assertTrue(old_thread.is_alive())
        c._session = None  # what _serve's finally leaves behind on its own
        reply = self.call(c, "describe")
        self.assertIn("x1", reply["params"])
        self.assertIsNot(c._loop, old_loop)
        old_thread.join(5)
        self.assertFalse(old_thread.is_alive(),
                         "the old loop/thread were not torn down: leaked")


# Fix round 1, M4: a JSON-RPC error other than a timeout must keep the
# session. No test exercises this against the real toykit server: every
# way tried to provoke a non-timeout, non-CONNECTION_CLOSED MCPError --
# missing required args, wrong-typed args, and calling a genuinely
# unregistered tool name via the raw session (bypassing KitClient's own
# "tool not in self.tools" guard) -- came back as an ordinary
# CallToolResult(is_error=True) from the mcp 2.0.0 MCPServer, not a
# protocol-level error; toykit's own tools cannot be made to raise one
# without changing toykit, which fix round 1 explicitly rules out. The
# code path (core/kits.py:_call, the `if exc.code == CONNECTION_CLOSED`
# branch) is implemented per the ruling but is untested against a real
# server; see task-3-report.md fix round 1 for the probes that established
# this.


class TestEnvironment(_Client):
    def test_child_env_is_allowlist_plus_passthrough_plus_set(self):
        c = self.client(env_passthrough=("TOYKIT_PROBE",))
        with mock.patch.dict(os.environ, {"TOYKIT_PROBE": "xyz",
                                          "TOYKIT_LEAK": "no"}):
            reply = self.call(c, "debug_env",
                              {"names": ["TOYKIT_PROBE", "TOYKIT_STATE_DIR",
                                         "TOYKIT_LEAK"]})
        self.assertEqual(reply, {"TOYKIT_PROBE": "xyz",
                                 "TOYKIT_STATE_DIR": str(self.tmp / "toy"),
                                 "TOYKIT_LEAK": None})


class TestTrace(_Client):
    def test_one_line_per_call(self):
        c = self.client()
        self.call(c, "describe")
        with self.assertRaises(KitToolError):
            self.call(c, "status", {"handle": "nope"})
        ok, bad = self.trace()
        self.assertEqual((ok["tool"], ok["ok"], ok["error"]),
                         ("describe", True, None))
        self.assertEqual((bad["tool"], bad["ok"]), ("status", False))
        self.assertIn("no job", bad["error"])
        for line in (ok, bad):
            self.assertEqual(line["workflow"], WF)
            self.assertEqual(line["kit"], "toykit")
            self.assertEqual(len(line["args_sha256"]), 64)
            self.assertEqual(line["server"], {"name": "toykit", "version": "1"})
            self.assertGreaterEqual(line["duration_s"], 0)


if __name__ == "__main__":
    unittest.main()
