"""A campaign over a study on the contract engine: q children in flight
through graph/pool.py's rolling pool, each child one `graph.run`
point, picks from surrokit through core/botorch_predict.py.
  python -m graph.closed_loop --study branin --q 2 --max-evals 8 --picker budget_sob --name-prefix brn
contract.launch_problems must pass before anything launches. To stop
launching, touch GRAPH_DATA/<name-prefix>/STOP; running children drain.
--check-only: run every check, print OK, launch nothing (exit 0; a refusal
is exit 2 as without it).
"""
from __future__ import annotations

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import modes as _modes  # noqa: E402
import paths  # noqa: E402
from boards import board_for  # noqa: E402
from campaign_dir import CampaignBusy, CampaignDir  # noqa: E402
from contract import EXECUTORS, KitSet, launch_problems, launch_stagger  # noqa: E402
from point_dir import BROKEN, PointDir  # noqa: E402
from pool import child_name, next_free_name, run_rolling  # noqa: E402
from run import line_buffered_stdout, parse_context, refuse  # noqa: E402


CL = "closed_loop"               # the tag of its refusals (run.refuse)


def point_dir(name: str) -> PointDir:
    return PointDir.of(paths.GRID_DATA_ROOT, name)


def busy_reason(name: str, board_names: set) -> str | None:
    """Why `name` must not be launched again, or None if it is free. A row
    or broken.txt means a prior run RESOLVED it; point.json or a
    *_cluster.txt means a child under it may still be IN FLIGHT (a runner
    killed while its children run). Launching it again would submit the
    same <config>.<step> names from two children."""
    if name in board_names:
        return ("already has a leaderboard row from a prior run under this "
                "--name-prefix")
    pd = point_dir(name)
    sd = pd.state
    if pd.broken() is not None:
        return (f"already carries {pd.path(BROKEN)} from a prior run under "
                f"this --name-prefix")
    if pd.started():
        return (f"has state in {sd}: a child under this name is in flight or "
                f"was abandoned. Advancing to the next index. RECOVERY: "
                f"relaunch under another --name-prefix. Removing {sd} is safe "
                f"only once nothing runs it (`flock -n {sd}/run.lock true` "
                f"succeeds) AND it never held a *_cluster.txt (nothing was "
                f"submitted): the name would be re-picked with a new x, and "
                f"the kit refuses the same <config>.<step> handle with other "
                f"params")
    return None


def make_pick_source(study, name_prefix, pick):
    """next_pick for pool.run_rolling. `pick(round_idx, picker, x_pending)`
    returns one x; the board is read once per process."""
    counter = {"i": 0}
    seen = {}

    def next_pick(picker, x_pending):
        if "board" not in seen:
            seen["board"] = {p.cfg for p in board_for(study).load()}
        name, i = next_free_name(
            name_prefix, counter["i"],
            lambda n: busy_reason(n, seen["board"]),
            log=lambda m: print(m, flush=True),
            summary_hint="Reasons as logged above -- see "
                         "graph/closed_loop.py::busy_reason.")
        counter["i"] = i + 1
        return pick(i, picker, x_pending), name
    return next_pick


def surrokit_pick(study):
    """One pick per launch, seeded 42 ^ round_idx (botorch_predict._seed)."""
    def pick(round_idx, picker, x_pending):
        import botorch_predict as bp
        picks = bp.compute_explore_picks(study.name, q=1, round_idx=round_idx,
                                         picker=picker,
                                         x_pending=x_pending or None)
        return [float(v) for v in picks[0]]
    return pick


def make_run_child(study, campaign, context_args, executor, parallel):
    """Popen `graph.run` and WAIT: the wait is the barrier."""
    def run_child(name, x):
        logs = paths.GRAPH_DATA / "closed_loop_logs"
        logs.mkdir(parents=True, exist_ok=True)
        # "--x=" form: argparse reads "--x -3.2,..." as a flag, not a value.
        cmd = [sys.executable, "-u", "-m", "graph.run", "--study",
               study.name, "--config", name, "--campaign", campaign,
               "--x=" + ",".join(repr(float(v)) for v in x)]
        for pair in context_args:
            cmd += ["--context", pair]
        cmd += ["--executor", executor]
        if parallel is not None:
            cmd += ["--parallel", str(parallel)]
        with open(logs / f"{name}.log", "w") as fh:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                    cwd=str(paths.REPO_ROOT))
        return proc.wait()
    return run_child


def soft(log=print):
    """Wrap a campaign-record write so a failure (a full quota) is logged
    once, loudly, and the campaign goes on: the record decides nothing."""
    warned = set()

    def wrap(fn, what):
        def call(*args):
            try:
                fn(*args)
            except OSError as exc:
                if what not in warned:
                    warned.add(what)
                    log(f"[closed_loop] WARNING: campaign record not written "
                        f"({what}: {exc}); the campaign goes on")
        return call
    return wrap


def main(argv=None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
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
    ap.add_argument("--executor", choices=EXECUTORS, default="grid",
                    help="where the jobs run; recorded in point.json, and a "
                         "rerun must use the same one; passed to every child")
    ap.add_argument("--parallel", type=int, default=None,
                    help="jobs at once on this node, with --executor local "
                         "only (1..16); passed to every child")
    ap.add_argument("--check-only", action="store_true",
                    help="run every launch check, print OK and exit 0 "
                         "without launching anything")
    args = ap.parse_args(argv_list)

    if args.study not in _modes.STUDIES:
        return refuse(f"unknown study {args.study!r}; known "
                      f"{sorted(_modes.STUDIES)} (studies under "
                      f"mode_specs/archive/ are not loaded)", CL)
    study = _modes.STUDIES[args.study]
    if not study.knobs:
        return refuse(f"study {args.study!r} has no knobs: there is "
                      f"nothing to pick; run graph.run", CL)
    if len(study.objectives) < 2 and args.picker != "qlnei":
        # qnehvi/hybrid need two objectives and budget_sob a constraint;
        # surrokit refuses only once rows exist, after grid time is spent.
        return refuse(f"study {args.study!r} has one objective; use "
                      f"--picker qlnei (it optimizes the primary objective), "
                      f"not {args.picker!r}", CL)
    try:
        # Once here, not by every child refusing until the pool aborts.
        parse_context(args.context, study)
    except ValueError as exc:
        return refuse(str(exc), CL)
    kits = KitSet(args.name_prefix, executor=args.executor,
                 parallel=args.parallel)
    try:
        # The first child's name, as next_free_name gives it when nothing is
        # busy: the prefix plus the suffix the pool adds. A later index
        # changes only digits, so one name covers them all.
        problems = launch_problems(
            study, kits, executor=args.executor, parallel=args.parallel,
            config_names=[child_name(args.name_prefix, 0)],
            board=board_for(study))
    finally:
        kits.close()
    if problems:
        for problem in problems:
            refuse(problem, CL)
        return 2
    if args.check_only:
        print(f"[closed_loop] OK: would launch study={study.name} q={args.q} "
              f"max_evals={args.max_evals} prefix={args.name_prefix} "
              f"board={board_for(study).path} executor={args.executor}",
              flush=True)
        return 0
    stagger = launch_stagger(study) if args.stagger is None else args.stagger
    camp = CampaignDir(paths.GRAPH_DATA, args.name_prefix)
    record = {"prefix": args.name_prefix, "study": study.name,
              "args": argv_list, "q": args.q, "max_evals": args.max_evals,
              "picker": args.picker, "executor": args.executor,
              "parallel": args.parallel, "context": list(args.context),
              "stagger": stagger, "host": socket.gethostname(),
              "pid": os.getpid(), "started": time.time()}
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(camp.start(record))
        except CampaignBusy as exc:
            return refuse(str(exc), CL)
        except OSError as exc:
            return refuse(f"cannot write the campaign record: {exc}", CL)
        recorded = soft(lambda m: print(m, flush=True))
        rc = 1
        try:
            print(f"[closed_loop] study={study.name} q={args.q} "
                  f"max_evals={args.max_evals} picker={args.picker} "
                  f"prefix={args.name_prefix} board={board_for(study).path} "
                  f"stagger={stagger:g}s executor={args.executor}",
                  flush=True)
            append = recorded(camp.append_outcome, "outcome")
            result = run_rolling(
                picker=args.picker, q=args.q, max_evals=args.max_evals,
                run_child=make_run_child(study, args.name_prefix,
                                         args.context, args.executor,
                                         args.parallel),
                next_pick=make_pick_source(study, args.name_prefix,
                                           surrokit_pick(study)),
                stop_flag=camp.stopping,
                row_landed=lambda name: name in {
                    p.cfg for p in board_for(study).load()},
                broken=lambda name: point_dir(name).broken() is not None,
                stagger=stagger,
                on_outcome=lambda oc: append(
                    {**oc._asdict(), "x": [float(v) for v in oc.x],
                     "time": time.time()}))
            tally = Counter(oc.reason for oc in result["outcomes"])
            print(f"[closed_loop] done: launched={result['launched']} "
                  f"rows={result['rows']} aborted={result['aborted']} | "
                  + ", ".join(f"{k}={n}" for k, n in sorted(tally.items())),
                  flush=True)
            rc = 1 if result["aborted"] else 0
            return rc
        finally:
            recorded(camp.finish, "finish")(rc)


if __name__ == "__main__":
    line_buffered_stdout()
    raise SystemExit(main())
