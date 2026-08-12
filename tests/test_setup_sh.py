"""setup.sh — the operator-facing skin over core/paths.py.

Mirrors muse's verbs: --status is `muse status`, --backing is
`muse backing`. Executed as a subprocess so we test the real script.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "setup.sh"


def run(*args, env=None):
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    if env:
        e.update(env)
    return subprocess.run([str(SETUP), *args], capture_output=True,
                          text=True, env=e, cwd=str(ROOT))


class TestSetupSh(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(SETUP.is_file())
        self.assertTrue(os.access(SETUP, os.X_OK))

    def test_status_prints_all_four_roots(self):
        r = run("--status")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        for key in ("REPO_ROOT", "DATA_ROOT", "ARTIFACT_ROOT", "BACKING"):
            self.assertIn(key, r.stdout)

    def test_status_reports_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            r = run("--status", env={"AUTORESEARCH_DATA_ROOT": td})
            self.assertIn(td, r.stdout)
            self.assertIn("env", r.stdout)

    def test_unknown_flag_exits_nonzero_with_usage(self):
        r = run("--bogus")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage", (r.stdout + r.stderr).lower())

    def test_backing_creates_and_removes_the_symlink(self):
        link = ROOT / "backing"
        self.assertFalse(link.exists() or link.is_symlink(),
                         msg="a backing link already exists; refusing to "
                             "clobber the operator's own link")
        with tempfile.TemporaryDirectory() as td:
            try:
                r = run("--backing", td)
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.path.realpath(link),
                                 os.path.realpath(td))
            finally:
                run("--backing", "-r")
        self.assertFalse(link.is_symlink())

    def test_backing_at_a_nonexistent_path_is_refused(self):
        r = run("--backing", "/no/such/dir")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((ROOT / "backing").is_symlink())

    def test_status_reports_the_venv(self):
        self.assertIn("VENV", run("--status").stdout)

    def test_venv_refuses_to_clobber_an_existing_one(self):
        # The repo under test has its own .venv; a silent `ln -sfn` over a
        # build the operator spent twenty minutes on is the failure to avoid.
        if not (ROOT / ".venv").exists():
            self.skipTest("no .venv in this checkout to protect")
        r = run("--venv", "/tmp")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)

    def test_venv_with_no_path_links_the_site_venv(self):
        # Exercised against a fake site venv, so the assertion does not
        # depend on any particular operator's area existing.
        with tempfile.TemporaryDirectory() as td:
            repo, site = Path(td) / "repo", Path(td) / "sitevenv"
            repo.mkdir()
            (site / "bin").mkdir(parents=True)
            (site / "bin" / "python").write_text("#!/bin/sh\n")
            (site / "bin" / "python").chmod(0o755)
            (repo / "setup.sh").write_bytes(SETUP.read_bytes())
            (repo / "setup.sh").chmod(0o755)

            e = dict(os.environ)
            e.pop("PYTHONPATH", None)
            e["AUTORESEARCH_SITE_VENV"] = str(site)
            r = subprocess.run([str(repo / "setup.sh"), "--venv"],
                               capture_output=True, text=True, env=e,
                               cwd=str(repo))
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(os.path.realpath(repo / ".venv"),
                             os.path.realpath(site))

            r = subprocess.run([str(repo / "setup.sh"), "--venv", "-r"],
                               capture_output=True, text=True, env=e,
                               cwd=str(repo))
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertFalse((repo / ".venv").is_symlink())

    def test_venv_rejects_a_directory_that_is_not_a_venv(self):
        with tempfile.TemporaryDirectory() as td:
            repo, notvenv = Path(td) / "repo", Path(td) / "notvenv"
            repo.mkdir()
            notvenv.mkdir()
            (repo / "setup.sh").write_bytes(SETUP.read_bytes())
            (repo / "setup.sh").chmod(0o755)
            e = dict(os.environ)
            e.pop("PYTHONPATH", None)
            r = subprocess.run([str(repo / "setup.sh"), "--venv", str(notvenv)],
                               capture_output=True, text=True, env=e,
                               cwd=str(repo))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("bin/python", r.stderr)
            self.assertFalse((repo / ".venv").is_symlink())

    def test_sourcing_does_not_leak_shell_options(self):
        # `set -u`/`pipefail` applied while sourced would persist in the
        # operator's interactive shell for the rest of the session.
        script = ("shopt -po nounset pipefail; "
                  "source ./setup.sh >/dev/null 2>&1; "
                  "echo ---; "
                  "shopt -po nounset pipefail")
        e = dict(os.environ)
        e.pop("PYTHONPATH", None)
        r = subprocess.run(["bash", "-c", script], cwd=str(ROOT),
                           capture_output=True, text=True, env=e)
        before, after = r.stdout.split("---")
        self.assertEqual(before.split(), after.split(),
                         msg="sourcing setup.sh changed the caller's shell options")


if __name__ == "__main__":
    unittest.main()
