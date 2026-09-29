"""Tests for the launch gates that used to be inline bash in tools/*.sh.

The point of moving them into core/launch_checks.py was that shell made them
untestable: a renamed env var or a changed state-file suffix could disable a
gate with nothing failing. These are the tests that make that a failure.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import launch_checks as lc  # noqa: E402


class TestConfigNameFree(unittest.TestCase):
    def _board(self, tmp, rows):
        board = Path(tmp) / "leaderboard_bo_foilspf.tsv"
        board.write_text("config\tsob\n" + "".join(f"{r}\t1.0\n" for r in rows))
        return board

    def test_name_already_on_a_board(self):
        with TemporaryDirectory() as tmp:
            board = self._board(tmp, ["grid01", "grid02"])
            problem = lc.check_config_name_free("grid02", [board])
            self.assertIn("already used", problem)

    def test_free_name(self):
        with TemporaryDirectory() as tmp:
            board = self._board(tmp, ["grid01"])
            self.assertIsNone(lc.check_config_name_free("grid99", [board]))

    def test_prefix_is_not_a_collision(self):
        """`grid1` must not match `grid10` -- the bash version anchored on a
        trailing whitespace class for exactly this reason."""
        with TemporaryDirectory() as tmp:
            board = self._board(tmp, ["grid10"])
            self.assertIsNone(lc.check_config_name_free("grid1", [board]))

    def test_unreadable_board_is_skipped_not_fatal(self):
        self.assertIsNone(
            lc.check_config_name_free("x", [Path("/nonexistent/board.tsv")]))

    def test_pending_files_are_scanned_too(self):
        """Live boards and pending files share one directory and one suffix;
        a name in either makes propose_one raise."""
        with TemporaryDirectory() as tmp:
            live = Path(tmp) / "autoresearch_leaderboards"
            live.mkdir()
            (live / "pending_bo_foilspf.tsv").write_text("config\tx\nptl01\t[]\n")
            found = lc.boards(data_root=Path(tmp))
            self.assertTrue(any(p.name.startswith("pending_") for p in found))
            self.assertIn("already used",
                          lc.check_config_name_free("ptl01", found))


class TestStaleClusters(unittest.TestCase):
    def test_stale_cluster_file_blocks_the_launch(self):
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "cfg01" / "state"
            state.mkdir(parents=True)
            (state / "mubeam_cluster.txt").write_text("123@schedd\n")
            problem = lc.check_no_stale_clusters("cfg01", Path(tmp))
            self.assertIn("cluster files", problem)
            self.assertIn("mubeam_cluster.txt", problem)

    def test_clean_state_dir_passes(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(lc.check_no_stale_clusters("cfg01", Path(tmp)))


class TestQuota(unittest.TestCase):
    def _xattr(self, used, quota):
        return lambda path, name: {
            "ceph.quota.max_bytes": str(quota).encode(),
            "ceph.dir.rbytes": str(used).encode()}[name]

    def test_under_the_limit_reports_usage_only(self):
        problem, info = lc.check_quota(Path("/x"),
                                       getxattr=self._xattr(int(5e11), int(2e12)))
        self.assertIsNone(problem)
        self.assertIn("25% of quota", info)

    def test_at_the_limit_is_a_problem(self):
        problem, _ = lc.check_quota(Path("/x"),
                                    getxattr=self._xattr(int(1.9e12), int(2e12)))
        self.assertIsNotNone(problem)
        self.assertIn("Errno 122", problem)

    def test_no_quota_xattr_is_silent(self):
        """Not every filesystem carries the CephFS xattrs; absence must not
        block a launch."""
        def raiser(path, name):
            raise OSError("no xattr")
        problem, info = lc.check_quota(Path("/x"), getxattr=raiser)
        self.assertIsNone(problem)
        self.assertIsNone(info)

    def test_zero_quota_is_treated_as_unset(self):
        self.assertIsNone(lc.quota_usage(Path("/x"),
                                         getxattr=self._xattr(10, 0)))

    def test_walks_up_to_the_volume_that_carries_the_quota(self):
        """DATA_ROOT is often a sandbox SUBDIRECTORY of the volume the quota
        sits on, and the volume root must not be hardcoded (one operator's
        path in everyone's launcher -- tests/test_no_hardcoded_paths)."""
        owner = "/fake/volume/owner"  # any nested layout; the walk is path-agnostic

        def xattr(path, name):
            if path != owner:
                raise OSError("no xattr here")
            return {"ceph.quota.max_bytes": b"2000000000000",
                    "ceph.dir.rbytes": b"500000000000"}[name]

        found = lc.quota_volume(Path(owner) / "localtest" / "deep",
                                getxattr=xattr)
        self.assertIsNotNone(found)
        self.assertEqual(str(found[0]), owner)
        _, info = lc.check_quota(Path(owner) / "localtest", getxattr=xattr)
        self.assertIn("25% of quota", info)

    def test_no_quota_anywhere_up_the_chain_is_silent(self):
        def raiser(path, name):
            raise OSError("no xattr")
        self.assertIsNone(lc.quota_volume(Path("/a/b/c"), getxattr=raiser))


class TestPrereqsAndBanner(unittest.TestCase):
    def test_unknown_mode_names_the_known_ones(self):
        problem = lc.check_prereqs("nosuchmode")
        self.assertIn("unknown mode", problem)
        self.assertIn("foilspf", problem)

    def test_stage_width_reads_the_spec(self):
        """The launch banner must be derived, never restated -- this is the
        line that would otherwise drift from what actually gets submitted."""
        import modes
        width = lc.stage_width("foilspf")
        for stage in modes.SPECS["foilspf"].grid_stages:
            self.assertIn(stage, width)
        self.assertNotIn("?", width)


class TestLaunchersStillCallTheGates(unittest.TestCase):
    """The regression this refactor exists to prevent: a launcher that quietly
    stops running the checks looks exactly like a working launcher."""

    def test_both_scripts_invoke_launch_checks(self):
        for script in ("run_grid.sh", "run_local.sh"):
            text = (ROOT / "tools" / script).read_text()
            self.assertIn("core/launch_checks.py", text, script)
            self.assertIn("|| exit 2", text, script)

    def test_only_the_grid_launcher_passes_grid(self):
        grid = (ROOT / "tools" / "run_grid.sh").read_text()
        local = (ROOT / "tools" / "run_local.sh").read_text()
        self.assertIn("--grid", grid)
        self.assertNotIn("--grid", local)

    def test_no_guard_was_left_behind_in_bash(self):
        """Whole point of the move: these must live in Python now, not both
        places, or the two copies drift."""
        for script in ("run_grid.sh", "run_local.sh"):
            text = (ROOT / "tools" / script).read_text()
            self.assertNotIn("getfattr", text, script)
            self.assertNotIn("klist", text, script)
            self.assertNotIn("_cluster.txt", text, script)


if __name__ == "__main__":
    unittest.main()
