---
type: project
title: BO Foils Grouped (foilsg)
description: 12D BO over a 49-foil stack in 4 z-groups (12-13-12-12), each group
  shares (rOut, hT, f); REPLACES deployed 37-foil base; wired 2026-06-09 after [bo-foils](/projects/bo-foils.md)
  saturated at sob≈3.89-3.90
status: active
timestamp: '2026-07-17'
---

# BO Foils Grouped (foilsg)

## Summary
12-D BO over a 49-foil stack partitioned into 4 contiguous z-groups (sizes
12-13-12-12, center-loaded). Each group shares one `(rOut, halfThickness,
hole_fraction)` triple. REPLACES the deployed DOE-2017 37-foil base (no
pinned baseline) — motivated by [bo-foils](/projects/bo-foils.md) saturation at sob≈3.89-3.90
where every champion railed upstream-`hT` to the 0.05 mm floor, suggesting
the base 0.0528 mm halfThickness is the bottleneck. Mode wired end-to-end
2026-06-09; no rows yet.

## Key facts

- **Z-layout = uniform spacing across deployed extent.** Deployed: 37 foils
  × `deltaZ=22.222222` ⇒ 36 gaps × 22.222 ≈ **800 mm** extent. New: 49 foils
  ⇒ 48 gaps of `800/48 = 16.6667 mm`. Stack center pinned by keeping
  `stoppingTarget.z0InMu2e = 5871`. `_geom_text` emits the `deltaZ` override.

- **12-D Real search space** (`FoilsGroupMode.build_space`,
  `bo_driver.py`): for g ∈ {0,1,2,3}:
  - `rOut_g{g}`  ∈ [50, 250] mm
  - `hT_g{g}`    ∈ [0.01, 1.0] mm
  - `f_g{g}`     ∈ [0, 0.95] (hole fraction; rIn = f·rOut)
  `is_buildable` is trivially True (f<1 ⇒ rIn<rOut).

- **`load_priors()` returns []** — fresh search space, no carryover from
  foilsf. First round must be Sobol-seeded; `N_INITIAL_POINTS = 10`.

- **Picker bootstrap dependency**: `--picker qlnei` requires ≥1 leaderboard
  row to fit the GP (`botorch_predict._load_history_tensor` raises SystemExit
  on empty history). Round 0 must be `--picker cl_min` (skopt shim with
  N_INITIAL_POINTS Sobol-init); rounds 1+ switch to qlnei.

- **Touch-points** (mirrors the foilsf pattern):
  - `bo_driver.py` — `FoilsGroupMode` class + `MODES["foilsg"]` registration
  - `botorch_predict.py` MODE_SPECS — 12-D bounds (stale-bounds hazard: must lockstep with `build_space`)
  - `graph/config.py` MUSING_BY_MODE / GRID_STAGES_BY_MODE / HARVEST_VERB_BY_MODE — Run1Bak, 4-stage chain, `harvest` verb (identical to foilsf)
  - `graph/closed_loop.py` `_import_gp` + `_DRY_RUN_KNOB_LABELS` + argparse choices
  - `graph/state.py` Literal widening
  - new `mmackenz_table_plots/gp_predict_foilsg.py` shim (clone of foilsf's)

- **Patched-lib hard dependency.** `_geom_text` always emits BOTH
  `stoppingTarget.holeRadius` (scalar = mean) AND `stoppingTarget.holeRadii`
  vector (per-foil). Stale grid binaries that pre-date the patched
  `StoppingTargetMaker.cc` will silently fall back to the scalar and build a
  uniform-hole 49-foil stack (wrong) — same hazard as [bo-foils](/projects/bo-foils.md) but worse
  because there's no pinned base to fall back to. Verify the grid tarball is
  current before launching.

## Cross-links
- Related: [bo-foils](/projects/bo-foils.md) (predecessor: extras-only on pinned 37 base, saturated 3.89-3.90), [bo-foil](/projects/bo-foil.md) (original 7D), [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md), [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)
- Source files: `bo_driver.py` `FoilsGroupMode`,
  `graph/config.py:35-77` (per-mode dispatch dicts),
  `botorch_predict.py` MODE_SPECS "foilsg",
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_foilsg.py`
- External: [muse-backing-pattern](/external/muse-backing-pattern.md) (patched libmu2e + LD_PRELOAD path)

- **foilsg02 closed 2026-06-10 (qlnei, q=10, max-rounds=5).** Final
  leaderboard 44 rows (foilsg01:4 sobol + foilsg02:40). Per-round top sob:
  R0 **1.23** → R1 **1.49** → R2 **1.66** → R3 **2.10** → R4 **2.69**.
  Trajectory monotone and steepening at exit (R3→R4 was +28%, the
  biggest jump). **No saturation at the 2026-06 exit** — the final-round
  picker was still exploiting when max_rounds=5 cut it off mid-climb; the
  line has been dormant since (candidate venue for the botorch-0.18 high-d
  test, [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md)). **Gap to foilsf plateau
  3.89 is ~31% (sob)** — open question whether free-base can clear it or
  whether the 12-D space just needs more evals to catch up to foilsf's 297.
  Operator decision pending on foilsg03 (more rounds, possibly larger q).
- Wall-clock per round (qlnei q=10, ~40 evals total in 12-D): R03 → R04
  took ~3h (full mubeam+downstream+harvest chain × 10 children + ~6 min
  acqf solve). Total foilsg02 wall-clock R0..R4 = ~15h elapsed parent time.
- **foilsg03/04/05 attrition window (2026-06-10..11):** three launches in
  48h, all cut short by infrastructure, only +11 rows total (leaderboard
  44 → 55). foilsg03: +8 rows, killed at R0 by
  [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md) (240-min cap).
  foilsg04: +0 rows, all 10/10 children died at mubeam submit —
  /nashome RCDS disk quota ([jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md)).
  foilsg05: +3 rows (R00_05/06/08, sob 2.75/2.91/2.90), 7/10 lost to
  [stage-out-rename-race](/incidents/stage-out-rename-race.md) under 1186-idle queue starvation, 3 survivors
  orphaned by the barrier false-positive at the raised 360-min cap.
  Current foilsg best: **sob 3.13 (foilsg03R00_04)** vs foilsf plateau 3.89.
- **foilsg06 launched 2026-06-12** (qlnei, q=10, max-rounds=2, parent pid
  1137647) — first campaign under the fixed liveness-wait barrier
  (no orphans possible short of the 24h backstop; see
  [closed-loop-runner](/drivers/closed-loop-runner.md)). Launched into an empty grid queue (3 jobs) with
  285G free on /nashome — both prior killers absent at launch. R0 landed
  +7 rows in ~1.5h (empty queue halves round time); 3/10 crashed at G4
  init. **Parent killed after R0** when the crash was root-caused.
- **⚠ ALL 62 foilsg leaderboard rows are geometry-tainted (2026-06-12).**
  The grid tarball never had the holeRadii-vector patch — every foilsg
  job built a UNIFORM-hole stack at hole = mean(f_g·rOut_g), not the
  per-group holes the x-points describe; children crashed outright when
  that mean exceeded min_g(rOut_g) (3/10 foilsg06, 7/10 foilsg05). The
  "champion" sob=3.16 (foilsg06R00_07) is a uniform-hole result. The
  hazard was documented at wiring time (patched-lib bullet above) but the
  tarball was never verified. Root cause + fix recipe:
  [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md). Campaign paused
  until the tarball is rebuilt from the patched workdir.

## Open questions / TODO
- Does foilsg03+ (more rounds, more evals) clear foilsf 3.89 ceiling, or
  does 12-D space need wider per-group bounds (e.g. asymmetric hT bounds
  per group, since foilsf champions all wanted upstream-thin / downstream-
  thicker)?
- 4 groups is a guess (vs 7-group / 13-group); revisit if leaderboard rows
  suggest strong z-asymmetry the 4-group partition can't capture.
