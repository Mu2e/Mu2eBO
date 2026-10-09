import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
from tests.engine_fixtures import (EngineCase, board_rows,  # noqa: E402
                                   toy_doc, write_study)


def zero_doc(name="zk"):
    doc = toy_doc(name=name, layout="v2")
    doc["knobs"] = []
    doc["evaluate"][0]["params"] = {}
    doc["evaluate"][0]["fixed"].update(x1=1.0, x2=2.0)
    return doc


class _Tmp(EngineCase):
    def run_module(self, *args):
        return subprocess.run([sys.executable, "-m", *args], cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=120)


class TestLoader(_Tmp):
    def test_no_knobs_loads(self):
        s = st.load_study_file(write_study(zero_doc(), self.studies))
        self.assertEqual(s.knobs, ())


class TestRunners(_Tmp):
    def test_a_zero_knob_point_lands_a_row_without_knob_columns(self):
        write_study(zero_doc(), self.studies)
        r = self.run_module("graph.run", "--study", "zk", "--config",
                            "z1", "--campaign", "t")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = board_rows(self.data, "zk")
        self.assertEqual(list(row)[:3], ["config", "branin", "currin"])
        self.assertEqual(row["config"], "z1")

    def test_x_is_refused_without_knobs_and_required_with_them(self):
        write_study(zero_doc(), self.studies)
        write_study(toy_doc(name="kn", layout="v2"), self.studies)
        r = self.run_module("graph.run", "--study", "zk", "--config",
                            "z1", "--campaign", "t", "--x=1,2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no knobs", r.stdout)
        r = self.run_module("graph.run", "--study", "kn", "--config",
                            "k1", "--campaign", "t")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--x", r.stdout)

    def test_the_loop_refuses_a_zero_knob_study(self):
        write_study(zero_doc(), self.studies)
        r = self.run_module("graph.closed_loop", "--study", "zk", "--q", "1",
                            "--max-evals", "1", "--name-prefix", "zk")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no knobs", r.stdout)


class TestSurrogate(_Tmp):
    def test_build_problem_refuses_and_problems_skip(self):
        s = st.load_study_file(write_study(zero_doc(), self.studies))
        import botorch_predict as bp
        with mock.patch.dict(bp._modes.STUDIES, {"zk": s}):
            with self.assertRaises(ValueError) as cm:
                bp.build_problem("zk")
            self.assertIn("no knobs", str(cm.exception))
            from surrogate import adapter
            self.assertNotIn("zk", adapter.AutoresearchAdapter().problems())


if __name__ == "__main__":
    unittest.main()
