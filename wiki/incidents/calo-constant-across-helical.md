# All harvest metrics are constant across helical configs

**Type:** incident
**Status:** **resolved (2026-05-17)** — canonical `muse tarball` shipped: mgit Mu2eG4 sparse checkout of v13_12_10 + helical-plug.patch, built against Run1Bak backing in `/exp/mu2e/app/users/oksuzian/autoresearch_muse/`. The muse-built `Code.tar.bz2`'s `setup.sh` calls `muse setup $CODE_DIR -q e29 prof p094`, putting the local lib ahead of CVMFS by link/path order (no LD_PRELOAD needed). Validated on grid via helical002 clusters 27881180 mubeam + 27881183 run1b_mubeam.
**Updated:** 2026-05-17

## Summary
**The entire harvested metric vector is bit-identical across six independent
helical configs** (helical002 through helical007 — Phase 1 q=5 CL-mean batch
plus the helical002 baseline). Not just `calo_per_pot`: also `sob=2.720000`,
`ce_seen=310485`, `ce_abs_eff=0.0004777939236622608` (16 digits), and
`muminus_stops=120396`. helical001 alone differs at the sob level (sob=2.71 vs
2.72, ce_seen=601124 — but that's because helical001 ran with 2× the
mustops_ce input pool; once normalized, `ce_abs_eff` agrees to 0.4%).

The leaderboard now has 7 rows with `obj=+2.108` for six of them. **BO has
zero signal across the helical knob space** — the objective surface is flat.

Concat outputs DO differ per config (MD5-distinct, sizes 263659862–263669674
bytes), so the geometry override IS reaching the mubeam→concat path. But the
downstream `run1b_mubeam` + `mustops_ce` outputs (the metrics BO reads) are
invariant, even with `MaxEventsToSkip` and `baseSeed=1` fixed.

This is much broader than the original "calo-only" framing. The TSdA helical
knobs (dx, dy, halflen, z0, angle) have **no measurable effect on any BO
input** in our current pipeline.

The output `*.root` files differ in MD5 (timestamps/metadata in art records),
but a direct ROOT readback of the 16 stopmat bins from file 0 of each config
shows **every bin matches to the integer** (e.g. BronzeC608=3750, COL5Poly=774,
CarbonFiber=1, total nonzero=5056 for both). The histograms are identical.

## Impact

**Helical-mode BO is not learning anything.** Both terms of `obj = sob −
α·calo_per_pot` are constant across the knob space. The Phase 1 q=5 CL-mean
batch returned five geometrically distinct configs (helical003–007 span dx ∈
[0.5, 2.65], halflen ∈ [52.7, 269.8], angle ∈ [94, 498]°) and all five
produced `sob=2.72, obj=+2.108` to the same precision as the helical002
baseline. The GP has no gradient to fit; further BO iterations are pure
random sampling masquerading as optimization.

Before running any more helical iterations, we need either:
1. A different metric the helical geometry actually affects, OR
2. A pipeline change that lets the helical override propagate into
   `run1b_mubeam`/`mustops_ce` outputs (not just `concat`).

Continuing to spend grid time on q=5 batches at ~500 jobs/iter is wasted until
this is resolved.

## Root cause (2026-05-16 — definitive)

**The helical-plug C++ code does not exist in Offline `v13_12_10`** (the
backing of the `Run1Bak` Musing our pipeline uses). The `tsda.helical.*`
parameters in our geom file are silently ignored — there is no consumer.

- `/cvmfs/.../Musings/Offline/v13_12_10/Offline/{GeometryService/src/TSdAMaker.cc,
  Mu2eG4/src/constructTSdA.cc, BeamlineGeom/{src,inc}/TSdA.{cc,hh}}`
  contain **zero occurrences** of the string `helical`.
- mmackenz's local Offline tree at
  `/exp/mu2e/app/users/mmackenz/run1b/Offline/Mu2eG4/src/constructTSdA.cc:322`
  has the patch:
  ```cpp
  const bool build_helical = _config.getBool("tsda.helical.build", false);
  if(build_helical) { ... finishNesting("TSdAHelicalTube", ...) ... }
  ```
  His `mmackenz_workflows/config_v100..v111` priors that show per-config
  calo variance were produced with this patched build (Muse area at
  `/exp/mu2e/app/users/mmackenz/run1b/`, built into
  `build/al9-prof-e29-p094/`).

Every other observed behaviour is consistent with "geometry actually
identical across configs":
- G4 sees the same TSdA every iteration → same secondaries → same SimParticle
  multiplicity per event → same nts.mubeam histograms.
- The ~0.1% file-size variation in `.art` outputs (637590 vs 641700 bytes etc.)
  is numerical noise / ordering, not real G4 variance.
- Event counts in `dts.MuBeamFlash.art`, `sim.TargetStops.art`, etc. are
  bit-identical across configs (15/21/17 in files 0/1/2, all three configs).

**The fix is not a harvester change.** It requires switching the pipeline's
Offline source so the helical plug is actually built:

1. ~~**Adopt mmackenz's Muse area** — change `MUSING` in `pipeline.py:45` and the
   `Code/setup.sh` packaged into `Code.tar.bz2` so grid workers source
   `muse setup /exp/mu2e/app/users/mmackenz/run1b` instead of
   `Run1Bak/setup.sh`. Worker nodes must mount `/exp/mu2e/app/` (they do).~~
   **FAILED 2026-05-16.** This was attempted (helical002 smoke test, clusters
   `84316127` mubeam + `27871333` run1b_mubeam, 400 jobs total). All jobs
   returned only `.log` files, zero `.art` outputs. Worker stderr showed
   `Error from pushd /exp/mu2e/app/users/mmackenz/run1b > /dev/null: exit code 1`
   followed by an 1800 s sleep loop. **Grid workers do NOT mount `/exp/mu2e/app/`** —
   only `/cvmfs/*` is visible (confirmed via `df -h` in the worker log). The
   prior wiki claim "Worker nodes already mount `/exp/mu2e/app/`" was wrong.
   Failed tarball preserved at
   `/exp/mu2e/data/users/oksuzian/autoresearch_grid/helical002/mubeam/Code/setup.sh`
   for forensic reference. `pipeline.py` was reverted to the stock Run1Bak
   musing source pattern with a warning comment at `write_code_tarball`.
2. **Cherry-pick the patch** into our own local Offline build (more work, more
   maintenance, but isolates us from mmackenz changing his tree).
3. **Wait for the patch to land in Offline trunk** (no ETA known).
4. **Publish mmackenz's patched build to CVMFS** as a new Musing — requires
   Mu2e infra cooperation but is the cleanest fix; mirrors how `Run1Bak` is
   already distributed today.
5. **Ship a subset of patched libraries** (e.g. `libmu2e_Mu2eG4.so`, ~47 MB)
   inside `Code.tar.bz2` and `LD_PRELOAD`/`LD_LIBRARY_PATH`-prepend them in
   `setup.sh`. ABI compatibility against the rest of `v13_12_10` is untested;
   risky but tractable without infra cooperation.
6. **Build our own patched Offline against the Run1Bak Musing's backing**
   (`muse backing SimJob Run1Bak` + `muse setup -q p094` + `muse build`),
   ship only the rebuilt `libmu2e_Mu2eG4.so` in `Code.tar.bz2`,
   `LD_PRELOAD` it from `setup.sh`. Same delivery mechanism as option 5, but
   the library is rebuilt against the exact Musing tree the workers use, so
   ABI compatibility is guaranteed by construction rather than untested. See
   [[muse-backing-pattern]] for the workflow.

**Option 6 was chosen and landed 2026-05-17.** Build artifact:
`/exp/mu2e/app/users/oksuzian/Offline_helical/build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so`
(47 MB, contains `mu2e::makeHelicalPlug` + patched `constructTSdA`).

## Why this happens (originally suspected, now superseded)

**Pipeline shipping is verified-clean.** For each of helical002/003/007:
- per-config geom files in `<cfg>/geom/` differ at the knob lines (e.g.
  helical002 `dx=4.1148` vs helical003 `dx=2.1078`).
- the cnf tarball carries the correct per-config `Code/autoresearch_<cfg>_geom.txt`,
  the correct materialized `mu2e.fcl` (geom basename substituted), and the
  correct per-config `jobpars.json` auxin block.
- the grid stdout confirms `Geometry file: /srv/no_xfer/Code/autoresearch_helical003_geom.txt`
  is loaded by GeometryService.

**G4 IS running per-config.** Every `.art` output of `run1b_mubeam` differs
by config (file sizes from `/pnfs/.../outstage/<cluster>/00/00000/`):

| file | helical002 | helical003 | helical007 |
|---|---|---|---|
| dts.MuBeamFlash.art | 637590 | 641700 | 641692 |
| sim.TargetStops.art | 139789 | 143885 | 143888 |
| sim.IPAStops.art | 146769 | 150880 | 150864 |
| sim.PolyStops.art | 603224 | 607382 | 607348 |
| dts.EarlyMuBeamFlash.art | 115601 | 119697 | 119699 |
| **nts.mubeam.root** | **8301** | **8301** | **8301** |

**The bug is in the harvest data source.** The `nts.mubeam.*.root` TFileService
output (which carries `TargetMuonFinder/stopmat`) is byte-identical across
configs, even though every `.art` file in the same outstage directory differs.
The harvester at `pipeline.py:462` (`_extract_calo_per_pot`) reads exclusively
from `nts.mubeam.*.root`, so it sees the invariant histogram and misses the
per-config variance that IS present in the `.art` files.

Working hypothesis for *why* `TargetMuonFinder/stopmat` is invariant: the
module appears to read from an upstream SimParticle collection that's
populated before the helical plug has any geometric effect (likely fed from
the fixed `MuBeamCat` resampler pool with pinned seeds), so its per-event
stopping-material classification doesn't depend on the per-config helical
geometry. The per-config G4 transport is fully present in the `.art` outputs
but invisible to this analyzer module.

## Key facts

- **Six configs, identical metrics:** helical002–007 all have
  `sob=2.720000`, `ce_seen=310485` (exact integer match),
  `ce_abs_eff=0.0004777939236622608` (16 digits match),
  `calo_per_pot=6.12242472e-06`, `calo_total=479.0`,
  `muminus_stops=120396`. Geometric span is non-trivial: dx ∈ [0.5, 4.11],
  dy ∈ [82.4, 84.6], halflen ∈ [52.7, 269.8], angle ∈ [94, 498]°.
- helical001 differs only because it ran with a doubled mustops_ce input pool
  (ce_simulated_events=1.94e6 vs 1.0e6); `ce_abs_eff` agrees with the others
  to 0.4%, well within A/B noise from [[grid-job-completion-check]].
- **Concat outputs DO differ per config:** MD5-distinct, sizes
  263659862–263669674 bytes — the geometry override IS reaching mubeam.
- Direct ROOT readback of file 0: `TargetMuonFinder/stopmat` has 16 bins, all
  match across configs (BronzeC608=3750, StoppingTarget_Al=141,
  StainlessSteel=230, Ti6Al4V=66, COL5Poly=774, ...). File MD5s differ;
  histogram contents do not.
- The run1b_mubeam input `MuBeamCat.txt` is the same file for both configs
  (fixed two-file resampling pool of `sim.mu2e.MuBeamCat.Run1Baa.001430_*.art`).
- `MaxEventsToSkip: 319542` and `SeedService.baseSeed: 1` are both pinned in
  `pipeline_templates/run1b_mubeam/template.fcl:9,17`, so resampled draws are deterministic.
- `mustops_ce` similarly pins `MaxEventsToSkip: 100720` and `SeedService.baseSeed: 1`.

## Action items

- [x] **STOP helical BO iterations until resolved.** No signal → no learning.
- [x] Falsified initial hypothesis (`.art`-vs-`nts.mubeam.root` data source
  bug): per-event counts and SimParticle multiplicity are *also* bit-identical
  in the `.art` files. Tiny ~0.1% file-size variance is numerical noise.
- [x] Root cause identified: `tsda.helical.*` knobs are unimplemented in
  Offline `v13_12_10`. Only mmackenz's local patched Offline implements them.
- [x] **Switch pipeline to mmackenz's Muse area** — **ATTEMPTED AND FAILED.**
  `pipeline.py` `write_code_tarball` was modified to source mmackenz's Muse
  area; helical002 smoke test (clusters 84316127 mubeam + 27871333 run1b_mubeam,
  400 jobs total) failed with `pushd ... exit code 1` because grid workers
  only have `/cvmfs/*` mounted. Reverted in same session with explanatory
  comment at `pipeline.py:210-216`. The "worker nodes already mount /exp" line
  above was a false assumption.
- [x] **Choose a remediation path** — option 6 (self-built patched lib via
  Run1Bak-backed Muse build). Cleaner than option 5 because backing against
  the exact CVMFS Musing the workers use guarantees ABI compat by construction.
- [x] **Build patched `libmu2e_Mu2eG4.so`** at
  `/exp/mu2e/app/users/oksuzian/Offline_helical/` (~47 MB, contains
  `mu2e::makeHelicalPlug` + patched `constructTSdA::build_helical` branch).
  Patch extracted as `helical-plug.patch` (5879 bytes, +112 lines) from
  mmackenz's uncommitted working tree, applied to a fresh `rsync` of
  `Musings/Offline/v13_12_10/Offline/`. Standard Mu2e dev workflow:
  `muse backing SimJob Run1Bak` + `muse setup -q p094` + `muse build -j 8`.
- [x] **Wire lib into `pipeline.py:write_code_tarball`** (constant
  `PATCHED_LIB`, copied into `Code/lib/` of the tarball). `setup.sh` gained
  `export LD_PRELOAD="$mydir/lib/libmu2e_Mu2eG4.so:$LD_PRELOAD"`. (Initial
  attempt used `LD_LIBRARY_PATH` prepend instead — failed because the `mu2e`
  binary's rpath includes the CVMFS lib path, which outranks `LD_LIBRARY_PATH`.
  `LD_PRELOAD` outranks rpath per glibc rules.)
- [x] **Differential local test 2026-05-17:** with a geom file where
  `tsda.helical.build=true` but `dx/dy/halflength` are deleted, the patched
  lib throws `SimpleConfig: No such parameter tsda.helical.dx` (proving the
  `build_helical` branch fired); the stock CVMFS lib runs through G4 init
  without complaining (proving the knob was silently ignored).
- [x] **Grid smoke-test (Task #40, validated 2026-05-17):** helical002 resubmitted
  through canonical muse-tarball pipeline (clusters 27881180 mubeam + 27881183
  run1b_mubeam + 91469973 concat + 91470122 mustops_ce). Harvest summary:
  `sob=0.967`, `ce_seen=153533`, `ce_abs_eff=0.000305`, `calo_per_pot=9.33e-07`.
  Every metric differs substantially from the pre-fix flat plateau (`sob=2.72`,
  `ce_seen=310485`, `ce_abs_eff=0.000478`, `calo_per_pot=6.12e-06`). The
  patched lib is firing on workers. Leaderboard now has the broken-era
  helical002 row plus the canonical-path row for direct comparison.
- [ ] Update [[bo-helical]] from `halted` → `active` and resume q=5 BO
  iterations (this entry's blocker is now lifted).

## Cross-links
- Related: [[bo-helical]] (calo penalty is dead in this project), [[scalarized-objective]] (α derivation doesn't apply for helical), [[harvest-denominator-bug]] (different bug, same harvest module), [[grid-job-completion-check]], [[scan-broken-codes-too-narrow]], [[stickman-sd-unwired]]
- Source files: `pipeline.py:437` (_CALO_EXTRACT_SCRIPT), `pipeline.py:462` (_extract_calo_per_pot), `pipeline_templates/run1b_mubeam/template.fcl:9,17` (deterministic resampler seeds)
- Raw evidence: `helical001/harvest/summary.json`, `helical002/harvest/summary.json`
