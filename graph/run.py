"""One point of a study on the contract engine; graph/closed_loop.py spawns
one per child. By hand:
  python -m graph.run --study branin --config brn001 --campaign brn --x=-1.5,2.25
(Write --x=... : argparse reads "--x -1.5,..." as a flag.)
A study with no knobs runs once, with no --x:
  python -m graph.run --study prodtools_smoke --config smoke01 --campaign smoke --executor local
Exit 0: the point ran (a leaderboard row, or broken.txt saying why not).
Exit 2: refused before anything ran. Anything else: a crash.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import modes as _modes  # noqa: E402
from boards import board_for  # noqa: E402
from contract import EXECUTORS, KitSet, launch_problems  # noqa: E402
from paths import GRID_DATA_ROOT  # noqa: E402
from study_graph import PointMismatch, build_study_graph, check_x  # noqa: E402


def refuse(message: str) -> int:
    print(f"[run] REFUSED: {message}", flush=True)
    return 2


def line_buffered_stdout() -> None:
    """An operator launches a runner with stdout sent to a log file, where
    print() is block-buffered: without this, [steps] and [pool] lines reach
    the log only when the process exits, so a live campaign's parent log
    looks silent. Called by both entry points; the children graph.closed_loop
    launches already run under `python -u`."""
    sys.stdout.reconfigure(line_buffering=True)


def local_env_refusal() -> str | None:
    """AUTORESEARCH_LOCAL was the deleted pipeline's grid-free activation
    switch (wiki/drivers/local-executor.md); nothing in the engine reads it
    any more. A stale export must not be silently ignored -- the engine's
    grid-free equivalent is `--executor local`."""
    if "AUTORESEARCH_LOCAL" in os.environ:
        return (f"AUTORESEARCH_LOCAL={os.environ['AUTORESEARCH_LOCAL']!r} is "
                f"set, but nothing reads it any more (it was the deleted "
                f"pipeline's grid-free activation switch); unset it and use "
                f"--executor local instead")
    return None


def parse_context(pairs, study) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"--context {pair!r}: expected name=value")
        if key not in study.context:
            raise ValueError(f"--context {key!r}: study {study.name!r} "
                             f"declares context {list(study.context)}")
        out[key] = float(value)
    missing = [c for c in study.context if c not in out]
    if missing:
        raise ValueError(f"study {study.name!r} needs --context for {missing}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--config", required=True,
                    help="the point's name; state in <GRID_DATA_ROOT>/<config>/state")
    ap.add_argument("--campaign", required=True,
                    help="groups the kit trace: GRAPH_DATA/<campaign>/kit_trace.jsonl")
    ap.add_argument("--x", default=None,
                    help="comma-separated knob values, in the study's knob "
                         "order; omit it for a study with no knobs")
    ap.add_argument("--context", action="append", default=[],
                    help="name=value for each leaderboard.context value")
    ap.add_argument("--executor", choices=EXECUTORS, default="grid",
                    help="where the jobs run; recorded in point.json, and a "
                         "rerun must use the same one")
    ap.add_argument("--parallel", type=int, default=None,
                    help="jobs at once on this node, with --executor local "
                         "only (1..16)")
    args = ap.parse_args(argv)

    removed = local_env_refusal()
    if removed:
        return refuse(removed)

    if args.study not in _modes.STUDIES:
        return refuse(f"unknown study {args.study!r}; known "
                      f"{sorted(_modes.STUDIES)} (studies under "
                      f"mode_specs/archive/ are not loaded)")
    study = _modes.STUDIES[args.study]
    try:
        if not study.knobs:
            if args.x is not None:
                return refuse(f"study {study.name!r} has no knobs; drop --x")
            x = []
        elif args.x is None:
            return refuse(f"study {study.name!r} has knobs "
                          f"{list(study.knob_names)}; pass --x=<values>")
        else:
            x = [float(v) for v in args.x.split(",")]
        check_x(study, x)
        context = parse_context(args.context, study)
    except ValueError as exc:
        return refuse(str(exc))
    state_dir = GRID_DATA_ROOT / args.config / "state"
    broken = state_dir / "broken.txt"
    if broken.exists():
        return refuse(f"{broken} exists: this point already failed "
                      f"({broken.read_text().strip()}). To retry it, delete "
                      f"{broken}: the rerun adopts the steps already "
                      f"submitted, so a step the kit itself reported failed "
                      f"stays failed (its handle <config>.<step> names the "
                      f"same job). To evaluate this x again from scratch, "
                      f"use a new config name")

    # A retried point adopts the steps it finished (scheduler.run_steps reads
    # the same files), so the board check must use the versions they ran under.
    adopted = {}
    for step in study.steps:
        path = state_dir / f"{step.step}_results.json"
        if path.exists():
            adopted[step.step] = json.loads(path.read_text())

    kits = KitSet(args.campaign, executor=args.executor,
                 parallel=args.parallel)
    try:
        # The launch check starts every kit through the KitSet the steps
        # reuse: a kit that won't start, or a step it rejects, is the
        # environment or the study, not this point, so it is refused before
        # anything is written rather than recorded in broken.txt.
        problems = launch_problems(
            study, kits, executor=args.executor, parallel=args.parallel,
            config_names=[args.config],
            board=board_for(study), adopted=adopted)
        if problems:
            return refuse("; ".join(problems))
        graph = build_study_graph(
            study, config=args.config, campaign=args.campaign,
            context=context, kits=kits, state_dir=state_dir,
            board=board_for(study), executor=args.executor).compile()
        graph.invoke({"config_name": args.config, "x_point": x})
    except PointMismatch as exc:
        return refuse(str(exc))
    finally:
        kits.close()
    return 0


if __name__ == "__main__":
    line_buffered_stdout()
    raise SystemExit(main())
