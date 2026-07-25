"""Render a Mu2e geometry overlay from a declarative JSON description.

Used by JSON-defined modes (core/mode_json.py). STDLIB ONLY — core/modes.py
imports this and must stay importable from any venv (see core/modes.py:1-8),
so no numpy even where bo_driver.py uses it.
"""
from __future__ import annotations

import ast
import math
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
