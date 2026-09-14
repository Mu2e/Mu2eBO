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
        self.assertTrue((p.REPO_ROOT / "graph" / "pool.py").is_file())

    def test_repo_root_matches_this_test_files_own_derivation(self):
        p = reload_with()
        self.assertEqual(p.REPO_ROOT, ROOT)

    def test_data_root_defaults_to_the_users_data_volume(self):
        p = reload_with()
        self.assertEqual(p.DATA_ROOT, Path("/exp/mu2e/data/users/testuser"))  # personal-path-ok: synthetic account name from reload_with()
        self.assertEqual(p.ARTIFACT_ROOT, Path("/exp/mu2e/app/users/testuser"))  # personal-path-ok: same synthetic account name

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
            # NOTE: assertRaises(paths.PathsError) does NOT work here.
            # importlib.reload re-executes the module, rebinding PathsError to
            # a NEW class object, so the class captured when assertRaises was
            # entered is not the class the reloaded code raises. Match on the
            # name instead of the identity; the module stays free of test
            # machinery.
            with self.assertRaises(Exception) as cm:
                importlib.reload(paths)
        self.assertEqual(type(cm.exception).__name__, "PathsError")
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


class TestEveryModuleAgreesOnTheRoot(unittest.TestCase):
    """The point of the module: one definition, not five copies that can
    drift. Each consumer keeps its own historic constant name; all must be
    the same object value as paths.REPO_ROOT."""

    def test_core_modules_use_the_resolver(self):
        import bo_driver
        import botorch_predict
        import harvest
        import pipeline
        self.assertEqual(bo_driver.ROOT, paths.REPO_ROOT)
        self.assertEqual(pipeline.AUTORESEARCH, paths.REPO_ROOT)
        self.assertEqual(botorch_predict.AUTORESEARCH, paths.REPO_ROOT)
        # harvest anchors on the muse work area, not the repo: Run1BAna is a
        # backing-resolved ARTIFACT (gitignored), so a fresh clone has none.
        self.assertEqual(harvest.MUSE_WORKAREA,
                         paths.artifact("autoresearch_muse"))

    def test_propose_and_preflight_scratch_is_not_in_the_repo(self):
        """Runtime OUTPUT never anchors on REPO_ROOT.

        proposal_dir/preflight_dir did until 2026-08-13, so `propose` wrote a
        candidate geom into the checkout -- fine when you own it,
        PermissionError when you are running someone else's (mmackenz, via
        tools/run_local.sh). Writable roots must derive from DATA_ROOT, which
        is per-operator by construction.
        """
        import bo_driver
        for mode in bo_driver.MODES.values():
            for d in (mode.proposal_dir, mode.preflight_dir):
                self.assertFalse(
                    str(d).startswith(str(paths.REPO_ROOT)),
                    f"{mode.name}: {d} is inside the repo")
                self.assertTrue(
                    str(d).startswith(str(paths.DATA_ROOT)),
                    f"{mode.name}: {d} is not under DATA_ROOT")

    def test_graph_modules_use_the_resolver(self):
        sys.path.insert(0, str(ROOT / "core"))
        os.environ.setdefault("AUTORESEARCH_MODE", "foilspf")
        import runtime
        self.assertEqual(runtime.BO_DRIVER, paths.REPO_ROOT / "core" / "bo_driver.py")


class TestDataRootsHaveOneDefinition(unittest.TestCase):
    """bo_driver.py used to carry three private copies of the grid-data root
    that could drift from graph/config.py's (retired 2026-08-19 into
    core/runtime.py). After the rewiring there is one definition and every
    consumer agrees with it."""

    def tearDown(self):
        importlib.reload(paths)

    def test_config_data_roots_come_from_the_resolver(self):
        # core/runtime.py's _SPEC lookup defaults AUTORESEARCH_MODE to the
        # live "foilspf" mode, so a bare `import runtime` no longer needs the
        # env var pre-stamped -- but prime it anyway so this file is runnable
        # standalone regardless of import order.
        os.environ.setdefault("AUTORESEARCH_MODE", "foilspf")
        sys.path.insert(0, str(ROOT / "core"))
        import runtime
        self.assertEqual(runtime.STOP_FLAG, paths.GRAPH_DATA / "STOP_CLOSED_LOOP")

    def test_bo_driver_no_longer_carries_its_own_grid_root(self):
        src = (ROOT / "core" / "bo_driver.py").read_text()
        self.assertNotIn("/exp/mu2e/data/users/", src)
        self.assertIn("GRID_DATA_ROOT", src)

    def test_grid_root_tracks_a_data_root_override(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.GRID_DATA_ROOT,
                         Path("/scratch/d/autoresearch_grid"))


class FakeSpec:
    def __init__(self, name, musing, grid_tarball):
        self.name, self.musing, self.grid_tarball = name, musing, grid_tarball


class TestRequire(unittest.TestCase):
    """paths.require: the shared stat-or-raise behind verify() and
    sourced_env()."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
        importlib.reload(paths)

    def test_returns_the_path_when_it_exists(self):
        setup = self.tmp / "setup_local.sh"
        setup.write_text("")
        self.assertEqual(paths.require(setup, "musing"), setup)

    def test_accepts_a_string_and_returns_a_path(self):
        # sourced_env passes MUSING, which is a str off the ModeSpec.
        setup = self.tmp / "setup_local.sh"
        setup.write_text("")
        self.assertEqual(paths.require(str(setup), "musing"), setup)

    def test_a_miss_names_the_path_the_description_and_the_remediation(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        with self.assertRaises(paths.PathsError) as cm:
            p.require(self.tmp / "gone.sh", "the mode's musing setup script")
        msg = str(cm.exception)
        self.assertIn("gone.sh", msg)
        self.assertIn("the mode's musing setup script", msg)
        self.assertIn("setup.sh --backing", msg)
        self.assertIn("ARTIFACT_ROOT", msg)

    def test_tail_is_appended_after_the_remediation(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        with self.assertRaises(paths.PathsError) as cm:
            p.require(self.tmp / "gone.sh", "thing", tail="\nOWN TAIL.")
        self.assertTrue(str(cm.exception).endswith("\nOWN TAIL."))


class TestVerify(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
        importlib.reload(paths)

    def test_passes_when_every_artifact_exists(self):
        setup = self.tmp / "setup_local.sh"
        tarball = self.tmp / "Code.tar.bz2"
        setup.write_text("")
        tarball.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(tarball))])

    def test_creates_the_three_data_dirs(self):
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(setup))])
        self.assertTrue(p.GRID_DATA_ROOT.is_dir())
        self.assertTrue(p.GRAPH_DATA.is_dir())
        self.assertTrue(p.LEADERBOARD_LIVE.is_dir())

    def test_missing_artifact_names_the_remediation_command(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        with self.assertRaises(paths.PathsError) as cm:
            p.verify([FakeSpec("m", str(self.tmp / "gone.sh"),
                               str(self.tmp / "gone.tar.bz2"))])
        msg = str(cm.exception)
        self.assertIn("setup.sh --backing", msg)
        self.assertIn("gone.sh", msg)
        self.assertIn("m", msg)

    def test_a_missing_extra_artifact_is_caught_too(self):
        # harvest's Run1BAna inputs are not per-mode ModeSpec fields, and no
        # step before harvest touches them -- so without this a fresh clone
        # ran every stage first and died at the very last one.
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        with self.assertRaises(paths.PathsError) as cm:
            p.verify([FakeSpec("m", str(setup), str(setup))],
                     extra=[(self.tmp / "gone.fcl", "EdepAna FCL (Run1BAna)")],
                     make_dirs=False)
        msg = str(cm.exception)
        self.assertIn("EdepAna FCL (Run1BAna)", msg)
        self.assertIn("setup.sh --backing", msg)

    def test_extra_defaults_to_empty_so_existing_callers_are_unaffected(self):
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(setup))], make_dirs=False)

    def test_make_dirs_false_does_not_create_anything(self):
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(setup))], make_dirs=False)
        self.assertFalse(p.GRID_DATA_ROOT.exists())


if __name__ == "__main__":
    unittest.main()
