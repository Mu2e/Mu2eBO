# autoresearch MCP Server (study tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An MCP server named `autoresearch` whose five tools let an agent with only MCP access check a study exactly as `python -m graph.check_study` does: start a check, poll for its report, and list, show and read about studies.

**Architecture:**
- `service/checks.py` holds a `CheckService` class: the job logic and the read-only study queries, in plain Python with no MCP. It imports only the standard library, `core.paths` and `core.study`.
- Each check is a detached `bash` job running `graph.check_study --json` into its own job directory, so a check survives a restart of the server or the client.
- `service/server.py` is a thin `MCPServer` with one tool per `CheckService` method, over stdio.

**Tech Stack:** Python 3.12 from ana 2.8.0; the official `mcp` 2.0.0 SDK (`mcp.server.mcpserver.MCPServer`; for tests, `mcp.client.stdio.stdio_client` and `mcp.ClientSession`); unittest.

**Spec:** `docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md`

## Global Constraints

- **Worktree and branch:** `/exp/mu2e/app/users/oksuzian/autoresearch-checkstudy`, branch `autoresearch-mcp` (from cabdeda; the spec is a31a2ec).
- **Suite:**
  - The command is `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`, run from the worktree.
  - The baseline is 824 OK (skipped=3), so the final count is 824 plus this plan's new tests, all OK.
- **Imports in `service/checks.py`:** only the standard library, `from core import paths` and `from core import study as st`.
  - It never imports `modes`, `graph.run`, `graph.check_study`, `core.contract` or `core.kits`.
  - The reason: a broken study on the study path must not stop the server that reports it.
- **Writes:** the server writes only:
  - `<data root>/study_drafts/<name>.json`;
  - `<data root>/autoresearch_graph_data/check_jobs/<job_id>/`;
  - whatever check_study writes itself.

  Nothing ever submits, launches or writes a board.
- **SDK usage:**
  - Every tool is `@server.tool(structured_output=True)`.
  - A tool's return annotation is `dict[str, Any]`, `list[dict[str, Any]]` or `str`; a bare `dict` is refused by the SDK as "not serializable for structured output".
  - A tool that raises `ValueError` reaches the client as `is_error` with the text `Error executing tool <name>: <message>`.
  - A `list` return arrives as `structured_content == {"result": [...]}`.
- **Every `measure_basis_sha` is unchanged:**

  | Study | sha |
  |---|---|
  | ce_chain | 79b9b3e2 |
  | foilsflash_ax | 405cc0e8 |
  | foilspf2k_ax | 2060c97e |
  | foilspf_ax | e96f0491 |
  | foilspfbp_ax | 54467d3e |
  | foilspfbpx_ax | d6ee2d28 |
  | foilspfbpz_ax | c4aafee1 |
  | foilspfbw_ax | 01bcbd62 |

- **Scratch:** acceptance scratch goes under `/exp/mu2e/data/users/oksuzian/claude-scratch/mcpaccept/`, never `/tmp`. Unit tests use `tempfile.TemporaryDirectory`, as the existing suite does.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

**Ruling (plan against spec):** the spec's job command sends `activate.sh`'s stderr to `/dev/null`. That loses the message the spec's very next bullet promises in `stderr_tail`. The plan's command therefore sends it to `"$1/stderr.log"`, and check_study's stderr is appended there (`2>>`). The cost if this is wrong is one redirect.

## Review Focus

1. **A job writing on the MCP stream.** The server's stdin and stdout carry the protocol, so a child that inherits them corrupts the session.
   - **Expected:** every job runs with stdin, stdout and stderr at `DEVNULL`, and the session keeps answering while a check runs.
   - **Test:** Task 3's stdio test calls `list_studies` while its check job is running.
2. **A `job_id` that is a path** (`../x`, `/etc/passwd`, `""`).
   - **Expected:** refused as an unknown job; nothing outside `check_jobs/` is read.
   - **Test:** Task 2, `test_a_job_id_that_is_a_path_is_unknown`.
3. **A recorded pid reused by another process,** or left as a zombie, after a server restart.
   - **Expected:** `lost`, not `running` forever.
   - **Test:** Task 2, `test_a_reused_pid_is_lost`. It writes a job whose pid is alive but has a different `/proc` start time.
4. **A relative path in `study`.**
   - **Expected:** resolved against the server's working directory when the check starts, because the job runs from the repo root.
   - **Test:** Task 2, `test_a_relative_path_is_made_absolute`.
5. **`activate.sh` fails,** for example on a bad `AUTORESEARCH_PYENV`.
   - **Expected:** `done`, `report` null, `error` "check_study's output is not JSON", and the activate message in `stderr_tail`.
   - **Test:** Task 2, `test_an_activate_failure_is_done_with_its_message`.

---

### Task 1: The service package and the read-only queries

**Files:**
- Create: `service/__init__.py` (empty)
- Create: `service/checks.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Produces, in `service/checks.py`:
  - **Constants:**
    - `EXECUTORS = ("grid", "local")`, which must equal `core.contract.EXECUTORS`; a test pins this;
    - `MODES_DIR = paths.REPO_ROOT / "mode_specs"`;
    - `STUDY_PATH_ENV = "AUTORESEARCH_STUDY_PATH"`;
    - `DATA_ROOT_ENV = "AUTORESEARCH_DATA_ROOT"`;
    - `TAIL_LINES = 40`.
  - **`class CheckService`:**
    - `__init__(self, env: Optional[Mapping[str, str]] = None)`
      - `self.env` is `dict(os.environ if env is None else env)`.
      - `self.data_root` is `Path(env[DATA_ROOT_ENV])` when that key is set and non-empty, else `paths.DATA_ROOT`.
      - `self.drafts_dir` is `self.data_root / "study_drafts"`.
      - `self.jobs_dir` is `self.data_root / paths.GRAPH_DATA.name / "check_jobs"`.
    - `study_files(self) -> List[Path]` returns `st.study_files(MODES_DIR, self.env.get(STUDY_PATH_ENV))`.
    - `list_studies(self) -> List[dict]` returns one entry per file:
      - **Every entry:** `{"name": <file stem>, "path": str, "loads": bool, "error": str|None, "knobs": [...]|None, "objectives": [...]|None, "board": str|None}`.
      - **A file that loads:**
        - `knobs` is `[{"name", "type", "min", "max", "unit"}]`;
        - `objectives` is `[{"name", "direction"}]`;
        - `board` is `Path(study.leaderboard_rel).name`.
      - **A file that fails:**
        - `loads` is false;
        - `error` is the exception text (`str(exc)` for a `ValueError`, else `"<Type>: <msg>"`);
        - the other three fields are None.
      - **A study whose `name` is not its file stem** fails with the error `"study name '<name>' does not match its file name '<stem>'"`.
    - `show_study(self, name: str) -> dict` returns `{"path": str, "study": <the file's JSON>}`.
      - An unknown name raises `ValueError("no study named '<name>' on the study path; known: [...]")`, listing the sorted stems.
      - A file that is not JSON raises `ValueError("<path>: not JSON: <exc>")`.
    - `study_guide(self) -> str` returns `(MODES_DIR / "README.md").read_text()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_service.py`.
  - **Header:** import `CheckService` and the constants from `service.checks`, with `ROOT` on `sys.path` as `tests/test_check_study.py` does.
  - **Builders:** reuse `tests.engine_fixtures`: `toy_doc`, `write_study`, `engine_env`.
  - **Base class `_Svc`:**
    - a temp dir with `studies/` and `data/`;
    - `self.svc = CheckService(env=engine_env(self.data, self.studies))`;
    - `toy_pre(name="toystudy", **kits)`, which is `toy_doc(name)` (its board is `leaderboard_<name>.tsv`) with `doc["preflight"] = {"kit": "toykit", "files": [], "params": {}}` and `doc["kits"]["toykit"]` updated with `kits`, as the helper in `tests/test_check_study.py` does.
  - **Class `TestQueries(_Svc)`:**
    - `test_list_has_good_and_broken_files`:
      - Set-up:
        - `write_study(toy_pre(), studies)`;
        - `(studies / "broken.json").write_text("{}")`;
        - a third file, `(studies / "misnamed.json").write_text(json.dumps(toy_doc(name="other")))`.
      - Index `svc.list_studies()` by name.
      - Assertions:
        - `toystudy` has `loads` true, `error` None, `board == "leaderboard_toystudy.tsv"`, `[k["name"] for k in knobs] == ["x1", "x2"]` and `objectives[0] == {"name": "branin", "direction": "min"}`;
        - `broken` has `loads` false, a non-empty `error` and `knobs` None;
        - `misnamed` has `loads` false, with `"does not match its file name"` in `error`;
        - `ce_chain` is listed with `loads` true, because `mode_specs/` is always on the path.
    - `test_show_study_returns_the_file`:
      - `svc.show_study("toystudy")["study"] == toy_pre()`;
      - `path` ends with `"toystudy.json"`.
    - `test_show_study_unknown_names_the_known`: `ValueError` whose text contains `"no study named 'nope'"` and `"toystudy"`.
    - `test_study_guide_is_the_readme`: contains `"### From draft to launch"`.
    - `test_executors_match_the_engine`: `checks.EXECUTORS == contract.EXECUTORS` (import `core.contract` in the test only).
    - `test_checks_never_imports_modes`:
      - Run `subprocess.run([sys.executable, "-c", "import sys, service.checks; sys.exit('modes' in sys.modules or 'core.modes' in sys.modules)"], cwd=ROOT, env=engine_env(...))`.
      - Assert `returncode == 0`.
    - `test_a_relative_study_path_entry_is_an_error`: a `CheckService` whose env has `AUTORESEARCH_STUDY_PATH="rel/dir"`; `list_studies()` raises `ValueError`.
- [ ] **Step 2: Run them to see them fail.**
  - Run: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest tests.test_service -v`
  - Expected: `ModuleNotFoundError: No module named 'service'`.
- [ ] **Step 3: Implement `service/__init__.py` and `service/checks.py`** with the Interfaces above.
  - The module docstring says what the module is.
  - `checks.py` does not edit `sys.path`: the server and the tests put the repo root on it.
- [ ] **Step 4: Run the tests again.** Expected: 7 OK.
- [ ] **Step 5: Commit:** `git add service/__init__.py service/checks.py tests/test_service.py && git commit -m "service: CheckService, the read-only study queries"`.

### Task 2: Check jobs (`start_check`, `check_result`)

**Files:**
- Modify: `service/checks.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `CheckService`, `EXECUTORS`, `TAIL_LINES` (Task 1).
- Produces, in `service/checks.py`:
  - **`JOB_SCRIPT`,** the exact `bash -c` text (spec, with the ruling above):
    ```
    source ./activate.sh >/dev/null 2>"$1/stderr.log" && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study "${@:2}" --json >"$1/report.json" 2>>"$1/stderr.log"; echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"
    ```
  - **`proc_start(pid: int) -> Optional[str]`:** the process's start time (field 22 of `/proc/<pid>/stat`), or None if there is no such process or it is a zombie.
    - Parse after the last `")"`: `rest = text[text.rindex(")") + 2:].split()`.
    - The state is `rest[0]` (None if `"Z"`); the start time is `rest[19]`.
  - **`CheckService.start_check(self, study: str = "", study_json: Optional[dict] = None, x: Optional[Sequence[float]] = None, executor: str = "grid", parallel: Optional[int] = None) -> dict`**, which returns `{"job_id", "target", "command"}`.
    - **Refusals,** each a `ValueError` whose message contains:
      - both `study` and `study_json` given: `"not both"`;
      - neither given: `"give study"`;
      - `study_json` not a dict: `"must be a JSON object"`;
      - `study_json` with `name` missing or not matching `^[A-Za-z0-9_]+$`: `"study_json.name"`;
      - an executor not in `EXECUTORS`: `"executor must be one of"`;
      - `parallel` without `"local"`: `"parallel goes with executor='local' only"`.
    - **Target:**
      - For `study_json`, the draft is written as `json.dumps(doc, indent=1) + "\n"` to `drafts_dir/<name>.json` (parents made), and the target is that path.
      - A `study` that ends in `.json` or contains `/` becomes `str(Path(study).absolute())`.
      - Anything else is passed through as a name.
    - **Arguments to check_study:**
      - the target;
      - then `--x=<v1>,<v2>,...` with `repr(float(v))`, only when `x is not None`;
      - then `--executor <executor>`;
      - then `--parallel <n>` when `parallel` is not None.
    - **`job_id`:** `f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"`, where `stem` is `Path(target).stem`. The job directory is `jobs_dir / job_id`, made with `parents=True, exist_ok=False`.
    - **Launch:** `subprocess.Popen(["bash", "-c", JOB_SCRIPT, "_", str(job_dir), *args], cwd=paths.REPO_ROOT, env=self.env, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)`.
      - A daemon thread runs `proc.wait`, so a finished job is reaped.
    - **`command`:** `'PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study ' + shlex.join([*args, "--json"])`.
    - **`job.json`:** written after the launch, holding `{"job_id", "target", "args", "command", "pid", "proc_start": proc_start(pid), "started": time.time()}`.
  - **`CheckService.check_result(self, job_id: str) -> dict`**, which returns `{"job_id", "state", "exit_code", "elapsed_s", "report", "stderr_tail", "error"}`.
    - **Unknown job:** a `job_id` that is empty, contains `/`, is `.` or `..`, or has no `jobs_dir/job_id/job.json` raises `ValueError(f"no check job {job_id!r} in {jobs_dir}")`.
    - **State,** in this order (it avoids the race of a job that ends between two reads):
      1. If `rc` exists, the job is `done`.
      2. Otherwise, if `proc_start(pid) == job["proc_start"]`, it is `running`.
      3. Otherwise, if `rc` exists now, it is `done`; else it is `lost`.
    - **When `done`:**
      - `exit_code` is the integer in `rc`.
      - On exit 2, `report` is None and `error` is None.
      - On any other exit, `report` is the parsed `report.json`. If the file is missing, empty or not JSON, `report` is None and `error` is `"check_study's output is not JSON"`.
    - **`elapsed_s`** is rounded to 0.1. It is `rc`'s mtime minus `started` when `done`, else now minus `started`.
    - **`stderr_tail`** is the last `TAIL_LINES` lines of `stderr.log`, or `""` if there is none. It is returned in every state.

- [ ] **Step 1: Write the failing tests**, class `TestJobs(_Svc)`.
  - **Helpers:**
    - `self.local = dict(executor="local", parallel=1)`;
    - `wait(job_id, timeout=120)`, which polls `check_result` every 0.5 s until `state != "running"` and returns the result. A timeout fails the test.
  - **Tests:**
    - `test_a_good_study_by_name_passes`:
      - `write_study(toy_pre(), studies)`, then `start_check("toystudy", **local)`;
      - `job_id` starts with `"toystudy-"`;
      - `"--executor local --parallel 1 --json"` is in `command`;
      - after `wait`: `state == "done"`, `exit_code == 0`, `report["ok"]` true and `error` None.
    - `test_a_good_study_by_path_passes`: the same with `str(path)`, where `path` is the study's absolute path; `target == str(path)`.
    - `test_study_json_writes_the_draft_and_passes`:
      - `start_check(study_json=toy_pre(name="drafty"), **local)` (its own board, `leaderboard_drafty.tsv`);
      - `data/study_drafts/drafty.json` exists and equals the doc;
      - `target` is that path;
      - exit 0.
    - `test_a_failing_precheck_is_exit_1`:
      - `toy_pre(function="reject")`;
      - exit 1;
      - `geometry` has status `"failed"`, and one of its problems contains `"fails the check"`.
    - `test_an_unknown_name_is_exit_2`:
      - `start_check("nope", **local)`;
      - exit 2, `report` None, `error` None;
      - `"nope"` is in `stderr_tail`.
    - `test_x_is_passed_through`:
      - `start_check("toystudy", x=[1.5, 2], **local)`;
      - `"--x=1.5,2.0"` is in `command`;
      - `report["point"] == {"x1": 1.5, "x2": 2.0}`.
    - `test_a_killed_job_is_lost`:
      - start a check;
      - at once, `os.killpg(job["pid"], signal.SIGKILL)`, with `pid` read from `job.json`;
      - `wait`;
      - `state == "lost"` and `exit_code` None.
    - `test_a_reused_pid_is_lost`:
      - start `p = subprocess.Popen(["sleep", "30"])` (cleanup: kill and wait);
      - hand-write `jobs_dir/"fake-20261002-000000-abcd"/job.json` with `pid=p.pid`, `proc_start="1"` and `started=time.time()`;
      - `check_result` gives `lost`;
      - rewrite it with `proc_start=proc_start(p.pid)`, and it gives `running`.
    - `test_a_job_id_that_is_a_path_is_unknown`: `""`, `"."`, `".."`, `"../check_jobs"`, `"/etc/passwd"` and `"nope-1"` each raise `ValueError` containing `"no check job"`.
    - `test_refusals`: each of the six refusals in Interfaces raises `ValueError` with its message fragment, and no job directory is created (`jobs_dir` is absent or empty).
      - For the `study_json.name` refusal, cover three docs: `{"name": "a-b"}`, `{"name": ""}` and `{}`.
    - `test_a_relative_path_is_made_absolute`:
      - `os.chdir(self.tmp)` (cleanup: chdir back);
      - `start_check("studies/toystudy.json", **local)`;
      - `target == str(self.tmp / "studies" / "toystudy.json")`;
      - exit 0.
    - `test_an_activate_failure_is_done_with_its_message`:
      - a `CheckService` whose env adds `AUTORESEARCH_PYENV="ana"` and drops `AUTORESEARCH_VENV` (which would skip the pyenv branch);
      - `start_check("toystudy", **local)`;
      - `state == "done"`, `exit_code == 1`, `report` None;
      - `error == "check_study's output is not JSON"`;
      - `"NAME VERSION"` is in `stderr_tail`.
- [ ] **Step 2: Run them to see them fail.**
  - Run: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest tests.test_service.TestJobs -v`
  - Expected: errors, `AttributeError: 'CheckService' object has no attribute 'start_check'`.
- [ ] **Step 3: Implement** `JOB_SCRIPT`, `proc_start`, `start_check` and `check_result` in `service/checks.py`, as in Interfaces.
- [ ] **Step 4: Run** `tests.test_service`. Expected: all OK, 19 tests.
- [ ] **Step 5: Commit:** `git commit -am "service: check jobs -- start_check and check_result over a detached check_study"`.

### Task 3: The MCP server

**Files:**
- Create: `service/server.py`
- Modify: `.mcp.json`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `CheckService` and its five methods (Tasks 1-2).
- Produces:
  - `service/server.py`, which puts the repo root on `sys.path` (as `surrogate/mcp_server.py` does), then builds `svc = CheckService()` and `server = MCPServer("autoresearch", instructions=INSTRUCTIONS)`.
    - **Tools:**

      | Tool | Returns |
      |---|---|
      | `start_check(study: str = "", study_json: dict[str, Any] \| None = None, x: list[float] \| None = None, executor: str = "grid", parallel: int \| None = None)` | `dict[str, Any]` |
      | `check_result(job_id: str)` | `dict[str, Any]` |
      | `list_studies()` | `list[dict[str, Any]]` |
      | `show_study(name: str)` | `dict[str, Any]` |
      | `study_guide()` | `str` |

    - Each tool is a one-line call to `svc`, with a docstring that says what it returns.
    - `if __name__ == "__main__": server.run("stdio")`.
  - **`INSTRUCTIONS`,** in substance (spec, "Server instructions"):
    - the five tools;
    - the loop:
      1. read `study_guide`;
      2. draft;
      3. `start_check`;
      4. `check_result` every 30-60 s until `state` is not `running` (a geometry pre-check takes about 6 minutes);
      5. fix from each failed check's `problems` and `detail`;
      6. repeat;
      7. install only with the operator's OK, then check again by name;
    - the exit codes:
      - 0: every check passed;
      - 1: a check failed;
      - 2: a bad target or `--x`, see `stderr_tail`;
      - 3: check_study itself broke, see `report.error`;
    - "another check_study of '<name>' is running" means wait and start again;
    - nothing here submits jobs, launches a campaign or writes a board.
  - **`.mcp.json`:** add an `"autoresearch"` entry beside `"surrogate"`, with `"command": "/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python"` and `"args": ["service/server.py"]`.

- [ ] **Step 1: Write the failing test**, class `TestStdio(_Svc)`, method `test_a_check_through_mcp`. It runs one `anyio.run` coroutine:
  - **Start:** `stdio_client(StdioServerParameters(command=sys.executable, args=[str(ROOT / "service" / "server.py")], env=engine_env(self.data, self.studies), cwd=str(ROOT)))`, then `ClientSession`, then `initialize()`.
  - **Instructions:** `init.instructions` contains `"check_result"` and `"submits"`.
  - **Tools:** `sorted(t.name for t in (await s.list_tools()).tools) == ["check_result", "list_studies", "show_study", "start_check", "study_guide"]`.
  - **A check:**
    - `write_study(toy_pre(), studies)` (before the server starts);
    - `start_check` with `{"study": "toystudy", "executor": "local", "parallel": 1}`;
    - `is_error` false; `structured_content["job_id"]` starts with `"toystudy-"`.
  - **While it runs:** `list_studies` has `is_error` false, and `"toystudy"` is among the `name`s of `structured_content["result"]`. This is Review Focus 1.
  - **Poll:** `check_result` every 0.5 s (with `anyio.sleep`) for up to 120 s, until `state != "running"`. Then `state == "done"`, `exit_code == 0` and `report["ok"]` true.
  - **An error:** `check_result` with `{"job_id": "nope"}` has `is_error` true, and its text contains `"no check job"`.
  - **After the error:** the session still answers `study_guide`.
- [ ] **Step 2: Run it to see it fail.**
  - Run: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest tests.test_service.TestStdio -v`
  - Expected: an error. stdio_client fails or the connection closes, because `service/server.py` does not exist.
- [ ] **Step 3: Implement `service/server.py`** and add the `.mcp.json` entry.
- [ ] **Step 4: Run the tests.**
  - `tests.test_service`: expected 20 OK.
  - Then the full suite: expected 844 OK (skipped=3). The count is 824 + 20; if another test count comes out, explain it before going on.
  - Then the eight `measure_basis_sha` values, from the worktree: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -c "import sys; from pathlib import Path; sys.path.insert(0, 'core'); import study as st; [print(n, s.measure_basis_sha[:8]) for n, s in sorted(st.load_study_dirs(Path('mode_specs'), None).items())]"`. Expected: the table in Global Constraints.
- [ ] **Step 5: Commit:** `git add service/server.py .mcp.json tests/test_service.py && git commit -m "service: the autoresearch MCP server (study tools), registered in .mcp.json"`.

### Task 4: Acceptance in a sandbox

**Files:** none in git. The client script and the results go to `SB=/exp/mu2e/data/users/oksuzian/claude-scratch/mcpaccept`.

- [ ] **Step 1: Prerequisites.**
  - `klist` shows at least 4 h left; if not, stop and ask the operator to `kinit`.
  - Create `$SB/data` and `$SB/studies`.
  - Write `$SB/client.py`. It:
    - takes a JSON list of `start_check` argument dicts;
    - starts `service/server.py` over stdio from the worktree, with `AUTORESEARCH_DATA_ROOT=$SB/data` and `AUTORESEARCH_STUDY_PATH=$SB/studies` added to the current env (after `source ./activate.sh`);
    - for each dict, calls `start_check`, then `check_result` every 15 s until done;
    - prints `exit_code`, `error`, each check's `name`, `status`, `note` and `problems`, and the elapsed time.
- [ ] **Step 2: ce_chain, local.**
  - Call `{"study": "ce_chain", "executor": "local", "parallel": 1}`.
  - Expected: exit 0; `geometry` passed with note "rendered, not pre-checked".
- [ ] **Step 3: foilspfbpz_ax, grid.**
  - Call `{"study": "foilspfbpz_ax"}`, run in the background, and wait on its result.
  - Expected: exit 0; geometry passed with the pre-check, in about 6 minutes.
- [ ] **Step 4: A broken draft.**
  - Use `foilspfbpz_ax.json`'s JSON, renamed `name: "mcpbroken"`, with board `leaderboards/leaderboard_bo_mcpbroken.tsv` and its first knob's `"fmt"` changed to `"{:d}"` (a real knob is real-valued, so the loader refuses it).
  - Expected: exit 1; `load` failed with a message naming `fmt`; the other checks skipped; `$SB/data/study_drafts/mcpbroken.json` exists.
  - **Ruling at run time:** if that edit loads, pick another field the loader refuses, such as a misspelt `objectives[0].metric` step, and record it.
- [ ] **Step 5: Side effects are clean.**
  - `git -C /exp/mu2e/app/users/oksuzian/autoresearch-checkstudy status --short` is empty.
  - `$SB/data/autoresearch_leaderboards` holds nothing new.
  - `find /exp/mu2e/data/users/oksuzian/autoresearch_grid -maxdepth 1 -newer $SB` is empty.
  - Record the three results in the ledger.

### Task 5: Records

**Files:**
- Create: `wiki/drivers/service.md`
- Modify: `wiki/index.md`, `wiki/log.md`, `mode_specs/README.md`
- Memory: `project_phase_c1_branches.md`, plus its `MEMORY.md` line

- [ ] **Step 1: `wiki/drivers/service.md`.**
  - OKF frontmatter: `type: driver`, `status: active`, `timestamp: '2026-10-02'`.
  - **Summary:** the server, why it is separate from the surrogate server, and why it never imports `modes`.
  - **Key facts:**
    - the five tools and their returns;
    - the job directory layout (`job.json`, `report.json`, `stderr.log`, `rc` written last);
    - the `done`/`running`/`lost` rules, including the `/proc` start-time check;
    - the activate-stderr ruling;
    - the SDK traps: `dict[str, Any]` not `dict`, a list wrapped in `{"result": ...}`, `is_error` and `structured_content` rather than the camelCase names;
    - the acceptance times.
  - **Cross-links:** [contract-engine](/drivers/contract-engine.md) (check_study), [surrogate](/drivers/surrogate.md), the spec and the plan.
  - Add the `wiki/index.md` line under Drivers and the `wiki/log.md` bullet under `## 2026-10-02`.
- [ ] **Step 2: `mode_specs/README.md`,** "From draft to launch": one line after step 3, saying that through MCP the `autoresearch` server's `start_check`/`check_result` run this same check.
- [ ] **Step 3: Suite and commit.** The suite is green. Then: `git add wiki mode_specs/README.md && git commit -m "wiki: the autoresearch MCP server"`.
- [ ] **Step 4: Memory.** Update `project_phase_c1_branches.md` with the branch, its commits and its state, plus its `MEMORY.md` line.
- [ ] **Step 5: After the merge, not on this branch.**
  - The live check from a Claude Code session needs the main checkout's `.mcp.json`, and a restart or `/mcp`.
  - So once the operator merges and restarts: one `list_studies` and one `start_check`/`check_result` on `ce_chain` (local), from the session.
