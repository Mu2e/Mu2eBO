# autoresearch — closed-loop Bayesian optimization of Mu2e geometry

A botorch GP proposes candidate geometries; each is rendered into an Offline
geometry file, checked locally for G4 feasibility, run through a multi-stage
Geant4 chain, and harvested into physics metrics — S/√B (Run1A
conversion-electron significance, maximized) and beam-flash energy deposition
per POT in the tracker (minimized). Rows append to a per-mode leaderboard TSV;
the GP refits and the loop continues.

Each optimization line is a **mode** — knobs, bounds, geometry rendering, grid
stages, and objectives in one JSON spec under `mode_specs/`:

```
foilsflash foilspf foilspf2k foilspfbp foilspfbpx foilspfbpz foilspfbw   # BO lines
ipa625 ipafix ipaovr nominal                                            # fixed A/B reference arms
```

## Setup

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
source activate.sh                                    # every new shell
./setup.sh --backing /exp/mu2e/app/users/oksuzian     # personal-path-ok: borrow a built Offline
export AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/<release>
kinit
```

- **`activate.sh`** exports `$AUTORESEARCH_PYTHON` — the published Mu2e env
  `ana 2.8.0` on `/cvmfs`. Nothing to build. `AUTORESEARCH_VENV=/path/to/venv`
  overrides it with a writable dev stack.
- **`--backing`** borrows another operator's patched Offline build and grid
  tarballs; a fresh clone has none, and every run refuses until you link one.
  The artifacts are world-readable, so this is all you need — you build
  nothing. `./setup.sh --status` always prints whose build you are on.
- **`AUTORESEARCH_PRODTOOLS`** is required for grid *and* local runs: every job
  is built and executed by [prodtools](https://github.com/Mu2e/prodtools), not
  by this repo. Point it at a checkout holding `bin/json2jobdef`.
- **Kerberos**: even local jobs stream resampler inputs from `/pnfs` over
  xrootd, so a ticket is not optional.

## Run one evaluation

```bash
tools/run_local.sh [config-name] [mode]     # this node, ~20 min
tools/run_grid.sh  [config-name] [mode]     # FermiGrid, 3-6 h
```

With no arguments each picks a timestamped config name and mode `foilspf`.
Both sandbox `AUTORESEARCH_DATA_ROOT` so a test run stays out of the board your
real campaigns train on, print the roots they resolved, and run every gate in
`core/launch_checks.py` before starting — artifacts and prodtools present,
config name free, no stale cluster files, and (grid only) CephFS quota under
90% plus a Kerberos ticket good for 4 h.

The grid one takes hours, so detach it:

```bash
nohup tools/run_grid.sh gridcheck01 \
  > /exp/mu2e/data/users/$USER/gridtest/gridcheck01.log 2>&1 &
```

What a run does:

```
propose → render geometry + preflight (local `mu2e -n 1`, zero-overlap gate)
→ stages (mubeam → mustops_ce → elebeam_flash) → harvest → scan_logs
→ evaluate (append leaderboard row)
```

Artifacts land in `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<config>/`, rows in
`$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/`. The committed
`leaderboards/` is a read-only archive, read as priors and never written.

### Local scale

`run_local.sh` defaults to 8 × 12500 events per stage, which lands a row. Every
default is an env override:

| variable | default | meaning |
|---|---|---|
| `AUTORESEARCH_LOCAL_NJOBS` | 8 | jobs per stage |
| `AUTORESEARCH_LOCAL_EVENTS` | 12500 | events per job |
| `AUTORESEARCH_LOCAL_POOL` | 8 | jobs running concurrently |

`AUTORESEARCH_LOCAL_EVENTS=200 tools/run_local.sh smoke01` is a ~30 s/stage
plumbing check instead. It produces a real `harvest/summary.json` but
deliberately lands **no row**: at 200 events the flash objective expects under
one event, and `evaluate` refuses a row whose second objective is zero rather
than let that zero dominate the Pareto front at the next GP refit.

## Run a campaign

The closed loop is a work pool: `q` evaluations in flight, one replacement
launched per exit, with the GP refit against the leaderboard as it stands.

```bash
nohup python -m graph.closed_loop --mode foilspf --picker hybrid \
  --q 20 --max-evals 40 --name-prefix foilspf05 \
  > "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/foilspf05_parent.log" 2>&1 &
```

`--help` lists the pickers and the rest. Pick an unused `--name-prefix`, and
don't edit `core/`, `graph/`, or `stage_entries/` while children are in flight —
they re-execute the working tree. To stop, `touch
"$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/STOP_CLOSED_LOOP"`; the pool
stops launching but blocks until every child exits. Recovery, monitoring, and
crashed parents: [wiki/drivers/closed-loop-runner.md](wiki/drivers/closed-loop-runner.md).

## Tests

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
```

681 tests, no grid contact.

More: `wiki/index.md`.
