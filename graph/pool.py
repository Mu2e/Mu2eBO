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

run_child / next_pick / stop_flag / renew / row_landed / broken are injected
callables. That is the test seam: tests pass fakes and never touch grid,
sqlite, or a subprocess.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def _should_abort(streak: int, q: int) -> bool:
    """MORE THAN q-1 consecutive rowless resolutions -- i.e. at least
    max(q, 2) in a row.

    At q=1, "streak >= q" would abort a campaign on its very first failure
    (that resolution IS the whole streak so far -- zero corroborating
    evidence of "systemically broken"). At q>1, max(q, 2) == q, matching
    the original intent exactly: "a full pool's worth of consecutive
    failures" (the rolling-no-row-streak-false-increment guard, restated
    for a design with no wave baseline to misattribute a row against).
    Extracted as a pure function so the threshold is unit-testable without
    simulating pool concurrency -- see tests/test_pool.py::TestAbortThreshold.
    """
    return streak >= max(q, 2)


def run_rolling(mode, picker, q, max_evals, alpha, name_prefix,
                run_child=None, next_pick=None, stop_flag=None, renew=None,
                row_landed=None, broken=None, log=print, stagger=None):
    """Keep q children in flight until max_evals launched and the pool drains.

    Returns {"launched", "rows", "outcomes", "aborted"}.

    Aborts per `_should_abort` -- the guard that used to need name-based
    wave accounting. Here each child's own outcome is read at the moment it
    resolves, so a row cannot be absorbed into a neighbouring wave's
    baseline.

    `stagger` seconds separate consecutive launches (not before the first
    one): concurrent mu2ejobsub submissions within ~10s are known to race
    (wiki/incidents/concurrent-token-contention.md, which measured 60-90s as
    safe). Defaults to `config.CLOSED_LOOP_STAGGER_SEC` when omitted; tests
    pass `stagger=0` so the suite doesn't sleep.
    """
    run_child = run_child or _default_run_child(mode, alpha)
    next_pick = next_pick or _default_pick_source(name_prefix)
    stop_flag = stop_flag or (lambda: False)
    renew = renew or (lambda: None)
    row_landed = row_landed or _default_row_landed
    broken = broken or _default_broken
    if stagger is None:
        from config import CLOSED_LOOP_STAGGER_SEC  # Task 4 folds config.py into core/paths.py
        stagger = CLOSED_LOOP_STAGGER_SEC

    inflight = {}
    launched = 0
    rows = 0
    streak = 0
    aborted = False
    outcomes = []

    def _resolve_one(fut):
        """Pop one resolved future -> Outcome, with a per-child log line
        regardless of which site (main loop or drain) calls this -- the
        drain used to omit it, so an abort's abandoned children (up to
        q-1 of them) produced no diagnostics at exactly the moment an
        operator most needs them."""
        name, x = inflight.pop(fut)
        try:
            rc = fut.result()
        except Exception as exc:  # noqa: BLE001
            rc = 1
            log(f"[pool] {name} raised: {exc}")
        oc = classify(name, x, rc, mode, row_landed(name, mode), broken(name))
        log(f"[pool] {name}: {oc.reason}")
        return oc

    with ThreadPoolExecutor(max_workers=q) as poolx:
        while (launched < max_evals or inflight) and not aborted:
            while (len(inflight) < q and launched < max_evals
                   and not stop_flag() and not aborted):
                if launched > 0 and stagger:
                    time.sleep(stagger)
                renew()
                x, name = next_pick(mode, picker,
                                    [v for _, v in inflight.values()])
                inflight[poolx.submit(run_child, name, x)] = (name, x)
                launched += 1
                log(f"[pool] launched {name} ({launched}/{max_evals}), "
                    f"in_flight={len(inflight)}")
            if not inflight:
                break
            oc = _resolve_one(next(as_completed(list(inflight))))
            outcomes.append(oc)
            if oc.row_landed:
                rows += 1
                streak = 0
            else:
                streak += 1
                log(f"[pool] {oc.name}: no-row streak {streak}/{max(q, 2)}")
            if _should_abort(streak, q):
                aborted = True
                log(f"[pool] ABORT: {streak} consecutive resolutions with "
                    f"no row (>= {max(q, 2)})")
        # Drain: never exit with work in flight. This is the structural fix
        # for closed-loop-final-round-orphan-children. Uses the SAME
        # _resolve_one helper as the main loop, so an abort's abandoned
        # children still get a per-child log line.
        for fut in as_completed(list(inflight)):
            oc = _resolve_one(fut)
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
    round-seed. Imports closed_loop lazily -- closed_loop imports pool.

    Skips any candidate name already resolved by an EARLIER process --
    present in the leaderboard, or carrying broken.txt. Relaunching under
    the same --name-prefix is the STANDARD recovery move in this project;
    without this skip, a fresh in-process counter starting at i=0 collides
    with the prior run's names, and _default_row_landed/_default_broken then
    read the OLD run's outcome (a leaderboard row, a broken.txt) as if it
    belonged to the NEW child -- reporting the wrong campaign's success or
    failure. See Task 3 review round 2, CRITICAL 1.
    """
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        import closed_loop as cl
        i = counter["i"]
        lb_names = cl._leaderboard_names(mode)
        name = f"{name_prefix}R{i:02d}_00"
        while name in lb_names or cl._child_is_broken(name):
            print(f"[pool] {name} already resolved (leaderboard row or "
                  f"broken.txt) from a PRIOR run under this --name-prefix "
                  f"-- skipping to avoid reporting its outcome as this "
                  f"child's", flush=True)
            i += 1
            name = f"{name_prefix}R{i:02d}_00"
        counter["i"] = i + 1
        picks = cl._botorch_picks_subprocess(mode, q=1, round_idx=i,
                                             picker=picker, pending=x_pending)
        return list(picks[0]), name
    return next_pick


def _default_row_landed(name, mode):
    import bo_driver as bo  # noqa: WPS433
    if mode not in bo.MODES:
        # `mode` is unregistered in bo_driver.MODES -- e.g. tests/test_pool.py's
        # synthetic mode="m". Production main() validates --mode against
        # sorted(modes.SPECS) before run_rolling is ever called, so this
        # branch cannot fire for a real campaign. Scoped to exactly this
        # check (not wrapped around the whole leaderboard read) so that a
        # REAL KeyError raised from inside a registered mode's
        # load_history() -- a genuinely broken leaderboard file, say -- is
        # NOT swallowed and turned into "landed": fail-open on the one
        # signal the whole no-row-streak abort guard reads is exactly
        # backwards.
        return True
    import closed_loop as cl
    return name in cl._leaderboard_names(mode)


def _default_broken(name):
    import closed_loop as cl
    return cl._child_is_broken(name)
