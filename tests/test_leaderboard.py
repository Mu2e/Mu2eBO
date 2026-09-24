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
import leaderboard as lbm  # noqa: E402
import study as st  # noqa: E402

_DEMO = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


class TestByteIdenticalOnARealBoard(unittest.TestCase):
    """Appending to a copy of a real board adds exactly the line today's
    writer would have produced."""

    def test_foilspfbpz_last_row_rewritten_identically(self):
        import modes
        root = Path(__file__).resolve().parent.parent
        src = root / "leaderboards" / "leaderboard_bo_foilspfbpz.tsv"
        study = modes.STUDIES["foilspfbpz"]
        with tempfile.TemporaryDirectory() as td:
            lines = src.read_text().splitlines(keepends=True)
            head, last = lines[:-1], lines[-1]
            copy = Path(td) / src.name
            copy.write_text("".join(head))
            lb = lbm.Leaderboard.for_study(study, path=copy, archive_path=None)
            cells = last.rstrip("\n").split("\t")
            n = len(study.knob_names)
            p = lbm.Point(cfg=cells[0], x=[float(v) for v in cells[1:1 + n]],
                          y={"sob": float(cells[1 + n]),
                             "flash_edep": float(cells[2 + n])})
            lb.append(p, {"alpha": float(cells[3 + n])})
            self.assertEqual(copy.read_text().splitlines(keepends=True)[-1], last)


def demo_lb(path: Path, archive_path: Path | None = None) -> Leaderboard:
    """The demo study's board (knobs a, b; objectives sob, flash_edep;
    extra columns alpha, obj; context alpha) at a scratch path."""
    return Leaderboard.for_study(st.load_study_file(_DEMO), path=path,
                                 archive_path=archive_path)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = demo_lb(self.tmp / "leaderboard_bo_test.tsv")

    def tearDown(self):
        self._td.cleanup()

    def test_header_line(self):
        self.assertEqual(self.lb.header(),
                         "config\ta\tb\tsob\tflash_edep\talpha\tobj\n")

    def test_missing_file_loads_empty(self):
        self.assertEqual(self.lb.load(), [])

    def test_append_load_roundtrip(self):
        p = Point(cfg="t01", x=[1.5, 2.5],
                  y={"sob": 3.14159, "flash_edep": 6.85e-7})
        self.lb.append(p, {"alpha": 1.0e5})
        first = self.lb.path.read_text().splitlines()[0] + "\n"
        self.assertEqual(first, self.lb.header())
        [got] = self.lb.load()
        self.assertEqual(got.cfg, "t01")
        self.assertEqual(got.x, [1.5, 2.5])
        self.assertEqual(set(got.y), {"sob", "flash_edep"})
        self.assertAlmostEqual(got.y["sob"], 3.14159, places=5)
        self.assertAlmostEqual(got.y["flash_edep"], 6.85e-7, places=12)

    def test_append_formats_like_today(self):
        p = Point(cfg="c1", x=[2.0, 0.5], y={"sob": 3.88, "flash_edep": 5.95893e-07})
        self.lb.append(p, {"alpha": 1.0e5})
        line = self.lb.path.read_text().splitlines()[1]
        self.assertEqual(line, "c1\t2.0000\t0.5000\t3.88000\t5.95893e-07"
                               "\t100000.000\t3.82041")

    def test_missing_context_is_an_error(self):
        p = Point(cfg="c1", x=[2.0, 0.5], y={"sob": 1.0, "flash_edep": 1e-6})
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(p, {})

    def test_headerless_board_refused(self):
        self.lb.path.write_text("c1\t2\t0.5\t3\t1e-6\t1e5\t2.9\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_touched_file_is_loud_not_empty(self):
        # touched-leaderboard-headerless-history-loss: a 0-byte existing file
        # must raise, never return [] while rows could exist.
        self.lb.path.touch()
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_fused_header_is_loud(self):
        # the remove_pending fusion shape: header and row 1 on one line.
        self.lb.path.write_text(
            "config\ta\tb\tsob\tflash_edep\talpha\tobj"
            "t01\t1.0000\t2.0000\t3.00000\t1.00000e-07\t1.000\t3.00000\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_malformed_row_is_loud_with_line_number(self):
        self.lb.append(Point("t01", [1.0, 2.0],
                             {"sob": 3.0, "flash_edep": 1e-7}), {"alpha": 1.0})
        with self.lb.path.open("a") as f:
            f.write("t02\tnot_a_number\t2.0000\t3.00000\t1.0e-07\t1.000\t3.00000\n")
        with self.assertRaises(RowParseError) as cm:
            self.lb.load()
        self.assertEqual(cm.exception.line_no, 3)

    def test_append_on_mismatch_quarantines_then_raises(self):
        self.lb.path.write_text("config\twrong\theader\n")
        p = Point(cfg="t01", x=[1.0, 2.0], y={"sob": 3.0, "flash_edep": 1e-7})
        with self.assertRaises(SchemaMismatch):
            self.lb.append(p, {"alpha": 1.0})
        q = self.lb.quarantine_path()
        self.assertTrue(q.exists())
        lines = q.read_text().splitlines()
        self.assertEqual(lines[0] + "\n", self.lb.header())
        self.assertTrue(lines[1].startswith("t01\t"))
        # main file untouched
        self.assertEqual(self.lb.path.read_text(), "config\twrong\theader\n")

    def test_bad_spec_fails_at_construction(self):
        # The fixed 4-column metric tail is gone (a study's columns are its
        # own); what __post_init__ still guards is names/formats lockstep.
        common = dict(path=self.tmp / "x.tsv", name="x", extra_columns=(),
                      context_names=(), consts={})
        with self.assertRaises(ValueError):
            Leaderboard(knob_names=("a",), knob_fmts=("{:.2f}",),
                        value_names=("sob", "calo"), value_fmts=("{:.5f}",),
                        **common)
        with self.assertRaises(ValueError):
            Leaderboard(knob_names=("a", "b"), knob_fmts=("{:.2f}",),
                        value_names=("sob",), value_fmts=("{:.5f}",),
                        **common)


class TestPending(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.lb = demo_lb(self.tmp / "leaderboard_bo_test.tsv")

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
            lb = demo_lb(tmp / "leaderboard_bo_test.tsv")
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
        return demo_lb(self.live, archive_path=self.archive)

    def test_load_returns_archive_rows_then_live_rows(self):
        lb = self._lb()
        self.archive.write_text(
            lb.header()
            + "old1\t1.0000\t0.5000\t3.10000\t1.00000e-06\t0.000\t3.10000\n")
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0})
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["old1", "new1"])

    def test_append_creates_the_live_directory(self):
        lb = self._lb()
        self.assertFalse(self.live.parent.exists())
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0})
        self.assertTrue(self.live.exists())

    def test_append_never_writes_to_the_archive(self):
        lb = self._lb()
        self.archive.write_text(lb.header())
        before = self.archive.read_text()
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0})
        self.assertEqual(self.archive.read_text(), before)

    def test_a_promoted_row_is_not_counted_twice(self):
        # Promotion into the committed archive is a manual git commit; a row
        # left behind in the live file must not enter the GP twice.
        lb = self._lb()
        lb.append(Point(cfg="dup", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0})
        self.archive.write_text(
            lb.header()
            + "dup\t2.0000\t0.5000\t4.00000\t2.00000e-06\t0.000\t4.00000\n")
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["dup"])

    def test_a_malformed_archive_header_fails_loud(self):
        lb = self._lb()
        self.archive.write_text("wrong\theader\n1\t2\n")
        with self.assertRaises(SchemaMismatch):
            lb.load()

    def test_no_archive_configured_behaves_as_before(self):
        lb = demo_lb(self.live, archive_path=None)
        lb.append(Point(cfg="only", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0})
        self.assertEqual([p.cfg for p in lb.load()], ["only"])

    def test_pending_follows_the_live_file_not_the_archive(self):
        lb = self._lb()
        self.assertEqual(lb.pending_path().parent, self.live.parent)

    def test_a_read_only_archive_dir_still_loads(self):
        """Someone else's checkout is READ-ONLY to you.

        Locking the archive created <its dir>/locks/<name>.lock, so merely
        READING the committed priors needed WRITE access to the repo. That
        died with PermissionError inside propose for a colleague running
        run_local.sh out of another user's worktree (2026-08-13).
        """
        repo = self.tmp / "someone_elses_repo" / "leaderboards"
        repo.mkdir(parents=True)
        archive = repo / "archive.tsv"
        lb = demo_lb(self.live, archive_path=archive)
        archive.write_text(
            lb.header()
            + "prior\t2.0000\t0.5000\t4.00000\t2.00000e-06\t0.000\t4.00000\n")
        mode = repo.stat().st_mode
        repo.chmod(0o500)                      # r-x: readable, NOT writable
        try:
            self.assertEqual([p.cfg for p in lb.load()], ["prior"])
            self.assertFalse((repo / "locks").exists(),
                             "reading the archive must not write to the repo")
        finally:
            repo.chmod(mode)                   # else tearDown cannot remove it


if __name__ == "__main__":
    unittest.main()
