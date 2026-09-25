import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import boards  # noqa: E402
import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402
import modes  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Point  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

META = {"handles": "toy=h1.toy", "spec_sha": "s" * 64,
        "measure_sha": "m" * 64, "time": "2026-09-24T00:00:00Z"}


class TestBoardFor(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(
            write_study(toy_doc(name="histtoy", layout="v2"),
                        self.tmp / "studies"))
        for patch in (
                mock.patch.object(boards, "leaderboard_live",
                                  lambda rel: self.tmp / "live" / Path(rel).name),
                mock.patch.object(boards, "leaderboard_archive",
                                  lambda rel: self.tmp / "arch" / Path(rel).name),
                mock.patch.dict(modes.STUDIES, {"histtoy": self.study})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_board_paths_come_from_the_study(self):
        board = boards.board_for(self.study)
        self.assertEqual(board.path, self.tmp / "live" / "leaderboard_histtoy.tsv")
        self.assertEqual(board.archive_path,
                         self.tmp / "arch" / "leaderboard_histtoy.tsv")
        self.assertEqual(board.layout, "v2")

    def test_an_engine_study_trains_on_its_board(self):
        boards.board_for(self.study).append(
            Point("h1", [1.0, 2.0], {"branin": 5.0, "currin": 3.0}), {}, META)
        X, Y, _, _ = bp.load_history_tensor("histtoy")
        self.assertEqual(X.tolist(), [[1.0, 2.0]])
        self.assertAlmostEqual(Y.tolist()[0][0], -5.0)
        self.assertAlmostEqual(Y.tolist()[0][1], -math.log10(3.0))

    def test_a_pipeline_study_still_reads_through_its_mode(self):
        with mock.patch.object(bo.MODES["foilspf"], "load_history",
                               return_value=[]) as m:
            self.assertEqual(bp.history_points("foilspf"), [])
        m.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
