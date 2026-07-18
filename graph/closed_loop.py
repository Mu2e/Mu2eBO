"""Multi-round closed-loop batch BO runner.

Each round:
  0. renew_token — `kinit -R` + sourced `setupmu2e-art.sh && getToken` to refresh krb5 +
                   bearer before launching children. Best-effort (errors
                   logged, not fatal). See wiki/incidents/kerberos-mid-run-expiry.
  1. predict_picks — refit GP on current leaderboard, return q Pareto picks.
  2. assign_names  — derive {prefix}R{NN}_{j} names; skip names already done.
  3. launch_children — Popen `graph.run --config-name … --x-point …` per pick,
                       staggered by CLOSED_LOOP_STAGGER_SEC. Children detach
                       (start_new_session=True) so killing this parent does
                       not propagate.
  4. barrier — poll each child's SqliteSaver checkpoint (NOT the leaderboard
               TSV, which is a derived end-of-harvest artifact) until terminal
               or dead-pid; cross-check leaderboard for sanity. Child process
               liveness is the wait condition — there is NO per-round pacing
               timeout (alive children always resolve via their internal
               stage caps). barrier_max_min (default 24h) is only a loud
               backstop for alive-but-hung children. Children whose process
               died without any resolution artifact are marked
               completed-failed after one poll tick of grace (foilsf08 crash
               shape).
  5. decide_next — loop unless max_rounds / zero_rows / STOP_FLAG.
               zero_rows fires only when ALL of this round's launched
               children resolved AND none produced a leaderboard row
               (all-failed). A barrier timeout with children still pending
               carries the round forward instead (the pending children become
               orphans whose rows land later — see
               wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md).

Convergence-by-Pareto-hash was deleted 2026-05-29 after 15 production runs
showed 0 true saves (FT05/FT06 r0→1 were both --max-rounds 2 and would have
exited anyway) and 1 false positive (foilsX04 zero-row case). Saturation is
now diagnosed post-hoc from the leaderboard. The zero-row break is the
orthogonal safety check (catches all-children-failed rounds early).

The outer graph is itself checkpointed in `checkpoints.sqlite`; killing this
parent and re-invoking with the same --thread-id resumes the current round.
assign_names treats names already present in the leaderboard (or with
state/broken.txt) as completed → barrier re-polls without re-launching.

See wiki/concepts/closed-loop-bo-design.md for the load-bearing constraints
(SqliteSaver WAL, TSV file locking, barrier source-of-truth, config-SHA
stamping, scan_logs gating, q-pick spacing).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))  # BO/pipeline modules

# Stamp AUTORESEARCH_MODE / AUTORESEARCH_NO_RUN1B BEFORE `from config import ...`
# — config.GRID_STAGES is selected from GRID_STAGES_BY_MODE at module-load time,
# and build.STAGE_NODES freezes it. argparse runs much later (in main()).
# Shared sniffers: graph/presniff.py. Issue Mu2eBO #15.
from presniff import presniff_mode, presniff_picker  # noqa: E402
from graph.child_tracker import ChildTracker, Resolution  # noqa: E402
import modes as _modes  # noqa: E402  (env-independent; safe pre-stamp)

presniff_mode()
presniff_picker()

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from config import (  # noqa: E402
    BOTORCH_PREDICT,
    BOTORCH_VENV_PY,
    CLOSED_LOOP_BARRIER_MAX_MIN,
    CLOSED_LOOP_BARRIER_POLL_SEC,
    CLOSED_LOOP_MAX_ROUNDS,
    CLOSED_LOOP_Q,
    CLOSED_LOOP_STAGGER_SEC,
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRAPH_DATA,
    GRID_DATA_ROOT,
    PROJECT_ROOT,
    STOP_FLAG,
    open_saver_conn,
)

from sourced_bash import run_sourced_bash  # noqa: E402

# cl_min retired per ADR-0001 (2026-07-06, deleted 2026-07-11): the closed
# loop must never import code outside this repo; all pickers route through
# in-repo botorch_predict.py in .venv-botorch.
PICKER_CHOICES = ("qnehvi", "qlnei", "pareto_sob", "qnparego", "hybrid")
DEFAULT_PICKER = "hybrid"

# ============================================================================
# Outer state schema
# ============================================================================

class ChildRecord(TypedDict, total=False):
    pid: Optional[int]
    log: str
    x_point: List[float]
    started_at: float
    thread_id: str  # per-launch unique; differs from config_name to dodge collisions


class RoundState(TypedDict, total=False):
    mode: str
    alpha: float
    q: int
    max_rounds: int
    round_idx: int
    name_prefix: str
    children: Dict[str, ChildRecord]
    launched_names: List[str]
    completed_names: List[str]
    history_len_before: int
    zero_rows: bool
    errors: List[str]
    stagger_sec: int
    barrier_poll_sec: int
    barrier_max_min: int
    stop_seen: bool
    timeout_seen: bool
    picker: str
    # Rolling mode (--rolling): q = pool WIDTH; the barrier exits on the
    # first resolution and decide_next replenishes the free slots until
    # max_evals total launches. round_idx counts replenish WAVES (feeds the
    # R{NN} name segment). no_row_streak generalizes the zero-rows guard:
    # q consecutive rowless resolutions = the foilsX04 all-failing shape.
    rolling: bool
    max_evals: int
    no_row_streak: int
    prev_completed_names: list  # child names resolved as of the previous wave
    rolling_done: bool


# ============================================================================
# Helpers
# ============================================================================

def _stop_requested() -> bool:
    return STOP_FLAG.exists()


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid exists. PID reuse can only make a
    dead child look alive (falls back to the barrier timeout) — a live
    child can never look dead."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _open_saver_conn() -> sqlite3.Connection:
    """Patchable seam (tests mock this name); recipe lives in config."""
    return open_saver_conn()


def _child_state_dir(name: str) -> Path:
    return GRID_DATA_ROOT / name / "state"


class _DiskSignals:
    """Production Signals adapter (CONTEXT.md: 'Signals adapter'): reads the
    raw child signals from disk/SQLite. Late-binds to the module-level
    helpers so tests that patch them (mock.patch.object(cl, ...)) keep
    intercepting; unit tests of the tracker itself inject a fake instead."""

    def __init__(self, mode: str, child_graph):
        self._mode = mode
        self._graph = child_graph

    def leaderboard_names(self) -> set:
        return _leaderboard_names(self._mode)

    def is_broken(self, name: str) -> bool:
        return _child_is_broken(name)

    def is_terminal(self, thread_id: str) -> bool:
        from graph.build import is_child_terminal  # noqa: WPS433 — patchable
        return is_child_terminal(thread_id=thread_id, child_graph=self._graph)

    def pid_alive(self, pid: int) -> bool:
        return _pid_alive(pid)


def _child_is_broken(name: str) -> bool:
    return (_child_state_dir(name) / "broken.txt").exists()


def _history(mode: str):
    """One flock-aware leaderboard read via the BO driver (which flocks).

    The barrier consumes this once per poll tick; per-child reads would
    re-parse the full (growing) TSV q times per tick, thousands of times
    per round at q=20 under the 24h backstop cap."""
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
    import bo_driver as bo  # noqa: WPS433
    return bo.MODES[mode].load_history()


def _leaderboard_names(mode: str) -> set:
    return {p.cfg for p in _history(mode)}


def _child_in_leaderboard(name: str, mode: str) -> bool:
    return name in _leaderboard_names(mode)


def _leaderboard_len(mode: str) -> int:
    return len(_history(mode))


# ============================================================================
# Nodes
# ============================================================================

def node_renew_token(state: RoundState) -> dict:
    """Refresh krb5 ticket + bearer token at top of each round.

    Closed-loop rounds run 6-8 h wall; default krb5 lifetime is ~25 h, so
    one or two rounds easily outlive the ticket. First post-expiry
    subprocess.run raises Errno 127 (ENOKEY) and the inner graph
    terminates before harvest. See wiki/incidents/kerberos-mid-run-expiry.md.

    Hard gate: if `getToken` fails (proxy for "can we actually submit?"),
    `sys.exit(2)` with an actionable message. Continuing past expiry just
    guarantees every child dies later with the same Errno 127, leaving
    orphan grid clusters and no leaderboard rows. The outer graph is
    checkpointed — operator runs `kinit` then re-invokes with the same
    `--thread-id` to resume from this node.

    `kinit -R` is best-effort (it's normal for it to fail if the ticket
    is past its renewable lifetime); the load-bearing check is `getToken`.
    """
    errors = list(state.get("errors", []))
    try:
        r = subprocess.run(["kinit", "-R"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            errors.append(f"renew_token[r{state['round_idx']}]: kinit -R rc={r.returncode}: "
                          f"{r.stderr.strip()[:200]}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"renew_token[r{state['round_idx']}]: kinit -R failed: {exc}")
    cmd = "source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh && getToken"
    try:
        # getToken shares the cvmfs/spack flake class -> retry via the shared
        # helper (was a bare one-shot subprocess.run). A persistent rc!=0 after
        # retries is still FATAL (krb5 likely expired); a transient flake now
        # recovers instead of hard-exiting the whole campaign at a round edge.
        r = run_sourced_bash(cmd, login=True, timeout=120,
                             label=f"renew_token[r{state['round_idx']}]")
    except Exception as exc:  # noqa: BLE001
        msg = (f"[closed_loop] FATAL renew_token[r{state['round_idx']}]: "
               f"getToken raised: {exc}. "
               f"Run `kinit` then re-invoke with same --thread-id to resume.")
        print(msg, flush=True)
        sys.exit(2)
    if r.returncode != 0:
        msg = (f"[closed_loop] FATAL renew_token[r{state['round_idx']}]: "
               f"getToken rc={r.returncode}: {r.stderr.strip()[:400]}. "
               f"Run `kinit` (krb5 likely past renewable lifetime) then "
               f"re-invoke with same --thread-id to resume.")
        print(msg, flush=True)
        sys.exit(2)
    print(f"[closed_loop] renew_token[r{state['round_idx']}]: krb5 + bearer refreshed", flush=True)
    return {"errors": errors}


def _botorch_picks_subprocess(mode: str, q: int, round_idx: int, picker: str = "qnehvi",
                              pending: list | None = None) -> list[tuple]:
    """Shell into .venv-botorch to run botorch_predict.py; return picks.

    Disjoint-venv: closed_loop.py runs under .venv-graph (no botorch); the
    botorch pickers need .venv-botorch (no langgraph). We round-trip
    picks through a temp JSON file using botorch_predict.py's
    --emit-picks-json.

    picker = any PICKER_CHOICES entry: "qnehvi" (multi-obj),
    "qlnei" (single-obj sob), "pareto_sob" (GP-mean sob corner),
    "qnparego" (random-Chebyshev-scalarization spread), "hybrid"
    (~60% qnehvi + ~40% qnparego; recommended for new multi-objective lines).

    Picks come back as JSON list-of-lists; convert to list-of-tuples to match
    the sklearn-EI path (gp.compute_explore_picks return contract).
    """
    import tempfile
    if not BOTORCH_VENV_PY.exists():
        raise FileNotFoundError(
            f"[closed_loop] picker={picker} requested but {BOTORCH_VENV_PY} "
            f"is missing; install .venv-botorch (all pickers require it)"
        )
    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as tf:
        out_path = Path(tf.name)
    pend_path: Optional[Path] = None
    try:
        cmd = [
            str(BOTORCH_VENV_PY), str(BOTORCH_PREDICT),
            "--mode", mode, "--q", str(q),
            "--round-idx", str(round_idx),
            "--picker", picker,
            "--emit-picks-json", str(out_path),
        ]
        if pending:
            # Rolling mode: in-flight x_points ride to the picker via a tmp
            # JSON so replacements fantasize over them (X_pending) instead of
            # re-picking a point that's already being measured.
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False) as pf:
                json.dump([list(x) for x in pending], pf)
                pend_path = Path(pf.name)
            cmd += ["--pending-json", str(pend_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
        if r.returncode != 0:
            raise RuntimeError(
                f"[closed_loop] botorch_predict rc={r.returncode}: "
                f"stderr={r.stderr.strip()[:400]}"
            )
        raw = json.loads(out_path.read_text())
    finally:
        for p in (out_path, pend_path):
            if p is not None:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
    return [tuple(p) for p in raw]


def node_predict_picks(state: RoundState) -> dict:
    """Refit GP, return q picks. Picker is one of PICKER_CHOICES.

    All pickers subprocess into .venv-botorch (disjoint venv) to run
    botorch_predict.py (cl_min retired per ADR-0001):
      qnehvi: multi-objective Pareto-HV picker; native acquisition is qNEHVI,
        not the scalarized obj the leaderboard reports.
      qlnei: single-obj qLogNoisyEI on sob only (drops the run1b_mubeam stage).
      pareto_sob: the GP-mean highest-sob frontier points.
      qnparego: qLogNEI over random Chebyshev scalarizations — spreads picks
        across the whole Pareto front (patrols the tails qNEHVI underprices).
      hybrid: ~60% qnehvi + ~40% qnparego in one batch — recommended default
        for new multi-objective lines (HV efficiency + native tail coverage;
        see wiki/concepts/saturation-is-acquisition-relative.md).
    """
    q = state["q"]
    mode = state["mode"]
    picker = state.get("picker", DEFAULT_PICKER)
    errors = list(state.get("errors", []))

    if state.get("rolling"):
        # Rolling: q is the pool WIDTH. Ask only for the free slots, capped by
        # the remaining eval budget, and hand the picker the in-flight
        # x_points so replacements fantasize over them (X_pending).
        children = dict(state.get("children", {}))
        completed = set(state.get("completed_names", []))
        in_flight = {n: rec for n, rec in children.items() if n not in completed}
        launched_total = len(set(children) | completed)
        q_next = max(0, min(q - len(in_flight),
                            state["max_evals"] - launched_total))
        if q_next == 0:
            # Drain wave: pool full or budget exhausted — the barrier just
            # waits for the next resolution; nothing to pick or launch.
            print(f"[closed_loop] predict_picks[w{state['round_idx']}]: "
                  f"rolling drain (in_flight={len(in_flight)} "
                  f"launched={launched_total}/{state['max_evals']})", flush=True)
            return {"history_len_before": _leaderboard_len(mode)}
        pending_x = [list(rec["x_point"]) for _, rec in sorted(in_flight.items())]
        picks = _botorch_picks_subprocess(mode, q_next, state["round_idx"],
                                          picker=picker, pending=pending_x)
        print(f"[closed_loop] predict_picks[w{state['round_idx']}]: rolling "
              f"picker={picker} q_next={q_next} got={len(picks)} "
              f"(pending={len(pending_x)} launched={launched_total}/"
              f"{state['max_evals']})", flush=True)
        if len(picks) < q_next:
            errors.append(
                f"predict_picks[w{state['round_idx']}]: only got "
                f"{len(picks)}/{q_next} rolling picks")
        transient = {**children,
                     **{f"_pick_{j:02d}": {"x_point": list(p)}
                        for j, p in enumerate(picks)}}
        return {
            "children": transient,
            "errors": errors,
            "history_len_before": _leaderboard_len(mode),
        }

    picks = _botorch_picks_subprocess(mode, q, state["round_idx"], picker=picker)
    print(f"[closed_loop] predict_picks[r{state['round_idx']}]: "
          f"picker={picker} "
          f"q={q} got={len(picks)}", flush=True)
    if len(picks) < q:
        errors.append(
            f"predict_picks[r{state['round_idx']}]: only got {len(picks)}/{q} "
            f"picks (Pareto frontier too short or too clustered)"
        )
    # Store picks transiently in children dict keyed by *placeholder* name;
    # real names land in assign_names. Also snapshot leaderboard length so
    # decide_next can detect "round produced 0 new rows" (all children
    # failed → exit early instead of refitting on identical data).
    transient = {f"_pick_{j:02d}": {"x_point": list(p)} for j, p in enumerate(picks)}
    return {
        "children": transient,
        "errors": errors,
        "history_len_before": _leaderboard_len(state["mode"]),
    }


def node_assign_names(state: RoundState) -> dict:
    """Derive {prefix}R{NN}_{j} names; skip names already complete."""
    prefix = state["name_prefix"]
    r = state["round_idx"]
    mode = state["mode"]
    transient = state.get("children", {})
    children: Dict[str, ChildRecord] = {}
    completed: List[str] = list(state.get("completed_names", []))
    for j_str, rec in sorted(transient.items()):
        if not j_str.startswith("_pick_"):
            # Already a real name (resume path) — keep as-is.
            children[j_str] = rec
            continue
        j = int(j_str.split("_")[-1])
        name = f"{prefix}R{r:02d}_{j:02d}"
        if _child_in_leaderboard(name, mode) or _child_is_broken(name):
            completed.append(name)
            continue
        children[name] = {
            "x_point": rec["x_point"],
            "log": str(GRAPH_DATA / "closed_loop_logs" / f"{name}.log"),
            "pid": None,
            "started_at": 0.0,
        }
    return {"children": children, "completed_names": completed}


def node_launch_children(state: RoundState) -> dict:
    """Popen one `graph.run` per pending child; stagger between launches."""
    stagger = state.get("stagger_sec", CLOSED_LOOP_STAGGER_SEC)
    mode = state["mode"]
    alpha = state["alpha"]
    children = dict(state["children"])
    errors = list(state.get("errors", []))
    # Idempotency: skip names whose inner graph has already started a stage
    # (per-stage cluster.txt exists) OR landed in the leaderboard OR have
    # broken.txt. A crashed parent re-entering launch_children must not
    # re-Popen `graph.run` for a config whose grid submission is in flight,
    # otherwise we double-submit (and pollute pending TSV / cluster files).
    def _already_running(name: str) -> bool:
        state_dir = _child_state_dir(name)
        if any(state_dir.glob("*_cluster.txt")):
            return True
        return _child_in_leaderboard(name, mode) or _child_is_broken(name)

    pending = [
        (n, rec) for n, rec in children.items()
        if not rec.get("pid") and not _already_running(n)
    ]
    (GRAPH_DATA / "closed_loop_logs").mkdir(parents=True, exist_ok=True)
    for idx, (name, rec) in enumerate(pending):
        x = rec["x_point"]
        log_path = Path(rec["log"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "w")
        # Per-launch unique thread_id: prevents SqliteSaver checkpoint collision
        # with prior `python -m graph.run --thread-id <name>` sessions sharing
        # the same name (e.g. manual smokes named graph001). config_name stays
        # the user-visible leaderboard key; thread_id is just the checkpoint
        # row key. See [[closed-loop-thread-id-checkpoint-collision]].
        # Reuse a thread_id from a prior crashed parent (resume path) when
        # the record already carries one — otherwise the new launch would
        # orphan the prior child's checkpoint AND the barrier's checkpoint
        # lookup (which uses rec["thread_id"]) would never resolve.
        thread_id = rec.get("thread_id") or f"{name}_{uuid.uuid4().hex[:8]}"
        rec["thread_id"] = thread_id
        cmd = [
            sys.executable, "-m", "graph.run",
            "--thread-id", thread_id,
            "--config-name", name,
            "--mode", mode,
            "--alpha", str(alpha),
            "--no-mock",
            "--x-point", ",".join(f"{v:.6f}" for v in x),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(PROJECT_ROOT),
            )
            rec["pid"] = proc.pid
            rec["started_at"] = time.time()
            print(f"[closed_loop] launched {name} pid={proc.pid} log={log_path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"launch[{name}]: {exc}")
        children[name] = rec
        if idx < len(pending) - 1:
            time.sleep(stagger)
    # launched_names must reflect Popens that ACTUALLY fired this round, not
    # `children.keys()` — otherwise stale-cluster skips silently fill the dict
    # with names that were never launched, defeating node_barrier's empty-guard
    # at :474-479 and causing a 240-min silent hang.
    # See wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md.
    launched_this_round = sorted(n for n, rec in children.items() if rec.get("pid"))
    completed = list(state.get("completed_names", []))
    for name in sorted(children):
        if children[name].get("pid"):
            continue
        if _child_in_leaderboard(name, mode) or _child_is_broken(name):
            # Legit resume — barrier will mark done on first poll tick.
            continue
        # Stale *_cluster.txt only: skipped by _already_running but no
        # leaderboard row and no broken.txt → grid was submitted by a prior
        # aborted run that never harvested. The barrier will never resolve
        # this child (no terminal checkpoint under the freshly-minted thread_id
        # either). Route to completed_names so the round terminates, with a
        # loud per-name error so the operator sees what happened.
        msg = (f"launch_children[r{state['round_idx']}]: SKIP {name} — stale "
               f"*_cluster.txt in {_child_state_dir(name)} (prior aborted submit, "
               f"no leaderboard row). Run "
               f"`rm {_child_state_dir(name)}/*_cluster.txt` and relaunch, or "
               f"use a different --name-prefix.")
        print(f"[closed_loop] {msg}", flush=True)
        errors.append(msg)
        completed.append(name)
    return {
        "children": children,
        "launched_names": launched_this_round,
        "completed_names": completed,
        "errors": errors,
    }


def node_barrier(state: RoundState) -> dict:
    """Block until every child resolves (terminal checkpoint, leaderboard row,
    broken.txt, or dead process) or STOP_FLAG appears.

    There is deliberately NO per-round pacing timeout. Child process liveness
    is the wait condition: an alive `graph.run` child is always progressing
    toward resolution (every grid stage inside it is bounded by pipeline.py's
    poll `cap_hours`), and a dead one is marked completed-failed within two
    poll ticks. Wall-clock windows were only ever a proxy for "will this
    child resolve?" and the proxy caused two orphan-storm incidents
    (foilsg03 @240min, foilsg05 @360min — see
    wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md).

    barrier_max_min (default 24h) is a loud BACKSTOP for the one remaining
    pathology — a child that is alive but hung — not round pacing. Tripping
    it should be rare and is always worth investigating."""
    poll = state.get("barrier_poll_sec", CLOSED_LOOP_BARRIER_POLL_SEC)
    max_min = state.get("barrier_max_min", CLOSED_LOOP_BARRIER_MAX_MIN)
    start = time.time()
    deadline = start + max_min * 60
    stop_seen = False
    timeout_seen = False
    mode = state["mode"]
    children = state["children"]
    launched = state.get("launched_names", [])
    # Hard guard: barrier on an empty launch set is always a state-management
    # bug (children dict cleared/replaced between launch_children and barrier).
    # all(n in completed for n in {}) == True would otherwise exit silently.
    if not launched:
        raise RuntimeError(
            f"barrier[r{state.get('round_idx')}]: launched_names empty — "
            f"state pipeline corrupted between launch_children and barrier "
            f"(children dict was replaced or never written)"
        )
    completed = set(state.get("completed_names", []))
    errors = list(state.get("errors", []))
    conn = _open_saver_conn()
    saver = SqliteSaver(conn)
    # Compile the inner child graph once so we can call get_state(cfg).next
    # against each child's thread_id. CheckpointTuple has no .next field;
    # only StateSnapshot does, and StateSnapshot only comes from a compiled
    # graph attached to the saver.
    sys.path.insert(0, str(PROJECT_ROOT))
    from graph.build import build_graph  # noqa: WPS433
    child_graph = build_graph().compile(checkpointer=saver)
    # All resolution state (sticky per-child Resolution + the dead-PID grace
    # set) lives in the ChildTracker; the barrier consumes transitions and
    # maps them to log/error lines. See graph/child_tracker.py.
    tracker = ChildTracker(children, _DiskSignals(mode, child_graph),
                           already_done=completed)
    rolling = state.get("rolling", False)
    resolved_since_entry = 0
    try:
        while True:
            transitions = tracker.tick()
            resolved_since_entry += len(transitions)
            for name, res in sorted(transitions.items()):
                if res is Resolution.DONE_TERMINAL_NO_ROW:
                    # Graph ended via preflight-fail / stage-fail. Count as done.
                    errors.append(
                        f"barrier[{name}]: terminal checkpoint but no leaderboard "
                        f"row (likely preflight/stage failure)"
                    )
                elif res is Resolution.DEAD_UNRESOLVED:
                    # Crashed mid-write (foilsf08 SqliteSaver shape) — the
                    # process can never produce a resolution artifact.
                    pid = (children.get(name) or {}).get("pid")
                    msg = (
                        f"barrier[{name}]: child process {pid} died "
                        f"without resolution (no leaderboard row / "
                        f"broken.txt / terminal checkpoint)"
                    )
                    print(f"[closed_loop] {msg}", flush=True)
                    errors.append(msg)
            if tracker.all_resolved():
                print(f"[closed_loop] barrier: all {len(children)} children resolved", flush=True)
                break
            if rolling and resolved_since_entry >= 1:
                # Rolling: don't wait for the slowest-of-q tail — hand the
                # freed slot(s) back to decide_next/predict_picks for
                # replenishment while the rest keep running.
                print(f"[closed_loop] barrier[w{state.get('round_idx')}]: "
                      f"rolling — {resolved_since_entry} resolved, "
                      f"{tracker.pending_count()} still in flight; replenishing",
                      flush=True)
                break
            if _stop_requested():
                stop_seen = True
                msg = (
                    f"barrier[r{state['round_idx']}]: STOP_FLAG seen, exiting "
                    f"({len(tracker.done_names())}/{len(children)} children resolved)"
                )
                print(f"[closed_loop] {msg}", flush=True)
                errors.append(msg)
                break
            if time.time() > deadline:
                timeout_seen = True
                msg = (
                    f"barrier[r{state['round_idx']}]: backstop cap "
                    f"{max_min}min reached with "
                    f"{tracker.pending_count()} children still pending "
                    f"AND alive — investigate (alive children should always "
                    f"resolve via their internal stage caps)"
                )
                print(f"[closed_loop] {msg}", flush=True)
                errors.append(msg)
                break
            time.sleep(poll)
    finally:
        conn.close()
    completed = set(state.get("completed_names", [])) | tracker.done_names()
    return {
        "completed_names": sorted(completed),
        "errors": errors,
        "stop_seen": stop_seen,
        "timeout_seen": timeout_seen,
    }


def node_decide_next(state: RoundState) -> dict:
    """Bump round_idx; check zero-row safety break; clear children for next round.

    Zero-row break: fires only when ALL of this round's launched children
    resolved AND the round added 0 new leaderboard rows compared to
    predict_picks's snapshot — i.e. every child genuinely failed
    (preflight-fail, scan_logs-broken, harvest crash). Continuing would
    refit on identical data and re-propose the same picks (foilsX04
    failure mode, 2026-05-29) — exit instead.

    A barrier timeout with children still pending must NOT trip the break:
    those children are running normally and their rows land later (foilsg03 /
    foilsg05 false-positive, see
    wiki/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md).
    Gate on this round's launched set, not the raw completed count —
    completed_names is cumulative across rounds, so a raw count comparison
    is trivially satisfied at round N>0.
    """
    mode = state["mode"]
    before = state.get("history_len_before", 0)
    after = _leaderboard_len(mode)
    new_rows = after - before

    if state.get("rolling"):
        # Rolling: no per-round clear — resolved children stay in the dict
        # (tracker pre-seeds them done via already_done) and the pool
        # replenishes. The zero-rows guard generalizes to a STREAK: q
        # consecutive rowless resolutions == a full pool's worth all failed
        # (the foilsX04 shape) -> abort.
        completed = set(state.get("completed_names", []))
        children = state.get("children", {})
        # Name-based streak accounting (fixes rolling-no-row-streak-false-
        # increment): a resolved child produced a row IFF its config name is in
        # the leaderboard. The old count comparison (len-delta vs new_rows)
        # raced the per-wave baseline refresh, so a row absorbed into a prior
        # wave's baseline made a SUCCESSFUL child read as rowless. Names are
        # immune to that timing — a child only enters completed_names after its
        # evaluate node has appended the row. Reset the streak on ANY newly
        # resolved child that produced a row; else add the rowless ones.
        prev_names = set(state.get("prev_completed_names", []))
        newly_resolved = completed - prev_names
        lb_names = _leaderboard_names(mode)
        rowless = [n for n in newly_resolved if n not in lb_names]
        resolved_this_wave = len(newly_resolved)
        streak = (0 if any(n in lb_names for n in newly_resolved)
                  else state.get("no_row_streak", 0) + len(rowless))
        launched_total = len(set(children) | completed)
        n_pending = sum(1 for n in children if n not in completed)
        rolling_done = (launched_total >= state["max_evals"]) and n_pending == 0
        abort = streak >= state["q"]
        print(f"[closed_loop] decide_next[w{state['round_idx']}]: rolling "
              f"+{new_rows} rows, resolved_wave={resolved_this_wave}, "
              f"no_row_streak={streak}/{state['q']}, "
              f"launched={launched_total}/{state['max_evals']}, "
              f"in_flight={n_pending}"
              + (" — ABORT (streak = full pool of rowless resolutions)"
                 if abort else "")
              + (" — DONE (budget spent, pool drained)" if rolling_done else ""),
              flush=True)
        return {
            "round_idx": state["round_idx"] + 1,
            "zero_rows": abort,
            "no_row_streak": streak,
            "prev_completed_names": sorted(completed),
            "rolling_done": rolling_done,
            "stop_seen": state.get("stop_seen", False),
            "timeout_seen": state.get("timeout_seen", False),
            # children/launched_names intentionally NOT cleared in rolling.
        }

    launched = state.get("launched_names", []) or []
    completed = set(state.get("completed_names", []))
    this_round_done = sum(1 for n in launched if n in completed)
    all_resolved = bool(launched) and this_round_done >= len(launched)
    zero_rows = (new_rows <= 0) and all_resolved
    if zero_rows:
        print(f"[closed_loop] decide_next[r{state['round_idx']}]: "
              f"0 new leaderboard rows + all {len(launched)} children resolved "
              f"(before={before} after={after}) — all failed; exiting early",
              flush=True)
    elif new_rows <= 0:
        print(f"[closed_loop] decide_next[r{state['round_idx']}]: "
              f"0 new rows but {len(launched) - this_round_done}/{len(launched)} "
              f"children still pending after barrier — carrying round forward "
              f"(NOT exiting)", flush=True)
    else:
        print(f"[closed_loop] decide_next[r{state['round_idx']}]: "
              f"+{new_rows} new rows (before={before} after={after})", flush=True)
    return {
        "round_idx": state["round_idx"] + 1,
        "zero_rows": zero_rows,
        "stop_seen": state.get("stop_seen", False),
        "timeout_seen": state.get("timeout_seen", False),
        "children": {},
        "launched_names": [],
        # completed_names intentionally persists across rounds.
    }


def route_after_decide(state: RoundState):
    if state.get("zero_rows"):
        return END
    if state.get("stop_seen") or _stop_requested():
        # stop_seen is the barrier's recorded observation; the live re-check is
        # belt-and-suspenders for a flag raised after the barrier exited. Keying
        # on stop_seen alone would race an operator who rm's the flag between
        # barrier exit and this edge (~ms window).
        return END
    if state.get("rolling"):
        if state.get("rolling_done"):
            return END
        if state.get("timeout_seen"):
            # 24h backstop tripped with a hung-but-alive child pinning a pool
            # slot; the budget can never advance. Loud END beats a 24h-per-wave
            # infinite loop (barrier-mode semantics differ: rounds there end
            # via max_rounds).
            return END
        return "renew_token"
    if state["round_idx"] >= state["max_rounds"]:
        return END
    return "renew_token"


# ============================================================================
# Graph wiring
# ============================================================================

def _build_outer_graph():
    g = StateGraph(RoundState)
    g.add_node("renew_token", node_renew_token)
    g.add_node("predict_picks", node_predict_picks)
    g.add_node("assign_names", node_assign_names)
    g.add_node("launch_children", node_launch_children)
    g.add_node("barrier", node_barrier)
    g.add_node("decide_next", node_decide_next)

    g.set_entry_point("renew_token")
    g.add_edge("renew_token", "predict_picks")
    g.add_edge("predict_picks", "assign_names")
    g.add_edge("assign_names", "launch_children")
    g.add_edge("launch_children", "barrier")
    g.add_edge("barrier", "decide_next")
    g.add_conditional_edges("decide_next", route_after_decide,
                            {"renew_token": "renew_token", END: END})
    return g


# ============================================================================
# CLI
# ============================================================================

_DRY_RUN_KNOB_LABELS = {
    # foils v2 is 6D per-side decoupled; must match FoilsMode.build_space order.
    "foils":   ("rOut_up", "rOut_dn", "hT_up", "hT_dn", "rIn_up", "rIn_dn"),
    # foilsf (v3) swaps the rIn dims for hole-fractions f = rIn/rOut.
    "foilsf":  ("rOut_up", "rOut_dn", "hT_up", "hT_dn", "f_up", "f_dn"),
    "foilsflash": ("rOut_up", "rOut_dn", "hT_up", "hT_dn", "f_up", "f_dn"),
    # foilsg: 4 z-groups × (rOut, hT, f) — 12 knobs, FoilsGroupMode.build_space order.
    "foilsg":  tuple(f"{k}_g{g}" for g in range(4) for k in ("rOut", "hT", "f")),
    # ipa: 5D IPA geometry, IPAMode.build_space order.
    "ipa":     ("thickness", "halfLength", "OutRadius0", "OutRadius1", "distFromTargetEnd"),
    # prodtarget6d: 6D rOut+thickness profile (N=35 fixed, lug derived).
    "prodtarget6d": ("r0", "r1", "r2", "t0", "t1", "t2"),
}


def _dry_run(args: argparse.Namespace) -> int:
    picks = _botorch_picks_subprocess(args.mode, args.q, round_idx=0, picker=args.picker)
    print(f"[dry-run] round 0: {len(picks)} picks (mode={args.mode}, picker={args.picker})")
    labels = _DRY_RUN_KNOB_LABELS.get(args.mode, tuple(f"x{i}" for i in range(len(picks[0]) if picks else 0)))
    for j, p in enumerate(picks):
        name = f"{args.name_prefix}R00_{j:02d}"
        kv = " ".join(f"{labels[i]}={p[i]:.4g}" for i in range(len(p)))
        print(f"  {name}: {kv}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=DEFAULT_MODE,
                    choices=sorted(_modes.SPECS))
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--q", type=int, default=CLOSED_LOOP_Q)
    ap.add_argument("--max-rounds", type=int, default=CLOSED_LOOP_MAX_ROUNDS)
    ap.add_argument("--name-prefix", default="bo",
                    help="child names will be {prefix}R{round:02d}_{j:02d} "
                         "(R is the round marker, not part of the prefix)")
    ap.add_argument("--stagger", type=int, default=CLOSED_LOOP_STAGGER_SEC,
                    help="seconds between successive child launches")
    ap.add_argument("--barrier-poll-sec", type=int, default=CLOSED_LOOP_BARRIER_POLL_SEC)
    ap.add_argument("--barrier-timeout-min", type=int, default=None,
                    help="DEPRECATED, ignored. The barrier waits on child "
                         "process liveness; see --barrier-max-min for the "
                         "hung-child backstop")
    ap.add_argument("--barrier-max-min", type=int, default=CLOSED_LOOP_BARRIER_MAX_MIN,
                    help="loud backstop cap on one round's barrier for "
                         "alive-but-hung children; NOT round pacing — "
                         "tripping it is always worth investigating")
    ap.add_argument("--thread-id", default=None,
                    help="if omitted, a fresh uuid is used; reuse to resume")
    ap.add_argument("--picker", choices=PICKER_CHOICES, default=DEFAULT_PICKER,
                    help="batch picker (all subprocess into .venv-botorch; "
                         "cl_min retired per ADR-0001). hybrid (~60%% qnehvi + "
                         "~40%% qnparego, the default) is recommended for "
                         "multi-objective lines; qnparego spreads picks across "
                         "the whole front; pareto_sob exploits the GP-mean "
                         "sob corner")
    ap.add_argument("--rolling", action="store_true",
                    help="rolling replenishment: keep q children in flight, "
                         "launching a pending-aware replacement as each one "
                         "resolves (kills the slowest-of-q round tail, "
                         "~+30-50%% evals/day). Budget = --max-evals; "
                         "--max-rounds is ignored")
    ap.add_argument("--max-evals", type=int, default=None,
                    help="rolling only: total evals to launch "
                         "(default q * max-rounds)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print round-0 picks + names without launching")
    args = ap.parse_args()

    if args.dry_run:
        return _dry_run(args)

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)
    conn = _open_saver_conn()
    saver = SqliteSaver(conn)
    graph = _build_outer_graph().compile(checkpointer=saver)

    thread_id = args.thread_id or f"closed-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}}
    init: RoundState = {
        "mode": args.mode,
        "alpha": args.alpha,
        "q": args.q,
        "max_rounds": args.max_rounds,
        "round_idx": 0,
        "name_prefix": args.name_prefix,
        "children": {},
        "completed_names": [],
        "errors": [],
        "stagger_sec": args.stagger,
        "barrier_poll_sec": args.barrier_poll_sec,
        "barrier_max_min": args.barrier_max_min,
        "picker": args.picker,
        "rolling": args.rolling,
        "max_evals": args.max_evals or args.q * args.max_rounds,
        "no_row_streak": 0,
        "prev_completed_names": [],
    }

    # Resolve the target leaderboard so the banner is self-incriminating: a
    # mode/prefix mismatch (e.g. --mode foils with a "foilsf" prefix landing
    # rows in v2 instead of v3) is then visible in the first log line rather
    # than only after R0 completes. See wiki [[leaderboards]] gotcha.
    try:
        import bo_driver as _bo  # noqa: WPS433
        _lb = str(_bo.MODES[args.mode].leaderboard)
    except Exception as _e:  # pragma: no cover - banner is best-effort
        _lb = f"<unresolved: {_e}>"
    budget = (f"rolling max_evals={init['max_evals']}" if args.rolling
              else f"max_rounds={args.max_rounds}")
    print(f"[closed_loop] thread_id={thread_id} q={args.q} {budget} "
          f"prefix={args.name_prefix} mode={args.mode} leaderboard={_lb} "
          f"picker={args.picker}", flush=True)
    if args.name_prefix.startswith("foilsf") and args.mode == "foils":
        print(f"[closed_loop] WARNING: prefix={args.name_prefix!r} looks like a "
              f"foilsf (v3 fractional) campaign but mode=foils writes v2 "
              f"(absolute rIn). Did you mean --mode foilsf?", flush=True)
    # Resume vs fresh: if a checkpoint exists for this thread_id, pass None
    # so LangGraph picks up from the last node instead of re-seeding state
    # (which would re-run predict_picks → assign_names → launch_children
    # and spawn duplicate grid children for the same configs).
    existing = graph.get_state(cfg) if thread_id else None
    if existing and existing.values:
        print(f"[closed_loop] resuming thread_id={thread_id} from next={existing.next}", flush=True)
        stream_input = None
    else:
        stream_input = init
    final = None
    for ev in graph.stream(stream_input, cfg, stream_mode="values"):
        final = ev
        snap = {
            "round_idx": ev.get("round_idx"),
            "completed": len(ev.get("completed_names", [])),
            "history_len_before": ev.get("history_len_before"),
            "zero_rows": ev.get("zero_rows"),
            "stop_seen": ev.get("stop_seen"),
            "timeout_seen": ev.get("timeout_seen"),
        }
        print(f"[closed_loop] {json.dumps(snap)}", flush=True)
    print(f"[closed_loop] done. final keys: {sorted((final or {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
