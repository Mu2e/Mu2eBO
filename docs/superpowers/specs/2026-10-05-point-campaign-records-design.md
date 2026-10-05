# Point and campaign records — design

2026-10-05. Candidates A and B of the architecture survey of 2026-10-05
(operator: "OK, go"; design "OK").

## Goal

Every tool that looks at a point or a campaign sees the same thing. Two
small modules own the files: one owns a point's `state/` folder, one owns a
campaign's folder. Writers and readers both go through them, so a rule
lives in one place.

Nothing about measurement changes: no `measure_sha`, row or board changes.
File formats stay readable by hand, and points and campaigns written before
this change still read.

## Today

- A point's `<grid>/<config>/state/` is written by `core/scheduler.py`,
  `graph/study_graph.py` and `core/score.py`. It is read by `graph/run.py`,
  `graph/closed_loop.py:busy_reason`, `graph/check_study.py`,
  `service/campaigns.py` and `service/dashboard.py`. Each rebuilds the paths
  and its own rules.
- `broken.txt` has three writers with different overwrite rules (the
  scheduler and `score` always overwrite, `study_graph` only when absent).
  The dashboard recovers the failing step with a regex (`BROKEN_RE`).
- Only an MCP-launched campaign writes `campaign.json`. For a shell launch
  the service guesses the study from argv or a child's `point.json`, and q
  and max-evals from argv (`dashboard._argv`, `campaigns._flag`).
- Liveness is a scan of this user's `/proc/*/cmdline`. A point still
  running on another host reads as "ended without a row".
- Child names have one producer (`pool.child_name`) and two parsers that
  disagree (`campaigns.is_child`: `R\d+_00`; `dashboard.CHILD_RE`:
  `(.+)R\d+_\d+`, greedy).
- The pool's Outcome is only logged as text. The MCP launcher learns
  "launched" by finding the `[closed_loop] study=` banner in the log.
- The dashboard calls `CampaignService._campaign_json`, `._processes` and
  `._load_study`, plus `campaigns._flag`.

## Design

### `core/locks.py` — the flock helpers

Stdlib only. Both record modules and `service/jobs.py` use it.

- `hold(path)` is a context manager. It takes an exclusive flock on `path`
  and holds it for the `with` block.
  - It waits up to 2 s, retrying, before raising `LockBusy`. A reader's
    probe takes a shared lock for about 0.3 ms, so a holder that gave up at
    once could be refused by a dashboard sweep.
- `held(path)` probes without blocking. It is `service/jobs.lock_held`,
  moved here; jobs.py imports it.

### `core/point_dir.py` — the point record

Stdlib only, plus `core/locks.py`. The service imports it without `modes`.
`PointDir(state_dir)` owns one point's `state/` folder;
`PointDir.of(grid_root, config)` builds it from the roots. `run_steps`,
`build_study_graph` and `score` keep their `state_dir` parameters and wrap
it themselves, so their callers and tests do not change.

- **Paths:** `state`, and the file of each record. Callers never build a
  `state/...` path themselves.
- **point.json:** `claim(point)` writes it, or checks that the existing one
  matches. It keeps today's refusals and messages, moved from
  `study_graph.node_derive`: no `measure_basis_sha`, a changed measurement,
  no executor, another executor, another point. `PointMismatch` moves here.
  `point()` reads it.
- **Steps:**
  - `write_handle(step, h)` and `handle(step)`;
  - `write_status(step, status)` and `status(step)`, the latter returning
    `(record, error)`, written for the dashboard only;
  - `write_results(step, record)`, `results(step)`, and
    `adopted(step_names)` → `{step: record}`.
- **broken.txt:** `mark_broken(reason, step=None)` writes the text
  `step <step>: <reason>`, or `<reason>` alone when there is no step. The
  format is unchanged.
  - The first writer wins: it does nothing if the file exists, and returns
    whether it wrote.
  - Nothing relies on today's overwrite: graph.run refuses a point that
    already has broken.txt, and a retry deletes the file first.
  - `broken()` → `Broken(step, text)` or `None`, the only parser of that
    text.
- **Scoring files:** `write_summary(...)` and `write_result(result)`.
- **Pre-check files:** the paths of `derived.json`, `geom.txt` and
  `preflight_verdict.json` (check_study reads the verdict).
- **Liveness:**
  - `run_lock()` is `locks.hold(state/run.lock)`. `running()` probes it.
  - `ever_ran()` is true when `run.lock` exists: a run under this code
    started here.
- **Step state:** `step_state(step)` maps the step's files to one of four
  states, plus the message, progress, last poll time, `poll_s` and any
  read error:
  - done if the step has results;
  - failed if its status is failed or cancelled, or `broken()` names it;
  - working if it has a status or a handle;
  - waiting otherwise.
  - The stall threshold, `STALL_FLOOR_S` and max(3·poll_s, 600 s), stays
    in the dashboard: it is a display rule.
- **Busy:** `started()` is true when `point.json` or any handle exists.
  `busy_reason` in closed_loop keeps its messages and asks `PointDir`.

The writers move onto it:
- **scheduler:** handle, status, results and broken; adopted records on
  resume.
- **study_graph:** claim, derived, geom, the verdict and broken.
- **score:** broken, summary and result.
- **run.py:**
  - the broken refusal and the adopted records;
  - the run lock, in a `with` block in `main()`;
  - when the lock is taken: after `launch_problems`, before
    `graph.invoke`, so a refused point still writes no folder;
  - on `LockBusy` it refuses (exit 2): two runners on one config;
  - with the lock held it checks `broken()` again before running.

`beamkit`'s own `state/<step>_beamkit.json` stays where it is; it belongs
with the kit-interface work.

### `core/campaign_dir.py` — the campaign record

Stdlib only, plus `core/locks.py`.

- **Child names:**
  - `child_name(prefix, i)` moves here from `graph/pool.py`, which
    imports it.
  - `parse_child(name)` → `(prefix, i)` or `None`. It matches
    `<prefix>R<digits>_00` and accepts only a name `child_name` would
    produce: `fooR5_00` and `fooR00_01` do not parse.
  - `is_child(prefix, name)`.
  - Every producer and parser uses these.
- **`CampaignDir(graph_data, prefix)`** owns `<graph_data>/<prefix>/`:
  - **`start(record)`** is a context manager. It holds `parent.lock`, via
    `locks.hold`, for the `with` block.
    - On `LockBusy` it raises `CampaignBusy`: another parent is alive on
      this prefix.
    - It writes `campaign.json`, replacing a record left by an earlier,
      ended run of the same prefix (`outcomes.jsonl` keeps appending).
    - A failed write raises. Nothing has launched yet, so closed_loop
      refuses.
    - The record holds `prefix, study, args, q, max_evals, picker,
      executor, parallel, context, stagger, host, pid, started`.
  - **`finish(exit_code)`** adds `ended` and `exit_code` to the record.
  - **`record()`** reads it. A campaign.json the old MCP launcher wrote has
    `prefix, study, args, command, pid, started`. For those, `record()`
    fills `q`, `max_evals` and the other launch fields from its `args`,
    the record's own argv, so a reader never parses argv itself.
  - **`append_outcome(outcome)`** adds one line to `outcomes.jsonl`:
    `{name, x, rc, reason, row_landed, broken, time}`. `outcomes()` →
    `{name: last line}`.
  - **`alive()`** is true while `parent.lock` is held, or `lock` is held
    (the MCP wrapper's lock, which covers activate.sh before closed_loop
    starts).
  - **`exit_code()`** gives the record's `exit_code`, else the MCP `rc`
    file.
  - **`launched_by()`** is `"mcp"` when `launch.json` exists or the record
    has a `command` key; `"shell"` when only `campaign.json` exists; `None`
    when neither does.
  - **`stopping()` and `stop()`** handle the STOP file.
  - **`write_launch(info)` and `launch()`** handle the MCP launch record,
    `launch.json`, created with O_EXCL. It keeps the wrapper's pid, which
    `stop` signals.

### The runners

- **`graph.closed_loop`:**
  - after the launch checks pass, and not with `--check-only`, it enters
    `CampaignDir.start(...)`;
  - `CampaignBusy` or a failed record write prints `[closed_loop]
    REFUSED: ...` and exits 2;
  - then it prints the banner as today;
  - it passes `on_outcome=camp.append_outcome` to `run_rolling`;
  - `finish(rc)` runs in a `finally` with the real exit code: 1 on an
    exception.
  - A failure in `append_outcome` or `finish` (a full quota) is logged
    once, loudly, and the campaign goes on: the record decides nothing,
    the same reason as the 2026-10-04 status-file fix.
- **`graph/pool.run_rolling`** gains `on_outcome=None`. It is called with
  each Outcome, in the main loop and the drain alike, after it is logged.
- **The children** keep Popen's default `close_fds`, so no child inherits
  `parent.lock` or the MCP lock. Kit servers are started without
  `pass_fds`, so none keeps `run.lock`.

### The readers

- **`service/campaigns.py`:**
  - The process scan (`_processes`, `_scan`, `_flag`) is deleted.
  - `campaign_status(prefix)` reads `CampaignDir`: study, alive, exit
    code, stopping, launched_by.
  - The study comes from the record, else from a child's `point.json` (the
    one fallback, for old shell campaigns).
  - Child state, one rule in one function:
    - scored if the board has its row;
    - else broken if `PointDir.broken()`;
    - else running if `PointDir.running()`;
    - else starting if the campaign is alive, the child has no outcome
      line and `PointDir.ever_ran()` is false;
    - else "ended without a row".
  - Each child also carries its `outcome` reason when one exists, its x
    from `point()`, and its objective values from the board, which is
    already loaded. The dashboard then reads the board through
    `campaign_status` only.
  - `campaign_status()` with no prefix lists every `*/campaign.json`.
  - `_launch_refusals` asks `alive()`, the STOP file, `launched_by()` and
    the child logs. A prefix that was ever used is refused.
  - `stop_campaign` counts running children by `PointDir.running()`. It
    warns "no sign of a campaign" when `launched_by()` is `None` and no
    child log exists.
  - `_launch`:
    - writes `launch.json`;
    - reports "launched" once `campaign.json` exists;
    - still reads refusals from the log on a nonzero exit, because that is
      closed_loop's only refusal channel and it is out of scope.
  - `_load_study` becomes public as `load_study`.
- **`service/dashboard.py`:**
  - It uses `campaign_dir.parse_child`, `CampaignDir.record()` for q and
    max-evals, `PointDir.step_state()`, `campaign_status` for points, x and
    values, and `svc.load_study`.
  - `CHILD_RE`, `BROKEN_RE`, `_mark_broken`, `_argv` and `_read_status`
    are deleted, as are its imports of `_flag` and of private methods.
  - Its `_step` keeps only the stall rule.
- **`graph/check_study.py`** uses `PointDir` for its state folder and the
  verdict.
- **Docs and text that describe these files or the pgrep advice:**
  - README "Where things land";
  - `wiki/drivers/service.md` and `wiki/drivers/contract-engine.md`;
  - `service/server.py` instructions;
  - the pgrep advice in `busy_reason` and in the pool's stall warning,
    which become "`run.lock` is held";
  - `.claude/commands/closed-loop-status.md` and
    `.claude/commands/closed-loop-harvest.md`;
  - CONTEXT.md gains **Point record** and **Campaign record**.

## Errors

- A malformed or unreadable record file is reported, never skipped. A
  reader that gets `ValueError` or `OSError` from `point()`, `record()` or
  `outcomes()` puts the error in its output, as the dashboard does today
  with an unreadable status file.
- A missing file is `None`, and an absent outcomes file is `{}`.
- Write failures:
  - **raise:** `claim`, `mark_broken`, handle, results, summary and result
    writes, and `start`;
  - **logged once, the run goes on:** `write_status`, `append_outcome` and
    `finish`. The first is already logged by the scheduler; the other two
    are logged by closed_loop.

## Rollout

Merge only when no campaign is running. Points and parents started by
older code hold no lock, so they would read as ended.

## Testing

- **`tests/test_locks.py`:**
  - hold/held;
  - a holder waits out a reader's probe instead of refusing;
  - LockBusy while another process holds the lock;
  - released on SIGKILL.
- **`tests/test_point_dir.py`:**
  - claim, with each mismatch;
  - mark_broken: first writer wins, with and without a step;
  - broken() round-trips both forms and a legacy file;
  - adopted();
  - step_state: done, failed by status, failed by broken, working by
    handle or by status, waiting, an unreadable status;
  - running() and ever_ran().
- **`tests/test_campaign_dir.py`:**
  - the name codec, including `foo` against `foo2R00_00`, `fooR5_00` and
    `fooR00_01`;
  - start/record/finish;
  - a second start refused while the first is alive;
  - a legacy MCP record giving q and max_evals from its args;
  - outcomes append/read;
  - alive through either lock;
  - exit_code from the record or `rc`;
  - launched_by in all three cases.
- **closed_loop:**
  - campaign.json and outcomes.jsonl are written;
  - a second parent on a live prefix is refused with `REFUSED`;
  - a failing `append_outcome` does not stop the pool;
  - `finish` records 1 when the pool raises.
- **run:**
  - a second runner on a running config is refused;
  - a refused point writes no folder (the existing test);
  - SIGKILL of `graph.run` while its toykit server lives leaves
    `running()` False.
- **campaigns/dashboard:**
  - a starting child (live parent, no run.lock yet) reads "starting";
  - an old shell campaign gets its study from a child's point.json;
  - an old MCP record shows q and max-evals.
- **Existing tests:** each keeps what it checks, but these change how they
  set up:
  - the ones that fake `_processes` or an argv parent hold real locks
    instead;
  - the ones that write state files by hand use `PointDir`;
  - TestBusyNames builds its folders with `PointDir`.
- **Acceptance:**
  - a local branin campaign from the shell, then `campaign_status`;
  - the MCP `start_campaign` of a second one in a sandbox data root;
  - `python -m service.dashboard --once` over both;
  - a cross-host probe: `running()` checked from a second node against a
    point running on mu2esrv01, if a second node is reachable, otherwise
    reported as unverified;
  - the `_ax` `measure_basis_sha` values are unchanged.

## Out of scope

- closed_loop's refusal text channel;
- the kit interface (beamkit's file in `state/`, the handle string);
- the measurement-identity work (survey candidate C);
- `campaign_status`'s list-or-dict return.
