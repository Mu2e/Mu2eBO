"""Headless driver: run the BO iteration graph once, no checkpointer.
Spawned per child by graph/pool.py's run_rolling; also used for one-off
chains. Usage:
  python -m graph.run --thread-id smoke001 --config-name graphsmoke001
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

# Load .env before any langchain/langgraph import so tracing picks it up.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# MUST precede `from build import ...` / `from runtime import ...`: both
# resolve AUTORESEARCH_MODE at import time
# (core/modes.py::stamp_mode_from_argv); the return value becomes --mode's
# argparse default, so args.mode IS the resolved mode.
import modes as _modes  # noqa: E402
_MODE = _modes.stamp_mode_from_argv()

from build import build_graph  # noqa: E402
from paths import GRAPH_DATA  # noqa: E402
from runtime import (  # noqa: E402
    DEFAULT_ALPHA,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=_MODE,
                    help="optimization line; defaults to AUTORESEARCH_MODE "
                         "if set, else modes.DEFAULT_MODE")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--config-name", default=None,
                    help="if omitted, auto-incremented from leaderboard")
    ap.add_argument("--thread-id", default=None,
                    help="if omitted, a fresh uuid is used")
    ap.add_argument("--x-point", default=None,
                    help="comma-separated forced x (e.g. '0.587,304.77,198.91,94.17'). "
                         "Skips BO propose and uses this point directly.")
    args = ap.parse_args()
    # Loud, cheap: a CLI/env-stamp/_SPEC/pipeline.MODE mode mismatch is
    # otherwise SILENT (wiki/incidents/events-per-job-mid-flight-edit.md).
    _modes.assert_mode_stamped(args.mode)

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)

    # No checkpointer: 51 campaigns audited, 0 resumes ever, 5 incidents
    # caused (wiki/incidents/sqlite-wal-corrupt-after-kill.md blocked a
    # restart outright). Resume's useful half survives via
    # graph/pool.py::_default_pick_source.
    graph = build_graph().compile()

    thread_id = args.thread_id or f"cli-{uuid.uuid4().hex[:8]}"
    # langgraph 1.2.9 has no practical cap, but 0.2.50 (ana_v2.8.0 pyenv
    # candidate) defaults to 25; the chain is ~8 supersteps plus up to
    # MAX_PROPOSE_RETRIES re-proposes, so 100 covers it with margin.
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    init = {
        "mode": args.mode,
        "alpha": args.alpha,
    }
    if args.config_name:
        init["config_name"] = args.config_name
    if args.x_point:
        init["x_point"] = [float(v) for v in args.x_point.split(",")]

    print(f"[run] thread_id={thread_id}", flush=True)
    expected_name = args.config_name
    final = None
    for ev in graph.stream(init, cfg, stream_mode="values"):
        final = ev
        # Config-name swap guard, unreachable now (no checkpointer); kept as
        # cheap insurance against a silent wrong-name leaderboard row
        # (wiki/incidents/closed-loop-thread-id-checkpoint-collision.md).
        if expected_name is not None:
            got = ev.get("config_name")
            if got is not None and got != expected_name:
                raise RuntimeError(
                    f"[run] FATAL config_name swapped: expected={expected_name!r} "
                    f"got={got!r} thread_id={thread_id!r}"
                )
        keys = [k for k in ("config_name", "preflight", "objective") if k in ev]
        snap = {k: ev[k] for k in keys}
        print(f"[run] {json.dumps(snap)}", flush=True)
    print(f"[run] done. final keys: {sorted((final or {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
