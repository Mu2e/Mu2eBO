import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import leaderboard as lbm  # noqa: E402
import score as sc  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

GOOD = {"branin": 1.5, "currin": 3.0, "n_inputs": 0.0}


def rec(metrics, step="toy", handle="c.toy", version="1"):
    return {"step": step, "kit": "toykit", "kit_version": version,
            "handle": handle, "params": {}, "inputs": [], "metrics": metrics,
            "files": [], "metadata": {}}


class _Score(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.state = self.tmp / "state"
        self.state.mkdir()

    def study(self, mutate=lambda d: None, layout="v2", name="scoretoy"):
        doc = toy_doc(name=name, layout=layout)
        mutate(doc)
        return st.load_study_file(write_study(doc, self.tmp / "studies"))

    def board(self, study):
        return Leaderboard.for_study(study, path=self.tmp / f"{study.name}.tsv",
                                     archive_path=None)

    def score(self, study, records, board=None, config="c"):
        return sc.score(study, config=config, x=[1.0, 2.0], records=records,
                        context={}, board=board or self.board(study),
                        state_dir=self.state, now=0)


class TestRows(_Score):
    def test_a_row_and_the_summary_files(self):
        study = self.study()
        board = self.board(study)
        res = self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(res, {"config": "c", "primary": 1.5,
                               "objectives": {"branin": 1.5, "currin": 3.0},
                               "row_appended": True})
        self.assertEqual(json.loads((self.state / "evaluate_result.json")
                                    .read_text()), res)
        summary = json.loads((self.state / "summary.json").read_text())
        self.assertEqual((summary["x"], summary["steps"]),
                         ([1.0, 2.0], {"toy": GOOD}))
        row = board.path.read_text().splitlines()[1].split("\t")
        self.assertEqual(row[-4:], ["toy=c.toy", study.spec_sha,
                                    study.measure_sha({"toykit": "1"}),
                                    "1970-01-01T00:00:00Z"])

    def test_scoring_again_lands_no_second_row(self):
        study = self.study()
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertFalse(self.score(study, {"toy": rec(GOOD)}, board)
                         ["row_appended"])
        self.assertEqual(len(board.path.read_text().splitlines()), 2)

    def test_extra_metrics_are_recorded(self):
        study = self.study(lambda d: d["extra_metrics"].append(
            {"name": "n_in", "metric": "toy.n_inputs", "fmt": "{:.0f}"}))
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(board.load()[0].y["n_in"], 0.0)

    def test_a_v1_study_writes_a_v1_row(self):
        study = self.study(layout="v1", name="scorev1")
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(len(board.path.read_text().splitlines()[1]
                             .split("\t")), 5)


class TestFailedEvaluations(_Score):
    def assertFails(self, records, *needles, study=None):
        study = study or self.study()
        board = self.board(study)
        with self.assertRaises(sc.ScoreError) as cm:
            self.score(study, records, board)
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertIn("score:", (self.state / "broken.txt").read_text())
        self.assertFalse(board.path.exists())

    def test_a_missing_metric(self):
        self.assertFails({"toy": rec({"branin": 1.5})}, "currin", "missing")

    def test_a_step_with_no_results(self):
        self.assertFails({}, "toy", "no results")

    def test_not_a_finite_number(self):
        self.assertFails({"toy": rec(dict(GOOD, branin=math.nan))},
                         "branin", "finite")

    def test_nonpositive_under_log10(self):
        self.assertFails({"toy": rec(dict(GOOD, currin=0.0))}, "currin",
                         "log10")

    def test_one_kit_on_two_versions(self):
        def two_steps(d):
            d["evaluate"].append({"step": "toy2", "kit": "toykit",
                                  "entry": None, "files": [],
                                  "files_from": [],
                                  "params": {"x1": "x1", "x2": "x2"},
                                  "fixed": {}})
            d["extra_metrics"].append({"name": "b2", "metric": "toy2.branin",
                                       "fmt": "{:.3f}"})
        self.assertFails({"toy": rec(GOOD),
                          "toy2": rec(GOOD, step="toy2", handle="c.toy2",
                                      version="2")},
                         "version", study=self.study(two_steps))


class TestBoardRefusals(_Score):
    def test_a_board_measured_another_way_refuses_the_row(self):
        study = self.study()
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board, config="c1")
        with self.assertRaises(lbm.MeasureMismatch):
            self.score(study, {"toy": rec(GOOD, handle="c2.toy", version="2")},
                       board, config="c2")
        self.assertEqual(len(board.path.read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
