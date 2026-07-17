---
type: project
title: bo-foil — original 7D foil-stack BO
description: original 7D BO over foil-stack geometry; superseded by bo-michael
status: superseded
status_note: by [[bo-michael]]; driver removed 2026-05-21
timestamp: '2026-05-21'
---

# bo-foil — original 7D foil-stack BO

## Summary
First-generation Bayesian Optimization driver. Searches a 7D space of foil-stack
geometry parameters, optimizing only Run1A CE S/√B. Superseded because the foil
topology is *not* where mmackenz's variance lives: across 76 degrader-out
configs the foil features collapse to only 5 unique vectors yet S/√B ranges
0.23–3.30. The actual leverage is in TSdA core + holeRadius + COL5, which is
what [bo-michael](/projects/bo-michael.md) now optimizes.

## Key facts
- **Driver:** `autoresearch_bo.py` ([autoresearch-bo](/drivers/autoresearch-bo.md)) — **removed 2026-05-21**;
  its patterns (SETUP env, fork_config, run_pipeline, append_leaderboard)
  live on in `autoresearch_bo_michael.py`.
- **History:** `leaderboard_bo.tsv` (kept on disk; consumed by slides/
  analyzers and the data-side overlay scripts).

## Cross-links
- Related: [bo-foilsg](/projects/bo-foilsg.md)
- Successor: [bo-michael](/projects/bo-michael.md)
- Driver page: [autoresearch-bo](/drivers/autoresearch-bo.md)
