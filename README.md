# autoresearch — closed-loop Bayesian optimization of Mu2e geometry

A closed-loop framework that optimizes Mu2e detector geometry against
full-simulation physics metrics. Each iteration: a botorch GP proposes
candidate geometries, each candidate is rendered into an Offline geometry
file, checked locally for G4 feasibility, run through a multi-stage Geant4
chain on FermiGrid, and harvested into physics metrics — typically
S/√B (Run1A conversion-electron significance, maximized) and beam-flash
energy deposition per POT in the tracker (minimized). Results append to a
per-mode leaderboard TSV; the GP refits and the loop continues.

Each optimization line is a **mode**: a self-contained definition of the
knobs, bounds, geometry rendering, grid stages, and objectives. Modes are
defined as JSON specs in `mode_specs/` (legacy lines are Python classes in
`core/bo_driver.py`). Currently registered:

```
foils foilsf foilsflash foilsg foilspf foilspf2k prodtarget prodtarget6d   # BO lines
ipa625 ipafix ipaovr nominal                                              # fixed A/B reference arms
```

## Prerequisites

- **Python env**: the project venv is `.venv` at the repo root (a symlink to
  `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv`). Use
  `source .venv/bin/activate` or call `.venv/bin/python` directly. If it
  doesn't exist yet, see [Building the environment](#building-the-environment).
- **Kerberos**: a fresh ticket before launch. Mid-run expiry kills chains at
  grid submission (see `wiki/incidents/kerberos-mid-run-expiry.md`).
- **Mu2e environment** is sourced by the pipeline itself per stage; do not
  pre-source it in the launching shell. If you source cvmfs setups manually,
  `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` first (NFS lock
  wedge, see `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`).

### Building the environment

One venv serves everything — orchestrator, botorch picker, and plot
renderers (consolidated 2026-07-18 from three separate venvs). Python 3.11,
built with [uv](https://github.com/astral-sh/uv); pinned in
`requirements.txt`, whose header is the authoritative recipe.

**Install the CPU torch wheel FIRST, before anything else.** `botorch` and
`gpytorch` both depend on torch, so if pip resolves it for them you get the
default CUDA build — gigabytes of unusable wheels on a CPU-only grid node.
The explicit `+cpu` local version from the pytorch CPU index pre-satisfies
that dependency.

```bash
VENV=/exp/mu2e/data/users/$USER/autoresearch_venvs/.venv   # keep it OFF /exp/mu2e/app
uv venv --python 3.11 "$VENV"
uv pip install --python "$VENV/bin/python" \
  --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
uv pip install --python "$VENV/bin/python" -r requirements.txt
ln -s "$VENV" .venv
```

The venv lives on the `/data` volume and is *symlinked* into the repo
deliberately: it is far too large for the `/exp/mu2e/app` quota, and moving
it across volumes afterwards is painfully slow on CephFS
(`wiki/incidents/venv-relocated-to-data-volume.md`). `$VENV` is free choice;
only the symlink name `.venv` is load-bearing.

Verify with the test suite. The leading blank `PYTHONPATH=` is required: it
clears any `PYTHONPATH` inherited from a sourced Mu2e/cvmfs environment, so
the tests resolve imports against the venv alone.

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests
```

To A/B a different picker stack (say a newer botorch), build a second venv
the same way and point `AUTORESEARCH_BOTORCH_VENV` at it; the picker
subprocess resolves that env var against the repo root, so the orchestrator
keeps running on `.venv`.

**Portability caveat.** Building the venv under your own `$USER` is not
enough to run this repo as another account. The project root and the three
off-repo data volumes are currently **hardcoded** — roughly 20 literal
`/exp/mu2e/{app,data}/users/oksuzian/...` paths across 9 modules, including
`core/bo_driver.py:47` (`ROOT`) and `graph/config.py:7,16,33`
(`PROJECT_ROOT`, `GRAPH_DATA`, `GRID_DATA_ROOT`). Every absolute path
elsewhere in this README reflects that deployment rather than a convention
you can substitute into. Making the tree multi-user means routing those
through one configurable root first; until then, treat this as a
single-account deployment.

## Running an optimization campaign

The standard entrypoint is the multi-round closed loop. It launches `q`
single-evaluation children in parallel, waits at a barrier, refits the GP on
the updated leaderboard, and picks the next batch:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
source .venv/bin/activate
export AUTORESEARCH_CHECKPOINT_DIR=/tmp/$USER/<prefix>   # SQLite checkpoints off CephFS

nohup python -m graph.closed_loop \
  --mode foilspf \
  --picker hybrid \
  --q 10 \
  --rolling --max-evals 20 \
  --name-prefix foilspf05 \
  > /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/foilspf05_parent.log 2>&1 &
echo "PID=$!"
```

Key flags (`python -m graph.closed_loop --help` for the full list):

| flag | meaning |
|---|---|
| `--mode` | which optimization line (registry above) |
| `--picker` | acquisition: `hybrid` (qNEHVI+qNParEGO, default), `qnehvi`, `qnparego`, `qlnei` (sob-only), `pareto_sob` (GP-corner exploit) |
| `--q` | children in flight per round |
| `--rolling --max-evals N` | rolling replacement up to N total evaluations (preferred over fixed `--max-rounds`) |
| `--name-prefix` | unique campaign name; child configs become `<prefix>R<round>_<i>` |

**Pre-launch checklist** (each item has a root-caused incident behind it):

1. **Unique `--name-prefix`** — never reuse one that appears in the
   leaderboard, the pending TSV, or `state/*_cluster.txt`. Reuse silently
   launches zero children (`wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md`).
2. **Nothing already running for the mode**:
   `pgrep -f "closed_loop.*<prefix>"`.
3. **Fresh Kerberos ticket** (a successful submit within the last hour counts).
4. **Don't edit `core/`, `graph/`, or `core/pipeline_templates/` while
   children are in flight** — children re-execute the working tree.

**Stopping**: `touch /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/STOP_CLOSED_LOOP`
for a clean stop at the next round boundary (remove the file afterwards).

**Monitoring**: parent log (path in the launch line above); per-child logs at
`<graph_data>/closed_loop_logs/<child>.log`; grid queue via
`jobsub_q -G mu2e --user=$USER`; results via
`tail leaderboards/leaderboard_bo_<mode>.tsv`.

## Running a single evaluation

One chain end-to-end, without the multi-round parent:

```bash
python -m graph.run \
  --mode foilspf \
  --config-name mytest01 --thread-id mytest01 \
  --no-mock
```

- `--mock` replaces the grid with synthetic metrics (fast smoke test of the
  graph itself); `--no-mock` runs the real chain. The flag is required.
- `--x-point v1,v2,...` forces a **designed point** (comma-separated values in
  the mode's knob order) instead of a BO ask — used for A/B arms, replicates,
  and controlled scans. Rows land in the same leaderboard as BO rows.
- Never reuse a `--config-name` that already exists: the collision guard
  silently allocates a fresh auto-incremented name.

What one evaluation does (LangGraph node order):

```
propose → render geometry + preflight (local `mu2e -n 1` G4 init,
zero-overlap gate) → grid stages (mode-defined, e.g. mubeam →
run1b_mubeam → concat → mustops_ce [→ elebeam_flash for flash modes]) →
harvest (metrics from grid outputs) → scan_logs (G4 error audit; blocks the
row if broken) → evaluate (append leaderboard row) → END
```

Wall time is ~3–6 h per evaluation, dominated by grid stages. Per-config
artifacts (geometry, FCL, cluster files, harvest `summary.json`, logs) live
under `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<config>/`.

Lower-level entrypoints, normally not needed: `core/bo_driver.py
propose | evaluate | preflight` (the per-step CLI the graph wraps) and
`core/pipeline.py` (per-stage `submit | poll | list-outputs`, used directly
only to recover stalled chains).

## Defining a new optimization line

Copy `tests/fixtures/modes/template.json` to `mode_specs/<name>.json` and
edit the name, leaderboard path, knobs, and geometry block — **read
`mode_specs/README.md` first**; it documents the loader's validation rules
and the gotchas (leaderboard-path uniqueness, integer-knob formats, reserved
names). The loader is `core/mode_json.py`; specs are validated at import and
merged into `core.modes.SPECS`.

## Code structure

```
autoresearch/
├── core/                    # mode definitions + per-evaluation machinery
│   ├── modes.py             #   ModeSpec registry: every per-mode fact in one
│   │                        #   pure-data table, no silent defaults (ADR-0002)
│   ├── mode_json.py         #   JSON spec loader/validator (mode_specs/ → SPECS)
│   ├── bo_driver.py         #   propose | evaluate | preflight CLI; BOMode classes
│   ├── botorch_predict.py   #   GP fit + acquisition (all pickers), ask/tell seam
│   ├── pipeline.py          #   grid runner: fork config, submit, poll, harvest I/O
│   ├── harvest.py           #   metric extraction from grid outputs → Eval summary
│   ├── geom_template.py     #   knob values → rendered Offline geometry file
│   └── pipeline_templates/  #   per-stage FCL templates
├── graph/                   # LangGraph orchestration
│   ├── run.py               #   single-evaluation entrypoint (one chain = one graph run)
│   ├── closed_loop.py       #   multi-round parent: q children, barrier, GP refit, pickers
│   ├── nodes.py             #   graph nodes (propose, preflight, stages, harvest, evaluate)
│   ├── build.py / state.py  #   graph wiring + typed state
│   ├── child_tracker.py     #   sole resolver of child state at the barrier
│   ├── config.py            #   paths, per-mode stage chains, env seams
│   ├── pipeline_io.py       #   proposal/leaderboard file I/O, name allocation
│   └── presniff.py / sourced_bash.py   # log classification; env-sourcing subprocess helper
├── mode_specs/              # JSON mode definitions (see its README)
├── leaderboards/            # results: leaderboard_bo_<mode>.tsv (BO lines),
│                            #   leaderboard_ab_<arm>.tsv (fixed reference arms)
├── tests/                   # unittest suite + golden-geometry fixtures
├── tools/                   # capture_golden_geom.py (golden parity capture)
├── docs/                    # talks, specs, plans, ADRs (docs/adr/)
├── wiki/                    # persistent knowledge base (OKF bundle): concepts,
│                            #   drivers, and 50+ root-caused incidents — read before
│                            #   debugging anything grid-related
├── CONTEXT.md               # domain glossary
└── CLAUDE.md                # agent/session instructions
```

Off-repo data volumes (all under `/exp/mu2e/data/users/oksuzian/`):
`autoresearch_grid/` (per-config artifacts), `autoresearch_graph_data/`
(logs, state, checkpoints), `autoresearch_venvs/` (the real venv).

## Tests

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v
```

~200 tests, no grid contact. The golden geometry-parity harness (renders
every registered mode and diffs against `tests/fixtures/golden_geom/`) runs
separately:

```bash
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

## Where to read more

- `wiki/index.md` — catalog of every concept, driver, and incident page.
- `wiki/projects/` — one page per optimization line: status, standard
  settings, campaign history.
- `docs/adr/` — architectural decisions (why cl_min was retired, why modes
  are a pure-data registry, …).
- `mode_specs/README.md` — the new-mode recipe.
