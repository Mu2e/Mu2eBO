"""Real-flock tests for bo_driver._lock_path/_flock_ex/_flock_sh.

Regression anchor: 2026-07-17 the _lock_path insertion silently captured
_flock_ex's @contextmanager decorator — every real lock acquisition raised
TypeError while the whole suite stayed green (no test entered the
contextmanagers). These tests hold locks for real and probe contention from
a child process (flock exclusion is between processes/fds, not within one).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402

# Child: try a non-blocking flock of the given kind on argv[1]; rc 0 = got
# it, rc 3 = blocked.
_CHILD = r"""
import fcntl, sys
mode = fcntl.LOCK_EX if sys.argv[2] == "ex" else fcntl.LOCK_SH
try:
    with open(sys.argv[1], "w") as f:
        fcntl.flock(f.fileno(), mode | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(3)
sys.exit(0)
"""


def _child_try(lock_path: Path, kind: str) -> int:
    return subprocess.run(
        [sys.executable, "-c", _CHILD, str(lock_path), kind],
        capture_output=True).returncode


class TestLockPath(unittest.TestCase):
    def test_anchor_is_locks_dir_next_to_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "leaderboard_bo_x.tsv"
            lp = bo._lock_path(target)
            self.assertEqual(lp, Path(tmp) / "locks" / "leaderboard_bo_x.tsv.lock")
            self.assertTrue(lp.parent.is_dir())  # locks/ auto-created


class TestFlockContention(unittest.TestCase):
    def test_ex_blocks_child_ex_until_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            lp = bo._lock_path(target)
            with bo._flock_ex(target):
                self.assertEqual(_child_try(lp, "ex"), 3)  # blocked
                self.assertEqual(_child_try(lp, "sh"), 3)  # readers blocked too
            self.assertEqual(_child_try(lp, "ex"), 0)      # released

    def test_sh_allows_child_sh_blocks_child_ex(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            lp = bo._lock_path(target)
            with bo._flock_sh(target):
                self.assertEqual(_child_try(lp, "sh"), 0)  # concurrent readers OK
                self.assertEqual(_child_try(lp, "ex"), 3)  # writer blocked

    def test_contextmanagers_are_actually_contextmanagers(self):
        # The 2026-07-17 breakage made _flock_ex(target) raise TypeError.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "t.tsv"
            with bo._flock_ex(target):
                pass
            with bo._flock_sh(target):
                pass


if __name__ == "__main__":
    unittest.main()
