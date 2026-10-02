# Campaign tools on the autoresearch MCP server

Date: 2026-10-02. Status: draft for review.

- **Branch:** `campaign-tools` (from `generic-study-phase-c1` 9b9ad07), worktree `../autoresearch-checkstudy`.
- **Follows:** the server's study tools (`docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md`, merged 2026-10-02).
- **Plan it comes from:** `docs/superpowers/specs/2026-09-23-mcp-framework-plan.md` piece 9. Its review moved this up to roadmap step 4: `campaign_status`, `leaderboard`, `start_campaign(confirm)` gated by the launch checks. Genesis: "expose through MCP".

## Goal

An agent with only MCP access can do four things with a campaign:
- check whether a launch would be accepted, and what it costs;
- launch it, only on an explicit confirm;
- follow it;
- stop it.

It can also read a study's leaderboard. An agent's worker cannot wait hours, so these are campaign-level tools that return at once, or within minutes.

## Decisions taken

- **Dry run, then confirm** (operator, 2026-10-02).
  - `start_campaign(confirm=false)`, the default, checks and reports.
  - Only `confirm=true` launches.
  - Claude Code's own permission prompt stays as a second gate.
- **Status sees any campaign, by prefix** (operator). That includes one started from a shell, read from the files every campaign leaves.
- **The dry run asks `graph.closed_loop` itself** (operator, option 1). A new `--check-only` flag runs every check a real launch runs, then exits without launching. The confirm call runs the same argv without the flag, so the check and the launch cannot disagree.
- **No `modes` import in the server, as for the study tools.** The leaderboard is read through `core/study.py` and `core/boards.py`.
- **Out of scope:**
  - the grid queue (`jobsub_q`: slow, and a child's state already shows what has been submitted or is done);
  - recipes as prompts;
  - trace middleware;
  - folding in the surrogate server;
  - `suggest`/`predict` (the surrogate server has them);
  - a real grid campaign in acceptance, which waits for the operator's word.

## What changes

### `graph/closed_loop.py`: `--check-only`

- **What it does:** after every refusal check passes (the known study, knobs, `--context`, and `launch_problems` with the first child's name and the board), it prints `[closed_loop] OK: would launch study=<s> q=<q> max_evals=<n> prefix=<p> board=<path> executor=<e>` and returns 0. No child, no pool, no STOP read.
- **Refusals are unchanged:** exit 2 with `[closed_loop] REFUSED: <problem>` lines.
- **The loop is untouched:** this is a few lines just before `run_rolling`.

### `service/jobs.py` (new): the detached launch

The check jobs' launch moves into `spawn_detached(job_dir, script, args, env) -> int` (the pid). Both the check jobs and the campaigns use it. It:
- takes `flock` on `job_dir/lock`;
- launches `bash -c <script> _ <job_dir> <args...>` from the repo root, with `start_new_session=True`, stdin/stdout/stderr at `DEVNULL` and `pass_fds` for the lock;
- closes its own copy of the lock;
- starts a reaper thread.

It also provides `lock_held(path) -> bool`, the non-blocking probe.

The check jobs' behaviour and tests are unchanged.

### `service/campaigns.py` (new): `CampaignService(env=None)`

It uses the same environment and data-root rule as `CheckService`. A campaign's folder is `<data root>/autoresearch_graph_data/<prefix>/`, the folder that already holds STOP.

#### `start_campaign`

`start_campaign(study, name_prefix, q, max_evals, picker="hybrid", executor="grid", parallel=None, context=None, stagger=None, confirm=False)`

- **The arguments** become closed_loop's argv:
  - `--study`, `--q`, `--max-evals`, `--picker`, `--name-prefix`;
  - `--context` once per entry;
  - `--executor`;
  - `--parallel` and `--stagger` when given.

  Values are checked by closed_loop, one set of rules. The server checks only that `name_prefix` matches `[A-Za-z0-9_]+`, since it names a folder.
- **Budget,** from the study file through `core/study.py`:
  - `grid_jobs_per_point` is the sum of `fixed.njobs` over the steps whose kit is `prodtools`. For `foilspfbpz_ax` that is 15 + 15 + 100 = 130.
  - `grid_jobs_total` is that sum times `max_evals`.
  - With `executor="local"` both are 0 and `local_jobs_per_point` carries the same sum.

  A study file that does not load gives no budget (null) and the loader's message; closed_loop's own refusal says the rest.
- **Dry run (`confirm=false`):**
  - Runs `source ./activate.sh >/dev/null && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop <argv> --check-only` synchronously from the repo root, with a 600 s cap.
  - Returns `{ok, problems, command, budget, output_tail}`:
    - exit 0 gives `ok: true`;
    - exit 2 gives `ok: false`, with `problems` the `REFUSED:` lines;
    - anything else gives `ok: false`, with `error` "closed_loop's check did not finish (exit N)" and the output's tail. This covers activate.sh failing, a crash or a timeout.

  Nothing is written by the server.
- **Launch (`confirm=true`):**
  - **Refused at once,** before anything is written, when:
    - a live parent already uses this prefix (lock or process scan);
    - `<prefix>/STOP` exists;
    - `<prefix>/campaign.json` exists. That means one MCP launch per prefix; the wiki's recovery after a crash is a new prefix.
  - **Otherwise** it claims the prefix by creating `campaign.json` exclusively (`O_EXCL`, so two concurrent calls cannot both launch), launches through `spawn_detached`, then completes `campaign.json` as `{prefix, study, args, command, pid, started}`. The script is `source ./activate.sh >/dev/null 2>"$1/parent.log" && PYTHONPATH= "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop "${@:2}" >>"$1/parent.log" 2>&1; echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"`.
  - **Then it watches `parent.log` for up to 600 s:**
    - the start line `[closed_loop] study=` gives `{state: "launched", pid, log}`;
    - `rc` appearing first gives `{state: "refused", problems: <the REFUSED lines>, exit_code}`, or `error` if there are none;
    - otherwise it gives `{state: "starting"}`, with "poll campaign_status".

#### `stop_campaign(name_prefix)`

- Creates `<prefix>/STOP`, making the folder if needed.
- Returns `{stop_file, parent_alive, children_running, warning}`.
- `warning` says "no sign of a campaign named <prefix>" when there is no parent, no child log and no `campaign.json`, so a typo is not silent.

#### `campaign_status(name_prefix=None)`

- **With a prefix,** it returns `{prefix, study, parent, stopping, children, rows, best}`.
  - **`parent` is `{alive, pid, launched_by, log_tail}`:**
    - For an MCP launch, `launched_by` is "mcp" and liveness is the lock. When it has ended, `exit_code` comes from `rc`.
    - Otherwise `launched_by` is "shell", and the process comes from a scan of `/proc/*/cmdline`: argv holds `graph.closed_loop` and `--name-prefix` followed by the prefix, or `--name-prefix=<prefix>`. With no match, `alive` is false.
  - **`study`** comes from `campaign.json`, else the live parent's `--study`, else a child's `state/point.json`.
  - **`stopping`** is whether `<prefix>/STOP` exists.
  - **`children`** come from the logs `closed_loop_logs/<prefix>R<digits>_00.log`, matched with that exact pattern so `foo` never picks up `foo2`. Each is `{name, state, last_line}`, and `state` is the first that holds:
    - `scored`: its row is on the board;
    - `broken`: `state/broken.txt` exists;
    - `running`: a `graph.run` process with `--config <name>` is alive;
    - otherwise `ended without a row`.
  - **`rows`** is the number of board rows whose config starts with the prefix; **`best`** is the best of them by the first objective (null when there are none).
- **With no prefix,** it returns `[{prefix, study, alive, launched_by}]` over:
  - live `graph.closed_loop` parents (process scan);
  - every `<prefix>/campaign.json`.

#### `leaderboard(study, name_prefix=None, top=20)`

- Looks the study up by name on the study path, the same lookup as `show_study`, and loads it with `core/study.py`; its board comes from `core/boards.py` (live plus archive).
- Returns `{study, board, n_rows, objective, rows}`:
  - `rows` is best first by the first objective, in its direction (max or min);
  - each row is `{config, x: {knob: value}, values: {name: value}}`;
  - `name_prefix` filters by config;
  - `top` limits the count.
- An unknown study names the known ones. A study file that does not load gives the loader's message.

### `service/server.py`

The four tools are thin wrappers over `CampaignService`, typed for the SDK (`dict[str, Any]`, `list[dict[str, Any]]`). The server instructions gain one paragraph:
- the dry run comes first;
- `confirm=true` only with the operator's OK;
- poll `campaign_status`;
- `stop_campaign` drains;
- a launched campaign submits real grid jobs and writes board rows.

## Testing

### `tests/test_campaigns.py`

Uses the `branin` engine study (toykit, `--picker budget_sob`, local) in a temporary data root.
- **`--check-only`:**
  - exit 0 with the OK line, and no child log, no board, no toykit submit;
  - an unknown study, a zero-knob study and a bad `--context` each give exit 2 with their `REFUSED:` line.
- **Dry run:**
  - `ok`, the command, and the budget: 0 grid jobs for branin, 130 per point for `mode_specs/foilspfbpz_ax.json`;
  - a bad `--context` gives `ok: false` with its problem;
  - `AUTORESEARCH_PYENV="ana"` gives the "did not finish" error with the activate message.
- **Launch:**
  - q=1 and max_evals=2 gives `launched`;
  - `campaign_status` reports alive, then ended with `exit_code` 0, 2 children scored, `rows` 2 and `best`;
  - `leaderboard(name_prefix=...)` returns those 2 rows, best first.
- **Refused at once:**
  - a second launch on the prefix;
  - a STOP file;
  - a live parent: a shell-started `graph.closed_loop` on the prefix.
- **Stop:** launch with max_evals=6 and q=1, then `stop_campaign`. The parent exits with fewer than 6 children, and `stopping` is true. A prefix with no campaign gets the warning.
- **A shell campaign:** `graph.closed_loop` started directly. `campaign_status` finds the parent (`launched_by: "shell"`), and the no-prefix list includes it.
- **Child states** from hand-made files:
  - broken;
  - ended without a row;
  - `foo` against `foo2`.
- **Leaderboard:**
  - the order follows each direction (a min objective ascending);
  - `top`;
  - an unknown study;
  - a broken study file.
- **The check jobs are unchanged:** `tests/test_service.py` passes as it is.

### Through MCP

The stdio test lists nine tools and runs one `start_campaign` dry run.

### Whole suite

The full suite is green, and every `measure_basis_sha` is unchanged.

## Acceptance

Through the stdio client, in a sandbox data root:
1. A dry run of `foilspfbpz_ax` on the grid gives `ok`, with 130 grid jobs per point. Nothing is submitted.
2. A dry run of `ce_chain` is refused: it has no knobs.
3. A real toy campaign, `branin` locally with q=2 and max_evals=4, followed with `campaign_status` and `leaderboard` until 4 rows land. This needs the engine study fixtures on `AUTORESEARCH_STUDY_PATH`.

After the merge and `/mcp`, live from a session:
- `campaign_status` of a past real campaign (for example `bpzax01`), read-only;
- `leaderboard foilspfbpz_ax top=5`, read-only;
- one dry run.

## Records

- `wiki/drivers/service.md`: a campaign-tools section, plus the `log.md` and `index.md` lines.
- `graph/closed_loop.py`'s docstring: `--check-only`.
- Memory: the branch and its state.
