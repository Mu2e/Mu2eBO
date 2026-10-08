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

# The studies deliberately shipped in the real mode_specs/ directory. Every
# file there is loaded by EVERY process that imports modes, so
# TestStudyDirectoryWiring pins the directory to exactly these -- adding a
# name here is a conscious act, which is exactly the review checkpoint we
# want.
SHIPPED = ("ce_chain", "foilsflash_ax", "foilspf_nominal", "foilspfbpz_ax",
           "ptg4bl")
# Retired names that must never load (see mode_specs/README.md):
# the seven original foilspf studies (their files were deleted on
# 2026-10-08; git history keeps them) and the four schema-1 files in
# mode_specs/archive/.
RETIRED = ("foilsflash", "foilspf", "foilspf2k", "foilspfbp", "foilspfbpx",
           "foilspfbpz", "foilspfbw", "ipa625", "ipafix", "ipaovr", "nominal")


class TestRegistry(unittest.TestCase):
    def test_the_shipped_studies_load_and_the_retired_ones_do_not(self):
        live = {n for n in modes.STUDIES if not n.startswith("_")}
        self.assertTrue(set(SHIPPED) <= live, live)
        self.assertFalse(set(RETIRED) & set(modes.STUDIES),
                         "a retired study is loaded")

    def test_the_pickers(self):
        self.assertEqual(modes.PICKER_CHOICES,
                         ("qnehvi", "qlnei", "budget_sob", "hybrid"))
        self.assertIn(modes.DEFAULT_PICKER, modes.PICKER_CHOICES)


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
        there, as every runner imports it."""
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

    def test_mode_specs_directory_holds_only_the_readme(self):
        """The real directory holds the README plus exactly the SHIPPED
        specs: a STRAY *.json checked in here would be loaded by every
        process that imports modes.

        Kept as an explicit allow-list rather than relaxed to "any *.json":
        the whole value of this guard is that an unintended file fails
        loudly, and `assertEqual` against a named set preserves that while a
        laxer check would not.

        `archive/` is excluded deliberately: nothing loads it. It holds the
        retired one-shot A/B specs."""
        stray = sorted(p.name for p in (ROOT / "mode_specs").iterdir()
                       if p.name != "archive")
        self.assertEqual(stray, sorted(["README.md"]
                                       + [f"{n}.json" for n in SHIPPED]))


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


if __name__ == "__main__":
    unittest.main()
