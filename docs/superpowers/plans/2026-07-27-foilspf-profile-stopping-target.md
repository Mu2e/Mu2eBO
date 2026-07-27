# foilspf — Profile-Parameterized All-Foils Stopping Target: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `foilspf`, a 10-D Bayesian-optimization line that varies every foil in the Mu2e stopping target — outer radius, thickness, central hole, and overall stack length — against the existing `foilsflash` sob + flash objective.

**Architecture:** One new JSON file, `mode_specs/foilspf.json`, and nothing else. The mode-loading machinery already derives every registration site from `modes.SPECS`, and `core/geom_template.py` already implements the Lagrange-quadratic profile engine this design needs. **No Python is written in this plan.** The remaining work is one spec file, one focused test module, one allow-list line, and a four-rung validation ladder that must be climbed in order.

**Tech Stack:** Python 3.11 stdlib (the mode loader is stdlib-only by contract), `unittest`, Mu2e Offline / Geant4 via `muse`, the Mu2e grid via `mu2ejobsub`.

## Global Constraints

Copied verbatim from the design spec. Every task's requirements implicitly include these.

- Mode name is `foilspf`. Leaderboard is `leaderboards/leaderboard_bo_foilspf.tsv` — a NEW file, shared with no other mode.
- Bounds: `rOut_{0,1,2}` ∈ [50, 120] mm · `hT_{0,1,2}` ∈ [0.01, 0.15] mm · `f_{0,1,2}` ∈ [0, 0.95] · `extent` ∈ [400, 1200] mm.
- Profile clips equal the bounds exactly: rOut [50, 120], hT [0.01, 0.15], f [0, 0.95].
- 49 foils. `z0InMu2e = 5871.0` pinned. `deltaZ = extent / 48` derived — **`deltaZ` is emitted once, from the expression, and never as a constant.**
- `stoppingTarget.holeRadius` is the poison pill and MUST render as the literal `1.0e6`, never `1000000.0`. It is emitted via `"raw"`, because JSON's number grammar loses the exponent form.
- `grid_tarball` MUST be `Code_helical_holeradii.tar.bz2` — it carries the per-foil `holeRadii` patch. Any other tarball silently builds a uniform-hole stack.
- Grid chain is `mubeam → mustops_ce → elebeam_flash` with `presubmit_after: {"mubeam": ["elebeam_flash"]}`.
- `obs_noise` is `[0.006, 0.01]`, carried from `foilsflash`.
- Never set `AUTORESEARCH_ELEBEAM_NJOBS`. The standard is the default 100 jobs (user decision 2026-07-09); overriding it double-spent 85% of grid-hours in a prior campaign.
- Never `git push` — the Bash tool cannot reach the user's ssh-agent. Commit only.
- Stage `git add` with **explicit paths**. Never `git add -A` or `git add .`; the working tree holds unrelated uncommitted deck, leaderboard, and wiki work.
- Baseline before this plan: **392 tests, all passing**, via `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`.

---

## File Structure

| File | Responsibility |
|---|---|
| `mode_specs/foilspf.json` (create) | The entire mode: software, grid chain, knobs, bounds, leaderboard, preflight flags, geometry template. |
| `tests/test_foilspf_spec.py` (create) | Behavioural tests for this one shipped spec: geometry correctness, bounds, clip, mass envelope. Kept separate from `tests/test_mode_json.py`, which tests the *loader schema* rather than any particular spec. |
| `tests/test_modes.py:320` (modify) | `SHIPPED_SPECS` allow-list — one line. Adding a file to `mode_specs/` deliberately fails a guard until it is listed; that is the intended review checkpoint. |
| `wiki/projects/bo-foilspf.md` (create, Task 4) | Wiki page for the new line. |
| `wiki/index.md`, `wiki/log.md` (modify, Task 4) | Index entry and dated log bullet. |

**Nothing else needs touching.** Verified against the live code: `graph/closed_loop.py:818` takes `--mode` choices from `sorted(_modes.SPECS)`; `core/botorch_predict.py:46` builds `MODE_SPECS` from `_modes.SPECS`; `graph/config.py:48` reads `_modes.SPECS[...]`; and `graph/state.py:38` types `mode` as a plain `str`, not a `Literal`. A new spec file registers itself everywhere.

---

## Task 1: The `foilspf` mode spec

**Files:**
- Create: `mode_specs/foilspf.json`
- Create: `tests/test_foilspf_spec.py`
- Modify: `tests/test_modes.py:320`

**Interfaces:**
- Consumes: `mode_json.load_mode_dir` (already wired at `core/modes.py` tail), `geom_template.GeomTemplate` profile support.
- Produces: `modes.SPECS["foilspf"]` — a `ModeSpec` with `knob_names == ("rOut_0","rOut_1","rOut_2","hT_0","hT_1","hT_2","f_0","f_1","f_2","extent")` and 10-element `bounds_lo`/`bounds_hi`; and `bo_driver.MODES["foilspf"]` — a `JsonMode`. Tasks 2–4 consume both.

- [ ] **Step 1: Write the failing test module**

Create `tests/test_foilspf_spec.py`:

```python
"""Behavioural tests for the shipped foilspf spec.

Separate from test_mode_json.py on purpose: that module tests the LOADER
(schema, rejection paths); this one tests that THIS spec renders the
geometry the design asked for. A loader bug and a spec bug fail different
files.

Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md
"""
import itertools
import math
import sys
import unittest
from pathlib import Path

# Match the rest of the suite: core/ on sys.path, import `modes` bare, so
# exactly one ModeSpec class is ever live in this process.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402

N_FOILS = 49
DEPLOYED = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 800.0]


def _render(x):
    return modes.SPECS["foilspf"].geom.render(x)


def _vec(text, key):
    """Pull one `vector<double> <key> = { ... };` line out of a render."""
    prefix = f"vector<double> {key} = {{"
    for line in text.splitlines():
        if line.startswith(prefix):
            body = line[len(prefix):].rsplit("}", 1)[0]
            return [float(v) for v in body.split(",")]
    raise KeyError(f"{key} not found in render")


def _scalar(text, key):
    for line in text.splitlines():
        if line.startswith("double ") and line.split(" = ")[0] == f"double {key}":
            return line.split(" = ")[1].rstrip(";")
    raise KeyError(f"{key} not found in render")


def _mass_g(x):
    """Aluminium mass of the rendered stack, grams. Al density 2.70e-3 g/mm^3."""
    text = _render(x)
    rout = _vec(text, "stoppingTarget.radii")
    rin = _vec(text, "stoppingTarget.holeRadii")
    ht = _vec(text, "stoppingTarget.halfThicknesses")
    return sum(math.pi * (a * a - b * b) * 2 * t * 2.70e-3
               for a, b, t in zip(rout, rin, ht))


class TestFoilspfRegistration(unittest.TestCase):

    def test_spec_loads_and_registers_as_a_json_mode(self):
        import bo_driver as bo
        self.assertIn("foilspf", modes.SPECS)
        self.assertIsInstance(bo.MODES["foilspf"], bo.JsonMode)

    def test_bounds_match_the_design(self):
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.knob_names, (
            "rOut_0", "rOut_1", "rOut_2",
            "hT_0", "hT_1", "hT_2",
            "f_0", "f_1", "f_2",
            "extent"))
        self.assertEqual(s.bounds_lo,
                         (50.0, 50.0, 50.0, 0.01, 0.01, 0.01, 0.0, 0.0, 0.0, 400.0))
        self.assertEqual(s.bounds_hi,
                         (120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.95, 0.95, 0.95, 1200.0))
        self.assertEqual(s.int_dims, ())

    def test_run_configuration_matches_foilsflash(self):
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.grid_stages, ("mubeam", "mustops_ce", "elebeam_flash"))
        self.assertEqual(s.presubmit_after, {"mubeam": ("elebeam_flash",)})
        self.assertEqual(s.obs_noise, (0.006, 0.01))
        self.assertIn("Code_helical_holeradii.tar.bz2", s.grid_tarball)

    def test_leaderboard_is_not_shared_with_any_other_mode(self):
        """Two modes writing one leaderboard interleaves incompatible schemas."""
        s = modes.SPECS["foilspf"]
        self.assertEqual(s.leaderboard_rel,
                         "leaderboards/leaderboard_bo_foilspf.tsv")
        others = [m.leaderboard_rel for n, m in modes.SPECS.items() if n != "foilspf"]
        self.assertNotIn(s.leaderboard_rel, others)


class TestFoilspfGeometry(unittest.TestCase):

    def test_every_per_foil_vector_has_49_entries(self):
        text = _render(DEPLOYED)
        for key in ("stoppingTarget.radii",
                    "stoppingTarget.halfThicknesses",
                    "stoppingTarget.holeRadii"):
            self.assertEqual(len(_vec(text, key)), N_FOILS, key)

    def test_deployed_equivalent_control_points_reproduce_the_deployed_stack(self):
        """All three control points equal => a flat profile. This is the
        anchor: if it drifts, every comparison against the deployed target
        is meaningless."""
        text = _render(DEPLOYED)
        self.assertEqual(set(_vec(text, "stoppingTarget.radii")), {75.0})
        self.assertEqual(set(_vec(text, "stoppingTarget.halfThicknesses")), {0.0528})
        self.assertEqual(set(_vec(text, "stoppingTarget.holeRadii")), {21.525})
        self.assertEqual(_scalar(text, "stoppingTarget.z0InMu2e"), "5871.0000")

    def test_extent_knob_drives_deltaZ(self):
        for extent, expected in ((400.0, "8.333333"),
                                 (800.0, "16.666667"),
                                 (1200.0, "25.000000")):
            x = DEPLOYED[:9] + [extent]
            self.assertEqual(_scalar(_render(x), "stoppingTarget.deltaZ"), expected)

    def test_a_bent_profile_is_not_flat(self):
        """Guards against a wiring bug where all three control points feed
        the same slot and every profile silently renders flat."""
        x = [50.0, 85.0, 120.0] + DEPLOYED[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertAlmostEqual(r[0], 50.0, places=3)
        self.assertAlmostEqual(r[48], 120.0, places=3)
        self.assertGreater(r[24], r[0])

    def test_clip_projects_the_quadratic_overshoot(self):
        """A quadratic through in-bounds control points overshoots BETWEEN
        them: (50, 120, 120) peaks at 128.8 near i=36. The clip must project
        it onto 120 rather than emit an out-of-bounds radius."""
        x = [50.0, 120.0, 120.0] + DEPLOYED[3:]
        r = _vec(_render(x), "stoppingTarget.radii")
        self.assertLessEqual(max(r), 120.0)
        self.assertAlmostEqual(r[36], 120.0, places=4)

    def test_hole_is_strictly_inside_the_foil_at_every_bound_corner(self):
        """rIn < rOut must hold everywhere, or G4Tubs aborts. 64 corners of
        the (rOut, f) sub-box."""
        worst = float("inf")
        for c in itertools.product((50.0, 120.0), repeat=3):
            for f in itertools.product((0.0, 0.95), repeat=3):
                x = list(c) + [0.0528] * 3 + list(f) + [800.0]
                text = _render(x)
                rout = _vec(text, "stoppingTarget.radii")
                rin = _vec(text, "stoppingTarget.holeRadii")
                worst = min(worst, min(a - b for a, b in zip(rout, rin)))
        self.assertGreater(worst, 0.0)

    def test_poison_pill_survives_the_json_number_grammar(self):
        """1.0e6 must reach the geometry verbatim. Rendered as 1000000.0 it
        still crashes, but the intent is unreadable; rendered as a
        'sensible' scalar it would silently build a uniform-hole stack --
        which is how 62 foilsg rows were lost."""
        text = _render(DEPLOYED)
        self.assertIn("double stoppingTarget.holeRadius = 1.0e6;", text)

    def test_no_geometry_key_is_emitted_twice(self):
        """Duplicate keys are last-write-wins in SimpleConfig, silently. The
        live hazard is deltaZ: a leftover constant would override the extent
        knob and pin every eval at 800 mm while the leaderboard recorded a
        knob that did nothing. GeomTemplate rejects duplicates at load, so
        this asserts the shipped render actually exercises that guarantee."""
        keys = []
        for line in _render(DEPLOYED).splitlines():
            if line.startswith("//") or line.startswith("#") or not line.strip():
                continue
            keys.append(line.split(" = ")[0].split(" ", 1)[1])
        self.assertEqual(sorted(keys), sorted(set(keys)))


class TestFoilspfMassEnvelope(unittest.TestCase):
    """The bounds were chosen to cap stack mass. If someone widens them,
    these fire before any grid time is spent."""

    DEPLOYED_37_FOIL_MASS_G = 171.1

    def test_deployed_equivalent_mass_is_49_over_37_of_the_real_target(self):
        self.assertAlmostEqual(_mass_g(DEPLOYED), 226.6, delta=1.0)

    def test_worst_corner_stays_inside_the_designed_envelope(self):
        """Heaviest reachable stack: max radius, no hole, max thickness."""
        x = [120.0] * 3 + [0.15] * 3 + [0.0] * 3 + [800.0]
        mass = _mass_g(x)
        self.assertAlmostEqual(mass, 1795.5, delta=5.0)
        self.assertLess(mass / self.DEPLOYED_37_FOIL_MASS_G, 11.0)

    def test_extent_does_not_change_mass(self):
        """Spreading the same foils over more z adds no aluminium. If this
        fails, extent is wired to something it should not touch."""
        short = _mass_g(DEPLOYED[:9] + [400.0])
        long_ = _mass_g(DEPLOYED[:9] + [1200.0])
        self.assertAlmostEqual(short, long_, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and watch them fail**

```bash
PYTHONPATH= .venv/bin/python -m unittest tests.test_foilspf_spec -v
```

Expected: every test errors with `KeyError: 'foilspf'` — the spec does not exist yet.

- [ ] **Step 3: Create the spec file**

Create `mode_specs/foilspf.json`. This exact content has been loaded and rendered successfully against the live loader; do not retype it from memory.

```json
{
  "name": "foilspf",
  "note": "10D all-foils stopping target: three Lagrange-quadratic profiles (rOut, halfThickness, hole fraction) across 49 foils plus a stack-length knob, vs the foilsflash sob+flash objective. Replaces the deployed 37-foil base entirely -- there is no pinned baseline. Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md",
  "software": {
    "musing": "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh",
    "grid_tarball": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2"
  },
  "run": {
    "stages": ["mubeam", "mustops_ce", "elebeam_flash"],
    "harvest": "harvest",
    "jobs_per_stage": {"mubeam": 15, "mustops_ce": 15, "elebeam_flash": 100},
    "presubmit_after": {"mubeam": ["elebeam_flash"]},
    "stage_tuning": {
      "mubeam": {"events_per_job": 200000, "memory_mb": 2000, "quorum": 0.8},
      "mustops_ce": {"events_per_job": 75000, "memory_mb": 2000, "quorum": 0.8},
      "elebeam_flash": {"events_per_job": 110000, "memory_mb": 2000}
    }
  },
  "knobs": [
    {"name": "rOut_0", "min": 50.0, "max": 120.0, "fmt": "{:.4f}"},
    {"name": "rOut_1", "min": 50.0, "max": 120.0, "fmt": "{:.4f}"},
    {"name": "rOut_2", "min": 50.0, "max": 120.0, "fmt": "{:.4f}"},
    {"name": "hT_0", "min": 0.01, "max": 0.15, "fmt": "{:.6f}"},
    {"name": "hT_1", "min": 0.01, "max": 0.15, "fmt": "{:.6f}"},
    {"name": "hT_2", "min": 0.01, "max": 0.15, "fmt": "{:.6f}"},
    {"name": "f_0", "min": 0.0, "max": 0.95, "fmt": "{:.4f}"},
    {"name": "f_1", "min": 0.0, "max": 0.95, "fmt": "{:.4f}"},
    {"name": "f_2", "min": 0.0, "max": 0.95, "fmt": "{:.4f}"},
    {"name": "extent", "min": 400.0, "max": 1200.0, "fmt": "{:.4f}"}
  ],
  "int_dims": [],
  "leaderboard": {
    "file": "leaderboards/leaderboard_bo_foilspf.tsv",
    "columns": ["sob", "flash_edep", "alpha", "obj"],
    "obs_noise": [0.006, 0.01],
    "metrics": {
      "sob": ["s_over_sqrt_b"],
      "flash_edep": ["flash_edep_per_pot", "flash_edep_per_event"]
    }
  },
  "preflight": {
    "fcl": "surfacecheck",
    "dumps_gdml": true,
    "verifies_foil_gdml": true,
    "preserves_gdml": false,
    "checks_managed_overlap": true
  },
  "geom": {
    "base": "Offline/Mu2eG4/geom/geom_run1_a.txt",
    "consts": {
      "n_foils": 49,
      "z0": 5871.0
    },
    "derived": {
      "deltaZ": "extent / 48"
    },
    "profiles": {
      "rOut_p": {"count": "n_foils", "control": ["rOut_0", "rOut_1", "rOut_2"], "clip": [50.0, 120.0]},
      "hT_p": {"count": "n_foils", "control": ["hT_0", "hT_1", "hT_2"], "clip": [0.01, 0.15]},
      "f_p": {"count": "n_foils", "control": ["f_0", "f_1", "f_2"], "clip": [0.0, 0.95]}
    },
    "lines": [
      {"comment": "=== foilspf (10D profile mode) === {n_foils} free foils, no pinned base"},
      {"comment": "rOut  profile: {rOut_0:.2f} -> {rOut_1:.2f} -> {rOut_2:.2f} mm (Lagrange quadratic, u = i/48)"},
      {"comment": "hT    profile: {hT_0:.4f} -> {hT_1:.4f} -> {hT_2:.4f} mm"},
      {"comment": "hole  profile: f = {f_0:.3f} -> {f_1:.3f} -> {f_2:.3f}  (rIn_i = f_i * rOut_i)"},
      {"comment": "extent {extent:.1f} mm over 48 gaps -> deltaZ {deltaZ:.6f} mm; centre pinned at z0 {z0:.1f}"},
      {"key": "hasTSdA", "type": "bool", "value": false},
      {"key": "tsda.helical.build", "type": "bool", "value": false},
      {"key": "stoppingTarget.z0InMu2e", "type": "double", "expr": "z0", "fmt": "{:.4f}"},
      {"key": "stoppingTarget.deltaZ", "type": "double", "expr": "deltaZ", "fmt": "{:.6f}"},
      {"key": "stoppingTarget.radii", "type": "vector<double>", "fmt": "{:.4f}",
       "per_index": {"count": "n_foils", "expr": "rOut_p[i]"}},
      {"key": "stoppingTarget.halfThicknesses", "type": "vector<double>", "fmt": "{:.6f}",
       "per_index": {"count": "n_foils", "expr": "hT_p[i]"}},
      {"comment": "POISON PILL: an unpatched StoppingTargetMaker ignores holeRadii and reads"},
      {"comment": "this scalar. 1e6 forces a loud G4Tubs crash instead of a silently uniform"},
      {"comment": "stack -- emitting a 'sensible' scalar is how 62 foilsg rows were lost."},
      {"key": "stoppingTarget.holeRadius", "type": "double", "raw": "1.0e6"},
      {"key": "stoppingTarget.holeRadii", "type": "vector<double>", "fmt": "{:.4f}",
       "per_index": {"count": "n_foils", "expr": "f_p[i] * rOut_p[i]"}},
      {"comment": "Degrader parked at 120 deg (mmackenz hardware detent)"},
      {"key": "degrader.build", "type": "bool", "value": false},
      {"key": "degrader.rotation", "type": "double", "value": 120.0},
      {"key": "ts.coll5.material1Name", "type": "string", "value": "COL5Poly"},
      {"comment": "TT_MidInner -> DS2Vacuum fix (manually patched, mirrors v111)"},
      {"key": "tracker.inDS2Vacuum", "type": "bool", "value": true},
      {"key": "ds2.halfLength", "type": "double", "value": 3825},
      {"key": "ds.hasServicePipes", "type": "bool", "value": false},
      {"comment": "Overlap-suppression (foil-support off + rail shrink)"},
      {"key": "stoppingTarget.foilTarget_supportStructure", "type": "bool", "value": false},
      {"key": "ds.lengthRail2", "type": "double", "value": 0.1},
      {"key": "ds.lengthRail3", "type": "double", "value": 0.1}
    ]
  }
}
```

- [ ] **Step 4: Run the new tests — they pass, and a DIFFERENT test now fails**

```bash
PYTHONPATH= .venv/bin/python -m unittest tests.test_foilspf_spec -v
```

Expected: PASS, 15 tests.

```bash
PYTHONPATH= .venv/bin/python -m unittest tests.test_modes -v
```

Expected: **one failure**, `test_mode_specs_directory_holds_only_the_readme`, reporting `['README.md', 'foilspf.json', 'foilsflash.json'] != ['README.md', 'foilsflash.json']`.

This failure is the guard working as designed. A new file in `mode_specs/` is loaded by every process that imports `modes`, so arriving there unannounced must break the build. Listing it is the conscious act.

- [ ] **Step 5: Add the spec to the allow-list**

In `tests/test_modes.py:320`, change:

```python
    SHIPPED_SPECS = {"foilsflash.json"}
```

to:

```python
    SHIPPED_SPECS = {"foilsflash.json", "foilspf.json"}
```

- [ ] **Step 6: Run the full suite**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests
```

Expected: `Ran 407 tests` (392 baseline + 15 new), `OK`. If any pre-existing test fails, stop and report — this task adds a file and one set literal, and must not perturb anything else.

- [ ] **Step 7: Commit**

```bash
git add mode_specs/foilspf.json tests/test_foilspf_spec.py tests/test_modes.py
git commit -m "feat(modes): add foilspf — 10D profile-parameterized all-foils stopping target

Three Lagrange-quadratic profiles (rOut, halfThickness, hole fraction)
across 49 foils, plus an extent knob driving deltaZ = extent/48. Pure
JSON: geom_template already ships lagrange_profile and permits
ast.Subscript on declared profiles, so no Python was needed.

First shipped spec to use the profiles block, which had 12 unit tests but
no production consumer. Bounds cap worst-corner stack mass at 10.5x the
deployed 171 g target; extent is verified not to change mass at all.

Design: docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md"
```

---

## Task 2: Local G4 preflight gate

**Files:** none modified. This is a validation gate producing evidence, not code.

**Interfaces:**
- Consumes: `modes.SPECS["foilspf"]` from Task 1.
- Produces: a recorded PASS/FAIL verdict for five geometries, which Task 3 depends on.

The `profiles` code path has never rendered a geometry that Geant4 actually built. This task costs minutes and gates a step that costs grid-hours.

- [ ] **Step 1: Render the five geometries**

```bash
mkdir -p /tmp/oksuzian/foilspf_preflight
PYTHONPATH= .venv/bin/python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "core")
import modes

OUT = Path("/tmp/oksuzian/foilspf_preflight")
CASES = {
    "deployed":  [75, 75, 75, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 800.0],
    "corner_hi": [120, 120, 120, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, 800.0],
    "corner_lo": [50, 50, 50, 0.01, 0.01, 0.01, 0.95, 0.95, 0.95, 800.0],
    "short":     [75, 75, 75, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 400.0],
    "long":      [75, 75, 75, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 1200.0],
}
for name, x in CASES.items():
    p = OUT / f"geom_foilspf_{name}.txt"
    p.write_text(modes.SPECS["foilspf"].geom.render(x))
    print("wrote", p)
PY
```

- [ ] **Step 2: Run real Geant4 initialization on each**

For each of the five files, run one event under the patched Musing. The `setup_local.sh` path is the one the spec declares, and is what carries the `holeRadii` patch locally:

```bash
for case in deployed corner_hi corner_lo short long; do
  echo "=== $case ==="
  ( source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh \
    && muse setup ops \
    && source /exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh \
    && mu2e -n 1 -c Mu2eG4/fcl/surfaceCheck.fcl \
         --config-override "GeometryService.inputFile=/tmp/oksuzian/foilspf_preflight/geom_foilspf_${case}.txt" \
    ) > /tmp/oksuzian/foilspf_preflight/${case}.log 2>&1
  echo "rc=$?"
done
```

If the `--config-override` form is rejected by this Offline version, fall back to the mechanism `bo_driver.py`'s own preflight uses — read `cmd_preflight` in `core/bo_driver.py` and mirror it exactly rather than inventing a new invocation.

- [ ] **Step 3: Check every log for a real PASS**

```bash
grep -c "holeRadii vector active (n=49)" /tmp/oksuzian/foilspf_preflight/*.log
grep -E "GeomSolids|GeomNav|G4Exception|-------- EEEE" /tmp/oksuzian/foilspf_preflight/*.log
```

Required for every case:
- the canary `holeRadii vector active (n=49)` appears **once** — this proves the patched `StoppingTargetMaker` is live and the per-foil holes are real, not the scalar fallback;
- **no** `GeomSolids`, `GeomNav`, or `G4Exception` lines.

A missing canary means the unpatched library is being used and every hole is wrong. **Do not proceed to Task 3** on a missing canary or any geometry error — report instead. Note that a preflight classifier bug once returned PASS on fatal `GeomSolids0002` aborts (wiki: `preflight-past-init-false-pass`), so grep the log yourself rather than trusting a summary verdict.

- [ ] **Step 4: Record the result**

Append the five verdicts (case, rc, canary present, geometry errors) to the task report. No commit — this task produces no tracked files.

---

## Task 3: Single grid eval gate

**Files:** none modified.

**Interfaces:**
- Consumes: Task 2's PASS verdicts.
- Produces: one row in an isolated leaderboard, proving the full chain works end-to-end before a campaign is funded.

This mirrors the `ffjson01` sequence that de-risked the JSON-mode switchover: one real eval, isolated, before any campaign.

- [ ] **Step 1: Confirm nothing is running and the prefix is free**

```bash
ps -fu $USER -ww | grep "[c]losed_loop\|[g]raph.run"
grep -c foilspfSMOKE leaderboards/leaderboard_bo_foilspf.tsv 2>/dev/null || echo "no leaderboard yet — expected"
```

Both must come back empty. Reusing a name-prefix that appears in a leaderboard or a stale `state/*_cluster.txt` makes the runner silently launch zero children (wiki: `closed-loop-stale-cluster-silent-no-launch`).

- [ ] **Step 2: Confirm Kerberos is fresh**

```bash
klist | head -5
```

The ticket must not expire within the next ~6 hours. Mid-run expiry kills the chain at `subprocess.run` with `Errno 127 ENOKEY` and no leaderboard row (wiki: `kerberos-mid-run-expiry`). Renew with `kinit -R` if it is close.

- [ ] **Step 3: Launch exactly one eval**

```bash
mkdir -p /tmp/oksuzian/foilspfSMOKE
AUTORESEARCH_MODE=foilspf \
AUTORESEARCH_CHECKPOINT_DIR=/tmp/oksuzian/foilspfSMOKE \
PYTHONPATH= nohup .venv/bin/python -m graph.closed_loop \
  --mode foilspf --name-prefix foilspfSMOKE \
  --picker hybrid --q 1 --max-rounds 1 \
  > graph_data/foilspfSMOKE_parent.log 2>&1 &
echo "PID=$!"
```

Do **not** set `AUTORESEARCH_ELEBEAM_NJOBS`. Expect roughly 3.5–4 hours to the row.

- [ ] **Step 4: Verify the row and the canary**

```bash
cut -f1,11,12 leaderboards/leaderboard_bo_foilspf.tsv
grep -rl "holeRadii vector active (n=49)" /exp/mu2e/data/users/oksuzian/autoresearch_grid/foilspfSMOKE*/ | head -3
```

Success requires **all** of:
- exactly one row, named `foilspfSMOKE*`;
- `sob` non-zero;
- `flash_edep` non-zero — a zero or missing flash means the `elebeam_flash` stage fail-softed, and the design's guarantee is that such a row is refused rather than recorded as a fake zero;
- the canary present in the grid-side logs, proving the **grid tarball** (not just the local Musing) carries the `holeRadii` patch.

The last point is the one that cannot be checked any earlier: preflight runs against the local patched environment, the grid runs against the tarball, and a mismatch between them is exactly what killed `foilsflashSMOKE3` (wiki: `foilsflash-tarball-mode-key-omission`).

- [ ] **Step 5: Record the result**

Report the row values and canary status. If flash is zero or the canary is absent, **stop** — do not launch Task 4.

---

## Task 4: Campaign and wiki

**Files:**
- Create: `wiki/projects/bo-foilspf.md`
- Modify: `wiki/index.md`, `wiki/log.md`

**Interfaces:**
- Consumes: Task 3's verified row.

- [ ] **Step 1: Launch the 20-eval campaign**

```bash
mkdir -p /tmp/oksuzian/foilspf01
AUTORESEARCH_MODE=foilspf \
AUTORESEARCH_CHECKPOINT_DIR=/tmp/oksuzian/foilspf01 \
PYTHONPATH= nohup .venv/bin/python -m graph.closed_loop \
  --mode foilspf --name-prefix foilspf01 \
  --picker hybrid --q 10 --rolling --max-evals 20 \
  > graph_data/foilspf01_parent.log 2>&1 &
echo "PID=$!"
```

Round 0 is Sobol — the 414 `foilsflash` rows are in a different (6-D extras-only) space and cannot warm-start this one.

- [ ] **Step 2: Verify launch health at ~15 minutes**

```bash
grep -c "^\[closed_loop\] launched foilspf01" graph_data/foilspf01_parent.log
grep -h '"preflight"' /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/closed_loop_logs/foilspf01R00_*.log \
  | grep -oE '"preflight": "[a-z]+"' | sort | uniq -c
```

Expect 10 launched and 10 `"pass"`. A wave of `fail_managed` or `ambiguous` verdicts with the parent still reporting success is the `foilsx04` failure mode — 20/20 children dead at preflight, parent converged with zero rows.

- [ ] **Step 3: Judge the campaign against the spec's success criteria**

When all 20 evals have landed, compute the Pareto front over the whole
`foilspf` leaderboard and check it against `foilsflash`'s best-known values:

```bash
PYTHONPATH= .venv/bin/python - <<'PY'
import csv
rows = []
with open("leaderboards/leaderboard_bo_foilspf.tsv") as f:
    for d in csv.DictReader(f, delimiter="\t"):
        try:
            s, fl = float(d["sob"]), float(d["flash_edep"])
        except (ValueError, KeyError, TypeError):
            continue
        if s > 0 and fl > 0:
            rows.append((d["config"], s, fl))
front = [a for a in rows if not any(
    b[1] >= a[1] and b[2] <= a[2] and (b[1] > a[1] or b[2] < a[2]) for b in rows)]
front.sort(key=lambda t: -t[1])
print(f"{len(rows)} evals | front = {len(front)}")
for n, s, fl in front:
    print(f"  {n:26s} sob {s:.2f}  flash {fl:.4g}")
print(f"\nbest sob = {max(r[1] for r in rows):.2f}  (foilsflash ceiling 3.91)")
print(f"min flash = {min(r[2] for r in rows):.4g}  (foilsflash floor 6.163e-07)")
PY
```

The spec declares success as **either** a row above sob 3.91 — meaning the
extras-only ceiling was a parameterization limit — **or** a point that
dominates a current `foilsflash` front member, meaning the richer geometry
buys front area without a new champion.

Neither outcome is a failure of the work. If the line produces neither, that
is itself the result the campaign was run to obtain: the ceiling is a property
of the stopping-target physics rather than of the search space, and the flash
axis is where remaining effort belongs. Record whichever of the three
outcomes occurred — the negative result is the one most likely to be
re-purchased by a future session if it goes unwritten.

- [ ] **Step 4: Write the wiki page**

Create `wiki/projects/bo-foilspf.md` following the OKF schema in `wiki/CLAUDE.md`: frontmatter with `type: project`, `title`, `description`, `status: active`, `timestamp: '2026-07-27'`; then `## Summary`, `## Key facts`, `## Cross-links`, `## Open questions / TODO`.

Key facts to record, since a future session would otherwise re-derive them:
- the 10-D parameterization and why the interior node sits at `u = 0.5` (reachability is unchanged by node placement; 0.5 minimizes out-of-bound excursion, 7.3% vs 46.7% at u=0.2; for exactly three points equispaced coincides with Chebyshev–Lobatto, and that coincidence breaks at four);
- the single-bend limit and the escape hatch (4 control points, 12-D) with the campaign evidence that would trigger it;
- that non-uniform spacing needs **no** patched library — `StoppingTargetMaker.cc:184` computes `z_i = offset + (i − n0)·deltaZ + zVars[i]` and reads `zVars` in stock Offline at `:85` — and was deferred only because a spacing profile overlaps the thickness profile;
- the mass envelope table and that `extent` does not change mass;
- that this is the first production consumer of the `profiles` engine.

Cross-link to `/projects/bo-foilsflash.md`, `/projects/bo-foilsg.md`, `/concepts/saturation-is-acquisition-relative.md`, `/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md`, and `/external/edmonds-target-hole-docdb10898.md`.

- [ ] **Step 5: Add the index and log entries**

One line in `wiki/index.md` under `## Projects`, and one bullet in `wiki/log.md` under a `## 2026-07-27` heading at the **top** of the file (newest first, per OKF), recording the launch and the Task 2/3 validation results.

- [ ] **Step 6: Commit the wiki**

```bash
git add wiki/projects/bo-foilspf.md wiki/index.md wiki/log.md
git commit -m "docs(wiki): bo-foilspf — first production campaign on the profile engine"
```

Explicit paths only. Do not `git push`.

---

## Notes for the implementer

**Why there is no Python task.** Every mode-registration site derives from `modes.SPECS`. If you find yourself editing `graph/closed_loop.py`, `core/botorch_predict.py`, `graph/state.py`, or `graph/config.py` to make `foilspf` appear, stop — something is wrong with the spec file, not with those modules. The one exception is the test allow-list in Task 1 Step 5, which is deliberate.

**The validation ladder is ordered, and the order is the point.** Unit tests catch schema and arithmetic errors for free. Local preflight catches Geant4 build failures for minutes. The single grid eval catches local-vs-grid environment divergence for one eval. The campaign costs 20. Each rung catches a class the rung below cannot see; skipping one does not save time, it moves the failure somewhere more expensive.

**Never edit `graph/*.py` or `core/pipeline.py` while a campaign is in flight.** Tasks 3 and 4 leave grid children running for hours.
