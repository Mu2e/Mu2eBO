import json
import os
import sys
import tempfile
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
