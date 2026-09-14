#!/usr/bin/env python3
"""Launch-time gates for tools/run_grid.sh and tools/run_local.sh.

Every check here runs BEFORE the first job is queued, and each one exists
because its absence cost hours of wall clock at least once. They lived as
inline bash in the two launcher scripts until 2026-08-20; shell made them
untestable, so a renamed env var or a changed state-file suffix could
disable a gate with nothing failing. Here they are ordinary functions with
injected inputs, pinned by tests/test_launch_checks.py.

Each check returns a problem string or None. Nothing here exits or prints:
main() is the only place that decides what a problem means, so a caller
that wants to warn rather than die can.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harvest  # noqa: E402
import modes  # noqa: E402
import paths  # noqa: E402

# A grid chain submits stages for HOURS, not once at the start, so validity
# now is not enough -- the ticket has to outlive the chain. Local runs
# submit nothing but still stream resampler inputs from /pnfs over xrootd,
# so they need a ticket, just not a long one.
GRID_TICKET_SECONDS = 4 * 3600
QUOTA_ABORT_PCT = 90


def _klist_text() -> str | None:
    """Raw `klist` output, or None when there is no usable ticket cache."""
    try:
        p = subprocess.run(["klist"], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _parse_klist_time(stamp: str) -> int | None:
    """klist's local-time stamp as an epoch, or None if it does not parse.

    Both a 4- and 2-digit year are in the wild. Parsed here rather than
    shelled out to `date -d` so the result is a plain function of the string
    and the process timezone -- testable without a subprocess.
    """
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return int(datetime.strptime(stamp, fmt).timestamp())
        except ValueError:
            continue
    return None


def check_kerberos(min_seconds: int, *, klist_text=_klist_text,
                   now=time.time) -> str | None:
    """Ticket present, and with `min_seconds` of life left.

    A ticket that expires mid-run kills the chain at the next submit
    (wiki/incidents/kerberos-mid-run-expiry.md), and the prodtools input
    gate reports the resulting auth failure as "absent from dCache tape" --
    which reads as missing data, sending you to look at SAM instead of at
    your ticket.
    """
    text = klist_text() if callable(klist_text) else klist_text
    if not text:
        return "no valid Kerberos ticket -- run kinit first."
    krbtgt = [ln for ln in text.splitlines() if "krbtgt" in ln]
    if not krbtgt:
        return "no valid Kerberos ticket -- run kinit first."
    if min_seconds <= 0:
        return None
    # `MM/DD/YYYY HH:MM:SS  MM/DD/YYYY HH:MM:SS  krbtgt/...`: fields 3+4 are
    # the expiry. An unparseable line is NOT fatal -- klist's format is
    # locale-dependent, and refusing to launch over a date format would be
    # worse than the risk it guards.
    fields = krbtgt[0].split()
    if len(fields) < 4:
        return None
    expiry = _parse_klist_time(f"{fields[2]} {fields[3]}")
    if expiry is None:
        return None
    left = expiry - int(now())
    if left < min_seconds:
        return (f"Kerberos ticket has under {min_seconds // 3600} h left "
                f"({left // 60} min) -- a chain submits stages for hours and "
                f"will die at a later submit. Run 'kinit' before launching.")
    return None


def boards(data_root: Path = None) -> list[Path]:
    """Every board a config name could already appear in: the live tree
    (leaderboards AND pending files share it, both `*.tsv`) plus the
    committed archive."""
    live = (data_root or paths.DATA_ROOT) / "autoresearch_leaderboards"
    return sorted(live.glob("*.tsv")) + sorted(
        (paths.REPO_ROOT / "leaderboards").glob("*.tsv"))


def check_config_name_free(config: str, board_files) -> str | None:
    """A name already in a board or pending file makes propose_one raise,
    which langgraph reports as ~30 lines of traceback after the run has
    already started -- and on the grid path, after jobs are queued."""
    for board in board_files:
        try:
            for line in Path(board).read_text().splitlines():
                if line.split("\t")[0].strip() == config:
                    return (f"config name {config!r} is already used (in "
                            f"{board}) -- pick another, or pass no argument "
                            f"for a timestamped one")
        except OSError:
            continue
    return None


def check_no_stale_clusters(config: str, grid_root: Path = None) -> str | None:
    """Stale `*_cluster.txt` makes a re-run adopt the OLD cluster ids instead
    of submitting: `_already_running()` reads them, `pending` comes back
    empty, and the barrier polls forever having launched nothing
    (wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md). Silent,
    so it has to be caught here."""
    state = (grid_root or paths.GRID_DATA_ROOT) / config / "state"
    stale = sorted(state.glob("*_cluster.txt"))
    if stale:
        return (f"{config!r} already has cluster files under {state} "
                f"({', '.join(p.name for p in stale)}) -- pick a fresh name "
                f"rather than resuming by accident")
    return None


def quota_usage(volume: Path, *, getxattr=os.getxattr):
    """(used_bytes, quota_bytes) for a CephFS dir, or None where unset.

    Read the xattrs, never `df`: df reports the whole filesystem, not this
    directory's quota (wiki/incidents/data-quota-exhausted-grid-accumulation.md).
    """
    try:
        quota = int(getxattr(str(volume), "ceph.quota.max_bytes"))
        used = int(getxattr(str(volume), "ceph.dir.rbytes"))
    except (OSError, ValueError):
        return None
    return (used, quota) if quota > 0 else None


def quota_volume(start: Path, *, getxattr=os.getxattr):
    """The nearest ancestor of `start` (itself included) carrying a CephFS
    quota, with its usage -- or None if nothing up the chain has one.

    Walked rather than hardcoded: the quota sits on the operator's volume
    root while DATA_ROOT is often a sandbox subdirectory of it, and naming
    that root in tracked source is exactly what tests/test_no_hardcoded_paths
    forbids -- it would be one operator's path baked into everyone's launcher.
    """
    for candidate in (start, *start.parents):
        usage = quota_usage(candidate, getxattr=getxattr)
        if usage is not None:
            return candidate, usage
    return None


def check_quota(start: Path, *, getxattr=os.getxattr):
    """(problem, info) -- a full /exp/mu2e/data surfaces as Errno 122 EDQUOT
    from inside a stage submit, hours in."""
    found = quota_volume(start, getxattr=getxattr)
    if found is None:
        return None, None
    volume, (used, quota) = found
    pct = used * 100 // quota
    info = (f"{volume} at {pct}% of quota "
            f"({used / 1e12:.2f} of {quota / 1e12:.2f} TB)")
    if pct >= QUOTA_ABORT_PCT:
        return (f"{info} -- over {QUOTA_ABORT_PCT}%; free space before "
                f"launching. A full quota fails as Errno 122 from inside a "
                f"stage submit, hours in."), info
    return None, info


def check_prereqs(mode: str) -> str | None:
    """Artifacts and prodtools, each resolved by the module that owns it.

    An artifact miss otherwise surfaces three preflight retries later as a
    bare "ambiguous"; an unset or mistyped AUTORESEARCH_PRODTOOLS dies from
    deep inside the first stage submit, since prodtools builds and runs
    every job -- local ones too.
    """
    try:
        paths.verify([modes.SPECS[mode]], extra=harvest.REQUIRED_ARTIFACTS,
                     make_dirs=False)
        paths.prodtools_root()
    except KeyError:
        return (f"unknown mode {mode!r} -- known modes: "
                f"{', '.join(sorted(modes.SPECS))}")
    except (paths.PathsError, SystemExit) as e:
        return str(e)
    return None


def stage_width(mode: str) -> str:
    """The per-stage grid width read from the mode spec rather than restated,
    so the launch banner cannot drift from what actually gets submitted."""
    spec = modes.SPECS[mode]
    return ", ".join(
        f"{s} {spec.stage_target_overrides.get(s, '?')}x"
        f"{spec.stage_tuning.get(s, {}).get('events_per_job', '?')}"
        for s in spec.grid_stages)



def run_checks(mode: str, config: str, *, grid: bool):
    """(problems, infos) for one launch. Grid-only gates are the ones whose
    failure mode needs a queue: a ticket long enough to outlive the chain,
    adopted-cluster silence, and the shared /exp/mu2e/data quota."""
    problems, infos = [], []
    problems.append(check_kerberos(GRID_TICKET_SECONDS if grid else 0))
    problems.append(check_config_name_free(config, boards()))
    if grid:
        problems.append(check_no_stale_clusters(config))
        problem, info = check_quota(paths.DATA_ROOT)
        problems.append(problem)
        infos.append(info)
    problems.append(check_prereqs(mode))
    if grid:
        infos.append(f"stages -- {stage_width(mode)}")
    return [p for p in problems if p], [i for i in infos if i]



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--grid", action="store_true",
                    help="apply the gates that only a queued chain needs")
    args = ap.parse_args(argv)

    label = "run_grid" if args.grid else "run_local"
    problems, infos = run_checks(args.mode, args.config, grid=args.grid)
    for info in infos:
        print(f"{label}: {info}")
    # stderr is unbuffered and stdout is not, so without this the problems
    # print ABOVE the context that explains them.
    sys.stdout.flush()
    for problem in problems:
        print(f"{label}: {problem}", file=sys.stderr)
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
