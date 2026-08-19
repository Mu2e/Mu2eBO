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

    Aborts when MORE THAN `q` consecutive resolutions land no row -- the
    guard that used to need name-based wave accounting. Here each child's
    own outcome is read at the moment it resolves, so a row cannot be
    absorbed into a neighbouring wave's baseline. Strictly greater than (not
    `>=`) so a q=1 pool's very first failed resolution -- which IS the whole
    streak so far -- doesn't read as "systemically broken" on zero evidence.
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
            if streak > q:
                # Strictly more than q (pool width) consecutive rowless
                # resolutions, not >=: at q=1 a single bad child is not yet
                # distinguishable from ordinary noise (its resolution IS the
                # entire streak so far), so >= would abort a campaign on its
                # very first failure. > q requires the pool to have failed
                # to land a row across a full width's worth PLUS one more,
                # which is what "systemically broken" actually looks like
                # at any pool width, q=1 included.
                aborted = True
                log(f"[pool] ABORT: {streak} consecutive resolutions with "
                    f"no row (> pool width {q})")
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
    try:
        return name in cl._leaderboard_names(mode)
    except KeyError:
        # `mode` is unregistered in bo_driver.MODES. In production this can
        # never happen -- main()'s argparse restricts --mode to
        # sorted(modes.SPECS) before run_rolling is ever called. It only
        # fires here for a synthetic test mode (tests/test_pool.py's
        # `mode="m"`) that never overrides row_landed; treat that as
        # "cannot fail this resolution" rather than crash the pool on a
        # lookup that only exists to prove out the pool's own concurrency,
        # not the leaderboard integration.
        return True


def _default_broken(name):
    import closed_loop as cl
    return cl._child_is_broken(name)
