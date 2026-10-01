"""The study registry (core/modes.py): which study files load into
modes.STUDIES, from where, and the batch pickers declared beside them.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import modes  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_the_live_studies_are_the_seven_engine_twins(self):
        import modes
        live = {n for n in modes.STUDIES if not n.startswith("_")}
        self.assertTrue({"foilsflash_ax", "foilspf_ax", "foilspf2k_ax",
                         "foilspfbp_ax", "foilspfbpx_ax", "foilspfbpz_ax",
                         "foilspfbw_ax"} <= live)
        self.assertFalse({"foilsflash", "foilspf", "foilspf2k", "foilspfbp",
                          "foilspfbpx", "foilspfbpz", "foilspfbw"} & live,
                         "the originals are archived, not loaded")

    def test_the_pickers(self):
        self.assertEqual(modes.PICKER_CHOICES,
                         ("qnehvi", "qlnei", "budget_sob", "hybrid"))
        self.assertIn(modes.DEFAULT_PICKER, modes.PICKER_CHOICES)


class TestArchiveIsPresentAndUnloaded(unittest.TestCase):
    """Archive guard (Phase C3 review): the eleven archived study files and
    the seven original foilspf boards must still exist on disk -- archived,
    not deleted -- and none of the archived names may leak into
    modes.STUDIES (mode_specs/README.md, "archive/")."""

    ORIGINAL_FOILSPF = ("foilsflash", "foilspf", "foilspf2k", "foilspfbp",
                        "foilspfbpx", "foilspfbpz", "foilspfbw")
    SCHEMA1 = ("ipa625", "ipafix", "ipaovr", "nominal")

    def test_the_eleven_archived_files_exist(self):
        archive_dir = modes.MODES_DIR / "archive"
        for name in self.ORIGINAL_FOILSPF + self.SCHEMA1:
            with self.subTest(name=name):
                self.assertTrue((archive_dir / f"{name}.json").exists(),
                                f"missing {archive_dir / (name + '.json')}")

    def test_the_seven_original_boards_still_exist(self):
        boards = modes.MODES_DIR.parent / "leaderboards"
        for name in self.ORIGINAL_FOILSPF:
            with self.subTest(name=name):
                path = boards / f"leaderboard_bo_{name}.tsv"
                self.assertTrue(path.exists(), f"missing {path}")

    def test_no_archived_name_is_loaded(self):
        self.assertFalse(
            (set(self.ORIGINAL_FOILSPF) | set(self.SCHEMA1))
            & set(modes.STUDIES))


class TestStudyDirectoryWiring(unittest.TestCase):
    """F8: the lines that ARE the study-directory feature had zero coverage.

    Deleting the `STUDIES = load_study_dirs(MODES_DIR, ...)` line of
    core/modes.py used to leave the whole suite green -- verified by
    mutation. Every other test registers its study by hand into
    modes.STUDIES and so bypasses directory discovery.

    Neither test here writes into the real mode_specs/ (a concurrently
    importing campaign child would load a probe dropped there). The primary
    directory is proven by comparing a fresh process's registry to the
    files in mode_specs/; "drop a study file in a directory, get a study"
    is proven through $AUTORESEARCH_STUDY_PATH with a temp directory,
    checking that the study is discovered into STUDIES and renders its
    geometry.
    """

    def _fresh_process(self, script, study_path=None, cwd=None):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("AUTORESEARCH_STUDY_PATH", None)
        if study_path is not None:
            env["AUTORESEARCH_STUDY_PATH"] = study_path
        r = subprocess.run([sys.executable, "-c", script],
                           cwd=str(cwd or ROOT),
                           capture_output=True, text=True, env=env,
                           timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_primary_directory_is_the_repo_mode_specs(self):
        """Run from core/ with PYTHONPATH popped, so core/ is the only
        project directory on sys.path: a bare `import modes` must work
        there, not only the package-qualified `core.modes`."""
        self.assertEqual(modes.MODES_DIR, ROOT / "mode_specs")
        script = (
            "import json\n"
            "import modes\n"
            "print(json.dumps([str(modes.MODES_DIR), sorted(modes.STUDIES)]))\n"
        )
        modes_dir, studies = json.loads(
            self._fresh_process(script, cwd=ROOT / "core").splitlines()[-1])
        want = sorted(p.stem for p in (ROOT / "mode_specs").glob("*.json"))
        self.assertEqual(Path(modes_dir), ROOT / "mode_specs")
        self.assertEqual(studies, want)
        # C2b: each foilspf study has an engine twin <name>_ax; since C3 the
        # twins are the foilspf studies shipped (the originals are archived).
        # ce_chain is the one zero-knob production-chain study.
        self.assertTrue(all(n.endswith("_ax") for n in want if n != "ce_chain"),
                        want)

    def test_a_study_on_the_study_path_is_loaded(self):
        name = "wiringprobe" + uuid.uuid4().hex[:8]
        doc = json.loads((ROOT / "mode_specs" / "foilsflash_ax.json")
                         .read_text())
        doc["name"] = name
        # Its own leaderboard basename: the loader rejects a study that
        # claims one already owned by another study.
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_bo_{name}.tsv"
        script = (
            "import sys\n"
            "sys.path.insert(0, 'core')\n"
            "import modes\n"
            f"n = {name!r}\n"
            "print('STUDY_DISCOVERED', n in modes.STUDIES)\n"
            "s = modes.STUDIES.get(n)\n"
            "print('GEOM_RENDERS', bool(s) and 'stoppingTarget.radii' in "
            "s.geom.render([120.0, 130.0, 0.1, 0.2, 0.3, 0.4]))\n"
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / f"{name}.json").write_text(json.dumps(doc))
            out = self._fresh_process(script, study_path=str(Path(td).resolve()))
        self.assertEqual(out.splitlines(),
                         ["STUDY_DISCOVERED True", "GEOM_RENDERS True"], out)

    # Specs deliberately shipped in the real mode_specs/ directory. Every file
    # here is loaded by EVERY process that imports modes, so the point of the
    # test below is that nothing arrives unnoticed -- adding a line here is a
    # conscious act, which is exactly the review checkpoint we want.
    SHIPPED_SPECS = {"ce_chain.json", "foilsflash_ax.json", "foilspf_ax.json",
                     "foilspf2k_ax.json", "foilspfbp_ax.json",
                     "foilspfbw_ax.json", "foilspfbpx_ax.json",
                     "foilspfbpz_ax.json"}

    def test_mode_specs_directory_holds_only_the_readme(self):
        """The real directory holds the README plus exactly the shipped specs:
        a STRAY *.json checked in here would be loaded by every process that
        imports modes.

        Kept as an explicit allow-list rather than relaxed to "any *.json":
        the whole value of this guard is that an unintended file fails
        loudly, and `assertEqual` against a named set preserves that while a
        laxer check would not.

        `archive/` is excluded deliberately: nothing loads it. It holds the
        retired one-shot A/B specs and, since Phase C3, the seven original
        foilspf studies, whose boards stay in leaderboards/."""
        stray = sorted(p.name for p in (ROOT / "mode_specs").iterdir()
                       if p.name != "archive")
        self.assertEqual(stray, sorted({"README.md"} | self.SHIPPED_SPECS))


class TestReadme(unittest.TestCase):
    def test_readme_documents_the_int_fmt_limitation(self):
        """F14: _validate_fmt probes with a float, so "{:d}" is rejected at
        load even for a knob with "type": "int" -- authors must write
        "{:.0f}". Loud, not silent; documented rather than changed (a {:d}
        fmt genuinely breaks on the float path)."""
        readme = (ROOT / "mode_specs" / "README.md").read_text()
        self.assertIn("{:d}", readme)
        self.assertIn("{:.0f}", readme)


class TestSingleModuleCopy(unittest.TestCase):
    """Only ONE copy of each of these modules may be live in the suite process.

    `core/modes.py` and its sibling core/geom_template.py are importable two
    ways -- bare (core/ on sys.path, which is how this suite imports) and
    qualified `core.<module>`. If both load, Python builds two non-identical
    copies of the same class (GeomTemplate, ...) and any isinstance check or
    `is`-identity across them silently returns False. Every test file here
    must therefore use the bare convention. A qualified `core.study` import
    trips these too: it pulls in `core.geom_template`.
    """
    def test_no_qualified_core_module_is_loaded(self):
        for bare in ("modes", "geom_template"):
            with self.subTest(module=bare):
                self.assertNotIn(
                    f"core.{bare}", sys.modules,
                    f"core.{bare} is loaded alongside bare `{bare}`, which "
                    f"creates two non-identical copies of its classes. Some "
                    f"test module imports `from core import {bare}` (or "
                    f"`from core.{bare} import ...`) -- switch it to the "
                    f"sys.path.insert + bare `import {bare}` convention used "
                    f"by tests/test_modes.py.")


class TestStaleModeEnv(unittest.TestCase):
    def test_a_stale_autoresearch_mode_is_ignored(self):
        """AUTORESEARCH_MODE was the pipeline's mode switch. After Phase C3
        nothing reads it: a leftover export in the operator's shell must
        not break an import, whatever it names."""
        env = dict(os.environ, AUTORESEARCH_MODE="no_such_mode_c3",
                   PYTHONPATH="")
        code = ("import sys; sys.path.insert(0, 'core'); sys.path.insert(0, 'graph'); "
                "import modes, botorch_predict, run, closed_loop; print('ok')")
        p = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertIn("ok", p.stdout)


if __name__ == "__main__":
    unittest.main()
