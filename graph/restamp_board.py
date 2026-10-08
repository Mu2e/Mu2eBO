"""Re-stamp an old leaderboard once, by hand, after proving that only kit
builds differ (spec
docs/superpowers/specs/2026-10-05-measure-identity-design.md).

Since 2026-10-05 a kit's version is hand-bumped: the anakit checkout commit and
the beamkit server version are a step's recorded build, no longer part of
the version. Rows measured before carry the old version strings, so their
measure_sha differs from what a launch computes now, and the launch check
refuses the board. This command moves such rows to the new measure_sha,
once, when it can prove the change is only the build:
  - every row of an old sha has its step records on disk (its point's
    state/<step>_results.json), and their handles are the row's;
  - those records' versions reproduce the row's measure_sha under today's
    study file (the study's measure basis is unchanged);
  - each kit's hand version (core/measure.py:hand_version) equals the
    kit's current version (no hand bump lies between them).
Rows of the committed archive board are never rewritten. All or nothing.

  python -m graph.restamp_board --study foilspfbpz_ax --why "..."            dry run
  python -m graph.restamp_board --study foilspfbpz_ax --why "..." --confirm  rewrite

--confirm copies the board to <board>.pre-restamp-<UTC time>.tsv, rewrites
the measure_sha column under the board's lock and appends one line per old
sha to <board>.restamp.jsonl. Exit 0: proven (or nothing to do); 2: refused.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from measure import (MixedVersions, hand_version,  # noqa: E402
                     recorded_versions)
from point_dir import PointDir  # noqa: E402


def old_build(kit: str, version: str) -> str:
    """The build an old-scheme version carried (`+<kit>-<build>`), or "-"."""
    m = re.search(rf"\+{re.escape(kit)}-([^+]+)", version)
    return m.group(1) if m else "-"


def _prove(study, rows, sha, grid_root, current, steps) -> tuple:
    """(versions, None) when every row of `sha` is proven, else
    (None, why)."""
    versions = None
    for row in rows:
        cfg = row["config"]
        pd = PointDir.of(grid_root, cfg)
        records = pd.adopted(steps)
        missing = [s for s in steps if s not in records]
        if missing:
            return None, (f"row {cfg}: no step record(s) {missing} in "
                          f"{pd.state}, so its measurement cannot be proven")
        handles = ",".join(f"{s}={records[s]['handle']}"
                           for s in sorted(records))
        if handles != row.get("handles"):
            return None, (f"row {cfg}: its handles {row.get('handles')!r} "
                          f"are not its records' {handles!r}")
        try:
            recorded = recorded_versions(records)
        except MixedVersions as exc:
            return None, f"row {cfg}: {exc}"
        got = study.measure_sha(recorded)
        if got != sha:
            return None, (f"row {cfg}: its records ({recorded}) give "
                          f"measure_sha {got[:12]}, not the row's "
                          f"{sha[:12]}: the study's measurement changed "
                          f"since it was measured; start a new board")
        for kit, version in sorted(recorded.items()):
            try:
                hand = hand_version(kit, version)
            except ValueError as exc:
                return None, f"row {cfg}: {exc}"
            if hand != current.get(kit):
                return None, (f"row {cfg}: kit {kit!r} was {version!r} "
                              f"(hand version {hand!r}) and is now "
                              f"{current.get(kit)!r}: a hand bump lies "
                              f"between them, so the numbers changed; "
                              f"start a new board")
        versions = versions or recorded
    return versions, None


def restamp(study, board, grid_root: Path, current: Dict[str, str],
            builds: Dict[str, Optional[str]], *, why: str, confirm: bool,
            user: str, now: float, log: Callable[[str], None] = print,
            anakit_log: Optional[Callable[[str, str], str]] = None) -> int:
    """Prove, print the plan, and with `confirm` rewrite. 0: proven or
    nothing to do; 2: refused (nothing written)."""
    new_sha = study.measure_sha(current)
    by_sha: Dict[str, List[dict]] = {}
    for row in board.live_rows():
        by_sha.setdefault(row["measure_sha"], []).append(row)
    old = {sha: rows for sha, rows in by_sha.items() if sha != new_sha}
    if not old:
        log(f"[restamp] {board.path}: nothing to do (every row is at "
            f"{new_sha[:12]}, or the board is empty)")
        return 0
    archive = board.archive_measure_shas()
    steps = [s.step for s in study.steps]
    plans, problems = [], []
    for sha, rows in sorted(old.items()):
        if sha in archive:
            problems.append(f"{sha[:12]}: rows of this sha are in the "
                            f"committed archive board {board.archive_path}, "
                            f"which is never rewritten")
            continue
        versions, bad = _prove(study, rows, sha, grid_root, current, steps)
        if bad:
            problems.append(f"{sha[:12]}: {bad}")
        else:
            plans.append((sha, rows, versions))
    for sha, rows, versions in plans:
        log(f"[restamp] {board.path}: {sha[:12]} -> {new_sha[:12]}, "
            f"{len(rows)} rows")
        for kit in sorted(versions):
            log(f"  {kit}: {versions[kit]} -> {current[kit]}; build "
                f"{old_build(kit, versions[kit])} -> {builds.get(kit) or '-'}")
        if "anakit" in versions and anakit_log is not None:
            try:
                changes = anakit_log(old_build("anakit", versions["anakit"]),
                                     builds.get("anakit") or "HEAD")
                log("  anakit analysis commits in between:")
                for line in changes.splitlines() or ["(none)"]:
                    log(f"    {line}")
            except Exception as exc:    # informational: never decides
                log(f"  git log failed: {exc}")
    if problems:
        for p in problems:
            log(f"[restamp] REFUSED: {p}")
        log("[restamp] nothing written (all or nothing)")
        return 2
    if not confirm:
        log("[restamp] dry run: nothing written; rerun with --confirm to "
            "rewrite")
        return 0
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    backup = board.path.with_name(f"{board.path.name}.pre-restamp-"
                                  f"{stamp}.tsv")
    n = board.restamp_rows({sha: new_sha for sha, _, _ in plans}, backup)
    record = board.path.with_name(board.path.name + ".restamp.jsonl")
    with open(record, "a") as fh:
        for sha, rows, versions in plans:
            fh.write(json.dumps({
                "study": study.name, "from": sha, "to": new_sha,
                "rows": len(rows), "from_versions": versions,
                "to_versions": dict(current),
                "from_builds": {k: old_build(k, v)
                                for k, v in versions.items()},
                "to_builds": dict(builds), "by": user, "time": now,
                "why": why, "backup": str(backup)}) + "\n")
    log(f"[restamp] re-stamped {n} rows of {board.path}; backup {backup}; "
        f"record {record}")
    return 0


def git_analysis_log(old: str, new: str) -> str:
    """The anakit checkout's analysis commits between two builds."""
    checkout = os.environ.get("AUTORESEARCH_ANAKIT")
    if not checkout:
        raise RuntimeError("AUTORESEARCH_ANAKIT is not set")
    r = subprocess.run(["git", "-C", checkout, "log", "--oneline",
                        f"{old}..{new}", "--", "tools/analyses/"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git exit {r.returncode}")
    return r.stdout.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--why", required=True,
                    help="why the build change does not change the numbers")
    ap.add_argument("--confirm", action="store_true",
                    help="rewrite the board (without it: a dry run)")
    args = ap.parse_args(argv)
    import modes as _modes
    import paths
    from boards import board_for
    from contract import ContractError, KitSet
    from kits import KitError
    if args.study not in _modes.STUDIES:
        print(f"[restamp] REFUSED: unknown study {args.study!r}", flush=True)
        return 2
    study = _modes.STUDIES[args.study]
    kits = KitSet("restamp", executor="grid")
    current, builds = {}, {}
    try:
        for name in sorted({s.kit for s in study.steps}):
            kit = kits.get(name)
            kit.start()
            current[name] = kit.version
            builds[name] = getattr(kit, "build", None)
    except (KitError, ContractError) as exc:
        print(f"[restamp] REFUSED: {exc}", flush=True)
        return 2
    finally:
        kits.close()
    return restamp(study, board_for(study), paths.GRID_DATA_ROOT, current,
                   builds, why=args.why, confirm=args.confirm,
                   user=os.environ.get("USER") or getpass.getuser(),
                   now=time.time(), log=lambda m: print(m, flush=True),
                   anakit_log=git_analysis_log)


if __name__ == "__main__":
    raise SystemExit(main())
