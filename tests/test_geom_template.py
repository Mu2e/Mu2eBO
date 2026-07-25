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
