"""Both graph.stream() calls must pass an explicit recursion_limit.

langgraph 1.2.9 has no practical cap, but 0.2.50 -- the version in the
ana_v2.8.0 pyenv candidate -- defaults to 25. The parent graph burns 6
supersteps per round, so --max-rounds 5 would die at round ~4 with
GraphRecursionError under that version, and no test exercises five parent
rounds. Pin it rather than depend on a library default that moved.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestRecursionLimitPinned(unittest.TestCase):
    def _stream_calls(self, rel):
        text = (ROOT / rel).read_text()
        return re.findall(r"\.stream\((.*?)\)\s*:", text, re.S)

    def test_run_py_stream_pins_recursion_limit(self):
        calls = self._stream_calls("graph/run.py")
        self.assertTrue(calls, "no .stream() call found in graph/run.py")
        for c in calls:
            self.assertIn("recursion_limit", c,
                          "graph/run.py .stream() must pin recursion_limit")

    def test_closed_loop_stream_pins_recursion_limit(self):
        # Deliberately does NOT require a .stream() to exist: Task 3 deletes
        # the parent graph outright. The invariant is "no UNBOUNDED stream
        # anywhere", which holds both before and after that. Asserting
        # existence would force Task 3 to delete a passing test, hiding
        # whether it also dropped the pin on run.py.
        for c in self._stream_calls("graph/closed_loop.py"):
            self.assertIn("recursion_limit", c,
                          "graph/closed_loop.py .stream() must pin recursion_limit")


if __name__ == "__main__":
    unittest.main()
