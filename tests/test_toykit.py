import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests import toykit  # noqa: E402

P = {"x1": 1.0, "x2": 2.0, "function": "branin_currin"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Store(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.store = toykit.ToyStore(self.root, clock=self.clock)

    def submits(self):
        path = self.root / "submits.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln)["name"] for ln in path.read_text().splitlines()]


class TestFunctions(unittest.TestCase):
    def test_branin_global_minimum(self):
        self.assertAlmostEqual(toykit.branin(math.pi, 2.275), 0.397887, places=5)

    def test_currin_at_the_centre(self):
        # u1 = u2 = 0.5: (1 - e^-1) * 1868.5 / 159.5
        self.assertAlmostEqual(toykit.currin(2.5, 7.5), 7.405, places=3)

    def test_currin_is_finite_and_positive_on_the_x2_zero_edge(self):
        v = toykit.currin(0.0, 0.0)
        self.assertTrue(math.isfinite(v) and v > 0)


class TestJobs(_Store):
    def test_job_completes_after_its_delay(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        self.assertEqual(self.store.status("c.toy")["state"], "working")
        self.clock.t += 5
        st = self.store.status("c.toy")
        self.assertEqual(st["state"], "completed")
        self.assertEqual(set(st), {"state", "message", "poll_ms", "progress"})

    def test_results(self):
        self.store.submit("c.toy", P, [], [{"name": "a", "uri": "file:///a",
                                            "kind": "text"}])
        res = self.store.results("c.toy")
        self.assertAlmostEqual(res["metrics"]["branin"], toykit.branin(1, 2))
        self.assertAlmostEqual(res["metrics"]["currin"], toykit.currin(1, 2))
        self.assertEqual(res["metrics"]["n_inputs"], 1.0)
        self.assertTrue(res["files"][0]["uri"].startswith("file://"))

    def test_same_submit_is_idempotent(self):
        _, created = self.store.submit("c.toy", P, [], [])
        _, again = self.store.submit("c.toy", P, [], [])
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(self.submits(), ["c.toy"])

    def test_same_name_different_params_is_refused(self):
        self.store.submit("c.toy", P, [], [])
        with self.assertRaises(ValueError) as cm:
            self.store.submit("c.toy", dict(P, x1=3.0), [], [])
        self.assertIn("different", str(cm.exception))

    def test_results_before_completion_is_refused(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        with self.assertRaises(ValueError):
            self.store.results("c.toy")

    def test_unknown_handle(self):
        with self.assertRaises(ValueError) as cm:
            self.store.status("nope")
        self.assertIn("no job 'nope'", str(cm.exception))

    def test_unknown_function_and_fail_are_refused(self):
        with self.assertRaises(ValueError):
            self.store.submit("a.t", dict(P, function="rosenbrock"), [], [])
        with self.assertRaises(ValueError):
            self.store.submit("b.t", dict(P, fail="sometimes"), [], [])

    def test_cancel(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        self.assertEqual(self.store.cancel("c.toy"), {"state": "cancelled"})
        self.assertEqual(self.store.status("c.toy")["state"], "cancelled")


class TestFailures(_Store):
    def test_status_failures(self):
        for fail, state in (("failed", "failed"), ("cancelled", "cancelled"),
                            ("bad_state", "bogus")):
            with self.subTest(fail=fail):
                self.store.submit(f"{fail}.t", dict(P, fail=fail), [], [])
                self.assertEqual(self.store.status(f"{fail}.t")["state"], state)

    def test_missing_metric(self):
        self.store.submit("m.t", dict(P, fail="missing_metric"), [], [])
        self.assertNotIn("currin", self.store.results("m.t")["metrics"])

    def test_nonpositive_metric(self):
        self.store.submit("n.t", dict(P, fail="nonpositive"), [], [])
        self.assertEqual(self.store.results("n.t")["metrics"]["currin"], 0.0)


class TestCheckAndDescribe(unittest.TestCase):
    def test_check(self):
        self.assertTrue(toykit.ToyStore.check("c.pre", P, [], [])["ok"])
        bad = toykit.ToyStore.check("c.pre", dict(P, function="reject"), [], [])
        self.assertFalse(bad["ok"])
        self.assertIn("reject", bad["message"])

    def test_describe(self):
        d = toykit.ToyStore.describe()
        self.assertEqual(d, {"params": list(toykit.PARAMS),
                             "metrics": list(toykit.METRICS),
                             "accepts_lists": False})


if __name__ == "__main__":
    unittest.main()
