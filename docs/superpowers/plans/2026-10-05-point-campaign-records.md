# Point and Campaign Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One module owns a point's `state/` folder and one owns a
campaign's folder. Every writer and reader goes through them, so every
tool sees the same thing.

**Architecture:**
- **Three new stdlib-only modules in `core/`:** `locks.py` (flock helpers),
  `point_dir.py` (`PointDir`) and `campaign_dir.py` (child names,
  `CampaignDir`).
- **The writers:** `scheduler`, `study_graph`, `score`, `graph.run`,
  `graph.closed_loop` and the pool move onto them.
- **The readers:** `service/campaigns.py` and `service/dashboard.py` read
  only them; the process scan is deleted.

**Tech Stack:** Python 3.12 stdlib (`fcntl.flock`, `json`, `contextlib`), unittest.

**Spec:** `docs/superpowers/specs/2026-10-05-point-campaign-records-design.md` (tip 51a8c11)

## Global Constraints

- New `core/` modules are stdlib only.
  - Imports between them use the repo's dual pattern:
    `if __package__: from core import locks` / `else: import locks`.
  - Nothing in them imports `modes`.
- No `measure_sha`, row, board or `measure_basis_sha` change.
  - Baseline: before Task 1, record `{name: s.measure_basis_sha}` for every
    loaded study in the ledger.
  - Compare after Task 8.
- File formats stay the same: point.json, `<step>_{cluster.txt,
  status.json,results.json}`, the broken.txt text, summary.json and
  evaluate_result.json.
- `write_atomic` keeps working as `scheduler.write_atomic`; the adapters
  import it from there.
- Test command: `source ./activate.sh >/dev/null 2>&1; PYTHONPATH=
  "$AUTORESEARCH_PYTHON" -m unittest <modules>`. The full suite is
  `-m unittest discover -s tests -t .` (about 9 min). Keep long output in
  the workspace.
- There is no grid contact anywhere in this plan.
- Merge only when no campaign is running (spec, "Rollout"): points and
  parents started by older code hold no lock.

## Review Focus

1. **A truncated last line in `outcomes.jsonl`** (parent killed mid-append):
   `campaign_status` reports an error for that campaign and still lists
   its children. Other campaigns are unaffected. Test: Task 6.
2. **A malformed `campaign.json`:** `campaign_status(prefix)` lists the
   children with the error, and `campaign_status()` lists the prefix with
   an `error`. Test: Task 6.
3. **A shell relaunch of an ended prefix:** `start` succeeds and replaces
   the record, `outcomes.jsonl` keeps both runs, and busy names are still
   skipped. Test: Task 5.
4. **Probing a point that never started:** `running()`/`ever_ran()` are
   False and no folder is created. Test: Task 2.
5. **`graph.run` SIGKILLed while its toykit server lives:** `running()` is
   False afterwards. Test: Task 3.

---

### Task 1: `core/locks.py`

**Files:**
- Create: `core/locks.py`, `tests/test_locks.py`
- Modify: `service/jobs.py`: `lock_held` becomes `from locks import held as
  lock_held` (keep the name, since `service/campaigns.py` and tests use it)

**Interfaces:**
- Produces:
  - `class LockBusy(RuntimeError)`;
  - `hold(path: Path, wait_s: float = 2.0) -> ContextManager[None]`: an
    exclusive flock on `path` (the file is created; its parent must
    exist), retried every 0.05 s until `wait_s`, then `LockBusy`;
  - `held(path: Path) -> bool`: today's `jobs.lock_held` body (False for
    a missing file).

- [ ] **Step 1: Write the failing tests.** In `tests/test_locks.py`:
  - `test_hold_then_held`: inside `with locks.hold(p)`, `held(p)` is True;
    after the block it is False. `held(missing)` is False and creates
    nothing.
  - `test_a_second_holder_is_refused`: hold it in a child process
    (`python -c` holding for 5 s, then a ready file); `hold(p, wait_s=0.3)`
    raises `LockBusy`.
  - `test_a_holder_waits_out_a_probe`: a thread takes `LOCK_SH` for 0.2 s;
    `hold(p, wait_s=2)` succeeds.
  - `test_released_on_sigkill`: SIGKILL the child holder; `held(p)` is
    False.
- [ ] **Step 2: Run them.** Expected: ImportError (no `locks`).
- [ ] **Step 3: Implement** `core/locks.py`, and point `service/jobs.py`
  at it (it already puts `core/` on `sys.path`).
- [ ] **Step 4: Run.** `tests.test_locks tests.test_service_jobs` (or
  whichever test file covers `jobs`; `grep -l lock_held tests/`).
  Expected: OK.
- [ ] **Step 5: Commit** "locks: the flock helpers, with a holder that
  waits out a reader's probe".

### Task 2: `core/point_dir.py`

**Files:**
- Create: `core/point_dir.py`, `tests/test_point_dir.py`

**Interfaces:**
- Consumes: `locks.hold`, `locks.held`.
- Produces, in `core/point_dir.py`:
  - **Moved here:** `write_atomic(path, text)` from scheduler (scheduler
    re-imports it), and `class PointMismatch(ValueError)` from study_graph
    (study_graph re-imports it, since run.py imports it from there).
  - `Broken(NamedTuple)`: `step: Optional[str]`, `reason: str`, `text: str`.
  - **Constants:** `POINT="point.json"`, `BROKEN="broken.txt"`,
    `RUN_LOCK="run.lock"`, `SUMMARY="summary.json"`,
    `RESULT="evaluate_result.json"`, `VERDICT="preflight_verdict.json"`,
    `DERIVED="derived.json"`, `GEOM="geom.txt"`.
  - **`class PointDir`:**
    - `PointDir(state: Path)`, `PointDir.of(grid_root, config)`,
      `.state`, `.path(name) -> Path`.
    - point.json: `claim(point: dict) -> None` (mkdir; write, or refuse
      with PointMismatch, moving the five checks and messages of
      `study_graph.node_derive`, keyed on `self.path(POINT)`) and
      `point() -> Optional[dict]` (bad JSON raises ValueError).
    - Steps:
      - `handle(step) -> Optional[str]` (stripped) and
        `write_handle(step, h)` (writes `h + "\n"`);
      - `status(step) -> (Optional[dict], Optional[str])` (today's
        `dashboard._read_status`) and `write_status(step, d)`;
      - `results(step) -> Optional[dict]`, `write_results(step, record)`
        (`indent=1, sort_keys=True`), and `adopted(steps) -> Dict[str,
        dict]`.
    - broken.txt: `mark_broken(reason, step=None) -> bool` (writes
      `f"step {step}: {reason}\n"` or `reason + "\n"`; False if the file
      exists) and `broken() -> Optional[Broken]` (first line;
      `re.match(r"step (\S+): (.*)")` gives the step and reason, else
      step None and reason = line).
    - Scoring: `write_summary(d)` and `write_result(d)`.
    - Liveness: `run_lock() -> ContextManager` (mkdir state, then
      `locks.hold(path(RUN_LOCK))`), `running() -> bool`,
      `ever_ran() -> bool` and `started() -> bool` (point.json or any
      `*_cluster.txt`).
    - `step_state(step) -> dict` with keys `state`
      (waiting/working/done/failed), `message`, `progress`, `error`,
      `handle_mtime`, `poll_time` and `poll_s`. The rules are the
      dashboard's `_step` plus `_mark_broken`: a broken() naming the step
      makes it failed with broken's reason as the message. A status
      record whose `time`/`poll_s` are not numbers sets `error` to
      `"bad status record: ..."`.

- [ ] **Step 1: Write the failing tests** in `tests/test_point_dir.py`
  (`PointDir(tmp/"state")`):
  - `test_claim_writes_then_matches`; `test_claim_refusals`: one subTest
    per mismatch (no measure_basis_sha, changed basis, no executor, other
    executor, other x), asserting today's message fragments (copy them
    from `tests/test_run.py` TestRefusals/TestExecutorFlag).
  - `test_mark_broken_first_writer_wins`: True, then False; the text stays
    the first.
  - `test_broken_forms`: `step b: KitError: boom` gives `("b", "KitError:
    boom")`; `preflight: fail_managed` gives `(None, "preflight:
    fail_managed")`; a legacy `broken\n` gives `(None, "broken")`; no file
    gives None.
  - `test_adopted_reads_only_finished_steps`.
  - `test_step_state`: done; failed by status; failed by broken (status
    says working); working by a handle alone; working by status; waiting;
    an unreadable status (`{`) is working with an error naming the file;
    a bad `time` gives an error "bad status record".
  - `test_liveness`: `running()`, `ever_ran()` and `started()` are False
    on a missing state dir, and nothing is created (Review Focus 4). Inside
    `run_lock()`, `running()` is True and `ever_ran()` is True; after it,
    `running()` is False and `ever_ran()` is still True.
- [ ] **Step 2: Run.** Expected: ImportError.
- [ ] **Step 3: Implement** `core/point_dir.py`.
- [ ] **Step 4: Run** `tests.test_point_dir`. Expected: OK.
- [ ] **Step 5: Commit** "point_dir: one owner for a point's state folder".

### Task 3: The writers and point readers use `PointDir`; graph.run holds the run lock

**Files:**
- Modify:
  - `core/scheduler.py`: `run_steps` and `_run_one` build
    `pd = PointDir(state_dir)` and use `adopted`, `handle`/`write_handle`,
    `write_status`, `write_results` and `mark_broken(message,
    step=failed.step)`. `write_atomic` is imported from point_dir.
  - `graph/study_graph.py`:
    - `node_derive` calls `pd.claim(point)`;
    - derived and geom go through `pd.path`, and the verdict through
      `pd.path(VERDICT)`;
    - `broken(reason, step=None)` uses `pd.mark_broken`;
    - `node_run_steps` passes `step=`;
    - re-export `PointMismatch`.
  - `core/score.py`: `pd.mark_broken(f"score: {exc}")` (keep the text),
    `write_summary` and `write_result`.
  - `graph/run.py`:
    - `pd = PointDir.of(GRID_DATA_ROOT, args.config)`;
    - the broken refusal uses `pd.broken().text`, and adopted uses
      `pd.adopted(...)`;
    - after `launch_problems` passes, enter `pd.run_lock()` around
      `graph.invoke`. On `LockBusy`, refuse: `f"another graph.run holds
      {pd.path(RUN_LOCK)}: this point is already running"`;
    - inside the lock, re-check `pd.broken()` and refuse as before.
  - `graph/closed_loop.py`:
    - `state_dir(name)` is removed; `busy_reason` uses
      `PointDir.of(paths.GRID_DATA_ROOT, name)` (`broken()`,
      `started()`);
    - `broken=` uses `.broken() is not None`;
    - the pgrep advice becomes: `nothing runs it (\`flock -n
      {sd}/run.lock true\` succeeds)`.
  - `graph/check_study.py`: `PointDir.of(paths.GRID_DATA_ROOT,
    config).state` and `pd.path(VERDICT)`.
- Test:
  - `tests/test_run.py`: add the two tests below.
  - `tests/test_closed_loop.py`:
    - `TestBusyNames.touch` builds `paths.GRID_DATA_ROOT/name/"state"`
      directly;
    - the pgrep assertions (lines ~79, ~355) assert `"run.lock"` and
      `"flock -n"` instead.

**Interfaces:**
- Consumes: Task 2's `PointDir`, `write_atomic`, `PointMismatch`,
  `VERDICT` and `RUN_LOCK`.
- Produces: `closed_loop.busy_reason(name, board_names)`, with an unchanged
  signature.

- [ ] **Step 1: Write the failing tests** in `tests/test_run.py`:
  - `test_a_second_runner_on_a_running_point_is_refused`:
    - hold `PointDir.of(grid, "p1").run_lock()` in the test;
    - `run.main([... "--config", "p1" ...])` on the toy study returns 2;
    - stdout says "already running";
    - no `toy_cluster.txt` is written.
  - `test_a_killed_runner_frees_its_point` (Review Focus 5):
    - Popen `graph.run` on a slow toy (`fixed.delay_s` 30) in its own
      session;
    - wait for `toy_cluster.txt`; `running()` is True;
    - SIGKILL that pid only, the toykit server stays alive;
    - within 2 s `running()` is False.
    - Then kill the group.
- [ ] **Step 2: Run** `tests.test_run`. Expected: the two new tests FAIL
  (exit 0 instead of 2; `running()` False while running).
- [ ] **Step 3: Implement** the modifications above.
- [ ] **Step 4: Run** `tests.test_run tests.test_scheduler tests.test_score
  tests.test_closed_loop tests.test_check_study tests.test_preflight_reuse
  tests.test_offline_preflight_kit tests.test_point_dir`. Expected: OK.
  The existing refusal and resume tests pass unchanged; any test that
  asserted broken.txt being overwritten gets a ledger Ruling (the spec
  makes it first-writer-wins).
- [ ] **Step 5: Commit** "engine: the point's writers go through PointDir;
  graph.run holds the point's run lock".

### Task 4: `core/campaign_dir.py`

**Files:**
- Create: `core/campaign_dir.py`, `tests/test_campaign_dir.py`

**Interfaces:**
- Consumes: `locks.hold`, `locks.held`, `locks.LockBusy`, and
  `point_dir.write_atomic`.
- Produces:
  - **Child names:**
    - `child_name(prefix, i) -> str` (`f"{prefix}R{i:02d}_00"`, moved from
      pool);
    - `parse_child(name) -> Optional[Tuple[str, int]]`: matches
      `(.+)R(\d+)_00`, then requires `child_name(prefix, int(i)) == name`;
    - `is_child(prefix, name) -> bool`.
  - `class CampaignBusy(RuntimeError)`.
  - **Constants:** `RECORD="campaign.json"`, `OUTCOMES="outcomes.jsonl"`,
    `PARENT_LOCK="parent.lock"`, `MCP_LOCK="lock"`, `LAUNCH="launch.json"`,
    `RC="rc"`, `STOP="STOP"`.
  - **`class CampaignDir(graph_data, prefix)`**, with `.path`:
    - `start(record) -> ContextManager[None]`:
      - mkdir;
      - `locks.hold(PARENT_LOCK)`, where `LockBusy` raises `CampaignBusy(f"campaign
        {prefix!r} is already running (another parent holds {lock})")`;
      - `write_atomic` the record, with `indent=1`.
    - `finish(exit_code)`: read, add `ended=time.time()` and `exit_code`,
      rewrite.
    - `record() -> Optional[dict]`:
      - ValueError on bad JSON;
      - for a record without `q`, it fills `q, max_evals, picker,
        executor, parallel, stagger` from `record["args"]` (int for `q`,
        `max_evals` and `parallel`, float for `stagger`, None when
        absent).
    - `append_outcome(d)`: one `json.dumps(d)` line, appended.
    - `outcomes() -> Dict[str, dict]`: the last line per `name`. A line
      that does not parse raises `ValueError(f"{path}:{lineno}: ...")`.
    - `alive()`: `held(PARENT_LOCK) or held(MCP_LOCK)`.
    - `exit_code() -> Optional[int]`: the record's, else the `rc` file
      (None if unreadable).
    - `launched_by() -> Optional[str]`: `"mcp"` if `launch.json` exists or
      the record has `command`, `"shell"` if only the record exists, else
      None.
    - `stopping()`, and `stop() -> Path` (mkdir, touch).
    - `write_launch(info)`: O_EXCL create (FileExistsError propagates).
      `update_launch(**fields)` rewrites it. `launch() -> Optional[dict]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_campaign_dir.py`:
  - `test_child_names`:
    - `parse_child("fooR07_00") == ("foo", 7)`;
    - `parse_child("fooR123_00") == ("foo", 123)`;
    - None for `fooR5_00`, `fooR00_01`, `fooR00_00x`, `single`;
    - `is_child("foo", "foo2R00_00")` is False;
    - `parse_child("foo2R00_00") == ("foo2", 0)`.
  - `test_start_record_finish`: `record()` inside the block; `alive()` is
    True inside and False after; `finish(0)` sets `exit_code` 0 and
    `ended`.
  - `test_a_second_start_is_refused`: a child process holds `start`;
    `start` here raises CampaignBusy with "already running".
  - `test_restart_of_an_ended_prefix` (Review Focus 3, unit part): `start`
    after an ended one replaces the record; earlier outcome lines stay.
  - `test_legacy_mcp_record`: the record `{prefix, study, args: ["--study",
    "s", "--q", "3", "--max-evals", "9", "--name-prefix", "p"], command,
    pid, started}` gives `q == 3`, `max_evals == 9`, `launched_by() ==
    "mcp"`.
  - `test_outcomes`: two lines for one name, last wins; a truncated final
    line raises ValueError naming the line.
  - `test_alive_through_the_mcp_lock`; `test_exit_code_from_rc`;
    `test_launched_by_none_shell_mcp`; `test_write_launch_is_exclusive`.
- [ ] **Step 2: Run.** Expected: ImportError.
- [ ] **Step 3: Implement** `core/campaign_dir.py`.
- [ ] **Step 4: Run** `tests.test_campaign_dir`. Expected: OK.
- [ ] **Step 5: Commit** "campaign_dir: child names and the campaign
  record".

### Task 5: closed_loop writes the record and the outcomes; pool reports each Outcome

**Files:**
- Modify:
  - `graph/pool.py`:
    - `child_name` is imported from campaign_dir (dual import; pool gets
      `core/` on `sys.path` the way closed_loop does);
    - `run_rolling(..., on_outcome=None)` calls `on_outcome(oc)` after
      each `[pool] <name>: <reason>` log line, in the main loop and the
      drain;
    - the stall WARNING's pgrep text becomes the flock-on-run.lock advice.
  - `graph/closed_loop.py`, `main`:
    - keep `argv_list = list(sys.argv[1:] if argv is None else argv)`;
    - after the check-only branch, `camp = CampaignDir(paths.GRAPH_DATA,
      prefix)` and a record with `{prefix, study, args: argv_list, q,
      max_evals, picker, executor, parallel, context, stagger, host:
      socket.gethostname(), pid: os.getpid(), started: time.time()}`;
    - enter `camp.start(record)` on a `contextlib.ExitStack`.
      `CampaignBusy` prints `[closed_loop] REFUSED: <msg>`; an `OSError`
      prints `[closed_loop] REFUSED: cannot write the campaign record:
      <exc>`. Either way it returns 2;
    - inside, the banner and then `run_rolling(...,
      on_outcome=soft(camp.append_outcome-of-oc))`, with the outcome dict
      `{**oc._asdict(), "x": list(oc.x), "time": time.time()}`;
    - `rc` defaults to 1, and `finally: soft(camp.finish)(rc)`;
    - `soft(fn)` logs `[closed_loop] WARNING: campaign record not written
      (<exc>); the campaign goes on` once per kind and swallows `OSError`.
- Test: `tests/test_closed_loop.py`, `tests/test_pool.py`

**Interfaces:**
- Consumes: Task 4 (`CampaignDir`, `CampaignBusy` and `child_name`).
- Produces:
  - `<GRAPH_DATA>/<prefix>/campaign.json`, `outcomes.jsonl` and
    `parent.lock`;
  - `pool.run_rolling(..., on_outcome=None)`;
  - `pool.child_name`, still importable from pool.

- [ ] **Step 1: Write the failing tests:**
  - **`tests/test_pool.py` `test_on_outcome_sees_every_outcome`:** `q=2`,
    `max_evals=3`, fake callables; `on_outcome` receives three Outcomes,
    in resolution order, matching `result["outcomes"]`.
  - **`tests/test_closed_loop.py` `TestCampaignRecord`,** branin local,
    `q=1`:
    - `test_record_and_outcomes`: after a 2-eval run, `campaign.json` has
      `study == "branin"`, `q == 1`, `max_evals == 2`, `exit_code == 0`
      and `host`; `outcomes.jsonl` has 2 lines with reason `ok`.
    - `test_a_live_prefix_is_refused`: hold `CampaignDir(...,
      "liv").start({})` in the test; `closed_loop.main` exits 2;
      "REFUSED" and "already running" are printed; `run_rolling` is not
      called (mock it).
    - `test_a_failing_outcome_write_does_not_stop_the_pool`: patch
      `CampaignDir.append_outcome` to raise `OSError(122, "quota")`; the
      run returns 0 with 2 rows, and the WARNING is printed once.
    - `test_finish_records_1_when_the_pool_raises`: patch
      `closed_loop.run_rolling` to raise RuntimeError; the exception
      propagates; the record's `exit_code == 1`.
    - `test_a_shell_relaunch_of_an_ended_prefix` (Review Focus 3): run
      prefix `rel` for 1 eval, then again for 1 eval. Both exit 0; the
      second skips `relR00_00` and lands `relR01_00`; `outcomes.jsonl`
      has 2 lines; the record's `started` is the second run's.
- [ ] **Step 2: Run** `tests.test_pool tests.test_closed_loop`. Expected:
  the new tests FAIL (no `on_outcome` kwarg; no `campaign.json`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_pool tests.test_closed_loop
  tests.test_campaign_dir`. Expected: OK.
- [ ] **Step 5: Commit** "closed_loop: every campaign writes its record and
  its outcomes; the pool reports each Outcome".

### Task 6: `service/campaigns.py` reads the records

**Files:**
- Modify:
  - `service/campaigns.py`:
    - delete `_scan` and the local `is_child`;
    - leave `_processes`, `_flag`, `_campaign_json` and a
      `_load_study = load_study` alias in place for the dashboard: they
      are unused by campaigns after this task, and Task 7 deletes them
      along with the dashboard's use of them, so the dashboard keeps
      working in between;
      import `is_child` from campaign_dir (`from service.campaigns import
      is_child` keeps working);
    - add `camp(prefix) -> CampaignDir` and `point(name) -> PointDir`;
    - rename `_load_study` to `load_study`;
    - rewrite `_parent`, `_study_of`, `campaign_status`, `_campaigns`,
      `stop_campaign`, `_launch_refusals` and `_launch` per the spec.
  - `service/server.py`: the `campaign_status` docstring (its keys,
    "starting").
- Test: `tests/test_campaigns.py`

**Interfaces:**
- Consumes: Tasks 2 and 4.
- Produces, for Task 7:
  - **`campaign_status(prefix)`** returns `{prefix, study, host, parent:
    {alive, pid, launched_by, exit_code, log_tail}, stopping, children,
    rows, best, board_error, error}`:
    - each child is `{name, state, last_line, outcome, x, values}`;
    - `state` is one of `scored|broken|running|starting|ended without a
      row`;
    - `x` is `{knob: v}` or None, and `values` is the board row's values
      or None;
    - `error` is the record or outcomes read error, else None.
  - **`campaign_status()`** returns a list of `{prefix, study, alive,
    launched_by, error}`, one per `*/campaign.json`.
  - **`camp(prefix)`, `point(name)` and `load_study(name)`.**
- **Rules:**
  - **Child state**, one function `_child_state(scored, pd, outcome,
    alive)`:
    - scored if `scored`;
    - broken if `pd.broken()`;
    - running if `pd.running()`;
    - starting if `alive` and `outcome is None` and not `pd.ever_ran()`;
    - else "ended without a row".
  - **`pid`:** the record's pid, else `launch()["pid"]`.
  - **`log_tail`:** from `parent.log` if it exists.
  - **`_launch_refusals`:**
    - `alive()` gives "campaign {p!r} is already running";
    - STOP is unchanged;
    - `launched_by()` not None gives "campaign {p!r} was already launched
      ({file}); use a new prefix";
    - the children check is unchanged.
  - **`_launch`:**
    - `write_launch({prefix, study, args, command, pid: None, started})`,
      where FileExistsError gives ValueError "was already launched";
    - spawn, then `update_launch(pid=...)`;
    - "launched" once `camp.record()` is not None;
    - the `rc` refusal path is unchanged.

- [ ] **Step 1: Update and add tests** in `tests/test_campaigns.py`:
  - **`test_a_shell_campaign`:** poll up to 60 s for `parent.alive`
    before asserting it (the record appears after the launch checks).
    The other assertions are unchanged.
  - **`_stop_launch`:** reads the pid from `launch.json`.
  - **`test_launch_refusals`:**
    - "already launched from MCP" becomes "already launched";
    - the argv stand-in parent becomes holding
      `self.svc.camp("busy").start({...})` in the test;
    - the last assertion becomes `assertIsNone(self.svc.camp("busy")
      .launch())`.
  - **`test_the_dry_run_sees_the_launch_refusals` and
    `test_a_refused_launch_spends_the_prefix`:** "already launched".
  - **`test_a_dry_run`:** adds `launch.json` to the files that must not
    exist.
  - **New tests:**
    - `test_a_starting_child`: hold `camp("sta").start({"study":
      "branin"})`; `child_log("staR00_00")`; state is `"starting"`. After
      the block it is `"ended without a row"`.
    - `test_a_running_child_by_its_lock`: hold
      `point("rnR00_00").run_lock()`; state is `"running"`; `stop_campaign`
      reports `children_running == 1`.
    - `test_an_old_shell_campaign_gets_its_study_from_a_point`: a child
      log plus `point.json` `{"study": "branin"}` and no record; `study ==
      "branin"`.
    - `test_a_bad_record_is_reported` (Review Focus 2): `campaign.json` =
      `"{"`; `campaign_status("bad")["error"]` names `campaign.json`, the
      children are still listed, and the list entry for `bad` has `error`.
    - `test_a_truncated_outcome_line_is_reported` (Review Focus 1): a
      record plus `outcomes.jsonl` ending in `{"name": "trR00_`; `error`
      names `outcomes.jsonl`, and the children are listed.
- [ ] **Step 2: Run** `tests.test_campaigns`. Expected: the new and updated
  tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_campaigns tests.test_service_server` (the
  server test file, if one exists: `ls tests | grep -i server`).
  Expected: OK.
- [ ] **Step 5: Commit** "campaigns: read the point and campaign records;
  no process scan".

### Task 7: `service/dashboard.py` reads only the records

**Files:**
- Modify:
  - `service/campaigns.py`: delete the shims Task 6 left (`_processes`,
    `_flag`, `_campaign_json`, the `_load_study` alias).
- Modify: `service/dashboard.py`:
  - **Delete:** `CHILD_RE`, `BROKEN_RE`, `_mark_broken`, `_argv`,
    `_read_status`, `_int`, and the `_flag` import.
  - **`prefixes`:** uses `parse_child`; its `campaign.json` mtime test is
    unchanged.
  - **`_step(view, running, now)`:**
    - turns a `PointDir.step_state` dict into the page's `{state,
      message, progress, age_s, stall, error}`;
    - `age_s` is `now - handle_mtime`;
    - stall uses `STALL_FLOOR_S`, as today;
    - a non-numeric poll field is already an `error` from step_state.
  - **`campaign_data`:**
    - `status = svc.campaign_status(prefix)`;
    - q and max_evals come from `svc.camp(prefix).record()`; a ValueError
      or OSError goes to `error`;
    - x and value come from each child's `x`/`values`;
    - steps come from `svc.point(name).step_state(s)`;
    - the study comes from `svc.load_study`;
    - "starting" maps to the point state "running" (in `POINT_STATES`).
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: Task 6's `campaign_status` child keys, `camp`, `point` and
  `load_study`, plus Task 2's `step_state` keys.
- Produces: an unchanged snapshot schema (`campaign_data` keys, `layout`).

- [ ] **Step 1: Update the tests:**
  - **The `_Dash` fixture:**
    - drop `self.procs` and `svc._processes`;
    - add `self.live(prefix, **record)`, which enters
      `svc.camp(prefix).start(record)` on an ExitStack closed in cleanup;
    - add `self.run_lock(name)`, which enters
      `svc.point(name).run_lock()` the same way;
    - `run_proc` becomes `run_lock`;
    - `row()` uses `svc.load_study`.
  - **`test_prefixes`:** `dd` comes from `self.live("dd", study=
    "toystudy", q=2, max_evals=6)`.
  - **`test_budget_and_best`:** `sh` comes from `self.live("sh", ...)`
    with q 2 and max_evals 6. The `mm` legacy record keeps its args form
    (it now reads through `record()`).
  - **`test_stall`:** uses `run_lock`; the "not running" half exits the
    stack.
  - **`test_build_snapshot`:** `lv` comes from `self.live`.
  - **`test_an_unreadable_board_keeps_the_points`:** the board path comes
    via `svc._board(svc.load_study(...))`.
  - **Unchanged assertions:** `test_the_step_that_broke_a_point_is_failed`
    and `test_a_bad_status_file` keep theirs.
  - **New `test_a_starting_point_is_running`:** `self.live("sp", study=
    "toystudy")` plus a child log; the point state is `"running"`.
- [ ] **Step 2: Run** `tests.test_dashboard`. Expected: FAIL (the fixture
  helpers and starting state are not there yet, and `_processes` is gone
  since Task 6).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_dashboard tests.test_campaigns`.
  Expected: OK.
- [ ] **Step 5: Commit** "dashboard: read the point and campaign records;
  no regex, no private methods".

### Task 8: Docs, glossary, full suite, acceptance

**Files:**
- Modify:
  - `README.md` "Where things land": state/`run.lock`; `<GRAPH_DATA>/<prefix>/campaign.json`, `outcomes.jsonl`, `parent.lock`.
  - `wiki/drivers/service.md`: the campaign-tools and dashboard sections; the liveness wording.
  - `wiki/drivers/contract-engine.md`: one "Point and campaign records (2026-10-05)" section.
  - `CONTEXT.md`: add **Point record** and **Campaign record** entries, and fix the **Busy name** pgrep advice.
  - `wiki/log.md`: a 2026-10-05 bullet.
  - `wiki/index.md`: the service and contract-engine one-liners, if they change.
  - The main checkout's local, untracked `.claude/commands/closed-loop-status.md` and `closed-loop-harvest.md`: the pgrep/process-scan advice becomes run.lock / campaign.json / outcomes.jsonl.

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Run the full suite.** Expected: OK, with the skipped count
  as before (3).
- [ ] **Step 3: Compare `measure_basis_sha`.** Every study's value equals
  the baseline in the ledger.
- [ ] **Step 4: Acceptance,** in a sandbox `AUTORESEARCH_DATA_ROOT` under
  `/exp/mu2e/data/users/oksuzian/claude-scratch/`. Record each result in
  the ledger:
  1. **Shell campaign:** `graph.closed_loop --study branin --q 1
     --max-evals 2 --executor local --parallel 1 --picker budget_sob
     --name-prefix accsh` from the shell. While it runs, `campaign_status
     accsh` shows alive and a running child. After it ends: 2 scored, and
     `outcomes.jsonl` has 2 `ok` lines.
  2. **MCP launch:** `CampaignService(env).start_campaign(...,
     confirm=True)` for `accmcp` gives "launched", and status shows
     launched_by mcp and exit_code 0.
  3. **Dashboard:** `python -m service.dashboard --once --no-serve --out
     <sandbox>/dash` lists both, with x, values and step states.
  4. **Cross-host:** if another host is reachable without new
     credentials, probe `held(<state>/run.lock)` there while a slow toy
     point runs here. Otherwise ledger it as "cross-host lock: unverified".
- [ ] **Step 5: Commit** "docs: point and campaign records". The
  `.claude/commands` files are untracked and are not committed.
