"""One point of a study on the contract engine; graph/study_loop.py spawns
one per child. By hand:
  python -m graph.study_run --study branin --config brn001 --campaign brn --x=-1.5,2.25
(Write --x=... : argparse reads "--x -1.5,..." as a flag.)
Exit 0: the point ran (a leaderboard row, or broken.txt saying why not).
Exit 2: refused before anything ran. Anything else: a crash.
Phase C renames this to graph.run when the pipeline path is deleted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import kit_registry  # noqa: E402
import modes as _modes  # noqa: E402
from boards import board_for  # noqa: E402
from contract import KitSet  # noqa: E402
from kits import KitError  # noqa: E402
from paths import GRID_DATA_ROOT  # noqa: E402
from study_graph import PointMismatch, build_study_graph, check_x  # noqa: E402


def refuse(message: str) -> int:
    print(f"[study_run] REFUSED: {message}", flush=True)
    return 2


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
    ap.add_argument("--x", required=True,
                    help="comma-separated knob values, in the study's knob order")
    ap.add_argument("--context", action="append", default=[],
                    help="name=value for each leaderboard.context value")
    args = ap.parse_args(argv)

    if args.study not in _modes.STUDIES:
        return refuse(f"unknown study {args.study!r}; known "
                      f"{sorted(_modes.STUDIES)}")
    if args.study not in _modes.ENGINE:
        return refuse(f"study {args.study!r} runs on the pipeline kits; use "
                      f"graph.run / graph.closed_loop until Phase C")
    study = _modes.STUDIES[args.study]
    try:
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

    kits = KitSet(args.campaign)
    try:
        # Start every kit now, through the KitSet the steps reuse: a kit that
        # won't start is the environment, not this point, so it is refused
        # before anything is written rather than recorded in broken.txt.
        for name in sorted(kit_registry.kits_of(study)):
            try:
                kits.get(name).tools
            except (KeyError, KitError) as exc:
                return refuse(f"kit {name!r} did not start, so nothing ran: "
                              f"{exc}")
        graph = build_study_graph(
            study, config=args.config, campaign=args.campaign,
            context=context, kits=kits, state_dir=state_dir,
            board=board_for(study)).compile()
        graph.invoke({"config_name": args.config, "x_point": x})
    except PointMismatch as exc:
        return refuse(str(exc))
    finally:
        kits.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
