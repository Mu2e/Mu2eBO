"""The parent rolling work-pool: q children in flight, replenish on resolve.

Replaces node_predict_picks' rolling branch + node_assign_names +
node_launch_children + node_barrier + node_decide_next + child_tracker.py --
roughly 700 LOC expressing a bounded work pool across four graph nodes and a
checkpointed state dict.

A child resolves when its SUBPROCESS EXITS. That is one RESOLUTION truth
source, replacing five (checkpoint terminal, pid_alive, *_cluster.txt,
broken.txt, leaderboard membership). Note that *_cluster.txt survives here in
a different role: `_name_busy_reason` reads it at LAUNCH time as an
already-submitted signal (the double-launch guard the retired
node_launch_children called `_already_running`). Retiring it as a resolution
signal and retiring it as a launch guard are two different things -- the
first draft of this module conflated them and dropped the guard, which is
final-review finding C1.

Four incidents stop being possible rather than guarded:

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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from concurrent.futures import as_completed

Outcome = namedtuple("Outcome", "name x rc row_landed broken reason")

# How often the parent prints what it is waiting on. Purely diagnostic --
# see _wait_one. 15 min is short enough that a q=20 launch (30 min of
# 90 s stagger before the first resolution can even be expected) is never
# silent for long, and long enough that a multi-day campaign log stays
# readable.
HEARTBEAT_S = 15 * 60

# Age at which an in-flight child gets a WARNING rather than a heartbeat
# line. 24 h matches core/pipeline.py's own poll cap_hours: past that, the
# child is outside every documented normal duration.
STALL_WARN_S = 24 * 3600


def _log_inflight(inflight, started, log, now=None, warn_after=STALL_WARN_S):
    """One heartbeat line: what is in flight and for how long.

    REPORT-ONLY, deliberately. It must never resolve, abandon or abort a
    child: a parent-level timeout that DECIDES things is exactly
    wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md, where
    a 240-min barrier timeout was misread as "all children failed" and the
    campaign exited with 8 orphans still running. The spec that produced
    this module closed that incident by construction (a child resolves when
    its subprocess exits, full stop) and this must not re-open it. The only
    thing missing was DIAGNOSTICS: `as_completed` with no timeout means a
    hung child (wiki/incidents/harvest-pyroot-nfs-rpc-hang.md: harvest in
    D-state 5.5 h with no timeout at any layer;
    wiki/incidents/poll-deadlock-missing-outstage-dirs.md: a full 24 h
    cap_hours wait) freezes the parent log, and silence is indistinguishable
    from healthy grid time.
    """
    now = time.time() if now is None else now
    ages = sorted(((now - started.get(name, now)), name)
                  for name, _x in inflight.values())
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


def _wait_one(inflight, started, log, heartbeat=HEARTBEAT_S):
    """Block until one future resolves, emitting a heartbeat meanwhile.

    Same contract as the bare `next(as_completed(...))` it replaces -- it
    returns exactly when a child exits, never earlier. The timeout drives
    logging only.
    """
    while True:
        try:
            return next(as_completed(list(inflight), timeout=heartbeat))
        except _FutureTimeout:
            _log_inflight(inflight, started, log)


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
                row_landed=None, broken=None, log=print, stagger=None,
                heartbeat=HEARTBEAT_S):
    """Keep q children in flight until max_evals launched and the pool drains.

    Returns {"launched", "rows", "outcomes", "aborted"}.

    Aborts per `_should_abort` -- the guard that used to need name-based
    wave accounting. Here each child's own outcome is read at the moment it
    resolves, so a row cannot be absorbed into a neighbouring wave's
    baseline.

    `stagger` seconds separate consecutive launches (not before the first
    one): concurrent mu2ejobsub submissions within ~10s are known to race
    (wiki/incidents/concurrent-token-contention.md, which measured 60-90s as
    safe). Defaults to `runtime.CLOSED_LOOP_STAGGER_SEC` when omitted; tests
    pass `stagger=0` so the suite doesn't sleep.

    `heartbeat` seconds between "here is what I am waiting on" log lines
    while the pool is blocked. REPORT-ONLY -- it never resolves or abandons
    a child (see `_log_inflight`); it exists because a hung child otherwise
    freezes the parent log indefinitely and silence is indistinguishable
    from healthy grid time.
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

    inflight = {}
    started = {}   # name -> launch timestamp, for the heartbeat's ages
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
        operator most needs them.

        Also renews the ticket, AFTER the outcome is recorded. renew() used
        to be called only in the top-up loop, so once the last child was
        LAUNCHED a q=20 pool could drain for hours with no `kinit -R` -- and
        children share the parent's ccache, so an expiry during a late stage
        submit is wiki/incidents/kerberos-mid-run-expiry.md: the eval dies
        before harvest and VANISHES (no row, no loud failure) rather than
        failing visibly. renew_token is time-gated at RENEW_MIN_INTERVAL_S,
        so the extra call sites cost nothing (final review, finding M7).

        Failures here are REPORTED, not fatal -- deliberately asymmetric with
        the pre-launch renew() in the top-up loop, which stays fatal. That
        one answers "can we still submit?", and the honest answer to no is
        stop launching. This one is opportunistic hygiene for children
        already running: aborting the parent on it would abandon reporting
        for a pool that is only draining, and during a drain there is
        nothing left to refuse to launch. SystemExit is caught explicitly
        because renew_token signals fatal with sys.exit(2)."""
        name, x = inflight.pop(fut)
        try:
            rc = fut.result()
        except Exception as exc:  # noqa: BLE001
            rc = 1
            log(f"[pool] {name} raised: {exc}")
        oc = classify(name, x, rc, mode, row_landed(name, mode), broken(name))
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
                                    [v for _, v in inflight.values()])
                inflight[poolx.submit(run_child, name, x)] = (name, x)
                started[name] = time.time()
                launched += 1
                log(f"[pool] launched {name} ({launched}/{max_evals}), "
                    f"in_flight={len(inflight)}")
            if not inflight:
                break
            oc = _resolve_one(_wait_one(inflight, started, log, heartbeat))
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
        # _resolve_one and _wait_one helpers as the main loop, so an abort's
        # abandoned children still get a per-child log line AND the drain --
        # which is where a q=20 pool spends its last hours, and where a STOP
        # spends ALL of its time -- is not silent either.
        while inflight:
            oc = _resolve_one(_wait_one(inflight, started, log, heartbeat))
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
    """Names carrying an unresolved row in the mode's pending TSV.

    Guarded exactly like _default_row_landed's MODES check: a synthetic test
    mode is not in bo_driver.MODES and has no pending file, so it contributes
    nothing rather than raising. A genuinely broken pending file still
    propagates -- this guard is scoped to the registry lookup only.
    """
    import bo_driver as bo  # noqa: WPS433
    if mode not in bo.MODES:
        return set()
    return {n for n, _x in bo.MODES[mode].load_pending()}


def _name_busy_reason(cl, name, lb_names, pending_names):
    """Why `name` must not be launched again, or None if it is free.

    Three signals, and they are NOT the same kind of thing:

      leaderboard row / broken.txt   -- the name is already RESOLVED by an
                                        earlier process.
      *_cluster.txt / pending row    -- the name has WORK IN FLIGHT (or
                                        abandoned mid-flight) from an
                                        earlier process.

    The second pair is the double-launch guard that `_already_running` used
    to carry in the retired node_launch_children, and it is what stops the
    corruption described in the final-review finding C1: relaunching under
    the same --name-prefix (the STANDARD recovery move, see run_rolling's
    caller and README "Recovering from a crashed parent") while a detached
    child from the prior run is still alive. A second `graph.run` under the
    same name would delete child 1's pending row and re-propose with child
    2's x (graph/nodes.py caller_pinned branch), then find child 1's
    `<stage>_cluster.txt` already present and SKIP submit (core/pipeline.py's
    submit idempotency guard) -- so child 2 polls child 1's clusters and
    harvests child 1's outputs. core/leaderboard.py append() has no
    duplicate-name guard, so two rows land under one name with two different
    x values, BOTH carrying child 1's geometry's metrics, and the GP then
    trains on a point whose x does not describe the geometry that produced
    it. Nothing errors.

    This cannot recreate closed-loop-stale-cluster-silent-no-launch (0
    children launched, barrier polls forever): that bug filtered a FIXED list
    of q names and ended with pending == []. Here the index counter is
    monotonic, so a skip ADVANCES to a fresh unused name rather than removing
    a launch from the batch. `next_pick` always returns a name.
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


def _default_pick_source(name_prefix):
    """Closure so the picker sees the running launch index for its name and
    round-seed. Imports closed_loop lazily -- closed_loop imports pool.

    Skips any candidate name an EARLIER process already resolved OR still has
    work in flight for; see `_name_busy_reason` for the four signals and why
    the cluster-file/pending pair is a DOUBLE-LAUNCH guard rather than a
    resolution signal. Relaunching under the same --name-prefix is the
    STANDARD recovery move in this project, so this path is on the normal
    operating envelope, not an exotic corner. See Task 3 review round 2,
    CRITICAL 1 and the final-review finding C1.
    """
    counter = {"i": 0}

    def next_pick(mode, picker, x_pending):
        import closed_loop as cl
        i = counter["i"]
        lb_names = cl._leaderboard_names(mode)
        pending_names = _pending_names(mode)
        while True:
            name = f"{name_prefix}R{i:02d}_00"
            why = _name_busy_reason(cl, name, lb_names, pending_names)
            if why is None:
                break
            print(f"[pool] SKIP {name}: {why}", flush=True)
            i += 1
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
