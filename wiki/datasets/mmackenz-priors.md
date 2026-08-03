---
type: dataset
title: mmackenz priors — geom_params.tsv
description: 104 hand-designed configs; 96 with both metrics
status: active
timestamp: '2026-05-15'
---

# mmackenz priors — geom_params.tsv

## Summary
Mike McKenzie's 104 hand-designed Run1B configurations, joined to the metrics
from his `table.org`. The canonical seed dataset for [bo-michael](/projects/bo-michael.md). Built by
expanding each `config_v##/run1b_beam/geom.txt` include chain and resolving
last-assignment-wins overrides.

## Key facts
- **TSV path:** `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/geom_params.tsv`
- **Builder:** `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/scrape_geom_params.py`
- **Source tree:** `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/config_v##/`
  (see [mmackenz-workflow](/external/mmackenz-workflow.md))
- **Row count:** 104 total; 96 with both `run_1a_ce_s_sqrt_b` and `calo_stop_per_pot`
- **Topology breakdown** (after metric filter): 76 degrader-OFF, 20 degrader-ON
- **Top configs (degrader=ON):** v39 (obj 3.459), v38, v34, v41, v40
- **Knob columns added in latest scrape:** `tsda_rin`, `tsda_r4`, `tsda_halfLength4`,
  `tsda_z0`, `tsda_material`, `tsda_extra_build`, `tsda_tubes_build`,
  `tsda_helical_build`, `tsda_cutout_build`, `coll5_material1`,
  `hasProtonAbsorber`, `degrader_in_beam`, `degrader_halfLength`, `topology`
- **Helical inner knobs NOT in TSV:** scraper captures only the boolean
  `tsda_helical_build`. The 5 inner knobs (`dx, dy, halflength, z0, angle`)
  must be parsed from `config_v##/run1b_beam/geom.txt` directly. [bo-helical](/projects/bo-helical.md)
  does this in `hel_load_priors()`. If you need helical knobs for any other
  consumer, either extend `scrape_geom_params.py` or call the same helper.
- **Helical-flagged rows:** 11 configs have `tsda_helical_build=True`
  (v100–v104, v106–v111). v110 missing sob → 10 usable for BO. v105 has no
  helical plug despite being in the v100s naming range.

## Cross-links
- Consumed by: [bo-michael](/projects/bo-michael.md), [bo-helical](/projects/bo-helical.md), [bo-driver](/drivers/bo-driver.md)
- Source-of-truth: [mmackenz-workflow](/external/mmackenz-workflow.md)
- Categorical projection: [col5-shield](/concepts/col5-shield.md)
