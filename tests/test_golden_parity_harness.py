"""Guards on the golden-parity harness itself.

The harness is manually run (not in `unittest discover`'s import graph by
accident -- it is imported here deliberately), so nothing else notices when it
silently stops pinning anything. That is exactly what happened: the
archive/live leaderboard split redefined `mode.leaderboard` to mean the
operator's LIVE board on $DATA_ROOT, `_roundtrip_mode` returned None for every
mode because no live board exists yet, and section (a) reported MISMATCH with
`current=None` -- indistinguishable from a real data regression.

These tests fail on that shape rather than letting it read as a diff.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tests"))

import bo_driver as bo  # noqa: E402
import golden_parity as gp  # noqa: E402


class TestSectionAPinsSomething(unittest.TestCase):
    """Section (a) must pin the committed archive, which is in-repo."""

    def test_every_mode_with_a_committed_archive_is_pinned(self):
        result = gp.section_a()
        unpinned = []
        for name, per_mode in result.items():
            archive = bo.MODES[name].leaderboard_archive
            if archive and archive.exists():
                if per_mode is None or per_mode.get("archive") is None:
                    unpinned.append(name)
        self.assertEqual(
            unpinned, [],
            "section_a() pinned nothing for modes whose committed archive "
            "exists on disk -- the harness is reporting on a board it cannot "
            "see. This is the archive/live split regression.")

    def test_result_carries_both_board_slots(self):
        """Each mode reports archive and live separately, so a missing live
        board is legible as 'absent' rather than collapsing the whole mode."""
        for name, per_mode in gp.section_a().items():
            self.assertIsNotNone(
                per_mode, f"{name}: whole-mode None hides which board is gone")
            self.assertIn("archive", per_mode, name)
            self.assertIn("live", per_mode, name)

    def test_section_a_raises_when_it_can_pin_nothing(self):
        """A harness that pins zero files must fail loudly, not return a dict
        of Nones that compares unequal and looks like a data diff."""
        saved = {n: (m.leaderboard, m.leaderboard_archive)
                 for n, m in bo.MODES.items()}
        missing = ROOT / "tests" / "goldens" / "definitely-not-here.tsv"
        try:
            for m in bo.MODES.values():
                m.leaderboard = missing
                m.leaderboard_archive = None
            with self.assertRaises(SystemExit):
                gp.section_a()
        finally:
            for n, (lb, arch) in saved.items():
                bo.MODES[n].leaderboard = lb
                bo.MODES[n].leaderboard_archive = arch


if __name__ == "__main__":
    unittest.main()
