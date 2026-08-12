# Local executor — run one stage without the grid

> **Amended 2026-08-12, after implementation.** The original spec described a
> four-stage local chain that produced a `summary.json` and a leaderboard-shaped
> row. What shipped is narrower: **`mubeam` only, no rows, no local board**.
> Everything below describes what works today. What was designed but not built
> is preserved verbatim under [Deferred to a later phase](#deferred-to-a-later-phase)
> — it is still the intended direction, it is simply not code yet.

**Goal (as shipped):** Run the `mubeam` stage on the local node, at reduced
statistics, and expose each job's resolved FCL as an editable file so rate
studies can be done by hand. The local run leaves `state/mubeam_outputs.txt`
in exactly the shape the grid path leaves it, so `harvest` and every downstream
consumer need no changes.

**Architecture:** `pipeline.py` already isolates every grid touch into three
functions (`submit_stage`, `poll_cluster`, `list_outputs`). The local executor
swaps those three and changes nothing else. `harvest`, the metric extractors,
and `summary.json` are shared verbatim between the grid and local paths — that
sharing is the point of the design, not an optimization. `core/harvest.py` is
byte-for-byte untouched by this branch.

**Tech stack:** Python 3.11 stdlib (`subprocess`, `concurrent.futures`,
`hashlib`, `pathlib`) plus `core/paths.py`; `unittest` (NOT pytest); the
existing `mu2ejobdef` / `mu2ejobfcl` tooling; no new dependencies.

## Global constraints

- The full suite must stay green with **no grid contact**: a local run issues
  no `mu2ejobsub` and no `jobsub_q`.
- `harvest` and every metric extractor are **untouched**. If the local path
  computed a rate its own way, local and grid numbers would stop being
  comparable and the feature would be pointless.
- Local runs produce no leaderboard row at all in this phase, so they cannot
  reach a production board.
- Default parallelism is small and fixed (4), never derived from `nproc`.

---

## Scope: `mubeam` only

`LOCAL_SUPPORTED_STAGES = ("mubeam",)` in `core/pipeline.py`. A local `mubeam`
needs no input staging. **Every downstream stage does**: `cmd_submit` builds a
/pnfs hardlink farm (`stage_hardlink_farm`) so `concat` / `mustops_ce` can
resolve input basenames, and that has no local analogue.

`local-build`, `local-run` and `submit --local` all route through one guard
(`_require_local_stage`) and **raise `SystemExit` with an explanatory message**
for any other stage. The refusal is loud on purpose: `mu2ejobdef` will happily
accept a cnf with no `--inputs`, and the resulting job reads nothing and
reports success.

The refusal covers `local-run` as much as `local-build`, because `local-run`
writes `state/<stage>_cluster.txt` — a runid parked in `concat_cluster.txt`
would trip `cmd_submit`'s idempotency guard and silently suppress a *real* grid
submit of that stage.

---

## Context — what already existed

Verified 2026-08-12 by reading the code, not assumed:

- `pipeline.py --config X submit <stage> --dry-run` **already** materializes the
  template, runs `mu2ejobdef` to build the real `cnf.*.tar` job config, calls
  `mu2ejobfcl --index 0` to resolve job 0's FCL, probes the input URLs, and
  stops before `mu2ejobsub` (`submit_stage`).
- **The resolved FCL was captured and thrown away.** It was bound solely so
  `_probe_input_urls` could read it. The artifact this spec exposes was already
  being generated.
- Stages hand off through a **plain text file list**,
  `state/<stage>_outputs.txt`, written by `list_outputs` and read both by the
  next stage's `--inputs` and by `harvest`. Reproducing that one file locally is
  sufficient to make every downstream step work unchanged.
- `preflight` already runs `mu2e -n 1` locally under `muse setup`, so local
  execution of Mu2e jobs is established practice in this repo.
- `graph.run --mock` bypasses the grid with synthetic metrics; it produces no
  FCL and no physics, and is not a substitute for this.

### Scale of a config (`core/pipeline.py` `STAGES`, `graph/config.py`)

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

## Design (as shipped)

### 1. The seam

One new module, `core/local_exec.py`, mirroring the grid trio:

| grid | local | change |
|---|---|---|
| `submit_stage` → `mu2ejobsub` | `build_fcls` + `run_jobs_local` | render each index's FCL with `mu2ejobfcl`, execute `mu2e -c` in a bounded thread pool |
| `poll_cluster` → `jobsub_q` | *(nothing)* | `run_jobs_local` is **synchronous**; by the time `poll` could run, every job is done, so `cmd_poll` is a no-op in local mode |
| `list_outputs` → `/pnfs` glob | `list_outputs_local` | glob a local root |

`mu2ejobdef` runs in **both** paths, so the local run uses the real job config
rather than an approximation of one. The argv is built by a single shared
helper, `_jobdef_cmd`, so grid and local cannot drift; the only permitted
difference is `--events-per-job`.

The local output root mirrors the outstage layout exactly:

```
DATA_ROOT/autoresearch_local/<config>/<runid>/00/00000/<output>.art
```

so `list_outputs_local` is a base-path swap rather than a rewrite. Its `/pnfs`
rename-drain loop (which exists only for dCache semantics — incidents
`stage-out-lag`, `stage-out-rename-race`) is skipped locally.

`<runid>` is a per-config integer occupying the position the grid cluster id
occupies, written to `state/<stage>_cluster.txt` exactly as a cluster id would
be.

### 2. The marker — `state/<stage>_local.txt`

**A runid is not a ClusterId, and nothing about the integer says which it is.**
`next_runid` returns small ints (1, 2, 3…). Handed to `jobsub_q`, such a value
polls a nonexistent cluster for the full 24 h cap (the
`poll-deadlock-missing-outstage-dirs` shape); handed to `list_outputs`, it globs
the grid outstage for a cluster no grid job ever wrote.

So `cmd_local_run` writes a marker file, `state/<stage>_local.txt`, holding the
same runid. It is the **single source of truth for "this stage ran locally"**,
and it is what `cmd_poll` and `cmd_list_outputs` consult (`_is_local_stage`).

Three rules hold it together:

1. **Marker written FIRST**, cluster file second. If the process dies between
   the two writes, the residue is a marker with no cluster file (poll no-ops;
   harmless), never a runid nothing distinguishes from a real cluster id.
2. **Cleared together, runid first**, by a grid `cmd_submit`. `submit_stage`
   rewrites `<stage>_cluster.txt` only *after* `mu2ejobsub` parses a cluster id,
   so unlinking the marker alone would leave the runid behind, unmarked, on
   every path that never reaches that write (`--dry-run`; a raise in
   `mu2ejobdef` / `mu2ejobfcl` / `_probe_input_urls` / token refresh /
   `mu2ejobsub`).
3. **The clear runs BEFORE the idempotency guard.** The guard cannot tell a
   runid from a ClusterId, so with the clear placed after it, a plain
   (un-forced) `submit mubeam` following any local run printed
   `already submitted (cluster=1)` and silently did nothing — on the exact path
   a graph child takes.

`AUTORESEARCH_LOCAL=1` is an **activation** switch only: `cmd_submit` reads it
to choose local mode, so a graph-runner child can inherit local mode without
every call site growing a flag. It is deliberately **not** a detection signal —
`_is_local_stage` keys on the marker alone. Every path that runs local jobs goes
through `cmd_local_run`, which always writes the marker, so an env disjunct
would add no capability and one failure mode: an operator who exported the var
for a study and later launched a campaign from that shell would make `cmd_poll`
a no-op on a live grid cluster.

### 3. CLI surface

Two new verbs alongside `submit` / `poll` / `list-outputs` / `harvest`:

```
pipeline.py --config X local-build mubeam    # build the FCLs, stop
pipeline.py --config X local-run   mubeam    # execute what is on disk
pipeline.py --config X submit mubeam --local # both
```

`local-build` then `local-run` is the study loop. `submit --local` always
rebuilds — `cmd_local_build` unlinks any existing cnf and rebuilds it
unconditionally, exactly as `submit_stage` does, so the canonical path cannot
inherit a stale edit or a cnf a *grid* submit left behind at 5,000 events/job.

### 4. The FCL edit loop

`local-build` writes each index's resolved FCL to
`state/fcl/<stage>_<index>.fcl` and records its SHA-256 in a
`<name>.fcl.sha256` sidecar. It prunes this stage's previous set first, so a
build of 4 followed by a build of 1 does not leave indices 1–3 behind for the
next run to misreport.

`local-run` executes whatever is on disk and compares hashes. On a mismatch it
prints `FCL hand-edited: <name>` to the console. A missing sidecar counts as
edited: absence of evidence is not evidence the file is pristine.

A recorded hash is deliberately chosen over a `--reuse-fcl` flag. A flag
protects you only if you remember to think about it. Compare
`template-fcl-staleness`, where an edit intended for one run silently persisted
into later ones.

**The warning is console-only in this phase.** Persisting it (a state file, or
an `fcl_edited` field on a row) belongs with the phase that produces rows;
until then it would be a schema field nothing can ever set.

### 5. Scale dials

`--local-njobs N` (default 1) and `--local-events N` (default 200). Either flag
may be **repeated** with `<stage>=<value>` to override one stage, and a repeat
wins over the bare form:

```
--local-njobs 1 --local-njobs elebeam_flash=4
```

Two explicit dials, not a scale factor: a multiplier reads clever and then
nobody can say what actually ran. Values must parse as integers ≥ 1; anything
else raises.

**`state/<stage>_events_per_job.txt` is stamped with the LOCAL value** by both
`local-build` and `local-run`. `harvest` scales metrics by that stamp. The stamp
exists because editing `events_per_job` between submit and harvest silently
mis-scaled `sob` once already
(`wiki/incidents/events-per-job-mid-flight-edit.md`). Getting this wrong makes
every local metric wrong by the ratio of real to local events, in a way that
looks entirely plausible. This is the single most likely way to build the
feature incorrectly.

### 6. Parallelism

Default pool size **4**, overridable with `--local-pool N`. This is a shared
48-core GPVM and `mustops_ce` requests 3 GB per job; a pool sized to the machine
would wedge the login node for everyone. Threads, not processes: each unit of
work is a subprocess, so the GIL is irrelevant.

A failed job is reported (`job NNNNN FAILED rc=N`, plus a closing warning
listing the failed indices), never raised — one bad index must not lose the
other jobs' output. A `subprocess` raise is caught per-job and written to that
job's log.

---

## Risks and constraints

- **A green local run does NOT validate the grid `Code.tar.bz2`.** Local runs
  exercise the patched muse workdir, not the grid tarball. These have diverged
  before at the cost of a whole campaign
  (`wiki/incidents/foilsflash-tarball-mode-key-omission.md`, where preflight
  passed locally while every grid job died;
  `wiki/incidents/prodtarget-env-divergence.md`). Local success means the
  physics config is sane, not that the grid job will start.
- **Statistics.** Covered under Non-goals.
- **`--local` becomes a live branch in production code.** Mitigated by the
  no-grid-contact tests, which is the reason those tests exist.
- **The graph layer is marker-unaware.** `graph/child_tracker.py`,
  `graph/closed_loop.py` and `graph/pipeline_io.py` know nothing about
  `state/<stage>_local.txt`. Local mode is a `pipeline.py`-level facility today;
  driving a chain through the orchestrator is not supported.
- **Nothing prunes local `.art` output**, which is multi-GB per run. There is
  deliberately no `local-clean` verb (YAGNI); the per-config namespacing makes
  manual cleanup a single named directory.

## Testing

`tests/test_local_exec.py`, `unittest`, no grid contact, every path a tmpdir:

- **No grid tooling, ever** — neither `local-build` nor `run_jobs_local` emits
  an argv containing `mu2ejobsub` or `jobsub_q`.
- **`state/<stage>_events_per_job.txt` carries the local value**, not the
  configured one — asserted for `local-build` and for `local-run`, and the grid
  path's own stamp is asserted separately so the `_jobdef_cmd` extraction
  cannot have broken it.
- **`list_outputs_local` writes a `<stage>_outputs.txt` shaped identically to
  the grid version**, so `harvest` is provably untouched.
- **A modified FCL prints `FCL hand-edited: <name>`** — at the `edited_fcls`
  unit *and* through `cmd_local_run` itself, with a negative case.
- **The local jobdef argv equals the grid jobdef argv** except for
  `--events-per-job`.
- **`cmd_local_run` end to end** (only `subprocess` mocked): the marker exists,
  the cluster file exists, and **the marker was written first**.
- **The marker, not the env var, drives detection**: `AUTORESEARCH_LOCAL=1`
  with no marker leaves `cmd_poll` reaching the real `poll_cluster` and
  `cmd_list_outputs` reaching the real `list_outputs`.
- **A grid submit clears the local pair**, forced *and* un-forced, and a
  `--local` submit does not clear its own marker.
- **Unsupported stages are refused** by both verbs.
- **A failing `mu2ejobfcl` surfaces its stderr** rather than swallowing it.
- **A smaller rebuild prunes the larger previous set**, and leaves other
  stages' FCLs alone.
- Pool bound, failure reporting, and the scale-dial parser are covered as
  units.

---

## Deferred to a later phase

Designed, specified, and **not implemented**. Recorded here so the intent
survives; do not read any of it as describing current behavior.

### A full local chain

The original design ran all four stages locally. `concat`, `mustops_ce` and
`elebeam_flash` consume a previous stage's outputs through a /pnfs hardlink
farm built in `cmd_submit`, and no local analogue exists. Extending the scope
means giving `stage_hardlink_farm` a local mode, or teaching the downstream
stages to take absolute local paths.

### The `concat` merge-factor clamp

> **`concat` clamps** `merge_factor` to `min(merge_factor, n_inputs)`: the
> configured 200 cannot merge the single file a local `mubeam` produces.

Needed the moment `concat` becomes locally runnable; unreachable until then. A
`clamp_merge_factor` helper was written, had no caller, and was removed.

### Row destination — `leaderboard_local_<mode>.tsv`

> `leaderboards/leaderboard_local_<mode>.tsv` — a separate file. The production
> board and the GP never see low-statistics rows, so a 5%-noise row cannot
> poison a campaign whose picker assumes 0.4%.
>
> The row carries the `njobs` and `events_per_job` actually used, plus
> `fcl_edited`. A local row that does not say how little data produced it is a
> trap for whoever reads it next.

A local `mubeam` alone cannot produce a row — `harvest` needs the CE and calo
stages. Both a `local_board_path` helper and an `EvalSummary.fcl_edited` field
were written, had no caller, and were removed; `fcl_edited` in particular would
otherwise have emitted `"fcl_edited": null` into every *grid* `summary.json`
forever with nothing able to set it. The separation rule above still stands and
must be honoured by whatever phase adds rows.

### `graph.run --local`

Phase 1 deliberately stops at `pipeline.py` verbs, driving the stage by hand.
That proves the executor without touching the orchestrator. The graph layer
remains marker-unaware; wiring it is the first task of any phase that wants a
chain.
