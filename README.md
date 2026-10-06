# autoresearch — closed-loop Bayesian optimization of Mu2e geometry

A botorch GP proposes candidate Mu2e geometries; each is evaluated end to end
by the contract engine — geometry render, a local G4 feasibility pre-check,
grid (or local) Geant4 stages, and physics-metric extraction — and the result
lands as a row on a per-study leaderboard. The GP refits against the board
and the loop continues.

Each optimization line is a **study**: knobs, geometry rendering, evaluate
steps and objectives in one schema-2 JSON file under `mode_specs/`. The
engine drives a study's steps through **kits** — MCP servers (or in-process
adapters) that speak a common `submit`/`status`/`results` contract — so a
study is portable across grid backends without touching the runner.

New here? `QUICKSTART.md` has the whole install and a first campaign on one page.

## Setup

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
source activate.sh                                    # every new shell
./setup.sh --backing /exp/mu2e/app/users/oksuzian     # personal-path-ok: borrow a built Offline
export AUTORESEARCH_PRODTOOLS=<prodtools checkout>    # unless ../muse_050125/prodtools exists
export AUTORESEARCH_ANAKIT=<anakit fork checkout>      # unless ../analysis-mcp-server exists
kinit
```

- **`activate.sh`** exports `$AUTORESEARCH_PYTHON` — the published Mu2e env
  `ana 2.8.0` on `/cvmfs`. Nothing to build. `AUTORESEARCH_VENV=/path/to/venv`
  overrides it with a writable dev stack. It also exports
  `AUTORESEARCH_ANAKIT` and `AUTORESEARCH_PRODTOOLS` from sibling checkouts
  of this repo (`../analysis-mcp-server`, `../muse_050125/prodtools`) when
  they are unset and those directories exist; otherwise export them yourself.
- **`--backing`** borrows another operator's patched Offline build and grid
  tarballs; a fresh clone has none, and every run refuses until you link one.
  The artifacts are world-readable, so this is all you need — you build
  nothing. `./setup.sh --status` always prints whose build you are on.
- **`AUTORESEARCH_PRODTOOLS`** is required for any study whose kits include
  `prodtools`/`offline_preflight` (grid *and* local runs): `kits.toml` starts
  two prodtools MCP servers from it,
  `${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_write_mcp.sh` (submits, via
  `submit_once` on the grid or `run_local` here) and `start_mcp.sh` (reads
  back status via `run_status`) — jobs are built and executed by
  [prodtools](https://github.com/Mu2e/prodtools), not by this repo. Point it
  at a checkout whose write server has a `submit_once`/`run_local` tool and
  whose read server has `run_status` (`core/adapters/prodtools.py`).
- **`AUTORESEARCH_ANAKIT`** is required for the `<name>_ax` studies, whose
  `sob`/`flash` steps run on the `anakit` kit — a fork of M. MacKenzie's
  analysis MCP server. See `kits.toml`.
- **`kits.toml`** is the registry of native contract kits (`command`, `env`,
  timeouts, poll cadence). Grid-backed kits (`prodtools`, `offline_preflight`,
  `anakit`) are declared in `core/kit_registry.py` and run as in-process
  Adapters instead of a `kits.toml` entry; a native kit needs only a
  `kits.toml` table, no Python.
- **Kerberos**: even local jobs stream resampler inputs from `/pnfs` over
  xrootd, so a ticket is not optional; a grid launch refuses up front unless
  at least 4 h remain (`core/contract.py:check_kerberos`).

## Studies

One file per study, `mode_specs/<name>.json`; every key is required and an
unknown key is a load error. The seven production lines are their MDC2025ax
engine twins: `foilsflash_ax`, `foilspf_ax`, `foilspf2k_ax`, `foilspfbp_ax`,
`foilspfbpx_ax`, `foilspfbpz_ax`, `foilspfbw_ax`.

`mode_specs/archive/` is unloaded history: the four schema-1 fixed A/B specs
(`ipa625`, `ipafix`, `ipaovr`, `nominal`) plus, since Phase C3, the seven
original (Run1Bap) foilspf studies that ran on the now-deleted pipeline. Their
v1 leaderboards stay in `leaderboards/` as plain files; nothing loads them
(a study may declare only layout `"v2"` since 2026-09-29).
See `mode_specs/README.md` for the field reference and how to add a study.

## Run one point

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study foilspfbpz_ax \
    --config <name> --campaign <name> --x=<v1,...,v10> \
    --context alpha=100000.0 --executor grid|local [--parallel N]
```

`--x` is comma-separated, in the study's knob order; a zero-knob study (e.g.
`prodtools_smoke`) omits it. Exit 0 means the point ran — either a
leaderboard row landed, or `state/broken.txt` says why not; exit 2 means it
was refused before anything ran (unknown study, `--x` out of bounds, a kit
that won't start, …). `--parallel N` (1..16) only applies with
`--executor local`.

## Run a campaign

`$GRAPH_DATA` below is `$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data`.

```bash
PYTHONPATH= nohup "$AUTORESEARCH_PYTHON" -m graph.closed_loop --study foilspfbpz_ax \
    --q 20 --max-evals 40 --picker budget_sob --name-prefix foilspfbpz08 \
    --context alpha=100000.0 --executor grid \
    > "$GRAPH_DATA/foilspfbpz08_parent.log" 2>&1 &
```

Keeps `--q` children (each one `graph.run`) in flight, launching one
replacement per exit, refitting the GP against the leaderboard as it stands.
`--picker` is one of `qnehvi`, `qlnei`, `budget_sob`, `hybrid`. Pick an unused
`--name-prefix`. To stop launching without killing what's running, touch
`$GRAPH_DATA/<name-prefix>/STOP`; the pool drains the in-flight set and exits.

## Where things land

- `<GRID_DATA_ROOT>/<config>/state/` — the point record (`core/point_dir.py`):
  `point.json`, `<step>_cluster.txt`, `<step>_status.json`,
  `<step>_results.json`, `broken.txt` (written at the first failure), and
  `run.lock`, held by the `graph.run` running the point
  (`flock -n <state>/run.lock true` fails while it runs).
- `$GRAPH_DATA/<name-prefix>/` — the campaign record (`core/campaign_dir.py`):
  `campaign.json` (study, q, max-evals, host, pid; exit code at the end),
  `outcomes.jsonl` (one line per finished point), `parent.lock` (held
  while the campaign runs) and `STOP`.
- The v2 leaderboards, under `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/`.
  The committed `leaderboards/` is a read-only archive, read as priors and
  never written.
- The per-child campaign logs, `$GRAPH_DATA/closed_loop_logs/<config>.log`.

## Dashboard

A live flow graph of every campaign (campaign, points, steps, result),
rebuilt from the campaign files every 2 minutes. Start it on the host the
campaigns run on (liveness is that host's process table):

```bash
source ./activate.sh && D="${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER}/autoresearch_dashboard" &&
mkdir -p "$D" && PYTHONPATH= setsid nohup "$AUTORESEARCH_PYTHON" -u -m service.dashboard \
  >> "$D/dashboard.log" 2>&1 &
```

Then `ssh -L 8765:localhost:8765 <host>` and open `http://localhost:8765`.
`--once` writes one snapshot and exits; `--no-serve --out DIR` only writes
the files. Spec: `docs/superpowers/specs/2026-10-04-dashboard-design.md`.

## Tests

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
```

35 test files, 729 tests, no grid contact.

## More

[wiki/drivers/contract-engine.md](wiki/drivers/contract-engine.md) is the
engine's design record. The `surrogate/` MCP server exposes the same boards
(GP fit, predict, suggest) to an outside client; see
[wiki/drivers/surrogate.md](wiki/drivers/surrogate.md). Wiki catalog:
`wiki/index.md`.
