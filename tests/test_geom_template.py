import sys
import unittest
from pathlib import Path

# Bare `core/`-on-sys.path convention (matches tests/test_modes.py,
# test_mode_json.py, test_json_mode.py, test_json_mode_parity.py): a
# qualified `from core.geom_template import ...` loads a SECOND,
# non-identical GeomTemplate/ExprError class under the `core.geom_template`
# sys.modules key alongside the bare one core/mode_json.py itself uses,
# reproducing the two-non-identical-classes bug Task 4 fixed for this exact
# module (see core/modes.py's tail comment). TestSingleModeSpecClass in
# tests/test_mode_json.py asserts "core.geom_template" and "core.bo_driver"
# never land in sys.modules across the whole suite -- this file was the gap.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from geom_template import ExprError, compile_expr, eval_expr  # noqa: E402


def _ev(src, env, allowed=None, profiles=frozenset()):
    allowed = allowed if allowed is not None else set(env)
    return eval_expr(
        compile_expr(src, allowed, "test.json[k]", profiles), env)


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
        # Subscripting is legal only on a DECLARED profile name (F9); every
        # other known name is a float at render time.
        self.assertAlmostEqual(
            _ev("rOut[i] * 2", env, profiles={"rOut"}), 40.0)

    def test_subscripting_a_non_profile_rejected(self):
        with self.assertRaises(ExprError) as cm:
            compile_expr("a[i]", {"a", "i"}, "modes/x.json[radii]",
                         profiles={"p"})
        msg = str(cm.exception)
        self.assertIn("a", msg)
        self.assertIn("modes/x.json[radii]", msg)

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

    def test_exponentiation_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("a ** 2", {"a"}, "w")


from geom_template import lagrange_profile  # noqa: E402


class TestProfile(unittest.TestCase):
    def test_hits_control_points_at_ends_and_middle(self):
        vals = lagrange_profile((10.0, 20.0, 30.0), 5, None)
        self.assertEqual(len(vals), 5)
        self.assertAlmostEqual(vals[0], 10.0)
        self.assertAlmostEqual(vals[2], 20.0)
        self.assertAlmostEqual(vals[-1], 30.0)

    # test_matches_prodtarget_profile removed 2026-08-08: was a byte-for-byte
    # parity check of lagrange_profile against ProdTargetMode._profile, the
    # numpy original it replaced. ProdTargetMode was archived along with the
    # other four dormant Python-mode adapters (no JSON successor -- the
    # "prodtarget" line was retired outright), so the reference
    # implementation no longer exists to compare against. lagrange_profile
    # itself stays live (foilspf's K=3 control-point profiles) and remains
    # covered by the other tests in this class.

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


from geom_template import GeomTemplate  # noqa: E402

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
        # NB: the const is n_foils, not n -- `n` is reserved (F9/F2: the
        # per_index loop injects it) and is rejected at from_dict.
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "segments": [{"count": "n_foils", "expr": "a"}]}],
            consts={"n_foils": 3},
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
        out = _tpl([{"comment": "up rOut={a:.2f} n={n_foils}"}],
                   consts={"n_foils": 6}).render([1.5, 0.0])
        self.assertIn("// up rOut=1.50 n=6", out)

    def test_unknown_name_rejected_at_from_dict(self):
        with self.assertRaises(ExprError):
            _tpl([{"key": "k.x", "type": "double", "fmt": "{:.1f}",
                   "expr": "nope"}])

    def test_comment_with_undefined_name_rejected_at_from_dict(self):
        """Bad comment name caught at from_dict, not at render (Critical finding #1)."""
        with self.assertRaises(ExprError) as cm:
            _tpl([{"comment": "value is {undefined_knob}"}])
        msg = str(cm.exception)
        self.assertIn("undefined_knob", msg)
        self.assertIn("t.json", msg)  # file locator

    def test_comment_undefined_name_not_wrapped_as_malformed(self):
        """Unknown comment name error is not re-wrapped as malformed (Fix A)."""
        with self.assertRaises(ExprError) as cm:
            _tpl([{"comment": "val={typo_name}"}])
        msg = str(cm.exception)
        # Should mention the typo, not mislabel it as malformed
        self.assertIn("typo_name", msg)
        self.assertNotIn("malformed", msg.lower())
        # Should not double the locator
        self.assertEqual(msg.count("t.json"), 1)

    def test_comment_malformed_format_string_detected(self):
        """Malformed format string (unmatched brace) raises ExprError (Fix A)."""
        with self.assertRaises(ExprError) as cm:
            _tpl([{"comment": "value is {a"}])  # missing closing brace
        msg = str(cm.exception)
        self.assertIn("malformed", msg.lower())
        self.assertIn("t.json", msg)

    def test_namespace_collision_knob_vs_const(self):
        """Const name colliding with knob name is rejected at from_dict (Important finding #2)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([], consts={"a": 5.0})  # knobs are ("a", "b")
        msg = str(cm.exception)
        self.assertIn("a", msg)
        self.assertIn("knobs", msg)
        self.assertIn("consts", msg)

    def test_namespace_collision_knob_vs_derived(self):
        """Derived name colliding with knob name is rejected at from_dict."""
        with self.assertRaises(ValueError) as cm:
            _tpl([], derived={"a": "b * 2"})  # knobs are ("a", "b")
        msg = str(cm.exception)
        self.assertIn("a", msg)

    def test_namespace_collision_knob_vs_profile(self):
        """Profile name colliding with knob name is rejected at from_dict."""
        with self.assertRaises(ValueError) as cm:
            _tpl([], profiles={"a": {"count": 3, "control": ["b", "b", "b"],
                                     "clip": [0.0, 100.0]}})  # knobs are ("a", "b")
        msg = str(cm.exception)
        self.assertIn("a", msg)

    def test_segment_value_rejects_bool(self):
        """Segment value=true is rejected, not silently converted to 1.0 (Important finding #3)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "segments": [{"count": 1, "value": True}]}])
        msg = str(cm.exception)
        self.assertIn("segments[0]", msg)
        self.assertIn("bool", msg)

    def test_segment_value_rejects_non_numeric(self):
        """Segment value with invalid type is rejected with context."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "segments": [{"count": 1, "value": "not_a_number"}]}])
        msg = str(cm.exception)
        self.assertIn("segments[0]", msg)

    def test_segment_value_numeric_still_works(self):
        """Segment value with a valid number still renders correctly (coverage fix)."""
        out = _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                     "segments": [{"count": 2, "value": 3.14}, {"count": 1, "value": 2}]}]
        ).render([1.0, 2.0])
        self.assertIn("vector<double> k.v = { 3.1, 3.1, 2.0 };", out)

    # -- C2: fmt must contain a replacement field and actually format -------
    def test_fmt_without_replacement_field_rejected(self):
        """Verified bug: 'fmt': '75.0' on stoppingTarget.radii rendered 49
        identical 75.0 values -- knobs inert, no error at load or render
        (Critical finding #2)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "75.0",
                   "segments": [{"count": 3, "expr": "a"}]}])
        msg = str(cm.exception)
        self.assertIn("75.0", msg)
        self.assertIn("replacement field", msg)

    def test_malformed_fmt_rejected_at_load_not_render(self):
        """A fmt whose spec doesn't apply to floats (e.g. '{:.4q}') must fail
        at from_dict, not the first time render() runs (Critical finding #2)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.4q}",
                   "segments": [{"count": 3, "expr": "a"}]}])
        msg = str(cm.exception)
        self.assertIn("{:.4q}", msg)

    def test_fmt_missing_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>",
                   "segments": [{"count": 3, "expr": "a"}]}])
        self.assertIn("fmt", str(cm.exception))

    # -- C3: clip lo must be <= hi -------------------------------------------
    def test_profile_clip_lo_greater_than_hi_rejected(self):
        """Verified bug: clip=[250.0, 50.0] pins every element to 50.00,
        byte-identical for every optimizer point -- knobs inert, no error
        (Critical finding #3)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([], profiles={"p": {"count": 3, "control": ["a", "b", "a"],
                                     "clip": [250.0, 50.0]}})
        msg = str(cm.exception)
        self.assertIn("250.0", msg)
        self.assertIn("50.0", msg)

    def test_profile_clip_lo_equal_hi_is_allowed(self):
        """lo == hi is a legitimate (if degenerate) pinned profile, not an
        ordering error -- only lo > hi is rejected."""
        _tpl([], profiles={"p": {"count": 3, "control": ["a", "b", "a"],
                                 "clip": [100.0, 100.0]}})

    # -- I5: geom's own nested schema rejects unknown top-level keys --------
    def test_unknown_geom_top_level_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            GeomTemplate.from_dict(
                {"base": "Offline/base.txt", "lines": [], "typo_key": 1},
                KNOBS, "t.json")
        msg = str(cm.exception)
        self.assertIn("typo_key", msg)

    # -- Minor: segments/per_index must declare a vector type ----------------
    def test_scalar_type_with_segments_rejected(self):
        """Verified bug: a scalar type with 'segments' currently renders
        'double k = { 7.00, 7.00 };' (Minor finding)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "double", "fmt": "{:.2f}",
                   "segments": [{"count": 2, "expr": "a"}]}])
        msg = str(cm.exception)
        self.assertIn("segments", msg)
        self.assertIn("double", msg)

    def test_scalar_type_with_per_index_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "double", "fmt": "{:.2f}",
                   "per_index": {"count": 2, "expr": "a + i"}}])
        msg = str(cm.exception)
        self.assertIn("per_index", msg)

    # -- I8: the renderer's clip wiring is exercised, not just accepted -----
    def test_profile_clip_reaches_the_rendered_text(self):
        """Renderer-level check that clip is actually applied by render(),
        not merely accepted at from_dict (Important finding #8):
        TestProfile.test_clip_bounds_the_overshoot calls lagrange_profile
        directly and never touches GeomTemplate.render(). Control points
        (50, 250, 250) genuinely overshoot to ~275 near index 36 without
        clipping -- see lagrange_profile's docstring and
        test_overshoot_is_real_without_clip below."""
        self.assertGreater(
            max(lagrange_profile((50.0, 250.0, 250.0), 49, None)), 250.0,
            "premise check: this control triple must overshoot unclipped")
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.4f}",
              "per_index": {"count": 49, "expr": "p[i]"}}],
            profiles={"p": {"count": 49, "control": ["a", "b", "b"],
                            "clip": [50.0, 250.0]}},
        ).render([50.0, 250.0])
        body = out.split("k.v = { ", 1)[1].split(" };", 1)[0]
        vals = [float(v) for v in body.split(", ")]
        self.assertEqual(len(vals), 49)
        self.assertLessEqual(max(vals), 250.0)
        self.assertGreaterEqual(min(vals), 50.0)

    # -- X2: line/profile/segment dicts reject unknown keys and mutually
    # exclusive combinations (final review) ----------------------------------
    def test_value_with_expr_is_rejected_not_silently_ignored(self):
        """Verified bug: {"value": 5.0, "expr": "a*2"} rendered the constant
        and silently dropped the expr (X2 in the final review)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.x", "type": "double", "value": 5.0, "expr": "a * 2"}])
        msg = str(cm.exception)
        self.assertIn("value", msg)
        self.assertIn("expr", msg)

    def test_value_with_segments_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "value": 5.0,
                   "segments": [{"count": 2, "expr": "a"}]}])
        msg = str(cm.exception)
        self.assertIn("value", msg)
        self.assertIn("segments", msg)

    def test_unknown_line_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.x", "type": "double", "value": 5.0, "typo_key": 1}])
        msg = str(cm.exception)
        self.assertIn("typo_key", msg)

    def test_unknown_comment_line_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"comment": "hi", "key": "k.x"}])
        msg = str(cm.exception)
        self.assertIn("key", msg)

    def test_unknown_profile_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([], profiles={"p": {"count": 3, "control": ["a", "b", "a"],
                                     "clip": [0.0, 100.0], "typo_key": 1}})
        msg = str(cm.exception)
        self.assertIn("typo_key", msg)

    def test_unknown_segment_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "segments": [{"count": 2, "expr": "a", "typo_key": 1}]}])
        msg = str(cm.exception)
        self.assertIn("typo_key", msg)

    # -- F2: `i` and `n` are reserved (the per_index loop scope) -----------
    def test_knob_named_i_rejected(self):
        """Verified bug: `_render_line` writes i (loop index) and n (count)
        into the per_index scope AFTER the env, so a knob/const/derived/
        profile of either name is silently shadowed there -- knob i=99
        rendered { 0.0, 1.0, 2.0 } (the loop index), const n=6 rendered
        { 3.0, 3.0, 3.0 } (the count). Loads clean, renders clean, wrong
        geometry (F2)."""
        with self.assertRaises(ValueError) as cm:
            GeomTemplate.from_dict(
                {"base": "Offline/base.txt", "lines": []}, ("i", "b"), "t.json")
        msg = str(cm.exception)
        self.assertIn("'i'", msg)
        self.assertIn("t.json", msg)

    def test_const_named_n_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([], consts={"n": 6})
        msg = str(cm.exception)
        self.assertIn("'n'", msg)
        self.assertIn("t.json", msg)

    def test_derived_named_i_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([], derived={"i": "a * 2"})
        self.assertIn("'i'", str(cm.exception))

    def test_profile_named_n_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([], profiles={"n": {"count": 3, "control": ["a", "b", "a"],
                                     "clip": [0.0, 100.0]}})
        self.assertIn("'n'", str(cm.exception))

    # -- F3(b): the same geometry key may not be emitted twice --------------
    def test_duplicate_line_key_rejected(self):
        """Verified against the Offline this project runs: GeometryService.hh
        defaults allowReplacement=true / messageOnReplacement=false and
        SimpleConfig.cc replaces with no message, so G4 silently takes the
        LAST of two identical keys. Editing the first of a duplicated pair
        leaves the stale one winning -- the silent-wrong-geometry class that
        tainted 62 foilsg rows (F3)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "stoppingTarget.holeRadius", "type": "double",
                   "raw": "1.0e6"},
                  {"key": "stoppingTarget.holeRadius", "type": "double",
                   "value": 21.5}])
        msg = str(cm.exception)
        self.assertIn("stoppingTarget.holeRadius", msg)
        self.assertIn("lines[1]", msg)
        self.assertIn("lines[0]", msg)

    def test_duplicate_comment_lines_are_fine(self):
        """Comments have no key; repeating one is not a redefinition."""
        out = _tpl([{"comment": "note"}, {"comment": "note"}]).render([1.0, 2.0])
        self.assertEqual(out.count("// note"), 2)

    # -- F9: subscripting is only legal on a declared profile ---------------
    def test_subscripting_a_scalar_rejected_at_load(self):
        """`expr: "a[b]"` used to load fine and die at RENDER with a bare
        `TypeError: 'float' object is not subscriptable` -- no file, no key
        (F9). Spec section 8 allows subscripting declared profiles only."""
        with self.assertRaises(ExprError) as cm:
            _tpl([{"key": "k.x", "type": "double", "fmt": "{:.1f}",
                   "expr": "a[b]"}])
        msg = str(cm.exception)
        self.assertIn("a", msg)
        self.assertIn("t.json", msg)

    def test_subscripting_a_scalar_in_per_index_rejected(self):
        with self.assertRaises(ExprError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "per_index": {"count": 3, "expr": "a[i]"}}])
        self.assertIn("t.json", str(cm.exception))

    def test_subscripting_a_declared_profile_still_works(self):
        out = _tpl(
            [{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
              "per_index": {"count": 3, "expr": "p[i]"}}],
            profiles={"p": {"count": 3, "control": ["a", "b", "a"],
                            "clip": [0.0, 100.0]}},
        ).render([10.0, 20.0])
        self.assertIn("vector<double> k.v = { 10.0, 20.0, 10.0 };", out)

    # -- F10: a newline in a comment injects a live assignment --------------
    def test_newline_in_comment_rejected(self):
        """Verified bug: `_render_line` prefixes only the FIRST line with
        '// ', so a comment carrying a newline renders a real geometry
        assignment on the following line (F10)."""
        with self.assertRaises(ValueError) as cm:
            _tpl([{"comment":
                   "harmless note\ndouble stoppingTarget.holeRadius = 21.5;"}])
        msg = str(cm.exception)
        self.assertIn("newline", msg)
        self.assertIn("t.json", msg)

    def test_newline_in_raw_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.hole", "type": "double",
                   "raw": "1.0e6;\ndouble other = 3.0"}])
        self.assertIn("newline", str(cm.exception))

    def test_segment_expr_with_value_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _tpl([{"key": "k.v", "type": "vector<double>", "fmt": "{:.1f}",
                   "segments": [{"count": 2, "expr": "a", "value": 3.0}]}])
        msg = str(cm.exception)
        self.assertIn("expr", msg)
        self.assertIn("value", msg)


if __name__ == "__main__":
    unittest.main()
