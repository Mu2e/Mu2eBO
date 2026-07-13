---
name: bo-helical
description: 5D BO over helical-plug inner namespace (dx, dy, halflength, z0, angle) with TSdA core + foils pinned at v111
type: project
---

# bo-helical — 5D helical-plug BO

**Type:** project
**Status:** superseded — retired from active runs 2026-05-29 after 4D Pareto saturation (HV +1.6% over last 76 evals, hit rate 62%→38%). Champion **helical045 obj=2.533 (2026-05-18)** stands but top-5 are likely G4 sibling-overlap artifacts (see [[tsda-disc-helical-sibling-overlap]]). **`HelicalMode` class DELETED from code 2026-07-12** (was the canonical test-fixture mode; fixtures migrated to `foils`). `leaderboard_bo_helical*.tsv` remain on disk; the OFF-repo `gp_predict_helical.py`/`botorch_predict_helical.py`/`overlay_knob_locations.py` in mmackenz_table_plots still call `bo.HelicalMode()` and now break at that call. Active BO line is [[bo-foils]] / [[bo-foilsflash]].
**Updated:** 2026-07-12 (HelicalMode code retired; fixtures moved to foils)

## Summary
Second BO mode in `autoresearch_bo_michael.py` (select with `--mode helical`).
Optimizes the **inner** `tsda.helical.*` namespace (dx, dy, halflength, z0, angle)
with the [[tsda]] core + foil stack + degrader + COL5 all pinned at v111 values.
Different physics from [[bo-michael]] (foil-stack mode): the helical plug
provides calo rejection by absorbing low-energy beam particles before they
reach the calorimeter, complementing the foil-stack approach.

## Key facts
- **Search space (live 4D Option A, all Real):** (z0 and rin derived; see Option A coupling)
  - `tsda.helical.dx` ∈ [0.01, 5.0] mm
  - `tsda.helical.dy` ∈ [40, 400] mm
  - `tsda.helical.halflength` ∈ [25, 500] mm
  - `tsda.helical.angle` ∈ [60, 720] deg — widened from 540 on 2026-05-21 because 15/47 v2 rows
    were rail-running at ≥525° (2 exactly at 540); best obj (QR00_02=2.64) is interior at 361°,
    so corners are exploration-driven, not optimum-driven, but the GP should be allowed to
    explore further before declaring 540 the ceiling.
  - Source of truth: `autoresearch_bo_michael.py:HelicalMode.build_space` +
    `gp_predict_helical.py:BOUNDS`. Keep these two in sync.
- **Pinned constants (v111-exact):**
  - TSdA core: `hasTSdA=true, r4=600, rin=80, halfLength4=12.5, z0=4195,
    materialName=StoppingTarget_Al`
  - Helical fixed: `nsteps=2000, material=StoppingTarget_Al,
    useTwistedBox=true` (default; pinned per-config in emitted geom.txt so
    grep recovers the solid-impl branch). Set `HelicalMode.HELICAL_USE_TWISTED_BOX
    = False` to A/B against the legacy tessellated impl — see
    [[tessellated-solid-facet-orientation]]. **One-off A/B override** (no
    source flip): `USE_TWISTED_BOX=0 graph.run …` reads
    `autoresearch_bo_michael.py:374` env-var, takes effect at module-import
    time, propagates to subprocesses via inherited env (`os.getenv("USE_TWISTED_BOX",
    "1") != "0"`). Source: `constructTSdA.cc`
    `makeHelicalPlug` dispatcher landed 2026-05-26 (source-only;
    grid tarball repackage still pending).
  - Foils: `holeRadius=0`, `radii = {125 × 38}` (bigger foils to block calo stops)
  - Degrader: `build=false, rotation=180`
  - COL5: `material1Name=COL5Poly`
- **Baseline:** `geom_run1_a.txt` + manually patched
  `tracker.inDS2Vacuum=true, ds2.halfLength=3825, ds.hasServicePipes=false`
  (mirrors v111 exactly). **NOT** `geom_run1_b_v06.txt` — that one configures
  a single-plate stopping target (`halfThicknesses={5.0}, radii={600,600},
  z0InMu2e=4195`) which is incoherent with the v111 38-foil stack we emit
  (`radii={125 × 38}`) and causes `VirtualDetector_ST_In outside DS2Vacuum`
  in G4. See [[geom-run1a-vs-run1b]].
- **Best-known prior (v111):** `dx=2, dy=85, halflen=150, z0=4345, angle=360`
  → sob=2.12, calo=1.62e-6, **obj=1.958**.
- **Leaderboard knob-correlation snapshot (2026-05-25, n=152, 24 feasible)**:
  Pearson on feasible-only for sob, all-rows for calo —
  `corr(dx, sob)=−0.35`, `corr(dy, calo)=+0.43`, `corr(angle, calo)=−0.37`,
  `corr(halflen, sob)=+0.19`. Translation: **thinner ribbon wins sob,
  wider ribbon costs calo, more total twist buys calo headroom, longer
  plug helps weakly**.
- **Dominant infeasible failure mode**: `dy > 120 mm AND halflen < 50 mm`
  (wide-and-stubby — blade sweeps full beam envelope but too short to
  provide momentum-selective filtering, just dumps multi-scatter into
  calo). 128/152 rows infeasible, this region is most of them.
- **Empirical best-feasible basin (with correct G4TwistedBox semantics —
  dx=half-thickness, dy=half-height, halflen=z-half-extent, angle=total
  twist; ribbon centered on beam axis at x=y=0)**:
  - `dx ≈ 0.2–1.3 mm` (full ribbon thickness 0.4–2.6 mm; ≪ Al X₀=89 mm,
    so minimal multi-Coulomb scattering — every winner has dx<1.3 mm)
  - `dy ≈ 75–110 mm` (full width 150–220 mm; matches post-TS muon
    envelope ~100 mm; going wider intercepts peripheral bg that
    scatters into calo)
  - `halflen ≈ 150–250 mm` (full length 300–500 mm)
  - `angle ≈ 500–700°` (1.4–2 full turns over the plug)
  - **Design parameter: twist rate `angle/halflen ≈ 2–4 deg/mm`** sets
    the spatial pitch of the rotating slab. Larmor-pitch-matched charged
    particles see ≈constant material the whole way; mismatched particles
    integrate ~50% on average. This is the actual helical-filter physics
    (NOT a hollow tube — the ribbon-vs-tube distinction matters because
    a beam-axis particle is INSIDE the absorber for half the rotation,
    not always outside it).
  - **Current objective-leader (2026-05-26): `helicalL02` sob=3.33,
    calo=2.46e-6, obj=3.08** at `dx=0.01, dy=108.6, halflen=249.0,
    angle=471.8`. Top 3 by obj (α=1e5): L02 (3.08) > graph023
    (sob=3.28, calo=3.08e-6, obj=2.97) > helical050a (sob=3.21,
    calo=2.54e-6, obj=2.96). All three cluster in same basin
    (dy~100-110, hl~200-260, ang~460-480, near-zero dx); all three
    sit just above 2e-6 calo cap (1.2-1.5× cap).
  - **NG02 sob-champion NOT obj-leader** (2026-05-26 correction): NG02
    (sob=3.61 at ang=720) is the raw-sob max but obj=2.53 because
    calo=1.08e-5 burns ~1.08 of obj via α=1e5 penalty (α·calo=1.08).
    Wiki briefly called NG02 "champion"; corrected here. The
    rail-extension RA01-04 sweep shows angle saturates near 720-760
    (RA01 sob=3.59 ≈ NG02) — confirms NG02 IS the sob basin max,
    just not where the BO objective points.
  - Prior champion: `helical051a` (sob=2.76, calo=1.71e-6) at
    `dx=0.23, dy=109.5, halflen=132.5, angle=538` — basin center, just
    slightly short. NG02 confirms the natural next-probe direction
    (longer halflen + more twist).
  - **Angle rail saturates near 720–760 (2026-05-25)** — RA rail-extension
    sweep at (dx=0.23, dy=110, hl=200) probed ang∈{760,800,830,860}
    past NG02's 720. RA01 (ang=760) sob=3.59 calo=9.64e-6 obj=2.63 ≈ NG02
    in noise; RA02 (ang=800) sob=3.58 obj=2.58 — flat. Conclusion:
    further angle widening past 720 does NOT pay off on this ridge;
    treat 720 as the effective upper. RA03/RA04 (ang=830, 860) still
    in flight 2026-05-25 20:34 as confirmation.
  - **4D BO is saturating (2026-05-26)** — GP-predicted sob ceiling moved
    4.28 → 4.33 across the two refits after the silent-pass strict gate +
    retro-scan recovered 5 clean QR00_* rows. Sub-noise gain. Clean top-5
    (post-retro-scan-broken purge): helical050a obj=2.96, PC02R00_03 2.67,
    RA04 2.65, QR00_02 2.64, RA03 2.64 — spread 5× in twist density, no
    unified design rule (Larmor-band dy≈109 mm is the load-bearing
    coincidence, not twist rate). **Next-leverage axes lie outside the
    current 4D space:** (a) COL5 material as a joint knob (single-knob
    {air,poly} in bo-michael, never joint-fit with helical — see
    [[col5-shield]]); (b) TSdA4 disc thickness promoted to 5th dimension
    (current top-5 exploit the 18 mm disc/plug overlap as a free 4%
    absorber per [[tsda-disc-helical-sibling-overlap]]); (c) hybrid
    offset-plug × helical class (mmackenz v48/v55-v68 scraped but never
    BO'd). Multi-agent synthesis 2026-05-26 (Explore agents on champions,
    non-helical classes, first-principles physics) explicitly recommends
    against more rounds of pure 4D refinement. Tasks #146/#147/#148.
  - **Cross-model saturation confirmation (2026-05-26)** — BoTorch qNEHVI
    refit (`botorch_predict_helical.py`, .venv-botorch) on 122 clean pts
    gives max-predicted sob=4.06, vs sklearn GP's 4.33 on 163 pts. Both
    plateau around 4 → saturation is model-independent, not a sklearn
    artifact. qNEHVI picks rail-run (5/8 pin a bound: hl=25 ×3, angle=720,
    dy=400, dx=5.0) — also a saturation signal: acquisition can't find
    interior gain so chases corners. Only pick 6 (dx=3.55, dy=73,
    angle=130, calo=1.29e-6) lands in a genuinely fresh feasible region.
    Implementation gotcha: `botorch_predict_helical.py:73-78` applies
    `_ncrit` unconditionally; missing the `_use_twisted_box` gate that
    `gp_predict_helical.py:84-113` added 2026-05-26. Result: BoTorch
    over-filters twisted-box configs (122 vs 163 training rows). Apples-
    to-apples comparison requires porting the twisted-box gate.
    **Post-cleanup re-confirmation (2026-05-27, n=175 v2 main TSV)**:
    sklearn trains on 165 v2 (drops 7 silent-pass + 3 disk-broken-flag);
    botorch trained on 117 v2 (drops 5 "unverified rows" + ~43 more via
    N_crit gate) — 48-row delta. qNEHVI picks 3/8 failed N_crit≤2000.
    **Fix landed 2026-05-27** at `botorch_predict_helical.py:63`:
    `DEFAULT_NSTEPS = bo.HelicalMode.HELICAL_NSTEPS` (was hardcoded 100).
    Post-fix: 165 v2 (matches sklearn), Pareto 348, predicted sob_max
    4.01 → **4.22**, N_crit-failing picks 3/8 → 1/8, pick #0 shifted
    from `dx=5.0, sob=1.4` to `dx=0.041, sob=3.1` (acquisition now
    exploring the right corner). botorch `_is_clean` keys on
    `report.json` while sklearn keys on `report.tsv` — different files,
    coincidentally same 7-row drop at n=175.
  - **qNEHVI picks land inside the predicted cloud, not on the Pareto
    edge — by design, not by bug**. The cloud
    (`botorch_predict_helical.py:199-203`) is a 2D density of posterior
    **means** over ~1M Sobol points. qNEHVI maximizes expected HV
    improvement over posterior **samples** (`SobolQMCNormalSampler(
    sample_shape=128, seed=42)` at `botorch_predict_helical.py:240`),
    not means. A candidate with mediocre mean but large posterior std
    has sample-tails that punch past the current Pareto front in
    (sob, -log10 calo) — so its expected HV gain is high even though
    its mean lands interior to the cloud. Amplifiers: loose ref-point
    `(REF_SOB=-0.5, REF_NEG_LOGCALO=-8.0)` widens the HV envelope so
    modest tails register as improvement; `prune_baseline=True` shrinks
    the baseline to the non-dominated subset (more candidates qualify);
    joint q=8 batch optimization diversifies picks across X to maximize
    *joint* HV rather than clustering at one edge spike. Reading a
    cyan-diamond at (sob~2.5, calo~3e-6): "posterior uncertain enough
    here that the upside tail is worth sampling" — canonical
    exploration-vs-exploitation signature. Want picks that hug the
    predicted Pareto edge instead? Switch to posterior-mean-greedy or
    UCB with small β; qNEHVI is doing the opposite job intentionally.
  - **Calo-feasible region exists at small-dy / long-hl (2026-05-25)** —
    CB rail (small-dy/sub-node) explored: CB01 (dx=0.8, dy=60, hl=300,
    ang=520) sob=1.31 **calo=1.38e-6** is the first strictly feasible
    row (under 2e-6 cap) outside the prior basin. CB02 ang=540 borderline
    (calo=2.26e-6); CB03/CB04 over cap. CB sweep traces a clean
    sob/calo trade-front: dx 0.4→0.8 buys feasibility at cost of sob.
    Useful Pareto-front anchor at low-sob feasible end.
- **Priors loaded:** 10 (v100, v101, v102, v103, v104, v106, v107, v108, v109,
  v111). v110 missing sob; v105 in the v100s range but has no helical plug.
- **Prior parsing:** TSV scraper only captures `tsda_helical_build` (boolean),
  not the inner knobs. `hel_load_priors()` cross-references TSV (for sob/calo)
  with `mmackenz_workflows/config_v##/run1b_beam/geom.txt` (for the 5 knobs).
- **Leaderboard:** `leaderboard_bo_helical.tsv`
  (cols: config dx dy halflength z0 angle sob calo alpha obj)
- **Proposal dir:** `bo_helical_proposals/`
- **Preflight dir:** `bo_helical_preflight/`

## Cross-links
- Driver: [[autoresearch-bo-michael]] (`--mode helical`)
- Autonomous-exploration driver: [[closed-loop-runner]] (multi-round Pareto
  picks; replaces the operator-paced "compute 5 picks → launch 5 chains →
  refit → repeat" loop used through helicalP01-P05)
- Sibling modes: [[bo-michael]], [[bo-foils]]
- Related concepts: [[tsda]], [[scalarized-objective]], [[fixed-geometry-constraint]]
- Priors: [[mmackenz-priors]]
- Source: `autoresearch_bo_michael.py`
- Reference geom: `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/config_v111/run1b_beam/geom.txt`

## Phase 1 result (2026-05-16) — flat objective surface
- q=5 CL-mean batch (helical003–007) returned 5 geometrically distinct
  configs spanning the full bounds box. **All five harvested to
  `sob=2.72000, obj=+2.108`**, bit-identical to the helical002 baseline.
  ce_seen=310485 and ce_abs_eff agree to 16 digits across all six configs.
- Leaderboard has 7 rows; the helical knobs produce zero measurable signal
  in our pipeline. Concat outputs DO differ per config — the failure is
  somewhere between concat and run1b_mubeam/mustops_ce.
- See [[calo-constant-across-helical]] for full evidence + **definitive
  root cause**: helical-plug C++ does not exist in Offline `v13_12_10`
  (Run1Bak Musing). Only mmackenz's local patched Offline at
  `/exp/mu2e/app/users/mmackenz/run1b/Offline/Mu2eG4/src/constructTSdA.cc:322`
  consumes `tsda.helical.build`. **No further helical BO iterations until
  pipeline switches Musing to mmackenz's Muse area.**

## Offline-version dependency (critical)
- This project **requires** the patched `constructTSdA.cc` with the
  `build_helical` branch. Stock Mu2e Offline (any version up through
  `v13_12_10`) silently ignores `tsda.helical.*` parameters.
- mmackenz's `mmackenz_workflows/config_v100..v111` priors show real
  per-config calo variance precisely because they were produced against
  his patched build (`/exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/`).
- Our pipeline's `MUSING` constant at `pipeline.py:45` points to
  `Run1Bak/setup.sh` → unpatched Offline.
- **2026-05-16 simple-swap attempt failed.** Modifying `write_code_tarball`
  to source `muse setup /exp/mu2e/app/users/mmackenz/run1b` and submitting
  helical002 to grid (clusters 84316127 mubeam + 27871333 run1b_mubeam,
  400 jobs total) returned only `.log` files. Worker stderr: `pushd
  /exp/mu2e/app/users/mmackenz/run1b > /dev/null: exit code 1`. **Grid
  workers only mount `/cvmfs/*`** — the entire `/exp/mu2e/app` namespace is
  invisible to jobs. Reverted same session.
- **Resolved 2026-05-17 via canonical muse-tarball path (option 7).**
  Final form: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/` is an mgit
  sparse checkout (Mu2eG4 only) of `Offline/v13_12_10` + helical-plug.patch,
  backed by `SimJob/Run1Bak`. `muse build -j 8` then `muse tarball` produces
  a 56 MB `Code_helical_base.tar.bz2` whose `setup.sh` does
  `muse setup $CODE_DIR -q e29 prof p094` — the local lib wins via Muse's
  normal link/path order, no LD_PRELOAD needed. `pipeline.py:write_code_tarball`
  extracts this base, drops in the per-config geom + a `setup_post.sh` that
  extends `MU2E_SEARCH_PATH`, and repacks. An earlier same-day variant shipped
  the raw `libmu2e_Mu2eG4.so` + LD_PRELOAD (worked but non-canonical); retired
  in favour of `muse tarball`. See [[muse-backing-pattern]] for the build
  recipe and [[calo-constant-across-helical]] for the full incident trail.

## q=5 batch result (helical013-017, 2026-05-17/18)
Second q=5 CL-mean batch (post helical008-012). Final leaderboard rows:

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 013 | 0.50 | 110.0 | 25.0 | 4250 | 540 | 1.00 | 2.56e-08 | 0.997 |
| 014 | 0.50 |  92.5 |  31.9 | 4438 | 432 | 2.00 | 1.23e-06 | 1.877 |
| 015 | 0.50 |  93.8 | 257.6 | 4298 | 283 | 1.73 | 2.84e-06 | 1.446 |
| 016 | 0.50 |  85.6 | 102.2 | 4347 | 245 | **2.61** | 3.995e-06 | **2.210** |
| 017 | 2.55 |  85.6 | 130.8 | 4500 | 421 | 1.65 | 1.81e-06 | 1.469 |

## q=5 batch result (helical018-022, 2026-05-18)
Third q=5 CL-mean batch — GP refining the dx=0.5, dy~85-95, z0~4300-4400 ridge.

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 018 | 0.50 | 85.0 |  25.0 | 4396 |  75 | 2.68 | 5.45e-06 | 2.135 |
| 019 | 0.50 | 85.7 | 242.7 | 4250 | 372 | 1.61 | 2.35e-06 | 1.375 |
| 020 | 0.50 | 92.3 |  25.0 | 4346 | 428 | 1.96 | 9.22e-07 | 1.868 |
| 021 | 4.61 | 85.9 |  29.4 | 4287 | 210 | 1.75 | 2.89e-06 | 1.461 |
| 022 | 0.50 | 96.7 | 184.3 | 4423 |  66 | 2.49 | 4.60e-06 | 2.030 |

- helical016 still the global best (obj=2.210); helical018 is 2nd at 2.135.
- **Pattern: dx wants the lower bound.** helical010/014/015/016/018/019/020/022
  all at dx=0.5 (8 of last 11 evaluations). GP keeps pushing dx toward 0;
  consider widening `tsda.helical.dx` lower bound below 0.5 for Phase 2.
- **Cluster long-tail:** helical015 mustops cluster 27819553 and helical019
  mustops cluster 28186753 both took >4 hours to drain — large angle / large
  halflength geometry seems to make mustops_ce slower per job, dragging the
  whole batch's wall clock to ~6 hours.
- **Speed lever applied 2026-05-18:** `STAGES["mustops_ce"]["events_per_job"]`
  dropped 10000 → 5000 in `pipeline.py`. Total CE stats halve (1M → 500k);
  per-A/B noise test on helical001, sob agreement is ~0.4% which is well
  below the q=5 batch-to-batch spread (~0.5–1.5 sob units). Effective
  long-tail reduction depends on how much of the slow geometry's per-job
  cost is event-driven vs. fixed; first batch to benefit is helical023-027.
- **Every mustops_ce submit in the batch hit token contention** (helical018,
  019, 020 all FAIL submit-mustops_ce within 5 min of each other). Previously
  only mubeam/run1b_mubeam/concat were known to collide; mustops_ce is just as
  vulnerable. See [[concurrent-token-contention]].
- **NEW failure mode (helical019):** list-outputs succeeded but cached one
  stale `NNNNN.<hash>` path; harvest 4hr later choked on FileNotFoundError in
  calo extraction subprocess (ROOT couldn't open one file → entire calo step
  bailed → `calo_per_pot: null` → evaluate refused). Fix: re-run `list-outputs
  run1b_mubeam` to refresh state, then re-harvest. See [[stage-out-rename-race]]
  "latent variant" section.
- Six recovery scripts written this batch live in `/tmp/helical_resume_*.sh`;
  `helical_resume_mustops.sh` is new (mustops_ce submit→poll→list→harvest→eval).

## q=5 batch result (helical023-027, 2026-05-18 morning)
Fourth q=5 CL-mean batch — first batch run with the halved `mustops_ce`
events_per_job (10k → 5k); helical023 set a new global best.

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 023 | 0.50 | 110.0 | 300.0 | 4500 | 287 | **2.62** | 2.42e-06 | **2.378** |
| 024 | 0.50 |  87.1 | 168.0 | 4398 |  60 | 2.45 | 4.33e-06 | 2.017 |
| 025 | 5.00 | 110.0 |  25.0 | 4500 | 154 | 1.71 | 3.07e-06 | 1.403 |
| 026 | 5.00 |  40.0 | 300.0 | 4250 | 358 | 1.34 | 4.46e-06 | 0.894 |
| 027 | 0.50 |  98.6 |  25.0 | 4500 | 196 | 2.62 | 5.56e-06 | 2.064 |

- **helical023 is the new global best (obj=2.378)**, beating helical016
  (2.210) by 8%. It sits at the *upper-corner* of the GP's exploration —
  dy=110 (upper bound), halflen=300 (upper bound), z0=4500 (upper bound),
  angle=287, with dx pinned at 0.5 (lower bound) as the entrenched pattern.
  Same calo as helical015 (~2.4e-6) but with 50% higher sob — the upper-z0
  / upper-halflength corner appears to provide deeper calo rejection at
  equal CE pass.
- **dx=0.5 pattern now 10 of last 14 evaluations** (014/015/016/018/019/
  020/022/023/024/027). GP is confident in lower-bound dx; Phase 2 should
  widen the dx lower bound below 0.5.
- **First clean q=5 launch:** 300s stagger held through all 5 SUBMITS_DONE
  with zero token-race retries — first time at q=5. Then chains drifted into
  sync at the concat boundary (helical026/027 both submit-concat at 09:50
  and 09:54, both hit rename-race variant 2 on stale `state/mubeam_outputs.txt`).
  Both recovered via relist+resume. See [[stage-out-rename-race]] variant 2
  and [[concurrent-token-contention]] drift-after-launch note.
- **Wall clock:** 09:25 → 11:00 = **95 min** from first FULL_START to last
  CHAIN_DONE. helical018-022 batch was ~140 min. Halving mustops_ce
  events_per_job + cleaner stage-out (only two relist+resume detours, no
  mustops_ce token races) shaved roughly 30%.
- **Race recovery cost:** ~17 min per chain (FAIL → relist → re-submit →
  poll → list → mustops_ce); both 026 and 027 finished within the batch
  window so no chain held back the overall completion time.

## q=5 batch result (helical028-032, 2026-05-18 noon)
Fifth q=5 CL-mean batch — GP doubling down on the helical023 upper-corner:
028/029 are near-neighbours of 023 (same dy=110, halflen=300, z0=4500;
varying only angle), 031 probes the lower-bound dy=40 with high sob/calo,
032 explores the opposite anti-corner (dx=5, z0=4250).

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 028 | 0.50 | 110.0 | 300.0 | 4500 |  60 | 2.38 | 4.17e-06 | 1.963 |
| 029 | 0.50 | 110.0 | 300.0 | 4500 | **510** | 2.39 | **1.66e-07** | **2.373** |
| 030 | 0.50 |  97.0 |  25.0 | 4413 | 230 | 2.58 | 4.89e-06 | 2.091 |
| 031 | 0.50 |  40.0 | 257.0 | 4500 | 506 | **2.67** | 5.13e-06 | 2.157 |
| 032 | 5.00 | 110.0 | 251.9 | 4250 | 284 | 0.844 | **3.49e-07** | 0.809 |

- **helical023 still global best (obj=2.378);** helical031 enters at rank #3
  (2.157). dx=0.5 pattern now 14 of last 19 evaluations.
- **Angle is a first-class knob.** helical023/028/029 are geometrically
  identical except `angle` ∈ {287, 60, 510}. Calo spans **15×**: 2.42e-06
  (023) → 4.17e-06 (028) → 1.66e-07 (029). sob varies only 9% across the
  same trio. helical029 nearly matches helical023's objective (2.373 vs
  2.378) while sitting at the Pareto knee — best calo of any helical run.
- **GP-predicted Pareto knee confirmed.** Post-helical028 GP analysis
  predicted that the upper-corner geom at angle ~400-540 would hit calo
  ~4e-07 with sob ~2.5 (see `/tmp/gp_pareto.py` and
  `gp_predicted_helical_cloud.png`). helical029 observed 1.66e-07 and 2.39 —
  GP got the trend and order right, even underestimated calo improvement.
  Lesson: when geom is otherwise pinned, the GP's angle-only predictions
  are trustworthy enough to drive directed proposals.
- **dx=5 / z0=4250 anti-corner confirmed broken.** helical032 hit
  record-low calo (3.5e-07, ~7× lower than anything else seen) but sob
  crashed to 0.844 — CE acceptance collapses when the plug sits in the
  upper-stream low-z0 position. Validates the GP's entrenched dx=0.5 preference.
- **dy=40 (lower bound) still viable.** helical031 at dy=40 hit sob=2.67
  (highest sob in any batch). Smaller foils don't kill the CE arm if the
  plug is doing the calo rejection work.
- **NEW recovery scripts (2026-05-18):** `/tmp/helical_recover_listrun1b.sh`
  (re-list run1b after rename race + idle-wait for sibling arm_a's
  `state/mustops_ce_outputs.txt` before harvest) and
  `/tmp/helical_recover_evaluate.sh` (relist run1b + reharvest + reevaluate
  after stage-out rename race latent variant 1 silently nulls calo_per_pot
  in summary.json). See [[stage-out-rename-race]].
- **Original chain-script CHAIN_FAIL events are misleading noise** when a
  RESUME_* or RECOVER_* event for the same config preceded them — the
  recovery script will emit its own CHAIN_DONE once it succeeds. Read the
  event log latest-event-wins per config, not first-event-wins.
- **Wall clock:** ~95 min for 4 of 5 chains (matches helical023-027 pace);
  helical029 still resolving the relist+arm-A-mustops wait.

## GP calibration + Pareto cloud structure (2026-05-18)
Post-helical029 surrogate analysis using two standalone GPs (sklearn-side,
mirroring skopt's kernel: `ConstantKernel * Matern(nu=2.5) + WhiteKernel`,
`normalize_y=True`, inputs normalized to `[0,1]^5`; sob linear, calo
log-transformed). Trained on 35 points (10 priors + 25 helical).

**Calibration via leave-one-out (helical only, N=25):**
- sob mean residual −0.017, RMSE 0.265, MAE 0.21
- mean predictive σ 0.23; fraction |z|<1 is **0.48** (ideal 0.68) → GP is
  mildly **over-confident**. Trust the *direction* of GP predictions more
  than the magnitude of σ.

**Dense Pareto sweep** (`gp_predict_helical.py` + `overlay_gp_predictions_helical.py`):
- 8388608 (2^23) Sobol points across the 5D box → predicted (sob, calo) cloud.
- Achievable cloud has a sharp vertical Pareto wall at S/√B ≈ 0.78
  (foil-stack + plug ceiling on CE acceptance with the v111 surround).
- Pareto knee at (sob≈0.72, calo≈1.7e-07); **helical029 sits on the knee**
  (observed 0.768, 1.66e-07 in plot units after x_scale).
- 69-point non-dominated frontier from the dense cloud, extending from
  (~0.78, 5e-06) through the knee to (~0.32, 4e-08).
- helical029 calo (observed 1.66e-07) **beat the GP's prediction of ~4e-07**
  at this corner — GP got direction right, underestimated improvement
  magnitude.

**The BO α=250000 scalarization probes one Pareto-tangent point.** Each
proposal maximizes `sob − α·calo`, which picks the cloud point whose Pareto
tangent has slope α. To map more of the frontier, either:
1. multiplex α across the q-batch (`/tmp/gp_pareto.py` shows the
   λ-sweep — λ=50k → angle near 287, λ=2M → angle near 540), or
2. switch to a proper multi-objective acquisition (qNEHVI / qParEGO, BoTorch).

**GP-prediction validation (helical033-042 batches, 2026-05-18 PM/evening)**
Picked 10 points across the 69-pt GP Pareto frontier (ranks 0/8/17/25/34/42/51/55/65/68)
to test GP calibration at the predicted-best locations. Batch 1 (033-037)
complete; batch 2 (038-042) in flight, 2/5 done as of 19:04.

| cfg | GP sob | obs sob | sob % | GP calo | obs calo | calo % | obs obj |
|---|---|---|---|---|---|---|---|
| 033 | 2.77 | 2.65 |  96% | 4.97e-06 | 5.18e-06 | 104% | 2.132 |
| 034 | 2.57 | 2.52 |  98% | 1.55e-06 | 1.16e-06 |  **75%** | **2.404** |
| 035 | 2.61 | 2.58 |  99% | 2.30e-06 | 2.43e-06 | 106% | 2.072 |
| 036 | 2.30 | 1.27 |  55% | 4.10e-07 | 4.14e-07 | 101% | 1.166 |
| 037 | 1.40 | 1.89 | 135% | 3.13e-07 | 1.16e-07 |  37% | 1.881 |
| 038 | 2.55 | 2.52 |  99% | 4.20e-06 | 5.03e-06 | 120% | 2.066 |
| 040 | 2.50 | 2.39 |  96% | 9.85e-07 | 1.30e-06 | 132% | 2.261 |

- **helical034 is NEW GLOBAL BEST** (obj=2.404, beats helical023 by 1%). GP
  picked the geom (dy=109, halflen=290, z0=4479, angle=333) and underestimated
  its calo performance. Third "upper-corner" winner alongside 023/029.
- helical040 enters at rank #4 (obj=2.261). dx pinned at lower bound 0.5
  on **every** GP-picked frontier point — see widening probe below.
- **sob calibration**: excellent for batch 1 (96–104%) except at high-angle
  corner (036 dropped to 55%; 037 jumped to 135%). Batch 2 holds at 96–99%.
- **calo calibration**: batch 1 conservative (75–106%, obs ≤ pred at the
  knee). Batch 2 mildly **over-confident** at 120–132% — GP underestimates
  observed calo by ~25% in a different region of the frontier.
- Lesson: GP-frontier picks are trustworthy on sob (when angle is in the
  trained range) but calo calibration is region-dependent. Trust direction
  more than magnitude.

## Helical-plug geometry semantics (2026-05-18)
Verified against `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:60–90`:
- `tsda.helical.dx` and `tsda.helical.dy` are **half-widths** of the ribbon
  cross-section (mm). Full extent in beam-transverse plane is `2·dx` by `2·dy`.
  Code: `G4ThreeVector b1(-dx, -dy, 0), b2(dx, -dy, 0), b3(dx, dy, 0), b4(-dx, dy, 0)`.
- `tsda.helical.halflength` is the half-length along z (mm); ribbon spans
  `[z0 - halflength, z0 + halflength]`.
- `tsda.helical.angle` is total twist in degrees from upstream to downstream
  end, applied uniformly over `nsteps=100` extruded slices.
- mmackenz priors used dx ∈ {1, 2} mm (i.e. 2-4 mm full width); GP-favoured
  dx=0.5 mm corresponds to a 1 mm ribbon — already near the manufacturable
  limit for self-supporting Al shim.

## GDML dump recipe (2026-05-18)
Materialize any helical geom to GDML for visualization:
1. Write `gdmldump.fcl` in `<DATA_ROOT>/<cfg>/` containing:
   ```
   #include "Offline/Mu2eG4/fcl/gdmldump.fcl"
   services.GeometryService.inputFile : "autoresearch_<cfg>_geom.txt"
   physics.producers.g4run.debug.GDMLFileName: "mu2e_<cfg>.gdml"
   ```
2. `source setupmu2e-art.sh && pushd /exp/mu2e/app/users/oksuzian/autoresearch_muse && muse setup -q p094 && popd`
3. `export MU2E_SEARCH_PATH=<DATA_ROOT>/<cfg>/geom:$MU2E_SEARCH_PATH`
4. `mu2e -c gdmldump.fcl -n 1` (must be `-n 1`, NOT `-n 0`, or GDML write skips).
- helical034 confirmed: emits 4.4 MB GDML with `AbsorberPV`/`AbsorberS`
  helical-plug volumes inside DS2Vacuum.

## Current top-5 (2026-05-18 evening) — silent-overlap cluster

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| **045** | 0.20 | 109.0 | 289.68 | 4479 | 333 | 2.65 | 1.174e-06 | **2.533** |
| 043 | 0.10 | 109.0 | 289.68 | 4479 | 333 | 2.63 | 1.015e-06 | 2.529 |
| 046 | 0.30 | 109.0 | 289.68 | 4479 | 333 | 2.62 | 1.136e-06 | 2.506 |
| 044 | 0.15 | 109.0 | 289.68 | 4479 | 333 | 2.63 | 1.258e-06 | 2.504 |
| 047 | 0.40 | 109.0 | 289.68 | 4479 | 333 | 2.59 | 1.023e-06 | 2.488 |
| 050 | 0.105 | 109.6 | 194.68 | 4496 | 460 | 2.45 | 6.52e-08 | 2.443 |
| 049 | 0.167 | 107.1 | 187.79 | 4498 | 293 | 2.62 | 1.99e-06 | 2.421 |

Top-5 are dx-clones at `(dy=109, halflen=289.68, z0=4479, angle=333)`. With
`tsda.z0=4195 + halfLength4=12.5 = 4207.5` (disc back face) and plug
upstream face at `z0 - halflen = 4189.32`, **all five overlap the disc by
~18 mm in z**. Gap-cluster reps helical049/050 (z0 placed downstream of
disc) underperform by ~4%, consistent with the overlap acting as free Al.
See [[tsda-disc-helical-sibling-overlap]].

## Option A coupling redesign (approved 2026-05-18)
**Search-space change:** drop `tsda.helical.z0`. New 4D space:
- `dx` ∈ [0.01, 5.0], `dy` ∈ [40, 400], `halflen` ∈ [25, 500], `angle` ∈ [60, 540]

**Derived knobs in `HelicalMode.render_geom`:**
- `tsda.helical.z0 = tsda.z0 + halfLength4 + halflen`
  (plug upstream face touches disc downstream face → no z-overlap by
  construction; downstream face at `tsda.z0 + halfLength4 + 2·halflen`)
- `tsda.rin = ceil(sqrt(dx² + dy²)) + 2 mm`
  (disc hole matches the plug's bounding circle plus 2 mm clearance —
  prevents disc/plug r-overlap when dy is widened past current 110)

**Source-side guard in `constructTSdA.cc:~350`:** throw if
`z0_helical - halflength < tsda.z0 + halfLength4` (defensive; render
should never produce this). See [[tsda-disc-helical-sibling-overlap]].

**Anchor re-evaluations to bridge leaderboards:**
- helical044 re-eval under Option A render (z0 will become
  4195+12.5+289.68 = 4497.18, ~18 mm downstream of current 4479) →
  delta against current obj=2.504 quantifies the silent-overlap bonus.
- helical049 re-eval → already in gap cluster, should be near-invariant.

**Bound widening rationale:**
- dy 40 → 400: BO has been pinned at 109 (upper bound). Disc r4=600 and
  coupled `rin=ceil(sqrt(dx²+dy²))+2` automatically keeps disc/plug clear;
  DS2Vacuum `ds.rIn=950` is the hard ceiling.
- halflen 25 → 500: BO pinned at 289-300 (upper bound). Joint with new
  z0-coupling, downstream face at `4207.5 + 2·500 = 5207.5 mm` still
  upstream of first ST foil at z≈5460.

## Preflight overlap-check integration (landed 2026-05-18)
`cmd_preflight` (helical mode only) now runs a Stage-2 surface check after
G4 init passes:
1. Materializes `<cfg>_surfacecheck.fcl` (`#include`s
   `Offline/Mu2eG4/fcl/surfaceCheck.fcl`, overrides
   `services.GeometryService.inputFile` to a per-config geom overlay that
   adds `g4.doSurfaceCheck=true` on top of the proposal's geom).
2. Runs `mu2e -c surfacecheck.fcl -n 1` in the same preflight workdir;
   ~7 min wall on `/exp` head node.
3. Greps for `Overlap is detected for volume <NAME>` lines, filters child
   names through `SURFACE_OVERLAP_MANAGED = r"^(TSdA|AbsorberPV|AbsorberS)"`,
   fails only on managed-volume hits.

**Stock-geometry baseline (load-bearing):** vanilla Run1Bak Musing
geom_common_current.txt emits **117 overlap lines** out of the box (114
FoilSupportStructure_NN:NN + StoppingTargetMother, 2 rails + DS3Vacuum, 1
VirtualDetector_EMC_0_Front + StoppingTargetMother). The whitelist exists
purely to suppress these — without it the smoke geom looks like 117
failures. See [[mu2e-overlap-check]].

**Helical plug volume name confirmed:** GDML dump of a smoke geom shows the
placement volume as `AbsorberPV:0` (G4Box) — the whitelist anchors on this.
Disc daughters are `TSdA[0-4]:0` (G4Tubs).

**End-to-end smoke verified 2026-05-18:** Option A render on
`helical_optionA_smoke` (x = [0.5, 109, 188, 333] → derived z0=4395.5,
rin=112) preflighted clean: 117 baseline hits, 0 managed hits → PASS.

## Envelope analysis (2026-05-18)
**No code-level envelope assertions** in `constructTSdA.cc:58–128` (`makeHelicalPlug`).
G4 would silently overlap and bias tracking if knobs poked past DS2Vacuum or
collided with the stopping target. Hard physical limits derived from geom:

| Knob | Current BO upper | Physical limit | Headroom | Constraint source |
|---|---|---|---|---|
| `dy` (mm)         | 110  | ~900 | **~8×**   | DS2Vacuum `ds.rIn=950`; TSdA `r4=600` is the only nearby structure |
| `halflength` (mm) | 300  | ~670 | **~2×**   | downstream face must clear first ST foil at z≈5460 |
| `z0` (mm)         | 4500 | ~5160 | ~660 mm | same ST-foil constraint, joint with halflength |

Computation of `vac_zLocDs23Split` (DS2/DS3 split) from
`DetectorSolenoidMaker.cc:254`:
```
vac_zLocDs23Split = ts.rTorus + 2·ts5.halfLength + 2·ds2.halfLength
                  = 2929 + 1250 + 7650         # ds2.halfLength=3825 override
                  = 11829 mm
```
DS2 vacuum spans z ∈ [4179, 11829]. Stopping target z0=5871 mm
(`stoppingTarget_CD3C_34foils.txt:18`); 38 foils × 22.222 mm deltaZ →
first foil at z ≈ 5460.

All three knobs (dy, halflen, z0) have substantial headroom. Recommendation:
widen to `dy ∈ [40, 400]`, `halflength ∈ [25, 500]`, `z0 ∈ [4250, 4800]`.
Caveat: still need preflight `mu2e -n 1` per proposal because constructTSdA
won't catch silent overlaps.

## dx widening probe (helical043-047, 2026-05-18 evening)
Optimizer has pinned dx at the lower bound 0.5 in 14 of last 19 evals plus
**every** GP-Pareto frontier pick. Bounds widened in
`autoresearch_bo_michael.py:374` from `Real(0.5, 5.0)` to `Real(0.1, 5.0)`.
Seeded 5 manual probes all pinned at helical034's other knobs (dy=109,
halflen=289.68, z0=4479, angle=333) with α=100000 and varying dx:

| cfg | dx (mm) | full width 2·dx |
|---|---|---|
| 043 | 0.10 | 0.2 mm — Al shim minimum |
| 044 | 0.15 | 0.3 mm |
| 045 | 0.20 | 0.4 mm |
| 046 | 0.30 | 0.6 mm |
| 047 | 0.40 | 0.8 mm |

- All 5 launched 18:15-18:35 with 300s stagger via
  `/tmp/launch_helical043_047.sh`. All through arm B by 19:05.
- GDML preflight on dx=0.1 builds cleanly (G4 geometry is valid at 0.2 mm).
- **Result**: dx widening paid off — helical047 set new global best at
  obj=2.488 (dx=0.40), then helical044 (dx=0.15) topped it at obj=2.504.
  Followup batch (049/050) at dx≈0.1-0.17 also entered top-4.
- **dx bounds widened again to 0.01** in `autoresearch_bo_michael.py:374`
  and `gp_predict_helical.py` BOUNDS (since helical050 sits at the previous
  lower bound 0.105 ≈ 0.1).
- **GP fix**: `gp_predict_helical.py:make_gp` `length_scale_bounds` floor
  raised from sklearn default 1e-5 to **1e-1** to prevent the dx dimension
  from collapsing to noise-only (was producing a vertical-line cloud in the
  Pareto overlay plot). 67-point Pareto frontier (was 25) after refit.

## Mechanical buildability concern (2026-05-18)
Optimizer keeps pushing dx toward 0 (thinner ribbon = less mass to disturb CE
arm, while still casting calo-stops downstream). The geometric optimum
(dx=0.5 → 1 mm ribbon, 290 mm long, 109 mm tall, 333° twist) is at or beyond
the limit of self-supporting Al shim stock and would require a structural
support frame in practice.
- Mu2e Offline already has `tsda.tubes.*` infrastructure for concentric Al
  absorber tubes (verified in mmackenz workflows: `grep -E "^bool\s+tsda\.tubes\.build\s*=\s*true"`
  across all configs returns zero matches — never activated).
- mmackenz "offset plug" class (v48, v55-v61) places solid Al disks at z
  offsets, not tube housings around ribbons.
- **Novel design candidate for Phase 2**: tube-housing-around-ribbon — use
  thin Al tube as the structural element with a twisted ribbon suspended
  inside. Combines proven `tsda.tubes` machinery with helical plug ribbon.
  Not in mmackenz's prior search vocabulary.

**Two-script overlay pattern** (sklearn + ROOT envs are incompatible):
- `gp_predict_helical.py` runs in `/usr/bin/python3` (has sklearn/scipy,
  no ROOT). Fits GPs, samples Sobol, computes Pareto mask, writes
  `gp_predictions_helical.tsv` + `gp_observed_helical.tsv` +
  `gp_explore_picks.tsv`.
- `overlay_gp_predictions_helical.py` / `..._mpl.py` reads those TSVs
  only — it does **not** touch the leaderboard. To regenerate the cloud
  plot after new leaderboard rows land, **always run
  `gp_predict_helical.py` first** to refresh the staging TSVs; otherwise
  the overlay re-renders the previous frontier.
- ROOT variant runs in the muse SimJob env (`muse setup SimJob` → ROOT
  6.32.06, no sklearn). `_mpl.py` variant runs in `/usr/bin/python3`
  with matplotlib only.
- Lives in `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/`.

## closed-loop-runner round 0 (helicalQR00_00..04, 2026-05-21)
First multi-round batch driven by [[closed-loop-runner]] instead of the
operator-paced loop. q=5 picks from `compute_explore_picks` against the
post-helicalP01-P03 GP fit (after the events-per-job re-harvest).

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| QR00_00 | 0.38 | 108.3 |  34.7 | 4242 | 359 | 3.57 | 1.06e-05 | 2.508 |
| QR00_01 | 0.27 | 119.2 | 454.7 | 4662 | 427 | 3.24 | 8.96e-06 | 2.344 |
| **QR00_02** | 0.13 | 117.2 | 351.2 | 4559 | 361 | **3.70** | 1.06e-05 | **2.642** |
| QR00_03 | 0.36 | 119.4 |  40.7 | 4248 | 318 | 3.72 | 1.28e-05 | 2.438 |
| QR00_04 | 0.91 | 123.2 |  91.3 | 4299 | 297 | 3.11 | 1.01e-05 | 2.101 |

- **helicalQR00_02 → new global best for v2 leaderboard** (obj=2.642 vs
  prior helicalP01_n5000=3.73 sob with similar calo). All five rows
  cluster near (sob 3.1-3.7, calo ~1e-05) — the post-N_crit-gate regime
  has moved the optimization onto a different region of the Pareto
  frontier than the earlier sob<3 v1-era runs.
- All 5 chains were recovered from a krb5-mid-run expiry at concat
  stage; see [[kerberos-mid-run-expiry]] — motivating the new
  `renew_token` node in [[closed-loop-runner]].
- **GP refit after these 5**: 37 observed (22 legacy + 15 v2), Pareto
  frontier grew 470 → 1027 points. sob max in the predicted-cloud
  collapsed from prior batches to ~2.83 — the 5 new rows substantially
  shifted the surrogate.

## GP under-predicts v2 highs — kernel collapses halflen/angle (2026-05-21)
After QR00 landed, the predicted-cloud in `gp_predicted_helical_cloud_mpl.png`
visibly fails to cover the 5 highest-sob v2 magenta stars (observed sob
3.1-3.65). Diagnosis: the fitted production kernel is

`0.79² * Matern(length_scale=[0.332, 0.258, 1e+03, 1e+03], nu=2.5) + WhiteKernel(noise_level=0.561)`

Length scales **1000 (upper bound) on dimensions 2 and 3** (halflength and
angle) mean the GP has declared those two knobs signal-free — it fits only
on (dx, dy) and dumps the remaining variance into noise (std ≈ 0.75). At
the v2 high-sob points the GP predicts sob 2.30-2.80; residuals of +0.5 to
+1.1 are all within ~1.5σ of its noise model, so it sees them as "lucky
scatter around the (dx,dy) mean." Cloud sob_max = 2.83 is exactly the
(dx,dy)-only mean at the most favorable corner.

**Disproved hypothesis**: it is NOT a legacy-pollution effect. Refit on
v2+priors only (25 points) made things worse — kernel collapsed to bounds
on 3 of 4 dimensions and the calo GP degenerated to a constant. 25 pts is
too sparse for 4D.

**Real fix candidates** (in order of cheapness):
1. Cap `length_scale_bounds` upper at ~2.0 in `gp_predict_helical.make_gp()`
   so the optimizer can't declare halflen/angle flat.
2. Cap WhiteKernel `noise_level_bounds` upper to force the GP to fit signal
   instead of absorbing it as noise.
3. More varied (halflen, angle) data — the in-flight SR00 round will widen
   the training set; revisit after it lands.

**Fix landed (2026-05-21)**: `make_gp()` now uses
`WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-5, 1e-1))`. Three-agent
review (empirical + skeptical + reframe) converged: (a) high-sob v2 points
are reproducible (graph011/012/017 internal spread 0.03 ≪ 0.75 WhiteKernel
σ), (b) conditional correlations in the dx<0.6, dy∈[105,125] cluster show
pearson(halflen,sob)=+0.40, pearson(angle,sob)=−0.47 — data DOES carry
halflen/angle signal, (c) physics requires it (helical028/029 vary calo
15× by angle alone). Post-fix kernel:
`1.21² * Matern(length_scale=[0.716, 0.1, 0.1, 0.1]) + WhiteKernel(0.009)`,
cloud sob_max = 3.91 (was 2.83), Pareto frontier 370 pts (was 98), all 15
v2 stars covered. Caveat: halflen/angle length-scales pinned to lower
bound 0.1 — GP is near-interpolating, so out-of-sample σ ≈ 0.12 is
overconfident; the 1e-1 noise cap (vs the 1e-2 cap empirical fix B tested)
is the middle ground. `compute_explore_picks()` (called by
[[closed-loop-runner]]) inherits the fix automatically.

Probe artifacts: `/tmp/gp_probe_v2.py`, `/tmp/gp_diag_nolegacy.py`,
diagnostic plots at
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predicted_helical_cloud_nolegacy.png`
and `gp_predicted_helical_cloud_fixC.png` (legacy diagnostic +
empirical fix-B plot, retained for reference).

## Forward-LOO calibration update (2026-05-25, n=98 v2 rows)
Re-ran the leave-one-out characterization at current data scale (priors +
98 v2 rows, ~4× the 2026-05-18 25-pt snapshot). Methodology: for each v2
row k in chronological order, refit `make_gp()` on priors + rows 1..k−1,
predict at row k's X, residual = pred_mean − observed.

**Headline:**
- sob RMSE: **1.246 (early half) → 0.384 (late half)** — 3.2× improvement;
  late-half residuals fit within the GP's predictive ±2σ band (well-
  calibrated post-FTFP_BERT + Option A).
- log-calo RMSE: 2.263 → 1.171 — only 1.9× improvement, still poor.
- **sob bias = −0.30** (GP systematically under-predicts sob — loop keeps
  finding better than the model expected).
- **log-calo bias = −0.87** (GP under-predicts log-calo by ~0.9 nats =
  observed calo is ~2.4× higher than predicted on average). This is the
  load-bearing empirical evidence for why `pessimistic_calo` exists:
  the **bias is in the GP itself, not in the picker**; pessimistic_calo
  compensates the symptom (fallback-region attractiveness) but does not
  fix the underlying under-prediction. A real fix would be a heavier-
  tailed log-calo prior or a heteroscedastic noise model.
- Early-iteration residuals are inflated mostly by the pre-Option-A and
  pre-FTFP_BERT regimes (rows are partly out-of-distribution for the
  unified GP); excluding those would shrink early RMSE further.

Plot: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_residuals_over_iter.png`.
Script: `/tmp/residuals_over_iter.py` (one-off; uses `.venv-botorch`
because `.venv-graph` lacks matplotlib — both venvs have sklearn).

Operational read: **sob is converged enough that further exploration buys
little**; the loop's remaining headroom is in calo modeling, not sob.
Next high-leverage move is heteroscedastic log-calo (or stop and trust
the 0.46-mm-blade champion).

**Persistence check (2026-05-24, n=74):** kernel still fits at the
envelope corners — sklearn warns `length_scale[1]` (dy) at lower bound
0.1 AND `noise_level` at upper bound 0.1 (the cap). Both have been
binding since the 2026-05-21 fix and have not relaxed across +30
training points (n=44→74). Interpretation: the dy floor is at the edge
of what the kernel can express (real dy structure at ~10% of [40,400] ≈
36 mm), and the noise ceiling reflects the irreducible 100-job MC
noise floor — neither is dangerous, but both are constraints to remember
when reading σ. Touching the noise cap would re-introduce the
collapse-to-flat failure mode; **the dy floor is NOT a safe relaxation
either**: empirical test at n=86 (2026-05-24) lowering dy floor 0.1→0.03
(others kept at 0.1, ls ceiling 1e5, noise floor 1e-10, noise cap kept
at 0.1) collapsed calo p1–p99 spread **1126% → 55%** (20× narrower)
while sob spread only widened 168%→196%. Pareto frontier shrank 50→23.
dy is the dominant dim for calo; making its length-scale local kills
calo variance and would under-explore low-calo regions. Both bounds
stay. Side-by-side at `/tmp/gp_bounded_vs_relaxed_v9.png`.
Cloud-replot output (refit on 74 pts) at
`gp_predicted_helical_cloud_mpl.png`, 2026-05-24 12:08.

**Unbounded re-test (2026-05-24, n=74):** ran `/tmp/gp_probe_unbounded.py`
with `length_scale_bounds=(1e-5, 1e5)` and `noise_level_bounds=(1e-10,
1e+1)` (sklearn-defaults-style). Unbounded fit drove dy length_scale to
**1e-5** (interpolation-only) — the GP became dy-local, every observed
dy treated as an isolated island. Result vs bounded: Pareto frontier
**20 vs 39 pts**, cloud calo range collapsed from **[3e-8, 4e-4] to
[1e-6, 1e-5]** (10× window), sob_p99 dropped **3.16 → 2.10**. The
"more data may relax the bounds" hope from 2026-05-21 is now
DISPROVED at n=74 — unbounded is strictly worse (different failure mode
from n=44, same conclusion). The cap and the dy floor both stay.
Diagnostic only; production `make_gp()` unchanged.
**n=81 re-confirmation (2026-05-24):** rerun via `/tmp/plot_unbounded_vs_bounded.py`.
"Unbounded" has two distinct failure regimes depending on how wide you
actually open the bounds:
- **Sklearn-defaults-wide** `length_scale_bounds=(1e-5, 1e5)`,
  `noise_level_bounds=(1e-10, 1e+1)`: cloud is tight but non-degenerate.
  99.99% of 1,048,576 Sobol samples lie within p1–p99 spread of
  **sob 7.4%, calo 8.4%** around `(sob≈2.13, calo≈3.78e-6)`; only
  **58 of 1M** lie outside the joint p1–p99 box.
- **Truly unbounded** `(1e-30, 1e30)` on Matern length-scale, WhiteKernel
  noise, AND ConstantKernel value (n=83): cloud collapses to a SINGLE
  point — `sob∈[2.16, 2.16]`, `calo∈[3.85e-6, 3.85e-6]`, Pareto frontier
  = 1 element. The 1M predictions are bit-identical. The GP becomes a
  constant predictor.
Bounded fit at same n: tail ~19,849 points, p1–p99 spread sob 39%, calo
~1130%. Side-by-side at `/tmp/gp_bounded_vs_unbounded_v8.png`
(truly-unbounded) and `_v7.png` (sklearn-defaults-wide). The takeaway:
sklearn's default wide bounds give a deceptively-narrow cloud that hides
how degenerate the unbounded optimization actually is; pushing the
bounds wider until the optimizer is truly free reveals total collapse
to a constant.

**Bounded GP is highly sensitive to small data additions (2026-05-24, n=86→87):**
While diagnosing why `/tmp/gp_bounded_vs_relaxed_v11.png` (left/bounded panel)
looked very different from canonical
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predicted_helical_cloud_mpl.png`,
discovered the bounded production GP collapses dramatically with single-row
data additions:
- At n=86 (this morning, ~12:07): calo cloud spanned **~4 decades**
  `[3e-8, 4e-4]`, p1–p99 ≈ **1126%** relative spread. This is what the
  canonical PNG/TSV captures (`gp_predictions_helical.tsv`, 8,388,609
  Sobol rows, mtime 12:07).
- At n=87 (this afternoon, ~16:00, after one new FT06 row): calo cloud
  spanned **~2 decades** `[4.2e-7, 4.5e-5]`, p1–p99 ≈ **121%** — **~10×
  collapse from one new point**. Verified by running canonical
  `gp_predict_helical._fit_and_sample(sobol_m=23)` fresh against current
  leaderboard — identical to my `_v11.png` left panel.
- **The ridge is NOT exploration-starvation; the picker is.** (2026-05-24,
  n=87, three-agent investigation.) Concern raised: if the GP is
  over-confident (small `logc_std`) in ridge regions, the BO won't
  explore there. Empirical diagnostic
  (`/tmp/gp_overconfidence_diagnostic.py`) DISPROVED over-confidence:
  - Near-training samples (distance < 0.143 in normalized 4D):
    median `logc_std` = **1.62** (p5=1.04, p95=1.75)
  - Ridge samples (|log(calo_pred) − log(3.82e-6)| < 0.1):
    median `logc_std` = **1.85** (p5=1.84, p95=1.85) — *15% LARGER*
  - `sob_std` similarly grows from 0.33 near training to ~1.18 far
    (asymptote plateau, honest GP behavior).
  The GP IS honestly uncertain in ridge regions. The actual starvation
  cause is that `compute_explore_picks` (`gp_predict_helical.py:218`)
  does **Pareto-of-mean** — never reads `logc_std`/`sob_std`. The
  honest uncertainty sits in the returned tuple, unused. Fix: switch
  picker to UCB/LCB of (sob, log_calo):
  `lcb_calo = mu_c − κ·sd_c; ucb_sob = mu_s + κ·sd_s; Pareto of
  (−ucb_sob, lcb_calo)`. One-file change, leaderboard-preserving.
  Skopt default κ=2.0 (bump to 3–5 if clustering persists). Pessimistic
  constant prior mean is a band-aid adjunct only; input warping is the
  long-term right answer if specific dims are over-bunched. BoTorch
  qNEHVI (`botorch_predict_helical.py`) would also fix it principled-ly
  but requires venv refactor + signature-match for `compute_explore_picks`.
- **κ-tuning of UCB/LCB has a structural ceiling against the ridge.**
  At logc_std≈1.85 in fallback regions, even κ=1 leaves the ridge
  `calo_lcb = exp(log(3.82e-6) − κ·1.85) ≈ 6e-7` — STILL below the
  calo_cap=2e-6 gate. So κ alone cannot push picks off the ridge; the
  fallback's σ is larger than any reasonable κ can scale. Concretely:
  to push ridge calo_lcb above 2e-6 needs `κ > log(2e-6/3.82e-6)/1.85
  = log(0.524)/1.85 = −0.35` — κ would have to be *negative* (LCB
  becomes UCB on calo) to defeat the ridge, which defeats the whole
  uncertainty-aware reasoning. Implication: if κ-sweep doesn't reach
  acceptable ridge-fraction by κ=0.5, **the right next step is the
  pessimistic constant prior or qNEHVI — not lower κ**.
- **BoTorch qNEHVI migration recipe** (Agent A, 4-agent team review
  2026-05-24, in case the sklearn band-aids fail): preserve
  `compute_explore_picks(q, nsteps_budget, min_spacing)` signature by
  shelling out — `subprocess.run(.venv-botorch/bin/python
  botorch_predict_helical.py --emit-picks-json …)` and parse the JSON
  back. Avoids merging torch into `.venv-graph` (~600 MB, sklearn/numpy
  ABI risk on the /data-mounted venv per
  [[venv-relocated-to-data-volume]]). Three load-bearing guardrails
  the current `botorch_predict_helical.py` doesn't have: (a)
  per-round ref-point = `nadir(feasible front) × 1.1` not hardcoded
  `REF_SOB=-0.5, REF_NEG_LOGCALO=-8.0` (loose ref → q clusters on
  fallback; tight ref → q clusters on narrow slice); (b) MC seed =
  `42 ^ round_idx` not fixed-42 (fixed seed reuses the same Sobol
  draw every round → subtle diversity bias); (c) `num_restarts=16`
  not 8 for q=8 in 4D. Also: botorch path uses `-log10(calo)` while
  sklearn uses `log(calo)` — predicted-calo TSVs from the two paths
  are NOT directly comparable. Backup if qNEHVI's ref-point
  sensitivity bites: **qParEGO** (Knowles 2006 / Daulton 2020) —
  random Tchebycheff weights per pick give automatic batch diversity
  *without* needing a ref point; for our asymmetric front (sob more
  important than marginally lower calo), reweight `Dirichlet(2,1)`
  toward sob.
- **Picker A/B measurement protocol** (Agent D, 4-agent team review
  2026-05-24): cannot replay history; per-round HV noise is 10–20%
  from grid stochasticity. **Primary metric** = constrained
  reference-set HV gain ΔHV_ref over feasible rows (`calo<2e-6`),
  with ref pinned at PRE-ROUND nadir (not post-round — drift hides
  exploration cost). **Secondary diagnostic** = min-pairwise-distance
  MPD in unit-normalized 4D box from picks alone (no grid spend):
  production picker A's collapsed cluster has MPD≈0.05; healthy
  explorer ≥0.20. **Decision rule:** ship if ΔHV_ref ≥ 1.25×
  recent-4-round baseline AND MPD ≥ 0.15 AND feasible-frac ≥ 5/8;
  revert if <0.75× OR feasible-frac <3/8; else need a 2nd round.
  **Pre-flight (zero compute):** refit GP once on current n; run
  candidate pickers against the FROZEN posterior; compare MPD,
  bbox-coverage, ridge-fraction (picks with logc_std>1.5). Sub-25%
  effects need ≥4 rounds to clear noise — we're explicitly accepting
  low statistical power for shipping speed.
  **Smoke A/B (2026-05-24, n=87, q=8, calo_cap=2e-6, min_spacing=0.02,
  `/tmp/picker_smoke_ab.py`)**: A picks all cluster in dx∈[1.90,2.41],
  dy∈[81,110], spread `[0.51, 29, 348, 186]` for `[dx, dy, hl, ang]`;
  all 8 with calo_mu < geomean and logc_std<0.9. B (κ=2) picks dx∈
  [0.23,4.73], dy∈[107,365], spread `[4.5, 259, 351, 375]` — ~9× wider
  on dx/dy. **7/8 of B's picks land on the fallback ridge** (calo_mu≈
  3.82e-6, logc_std≈1.85) and 3/8 have sob_std>1.2 → blind shots.
  Implication: **κ=2 may be too aggressive for a single round** (would
  mostly teach the GP, not improve the leaderboard); consider κ ∈
  {0.5, 1} sweep or hedge with split-q (4 mean-Pareto + 4 UCB/LCB)
  before landing the swap. Plot: `/tmp/picker_smoke_ab.png`.
- **Fallback ridge will NOT disappear with more leaderboard rows.** At
  n=87 ~87% of the 1M Sobol cloud sits in the GP fallback regime (per
  the 3-agent ridge diagnostic above). 4D + stationary Matern means
  halving that volume needs ~16× more data (curse of dimensionality);
  even doubling n→170 leaves the ridge clearly visible in the canonical
  PNG. **Higher stats is not a fix.** The cure is structural — a
  pessimistic constant prior mean (shift fallback to `log(max(y_calo))`
  ≈ −10.6 instead of geomean −12.78 → ridge moves to ~2.4e-5, above the
  calo_cap=2e-6 gate, picker stops finding it attractive), BoTorch
  qNEHVI with first-class `mean_module`, or input warping. sklearn's
  `GaussianProcessRegressor(normalize_y=True)` makes option 1 awkward
  (must disable normalize_y and shift y manually pre/post fit).
- **Horizontal density ridge in canonical PNG ≈ GP fallback to training
  geometric mean of calo** (not physics): `gp_predict_helical.py:135`
  fits the calo GP on `np.log(y_calo)`, with `normalize_y=True`. In
  regions of Sobol space far from any observation the posterior collapses
  to the prior mean in log-space; `np.exp()` of that is the geometric
  mean. At n=87 that's `exp(mean(log(calo))) =` **3.82e-6**
  (log10 ≈ −5.42) — shows as a horizontal band of high pcolormesh
  density just below 4e-6 in canonical PNG. NOT the arithmetic mean
  5.3e-6 (a common mis-identification — easy to make if you forget the
  `np.log(y_calo)` transform on line 135). The line walks as new rows
  land; same mechanism that drives the calo cloud span sensitivity
  (preceding block). Sob GP is fit directly (no log), so its fallback
  ridge sits at arithmetic `mean(training sob) ≈ 2.0`. Only the Pareto
  frontier (white line) is the physically-meaningful part of the cloud.
- **Canonical PNG rendering quirks (not data, but easy to misread):**
  `overlay_gp_predictions_helical_mpl.py` uses pcolormesh 2D density with
  **fixed `range=[[0,1.15], [-8,-4]]`** — y-axis always spans 4 decades of
  calo regardless of actual GP fit (empty bins just don't render). Direct
  scatter of the same TSV with autoscaled y will collapse to 2 decades on
  a tighter fit; this is a rendering difference, not a fit difference.
  x-axis is also normalized: `sob / x_scale` where `x_scale = nominal Run
  1A sob ≈ 3.3` (read from `table.org`), so canonical x range is [0, 1.15],
  not raw sob. The PNG also overlays mmackenz `table.org` configs (8
  marker/color classes) on top of the GP cloud. Side-by-side comparisons
  must reproduce all three (pcolormesh + x_scale normalization + fixed
  log y-range), not just scatter the prediction tuples.
- **Operational consequence:** `gp_predicted_helical_cloud_mpl.png` and
  `gp_predictions_helical.tsv` are **stale after every closed-loop round**.
  Regenerating both takes ~minutes (sobol_m=23 → 8.4M predictions); do
  it as part of post-round housekeeping before reading the visualization
  to make decisions. Reading the stale PNG and reasoning about Pareto
  shape will mislead.
- **`pessimistic_calo` gate landed (2026-05-24)** — `_fit_and_sample` +
  `compute_explore_picks` in `gp_predict_helical.py` accept
  `pessimistic_calo: bool = False`; default-off so non-flagged callers
  are bit-identical. Implementation: build a fresh
  `GaussianProcessRegressor(kernel=<same as make_gp()>, normalize_y=False)`,
  fit on `np.log(y_calo[pos]) - log_shift` where
  `log_shift = float(np.log(np.max(y_calo[pos])))`, then add `log_shift`
  back to `logc_pred` post-predict (`logc_std` unchanged). `normalize_y`
  must be False or sklearn double-centers; this is the load-bearing
  detail. At n=87, `log_shift = -11.128` (slightly higher than the
  prior estimate of −10.6 — actual `max(y_calo)` in v2 is 1.47e-05).
  CLI exposed via `graph/closed_loop.py --pessimistic-calo`
  (stored in RoundState as `pessimistic_calo`, plumbed to both
  `node_predict_picks` and `node_refit_and_check`). Pre-flight A/B
  (`/tmp/preflight_pessimistic_picker.py`): MPD 0.032 → 0.143 (4.5×),
  dx span [1.9, 2.4] → [0.094, 4.834] (full range), feasible 8/8, ridge
  0/8, bbox-coverage 3×. Reuse note: `closed_loop.py --dry-run
  --pessimistic-calo` (line 475) was already capable of printing the q
  picks; running it twice (with/without the flag) gives the same picks
  side-by-side — the throwaway preflight script only adds auto-MPD /
  feasible / ridge metrics and a pass/fail gate. First grid validation
  is `helicalPC01R00_00..07` launched 2026-05-24 (thread_id helicalPC01,
  q=8, max_rounds=1, ~8 h harvest); assessment plan in
  `/nashome/o/oksuzian/.claude/plans/zazzy-booping-ladybug.md`.
- **PC01 first-round outcome (2026-05-24, harvested in ~40 min — much
  faster than the plan's ~8 h estimate, possibly because all 8 children
  ran on currently-empty queue):** realized MPD=0.121 (baseline median
  ~0.075), realized dx span [0.094, 4.835] (full 5-unit box; baseline
  ~2.0), best obj=2.589 (highest of any round; FT03=2.561, FT06=2.506),
  but only 1/8 feasible (calo<2e-6) tied with baseline median, AND the
  one feasible point lands at sob=0.718 vs baseline sob~1.29. Soft
  signals confirm the prior IS diversifying as intended, but
  pred-vs-realized calo calibration is the next gap to diagnose. The
  plan's strict ΔHV_ref gate is unusable here — see next bullet.
- **ΔHV_ref metric is degenerate at the 2e-6 calo cap**
  (`/tmp/assess_pc01.py`, 2026-05-24): per-round constrained HV gain is
  **identically 0.0** for every round (FT03..FT06 AND PC01), regardless
  of whether the reference is the PRE-round nadir or the GLOBAL
  worst-feasible nadir. The cap is so tight (only 19 historical feasible
  points across hundreds of grid evals) that the historical Pareto front
  already dominates every new point on the feasible side; new picks fall
  below the front in (sob, −calo) and don't widen the HV box. **Plans
  proposing "use per-round ΔHV_ref as the keep/revert gate" cannot
  discriminate here.** Use soft signals (MPD, dx span, best obj,
  feasibility) instead, OR loosen the calo cap to a less brutal
  threshold (e.g. 5e-6) where the per-round feasible Pareto front can
  actually shift. Do NOT rerun ΔHV_ref expecting non-zero values
  without first relaxing the cap.
- The collapse is the bounded fit doing its job (one new point disambiguates
  a previously-flat ridge in the posterior), not pathology. But it does
  mean the GP's exploration signal has just halved its calo dynamic range,
  which directly shrinks the Pareto picks' calo spread in the next round
  — relevant for closed-loop `min_spacing` clustering behavior.

## N_crit margin too loose at 5000 — empirical (SR00_00, 2026-05-21)
The N_crit ≤ `HELICAL_NSTEPS=5000` guard ([[tessellated-solid-facet-orientation]])
was set on the prior assumption that the patched facet-orientation
fix would keep geometry valid up to that buildable ceiling. **SR00_00
empirically refutes that.** Geometry `dx=0.011, dy=125, halflen=251,
angle=167` → N_crit ≈ 4144 (well below 5000) reproduced the same
GeomSolids1001 + stuck-track flood the guard was supposed to prevent:

| stage | n_jobs flagged | n_jobs total | G4Exceptions | stuck tracks |
|---|---|---|---|---|
| mubeam        | 186 | 200 | 1.74 M | 0.58 M |
| run1b_mubeam  | 195 | 200 | 45 k   | 15 k   |
| mustops_ce    |  90 | 100 | 6.66 M | 2.22 M |

scan_logs gating ([[closed-loop-bo-design]] revision #5, landed in graph
node) **worked as designed**: `state/broken.txt` written, leaderboard
append suppressed. `summary.json` reported sob=3.88, calo=1.42e-5 — both
inflated by the stuck-track count saturation; NOT in the v2 leaderboard.

The 3-4 h per-job CPU wall on these geometries is **not slow-but-correct
geometry**; it is the same G4 stuck-track inflation. There is no
"throughput gate" distinct from the brokenness gate — at the bad-corner
of the search space, the per-job cost IS the brokenness. (Earlier draft
of this section, since revised, framed the 3-4 h walls as a separate
throughput concern with a tabular dx-vs-wall comparison — that framing
turned out to be a misread of the same N_crit-margin failure.)

VmPeak ≈ 2.75 GB on these jobs is a real but **secondary** finding:
when the guard tightens enough to exclude broken-corner picks, the
VmPeak distribution is expected to drop with it. Memory bump to 3.0 GB
landed defensively but should not be needed once N_crit picks are sane.

**Action items applied 2026-05-21:**
- `HelicalMode.HELICAL_NSTEPS` lowered 5000 → 2000 in
  `autoresearch_bo_michael.py`. This is the predicate the propose-loop's
  `is_buildable` consults; tightens the bare-propose path identically to
  the picks path.
- `closed_loop` should be invoked with `--nsteps-budget 2000` (matches
  `compute_explore_picks` Sobol filter). The two constants are now
  co-equal — drift would re-open the same hole this incident exposed.
- Still TBD: revisit whether 2000 is empirically sufficient. SR00_00 is
  one data point; the boundary between "buildable & correct" and
  "buildable but stuck-track-flooded" needs a deliberate sweep, not just
  guesswork. If SR01 produces another broken row at N_crit ≤ 2000,
  tighten further (1000?) and consider a runtime stuck-track ratio gate
  in scan_logs that fires earlier (during poll, not after harvest)
  so the closed loop doesn't burn 4 h of CPU on geometry that was
  doomed at submit time. See [[closed-loop-bo-design]]
"Throughput gate" note.

**Update 2026-05-27:** the FCL nsteps and the BO N_crit budget are now
**intentionally decoupled**, reversing the prior "must move together"
rule above:
- `autoresearch_bo_michael.py` `HELICAL_NSTEPS = 10000` — FCL geometry
  mesh resolution (`tsda.helical.nsteps`). Higher = finer-faceted built
  helical solid, more memory/CPU per G4 init, but no BO-search effect.
- `gp_predict_helical.py` `DEFAULT_NSTEPS_BUDGET = 2000` — sklearn N_crit
  Sobol gate. The BO refuses to *propose* configs needing >2000
  winding-self-intersection steps; configs that *do* get proposed are
  built at nsteps=10000 (well above what their geometry actually needs).
- `botorch_predict_helical.py` `NSTEPS_BUDGET = 2000` — same role for
  qNEHVI's Sobol pool + intra-point feasibility constraint.
- Rationale: 10000 facets is cheap for resolution but high N_crit
  regions (extreme aspect ratios) still produce ambiguous geometry under
  twisted-box; keep the search-space gate at the empirically-validated
  2000 threshold even as we render at finer resolution.

First post-decoupling q=3 picks (sklearn Pareto-spaced):
dx=0.012 sob=4.08 calo=1.3e-5 / dx=2.16 sob=1.47 calo=1.4e-6 / dx=4.80
sob=0.45 calo=2.7e-7. BoTorch qNEHVI piled all 3 picks at small-dx
high-sob corner (qNEHVI is hypervolume-greedy), 1/3 failed the
N_crit≤2000 gate — qNEHVI sees the gate as a *soft* intra-point
constraint, not a hard reject. Pre-submission inspection is mandatory.

## Pareto saturation in 4D (2026-05-28)
Hypervolume-vs-evals diagnostic on the 176-row v2 leaderboard shows the
4D BO has effectively saturated — running more 4D evaluations buys
near-zero front improvement:

| Metric | First 50 evals | Eval 100 | Final (176) |
|---|---|---|---|
| Dominated HV (sob × calo, ref=worst+2%) | 4.84e-5 | 4.99e-5 | 5.07e-5 |
| Pareto-hit rate (W=20 rolling) | 62% | — | 38% |

HV gain decomposition: +3.0% (50→100, 50 evals) then **+1.6% (100→176, 76 evals)** —
5× drop in HV-per-eval. Pareto-hit rate (fraction of new evals that expand
the front) decayed from 62% early → 38% late.

Plot: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/pareto_saturation.png`
(generator `/tmp/pareto_saturation.py`).

**Implication for next-step planning:**
- Continuing pure 4D closed-loops (e.g. another FT0x round) will keep
  shaving ~0.02% HV/round — not worth the grid hours.
- The actually-load-bearing follow-ups are the dimensionality lifts that
  have been queued but not run: **promote COL5 material** (#146) and
  **TSdA4 disc thickness** (#147) to BO knobs, and the **targeted
  small-dy / long-hl / mid-angle corner** explore batch (#148) the GP
  cloud rendering already flagged as under-sampled.
- Saturation diagnostic should be re-run after every dimensionality lift
  to recheck whether the new dim opened HV worth chasing.

## Post-cleanup champion shift (2026-05-27)
After the [[scan-broken-codes-too-narrow]] full-census purge moved 38 v2
rows + 3 legacy rows to `.broken.tsv` sidecars (see [[leaderboards]]),
GP refit on the cleaned leaderboard:
- Training set: 196 → **175 v2 rows** (10 priors + 165 helical, 0 legacy
  after legacy file dropped from gp_predict_helical loader gate)
- Still-filtered: **7 silent-pass configs** (graph001-005, graphsmoke001/002)
  — no `state/` dir on disk, retro-scan SKIPped them, gate treats as
  broken-unknown.
- Pareto frontier: 469 → **772 points**.
- GP top pick: `dx=0.012, dy=132, halflen=362, angle=424` →
  `sob=4.075, calo=1.33e-5`. **dx sits at BO lower bound 0.01** (sub-mil
  ribbon) — extreme-corner pick, likely unphysical / unmanufacturable;
  treat as exploration-only.

**New observed champions (post-sidecar):**
| metric | config | dx | dy | hl | ang | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| top obj | **helicalQR00_02** | 0.13 | 117.2 | 351.2 | 361 | 3.70 | 1.06e-5 | **2.642** |
| top sob | helicalFT08R00_00 | 0.013 | 147 | 44 | 706 | 3.83 | 1.77e-5 | 2.064 |
| top low-calo (sub-2e-6) | helicalNG04 | 0.8 | 70 | 250 | 560 | 1.67 | 1.94e-6 | 1.476 |

**Champion regime shifted significantly.** Prior top-3 obj champions
(helicalL02 obj=3.084, graph023 obj=2.972, helical041a obj=2.833) are
all now in `leaderboard_bo_helical_v2.broken.tsv` — their metrics were
artifacts of broken tessellated geometry (see [[tessellated-solid-facet-orientation]]
A/B grid test for helical041a). The new top-obj champion
(helicalQR00_02 at 2.642) is **a 14% drop from the prior tainted
champion** but is geometrically validated (no LikelyGeomOverlap in
its scan_logs report).

QR00_02 also sat at #4 in the pre-cleanup top-5 (see "Cross-model
saturation confirmation" block); the cleanup demotes the three above it
and promotes #4 to #1. Validates the "4D BO is saturating" reading: the
true ceiling is closer to obj≈2.6-2.7, not the 3.0+ region the tainted
rows had been suggesting.

## Chain-script evaluate bug (recurrent, 2026-05-18)
`/tmp/helical_full.sh:59-60` has a line-continuation in the `run evaluate`
call that mangles argument splitting → `evaluate` exits rc=2 with
CHAIN_FAIL. **summary.json has already been written by harvest by the time
evaluate runs**, so manual recovery is one-line:
`./autoresearch_bo_michael.py --mode helical evaluate <cfg> <DATA>/<cfg>/harvest/summary.json`
Hit by helical043, helical045, helical046 in succession (all three dx-probe
configs that completed). Fix the chain-script line continuation when
touching it next.

## Loader N_crit-gate silently drops most v2 rows from GP training (2026-05-23)
`gp_predict_helical.py:_load_lb` (lines 81-102) per-row checks
`_ncrit(dx, dy, angle) > KNOWN_NSTEPS.get(config, DEFAULT_NSTEPS=100)`.
`KNOWN_NSTEPS` only lists `helical050a_n5000=5000` — every other config
falls back to **`DEFAULT_NSTEPS=100`** (historical pre-2026-05-21
default), even though the *current production* `HelicalMode.HELICAL_NSTEPS=2000`
(`autoresearch_bo_michael.py:367`). On the 2026-05-23 refit, this
dropped **36/71 v2 rows** (51%) — including `graph027` (N_crit≈690 from
the helicalQR00_02 baseline) and most high-angle SR/QR/F01 configs.
The 35 retained are not biased per se (the dropped rows would have
fired GeomSolids1001 at nsteps=100 IF run at that nsteps; they were
actually run at nsteps=2000 and produced valid data) — but the
training set is half the leaderboard, **silently**, and the function
prints nothing when N_crit-dropping a row (only `_is_broken` drops
print). Fix when touching that block: replace `DEFAULT_NSTEPS=100` with
`HelicalMode.HELICAL_NSTEPS` (or stamp per-row nsteps into the
leaderboard at evaluate-time and read it back here).
Cross-check before declaring a GP refit incorporates new rows:
`grep -E "^helicalF01|^graph027" leaderboard_bo_helical_v2.tsv` then
compare "trained on N points" against expected count.

## GP under-predicts at low-calo extrapolation tail — F01 evidence (2026-05-23)
The closed-loop F01 batch (q=8, picks predicted at calo<2e-6) landed
its 8 observations in calo∈[3.7e-6, 9.6e-6] — **5× to 56× higher than
predicted**, with the ratio growing monotonically with distance from
the training support:

| pick | pred sob/calo | obs sob/calo | calo ratio | sob ratio |
|---|---|---|---|---|
| F01_00 | 2.59 / 1.92e-6 | 3.31 / 9.64e-6 | 5.0× | 1.28× |
| F01_03 | 1.77 / 3.40e-7 | 3.05 / 8.12e-6 | 24× | 1.72× |
| F01_07 | 0.15 / 6.59e-8 | 2.16 / 3.68e-6 | **56×** | **14×** |

Both metrics under-predict; the worse the prediction, the larger the
gap. Mechanism: log-calo GP has very few training points with calo<2e-6
(the leaderboard is dominated by calo∈[1e-5, 5e-5] from earlier
batches), so picks deep into the predicted low-calo tail are pure
extrapolation — the log-calo GP regresses toward bulk mean as posterior
variance grows. The sob GP shows the same pattern in reverse: low-sob
picks land at much higher sob than predicted, because none of the
training rows have sob<1.5.

**Implication for closed-loop strategy**: GP-driven picks into
unexplored regions of (sob, calo)-space are NOT trustworthy as
*objective predictions*; they are exploration moves whose value is
seeding the GP with observations in new regions, not landing on the
predicted Pareto front. The F01 batch successfully expanded the
training support into the low-sob tail (sob∈[2.16, 3.31] is the lowest
8-pack so far) — but the actual Pareto frontier from F01 sits *above*
the GP's prior Pareto cloud, not below it.

Open question: does tightening `make_gp()` length_scale upper bound
(currently ~2.0 per fix landed 2026-05-21) help, or hurt? It would
shorten extrapolation reach but also reduce the GP's ability to
share information across the 4D space's coarse structure.

## Open questions / TODO
- helical001 (`dx=2.32, dy=84, halflen=263, z0=4500, angle=452`) PASSED
  preflight with the v111-style baseline. Submit to grid; target obj > 1.958.
- The v111-baseline render emits the same TT_MidInner patches as v111. If
  task #21 someday switches the project to a stage-aware baseline (one geom
  per stage), revisit whether this manual patch can be dropped.
- michael-mode load_priors does NOT exclude helical configs — v111 enters the
  michael GP as if its low calo (1.62e-6) came from foil stack alone, when
  actually the helical plug is doing most of the rejection. This contaminates
  the michael GP signal at low-calo region. Consider filtering helical priors
  out of michael mode (separate concern from this project).
