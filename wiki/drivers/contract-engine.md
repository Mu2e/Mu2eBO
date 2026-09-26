---
type: driver
title: Contract engine (Phase B)
description: kits.toml native kits over stdio MCP (KitClient), the evaluator
  contract (NativeKit, check_kits), run_steps (one scheduler node,
  state-file resume), v2 rows with measure_sha, graph.study_run /
  graph.study_loop; toykit Branin acceptance in 28.7 s; C1 prodtools
  adapter (`core/adapters/`), --executor, zero-knob studies
status: active
timestamp: '2026-09-25'
---

# Contract engine (Phase B)

## Summary
The generic-study engine that runs a study whose kits all speak the
evaluator contract (`submit`/`status`/`results`, plus optional
`check`/`describe`/`cancel`) over stdio MCP. A study's steps are declared
in its schema-2 JSON (`mode_specs/<name>.json`, data, not code); the
engine drives them through `core/kits.py`'s
`KitClient`, `core/contract.py`'s `NativeKit`/`KitSet`/`check_kits`, and
`core/scheduler.py`'s `run_steps`, then scores and appends a v2 leaderboard
row (`core/score.py`, `core/leaderboard.py`). `graph/study_run.py` runs one
point; `graph/study_loop.py` runs a campaign of them through the existing
rolling pool (`graph/pool.py`). `tests/toykit.py` is both the reference
kit implementation and the CI engine: a full Branin/Currin acceptance
campaign (q=2, 8 evaluations) runs end to end from a JSON file alone in
28.7 s. Design: `docs/superpowers/specs/2026-09-23-generic-study-design.md`.
Phase C1 (2026-09-25, branch `generic-study-phase-c1`) gave `prodtools`
an adapter (below), so a zero-knob prodtools study —
`tests/fixtures/engine_studies/prodtools_smoke.json`, the Phase C1
acceptance study — now runs on the engine too. `foilspf` and its
siblings still run on the pipeline (`core/bo_driver.py`,
[closed-loop-runner](/drivers/closed-loop-runner.md)), because their
other kits (`offline_preflight`, `ce_sensitivity`,
`flash_edep_per_pot`) have no adapter yet — that's Phase C2.

## Key facts

**Registry (`kits.toml`, `core/kit_config.py`)**
- `kits.toml` is the registry of native contract kits: one TOML table per
  kit, every key required and unknown keys rejected (ADR-0002) —
  `command`, `env_passthrough`, `set`, `study_keys`, `fixed_keys`,
  `accepts_lists`, `check`, `launch_stagger_s`, `poll_s`, `timeouts`
  (`core/kit_config.py:KEYS`).
- `command` and `set` values may hold the tokens `${PYTHON}` (the running
  interpreter, `sys.executable`), `${REPO_ROOT}` and `${DATA_ROOT}`
  (`core/paths.py`), or `${NAME}` for any other environment variable,
  which must already be set — resolved only when the kit starts, never at
  import (`core/kit_config.py:resolve`).
- The only entry as of 2026-09-25 is `[toykit]`: command
  `${PYTHON} ${REPO_ROOT}/tests/toykit.py`, `set` pins
  `TOYKIT_STATE_DIR=${DATA_ROOT}/toykit`, `poll_s = [0.1, 2.0]` (grid kits
  are expected at 30 s–10 min), `check = true`, `launch_stagger_s = 0`.
- `core/kit_registry.py` merges `kits.toml`'s native kits (`engine=True`)
  with four declared kits — `prodtools` (Phase C1: `engine=True,
  pipeline=True`, driven by its adapter below) and `offline_preflight`,
  `ce_sensitivity`, `flash_edep_per_pot` (still `engine=False,
  pipeline=True` — Phase C2); a name clash between the two raises at
  import.
- **`kits.toml` is parsed when `core.kit_registry` is imported**
  (`NATIVE = load_kit_configs()`), and `core.study` and `core.modes` import
  it, so a `kits.toml` error breaks the pipeline's imports too
  (`graph.run`, `graph.closed_loop`, the surrogate MCP server), not just
  the engine's.
- **Routing, as the code enforces it (the three-way rule, Phase C1):** a
  study runs on the engine when the engine can drive every kit it names,
  otherwise on the pipeline when the pipeline can; one neither runner can
  drive whole is refused, and so is a pipeline study with no knobs
  (`core/modes.py:runs_on_engine`); a pipeline study must also be layout
  `"v1"` (`core/study_compat.py`). All these refusals happen at
  `core.modes` import, so one such study file in `mode_specs/` or on
  `$AUTORESEARCH_STUDY_PATH` stops every command for every study
  (`mode_specs/README.md`, "Engine studies").
- **Why `env_passthrough` exists:** the MCP SDK's
  `mcp.client.stdio.get_default_environment()` passes only a short
  allowlist of variables to the child process, so any kit that needs more
  (a Kerberos cache, a token file, …) must name them in `env_passthrough`
  in `kits.toml`; a missing one is a start-time error naming the kit and
  the variable, raised when the kit starts (at `check_kits`, at
  `graph.study_run`'s kit start check, or at the first call), never at
  import (`core/kit_config.py:KitConfig.resolve_env`, surfaced as a
  `KitError` from `core/kits.py:KitClient.start`).

**KitClient (`core/kits.py`)**
- One MCP session per kit per child, run on a private asyncio loop in a
  daemon thread (a nested `asyncio.run` under a caller's own loop is
  impossible, and anyio cancel scopes must be exited by the task that
  entered them).
- **Calls run from several threads concurrently on one session; the lock
  (`self._lock`) covers only starting the server and scheduling the MCP
  call, never the wait for its result** — otherwise a slow call from one
  thread would hold every other thread's `timeout_s` hostage, and
  `run_steps` runs its ready steps on separate threads sharing one
  `KitSet`.
- A **generation counter** (bumped on every successful start) is captured
  under the lock at the moment a call is scheduled; if that call later
  fails with the server "lost", `_lost()` only tears the session down when
  its captured generation is still current. A stale generation means some
  other call already respawned the server, so this call's own failure must
  never tear the new one down (`core/kits.py:KitClient._lost`).
- **What counts as a lost server:** an `MCPError` with code
  `CONNECTION_CLOSED`, or any non-`MCPError` exception raised while
  waiting on the call (`core/kits.py:KitClient._call`'s bare
  `except Exception`, e.g. a raw transport failure), calls `_lost` and
  closes the session so the next call respawns the server. An `MCPError`
  with any other code (not a timeout — bad params, a tool-side crash the
  server itself reported at the protocol level) is a plain `KitError`
  with the session **kept** — the server answered, it didn't disappear.
  `REQUEST_TIMEOUT` raises `KitTimeout` with the session also **kept**
  (the server may still be working on it).

**Retry policy (`core/contract.py:NativeKit`)**
- `ATTEMPTS = 3`. `status`, `results`, `check` and `describe` retry any
  `KitError` (transport failure, timeout, "server lost") up to 3 times,
  and also retry a `KitToolError` (the server explicitly refused the
  call) since they're read-only and safe to repeat.
- `submit` retries `KitError` (so a dead server is restarted and the
  submit resent — safe, since submit is idempotent by name) but never
  retries a `KitToolError` (a refused submit under the same name with
  different params must never be repeated).
- `cancel` gets exactly 1 attempt, no retries of either kind.
- **Backoff (Phase C1):** `call_with_retries` pauses `RETRY_PAUSES_S =
  (5.0, 20.0)` s after the 1st and 2nd failed attempt, so a credential
  blip lasting seconds doesn't fail the step.
- **`check_kits(study, campaign)`** is the launch check: it opens every
  kit the study names, confirms it offers `submit`/`status`/`results`
  (plus `check` when it's the preflight kit), that it reports a
  `serverInfo.version` (else `measure_sha` can't fingerprint it), and — if
  it offers `describe` — that the study's params/metrics match what the
  kit accepts/returns. It starts each kit exactly once; any problem is
  collected and returned as a list, and `graph/study_loop.py` refuses to
  launch (exit 2) if the list is non-empty.
- **`graph/study_run.py` runs a start check, not the full `check_kits`:**
  after its other refusals and before anything is written for the point,
  it starts every kit the study names (`kit_registry.kits_of`) through the
  child's own `KitSet` (`kits.get(name).tools`), so the steps reuse those
  servers. A kit that won't start is refused (exit 2) naming the kit and
  the error — no submit, no `point.json`, no `broken.txt` — so an
  environment problem is never recorded as a failed evaluation.

**`run_steps` (`core/scheduler.py`)**
- One LangGraph node (`run_steps`, called from
  `graph/study_graph.py:node_run_steps`) schedules every step of a point,
  rather than one graph node per step — LangGraph finishes a whole
  superstep before starting the next, so a per-step node would make
  `mustops_ce` wait for `elebeam_flash` even after `mubeam` finished
  (the wait today's `presubmit_after` works around). Ready steps run
  concurrently in a `ThreadPoolExecutor`.
- Each step is driven from its own state files under
  `GRID_DATA_ROOT/<config>/state/` (`core/paths.py:GRID_DATA_ROOT`,
  `graph/study_run.py:main`), which is what makes a killed child resumable
  with no second submit: `<step>_results.json` exists → adopt and skip;
  `<step>_cluster.txt` exists → poll that handle; neither → `submit` then
  write the handle.
- **`broken.txt` is written at the FIRST step failure**
  (`step <name>: <message>`, `core/scheduler.py:run_steps`), the moment
  that failure is known — not after every step drains. Steps already
  running (siblings of the failed one) are allowed to finish; no new
  steps start.
- An unexpected exception in a step (a bug, e.g. an `OSError` from
  `write_atomic`, as opposed to a `KitError`/`ContractError`/`KeyError`/
  `ValueError` the step function itself catches and reports as a
  `StepOutcome`) is logged at once through the injected `log` callable
  (default `print`, i.e. stdout — `core/scheduler.py:run_steps`, no
  `sys.stderr` write), recorded in `broken.txt` the same way, and
  **re-raised only after every already-running sibling has finished** —
  so the child still exits non-zero on a programming error, but doesn't
  kill in-flight grid work to do it.

**A broken point is terminal**
- `graph/study_run.py:main` refuses (exit 2) any config whose
  `GRID_DATA_ROOT/<config>/state/broken.txt` already exists, printing
  the message it recorded and how to retry (below).
- `graph/study_loop.py:busy_reason` treats `broken.txt` the same as an
  existing leaderboard row: a resolved name from a prior run under this
  `--name-prefix`, and skips to the next index rather than relaunching it.
- **To retry a point:** the operator deletes its `broken.txt` — that is
  enough. A rerun then re-executes `derive`/`render`, **re-runs
  `preflight`** (see Open questions), and `run_steps` adopts any existing
  `<step>_cluster.txt` handles it finds (polling the same handle rather
  than submitting again) and any `<step>_results.json` already written —
  so a retry after a transient failure costs no second submit.
- **A step the kit itself reported `failed` stays failed on retry:** the
  handle is deterministic (`<config>.<step>`), so polling it — or even
  deleting the whole state dir and resubmitting the same params — gets
  the kit's existing, failed job back. Re-evaluating such a point needs a
  new config name (`graph/study_run.py`'s refusal text says the same).

**`measure_sha` (`core/study.py:Study.measure_sha`, `core/score.py`)**
- SHA-256 over `measure_basis` (`derive`, `geom`, all of `kits`, each
  step's `kit`/resolved `entry`/`files`/`files_from`/`params`/`fixed`,
  each objective's `metric` and `transform`, and each extra metric's
  `metric` only — an `ExtraMetric` has no `transform` field —
  `core/study.py:_EXTRA_METRIC`, `_measure_basis`) plus **the reported
  version of every kit a step runs on**.
- It leaves out `note`, knob bounds, `fmt`, `noise`, `constraints` and
  `leaderboard` — nothing that doesn't change what a measurement means.
- The **preflight kit's version is not hashed** (it gates a point but
  produces no numbers for it); only its settings, which live in `kits`
  and so are already covered.
- A kit's version is its `serverInfo.version` at MCP `initialize`
  (`core/kits.py:KitClient._serve`); `check_kits` refuses launch if any
  kit reports none.
- `core/leaderboard.py:Leaderboard._check_v2` refuses an append whose
  `measure_sha` differs from what's already on a v2 board, quarantining
  the row (`<board>.quarantine.tsv`) rather than mixing measurements.
- **A resume is guarded too, one step earlier:** `point.json` records
  `measure_basis_sha` (`core/study.py:Study.measure_basis_sha`, the
  SHA-256 of `measure_basis` alone — the part of `measure_sha` the study
  file controls; kit versions are known only once a kit starts). Rerunning
  a killed point after the study's measurement changed raises
  `PointMismatch` in `derive` (exit 2, nothing submitted or written):
  otherwise the rerun would poll the old handle, measured the old way, and
  stamp its numbers with the edited study's `measure_sha` — on a fresh
  board nothing else would catch it. A `point.json` without the field
  (written before 2026-09-25) is refused the same way, never assumed
  unchanged (`graph/study_graph.py:node_derive`).

**v2 rows**
- Column order: `config`, each knob, each objective, each extra metric,
  each extra column, then `handles`, `spec_sha`, `measure_sha`, `time`
  (`core/leaderboard.py:Leaderboard.header`, `V2_META`).
- `handles` is `step=handle` pairs, comma-joined and sorted by step name
  (`core/score.py:row_meta`), e.g. a one-step `toykit` study's point `p1`
  records `toy=p1.toy`.
- A v1 board has none of the `V2_META` columns; `append()` refuses to
  attach `meta` to a v1 row and refuses a v2 row missing any of them.

**`graph.study_run`**
- One point end to end: `derive → render → preflight → run_steps → score`
  (`graph/study_graph.py:build_study_graph`), invoked as
  `python -m graph.study_run --study S --config C --campaign K --x=v1,v2,...`.
- **Exit 0:** the point ran — either a leaderboard row landed, or
  `broken.txt` says why not. **Exit 2:** refused before anything ran (an
  unknown or non-engine study, `x` outside the knob box or of the wrong
  length, a missing or unknown `--context`, a broken point, a kit that
  won't start, a config name already claimed by a different point in
  `point.json`, or a `point.json` whose `measure_basis_sha` is missing or
  differs from the study's). Anything else is a crash.
- Preflight params follow the same clash rule as a step's
  (`core/scheduler.py:merge_params`, shared by `step_params` and
  `graph/study_graph.py:node_preflight`): a param mapped from the point may
  not share a name with a kit setting (or a step's fixed value) — a
  `ValueError` naming the param, which breaks the point at preflight
  rather than letting the setting silently replace the point's value.
- Phase C renames this module to `graph.run` when the pipeline path is
  deleted.

**`graph.study_loop`**
- One campaign: `python -m graph.study_loop --study S --q N --max-evals M
  --picker P --name-prefix NAME`, wired onto the existing rolling pool
  (`graph/pool.py:run_rolling`) via `graph/study_loop.py`'s
  `make_run_child`/`make_pick_source`.
- `--context` is validated once at launch with `graph/study_run.py:
  parse_context` (the function each child uses), then `check_kits` must
  pass, before anything launches (exit 2 otherwise, naming each problem).
  Without the launch check a bad `--context` made every child refuse and
  the pool abort after max(q, 2) of them.
- Each child is launched **unbuffered**
  (`python -u -m graph.study_run ... --x=...`), logging to
  `GRAPH_DATA/closed_loop_logs/<child>.log` (`graph/study_loop.py:
  make_run_child`).
- `busy_reason(name, board_names)` decides which names a relaunch under
  the same `--name-prefix` must skip: a leaderboard row or `broken.txt`
  means a prior run RESOLVED that name; `point.json` or any
  `*_cluster.txt` means a child may still be in flight, or was abandoned —
  either way the name is skipped, never relaunched under the same name.
  Its RECOVERY text recommends another `--name-prefix`: removing the state
  dir is safe only when nothing runs the child AND no `*_cluster.txt` was
  ever written, because a freed name is re-picked with a new x and the kit
  refuses the same `<config>.<step>` handle with other params (→
  `broken.txt` and an abort-streak increment).
- **Rows are counted by name against the live board**
  (`{p.cfg for p in board_for(study).load()}`), never by reading
  `evaluate_result.json`'s `row_appended` flag — a row that landed but
  whose recording process died before it could report `row_appended` must
  still count.
- To stop launching without killing what's running, touch
  `GRAPH_DATA/<name-prefix>/STOP`; the pool checks it before every launch
  and drains the in-flight set once it's set.
- Phase C folds this module into `graph/closed_loop.py`.

**`toykit` (`tests/toykit.py`)**
- The reference contract kit and the CI engine: a stdio MCP server
  offering the full contract (`submit`/`status`/`results`/`check`/
  `describe`/`cancel`) plus `debug_*` tools the client tests use.
- Jobs are files under `$TOYKIT_STATE_DIR` (which `kits.toml` pins to
  `${DATA_ROOT}/toykit`), so a restarted child talking to a freshly
  spawned server process still finds the job it submitted before being
  killed.
- `FAILS = ("failed", "cancelled", "bad_state", "missing_metric",
  "nonpositive")` — a study's `fixed.fail` picks one: `failed`/`cancelled`
  make `status` report that state; `bad_state` reports a state outside
  the contract (`"bogus"`, exercising `ContractError`); `missing_metric`
  drops `currin` from `results`; `nonpositive` zeroes it (exercises the
  log10-transform failure).
- `FUNCTIONS = ("branin_currin", "reject")`: `branin_currin` scores
  `branin`/`currin`/`n_inputs`; `reject`'s `check` always fails `ok`
  (exercises a rejected preflight).

**Acceptance timing (Task 10, `tests/test_study_loop.py:
TestBraninCampaign.test_eight_points_in_under_a_minute`)**
- `tests/fixtures/engine_studies/branin.json`: 2 knobs, 2 objectives
  (Branin min, Currin min+log10), 1 constraint, layout v2, one `toykit`
  step. `python -m graph.study_loop --study branin --q 2 --max-evals 8
  --picker budget_sob` ran end to end (all 8 points, real GP picks) in
  **28.7 s** — the design's acceptance bar was "under a minute".

**prodtools kit (Phase C1, `core/adapters/prodtools.py`)**
- `ProdtoolsKit` is an in-process `Adapter` (`core/contract.py:ADAPTERS`),
  not a native `kits.toml` entry: it speaks the contract itself, over two
  `KitClient`s onto the `prodtools_write`/`prodtools_read` MCP servers
  (`kits.toml`'s `[servers.prodtools_write]`/`[servers.prodtools_read]`,
  Task 2). `core/adapters/__init__.py:register_all` registers it (and
  every future adapter) at import.
- **Record file:** `<GRID_DATA_ROOT>/<config>/prodtools/<step>/record.json`,
  written before the submit (`state="submitting"`) and updated after
  (`"submitted"`, then a `verdict`), so a killed child's rerun adopts the
  run by digest instead of resubmitting it. Same params/files/inputs/
  executor → adopt; different → refused; a receipt caught stuck in
  `submitting`/`building` fails loudly (whether the jobs ever reached the
  grid can't be told).
- **The entry template arrives as `params["entry"]`:** `core/scheduler.py:
  step_params` resolves the step's stage template
  (`study.entry_template`) and hands it to any kit whose `KitDecl.
  uses_entries` is set (Task 1); `prodtools_entry.entry_for_step`
  substitutes `{cfg}`/`{geom}` in it and renders the json2jobdef entry.
- **`dsconf_fmt`:** a stage template's `desc_fmt`/`dsconf_fmt` name the
  json2jobdef `desc`/`dsconf`; every prodtools template in
  `stage_entries/` uses `dsconf_fmt: "Run1Bak_{cfg}"`.
- **200-job cap:** `kit_registry.MAX_JOBS_PER_STEP = 200` refuses a
  larger `fixed.njobs` at study-load time, because prodtools'
  `run_status` (`INDEX_CAP` in its `tools/runs.py`) lists at most 200
  jobs' outputs — a bigger step would read a silently truncated list.
- **`quorum` is required** in every prodtools step's `fixed`
  (`KitDecl.required_fixed`); below it, `_complete` fails the step
  (`{ok}/{njobs} jobs ok, below quorum {quorum}`).
- **The log scan:** `_scan_logs` requires every successful job to have a
  `.log` (else fail — the scan couldn't run), then greps every log under
  the run's outstage (grid) or run dir (local) for each of
  `kits.prodtools.fatal_log_codes`; the first match fails the step
  (foilspf: `GeomSolids1001`).
- **Timeouts:** `run_status` reporting `unknown` fails the step after
  `UNKNOWN_LIMIT_S = 6 h`; outputs still missing from disk after the jobs
  ended fail it after `STAGEOUT_LIMIT_S = 30 min` (both counted from the
  first time the condition was seen, stamped in the record).
- **The submit lock:** a grid `submit_once` is taken under
  `/tmp/mu2e_submit.<user>.lock` (`SUBMIT_LOCK`) — the same file
  `core/pipeline.py`'s `_submit_lock` uses, so both runners serialize
  their grid submits on a host
  ([concurrent-token-contention](/incidents/concurrent-token-contention.md)).
- **No token refresh in the adapter:** the adapter never renews a
  Kerberos ticket; `graph/study_run.py:launch_refusals` refuses a grid
  launch up front when the study's kit(s) set `REQUIRES_KERBEROS` and
  under 4 h remain (`core/contract.py:requires_kerberos`), and the write
  server's own `run_as="self"` path is what actually renews it.
- **`--executor`/`--parallel`:** `graph.study_run --executor grid|local`
  and `graph.study_loop --executor ... --parallel N` (local only, 1..16)
  choose `ProdtoolsKit.executor`/`.parallel`, which pick `submit_once`
  (grid) vs `run_local` (local) and the poll cadence
  (`core/adapters/prodtools.py:_POLL`); recorded in `point.json`, not
  part of `measure_sha`. Worked example: `python -m graph.study_run
  --study prodtools_smoke --config smoke01 --campaign smoke --executor
  local`.
- **Zero-knob studies:** `tests/fixtures/engine_studies/prodtools_smoke.json`
  has `"knobs": []` — `graph.study_run` runs it with no `--x`;
  `graph.study_loop` refuses it (one-shot studies have no campaign to
  loop); the surrogate skips them (`core/modes.py`, Task 5).
- **Cancel of the other steps:** `core/scheduler.py:run_steps` cancels
  every already-submitted sibling of a failed/cancelled step whose kit
  offers `cancel` (`ProdtoolsKit.cancel` calls the write server's
  `cancel_run`, offered only when that server has the tool); a step that
  hasn't submitted yet just sees the stop event and never does; a failed
  cancel attempt is logged and that step runs to completion.
- **`cancel_run` (Task 9, P3):** on the prodtools side, a local branch
  `cancel-run` (worktree off local main `6640e6e`, not merged or pushed)
  adds the write tool `cancel_run(name, run_as="self")` plus
  `bin/runcancel`/`utils/runcancel.py`: grid via `jobsub_rm -G mu2e
  --jobid <cluster>@<schedd>`, local via SIGTERM guarded by
  `utils/run_receipt.pid_alive` (one shared `/proc` liveness check); the
  receipt records `cancelled`/`cancelled_from`/`cancelled_utc`;
  `run_status` needed no change.

## Cross-links
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md) (the
  pipeline campaign runner this engine sits alongside, not on top of, in
  Phase B), [surrogate](/drivers/surrogate.md) (the MCP door that reads
  the same v2 boards through `core/botorch_predict.py`),
  [tests](/drivers/tests.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md)
  (the pipeline's load-bearing constraints — the engine reuses its rolling
  pool but not its checkpointing or barrier logic)
- Source files: `kits.toml`, `core/kit_config.py`, `core/kit_registry.py`,
  `core/kits.py`, `core/contract.py`, `core/scheduler.py`,
  `core/study.py`, `core/score.py`, `core/leaderboard.py`, `core/boards.py`,
  `graph/study_graph.py`, `graph/study_run.py`, `graph/study_loop.py`,
  `graph/pool.py`, `tests/toykit.py`, `core/adapters/__init__.py`,
  `core/adapters/prodtools.py`, `core/adapters/prodtools_entry.py`,
  `tests/fixtures/engine_studies/prodtools_smoke.json`
- Design: `docs/superpowers/specs/2026-09-23-generic-study-design.md`

## Open questions / TODO
P1 spike (2026-09-25): a `dir:` staging entry goes through prodtools'
`submit_once` end to end unchanged (entry parse, cnf build with no SAM
lookup, `-N njobs`, `dir:` preflight that only stats files, no ledger,
worker resolves `xroot://…/pnfs/…` literally with `track_parents=False`,
`run_status` reads only the cnf and exit codes). Checked by a dry run on
gridphaseA01's real mustops_ce entry. What the Phase C prodtools adapter
must still handle:
- P1 part 1 is still needed: `_select_push_params`
  (`prodtools_mcp_write/tools.py:91-94`) refuses an entry with `code` and
  no `simjob_setup`. Designed 2026-09-25 (prodtools branch
  `code-entries-run-local`, spec
  `docs/superpowers/specs/2026-09-25-code-entries-and-run-local-design.md`),
  with P2 `run_local` in the same spec. **No runner change and no FHiCL
  hook needed:** a cvmfs Musing's `setup.sh` and a `muse tarball`
  `Code/setup.sh` are the same five-line script, so passing the unpacked
  tarball's `Code/setup.sh` as `run_cli`'s `simjob_setup` works as it
  does for a Musing. Our tarball's `setup_post.sh` already prepends
  `$CODE_DIR` to `FHICL_FILE_PATH`. Our per-config tarballs are 15 MB
  (17 MB unpacked).
  **Implemented 2026-09-25 and merged into the LOCAL `main` of
  `muse_050125/prodtools` at 6640e6e (not pushed to Mu2e; the branches
  were deleted). The prodtools MCP servers run that checkout, so they get
  it after a restart.** PR 1 content = (06fed73: `utils/code_cache.py`, content-
  keyed unpack under `/exp/mu2e/data/users/<you>/prodtools/code/<sha256>/`;
  `submit_once` takes code entries; `push_cnf` refuses them). PR 2 content =
  (6640e6e: `json2jobdef --once --local`, the `run_local`
  write tool with `parallel` capped at 16, the local branch of
  `run_status`, and runlocal stopping its jobs on SIGTERM/SIGINT/SIGHUP).
  A live check on mu2esrv01 with gridphaseA01's mubeam entry passed: cnf
  built from the tarball's environment; a 10-event `run_local` reached
  `done` with 6 outputs; `kill <pid>` left no process of the run. The
  build and review record is in
  `/exp/mu2e/data/users/oksuzian/prodtools_p1p2_sdd_record/`. For the
  adapter: `run_local` refuses `firstjob` windows, and a local run and a
  grid run of one desc+dsconf share a run name, which is used once.
- `submit_once`, `run_receipt` and `run_status` exist only in the prodtools
  checkout (commits 623dca6 and 9713171 on mu2e/main, 2026-09-20), not in
  v3.2.0 or cvmfs `current` (v3.3.4); the MCP server runs its own
  checkout's `bin/json2jobdef`.
- Set `"sequential_aux": true` on staged stages, or jobs sample the staged
  files with replacement (see [pipeline](/drivers/pipeline.md)).
- The outstage moves to `workflow/<dsconf>/outstage` (no wfproject is
  passed), so harvest must take the output paths from the receipt.
- A desc+dsconf pair can be submitted once (`run_receipt.py:75`): today's
  `submit --force` under the same dsconf is refused.
- Never set `copy_input`: the worker's local-copy path does a SAM locate.

Phase C split (operator, 2026-09-25): C1 the prodtools kit, C2 foilspf on
the engine, C3 delete the pipeline. C1 spec:
`docs/superpowers/specs/2026-09-25-prodtools-kit-design.md` (branch
`generic-study-phase-c1`). Decided there: `--executor grid|local` is a
runner flag outside `measure_sha`; below-`quorum` fails the step and
`quorum` is required; the adapter is in-process (`core/adapters/`);
prodtools gains P3 `cancel_run`; and the sob and flash analyses go to
anakit in C2, not local plugins (settles the design's Open question 2).

Phase C follow-ups found in review (2026-09-25):
- No launch-time check that the board's `measure_sha` matches the study's
  current one — a child runs its steps and is refused only at append.
  `graph/study_loop.py`.
- A resumed child re-runs preflight; a transient `check` failure then
  marks a point broken while its grid job still runs. `graph/study_graph.py`.
- ~~Sibling steps of a failed step run to completion (the contract's
  `cancel` is unused) — grid hours spent on a dead point.
  `core/scheduler.py`.~~ **Done in C1:** `run_steps` cancels every running
  sibling of a failed/cancelled step whose kit offers `cancel` (a failed
  cancel is logged and that step runs to completion); a step that has not
  submitted yet never does (see "prodtools kit (Phase C1)" above).
- ~~`NativeKit` retries have no backoff; a status failure that lasts
  seconds (a credential blip) fails the step. `core/contract.py`.~~
  **Done in C1:** `call_with_retries` pauses `RETRY_PAUSES_S = (5.0,
  20.0)` s after the 1st and 2nd failed attempt.
- ~~No credential renewal / 4 h ticket gate for engine campaigns.
  `graph/study_loop.py`.~~ **Done in C1:** a grid launch whose kit sets
  `REQUIRES_KERBEROS` is refused up front (`graph/study_run.py:
  launch_refusals`, `core/contract.py:requires_kerberos`) unless a
  ticket with at least 4 h left is held; the adapter itself never
  refreshes one.
- After a runner restart, orphaned in-flight children's x are not passed
  to the picker as pending. `graph/study_loop.py`.
- A leftover `STOP` file makes a relaunch under the same prefix launch
  nothing, silently. `graph/study_loop.py`.
- A picker failure mid-campaign surfaces only after in-flight children
  finish (inherited from `graph/pool.py`).
