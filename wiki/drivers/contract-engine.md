---
type: driver
title: Contract engine
description: 'The only runner — studies as JSON, kits over MCP (prodtools, offline_preflight, anakit, beamkit), run_steps, measure_sha boards, graph.run / graph.closed_loop, check_study, params_from'
status: active
timestamp: '2026-10-08'
---

# Contract engine

## Summary
The engine runs a study: a JSON file in `mode_specs/` (data, not code)
that names its knobs, its geometry, its kits and its steps. Every kit
speaks the evaluator contract (`submit`/`status`/`results`, optional
`check`/`describe`/`cancel`). Native kits are listed in `kits.toml` and
reached over stdio MCP (`core/kits.py:KitClient`); four in-process
adapters (`core/adapters/`) wrap the real servers: `prodtools` (art jobs,
grid or local), `offline_preflight` (the geometry pre-check), `anakit`
(M. MacKenzie's analyses) and `beamkit` (G4beamline). `core/scheduler.py:
run_steps` drives a point's steps, `core/score.py` scores them and
`core/leaderboard.py` appends a v2 row stamped with a `measure_sha`.
`graph/run.py` runs one point, `graph/closed_loop.py` runs a campaign on
the rolling pool (`graph/pool.py`), `graph/check_study.py` checks a study
file before launch. The pipeline (`core/pipeline.py`, `bo_driver.py`) was
deleted in Phase C3 (2026-09-28); the engine is the only runner.
`tests/toykit.py` is the reference kit and the CI engine: a Branin/Currin
campaign (q=2, 8 points) runs end to end in 28.7 s.

## Key facts

### Studies
- **Format:** schema-2 JSON, keys `schema`, `name`, `note`, `knobs`,
  `derive`, `geom`, `kits`, `preflight`, `evaluate` (the steps),
  `objectives`, `constraints`, `extra_metrics`, `extra_columns`,
  `leaderboard`. The loader is `core/study.py`; `mode_specs/README.md` is
  the how-to.
- **Live studies** (`mode_specs/`):
  - `foilspfbpz_ax`: 10 knobs, the foilspf profile target on SimJob
    MDC2025ax; board `leaderboard_bo_foilspfbpz_ax_upstream.tsv`.
  - `foilsflash_ax`: 6 knobs; board `..._foilsflash_ax_upstream.tsv`.
  - `foilspf_nominal`: zero knobs, the deployed 37-foil target; the
    production baseline and the source of the flash damage budget; board
    `leaderboard_foilspf_nominal_upstream.tsv`.
  - `ce_chain`: zero knobs, the CeEndpoint dts -> dig -> mcs -> nts chain
    plus an anakit plot step ([production-chain-spike-2026-09](/concepts/production-chain-spike-2026-09.md)).
  - `ptg4bl`: G4beamline production target through beamkit
    ([bo-ptg4bl](/projects/bo-ptg4bl.md)); board `leaderboard_bo_ptg4bl_5k.tsv`.
- Older studies (the pipeline's seven foilspf originals and five unused
  `_ax` twins) are deleted; git history keeps them, and their boards stay
  in `leaderboards/` as plain files. `mode_specs/archive/` (four schema-1
  A/B files) is never loaded: `load_study_dirs` globs `mode_specs/` flat.
- **All studies load at `core.modes` import** (from `mode_specs/` and
  `$AUTORESEARCH_STUDY_PATH`), so one broken study file, or one naming a
  kit not in `kit_registry.KITS` (`"unknown kit"`), stops every command
  for every study.
- **`${ARTIFACT}/` paths:** a kit setting or a step's `fixed` value may
  hold a path only as `${ARTIFACT}/...` (`core/study.py:expand_artifact`).
  It stays raw at load, so `measure_sha` hashes the same string for every
  operator; it is expanded only where a step's params are built.
- **Load rules worth knowing:** a knob, objective or metric may not be
  named after a column the board adds (`config`, `handles`, `spec_sha`,
  `measure_sha`, `time`); two steps of a `uses_entries` kit may not
  resolve to the same `desc_fmt` (`_check_run_names` — prodtools names a
  run `cnf.<owner>.<desc>.<dsconf>.0` and refuses a second use); a
  profile whose three controls are all knobs must have `clip` equal to
  their bounds' span (`_check_profile_clips`); `offline_preflight` and
  `prodtools` must name the same `code_tarball`
  (`kit_registry.MATCHING_SETTINGS`); `require_zero_overlaps` needs
  `checks_managed_overlap`; a prodtools step may not ask for more than
  200 jobs (`MAX_JOBS_PER_STEP`: prodtools' `run_status` lists at most
  200 jobs' outputs).
- **Zero-knob studies** (`foilspf_nominal`, `ce_chain`,
  `tests/fixtures/engine_studies/prodtools_smoke.json`) run through
  `graph.run` with no `--x`; `graph.closed_loop` refuses them and the
  surrogate does not list them.
- **One geometry for every step:** a study's `geom` is written once and
  each prodtools step lists `"files": ["geom"]`, its template pointing
  `GeometryService.inputFile` at `{geom}`. A `geom: null` study has no
  shared geometry. Template placeholders are only `{cfg}` and `{geom}`.
- **Stage templates** are `stage_entries/<name>.json`, frozen: they are
  hashed whole into `measure_basis`. Their `_comment` still points at the
  deleted `core/pipeline.py`; read it with `git show 3d48db1:core/pipeline.py`.
  The FCL snippets they `#include` (`core/pipeline_templates/*.fcl`) are
  hashed by NAME only (see Open questions).

### Registry (`kits.toml`, `core/kit_config.py`, `core/kit_registry.py`)
- `kits.toml` holds the native kits (only `[toykit]` today) and the
  `[servers.*]` tables the adapters start (`prodtools_write`,
  `prodtools_read`, `anakit`, `beamkit`). Every key is required and
  unknown keys are rejected (ADR-0002).
- Tokens in `command`/`set`: `${PYTHON}` (`sys.executable`),
  `${REPO_ROOT}`, `${DATA_ROOT}`, or `${NAME}` for any set environment
  variable. They resolve when the kit starts, never at import.
- **`kits.toml` is parsed when `core.kit_registry` is imported**, so a
  `kits.toml` error breaks every command, the surrogate MCP server too.
- `core/kit_registry.py:KITS` holds one `KitDecl` per kit: `study_keys`,
  `fixed_keys`, `required_fixed`, `uses_entries`, `step_kit`,
  `check_kit`, `executors`, `launch_stagger_s`, `requires_kerberos`,
  `names_runs_after_config`, `factory` (`"adapters.prodtools:ProdtoolsKit"`,
  relative to `core/`; `None` for a native kit) and `reserved_params`. A
  name clash between native and declared kits raises at import.
  `contract.load_factory` imports the factory when the kit opens.
- **`env_passthrough` exists because** the MCP SDK passes a child only a
  short allowlist of variables. A kit that needs `KRB5CCNAME`, a token
  path or jobsub settings must name them; a missing one is a `KitError`
  when the kit starts.

### KitClient (`core/kits.py`)
- One MCP session per kit per child, on a private asyncio loop in a
  daemon thread.
- Calls run from several threads on one session. The lock covers only
  starting the server and scheduling a call, never the wait for its
  result, so a slow call cannot hold up the others.
- A **generation counter** guards respawns: a "lost server" failure tears
  the session down only if its generation is still current.
- **Lost server** = `MCPError` `CONNECTION_CLOSED` or any non-MCP
  exception while waiting: the session is closed and the next call
  respawns it. Any other `MCPError` is a `KitError` with the session kept;
  `REQUEST_TIMEOUT` is `KitTimeout`, session kept.
- **Text-only replies** (prodtools' tools set no structured output under
  mcp 2.x): a text reply is parsed as JSON and must be an object, else a
  `KitError` naming the tool. Structured content wins when present.

### Retries and the launch check (`core/contract.py`)
- `call_with_retries` / `RETRY_PAUSES_S`: `submit`, `check`, `describe`
  make 3 attempts (pauses 5, 20 s); `status`, `results`, `cancel` make 5
  (5, 20, 60, 180 s, about 4.5 min), so a grid point rides out a short
  server outage. A `KitError` is always retried; a `KitToolError` (the
  server refused) only for the read-only calls, never `submit` or
  `cancel`.
- **The kit error rule:** a kit raises only `KitError` or `ContractError`
  for an expected failure. `KitSet.get` wraps each kit in
  `contract.GuardedKit`, which turns `OSError`, `ValueError`, `KeyError`
  and `subprocess.SubprocessError` into `KitError(kit, call, ...)`, so a
  full disk or a hung `git` breaks only the point. Anything else
  (`TypeError`, `AttributeError`) crashes.
- **`launch_problems(study, kits, *, executor, parallel, config_names,
  board=, adopted=)`** is the one launch check, used by `graph.run`,
  `graph.closed_loop` and `check_study` (refusal = exit 2, each problem
  named). In order:
  1. static checks: executor rules; a grid launch of a kit with
     `requires_kerberos` needs a ticket with 4 h left
     (`GRID_TICKET_SECONDS`); the config-name rule of each kit with
     `names_runs_after_config`. A static problem returns before any kit
     opens;
  2. per kit: `start()`, the contract tools it must offer (a step kit
     `submit`/`status`/`results`; a preflight-only kit just `check`), a
     `serverInfo.version`, the `describe` cross-check if offered, and
     each step's `step_problems`;
  3. the board check (`core/measure.py:board_problems`): the
     `measure_sha` this launch would write against
     `Leaderboard.measure_shas()` (archive plus live rows). A board with
     rows and none of this sha, or a header not the study's
     (`SchemaMismatch`), is refused; say a new `leaderboard.file`. An
     empty or missing board passes.
- A kit that won't start is refused with nothing written (no submit, no
  `point.json`, no `broken.txt`), so an environment problem never becomes
  a failed evaluation.
- **A resumed point is measured as `score` will measure it:** `graph.run`
  passes finished steps' records as `adopted=`; a kit whose steps were all
  adopted is checked at its recorded version, so a retry after a kit bump
  lands on its own board. A kit adopted in part at an old version is
  refused: rerun the x under a new config name.

### `run_steps` (`core/scheduler.py`)
- One LangGraph node schedules every step of a point (LangGraph finishes a
  whole superstep before the next, so one node per step would make
  `mustops_ce` wait for `elebeam_flash`). Ready steps run concurrently in
  a thread pool. A step waits for `Step.upstream`: its `files_from`
  steps, then its `params_from` sources.
- Each step is driven from its own files under
  `GRID_DATA_ROOT/<config>/state/`, so a killed child resumes with no
  second submit: `<step>_results.json` exists -> adopt; `<step>_cluster.txt`
  exists -> poll that handle; neither -> `submit`.
- **`broken.txt` is written at the FIRST step failure.** Running siblings
  are cancelled when their kit offers `cancel` (prodtools does; anakit and
  beamkit do not, so theirs run to completion — remove beamkit jobs with
  `jobsub_rm` if needed). A failed cancel is logged and that step runs on.
- An unexpected exception in a step is logged at once, recorded in
  `broken.txt`, and re-raised only after running siblings finish, so the
  child exits non-zero without killing in-flight grid work.
- Step params (`merge_params`, shared with the pre-check): a param mapped
  from the point may not share a name with a kit setting or a fixed
  value; a clash breaks the point rather than silently replacing a value.

### A broken point is terminal
- `graph.run` refuses (exit 2) a config whose `state/broken.txt` exists,
  printing the recorded reason. `graph.closed_loop` treats `broken.txt`
  like a board row: that name is resolved, skip it.
- **To retry:** delete `broken.txt`. The rerun re-derives, re-renders,
  reuses a saved PASSING pre-check verdict if its basis is unchanged
  (`study_graph.preflight_basis`/`reusable_pass`; a saved failure is never
  reused), adopts existing handles and results — no second submit.
- **A step the kit reported `failed` stays failed:** the handle is
  deterministic (`<config>.<step>`), so polling or resubmitting gets the
  same failed job back. Re-evaluating needs a new config name.

### `measure_sha` and measure identity (`core/study.py`, `core/measure.py`)
- `measure_sha` = SHA-256 over `measure_basis` (`derive`, `geom`, all of
  `kits`, each step's `kit`/resolved `entry`/`files`/`files_from`/
  `params`/`fixed`, `params_from` when non-empty, each objective's
  `metric`+`transform`, each extra metric's `metric`) plus the version of
  every kit a step runs on. Left out: `note`, knob bounds, `fmt`, `noise`,
  `constraints`, `leaderboard`. The preflight kit's version is not hashed
  (it gates a point but produces no numbers).
- **Kit versions are hand-bumped** (since 2026-10-05): `prodtools-adapter/1`,
  `anakit-adapter/2`, `beamkit-adapter/1+fom1`. The anakit checkout
  commit and the beamkit server version are each step's recorded build,
  never part of the version, so an unrelated commit never splits a board.
  Bump an adapter's `VERSION` when a step would measure anew (for anakit,
  when an analysis computes differently). A forgotten bump mixes
  measurements on one board: the operator accepted that.
- `core/measure.py` decides: `recorded_versions` (score's row sha;
  `MixedVersions` on disagreement), `point_versions`, `board_problems`.
  Every live study's `measure_basis_sha` is pinned in
  `tests/test_study.py:PINNED` and `tests/test_measure.py:BASIS`.
- Old boards were re-stamped once by hand (ptg4bl, 2026-10-08) and the
  `_ax` studies moved to new `_upstream` boards; the one-time re-stamp
  tool is deleted.
- `Leaderboard.append` still refuses a row of another `measure_sha` and
  quarantines it (`<board>.quarantine.tsv`), for a board changed mid-run.
- **Resume guard:** `point.json` records `measure_basis_sha`. Rerunning a
  killed point after the study's measurement changed raises
  `PointMismatch` in `derive` (exit 2, nothing written), so old handles
  are never stamped with a new sha.

### v2 rows
- Columns: `config`, knobs, objectives, extra metrics, extra columns,
  then `handles`, `spec_sha`, `measure_sha`, `time`
  (`Leaderboard.header`, `V2_META`). `handles` is sorted `step=handle`
  pairs, e.g. `toy=p1.toy`.
- `"v2"` is the only layout; a study saying `"v1"` is refused at load.
- `spec_sha` hashes the whole study file, `note` included, and the duplicate-row check compares it: after any edit to a live study's file, re-scoring a point that already has a row is refused as a duplicate. Leave a live study's file alone; change it only together with a new board.
- A row with no `measure_sha` raises `RowParseError` (line number).

### `graph.run`
- `python -m graph.run --study S --config C --campaign K --x=v1,v2,...
  [--context k=v] [--executor grid|local] [--parallel N]`: one point,
  `derive -> render -> preflight -> run_steps -> score`
  (`graph/study_graph.py:build_study_graph`).
- **Exit 0:** the point ran (a row landed, or `broken.txt` says why not).
  **Exit 2:** refused before anything ran (unknown study, bad `--x` or
  `--context`, a broken point, a kit that won't start, a config name
  claimed by another point, a `measure_basis_sha` mismatch, another
  runner holding the point). Anything else is a crash.
- Holds `state/run.lock` (flock) while the point runs, taken after the
  launch check; a second `graph.run` on the same config is refused.
- `--executor`/`--parallel` (local only, 1..16) pick prodtools'
  `submit_once` vs `run_local` and the poll cadence; recorded in
  `point.json`, not in `measure_sha`.
- Both runners flush stdout line by line (`run.line_buffered_stdout`), so
  a log redirected to a file is live.

### `graph.closed_loop`
- `python -m graph.closed_loop --study S --q N --max-evals M --picker P
  --name-prefix NAME [--executor ...] [--parallel N] [--stagger s]
  [--check-only]`, on `graph/pool.py:run_rolling`.
- `--context` is parsed once and the launch check must pass before
  anything launches. `--check-only` runs only those checks (the MCP
  `start_campaign` dry run, [service](/drivers/service.md)).
- Each child is `python -u -m graph.run ...`, logging to
  `GRAPH_DATA/closed_loop_logs/<child>.log`. Stagger: the largest
  `launch_stagger_s` of the study's kits (90 s for prodtools and beamkit).
- **Busy names:** a board row or `broken.txt` means resolved; `point.json`
  or any `*_cluster.txt` means maybe in flight or abandoned. Either way the
  name is skipped, never relaunched. Prefer a new `--name-prefix`: a
  freed name gets a new x, and the kit refuses the same handle with other
  params.
- Rows are counted by name against the live board, never from a child's
  own report.
- **Stop launching:** touch `GRAPH_DATA/<prefix>/STOP`; in-flight children
  drain. No credential renewal mid-campaign: the launch check's 4 h ticket
  rule is the only guard.

### Point and campaign records
- **`core/point_dir.py:PointDir` owns a point's `state/` folder;** no
  other module builds a `state/...` path. `broken.txt` (`step <s>:
  <reason>`): first writer wins, `PointDir.broken()` is its only parser.
  `step_state(step)` is the one file-to-state rule (done, failed, working,
  waiting). `write_atomic` and `PointMismatch` live here.
- **`core/campaign_dir.py` owns `<GRAPH_DATA>/<prefix>/`:** `child_name`/
  `parse_child`, and `CampaignDir`. Every `graph.closed_loop` writes
  `campaign.json` once its checks pass (study, args, q, max_evals,
  picker, executor, host, pid, started; `ended`/`exit_code` at the end),
  holds `parent.lock`, and appends one `outcomes.jsonl` line per finished
  child. A live prefix is refused (exit 2). A failed record write is
  logged and the campaign goes on: the record decides nothing.
- **`core/locks.py`:** `hold(path, wait_s=2.0)` (exclusive, retries 2 s
  then `LockBusy`), `wait(path)` (blocking), `held(path)` (a probe).
  flock works across processes on this CephFS mount; fds are not
  inherited, so no kit server or child keeps a parent's lock. Liveness of
  points and campaigns is read from these locks, not from a process scan.

### `params_from` (2026-10-07)
- A step param taken from an earlier step's metric:
  `"params_from": {"<param>": "<step>.<metric>"}` (required key, `{}`
  when unused). The engine copies the value as it is and computes
  nothing; physics stays in the kit.
- `Step.sent_params` and `core/study.py:metrics_read(study, step)` are
  the one answer to "what does a step send / what is read from it"
  (`contract._needs`, `anakit.step_problems`). A mapped param may not
  share a name with another param of the step; `fixed` may still
  override a kit setting.
- Run time (`scheduler.params_from_values`): a missing metric, a bool,
  text, NaN or ±inf fails the step, naming the param; an adopted producer
  passes its recorded value.

### `check_study` (`graph/check_study.py`)
- `python -m graph.check_study <name-or-path> [--x=...] [--executor ...]
  [--parallel N] [--json]`. A path may be a draft anywhere; it is checked
  as if installed (it replaces the study of its name). Exit 0 all
  passed, 1 a check failed, 2 bad command line or target, 3 check_study
  itself broke. Source `activate.sh` first, or the launch check fails on
  the kits.
- Four checks, each passed/failed/skipped: `load` (the file, its name,
  board not used by another study, every other study still loads),
  `artifacts` (every `${ARTIFACT}/` path exists, named by JSON location),
  `launch` (`launch_problems` with the board, as `graph.run`), `geometry`
  (derive -> render -> pre-check at the middle of the knob box, an int
  knob rounded down, or `--x`). A load failure skips the rest; a launch
  failure skips geometry.
- `--json` report: `{study, path, ok, crashed, error, point, checks:
  [{name, status, problems, note, detail}]}`; branch on the exit code,
  never on "Traceback" in stderr.
- Never reuses a verdict: scratch `<GRID_DATA_ROOT>/check_<study>/`
  (emptied only when it holds the `.check_study` marker), one check per
  study at a time (`locks.hold(..., wait_s=0)` on `check_<study>.lock`).
  No submit, no board write. A geometry pre-check takes about 6 min.
- Must not import `modes` at module level: a broken draft on the study
  path would crash the check instead of being reported.
- Not checked: stage-template FCL paths, prodtools' own entry
  validation, corners of the knob box.
- No study-writing skill: baseline agents already wrote correct studies
  from `mode_specs/README.md` ("From draft to launch") and the existing
  studies; the [service](/drivers/service.md) MCP tools wrap check_study.

### prodtools adapter (`core/adapters/prodtools.py`)
- `ProdtoolsKit` talks to two MCP servers from the prodtools checkout
  `$AUTORESEARCH_PRODTOOLS` (`[servers.prodtools_write]`/`_read`).
  `submit_once`, `run_local`, `run_status` and `cancel_run` come from that
  checkout (cvmfs v3.2.0 and v3.3.4 lack them). Every tool it calls needs a
  timeout in kits.toml, or the kit refuses to start.
- **The entry:** `step_params` hands the step's stage template as
  `params["entry"]` to a `uses_entries` kit; `prodtools_entry.entry_for_step`
  fills `{cfg}`/`{geom}` and builds the json2jobdef entry. The run label
  is `kits.prodtools.dsconf` (holds `{cfg}`).
- **`sequential_aux`:** `mustops_ce` (and `ce_dts`) set
  `"sequential_aux": true`, so job i reads staged file i mod N. Without
  it prodtools picks each job's aux input at random by job index:
  sampling with replacement, unbiased but about a third of mubeam's
  statistics lost (σ(sob) of rows before 2026-09-25 includes this).
  `entry_for_step` copies the key into the entry; SAM-catalogue inputs
  (`mubeam`, `elebeam_flash`) leave it unset on purpose.
- **The grid worker runs the shipped prodtools bundle**, not cvmfs
  `current`: the submit tars the submitting checkout's `bin/`+`utils/`
  (`utils/submit.py:bundle_prodtools`, content-addressed
  `prodtools-<sha12>.tar`) and `runjob.sh` runs that. So the worker runs
  whatever `$AUTORESEARCH_PRODTOOLS` holds.
- **Record:** `<GRID_DATA_ROOT>/<config>/prodtools/<step>/record.json`,
  written before the submit (`submitting`, with `submitting_utc`) and
  after. A rerun adopts the run by digest; different params are refused;
  a run created before `submitting_utc` (the name was used before) is a
  loud error; a receipt stuck in `submitting`/`building`/`starting` fails
  loudly (a local run still `starting` after 10 min fails).
- **`quorum`** is required in every step's `fixed`; below it the step
  fails (`{ok}/{njobs} jobs ok, below quorum`).
- **Log scan:** every successful job needs a `.log`; every log is grepped
  for `kits.prodtools.fatal_log_codes` (foilspf: `GeomSolids1001`).
- **Timeouts:** `run_status` `unknown` fails after `UNKNOWN_LIMIT_S` 6 h;
  outputs missing after the jobs ended fail after `STAGEOUT_LIMIT_S`
  30 min.
- **Submit lock:** a grid `submit_once` holds `/tmp/mu2e_submit.<user>.lock`
  (`SUBMIT_LOCK`, also taken by beamkit) — see
  [concurrent-token-contention](/incidents/concurrent-token-contention.md).
  It sets a big campaign's ramp: each `_ax` `submit_once` takes ~2 min
  (each step ships its own content-keyed code tarball), so a host submits
  ~30 steps/hour; at q=20 the first 40 submits take ~80 min.
- **One straggler holds a whole point:** quorum is applied only after
  every job ends. In bpzax01 single jobs ran 6–14 h where their step's
  others took ~1.5 h. A per-job lifetime alone does not fix it: a job past
  `--expected-lifetime` is HELD, not removed, and `run_status` counts held
  jobs as running. Open design item: a tail cutoff.
- **Killing a local run does not stop its mu2e jobs.** prodtools starts
  the runlocal driver in its own session and each job in its own process
  group, so killing `graph.run`, the closed_loop parent or the driver's
  group never reaches the jobs. Stop a run with `kill <pid>` of the
  receipt's driver pid (or `cancel_run`): the driver ends every job's
  group and sends SIGKILL after 10 s, since mu2e ignores SIGTERM during G4
  geometry init.
- **Credentials:** the adapter never renews a Kerberos ticket. The servers
  get `KRB5CCNAME`, `XDG_RUNTIME_DIR` (the bearer token is
  `$XDG_RUNTIME_DIR/bt_u<uid>`) and, for the write server, the five
  `JOBSUB_*` settings from `/etc/profile.d/jobsub_lite.sh` (without
  `JOBSUB_DROPBOX_SERVER_LIST` the tarball publish fails).
- prodtools gotchas: a desc+dsconf pair is used once (a local and a grid
  run of one name share it); `run_local` refuses `firstjob` windows; never
  set `copy_input` (the worker does a SAM locate).
- `TestRealServers` (`tests/test_prodtools_adapter.py`) checks every
  argument dict against the real servers' input schemas; it runs only with
  `AUTORESEARCH_PRODTOOLS` set and `AUTORESEARCH_REAL_KIT_TESTS=1`.

### offline_preflight adapter (`core/adapters/offline_preflight.py`)
- The geometry pre-check. Its rules are in
  `core/adapters/preflight_checks.py` (`check_files`, `stage_workdir`,
  `run_check`, `classify` -> `Verdict(ok, code, reason, notes)`,
  `verify_stopping_target_gdml`, and `run_sourced_bash`, the retry runner
  for transient environment failures).
- It runs from the study's code tarball, unpacked once per content into
  `<GRID_DATA_ROOT>/_code/<sha256>/`, with `MUSE_WORK_DIR` unset;
  workdir `<GRID_DATA_ROOT>/<config>/preflight/` keeps `preflight.log` and
  `asbuilt.gdml`. The as-built GDML check compares every hole radius.
- The message is `<code>: <reason>` plus the check's notes (foils
  verified, overlap count, return code); `ambiguous` fails, with the log's
  last 40 lines. An `OSError` or an unparseable GDML breaks the point.
- Version `offline-preflight-adapter/1`, not part of `measure_sha`.

### anakit adapter (`core/adapters/anakit.py`)
- Drives M. MacKenzie's analysis MCP server, his `main` checked out at
  `$AUTORESEARCH_ANAKIT` (pinned `ANAKIT_PIN_SHA` 3ba8d23, asserted by the
  suite). The server starts with `--musing <kits.anakit.musing>` (`"SimJob
  MDC2025ay"`). Details, the per-electron flash factor and history:
  [anakit](/external/anakit.md).
- **One server per step:** anakit runs one analysis at a time, so
  `submit` starts a fresh server, runs the analysis to the end, writes
  `<GRID_DATA_ROOT>/<config>/anakit/<step>/anakit_result.json` and closes
  it. `status`/`results` read that file. A point resumed mid-analysis runs
  it again. No `describe`, no `cancel`.
- `RUN_TIMEOUT_S = 3000` per analysis; the kits.toml `run_analysis`
  timeout must be at least that plus `CALL_MARGIN_S` (300 s); it is 3600.
- A dirty checkout is refused at open and at every submit; the commit is
  the step's recorded build.
- `step_problems`: the analysis exists in the catalogue (`list_analyses`
  must give `metrics`, `takes_data_files` and `input_kind`; a missing key
  is an error, never a default), every sent
  param is declared and every required one sent, and every metric the
  study reads from the step is offered. EdepAna checks apply only to
  `art_files` analyses.
- **The `_ax` chain** (foilspfbpz_ax, foilsflash_ax, foilspf_nominal):
  prodtools steps `mubeam`, `mustops_ce`, `elebeam_flash`, then anakit
  `stops` (`muon_stop_rate`) -> `ce_edep` (`edep`) -> `sob`
  (`approx_ce_sensitivity`, `stops_per_pot` via `params_from`) and
  `flash` (`edep` on elebeam_flash). `flash_edep` is per generated
  electron; the damage budget is 7.506758e-06, the deployed target's flash
  (foilspf_nominal reproduces it).
  `ce_chain`'s plot step reads `trigger_efficiency_ntuple` (objective
  `n_selected`).
- The fork's settings (`input_correction`, `dio_fraction`, `dio_table`,
  `pot_per_electron`) are refused at load; the KitDecl keeps `analysis`,
  `upstream_eff`, `cosmic_rate_per_s_per_mev`, `trigger_paths`.

### beamkit adapter (`core/adapters/beamkit.py`)
- Runs G4beamline steps through the beamkit MCP server
  ([bo-ptg4bl](/projects/bo-ptg4bl.md)). Grid only, Kerberos required.
- **Settings:** `kits.beamkit` `deck_url`, `deck_ref` (40-hex sha),
  `main_input`, `deck_params`; fixed per step `njobs`, `events_per_job`,
  `quorum`, `plane`, `pdg`. Every other step param is a deck param
  (`key=value` on the g4bl command line); names of adapter settings or
  beamkit worker params are refused (`KitDecl.reserved_params`).
- **`[servers.beamkit]`** runs `${AUTORESEARCH_BEAMKIT}/.venv/bin/beamkit-mcp`
  with `BEAMKIT_PRODTOOLS_ROOT=${AUTORESEARCH_PRODTOOLS}` (the cvmfs
  prodtools has no MCP venv) and passes jobsub's `OTEL_EXPORTER_JAEGER_*`:
  without them `jobsub_q` prints tracing notes into its table and the
  queue count is refused. Claude Code's own beamkit MCP entry points at
  cvmfs prodtools, so its status/outputs tools fail in a session.
- **submit:** `run_beamline`, tag = the step name's letters and digits
  plus 6 hex of its sha256; a step record
  `<grid>/<config>/state/<step>_beamkit.json` lets a rerun adopt the run
  (found by tag if the call failed but the run exists). Submits share the
  prodtools host lock, 90 s apart.
- **status:** working while the queue has idle or running jobs;
  completed when files meet the quorum (`prodtools.meets_quorum`); failed
  otherwise ("k of n files, m held"). An unreadable queue fails after 6 h;
  held jobs count as in flight until they have been all that is left for
  2 h. Polls every 2 min. `make_recoveries` is never called (it acts on
  the whole ledger).
- **results:** uproot reads the tree at `plane` and counts unique
  `(file, EventID, TrackID)` with a listed PDG id per POT (files ×
  `events_per_job`). Version `beamkit-adapter/1+fom<N>`.
- Tests use `tests/fakebeamkit.py` through the real KitClient; a fake
  `klist` on `PATH` passes the Kerberos check.

### toykit (`tests/toykit.py`)
- The reference kit: the full contract plus `debug_*` tools. Jobs are
  files under `$TOYKIT_STATE_DIR` (`${DATA_ROOT}/toykit`), so a restarted
  server finds them.
- `fixed.fail` picks a failure: `failed`, `cancelled`, `bad_state`,
  `missing_metric`, `nonpositive`. `function`: `branin_currin` or
  `reject` (its `check` always fails).
- `tests/fixtures/engine_studies/branin.json`: 2 knobs, 2 objectives, 1
  constraint; `TestBraninCampaign` runs 8 points with real GP picks in
  under a minute.

### Pipeline deleted (Phase C3, 2026-09-28)
- Deleted: `core/pipeline.py`, `harvest.py`, `bo_driver.py`,
  `study_compat.py`, the prodtools exec/submit drivers, `runtime.py`,
  `launch_checks.py`, the old pipeline `graph/` runners and `tools/`.
  `graph/study_run.py` and `study_loop.py` took the names `graph/run.py`
  and `graph/closed_loop.py`. History: [pipeline](/drivers/pipeline.md),
  [bo-driver](/drivers/bo-driver.md), [closed-loop-runner](/drivers/closed-loop-runner.md).
- Kept on purpose: the `desc_fmt` template key and the
  `core/pipeline_templates/` name (renaming either changes every
  `measure_sha`).
- Inert env vars (nothing reads them): `AUTORESEARCH_MODE`,
  `AUTORESEARCH_ELEBEAM_NJOBS`, `AUTORESEARCH_LOCAL` and
  `AUTORESEARCH_LOCAL_*`, `AUTORESEARCH_NO_RUN1B`,
  `AUTORESEARCH_BOTORCH_VENV`. `.env`/LangSmith tracing is not loaded.

## Cross-links
- Related: [service](/drivers/service.md) (MCP study and campaign tools,
  dashboard), [surrogate](/drivers/surrogate.md) (reads the same v2
  boards), [tests](/drivers/tests.md), [anakit](/external/anakit.md),
  [bo-foilspf](/projects/bo-foilspf.md), [bo-ptg4bl](/projects/bo-ptg4bl.md),
  [production-chain-spike-2026-09](/concepts/production-chain-spike-2026-09.md),
  [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (the
  pipeline's constraints; the engine reused its rolling pool only)
- Source files: `kits.toml`, `core/kit_config.py`, `core/kit_registry.py`,
  `core/kits.py`, `core/contract.py`, `core/scheduler.py`,
  `core/study.py`, `core/measure.py`, `core/score.py`,
  `core/leaderboard.py`, `core/boards.py`, `core/point_dir.py`,
  `core/campaign_dir.py`, `core/locks.py`, `core/adapters/`,
  `graph/study_graph.py`, `graph/run.py`, `graph/closed_loop.py`,
  `graph/check_study.py`, `graph/pool.py`, `tests/toykit.py`,
  `tests/textkit.py`, `mode_specs/*.json`
- How-to: `QUICKSTART.md`, `mode_specs/README.md`

## Open questions / TODO
- **Straggler tail cutoff:** complete a step once ok/njobs ≥ quorum and
  the rest run far past the step's median. A per-job lifetime works only
  if a run-time-held job counts as failed, and a lifetime in `fixed`
  would change `measure_sha` unless kept out of the basis.
- **`measure_basis` hashes FCL include names, not their bytes:** editing a
  `core/pipeline_templates/*.fcl` snippet changes what jobs run with no
  `measure_sha` change.
- **A local run is not Kerberos-checked:** the 4 h check runs only for
  `--executor grid`, but a local run still streams inputs from `/pnfs`
  over xrootd; a ticketless local run fails later, inside a step.
- **Launch checks the pipeline had and the engine lacks:** data quota,
  config name free of a prior claim, no stale grid cluster.
- After a runner restart, orphaned in-flight children's x are not passed
  to the picker as pending (`graph/closed_loop.py`).
- A leftover `STOP` file makes a relaunch under the same prefix launch
  nothing, silently.
- A picker failure mid-campaign surfaces only after in-flight children
  finish (`graph/pool.py`).
