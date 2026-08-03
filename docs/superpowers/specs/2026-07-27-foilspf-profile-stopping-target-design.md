# foilspf — profile-parameterized all-foils stopping target vs sob + flash

**Status:** design, approved in outline 2026-07-27. No code written.

## Goal

A new BO line that varies **every foil** in the stopping target — outer radius,
thickness, central hole, and overall stack length — instead of the current
`foilsflash` line's fixed
37-foil base plus a ±6-foil extras envelope. Per-foil values come from smooth
profiles in foil index, the same parameterization `bo-prodtarget` uses for the
production target's plates.

Objective is unchanged from `foilsflash`: maximize `S/√B` while minimizing
electron-beam early-flash tracker edep per POT.

## Why

Two independent reasons, both recorded in the wiki:

1. **The 3.91 sob ceiling has survived two picker-driven campaigns**
   (`foilsflash23`, `foilsflash25`, 40 evals, identical settings). Per
   `wiki/concepts/saturation-is-acquisition-relative.md`, a third campaign in
   the same space buys the same negative result. The extras-only envelope is
   the most likely limitation, and it has never been lifted.

2. **The central hole is not currently a knob.** The reconciliation of the
   early foilsflash flash null was that the line "varied the outer envelope,
   not the central hole" (`wiki/external/edmonds-target-hole-docdb10898.md`).
   Edmonds (DocDB-10898) measures a central hole at R ≈ 18–21.5 mm cutting
   beam flash ~30%. A per-foil hole profile puts that lever in the search
   space for the first time.

The 48-eval flash regression supports profiling all three quantities: every
one is significant — `rOut_dn` −0.60, `hT_dn` +0.52, `hT_up` +0.51, `f_dn`
−0.50, `rOut_up` +0.37, `f_up` −0.37.

## Non-goals

- Not a replacement for `foilsflash`. That line keeps its 414 rows and its
  leaderboard untouched.
- Not a retrofit of `foilsg`. That mode optimizes sob + calo on the 4-stage
  Run1B chain; changing both its objective and its parameterization would
  orphan its one clean row for no gain.
- No foil-count knob. `N` is fixed at 49. The thickness profile already spans
  0.25×–3.8× deployed mass, and an integer dimension carries a known failure
  mode (`wiki/incidents/langgraph-checkpoint-numpy-int64.md`).
- No mass constraint. Ruled out in favour of bounds (see "Mass envelope").

## Architecture

### Parameterization

49 foils, spacing uniform but adjustable, stack centre pinned at
`z0InMu2e = 5871`. At the deployed extent of 800 mm this is the same layout as
`foilsg`, so the two lines remain structurally comparable.

Three quantities are Lagrange quadratics in normalized foil index
`u = i/48`, each through control points at `u ∈ {0, 0.5, 1}`. A tenth knob
sets the overall stack length:

| knob group | bounds | clip | deployed value |
|---|---|---|---|
| `rOut_0`, `rOut_1`, `rOut_2` | [50, 120] mm | [50, 120] | 75 |
| `hT_0`, `hT_1`, `hT_2` | [0.01, 0.15] mm | [0.01, 0.15] | 0.0528 |
| `f_0`, `f_1`, `f_2` | [0, 0.95] | [0, 0.95] | 0.287 |
| `extent` | [400, 1100] mm | n/a (scalar) | 800 |

Per foil: `rIn_i = f_i · rOut_i`. Derived: `deltaZ = extent / 48`, so
`deltaZ` spans 8.33–22.92 mm against the deployed 16.666666.

Search dimension is 10, all continuous, no integer dims.

**Why `extent` and not a spacing profile.** Foil gaps are vacuum, so moving
foils changes no muon's material budget — it changes *where along z* muons
come to rest, and hence acceptance. A non-uniform spacing profile (`zVars`,
+3 knobs, 12-D) is feasible as pure config — `StoppingTargetMaker.cc:184`
computes `z_i = offset + (i − n0)·deltaZ + zVars[i]` and reads `zVars` in
**stock** Offline (`:85`, with a repeat-last fill rule; the base geometry sets
it to all zeros). It was rejected because it is **partly degenerate with the
thickness profile**: upstream material density can be raised either by
thickening those foils or by bunching them, so the GP would spend evals
separating two knobs doing overlapping work. A single `extent` knob has no
such overlap — nothing else in the space can change total stack length.

`extent` does **not** affect stack mass (same foils, spread differently), so
the mass envelope below is unchanged by this knob.

Bounds are 0.5×–1.375× deployed. The stack spans `5871 ± extent/2`, i.e.
5321–6421 mm at the widest, well inside the OPA envelope (centre 6250,
half-length 2250). At the shortest extent the foil-surface gap is
`8.33 − 2(0.15) = 8.03` mm, so no overlap is possible at any thickness in
range. The OPA-coupled support-wire calculation at `StoppingTargetMaker.cc:140`
does not apply: it is gated on `foilTarget_supportStructure_endAtOPA`, and this
geometry sets `stoppingTarget.foilTarget_supportStructure = false`.

> **SUPERSEDED 2026-08-02 — this section documents the pre-relocation state.**
> `EMC_Source` was afterwards relocated `5300 → 5000` (one config line;
> `zEMCSourceInMu2e` is a plain `c.getDouble` default — the VD is a 20 µm
> vacuum disc that nothing in the foils family reads), which moves the
> upstream wall from `extent ≈ 1142` to **`extent ≈ 1742`**. After foilspf02
> pinned the 1100 bound, worst-corner preflight measured the real ceiling:
> **1100 / 1400 / 1700 all PASS at zero overlaps; 1800 FAILs** on
> `EMC_Source` vs `StoppingTargetMother` by 3.401 cm. The bound is now
> **1700** (42 mm of margin below 1742, the same convention as the old
> 1100/1142 pair). The table below is retained as the historical record of
> why 1100 was right *at the time*.

**The 1100 ceiling is measured, not round (revised 2026-07-27 from an initial
1200).** `VirtualDetector_EMC_Source` sits at a fixed `z = 5300`; the stack's
upstream edge is `5871 − extent/2`, so it reaches that detector at
`extent ≈ 1142`. Live preflight confirms the boundary sharply:

| extent | upstream edge | overlaps reported |
|---|---|---|
| 1100 | 5321 | **1** — `VirtualDetector_EMC_0_Front` only |
| 1140 | 5301 | 2 — `VirtualDetector_EMC_Source` joins |
| 1200 | 5271 | 2 |

One overlap is exactly what production `foilsflash` carries (`EMC_0_Front`
against `StoppingTargetMother`, at 17.06 cm — larger than anything `foilspf`
produces). Capping at 1100 therefore keeps this line inside the **same
geometry regime the existing campaigns have validated**, instead of letting
the optimizer explore a two-overlap regime nothing in this project has run.

**Zero overlaps is not reachable, and one is the floor (measured 2026-07-27).**
A preflight on a stock probe — same base include, deployed 37 foils, support
structure left ON, zero `stoppingTarget` overrides — reports **114** overlaps:
111 `FoilSupportStructure_*`, 1 `VirtualDetector_EMC_0_Front`, and 1 each of
`NorthRailDS3`/`SouthRailDS3`. `foilspf` reports **1**. The two
"Overlap-suppression" lines in the geometry
(`stoppingTarget.foilTarget_supportStructure = false`, `ds.lengthRail2/3 = 0.1`)
are what remove the other 113.

The survivor cannot be removed **within this Musing**.
`VirtualDetector_EMC_0_Front` is a disk at a fixed `z = 5830`, `r = 454`; the
target is centred at `z = 5871` and so spans 5830 for **any** `extent > 82` mm.
Within Run1Bak, eliminating it would require moving the stopping target off its
real position — changing the physics under study — or deleting a stock Mu2e
detector. This corroborates the characterization already recorded at
`core/bo_driver.py:1602`.

**CORRECTION (measured 2026-07-27): it is NOT inherent to Mu2e — it is fixed
upstream in `SimJob/Run1Bap`, four releases newer than our Run1Bak base.**
An earlier revision of this section claimed the overlap was "present in every
official Mu2e simulation". That is false. Same pure-stock probe, same
surface-check settings, run under each Musing:

| | Run1Bak (our base) | Run1Bap (current) |
|---|---|---|
| overlaps, stock `geom_run1_a.txt` | **117** | **0** |
| volumes surface-checked | 10,496 | 10,495 |
| result | **abort, core dumped** | clean exit, status 0 |

Run1Bap reports 10,495 of 10,495 volumes OK with zero `G4Exception` blocks, so
the check genuinely ran. Our geometry's three suppression layers
(`foilTarget_supportStructure=false`, the `inDS2Vacuum`/`ds2.halfLength` fix,
`ds.lengthRail2/3=0.1`) are therefore **workarounds for a stale Offline whose
stock geometry does not even run**, not general hygiene.

**SECOND CORRECTION (measured 2026-07-28): the stock-vs-stock probe above does
NOT transfer to our geometry.** Swapping Musing alone changes nothing; the
override must be dropped too, and that is only survivable under Run1Bap. Full
2×2, same `foilspf` corner_hi geometry (49 foils @ rOut=120, extent 800), same
surface-check settings, patched `GeometryService` in all four cells:

| Musing | `inDS2Vacuum`/`ds2.halfLength` | overlaps | exit |
|---|---|---|---|
| Run1Bak (live base) | present | 1 — `EMC_0_Front` | rc=0 |
| Run1Bap | present | 1 — `EMC_0_Front` | rc=0 |
| Run1Bak | removed | 6 — incl. `TT_MidInner` | **rc=134, core dumped** |
| Run1Bap | removed | **0** | rc=0 |

The two "present" rows are bit-identical: same log line, same overlapping pair,
same penetration (11.7059 cm), same 937 cases. The mechanism is the ternary at
`constructVirtualDetectors.cc:502,792,840,889,940`, which v13_32_10 changed from
`isDumbbell` to `!tracker.inDS2Vacuum`. With `inDS2Vacuum=true` both evaluate
false, so **our own override pins us to the pre-fix branch** — the upstream fix
only bites when the flag is unset.

Row 3 independently reproduces [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md):
removing the override under Run1Bak resurrects exactly the `TT_MidInner` failure
that motivated it. So the override is mandatory under Run1Bak and counter-
productive under Run1Bap — **Run1Bap has absorbed our hand-maintained
TT_MidInner patch upstream.** Retiring a local workaround is a maintenance win
independent of the overlap count.

Caveat before acting on row 4: `tracker.inDS2Vacuum` is not an overlap knob. At
`Mu2eWorld.cc:346-347` it selects the tracker's mother volume
(`DS2Vacuum` vs `DS3Vacuum`); with `ds2.halfLength=3825` it also extends DS2
toward the MBS. Both mothers are vacuum, so no material moves in the tracker
region — but the objective *is* tracker `StrawGasStep` edep, so dropping the
override is a physics-affecting change owing an A/B on flash edep, not a
geometry-cleanliness decision.

**Migration status (updated 2026-07-28): the rebuild is DONE; adoption is not.**
Stock Run1Bap does not support the per-foil `holeRadii` vector this line depends
on — verified directly, the poison pill fired under stock Run1Bap with
`pRMin = 1e+06, pRMax = 75` (a live confirmation that the pill works as designed
in a genuinely unpatched environment). The patch has since been rebuilt against
Run1Bap at `/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial` — an
mgit-style partial checkout (`GeometryService` only, 2 libs, 26 s, 178 MB;
`rebuild.sh` in that tree is the exact recipe). `StoppingTargetMaker.{cc,hh}`
are byte-identical between v13_12_10 and v13_32_10, so the patch applied with
zero adaptation, and the canary confirms the local library wins over the
backing at runtime.

What remains is **adoption**, which is a physics decision, not a build one:
switching `mode_specs/*.json` `software.musing`/`grid_tarball` means accepting a
**leaderboard discontinuity** — the 414 existing `foilsflash` rows were measured
under Run1Bak, and an Offline release change moves the physics baseline. That is
a scoped piece of work affecting the whole foils family, not a `foilspf`
decision, and it remains out of scope here. Note the overlap argument is NOT a
reason to hurry it: per the 2×2 above, migrating while keeping the override is
geometrically a no-op.

Disabling `VirtualDetector_EMC_Source` was considered and rejected: it treats
the symptom rather than the stack growing into detector space, it diverges
`foilspf`'s geometry from every sibling line for a non-knob reason (undoing
the comparability the 49-foil layout was chosen to preserve), and no one
disabled a detector for the pre-existing `EMC_0_Front` overlap. The honest
caveat behind the conservatism: both overlaps involve **massless** virtual
detectors and G4 calls them warnings, but navigation ambiguity in a region
containing the stopping-target foils could in principle perturb where muons
stop — which is the signal. Production tolerates the existing one by
precedent, not by analysis. That is a reason not to add a second one when
the fix costs 100 mm of a range that was speculative anyway.

**Clipping is load-bearing.** A quadratic through in-range control points
overshoots between them — at these bounds, control `(50, 120, 120)` peaks at
**128.8 mm** near `i=36`, 7.3% above the 120 ceiling. The clip projects the
value rather than discarding the eval, matching `ProdTargetMode._expand`.

**Why the interior node sits at `u = 0.5`.** Node placement does not change
what is reachable — any three distinct nodes span the same space of
quadratics, so moving the interior node only relabels which knob triple maps
to which curve. It does change how far the curve strays outside its bounds
between nodes, and 0.5 minimizes that by a wide margin. Measured worst-case
excursion above a [50, 120] bound, over all in-bounds control points:

| interior node | max value | overshoot |
|---|---|---|
| 0.20 | 176.0 | +46.7% |
| 0.30 | 148.6 | +23.8% |
| **0.50** | **128.8** | **+7.3%** |
| 0.70 | 148.6 | +23.8% |
| 0.80 | 176.0 | +46.7% |

That matters because a clipped knob stops meaning what it says: ask for 120
at the node and an off-centre placement flattens a whole region against the
ceiling. `u = 0.5` is also symmetric, so upstream and downstream get equal
resolution rather than an arbitrary directional bias. Convenient coincidence:
for exactly three points, equispaced nodes **are** the Chebyshev–Lobatto
nodes, so the obvious choice is also the best-conditioned one. This
coincidence breaks at four or more points — equispaced `{0, ⅓, ⅔, 1}` is not
Chebyshev–Lobatto `{0, 0.25, 0.75, 1}` — so a future cubic revision must
choose node positions deliberately rather than inheriting "evenly spaced".

### What the parameterization can and cannot express

Deliberate and worth stating plainly, because it bounds what this line can
ever find. Free per-foil control would be 49 × 4 (radius, thickness, hole,
position) = **196 dimensions**; this design uses **10**. The reachable shape
family per profiled quantity is:

- uniform (all three control points equal — reproduces the deployed-style
  stack and anything `foilsg` could do with a single group)
- monotone ramp (falls out for free when the middle knob is the mean of the
  ends — the quadratic degenerates to a straight line)
- barrel (fat middle, thin ends)
- hourglass (thin middle, fat ends)

**One bend, maximum.** Unreachable: any profile with two or more turning
points, step changes, alternating thick/thin patterns, or "only the first six
foils differ".

Accepted because real targets are smooth, the underlying physics (muon
slowing along z) is smooth, and 196-D is not searchable at ~4.5 h/eval. Note
`foilsg` has the complementary blind spot — its four z-groups express a step
but not a smooth ramp — so neither parameterization dominates.

**Escape hatch, and its trigger.** If champions consistently rail the end
control points or max the available bend, the space is signalling that one
bend is not enough; the response is 4 control points per quantity (12-D,
two bends). That is an engine change, not a spec change — `lagrange_profile`
hardcodes exactly three control points and the schema enforces it — so it is
explicitly out of scope for v0 and should be decided from campaign evidence.

**Every point is buildable.** `f ≤ 0.95` and `f ≥ 0` give `0 ≤ rIn < rOut`
at every index, so there is no rejection region for the GP to model.

### Mass envelope

Aluminium mass of the rendered stack is
`Σ_i π(rOut_i² − rIn_i²) · 2·hT_i · 2.70e-3` grams. Against the deployed
37-foil target at **171.1 g**:

| configuration | mass | vs deployed |
|---|---|---|
| 49 foils at deployed thickness | 226.6 g | 1.32× |
| thinnest, `hT = 0.01` at nominal r/f | 42.9 g | 0.25× |
| `hT = 0.15` at nominal r/f | 643.6 g | 3.76× |
| worst corner `rOut 120, f 0, hT 0.15` | 1795.5 g | 10.49× |

The `rOut ≤ 120` ceiling is what keeps the worst corner bounded; capping
thickness alone does not, because mass scales as `rOut²(1−f²)·hT·N`. With
`rOut ≤ 250` the same thickness cap still admits a 46× corner, and cold-start
Sobol samples the box uniformly, so those corners *would* be visited in round
0 — unlike the warm `foilsflash` line, whose optimizer never went there.

`rOut ≤ 120` is not a meaningful restriction on the useful region: every
`foilsflash` champion sits at rOut 79–120.

A true mass constraint was considered and rejected for v0. It is the
physically correct instrument, but `ModeSpec` has no constraint field —
`is_buildable` exists only on the Python `BOMode` base and is trivially true
for `JsonMode` — so it would cost a spec field plus an override plus tests,
and would make 75–85% of the box infeasible, slowing cold start. Revisit if
results show the optimizer pushing against the `rOut`/`hT` ceilings together.

### Implementation: one JSON file, zero Python

`core/geom_template.py` already ships everything required:

- `lagrange_profile` (`:100`) — the K=3 quadratic with clipping. Its docstring
  states it mirrors `ProdTargetMode._profile`.
- `GeomTemplate.from_dict` accepts a `profiles` block with full
  namespace-collision validation against knobs, consts, and derived names.
- `compile_expr` explicitly permits `ast.Subscript` **only** on declared
  profile names, so `f_p[i] * rOut_p[i]` is expressible and a subscript on a
  scalar is rejected at load with a file+key locator.
- 12 unit tests in `tests/test_geom_template.py` cover the profile path.

No shipped spec or fixture currently declares a profile, so this will be the
first production use of that code path. That is the reason for the staged
validation below, not a reason to write Python instead.

The spec is `mode_specs/foilspf.json`, modelled on `mode_specs/foilsflash.json`.
Geometry block:

```json
"derived": {
  "deltaZ": "extent / 48"
},
"profiles": {
  "rOut_p": {"count": 49, "control": ["rOut_0","rOut_1","rOut_2"], "clip": [50, 120]},
  "hT_p":   {"count": 49, "control": ["hT_0","hT_1","hT_2"],       "clip": [0.01, 0.15]},
  "f_p":    {"count": 49, "control": ["f_0","f_1","f_2"],          "clip": [0, 0.95]}
},
"lines": [
  {"key": "stoppingTarget.deltaZ",          "type": "double",
   "expr": "deltaZ",                                            "fmt": "{:.6f}"},
  {"key": "stoppingTarget.radii",           "type": "vector<double>",
   "per_index": {"count": 49, "expr": "rOut_p[i]"},           "fmt": "{:.4f}"},
  {"key": "stoppingTarget.halfThicknesses", "type": "vector<double>",
   "per_index": {"count": 49, "expr": "hT_p[i]"},             "fmt": "{:.6f}"},
  {"key": "stoppingTarget.holeRadius",      "type": "double", "raw": "1.0e6"},
  {"key": "stoppingTarget.holeRadii",       "type": "vector<double>",
   "per_index": {"count": 49, "expr": "f_p[i] * rOut_p[i]"},  "fmt": "{:.4f}"}
]
```

`stoppingTarget.holeRadius = 1.0e6` is the **poison pill** and must stay
`raw`: JSON's number grammar would render it `1000000.0`. It makes an
unpatched grid binary crash loudly instead of silently building a uniform-hole
stack — the exact failure that tainted all 62 `foilsg` rows
(`wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md`).

All remaining geometry lines are copied verbatim from `foilsg`'s render, which
is the validated stopping-target-replacement geometry:

**`stoppingTarget.deltaZ` is NOT in this list** — it is knob-derived and
emitted by the `expr` line above. Emitting it here as well would put the same
key on two lines, where last-write-wins silently decides the geometry: the
constant would override every `extent` the optimizer picked, and every eval
would run at 800 mm while the leaderboard recorded the knob it never used.
An implementation-time check should assert no key is emitted twice.

```
#include "Offline/Mu2eG4/geom/geom_run1_a.txt"
bool   hasTSdA = false;
bool   tsda.helical.build = false;
double stoppingTarget.z0InMu2e = 5871.0000;
bool   degrader.build = false;
double degrader.rotation = 120.0;
string ts.coll5.material1Name = "COL5Poly";
bool   tracker.inDS2Vacuum = true;
double ds2.halfLength = 3825;
bool   ds.hasServicePipes = false;
bool   stoppingTarget.foilTarget_supportStructure = false;
double ds.lengthRail2 = 0.1;
double ds.lengthRail3 = 0.1;
```

### Run configuration

Identical to `foilsflash` except the leaderboard:

| field | value |
|---|---|
| `grid_stages` | `mubeam`, `mustops_ce`, `elebeam_flash` |
| `presubmit_after` | `{"mubeam": ["elebeam_flash"]}` |
| `grid_tarball` | `Code_helical_holeradii.tar.bz2` (**required** — carries the `holeRadii` patch) |
| `musing` | `Offline_helical/setup_local.sh` |
| `preflight_fcl` | `surfacecheck` |
| `metric_cols` | `sob`, `flash_edep`, `alpha`, `obj` |
| `obs_noise` | `(0.006, 0.01)` |
| `stage_tuning` | as `foilsflash` (mubeam 200000 ev/job, mustops_ce 75000, elebeam_flash 110000; memory 2000 MB; quorum 0.8) |
| `leaderboard_rel` | `leaderboards/leaderboard_bo_foilspf.tsv` (new, empty) |

### Cold start

The 414 `foilsflash` rows are in the 6D extras-only space and are **not**
transferable to this 10D profile space. `load_priors()` returns empty and the
GP starts cold: round 0 is Sobol. Budget ~20 evals before results are
meaningful. This is inherent to changing the parameterization, not a defect.

`extent` is the one knob whose effect can be read almost immediately: it is
uncorrelated with the three shape families, so even the Sobol round should
show whether stack length moves `sob` or `flash` at all.

## Validation

Staged, cheapest first. **No campaign until all four pass.** This mirrors the
`ffjson01` sequence that de-risked the JSON-mode switchover.

1. **Unit tests** (`tests/test_mode_json.py`, no grid):
   - 49 elements emitted for each of `radii`, `halfThicknesses`, `holeRadii`.
   - Deployed-equivalent control points (all three equal to 75 / 0.0528 /
     0.287) render `rOut 75.0000`, `hT 0.052800`, `holeRadii 21.5250` at
     every index.
   - Clip engages: control points that overshoot between nodes produce values
     at the clip bound, never beyond.
   - `rIn_i < rOut_i` at every index across the corner set.
   - The poison pill renders exactly `1.0e6`, not `1000000.0`.
   - `extent = 800` renders `stoppingTarget.deltaZ = 16.666667`; the bound
     values 400 and 1100 render 8.333333 and 22.916667.
   - **No geometry key is emitted twice** — scan the render for duplicate
     keys. `deltaZ` is the live hazard: a leftover constant would silently
     override the `extent` knob and pin every eval at 800 mm.
   - `foilspf` appears in `SPECS` and is a `JsonMode`.
2. **Local G4 preflight** (`mu2e -n 1`, surface-check FCL) on five renders:
   deployed-equivalent, both extreme shape corners, and — because `extent` is
   the one knob that moves foils rather than resizing them — the shortest and
   longest stack at deployed shape. Expect PASS with no `GeomSolids`/`GeomNav`
   errors.
3. **One grid eval** — `--q 1 --max-rounds 1` under an isolated leaderboard
   path and a fresh name-prefix. Success criteria: preflight PASS carrying
   the patched-lib canary `holeRadii vector active (n=49)`; a row lands with
   non-zero `sob` **and** non-zero `flash_edep`.
4. **Campaign** — 20 evals, `--picker hybrid --q 10 --rolling --max-evals 20`,
   elebeam at the default 100 jobs (no `ELEBEAM_NJOBS` override), checkpoint
   off CephFS under `/tmp/oksuzian/<prefix>`.

## Success criteria

The line succeeds if, within its first 20 evals, it produces **either**:

- a row above sob 3.91 — the extras-only ceiling was a parameterization limit; or
- a Pareto point dominating any current front member — the richer geometry buys
  front area even without a new champion.

If it does neither, that is a real result: the ceiling is a property of the
stopping-target physics, not of the search space, and the flash axis is where
remaining effort belongs.

## Risks

| risk | mitigation |
|---|---|
| Profile code path never used in production | Staged validation 1–3 before any campaign spend |
| Grid tarball lacks the `holeRadii` patch | Poison pill crashes loudly; canary checked in validation 3 |
| Cold start wastes evals | Accepted and budgeted; inherent to a new space |
| Thick/large corners fail G4 | Bounds capped at 10.5× deployed mass; preflight on corners in validation 2 |
| GP mis-scaled across 3 knob families | `obs_noise` carried from `foilsflash`; inputs normalized by existing picker code |

## Open questions

- Is there a real Mu2e stopping-target mass budget? If one exists, it belongs
  here as a constraint and would change the bounds decision above.
- Is there an acceptance-driven limit on stack length that should tighten
  `extent`'s [400, 1100] range? The ceiling is set by the EMC_Source clearance
  (OPA envelope, foil-overlap) and 0.5×–1.5× of deployed, not from a
  stopping-distribution or tracker-acceptance argument. If the campaign rails
  `extent` to either bound, that is the question to answer before widening it.
- Non-uniform spacing (`zVars`, +3 knobs) is deliberately deferred, not
  blocked — it is expressible in stock Offline today. Revisit only if `extent`
  turns out to be a strong lever, since a spacing *profile* overlaps the
  thickness profile and should not be bought before the cheap version pays.
