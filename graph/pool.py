"""The parent rolling work-pool: q children in flight, replenish on resolve.

A child resolves when its SUBPROCESS EXITS -- the single resolution truth
source; *_cluster.txt survives only as the runner's LAUNCH-time
double-launch guard (graph/closed_loop.py busy_reason). Retired-by-design
(wiki/incidents/): barrier-false-positive-round1,
closed-loop-barrier-timeout-zero-rows-falsepos,
closed-loop-final-round-orphan-children, rolling-no-row-streak-false-increment.
The caller (graph/closed_loop.py) supplies the run_child/next_pick/row_landed/
broken callables and the stagger; stop_flag is optional. They are also the
test seam. Nothing here renews credentials: a grid campaign whose kit needs
Kerberos is refused at launch unless the ticket has 4 h left
(contract.launch_problems, which graph/closed_loop.py runs before the pool
starts).
"""
from __future__ import annotations

import sys
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from concurrent.futures import as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from campaign_dir import child_name  # noqa: E402,F401  (THE child-name shape)

Outcome = namedtuple("Outcome", "name x rc row_landed broken reason")

# Heartbeat cadence: 15 min so a q=20 launch (30 min of 90 s stagger before
# the first possible resolution) is never silent long, yet multi-day campaign
# logs stay readable. Diagnostic only (see _log_inflight).
HEARTBEAT_S = 15 * 60

# In-flight age that upgrades the heartbeat to a WARNING: 24 h is past every
# normal stage duration. Since prodtools jobwait has no internal timeout, this
# WARNING and the closed-loop barrier are the only signals a child is stuck.
STALL_WARN_S = 24 * 3600

# Busy-name skips logged in full before summarising as a count: each SKIP
# line carries a multi-line recovery recipe, so an uncapped loop floods the log.
SKIP_LOG_LIMIT = 5


def _log_inflight(inflight, log, now=None, warn_after=STALL_WARN_S):
    """One heartbeat line: what is in flight and for how long.

    REPORT-ONLY: never resolves, abandons or aborts a child (a DECIDING
    timeout is wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md);
    without it a hung child (wiki/incidents/harvest-pyroot-nfs-rpc-hang.md,
    wiki/incidents/poll-deadlock-missing-outstage-dirs.md) freezes the log.
    """
    now = time.time() if now is None else now
    ages = sorted((now - t0, name) for name, _x, t0 in inflight.values())
    summary = ", ".join(f"{name} {age / 3600:.1f}h" for age, name in ages)
    log(f"[pool] heartbeat: {len(inflight)} in flight ({summary})")
    for age, name in ages:
        if age < warn_after:
            break
        log(f"[pool] WARNING {name} has been in flight {age / 3600:.1f}h "
            f"(> {warn_after / 3600:.0f}h). Nothing is being resolved or "
            f"abandoned on its account -- the parent waits for its "
            f"subprocess to exit, by design. To investigate: its "
            f"<grid>/{name}/state/run.lock (`flock -n` on it fails while "
            f"the child runs), its log under "
            f"closed_loop_logs/{name}.log, and `jobsub_q -G mu2e "
            f"--user=$USER`. If you kill it, do NOT relaunch it under the "
            f"same --name-prefix: `state/point.json` or `*_cluster.txt` "
            f"still marks {name} busy (graph/closed_loop.py::busy_reason), "
            f"and the kit refuses the same <config>.<step> handle with "
            f"other params. Relaunch under another --name-prefix instead.")


def _wait_one(inflight, log, heartbeat=HEARTBEAT_S):
    """Block until one future resolves; the timeout drives heartbeat logging
    only, never an early return."""
    while True:
        try:
            return next(as_completed(list(inflight), timeout=heartbeat))
        except _FutureTimeout:
            _log_inflight(inflight, log)


def classify(name, x, rc, row_landed, broken) -> Outcome:
    """Exit code plus artifacts decide the outcome. No polling. A landed row
    counts whatever the rc: the point is on the board, so the child must
    not add to the no-row streak."""
    if row_landed:
        return Outcome(name, x, rc, True, False,
                       "ok" if rc == 0 else f"row landed but child rc={rc}")
    if broken:
        return Outcome(name, x, rc, False, True, "broken")
    if rc != 0:
        return Outcome(name, x, rc, False, False, f"child rc={rc}")
    return Outcome(name, x, rc, False, False, "exit 0 but no leaderboard row")


def _should_abort(streak: int, q: int) -> bool:
    """Abort at max(q, 2) consecutive rowless resolutions: at q=1 a bare
    `streak >= q` would abort on the very first failure. Restates the
    wiki/incidents/rolling-no-row-streak-false-increment.md guard for a
    design with no wave baseline to misattribute a row against."""
    return streak >= max(q, 2)


def run_rolling(picker, q, max_evals, *, run_child, next_pick, row_landed,
                broken, stagger, stop_flag=None, log=print,
                heartbeat=HEARTBEAT_S, on_outcome=None):
    """Keep q children in flight until max_evals launched and the pool drains.

    Returns {"launched", "rows", "outcomes", "aborted"}. `stagger` separates
    launches: concurrent mu2ejobsub within ~10s races
    (wiki/incidents/concurrent-token-contention.md measured 60-90s safe).
    `heartbeat` is REPORT-ONLY -- never resolves/abandons (_log_inflight).
    `on_outcome(oc)`, if given, sees each Outcome once it is logged, in the
    main loop and the drain alike (graph/closed_loop.py records it).

    Failures never hide a drain. A raise in the main loop (next_pick --
    budget_sob refusing to pick, core/botorch_predict.py -- or stop_flag)
    stops launching and is logged as FATAL at once; the children in flight
    then drain as usual, and only then is it raised again. A raise from
    row_landed/broken for one child becomes that child's Outcome; one from
    on_outcome is logged. Neither stops the pool.
    """
    stop_flag = stop_flag or (lambda: False)

    inflight = {}   # future -> (name, x, launch timestamp)
    launched = 0
    rows = 0
    streak = 0
    aborted = False
    outcomes = []
    failure = None

    def _resolve_one(fut):
        """Pop one resolved future -> Outcome, logging per child from main
        loop and drain alike, whatever the checks or on_outcome raise."""
        name, x, _t0 = inflight.pop(fut)
        try:
            rc = fut.result()
        except Exception as exc:  # noqa: BLE001
            rc = 1
            log(f"[pool] {name} raised: {exc}")
        try:
            oc = classify(name, x, rc, row_landed(name), broken(name))
        except Exception as exc:  # noqa: BLE001
            # Fail closed: a row nobody could see is not counted, so the
            # child adds to the no-row streak like any rowless exit.
            oc = Outcome(name, x, rc, False, False,
                         f"outcome unknown: {type(exc).__name__}: {exc}")
        log(f"[pool] {name}: {oc.reason}")
        if on_outcome is not None:
            try:
                on_outcome(oc)
            except Exception as exc:  # noqa: BLE001
                log(f"[pool] WARNING: on_outcome raised for {name} "
                    f"({type(exc).__name__}: {exc}); the pool goes on")
        return oc

    with ThreadPoolExecutor(max_workers=q) as poolx:
        try:
            while (launched < max_evals or inflight) and not aborted:
                while (len(inflight) < q and launched < max_evals
                       and not stop_flag() and not aborted):
                    if launched > 0 and stagger:
                        time.sleep(stagger)
                    x, name = next_pick(picker,
                                        [v for _, v, _t in inflight.values()])
                    inflight[poolx.submit(run_child, name, x)] = (name, x,
                                                                  time.time())
                    launched += 1
                    log(f"[pool] launched {name} ({launched}/{max_evals}), "
                        f"in_flight={len(inflight)}")
                if not inflight:
                    break
                oc = _resolve_one(_wait_one(inflight, log, heartbeat))
                outcomes.append(oc)
                if oc.row_landed:
                    rows += 1
                    streak = 0
                else:
                    streak += 1
                    log(f"[pool] {oc.name}: no-row streak "
                        f"{streak}/{max(q, 2)}")
                if _should_abort(streak, q):
                    aborted = True
                    log(f"[pool] ABORT: {streak} consecutive resolutions "
                        f"with no row (>= {max(q, 2)})")
        except Exception as exc:  # noqa: BLE001
            # Leaving the with-block on this raise would wait in the
            # executor's __exit__ for every child in flight -- silently, for
            # hours on the grid -- and print the error only at the end.
            failure = exc
            log(f"[pool] FATAL: {type(exc).__name__}: {exc} -- launching "
                f"nothing more; draining {len(inflight)} in flight first "
                f"(this has NOT hung), then raising it")
        # Drain: never exit with work in flight -- the structural fix for
        # wiki/incidents/closed-loop-final-round-orphan-children.md. Same
        # _resolve_one/_wait_one, so an abort/STOP/FATAL drain still logs
        # per child under the heartbeat.
        while inflight:
            oc = _resolve_one(_wait_one(inflight, log, heartbeat))
            outcomes.append(oc)
            if oc.row_landed:
                rows += 1
    if failure is not None:
        raise failure
    return {"launched": launched, "rows": rows,
            "outcomes": outcomes, "aborted": aborted}


# --- child names ----------------------------------------------------------

def next_free_name(name_prefix, start, busy_reason, *, log, summary_hint):
    """(name, index) of the first name at or after index `start` that
    busy_reason(name) calls free (None). Skips are logged, capped at
    SKIP_LOG_LIMIT lines plus one summary line ending in `summary_hint`."""
    i, skipped = start, 0
    while True:
        name = child_name(name_prefix, i)
        why = busy_reason(name)
        if why is None:
            break
        if skipped < SKIP_LOG_LIMIT:
            log(f"[pool] SKIP {name}: {why}")
        skipped += 1
        i += 1
    if skipped > SKIP_LOG_LIMIT:
        log(f"[pool] ... and {skipped - SKIP_LOG_LIMIT} further consecutive "
            f"busy names skipped (last was {child_name(name_prefix, i - 1)}); "
            f"resuming at {name}. {summary_hint}")
    return name, i
