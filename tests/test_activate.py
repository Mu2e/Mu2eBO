"""Tests for activate.sh -- which interpreter the project runs on.

The switch from a personal `.venv` to the published cvmfs env (`ana 2.8.0`,
2026-08-20) has two failure modes that are silent rather than loud, and both
are pinned here: resolving an env whose numpy is too old for torch, and
letting `pyenv.sh`'s exported command wrappers into our subprocesses.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
ACTIVATE = ROOT / "activate.sh"
CVMFS = Path("/cvmfs/mu2e.opensciencegrid.org")


def run_activate(env_extra, script='echo "$AUTORESEARCH_PYTHON"'):
    """Source activate.sh in a clean bash and report (rc, stdout, stderr)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("AUTORESEARCH_")}
    env.update(env_extra)
    p = subprocess.run(
        ["bash", "-c", f"source '{ACTIVATE}' || exit 2\n{script}"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


class TestVersionIsAlwaysExplicit(unittest.TestCase):
    """`pyenv ana` with no version means 2.7.0 and `current` is 2.6.1 -- both
    numpy 1.26, which torch and botorch will not run on. An implicit version
    must be refused, not resolved."""

    def test_name_without_version_is_refused(self):
        rc, _, err = run_activate({"AUTORESEARCH_PYENV": "ana"})
        self.assertEqual(rc, 2)
        self.assertIn("NAME VERSION", err)

    def test_default_pins_a_version(self):
        text = ACTIVATE.read_text()
        self.assertIn("AUTORESEARCH_PYENV:=ana 2.8.0", text)

    def test_unpublished_version_names_the_path(self):
        rc, _, err = run_activate({"AUTORESEARCH_PYENV": "ana 0.0.0"})
        self.assertEqual(rc, 2)
        self.assertIn("env/ana/0.0.0", err)


class TestVenvOverride(unittest.TestCase):
    def test_missing_venv_is_refused(self):
        with TemporaryDirectory() as tmp:
            rc, _, err = run_activate({"AUTORESEARCH_VENV": tmp})
            self.assertEqual(rc, 2)
            self.assertIn("not a venv", err)

    def test_venv_wins_over_the_published_env(self):
        """The dev override has to beat the default, or there is no way to
        test a change against a writable stack."""
        venv = ROOT / ".venv"
        if not (venv / "bin" / "python").exists():
            self.skipTest("no .venv on this machine")
        rc, out, _ = run_activate({"AUTORESEARCH_VENV": str(venv)})
        self.assertEqual(rc, 0)
        self.assertEqual(out, str(venv / "bin" / "python"))


class TestNeverActivates(unittest.TestCase):
    """pyenv.sh `export -f`s wrappers for python/pip/jupyter/conda/mamba, and
    each wrapper re-prepends the env's site-packages to PYTHONPATH and its
    lib/ to LD_LIBRARY_PATH on EVERY call. Exported bash functions cross into
    every child, so an activated shell would push a second ROOT/XRootD
    binding into the harvest steps that run PyROOT under `muse setup`."""

    def test_does_not_source_pyenv(self):
        text = ACTIVATE.read_text()
        self.assertNotIn("source \"$_PYENV_SH\"", text)
        self.assertNotIn("pyenv.sh\"", text.replace("# ", ""))

    def test_leaves_the_environment_untouched(self):
        if not CVMFS.is_dir():
            self.skipTest("no /cvmfs on this machine")
        rc, out, _ = run_activate(
            {}, script='echo "PP=[${PYTHONPATH-unset}] FN=$(declare -F python)"')
        self.assertEqual(rc, 0)
        # PYTHONPATH must be untouched -- unset, or whatever it already was
        # (the caller runs with it empty); what it must NEVER be is the env's
        # site-packages. And no `python` shell function may exist to inherit.
        payload = out.split("PP=[")[1]
        pythonpath = payload.split("]")[0]
        self.assertIn(pythonpath, ("", "unset"), f"PYTHONPATH gained {pythonpath!r}")
        self.assertNotIn("site-packages", out)
        self.assertEqual(out.split("FN=")[1].strip(), "")


class TestResolvesThePublishedEnv(unittest.TestCase):
    def setUp(self):
        if not CVMFS.is_dir():
            self.skipTest("no /cvmfs on this machine")

    def test_default_resolves_to_a_working_interpreter(self):
        rc, out, _ = run_activate(
            {}, script='PYTHONPATH= "$AUTORESEARCH_PYTHON" -c '
                       '"import sys;print(sys.version_info[:2])"')
        self.assertEqual(rc, 0)
        self.assertIn("(3, 12)", out)

    def test_reports_its_source(self):
        rc, out, _ = run_activate({}, script='echo "$AUTORESEARCH_PYTHON_SOURCE"')
        self.assertEqual(rc, 0)
        self.assertEqual(out, "pyenv ana 2.8.0")

    def test_the_published_env_carries_the_bo_stack(self):
        """numpy 2 was the ONE load-bearing conflict that kept this project
        off the shared env; 2.8.0 is the release that resolved it."""
        rc, out, _ = run_activate(
            {}, script='PYTHONPATH= "$AUTORESEARCH_PYTHON" -c '
                       '"import numpy,torch,botorch;print(numpy.__version__[0])" '
                       '2>/dev/null')
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "2", "published env must ship numpy 2.x")


class TestLaunchersUseIt(unittest.TestCase):
    def test_both_launchers_source_activate(self):
        for script in ("run_grid.sh", "run_local.sh"):
            text = (ROOT / "tools" / script).read_text()
            self.assertIn("source activate.sh", text, script)

    def test_launchers_never_call_a_bare_python(self):
        """A bare `python` would take whatever PATH happens to hold -- on this
        node, the system 3.9. Every call goes through the resolved path."""
        for script in ("run_grid.sh", "run_local.sh"):
            text = (ROOT / "tools" / script).read_text()
            body = "\n".join(ln for ln in text.splitlines()
                             if ln.strip() and not ln.lstrip().startswith("#"))
            self.assertNotIn(" python ", body, script)
            self.assertNotIn("exec python", body, script)
            self.assertIn('"$AUTORESEARCH_PYTHON"', body, script)

    def test_launchers_no_longer_activate_a_venv(self):
        for script in ("run_grid.sh", "run_local.sh"):
            text = (ROOT / "tools" / script).read_text()
            self.assertNotIn(".venv/bin/activate", text, script)


class TestPickerFollowsTheCaller(unittest.TestCase):
    """The switch's quietest failure: launchers move to the published env
    while the GP picker keeps shelling a repo-relative `.venv`, so the BO
    math runs on a different torch than everything it was verified with."""

    def _runtime_value(self, env_extra):
        env = dict(os.environ, AUTORESEARCH_MODE="foilspf")
        env.pop("AUTORESEARCH_BOTORCH_VENV", None)
        env.update(env_extra)
        env["PYTHONPATH"] = ""
        p = subprocess.run(
            [sys.executable, "-c",
             "import sys;sys.path.insert(0,'core');import runtime;"
             "print(runtime.BOTORCH_VENV_PY)"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_defaults_to_the_running_interpreter(self):
        self.assertEqual(self._runtime_value({}), sys.executable)

    def test_ab_seam_still_names_a_repo_relative_venv(self):
        """Keep the two-build A/B possible -- it is how a torch-version
        difference in the picker gets measured."""
        self.assertEqual(self._runtime_value({"AUTORESEARCH_BOTORCH_VENV": ".venv"}),
                         str(ROOT / ".venv" / "bin" / "python"))


if __name__ == "__main__":
    unittest.main()
