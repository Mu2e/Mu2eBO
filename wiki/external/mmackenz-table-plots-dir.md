---
type: external
title: mmackenz_table_plots/ — off-repo analysis + picker scripts dir
description: off-repo /data dir holding 46 unversioned picker/renderer scripts
  + artifacts; name is historical misnomer; the 3 repo->dir refs are GONE (no
  repo module imports it any more) and 12 of its scripts are dead-and-stamped
status: active
timestamp: '2026-08-22'
updated_note: '2026-08-22 audit: repo->dir coupling fully severed; 12 scripts
  verified DOES-NOT-RUN and stamped in place; the 12 live foilspf deck
  generators import nothing from the repo'
---

# mmackenz_table_plots/ — off-repo analysis + picker scripts dir

## Summary
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/` is an
**off-repo** directory (on the /data volume, NOT under the git tree at
`/exp/mu2e/app/.../autoresearch`) holding ~20 Python scripts — the BO pickers,
GP-cloud renderers, overlays, saturation report — mixed with their generated
artifacts (PNGs, GIFs, TSVs). It is **no longer load-bearing**: the closed
loop stopped importing `gp_predict_*.py` when the skopt kernel was retired
(2026-07-18), and as of 2026-08-22 no module under `core/` or `graph/` names
this directory at all.

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
- **The three hardcoded repo refs are GONE (verified 2026-08-22):**
  `grep -n "GP_SCRIPT_DIR\|gp_predict_\|GEOM_TSV\|mmackenz_table_plots"
  core/*.py graph/*.py` returns nothing. Was: `graph/closed_loop.py:86`
  `GP_SCRIPT_DIR`, `botorch_predict.py:6` docstring, `bo_driver.py:76`
  `GEOM_TSV`. **The directory can now be moved without touching the repo.**
- **12 of the 46 scripts DO NOT RUN, and are stamped as such in place
  (2026-08-22).** Verified by executing each against a worktree of the
  pre-audit tree AND the current one — identical failures on both, so none
  of it was caused by the 2026-08-22 slim-down. Blockers: 7 die at `from
  skopt import Optimizer` (skopt retired 2026-07-18, absent from cvmfs
  `ana 2.8.0` and the dev venv; their `cl_min` strategy went with it per
  ADR-0001) — `gp_predict_{foilsflash,foilsf,foils,foilsg,ipa}.py`,
  `diversity_overlay_foils.py`, `loco_picker_eval.py`; 3 at
  `bo.HelicalMode` — `gp_predict_helical.py`,
  `botorch_predict_helical.py`, `overlay_knob_locations.py`; 2 on a mode
  that is in neither `mode_specs/` nor its archive —
  `botorch_predict_prodtarget{,6d}_cloud.py`. Originals are in
  `_backup_20260822/`.
- **The 12 LIVE foilspf deck generators import NOTHING from the repo**
  (`gp_predict_foilspf*_perpot_cloud.py`, `sketch_foilspf*.py`): they read
  the leaderboard TSV and train their own sklearn GPs. The deck-refresh path
  is therefore insulated from repo refactors — checked after the slim-down.
  `gp_predict_ipa_cloud.py` and `foils_v2_loader.py` are self-contained the
  same way and still run; only their comments named retired symbols.
- **REVERSE coupling (these plotters hardcode the repo's module + leaderboard
  paths) — REBASED onto the 2026-07-17 core/leaderboards/ reorg.** 20 scripts
  were rewritten in one pass: every `sys.path.insert(0, <repo root>)` →
  `<root>/core` (the BO modules moved to `core/`), and every
  `ROOT/"leaderboard_bo_<mode>.tsv"` → `ROOT/"leaderboards"/…` (incl. the
  absolute-path `overlay_bo_on_s_sqrt_b.py` and loco's embedded `python -c`
  snippet). Pre-edit backup:
  `autoresearch_archive/mmackenz_table_plots_prereorg_20260717.tar.gz`.
  **CONVENTION GOING FORWARD:** a new off-repo plotter must
  `sys.path.insert(0, str(AUTORESEARCH / "core"))` to import `bo`/`bp`, and
  read leaderboards as `AUTORESEARCH / "leaderboards" / "leaderboard_bo_<mode>.tsv"`.
  The old flat-root forms silently fail (module not found / stale-PNG
  half-refresh).
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
  `bo_driver.py:76`

## Open questions / TODO
- Execute the code→repo / artifacts→renamed-dir migration after the current
  foilsY campaign completes.
