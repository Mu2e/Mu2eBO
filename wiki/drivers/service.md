---
type: driver
title: autoresearch MCP server (study tools)
description: service/ — the `autoresearch` MCP server (stdio, .mcp.json); start_check/check_result run `graph.check_study --json` as a detached job polled for its report, plus list_studies/show_study/study_guide; liveness is a flock the server hands to the job (pass_fds); never imports modes; accepted 2026-10-02 (ce_chain local 58 s, foilspfbpz_ax grid pre-check 314 s, broken draft 1.3 s)
status: active
timestamp: '2026-10-02'
---

# autoresearch MCP server (study tools)

## Summary
`service/` is the `autoresearch` MCP server, piece 3 of the study-writing
line. It lets an agent with only MCP access draft a study, have it checked
exactly as `python -m graph.check_study` checks it (see
[contract-engine](/drivers/contract-engine.md), check_study), and fix it
from the report.

It is a separate server from [surrogate](/drivers/surrogate.md) because
the surrogate server imports `modes`, which loads every study at start-up,
so one broken study file would stop it. The surrogate server is also
surrokit's generated scaffold. `service/checks.py` imports only the
standard library plus `core/paths.py` and `core/study.py`.

The campaign tools planned for this server (`campaign_status`,
`leaderboard`, `start_campaign(confirm)`) come later.

## Key facts
- **Files:**
  - `service/checks.py`: `CheckService`, plain Python with no MCP.
  - `service/server.py`: an `MCPServer("autoresearch")` with one tool per method.
  - `.mcp.json`: the `"autoresearch"` entry, with the ana 2.8.0 python and `args ["service/server.py"]`.
- **Tools:**
  - `start_check(study | study_json, x, executor, parallel)` returns `{job_id, target, command}` at once.
  - `check_result(job_id)` returns `{state: running|done|lost, exit_code, elapsed_s, report, stderr_tail, error}`.
  - `list_studies()` returns name, path, loads/error, knob and objective names, and the board basename.
  - `show_study(name)` and `study_guide()` (the text of `mode_specs/README.md`).
- **Two refusals in the server:**
  - not exactly one of `study` and `study_json`;
  - a `study_json` whose `name` is not `[A-Za-z0-9_]+`, since that name becomes a file name.

  check_study decides everything else, with one set of rules. An unknown name, a bad `--x` or an unknown executor is exit 2; `--parallel` with grid fails the launch check.
- **Drafts:** a `study_json` is written to `<data root>/study_drafts/<name>.json`, replacing an earlier draft of that name, and checked from there.
- **A relative path** in `study` is made absolute against the server's working directory, because the job runs from the repo root.
- **Job directory:** `<data root>/autoresearch_graph_data/check_jobs/<study>-<YYYYmmdd-HHMMSS>-<4hex>/` holds:
  - `job.json` (target, args, command, pid, start time);
  - `lock`;
  - `report.json` (check_study's stdout);
  - `stderr.log` (activate.sh's stderr, then check_study's);
  - `rc`, written last through `rc.tmp` and an mv.

  Nothing cleans old job directories.
- **The job:** `bash -c 'source ./activate.sh … && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study "${@:2}" --json …'`, run with `start_new_session=True` and stdin, stdout and stderr all `DEVNULL`.
  - The server's own stdin and stdout carry the MCP stream, so a job must never inherit them.
  - A daemon thread `wait()`s on each job. Without it, every dropped `Popen` raised a ResourceWarning and a long-lived server would collect zombies.
- **Liveness is a lock, not a pid.**
  - Before the launch, the server opens `lock`, takes `flock(LOCK_EX)`, passes that fd to the job (`pass_fds`), and closes its own copy.
  - The lock belongs to the open file description, so it is held as long as any job process holds the fd: the job, check_study, and any process they spawn that keeps it open.
  - It is released on exit and on SIGKILL. Measured on the CephFS data volume 2026-10-02.
  - There is no start race, which taking the lock inside the job script would have had, and nothing goes wrong after a restart (a reused pid, a zombie).
  - The pid in `job.json` is only for killing a stuck job by hand (`kill -9 -<pid>`: the job leads its own process group).
- **State rule** (`check_result`):
  1. If `rc` exists, the job is `done`.
  2. Otherwise, if the lock is held (a non-blocking flock gets `BlockingIOError`), it is `running`.
  3. Otherwise, if `rc` exists now, it is `done`; else it is `lost`.

  Reading `rc` twice closes the race of a job that ends between the two reads.
- **When `done`:**
  - Exit 2: `report` is null; the reason is in `stderr_tail`.
  - Any other exit: `report` is the parsed `report.json`, or null with `error` "check_study's output is not JSON". That is how an `activate.sh` failure shows up, with its message in `stderr_tail`.
- **mcp 2.0.0 SDK traps** (measured 2026-10-02):
  - A tool returning a bare `dict` is refused at import with "not serializable for structured output"; annotate `dict[str, Any]`.
  - A `list` return reaches the client as `structured_content == {"result": [...]}`.
  - A `ValueError` raised in a tool becomes `is_error` with the text `Error executing tool <name>: <msg>`.
  - The client-side attributes are snake_case: `is_error`, `structured_content`. `isError` raises AttributeError.
- **Bare core imports:** `service/checks.py` imports `core/` modules bare, with `core/` on `sys.path`, as every engine module does.
  - A qualified `from core import study` loaded `core.geom_template` beside the bare copy.
  - That failed `tests/test_modes.py` `TestSingleModuleCopy` in the full suite, though not in `tests/test_service.py` on its own.
- **Tests:** `tests/test_service.py`, 14 tests: the queries, toykit jobs with `--executor local --parallel 1`, and one stdio MCP client session. The suite is 838 OK (skipped=3).
- **Acceptance (2026-10-02),** through a stdio client in a sandbox data root:

  | Run | Result | Time |
  |---|---|---|
  | `ce_chain` local | exit 0, geometry "rendered, not pre-checked" | 58.5 s |
  | `foilspfbpz_ax` grid | exit 0, pre-check pass (49 foils verified, 0 overlaps) | 313.8 s |
  | a `study_json` with `"objectives": []` | exit 1, load failed "at least one objective is required", the rest skipped | 1.3 s |

  Side effects were clean.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (check_study), [surrogate](/drivers/surrogate.md)
- Source files: `service/checks.py`, `service/server.py`, `tests/test_service.py`, `.mcp.json`
- Spec: `docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md`; plan: `docs/superpowers/plans/2026-10-02-autoresearch-mcp.md`

## Open questions / TODO
- A live call from a Claude Code session, which needs the main checkout's `.mcp.json` after the merge and a restart or `/mcp`.
- The campaign tools on this server.
