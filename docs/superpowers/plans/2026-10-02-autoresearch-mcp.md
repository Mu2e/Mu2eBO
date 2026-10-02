# autoresearch MCP Server (study tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An MCP server named `autoresearch` whose five tools let an agent with only MCP access check a study exactly as `python -m graph.check_study` does: start a check, poll for its report, and list, show and read about studies.

**Architecture:**
- `service/checks.py` holds `CheckService`: the job logic and the read-only queries, in plain Python with no MCP.
- Each check is a detached `bash` job that runs `graph.check_study --json` into its own job directory. The job holds a lock that the server took before the launch and handed over to it, so the server can tell whether the job is still alive.
- `service/server.py` is a thin `MCPServer` with one tool per `CheckService` method, over stdio.

**Tech Stack:** Python 3.12 from ana 2.8.0; the official `mcp` 2.0.0 SDK (`mcp.server.mcpserver.MCPServer`; for tests, `mcp.client.stdio.stdio_client` and `mcp.ClientSession`); unittest.

**Spec:** `docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md`

## Global Constraints

- **Worktree and branch:** `/exp/mu2e/app/users/oksuzian/autoresearch-checkstudy`, branch `autoresearch-mcp`.
- **Suite:** `PY=/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python`; then `PYTHONPATH= $PY -m unittest discover -s tests -t .`. The baseline is 824 OK (skipped=3).
- **Imports in `service/checks.py`:** only the standard library, `from core import paths` and `from core import study as st`. It never imports `modes`, `graph.run`, `graph.check_study`, `core.contract` or `core.kits`.
- **Writes:** only `<data root>/study_drafts/<name>.json`, `<data root>/autoresearch_graph_data/check_jobs/<job_id>/`, and whatever check_study writes itself. Nothing submits, launches or writes a board.
- **SDK traps (measured with mcp 2.0.0):**
  - Every tool is `@server.tool(structured_output=True)`.
  - A return type must be `dict[str, Any]`, `list[dict[str, Any]]` or `str`; a bare `dict` is refused at import.
  - A `ValueError` raised in a tool arrives as `is_error` with the text `Error executing tool <name>: <message>`.
  - A list arrives as `structured_content == {"result": [...]}`.
  - The attribute names are snake_case: `is_error`, `structured_content`.
- **Scratch:** acceptance scratch goes under `/exp/mu2e/data/users/oksuzian/claude-scratch/mcpaccept/`; unit tests use `tempfile`, as the suite does.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

## Review Focus

1. **A job writing on the MCP stream:** the server's stdin and stdout carry the protocol.
   - **Expected:** every job runs with stdin, stdout and stderr at `DEVNULL`, and the session keeps answering while a check runs.
   - **Test:** Task 2 calls `list_studies` mid-check.
2. **A `job_id` that is a path** (`../x`, `/etc/passwd`, `""`).
   - **Expected:** refused as an unknown job.
   - **Test:** `test_a_job_id_that_is_a_path_is_unknown`.
3. **A relative `study` path:** the job runs from the repo root, not the server's working directory.
   - **Expected:** made absolute when the check starts.
   - **Test:** `test_a_good_study_by_relative_path_passes`.
4. **`activate.sh` fails.**
   - **Expected:** `done`, the "not JSON" error, and its message in `stderr_tail`.
   - **Test:** `test_an_activate_failure_is_done_with_its_message`.

---

### Task 1: `service/checks.py`

**Files:**
- Create: `service/__init__.py` (empty)
- Create: `service/checks.py`
- Test: `tests/test_service.py`

**Interfaces (produces):**
- **Constants:**
  - `MODES_DIR = paths.REPO_ROOT / "mode_specs"`;
  - `TAIL_LINES = 40`;
  - `JOB_SCRIPT`, which is the spec's text exactly:
    ```
    source ./activate.sh >/dev/null 2>"$1/stderr.log" && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study "${@:2}" --json >"$1/report.json" 2>>"$1/stderr.log"; echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"
    ```
- **`CheckService(env: Optional[Mapping[str, str]] = None)`:**
  - `self.env` is `dict(os.environ if env is None else env)`.
  - `self.data_root` is `Path(env["AUTORESEARCH_DATA_ROOT"])` when that is set and non-empty, else `paths.DATA_ROOT`.
  - `drafts_dir` is `data_root / "study_drafts"`.
  - `jobs_dir` is `data_root / paths.GRAPH_DATA.name / "check_jobs"`.
- **`list_studies() -> List[dict]`:** one entry per file of `st.study_files(MODES_DIR, env.get("AUTORESEARCH_STUDY_PATH"))`, as `{"name": <stem>, "path", "loads", "error", "knobs", "objectives", "board"}`.
  - A file that loads gets knob and objective name lists, and `board` set to `Path(leaderboard_rel).name`.
  - A file that fails gets `loads: false`, the exception text in `error`, and None in the last three fields.
- **`show_study(name) -> {"path", "study"}`:** looks the name up by stem on the same study files.
  - An unknown name raises `ValueError` containing `"no study named '<name>'"` and the sorted known stems.
- **`study_guide() -> str`:** the text of `MODES_DIR / "README.md"`.
- **`start_check(study="", study_json=None, x=None, executor="grid", parallel=None) -> {"job_id", "target", "command"}`:**
  - **Refusals,** each a `ValueError` raised before anything is written:
    - not exactly one of `study` and `study_json`: `"exactly one of study and study_json"`;
    - a `study_json` that is not a dict whose `name` matches `^[A-Za-z0-9_]+$`: `"study_json.name"`.
  - **Target:**
    - a `study_json` is written as `json.dumps(doc, indent=1) + "\n"` to `drafts_dir/<name>.json`, which becomes the target;
    - a `study` that ends in `.json` or contains `/` becomes `str(Path(study).absolute())`;
    - otherwise the name passes through.
  - **Arguments:** the target, then `--x=` with `",".join(repr(float(v)) for v in x)` if `x is not None`, then `--executor <executor>`, then `--parallel <n>` if given. Executor and `parallel` are not validated here; check_study does that.
  - **`job_id`:** `f"{Path(target).stem}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"`. The job directory is made with `exist_ok=False`.
  - **The lock:**
    1. `fd = os.open(job_dir / "lock", O_CREAT | O_RDWR)`;
    2. `fcntl.flock(fd, LOCK_EX)`;
    3. `Popen(["bash", "-c", JOB_SCRIPT, "_", str(job_dir), *args], cwd=paths.REPO_ROOT, env=self.env, stdin/stdout/stderr=DEVNULL, start_new_session=True, pass_fds=(fd,))`;
    4. `os.close(fd)` in a `finally`.

    This is measured on CephFS: the lock is held at once, while the job runs and by its grandchildren, and it is free on exit and on kill.
  - **`command`:** `'PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study ' + shlex.join([*args, "--json"])`.
  - **`job.json`:** `{"job_id", "target", "args", "command", "pid", "started": time.time()}`. The `pid` is there so a stuck job can be killed; it is never used to judge liveness.
- **`check_result(job_id) -> {"job_id", "state", "exit_code", "elapsed_s", "report", "stderr_tail", "error"}`:**
  - **Unknown job:** a `job_id` that is empty, contains `/`, is `.` or `..`, or has no `job.json` raises `ValueError` containing `"no check job"`.
  - **State,** in this order, which closes the race of a job ending between two reads:
    1. If `rc` exists, the job is `done`.
    2. Otherwise, if the lock is held, it is `running`. Test it with `flock(LOCK_EX | LOCK_NB)` on a fresh fd: `BlockingIOError` means held; otherwise unlock and close.
    3. Otherwise, if `rc` exists now, it is `done`; else it is `lost`.
  - **When `done`:**
    - `exit_code` is the integer in `rc`.
    - On exit 2, `report` and `error` are None.
    - On any other exit, `report` is the parsed `report.json`. If the file is missing, empty or not JSON, `report` is None and `error` is `"check_study's output is not JSON"`.
  - **`elapsed_s`** is rounded to 0.1. It is `rc`'s mtime minus `started` when `done`, else now minus `started`.
  - **`stderr_tail`** is the last `TAIL_LINES` lines of `stderr.log`, or `""`. It is returned in every state.

- [ ] **Step 1: Write the failing tests** in `tests/test_service.py`.
  - **Header:** as in `tests/test_check_study.py`, with `ROOT` on `sys.path`, and reuse `tests.engine_fixtures` (`toy_doc`, `write_study`, `engine_env`).
  - **Base class `_Svc`:**
    - a temp dir with `studies/` and `data/`;
    - `self.svc = CheckService(env=engine_env(self.data, self.studies))`;
    - `toy_pre(name="toystudy", **kits)`, which is `toy_doc(name)` with `preflight = {"kit": "toykit", "files": [], "params": {}}` and the toykit kit updated;
    - `wait(job_id)`, which polls `check_result` every 0.5 s, for up to 120 s, until `state != "running"`.
  - **`TestQueries(_Svc)`:**
    - `test_list_has_good_and_broken_files`:
      - set-up: `toystudy` written, plus `broken.json` holding `"{}"`;
      - `toystudy` has `loads` true, `knobs == ["x1", "x2"]`, `objectives == ["branin", "currin"]` and `board == "leaderboard_toystudy.tsv"`;
      - `broken` has `loads` false, a non-empty `error` and `knobs` None;
      - `ce_chain` is listed and loads.
    - `test_show_study`: `show_study("toystudy")["study"] == toy_pre()`, and `show_study("nope")` raises with `"no study named 'nope'"` and `"toystudy"`.
    - `test_study_guide_is_the_readme`: the text contains `"### From draft to launch"`.
    - `test_checks_never_imports_modes`: `subprocess.run([sys.executable, "-c", "import sys, service.checks; sys.exit('modes' in sys.modules or 'core.modes' in sys.modules)"], cwd=ROOT, env=engine_env(...)).returncode == 0`.
  - **`TestJobs(_Svc)`,** using `local = dict(executor="local", parallel=1)`:
    - `test_a_good_study_by_name_passes`:
      - `start_check("toystudy", x=[1.5, 2], **local)`;
      - `job_id` starts with `"toystudy-"`;
      - `"--x=1.5,2.0 --executor local --parallel 1 --json"` is in `command`;
      - after `wait`: `done`, exit 0, `report["ok"]` true, `report["point"] == {"x1": 1.5, "x2": 2.0}` and `error` None.
    - `test_a_good_study_by_relative_path_passes`:
      - `os.chdir(self.tmp)` (cleanup: chdir back);
      - `start_check("studies/toystudy.json", **local)`;
      - `target == str(self.tmp / "studies" / "toystudy.json")`;
      - exit 0.
    - `test_study_json_writes_the_draft_and_passes`:
      - `start_check(study_json=toy_pre(name="drafty"), **local)`;
      - `data/study_drafts/drafty.json` parses to that doc and is the `target`;
      - exit 0.
    - `test_an_unknown_name_is_exit_2`:
      - `start_check("nope", **local)`;
      - exit 2, `report` and `error` None;
      - `"nope"` is in `stderr_tail`.
    - `test_a_killed_job_is_lost`:
      - start a check;
      - at once, `os.killpg(<pid from job.json>, SIGKILL)` (the job leads its own session);
      - `wait`;
      - `lost`, with `exit_code` None.
    - `test_an_activate_failure_is_done_with_its_message`:
      - a service whose env adds `AUTORESEARCH_PYENV="ana"` and drops `AUTORESEARCH_VENV`;
      - `done`, exit 1, `report` None;
      - `error == "check_study's output is not JSON"`;
      - `"NAME VERSION"` is in `stderr_tail`.
    - `test_a_job_id_that_is_a_path_is_unknown`: `""`, `"."`, `".."`, `"../check_jobs"`, `"/etc/passwd"` and `"nope-1"` each raise with `"no check job"`.
    - `test_refusals`:
      - both of `study` and `study_json`, and neither, each raise with `"exactly one of"`;
      - `study_json` given as `[]`, `{}`, `{"name": ""}` and `{"name": "a-b"}` each raise with `"study_json.name"`;
      - `jobs_dir` is not created and `drafts_dir` stays empty.
- [ ] **Step 2: Run them to see them fail.**
  - Run: `PYTHONPATH= $PY -m unittest tests.test_service -v`
  - Expected: `ModuleNotFoundError: No module named 'service'`.
- [ ] **Step 3: Implement** `service/__init__.py` and `service/checks.py` as in Interfaces. `checks.py` does not touch `sys.path`: the server and the tests put the repo root on it.
- [ ] **Step 4: Run them again.** Expected: 12 OK.
- [ ] **Step 5: Commit:** `git add service tests/test_service.py && git commit -m "service: CheckService -- study queries and detached check_study jobs"`.

### Task 2: The MCP server

**Files:**
- Create: `service/server.py`
- Modify: `.mcp.json`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `CheckService` (Task 1).
- Produces: `service/server.py`.
  - It puts the repo root on `sys.path`, as `surrogate/mcp_server.py` does.
  - It builds `svc = CheckService()` and `server = MCPServer("autoresearch", instructions=INSTRUCTIONS)`.
  - **Tools,** each a one-line call to `svc` with a docstring saying what it returns:
    - `start_check(study: str = "", study_json: dict[str, Any] | None = None, x: list[float] | None = None, executor: str = "grid", parallel: int | None = None) -> dict[str, Any]`;
    - `check_result(job_id: str) -> dict[str, Any]`;
    - `list_studies() -> list[dict[str, Any]]`;
    - `show_study(name: str) -> dict[str, Any]`;
    - `study_guide() -> str`.
  - `server.run("stdio")` under `__main__`.
  - **`INSTRUCTIONS`** (spec, "Server instructions"):
    - the loop:
      1. read `study_guide`;
      2. draft;
      3. `start_check`;
      4. `check_result` every 30-60 s while `running` (a geometry pre-check takes about 6 minutes);
      5. fix from each failed check's `problems` and `detail`;
      6. repeat;
      7. install only with the operator's OK, then check again by name;
    - the exit codes:
      - 0: passed;
      - 1: a check failed;
      - 2: a bad target, `--x` or executor (see `stderr_tail`);
      - 3: check_study broke (see `report.error`);
    - "another check_study of '<name>' is running" means wait and start again;
    - nothing here submits jobs, launches a campaign or writes a board.
- **`.mcp.json`:** an `"autoresearch"` entry beside `"surrogate"`, with the same `command` and `"args": ["service/server.py"]`.

- [ ] **Step 1: Write the failing test,** `TestStdio(_Svc).test_a_check_through_mcp`, as one `anyio.run` coroutine:
  - **Start:** with `toystudy` written first, `stdio_client(StdioServerParameters(command=sys.executable, args=[str(ROOT / "service" / "server.py")], env=engine_env(self.data, self.studies), cwd=str(ROOT)))`, then `ClientSession`, then `initialize()`.
  - **Instructions:** `init.instructions` contains `"check_result"` and `"submits"`.
  - **Tools:** the sorted tool names are `["check_result", "list_studies", "show_study", "start_check", "study_guide"]`.
  - **A check:** `start_check` with `{"study": "toystudy", "executor": "local", "parallel": 1}`.
  - **While it runs:** `list_studies` has `is_error` false, with `"toystudy"` among the `structured_content["result"]` names. This is Review Focus 1.
  - **Poll:** `check_result` until it is not running, with `anyio.sleep(0.5)` and a 120 s cap. Then `done`, exit 0, `report["ok"]` true.
  - **An error:** `check_result` with `{"job_id": "nope"}` has `is_error` true, and its text contains `"no check job"`.
- [ ] **Step 2: Run it to see it fail.**
  - Run: `PYTHONPATH= $PY -m unittest tests.test_service.TestStdio -v`
  - Expected: an error, because the server script does not exist.
- [ ] **Step 3: Implement `service/server.py`** and add the `.mcp.json` entry.
- [ ] **Step 4: Run the tests.**
  - `tests.test_service`: expected 13 OK.
  - The full suite: expected 837 OK (skipped=3). If the count differs, explain it before going on.
- [ ] **Step 5: Commit:** `git add service/server.py .mcp.json tests/test_service.py && git commit -m "service: the autoresearch MCP server (study tools), registered in .mcp.json"`.

### Task 3: Acceptance in a sandbox

**Files:** none in git. Everything goes under `SB=/exp/mu2e/data/users/oksuzian/claude-scratch/mcpaccept`.

- [ ] **Step 1: Prerequisites.**
  - `klist` shows at least 4 h left; if not, stop and ask the operator to `kinit`.
  - Create `$SB/data` and `$SB/studies`.
  - Write `$SB/client.py`. It:
    - starts `service/server.py` over stdio from the worktree, with `AUTORESEARCH_DATA_ROOT=$SB/data` and `AUTORESEARCH_STUDY_PATH=$SB/studies`;
    - for each `start_check` argument dict given as JSON on argv, polls `check_result` every 15 s until done;
    - prints the exit code, `error`, each check's `name`, `status`, `note` and `problems`, and `elapsed_s`.
- [ ] **Step 2: ce_chain, local.**
  - Call `{"study": "ce_chain", "executor": "local", "parallel": 1}`.
  - Expected: exit 0; the geometry note is "rendered, not pre-checked".
- [ ] **Step 3: foilspfbpz_ax, grid.**
  - Call `{"study": "foilspfbpz_ax"}`, in the background, and wait on its result.
  - Expected: exit 0; the pre-check passed, in about 6 minutes.
- [ ] **Step 4: A broken draft.**
  - Use `foilspfbpz_ax.json` with `name` set to `"mcpbroken"`, board `leaderboards/leaderboard_bo_mcpbroken.tsv`, and `"objectives": []`, passed as `study_json`.
  - Expected: exit 1; `load` failed with the loader's message; the other checks skipped; the draft is in `$SB/data/study_drafts/`.
- [ ] **Step 5: Side effects are clean.**
  - The worktree's `git status --short` is empty.
  - `$SB/data/autoresearch_leaderboards` does not exist.
  - Nothing in `/exp/mu2e/data/users/oksuzian/autoresearch_grid` is newer than `$SB`.
  - Record the results in the ledger.

### Task 4: Records

- [ ] **Step 1: `wiki/drivers/service.md`** (OKF, `type: driver`, `status: active`, `timestamp: '2026-10-02'`). It covers:
  - the server, and why it is separate from the surrogate server and never imports `modes`;
  - the tools;
  - the job directory;
  - the `done`/`running`/`lost` rules and the lock handoff (`pass_fds`);
  - the SDK traps;
  - the acceptance results;
  - links to [contract-engine](/drivers/contract-engine.md), [surrogate](/drivers/surrogate.md), the spec and the plan.

  Also add the `wiki/index.md` line under Drivers and the `wiki/log.md` bullet under `## 2026-10-02`.
- [ ] **Step 2: `mode_specs/README.md`,** "From draft to launch": one line after step 3, saying that through MCP the `autoresearch` server's `start_check`/`check_result` run this same check.
- [ ] **Step 3: Suite and commit.** The suite is green. Then: `git add wiki mode_specs/README.md && git commit -m "wiki: the autoresearch MCP server"`.
- [ ] **Step 4: Memory.** Update `project_phase_c1_branches.md` with the branch, its commits and its state, plus its `MEMORY.md` line.
- [ ] **Step 5: After the operator merges and restarts Claude Code (or runs `/mcp`):** one `list_studies` and one `start_check`/`check_result` on `ce_chain` (local), from the session.
