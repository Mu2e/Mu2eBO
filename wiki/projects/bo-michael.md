---
type: project
title: bo-michael — joint S/√B and calo/POT optimization
description: (**code retired 2026-07-12**) 4D BO maximizing `S/√B − α·calo/POT`
  over TSdA + holeRadius + COL5; `MichaelMode` deleted, leaderboard frozen
status: superseded
status_note: '`MichaelMode` class DELETED from code 2026-07-12 (was the last non-holeRadii
  Categorical-COL5 mode; superseded by [bo-foils](/projects/bo-foils.md) family long before). Leaderboard
  TSVs remain on disk as frozen artifacts; the mode is no longer in `MODES`/`modes.SPECS`
  and `--mode michael` is rejected.'
timestamp: '2026-07-12'
updated_note: code retired
---

# bo-michael — joint S/√B and calo/POT optimization

## Summary
Bayesian Optimization of Mu2e detector geometry to jointly maximize Run1A CE
S/√B and minimize Run1B calo_stop_per_pot, scalarized as
`obj = sob − α·calo` with α=1e5. Seeded from mmackenz's 96 prior configurations
(those with both metrics populated). Search space is 4D after pinning
[degrader](/concepts/degrader.md) off.

## Key facts
- **Search space (4D):**
  - `tsda.rin` ∈ [0.001, 130.0] mm — bimodal in priors, dominant variance
  - `tsda.halfLength4` ∈ [7.5, 12.5] cm — modest leverage
  - `stoppingTarget.holeRadius` ∈ [0.0, 50.0] mm — sparse but present
  - `col5` ∈ {"air", "poly"} — categorical, see [col5-shield](/concepts/col5-shield.md)
- **Pinned constants:** `tsda.r4=600`, `tsda.z0=4195`, `materialName=StoppingTarget_Al`
  (>85% of mmackenz configs use these); `degrader.build=false, rotation=180.0`
  (out of beam — see [degrader](/concepts/degrader.md))
- **α=1e5** chosen so 1e-5 calo cost ≈ 1 unit of S/√B (mmackenz calo range
  4e-8 .. 2.5e-5). See [scalarized-objective](/concepts/scalarized-objective.md).
- **Best known with degrader=OFF:** mmackenz subset ceiling ~obj 2.10
- **Best known with degrader=ON:** v39 → obj=3.459
  (rin=130, hL4=8.75, hole=21.5, col5=COL5Poly, sob=3.48, calo=2.13e-7).
  Switching the pin would raise the achievable ceiling by ~1.4 units.
- **Driver:** [bo-driver](/drivers/bo-driver.md) (default `--mode michael`; sibling: [bo-helical](/projects/bo-helical.md))
- **Preflight:** [preflight](/drivers/preflight.md) catches G4 init failures locally before grid submission

## Cross-links
- Source: `bo_driver.py`
- Sibling modes: [bo-helical](/projects/bo-helical.md), [bo-foils](/projects/bo-foils.md)
- Predecessor: [bo-foil](/projects/bo-foil.md) (this supersedes it)
- Priors: [mmackenz-priors](/datasets/mmackenz-priors.md)
- Design constraint: [fixed-geometry-constraint](/concepts/fixed-geometry-constraint.md) (degrader=off in both Run1A and Run1B)
- Known failure mode: [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md)
- Known data bug fix: [col5-projection-bug](/incidents/col5-projection-bug.md)

## Open questions / TODO
- Decide whether to flip `degrader` pin from off→on to chase obj~3.5 ceiling
- Fix `render_geom()` baseline so run1b_mubeam stage uses `geom_run1_b_v06.txt`
  (task #21) — currently emits `geom_run1_a.txt` only
- mike001 grid submission outcome → record in [leaderboards](/datasets/leaderboards.md)
