"""Every live tracked leaderboard/pending file must satisfy its study's
header — the pre-landing check of spec 2026-08-08, kept permanently so
schema drift is caught in the suite, not mid-campaign.

If this fails on a REAL tracked file: STOP, report — do not edit the file.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import modes  # noqa: E402
from leaderboard import Leaderboard, PENDING_HEADER  # noqa: E402


class TestLiveFileHeaders(unittest.TestCase):
    def test_every_live_leaderboard_and_pending_header(self):
        checked = 0
        live_root, archive_root = ROOT / "leaderboards", ROOT
        for name, study in modes.STUDIES.items():
            rel = Path(study.leaderboard_rel)
            lb = Leaderboard.for_study(study,
                                       path=live_root / rel.name,
                                       archive_path=archive_root / rel)
            for target in (lb.archive_path, lb.path):
                if target is None or not target.exists():
                    continue
                with target.open() as f:
                    first = f.readline()
                self.assertEqual(
                    first.rstrip("\n"), lb.header().rstrip("\n"),
                    msg=f"{target} header != Study({name}) schema")
                checked += 1
            pp = lb.pending_path()
            if pp.exists() and pp.stat().st_size > 0:
                with pp.open() as f:
                    first = f.readline()
                self.assertEqual(
                    first.rstrip("\n"), PENDING_HEADER.rstrip("\n"),
                    msg=f"{pp} pending header malformed")
                checked += 1
        self.assertGreater(checked, 0, "no live files found — wrong ROOT?")


if __name__ == "__main__":
    unittest.main()
