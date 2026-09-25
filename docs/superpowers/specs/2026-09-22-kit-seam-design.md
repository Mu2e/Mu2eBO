# Kit seam: surrokit and prodtools over MCP — design (spec 1 of 4)

Date: 2026-09-22. Status: draft for review.

## Context

Goal (operator, 2026-09-22): make autoresearch modular so it runs on MCP
servers ("kits": prodtools, beamkit, surrokit, anakit), make the LangGraph
graph reusable for other studies (Offline and G4beamline, both of which
prodtools supports), let other users install their own copy, and keep every
path to one person's area out of the code.

The alignment check against the Genesis/KE discussion (mu2e Slack with
Simon Corrodi and Ray Culbertson, the ANL thread with Nesar Ramachandra, the
HEP-KE repos) found no conflict and added requirements: clean interfaces per
part so any harness can drive them (Simon, 2026-08-06); one shared
trace-logging method across efforts (same); public-repo, pip/uv-installable
servers (Simon and Nesar, 2026-09-15); per-workflow identity on calls (Ray
and Simon, 2026-09-07); streamable-http transport for hostable servers
(Nesar). The operator deferred http: **this work is stdio only**.

The effort is split into four specs, each with its own plan:

1. **Kit seam, surrokit, prodtools** — this document. Autoresearch-owned.
2. **Analysis through anakit** — harvest moves to anakit
   (github.com/michaelmackenzie/analysis-mcp-server); needs its owner.
   Our sob and flash definitions must be ported as anakit analyses, not
   swapped for `approx_ce_sensitivity`, whose defaults differ.
3. **Study spec and generic graph** — `studies/<name>/study.toml`, a graph
   generated from the study, the first G4beamline study through beamkit.
   Offline geometry studies need no per-study Python: `core/geom_template.py`
   already renders knobs into a geometry overlay from formulas held as data
   (foilspf included); G4beamline knobs go straight to beamkit `params`. Decides where `preflight` and
   `scan_logs` live.
4. **Orchestrator MCP server** — autoresearch publishes `start_campaign`,
   `campaign_status`, `leaderboard`, `suggest`, `predict` using the HEP-KE
   starter-repo wrapper; `surrogate/` is deleted then.

Honest accounting: moving prodtools calls from subprocess to MCP does not
shrink the code (a client replaces a `subprocess.run`). Spec 1 buys one
uniform, tested, portable seam. The line savings come in specs 2 and 3.

## Scope

In:
- `core/kits.py` (the kit client) and `kits.toml` (kit registry).
- surrokit as a stateless stdio MCP server; every pick path calls it.
- prodtools-write `submit_once` for grid submit; prodtools read
  `run_status` for waiting and for outputs; a new prodtools local-run tool.
- Trace log and workflow identity on every kit call.
- Removal of the personal paths this spec can remove, and a lint that keeps
  them out.

Out: anakit, the study spec, the orchestrator server, http transport,
beamkit (already an MCP kit; wired in spec 3), where the shared build
artifacts live (open decision, below).

## Verified prodtools facts (source at `1dc0499`, 2026-09-22)

- Read server exposes `run_status(name, mine, user)`
  (`mcp/src/prodtools_mcp/tools/runs.py:53`). It reads the `--once`
  receipt, then returns `state` in {building, submitting, failed, running,
  unknown, short, done}, `jobs` {expected, ok, failed, unknown, exit codes
  of failed}, and `outputs` {proc index: output paths} for the ok procs.
  Lists are capped at `INDEX_CAP = 200`. `unknown` is never success — the
  same rule as our `state/<stage>_wait.json` contract.
- Write server `submit_once(json, desc, dsconf, run_as="self", ...)` runs
  `json2jobdef --once`: it builds the cnf itself, submits every job in one
  `jobsub_submit` (at most 10000) to outstage, nothing in SAM, no ledger.
  The run name is `cnf.<owner>.<desc>.<dsconf>.0`, and a reused name is
  refused (`RunExists`). That refusal is our double-submit guard.
- Receipts live at `/exp/mu2e/data/users/<login>/prodtools/runs/`
  (`utils/run_receipt.py:35`), per user, not configurable.
- **Blocker P1:** the write tools refuse our entries. Every autoresearch
  entry is code-mode (`"code": <per-config tarball>`, no `simjob_setup`;
  `core/prodtools_exec.py:render_entry`). `_select_push_params`
  (`prodtools_mcp_write/tools.py:47`) raises for any non-g4bl entry without
  `simjob_setup`, and `run_cli` needs a Musing to put `mu2e` on PATH for
  `json2jobdef`. json2jobdef itself accepts code-mode ("exactly one of
  simjob_setup and code", `utils/json2jobdef.py:412`).
- **Blocker P2:** no local-run tool. `runlocal` is CLI-only.
- No write tool exposes grid job logs; `run_status` gives outstage paths
  and failed exit codes only.
- Job counts fit the cap: foilspf stages run 15/15/100 jobs; the default
  maximum is 200, exactly `INDEX_CAP`.

## Design

### 1. Kit client — `core/kits.py`

- `KitClient(name)`: synchronous handle on one stdio MCP server. Lifted from
  beamkit's `mcpclient.py` (private event loop on a daemon thread, one
  session for the process's life, stderr tail on a failed start). Uses the
  `mcp` 2.0 client in ana 2.8.0 (`ClientSession.call_tool` takes `meta=`
  and `read_timeout_seconds=`). `langchain_mcp_adapters` in ana 2.8.0 is
  broken against mcp 2.0 (`ImportError: RequestContext`) and is not used.
- `call(tool, timeout_s, **args) -> dict`. Every call names its timeout.
  Every failure — start, protocol, tool error, timeout — raises
  `KitError(kit, tool, message)`. Nodes do not catch it; the graph routes
  to END with the reason, as today.
- **No automatic retries, ever.** A dead server is respawned before the
  NEXT call, never to repeat the failed one. A timed-out submit may already
  be on the grid; recovery is by `run_status(name)` (see §3).
- `kits_for(campaign)` returns clients keyed by kit name, created lazily,
  closed at process exit.

### 2. Registry — `kits.toml` (repo root)

```toml
[surrokit]
command = ["uvx", "--from", "git+https://github.com/oksuzian/surrokit@v0.2.0", "surrokit-mcp"]   # the pin: a literal tag
env     = ["UV_CACHE_DIR"]

[prodtools]            # read-only server
command = ["${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_mcp.sh"]
env     = ["KRB5CCNAME", "BEARER_TOKEN_FILE"]

[prodtools-write]
command = ["${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_write_mcp.sh"]
env     = ["KRB5CCNAME", "BEARER_TOKEN_FILE"]
set     = { SPACK_USER_CACHE_PATH = "${DATA_ROOT}/spack_user_cache" }
```

- `${VAR}` resolves from the environment, except `${DATA_ROOT}`, which
  resolves from `core/paths.py`. An unresolved variable fails at first use
  of that kit, naming kit and variable. No defaults.
- `env` lists the variables passed through; the MCP SDK passes only a short
  allowlist otherwise, which silently drops the Kerberos cache.
- `set` pins variables for the child. `SPACK_USER_CACHE_PATH` off NFS is the
  mitigation from wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md,
  because every prodtools launch runs `muse setup ops`.
- The literal tag in the surrokit command is the pin, bumped by editing this
  file after re-running the parity gate. It replaces `SURROKIT_PIN_SHA` and the
  sibling-checkout rule in `core/paths.py`. surrokit is public with no tags
  yet; the first tag is part of this work.
- `UV_CACHE_DIR` must be off nashome (torch wheels are GB-sized). The
  launch checks in `core/launch_checks.py` refuse a campaign when it is unset
  or under `$HOME`.

### 3. prodtools through the seam

Grid stage, per (config, stage), replacing `submit_stage_prodtools`,
`core/prodtools_submit_driver.py`, and the `jobwait` path:

1. Render the entry exactly as today (`render_entry`, code tarball, staged
   `dir:` inputs), write `state/<stage>_entry.json`.
2. Idempotency: call `run_status(name)` first. `not_found` means submit;
   any existing receipt means adopt it and skip the submit. This replaces
   the `cluster.txt` re-attach.
3. `prodtools-write.submit_once(json=<entry path>, desc, dsconf,
   run_as="self")`, under the existing `_submit_lock` and 60-90 s stagger
   (wiki/incidents/concurrent-token-contention.md). Write the run name to
   `state/<stage>_run.txt`.
4. Wait: poll `run_status(name)` every 120 s until `state` is `done`,
   `short`, `failed` or `unknown`-after-completion. The closed-loop barrier
   timeout stays the only cap.
5. Write `state/<stage>_wait.json` from `jobs`, and the stage's output list
   from `outputs`. `unknown` never counts as ok; denominators are ok procs
   only (wiki/incidents/harvest-denominator-bug.md). A truncated `outputs`
   (more than 200 ok procs) is a hard error until P3 lands.

Local stage: same shape through the new local-run tool (P2).

What stays in autoresearch: entry rendering, the per-config code tarball,
input farming between stages, harvest (until spec 2), `preflight` and
`scan_logs` (spec 3 decides; `scan_logs` reads the `outstage` path that
`run_status` returns).

Deleted in this spec: `core/prodtools_submit_driver.py`, the submit, cnf
build, `jobwait` and `runlocal` shells in `core/prodtools_exec.py`,
`poll`/`list-outputs` internals in `core/pipeline.py` that the receipt
replaces, and the per-user ledger path under `DATA_ROOT/prodtools_ledger/`.
Exact line counts go in the plan.

### 4. surrokit through the seam

- New in surrokit (upstream, the operator's public repo): console script
  `surrokit-mcp`, a stateless stdio server with
  `ask(problem, X, Y, noise, bounds, int_dims, pending, picker, seed,
  constraint)` and `predict(problem, X, Y, noise, bounds, x)`. The client
  sends the history; the server keeps a fit cache keyed by a digest of the
  arguments. Ships a `uv.lock`.
- `core/botorch_predict.py` keeps `build_problem`, `load_history_tensor`,
  the `-log10` transform and the `42 ^ round_idx` seed; `compute_explore_picks`
  calls `surrokit.ask` through the kit client instead of importing surrokit.
- `surrogate/adapter.py` and `surrogate/mcp_server.py` are rewired to the
  same client, so agent-facing `suggest` stays the production pick path.
  They are deleted in spec 4, not here.

### 5. Trace log and workflow identity

- Every call carries MCP request `meta = {"workflow":
  "<campaign>/<round>/<config>/<stage>"}`. Servers may ignore it today.
- Every call appends one JSON line to
  `GRAPH_DATA/<campaign>/kit_trace.jsonl`: time, workflow, kit, tool,
  SHA-256 of the canonical arguments, duration, `ok` or the error text.
  This file format is what we offer the other efforts as the shared trace
  method.

### 6. Portability

- Lint: `tests/test_no_hardcoded_paths.py` extends to `kits.toml` and
  `.mcp.json`, and bans `/exp/mu2e/{app,data}/users/<name>` with a real
  login anywhere outside the pragma'd test fixtures.
- Removed: the `setup.sh` site-venv default (`--venv` then requires a
  path) and the README's backing example with a personal path (it becomes
  `<operator>`).
- `.mcp.json` registers the surrogate server through `${AUTORESEARCH_PYTHON}`
  instead of the literal ana 2.8.0 path. Claude Code expands that variable
  at launch, so it must be started from a shell that sourced `activate.sh`;
  an unset variable fails loudly at server start.
- **Open decision, not this spec's to make:** `core/paths.py`
  `_EXAMPLE_BACKING` names where the patched Offline build and grid tarballs
  live. Other users depend on that directory until the artifacts move to a
  shared home (group area or cvmfs). The operator picks the home; the move
  is its own task.

## Upstream changes needed

All opened only on the operator's go-ahead.

- **prodtools (Mu2e org)**
  - P1: `submit_once`, and the new local-run tool, accept code-mode
    entries. The env for `json2jobdef` comes from the code tarball's own
    setup, not a Musing.
  - P2: a local-run tool with a receipt, `run_local(json, desc, dsconf,
    nproc)` returning a name, readable by `run_status`, so local and grid
    share the wait path.
  - P3 (only if a stage exceeds 200 jobs): paging for `run_status.outputs`.
- **surrokit (operator's repo)**: stateless server, console script,
  `uv.lock`, first tag.

## Testing

- `tests/fake_kit.py`: a generic stdio MCP server driven by a JSON script
  (tool, expected arguments, reply or error). Unit tests cover the client:
  timeout, server death then respawn-without-retry, `KitError` shape, trace
  line, `meta` forwarding, unresolved `${VAR}`.
- `tests/test_kit_contracts.py`: starts each real kit when its install is
  present and checks every argument the orchestrator sends against the
  live tool schema; skips otherwise. Pattern from beamkit's
  `tests/test_bridge_contract.py`.
- Pick parity: the surrokit server run under ana 2.8.0 from a checkout
  must give bit-identical picks to today's in-process call on the fixture
  board (proves the protocol adds nothing). The uvx-locked env is then
  measured against it and the difference recorded, not asserted, since
  torch builds differ (wiki/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md).
- Suite green under `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`.
- Acceptance: one foilspf grid round at q=1 end to end through the seam,
  row landed, trace log present; one local run through P2.

## Order

1. Kit client, registry, fake kit, tests. No behavior change.
2. surrokit server upstream and tag; picks through the seam; parity gate.
3. prodtools P1 and P2 upstream; grid and local stages through the seam;
   deletions; q=1 grid acceptance.
4. Portability lint and removals; wiki pages updated
   (drivers/pipeline, drivers/surrogate, drivers/closed-loop-runner, log).

## Risks

- P1 is the critical path and is not in our control. Stage 3 waits on it;
  stages 1, 2 and 4 do not.
- q children each spawn their own prodtools servers. The stagger and the
  off-NFS spack cache mitigate the lock and token races; a parent-owned
  client shared by children is the fallback if they recur.
- A kit start takes seconds (`muse setup ops`); sessions live for the
  process, so this is paid once per child, not per call.
