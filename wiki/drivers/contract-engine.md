---
type: driver
title: Contract engine (Phase B)
description: kits.toml native kits over stdio MCP (KitClient), the evaluator
  contract (NativeKit, check_kits), run_steps (one scheduler node,
  state-file resume), v2 rows with measure_sha, graph.run /
  graph.closed_loop; toykit Branin acceptance in 28.7 s; C1 prodtools
  adapter (`core/adapters/`), --executor, zero-knob studies; C2a
  offline_preflight adapter (the geometry pre-check from the code
  tarball), dsconf study setting; C2b anakit adapter (one server per
  step), step_problems launch hook, <study>_ax engine twins on MDC2025ax;
  C3 (2026-09-28) deletes the pipeline — the engine is the only runner
status: active
timestamp: '2026-09-29'
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
row (`core/score.py`, `core/leaderboard.py`). `graph/run.py` runs one
point; `graph/closed_loop.py` runs a campaign of them through the existing
rolling pool (`graph/pool.py`). `tests/toykit.py` is both the reference
kit implementation and the CI engine: a full Branin/Currin acceptance
campaign (q=2, 8 evaluations) runs end to end from a JSON file alone in
28.7 s. Design: `docs/superpowers/specs/2026-09-23-generic-study-design.md`.
Phase C1 (2026-09-25, branch `generic-study-phase-c1`) gave `prodtools`
an adapter (below), so a zero-knob prodtools study —
`tests/fixtures/engine_studies/prodtools_smoke.json`, the Phase C1
acceptance study — now runs on the engine too. `foilspf` and its six
siblings ran on the pipeline (`core/bo_driver.py`) until Phase C3
(2026-09-28) deleted it — the seven original study files were archived
to `mode_specs/archive/` unmodified, a global constraint of Phase C2 —
but each already had an engine twin, `<name>_ax` (Phase C2b, below), that
runs the same geometry through the engine's `anakit` adapter instead of
the pipeline's harvest; the `_ax` twins are the production lines now. See
"Pipeline deleted (Phase C3)" below.

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
- `core/kit_registry.py` merges `kits.toml`'s native kits with three
  declared kits, each an in-process `Adapter` (`core/contract.py:
  ADAPTERS`): `prodtools` (Phase C1), `offline_preflight` (Phase C2a),
  `anakit` (Phase C2b) — verify with `grep -n "^    KitDecl(" core/
  kit_registry.py`. A name clash between the native and declared sets
  raises at import. `KitDecl` (`name`, `study_keys`, `fixed_keys`,
  `required_fixed`, `uses_entries`, `step_kit`, `check_kit`) has no
  `engine`/`pipeline` flags. Until Phase C3 (2026-09-28) the registry also
  declared `ce_sensitivity` and `flash_edep_per_pot`, and every `KitDecl`
  carried `engine`/`pipeline` booleans the pipeline routed on; both went
  with the pipeline.
- **`kits.toml` is parsed when `core.kit_registry` is imported**
  (`NATIVE = load_kit_configs()`), and `core.study` and `core.modes` import
  it, so a `kits.toml` error breaks every command
  (`graph.run`, `graph.closed_loop`, the surrogate MCP server), not just
  one of them.
- **Routing, as the code enforces it:** every loaded study runs on the
  engine — there is no other runner to route to since Phase C3. A study
  naming a kit that isn't in `kit_registry.KITS` is refused at load
  (`core/study.py`: `"unknown kit"`), which happens at `core.modes`
  import, so one such study file in `mode_specs/` or on
  `$AUTORESEARCH_STUDY_PATH` stops every command for every study
  (`mode_specs/README.md`, "Studies run on the engine"). Until Phase C3
  this was "the three-way rule" (Phase C1): a study ran on the engine when
  the engine could drive every kit it named, otherwise on the pipeline
  when the pipeline could, otherwise was refused, and a pipeline study
  also had to be layout `"v1"` (`core/modes.py:runs_on_engine`,
  `core/study_compat.py`) — both functions and that layout rule are gone.
- **Why `env_passthrough` exists:** the MCP SDK's
  `mcp.client.stdio.get_default_environment()` passes only a short
  allowlist of variables to the child process, so any kit that needs more
  (a Kerberos cache, a token file, …) must name them in `env_passthrough`
  in `kits.toml`; a missing one is a start-time error naming the kit and
  the variable, raised when the kit starts (at `check_kits`, at
  `graph.run`'s kit start check, or at the first call), never at
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

**Retry policy (`core/contract.py:call_with_retries`, Phase C2a)**
- `RETRY_PAUSES_S` is per contract call: `submit`, `check` and
  `describe` make 3 attempts, pausing 5 and 20 s; `status`, `results`
  and `cancel` make 5, pausing 5, 20, 60 and 180 s (about 4.5 min), so a
  point waiting hours on the grid rides out a server outage of minutes.
- A `KitError` (transport failure, timeout, "server lost") is always
  retried. A `KitToolError` (the server refused) is retried for
  `status`, `results`, `check` and `describe`, which are read-only, and
  never for `submit` (a refused submit under the same name with
  different params must never be repeated) or `cancel`.
- The prodtools adapter's `run_status` polls use the `status` budget
  from `status` and the `submit` budget when `submit` adopts a run;
  its `cancel_run` uses the `cancel` budget.
- **`check_kits(study, campaign)`** is the launch check: it opens every
  kit the study names, confirms a kit that runs a step offers
  `submit`/`status`/`results` and the preflight kit `check` (a kit used
  only for the preflight needs only `check`), that it reports a
  `serverInfo.version` (else `measure_sha` can't fingerprint it), and — if
  it offers `describe` — that the study's params/metrics match what the
  kit accepts/returns. It starts each kit exactly once; any problem is
  collected and returned as a list, and `graph/closed_loop.py` refuses to
  launch (exit 2) if the list is non-empty.
- **`graph/run.py` runs a start check, not the full `check_kits`:**
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
  `graph/run.py:main`), which is what makes a killed child resumable
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
- `graph/run.py:main` refuses (exit 2) any config whose
  `GRID_DATA_ROOT/<config>/state/broken.txt` already exists, printing
  the message it recorded and how to retry (below).
- `graph/closed_loop.py:busy_reason` treats `broken.txt` the same as an
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
  new config name (`graph/run.py`'s refusal text says the same).

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

**`graph.run`**
- One point end to end: `derive → render → preflight → run_steps → score`
  (`graph/study_graph.py:build_study_graph`), invoked as
  `python -m graph.run --study S --config C --campaign K --x=v1,v2,...`.
- **Exit 0:** the point ran — either a leaderboard row landed, or
  `broken.txt` says why not. **Exit 2:** refused before anything ran (an
  unknown study — since Phase C3 there is no "non-engine" study any more,
  every loaded study runs on the engine — `x` outside the knob box or of the
  wrong length, a missing or unknown `--context`, a broken point, a kit that
  won't start, a config name already claimed by a different point in
  `point.json`, or a `point.json` whose `measure_basis_sha` is missing or
  differs from the study's). Anything else is a crash.
- Preflight params follow the same clash rule as a step's
  (`core/scheduler.py:merge_params`, shared by `step_params` and
  `graph/study_graph.py:node_preflight`): a param mapped from the point may
  not share a name with a kit setting (or a step's fixed value) — a
  `ValueError` naming the param, which breaks the point at preflight
  rather than letting the setting silently replace the point's value.
- Renamed from `graph/study_run.py` in Phase C3 (2026-09-28), when the
  pipeline path was deleted; dated bullets elsewhere on this page that
  predate the rename still say `graph.study_run`/`graph/study_run.py`.

**`graph.closed_loop`**
- One campaign: `python -m graph.closed_loop --study S --q N --max-evals M
  --picker P --name-prefix NAME`, wired onto the existing rolling pool
  (`graph/pool.py:run_rolling`) via `graph/closed_loop.py`'s
  `make_run_child`/`make_pick_source`.
- `--context` is validated once at launch with `graph/run.py:
  parse_context` (the function each child uses), then `check_kits` must
  pass, before anything launches (exit 2 otherwise, naming each problem).
  Without the launch check a bad `--context` made every child refuse and
  the pool abort after max(q, 2) of them.
- Each child is launched **unbuffered**
  (`python -u -m graph.run ... --x=...`), logging to
  `GRAPH_DATA/closed_loop_logs/<child>.log` (`graph/closed_loop.py:
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
- Renamed from `graph/study_loop.py` in Phase C3 (2026-09-28); see
  "Pipeline deleted (Phase C3)" below.

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

**Acceptance timing (Task 10, `tests/test_closed_loop.py:
TestBraninCampaign.test_eight_points_in_under_a_minute`; the test file was
`tests/test_study_loop.py` before the Phase C3 rename)**
- `tests/fixtures/engine_studies/branin.json`: 2 knobs, 2 objectives
  (Branin min, Currin min+log10), 1 constraint, layout v2, one `toykit`
  step. `python -m graph.closed_loop --study branin --q 2 --max-evals 8
  --picker budget_sob` ran end to end (all 8 points, real GP picks) in
  **28.7 s** — the design's acceptance bar was "under a minute".

**prodtools kit (Phase C1, `core/adapters/prodtools.py`)**
- `ProdtoolsKit` is an in-process `Adapter` (`core/contract.py:ADAPTERS`),
  not a native `kits.toml` entry: it speaks the contract itself, over two
  `KitClient`s onto the `prodtools_write`/`prodtools_read` MCP servers
  (`kits.toml`'s `[servers.prodtools_write]`/`[servers.prodtools_read]`,
  Task 2). `core/adapters/__init__.py:register_all` registers it (and
  every future adapter) lazily, from `core/contract.py:_load_adapters`
  (called first by `open_kit`, `launch_stagger`, `executor_problems` and
  `requires_kerberos`), not at import — an adapter module imports
  `core.contract`.
- **prodtools replies are text only:** its read tools are declared
  `-> dict` and its write tools have no return annotation, and neither
  sets `structured_output`, so under mcp 2.x a reply carries no
  structured content. `KitClient._call` parses a non-error text reply as
  JSON and requires an object; empty/invalid JSON, a list or a scalar is
  a `KitError` naming the tool. Structured content, when present, still
  wins. `tests/textkit.py` registers tools both ways
  (`TestTextReplies` in `tests/test_kits.py`).
- **Record file:** `<GRID_DATA_ROOT>/<config>/prodtools/<step>/record.json`,
  written before the submit (`state="submitting"`) and updated after
  (`"submitted"`, then a `verdict`), so a killed child's rerun adopts the
  run by digest instead of resubmitting it. Same params/files/inputs/
  executor → adopt; different → refused; a receipt caught stuck in
  `submitting`/`building` fails loudly (whether the jobs ever reached the
  grid can't be told). The record stamps `submitting_utc` (prodtools'
  receipt format) right before the submit, and `_adopt` takes only a run
  whose `run_status` `created_utc` is at or after it: an older run means
  the config name was used before (or `record.json` was lost) and is a
  loud error, never adopted; a missing timestamp is an error too.
- **The entry template arrives as `params["entry"]`:** `core/scheduler.py:
  step_params` resolves the step's stage template
  (`study.entry_template`) and hands it to any kit whose `KitDecl.
  uses_entries` is set (Task 1); `prodtools_entry.entry_for_step`
  substitutes `{cfg}`/`{geom}` in it and renders the json2jobdef entry.
- **`dsconf` (Phase C2a):** the run label is the study setting
  `kits.prodtools.dsconf` (required, holds `{cfg}`, letters/digits/`_`
  once filled); the stage templates no longer carry `dsconf_fmt`, and
  `entry_for_step` refuses one that does.
- **200-job cap:** `kit_registry.MAX_JOBS_PER_STEP = 200` refuses a
  larger `fixed.njobs` at study-load time, because prodtools'
  `run_status` (`INDEX_CAP` in its `tools/runs.py`) lists at most 200
  jobs' outputs — a bigger step would read a silently truncated list.
- **`quorum` is required** in every prodtools step's `fixed`
  (`KitDecl.required_fixed`); below it, `_complete` fails the step
  (`{ok}/{njobs} jobs ok, below quorum {quorum}`).
- **The log scan:** `_scan_logs` requires every successful job to have a
  `.log` (a missing one first waits out the same 30-min stage-out window
  as a missing output, then fails — the scan couldn't run), then greps
  every log under the run's outstage (grid) or run dir (local) for each
  of `kits.prodtools.fatal_log_codes`; the first match fails the step
  (foilspf: `GeomSolids1001`).
- **Timeouts:** `run_status` reporting `unknown` fails the step after
  `UNKNOWN_LIMIT_S = 6 h`; outputs still missing from disk after the jobs
  ended fail it after `STAGEOUT_LIMIT_S = 30 min` (both counted from the
  first time the condition was seen, stamped in the record). Every tool
  the adapter calls needs a timeout in its server's kits.toml table
  (`TOOLS`: write submit_once/run_local/cancel_run, read run_status);
  `ProdtoolsKit.__init__` refuses a config missing one.
- **The submit lock:** a grid `submit_once` is taken under
  `/tmp/mu2e_submit.<user>.lock` (`SUBMIT_LOCK`) — the same file
  `core/pipeline.py`'s `_submit_lock` uses, so both runners serialize
  their grid submits on a host
  ([concurrent-token-contention](/incidents/concurrent-token-contention.md)).
- **No token refresh in the adapter:** the adapter never renews a
  Kerberos ticket; `graph/run.py:launch_refusals` refuses a grid
  launch up front when the study's kit(s) set `REQUIRES_KERBEROS` and
  under 4 h remain (`core/contract.py:requires_kerberos`). The servers
  get `KRB5CCNAME` and `XDG_RUNTIME_DIR` (kits.toml `env_passthrough`)
  and find the bearer token at `$XDG_RUNTIME_DIR/bt_u<uid>` — without
  the variable they read a stale `/tmp/bt_u<uid>`. The write server's
  `run_as="self"` path refreshes that token from the Kerberos ticket on
  write calls; it does not renew the ticket (renewal between writes: C2).
- **Contract check against the real servers:** `TestRealServers` in
  `tests/test_prodtools_adapter.py` starts both servers from kits.toml
  and, read-only, checks every argument dict the adapter sends
  (`_launch_call`, `_cancel_args`, `_run_status_args`) against the
  tool's input schema (`KitClient.tool_schemas`) and that `run_status`
  of a run that cannot exist is None. Skipped unless
  `AUTORESEARCH_PRODTOOLS` is set AND `AUTORESEARCH_REAL_KIT_TESTS=1`
  (the second switch keeps the default suite hermetic in a shell that
  exports the first for the pipeline). A server ignores an argument its
  schema lacks, so only this check catches that drift.
- **`--executor`/`--parallel`:** `graph.run --executor grid|local`
  and `graph.closed_loop --executor ... --parallel N` (local only, 1..16)
  choose `ProdtoolsKit.executor`/`.parallel`, which pick `submit_once`
  (grid) vs `run_local` (local) and the poll cadence
  (`core/adapters/prodtools.py:_POLL`); recorded in `point.json`, not
  part of `measure_sha`. Worked example: `python -m graph.run
  --study prodtools_smoke --config smoke01 --campaign smoke --executor
  local`.
- **Zero-knob studies:** `tests/fixtures/engine_studies/prodtools_smoke.json`
  has `"knobs": []` — `graph.run` runs it with no `--x`;
  `graph.closed_loop` refuses it (one-shot studies have no campaign to
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
- **Local acceptance PASSED (2026-09-26, config `c1local01`,
  `AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c1accept`,
  prodtools local main `6640e6e`, so no `cancel_run`):** `graph.study_run
  --study prodtools_smoke --executor local` exited 0 in **3 min 48 s**
  wall and landed one v2 row, `ce_jobs_ok=1 mubeam_jobs_ok=1`.
  Timeline from `kit_trace.jsonl`:
  - ~46 s from launch to the first `run_local`. This covers the Python
    start, both server starts (each sources `setupmu2e-art.sh` and runs
    `muse setup ops`), the code tarball and the entry.
  - `run_local` itself took 26 s (mubeam) and 22 s (mustops_ce).
  - `run_status` took 0.006–0.12 s per call, at the local 10 s poll.
  - Each step then ran about 1.5 min until completed.
  Two code tarballs of about 15 MB each were built: the steps ship
  different bare-name `#include`s, so their content keys differ. That
  bears on the code-cache growth open question.
  To run the smoke against the `cancel-run` worktree, the worktree first
  needs its own `mcp/.venv`. The shared venv's editable `.pth` points at
  main's `mcp/src`, so the servers load main's code whatever
  `AUTORESEARCH_PRODTOOLS` names.
- **Grid acceptance PASSED (2026-09-26, config `c1grid03`)** on the stock
  SimJob MDC2025ax release (`Code_mdc2025ax.tar.bz2`: a `backing` link
  plus `setup.sh`; Offline v13_38_00 has the holeRadii and IPA
  zStartInMu2e patches upstream). It took 14 min 36 s wall and landed
  one v2 row. Each `submit_once` took about 2 min, including the RCDS
  publish. mubeam ran as `30116821.0@jobsub04`; its `TargetStops` file
  was hard-linked into `/pnfs/.../autoresearch_grid/c1grid03/staged/mustops_ce`
  and read there by mustops_ce (`86801721.0@jobsub01`). Two earlier tries
  failed before submitting, and nothing reached the grid:
  - `c1grid01`: prodtools' tape check crashes under a Python 3.10
    Musing
    ([prodtools-tape-check-musing-python-mismatch](/incidents/prodtools-tape-check-musing-python-mismatch.md)).
  - `c1grid02`: `jobsub_submit` lacked `JOBSUB_DROPBOX_SERVER_LIST`.
    The kit client starts servers with a minimal environment, so the
    write server now passes the five `JOBSUB_*` settings from
    `/etc/profile.d/jobsub_lite.sh` (`kits.toml`).
  A grid launch needs 4 h of Kerberos ticket, so `kinit -R` came first.

**Geometry pre-check kit and C1's small fixes (Phase C2a)**
- Spec `docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md`,
  plan `docs/superpowers/plans/2026-09-26-c2a-preflight-kit.md`, branch
  `generic-study-phase-c2a`.
- `core/adapters/preflight_checks.py` holds the pre-check's rules
  (`check_files`, `stage_workdir`, `run_check`, `classify` ->
  `Verdict(ok, code, reason, notes)`, `verify_stopping_target_gdml`),
  shared by `OfflinePreflightKit` (`core/adapters/offline_preflight.py`)
  and `bo_driver preflight`. The `holeRadii vector active` printout
  check is gone: upstream Offline v13_38_00 prints no such line, and the
  as-built GDML comparison checks every hole radius.
- The check runs from the study's code tarball, unpacked once per
  content into `<GRID_DATA_ROOT>/_code/<sha256>/`
  (`prodtools_entry.unpacked`), with `MUSE_WORK_DIR` unset as prodtools'
  runlocal does; workdir `<GRID_DATA_ROOT>/<config>/preflight/`, emptied
  first, keeps `preflight.log` and `asbuilt.gdml`. `musing` is gone from
  every study and from `ModeSpec`; the pipeline's `sourced_env` sources
  the code tarball's `Code/setup.sh` instead.
- The loader refuses a study whose `kits.offline_preflight.code_tarball`
  differs from `kits.prodtools.code_tarball`
  (`kit_registry.MATCHING_SETTINGS`). `check_kits` asks a kit used only
  for the preflight for `check` alone.
- The kit's message is `<code>: <reason>`; `ambiguous` fails, with the
  log's last 40 lines. `node_preflight` was not changed.
- Fixes: stuck receipts (`submitting`/`building`/`starting`) name
  prodtools' error and where to look (`jobsub_q`, or the local host and
  pid); a local run still `starting` after 10 min fails; a `done`/`short`
  reply with no `jobs` block raises; `KitClient.start` writes a
  `start` trace row; `entry` is reserved at load for a kit that takes
  stage templates; `graph.closed_loop` checks `<prefix>R00_00` against
  each adapter's `config_problem` before launching.
- A pre-check that hits an `OSError` (quota, unpack) or a GDML dump it
  cannot parse now marks the point broken; the loader refuses
  `require_zero_overlaps: true` without `checks_managed_overlap: true`.
- **C2a acceptance PASSED (2026-09-26/27, data root
  `/exp/mu2e/data/users/oksuzian/c2accept`, all local, real G4):**
  - `prodtools_smoke` on MDC2025ax (`c2alocal01`): pre-check `pass` with
    zero surface-check overlaps, both steps completed, one row, 7 min 33 s
    wall (the pre-check's G4 init is about 3 min of that).
  - The broken geometry (every hole radius 1.2 × its foil's outer radius):
    the kit on MDC2025ax said `fail_managed` (fatal G4 abort) and nothing
    was submitted; the old pre-check at the C1 tip (Run1Bap `musing`) also
    said `fail_managed`.
  - The passing geometry: the old pre-check at the C1 tip said `pass`, and
    this branch's pipeline pre-check (Run1Bap code tarball, new shared
    rules) said `pass`, so the pipeline stays runnable for C2b's parity
    check.
  - Overlap counts were 0 in all six logs, on both releases.

**anakit kit and the foilspf engine twins (Phase C2b)**
- Spec: `docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md`,
  branch `generic-study-phase-c2b`. See [anakit](/external/anakit.md) for
  the fork itself (commits, the work area, the build).
- `AnakitKit` (`core/adapters/anakit.py`, another in-process
  `core/contract.py:ADAPTERS` entry) drives M. MacKenzie's analysis MCP
  server for the `sob`/`flash` steps: `ce_sensitivity` and
  `flash_edep_per_pot`, run by our fork under
  `kits.toml[servers.anakit]`. It offers no `describe` (its params/metrics
  are per-analysis, checked instead by `step_problems`, below) and no
  `cancel` (a failed sibling step still lets an in-flight anakit analysis
  run to completion — `core/scheduler.py:run_steps` only cancels a step
  whose kit offers the tool).
- **One server per step:** FastMCP 1.28 calls a sync tool on its own event
  loop, so one anakit server runs one analysis at a time; `submit` starts a
  fresh server on the study's `kits.anakit.work_area`, runs the analysis to
  completion, and closes it (`AnakitKit._client`/`_call`). The reply lands
  at `<GRID_DATA_ROOT>/<config>/anakit/<step>/anakit_result.json`
  (`AnakitKit._step_dir`); `status`/`results` only read that file, so a
  point resumed after a crash mid-analysis has no handle yet and the
  analysis reruns from scratch (no partial-progress resume, unlike a grid
  job's `run_status`).
- **Version = adapter + fork commit:** the reported `version` is
  `anakit-adapter/1+anakit-<commit>`, the fork's short commit read once
  when the campaign's `KitSet` opens the kit (`fork_commit`). **`submit`
  re-checks the fork on every call** and refuses (`KitError`) if it has
  gone dirty, or moved to a different commit, since open — `measure_sha`
  must label the build that actually ran, not a stale label captured at
  open; restarting the campaign picks up the new commit.
- **`RUN_TIMEOUT_S = 3000`** is the adapter's own budget for one
  `run_analysis` call (`timeout_s` in the call args);
  `kits.toml[servers.anakit].timeouts.run_analysis` must be at least
  `RUN_TIMEOUT_S + CALL_MARGIN_S` (300 s) so anakit reports its own timeout
  rather than the MCP call being cut off first (`AnakitKit._check_timeouts`);
  it is set to 3600 s.
- **OSError and git failures are wrapped, not left to crash the engine
  child:** a quota-limited or otherwise flaky `GRID_DATA_ROOT` (the step
  directory's `mkdir`/`rmtree` in `submit`), and a hung or missing `git`
  binary in the fork checkout (`_git`, used by `fork_commit` and
  `code_commit`), both raise a `KitError`/`ValueError` naming the failing
  command — matching the sibling adapters' OSError-wrapping
  (`core/adapters/offline_preflight.py:check`,
  `core/adapters/prodtools.py:_prepare`), so a full disk or a wedged `git`
  breaks only the point, not the whole engine child.
- **A catalogue entry missing `metrics` or `takes_data_files` is an error,
  not a default:** anakit's `list_analyses` reply is checked for both keys
  explicitly in `submit` and in `step_problems` — a broken reply is a loud
  `KitError`/`ContractError`, never assumed (e.g. that every analysis takes
  a list of files).
- **`step_problems` (`core/contract.py:kit_step_problems`):** the optional
  per-step half of the launch check — a kit may say what's wrong with one
  of its steps before any job runs. `check_kits` (used by
  `graph.closed_loop`) calls it for every step of every kit the study
  names; `graph.run` runs the same per-step check itself, not the
  full `check_kits`, right after starting its kits and before writing
  anything for the point (`graph/run.py`, after the kit-start loop).
  `AnakitKit.step_problems` uses it to check the work area is a directory,
  the code tarball's `backing` link matches it, the step's `analysis`
  exists in anakit's catalogue, every sent param is one the analysis
  declares (and every required one is sent), and the study's
  objectives/extra metrics sourced from that step are all in the
  analysis's `metrics`.
- **`${ARTIFACT}/` in a step's `fixed`:** a fixed value like
  `sob.fixed.dio_table` follows the same rule as a kit setting — only the
  `${ARTIFACT}/` token is allowed, never a bare personal path
  (`core/study.py:expand_artifact`), checked at study load but left RAW
  there, so `measure_basis` (and `measure_sha`) hashes the unexpanded
  string identically for every operator; it is expanded to a real path
  only where a step's params are actually built
  (`core/scheduler.py:step_params`).
- **The seven `<name>_ax` twins** (`mode_specs/foilsflash_ax.json`,
  `foilspf_ax`, `foilspf2k_ax`, `foilspfbp_ax`, `foilspfbpx_ax`,
  `foilspfbpz_ax`, `foilspfbw_ax`) are new engine studies, not edits to the
  seven originals, which stay pipeline-only and untouched. They must: the
  pipeline's `core/modes.py:DEFAULT_MODE = "foilspf"` has to remain a live
  pipeline `SPECS` entry (`ENGINE`/`SPECS` partition every study by
  `runs_on_engine`, and `DEFAULT_MODE` is asserted to be in `SPECS`) — it's
  the fallback every module-level `AUTORESEARCH_MODE` reader uses. A twin
  keeps its original's knobs, `derive`/`geom` and the original's `note` for
  the geometry explanation, but points `kits.prodtools`/
  `kits.offline_preflight.code_tarball` at `Code_mdc2025ax.tar.bz2`
  (`dsconf: MDC2025ax_{cfg}`), adds `kits.anakit.work_area`, and replaces
  the `sob`/`flash` steps' `kit: ce_sensitivity|flash_edep_per_pot` with
  `kit: anakit` plus an `analysis` fixed value and that analysis's own
  fixed params (`input_correction`, `cosmic_rate_per_s_per_mev`,
  `dio_fraction`, `dio_table` for `sob`; `pot_per_electron` for `flash`).
  Each twin gets its own, empty v2 leaderboard
  (`leaderboards/leaderboard_bo_<name>_ax.tsv`) — rows measured on a
  different release can't be mixed onto the original's v1 board.
- **Pre-check reuse on resume:** `graph/study_graph.py:preflight_basis`
  fingerprints what a PASSING verdict depends on (the kit, its settings,
  the point's mapped values, and each read file's content — SHA-256 for a
  `file://` ref, else its URI), JSON-normalized so it round-trips through
  `preflight_verdict.json`; `reusable_pass` reuses a saved verdict only
  when it says `ok: true` for exactly that basis, so a resumed point whose
  settings and files haven't changed skips the pre-check outright instead
  of re-running G4 init. A saved FAILURE is never reused — retrying a point
  (deleting `broken.txt`) always checks again. The verdict's message also
  now ends with the check's own notes (foils verified, overlap-hit count,
  return code), not just the classified code (commit `bc37a48`). This
  closes the "resumed child re-runs preflight" follow-up below.
- **`tools/c2b_parity.py`** (manual, outside `unittest discover`, deleted
  with the pipeline in C3) is the sob/flash parity check against the old
  pipeline's harvest: `level1` runs `approx_ce_sensitivity` alone over
  every archived `foilspf*/harvest/summary.json` + `nts.ce.root` pair and
  compares against the pipeline's printed `s_over_sqrt_b` (`sob_matches`:
  within half the macro's last printed digit, plus anakit's own 0.01%
  convolution-change tolerance); `level2` runs both `sob` and `flash` on
  one archived point's real output files and compares seven quantities
  (`compare_level2`): four EXACT counts (`muminus_stops`,
  `mubeam_sim_total`, `ce_seen`, `ce_simulated_events`), `ce_abs_eff` and
  `flash_edep_per_pot` at ≤1e-6 relative, and `s_over_sqrt_b` by the Level 1
  rule (`sob_matches`); `level3-setup`/
  `level3-check` hand-write `<step>_results.json` records for
  `graph.study_run` to adopt, so a point can be re-scored end to end
  through the real engine (not just the adapter), then diff the engine's
  own state files and its v2 board row against the archived summary.
  Every analysis in the tool runs through `AnakitKit` with
  `foilspfbpz_ax`'s own settings (`study_params`), so the parity check
  covers the adapter and the study file, not only the two anakit analyses.
- **Acceptance PASSED (2026-09-27/28).** Fork `3561c79`..`60cb434`,
  Mu2eOptAna `9b197e2`, autoresearch through `3820ea5`.
  - **Parity Level 1:** 495 archived `foilspf*` harvests found, 495
    compared, 0 mismatched or failed, 0 skipped. The plan's fact sheet
    said 497; it counted `nts` files, not summaries.
  - **Parity Level 2**, all 7/7 on three points, with counts exact:
    - `gridphaseA01`: sob 1.69 → 1.69218.
    - `foilspfbpz07R11_00`: sob 4.15 → 4.15067.
    - `foilspfbpz07R19_00`: sob 4.03 → 4.02725.
    - `ce_abs_eff` and flash agree to ~1e-15 relative, float rounding only.
  - **Parity Level 3** (`gridphaseA01`, sandbox
    `c2b_sandbox/l3`): `graph.study_run` adopted the three hand-written
    grid records, ran `flash` and `sob` through `AnakitKit` and appended a
    row. Primary 1.6921788498091483. `level3-check` exited 0 on 7/7 plus
    the board row.
  - **Local** (`c2blocal01`, `foilspfbpz_local`, `--executor local
    --parallel 4`): the pre-check passed, 5/5 steps completed and a row
    landed, in about 10 min. At 20000 mubeam, 4000 CE and 40000 elebeam
    events its numbers (sob 4.167, flash 4.24e-7) are not physics.
  - **Grid** on SimJob MDC2025ax against Run1Bap:

    | point | sob (Run1Bap) | flash_edep_per_pot (Run1Bap) | wall |
    |---|---|---|---|
    | `c2bnom01` (`foilspf_nominal`, the deployed 37-foil stack) | 3.25997 (3.26, −0.0%) | 6.50684e-07 (6.854e-07, −5.1%) | 3 h 04 min |
    | `c2bR11ax01` (`foilspfbpz_ax`, R11_00's x) | 4.14258 (4.15, −0.2%) | 7.25485e-07 (6.695e-07, +8.4%) | 3 h 28 min |

    Both changes are under the plan's 20% investigation line. The two
    grid runs overlapped; mustops_ce's tail jobs dominated the wall time.
  - **New damage budget on MDC2025ax: 6.50684e-07**, c2bnom01's flash at 6
    significant figures. It is in the seven `_ax` twins' `constraints`
    (commit `0326130`). The originals and the two acceptance fixtures
    keep Run1Bap's 6.85443e-07.
    - **Consequence:** R11_00 sat 2.3% under budget on Run1Bap but sits
      11.5% over it on MDC2025ax. Its flash-to-nominal ratio went from
      0.977 to 1.115. That is ~1.5σ at the archive's ~4.5% flash noise per
      point, so a `budget_sob` round on the `_ax` boards will not treat
      R11_00 as feasible.
    - c2bR11ax01's row carries the pre-budget `spec_sha`: the study was
      loaded before the commit. `spec_sha` is recorded, never checked,
      and `measure_sha` does not see `constraints`.
  - Rows: `leaderboards/leaderboard_bo_foilspfbpz_ax.tsv` (c2bR11ax01) and
    `leaderboard_foilspf_nominal.tsv` (c2bnom01) under the real data root.

**Pipeline deleted (Phase C3)**
- Spec: `docs/superpowers/specs/2026-09-28-c3-delete-pipeline-design.md`,
  branch `generic-study-phase-c3`, from `generic-study-phase-c1` at
  `3d48db1` (which already held C1, C2a and C2b). C2b (above) proved
  sob/flash parity between the pipeline and the engine+anakit on
  2026-09-28, so nothing needed the pipeline any more.
- **What was deleted:** `core/pipeline.py`, `harvest.py`, `bo_driver.py`,
  `study_compat.py`, `prodtools_exec.py`, `prodtools_submit_driver.py`,
  `runtime.py`, `launch_checks.py`; the OLD `graph/run.py` and
  `graph/closed_loop.py` (the pipeline's campaign/point runners, before
  the rename below took their names), plus `graph/nodes.py`,
  `pipeline_io.py`, `state.py`, `build.py`; `tools/run_grid.sh`,
  `run_local.sh` and `tools/c2b_parity.py` (`tools/` itself went, empty);
  the pipeline-only tests (`test_closed_loop`/`test_study_loop` under
  their old pipeline meaning, `test_foilspf_spec`, `test_geom_golden_parity`
  under its old pipeline-comparison shape, `test_golden_parity_harness`,
  `test_harvest`, `test_json_mode`, `test_nodes`, `test_no_mock_mode`,
  `test_pipeline_verbs`, `test_seam_protocol`, `test_stages_retired`,
  `test_prodtools_exec`, `test_launch_checks`, `test_mode_archive`,
  `test_c2b_parity`, `test_runtime_constants`) and their fixtures
  (`tests/fixtures/modes/`, `tests/goldens/`; `tests/fixtures/golden_geom/`
  was kept, retargeted to `foilsflash_ax`). `core/modes.py` lost `SPECS`,
  `ModeSpec`, `DEFAULT_MODE`, `resolve_env_mode`, `AUTORESEARCH_MODE`,
  `ENGINE` and `runs_on_engine`; `KitDecl` lost its `engine`/`pipeline`
  flags and the `ce_sensitivity`/`flash_edep_per_pot` KitDecls;
  `core/paths.py` lost `BO_WORK`, `prodtools_root`, `verify` and
  `require`; `graph/pool.py`'s `run_rolling` lost its pipeline-default
  fallbacks (`_default_run_child`, `_default_pick_source`,
  `_default_row_landed`, `_default_broken`, `_pending_names`, the
  pipeline branch of `_name_busy_reason`, and the `runtime.
  CLOSED_LOOP_STAGGER_SEC` stagger fallback) — every caller now passes
  `run_child`, `next_pick`, `row_landed`, `broken` and `stagger` itself.
  The Kerberos move (`check_kerberos`, `GRID_TICKET_SECONDS`, from
  `core/launch_checks.py` into `core/contract.py`) landed first, in
  commit `33bfb24`, so the tree stayed green before the rest of the cut.
- **Renamed:** `graph/study_run.py` → `graph/run.py`, `graph/study_loop.py`
  → `graph/closed_loop.py` (see the two subsections above), with
  `git mv` so history follows; `tests/test_study_run.py` →
  `tests/test_run.py`, `tests/test_study_loop.py` →
  `tests/test_closed_loop.py`. Log/refusal prefixes followed:
  `[study_run]` → `[run]`, `[study_loop]` → `[closed_loop]`; an unknown
  study's refusal now says studies under `mode_specs/archive/` are not
  loaded; the busy-name recovery hint now says
  `pgrep -f 'graph.run.*<name>'`, not `study_run`.
- **The archive decision (operator, 2026-09-28):** the seven original
  foilspf studies and their v1 boards are archived, not deleted — the
  operator chose the easiest path over read-only history. The study files
  moved (`git mv`) to `mode_specs/archive/`, unloaded
  (`core/study.py:load_study_dirs` globs `mode_specs/` flat, so `archive/`
  is never selectable with `--study`); their boards stay in `leaderboards/`
  as plain files. The surrogate MCP stops seeing them (`list_problems`
  answers with only the seven `_ax` studies); a pre-C3 commit brings the
  originals back if anyone ever needs to run one again. See
  `mode_specs/README.md`, "`archive/`".
- **Three rulings carried over unchanged from the design (out of scope for
  C3):**
  1. The `desc_fmt` → `desc` template rename is dropped: it would change
     every `_ax` study's `measure_sha` (the stage templates are part of
     `measure_basis`), and `Leaderboard.append` refuses a mixed
     `measure_sha` — every later `foilspfbpz_ax` row would be quarantined
     until someone moved the board holding the one real MDC2025ax row
     (`c2bR11ax01`) aside. `core/adapters/prodtools_entry.py` keeps
     reading `desc_fmt`.
  2. `core/pipeline_templates/` keeps its name: the engine reads it
     (`prodtools_entry.py`), and renaming it would also touch
     `measure_basis`.
  3. v1 leaderboard-layout support stays in `core/leaderboard.py`: nothing
     loaded uses it any more (only the archived boards are v1), but
     removing it is extra work with nothing gained.
- **`measure_basis_sha` is unchanged** for all seven `_ax` studies —
  renaming modules and deleting dead code around them touched none of
  `derive`, `geom`, `kits`, the steps or the objectives:
  ```
  foilsflash_ax  405cc0e850b9dc4ed28ee96bea8187c94185bce654230acc5016de73a1763d6f
  foilspf2k_ax   2060c97e7de0a4a18f6364e0a721e6abe45e4bc98a089b4ffedcea75385e12a4
  foilspf_ax     e96f0491abe95519352962dc51616fca0598eabf5b5cfba122734179da3b250e
  foilspfbp_ax   54467d3e05b4742da1fbd3a7809cf50f770fdc18219c40773ada487355cb0547
  foilspfbpx_ax  d6ee2d286f6e8e26a6417dfb9530789beefd8f385179036f60c4385d1e6d8a4d
  foilspfbpz_ax  c4aafee1c30ba5121ab727bcab4513786b6d076c10f976d1b786daf95e218a80
  foilspfbw_ax   01bcbd62be9a8f4d8b825e85267a3e7b45a0746b2784f1c48c32aeacba962191
  ```
- **`stage_entries/*.json` still names the deleted file in its own
  `_comment`.** Every stage template's `_comment` field (e.g.
  `stage_entries/mubeam.json:2`) says "Rationale for these keys lives in
  core/pipeline.py, in the comment block immediately above
  _render_fcl_overrides" — that file is gone. `stage_entries/*.json` is
  frozen (the templates are hashed whole into `measure_basis`, ruling 2
  above), so the comment is not rewritten; read the rationale with
  `git show 3d48db1:core/pipeline.py` (the last commit that still has it).
- **Env vars now inert** (nothing reads them; confirmed by grep, 2026-09-29
  review): `AUTORESEARCH_MODE` (the pipeline's mode switch —
  `tests/test_modes.py` pins that a stale export is ignored, never a
  `SystemExit`), `AUTORESEARCH_ELEBEAM_NJOBS`, `AUTORESEARCH_LOCAL` and its
  `AUTORESEARCH_LOCAL_{NJOBS,EVENTS,POOL}` scale knobs (`AUTORESEARCH_LOCAL`
  itself is now REFUSED rather than silently ignored — see
  [local-executor](/drivers/local-executor.md) and `graph/run.py:
  local_env_refusal`), `AUTORESEARCH_NO_RUN1B`, `AUTORESEARCH_BOTORCH_VENV`.
- **`.env`/LangSmith tracing is no longer loaded.** Nothing calls
  `load_dotenv()` since Phase C3 (only the deleted pipeline's
  `graph/run.py` did), so a `.env` with `LANGCHAIN_*`/`LANGSMITH_*` keys
  is inert; the unused `python-dotenv` pin was dropped from
  `requirements.txt` on 2026-09-29.
- **Acceptance PASSED (2026-09-29).**
  - **Suite:** green at the branch tip, 729 tests OK (skipped=4).
  - **Grep gates:** clean.
  - **Measurement:** the seven `_ax` studies' `measure_basis_sha` values
    are unchanged.
  - **Local run under the new name:** `graph.run --study foilspfbpz_local`,
    `--executor local --parallel 4`, sandbox `c3_sandbox/local`.
    - `c3local01` ran at `dc8a176`, `c3local02` at `f38f649`.
    - Both passed the pre-check, completed 5/5 steps and landed a row.
    - sob 4.167405887555443 and flash 4.24058e-07, bit-identical to C2b's
      `c2blocal01` at the same x before C3.
  - **Surrogate MCP:** a fresh `surrogate/mcp_server.py` lists exactly the
    seven `_ax` studies (`foilspfbpz_ax`: 1 row, `c2bR11ax01`; the others
    0) and none of the originals.
  - **No grid run:** the engine changed only by renames, by losing
    fallbacks it never used, and by the new `AUTORESEARCH_LOCAL` refusal.

## Cross-links
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md) (superseded
  — the pipeline campaign runner this engine sat alongside, not on top of,
  through Phase B/C2; Phase C3 deleted it, so the engine is now the only
  runner), [surrogate](/drivers/surrogate.md) (the MCP door that reads
  the same v2 boards through `core/botorch_predict.py`),
  [tests](/drivers/tests.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md)
  (the pipeline's load-bearing constraints, historical — the engine reused
  its rolling pool but not its checkpointing or barrier logic),
  [anakit](/external/anakit.md) (the fork the C2b kit drives)
- Source files: `kits.toml`, `core/kit_config.py`, `core/kit_registry.py`,
  `core/kits.py`, `core/contract.py`, `core/scheduler.py`,
  `core/study.py`, `core/score.py`, `core/leaderboard.py`, `core/boards.py`,
  `graph/study_graph.py`, `graph/run.py`, `graph/closed_loop.py`,
  `graph/pool.py`, `tests/toykit.py`, `tests/textkit.py`,
  `core/adapters/__init__.py`,
  `core/adapters/prodtools.py`, `core/adapters/prodtools_entry.py`,
  `core/adapters/offline_preflight.py`, `core/adapters/preflight_checks.py`,
  `core/adapters/anakit.py`,
  `tests/fixtures/engine_studies/prodtools_smoke.json`,
  `mode_specs/foilspf_ax.json` and its six siblings
- Design: `docs/superpowers/specs/2026-09-23-generic-study-design.md`,
  `docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md`,
  `docs/superpowers/specs/2026-09-28-c3-delete-pipeline-design.md`

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

The pipeline is reference-only from 2026-09-26: the operator plans no
foilspf campaign before C2. It stays runnable, but only so that C2 can run
one point both ways (pipeline vs engine + anakit) and match
`s_over_sqrt_b` and the flash numbers before C3 deletes it. Until then,
changes to what it reads wait for C3. First among them: rename the stage
templates' `desc_fmt` to `desc` (`dsconf_fmt` is gone since C2a), so that a
filled-in template is a prodtools entry key for key
(`core/pipeline.py:249` still reads `desc_fmt`). Each template's
`_comment` should also name the production entry it derives from; for
mubeam that is `data/Run1B/resampler_beam.json` MuBeamFlash/Run1Bak, which
shares only `fcl`, `resampler_name` and `input_data`.
**Resolved by C3 (2026-09-28), not as planned above:** the `desc_fmt`
rename was dropped rather than done (see "Pipeline deleted (Phase C3)"
below, ruling 1 — it would have changed every `_ax` study's `measure_sha`),
and `core/pipeline.py` itself, `desc_fmt`-reading line included, is
deleted along with the rest of the pipeline.

Phase C follow-ups found in review (2026-09-25):
- No launch-time check that the board's `measure_sha` matches the study's
  current one — a child runs its steps and is refused only at append.
  `graph/closed_loop.py`.
- ~~A resumed child re-runs preflight; a transient `check` failure then
  marks a point broken while its grid job still runs. `graph/study_graph.py`.~~
  **Done in C2b:** `preflight_basis`/`reusable_pass` record what a PASSING
  verdict depended on (kit, settings, mapped params, file content hashes)
  in `preflight_verdict.json`; a resumed point whose basis is unchanged
  reuses that saved pass and skips the pre-check outright, so a transient
  `check` failure on a second run can no longer break a point whose grid
  job is already running. A saved FAILURE is never reused — retrying a
  point (deleting `broken.txt`) always checks again (see "anakit kit and
  the foilspf engine twins (Phase C2b)" above, commit `bc37a48`).
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
  `REQUIRES_KERBEROS` is refused up front (`graph/run.py:
  launch_refusals`, `core/contract.py:requires_kerberos`) unless a
  ticket with at least 4 h left is held; the adapter itself never
  refreshes one.
- After a runner restart, orphaned in-flight children's x are not passed
  to the picker as pending. `graph/closed_loop.py`.
- A leftover `STOP` file makes a relaunch under the same prefix launch
  nothing, silently. `graph/closed_loop.py`.
- A picker failure mid-campaign surfaces only after in-flight children
  finish (inherited from `graph/pool.py`).
- **Ported-launch-checks follow-up (Phase C3 ruling, 2026-09-28):** engine
  launch checks the pipeline had and the engine still lacks are a
  follow-up, explicitly not part of C3 — data-quota, config-name-free and
  stale-cluster, previously done by `tools/run_grid.sh` via the now-deleted
  `core/launch_checks.py`. (This is distinct from `config_name_problems` in
  `core/contract.py`, which `graph/closed_loop.py` already calls at launch —
  that checks the first child name against each kit's own character rule,
  not whether the name is free of a prior claim, quota-under-limit, or a
  stale grid cluster.)
- **A local run no longer checks for a live Kerberos ticket before
  starting.** `requires_kerberos` (`core/contract.py:368`) returns `False`
  whenever `executor != "grid"`, since it only asks whether some kit sets
  `REQUIRES_KERBEROS` (the prodtools adapter's grid path). But README.md's
  own Kerberos note says even a local run streams resampler inputs from
  `/pnfs` over xrootd, needing a live bearer token exactly as a grid worker
  does — the deleted pipeline's `run_local.sh` called `check_kerberos(0)`
  (any ticket, not the grid path's 4 h minimum) to catch that up front. The
  engine has no equivalent: a ticketless `--executor local` run is not
  refused at launch and instead fails later, inside a step's xrootd read.
- **`measure_basis` hashes a stage template whole, but only the FILENAMES
  of its FCL includes, never their bytes.** `core/study.py:_measure_basis`
  puts each step's `entry(s)` — the whole `stage_entries/<step>.json` dict,
  via `_stage_template` — into the hashed basis, so `fcl_overrides.#include`
  contributes as a list of strings like `"sim_kept_products_extras.fcl"`.
  The actual snippet files those names resolve to, `core/pipeline_templates/
  *.fcl` (read at run time by `core/adapters/prodtools_entry.py`'s
  `TEMPLATES_ROOT`), are never read or hashed by `_measure_basis`. So
  editing an include's FCL content (not its filename) changes what every
  future job runs with no `measure_sha` change — a champion re-run after
  such an edit would silently compare apples to oranges on the same board.
