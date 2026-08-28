# Prodtools switch — autoresearch job execution via prodtools

**Date:** 2026-08-16
**Status:** draft — pending operator review
**Supersedes:** the local-executor line of `2026-08-12-local-executor-design.md`
(local execution becomes `runlocal`; this spec extends the switch to the grid
path and the completion seam).

## Goal

Autoresearch stops owning job execution. Building, running (local or grid),
and watching Mu2e jobs all go through prodtools
(`/exp/mu2e/app/users/oksuzian/muse_050125/prodtools`) — the same code that
runs production. Autoresearch keeps only what is genuinely its own: geometry
proposal, entry rendering, harvest/metrics, leaderboards, and the closed-loop
BO orchestration.

Net effect: ~800–900 lines deleted from autoresearch (plus their tests), one
new ~40-line verb added to prodtools (`jobwait`), and the env-divergence class
of incidents (local env ≠ grid tarball: `foilsflash-tarball-mode-key-omission`,
`prodtarget-env-divergence`) eliminated structurally — there is one job-prep
path, prodtools' `process_jobdef`, everywhere.

## Decisions (all settled 2026-08-16 with the operator)

1. **JSON entry everywhere.** The per-(config, stage) JSON entry
   (`json2jobdef` format) is the single source of truth for a job: `tarball`
   name, per-config `code` tarball, `njobs`, `fcl` + `fcl_overrides`, `inloc`,
   `outloc`. `pipeline.py`'s job knowledge shrinks to "render this dict."
   FCL changes ride `fcl_overrides` in the entry — never runtime FCL editing
   (a cnf rebuild costs 3.8 s, measured).
2. **Grid submission via prodtools `submit`** (direct `jobsub_submit`; the
   mu2ejobsub backend was retired from prodtools 2026-07-19). Our per-config
   `Code.<base>.tar.bz2` rides the entry's `code` key →
   `--tar_file_name dropbox://` (RCDS), same delivery as before.
3. **Completion via a new prodtools verb `jobwait`** — see below. Queue-side
   truth only; no filesystem access, no fallbacks, no internal timeout.
4. **Outputs stay out of SAM.** `outloc: outstage` →
   `$MU2EGRID_WFOUTSTAGE/<cluster>/<process>`, no declares. BO evaluations are
   ephemeral by the hundreds; SAM is a shared permanent catalog. (Named
   alternative, rejected: declaring to SAM would make
   `listNewDatasets --completeness` work verbatim — not worth the pollution.)
5. **One results contract.** `runlocal --json` (local) and `jobwait --json`
   (grid) write the same summary shape. It is the only thing autoresearch
   reads back, and the *permanent* record of per-job outcomes (condor history
   fades in days).

## jobwait — the one new prodtools piece

The grid twin of `runlocal`: "block until this cluster is finished, then
write down exactly how each job ended."

```
jobwait --jobdef cnf.tar --cluster <id>[@schedd] [--poll-s 300] --json out.json
```

1. Every ~5 min: `jobsub_q --user` snapshot → is the cluster still present?
   (reuses `submissions.live_clusters()` / `cluster_queue_state()` —
   fail-closed: a failed query is `error`, never `drained`).
2. Cluster gone: one `jobsub_history -J <cluster>@<schedd> -limit <njobs>
   -af ProcId ExitCode` call. `-limit` passes through to condor_history and
   stops the newest-first scan early: measured 8.4 s vs 51 s unlimited on a
   real 999-job prodtools cluster, and a just-drained cluster sits at the
   head of the history file, so expect seconds. Missing records (fewer than
   njobs found) degrade to the full scan and report as `unknown`.
   Exit 0 ⇒ ran fine AND outputs copied — in direct mode the copy is inside
   the job, so the exit code is the complete success record.
3. Write the JSON atomically (runlocal's writer): per-index
   `{index, rc, outputs[...]}` (paths are deterministic from the cnf; exit 0
   is the receipt they exist), `ok`, `failed[]`. Exit 0 iff every job
   exited 0 — a convenience summary only, same convention as runlocal, and
   the JSON is written regardless. Autoresearch never gates on the exit
   code: it reads the JSON and applies its own acceptance policy (partial
   completion at ~95% proceeds, harvest divides by the true `ok` count),
   exactly as today. Acceptance thresholds are caller policy and stay out
   of the tool for the same reason timeouts do.

Deliberate non-features (operator decisions):
- **No file checking.** Not as primary (dropped: dCache polling load; condor
  can re-run an evicted job even after its copy, so pre-drain files aren't
  final), not as fallback (dropped: no guessing). Empty/unreachable history →
  every job reported `rc: null` / status `unknown`, nonzero exit. Honest
  failure beats inferred success.
- **No internal timeout.** Held/stuck jobs → jobwait keeps waiting. Patience
  is the caller's policy: closed-loop has its barrier timeout; a shell has
  `timeout 24h jobwait …`.
- `jobsub_wait` is NOT used: verified 2026-08-16 to be a `condor_wait`
  wrapper needing a local condor log that jobsub_lite submissions don't
  leave on the submit node. There is no official blocking wait; queue-snapshot
  polling is the state of the art.

Safety net behind the exit-code trust: harvest physically opens every file
and already fails soft (degraded row) on unreadable input — a lying exit 0
cannot silently poison a leaderboard row.

## Architecture / data flow

```
propose (BO ask, unchanged)
  └─ pipeline.py renders entry.json per (config, stage)     [autoresearch]
       └─ json2jobdef  → cnf.tar                            [prodtools]
            ├─ LOCAL:  runlocal --json wait.json            [prodtools]
            └─ GRID:   submit → cluster id                  [prodtools]
                        └─ jobwait --json wait.json         [prodtools, NEW]
       └─ harvest reads wait.json: which indices succeeded  [autoresearch]
          (true denominator) + where the outputs are; physics
          extraction unchanged
```

Stage chaining: a downstream entry's `inloc` points at the upstream stage's
output location (`dir:` for local farms; outstage path for grid), exactly as
tested in the runlocal chain run (6/6 jobs, 3 stage shapes, 2026-08-12..13).

Closed-loop integration: `submit` already parses and returns the cluster id
(`_parse_cluster_id`, jobsub-lite-hardened); pipeline still records it in
`state/<stage>_cluster.txt` so the barrier, `_already_running()` guard, and
incident tooling keep their source of truth. The barrier's per-child
resolution reads the wait.json instead of `poll`/`list-outputs` output.

Submission ledger: `submit` requires one (reserve-before-submit). Autoresearch
passes a per-project db under `DATA_ROOT` (runtime state never in the repo
checkout — commit 9f0c43c convention). Internal bookkeeping only; completion
detection never reads it.

Prodtools location: resolved from env `AUTORESEARCH_PRODTOOLS` (no hardcoded
personal-path default in committed code; `paths.verify()` names the missing
variable). Version pinning = whatever that checkout is; prodtools and
autoresearch co-evolve in this group.

## Deleted from autoresearch

- `core/local_exec.py` (293 lines) — replaced by `runlocal`.
- `core/pipeline.py`: the 9 local-exec functions (~213 lines), `mu2ejobdef`
  flag-building, `mu2ejobsub` submit wrapper + cluster-id parsing,
  `poll_cluster`, `list-outputs`, the outstage-layout walkers.
- `tests/test_local_exec.py` (1001 lines, incl. the 3 duplicated test classes
  whose 8 shadowed tests never ran) — replaced by entry-rendering +
  seam-contract tests.
- Kept: `write_code_tarball` (per-config code tarball is still our delivery
  unit), preflight, harvest/metric extractors, leaderboard, graph/closed-loop.

## Error handling

- `submit` failure (no cluster id): stage fails immediately, stderr surfaced
  (c2b154d convention) — no reservation leak (ledger row closed by submit).
- `jobwait` nonzero: partial statistics path, same as today — harvest divides
  by `ok` count (the `harvest-denominator-bug` rule), row lands degraded or
  child fails per existing mode policy. `unknown` outcomes (empty history)
  are treated as failed for barrier purposes and flagged in the child log.
- Flash modes: the `grid_stages` gating from
  `no-run1b-substitution-poisons-flash-modes` is untouched — a fail-soft
  second objective still never coerces to 0.0.
- Held cluster: jobwait waits; the closed-loop barrier timeout is the
  backstop, exactly as for today's stalled stages.

## Testing

- Unit (in `tests/`, unittest, zero grid contact — suite invariant):
  entry rendering per mode/stage (golden dicts); wait.json parsing incl.
  `unknown`; denominator propagation into harvest; cluster.txt round-trip.
- Contract: one fixture wait.json shared with a runlocal-produced real one —
  assert schema equality (the "same JSON either way" claim, tested).
- `jobwait` unit tests live in prodtools (its home), with injected fake
  `jobsub_q`/`jobsub_history` runners (both already injectable).
- Live validation (needs fresh operator approval per standing rule):
  (a) 2-job grid smoke through submit + jobwait — also verifies ExitCode
  passthrough end-to-end for OUR jobs; (b) one full closed-loop child
  mubeam→…→harvest on the grid; (c) local chain re-run (already proven).

## Open items

- Who writes `jobwait`: operator in prodtools (pattern of Code.tar and
  `--json`), or drafted by Claude on a prodtools branch for review.
- The `<stage>_cluster.txt`-adjacent incident tooling (stale-cluster guard)
  keeps working unchanged, but should be re-read during implementation
  planning against the new submit path.
