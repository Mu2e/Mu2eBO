# Live campaign dashboard — design

Date: 2026-10-04. Branch `dashboard` from `generic-study-phase-c1` (0584c99).

## Goal

One page that answers "status?" without asking: every campaign in flight as
a live flow graph (campaign → points → steps → result), coloured by state,
with each step's progress in the kit's own words. Monitoring only.

Not in scope: results views (leaderboards, best-so-far curves, knob
scatters), any action (launch, stop), grid or Kerberos calls, an MCP tool to
start the dashboard, deploying to the mu2e-exp docroot (only `--no-serve`
is provided for it).

## Parts

1. **Step status file** (engine): `core/scheduler.py` records every poll.
2. **`service/dashboard.py`**: `build_snapshot()` (reads files, emits the
   graph with its layout) and `main()` (the loop, the lock, the server).
3. **`service/dashboard.html`**: draws the snapshot's graph as SVG. No
   library, no CDN.

## 1. Step status file

In `_run_one`, after each `kit.status()`, the scheduler writes
`<state_dir>/<step>_status.json` (atomically, `write_atomic`):

```json
{"state": "working", "message": "10 job(s) queued or running, 0 held, 10 file(s)",
 "progress": {"done": 10, "total": 20, "ok": 10}, "time": 1791041487.5,
 "poll_s": 120.0}
```

- `state`, `message`, `progress` are the kit's status as returned
  (`progress` may be null); `time` is the engine's clock; `poll_s` is the
  sleep the scheduler takes next (`min(max(poll_ms/1000, lo), hi)`), 0 on a
  terminal state.
- The last write of a step holds its terminal state.
- Nothing reads it but the dashboard: resume still keys on `_cluster.txt`
  and `_results.json`.

## 2. Snapshot

`build_snapshot(svc, now, days) -> dict`, where `svc` is a
`CampaignService` (its data root, process scan, study loading, boards).

**Campaigns shown:** the union of
- `svc.campaign_status()` (MCP campaigns with `campaign.json`, and live
  shell parents from this host's process table), and
- prefixes parsed from `closed_loop_logs/<prefix>R<n>_<m>.log` whose newest
  log is younger than `days` (default 7): finished shell campaigns.

For each, `svc.campaign_status(prefix)` gives parent liveness, study,
children and their states (scored / broken / running / ended without a
row), rows and best; `max_evals` and `q` come from `campaign.json`'s `args`
or the live parent's argv when present (else null).

**Per point** (child): `point.json`'s x; per step of the study, a step state:

| step state | evidence |
|---|---|
| done | `<step>_results.json` exists |
| failed | `<step>_status.json` state failed or cancelled |
| working | `<step>_status.json` state working, or `<step>_cluster.txt` without a status file (a pre-feature run) |
| waiting | none of the above |

plus, for a working step, the status file's message and progress, its
age in the step (`now -` the `_cluster.txt` mtime, the submit time) and a
**stall** flag: the point is running and
`now - time > max(3 * poll_s, 600)`. A pre-feature step (no status file)
never stalls.

**Snapshot shape:**

```
{"time", "host", "every_s", "errors": [...],
 "campaigns": [{"prefix", "study", "alive", "exit_code", "launched_by",
                "host", "stopping", "q", "max_evals", "rows", "best",
                "error", "graph": {"bands": [...], "edges": [...]}}]}
```

**Graph.** Columns (layers): 0 campaign, 1 point, 2..k steps by topological
depth over `files_from` (a step's layer = 2 + its longest path from a root
step), k+1 result. Each point is a *band*; steps that share a depth stack
as sub-rows inside the band, so a band's height is the widest depth.
Each band carries its nodes `{id, kind, layer, subrow, label, state,
detail}` (kind: point / step / result; detail = the hover text: knob
values, full kit message, last log line). Edges are node-id pairs:
campaign → point, point → each root step, upstream → downstream step
(`files_from`), each leaf step → result.

- **Result node:** the value (objective, `fmt`) and ★ on the campaign's
  best when scored; else the point state (running, broken, ended without a
  row).
- **Band order:** running points (by name), then scored by the objective's
  direction (best first), then broken and ended.
- **Folding:** scored bands carry `fold: "scored"`; the page shows them as
  one node "N scored, best V" until clicked. A campaign that is not alive is
  emitted with `collapsed: true` (one summary node: rows, best, exit code)
  and expands on click.
- **Errors:** a study that does not load or a board that cannot be read
  sets that campaign's `error` (shown in red) and still emits its points
  from the files; a failure outside any one campaign goes to the top
  `errors`. Nothing is dropped silently.

## 3. Process

```
python -m service.dashboard [--every 120] [--port 8765] [--days 7]
                            [--out DIR] [--no-serve] [--once]
```

- `--out` defaults to `<data root>/autoresearch_dashboard/`. At start the
  page is copied there; each cycle writes `snapshot.json.tmp` then renames
  it to `snapshot.json`.
- **One instance per `--out`:** `flock(LOCK_EX | LOCK_NB)` on `<out>/lock`,
  which also holds `pid host`; a second instance exits 1 naming the first.
- **Server:** `ThreadingHTTPServer` on `127.0.0.1:<port>`, serving `<out>`
  only, request logging off, in a daemon thread. A port in use exits 1 with
  the error (no other port is tried). `--no-serve` skips it.
- **Loop:** build, write, sleep `every`. A cycle that raises logs its
  traceback to stderr (`dashboard.log` when detached) and keeps the previous
  snapshot; the page's age dot then turns red. SIGTERM and Ctrl-C exit 0.
- `--once`: one cycle, no server, exit 0.
- **Start (README):**
  `source ./activate.sh && setsid nohup "$AUTORESEARCH_PYTHON" -u -m service.dashboard >> "$AUTORESEARCH_DATA_ROOT/autoresearch_dashboard/dashboard.log" 2>&1 &`
  on the host the campaigns run on (liveness is that host's process table);
  view with `ssh -L 8765:localhost:8765 <host>` and `http://localhost:8765`.
- Imports: standard library and what `service/campaigns.py` imports; never
  modes.

## 4. Page

`service/dashboard.html`, ~150 lines of HTML, CSS, JS. It fetches
`snapshot.json` (cache-busted) every 60 s and redraws.

- **Top bar:** snapshot age as a dot (green when age ≤ 2 × `every_s`,
  amber ≤ 3 ×, red beyond), the host, the build time, top-level errors.
- **Campaigns** stacked, live first: a header line (prefix, study, alive or
  ended with exit code, rows / max_evals, best, error in red), then the
  graph. The page stacks bands top to bottom (summing band heights; folded
  bands contribute one row) and places nodes at `layer` columns; it decides
  nothing else.
- **Colours:** grey waiting, blue working, amber stall, green done /
  scored, red failed / broken, ★ best. A working step shows a progress bar
  (`done / total`) and its age.
- **Hover:** SVG `<title>` with the node's `detail`. Click toggles a fold or
  a collapsed campaign (kept across redraws in memory).
- Light and dark from `prefers-color-scheme`.

## 5. Tests

`tests/test_dashboard.py`, plus scheduler tests in the existing scheduler
test file:

- **Scheduler:** each poll writes `<step>_status.json` with the kit's state,
  message, progress, time and the clamped `poll_s`; the last write is
  terminal; a resume from `_cluster.txt` still polls (the file is not read).
- **`build_snapshot`** on a fake data root (boards, child logs, state dirs,
  `campaign.json`), a fake process list and a fixed clock:
  - finds an MCP campaign, a live shell one, and a finished shell one from
    its logs within `days`; drops one older than `days`;
  - step states from the evidence table, incl. a pre-feature
    `_cluster.txt`-only step;
  - the stall flag: at `3 * poll_s` (≥ 600 s) on a running point, never on
    a dead point or a pre-feature step;
  - layers and sub-rows for a one-step study and a multi-step DAG (two root
    steps feeding a third); edges follow `files_from`;
  - band order, the `scored` fold, ★ on the best by direction, a
    non-alive campaign collapsed;
  - an unloadable study sets that campaign's `error` and the rest builds.
- **`main`:** `--once` writes `snapshot.json` and the page; a second
  instance on the same `--out` exits 1 naming the first; a busy port exits
  1; the server returns `snapshot.json` on 127.0.0.1.
- **Page:** no JS harness exists here; one manual check against a live
  snapshot is part of acceptance.

## 6. Acceptance

Start it on the campaign host during a live campaign; through the tunnel,
the graph matches `campaign_status` for that prefix (points, states,
rows, best), a working step shows the kit's message and progress, and the
age dot turns red within 3 cycles of killing the process.
