"""board_for: the leaderboard a study writes and trains on, which is its
live board under DATA_ROOT plus the committed archive at its repo-relative
path (core/leaderboard.py owns the format)."""
from __future__ import annotations

if __package__:
    from core.leaderboard import Leaderboard
    from core.paths import leaderboard_archive, leaderboard_live
else:
    from leaderboard import Leaderboard
    from paths import leaderboard_archive, leaderboard_live


def board_for(study) -> Leaderboard:
    return Leaderboard.for_study(
        study, path=leaderboard_live(study.leaderboard_rel),
        archive_path=leaderboard_archive(study.leaderboard_rel))
