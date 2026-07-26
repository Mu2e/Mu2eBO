"""Load and validate JSON-defined modes into ModeSpec objects.

One JSON file per optimization line, in modes/. Every check happens at load
time so a typo is an import error, never a corrupt geometry six hours into a
campaign. STDLIB ONLY (see core/modes.py:1-8).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

# Mirror our own package-qualification when importing the sibling module: if
# we were loaded as `core.mode_json` (repo-root imports, __package__=="core"),
# resolve GeomTemplate the same way; if we were loaded as bare `mode_json`
# (bo_driver.py subprocess path, core/ alone on sys.path, __package__==""),
# resolve it bare too. A hardcoded qualified import breaks the bare path
# outright (no `core` package to find); a hardcoded bare import would, under
# the qualified path, load core/geom_template.py a SECOND time under a
# different sys.modules key -- reproducing the two-non-identical-classes bug
# Task 4 fixed for this exact class (see core/modes.py's tail comment).
if __package__:
    from core.geom_template import GeomTemplate
else:
    from geom_template import GeomTemplate

_REQUIRED_TOP = ("name", "software", "run", "knobs", "leaderboard",
                 "preflight", "geom")
_REQUIRED_SOFTWARE = ("musing", "grid_tarball")
_REQUIRED_RUN = ("stages", "harvest")
_REQUIRED_PREFLIGHT = ("fcl", "dumps_gdml", "verifies_foil_gdml",
                       "preserves_gdml", "checks_managed_overlap")
_REQUIRED_LEADERBOARD = ("columns", "obs_noise", "metrics")


def _need(d: dict, keys, where: str) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: missing required field(s) {missing}")


def load_mode_file(path: Path) -> "object":
    """Parse one mode JSON file into a ModeSpec. Raises ValueError on any
    schema problem, always naming the file."""
    # Local import (modes.py imports this module -- see the tail of
    # core/modes.py), mirroring __package__ for the same reason as the
    # GeomTemplate import above: this resolves whichever `modes` module is
    # ALREADY loaded (bare or `core.`-qualified) instead of a second,
    # non-identical copy with its own ModeSpec class.
    if __package__:
        from core.modes import ModeSpec
    else:
        from modes import ModeSpec

    where = str(path)
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{where}: invalid JSON: {exc}") from None

    _need(doc, _REQUIRED_TOP, where)
    software, run = doc["software"], doc["run"]
    leaderboard, preflight = doc["leaderboard"], doc["preflight"]
    _need(software, _REQUIRED_SOFTWARE, f"{where}[software]")
    _need(run, _REQUIRED_RUN, f"{where}[run]")
    _need(leaderboard, _REQUIRED_LEADERBOARD, f"{where}[leaderboard]")
    _need(preflight, _REQUIRED_PREFLIGHT, f"{where}[preflight]")

    knobs = doc["knobs"]
    if not knobs:
        raise ValueError(f"{where}[knobs]: at least one knob is required")
    for i, k in enumerate(knobs):
        _need(k, ("name", "min", "max", "fmt"), f"{where}[knobs[{i}]]")

    names = tuple(k["name"] for k in knobs)
    if len(set(names)) != len(names):
        raise ValueError(f"{where}[knobs]: duplicate knob names in {list(names)}")

    columns = tuple(leaderboard["columns"])
    if len(columns) != 4:
        raise ValueError(
            f"{where}[leaderboard]: 'columns' must have exactly 4 entries "
            f"(sob-like, second-objective, alpha, obj) to match "
            f"BOMode.format_row; got {list(columns)}")

    noise = leaderboard["obs_noise"]
    if noise is not None:
        if len(noise) != 2 or not all(v > 0 for v in noise):
            raise ValueError(
                f"{where}[leaderboard]: obs_noise must be 2 positive sigmas, "
                f"got {noise!r}")
        noise = tuple(float(v) for v in noise)

    metrics = {k: tuple(v) for k, v in leaderboard["metrics"].items()}
    for col in columns[:2]:
        if col not in metrics:
            raise ValueError(
                f"{where}[leaderboard.metrics]: no summary.json keys given for "
                f"column {col!r}")

    # Any name GeomTemplate can't resolve (typo, or a knob dropped from
    # `knobs` without updating the formulas that reference it -- both
    # observed failure modes) IS a knobs/geom lockstep break; say so
    # explicitly while keeping GeomTemplate's own detail (which names, where).
    try:
        geom = GeomTemplate.from_dict(doc["geom"], names, f"{where}[geom]")
    except ValueError as exc:
        raise ValueError(
            f"{where}: knobs and geom must stay in lockstep -- {exc}") from None

    spec = ModeSpec(
        name=doc["name"],
        musing=software["musing"],
        grid_tarball=software["grid_tarball"],
        grid_stages=tuple(run["stages"]),
        harvest_verb=run["harvest"],
        stage_target_overrides=dict(run.get("jobs_per_stage") or {}),
        presubmit_after={k: tuple(v)
                         for k, v in (run.get("presubmit_after") or {}).items()},
        bounds_lo=tuple(float(k["min"]) for k in knobs),
        bounds_hi=tuple(float(k["max"]) for k in knobs),
        int_dims=tuple(doc.get("int_dims") or ()),
        preflight_fcl=preflight["fcl"],
        dumps_gdml=preflight["dumps_gdml"],
        verifies_foil_gdml=preflight["verifies_foil_gdml"],
        preserves_gdml=preflight["preserves_gdml"],
        checks_managed_overlap=preflight["checks_managed_overlap"],
        knob_names=names,
        knob_fmts=tuple(k["fmt"] for k in knobs),
        metric_cols=columns,
        obs_noise=noise,
        geom=geom,
        metrics=metrics,
        leaderboard_rel=leaderboard["file"],
    )
    return spec


def load_mode_dir(directory: Path, existing: Dict[str, object]) -> Dict[str, object]:
    """Load every modes/*.json. A name already present in `existing` is a hard
    error: silently shadowing a Python mode would be a new way to build the
    wrong geometry."""
    if not directory.is_dir():
        return {}
    out: Dict[str, object] = {}
    for path in sorted(directory.glob("*.json")):
        spec = load_mode_file(path)
        # Registered modes must be findable by file name. Checked HERE, not in
        # load_mode_file, so test fixtures can be loaded from any path.
        if spec.name != path.stem:
            raise ValueError(
                f"{path}: mode name {spec.name!r} does not match its file name "
                f"{path.stem!r}; modes/ must stay greppable by name")
        if spec.name in existing or spec.name in out:
            raise ValueError(
                f"{path}: mode name {spec.name!r} collides with an existing "
                f"mode; JSON modes never override Python modes")
        out[spec.name] = spec
    return out
