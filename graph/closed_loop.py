"""Rolling closed-loop BO campaign: a bounded work-pool parent.

The parent keeps `q` children in flight (`graph.run` subprocesses) and tops
up as each one exits, until `max_evals` have been launched and the pool
drains. All of that lives in `graph/pool.py::run_rolling`; this module wires
CLI args to it and keeps the pieces `run_rolling` depends on:

  renew_token              — kerberos + bearer refresh; passed as
                             `renew=renew_token` and called once before EVERY
                             child launch. Time-gated internally (see
                             RENEW_MIN_INTERVAL_S) so the call frequency
                             doesn't multiply exposure to the /cvmfs sourcing
                             flake class.
  _stop_requested          — the STOP_CLOSED_LOOP kill switch; passed as
                             `stop_flag=_stop_requested`.
  _botorch_picks_subprocess — the picker subprocess wrapper; what `pool.py`
                             calls in production, once per pick, and what
                             `--dry-run` previews.
  _leaderboard_names / _child_is_broken — the two signals `pool.py` reads
                             at resolution time (rows landed / broken.txt).

There is no LangGraph state machine and no SqliteSaver checkpoint for the
parent. A child resolves when its subprocess EXITS — `run_rolling`'s
`ThreadPoolExecutor` + `as_completed` IS the barrier. See graph/pool.py for
the rationale and the incidents that retires.

See wiki/concepts/closed-loop-bo-design.md and
wiki/drivers/closed-loop-runner.md.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))  # BO/pipeline modules

import modes as _modes  # noqa: E402

# MUST precede `from runtime import ...` below (and every lazy `import
# bo_driver` / `import pipeline` further down): both core/runtime.py (_SPEC)
# and core/pipeline.py (MODE) resolve the process's mode from
# AUTORESEARCH_MODE at IMPORT time and cannot be re-pointed later. The parent
# also passes --mode explicitly to each child, so it must not hand children an
# env that contradicts it. Precedence rules:
# core/modes.py::stamp_mode_from_argv; main() re-checks with
# assert_mode_stamped(). The RETURN VALUE becomes --mode's argparse default
# below, so `args.mode` IS the resolved mode rather than a second constant.
_MODE = _modes.stamp_mode_from_argv()

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from paths import GRAPH_DATA, GRID_DATA_ROOT, REPO_ROOT as PROJECT_ROOT  # noqa: E402
from runtime import (  # noqa: E402
    BOTORCH_VENV_PY,
    CLOSED_LOOP_MAX_ROUNDS,
    CLOSED_LOOP_Q,
    DEFAULT_ALPHA,
    STOP_FLAG,
)

from sourced_bash import run_sourced_bash  # noqa: E402

# Module-level (not lazy inside main()) so `run_rolling` is a patchable
# attribute of THIS module (cl.run_rolling) for tests/test_closed_loop.py.
# No circular-import hazard: pool.py imports closed_loop only inside its own
# function bodies.
from pool import child_name, run_rolling  # noqa: E402

# cl_min retired per ADR-0001: the closed loop must never import code outside
# this repo; all pickers route through in-repo botorch_predict.py in the
# project .venv.
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


# ============================================================================
# Renew token — wired into run_rolling as `renew=renew_token`
# ============================================================================

# Minimum spacing between successful renewals. run_rolling calls renew() once
# per LAUNCH (up to ~40 times in a q=20 max_evals=40 campaign). The cost is
# not wall time (kinit -R IS cheap) but FAILURE SURFACE: every call sources
# setupmu2e-art.sh from /cvmfs, a known flake class
# (wiki/incidents/sourced-env-stderr-swallowed.md and
# wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md -- the second is
# *triggered* by concurrent lock churn on exactly this path), and a
# persistent failure here is FATAL. krb5 lifetime is ~25h, so 30 min gives
# the same freshness guarantee at a twentieth of the exposure. Kept inside
# renew_token (not at the call site) so the gate can't be bypassed.
RENEW_MIN_INTERVAL_S = 30 * 60

_last_renewed_at = 0.0


def renew_token() -> None:
    """Refresh krb5 ticket + bearer token. A plain zero-arg callable per
    run_rolling's `renew` seam, called before every child launch. Time-gated:
    a no-op if the last successful renewal was under RENEW_MIN_INTERVAL_S ago.

    Campaigns run many hours wall; default krb5 lifetime is ~25h, so a long
    rolling run can outlive the ticket. The first post-expiry subprocess.run
    raises Errno 127 (ENOKEY) and the inner graph terminates before harvest —
    the eval is silently LOST (no leaderboard row, no loud failure) rather
    than visibly failed. See wiki/incidents/kerberos-mid-run-expiry.md.

    Hard gate: if `getToken` fails (proxy for "can we actually submit?"),
    `sys.exit(2)` with an actionable message. SystemExit is not an Exception
    subclass, so run_rolling's `except Exception` around a resolved future
    never swallows it; it propagates out of the launch loop and out of the
    `with ThreadPoolExecutor(...)` block, whose `shutdown(wait=True)` on
    unwind still drains already-launched children, so nothing already
    submitted to the grid is abandoned mid-flight. No new children launch
    past this point; already-submitted ones don't need the parent's local
    ticket. The FATAL print says so explicitly, because the drain can take
    hours and an operator watching the tail could mistake it for a hang.

    `kinit -R` is best-effort (failing is normal past the renewable
    lifetime); the load-bearing check is `getToken`.
    """
    global _last_renewed_at
    if time.time() - _last_renewed_at < RENEW_MIN_INTERVAL_S:
        return
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
        # helper. A persistent rc!=0 after retries is still FATAL (krb5 likely
        # expired); a transient flake recovers instead of hard-exiting the
        # whole campaign.
        r = run_sourced_bash(cmd, login=True, timeout=120, label="renew_token")
    except Exception as exc:  # noqa: BLE001
        msg = (f"[closed_loop] FATAL renew_token: getToken raised: {exc}. "
               f"Run `kinit` then retry. No new children will launch; "
               f"already-running children are being drained (may take up "
               f"to hours -- this has NOT hung) before this process exits "
               f"with code 2.")
        print(msg, flush=True)
        sys.exit(2)
    if r.returncode != 0:
        msg = (f"[closed_loop] FATAL renew_token: getToken rc={r.returncode}: "
               f"{r.stderr.strip()[:400]}. Run `kinit` (krb5 likely past "
               f"renewable lifetime) then retry. No new children will "
               f"launch; already-running children are being drained (may "
               f"take up to hours -- this has NOT hung) before this "
               f"process exits with code 2.")
        print(msg, flush=True)
        sys.exit(2)
    _last_renewed_at = time.time()
    print("[closed_loop] renew_token: krb5 + bearer refreshed", flush=True)


# ============================================================================
# Picker
# ============================================================================

def _botorch_picks_subprocess(mode: str, q: int, round_idx: int, picker: str = "qnehvi",
                              pending: list | None = None) -> list[tuple]:
    """Shell into the botorch venv for q picks (thin wrapper on bo.botorch_ask).

    bo.botorch_ask owns the subprocess + JSON round-trip; this wrapper pins
    the venv from runtime.BOTORCH_VENV_PY (the AUTORESEARCH_BOTORCH_VENV A/B
    seam) and keeps the list-of-tuples return contract.

    picker = any PICKER_CHOICES entry: "qnehvi" (multi-obj), "qlnei"
    (single-obj sob -- acquisition ONLY, it changes no stage chain),
    "pareto_sob" (GP-mean sob corner), "budget_sob" (same, constrained to the
    deployed damage budget), "qnparego" (random-Chebyshev-scalarization
    spread), "hybrid" (~60% qnehvi + ~40% qnparego; recommended for new
    multi-objective lines). `pending` carries in-flight x_points so
    replacements fantasize over them (X_pending) instead of re-picking a
    point already being measured; `run_rolling`'s `next_pick` hook passes it
    the literal in-flight set.
    """
    import bo_driver as bo  # noqa: WPS433  (env-independent; safe pre-stamp)
    raw = bo.botorch_ask(mode, q, seed_idx=round_idx, picker=picker,
                         pending=pending, venv_py=BOTORCH_VENV_PY)
    return [tuple(p) for p in raw]


# ============================================================================
# CLI
# ============================================================================

def _dry_run(args: argparse.Namespace) -> int:
    """Preview the picks and names a real launch would start with.

    Names come from `pool.child_name`, so an operator is never shown names the
    campaign will not use. The indices are only indicative: a live run
    advances past any name already resolved or with work in flight (see
    `pool._name_busy_reason`), and refits the GP between picks instead of
    drawing them as one batch.
    """
    picks = _botorch_picks_subprocess(args.mode, args.q, round_idx=0, picker=args.picker)
    print(f"[dry-run] first {len(picks)} picks (mode={args.mode}, "
          f"picker={args.picker})")
    # Labels come from the registry (ModeSpec.knob_names, ADR-0002), not a
    # hand-maintained table: the local copy this replaced covered 5 of 11
    # modes, so every JSON mode printed bare x0..xN with drifted labels.
    labels = _modes.SPECS[args.mode].knob_names
    for j, p in enumerate(picks):
        name = child_name(args.name_prefix, j)
        kv = " ".join(f"{labels[i]}={p[i]:.4g}" for i in range(len(p)))
        print(f"  {name}: {kv}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=_MODE,
                    choices=sorted(_modes.SPECS),
                    help="optimization line; defaults to AUTORESEARCH_MODE "
                         "if set, else modes.DEFAULT_MODE")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--q", type=int, default=CLOSED_LOOP_Q,
                    help="pool WIDTH: children kept in flight at once")
    ap.add_argument("--max-rounds", type=int, default=CLOSED_LOOP_MAX_ROUNDS,
                    help="NOT a round count -- there are no rounds. Used "
                         "only to derive a default --max-evals "
                         "(q * max-rounds) when --max-evals is omitted")
    ap.add_argument("--name-prefix", default="bo",
                    help="child names will be {prefix}R{i:02d}_00, i "
                         "counting launches (names already resolved or with "
                         "work in flight are skipped -- see "
                         "graph/pool.py::_name_busy_reason)")
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
                    help="print the first q picks + their names without "
                         "launching")
    args = ap.parse_args()
    # Loud, cheap: a mode disagreement between the CLI, the env stamp,
    # runtime._SPEC and pipeline.MODE is otherwise SILENT -- the grid just
    # runs another mode's events_per_job / njobs / grid tarball / stage chain,
    # a metric denominator error with no error surface
    # (wiki/incidents/events-per-job-mid-flight-edit.md).
    _modes.assert_mode_stamped(args.mode)

    if args.dry_run:
        return _dry_run(args)

    import paths as _paths
    import modes as _modes_verify
    _paths.verify(_modes_verify.SPECS.values())

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)

    # Resolve the target leaderboard so the banner is self-incriminating: a
    # mode/prefix mismatch (rows landing on the wrong board) is visible in the
    # first log line rather than only after the first eval completes. See
    # wiki/datasets/leaderboards.md.
    try:
        import bo_driver as _bo  # noqa: WPS433
        _lb = str(_bo.MODES[args.mode].leaderboard)
    except Exception as _e:  # pragma: no cover - banner is best-effort
        _lb = f"<unresolved: {_e}>"
    max_evals = args.max_evals or (args.q * args.max_rounds)
    print(f"[closed_loop] q={args.q} max_evals={max_evals} "
          f"prefix={args.name_prefix} mode={args.mode} leaderboard={_lb} "
          f"picker={args.picker}", flush=True)
    result = run_rolling(
        mode=args.mode, picker=args.picker, q=args.q, max_evals=max_evals,
        alpha=args.alpha, name_prefix=args.name_prefix,
        renew=renew_token, stop_flag=_stop_requested)
    # Tally by outcome reason so a multi-day log ends with the failure
    # breakdown on one line instead of scattered through thousands of
    # per-child lines.
    tally = Counter(oc.reason for oc in result["outcomes"])
    tally_str = ", ".join(f"{reason}={n}" for reason, n in
                          sorted(tally.items(), key=lambda kv: -kv[1]))
    print(f"[closed_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']} | {tally_str}",
          flush=True)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
