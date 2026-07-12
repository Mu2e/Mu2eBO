# TSdAHelicalTube tessellated solid — negative cubic volume (self-intersection)

**Type:** incident
**Status:** resolved (source fix landed 2026-05-20: stacked G4TwistedBox analytic primitive; grid tarball repackage still pending)
**Updated:** 2026-05-27 (TWB02/03/04 A/B envelope: twist systematically -5–7% sob, -1–12% calo across BO space)

## Summary
`G4TessellatedSolid::SetSolidClosed()` issues `G4Exception : GeomSolids1001`
on the `TSdAHelicalTube` solid: *"negative cubic volume, please check
orientation of facets!"* — the message blames facet orientation, but static
analysis of `makeHelicalPlug` shows the winding is **correct** for all 8 side
triangles + 2 end caps (right-hand rule produces outward normals). The real
cause is **per-slice broad-face warp**: each tessellated slice's two ±x broad
faces are non-planar quads (twist accumulates linearly along the slice's
axial extent), and G4 splits each non-planar quad into two triangles using a
fixed diagonal. At extreme aspect ratios (helical050a: `dy/dx = 1044`) the
warp height exceeds the plate thickness and the two triangles representing
the +x face cross *through* the two triangles representing the −x face
*within the same slice*; G4's divergence-theorem volume integral double-counts
the self-overlap with reversed sign → net negative volume (~32.1 vs ~18 cm³
intended → ~80% mass inflation in every grid job built with this lib). G4
still constructs the solid but its internal navigation produces a flood of
`GeomNav1002` "Stuck Track" warnings during tracking. Discovered 2026-05-20
in helical050a worker logs; preflight surface-check passed because it
validates sibling overlaps, not internal self-intersection.

## Key facts
- **Warning text:**
  `Defects in solid: TSdAHelicalTube - negative cubic volume, please check
  orientation of facets!` issued by `G4TessellatedSolid::SetSolidClosed()`.
- **Cascading effect:** 1× GeomSolids1001 per worker at construction →
  thousands of GeomNav1002 "Stuck Track" / "Likely geometry overlap" per
  worker during event tracking. helical050a totals (see
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/helical050a/scan_logs/report.tsv`):
  ~28.5M GeomNav1002 events across mubeam + run1b_mubeam + mustops_ce.
  Stuck-track position `(-3925.8, -0.59, 4569.0)` (r≈22 mm, z=4569 → deep
  inside plug, not at the disc-face boundary).
- **Hit rate:** GeomSolids1001 fires in **197/200 mubeam workers, 199/200
  run1b_mubeam, 90/98 mustops_ce** for helical050a — near-100% across every
  worker that constructs the plug. Concat is unaffected (no G4).
- **Why preflight missed it:**
  - `g4.doSurfaceCheck=true` (wired in task #52) validates *sibling*
    geometric overlap, not facet winding inside a single solid.
  - Preflight scans for "Overlap" lines only; "negative cubic volume" is a
    warning, not an error, and `mu2e -n 1` exits 0.
- **Source location:** `makeHelicalPlug()` in
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:59-129`.
  Builds the solid as `nSteps` stacked twisted slices; each slice contributes
  8 triangular side facets + (at the ends) one quad cap. Vertex order verified
  at `angle=0`: front -ŷ, right +x̂, back +ŷ, left -x̂, bottom -ẑ, top +ẑ —
  all outward. **Winding is not the bug.**
- **Real cause — per-slice broad-face warp (corrected 2026-05-20).** Each
  slice's ±x faces are non-planar quads because the cross-section rotates
  linearly along the slice's axial extent. G4 splits each non-planar quad
  into two triangles using a fixed diagonal; the diagonal pair is offset
  from the true ruled surface by a warp height that scales as
  `warp ≈ dy · (angle/N) · (1/4)` where `N = nsteps`. For helical050a
  (`dy=109.6, angle=459.6° → 8.02 rad, N=100`) that's `warp ≈ 712/N mm
  = 7.12 mm`, dwarfing the plate thickness `2·dx = 0.21 mm`. The +x
  triangle-pair and −x triangle-pair therefore cross each other *within the
  same slice*. Same mechanism causes the divergence-theorem volume integral
  to over-count: actual integrated volume ≈ 32.1 cm³ vs intended ~18 cm³ —
  about an **80% mass inflation** in every grid job built with the broken
  lib.
- **Predicate (corrected):** crossover when warp ≈ `2·dx` (plate thickness):
  `N_crit ≈ dy · angle_rad / (8 · dx)`. For helical050a: `N_crit ≈ 3390`.
  Below ~3400 the solid self-intersects; above it does not. The original
  default `nsteps=100` and the empirical mitigation `nsteps=500` are both
  well below this threshold, which is why both produce GeomSolids1001.
  `nsteps=5000` would have been sufficient (no source patch needed), but at
  ~50× the facet count it is not the chosen fix.
- **Direction of bias on calo_per_pot — INVERTED from initial hypothesis
  (measured 2026-05-21).** End-to-end A/B at fixed helical050a x-point, OLD
  tessellated lib both sides, only `nsteps` differs:

  | build | calo_per_pot | s_over_sqrt_b | obj |
  |---|---|---|---|
  | helical050a (broken, n=100) | 2.54e-6 | 3.21 | 2.96 |
  | helical050a_n5000 (clean, n=5000) | **1.09e-5** | 3.65 | 2.56 |

  Clean geometry produces **4.3× higher** calo_per_pot, not lower. The
  earlier "40× vs legacy helical050" comparison was misleading — that
  contrasted against a *different* x-point (pre-Option-A render), not the
  same geometry under a different build. Real direction: the broken plug
  was **masking** calo background, not inflating it.
- **Mechanism (corrected):** the 27M-per-worker `Stuck Track` events at the
  defective plug effectively **kill background particles** before they reach
  the calo — G4 absorbs anything that gets stuck. With clean geometry, those
  particles correctly propagate downstream and deposit energy in the calo,
  raising calo_per_pot ~4×. So the broken plug is a spurious absorber, not
  a spurious scatterer-into-calo.
- **Leaderboard implication:** many low-calo helicalNNN winners on the
  pre-fix leaderboard are likely **artifacts of stuck-track absorption** in
  the broken plug. Their true calo_per_pot is substantially higher. The
  retroactive sweep needs to re-evaluate all rows; rankings will shift.
- **Upstream physics impact — mubeam yield inflation (measured 2026-05-21).**
  The broken plug doesn't just dirty downstream stages; both mubeam stages
  themselves are affected because backsplash/stuck-tracks at the TSdA
  produce spurious TargetStops. Full-stage A/B from worker `TrigReport`
  blocks (200 workers × 5000 events per build per stage):

  | stage | DS field | broken (n=100) | clean (n=5000) | inflation |
  |---|---|---|---|---|
  | `mubeam` (Run1A) | **on** | 741.8 / 5000 (14.84%) | 539.6 / 5000 (10.79%) | **+37.5%** |
  | `run1b_mubeam` (Run1B) | **off** | 16.0 / 5000 (0.32%) | 10.8 / 5000 (0.22%) | **+48.0%** |

  Both DS configurations biased high; **DS-off hit relatively harder** because
  real stops drop ~70× when the focusing field is off, so backsplash/stuck-track
  noise is a larger fraction of the signal. This is the physical channel by
  which downstream calo_per_pot inflation gets seeded — every downstream stage
  consumes biased TargetStops products from both upstream paths.
  - Implication: any pre-fix helicalNNN row's mubeam *and* run1b_mubeam yields
    are biased, not just its calo. The retroactive sweep needs to flag mubeam
    impact too, not just scan_logs warnings.

## Workflow detection (landed 2026-05-20)
End-of-workflow `scan_logs` node in [[graph-runner]] (between `harvest` and
`evaluate`) walks every worker `.log` under each stage's outstage dir and
counts:
- G4Exception, Stuck Track, Likely geometry overlap, GeomSolids1001,
  GeomNav1002, Error, Warning, FATAL, SEGV
Writes `<grid_root>/<config_name>/scan_logs/report.tsv` + `report.json`.
**Report-only** — never gates evaluate; the leaderboard row is still written
so historical context is preserved. Existing in-flight chains (graph022/023/024,
helicalL01-L05, H1/H2, yellow-star re-evals) compiled the old topology in RAM
at startup and are unaffected; only freshly-launched `python -m graph.run`
invocations include the scan.

## Fix landed (2026-05-20)

**Replaced tessellated chord construction with stacked analytic G4TwistedBox.**
`makeHelicalPlug` in `constructTSdA.cc` now computes
`N = ceil(|angle| / 85°)` segments along z, each a `G4TwistedBox` of axial
extent `2·halflength/N` and twist `angle/N`, combined via `G4UnionSolid`
(segment 0 wrapped in `G4DisplacedSolid` so the assembly's local origin sits
at the geometric midpoint). The 85° cap stays under `G4VTwistedFaceted`'s hard
~90° per-solid twist limit; consecutive segment faces are matched by per-segment
z-rotation `phi_i = -angle/2 + (i+0.5)·angle/N`. No facets, no chord crossings,
no `tsda.helical.nsteps` knob.

**Empirical mitigations that did NOT work:**
- `tsda.helical.nsteps=500` (5× the default 100) — still produces
  `GeomSolids1001` for helical050a. Per the corrected mechanism above the
  crossover is at `N_crit ≈ 3390`; 500 is well below. `nsteps ≥ 3400`
  would in fact eliminate the warning without a source patch, but at
  ~50–100× the facet count (slower G4 navigation, much larger GDML), so
  the stacked-twistedbox source fix is preferred.

**Alternate mitigation that DOES work (empirically verified 2026-05-21).**
Local-muse preflight A/B at fixed helical050a knobs, broken-tessellated lib
swapped in via `git`-snapshot revert (`/exp/mu2e/app/users/oksuzian/autoresearch_muse/.snap/_scheduled-2026-05-20-00_00_02_UTC_*/Offline/Mu2eG4/src/constructTSdA.cc`)
+ explicit-target `muse build`:

| nsteps | lib | solid reported | GeomSolids1001 | surface-check |
|---|---|---|---|---|
| 100  | OLD tessellated | `G4TessellatedSolid` | **2** | OK |
| 5000 | OLD tessellated | `G4TessellatedSolid` | **0** | OK |
| 100  | patched twistedbox | `G4UnionSolid` (6 twistedbox segs) | **0** | OK |

Confirms the predicted `N_crit ≈ 3390` boundary: n=5000 with the OLD code is
sufficient to eliminate the construction defect, no source patch needed. We
nonetheless ship the twistedbox patched lib on grid (smaller GDML, faster
nav). The n=5000 alternative is kept as a fallback in case G4 navigation ever
misbehaves on twisted-prism solids for a future material/version.
- Naive single `G4TwistedBox` (pre-stacking) — analytic, no facet bugs, but
  G4 throws `GeomSolids0002 — twist angle too big` for any total twist > π/2.
  BO search space allows angle ∈ [60, 540]°, so this would have restricted
  exploration.

**Verification (helical050a, angle=459.591°):**
- N=6 segments expected; GDML confirms 6 `<twistedbox>` + 0 `<tessellated>`
- 4 `TSdAHelicalAsm_*` intermediate union solids + final `TSdAHelicalTube`
- mu2e exit 0, zero G4Exception, zero GeomSolids errors
- Per-segment seg_twist = 459.591/6 = 76.6° ✓ inside the 85° margin

**Major preflight caveat discovered while debugging.** `cmd_preflight` in
`autoresearch_bo_michael.py:684` only sources the CVMFS MUSING (line 724)
— it never loads the patched `libmu2e_Mu2eG4.so`, so the helical plug is
constructed using the **stock** Offline code, not the patched code. Until
preflight is taught to source the local muse setup (or `Code/setup.sh` from
the shipped tarball), preflight cannot detect helical-plug bugs. See
[[preflight]] for the limitation.

**Build gotcha discovered.** `muse build Offline` reports "up to date"
without re-linking the changed lib (it stops at the package target).
Targeting the .so explicitly works: `muse build build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so`.
See [[muse-backing-pattern]].

**Outstanding:** repackage `Code_helical_base.tar.bz2` (task #53) so grid
workers pick up the patched lib. Until then, grid jobs still run the broken
tessellated path.

**Default flipped (2026-05-21):** `HelicalMode.HELICAL_NSTEPS` 100 → 5000
(autoresearch_bo_michael.py:328). The production `Code_helical_base.tar.bz2`
is the OLD tessellated lib (swapped in for the helical050a_n5000 test on
2026-05-21, not yet swapped back). At the old default of 100 the OLD lib
floods GeomSolids1001 + 28M GeomNav1002/worker; nsteps=5000 is above
N_crit≈3390 and produces zero hits.

**Lowered again 5000 → 2000 (2026-05-21 evening).** SR00_00 (`dx=0.011,
dy=125, halflen=251, angle=167`, N_crit≈4144) was buildable under the
5000 ceiling but reproduced the GeomSolids1001 flood end-to-end: 186/200
mubeam jobs, 195/200 run1b_mubeam, 90/100 mustops_ce flagged; 6.66 M
exceptions + 2.22 M stuck tracks in mustops_ce alone. summary.json
reported inflated sob=3.88, calo=1.42e-5; scan_logs gate wrote
broken.txt and suppressed the leaderboard append. The N_crit≈3390
boundary from the n=5000 sweep above was measured on a single geometry
(helical050a); SR00_00 shows the boundary moves with (dy, halflen, angle)
and is not safely captured by any single nsteps value within the
buildable budget. Empirical: at 2000 the closed loop wastes less CPU
on doomed picks; this is *defensive*, not a proof that 2000 is safe.
Co-equal with `--nsteps-budget 2000` in `closed_loop` (drift between
the two reopens the propose-loop hole). See [[bo-helical]] "N_crit
margin too loose" and [[closed-loop-bo-design]].

## A/B grid test at sub-N_crit knobs (2026-05-26)
End-to-end grid A/B at helical041a knobs (`dx=0.57, dy=110, halflen=246,
angle=538.77` → N_crit ≈ dy·rad(angle)/(8·dx) ≈ 227, well under nsteps=2000)
via the FCL-selectable dispatcher (`tsda.helical.useTwistedBox`):

| config | sob | calo | obj | scan_logs |
|---|---:|---:|---:|---|
| helicalTWB01_tess  (useTwistedBox=false) | 2.91 | 6.55e-6 | 2.25 | 0 GeomSolids1001, 0 LikelyGeomOverlap |
| helicalTWB01_twist (useTwistedBox=true)  | 2.71 | 6.49e-6 | 2.06 | 0 GeomSolids1001, 0 LikelyGeomOverlap |

Tess vs twist agree within ~7% on sob and ~1% on calo at sub-N_crit angles
— confirms twisted-box is a faithful replacement when tessellated is in its
buildable regime. Both branches show only ~2 generic Errors/log (background
noise, not geometry).

## A/B dispatch knob (env-var override)
`HelicalMode.HELICAL_USE_TWISTED_BOX` at `autoresearch_bo_michael.py:377`
reads `os.getenv("USE_TWISTED_BOX", "1") != "0"`. To run an A/B without
editing the class constant, set the env var **in the parent shell of the
graph.run invocation** — it's read once at module import:

```bash
USE_TWISTED_BOX=0 .venv-graph/bin/python -m graph.run \
  --mode helical --no-mock --config-name helicalFOO_tess \
  --x-point dx,dy,hl,angle  # emits useTwistedBox = false
USE_TWISTED_BOX=1 ... --config-name helicalFOO_twist  # emits true
```

Verify the right value landed via `grep useTwistedBox
<grid>/<config>/geom/autoresearch_<config>_geom.txt`. Default of `1` matches
the deployed lib and the C++ dispatcher default — unsetting the var anywhere
in the chain still resolves to twisted-box.

## A/B envelope across BO space (TWB01–04, 2026-05-27)
4 clean-vs-clean pairs spanning the buildable sub-N_crit envelope of the
4D BO search box (dx∈[0.01,5], dy∈[40,400], hl∈[25,500], angle∈[60,720]):

| pair | (dx,dy,hl,angle) | N_crit | sob tess→twist | Δsob | calo tess→twist | Δcalo |
|---|---|---:|---|---:|---|---:|
| TWB01 | (0.57, 110, 246, 539) | ~138 | 2.91 → 2.71 | −6.9% | 6.55e-6 → 6.49e-6 | −0.9% |
| TWB02 | (1.5, 120, 300, 150)  | ~26  | 1.80 → 1.72 | −4.4% | 6.33e-6 → 5.91e-6 | −6.6% |
| TWB03 | (0.8, 200, 250, 400)  | ~218 | 2.65 → 2.46 | −7.2% | 9.26e-6 → 8.68e-6 | −6.3% |
| TWB04 | (0.3, 150, 200, 600)  | ~654 | 3.72 → 3.46 | −7.0% | 1.49e-5 → 1.31e-5 | −12.2% |

**Systematic bias direction: twist is uniformly lower** on both sob (−5 to
−7%) and calo (−1 to −12%) across all 4 pairs. Not MC noise — every pair
agrees on sign in both metrics. Hypothesis: tessellated representation has
residual facet-edge wrinkles (sub-N_crit warp is < plate thickness but not
zero), and those wrinkles scatter slightly more than the analytic ruled
prism, biasing both sob (more downstream particles per stop) and calo
(more energy deposited downstream). The largest Δcalo (−12% at TWB04,
dx=0.3 mm, the thinnest plate) is consistent with this — thinner plates
have less material to absorb the extra-scattered tracks before they reach
the calo.

**Bias enters at mustops_ce, not mubeam — kCarTolerance-halo mechanism (2026-05-27)**:
Per-stage harvest dissection of TWB01/02/03 (clean A/B pairs only — TWB04
excluded per below) from `summary.json` fields:

| pair | mubeam stopping_factor tess/twist | mustops_ce ce_seen/sim tess/twist |
|---|---:|---:|
| TWB01 | 0.978 (twist wins, ±2%) | **1.050** (tess +5%) |
| TWB02 | 1.008 (≈equal) | **1.031** (tess +3%) |
| TWB03 | 0.968 (twist wins, ±3%) | **1.062** (tess +6%) |

Bulk muon stopping (mubeam) is statistically indistinguishable across the
3 pairs (sign flips). The systematic bias appears entirely at
**mustops_ce**: tess returns 3–6% more CE-stage hits per simulated event
in every pair, with same sign. This propagates into both sob (+4.7 to
+7.7%) and calo (+0.9 to +7.1%) at the final harvest step. Source files:
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/harvest/summary.json`
(schema in [[pipeline]]).

**Most likely mechanism (3-agent investigation, agent transcripts in
session log)**: `G4TessellatedSolid::Inside()` declares a point on-surface
within `kCarTolerance` of *any* facet. With N triangular facets
approximating a curved twisted surface, the on-surface band is a *union*
of N planar slabs whose outer envelope sits outside the smooth ideal
surface by the facet chord sagitta. Analytic `G4TwistedBox` resolves the
curved boundary to one thin sheet. Net effect: tessellated representation
has a slightly thicker effective material at grazing angles → more late
CE candidates pass through it → higher mustops_ce hit rate. Secondary
contributor: `G4TwistedBox` stacked via `G4UnionSolid` (N=ceil(|angle|/85°)
segments) creates internal seams that force boundary-step truncation; tess
single-mesh has no such seams. Shorter steps → smaller Moliere deflections
→ fewer captures on twist side. Together these predict tess > twist in
both metrics, surface-effect dominant (matches Δcalo > Δsob magnitude on
TWB02/03 and the per-stage signature). **This supersedes the earlier
"facet-edge wrinkle" hypothesis** — wrinkles would have biased mubeam too,
which the data rules out.

**Operational consequence**: cross-implementation comparison of any pre-
2026-05-21 tessellated-era leaderboard row vs post-2026-05-21 twisted-
box-era row is biased by ~3–6% at mustops_ce ≈ ~5–7% sob ≈ ~1–7% calo.
If a future champion is selected from cross-era data, re-run it under
both branches to remove the bias.

**TWB04_tess is polluted — overlap, not wrinkle (2026-05-27 follow-up)**:
scan_logs report shows TWB04_tess has **29,361 LikelyGeomOverlap** + 29,361
GeomNav1002 + 29,361 StuckTrack across mubeam/mustops_ce/run1b_mubeam,
while TWB04_twist (and TWB01/02/03 tess) all have 0. TWB04 sits below
N_crit (~654 vs nsteps=2000) so no GeomSolids1001 fires (no facet
self-intersection), but the thinnest plate (dx=0.3 mm) at angle=600°
still produces a navigation pathology in tess that twist is immune to.
The TWB04 row in the A/B envelope above is **broken-geometry tainted**
(would trip `_is_broken` LikelyOverlap>100 gate); its −12% Δcalo is the
overlap signal, not wrinkle scatter. TWB01/02/03 remain clean A/B pairs.
**Operational consequence**: N_crit is necessary-but-not-sufficient for
tessellated correctness — even below N_crit, thin-plate × high-angle
configs can produce thousands of overlaps. Treat any tess-era leaderboard
row in this corner as suspect until scan_logs confirms zero overlap.

**Why Δsob is stable (−5/−7%) but Δcalo is variable (−1 to −12%)**: sob
counts CE-region stops, which are bulk-volume dominated — the facet-edge
extra-scatter contribution is a small constant fraction of the dominant
volume-scatter rate, so it lands at a consistent percent across pairs.
Calo counts late/wide energy adjacent to stuck-tracks, which is
surface-grazing dominated — the same facet-edge mechanism here is the
*main* contribution rather than a small perturbation, so its magnitude
swings with plate geometry (thinnest plate TWB04 dx=0.3 mm shows the
biggest −12% delta). Useful diagnostic: if a future implementation change
moves Δsob and Δcalo by similar fractions it's a bulk effect; if Δcalo
moves while Δsob stays put, it's a surface effect.

**Leaderboard implication**: the ~5–7% sob bias is comparable to MC noise
on a single config but is **systematic**, so cross-config comparisons
between tessellated-era rows and twisted-box-era rows on the leaderboard
are biased — twisted-box rows look ~5–7% worse on sob and ~5–10% lower on
calo than they would have under tessellated. Pareto ordering between the
two eras should be interpreted with this in mind. (Mitigation: when the
final champion is chosen, re-evaluate it under both branches to remove
the cross-implementation bias.) See [[bo-helical]] Open questions.

## Twisted-box clean at extreme angle (FT08, 2026-05-26)
3 closed-loop FT08 children built with `useTwistedBox = true` (deployed
default), all four stages scanned (mubeam + run1b_mubeam + concat +
mustops_ce, ~560 worker logs each):

| child | dx | dy | hl | angle | N_crit if tess | GeomSolids1001 | LikelyOverlap | Stuck |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FT08R00_00 | 0.013 | 147 | 44 | 706 | ~17,400 | 0 | 2 | 2 |
| FT08R00_01 | 0.028 | 92 | 375 | 712 | ~3,590 | 0 | 1 | 1 |
| FT08R00_03 | 2.67 | 67 | 160 | 481 | ~17 | 0 | 2 | 2 |

R00_00 is the strongest evidence: tessellated N_crit ~17,400 is far above
any practical `nsteps` budget (current ceiling 2000); twisted-box builds
the analytic ruled prism with zero facet-orientation errors. The 1–2
overlap/stuck counts per child are the single-event background floor
(see [[scan-broken-codes-too-narrow]] subthreshold pattern), not a
geometry pathology — well below OVERLAP_THRESHOLD=100, and `_is_broken`
passes all three. Prior verified-clean A/B was at angle=538° (helicalTWB01);
this extends the empirical envelope to angle ≥ 700° at extreme aspect
ratios. Conclusion: twisted-box is the correct default across the full
BO search space; tessellated remains only useful for legacy reproductions
within its buildable regime.

**Champion regime is an artifact, not a real signal.** Neither A/B branch
reproduces the original helical041a leaderboard metrics (sob=3.13,
calo=2.97e-6). Both reproductions sit at calo ~6.5e-6 — **2.2× higher than
the leaderboard row**. Combined with the retro-scan finding that the
original helical041a logged 24M LikelyGeomOverlap + 478 GeomSolids1001 hits
across every stage (see [[scan-broken-codes-too-narrow]] retro-scan table),
this is direct evidence that the helical041a "top-3 champion" was a
stuck-track-absorption artifact under broken tessellated geometry. The
same conclusion likely applies to helicalL02 and graph023 (the other two
retro-scan-broken champions in the same regime).

## Upstream-table contamination
- mmackenz `table.org` rows that use the helical plug are also built with the
  broken tessellated lib (e.g. **v113**, added 2026-05-20, *"2.50 cm Al plate
  with 80 mm hole, optimized helical plug"*, sob=2.96, calo=8.52e-8). The
  artificially-low calo is the same stuck-track-absorption artifact as the
  pre-fix helicalNNN leaderboard rows. The overlay script
  `overlay_gp_predictions_helical_mpl.py` blacklists these entries via
  `TABLE_BLACKLIST` so they don't pollute the visualization.
- New mmackenz helical-plug table rows should be added to the blacklist (or
  the underlying mmackenz workflow must rebuild against the patched lib)
  before being trusted as ground-truth.

## Cross-links
- Related: [[graph-runner]], [[tsda]], [[tsda-disc-helical-sibling-overlap]],
  [[mu2e-overlap-check]], [[preflight]], [[prodtarget-spacer-supportring-overlap]], [[scan-broken-codes-too-narrow]]
- Source: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:58-128`
- Detection: `graph/pipeline_io.py:scan_worker_logs`, `graph/nodes.py:node_scan_logs`
- Sample report: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/helical050a/scan_logs/report.tsv`

## Side-by-side GDML evidence
Two `gdmldump` outputs in `/exp/mu2e/app/users/oksuzian/autoresearch/gdml_dumps/`
make the fix visually inspectable (helical050a params, identical inputs):
- `mu2e_helical050a_tessellated.gdml` (4.9 MB) — old `Code_helical_base.tar.bz2`
  lib (LD_PRELOAD'd over Run1Bak). 1 `<tessellated>` solid (TSdAHelicalTube,
  4002 facets); `GeomSolids1001 negative cubic volume` thrown live during the
  dump.
- `mu2e_helical050a_twistedbox.gdml` (4.2 MB) — new patched lib. 0 tessellated,
  6 `<twistedbox>` solids (one per 85°-cap segment, `N=ceil(459.591/85)`), 5
  `TSdAHelicalAsm_*` intermediate unions + final `TSdAHelicalTube`. Zero
  warnings.

## Open questions / TODO
- Repackage `Code_helical_base.tar.bz2` with the patched lib + ship to grid;
  re-run helical050a end-to-end and compare new `calo_per_pot` vs current
  (2.54e-6). If the new value lands near 6.5e-8 (legacy 050), confirms the
  40× bump is entirely this defect (task #53).
- Teach `cmd_preflight` to source the local muse setup (or extracted
  `Code/setup.sh`) so future helical-plug bugs surface in preflight rather
  than only in grid logs.
- Retroactive sweep: opt-in run of `scan_worker_logs` over all completed
  helicalNNN configs to flag which historical leaderboard rows are tainted
  (built with the broken lib) vs trustworthy. The ~80% mass inflation
  almost certainly biases the bo-helical leaderboard — every pre-fix
  helicalNNN row should be re-run for trustworthy ranking.
- **Alternative fix — radial subdivision of broad faces.** The stacked-twistedbox
  patch is analytic and was preferred because no facet bookkeeping is needed,
  but if a tessellated path is ever wanted again (e.g. for a material whose
  G4 navigation misbehaves under twisted-prism solids), the cheaper fix is to
  subdivide the broad ±x faces *radially* (across the long `2·dy` dimension)
  rather than only axially. The warp scales as `dy·(angle/N)/4` — it's large
  only because each broad facet spans the full ribbon width as one
  un-subdivided piece. Splitting each broad quad into `M` strips along y
  cuts the per-strip warp by `1/M²` (the warp goes as length²), so M≈8
  would suffice for helical050a where N=100 is currently 34× under threshold.
  Net facet count: 4N (axial) × 2M (radial strips) per broad face, well
  under the 5000-step purely-axial fix.
