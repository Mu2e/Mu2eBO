"""Leaderboard module: schema-owning history I/O (spec 2026-08-08).

Regression anchor: touched-leaderboard-headerless-history-loss (foilspfbw01).
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from leaderboard import (  # noqa: E402
    Leaderboard, Point, SchemaMismatch, RowParseError)
import leaderboard as lbm  # noqa: E402
import study as st  # noqa: E402

sys.path.insert(0, str(ROOT))
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

_DEMO = Path(__file__).parent / "fixtures" / "studies" / "demo.json"

META = {"handles": "toy=c1.toy", "spec_sha": "s" * 64,
        "measure_sha": "m" * 64, "time": "2026-09-24T00:00:00Z"}
# META's cells as they end a row, tab-led.
META_TAIL = "".join("\t" + META[k] for k in lbm.V2_META)


class TestFormatsMatchARealBoard(unittest.TestCase):
    """A real row's cells come out of the writer byte for byte as the board
    that holds them has them. The board is the archived foilspfbpz study's
    committed one, written in layout "v1" (retired 2026-09-29): the same
    columns without the V2_META tail. The archived study file names kits
    deleted in Phase C3, so the columns come from its twin foilspfbpz_ax
    (same knobs, objectives and columns)."""

    def test_foilspfbpz_last_row_formats_identically(self):
        import modes
        src = ROOT / "leaderboards" / "leaderboard_bo_foilspfbpz.tsv"
        study = modes.STUDIES["foilspfbpz_ax"]
        lines = src.read_text().splitlines(keepends=True)
        head, last = lines[0], lines[-1]
        # format_line() never touches disk; this Leaderboard only needs a
        # plausible path, not a real directory.
        lb = lbm.Leaderboard.for_study(
            study, path=Path("/nonexistent") / src.name, archive_path=None)
        self.assertEqual(head.rstrip("\n") + "\t"
                         + "\t".join(lbm.V2_META) + "\n", lb.header())
        cells = last.rstrip("\n").split("\t")
        n = len(study.knob_names)
        p = lbm.Point(cfg=cells[0], x=[float(v) for v in cells[1:1 + n]],
                      y={"sob": float(cells[1 + n]),
                         "flash_edep": float(cells[2 + n])})
        line = lb.format_line(p, {"alpha": float(cells[3 + n])}, META)
        self.assertEqual(line, last.rstrip("\n") + META_TAIL + "\n")


def demo_lb(path: Path, archive_path: Path | None = None) -> Leaderboard:
    """The demo study's board (knobs a, b; objectives sob, flash_edep;
    extra columns alpha, obj; the V2_META tail; context alpha) at a
    scratch path."""
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
                         "config\ta\tb\tsob\tflash_edep\talpha\tobj"
                         "\thandles\tspec_sha\tmeasure_sha\ttime\n")

    def test_missing_file_loads_empty(self):
        self.assertEqual(self.lb.load(), [])

    def test_append_load_roundtrip(self):
        p = Point(cfg="t01", x=[1.5, 2.5],
                  y={"sob": 3.14159, "flash_edep": 6.85e-7})
        self.lb.append(p, {"alpha": 1.0e5}, META)
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
        self.lb.append(p, {"alpha": 1.0e5}, META)
        line = self.lb.path.read_text().splitlines()[1]
        self.assertEqual(line, "c1\t2.0000\t0.5000\t3.88000\t5.95893e-07"
                               "\t100000.000\t3.82041" + META_TAIL)

    def test_missing_context_is_an_error(self):
        p = Point(cfg="c1", x=[2.0, 0.5], y={"sob": 1.0, "flash_edep": 1e-6})
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(p, {}, META)

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
        # a header fused with row 1 on one line.
        self.lb.path.write_text(
            self.lb.header().rstrip("\n")
            + "t01\t1.0000\t2.0000\t3.00000\t1.00000e-07\t1.000\t3.00000"
            + META_TAIL + "\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.load()

    def test_malformed_row_is_loud_with_line_number(self):
        self.lb.append(Point("t01", [1.0, 2.0],
                             {"sob": 3.0, "flash_edep": 1e-7}), {"alpha": 1.0},
                       META)
        with self.lb.path.open("a") as f:
            f.write("t02\tnot_a_number\t2.0000\t3.00000\t1.0e-07\t1.000"
                    "\t3.00000" + META_TAIL + "\n")
        with self.assertRaises(RowParseError) as cm:
            self.lb.load()
        self.assertEqual(cm.exception.line_no, 3)

    def test_append_on_mismatch_quarantines_then_raises(self):
        self.lb.path.write_text("config\twrong\theader\n")
        p = Point(cfg="t01", x=[1.0, 2.0], y={"sob": 3.0, "flash_edep": 1e-7})
        with self.assertRaises(SchemaMismatch):
            self.lb.append(p, {"alpha": 1.0}, META)
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
            + "old1\t1.0000\t0.5000\t3.10000\t1.00000e-06\t0.000\t3.10000"
            + META_TAIL + "\n")
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0},
                  META)
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["old1", "new1"])

    def test_append_creates_the_live_directory(self):
        lb = self._lb()
        self.assertFalse(self.live.parent.exists())
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0},
                  META)
        self.assertTrue(self.live.exists())

    def test_append_never_writes_to_the_archive(self):
        lb = self._lb()
        self.archive.write_text(lb.header())
        before = self.archive.read_text()
        lb.append(Point(cfg="new1", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0},
                  META)
        self.assertEqual(self.archive.read_text(), before)

    def test_a_promoted_row_is_not_counted_twice(self):
        # Promotion into the committed archive is a manual git commit; a row
        # left behind in the live file must not enter the GP twice.
        lb = self._lb()
        lb.append(Point(cfg="dup", x=[2.0, 0.5],
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0},
                  META)
        self.archive.write_text(
            lb.header()
            + "dup\t2.0000\t0.5000\t4.00000\t2.00000e-06\t0.000\t4.00000"
            + META_TAIL + "\n")
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
                        y={"sob": 4.0, "flash_edep": 2e-6}), {"alpha": 0.0},
                  META)
        self.assertEqual([p.cfg for p in lb.load()], ["only"])

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
            + "prior\t2.0000\t0.5000\t4.00000\t2.00000e-06\t0.000\t4.00000"
            + META_TAIL + "\n")
        mode = repo.stat().st_mode
        repo.chmod(0o500)                      # r-x: readable, NOT writable
        try:
            self.assertEqual([p.cfg for p in lb.load()], ["prior"])
            self.assertFalse((repo / "locks").exists(),
                             "reading the archive must not write to the repo")
        finally:
            repo.chmod(mode)                   # else tearDown cannot remove it


class TestV2Rows(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(
            write_study(toy_doc(layout="v2"), self.tmp / "studies"))
        self.lb = Leaderboard.for_study(self.study, path=self.tmp / "b.tsv",
                                        archive_path=self.tmp / "arch.tsv")

    def pt(self, name="c1", b=1.5):
        return Point(name, [1.0, 2.0], {"branin": b, "currin": 3.0})

    def rows(self):
        return self.lb.path.read_text().splitlines()[1:]

    def test_header_ends_with_the_meta_columns(self):
        self.assertEqual(self.lb.header().rstrip("\n").split("\t")[-4:],
                         list(lbm.V2_META))

    def test_a_v2_row_needs_all_its_meta(self):
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {}, {})
        partial = {k: v for k, v in META.items() if k != "time"}
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {}, partial)

    def test_meta_may_not_hold_a_tab(self):
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {}, dict(META, handles="a\tb"))

    def test_append_then_load(self):
        self.assertTrue(self.lb.append(self.pt(), {}, META))
        (p,) = self.lb.load()
        self.assertEqual((p.cfg, p.x, p.y),
                         ("c1", [1.0, 2.0], {"branin": 1.5, "currin": 3.0}))
        self.assertTrue(self.rows()[0].endswith(
            "\ttoy=c1.toy\t" + "s" * 64 + "\t" + "m" * 64
            + "\t2026-09-24T00:00:00Z"))

    def test_the_same_row_again_is_a_no_op(self):
        self.lb.append(self.pt(), {}, META)
        again = self.lb.append(self.pt(), {},
                               dict(META, time="2026-09-25T00:00:00Z"))
        self.assertFalse(again)
        self.assertEqual(len(self.rows()), 1)

    def test_the_same_name_with_other_values_is_refused(self):
        self.lb.append(self.pt(), {}, META)
        with self.assertRaises(lbm.DuplicateRow):
            self.lb.append(self.pt(b=2.0), {}, META)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("c1", self.lb.quarantine_path().read_text())

    def test_a_different_measurement_is_refused(self):
        self.lb.append(self.pt(), {}, META)
        with self.assertRaises(lbm.MeasureMismatch) as cm:
            self.lb.append(self.pt("c2"), {}, dict(META, measure_sha="n" * 64))
        self.assertIn("new board", str(cm.exception))
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("c2", self.lb.quarantine_path().read_text())

    def test_the_archive_counts_for_the_measurement(self):
        arch = Leaderboard.for_study(self.study, path=self.tmp / "arch.tsv",
                                     archive_path=None)
        arch.append(self.pt("a1"), {}, dict(META, measure_sha="a" * 64))
        with self.assertRaises(lbm.MeasureMismatch):
            self.lb.append(self.pt("c2"), {}, META)
        self.assertFalse(self.lb.path.exists())

class TestMeasureShas(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(
            write_study(toy_doc(layout="v2"), self.tmp / "studies"))
        self.lb = Leaderboard.for_study(self.study, path=self.tmp / "b.tsv",
                                        archive_path=None)

    def test_a_missing_file_has_none(self):
        self.assertEqual(self.lb.measure_shas(), set())

    def test_a_header_only_board_has_none(self):
        self.lb.path.write_text(self.lb.header())
        self.assertEqual(self.lb.measure_shas(), set())

    def test_the_shas_of_the_rows(self):
        for name, sha in (("c1", "a" * 64), ("c2", "a" * 64)):
            self.lb.append(Point(name, [1.0, 2.0], {"branin": 1.5, "currin": 3.0}),
                           {}, dict(META, measure_sha=sha))
        self.assertEqual(self.lb.measure_shas(), {"a" * 64})
        self.lb.path.write_text(
            self.lb.path.read_text()
            + self.lb.path.read_text().splitlines()[1].replace("a" * 64, "b" * 64)
                .replace("c1", "c3") + "\n")
        self.assertEqual(self.lb.measure_shas(), {"a" * 64, "b" * 64})

    def archive_with(self, sha):
        arch = Leaderboard.for_study(self.study, path=self.tmp / "arch.tsv",
                                     archive_path=None)
        arch.append(Point("a1", [1.0, 2.0], {"branin": 1.5, "currin": 3.0}),
                    {}, dict(META, measure_sha=sha))
        return Leaderboard.for_study(self.study, path=self.tmp / "b.tsv",
                                     archive_path=arch.path)

    def test_an_archive_row_counts_with_no_live_file(self):
        lb = self.archive_with("b" * 64)
        self.assertEqual(lb.measure_shas(), {"b" * 64})

    def test_the_archive_and_the_live_board_are_one_union(self):
        lb = self.archive_with("b" * 64)
        lb.append(Point("c1", [1.0, 2.0], {"branin": 1.5, "currin": 3.0}),
                  {}, dict(META, measure_sha="b" * 64))
        lb.path.write_text(lb.header() + lb.path.read_text().splitlines()[1]
                           .replace("b" * 64, "a" * 64) + "\n")
        self.assertEqual(lb.measure_shas(), {"a" * 64, "b" * 64})

    def test_a_wrong_header_is_refused(self):
        self.lb.path.write_text("config\tx\n")
        with self.assertRaises(SchemaMismatch):
            self.lb.measure_shas()


if __name__ == "__main__":
    unittest.main()
