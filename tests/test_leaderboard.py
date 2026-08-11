"""Leaderboard module: schema-owning history/pending I/O (spec 2026-08-08).

Regression anchors: touched-leaderboard-headerless-history-loss (foilspfbw01),
the remove_pending header-fusion bug (foilsflash24R00_00), stale pending rows.
"""
import io
import sys
import tempfile
import time
import unittest
import unittest.mock
from contextlib import redirect_stderr
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


class TestPending(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = make_lb(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def test_add_load_remove_roundtrip(self):
        self.lb.pending_add("t01", [1.5, 2.5], alpha=1.0e5)
        self.lb.pending_add("t02", [3.0, 4.0], alpha=1.0e5)
        self.assertEqual(self.lb.pending_load(),
                         [("t01", [1.5, 2.5]), ("t02", [3.0, 4.0])])
        self.assertTrue(self.lb.pending_remove("t01"))
        self.assertFalse(self.lb.pending_remove("t01"))
        self.assertEqual(self.lb.pending_load(), [("t02", [3.0, 4.0])])

    def test_last_row_removal_keeps_header_newline(self):
        # regression: the fusion bug's ROOT CAUSE — header must stay
        # newline-terminated when the last pending row is removed.
        self.lb.pending_add("t01", [1.0, 2.0], alpha=1.0)
        self.assertTrue(self.lb.pending_remove("t01"))
        self.assertTrue(self.lb.pending_path().read_text().endswith("\n"))
        self.lb.pending_add("t02", [3.0, 4.0], alpha=1.0)
        self.assertEqual(self.lb.pending_load(), [("t02", [3.0, 4.0])])

    def test_stale_rows_warn_but_are_returned(self):
        self.lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
        now = time.time() + 49 * 3600
        buf = io.StringIO()
        with redirect_stderr(buf):
            rows = self.lb.pending_load(now=now)
        self.assertEqual(rows, [("old01", [1.0, 2.0])])
        self.assertIn("old01", buf.getvalue())
        self.assertIn("pending-prune", buf.getvalue())

    def test_prune_removes_only_stale(self):
        self.lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
        self.lb.pending_add("new01", [3.0, 4.0], alpha=1.0)
        now = time.time() + 49 * 3600
        # Both rows share a real timestamp, so selectivity is exercised via
        # the threshold: at 50h neither qualifies, at 48h both do.
        self.assertEqual(self.lb.pending_prune(older_than_h=50.0, now=now), [])
        removed = self.lb.pending_prune(older_than_h=48.0, now=now)
        self.assertEqual(sorted(removed), ["new01", "old01"])
        self.assertEqual(self.lb.pending_load(), [])
        self.assertTrue(self.lb.pending_path().read_text().endswith("\n"))

    def test_pending_header_mismatch_is_loud(self):
        self.lb.pending_path().write_text("config\twrong\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.pending_load()
        with self.assertRaises(SchemaMismatch):
            self.lb.pending_add("t01", [1.0, 2.0], alpha=1.0)
        self.assertTrue(self.lb.pending_path()
                        .with_name(self.lb.pending_path().name
                                   + ".quarantine.tsv").exists())


class TestPendingPruneCmd(unittest.TestCase):
    def test_cmd_pending_prune_prints_and_prunes(self):
        import types
        import bo_driver as bo
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            lb = make_lb(tmp)
            lb.pending_add("old01", [1.0, 2.0], alpha=1.0)
            mode = next(iter(bo.MODES.values()))
            with unittest.mock.patch.object(
                    type(mode), "leaderboard_io", return_value=lb):
                args = types.SimpleNamespace(
                    mode=mode.name, older_than_hours=-1.0)  # everything stale
                rc = bo.cmd_pending_prune(args)
                self.assertEqual(rc, 0)
                self.assertEqual(lb.pending_load(), [])  # row actually pruned


class TestArchivePlusLive(unittest.TestCase):
    """The committed leaderboards/ are read-only priors; this operator's own
    rows append to a separate live file. load() returns both."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.archive = self.tmp / "archive.tsv"
        self.live = self.tmp / "live" / "board.tsv"

    def tearDown(self):
        self._td.cleanup()

    def _lb(self):
        return Leaderboard(path=self.live, name="m", archive_path=self.archive,
                           knob_names=("a",), knob_fmts=("{:.3f}",),
                           metric_cols=("sob", "calo", "alpha", "obj"))

    def test_load_returns_archive_rows_then_live_rows(self):
        lb = self._lb()
        self.archive.write_text(
            lb.header()
            + "old1\t1.000\t3.10000\t1.00000e-06\t0.000\t3.10000\n")
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["old1", "new1"])

    def test_append_creates_the_live_directory(self):
        lb = self._lb()
        self.assertFalse(self.live.parent.exists())
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertTrue(self.live.exists())

    def test_append_never_writes_to_the_archive(self):
        lb = self._lb()
        self.archive.write_text(lb.header())
        before = self.archive.read_text()
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertEqual(self.archive.read_text(), before)

    def test_a_promoted_row_is_not_counted_twice(self):
        # Promotion into the committed archive is a manual git commit; a row
        # left behind in the live file must not enter the GP twice.
        lb = self._lb()
        lb.append(Point(cfg="dup", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.archive.write_text(
            lb.header()
            + "dup\t2.000\t4.00000\t2.00000e-06\t0.000\t4.00000\n")
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["dup"])

    def test_a_malformed_archive_header_fails_loud(self):
        lb = self._lb()
        self.archive.write_text("wrong\theader\n1\t2\n")
        with self.assertRaises(SchemaMismatch):
            lb.load()

    def test_no_archive_configured_behaves_as_before(self):
        lb = Leaderboard(path=self.live, name="m",
                         knob_names=("a",), knob_fmts=("{:.3f}",),
                         metric_cols=("sob", "calo", "alpha", "obj"))
        lb.append(Point(cfg="only", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertEqual([p.cfg for p in lb.load()], ["only"])

    def test_pending_follows_the_live_file_not_the_archive(self):
        lb = self._lb()
        self.assertEqual(lb.pending_path().parent, self.live.parent)


if __name__ == "__main__":
    unittest.main()
