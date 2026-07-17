---
type: driver
title: autoresearch_bo.py — original 7D BO driver (removed)
description: original 7D BO driver
status: superseded
status_note: (removed 2026-05-21; replaced by [[autoresearch-bo-michael]])
timestamp: '2026-05-21'
---

# autoresearch_bo.py — original 7D BO driver (removed)

## Summary
First-generation BO driver, optimizing only Run1A CE S/√B over a 7D foil-stack
search space. Removed from the repo on 2026-05-21 once its only consumers
(itself + the matching `autoresearch_loop.py` predecessor) were retired in
favor of [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md). The page is kept so cross-links from
[bo-foil](/projects/bo-foil.md) and the wiki history don't dangle.

## Key facts
- **Removed:** 2026-05-21 — see commit `git log --diff-filter=D -- autoresearch_bo.py`.
- **Why removed:** every load-bearing pattern (SETUP env, fork_config,
  run_pipeline, append_leaderboard) was reused-and-extended in
  `autoresearch_bo_michael.py`. The standalone script had no active call
  site; `leaderboard_bo.tsv` is still on disk only because slides/ analyzers
  and the data-side overlay still read it.
- **History TSV:** `leaderboard_bo.tsv` (kept, see [leaderboards](/datasets/leaderboards.md))

## Cross-links
- Project: [bo-foil](/projects/bo-foil.md)
- Successor: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)
