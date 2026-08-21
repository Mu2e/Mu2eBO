"""Every graph .stream() in the repo must run under an explicit recursion_limit.

langgraph 1.2.9 has no practical cap, but 0.2.50 -- the version in the
ana_v2.8.0 pyenv candidate -- defaults to 25. A chain that quietly exceeds it
there dies with GraphRecursionError mid-eval. Pin it rather than depend on a
library default that moved.

REWRITTEN (final review, finding M1). The previous version named two files:
graph/run.py, and graph/closed_loop.py with `require_call=False`. When the
parent graph was deleted (Task 3 removed the last .stream() from
closed_loop.py) that second test became VACUOUS -- `calls == []` hit an early
`return` and it could never fail again, while its docstring still described
"the parent graph burns 6 supersteps per round". Scanning the tree instead
means the invariant survives a file being added, deleted, or renamed: any NEW
streaming call site is covered the day it lands.

These assert on the FILE, not on the text inside the call parens. An earlier
version regexed the call site, which made passing a shared `cfg` by name fail
and silently forced a second inline dict literal at every stream() -- the
opposite of what you want.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("graph", "core", "tools")
SKIP_PARTS = {".venv", "__pycache__", "leaderboards", "goldens", "fixtures"}

_STREAM_CALL = re.compile(r"\.stream\((.*?)\)\s*:", re.S)


def _sources():
    for d in SEARCH_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if SKIP_PARTS & set(p.parts):
                continue
            yield p


class TestRecursionLimitPinned(unittest.TestCase):
    def test_at_least_one_stream_call_exists(self):
        """Guards the guard: if nothing streams any more, this whole file is
        dead weight and should be deleted, not left silently passing."""
        streaming = [p for p in _sources()
                     if _STREAM_CALL.search(p.read_text())]
        self.assertTrue(
            streaming,
            "no .stream() call left under " + "/, ".join(SEARCH_DIRS) +
            "/ -- delete tests/test_recursion_limit.py rather than keep a "
            "test that cannot fail")

    def test_every_stream_call_site_pins_recursion_limit(self):
        for path in _sources():
            text = path.read_text()
            calls = _STREAM_CALL.findall(text)
            if not calls:
                continue
            rel = path.relative_to(ROOT)
            with self.subTest(file=str(rel)):
                self.assertIn(
                    "recursion_limit", text,
                    f"{rel} streams a graph but never pins recursion_limit")
                for c in calls:
                    self.assertFalse(
                        c.strip().startswith("{"),
                        f"{rel}: pass the shared config by name, do not "
                        f"inline a second dict literal at the .stream() call")


if __name__ == "__main__":
    unittest.main()
