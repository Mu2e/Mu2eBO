"""Leaderboard module: schema-owning history/pending I/O (spec 2026-08-08).

Regression anchors: touched-leaderboard-headerless-history-loss (foilspfbw01),
the remove_pending header-fusion bug (foilsflash24R00_00), stale pending rows.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from leaderboard import (  # noqa: E402
    Leaderboard, Point, SchemaMismatch, RowParseError)


def make_lb(tmp: Path) -> Leaderboard:
    return Leaderboard(
        path=tmp / "leaderboard_bo_test.tsv", name="test",
        knob_names=("k0", "k1"), knob_fmts=("{:.2f}", "{:.2f}"),
        metric_cols=("sob", "flash_edep", "alpha", "obj"))


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = make_lb(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def test_header_line(self):
        self.assertEqual(self.lb.header(),
                         "config\tk0\tk1\tsob\tflash_edep\talpha\tobj\n")

    def test_missing_file_loads_empty(self):
        self.assertEqual(self.lb.load(), [])

    def test_append_load_roundtrip(self):
        p = Point(cfg="t01", x=[1.5, 2.5], sob=3.14159, calo=6.85e-7)
        self.lb.append(p, alpha=1.0e5)
        first = self.lb.path.read_text().splitlines()[0] + "\n"
        self.assertEqual(first, self.lb.header())
        [got] = self.lb.load()
        self.assertEqual(got.cfg, "t01")
        self.assertEqual(got.x, [1.5, 2.5])
        self.assertAlmostEqual(got.sob, 3.14159, places=5)
        self.assertAlmostEqual(got.calo, 6.85e-7, places=12)

    def test_touched_file_is_loud_not_empty(self):
        # touched-leaderboard-headerless-history-loss: a 0-byte existing file
        # must raise, never return [] while rows could exist.
        self.lb.path.touch()
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_fused_header_is_loud(self):
        # the remove_pending fusion shape: header and row 1 on one line.
        self.lb.path.write_text(
            "config\tk0\tk1\tsob\tflash_edep\talpha\tobj"
            "t01\t1.00\t2.00\t3.00000\t1.00000e-07\t1.000\t3.00000\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_malformed_row_is_loud_with_line_number(self):
        self.lb.append(Point("t01", [1.0, 2.0], 3.0, 1e-7), alpha=1.0)
        with self.lb.path.open("a") as f:
            f.write("t02\tnot_a_number\t2.00\t3.00000\t1.0e-07\t1.000\t3.00000\n")
        with self.assertRaises(RowParseError) as cm:
            self.lb.load()
        self.assertEqual(cm.exception.line_no, 3)

    def test_append_on_mismatch_quarantines_then_raises(self):
        self.lb.path.write_text("config\twrong\theader\n")
        p = Point(cfg="t01", x=[1.0, 2.0], sob=3.0, calo=1e-7)
        with self.assertRaises(SchemaMismatch):
            self.lb.append(p, alpha=1.0)
        q = self.lb.quarantine_path()
        self.assertTrue(q.exists())
        lines = q.read_text().splitlines()
        self.assertEqual(lines[0] + "\n", self.lb.header())
        self.assertTrue(lines[1].startswith("t01\t"))
        # main file untouched
        self.assertEqual(self.lb.path.read_text(), "config\twrong\theader\n")

    def test_bad_spec_fails_at_construction(self):
        with self.assertRaises(ValueError):
            Leaderboard(path=self.tmp / "x.tsv", name="x",
                        knob_names=("a",), knob_fmts=("{:.2f}",),
                        metric_cols=("sob", "calo"))  # not 4 columns


if __name__ == "__main__":
    unittest.main()
