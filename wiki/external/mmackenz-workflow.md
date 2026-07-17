---
type: external
title: mmackenz Run1B workflow tree
description: '`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/`'
status: active
timestamp: '2026-05-15'
---

# mmackenz Run1B workflow tree

## Summary
Mike McKenzie's hand-designed Run1B configuration sweep. Source-of-truth for
the priors that seed [bo-michael](/projects/bo-michael.md) and the reference syntax for our geom
override files.

## Key facts
- **Root:** `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/`
- **Per-config tree:** `config_v##/run1b_beam/geom.txt` (entry point;
  fallback `config_v##/run1a_beam/geom.txt`)
- **Metric source:** `workflows/table.org`
- **Reference geom:** `config_v50/run1b_beam/geom.txt` — used as the
  template for [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)'s `render_geom()` syntax
- **Helpful scripts:**
  `workflows/scripts/extract_analysis_results.py` — calo extraction logic
  reused by [pipeline](/drivers/pipeline.md)
  `workflows/scripts/plot_table_configs.py` — `parse_table_file`, `parse_float`

## Cross-links
- Related: [mmackenz-table-plots-dir](/external/mmackenz-table-plots-dir.md)
- Consumed by: [mmackenz-priors](/datasets/mmackenz-priors.md), [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md)
