"""Unit tests for core/paths.py — the single filesystem-root resolver.

Constants are module-level, so environment variation is done with
mock.patch.dict + importlib.reload, and tearDown reloads once more with the
pristine environment so later tests do not inherit a patched module.
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402


def reload_with(**env):
    """Reload paths with exactly `env` overlaid on a USER-only environment."""
    base = {"USER": "testuser"}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return importlib.reload(paths)


class TestPathsResolution(unittest.TestCase):
    def tearDown(self):
        importlib.reload(paths)   # restore the real environment's view

    def test_repo_root_is_the_directory_holding_core_and_graph(self):
        p = reload_with()
        self.assertTrue((p.REPO_ROOT / "core" / "paths.py").is_file())
        self.assertTrue((p.REPO_ROOT / "graph" / "config.py").is_file())

    def test_repo_root_matches_this_test_files_own_derivation(self):
        p = reload_with()
        self.assertEqual(p.REPO_ROOT, ROOT)

    def test_data_root_defaults_to_the_users_data_volume(self):
        p = reload_with()
        self.assertEqual(p.DATA_ROOT, Path("/exp/mu2e/data/users/testuser"))
        self.assertEqual(p.ARTIFACT_ROOT, Path("/exp/mu2e/app/users/testuser"))

    def test_env_override_beats_the_user_default(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d",
                        AUTORESEARCH_ARTIFACT_ROOT="/scratch/a")
        self.assertEqual(p.DATA_ROOT, Path("/scratch/d"))
        self.assertEqual(p.ARTIFACT_ROOT, Path("/scratch/a"))

    def test_derived_data_roots_hang_off_data_root(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.GRID_DATA_ROOT, Path("/scratch/d/autoresearch_grid"))
        self.assertEqual(p.GRAPH_DATA,
                         Path("/scratch/d/autoresearch_graph_data"))
        self.assertEqual(p.LEADERBOARD_LIVE,
                         Path("/scratch/d/autoresearch_leaderboards"))

    def test_unset_user_raises_instead_of_inventing_a_path(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(paths.PathsError) as cm:
                importlib.reload(paths)
        self.assertIn("AUTORESEARCH_DATA_ROOT", str(cm.exception))

    def test_import_does_not_require_exp_mu2e_to_exist(self):
        # Resolution is string math: a root pointing at a nonexistent tree
        # must import cleanly. Only artifact()/verify() stat.
        p = reload_with(AUTORESEARCH_DATA_ROOT="/no/such/tree/d",
                        AUTORESEARCH_ARTIFACT_ROOT="/no/such/tree/a")
        self.assertEqual(p.DATA_ROOT, Path("/no/such/tree/d"))
        self.assertFalse(p.DATA_ROOT.exists())


class TestArtifactLinkOrder(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        (self.tmp / "local").mkdir()
        (self.tmp / "backing").mkdir()

    def tearDown(self):
        self._td.cleanup()
        importlib.reload(paths)

    def _paths(self):
        return reload_with(
            AUTORESEARCH_ARTIFACT_ROOT=str(self.tmp / "local"),
            AUTORESEARCH_BACKING=str(self.tmp / "backing"))

    def test_local_wins_over_backing(self):
        (self.tmp / "local" / "tool.sh").write_text("local\n")
        (self.tmp / "backing" / "tool.sh").write_text("backing\n")
        p = self._paths()
        self.assertEqual(p.artifact("tool.sh").read_text(), "local\n")

    def test_backing_fills_in_what_local_lacks(self):
        (self.tmp / "backing" / "tool.sh").write_text("backing\n")
        p = self._paths()
        self.assertEqual(p.artifact("tool.sh").read_text(), "backing\n")

    def test_miss_returns_the_intended_local_path_and_never_raises(self):
        p = self._paths()
        got = p.artifact("nowhere/tool.sh")
        self.assertEqual(got, self.tmp / "local" / "nowhere" / "tool.sh")
        self.assertFalse(got.exists())

    def test_no_backing_configured_is_fine(self):
        p = reload_with(AUTORESEARCH_ARTIFACT_ROOT=str(self.tmp / "local"))
        self.assertIsNone(p.BACKING)
        self.assertEqual(p.artifact("tool.sh"), self.tmp / "local" / "tool.sh")

    def test_absolute_rel_is_rejected(self):
        p = self._paths()
        with self.assertRaises(paths.PathsError):
            p.artifact("/etc/passwd")


class TestLeaderboardPaths(unittest.TestCase):
    def tearDown(self):
        importlib.reload(paths)

    def test_archive_keeps_the_repo_relative_path(self):
        p = reload_with()
        self.assertEqual(p.leaderboard_archive("leaderboards/lb_x.tsv"),
                         p.REPO_ROOT / "leaderboards" / "lb_x.tsv")

    def test_live_flattens_to_the_basename(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.leaderboard_live("leaderboards/lb_x.tsv"),
                         Path("/scratch/d/autoresearch_leaderboards/lb_x.tsv"))

    def test_absolute_leaderboard_rel_is_rejected(self):
        p = reload_with()
        with self.assertRaises(paths.PathsError):
            p.leaderboard_live("/tmp/escaped.tsv")


if __name__ == "__main__":
    unittest.main()
