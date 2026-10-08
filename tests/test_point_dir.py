"""core/point_dir.py: one owner for a point's state folder (spec
docs/superpowers/specs/2026-10-05-point-campaign-records-design.md)."""
import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import point_dir as pdm  # noqa: E402
from point_dir import PointDir, PointMismatch  # noqa: E402
from tests.engine_fixtures import TmpCase  # noqa: E402

POINT = {"study": "s", "config": "p1", "campaign": "c", "x": [1.0, 2.0],
         "context": {}, "measure_basis_sha": "a" * 64, "executor": "grid"}


class _Dir(TmpCase):
    def setUp(self):
        super().setUp()
        self.pd = PointDir.of(self.tmp, "p1")

    def put(self, name, payload):
        self.pd.state.mkdir(parents=True, exist_ok=True)
        path = self.pd.path(name)
        path.write_text(payload if isinstance(payload, str)
                        else json.dumps(payload))
        return path


class TestPoint(_Dir):
    def test_of_builds_the_state_path(self):
        self.assertEqual(self.pd.state, self.tmp / "p1" / "state")
        self.assertEqual(PointDir(self.pd.state).state, self.pd.state)

    def test_claim_writes_then_matches(self):
        self.pd.claim(POINT)
        self.assertEqual(self.pd.point(), POINT)
        self.pd.claim(dict(POINT))          # the same point: no error

    def test_claim_refusals(self):
        cases = [
            ({k: v for k, v in POINT.items() if k != "measure_basis_sha"},
             ("no measure_basis_sha",)),
            (dict(POINT, measure_basis_sha="b" * 64),
             ("measurement changed", "aaaaaaaaaaaa")),
            ({k: v for k, v in POINT.items() if k != "executor"},
             ("has no executor",)),
            (dict(POINT, executor="local"), ("--executor local",)),
            (dict(POINT, x=[3.0, 4.0]), ("records a different point",)),
        ]
        for old, fragments in cases:
            with self.subTest(fragments=fragments):
                self.put(pdm.POINT, old)
                with self.assertRaises(PointMismatch) as cm:
                    self.pd.claim(POINT)
                for f in fragments:
                    self.assertIn(f, str(cm.exception))
                self.assertIn("point.json", str(cm.exception))

    def test_a_bad_point_json_raises(self):
        self.put(pdm.POINT, "{")
        with self.assertRaises(ValueError):
            self.pd.point()
        self.put(pdm.POINT, "[1, 2]")
        with self.assertRaises(ValueError) as cm:
            self.pd.point()
        self.assertIn("not a JSON object", str(cm.exception))
        self.assertIsNone(PointDir.of(self.tmp, "none").point())


class TestBroken(_Dir):
    def test_mark_broken_first_writer_wins(self):
        self.assertTrue(self.pd.mark_broken("KitError: boom", step="b"))
        self.assertFalse(self.pd.mark_broken("score: later"))
        self.assertEqual(self.pd.path(pdm.BROKEN).read_text(),
                         "step b: KitError: boom\n")

    def test_broken_forms(self):
        self.assertIsNone(self.pd.broken())
        for text, step, reason in (
                ("step b: KitError: boom\n", "b", "KitError: boom"),
                ("preflight: fail_managed\n", None, "preflight: fail_managed"),
                ("broken\n", None, "broken")):
            with self.subTest(text=text):
                self.put(pdm.BROKEN, text)
                got = self.pd.broken()
                self.assertEqual((got.step, got.reason, got.text),
                                 (step, reason, text.strip()))


class TestSteps(_Dir):
    def setUp(self):
        super().setUp()
        self.pd.state.mkdir(parents=True)     # writers expect the folder
    def test_handles_results_adopted(self):
        self.assertIsNone(self.pd.handle("a"))
        self.pd.write_handle("a", "p1.a")
        self.assertEqual(self.pd.handle("a"), "p1.a")
        self.assertEqual(self.pd.path("a_cluster.txt").read_text(), "p1.a\n")
        self.pd.write_results("a", {"step": "a", "metrics": {"m": 1.0}})
        self.assertEqual(self.pd.results("a")["metrics"], {"m": 1.0})
        self.assertEqual(self.pd.adopted(["a", "b"]),
                         {"a": {"step": "a", "metrics": {"m": 1.0}}})

    def test_status(self):
        self.assertEqual(self.pd.status("a"), (None, None))
        self.pd.write_status("a", {"state": "working"})
        self.assertEqual(self.pd.status("a"), ({"state": "working"}, None))
        self.put("a_status.json", "{")
        rec, err = self.pd.status("a")
        self.assertIsNone(rec)
        self.assertIn("a_status.json", err)


class TestStepState(_Dir):
    def setUp(self):
        super().setUp()
        self.pd.state.mkdir(parents=True)
    def status(self, step, state="working", t=None, poll_s=120.0, **kw):
        self.pd.write_status(step, dict({"state": state, "message":
                                         f"{step} {state}", "progress": None,
                                         "time": t or time.time(),
                                         "poll_s": poll_s}, **kw))

    def test_states(self):
        self.pd.write_results("done", {})
        self.status("bad", state="failed")
        self.status("brk")
        self.pd.mark_broken("KitError: boom", step="brk")
        self.pd.write_handle("hnd", "p1.hnd")
        self.status("wrk", progress={"done": 1, "total": 2, "ok": 1})
        got = {s: self.pd.step_state(s)["state"]
               for s in ("done", "bad", "brk", "hnd", "wrk", "none")}
        self.assertEqual(got, {"done": "done", "bad": "failed",
                               "brk": "failed", "hnd": "working",
                               "wrk": "working", "none": "waiting"})
        self.assertEqual(self.pd.step_state("brk")["message"],
                         "KitError: boom")
        wrk = self.pd.step_state("wrk")
        self.assertEqual(wrk["progress"], {"done": 1, "total": 2, "ok": 1})
        self.assertEqual(wrk["poll_s"], 120.0)
        self.assertIsNotNone(wrk["poll_time"])
        hnd = self.pd.step_state("hnd")
        self.assertAlmostEqual(hnd["handle_mtime"],
                               self.pd.path("hnd_cluster.txt").stat().st_mtime)

    def test_an_unreadable_status(self):
        self.pd.write_handle("b", "p1.b")
        self.put("b_status.json", "{")
        view = self.pd.step_state("b")
        self.assertEqual(view["state"], "working")
        self.assertIn("b_status.json", view["error"])

    def test_a_bad_poll_time(self):
        self.status("b", t="soon")
        view = self.pd.step_state("b")
        self.assertEqual(view["state"], "working")
        self.assertIn("bad status record", view["error"])
        self.assertIsNone(view["poll_time"])


class TestLiveness(_Dir):
    def test_a_point_that_never_started(self):
        self.assertFalse(self.pd.running())
        self.assertFalse(self.pd.ever_ran())
        self.assertFalse(self.pd.started())
        self.assertFalse((self.tmp / "p1").exists())

    def test_run_lock(self):
        with self.pd.run_lock():
            self.assertTrue(self.pd.running())
            self.assertTrue(self.pd.ever_ran())
        self.assertFalse(self.pd.running())
        self.assertTrue(self.pd.ever_ran())

    def test_started(self):
        self.pd.state.mkdir(parents=True)
        self.pd.write_handle("a", "p1.a")
        self.assertTrue(self.pd.started())
        other = PointDir.of(self.tmp, "p2")
        other.claim(dict(POINT, config="p2"))
        self.assertTrue(other.started())


if __name__ == "__main__":
    unittest.main()
