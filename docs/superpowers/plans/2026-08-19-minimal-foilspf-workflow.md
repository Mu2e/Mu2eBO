# Minimal foilspf Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove ~3,000 LOC of orchestration from the BO loop — the SqliteSaver checkpointer, the five-source barrier, mock mode, and the `STAGES` literal — without changing any physics, metric, or geometry path.

**Architecture:** LangGraph stays. The *child* keeps its `StateGraph` (the LLM-node door). The *parent* round-loop stops being a graph and becomes a bounded `ThreadPoolExecutor` work-pool whose barrier is `as_completed`; a child resolves when its subprocess exits, which is one truth source replacing five. Both graphs compile without a checkpointer.

**Tech Stack:** Python 3.11 (`.venv`), `unittest` (never pytest), LangGraph 1.2.9 (`StateGraph` + `START`/`END` only), `concurrent.futures`, prodtools for grid submission.

**Spec:** `docs/superpowers/specs/2026-08-19-minimal-foilspf-workflow-design.md`

## Global Constraints

- Test runner is `unittest`, NOT pytest. Full suite: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
- The suite must stay green with **zero grid contact** — no `mu2ejobsub`, no `jobsub_q`, no `/pnfs` writes.
- Baseline at plan start: **620 tests, OK (skipped=1)**. Every task ends green.
- Golden parity must stay green: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b` after every task; add `c` at Task 6 (it runs a real local G4 preflight, ~2 min, no grid).
- **Never `git push`.** Bash-tool subshells cannot reach the operator's credentials. The operator pushes.
- **Stage explicit paths only.** Never `git add -A`, `-u`, or `.`.
- **Never wildcard `rm`.** Use explicit named paths, or `git rm`/`git mv`.
- **No grid submission.** Offline validation only.
- Wiki edits (`wiki/**`) stay UNCOMMITTED for operator review. Do not commit them.
- Commit trailers, verbatim on every commit:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
  ```
- Do NOT change: metric definitions, harvest extractors, geom rendering, the mode-spec JSON schema, the leaderboard TSV schema or its locking, or `pipeline.py`'s per-stage idempotency guards.
- Branch off `json-modes`. Step 0 of the spec is already DONE (`8aa867b`, `7d51236`, `1b51767`, `e63f79d`) — do not redo it.

---

## File Structure

| File | Fate | Responsibility after |
|---|---|---|
| `graph/pool.py` | **create** | The parent rolling work-pool loop + outcome classification. Sole owner of round/wave bookkeeping. |
| `graph/closed_loop.py` | shrink 942 → ~250 | CLI + `main()` only; delegates the loop to `graph/pool.py` |
| `graph/child_tracker.py` | **delete** | — |
| `graph/presniff.py` | **delete** | — |
| `graph/config.py` | **delete** | constants move to `core/paths.py` + `core/runtime.py` |
| `core/runtime.py` | **create** | Non-path runtime tunables previously in `graph/config.py` |
| `graph/build.py` | modify | Child graph, no `mock_grid` node |
| `graph/nodes.py` | modify | `node_mock_grid` removed |
| `graph/state.py` | modify | `mock` field removed |
| `graph/run.py` | modify | Child entry; no `--mock`, no checkpointer, explicit `recursion_limit` |
| `graph/pipeline_io.py` | shrink | `mock_metrics` removed |
| `core/pipeline.py` | modify | `STAGES` literal deleted |
| `stage_entries/*.json` | modify | gain `desc_fmt`, `output_glob`, `njobs`, `merge_factor` |
| `mode_specs/{ipa625,ipafix,ipaovr,nominal}.json` | `git mv` → `mode_specs/archive/` | — |
| `tests/test_pool.py` | **create** | Pool-loop unit tests |
| `tests/test_closed_loop.py` | shrink 1022 → ~250 | keep CLI/arg tests, drop barrier machinery |
| `tests/test_child_tracker.py` | **delete** | — |
| `tests/test_wal_multiwriter_stress.py` | **delete** | — |

---

## Task 1: Pin `recursion_limit` explicitly

**Why first:** independent of everything else, one line each, and it is a live landmine — langgraph 1.2.9 (ours) has no practical cap, but langgraph 0.2.50 (the `ana_v2.8.0` pyenv candidate) defaults to **25**. The parent burns 6 supersteps per round, so `--max-rounds 5` would die at round ~4 with `GraphRecursionError`. The 620-test suite cannot catch it because no test runs five parent rounds.

**Files:**
- Modify: `graph/run.py:85` (the `graph.stream(...)` call)
- Modify: `graph/closed_loop.py:926` (the `graph.stream(...)` call)
- Test: `tests/test_recursion_limit.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. Later tasks must preserve the `recursion_limit` key when they rewrite these call sites (Task 3 replaces the `closed_loop.py` one entirely; Task 3 must NOT reintroduce an unbounded stream).

- [ ] **Step 1: Write the failing test**

Create `tests/test_recursion_limit.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_recursion_limit -v`
Expected: FAIL — `AssertionError: 'recursion_limit' not found in ...` (both calls exist today and neither pins it)

- [ ] **Step 3: Add the limit to `graph/run.py`**

Replace the `cfg` assignment (currently `cfg = {"configurable": {"thread_id": thread_id}}`) with:

```python
    # Pinned, not left to the library default: langgraph 1.2.9 has no
    # practical cap but 0.2.50 (the ana_v2.8.0 pyenv candidate) defaults to
    # 25. The child chain is ~8 supersteps plus up to MAX_PROPOSE_RETRIES
    # re-proposes; 100 is far above that and far below anything runaway.
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
```

- [ ] **Step 4: Add the limit to `graph/closed_loop.py`**

Find the `cfg` dict passed to `graph.stream(stream_input, cfg, stream_mode="values")` near line 926 and add the same key:

```python
    # 6 supersteps per round; 100 covers max_rounds well past any real
    # campaign. See graph/run.py for why this is pinned and not defaulted.
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
```

- [ ] **Step 5: Run the new test**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_recursion_limit -v`
Expected: PASS ×2

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
Expected: `Ran 622 tests ... OK (skipped=1)`

- [ ] **Step 7: Commit**

```bash
git add graph/run.py graph/closed_loop.py tests/test_recursion_limit.py
git commit -F - <<'EOF'
fix(graph): pin recursion_limit on both stream() calls

langgraph 1.2.9 has no practical cap (verified to 200 supersteps), but
langgraph 0.2.50 -- the version in the ana_v2.8.0 pyenv candidate -- defaults
to 25. The parent graph burns 6 supersteps per round, so --max-rounds 5 would
die at round ~4 with GraphRecursionError there. The 620-test suite cannot
catch it because no test runs five parent rounds.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Task 2: Delete mock mode

**Why:** the operator dropped it. It costs a graph node, a routing branch, a required CLI flag, a state field, and a `pipeline_io` function.

**Files:**
- Modify: `graph/build.py` — drop `node_mock_grid` import, `g.add_node("mock_grid", ...)`, the `"mock"` routing key, `g.add_edge("mock_grid", "evaluate")`
- Modify: `graph/nodes.py:200-202` — delete `node_mock_grid`; `graph/nodes.py:273-285` — `route_after_preflight` loses the `"mock"` branch
- Modify: `graph/state.py:53` — delete `mock: bool`
- Modify: `graph/run.py:58-59, 75` — delete the `--mock` argument and the `"mock"` init key
- Modify: `graph/closed_loop.py` — delete `"--no-mock",` from the child `cmd` list (in `node_launch_children`)
- Modify: `graph/pipeline_io.py:153-190` — delete `mock_metrics`
- Test: `tests/test_no_mock_mode.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `route_after_preflight(state) -> Literal["real", "propose", "__end__"]` — the `"mock"` return value is gone. Task 3 relaunches children without `--no-mock`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_mock_mode.py`:

```python
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

# graph/config.py resolves its mode spec at IMPORT time and its "foils"
# default is dangling (that spec was retired), so a bare `import build` raises
# KeyError('foils'). Set the mode explicitly rather than depend on the default.
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_no_mock_mode -v`
Expected: FAIL — `node_mock_grid` still present, `mock_metrics` still present, `mock` still in annotations, `mock_grid` still a node, `--mock` still in run.py.

- [ ] **Step 3: Remove the node and its routing**

In `graph/nodes.py`, delete the whole `node_mock_grid` function:

```python
def node_mock_grid(state: BOIterationState) -> dict:
    """Synthetic metrics — Phase 1 path, no grid contact."""
    return {"metrics": pio.mock_metrics(state["x_point"], state["mode"])}
```

and change `route_after_preflight`'s signature and pass-branch:

```python
def route_after_preflight(state: BOIterationState) -> Literal["real", "propose", "__end__"]:
```

```python
    if status == "pass":
        return "real"
```

In `graph/build.py`: drop `node_mock_grid,` from the `from nodes import (...)` block, delete the line `g.add_node("mock_grid", node_mock_grid)`, delete `"mock": "mock_grid",` from the `add_conditional_edges("render_preflight", ...)` mapping, and delete `g.add_edge("mock_grid", "evaluate")`.

- [ ] **Step 4: Remove the state field, the CLI flag, and `mock_metrics`**

In `graph/state.py`, delete the line `    mock: bool`.

In `graph/run.py`, delete the `--mock` argument block:

```python
    ap.add_argument("--mock", action=argparse.BooleanOptionalAction, required=True,
                    help="--mock = synthetic metrics (no grid); --no-mock = real grid.")
```

and delete `        "mock": args.mock,` from the `init` dict. Also delete the `--mock` mention from the module docstring usage line.

In `graph/closed_loop.py`, delete the line `            "--no-mock",` from the child `cmd` list.

In `graph/pipeline_io.py`, delete the `# --- mock grid (Phase 1) ---` comment and the entire `mock_metrics` function through its closing `}`.

- [ ] **Step 5: Run the new test**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_no_mock_mode -v`
Expected: PASS ×7

- [ ] **Step 6: Fix fallout in the existing suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -40`

Any test that passes `mock=True/False` in a state dict, asserts on `mock_grid`, or calls `mock_metrics` must be deleted (not adapted — the behaviour is gone). Delete those test methods outright.

- [ ] **Step 7: Verify suite and golden parity**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
Expected: OK, count is 622 minus whatever mock tests you deleted, plus 7.

Run: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b`
Expected: `[a] round-trip parity: OK` and `[b] history tensor fingerprint: OK`

- [ ] **Step 8: Commit**

```bash
git add graph/build.py graph/nodes.py graph/state.py graph/run.py \
        graph/closed_loop.py graph/pipeline_io.py tests/test_no_mock_mode.py
git add -u tests/
git commit -F - <<'EOF'
refactor(graph): delete mock mode

Retires the synthetic-metrics path at every surface it had: the mock_grid
node, route_after_preflight's "mock" branch, the required --mock CLI flag,
the `mock` state field, closed_loop's --no-mock child argument, and
pipeline_io.mock_metrics. route_after_preflight now returns
Literal["real", "propose", "__end__"].

Dropping any one surface and leaving the rest fails at RUNTIME, not import
(a --mock flag routing nowhere, or a node with no edge into it), so
tests/test_no_mock_mode.py pins the absence at all seven.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Task 3: Parent becomes a bounded work-pool; checkpointer and ChildTracker deleted

**Why atomic:** the barrier is the checkpointer's only consumer. Dropping the checkpointer first would leave the barrier polling something that no longer exists, so these land together.

**Rolling is the production mode** — every recent campaign ran `q=20 rolling max_evals=40`. `q` is pool *width*, not batch size.

**Files:**
- Create: `graph/pool.py`
- Create: `tests/test_pool.py`
- Modify: `graph/closed_loop.py` — delete `node_predict_picks`'s rolling branch, `node_assign_names`, `node_launch_children`, `node_barrier`, `node_decide_next`, `route_after_decide`, `_build_outer_graph`, `RoundState`, `ChildRecord`, `_DiskSignals`, and the `SqliteSaver`/`sqlite3` imports; keep `main()`, `_dry_run`, `_botorch_picks_subprocess`, `node_renew_token`'s body (as a plain function), `_stop_requested`, `_child_state_dir`, `_child_is_broken`, `_leaderboard_names`
- Modify: `graph/run.py` — compile without a checkpointer
- Modify: `graph/build.py` — delete `is_child_terminal`
- Delete: `graph/child_tracker.py`, `tests/test_child_tracker.py`, `tests/test_wal_multiwriter_stress.py`
- Modify: `tests/test_closed_loop.py` — delete barrier/checkpoint machinery tests

**Interfaces:**
- Consumes: `route_after_preflight` from Task 2 (no `"mock"`).
- Produces, all in `graph/pool.py`:
  - `Outcome = namedtuple("Outcome", "name x rc row_landed broken reason")`
  - `classify(name, x, rc, mode, row_landed, broken) -> Outcome`
  - `run_rolling(mode, picker, q, max_evals, alpha, name_prefix, run_child=None, next_pick=None, stop_flag=None, renew=None, row_landed=None, broken=None, log=print) -> dict` — returns `{"launched": int, "rows": int, "outcomes": list[Outcome], "aborted": bool}`. `run_child`, `next_pick`, `stop_flag`, `renew`, `row_landed` and `broken` are injected callables; production defaults are module-level functions. **This injection is the test seam** — tests pass fakes and never touch the grid, sqlite, or a subprocess.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pool.py`:

```python
"""Unit tests for the parent rolling work-pool.

Replaces ~1,470 LOC that tested five agreeing signal sources (checkpoint
terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard membership). The
pool has ONE: a child resolves when its subprocess exits. run_child is an
injected callable, so none of this touches the grid, sqlite, or a subprocess.
"""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))

import pool  # noqa: E402


def _picker(n_dims=2):
    """Deterministic pick source: x is [i, i], name is c{i}."""
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        i = counter["i"]
        counter["i"] += 1
        return [float(i)] * n_dims, f"c{i}"
    return next_pick, counter


class TestPoolWidth(unittest.TestCase):
    def test_never_exceeds_q_in_flight(self):
        peak = {"n": 0}
        lock = threading.Lock()
        gate = threading.Event()

        def run_child(name, x):
            with lock:
                peak["n"] += 1
                peak_now = peak["n"]
                peak["max"] = max(peak.get("max", 0), peak_now)
            gate.wait(timeout=5)
            with lock:
                peak["n"] -= 1
            return 0

        next_pick, _ = _picker()
        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=9, alpha=1.0,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None)
        t.cancel()
        self.assertLessEqual(peak["max"], 3)


class TestReplenish(unittest.TestCase):
    def test_one_resolution_triggers_exactly_one_new_pick(self):
        next_pick, counter = _picker()
        pool.run_rolling(mode="m", picker="p", q=2, max_evals=5, alpha=1.0,
                         name_prefix="t", run_child=lambda n, x: 0,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None)
        self.assertEqual(counter["i"], 5)

    def test_x_pending_equals_in_flight_set(self):
        seen = []
        gate = threading.Event()

        def run_child(name, x):
            gate.wait(timeout=5)
            return 0

        def next_pick(mode, picker, x_pending):
            seen.append([list(v) for v in x_pending])
            i = len(seen) - 1
            return [float(i)], f"c{i}"

        t = threading.Timer(0.2, gate.set)
        t.start()
        pool.run_rolling(mode="m", picker="p", q=3, max_evals=3, alpha=1.0,
                         name_prefix="t", run_child=run_child,
                         next_pick=next_pick,
                         stop_flag=lambda: False, renew=lambda: None)
        t.cancel()
        self.assertEqual(seen[0], [])
        self.assertEqual(seen[1], [[0.0]])
        self.assertEqual(seen[2], [[0.0], [1.0]])


class TestDrain(unittest.TestCase):
    def test_loop_drains_inflight_before_exiting(self):
        """The final-round orphan-children fix, as an assertion."""
        finished = []

        def run_child(name, x):
            finished.append(name)
            return 0

        next_pick, _ = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=4, max_evals=4,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: False, renew=lambda: None)
        self.assertEqual(len(finished), 4)
        self.assertEqual(len(res["outcomes"]), 4)


class TestNoRowStreak(unittest.TestCase):
    def test_streak_increments_on_rowless_and_resets_on_row(self):
        """Each child's outcome is observed as it resolves; there are no wave
        baselines for a row to be absorbed into. That is the root fix for
        rolling-no-row-streak-false-increment."""
        rows = {"c0": False, "c1": True, "c2": False}
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=1, max_evals=3, alpha=1.0,
            name_prefix="t",
            run_child=lambda n, x: 0 if rows.get(n) else 1,
            next_pick=next_pick,
            stop_flag=lambda: False, renew=lambda: None,
            row_landed=lambda name, mode: rows.get(name, False))
        self.assertEqual(res["rows"], 1)
        self.assertFalse(res["aborted"])

    def test_q_consecutive_rowless_aborts(self):
        next_pick, _ = _picker()
        res = pool.run_rolling(
            mode="m", picker="p", q=2, max_evals=10, alpha=1.0,
            name_prefix="t", run_child=lambda n, x: 1,
            next_pick=next_pick,
            stop_flag=lambda: False, renew=lambda: None,
            row_landed=lambda name, mode: False)
        self.assertTrue(res["aborted"])
        self.assertLess(res["launched"], 10)


class TestStopFlag(unittest.TestCase):
    def test_stop_halts_topup_but_still_drains(self):
        stop = {"v": False}
        done = []

        def run_child(name, x):
            done.append(name)
            stop["v"] = True
            return 0

        next_pick, counter = _picker()
        res = pool.run_rolling(mode="m", picker="p", q=2, max_evals=20,
                               alpha=1.0, name_prefix="t",
                               run_child=run_child, next_pick=next_pick,
                               stop_flag=lambda: stop["v"],
                               renew=lambda: None)
        self.assertLess(res["launched"], 20)
        self.assertEqual(len(res["outcomes"]), len(done))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_pool -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pool'`

- [ ] **Step 3: Write `graph/pool.py`**

```python
"""The parent rolling work-pool: q children in flight, replenish on resolve.

Replaces node_predict_picks' rolling branch + node_assign_names +
node_launch_children + node_barrier + node_decide_next + child_tracker.py --
roughly 700 LOC expressing a bounded work pool across four graph nodes and a
checkpointed state dict.

A child resolves when its SUBPROCESS EXITS. That is one truth source,
replacing five (checkpoint terminal, pid_alive, *_cluster.txt, broken.txt,
leaderboard membership). Four incidents stop being possible rather than
guarded:

  barrier-false-positive-round1          no checkpoint `.next` to misread
  closed-loop-barrier-timeout-zero-rows  no parent-level barrier timeout
  closed-loop-final-round-orphan-children `or inflight` drains before exit
  rolling-no-row-streak-false-increment   no wave baselines to absorb a row

run_child / next_pick / stop_flag / renew / row_landed are injected callables.
That is the test seam: tests pass fakes and never touch grid, sqlite, or a
subprocess.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

Outcome = namedtuple("Outcome", "name x rc row_landed broken reason")


def classify(name, x, rc, mode, row_landed, broken) -> Outcome:
    """Exit code plus artifacts decide the outcome. No polling."""
    if rc == 0 and row_landed:
        return Outcome(name, x, rc, True, False, "ok")
    if broken:
        return Outcome(name, x, rc, False, True, "broken")
    if rc != 0:
        return Outcome(name, x, rc, False, False, f"child rc={rc}")
    return Outcome(name, x, rc, False, False, "exit 0 but no leaderboard row")


def run_rolling(mode, picker, q, max_evals, alpha, name_prefix,
                run_child=None, next_pick=None, stop_flag=None, renew=None,
                row_landed=None, broken=None, log=print):
    """Keep q children in flight until max_evals launched and the pool drains.

    Returns {"launched", "rows", "outcomes", "aborted"}.

    Aborts when `q` consecutive resolutions land no row -- the guard that used
    to need name-based wave accounting. Here each child's own outcome is read
    at the moment it resolves, so a row cannot be absorbed into a neighbouring
    wave's baseline.
    """
    run_child = run_child or _default_run_child(mode, alpha)
    next_pick = next_pick or _default_pick_source(name_prefix)
    stop_flag = stop_flag or (lambda: False)
    renew = renew or (lambda: None)
    row_landed = row_landed or _default_row_landed
    broken = broken or _default_broken

    inflight = {}
    launched = 0
    rows = 0
    streak = 0
    aborted = False
    outcomes = []

    with ThreadPoolExecutor(max_workers=q) as poolx:
        while (launched < max_evals or inflight) and not aborted:
            while (len(inflight) < q and launched < max_evals
                   and not stop_flag() and not aborted):
                renew()
                x, name = next_pick(mode, picker,
                                    [v for _, v in inflight.values()])
                inflight[poolx.submit(run_child, name, x)] = (name, x)
                launched += 1
                log(f"[pool] launched {name} ({launched}/{max_evals}), "
                    f"in_flight={len(inflight)}")
            if not inflight:
                break
            done = next(as_completed(list(inflight)))
            name, x = inflight.pop(done)
            try:
                rc = done.result()
            except Exception as exc:  # noqa: BLE001
                rc = 1
                log(f"[pool] {name} raised: {exc}")
            oc = classify(name, x, rc, mode,
                          row_landed(name, mode), broken(name))
            outcomes.append(oc)
            if oc.row_landed:
                rows += 1
                streak = 0
            else:
                streak += 1
                log(f"[pool] {name}: {oc.reason} "
                    f"(no-row streak {streak}/{q})")
            if streak >= q:
                aborted = True
                log(f"[pool] ABORT: {q} consecutive resolutions with no row")
        # Drain: never exit with work in flight. This is the structural fix
        # for closed-loop-final-round-orphan-children.
        for fut in as_completed(list(inflight)):
            name, x = inflight.pop(fut)
            try:
                rc = fut.result()
            except Exception:  # noqa: BLE001
                rc = 1
            oc = classify(name, x, rc, mode,
                          row_landed(name, mode), broken(name))
            outcomes.append(oc)
            if oc.row_landed:
                rows += 1
    return {"launched": launched, "rows": rows,
            "outcomes": outcomes, "aborted": aborted}


# --- production defaults ---------------------------------------------------

def _default_run_child(mode, alpha):
    """Popen `graph.run` and WAIT. The wait IS the barrier."""
    from config import GRAPH_DATA, PROJECT_ROOT  # Task 4 moves this to core.runtime

    def run_child(name, x):
        logs = GRAPH_DATA / "closed_loop_logs"
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"{name}.log"
        cmd = [
            sys.executable, "-m", "graph.run",
            "--thread-id", f"{name}_{uuid.uuid4().hex[:8]}",
            "--config-name", name,
            "--mode", mode,
            "--alpha", str(alpha),
            "--x-point", ",".join(f"{v:.6f}" for v in x),
        ]
        with open(log_path, "w") as fh:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                    cwd=str(PROJECT_ROOT))
        return proc.wait()
    return run_child


def _default_pick_source(name_prefix):
    """Closure so the picker sees the running launch index for its name and
    round-seed. Imports closed_loop lazily -- closed_loop imports pool."""
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        import closed_loop as cl
        i = counter["i"]
        counter["i"] += 1
        picks = cl._botorch_picks_subprocess(mode, q=1, round_idx=i,
                                             picker=picker, pending=x_pending)
        return list(picks[0]), f"{name_prefix}R{i:02d}_00"
    return next_pick


def _default_row_landed(name, mode):
    import closed_loop as cl
    return name in cl._leaderboard_names(mode)


def _default_broken(name):
    import closed_loop as cl
    return cl._child_is_broken(name)
```

- [ ] **Step 4: Wire the production defaults**

Verify the two signatures the defaults depend on, and adjust the calls if the
real ones differ — do not assume:

```bash
grep -n "def _botorch_picks_subprocess" -A 4 graph/closed_loop.py
grep -n "def _leaderboard_names\|def _child_is_broken" -A 3 graph/closed_loop.py
```

`_botorch_picks_subprocess(mode, q, round_idx, picker=..., pending=...)` must
return a sequence of x-lists; if its keyword for in-flight points is not
`pending`, use the real name. Every `closed_loop` import inside `pool.py` is
lazy and inside the function body **on purpose** — `closed_loop` imports
`pool`, so a module-level import is a circular-import failure at startup.

- [ ] **Step 5: Run the pool tests**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_pool -v`
Expected: PASS ×7

- [ ] **Step 6: Rewire `closed_loop.main()` and delete the graph**

In `graph/closed_loop.py`, delete `node_predict_picks`'s rolling branch, `node_assign_names`, `node_launch_children`, `node_barrier`, `node_decide_next`, `route_after_decide`, `_build_outer_graph`, `RoundState`, `ChildRecord`, `_DiskSignals`, `_open_saver_conn`, and the `sqlite3` / `SqliteSaver` imports. Replace the graph invocation in `main()` with:

```python
    from pool import run_rolling
    result = run_rolling(
        mode=args.mode, picker=args.picker, q=args.q,
        max_evals=args.max_evals or (args.q * args.max_rounds),
        alpha=args.alpha, name_prefix=args.name_prefix)
    print(f"[closed_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']}", flush=True)
    return 1 if result["aborted"] else 0
```

Delete the `--rolling` flag: rolling is now the only mode. Keep `--max-evals`; when omitted it defaults to `q * max_rounds` as shown.

- [ ] **Step 7: Compile both graphs without a checkpointer**

In `graph/run.py`, delete `saver = SqliteSaver(open_saver_conn())` and the `SqliteSaver` import, and change the compile to:

```python
    # No checkpointer. Audited 51 campaigns: 44 clean, 7 died mid-flight, 0
    # ever resumed from a checkpoint -- while it CAUSED 5 incidents, and in
    # sqlite-wal-corrupt-after-kill it blocked the restart outright. The
    # useful half of resume is assign_names skipping names already in the
    # leaderboard, which is the leaderboard's doing and survives this.
    graph = build_graph().compile()
```

In `graph/build.py`, delete `is_child_terminal` entirely.

- [ ] **Step 8: Delete the dead modules and their tests**

```bash
git rm graph/child_tracker.py tests/test_child_tracker.py \
       tests/test_wal_multiwriter_stress.py
```

- [ ] **Step 9: Trim `tests/test_closed_loop.py`**

Delete every test that patches `cl.SqliteSaver`, calls `node_barrier`, `node_assign_names`, `node_launch_children`, `node_decide_next`, `route_after_decide`, or `is_child_terminal`. Keep the CLI/argument-parsing tests and anything exercising `_botorch_picks_subprocess`, `_leaderboard_names`, `_child_is_broken`, or `_stop_requested`.

- [ ] **Step 10: Run the full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -30`
Expected: OK. Count drops sharply (≈ −60 tests from the three deleted files, +7 from `test_pool.py`).

Run: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b`
Expected: both OK.

- [ ] **Step 11: Commit**

```bash
git add graph/pool.py graph/closed_loop.py graph/run.py graph/build.py \
        tests/test_pool.py
git add -u graph/ tests/
git commit -F - <<'EOF'
refactor(graph): parent becomes a work-pool; checkpointer + ChildTracker gone

The parent's six nodes were pool bookkeeping in a straight line. graph/pool.py
expresses the same rolling campaign as a bounded ThreadPoolExecutor whose
barrier is as_completed -- ~700 LOC of node/state/tracker machinery replaced.

A child now resolves when its SUBPROCESS EXITS: one truth source replacing
five (checkpoint terminal, pid_alive, *_cluster.txt, broken.txt, leaderboard
membership). Four incidents become structurally impossible rather than
guarded: barrier-false-positive-round1 (no checkpoint .next to misread),
closed-loop-barrier-timeout-zero-rows-falsepos (no parent-level barrier
timeout), closed-loop-final-round-orphan-children (`or inflight` drains before
exit), rolling-no-row-streak-false-increment (outcomes observed as they
resolve, so no wave baseline can absorb a row).

Both graphs compile WITHOUT a checkpointer. Audit across all 51 parent logs
with parseable rounds: 44 ended cleanly, 7 died mid-flight, and 0 EVER resumed
from a checkpoint -- while it caused 5 incidents and, in
sqlite-wal-corrupt-after-kill, blocked the restart outright.

x_pending is now the literal in-flight set rather than a pending TSV that can
drift. run_child/next_pick/stop_flag/renew/row_landed are injected callables,
so tests touch no grid, no sqlite, no subprocess.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Task 4: Plumbing — `pipeline_io` in-process, `presniff` and `graph/config.py` deleted

**Files:**
- Create: `core/runtime.py`
- Delete: `graph/presniff.py`, `graph/config.py`
- Modify: `graph/nodes.py`, `graph/build.py`, `graph/run.py`, `graph/closed_loop.py`, `graph/pool.py`, `graph/pipeline_io.py` — import from `core.runtime` / `core.paths`
- Test: `tests/test_runtime_constants.py` (create)

**Interfaces:**
- Consumes: `graph/pool.py` from Task 3.
- Produces: `core/runtime.py` exporting `DEFAULT_MODE`, `DEFAULT_ALPHA`, `MAX_PROPOSE_RETRIES`, `PREFLIGHT_TIMEOUT_S`, `CLOSED_LOOP_Q`, `CLOSED_LOOP_MAX_ROUNDS`, `CLOSED_LOOP_STAGGER_SEC`, `CLOSED_LOOP_BARRIER_POLL_SEC`, `CLOSED_LOOP_BARRIER_MAX_MIN`, `STOP_FLAG`, `BOTORCH_VENV_PY`, `BOTORCH_PREDICT`, `BO_DRIVER`, `PIPELINE_DRIVER`, `GRID_STAGES`, `PRESUBMIT_AFTER`, `MUSING`. Path-shaped names (`GRAPH_DATA`, `PROJECT_ROOT`, `GRID_DATA_ROOT`) come from `core/paths.py`, which already owns them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_constants.py`:

```python
"""core/runtime.py owns the non-path runtime tunables graph/config.py held.

presniff.py existed only because config.py read AUTORESEARCH_* env vars at
IMPORT time while argparse ran in main() -- too late. Constants that are
plain values, resolved once, need no pre-argparse sniffing, so both files go.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

NAMES = [
    "DEFAULT_MODE", "DEFAULT_ALPHA", "MAX_PROPOSE_RETRIES",
    "PREFLIGHT_TIMEOUT_S", "CLOSED_LOOP_Q", "CLOSED_LOOP_MAX_ROUNDS",
    "CLOSED_LOOP_STAGGER_SEC", "CLOSED_LOOP_BARRIER_POLL_SEC",
    "CLOSED_LOOP_BARRIER_MAX_MIN", "STOP_FLAG", "BOTORCH_VENV_PY",
    "BOTORCH_PREDICT", "BO_DRIVER", "PIPELINE_DRIVER", "GRID_STAGES",
    "PRESUBMIT_AFTER", "MUSING",
]


class TestRuntimeConstants(unittest.TestCase):
    def test_all_names_present(self):
        import runtime
        missing = [n for n in NAMES if not hasattr(runtime, n)]
        self.assertEqual(missing, [])

    def test_graph_config_is_gone(self):
        self.assertFalse((ROOT / "graph" / "config.py").exists())

    def test_presniff_is_gone(self):
        self.assertFalse((ROOT / "graph" / "presniff.py").exists())

    def test_no_module_imports_graph_config(self):
        offenders = []
        for p in list((ROOT / "graph").glob("*.py")) + list((ROOT / "core").glob("*.py")):
            t = p.read_text()
            if "from config import" in t or "import presniff" in t:
                offenders.append(p.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_runtime_constants -v`
Expected: FAIL ×4

- [ ] **Step 3: Create `core/runtime.py`**

Copy the constant definitions verbatim out of `graph/config.py` (lines 31-32, 50-75, 126-170, 198-201), replacing `PROJECT_ROOT` with an import from `core/paths.py`:

```python
"""Non-path runtime tunables for the BO loop.

Moved out of graph/config.py 2026-08-19. Path-shaped roots live in
core/paths.py, which is the single filesystem-root resolver; this file holds
only plain values. graph/presniff.py died with the move: it existed solely
because config.py resolved AUTORESEARCH_* env vars at IMPORT time while
argparse ran later in main(), and constants resolved once need no
pre-argparse sniffing.
"""
from __future__ import annotations

import os
from pathlib import Path

import modes as _modes
from paths import GRAPH_DATA, REPO_ROOT

# Default is foilspf, NOT the historical "foils": that spec was retired and
# the lookup has been dangling since -- a bare `import config` raised
# KeyError('foils'). See ledger Ruling 2.
_SPEC = _modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foilspf")]

MUSING = _SPEC.musing
GRID_STAGES = list(_SPEC.grid_stages)
PRESUBMIT_AFTER = {k: list(v) for k, v in _SPEC.presubmit_after.items()}

BO_DRIVER = REPO_ROOT / "core" / "bo_driver.py"
PIPELINE_DRIVER = REPO_ROOT / "core" / "pipeline.py"
BOTORCH_PREDICT = REPO_ROOT / "core" / "botorch_predict.py"
BOTORCH_VENV_PY = Path(os.environ.get(
    "AUTORESEARCH_BOTORCH_VENV", str(REPO_ROOT / ".venv"))) / "bin" / "python"

DEFAULT_MODE = "foilspf"
DEFAULT_ALPHA = 1.0e5
MAX_PROPOSE_RETRIES = 3
PREFLIGHT_TIMEOUT_S = 1200
CLOSED_LOOP_Q = 5
CLOSED_LOOP_MAX_ROUNDS = 10
CLOSED_LOOP_STAGGER_SEC = 90
CLOSED_LOOP_BARRIER_POLL_SEC = 300
CLOSED_LOOP_BARRIER_MAX_MIN = 1440
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"
```

Check `graph/config.py` for the exact `BOTORCH_VENV_PY` expression and copy it rather than the sketch above if it differs.

**Ruling 2 applies here (from the SDD ledger):** do NOT copy `"foils"` forward.
That spec was retired, so `SPECS["foils"]` is a dangling lookup — verify with
`PYTHONPATH= .venv/bin/python -c "import sys;sys.path.insert(0,'core');sys.path.insert(0,'graph');import config"`,
which raises `KeyError: 'foils'` today. Both the `_SPEC` lookup default and
`DEFAULT_MODE` become `"foilspf"`. Add a test to
`tests/test_runtime_constants.py`:

```python
    def test_default_mode_is_a_live_mode(self):
        import modes
        import runtime
        self.assertIn(runtime.DEFAULT_MODE, modes.SPECS)
```

- [ ] **Step 4: Repoint every importer**

In `graph/nodes.py`, `graph/build.py`, `graph/run.py`, `graph/closed_loop.py`, `graph/pool.py`: change `from config import X, Y` to `from runtime import X, Y`, moving any path-shaped name (`GRAPH_DATA`, `PROJECT_ROOT`) to `from paths import GRAPH_DATA, REPO_ROOT as PROJECT_ROOT`. Delete all `import presniff` / `presniff.*` calls and their pre-`from config import` comment blocks.

- [ ] **Step 5: Make `pipeline_io` call `core/` in-process**

In `graph/pipeline_io.py`, replace `_run_pipeline_verb`'s `subprocess.run([...PIPELINE_DRIVER...])` with a direct import and call of `core/pipeline.py`'s `cmd_submit` / `cmd_poll` / `cmd_list_outputs` / `cmd_harvest`. Keep `run_preflight` as a subprocess — it shells a sourced Mu2e environment and must stay firewalled.

**If the in-process switch causes any test to fail on captured stdout or on `SystemExit`, revert just this step**, leave `_run_pipeline_verb` shelling out, and note it in the commit. The subprocess firewall existed for the checkpointed runner; removing it is a nice-to-have, not load-bearing, and it is not worth destabilising the harvest path.

- [ ] **Step 6: Delete the old files**

```bash
git rm graph/config.py graph/presniff.py
```

- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_runtime_constants -v`
Expected: PASS ×4

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
Expected: OK

Run: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b`
Expected: both OK

- [ ] **Step 8: Commit**

```bash
git add core/runtime.py tests/test_runtime_constants.py
git add -u graph/ core/
git commit -F - <<'EOF'
refactor(graph): core/runtime.py replaces graph/config.py; presniff deleted

Path-shaped roots already belong to core/paths.py (the single filesystem-root
resolver); core/runtime.py takes the plain values that were sharing
graph/config.py with them.

presniff.py dies with the move. It existed ONLY because config.py resolved
AUTORESEARCH_* env vars at IMPORT time while argparse ran later in main() --
too late for build.STAGE_NODES, which freezes GRID_STAGES. Constants resolved
once need no pre-argparse sniffing.

pipeline_io's grid-stage wrappers now call core/pipeline.py in-process. The
subprocess firewall existed to keep I/O side effects away from the long-lived
CHECKPOINTED runner, which no longer exists. run_preflight deliberately stays
a subprocess: it shells a sourced Mu2e environment.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Task 5: Archive the four A/B mode specs

**Scope honesty:** this saves ~0 LOC. Mode specs are JSON data and mode dispatch is already down to 5 hardcoded strings repo-wide. It is tidiness, and it is the cheapest task in the plan — do not let anyone conclude the codebase was large *because* it supported 11 modes.

**Files:**
- Move: `mode_specs/{ipa625,ipafix,ipaovr,nominal}.json` → `mode_specs/archive/`
- Modify: `core/mode_json.py` — exclude `archive/` from the spec glob
- Test: `tests/test_mode_archive.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `modes.SPECS` has 7 keys — `foilsflash`, `foilspf`, `foilspf2k`, `foilspfbp`, `foilspfbpx`, `foilspfbpz`, `foilspfbw`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mode_archive.py`:

```python
"""The four one-shot A/B specs are archived, not deleted.

Their leaderboards (leaderboard_ab_*.tsv) stay in place and readable, so
nothing that can reproduce a past row is destroyed -- only the registry glob
stops picking the specs up.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

ARCHIVED = ["ipa625", "ipafix", "ipaovr", "nominal"]
LIVE = ["foilsflash", "foilspf", "foilspf2k", "foilspfbp",
        "foilspfbpx", "foilspfbpz", "foilspfbw"]


class TestModeArchive(unittest.TestCase):
    def test_live_modes_are_exactly_the_foilspf_family(self):
        import modes
        self.assertEqual(sorted(modes.SPECS), sorted(LIVE))

    def test_archived_specs_moved_not_deleted(self):
        for m in ARCHIVED:
            self.assertFalse((ROOT / "mode_specs" / f"{m}.json").exists(), m)
            self.assertTrue((ROOT / "mode_specs" / "archive" / f"{m}.json").exists(), m)

    def test_archived_leaderboards_still_present(self):
        for m in ARCHIVED:
            self.assertTrue(
                (ROOT / "leaderboards" / f"leaderboard_ab_{m}.tsv").exists(), m)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_mode_archive -v`
Expected: FAIL — `SPECS` still has 11 keys; `mode_specs/archive/` does not exist.

- [ ] **Step 3: Move the specs**

```bash
mkdir -p mode_specs/archive
git mv mode_specs/ipa625.json mode_specs/ipafix.json \
       mode_specs/ipaovr.json mode_specs/nominal.json mode_specs/archive/
```

- [ ] **Step 4: Exclude `archive/` from the glob**

In `core/mode_json.py`, find the spec-discovery glob (a `MODE_SPECS_DIR.glob("*.json")`) and confirm it is non-recursive so `archive/` is already excluded. If it uses `rglob` or `**`, change it to a flat `glob("*.json")` and add:

```python
# Flat glob on purpose: mode_specs/archive/ holds retired one-shot A/B specs
# whose leaderboards are still readable. A recursive glob would resurrect them
# into the registry.
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_mode_archive -v`
Expected: PASS ×3

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -30`

Fix fallout: `tests/test_modes.py`, `tests/test_json_mode.py` and `tests/golden_parity.py`'s `section_a` iterate `bo.MODES`. Any test asserting an 11-mode registry updates to 7. `[a]`'s baseline must be re-captured because four mode keys disappear.

- [ ] **Step 6: Re-capture golden `[a]`**

Run: `PYTHONPATH= .venv/bin/python tests/golden_parity.py capture a`
Then: `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b`
Expected: both OK.

Before committing the new baseline, diff it against the old one and confirm the ONLY change is the four removed mode keys — no row counts, sha256s, or `mismatch_idx` entries may move for the seven survivors.

- [ ] **Step 7: Commit**

```bash
git add mode_specs/archive core/mode_json.py tests/test_mode_archive.py \
        tests/goldens/parity_a_baseline.json
git add -u mode_specs/ tests/
git commit -F - <<'EOF'
refactor(modes): archive the four one-shot A/B specs

ipa625, ipafix, ipaovr, nominal -- 2 rows each -- move to mode_specs/archive/
via git mv, not delete. Their leaderboard_ab_*.tsv files stay in place, so
nothing that can reproduce a past row is destroyed; only the registry glob
stops picking the specs up. modes.SPECS is now the 7-key foilspf family.

Saves ~0 LOC, and that is the point worth recording: mode specs are JSON data
and mode dispatch is already down to 5 hardcoded strings across all of core/
and graph/. This codebase was never large BECAUSE it supported 11 modes.

Golden [a] re-captured -- verified the only delta is the four removed keys;
no row count, sha256 or mismatch_idx moved for the seven survivors.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Task 6: Retire the `STAGES` literal into `stage_entries/`

**The real defect is a silent shadow, not "insufficient genericity."** `stage_entries/<stage>.json` already carries an `events` key holding the *same values* as `STAGES[…]["events_per_job"]` — mubeam 5000, mustops_ce 2500, elebeam_flash 2500, run1b_mubeam 5000. `core/pipeline.py:1062` resolves `events=cfg.get("events_per_job", entry_tmpl.get("events"))`, so `STAGES` wins and the JSON never fires. They agree today by coincidence; editing the JSON is a **silent no-op**. Same shape as the outloc precedence bug and `events-per-job-mid-flight-edit`.

`desc_fmt` and `output_glob` should NOT become mode-driven — `sim.*.TargetStops.*.art` is what mubeam emits regardless of geometry. They are stage properties in the wrong file.

**Files:**
- Modify: `stage_entries/{mubeam,run1b_mubeam,concat,mustops_ce,elebeam_flash}.json` — add `desc_fmt`, `output_glob`, `njobs`; `concat` also gains `merge_factor`
- Modify: `core/pipeline.py:209-258` — delete `STAGES`; `:506`, `:517`, `:870`, `:1047`, `:1062`, `:1307` — read from the stage entry
- Test: `tests/test_stages_retired.py` (create)

**Interfaces:**
- Consumes: `core/runtime.py` from Task 4 (`GRID_STAGES`).
- Produces: `pipeline.stage_cfg(stage) -> dict` — merged view, mode spec overriding stage entry. One precedence rule, one direction:
  > mode spec (`run.jobs_per_stage`, `run.stage_tuning`) **overrides** `stage_entries/<stage>.json` (the default). Nothing overrides the mode spec.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stages_retired.py`:

```python
"""The STAGES literal is gone; stage-level data lives in stage_entries/.

The bug being removed is a SILENT SHADOW: stage_entries/<stage>.json already
carried `events` with the same values as STAGES[...]["events_per_job"], and
pipeline.py resolved STAGES first -- so editing the JSON did nothing, with no
error. Same failure shape as the outloc precedence bug and
events-per-job-mid-flight-edit.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

STAGES = ["mubeam", "run1b_mubeam", "concat", "mustops_ce", "elebeam_flash"]


class TestStagesRetired(unittest.TestCase):
    def test_pipeline_has_no_STAGES_literal(self):
        import pipeline
        self.assertFalse(hasattr(pipeline, "STAGES"))

    def test_every_stage_entry_carries_stage_level_fields(self):
        for s in STAGES:
            d = json.loads((ROOT / "stage_entries" / f"{s}.json").read_text())
            self.assertIn("desc_fmt", d, s)
            self.assertIn("output_glob", d, s)
            self.assertIn("njobs", d, s)

    def test_no_duplicated_events_per_job_key(self):
        """`events` is the only spelling. Two files holding one number, with
        one silently winning, is the bug this task removes."""
        for s in STAGES:
            d = json.loads((ROOT / "stage_entries" / f"{s}.json").read_text())
            self.assertNotIn("events_per_job", d, s)

    def test_mode_spec_overrides_stage_entry(self):
        import pipeline
        cfg = pipeline.stage_cfg("mubeam", mode="foilspf")
        self.assertEqual(cfg["events"], 200000)
        self.assertEqual(cfg["njobs"], 15)

    def test_stage_entry_supplies_the_default(self):
        import pipeline
        cfg = pipeline.stage_cfg("mubeam", mode=None)
        self.assertEqual(cfg["events"], 5000)
        self.assertEqual(cfg["desc_fmt"], "Run1A_MuBeam_{cfg}")
        self.assertEqual(cfg["output_glob"], "sim.*.TargetStops.*.art")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_stages_retired -v`
Expected: FAIL ×5

- [ ] **Step 3: Move the data into `stage_entries/`**

Add to each stage entry JSON the values currently in `STAGES` (`core/pipeline.py:209-258`) and `STAGE_TARGETS` (was `graph/config.py:86`, now `core/runtime.py`):

| stage | `desc_fmt` | `output_glob` | `njobs` | extra |
|---|---|---|---|---|
| mubeam | `Run1A_MuBeam_{cfg}` | `sim.*.TargetStops.*.art` | 200 | |
| run1b_mubeam | `Run1B_MuBeam_{cfg}` | `nts.*.mubeam.*.root` | 200 | |
| concat | `Run1A_MuStopsCat_{cfg}` | `sim.*.MuminusStopsCat.*.art` | 1 | `merge_factor: 200` |
| mustops_ce | `Run1A_CeEndpoint_{cfg}` | `dts.*.CeEndpoint.*.art` | 200 | |
| elebeam_flash | `Run1A_EleBeamFlash_{cfg}` | `dts.*.EarlyEleBeamFlash.*.art` | 100 | |

Do **not** add `events_per_job` — `events` is already there with the right value.

Move the load-bearing tuning rationale from the `STAGES` comments into each entry's existing `_comment` key. The `mustops_ce` history is measured knowledge, not decoration — carry it verbatim, especially: the 2026-05-21 AM reversion to `events_per_job=5000` without compensating `njobs` halved statistics and moved σ(sob) 0.10 → 0.14; the 200×2500 pairing restores it.

- [ ] **Step 4: Add `stage_cfg` and delete `STAGES`**

In `core/pipeline.py`, delete the `STAGES = {...}` literal (lines 209-258) and add:

```python
def stage_cfg(stage: str, mode: str | None = None) -> dict:
    """Merged stage config. ONE precedence rule, ONE direction.

    mode spec (run.jobs_per_stage, run.stage_tuning) OVERRIDES
    stage_entries/<stage>.json (the default). Nothing overrides the mode spec.

    This replaces the STAGES literal, whose `events_per_job` shadowed the
    `events` key that stage_entries/<stage>.json already carried with the same
    value -- so editing the JSON was a silent no-op. Two files holding one
    number with one quietly winning is the failure shape of the outloc
    precedence bug and of events-per-job-mid-flight-edit.
    """
    import prodtools_exec
    cfg = dict(prodtools_exec.load_stage_entry(stage))
    if mode:
        import modes
        spec = modes.SPECS[mode]
        if stage in spec.jobs_per_stage:
            cfg["njobs"] = spec.jobs_per_stage[stage]
        tuning = spec.stage_tuning.get(stage, {})
        if "events_per_job" in tuning:
            cfg["events"] = tuning["events_per_job"]
        for k in ("memory_mb", "quorum"):
            if k in tuning:
                cfg[k] = tuning[k]
    return cfg
```

Replace every `STAGES[stage]` read (`:506`, `:517`, `:870`, `:1047`, `:1062`, `:1307`) with `stage_cfg(stage, MODE)`. At `:1062` the whole `events=cfg.get("events_per_job", entry_tmpl.get("events"))` expression collapses to `events=cfg["events"]`.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_stages_retired -v`
Expected: PASS ×5

- [ ] **Step 6: Prove it is pure data relocation**

Write a throwaway check in the scratchpad that renders the prodtools entry for all 7 modes × 5 stages at `HEAD` and at `HEAD~1`, and diffs them. **Every one must be byte-identical.** Any diff is a bug, not an improvement — fix it before continuing.

- [ ] **Step 7: Run the full suite and all three golden sections**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
Expected: OK

Run: `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` then
`PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b c`
Expected: `[a] OK`, `[b] OK`, `[c] seam replay parity: OK` (`[c]` runs a real local G4 preflight, ~2 min, no grid contact).

- [ ] **Step 8: Commit**

```bash
git add core/pipeline.py stage_entries tests/test_stages_retired.py
git add -u core/ tests/
git commit -F - <<'EOF'
refactor(pipeline): retire the STAGES literal into stage_entries/

The headline is not "make STAGES generic" -- njobs and events_per_job already
resolved from the mode spec, and desc_fmt/output_glob SHOULD NOT be
mode-driven (sim.*.TargetStops.*.art is what mubeam emits regardless of
geometry). They are stage properties that were sitting in a module-level
Python global instead of the per-stage JSON beside them.

The headline is a SILENT SHADOW. stage_entries/<stage>.json already carried
an `events` key with the SAME values as STAGES[...]["events_per_job"] (mubeam
5000, mustops_ce 2500, elebeam_flash 2500, run1b_mubeam 5000), and
pipeline.py resolved `cfg.get("events_per_job", entry_tmpl.get("events"))` --
STAGES won, the JSON never fired, and editing it was a no-op with no error.
They agreed only by coincidence. Third instance of this shape, after the
outloc precedence bug and events-per-job-mid-flight-edit.

New stage_cfg(stage, mode) has ONE precedence rule in ONE direction: mode spec
overrides stage entry, nothing overrides the mode spec. The measured
mustops_ce tuning history moves into the entry's _comment -- the 2026-05-21 AM
reversion to 5000 without compensating njobs halved statistics and moved
sigma(sob) 0.10 -> 0.14.

Verified pure data relocation: 7 modes x 5 stages render byte-identical
prodtools entries before and after.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## Acceptance (after Task 6)

**Offline gates — must all pass before any live run:**

- [ ] `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .` → OK
- [ ] `PYTHONPATH= .venv/bin/python tests/golden_parity.py check a b c` → all three OK
- [ ] `wc -l graph/*.py` totals ≈ 900 (from 2,524)

**Live gate — requires EXPLICIT operator approval at the point of launch. This plan's approval does not authorize submission. Ask again.**

Per spec §7, 9 evaluations total:

1. Pick an `x_point` already in `leaderboards/leaderboard_bo_foilspfbpz.tsv`. Run it through `graph.run --x-point` on old code and new code.
2. **Rendered geom file must be byte-identical** — deterministic, so a hard equality check covering the whole propose → render path.
3. **Metrics compared within measured noise**, not bit-identical: re-running resamples. Use σ(sob)=0.6% from `wiki/concepts/bo-noise-budget.md`.
4. One small rolling campaign (`q=4`, `max_evals=8`) to exercise replenish-and-drain, which a single eval cannot reach.

**Known regression to state plainly at handover:** a parent killed mid-round loses that round's bookkeeping. Per-stage `cluster.txt` idempotency means a relaunch re-attaches to already-submitted grid clusters rather than resubmitting, so the cost is bookkeeping, not compute. Justified by the 0-resumes-in-51-campaigns audit, but it is nominally a capability regression.

**Do not use `hybrid` or `qnehvi` for any before/after picker comparison** — both are non-reproducible run-to-run in the same venv, even at 20 rows. Use `budget_sob`, the only reproducible picker. See `wiki/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md`.
