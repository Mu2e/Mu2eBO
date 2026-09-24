# Generic Studies, Phase A (Study Model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every study is a schema-2 JSON file loaded into one `Study` model. The leaderboard, the surrogate glue, the driver's evaluate verb and the MCP adapter read only `Study` fields. foilspf keeps running unchanged, and parity is verified against goldens captured before any change.

**Architecture:**
- A new stdlib-only loader, `core/study.py`, validates schema 2 using a kit declaration table, `core/kit_registry.py`.
- A temporary view, `core/study_compat.py`, builds today's `ModeSpec` from a `Study`, so `pipeline.py`, `runtime.py`, preflight and the graph keep working until Phase C deletes them.
- The 7 live specs and 3 test fixtures are converted once by a throwaway script, and then the old loader (`core/mode_json.py`) is deleted.
- The generic consumers (`core/leaderboard.py`, `core/botorch_predict.py`, `core/bo_driver.py` evaluate, `surrogate/adapter.py`) are then rewritten to use objective names, directions, transforms and the constraint from the `Study`.

**Tech Stack:** Python 3 (ana 2.8.0 via `$AUTORESEARCH_PYTHON`), stdlib `unittest`, surrokit (GP and pickers), torch (only in `botorch_predict.py`).

**Spec:** `docs/superpowers/specs/2026-09-23-generic-study-design.md`. Read the Phase A row, "The study file (schema 2)", "Field rules" and "Leaderboard rows".

## Global Constraints

- **ADR-0002:** every schema key is required, unknown keys are rejected, there are no silent defaults, and every error names the file, the field and the rule.
- **Stdlib only** in `core/study.py`, `core/kit_registry.py`, `core/study_compat.py` and `core/leaderboard.py`. `core/leaderboard.py` keeps its "no project imports" rule.
- **Import mirroring:** modules imported both as `core.X` and as bare `X` use the `if __package__:` pattern already in `core/mode_json.py` and `core/modes.py`.
- **Tests never write under `leaderboards/` or `mode_specs/`.** Use temp dirs and temp copies. The one exception is the existing wiring test, which cleans up after itself.
- **Suite command:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` It must be green at every commit.
- **One test module:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study -v`
- **Golden harness:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check <sections>`
- **No personal paths:** `tests/test_no_hardcoded_paths.py` must stay green. Use `${ARTIFACT}/…` in specs and fixtures.
- **Commit messages** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```
- **The only intended behavior change:** the flash objective no longer falls back to `flash_edep_per_event` when `flash_edep_per_pot` is missing. Everything else is bit-identical.

---

### Task 1: Capture parity baselines before any change

**Files:**
- Modify: `tests/golden_parity.py` (add sections `d` and `e`, and wire them into `main()`)
- Create: `tests/goldens/spec_dump_baseline.json`, `tests/goldens/ask_inputs_baseline.json`, `tests/goldens/parity_a_baseline.json`, `tests/goldens/leaderboard_bo_foilsflash.frozen.tsv` (all by running `capture`)

**Interfaces:**
- Produces: sections `d` (every live `ModeSpec` field, plus rendered-geometry hashes at 3 points) and `e` (a fingerprint of the exact `surrokit.ask` inputs for `budget_sob`, `qnehvi` and `qlnei`). Tasks 5, 7 and 8 run `check d e`.

- [ ] **Step 1: Add section d (spec dump) to `tests/golden_parity.py`**

Add below the `C_BASE = …` line:

```python
D_BASE = GOLDENS / "spec_dump_baseline.json"
E_BASE = GOLDENS / "ask_inputs_baseline.json"

# Every ModeSpec field except `geom` (pinned through rendered text below).
_SPEC_FIELDS = (
    "name", "musing", "grid_tarball", "grid_stages", "stage_target_overrides",
    "presubmit_after", "stage_tuning", "bounds_lo", "bounds_hi", "int_dims",
    "dumps_gdml", "verifies_foil_gdml", "checks_managed_overlap",
    "require_zero_overlaps", "knob_names", "knob_fmts", "metric_cols",
    "obs_noise", "metrics", "leaderboard_rel")


def _jsonable(v):
    if isinstance(v, tuple):
        return [_jsonable(e) for e in v]
    if isinstance(v, dict):
        return {k: _jsonable(e) for k, e in sorted(v.items())}
    return v


def _sample_points(spec):
    lo, hi = spec.bounds_lo, spec.bounds_hi
    return {"lo": list(lo),
            "mid": [(a + b) / 2 for a, b in zip(lo, hi)],
            "q30": [a + 0.3 * (b - a) for a, b in zip(lo, hi)]}


def section_d():
    """Every live ModeSpec, field by field, plus sha256 of geom.render at 3
    points. Pins the schema-2 conversion: the Phase-A pipeline view must
    rebuild today's ModeSpec exactly."""
    import modes
    out = {}
    for name in sorted(modes.SPECS):
        spec = modes.SPECS[name]
        rec = {f: _jsonable(getattr(spec, f)) for f in _SPEC_FIELDS}
        rec["geom_sha"] = {
            k: hashlib.sha256(spec.geom.render(x).encode()).hexdigest()
            for k, x in _sample_points(spec).items()}
        out[name] = rec
    return out
```

- [ ] **Step 2: Add section e (ask-input fingerprint) below `section_d`**

```python
def section_e():
    """sha256 of the exact arguments compute_explore_picks hands to
    surrokit.ask, per picker, on the frozen foilsflash board. Pick OUTPUTS
    are not bit-reproducible run to run (wiki/incidents/hybrid-picker-scipy-
    abnormal-retry-nondeterminism.md); identical INPUTS are what Phase A must
    preserve."""
    import botorch_predict as bp
    mode = bo.MODES["foilsflash"]
    spec_lo = list(bp._modes.SPECS["foilsflash"].bounds_lo)
    spec_hi = list(bp._modes.SPECS["foilsflash"].bounds_hi)
    pending = [[(a + b) / 2 for a, b in zip(spec_lo, spec_hi)]]
    captured = {}

    def fake_ask(problem, X, Y, **kw):
        captured["args"] = {"problem": repr(problem), "X": X, "Y": Y,
                            **{k: kw[k] for k in sorted(kw)}}
        return [list(problem.bounds_lo)] * kw["q"]

    orig_ask = bp.surrokit.ask
    orig, orig_arch = mode.leaderboard, mode.leaderboard_archive
    mode.leaderboard, mode.leaderboard_archive = FROZEN_LB, None
    out = {}
    try:
        bp.surrokit.ask = fake_ask
        for picker in ("budget_sob", "qnehvi", "qlnei"):
            bp.compute_explore_picks("foilsflash", q=2, round_idx=3,
                                     picker=picker, x_pending=pending)
            blob = json.dumps(captured["args"], sort_keys=True, default=repr)
            out[picker] = {"sha": hashlib.sha256(blob.encode()).hexdigest(),
                           "problem": captured["args"]["problem"],
                           "n_rows": len(captured["args"]["X"])}
    finally:
        bp.surrokit.ask = orig_ask
        mode.leaderboard, mode.leaderboard_archive = orig, orig_arch
    return out
```

- [ ] **Step 3: Wire d and e into `main()`**

In `main()`, change the default section list:

```python
    sections = sys.argv[2:] or ["a", "b", "c", "d", "e"]
```

Before the final summary block of `main()` (after the `if "c" in sections:` block), add:

```python
    for key, fn, base_path in (("d", section_d, D_BASE),
                               ("e", section_e, E_BASE)):
        if key not in sections:
            continue
        cur = fn()
        if action == "capture":
            base_path.write_text(json.dumps(cur, indent=2, sort_keys=True))
            print(f"[{key}] captured -> {base_path}")
            continue
        base = json.loads(base_path.read_text())
        ok = cur == base
        print(f"[{key}] parity: {'OK' if ok else 'MISMATCH'}")
        if not ok:
            for k in sorted(set(base) | set(cur)):
                if base.get(k) != cur.get(k):
                    print(f"    {k}: baseline={json.dumps(base.get(k))[:400]}\n"
                          f"         current ={json.dumps(cur.get(k))[:400]}")
            fails += 1
```

- [ ] **Step 4: Capture all four baselines**

Run:
```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py capture a b d e
```
Expected output, one line each: `[a] captured -> …`, `[b] captured -> …`, `[d] captured -> …`, `[e] captured -> …`.

Section b copies the committed foilsflash board to `tests/goldens/leaderboard_bo_foilsflash.frozen.tsv` if that file is missing. Section `c` needs real G4 and is not part of the Phase A gates.

- [ ] **Step 5: Confirm the baselines reproduce**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: `[a] round-trip parity: OK`, `[b] history tensor fingerprint: OK`, `[d] parity: OK`, `[e] parity: OK`.

- [ ] **Step 6: Commit**

```bash
git add tests/golden_parity.py tests/goldens/
git commit -m "test(golden): pin ModeSpec dump and surrokit.ask inputs before the schema-2 switch"
```

---

### Task 2: Kit declarations and the schema-2 study loader

**Files:**
- Create: `core/kit_registry.py`
- Create: `core/study.py`
- Create: `tests/fixtures/studies/demo.json`
- Test: `tests/test_study.py`

**Interfaces:**
- Consumes: `geom_template.GeomTemplate.from_dict(d, knob_names, where)`, `geom_template.compile_expr(src, allowed_names, where)`, `geom_template.eval_expr(compiled, env)`, `geom_template._validate_fmt(fmt, where)`, `geom_template._RESERVED_ELEMENTWISE_NAMES`, `paths.artifact(rel)`
- Produces:
  - `kit_registry.KITS: dict[str, KitDecl]`, where `KitDecl` has `name`, `study_keys` (dict key→validator, all required), `fixed_keys` (dict key→validator, each optional), `uses_entries`, `step_kit` and `check_kit`.
  - `kit_registry.validate_study_settings(kit, settings, where) -> dict` and `kit_registry.validate_fixed(kit, fixed, where) -> dict`.
  - `study.Study`, a frozen dataclass with fields `path, name, note, knobs, derive, geom, geom_writer, kits, preflight, steps, objectives, constraints, extra_metrics, extra_columns, leaderboard_rel, layout, context, spec_sha`, and properties `knob_names, knob_fmts, bounds_lo, bounds_hi, int_dims, value_names, consts`.
  - `study.Knob(name, type, min, max, unit, fmt)` and `study.Step(step, kit, entry, files, files_from, params, fixed)`.
  - `study.Objective(name, metric, direction, transform, noise, fmt)`, with properties `.step` and `.key` (the two halves of `metric`).
  - `study.StudyConstraint(name, bound, value, k_sigma)`, where `bound` is `"max"` or `"min"`.
  - `study.ExtraMetric(name, metric, fmt)` and `study.ExtraColumn(name, expr, fmt)`. `ExtraColumn` has a method `evaluate(env: dict) -> float`.
  - `study.load_study_file(path: Path) -> Study`
  - `study.load_study_dirs(primary: Path, extra: str | None) -> dict[str, Study]`, where `extra` is the colon-separated `$AUTORESEARCH_STUDY_PATH`.

- [ ] **Step 1: Write the fixture `tests/fixtures/studies/demo.json`**

```json
{
  "schema": 2,
  "name": "demo",
  "note": "schema-2 test fixture shaped like the foilspf family",
  "knobs": [
    {"name": "a", "type": "real", "min": 1.0, "max": 3.0, "unit": "mm", "fmt": "{:.4f}"},
    {"name": "b", "type": "real", "min": 0.0, "max": 1.0, "unit": "", "fmt": "{:.4f}"}
  ],
  "derive": {
    "consts": {"n_el": 5, "z0": 100.0},
    "exprs": {"ab": "a * b"},
    "profiles": {"a_p": {"kind": "lagrange", "count": "n_el",
                         "control": ["a", "ab", "a"], "clip": [0.0, 10.0]}}
  },
  "geom": {
    "writer": "offline_simpleconfig",
    "base": "Offline/Mu2eG4/geom/geom_run1_a.txt",
    "lines": [
      {"key": "demo.z0", "type": "double", "expr": "z0", "fmt": "{:.4f}"},
      {"key": "demo.ab", "type": "double", "expr": "ab", "fmt": "{:.6f}"},
      {"key": "demo.radii", "type": "vector<double>", "fmt": "{:.4f}",
       "per_index": {"count": "n_el", "expr": "a_p[i]"}}
    ]
  },
  "kits": {
    "prodtools": {"code_tarball": "${ARTIFACT}/demo/Code_demo.tar.bz2"},
    "offline_preflight": {"musing": "${ARTIFACT}/demo/setup_local.sh",
                          "dumps_gdml": true, "verifies_foil_gdml": true,
                          "checks_managed_overlap": true,
                          "require_zero_overlaps": true}
  },
  "preflight": {"kit": "offline_preflight", "params": {}, "files": ["geom"]},
  "evaluate": [
    {"step": "mubeam", "kit": "prodtools", "entry": "mubeam", "files": ["geom"],
     "files_from": [], "params": {},
     "fixed": {"njobs": 15, "events_per_job": 200000, "memory_mb": 2000, "quorum": 0.8}},
    {"step": "mustops_ce", "kit": "prodtools", "entry": "mustops_ce", "files": ["geom"],
     "files_from": ["mubeam"], "params": {},
     "fixed": {"njobs": 15, "events_per_job": 75000, "memory_mb": 2000, "quorum": 0.8}},
    {"step": "elebeam_flash", "kit": "prodtools", "entry": "elebeam_flash", "files": ["geom"],
     "files_from": [], "params": {},
     "fixed": {"njobs": 100, "events_per_job": 110000, "memory_mb": 2000}},
    {"step": "sob", "kit": "ce_sensitivity", "entry": null, "files": [],
     "files_from": ["mubeam", "mustops_ce"], "params": {}, "fixed": {}},
    {"step": "flash", "kit": "flash_edep_per_pot", "entry": null, "files": [],
     "files_from": ["elebeam_flash"], "params": {}, "fixed": {}}
  ],
  "objectives": [
    {"name": "sob", "metric": "sob.s_over_sqrt_b", "direction": "max",
     "transform": "none", "noise": 0.006, "fmt": "{:.5f}"},
    {"name": "flash_edep", "metric": "flash.flash_edep_per_pot", "direction": "min",
     "transform": "log10", "noise": 0.01, "fmt": "{:.5e}"}
  ],
  "constraints": [{"name": "flash_edep", "max": 6.85443e-7, "k_sigma": 1.0}],
  "extra_metrics": [],
  "extra_columns": [
    {"name": "alpha", "expr": "alpha", "fmt": "{:.3f}"},
    {"name": "obj", "expr": "sob - alpha * flash_edep", "fmt": "{:.5f}"}
  ],
  "leaderboard": {"file": "leaderboards/leaderboard_demo_study.tsv",
                  "layout": "v1", "context": ["alpha"]}
}
```

- [ ] **Step 2: Write the failing tests `tests/test_study.py`**

```python
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import study as st  # noqa: E402
import kit_registry  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


def _doc():
    return json.loads(FIXTURE.read_text())


def _step(doc, name):
    return next(s for s in doc["evaluate"] if s["step"] == name)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def write(self, doc, name=None, directory=None):
        d = directory or self.tmp
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name or doc['name']}.json"
        p.write_text(json.dumps(doc))
        return p

    def load(self, doc):
        return st.load_study_file(self.write(doc))

    def assertRejects(self, doc, *needles):
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        for n in needles:
            self.assertIn(n, str(cm.exception))


class TestFixtureLoads(_Tmp):
    def test_fields(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.name, "demo")
        self.assertEqual(s.knob_names, ("a", "b"))
        self.assertEqual(s.bounds_lo, (1.0, 0.0))
        self.assertEqual(s.int_dims, ())
        self.assertEqual([o.name for o in s.objectives], ["sob", "flash_edep"])
        self.assertEqual(s.objectives[1].step, "flash")
        self.assertEqual(s.objectives[1].key, "flash_edep_per_pot")
        self.assertEqual(s.constraints[0].bound, "max")
        self.assertEqual(s.value_names, ("sob", "flash_edep"))
        self.assertEqual(s.layout, "v1")
        self.assertEqual(s.context, ("alpha",))
        self.assertEqual(s.consts, {"n_el": 5, "z0": 100.0})
        self.assertEqual([x.step for x in s.steps],
                         ["mubeam", "mustops_ce", "elebeam_flash", "sob", "flash"])
        self.assertEqual(s.kits["prodtools"]["code_tarball"][-len("Code_demo.tar.bz2"):],
                         "Code_demo.tar.bz2")
        self.assertNotIn("${", s.kits["prodtools"]["code_tarball"])

    def test_geom_renders_profile(self):
        s = st.load_study_file(FIXTURE)
        text = s.geom.render([2.0, 0.5])
        self.assertIn("double demo.ab = 1.000000;", text)
        self.assertIn("vector<double> demo.radii = {", text)

    def test_extra_column_evaluates(self):
        s = st.load_study_file(FIXTURE)
        obj = next(c for c in s.extra_columns if c.name == "obj")
        self.assertAlmostEqual(
            obj.evaluate({"sob": 3.0, "flash_edep": 1e-6, "alpha": 1e5, **s.consts}),
            2.9)

    def test_spec_sha_is_stable_and_content_sensitive(self):
        a = self.load(_doc())
        doc = _doc()
        doc["note"] = "changed"
        b = self.load(doc)
        self.assertEqual(a.spec_sha, st.load_study_file(FIXTURE).spec_sha)
        self.assertNotEqual(a.spec_sha, b.spec_sha)


class TestTopLevel(_Tmp):
    def test_every_top_key_required(self):
        for key in st._TOP:
            doc = _doc()
            del doc[key]
            with self.subTest(key=key):
                self.assertRejects(doc, key)

    def test_unknown_top_key(self):
        doc = _doc()
        doc["stages"] = []
        self.assertRejects(doc, "stages")

    def test_schema_must_be_2(self):
        doc = _doc()
        doc["schema"] = 1
        self.assertRejects(doc, "schema")

    def test_duplicate_json_key(self):
        p = self.tmp / "demo.json"
        p.write_text(FIXTURE.read_text().replace(
            '"note":', '"note": "x", "note":', 1))
        with self.assertRaises(ValueError) as cm:
            st.load_study_file(p)
        self.assertIn("duplicate JSON key", str(cm.exception))


class TestKnobs(_Tmp):
    def test_int_knob_needs_integer_bounds(self):
        doc = _doc()
        doc["knobs"][0]["type"] = "int"
        doc["knobs"][0]["min"] = 1.5
        self.assertRejects(doc, "integer bounds")

    def test_int_dims_from_type(self):
        doc = _doc()
        doc["knobs"][0]["type"] = "int"
        self.assertEqual(self.load(doc).int_dims, (0,))

    def test_min_below_max(self):
        doc = _doc()
        doc["knobs"][1]["min"] = 2.0
        self.assertRejects(doc, "min")

    def test_knob_name_collides_with_column(self):
        doc = _doc()
        doc["knobs"][0]["name"] = "sob"
        self.assertRejects(doc, "sob")

    def test_reserved_elementwise_name(self):
        doc = _doc()
        doc["knobs"][0]["name"] = "i"
        self.assertRejects(doc, "reserved")


class TestDeriveAndGeom(_Tmp):
    def test_profile_kind_must_be_lagrange(self):
        doc = _doc()
        doc["derive"]["profiles"]["a_p"]["kind"] = "spline"
        self.assertRejects(doc, "lagrange")

    def test_derive_without_geom_rejected_in_phase_a(self):
        doc = _doc()
        doc["geom"] = None
        for s in doc["evaluate"]:
            s["files"] = []
        doc["preflight"]["files"] = []
        self.assertRejects(doc, "derive")

    def test_unknown_writer(self):
        doc = _doc()
        doc["geom"]["writer"] = "g4bl_include"
        self.assertRejects(doc, "writer")

    def test_geom_file_without_geom(self):
        doc = _doc()
        doc["geom"] = None
        doc["derive"] = {"consts": {}, "exprs": {}, "profiles": {}}
        self.assertRejects(doc, "geom")


class TestSteps(_Tmp):
    def test_unknown_kit(self):
        doc = _doc()
        _step(doc, "sob")["kit"] = "anakit"
        self.assertRejects(doc, "anakit")

    def test_files_from_unknown_step(self):
        doc = _doc()
        _step(doc, "mustops_ce")["files_from"] = ["nope"]
        self.assertRejects(doc, "nope")

    def test_cycle(self):
        doc = _doc()
        _step(doc, "mubeam")["files_from"] = ["mustops_ce"]
        self.assertRejects(doc, "cycle")

    def test_duplicate_step_name(self):
        doc = _doc()
        _step(doc, "flash")["step"] = "sob"
        self.assertRejects(doc, "duplicate")

    def test_prodtools_step_needs_entry(self):
        doc = _doc()
        _step(doc, "mubeam")["entry"] = None
        self.assertRejects(doc, "entry")

    def test_plugin_step_takes_no_entry(self):
        doc = _doc()
        _step(doc, "sob")["entry"] = "x"
        self.assertRejects(doc, "entry")

    def test_unknown_fixed_key(self):
        doc = _doc()
        _step(doc, "mubeam")["fixed"]["njob"] = 3
        self.assertRejects(doc, "njob")

    def test_fixed_value_type(self):
        doc = _doc()
        _step(doc, "mubeam")["fixed"]["quorum"] = 1.5
        self.assertRejects(doc, "quorum")

    def test_params_name_must_exist(self):
        doc = _doc()
        _step(doc, "mubeam")["params"] = {"x": "nope"}
        self.assertRejects(doc, "nope")


class TestKits(_Tmp):
    def test_missing_kit_setting(self):
        doc = _doc()
        del doc["kits"]["offline_preflight"]["require_zero_overlaps"]
        self.assertRejects(doc, "require_zero_overlaps")

    def test_configured_but_unused_kit(self):
        doc = _doc()
        doc["preflight"] = None   # offline_preflight keeps its settings
        self.assertRejects(doc, "unused")

    def test_used_kit_needs_settings(self):
        doc = _doc()
        del doc["kits"]["prodtools"]
        self.assertRejects(doc, "prodtools")

    def test_preflight_kit_must_offer_check(self):
        doc = _doc()
        doc["preflight"]["kit"] = "prodtools"
        self.assertRejects(doc, "check")

    def test_personal_path_refused(self):
        doc = _doc()
        doc["kits"]["prodtools"]["code_tarball"] = "/exp/mu2e/app/users/somebody/x.tar"  # personal-path-ok: made-up name, exercises the refusal
        self.assertRejects(doc, "personal")

    def test_registry_declares_the_zero_overlap_flag(self):
        self.assertIn("require_zero_overlaps",
                      kit_registry.KITS["offline_preflight"].study_keys)


class TestObjectivesAndConstraints(_Tmp):
    def test_at_least_one_objective(self):
        doc = _doc()
        doc["objectives"] = []
        doc["constraints"] = []
        doc["extra_columns"] = []
        self.assertRejects(doc, "objective")

    def test_metric_names_a_step(self):
        doc = _doc()
        doc["objectives"][0]["metric"] = "nostep.s_over_sqrt_b"
        self.assertRejects(doc, "nostep")

    def test_metric_needs_step_dot_key(self):
        doc = _doc()
        doc["objectives"][0]["metric"] = "s_over_sqrt_b"
        self.assertRejects(doc, "step.key")

    def test_direction_and_transform_enums(self):
        doc = _doc()
        doc["objectives"][0]["direction"] = "up"
        self.assertRejects(doc, "direction")
        doc = _doc()
        doc["objectives"][0]["transform"] = "ln"
        self.assertRejects(doc, "transform")

    def test_at_most_one_constraint(self):
        doc = _doc()
        doc["constraints"].append({"name": "sob", "min": 3.0, "k_sigma": 1.0})
        self.assertRejects(doc, "at most one")

    def test_constraint_needs_exactly_one_bound(self):
        doc = _doc()
        doc["constraints"][0]["min"] = 1e-9
        self.assertRejects(doc, "exactly one")

    def test_constraint_side_must_match_direction(self):
        doc = _doc()
        doc["constraints"] = [{"name": "flash_edep", "min": 1e-9, "k_sigma": 1.0}]
        self.assertRejects(doc, "'max'")

    def test_log10_bound_must_be_positive(self):
        doc = _doc()
        doc["constraints"][0]["max"] = 0.0
        self.assertRejects(doc, "positive")

    def test_extra_column_unknown_name(self):
        doc = _doc()
        doc["extra_columns"][1]["expr"] = "sob - beta"
        self.assertRejects(doc, "beta")


class TestLeaderboard(_Tmp):
    def test_layout_v2_arrives_in_phase_b(self):
        doc = _doc()
        doc["leaderboard"]["layout"] = "v2"
        self.assertRejects(doc, "Phase B")

    def test_dotdot_rejected(self):
        doc = _doc()
        doc["leaderboard"]["file"] = "../x.tsv"
        self.assertRejects(doc, "..")

    def test_context_collides_with_column(self):
        doc = _doc()
        doc["leaderboard"]["context"] = ["sob"]
        self.assertRejects(doc, "context")


class TestDirs(_Tmp):
    def test_name_must_match_stem(self):
        self.write(_doc(), name="other")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp, None)
        self.assertIn("file name", str(cm.exception))

    def test_study_path_adds_a_directory(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["name"] = "extra"
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_extra.tsv"
        self.write(doc, directory=self.tmp / "mine")
        out = st.load_study_dirs(self.tmp / "main", str(self.tmp / "mine"))
        self.assertEqual(sorted(out), ["demo", "extra"])

    def test_duplicate_name_across_dirs(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["leaderboard"]["file"] = "leaderboards/leaderboard_other.tsv"
        self.write(doc, directory=self.tmp / "mine")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp / "main", str(self.tmp / "mine"))
        self.assertIn("defined twice", str(cm.exception))

    def test_missing_study_path_dir(self):
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp, str(self.tmp / "nope"))
        self.assertIn("AUTORESEARCH_STUDY_PATH", str(cm.exception))

    def test_shared_leaderboard_rejected(self):
        self.write(_doc(), directory=self.tmp / "main")
        doc = _doc()
        doc["name"] = "twin"
        self.write(doc, directory=self.tmp / "main")
        with self.assertRaises(ValueError) as cm:
            st.load_study_dirs(self.tmp / "main", None)
        self.assertIn("leaderboard", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study -v`
Expected: an `ImportError`, because `study` and `kit_registry` don't exist yet.

- [ ] **Step 4: Write `core/kit_registry.py`**

```python
"""Declared kits for schema-2 studies (generic-study design, Phase A).

A study names kits in three places: study["kits"], study["preflight"]["kit"]
and each step's "kit". This table says which names exist and which settings
each accepts, so a typo is a load error. Phase B adds the adapters that
implement the evaluator contract under these same names. STDLIB ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict


def _positive_int(v, where):
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValueError(f"{where}: must be a positive int, got {v!r}")
    return v


def _fraction(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
        raise ValueError(f"{where}: must be a number in (0, 1], got {v!r}")
    return float(v)


def _flag(v, where):
    if not isinstance(v, bool):
        raise ValueError(f"{where}: must be true or false, got {v!r}")
    return v


def _path(v, where):
    if not isinstance(v, str) or not v:
        raise ValueError(f"{where}: must be a non-empty path string, got {v!r}")
    return v


@dataclass(frozen=True)
class KitDecl:
    name: str
    study_keys: Dict[str, Callable]   # study["kits"][name]: every key required
    fixed_keys: Dict[str, Callable]   # a step's "fixed": each key optional
    uses_entries: bool                # step "entry" names a stage template
    step_kit: bool                    # may appear in evaluate[]
    check_kit: bool                   # may be study["preflight"]["kit"]


KITS: Dict[str, KitDecl] = {d.name: d for d in (
    KitDecl("prodtools",
            study_keys={"code_tarball": _path},
            fixed_keys={"njobs": _positive_int, "events_per_job": _positive_int,
                        "memory_mb": _positive_int, "quorum": _fraction},
            uses_entries=True, step_kit=True, check_kit=False),
    KitDecl("offline_preflight",
            study_keys={"musing": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
            fixed_keys={}, uses_entries=False, step_kit=False, check_kit=True),
    KitDecl("ce_sensitivity", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False),
    KitDecl("flash_edep_per_pot", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False),
)}


def validate_study_settings(kit: str, settings, where: str) -> dict:
    """study["kits"][kit]: an object holding exactly the declared keys."""
    decl = KITS[kit]
    if not isinstance(settings, dict):
        raise ValueError(f"{where}: must be an object, got {settings!r}")
    unknown = sorted(set(settings) - set(decl.study_keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; kit {kit!r} "
                         f"accepts {sorted(decl.study_keys)}")
    missing = sorted(set(decl.study_keys) - set(settings))
    if missing:
        raise ValueError(f"{where}: missing required key(s) {missing} for "
                         f"kit {kit!r}")
    return {k: decl.study_keys[k](v, f"{where}[{k}]")
            for k, v in settings.items()}


def validate_fixed(kit: str, fixed, where: str) -> dict:
    """A step's "fixed": any subset of the declared keys, each type-checked."""
    decl = KITS[kit]
    if not isinstance(fixed, dict):
        raise ValueError(f"{where}: must be an object, got {fixed!r}")
    unknown = sorted(set(fixed) - set(decl.fixed_keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; kit {kit!r} "
                         f"accepts {sorted(decl.fixed_keys)}")
    return {k: decl.fixed_keys[k](v, f"{where}[{k}]") for k, v in fixed.items()}
```

- [ ] **Step 5: Write `core/study.py`**

```python
"""Schema-2 study files -> a frozen Study (generic-study design).

Every key is required, unknown keys are rejected, and every error names the
file, the field and the rule (ADR-0002). A study reaches the physics only
through the kits it names (core/kit_registry.py). STDLIB ONLY.
Spec: docs/superpowers/specs/2026-09-23-generic-study-design.md
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

if __package__:
    from core import kit_registry, paths
    from core.geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                                    _validate_fmt, compile_expr, eval_expr)
else:
    import kit_registry
    import paths
    from geom_template import (GeomTemplate, _RESERVED_ELEMENTWISE_NAMES,
                               _validate_fmt, compile_expr, eval_expr)

SCHEMA = 2
_TOP = ("schema", "name", "note", "knobs", "derive", "geom", "kits",
        "preflight", "evaluate", "objectives", "constraints", "extra_metrics",
        "extra_columns", "leaderboard")
_KNOB = ("name", "type", "min", "max", "unit", "fmt")
_DERIVE = ("consts", "exprs", "profiles")
_PROFILE = ("kind", "count", "control", "clip")
_GEOM = ("writer", "base", "lines")
_PREFLIGHT = ("kit", "params", "files")
_STEP = ("step", "kit", "entry", "files", "files_from", "params", "fixed")
_OBJECTIVE = ("name", "metric", "direction", "transform", "noise", "fmt")
_EXTRA_METRIC = ("name", "metric", "fmt")
_EXTRA_COLUMN = ("name", "expr", "fmt")
_LEADERBOARD = ("file", "layout", "context")
_WRITERS = ("offline_simpleconfig",)
_RENDERED_FILES = ("geom",)
_DIRECTIONS = ("max", "min")
_TRANSFORMS = ("none", "log10")
_ARTIFACT_TOKEN = "${ARTIFACT}/"


@dataclass(frozen=True)
class Knob:
    name: str
    type: str
    min: float
    max: float
    unit: str
    fmt: str


@dataclass(frozen=True)
class Step:
    step: str
    kit: str
    entry: Any
    files: Tuple[str, ...]
    files_from: Tuple[str, ...]
    params: Dict[str, str]
    fixed: Dict[str, Any]


@dataclass(frozen=True)
class Objective:
    name: str
    metric: str
    direction: str
    transform: str
    noise: float
    fmt: str

    @property
    def step(self) -> str:
        return self.metric.split(".", 1)[0]

    @property
    def key(self) -> str:
        return self.metric.split(".", 1)[1]


@dataclass(frozen=True)
class StudyConstraint:
    name: str
    bound: str      # "max" (value <= bound) or "min" (value >= bound)
    value: float
    k_sigma: float


@dataclass(frozen=True)
class ExtraMetric:
    name: str
    metric: str
    fmt: str

    @property
    def key(self) -> str:
        return self.metric.split(".", 1)[1]


@dataclass(frozen=True)
class ExtraColumn:
    name: str
    expr: str
    fmt: str
    _compiled: Any = field(compare=False, repr=False)

    def evaluate(self, env: Dict[str, Any]) -> float:
        return float(eval_expr(self._compiled, dict(env)))


@dataclass(frozen=True)
class Study:
    path: Path
    name: str
    note: str
    knobs: Tuple[Knob, ...]
    derive: Dict[str, Any]
    geom: Optional[GeomTemplate] = field(compare=False)
    geom_writer: Optional[str]
    kits: Dict[str, Dict[str, Any]]
    preflight: Optional[Dict[str, Any]]
    steps: Tuple[Step, ...]
    objectives: Tuple[Objective, ...]
    constraints: Tuple[StudyConstraint, ...]
    extra_metrics: Tuple[ExtraMetric, ...]
    extra_columns: Tuple[ExtraColumn, ...]
    leaderboard_rel: str
    layout: str
    context: Tuple[str, ...]
    spec_sha: str

    @property
    def knob_names(self) -> Tuple[str, ...]:
        return tuple(k.name for k in self.knobs)

    @property
    def knob_fmts(self) -> Tuple[str, ...]:
        return tuple(k.fmt for k in self.knobs)

    @property
    def bounds_lo(self) -> Tuple[float, ...]:
        return tuple(k.min for k in self.knobs)

    @property
    def bounds_hi(self) -> Tuple[float, ...]:
        return tuple(k.max for k in self.knobs)

    @property
    def int_dims(self) -> Tuple[int, ...]:
        return tuple(i for i, k in enumerate(self.knobs) if k.type == "int")

    @property
    def value_names(self) -> Tuple[str, ...]:
        """Objective then extra-metric names: the values a row carries."""
        return (tuple(o.name for o in self.objectives)
                + tuple(m.name for m in self.extra_metrics))

    @property
    def consts(self) -> Dict[str, Any]:
        return dict(self.derive["consts"])


class _DuplicateJsonKey(ValueError):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _no_duplicate_keys(pairs):
    """json.loads keeps the LAST duplicate key silently; refuse instead."""
    out = {}
    for k, v in pairs:
        if k in out:
            raise _DuplicateJsonKey(k)
        out[k] = v
    return out


def _obj(d, keys, where):
    """d must be an object holding exactly `keys`."""
    if not isinstance(d, dict):
        raise ValueError(f"{where}: must be an object, got {d!r}")
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: missing required field(s) {missing}")
    unknown = sorted(set(d) - set(keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; accepted keys "
                         f"are {sorted(keys)}")
    return d


def _list(v, where):
    if not isinstance(v, list):
        raise ValueError(f"{where}: must be a list, got {v!r}")
    return v


def _name(v, where):
    if not isinstance(v, str) or not v.isidentifier():
        raise ValueError(f"{where}: must be an identifier string, got {v!r}")
    return v


def _number(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}: must be a number, got {v!r}")
    return float(v)


def _expand(value, where):
    """Only '${ARTIFACT}/' is supported; a bare personal user area is
    refused (it would run only for that account)."""
    if not isinstance(value, str):
        return value
    if value.startswith(_ARTIFACT_TOKEN):
        return str(paths.artifact(value[len(_ARTIFACT_TOKEN):]))
    if "${" in value:
        raise ValueError(f"{where}: unknown variable in {value!r}; the only "
                         f"supported token is '${{ARTIFACT}}/'")
    if re.match(r"^/exp/mu2e/(app|data)/users/[^/]+/", value):
        raise ValueError(f"{where}: {value!r} hardcodes a personal user "
                         f"area; use '${{ARTIFACT}}/<rest-of-path>'")
    return value


def _metric(v, steps, where):
    if not isinstance(v, str) or v.count(".") != 1 or not all(v.split(".")):
        raise ValueError(f"{where}: metric must be 'step.key', got {v!r}")
    step = v.split(".", 1)[0]
    if step not in steps:
        raise ValueError(f"{where}: metric {v!r} names step {step!r}, which "
                         f"is not in evaluate[] ({sorted(steps)})")
    return v


def _knobs(raw, where):
    raw = _list(raw, f"{where}[knobs]")
    if not raw:
        raise ValueError(f"{where}[knobs]: at least one knob is required")
    out = []
    for i, k in enumerate(raw):
        kw = f"{where}[knobs[{i}]]"
        _obj(k, _KNOB, kw)
        name = _name(k["name"], f"{kw}[name]")
        if name in _RESERVED_ELEMENTWISE_NAMES:
            raise ValueError(f"{kw}: knob name {name!r} is reserved (the "
                             f"geometry renderer injects 'i' and 'n')")
        if k["type"] not in ("real", "int"):
            raise ValueError(f"{kw}[type]: must be 'real' or 'int', got "
                             f"{k['type']!r}")
        lo, hi = _number(k["min"], f"{kw}[min]"), _number(k["max"], f"{kw}[max]")
        if not lo < hi:
            raise ValueError(f"{kw}: min ({lo}) must be < max ({hi})")
        if k["type"] == "int" and not (lo.is_integer() and hi.is_integer()):
            raise ValueError(f"{kw}: an int knob needs integer bounds, got "
                             f"[{lo}, {hi}]")
        if not isinstance(k["unit"], str):
            raise ValueError(f"{kw}[unit]: must be a string (may be empty)")
        _validate_fmt(k["fmt"], f"{kw}[fmt]")
        out.append(Knob(name, k["type"], lo, hi, k["unit"], k["fmt"]))
    names = [k.name for k in out]
    if len(set(names)) != len(names):
        raise ValueError(f"{where}[knobs]: duplicate knob names {names}")
    return tuple(out)


def _derive_and_geom(doc, knob_names, where):
    derive = _obj(doc["derive"], _DERIVE, f"{where}[derive]")
    for k in _DERIVE:
        if not isinstance(derive[k], dict):
            raise ValueError(f"{where}[derive.{k}]: must be an object")
    profiles = {}
    for pname, p in derive["profiles"].items():
        pw = f"{where}[derive.profiles.{pname}]"
        _obj(p, _PROFILE, pw)
        if p["kind"] != "lagrange":
            raise ValueError(f"{pw}[kind]: only 'lagrange' exists, got "
                             f"{p['kind']!r}")
        profiles[pname] = {k: p[k] for k in ("count", "control", "clip")}
    geom = doc["geom"]
    if geom is None:
        if any(derive[k] for k in _DERIVE):
            raise ValueError(f"{where}[derive]: must be empty when geom is "
                             f"null in this version (derive without a "
                             f"geometry file arrives with Phase B)")
        return derive, None, None
    _obj(geom, _GEOM, f"{where}[geom]")
    if geom["writer"] not in _WRITERS:
        raise ValueError(f"{where}[geom.writer]: must be one of "
                         f"{list(_WRITERS)}, got {geom['writer']!r}")
    template = GeomTemplate.from_dict(
        {"base": geom["base"], "consts": derive["consts"],
         "derived": derive["exprs"], "profiles": profiles,
         "lines": geom["lines"]},
        knob_names, f"{where}[derive+geom]")
    return derive, template, geom["writer"]


def _steps(raw, has_geom, names, where):
    raw = _list(raw, f"{where}[evaluate]")
    if not raw:
        raise ValueError(f"{where}[evaluate]: at least one step is required")
    out = []
    for i, s in enumerate(raw):
        sw = f"{where}[evaluate[{i}]]"
        _obj(s, _STEP, sw)
        step = _name(s["step"], f"{sw}[step]")
        kit = s["kit"]
        if kit not in kit_registry.KITS or not kit_registry.KITS[kit].step_kit:
            raise ValueError(f"{sw}[kit]: {kit!r} is not a step kit; known: "
                             f"{sorted(k for k, d in kit_registry.KITS.items() if d.step_kit)}")
        decl = kit_registry.KITS[kit]
        entry = s["entry"]
        if decl.uses_entries and not (isinstance(entry, dict)
                                      or (isinstance(entry, str) and entry)):
            raise ValueError(f"{sw}[entry]: kit {kit!r} needs a stage-template "
                             f"name or an inline template object")
        if not decl.uses_entries and entry is not None:
            raise ValueError(f"{sw}[entry]: kit {kit!r} takes no entry; use null")
        files = tuple(_list(s["files"], f"{sw}[files]"))
        for f in files:
            if f not in _RENDERED_FILES:
                raise ValueError(f"{sw}[files]: unknown rendered file {f!r}; "
                                 f"known: {list(_RENDERED_FILES)}")
            if f == "geom" and not has_geom:
                raise ValueError(f"{sw}[files]: lists 'geom' but the study's "
                                 f"geom is null")
        params = s["params"]
        if not isinstance(params, dict):
            raise ValueError(f"{sw}[params]: must be an object")
        for pk, pv in params.items():
            if pv not in names:
                raise ValueError(f"{sw}[params.{pk}]: {pv!r} is not a knob, "
                                 f"const, expr or profile name")
        fixed = kit_registry.validate_fixed(kit, s["fixed"], f"{sw}[fixed]")
        out.append(Step(step, kit, entry, files,
                        tuple(_list(s["files_from"], f"{sw}[files_from]")),
                        dict(params), fixed))
    step_names = [s.step for s in out]
    if len(set(step_names)) != len(step_names):
        raise ValueError(f"{where}[evaluate]: duplicate step names {step_names}")
    for s in out:
        for up in s.files_from:
            if up not in step_names:
                raise ValueError(f"{where}[evaluate.{s.step}.files_from]: "
                                 f"unknown step {up!r}")
    _check_acyclic(out, where)
    return tuple(out)


def _check_acyclic(steps, where):
    deps = {s.step: set(s.files_from) for s in steps}
    state = {}

    def visit(n, trail):
        if state.get(n) == "done":
            return
        if state.get(n) == "open":
            raise ValueError(f"{where}[evaluate]: files_from forms a cycle "
                             f"{' -> '.join(trail + [n])}")
        state[n] = "open"
        for d in sorted(deps[n]):
            visit(d, trail + [n])
        state[n] = "done"

    for n in deps:
        visit(n, [])


def _kits_and_preflight(doc, steps, has_geom, where):
    kits_raw = doc["kits"]
    if not isinstance(kits_raw, dict):
        raise ValueError(f"{where}[kits]: must be an object")
    pre = doc["preflight"]
    used = {s.kit for s in steps}
    if pre is not None:
        pw = f"{where}[preflight]"
        _obj(pre, _PREFLIGHT, pw)
        kit = pre["kit"]
        if kit not in kit_registry.KITS or not kit_registry.KITS[kit].check_kit:
            raise ValueError(f"{pw}[kit]: {kit!r} does not offer a check; "
                             f"known: {sorted(k for k, d in kit_registry.KITS.items() if d.check_kit)}")
        for f in _list(pre["files"], f"{pw}[files]"):
            if f not in _RENDERED_FILES or (f == "geom" and not has_geom):
                raise ValueError(f"{pw}[files]: cannot provide {f!r}")
        if not isinstance(pre["params"], dict):
            raise ValueError(f"{pw}[params]: must be an object")
        used.add(kit)
    kits = {}
    for kit, settings in kits_raw.items():
        kw = f"{where}[kits.{kit}]"
        if kit not in kit_registry.KITS:
            raise ValueError(f"{kw}: unknown kit {kit!r}")
        if kit not in used:
            raise ValueError(f"{kw}: kit {kit!r} is configured but unused by "
                             f"any step or the preflight")
        checked = kit_registry.validate_study_settings(kit, settings, kw)
        kits[kit] = {k: _expand(v, f"{kw}[{k}]") for k, v in checked.items()}
    for kit in sorted(used):
        if kit_registry.KITS[kit].study_keys and kit not in kits:
            raise ValueError(f"{where}[kits]: kit {kit!r} is used but has no "
                             f"settings; it needs "
                             f"{sorted(kit_registry.KITS[kit].study_keys)}")
    return kits, pre


def _objectives(raw, step_names, where):
    raw = _list(raw, f"{where}[objectives]")
    if not raw:
        raise ValueError(f"{where}[objectives]: at least one objective is "
                         f"required")
    out = []
    for i, o in enumerate(raw):
        ow = f"{where}[objectives[{i}]]"
        _obj(o, _OBJECTIVE, ow)
        if o["direction"] not in _DIRECTIONS:
            raise ValueError(f"{ow}[direction]: must be one of "
                             f"{list(_DIRECTIONS)}, got {o['direction']!r}")
        if o["transform"] not in _TRANSFORMS:
            raise ValueError(f"{ow}[transform]: must be one of "
                             f"{list(_TRANSFORMS)}, got {o['transform']!r}")
        noise = _number(o["noise"], f"{ow}[noise]")
        if noise <= 0:
            raise ValueError(f"{ow}[noise]: must be > 0, got {noise}")
        _validate_fmt(o["fmt"], f"{ow}[fmt]")
        out.append(Objective(_name(o["name"], f"{ow}[name]"),
                             _metric(o["metric"], step_names, f"{ow}[metric]"),
                             o["direction"], o["transform"], noise, o["fmt"]))
    return tuple(out)


def _constraints(raw, objectives, where):
    raw = _list(raw, f"{where}[constraints]")
    if len(raw) > 1:
        raise ValueError(f"{where}[constraints]: at most one constraint in "
                         f"this version, got {len(raw)}")
    by_name = {o.name: o for o in objectives}
    out = []
    for i, c in enumerate(raw):
        cw = f"{where}[constraints[{i}]]"
        if not isinstance(c, dict):
            raise ValueError(f"{cw}: must be an object")
        bounds = [b for b in ("max", "min") if b in c]
        if len(bounds) != 1:
            raise ValueError(f"{cw}: needs exactly one of 'max' or 'min'")
        _obj(c, ("name", "k_sigma", bounds[0]), cw)
        if c["name"] not in by_name:
            raise ValueError(f"{cw}[name]: {c['name']!r} is not an objective")
        obj = by_name[c["name"]]
        # surrokit constrains an axis from below only; a maximized axis is
        # the raw value (max) or its negation (min), so the bound's side is
        # fixed by the direction.
        want = "max" if obj.direction == "min" else "min"
        if bounds[0] != want:
            raise ValueError(f"{cw}: objective {obj.name!r} is "
                             f"'{obj.direction}', so its constraint must be "
                             f"'{want}'")
        value = _number(c[bounds[0]], f"{cw}[{bounds[0]}]")
        if obj.transform == "log10" and value <= 0:
            raise ValueError(f"{cw}: a log10 objective needs a positive "
                             f"bound, got {value}")
        k = _number(c["k_sigma"], f"{cw}[k_sigma]")
        if k < 0:
            raise ValueError(f"{cw}[k_sigma]: must be >= 0, got {k}")
        out.append(StudyConstraint(obj.name, bounds[0], value, k))
    return tuple(out)


def _extras(doc, step_names, objectives, consts, context, where):
    metrics = []
    for i, m in enumerate(_list(doc["extra_metrics"], f"{where}[extra_metrics]")):
        mw = f"{where}[extra_metrics[{i}]]"
        _obj(m, _EXTRA_METRIC, mw)
        _validate_fmt(m["fmt"], f"{mw}[fmt]")
        metrics.append(ExtraMetric(_name(m["name"], f"{mw}[name]"),
                                   _metric(m["metric"], step_names, f"{mw}[metric]"),
                                   m["fmt"]))
    allowed = ({o.name for o in objectives} | {m.name for m in metrics}
               | set(consts) | set(context))
    columns = []
    for i, c in enumerate(_list(doc["extra_columns"], f"{where}[extra_columns]")):
        cw = f"{where}[extra_columns[{i}]]"
        _obj(c, _EXTRA_COLUMN, cw)
        _validate_fmt(c["fmt"], f"{cw}[fmt]")
        compiled = compile_expr(c["expr"], allowed, f"{cw}[expr]")
        columns.append(ExtraColumn(_name(c["name"], f"{cw}[name]"),
                                   c["expr"], c["fmt"], compiled))
    return tuple(metrics), tuple(columns)


def _leaderboard(raw, where):
    lb = _obj(raw, _LEADERBOARD, f"{where}[leaderboard]")
    rel = lb["file"]
    if not isinstance(rel, str) or Path(rel).is_absolute():
        raise ValueError(f"{where}[leaderboard.file]: must be a repo-relative "
                         f"path, got {rel!r}")
    if ".." in Path(rel).parts:
        raise ValueError(f"{where}[leaderboard.file]: must not contain '..' "
                         f"(got {rel!r})")
    if lb["layout"] != "v1":
        raise ValueError(f"{where}[leaderboard.layout]: only 'v1' in this "
                         f"version; 'v2' arrives with Phase B")
    context = tuple(_name(c, f"{where}[leaderboard.context]")
                    for c in _list(lb["context"], f"{where}[leaderboard.context]"))
    return Path(rel).as_posix(), lb["layout"], context


def _check_columns(knobs, objectives, metrics, columns, context, where):
    cols = (["config"] + [k.name for k in knobs] + [o.name for o in objectives]
            + [m.name for m in metrics] + [c.name for c in columns])
    seen = set()
    for c in cols:
        if c in seen:
            raise ValueError(f"{where}: leaderboard column {c!r} appears "
                             f"twice (knob, objective, extra metric or extra "
                             f"column names must all differ)")
        seen.add(c)
    clash = sorted(set(context) & seen)
    if clash:
        raise ValueError(f"{where}[leaderboard.context]: {clash} collide "
                         f"with column names")


def load_study_file(path: Path) -> Study:
    """Parse and validate one schema-2 study file. Raises ValueError."""
    path = Path(path)
    where = str(path)
    text = path.read_text()
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{where}: invalid JSON: {exc}") from None
    except _DuplicateJsonKey as exc:
        raise ValueError(f"{where}: duplicate JSON key {exc.key!r} (json.loads "
                         f"would silently keep the last one)") from None
    _obj(doc, _TOP, where)
    if doc["schema"] != SCHEMA:
        raise ValueError(f"{where}[schema]: must be {SCHEMA}, got "
                         f"{doc['schema']!r}")
    if not isinstance(doc["note"], str):
        raise ValueError(f"{where}[note]: must be a string")
    knobs = _knobs(doc["knobs"], where)
    knob_names = tuple(k.name for k in knobs)
    derive, geom, writer = _derive_and_geom(doc, knob_names, where)
    names = (set(knob_names) | set(derive["consts"]) | set(derive["exprs"])
             | set(derive["profiles"]))
    steps = _steps(doc["evaluate"], geom is not None, names, where)
    step_names = {s.step for s in steps}
    kits, preflight = _kits_and_preflight(doc, steps, geom is not None, where)
    objectives = _objectives(doc["objectives"], step_names, where)
    constraints = _constraints(doc["constraints"], objectives, where)
    rel, layout, context = _leaderboard(doc["leaderboard"], where)
    metrics, columns = _extras(doc, step_names, objectives, derive["consts"],
                               context, where)
    _check_columns(knobs, objectives, metrics, columns, context, where)
    sha = hashlib.sha256(json.dumps(doc, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()
    return Study(path=path, name=_name(doc["name"], f"{where}[name]"),
                 note=doc["note"], knobs=knobs, derive=derive, geom=geom,
                 geom_writer=writer, kits=kits, preflight=preflight,
                 steps=steps, objectives=objectives, constraints=constraints,
                 extra_metrics=metrics, extra_columns=columns,
                 leaderboard_rel=rel, layout=layout, context=context,
                 spec_sha=sha)


def load_study_dirs(primary: Path, extra: Optional[str]) -> Dict[str, Study]:
    """Every *.json in `primary` (flat: archive/ stays unloaded) and in each
    directory of the colon-separated `extra` ($AUTORESEARCH_STUDY_PATH)."""
    dirs = [Path(primary)]
    for d in (extra or "").split(":"):
        if not d:
            continue
        if not Path(d).is_dir():
            raise ValueError(f"AUTORESEARCH_STUDY_PATH names {d!r}, which is "
                             f"not a directory")
        dirs.append(Path(d))
    out: Dict[str, Study] = {}
    boards: Dict[str, Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            s = load_study_file(p)
            if s.name != p.stem:
                raise ValueError(f"{p}: study name {s.name!r} does not match "
                                 f"its file name {p.stem!r}")
            if s.name in out:
                raise ValueError(f"{p}: study {s.name!r} is defined twice "
                                 f"(also {out[s.name].path})")
            board = Path(s.leaderboard_rel).name
            if board in boards:
                raise ValueError(f"{p}: leaderboard basename {board!r} is "
                                 f"already used by {boards[board]}; two "
                                 f"studies sharing one board contaminate "
                                 f"each other's GP history")
            boards[board] = p
            out[s.name] = s
    return out
```

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study -v`
Expected: every test PASSES. If an assertion's needle doesn't appear in the message, fix the message in `study.py` so it names the field; don't weaken the test.

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK. The new modules are not wired into anything yet.

- [ ] **Step 8: Commit**

```bash
git add core/kit_registry.py core/study.py tests/test_study.py tests/fixtures/studies/demo.json
git commit -m "feat(study): schema-2 study loader and kit declarations"
```

---

### Task 3: The temporary pipeline view (`Study` → `ModeSpec`)

**Files:**
- Create: `core/study_compat.py`
- Test: `tests/test_study_compat.py`

**Interfaces:**
- Consumes: `study.load_study_file`, `study.Study`, `modes.ModeSpec`
- Produces: `study_compat.modespec_from_study(study) -> ModeSpec` and `study_compat.load_modespec(path) -> ModeSpec`. Both are deleted in Phase C together with `pipeline.py`'s verbs.

- [ ] **Step 1: Write the failing tests `tests/test_study_compat.py`**

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import study as st  # noqa: E402
import study_compat as sc  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


class TestView(unittest.TestCase):
    def setUp(self):
        self.spec = sc.load_modespec(FIXTURE)

    def test_pipeline_fields(self):
        s = self.spec
        self.assertEqual(s.grid_stages, ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(s.presubmit_after, {"mubeam": ("elebeam_flash",)})
        self.assertEqual(s.stage_target_overrides,
                         {"mubeam": 15, "mustops_ce": 15, "elebeam_flash": 100})
        self.assertEqual(s.stage_tuning["elebeam_flash"],
                         {"events_per_job": 110000, "memory_mb": 2000})
        self.assertEqual(s.stage_tuning["mubeam"]["quorum"], 0.8)
        self.assertTrue(s.require_zero_overlaps)
        self.assertTrue(s.musing.endswith("demo/setup_local.sh"))
        self.assertTrue(s.grid_tarball.endswith("demo/Code_demo.tar.bz2"))

    def test_leaderboard_fields(self):
        s = self.spec
        self.assertEqual(s.metric_cols, ("sob", "flash_edep", "alpha", "obj"))
        self.assertEqual(s.obs_noise, (0.006, 0.01))
        self.assertEqual(s.metrics, {"sob": ("s_over_sqrt_b",),
                                     "flash_edep": ("flash_edep_per_pot",)})
        self.assertEqual(s.knob_names, ("a", "b"))
        self.assertEqual(s.leaderboard_rel, "leaderboards/leaderboard_demo_study.tsv")

    def test_geom_is_the_studys(self):
        study = st.load_study_file(FIXTURE)
        self.assertEqual(self.spec.geom.render([2.0, 0.5]),
                         study.geom.render([2.0, 0.5]))


class TestRefusals(unittest.TestCase):
    """A study the Phase-A pipeline cannot run must fail loudly at load."""

    def _load(self, mutate):
        doc = json.loads(FIXTURE.read_text())
        mutate(doc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "demo.json"
            p.write_text(json.dumps(doc))
            with self.assertRaises(ValueError) as cm:
                sc.load_modespec(p)
        return str(cm.exception)

    def test_three_objectives(self):
        def m(d):
            d["objectives"].append({"name": "third", "metric": "sob.x",
                                    "direction": "max", "transform": "none",
                                    "noise": 0.1, "fmt": "{:.3f}"})
        self.assertIn("Phase-A pipeline", self._load(m))

    def test_input_rule(self):
        def m(d):
            d["evaluate"][1]["files_from"] = ["elebeam_flash"]
        self.assertIn("files_from", self._load(m))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_compat -v`
Expected: `ModuleNotFoundError: No module named 'study_compat'`

- [ ] **Step 3: Write `core/study_compat.py`**

```python
"""TEMPORARY: today's ModeSpec, built from a schema-2 Study.

pipeline.py, runtime.py, preflight and the graph still read ModeSpec
fields. This view keeps them running on schema-2 files until Phase C moves
foilspf onto the contract engine and deletes both this module and those
code paths. A study the old pipeline cannot run is refused here, loudly.
STDLIB ONLY.
"""
from __future__ import annotations

from pathlib import Path

if __package__:
    from core.study import Study, load_study_file
else:
    from study import Study, load_study_file

_PIPELINE_TUNING = ("events_per_job", "memory_mb", "quorum")
_PLUGINS = ("ce_sensitivity", "flash_edep_per_pot")


def _need(cond: bool, study: Study, why: str) -> None:
    if not cond:
        raise ValueError(f"{study.path}: cannot run on the Phase-A pipeline: "
                         f"{why}")


def modespec_from_study(study: Study):
    if __package__:
        from core.modes import ModeSpec
    else:
        from modes import ModeSpec

    _need(study.geom is not None, study, "it has no geom")
    _need(study.preflight is not None
          and study.preflight["kit"] == "offline_preflight", study,
          "its preflight is not offline_preflight")
    _need(study.layout == "v1", study, "its leaderboard layout is not v1")
    _need(len(study.objectives) == 2, study,
          f"it has {len(study.objectives)} objectives; the pipeline writes "
          f"exactly 2")
    _need(not study.extra_metrics, study, "it declares extra_metrics")
    _need([c.name for c in study.extra_columns] == ["alpha", "obj"], study,
          "its extra_columns are not ['alpha', 'obj']")
    plugin_steps = {s.step for s in study.steps if s.kit in _PLUGINS}
    for o in study.objectives:
        _need(o.step in plugin_steps, study,
              f"objective {o.name!r} does not come from a harvest plugin")
    grid = [s for s in study.steps if s.kit == "prodtools"]
    _need(bool(grid), study, "it has no prodtools steps")
    roots = [s.step for s in grid if not s.files_from]
    _need(bool(roots) and roots[0] == grid[0].step, study,
          "its first prodtools step must take no files_from")
    for s in grid:
        _need(s.files_from in ((), (roots[0],)), study,
              f"step {s.step!r} files_from must be [] or [{roots[0]!r}] "
              f"(the pipeline's only input rule)")

    pre = study.kits["offline_preflight"]
    o0, o1 = study.objectives
    return ModeSpec(
        name=study.name,
        musing=pre["musing"],
        grid_tarball=study.kits["prodtools"]["code_tarball"],
        grid_stages=tuple(s.step for s in grid),
        stage_target_overrides={s.step: s.fixed["njobs"] for s in grid
                                if "njobs" in s.fixed},
        presubmit_after=({roots[0]: tuple(roots[1:])} if roots[1:] else {}),
        stage_tuning={s.step: {k: s.fixed[k] for k in _PIPELINE_TUNING
                               if k in s.fixed}
                      for s in grid
                      if any(k in s.fixed for k in _PIPELINE_TUNING)},
        bounds_lo=study.bounds_lo,
        bounds_hi=study.bounds_hi,
        int_dims=study.int_dims,
        dumps_gdml=pre["dumps_gdml"],
        verifies_foil_gdml=pre["verifies_foil_gdml"],
        checks_managed_overlap=pre["checks_managed_overlap"],
        require_zero_overlaps=pre["require_zero_overlaps"],
        knob_names=study.knob_names,
        knob_fmts=study.knob_fmts,
        metric_cols=(o0.name, o1.name, "alpha", "obj"),
        obs_noise=(o0.noise, o1.noise),
        geom=study.geom,
        metrics={o.name: (o.key,) for o in study.objectives},
        leaderboard_rel=study.leaderboard_rel,
    )


def load_modespec(path: Path):
    return modespec_from_study(load_study_file(Path(path)))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_compat -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/study_compat.py tests/test_study_compat.py
git commit -m "feat(study): temporary Study->ModeSpec view for the Phase-A pipeline"
```

---

### Task 4: The one-time converter, checked against the old loader

**Files:**
- Create: `tools/convert_spec_v2.py`
- Test: `tests/test_convert_spec_v2.py`

**Interfaces:**
- Consumes: `mode_json.load_mode_file` (the old loader, still present), `study_compat.modespec_from_study`, `study.load_study_file`
- Produces: `convert_spec_v2.convert(doc: dict) -> dict`, and the CLI `tools/convert_spec_v2.py --in-place FILE...`

- [ ] **Step 1: Write the failing tests `tests/test_convert_spec_v2.py`**

```python
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tools"))
import convert_spec_v2 as cv  # noqa: E402
import study_compat as sc  # noqa: E402
from mode_json import load_mode_file  # noqa: E402

LIVE = sorted((ROOT / "mode_specs").glob("*.json"))
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "modes").glob("*.json"))


def _x_points(spec):
    lo, hi = spec.bounds_lo, spec.bounds_hi
    return [list(lo), [(a + b) / 2 for a, b in zip(lo, hi)],
            [a + 0.3 * (b - a) for a, b in zip(lo, hi)]]


class TestConversionMatchesOldLoader(unittest.TestCase):
    def _compare(self, path, allow_presubmit_change=False):
        old = load_mode_file(path)
        doc = json.loads(path.read_text())
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / path.name
            p.write_text(json.dumps(cv.convert(doc)))
            new = sc.load_modespec(p)
        skip = {"geom", "metrics"}
        if allow_presubmit_change:
            skip.add("presubmit_after")
        for f in dataclasses.fields(old):
            if f.name in skip:
                continue
            with self.subTest(file=path.name, field=f.name):
                self.assertEqual(getattr(new, f.name), getattr(old, f.name))
        # The one intended change: no per-event fallback for the flash metric.
        self.assertEqual(new.metrics["sob"], old.metrics["sob"])
        self.assertEqual(new.metrics[old.metric_cols[1]],
                         old.metrics[old.metric_cols[1]][:1])
        for x in _x_points(old):
            self.assertEqual(new.geom.render(x), old.geom.render(x))

    def test_every_live_spec(self):
        self.assertEqual(len(LIVE), 7)
        for p in LIVE:
            self._compare(p)

    def test_fixtures(self):
        # foils.json and template.json declare no presubmit_after; in
        # schema 2 two independent steps always start together, so their
        # view gains {mubeam: (elebeam_flash,)}. Everything else must match.
        for p in FIXTURES:
            self._compare(p, allow_presubmit_change=True)


class TestConvertShape(unittest.TestCase):
    def test_structure(self):
        doc = json.loads((ROOT / "mode_specs" / "foilspfbpz.json").read_text())
        out = cv.convert(doc)
        self.assertEqual(out["schema"], 2)
        self.assertEqual([s["step"] for s in out["evaluate"]],
                         ["mubeam", "mustops_ce", "elebeam_flash", "sob", "flash"])
        self.assertEqual(out["constraints"],
                         [{"name": "flash_edep", "max": 6.85443e-7, "k_sigma": 1.0}])
        self.assertEqual(out["leaderboard"]["context"], ["alpha"])
        self.assertEqual(out["derive"]["profiles"]["rOut_p"]["kind"], "lagrange")

    def test_refuses_unexpected_metrics(self):
        doc = json.loads((ROOT / "mode_specs" / "foilspf.json").read_text())
        doc["leaderboard"]["metrics"]["sob"] = ["something_else"]
        with self.assertRaises(ValueError):
            cv.convert(doc)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_convert_spec_v2 -v`
Expected: `ModuleNotFoundError: No module named 'convert_spec_v2'`

- [ ] **Step 3: Write `tools/convert_spec_v2.py`**

```python
#!/usr/bin/env python3
"""ONE-TIME: convert today's mode spec JSON to a schema-2 study file.

Knows exactly one family, the foilspf/foilsflash chain (mubeam ->
mustops_ce, elebeam_flash; harvest = EdepAna sensitivity + flash), and
refuses anything else. Deleted after the switch (Task 5).

Usage: tools/convert_spec_v2.py --in-place FILE [FILE ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FLASH_BUDGET = 6.85443e-7   # was botorch_predict.flash_budget()'s default
BUDGET_K_SIGMA = 1.0        # was botorch_predict.budget_k_sigma()'s default
_EXPECTED_STAGES = ["mubeam", "mustops_ce", "elebeam_flash"]


def convert(doc: dict) -> dict:
    run, lb = doc["run"], doc["leaderboard"]
    if run["stages"] != _EXPECTED_STAGES:
        raise ValueError(f"{doc['name']}: stages {run['stages']} are not the "
                         f"foilspf chain {_EXPECTED_STAGES}")
    c0, c1 = lb["columns"][0], lb["columns"][1]
    if lb["columns"][2:] != ["alpha", "obj"]:
        raise ValueError(f"{doc['name']}: unexpected columns {lb['columns']}")
    if lb["metrics"].get(c0) != ["s_over_sqrt_b"] or \
            lb["metrics"].get(c1, [None])[0] != "flash_edep_per_pot":
        raise ValueError(f"{doc['name']}: unexpected metrics {lb['metrics']}")

    int_dims = set(doc.get("int_dims") or [])
    knobs = [{"name": k["name"], "type": "int" if i in int_dims else "real",
              "min": k["min"], "max": k["max"], "unit": "", "fmt": k["fmt"]}
             for i, k in enumerate(doc["knobs"])]
    g = doc["geom"]
    derive = {"consts": g.get("consts") or {}, "exprs": g.get("derived") or {},
              "profiles": {n: {"kind": "lagrange", **p}
                           for n, p in (g.get("profiles") or {}).items()}}
    geom = {"writer": "offline_simpleconfig", "base": g["base"],
            "lines": g["lines"]}

    presubmitted = set()
    for targets in (run.get("presubmit_after") or {}).values():
        presubmitted.update(targets)
    jobs = run.get("jobs_per_stage") or {}
    tuning = run.get("stage_tuning") or {}
    first = run["stages"][0]
    steps = []
    for stage in run["stages"]:
        fixed = {}
        if stage in jobs:
            fixed["njobs"] = jobs[stage]
        fixed.update(tuning.get(stage, {}))
        # The pipeline feeds only the first stage's outputs forward
        # (pipeline.py INPUT_STAGE); elebeam_flash resamples its own input.
        files_from = [] if stage in (first, "elebeam_flash") else [first]
        steps.append({"step": stage, "kit": "prodtools", "entry": stage,
                      "files": ["geom"], "files_from": files_from,
                      "params": {}, "fixed": fixed})
    steps += [
        {"step": "sob", "kit": "ce_sensitivity", "entry": None, "files": [],
         "files_from": ["mubeam", "mustops_ce"], "params": {}, "fixed": {}},
        {"step": "flash", "kit": "flash_edep_per_pot", "entry": None,
         "files": [], "files_from": ["elebeam_flash"], "params": {},
         "fixed": {}},
    ]
    noise = lb["obs_noise"]
    return {
        "schema": 2,
        "name": doc["name"],
        "note": doc.get("note", ""),
        "knobs": knobs,
        "derive": derive,
        "geom": geom,
        "kits": {
            "prodtools": {"code_tarball": doc["software"]["grid_tarball"]},
            "offline_preflight": {"musing": doc["software"]["musing"],
                                  **doc["preflight"]},
        },
        "preflight": {"kit": "offline_preflight", "params": {},
                      "files": ["geom"]},
        "evaluate": steps,
        "objectives": [
            {"name": c0, "metric": "sob.s_over_sqrt_b", "direction": "max",
             "transform": "none", "noise": noise[0], "fmt": "{:.5f}"},
            {"name": c1, "metric": "flash.flash_edep_per_pot",
             "direction": "min", "transform": "log10", "noise": noise[1],
             "fmt": "{:.5e}"},
        ],
        "constraints": [{"name": c1, "max": FLASH_BUDGET,
                         "k_sigma": BUDGET_K_SIGMA}],
        "extra_metrics": [],
        "extra_columns": [
            {"name": "alpha", "expr": "alpha", "fmt": "{:.3f}"},
            {"name": "obj", "expr": f"{c0} - alpha * {c1}", "fmt": "{:.5f}"},
        ],
        "leaderboard": {"file": lb["file"], "layout": "v1",
                        "context": ["alpha"]},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in-place", action="store_true", required=True)
    ap.add_argument("files", nargs="+", type=Path)
    ns = ap.parse_args(argv)
    for p in ns.files:
        doc = json.loads(p.read_text())
        if doc.get("schema") == 2:
            print(f"skip (already schema 2): {p}")
            continue
        p.write_text(json.dumps(convert(doc), indent=1) + "\n")
        print(f"converted: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Before relying on the `elebeam_flash` rule, confirm `pipeline.py` stages inputs only for `mustops_ce`:

```bash
grep -n 'INPUT_STAGE\|stage == "mustops_ce"' core/pipeline.py
```

Expected: `INPUT_STAGE = "mubeam"` and the two `if … == "mustops_ce"` input branches. No other stage consumes a previous stage's files.

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_convert_spec_v2 -v`
Expected: 4 tests PASS. `test_every_live_spec` compares 7 specs field by field and renders each geometry at 3 points.

- [ ] **Step 5: Commit**

```bash
git add tools/convert_spec_v2.py tests/test_convert_spec_v2.py
git commit -m "feat(tools): one-time v1->schema-2 spec converter, verified against the old loader"
```

---

### Task 5: Switch the registry to schema 2 and delete the old loader

**Files:**
- Modify (converted in place): `mode_specs/*.json` (7 files), `tests/fixtures/modes/foilsflash.json`, `tests/fixtures/modes/foils.json`, `tests/fixtures/modes/template.json`
- Modify: `core/modes.py` (loader import and `STUDIES`)
- Delete: `core/mode_json.py`, `tests/test_mode_json.py`, `tools/convert_spec_v2.py`, `tests/test_convert_spec_v2.py`
- Modify: `tests/test_json_mode.py`, `tests/test_json_mode_parity.py`, `tests/test_pipeline_verbs.py`, `tests/test_zero_overlap_policy.py`, and any other test the grep in Step 4 finds
- Modify: `tests/golden_parity.py` (declare the intended `metrics` change for section d)
- Modify comments: `core/paths.py:116`, `core/pipeline.py:143`, `core/geom_template.py:3`
- Rewrite: `mode_specs/README.md`

**Interfaces:**
- Consumes: `study.load_study_dirs`, `study_compat.modespec_from_study`
- Produces: `modes.STUDIES: dict[str, Study]` (new) and `modes.SPECS: dict[str, ModeSpec]` (now derived from `STUDIES`). Tasks 6–9 read `modes.STUDIES`.

- [ ] **Step 1: Convert the files**

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" tools/convert_spec_v2.py --in-place mode_specs/*.json tests/fixtures/modes/*.json
```

Expected: 10 lines of `converted: …`. `mode_specs/archive/` is not touched.

- [ ] **Step 2: Point `core/modes.py` at the new loader**

Replace this block in `core/modes.py`:

```python
if __package__:
    from core.mode_json import load_mode_dir  # noqa: E402 - SPECS must exist first
else:
    from mode_json import load_mode_dir  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
SPECS.update(load_mode_dir(MODES_DIR))
```

with:

```python
if __package__:
    from core.study import load_study_dirs  # noqa: E402 - SPECS must exist first
    from core.study_compat import modespec_from_study  # noqa: E402
else:
    from study import load_study_dirs  # noqa: E402
    from study_compat import modespec_from_study  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
# Schema-2 studies: the one source. SPECS is today's ModeSpec view of them,
# kept for pipeline.py/runtime.py/preflight until Phase C deletes both.
STUDIES = load_study_dirs(MODES_DIR, os.environ.get("AUTORESEARCH_STUDY_PATH"))
SPECS.update({n: modespec_from_study(s) for n, s in STUDIES.items()})
```

`os` is already imported in `core/modes.py`.

- [ ] **Step 3: Delete the old loader and the converter**

```bash
git rm core/mode_json.py tests/test_mode_json.py tools/convert_spec_v2.py tests/test_convert_spec_v2.py
```

`tests/test_study.py` replaces `tests/test_mode_json.py`. Every rule the old tests pinned has a schema-2 counterpart there: required keys, unknown keys, duplicate JSON keys, knob bounds, reserved names, stage-name typos (now step and `files_from` checks), leaderboard `..`, and shared leaderboards.

- [ ] **Step 4: Update the tests that used the old loader or old field paths**

Exact import replacements:

| File | Old | New |
|---|---|---|
| `tests/test_json_mode_parity.py:25` | `from mode_json import load_mode_file  # noqa: E402` | `from study_compat import load_modespec as load_mode_file  # noqa: E402` |
| `tests/test_json_mode.py:28` | `from mode_json import load_mode_file  # noqa: E402` | `from study_compat import load_modespec as load_mode_file  # noqa: E402` |
| `tests/test_pipeline_verbs.py:165` | `from mode_json import load_mode_file  # noqa: E402 (bare, core/ on sys.path)` | `from study_compat import load_modespec as load_mode_file  # noqa: E402 (bare, core/ on sys.path)` |
| `tests/test_pipeline_verbs.py:211` | `"from mode_json import load_mode_file\n"` | `"from study_compat import load_modespec as load_mode_file\n"` |

In `tests/test_zero_overlap_policy.py`, replace the body of `test_loader_rejects_a_spec_missing_the_flag`:

```python
        import kit_registry
        self.assertIn("require_zero_overlaps",
                      kit_registry.KITS["offline_preflight"].study_keys)
```

Then find every test that edits a fixture document by old field paths:

```bash
grep -rn '\["software"\]\|\["run"\]\|\["int_dims"\]\|\["columns"\]\|\["obs_noise"\]\|\["metrics"\]\|\["preflight"\]\[\|\["geom"\]\["consts"\]\|\["geom"\]\["derived"\]\|\["geom"\]\["profiles"\]' tests/*.py
```

Rewrite each hit with this table. `_step(doc, S)` means `next(s for s in doc["evaluate"] if s["step"] == S)`; define it locally in the file if needed.

| Old path | Schema-2 path |
|---|---|
| `doc["software"]["musing"]` | `doc["kits"]["offline_preflight"]["musing"]` |
| `doc["software"]["grid_tarball"]` | `doc["kits"]["prodtools"]["code_tarball"]` |
| `doc["run"]["jobs_per_stage"][S]` | `_step(doc, S)["fixed"]["njobs"]` |
| `doc["run"]["stage_tuning"][S][k]` | `_step(doc, S)["fixed"][k]` |
| `doc["preflight"][k]` | `doc["kits"]["offline_preflight"][k]` |
| `doc["int_dims"] = [i]` | `doc["knobs"][i]["type"] = "int"` |
| `doc["leaderboard"]["obs_noise"][i]` | `doc["objectives"][i]["noise"]` |
| `doc["geom"]["consts"]` | `doc["derive"]["consts"]` |
| `doc["geom"]["derived"]` | `doc["derive"]["exprs"]` |
| `doc["geom"]["profiles"][n]` | `doc["derive"]["profiles"][n]` (keep `"kind": "lagrange"`) |

A test that asserts an old-schema-only validation error (for example "columns must have exactly 4 entries") is testing a rule that no longer exists. Delete that test, and name the replacing `tests/test_study.py` test in the commit message.

- [ ] **Step 5: Update the three code comments that name `mode_json`**

- `core/paths.py:116`: change "why core/mode_json.py enforces basename" to "why core/study.py enforces basename".
- `core/pipeline.py:143`: change "mode_json's _validate_stage_tuning rejects" to "core/kit_registry.py's validate_fixed rejects".
- `core/geom_template.py:3`: change "Used by JSON-defined modes (core/mode_json.py)." to "Used by schema-2 studies (core/study.py)."

- [ ] **Step 6: Rewrite `mode_specs/README.md`**

```markdown
# Studies (schema 2)

One file per study: `mode_specs/<name>.json`, where `<name>` equals the
`"name"` field. Every file here, plus every `*.json` in the directories on
`$AUTORESEARCH_STUDY_PATH` (colon-separated), is loaded at import by
`core/study.py`. `archive/` holds retired specs in the old format and is
not loaded.

The format, field rules and examples are in
`docs/superpowers/specs/2026-09-23-generic-study-design.md`
("The study file (schema 2)").

## Starting a new study

Copy `tests/fixtures/modes/template.json` (it points at a non-live
leaderboard) and change:

1. `"name"`: must equal the file stem.
2. `"leaderboard": {"file": ...}`: a path no other study uses.
3. the knobs, `derive` and `geom`.

Every key is required and unknown keys are rejected, so a typo fails at
import, never hours into a campaign.
```

- [ ] **Step 7: Declare the intended section-d change in `tests/golden_parity.py`**

In `main()`'s d/e loop, directly after `base = json.loads(base_path.read_text())`, add:

```python
        if key == "d":
            # Intended Phase-A change (spec, "Changed on purpose"): the flash
            # objective no longer falls back to flash_edep_per_event.
            for rec in base.values():
                flash = rec["metrics"].get(rec["metric_cols"][1])
                if flash and flash[1:] == ["flash_edep_per_event"]:
                    rec["metrics"][rec["metric_cols"][1]] = flash[:1]
```

- [ ] **Step 8: Run the golden gates**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: all four `OK`.

If `d` mismatches, the printed field and mode show exactly which conversion rule is wrong. Fix `study_compat.py` or the converted file; never the baseline.

- [ ] **Step 9: Run the full suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 10: Commit**

```bash
git add -A mode_specs/ tests/ core/modes.py core/paths.py core/pipeline.py core/geom_template.py
git commit -m "feat(study): schema-2 files are the only spec format; old loader deleted

The 7 live specs and 3 fixtures are converted in place; modes.SPECS is now a
view built from modes.STUDIES. Golden d/a/b/e unchanged except the intended
removal of the flash_edep_per_event fallback."
```

---

### Task 6: Generic leaderboard rows

**Files:**
- Modify: `core/leaderboard.py` (`Point`, `Leaderboard`)
- Modify: `core/bo_driver.py` (`JsonMode.leaderboard_io`, `append_history`, `cmd_evaluate`'s `Point` construction and append)
- Modify: `core/botorch_predict.py:54-64`, `surrogate/adapter.py:35-43`, `tests/golden_parity.py` (`_roundtrip_file`): read `p.y[...]` instead of `.sob`/`.calo`
- Test: `tests/test_leaderboard.py` (rewrite the affected tests), plus every test found by the grep in Step 5

**Interfaces:**
- Consumes: `modes.STUDIES`, `study.Study` (`knob_names`, `knob_fmts`, `objectives`, `extra_metrics`, `extra_columns`, `context`, `consts`)
- Produces:
  - `leaderboard.Point(cfg: str, x: list, y: dict[str, float])`
  - `leaderboard.Leaderboard.for_study(study, *, path, archive_path) -> Leaderboard`
  - `Leaderboard.append(p: Point, context: dict) -> None`
  - `Leaderboard.load() -> list[Point]`
  - `Leaderboard.header() -> str`
  - `JsonMode.append_history(p, context: dict)`

- [ ] **Step 1: Write the failing tests** (add to `tests/test_leaderboard.py`; keep the existing pending-file tests)

```python
import shutil
import tempfile
from pathlib import Path

import leaderboard as lbm  # core/ is already on sys.path in this file
import study as st

_DEMO = Path(__file__).parent / "fixtures" / "studies" / "demo.json"


class TestGenericRows(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(_DEMO)
        self.lb = lbm.Leaderboard.for_study(
            self.study, path=self.tmp / "board.tsv", archive_path=None)

    def tearDown(self):
        self._td.cleanup()

    def test_header_from_study(self):
        self.assertEqual(self.lb.header(),
                         "config\ta\tb\tsob\tflash_edep\talpha\tobj\n")

    def test_append_formats_like_today(self):
        p = lbm.Point(cfg="c1", x=[2.0, 0.5], y={"sob": 3.88, "flash_edep": 5.95893e-07})
        self.lb.append(p, {"alpha": 1.0e5})
        line = (self.tmp / "board.tsv").read_text().splitlines()[1]
        self.assertEqual(line, "c1\t2.0000\t0.5000\t3.88000\t5.95893e-07"
                               "\t100000.000\t3.82041")

    def test_missing_context_is_an_error(self):
        p = lbm.Point(cfg="c1", x=[2.0, 0.5], y={"sob": 1.0, "flash_edep": 1e-6})
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(p, {})

    def test_load_round_trip(self):
        self.lb.append(lbm.Point("c1", [2.0, 0.5], {"sob": 3.0, "flash_edep": 1e-6}),
                       {"alpha": 1e5})
        [p] = self.lb.load()
        self.assertEqual(p.cfg, "c1")
        self.assertEqual(p.y, {"sob": 3.0, "flash_edep": 1e-6})

    def test_headerless_board_refused(self):
        (self.tmp / "board.tsv").write_text("c1\t2\t0.5\t3\t1e-6\t1e5\t2.9\n")
        with self.assertRaises(lbm.SchemaMismatch):
            self.lb.load()


class TestByteIdenticalOnARealBoard(unittest.TestCase):
    """Appending to a copy of a real board adds exactly the line today's
    writer would have produced."""

    def test_foilspfbpz_last_row_rewritten_identically(self):
        import modes
        root = Path(__file__).resolve().parent.parent
        src = root / "leaderboards" / "leaderboard_bo_foilspfbpz.tsv"
        study = modes.STUDIES["foilspfbpz"]
        with tempfile.TemporaryDirectory() as td:
            lines = src.read_text().splitlines(keepends=True)
            head, last = lines[:-1], lines[-1]
            copy = Path(td) / src.name
            copy.write_text("".join(head))
            lb = lbm.Leaderboard.for_study(study, path=copy, archive_path=None)
            cells = last.rstrip("\n").split("\t")
            n = len(study.knob_names)
            p = lbm.Point(cfg=cells[0], x=[float(v) for v in cells[1:1 + n]],
                          y={"sob": float(cells[1 + n]),
                             "flash_edep": float(cells[2 + n])})
            lb.append(p, {"alpha": float(cells[3 + n])})
            self.assertEqual(copy.read_text().splitlines(keepends=True)[-1], last)
```

The last test rebuilds a row from disk-rounded values, as golden section (a) does. The `obj` value is recomputed from rounded `sob` and `flash_edep`. If it differs from the file in the last decimal for the chosen row, pick a row with no such difference. Golden (a) records which rows those are, in `mismatch_idx`.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_leaderboard -v`
Expected: `AttributeError: type object 'Leaderboard' has no attribute 'for_study'`

- [ ] **Step 3: Rewrite `Point` and `Leaderboard` in `core/leaderboard.py`**

Replace the `Point` class with:

```python
@dataclass
class Point:
    """One evaluated config: knob vector x plus named values y (the study's
    objectives and extra metrics, keyed by name)."""
    cfg: str
    x: list
    y: dict
```

Replace the `Leaderboard` class's fields, `__post_init__`, `from_spec`, `header`, `_load_one`, `_format_line` and `append` with the version below. `quarantine_path`, `_append_quarantine`, `load` and every pending method stay exactly as they are.

```python
@dataclass(frozen=True)
class Leaderboard:
    path: Path
    name: str
    knob_names: tuple
    knob_fmts: tuple
    value_names: tuple      # objectives then extra metrics (read back)
    value_fmts: tuple
    extra_columns: tuple    # objects with .name/.fmt/.evaluate(env); never read back
    context_names: tuple    # runtime values append() must receive
    consts: dict            # visible to extra-column expressions
    archive_path: Path | None = None   # committed read-only priors

    def __post_init__(self):
        if len(self.knob_names) != len(self.knob_fmts):
            raise ValueError(
                f"{self.name}: knob_names/knob_fmts length mismatch "
                f"({len(self.knob_names)} vs {len(self.knob_fmts)})")
        if len(self.value_names) != len(self.value_fmts):
            raise ValueError(
                f"{self.name}: value_names/value_fmts length mismatch")

    @classmethod
    def for_study(cls, study, *, path: Path,
                  archive_path: Path | None) -> "Leaderboard":
        values = tuple(study.objectives) + tuple(study.extra_metrics)
        return cls(path=path, name=study.name,
                   knob_names=tuple(study.knob_names),
                   knob_fmts=tuple(study.knob_fmts),
                   value_names=tuple(v.name for v in values),
                   value_fmts=tuple(v.fmt for v in values),
                   extra_columns=tuple(study.extra_columns),
                   context_names=tuple(study.context),
                   consts=dict(study.consts),
                   archive_path=archive_path)

    # --- history -----------------------------------------------------------
    def header(self) -> str:
        cols = ("config", *self.knob_names, *self.value_names,
                *(c.name for c in self.extra_columns))
        return "\t".join(cols) + "\n"

    def _load_one(self, path: Path, *, lock: bool = True) -> list[Point]:
        """lock=False for the committed archive: _lock_path CREATES the lock
        file, so even a SHARED lock needs WRITE access to the repo."""
        if not path.exists():
            return []
        out = []
        with (_flock_sh(path) if lock else nullcontext()), path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = self.header().rstrip("\n").split("\t")
            reader = csv.DictReader(f, fieldnames=cols, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                try:
                    out.append(Point(
                        cfg=row["config"],
                        x=[float(row[c]) for c in self.knob_names],
                        y={v: float(row[v]) for v in self.value_names}))
                except (KeyError, ValueError, TypeError) as e:
                    raise RowParseError(path, line_no, e) from e
        return out

    def _format_line(self, p: Point, context: dict) -> str:
        missing = [c for c in self.context_names if c not in context]
        if missing:
            raise LeaderboardError(
                f"{self.name}: row {p.cfg!r} needs runtime value(s) {missing} "
                f"(leaderboard.context) and the caller did not pass them")
        knobs = [fmt.format(v) for fmt, v in zip(self.knob_fmts, p.x)]
        values = [fmt.format(p.y[n])
                  for fmt, n in zip(self.value_fmts, self.value_names)]
        env = {**self.consts, **p.y, **context}
        extras = [c.fmt.format(c.evaluate(env)) for c in self.extra_columns]
        return "\t".join([p.cfg, *knobs, *values, *extras]) + "\n"

    def append(self, p: Point, context: dict) -> None:
        line = self._format_line(p, context)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _flock_ex(self.path):
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return
            with self.path.open() as f:
                first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                self._append_quarantine(self.header(), line)
                raise SchemaMismatch(self.path, self.header(), first,
                                     quarantined=self.quarantine_path())
            with self.path.open("a") as f:
                f.write(line)
```

Update the module docstring's first line to: `"""Leaderboard: the schema-owning module for per-study history + pending TSVs.`

Then run `grep -n "from_spec" -r core graph surrogate tests tools`. Replace each caller with `Leaderboard.for_study(modes.STUDIES[name], path=live_root / Path(rel).name, archive_path=archive_root / rel)`, using the same two paths the caller passed before.

- [ ] **Step 4: Wire `core/bo_driver.py`**

In `JsonMode.leaderboard_io`, replace the `Leaderboard(...)` construction with:

```python
            lb = Leaderboard.for_study(_modes.STUDIES[self.name],
                                       path=self.leaderboard,
                                       archive_path=archive)
```

Replace `append_history`:

```python
    def append_history(self, p: Point, context: dict):
        self.leaderboard_io().append(p, context)
```

In `cmd_evaluate`, replace the three statements that build `p`, append it and emit JSON with:

```python
    study = _modes.STUDIES[mode.name]
    p = Point(cfg=args.config_name, x=x,
              y={study.objectives[0].name: float(sob),
                 study.objectives[1].name: float(calo)})
    # Clear pending BEFORE appending: a crash in between leaves "missing
    # leaderboard row" (loud, re-runnable) rather than a silent phantom
    # pending row that trips propose_one's collision guard.
    removed = mode.remove_pending(args.config_name)
    mode.append_history(p, {"alpha": args.alpha})
    obj = float(sob) - args.alpha * float(calo)   # removed in Task 8
    if getattr(args, "emit_json", None):
        write_json_atomic(Path(args.emit_json), {
            "config": p.cfg,
            "obj": obj,
            "sob": float(sob),
            "calo_or_flash": float(calo),
            "row_appended": True,
        })
    pend_tag = "  (cleared from pending)" if removed else ""
    print(f"[{mode.name}] recorded {p.cfg}: sob={float(sob):.3f} "
          f"calo={float(calo):.3e} obj={obj:+.3f}  →  {mode.leaderboard}{pend_tag}")
    return 0
```

- [ ] **Step 5: Mechanical `Point` updates outside the driver**

- `core/botorch_predict.py` `load_history_tensor`: change `p.sob` to `p.y[spec.metric_cols[0]]` and `p.calo` to `p.y[spec.metric_cols[1]]`. Task 7 rewrites this function; this step only keeps it running.
- `surrogate/adapter.py` `_board_summary`: change `p.sob` to `p.y["sob"]`, and `best.calo` to `best.y[spec.metric_cols[1]]`. Task 9 rewrites this function.
- `tests/golden_parity.py` `_roundtrip_file`: build `bo.Point(cfg=row["config"], x=[float(row[c]) for c in lb.knob_names], y={v: float(row[v]) for v in lb.value_names})`. Replace the call `lb._format_line(p, alpha)` with `lb._format_line(p, {"alpha": alpha})`, keeping whatever variable it already reads `alpha` from.

Then find the remaining test uses:

```bash
grep -rn "sob=\|calo=\|\.calo\b\|metric_cols=\|append_history(\|\.append(p, \|_format_line(" tests/*.py
```

Convert each with this mapping:

| Old | New |
|---|---|
| `Point(cfg=c, x=x, sob=s, calo=f)` | `Point(cfg=c, x=x, y={"sob": s, "flash_edep": f})`. Use the study's second objective name when the test's mode names it differently. |
| `p.sob` / `p.calo` | `p.y["sob"]` / `p.y["flash_edep"]` |
| `Leaderboard(path=…, name=…, knob_names=…, knob_fmts=…, metric_cols=…)` | `Leaderboard.for_study(study, path=…, archive_path=None)`, with `study` from `modes.STUDIES[...]` or `st.load_study_file(...)` |
| `append_history(p, alpha)` / `lb.append(p, alpha)` | `append_history(p, {"alpha": alpha})` / `lb.append(p, {"alpha": alpha})` |

Delete `tests/test_modes.py::test_leaderboard_io_rejects_non4_metric_tail`, because a study's columns are no longer a fixed four. Its replacement is `tests/test_study.py::TestKnobs::test_knob_name_collides_with_column` together with `TestGenericRows`.

- [ ] **Step 6: Run the leaderboard tests, the suite and the goldens**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_leaderboard -v` and expect PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` and expect OK.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e` and expect all `OK`.

- [ ] **Step 7: Commit**

```bash
git add core/leaderboard.py core/bo_driver.py core/botorch_predict.py surrogate/adapter.py tests/
git commit -m "feat(leaderboard): rows are named values from the study; columns and formats from the spec"
```

---

### Task 7: Generic surrogate glue (history and problem from the study)

**Files:**
- Modify: `core/botorch_predict.py` (`load_history_tensor`, `build_problem`, `compute_explore_picks`; delete `flash_budget` and `budget_k_sigma`)
- Modify: `surrogate/adapter.py` (`problems()` and `history()` call the renamed parameter)
- Modify: `tests/golden_parity.py` (no code change; it calls `load_history_tensor("foilsflash")` positionally)
- Test: `tests/test_botorch_predict.py` (new tests; update any use of `sob_only=`)

**Interfaces:**
- Consumes: `modes.STUDIES`, `Study.objectives`, `Study.constraints`, `Point.y`
- Produces:
  - `botorch_predict.axis_value(obj, v) -> float | None`: a raw metric value becomes a maximized axis value, or None when undefined.
  - `load_history_tensor(mode: str, primary_only: bool = False)` (renamed from `sob_only`).
  - `build_problem(mode: str, primary_only: bool = False) -> surrokit.Problem`.

- [ ] **Step 1: Write the failing tests** (add to `tests/test_botorch_predict.py`)

```python
import math
import types

import botorch_predict as bp
import study as st


def _obj(direction, transform):
    return st.Objective("m", "s.m", direction, transform, 0.1, "{:.3f}")


class TestAxisValue(unittest.TestCase):
    def test_max_none(self):
        self.assertEqual(bp.axis_value(_obj("max", "none"), 3.0), 3.0)

    def test_min_none(self):
        self.assertEqual(bp.axis_value(_obj("min", "none"), 3.0), -3.0)

    def test_min_log10(self):
        self.assertAlmostEqual(bp.axis_value(_obj("min", "log10"), 1e-6), 6.0)

    def test_max_log10(self):
        self.assertAlmostEqual(bp.axis_value(_obj("max", "log10"), 100.0), 2.0)

    def test_undefined(self):
        self.assertIsNone(bp.axis_value(_obj("min", "log10"), 0.0))
        self.assertIsNone(bp.axis_value(_obj("max", "none"), float("nan")))
        self.assertIsNone(bp.axis_value(_obj("max", "none"), None))


class TestThreeObjectiveProblem(unittest.TestCase):
    """A synthetic 3-objective study builds a 3-axis Problem, fits, and
    picks (spec Phase A acceptance)."""

    def test_three_axes(self):
        objs = (st.Objective("y1", "s.a", "max", "none", 0.01, "{:.4f}"),
                st.Objective("y2", "s.b", "min", "log10", 0.02, "{:.4e}"),
                st.Objective("y3", "s.c", "min", "none", 0.03, "{:.4f}"))
        fake = types.SimpleNamespace(
            objectives=objs,
            constraints=(st.StudyConstraint("y2", "max", 1e-3, 1.0),),
            bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 1.0), int_dims=())
        prob = bp._problem_from(fake, primary_only=False)
        self.assertEqual(prob.noise, (0.01, 0.02, 0.03))
        self.assertEqual(prob.constraint.axis, 1)
        self.assertAlmostEqual(prob.constraint.min, 3.0)
        X = [[0.1 * i, 0.05 * i] for i in range(8)]
        Y = [[x0, -math.log10(1e-4 + x1), -x0 * x1] for x0, x1 in X]
        picks = bp.surrokit.ask(prob, X, Y, q=2, picker="qnehvi", seed=42)
        self.assertEqual(len(picks), 2)

    def test_primary_only_drops_other_axes_and_their_constraint(self):
        objs = (st.Objective("y1", "s.a", "max", "none", 0.01, "{:.4f}"),
                st.Objective("y2", "s.b", "min", "log10", 0.02, "{:.4e}"))
        fake = types.SimpleNamespace(
            objectives=objs,
            constraints=(st.StudyConstraint("y2", "max", 1e-3, 1.0),),
            bounds_lo=(0.0,), bounds_hi=(1.0,), int_dims=())
        prob = bp._problem_from(fake, primary_only=True)
        self.assertEqual(prob.noise, (0.01,))
        self.assertIsNone(prob.constraint)
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_botorch_predict -v`
Expected: `AttributeError: module 'botorch_predict' has no attribute 'axis_value'`

- [ ] **Step 3: Rewrite the glue in `core/botorch_predict.py`**

Replace `load_history_tensor`, `flash_budget`, `budget_k_sigma` and `build_problem` (everything from `def load_history_tensor` down to just before `def compute_explore_picks`, keeping `_seed` in place) with:

```python
def axis_value(obj, v):
    """Raw metric -> the maximized surrogate axis (surrokit's math space),
    or None when it is undefined (missing, non-finite, or <= 0 under log10).
    """
    if v is None or not math.isfinite(v):
        return None
    if obj.transform == "log10":
        if v <= 0:
            return None
        v = math.log10(v)
    return v if obj.direction == "max" else -v


def _objectives(study, primary_only):
    return study.objectives[:1] if primary_only else study.objectives


def load_history_tensor(mode: str, primary_only: bool = False):
    """(X, Y, bounds, int_dims) over the study's search space. Y has one
    maximized column per objective (primary_only: the first objective only);
    a row with any undefined axis value is left out."""
    if mode not in _modes.STUDIES:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(_modes.STUDIES)}.")
    study = _modes.STUDIES[mode]
    objs = _objectives(study, primary_only)
    X_rows, Y_rows = [], []
    for p in bo.MODES[mode].load_history():
        ys = [axis_value(o, p.y.get(o.name)) for o in objs]
        if any(y is None for y in ys):
            continue
        X_rows.append([float(v) for v in p.x])
        Y_rows.append(ys)
    lo = torch.tensor(list(study.bounds_lo), device=DEVICE)
    hi = torch.tensor(list(study.bounds_hi), device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)
    d = len(study.bounds_lo)
    if X_rows:
        X = torch.tensor(X_rows, device=DEVICE)
        Y = torch.tensor(Y_rows, device=DEVICE)
        if X.shape[1] != d:
            raise SystemExit(
                f"[botorch_predict] mode={mode} dim mismatch: history has "
                f"{X.shape[1]}D points but the study declares {d} knobs "
                f"({study.knob_names}).")
    else:
        X = torch.empty((0, d), device=DEVICE)
        Y = torch.empty((0, len(objs)), device=DEVICE)
    return X, Y, bounds, list(study.int_dims)


def _problem_from(study, primary_only: bool) -> "surrokit.Problem":
    objs = _objectives(study, primary_only)
    constraint = None
    for c in study.constraints:
        axes = [i for i, o in enumerate(objs) if o.name == c.name]
        if not axes:
            continue    # constrained objective not in this problem
        i = axes[0]
        # The loader fixed the bound's side so the transformed bound is a
        # LOWER bound on the maximized axis (surrokit: mean - k*sigma >= min).
        constraint = surrokit.Constraint(
            axis=i, min=axis_value(objs[i], c.value), k_sigma=c.k_sigma)
    return surrokit.Problem(
        bounds_lo=tuple(study.bounds_lo), bounds_hi=tuple(study.bounds_hi),
        int_dims=tuple(study.int_dims),
        noise=tuple(o.noise for o in objs), constraint=constraint)


def build_problem(mode: str, primary_only: bool = False) -> "surrokit.Problem":
    """The single home for surrokit.Problem assembly over a study."""
    return _problem_from(_modes.STUDIES[mode], primary_only)
```

In `compute_explore_picks`, replace the lines from `sob_only = (picker == "qlnei")` through the end of the `except surrokit.InfeasibleError` block with:

```python
    primary_only = (picker == "qlnei")
    X, Y, bounds, int_dims = load_history_tensor(mode, primary_only=primary_only)
    if x_pending:
        pend_width = len(x_pending[0])
        if pend_width != bounds.shape[-1]:
            raise SystemExit(
                f"[botorch_predict] x_pending dim {pend_width} != "
                f"search-space dim {bounds.shape[-1]} for mode={mode}")
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
    study = _modes.STUDIES[mode]
    if picker == "budget_sob" and not study.constraints:
        raise SystemExit(f"[botorch_predict] picker budget_sob needs a "
                         f"constraint, and study {mode!r} declares none")
    sk_picker = "constrained_max" if picker == "budget_sob" else picker
    problem = build_problem(mode, primary_only=primary_only)
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    try:
        picks = surrokit.ask(problem, X.tolist(), Y.tolist(), q=q,
                             picker=sk_picker, seed=_seed(round_idx),
                             pending=x_pending, hv_frac=hv_frac)
    except surrokit.InfeasibleError as e:
        c = study.constraints[0]
        op = "<=" if c.bound == "max" else ">="
        raise SystemExit(
            f"[botorch_predict] budget_sob: GP predicts NO point in the "
            f"search box with {c.name} {op} {c.value:.3e} ({e}); refusing "
            f"to submit blind picks.")
    return [tuple(row) for row in picks]
```

Update the module docstring's first line to `"""BoTorch pickers for any study (objectives, transforms and the constraint from modes.STUDIES).`

- [ ] **Step 4: Update the callers of the renamed parameter**

```bash
grep -rn "sob_only" core graph surrogate tests tools
```

Rename every hit to `primary_only`. `surrogate/adapter.py` `problems()` is unchanged, because it calls `bp.build_problem(name)` with no flag.

- [ ] **Step 5: Run the tests and the golden gates**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_botorch_predict -v` and expect PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check b e` and expect `[b] … OK` and `[e] parity: OK`.

If `e` mismatches, compare the printed `problem` repr with the baseline. The constraint must be `Constraint(axis=1, min=6.164…, k_sigma=1.0)`, the noise `(0.006, 0.01)`, and `n_rows` must be unchanged.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK. Tests that set `AUTORESEARCH_FLASH_BUDGET` or `AUTORESEARCH_BUDGET_KSIGMA` now fail, because those overrides are gone. Rewrite each to change the study's constraint instead: copy `demo.json` into a temp dir, edit `constraints[0].max` or `k_sigma`, and load it with `st.load_study_file`. Delete tests whose only purpose was the environment override.

- [ ] **Step 7: Commit**

```bash
git add core/botorch_predict.py surrogate/adapter.py tests/
git commit -m "feat(surrogate-glue): N objectives, transforms and the constraint come from the study

AUTORESEARCH_FLASH_BUDGET / AUTORESEARCH_BUDGET_KSIGMA removed: the study file
is the only source of the constraint. Golden b and e unchanged."
```

---

### Task 8: Generic evaluate

**Files:**
- Modify: `core/bo_driver.py` (`JsonMode.extract_metrics`, `_resolve_metric` deleted, `cmd_evaluate`)
- Modify: `graph/pipeline_io.py:331` (read `"primary"`)
- Test: `tests/test_json_mode.py` (evaluate tests) or a new `tests/test_evaluate_generic.py`

**Interfaces:**
- Consumes: `modes.STUDIES`, `Objective.key`, `ExtraMetric.key`
- Produces:
  - `JsonMode.extract_metrics(summary: dict) -> dict[str, float | None]`, keyed by objective and extra-metric names.
  - `evaluate_result.json` = `{"config": str, "primary": float, "objectives": {name: float}, "row_appended": true}`. `graph/pipeline_io.run_evaluate` returns `primary`.

- [ ] **Step 1: Write the failing tests `tests/test_evaluate_generic.py`**

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import bo_driver as bo  # noqa: E402


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.mode = bo.MODES["foilspfbpz"]

    def test_values_by_name(self):
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 6e-7})
        self.assertEqual(out, {"sob": 3.9, "flash_edep": 6e-7})

    def test_no_per_event_fallback(self):
        out = self.mode.extract_metrics(
            {"s_over_sqrt_b": 3.9, "flash_edep_per_event": 0.2})
        self.assertIsNone(out["flash_edep"])


class TestEvaluateRefusals(unittest.TestCase):
    """cmd_evaluate never appends a row with a missing objective or a
    non-positive log10 objective."""

    def _run(self, summary):
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "summary.json"
            sp.write_text(json.dumps(summary))
            args = SimpleNamespace(mode="foilspfbpz", alpha=1e5,
                                   config_name="nosuchcfg", summary=str(sp),
                                   emit_json=None)
            try:
                return bo.cmd_evaluate(args)
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 1

    def test_missing_objective(self):
        self.assertEqual(self._run({"s_over_sqrt_b": 3.9}), 1)

    def test_zero_log10_objective(self):
        self.assertEqual(
            self._run({"s_over_sqrt_b": 3.9, "flash_edep_per_pot": 0.0}), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_evaluate_generic -v`
Expected: FAIL. `extract_metrics` still returns a `(sob, second)` tuple.

- [ ] **Step 3: Rewrite `extract_metrics` and `cmd_evaluate` in `core/bo_driver.py`**

Delete `_resolve_metric`, and replace `extract_metrics` with:

```python
    def extract_metrics(self, summary: dict) -> dict:
        """summary.json -> {objective/extra-metric name: value or None}.

        Phase A: summary.json is still one flat harvest file, so a metric
        'step.key' resolves by its key. No fallback between keys: two keys
        are two different quantities (per-POT vs per-event flash differ by
        units)."""
        study = _modes.STUDIES[self.name]
        out = {}
        for item in (*study.objectives, *study.extra_metrics):
            v = summary.get(item.key)
            out[item.name] = None if v is None else float(v)
        return out
```

Replace `cmd_evaluate` from its first line down to the `return 0` with:

```python
def cmd_evaluate(args):
    mode = MODES[args.mode]
    study = _modes.STUDIES[mode.name]
    summary = json.loads(Path(args.summary).read_text())
    values = mode.extract_metrics(summary)
    # A missing value is NEVER coerced to a number: a fake zero row dominates
    # the whole Pareto front at the next GP refit
    # (wiki/incidents/no-run1b-substitution-poisons-flash-modes.md).
    missing = [n for n, v in values.items() if v is None]
    if missing:
        print(f"[{mode.name}] summary.json has no value for {missing} "
              f"({[i.metric for i in (*study.objectives, *study.extra_metrics) if i.name in missing]}) "
              f"— refusing to append a row; recover the failed stage first.")
        return 1
    for o in study.objectives:
        if o.transform == "log10" and values[o.name] <= 0:
            raise SystemExit(
                f"[{mode.name}] objective {o.name!r} resolved to "
                f"{values[o.name]!r} from summary.json key {o.key!r} -- "
                f"refusing to append a row; a zero/negative log10 objective "
                f"would dominate the Pareto front at the next GP refit")
    geom = mode.proposal_dir / f"{args.config_name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 1
    x = mode.x_for_evaluate(args.config_name)
    p = Point(cfg=args.config_name, x=x, y=values)
    # Clear pending BEFORE appending: a crash in between leaves "missing
    # leaderboard row" (loud, re-runnable) rather than a silent phantom
    # pending row that trips propose_one's collision guard.
    removed = mode.remove_pending(args.config_name)
    mode.append_history(p, {"alpha": args.alpha})
    primary = study.objectives[0].name
    if getattr(args, "emit_json", None):
        write_json_atomic(Path(args.emit_json), {
            "config": p.cfg,
            "primary": values[primary],
            "objectives": {o.name: values[o.name] for o in study.objectives},
            "row_appended": True,
        })
    pend_tag = "  (cleared from pending)" if removed else ""
    shown = ", ".join(f"{o.name}={values[o.name]:.4g}" for o in study.objectives)
    print(f"[{mode.name}] recorded {p.cfg}: {shown}  →  "
          f"{mode.leaderboard}{pend_tag}")
    return 0
```

- [ ] **Step 4: Make the graph read the primary objective**

In `graph/pipeline_io.py` `run_evaluate`, change:

```python
        return float(json.loads(result_path.read_text())["obj"]), tail
```

to:

```python
        return float(json.loads(result_path.read_text())["primary"]), tail
```

and change its docstring's second line to `objective (the study's primary objective) from the typed result JSON.` The graph state's `objective` field is logged only. `graph/pool.py` resolves children by landed rows, never by this number.

- [ ] **Step 5: Update the tests that read the old result keys**

```bash
grep -rn '"obj"\]\|"calo_or_flash"\|\["sob"\]' tests/*.py graph core
```

Change readers of `evaluate_result.json` to the keys `primary` and `objectives`. Leaderboard column assertions that use `"obj"` as a board column stay as they are.

- [ ] **Step 6: Run the tests, the suite and the goldens**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_evaluate_generic -v` and expect PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` and expect OK.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e` and expect all `OK`.

- [ ] **Step 7: Commit**

```bash
git add core/bo_driver.py graph/pipeline_io.py tests/
git commit -m "feat(evaluate): values by objective name from the study; no per-event fallback

evaluate_result.json carries primary + objectives; the graph logs the
primary objective."
```

---

### Task 9: MCP stats meta, the generic-core gate, and docs

**Files:**
- Modify: `surrogate/adapter.py` (`_board_summary`, `history`)
- Modify: `surrogate/mcp_server.py` (the `instructions` string)
- Create: `tests/test_generic_core.py`
- Modify: `tests/test_surrogate.py` (meta keys)
- Modify: `wiki/drivers/surrogate.md`, `wiki/drivers/bo-driver.md`, `wiki/concepts/budget-sob-picker.md`, `wiki/log.md`

**Interfaces:**
- Consumes: `modes.STUDIES`, `Point.y`
- Produces: `stats` meta = `{"objectives": [...], "knobs": [...], "knob_names": [...], "leaderboard": str, "best": {...}, "primary_range": [lo, hi]}`

- [ ] **Step 1: Write the failing tests `tests/test_generic_core.py`**

```python
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that are generic end to end: no physics names at all.
STRICT = ["core/study.py", "core/leaderboard.py", "core/study_compat.py"]
# Files that still host Mu2e code paths (preflight, picker names like
# budget_sob) but must not read objectives by physics name.
USAGE = ["core/botorch_predict.py", "core/bo_driver.py",
         "surrogate/adapter.py", "graph/pipeline_io.py",
         "core/kit_registry.py"]
USAGE_RX = re.compile(r"\.sob\b|\.calo\b|\bmetric_cols\b|flash_budget|"
                      r"budget_k_sigma|calo_or_flash|\bsob_only\b")


class TestGenericCore(unittest.TestCase):
    def test_strict_files_name_no_physics(self):
        rx = re.compile(r"\bsob\b|\bcalo\b|flash", re.IGNORECASE)
        for rel in STRICT:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if rx.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])

    def test_usage_files_read_objectives_by_study_name(self):
        for rel in USAGE:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if USAGE_RX.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
```

`core/study_compat.py` builds `metric_cols` and names the harvest plugins, so it will fail the strict check. Move `core/study_compat.py` from `STRICT` to a third list, `EXEMPT_UNTIL_PHASE_C = ["core/study_compat.py"]`, that the test does not scan. The comment above it should say it is deleted in Phase C. `core/modes.py` keeps the `ModeSpec` fields until Phase C and is not scanned either.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_generic_core -v`
Expected: FAIL. The usage hits are in `surrogate/adapter.py` (`metric_cols`, `p.y["sob"]`) and in any leftover strings.

- [ ] **Step 3: Make `surrogate/adapter.py` generic**

Replace `_board_summary` and `history` with:

```python
def _board_summary(name: str) -> dict:
    """Champion by the primary objective (direction-aware) and its observed
    range, for the MCP `stats` tool (the scaffold's stats is n_rows + meta)."""
    study = _modes.STUDIES[name]
    prim = study.objectives[0]
    pts = [p for p in bo.MODES[name].load_history()
           if p.y.get(prim.name) is not None and math.isfinite(p.y[prim.name])]
    if not pts:
        return {}
    pick = max if prim.direction == "max" else min
    best = pick(pts, key=lambda p: p.y[prim.name])
    vals = [p.y[prim.name] for p in pts]
    return {"best": {"config": best.cfg, "x": list(best.x), **best.y},
            "primary_range": [min(vals), max(vals)]}


def _axis_label(o) -> str:
    inner = f"log10({o.name})" if o.transform == "log10" else o.name
    return inner if o.direction == "max" else f"-{inner}"
```

and, inside the class:

```python
    def history(self, name: str):
        study = _modes.STUDIES[name]
        X, Y, _, _ = bp.load_history_tensor(name)
        meta = {
            "objectives": [{"name": o.name, "direction": o.direction,
                            "transform": o.transform, "axis": _axis_label(o)}
                           for o in study.objectives],
            "knobs": [{"name": k.name, "type": k.type, "unit": k.unit,
                       "min": k.min, "max": k.max} for k in study.knobs],
            "knob_names": list(study.knob_names),
            "leaderboard": study.leaderboard_rel,
        }
        meta.update(_board_summary(name))
        return X.tolist(), Y.tolist(), meta
```

Also change the comment at `core/bo_driver.py:102` from `# Row shape (KNOB_NAMES/KNOB_FMTS/metric_cols) reads modes.SPECS, the` to `# Row shape (KNOB_NAMES/KNOB_FMTS) reads modes.SPECS, the` (the gate scans comments too).

Change `problems()` to iterate `_modes.STUDIES` instead of `_modes.SPECS`. In `suggest`, replace both `_modes.SPECS` references with `_modes.STUDIES`. Update the module docstring's first line to `"""AutoresearchAdapter: serve schema-2 studies + leaderboards to surrokit.`

- [ ] **Step 4: Make the MCP server's instructions generic**

In `surrogate/mcp_server.py`, replace the `instructions=(…)` text with:

```python
    instructions=(
        "GP surrogate over the autoresearch leaderboards. Problems are the "
        "registered studies. Every output axis is MAXIMIZED; stats(problem)"
        ".objectives gives each axis's name, direction, transform and label "
        "(e.g. '-log10(flash_edep)'), and .knobs gives names, units and "
        "bounds. suggest() IS the production pick path (qnehvi | qlnei | "
        "budget_sob | hybrid, seed derived from round_idx exactly as the "
        "closed loop does). Nothing here submits jobs or writes to "
        "leaderboards -- pure read + compute."
    ),
```

- [ ] **Step 5: Update `tests/test_surrogate.py`**

```bash
grep -n "best_sob\|sob_range\|objectives\"\]\|neg_log10" tests/test_surrogate.py
```

Replace `best_sob` with `best` and `sob_range` with `primary_range`. An assertion on `meta["objectives"] == ["sob", "neg_log10_flash_edep"]` becomes:

```python
        self.assertEqual([o["axis"] for o in meta["objectives"]],
                         ["sob", "-log10(flash_edep)"])
```

- [ ] **Step 6: Run the tests, the suite and every golden**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_generic_core tests.test_surrogate -v` and expect PASS.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` and expect OK.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e` and expect all `OK`.

- [ ] **Step 7: Update the wiki**

- `wiki/drivers/surrogate.md`: `stats` meta now carries `objectives` (name, direction, transform, axis label), `knobs` (name, type, unit, bounds), `best` and `primary_range` (were `best_sob` and `sob_range`). Bump `timestamp`.
- `wiki/drivers/bo-driver.md`: specs are schema-2 study files (`core/study.py`). `evaluate` resolves values by objective name, with no `flash_edep_per_event` fallback. `evaluate_result.json` carries `primary` and `objectives`. Bump `timestamp`.
- `wiki/concepts/budget-sob-picker.md`: `AUTORESEARCH_FLASH_BUDGET` and `AUTORESEARCH_BUDGET_KSIGMA` are gone. The budget and k are the study's `constraints[0].max` and `k_sigma`. For an unconstrained corner round, copy the study into a directory on `$AUTORESEARCH_STUDY_PATH` under a new name and leaderboard, and raise `max` there. Bump `timestamp`.
- `wiki/log.md`: under today's `## YYYY-MM-DD` heading at the top, add one bullet summarizing Phase A (schema 2 the only format; `modes.STUDIES`; generic leaderboard, glue, evaluate and stats; env overrides removed; the flash fallback removed; goldens a/b/d/e unchanged).

- [ ] **Step 8: Commit**

```bash
git add surrogate/ tests/ wiki/
git commit -m "feat(mcp): stats meta from the study; gate that generic code never names physics

Phase A of the generic-study design complete: schema 2 is the only spec
format, and the leaderboard, surrogate glue, evaluate and MCP adapter read
objectives from the study."
```

---

## Self-review notes (kept for the executor)

- **Spec coverage:**

  | Spec item | Where |
  |---|---|
  | Study loader and rules | Task 2 |
  | `derive` lifted out of `geom` | Task 2 (`_derive_and_geom`) |
  | Leaderboard with `extra_columns`, `fmt`, `layout`, `context` | Tasks 2 and 6 |
  | `build_problem(study)` with transforms and the constraint | Task 7 |
  | `stats` meta | Task 9 |
  | One-time conversion and deleting the old loader | Tasks 4 and 5 |
  | Parity gates (spec dump, geometry, history fingerprint, ask inputs, byte-identical append) | Tasks 1, 5, 6, 7 and 8 |
  | Synthetic 3-objective study | Task 7 |
  | Env overrides removed | Task 7 |
  | Flash fallback dropped | Tasks 5 and 8 |
  | Pending format unchanged | untouched; no task, on purpose |
- **Deliberately not in Phase A:** leaderboard layout `v2`, derive without geometry, adapters and the contract engine (Phase B), deleting `study_compat.py` and `pipeline.py`'s verbs (Phase C), removing the `--alpha` flag (a later cleanup).
- **Names used across tasks:**
  - `modes.STUDIES`, `Study.objectives`, `Objective.key`, `Leaderboard.for_study`, `Point.y`
  - `axis_value`, `_problem_from`, `primary_only`, `load_modespec`, `modespec_from_study`
