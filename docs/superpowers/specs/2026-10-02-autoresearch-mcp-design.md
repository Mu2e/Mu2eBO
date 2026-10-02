# The autoresearch MCP server: study checking as a service

Date: 2026-10-02. Status: draft for review. Branch `autoresearch-mcp` (from
`generic-study-phase-c1` cabdeda), worktree `../autoresearch-checkstudy`.
Piece 3 of the study-writing line: 1 check_study (merged 2026-10-01), 2 a
study-writing skill (dropped 2026-10-02: no-skill baselines already pass;
`mode_specs/README.md` "From draft to launch" instead), 3 this.

## Goal

An agent with only MCP access (Claude Code or another harness) can draft a
study, have it checked exactly as `python -m graph.check_study` checks it,
and fix it from the report. This starts the planned autoresearch MCP server
(`docs/superpowers/specs/2026-09-23-mcp-framework-plan.md` piece 9, moved up
by its review to roadmap step 4) with the study tools only; the campaign
tools it plans (`campaign_status`, `leaderboard`, `start_campaign(confirm)`)
come later on the same server.

## Decisions taken

- **A new server with the study tools** (operator, 2026-10-02, option 1).
  The surrogate server stays as it is: it loads every study at start-up, so
  one broken file would stop it, and it is surrokit's generated scaffold.
- **Start, then poll** (operator): the geometry pre-check takes about 6
  minutes, so `start_check` returns a job id at once and `check_result`
  returns the report when the job ends.
- **The server never imports `modes`** (nor `graph.run`, which imports it):
  a broken study on the study path must not stop the server that reports it.
- stdio transport only (framework plan, operator 2026-09-22). The SDK is the
  official `mcp` 2.0 in ana 2.8.0 (`mcp.server.mcpserver.MCPServer`); nothing
  to install.

## What changes

### `service/` (new package)

Not named `mcp/`: a top-level `mcp` directory would shadow the SDK.

- `service/checks.py`: the job logic and the read-only study queries, plain
  Python, testable without MCP. Imports only the standard library and
  `core/paths.py`, `core/study.py`.
- `service/server.py`: an `MCPServer` named `autoresearch`, each tool a thin
  wrapper over `checks.py`, run with `server.run("stdio")`.
- `.mcp.json`: a second entry, `"autoresearch"`, with the same interpreter
  as `"surrogate"` and `args ["service/server.py"]`.

### The tools

| Tool | Returns |
|---|---|
| `start_check(study="", study_json=None, x=None, executor="grid", parallel=None)` | `{job_id, target, command}` at once |
| `check_result(job_id)` | `{job_id, state, exit_code, elapsed_s, report, stderr_tail, error}` |
| `list_studies()` | `[{name, path, loads, error, knobs, objectives, board}]` |
| `show_study(name)` | `{path, study}` (the file's JSON) |
| `study_guide()` | the text of `mode_specs/README.md` |

- **`start_check`**: exactly one of `study` (a study name on the study path,
  or a path to a `.json` file) and `study_json` (the study as a JSON object).
  `study_json` is written to
  `$AUTORESEARCH_DATA_ROOT/study_drafts/<name>.json`, replacing an earlier
  draft of that name, and checked from there. `x` is a list of numbers
  (`--x=`); `executor` is `"grid"` or `"local"`; `parallel` only with
  `"local"`. Refused at once, with a message: anything but exactly one of
  `study`/`study_json`; a `study_json` that is not an object or whose
  `name` is missing or not `[A-Za-z0-9_]+` (it names the draft file).
  Everything else is left to check_study, one set of rules: a name that is
  not a study, a bad `--x` or an unknown executor is exit 2, and `parallel`
  with `"grid"` fails its launch check.
- **`check_result`** states:
  - `done`: `rc` exists. Exit 0, 1 or 3: `report` is check_study's JSON
    (on exit 3 it carries `crashed` and `error.traceback`). Exit 2: `report`
    is null and `stderr_tail` says why. A report that does not parse:
    `report` null, `error` "check_study's output is not JSON", and the tail.
  - `running`: no `rc`, and the job still holds its lock; `elapsed_s` since
    start.
  - `lost`: no `rc` and the lock free (the job was killed); `stderr_tail`
    included.
  - An unknown `job_id` is an error naming it.
- **`list_studies`**: every file of `study.study_files(mode_specs/,
  $AUTORESEARCH_STUDY_PATH)`, each loaded on its own: `knobs` and
  `objectives` are name lists and `board` the board's basename (`show_study`
  has the rest); a file that does not load is listed with `loads: false`
  and its error.
- **`show_study`**: by name, the same lookup as check_study; an unknown name
  is an error listing the known ones.
- **Server instructions** (sent to the client at start-up), in substance:
  the tools; the loop (read `study_guide`, draft, `start_check`,
  `check_result` until done, fix from the failed checks' `problems` and
  `detail`, repeat; install with the operator's OK and check again by
  name); the exit codes (0 every check passed, 1 a check failed, 2 a bad
  target or `--x`, 3 check_study broke); and that nothing here submits,
  launches or writes a board.

### How a check job runs

- The command is
  `bash -c 'source ./activate.sh >/dev/null 2>"$1/stderr.log" && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study "${@:2}" --json >"$1/report.json" 2>>"$1/stderr.log"; echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"' _ <job dir> <target> [--x=...] [--executor ...] [--parallel N]`
  (the job directory is an absolute path),
  run from the repo root under
  `subprocess.Popen(..., start_new_session=True)`, so a restart of the
  client or the server does not kill a check in flight. Its stdin, stdout
  and stderr are `/dev/null` (the server's own carry the MCP stream). It
  inherits the server's environment (Kerberos ticket,
  `AUTORESEARCH_DATA_ROOT`, `AUTORESEARCH_STUDY_PATH`).
- **Liveness is a lock, not a pid.** Before the launch the server opens
  `<job dir>/lock`, takes an exclusive `flock` on it and hands that file
  to the job (`pass_fds`), closing its own copy; the lock is then held
  exactly as long as the job's processes live, with no race at start and
  nothing to confuse after a restart (a reused pid, a zombie).
  `check_result` tries the lock without blocking: taken means the job
  ended.
- If `activate.sh` itself fails, check_study never runs and `rc` holds
  that failure: `done` with an empty report, so `error` says "check_study's
  output is not JSON" and the stderr tail shows why. Never silent.
- Job directory `$GRAPH_DATA/check_jobs/<job_id>/`: `job.json` (target,
  argv, start time, and the pid, to kill a stuck job by hand), `lock`, `report.json`, `stderr.log`, and `rc` written
  last.
- `job_id` is `<study>-<YYYYmmdd-HHMMSS>-<4 hex>`; `<study>` is the target's
  file stem (or name).
- Two checks of one study at once: check_study's own per-study lock reports
  the second ("another check_study of ... is running"); the server adds
  nothing.
- Old job directories are kept; there is no clean-up tool.

**Never:** a submit, a launch, a board write, or a write outside
`study_drafts/`, `check_jobs/` and what check_study itself writes.

## Testing

- **`service/checks.py`** (`tests/test_service.py`), with toykit studies in
  a temporary data root and study path, `--executor local --parallel 1`:
  - a good study by name (with `x`), by relative path, and as
    `study_json`: `done`, exit 0, `report.ok` true; the `study_json` draft
    file exists;
  - an unknown name: exit 2, `report` null, the name in `stderr_tail`;
  - a job killed before it ends: `lost`;
  - `activate.sh` failing: `done`, the "not JSON" error, its message in
    `stderr_tail`;
  - refused at once: an unknown or path-like `job_id`; not exactly one of
    `study`/`study_json`; a `study_json` name that is missing or not an
    identifier;
  - `list_studies` with a broken file beside good ones: the good ones
    listed, the broken one with `loads: false` and its error;
  - `show_study` and `study_guide` return the file and the README;
  - `service/checks.py` imports no `modes`.
- **Through MCP**: start `service/server.py` over stdio with the SDK's
  client (`mcp.client.stdio.stdio_client`, `ClientSession`), list the tools,
  `start_check` a toy study, call `list_studies` while it runs, poll
  `check_result` until `done` with exit 0.
- Full suite green.

## Acceptance

Through the stdio client, in a sandbox data root:

1. `ce_chain`, `executor="local"`, `parallel=1`: exit 0, geometry "rendered,
   not pre-checked".
2. `foilspfbpz_ax`, grid: exit 0, the pre-check passed (about 6 minutes).
3. A `study_json` with `"objectives": []`: exit 1, `load` failed with the
   loader's message.

Then the server goes into `.mcp.json`; after a Claude Code restart (or
`/mcp`), one live `list_studies` and one `start_check`/`check_result` from a
session.

## Records

- Wiki: a new page `drivers/service.md` (the server, its tools, the job
  layout), a `log.md` bullet, the `index.md` line.
- `mode_specs/README.md` "From draft to launch": one line pointing at the
  `autoresearch` MCP tools.
- Memory: the branch and its state.

## Not in scope

- The campaign tools (`campaign_status`, `leaderboard`,
  `start_campaign(confirm)`), folding the surrogate tools in, recipes as
  prompts, http transport, trace middleware.
- A clean-up tool for old jobs; a quick check without the pre-check.
