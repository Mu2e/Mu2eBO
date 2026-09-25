---
type: driver
title: Contract engine (Phase B)
description: kits.toml native kits over stdio MCP (KitClient), the evaluator
  contract (NativeKit, check_kits), run_steps (one scheduler node,
  state-file resume), v2 rows with measure_sha, graph.study_run /
  graph.study_loop; toykit Branin acceptance in 28.7 s
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
As of 2026-09-25 this is the only engine study family — `foilspf` and its
siblings still run on the pipeline (`core/bo_driver.py`,
[closed-loop-runner](/drivers/closed-loop-runner.md)) until Phase C gives
prodtools an adapter.

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
  with the four pipeline kits (`prodtools`, `offline_preflight`,
  `ce_sensitivity`, `flash_edep_per_pot`, all `engine=False` until Phase C
  gives them adapters); a name clash between the two raises at import.
- **`kits.toml` is parsed when `core.kit_registry` is imported**
  (`NATIVE = load_kit_configs()`), and `core.study` and `core.modes` import
  it, so a `kits.toml` error breaks the pipeline's imports too
  (`graph.run`, `graph.closed_loop`, the surrogate MCP server), not just
  the engine's.
- **Routing, as the code enforces it:** a study's kits are all engine kits
  or all pipeline kits (a mix is refused, `core/modes.py:runs_on_engine`),
  and a pipeline study must be layout `"v1"` (`core/study_compat.py`). Both
  refusals happen at `core.modes` import, so one such study file in
  `mode_specs/` or on `$AUTORESEARCH_STUDY_PATH` stops every command for
  every study (`mode_specs/README.md`, "Engine studies").
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
- No backoff between attempts (see Open questions).
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
  `graph/pool.py`, `tests/toykit.py`
- Design: `docs/superpowers/specs/2026-09-23-generic-study-design.md`

## Open questions / TODO
Phase C follow-ups found in review (2026-09-25):
- No launch-time check that the board's `measure_sha` matches the study's
  current one — a child runs its steps and is refused only at append.
  `graph/study_loop.py`.
- A resumed child re-runs preflight; a transient `check` failure then
  marks a point broken while its grid job still runs. `graph/study_graph.py`.
- Sibling steps of a failed step run to completion (the contract's
  `cancel` is unused) — grid hours spent on a dead point. `core/scheduler.py`.
- `NativeKit` retries have no backoff; a status failure that lasts seconds
  (a credential blip) fails the step. `core/contract.py`.
- No credential renewal / 4 h ticket gate for engine campaigns.
  `graph/study_loop.py`.
- After a runner restart, orphaned in-flight children's x are not passed
  to the picker as pending. `graph/study_loop.py`.
- A leftover `STOP` file makes a relaunch under the same prefix launch
  nothing, silently. `graph/study_loop.py`.
- A picker failure mid-campaign surfaces only after in-flight children
  finish (inherited from `graph/pool.py`).
