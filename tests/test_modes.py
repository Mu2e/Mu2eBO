"""Completeness + lockstep tests for the ModeSpec registry (ADR-0002).

These are the tests that turn "MUST stay in lockstep" comments into failures:
a new mode, a moved bound, or a renamed stage now breaks HERE instead of
silently building the wrong geometry on the grid.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402

# The Python-mode names -- frozen here, deliberately NOT derived from
# modes.SPECS. Dropping a real mode_specs/*.json file in (the entire
# point of the json-modes branch) adds a SPECS entry; tests that assert
# facts about "the Python modes" must key off this frozen set, not "every key
# in SPECS", or they break the moment the feature they exist to enable is
# first used. See I6 in the json-configurable-modes final review.
# Empty since 2026-08-08: the last five Python-mode adapters (foils, foilsf,
# foilsg, prodtarget, prodtarget6d) were archived that day -- see
# docs/superpowers/specs/2026-08-08-leaderboard-module-design.md. Every mode
# is JSON-defined now (JsonMode); test_python_mode_names_matches_the_live_registry
# below derives the truth from the registry so a stale name cannot linger
# unnoticed if a Python mode adapter is ever reintroduced.
PYTHON_MODE_NAMES = frozenset()


class TestRegistryCompleteness(unittest.TestCase):
    def test_keys_match_driver_modes(self):
        import bo_driver as bo
        self.assertEqual(set(modes.SPECS), set(bo.MODES),
                         "modes.SPECS and driver MODES diverged")

    def test_name_field_matches_key(self):
        for name, spec in modes.SPECS.items():
            self.assertEqual(spec.name, name)

    def test_python_mode_names_matches_the_live_registry(self):
        """PYTHON_MODE_NAMES drives which modes are asserted to carry no JSON
        fields. Derive the truth from the registry rather than trusting the
        hand-maintained set: when foilsflash was retired to JSON (2026-07-26)
        a stale entry here turned into a confusing failure in a test that was
        not about retirement at all."""
        import bo_driver as bo
        live = {n for n, m in bo.MODES.items()
                if not isinstance(m, bo.JsonMode)}
        self.assertEqual(set(PYTHON_MODE_NAMES), live,
                         "PYTHON_MODE_NAMES is stale: a mode was retired to "
                         "JSON (or added) without updating this set")

    def test_every_fact_populated(self):
        for name, spec in modes.SPECS.items():
            self.assertTrue(spec.musing.startswith("/"), name)
            self.assertTrue(spec.grid_tarball.endswith(".tar.bz2"), name)
            self.assertGreater(len(spec.grid_stages), 0, name)

    def test_obs_noise_declared_per_family(self):
        # The foils/flash family has replicate-measured sigma and MUST pin
        # it (free MLL noise ranked the best-ever eval 16th of 324).
        # "foils"/"foilsf"/"foilsg" (the original Python-mode family) and
        # the ProdTarget family (which declared obs_noise=None EXPLICITLY,
        # since its GP axis 1 is a raw negated value whose units depend on
        # which fallback fired) were both archived 2026-08-08; foilsflash is
        # the sole surviving anchor of this pin.
        noise = modes.SPECS["foilsflash"].obs_noise
        self.assertIsNotNone(noise)
        self.assertEqual(len(noise), 2)
        self.assertTrue(all(v > 0 for v in noise))


class TestBoundsLockstep(unittest.TestCase):
    def test_build_space_matches_spec(self):
        # THE lockstep test: build_space pairs the driver's KNOB_NAMES with
        # the registry bounds and must raise loudly on a length mismatch;
        # the SpaceDim rows it returns must mirror the spec exactly (the
        # spec is what the botorch picker and cloud plots read).
        import bo_driver as bo
        for name, spec in modes.SPECS.items():
            dims = bo.MODES[name].build_space()
            lo = tuple(d.low for d in dims)
            hi = tuple(d.high for d in dims)
            intd = tuple(i for i, d in enumerate(dims) if d.is_int)
            self.assertEqual(spec.bounds_lo, lo, name)
            self.assertEqual(spec.bounds_hi, hi, name)
            self.assertEqual(spec.int_dims, intd, name)
            self.assertEqual(tuple(d.name for d in dims),
                             tuple(bo.MODES[name].KNOB_NAMES), name)

    def test_leaderboard_row_roundtrips(self):
        # Leaderboard.append (core/leaderboard.py) writes the header + line;
        # Leaderboard.load must read exactly those columns back. This pins
        # the KNOB_NAMES / header / value-column contract the 2026-07-12
        # driver collapse introduced: a renamed knob column silently broke
        # reading EXISTING rows (now a loud RowParseError/SchemaMismatch
        # instead of a swallowed KeyError -- see
        # wiki/incidents/touched-leaderboard-headerless-history-loss.md).
        # Round-trips build_space midpoints through append/load for every
        # mode, each against its own scratch temp-dir copy (never the real
        # leaderboards/*.tsv -- mode.leaderboard_io() is only consulted for
        # its knob/metric column schema, not written to).
        import tempfile
        import bo_driver as bo
        for name, mode in bo.MODES.items():
            # leaderboard_io() caches onto the shared bo.MODES[name]
            # singleton (same object across every test in this process);
            # drop the cache afterward so a later test that patches the
            # registry and expects a fresh Leaderboard build doesn't
            # silently get this test's cached instance back instead.
            self.addCleanup(setattr, mode, "_lb_cache", None)
            study = modes.STUDIES[name]
            self.assertEqual(mode.leaderboard_io().header(),
                             bo.Leaderboard.for_study(
                                 study, path=mode.leaderboard,
                                 archive_path=None).header(), name)
            x0 = []
            for d in mode.build_space():
                if d.is_int:
                    x0.append(int(round((d.low + d.high) / 2)))
                else:
                    x0.append((d.low + d.high) / 2.0)
            p = bo.Point(cfg="RT01", x=x0,
                         y={study.objectives[0].name: 3.21,
                            study.objectives[1].name: 6.5e-7})
            with tempfile.TemporaryDirectory() as td:
                lb = bo.Leaderboard.for_study(
                    study, path=Path(td) / f"leaderboard_bo_{name}.tsv",
                    archive_path=None)
                lb.append(p, {"alpha": 1.0e5})
                [back] = lb.load()
            self.assertEqual(back.cfg, "RT01", name)
            self.assertEqual(len(back.x), len(x0), name)
            for got, want in zip(back.x, x0):
                self.assertAlmostEqual(float(got), float(want), places=3, msg=name)

    # test_prodtarget_tarball_matches_stage_config removed 2026-08-08:
    # modes._PRODTARGET_TARBALL and pipeline.STAGES["pot_only"] (the two
    # facts it pinned in lockstep) were both deleted along with the
    # harvest-pot-only verb and the ProdTarget family that was their only
    # consumer.


class TestSpotFacts(unittest.TestCase):
    """Load-bearing values pinned individually — the ones with incident
    history or active standards behind them."""

    def test_foilsflash_thickness_floor(self):
        self.assertEqual(modes.SPECS["foilsflash"].bounds_lo[2], 0.002)
        self.assertEqual(modes.SPECS["foilsflash"].bounds_lo[3], 0.002)

    def test_foilsflash_elebeam_standard_100(self):
        self.assertEqual(
            modes.SPECS["foilsflash"].stage_target_overrides["elebeam_flash"], 100)

    def test_foilsflash_presubmit_overlap(self):
        self.assertEqual(modes.SPECS["foilsflash"].presubmit_after,
                         {"mubeam": ("elebeam_flash",)})

    def test_foils_family_needs_holeradii_tarball(self):
        # (ipa — the last non-holeradii CE/calo mode — retired 2026-07-18;
        # its base-tarball regression pin went with it. "foils"/"foilsf"/
        # "foilsg" -- the Python-mode family -- archived 2026-08-08;
        # foilsflash is the sole surviving anchor.)
        self.assertIn("holeradii", modes.SPECS["foilsflash"].grid_tarball)

    # test_prodtarget6d_banner_drift_retired removed 2026-08-08: pinned
    # `modes.SPECS["prodtarget6d"].checks_managed_overlap` as a regression
    # guard against the old hand-listed preflight-mode-tuple omission bug.
    # prodtarget6d itself was archived (Python-mode adapter deleted, no JSON
    # replacement); nothing named "prodtarget6d" is left to omit from a
    # tuple that no longer exists either (checks_managed_overlap is a
    # per-ModeSpec field, not a hand-listed mode-name tuple).


class TestSchemaFields(unittest.TestCase):
    def test_metric_cols_spot_pins(self):
        # "foils" (plain "calo" tail) and "prodtarget" (5-column mu_per_POT
        # tail) were archived 2026-08-08; every surviving mode shares the
        # foilsflash-family "flash_edep" tail, so there is no longer a
        # second shape to contrast against.
        # metric_cols is the study_compat view's column tail; the
        # leaderboard itself reads its columns by name from the Study
        # (core/leaderboard.py Leaderboard.for_study), not from here.
        self.assertEqual(modes.SPECS["foilsflash"].metric_cols,
                         ("sob", "flash_edep", "alpha", "obj"))

    def test_driver_reads_registry(self):
        import bo_driver as bo
        for name, mode in bo.MODES.items():
            self.assertEqual(mode.KNOB_NAMES, modes.SPECS[name].knob_names)
            self.assertEqual(mode.KNOB_FMTS, modes.SPECS[name].knob_fmts)

    # test_leaderboard_io_rejects_non4_metric_tail removed 2026-09-24
    # (generic-study Task 6): a study's leaderboard columns are no longer a
    # fixed four-column tail, so there is no length to reject. Column-name
    # collisions are refused at study load
    # (tests/test_study.py::TestKnobs::test_knob_name_collides_with_column)
    # and the study-derived header/format is pinned by
    # tests/test_leaderboard.py::TestGenericRows.


class TestGeomField(unittest.TestCase):
    # test_python_modes_declare_the_json_fields_as_none removed 2026-08-08:
    # asserted geom/metrics/leaderboard_rel are None and stage_tuning={} for
    # every name in PYTHON_MODE_NAMES. That set is now permanently empty (no
    # Python-mode adapters survive), so the loop body could never execute --
    # a vacuously-passing test is worse than no test.

    def test_the_new_fields_are_required_not_defaulted(self):
        """A missing fact must be a TypeError, never a silent default."""
        import dataclasses
        by_name = {f.name: f for f in dataclasses.fields(modes.ModeSpec)}
        for field in ("geom", "metrics", "leaderboard_rel"):
            self.assertIn(field, by_name)
            self.assertIs(by_name[field].default, dataclasses.MISSING,
                          f"{field} must not have a default")
            self.assertIs(by_name[field].default_factory, dataclasses.MISSING,
                          f"{field} must not have a default_factory")
        with self.assertRaises(TypeError):
            modes.ModeSpec(name="x")  # type: ignore[call-arg]


class TestSubprocessImport(unittest.TestCase):
    def test_imports_with_only_core_on_syspath(self):
        """Verify modes imports cleanly with only core/ on sys.path
        (the production path when bo_driver is invoked as a subprocess).
        TYPE_CHECKING guard ensures this works despite GeomTemplate annotation.
        """
        import subprocess
        core = Path(__file__).resolve().parent.parent / "core"
        # Was: counted the six frozen Python-mode names against modes.SPECS
        # (all archived 2026-08-08). "foilsflash" is the stable, long-lived
        # JSON mode (mode_specs/foilsflash.json) -- a fixed anchor to check
        # instead, unlike the shipped-specs set as a whole (IPA A/B clones
        # and similar throwaway modes come and go, see
        # TestModeSpecsDirectoryWiring.SHIPPED_SPECS).
        script = "import modes; print('foilsflash' in modes.SPECS)"
        r = subprocess.run([sys.executable, "-c", script],
                           cwd=str(core), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"import failed: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "True",
                         "modes.SPECS must expose the foilsflash JSON spec")


class TestModeSpecsDirectoryWiring(unittest.TestCase):
    """F8: the lines that ARE the study-directory feature had zero coverage.

    Deleting the `STUDIES = load_study_dirs(MODES_DIR, ...)` /
    `SPECS = {...}` tail of core/modes.py, or the
    `MODES[_name] = JsonMode(_name)` loop in core/bo_driver.py, used to leave
    the whole suite green -- verified by mutation, twice. Every other test
    registers its study by hand into modes.STUDIES/SPECS and so bypasses
    directory discovery.

    Neither test here writes into the real mode_specs/ (a concurrently
    importing campaign child would load a probe dropped there). The primary
    directory is proven by comparing a fresh process's registry to the
    files in mode_specs/; "drop a study file in a directory, get a runnable
    mode" is proven through $AUTORESEARCH_STUDY_PATH with a temp directory,
    checking all three links of the chain: the study is discovered into
    STUDIES and SPECS, a JsonMode is registered under that name in the
    driver, and it renders geometry.
    """

    ROOT = Path(__file__).resolve().parent.parent

    def _fresh_process(self, script, study_path=None):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("AUTORESEARCH_STUDY_PATH", None)
        if study_path is not None:
            env["AUTORESEARCH_STUDY_PATH"] = study_path
        r = subprocess.run([sys.executable, "-c", script], cwd=str(self.ROOT),
                           capture_output=True, text=True, env=env,
                           timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_primary_directory_is_the_repo_mode_specs(self):
        self.assertEqual(modes.MODES_DIR, self.ROOT / "mode_specs")
        script = (
            "import json, sys\n"
            "sys.path.insert(0, 'core')\n"
            "import modes\n"
            "print(json.dumps([str(modes.MODES_DIR), sorted(modes.STUDIES), "
            "sorted(modes.SPECS)]))\n"
        )
        modes_dir, studies, specs = json.loads(
            self._fresh_process(script).splitlines()[-1])
        want = sorted(p.stem for p in (self.ROOT / "mode_specs").glob("*.json"))
        self.assertEqual(Path(modes_dir), self.ROOT / "mode_specs")
        self.assertEqual(studies, want)
        self.assertEqual(specs, want)

    def test_a_study_on_the_study_path_becomes_a_runnable_mode(self):
        name = "wiringprobe" + uuid.uuid4().hex[:8]
        doc = json.loads((Path(__file__).parent / "fixtures" / "modes"
                          / "template.json").read_text())
        doc["name"] = name
        # Its own leaderboard basename: the loader rejects a study that
        # claims one already owned by another study.
        doc["leaderboard"]["file"] = f"leaderboards/leaderboard_bo_{name}.tsv"
        script = (
            "import sys\n"
            "sys.path.insert(0, 'core')\n"
            "import modes, bo_driver\n"
            f"n = {name!r}\n"
            "print('STUDY_DISCOVERED', n in modes.STUDIES)\n"
            "print('SPEC_DISCOVERED', n in modes.SPECS)\n"
            "m = bo_driver.MODES.get(n)\n"
            "print('DRIVER_CLASS', type(m).__name__)\n"
            "print('GEOM_RENDERS', bool(m) and 'stoppingTarget.radii' in "
            "m._geom_text([120.0, 130.0, 0.1, 0.2]))\n"
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / f"{name}.json").write_text(json.dumps(doc))
            out = self._fresh_process(script, study_path=str(Path(td).resolve()))
        self.assertEqual(out.splitlines(),
                         ["STUDY_DISCOVERED True",
                          "SPEC_DISCOVERED True",
                          "DRIVER_CLASS JsonMode",
                          "GEOM_RENDERS True"], out)

    # Specs deliberately shipped in the real mode_specs/ directory. Every file
    # here is loaded by EVERY process that imports modes, so the point of the
    # test below is that nothing arrives unnoticed -- adding a line here is a
    # conscious act, which is exactly the review checkpoint we want.
    SHIPPED_SPECS = {"foilsflash.json", "foilspf.json", "foilspf2k.json",
                     "foilspfbp.json", "foilspfbw.json", "foilspfbpx.json",
                     "foilspfbpz.json"}

    def test_mode_specs_directory_holds_only_the_readme(self):
        """The real directory holds the README plus exactly the shipped specs:
        a STRAY *.json checked in here would be loaded by every process that
        imports modes.

        Was "only the README" until foilsflash became JSON-defined
        (2026-07-26). Kept as an explicit allow-list rather than relaxed to
        "any *.json": the whole value of this guard is that an unintended file
        fails loudly, and `assertEqual` against a named set preserves that
        while a laxer check would not.

        No test writes into this directory any more (the wiring tests above
        use a temp dir on $AUTORESEARCH_STUDY_PATH), so the old
        `wiringprobe*.json` exclusion is gone: any stray file fails here.

        `archive/` is excluded deliberately: it holds retired one-shot A/B
        specs whose leaderboards are still readable (see Task 5)."""
        root = Path(__file__).resolve().parent.parent
        stray = sorted(p.name for p in (root / "mode_specs").iterdir()
                       if p.name != "archive")
        self.assertEqual(stray, sorted({"README.md"} | self.SHIPPED_SPECS))

    def test_every_shipped_spec_is_a_registered_json_mode(self):
        """A file in mode_specs/ that never became a live mode means the
        loader silently skipped it."""
        import bo_driver as bo
        for fname in self.SHIPPED_SPECS:
            name = fname[:-len(".json")]
            self.assertIn(name, modes.SPECS, f"{fname} did not reach SPECS")
            self.assertIsInstance(bo.MODES[name], bo.JsonMode)


class TestCopyPasteTemplate(unittest.TestCase):
    """F4 (second half), ported from the old spec loader's test module
    (deleted with the schema-2 switch):
    mode_specs/README.md once advertised tests/fixtures/modes/foilsflash.json
    as the thing to copy -- and that file declares the LIVE foilsflash
    leaderboard. Copy it, miss the leaderboard line (it looks plausible) and
    the new line appends into a live TSV. The loader rejects a shared
    leaderboard outright, but what the README hands an author must not be a
    live-leaderboard file in the first place.
    """

    ROOT = Path(__file__).resolve().parent.parent
    TEMPLATE = Path(__file__).parent / "fixtures" / "modes" / "template.json"

    def readme(self) -> str:
        return (self.ROOT / "mode_specs" / "README.md").read_text()

    def test_readme_advertises_the_template(self):
        self.assertIn("tests/fixtures/modes/template.json", self.readme())

    def test_template_loads(self):
        """Through the same study -> ModeSpec path core/modes.py uses, so a
        copy dropped into mode_specs/ becomes a runnable mode."""
        from study_compat import load_modespec
        spec = load_modespec(self.TEMPLATE)
        self.assertEqual(spec.name, "template")
        self.assertIsNotNone(spec.geom)
        self.assertTrue(spec.geom.render([v for v in spec.bounds_lo]))

    def test_template_leaderboard_is_not_a_live_one(self):
        # By basename: the live board tree is flat (paths.leaderboard_live),
        # so a template sharing only a basename would still write a live TSV.
        from study import load_study_file
        board = Path(load_study_file(self.TEMPLATE).leaderboard_rel).name
        live = {Path(s.leaderboard_rel).name for s in modes.STUDIES.values()}
        self.assertNotIn(board, live)

    def test_readme_documents_the_int_fmt_limitation(self):
        """F14: _validate_fmt probes with a float, so "{:d}" is rejected at
        load even for a knob with "type": "int" -- authors must write
        "{:.0f}". Loud, not silent; documented rather than changed (a {:d}
        fmt genuinely breaks on the float path)."""
        readme = self.readme()
        self.assertIn("{:d}", readme)
        self.assertIn("{:.0f}", readme)


class TestSingleModeSpecClass(unittest.TestCase):
    """Only ONE copy of each of these modules may be live in the suite process.

    Ported from the old spec loader's test module (deleted with the
    schema-2 switch): the invariant is about import convention, not the
    loader. `core/modes.py` (and its siblings
    core/geom_template.py, core/bo_driver.py) are importable two ways --
    bare (core/ on sys.path, which is how bo_driver.py runs as a subprocess
    and how this suite imports) and qualified `core.<module>`. If both load,
    Python builds two non-identical copies of the same class (ModeSpec,
    GeomTemplate, ...) and any isinstance check or `is`-identity across them
    silently returns False. Every test file here must therefore use the bare
    convention. tests/test_geom_template.py was the gap that motivated the
    geom_template/bo_driver entries below (I7 in the json-configurable-modes
    final review) -- it used qualified `core.geom_template`/`core.bo_driver`
    imports until fixed. A qualified `core.study`/`core.study_compat` import
    trips these too: both pull in `core.geom_template`, and
    study_compat.modespec_from_study imports `core.modes` when called.
    """
    def test_qualified_modes_module_is_not_loaded(self):
        self.assertNotIn(
            "core.modes", sys.modules,
            "core.modes is loaded alongside bare `modes`, which creates two "
            "non-identical ModeSpec classes. Some test module is importing "
            "`from core import modes` -- switch it to the sys.path.insert + "
            "bare `import modes` convention used by tests/test_modes.py.")

    def test_qualified_geom_template_module_is_not_loaded(self):
        self.assertNotIn(
            "core.geom_template", sys.modules,
            "core.geom_template is loaded alongside bare `geom_template`, "
            "which creates two non-identical GeomTemplate/ExprError classes. "
            "Some test module is importing `from core.geom_template import "
            "...` -- switch it to the sys.path.insert + bare `import "
            "geom_template` convention used by tests/test_geom_template.py.")

    def test_qualified_bo_driver_module_is_not_loaded(self):
        self.assertNotIn(
            "core.bo_driver", sys.modules,
            "core.bo_driver is loaded alongside bare `bo_driver`, which "
            "creates two non-identical MODES/ModeSpec-consuming classes. "
            "Some test module is importing `from core.bo_driver import "
            "...` -- switch it to the sys.path.insert + bare `import "
            "bo_driver` convention used by tests/test_json_mode.py.")


if __name__ == "__main__":
    unittest.main()


class TestModeStamping(unittest.TestCase):
    """Finding I1 (final review): nothing stamped AUTORESEARCH_MODE from
    --mode after graph/presniff.py was deleted in 265c642, so with
    `--mode foilspfbw` on the command line runtime._SPEC.name resolved to
    "foilspf" and pipeline.MODE to "foilsflash" -- neither the requested
    mode, and which you got depended on import order inside graph/build.py.

    Untestable in-process: both modules resolve their mode at IMPORT time,
    and the suite has already imported them under tests/__init__.py's stamp.
    The end-to-end case therefore spawns a fresh interpreter.
    """

    ROOT = Path(__file__).resolve().parent.parent

    def test_stamps_space_separated_form(self):
        env = {}
        with mock.patch.dict(modes.os.environ, env, clear=False):
            got = modes.stamp_mode_from_argv(["--mode", "foilspfbw", "--q", "2"])
            self.assertEqual(got, "foilspfbw")
            self.assertEqual(modes.os.environ["AUTORESEARCH_MODE"], "foilspfbw")

    def test_stamps_equals_form(self):
        with mock.patch.dict(modes.os.environ, {}, clear=False):
            self.assertEqual(modes.stamp_mode_from_argv(["--mode=foilspf2k"]),
                             "foilspf2k")

    def test_unknown_mode_falls_through_and_is_never_stamped_as_such(self):
        """Stamping a typo would turn argparse's "invalid choice" message
        into a bare KeyError traceback from `from runtime import ...`. It
        falls through to the env / DEFAULT_MODE instead, and
        assert_mode_stamped reports the bad name properly."""
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "foilspfbw"}, clear=False):
            self.assertEqual(modes.stamp_mode_from_argv(["--mode", "nope"]),
                             "foilspfbw")
            self.assertEqual(modes.os.environ["AUTORESEARCH_MODE"], "foilspfbw")

    def test_no_mode_flag_keeps_an_already_set_env(self):
        """Precedence rung 2: AUTORESEARCH_MODE is the supported way to
        pick a mode without the flag, so the stamp must not clobber it --
        overwriting an operator's explicit export with DEFAULT_MODE would be
        its own silent substitution."""
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "foilspfbw"}, clear=False):
            self.assertEqual(modes.stamp_mode_from_argv(["--q", "2"]),
                             "foilspfbw")
            self.assertEqual(modes.os.environ["AUTORESEARCH_MODE"], "foilspfbw")

    def test_no_mode_flag_and_no_env_stamps_the_registry_default(self):
        """Precedence rung 3, and the fix for the round-2 defect: it must
        STAMP, not merely return. Returning without stamping left every
        module-level reader to apply its own fallback, and they disagreed."""
        env = dict(modes.os.environ)
        env.pop("AUTORESEARCH_MODE", None)
        with mock.patch.dict(modes.os.environ, env, clear=True):
            self.assertEqual(modes.stamp_mode_from_argv([]),
                             modes.DEFAULT_MODE)
            self.assertEqual(modes.os.environ["AUTORESEARCH_MODE"],
                             modes.DEFAULT_MODE)

    def test_explicit_mode_beats_an_already_set_env(self):
        """Precedence rung 1."""
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "foilsflash"}, clear=False):
            self.assertEqual(modes.stamp_mode_from_argv(["--mode", "foilspf2k"]),
                             "foilspf2k")

    def test_assert_mode_stamped_passes_when_all_agree(self):
        import pipeline
        import runtime
        modes.assert_mode_stamped(runtime._SPEC.name)
        self.assertEqual(runtime._SPEC.name, pipeline.MODE)

    def test_assert_mode_stamped_names_an_unknown_mode_as_such(self):
        """graph/run.py's --mode has no argparse choices, so a typo lands in
        the assertion; it must not be reported as an import-order problem."""
        with self.assertRaises(SystemExit) as cm:
            modes.assert_mode_stamped("nosuchmode")
        self.assertIn("unknown --mode 'nosuchmode'", str(cm.exception))
        self.assertIn("foilspf", str(cm.exception))

    def test_assert_mode_stamped_dies_on_disagreement(self):
        import runtime
        other = next(m for m in modes.SPECS if m != runtime._SPEC.name)
        with self.assertRaises(SystemExit) as cm:
            modes.assert_mode_stamped(other)
        msg = str(cm.exception)
        for frag in ("--mode", "AUTORESEARCH_MODE", "runtime._SPEC.name",
                     "pipeline.MODE", other):
            self.assertIn(frag, msg)

    def test_stamp_makes_runtime_and_pipeline_agree_in_a_fresh_process(self):
        """The regression itself, end to end: stamp then import, and both
        mode-keyed modules resolve to the CLI's mode."""
        script = (
            "import sys, os\n"
            "sys.argv = ['run.py', '--mode', 'foilspfbw']\n"
            f"sys.path[:0] = [{str(self.ROOT / 'graph')!r}, "
            f"{str(self.ROOT / 'core')!r}]\n"
            "import modes\n"
            "modes.stamp_mode_from_argv()\n"
            "import build, runtime, pipeline\n"
            "print(os.environ['AUTORESEARCH_MODE'], runtime._SPEC.name, "
            "pipeline.MODE)\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("AUTORESEARCH_MODE", None)
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           capture_output=True, text=True,
                           cwd=str(self.ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertEqual(r.stdout.split()[-3:],
                         ["foilspfbw", "foilspfbw", "foilspfbw"])

    # --- entrypoint / module-scope-env-reader reachability -----------------
    #
    # The invariant is "no entrypoint reaches a module-scope reader of
    # AUTORESEARCH_MODE before stamping it", NOT "graph/run.py and
    # graph/closed_loop.py each contain a `from runtime import` line after a
    # stamp line". The literal-two-files version missed a plain `import
    # runtime`, any indirect import (a new module-scope `from X import ...`
    # where X itself imports runtime), and any third entrypoint added later.

    @staticmethod
    def _module_sources(root):
        out = {}
        for d in ("core", "graph"):
            for f in sorted((root / d).glob("*.py")):
                if f.name == "__init__.py":
                    continue
                out[f.stem] = f.read_text()
        return out

    @staticmethod
    def _module_scope_lines(text):
        """Column-0 statements only -- anything indented is inside a def/
        class/if and does not run at import."""
        for line in text.splitlines():
            if not line or line[0].isspace() or line.lstrip().startswith("#"):
                continue
            yield line

    # A module-scope read of the process mode, in either spelling: the raw
    # env var, or the canonical resolver every reader now calls. Keying on
    # the env-var name ALONE silently blinded this detector the moment the
    # readers were routed through modes.resolve_env_mode() -- caught by
    # test_env_reader_detection_finds_the_known_readers, which is exactly
    # what that guard-the-guard is for.
    _READS_MODE_RE = re.compile(r"AUTORESEARCH_MODE|resolve_env_mode\(")

    @classmethod
    def _env_readers(cls, sources):
        """Modules whose IMPORT resolves the process mode, transitively."""
        direct = {
            name for name, text in sources.items()
            if any(cls._READS_MODE_RE.search(ln)
                   for ln in cls._module_scope_lines(text))
        }
        imports = {
            name: {m.group(1) for ln in cls._module_scope_lines(text)
                   for m in [re.match(r"(?:from|import)\s+(\w+)", ln)] if m}
            for name, text in sources.items()
        }
        # `modes` DEFINES resolve_env_mode but only reads the env inside a
        # function body, so it is not itself an import-time reader; excluding
        # it keeps the closure from tainting every module in the tree.
        direct.discard("modes")
        tainted, changed = set(direct), True
        while changed:
            changed = False
            for name, deps in imports.items():
                if name not in tainted and deps & tainted:
                    tainted.add(name)
                    changed = True
        return tainted

    @classmethod
    def _entrypoints(cls, root):
        return sorted(
            f for f in (root / "graph").glob("*.py")
            if '__name__ == "__main__"' in f.read_text()
            and 'add_argument("--mode"' in f.read_text()
        )

    def test_env_reader_detection_finds_the_known_readers(self):
        """Guards the guard: if this stops finding runtime/pipeline the
        reachability test below silently passes on nothing."""
        readers = self._env_readers(self._module_sources(self.ROOT))
        self.assertLessEqual({"runtime", "pipeline", "bo_driver"}, readers)
        # ...and picks up the indirect ones (build imports runtime).
        self.assertIn("build", readers)
        # ...but not modes itself, whose only uses are inside functions.
        self.assertNotIn("modes", readers)

    def test_every_entrypoint_stamps_before_any_module_scope_env_reader(self):
        import re
        eps = self._entrypoints(self.ROOT)
        self.assertTrue(eps, "no --mode entrypoint found under graph/")
        readers = self._env_readers(self._module_sources(self.ROOT))
        for path in eps:
            rel = path.relative_to(self.ROOT)
            with self.subTest(entrypoint=str(rel)):
                self.assertEqual(
                    self._stamp_violations(path.read_text(), readers), [],
                    f"{rel}: see message(s) above")

    # The locator is ^-anchored to the assignment, NOT a bare
    # `stamp_mode_from_argv\(` search over the whole file. A prose mention in
    # a comment ABOVE a bad import would otherwise satisfy the search and
    # make this check pass on a genuinely broken file -- it only failed to
    # do so because the two existing prose mentions happen to lack a
    # trailing "(". Round-3 minor 1.
    _STAMP_RE = re.compile(r"^_MODE = _modes\.stamp_mode_from_argv\(", re.M)

    @classmethod
    def _stamp_violations(cls, text, readers):
        out = []
        stamp = cls._STAMP_RE.search(text)
        if stamp is None:
            return ["takes --mode but never assigns "
                    "_MODE = _modes.stamp_mode_from_argv(...)"]
        for ln in cls._module_scope_lines(text):
            m = re.match(r"(?:from|import)\s+(\w+)", ln)
            if not m or m.group(1) not in readers:
                continue
            if text.index(ln) < stamp.start():
                out.append(f"`{ln.strip()}` imports a module that resolves "
                           f"AUTORESEARCH_MODE at import time, but runs "
                           f"BEFORE stamp_mode_from_argv()")
        return out

    def test_stamp_locator_is_not_comment_defeatable(self):
        """Guard-the-guard, locator axis (round-3 minor 1). A comment
        mentioning the stamp must not stand in for the stamp itself."""
        decoy = ("# NB: this module calls stamp_mode_from_argv() further "
                 "down.\nimport runtime\n"
                 "_MODE = _modes.stamp_mode_from_argv()\n")
        self.assertNotEqual(
            self._stamp_violations(decoy, {"runtime"}), [],
            "a prose mention of stamp_mode_from_argv() satisfied the "
            "locator, so the check passes on a broken file")
        good = ("_MODE = _modes.stamp_mode_from_argv()\nimport runtime\n")
        self.assertEqual(self._stamp_violations(good, {"runtime"}), [])
        missing = "import runtime\n"
        self.assertNotEqual(self._stamp_violations(missing, {"runtime"}), [])

    # --- omitting --mode is a SUPPORTED invocation -------------------------

    def _entrypoint_probe(self, module):
        """Import an entrypoint module (which runs its stamp) with a bare
        argv, then report what the two mode-keyed modules resolved to."""
        script = (
            "import sys, os\n"
            f"sys.argv = ['{module}.py']\n"
            f"sys.path[:0] = [{str(self.ROOT / 'graph')!r}, "
            f"{str(self.ROOT / 'core')!r}]\n"
            f"import {module}\n"
            "import modes, runtime, pipeline\n"
            "modes.assert_mode_stamped(modes.DEFAULT_MODE)\n"
            "print(os.environ.get('AUTORESEARCH_MODE'), runtime._SPEC.name, "
            "pipeline.MODE, modes.DEFAULT_MODE)\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("AUTORESEARCH_MODE", None)
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           capture_output=True, text=True, cwd=str(self.ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout.split()[-4:]

    def test_omitting_mode_starts_cleanly_on_closed_loop(self):
        """Omitting --mode is SUPPORTED (both CLIs declare a default), so it
        must not be a startup FATAL. It was: stamp_mode_from_argv correctly
        stamped nothing, core/runtime.py fell back to "foilspf" and
        core/pipeline.py's own setdefault fell back to "foilsflash" -- two
        different legacy fallbacks -- and assert_mode_stamped read the env
        AFTER the `import pipeline` it itself triggered, so it reported a
        three-way disagreement it had caused, blaming import order for a
        missing flag."""
        env, rt, pl, dflt = self._entrypoint_probe("closed_loop")
        self.assertEqual([env, rt, pl], [dflt, dflt, dflt])

    def test_omitting_mode_starts_cleanly_on_run(self):
        env, rt, pl, dflt = self._entrypoint_probe("run")
        self.assertEqual([env, rt, pl], [dflt, dflt, dflt])

    def test_entrypoints_default_mode_to_the_stamped_value(self):
        """args.mode must BE the resolved mode, not a second constant that
        happens to match it -- otherwise an omitted --mode, a set
        AUTORESEARCH_MODE and the registry default are three chances to
        disagree."""
        import re
        for path in self._entrypoints(self.ROOT):
            rel = path.relative_to(self.ROOT)
            text = path.read_text()
            with self.subTest(entrypoint=str(rel)):
                self.assertIsNotNone(
                    re.search(r"^_MODE = _modes\.stamp_mode_from_argv\(\)",
                              text, re.M),
                    f"{rel}: the stamp's return value is not captured")
                self.assertIsNotNone(
                    re.search(r'add_argument\("--mode",\s*default=_MODE',
                              text),
                    f"{rel}: --mode's argparse default must be the stamped "
                    f"mode")

    # --- a set-but-UNKNOWN AUTORESEARCH_MODE must be LOUD ------------------

    def _bad_env_probe(self, module):
        """Import an entrypoint with AUTORESEARCH_MODE set to a name that is
        not a live spec. Returns (rc, stderr)."""
        script = (
            "import sys\n"
            f"sys.argv = ['{module}.py']\n"
            f"sys.path[:0] = [{str(self.ROOT / 'graph')!r}, "
            f"{str(self.ROOT / 'core')!r}]\n"
            f"import {module}\n"
            "print('STARTED')\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["AUTORESEARCH_MODE"] = "bogusmode"
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           capture_output=True, text=True, cwd=str(self.ROOT))
        return r.returncode, r.stderr, r.stdout

    def test_unknown_env_mode_is_loud_on_closed_loop(self):
        """Round-3 Important: rung 2 read AUTORESEARCH_MODE without checking
        it names a live spec, so an unknown value fell through to
        DEFAULT_MODE and a campaign launched at rc=0 against the wrong
        bounds, geometry and LEADERBOARD. The live names differ by one
        character (foilspf / foilspfbw / foilspfbp / foilspfbpx /
        foilspfbpz), and writing rows into another mode's leaderboard is the
        most expensive silent failure in this system -- it is what the GP
        refits on. --mode nosuchmode was already loud; this closes the
        asymmetry."""
        rc, err, out = self._bad_env_probe("closed_loop")
        self.assertNotEqual(rc, 0, f"started anyway: {out!r}")
        self.assertNotIn("STARTED", out)
        self.assertIn("bogusmode", err)
        self.assertIn("AUTORESEARCH_MODE", err)
        self.assertIn(modes.DEFAULT_MODE, err)  # lists the known modes

    def test_unknown_env_mode_is_loud_on_run(self):
        rc, err, out = self._bad_env_probe("run")
        self.assertNotEqual(rc, 0, f"started anyway: {out!r}")
        self.assertIn("bogusmode", err)

    def test_unknown_env_mode_is_loud_for_a_bare_pipeline_import(self):
        """The two stamping entrypoints were not the only readers: a
        standalone `python core/pipeline.py` resolved the same env var and
        died with a bare KeyError('bogusmode'). Same failure, worse message
        -- so the check lives in the ONE resolver every reader now calls."""
        script = (
            "import sys\n"
            f"sys.path[:0] = [{str(self.ROOT / 'core')!r}]\n"
            "import pipeline\n"
            "print('STARTED')\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["AUTORESEARCH_MODE"] = "bogusmode"
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           capture_output=True, text=True, cwd=str(self.ROOT))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bogusmode", r.stderr)
        self.assertIn("AUTORESEARCH_MODE", r.stderr)
        self.assertNotIn("KeyError", r.stderr)

    def test_resolve_env_mode_unset_falls_through_to_the_default(self):
        env = dict(modes.os.environ)
        env.pop("AUTORESEARCH_MODE", None)
        with mock.patch.dict(modes.os.environ, env, clear=True):
            self.assertEqual(modes.resolve_env_mode(), modes.DEFAULT_MODE)

    def test_resolve_env_mode_empty_falls_through_to_the_default(self):
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": ""}, clear=False):
            self.assertEqual(modes.resolve_env_mode(), modes.DEFAULT_MODE)

    def test_resolve_env_mode_passes_a_live_spec_through(self):
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "foilspfbw"}, clear=False):
            self.assertEqual(modes.resolve_env_mode(), "foilspfbw")

    def test_resolve_env_mode_raises_on_a_set_but_unknown_value(self):
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "foilspfbx"}, clear=False):
            with self.assertRaises(SystemExit) as cm:
                modes.resolve_env_mode()
        msg = str(cm.exception)
        self.assertIn("foilspfbx", msg)
        self.assertIn("AUTORESEARCH_MODE", msg)
        for m in modes.SPECS:
            self.assertIn(m, msg)

    def test_stamp_does_not_coerce_a_set_but_unknown_env(self):
        with mock.patch.dict(modes.os.environ,
                             {"AUTORESEARCH_MODE": "bogusmode"}, clear=False):
            with self.assertRaises(SystemExit):
                modes.stamp_mode_from_argv([])

    def test_one_default_mode_literal_in_the_tree(self):
        """The shadow shape this branch existed to delete: core/runtime.py,
        core/pipeline.py and core/bo_driver.py each carried their own
        module-level fallback literal, and two of them disagreed.

        Globbed, not a hardcoded three: the whole point is that the reader
        set is NOT a fixed list. graph/pipeline_io.py was a live reader
        outside the original tuple (round-3 minor 2), and the sibling
        reachability test on this page already derives its file set the same
        way."""
        offenders = []
        files = sorted((self.ROOT / "core").glob("*.py")) + \
            sorted((self.ROOT / "graph").glob("*.py"))
        self.assertGreater(len(files), 10, "glob found suspiciously few files")
        for path in files:
            rel = path.relative_to(self.ROOT)
            for ln, line in enumerate(path.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r'(setdefault|environ\.get)\(\s*'
                             r'"AUTORESEARCH_MODE"\s*,\s*"', line):
                    offenders.append(f"{rel}:{ln}")
        self.assertEqual(
            offenders, [],
            "hardcoded AUTORESEARCH_MODE fallback literal(s); use "
            "modes.DEFAULT_MODE")

    def test_test_tree_mode_literals_agree_with_the_registry(self):
        """The per-module `setdefault("AUTORESEARCH_MODE", ...)` lines in
        tests/ must stay literal -- they exist for `discover -s tests`
        WITHOUT `-t .`, which never imports tests/__init__.py and so cannot
        rely on its stamp. But a literal that can drift from
        modes.DEFAULT_MODE is the same shadow shape as the five core ones,
        so make the drift a failure instead of a silent divergence."""
        import re
        bad = []
        for f in sorted((self.ROOT / "tests").glob("*.py")):
            for ln, line in enumerate(f.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                m = re.search(r'setdefault\(\s*"AUTORESEARCH_MODE"\s*,\s*'
                              r'"([^"]+)"', line)
                if m and m.group(1) != modes.DEFAULT_MODE:
                    bad.append(f"{f.name}:{ln} pins {m.group(1)!r}")
        self.assertEqual(
            bad, [],
            f"test-tree AUTORESEARCH_MODE literal(s) disagree with "
            f"modes.DEFAULT_MODE ({modes.DEFAULT_MODE!r})")

    def test_default_mode_is_a_live_spec(self):
        self.assertIn(modes.DEFAULT_MODE, modes.SPECS)

    def test_entrypoints_assert_mode_after_argparse(self):
        for rel in ("graph/run.py", "graph/closed_loop.py"):
            text = (self.ROOT / rel).read_text()
            self.assertIn("assert_mode_stamped(args.mode)", text,
                          f"{rel}: no loud startup mode assertion")
