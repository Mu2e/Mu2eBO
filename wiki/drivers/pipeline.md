---
type: driver
title: pipeline.py — parametric grid runner
description: 'per-config runner: forks config, submits grid, harvests'
status: active
timestamp: '2026-06-07'
updated_note: added `harvest-pot-only` subcommand for bo-prodtarget
---

# pipeline.py — parametric grid runner

## Summary
One canonical pipeline.py at the repo root. Pass `--config CFG`; per-config
paths (work tree, geom file, DSCONF, /pnfs staging dir, stage `desc` strings)
are derived from CFG. Invoked once per BO iteration after `propose` to submit
the multi-stage workflow to the grid and harvest results into `summary.json`.

Replaced the per-config rsync+sed fork pattern (see [template-fcl-staleness](/incidents/template-fcl-staleness.md)
for the failure that motivated this).

## Key facts
- **Path:** `pipeline.py` (project root)
- **Templates:** `pipeline_templates/<stage>/template.fcl` with the geom
  basename slot marked `__GEOM_FILE__`. `submit_stage` substitutes
  `autoresearch_<cfg>_geom.txt` and writes the materialized FCL to
  `<work_root>/<cfg>/state/<stage>_template_materialized.fcl` before handing
  it to mu2ejobdef.
- **MuBeamCat input lists:** shared across all configs at
  `pipeline_templates/{mubeam,run1b_mubeam}/MuBeamCat.txt` (referenced by
  absolute path in the auxinput; no per-config copy).
- **Per-config work tree** (auto-created on first `--config CFG` invocation):
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/` with `geom/`,
  `<stage>/` (cnf tarballs + Code.tar.bz2), `state/` (cluster IDs, output
  lists, materialized FCL), `harvest/` (summary.json, EdepAna outputs).
- **PNFS staging:** `/pnfs/mu2e/scratch/users/$USER/autoresearch_grid/<cfg>/staged/`
- **Subcommands:** `submit | poll | list-outputs | harvest | harvest-pot-only`
  (a `materialize` debug verb was removed 2026-07-12 — zero callers;
  `_materialize_template` itself lives on inside `submit`). `harvest-pot-only` (added
  2026-06-07 for [bo-prodtarget](/projects/bo-prodtarget.md)) is a separate uproot-based subcommand
  (not a switch on `harvest`) because the objective differs (`mu_per_POT` at
  VD sid=8 vs S/√B − α·calo/POT) and the chain is single-stage — cleaner as
  a parallel command than rewiring `cmd_harvest`. VD branch is `sid` (not
  `vdid`); denominator is `genCountLogger/numEvents` (1-bin TH1D, exact POT
  per file). `harvest-pot-only` only checks the `pot_only` stage SHA — the
  4-stage harvest checks all four.
- **Idempotency (landed 2026-05-19 for Phase 2b LangGraph wiring):**
  `submit` no-ops with `"already submitted (cluster=NNN); skip submit"` if
  `<stage>_cluster.txt` already exists. `list-outputs` no-ops if
  `<stage>_outputs.txt` exists AND every basename in it still resolves under
  the `/pnfs` outstage. Either guard can be bypassed with `--force` (re-submits
  to a new cluster / re-globs /pnfs respectively); use `--force` when a stage
  needs to be reseeded with a different cluster (rare; usually the right move
  is to delete the cluster file by hand). Poll and harvest have always been
  naturally re-entrant. The guards enable the LangGraph stage nodes (see
  [graph-runner](/drivers/graph-runner.md)) to safely re-run after a checkpoint kill or hot-reload
  without double-submitting — see graph007 incident, 2026-05-19, where three
  successive submits clobbered the cluster file before the guards landed.
- **Preemptive token renewal (`submit_stage` lines 319-326, landed 2026-05-18):**
  Before every `mu2ejobsub` invocation, runs
  `bash -c 'source $SETUPMU2E && getToken'` to refresh the bearer token
  idempotently. Addresses the "cached token went stale under concurrent
  submission" sub-flavor of [concurrent-token-contention](/incidents/concurrent-token-contention.md). The
  jobsub_lite cache-dir same-second collision is NOT addressed by this and
  still needs a per-user flock (TODO).
- **Stages:** `mubeam` → `concat` → `mustops_ce` (Run1A) and `run1b_mubeam`
  (Run1B), defined in module-level `STAGES` dict. Plus `pot_only`
  (single-stage, MDC2025aq-backed) added 2026-06-07 for [bo-prodtarget](/projects/bo-prodtarget.md).
  Stage selection for a chain is owned by `GRID_STAGES_BY_MODE` in
  `graph/config.py` (Mu2eBO issue #15, design only as of 2026-06-07);
  invoked-by-name `pipeline.py submit <stage>` works for any STAGES entry
  regardless of mode dispatch.
- **Per-stage backing override (2026-06-07):** two optional STAGES keys
  let one stage swap out from the helical-patched Run1Bak default:
  - `"code_tarball"`: absolute path to an alternate muse-built
    `Code_*.tar.bz2` (used by `write_code_tarball(stage_dir,
    base_tarball=...)`). Default is module-global `MUSE_BASE_TARBALL`
    (helical-patched Run1Bak).
  - `"dsconf_musing"`: string substituted into DSCONF as
    `f"{musing}_{cfg}"` (via new `_stage_dsconf(stage)` helper at
    pipeline.py:113). Default is module-global `DSCONF = f"Run1Bak_{cfg}"`.
    Only affects the cnf filename and the `--dsconf` arg of mu2ejobdef
    (does NOT propagate into /pnfs paths). Without this, prodtarget
    output files were mislabeled `…Run1Bak_pt001…` despite being built
    against MDC2025aq.
- **Geom overlay:** ships via `Code.tar`; geom-bearing stages
  (mubeam, run1b_mubeam, mustops_ce) reference the same
  `autoresearch_<cfg>_geom.txt` basename via the `__GEOM_FILE__` substitution.
- **Geom auto-staging:** `autoresearch_bo_michael.py propose <cfg>` copies the
  rendered proposal into `<work_root>/<cfg>/geom/` so `pipeline.py --config
  <cfg>` runs without manual prep.
- **Harvest output:** `summary.json` with `s_over_sqrt_b`, `calo_per_pot`,
  and a `config` field naming the CFG.
- **Calo extraction:** reuses `_extract_target_al_entries` from mmackenz's
  `Run1BAna/workflows/scripts/extract_analysis_results.py`, with
  `_MUBEAM_INPUT_EFFICIENCY_BY_FCL = 0.01278168` correction.
- **Harvest env (`sourced_env(with_muse=True)`, pipeline.py:172):** sources
  `autoresearch_muse` with `muse setup -q p094` AND prepends mmackenz's
  Run1BAna lib dir to `CET_PLUGIN_PATH` + `LD_LIBRARY_PATH`. Reason: EdepAna
  lives in mmackenz's personal `Run1BAna` repo
  (`github.com/michaelmackenzie/Run1BAna`, **not** in Mu2e org and **not** in
  Offline/Run1Bak). Building it locally needs `EventNtuple` + an older
  Run1BAna commit that matches v13_12_10 ABI (HEAD references `_caloCluster`
  which v13_12_10 doesn't have). Cheaper: harvest is local-only so /exp paths
  work; we just borrow the prebuilt lib at
  `/exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so`.
- **Worker Offline source = canonical muse tarball** (`pipeline.py:45-54`
  `MUSING` + `MUSE_BASE_TARBALL`). `write_code_tarball` extracts the prebuilt
  `Code_helical_base.tar.bz2` (produced by `muse tarball` in
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/`), drops the per-config
  geom into `Code/`, writes `Code/setup_post.sh` with `MU2E_SEARCH_PATH` +
  `FHICL_FILE_PATH` extensions, then repacks. The base tarball's `setup.sh`
  calls `muse setup $CODE_DIR -q e29 prof p094`, which puts the local libs
  ahead of CVMFS via Muse's normal link/path order.
- **Helical-plug lib (landed 2026-05-17, canonicalized later that day):**
  Patched `libmu2e_Mu2eG4.so` (containing `mu2e::makeHelicalPlug` +
  `build_helical` branch in `constructTSdA`) lives inside the base tarball at
  `Code/build/al9-prof-e29-p094/Offline/lib/`. Build artifact source is
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/` (mgit Mu2eG4 sparse
  checkout of v13_12_10 + helical-plug.patch, backed by SimJob/Run1Bak,
  `muse build -j 8 → muse tarball`). See [muse-backing-pattern](/external/muse-backing-pattern.md) for the
  build recipe and [calo-constant-across-helical](/incidents/calo-constant-across-helical.md) for the motivating bug.
- **Historical: `LD_PRELOAD` retired 2026-05-17.** An earlier same-day
  iteration shipped the patched lib as `Code/lib/libmu2e_Mu2eG4.so` + an
  `export LD_PRELOAD=` line in `setup.sh`, because `LD_LIBRARY_PATH` is
  beaten by the `mu2e` binary's rpath. The canonical `muse setup` path
  achieves the same override via link order without needing LD_PRELOAD; the
  hand-rolled setup.sh + `Code/lib/` were dropped.
- **Failed Musing-swap attempt 2026-05-16 (historical):** `write_code_tarball`
  was briefly modified to `pushd /exp/mu2e/app/users/mmackenz/run1b && muse
  setup && popd`. All 400 helical002 smoke-test jobs (clusters 84316127,
  27871333) returned only `.log` files because **grid workers only mount
  `/cvmfs/*`** (`/exp/mu2e/app` invisible). Replaced by the tarball-shipping
  approach above; the patched lib travels inside `Code.tar.bz2` via `--code`
  staging, so worker mounts don't matter.

## Cross-links
- Consumed by: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md) `evaluate`, [graph-runner](/drivers/graph-runner.md) (per-stage nodes)
- Geom rendered by: [autoresearch-bo-michael](/drivers/autoresearch-bo-michael.md) `propose` (auto-stages into work tree)
- Regression tests: [tests](/drivers/tests.md) (pins the `_check_stage_config_sha` contract)
- See: [grid-job-completion-check](/incidents/grid-job-completion-check.md) for monitoring conventions
- History: [template-fcl-staleness](/incidents/template-fcl-staleness.md) (the bug this refactor closes)

## Open questions / TODO
- Eventually delete the legacy `smoke_*/` trees under
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/` once the parametric path
  has been the only one driven for a few iterations.
