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
foilsflash foilspf foilspf2k foilspfbp foilspfbpx foilspfbpz foilspfbw   # BO lines
ipa625 ipafix ipaovr nominal                                            # fixed A/B reference arms
```

## First-time setup

The order matters; each step links to the section that explains it. Steps 1-3
are one-time, step 4 is per shell.

1. **Clone it anywhere you like.** The project root is derived from the code's
   own location, so no path is baked in — `/exp/mu2e/app/users/$USER/autoresearch`
   is conventional, not required.

   ```bash
   git clone <repo-url> autoresearch && cd autoresearch
   ```

2. **Build the venv and symlink it** — see
   [Building the environment](#building-the-environment). Install the CPU torch
   wheel *first*; that section explains why. Verify with the test suite it gives
   you before going further: a green suite means the Python side is sound
   without `/exp/mu2e` being involved at all.

3. **Point at the build artifacts** — see [Artifacts](#artifacts). A fresh clone
   has none, so a campaign launch will refuse until you either build your own or
   link someone else's:

   ```bash
   ./setup.sh --backing /exp/mu2e/app/users/<operator>
   ```

4. **Load the roots into your shell**, then confirm what you are running
   against. Do this in every new shell, before launching anything:

   ```bash
   source .venv/bin/activate
   source setup.sh
   ./setup.sh --status
   ```

   `--status` prints the four resolved roots and where each came from
   (`default ($USER)`, `env`, or `backing`). If any line surprises you, stop and
   fix it before submitting jobs — that is what this command is for.

5. **Smoke-test the chain** with a single mock evaluation before spending grid
   time — see [Running a single evaluation](#running-a-single-evaluation) and
   use `--mock`.

Then read [Running an optimization campaign](#running-an-optimization-campaign).
If a launch fails, the error names both the offending path and the command that
fixes it; the [Artifacts](#artifacts) section explains the backing rule behind
those messages.

## Prerequisites

- **Python env**: the project venv is `.venv` at the repo root (a symlink to
  `/exp/mu2e/data/users/$USER/autoresearch_venvs/.venv`). Use
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

### Artifacts

Grid stages need a patched Offline build and a prebuilt `Code_*.tar.bz2`.
Modes reference them as `${ARTIFACT}/...`, resolved against
`$AUTORESEARCH_ARTIFACT_ROOT` (default `/exp/mu2e/app/users/$USER`) and
falling through to a **backing** link for anything you have not built
yourself — the same local-wins-then-backing rule as `muse backing`:

```bash
./setup.sh --backing /exp/mu2e/app/users/<operator>   # borrow an existing build
./setup.sh --status                                   # what am I running against?
```

`<operator>` is anyone who already has the patched Offline build and the
grid tarballs. Until the build recipes live in this repo, that means asking
a colleague who has run a campaign — the artifacts are world-readable, so a
backing link is all you need and you build nothing.

A fresh clone has no backing and no local artifacts, so campaign launch
fails immediately, naming the command above. That is deliberate: running
against someone else's build should be something you said, not something
that happened.

### Where your results go

- **Live rows** append to `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/`
  (default `/exp/mu2e/data/users/$USER/...`), one flat directory.
- **The committed `leaderboards/`** are a read-only archive of past
  campaigns. Every operator starts warm from them; nobody writes to them
  except by a reviewed git commit.
- Grid work trees and logs likewise live under your own `$AUTORESEARCH_DATA_ROOT`.

## Running an optimization campaign

The standard entrypoint is the multi-round closed loop. It launches `q`
single-evaluation children in parallel, waits at a barrier, refits the GP on
the updated leaderboard, and picks the next batch:

```bash
cd /exp/mu2e/app/users/$USER/autoresearch    # wherever you cloned it
source .venv/bin/activate
source setup.sh   # exports AUTORESEARCH_DATA_ROOT / AUTORESEARCH_ARTIFACT_ROOT used below
export AUTORESEARCH_CHECKPOINT_DIR=/tmp/$USER/<prefix>   # SQLite checkpoints off CephFS

nohup python -m graph.closed_loop \
  --mode foilspf \
  --picker hybrid \
  --q 10 \
  --rolling --max-evals 20 \
  --name-prefix foilspf05 \
  > "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/foilspf05_parent.log" 2>&1 &
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

**Stopping**: `source setup.sh` (if not already done in this shell), then
`touch "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/STOP_CLOSED_LOOP"`
for a clean stop at the next round boundary (remove the file afterwards).

**Monitoring**: parent log (path in the launch line above); per-child logs at
`<graph_data>/closed_loop_logs/<child>.log`; grid queue via
`jobsub_q -G mu2e --user=$USER`; results via
`tail "$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/leaderboard_bo_<mode>.tsv"`
(again, `source setup.sh` first if needed — the repo's `leaderboards/` is the
frozen archive of past campaigns, not where a running campaign's new rows
land).

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
under `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<config>/`.

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
│   ├── paths.py             #   the ONLY module that knows a filesystem
│   │                        #   layout: repo/data/artifact roots + backing
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
├── setup.sh                 # --status / --backing; sourced, exports the roots
├── CONTEXT.md               # domain glossary
└── CLAUDE.md                # agent/session instructions
```

Off-repo data volumes (all under `$AUTORESEARCH_DATA_ROOT`, default `/exp/mu2e/data/users/$USER/`):
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
