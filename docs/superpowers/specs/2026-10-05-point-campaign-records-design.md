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

### `core/point_dir.py` — the point record

Stdlib only, no project imports (the service imports it without `modes`).
`PointDir(grid_root, config)` owns `<grid_root>/<config>/state/`.

- **Paths:** `state`, and the file of each record. Callers never build a
  `state/...` path themselves.
- **point.json:** `claim(point)` writes it, or checks that the existing one
  matches. It keeps today's refusals and messages, moved from
  `study_graph.node_derive`: no `measure_basis_sha`, a changed measurement,
  no executor, another executor, another point. `PointMismatch` moves here.
  `point()` reads it.
- **Steps:**
  - `write_handle(step, h)` and `handle(step)`;
  - `write_status(step, status)`, written for the dashboard only;
  - `write_results(step, record)`, `results(step)`, and
    `adopted(step_names)` → `{step: record}`.
- **broken.txt:** `mark_broken(reason, step=None)` writes the text
  `step <step>: <reason>`, or `<reason>` alone when there is no step. The
  format is unchanged. The first writer wins: it does nothing if the file
  exists, and returns whether it wrote. `broken()` → `Broken(step, text)`
  or `None`: the only parser of that text.
- **Scoring files:** `write_summary(...)`, `write_result(result)` and
  `result()` (`evaluate_result.json`). The dashboard takes a point's value
  from `result()` instead of loading the board a second time.
- **Pre-check files:** the paths of `derived.json`, `geom.txt` and
  `preflight_verdict.json` (check_study reads the verdict).
- **Liveness:** `hold_run_lock()` takes an exclusive, non-blocking flock
  on `state/run.lock` and holds it until the process exits. `running()`
  probes it.
  - `graph.run` takes it after its refusals and before anything runs.
  - If another `graph.run` holds it, the point is refused (exit 2): two
    runners on one config.
- **Step state for readers:** `step_state(step, now, running)` is the
  dashboard's rule today, moved here with `STALL_FLOOR_S`:
  - done if the step has results;
  - failed if its status is failed or cancelled, or `broken()` names it;
  - working if it has a status or a handle;
  - waiting otherwise;
  - a working step stalls when its last poll is older than
    max(3·poll_s, 600 s).
- **Busy:** `started()` is true when `point.json` or any handle exists.
  `busy_reason` in closed_loop keeps its messages and asks `PointDir`.

The writers move onto it:
- **scheduler:** handle, status, results and broken; adopted records on
  resume.
- **study_graph:** claim, derived, geom, the verdict and broken.
- **score:** broken, summary and result.
- **run.py:** the broken refusal and the adopted records.

`beamkit`'s own `state/<step>_beamkit.json` stays where it is; it belongs
with the kit-interface work.

### `core/campaign_dir.py` — the campaign record

Stdlib only. It holds three things.

- **Child names:** `child_name(prefix, i)` (moved from `graph/pool.py`,
  which imports it), `parse_child(name)` → `(prefix, i)` or `None`, matching
  `<prefix>R<digits>_00` exactly, and `is_child(prefix, name)`. Every
  producer and parser uses these.
- **`CampaignDir(graph_data, prefix)`** owns `<graph_data>/<prefix>/`:
  - `start(record)`:
    - refuses (`CampaignBusy`) if another parent holds `parent.lock`;
    - otherwise takes that flock for the life of the process and writes
      `campaign.json`, replacing a record left by an earlier, ended run of
      the same prefix (`outcomes.jsonl` keeps appending).
    - The record holds `prefix, study, args, q, max_evals, picker,
      executor, parallel, context, stagger, host, pid, started`.
  - `finish(exit_code)` adds `ended` and `exit_code` to the record.
  - `record()` reads it. A campaign.json written by the MCP launcher before
    this change has `study` and `args`; the other fields are absent and
    read as `None`.
  - `append_outcome(outcome)` adds one line to `outcomes.jsonl`:
    `{name, x, rc, reason, row_landed, broken, time}`.
    `outcomes()` → `{name: last line}`.
  - `alive()` is true while `parent.lock` is held, or `lock` is held (the
    MCP wrapper's lock, which covers activate.sh before closed_loop
    starts).
  - `exit_code()` gives the record's `exit_code`, else the MCP `rc` file.
  - `stopping()` and `stop()` handle the STOP file.
  - `write_launch(info)` and `launch()` handle the MCP launch record,
    `launch.json`, created with O_EXCL.
- **Locks:** `hold_lock(path)` and `lock_held(path)`, the flock helpers
  `point_dir` uses too. `service/jobs.lock_held` becomes this one.

### The runners

- **`graph.closed_loop`:**
  - after the launch checks pass, and not with `--check-only`, it calls
    `CampaignDir.start(...)`, refusing with exit 2 on `CampaignBusy`;
  - then it prints the banner as today;
  - it passes `on_outcome=camp.append_outcome` to `run_rolling`;
  - `finish(rc)` runs on return.
- **`graph/pool.run_rolling`** gains `on_outcome=None`. It is called with
  each Outcome, in the main loop and the drain alike, after it is logged.
- **`graph.run`** holds the point's run lock from just after its refusals
  until it exits.

### The readers

- **`service/campaigns.py`:**
  - The process scan (`_processes`, `_scan`) is deleted.
  - `campaign_status(prefix)` reads `CampaignDir` (study, alive, exit code,
    stopping, launched_by: `"mcp"` when `launch.json` exists or the record
    has a `command` key, which only the old MCP launcher wrote, else
    `"shell"`), plus `PointDir` per child and the board.
  - Child state, one rule in one function:
    - scored if the board has its row;
    - else broken if `PointDir.broken()`;
    - else running if `PointDir.running()`;
    - else "ended without a row".
    - Each child also carries its `outcome` reason when one exists.
  - `campaign_status()` with no prefix lists every `*/campaign.json`.
  - `_launch_refusals` asks `alive()`, the STOP file, the record and the
    child logs: a prefix with a `campaign.json` or a `launch.json` is used.
  - `stop_campaign` counts running children by `PointDir.running()`.
  - `_launch` writes `launch.json` and reports "launched" once
    `campaign.json` exists. Refusals are still read from the log on a
    nonzero exit, because that is closed_loop's only refusal channel and
    it is out of scope.
  - `_load_study` becomes public as `load_study`.
- **`service/dashboard.py`:**
  - It uses `campaign_dir.parse_child`, `CampaignDir.record()` for q and
    max-evals, `PointDir.point()`, `step_state()` and `result()`, and
    `svc.load_study`.
  - `CHILD_RE`, `BROKEN_RE`, `_mark_broken`, `_step`, `_argv`,
    `_read_status`, `STALL_FLOOR_S` and its imports of `_flag` and private
    methods are deleted.
- **`graph/check_study.py`** uses `PointDir` for its state folder and the
  verdict.

## Errors

- A malformed or unreadable record file is reported, never skipped. A
  reader that gets `ValueError` or `OSError` from `point()`, `record()` or
  `outcomes()` puts the error in its output, as the dashboard does today
  with an unreadable status file.
- A missing file is `None`, and an absent outcomes file is `{}`.
- A write failure raises, except `write_status`, whose failure the
  scheduler already logs and survives (2026-10-04 fix).

## Testing

- **`tests/test_point_dir.py`:**
  - claim, with each mismatch;
  - mark_broken: first writer wins, with and without a step;
  - broken() round-trips both forms and a legacy file;
  - adopted();
  - step_state (done, failed by status, failed by broken, working by
    handle or by status, waiting, stall);
  - run lock: held while the process lives, released on exit, a second
    holder refused.
- **`tests/test_campaign_dir.py`:**
  - the name codec, including `foo` against `foo2R00_00` and `_01`;
  - start/record/finish;
  - a second start refused while the first holds the lock;
  - a legacy record;
  - outcomes append/read;
  - alive through either lock;
  - exit_code from the record or `rc`.
- **Existing tests** keep their assertions. The ones that monkeypatch
  `_processes` or write state files by hand move to real locks and to
  `PointDir` writers.
- **closed_loop:** `campaign.json` and `outcomes.jsonl` are written, and a
  second parent on a live prefix is refused.
- **run:** a second runner on a running config is refused.
- **Acceptance:**
  - a local branin campaign from the shell, then `campaign_status`, the
    MCP `start_campaign` of a second one in a sandbox data root, and
    `python -m service.dashboard --once` over both;
  - the `_ax` `measure_basis_sha` values are unchanged.

## Out of scope

- closed_loop's refusal text channel;
- the kit interface (beamkit's file in `state/`, the handle string);
- the measurement-identity work (survey candidate C);
- `campaign_status`'s list-or-dict return.
