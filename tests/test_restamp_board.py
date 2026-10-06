"""graph/restamp_board.py: re-stamp an old board once, after proving only
kit builds differ (spec
docs/superpowers/specs/2026-10-05-measure-identity-design.md)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
import measure  # noqa: E402
import modes  # noqa: E402
import restamp_board as rb  # noqa: E402
from leaderboard import Leaderboard, Point  # noqa: E402
from point_dir import PointDir  # noqa: E402

STUDY = modes.STUDIES["foilspfbpz_ax"]
OLD = {"anakit": "anakit-adapter/1+anakit-60cb434419a2",
       "prodtools": "prodtools-adapter/1"}
CUR = {"anakit": "anakit-adapter/1", "prodtools": "prodtools-adapter/1"}
BUILDS = {"anakit": "1f831a1aaaaa", "prodtools": None}
STEPS = [s.step for s in STUDY.steps]
KIT_OF = {s.step: s.kit for s in STUDY.steps}


class _Board(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.grid = self.tmp / "grid"
        self.lines = []
        self.git_calls = []

    def make_board(self, archive=None):
        return Leaderboard.for_study(STUDY, path=self.tmp / "b.tsv",
                                     archive_path=archive or
                                     self.tmp / "none.tsv")

    def add_row(self, board, cfg, versions=OLD, sha=None, records=True,
                handles=None):
        sha = sha or STUDY.measure_sha(versions)
        y = {o.name: 1.0 for o in STUDY.objectives}
        y.update({m.name: 1.0 for m in STUDY.extra_metrics})
        meta = {"handles": handles or ",".join(
                    f"{s}={cfg}.{s}" for s in sorted(STEPS)),
                "spec_sha": STUDY.spec_sha, "measure_sha": sha,
                "time": "2026-09-30T00:00:00Z"}
        # Written raw, not through append: some boards here mix shas.
        line = board.format_line(Point(cfg, list(STUDY.bounds_lo), y),
                                 {c: 1e5 for c in STUDY.context}, meta)
        if not board.path.exists():
            board.path.write_text(board.header())
        with board.path.open("a") as fh:
            fh.write(line)
        if records:
            pd = PointDir.of(self.grid, cfg)
            pd.state.mkdir(parents=True, exist_ok=True)
            for s in STEPS:
                pd.write_results(s, {
                    "step": s, "kit": KIT_OF[s], "kit_version": versions[KIT_OF[s]],
                    "handle": f"{cfg}.{s}", "metrics": {}, "files": [],
                    "metadata": {}, "params": {}, "inputs": []})

    def git_log(self, old, new):
        self.git_calls.append((old, new))
        return "e232d43 refactor ce_sensitivity\n1f831a1 nts_momentum"

    def run_it(self, board, confirm=False, current=CUR, anakit_log=None):
        return rb.restamp(STUDY, board, self.grid, current, BUILDS,
                          why="the fork moved; no analysis changed",
                          confirm=confirm, user="tester", now=1.8e9,
                          log=self.lines.append,
                          anakit_log=anakit_log or self.git_log)

    @property
    def text(self):
        return "\n".join(self.lines)

    def assertUnchanged(self, board, before):
        self.assertEqual(board.path.read_bytes(), before)
        self.assertEqual(list(self.tmp.glob("b.tsv.pre-restamp-*")), [])
        self.assertFalse((self.tmp / "b.tsv.restamp.jsonl").exists())


class TestProven(_Board):
    def test_dry_run_plans_and_writes_nothing(self):
        board = self.make_board()
        self.add_row(board, "c0")
        self.add_row(board, "c1")
        before = board.path.read_bytes()
        self.assertEqual(self.run_it(board), 0, self.text)
        old, new = STUDY.measure_sha(OLD), STUDY.measure_sha(CUR)
        for needle in (old[:12], new[:12], "2 rows", OLD["anakit"],
                       "anakit-adapter/1", "60cb434419a2", "1f831a1aaaaa",
                       "nts_momentum", "dry run"):
            self.assertIn(needle, self.text)
        self.assertEqual(self.git_calls, [("60cb434419a2", "1f831a1aaaaa")])
        self.assertUnchanged(board, before)

    def test_confirm_rewrites_backs_up_and_logs(self):
        board = self.make_board()
        self.add_row(board, "c0")
        self.add_row(board, "c1")
        self.assertEqual(self.run_it(board, confirm=True), 0, self.text)
        new = STUDY.measure_sha(CUR)
        self.assertEqual(board.measure_shas(), {new})
        self.assertEqual(len(list(self.tmp.glob("b.tsv.pre-restamp-*.tsv"))),
                         1)
        lines = (self.tmp / "b.tsv.restamp.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual((entry["from"], entry["to"], entry["rows"],
                          entry["by"], entry["study"]),
                         (STUDY.measure_sha(OLD), new, 2, "tester",
                          "foilspfbpz_ax"))
        self.assertIn("no analysis changed", entry["why"])
        self.assertTrue(Path(entry["backup"]).exists())
        self.assertEqual(entry["from_builds"]["anakit"], "60cb434419a2")
        self.assertEqual(measure.board_problems(STUDY, board, CUR), [])

    def test_git_log_failure_is_reported(self):
        board = self.make_board()
        self.add_row(board, "c0")

        def broken(old, new):
            raise RuntimeError("no checkout")
        self.assertEqual(self.run_it(board, anakit_log=broken), 0, self.text)
        self.assertIn("git log failed: no checkout", self.text)

    def test_nothing_to_do(self):
        board = self.make_board()
        self.assertEqual(self.run_it(board), 0)
        self.assertIn("nothing to do", self.text)
        self.lines.clear()
        self.add_row(board, "c0", versions=CUR)
        self.assertEqual(self.run_it(board, confirm=True), 0)
        self.assertIn("nothing to do", self.text)
        self.assertFalse((self.tmp / "b.tsv.restamp.jsonl").exists())


class TestRefused(_Board):
    def refused(self, board, needle, current=CUR):
        before = board.path.read_bytes()
        self.assertEqual(self.run_it(board, confirm=True, current=current), 2,
                         self.text)
        self.assertIn(needle, self.text)
        self.assertUnchanged(board, before)

    def test_the_basis_changed(self):
        board = self.make_board()
        # Measured as some other study measured it: its records do not
        # reproduce the row's sha.
        self.add_row(board, "c0", sha="e" * 64)
        self.refused(board, "measurement changed")

    def test_a_hand_bump(self):
        board = self.make_board()
        self.add_row(board, "c0")
        self.refused(board, "hand", current=dict(CUR, anakit="anakit-adapter/2"))

    def test_a_row_without_records(self):
        board = self.make_board()
        self.add_row(board, "c0")
        self.add_row(board, "c1", records=False)
        self.refused(board, "c1")

    def test_mismatched_handles(self):
        board = self.make_board()
        self.add_row(board, "c0", handles="sob=other.sob")
        self.refused(board, "handles")

    def test_archive_rows(self):
        archive = Leaderboard.for_study(STUDY, path=self.tmp / "arch.tsv",
                                        archive_path=self.tmp / "none.tsv")
        self.add_row(archive, "a0")
        board = self.make_board(archive=archive.path)
        self.add_row(board, "c0")
        self.refused(board, "archive")

    def test_one_bad_sha_among_two_writes_nothing(self):
        board = self.make_board()
        self.add_row(board, "c0")
        self.add_row(board, "c1", versions=dict(OLD, prodtools="prodtools-adapter/0"))
        self.refused(board, "hand")


if __name__ == "__main__":
    unittest.main()
