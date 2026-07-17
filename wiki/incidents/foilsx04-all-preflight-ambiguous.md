---
type: incident
title: foilsX04 — silent total failure with spurious convergence
description: foilsX04 ran 20 children across 2 rounds, all died at preflight=ambiguous
  (rc=3), parent reported converged=True with zero leaderboard rows
status: resolved
status_note: 2026-05-29 (convergence-by-pareto-hash machinery deleted entirely;
  zero-row safety break in `node_decide_next`; rc=3 ambiguous now retriable in `route_after_preflight`)
timestamp: '2026-06-05'
updated_note: 'FIX BAKED IN + VERIFIED UNDER CONCURRENCY: `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER`
  prepended INSIDE the bash command at `autoresearch_bo_michael.py:1188` (cmd_preflight)
  + `pipeline.py:289` (sourced_env). Single-config verify: foilsZ05R00_00 re-preflight
  rc=0, no Errno 5. **q=10 concurrent verify (foilsZ06 R00): ALL 10 preflights PASS,
  0 ambiguous** — compare foilsZ05 pre-fix (26 ambiguous, 0 pass). Incident class
  retired.'
---

# foilsX04 — silent total failure with spurious convergence

## ACTUAL ROOT CAUSE — STALE SPACK LOCK, *NOT* CVMFS (2026-06-05, definitive)

**The `[Errno 5] Input/output error` during `spack load` is NFS-flock contention
on the spack cache lock in NFS HOME, not a cvmfs outage.** The whole "cvmfs flake
/ partial I/O fault / needs admin" framing below (2026-06-01..04) was WRONG.
mmackenz pointed at the spack lock; the full mechanism + permanent fix:

- **Mechanism = concurrent `spack load` racing flock over NFS.** A SINGLE cold
  setup works (5/5 OK); but **5–8 CONCURRENT setups all FAIL** and the lock
  `~/.spack/cache/providers/.fnal_art-index.json.lock` self-corrupts. So q=10
  closed-loop preflights (each runs `spack load muse/git`) race it → all
  ambiguous. Explains the whole history: q=3 (foilsZ02) mostly survived; q=10
  (foilsZ03/Z04) died. The monotonic R00-ok→R01→R02-dead pattern = the lock
  degrading once the first overlap corrupts it.
- **PARTIAL fix (single-process only): `rm -f
  ~/.spack/cache/providers/.fnal_art-index.json.lock`.** Cures one cold setup,
  but **q>1 preflights immediately re-race and re-break it** — foilsZ04 (q=10)
  died this way *after* the rm. Not sufficient for the closed-loop.
- **PERMANENT fix (verified 8/8 concurrent OK): put the spack cache on LOCAL
  disk** so the locks leave flaky NFS:
  ```
  export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER   # locks -> /tmp (local), not nashome
  ```
  Launch the closed-loop with this exported (children inherit it). foilsZ05
  (q=10×5) relaunched with it 2026-06-05. **TODO: bake `SPACK_USER_CACHE_PATH`
  into the closed-loop launch / `pipeline.sourced_env` so every preflight gets
  it** — that retires this entire incident class. (NB `/tmp` is node-local, fine
  for the local preflights; grid workers set up their own env.)
- **NEGATIVE RESULT — export-at-launch is NOT sufficient (foilsZ05, 2026-06-05):**
  launched the q=10×5 parent with `SPACK_USER_CACHE_PATH=/tmp/spack_cache_oksuzian`
  exported in the launching shell; R00 still produced **26 `preflight=ambiguous`
  verdicts** with the same `[Errno 5]` in `bo_foils_preflight/foilsZ05R00_*.log`.
  Tell that the env var DID move the parent's locks (the nashome
  `.fnal_art-index.json.lock` was NOT recreated), but the **preflight subprocess
  re-sources its env in a way that drops the inherited var** (one of:
  `cmd_preflight`'s `subprocess.run(..., env=...)` filtering, the `bash -lc`
  setup script clobbering, or env-i style scrubbing in `graph/sourced_bash.py`).
  **So the fix MUST be in the code path that sets up the preflight env** —
  exporting at the launching shell is a false fix. Concretely: add
  `SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` inside `cmd_preflight`
  (`autoresearch_bo_michael.py:cmd_preflight`) or in `graph/sourced_bash.py`'s
  `run_sourced_bash` BEFORE the `spack load` runs, AND verify it survives by
  reading `bo_foils_preflight/<cfg>.log` (env dump or `printenv | grep SPACK`).

- **Evidence:** after deleting that single 0-byte lock file, the cold probe
  (`env -i HOME=$HOME bash -lc 'source setupmu2e-art.sh; command -v muse'`) went
  from **0/many FAIL → 5/5 OK** instantly, on the same node, with no cvmfs/admin
  action. The lock was 0 bytes, dated Jul 2025, `lsof`/`fuser` showed **no
  holder** (stale). `~/.spack/cache/` is fully regenerable ("nothing here should
  be required") — can `rm` the whole dir if the single lock doesn't do it.
- **Why the cvmfs red herring held so long:** spack reads/locks its provider
  index under `~/.spack/cache/` (NFS home); a stale/bad lock there throws `EIO`
  (Errno 5) which *looks* like a cvmfs read error and is even printed by
  `setupmu2e-art.sh`'s spack helper. The **tell that it's spack-local, not
  cvmfs:** `Musings/` + `DataFiles/` (real cvmfs) read FINE while only
  `spack load muse/git` fails. Whenever you see that pattern → it's the spack
  lock, NOT cvmfs. Check `lsof <lock>` for a live holder first (none = stale,
  safe to delete).
- **Reframes all prior instances:** foilsX04, foilsY02 r0, foilsZ03 R01–R02
  preflight=ambiguous "cvmfs flakes" were almost certainly THIS stale spack lock
  — a 1-second fix, not an outage. The retry-with-backoff / zero-row-gate /
  "wait for cvmfs admins" responses all treated a symptom.
- **TODO (robustness):** `cmd_preflight` could auto-`rm` a stale provider lock
  (verify no holder) before sourcing, to self-heal this class entirely.

## RECURRENCE + EXACT CAUSE CAPTURED (2026-06-04, foilsZ03) — see correction above

`foilsZ03` (qLogNEHVI, q=10×5) died the same way: **R00 all 10 children PASS,
R01 → 2 rows, R02 → 0 rows (all preflight=ambiguous), zero-row gate exits early**
(monotonic degradation = an env outage that worsened mid-run, NOT bad picks —
qLogNEHVI even found `sob=3.82` in R00).

- **The "swallowed" cause is NOT lost — it's in `bo_foils_preflight/<config>.log`
  STDERR (load-bearing diagnostic pointer).** The child log + parent only show
  `preflight=ambiguous`, but the per-config preflight log's `--- STDERR ---`
  section had the real error:
  ```
  ==> Error: [Errno 5] Input/output error
  /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh: line 47: /bin/museDefine.sh: No such file or directory
  /cvmfs/.../Run1Bak/setup.sh: line 4: muse: command not found
  ```
  So **to diagnose any preflight=ambiguous, read `bo_foils_preflight/<config>.log`
  FIRST** — no interactive re-run needed (resolves the old "needs re-run to read
  stderr" note). A FAILED preflight log is ~6 lines; a PASSED one is ~10k.
- **Exact cause this time = CVMFS partial I/O failure.** A cvmfs read inside
  `setupmu2e-art.sh`'s spack/python helper threw `[Errno 5] Input/output error`
  (the top-level cvmfs dir still `ls`'d fine — partial cache/backend fault),
  which left a path var empty so `${MUSE}/bin/museDefine.sh` **collapsed to the
  literal `/bin/museDefine.sh`** → `No such file` → `muse: command not found` →
  `mu2e -n 1` never ran → ambiguous. **DON'T chase `museDefine.sh`** — it's a
  *downstream* path-expansion symptom, not the broken file (probing
  `/cvmfs/.../bin/museDefine.sh` directly is a red herring; that path doesn't
  even exist normally). The upstream `[Errno 5]` is the fault. NOT our code,
  q=10, or qLogNEHVI. **Persisted for hours**, **flapping** (the error alternated
  `Errno 5` ↔ `ENOENT` between probes).
- **Canonical one-liner reproducer (node-local, hand to cvmfs admins):**
  ```
  source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh; command -v muse
  ```
  → emits the `[Errno 5]` + `muse -> MISSING` when broken. Full-pipeline repro:
  `.venv-graph/bin/python autoresearch_bo_michael.py --mode foilsf preflight <cfg>`.
  User-space can't fix cvmfs (admin-managed `cvmfs_config wipecache`/remount);
  wait for recovery, try a different interactive node, or file a ticket.
- **The fault is ISOLATED to `spack load`, not broad cvmfs (2026-06-04).**
  `bash -lxc` trace pins the `[Errno 5]` to `spack load --sh muse/<hash>` and
  `spack load --sh git/<hash>` inside `setupmu2e-art.sh`; cold-read breadth test:
  `setupmu2e-art.sh` OK, **`/cvmfs/.../bin/muse` FAIL**, but **`Musings/` +
  `DataFiles/` OK** — i.e. the spack package tree (+ the muse launcher) is the
  broken region, while the geometry/config files `mu2e -n 1` actually reads are
  healthy. **Workaround: launch the closed-loop FROM A WARM SHELL** (muse already
  `spack load`-ed) so preflight subprocesses inherit the loaded env and skip the
  broken `spack load` — the rest of the run reads only the healthy tree. Validate
  first with one preflight from the warm shell
  (`autoresearch_bo_michael.py --mode foilsf preflight <cfg>` → expect
  `preflight=ok`); if ok, the campaign can run during the outage without waiting
  for cvmfs/admins. (Whether it works hinges on the preflight subprocess
  inheriting vs scrubbing the parent env — test, don't assume.)
- **RECOVERY-CHECK GOTCHA: a warm shell's `muse` is a FALSE-POSITIVE
  (2026-06-04).** Checking `command -v muse` in your *existing* interactive
  shell returns `muse` even while cvmfs is broken — because muse is already in
  PATH from an earlier successful setup today (warm). But **preflights run in
  fresh COLD subshells** (`bash -lc 'source setupmu2e-art.sh …'`), which redo the
  full cvmfs read and still die. Observed: same node (`mu2esrv01`), warm shell
  `muse` OK but **5/5 cold-subshell probes FAIL**. So the ONLY valid
  "recovered?" test is the **cold** probe:
  ```
  bash -lc 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1; command -v muse >/dev/null && echo OK || echo FAIL'
  ```
  Re-launch only when that prints `OK` consistently — never trust a warm-shell
  `muse` as the green light.
  - **DEEPER (2026-06-04): even a `bash -lc` cold probe is masked by ENV
    INHERITANCE.** `bash -lc` inherits the parent shell's *exported* env, so a
    warm interactive shell's `MUSE*/SPACK*` vars carry into the child and
    short-circuit `setupmu2e-art.sh` past the broken cvmfs read → spurious `OK`.
    Observed: user's `bash -lc` probe = OK, but the Claude Bash tool (a genuinely
    clean env — `env | grep -i muse` empty, like the detached closed-loop) =
    **9/9 FAIL** with the real `[Errno 5]`, even sandbox-disabled. The
    **truly-cold** test that represents a fresh preflight scrubs the env:
    ```
    env -i HOME="$HOME" USER="$USER" TERM=xterm bash -lc 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1; command -v muse >/dev/null && echo OK || echo FAIL'
    ```
    Closed-loop preflights run from a clean (no-muse-var) env, so the scrubbed
    `env -i` probe — not a `bash -lc` from your working shell — is the valid
    recovery gate. (Also the cleanest admin reproducer: Errno 5 from a pristine
    env.)
- **The banner-gated retry (3× / 5,15,30s ≈ 50 s window) is too SHORT for a
  multi-minute/multi-round cvmfs outage** — it rides out sub-minute flakes but
  not this. The zero-row gate worked as designed (caught the all-fail round,
  exited clean) but can't save a campaign from a persistent external outage. A
  user can't fix cvmfs (admin-managed); wait for recovery or file a ticket.

## ROOT CAUSE OF BUG #1 IDENTIFIED (2026-06-01)
The "unknown" cause of the uniform rc=3 preflight failures is the **same
transient cvmfs/spack env-source flake** documented in
[sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md), hitting `cmd_preflight`'s OWN env-source
(`autoresearch_bo_michael.py:1039`, separate from `pipeline.py:sourced_env`).
When the flake hits, `mu2e` never runs → empty output → nonzero rc →
rc-map reads it as **rc=3 ambiguous**. The preflight log is just the 16-byte
template. X03 passed because it ran outside a bad cvmfs window; X04 (and
foilsY02 round 0 on 2026-06-01) ran inside one. Reproduced + fixed via
foilsY02: a manual re-run of the "failed" geoms passes rc=0; the fix adds
retry-with-backoff gated on "mu2e never emitted a banner"
(`autoresearch_bo_michael.py:1047`). The earlier note ("needs interactive
re-run to read the surface-check stderr") is now done — there was no
surface-check stderr because surface-check never ran.

## Summary
Closed-loop parent `foilsX04` (q=10, max-rounds=10) launched 2026-05-29,
spawned 20 children across rounds 0+1, every child's graph terminated at
the **preflight node** with status `ambiguous`, and the parent reported
`converged=True` after k=2 identical pareto-hashes — producing **zero
new leaderboard rows** while looking superficially successful.

Two distinct bugs collided to produce the silent failure:

1. **Whatever made X04 picks uniformly fail preflight with rc=3** —
   currently unknown; needs interactive re-run of
   `.venv-graph/bin/python autoresearch_bo_michael.py --mode foils preflight foilsX04R00_00`
   to read the surface-check stderr. X03 picks PASSed cleanly under the
   same code; only X04 is affected.
2. **Convergence check has no "new evals this round" floor** —
   identical pareto-hashes across rounds resolve `converged=True` even
   when 100% of children failed and the leaderboard didn't grow.

## Key facts

- **Symptoms (parent log `graph_data/closed_loop_logs/closed_foilsX04_r0.log`):**
  ```
  round 0: launched 10 children, barrier resolved, pareto_hash=6459d20d... converged=False
  round 1: launched 10 children, barrier resolved, pareto_hash=6459d20d... converged=True
  done. final keys: [...]  ← parent exits cleanly
  ```
  No errors, no traceback, no warning in the parent log.

- **Per-child evidence (`foilsX04R00_00.log` is representative of all 20):**
  ```
  [run] {"config_name": "foilsX04R00_00", "preflight": "pending", "objective": null}
  [run] {"config_name": "foilsX04R00_00", "preflight": "ambiguous", "objective": null}
  [run] done. final keys: [...]
  ```
  The graph terminates immediately after preflight returns "ambiguous";
  no submit, no harvest, no scan_logs, no evaluate.

- **Grid-work-dir forensics** (`autoresearch_grid/foilsX04R00_00/`):
  - `geom/autoresearch_foilsX04R00_00_geom.txt` — present (proposal
    rendered)
  - `state/` — empty (no `*_cluster.txt`, no `*_outputs.txt`)
  - No grid jobs were ever submitted.

- **Leaderboard delta**: 0 new rows. `wc -l leaderboard_bo_foils_v1.tsv`
  unchanged at 74 (73 data) — same as end of X03.

- **Status mapping (load-bearing, `graph/pipeline_io.py:140`):**
  `{0: "pass", 1: "fail_managed", 2: "fail_init", 3: "ambiguous"}` —
  `ambiguous` corresponds to `cmd_preflight` rc=3, which the driver
  raises on **unhandled surface-check errors** (not managed-overlap,
  not G4 init failure). Means surface-check started but blew up
  before classifying.

- **Why convergence fired falsely**: `node_refit_and_check` computes
  `pareto_hash` from the LEADERBOARD, not the round's new evals. When
  no new rows land, the hash is identical to the prior round's by
  construction. Two identical hashes → k=2 repeat → converged. Same
  failure mode as [barrier-false-positive-round1](/incidents/barrier-false-positive-round1.md) but driven by
  all-children-fail rather than saver miss. **Fix shape: gate
  convergence on `len(history_after) > len(history_before)` for
  the round before counting toward k.**

- **Comparison with X03 (which worked):** X03 closed cleanly with
  50 evals across 5 rounds (leaderboard at 73 data rows). Same code
  tree, same FoilsMode class. The only environmental difference noted
  in `wiki/log.md` between X03 close and X04 launch is the
  `useTwistedBox` dispatcher work (tasks #134-136 in TaskList) —
  candidate root cause but not yet confirmed. Tasks #149 + #137
  ("Submit 3 A/B pairs tess vs twist", "Preflight both branches
  locally") are both in_progress/pending.

## Cross-links
- Related: [rolling-no-row-streak-false-increment](/incidents/rolling-no-row-streak-false-increment.md) (the rolling-era guard this shape motivated), [barrier-false-positive-round1](/incidents/barrier-false-positive-round1.md) (sibling failure mode —
  same "looks converged" symptom, different mechanism),
  [scan-broken-codes-too-narrow](/incidents/scan-broken-codes-too-narrow.md) (sibling silent-pass-broken
  pattern in scan_logs),
  [bo-foils](/projects/bo-foils.md) (the project line affected),
  [closed-loop-runner](/drivers/closed-loop-runner.md) (where the convergence-on-no-new-evals fix
  belongs), [preflight-fcl-genparticle-missing](/incidents/preflight-fcl-genparticle-missing.md), [preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)
- Source files:
  - `graph/pipeline_io.py:140` — `{3: "ambiguous"}` rc mapping
  - `graph/closed_loop.py` — convergence-check site (needs gate)
  - `autoresearch_bo_michael.py:cmd_preflight` — rc=3 emission
  - `graph_data/closed_loop_logs/closed_foilsX04_r0.log`,
    `foilsX04R00_00.log..R01_09.log` — evidence

## 3-agent debug findings (2026-05-29)

Three parallel agents investigated; the picture diverges from the
initial single-bug hypothesis:

### Finding 1 — convergence-gate bug **CONFIRMED**
- Reproduced at `graph/closed_loop.py:424-439` in `node_refit_and_check`:
  hash is derived from GP picks (re-tellable from leaderboard), so
  identical leaderboards → identical hashes → k=2 → `converged=True`
  even when zero rows landed.
- Patch shape (~25 LOC): snapshot `len(bo.MODES[mode].load_history())`
  in `node_barrier`, skip the hash append entirely when
  `new_rows == 0`. Fail-fast or warn-and-continue is a follow-up call.
- **`tests/test_closed_loop.py` has ZERO coverage of
  `node_refit_and_check`** — that's the gap that let this ship.
  Regression test must instantiate the node with a frozen leaderboard
  + two round invocations and assert `converged=False`.

### Finding 2 — rc=3 "ambiguous" is **NOT a code regression**
- Agent reran `cmd_preflight` on three X04 configs interactively
  (`foilsX04R00_00`, `R00_05`, `R01_03`): all **PASS rc=0**. Geom
  files clean; no `useTwistedBox` / helical / TSdA leak into FoilsMode
  emission (FoilsMode emits `hasTSdA = false`).
- rc=3 emission conditions at `autoresearch_bo_michael.py:1067-1069`:
  subprocess rc≠0 AND `past_init=False` AND no `G4_GEOM_FAIL_RX`
  match AND no managed_hits AND no timeout. Anything that kills
  `mu2e -n 1` early and silently (OOM, host load, transient
  filesystem) lands here.
- **Working hypothesis**: 10 concurrent local `mu2e` preflights from
  one closed-loop round competed for cores/RAM on the parent host;
  some got OOM-killed before G4 init produced a regex-matchable
  signature. Reproducer: launch 10 simultaneous preflights from one
  shell and watch resident memory.
- Proposed mitigation at `graph/nodes.py:68`: treat `ambiguous` like
  `fail_managed` (route back to propose with attempt-cap), instead of
  terminal. Decouples the env-induced fail from the convergence path.

### Finding 3 — relaunch artifact reframes the symptom
- Parent log mtime `closed_foilsX04_r0.log` = 09:01; all 20 child
  logs `foilsX04R00_*/R01_*.log` mtime range 07:37–08:56. The
  visible parent log is a **relaunch** that reaped pre-existing
  checkpoint state and instantly reported `barrier: all resolved`.
  Same family as [barrier-false-positive-round1](/incidents/barrier-false-positive-round1.md) (saver returns
  stale state). NOT a fresh run from scratch.
- `Code_helical_base.tar.bz2` mtime 2026-05-26 — predates X03 by
  three days. The `useTwistedBox` dispatcher work (TaskList #134-136)
  was completed in source but **never built/repackaged/shipped to
  grid**. Preflight doesn't load the helical lib anyway. The
  "X04 raced useTwistedBox" hypothesis in the original write-up is
  **REJECTED**.

## Patch design (post agentic review 2026-05-29)

Load-bearing facts for whoever applies these:

- **Infinite-loop risk of convergence-gate patch = NONE.**
  `route_after_decide` at `graph/closed_loop.py:454` hard-exits when
  `round_idx >= max_rounds`. Even if every round produces zero rows
  under the patched logic, the loop terminates at `--max-rounds` with
  `converged=False`. No new bound needed.
- **Best snapshot site is `node_predict_picks`** (not `node_barrier`).
  Barrier already owns sqlite+saver+polling — don't grow it. Add one
  RoundState key `history_len_before: int` set in predict_picks,
  compared in `node_refit_and_check`. (Doing it in barrier is
  acceptable but couples two concerns.)
- **`MAX_PROPOSE_RETRIES = 3`** at `graph/config.py:40` already
  bounds the blast radius of the rc=3-retriable change. Counter
  incremented in `node_propose:52`, reset to `{}` in
  `node_decide_next:188`. Per-iteration cap → worst case 3 propose
  attempts per BO iter. No separate `MAX_AMBIGUOUS_RETRIES` needed.
- **rc=3 currently routes terminal** (`graph/nodes.py:200-208`): only
  `pass` and `fail_managed` are non-terminal; `ambiguous`,
  `fail_init`, `pending` all fall to END. Docstring at
  `node_render_preflight:61` explicitly says "init failure or
  ambiguous → terminal error" — that comment also needs updating.
- **rc=3 stderr is captured but truncated to one line.**
  `cmd_preflight` already dumps last 40 lines of `mu2e` stderr to
  disk (`autoresearch_bo_michael.py:1068`); `nodes.py:69` currently
  only pipes `.splitlines()[-1]` into state errors. Patch 2 must
  also widen this — without it, repeated retries accumulate
  identical opaque "preflight[ambiguous] foo: ..." lines.
- **Stochastic retry is safe**: BO sampling means each propose
  retry draws a *different* `x`, so a true geom bug in one config
  doesn't infinite-loop on the same config.
- **Only foilsX04 has rc=3** in `wiki/incidents/` — grep
  `incidents/` for `ambiguous` / `rc=3` returns this file only
  (plus log.md backrefs). No prior incident would have been masked
  by retrying rc=3.

## Resolution applied 2026-05-29

Both findings addressed in `graph/closed_loop.py` + `graph/nodes.py`
(see [closed-loop-runner](/drivers/closed-loop-runner.md) "Convergence" section for design rationale):

1. **Convergence-by-pareto-hash deleted** rather than gated. 15-run
   production audit showed 0 true saves; mechanism wasn't earning
   its keep. `_pareto_hash`, `node_refit_and_check`, `pareto_hashes`/
   `converged`/`convergence_k` state keys, and the `--convergence-k`
   CLI arg all removed. Graph rewired `barrier → decide_next`
   directly. Saturation is now diagnosed post-hoc from the leaderboard
   (Pareto-front movement plots).
2. **Zero-row safety break** added in `node_decide_next`:
   `history_len_before` snapshot in `node_predict_picks`, compared
   in `node_decide_next`; if `new_rows <= 0` set `zero_rows=True`
   and `route_after_decide` ENDs. Catches "all children failed"
   round generically, not just the spurious-convergence symptom.
3. **rc=3 ambiguous now retriable** at `graph/nodes.py:route_after_preflight`
   — same MAX_PROPOSE_RETRIES=3 cap as `fail_managed`. Each propose
   retry draws a different `x` from skopt, so a true geom bug doesn't
   infinite-loop. Stderr capture widened from `splitlines()[-1]` to
   last 8 lines so repeated retries accumulate useful context.

Regression coverage in `tests/test_closed_loop.py`:
`TestDecideNext.test_zero_new_rows_sets_zero_rows_true`,
`test_negative_delta_sets_zero_rows_true`,
`TestRouteAfterDecide.test_zero_rows_ends`,
`TestBuildGraph.test_refit_and_check_removed`.

## Open questions / TODO
- **Add a concurrent-preflight-stress test** that launches N=10
  preflights from a single closed-loop round on the parent host and
  measures peak RSS. If reproduces rc=3, also gate closed_loop on a
  semaphore (`max-concurrent-preflights`) — but this is speculative
  until the OOM/load hypothesis is confirmed. The rc=3-retriable
  fix is a robustness layer, not a root-cause repair.
- **Decide leaderboard hygiene for X04**: 20 grid-work dirs with only
  `geom/` are wasted disk but harmless; safe to `rm -rf`.
