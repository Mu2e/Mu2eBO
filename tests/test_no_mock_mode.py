"""Mock mode is retired. These pin its absence at every surface it had.

It was a graph node, a routing branch, a required CLI flag, a state field and
a pipeline_io function. Dropping any one of those and leaving the rest is the
failure this guards -- a --mock flag that routes nowhere, or a mock_grid node
with no edge into it, both fail at runtime rather than import.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))

# core/runtime.py (graph/config.py before 2026-08-19) resolves its mode spec
# at IMPORT time, so a bare `import build` needs a live mode in the env.
# tests/__init__.py stamps the suite's mode once for the whole process; this
# setdefault is only reached by `discover -s tests` without `-t .`, which
# never imports the package __init__, and must agree with it.
os.environ.setdefault("AUTORESEARCH_MODE", "foilspf")


class TestMockModeRetired(unittest.TestCase):
    def test_nodes_has_no_mock_grid(self):
        import nodes
        self.assertFalse(hasattr(nodes, "node_mock_grid"))

    def test_pipeline_io_has_no_mock_metrics(self):
        import pipeline_io
        self.assertFalse(hasattr(pipeline_io, "mock_metrics"))

    def test_state_has_no_mock_field(self):
        import state
        self.assertNotIn("mock", state.BOIterationState.__annotations__)

    def test_graph_has_no_mock_grid_node(self):
        import build
        compiled = build.build_graph().compile()
        self.assertNotIn("mock_grid", compiled.get_graph().nodes)

    def test_run_py_has_no_mock_flag(self):
        self.assertNotIn("--mock", (ROOT / "graph" / "run.py").read_text())

    def test_closed_loop_does_not_pass_no_mock(self):
        self.assertNotIn("--no-mock",
                         (ROOT / "graph" / "closed_loop.py").read_text())

    def test_route_after_preflight_returns_real_on_pass(self):
        import nodes
        self.assertEqual(
            nodes.route_after_preflight({"preflight": "pass", "attempts": {}}),
            "real")

    def test_node_propose_does_not_write_mock(self):
        import nodes
        result = nodes.node_propose({"mode": "foilspf", "config_name": "test", "alpha": 0.1})
        self.assertNotIn("mock", result,
                         "node_propose returned a 'mock' key; the state field was deleted but "
                         "the write-site at nodes.py:112 survives")

    def test_tools_run_local_sh_does_not_pass_no_mock(self):
        self.assertNotIn("--no-mock",
                         (ROOT / "tools" / "run_local.sh").read_text())


if __name__ == "__main__":
    unittest.main()
