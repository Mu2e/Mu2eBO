"""Load and validate JSON-defined modes into ModeSpec objects.

One JSON file per optimization line, in mode_specs/. Every check happens at load
time so a typo is an import error, never a corrupt geometry six hours into a
campaign. STDLIB ONLY (see core/modes.py:1-8).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

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
    from core.geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                                    _validate_fmt)
else:
    from geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                               _validate_fmt)

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
_REQUIRED_PREFLIGHT = ("dumps_gdml", "verifies_foil_gdml",
                       "preserves_gdml", "checks_managed_overlap",
                       "require_zero_overlaps")
_REQUIRED_LEADERBOARD = ("file", "columns", "obs_noise", "metrics")
_ALLOWED_KNOB = ("name", "min", "max", "fmt")

# run.stage_tuning[<stage>] accepted keys, mirroring core/pipeline.py STAGES
# fields that a JSON mode is allowed to override. Anything else (a typo, or a
# STAGES field this schema doesn't cover) is a load error -- see I4/I5.
_STAGE_TUNING_KEYS = ("events_per_job", "memory_mb", "quorum")

# Leaderboard columns a knob may NOT be named after. A collision makes
# core/leaderboard.py's Leaderboard.header/append emit the column twice;
# csv.DictReader keeps the LAST, so Leaderboard.load reads the METRIC into
# that knob's coordinate and the GP trains on garbage -- silently. `config`
# is the writer-side leading column (Leaderboard.header hardcodes it);
# `alpha`/`obj` are normally in leaderboard.columns already but are listed
# here so they are rejected even if a spec renames the tail. The spec's own
# leaderboard.columns are added on top at load.
_RESERVED_KNOB_COLUMNS = ("config", "alpha", "obj")


class _DuplicateJsonKey(ValueError):
    """A JSON object carried the same key twice."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _reject_duplicate_json_keys(pairs):
    """json.loads object_pairs_hook: plain json.loads accepts duplicate object
    keys and silently keeps the LAST one, so editing the first of two
    duplicated blocks has no effect and no error -- the same
    silent-wrong-geometry class that tainted 62 foilsg rows."""
    out = {}
    for k, v in pairs:
        if k in out:
            raise _DuplicateJsonKey(k)
        out[k] = v
    return out


def _normalize_leaderboard_rel(rel: str, where: str) -> str:
    """Canonical form for comparing two leaderboard declarations.

    Collapses './' and doubled slashes so 'leaderboards/x.tsv' and
    './leaderboards/x.tsv' cannot name the same file past the uniqueness
    check. '..' is rejected outright: it both escapes the repo and defeats
    that comparison.
    """
    p = Path(rel)
    if ".." in p.parts:
        raise ValueError(
            f"{where}[leaderboard]: 'file' must not contain '..' (got "
            f"{rel!r}); it escapes the repo root and defeats the "
            f"leaderboard-uniqueness check across modes")
    return p.as_posix()


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


def _validate_stage_tuning(run: dict, declared_stages,
                           where: str) -> Dict[str, Dict[str, object]]:
    """Validate + normalize run.stage_tuning (core/pipeline.py STAGES
    overrides applied on top of pipeline defaults -- see core/pipeline.py's
    _apply_stage_tuning). Defaults to {} when absent, never silently drops an
    unknown tuning key.

    Stage NAMES are checked against this mode's run.stages, exactly as
    _validate_jobs_per_stage and _validate_presubmit_after already do. Without
    that, two things escaped load time: a name that exists in pipeline.STAGES
    but not in this mode's chain loaded fine and was SILENTLY INERT forever
    (the intended tuning never applied, no error), and a pure typo
    ('mubeem') loaded fine and raised only at core/pipeline.py module
    import -- inside every child at first submit, after propose and preflight
    had already passed.
    """
    raw = run.get("stage_tuning")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}[run.stage_tuning]: must be an object of "
            f"{{stage: {{tuning}}}}, got {raw!r}")
    _reject_unknown(raw, declared_stages, f"{where}[run.stage_tuning]")
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


def _validate_jobs_per_stage(run: dict, declared_stages, where: str) -> Dict[str, int]:
    """Validate run.jobs_per_stage keys against the mode's declared
    run.stages. A typo'd stage name (e.g. 'mubeem') otherwise loads fine and
    silently adds a dead key to graph.config.STAGE_TARGETS via a plain
    dict.update -- the REAL stage is left at its default job count with no
    error anywhere (X3 in the json-configurable-modes final review)."""
    raw = run.get("jobs_per_stage")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}[run.jobs_per_stage]: must be an object of "
            f"{{stage: njobs}}, got {raw!r}")
    _reject_unknown(raw, declared_stages, f"{where}[run.jobs_per_stage]")
    # Values were passed through raw: true / 15.5 / "20" all loaded. The value
    # flows to graph/config.py STAGE_TARGETS.update -> pipeline.STAGES[...]
    # ["njobs"] -> str(cfg["njobs"]) in the jobsub command, so a bad value on
    # a LATER stage surfaces only after the earlier stages' hours have run.
    # isinstance(True, int) is True, so bool needs its own rejection.
    for stage, njobs in raw.items():
        if isinstance(njobs, bool) or not isinstance(njobs, int) or njobs <= 0:
            raise ValueError(
                f"{where}[run.jobs_per_stage.{stage}]: must be a positive int "
                f"(grid job count), got {njobs!r}; this value reaches the "
                f"jobsub command line unchanged and would fail only after the "
                f"earlier stages have already run")
    return dict(raw)


def _validate_presubmit_after(run: dict, declared_stages, where: str) -> Dict[str, Tuple[str, ...]]:
    """Validate run.presubmit_after the same way as jobs_per_stage: keys are
    stage names and must be declared in run.stages, and each value must be a
    list of stage-name strings -- a bare string value silently becomes a
    tuple of its characters via tuple(str) (X3)."""
    raw = run.get("presubmit_after")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{where}[run.presubmit_after]: must be an object of "
            f"{{stage: [stages]}}, got {raw!r}")
    _reject_unknown(raw, declared_stages, f"{where}[run.presubmit_after]")
    out: Dict[str, Tuple[str, ...]] = {}
    for stage, targets in raw.items():
        sw = f"{where}[run.presubmit_after.{stage}]"
        if not isinstance(targets, list) or not all(
                isinstance(t, str) for t in targets):
            raise ValueError(
                f"{sw}: must be a list of stage-name strings, got "
                f"{targets!r} (a bare string here silently becomes a tuple "
                f"of its characters)")
        out[stage] = tuple(targets)
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
        doc = json.loads(path.read_text(),
                         object_pairs_hook=_reject_duplicate_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{where}: invalid JSON: {exc}") from None
    except _DuplicateJsonKey as exc:
        raise ValueError(
            f"{where}: duplicate JSON key {exc.key!r}. json.loads keeps the "
            f"LAST of two identical keys with no error, so editing the first "
            f"one would silently have no effect") from None

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

    stage_tuning = _validate_stage_tuning(run, stages, where)
    jobs_per_stage = _validate_jobs_per_stage(run, stages, where)
    presubmit_after = _validate_presubmit_after(run, stages, where)

    knobs = doc["knobs"]
    if not knobs:
        raise ValueError(f"{where}[knobs]: at least one knob is required")
    for i, k in enumerate(knobs):
        kw = f"{where}[knobs[{i}]]"
        _need(k, _ALLOWED_KNOB, kw)
        _reject_unknown(k, _ALLOWED_KNOB, kw)
        # R1: an unvalidated fmt like "75.0" (no replacement field) writes a
        # CONSTANT into every knob column of the leaderboard; Leaderboard.load
        # (core/leaderboard.py) parses it back as a valid float, so every past
        # eval collapses to the same point and the GP trains on garbage --
        # silently. Same guard geom_template.py already applies to computed
        # geometry lines.
        _validate_fmt(k["fmt"], kw)
        # `i`/`n` are injected by the geometry renderer's per_index loop and
        # would silently shadow the knob there (see geom_template's
        # _RESERVED_ELEMENTWISE_NAMES). Checked here too so the error names
        # the knob index rather than the whole geom block.
        if k["name"] in _RESERVED_ELEMENTWISE_NAMES:
            raise ValueError(
                f"{kw}: knob name {k['name']!r} is reserved -- 'i' (element "
                f"index) and 'n' (element count) are injected by the geometry "
                f"renderer's per_index loop and would SILENTLY shadow the "
                f"knob there, rendering the loop variable instead of the "
                f"proposed value")
        lo, hi = float(k["min"]), float(k["max"])
        if not lo < hi:
            raise ValueError(
                f"{kw}: min ({lo}) must be < max ({hi}); a knob with "
                f"min >= max is a degenerate or inverted search-space "
                f"dimension")

    names = tuple(k["name"] for k in knobs)
    if len(set(names)) != len(names):
        raise ValueError(f"{where}[knobs]: duplicate knob names in {list(names)}")

    int_dims_raw = doc.get("int_dims") or ()
    n_knobs = len(knobs)
    for idx in int_dims_raw:
        if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx < n_knobs):
            raise ValueError(
                f"{where}[int_dims]: index {idx!r} is out of range for "
                f"{n_knobs} knob(s) (valid indices are 0..{n_knobs - 1}); an "
                f"out-of-range index otherwise silently leaves an integer "
                f"knob continuous")

    columns = tuple(leaderboard["columns"])
    if len(columns) != 4:
        raise ValueError(
            f"{where}[leaderboard]: 'columns' must have exactly 4 entries "
            f"(sob-like, second-objective, alpha, obj) to match "
            f"core/leaderboard.py's Leaderboard row schema; got "
            f"{list(columns)}")
    if columns[0] != "sob":
        raise ValueError(
            f"{where}[leaderboard]: columns[0] must be exactly 'sob', got "
            f"{columns[0]!r}. Leaderboard.load (core/leaderboard.py) reads "
            f"row[metric_cols[0]] into Point.sob positionally, so this isn't "
            f"a parse-time hazard, but every leaderboard TSV across every "
            f"mode names its first metric column 'sob' by convention -- a "
            f"per-spec rename here would be the one leaderboard file whose "
            f"header doesn't match, tripping up anyone diffing/grepping "
            f"leaderboards/*.tsv by that convention.")

    # A knob column and a metric column share one TSV header row
    # (Leaderboard.header/append -- core/leaderboard.py -- writes `config` +
    # knob_names + metric_cols). A knob named after any of them emits that
    # column TWICE; csv.DictReader keeps the LAST, so Leaderboard.load reads
    # the METRIC back into that knob's coordinate and the GP trains on
    # garbage -- silently.
    reserved_cols = set(columns) | set(_RESERVED_KNOB_COLUMNS)
    for i, nm in enumerate(names):
        if nm in reserved_cols:
            raise ValueError(
                f"{where}[knobs[{i}]]: knob name {nm!r} is a reserved "
                f"leaderboard column (leaderboard.columns + "
                f"{list(_RESERVED_KNOB_COLUMNS)}). The header would carry it "
                f"twice and csv.DictReader keeps the last, so "
                f"core/leaderboard.py's Leaderboard.load would read the "
                f"METRIC into this knob's coordinate on every past row")

    noise = leaderboard["obs_noise"]
    if noise is not None:
        if len(noise) != 2 or not all(v > 0 for v in noise):
            raise ValueError(
                f"{where}[leaderboard]: obs_noise must be 2 positive sigmas, "
                f"got {noise!r}")
        noise = tuple(float(v) for v in noise)

    metrics_raw = leaderboard["metrics"]
    if not isinstance(metrics_raw, dict):
        raise ValueError(
            f"{where}[leaderboard.metrics]: must be an object of "
            f"{{column: [summary.json keys]}}, got {metrics_raw!r}")
    metrics: Dict[str, Tuple[str, ...]] = {}
    for col, keys in metrics_raw.items():
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValueError(
                f"{where}[leaderboard.metrics.{col}]: must be a list of "
                f"summary.json key strings, got {keys!r} (a bare string here "
                f"silently becomes a tuple of its characters, which then "
                f"fails only after a ~4.5h grid evaluation)")
        metrics[col] = tuple(keys)
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
    lb_file = _normalize_leaderboard_rel(lb_file, where)

    geom = GeomTemplate.from_dict(doc["geom"], names, f"{where}[geom]")

    spec = ModeSpec(
        name=doc["name"],
        musing=software["musing"],
        grid_tarball=software["grid_tarball"],
        grid_stages=tuple(stages),
        harvest_verb=run["harvest"],
        stage_target_overrides=jobs_per_stage,
        presubmit_after=presubmit_after,
        bounds_lo=tuple(float(k["min"]) for k in knobs),
        bounds_hi=tuple(float(k["max"]) for k in knobs),
        int_dims=tuple(int_dims_raw),
        dumps_gdml=preflight["dumps_gdml"],
        verifies_foil_gdml=preflight["verifies_foil_gdml"],
        preserves_gdml=preflight["preserves_gdml"],
        checks_managed_overlap=preflight["checks_managed_overlap"],
        require_zero_overlaps=preflight["require_zero_overlaps"],
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
    the wrong geometry. So is a leaderboard file already claimed by another
    mode (see below).

    Both checks live HERE and not in load_mode_file, so test fixtures -- which
    deliberately declare the LIVE names and leaderboards to prove parity --
    can still be loaded from any path.
    """
    if not directory.is_dir():
        return {}
    out: Dict[str, object] = {}
    seen_leaderboards: Dict[str, Path] = {}
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
        # Two modes writing one leaderboard is silent cross-mode GP
        # contamination in BOTH directions: the schemas match column-for-
        # column, so each mode's load_history() happily parses the other's
        # rows as its own evals. The realistic path is a copy-pasted spec
        # whose leaderboard line was never edited -- it looks plausible.
        lb = spec.leaderboard_rel
        if lb in seen_leaderboards:
            raise ValueError(
                f"{path}: leaderboard {lb!r} is already declared by "
                f"{seen_leaderboards[lb]}. Two modes sharing one leaderboard "
                f"silently cross-contaminate their GP history; give each mode "
                f"its own leaderboards/*.tsv.")
        seen_leaderboards[lb] = path
        out[spec.name] = spec
    return out
