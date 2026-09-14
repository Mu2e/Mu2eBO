"""The four one-shot A/B specs are archived, not deleted.

Their leaderboards (leaderboard_ab_*.tsv) stay in place and readable, so
nothing that can reproduce a past row is destroyed -- only the registry glob
stops picking the specs up.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

ARCHIVED = ["ipa625", "ipafix", "ipaovr", "nominal"]
LIVE = ["foilsflash", "foilspf", "foilspf2k", "foilspfbp",
        "foilspfbpx", "foilspfbpz", "foilspfbw"]


class TestModeArchive(unittest.TestCase):
    def test_live_modes_are_exactly_the_foilspf_family(self):
        import modes
        self.assertEqual(sorted(modes.SPECS), sorted(LIVE))

    def test_archived_specs_moved_not_deleted(self):
        for m in ARCHIVED:
            self.assertFalse((ROOT / "mode_specs" / f"{m}.json").exists(), m)
            self.assertTrue((ROOT / "mode_specs" / "archive" / f"{m}.json").exists(), m)

    def test_archived_leaderboards_still_present(self):
        for m in ARCHIVED:
            self.assertTrue(
                (ROOT / "leaderboards" / f"leaderboard_ab_{m}.tsv").exists(), m)


if __name__ == "__main__":
    unittest.main()
