# Stopping-Target Foil Base Spec

**Type:** concept
**Status:** active
**Updated:** 2026-06-01

## Summary
The deployed Mu2e stopping-target geometry is 37 aluminum foils at rOut=75 mm,
halfThickness=0.0528 mm (full ≈ 105.6 µm — *not* the "100 µm" design spec),
holeRadius=21.5 mm, deltaZ=22.222222 mm, z0InMu2e=5871 mm. Knowing the
exact source-of-truth file + override chain matters when building per-foil
overrides (e.g. [[bo-foils]] adds extras around this base) or interpreting
"why is the count 37 and not 34 or 38?"

## Key facts

- **Source-of-truth chain** (last-write wins; FHiCL re-emitted vectors are
  *replaced*, not merged):
  1. `Offline/Mu2eG4/geom/stoppingTarget_CD3C_34foils.txt` — 34-foil base;
     sets `stoppingTarget.z0InMu2e = 5871`, `deltaZ = 22.222222`,
     `fillMaterial = "DSVacuum"`.
  2. `Offline/Mu2eG4/geom/stoppingTargetHoles_DOE_review_2017.txt` — extends
     to 37 foils; explicit `stoppingTarget.radii = {75.00 × 37}`,
     `stoppingTarget.holeRadius = 21.5`, `halfThicknesses = {0.025 cm}`
     (= 0.25 mm full thickness — DOE-2017 figure).
  3. `Offline/Mu2eG4/geom/stoppingTargetHoles_v02.txt` — currently included
     by `geom_run1_a.txt`; overrides `halfThicknesses = {0.0528}` (mm half;
     full = 0.1056 mm ≈ 105.6 µm) and adds wire-support radii.

- **Deployed-vs-design halfThickness mismatch:** the "Mu2e foils are 100 µm
  thick" docs/papers number is the *design* spec. The `v02.txt` deployed
  value is 0.0528 mm half (≈105.6 µm full) — likely an as-built tolerance.
  Use **0.0528** when matching the simulated geometry; use **0.05** if you
  intend to compare against a documents-spec configuration.

- **`stoppingTarget.holeRadius` historically a SINGLE SCALAR; patched lib
  (2026-06-01) adds optional per-foil `stoppingTarget.holeRadii` vector.**
  Upstream `StoppingTargetMaker.cc:41` reads only the scalar via
  `c.getDouble("stoppingTarget.holeRadius", 0)`. The patched build in
  `Code_helical_base.tar.bz2` (post 2026-06-01 cutover) reads
  `vector<double> stoppingTarget.holeRadii` when present (last-element-
  repeat semantics, mirrors `halfThicknesses` parsing), falls back to the
  scalar otherwise. Decouples extras-rIn from the pinned base rIn=21.5 in
  [[bo-foils]]. **Dual-emit contract:** `FoilsMode._geom_text` always emits
  BOTH the scalar (at BASE_HOLE_RADIUS_MM=21.5) and the per-foil vector —
  legacy grid workers running the old tarball silently fall back to the
  scalar and rebuild the deployed-baseline base correctly (extras still
  wrong, but base is right). Patch at `/tmp/holeRadii-vector.patch`.

- **Vector keys that ARE per-foil** (`StoppingTargetMaker.cc:40, 50`,
  `getVectorDouble`): `stoppingTarget.radii`, `stoppingTarget.halfThicknesses`.
  FHiCL "last value repeats" parser convention applies — a 1-entry vector
  expands to length-of-radii.

- **FHiCL vector replacement after include:** re-emitting
  `vector<double> stoppingTarget.radii = {...}` *after* an `#include`
  *replaces* the included vector entirely; it does not append/merge. Same
  pattern is used by `geom_run1_b_v06.txt:29-31` for run1b overrides. This
  is how [[bo-foils]] inserts `n_up + 37 + n_down` extras around the base.

- **HelicalMode previously emitted FOIL_COUNT=38** (off-by-one vs deployed
  37). Fixed at `autoresearch_bo_michael.py:379` on 2026-05-28; affects
  only newly-emitted geom.txt files — pre-existing frozen helical leaderboard
  rows are unchanged (each config carries its own geom snapshot).

- **+12 extras envelope is buildable at the extreme corner** (Phase 0,
  2026-05-28): `foilsP0_AS` at `n_up=6, n_down=6, extra_rOut=250 mm,
  extra_halfThickness=1.0 mm, extra_rIn=50 mm` passes G4 surface-check with
  zero managed-volume overlaps (1 baseline hit only). 49-entry `radii`
  vector. No need to clamp the FoilsMode search space defensively — the
  full 5D box is feasible. `_AU` (6↑/0↓) and `_AD` (0↑/6↓) also PASS with
  43-entry vectors. Preflight logs at
  `bo_foils_preflight/foilsP0_{AU,AD,AS}.log`.

## Cross-links
- Related: [[bo-foils]] (consumes this spec), [[bo-helical]] (re-emits foil
  vector at rOut=125 to block calo stops), [[tsda]], [[production-target-stickman]]
- Source files:
  `/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/CaloCalibc/Offline/GeometryService/src/StoppingTargetMaker.cc:33-127`,
  `Offline/Mu2eG4/geom/stoppingTargetHoles_v02.txt`,
  `Offline/Mu2eG4/geom/stoppingTargetHoles_DOE_review_2017.txt`,
  `Offline/Mu2eG4/geom/stoppingTarget_CD3C_34foils.txt`,
  `autoresearch_bo_michael.py:379` (HelicalMode.FOIL_COUNT),
  `autoresearch_bo_michael.py` `FoilsMode.BASE_*` constants

## Open questions / TODO
- Confirm with mmackenz whether the 0.0528 mm v02 override is a measured
  as-built value or a deliberate over-thickness for a safety margin.
