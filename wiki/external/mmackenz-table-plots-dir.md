---
type: external
title: mmackenz_table_plots/ — off-repo analysis + picker scripts dir
description: off-repo /data dir holding ~20 unversioned picker/renderer scripts
  + artifacts; name is historical misnomer; 3 hardcoded repo refs; migration blocked
  while a closed-loop runs
status: active
timestamp: '2026-06-02'
---

# mmackenz_table_plots/ — off-repo analysis + picker scripts dir

## Summary
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/` is an
**off-repo** directory (on the /data volume, NOT under the git tree at
`/exp/mu2e/app/.../autoresearch`) holding ~20 Python scripts — the BO pickers,
GP-cloud renderers, overlays, saturation report — mixed with their generated
artifacts (PNGs, GIFs, TSVs). Some of these scripts are **load-bearing**:
`gp_predict_{foils,helical}.py` are imported live by the closed-loop picker.

## Key facts
- **Why "mmackenz" (historical drift):** it began as plots of mmackenz's
  hand-designed config TABLE — `scrape_geom_params.py` scrapes
  `geom_params.tsv` from the [mmackenz-workflow](/external/mmackenz-workflow.md) tree; "table_plots" = plots
  of that table. It then accreted ALL the BO renderers/shims/overlays. The
  name is now a **misnomer** — almost nothing in it is mmackenz-specific.
- **Why on /data:** /app (repo volume) has tight quota; /data is the big
  volume, so large regenerable artifacts (GIFs ~2.9 MB, PNGs ~200–250 KB)
  live there to keep git lean — same rationale as
  [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md). It's also a sibling of the
  `autoresearch_grid/` work tree it plots.
- **Smell:** ~20 scripts there are CODE, unversioned (no git history/review).
  `botorch_predict_helical.py` was once deleted before a snapshot window
  (see [bo-helical](/projects/bo-helical.md)) — exactly this fragility. Artifacts on /data is fine;
  load-bearing code on /data is the risk.
- **THREE hardcoded repo refs pin this path** (must all change on any move):
  - `graph/closed_loop.py:86` — `GP_SCRIPT_DIR` (picker import dir)
  - `botorch_predict.py:6` — docstring pointer to `gp_predict_{foils,helical}.py`
  - `autoresearch_bo_michael.py:76` — `GEOM_TSV = .../geom_params.tsv`
- **Size breakdown (2026-06-02 `du`):** 2.2 GB total, but that's **1.6 GB of
  TSV/JSON** (sobol prediction dumps, scraped tables) — the actual size driver.
  Code is **147 KB** (all 20 `.py`); PNGs 4.6 MB (39); GIF 2.4 MB. For scale
  the repo `.git` is 14 MB, `docs/` 4.5 MB. **Conclusion: size is NOT a reason
  to keep the code on /data** — moving 147 KB into git is free; only the
  1.6 GB of regenerable data tables justifies /data. The earlier "keep
  artifacts off git" rationale conflated code with the data tables.
  - **What the 1.6 GB actually is:** four HELICAL prediction dumps —
    `gp_predictions_helical{,_nolegacy,_fixC}.tsv` (**509 MB each**, full
    ~2²⁰ Sobol-grid GP predictions) + `botorch_predictions_helical.tsv`
    (64 MB). The three 509 MB files are near-duplicate A/B variants
    (base / no-legacy / fix-C experiment snapshots). **`_nolegacy` + `_fixC`
    (~1 GB, 509 MB each, May 21, no code refs) DELETED 2026-06-02** → dir now
    1.2 GB; kept the base `gp_predictions_helical.tsv` (509 MB) + botorch
    (64 MB). No foils/v2 data is large. All regenerable from the renderer.
- **Proposed migration (2026-06-02, not yet done):** move CODE into the repo
  (versioned `autoresearch/analysis/`), keep only artifacts on /data under a
  clearer name (e.g. `autoresearch_grid/bo_plots/`), update the 3 refs.
- **Migration is BLOCKED while a closed-loop campaign runs:** the live parent
  imports `gp_predict_foils` from `GP_SCRIPT_DIR` every round's
  `predict_picks`; renaming/moving mid-run → ImportError → campaign dies.
  Do it between campaigns, or leave a symlink `mmackenz_table_plots → <new>`.

## Cross-links
- Related: [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), [closed-loop-runner](/drivers/closed-loop-runner.md), [batch-bo](/concepts/batch-bo.md),
  [mmackenz-workflow](/external/mmackenz-workflow.md), [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md)
- Source refs: `graph/closed_loop.py:86`, `botorch_predict.py:6`,
  `autoresearch_bo_michael.py:76`

## Open questions / TODO
- Execute the code→repo / artifacts→renamed-dir migration after the current
  foilsY campaign completes.
