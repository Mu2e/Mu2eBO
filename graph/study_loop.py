"""A campaign over a study on the contract engine: q children in flight
through graph/pool.py's rolling pool, each child one `graph.study_run`
point, picks from surrokit through core/botorch_predict.py.
  python -m graph.study_loop --study branin --q 2 --max-evals 8 --picker budget_sob --name-prefix brn
check_kits must pass before anything launches. To stop launching, touch
GRAPH_DATA/<name-prefix>/STOP; running children drain. Phase C folds this
into graph/closed_loop.py when the pipeline path is deleted.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import modes as _modes  # noqa: E402
import paths  # noqa: E402
from boards import board_for  # noqa: E402
from contract import check_kits, launch_stagger  # noqa: E402
from pool import next_free_name, run_rolling  # noqa: E402
from study_run import parse_context  # noqa: E402


def state_dir(name: str) -> Path:
    return paths.GRID_DATA_ROOT / name / "state"


def busy_reason(name: str, board_names: set) -> str | None:
    """Why `name` must not be launched again, or None if it is free. A row
    or broken.txt means a prior run RESOLVED it; point.json or a
    *_cluster.txt means a child under it may still be IN FLIGHT (a runner
    killed while its children run). Launching it again would submit the
    same <config>.<step> names from two children."""
    if name in board_names:
        return ("already has a leaderboard row from a prior run under this "
                "--name-prefix")
    sd = state_dir(name)
    if (sd / "broken.txt").exists():
        return (f"already carries {sd / 'broken.txt'} from a prior run under "
                f"this --name-prefix")
    if (sd / "point.json").exists() or any(sd.glob("*_cluster.txt")):
        return (f"has state in {sd}: a child under this name is in flight or "
                f"was abandoned. Advancing to the next index. RECOVERY: "
                f"relaunch under another --name-prefix. Removing {sd} is safe "
                f"only once nothing runs it (pgrep -f 'study_run.*{name}') "
                f"AND it never held a *_cluster.txt (nothing was submitted): "
                f"the name would be re-picked with a new x, and the kit "
                f"refuses the same <config>.<step> handle with other params")
    return None


def make_pick_source(study, name_prefix, pick):
    """next_pick for pool.run_rolling. `pick(round_idx, picker, x_pending)`
    returns one x; the board is read once per process, like the pipeline's
    pick source (graph/pool.py::_default_pick_source)."""
    counter = {"i": 0}
    seen = {}

    def next_pick(mode, picker, x_pending):
        if "board" not in seen:
            seen["board"] = {p.cfg for p in board_for(study).load()}
        name, i = next_free_name(
            name_prefix, counter["i"],
            lambda n: busy_reason(n, seen["board"]),
            log=lambda m: print(m, flush=True),
            summary_hint="Reasons as logged above -- see "
                         "graph/study_loop.py::busy_reason.")
        counter["i"] = i + 1
        return pick(i, picker, x_pending), name
    return next_pick


def surrokit_pick(study):
    """One pick per launch, seeded 42 ^ round_idx like the pipeline's."""
    def pick(round_idx, picker, x_pending):
        import botorch_predict as bp
        picks = bp.compute_explore_picks(study.name, q=1, round_idx=round_idx,
                                         picker=picker,
                                         x_pending=x_pending or None)
        return [float(v) for v in picks[0]]
    return pick


def make_run_child(study, campaign, context_args):
    """Popen `graph.study_run` and WAIT: the wait is the barrier."""
    def run_child(name, x):
        logs = paths.GRAPH_DATA / "closed_loop_logs"
        logs.mkdir(parents=True, exist_ok=True)
        # "--x=" form: argparse reads "--x -3.2,..." as a flag, not a value.
        cmd = [sys.executable, "-u", "-m", "graph.study_run", "--study",
               study.name, "--config", name, "--campaign", campaign,
               "--x=" + ",".join(repr(float(v)) for v in x)]
        for pair in context_args:
            cmd += ["--context", pair]
        with open(logs / f"{name}.log", "w") as fh:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                    cwd=str(paths.REPO_ROOT))
        return proc.wait()
    return run_child


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--q", type=int, required=True,
                    help="children kept in flight at once")
    ap.add_argument("--max-evals", type=int, required=True,
                    help="points to launch in total")
    ap.add_argument("--picker", choices=_modes.PICKER_CHOICES,
                    default=_modes.DEFAULT_PICKER)
    ap.add_argument("--name-prefix", required=True,
                    help="child names are {prefix}R{i:02d}_00; also the "
                         "campaign name")
    ap.add_argument("--stagger", type=float, default=None,
                    help="seconds between launches (default: the largest "
                         "launch_stagger_s of the study's kits)")
    ap.add_argument("--context", action="append", default=[],
                    help="name=value, passed to every child")
    args = ap.parse_args(argv)

    if args.study not in _modes.STUDIES:
        print(f"[study_loop] REFUSED: unknown study {args.study!r}; known "
              f"{sorted(_modes.STUDIES)}", flush=True)
        return 2
    if args.study not in _modes.ENGINE:
        print(f"[study_loop] REFUSED: study {args.study!r} runs on the "
              f"pipeline kits; use graph.closed_loop until Phase C", flush=True)
        return 2
    study = _modes.STUDIES[args.study]
    try:
        # Once here, not by every child refusing until the pool aborts.
        parse_context(args.context, study)
    except ValueError as exc:
        print(f"[study_loop] REFUSED: {exc}", flush=True)
        return 2
    problems = check_kits(study, campaign=args.name_prefix)
    if problems:
        for problem in problems:
            print(f"[study_loop] REFUSED: {problem}", flush=True)
        return 2
    stagger = launch_stagger(study) if args.stagger is None else args.stagger
    stop = paths.GRAPH_DATA / args.name_prefix / "STOP"
    print(f"[study_loop] study={study.name} q={args.q} "
          f"max_evals={args.max_evals} picker={args.picker} "
          f"prefix={args.name_prefix} board={board_for(study).path} "
          f"stagger={stagger:g}s", flush=True)
    result = run_rolling(
        mode=study.name, picker=args.picker, q=args.q,
        max_evals=args.max_evals, alpha=None, name_prefix=args.name_prefix,
        run_child=make_run_child(study, args.name_prefix, args.context),
        next_pick=make_pick_source(study, args.name_prefix,
                                   surrokit_pick(study)),
        stop_flag=stop.exists,
        row_landed=lambda name, mode: name in {p.cfg for p in
                                               board_for(study).load()},
        broken=lambda name: (state_dir(name) / "broken.txt").exists(),
        stagger=stagger)
    tally = Counter(oc.reason for oc in result["outcomes"])
    print(f"[study_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']} | "
          + ", ".join(f"{k}={n}" for k, n in sorted(tally.items())),
          flush=True)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
