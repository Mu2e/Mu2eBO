# JSON-configurable optimization modes — design

**Date:** 2026-07-25
**Status:** design approved, not yet planned
**Goal:** add a new BO optimization line by writing **one JSON file**, with no Python changes.

---

## 1. Problem

Adding an optimization line today means editing Python in several places: a `ModeSpec`
entry in `core/modes.py`, a `BOMode` subclass in `core/bo_driver.py`, the `MODES` dict,
and a `Literal` in `graph/state.py`. `CONTEXT.md:20` states it plainly — *"Adding a mode
= subclass BOMode + add to MODES"*. Missing one site is the root of a whole incident
family (`foilsflash-tarball-mode-key-omission`, `preflight-mode-tuple-prodtarget6d-omission`).

The ask: introduce optimization configurations nobody has thought of yet, without
touching source.

## 2. What a Mode actually needs

`CONTEXT.md:82` defines a **Mode = ModeSpec (data) + BOMode (behavior)**. `core/modes.py`
is already pure data — six modes, every field explicit, stdlib-only. That half is
JSON-ready as written.

The behavior half turned out to be far more regular than expected. `_geom_text(x)` emits
a Mu2e geometry overlay, which is just an include plus typed assignments:

```
#include "Offline/Mu2eG4/geom/geom_run1_a.txt"
bool degrader.build = false;                   <- fixed setting
double ds2.halfLength = 3825;                  <- fixed setting
vector<double> stoppingTarget.radii = { ... }; <- the knob-derived part
```

Of ~20 lines in a foils geometry, only **four** depend on the knobs. Their structure is
simple: repeated segments (`[rOut_up]*6 + [75.0]*37 + [rOut_dn]*6`) or a profile over
index (`c0 + c1*i + c2*i^2`). A small vocabulary reproduces **all four** existing
geometry families.

The overlay is a generic override mechanism, so any parameter Offline already reads can
be varied with no C++ work. Confirmed: the existing foils geometry already overrides
`ts.coll5.material1Name`, a TS collimator parameter.

## 3. Scope

**Day one — a JSON mode must run a campaign end-to-end:** propose -> render geom ->
preflight -> stages -> harvest -> leaderboard row.

**Deferred, by decision:** `is_buildable` constraints, `parse_geom` round-trip, and
`load_priors`. Defaults: always buildable, `parse_geom` raises `NotImplementedError`
with a pointed message, no priors (botorch Sobol already cold-starts).

**Three tiers of "new line"**, only the first two of which JSON covers:

| Tier | Example | Needs |
|---|---|---|
| 1 | TS collimator vs S/sqrt(B) | New geom keys only; existing stage chain. **Pure JSON.** |
| 2 | New measurement stage | New `STAGES` entry (already data) + a `template.fcl`. JSON + one file. |
| 3 | New metric extractor | New harvest logic. **Python.** |

Tier 1 is broader than it sounds: `mubeam -> mustops_ce` measures CE significance
regardless of which geometry was perturbed.

## 4. Approach: additive JSON registry

**Chosen over** (a) migrating all six modes to JSON — rewrites incident-hardened
renderers for no functional gain, and shared constants like `_FOILS_FAMILY_NOISE` expand
into literals that drift; (b) plugin Python renderers — lowest risk but fails the actual
goal, since adding a line still means writing code.

- `core/modes.py` keeps its six Python specs **unchanged** and gains a loader for
  `modes/*.json`, merged into `SPECS` through the same `__post_init__` validation.
- `ModeSpec` gains one optional `geom` field. The six Python modes pass `None`
  **explicitly** — matching the module's "a missing fact is an import error, never a
  default" rule.
- `core/bo_driver.py` gains one generic `JsonMode(BOMode)` bound to any spec carrying a
  `geom` block. No new class per line.
- A JSON file claiming an existing Python mode's name is a **hard error**, never an
  override. Silently shadowing `foilsflash` would be a new way to build wrong geometry.
- `graph/state.py`: `mode: Literal[...]` -> `str`. It is a `TypedDict` annotation, erased
  at runtime, so nothing breaks; only `tests/test_modes.py::test_keys_match_state_literal`
  binds it, and it is retargeted to "every spec has a driver".

Existing modes keep their Python renderers in production. Trusting JSON to regenerate a
live campaign's geometry is a change to prove, not to assume.

## 5. File format — one file per optimization job

`modes/<name>.json`, at the repo root beside `leaderboards/`.

```
{
  "name":     "<mode name, must not collide with a Python mode>",
  "note":     "<one-line description>",
  "software": { "musing": "<abs path to setup.sh>",
                "grid_tarball": "<abs path to Code.tar.bz2>" },
  "run": {
    "stages":          ["<ordered stage chain>"],
    "harvest":         "harvest" | "harvest-pot-only",
    "jobs_per_stage":  { "<stage>": <njobs> },
    "presubmit_after": { "<stage>": ["<stage to presubmit>"] },
    "stage_tuning":    { "<stage>": { "events_per_job": N,
                                      "memory_mb": N, "quorum": F } }
  },
  "knobs":     [ {"name": "<knob>", "min": F, "max": F, "fmt": "{:.4f}"} ],
  "int_dims":  [ <indices of integer knobs> ],
  "leaderboard": {
    "file":      "leaderboards/<file>.tsv",
    "columns":   ["<metric columns after the knobs>"],
    "obs_noise": [<sigma axis 0>, <sigma axis 1>],
    "metrics":   { "<column>": ["<summary.json key>", "<fallback>", ...] }
  },
  "preflight": { "fcl": "surfacecheck" | "preflight",
                 "dumps_gdml": B, "verifies_foil_gdml": B,
                 "preserves_gdml": B, "checks_managed_overlap": B },
  "geom":      { ... see below ... }
}
```

`stage_tuning` replaces the hardcoded `if os.environ.get("AUTORESEARCH_MODE") ==
"foilsflash":` block at `core/pipeline.py:273-292`, which mutates the shared `STAGES`
dict with eight tuned numbers reachable only by editing source.

`metrics` maps a leaderboard column to an ordered list of `summary.json` keys, first hit
wins. A list, not a string: real foilsflash falls back
`flash_edep_per_pot -> flash_edep_per_event -> calo_per_pot` so mock/dry-run still work.

### 5.1 The geom block

```
"geom": {
  "base":     "<Offline geom file to #include>",
  "consts":   { "<name>": <number> },
  "derived":  { "<name>": "<expression over knobs and consts>" },
  "profiles": { "<name>": {"count": <n>, "control": ["<knob>", ...],
                           "clip": [<lo>, <hi>]} },
  "lines":    [ ... ]
}
```

Each entry in `lines` is one of:

| Form | Meaning |
|---|---|
| `{"comment": "..."}` | A comment line; `{name:fmt}` placeholders interpolate knobs/derived. |
| `{"key", "type", "value"}` | A fixed assignment. Most lines are these. |
| `{"key", "type", "raw"}` | A fixed assignment rendered as **exact literal text**. |
| `{"key", "type", "fmt", "expr"}` | A scalar computed from knobs. |
| `{"key", "type", "fmt", "segments": [{"count", "expr"\|"value"}]}` | Repeat each segment's value `count` times, concatenated. |
| `{"key", "type", "fmt", "per_index": {"count", "expr"}}` | Evaluate per element; `i` is the index, `n` the count. |

`type` is a simpleConfig type: `bool`, `int`, `double`, `string`, `vector<double>`,
`vector<string>`.

`count` accepts either a literal number or the name of a `consts` entry, so element
counts stay named (`"count": "n_foils"`) rather than repeated as magic numbers. Inside a
segment, `expr` and `value` are interchangeable — `expr` referencing a const is preferred
over a bare literal, so the constant is declared once and cannot drift between lines.

`raw` exists because JSON numbers do not round-trip their literal form. The poison-pill
scalar is written `1.0e6` by the Python renderer, but `json.load` yields the float
`1000000.0`, which renders as `"1000000.0"` — a different string. Ordinary ints and floats
round-trip fine (`3825` -> `"3825"`, `120.0` -> `"120.0"`), so `raw` is only needed where
the exact characters matter. It takes a string and is emitted verbatim, with `type` still
declared for readability.

**Profiles** expand a few control points into a smooth per-index curve, using the same
Lagrange quadratic as `ProdTargetMode._profile` (`bo_driver.py:913-920`): control values
are hit exactly at the start, middle, and end. This matters — control points are in
**physical units**, so bounds mean what they say. With raw polynomial coefficients,
`r1 = -2` yields `r(48) = 50 - 96 = -46 mm`, a crash from a point the optimizer believed
legal.

`clip` is **required** on profiles, not optional. A Lagrange quadratic through in-range
control points can still overshoot between them: `(50, 250, 250)` reaches **275 mm** at
`i ~ 36`. `ProdTargetMode._expand` clips for the same reason (`bo_driver.py:936`).
Clipping projects rather than rejects, so no eval is wasted.

Profiles are referenced from `per_index` expressions by name with an index: `rOut[i]`.
This indexing also makes per-foil knob arrays expressible later, should they be wanted.

## 6. Worked example A — `foilsflash`, as the validation case

The live line, expressed entirely in the schema. Values from `modes.py:165-192`, the
`pipeline.py` tuning block, and `FoilsMode._geom_text` (`bo_driver.py:417-469`).

**The complete file is committed at `tests/fixtures/modes/foilsflash.json`** — this
section shows excerpts, but the fixture is the artifact the acceptance test (§9) loads,
so the target is a real file rather than a description to interpret.

Geometry: 6 upstream extras + 37 pinned base + 6 downstream, via `segments`. Hole radius
is a fraction of that side's outer radius, so it needs `derived`:

```
"consts":  {"n_up": 6, "n_dn": 6, "base_n": 37,
            "base_rOut": 75.0, "base_hT": 0.0528, "base_hole": 21.5},
"derived": {"rIn_up": "extra_f_up * extra_rOut_up",
            "rIn_dn": "extra_f_dn * extra_rOut_dn"},

{"key": "stoppingTarget.radii", "type": "vector<double>", "fmt": "{:.4f}",
 "segments": [{"count": "n_up",   "expr": "extra_rOut_up"},
              {"count": "base_n", "expr": "base_rOut"},
              {"count": "n_dn",   "expr": "extra_rOut_dn"}]},

{"key": "stoppingTarget.holeRadius", "type": "double", "value": 1.0e6},

{"key": "stoppingTarget.holeRadii", "type": "vector<double>", "fmt": "{:.4f}",
 "segments": [{"count": "n_up",   "expr": "rIn_up"},
              {"count": "base_n", "expr": "base_hole"},
              {"count": "n_dn",   "expr": "rIn_dn"}]}
```

The `1.0e6` scalar is a **poison pill**, not a value: an unpatched `StoppingTargetMaker`
ignores the `holeRadii` vector and reads this scalar, and `1e6` forces a loud `G4Tubs`
crash instead of a silently uniform stack. Emitting a "sensible" scalar is exactly how 62
foilsg rows were built with the wrong geometry
(`wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md`). **Any foils-family
JSON mode must ship it.**

**Known fidelity gap:** the Python has three env escape hatches —
`AUTORESEARCH_BASE_HOLE_RADIUS_MM`, `AUTORESEARCH_N_UP`, `AUTORESEARCH_N_DOWN` — used for
one-off experiments such as the no-hole flash A/B. In JSON these become the plain
constants `21.5`, `6`, `6`. Accepted: a new line does not need them, and env-binding is
complexity for a case that has not arisen outside foils.

## 7. Worked example B — `foilsgflash`, a line that does not exist yet

All 49 foils free as smooth profiles, scored on flash vs S/sqrt(B): foilsg's geometry
crossed with foilsflash's objective. Reuses foilsg's z-layout, foilsflash's stages and
objectives, and the same musing and tarball as both. **9 knobs** (three control points
each for radius, half-thickness, hole fraction).

```
"consts":  {"n_foils": 49, "z0": 5871.0},
"derived": {"delta_z": "22.222222 * 36 / (n_foils - 1)"},

"profiles": {
  "rOut": {"count": "n_foils", "control": ["r_up","r_mid","r_dn"], "clip": [50.0, 250.0]},
  "hT":   {"count": "n_foils", "control": ["t_up","t_mid","t_dn"], "clip": [0.002, 1.0]},
  "frac": {"count": "n_foils", "control": ["f_up","f_mid","f_dn"], "clip": [0.0, 0.95]}
},

{"key": "stoppingTarget.z0InMu2e", "type": "double", "fmt": "{:.4f}",  "expr": "z0"},
{"key": "stoppingTarget.deltaZ",   "type": "double", "fmt": "{:.6f}",  "expr": "delta_z"},
{"key": "stoppingTarget.radii",    "type": "vector<double>", "fmt": "{:.4f}",
 "per_index": {"count": "n_foils", "expr": "rOut[i]"}},
{"key": "stoppingTarget.holeRadii", "type": "vector<double>", "fmt": "{:.4f}",
 "per_index": {"count": "n_foils", "expr": "frac[i] * rOut[i]"}}
```

`delta_z` is derived rather than literal: foilsg computes
`22.222222 * 36 / 48 = 16.666666` (`bo_driver.py:674-677`), and a hand-copied
`16.666667` would silently shift every foil.

This is a strictly better line than foilsg: **9 dimensions instead of 12**, with smooth
variation across all 49 foils rather than four piecewise-constant bands — more expressive
geometry in a smaller search space.

## 8. Validation and error handling

Everything is checked **at load**, before any job is submitted, per the `modes.py` rule
that a missing fact is an import error.

- Required fields present; knob/bounds/format counts in lockstep (existing
  `__post_init__`).
- Expressions are **parsed to an AST**, never `eval`'d as text. Permitted: arithmetic
  operators, numeric literals, whitelisted names, and a small function whitelist
  (`min`, `max`, `abs`, `sqrt`). Rejected: attribute access, calls outside the whitelist,
  comprehensions, subscripting other than declared profiles.
- Every name must resolve to a knob, const, derived value, profile, or `i`/`n`. A typo
  like `extra_rout_up` fails at load, naming the file, the geometry key, and the bad name.
- `derived` may reference knobs and consts, not other derived values — acyclic by
  construction, no ordering rules to get wrong.
- Declared `type` must match the value's type.
- Name collision with a Python mode is a hard error.

**Not checkable here:** whether a geometry key exists in Offline. Nothing in this repo can
see Offline's parameter list, so a misspelled `ts.coll5.halfLength` loads fine and is
caught by preflight — the same gate as today, no regression.

## 9. Testing

**Acceptance test.** The target is committed as
`tests/fixtures/modes/foilsflash.json` — a complete reproduction of the live line, whose
spec fields are cross-checked against `modes.SPECS["foilsflash"]` (all 17 facts verified
equal at the time of writing). Render it and the current `FoilsFlashMode._geom_text` at
the same sampled x-points (Sobol, fixed seed) and require the results to agree.

"Agree" means **semantic equality, not byte equality**: parse both outputs into
`key -> value(s)` and require an exact match, including every one of the 49 numbers per
vector at full emitted precision. Byte equality was the original criterion and is the
wrong one — it would force the JSON to reproduce cosmetic alignment (the renderer pads
`stoppingTarget.radii` with ten spaces so `=` lines up with `halfThicknesses`), non-ASCII
comment characters (`120°`, `TT_MidInner→DS2Vacuum`), and an inherited comment header that
calls foilsflash *"foils mode v2, 6D"*. None of that reaches Geant4. The fixture
deliberately writes accurate comments rather than replicating the inherited quirk, since
it doubles as the template someone copies for a new line.

The comparison is defined **at default environment**. `FoilsMode` reads three env
overrides — `AUTORESEARCH_BASE_HOLE_RADIUS_MM`, `AUTORESEARCH_N_UP`, `AUTORESEARCH_N_DOWN`
— which the JSON freezes to `21.5`, `6`, `6` (§6). With any of them set the two diverge by
construction, so the test must clear them rather than inherit the caller's shell.

Repeat the same comparison for `foils` and `prodtarget`, which exercise `segments` and
`profiles` respectively.

Supporting tests: loader rejections (missing field, unresolved name, type mismatch, name
collision), an evaluator test confirming a hostile expression is refused, and profile
expansion against `ProdTargetMode._profile` including the clip path.

The existing 217 tests must stay green — nothing about the six Python modes changes.

## 10. Non-goals

- Does not allow varying a parameter Offline does not already read; that needs a C++
  change, a rebuilt musing, **and** a rebuilt grid tarball (`prodtarget-env-divergence`).
- Does not add new measurements — Tier 3 stays Python in `harvest.py`.
- Does not migrate the six existing modes.
- Does not provide buildability constraints, geom round-trip, or prior seeding.

## 11. Settled decisions

Both remaining questions were resolved on 2026-07-25. Neither is in scope.

- **Per-knob arrays — NO.** `{"name": "rOut", "count": 49, ...}` with `rOut[i]`, giving
  every element an independent knob, is not included. The profile form already varies all
  49 foils; independent knobs would mean 49 x 3 = 147 dimensions against ~4.5 h evals,
  when the widest space this project has run is 12D. Array indexing (`rOut[i]`) still
  exists for referencing profiles, so adding this later is additive, not a redesign.
- **`buildable` expressions — NO.** Rejecting infeasible points stays out. The profile
  form handles the same problem better by projection: `clip` trims an out-of-range value
  instead of discarding the eval, matching `ProdTargetMode._expand`. Revisit only if a
  new line has a constraint that clipping cannot express.
