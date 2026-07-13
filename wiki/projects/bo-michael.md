# bo-michael — joint S/√B and calo/POT optimization

**Type:** project
**Status:** superseded — `MichaelMode` class DELETED from code 2026-07-12 (was the last non-holeRadii Categorical-COL5 mode; superseded by [[bo-foils]] family long before). Leaderboard TSVs remain on disk as frozen artifacts; the mode is no longer in `MODES`/`modes.SPECS` and `--mode michael` is rejected.
**Updated:** 2026-07-12 (code retired)

## Summary
Bayesian Optimization of Mu2e detector geometry to jointly maximize Run1A CE
S/√B and minimize Run1B calo_stop_per_pot, scalarized as
`obj = sob − α·calo` with α=1e5. Seeded from mmackenz's 96 prior configurations
(those with both metrics populated). Search space is 4D after pinning
[[degrader]] off.

## Key facts
- **Search space (4D):**
  - `tsda.rin` ∈ [0.001, 130.0] mm — bimodal in priors, dominant variance
  - `tsda.halfLength4` ∈ [7.5, 12.5] cm — modest leverage
  - `stoppingTarget.holeRadius` ∈ [0.0, 50.0] mm — sparse but present
  - `col5` ∈ {"air", "poly"} — categorical, see [[col5-shield]]
- **Pinned constants:** `tsda.r4=600`, `tsda.z0=4195`, `materialName=StoppingTarget_Al`
  (>85% of mmackenz configs use these); `degrader.build=false, rotation=180.0`
  (out of beam — see [[degrader]])
- **α=1e5** chosen so 1e-5 calo cost ≈ 1 unit of S/√B (mmackenz calo range
  4e-8 .. 2.5e-5). See [[scalarized-objective]].
- **Best known with degrader=OFF:** mmackenz subset ceiling ~obj 2.10
- **Best known with degrader=ON:** v39 → obj=3.459
  (rin=130, hL4=8.75, hole=21.5, col5=COL5Poly, sob=3.48, calo=2.13e-7).
  Switching the pin would raise the achievable ceiling by ~1.4 units.
- **Driver:** [[autoresearch-bo-michael]] (default `--mode michael`; sibling: [[bo-helical]])
- **Preflight:** [[preflight]] catches G4 init failures locally before grid submission

## Cross-links
- Source: `autoresearch_bo_michael.py`
- Sibling modes: [[bo-helical]], [[bo-foils]]
- Predecessor: [[bo-foil]] (this supersedes it)
- Priors: [[mmackenz-priors]]
- Design constraint: [[fixed-geometry-constraint]] (degrader=off in both Run1A and Run1B)
- Known failure mode: [[geom-run1a-vs-run1b]]
- Known data bug fix: [[col5-projection-bug]]

## Open questions / TODO
- Decide whether to flip `degrader` pin from off→on to chase obj~3.5 ceiling
- Fix `render_geom()` baseline so run1b_mubeam stage uses `geom_run1_b_v06.txt`
  (task #21) — currently emits `geom_run1_a.txt` only
- mike001 grid submission outcome → record in [[leaderboards]]
