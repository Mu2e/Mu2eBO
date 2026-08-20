"""Rolling closed-loop BO campaign: a bounded work-pool parent.

Keeps q `graph.run` children in flight until max_evals launched and the pool
drains (graph/pool.py::run_rolling -- its ThreadPoolExecutor + as_completed
IS the barrier; no LangGraph, no SqliteSaver). Wires CLI args and supplies
renew_token, _stop_requested, _botorch_picks_subprocess,
_leaderboard_names/_child_is_broken. See
wiki/concepts/closed-loop-bo-design.md, wiki/drivers/closed-loop-runner.md.
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

# MUST precede `from runtime import ...` (and lazy bo_driver/pipeline
# imports): core/runtime.py (_SPEC) and core/pipeline.py (MODE) resolve
# AUTORESEARCH_MODE at IMPORT time (core/modes.py::stamp_mode_from_argv).
# The return value becomes --mode's argparse default: args.mode IS the
# resolved mode.
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

# Module-level so tests can patch cl.run_rolling; no import cycle -- pool.py
# imports closed_loop only inside function bodies.
from pool import child_name, run_rolling  # noqa: E402

# cl_min retired per ADR-0001: the closed loop never imports code outside
# this repo; all pickers route through in-repo botorch_predict.py.
PICKER_CHOICES = ("qnehvi", "qlnei", "budget_sob", "hybrid")
DEFAULT_PICKER = "hybrid"


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


# Renewal spacing. The cost is FAILURE SURFACE, not wall time: each call
# sources setupmu2e-art.sh from /cvmfs, a known flake class
# (wiki/incidents/sourced-env-stderr-swallowed.md,
# wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md -- triggered by exactly
# this concurrent lock churn), and persistent failure is FATAL. krb5 lifetime
# ~25h, so 30 min gives the same freshness at 1/20 the exposure. Gated inside
# renew_token so call sites can't bypass it.
RENEW_MIN_INTERVAL_S = 30 * 60

_last_renewed_at = 0.0


def renew_token() -> None:
    """Refresh krb5 + bearer token (run_rolling's `renew` seam, called before
    every launch); no-op under RENEW_MIN_INTERVAL_S.

    A campaign can outlive the ~25h ticket: the post-expiry eval is silently
    LOST (wiki/incidents/kerberos-mid-run-expiry.md). getToken failure
    ("can we actually submit?") sys.exit(2)s -- SystemExit is not an
    Exception, so run_rolling never swallows it, and the ThreadPoolExecutor
    unwind still DRAINS already-launched children (the FATAL print says so:
    the drain can take hours and is not a hang). `kinit -R` is best-effort;
    getToken is the load-bearing check.
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
        # helper; persistent rc!=0 stays FATAL (krb5 likely expired).
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


def _botorch_picks_subprocess(mode: str, q: int, round_idx: int, picker: str = "qnehvi",
                              pending: list | None = None) -> list[tuple]:
    """Shell into the botorch venv for q picks (wraps bo.botorch_ask; venv
    pinned via runtime.BOTORCH_VENV_PY, the AUTORESEARCH_BOTORCH_VENV A/B
    seam). `pending` carries in-flight x_points so replacements fantasize
    over them (X_pending) instead of re-picking a point being measured."""
    import bo_driver as bo  # noqa: WPS433  (env-independent; safe pre-stamp)
    raw = bo.botorch_ask(mode, q, seed_idx=round_idx, picker=picker,
                         pending=pending, venv_py=BOTORCH_VENV_PY)
    return [tuple(p) for p in raw]


def _dry_run(args: argparse.Namespace) -> int:
    """Preview the picks and names a real launch would start with. Names come
    from pool.child_name so the preview cannot drift; indices are indicative
    only (a live run skips busy names and refits between picks)."""
    picks = _botorch_picks_subprocess(args.mode, args.q, round_idx=0, picker=args.picker)
    print(f"[dry-run] first {len(picks)} picks (mode={args.mode}, "
          f"picker={args.picker})")
    # Labels from the registry (ModeSpec.knob_names, ADR-0002).
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
                         "multi-objective lines; budget_sob exploits the "
                         "GP-mean sob corner inside the damage budget")
    ap.add_argument("--max-evals", type=int, default=None,
                    help="total evals to launch (default q * max-rounds)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the first q picks + their names without "
                         "launching")
    args = ap.parse_args()
    # Loud, cheap: a CLI/env-stamp/_SPEC/pipeline.MODE mode disagreement is
    # otherwise SILENT (wiki/incidents/events-per-job-mid-flight-edit.md).
    _modes.assert_mode_stamped(args.mode)

    if args.dry_run:
        return _dry_run(args)

    import paths as _paths
    import modes as _modes_verify
    _paths.verify(_modes_verify.SPECS.values())

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)

    # Resolve the target leaderboard so a mode/prefix mismatch (rows landing
    # on the wrong board) is visible in the first log line.
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
    tally = Counter(oc.reason for oc in result["outcomes"])
    tally_str = ", ".join(f"{reason}={n}" for reason, n in
                          sorted(tally.items(), key=lambda kv: -kv[1]))
    print(f"[closed_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']} | {tally_str}",
          flush=True)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
