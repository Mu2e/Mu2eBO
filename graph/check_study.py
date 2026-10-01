"""Check a study file before launch: it loads, its ${ARTIFACT} paths exist,
the launch check passes and its geometry passes the pre-check at one point.
Nothing is submitted and no board row is written."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

# Not modes, nor run (which imports it): importing modes loads every study,
# so one broken file would crash this check instead of being reported.
import paths  # noqa: E402
import study as st  # noqa: E402

MODES_DIR = paths.REPO_ROOT / "mode_specs"
STUDY_PATH_ENV = "AUTORESEARCH_STUDY_PATH"
ALL_STUDIES = "every launch loads all studies"


@dataclass
class Check:
    name: str
    status: str                     # "passed" | "failed" | "skipped"
    problems: List[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "problems": list(self.problems), "note": self.note}


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
    study = None
    try:
        study = st.load_study_file(path)
    except Exception as exc:
        problems.append(_error_text(exc))
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
    for other in others:
        if other.resolve() == me:
            continue
        try:
            o = st.load_study_file(other)
        except Exception as exc:
            problems.append(f"{other} fails to load ({_error_text(exc)}); "
                            f"{ALL_STUDIES}")
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
            st.load_study_dirs(MODES_DIR, os.environ.get(STUDY_PATH_ENV))
        except Exception as exc:
            problems.append(f"the study path fails to load "
                            f"({_error_text(exc)}); {ALL_STUDIES}")
    if problems:
        return Check("load", "failed", problems), None
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
            "point": point, "checks": [c.as_dict() for c in checks]}


def render_text(rep: dict) -> str:
    lines = [f"check_study {rep['study']} ({rep['path']})"]
    if rep["point"] is not None:
        lines.append(f"point: {rep['point']}")
    for c in rep["checks"]:
        lines.append(f"{c['name']:9} {c['status'].upper()}  {c['note']}"
                     .rstrip())
        lines.extend(f"    - {p}" for p in c["problems"])
    lines.append("OK" if rep["ok"] else "FAILED")
    return "\n".join(lines)
