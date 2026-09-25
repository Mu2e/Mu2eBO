# Phase C1: the prodtools kit — design

Date: 2026-09-25. Status: draft for review.

Related:
- [`2026-09-23-generic-study-design.md`](2026-09-23-generic-study-design.md),
  the generic-study design. This document implements the first part of its
  Phase C and amends it where the "Decisions" section below says so.
- [`2026-09-22-kit-seam-design.md`](2026-09-22-kit-seam-design.md), for the
  verified prodtools facts and the kit client.
- prodtools spec
  `docs/superpowers/specs/2026-09-25-code-entries-and-run-local-design.md`
  in `muse_050125/prodtools` (P1 and P2, merged into that repo's local
  `main` at 6640e6e, not pushed).
- `wiki/drivers/contract-engine.md`, Open questions: the P1 spike findings
  and the Phase C follow-ups this document picks up.

## Goal

Phase C of the generic-study design moves foilspf onto the contract engine
and deletes the old pipeline. It is split into three sub-projects, each with
its own spec, plan and build:

| # | Sub-project | Done when |
|---|---|---|
| **C1** (this document) | the prodtools kit, zero-knob studies, and the engine fixes real grid jobs need first | a dry run matches today's entries; a zero-knob study runs `mubeam` then `mustops_ce` locally, then 1 job per step on the grid |
| C2 | foilspf on the engine: `offline_preflight`, the sob and flash analyses in anakit, the campaign-loop follow-ups | one foilspfbpz point at q = 1 on the grid, with a row that agrees with history within noise |
| C3 | delete the old pipeline; rename `study_run`/`study_loop` to `graph.run`/`graph.closed_loop` | the suite is green and nothing imports the deleted modules |

After C1, a study whose steps all run on prodtools is defined in JSON and
runs on the engine, locally or on the grid, with nothing Mu2e-specific in the
engine.

## Decisions

All decided by the operator on 2026-09-25.

| Question | Decision |
|---|---|
| How is a run chosen to be local or grid? | A runner flag, `--executor grid\|local`. The executor does not change the physics, so it is not part of `measure_sha`. A small plumbing test is its own study file with its own board; the `AUTORESEARCH_LOCAL_*` scale variables have no engine counterpart. |
| A prodtools step with too few successful jobs | Below `quorum` the step fails and the point gets `broken.txt` and no row. `quorum` is required on every prodtools step; there is no default. (Today's pipeline only warns below its default of 0.9.) |
| Where the prodtools-specific code lives | An in-process adapter in autoresearch, `core/adapters/prodtools.py`, calling the prodtools read and write MCP servers through the existing kit client. It imports only the contract types, so it could later be lifted into an MCP server of its own. |
| Cancelling a prodtools run | Add **P3**, a `cancel_run` tool, to the prodtools repo (local `main`, pushed only on a go-ahead). |
| Where the sob and flash analyses go (for C2) | anakit, not local plugins. This settles Open question 2 of the generic-study design. |

## What changes, file by file

| File | Change |
|---|---|
| `core/adapters/__init__.py`, `core/adapters/prodtools.py` | new: `ProdtoolsKit`, registered as the adapter for the kit `prodtools` |
| `kits.toml`, `core/kit_config.py` | a new `[servers.<name>]` table: the MCP servers an adapter talks to (`prodtools_read`, `prodtools_write`); a new required `executors` key on each native kit |
| `core/kit_registry.py` | `KitDecl` gains `pipeline` and `required_fixed`; `prodtools` gains `fatal_log_codes`, a 200-job cap and a required `quorum`; two new value validators |
| `core/modes.py` | the rule that decides whether a study runs on the engine or the pipeline |
| `core/contract.py` | retry backoff; `open_kit` and `KitSet` carry the executor and `--parallel`; `check_kits` also checks an adapter's servers |
| `core/scheduler.py` | cancel the other running steps when one fails |
| `core/study.py`, `graph/study_graph.py` | zero-knob studies |
| `graph/study_run.py`, `graph/study_loop.py` | `--executor`, `--parallel`, the ticket check, zero-knob handling |
| `stage_entries/mustops_ce.json` | `MaxEventsToSkip: 8000` written in the template |
| `mode_specs/*.json` (the 7 live specs) | `quorum: 0.8` on `elebeam_flash`; `fatal_log_codes` under `kits.prodtools` |
| `tests/fixtures/engine_studies/prodtools_smoke.json` | new: the zero-knob acceptance study |
| prodtools repo | P3: `cancel_run`, and `cancelled` in `run_status` |

## Which studies run on the engine

Until C3 two runners exist: the old pipeline (`graph.run`,
`graph.closed_loop`, `core/pipeline.py`) and the engine (`graph.study_run`,
`graph.study_loop`). Each kit declares which runners can drive it. Today a
kit has one flag, `engine`, and a study that mixes engine and pipeline kits
is refused when the study files load, which stops every command.

Once `prodtools` has an adapter, both runners can drive it. With one flag,
marking it `engine=True` would make every foilspf spec "mixed" and break
every command. So `KitDecl` gets two flags, `engine` and `pipeline`:

| Kit | engine | pipeline |
|---|---|---|
| `prodtools` | yes (new) | yes |
| `offline_preflight`, `ce_sensitivity`, `flash_edep_per_pot` | no (C2) | yes |
| native kits from `kits.toml` (`toykit`) | yes | no |

The rule, applied when a study loads (`core/modes.py`, `runs_on_engine`):
1. If the engine can drive every kit the study names, it is an engine study.
2. Otherwise, if the pipeline can drive every kit, it is a pipeline study.
3. Otherwise it is refused, naming the kits no single runner can drive.

So the foilspf specs stay on the pipeline, unchanged, until C2 gives their
other kits engine support; then they pass rule 1 with no switch to flip. A
prodtools-only study runs on the engine. C3 deletes the `pipeline` flag and
rule 2.

## The adapter: `ProdtoolsKit`

### Shape

- `ProdtoolsKit(campaign, *, executor, parallel)` implements the Kit
  interface of `core/contract.py` (`name`, `version`, `tools`,
  `accepts_lists`, `poll_s`, `submit`, `status`, `results`, `describe`,
  `cancel`, `close`). `accepts_lists` is false.
- It opens two `KitClient`s, both configured in `kits.toml`:
  - `[servers.prodtools_write]`: `${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_write_mcp.sh`,
    for `submit_once`, `run_local` and, after P3, `cancel_run`;
  - `[servers.prodtools_read]`: `${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_mcp.sh`,
    for `run_status`.

  A `[servers.<name>]` entry has the keys `command`, `env_passthrough`,
  `set` and `timeouts` (per server tool plus `start`), all required. For
  both prodtools servers, `env_passthrough` is `KRB5CCNAME` and
  `BEARER_TOKEN_FILE`, and `set` puts `SPACK_USER_CACHE_PATH` off NFS
  (`wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`). Timeouts:
  `submit_once` 900 s, `run_local` 300 s, `run_status` 120 s, `cancel_run`
  120 s, `start` 120 s.
- **Version:** the adapter's own constant, `prodtools-adapter/1`. It is what
  `measure_sha` hashes. The prodtools write server's reported version goes
  into each step's results metadata, but not into the hash, so a prodtools
  upgrade does not start a new board. The constant is bumped by hand
  whenever the adapter changes what a step measures.
- **`tools`:** `submit`, `status`, `results`, `describe`, plus `cancel`
  when the write server offers `cancel_run`.
- **`poll_s`:** 30 s to 600 s for `grid`, 5 s to 60 s for `local`.
- **`LAUNCH_STAGGER_S`:** 90 s, today's grid stagger
  (`wiki/incidents/concurrent-token-contention.md`).
- **Executors:** `grid` (the default) and `local`. `parallel` (1 to 16,
  default 4) applies to `local` only; the runner refuses it with `grid`.
- **Names:** the engine's handle is `<config>.<step>`. The adapter splits
  it at the last dot. It refuses a config name that has any character other
  than letters, digits and `_`, because the config goes into prodtools'
  `desc` and `dsconf`, which are dot-separated fields of the run name.
- **Adapter state** for one step lives in
  `<GRID_DATA_ROOT>/<config>/prodtools/<step>/`: `record.json`, the
  rendered `entry.json`, and, for `local`, the staged input directory. The
  per-config code tarball is `<GRID_DATA_ROOT>/<config>/prodtools/Code.<digest>.tar.bz2`,
  shared by that config's steps.

### `describe`

`{params: [the prodtools study keys and fixed keys], metrics: ["njobs",
"njobs_ok"], accepts_lists: false}`, so `check_kits` checks a study's
params and metric names against the adapter at launch.

### `submit(name, params, files, inputs)`

1. **Render the entry** from the step's stage template (the step's `entry`),
   the same way `core/pipeline.py:_render_and_build_cnf` does today:
   - `desc` is the template's `desc_fmt` with the config name, and `dsconf`
     is `Run1Bak_<config>`, both as today, so the dry run can compare
     entries directly. The run name is therefore
     `cnf.<user>.<desc>.<dsconf>.0`.
   - `njobs`, `events_per_job` (as the entry's `events`) and `memory_mb`
     (as `memory`) come from `params`, which carries the step's `fixed`
     values. The template's own `njobs`, `events` and `memory` are defaults
     used only when `fixed` omits them.
   - `{geom}` in the template is the basename of the `geom` file in
     `files`.
   - `mustops_ce`'s `MaxEventsToSkip` comes from the template, which now
     says 8000 (today Python lowers the template's 100720 to 8000; the
     pipeline keeps doing that until C3, which is now a no-op).
2. **Build the per-config code tarball**: the study's `code_tarball`, plus
   the `geom` file, plus every bare-name (no `/`) `#include` of the
   template's `fcl_overrides`, taken from `core/pipeline_templates/`, plus
   `Code/setup_post.sh` prepending `$CODE_DIR` to `MU2E_SEARCH_PATH` and
   `FHICL_FILE_PATH`. The digest in its name is the SHA-256 over the base
   tarball's bytes, the geom, the extra files and `setup_post.sh`; an
   existing file with that name is reused. This is today's
   `write_code_tarball`, keyed by content instead of mtime.
3. **Stage the inputs.** When `inputs` is not empty, every input file is
   hard-linked into one directory and the entry gets
   `inloc: "dir:<directory>"` and `input_data: {basename: 1, ...}`, as
   today's `input_farm`:
   - `grid`: `/pnfs/mu2e/scratch/users/<user>/autoresearch_grid/<config>/staged/<step>/`.
     A hard link that fails is an error; a copy is never made
     (`wiki/incidents/data-quota-exhausted-grid-accumulation.md`).
   - `local`: the step's adapter directory. A cross-device link falls back
     to a copy, as today's local farm does.
   - An input whose URI is not `file://` is refused.
4. **Write the record, then submit.** `record.json` gets the params digest
   (SHA-256 of the canonical JSON of `params`, the FileRefs in `files` and
   `inputs`, and the executor), the entry path, the executor, and
   `state: "submitting"`. Then:
   - `grid`: take the host-wide submit lock
     (`/tmp/mu2e_submit.<user>.lock`, the same file today's pipeline
     uses, so the two runners serialize together), refresh the bearer token
     if it is more than 1 h old (today's `_maybe_refresh_token`), and call
     `submit_once(json=<entry.json>, desc, dsconf, run_as="self")`.
   - `local`: call `run_local(json=<entry.json>, desc, dsconf,
     run_as="self", parallel=<parallel>)`.

   On success the record becomes `state: "submitted"` with the receipt's
   run name, and `submit` returns `name`. On a timeout or transport error,
   the adapter asks `run_status` for the run: if a receipt exists it is
   adopted; if not, `submit` raises and the step fails, and a later rerun
   of the point submits again from the record.
5. **Idempotency by name.** When `record.json` already exists:
   - same digest, `submitted`: return `name`;
   - same digest, `submitting`: ask `run_status`; adopt a receipt that is
     `submitted`, `running` or finished, submit again if there is none, and
     fail loudly if the receipt is itself stuck in `submitting` or
     `building`;
   - different digest: raise, naming both digests. The same name with
     different params is an error in the contract.

### `status(handle)`

`run_status(name=<run name>, mine=True)`, mapped:

| `run_status` state | contract state |
|---|---|
| `building`, `submitting`, `starting`, `submitted`, `running` | `working`; `progress` is `{done, total, ok}` from the `jobs` block when there is one |
| `unknown` | `working`, with prodtools' note as the message. The first time it is seen is written to the record; after 6 h of `unknown` the step is `failed`. `unknown` is never success. |
| `failed` | `failed`, with prodtools' `error` or `note` |
| `cancelled` (P3) | `cancelled` |
| `done`, `short` | the completion checks below |

**Completion checks** run once; their verdict is written to the record and
reused by later `status` and `results` calls.
1. `ok == 0`, or `ok / njobs < quorum`: `failed`, e.g. `11/15 jobs ok,
   below quorum 0.8`.
2. **Stage-out.** Every output that `run_status` lists for a successful job
   must exist. If some are missing, the step stays `working` with the
   message `waiting for stage-out: N of M outputs missing`; after 30 min it
   is `failed` (`wiki/incidents/stage-out-lag.md`).
3. **Log scan.** Every job's logs, successful or not:
   - `grid`: `<outstage>/<cluster>/<proc>/*.log`;
   - `local`: `<run dir>/job_NNNNNN/*.log`.

   Each is searched for the codes in `kits.prodtools.fatal_log_codes`. Any
   hit is `failed`, naming the code and the job. A successful job with no
   `.log` file is `failed` too: a scan that could not run is not a clean
   scan. A failed job with no log is already counted against `quorum` and
   adds nothing here. This replaces the pipeline's `scan_logs` node for
   engine studies.
4. Otherwise `completed`.

`poll_ms` is 60 000 while `working` on the grid and 10 000 locally.

### `results(handle)`

Only after `status` has said `completed`; otherwise an error.
- **`files`:** the outputs of successful jobs whose basename matches the
  template's `output_glob`, the same selection `list-outputs` makes today.
  Each is `{name: basename, uri: file://<absolute path>, kind: <extension
  without the dot>}`.
- **`metrics`:** `{njobs, njobs_ok}`.
- **`metadata`:** `events_per_job`, `executor`, `run_name`, `desc`,
  `dsconf`, `jobid` (grid) or `host` and `pid` (local), `outstage` (grid)
  or the run directory (local), the failed jobs' exit codes, and the
  prodtools write server's version. C2's analyses take their denominators
  from `njobs_ok` and `events_per_job` here.

### `cancel(handle)`

Offered only when the write server has `cancel_run` (P3). Calls
`cancel_run(name=<run name>, run_as="self")` once, never retried, and
returns the contract state from its reply.

## Engine changes

### Executor and parallel

- `graph.study_run` and `graph.study_loop` take `--executor grid|local`
  (default `grid`) and `--parallel N` (`local` only, 1 to 16, default 4).
- They reach adapters through `KitSet(campaign, executor=..., parallel=...)`
  and `open_kit(name, campaign, executor=..., parallel=...)`. An adapter
  declares the executors it supports in `EXECUTORS`; a native kit from
  `kits.toml` gets a new required key `executors` (`toykit`: `["grid",
  "local"]`, since it does not care).
- A launch is refused when any kit of the study does not support the chosen
  executor, or when `--parallel` is given with `grid`.
- `point.json` records the executor. A rerun of the point with a different
  executor is refused, before anything runs.
- `study_loop` passes both flags to every child it launches.

### Zero-knob studies

A study may have `knobs: []`: it is evaluated once, at a fixed setup, with
no search.
- The loader accepts an empty list. `derive` and `geom` may then use only
  consts.
- A zero-knob study must run on the engine; a pipeline study with no knobs
  is refused at load.
- `graph.study_run` refuses `--x` for a zero-knob study; for every other
  study `--x` stays required.
- `graph.study_loop` refuses a zero-knob study: "nothing to pick; run
  graph.study_run".
- The surrogate MCP server's `list_problems` leaves zero-knob studies out,
  and `build_problem` refuses one.
- Its leaderboard rows have no knob columns.

### Retry backoff

`NativeKit._call` and the adapter's calls to the prodtools servers share one
retry helper. The calls that may be repeated keep their 3 attempts, now with
a pause of 5 s after the first failure and 20 s after the second. The
pause is injectable so tests run in milliseconds.

### Cancelling the other steps when one fails

- `run_steps` holds a stop event. When the first step fails, it sets the
  event and calls `cancel(handle)`, once, on every running step whose kit
  offers `cancel` and whose `<step>_cluster.txt` exists. Kits without
  `cancel` are logged: `<step>: kit <kit> cannot cancel; it runs to
  completion`.
- A step thread that has not submitted yet checks the event before calling
  `submit` and ends as `cancelled` without submitting.
- Cancelled steps end with outcome `cancelled`; `broken.txt` still names
  the first step that failed.

### Ticket check

`graph.study_run` and `graph.study_loop` refuse a launch with executor
`grid` when any kit of the study declares `REQUIRES_KERBEROS` (the prodtools
adapter does) and the Kerberos ticket has less than 4 h left, using
`core/launch_checks.check_kerberos(GRID_TICKET_SECONDS)`. Renewing the
ticket during a campaign is C2 work.

### Launch check for adapters

`check_kits` starts each adapter's servers once. It refuses the launch if a
server will not start, or if the write server lacks `submit_once`
(executor `grid`) or `run_local` (executor `local`), or the read server
lacks `run_status`.

## Registry and data changes

- **`KitDecl`** gains `pipeline: bool` and `required_fixed: frozenset`. The
  loader refuses a step whose kit's `required_fixed` keys are missing from
  its `fixed`.
- **`prodtools`** declares:
  - study keys: `code_tarball` (path) and `fatal_log_codes` (a list of
    strings, may be empty; new validator `string_list`);
  - fixed keys: `njobs` (1 to 200; new validator `job_count`, because
    `run_status` lists at most 200 jobs' outputs and a larger run would be
    silently truncated), `events_per_job`, `memory_mb`, `quorum`;
  - `required_fixed = {"quorum"}`; `engine=True`, `pipeline=True`.
- **The 7 live specs** (`foilsflash`, `foilspf`, `foilspf2k`, `foilspfbp`,
  `foilspfbpx`, `foilspfbpz`, `foilspfbw`): every prodtools step has a
  `quorum` (`elebeam_flash` gets 0.8, the value the other stages use), and
  `kits.prodtools` gets `fatal_log_codes: ["GeomSolids1001"]`, today's
  `SCAN_BROKEN_CODES`. The pipeline's behavior changes only in its warning
  threshold for `elebeam_flash` (0.9 to 0.8). A golden that records
  `elebeam_flash`'s quorum is updated for that one field; everything else
  in the goldens must pass unchanged.
- **`stage_entries/mustops_ce.json`**: `MaxEventsToSkip` 100720 becomes
  8000, with the rationale moved from the `core/pipeline.py` comment into
  the template's `_comment`.

## P3 in the prodtools repo

On the local `main` of `muse_050125/prodtools`, on its own branch, pushed
only on a go-ahead.
- **`cancel_run(name, run_as="self")`**, a write tool:
  - grid: `jobsub_rm` of the receipt's `jobid`, as the user;
  - local: SIGTERM to the receipt's `pid`, which since P2 stops runlocal and
    every job it started. Refused when the receipt's `host` is not this
    host, or when `/proc/<pid>/cmdline` does not name the run's directory
    (the same guard `run_status` uses).
  - It writes `cancelled_utc` to the receipt atomically. Cancelling a
    cancelled run returns its state again; cancelling a finished run
    (`done`, `short`, `failed`) is refused.
- **`run_status`** reports `state: "cancelled"` for a receipt with
  `cancelled_utc`, plus the `jobs` block when one can be read.
- Unit tests in `test/test_unit.py`, run as that repo runs them.

## Failures

Every failure is loud and says why. A missing number is never replaced by
zero.

| Failure | Caught | Result |
|---|---|---|
| A study without `quorum` on a prodtools step, `njobs` over 200, a bad `fatal_log_codes` | at load | refused, naming the field |
| A config name with characters other than letters, digits and `_` | at `submit` | the step fails, naming the character |
| A prodtools server will not start or lacks a tool | `check_kits` at launch | the launch is refused |
| `--executor local` with a kit that cannot run locally; `--parallel` with `grid` | at launch | refused |
| Resume with a different executor | at launch of the point | refused; nothing runs |
| Ticket under 4 h, executor `grid` | at launch | refused |
| Same name, different params | at `submit` | the step fails, naming both digests |
| `submit_once` times out | at `submit` | the receipt is adopted if it exists; otherwise the step fails and a rerun submits again |
| Below `quorum`, or no job succeeded | completion check | `failed`, with the counts |
| Outputs still missing 30 min after the jobs ended | completion check | `failed` |
| A fatal log code, or a job with no log | completion check | `failed`, naming the code or the job |
| `run_status` says `unknown` for 6 h | `status` | `failed` |
| One step fails | `run_steps` | the others are cancelled where the kit can; `broken.txt` names the first failure |

## Testing

- **Adapter unit tests** (`tests/test_prodtools_adapter.py`), against a
  scripted fake of the two prodtools servers:
  - submit: a fresh record; the same digest again; a different digest; a
    crash in `submitting` with and without a receipt; a receipt stuck in
    `submitting`; a timeout followed by adoption;
  - every row of the status table, including 6 h of `unknown`;
  - the completion checks: below `quorum`, zero ok, the stage-out wait and
    its 30 min limit, a log-scan hit, a successful job with no log, a
    failed job with no log;
  - results FileRefs and metadata; `results` before `completed` refused;
  - the code tarball: its contents, and reuse by digest;
  - staging: hard links, a refused copy on `grid`, a copy on `local`, a
    non-`file://` input refused;
  - config names refused; the entry for each of the three foilspf stage
    templates.
- **Contract check against the real servers:** when
  `AUTORESEARCH_PRODTOOLS` is set, the arguments the adapter sends are
  validated against the real tools' input schemas from `tools/list`;
  skipped otherwise.
- **Engine tests on toykit:** cancelling the other steps, including a step
  stopped before it submitted; backoff timing through the injected pause;
  executor refusals and a resume with another executor; a zero-knob study
  through `study_run`, and the `--x`, `study_loop` and pipeline refusals;
  the ticket check; the three-way runner rule.
- **Registry and loader:** `required_fixed`, `job_count`, `string_list`,
  and the updated specs loading.
- **Goldens:** a to e pass, updated only where they record
  `elebeam_flash`'s quorum.
- **P3:** unit tests in the prodtools repo.

Command: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`

## Acceptance

In this order:
1. **Dry run.** For gridphaseA01's config, the adapter renders the entries
   for `mubeam`, `mustops_ce` and `elebeam_flash`. Each equals the
   pipeline's `state/<stage>_entry.json` except for the code tarball path
   and, for `mustops_ce`, the staged input directory; the `submit_once`
   arguments (`desc`, `dsconf`, `run_as`) match what the pipeline passed.
2. **Local.** `tests/fixtures/engine_studies/prodtools_smoke.json`, a
   zero-knob study: a fixed geometry, `mubeam` with 1 job of 200 events,
   then `mustops_ce` with 1 job reading its output, objective
   `mustops_ce.njobs_ok`. `graph.study_run --executor local` lands one row.
   The run also records how long the two prodtools servers take to start.
3. **Grid.** The same study with `--executor grid`, 1 job per step, lands
   one row; then one extra `submit` of a throwaway step is cancelled with
   `cancel_run` and reads `cancelled`. This step needs the operator's
   go-ahead before it submits.

## Out of scope

- C2: foilspf on the engine; `offline_preflight`; the sob and flash
  analyses in anakit and the anakit adapter; the campaign-loop follow-ups
  (the `measure_sha` launch check, preflight on resume, orphaned points as
  pending, a loud `STOP` refusal, early picker failure, ticket renewal).
- C3: deleting the pipeline.
- A file pattern on `files_from` (from the POMS review,
  `wiki/external/poms-chained-workflows.md`): not needed while each stage
  template names one `output_glob`.
- Pushing prodtools P1, P2 or P3 upstream.

## Open questions

1. Whether q children, each starting its own two prodtools servers, brings
   back the NFS lock wedge. The local acceptance run measures startup; the
   fallback, one server shared by the children, needs http transport and
   is not in C1.
2. The prodtools code cache (`/exp/mu2e/data/users/<you>/prodtools/code/`)
   gains one unpacked tree (~17 MB) per config and is never cleaned. That is
   fine for a campaign of hundreds of points; a cleanup rule is future
   prodtools work.
