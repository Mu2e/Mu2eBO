"""Load and validate JSON-defined modes into ModeSpec objects.

One JSON file per optimization line, in mode_specs/. Every check happens at load
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
# "note" and "int_dims" are legal top-level keys that are optional (no
# _need entry) -- listed here only so _reject_unknown doesn't flag them.
_ALLOWED_TOP = _REQUIRED_TOP + ("note", "int_dims")
_REQUIRED_SOFTWARE = ("musing", "grid_tarball")
_REQUIRED_RUN = ("stages", "harvest")
# jobs_per_stage/presubmit_after/stage_tuning are optional (default to
# empty when absent -- see load_mode_file below).
_ALLOWED_RUN = _REQUIRED_RUN + ("jobs_per_stage", "presubmit_after", "stage_tuning")
_REQUIRED_PREFLIGHT = ("fcl", "dumps_gdml", "verifies_foil_gdml",
                       "preserves_gdml", "checks_managed_overlap")
_REQUIRED_LEADERBOARD = ("file", "columns", "obs_noise", "metrics")
_ALLOWED_KNOB = ("name", "min", "max", "fmt")

# run.stage_tuning[<stage>] accepted keys, mirroring core/pipeline.py STAGES
# fields that a JSON mode is allowed to override. Anything else (a typo, or a
# STAGES field this schema doesn't cover) is a load error -- see I4/I5.
_STAGE_TUNING_KEYS = ("events_per_job", "memory_mb", "quorum")


def _need(d: dict, keys, where: str) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: missing required field(s) {missing}")


def _reject_unknown(d: dict, allowed, where: str) -> None:
    """Fail loud on a typo'd/unrecognized key instead of silently no-oping it
    -- e.g. 'jobs_per_stagez' parsing to stage_target_overrides={} with no
    error, or 'intdims' leaving int_dims=() and turning an integer knob
    continuous with nothing to say why."""
    unknown = set(d) - set(allowed)
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {sorted(unknown)}; accepted keys are "
            f"{sorted(allowed)}")


def _validate_stage_tuning(run: dict, where: str) -> Dict[str, Dict[str, object]]:
    """Validate + normalize run.stage_tuning (core/pipeline.py STAGES
    overrides applied on top of pipeline defaults -- see core/pipeline.py's
    _apply_stage_tuning). Defaults to {} when absent, never silently drops an
    unknown tuning key."""
    raw = run.get("stage_tuning")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}[run.stage_tuning]: must be an object of "
            f"{{stage: {{tuning}}}}, got {raw!r}")
    out: Dict[str, Dict[str, object]] = {}
    for stage, tuning in raw.items():
        sw = f"{where}[run.stage_tuning.{stage}]"
        if not isinstance(tuning, dict):
            raise ValueError(f"{sw}: must be an object, got {tuning!r}")
        _reject_unknown(tuning, _STAGE_TUNING_KEYS, sw)
        checked: Dict[str, object] = {}
        if "events_per_job" in tuning:
            v = tuning["events_per_job"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ValueError(
                    f"{sw}[events_per_job]: must be a positive int, got {v!r}")
            checked["events_per_job"] = v
        if "memory_mb" in tuning:
            v = tuning["memory_mb"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ValueError(
                    f"{sw}[memory_mb]: must be a positive int, got {v!r}")
            checked["memory_mb"] = v
        if "quorum" in tuning:
            v = tuning["quorum"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= 1):
                raise ValueError(
                    f"{sw}[quorum]: must be a float in (0, 1], got {v!r}")
            checked["quorum"] = float(v)
        out[stage] = checked
    return out


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
    _reject_unknown(doc, _ALLOWED_TOP, where)
    software, run = doc["software"], doc["run"]
    leaderboard, preflight = doc["leaderboard"], doc["preflight"]
    _need(software, _REQUIRED_SOFTWARE, f"{where}[software]")
    _reject_unknown(software, _REQUIRED_SOFTWARE, f"{where}[software]")
    _need(run, _REQUIRED_RUN, f"{where}[run]")
    _reject_unknown(run, _ALLOWED_RUN, f"{where}[run]")
    _need(leaderboard, _REQUIRED_LEADERBOARD, f"{where}[leaderboard]")
    _reject_unknown(leaderboard, _REQUIRED_LEADERBOARD, f"{where}[leaderboard]")
    _need(preflight, _REQUIRED_PREFLIGHT, f"{where}[preflight]")
    _reject_unknown(preflight, _REQUIRED_PREFLIGHT, f"{where}[preflight]")

    stages = run["stages"]
    if not isinstance(stages, list) or not stages or not all(
            isinstance(s, str) for s in stages):
        raise ValueError(
            f"{where}[run.stages]: must be a list of stage-name strings, "
            f"got {stages!r} (a bare string here silently becomes a tuple "
            f"of its characters)")

    stage_tuning = _validate_stage_tuning(run, where)

    knobs = doc["knobs"]
    if not knobs:
        raise ValueError(f"{where}[knobs]: at least one knob is required")
    for i, k in enumerate(knobs):
        _need(k, _ALLOWED_KNOB, f"{where}[knobs[{i}]]")
        _reject_unknown(k, _ALLOWED_KNOB, f"{where}[knobs[{i}]]")

    names = tuple(k["name"] for k in knobs)
    if len(set(names)) != len(names):
        raise ValueError(f"{where}[knobs]: duplicate knob names in {list(names)}")

    columns = tuple(leaderboard["columns"])
    if len(columns) != 4:
        raise ValueError(
            f"{where}[leaderboard]: 'columns' must have exactly 4 entries "
            f"(sob-like, second-objective, alpha, obj) to match "
            f"BOMode.format_row; got {list(columns)}")
    if columns[0] != "sob":
        raise ValueError(
            f"{where}[leaderboard]: columns[0] must be exactly 'sob', got "
            f"{columns[0]!r}. BOMode.load_history_row (core/bo_driver.py) "
            f"hardcodes row['sob'] when reading leaderboard history back; a "
            f"different first-column name raises KeyError there, which "
            f"load_history's `except (KeyError, ValueError): continue` "
            f"swallows silently -- yielding ZERO history rows and an "
            f"eternal BO cold-start instead of a visible error.")

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

    lb_file = leaderboard["file"]
    if not isinstance(lb_file, str) or Path(lb_file).is_absolute():
        raise ValueError(
            f"{where}[leaderboard]: 'file' must be a repo-relative path, got "
            f"{lb_file!r}. JsonMode builds the leaderboard path as "
            f"`ROOT / spec.leaderboard_rel`; pathlib's '/' operator silently "
            f"DISCARDS the left side when the right side is absolute, so an "
            f"absolute 'file' escapes the repo root instead of erroring.")

    geom = GeomTemplate.from_dict(doc["geom"], names, f"{where}[geom]")

    spec = ModeSpec(
        name=doc["name"],
        musing=software["musing"],
        grid_tarball=software["grid_tarball"],
        grid_stages=tuple(stages),
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
        leaderboard_rel=lb_file,
        stage_tuning=stage_tuning,
    )
    return spec


def load_mode_dir(directory: Path, existing: Dict[str, object]) -> Dict[str, object]:
    """Load every mode_specs/*.json. A name already present in `existing` is a
    hard error: silently shadowing a Python mode would be a new way to build
    the wrong geometry."""
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
                f"{path.stem!r}; mode_specs/ must stay greppable by name")
        if spec.name in existing or spec.name in out:
            raise ValueError(
                f"{path}: mode name {spec.name!r} collides with an existing "
                f"mode; JSON modes never override Python modes")
        out[spec.name] = spec
    return out
