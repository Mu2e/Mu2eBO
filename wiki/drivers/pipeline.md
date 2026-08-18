---
type: driver
title: pipeline.py — parametric grid runner
description: 'per-config runner: job description is checked-in `stage_entries/<stage>.json`, execution shells prodtools (env `AUTORESEARCH_PRODTOOLS`: json2jobdef/submit/jobwait/runlocal) — submits grid or local, harvests'
status: active
timestamp: '2026-08-16'
updated_note: 'prodtools-switch Task 12: page rewritten end-to-end for the
  final architecture (Tasks 1-14) — job description is now checked-in
  stage_entries/<stage>.json + mode_specs stage_tuning, execution is shelled
  to prodtools (json2jobdef/submit/jobwait/runlocal) via core/prodtools_exec.py,
  mu2ejobdef/mu2ejobsub/local_exec.py/poll_cluster/list_outputs-glob/
  local-build/local-run/--cap-hours are all deleted; supersedes the
  mu2ejobdef-era content this page carried through 2026-08-16'
---

# pipeline.py — parametric grid runner

## Summary
One canonical pipeline.py at the repo root. Pass `--config CFG`; per-config
paths (work tree, geom file, DSCONF, /pnfs staging dir, stage `desc` strings)
are derived from CFG. Invoked once per BO iteration after `propose` to submit
the multi-stage workflow to the grid and harvest results into `summary.json`.

Replaced the per-config rsync+sed fork pattern (see [template-fcl-staleness](/incidents/template-fcl-staleness.md)
for the failure that motivated this). As of the 2026-08-16 **prodtools
switch**, `pipeline.py` no longer owns job execution at all: it renders a
job description and shells [prodtools](/external/muse-backing-pattern.md)
(env `AUTORESEARCH_PRODTOOLS`) to build, run, and wait on it. The old
`mu2ejobdef`/`mu2ejobsub` wrappers, the local-only executor
(`core/local_exec.py`), the `poll_cluster` wall-clock-cap loop, and the
outstage glob-walker are all deleted — see
[local-executor](/drivers/local-executor.md) (superseded) for the executor
this replaced.

## Key facts

### Job description: stage_entries/ + mode_specs stage_tuning
- **Path:** `core/pipeline.py` (moved from project root in the 2026-07-17
  reorg; this page's "project root" wording was stale — fixed 2026-07-19)
- **Checked-in per-stage JSON, `stage_entries/<stage>.json`** (one file per
  stage: `mubeam`, `run1b_mubeam`, `concat`, `mustops_ce`, `elebeam_flash`)
  is now the single job description, in **json2jobdef's own native entry
  schema** — retired 2026-08-16 (prodtools-switch Tasks 13+14) from two
  earlier generations: the hand-written
  `pipeline_templates/<stage>/template.fcl` files (Task 13), then
  `core/pipeline.py`'s `STAGE_FCL` Python dict (Task 14, lifted to JSON so
  the entry is reviewable/diffable independent of code). Each file carries
  whatever subset of `fcl` (the *published* Production FCL path, e.g.
  `Production/JobConfig/pileup/MuBeamResampler.fcl` — not a per-config
  materialized file), `fcl_overrides` (flat dotted-key dict, rendered
  directly by prodtools' `write_fcl_template`), `resampler_name`,
  `input_data`, `inloc`, `outloc`, `run`, `memory`, `events` that stage
  needs (a merge stage like `concat` has neither `run` nor `events`; a
  staged-input stage like `mustops_ce` has no `input_data`).
- **Two placeholders only**, substituted by `core/prodtools_exec.py`'s
  `load_stage_entry`: `{cfg}` and `{geom}` (the geom basename,
  `autoresearch_<cfg>_geom.txt`). Any other `{token}` in a stage_entries
  JSON string is a loud `ValueError` at load time — never a literal
  `{typo}` string riding into a submitted FHiCL override. Runtime fields
  (njobs, events/memory overrides from a mode's `stage_tuning`, staged
  `input_data`/`inloc` for a consuming stage, mustops_ce's concat-less
  `MaxEventsToSkip` toggle 100720→8000) are merged in by `pipeline.py`
  after `load_stage_entry` returns — never templated into the JSON itself.
- **`'#include'` first, then the rest of `fcl_overrides`.** mubeam and
  run1b_mubeam each need ONE static extras FCL
  (`pipeline_templates/{mubeam,run1b_mubeam}_extras.fcl`, not per-config)
  for the handful of `@sequence::`-bearing overrides (`outputCommands`,
  mubeam's `targetStopPath`) that cannot be expressed as a JSON value at
  all — pulled in via the entry's `fcl_overrides['#include']` list and
  shipped in the per-config code tarball the same way the geom overlay is.
- **Load-bearing gotcha found during Task 13's real-env validation**: a
  *nested* FCL table override (e.g. `"physics.filters.muminusSelector": {
  "module_type": ..., ... }`) is NOT viable even though it's valid JSON —
  `write_fcl_template`'s `json.dumps()` always quotes dict KEYS
  (`"module_type": ...`), and FHiCL table syntax requires bare (unquoted)
  key identifiers; a quoted-key table is a hard `fhicl-get` parse error
  (`detected at or near` the opening `{`), reproduced directly against the
  real prodtools checkout. Fix: flatten to individual dotted leaf keys
  (`"physics.filters.muminusSelector.module_type": "ParticleCodeFilter"`,
  ...) — confirmed against real `Production/*.json` campaign configs, which
  never nest a table literal in `fcl_overrides` either. Lists (including
  nested lists like `ParticleCodes: [[13, ...]]`) are fine; only dict/table
  values break.
- **Assembly:** for a (config, stage), `pipeline.py` calls `load_stage_entry`
  then `core/prodtools_exec.py`'s `render_entry` to merge in the runtime
  fields, then `write_entry` writes the one-element-list json2jobdef entry
  to `state/<stage>_entry.json` — the audit record of exactly what was
  submitted for that stage of that config. `outloc` is caller-supplied
  (the stage_entries JSON value wins; `render_entry`'s `_DEFAULT_OUTLOC`
  fallback fires only for a caller that passes none at all, e.g. a test).
- **MuBeamCat input lists:** shared across all configs at
  `pipeline_templates/{mubeam,run1b_mubeam}/MuBeamCat.txt` (referenced by
  absolute path in the auxinput; no per-config copy).
- **Per-config work tree** (auto-created on first `--config CFG` invocation):
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/` with `geom/`,
  `<stage>/` (cnf tarballs + Code.tar.bz2), `state/` (`<stage>_cluster.txt`,
  `<stage>_jobsub_id.txt`, `<stage>_entry.json`, `<stage>_wait.json`,
  `<stage>_outputs.txt`, config-SHA + events-per-job stamps — no materialized
  FCL anymore, that generation is gone), `harvest/` (summary.json, EdepAna
  outputs).
- **PNFS staging:** `/pnfs/mu2e/scratch/users/$USER/autoresearch_grid/<cfg>/staged/`
- **Subcommands:** `submit | poll | list-outputs | harvest | harvest-pot-only`.
  (`materialize` was removed 2026-07-12 — zero callers, and the mechanism it
  guarded, per-config FCL materialization, no longer exists at all post
  prodtools-switch. `local-build`/`local-run` — the by-hand FCL-editing verbs
  the old local executor exposed — were deleted 2026-08-16 alongside
  `core/local_exec.py`; to inspect the exact FCL a stage will run, read
  `state/<stage>_entry.json`, or `--local --dry-run` to build the cnf without
  submitting.) `harvest-pot-only` (added 2026-06-07 for
  [bo-prodtarget](/projects/bo-prodtarget.md)) is a separate uproot-based
  subcommand (not a switch on `harvest`) because the objective differs
  (`mu_per_POT` at VD sid=8 vs S/√B − α·calo/POT) and the chain is
  single-stage — cleaner as a parallel command than rewiring `cmd_harvest`.
  VD branch is `sid` (not `vdid`); denominator is
  `genCountLogger/numEvents` (1-bin TH1D, exact POT per file).
  `harvest-pot-only` only checks the `pot_only` stage SHA — the 4-stage
  harvest checks all four.

### Execution: submit/poll shell prodtools (env AUTORESEARCH_PRODTOOLS)
- **Everything autoresearch says to prodtools goes through
  `core/prodtools_exec.py`** (`px` in `pipeline.py`): render an entry, build
  the cnf (`json2jobdef`), run it locally (`runlocal`) or submit it to the
  grid (`submit_entry`, via `core/prodtools_submit_driver.py`), wait on it
  (`jobwait`), read back the shared `wait.json` summary. `pipeline.py`
  itself no longer knows how a job actually runs — see the design doc at
  `docs/superpowers/specs/2026-08-16-prodtools-switch-design.md`.
- **`AUTORESEARCH_PRODTOOLS`** must point at a prodtools checkout (the
  directory holding `bin/json2jobdef`); `core/paths.py`'s `prodtools_root()`
  raises `SystemExit` naming the variable if it's unset or the checkout is
  bad. No hardcoded personal-path default in committed code (9f0c43c
  convention) — the operator checkout used for prodtools-switch validation
  is `/exp/mu2e/app/users/oksuzian/muse_050125/prodtools`.
- **`submit <stage>`**: `submit_stage_prodtools` builds the code tarball,
  loads + renders the stage's `stage_entries/<stage>.json` entry (merging in
  runtime njobs/events/memory/staged-input fields), writes
  `state/<stage>_entry.json`, runs `json2jobdef` to build the cnf, then
  either grid-submits (`submit_entry`, under the host-wide `_submit_lock`
  with `_maybe_refresh_token` renewing the bearer token — same
  age-gated renewal that replaced the old always-refresh call, still
  addressing [concurrent-token-contention](/incidents/concurrent-token-contention.md))
  or, with `--local`, runs it in-process via `runlocal`. Grid path writes
  `state/<stage>_cluster.txt` (bare cluster int) AND the NEW
  `state/<stage>_jobsub_id.txt` (`NNNN@schedd`, what `jobwait` needs — the
  old mu2ejobsub-parsed cluster id alone wasn't enough). Local path writes
  the literal runid `"1"` into `<stage>_cluster.txt` plus a
  `state/<stage>_local.txt` marker (the ONLY thing `_is_local_stage` checks
  — never the env var, so a later `poll`/`list-outputs` in a shell that
  happens to still export `AUTORESEARCH_LOCAL` can't silently no-op a poll
  of a live grid cluster). A grid `submit` clears any stale local marker
  first (ordering is load-bearing — see the long comment at
  `cmd_submit`, pipeline.py:~1160).
- **`poll <stage>`**: for a local stage this is a no-op (already complete).
  For a grid stage it calls `px.run_jobwait`, which shells prodtools'
  `jobwait` — **no internal timeout by design**; it blocks until the
  cluster drains or a caller-side timeout kills it. The closed-loop
  barrier's own timeout (`CLOSED_LOOP_BARRIER_MAX_MIN`) is the only
  backstop for a hung/held cluster now — the old `poll_cluster`'s
  `--cap-hours`/24h wall-clock cap is gone. `jobwait` polls
  `jobsub_q`/`condor_history` every `--poll-s` (default 300s); when the
  cluster is gone it does ONE `jobsub_history -limit njobs` call
  (measured 8.4s vs 51s unlimited on a real 999-job cluster) and writes
  `wait.json` with per-index `{index, rc, outputs[...]}`, `ok`, `failed[]`.
  A missing/unreachable history record is `rc: null` (`unknown`) — NEVER
  counted as `ok`; an unverifiable job contributes zero files to harvest's
  denominator (`outputs_from_wait` filters `rc != 0`, including `None`,
  before anything reaches harvest — the
  [harvest-denominator-bug](/incidents/harvest-denominator-bug.md) rule
  extended to the new contract). `cmd_poll` applies acceptance policy on
  top: 0 `ok` jobs is a hard `SystemExit`; below the per-stage `quorum`
  (default 0.9) is a loud WARN but proceeds with what landed — the same
  behavior the old convergence gate had.
- **One results contract, `state/<stage>_wait.json`**: `runlocal --json`
  (local) and `jobwait --json` (grid) write the identical summary shape, so
  everything downstream (`list-outputs`, harvest) is executor-blind. This
  file is the **permanent record of per-job outcomes** — condor history
  fades in days, `wait.json` doesn't.
- **`list-outputs <stage>`**: reads `wait.json` (via `px.read_wait`,
  executor-blind — no more separate grid-glob and local-glob code paths)
  and filters to `ok` (rc==0) jobs whose output basename matches the
  stage's glob, writing `state/<stage>_outputs.txt`; harvest denominators
  are `ok`-only, unchanged in spirit from before the switch, just sourced
  from `wait.json` instead of a `/pnfs` directory walk.
- **Idempotency (landed 2026-05-19 for Phase 2b LangGraph wiring, carried
  through the prodtools switch):** `submit` no-ops with `"already submitted
  (cluster=NNN); skip submit"` if `<stage>_cluster.txt` already exists.
  `list-outputs` no-ops if `<stage>_outputs.txt` exists AND every basename
  in it still resolves on disk. Either guard can be bypassed with `--force`
  (re-submits to a new cluster / re-reads `wait.json` respectively); use
  `--force` when a stage needs to be reseeded with a different cluster
  (rare; usually the right move is to delete the cluster file by hand).
  Poll and harvest have always been naturally re-entrant. The guards
  enable the LangGraph stage nodes (see
  [graph-runner](/drivers/graph-runner.md)) to safely re-run after a
  checkpoint kill or hot-reload without double-submitting — see graph007
  incident, 2026-05-19, where three successive submits clobbered the
  cluster file before the guards landed.
- **Outstage layout is now flat, `<cluster>/<proc>/`** (prodtools'
  convention) rather than the old `<cluster>/00/<hash>/` nesting;
  `scan_logs` walks both shapes so historical clusters still resolve
  ([data-quota-exhausted-grid-accumulation](/incidents/data-quota-exhausted-grid-accumulation.md)
  and other pre-switch incidents that reference the old layout are
  historical).
- **Submission ledger:** `submit`'s grid path reserves-then-attaches a row
  in prodtools' submission ledger at
  `$AUTORESEARCH_DATA_ROOT/prodtools_ledger/submissions.db` (per-project,
  outside the repo checkout — 9f0c43c convention); internal bookkeeping
  only, never read back for completion detection (that's `wait.json`'s
  job).
- **Deleted 2026-08-16 (prodtools-switch Tasks 1-14), not just superseded:**
  `core/local_exec.py`; the `mu2ejobdef`/`mu2ejobsub` command-building and
  cluster-id-parsing wrappers; `poll_cluster`; the outstage glob-walker
  (module-level `list_outputs`); the `local-build`/`local-run` argparse
  verbs and their `cmd_local_build`/`cmd_local_run` handlers; the
  deprecated `--cap-hours` flag; all five
  `pipeline_templates/<stage>/template.fcl` files. ~800-900 lines removed
  from autoresearch (`tests/test_local_exec.py` deleted too, coverage of
  surviving behavior ported into `test_pipeline_verbs.py`/
  `test_prodtools_exec.py`), one new ~40-line verb (`jobwait`) added to
  prodtools.
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
  `autoresearch_<cfg>_geom.txt` basename via the stage_entries `{geom}`
  placeholder (retired the old `__GEOM_FILE__` sentinel substitution when
  templates were retired — see the Job description section above).
- **Geom auto-staging:** `bo_driver.py propose <cfg>` copies the
  rendered proposal into `<work_root>/<cfg>/geom/` so `pipeline.py --config
  <cfg>` runs without manual prep.
- **Harvest output:** `summary.json` with `s_over_sqrt_b`, `calo_per_pot`,
  and a `config` field naming the CFG.
- **`cmd_harvest` delegates Steps 1+4 to `harvest.py` runner seams
  (2026-07-19, commit 1809635 — friction-survey candidate 5's harvest
  phase-2 slice, `graph/closed_loop.py`'s ChildTracker full-cut was
  candidate 2's).** Step 1 (EdepAna over CeEndpoint outputs) and Step 4
  (`rough_run1a_sensitivity.C` → `s_over_sqrt_b`) now call
  `hv.run_edepana(...)` / `hv.run_sensitivity_macro(...)`, each taking an
  injected `runner(cmd, cwd)` — `pipeline.py` still owns env/
  `FHICL_FILE_PATH` binding via a local closure (`_mu2e_runner`/
  `_root_runner`) so `harvest.py` stays stdlib-only and testable with
  fakes. `EDEP_FCL`/`SENSITIVITY_MACRO` path constants moved to
  `harvest.py` with their consumers. Hard-fail (`SystemExit`) semantics on
  rc≠0 or unparseable output preserved exactly. Golden re-harvest of
  `foilsflash13R00_02` verified all `summary.json` keys bit-identical
  before/after. **`cmd_harvest` is NOT fully subprocess-free**: Step 2
  (per-file event counting via `_count_events_art`, `pipeline.py:1115`,
  called at `:1277`) is still an inline `subprocess.run` — out of this
  round's scope. See
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md).
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
- Consumed by: [bo-driver](/drivers/bo-driver.md) `evaluate`, [graph-runner](/drivers/graph-runner.md) (per-stage nodes)
- Grid-free path: `submit --local` runs the same stage in-process via
  prodtools `runlocal` — `cmd_submit` dispatches on `--local`/`AUTORESEARCH_LOCAL`;
  see [local-executor](/drivers/local-executor.md) (superseded page, historical
  detail on the pre-prodtools-switch executor this replaced)
- Geom rendered by: [bo-driver](/drivers/bo-driver.md) `propose` (auto-stages into work tree)
- Regression tests: [tests](/drivers/tests.md) (pins the `_check_stage_config_sha` contract)
- Related: [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md) (candidate 5, harvest unification)
- See: [grid-job-completion-check](/incidents/grid-job-completion-check.md) for monitoring conventions
- History: [template-fcl-staleness](/incidents/template-fcl-staleness.md) (the bug the parametric refactor closed); the 2026-08-16 prodtools switch is documented in `docs/superpowers/specs/2026-08-16-prodtools-switch-design.md` (design) and `.superpowers/sdd/2026-08-16-prodtools-switch/progress.md` (task-by-task ledger)

## Open questions / TODO
- Eventually delete the legacy `smoke_*/` trees under
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/` once the parametric path
  has been the only one driven for a few iterations.
- `docs/prodtools/EXAMPLES.md` (or wherever the prodtools examples doc lives)
  needs a refresh for the new `jobwait` verb — never hand-edit it, regenerate
  it.
