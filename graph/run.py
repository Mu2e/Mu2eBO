"""Headless driver: invoke the BO iteration graph once, no checkpointer.

This is the standard entrypoint (the `langgraph dev` Studio/Streamlit overlay
was retired 2026-07-17) — used directly for one-off chains and spawned per
child by graph/pool.py's run_rolling (graph/closed_loop.py's parent).

Usage:
  source .venv/bin/activate
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

# Load .env (LANGSMITH_*, etc.) before any langchain/langgraph import so the
# tracing client picks them up.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# MUST precede `from build import ...` / `from runtime import ...`: both
# core/runtime.py (_SPEC) and core/pipeline.py (MODE) resolve the process's
# mode from AUTORESEARCH_MODE at IMPORT time and cannot be re-pointed later,
# so without this the child runs whichever mode the fallbacks land on --
# which, before this stamp was restored, was `foilspf` for runtime and
# `foilsflash` for pipeline no matter what --mode said. Replaces the deleted
# graph/presniff.py; see core/modes.py::stamp_mode_from_argv for why the
# "all live specs are identical today" argument that deleted it does not
# hold as a code invariant. main() re-checks with assert_mode_stamped().
import modes as _modes  # noqa: E402
_modes.stamp_mode_from_argv()

from build import build_graph  # noqa: E402
from paths import GRAPH_DATA  # noqa: E402
from runtime import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_MODE,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=DEFAULT_MODE)
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--config-name", default=None,
                    help="if omitted, auto-incremented from leaderboard")
    ap.add_argument("--thread-id", default=None,
                    help="if omitted, a fresh uuid is used")
    ap.add_argument("--x-point", default=None,
                    help="comma-separated forced x (e.g. '0.587,304.77,198.91,94.17'). "
                         "Skips BO propose and uses this point directly.")
    args = ap.parse_args()
    # Loud, cheap: a mode disagreement between the CLI, the env stamp,
    # runtime._SPEC and pipeline.MODE is otherwise SILENT -- the grid just
    # quietly runs another mode's events_per_job / njobs / grid tarball /
    # stage chain, which is a metric denominator error with no error surface
    # (wiki/incidents/events-per-job-mid-flight-edit.md).
    _modes.assert_mode_stamped(args.mode)

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)

    # No checkpointer. Audited 51 campaigns: 44 clean, 7 died mid-flight, 0
    # ever resumed from a checkpoint -- while it CAUSED 5 incidents, and in
    # sqlite-wal-corrupt-after-kill it blocked the restart outright. The
    # useful half of resume -- not relaunching a config a prior run already
    # resolved, and not launching a second child on top of one whose grid
    # work is still in flight -- survives this: graph/pool.py's
    # _default_pick_source skips any candidate name with a leaderboard row,
    # a broken.txt, a *_cluster.txt or an unresolved pending row (Task 3
    # review round 2 CRITICAL 1; final review C1). That is what actually
    # matters for the standard recovery move (relaunch under the same
    # --name-prefix), since that's a fresh `python -m graph.closed_loop`
    # invocation, not a resumed `python -m graph.run` thread_id.
    graph = build_graph().compile()

    thread_id = args.thread_id or f"cli-{uuid.uuid4().hex[:8]}"
    # Pinned, not left to the library default: langgraph 1.2.9 has no
    # practical cap but 0.2.50 (the ana_v2.8.0 pyenv candidate) defaults to
    # 25. The child chain is ~8 supersteps plus up to MAX_PROPOSE_RETRIES
    # re-proposes; 100 is far above that and far below anything runaway.
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
        # Config-name swap guard. UNREACHABLE as written: it existed for
        # closed-loop-thread-id-checkpoint-collision, where a stale
        # SqliteSaver checkpoint resumed a different thread's state
        # mid-stream and the wrong row went to the leaderboard -- and there
        # is no checkpointer any more (retired 2026-08-19), so nothing can
        # inject another config_name into this stream. KEPT DELIBERATELY as
        # cheap insurance: it is one string compare per superstep, and the
        # failure it catches (a leaderboard row under the wrong name) is
        # both silent and unrecoverable. Do not read its presence as
        # evidence that a resume mechanism still exists.
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
