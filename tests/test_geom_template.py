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

    def test_exponentiation_rejected(self):
        with self.assertRaises(ExprError):
            compile_expr("a ** 2", {"a"}, "w")


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


if __name__ == "__main__":
    unittest.main()
