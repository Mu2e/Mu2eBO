"""Schema-2 study files -> a frozen Study (generic-study design).

Every key is required, unknown keys are rejected, and every error names the
file, the field and the rule (ADR-0002). A study reaches the physics only
through the kits it names (core/kit_registry.py). STDLIB ONLY.
Spec: docs/superpowers/specs/2026-09-23-generic-study-design.md
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

if __package__:
    from core import kit_registry, paths
    from core.geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                                    _validate_fmt, compile_expr, eval_expr)
else:
    import kit_registry
    import paths
    from geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                               _validate_fmt, compile_expr, eval_expr)

SCHEMA = 2
_TOP = ("schema", "name", "note", "knobs", "derive", "geom", "kits",
        "preflight", "evaluate", "objectives", "constraints", "extra_metrics",
        "extra_columns", "leaderboard")
_KNOB = ("name", "type", "min", "max", "unit", "fmt")
_DERIVE = ("consts", "exprs", "profiles")
_PROFILE = ("kind", "count", "control", "clip")
_GEOM = ("writer", "base", "lines")
_PREFLIGHT = ("kit", "params", "files")
_STEP = ("step", "kit", "entry", "files", "files_from", "params", "fixed")
_OBJECTIVE = ("name", "metric", "direction", "transform", "noise", "fmt")
_EXTRA_METRIC = ("name", "metric", "fmt")
_EXTRA_COLUMN = ("name", "expr", "fmt")
_LEADERBOARD = ("file", "layout", "context")
_WRITERS = ("offline_simpleconfig",)
_RENDERED_FILES = ("geom",)
_DIRECTIONS = ("max", "min")
_TRANSFORMS = ("none", "log10")
_ARTIFACT_TOKEN = "${ARTIFACT}/"


@dataclass(frozen=True)
class Knob:
    name: str
    type: str
    min: float
    max: float
    unit: str
    fmt: str


@dataclass(frozen=True)
class Step:
    step: str
    kit: str
    entry: Any
    files: Tuple[str, ...]
    files_from: Tuple[str, ...]
    params: Dict[str, str]
    fixed: Dict[str, Any]


@dataclass(frozen=True)
class Objective:
    name: str
    metric: str
    direction: str
    transform: str
    noise: float
    fmt: str

    @property
    def step(self) -> str:
        return self.metric.split(".", 1)[0]

    @property
    def key(self) -> str:
        return self.metric.split(".", 1)[1]


@dataclass(frozen=True)
class StudyConstraint:
    name: str
    bound: str      # "max" (value <= bound) or "min" (value >= bound)
    value: float
    k_sigma: float


@dataclass(frozen=True)
class ExtraMetric:
    name: str
    metric: str
    fmt: str

    @property
    def key(self) -> str:
        return self.metric.split(".", 1)[1]


@dataclass(frozen=True)
class ExtraColumn:
    name: str
    expr: str
    fmt: str
    _compiled: Any = field(compare=False, repr=False)

    def evaluate(self, env: Dict[str, Any]) -> float:
        return float(eval_expr(self._compiled, dict(env)))


@dataclass(frozen=True)
class Study:
    path: Path
    name: str
    note: str
    knobs: Tuple[Knob, ...]
    derive: Dict[str, Any]
    geom: Optional[GeomTemplate] = field(compare=False)
    kits: Dict[str, Dict[str, Any]]
    preflight: Optional[Dict[str, Any]]
    steps: Tuple[Step, ...]
    objectives: Tuple[Objective, ...]
    constraints: Tuple[StudyConstraint, ...]
    extra_metrics: Tuple[ExtraMetric, ...]
    extra_columns: Tuple[ExtraColumn, ...]
    leaderboard_rel: str
    layout: str
    context: Tuple[str, ...]
    spec_sha: str

    @property
    def knob_names(self) -> Tuple[str, ...]:
        return tuple(k.name for k in self.knobs)

    @property
    def knob_fmts(self) -> Tuple[str, ...]:
        return tuple(k.fmt for k in self.knobs)

    @property
    def bounds_lo(self) -> Tuple[float, ...]:
        return tuple(k.min for k in self.knobs)

    @property
    def bounds_hi(self) -> Tuple[float, ...]:
        return tuple(k.max for k in self.knobs)

    @property
    def int_dims(self) -> Tuple[int, ...]:
        return tuple(i for i, k in enumerate(self.knobs) if k.type == "int")

    @property
    def consts(self) -> Dict[str, Any]:
        return dict(self.derive["consts"])


def _obj(d, keys, where):
    """d must be an object holding exactly `keys`."""
    if not isinstance(d, dict):
        raise ValueError(f"{where}: must be an object, got {d!r}")
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: missing required field(s) {missing}")
    unknown = sorted(set(d) - set(keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; accepted keys "
                         f"are {sorted(keys)}")
    return d


def _list(v, where):
    if not isinstance(v, list):
        raise ValueError(f"{where}: must be a list, got {v!r}")
    return v


def _dict(v, where):
    if not isinstance(v, dict):
        raise ValueError(f"{where}: must be an object, got {v!r}")
    return v


def _one_of(v, choices, where, why=""):
    if v not in choices:
        raise ValueError(f"{where}: must be one of {list(choices)}, got "
                         f"{v!r}{why}")
    return v


def _kit(name, role, where):
    """A registered kit whose KitDecl sets `role` ('step_kit' or
    'check_kit')."""
    ok = sorted(k for k, d in kit_registry.KITS.items() if getattr(d, role))
    return _one_of(name, ok, where, f" (the kits with {role}=True)")


def _files(raw, has_geom, where):
    """`where` is the owning step or preflight."""
    files = tuple(_list(raw, f"{where}[files]"))
    for f in files:
        _one_of(f, _RENDERED_FILES, f"{where}[files]")
        if f == "geom" and not has_geom:
            raise ValueError(f"{where}[files]: lists 'geom' but the study's "
                             f"geom is null")
    return files


def _params(raw, names, where):
    """`where` is the owning step or preflight; each value names a knob,
    const, expr or profile."""
    for k, v in _dict(raw, f"{where}[params]").items():
        if not isinstance(v, str) or v not in names:
            raise ValueError(f"{where}[params.{k}]: must be a string naming "
                             f"a knob, const, expr or profile, got {v!r}")
    return dict(raw)


def _name(v, where):
    if not isinstance(v, str) or not v.isidentifier():
        raise ValueError(f"{where}: must be an identifier string, got {v!r}")
    return v


def _number(v, where):
    # json.loads accepts the literals NaN/Infinity, and every comparison
    # against NaN is False: a NaN noise or bound would pass the "> 0" checks
    # below and reach the GP as a silent garbage value.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}: must be a number, got {v!r}")
    try:
        f = float(v)
    except OverflowError:      # an int literal too large for a float
        f = math.inf
    if not math.isfinite(f):
        raise ValueError(f"{where}: must be a finite number, got {v!r}")
    return f


def _expand(value, where):
    """Only '${ARTIFACT}/' is supported; a bare personal user area is
    refused (it would run only for that account)."""
    if not isinstance(value, str):
        return value
    if value.startswith(_ARTIFACT_TOKEN):
        return str(paths.artifact(value[len(_ARTIFACT_TOKEN):]))
    if "${" in value:
        raise ValueError(f"{where}: unknown variable in {value!r}; the only "
                         f"supported token is '${{ARTIFACT}}/'")
    if re.match(r"^/exp/mu2e/(app|data)/users/[^/]+/", value):
        raise ValueError(f"{where}: {value!r} hardcodes a personal user "
                         f"area; use '${{ARTIFACT}}/<rest-of-path>'")
    return value


def _metric(v, steps, where):
    if not isinstance(v, str) or v.count(".") != 1 or not all(v.split(".")):
        raise ValueError(f"{where}: metric must be 'step.key', got {v!r}")
    step = v.split(".", 1)[0]
    if step not in steps:
        raise ValueError(f"{where}: metric {v!r} names step {step!r}, which "
                         f"is not in evaluate[] ({sorted(steps)})")
    return v


def _knobs(raw, where):
    raw = _list(raw, f"{where}[knobs]")
    if not raw:
        raise ValueError(f"{where}[knobs]: at least one knob is required")
    out = []
    for i, k in enumerate(raw):
        kw = f"{where}[knobs[{i}]]"
        _obj(k, _KNOB, kw)
        name = _name(k["name"], f"{kw}[name]")
        if name in _RESERVED_ELEMENTWISE_NAMES:
            raise ValueError(f"{kw}: knob name {name!r} is reserved (the "
                             f"geometry renderer injects 'i' and 'n')")
        _one_of(k["type"], ("real", "int"), f"{kw}[type]")
        lo, hi = _number(k["min"], f"{kw}[min]"), _number(k["max"], f"{kw}[max]")
        if not lo < hi:
            raise ValueError(f"{kw}: min ({lo}) must be < max ({hi})")
        if k["type"] == "int" and not (lo.is_integer() and hi.is_integer()):
            raise ValueError(f"{kw}: an int knob needs integer bounds, got "
                             f"[{lo}, {hi}]")
        if not isinstance(k["unit"], str):
            raise ValueError(f"{kw}[unit]: must be a string (may be empty)")
        _validate_fmt(k["fmt"], f"{kw}[fmt]")
        out.append(Knob(name, k["type"], lo, hi, k["unit"], k["fmt"]))
    return tuple(out)     # duplicate names: _check_columns


def _derive_and_geom(doc, knob_names, where):
    derive = _obj(doc["derive"], _DERIVE, f"{where}[derive]")
    for k in _DERIVE:
        _dict(derive[k], f"{where}[derive.{k}]")
    profiles = {}
    for pname, p in derive["profiles"].items():
        pw = f"{where}[derive.profiles.{pname}]"
        _obj(p, _PROFILE, pw)
        _one_of(p["kind"], ("lagrange",), f"{pw}[kind]")
        profiles[pname] = {k: p[k] for k in ("count", "control", "clip")}
    geom = doc["geom"]
    if geom is None:
        if any(derive[k] for k in _DERIVE):
            raise ValueError(f"{where}[derive]: must be empty when geom is "
                             f"null in this version (derive without a "
                             f"geometry file arrives with Phase B)")
        return derive, None
    _obj(geom, _GEOM, f"{where}[geom]")
    _one_of(geom["writer"], _WRITERS, f"{where}[geom.writer]")
    template = GeomTemplate.from_dict(
        {"base": geom["base"], "consts": derive["consts"],
         "derived": derive["exprs"], "profiles": profiles,
         "lines": geom["lines"]},
        knob_names, f"{where}[derive+geom]")
    return derive, template


def _steps(raw, has_geom, names, where):
    raw = _list(raw, f"{where}[evaluate]")
    if not raw:
        raise ValueError(f"{where}[evaluate]: at least one step is required")
    out = []
    for i, s in enumerate(raw):
        sw = f"{where}[evaluate[{i}]]"
        _obj(s, _STEP, sw)
        step = _name(s["step"], f"{sw}[step]")
        kit = _kit(s["kit"], "step_kit", f"{sw}[kit]")
        decl = kit_registry.KITS[kit]
        entry = s["entry"]
        if decl.uses_entries and not (isinstance(entry, dict)
                                      or (isinstance(entry, str) and entry)):
            raise ValueError(f"{sw}[entry]: kit {kit!r} needs a stage-template "
                             f"name or an inline template object")
        if not decl.uses_entries and entry is not None:
            raise ValueError(f"{sw}[entry]: kit {kit!r} takes no entry; use null")
        fixed = kit_registry.validate(kit, s["fixed"], decl.fixed_keys,
                                      f"{sw}[fixed]", required=False)
        out.append(Step(step, kit, entry, _files(s["files"], has_geom, sw),
                        tuple(_list(s["files_from"], f"{sw}[files_from]")),
                        _params(s["params"], names, sw), fixed))
    step_names = [s.step for s in out]
    if len(set(step_names)) != len(step_names):
        raise ValueError(f"{where}[evaluate]: duplicate step names {step_names}")
    for s in out:
        for up in s.files_from:
            if up not in step_names:
                raise ValueError(f"{where}[evaluate.{s.step}.files_from]: "
                                 f"unknown step {up!r}")
    _check_acyclic(out, where)
    return tuple(out)


def _check_acyclic(steps, where):
    deps = {s.step: set(s.files_from) for s in steps}
    state = {}

    def visit(n, trail):
        if state.get(n) == "done":
            return
        if state.get(n) == "open":
            raise ValueError(f"{where}[evaluate]: files_from forms a cycle "
                             f"{' -> '.join(trail + [n])}")
        state[n] = "open"
        for d in sorted(deps[n]):
            visit(d, trail + [n])
        state[n] = "done"

    for n in deps:
        visit(n, [])


def _kits_and_preflight(doc, steps, has_geom, names, where):
    kits_raw = _dict(doc["kits"], f"{where}[kits]")
    pre = doc["preflight"]
    used = {s.kit for s in steps}
    if pre is not None:
        pw = f"{where}[preflight]"
        _obj(pre, _PREFLIGHT, pw)
        used.add(_kit(pre["kit"], "check_kit", f"{pw}[kit]"))
        _files(pre["files"], has_geom, pw)
        _params(pre["params"], names, pw)
    kits = {}
    for kit, settings in kits_raw.items():
        kw = f"{where}[kits.{kit}]"
        if kit not in kit_registry.KITS:
            raise ValueError(f"{kw}: unknown kit {kit!r}")
        if kit not in used:
            raise ValueError(f"{kw}: kit {kit!r} is configured but unused by "
                             f"any step or the preflight")
        checked = kit_registry.validate(
            kit, settings, kit_registry.KITS[kit].study_keys, kw,
            required=True)
        kits[kit] = {k: _expand(v, f"{kw}[{k}]") for k, v in checked.items()}
    for kit in sorted(used):
        if kit_registry.KITS[kit].study_keys and kit not in kits:
            raise ValueError(f"{where}[kits]: kit {kit!r} is used but has no "
                             f"settings; it needs "
                             f"{sorted(kit_registry.KITS[kit].study_keys)}")
    return kits, pre


def _objectives(raw, step_names, where):
    raw = _list(raw, f"{where}[objectives]")
    if not raw:
        raise ValueError(f"{where}[objectives]: at least one objective is "
                         f"required")
    out = []
    for i, o in enumerate(raw):
        ow = f"{where}[objectives[{i}]]"
        _obj(o, _OBJECTIVE, ow)
        _one_of(o["direction"], _DIRECTIONS, f"{ow}[direction]")
        _one_of(o["transform"], _TRANSFORMS, f"{ow}[transform]")
        noise = _number(o["noise"], f"{ow}[noise]")
        if noise <= 0:
            raise ValueError(f"{ow}[noise]: must be > 0, got {noise}")
        _validate_fmt(o["fmt"], f"{ow}[fmt]")
        out.append(Objective(_name(o["name"], f"{ow}[name]"),
                             _metric(o["metric"], step_names, f"{ow}[metric]"),
                             o["direction"], o["transform"], noise, o["fmt"]))
    return tuple(out)


def _constraints(raw, objectives, where):
    raw = _list(raw, f"{where}[constraints]")
    if len(raw) > 1:
        raise ValueError(f"{where}[constraints]: at most one constraint in "
                         f"this version, got {len(raw)}")
    by_name = {o.name: o for o in objectives}
    out = []
    for i, c in enumerate(raw):
        cw = f"{where}[constraints[{i}]]"
        bounds = [b for b in ("max", "min") if b in _dict(c, cw)]
        if len(bounds) != 1:
            raise ValueError(f"{cw}: needs exactly one of 'max' or 'min'")
        _obj(c, ("name", "k_sigma", bounds[0]), cw)
        if c["name"] not in by_name:
            raise ValueError(f"{cw}[name]: {c['name']!r} is not an objective")
        obj = by_name[c["name"]]
        # surrokit constrains an axis from below only; a maximized axis is
        # the raw value (max) or its negation (min), so the bound's side is
        # fixed by the direction.
        want = "max" if obj.direction == "min" else "min"
        if bounds[0] != want:
            raise ValueError(f"{cw}: objective {obj.name!r} is "
                             f"'{obj.direction}', so its constraint must be "
                             f"'{want}'")
        value = _number(c[bounds[0]], f"{cw}[{bounds[0]}]")
        if obj.transform == "log10" and value <= 0:
            raise ValueError(f"{cw}: a log10 objective needs a positive "
                             f"bound, got {value}")
        k = _number(c["k_sigma"], f"{cw}[k_sigma]")
        if k < 0:
            raise ValueError(f"{cw}[k_sigma]: must be >= 0, got {k}")
        out.append(StudyConstraint(obj.name, bounds[0], value, k))
    return tuple(out)


def _extras(doc, step_names, objectives, consts, context, where):
    metrics = []
    for i, m in enumerate(_list(doc["extra_metrics"], f"{where}[extra_metrics]")):
        mw = f"{where}[extra_metrics[{i}]]"
        _obj(m, _EXTRA_METRIC, mw)
        _validate_fmt(m["fmt"], f"{mw}[fmt]")
        metrics.append(ExtraMetric(_name(m["name"], f"{mw}[name]"),
                                   _metric(m["metric"], step_names, f"{mw}[metric]"),
                                   m["fmt"]))
    allowed = ({o.name for o in objectives} | {m.name for m in metrics}
               | set(consts) | set(context))
    columns = []
    for i, c in enumerate(_list(doc["extra_columns"], f"{where}[extra_columns]")):
        cw = f"{where}[extra_columns[{i}]]"
        _obj(c, _EXTRA_COLUMN, cw)
        _validate_fmt(c["fmt"], f"{cw}[fmt]")
        compiled = compile_expr(c["expr"], allowed, f"{cw}[expr]")
        columns.append(ExtraColumn(_name(c["name"], f"{cw}[name]"),
                                   c["expr"], c["fmt"], compiled))
    return tuple(metrics), tuple(columns)


def _leaderboard(raw, where):
    lb = _obj(raw, _LEADERBOARD, f"{where}[leaderboard]")
    rel = lb["file"]
    if not isinstance(rel, str) or Path(rel).is_absolute():
        raise ValueError(f"{where}[leaderboard.file]: must be a repo-relative "
                         f"path, got {rel!r}")
    if ".." in Path(rel).parts:
        raise ValueError(f"{where}[leaderboard.file]: must not contain '..' "
                         f"(got {rel!r})")
    _one_of(lb["layout"], ("v1",), f"{where}[leaderboard.layout]",
            "; 'v2' arrives with Phase B")
    context = tuple(_name(c, f"{where}[leaderboard.context]")
                    for c in _list(lb["context"], f"{where}[leaderboard.context]"))
    return Path(rel).as_posix(), lb["layout"], context


def _check_columns(knobs, objectives, metrics, columns, context, where):
    cols = [("config", "config")] + [
        (x.name, f"{field}.{x.name}")
        for field, xs in (("knobs", knobs), ("objectives", objectives),
                          ("extra_metrics", metrics),
                          ("extra_columns", columns))
        for x in xs]
    names = [n for n, _ in cols]
    dup = sorted({label for n, label in cols if names.count(n) > 1})
    if dup:
        raise ValueError(f"{where}[{', '.join(dup)}]: a leaderboard column "
                         f"appears twice (config, knob, objective, extra "
                         f"metric and extra column names must all differ)")
    # A context name is allowed to equal an extra_column name -- that's how
    # an externally-supplied context value (e.g. alpha) is rendered as a
    # leaderboard column (an extra_column with a passthrough expr of the
    # same name). It may not equal 'config', a knob, an objective or an
    # extra metric: those already mean something computed elsewhere, so
    # reusing the name for a context value would be ambiguous.
    reserved = ({"config"} | {k.name for k in knobs} | {o.name for o in objectives}
                | {m.name for m in metrics})
    clash = sorted(set(context) & reserved)
    if clash:
        raise ValueError(f"{where}[leaderboard.context]: {clash} collide "
                         f"with column names")


def load_study_file(path: Path) -> Study:
    """Parse and validate one schema-2 study file. Raises ValueError."""
    path = Path(path)
    where = str(path)

    def no_duplicate_keys(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"{where}: duplicate JSON key {k!r} "
                                 f"(json.loads would silently keep the last "
                                 f"one)")
            out[k] = v
        return out

    try:
        doc = json.loads(path.read_text(), object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{where}: invalid JSON: {exc}") from None
    _obj(doc, _TOP, where)
    if doc["schema"] != SCHEMA:
        raise ValueError(f"{where}[schema]: must be {SCHEMA}, got "
                         f"{doc['schema']!r}")
    if not isinstance(doc["note"], str):
        raise ValueError(f"{where}[note]: must be a string")
    knobs = _knobs(doc["knobs"], where)
    knob_names = tuple(k.name for k in knobs)
    derive, geom = _derive_and_geom(doc, knob_names, where)
    names = (set(knob_names) | set(derive["consts"]) | set(derive["exprs"])
             | set(derive["profiles"]))
    steps = _steps(doc["evaluate"], geom is not None, names, where)
    step_names = {s.step for s in steps}
    kits, preflight = _kits_and_preflight(doc, steps, geom is not None,
                                          names, where)
    objectives = _objectives(doc["objectives"], step_names, where)
    constraints = _constraints(doc["constraints"], objectives, where)
    rel, layout, context = _leaderboard(doc["leaderboard"], where)
    metrics, columns = _extras(doc, step_names, objectives, derive["consts"],
                               context, where)
    _check_columns(knobs, objectives, metrics, columns, context, where)
    sha = hashlib.sha256(json.dumps(doc, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()
    return Study(path=path, name=_name(doc["name"], f"{where}[name]"),
                 note=doc["note"], knobs=knobs, derive=derive, geom=geom,
                 kits=kits, preflight=preflight,
                 steps=steps, objectives=objectives, constraints=constraints,
                 extra_metrics=metrics, extra_columns=columns,
                 leaderboard_rel=rel, layout=layout, context=context,
                 spec_sha=sha)


def load_study_dirs(primary: Path, extra: Optional[str]) -> Dict[str, Study]:
    """Every *.json in `primary` (flat: archive/ stays unloaded) and in each
    directory of the colon-separated `extra` ($AUTORESEARCH_STUDY_PATH),
    whose entries must be absolute paths."""
    dirs = [Path(primary)]
    for d in (extra or "").split(":"):
        if not d:
            continue
        if not Path(d).is_absolute():
            raise ValueError(f"AUTORESEARCH_STUDY_PATH entry {d!r} is a "
                             f"relative path; every entry must be absolute "
                             f"(a relative one resolves against each "
                             f"process's working directory, and campaign "
                             f"children do not share the operator's)")
        if not Path(d).is_dir():
            raise ValueError(f"AUTORESEARCH_STUDY_PATH names {d!r}, which is "
                             f"not a directory")
        dirs.append(Path(d))
    out: Dict[str, Study] = {}
    boards: Dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            s = load_study_file(p)
            if s.name != p.stem:
                raise ValueError(f"{p}: study name {s.name!r} does not match "
                                 f"its file name {p.stem!r}")
            if s.name in out:
                raise ValueError(f"{p}: study {s.name!r} is defined twice "
                                 f"(also {out[s.name].path})")
            board = Path(s.leaderboard_rel).name
            if board in boards:
                raise ValueError(f"{p}: leaderboard basename {board!r} is "
                                 f"already used by {boards[board]}; two "
                                 f"studies sharing one board contaminate "
                                 f"each other's GP history")
            boards[board] = p
            out[s.name] = s
    return out
