# Phase C2a: the geometry pre-check kit, the run label, C1's small fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a study on the contract engine gate each point on the `mu2e -n 1` geometry pre-check, run from the same code tarball as its grid jobs; make the run label a study setting; and land the seven small fixes deferred from C1.

**Architecture:** The pre-check's rules move out of `core/bo_driver.py` into plain functions, `core/adapters/preflight_checks.py`, which an in-process adapter (`core/adapters/offline_preflight.py`, `OfflinePreflightKit`) and the old pipeline's pre-check both call. Both run the check from the study's `kits.prodtools.code_tarball`, unpacked once per content by `prodtools_entry.unpacked`, so the `musing` setting goes away. The run label moves from the stage templates to `kits.prodtools.dsconf`. The fixes touch `core/contract.py` (retry budgets per call), the prodtools adapter (stuck receipts, `starting`, a missing `jobs` block), `core/kits.py` (a trace row for `start`), `core/study.py` (`entry` reserved at load) and `graph/study_loop.py` (the name prefix checked before launch).

**Tech Stack:** Python 3 (ana 2.8.0 via `$AUTORESEARCH_PYTHON`), `unittest`, LangGraph, the `mcp` 2.x SDK, GNU `tar`.

**Spec:** `docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md`

## Global Constraints

- All commands run from the repo root, `/exp/mu2e/app/users/oksuzian/autoresearch`, in a shell that ran `source ./activate.sh`.
- Test command: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` (about 5 min, ~969 tests at branch start) — the suite must be green at every commit.
- Golden parity: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check d` after any task that touches a study file or `ModeSpec`, plus `check a b e`; never `c` (it runs real G4).
- `core/kit_config.py`, `core/kit_registry.py` and `core/study.py` are STDLIB ONLY (their headers say so).
- `core/study.py`, `core/kits.py`, `core/contract.py`, `core/scheduler.py`, `graph/study_graph.py`, `graph/study_run.py`, `graph/study_loop.py` may not contain the words `sob`, `calo` or `flash` anywhere, comments included (`tests/test_generic_core.py`).
- No silent fallbacks: every refusal names the field or value and the rule. A missing number is never replaced by a default.
- No personal user path (`/exp/mu2e/(app|data)/users/<name>`) in tracked source under `core`, `graph`, `tests`, `tools`, `mode_specs`, or in `CONTEXT.md` (`tests/test_no_hardcoded_paths.py`). Code tarball paths in study files are written `${ARTIFACT}/autoresearch_muse/...`.
- Scratch and outputs under `/exp/mu2e/data/users/oksuzian/` or the data root, never `/tmp` — except the two existing `/tmp` conventions reused on purpose: the host-wide submit lock `/tmp/mu2e_submit.<user>.lock` and the spack cache `/tmp/spack_cache_<user>`. The pre-check's workdir is `<GRID_DATA_ROOT>/<config>/preflight/` and its unpack cache `<GRID_DATA_ROOT>/_code/<sha256>/`, for the engine kit and the pipeline alike.
- Verdict codes are today's `PREFLIGHT_VERDICTS` values: a check returns `pass`, `fail_managed` (every FAIL) or `ambiguous`; `fail_init` stays the pipeline's "no proposal geometry". Only `pass` passes.
- The old pipeline is reference-only (no campaigns before C2b). Its pre-check keeps its printing, its return codes (0 pass, 1 FAIL, 2 no proposal, 3 ambiguous) and its `paths.verify(... REQUIRED_ARTIFACTS)` gate.
- Retry budgets (spec section 3, fix 5): `submit`, `check`, `describe` — 3 attempts, pauses (5, 20) s; `status`, `results`, `cancel` — 5 attempts, pauses (5, 20, 60, 180) s.
- `STARTING_LIMIT_S = 10 * 60`. `OfflinePreflightKit`: `EXECUTORS = ("grid", "local")`, `REQUIRES_KERBEROS = False`, `LAUNCH_STAGGER_S = 0`.
- `dsconf` values: `prodtools_smoke` `MDC2025ax_{cfg}`; the seven mode specs, `demo.json` and `template.json` `Run1Bak_{cfg}`. The `tests/fixtures/prodtools_parity/` files are not edited.
- Nothing is pushed, and nothing is submitted to the grid, without the operator's go-ahead.
- Stage explicit paths only (`git add <path> ...`, never `-A` or `.`).
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

## Review Focus

1. The engine launched from a shell where `muse setup` already ran (`MUSE_WORK_DIR` set — the usual habit): the tarball's `Code/setup.sh` would refuse ("Muse already setup"), look like an env flake, burn every retry and end `ambiguous` on every point. `run_check` must unset `MUSE_WORK_DIR` in its command, as prodtools' `runlocal` does for its jobs. Pinned by `test_the_command_unsets_muse_work_dir_first` (Task 2).
2. A rerun of a point whose `preflight/` workdir still holds the last run's `preflight_geom.gdml` or `asbuilt.gdml`, and whose new G4 run wrote no GDML: the stale dump must never verify as this run's as-built geometry. Pinned by `test_a_stale_gdml_in_the_workdir_is_not_read` (Task 4).
3. A code tarball rebuilt in place under the same file name (the operator's usual move after a patch): the unpack cache must not keep serving the old tree. Pinned by `test_a_tarball_rebuilt_in_place_gets_a_new_tree` (Task 1).
4. A stage template on `$AUTORESEARCH_STUDY_PATH` written before C2a, still carrying `dsconf_fmt`: it must be refused with the fix named, not silently ignored while the study's `dsconf` wins. Pinned by `test_a_template_still_naming_dsconf_fmt_is_refused` (Task 5).
5. A pipeline study (foilspf family) whose `kits.prodtools.dsconf` is anything but `Run1Bak_{cfg}`: the pipeline names runs with its own `DSCONF` and would ignore the setting, so the study must be refused at load. Pinned by `test_a_run_label_the_pipeline_would_ignore_is_refused` (Task 5).

---

### Task 1: The unpack cache

**Files:**
- Modify: `core/adapters/prodtools_entry.py` (add `unpacked` after `build_code_tarball`)
- Test: `tests/test_prodtools_entry.py` (new class `TestUnpacked`)

**Interfaces:**
- Produces: `prodtools_entry.unpacked(tarball, cache_root) -> Path` — the directory that holds `Code/` (so `<result>/Code/setup.sh` exists), `<cache_root>/<sha256 hex of the tarball's bytes>`. Raises `ValueError` naming the tarball when it is missing, not a tar file, or has no `Code/setup.sh`. Safe to call from several threads or processes at once.

- [ ] **Step 1: Write the failing tests**

In `tests/test_prodtools_entry.py`, add `import hashlib` and `import shutil` to the imports at the top, and add this class after `TestCodeTarball`:

```python
class TestUnpacked(_Tmp):
    def tarball(self, setup_text="echo hi\n", with_setup=True):
        """A muse-style tarball at a fixed path: Code/setup.sh and the
        Code/backing link to a /cvmfs release. Rebuilding overwrites it."""
        src = self.tmp / "src"
        if src.exists():
            shutil.rmtree(src)
        code = src / "Code"
        code.mkdir(parents=True)
        if with_setup:
            (code / "setup.sh").write_text(setup_text)
        (code / "backing").symlink_to(
            "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax")
        path = self.tmp / "Code.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        return path

    def test_unpacks_once_under_the_digest_of_its_bytes(self):
        t = self.tarball()
        cache = self.tmp / "cache"
        root = pe.unpacked(t, cache)
        self.assertEqual(root,
                         cache / hashlib.sha256(t.read_bytes()).hexdigest())
        self.assertEqual((root / "Code" / "setup.sh").read_text(), "echo hi\n")
        self.assertTrue((root / "Code" / "backing").is_symlink())
        mtime = (root / "Code" / "setup.sh").stat().st_mtime_ns
        self.assertEqual(pe.unpacked(str(t), cache), root)
        self.assertEqual((root / "Code" / "setup.sh").stat().st_mtime_ns, mtime)
        self.assertEqual([p.name for p in cache.iterdir()], [root.name])

    def test_a_tarball_rebuilt_in_place_gets_a_new_tree(self):
        cache = self.tmp / "cache"
        old = pe.unpacked(self.tarball(), cache)
        new = pe.unpacked(self.tarball(setup_text="echo rebuilt\n"), cache)
        self.assertNotEqual(new, old)
        self.assertEqual((new / "Code" / "setup.sh").read_text(),
                         "echo rebuilt\n")

    def test_two_unpackers_at_once_share_one_tree(self):
        t = self.tarball()
        cache = self.tmp / "cache"
        got, errors = [], []

        def unpack():
            try:
                got.append(pe.unpacked(t, cache))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=unpack) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(got)), 1)
        self.assertEqual([p.name for p in cache.iterdir()], [got[0].name])

    def test_a_missing_codeless_or_broken_tarball_is_refused_naming_it(self):
        cache = self.tmp / "cache"
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(self.tmp / "gone.tar.bz2", cache)
        self.assertIn("gone.tar.bz2", str(cm.exception))
        bare = self.tarball(with_setup=False)
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(bare, cache)
        self.assertIn(str(bare), str(cm.exception))
        self.assertIn("Code/setup.sh", str(cm.exception))
        junk = self.tmp / "junk.tar.bz2"
        junk.write_text("not a tarball")
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(junk, cache)
        self.assertIn(str(junk), str(cm.exception))
        self.assertEqual(list(cache.iterdir()), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_entry.TestUnpacked -v`
Expected: FAIL — `AttributeError: module 'adapters.prodtools_entry' has no attribute 'unpacked'`.

- [ ] **Step 3: Implement `unpacked`**

In `core/adapters/prodtools_entry.py`, add after `build_code_tarball`:

```python
def unpacked(tarball, cache_root) -> Path:
    """The directory holding `tarball`'s Code/, unpacked once into
    <cache_root>/<sha256 of its bytes>/ (Phase C2a spec, "Files"): every
    check of the same bytes shares one tree, and a tarball rebuilt in
    place gets a new one. Built in a private directory and renamed into
    place, as build_code_tarball does, so concurrent unpackers of one
    tarball are safe: the first rename wins and every caller uses its
    tree. A tree counts only once it has Code/setup.sh, the script the
    geometry pre-check sources."""
    tarball = Path(tarball)
    if not tarball.is_file():
        raise ValueError(f"code_tarball {tarball} does not exist")
    cache_root = Path(cache_root)
    final = cache_root / _sha256_file(tarball)
    setup = Path("Code") / "setup.sh"
    if (final / setup).is_file():
        return final
    cache_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=cache_root))
    try:
        _tar(["xjf", str(tarball), "-C", str(work)], f"unpacking {tarball}")
        if not (work / setup).is_file():
            raise ValueError(f"code_tarball {tarball} has no Code/setup.sh, "
                             f"so it is not a muse tarball (build it with "
                             f"`muse tarball`)")
        try:
            os.rename(work, final)
        except OSError:
            # Another unpacker renamed the same bytes into place first.
            if not (final / setup).is_file():
                raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return final
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_entry -v`
Expected: PASS (all classes, `TestParity` included).

- [ ] **Step 5: Run the suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/adapters/prodtools_entry.py tests/test_prodtools_entry.py
git commit -F - <<'EOF'
feat(adapters): unpack a code tarball once per content, safely in parallel

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 2: The shared pre-check; the pipeline's pre-check runs through it, from the code tarball

**Files:**
- Create: `core/adapters/preflight_checks.py`
- Create: `tests/preflight_logs.py` (recorded log shapes and GDML builders; not a test module)
- Create: `tests/test_preflight_checks.py`
- Modify: `core/bo_driver.py` (imports at lines 22 and 43-45; delete lines 380-516 except `write_json_atomic`; rewrite `_cmd_preflight_impl`)
- Modify: `core/runtime.py` (`SETUPMU2E`, `PREFLIGHT_TIMEOUT_S` re-exported)
- Modify: `tests/test_audit_fixes.py` (two classes move out), `tests/test_zero_overlap_policy.py` (imports)

**Interfaces:**
- Consumes: `prodtools_entry.unpacked(tarball, cache_root) -> Path` (Task 1).
- Produces (all in `core/adapters/preflight_checks.py`):
  - `SETUPMU2E: str`; `TIMEOUT_S = 1200`; `PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init", 3: "ambiguous"}`; `FCL_NAME = "surfacecheck.fcl"`; `PREFLIGHT_GDML_NAME = "preflight_geom.gdml"`; and, moved verbatim from `bo_driver`, `G4_GEOM_FAIL_RX`, `G4_FATAL_RX`, `SURFACE_CHECK_GEOM_OVERLAY`, `SURFACE_CHECK_FCL`, `PREFLIGHT_GDML_FCL_LINES`, `GDML_FOIL_TUBE_RX`, `SURFACE_OVERLAP_RX`, `SURFACE_OVERLAP_MANAGED`, `verify_stopping_target_gdml(gdml_path, geom_text, tol_mm=1e-3) -> list[str]`
  - `Verdict(ok: bool, code: str, reason: str, notes: tuple[str, ...] = ())` (frozen dataclass)
  - `overlap_banner(checks_managed_overlap: bool, require_zero_overlaps: bool) -> str`
  - `geom_name(config: str) -> str` — `autoresearch_<config>_geom.txt`, the name the grid jobs use
  - `check_files(geom_basename: str, *, dumps_gdml: bool) -> dict[str, str]` — `{"surfacecheck_<geom_basename>": overlay, "surfacecheck.fcl": fcl}`
  - `stage_workdir(workdir, *, geom_text: str, geom_basename: str, dumps_gdml: bool) -> Path` — empties the workdir, writes the geometry and the check files
  - `retry_if_mu2e_never_started(proc) -> bool`
  - `run_check(code_dir, workdir, fcl: str, *, timeout_s: float, label: str = "preflight", log=None) -> (out: str, rc: int, timed_out: bool)`
  - `classify(out, rc, timed_out, *, geom_text, gdml_path, verifies_foil_gdml, checks_managed_overlap, require_zero_overlaps) -> Verdict`
- `bo_driver` keeps `PREFLIGHT_VERDICTS` as a name (imported), loses `G4_*`, `SURFACE_*`, `PREFLIGHT_GDML_*`, `GDML_FOIL_TUBE_RX`, `verify_stopping_target_gdml`, `_overlap_banner`.

The one intended verdict change: the `holeRadii vector active` printout check is dropped (spec, "Decisions"); the as-built GDML comparison still checks every foil's hole radius.

- [ ] **Step 1: Create the shared test fixtures**

Create `tests/preflight_logs.py`:

```python
"""Recorded pre-check log shapes and GDML builders, shared by
tests/test_preflight_checks.py and tests/test_offline_preflight_kit.py.
Not a test module: unittest discovers test*.py only.

FATAL_LOG and ADVISORY_LOG are the foilsg06R00_00 preflight log shapes
(moved from tests/test_audit_fixes.py with G4_FATAL_RX); MANAGED_LOG uses
the volume name SURFACE_OVERLAP_MANAGED matches; each log ends the way
run_check joins stdout and stderr."""
import re

FATAL_LOG = (
    "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
    "... geometry construction ...\n"
    "-------- EEEE ------- G4Exception-START -------- EEEE -------\n"
    "*** G4Exception : GeomSolids0002\n"
    "      issued by : G4Tubs::G4Tubs()\n"
    "Invalid values for radii in solid: Foil_00\n"
    "        pRMin = 51.041, pRMax = 50\n"
    "*** Fatal Exception *** core dump ***\n"
)

# Advisory surface-check noise from a stock-geometry overlap.
ADVISORY_LOG = (
    "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
    "-------- WWWW ------- G4Exception-START -------- WWWW -------\n"
    "*** G4Exception : GeomVol1002\n"
    "      issued by : G4PVPlacement::CheckOverlaps()\n"
    "Overlap is detected for volume TT_MidInner\n"
    "-------- WWWW -------- G4Exception-END --------- WWWW -------\n"
    "Begin processing the 1st record\n"
    "Art has completed and will exit with status 0.\n"
)

CLEAN_LOG = (
    "Geant4 version Name: geant4-11-02-patch-01    (16-February-2024)\n"
    "%MSG-i MF_INIT_OK:  Early 26-Sep-2026 10:00:00 CDT JobSetup\n"
    "Begin processing the 1st record. run: 1803 subRun: 0 event: 1\n"
    "Art has completed and will exit with status 0.\n"
    "\n--- STDERR ---\n"
)

MANAGED_LOG = (
    "Begin processing the 1st record\n"
    "Overlap is detected for volume StoppingTargetFoil_07:0 (G4Tubs) with "
    "its mother volume StoppingTargetMother (G4Tubs)\n"
    "          protrusion at mother local point (0,0,0) by 1.2 mm\n"
    "Art has completed and will exit with status 0.\n"
)

# A construction error before art reached the event loop, not fatal-marked.
PRE_INIT_GEOM_LOG = (
    "Geant4 version Name: geant4-11-02-patch-01    (16-February-2024)\n"
    "-------- EEEE ------- G4Exception-START -------- EEEE -------\n"
    "*** G4Exception : GeomMgt0002\n"
    "      issued by : G4PVPlacement::G4PVPlacement()\n"
    "Volume VirtualDetector_TT_MidInner is outside mother DS2Vacuum\n"
    "-------- EEEE -------- G4Exception-END --------- EEEE -------\n"
)

# The env flake: `mu2e` never started.
NO_MU2E_LOG = "\n--- STDERR ---\nbash: line 1: mu2e: command not found\n"

GEOM = (
    "vector<double> stoppingTarget.radii          = { 100.0, 200.0 };\n"
    "vector<double> stoppingTarget.halfThicknesses = { 0.5, 0.25 };\n"
    "double stoppingTarget.holeRadius = 1.0e6;\n"
    "vector<double> stoppingTarget.holeRadii      = { 10.0, 0.0 };\n"
)


def gdml(tubes):
    """A GDML document holding the given (name, rmin, rmax, z, lunit)
    tubes."""
    items = "".join(
        f'<tube name="{n}" rmin="{rmin}" rmax="{rmax}" z="{z}" '
        f'lunit="{lunit}" deltaphi="6.28" aunit="rad"/>'
        for n, rmin, rmax, z, lunit in tubes)
    return f'<?xml version="1.0"?><gdml><solids>{items}</solids></gdml>'


def _vector(geom_text, key):
    m = re.search(rf"vector<double>\s+stoppingTarget\.{key}\s*=\s*"
                  rf"\{{([^}}]*)\}}", geom_text)
    return [float(v) for v in m.group(1).split(",")]


def gdml_matching(geom_text):
    """The GDML a correct G4 build of `geom_text`'s stopping target writes:
    one pointer-suffixed Foil_NN tube per foil (rIn = holeRadii[i], rOut =
    radii[i], full length = 2 * halfThicknesses[i])."""
    radii = _vector(geom_text, "radii")
    half = _vector(geom_text, "halfThicknesses")
    holes = _vector(geom_text, "holeRadii")
    return gdml([(f"Foil_{i:02d}0x55d1a2b3", holes[i], r, 2 * half[i], "mm")
                 for i, r in enumerate(radii)])
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_preflight_checks.py`:

```python
"""core/adapters/preflight_checks.py: the geometry pre-check's files, its
run, and the log -> verdict rules, shared by the offline_preflight kit and
core/bo_driver.py's pipeline pre-check (Phase C2a)."""
import contextlib
import dataclasses
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import bo_driver as bo  # noqa: E402
import paths  # noqa: E402
from adapters import preflight_checks as pc  # noqa: E402
from adapters import prodtools_entry as pe  # noqa: E402
from tests.preflight_logs import (ADVISORY_LOG, CLEAN_LOG, FATAL_LOG,  # noqa: E402
                                  GEOM, MANAGED_LOG, NO_MU2E_LOG,
                                  PRE_INIT_GEOM_LOG, gdml, gdml_matching)


class TestFatalAbortRegexes(unittest.TestCase):
    """Regression for wiki/incidents/preflight-past-init-false-pass.md
    (moved from tests/test_audit_fixes.py): a fatal GeomSolids0002 abort
    AFTER pre-geometry strings (BeginRun / GenParticle) was classified
    PASS because past_init short-circuited the geom-fail check."""

    def test_fatal_abort_matches(self):
        self.assertTrue(pc.G4_FATAL_RX.search(FATAL_LOG))

    def test_advisory_overlap_does_not_match_fatal(self):
        self.assertFalse(pc.G4_FATAL_RX.search(ADVISORY_LOG))

    def test_geom_fail_rx_includes_geomsolids(self):
        self.assertTrue(pc.G4_GEOM_FAIL_RX.search(FATAL_LOG))

    def test_past_init_would_have_masked_it(self):
        self.assertIn("BeginRun", FATAL_LOG)


class TestVerifyStoppingTargetGdml(unittest.TestCase):
    """As-built GDML geometry assertion (moved from
    tests/test_audit_fixes.py)."""

    def _run(self, tubes, geom=None):
        with tempfile.NamedTemporaryFile("w", suffix=".gdml",
                                         delete=False) as f:
            f.write(gdml(tubes))
            path = f.name
        try:
            return pc.verify_stopping_target_gdml(path, geom or GEOM)
        finally:
            Path(path).unlink()

    def test_matching_geometry_passes(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_wrong_hole_radius_fails(self):
        errs = self._run([("Foil_00", 51.041, 100.0, 1.0, "mm"),
                          ("Foil_01", 51.041, 200.0, 0.5, "mm")])
        self.assertEqual(len(errs), 2)
        self.assertIn("Foil_00 rIn", errs[0])

    def test_foil_count_mismatch_fails(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm")])
        self.assertTrue(any("1 Foil_* tubes" in e and "2 foils" in e
                            for e in errs))

    def test_scalar_fallback_geom_uses_scalar(self):
        geom = ("vector<double> stoppingTarget.radii = { 100.0 };\n"
                "double stoppingTarget.holeRadius = 21.5;\n")
        errs = self._run([("Foil_00", 21.5, 100.0, 0.0, "mm")], geom=geom)
        self.assertEqual(errs, [])

    def test_cm_units_scaled(self):
        errs = self._run([("Foil_00", 1.0, 10.0, 0.1, "cm"),
                          ("Foil_01", 0.0, 20.0, 0.05, "cm")])
        self.assertEqual(errs, [])

    def test_pointer_suffixed_names_parse_correctly(self):
        errs = self._run([("Foil_000x55d1a2b3", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_010x55d1c4d5", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_missing_foil_indices_reported(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_07", 0.0, 200.0, 0.5, "mm")])
        self.assertTrue(any("missing from GDML: [1]" in e for e in errs))

    def test_repeat_last_half_thickness(self):
        geom = ("vector<double> stoppingTarget.radii = { 100.0, 200.0 };\n"
                "vector<double> stoppingTarget.halfThicknesses = { 0.5 };\n"
                "vector<double> stoppingTarget.holeRadii = { 0.0, 0.0 };\n")
        errs = self._run([("Foil_00", 0.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 1.0, "mm")], geom=geom)
        self.assertEqual(errs, [])


STRICT = dict(verifies_foil_gdml=False, checks_managed_overlap=True,
              require_zero_overlaps=True)


class TestClassify(unittest.TestCase):
    """One recorded log per verdict, the rules and order bo_driver used."""

    def classify(self, out, rc, *, timed_out=False, gdml_path=None,
                 geom_text=GEOM, **flags):
        return pc.classify(out, rc, timed_out, geom_text=geom_text,
                           gdml_path=gdml_path or "/nonexistent.gdml",
                           **{**STRICT, **flags})

    def gdml_file(self, text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / pc.PREFLIGHT_GDML_NAME
        path.write_text(text)
        return path

    def test_a_clean_run_passes_and_names_the_policy(self):
        v = self.classify(CLEAN_LOG, 0)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertEqual(v.reason, "init=True; no geom-fail signature and "
                                   "zero surface-check overlaps.")
        self.assertIn("surface-check total_hits=0 unique_volumes=0 "
                      "baseline=0 managed=0", v.notes)

    def test_the_holeradii_printout_is_no_longer_required(self):
        self.assertIn("stoppingTarget.holeRadii", GEOM)
        self.assertNotIn("holeRadii vector active", CLEAN_LOG)
        self.assertTrue(self.classify(CLEAN_LOG, 0).ok)

    def test_a_fatal_abort_fails_even_past_init(self):
        v = self.classify(FATAL_LOG, 134)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith("fatal G4/art abort:\n"))
        self.assertIn("GeomSolids0002", v.reason)

    def test_a_missing_gdml_dump_fails(self):
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertIn(f"GDML dump {Path('/nonexistent.gdml').name} not "
                      f"produced", v.reason)

    def test_an_as_built_geometry_that_differs_fails(self):
        wrong = self.gdml_file(gdml([("Foil_00", 51.0, 100.0, 1.0, "mm"),
                                     ("Foil_01", 51.0, 200.0, 0.5, "mm")]))
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=wrong)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "as-built geometry differs from geom file (2 mismatches):\n"))
        self.assertIn("    Foil_00 rIn", v.reason)

    def test_a_matching_gdml_passes_and_counts_the_foils(self):
        good = self.gdml_file(gdml_matching(GEOM))
        v = self.classify(CLEAN_LOG, 0, verifies_foil_gdml=True,
                          gdml_path=good)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertIn("geometry assertion: 2 foils verified against as-built "
                      "GDML (rIn/rOut/thickness)", v.notes)

    def test_any_overlap_fails_under_the_zero_overlap_policy(self):
        v = self.classify(ADVISORY_LOG, 0)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "zero-overlap policy: 1 overlap(s) in 1 volume(s):\n"
            "    TT_MidInner"))
        self.assertIn("\ncontext:\n", v.reason)

    def test_stock_overlaps_pass_under_the_managed_policy(self):
        v = self.classify(ADVISORY_LOG, 0, require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code), (True, "pass"))
        self.assertTrue(v.reason.endswith("and no managed-volume overlap."))
        self.assertIn("(info) 1 known stock-geometry overlaps (1 unique "
                      "volumes); ignored — not managed by BO knobs.", v.notes)

    def test_a_managed_volume_overlap_fails(self):
        v = self.classify(MANAGED_LOG, 0, require_zero_overlaps=False)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith(
            "managed-volume overlap detected:\n    StoppingTargetFoil_07:0"))
        self.assertIn("\ncontext:\n", v.reason)

    def test_a_geometry_error_before_init_fails(self):
        v = self.classify(PRE_INIT_GEOM_LOG, 65,
                          checks_managed_overlap=False)
        self.assertEqual((v.ok, v.code), (False, "fail_managed"))
        self.assertTrue(v.reason.startswith("Geant4 geometry error:\n"))
        self.assertIn("GeomMgt0002", v.reason)

    def test_no_banner_and_a_failed_run_is_ambiguous_with_the_log_tail(self):
        v = self.classify(NO_MU2E_LOG, 127)
        self.assertEqual((v.ok, v.code), (False, "ambiguous"))
        self.assertTrue(v.reason.startswith(
            "rc=127, no geom-fail signature. Last 40 lines of log:\n"))
        self.assertIn("mu2e: command not found", v.reason)

    def test_a_timeout_passes_as_it_always_has(self):
        v = self.classify("Geant4 version Name: geant4-11-02\n", -1,
                          timed_out=True)
        self.assertEqual((v.ok, v.code), (True, "pass"))

    def test_every_code_is_a_verdict_value(self):
        for out, rc in ((CLEAN_LOG, 0), (FATAL_LOG, 134), (NO_MU2E_LOG, 127)):
            self.assertIn(self.classify(out, rc).code,
                          pc.PREFLIGHT_VERDICTS.values())


class TestFiles(unittest.TestCase):
    def test_geom_name_is_the_grid_jobs_name(self):
        self.assertEqual(pc.geom_name("cfg1"), "autoresearch_cfg1_geom.txt")

    def test_the_overlay_includes_the_geometry_and_the_fcl_names_it(self):
        files = pc.check_files("autoresearch_cfg1_geom.txt", dumps_gdml=False)
        self.assertEqual(sorted(files),
                         ["surfacecheck.fcl",
                          "surfacecheck_autoresearch_cfg1_geom.txt"])
        overlay = files["surfacecheck_autoresearch_cfg1_geom.txt"]
        self.assertTrue(overlay.startswith(
            '#include "autoresearch_cfg1_geom.txt"\n'))
        self.assertIn("bool g4.doSurfaceCheck             = true;", overlay)
        fcl = files[pc.FCL_NAME]
        self.assertIn('#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"', fcl)
        self.assertIn('services.GeometryService.inputFile : '
                      '"surfacecheck_autoresearch_cfg1_geom.txt"', fcl)
        self.assertNotIn("writeGDML", fcl)

    def test_dumps_gdml_adds_the_gdml_lines(self):
        fcl = pc.check_files("g.txt", dumps_gdml=True)[pc.FCL_NAME]
        self.assertTrue(fcl.endswith(pc.PREFLIGHT_GDML_FCL_LINES))

    def test_stage_workdir_empties_it_then_writes_the_files(self):
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "cfg1" / "preflight"
            w.mkdir(parents=True)
            (w / pc.PREFLIGHT_GDML_NAME).write_text("stale")
            pc.stage_workdir(w, geom_text="// g\n",
                             geom_basename="autoresearch_cfg1_geom.txt",
                             dumps_gdml=True)
            self.assertEqual(sorted(p.name for p in w.iterdir()),
                             ["autoresearch_cfg1_geom.txt", "surfacecheck.fcl",
                              "surfacecheck_autoresearch_cfg1_geom.txt"])
            self.assertEqual((w / "autoresearch_cfg1_geom.txt").read_text(),
                             "// g\n")


class TestRunCheck(unittest.TestCase):
    def run_check(self, stdout="out", stderr="err", rc=0):
        seen = {}

        def fake(cmd, **kw):
            seen.update(cmd=cmd, **kw)
            p = subprocess.CompletedProcess(["bash"], rc, stdout=stdout,
                                            stderr=stderr)
            p.timed_out = False
            return p

        with mock.patch.object(pc, "_sourced_bash", return_value=fake):
            result = pc.run_check(Path("/c/abc"), Path("/w/cfg1/preflight"),
                                  "surfacecheck.fcl", timeout_s=60,
                                  log=io.StringIO())
        return result, seen

    def test_the_command_unsets_muse_work_dir_first(self):
        _result, seen = self.run_check()
        self.assertTrue(seen["cmd"].startswith("unset MUSE_WORK_DIR && "))

    def test_the_command_sources_the_tarballs_setup_and_prepends_the_workdir(self):
        (out, rc, timed_out), seen = self.run_check()
        cmd = seen["cmd"]
        self.assertIn(f"source {pc.SETUPMU2E} >/dev/null && ", cmd)
        self.assertIn("source /c/abc/Code/setup.sh >/dev/null && ", cmd)
        self.assertIn('export MU2E_SEARCH_PATH="/w/cfg1/preflight:'
                      '$MU2E_SEARCH_PATH"', cmd)
        self.assertIn('export FHICL_FILE_PATH="/w/cfg1/preflight:'
                      '$FHICL_FILE_PATH"', cmd)
        self.assertTrue(cmd.endswith(
            "cd /w/cfg1/preflight && mu2e -c surfacecheck.fcl -n 1"))
        self.assertEqual(seen["timeout"], 60)
        self.assertIs(seen["should_retry"], pc.retry_if_mu2e_never_started)
        self.assertEqual((out, rc, timed_out),
                         ("out\n--- STDERR ---\nerr", 0, False))

    def test_only_a_run_that_never_started_is_retried(self):
        def proc(rc, out=""):
            return subprocess.CompletedProcess(["bash"], rc, stdout=out,
                                               stderr="")
        self.assertTrue(pc.retry_if_mu2e_never_started(proc(127)))
        self.assertFalse(pc.retry_if_mu2e_never_started(
            proc(3, "Geant4 version Name")))
        self.assertFalse(pc.retry_if_mu2e_never_started(proc(0)))

    def test_runtime_reexports_the_pre_checks_constants(self):
        import runtime
        self.assertEqual(runtime.SETUPMU2E, pc.SETUPMU2E)
        self.assertEqual(runtime.PREFLIGHT_TIMEOUT_S, pc.TIMEOUT_S)


class TestPipelinePreflight(unittest.TestCase):
    """core/bo_driver.py's pre-check through the shared functions: the same
    return codes and verdict lines, run from the mode's code tarball."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.mode = bo.MODES["foilspf"]
        spec = bo._modes.SPECS["foilspf"]
        tarball = self.tmp / "Code.tar.bz2"
        tarball.write_text("")
        self.spec = dataclasses.replace(spec, grid_tarball=str(tarball),
                                        dumps_gdml=False,
                                        verifies_foil_gdml=False)
        self.calls = []
        for patch in (
                mock.patch.dict(bo._modes.SPECS, {"foilspf": self.spec}),
                mock.patch.multiple(self.mode,
                                    proposal_dir=self.tmp / "proposals",
                                    preflight_dir=self.tmp / "preflight"),
                mock.patch.object(bo, "GRID_DATA_ROOT", self.tmp / "grid"),
                mock.patch.object(paths, "verify"),
                mock.patch.object(pe, "unpacked",
                                  return_value=self.tmp / "code")):
            patch.start()
            self.addCleanup(patch.stop)
        x = [(lo + hi) / 2 for lo, hi in zip(spec.bounds_lo, spec.bounds_hi)]
        self.geom_text = self.mode.render_proposal("cfgT", x).read_text()
        self.workdir = self.tmp / "grid" / "cfgT" / "preflight"

    def preflight(self, out, rc, *, write_gdml=False, **spec_over):
        if spec_over:
            bo._modes.SPECS["foilspf"] = dataclasses.replace(self.spec,
                                                             **spec_over)

        def fake(code_dir, workdir, fcl, *, timeout_s, label):
            self.calls.append((code_dir, workdir, fcl, timeout_s, label))
            if write_gdml:
                geom = (workdir / pc.geom_name("cfgT")).read_text()
                (workdir / pc.PREFLIGHT_GDML_NAME).write_text(
                    gdml_matching(geom))
            return out, rc, False

        buf = io.StringIO()
        with mock.patch.object(pc, "run_check", side_effect=fake), \
                contextlib.redirect_stdout(buf):
            code = bo._cmd_preflight_impl(
                SimpleNamespace(mode="foilspf", config_name="cfgT"))
        return code, buf.getvalue()

    def test_a_clean_run_passes_from_the_code_tarball(self):
        code, out = self.preflight(CLEAN_LOG, 0)
        self.assertEqual(code, 0)
        self.assertIn("[preflight/foilspf] PASS  init=True; no geom-fail "
                      "signature and zero surface-check overlaps.", out)
        pe.unpacked.assert_called_once_with(self.spec.grid_tarball,
                                            self.tmp / "grid" / "_code")
        self.assertEqual(self.calls, [(self.tmp / "code", self.workdir,
                                       "surfacecheck.fcl", 1200,
                                       "preflight/foilspf")])
        self.assertEqual(
            (self.workdir / "autoresearch_cfgT_geom.txt").read_text(),
            self.geom_text)
        self.assertEqual((self.tmp / "preflight" / "cfgT.log").read_text(),
                         CLEAN_LOG)

    def test_a_fatal_abort_is_rc_1(self):
        code, out = self.preflight(FATAL_LOG, 134)
        self.assertEqual(code, 1)
        self.assertIn("[preflight/foilspf] FAIL  fatal G4/art abort:", out)

    def test_an_env_flake_is_rc_3_and_names_the_log(self):
        code, out = self.preflight(NO_MU2E_LOG, 127)
        self.assertEqual(code, 3)
        self.assertIn("[preflight/foilspf] AMBIGUOUS  rc=127", out)
        self.assertIn(f"See {self.tmp / 'preflight' / 'cfgT.log'}", out)

    def test_a_missing_gdml_dump_fails(self):
        code, out = self.preflight(CLEAN_LOG, 0, dumps_gdml=True,
                                   verifies_foil_gdml=True)
        self.assertEqual(code, 1)
        self.assertIn("GDML dump preflight_geom.gdml not produced", out)
        self.assertIn("writeGDML",
                      (self.workdir / "surfacecheck.fcl").read_text())

    def test_a_verified_as_built_geometry_passes_and_is_kept(self):
        code, out = self.preflight(CLEAN_LOG, 0, write_gdml=True,
                                   dumps_gdml=True, verifies_foil_gdml=True)
        self.assertEqual(code, 0, out)
        self.assertIn("foils verified against as-built GDML", out)
        self.assertTrue((self.tmp / "grid" / "cfgT" / "geom"
                         / "asbuilt_cfgT.gdml").is_file())

    def test_a_missing_proposal_is_rc_2_and_runs_nothing(self):
        (self.tmp / "proposals" / "cfgT_geom.txt").unlink()
        code, _out = self.preflight(CLEAN_LOG, 0)
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_preflight_checks -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapters.preflight_checks'`.

- [ ] **Step 4: Create `core/adapters/preflight_checks.py`**

The constants, the regexes, `verify_stopping_target_gdml` and the comments above them are copied verbatim from `core/bo_driver.py:380-516`:

```python
"""The geometry pre-check's pieces, as plain functions (Phase C2a spec,
docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md, "1. The
offline_preflight kit"): the surface-check files, running `mu2e -n 1`
from a code tarball's Code/, and reading its log into a verdict. The
offline_preflight adapter (core/adapters/offline_preflight.py) and, until
Phase C3 deletes it, the pipeline's pre-check (core/bo_driver.py) both
call these, so the two runners judge a geometry the same way.
Stdlib only at import; graph/sourced_bash.py loads when a check runs.
"""
from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
# Wall-clock cap on one `mu2e -n 1` check (G4 init + surface check).
TIMEOUT_S = 1200

# Preflight verdict vocabulary — the ONE home of the rc mapping. A check
# returns pass, fail_managed (every FAIL) or ambiguous; fail_init is the
# pipeline's "no proposal geometry", decided before any check runs.
PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init",
                      3: "ambiguous"}

FCL_NAME = "surfacecheck.fcl"

G4_GEOM_FAIL_RX = re.compile(
    r"G4Exception.*?(GeomMgt000\d|GeomVol1002|GeomSolids00\d\d|placement|outside mother|overlap)",
    re.IGNORECASE | re.DOTALL,
)

# Fatal G4/art aborts that must FAIL preflight regardless of past_init:
# past_init fires on pre-geometry strings, so a geometry abort AFTER them
# was misclassified PASS while the grid died on the identical error. See
# wiki/incidents/preflight-past-init-false-pass.md.
G4_FATAL_RX = re.compile(
    r"G4Exception\s*:\s*GeomSolids00\d\d"
    r"|\*\*\* Fatal Exception \*\*\*"
    r"|G4Exception.*?Aborting execution",
    re.IGNORECASE | re.DOTALL,
)

# Surface-check detects silent volume overlaps that wouldn't fail G4 init
# (wiki external/mu2e-overlap-check, incidents/tsda-disc-helical-sibling-overlap).
SURFACE_CHECK_GEOM_OVERLAY = """\
#include "{base_geom_basename}"

// Activate G4 CheckOverlaps surface sampling.
bool g4.doSurfaceCheck             = true;
int  g4.nSurfaceCheckPointsPercmsq = 1;
int  g4.minSurfaceCheckPoints      = 100;
int  g4.maxSurfaceCheckPoints      = 10000000;
"""

SURFACE_CHECK_FCL = """\
#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"

services.GeometryService.inputFile : "{geom_basename}"
{gdml_lines}"""

# GDML geometry assertion (foils family): the dump reflects what G4 ACTUALLY
# built, catching value-level divergence the holeRadii canary can't see.
PREFLIGHT_GDML_NAME = "preflight_geom.gdml"
PREFLIGHT_GDML_FCL_LINES = (
    'physics.producers.g4run.debug.writeGDML : true\n'
    f'physics.producers.g4run.debug.GDMLFileName : "{PREFLIGHT_GDML_NAME}"\n'
)

# G4's GDML writer appends a pointer suffix ("Foil_020x55d1..."). A greedy
# \d+ would swallow the leading 0 of "0x" and scramble indices (foil 02 ->
# "20"); non-greedy digits + anchored optional 0x-suffix is exact.
GDML_FOIL_TUBE_RX = re.compile(r"Foil_(\d+?)(?:0x[0-9a-fA-F]+)?$")


def verify_stopping_target_gdml(gdml_path, geom_text, tol_mm=1e-3):
    """Assert the G4-built stopping-target foils match the geom file.

    Plain XML iterparse -- NOT ROOT TGDMLParse, which segfaults on forward
    volume refs (wiki/incidents/root-gdml-forward-volume-ref.md). Each foil
    is a uniquely named G4Tubs "Foil_NN" (constructStoppingTarget.cc:162).
    Returns mismatch strings; empty == verified.
    """
    import xml.etree.ElementTree as ET

    def _vec(key):
        m = re.search(
            rf"vector<double>\s+stoppingTarget\.{key}\s*=\s*\{{([^}}]*)\}}",
            geom_text)
        return [float(v) for v in m.group(1).split(",")] if m else None

    radii = _vec("radii")
    if radii is None:
        return ["geom has no stoppingTarget.radii vector — nothing to verify"]
    half = _vec("halfThicknesses") or []
    if half and len(half) < len(radii):
        # StoppingTargetMaker repeats the last halfThickness entry.
        half = half + [half[-1]] * (len(radii) - len(half))
    holes = _vec("holeRadii")
    if holes is None:
        m = re.search(r"stoppingTarget\.holeRadius\s*=\s*([0-9.eE+-]+)",
                      geom_text)
        holes = [float(m.group(1))] * len(radii) if m else [0.0] * len(radii)

    found = {}
    for _ev, el in ET.iterparse(str(gdml_path)):
        if el.tag.split("}")[-1] == "tube":
            m = GDML_FOIL_TUBE_RX.match(el.get("name", ""))
            if m:
                lunit = el.get("lunit", "mm")
                scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0}.get(lunit)
                if scale is None:
                    return [f"GDML tube {el.get('name')} has unknown "
                            f"lunit={lunit}"]
                found[int(m.group(1))] = (
                    float(el.get("rmin", 0.0)) * scale,
                    float(el.get("rmax")) * scale,
                    float(el.get("z")) * scale,  # GDML z = FULL length
                )
        el.clear()

    errs = []
    if len(found) != len(radii):
        errs.append(f"GDML has {len(found)} Foil_* tubes but geom "
                    f"specifies {len(radii)} foils")
    missing = [i for i in range(len(radii)) if i not in found]
    if missing:
        errs.append(f"foils missing from GDML: {missing[:10]}"
                    f"{'...' if len(missing) > 10 else ''}")
    for i, r_out in enumerate(radii):
        if i not in found:
            continue
        rmin, rmax, z_full = found[i]
        checks = [("rIn", rmin, holes[i]), ("rOut", rmax, r_out)]
        if half:
            checks.append(("fullThickness", z_full, 2.0 * half[i]))
        for label, got, want in checks:
            if abs(got - want) > tol_mm:
                errs.append(f"Foil_{i:02d} {label}: GDML={got:.4f} "
                            f"geom={want:.4f} (Δ={got - want:+.4f} mm)")
    return errs


# Only overlaps involving BO-managed volumes (StoppingTargetFoil_*) matter:
# stock Mu2e geometry has ~117 baseline overlap lines (FoilSupportStructure_*,
# NorthRailDS3/SouthRailDS3, VirtualDetector_EMC_0_Front), whitelisted by
# volume name.
SURFACE_OVERLAP_RX = re.compile(r"Overlap is detected for volume\s+(\S+)")
SURFACE_OVERLAP_MANAGED = re.compile(r"^StoppingTargetFoil_")

# art got this far (BeginRun, the event loop, produce() asking for input):
# a geometry message after it is advisory surface-check noise.
_PAST_INIT = ("BeginRun", "Event::beginEvent", "EndOfEventAction",
              "Begin processing the 1st record", "GenParticle")
# Any of these in the output means `mu2e` started.
_BANNERS = ("Geant4", "%MSG", "Art has", "Begin processing", "G4Exception")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str                    # a PREFLIGHT_VERDICTS value
    reason: str                  # the PASS / FAIL / AMBIGUOUS line's text
    notes: Tuple[str, ...] = ()  # what the check found on the way


def overlap_banner(checks_managed_overlap, require_zero_overlaps) -> str:
    """PASS-line suffix naming which overlap policy actually ran (kept next
    to the policy flags so it cannot drift from the gate)."""
    if not checks_managed_overlap:
        return ""
    if require_zero_overlaps:
        return " and zero surface-check overlaps"
    return " and no managed-volume overlap"


def geom_name(config: str) -> str:
    """The geometry file's name for `config`: the name the grid jobs use."""
    return f"autoresearch_{config}_geom.txt"


def check_files(geom_basename: str, *, dumps_gdml: bool) -> dict:
    """{file name: text} of the check's two files: the geometry overlay
    that turns on G4's surface check around `geom_basename`, and the FCL
    that reads it (plus the GDML dump lines when `dumps_gdml`). One G4
    init covers both checks: surfacecheck.fcl enables doSurfaceCheck AND
    exercises the plain G4-init path."""
    overlay = f"surfacecheck_{geom_basename}"
    return {
        overlay: SURFACE_CHECK_GEOM_OVERLAY.format(
            base_geom_basename=geom_basename),
        FCL_NAME: SURFACE_CHECK_FCL.format(
            geom_basename=overlay,
            gdml_lines=PREFLIGHT_GDML_FCL_LINES if dumps_gdml else ""),
    }


def stage_workdir(workdir, *, geom_text: str, geom_basename: str,
                  dumps_gdml: bool) -> Path:
    """Empty `workdir` (created when absent), then write the point's
    geometry as `geom_basename` and the check files into it. Emptied, so
    a rerun never reads the last run's GDML dump or log as its own."""
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    (workdir / geom_basename).write_text(geom_text)
    for name, text in check_files(geom_basename,
                                  dumps_gdml=dumps_gdml).items():
        (workdir / name).write_text(text)
    return workdir


def retry_if_mu2e_never_started(proc) -> bool:
    """run_sourced_bash's retry rule for the check. A transient env-source
    flake ([Errno 5]) leaves `mu2e` unsourced: a nonzero exit with no
    Geant4/art banner. A banner-bearing result is a real run and must NOT
    be retried (wiki/incidents/sourced-env-stderr-swallowed.md)."""
    combined = (proc.stdout or "") + (proc.stderr or "")
    started = any(s in combined for s in _BANNERS)
    return proc.returncode != 0 and not started


def _sourced_bash():
    """graph/sourced_bash.py's run_sourced_bash: the retry-with-backoff
    runner, which also exports SPACK_USER_CACHE_PATH onto local /tmp inside
    the command (wiki/incidents/foilsx04-all-preflight-ambiguous.md)."""
    graph = str(Path(__file__).resolve().parents[2] / "graph")
    if graph not in sys.path:
        sys.path.append(graph)
    from sourced_bash import run_sourced_bash
    return run_sourced_bash


def run_check(code_dir, workdir, fcl: str, *, timeout_s,
              label: str = "preflight", log=None):
    """Run `mu2e -c <fcl> -n 1` in `workdir` under the code tarball
    unpacked at `code_dir` (prodtools_entry.unpacked): setupmu2e-art.sh,
    then <code_dir>/Code/setup.sh, with `workdir` first on MU2E_SEARCH_PATH
    and FHICL_FILE_PATH so the point's geometry and the check files win.
    Retried only when mu2e never started. Returns (out, rc, timed_out);
    `out` is stdout, a separator line, then stderr."""
    setup = Path(code_dir) / "Code" / "setup.sh"
    cmd = (
        # A launching shell with muse already set up makes `muse setup`
        # refuse ("Muse already setup"), which reads as the env flake and
        # would burn every retry. Unset only this variable, as prodtools'
        # runlocal does for its jobs (utils/runlocal.py:child_env).
        "unset MUSE_WORK_DIR && "
        # `>/dev/null` (not `2>&1`) lets a flake's stderr reach the log.
        f"source {SETUPMU2E} >/dev/null && "
        f"source {setup} >/dev/null && "
        f'export MU2E_SEARCH_PATH="{workdir}:$MU2E_SEARCH_PATH" && '
        f'export FHICL_FILE_PATH="{workdir}:$FHICL_FILE_PATH" && '
        f"cd {workdir} && "
        f"mu2e -c {fcl} -n 1")
    proc = _sourced_bash()(cmd, timeout=timeout_s,
                           should_retry=retry_if_mu2e_never_started,
                           label=label, log=log or sys.stdout)
    out = (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or "")
    return out, proc.returncode, proc.timed_out


def _overlap_context(out, vols) -> str:
    """The log around the first listed volume's overlap report, as a block
    to append to a FAIL reason; empty when the log has none."""
    for v in vols[:1]:
        m = re.search(rf"Overlap is detected for volume\s+{re.escape(v)}.*",
                      out)
        if m:
            return f"\ncontext:\n{out[max(0, m.start() - 100): m.end() + 400]}"
    return ""


def classify(out, rc, timed_out, *, geom_text, gdml_path,
             verifies_foil_gdml, checks_managed_overlap,
             require_zero_overlaps) -> Verdict:
    """The verdict on one check's output, by core/bo_driver.py's rules in
    their order (fatal abort, as-built GDML, overlaps, a geometry error
    before init, then pass or ambiguous), minus the retired `holeRadii
    vector active` printout check: upstream Offline prints no such line,
    and the GDML comparison checks every foil's hole radius."""
    notes = []

    def fail(reason):
        return Verdict(False, "fail_managed", reason, tuple(notes))

    past_init = any(s in out for s in _PAST_INIT)

    # Fatal aborts FAIL unconditionally, before past_init or surface-check
    # logic can mask them (see G4_FATAL_RX).
    fatal = G4_FATAL_RX.search(out)
    if fatal:
        snippet = out[max(0, fatal.start() - 300): fatal.end() + 400]
        return fail(f"fatal G4/art abort:\n{snippet}")

    # As-built assertion: G4-constructed foil stack (GDML) vs the geom file,
    # per foil. HARD gate: a run whose built geometry differs from x must
    # never reach the grid.
    if verifies_foil_gdml:
        gdml_path = Path(gdml_path)
        if not gdml_path.exists():
            return fail(f"GDML dump {gdml_path.name} not produced — cannot "
                        f"verify as-built geometry (writeGDML missing from "
                        f"env?)")
        mismatches = verify_stopping_target_gdml(gdml_path, geom_text)
        if mismatches:
            listed = "\n".join(f"    {m}" for m in mismatches[:10])
            return fail(f"as-built geometry differs from geom file "
                        f"({len(mismatches)} mismatches):\n{listed}")
        radii_m = re.search(
            r"vector<double>\s+stoppingTarget\.radii\s*=\s*\{([^}]*)\}",
            geom_text)
        n_foils = len(radii_m.group(1).split(",")) if radii_m else 0
        notes.append(f"geometry assertion: {n_foils} foils verified against "
                     f"as-built GDML (rIn/rOut/thickness)")

    # Surface-check emits advisory GeomVol1002 warnings on every baseline
    # overlap (~117 in stock geometry), so the geom_fail regex is only
    # consulted when construction actually aborted (past_init=False).
    if checks_managed_overlap:
        all_hits = SURFACE_OVERLAP_RX.findall(out)
        unique_all = sorted(set(all_hits))
        managed_hits = [v for v in all_hits if SURFACE_OVERLAP_MANAGED.match(v)]
        unique_managed = sorted(set(managed_hits))
        baseline_count = len(all_hits) - len(managed_hits)
        notes.append(f"surface-check total_hits={len(all_hits)} "
                     f"unique_volumes={len(unique_all)} "
                     f"baseline={baseline_count} managed={len(managed_hits)}")
        # Strict policy first, so the reported reason is the real one. The
        # name-based managed/baseline split falsely assumes "not named like
        # a BO volume" => "independent of BO knobs": IPAsupport_* sits at a
        # z derived from targetEnd (MECOStyleProtonAbsorberMaker.cc:124-129);
        # foilsflashRUN1BAP01 introduced 3 such overlaps and still PASSED.
        # Studies whose release can reach zero opt into failing on ANY
        # overlap.
        if require_zero_overlaps and all_hits:
            listed = "\n".join(
                f"    {v}"
                f"{'  [managed]' if SURFACE_OVERLAP_MANAGED.match(v) else ''}"
                for v in unique_all)
            return fail(f"zero-overlap policy: {len(all_hits)} overlap(s) in "
                        f"{len(unique_all)} volume(s):\n{listed}"
                        + _overlap_context(out, unique_managed or unique_all))
        if managed_hits:
            listed = "\n".join(f"    {v}" for v in unique_managed)
            return fail(f"managed-volume overlap detected:\n{listed}"
                        + _overlap_context(out, unique_managed))
        if baseline_count:
            notes.append(f"(info) {baseline_count} known stock-geometry "
                         f"overlaps ({len(unique_all)} unique volumes); "
                         f"ignored — not managed by BO knobs.")

    if not past_init:
        geom_fail = G4_GEOM_FAIL_RX.search(out)
        if geom_fail:
            snippet = out[max(0, geom_fail.start() - 200): geom_fail.end() + 600]
            return fail(f"Geant4 geometry error:\n{snippet}")

    if timed_out or rc == 0 or past_init:
        return Verdict(True, "pass",
                       f"init=True; no geom-fail signature"
                       f"{overlap_banner(checks_managed_overlap, require_zero_overlaps)}.",
                       tuple(notes))

    tail = "\n".join(out.splitlines()[-40:])
    return Verdict(False, "ambiguous",
                   f"rc={rc}, no geom-fail signature. Last 40 lines of "
                   f"log:\n{tail}", tuple(notes))
```

- [ ] **Step 5: `core/runtime.py` re-exports the two constants**

Replace the line
```python
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
```
with
```python
# The geometry pre-check owns these two (core/adapters/preflight_checks.py),
# so the engine's offline_preflight kit reads them without importing this
# mode-resolving module.
from adapters.preflight_checks import SETUPMU2E  # noqa: E402
from adapters.preflight_checks import TIMEOUT_S as PREFLIGHT_TIMEOUT_S  # noqa: E402
```
and delete these two lines further down:
```python
# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
PREFLIGHT_TIMEOUT_S = 1200
```

- [ ] **Step 6: `core/bo_driver.py` delegates**

1. Delete `import re` (line 22); nothing else in the module uses it once the block below is gone.
2. Replace
```python
from runtime import PREFLIGHT_TIMEOUT_S, SETUPMU2E  # noqa: E402
sys.path.insert(0, str(ROOT / "graph"))
from sourced_bash import run_sourced_bash  # noqa: E402
```
with
```python
from runtime import PREFLIGHT_TIMEOUT_S  # noqa: E402
sys.path.insert(0, str(ROOT / "graph"))
# The geometry pre-check, shared with the engine's offline_preflight kit
# (Phase C2a). PREFLIGHT_VERDICTS stays importable from here.
from adapters import preflight_checks as pc  # noqa: E402
from adapters import prodtools_entry as pe  # noqa: E402
from adapters.preflight_checks import PREFLIGHT_VERDICTS  # noqa: E402
```
3. Delete everything from the line `G4_GEOM_FAIL_RX = re.compile(` (line 380) down to and including the two-line `PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init",` / `                      3: "ambiguous"}` (lines 515-516), so `write_json_atomic` directly follows `cmd_evaluate`. This removes `G4_*`, `SURFACE_*`, `PREFLIGHT_GDML_*`, `GDML_FOIL_TUBE_RX`, `verify_stopping_target_gdml`, `_overlap_banner` and the old `PREFLIGHT_VERDICTS`.
4. Add after `write_json_atomic`:
```python
_VERDICT_LABELS = {"pass": "PASS", "fail_managed": "FAIL",
                   "ambiguous": "AMBIGUOUS"}
_RC_OF_VERDICT = {v: k for k, v in PREFLIGHT_VERDICTS.items()}
```
5. Replace the whole of `_cmd_preflight_impl` with:
```python
def _cmd_preflight_impl(args):
    mode = MODES[args.mode]
    spec = _modes.SPECS[mode.name]

    import harvest as _harvest
    import paths as _paths
    # Preflight runs first, so a missing backing surfaces here -- including
    # harvest's Run1BAna artifacts, which no earlier step touches.
    _paths.verify([spec], extra=_harvest.REQUIRED_ARTIFACTS, make_dirs=False)

    name = args.config_name
    geom = mode.proposal_dir / f"{name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 2
    geom_text = geom.read_text()

    mode.preflight_dir.mkdir(parents=True, exist_ok=True)
    # The code the grid jobs run: the mode's code tarball, unpacked once per
    # content, so preflight and grid cannot diverge (the prodtarget
    # env-divergence and foilsg holeRadii incidents).
    code_dir = pe.unpacked(spec.grid_tarball, GRID_DATA_ROOT / "_code")
    workdir = GRID_DATA_ROOT / name / "preflight"
    pc.stage_workdir(workdir, geom_text=geom_text,
                     geom_basename=pc.geom_name(name),
                     dumps_gdml=spec.dumps_gdml)
    log = mode.preflight_dir / f"{name}.log"
    print(f"[preflight/{mode.name}] cfg={name}  workdir={workdir}  log={log}")
    print(f"[preflight/{mode.name}] geom: {geom}  fcl: {pc.FCL_NAME}")

    out, rc, timed_out = pc.run_check(code_dir, workdir, pc.FCL_NAME,
                                      timeout_s=PREFLIGHT_TIMEOUT_S,
                                      label=f"preflight/{mode.name}")
    log.write_text(out)
    print(f"[preflight/{mode.name}] return code: {rc}  timed_out={timed_out}")

    gdml = workdir / pc.PREFLIGHT_GDML_NAME
    verdict = pc.classify(out, rc, timed_out, geom_text=geom_text,
                          gdml_path=gdml,
                          verifies_foil_gdml=spec.verifies_foil_gdml,
                          checks_managed_overlap=spec.checks_managed_overlap,
                          require_zero_overlaps=spec.require_zero_overlaps)
    for note in verdict.notes:
        print(f"[preflight/{mode.name}] {note}")
    if spec.verifies_foil_gdml and gdml.exists():
        # Kept where the pipeline has always kept it.
        keep_dir = GRID_DATA_ROOT / name / "geom"
        keep_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gdml, keep_dir / f"asbuilt_{name}.gdml")
    print(f"[preflight/{mode.name}] {_VERDICT_LABELS[verdict.code]}  "
          f"{verdict.reason}")
    if verdict.code == "ambiguous":
        print(f"[preflight/{mode.name}] See {log}")
    return _RC_OF_VERDICT[verdict.code]
```
`cmd_preflight` is unchanged: it still maps the rc through `PREFLIGHT_VERDICTS`.

- [ ] **Step 7: Move the old tests and repoint the overlap-policy imports**

In `tests/test_audit_fixes.py`, delete from the line `class TestPreflightFatalAbortClassification(unittest.TestCase):` down to (not including) the line `import bo_driver as bo  # noqa: E402` (lines 506-642): both classes now live in `tests/test_preflight_checks.py`.

In `tests/test_zero_overlap_policy.py`, replace
```python
from bo_driver import (  # noqa: E402
    SURFACE_OVERLAP_MANAGED,
    SURFACE_OVERLAP_RX,
    _overlap_banner,
)
```
with
```python
from adapters.preflight_checks import (  # noqa: E402
    SURFACE_OVERLAP_MANAGED,
    SURFACE_OVERLAP_RX,
    overlap_banner,
)
```
and replace
```python
    def test_banner_reports_strict_policy(self):
        self.assertEqual(_overlap_banner("foilsflash"),
                         " and zero surface-check overlaps")
```
with
```python
    def test_banner_reports_strict_policy(self):
        spec = modes.SPECS["foilsflash"]
        self.assertEqual(overlap_banner(spec.checks_managed_overlap,
                                        spec.require_zero_overlaps),
                         " and zero surface-check overlaps")
```

- [ ] **Step 8: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_preflight_checks tests.test_zero_overlap_policy tests.test_audit_fixes tests.test_seam_protocol tests.test_runtime_constants -v`
Expected: PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: every section passes (no study or `ModeSpec` changed).

- [ ] **Step 9: Commit**

```bash
git add core/adapters/preflight_checks.py core/bo_driver.py core/runtime.py \
  tests/preflight_logs.py tests/test_preflight_checks.py \
  tests/test_audit_fixes.py tests/test_zero_overlap_policy.py
git commit -F - <<'EOF'
refactor(preflight): shared pre-check functions; the pipeline's check runs from the code tarball

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 3: `code_tarball` replaces `musing`; the pre-check and the jobs must name one tarball

**Files:**
- Modify: `core/kit_registry.py` (`offline_preflight` study keys; `MATCHING_SETTINGS`, `check_matching_settings`)
- Modify: `core/study.py` (`_kits_and_preflight` calls the check)
- Modify: `core/modes.py` (`ModeSpec.musing` removed), `core/study_compat.py`, `core/runtime.py` (`MUSING` removed)
- Modify: `core/pipeline.py` (`sourced_env` sources the code tarball's `Code/setup.sh`), `core/paths.py` (`verify`)
- Modify: `mode_specs/{foilsflash,foilspf,foilspf2k,foilspfbp,foilspfbpx,foilspfbpz,foilspfbw}.json`, `tests/fixtures/studies/demo.json`, `tests/fixtures/modes/template.json`
- Modify: `tests/golden_parity.py` (section d)
- Test: `tests/test_study.py`, `tests/test_modes.py`, `tests/test_study_compat.py`, `tests/test_foilspf_spec.py`, `tests/test_paths.py`, `tests/test_pipeline_verbs.py`, `tests/test_runtime_constants.py`

**Interfaces:**
- Consumes: `prodtools_entry.unpacked` (Task 1).
- Produces: `KITS["offline_preflight"].study_keys == {"code_tarball", "dumps_gdml", "verifies_foil_gdml", "checks_managed_overlap", "require_zero_overlaps"}` (all required); `kit_registry.MATCHING_SETTINGS`; `kit_registry.check_matching_settings(kits: dict, where: str) -> None` (raises `ValueError`); `ModeSpec` without `musing`; `runtime` without `MUSING`; `paths.verify` reads only `.name` and `.grid_tarball` of each spec.

Why the pipeline's `sourced_env` changes here: it sourced the mode's musing before `muse setup ops`, because `json2jobdef` needs `mu2e` on PATH. With `musing` gone it sources the unpacked code tarball's `Code/setup.sh` instead — the environment prodtools' own write server builds for a code entry.

- [ ] **Step 1: Write the failing tests**

In `tests/test_study.py`:

(a) In `TestArtifactExpansion._expanded`, set both kits (the loader now refuses them differing):
```python
    def _expanded(self, rel):
        doc = _doc()
        doc["kits"]["prodtools"]["code_tarball"] = "${ARTIFACT}/" + rel
        doc["kits"]["offline_preflight"]["code_tarball"] = "${ARTIFACT}/" + rel
        return self.load(doc).kits["prodtools"]["code_tarball"]
```
(b) In `TestKits.test_unknown_variable_token_refused`, change `doc["kits"]["offline_preflight"]["musing"] = "${HOME}/x/setup.sh"` to `doc["kits"]["offline_preflight"]["code_tarball"] = "${HOME}/x/Code.tar.bz2"`.
(c) Add after `TestKits`:
```python
class TestMatchingSettings(_Tmp):
    def test_the_pre_check_and_the_jobs_must_name_one_code_tarball(self):
        doc = _doc()
        doc["kits"]["offline_preflight"]["code_tarball"] = \
            "${ARTIFACT}/demo/Other.tar.bz2"
        self.assertRejects(doc, "[kits.offline_preflight.code_tarball]",
                           "${ARTIFACT}/demo/Other.tar.bz2",
                           "kits.prodtools.code_tarball",
                           "${ARTIFACT}/demo/Code_demo.tar.bz2")

    def test_the_fixture_names_one_tarball_for_both(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.kits["offline_preflight"]["code_tarball"],
                         s.kits["prodtools"]["code_tarball"])
        self.assertNotIn("musing", s.kits["offline_preflight"])

    def test_the_rule_needs_both_kits(self):
        kit_registry.check_matching_settings(
            {"offline_preflight": {"code_tarball": "a"}}, "w")
```

In `tests/test_modes.py`, `test_every_fact_populated`: replace `self.assertTrue(spec.musing.startswith("/"), name)` with `self.assertTrue(spec.grid_tarball.startswith("/"), name)` and add `self.assertFalse(hasattr(spec, "musing"), name)`.

In `tests/test_study_compat.py`, `test_pipeline_fields`: replace `self.assertTrue(s.musing.endswith("demo/setup_local.sh"))` with `self.assertFalse(hasattr(s, "musing"))`.

In `tests/test_foilspf_spec.py`, `test_run_configuration_matches_foilsflash`: delete the line `self.assertEqual(s.musing, ff.musing)` (the loader's equal-tarball rule now covers the pre-check).

In `tests/test_runtime_constants.py`, remove `"MUSING"` from `NAMES` (the last element: the line becomes `"PRESUBMIT_AFTER",` followed by `]`).

In `tests/test_paths.py`: replace `FakeSpec` with
```python
class FakeSpec:
    def __init__(self, name, grid_tarball):
        self.name, self.grid_tarball = name, grid_tarball
```
and update its six call sites exactly:
- `p.verify([FakeSpec("m", str(setup), str(tarball))])` → `p.verify([FakeSpec("m", str(tarball))])`
- every `FakeSpec("m", str(setup), str(setup))` (four places) → `FakeSpec("m", str(setup))`
- in `test_missing_artifact_names_the_remediation_command`, `p.verify([FakeSpec("m", str(self.tmp / "gone.sh"),` / `str(self.tmp / "gone.tar.bz2"))])` → `p.verify([FakeSpec("m", str(self.tmp / "gone.tar.bz2"))])`, and its `self.assertIn("gone.sh", msg)` → `self.assertIn("gone.tar.bz2", msg)`.

In `tests/test_pipeline_verbs.py`, class `TestSourcedEnvGuards`: replace the class docstring's "and the missing-musing guard" with "and the missing-code-tarball guard", replace `setUp` and `test_a_missing_musing_fails_fast_instead_of_retrying` with:
```python
    def setUp(self):
        # sourced_env stats the code tarball and unpacks it before shelling
        # out, so point both at stand-ins -- these cases are about
        # everything AFTER that, and the suite must stay green on a machine
        # with no /exp/mu2e.
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tarball = Path(self._td.name) / "Code.tar.bz2"
        self.tarball.write_text("")
        self.code = Path(self._td.name) / "code"
        for patcher in (
                mock.patch.object(pipeline, "MUSE_BASE_TARBALL", self.tarball),
                mock.patch.object(pipeline.pe, "unpacked",
                                  return_value=self.code)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_missing_code_tarball_fails_fast_instead_of_retrying(self):
        # `source <missing>` is rc=1, the same rc as the cvmfs/spack flake the
        # retry loop exists for; a ${ARTIFACT} path resolves under the
        # CALLING operator's app area, so a second operator hits this on a
        # first direct `pipeline.py ... submit`, which never runs preflight.
        import paths
        with mock.patch.object(pipeline, "MUSE_BASE_TARBALL",
                               Path("/nonexistent/Code.tar.bz2")), \
             mock.patch.object(pipeline, "run_sourced_bash") as rsb:
            with self.assertRaises(paths.PathsError) as cm:
                pipeline.sourced_env()
        rsb.assert_not_called()
        pipeline.pe.unpacked.assert_not_called()
        msg = str(cm.exception)
        self.assertIn("/nonexistent/Code.tar.bz2", msg)
        self.assertIn("setup.sh --backing", msg)

    def test_the_prelude_sources_the_code_tarballs_own_setup(self):
        with mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout="", stderr="")) as rsb:
            pipeline.sourced_env()
        pipeline.pe.unpacked.assert_called_once_with(
            self.tarball, pipeline.DATA_ROOT / "_code")
        cmd = rsb.call_args[0][0]
        self.assertIn(f"source {self.code}/Code/setup.sh && muse setup ops",
                      cmd)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study tests.test_modes tests.test_study_compat tests.test_paths tests.test_pipeline_verbs.TestSourcedEnvGuards tests.test_runtime_constants -v`
Expected: FAIL — `check_matching_settings` is missing, `ModeSpec` still has `musing`, and `sourced_env` still stats and sources `MUSING` (so `pe.unpacked` is never called). `tests/test_runtime_constants.py` passes before and after: it checks only that the listed names exist.

- [ ] **Step 3: The registry and the loader**

In `core/kit_registry.py`, change the `offline_preflight` declaration's `study_keys` to:
```python
            study_keys={"code_tarball": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
```
(leave its other fields as they are), and add after the `KITS` table:
```python
# Settings two kits must agree on when a study uses both:
# (kit, key, other kit, other key, why).
MATCHING_SETTINGS = (
    ("offline_preflight", "code_tarball", "prodtools", "code_tarball",
     "the geometry pre-check must run the code the jobs run, or a geometry "
     "it passes can build differently on the grid (the env-divergence "
     "incidents)"),
)


def check_matching_settings(kits: dict, where: str) -> None:
    """Refuse a study whose kits disagree on a MATCHING_SETTINGS pair.
    `kits` is study["kits"] as written, so the message names the values
    the author wrote."""
    for kit, key, other, other_key, why in MATCHING_SETTINGS:
        if kit in kits and other in kits:
            mine, theirs = kits[kit].get(key), kits[other].get(other_key)
            if mine != theirs:
                raise ValueError(
                    f"{where}[kits.{kit}.{key}]: {mine!r} differs from "
                    f"kits.{other}.{other_key} {theirs!r}; the two must "
                    f"name the same file: {why}")
```

In `core/study.py`, `_kits_and_preflight`, add just before `return kits, pre`:
```python
    kit_registry.check_matching_settings(kits_raw, where)
```

- [ ] **Step 4: `ModeSpec`, `runtime`, `paths.verify`**

- `core/modes.py`: delete the line `    musing: str` from `ModeSpec`.
- `core/study_compat.py`: delete the line `        musing=pre["musing"],` from the `ModeSpec(...)` call.
- `core/runtime.py`: delete the line `MUSING = _SPEC.musing` (and the blank line it leaves doubled).
- `core/paths.py`, `verify`: change the docstring's `` `specs`: iterable with .name/.musing/.grid_tarball `` to `` `specs`: iterable with .name/.grid_tarball ``, and the loop head `for field in ("musing", "grid_tarball"):` to `for field in ("grid_tarball",):`.

- [ ] **Step 5: The pipeline's `sourced_env`**

In `core/pipeline.py`, change `from runtime import MUSING, SETUPMU2E  # noqa: E402` to `from runtime import SETUPMU2E  # noqa: E402`; change the first line of `sourced_env`'s docstring to `"""Return an env dict with setupmu2e-art.sh + the code tarball's setup + ops tooling sourced.`; and replace, in its `else:` branch, the block from `        # Stat MUSING first:` through the closing `        )` of `prelude` with:
```python
        # The mode's code tarball's own Code/setup.sh, as the grid jobs and
        # the geometry pre-check source it: json2jobdef needs `mu2e` on PATH
        # (prodtools' write server builds the same environment for a code
        # entry). Stat the tarball first: `source` on a missing file is
        # rc=1, the same rc as that flake, so an unresolvable tarball (any
        # operator without the artifact, on a path that never ran
        # preflight's paths.verify()) would burn all four retries and name
        # only the command line. SETUPMU2E is deliberately NOT checked: it
        # lives on cvmfs, where "missing" is usually the transient the
        # retries recover.
        import paths  # see core/paths.py
        paths.require(MUSE_BASE_TARBALL, "the mode's code tarball")
        code_dir = pe.unpacked(MUSE_BASE_TARBALL, DATA_ROOT / "_code")
        prelude = (
            f"source {SETUPMU2E} && "
            f"source {code_dir}/Code/setup.sh && "
            f"muse setup ops && "
        )
```

- [ ] **Step 6: The study files**

Run once from the repo root; every file carries exactly one `musing` setting, which becomes its own prodtools `code_tarball`:

```python
import json, pathlib, re
FILES = ["mode_specs/foilsflash.json", "mode_specs/foilspf.json",
         "mode_specs/foilspf2k.json", "mode_specs/foilspfbp.json",
         "mode_specs/foilspfbpx.json", "mode_specs/foilspfbpz.json",
         "mode_specs/foilspfbw.json", "tests/fixtures/studies/demo.json",
         "tests/fixtures/modes/template.json"]
for f in FILES:
    p = pathlib.Path(f)
    s = p.read_text()
    code = json.loads(s)["kits"]["prodtools"]["code_tarball"]
    old = re.findall(r'"offline_preflight": \{"musing": "[^"]*"', s)
    assert len(old) == 1 and s.count('"musing"') == 1, f
    s = s.replace(old[0], f'"offline_preflight": {{"code_tarball": "{code}"')
    p.write_text(s)
    kits = json.loads(s)["kits"]
    assert kits["offline_preflight"]["code_tarball"] == code, f
```

Then `git diff --stat` must show exactly those 9 files with 2 lines changed each (one line out, one in).

- [ ] **Step 7: Golden (d) declares the dropped field**

In `tests/golden_parity.py`:
- `_SPEC_FIELDS`: remove `"musing", ` (the first line becomes `"name", "grid_tarball", "grid_stages", "stage_target_overrides",`).
- `section_d`: `for field in ("musing", "grid_tarball"):` → `for field in ("grid_tarball",):`; in its docstring, `` `musing`/`grid_tarball` are recorded `` → `` `grid_tarball` is recorded ``.
- `_portable_artifact_path`'s docstring: `musing/grid_tarball on a live ModeSpec are` → `grid_tarball on a live ModeSpec is`.
- after `_quorum_on_elebeam_flash`, add:
```python
def _drop_musing(base):
    """Intended Phase-C2a change (preflight-kit spec, "Settings and
    registry"): the pre-check runs from the prodtools code tarball, so
    ModeSpec no longer has a musing."""
    for rec in base.values():
        rec.pop("musing", None)
```
- `_declared_changes` gains a third line `    _drop_musing(base)`.
- The module docstring's (d) paragraph: `(`_declared_changes`: the per-event fallback drop, and C1's elebeam_flash quorum)` → `(`_declared_changes`: the per-event fallback drop, C1's elebeam_flash quorum, and C2a's dropped musing)`.

- [ ] **Step 8: Run the tests and the golden**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: every section passes.

- [ ] **Step 9: Commit**

```bash
git add core/kit_registry.py core/study.py core/modes.py core/study_compat.py \
  core/runtime.py core/pipeline.py core/paths.py \
  mode_specs/foilsflash.json mode_specs/foilspf.json mode_specs/foilspf2k.json \
  mode_specs/foilspfbp.json mode_specs/foilspfbpx.json mode_specs/foilspfbpz.json \
  mode_specs/foilspfbw.json tests/fixtures/studies/demo.json \
  tests/fixtures/modes/template.json tests/golden_parity.py \
  tests/test_study.py tests/test_modes.py tests/test_study_compat.py \
  tests/test_foilspf_spec.py tests/test_paths.py tests/test_pipeline_verbs.py \
  tests/test_runtime_constants.py
git commit -F - <<'EOF'
feat(registry): the pre-check names the jobs' code_tarball; musing is gone

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 4: The `offline_preflight` adapter

**Files:**
- Create: `core/adapters/offline_preflight.py`
- Modify: `core/adapters/__init__.py` (register it), `core/adapters/prodtools.py` (`config_problem`, used by `split_handle`)
- Modify: `core/kit_registry.py` (`offline_preflight` gets `engine=True`)
- Modify: `core/contract.py` (`check_kits`: a kit used only for the preflight needs only `check`)
- Create: `tests/test_offline_preflight_kit.py`
- Modify: `tests/test_contract.py`, `tests/test_kit_config.py`

**Interfaces:**
- Consumes: `pc.stage_workdir`, `pc.geom_name`, `pc.run_check`, `pc.classify`, `pc.FCL_NAME`, `pc.PREFLIGHT_GDML_NAME`, `pc.TIMEOUT_S` (Task 2); `pe.unpacked` (Task 1).
- Produces:
  - `prodtools.config_problem(config: str) -> str | None` — why `config` cannot name a prodtools run (letters, digits and `_` only), or `None`.
  - `OfflinePreflightKit(campaign, *, executor="grid", parallel=None, grid_root=None, runner=None, timeout_s=None)`; `name = "offline_preflight"`, `accepts_lists = False`, `EXECUTORS = ("grid", "local")`, `REQUIRES_KERBEROS = False`, `LAUNCH_STAGGER_S = 0`; `version -> "offline-preflight-adapter/1"`; `tools -> frozenset({"check", "describe"})`; `describe() -> Describe(PARAMS, (), False)`; `check(name, params, files, inputs, workflow) -> (bool, str)`; `close()`.
  - module constants `PARAMS = ("code_tarball", "dumps_gdml", "verifies_foil_gdml", "checks_managed_overlap", "require_zero_overlaps")`, `ASBUILT_NAME = "asbuilt.gdml"`, `LOG_NAME = "preflight.log"`.
  - `runner(code_dir, workdir, fcl, *, timeout_s, label) -> (out, rc, timed_out)` is the injection seam (default `pc.run_check`).

The engine needs no change: `graph/study_graph.py:node_preflight` already calls `kit.check(f"{config}.preflight", params, files, [], workflow)`, with `params` = the preflight's mapped params merged with `study.kits[<preflight kit>]` (so `code_tarball` and the four flags arrive as params), and turns `(False, message)` or a `ValueError` into `broken.txt`. Only `check_kits` changes, because it demanded `submit`/`status`/`results` of every kit, and this one runs no step.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_offline_preflight_kit.py`:

```python
"""core/adapters/offline_preflight.py: the geometry pre-check as a contract
kit (Phase C2a). run_check is replaced by a fake returning recorded output;
the unpack cache, the workdir and the verdict are real."""
import json
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402
from adapters import offline_preflight as op  # noqa: E402
from adapters import preflight_checks as pc  # noqa: E402
from study_graph import build_study_graph  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES, write_study  # noqa: E402
from tests.preflight_logs import (CLEAN_LOG, FATAL_LOG, GEOM,  # noqa: E402
                                  NO_MU2E_LOG, gdml_matching)


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.base = self.tarball(self.tmp / "Code_base.tar.bz2")
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text(GEOM)
        self.runs = []

    def tarball(self, path, *, with_setup=True):
        code = self.tmp / "src" / path.name / "Code"
        code.mkdir(parents=True)
        (code / ("setup.sh" if with_setup else "README")).write_text("x\n")
        with tarfile.open(path, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        return path

    def fake(self, out, rc, *, gdml_text=None, timed_out=False):
        """A run_check stand-in: records its call, optionally writes the
        GDML dump G4 would have written, returns the recorded output."""
        def run(code_dir, workdir, fcl, *, timeout_s, label):
            self.runs.append((Path(code_dir), Path(workdir), fcl, timeout_s,
                              label))
            if gdml_text is not None:
                (Path(workdir) / pc.PREFLIGHT_GDML_NAME).write_text(gdml_text)
            return out, rc, timed_out
        return run

    def kit(self, runner=None, **kw):
        return op.OfflinePreflightKit(
            "camp", executor="local", grid_root=self.tmp / "grid",
            runner=runner or self.fake(CLEAN_LOG, 0), **kw)

    def params(self, **over):
        p = {"code_tarball": str(self.base), "dumps_gdml": False,
             "verifies_foil_gdml": False, "checks_managed_overlap": True,
             "require_zero_overlaps": False}
        p.update(over)
        return p

    def files(self, uri=None):
        return [{"name": "geom", "uri": uri or self.geom.as_uri(),
                 "kind": "geom"}]

    def check(self, kit=None, name="cfg1.preflight", files=None, inputs=(),
              **over):
        return (kit or self.kit()).check(
            name, self.params(**over), self.files() if files is None else files,
            list(inputs), "camp/cfg1/preflight")

    def workdir(self, config="cfg1"):
        return self.tmp / "grid" / config / "preflight"


class TestCheck(_Kit):
    def test_a_passing_geometry_runs_from_the_unpacked_tarball(self):
        ok, message = self.check()
        self.assertTrue(ok, message)
        self.assertTrue(message.startswith("pass: init=True"), message)
        ((code_dir, workdir, fcl, timeout_s, label),) = self.runs
        self.assertEqual(code_dir.parent, self.tmp / "grid" / "_code")
        self.assertTrue((code_dir / "Code" / "setup.sh").is_file())
        self.assertEqual((workdir, fcl, timeout_s),
                         (self.workdir(), "surfacecheck.fcl", pc.TIMEOUT_S))
        self.assertIn("cfg1", label)

    def test_the_workdir_holds_the_geometry_the_check_files_and_the_log(self):
        stale = self.workdir() / "left_over.txt"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")
        self.check()
        self.assertEqual(sorted(p.name for p in self.workdir().iterdir()),
                         ["autoresearch_cfg1_geom.txt", "preflight.log",
                          "surfacecheck.fcl",
                          "surfacecheck_autoresearch_cfg1_geom.txt"])
        self.assertEqual(
            (self.workdir() / "autoresearch_cfg1_geom.txt").read_text(), GEOM)
        self.assertEqual((self.workdir() / "preflight.log").read_text(),
                         CLEAN_LOG)

    def test_a_fatal_abort_fails_with_the_verdict_code(self):
        ok, message = self.check(self.kit(self.fake(FATAL_LOG, 134)))
        self.assertFalse(ok)
        self.assertTrue(message.startswith("fail_managed: fatal G4/art abort:"),
                        message)

    def test_ambiguous_fails_and_carries_the_log_tail(self):
        ok, message = self.check(self.kit(self.fake(NO_MU2E_LOG, 127)))
        self.assertFalse(ok)
        self.assertTrue(message.startswith("ambiguous: rc=127"), message)
        self.assertIn("mu2e: command not found", message)

    def test_the_as_built_gdml_is_verified_and_kept(self):
        ok, message = self.check(
            self.kit(self.fake(CLEAN_LOG, 0, gdml_text=gdml_matching(GEOM))),
            dumps_gdml=True, verifies_foil_gdml=True)
        self.assertTrue(ok, message)
        self.assertTrue((self.workdir() / op.ASBUILT_NAME).is_file())
        self.assertFalse((self.workdir() / pc.PREFLIGHT_GDML_NAME).exists())
        self.assertIn("writeGDML",
                      (self.workdir() / "surfacecheck.fcl").read_text())

    def test_a_stale_gdml_in_the_workdir_is_not_read(self):
        """A rerun whose G4 run wrote no GDML must not verify against the
        last run's dump: the workdir is emptied first."""
        self.workdir().mkdir(parents=True)
        for name in (pc.PREFLIGHT_GDML_NAME, op.ASBUILT_NAME):
            (self.workdir() / name).write_text(gdml_matching(GEOM))
        ok, message = self.check(dumps_gdml=True, verifies_foil_gdml=True)
        self.assertFalse(ok)
        self.assertIn("not produced", message)
        self.assertFalse((self.workdir() / op.ASBUILT_NAME).exists())

    def test_two_checks_at_once_share_one_unpacked_tree(self):
        kit = self.kit()
        results, errors = [], []

        def check(config):
            try:
                results.append(self.check(kit, name=f"{config}.preflight"))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=check, args=(c,))
                   for c in ("cfgA", "cfgB")]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertTrue(all(ok for ok, _m in results), results)
        self.assertEqual(len(list((self.tmp / "grid" / "_code").iterdir())), 1)


class TestRefusals(_Kit):
    def assertRefused(self, *needles, **kw):
        with self.assertRaises(ValueError) as cm:
            self.check(**kw)
        for needle in needles:
            self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.runs, [])

    def test_a_config_name_prodtools_cannot_carry(self):
        self.assertRefused("'-'", "only letters, digits and _",
                           name="cfg-1.preflight")

    def test_a_name_that_is_not_config_dot_preflight(self):
        self.assertRefused("<config>.preflight", name="cfg1.mubeam")
        self.assertRefused("<config>.preflight", name="preflight")

    def test_a_geometry_that_is_not_a_local_file(self):
        self.assertRefused("file://",
                           files=self.files("root://fndca/pnfs/geom.txt"))

    def test_no_geometry_file(self):
        self.assertRefused("'geom'", files=[])

    def test_inputs(self):
        self.assertRefused("no inputs", inputs=[self.files()[0]])

    def test_an_unknown_or_missing_param(self):
        self.assertRefused("musing", musing="/x/setup.sh")
        with self.assertRaises(ValueError) as cm:
            self.kit().check("cfg1.preflight", {"code_tarball": str(self.base)},
                             self.files(), [], "w")
        self.assertIn("dumps_gdml", str(cm.exception))

    def test_a_missing_or_codeless_tarball_names_it(self):
        self.assertRefused("gone.tar.bz2",
                           code_tarball=str(self.tmp / "gone.tar.bz2"))
        bare = self.tarball(self.tmp / "Bare.tar.bz2", with_setup=False)
        self.assertRefused(str(bare), "Code/setup.sh", code_tarball=str(bare))


class TestKitInterface(_Kit):
    def test_describe_tools_version_and_launch_attributes(self):
        kit = self.kit()
        self.assertEqual(kit.tools, frozenset({"check", "describe"}))
        self.assertEqual(kit.describe(),
                         ct.Describe(op.PARAMS, (), False))
        self.assertEqual(kit.version, "offline-preflight-adapter/1")
        self.assertEqual((op.OfflinePreflightKit.EXECUTORS,
                          op.OfflinePreflightKit.REQUIRES_KERBEROS,
                          op.OfflinePreflightKit.LAUNCH_STAGGER_S),
                         (("grid", "local"), False, 0))

    def test_an_unknown_executor_is_refused(self):
        with self.assertRaises(ValueError):
            op.OfflinePreflightKit("camp", executor="cloud")

    def test_it_opens_as_the_adapter_and_runs_on_both_runners(self):
        kit = ct.open_kit("offline_preflight", "camp", executor="local")
        self.assertIsInstance(kit, op.OfflinePreflightKit)
        d = kit_registry.KITS["offline_preflight"]
        self.assertTrue(d.engine and d.pipeline and d.check_kit)
        self.assertFalse(d.step_kit)


class TestInThePointGraph(_Kit):
    def test_a_failing_pre_check_marks_the_point_broken_and_submits_nothing(self):
        """The engine's node_preflight, unchanged, hands the kit the study's
        settings as params and turns its verdict into broken.txt."""
        doc = json.loads((ENGINE_STUDIES / "prodtools_smoke.json").read_text())
        doc["name"] = "pcgraph"
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_pcgraph.tsv"
        code = "${ARTIFACT}/Code_base.tar.bz2"
        doc["kits"]["prodtools"]["code_tarball"] = code
        doc["kits"]["offline_preflight"] = {
            "code_tarball": code, "dumps_gdml": False,
            "verifies_foil_gdml": False, "checks_managed_overlap": True,
            "require_zero_overlaps": True}
        doc["preflight"] = {"kit": "offline_preflight", "params": {},
                            "files": ["geom"]}
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp):
            study = st.load_study_file(write_study(doc, self.tmp / "studies"))
        kit = self.kit(self.fake(FATAL_LOG, 134))
        opened = []

        class Kits:
            def get(self, name):
                opened.append(name)
                if name != "offline_preflight":
                    raise AssertionError(f"kit {name!r} was opened")
                return kit

        state = self.tmp / "grid" / "pcg01" / "state"
        build_study_graph(study, config="pcg01", campaign="c", context={},
                          kits=Kits(), state_dir=state, board=None,
                          log=lambda m: None, executor="local").compile() \
            .invoke({"config_name": "pcg01", "x_point": []})
        self.assertTrue((state / "broken.txt").read_text().startswith(
            "preflight: fail_managed: fatal G4/art abort:"))
        verdict = json.loads((state / "preflight_verdict.json").read_text())
        self.assertFalse(verdict["ok"])
        self.assertEqual(opened, ["offline_preflight"])
        self.assertFalse((self.tmp / "grid" / "pcg01" / "prodtools").exists())


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_contract.py`:
- add `from adapters import offline_preflight as op  # noqa: E402` next to the other imports;
- in `TestRegistry.test_only_an_engine_kit_without_a_kits_toml_entry_takes_an_adapter`, change `("toykit", "nosuchkit", "offline_preflight")` to `("toykit", "nosuchkit", "ce_sensitivity")`;
- in `TestRegistry.test_a_kit_with_neither_is_refused`, change `ct.open_kit("offline_preflight", "c")` to `ct.open_kit("ce_sensitivity", "c")`;
- add to `TestCheckKits`:
```python
    def preflight_only(self, doc):
        doc["kits"]["offline_preflight"] = {
            "code_tarball": "${ARTIFACT}/Code_x.tar.bz2", "dumps_gdml": False,
            "verifies_foil_gdml": False, "checks_managed_overlap": True,
            "require_zero_overlaps": False}
        doc["preflight"] = {"kit": "offline_preflight", "params": {},
                            "files": []}

    def test_a_kit_used_only_for_the_preflight_needs_only_check(self):
        study = self.study(self.preflight_only)

        def opener(name, campaign):
            if name == "offline_preflight":
                return op.OfflinePreflightKit(campaign)
            return self.open(name, campaign)

        self.assertEqual(ct.check_kits(study, campaign="c", opener=opener), [])

    def test_a_preflight_only_kit_without_check_is_refused(self):
        study = self.study(self.preflight_only)

        class NoCheck:
            accepts_lists = False
            tools = frozenset({"describe"})
            version = "1"

            def describe(self):
                return None

            def close(self):
                pass

        def opener(name, campaign):
            if name == "offline_preflight":
                return NoCheck()
            return self.open(name, campaign)

        problems = ct.check_kits(study, campaign="c", opener=opener)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("['check']", problems[0])
```

In `tests/test_kit_config.py`, replace `test_pipeline_kits_are_not_engine_kits` with:
```python
    def test_pipeline_kits_are_not_engine_kits(self):
        for name in ("ce_sensitivity", "flash_edep_per_pot"):
            with self.subTest(kit=name):
                self.assertFalse(kit_registry.KITS[name].engine)
                self.assertTrue(kit_registry.KITS[name].pipeline)

    def test_the_pre_check_kit_runs_on_both_runners(self):
        d = kit_registry.KITS["offline_preflight"]
        self.assertTrue(d.engine and d.pipeline)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_offline_preflight_kit tests.test_contract tests.test_kit_config -v`
Expected: FAIL — no module `adapters.offline_preflight`; `offline_preflight` is not an engine kit.

- [ ] **Step 3: Export the config-name rule from the prodtools adapter**

In `core/adapters/prodtools.py`, replace `split_handle` with:
```python
def config_problem(config: str):
    """Why `config` cannot name a prodtools run, or None. The config
    becomes part of prodtools' dot-separated run name, so only letters,
    digits and _."""
    if not config:
        return "config name is empty"
    if _CONFIG.fullmatch(config):
        return None
    bad = sorted(set(_CONFIG.sub("", config)))
    return (f"config name {config!r} has character(s) "
            f"{', '.join(repr(c) for c in bad)}; only letters, digits and _ "
            f"may appear, because the config is part of prodtools' "
            f"dot-separated run name")


def split_handle(name: str):
    """'<config>.<step>' -> (config, step); the config must pass
    config_problem."""
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"prodtools: {name!r} is not <config>.<step>")
    why = config_problem(config)
    if why:
        raise ValueError(f"prodtools: {why}")
    return config, step
```

- [ ] **Step 4: Create the adapter**

Create `core/adapters/offline_preflight.py`:

```python
"""The geometry pre-check as a contract kit: the adapter the engine drives
for a study whose preflight is `offline_preflight` (Phase C2a spec,
docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md, "1. The
offline_preflight kit").

check unpacks the study's code tarball (the one its prodtools steps ship,
so the pre-check runs the jobs' own code), writes the point's geometry
and the surface-check files into <GRID_DATA_ROOT>/<config>/preflight/,
runs `mu2e -n 1` there and reads the log into a verdict
(core/adapters/preflight_checks.py). It always runs on this node,
whatever --executor says: one event, no inputs.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ == "core.adapters":
    from core import paths
    from core.adapters import preflight_checks as pc
    from core.adapters import prodtools_entry as pe
    from core.adapters.prodtools import config_problem
    from core.contract import Describe
else:
    import paths
    from adapters import preflight_checks as pc
    from adapters import prodtools_entry as pe
    from adapters.prodtools import config_problem
    from contract import Describe

VERSION = "offline-preflight-adapter/1"   # bump when a verdict would change
PARAMS = ("code_tarball", "dumps_gdml", "verifies_foil_gdml",
          "checks_managed_overlap", "require_zero_overlaps")
ASBUILT_NAME = "asbuilt.gdml"
LOG_NAME = "preflight.log"


class OfflinePreflightKit:
    """One campaign child's pre-check. It offers only `check` and
    `describe`: a study names it as its preflight, never as a step."""

    name = "offline_preflight"
    accepts_lists = False
    EXECUTORS = ("grid", "local")
    REQUIRES_KERBEROS = False       # no inputs, no grid
    LAUNCH_STAGGER_S = 0

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 grid_root=None, runner=None, timeout_s=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"offline_preflight: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign, self.executor = campaign, executor
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._run = runner or pc.run_check
        self._timeout_s = pc.TIMEOUT_S if timeout_s is None else timeout_s

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return VERSION

    @property
    def tools(self) -> frozenset:
        return frozenset({"check", "describe"})

    def describe(self):
        return Describe(PARAMS, (), False)

    def close(self) -> None:
        pass

    def check(self, name, params, files, inputs, workflow):
        config = self._config_of(name)
        unknown = sorted(set(params) - set(PARAMS))
        if unknown:
            raise ValueError(f"offline_preflight: unknown param(s) {unknown}; "
                             f"it accepts {list(PARAMS)}")
        missing = [k for k in PARAMS if k not in params]
        if missing:
            raise ValueError(f"offline_preflight: param(s) {missing} are "
                             f"missing")
        if inputs:
            raise ValueError(f"offline_preflight: takes no inputs, got "
                             f"{len(inputs)}")
        geom = self._geom_path(files)
        code_dir = pe.unpacked(params["code_tarball"],
                               self._grid_root / "_code")
        workdir = self._grid_root / config / "preflight"
        geom_text = geom.read_text()
        pc.stage_workdir(workdir, geom_text=geom_text,
                         geom_basename=pc.geom_name(config),
                         dumps_gdml=params["dumps_gdml"])
        out, rc, timed_out = self._run(code_dir, workdir, pc.FCL_NAME,
                                       timeout_s=self._timeout_s,
                                       label=f"offline_preflight/{config}")
        (workdir / LOG_NAME).write_text(out)
        gdml = workdir / pc.PREFLIGHT_GDML_NAME
        verdict = pc.classify(
            out, rc, timed_out, geom_text=geom_text, gdml_path=gdml,
            verifies_foil_gdml=params["verifies_foil_gdml"],
            checks_managed_overlap=params["checks_managed_overlap"],
            require_zero_overlaps=params["require_zero_overlaps"])
        if gdml.exists():
            gdml.replace(workdir / ASBUILT_NAME)
        return verdict.ok, f"{verdict.code}: {verdict.reason}"

    # --- plumbing ----------------------------------------------------------
    @staticmethod
    def _config_of(name) -> str:
        config, dot, step = name.rpartition(".")
        if not dot or not config or step != "preflight":
            raise ValueError(f"offline_preflight: {name!r} is not "
                             f"<config>.preflight")
        why = config_problem(config)
        if why:
            raise ValueError(f"offline_preflight: {why}")
        return config

    @staticmethod
    def _geom_path(files) -> Path:
        geoms = [f for f in files if f.get("name") == "geom"]
        if len(geoms) != 1:
            raise ValueError(f"offline_preflight: needs exactly one file "
                             f"named 'geom', got "
                             f"{[f.get('name') for f in files]}")
        uri = geoms[0].get("uri", "")
        if not uri.startswith("file://"):
            raise ValueError(f"offline_preflight: the geom file is {uri!r}; "
                             f"only a file:// URI can be read on this node")
        return Path(unquote(urlparse(uri).path))
```

- [ ] **Step 5: Register it; flip the registry flag; the check-only rule**

Replace the body of `register_all` in `core/adapters/__init__.py`:
```python
def register_all(register, adapters) -> None:
    """Register every adapter this package holds that `adapters` lacks."""
    if __package__ == "core.adapters":
        from core.adapters.offline_preflight import OfflinePreflightKit
        from core.adapters.prodtools import ProdtoolsKit
    else:
        from adapters.offline_preflight import OfflinePreflightKit
        from adapters.prodtools import ProdtoolsKit
    for name, factory in (("prodtools", ProdtoolsKit),
                          ("offline_preflight", OfflinePreflightKit)):
        if name not in adapters:
            register(name, factory)
```

In `core/kit_registry.py`, the `offline_preflight` declaration: `step_kit=False, check_kit=True, engine=False, pipeline=True),` → `step_kit=False, check_kit=True, engine=True, pipeline=True),`.

In `core/contract.py`, `check_kits`: replace
```python
        try:
            need = set(REQUIRED_TOOLS)
            if study.preflight is not None and study.preflight["kit"] == name:
```
with
```python
        try:
            # A kit that runs a step needs the step calls; a kit used only
            # for the preflight needs only `check`.
            need = (set(REQUIRED_TOOLS)
                    if any(s.kit == name for s in study.steps) else set())
            if study.preflight is not None and study.preflight["kit"] == name:
```
and in its docstring, `offer the contract's tools (and \`check\` when it runs the preflight)` → `offer the contract's step tools when it runs a step (and \`check\` when it runs the preflight)`.

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_offline_preflight_kit tests.test_contract tests.test_kit_config tests.test_prodtools_adapter -v`
Expected: PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass. (`tests/test_study_engine.py::test_engine_studies_stay_out_of_specs` still reads `['branin', 'prodtools_smoke']`: the foilspf studies keep two pipeline-only kits.)

- [ ] **Step 7: Commit**

```bash
git add core/adapters/offline_preflight.py core/adapters/__init__.py \
  core/adapters/prodtools.py core/kit_registry.py core/contract.py \
  tests/test_offline_preflight_kit.py tests/test_contract.py tests/test_kit_config.py
git commit -F - <<'EOF'
feat(adapters): offline_preflight kit, the geometry pre-check on the engine

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 5: The run label as a study setting

**Files:**
- Modify: `core/kit_registry.py` (`_dsconf`; `prodtools` study key)
- Modify: `core/adapters/prodtools_entry.py` (`_TEMPLATE_KEYS`, `entry_for_step`), `core/adapters/prodtools.py` (`PARAMS`, `submit`, `_prepare`)
- Modify: `core/study_compat.py` (pipeline studies must say `Run1Bak_{cfg}`)
- Modify: `stage_entries/{mubeam,mustops_ce,elebeam_flash}.json` (drop `dsconf_fmt`)
- Modify: the seven `mode_specs/*.json`, `tests/fixtures/studies/demo.json`, `tests/fixtures/modes/template.json`, `tests/fixtures/engine_studies/prodtools_smoke.json`
- Test: `tests/test_study.py`, `tests/test_prodtools_entry.py`, `tests/test_prodtools_adapter.py`, `tests/test_study_compat.py`, `tests/test_stages_retired.py`, `tests/test_study_engine.py`

**Interfaces:**
- Produces: `KITS["prodtools"].study_keys` gains `dsconf` (required; a string containing `{cfg}`, which with `{cfg}` filled holds only letters, digits and `_`); `pe.entry_for_step(template, *, config, fixed, code_tarball, dsconf, geom_name=None, staged=None) -> (entry, facts)` — `dsconf` is the raw study setting, `facts["dsconf"]` the filled label; `prodtools.PARAMS` gains `"dsconf"` (required by `submit`). Study settings reach the adapter through `scheduler.step_params`, which already merges `study.kits["prodtools"]` into every prodtools step's params.

The pipeline is untouched: it names runs with its own `DSCONF = f"Run1Bak_{cfg}"` (`core/pipeline.py:_bind_config`) and never read `dsconf_fmt`; `study_compat` now refuses a pipeline study whose setting says otherwise, so the setting can never be silently ignored.

- [ ] **Step 1: Write the failing tests**

In `tests/test_study.py`, add to `TestProdtoolsKeys`:
```python
    def test_dsconf_holds_cfg_and_only_name_characters(self):
        for bad, needle in (("Run1Bak", "{cfg}"), (7, "{cfg}"),
                            ("Run1Bak-{cfg}", "'-'"),
                            ("Run1Bak_{cfg}_{geom}", "'{'")):
            doc = _doc()
            doc["kits"]["prodtools"]["dsconf"] = bad
            with self.subTest(bad=bad):
                self.assertRejects(doc, "[kits.prodtools][dsconf]", needle)

    def test_the_fixture_names_the_pipelines_run_label(self):
        self.assertEqual(st.load_study_file(FIXTURE).kits["prodtools"]["dsconf"],
                         "Run1Bak_{cfg}")
```

In `tests/test_prodtools_entry.py`:
- `TestParity.test_entries_match_gridphaseA01`: add `dsconf="Run1Bak_{cfg}",` to the `pe.entry_for_step(...)` call (after `code_tarball="CODE",`).
- In `TestEntryForStep`, add `dsconf="Run1Bak_{cfg}"` to the calls in `test_geom_without_a_geom_file_is_refused` and `test_template_defaults_fill_what_fixed_omits`, and replace `test_a_template_without_dsconf_fmt_is_refused` with:
```python
    def test_a_template_still_naming_dsconf_fmt_is_refused(self):
        t = dict(template("mubeam"), dsconf_fmt="Run1Bak_{cfg}")
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(t, config="c1", fixed={}, code_tarball="CODE",
                              dsconf="Run1Bak_{cfg}", geom_name="g.txt")
        self.assertIn("dsconf_fmt", str(cm.exception))
        self.assertIn("kits.prodtools.dsconf", str(cm.exception))

    def test_the_run_label_is_the_dsconf_setting_with_cfg_filled(self):
        entry, facts = pe.entry_for_step(
            template("mubeam"), config="c1", fixed={}, code_tarball="CODE",
            dsconf="MDC2025ax_{cfg}", geom_name="g.txt")
        self.assertEqual((entry["dsconf"], facts["dsconf"]),
                         ("MDC2025ax_c1", "MDC2025ax_c1"))

    def test_a_dsconf_without_cfg_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(template("mubeam"), config="c1", fixed={},
                              code_tarball="CODE", dsconf="Run1Bak",
                              geom_name="g.txt")
        self.assertIn("{cfg}", str(cm.exception))
```

In `tests/test_prodtools_adapter.py`:
- `_Kit.params`: add `"dsconf": "Run1Bak_{cfg}",` to the dict (after `"code_tarball": str(self.base),`).
- `TestWithRunSteps`: add `"dsconf": "Run1Bak_{cfg}",` to `settings`.
- add to `TestSubmit`:
```python
    def test_the_run_label_comes_from_the_dsconf_param(self):
        self.submit(self.kit(), dsconf="MDC2025ax_{cfg}")
        name = f"cnf.{USER}.Run1A_MuBeam_cfg1.MDC2025ax_cfg1.0"
        self.assertEqual(self.fake.entries[name]["dsconf"], "MDC2025ax_cfg1")
        self.assertEqual(self.record()["run_name"], name)

    def test_a_missing_dsconf_is_refused(self):
        params = self.params()
        del params["dsconf"]
        with self.assertRaises(ValueError) as cm:
            self.kit().submit("cfg1.mubeam", params, self.files(), [], "w")
        self.assertIn("'dsconf'", str(cm.exception))
        self.assertEqual(self.fake.write.calls, [])
```

In `tests/test_study_compat.py`, add to `TestRefusals`:
```python
    def test_a_run_label_the_pipeline_would_ignore_is_refused(self):
        def m(d):
            d["kits"]["prodtools"]["dsconf"] = "Other_{cfg}"
        msg = self._load(m)
        self.assertIn("dsconf", msg)
        self.assertIn("Run1Bak_{cfg}", msg)
```

In `tests/test_stages_retired.py`, `test_every_stage_entry_carries_stage_level_fields`: add `self.assertNotIn("dsconf_fmt", d, s)` after the `njobs` assertion.

In `tests/test_study_engine.py`, `TestProdtoolsSmoke.test_it_is_foilspfbpz_at_one_fixed_point`: add `self.assertEqual(smoke.kits["prodtools"]["dsconf"], "MDC2025ax_{cfg}")`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study tests.test_prodtools_entry tests.test_prodtools_adapter tests.test_study_compat tests.test_stages_retired tests.test_study_engine -v`
Expected: FAIL — `dsconf` is an unknown kit key; `entry_for_step` has no `dsconf` argument; the templates still carry `dsconf_fmt`.

- [ ] **Step 3: The registry**

In `core/kit_registry.py`, add `import re` after `import math`, add after `_string_list`:
```python
_RUN_LABEL = re.compile(r"[A-Za-z0-9_]+")


def _dsconf(v, where):
    """A prodtools run label (json2jobdef's dsconf): one per config, so it
    holds {cfg}; with {cfg} filled it goes into prodtools' dot-separated
    run and file names, so only letters, digits and _."""
    if not isinstance(v, str) or "{cfg}" not in v:
        raise ValueError(f"{where}: must be a string containing {{cfg}} "
                         f"(each config needs its own run label), got {v!r}")
    filled = v.replace("{cfg}", "cfg")
    if not _RUN_LABEL.fullmatch(filled):
        bad = sorted(set(_RUN_LABEL.sub("", filled)))
        raise ValueError(f"{where}: {v!r} has character(s) "
                         f"{', '.join(repr(c) for c in bad)}; with {{cfg}} "
                         f"filled in only letters, digits and _ may appear, "
                         f"because the label is part of prodtools' "
                         f"dot-separated run and file names")
    return v
```
and change the `prodtools` declaration's `study_keys` to:
```python
            study_keys={"code_tarball": _path, "dsconf": _dsconf,
                        "fatal_log_codes": _string_list},
```

- [ ] **Step 4: The entry helper and the adapter**

In `core/adapters/prodtools_entry.py`, change `_TEMPLATE_KEYS = ("desc_fmt", "dsconf_fmt", "fcl", "output_glob")` to `_TEMPLATE_KEYS = ("desc_fmt", "fcl", "output_glob")` and replace `entry_for_step` with:
```python
def entry_for_step(template, *, config, fixed, code_tarball, dsconf,
                   geom_name=None, staged=None):
    """(entry, facts) for one prodtools step.

    `template` is the step's stage template as the study resolved it;
    {cfg} becomes `config`, and {geom} `geom_name` (a template that names
    {geom} for a step with no geometry file is refused). `dsconf` is the
    study's run label (kits.prodtools.dsconf), {cfg} filled the same way.
    `fixed` holds the study's njobs / events_per_job / memory_mb when it
    sets them; the template's njobs / events / memory are the defaults.
    `staged` is (directory, {basename: 1}) when the step reads upstream
    outputs. `facts` are what the adapter records: desc, dsconf, njobs,
    events_per_job and output_glob.
    """
    if "dsconf_fmt" in template:
        raise ValueError("stage template: 'dsconf_fmt' is retired since "
                         "Phase C2a; the run label is the study setting "
                         "kits.prodtools.dsconf. Drop it from the template")
    if "{cfg}" not in dsconf:
        raise ValueError(f"dsconf {dsconf!r} has no {{cfg}}: every config "
                         f"needs its own run label")
    mapping = {"cfg": config}
    if geom_name is not None:
        mapping["geom"] = geom_name
    t = substitute_placeholders(template, mapping, "entry")
    missing = [k for k in _TEMPLATE_KEYS if k not in t]
    if missing:
        raise ValueError(f"stage template: missing key(s) {missing}")
    label = substitute_placeholders(dsconf, {"cfg": config}, "dsconf")
    njobs = fixed.get("njobs", t.get("njobs"))
    if njobs is None:
        raise ValueError("stage template: no njobs in the step's fixed or "
                         "the template")
    events = fixed.get("events_per_job", t.get("events"))
    entry = render_entry(
        dsconf=label, desc=t["desc_fmt"], njobs=njobs,
        code_tarball=code_tarball, fcl_name=t["fcl"], events=events,
        run=t.get("run"), memory_mb=fixed.get("memory_mb", t.get("memory")),
        input_data=staged[1] if staged else t.get("input_data"),
        inloc=f"dir:{staged[0]}" if staged else t.get("inloc"),
        resampler_name=t.get("resampler_name"),
        fcl_overrides=t.get("fcl_overrides"), outloc=t.get("outloc"),
        sequential_aux=t.get("sequential_aux"))
    facts = {"desc": t["desc_fmt"], "dsconf": label,
             "njobs": njobs, "events_per_job": events,
             "output_glob": t["output_glob"]}
    return entry, facts
```

In `core/adapters/prodtools.py`:
- `PARAMS = ("entry", "code_tarball", "fatal_log_codes", "njobs",` / `"events_per_job", "memory_mb", "quorum")` → `PARAMS = ("entry", "code_tarball", "dsconf", "fatal_log_codes", "njobs",` / `"events_per_job", "memory_mb", "quorum")`.
- in `submit`, `for key in ("entry", "code_tarball", "fatal_log_codes", "quorum"):` → `for key in ("entry", "code_tarball", "dsconf", "fatal_log_codes",` / `"quorum"):`.
- in `_prepare`, the `pe.entry_for_step(...)` call gains `dsconf=params["dsconf"],` after `code_tarball=str(tarball),`.

- [ ] **Step 5: The pipeline's view refuses another label**

In `core/study_compat.py`, add after `_PLUGINS = (...)`:
```python
# core/pipeline.py names every run with its own DSCONF, never the setting.
_PIPELINE_DSCONF = "Run1Bak_{cfg}"
```
and after the `for s in grid:` loop (before `pre = study.kits["offline_preflight"]`):
```python
    label = study.kits["prodtools"]["dsconf"]
    _need(label == _PIPELINE_DSCONF, study,
          f"its kits.prodtools.dsconf is {label!r}; the pipeline names every "
          f"run {_PIPELINE_DSCONF!r} (core/pipeline.py DSCONF) and would "
          f"ignore any other")
```

- [ ] **Step 6: The templates and the study files**

Run once from the repo root:

```python
import json, pathlib
for step in ("mubeam", "mustops_ce", "elebeam_flash"):
    p = pathlib.Path(f"stage_entries/{step}.json")
    s = p.read_text()
    line = ' "dsconf_fmt": "Run1Bak_{cfg}",\n'
    assert s.count(line) == 1, p
    p.write_text(s.replace(line, ""))
    assert "dsconf_fmt" not in json.loads(p.read_text()), p
RUN1BAK = ["mode_specs/foilsflash.json", "mode_specs/foilspf.json",
           "mode_specs/foilspf2k.json", "mode_specs/foilspfbp.json",
           "mode_specs/foilspfbpx.json", "mode_specs/foilspfbpz.json",
           "mode_specs/foilspfbw.json", "tests/fixtures/studies/demo.json",
           "tests/fixtures/modes/template.json"]
OLD = ', "fatal_log_codes": ["GeomSolids1001"]}'
NEW = ', "dsconf": "Run1Bak_{cfg}", "fatal_log_codes": ["GeomSolids1001"]}'
for f in RUN1BAK:
    p = pathlib.Path(f)
    s = p.read_text()
    assert s.count(OLD) == 1, f
    p.write_text(s.replace(OLD, NEW))
    assert json.loads(p.read_text())["kits"]["prodtools"]["dsconf"] == "Run1Bak_{cfg}", f
smoke = pathlib.Path("tests/fixtures/engine_studies/prodtools_smoke.json")
doc = json.loads(smoke.read_text())
pt = doc["kits"]["prodtools"]
doc["kits"]["prodtools"] = {"code_tarball": pt["code_tarball"],
                            "dsconf": "MDC2025ax_{cfg}",
                            "fatal_log_codes": pt["fatal_log_codes"]}
smoke.write_text(json.dumps(doc, indent=1) + "\n")
```

`git diff --stat` must show the 3 templates (1 line each), the 9 hand-formatted study files (1 line each) and `prodtools_smoke.json` (1 line added). `tests/fixtures/prodtools_parity/` is untouched.

- [ ] **Step 7: Run the tests and the golden**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass (`TestParity` included: gridphaseA01 ran under `Run1Bak_gridphaseA01`).
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: every section passes (`ModeSpec` has no dsconf field).

- [ ] **Step 8: Commit**

```bash
git add core/kit_registry.py core/adapters/prodtools_entry.py core/adapters/prodtools.py \
  core/study_compat.py stage_entries/mubeam.json stage_entries/mustops_ce.json \
  stage_entries/elebeam_flash.json mode_specs/foilsflash.json mode_specs/foilspf.json \
  mode_specs/foilspf2k.json mode_specs/foilspfbp.json mode_specs/foilspfbpx.json \
  mode_specs/foilspfbpz.json mode_specs/foilspfbw.json tests/fixtures/studies/demo.json \
  tests/fixtures/modes/template.json tests/fixtures/engine_studies/prodtools_smoke.json \
  tests/test_study.py tests/test_prodtools_entry.py tests/test_prodtools_adapter.py \
  tests/test_study_compat.py tests/test_stages_retired.py tests/test_study_engine.py
git commit -F - <<'EOF'
feat(prodtools): the run label is the study setting kits.prodtools.dsconf

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 6: Retry budgets per contract call (fix 5)

**Files:**
- Modify: `core/contract.py` (`ATTEMPTS` / `RETRY_PAUSES_S` → a per-call table; `call_with_retries`; `NativeKit._call`, `cancel`)
- Modify: `core/adapters/prodtools.py` (`_run_status(..., call=...)`, its three callers; `cancel`)
- Test: `tests/test_contract.py`, `tests/test_prodtools_adapter.py`

**Interfaces:**
- Produces: `contract.RETRY_PAUSES_S: dict[str, tuple[float, ...]]` keyed by contract call (`submit`, `check`, `describe`: `(5.0, 20.0)`; `status`, `results`, `cancel`: `(5.0, 20.0, 60.0, 180.0)`); `contract.call_with_retries(fn, *, call, retry_tool_errors, pause=time.sleep)` — `len(RETRY_PAUSES_S[call]) + 1` attempts. `ATTEMPTS` is removed. `ProdtoolsKit._run_status(run_name, workflow, *, call)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_contract.py`, class `TestRetryPolicy`: replace `test_status_gives_up_after_three_attempts`, `test_cancel_is_never_retried` and `test_pauses_grow_between_attempts` with:
```python
    def test_status_gives_up_after_five_attempts(self):
        kit, c = self.kit([KitError("k", "status", "lost")] * 5)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(len(c.calls), 5)

    def test_status_pauses_about_four_and_a_half_minutes_in_all(self):
        pauses = []
        client = FakeClient([KitError("k", "status", "lost")] * 5)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(pauses, [5.0, 20.0, 60.0, 180.0])

    def test_results_and_cancel_share_the_long_budget(self):
        for call in ("results", "cancel"):
            self.assertEqual(ct.RETRY_PAUSES_S[call], (5.0, 20.0, 60.0, 180.0))

    def test_submit_keeps_three_attempts_and_short_pauses(self):
        pauses = []
        client = FakeClient([KitTimeout("k", "submit", "timed out")] * 3)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitTimeout):
            kit.submit("c.s", {}, [], [], "w")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(pauses, [5.0, 20.0])

    def test_cancel_retries_a_lost_server_but_never_a_refusal(self):
        kit, c = self.kit([KitError("k", "cancel", "lost"),
                           {"state": "cancelled"}])
        self.assertEqual(kit.cancel("h", "w"), "cancelled")
        self.assertEqual(len(c.calls), 2)
        kit, c = self.kit([KitToolError("k", "cancel", "no such handle")])
        with self.assertRaises(KitToolError):
            kit.cancel("h", "w")
        self.assertEqual(len(c.calls), 1)
```

In `tests/test_prodtools_adapter.py`:
- `TestStatus.test_an_error_reply_other_than_not_found_is_raised_after_retries`: change `self.assertEqual(len(self.fake.read.calls), 3)` to `self.assertEqual(len(self.fake.read.calls), 5)`.
- `TestRealServers.test_run_status_of_a_run_that_cannot_exist_is_none`: the call becomes `self.kit("grid")._run_status(self.no_such_run(), self.WF, call="status")`.
- add to `TestSubmit`:
```python
    def test_adopting_after_a_failed_launch_keeps_the_submit_budget(self):
        self.fake.raise_after_submit = KitTimeout("prodtools", "submit_once",
                                                  "timed out")
        self.fake.read.handler = lambda tool, args: {
            "error": {"kind": "auth_expired", "message": "token expired",
                      "remedy": "renew"}}
        with self.assertRaises(KitToolError):
            self.submit(self.kit())
        self.assertEqual(len(self.fake.read.calls), 3)
```
- add to `TestCancelAndLaunch`:
```python
    def test_cancel_retries_a_lost_write_server(self):
        kit = self.kit(cancel=True)
        self.submit(kit)
        write, lost = self.fake.write.handler, []

        def flaky(tool, args):
            if tool == "cancel_run" and not lost:
                lost.append(1)
                raise KitError("prodtools-write", tool, "server lost")
            return write(tool, args)

        self.fake.write.handler = flaky
        self.assertEqual(kit.cancel("cfg1.mubeam", "w"), "cancelled")
        self.assertEqual([c[0] for c in self.fake.write.calls],
                         ["submit_once", "cancel_run", "cancel_run"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract.TestRetryPolicy tests.test_prodtools_adapter -v`
Expected: FAIL — 3 attempts where 5 are expected; `RETRY_PAUSES_S` is a tuple; `_run_status` takes no `call`; `cancel` is not retried.

- [ ] **Step 3: The contract**

In `core/contract.py`, replace
```python
ATTEMPTS = 3            # bounded retries of the calls safe to repeat
RETRY_PAUSES_S = (5.0, 20.0)   # after the 1st and the 2nd failed attempt
```
with
```python
# Pauses between attempts, per contract call; a call makes one attempt
# more than it has pauses. submit, check and describe: a credential blip
# lasts seconds. status, results and cancel: read-only or idempotent, on a
# point that may have waited hours, so they ride out a server outage of
# minutes (5 attempts, about 4.5 min).
_BRIEF = (5.0, 20.0)
_PATIENT = (5.0, 20.0, 60.0, 180.0)
RETRY_PAUSES_S = {"submit": _BRIEF, "check": _BRIEF, "describe": _BRIEF,
                  "status": _PATIENT, "results": _PATIENT,
                  "cancel": _PATIENT}
```
and replace `call_with_retries` with:
```python
def call_with_retries(fn, *, call, retry_tool_errors, pause=time.sleep):
    """fn() up to len(RETRY_PAUSES_S[call]) + 1 times, `call` being the
    contract call it serves. Transport failures and timeouts are retried;
    a tool error only when retry_tool_errors (a refused submit -- same
    name, different params -- must never be repeated). Between attempts
    it pauses RETRY_PAUSES_S[call]."""
    pauses = RETRY_PAUSES_S[call]
    for attempt in range(len(pauses) + 1):
        try:
            return fn()
        except KitToolError:
            if not retry_tool_errors or attempt == len(pauses):
                raise
        except KitError:
            if attempt == len(pauses):
                raise
        pause(pauses[attempt])
```
In `NativeKit`, replace `_call` with:
```python
    def _call(self, tool, args, workflow, *, retry_tool_errors):
        """Transport failures and timeouts are retried (the client respawns
        a lost server before the next call), with the pauses of the call's
        RETRY_PAUSES_S; see call_with_retries."""
        return call_with_retries(
            lambda: self.client.call(tool, args,
                                     timeout_s=self.config.timeouts[tool],
                                     workflow=workflow),
            call=tool, retry_tool_errors=retry_tool_errors,
            pause=self._pause)
```
and in `NativeKit.cancel`, `retry_tool_errors=False, attempts=1),` → `retry_tool_errors=False),`.

- [ ] **Step 4: The prodtools adapter**

In `core/adapters/prodtools.py`:
- `_run_status`: signature `def _run_status(self, run_name, workflow, *, call):`; add to its docstring the sentence `` `call` names the contract call it serves, which sets its retry budget (contract.RETRY_PAUSES_S). ``; and `reply = call_with_retries(once, retry_tool_errors=True,` / `pause=self._pause)` → `reply = call_with_retries(once, call=call, retry_tool_errors=True,` / `pause=self._pause)`.
- in `status`: `reply = self._run_status(rec["run_name"], workflow)` → `reply = self._run_status(rec["run_name"], workflow, call="status")`.
- in `_adopt`: `reply = self._run_status(rec["run_name"], workflow)` → `reply = self._run_status(rec["run_name"], workflow, call="submit")`.
- in `cancel`, replace
```python
        reply = self._call(self._write, "cancel_run",
                           self._cancel_args(rec["run_name"]), workflow)
```
with
```python
        reply = call_with_retries(
            lambda: self._call(self._write, "cancel_run",
                               self._cancel_args(rec["run_name"]), workflow),
            call="cancel", retry_tool_errors=False, pause=self._pause)
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/contract.py core/adapters/prodtools.py tests/test_contract.py \
  tests/test_prodtools_adapter.py
git commit -F - <<'EOF'
fix(contract): status, results and cancel ride out a 4.5 min outage; submit keeps 3 attempts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 7: prodtools receipts and replies (fixes 1, 2, 7)

**Files:**
- Modify: `core/adapters/prodtools.py` (`STUCK`, `STARTING_LIMIT_S`; `submit`, `_adopt`, new `_stuck`; `status`; `_complete`)
- Test: `tests/test_prodtools_adapter.py`

**Interfaces:**
- Consumes: `_run_status(run_name, workflow, *, call)` (Task 6).
- Produces: `prodtools.STUCK = ("submitting", "building", "starting")`; `prodtools.STARTING_LIMIT_S = 10 * 60`; `ProdtoolsKit._adopt(rec, workflow, launch_error=None) -> bool`; `ProdtoolsKit._stuck(rec, reply, launch_error) -> str`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_prodtools_adapter.py`, add to `TestSubmit`:
```python
    def stick(self, state, error, *, drop_host=False):
        """The next launch creates its run, leaves its receipt in `state`
        and raises `error`, as a prodtools that died mid-submit would."""
        write = self.fake.write.handler

        def handler(tool, args):
            reply = write(tool, args)
            run = self.fake.runs[reply["name"]]
            run["state"] = state
            if drop_host:
                del run["host"], run["pid"]
            raise error

        self.fake.write.handler = handler

    def test_a_stuck_grid_receipt_names_prodtools_error_and_jobsub_q(self):
        self.stick("submitting", KitToolError(
            "prodtools-write", "submit_once",
            "jobsub_submit: rc=1: NoPublisherHandlerServerError"))
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        msg = str(cm.exception)
        for needle in ("'submitting'", "NoPublisherHandlerServerError",
                       "jobsub_q", "new config name"):
            self.assertIn(needle, msg)

    def test_a_stuck_local_receipt_names_its_host_and_pid(self):
        self.stick("building", KitTimeout("prodtools-write", "run_local",
                                          "timed out after 300 s"))
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit(executor="local"))
        msg = str(cm.exception)
        for needle in ("'building'", "timed out after 300 s", "node.example",
                       "4242"):
            self.assertIn(needle, msg)
        self.assertNotIn("jobsub_q", msg)

    def test_a_local_receipt_in_starting_without_a_host_names_its_run_dir(self):
        self.stick("starting", KitTimeout("prodtools-write", "run_local",
                                          "timed out after 300 s"),
                   drop_host=True)
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit(executor="local"))
        msg = str(cm.exception)
        self.assertIn("'starting'", msg)
        self.assertIn(str(self.tmp / "prodtools" / "runs" / self.run_name()),
                      msg)
        self.assertEqual(self.record()["state"], "submitting")
```

Add to `TestStatus`:
```python
    def test_starting_is_working_until_ten_minutes_then_failed(self):
        kit, name = self.submitted(executor="local")
        self.fake.runs[name]["state"] = "starting"
        s = self.state(kit)
        self.assertEqual((s.state, s.message), ("working", "starting"))
        self.clock[0] += 10 * 60
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("10 min", s.message)

    def test_a_run_that_leaves_starting_resets_the_clock(self):
        kit, name = self.submitted(executor="local")
        self.fake.runs[name]["state"] = "starting"
        self.state(kit)
        self.assertIn("starting_since", self.record())
        self.fake.runs[name]["state"] = "running"
        self.assertEqual(self.state(kit).state, "working")
        self.assertNotIn("starting_since", self.record())

    def test_done_without_a_jobs_block_raises_naming_the_run(self):
        kit, name = self.submitted()
        self.fake.runs[name]["state"] = "done"
        with self.assertRaises(KitError) as cm:
            self.state(kit)
        self.assertIn(name, str(cm.exception))
        self.assertIn("no jobs block", str(cm.exception))
        self.assertNotIn("verdict", self.record())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_adapter -v`
Expected: FAIL — the stuck message carries no prodtools text or host; `starting` is adopted and never times out; a jobs-less `done` reads "0/2 jobs ok".

- [ ] **Step 3: Implement**

In `core/adapters/prodtools.py`, add after `STAGEOUT_LIMIT_S = 30 * 60`:
```python
STARTING_LIMIT_S = 10 * 60
# Receipt states before a run is known to be running: a receipt left in
# one of them means prodtools died mid-submit or mid-launch.
STUCK = ("submitting", "building", "starting")
```

In `submit`, replace
```python
        try:
            self._launch(rec, workflow)
        except KitError:
            if not self._adopt(rec, workflow):
                raise
```
with
```python
        try:
            self._launch(rec, workflow)
        except KitError as exc:
            if not self._adopt(rec, workflow, launch_error=exc.message):
                raise
```

Replace `_adopt` with:
```python
    def _adopt(self, rec, workflow, launch_error=None) -> bool:
        """True when prodtools already has this step's run, past
        submission; False when it has none. A run created before the
        record's submitting_utc is not this step's (the config name was
        used before) and is an error, as is a receipt stuck in a STUCK
        state: whether jobs reached the grid, or a local run started,
        cannot be told. `launch_error` is what the launch call raised,
        when this adopt follows one."""
        reply = self._run_status(rec["run_name"], workflow, call="submit")
        if reply is None:
            return False
        created, ours = reply.get("created_utc"), rec.get("submitting_utc")
        if (_utc_of(created, "run_status's created_utc", rec["run_name"])
                < _utc_of(ours, "the record's submitting_utc",
                          rec["run_name"])):
            config, _step = split_handle(rec["name"])
            raise KitError(
                self.name, "submit",
                f"{rec['run_name']} was created at {created}, before this "
                f"step started submitting at {ours}, so it is not this "
                f"step's run: the config name {config!r} was used before. "
                f"Pick a new config name")
        if reply.get("state") in STUCK:
            raise KitError(self.name, "submit",
                           self._stuck(rec, reply, launch_error))
        return True

    def _stuck(self, rec, reply, launch_error) -> str:
        """The refusal for a receipt stuck in a STUCK state: prodtools' own
        error text when there is one, and where to look for the run."""
        msg = f"{rec['run_name']}: its receipt is stuck in {reply['state']!r}"
        errors = [e for e in (launch_error, reply.get("error")) if e]
        if errors:
            msg += " (prodtools said: " + "; ".join(errors) + ")"
        if self.executor == "grid":
            msg += (", so whether its jobs reached the grid cannot be told. "
                    "Look for its cluster in jobsub_q")
        elif reply.get("host") and reply.get("pid"):
            msg += (f", so whether its local run started cannot be told. "
                    f"Look on {reply['host']} for pid {reply['pid']}")
        else:
            run_dir = Path(reply.get("receipt", "")).parent
            msg += (f", and it names no host or pid yet, so whether its "
                    f"local run started cannot be told. Look for a runlocal "
                    f"or json2jobdef process whose command line names "
                    f"{run_dir}")
        return msg + "; this point needs a new config name"
```

In `status`, replace
```python
        if rec.pop("unknown_since", None) is not None:
            self._save(sdir, rec)
        if state in WORKING:
```
with
```python
        if rec.pop("unknown_since", None) is not None:
            self._save(sdir, rec)
        if state == "starting":
            since = rec.setdefault("starting_since", self._clock())
            self._save(sdir, rec)
            if self._clock() - since >= STARTING_LIMIT_S:
                return self._decide(
                    sdir, rec, "failed",
                    f"run_status has said starting for "
                    f"{STARTING_LIMIT_S // 60} min: prodtools never "
                    f"launched runlocal for {rec['run_name']} (receipt "
                    f"{reply.get('receipt')})")
            return self._working("starting", progress)
        if rec.pop("starting_since", None) is not None:
            self._save(sdir, rec)
        if state in WORKING:
```

In `_complete`, replace the first line `jobs = reply.get("jobs") or {}` with:
```python
        jobs = reply.get("jobs")
        if not isinstance(jobs, dict):
            raise KitError(self.name, "status",
                           f"{rec['run_name']}: run_status says "
                           f"{reply.get('state')!r} but its reply has no "
                           f"jobs block, so how many jobs succeeded cannot "
                           f"be told")
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_adapter -v`
Expected: PASS (`test_a_receipt_stuck_in_submitting_fails_loudly` still finds `jobsub_q`).
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/adapters/prodtools.py tests/test_prodtools_adapter.py
git commit -F - <<'EOF'
fix(prodtools): stuck receipts name prodtools' error and where to look; starting times out; a done reply needs its jobs block

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 8: The engine's small fixes: the start trace (3), `entry` reserved at load (6), the name prefix (4)

**Files:**
- Modify: `core/kits.py` (`KitClient.start` → `start` + `_start`)
- Modify: `core/study.py` (`_steps`, `_kits_and_preflight`)
- Modify: `core/contract.py` (`config_name_problems`), `core/adapters/prodtools.py` and `core/adapters/offline_preflight.py` (`config_problem` class attribute), `graph/study_loop.py`
- Test: `tests/test_kits.py`, `tests/test_study.py`, `tests/test_contract.py`, `tests/test_study_loop.py`

**Interfaces:**
- Consumes: `prodtools.config_problem(config)` (Task 4).
- Produces: a `kit_trace.jsonl` row `{"tool": "start", "workflow": "<campaign>/start", ...}` per start attempt; `contract.config_name_problems(study, config: str) -> list[str]` — each problem `"kit '<name>': <why>"`; an adapter class may carry `config_problem` (a staticmethod `str -> str | None`), as `ProdtoolsKit` and `OfflinePreflightKit` now do.

- [ ] **Step 1: Write the failing tests**

In `tests/test_kits.py`, class `TestTrace`, replace `test_one_line_per_call` with:
```python
    def test_one_line_per_start_and_per_call(self):
        c = self.client()
        self.call(c, "describe")
        with self.assertRaises(KitToolError):
            self.call(c, "status", {"handle": "nope"})
        start, ok, bad = self.trace()
        self.assertEqual((start["tool"], start["ok"], start["error"],
                          start["workflow"]), ("start", True, None, "camp/start"))
        self.assertEqual(start["server"], {"name": "toykit", "version": "1"})
        self.assertGreaterEqual(start["duration_s"], 0)
        self.assertEqual((ok["tool"], ok["ok"], ok["error"]),
                         ("describe", True, None))
        self.assertEqual((bad["tool"], bad["ok"]), ("status", False))
        self.assertIn("no job", bad["error"])
        for line in (ok, bad):
            self.assertEqual(line["workflow"], WF)
            self.assertEqual(line["kit"], "toykit")
            self.assertEqual(len(line["args_sha256"]), 64)
            self.assertEqual(line["server"], {"name": "toykit", "version": "1"})
            self.assertGreaterEqual(line["duration_s"], 0)

    def test_a_failed_start_is_traced_with_its_error(self):
        c = self.client(set_env={})       # no TOYKIT_STATE_DIR
        with self.assertRaises(KitError):
            self.call(c, "describe")
        start, call = self.trace()
        self.assertEqual((start["tool"], start["ok"]), ("start", False))
        self.assertIn("TOYKIT_STATE_DIR is not set", start["error"])
        self.assertEqual((call["tool"], call["ok"]), ("describe", False))

    def test_starting_a_started_client_writes_nothing(self):
        c = self.client()
        c.start()
        c.start()
        self.assertEqual([r["tool"] for r in self.trace()], ["start"])
```

In `tests/test_study.py`, add:
```python
class TestReservedEntry(_Tmp):
    def test_entry_is_reserved_for_a_kit_that_takes_templates(self):
        cases = (
            ("param", lambda d: _step(d, "mubeam")["params"].update(entry="a"),
             "[evaluate[0]][params.entry]"),
            ("fixed", lambda d: _step(d, "mubeam")["fixed"].update(entry=1),
             "[evaluate[0]][fixed.entry]"),
            ("setting", lambda d: d["kits"]["prodtools"].update(entry="x"),
             "[kits.prodtools][entry]"))
        for label, mutate, field in cases:
            doc = _doc()
            mutate(doc)
            with self.subTest(label):
                self.assertRejects(doc, field, "reserved")
```

In `tests/test_contract.py`, add `import types` to the imports and add:
```python
class TestConfigNames(unittest.TestCase):
    @staticmethod
    def study(*kits, preflight=None):
        return types.SimpleNamespace(
            steps=tuple(types.SimpleNamespace(kit=k) for k in kits),
            preflight=preflight)

    def test_the_prodtools_rule_covers_its_steps_and_the_pre_check(self):
        s = self.study("prodtools", preflight={"kit": "offline_preflight"})
        problems = ct.config_name_problems(s, "smoke-1R00_00")
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("'-'" in p for p in problems))
        self.assertEqual(ct.config_name_problems(s, "smoke1R00_00"), [])

    def test_a_kit_without_a_rule_accepts_any_name(self):
        self.assertEqual(ct.config_name_problems(self.study("toykit"),
                                                 "a-b.c"), [])
```

In `tests/test_study_loop.py`, add `import contextlib`, `import io` and `import study as st  # noqa: E402` (next to `import study_loop`) to the imports, and add:
```python
class TestNamePrefix(unittest.TestCase):
    def test_a_prefix_a_kit_cannot_name_launches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            study = st.load_study_file(
                write_study(toy_doc(name="pfxtoy", layout="v2"), Path(td)))
        seen = []

        def rule(study_, config):
            seen.append(config)
            return [f"kit 'x': config name {config!r} has character(s) '-'"]

        out = io.StringIO()
        with mock.patch.dict(study_loop._modes.STUDIES, {"pfxtoy": study}), \
                mock.patch.object(study_loop._modes, "ENGINE",
                                  frozenset({"pfxtoy"})), \
                mock.patch.object(study_loop, "config_name_problems",
                                  side_effect=rule), \
                mock.patch.object(study_loop, "check_kits", return_value=[]), \
                mock.patch.object(study_loop, "run_rolling") as rolling, \
                contextlib.redirect_stdout(out):
            rc = study_loop.main(["--study", "pfxtoy", "--q", "1",
                                  "--max-evals", "1", "--name-prefix",
                                  "smoke-1"])
        self.assertEqual(rc, 2)
        self.assertEqual(seen, ["smoke-1R00_00"])
        rolling.assert_not_called()
        self.assertIn("REFUSED", out.getvalue())
        self.assertIn("smoke-1R00_00", out.getvalue())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kits.TestTrace tests.test_study.TestReservedEntry tests.test_contract.TestConfigNames tests.test_study_loop.TestNamePrefix -v`
Expected: FAIL — no start row; `entry` refused only as an unknown key (or not at all for params); `config_name_problems` missing.

- [ ] **Step 3: The start trace**

In `core/kits.py`, replace the `start` method's first lines
```python
    def start(self) -> None:
        name = self.config.name
        with self._lock:
            if self._session is not None:
                return
            if self._loop is not None:
```
and the rest of its body with the two methods below; `_start` holds the old body from `if self._loop is not None:` to the end, dedented one level (it no longer sits under `with self._lock:`) and otherwise unchanged:
```python
    def start(self) -> None:
        """Start the server, once. Each attempt writes a trace row (tool
        "start", its duration and any error), as each call does."""
        with self._lock:
            if self._session is not None:
                return
            t0 = time.monotonic()
            error = None
            try:
                self._start()
            except BaseException as exc:
                error = getattr(exc, "message", None) or repr(exc)
                raise
            finally:
                self._trace("start", {}, f"{self.campaign}/start",
                            time.monotonic() - t0, error)

    def _start(self) -> None:
        """start()'s body; the caller holds self._lock."""
        name = self.config.name
        if self._loop is not None:
            # The serve task ended on its own between calls (the
            # server died with nobody waiting on it): _session is
            # already cleared, but its loop and thread are not.
            # Tear them down before building a fresh one, or the old
            # `kit-<name>` thread spins forever.
            self._teardown()
        try:
            from mcp.client.stdio import get_default_environment
            command = self.config.resolve_command()
            env = self.config.resolve_env(get_default_environment())
        except KitConfigError as exc:
            raise KitError(name, "start", str(exc)) from None
        self._stderr_tail.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        name=f"kit-{name}", daemon=True)
        self._thread.start()
        ready = concurrent.futures.Future()
        self._serve_fut = asyncio.run_coroutine_threadsafe(
            self._serve(ready, command, env), self._loop)
        timeout = self.config.timeouts["start"]
        try:
            ready.result(timeout)
        except concurrent.futures.TimeoutError:
            self._teardown()
            raise KitError(name, "start", f"server did not start within "
                           f"{timeout:g} s ({command})") from None
        except Exception as exc:  # noqa: BLE001 - reported with stderr
            self._teardown()
            if self._pump is not None:
                self._pump.join(2)
            tail = " | ".join(self._stderr_tail)
            raise KitError(name, "start", f"server did not start "
                           f"({command}): {type(exc).__name__}: {exc}; "
                           f"child stderr: {tail}") from exc
```

- [ ] **Step 4: `entry` reserved at load**

In `core/study.py`, `_steps`, right after `decl = kit_registry.KITS[kit]`:
```python
        if decl.uses_entries:
            for part in ("params", "fixed"):
                if isinstance(s[part], dict) and "entry" in s[part]:
                    raise ValueError(
                        f"{sw}[{part}.entry]: 'entry' is reserved for kit "
                        f"{kit!r}, which receives the step's stage template "
                        f"under that name")
```
and in `_kits_and_preflight`, inside `for kit, settings in kits_raw.items():`, right after the `if kit not in used:` block:
```python
        if (kit_registry.KITS[kit].uses_entries and isinstance(settings, dict)
                and "entry" in settings):
            raise ValueError(f"{kw}[entry]: 'entry' is reserved for kit "
                             f"{kit!r}, which receives each step's stage "
                             f"template under that name")
```
`core/scheduler.py:step_params`' run-time check stays as the guard.

- [ ] **Step 5: The name-prefix check**

In `core/contract.py`, add after `requires_kerberos`:
```python
def config_name_problems(study, config: str) -> List[str]:
    """Why a kit of the study would refuse `config` as a config name: an
    adapter declares its rule as config_problem(config) -> str | None.
    Empty means every kit accepts the name."""
    _load_adapters()
    problems = []
    for name in sorted(kit_registry.kits_of(study)):
        rule = getattr(ADAPTERS.get(name), "config_problem", None)
        why = rule(config) if rule is not None else None
        if why:
            problems.append(f"kit {name!r}: {why}")
    return problems
```

In `core/adapters/prodtools.py`, class `ProdtoolsKit`, add after `LAUNCH_STAGGER_S = 90.0`:
```python
    config_problem = staticmethod(config_problem)
```
In `core/adapters/offline_preflight.py`, class `OfflinePreflightKit`, add after `LAUNCH_STAGGER_S = 0`:
```python
    config_problem = staticmethod(config_problem)
```

In `graph/study_loop.py`:
- `from contract import EXECUTORS, check_kits, launch_stagger  # noqa: E402` → `from contract import (EXECUTORS, check_kits, config_name_problems,  # noqa: E402` / `                      launch_stagger)`
- `from pool import next_free_name, run_rolling  # noqa: E402` → `from pool import child_name, next_free_name, run_rolling  # noqa: E402`
- replace
```python
    problems = launch_refusals(study, args.executor, args.parallel)
    problems += check_kits(study, campaign=args.name_prefix,
```
with
```python
    problems = launch_refusals(study, args.executor, args.parallel)
    # The first child's name, as next_free_name gives it when nothing is
    # busy: the prefix plus the suffix the pool adds. A later index changes
    # only digits, so one name covers them all.
    problems += config_name_problems(study, child_name(args.name_prefix, 0))
    problems += check_kits(study, campaign=args.name_prefix,
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kits tests.test_study tests.test_contract tests.test_study_loop tests.test_generic_core -v`
Expected: PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add core/kits.py core/study.py core/contract.py core/adapters/prodtools.py \
  core/adapters/offline_preflight.py graph/study_loop.py tests/test_kits.py \
  tests/test_study.py tests/test_contract.py tests/test_study_loop.py
git commit -F - <<'EOF'
fix(engine): trace kit starts, reserve entry at load, check the name prefix before launch

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

### Task 9: The smoke study's pre-check, and the docs

**Files:**
- Modify: `tests/fixtures/engine_studies/prodtools_smoke.json`
- Modify: `tests/test_study_engine.py`
- Modify: `CONTEXT.md`, `mode_specs/README.md`, `wiki/drivers/contract-engine.md`, `wiki/drivers/preflight.md`, `wiki/index.md`, `wiki/log.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `prodtools_smoke` with `preflight: {"kit": "offline_preflight", "params": {}, "files": ["geom"]}` and `kits.offline_preflight` = the MDC2025ax tarball plus foilspfbpz's four policy flags — the study the acceptance runs use.

- [ ] **Step 1: Write the failing test**

In `tests/test_study_engine.py`, add to `TestProdtoolsSmoke`:
```python
    def test_it_gates_on_the_pre_check_with_foilspfbpzs_policy(self):
        smoke = st.load_study_file(ENGINE_STUDIES / "prodtools_smoke.json")
        bpz = st.load_study_file(ROOT / "mode_specs" / "foilspfbpz.json")
        self.assertEqual(smoke.preflight, {"kit": "offline_preflight",
                                           "params": {}, "files": ["geom"]})
        pre = smoke.kits["offline_preflight"]
        self.assertEqual(pre["code_tarball"],
                         smoke.kits["prodtools"]["code_tarball"])
        self.assertTrue(pre["code_tarball"].endswith("Code_mdc2025ax.tar.bz2"))
        for flag in ("dumps_gdml", "verifies_foil_gdml",
                     "checks_managed_overlap", "require_zero_overlaps"):
            self.assertEqual(pre[flag], bpz.kits["offline_preflight"][flag],
                             flag)
        self.assertTrue(modes.runs_on_engine(smoke))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_engine.TestProdtoolsSmoke -v`
Expected: FAIL (`smoke.preflight` is `None`).

- [ ] **Step 3: Give the smoke study its pre-check**

Run once from the repo root:

```python
import json, pathlib
p = pathlib.Path("tests/fixtures/engine_studies/prodtools_smoke.json")
doc = json.loads(p.read_text())
bpz = json.loads(pathlib.Path("mode_specs/foilspfbpz.json").read_text())
flags = {k: v for k, v in bpz["kits"]["offline_preflight"].items()
         if k != "code_tarball"}
doc["kits"]["offline_preflight"] = {
    "code_tarball": doc["kits"]["prodtools"]["code_tarball"], **flags}
doc["preflight"] = {"kit": "offline_preflight", "params": {},
                    "files": ["geom"]}
doc["note"] += (" Phase C2a adds the geometry pre-check (offline_preflight) "
                "from the same code tarball, with foilspfbpz's GDML and "
                "overlap policy.")
p.write_text(json.dumps(doc, indent=1) + "\n")
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass (`test_engine_studies_stay_out_of_specs` still reads `['branin', 'prodtools_smoke'] False True`).

- [ ] **Step 5: The docs**

`CONTEXT.md`:
- **Engine study**: `and \`prodtools_smoke\` (the Phase C1 acceptance study, on \`prodtools\`).` → `and \`prodtools_smoke\` (the Phase C1 acceptance study, on \`prodtools\`, gated by the \`offline_preflight\` pre-check since Phase C2a).`
- **Pipeline study**: `` `prodtools` has an engine adapter since Phase C1, but their other three kits (`offline_preflight`, `ce_sensitivity`, `flash_edep_per_pot`) are pipeline-only. `` → `` `prodtools` (Phase C1) and `offline_preflight` (Phase C2a) have engine adapters, but their other two kits (`ce_sensitivity`, `flash_edep_per_pot`) are pipeline-only until Phase C2b. ``
- **Adapter** (2): `` `prodtools` (`core/adapters/prodtools.py`, Phase C1) is the first; `` → `` `prodtools` (`core/adapters/prodtools.py`, Phase C1) and `offline_preflight` (`core/adapters/offline_preflight.py`, Phase C2a); an adapter may also declare `config_problem(config)`, its config-name rule, which `graph.study_loop` checks against the first child name before launching; ``
- **Preflight**: replace the entry's text with: `The local 1-event G4 feasibility check gating a point before anything is submitted: \`mu2e -n 1\` with G4's surface check, the as-built GDML comparison and the overlap policy, run on this node from the study's code tarball (\`kits.offline_preflight.code_tarball\`, which must equal \`kits.prodtools.code_tarball\`). Its rules live in \`core/adapters/preflight_checks.py\`, shared by the engine's \`offline_preflight\` kit and the pipeline's \`bo_driver preflight\`; its workdir is \`<GRID_DATA_ROOT>/<config>/preflight/\`. Verdicts are \`pass\` / \`fail_managed\` / \`fail_init\` / \`ambiguous\`; only \`pass\` passes.`
- **Musing**: replace the entry's text with: `The Mu2e Offline release a code tarball builds against (its \`Code/backing\` link: SimJob MDC2025ax for engine studies, Run1Bap for the foilspf family). Since Phase C2a no study names one: the pre-check, the pipeline's prodtools calls and the jobs all source the code tarball's own \`Code/setup.sh\`.`
- **Grid tarball**: replace the entry's text with: `The \`Code.tar.bz2\` shipped to grid workers (\`kits.prodtools.code_tarball\`). The pre-check unpacks and runs the same file (\`prodtools_entry.unpacked\`, cached by content under \`<GRID_DATA_ROOT>/_code/\`), so the geometry it passes is the geometry the jobs build (the env-divergence incidents).`

`mode_specs/README.md`, section "Engine studies" (several old passages below span line breaks in the file; match them as whole lines):
- replace the section's first paragraph (the 10 lines from `A study whose kits are ALL engine kits` through `(\`core/bo_driver.py\`, \`graph/run.py\`, \`graph/closed_loop.py\`).`) with:
  ```
  A study whose kits are ALL engine kits (`core.modes.ENGINE`; a kit is an
  engine kit once it has either a `kits.toml` entry, like `toykit`, or a
  registered adapter, like `prodtools` and `offline_preflight`) runs through
  the contract engine — `graph.study_run` per point, `graph.study_loop` for a
  campaign — instead of the pipeline. Its `leaderboard.layout` should be
  `"v2"`, so its board carries `measure_sha` and refuses an append measured
  a different way. A study with a kit that has no adapter yet
  (`ce_sensitivity`, `flash_edep_per_pot` — Phase C2b) runs through the
  pipeline (`core/bo_driver.py`, `graph/run.py`, `graph/closed_loop.py`).
  ```
- replace the two-line bullet that begins `- A stage template names its prodtools` (it ends `are substituted.`) with two bullets:
  ```
  - A stage template names its prodtools `desc_fmt` (`{cfg}` and `{geom}`
    are substituted). The run label is the study setting
    `kits.prodtools.dsconf`: it must contain `{cfg}` and, filled in, hold
    only letters, digits and `_`. The foilspf family says `Run1Bak_{cfg}`,
    the only label the pipeline accepts; `prodtools_smoke` says
    `MDC2025ax_{cfg}`. A template still carrying `dsconf_fmt` is refused.
  - `"preflight": {"kit": "offline_preflight", ...}` gates each point on
    `mu2e -n 1` with G4's surface check, run on this node from
    `kits.offline_preflight.code_tarball`, which must equal
    `kits.prodtools.code_tarball` when a study has both. A failure (or an
    `ambiguous` run) marks the point broken before anything is submitted;
    the log is `<GRID_DATA_ROOT>/<config>/preflight/preflight.log`.
  ```
- section "Gotchas", the `${ARTIFACT}` bullet: `(\`kits.prodtools.code_tarball\`, \`kits.offline_preflight.musing\`)` → `(\`kits.prodtools.code_tarball\`, \`kits.offline_preflight.code_tarball\`)`.

`wiki/drivers/contract-engine.md` (its `timestamp` is already `'2026-09-26'`; again, old passages that span line breaks are matched as whole lines):
- frontmatter `description`: append `; C2a offline_preflight adapter (the geometry pre-check from the code tarball), dsconf study setting` to its last line (`  adapter (\`core/adapters/\`), --executor, zero-knob studies`).
- replace the block from `**Retry policy (\`core/contract.py:NativeKit\`)**` through the `- **Backoff (Phase C1):** ...` bullet (it ends `blip lasting seconds doesn't fail the step.`) with:
  ```
  **Retry policy (`core/contract.py:call_with_retries`, Phase C2a)**
  - `RETRY_PAUSES_S` is per contract call: `submit`, `check` and
    `describe` make 3 attempts, pausing 5 and 20 s; `status`, `results`
    and `cancel` make 5, pausing 5, 20, 60 and 180 s (about 4.5 min), so a
    point waiting hours on the grid rides out a server outage of minutes.
  - A `KitError` (transport failure, timeout, "server lost") is always
    retried. A `KitToolError` (the server refused) is retried for
    `status`, `results`, `check` and `describe`, which are read-only, and
    never for `submit` (a refused submit under the same name with
    different params must never be repeated) or `cancel`.
  - The prodtools adapter's `run_status` polls use the `status` budget
    from `status` and the `submit` budget when `submit` adopts a run;
    its `cancel_run` uses the `cancel` budget.
  ```
- in the `check_kits` bullet, replace its second and third lines
  ```
    kit the study names, confirms it offers `submit`/`status`/`results`
    (plus `check` when it's the preflight kit), that it reports a
  ```
  with
  ```
    kit the study names, confirms a kit that runs a step offers
    `submit`/`status`/`results` and the preflight kit `check` (a kit used
    only for the preflight needs only `check`), that it reports a
  ```
- replace the three-line bullet that begins `- **\`dsconf_fmt\`:**` with:
  ```
  - **`dsconf` (Phase C2a):** the run label is the study setting
    `kits.prodtools.dsconf` (required, holds `{cfg}`, letters/digits/`_`
    once filled); the stage templates no longer carry `dsconf_fmt`, and
    `entry_for_step` refuses one that does.
  ```
- in the paragraph that begins `The pipeline is reference-only`, change `` `desc_fmt` / `dsconf_fmt` to `desc` / `dsconf` `` (one line of the file) to `` `desc_fmt` to `desc` (`dsconf_fmt` is gone since C2a) ``.
- insert before `## Cross-links`:
  ```
  **Geometry pre-check kit and C1's small fixes (Phase C2a)**
  - Spec `docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md`,
    plan `docs/superpowers/plans/2026-09-26-c2a-preflight-kit.md`, branch
    `generic-study-phase-c2a`.
  - `core/adapters/preflight_checks.py` holds the pre-check's rules
    (`check_files`, `stage_workdir`, `run_check`, `classify` ->
    `Verdict(ok, code, reason, notes)`, `verify_stopping_target_gdml`),
    shared by `OfflinePreflightKit` (`core/adapters/offline_preflight.py`)
    and `bo_driver preflight`. The `holeRadii vector active` printout
    check is gone: upstream Offline v13_38_00 prints no such line, and the
    as-built GDML comparison checks every hole radius.
  - The check runs from the study's code tarball, unpacked once per
    content into `<GRID_DATA_ROOT>/_code/<sha256>/`
    (`prodtools_entry.unpacked`), with `MUSE_WORK_DIR` unset as prodtools'
    runlocal does; workdir `<GRID_DATA_ROOT>/<config>/preflight/`, emptied
    first, keeps `preflight.log` and `asbuilt.gdml`. `musing` is gone from
    every study and from `ModeSpec`; the pipeline's `sourced_env` sources
    the code tarball's `Code/setup.sh` instead.
  - The loader refuses a study whose `kits.offline_preflight.code_tarball`
    differs from `kits.prodtools.code_tarball`
    (`kit_registry.MATCHING_SETTINGS`). `check_kits` asks a kit used only
    for the preflight for `check` alone.
  - The kit's message is `<code>: <reason>`; `ambiguous` fails, with the
    log's last 40 lines. `node_preflight` was not changed.
  - Fixes: stuck receipts (`submitting`/`building`/`starting`) name
    prodtools' error and where to look (`jobsub_q`, or the local host and
    pid); a local run still `starting` after 10 min fails; a `done`/`short`
    reply with no `jobs` block raises; `KitClient.start` writes a
    `start` trace row; `entry` is reserved at load for a kit that takes
    stage templates; `graph.study_loop` checks `<prefix>R00_00` against
    each adapter's `config_problem` before launching.
  ```
- in `## Cross-links`, the source-file list: after `` `core/adapters/prodtools.py`, `core/adapters/prodtools_entry.py`, `` add `` `core/adapters/offline_preflight.py`, `core/adapters/preflight_checks.py`, ``.

`wiki/drivers/preflight.md`: set `timestamp: '2026-09-26'`, replace the three-line `updated_note:` value with the one line `updated_note: C2a — the rules moved to core/adapters/preflight_checks.py, shared with the engine's offline_preflight kit; runs from the code tarball; holeRadii canary dropped`, and insert right after the `# preflight — local G4 init feasibility check` heading:
```
> **2026-09-26 — Phase C2a:** the rules below now live in
> `core/adapters/preflight_checks.py`, shared by `bo_driver preflight` and
> the engine's `offline_preflight` kit ([contract-engine](/drivers/contract-engine.md)).
> Both run from the study's code tarball (unpacked under
> `<GRID_DATA_ROOT>/_code/<sha256>/`), not a musing, in
> `<GRID_DATA_ROOT>/<config>/preflight/` rather than a /tmp workdir.
> Layer 2 (the `holeRadii vector active` canary) is gone: upstream Offline
> prints no such line and layer 3 checks every hole radius. Tests:
> `tests/test_preflight_checks.py`.
```

`wiki/index.md`, the contract-engine line: append `; C2a offline_preflight adapter (the geometry pre-check from the code tarball), dsconf study setting`.

`wiki/log.md`: insert right under the existing `## 2026-09-26` heading (above its first bullet):
```
- **updated** [contract-engine](/drivers/contract-engine.md): Phase C2a
  implemented on branch `generic-study-phase-c2a` — the `offline_preflight`
  adapter (the pre-check from the code tarball, `musing` gone), the run
  label as `kits.prodtools.dsconf`, retry budgets per call, and C1's other
  small fixes.
- **updated** [preflight](/drivers/preflight.md): the rules moved to
  `core/adapters/preflight_checks.py`; the holeRadii canary is dropped.
```

- [ ] **Step 6: Run the suite once more**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass (`tests/test_no_hardcoded_paths.py` scans `CONTEXT.md`).

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/engine_studies/prodtools_smoke.json tests/test_study_engine.py \
  CONTEXT.md mode_specs/README.md wiki/drivers/contract-engine.md \
  wiki/drivers/preflight.md wiki/index.md wiki/log.md
git commit -F - <<'EOF'
docs: the smoke study's pre-check; engine docs and wiki for Phase C2a

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
EOF
```

---

## Acceptance (the controller, after the final review)

These run real G4 and the real prodtools servers locally, so they are not subagent tasks. Nothing goes to the grid. Set once (a fresh data root: the smoke study's `measure_sha` changed with `dsconf` and the pre-check settings, so the C1 board would refuse its row):

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch && source ./activate.sh
export AUTORESEARCH_PRODTOOLS=/exp/mu2e/app/users/oksuzian/muse_050125/prodtools
export AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c2accept
S=$AUTORESEARCH_DATA_ROOT/studies
mkdir -p $S
export AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies:$S
```

The broken geometry: `prodtools_smoke` with every foil's hole radius 1.2 times its outer radius, so `G4Tubs` gets `pRMin > pRMax` (GeomSolids0002, the foilsg incident's shape) in any release. A const will not do it: the profiles clip `f` to [0, 0.95] and `rOut` to [30, 150] mm, so the one line changed is the `stoppingTarget.holeRadii` geometry line:

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" - <<'EOF'
import json, os
doc = json.load(open("tests/fixtures/engine_studies/prodtools_smoke.json"))
doc["name"] = "c2a_broken"
doc["note"] = ("C2a acceptance: prodtools_smoke with every hole radius 1.2x "
               "its foil's outer radius (G4Tubs pRMin > pRMax), a geometry "
               "the pre-check must fail.")
doc["leaderboard"]["file"] = "leaderboards/leaderboard_c2a_broken.tsv"
(line,) = [l for l in doc["geom"]["lines"]
           if l.get("key") == "stoppingTarget.holeRadii"]
assert line["per_index"]["expr"] == "f_p[i] * rOut_p[i]"
line["per_index"]["expr"] = "1.2 * rOut_p[i]"
out = os.path.join(os.environ["AUTORESEARCH_DATA_ROOT"], "studies",
                   "c2a_broken.json")
open(out, "w").write(json.dumps(doc, indent=1) + "\n")
EOF
```

1. **The smoke study end to end, locally, on MDC2025ax:**
   `time PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.study_run --study prodtools_smoke --config c2alocal01 --campaign c2a --executor local`
   exits 0; `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/c2alocal01/state/preflight_verdict.json` has `"ok": true` and a message starting `pass:`; `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/leaderboard_prodtools_smoke.tsv` has one row with `ce_jobs_ok` 1. If the pre-check fails only on the zero-overlap policy (MDC2025ax may carry stock overlaps Run1Bap does not), stop and report the volumes from `.../c2alocal01/preflight/preflight.log`; do not flip `require_zero_overlaps` without the operator.
2. **The broken geometry, new side:**
   `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.study_run --study c2a_broken --config c2abroken01 --campaign c2a --executor local`
   exits 0; `.../c2abroken01/state/preflight_verdict.json` has `"ok": false` and a message starting `fail_managed:`; `.../c2abroken01/prodtools/` does not exist (nothing was submitted).
3. **Old verdicts, at the C1 branch tip (Run1Bap musing):**
   ```bash
   git worktree add --detach $AUTORESEARCH_DATA_ROOT/c1tip generic-study-phase-c1
   PYTHONPATH= "$AUTORESEARCH_PYTHON" - <<'EOF'
   import os, pathlib, sys
   sys.path.insert(0, "core")
   import study as st
   root = pathlib.Path(os.environ["AUTORESEARCH_DATA_ROOT"])
   d = root / "autoresearch_bo_work" / "proposals" / "foilspfbpz"
   d.mkdir(parents=True, exist_ok=True)
   for cfg, path in (("c2aoldpass01", "tests/fixtures/engine_studies/prodtools_smoke.json"),
                     ("c2aoldbroken01", str(root / "studies" / "c2a_broken.json"))):
       (d / f"{cfg}_geom.txt").write_text(st.load_study_file(path).geom.render([]))
   EOF
   cd $AUTORESEARCH_DATA_ROOT/c1tip
   for cfg in c2aoldpass01 c2aoldbroken01; do
     env -u AUTORESEARCH_STUDY_PATH AUTORESEARCH_MODE=foilspfbpz PYTHONPATH= \
       "$AUTORESEARCH_PYTHON" core/bo_driver.py --mode foilspfbpz preflight $cfg \
       --emit-json $AUTORESEARCH_DATA_ROOT/old_$cfg.json
   done
   cd /exp/mu2e/app/users/oksuzian/autoresearch
   cat $AUTORESEARCH_DATA_ROOT/old_c2aoldpass01.json $AUTORESEARCH_DATA_ROOT/old_c2aoldbroken01.json
   ```
   (`AUTORESEARCH_STUDY_PATH` is unset for the old side: the C1 loader would refuse this branch's smoke study, which carries `dsconf` and the new pre-check settings.) The pass geometry is foilspfbpz at gridphaseA01's point, which `tests/test_study_engine.py` pins as the smoke study's geometry. Expected verdicts: `pass` and `fail_managed`, the same codes as steps 1 and 2.
4. **Record the overlap counts** (they may differ between releases): `grep -c "Overlap is detected" $AUTORESEARCH_DATA_ROOT/autoresearch_bo_work/preflight/foilspfbpz/c2aold*.log $AUTORESEARCH_DATA_ROOT/autoresearch_grid/c2a*/preflight/preflight.log`. Put the four verdicts, the counts, and step 1's wall time in `wiki/drivers/contract-engine.md` (a "C2a acceptance" bullet) with a `wiki/log.md` line, then `git worktree remove $AUTORESEARCH_DATA_ROOT/c1tip`.
