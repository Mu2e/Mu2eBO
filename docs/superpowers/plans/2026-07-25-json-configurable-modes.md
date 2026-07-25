# JSON-Configurable Optimization Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let someone add a new Bayesian-optimization line to this project by writing one JSON file, with no Python changes.

**Architecture:** Purely additive. `core/modes.py` keeps its six hand-written Python `ModeSpec` entries untouched and gains a loader that reads `modes/*.json` and merges them into the same `SPECS` table. `ModeSpec` gains one optional `geom` field describing how to render a Mu2e geometry overlay; the six Python modes pass `None` explicitly. `core/bo_driver.py` gains a single generic `JsonMode` class bound to any spec carrying a `geom` block, so no new class is written per line.

**Tech Stack:** Python 3.11 (stdlib only in the new modules), `unittest`, the project venv at `.venv`.

## Global Constraints

- **The new modules must be stdlib-only.** `core/modes.py:1-8` states it is "stdlib-only so the project .venv (and any A/B picker venv) and pipeline.py can import it". `core/geom_template.py` and `core/mode_json.py` are imported by `modes.py`, so **no numpy** — the Lagrange profile must be pure Python even though `ProdTargetMode._profile` uses numpy.
- **Never silently default.** `core/modes.py:1-8`: "every field passed explicitly (a missing fact is an import error, never a default)". Every validation failure raises with the file name and the offending field.
- **Do not modify the six existing Python modes' renderers.** `FoilsMode`, `FoilsFracMode`, `FoilsFlashMode`, `FoilsGroupMode`, `ProdTargetMode`, `ProdTarget6DMode` keep their `_geom_text` and stay in production. They survived the `foilsg-holeRadii` and `prodtarget-env-divergence` incidents.
- **Do not touch `core/pipeline.py`'s foilsflash block** (`core/pipeline.py:273-292`). The JSON `stage_tuning` field is the mechanism for *JSON* modes; migrating foilsflash to it is explicitly out of scope.
- **A JSON file whose `name` collides with a Python mode is a hard error**, never an override.
- **Run the full suite with:** `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`. All **217** existing tests must stay green.
- **Run one test file with:** `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
- **Commit trailer** — every commit ends with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
  ```
- **Never `git push`.** Bash subshells cannot reach the user's ssh-agent (wiki incident `claude-bash-no-ssh-agent`).

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `core/geom_template.py` | Turn a geom description + knob values into geometry-overlay text. Owns the expression evaluator, profile expansion, and line rendering. |
| `core/mode_json.py` | Read and validate `modes/*.json`; produce `ModeSpec` objects. Owns all schema validation and error messages. |
| `modes/README.md` | Explains the folder; the folder must exist for the loader's glob. |
| `tests/test_geom_template.py` | Evaluator, profile, and renderer unit tests. |
| `tests/test_mode_json.py` | Loader validation and rejection tests. |
| `tests/test_json_mode_parity.py` | The acceptance test: semantic equality against the Python renderers. |

**Modified:**

| File | Change |
|---|---|
| `core/modes.py` | `ModeSpec` gains `geom`; six specs pass `geom=None`; JSON specs merged into `SPECS`. |
| `core/bo_driver.py` | Add `JsonMode`; register JSON specs into `MODES`. |
| `graph/state.py:36-37` | `mode: Literal[...]` becomes `mode: str`. |
| `tests/test_modes.py:23-27` | `test_keys_match_state_literal` retargeted. |

**Already committed (do not recreate):** `tests/fixtures/modes/foilsflash.json` — the acceptance-test target.

---

### Task 1: Restricted expression evaluator

Formulas in the JSON must never be `eval`'d as free text. This task builds a parser that accepts arithmetic over a whitelist of names and rejects everything else, reporting errors with enough context to find the typo.

**Files:**
- Create: `core/geom_template.py`
- Test: `tests/test_geom_template.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `class ExprError(ValueError)`
  - `compile_expr(src: str, allowed_names: set[str], where: str) -> ast.Expression`
  - `eval_expr(compiled: ast.Expression, env: dict) -> float`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geom_template.py`:

```python
import unittest

from core.geom_template import ExprError, compile_expr, eval_expr


def _ev(src, env, allowed=None):
    allowed = allowed if allowed is not None else set(env)
    return eval_expr(compile_expr(src, allowed, "test.json[k]"), env)


class TestExpr(unittest.TestCase):
    def test_arithmetic(self):
        self.assertAlmostEqual(_ev("a + b * 2", {"a": 1.0, "b": 3.0}), 7.0)
        self.assertAlmostEqual(_ev("(a - b) / 2", {"a": 5.0, "b": 1.0}), 2.0)
        self.assertAlmostEqual(_ev("-a", {"a": 4.0}), -4.0)
        self.assertAlmostEqual(_ev("a * a", {"a": 3.0}), 9.0)

    def test_whitelisted_functions(self):
        self.assertAlmostEqual(_ev("min(a, b)", {"a": 1.0, "b": 2.0}), 1.0)
        self.assertAlmostEqual(_ev("max(a, b)", {"a": 1.0, "b": 2.0}), 2.0)
        self.assertAlmostEqual(_ev("abs(a)", {"a": -2.0}), 2.0)
        self.assertAlmostEqual(_ev("sqrt(a)", {"a": 9.0}), 3.0)

    def test_profile_subscript(self):
        env = {"rOut": [10.0, 20.0, 30.0], "i": 1}
        self.assertAlmostEqual(_ev("rOut[i] * 2", env), 40.0)

    def test_unknown_name_names_the_typo_and_location(self):
        with self.assertRaises(ExprError) as cm:
            compile_expr("extra_rout_up * 2", {"extra_rOut_up"}, "modes/x.json[radii]")
        msg = str(cm.exception)
        self.assertIn("extra_rout_up", msg)
        self.assertIn("modes/x.json[radii]", msg)
        self.assertIn("extra_rOut_up", msg)  # lists what IS known

    def test_attribute_access_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("a.__class__", {"a"}, "w")

    def test_arbitrary_call_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("open('x')", {"a"}, "w")

    def test_comprehension_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("[x for x in (1, 2)]", {"a"}, "w")

    def test_string_constant_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("'abc'", {"a"}, "w")

    def test_syntax_error_is_exprerror(self):
        with self.assertRaises(ExprError):
            compile_expr("a +", {"a"}, "w")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.geom_template'`

- [ ] **Step 3: Write minimal implementation**

Create `core/geom_template.py`:

```python
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
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add core/geom_template.py tests/test_geom_template.py
git commit -m "feat(geom): restricted-AST expression evaluator for JSON modes

Formulas in mode JSON are parsed to an AST and whitelisted, never eval'd as
text. Permits arithmetic, four functions, and profile subscripting; rejects
attribute access, arbitrary calls, comprehensions, and string constants.
Unknown names report the file, the geometry key, and the known names.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 2: Lagrange profile expansion

Profiles turn three control points into a per-element curve. This must match `ProdTargetMode._profile` (`core/bo_driver.py:913-920`) exactly, but in pure Python, and it must clip — control points `(50, 250, 250)` overshoot to 275 at `i≈36`.

**Files:**
- Modify: `core/geom_template.py`
- Test: `tests/test_geom_template.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `lagrange_profile(control: Iterable[float], count: int, clip: tuple[float, float] | None) -> List[float]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_geom_template.py` (before `if __name__`):

```python
from core.geom_template import lagrange_profile


class TestProfile(unittest.TestCase):
    def test_hits_control_points_at_ends_and_middle(self):
        vals = lagrange_profile((10.0, 20.0, 30.0), 5, None)
        self.assertEqual(len(vals), 5)
        self.assertAlmostEqual(vals[0], 10.0)
        self.assertAlmostEqual(vals[2], 20.0)
        self.assertAlmostEqual(vals[-1], 30.0)

    def test_matches_prodtarget_profile(self):
        """Byte-for-byte agreement with the numpy original it replaces."""
        from core.bo_driver import ProdTargetMode
        for ctrl in [(2.0, 3.0, 4.5), (4.5, 2.0, 4.5), (3.0, 3.0, 3.0)]:
            for n in (5, 35, 49):
                want = list(ProdTargetMode._profile(ctrl, n))
                got = lagrange_profile(ctrl, n, None)
                for a, b in zip(want, got):
                    self.assertAlmostEqual(a, b, places=12,
                                           msg=f"ctrl={ctrl} n={n}")

    def test_overshoot_is_real_without_clip(self):
        """(50,250,250) exceeds 250 -- this is why clip is mandatory."""
        vals = lagrange_profile((50.0, 250.0, 250.0), 49, None)
        self.assertGreater(max(vals), 250.0)

    def test_clip_bounds_the_overshoot(self):
        vals = lagrange_profile((50.0, 250.0, 250.0), 49, (50.0, 250.0))
        self.assertLessEqual(max(vals), 250.0)
        self.assertGreaterEqual(min(vals), 50.0)

    def test_single_element(self):
        self.assertEqual(lagrange_profile((7.0, 8.0, 9.0), 1, None), [7.0])

    def test_requires_three_control_points(self):
        with self.assertRaises(ValueError):
            lagrange_profile((1.0, 2.0), 5, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: FAIL with `ImportError: cannot import name 'lagrange_profile'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/geom_template.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add core/geom_template.py tests/test_geom_template.py
git commit -m "feat(geom): pure-Python Lagrange profile with mandatory clip

Matches ProdTargetMode._profile to 12 decimal places without numpy, since
core/modes.py must stay stdlib-only. Test pins the overshoot that makes clip
mandatory: control points (50,250,250) reach 275 at i~36.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 3: Geometry renderer

Turn a validated geom description plus a knob vector into overlay text.

**Files:**
- Modify: `core/geom_template.py`
- Test: `tests/test_geom_template.py`

**Interfaces:**
- Consumes: `compile_expr`, `eval_expr`, `ExprError`, `lagrange_profile` (Tasks 1-2).
- Produces: `class GeomTemplate` with `GeomTemplate.from_dict(d: dict, knob_names: tuple, where: str) -> GeomTemplate` and `render(x: list[float]) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_geom_template.py`:

```python
from core.geom_template import GeomTemplate

KNOBS = ("a", "b")


def _tpl(lines, consts=None, derived=None, profiles=None):
    d = {"base": "Offline/base.txt", "lines": lines}
    if consts:
        d["consts"] = consts
    if derived:
        d["derived"] = derived
    if profiles:
        d["profiles"] = profiles
    return GeomTemplate.from_dict(d, KNOBS, "t.json")


class TestRender(unittest.TestCase):
    def test_base_include_is_first_line(self):
        out = _tpl([]).render([1.0, 2.0])
        self.assertTrue(
            out.startswith('#include "Offline/base.txt"\n'), repr(out[:60]))

    def test_fixed_values_by_type(self):
        out = _tpl([
            {"key": "k.b", "type": "bool", "value": False},
            {"key": "k.i", "type": "int", "value": 3825},
            {"key": "k.d", "type": "double", "value": 120.0},
            {"key": "k.s", "type": "string", "value": "COL5Poly"},
        ]).render([1.0, 2.0])
        self.assertIn("bool k.b = false;", out)
        self.assertIn("int k.i = 3825;", out)
        self.assertIn("double k.d = 120.0;", out)
        self.assertIn('string k.s = "COL5Poly";', out)

    def test_raw_emits_exact_literal(self):
        """JSON floats lose 1.0e6; raw preserves the characters."""
        out = _tpl([
            {"key": "k.hole", "type": "double", "raw": "1.0e6"},
        ]).render([1.0, 2.0])
        self.assertIn("double k.hole = 1.0e6;", out)
        self.assertNotIn("1000000.0", out)

    def test_scalar_expression(self):
        out = _tpl([
            {"key": "k.x", "type": "double", "fmt": "{:.4f}", "expr": "a * b"},
        ]).render([3.0, 4.0])
        self.assertIn("double k.x = 12.0000;", out)

    def test_segments_concatenate(self):
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "segments": [{"count": 2, "expr": "a"},
                           {"count": 3, "expr": "base"},
                           {"count": 1, "expr": "b"}]}],
            consts={"base": 9.0},
        ).render([1.0, 2.0])
        self.assertIn(
            "vector<double> k.v = { 1.0, 1.0, 9.0, 9.0, 9.0, 2.0 };", out)

    def test_count_accepts_const_name(self):
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "segments": [{"count": "n", "expr": "a"}]}],
            consts={"n": 3},
        ).render([5.0, 0.0])
        self.assertIn("vector<double> k.v = { 5.0, 5.0, 5.0 };", out)

    def test_per_index_exposes_i_and_n(self):
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "per_index": {"count": 3, "expr": "a + i"}}],
        ).render([10.0, 0.0])
        self.assertIn("vector<double> k.v = { 10.0, 11.0, 12.0 };", out)

    def test_derived_values_usable_in_expressions(self):
        out = _tpl(
            [{"key": "k.x", "type": "double", "fmt": "{:.2f}", "expr": "prod"}],
            derived={"prod": "a * b"},
        ).render([3.0, 4.0])
        self.assertIn("double k.x = 12.00;", out)

    def test_profiles_referenced_by_index(self):
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "per_index": {"count": 3, "expr": "p[i]"}}],
            profiles={"p": {"count": 3, "control": ["a", "b", "a"],
                            "clip": [0.0, 100.0]}},
        ).render([10.0, 20.0])
        self.assertIn("vector<double> k.v = { 10.0, 20.0, 10.0 };", out)

    def test_comments_interpolate_knobs(self):
        out = _tpl([{"comment": "up rOut={a:.2f} n={n}"}],
                   consts={"n": 6}).render([1.5, 0.0])
        self.assertIn("// up rOut=1.50 n=6", out)

    def test_unknown_name_rejected_at_from_dict(self):
        with self.assertRaises(ExprError):
            _tpl([{"key": "k.x", "type": "double", "fmt": "{:.1f}",
                   "expr": "nope"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: FAIL with `ImportError: cannot import name 'GeomTemplate'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/geom_template.py`:

```python
_SCALAR_TYPES = ("bool", "int", "double", "string")
_VECTOR_TYPES = ("vector<double>", "vector<string>")
_VALID_TYPES = _SCALAR_TYPES + _VECTOR_TYPES


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
    raise ValueError(f"{where}: unknown type {type_!r}")


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
        knob_names = tuple(knob_names)
        base = d.get("base")
        if not base:
            raise ValueError(f"{where}: geom.base is required")

        consts = dict(d.get("consts") or {})
        for k, v in consts.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{where}: const {k!r} must be a number, got {v!r}")

        # derived may reference knobs and consts, NOT other derived values --
        # acyclic by construction, so there is no ordering rule to get wrong.
        base_names = set(knob_names) | set(consts)
        derived = {}
        for name, src in (d.get("derived") or {}).items():
            derived[name] = compile_expr(src, base_names, f"{where}[derived.{name}]")

        scalar_names = base_names | set(derived)

        profiles = {}
        for name, p in (d.get("profiles") or {}).items():
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
            compiled = [compile_expr(c, scalar_names, f"{where}[profiles.{name}]")
                        for c in control]
            profiles[name] = (count, compiled, (float(clip[0]), float(clip[1])))

        elementwise_names = scalar_names | set(profiles) | {"i", "n"}

        lines = []
        for idx, raw_line in enumerate(d.get("lines") or []):
            lines.append(cls._prepare_line(
                raw_line, consts, scalar_names, elementwise_names,
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
    def _prepare_line(cls, ln, consts, scalar_names, elementwise_names, where):
        if "comment" in ln:
            return {"kind": "comment", "text": ln["comment"]}

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
        if not fmt:
            raise ValueError(f"{where}: computed line needs a 'fmt'")

        if "expr" in ln:
            if type_ not in _SCALAR_TYPES:
                raise ValueError(f"{where}: 'expr' needs a scalar type, got {type_}")
            return {"kind": "expr", "key": key, "type": type_, "fmt": fmt,
                    "expr": compile_expr(ln["expr"], scalar_names, where)}

        if "segments" in ln:
            segs = []
            for j, seg in enumerate(ln["segments"]):
                sw = f"{where}.segments[{j}]"
                count = cls._resolve_count(seg.get("count"), consts, sw)
                if "expr" in seg:
                    compiled = compile_expr(seg["expr"], scalar_names, sw)
                elif "value" in seg:
                    compiled = compile_expr(repr(float(seg["value"])), set(), sw)
                else:
                    raise ValueError(f"{sw}: segment needs 'expr' or 'value'")
                segs.append((count, compiled))
            return {"kind": "segments", "key": key, "type": type_, "fmt": fmt,
                    "segments": segs}

        if "per_index" in ln:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_geom_template -v`
Expected: PASS, 26 tests

- [ ] **Step 5: Commit**

```bash
git add core/geom_template.py tests/test_geom_template.py
git commit -m "feat(geom): declarative geometry renderer

Five line forms -- value, raw, expr, segments, per_index -- plus consts,
derived values, profiles, and interpolated comments. Every formula is
compiled and name-checked at from_dict, so a typo fails before any job is
submitted rather than mid-campaign.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 4: `ModeSpec` gains an optional `geom` field

**Files:**
- Modify: `core/modes.py:60-266`
- Test: `tests/test_modes.py`

**Interfaces:**
- Consumes: `GeomTemplate` (Task 3).
- Produces: `ModeSpec.geom: Optional[GeomTemplate]`, `ModeSpec.metrics: Optional[Dict[str, Tuple[str, ...]]]`, `ModeSpec.leaderboard_rel: Optional[str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_modes.py` inside the existing test class file (add a new class at the end, before any `if __name__`):

```python
class TestGeomField(unittest.TestCase):
    def test_python_modes_declare_the_json_fields_as_none(self):
        for name, spec in modes.SPECS.items():
            self.assertIsNone(spec.geom, f"{name} should have no geom template")
            self.assertIsNone(spec.metrics, f"{name} should have no metrics map")
            self.assertIsNone(spec.leaderboard_rel, f"{name} sets leaderboard on the class")

    def test_the_new_fields_are_required_not_defaulted(self):
        """A missing fact must be a TypeError, never a silent default."""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(modes.ModeSpec)}
        for field in ("geom", "metrics", "leaderboard_rel"):
            self.assertIn(field, fields)
            self.assertIs(dataclasses.fields(modes.ModeSpec)[0].default,
                          dataclasses.MISSING)
        with self.assertRaises(TypeError):
            modes.ModeSpec(name="x")  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_modes -v`
Expected: FAIL with `AttributeError: 'ModeSpec' object has no attribute 'geom'`

- [ ] **Step 3: Write minimal implementation**

In `core/modes.py`, add the import near the top (after the `typing` import):

```python
from core.geom_template import GeomTemplate
```

Add these two fields to the `ModeSpec` dataclass, immediately after `obs_noise`:

```python
    # Declarative geometry, metric mapping, and leaderboard path. Present ONLY
    # on JSON-defined modes (core/mode_json.py); the six Python modes render via
    # their BOMode subclass, set `leaderboard` as a class attribute, and pass
    # None here EXPLICITLY, never by default.
    geom: Optional[GeomTemplate]
    metrics: Optional[Dict[str, Tuple[str, ...]]]
    leaderboard_rel: Optional[str]
```

Then add `geom=None,`, `metrics=None,` and `leaderboard_rel=None,` as the last three arguments of **each** of the six `ModeSpec(...)` calls in `SPECS` — `foils`, `foilsf`, `foilsflash`, `foilsg`, `prodtarget`, `prodtarget6d`. For example, `foils` ends:

```python
        obs_noise=_FOILS_FAMILY_NOISE,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
Expected: PASS — 245 tests (217 pre-existing + 26 from Tasks 1-3 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add core/modes.py tests/test_modes.py
git commit -m "feat(modes): ModeSpec gains optional geom and metrics fields

Both are REQUIRED constructor arguments carrying None for the six Python
modes, matching the module's rule that a missing fact is an import error
rather than a silent default.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 5: JSON loader

**Files:**
- Create: `core/mode_json.py`, `modes/README.md`
- Modify: `core/modes.py` (call the loader after `SPECS` is defined)
- Test: `tests/test_mode_json.py`

**Interfaces:**
- Consumes: `ModeSpec` (Task 4), `GeomTemplate.from_dict` (Task 3).
- Produces: `load_mode_file(path: Path) -> ModeSpec`, `load_mode_dir(directory: Path, existing: dict) -> Dict[str, ModeSpec]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mode_json.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from core import modes
from core.mode_json import load_mode_dir, load_mode_file

FIXTURE = Path(__file__).parent / "fixtures" / "modes" / "foilsflash.json"


def _write(tmp: Path, name: str, doc: dict) -> Path:
    p = tmp / f"{name}.json"
    p.write_text(json.dumps(doc))
    return p


def _valid_doc() -> dict:
    doc = json.loads(FIXTURE.read_text())
    doc["name"] = "demo"
    return doc


class TestLoadFixture(unittest.TestCase):
    def test_fixture_loads_into_a_modespec(self):
        spec = load_mode_file(FIXTURE)
        self.assertEqual(spec.name, "foilsflash")
        self.assertIsNotNone(spec.geom)
        self.assertEqual(spec.grid_stages,
                         ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(spec.metric_cols, ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(spec.obs_noise, (0.006, 0.010))
        self.assertEqual(spec.metrics["sob"], ("s_over_sqrt_b",))

    def test_fixture_matches_the_python_spec(self):
        """The fixture is the acceptance target: its facts must equal the live spec."""
        spec, live = load_mode_file(FIXTURE), modes.SPECS["foilsflash"]
        for field in ("musing", "grid_tarball", "grid_stages", "harvest_verb",
                      "stage_target_overrides", "presubmit_after", "bounds_lo",
                      "bounds_hi", "knob_names", "knob_fmts", "metric_cols",
                      "obs_noise", "preflight_fcl", "dumps_gdml",
                      "verifies_foil_gdml", "preserves_gdml",
                      "checks_managed_overlap"):
            self.assertEqual(getattr(spec, field), getattr(live, field), field)


class TestRejections(unittest.TestCase):
    def _expect_error(self, mutate, *needles):
        doc = _valid_doc()
        mutate(doc)
        with tempfile.TemporaryDirectory() as td:
            p = _write(Path(td), "demo", doc)
            with self.assertRaises(ValueError) as cm:
                load_mode_file(p)
        msg = str(cm.exception)
        for needle in needles:
            self.assertIn(needle, msg)

    def test_missing_required_field(self):
        self._expect_error(lambda d: d.pop("software"), "software")

    def test_unknown_name_in_formula(self):
        self._expect_error(
            lambda d: d["geom"]["derived"].update({"rIn_up": "nope * 2"}),
            "nope")

    def test_metric_column_count_must_be_four(self):
        self._expect_error(
            lambda d: d["leaderboard"].update({"columns": ["sob", "obj"]}),
            "columns")

    def test_knob_bounds_lockstep(self):
        def drop_a_knob(d):
            d["knobs"] = d["knobs"][:-1]
        self._expect_error(drop_a_knob, "lockstep")

    def test_profile_without_clip_rejected(self):
        def add_bad_profile(d):
            d["geom"]["profiles"] = {
                "p": {"count": 3, "control": ["extra_f_up"] * 3}}
        self._expect_error(add_bad_profile, "clip")


class TestCollision(unittest.TestCase):
    def test_name_collision_with_python_mode_is_hard_error(self):
        with tempfile.TemporaryDirectory() as td:
            _write(Path(td), "foilsflash", json.loads(FIXTURE.read_text()))
            with self.assertRaises(ValueError) as cm:
                load_mode_dir(Path(td), modes.SPECS)
            self.assertIn("foilsflash", str(cm.exception))
            self.assertIn("collides", str(cm.exception))

    def test_missing_directory_yields_no_modes(self):
        self.assertEqual(load_mode_dir(Path("/nonexistent/modes"), {}), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_mode_json -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.mode_json'`

- [ ] **Step 3: Write minimal implementation**

Create `core/mode_json.py`:

```python
"""Load and validate JSON-defined modes into ModeSpec objects.

One JSON file per optimization line, in modes/. Every check happens at load
time so a typo is an import error, never a corrupt geometry six hours into a
campaign. STDLIB ONLY (see core/modes.py:1-8).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from core.geom_template import GeomTemplate

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
    from core.modes import ModeSpec  # local import: modes.py imports this module

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

    geom = GeomTemplate.from_dict(doc["geom"], names, f"{where}[geom]")

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
    if spec.name != path.stem and path.stem != "foilsflash":
        # fixture aside, the file name is the mode name -- keeps modes/ greppable
        raise ValueError(
            f"{where}: mode name {spec.name!r} does not match file name "
            f"{path.stem!r}")
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
        if spec.name in existing or spec.name in out:
            raise ValueError(
                f"{path}: mode name {spec.name!r} collides with an existing "
                f"mode; JSON modes never override Python modes")
        out[spec.name] = spec
    return out
```

Create `modes/README.md`:

```markdown
# JSON-defined optimization modes

One file per optimization line: `modes/<name>.json`, where `<name>` matches the
`"name"` field. Every file here is loaded at import and merged into
`core.modes.SPECS`.

See `docs/superpowers/specs/2026-07-25-json-configurable-modes-design.md` for the
schema, and `tests/fixtures/modes/foilsflash.json` for a complete worked example.

A file whose name collides with a Python-defined mode (foils, foilsf, foilsflash,
foilsg, prodtarget, prodtarget6d) is a hard error, not an override.
```

Append to `core/modes.py`, after the `SPECS` dict literal closes:

```python
# JSON-defined modes (one file per line) are merged in AFTER the Python table,
# and may never shadow it -- see core/mode_json.py.
from core.mode_json import load_mode_dir  # noqa: E402 - SPECS must exist first

MODES_DIR = Path(__file__).resolve().parent.parent / "modes"
SPECS.update(load_mode_dir(MODES_DIR, SPECS))
```

Add `from pathlib import Path` to `core/modes.py`'s imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
Expected: PASS — 254 tests

- [ ] **Step 5: Commit**

```bash
git add core/mode_json.py core/modes.py modes/README.md tests/test_mode_json.py
git commit -m "feat(modes): load modes/*.json into SPECS

One JSON file per optimization line, validated entirely at load. A name that
collides with a Python mode is a hard error rather than an override --
silently shadowing foilsflash would be a new way to build wrong geometry.

Tests pin the committed foilsflash fixture against the live Python spec on
all 17 facts.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 6: `JsonMode` driver class

**Files:**
- Modify: `core/bo_driver.py:1152-1159`
- Test: `tests/test_json_mode.py`

**Interfaces:**
- Consumes: `ModeSpec.geom`, `ModeSpec.metrics` (Tasks 4-5).
- Produces: `class JsonMode(BOMode)` and `MODES` entries for every JSON spec.

- [ ] **Step 1: Write the failing test**

Create `tests/test_json_mode.py`:

```python
import json
import unittest
from pathlib import Path

from core import modes
from core.bo_driver import JsonMode
from core.mode_json import load_mode_file

FIXTURE = Path(__file__).parent / "fixtures" / "modes" / "foilsflash.json"


class TestJsonMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dataclasses
        # register under a non-colliding name so SPECS/MODES stay clean
        cls.spec = dataclasses.replace(load_mode_file(FIXTURE), name="demoflash")
        modes.SPECS["demoflash"] = cls.spec
        cls.mode = JsonMode("demoflash")

    @classmethod
    def tearDownClass(cls):
        modes.SPECS.pop("demoflash", None)

    def test_knob_names_and_space_come_from_the_spec(self):
        self.assertEqual(self.mode.KNOB_NAMES, self.spec.knob_names)
        space = self.mode.build_space()
        self.assertEqual(len(space), 6)
        self.assertEqual(space[0].lo, 50.0)
        self.assertEqual(space[0].hi, 250.0)

    def test_geom_text_renders(self):
        text = self.mode._geom_text([120.0, 130.0, 0.1, 0.2, 0.3, 0.4])
        self.assertIn("#include", text)
        self.assertIn("stoppingTarget.radii", text)
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;", text)

    def test_no_priors(self):
        self.assertEqual(self.mode.load_priors(), [])

    def test_parse_geom_refuses_clearly(self):
        with self.assertRaises(NotImplementedError) as cm:
            self.mode.parse_geom("anything")
        self.assertIn("demoflash", str(cm.exception))

    def test_extract_metrics_uses_the_fallback_chain(self):
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 1e-6}),
            (3.9, 1e-6))
        # falls through to the second key when the first is absent
        self.assertEqual(
            self.mode.extract_metrics(
                {"s_over_sqrt_b": 3.9, "flash_edep_per_event": 2e-6}),
            (3.9, 2e-6))

    def test_extract_metrics_missing_key_names_the_column(self):
        with self.assertRaises(KeyError) as cm:
            self.mode.extract_metrics({"s_over_sqrt_b": 3.9})
        self.assertIn("flash_edep", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_json_mode -v`
Expected: FAIL with `ImportError: cannot import name 'JsonMode'`

- [ ] **Step 3: Write minimal implementation**

In `core/bo_driver.py`, add this class immediately before the `MODES` dict:

```python
class JsonMode(BOMode):
    """The single driver class behind every JSON-defined mode.

    All the leaderboard/search-space behaviour is inherited: BOMode reads
    KNOB_NAMES, KNOB_FMTS, CALO_COL, format_row and build_space straight from
    modes.SPECS, so a JSON spec gets them with no code. Only the three abstract
    methods need filling, and two of them are deliberately empty:
    priors (a new line has none -- botorch Sobol cold-starts) and parse_geom
    (geometry round-trip is out of scope by design decision).
    """

    def __init__(self, name: str):
        spec = _modes.SPECS[name]
        if spec.geom is None:
            raise ValueError(f"{name}: JsonMode requires a geom template")
        self.name = name
        self.leaderboard = ROOT / spec.leaderboard_rel
        self.proposal_dir = ROOT / "bo_work" / "proposals" / name
        self.preflight_dir = ROOT / "bo_work" / "preflight" / name

    def load_priors(self) -> list[Point]:
        return []

    def _geom_text(self, x) -> str:
        return _modes.SPECS[self.name].geom.render(x)

    def parse_geom(self, text: str):
        raise NotImplementedError(
            f"{self.name}: JSON-defined modes do not support geometry "
            f"round-trip (parse_geom). It is out of scope by design; see "
            f"docs/superpowers/specs/2026-07-25-json-configurable-modes-design.md")

    def extract_metrics(self, summary: dict) -> tuple[float, float]:
        spec = _modes.SPECS[self.name]
        out = []
        for col in spec.metric_cols[:2]:
            for key in spec.metrics[col]:
                if summary.get(key) is not None:
                    out.append(float(summary[key]))
                    break
            else:
                raise KeyError(
                    f"{self.name}: summary.json has none of "
                    f"{list(spec.metrics[col])} for column {col!r}")
        return out[0], out[1]
```

Directly after the `MODES` dict literal, register one `JsonMode` per JSON spec:

```python
# JSON-defined modes: one JsonMode per spec carrying a geom template. The six
# Python modes are already in MODES above and are never replaced -- the loader
# in core/mode_json.py has already rejected any name collision.
for _name, _spec in _modes.SPECS.items():
    if _spec.geom is not None:
        MODES[_name] = JsonMode(_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
Expected: PASS — 260 tests

- [ ] **Step 5: Commit**

```bash
git add core/bo_driver.py core/geom_template.py core/mode_json.py tests/test_json_mode.py
git commit -m "feat(driver): one generic JsonMode behind every JSON mode

BOMode already reads knob names, formats, objective column, row format and
search space from modes.SPECS, so a JSON spec inherits all of it. Only
_geom_text does real work; priors and parse_geom are deliberately empty per
the design's scope decisions, and parse_geom says so when called.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 7: Relax the mode `Literal` and retarget its test

`graph/state.py` hardcodes the six mode names. It is a `TypedDict` annotation, erased at runtime, so nothing breaks — but a test pins it, and a JSON mode would fail that test.

**Files:**
- Modify: `graph/state.py:34-37`
- Modify: `tests/test_modes.py:23-27`

**Interfaces:**
- Consumes: `modes.SPECS`, `bo_driver.MODES`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Replace `test_keys_match_state_literal` in `tests/test_modes.py` with:

```python
    def test_every_spec_has_a_driver(self):
        """The completeness guarantee the old Literal test provided: a mode
        declared anywhere must be constructible. JSON modes are registered at
        import, so this covers them too."""
        import core.bo_driver as bo
        for name in modes.SPECS:
            self.assertIn(name, bo.MODES, f"{name} has no driver in MODES")

    def test_state_mode_is_not_a_closed_literal(self):
        """JSON modes are discovered at runtime, so the annotation cannot
        enumerate them."""
        import typing
        import graph.state as st
        ann = typing.get_type_hints(st.BOIterationState)["mode"]
        self.assertIs(ann, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_modes -v`
Expected: FAIL — `test_state_mode_is_not_a_closed_literal` fails because the annotation is still a `Literal`.

- [ ] **Step 3: Write minimal implementation**

In `graph/state.py`, replace lines 34-37:

```python
    # Mode name. NOT a Literal: JSON-defined modes (modes/*.json) are
    # discovered at import, so the set is not knowable statically. The real
    # completeness check is tests/test_modes.py::test_every_spec_has_a_driver,
    # which asserts every modes.SPECS entry has a driver in bo_driver.MODES.
    mode: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
Expected: PASS — 261 tests

- [ ] **Step 5: Commit**

```bash
git add graph/state.py tests/test_modes.py
git commit -m "refactor(state): mode is str, not a closed Literal

JSON modes are discovered at import, so the annotation cannot enumerate
them. The Literal only ever bound a test (it is a TypedDict field, erased at
runtime); that test is retargeted to the guarantee that actually matters --
every spec has a constructible driver.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 8: Acceptance test — semantic parity with the Python renderers

The whole feature rests on this: if the JSON can regenerate a live campaign's geometry, it can carry a new line.

Covers **foilsflash** (segments + `derived` + `raw`) and **foils** (segments with
absolute hole radii, no `derived`). **`prodtarget` is deliberately not covered** — its
`metric_cols` has five entries and `BOMode.format_row` (`bo_driver.py:185-198`) raises
unless there are exactly four, so a prodtarget-shaped JSON mode cannot be written at all
until `format_row` is generalized. Its `_expand` also clips one profile against another
profile's per-element value (`bo_driver.py:936-938`), which the constant `clip` cannot
express. Profiles are instead proven by Task 2's unit test, which pins `lagrange_profile`
against `ProdTargetMode._profile` to 12 decimal places.

**Files:**
- Create: `tests/fixtures/modes/foils.json`
- Create: `tests/test_json_mode_parity.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1a: Create the `foils` fixture**

`foils` is the same 49-foil geometry as foilsflash, but its last two knobs are
**absolute hole radii in mm**, not fractions — so there is no `derived` block and
`holeRadii` reads the knobs directly. Its second objective is `calo`, not `flash_edep`.

Create `tests/fixtures/modes/foils.json` by copying
`tests/fixtures/modes/foilsflash.json` and making exactly these changes:

```jsonc
  "name": "foils",
  "run": {
    "stages": ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    "harvest": "harvest",
    "jobs_per_stage": {},
    "presubmit_after": {},
    "stage_tuning": {}
  },
  // last two knobs are radii in mm, and the halfThickness floor is 0.01 not 0.002
  "knobs": [
    {"name": "extra_rOut_up",          "min": 50.0, "max": 250.0, "fmt": "{:.4f}"},
    {"name": "extra_rOut_dn",          "min": 50.0, "max": 250.0, "fmt": "{:.4f}"},
    {"name": "extra_halfThickness_up", "min": 0.01, "max": 1.0,   "fmt": "{:.6f}"},
    {"name": "extra_halfThickness_dn", "min": 0.01, "max": 1.0,   "fmt": "{:.6f}"},
    {"name": "extra_rIn_up",           "min": 0.0,  "max": 50.0,  "fmt": "{:.4f}"},
    {"name": "extra_rIn_dn",           "min": 0.0,  "max": 50.0,  "fmt": "{:.4f}"}
  ],
  "leaderboard": {
    "file":      "leaderboards/leaderboard_bo_foils_v2.tsv",
    "columns":   ["sob", "calo", "alpha", "obj"],
    "obs_noise": [0.006, 0.035],
    "metrics": {"sob": ["s_over_sqrt_b"], "calo": ["calo_per_pot"]}
  },
```

In `geom`, **delete the `derived` block entirely** and change the two `holeRadii`
segment expressions from `rIn_up` / `rIn_dn` to `extra_rIn_up` / `extra_rIn_dn`. Update
the two interpolated comments that mention `{rIn_up:.2f}` / `{rIn_dn:.2f}` to
`{extra_rIn_up:.2f}` / `{extra_rIn_dn:.2f}`. Everything else is unchanged.

- [ ] **Step 1b: Write the failing test**

Create `tests/test_json_mode_parity.py`:

```python
"""Acceptance test: a JSON mode must produce the SAME GEOMETRY as the Python
renderer it reproduces.

Semantic equality, not byte equality. Byte equality would force the JSON to
reproduce cosmetic alignment (the renderer pads stoppingTarget.radii so '='
lines up with halfThicknesses), non-ASCII comment characters, and an inherited
header calling foilsflash "foils mode v2, 6D" -- none of which reaches Geant4.
"""
import os
import re
import unittest
from pathlib import Path

from core.bo_driver import MODES
from core.mode_json import load_mode_file

FIXTURES = Path(__file__).parent / "fixtures" / "modes"

# FoilsMode reads these; the JSON freezes them, so parity is defined at default.
_ENV_OVERRIDES = ("AUTORESEARCH_BASE_HOLE_RADIUS_MM",
                  "AUTORESEARCH_N_UP", "AUTORESEARCH_N_DOWN")

_ASSIGN_RX = re.compile(
    r"^\s*(?:bool|int|double|string|vector<double>|vector<string>)\s+"
    r"([A-Za-z0-9_.]+)\s*=\s*(.+?);\s*$")


def parse_assignments(text: str) -> dict:
    """geom text -> {key: normalised value string}. Comments and whitespace
    are dropped; every number is kept exactly as emitted."""
    out = {}
    for line in text.splitlines():
        line = line.split("//")[0]
        m = _ASSIGN_RX.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("{"):
            inner = val.strip("{} ").strip()
            val = "{" + ",".join(p.strip() for p in inner.split(",")) + "}"
        out[key] = val
    return out


# Interior point plus both box corners: corners are where formats and clipping
# are most likely to diverge.
SAMPLE_X = {
    "foilsflash": [
        [120.0, 130.0, 0.10, 0.20, 0.30, 0.40],
        [50.0, 250.0, 0.002, 1.0, 0.0, 0.95],
        [175.5, 62.25, 0.5289, 0.0031, 0.7654, 0.1234],
        [250.0, 50.0, 1.0, 0.002, 0.95, 0.0],
    ],
    "foils": [
        [120.0, 130.0, 0.10, 0.20, 15.0, 40.0],
        [50.0, 250.0, 0.01, 1.0, 0.0, 50.0],
        [175.5, 62.25, 0.5289, 0.0131, 33.75, 4.5],
        [250.0, 50.0, 1.0, 0.01, 50.0, 0.0],
    ],
}


class ParityMixin:
    """Renders the fixture and the Python mode of the same name, and requires
    the parsed assignments to match exactly."""
    mode_name = ""

    @classmethod
    def setUpClass(cls):
        cls._saved = {k: os.environ.pop(k, None) for k in _ENV_OVERRIDES}
        cls.spec = load_mode_file(FIXTURES / f"{cls.mode_name}.json")

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_same_geometry_as_python_renderer(self):
        python_mode = MODES[self.mode_name]
        for x in SAMPLE_X[self.mode_name]:
            want = parse_assignments(python_mode._geom_text(x))
            got = parse_assignments(self.spec.geom.render(x))
            self.assertEqual(set(want), set(got), f"key sets differ at x={x}")
            for key in want:
                self.assertEqual(want[key], got[key], f"{key} differs at x={x}")

    def test_the_49_numbers_are_all_compared(self):
        """Guards the guard: a vector really does carry 49 entries."""
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        radii = parse_assignments(text)["stoppingTarget.radii"]
        self.assertEqual(len(radii.strip("{}").split(",")), 49)

    def test_poison_pill_scalar_survives(self):
        text = self.spec.geom.render(SAMPLE_X[self.mode_name][0])
        self.assertEqual(
            parse_assignments(text)["stoppingTarget.holeRadius"], "1.0e6")


class TestFoilsflashParity(ParityMixin, unittest.TestCase):
    mode_name = "foilsflash"


class TestFoilsParity(ParityMixin, unittest.TestCase):
    mode_name = "foils"


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_json_mode_parity -v`
Expected: FAIL if any construct is wrong — this is the test that proves the feature.

- [ ] **Step 3: Fix whatever it reports**

No new implementation should be needed. If the test fails, the defect is in
Task 3's renderer or the fixture, not in the test — the Python renderer is the
reference. Common causes and their fixes:

- A vector's numbers differ in the last digit → the `fmt` in the fixture does
  not match the Python `f"{r:.4f}"` / `f"{h:.6f}"`.
- A key is missing from `got` → a line is absent from the fixture's `lines`.
- `stoppingTarget.holeRadius` reads `1000000.0` → the fixture used `value`
  instead of `raw`.

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
Expected: PASS — 267 tests, including the original 217.

- [ ] **Step 5: Commit**

```bash
git add tests/test_json_mode_parity.py
git commit -m "test(modes): acceptance parity against the Python renderer

Renders the committed foilsflash fixture and FoilsFlashMode._geom_text at
four sampled points including both box corners, then compares parsed
key -> value maps: every key, and all 49 numbers per vector at full emitted
precision. Comments and alignment are excluded because they do not reach
Geant4. Env overrides are cleared, since the JSON freezes them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

## Verification

After Task 8, the whole feature is verifiable end-to-end:

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests
```
Expected: **OK**, 267 tests (217 pre-existing + 50 new).

These counts are the expected arithmetic, not a contract: if your total differs,
reconcile it against the per-task deltas (9, 6, 11, 2, 9, 6, +2-1, 6) before assuming
a test is missing.

Then confirm a JSON mode is actually usable as a mode:

```bash
PYTHONPATH= .venv/bin/python -c "
from core import modes
from core.bo_driver import MODES
print('specs:', sorted(modes.SPECS))
print('drivers:', sorted(MODES))
assert set(modes.SPECS) == set(MODES)
print('OK - every spec has a driver')
"
```

## Out of scope (decided, do not implement)

- Per-knob arrays (`{"name": "rOut", "count": 49}` with independent `rOut[i]` knobs).
- `buildable` expressions rejecting infeasible points — `clip` projects instead.
- `parse_geom` round-trip for JSON modes.
- Prior seeding for JSON modes.
- Migrating any of the six Python modes to JSON.
- Migrating `core/pipeline.py:273-292`'s foilsflash tuning block.
