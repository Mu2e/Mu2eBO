"""Headless driver: invoke the BO iteration graph once with a SqliteSaver.

Use this when you don't want to run `langgraph dev` — e.g. for a cron-driven
supervisor or a one-off CLI smoke. Studio cannot attach to this checkpoint
DB (Studio reads the dev server's in-memory store), but `graph_app/streamlit_app.py`
will still see the leaderboard rows that this run produces.

Usage:
  source .venv-graph/bin/activate
  python -m graph.run --thread-id smoke001 --config-name graphsmoke001
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# Stamp AUTORESEARCH_MODE BEFORE `from config import ...` — config.GRID_STAGES
# is selected from GRID_STAGES_BY_MODE at module-load time, and build.STAGE_NODES
# freezes it. argparse runs in main(), too late. Shared sniffer: graph/presniff.py.
from presniff import presniff_mode  # noqa: E402

presniff_mode()

# Load .env (LANGSMITH_*, etc.) before any langchain/langgraph import so
# tracing client picks them up. langgraph.json's "env" field is honored only
# by `langgraph dev`; the headless runner needs an explicit load.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

from build import build_graph  # noqa: E402
from config import (  # noqa: E402
    CHECKPOINT_DB,
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRAPH_DATA,
    SQLITE_TIMEOUT_S,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=DEFAULT_MODE)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--config-name", default=None,
                    help="if omitted, auto-incremented from leaderboard")
    ap.add_argument("--thread-id", default=None,
                    help="if omitted, a fresh uuid is used")
    ap.add_argument("--mock", action=argparse.BooleanOptionalAction, default=True,
                    help="use synthetic metrics (Phase 1 default). Pass --no-mock for real grid.")
    ap.add_argument("--x-point", default=None,
                    help="comma-separated forced x (e.g. '0.587,304.77,198.91,94.17'). "
                         "Skips BO propose and uses this point directly.")
    args = ap.parse_args()

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(CHECKPOINT_DB),
        check_same_thread=False,
        timeout=SQLITE_TIMEOUT_S,
    )
    # WAL is persistent per-DB, but set it explicitly so a fresh
    # checkpoints.sqlite (deleted/recreated) doesn't fall back to the
    # default DELETE journal which serializes all writers.
    conn.execute("PRAGMA journal_mode=WAL;")
    saver = SqliteSaver(conn)

    graph = build_graph().compile(checkpointer=saver)

    thread_id = args.thread_id or f"cli-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}}
    init = {
        "mode": args.mode,
        "alpha": args.alpha,
        "mock": args.mock,
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
        # Config-name swap guard: if a stale SqliteSaver checkpoint resumes
        # a different thread's state mid-stream, abort loudly rather than
        # silently writing the wrong row to the leaderboard.
        # See [[closed-loop-thread-id-checkpoint-collision]].
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
