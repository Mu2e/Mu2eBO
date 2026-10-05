---
type: driver
title: autoresearch MCP server (study and campaign tools)
description: service/ — the `autoresearch` MCP server (stdio, .mcp.json); start_check/check_result run `graph.check_study --json` as a detached job polled for its report, plus list_studies/show_study/study_guide; liveness is a flock the server hands to the job (pass_fds); never imports modes; accepted 2026-10-02 (ce_chain local 58 s, foilspfbpz_ax grid pre-check 314 s, broken draft 1.3 s). Campaign tools (2026-10-02): start_campaign (a dry run through `graph.closed_loop --check-only`, confirm=true launches detached; one MCP launch per prefix), stop_campaign, campaign_status (any campaign, shell-started too), leaderboard. Dashboard (2026-10-04): `python -m service.dashboard`, a live flow graph of every campaign from the files (snapshot.json every 2 min, served on 127.0.0.1); campaign_status and the dashboard read the point and campaign records (2026-10-05), liveness by flock, no process scan
status: active
timestamp: '2026-10-05'
---

# autoresearch MCP server (study and campaign tools)

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
- **Live from a Claude Code session (2026-10-02, after the merge and `/mcp`):** `list_studies` listed all 8 studies, each loading; `start_check` on `ce_chain` (local, parallel 1) followed by `check_result` gave exit 0 and `report.ok` true in 50.2 s, against the live data root (job `ce_chain-20261002-151322-3608`).

## Campaign tools (2026-10-02)

Spec `docs/superpowers/specs/2026-10-02-campaign-tools-design.md`; plan
`docs/superpowers/plans/2026-10-02-campaign-tools.md`; code
`service/campaigns.py` (`CampaignService`), `service/jobs.py`
(`spawn_detached`, `lock_held`, shared with the check jobs).

- **`start_campaign(study, name_prefix, q, max_evals, picker, executor,
  parallel, context, stagger, confirm=False)`:**
  - **The dry run is the default.** It runs `graph.closed_loop <argv>
    --check-only`: every check a real launch makes, then
    `[closed_loop] OK: would launch …` and exit 0, or the usual
    `REFUSED:` lines and exit 2. It returns `{ok, problems, command,
    budget, output_tail, error}`.
  - **The budget** is the sum of the prodtools steps' `fixed.njobs`:
    `foilspfbpz_ax` gives 130 per point (15 + 15 + 100).
  - **Timeouts:** the dry run is capped at 600 s and kills its whole
    process group on timeout.
  - **What it writes:** the server writes nothing. closed_loop's `KitSet`
    writes `kit_trace.jsonl` to `GRAPH_DATA/<prefix>/` during any launch
    check (`core/contract.py:329`), so that folder exists after a dry run.
  - **`confirm=true` relaunches the same argv without the flag,** so
    closed_loop's own checks run again. It is refused at once when:
    - a live parent has the prefix (its `parent.lock`, or the MCP
      wrapper's `lock`);
    - `<prefix>/STOP` exists;
    - the prefix was ever launched: `<prefix>/launch.json` (claimed with
      `O_EXCL`, so of two concurrent confirms only one launches) or
      `<prefix>/campaign.json` exists;
    - the prefix already has child logs: a second parent on one prefix
      would double its grid submits.
  - **The dry run reports those refusals too** (final-review fix), so the
    check and the launch never disagree.
  - **One MCP launch per prefix:** a launch closed_loop refuses spends the
    prefix (`state: "refused"`, note "dry-run again and launch under a new
    prefix").
  - **The answer:** for up to 600 s it waits for `<prefix>/campaign.json`,
    which closed_loop writes once its launch checks pass (`launched`), or
    `rc` (`refused`, with the `REFUSED:` lines read from `parent.log`);
    otherwise it returns `starting`. The launch record is
    `<prefix>/launch.json` (command, the wrapper's pid) since 2026-10-05.
- **`stop_campaign(prefix)`** touches `<prefix>/STOP`: running children
  drain. It warns "no sign of a campaign" when there is no record
  (`campaign.json` or `launch.json`) and no child log; `children_running`
  counts held `run.lock`s.
- **`campaign_status(prefix)`** reads the point and campaign records
  (2026-10-05; see [contract-engine](/drivers/contract-engine.md), "Point
  and campaign records"):
  - **Parent:** alive while `parent.lock` (closed_loop) or `lock` (the MCP
    wrapper) is held; `exit_code` from `campaign.json`, else `rc`;
    `launched_by` mcp (`launch.json`, or an old record with `command`),
    shell (a record only) or None.
  - **Study:** the record's, else (a campaign from before the records) the
    one a child's `point.json` names.
  - **Children** are the `closed_loop_logs/<prefix>R<n>_00.log` files
    (`campaign_dir.is_child`, so `foo` never takes `foo2`). Each is
    `scored` (row on the board), `broken` (`state/broken.txt`), `running`
    (its `state/run.lock` is held), `starting` (the campaign is alive and
    the child has no outcome and has never taken its lock: graph.run is in
    its launch checks) or `ended without a row`; each carries `outcome`
    (the pool's reason from `outcomes.jsonl`), `x` and the board `values`.
  - **`rows` and `best`** come from the board by the same exact match.
  - **A study file that no longer loads** gives `board_error`; an
    unreadable `campaign.json` or a truncated `outcomes.jsonl` line gives
    `error`; the children are still listed.
  - **Liveness is a flock on the shared data root,** so a campaign on
    another node shows as running too. A campaign or point started by code
    from before 2026-10-05 holds no lock and reads as ended.
  - **A prefix must match `[A-Za-z0-9_]+`,** so `""` or `/dir` cannot
    point the reads at another directory (final-review fix).
  - **With no prefix,** it lists every `<prefix>/campaign.json` (every
    campaign since 2026-10-05 writes one). In the server that list comes
    back as
    `{"campaigns": [...]}`, because a union of return types is not
    structured output.
- **`leaderboard(study, name_prefix=None, top=20)`:** the rows, best first
  by the first objective's direction, each `{config, x, values}`.
  - The board is built from the service's own data root
    (`Leaderboard.for_study`), not `board_for`, which uses the process's
    data root. In the server they agree.
- **Known limits:**
  - confirm is not tied to a dry run: the gate is the operator's
    permission prompt, so never allowlist `start_campaign`.
- **The `_ax` studies need `--context alpha=…`.** Without it closed_loop
  refuses "needs --context for ['alpha']". The live `foilspfbpz_ax`
  board's 41 rows all carry `alpha=100000`.
- **Acceptance (2026-10-02),** through the stdio client in a sandbox data
  root, with nothing on the grid:
  - **`foilspfbpz_ax` grid dry run** (q=10, max_evals=40, alpha=100000):
    `ok`, with a budget of 130 per point and 5,200 in total.
  - **`ce_chain` dry run:** refused "has no knobs: … run graph.run".
  - **branin,** local, q=2, max_evals=4: launched, 4 children scored,
    `exit_code` 0, and `leaderboard` gave 4 rows.
- **Live from a Claude Code session (2026-10-02, after the merge and
  `/mcp`):**
  - `campaign_status bpzax01` showed 40 children scored, best
    `bpzax01R15_00` at sob 4.081, parent not alive (it was shell-launched
    and has ended);
  - `leaderboard foilspfbpz_ax top=5` gave 41 rows, best `c2bR11ax01` at
    sob 4.143;
  - a grid dry run (q=10, max_evals=40, alpha=100000) was refused by
    closed_loop's board check, which is correct: the live board holds
    measure_sha 1a91751589c1 and a launch now measures 28a09663f81f (the
    anakit fork moved). The next `_ax` campaign needs a new
    `leaderboard.file`. Budget: 130 jobs per point, 5,200 in total.
- **Tests:** `tests/test_campaigns.py` (17), `TestCheckOnly` in
  `tests/test_closed_loop.py` (2), `TestSpawn` in `tests/test_service.py`
  (1), and the stdio test sees nine tools. The suite is 858 OK
  (skipped=3).

## Dashboard (2026-10-04)
- **What:** `python -m service.dashboard` rebuilds
  `<data root>/autoresearch_dashboard/snapshot.json` every `--every` s
  (default 120) and serves that directory on `127.0.0.1:<port>` (default
  8765); `service/dashboard.html` draws each campaign as a flow graph
  (campaign → points → steps → result). Start line and tunnel: README
  "Dashboard". Spec `docs/superpowers/specs/2026-10-04-dashboard-design.md`.
- **Source of a step's progress:** the scheduler writes
  `<point>/state/<step>_status.json` on every kit poll (state, the kit's
  message, done/total, time, the chosen `poll_s`). Nothing else reads it;
  resume still keys on `_cluster.txt` / `_results.json`. A failed write
  (a full quota) is logged once per step and never fails the step: the
  dashboard then shows that step as stalled.
- **Step states** are `PointDir.step_state`'s (core/point_dir.py): the
  step `broken.txt` names is failed with its message, whatever its last
  poll said; the stall rule below is the dashboard's own. An unreadable board (a `LeaderboardError`, e.g. a bad row) is that
  campaign's `error`; its points still show (`campaign_status` now catches
  it as `board_error` too).
- **Stall rule:** a working step of a running point whose last poll is older
  than `max(3 * poll_s, 600 s)` turns amber. Kit-agnostic: prodtools grid
  polls up to 600 s, beamkit every 120 s, so a fixed 15 min would false-alarm.
- **Which campaigns:** live ones always, others while their child logs or
  `campaign.json` changed within `--days` (default 7). q and max_evals come
  from `campaign.json` (an old MCP record's own argv); a shell campaign
  from before 2026-10-05 has none.
- **Liveness** is the records' flocks (`parent.lock`, `run.lock`), as in
  `campaign_status`: no process table, so another data root's campaigns
  never show (the 2026-10-04 test-suite ghosts are gone).
- **Cost:** about 3 s per snapshot on the live data root (3059 child logs,
  three campaigns), ~160 kB JSON; no grid, no Kerberos.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (check_study), [surrogate](/drivers/surrogate.md)
- Source files: `service/checks.py`, `service/server.py`, `tests/test_service.py`, `.mcp.json`
- Spec: `docs/superpowers/specs/2026-10-02-autoresearch-mcp-design.md`; plan: `docs/superpowers/plans/2026-10-02-autoresearch-mcp.md`

## Open questions / TODO
- A real grid campaign launched over MCP (waits for the operator's word).
