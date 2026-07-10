---
# Production Target — Stickman v1.0 (MDC2025aq default)

**Type:** concept
**Status:** active
**Updated:** 2026-06-17 (as-built ProductionTargetMother daughter inventory + standalone-GDML extractor)

## Summary
PS production target in `MDC2025aq` is the **Stickman v1.0** geometry (35
Inconel718 plates on rods + bicycle-wheel support), not Hayman v2. It is
selected via the include chain `geom_common_current → geom_common →
geom_run1_a_stickman.txt:69 → ProductionTarget_Stickman_v1_0.txt`. Knob
inventory here so a BO line over the PT can be wired without re-deriving the
file layout.

## Key facts
- **Default selector** (MDC2025aq backing): `targetPS_model = "Stickman_v_1_0"`,
  `targetPS_version = 4`. Hayman v2 dependence intentionally removed in the
  Stickman geom file.
- **Geom file**: `backing/Offline/Mu2eG4/geom/ProductionTarget_Stickman_v1_0.txt`
  — full knob set (140+ lines).
- **Placement**: `productionTarget.zNominal = -6164.5 mm`,
  `productionTarget.offset = {0,0,0}`, `targetPS_rotY = 14°` (X/Z = 0).
- **Plates** (35 default): `targetPS_plateMaterial[]` = Inconel718,
  `targetPS_rOut[] = 3.15 mm` (core radius), `targetPS_plateThickness[] = 5.0 mm`,
  `targetPS_plateLugThickness[] = 6.0 mm`, fillets on by default
  (`addFilletToPlateCore=true`, `plateFilletRadius=1.0 mm`).
- **Fins**: `nStickmanFins=3` at angles `{285,165,45}°`,
  `plateFinOuterRadius=18.075 mm`, `plateFinWidth=2.0 mm`.
- **Supports** (bicycle wheel inherited from Hayman): `wheel.rOut=196.85`,
  `wheel.rIn=177.8`, Al; 3 spokes, Inconel718 rods.
- **Beam knobs** (`Offline/EventGenerator/fcl/prolog.fcl:97-113`,
  `PrimaryProtonGun`): `beamSpotSigma=1.0 mm`, `shape="gaus"`, `rmax=100 mm`,
  `beamDisplacementOnTarget=[0,0,0]`, `beamRotationTheta/Phi/Psi=0`.
- **POT stage cuts** (`Production/JobConfig/beam/POT.fcl`):
  `minRangeCut = 1.0 mm` (coarse — `g4-speed-knobs` shows 0.05 is the safe
  arm for downstream stages; beam stage uses 1.0); `enableSD=[virtualdetector]`
  only; common cut union with `mu2eg4CutDeltaElectrons`.
- **Available target geometries** in same dir: `Hayman_v2`/`_v2_0/_1/_2`,
  `HaymanLowerDensity`, `Stickman_v1_0`, `Hayman_v2_TS06`. Switch by editing
  the include in the geom_run1_*.txt selector (or override via FHiCL geom file
  prolog).
- **`StoppingTargetMaker` parallel**: like the muon stopping-target
  ([[stopping-target-foil-base-spec]]), per-plate vector params
  (`rOut[]`, `plateThickness[]`, `plateMaterial[]`, `plateLugThickness[]`) are
  length-`numberOfPlates` arrays — if you change `numberOfPlates` you must
  resize *all four* together or the geometry maker will assert.
- **Per-plate enforcement** (`backing/Offline/GeometryService/src/ProductionTargetMaker.cc:419-438`):
  `cet::exception("GEOM")` thrown at construction if any of
  `targetPS_plateMaterial`, `targetPS_rOut`, `targetPS_plateThickness`,
  `targetPS_plateLugThickness` has `size() != numberOfPlates`. There is no
  broadcast/recycle — a scalar value must be replicated `nPlates` times.
- **`targetPS_plateFinAngles` is sized to `targetPS_nStickmanFins` (default 3),
  NOT `numberOfPlates`** (`PTM.cc:439-443`); fin geometry
  (`plateFinOuterRadius`, `plateFinWidth`, `plateCenterToLugCenter`, lug radii,
  `addFilletToPlateCore/Lug`, `plateFilletRadius`) is **global scalar** —
  fins are identical across all plates by design.
- **Plate-to-plate pitch is `plateLugThickness`, NOT `spacerHalfLength`**
  (`constructTargetPS.cc:1659-1716`). The z-march starts at
  `−halfStickmanLength + supportRingLength + 2·spacerHalfLength`, then steps
  `_currentZ += plateLugThickness(i)` per plate; `plateThickness` only sets
  the core extent inside that pitch (plate flush on upstream side).
  **Inter-plate gap = `plateLugThickness − plateThickness`** (defaults
  `6 − 5 = 1 mm`). `spacerHalfLength` sets ONLY the single spacer between
  the end-ring and the first/last plate; it does not appear in inter-plate
  geometry. Sweeping `spacerHalfLength` is effectively dead-on-arrival for
  production physics.
- **Total Stickman envelope identity** (`ProductionTarget.cc:230` + above):
  `2·halfStickmanLength = 2·supportRingLength + 4·spacerHalfLength +
  Σ plateLugThickness`. Defaults: `2·8.1 + 4·1.5 + 35·6 = 232.2 mm` →
  matches the comment "full target length 232.2 mm" in the geom file. If a
  forker changes `numberOfPlates` or `plateLugThickness`, it **must** update
  `targetPS_halfStickmanLength` to match (or bump
  `targetPS_productionTargetMotherHalfLength ≥ halfStickmanLength + margin`).
- **Silent overlap risk**: `plateLugThickness[i] < plateThickness[i]` is not
  asserted anywhere read so far — the plate core would extend past the next
  plate's start. Defensive check belongs in the config forker, not the geom
  maker.
- **As-built `ProductionTargetMother` daughter inventory** (verified 2026-06-17 from `asbuilt_pt6d07R01_07.gdml`): **53 daughters** = 35 `ProductionTargetPlate00`–`34` + 3 `ProductionTargetRod_{0,1,2}` + 6 `ProductionTargetSpacer{NegZ,PosZ}_{0,1,2}` + 2 `ProductionTargetSupportRing_{Upstream,Downstream}` + 6 `ProductionTargetSpokeWire_{Up,Down}stream_{0,1,2}` + 1 `ProductionTargetSupportWheel`. Plates are flat leaves (0 sub-physvol). A standalone subset GDML of the whole mother = 54 volumes / **959 solids** (the high solid count is boolean geometry of the wheel/rings/spokes, not the plates) / 249 material+element entries.
- **Standalone-GDML extractor**: `tools/gdml_subset_production_target.py <asbuilt.gdml> [out] [--plates-only] [--mother NAME]` pulls `ProductionTargetMother` + descendants into a self-contained GDML (world = the mother). Recursive volume walk + boolean-solid ref closure + carries the whole `<materials>` block (so Inconel718→element fractions resolve). Emits **post-order** (daughters before mother) for ROOT TGDMLParse ([[root-gdml-forward-volume-ref]]). NOTE the foils tool `gdml_subset_stopping_target.py` is hardcoded to `StoppingTargetMother`+`Foil_*` and will NOT extract `ProductionTargetPlate*` — use this one for prodtarget. **But for ROOT-only viewing you don't even need it** — `TGeoManager::Import(asbuilt); gGeoManager->GetVolume("ProductionTargetMother")->Draw("ogl")` draws just that subtree from the full-world GDML (ROOT strips the `0x…` pointer suffix on import, so the plain name resolves).
- **Natural BO axes** (if a "bo-prodtarget" line gets created): continuous —
  `numberOfPlates` (int), `plateThickness` (scalar or per-plate),
  `rOut` (core radius), `rotY` (beam-target angle), `productionTarget.offset.{x,y}`,
  `beamSpotSigma`. Discrete — plate material (Inconel718 / W / Ta).

## Cross-links
- Related: [[g4-speed-knobs]], [[stopping-target-foil-base-spec]],
  [[fixed-geometry-constraint]]
- Source files:
  `backing/Offline/Mu2eG4/geom/ProductionTarget_Stickman_v1_0.txt`,
  `backing/Offline/Mu2eG4/geom/geom_run1_a_stickman.txt:69`,
  `backing/Offline/EventGenerator/fcl/prolog.fcl:97`,
  `Production/JobConfig/beam/POT.fcl`
- External: MDC2025aq SimJob — `/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025aq/`

## DPA vs thermal coupling (BO search-space triage)

No engineering DPA/thermal spec is in this wiki yet. The two failure modes
have **different geometry coupling** — earlier draft conflated them.

- **DPA** (local lattice displacements): scales with local proton fluence,
  set by `beamSpotSigma` (fluence ∝ 1/σ²) and integrated POT. **NOT a
  function of `rOut`** as long as `rOut ≥ ~few·σ` (same protons hit the same
  core volume regardless of plate radius). DPA is largely a run-lifetime
  budget, not a per-config geometry knob.
- **Thermal / peak-T**: power-per-length in the irradiated core is roughly
  constant (depends on ρ·dE/dx, not rOut for σ ≪ rOut); heat must leave by
  **radiation from the surface** (PSVacuum, no convection) + **conduction
  through lugs/rods/spacers**. So smaller `rOut` → smaller radiating area →
  higher equilibrium peak T. `rOut` is dominantly a **thermal** knob, not a
  DPA knob.

### Coupling buckets
- **Decoupled (sweep freely)**: `beamDisplacementOnTarget`,
  `beamRotation{Theta,Phi,Psi}`, `productionTarget.offset` (mm scale),
  `targetPS_productionTargetMother{OuterRadius,HalfLength}` (sim envelope only),
  all `targetPS.supports.*` (wheel at r≈197 mm is outside beam),
  fillets, `targetPS_plateFinAngles`/`nStickmanFins`/`plateFinWidth`/
  `plateFinOuterRadius` (off-axis structural).
- **DPA-coupled (engineering check)**: `beamSpotSigma` (local fluence ∝ 1/σ²
  — **don't shrink below ~1 mm**), `plateMaterial[]` (displacement
  thresholds + recovery differ; Inconel718 chosen for high-T, not low-DPA).
- **Thermal-coupled (engineering check)**: `rOut[]` (radiating area scales
  with surface ∝ rOut), `numberOfPlates` (fewer plates → more ΔE each →
  hotter), `plateThickness[]`, `plateMaterial[]` (T_max + conductivity),
  `spacerHalfLength` / `supportRingLength` (sets conduction path + radiation
  view factor between plates).

A safe ~6-8D BO box that touches neither DPA nor thermal design point:
`{beamDisplacementOnTarget.{x,y}, productionTarget.offset.{x,y,z}, rotY,
plateFinAngles, supportRingCutoutAngles}` (note: σ is *excluded* because it
moves DPA; rOut/nPlates/thickness/spacer excluded because they move thermal).

## Open questions / TODO
- Engineering envelope (max/min, peak-T, DPA limits) for `numberOfPlates`,
  `plateThickness`, `rOut`, `plateMaterial` on the Stickman support? — would
  need the mechanical drawing constraints / docDB rad-damage spec.
- Whether `Mu2eG4CommonCut`'s `minRangeCut=1.0 mm` at the POT stage is
  load-bearing for pion yield (vs CPU) — not measured here.
