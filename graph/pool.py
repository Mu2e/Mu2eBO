"""The parent rolling work-pool: q children in flight, replenish on resolve.

A child resolves when its SUBPROCESS EXITS -- the single resolution truth
source; *_cluster.txt survives only as `_name_busy_reason`'s LAUNCH-time
double-launch guard. Retired-by-design (wiki/incidents/):
barrier-false-positive-round1, closed-loop-barrier-timeout-zero-rows-falsepos,
closed-loop-final-round-orphan-children, rolling-no-row-streak-false-increment.
The run_child/next_pick/stop_flag/renew/row_landed/broken callables are the
test seam.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from concurrent.futures import as_completed

Outcome = namedtuple("Outcome", "name x rc row_landed broken reason")

# Heartbeat cadence: 15 min so a q=20 launch (30 min of 90 s stagger before
# the first possible resolution) is never silent long, yet multi-day campaign
# logs stay readable. Diagnostic only (see _log_inflight).
HEARTBEAT_S = 15 * 60

# In-flight age that upgrades the heartbeat to a WARNING: 24 h matches
# core/pipeline.py's poll cap_hours -- past it, outside every normal duration.
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
            f"subprocess to exit, by design. To investigate: "
            f"`pgrep -f 'graph.run.*{name}'`, its log under "
            f"closed_loop_logs/{name}.log, and `jobsub_q -G mu2e "
            f"--user=$USER`. If you kill it, clear its state before any "
            f"relaunch under the same --name-prefix: "
            f"`rm <grid>/{name}/state/*_cluster.txt` (only once no job of "
            f"its is still landing outputs there), or relaunch with a "
            f"different --name-prefix.")


def _wait_one(inflight, log, heartbeat=HEARTBEAT_S):
    """Block until one future resolves; the timeout drives heartbeat logging
    only, never an early return."""
    while True:
        try:
            return next(as_completed(list(inflight), timeout=heartbeat))
        except _FutureTimeout:
            _log_inflight(inflight, log)


def classify(name, x, rc, row_landed, broken) -> Outcome:
    """Exit code plus artifacts decide the outcome. No polling."""
    if rc == 0 and row_landed:
        return Outcome(name, x, rc, True, False, "ok")
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


def run_rolling(mode, picker, q, max_evals, alpha, name_prefix,
                run_child=None, next_pick=None, stop_flag=None, renew=None,
                row_landed=None, broken=None, log=print, stagger=None,
                heartbeat=HEARTBEAT_S):
    """Keep q children in flight until max_evals launched and the pool drains.

    Returns {"launched", "rows", "outcomes", "aborted"}. `stagger` separates
    launches: concurrent mu2ejobsub within ~10s races
    (wiki/incidents/concurrent-token-contention.md measured 60-90s safe).
    `heartbeat` is REPORT-ONLY -- never resolves/abandons (_log_inflight).
    """
    run_child = run_child or _default_run_child(mode, alpha)
    next_pick = next_pick or _default_pick_source(name_prefix)
    stop_flag = stop_flag or (lambda: False)
    renew = renew or (lambda: None)
    row_landed = row_landed or _default_row_landed
    broken = broken or _default_broken
    if stagger is None:
        from runtime import CLOSED_LOOP_STAGGER_SEC
        stagger = CLOSED_LOOP_STAGGER_SEC

    inflight = {}   # future -> (name, x, launch timestamp)
    launched = 0
    rows = 0
    streak = 0
    aborted = False
    outcomes = []

    def _resolve_one(fut):
        """Pop one resolved future -> Outcome, logging per child from main
        loop and drain alike.

        Renews the ticket AFTER recording the outcome: a q=20 drain runs for
        hours and children share the parent's ccache
        (wiki/incidents/kerberos-mid-run-expiry.md -- an expired-ticket eval
        VANISHES rather than failing visibly). Failure here is REPORTED, not
        fatal -- only the pre-launch renew gates "can we still submit?".
        SystemExit caught: renew_token signals fatal via sys.exit(2)."""
        name, x, _t0 = inflight.pop(fut)
        try:
            rc = fut.result()
        except Exception as exc:  # noqa: BLE001
            rc = 1
            log(f"[pool] {name} raised: {exc}")
        oc = classify(name, x, rc, row_landed(name, mode), broken(name))
        log(f"[pool] {name}: {oc.reason}")
        try:
            renew()
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            log(f"[pool] renew at resolution failed ({exc}); not fatal here "
                f"-- the pre-launch renew is the gate that stops the "
                f"campaign. Children already running are unaffected.")
        return oc

    with ThreadPoolExecutor(max_workers=q) as poolx:
        while (launched < max_evals or inflight) and not aborted:
            while (len(inflight) < q and launched < max_evals
                   and not stop_flag() and not aborted):
                if launched > 0 and stagger:
                    time.sleep(stagger)
                renew()
                x, name = next_pick(mode, picker,
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
                log(f"[pool] {oc.name}: no-row streak {streak}/{max(q, 2)}")
            if _should_abort(streak, q):
                aborted = True
                log(f"[pool] ABORT: {streak} consecutive resolutions with "
                    f"no row (>= {max(q, 2)})")
        # Drain: never exit with work in flight -- the structural fix for
        # wiki/incidents/closed-loop-final-round-orphan-children.md. Same
        # _resolve_one/_wait_one, so an abort/STOP drain still logs per child.
        while inflight:
            oc = _resolve_one(_wait_one(inflight, log, heartbeat))
            outcomes.append(oc)
            if oc.row_landed:
                rows += 1
    return {"launched": launched, "rows": rows,
            "outcomes": outcomes, "aborted": aborted}


# --- production defaults ---------------------------------------------------

def _default_run_child(mode, alpha):
    """Popen `graph.run` and WAIT. The wait IS the barrier."""
    from paths import GRAPH_DATA, REPO_ROOT as PROJECT_ROOT

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


def _pending_names(mode) -> set:
    """Names with an unresolved row in the mode's pending TSV. An
    unregistered mode raises KeyError loudly: fail-open would give the
    double-launch guard a silently EMPTY busy-name set."""
    import bo_driver as bo  # noqa: WPS433
    return {n for n, _x in bo.MODES[mode].load_pending()}


def _name_busy_reason(cl, name, lb_names, pending_names):
    """Why `name` must not be launched again, or None if it is free.

    leaderboard row / broken.txt = RESOLVED by a prior process;
    *_cluster.txt / pending row = work IN FLIGHT (the double-launch guard).
    Relaunching under the same --name-prefix with a prior detached child
    alive is the STANDARD recovery move; without the guard, pipeline.py's
    submit idempotency makes child 2 harvest child 1's outputs -- two rows
    under one name, both with child 1's metrics, and the GP trains on an x
    that does not describe its geometry. Nothing errors. Cannot recreate
    wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md: the
    monotonic launch index means a skip ADVANCES to a fresh name.
    """
    if name in lb_names:
        return (f"already has a leaderboard row from a PRIOR run under this "
                f"--name-prefix -- skipping so this child is not credited "
                f"with that run's outcome")
    if cl._child_is_broken(name):
        return (f"already carries broken.txt from a PRIOR run under this "
                f"--name-prefix -- skipping so this child is not credited "
                f"with that run's outcome")
    state_dir = cl._child_state_dir(name)
    if any(state_dir.glob("*_cluster.txt")):
        return (
            f"has *_cluster.txt in {state_dir} -- a grid submission under "
            f"this name is IN FLIGHT or was abandoned by a prior run. "
            f"Launching a second graph.run here would re-use that cluster "
            f"and land TWO leaderboard rows under one name, both carrying "
            f"the FIRST child's metrics. Advancing to the next index. "
            f"RECOVERY: confirm nothing is alive for it "
            f"(pgrep -f 'graph.run.*{name}'), then either "
            f"`rm {state_dir}/*_cluster.txt` and relaunch, or relaunch with "
            f"a different --name-prefix")
    if name in pending_names:
        return (
            f"has an unresolved row in the pending TSV -- a prior run "
            f"proposed under this name and never resolved it (it may still "
            f"be in preflight, which can take up to PREFLIGHT_TIMEOUT_S per "
            f"attempt, before any cluster file exists). Advancing to the "
            f"next index rather than racing it. If that attempt is dead, "
            f"`core/bo_driver.py --mode <mode> pending-prune` clears the row")
    return None


def child_name(name_prefix: str, i: int) -> str:
    """THE child-name shape `{prefix}R{i:02d}_00`; every producer (allocator,
    skip summary, dry-run preview) goes through here so names cannot drift."""
    return f"{name_prefix}R{i:02d}_00"


def _default_pick_source(name_prefix):
    """Closure holding the monotonic launch index; imports closed_loop lazily
    (closed_loop imports pool). Busy names skip per `_name_busy_reason`."""
    counter = {"i": 0}
    busy_cache = {}

    def next_pick(mode, picker, x_pending):
        import closed_loop as cl
        i = counter["i"]
        # Both TSVs read ONCE per process: flock'd full-file reads consulted
        # strictly for PRIOR-run state; the monotonic index plus the
        # single-writer-per---name-prefix invariant make later reads moot.
        if mode not in busy_cache:
            busy_cache[mode] = (cl._leaderboard_names(mode),
                                _pending_names(mode))
        lb_names, pending_names = busy_cache[mode]
        skipped = 0
        while True:
            name = child_name(name_prefix, i)
            why = _name_busy_reason(cl, name, lb_names, pending_names)
            if why is None:
                break
            if skipped < SKIP_LOG_LIMIT:
                print(f"[pool] SKIP {name}: {why}", flush=True)
            skipped += 1
            i += 1
        if skipped > SKIP_LOG_LIMIT:
            print(f"[pool] ... and {skipped - SKIP_LOG_LIMIT} further "
                  f"consecutive busy names skipped (last was "
                  f"{child_name(name_prefix, i - 1)}); resuming at {name}. "
                  f"Reasons are the same four signals as above -- see "
                  f"graph/pool.py::_name_busy_reason.", flush=True)
        counter["i"] = i + 1
        picks = cl._botorch_picks_subprocess(mode, q=1, round_idx=i,
                                             picker=picker, pending=x_pending)
        return list(picks[0]), name
    return next_pick


def _default_row_landed(name, mode):
    """Did this child land a leaderboard row? THE signal `_should_abort` reads.

    An unregistered mode raises loudly (ADR-0002) rather than fail-open
    "every child landed a row", which would let a mode-registry mismatch
    report a campaign of silent failures as fully successful -- the shape of
    wiki/incidents/foilsflash-tarball-mode-key-omission.md and
    wiki/incidents/preflight-mode-tuple-prodtarget6d-omission.md.
    """
    import bo_driver as bo  # noqa: WPS433
    bo.MODES[mode]   # loud KeyError on an unregistered mode (ADR-0002)
    import closed_loop as cl
    return name in cl._leaderboard_names(mode)


def _default_broken(name):
    import closed_loop as cl
    return cl._child_is_broken(name)
