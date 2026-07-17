---
type: concept
title: Geant4 speed knobs (local bench, 2026-05-22)
description: '`minRangeCut=0.05` is the safe speedup arm (−6% CPU); `Minimal` physics
  list zeros stop counts even though workflow looks "EM-only"'
status: active
timestamp: '2026-07-08'
updated_note: 'local `elebeam_flash` geometry-pruning bench: guess overturned'
---

# Geant4 speed knobs (local bench, 2026-05-22)

## External G4 speedup technology survey (2026-07-08, web research, no local bench)

Ranked-list research task (G4HepEm, Woodcock tracking, specialized tracking
managers, version-to-version CPU evolution, LTO/PGO, field-nav) against
current (2025-2026) primary sources. Full ranked list with sources delivered
to the user directly; key facts worth banking here because they change risk
assessment of levers already in this page:

- **G4TransportationWithMsc** (merges transportation+MSC stepping, default
  with `G4EmStandard_opt1`, i.e. `FTFP_BERT_EMV` in Mu2e terms) does NOT
  work with parallel worlds (Mu2eG4 parallel-world usage unverified — check
  before adopting) and, more importantly, **`G4EmStandard_opt1` pairs by
  default with `G4UniversalFluctuation`** instead of opt0's
  `G4UrbanFluctuation`. Per Hahnfeld/Ivanchenko CHEP2023
  (arXiv/indico.jlab.org 1214-2023_chep_em.pdf, Fig. 1),
  `G4UniversalFluctuation` has **measurably biased mean + wrong-shape
  energy-loss distribution for a 5.6 µm Si layer at 100 MeV e−** vs
  `G4UrbanFluctuation`, which matches Meroli 2011 data well. **This directly
  threatens the wiki's existing "FTFP_BERT_EMV: viable" verdict** (5-arm
  stepper bench + physics-list bench above, judged only on
  TargetStops/PolyStops counts) for the `run1b_mubeam`/`elebeam_flash`
  EM-edep observable — our foils are ~0.1 mm Al, same order of magnitude as
  the failing test case. Plain `FTFP_BERT` (opt0, currently deployed)
  already uses the accurate `G4UrbanFluctuation` and is NOT implicated.
  **Do not promote `FTFP_BERT_EMV`/opt1-based lists to any EM-edep-scoring
  stage without a thin-foil energy-loss-shape check first.**
- **Woodcock (delta) tracking is NOT in mainline Geant4** — same CHEP2023
  source: "the implementation is not part of the main Geant4 repository...
  planned to be part of the new library G4HepEm." Only reachable via
  G4HepEm's `G4HepEmTrackingManager` (up to 2× on a toy sampling
  calorimeter per Hahnfeld's Oct-2025 CM talk; ATLAS EMEC arm measured
  +17.5%, CHEP2025 `epjconf_chep2025_01351`). G4HepEm only covers e±/γ
  (job type (b) / `run1b_mubeam`+`elebeam_flash`) — zero relevance/risk to
  muon transport (job type (a)). Integration is a real R&D lift: new
  external dependency + registering `G4VTrackingManager` on particle
  definitions in Mu2eG4 source (G4 11.0+ interface) + muse rebuild, not an
  FCL knob.
- **LTO build of Geant4+Offline: +5% throughput, bitwise-identical physics**
  ("pure technical change") per ATLAS's CMAKE_INTERPROCEDURAL_OPTIMIZATION
  report (CDS ATL-SOFT-PROC-2023-002). Zero G4-version dependency, zero
  fidelity risk if it links cleanly — cheapest unexplored lever found in
  this survey, worth a muse-backed trial build.
- **Version-bump 11.0→11.4 is not, by itself, worth fighting for.**
  Per-release CPU notes are individually "few percent" or unquantified
  (11.1: `G4GammaGeneralProcess` default + EM-data env-var caching; 11.2:
  `G4SafetyCalculator`, QSS integrator (pure-B-field only), `G4UrbanMscModel`
  safety-reorder; 11.3: Opt3 `DistanceToBoundary` optimization, parallel
  voxel init; 11.4 released 2025-12-05, too new to be any current pin: QSS3,
  default-on parallel voxelization). The double-digit numbers in the
  literature (ATLAS 1.8× MC20→MC23) are a **3-year bundle of ~8 separate
  techniques** (LTO, VecGeom, Woodcock, region cuts, Russian roulette,
  single-library build, `G4GammaGeneralProcess`, B-field switch-off), not
  the version bump alone. `G4GammaGeneralProcess` (few-% default gamma
  speedup) is the one default-on-upgrade item worth checking — verify
  Mu2e's currently-pinned G4 minor version already has it (≥11.1).
- **Global-vs-local field manager scoping is a zero-cost, unbenched lever
  specific to our long-solenoid workload.** Per the official Geant4
  performance-tips page (twiki.cern.ch/.../Geant4PerformanceTips): "When a
  field object exists for a volume, all charged particles inside will take
  more CPU time to move — even if the field value is zero." Nobody has
  checked whether `Mu2eWorld` attaches one global B-field manager across
  the whole world (including field-free regions far downstream of the DS)
  vs. scoping it to TS/DS only. Independent of G4 version; pure code-audit
  + possible source patch.

## Geometry-pruning via `bool has*` flags — MEASURED 2026-07-08, guess OVERTURNED

**TL;DR: the "plausible 10-30%" guess below was wrong and the "CRV/STM/
externals/MBS droppable freely" safety claim was wrong.** A local
`elebeam_flash` bench (`/tmp/g4_geomprune_bench/`, `n=10000`,
FTFP_BERT, DS-on, foilsflash08R00_00 geom+FCL, single run per arm — no
replicates, see caveats) found: **3 of the 4 candidate flags
(hasCosmicRayShield, hasExternalShielding, hasMBS) crash immediately**
with a `GeomHandle` GEOM exception, root-caused to **hard-coded
unconditional dependencies in `Mu2eG4/src/{Mu2eWorld,
constructVirtualDetectors}.cc`** that are simply not gated by the same
`has*` flag GeometryService uses to build the detector element — not an
FCL problem, needs a source patch (out of scope for this bench). Only
`hasSTM` runs clean, and it buys ~0% (see table). `hasDiskCalorimeter`
crashes too (a *different* module, not geometry construction) but is
fixable with an FCL-only workaround; the fixed arm buys −4.7% wall, far
short of the guessed 10-30%.

**Per-flag verdict:**

| Flag | Result | Root cause | Fixable how |
|---|---|---|---|
| `hasCosmicRayShield=false` | **BROKEN** (alone or combined w/ STM+MBS) | `Mu2eG4/src/constructVirtualDetectors.cc` (~line 1768): `GeomHandle<CosmicRayShield> CRS;` sits *before* the `if(vdg->exist(vdId))` gate in the `CRV_R..CRV_U` virtual-detector loop — instantiated unconditionally every job. Reached via `Mu2eWorld.cc`'s unconditional call to `constructVirtualDetectors()` (not itself gated on `hasCosmicRayShield`/`vd.crv.build`). Independent of `hasSTM` (tested both ways — same crash). | 1-line source patch: move the `GeomHandle` inside the loop, or wrap the loop in `if (_config.getBool("hasCosmicRayShield", false))`. Needs muse-backed patched Offline rebuild (see [muse-backing-pattern](/external/muse-backing-pattern.md)). |
| `hasExternalShielding=false` | **BROKEN** (alone or combined) | `Mu2eG4/src/Mu2eWorld.cc:237` calls `constructSaddles(hallInfo, _config)` **unconditionally** (only the *ExternalShielding volumes themselves*, lines 231-233, are gated by `hasExternalShielding`), but `GeometryService.cc:308-312` only builds the `Saddle` detector element **inside** `if(hasExternalShielding)`. Confirmed both in an isolated single-flag smoke test and combined with CRV+STM+MBS. | `if (_config.getBool("hasExternalShielding", false)) constructSaddles(...)` in Mu2eWorld.cc. |
| `hasMBS=false` | **BROKEN** (alone or combined) | `Mu2eWorld::constructStepLimiters()` (~line 655) unconditionally does `_helper->locateVolInfo("MBSMother").logical` for the step-limiter volume list, even though the actual MBS G4 construction (line 246-248) *is* correctly gated by `hasMBS`. Third independent unconditional-dependency bug, unrelated to the CRV/Ext ones. | Guard the `MBSMother` lookup in `constructStepLimiters()` with the same `hasMBS` check. |
| `hasSTM=false` (alone) | **SAFE but ~POINTLESS** | Runs clean (correctly gated everywhere touched — `Mu2eWorld.cc:254`, `GeometryService.cc:283`, `VirtualDetectorMaker.cc:523`'s hasSTM block skips cleanly when nothing downstream needs it). | n/a |
| `hasDiskCalorimeter=false` | **BROKEN as-is, fixable via FCL** | `CommonMC`'s `CaloShowerStepMaker` producer unconditionally needs `GeomHandle<Calorimeter>` (StepPointMC→CaloShowerStep conversion), regardless of `hasDiskCalorimeter` — same failure *class* as CRV/MBS (a downstream consumer assumes the geometry it converts always exists) but this one is a **producer not scheduled from a fixed C++ call site**, so it CAN be dropped from the FCL trigger path. | Drop `CaloShowerStepMaker` from `physics.{flashPath,earlyFlashPath}`, blank `compressDetStepMCs.caloShowerStepTag`, and set `{Early}DetStepFilter.MinimumSumCaloStepE` to an unreachable threshold (NOT 0 — 0 makes the OR-logic trivially pass every event once calo energy is undefined) + `CaloShowerSteps: []`. Recipe: `/tmp/g4_geomprune_bench/nocalo_module_fix.fcl`. |

**Measured (n=10000 events, single run per arm, FTFP_BERT, DS-on):**

| Arm | wall/ev [ms] | Δwall | CPU/ev [ms] | ΔCPU | init [s] | VmPeak [MB] | ΔVmPeak | events passing EarlyDetStepFilter | tracker-hit events | total tracker edep [MeV] | SimParticles (compressed) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 19.59 | — | 19.42 | — | 14 | 1553.3 | — | 20/10000 | 5 | 0.0558 | 139 |
| −calo (fixed) | 18.67 | **−4.7%** | 18.54 | −4.5% | 12 | 1543.1 | −0.65% | 7/10000 | 7 | 0.0518 | 46 |
| −STM only | 19.11 | **−2.5%** | 18.93 | −2.5% | 14 | 1547.9 | −0.34% | 21/10000 | 3 | 0.0122 | 152 |

**Verdicts:**
- **−calo (fixed): POINTLESS-to-marginal on CPU** (−4.7% wall, single-run — no
  replicate to separate from run-to-run jitter; the wiki's mubeam-stage
  physics-list bench saw the ShieldingM-self noise floor alone hit ~8% on
  `calo_per_pot` at n=200 jobs, so a single local run at n=10000 events could
  easily be within noise). **Edep bias UNDETERMINED, not SAFE, not
  BIASED** — dropping calo removes the calo-energy leg of the
  `DetectorStepFilter` OR-selection (`MinimumSumCaloStepE`), which
  *changes which events pass* (20→7 out of 10000): baseline's 20 include
  events selected purely on calo energy that −calo can never select. This
  is a **selection-function confound**, not a clean paired comparison of
  the same event population. On top of that, **available statistics are
  far below what the task anticipated**: only 3-7 tracker-hit events per
  arm at n=10000 (the task's ~0.5% hit-rate assumption implied ~50, actual
  is ~0.03-0.07%) — Poisson σ on single-digit counts is 40-60%, so no
  edep verdict is defensible at this n. Would need ≥10× more events (or
  many more paired EleBeamCat file-pairs) for a real backsplash call.
- **−STM: SAFE, essentially POINTLESS** (−2.5% wall, likely noise-level;
  SimParticle count per passing event is flat vs baseline, 7.24 vs 6.95 —
  no evidence STM is a meaningful secondary-tracking CPU sink for this
  workload). The 0.0122 vs 0.0558 MeV "78% edep drop" is **not a real
  signal** — it's 3 vs 5 hit-events, well inside Poisson noise.
- **CRV/Ext/MBS: cannot be evaluated at all** — the mechanism hypothesis
  ("CRV is where EM leakage dies expensively") from the original guess is
  **neither confirmed nor refuted**; the flag that was supposed to test it
  crashes before producing one event. Given calo (the one testable
  "dense-material secondary" flag) only bought −4.7%, the wiki's
  "plausible 10-30%" framing for the *whole* has*-flag family should be
  treated as **overturned** until CRV can actually be measured (needs the
  source patch above).
- **Overall recommendation:** this lever is **not worth pursuing further
  as an FCL-only pruning technique** — 3 of 5 flags need a C++ patch just
  to run, and the one flag that IS FCL-fixable (calo) buys single-digit %
  CPU with an unresolvable statistics problem on the edep side at
  reasonable event counts. If CRV's real effect matters, it needs the
  `constructVirtualDetectors.cc` one-line patch + muse rebuild + a MUCH
  larger n (or a different observable with better statistics) — not a
  quick FCL-overlay bench.

**Bench artifacts (scratch, not committed):** `/tmp/g4_geomprune_bench/`
— `base.fcl`/`base_geom.txt` (copied from `foilsflash08R00_00`),
`geom_arm*.txt` (per-arm overlays), `fcl_arm*.fcl`, `nocalo_module_fix.fcl`
(the calo FCL workaround), `run_arm.sh` (timing harness), `extract_edep.py`
/ `count_simp.py` (gallery extractors, cribbed from `pipeline.py`'s
`_TRK_EDEP_EXTRACT_SCRIPT`), `run_*.log`/`run_*.log.meta` (raw art +
`/usr/bin/time -v` output per arm). EleBeamCat input resolved via
`samweb locate-file` (2 files, `dcache:persistent`, not tape — no
prestage needed): `sim.mu2e.EleBeamCat.Run1Baa.001430_{00000000,
00003251}.art`.

---

*(Original pre-bench guess, superseded above — kept for the record.)*
geom_common_current.txt exposes per-subsystem switches settable in our
per-config overlay (one line each): hasCosmicRayShield, hasExternalShielding,
hasDiskCalorimeter, hasSTM, hasMBS, hasProtonAbsorber, hasTSdA, hasHall,
hasBFieldManager (+ a base-file comment wishing CRV were toggled — anticipated
use). Physics of the saving: **G4 stepping cost is LOCAL** — dropping
far-away detail buys init (~35 s/job ≈ 2%) + memory (slot notch), NOT
stepping CPU; the real stepping win is dense material secondaries reach:
**CRV** (counters+absorber wrapping the whole DS = where EM leakage and
capture neutrons die expensively) and **calo disks** (forward-electron
showers). Plausible 10-30% on flash jobs — NOT the beamline-deck 2-5×
(primaries still traverse the detailed DS). Safety: flash jobs can drop
CRV/STM/externals/MBS freely; **calo drop needs an A/B** (backsplash into
the tracker is real flash edep — same caveat as the kill-plane); muon jobs
can likely drop CRV/STM/externals/calo (backscatter-into-ST gate); NEVER
drop field manager/target/proton absorber/TSdA/beamline/virtual detectors
(base file warns components assume vd presence). Gate = A/B within
leaderboard noise (σ_flash 2%, σ_sob 0.4%), one overlay line per arm —
fold into the Tier-1 elebeam_flash profiling bench (profile BEFORE pruning).

## G4FastSimulationPhysics assessment (2026-07-08): socket without a worthwhile plug

It's a hook (fast-sim manager process + user-supplied G4VFastSimulationModel
per envelope region), not a speedup. Every candidate model for our workloads
is dominated: (1) foil region — physics IS transport/MCS, nothing to
parametrize; the "model" = our external parametric toy, better outside G4
(see [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md)); (2) invariant beamline — an in-G4
teleport model duplicates what MuBeamCat resampling already does at file
level; the better lever is the resampling-surface audit; (3) the ONE
in-scope use: post-tracker calo showers in flash jobs are wasted CPU for the
StrawGasStep observable — but Mu2e's FCL cut algebra (`plane`/`inVolume`
predicates) gives a kill-plane for ZERO code; check its worth in the
Tier-1 elebeam_flash profiling bench; (4) GFlash-on-CsI is textbook only
for a calo-OBSERVABLE line and smears the observable (no Mu2e tune exists)
— unchanged from the May note. NB: Celeritas is the one maintained "plug"
for this socket family (its G4 offload attaches via fast-sim/tracking-manager
hooks) but inherits none of its limits from the socket — see the GPU verdict
+ ceiling arithmetic below; it earns a place only if three things align:
NERSC GPU batch secured AND the standalone pilot clears the e±-curling
question AND a future line is flash-heavy enough (~85% EM) for ≤1.7× to bite.

## Production-practice survey (2026-07-08, web): what experiments actually shipped

Itemized, physics-validated production gains (sources in log/agent report:
ATLAS CHEP2024/2019, CMS Pedro CHEP2018 + CHEP2023, LHCb ReDecay EPJ C79:268,
Belle II CHEP2021, COMET TDR, SHiP arXiv:2512.10520):
- **ATLAS Run-3 ×1.8-2.0 total** = stack of: n/γ Russian roulette ~10%,
  gamma-process range cuts 6-10% (G4 does NOT apply range cuts to
  conv/phot/compt by default!), Woodcock-in-EMEC 17.5%, VecGeom 2-7%,
  B-field switch-off in calo 3%, GammaGeneralProcess 3%, big-lib static
  5-7%, LTO ~5%, G4 version bumps.
- **CMS ×3.4-4.7 total**; single biggest transferable item: **tracking cut
  killing charged <2 MeV in vacuum (0.69× minbias CPU — stops looping e±)**;
  also per-region cuts (0.01mm-1cm span), RR 25-29%, time cut 500ns.
- **LHCb ReDecay ×10-20** (reuse rest-of-event, re-decay signal) — the
  largest single technique anywhere; correlated-sample caveat.
- **Belle II −44%** = option1 EM (−21-27%) + G4 version (−21-30%). **TENSION
  with our thin-foil finding**: option1's G4UniversalFluctuation is
  measurably wrong for thin-layer energy loss (see External survey above) —
  Belle-II-style opt1 swap is CONTRAINDICATED for elebeam_flash/run1b
  (edep observables), possibly OK for mubeam/mustops (count observables).
- **COMET (closest analog)**: no G4-knob paper; their entire strategy is
  staged simulation + resampling (= our MuBeamCat/EleBeamCat architecture).
  SHiP pushed the same idea to histogram-sampled muon transport (>1e4× for
  design loops needing only transported distributions).
- **Transferable shortlist for us**: (1) gamma-process + per-region range
  cuts [config-only A/B]; (2) neutron RR — needs weight-aware EdepAna +
  σ(calo) re-measure; (3) CMS-style looping-e± tracking cut in field
  regions AWAY from ST/tracker (DS graded field is a looping-e factory;
  must be gated off near the flash observable); (4) GammaGeneralProcess
  (verify pin ≥11.1 = free); (5) **resampling-surface audit**: check where
  the MuBeamCat surface sits relative to the varying target — moving the
  per-campaign frozen surface closer to the ST amortizes more per-eval
  transport (COMET/SHiP pattern; potentially the largest architectural
  lever). NOT transferable: Woodcock (needs dense segmented calo),
  frozen showers, whole-list swaps (Minimal already root-caused).

## GPU transport verdict (2026-07-08, web survey): NO-GO for 12 months

- **Celeritas** (v0.6.x; FNAL-adjacent SciDAC): muon EM only "initial
  support"; field transport exists BUT their own CHEP2024 profiling
  (arXiv:2503.17608) documents severe GPU load-imbalance from low-momentum
  "curling" tracks in B-fields — the exact pathology of Mu2e muons
  spiraling in the ~1 T solenoid. Performance case for our muon workload is
  currently NEGATIVE, not just unproven. Real end-to-end speedups on
  CMS/ATLAS-like EM: 1.5-2×/A100 (the 6-32× headline is kernel-only).
- **AdePT**: e±/γ ONLY (no muons, categorically out for workload (a));
  device field-maps still future work; ~2× whole-job degrading to 1.6× at
  high thread counts; custom per-track user data (needed by Mu2eG4 scoring)
  not supported.
- **No FNAL batch-GPU path** fits our hundreds-of-single-core-jobs shape:
  Wilson Cluster ≈ 8×A100+12×V100+18×P100 behind a project request; EAF is
  interactive-analysis-shaped (no mu2ejobsub-like batch).
- **Re-check triggers (12-18 mo)**: Celeritas muon-in-field validation vs
  G4 reference; either project's first non-preliminary production campaign.
- **AMENDED 2026-07-08 (user: FNAL/NERSC batch-GPU access is obtainable)** —
  access removes only 1 of 3 no-go legs (muon physics + integration cost
  stand). Re-ranked uses of batch access: (1) HEPCloud→NERSC as raw BATCH
  CAPACITY (CPU-equivalent) raises the 1,250-slot ceiling with zero code
  risk — our jobs are ideal migrants (CVMFS+tarball, 30-60 min, 2.5 GB;
  Shifter/Podman runs CVMFS); worth more than the GPUs themselves;
  (2) contained Celeritas PILOT on the flash workload: standalone celer-g4
  (GDML export via our existing tooling + DS field map + edep scoring, NO
  art integration) to MEASURE whether 1-100 MeV e± curling in ~1 T hits the
  muon-class load-imbalance — 1-2 wk, Wilson Cluster 8×A100 suffices,
  FNAL-adjacent project = feedback path; (3) SHiP-pattern GPU surrogate +
  ML training: park until per-event multi-fidelity or ~150D lines. Access
  instruments: HEPCloud = experiment-level engagement; Wilson = ServiceNow
  project request; NERSC = ERCAP.
- **Celeritas flash-pilot DESIGN (2026-07-08, ~1-2 wk)**: standalone
  `celer-g4` (bypasses Offline/art + the G4 pin entirely; same-app
  offload-on/off = clean A/B). Components: (1) DS-region GDML subset via our
  existing `tools/gdml_subset_*` extractor (foils+tracker+DS vacuum, simple
  solids — dodges VecGeom exotic-solid gaps), (2) DS field-map sampler →
  Celeritas v0.6 3D map format, (3) EleBeamCat e⁻ → HepMC3 via the existing
  gallery/PyROOT path, (4) scoring = per-volume/shell edep tally as
  flash_edep_total proxy (roughest edge; calorimeter-style tallies only),
  (5) CPU-only reference arm runs on any node — shake down the whole
  harness BEFORE GPU access (Wilson A100 request). Measures: curling
  throughput question, edep-vs-G4 agreement, VecGeom compatibility of a
  Mu2e subset. Does NOT measure: art integration cost, NERSC per-dollar.
  Caveat: reference arm ≠ FTFP_BERT stack — transport benchmark only,
  never compare absolute edep to leaderboard numbers.
- **Celeritas ceiling arithmetic (2026-07-08)**: measured 1.5-2× applies to
  e±/γ transport only → eval-throughput ceiling ~1.7× for flash-shaped
  lines (85% EM grid-hours), ~1.2× for calo-shaped, 1.0× muon-only; before
  three haircuts (unmeasured e±-curling in the ~1T DS field; art-scoring
  integration is the still-"preliminary" part; GPU-node allocation cost may
  lose per-dollar to plain CPU nodes — no published per-dollar win).
  Dominated on effort-adjusted terms by q=40+overlap (2.2-2.5×), HEPCloud
  CPU (2-3×), and range/tracking cuts (15-25%) — pilot value = information
  + positioning, not near-term throughput.

## STATE CORRECTION + RE-RANKING (2026-07-08)

> **STATE CORRECTION + RE-RANKING (2026-07-08).** The "reverted to ShieldingM /
> decision pending" narrative below is STALE: `grep physicsListName
> pipeline_templates/*/template.fcl` shows **FTFP_BERT deployed in all 5
> G4-bearing templates** (mubeam, run1b_mubeam, mustops_ce, mustops_pileup,
> elebeam_flash) — the −8-20% grid CPU and −45% VmPeak are banked. Stepper
> dp745 remains optimal per the 5-arm bench. **Reframe: at the pinned
> ~1,250-slot ceiling ([bo-noise-budget](/concepts/bo-noise-budget.md)), G4 CPU cuts are CAPACITY
> (evals/day), not just latency — but value is line-shape dependent.**
> Open levers, re-ranked 2026-07-08:
> 1. **`elebeam_flash` never profiled** (post-dates this campaign; ~85% of
>    foilsflash grid-hours). Its EM cascade IS the observable → only
>    region-cuts (loose global/tight straw-gas), trajectory-storage cuts,
>    and can't-reach-tracker CommonCut kills are safe candidates. Half-day
>    local bench with the /tmp/g4_mubeam_bench methodology.
> 2. **MinDEDX (−64%) is now infrastructure-cheap**: the blocker
>    (`simParticleList.cc:15` hard `stoppingCode==32`) is a one-line
>    accept-{31,32} patch, and Muse-backed patched-Offline + tarball
>    rebuilds are routine since May (holeradii/prodtarget precedents).
>    Scope mubeam+mustops_ce ONLY (never run1b_mubeam/elebeam_flash — EM
>    observables). Muon-shaped lines: ≈−45% grid-hours ≈ +80% evals/day;
>    foilsflash-shaped: only ~10%.
> 3. Port `beam/epilog_1b.fcl`'s `Mu2eG4CommonCut` block (production-blessed,
>    orthogonal, unbenched here; minRangeCut=1.0 part known ~0% on FTFP_BERT).
> 4. Memory→slots: measured VmPeak 1.1-1.5 GB under FTFP_BERT vs 2500 MB
>    requested — 1800-2000 MB request is the next slot-matching notch.
> 5. Still deferred: importance biasing (2-5×, weight-audit blocker),
>    Celeritas/AdePT (no GPUs/integration), VecGeom (rebuild for 5-15%),
>    G4-MT (hardcoded 1 thread + 1-slot jobs).

## Promoted to default in all G4-bearing templates (2026-05-23)

After the mubeam-only A/B (graph027 vs helicalQR00_02) showed −20% CPU
with sob/calo deltas inside the ShieldingM-self noise floor on the same
x_point (see helicalQR00_02_noise re-run below), the FCL override
`physics.producers.g4run.physics.physicsListName: "FTFP_BERT"` was added
to all 3 G4-bearing templates:

- `pipeline_templates/mubeam/template.fcl`
- `pipeline_templates/run1b_mubeam/template.fcl`
- `pipeline_templates/mustops_ce/template.fcl`

(`concat` has no G4, skipped.) **Caveat: only the mubeam stage has grid
A/B evidence.** `run1b_mubeam` and `mustops_ce` were flipped on the
assumption that the CPU/noise tradeoff is similar; the latter is the
sob-numerator stage, so first-round monitoring is needed. Validation
batch: closed-loop `helicalFT01R00_*` (q=8, max-rounds=1, calo<2e-6
predicted region, launched 2026-05-23 12:22 thread
`closed-FT01-20260523_122205`). Compare per-stage CPU + sob/calo
against the QR00_02/SR02 history to confirm extrapolation holds before
treating this as the new baseline.

## Grid A/B validation (2026-05-23) — FTFP_BERT vs ShieldingM on full mubeam stage

**Configs:** `graph027` (FTFP_BERT) re-runs the same x_point as baseline
`helicalQR00_02` (ShieldingM): dx=0.134, dy=117.19, halflen=351.24, angle=361.
200 jobs each, identical events_per_job/seeds otherwise. Worker logs at
`/pnfs/mu2e/scratch/users/oksuzian/workflow/default/outstage/{70172746,28239926}/`.

**Scoping (load-bearing):** FTFP_BERT was applied to the `mubeam` stage
ONLY — the FCL edit was a single line in
`pipeline_templates/mubeam/template.fcl`. `run1b_mubeam`, `concat`, and
`mustops_ce` ran ShieldingM in both arms. Wall/CPU/Vm numbers below are
mubeam-stage only (extracted from worker logs); sob and calo are
end-of-chain (after 4 stages, of which only one differed).

| Metric | helicalQR00_02 (ShieldingM) | graph027 (FTFP_BERT) | Δ |
|---|---:|---:|---:|
| CPU mean [s] (n=182/196 successful-only) | 199.6 | 178.5 | **−10.6%** |
| Real mean [s] (n=182/196 successful-only) | 205.8 | 189.3 | **−8.0%** |
| CPU mean [s] (n=200/200 all TimeReport) | 228.3 | 182.8 | **−20.0%** |
| Real mean [s] (n=200/200 all TimeReport) | 235.4 | 193.8 | **−17.7%** |
| VmPeak [MB] | 2664 | 1474 | **−45%** |
| VmHWM [MB] | 2337 | 1149 | −51% |
| sob | 3.70 | 3.77 | +1.9% |
| calo/POT | 1.058e-5 | 1.139e-5 | +7.6% |
| scalarized obj (α=1e5) | 2.642 | 2.631 | −0.4% (flat) |

**Selection bias warning on the CPU mean:** The n=182/196 row counts only
jobs whose `.art` made it to /pnfs (post-stage-out success); these jobs
exclude the slow-tail workers that died during PostEndJob (xrootd
FileOpenError per [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md)). The slow-tail
jobs ARE in worker logs (they reach TimeReport before stage-out). Filtering
on /pnfs success preferentially drops slow-tail jobs — and that filter
removed 18 jobs from Shield but only 4 from FTFP, biasing the Shield mean
DOWN more than the FTFP mean. The unbiased n=200/200 comparison (every
worker that emitted TimeReport) puts FTFP wall savings at **−20% CPU /
−17.7% Real**, not the −10.6% I first reported. The wall criterion in
the original plan ("≈ −40 to −50%") still failed, but by less than the
n=182 number suggested.

**Key finding: the local-bench −48% wall did NOT replicate on the grid
(only −8%).** Local bench at 300 events on `helical011` geom predicted
~2× speedup; grid sees ~1.1×.

**Root cause (root-caused 2026-05-23 by pulling per-event timings from
worker logs):** the discrepancy is NOT I/O dilution — it's that the
local bench and the grid A/B measured **different geometries**, and
per-event G4 work is wildly geometry-dependent:

| | per-event wall | geometry |
|---|---:|---|
| local bench (`helical011`) | 266 ms/ev (Shield) → 138 ms/ev (FTFP) = **−48%** | dx=3.12, halflen=55.5, angle=4331 (v1-era) |
| grid (`helicalQR00_02`) | ~40 ms/ev (Shield) → ~36 ms/ev (FTFP) = **−11%** | dx=0.13, halflen=351, angle=361 |

helicalQR00_02's per-event G4 wall is **6.6× lower than helical011's** —
absorber/scattering load is dramatically different across geometries.
FTFP_BERT's savings come from cheaper hadronic models; in a regime where
hadronic cascades are already a small fraction of total G4 work (efficient
absorber, less secondary production), there's less for it to save.

Init times are NOT the differentiator (grid worker logs show 35s FTFP vs
37s Shield — only 2s gap, fully amortized over 5000-event production
runs).

**Operational rule: physics-list speedups are geometry-dependent. A
single-x_point local bench cannot be extrapolated to other geometries.
Always cross-check local-bench speedups against a full grid A/B before
flipping a default;
local bench overestimates by ~5× on this stage, not because of stage
overhead but because of geometry-specific G4 sensitivity.**

**The memory drop is the headline win, not wall.** −45% VmPeak (2.66
→ 1.47 GB) is a substantial OOM-safety margin — production mubeam
flirts with 2.5 GB limits routinely. Memory drop is consistent across
all sampled workers (FTFP_BERT VmPeak clustered at 1473-1524 MB; ShieldingM
clustered at 2663-2667 MB). Mechanism inference: FTFP_BERT's hadronic
table set is much smaller than ShieldingM's, which carries
multi-physics-model coverage (HP-style data files, neutron data, etc.).

**Decision-rule outcome:** plan required wall ≈ −40 to −50% AND sob/calo
within noise to flip default. Wall criterion FAILED (−8% vs target
−40-50%); sob/calo are within noise (sob +1.9%, scalarized obj flat).
Template was reverted to ShieldingM after the A/B chain materialized.
**Re-open question for the user:** does the memory win justify flipping
default anyway? Not a decision-rule call.

**What the A/B does NOT prove (2026-05-23):** "graph027 sob/calo close
to baseline at one x_point" is NOT "FTFP_BERT gives the same physics
as ShieldingM." Specifically:

- **No A/B noise repeat.** We never re-ran helicalQR00_02 with same
  x_point under ShieldingM to measure 200-job run-to-run scatter. The
  +7.6% calo gap could be inside noise or real — undetermined.
  Closest existing noise measurement is the helical001 mustops_ce A/B
  noise test (task #29); whether that floor applies to mubeam-stage
  calo at this x_point is itself unverified.
- **Single x_point.** Physics-list disagreement can be x_point-dependent
  (material composition near stopping target). One geometry near the
  sob-max isn't generalizable.
- **No kinematic spectrum comparison.** Never opened the `.art` files
  to check momentum spectra, vertex distributions, per-material
  stopping rates, or EarlyMuBeamFlash flux into downstream stages.
  Two physics lists can match on summed BO objectives while differing
  on distributions that matter for other analyses.
- **Downstream-stage drift cancellation.** sob/calo are 3-stage
  products (mubeam → run1b_mubeam → concat → mustops_ce). A mubeam
  physics-list shift could cancel by mustops_ce, hiding intermediate
  drift.

**Minimum bar to actually claim physics-equivalence:** re-run
helicalQR00_02 once under ShieldingM (cheap; same template, same
x_point) to measure the noise floor at this point, then re-evaluate
the FTFP_BERT delta against that floor. For a stronger claim, also
compare materialized `.art` momentum spectra. Until then, the only
defensible claim is "FTFP_BERT produces similar end-stage BO
objectives at the helicalQR00_02 x_point."

**Noise floor measured (2026-05-23) — FTFP_BERT delta IS inside the
ShieldingM-vs-ShieldingM noise.** Re-ran `helicalQR00_02_noise` at
the same x_point under default ShieldingM (200 jobs each stage):

| Comparison | Δsob | Δcalo | Δobj (α=1e5) |
|---|---:|---:|---:|
| **Noise** (QR00_02 vs QR00_02_noise) | +1.62% | **+8.32%** | **−1.06%** |
| **FTFP_BERT** (graph027 vs QR00_02) | +1.89% | +7.66% | −0.42% |

The +7.6% calo gap I'd flagged as uncharacterized is actually *smaller*
than the measured ShieldingM-self noise floor (+8.3%). The FTFP_BERT
"effect" on sob/calo/obj is statistically indistinguishable from
run-to-run noise at n=200. **Defensible claim upgraded**:
"FTFP_BERT is physics-equivalent to ShieldingM on the BO objective
at the helicalQR00_02 x_point within measured noise (n=200, 1
A/B repeat)."

Caveats that still hold: single x_point, no kinematic spectrum check.
A grid-A/B at a second x_point + one `.art` momentum-spectrum spot-check
would close the remaining gap.

**Implication for the flip decision**: the original "wall criterion
FAILED" verdict (Δwall=−10.6% << −40% target) still stands as the
reason NOT to flip on speed alone. But the OOM-safety motive
(−45% VmPeak) is now unencumbered by any "but did it perturb the
physics?" concern at this x_point. Re-open: flip FTFP_BERT default
for memory-driven OOM safety. Decision still pending.

Raw rows in `leaderboard_bo_helical_v2.tsv`:
- `helicalQR00_02`: sob=3.700 calo=1.0577e-05 obj=2.6423 (ShieldingM)
- `helicalQR00_02_noise`: sob=3.760 calo=1.1457e-05 obj=2.6143 (ShieldingM)
- `graph027`: sob=3.770 calo=1.1386e-05 obj=2.6314 (FTFP_BERT)

**Footgun re-confirmed:** the `--config-name helicalQR00_02_ftfp` CLI flag
silently fell through to auto-increment `graph027` due to the pending-row
collision in propose_one — see [graph-runner](/drivers/graph-runner.md) for the workaround
(clear pending TSV row before reusing a name from the CLI).

---


## Summary
Local A/B measurements of Geant4 production-cut / field-stepping / physics-list
knobs on (a) the CE harness `g4test_03.fcl` and (b) the real `mubeam` stage.
The point: identify FCL overrides that cut CPU per event without shifting the
leaderboard metrics (`s_over_sqrt_b`, `calo_per_pot`) outside Poisson noise.
One arm is safe (`minRangeCut=0.05`); two intuitively-promising arms turned
out to be unsafe (`Minimal` physics list breaks the workflow; `bfieldMaxStep`
/ `protonProductionCut` / `stepMinimum` are noise-floor).

## Key facts

- **FCL override path** for all of these knobs:
  `physics.producers.g4run.physics.<knob>` (NOT `physics.physicsList.*`).
- **Local bench location:** `/tmp/g4_speed_bench/` (CE harness) and
  `/tmp/g4_mubeam_bench/` (real mubeam stage with helical011 geom). All
  variants `#include` a baseline fcl and override one knob.
- **CE harness bench (g4test_03.fcl, 1000 events, baseline 86.9 ± 1.7%):**
  - `minRangeCut 0.01→0.1 mm`: −8.9% CPU
  - `minRangeCut 0.01→0.5 mm`: −15.6% CPU
  - `minRangeCut 0.01→1.0 mm`: −18.5% CPU
  - `protonProductionCut`, `bfieldMaxStep`, `stepMinimum`: all within ±2%
  - `physicsListName "Minimal"`: −82% CPU (4.5× speedup), but drops
    hadronic / decay processes.
- **mubeam stage bench (300 events, helical011 geom, baseline 58 s wall):**
  - `minRangeCut=0.05`: −6% CPU. TargetStops 33→35, PolyStops 7→8, FlashOut
    1→1. All Δ < 1σ Poisson — safe.
  - `physicsListName "Minimal"`: −82% CPU. **TargetStops 33→0**,
    **PolyStops 7→0**, **FlashOut 1→0**. Workflow is broken — no muons
    reach the foils despite EmStandard being included. `Minimal` is OUT
    as a speedup arm even though the workflow is "muon transport +
    geometric stop classification."
- **Why Minimal failed (root-caused 2026-05-22 via SimParticleAnalyzer on
  unfiltered g4run output, 100 events each, same input file & geom):**
  - Same 108 mu- per run (resampler is deterministic on seed).
  - Baseline: 8 mu- end in Target_Al Z-window (5471 < z < 6371 mm), all
    with `stoppingCode=32 (muMinusCaptureAtRest)`, all with KE=0.
    54 / 108 mu- already at rest (mu2eMaxSteps, KE=0), and 54 die
    spread through the TS / TSdA / downstream — physical mix.
  - Minimal: **0 mu- end in the target Z-window. 0 muMinusCaptureAtRest.**
    The "same" 54 already-at-rest mu- still end at vid=1128 with KE=0
    (these are the resampler ghosts — input file already had them stopped).
    The OTHER 54 in-flight mu- all end at **z = 52,265 mm** (world
    boundary) with `stoppingCode=182 (CoupledTransportation)` and
    KE distribution unchanged from baseline (20 mu in [1,10] MeV,
    34 mu in [10,100] MeV). Median end-Z in Minimal = 52,265 mm vs
    36.9 mm baseline.
  - Verdict: option **(a)** muons fly straight through the Al — they
    don't stop *anywhere*; `Minimal` lacks `muIoni` so muons don't lose
    energy in matter, transport-only the whole way out of the world.
    "End-process == wrong code" or "stop in wrong volume" are wrong
    framings; muons keep their multi-MeV KE all the way to the world
    boundary.
- **Diagnostic recipe** (kept in `/tmp/g4_mubeam_bench/`):
  - `diag_simp_baseline.fcl` / `diag_simp_Minimal.fcl` — minimal path
    `[genCounter, protonTimeOffset, beamResampler, g4run, g4consistentFilter]`
    + `SimParticleAnalyzer` reading `g4run` (no stop filters), `outputs: {}`,
    100 events.
  - `analyze_diag.py` — PyROOT summary: per physics-list table of mu-
    end-Z bins, stoppingCode histogram, end-KE histogram (also mu+).
  - Wall: baseline 59 s, Minimal 10 s; together comfortably <2 min.
- **Recommended grid A/B arm:** single override
  `physics.producers.g4run.physics.minRangeCut: 0.05` on mubeam +
  run1b_mubeam stages. Expected −5–10% wall reduction; verify
  `calo_per_pot` and `s_over_sqrt_b` stay within leaderboard noise on at
  least 2 replicates.
- **Env-var gotcha:** locally running `mu2e -c <fcl>` with a geom overlay
  in a non-standard directory requires BOTH `FHICL_FILE_PATH` (for
  `#include "bench_baseline.fcl"`) AND `MU2E_SEARCH_PATH` (for
  `services.GeometryService.inputFile: "bench_geom.txt"`) to be prepended.
  Setting only `MU2E_SEARCH_PATH` fails the include resolution silently
  with exit 90 "Can't find file".

## Cross-links
- Related: [scalarized-objective](/concepts/scalarized-objective.md), [bo-helical](/projects/bo-helical.md), [mmackenz-workflow](/external/mmackenz-workflow.md), [production-target-stickman](/concepts/production-target-stickman.md)
- Source files: `/tmp/g4_mubeam_bench/run_bench.sh`,
  `/tmp/g4_mubeam_bench/bench_*.fcl`
- External: [Geant4 production cuts](https://geant4-userdoc.web.cern.ch/UsersGuides/ForApplicationDeveloper/html/TrackingAndPhysics/cuts.html)
- Skills: should have used `coding-with-fhicl` for the FCL composition

## Alternative physics lists — benched 2026-05-22 (300 events mubeam, helical011 geom, parallel)

| Arm | Wall (s) | Speedup | TargetStops | PolyStops | Verdict |
|---|---:|---:|---:|---:|---|
| baseline ShieldingM | 79.83 | — | 33 | 7 | control |
| `QBBC` | 38.18 | −52% | crash | crash | **broken** — `ProcessCode` enum |
| `FTFP_BERT` | 41.38 | **−48%** | 37 | 6 | **viable**, Δ ≤ 1σ Poisson |
| `FTFP_BERT_EMV` | 42.10 | −47% | 39 | 6 | viable, Δ ≤ 1σ |
| `MinDEDX` | 29.13 | **−64%** | 34 | 8 | viable! (see caveats below) |

**FTFP_BERT is ~2× faster than ShieldingM** with stop counts unchanged
within Poisson noise. Zero code change. This dwarfs `minRangeCut=0.05`
(−6%) and is the recommended first grid A/B arm.

**Stacking bench (2026-05-22, 4-way parallel, 300 events, helical011 geom,
files `/tmp/g4_mubeam_bench/bench_FTFP_BERT_rc{05,10}.fcl` +
`run_bench3.sh`):**

| Arm | Wall (s) | vs baseline | vs FTFP_BERT alone | TargetStops | PolyStops |
|---|---:|---:|---:|---:|---:|
| baseline ShieldingM | 55.12 | — | — | 33 | 7 |
| FTFP_BERT | 21.08 | −62% | — | 37 | 6 |
| FTFP_BERT + rc=0.05 | 20.70 | −62% | −1.8% | 33 | 7 |
| FTFP_BERT + rc=0.10 | 21.08 | −62% | 0% | 34 | 5 |

**`minRangeCut` does NOT meaningfully stack on FTFP_BERT.** It gave
−6% on ShieldingM (additive) but stacks to ~0% within run-to-run jitter
on FTFP_BERT. Mechanism (best inference): ShieldingM's bottleneck was
EM cascade work that minRangeCut suppresses; FTFP_BERT already has a
lighter EM + faster hadronic (BERT) so the cuttable secondaries aren't
the bottleneck anymore. **Implication for the grid A/B: use
`FTFP_BERT` alone — second knob buys nothing and adds an audit-trail
defense.** (Caveat: baseline ShieldingM's wall is inflated by parallel
contention here vs prior 5-way bench (55.12s vs 79.83s) because it ran
solo for ~35s after the 3 FTFP arms exited. Cohort-internal FTFP
ratios are clean since they have identical contention profiles.)

**Aggressive `minRangeCut` sweep at 3k events (2026-05-22, 5-way parallel,
`run_bench4.sh` + `bench_FTFP_BERT_rc{50,100,500}_3k.fcl`):** confirms
the 300-event finding wasn't statistics-limited.

| Arm | Wall (s) | vs baseline | vs FTFP_BERT | TargetStops (σ≈18) | PolyStops (σ≈10) |
|---|---:|---:|---:|---:|---:|
| baseline ShieldingM | 114.97 | — | — | 342 | 96 |
| FTFP_BERT | 49.24 | −57% | — | 356 (+0.8σ) | 80 (−1.6σ) |
| FTFP_BERT + rc=0.5 mm | 47.28 | −59% | −4.0% | 349 (+0.4σ) | 93 (−0.3σ) |
| FTFP_BERT + rc=1.0 mm | 48.29 | −58% | −1.9% | 368 (+1.4σ) | 90 (−0.6σ) |
| FTFP_BERT + rc=5.0 mm | 47.82 | −58% | −2.9% | 363 (+1.2σ) | 89 (−0.7σ) |

Pushing minRangeCut to 5.0 mm (500× the 0.01 mm default) gives <4% wall
reduction over FTFP_BERT alone, with no monotone trend across the three
rc values — it's noise. **Stop counts are remarkably robust to
minRangeCut: even rc=5.0 mm shifts TargetStops by only 1.2σ.**
Mechanism inference: minRangeCut controls EM secondary tracking depth,
not the parent muon trajectory; TargetStopFilter only cares whether the
muon got to the Al, so killing the gamma/electron cascade around it
doesn't move that count. Important corollary: the CE-harness's
`−18.5% at rc=1.0` (g4test_03) does NOT transfer to mubeam — CE-harness
extrapolation overstates minRangeCut's value at the production stage.

**`QBBC` failure (rc=1) — Mu2e Offline incompatibility:** PostEndJob
exception "There was one or more phyics processes that are not in the
ProcessCode enum. Number of processes: 1." QBBC introduces a G4 process
that `Offline/MCDataProducts/inc/ProcessCode.hh` doesn't enumerate.
Would need an enum extension + Offline rebuild — not worth it when
FTFP_BERT delivers comparable speedup with zero patches. **Implication:
the Mu2e ProcessCode enum is a hidden constraint on physics-list
substitution; any candidate must be checked at runtime, not just on
process-coverage grounds.**

**`MinDEDX` surprise — works despite lacking `G4StoppingPhysics`:**
Agent prediction said TargetStops=0 (no `muMinusCaptureAtRest`).
Empirical: 34 vs baseline 33. **Root cause: `TargetStopFilter` selects
on kinematic state (KE≈0 in Al volume), not on end-process code.**
MinDEDX has `muIoni`, so muons physically slow to rest in the foils;
the absence of capture-at-rest just means the muon sits at the end of
its step list (mu2eMaxSteps or step-limiter), which still satisfies the
filter's KE≈0 cut. This refines the
earlier-recorded Minimal failure mode: `Minimal` fails not because it
lacks `G4StoppingPhysics`, but because it lacks `muIoni` so muons fly
ballistically through the Al at multi-MeV KE (see "Why Minimal failed"
above).

**MinDEDX kinematic validation (2026-05-22, SimParticleAnalyzer on
unfiltered g4run, 100 events; diagnostic in
`/tmp/g4_mubeam_bench/diag_simp_MinDEDX.fcl` + `analyze_diag2.py`):**
- mu- ending in Target_Al Z (5471<z<6371 mm): **MinDEDX 9 vs baseline 8**
  (Δ < 1σ Poisson). Same 9 muons have KE≈0.
- End-Z histogram bin-by-bin matches baseline: MinDEDX 87/3/5/0/9/0/4 vs
  baseline 88/1/6/0/8/0/5 across the 7 Z windows.
- End-KE distribution **bit-identical** to baseline both globally
  (54@KE≈0, 20@[1,10] MeV, 34@[10,100] MeV) and restricted to the
  target window (8 @ KE≈0 baseline, 9 @ KE≈0 MinDEDX).
- Total SimParticles: baseline 35,827 vs MinDEDX 1,315 = **27× fewer
  secondaries**. This is where the −64% wall comes from — MinDEDX skips
  the EM cascade in TS material.
- **Caveat — different at-rest stoppingCode label:** MinDEDX uses
  `code_31` (likely `hMinusCaptureAtRest` or a generic atomic-capture
  handler) where baseline uses `code_32 = muMinusCaptureAtRest`. Both
  fire on 54 muons; **kinematic outcome identical** but the process-code
  metadata differs. **Production-blocker CONFIRMED (2026-05-22):**
  `stoppedMuMinusList(simh)` in
  `Offline/Mu2eUtilities/src/simParticleList.cc:15` does
  `inpart.stoppingCode() == ProcessCode::muMinusCaptureAtRest` (hard
  equality on code 32). Called by `CeEndpoint_module.cc:120`,
  `FlatMuonDaughterGenerator_module`, and `Pileup_module`. MinDEDX
  code-31 stops are silently dropped → `mustops_ce` stage's CeEndpoint
  generator throws. MinDEDX is **NOT** usable as a drop-in for the full
  production chain. To use MinDEDX in production needs one of: (a)
  patch `simParticleList.cc:15` to accept {31, 32} (Muse-backed Offline
  rebuild — see [muse-backing-pattern](/external/muse-backing-pattern.md) for the helical-plug
  precedent), or (b) re-tag code 31 → 32 in
  `Mu2eG4CustomizationPhysicsConstructor` before the SimParticle is
  written out. Either is a bigger change than the bench warranted.
  **Recommendation: use `FTFP_BERT` (−48% wall, zero code change,
  fires code 32) for the grid A/B instead.**

**MinDEDX open questions:**
- Does any downstream stage filter on `stoppingCode == 32`? If no,
  MinDEDX is production-ready at −64% wall.
- `G4Decay` presence unverified — but irrelevant for TargetStops
  generation (DIO is generated downstream from TargetStops).
- Calo flash spectrum unchecked; calo_per_pot impact unknown (measured
  in run1b_mubeam, not mubeam — would need separate bench).

## Alternative physics lists — pre-bench analysis (kept for context)
The `Minimal` failure mode generalizes: the **required** constructors for
the mubeam workflow are (a) an EM constructor that defines `muIoni`
(any `G4EmStandardPhysics[_optN]`), (b) `G4DecayPhysics`, (c)
`G4StoppingPhysics` (owns `muMinusCaptureAtRest`). Drop anything else.

**`physicsListDecider.cc` accepted names** (`Offline/Mu2eG4/src/physicsListDecider.cc`,
inspected against Musings/Offline/v10_07_00):
- 3 Mu2e-defined hard-coded names at lines 69-81:
  - `Minimal` → `Mu2eG4MinimalModularPhysicsList` (transportation +
    step-limiter only; no muIoni, no capture — broken for mubeam)
  - `MinDEDX` → `Mu2eG4MinDEDXModularPhysicsList` (EM only; has muIoni
    but **no `G4StoppingPhysics`** → muons ionize and slow to rest but
    do not capture. Useful as an *ablation* arm to confirm root cause
    from the other direction.)
  - `ErrorPhysicsList` → `G4ErrorPhysicsList` (for track-error
    propagation; unrelated to production)
- Anything else is delegated to `G4PhysListFactory` at line 89 — accepts
  `ShieldingM` (the default), `Shielding`, `FTFP_BERT`, `QGSP_BERT`,
  `QBBC`, and `_EMV`/`_EMX`/`_EMY`/`_EMZ` suffixed variants.
- Every list (including the Mu2e-defined ones) gets
  `Mu2eG4StepLimiterPhysicsConstructor` + `Mu2eG4CustomizationPhysicsConstructor`
  appended at lines 101-104.
Ranked candidates:
- **`FTFP_BERT_EMV`** — stock G4 list with "EM opt1" (designed for HEP
  production). Includes Stopping + Decay + EM-with-muIoni. Qualitatively
  1.5×–2× vs ShieldingM. Zero code change if `physicsListDecider.cc`
  already registers it (TBD).
- **Custom ModularPhysicsList** "Mu2e-Lite" =
  `G4EmStandardPhysics_option1 + G4DecayPhysics +
  G4StoppingPhysics(useMuonMinusCapture=true)`. Largest possible
  speedup — close to Minimal's −82% but workflow-safe. Needs a new
  constructor class in `Mu2eG4/src/` registered via
  `physicsListDecider.cc`.
- **`QGSP_BERT_EMV`** — equivalent to FTFP_BERT_EMV for our muon-only
  stage (no hadronic showers); listed only as backup.
- **Footgun:** `G4StoppingPhysics(useMuonMinusCapture=false)` silently
  kills capture. The default is `true` — keep it.

## G4 ODE stepper (`physics.producers.g4run.physics.stepper`)

**Default (Offline v10_07_00):** `G4DormandPrince745` — adaptive embedded
5(4) RK, set in `Offline/Mu2eG4/fcl/prolog.fcl:47`. Already the modern
"fast" choice; limited headroom expected.

**5-arm bench (2026-05-22, FTFP_BERT × stepper, 3k events parallel,
`run_bench5.sh` + `bench_FTFP_{dp745,helixSR,helixIE,rk4,bs23}_3k.fcl`):**

| Arm | Wall (s) | vs dp745 | TargetStops | PolyStops |
|---|---:|---:|---:|---:|
| **FTFP_dp745 (default)** | **47.46** | **—** | 356 | 80 |
| FTFP_helixSR | 50.83 | +7.1% | 363 (+0.4σ) | 88 (+0.8σ) |
| FTFP_helixIE | 49.66 | +4.6% | 354 (−0.1σ) | 89 (+0.9σ) |
| FTFP_rk4 | 54.97 | +16% | 344 (−0.7σ) | 95 (+1.5σ) |
| FTFP_bs23 | 95.25 | **+101%** | 340 (−0.9σ) | 94 (+1.4σ) |

**`G4DormandPrince745` is already optimal — no stepper swap helps.**

- **Helix-aware steppers LOSE** (5-7% slower) despite TS being solenoidal.
  Mubeam transport spans the whole geometry (DS, calo, world), not just
  the TS solenoid; helix steppers assume pure-helix motion and degrade
  in non-helical regions. dp745's adaptive step expansion in
  low-gradient regions wins on net.
- **`G4BogackiShampine23` is 2× slower** — counterintuitive for an
  adaptive 3(2). At the tight `epsilonMin/Max = 1.0e-5` in
  `prolog.fcl:53-54`, the lower-order method needs dramatically more
  steps to hit the same error bound. Lower-order adaptive RK is an
  anti-pattern at this tolerance.
- **Subtle PolyStops pattern (caveat):** all 4 non-default steppers
  gave higher PolyStops (88-95) than dp745 (80), clustering closer to
  baseline ShieldingM's 96. Joint probability of 4 same-side draws by
  chance ≈ 6%. May indicate dp745+FTFP has a small systematic PolyStop
  suppression vs other steppers; TargetStops unaffected. Re-bench with
  more replicates if PolyStops matter to the BO objective.

**All 10 registered stepper names** (enumerated in
`Offline/Mu2eG4/src/Mu2eWorld.cc:440-477`; everything else throws
`cet::exception("GEOM") "Unrecognized stepper"` at line 479):
- `G4DormandPrince745` (default, adaptive 5(4))
- `G4DormandPrince745WSpin`
- `G4ClassicalRK4` (classic fixed-order)
- `G4ClassicalRK4WSpin`
- `G4ImplicitEuler` / `G4ExplicitEuler` (low-order)
- `G4SimpleRunge` / `G4SimpleHeum` (2nd-order)
- `G4HelixImplicitEuler` / `G4HelixSimpleRunge` (helix-specialized,
  designed for solenoidal fields like our TS)
- `G4BogackiShampine23` (adaptive 3(2), lower-order embedded RK)

**Hidden constraint (`physicsListDecider.cc:152-157`):** if
`decayMuonsWithSpin: true`, the code throws unless stepper is one of
`G4ClassicalRK4WSpin` / `G4DormandPrince745WSpin`. The default chain
(MuBeamResampler + epilog_1b) does NOT set `decayMuonsWithSpin`, so any
of the 10 above are legal in our mubeam path.

**Spin-equation note:** the WSpin variants instantiate the stepper at
order 12 with `G4Mag_SpinEqRhs` instead of the default order-6
`G4Mag_UsualEqRhs` — i.e. they integrate spin alongside position/momentum.
Don't enable WSpin unless you need spin output; it doubles state per
step.

## Untapped FCL knobs (audited 2026-05-22, Mu2eG4Config.hh + prolog.fcl)

All of these are reachable from MuBeamResampler chain via
`physics.producers.g4run.<group>.<knob>` with one-line FCL override — no
code change, no Offline rebuild. NOT YET BENCHED.

**Per-region production cuts (highest FCL-only lever, ~5–20% expected):**
- `physics.minRangeRegionCuts: {<region>: <mm>, ...}` — `Mu2eG4Config.hh:143`,
  applied in `Mu2eWorld.cc:276-312`, defaulted unset (commented in
  `prolog.fcl:19`). Bigger lever than global `minRangeCut` because tight
  cuts can be retained at the Al target / TS while loosened elsewhere.
  Risk: collapsed calo secondaries if `CalorimeterMother` ≥ 1 mm.

**Output / runaway hygiene (near-zero physics risk):**
- `TrajectoryControl.mcTrajectoryMomentumCut` — default 50 MeV/c
  (`prolog.fcl:85`). Raising to 200 cuts trajectory storage for low-p
  tracks; transport-CPU unchanged, I/O shrinks.
- `TrajectoryControl.defaultMinPointDistance` — default 500 mm
  (`prolog.fcl:83`); `perVolumeMinDistance` table at `prolog.fcl:88-101`
  (PSVacuum/CalorimeterMother = 15 mm).
- `ResourceLimits.maxStepsPerTrack` — default 100000
  (`Mu2eG4ResourceLimits.cc:5`, enforced in `Mu2eSpecialCutsProcess.cc:64`).
  Hard-kills runaway tracks; lowering catches cascade pathologies.
- `ResourceLimits.maxStepPointCollectionSize` / `maxSimParticleCollectionSize`
  — default 100000 each; **truncate output silently** if hit, dangerous to
  lower without measuring saturation rate first.

**Composable per-step / per-stack kill predicates (powerful but risky):**
- `Mu2eG4SteppingOnlyCut`, `Mu2eG4StackingOnlyCut`, `Mu2eG4CommonCut`
  (DelegatedParameter) — `Mu2eG4Config.hh:228-230`. Predicate algebra
  (`union/intersection/plane/inVolume/notInVolume/pdgId/notPdgId/isNeutral/`
  `isCharged/kineticEnergy/globalTime/primary/constant`) lives in
  `Mu2eG4Cuts.cc:744-769`. Composable kills entirely in FCL. Example:
  `{type: kineticEnergy, cut: 10, pdg: [11,22]}` would kill low-E EM
  secondaries. Risk: easy to break calo_per_pot.

**Particle-kill recipe (2026-06-10, audited not benched).** The
infrastructure for "kill all neutrons/gammas/etc." is a pure-FCL
one-liner — no source patch, no muse rebuild:

- FCL slot path: `physics.producers.g4run.Mu2eG4StackingOnlyCut`
  (stacking action = fires at track CREATION; best CPU savings since
  killed tracks never get propagated at all). Default in
  `mu2eg4runDefaultSingleStage` (prolog.fcl:184-192) is the
  pre-defined `mu2eg4CutNeutrinos` table at prolog.fcl:173-176, which
  is itself just `{type: pdgId pars: [12,-12,14,-14,16,-16]}`.
- Drop-in: `union` of the existing neutrino cut + a new `pdgId` cut
  listing the PDGs to kill. Neutrons=2112, gammas=22, electrons=11,
  positrons=-11.
- Cut handler: `ParticleIdCut::stackingActionCut` at Mu2eG4Cuts.cc:536
  → sorted-vector binary search on PDG, O(log N) per track.

**Mode-by-mode safety:** For `pot_only` (prodtarget Path D edep
harvest) killing neutrons is essentially free physically (most exit
the plates anyway) and saves ~20-40% CPU; killing gammas/e± saves
more but **shifts the edep zero-point** since EM cascades dominate
plate heating — would require a fresh pt001 baseline before mixing
with ptX01-X05 leaderboard rows. For `mubeam`/`run1b_mubeam`/
`mustops_ce` (sob/calo objectives) killing e± **destroys the calo
signal entirely** — never apply there.

**Other physics knobs:**
- `physics.strawGasMaxStep` — default −1 (disabled), `prolog.fcl:61`.
  Local step limiter in straw gas only (tracker stage, not mubeam).
- `physics.limitStepInAllVolumes` — default false, `prolog.fcl:63`.
  Globally applies `bfieldMaxStep` everywhere (typically a slowdown).
- `physics.noDecay` — PDG-list of particles whose decay is disabled;
  empty by default (`prolog.fcl:14`).

## Framework-level fast-sim options (audited 2026-05-22, ranked for mubeam)

**Production-deployable today:**
- **G4ImportanceProcess / Russian-roulette biasing** — **highest absolute
  leverage (2–5× estimated)** for mubeam by killing muons that miss the
  TS aperture and splitting survivors near TSdA. Requires `G4IStore`
  wired into `Mu2eWorld` (~1 week). **BLOCKER:** downstream must be
  weight-aware — `s_over_sqrt_b`, `calo_per_pot` need to propagate
  per-track weights. Major analysis audit; not a drop-in.
- **Kill-shell at world boundary** — `G4UserStackingAction` flag.
  Estimated 2–8% by killing back-scattered secondaries. Cheap fallback
  if importance biasing's weight audit blows up.

**Defer / not applicable:**
- **AdePT** (CERN GPU EM transport) — no GPUs on Mu2e grid; muons not
  offloaded yet. CHEP 2025: still in integration phase. Non-starter
  today.
- **Celeritas** (ORNL/FNAL GPU) — muon EM support recently added
  (brems/ioni/pair-prod) but still e±/γ-first. **No Mu2e integration
  exists.** Mubeam gain ~0 today without GPUs. CMS Run-3 is the only
  production deployment. Revisit in ~12 months.
- **VecGeom** — vectorized geometry. 5–15% on tube-heavy geometry like
  ours but **requires Offline rebuild** to link/swap solid impls.
  Tessellated-plug fragility (see [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md))
  raises overlap/boundary risk. Not worth it for marginal gain.
- **G4-MT** — Mu2e has `Mu2eG4MT_module.cc` but hardcodes
  `SetNumberOfThreads(1)` (line 82). No FCL exposure of nThreads. Even
  if exposed: 1-slot grid jobs → MT overhead dominates, near-0% real
  gain. Per-thread RNG re-seeding is the main code change.
- **GFlash / G4FastSimulationManagerProcess** — parametrized EM showers.
  **Wrong stage for mubeam** (no calo). Worth re-evaluating for
  `run1b_mubeam` if/when calo stage is benched.
- **EM physics opt0–4** — already covered: `FTFP_BERT_EMV` (opt1) vs
  `FTFP_BERT` (opt0-ish default) was −1.4% in our 5-arm bench (see
  table above). Diminishing returns; FTFP_BERT default is essentially
  HEP-tuned EM already.

## Mu2e community precedent (audited 2026-05-22)

**No prior collaboration fast-sim work on mubeam exists.** No Musing
tagged `fast/lite/smoke/quick`; no `FastSim`/`GFlash` in Offline; no
benchmark notes from mmackenz; `Mu2eG4MT_module.cc` ships but no
production benchmark on-disk; `mu2ewiki.fnal.gov` pages paywalled (HTTP
402 from this env), DocDB unchecked.

**Two non-obvious facts that change our priors:**

1. **Production POT-beam already uses `minRangeCut: 1.0` (100× the
   `0.010 mm` default in `Offline/Mu2eG4/fcl/prolog.fcl:16`).** Sites
   that override: `Musings/SimJob/Run1Bak/Production/JobConfig/beam/`
   `{epilog_1b.fcl:18, POT.fcl:71, POT_extmon.fcl:71,`
   `POT_validation.fcl:113}` + `cosmic/S1DSStops.fcl:77` +
   `extmon/extmonbeam_g4s2.fcl:149`, all tagged "coarse range for this
   stage." **Implication:** our `0.05/1.0/5.0` mubeam sweep arms are
   *more conservative* than what production already trusts for sibling
   beam stages. The reason the Run1B mubeam stage doesn't have this
   override is asymmetric inheritance (next point), not a deliberate
   safety choice.

2. **mmackenz mubeam (and our autoresearch chain mirroring it) `#include`s
   `Production/JobConfig/pileup/epilog_1b.fcl`, NOT
   `JobConfig/beam/epilog_1b.fcl`.** These are different files in
   different subdirs. The `beam/epilog_1b.fcl` carries both
   `minRangeCut: 1.0` AND a `Mu2eG4CommonCut` block (volume/KE/pdgId
   kills via `KillerVolumesCache` from `Mu2eG4Cuts.cc:456`); the
   `pileup/epilog_1b.fcl` carries neither. **Two unexplored axes for
   free speedup on our mubeam stage:** (a) raise `minRangeCut` to
   production-blessed `1.0` (already shown ~0% extra on top of
   FTFP_BERT in our 3k bench — confirms no harm), (b) port the
   `beam/epilog_1b.fcl` `Mu2eG4CommonCut` block. (b) is orthogonal to
   physics-list choice and not yet benched.

**FTFP_BERT is genuinely new ground for mubeam.** Mu2e's `ShieldingM`
choice was made for hadronic backgrounds at the production target
(pion-production Bertini transition); no published Mu2e benchmark of
swapping it out *for the mubeam stage only* — our −48% finding appears
to be the first.

## Open questions / TODO
- **Production-blocker check (MinDEDX):** grep Mu2e Offline + workflow FCLs
  for selectors on `stoppingCode == 32` (`muMinusCaptureAtRest`). Candidates:
  `mustops_ce`, `CeEndpoint` generator, `StoppedMuonResampler`. If any of
  these filter on code 32, MinDEDX's code-31 stops are invisible
  downstream and the −64% wall is unusable as-is.
- **G4FastSimulationManagerProcess / GFlash** is the right tool for the
  *calo* stage (`run1b_mubeam`) where EM showers dominate, NOT for mubeam
  where the cost is muon transport through the TS. Don't invest in GFlash
  until run1b_mubeam is locally profiled and confirmed CPU-bound on calo
  EM showers. Pure `G4EmStandardPhysics` (no FastSim) would be slower than
  MinDEDX since it still generates the full secondary cascade — MinDEDX's
  −64% comes from cascade suppression (27× fewer SimParticles), not from
  EM-only-ness.
- **Stacking-action cuts (orthogonal axis):** `Mu2eG4StackingAction.cc` +
  `Mu2eG4CustomizationPhysicsConstructor` may already kill known-irrelevant
  secondaries; tightening them is independent of physics-list choice and
  composable with MinDEDX/FTFP_BERT.
- Run a 2-replicate grid A/B at `minRangeCut=0.05` against current
  best-known config (e.g. `helicalP01`) to confirm leaderboard-noise
  preservation on full-statistics jobs.
- Try `minRangeCut=0.1` as a more aggressive arm if 0.05 holds.
- Re-test `bfieldMaxStep` / `stepMinimum` directly on mubeam, not CE
  harness — they were noise-floor on g4test_03 but muon helical motion
  through the TS may be more sensitive.
- Bench the Mu2e-Lite modular list (custom
  `G4EmStandardPhysics_option1 + G4DecayPhysics + G4StoppingPhysics`)
  only if MinDEDX is blocked by code-32 downstream filters; otherwise
  MinDEDX is the empirical winner and a custom list is overkill.
