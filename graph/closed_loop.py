"""Rolling closed-loop BO campaign: a bounded work-pool parent.

The parent keeps `q` children in flight (`graph.run` subprocesses) and tops
up as each one exits, until `max_evals` have been launched and the pool
drains. All of that lives in `graph/pool.py::run_rolling`; this module wires
CLI args to it and keeps the pieces `run_rolling` depends on:

  renew_token             — kerberos + bearer refresh; passed to
                             run_rolling as `renew=renew_token` and called
                             once before EVERY child launch (not once per
                             round — there are no rounds anymore). kinit -R
                             on a healthy ticket is a cheap no-op, so the
                             higher call frequency is safe.
  predict_picks           — refit GP, return q picks (non-rolling shape;
                             kept for `--dry-run` and for anyone driving it
                             directly. `pool.py`'s own `_default_pick_source`
                             calls `_botorch_picks_subprocess` directly
                             rather than through this node).
  _botorch_picks_subprocess — the actual picker subprocess wrapper; this is
                             what `pool.py` calls in production.
  _leaderboard_names / _child_is_broken — the two signals `pool.py` reads
                             at resolution time (rows landed / broken.txt).

There is no outer LangGraph state machine anymore, and no SqliteSaver
checkpoint for the parent. A child resolves when its subprocess EXITS —
`run_rolling`'s `ThreadPoolExecutor` + `as_completed` IS the barrier. See
graph/pool.py for the full rationale and the incidents this retires
(barrier-false-positive-round1, closed-loop-barrier-timeout-zero-rows-
falsepos, closed-loop-final-round-orphan-children,
rolling-no-row-streak-false-increment).

See wiki/concepts/closed-loop-bo-design.md (being superseded by this
change) and wiki/drivers/closed-loop-runner.md.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))  # BO/pipeline modules

# Stamp AUTORESEARCH_MODE / AUTORESEARCH_NO_RUN1B BEFORE `from config import ...`
# — config.GRID_STAGES is selected from GRID_STAGES_BY_MODE at module-load time,
# and build.STAGE_NODES freezes it. argparse runs much later (in main()).
# Shared sniffers: graph/presniff.py. Issue Mu2eBO #15.
from presniff import presniff_mode, presniff_picker  # noqa: E402
import modes as _modes  # noqa: E402  (env-independent; safe pre-stamp)

presniff_mode()
presniff_picker()

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config import (  # noqa: E402
    BOTORCH_VENV_PY,
    CLOSED_LOOP_MAX_ROUNDS,
    CLOSED_LOOP_Q,
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRAPH_DATA,
    GRID_DATA_ROOT,
    PROJECT_ROOT,
    STOP_FLAG,
)

from sourced_bash import run_sourced_bash  # noqa: E402

# cl_min retired per ADR-0001 (2026-07-06, deleted 2026-07-11): the closed
# loop must never import code outside this repo; all pickers route through
# in-repo botorch_predict.py in the project .venv.
PICKER_CHOICES = ("qnehvi", "qlnei", "pareto_sob", "budget_sob",
                  "qnparego", "hybrid")
DEFAULT_PICKER = "hybrid"


# ============================================================================
# Helpers
# ============================================================================

def _stop_requested() -> bool:
    return STOP_FLAG.exists()


def _child_state_dir(name: str) -> Path:
    return GRID_DATA_ROOT / name / "state"


def _child_is_broken(name: str) -> bool:
    return (_child_state_dir(name) / "broken.txt").exists()


def _history(mode: str):
    """One flock-aware leaderboard read via the BO driver (which flocks)."""
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
    import bo_driver as bo  # noqa: WPS433
    return bo.MODES[mode].load_history()


def _leaderboard_names(mode: str) -> set:
    return {p.cfg for p in _history(mode)}


def _leaderboard_len(mode: str) -> int:
    return len(_history(mode))


# ============================================================================
# Renew token — wired into run_rolling as `renew=renew_token`
# ============================================================================

def renew_token() -> None:
    """Refresh krb5 ticket + bearer token. Called by run_rolling before
    every child launch (no `state`/round shape left — the pool has no
    rounds; this is a plain zero-arg callable, per run_rolling's `renew`
    injection seam).

    Closed-loop campaigns run many hours wall; default krb5 lifetime is ~25h,
    so a long rolling run can easily outlive the ticket. First post-expiry
    subprocess.run raises Errno 127 (ENOKEY) and the inner graph terminates
    before harvest — the eval is silently LOST (no leaderboard row, no loud
    failure) rather than visibly failed. See
    wiki/incidents/kerberos-mid-run-expiry.md.

    Hard gate: if `getToken` fails (proxy for "can we actually submit?"),
    `sys.exit(2)` with an actionable message. This is a SystemExit, not an
    Exception subclass, so it is never caught by run_rolling's
    `except Exception` around a resolved future's `.result()` — it
    propagates straight out of the launch loop, out of the
    `with ThreadPoolExecutor(...)` block (which still drains any already-
    launched, already-running children via its own `shutdown(wait=True)`
    on unwind, so nothing already submitted to the grid is abandoned
    mid-flight), out of run_rolling, out of main(), and terminates the
    process with exit code 2. No new children are launched past this
    point; children already handed to the grid are on their own from here
    (they don't need the parent's local ticket once submitted).

    `kinit -R` is best-effort (it's normal for it to fail if the ticket
    is past its renewable lifetime); the load-bearing check is `getToken`.
    """
    try:
        r = subprocess.run(["kinit", "-R"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"[closed_loop] renew_token: kinit -R rc={r.returncode}: "
                  f"{r.stderr.strip()[:200]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[closed_loop] renew_token: kinit -R failed: {exc}", flush=True)
    cmd = "source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh && getToken"
    try:
        # getToken shares the cvmfs/spack flake class -> retry via the shared
        # helper (was a bare one-shot subprocess.run). A persistent rc!=0 after
        # retries is still FATAL (krb5 likely expired); a transient flake now
        # recovers instead of hard-exiting the whole campaign.
        r = run_sourced_bash(cmd, login=True, timeout=120, label="renew_token")
    except Exception as exc:  # noqa: BLE001
        msg = (f"[closed_loop] FATAL renew_token: getToken raised: {exc}. "
               f"Run `kinit` then retry.")
        print(msg, flush=True)
        sys.exit(2)
    if r.returncode != 0:
        msg = (f"[closed_loop] FATAL renew_token: getToken rc={r.returncode}: "
               f"{r.stderr.strip()[:400]}. Run `kinit` (krb5 likely past "
               f"renewable lifetime) then retry.")
        print(msg, flush=True)
        sys.exit(2)
    print("[closed_loop] renew_token: krb5 + bearer refreshed", flush=True)


# ============================================================================
# Picker
# ============================================================================

def _botorch_picks_subprocess(mode: str, q: int, round_idx: int, picker: str = "qnehvi",
                              pending: list | None = None) -> list[tuple]:
    """Shell into the botorch venv for q picks (thin wrapper on bo.botorch_ask).

    Picker subprocess: bo.botorch_ask shells into BOTORCH_VENV_PY (the
    project .venv by default; AUTORESEARCH_BOTORCH_VENV overrides). It owns
    the subprocess + JSON round-trip; this wrapper pins the venv from
    config.BOTORCH_VENV_PY (the AUTORESEARCH_BOTORCH_VENV A/B seam) and
    keeps the historical list-of-tuples return contract.

    picker = any PICKER_CHOICES entry: "qnehvi" (multi-obj),
    "qlnei" (single-obj sob), "pareto_sob" (GP-mean sob corner),
    "budget_sob" (GP-mean sob corner constrained to the deployed damage
    budget), "qnparego" (random-Chebyshev-scalarization spread), "hybrid"
    (~60% qnehvi + ~40% qnparego; recommended for new multi-objective lines).
    `pending` carries in-flight x_points so replacements fantasize over them
    (X_pending) instead of re-picking a point that's already being measured.
    This is `graph/pool.py`'s test seam: `run_rolling`'s `next_pick` hook
    wraps this call and passes it the literal in-flight set.
    """
    import bo_driver as bo  # noqa: WPS433  (env-independent; safe pre-stamp)
    raw = bo.botorch_ask(mode, q, seed_idx=round_idx, picker=picker,
                         pending=pending, venv_py=BOTORCH_VENV_PY)
    return [tuple(p) for p in raw]


def node_predict_picks(state: dict) -> dict:
    """Refit GP, return q picks. Picker is one of PICKER_CHOICES.

    Not called by `main()` / `run_rolling` (which calls
    `_botorch_picks_subprocess` directly per-pick); kept for `--dry-run`
    parity and standalone use.

    All pickers subprocess into BOTORCH_VENV_PY (.venv by default) to run
    botorch_predict.py (cl_min retired per ADR-0001):
      qnehvi: multi-objective Pareto-HV picker; native acquisition is qNEHVI,
        not the scalarized obj the leaderboard reports.
      qlnei: single-obj qLogNoisyEI on sob only (drops the run1b_mubeam stage).
      pareto_sob: the GP-mean highest-sob frontier points.
      budget_sob: same corner, CONSTRAINED to predicted flash <= the deployed
        damage budget -- the deployment-facing exploit (pareto_sob's picks are
        typically unbuildable: +50-70% damage).
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

    picks = _botorch_picks_subprocess(mode, q, state["round_idx"], picker=picker)
    print(f"[closed_loop] predict_picks[r{state['round_idx']}]: "
          f"picker={picker} "
          f"q={q} got={len(picks)}", flush=True)
    if len(picks) < q:
        errors.append(
            f"predict_picks[r{state['round_idx']}]: only got {len(picks)}/{q} "
            f"picks (Pareto frontier too short or too clustered)"
        )
    transient = {f"_pick_{j:02d}": {"x_point": list(p)} for j, p in enumerate(picks)}
    return {
        "children": transient,
        "errors": errors,
        "history_len_before": _leaderboard_len(state["mode"]),
    }


# ============================================================================
# CLI
# ============================================================================

def _dry_run(args: argparse.Namespace) -> int:
    picks = _botorch_picks_subprocess(args.mode, args.q, round_idx=0, picker=args.picker)
    print(f"[dry-run] round 0: {len(picks)} picks (mode={args.mode}, picker={args.picker})")
    # Labels come from the registry (ModeSpec.knob_names, ADR-0002), not a
    # hand-maintained table: the local copy this replaced covered 5 of the 11
    # modes, so every JSON mode (foilspf, the A/B arms) printed bare x0..xN,
    # and its labels had drifted from the leaderboard column names.
    labels = _modes.SPECS[args.mode].knob_names
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
    ap.add_argument("--q", type=int, default=CLOSED_LOOP_Q,
                    help="pool WIDTH: children kept in flight at once")
    ap.add_argument("--max-rounds", type=int, default=CLOSED_LOOP_MAX_ROUNDS,
                    help="used only to derive a default --max-evals "
                         "(q * max-rounds) when --max-evals is omitted")
    ap.add_argument("--name-prefix", default="bo",
                    help="child names will be {prefix}R{wave:02d}_00")
    ap.add_argument("--picker", choices=PICKER_CHOICES, default=DEFAULT_PICKER,
                    help="batch picker (all subprocess into the picker venv; "
                         "cl_min retired per ADR-0001). hybrid (~60%% qnehvi + "
                         "~40%% qnparego, the default) is recommended for "
                         "multi-objective lines; qnparego spreads picks across "
                         "the whole front; pareto_sob exploits the GP-mean "
                         "sob corner")
    ap.add_argument("--max-evals", type=int, default=None,
                    help="total evals to launch (default q * max-rounds)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print round-0 picks + names without launching")
    args = ap.parse_args()

    if args.dry_run:
        return _dry_run(args)

    import paths as _paths
    import modes as _modes_verify
    _paths.verify(_modes_verify.SPECS.values())

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)

    # Resolve the target leaderboard so the banner is self-incriminating: a
    # mode/prefix mismatch (e.g. --mode foils with a "foilsf" prefix landing
    # rows in v2 instead of v3) is then visible in the first log line rather
    # than only after the first eval completes. See wiki [[leaderboards]].
    try:
        import bo_driver as _bo  # noqa: WPS433
        _lb = str(_bo.MODES[args.mode].leaderboard)
    except Exception as _e:  # pragma: no cover - banner is best-effort
        _lb = f"<unresolved: {_e}>"
    max_evals = args.max_evals or (args.q * args.max_rounds)
    print(f"[closed_loop] q={args.q} max_evals={max_evals} "
          f"prefix={args.name_prefix} mode={args.mode} leaderboard={_lb} "
          f"picker={args.picker}", flush=True)
    if args.name_prefix.startswith("foilsf") and args.mode == "foils":
        print(f"[closed_loop] WARNING: prefix={args.name_prefix!r} looks like a "
              f"foilsf (v3 fractional) campaign but mode=foils writes v2 "
              f"(absolute rIn). Did you mean --mode foilsf?", flush=True)

    from pool import run_rolling
    result = run_rolling(
        mode=args.mode, picker=args.picker, q=args.q,
        max_evals=args.max_evals or (args.q * args.max_rounds),
        alpha=args.alpha, name_prefix=args.name_prefix,
        renew=renew_token)
    print(f"[closed_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']}", flush=True)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
