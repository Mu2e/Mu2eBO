"""Every live tracked leaderboard file must satisfy its study's
header — the pre-landing check of spec 2026-08-08, kept permanently so
schema drift is caught in the suite, not mid-campaign.

If this fails on a REAL tracked file: STOP, report — do not edit the file.

Since Phase C3 the loaded studies are the _ax engine twins. None has a
committed board yet (the engine writes live boards under DATA_ROOT), so until
one is promoted into leaderboards/ there is nothing to check and the test
SKIPS, saying so, rather than reading as a green check. The archived
studies' v1 boards are not checked: their study files are unloaded.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import modes  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402


class TestLiveFileHeaders(unittest.TestCase):
    def test_every_live_leaderboard_header(self):
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
        self.assertTrue(live_root.is_dir(), f"{live_root} missing — wrong ROOT?")
        self.assertTrue(modes.STUDIES, "no studies loaded")
        if checked == 0:
            self.skipTest(
                f"nothing to check: none of the loaded studies "
                f"({', '.join(sorted(modes.STUDIES))}) has a board "
                f"under {live_root} yet (see the module docstring)")


if __name__ == "__main__":
    unittest.main()
