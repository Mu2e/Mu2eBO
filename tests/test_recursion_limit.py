"""Both graph.stream() calls must run under an explicit recursion_limit.

langgraph 1.2.9 has no practical cap, but 0.2.50 -- the version in the
ana_v2.8.0 pyenv candidate -- defaults to 25. The parent graph burns 6
supersteps per round, so --max-rounds 5 would die at round ~4 with
GraphRecursionError under that version, and no test exercises five parent
rounds. Pin it rather than depend on a library default that moved.

These assert on the FILE, not on the text inside the call parens. An earlier
version regexed the call site, which made passing a shared `cfg` by name fail
and silently forced a second inline dict literal at every stream() -- the
opposite of what you want.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestRecursionLimitPinned(unittest.TestCase):
    def _stream_args(self, rel):
        text = (ROOT / rel).read_text()
        return text, re.findall(r"\.stream\((.*?)\)\s*:", text, re.S)

    def _assert_pinned(self, rel, require_call):
        text, calls = self._stream_args(rel)
        if require_call:
            self.assertTrue(calls, f"no .stream() call found in {rel}")
        if not calls:
            return
        self.assertIn(
            "recursion_limit", text,
            f"{rel} streams a graph but never pins recursion_limit")
        for c in calls:
            self.assertFalse(
                c.strip().startswith("{"),
                f"{rel}: pass the shared config by name, do not inline a "
                f"second dict literal at the .stream() call")

    def test_run_py_stream_pins_recursion_limit(self):
        self._assert_pinned("graph/run.py", require_call=True)

    def test_closed_loop_stream_pins_recursion_limit(self):
        # Deliberately does NOT require a .stream() to exist: a later task
        # deletes the parent graph outright. The invariant is "no UNBOUNDED
        # stream anywhere", which holds before and after that.
        self._assert_pinned("graph/closed_loop.py", require_call=False)


if __name__ == "__main__":
    unittest.main()
