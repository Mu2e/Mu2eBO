# Live Campaign Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A page that shows every campaign in flight as a live flow graph (campaign → points → steps → result), rebuilt from files every 2 minutes.

**Architecture:** The scheduler records each kit poll in `<step>_status.json`. `service/dashboard.py` reads campaign files through `CampaignService`, emits `snapshot.json` with the graph already laid out, and serves its output dir on localhost. `service/dashboard.html` only draws it.

**Tech Stack:** Python 3.12 standard library (ana 2.8.0), `unittest`; plain HTML/CSS/JS + inline SVG.

**Spec:** `docs/superpowers/specs/2026-10-04-dashboard-design.md`

## Global Constraints

- Monitoring only: no actions, no grid or Kerberos calls, no new dependencies, no CDN.
- `service/dashboard.py` imports only the standard library and what `service/campaigns.py` imports; never modes.
- Stall: point running and `now - status.time > max(3 * poll_s, 600)`; never on a dead point or a step without a status file.
- Age dot: green ≤ 2 × `every_s`, amber ≤ 3 ×, red beyond.
- Defaults: `--every 120`, `--port 8765`, `--days 7`, `--out <data root>/autoresearch_dashboard/`; server binds `127.0.0.1` only.
- No silent fallbacks: per-campaign problems go to that campaign's `error`, others to top-level `errors`; a busy port or a held lock exits 1.
- Test command (worktree root): `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`

## Review Focus

- A child log whose name is not `<prefix>R<n>_<m>` (e.g. a single `graph.run` config) sits in `closed_loop_logs/`: discovery must skip it, not invent a campaign. (Task 2 test.)
- A campaign whose study file is gone or no longer loads: its points still show, from files, with `error` set. (Task 2 test.)
- A `_status.json` that is half-written or not JSON (copied by hand, disk full): that step reads as working with `error` in its detail, and the snapshot still builds. (Task 2 test.)
- A study with steps at the same depth (two root steps): their nodes get distinct sub-rows and the band's height is 2. (Task 3 test.)
- The dashboard started twice, or on a port already in use: exit 1 naming the cause, never a second writer. (Task 4 test.)

---

### Task 1: The scheduler records every poll

**Files:**
- Modify: `core/scheduler.py` (`_run_one`, the poll loop at ~253-262)
- Test: `tests/test_scheduler.py` (new `TestStatusFile(_Run)`)

**Interfaces:**
- Produces: `<state_dir>/<step>_status.json` = `{"state": str, "message": str, "progress": {"done","total","ok"} | null, "time": float (time.time()), "poll_s": float}`; `poll_s` = the clamped sleep about to be taken, `0.0` on a terminal state.

- [ ] **Step 1: Write the failing tests** in `TestStatusFile`:
  - `test_each_poll_is_recorded`: `FakeKit({"a": ["working", "completed"]}, poll_s=(0.5, 2.0), poll_ms=1500)`; a `sleep` callback reads `a_status.json` and appends it; assert the read inside sleep has `state == "working"`, `message == "a working"`, `progress is None`, `poll_s == 1.5`, and `before <= time <= after` (wall clock around the run).
  - `test_the_last_write_is_terminal`: after the run, `a_status.json` has `state == "completed"` and `poll_s == 0.0`; for script `["failed"]` it has `state == "failed"`.
  - `test_a_resume_does_not_read_it`: write `a_cluster.txt` = `"c.a\n"` and a garbage `a_status.json` (`"not json"`); run; the step completes and `kit.submits == []`.
- [ ] **Step 2: Run** `... -m unittest tests.test_scheduler -v`. Expected: the three new tests FAIL (no file / file not rewritten); the rest pass.
- [ ] **Step 3: Implement**: in the poll loop, compute the clamped sleep first, then `write_atomic(state_dir / f"{step.step}_status.json", json.dumps({...}))` before acting on the state (terminal states write `poll_s: 0.0`).
- [ ] **Step 4: Run** the same command. Expected: all pass.
- [ ] **Step 5: Commit** `scheduler: record each status poll in <step>_status.json`.

### Task 2: Snapshot data — campaigns, points, step states

**Files:**
- Create: `service/dashboard.py`
- Create: `tests/test_dashboard.py` (class `_Dash` fixture + `TestData`)

**Interfaces:**
- Consumes: Task 1's status file; `CampaignService(env)` (`campaign_status()`, `campaign_status(prefix)`, `_load_study`, `_board`, `_processes`, `grid_data`, `logs_dir`, `camp_dir`), `service.campaigns._flag`.
- Produces: `campaign_data(svc, prefix, now) -> dict` with keys `prefix, study, alive, exit_code, launched_by, host, stopping, q, max_evals, rows, best, best_label, error, steps, points`; `steps` = `[{"step", "kit", "files_from": [..]}]` from the study (empty when it does not load); `points` = `[{"name", "state", "x": {knob: value} | None, "last_line", "steps": {step: {"state", "message", "progress", "age_s", "stall", "error"}}}]`. `prefixes(svc, now, days) -> list[str]` (sorted). Point states: `scored | broken | running | ended` (from `campaign_status`'s `"ended without a row"`). Step states: `waiting | working | done | failed` (spec table). `best_label` = the objective's `fmt` applied to the best value, or `None`.

- [ ] **Step 1: Write the fixture `_Dash`**: temp data root; studies dir holding `toy_doc("toystudy")` and a 3-step variant `toy_doc("dagstudy")` whose `evaluate` is steps `a`, `b` (no `files_from`) and `c` (`files_from: ["a","b"]`, objectives' metrics `c.branin` / `c.currin`); `svc = CampaignService(env=engine_env(data, studies))`; `svc._processes = lambda: self.procs` (a list the test sets); helpers `child(name, study, x, last_line)` writing the child log and `state/point.json`, `step_file(name, step, kind, payload)` writing `_cluster.txt` / `_status.json` / `_results.json`, `row(study, name, x, y)` appending through `svc._board(study).append(Point(...), {}, META)` with `META` as in `tests/test_boards.py`, `mcp(prefix, study, args)` writing `camp_dir/campaign.json`. A fixed `now`.
- [ ] **Step 2: Write the failing tests** in `TestData`:
  - `test_prefixes`: logs `aaR00_00` (now), `bbR00_00` (8 days old, via `os.utime`), `single_config` (no `R<n>_<m>`), plus `mcp("cc", ...)` with no logs → `prefixes(svc, now, 7) == ["aa", "cc"]`; a live shell parent in `self.procs` (`["python", "-m", "graph.closed_loop", "--study", "toystudy", "--name-prefix", "dd", "--q", "2", "--max-evals", "6"]`) adds `"dd"`.
  - `test_point_and_step_states`: one campaign on `dagstudy`: point 0 with `a` results, `b` status working (message `"b working"`, progress `{done 3, total 10, ok 3}`), `c` nothing; assert step states `done/working/waiting`, `b`'s message and progress; point 1 with only `a_cluster.txt` → `a` is `working` with `stall False`; point 2 with a `b_status.json` state `failed` → `failed`.
  - `test_stall`: point running (its config in `self.procs` as a `graph.run --config` argv), status `time = now - 601`, `poll_s 120` → `stall True`; `time = now - 599` → `False`; `poll_s 300`, `time = now - 899` → `False`, `now - 901` → `True`; same old status on a point not running → `False`.
  - `test_age_in_step`: `_cluster.txt` mtime `now - 3600` → `age_s == 3600`.
  - `test_budget_and_best`: `mcp("mm", "toystudy", [... "--q","3","--max-evals","9"])` → `q == 3`, `max_evals == 9`; two rows (`branin` 2.0 and 1.0, direction `min`) → `best["config"]` is the 1.0 row and `best_label == "1.000000"`; a shell parent gives q/max_evals from its argv.
  - `test_a_study_that_does_not_load`: child `point.json` names study `gone` (no file) → `error` mentions `gone`, `steps == []`, the point is still listed with its state.
  - `test_a_bad_status_file`: `b_status.json` = `"{"` → step `working`, its `error` names the file; other points unaffected.
- [ ] **Step 3: Run** `... -m unittest tests.test_dashboard -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `prefixes` (union of `campaign_status()` prefixes and `re.fullmatch(r"(.+)R\d+_\d+", stem)` over `logs_dir/*.log` whose newest mtime is within `days`) and `campaign_data` (one `campaign_status(prefix)` call; study via `_load_study` inside `try/except ValueError` → `error`; x from `point.json` zipped with the knob names; step evidence per the spec table; the module docstring names the spec).
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit** `dashboard: campaign and point data from the files`.

### Task 3: The graph and the snapshot

**Files:**
- Modify: `service/dashboard.py`
- Test: `tests/test_dashboard.py` (`TestGraph`)

**Interfaces:**
- Consumes: Task 2's `campaign_data`, `prefixes`.
- Produces: `layout(camp: dict) -> dict` = `{"columns": int, "bands": [{"point", "fold": "scored" | None, "height": int, "nodes": [{"id", "kind": "point"|"step"|"result", "layer", "subrow", "label", "state", "detail", "progress"?, "age_s"?, "best"?}]}], "edges": [[from_id, to_id]]}`; ids `"<point>"`, `"<point>/<step>"`, `"<point>/result"`, and `"campaign"` for the root. `build_snapshot(svc, now, days, every_s) -> dict` = `{"time", "host", "every_s", "errors", "campaigns": [campaign_data + {"collapsed": not alive, "graph": layout(...)}]}`, live campaigns first, then by prefix. Node states: point/result take the point state; a step takes its step state, or `"stall"` when its `stall` is true.

- [ ] **Step 1: Write the failing tests** in `TestGraph` (on `campaign_data` dicts built by hand, no files):
  - `test_one_step_layers`: one-step study → `columns == 4`; point layer 1, step layer 2, result layer 3; edges `campaign→p`, `p→p/toy`, `p/toy→p/result`.
  - `test_dag_layers_and_subrows`: steps `a`, `b` → `c` → `a` and `b` layer 2 with subrows 0 and 1, `c` layer 3, result layer 4, band `height == 2`; edges `p/a→p/c`, `p/b→p/c`, `p→p/a`, `p→p/b`, `p/c→p/result`.
  - `test_band_order_and_fold`: points running `r2`, `r1`, scored `s1` (1.0) and `s2` (0.5) with direction `min`, broken `b1`, ended `e1` → band order `r1, r2, s2, s1, b1, e1`; scored bands have `fold == "scored"`, others `None`; result node of `s2` has `best: True` and label `"0.500000"`.
  - `test_stall_state`: a working step with `stall True` → node state `"stall"`.
  - `test_build_snapshot`: on the Task 2 fixture with one live (process listed) and one ended campaign → live first, ended has `collapsed True`; `every_s` and `host` set; an exception raised by `campaign_data` for one prefix (patched) lands in `errors` and the other campaign is present.
- [ ] **Step 2: Run** `... -m unittest tests.test_dashboard -v`. Expected: `TestGraph` FAILS (no `layout`).
- [ ] **Step 3: Implement** `layout` (step layer = 2 + longest path from a root over `files_from`; subrow = order of the study's step list within a layer; detail strings: point = `knob=value` lines + `last_line`, step = `kit: message` + error, result = value or state) and `build_snapshot`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `dashboard: lay out the flow graph and build the snapshot`.

### Task 4: The process — CLI, lock, loop, server

**Files:**
- Modify: `service/dashboard.py` (`main(argv=None) -> int`, `if __name__ == "__main__": sys.exit(main())`)
- Modify: `README.md` (a "Dashboard" paragraph near the `surrogate/` MCP paragraph, ~line 123: the start line and the tunnel line from the spec)
- Test: `tests/test_dashboard.py` (`TestMain`, subprocess runs with `engine_env`)

**Interfaces:**
- Consumes: Task 3's `build_snapshot`.
- Produces: the CLI of the spec; files in `--out`: `index.html` (copy of `service/dashboard.html`), `snapshot.json`, `lock` (content `"<pid> <host>\n"`).

- [ ] **Step 1: Write the failing tests** in `TestMain` (this task creates a placeholder `service/dashboard.html`, `<!doctype html><title>Campaigns</title>`, which Task 5 replaces):
  - `test_once`: `python -m service.dashboard --once --out D` → rc 0; `D/snapshot.json` parses with key `campaigns`; `D/index.html` exists; no `D/snapshot.json.tmp`.
  - `test_a_second_instance_exits`: start `--no-serve --every 60 --out D` (Popen), wait for `D/snapshot.json`; a second `--once --out D` → rc 1 and stderr names the first pid; kill the first.
  - `test_a_busy_port_exits`: bind a socket on `127.0.0.1:0`, pass its port → rc 1, stderr contains `port`.
  - `test_serves_the_snapshot`: start with a free port (bind-and-release `127.0.0.1:0`), poll `http://127.0.0.1:<port>/snapshot.json` (urllib, ≤ 30 s) → 200 and JSON with `campaigns`; SIGTERM → rc 0.
- [ ] **Step 2: Run** `... -m unittest tests.test_dashboard -v`. Expected: `TestMain` FAILS.
- [ ] **Step 3: Implement** `main`: argparse with the spec's flags; out dir default from `CampaignService(...).data_root / "autoresearch_dashboard"`; lock = `fcntl.flock(LOCK_EX | LOCK_NB)` held for the process's life, then write `pid host`; copy the page; server = `ThreadingHTTPServer(("127.0.0.1", port), partial(SimpleHTTPRequestHandler, directory=out))` with `log_message` silenced, `serve_forever` in a daemon thread; loop: `build_snapshot` → write `.tmp` → `os.replace`; a raising cycle prints its traceback to stderr and keeps the old snapshot; SIGTERM handler raises `SystemExit(0)`.
- [ ] **Step 4: Run** the same command, then the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `dashboard: the snapshot loop, its lock and the localhost server`.

### Task 5: The page, acceptance, wiki

**Files:**
- Replace: `service/dashboard.html`
- Modify: `wiki/drivers/service.md` (a "Dashboard" key fact), `wiki/log.md` (today's bullet), `wiki/index.md` (the service one-liner)

**Interfaces:**
- Consumes: the snapshot shape of Task 3.

- [ ] **Step 1: Write the page** (~150 lines): fetch `snapshot.json?t=<now>` on load and every 60 s; top bar (age dot per the Global Constraints, host, build time, `errors` in red); per campaign a header line (prefix, study, alive or `ended rc=<exit_code>`, `rows / max_evals`, `best_label`, `error` in red) and an SVG: bands stacked top to bottom (a folded `scored` group drawn as one node `"<N> scored, best <best_label>"`; a `collapsed` campaign as one summary node), node x = `layer` column, y = band offset + `subrow`, edges as lines between node boxes; colours: waiting grey, working/running blue, stall amber, done/scored green, failed/broken/ended red, ★ on `best`; a `progress` bar `done/total` and `age_s` (h:mm) inside working step nodes; `<title>` = `detail`; clicks toggle folds and collapsed campaigns, remembered in a JS `Set` across redraws; `prefers-color-scheme` light/dark tokens on `:root`.
- [ ] **Step 2: Check it locally**: `python -m service.dashboard --once --out <scratch>/dash` against the live data root, then serve it (`--no-serve` off, a free port) and open it through the tunnel; compare with `campaign_status` for a live prefix (points, states, rows, best); a working step shows the kit's message and progress.
- [ ] **Step 3: Acceptance on the campaign host**: start detached with the README line; open through `ssh -L`; kill the process and see the age dot turn red within 3 cycles; restart it.
- [ ] **Step 4: Wiki**: the dashboard fact in `wiki/drivers/service.md` (start line, files, stall rule, host caveat), bump its `timestamp`, the index one-liner, a log bullet under `## 2026-10-04`.
- [ ] **Step 5: Run the full suite. Expected: OK. Commit** `dashboard: the flow-graph page; wiki`.
