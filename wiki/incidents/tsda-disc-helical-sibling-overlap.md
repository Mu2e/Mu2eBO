---
name: tsda-disc-helical-sibling-overlap
description: TSdA4 disc and helical plug are sibling daughters of DS2Vacuum; silent G4 navigation-order overlap when z-ranges intersect
type: incident
---

# TSdA disc ↔ helical plug sibling overlap

**Type:** incident
**Status:** active (open; mitigation in progress — Option A coupling + preflight surface-check)
**Updated:** 2026-05-18

## Summary
`constructTSdA.cc` places the TSdA4 absorber disc and the helical plug as
**direct siblings inside `ds2VacuumInfo.logical`**, not as a parent/child
pair. Neither call passes a CheckOverlaps flag. When `tsda.helical.z0`
falls inside `[tsda.z0 - halfLength4, tsda.z0 + halfLength4]`, the two
volumes geometrically overlap; G4 silently tracks the overlap region as
whichever was placed last (the helical plug, per `constructTSdA.cc` line
ordering). The optimizer can exploit this as a "free" thicker absorber
without any error or warning — the top-4 BO winners as of 2026-05-18 all
sit in a region where the plug's upstream face is at z = 4189.32 mm
(z0=4479 − halflen=289.68) while the disc occupies z ∈ [4182.5, 4207.5]
(tsda.z0=4195 ± halfLength4=12.5). The 18-mm overlap may explain why this
geometric cluster beats the "gap" cluster (helical049/050, with z0
positioned downstream of the disc) by ~4%.

## Key facts
- **Sibling placement:**
  - `constructTSdA.cc:240–252` — `nestTubs` places TSdA4 disc in `ds2VacuumInfo.logical`
  - `constructTSdA.cc:322–352` — `makeHelicalPlug` returns an extruded solid,
    then `finishNesting` places it in `ds2VacuumInfo.logical` at
    `(0, 0, z0_helical - ds2VacuumInfo.centerInMu2e().z())`
  - Both calls omit the `CheckOverlaps` argument → defaults to false.
- **No envelope assertions** in `makeHelicalPlug` (lines 58–128) or in the
  outer constructor. Out-of-range `dy`, `halflength`, or `z0` won't throw —
  they just produce silent overlaps with the disc, DS2Vacuum walls, or
  downstream stopping target.
- **Affected configs (2026-05-18 top-5, all geometric clones varying dx):**
  - helical045 (dx=0.20, obj=2.533 — current GLOBAL BEST)
  - helical043 (dx=0.10, obj=2.529)
  - helical046 (dx=0.30, obj=2.506)
  - helical044 (dx=0.15, obj=2.504)
  - helical047 (dx=0.40, obj=2.488)
  All five share `dy=109, halflen=289.68, z0=4479, angle=333` → all overlap
  the TSdA disc by 18 mm in z.
- **Gap-cluster comparison (no overlap):**
  - helical049 (z0=4498, halflen=188 → upstream face at z=4310, ~103 mm
    downstream of disc back face): obj=2.421
  - helical050 (z0=4496, halflen=195 → upstream face at z=4301, ~94 mm gap):
    obj=2.443
  Gap cluster underperforms overlap cluster by ~4%, consistent with the
  overlap acting as ~18 mm of extra Al absorber.
- **G4 navigation rule:** when point P is inside two sibling daughters,
  G4 returns the daughter whose insertion order in the mother's daughter
  list is **later** (`G4VNavigator::LocateGlobalPointAndSetup` does not
  detect ambiguity; documented under "geometry overlaps cause navigation
  errors that are difficult to predict"). For TSdA disc vs helical plug,
  the plug is placed second → overlap region tracked as plug material.
  Same material (`StoppingTarget_Al`) in both cases, but the helical-plug
  cross section differs from a flat-disc cross section, so the local
  effective thickness shifts.
- **Why the optimizer found it:** structural overlap is an
  unintentional knob with monotonic favourable effect on calo (more Al
  thickness = more low-E absorption) and small negative effect on sob (some
  CE arm scatter). BO's preference for `z0 = 4479` and `halflen = 289.68`
  exactly matches the inner edge of the overlap region — coincidence is
  implausible.

## Mitigation plan (2026-05-18)
**Option A coupling (approved):** drop `tsda.helical.z0` from the BO search
space; render it as `z0 = tsda.z0 + halfLength4 + halflen` so the plug's
upstream face touches the disc's downstream face by construction. Search
space shrinks 5D → 4D (dx, dy, halflen, angle).

**Source-side guard:** add a throw assertion in `constructTSdA.cc` after
the helical placement (~line 350):
```cpp
const double disc_zmax = atsd->z0() + atsd->halfLength4();
const double plug_zmin = z0_helical - halflength;
if (plug_zmin < disc_zmax - 1e-6) {
  throw cet::exception("GEOM") << "TSdA helical plug overlaps disc in z: "
    << "plug_zmin=" << plug_zmin << " < disc_zmax=" << disc_zmax;
}
```

**Preflight surface-check:** wire `g4.doSurfaceCheck=true` into a per-config
wrapper FCL (see [[mu2e-overlap-check]]) and run `mu2e -n 1` in
`preflight_helical`. Reject the proposal on any "Overlap" line.

**Re-anchor leaderboard:** re-evaluate helical044 and helical049 under the
new Option-A render to bridge old/new leaderboards before resuming BO.

## Cross-links
- Related: [[bo-helical]], [[tsda]], [[mu2e-overlap-check]], [[preflight]], [[scan-broken-codes-too-narrow]], [[tessellated-solid-facet-orientation]]
- Source: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:240,322,350`
- BO driver: `autoresearch_bo_michael.py` (HelicalMode render_geom, BOUNDS, search space)

## Open questions / TODO
- Quantify the overlap's contribution: rerun helical044's geom with z0
  bumped from 4479 → 4497 (just-touching, no overlap, same halflen) and
  compare calo. If obj drops by ~4%, the overlap is the entire "winner"
  margin.
- Confirm G4 picks the helical-plug volume (not the disc) for tracking in
  the overlap region — could verify with a particle-gun probe at z=4192.
