# Local executor — run a config chain without the grid

**Goal:** Run one config's full stage chain on the local node, at reduced
statistics, producing the same `summary.json` and a leaderboard-shaped row —
and expose each job's FCL as an editable file so rate studies can be done by
hand.

**Architecture:** `pipeline.py` already isolates every grid touch into three
functions (`submit_stage`, `poll_cluster`, `list_outputs`). A `--local` flag
swaps those three for a local executor and changes nothing else. `harvest`,
the metric extractors, and `summary.json` are shared verbatim between the grid
and local paths — that sharing is the point of the design, not an optimization.

**Tech stack:** Python 3.11 stdlib (`subprocess`, `concurrent.futures`,
`hashlib`, `pathlib`); `unittest` (NOT pytest); the existing `mu2ejobdef` /
`mu2ejobfcl` tooling; no new dependencies.

## Global constraints

- The full suite must stay green with **no grid contact**: a local chain issues
  no `mu2ejobsub` and no `jobsub_q`.
- `harvest` and every metric extractor are **untouched**. If the local path
  computes a rate its own way, local and grid numbers stop being comparable and
  the feature is pointless.
- Local rows never reach a production leaderboard.
- Default parallelism is small and fixed (4), never derived from `nproc`.

---

## Context — what already exists

Verified 2026-08-12 by reading the code, not assumed:

- `pipeline.py --config X submit <stage> --dry-run` **already** materializes the
  template, runs `mu2ejobdef` to build the real `cnf.*.tar` job config, calls
  `mu2ejobfcl --index 0` to resolve job 0's FCL, probes the input URLs, and
  stops before `mu2ejobsub` (`core/pipeline.py:672-734`).
- **The resolved FCL is captured and thrown away.** It is bound at
  `core/pipeline.py:728` solely so `_probe_input_urls` can read it. The artifact
  this spec exposes is already being generated today.
- Stages hand off through a **plain text file list**,
  `state/<stage>_outputs.txt`, written by `list_outputs`
  (`core/pipeline.py:848-883`) and read both by the next stage's `--inputs` and
  by `harvest`. Reproducing that one file locally is sufficient to make every
  downstream step work unchanged.
- `preflight` already runs `mu2e -n 1` locally under `muse setup`, so local
  execution of Mu2e jobs is established practice in this repo.
- `graph.run --mock` bypasses the grid with synthetic metrics; it produces no
  FCL and no physics, and is not a substitute for this.

### Scale of a config (`core/pipeline.py:159`, `graph/config.py:84`)

| stage | njobs | events/job | total events |
|---|---|---|---|
| `mubeam` | 200 | 5,000 | 1.0M |
| `concat` | 1 | merge factor 200 | — |
| `mustops_ce` | 200 | 2,500 | 500k |
| `elebeam_flash` | 100 | 2,500 | 250k |

~500 jobs per config. One config at full statistics is ~8 h wall even if it
monopolized this 48-core node. A BO campaign is 40 configs, so ~15,000
CPU-hours — campaigns stay on the grid, permanently.

---

## Non-goals

- **Running a BO campaign locally.** See the arithmetic above.
- **BO-quality numbers.** Metric noise scales as 1/√N. At full statistics
  σ(sob) is 0.4% (`wiki/concepts/bo-noise-budget.md`); at the defaults here a
  stage runs 200 events against a configured 250k–1M, i.e. **1/1250 to 1/5000
  of campaign statistics**, so σ is tens of percent. Record-breaking steps in
  this project are ~1%. A local run resolves 2× effects, not 1% ones.
- **Validating the grid tarball.** Stated again below because it is the most
  expensive way to misread a green local run.

---

## Design

### 1. The seam

One new module, `core/local_exec.py`, with three functions mirroring the grid
trio. `pipeline.py` dispatches to them once, at the top of each stage function:

| grid | local | change |
|---|---|---|
| `submit_stage` → `mu2ejobsub` | `run_stage_local` | render each index's FCL with `mu2ejobfcl`, execute `mu2e -c` in a bounded pool |
| `poll_cluster` → `jobsub_q` | `wait_local` | wait on the pool; a failed job counts as a failed job |
| `list_outputs` → `/pnfs` glob | `list_outputs_local` | glob a local root |

`mu2ejobdef` runs in **both** paths, so the local run uses the real job config
rather than an approximation of one.

The local output root mirrors the outstage layout exactly:

```
DATA_ROOT/autoresearch_local/<config>/<runid>/00/00000/<output>.art
```

`<runid>` is a per-config integer that occupies the same position the grid
cluster id occupies, and is written to `state/<stage>_cluster.txt` exactly as a
cluster id would be — so the existing submit idempotency guard ("already
submitted (cluster=…); skip submit") behaves identically in local mode.

so `list_outputs_local` is a base-path swap rather than a rewrite. Its
`/pnfs` rename-drain loop (which exists only for dCache semantics — incidents
`stage-out-lag`, `stage-out-rename-race`) is skipped locally.

### 2. CLI surface

Two new verbs alongside `submit` / `poll` / `list-outputs` / `harvest`:

```
pipeline.py --config X local-build <stage>    # build the FCLs, stop
pipeline.py --config X local-run   <stage>    # execute what is on disk
pipeline.py --config X submit <stage> --local # both; used by a full local chain
```

`AUTORESEARCH_LOCAL=1` sets the same mode, so a graph-runner child inherits it
without every call site growing a flag.

`local-build` then `local-run` is the study loop. `submit --local` always
rebuilds, so the canonical path cannot inherit a stale edit.

### 3. The FCL edit loop

`local-build` writes each index's resolved FCL to
`state/fcl/<stage>_<index>.fcl` and records its SHA-256.

`local-run` executes whatever is on disk and compares hashes. On a mismatch it
prints `FCL hand-edited: <name>` and records `fcl_edited: true` in
`summary.json`.

A recorded hash is deliberately chosen over a `--reuse-fcl` flag. A flag
protects you only if you remember to think about it; the recorded fact travels
with the row, so a number generated today is still interpretable in three
months. Compare `template-fcl-staleness`, where an edit intended for one run
silently persisted into later ones.

### 4. Scale dials

`--local-njobs N` (default 1) and `--local-events N` (default 200). Either flag
may be **repeated** with `<stage>=<value>` to override one stage, and a repeat
wins over the bare form:

```
--local-njobs 1 --local-njobs elebeam_flash=4
```

Two explicit dials, not a scale factor: a multiplier reads clever and then
nobody can say what actually ran.

**`state/<stage>_events_per_job.txt` must be stamped with the LOCAL value.**
`harvest` scales metrics by that stamp. The stamp exists because editing
`events_per_job` between submit and harvest silently mis-scaled `sob` once
already (`wiki/incidents/events-per-job-mid-flight-edit.md`). Getting this
wrong makes every local metric wrong by the ratio of real to local events, in
a way that looks entirely plausible. This is the single most likely way to
build the feature incorrectly.

**`concat` clamps** `merge_factor` to `min(merge_factor, n_inputs)`: the
configured 200 cannot merge the single file a local `mubeam` produces.

### 5. Row destination

`leaderboards/leaderboard_local_<mode>.tsv` — a separate file. The production
board and the GP never see low-statistics rows, so a 5%-noise row cannot poison
a campaign whose picker assumes 0.4%.

The row carries the `njobs` and `events_per_job` actually used, plus
`fcl_edited`. A local row that does not say how little data produced it is a
trap for whoever reads it next.

### 6. Parallelism

Default pool size **4**, overridable with `--local-pool N`. This is a shared
48-core GPVM and `mustops_ce` requests 3 GB per job; a pool sized to the machine
would wedge the login node for everyone.

---

## Risks and constraints

- **A green local chain does NOT validate the grid `Code.tar.bz2`.** Local runs
  exercise the patched muse workdir, not the grid tarball. These have diverged
  before at the cost of a whole campaign
  (`wiki/incidents/foilsflash-tarball-mode-key-omission.md`, where preflight
  passed locally while every grid job died;
  `wiki/incidents/prodtarget-env-divergence.md`). Local success means the
  physics config is sane, not that the grid job will start.
- **Statistics.** Covered under Non-goals; restated in the row itself.
- **`--local` becomes a live branch in production code.** Mitigated by test 1
  below, which is the reason that test exists.

## Testing

Six `unittest` tests, no grid contact, matching the existing suite's style:

1. A full local chain issues **no** argv beginning with `mu2ejobsub` or
   `jobsub_q` (patch `subprocess`).
2. `state/<stage>_events_per_job.txt` carries the local value, not the
   configured one.
3. `concat`'s merge factor clamps to the actual input count.
4. `list_outputs_local` writes a `<stage>_outputs.txt` shaped identically to the
   grid version, so `harvest` is provably untouched.
5. A modified FCL sets `fcl_edited: true` and prints the warning.
6. A local run never writes to a production leaderboard path.

## Open questions

- Should `graph.run` gain `--local` in this phase, or should phase 1 stop at
  `pipeline.py` verbs and drive the four stages by hand? Driving by hand first
  proves the executor without touching the orchestrator.
- Retention: local `.art` output is multi-GB per run and nothing prunes it. A
  `local-clean` verb is deliberately omitted for now (YAGNI); the per-config
  namespacing makes manual cleanup a single named directory.
