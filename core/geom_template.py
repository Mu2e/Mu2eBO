"""Render a Mu2e geometry overlay from a declarative JSON description.

Used by JSON-defined modes (core/mode_json.py). STDLIB ONLY — core/modes.py
imports this and must stay importable from any venv (see core/modes.py:1-8),
so no numpy even where bo_driver.py uses it.
"""
from __future__ import annotations

import ast
import math
import string
from typing import Any, Dict, Iterable, List, Set

_ALLOWED_FUNCS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt}
# ast.Pow is excluded: large exponents hang Python (e.g. 99999999 ** 99999999),
# and negative base + fractional exp returns complex (e.g. (-2.0)**0.5 → complex).
# Profiles write i*i instead; roots use sqrt(). No formula needs **.
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


class ExprError(ValueError):
    """A formula was unparseable, used an unknown name, or used forbidden syntax."""


def compile_expr(src: str, allowed_names: Set[str], where: str) -> ast.Expression:
    """Parse `src` and verify every construct is permitted.

    `where` is a human locator (file + geometry key) included in every error.
    Raises ExprError; never evaluates.
    """
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"{where}: cannot parse formula {src!r}: {exc}") from None
    _verify(tree.body, allowed_names, src, where)
    return tree


def _verify(node: ast.AST, allowed: Set[str], src: str, where: str) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(
                f"{where}: only numeric constants are allowed in {src!r}, "
                f"got {node.value!r}")
        return
    if isinstance(node, ast.Name):
        if node.id not in allowed:
            raise ExprError(
                f"{where}: unknown name {node.id!r} in formula {src!r}; "
                f"known names are {sorted(allowed)}")
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        _verify(node.left, allowed, src, where)
        _verify(node.right, allowed, src, where)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARYOPS):
        _verify(node.operand, allowed, src, where)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ExprError(
                f"{where}: only {sorted(_ALLOWED_FUNCS)} may be called in {src!r}")
        if node.keywords:
            raise ExprError(f"{where}: keyword arguments are not allowed in {src!r}")
        for arg in node.args:
            _verify(arg, allowed, src, where)
        return
    if isinstance(node, ast.Subscript):
        # profile indexing: rOut[i]
        _verify(node.value, allowed, src, where)
        _verify(node.slice, allowed, src, where)
        return
    raise ExprError(
        f"{where}: forbidden syntax {type(node).__name__} in formula {src!r}")


def eval_expr(compiled: ast.Expression, env: Dict[str, Any]) -> float:
    """Evaluate a compiled formula against `env`. Builtins are stripped."""
    return eval(  # noqa: S307 — AST was whitelisted by compile_expr
        compile(compiled, "<geom>", "eval"), {"__builtins__": {}, **_ALLOWED_FUNCS}, env)


def lagrange_profile(control: Iterable[float], count: int,
                     clip: tuple | None) -> List[float]:
    """Lagrange quadratic through (c0, c1, c2) at u = 0, 0.5, 1, sampled at
    `count` uniform points in [0, 1].

    Mirrors ProdTargetMode._profile (core/bo_driver.py:913-920) in pure Python
    because this module must stay stdlib-only. Control points are in physical
    units, so bounds mean what they say -- unlike raw polynomial coefficients,
    where c1 = -2 would drive a radius negative.

    `clip` is (lo, hi) and is required by the schema for exactly one reason:
    a quadratic through in-range control points can still overshoot between
    them -- (50, 250, 250) reaches ~275 near i=36. Clipping projects the value
    instead of discarding the eval (same choice as ProdTargetMode._expand).
    """
    control = list(control)
    if len(control) != 3:
        raise ValueError(
            f"profile needs exactly 3 control points, got {len(control)}")
    c0, c1, c2 = control
    out: List[float] = []
    for k in range(count):
        u = 0.0 if count == 1 else k / (count - 1)
        v = c0 * (1 - 2 * u) * (1 - u) + c1 * 4 * u * (1 - u) + c2 * u * (2 * u - 1)
        if clip is not None:
            v = min(max(v, clip[0]), clip[1])
        out.append(v)
    return out


_SCALAR_TYPES = ("bool", "int", "double", "string")
_VECTOR_TYPES = ("vector<double>", "vector<string>")
_VALID_TYPES = _SCALAR_TYPES + _VECTOR_TYPES


def _validate_comment_names(text: str, available_names: Set[str], where: str) -> None:
    """Extract and validate placeholder names in a format string.

    Raises ExprError if any placeholder name is unknown or if the format string
    is malformed.
    """
    field_names = set()
    try:
        formatter = string.Formatter()
        for _, field_name, _, _ in formatter.parse(text):
            if field_name is not None:  # None means literal text with no placeholder
                # field_name can be like "a" or "a.x[0]" — we only care about the root
                root_name = field_name.split('.')[0].split('[')[0]
                if root_name:  # empty after split means something like ".x"
                    field_names.add(root_name)
    except ValueError as exc:
        # Malformed format string (e.g., unmatched brace)
        raise ExprError(f"{where}: malformed comment format string: {exc}") from None

    for name in field_names:
        if name not in available_names:
            raise ExprError(
                f"{where}: unknown name {name!r} in comment placeholder; "
                f"known names are {sorted(available_names)}")


def _reject_unknown_keys(d: dict, allowed: Iterable[str], where: str) -> None:
    """Fail loud on a typo'd or unrecognized key instead of silently no-oping
    it (e.g. a misspelled schema key parsed by nothing, doing nothing)."""
    unknown = set(d) - set(allowed)
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {sorted(unknown)}; accepted keys are "
            f"{sorted(allowed)}")


def _validate_fmt(fmt: Any, where: str) -> None:
    """A computed line's 'fmt' must (a) exist, (b) contain a replacement
    field, and (c) actually be able to format a float. Checked at load so a
    format string like "75.0" (no field -- every element renders as the same
    constant, the knob goes inert with no error) or "{:.4q}" (malformed --
    would only fail the first time render() runs) is caught here instead.
    """
    if not fmt:
        raise ValueError(f"{where}: computed line needs a 'fmt'")
    if not isinstance(fmt, str):
        raise ValueError(f"{where}: 'fmt' must be a string, got {fmt!r}")
    try:
        has_field = any(field is not None
                         for _, field, _, _ in string.Formatter().parse(fmt))
    except ValueError as exc:
        raise ValueError(f"{where}: malformed fmt {fmt!r}: {exc}") from None
    if not has_field:
        raise ValueError(
            f"{where}: fmt {fmt!r} has no replacement field (e.g. '{{:.4f}}'); "
            f"every element would render as the same literal text, silently "
            f"making the knob inert")
    try:
        fmt.format(1.0)
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise ValueError(
            f"{where}: fmt {fmt!r} cannot format a float: {exc}") from None


def _literal(type_: str, value: Any, where: str) -> str:
    """Render a JSON value as simpleConfig literal text."""
    if type_ == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{where}: type bool needs true/false, got {value!r}")
        return "true" if value else "false"
    if type_ == "string":
        if not isinstance(value, str):
            raise ValueError(f"{where}: type string needs a string, got {value!r}")
        return f'"{value}"'
    if type_ == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where}: type int needs an integer, got {value!r}")
        return str(value)
    if type_ == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where}: type double needs a number, got {value!r}")
        return str(value)
    raise ValueError(
        f"{where}: a fixed 'value' needs a scalar type {list(_SCALAR_TYPES)}, "
        f"got {type_!r}; build vectors with 'segments' or 'per_index'")


class GeomTemplate:
    """A validated geometry description. Build with from_dict, then render(x)."""

    def __init__(self, base, knob_names, consts, derived, profiles, lines):
        self._base = base
        self._knob_names = tuple(knob_names)
        self._consts = consts
        self._derived = derived      # name -> compiled
        self._profiles = profiles    # name -> (count, [compiled controls], clip)
        self._lines = lines          # list of prepared dicts

    # -- construction / validation ------------------------------------------
    @classmethod
    def from_dict(cls, d: dict, knob_names: Iterable[str], where: str) -> "GeomTemplate":
        _reject_unknown_keys(
            d, ("base", "consts", "derived", "profiles", "lines"), where)
        knob_names = tuple(knob_names)
        base = d.get("base")
        if not base:
            raise ValueError(f"{where}: geom.base is required")

        consts = dict(d.get("consts") or {})
        for k, v in consts.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{where}: const {k!r} must be a number, got {v!r}")

        # Check for namespace collisions: each name may appear in only one category
        # (knobs, consts, derived, or profiles).
        knob_set = set(knob_names)
        const_set = set(consts)
        collision = knob_set & const_set
        if collision:
            raise ValueError(
                f"{where}: name(s) {sorted(collision)} defined in both knobs and consts")

        # derived may reference knobs and consts, NOT other derived values --
        # acyclic by construction, so there is no ordering rule to get wrong.
        base_names = knob_set | const_set
        derived = {}
        derived_set = set()
        for name, src in (d.get("derived") or {}).items():
            if name in knob_set:
                raise ValueError(
                    f"{where}: name {name!r} defined in both knobs and derived")
            if name in const_set:
                raise ValueError(
                    f"{where}: name {name!r} defined in both consts and derived")
            derived[name] = compile_expr(src, base_names, f"{where}[derived.{name}]")
            derived_set.add(name)

        scalar_names = base_names | derived_set

        profiles = {}
        profiles_set = set()
        for name, p in (d.get("profiles") or {}).items():
            if name in knob_set:
                raise ValueError(
                    f"{where}: name {name!r} defined in both knobs and profiles")
            if name in const_set:
                raise ValueError(
                    f"{where}: name {name!r} defined in both consts and profiles")
            if name in derived_set:
                raise ValueError(
                    f"{where}: name {name!r} defined in both derived and profiles")
            count = cls._resolve_count(p.get("count"), consts, f"{where}[profiles.{name}]")
            control = p.get("control")
            if not control or len(control) != 3:
                raise ValueError(
                    f"{where}[profiles.{name}]: 'control' must list exactly 3 names")
            clip = p.get("clip")
            if clip is None or len(clip) != 2:
                raise ValueError(
                    f"{where}[profiles.{name}]: 'clip' is required and must be "
                    f"[lo, hi] (a quadratic overshoots between control points)")
            clip_lo, clip_hi = float(clip[0]), float(clip[1])
            if clip_lo > clip_hi:
                raise ValueError(
                    f"{where}[profiles.{name}]: clip lo={clip_lo} > hi={clip_hi}; "
                    f"this pins every element of the profile to {clip_hi} "
                    f"(byte-identical for every optimizer point), silently "
                    f"making the knob inert")
            compiled = [compile_expr(c, scalar_names, f"{where}[profiles.{name}]")
                        for c in control]
            profiles[name] = (count, compiled, (clip_lo, clip_hi))
            profiles_set.add(name)

        elementwise_names = scalar_names | profiles_set | {"i", "n"}
        # For comment validation, the available names include everything except i/n
        # (which are only valid in per_index, not in comments)
        comment_names = knob_set | const_set | derived_set | profiles_set

        lines = []
        for idx, raw_line in enumerate(d.get("lines") or []):
            lines.append(cls._prepare_line(
                raw_line, consts, scalar_names, elementwise_names, comment_names,
                f"{where}[lines[{idx}]]"))
        return cls(base, knob_names, consts, derived, profiles, lines)

    @staticmethod
    def _resolve_count(count, consts, where) -> int:
        if isinstance(count, str):
            if count not in consts:
                raise ValueError(
                    f"{where}: count {count!r} is not a declared const "
                    f"(known: {sorted(consts)})")
            count = consts[count]
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError(f"{where}: count must be an integer, got {count!r}")
        if count < 1:
            raise ValueError(f"{where}: count must be >= 1, got {count}")
        return count

    @classmethod
    def _prepare_line(cls, ln, consts, scalar_names, elementwise_names, comment_names, where):
        if "comment" in ln:
            comment_text = ln["comment"]
            _validate_comment_names(comment_text, comment_names, where)
            return {"kind": "comment", "text": comment_text}

        key, type_ = ln.get("key"), ln.get("type")
        if not key:
            raise ValueError(f"{where}: line needs a 'key'")
        if type_ not in _VALID_TYPES:
            raise ValueError(
                f"{where}: type must be one of {list(_VALID_TYPES)}, got {type_!r}")

        if "raw" in ln:
            if not isinstance(ln["raw"], str):
                raise ValueError(f"{where}: 'raw' must be a string")
            return {"kind": "raw", "key": key, "type": type_, "text": ln["raw"]}
        if "value" in ln:
            return {"kind": "literal", "key": key, "type": type_,
                    "text": _literal(type_, ln["value"], where)}

        fmt = ln.get("fmt")
        _validate_fmt(fmt, where)

        if "expr" in ln:
            if type_ not in _SCALAR_TYPES:
                raise ValueError(f"{where}: 'expr' needs a scalar type, got {type_}")
            return {"kind": "expr", "key": key, "type": type_, "fmt": fmt,
                    "expr": compile_expr(ln["expr"], scalar_names, where)}

        if "segments" in ln:
            if type_ not in _VECTOR_TYPES:
                raise ValueError(
                    f"{where}: 'segments' produces a vector; type must be one "
                    f"of {list(_VECTOR_TYPES)}, got {type_!r} (a scalar type "
                    f"here silently renders 'double k = {{ 7.00, 7.00 }};')")
            segs = []
            for j, seg in enumerate(ln["segments"]):
                sw = f"{where}.segments[{j}]"
                count = cls._resolve_count(seg.get("count"), consts, sw)
                if "expr" in seg:
                    compiled = compile_expr(seg["expr"], scalar_names, sw)
                elif "value" in seg:
                    # Validate the value with the same discipline as _literal
                    val = seg["value"]
                    if isinstance(val, bool):
                        raise ValueError(f"{sw}: segment value must be a number, not a bool")
                    if not isinstance(val, (int, float)):
                        raise ValueError(
                            f"{sw}: segment value must be a number, got {val!r}")
                    compiled = compile_expr(repr(float(val)), set(), sw)
                else:
                    raise ValueError(f"{sw}: segment needs 'expr' or 'value'")
                segs.append((count, compiled))
            return {"kind": "segments", "key": key, "type": type_, "fmt": fmt,
                    "segments": segs}

        if "per_index" in ln:
            if type_ not in _VECTOR_TYPES:
                raise ValueError(
                    f"{where}: 'per_index' produces a vector; type must be "
                    f"one of {list(_VECTOR_TYPES)}, got {type_!r}")
            pi = ln["per_index"]
            count = cls._resolve_count(pi.get("count"), consts, where)
            if "expr" not in pi:
                raise ValueError(f"{where}: per_index needs an 'expr'")
            return {"kind": "per_index", "key": key, "type": type_, "fmt": fmt,
                    "count": count,
                    "expr": compile_expr(pi["expr"], elementwise_names, where)}

        raise ValueError(
            f"{where}: line needs one of value / raw / expr / segments / per_index")

    # -- rendering ----------------------------------------------------------
    def render(self, x: Iterable[float]) -> str:
        x = list(x)
        if len(x) != len(self._knob_names):
            raise ValueError(
                f"expected {len(self._knob_names)} knob values, got {len(x)}")
        env: Dict[str, Any] = dict(zip(self._knob_names, (float(v) for v in x)))
        env.update(self._consts)
        for name, compiled in self._derived.items():
            env[name] = eval_expr(compiled, dict(env))
        for name, (count, controls, clip) in self._profiles.items():
            ctrl = [eval_expr(c, dict(env)) for c in controls]
            env[name] = lagrange_profile(ctrl, count, clip)

        out = [f'#include "{self._base}"', ""]
        for ln in self._lines:
            out.append(self._render_line(ln, env))
        return "\n".join(out) + "\n"

    def _render_line(self, ln: dict, env: dict) -> str:
        kind = ln["kind"]
        if kind == "comment":
            return "// " + ln["text"].format(**env)
        if kind in ("literal", "raw"):
            return f'{ln["type"]} {ln["key"]} = {ln["text"]};'
        if kind == "expr":
            val = eval_expr(ln["expr"], dict(env))
            return f'{ln["type"]} {ln["key"]} = {ln["fmt"].format(val)};'
        if kind == "segments":
            vals = []
            for count, compiled in ln["segments"]:
                vals.extend([eval_expr(compiled, dict(env))] * count)
        elif kind == "per_index":
            vals = []
            for i in range(ln["count"]):
                scope = dict(env)
                scope["i"] = i
                scope["n"] = ln["count"]
                vals.append(eval_expr(ln["expr"], scope))
        else:  # pragma: no cover - _prepare_line rejects anything else
            raise ValueError(f"unknown line kind {kind!r}")
        body = ", ".join(ln["fmt"].format(v) for v in vals)
        return f'{ln["type"]} {ln["key"]} = {{ {body} }};'
