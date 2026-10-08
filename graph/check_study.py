"""Check a study file before launch: it loads, its ${ARTIFACT} paths exist,
the launch check passes, and its geometry passes the pre-check at one point
(the middle of every knob's bounds, or --x). Nothing is submitted and no
board row is written. By hand:
  python -m graph.check_study foilspfbpz_ax
  python -m graph.check_study /path/to/draft.json --x=1.5,2 --json
  python -m graph.check_study ce_chain --executor local --parallel 1
The pre-check works in <GRID_DATA_ROOT>/check_<study>/, emptied at every run
(only when it holds the .check_study marker this command writes there);
<GRID_DATA_ROOT>/check_<study>.lock lets one check of a study run at a time.
A draft outside the study path is checked as if installed there, in place
of the study file of its name.
Exit 0: every check passed. Exit 1: a check failed (the report says which
and why; a check that caught an exception keeps its traceback in "detail").
Exit 2: a bad command line, or a target that is neither a file nor a study
on the study path. Exit 3: check_study itself broke; the traceback is on
stderr and, with --json, in the report's "error" (with the checks finished
before it).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

# Not modes, nor run (which imports it): importing modes loads every study,
# so one broken file would crash this check instead of being reported.
import paths  # noqa: E402
import study as st  # noqa: E402
from boards import board_for  # noqa: E402
from contract import EXECUTORS, ContractError, KitSet, launch_problems  # noqa: E402
from kits import KitError  # noqa: E402
from leaderboard import LeaderboardError  # noqa: E402
from point_dir import VERDICT, PointDir  # noqa: E402
from study_graph import build_study_graph, check_x  # noqa: E402

MODES_DIR = paths.REPO_ROOT / "mode_specs"
STUDY_PATH_ENV = "AUTORESEARCH_STUDY_PATH"
ALL_STUDIES = "every launch loads all studies"
MARKER = ".check_study"
CAMPAIGN = "check"


@dataclass
class Check:
    name: str
    status: str                     # "passed" | "failed" | "skipped"
    problems: List[str] = field(default_factory=list)
    note: str = ""
    detail: str = ""                # tracebacks of the exceptions it caught

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "problems": list(self.problems), "note": self.note,
                "detail": self.detail}


def _trace(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def _error_text(exc: Exception) -> str:
    """The loader reports a bad study as a ValueError naming the file; any
    other exception is a draft it did not expect, named by its type."""
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _study_files() -> List[Path]:
    return st.study_files(MODES_DIR, os.environ.get(STUDY_PATH_ENV))


def resolve_target(arg: str) -> Path:
    """A path (it ends in .json or contains '/') or the name of a study on
    the study path (mode_specs/ and $AUTORESEARCH_STUDY_PATH)."""
    if arg.endswith(".json") or "/" in arg:
        path = Path(arg)
        if not path.is_file():
            raise ValueError(f"{arg}: no such study file")
        return path
    for path in _study_files():
        if path.stem == arg:
            return path
    raise ValueError(f"no study named {arg!r} in mode_specs/ or "
                     f"${STUDY_PATH_ENV}; pass the file's path to check a "
                     f"draft")


def check_load(path: Path) -> Tuple[Check, Optional[object]]:
    """The study loads, its name is its file's stem, its board basename is
    not another study's, and every other study file on the study path loads
    (the runners load them all, so one broken file stops every launch)."""
    path = Path(path)
    problems: List[str] = []
    details: List[str] = []

    def unexpected(exc):
        # The loader's ValueError message is the whole story; anything else
        # is a draft it did not expect, so keep where it broke.
        if not isinstance(exc, ValueError):
            details.append(_trace(exc))

    study = None
    try:
        study = st.load_study_file(path)
    except Exception as exc:
        problems.append(_error_text(exc))
        unexpected(exc)
    if study is not None and study.name != path.stem:
        problems.append(f"study {study.name!r} is in {path.name}; the name "
                        f"must equal the file name")
    try:
        others = _study_files()
    except ValueError as exc:
        problems.append(f"{exc}; {ALL_STUDIES}")
        others = []
    board = Path(study.leaderboard_rel).name if study is not None else None
    me = path.resolve()
    on_path = any(other.resolve() == me for other in others)
    # A draft outside the study path is checked as if installed there: it
    # takes the place of the file of its name, which it would replace.
    installed = (list(others) if on_path else
                 [path if p.stem == path.stem else p for p in others])
    if not on_path and path not in installed:
        installed.append(path)
    for other in installed:
        if other.resolve() == me:
            continue
        try:
            o = st.load_study_file(other)
        except Exception as exc:
            problems.append(f"{other} fails to load ({_error_text(exc)}); "
                            f"{ALL_STUDIES}")
            unexpected(exc)
            continue
        # A study of the same name is this one: the target is a draft of it.
        if (study is not None and o.name != study.name
                and Path(o.leaderboard_rel).name == board):
            problems.append(f"leaderboard basename {board!r} is already used "
                            f"by {other}")
    if not problems:
        # What the runners do at import, for the rules across files the
        # checks above do not make (a name defined twice, two other studies
        # on one board).
        try:
            st.load_study_list(installed)
        except Exception as exc:
            problems.append(f"the study path fails to load "
                            f"({_error_text(exc)}); {ALL_STUDIES}")
            unexpected(exc)
    if problems:
        return Check("load", "failed", problems,
                     detail="\n".join(details)), None
    return Check("load", "passed"), study


def _strings(node, where: str):
    """(location, value) for every string in a JSON tree; the location is
    dotted keys with [i] for list indexes."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{where}.{key}" if where else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{where}[{i}]")
    elif isinstance(node, str):
        yield where, node


def check_artifacts(path: Path) -> Check:
    """Every '${ARTIFACT}/' value names a file or directory that exists. A
    miss would otherwise surface only when a kit opens it."""
    problems, seen = [], 0
    for where, value in _strings(json.loads(Path(path).read_text()), ""):
        if not value.startswith(st._ARTIFACT_TOKEN):
            continue
        seen += 1
        try:
            expanded = st.expand_artifact(value, where)
        except (ValueError, paths.PathsError) as exc:
            problems.append(f"{where}: {exc}")
            continue
        if not Path(expanded).exists():
            problems.append(f"{where}: {value} -> {expanded} does not exist")
    if problems:
        return Check("artifacts", "failed", problems)
    return Check("artifacts", "passed",
                 note="" if seen else "no ${ARTIFACT} paths")


def center_point(study) -> List[float]:
    """The middle of each knob's bounds; an int knob rounds down."""
    return [float((k.min + k.max) // 2) if k.type == "int"
            else (k.min + k.max) / 2 for k in study.knobs]


def report(study_name: str, path: str, point: Optional[dict],
           checks: List[Check]) -> dict:
    return {"study": study_name, "path": path,
            "ok": all(c.status == "passed" for c in checks),
            "crashed": False, "error": None,
            "point": point, "checks": [c.as_dict() for c in checks]}


def crash_report(study_name: str, path: str, point: Optional[dict],
                 checks: List[Check], exc: BaseException) -> dict:
    """check_study itself broke: the whole error, and the checks it had
    finished."""
    rep = report(study_name, path, point, checks)
    rep.update(ok=False, crashed=True,
               error={"type": type(exc).__name__, "message": str(exc),
                      "traceback": _trace(exc)})
    return rep


def render_text(rep: dict) -> str:
    lines = [f"check_study {rep['study']} ({rep['path']})"]
    if rep["point"] is not None:
        lines.append(f"point: {rep['point']}")
    for c in rep["checks"]:
        lines.append(f"{c['name']:9} {c['status'].upper()}  {c['note']}"
                     .rstrip())
        lines.extend(f"    - {p}" for p in c["problems"])
    if rep["crashed"]:
        err = rep["error"]
        lines.append(f"CRASHED: {err['type']}: {err['message']} (traceback "
                     f"on stderr)")
    else:
        lines.append("OK" if rep["ok"] else "FAILED")
    return "\n".join(lines)


def check_launch(study, kits, *, executor: str, parallel, config: str) -> Check:
    """The check graph.run makes before it writes anything: executor rules,
    Kerberos, the config name, every kit starts and reports a version, the
    params/metrics cross-check, each kit's step checks, and the board."""
    try:
        problems = launch_problems(study, kits, executor=executor,
                                   parallel=parallel, config_names=[config],
                                   board=board_for(study))
    except (KitError, ContractError, LeaderboardError, OSError) as exc:
        return Check("launch", "failed", [f"{type(exc).__name__}: {exc}"],
                     detail=_trace(exc))
    if problems:
        return Check("launch", "failed", problems)
    return Check("launch", "passed")


def prepare_scratch(config: str) -> Optional[str]:
    """Empty <GRID_DATA_ROOT>/<config>/ so no verdict of an earlier run is
    reused, but only a directory this command made (it holds the marker).
    Returns the problem, or None."""
    d = paths.GRID_DATA_ROOT / config
    marker = d / MARKER
    if d.exists() or d.is_symlink():
        if not marker.is_file() or d.is_symlink():
            return (f"{d} exists but was not made by check_study (no "
                    f"{MARKER} marker); left untouched")
        shutil.rmtree(d)
    d.mkdir(parents=True)
    marker.write_text("made by graph/check_study.py, which empties this "
                      "directory at every run\n")
    return None


def check_geometry(study, kits, *, x: List[float], config: str,
                   executor: str) -> Check:
    """derive -> render -> preflight at x, in a fresh scratch directory."""
    try:
        check_x(study, x)
    except ValueError as exc:
        return Check("geometry", "failed", [str(exc)])
    # Two checks of one study share its scratch directory: the second would
    # empty it under the first and read the first one's verdict as its own.
    lock = paths.GRID_DATA_ROOT / f"{config}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return Check("geometry", "failed", [
                f"another check_study of {study.name!r} is running ({lock} "
                f"is locked); rerun when it ends"])
        return _geometry_locked(study, kits, x=x, config=config,
                                executor=executor)


def _geometry_locked(study, kits, *, x, config, executor) -> Check:
    try:
        problem = prepare_scratch(config)
    except OSError as exc:
        return Check("geometry", "failed", [f"{type(exc).__name__}: {exc}"],
                     detail=_trace(exc))
    if problem:
        return Check("geometry", "failed", [problem])
    pd = PointDir.of(paths.GRID_DATA_ROOT, config)
    state_dir = pd.state
    graph = build_study_graph(
        study, config=config, campaign=CAMPAIGN, context={}, kits=kits,
        state_dir=state_dir, board=None, executor=executor,
        log=lambda m: print(m, file=sys.stderr, flush=True),
        through="preflight").compile()
    try:
        out = graph.invoke({"config_name": config, "x_point": x})
    except Exception as exc:
        # derive and render raise for a bad expression or profile; graph.run
        # would crash on it, here it is the check's verdict. The traceback
        # is kept: it may as well be a bug in the engine.
        trace = _trace(exc)
        print(trace, file=sys.stderr, end="", flush=True)
        return Check("geometry", "failed", [f"{type(exc).__name__}: {exc}"],
                     detail=trace)
    if out.get("broken"):
        return Check("geometry", "failed", [out.get("reason", "")])
    if study.preflight is not None:
        verdict = json.loads(pd.path(VERDICT).read_text())
        note = verdict.get("message") or "pre-check passed"
    elif study.geom is not None:
        note = "rendered, not pre-checked"
    else:
        note = "no geometry"
    return Check("geometry", "passed", note=note)


def run_checks(path: Path, x_arg: Optional[List[float]], *, executor: str,
               parallel, progress: dict) -> dict:
    """The four checks, in order. `progress` ({"study", "point", "checks"})
    holds what is done so far, for the report of a crash."""
    checks = progress["checks"]
    load, study = check_load(path)
    checks.append(load)
    if study is None:
        checks.extend(Check(name, "skipped", note="skipped: load failed")
                      for name in ("artifacts", "launch", "geometry"))
        return report(path.stem, str(path.resolve()), None, checks)
    progress["study"] = study.name
    x = x_arg if x_arg is not None else center_point(study)
    # Static, so it is reported even when the launch check fails. An --x
    # that does not fit the knobs has no point to name.
    try:
        check_x(study, x)
        bad_x = None
        progress["point"] = dict(zip(study.knob_names, x))
    except ValueError as exc:
        bad_x = str(exc)
    config = f"check_{study.name}"
    checks.append(check_artifacts(path))
    kits = KitSet(CAMPAIGN, executor=executor, parallel=parallel)
    try:
        launch = check_launch(study, kits, executor=executor,
                              parallel=parallel, config=config)
        checks.append(launch)
        if bad_x is not None:
            checks.append(Check("geometry", "failed", [bad_x]))
        elif launch.status == "passed":
            checks.append(check_geometry(study, kits, x=x, config=config,
                                         executor=executor))
        else:
            checks.append(Check("geometry", "skipped",
                                note="skipped: launch failed"))
    finally:
        kits.close()
    return report(study.name, str(path.resolve()), progress["point"], checks)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a study file's path, or the name of a "
                                   "study on the study path")
    ap.add_argument("--x", default=None,
                    help="comma-separated knob values, in the study's knob "
                         "order; default the middle of each knob's bounds")
    ap.add_argument("--executor", choices=EXECUTORS, default="grid",
                    help="the executor the launch check assumes, as graph.run")
    ap.add_argument("--parallel", type=int, default=None,
                    help="jobs at once on this node, with --executor local only")
    ap.add_argument("--json", action="store_true",
                    help="print one JSON object; log lines go to stderr")
    args = ap.parse_args(argv)
    try:
        path = resolve_target(args.target)
        x_arg = (None if args.x is None
                 else [float(v) for v in args.x.split(",")])
        if x_arg is not None and not all(math.isfinite(v) for v in x_arg):
            # A NaN would also make the report invalid JSON.
            raise ValueError(f"--x: every value must be a finite number, "
                             f"got {args.x!r}")
    except ValueError as exc:
        print(f"check_study: {exc}", file=sys.stderr)
        return 2
    progress = {"study": path.stem, "point": None, "checks": []}
    try:
        # Whatever the engine prints while checking goes to stderr, so
        # stdout holds the report alone.
        with contextlib.redirect_stdout(sys.stderr):
            rep = run_checks(path, x_arg, executor=args.executor,
                             parallel=args.parallel, progress=progress)
        code = 0 if rep["ok"] else 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        rep = crash_report(progress["study"], str(path.resolve()),
                           progress["point"], progress["checks"], exc)
        code = 3
    print(json.dumps(rep, indent=1) if args.json else render_text(rep),
          flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
