# Campaign Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four campaign tools on the `autoresearch` MCP server: `start_campaign` (a dry run, then confirm), `stop_campaign`, `campaign_status` and `leaderboard`.

**Architecture:**
- `graph.closed_loop` gains `--check-only`, which runs every launch check and exits without launching.
- `service/jobs.py` holds the detached launch with the lock handoff, now shared by the check jobs and the campaigns.
- `service/campaigns.py` (`CampaignService`) reads the files every campaign leaves behind and launches `graph.closed_loop` detached.
- `service/server.py` wraps the four methods as tools.

**Tech Stack:** Python 3.12 (ana 2.8.0), mcp 2.0.0, unittest.

**Spec:** `docs/superpowers/specs/2026-10-02-campaign-tools-design.md`

## Global Constraints

- **Worktree:** `/exp/mu2e/app/users/oksuzian/autoresearch-checkstudy`, branch `campaign-tools` (spec 34cf21a).
- **Commands:**
  - `PY=/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python`;
  - the suite is `PYTHONPATH= $PY -m unittest discover -s tests -t .`, with a baseline of 838 OK (skipped=3).
- **No modes in the server:** `service/*.py` import only the standard library and bare `core/` modules (`paths`, `study`, `leaderboard`, `boards`), with `core/` on `sys.path`. They never import `modes`, `contract`, `kits` or `graph.*`. Qualified `core.x` imports break `tests/test_modes.py` `TestSingleModuleCopy`.
- **Tests run locally only:** `branin` from `tests/fixtures/engine_studies/` (toykit, knobs `x1`/`x2`, objectives `branin` and `currin`, both `min`, board `leaderboard_branin.tsv`), always with `--picker budget_sob --executor local --parallel 1`. The environment comes from `tests.engine_fixtures.engine_env(data, ENGINE_STUDIES)`.
- **Prefixes are exact:** children and rows match `re.fullmatch(re.escape(prefix) + r"R\d+_00", name)`, never `startswith`.
- **No grid submit anywhere,** in tests or in acceptance.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

**Ruling (plan against spec):** the spec reads the board through `core/boards.py`, but `board_for` uses the process's own data root. `CampaignService` therefore builds the same board itself with its own data root:
- `Leaderboard.for_study(study, path=data_root / paths.LEADERBOARD_LIVE.name / Path(study.leaderboard_rel).name, archive_path=paths.leaderboard_archive(study.leaderboard_rel))`.

This is the same rule `CheckService` uses, and in the server (`env=None`) the result is identical.

**Known limit (recorded, not tested):** the process scan covers the whole host for this user. A campaign with the same prefix under another data root counts as live.

## Review Focus

1. **A refused launch spends its prefix** (one MCP launch per prefix).
   - **Expected:** `state: "refused"` with the reasons and a message to dry-run again with a new prefix; a second confirm on that prefix is refused at once.
   - **Test:** Task 4, `test_a_refused_launch_spends_the_prefix`.
2. **`foo` against `foo2`.**
   - **Expected:** children and rows never mix.
   - **Test:** Task 3, `test_prefixes_are_exact`.
3. **A dry run that hangs** (a kit that never starts).
   - **Expected:** after the cap, `ok: false` and "did not finish".
   - **Test:** Task 4, `test_a_hung_dry_run_times_out`, with `check_timeout_s` set very small.
4. **Status or stop on a prefix that never ran.**
   - **Expected:** an empty status (study None, no children, `rows` 0, `best` None), and `stop_campaign` warns.
   - **Test:** Task 3, `test_an_unknown_prefix`.
5. **A study with no board file yet.**
   - **Expected:** `leaderboard` gives `n_rows` 0 and `rows` `[]`.
   - **Test:** Task 3, `test_leaderboard_of_an_empty_board`.

---

### Task 1: `graph.closed_loop --check-only`

**Files:** Modify `graph/closed_loop.py` (the module docstring, the argparser, and `main` just after the `if problems:` refusal block). Test: `tests/test_closed_loop.py`.

**Produces:**
- **The flag** `--check-only` (`action="store_true"`).
- **On success it prints** `[closed_loop] OK: would launch study=<s> q=<q> max_evals=<n> prefix=<p> board=<path> executor=<e>` and returns 0. No pool, no STOP read, no child.
- **Refusals are unchanged:** exit 2 with `[closed_loop] REFUSED: ` lines.

- [ ] **Step 1: Failing tests,** class `TestCheckOnly` using the file's `loop_cmd`, `board_rows` and `submits`:
  - `test_check_only_launches_nothing`:
    - `loop_cmd("branin", 1, 2, "chk") + ["--check-only"]`, with `engine_env(data, ENGINE_STUDIES)`;
    - rc 0;
    - `"[closed_loop] OK: would launch study=branin q=1 max_evals=2 prefix=chk"` is in stdout;
    - `data/autoresearch_graph_data/closed_loop_logs` does not exist;
    - `board_rows(data, "branin") == []` and `submits(data) == []`.
  - `test_check_only_refusals`: each gives rc 2 with its fragment in stdout:
    - study `nope`: `"unknown study 'nope'"`;
    - `ce_chain`: `"has no knobs"`;
    - branin with `--context alpha=1`: `"--context 'alpha'"`.
- [ ] **Step 2: Run them.** `PYTHONPATH= $PY -m unittest tests.test_closed_loop.TestCheckOnly -v`. Expected: the first fails, because argparse rejects `--check-only` with rc 2.
- [ ] **Step 3: Implement.** Add one line to the docstring: "`--check-only`: run every check, print OK, launch nothing".
- [ ] **Step 4: Run them.** Expected: 2 OK.
- [ ] **Step 5: Commit:** `closed_loop: --check-only runs every launch check and launches nothing`.

### Task 2: `service/jobs.py`, the shared detached launch

**Files:** Create `service/jobs.py`. Modify `service/checks.py`: `start_check` calls `spawn_detached`, and `_locked` is replaced by `lock_held`. Test: `tests/test_service.py`.

**Produces:**
- **`spawn_detached(job_dir: Path, script: str, args: Sequence[str], env: Mapping[str, str]) -> int`:**
  1. open `job_dir/"lock"` with `O_CREAT | O_RDWR`, mode 0o644;
  2. `flock(LOCK_EX)`;
  3. `Popen(["bash", "-c", script, "_", str(job_dir), *args], cwd=paths.REPO_ROOT, env=env, stdin/stdout/stderr=DEVNULL, start_new_session=True, pass_fds=(fd,))`;
  4. close the fd in a `finally`;
  5. a daemon thread runs `proc.wait`;
  6. return `proc.pid`.
- **`lock_held(path: Path) -> bool`:**
  - False if the file is missing;
  - otherwise probe with `LOCK_SH | LOCK_NB` on a fresh fd. `BlockingIOError` means True; otherwise unlock and return False.
  - The shared probe means two probes never conflict with each other (the deferred minor from the last review).

- [ ] **Step 1: Failing test,** `TestSpawn.test_the_lock_lives_with_the_job`:
  - `pid = spawn_detached(d, 'sleep 2; echo done >"$1/out"', [], dict(os.environ))`;
  - `lock_held(d / "lock")` is True;
  - poll for up to 15 s until it is False;
  - then `(d / "out").read_text() == "done\n"`;
  - `lock_held(d / "missing")` is False.
- [ ] **Step 2: Run it.** Expected: `ModuleNotFoundError: service.jobs`.
- [ ] **Step 3: Implement,** and switch `checks.py` over. Its `JOB_SCRIPT`, job layout and results are unchanged.
- [ ] **Step 4: Run `tests.test_service`.** Expected: 15 OK (14 plus 1).
- [ ] **Step 5: Commit:** `service: the detached launch and lock probe in service/jobs.py`.

### Task 3: `CampaignService`, the read side

**Files:** Create `service/campaigns.py`. Test: `tests/test_campaigns.py` (new).

**Produces:**
- **`is_child(prefix: str, name: str) -> bool`:** `re.fullmatch(re.escape(prefix) + r"R\d+_00", name) is not None`. Children and rows both use it.
- **`CampaignService(env=None)`:** the same `env` and `data_root` rule as `CheckService`, plus:
  - `graph_data = data_root / paths.GRAPH_DATA.name`;
  - `grid_data = data_root / paths.GRID_DATA_ROOT.name`;
  - `camp_dir(prefix) = graph_data / prefix`.
- **`_processes() -> List[Tuple[int, List[str]]]`:** `(pid, argv)` from `/proc/*/cmdline` (NUL-split) for this user's processes, skipping any that vanish while being read.
  - A **closed_loop parent** is an argv holding `"graph.closed_loop"`. Its prefix is the value after `--name-prefix` (or in `--name-prefix=`); its study is the value after `--study`.
  - A **running child** is an argv holding `"graph.run"`, named by its `--config`.
- **`leaderboard(study: str, name_prefix: Optional[str] = None, top: int = 20) -> dict`:**
  - The study is looked up by stem on `study_files` (`ValueError("no study named ...; known: [...]")`) and loaded with `st.load_study_file`, whose `ValueError` propagates. The board is built as in the Ruling.
  - Returns `{study, board: str(live path), n_rows, objective: {name, direction}, rows}`.
  - `n_rows` counts every row of the board. `rows` are filtered by the exact prefix, sorted best first by the first objective (`max` descending, `min` ascending), and cut to `top`.
  - Each row is `{config, x: {knob: value}, values: y}`.
- **`campaign_status(name_prefix: Optional[str] = None)`:**
  - **With a prefix,** returns `{prefix, study, parent, stopping, children, rows, best}` as in the spec, with these rules:
    - `parent.launched_by` is "mcp" when `campaign.json` exists. Then `alive = lock_held(camp_dir/"lock")`, and `exit_code` is the integer in `rc` if present.
    - Otherwise it is "shell" when a scanned parent has this prefix (`alive` true, with its `pid`); otherwise `alive` is false and `launched_by` is None.
    - `log_tail` is the last 20 lines of `camp_dir/"parent.log"` for MCP launches, else `""`.
    - `study` comes from `campaign.json`, else the scanned parent's `--study`, else the first child's `grid_data/<child>/state/point.json` `"study"`, else None.
    - `children` are sorted by name, each `{name, state, last_line}`, where `last_line` is the last non-empty line of the child's log.
    - `rows` and `best` come from the study's board, by exact prefix. `best` is the row dict as in `leaderboard`; `rows` is 0 and `best` None without a study.
  - **With no prefix,** returns a list sorted by prefix, merging scanned parents with every `graph_data/*/campaign.json`: `[{prefix, study, alive, launched_by}]`.
- **`stop_campaign(name_prefix: str) -> dict`:**
  - `name_prefix` must match `[A-Za-z0-9_]+` (`ValueError` otherwise).
  - It touches `camp_dir/"STOP"` (folder made) and returns `{stop_file, parent_alive, children_running, warning}`.
  - `warning` is `f"no sign of a campaign named {prefix!r}"` when there is no `campaign.json`, no scanned parent and no child log; otherwise None.

- [ ] **Step 1: Failing tests,** `tests/test_campaigns.py`. The base class gives a temp `data`, `env = engine_env(data, ENGINE_STUDIES)` and `svc = CampaignService(env=env)`. A helper `shell_loop(prefix, max_evals, q=1)` Popens `graph.closed_loop` (`--picker budget_sob --executor local --parallel 1`, `cwd=ROOT`, stdout/stderr to a file under the temp dir, `start_new_session=True`), and cleanup kills its group. A helper `wait_exit(p, 180)` waits for it.
  - `test_a_shell_campaign`:
    - `shell_loop("shl", 2)`;
    - at once, `campaign_status("shl")["parent"]` has `alive` true and `launched_by` "shell", and the no-prefix list holds `"shl"`;
    - after it exits: `alive` false, `study == "branin"`, both children `scored`, `rows == 2`;
    - `best["values"]["branin"]` is the smaller of the two rows;
    - `leaderboard("branin", "shl")["rows"]` has 2 rows in ascending `branin` order.
  - `test_prefixes_are_exact`:
    - hand-write `graph_data/closed_loop_logs/fooR00_00.log` and `foo2R00_00.log`;
    - `campaign_status("foo")` lists only `fooR00_00`;
    - `is_child("foo", "fooR12_00")` is true; `is_child("foo", "foo2R00_00")` and `is_child("foo", "fooR00_00x")` are false.
  - `test_child_states`:
    - a child log, plus `grid_data/<c>/state/broken.txt`, gives `broken`;
    - a child log with no row, no process and no `broken.txt` gives `ended without a row`.
  - `test_an_unknown_prefix`:
    - `campaign_status("nothing")` gives `study` None, `children == []`, `rows == 0`, `best` None and `parent.alive` false;
    - `stop_campaign("nothing")["warning"]` contains `"no sign of a campaign"`, and `STOP` exists.
  - `test_leaderboard_of_an_empty_board`: `leaderboard("branin")` gives `n_rows == 0` and `rows == []`.
  - `test_leaderboard_errors`: an unknown study gives `ValueError` with `"no study named 'nope'"`; `stop_campaign("a-b")` gives `ValueError`.
- [ ] **Step 2: Run them.** `PYTHONPATH= $PY -m unittest tests.test_campaigns -v`. Expected: `ModuleNotFoundError: service.campaigns`.
- [ ] **Step 3: Implement** as in Produces.
- [ ] **Step 4: Run them.** Expected: 6 OK.
- [ ] **Step 5: Commit:** `service: CampaignService -- campaign_status, stop_campaign, leaderboard`.

### Task 4: `start_campaign`

**Files:** Modify `service/campaigns.py`. Test: `tests/test_campaigns.py`.

**Produces:**
- **Constants:**
  - `DRY_SCRIPT = 'source ./activate.sh >/dev/null && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop "$@" --check-only'`;
  - `LAUNCH_SCRIPT` is the spec's text exactly;
  - `BANNER = "[closed_loop] study="`;
  - `REFUSED = "[closed_loop] REFUSED: "`;
  - attributes `check_timeout_s = 600` and `launch_wait_s = 600`.
- **`budget(study: str, max_evals: int, executor: str) -> Optional[dict]`:** loads the study by name (None on a load error).
  - `per = sum(s.fixed.get("njobs", 0) for s in study.steps if s.kit == "prodtools")`.
  - Grid gives `{grid_jobs_per_point: per, grid_jobs_total: per * max_evals}`.
  - Local gives `{grid_jobs_per_point: 0, grid_jobs_total: 0, local_jobs_per_point: per}`.
- **`start_campaign(study, name_prefix, q, max_evals, picker="hybrid", executor="grid", parallel=None, context=None, stagger=None, confirm=False) -> dict`:**
  - `name_prefix` is checked as in `stop_campaign`.
  - **argv:** `--study, --q, --max-evals, --picker, --name-prefix`, one `--context` per entry, `--executor`, then `--parallel` and `--stagger` only when given.
  - `command` is `'PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop ' + shlex.join(argv)`.
  - **Dry run:** `subprocess.run(["bash", "-c", DRY_SCRIPT, "_", *argv], cwd=paths.REPO_ROOT, env=self.env, stdin=DEVNULL, capture_output=True, text=True, timeout=self.check_timeout_s)`. The output is stdout plus stderr. It returns `{ok, problems, command, budget, output_tail, error}`:
    - rc 0 gives `ok: true`;
    - rc 2 gives `ok: false` with `problems` the REFUSED lines, stripped of their prefix;
    - any other rc, or `TimeoutExpired`, gives `ok: false` with `error` `f"closed_loop's check did not finish ({'timed out' or f'exit {rc}'})"` and `output_tail` the last 40 lines.
  - **Launch (`confirm=True`):** each refusal raises `ValueError` before anything is written:
    - a scanned live parent on the prefix: `"already running"`;
    - `camp_dir/"STOP"` exists: `"STOP"`;
    - claiming `camp_dir/"campaign.json"` with `O_CREAT | O_EXCL` fails: `"already launched from MCP"`.

    Then `pid = spawn_detached(...)`, `campaign.json` is completed, and it polls every 1 s for up to `launch_wait_s`:
    - `BANNER` in `parent.log` returns `{state: "launched", prefix, pid, log}`;
    - otherwise `rc` present returns `{state: "refused", problems, exit_code, error, note}`:
      - `error` is set when there are no REFUSED lines;
      - `note` is "this prefix is spent: dry-run again and launch under a new prefix";
    - on timeout it returns `{state: "starting", prefix, pid, log}`.

- [ ] **Step 1: Failing tests:**
  - `test_budget`:
    - `budget("branin", 4, "local") == {"grid_jobs_per_point": 0, "grid_jobs_total": 0, "local_jobs_per_point": 0}`;
    - for `mode_specs/foilspfbpz_ax.json`, `budget("foilspfbpz_ax", 10, "grid")` is `{"grid_jobs_per_point": 130, "grid_jobs_total": 1300}`.
  - `test_a_dry_run`:
    - `start_campaign("branin", "dry", 1, 2, picker="budget_sob", executor="local", parallel=1)` gives `ok` true;
    - `"--check-only"` is not in `command`, and `"--name-prefix dry"` is;
    - `graph_data/"dry"` does not exist.
  - `test_a_refused_dry_run`: `context=["alpha=1"]` gives `ok` false and `"--context 'alpha'"` in `problems[0]`.
  - `test_a_hung_dry_run_times_out`: `svc.check_timeout_s = 0.01` gives `ok` false and `"did not finish (timed out)"` in `error`.
  - `test_an_activate_failure_in_a_dry_run`:
    - a service whose env adds `AUTORESEARCH_PYENV="ana"` and drops `AUTORESEARCH_VENV`;
    - `"did not finish (exit 1)"`, with `"NAME VERSION"` in `output_tail`.
  - `test_a_launch_runs_to_the_end`:
    - `confirm=True` on prefix `"mcp1"` with `max_evals=2` (local, budget_sob) gives `state` "launched";
    - poll `campaign_status("mcp1")` for up to 180 s until `parent.alive` is false;
    - then `launched_by` "mcp", `exit_code` 0, 2 children `scored` and `rows == 2`.
  - `test_launch_refusals`:
    - `confirm=True` on `"dup"` (local, budget_sob, max_evals=1) gives `launched`; a second `confirm=True` on `"dup"` gives `"already launched from MCP"`; then wait for `"dup"` to end;
    - `stop_campaign("stp")` then `confirm=True` on `"stp"` gives `"STOP"`;
    - `shell_loop("busy", 6)` then `confirm=True` on `"busy"` gives `"already running"`.
  - `test_a_refused_launch_spends_the_prefix`:
    - `confirm=True` with `context=["alpha=1"]` gives `state` "refused", with `"--context 'alpha'"` in `problems[0]` and `"spent"` in `note`;
    - a second confirm gives `ValueError` with `"already launched from MCP"`.
  - `test_stop_drains_a_launch`:
    - launch `"drn"` with `max_evals=6, q=1` and get `launched`;
    - `stop_campaign("drn")["parent_alive"]` is True;
    - poll until the parent ends (≤ 180 s);
    - fewer than 6 children, `stopping` true and `exit_code` 0.
- [ ] **Step 2: Run them.** Expected: `AttributeError: ... 'start_campaign'` / `'budget'`.
- [ ] **Step 3: Implement** as in Produces.
- [ ] **Step 4: Run `tests.test_campaigns`.** Expected: 15 OK.
- [ ] **Step 5: Commit:** `service: start_campaign -- a dry run through --check-only, then a confirmed detached launch`.

### Task 5: The server

**Files:** Modify `service/server.py` and `tests/test_service.py` (`TestStdio`).

**Produces:**
- **Four tools,** all `structured_output=True`:
  - `start_campaign(study: str, name_prefix: str, q: int, max_evals: int, picker: str = "hybrid", executor: str = "grid", parallel: int | None = None, context: list[str] | None = None, stagger: float | None = None, confirm: bool = False) -> dict[str, Any]`;
  - `stop_campaign(name_prefix: str) -> dict[str, Any]`;
  - `campaign_status(name_prefix: str | None = None) -> dict[str, Any]`. With no prefix it returns `{"campaigns": [...]}`, because a union of return types is not structured output.
  - `leaderboard(study: str, name_prefix: str | None = None, top: int = 20) -> dict[str, Any]`.
- **One `INSTRUCTIONS` paragraph,** in substance:
  - Campaigns: always call `start_campaign` with `confirm=false` first, and show the operator its `command`, `problems` and `budget`.
  - Call `confirm=true` only with the operator's OK. A launched campaign submits real grid jobs and writes leaderboard rows. One launch per prefix: a refused launch spends it.
  - Follow it with `campaign_status`, every few minutes, not seconds. `stop_campaign` stops new launches and running children finish.
  - `leaderboard` shows the rows, best first.

- [ ] **Step 1: Failing test.** In `test_a_check_through_mcp`:
  - the sorted tool names are the nine;
  - `"confirm=false"` is in `init.instructions`;
  - `start_campaign` with `{"study": "toystudy", "name_prefix": "mcpdry", "q": 1, "max_evals": 2, "executor": "local", "parallel": 1}` has `is_error` false and `structured_content["ok"]` true;
  - `campaign_status` with `{}` has `is_error` false, and `"campaigns"` is in `structured_content`.
- [ ] **Step 2: Run it.** Expected: the tool-name assert fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `tests.test_service` and `tests.test_campaigns` pass. Then the full suite gives 838 + 2 (Task 1) + 1 (Task 2) + 15 (Tasks 3-4) = 856 OK (skipped=3); if the count differs, explain it. Every `measure_basis_sha` is unchanged:
  - ce_chain 79b9b3e2;
  - foilsflash_ax 405cc0e8;
  - foilspf2k_ax 2060c97e;
  - foilspf_ax e96f0491;
  - foilspfbp_ax 54467d3e;
  - foilspfbpx_ax d6ee2d28;
  - foilspfbpz_ax c4aafee1;
  - foilspfbw_ax 01bcbd62.
- [ ] **Step 5: Commit:** `service: the campaign tools on the autoresearch MCP server`.

### Task 6: Acceptance in a sandbox

**Files:** none in git. `SB=/exp/mu2e/data/users/oksuzian/claude-scratch/mcpcampaign`.

- [ ] **Step 1:**
  - `klist` shows at least 4 h left.
  - `$SB/client.py` is the study-tools acceptance client, extended to call any tool with JSON args and print the result. It uses `AUTORESEARCH_DATA_ROOT=$SB/data` and `AUTORESEARCH_STUDY_PATH=<worktree>/tests/fixtures/engine_studies`.
- [ ] **Step 2:** A dry run of `foilspfbpz_ax` on the grid (`q=10`, `max_evals=40`) gives `ok`, with budget 130 and 5200. `find /exp/mu2e/data/users/oksuzian/autoresearch_grid -maxdepth 1 -newer $SB/.start` shows nothing.
- [ ] **Step 3:** A dry run of `ce_chain` gives `ok: false`, with "has no knobs".
- [ ] **Step 4:**
  - `branin`, local, budget_sob, q=2, max_evals=4, `confirm=true` on prefix `accbrn` gives `launched`;
  - `campaign_status` every 15 s until the parent ends: 4 scored, `exit_code` 0;
  - `leaderboard branin accbrn` gives 4 rows, best first.
- [ ] **Step 5:**
  - the worktree's `git status --short` is empty;
  - the live `autoresearch_leaderboards` and `autoresearch_grid` hold nothing new;
  - results go in the ledger.

### Task 7: Records

- [ ] **Step 1:** `wiki/drivers/service.md` gets a "Campaign tools (2026-10-02)" section:
  - the four tools;
  - `--check-only`;
  - the prefix rules (exact match, one MCP launch per prefix, a refusal spends it);
  - the host-wide scan limit;
  - the `board_for` ruling;
  - the acceptance results.

  Also update its description and `timestamp`, add the `log.md` bullet, and update the `index.md` service line.
- [ ] **Step 2:** The suite is green. Commit: `wiki: campaign tools on the autoresearch MCP server`.
- [ ] **Step 3:** Memory: update `project_phase_c1_branches.md` and its MEMORY.md line.
- [ ] **Step 4: After the operator merges and runs `/mcp`:**
  - `campaign_status` of `bpzax01`;
  - `leaderboard foilspfbpz_ax top=5`;
  - one dry run, live from the session.
