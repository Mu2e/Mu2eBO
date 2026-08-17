---
type: driver
title: local executor — the grid-free path
description: '(**SUPERSEDED 2026-08-16** by the prodtools switch: `core/local_exec.py` deleted, `submit --local` now shells prodtools `runlocal`) `AUTORESEARCH_LOCAL=1`/`--local` still activate a grid-free run (no jobsub, but NOT offline: resampler inputs stream from /pnfs over xrootd, and `AUTORESEARCH_PRODTOOLS` is now required even locally); `$AUTORESEARCH_DATA_ROOT` is the sandbox seam that keeps toy rows off the live board; ~33 s/stage at 1×200 events under prodtools runlocal (was ~20 s pre-switch), and a flash mode cannot land a row at that scale by design'
status: superseded
status_note: 'superseded 2026-08-16 by the prodtools switch: core/local_exec.py deleted, execution moved to prodtools runlocal via pipeline.py submit --local'
timestamp: '2026-08-16'
updated_note: 'SUPERSEDED (prodtools-switch Task 12): core/local_exec.py, the local-build/local-run verbs, cmd_local_build/cmd_local_run were all deleted 2026-08-16 (Task 9). AUTORESEARCH_LOCAL=1 / --local still activate a grid-free run, but pipeline.py submit --local now shells prodtools runlocal (core/prodtools_exec.py:run_runlocal) instead of running the machinery this page describes. See wiki/drivers/pipeline.md, "Execution: submit/poll shell prodtools" for the current mechanism. This page is kept for its still-true operational facts (activation-vs-detection rule, AUTORESEARCH_LOCAL_* scale knobs, flash-mode zero-row math, backing requirement) that were NOT rewritten by the switch, but any fact naming core/local_exec.py, cmd_local_run, or local-build/local-run as live code is now historical.'
---

# local executor — the grid-free path (SUPERSEDED)

## Summary
**Superseded 2026-08-16 by the prodtools switch.** `core/local_exec.py` and
the `local-build`/`local-run` verbs described on this page were deleted; the
current grid-free path is `pipeline.py --config CFG submit <stage> --local`
(or the `AUTORESEARCH_LOCAL=1` env activation, unchanged), which now shells
prodtools' own `runlocal` binary (via `core/prodtools_exec.py:run_runlocal`)
instead of the machinery below. See
[pipeline](/drivers/pipeline.md#execution-submitpoll-shell-prodtools-env-autoresearch_prodtools)
for the current mechanism, state files (`<stage>_wait.json` replaces the
by-hand FCL files this page describes), and the `AUTORESEARCH_PRODTOOLS`
requirement (also needed for a *local* run now, since `runlocal` is a
prodtools binary). The operational facts below this notice — the
activation-vs-detection rule, the `AUTORESEARCH_LOCAL_*` scale knobs, the
flash-mode zero-row math, the backing requirement — are unchanged and still
true; only the *how it executes* paragraph is obsolete.

`AUTORESEARCH_LOCAL=1` makes the ordinary entrypoint run every stage as a
local `mu2e` process instead of a grid job — no `jobsub`, no job queue. It is
NOT offline: the built FCLs point `beamResampler.fileNames` at
`xroot://fndcadoor.fnal.gov//pnfs/...` (MuBeamCat, EleBeamCat), so a local job
streams its inputs over xrootd and needs a live bearer token exactly as a grid
worker does. It is an ACTIVATION switch read once, in `cmd_submit`
(`core/pipeline.py`); `graph/pipeline_io.py` shells out without `env=`, so a
graph child inherits it and needs no flag of its own. The same command a
grid campaign uses therefore works unchanged:

```
AUTORESEARCH_LOCAL=1 python -m graph.run --mode <m> --config-name <c> \
    --thread-id <c> --no-mock
```

## Key facts
- **Activation ≠ detection.** `_is_local_stage` keys on the
  `state/<stage>_local.txt` marker ONLY, never the env var. An env disjunct
  would make a poll of a live grid cluster silently no-op whenever the
  variable happened to be exported.
- **HISTORICAL (pre-2026-08-16):** the output tree used to mirror the /pnfs
  outstage at `$DATA_ROOT/autoresearch_local/<config>/<runid>/00/<index:05d>/`,
  written by `core/local_exec.py`. **Post prodtools switch**, a local run's
  per-job output dir lives under `<DATA_ROOT>/autoresearch_grid/<cfg>/<stage>/local/`
  (prodtools `runlocal`'s own `--workdir`, per-job subdir naming owned by
  prodtools) and `harvest`/`list-outputs` locate files via the executor-blind
  `state/<stage>_wait.json` contract (each job's `dir` + `outputs[...]`)
  rather than by walking a known directory layout at all — see
  [pipeline](/drivers/pipeline.md).
- **`$AUTORESEARCH_DATA_ROOT` is the sandbox seam.** Everything the runner
  writes derives from it — grid tree, logs, AND this operator's live
  leaderboard (`core/paths.py:72-74`) — while the committed archive is always
  read from the repo (`core/leaderboard.py:183`, archive-wins). Pointing
  DATA_ROOT at a scratch dir is therefore the whole answer to "where does a
  200-event plumbing row go": nowhere that trains a real GP. The
  `leaderboard_local_<mode>.tsv` requirement in
  `docs/superpowers/specs/2026-08-12-local-executor-design.md` was never
  implemented and is superseded by this — one existing switch instead of new
  routing logic.
- **Default scale is 1 job x 200 events per stage** — a plumbing check, not a
  measurement. Raise via `AUTORESEARCH_LOCAL_{NJOBS,EVENTS,POOL}` (the env
  seam exists because a graph child cannot be passed `--local-*` flags). The
  env vars take a bare int only; per-stage `<stage>=<int>` works solely on
  `submit --local`'s `--local-njobs`/`--local-events` flags (the
  `pipeline.py local-build/local-run` flags this originally referred to were
  deleted 2026-08-16), so a graph run scales every stage together.
- **MEASURED 2026-08-12** (fresh clone, config local01, foilspf, 1 x 200
  events), under the now-deleted `core/local_exec.py`: ~20 s per stage —
  mubeam 20 s, elebeam_flash 22 s, mustops_ce 23 s — then a full
  `harvest/summary.json` with `s_over_sqrt_b=4.38`, `ce_seen=118`,
  `muminus_stops=17`.
- **RE-MEASURED 2026-08-17 under prodtools `runlocal`** (ptlocal02, same mode
  and scale): ~33 s per stage — mubeam 33 s, elebeam_flash 33 s, mustops_ce
  32 s. The switch added **~+10 s of fixed per-JOB startup** (code-tarball
  unpack to `<stage>/local/code/Code` + `muse setup` inside each job's
  `bash -c`), which is +50% at 1x200 but only +2-4% at the 12500-events/job
  production scale, where per-event cost dominates. Startup is per JOB, not
  per stage, so it is also the reason a stage's wall clock sits ~12 s above
  its slowest job rather than scaling with the pool.
- **A default-scale run on a flash mode cannot land a row, by design.** Flash
  energy is deposited by ~2.4e-3 of input events (measured across
  foilspfbpz07: 18-26k edep events per 8-11M input), so 200 events expects
  0.48 and yields zero ~62% of the time. `evaluate` then refuses the append
  ("a zero/negative second metric would dominate the Pareto front at the next
  GP refit") and writes `scan_logs/evaluate_zero_row.tsv`. Roughly 1e5 total
  events (NJOBS x EVENTS) buys ~240 flash events, ~6% statistical error.
- **DELETED 2026-08-16: `local-build` / `local-run`, the by-hand FCL seam.**
  These verbs (`local-build` rendered one FCL per job index to
  `state/fcl/<stage>_<index>.fcl` with a SHA-256, so a later `local-run`
  named any file the operator edited) are gone along with
  `core/local_exec.py`. To inspect the FCL a stage will run now, read
  `state/<stage>_entry.json` (the json2jobdef entry) or run
  `submit <stage> --local --dry-run` to build the cnf without executing it —
  see [pipeline](/drivers/pipeline.md).
- **One guard survives the switch**: a config whose `state/<stage>_cluster.txt`
  holds a real grid cluster id is refused by `_require_local_stage` (the
  `--local` branch overwrites that file and the events-per-job stamp harvest
  divides by). `sourced_env()`'s refusal of a shell that already has
  `MUSE_WORK_DIR` set (because `museSetup.sh:13` rejects a second setup and
  all four retries would burn ~50 s on an unfixable condition) also survives
  unchanged.
- **VERIFIED backing-only (2026-08-12, config gu01)**: with `ARTIFACT_ROOT`
  pointed at an EMPTY directory and artifacts reachable only through the
  `backing` symlink, the whole chain ran — propose, geom render, preflight,
  all three stages, and harvest (`s_over_sqrt_b=4.32`, `degraded: {}`). That
  is the general-user configuration: nothing silently resolved to the
  operator's own root. What a general Mu2e user still needs is a Kerberos
  ticket, their own DATA_ROOT, and read access to an operator's artifact
  directory — no build, no grid quota, no jobsub.
- **The backing is the bootstrap limit.** No recipe in this repo builds the
  patched Offline or the `Code_*.tar.bz2` tarballs, so an outside user cannot
  start without an operator's directory staying readable. That, not the code,
  is what stands between "works for a general user" and "self-service".
- **A fresh clone needs a backing for harvest, not just for the grid.**
  Run1BAna's FCL and sensitivity macro resolve through `artifact()` and are
  gated at preflight by `paths.verify(extra=...)` — see
  [preflight](/drivers/preflight.md). Before that fix the miss surfaced hours
  later, inside harvest.
- **NEW as of the prodtools switch: `AUTORESEARCH_PRODTOOLS` is required for
  a LOCAL run too.** `submit --local` shells prodtools' `runlocal` binary
  (`core/prodtools_exec.py:run_runlocal`), the same `AUTORESEARCH_PRODTOOLS`-
  resolved checkout the grid path uses (`core/paths.py:prodtools_root()`).
  This was not a requirement of the old `core/local_exec.py` executor —
  running grid-free no longer means running prodtools-free.

## Cross-links
- Related: [pipeline](/drivers/pipeline.md) (current mechanism — read this
  page for facts about `AUTORESEARCH_LOCAL`/backing/flash-mode math that
  weren't superseded), [preflight](/drivers/preflight.md),
  [graph-runner](/drivers/graph-runner.md)
- Source files (current): `core/pipeline.py` (`cmd_submit`'s `--local`
  branch, `_require_local_stage`, `sourced_env`), `core/prodtools_exec.py`
  (`run_runlocal`), `core/paths.py` (`prodtools_root`)
- Source files (DELETED 2026-08-16, historical only): `core/local_exec.py`
- Spec: `docs/superpowers/specs/2026-08-12-local-executor-design.md`
  (superseded in turn by
  `docs/superpowers/specs/2026-08-16-prodtools-switch-design.md`, which
  explicitly extends/replaces it: "local execution becomes `runlocal`")
- README: "Running without the grid" — the from-scratch recipe

## Open questions / TODO
- The 2026-08-12 spec still describes a mubeam-only executor and still
  carries the superseded `leaderboard_local_<mode>.tsv` requirement; moot
  now that the spec itself is superseded by the prodtools-switch design doc,
  but nobody has gone back to mark the older spec file itself superseded.
