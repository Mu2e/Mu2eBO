# autoresearch — closed-loop Bayesian optimization of Mu2e geometry

Each iteration: a botorch GP proposes candidate geometries, each is rendered
into an Offline geometry file, checked locally for G4 feasibility, run through
a multi-stage Geant4 chain on FermiGrid, and harvested into physics metrics —
typically S/√B (Run1A conversion-electron significance, maximized) and beam-flash
energy deposition per POT in the tracker (minimized). Rows append to a per-mode
leaderboard TSV; the GP refits and the loop continues.

Each optimization line is a **mode**: knobs, bounds, geometry rendering, grid
stages, and objectives in one self-contained definition — a JSON spec in
`mode_specs/` (legacy lines are Python classes in `core/bo_driver.py`).

```
foilsflash foilspf foilspf2k foilspfbp foilspfbpx foilspfbpz foilspfbw   # BO lines
ipa625 ipafix ipaovr nominal                                            # fixed A/B reference arms
```

## Quick start

Copy-paste. About two minutes; nothing is built.

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
source activate.sh                                           # <- every new shell
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .   # expect OK
# ./setup.sh --backing /exp/mu2e/app/users/oksuzian   # personal-path-ok: uncomment on purpose - see below
source setup.sh                                              # <- every new shell
./setup.sh --status                                          # confirm before submitting
```

No venv to build or link: `activate.sh` resolves the published Mu2e env on
`/cvmfs` (`ana 2.8.0`) and exports it as `$AUTORESEARCH_PYTHON`.

- **The two `source` lines are the only per-shell steps**, and they are
  ordered: `activate.sh` resolves the interpreter, `setup.sh` freezes the
  roots. The blank `PYTHONPATH=` clears whatever a sourced cvmfs environment
  left behind.
- **`--backing` is commented on purpose.** A fresh clone has no patched
  Offline build, so a campaign launch refuses until you link one — but running
  on someone else's build should be a thing you decided, not a thing a paste
  did to you. See [Artifacts](#artifacts).
- **`--status`** prints the resolved roots, interpreter, and where each came
  from. If a line surprises you, stop before submitting jobs.

Next: [one evaluation](#running-a-single-evaluation), then
[a campaign](#running-an-optimization-campaign). With no grid access, go to
[Running without the grid](#running-without-the-grid).

## Prerequisites

- **Python env**: `source activate.sh` exports `$AUTORESEARCH_PYTHON`,
  defaulting to the published `ana 2.8.0` on `/cvmfs` — nothing to build,
  identical on every node, and the release whose numpy 2.5.2 finally carries
  torch + botorch. `AUTORESEARCH_VENV=/path/to/venv` selects a writable dev
  stack; `AUTORESEARCH_PYENV="ana 2.9.0"` another release. **Always name a
  version**: bare `pyenv ana` means 2.7.0 and `current` is 2.6.1, both numpy
  1.26, which torch will not run on. `activate.sh` deliberately does not
  *activate* the env — its header explains why the exported `python`/`pip`
  wrappers must not reach our subprocesses.
- **`AUTORESEARCH_PRODTOOLS`** (required, grid AND local): every job — build,
  submit, wait, run-locally — is executed by shelling out to
  [prodtools](https://github.com/Mu2e/prodtools), never by this repo directly.
  Point it at a checkout holding `bin/json2jobdef`:

  ```bash
  export AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/<release>
  ```

  Unset, or missing `bin/json2jobdef`, fails loudly at the first submit,
  naming the variable — there is no silent fallback.
- **Kerberos**: a fresh ticket before launch; a grid chain submits stages for
  hours, so `tools/run_grid.sh` refuses one with under 4 h left
  (`wiki/incidents/kerberos-mid-run-expiry.md`).
- **Mu2e environment** is sourced by the pipeline itself per stage; do not
  pre-source it in the launching shell. If you source cvmfs setups manually,
  `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` first (NFS lock wedge,
  `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`).

### Building the environment

Optional — the published `/cvmfs` env is the default and needs no build. Build
your own to change a pin, or to have one nobody can rebuild under you. One venv
serves everything (orchestrator, picker, plot renderers); `requirements.txt`'s
header is the authoritative recipe, `requirements.lock` the pinned resolution.

**Install the CPU torch wheel FIRST.** `botorch` and `gpytorch` both depend on
torch, so if pip resolves it for them you get the CUDA build — 2.8 GB against
692 MB.

```bash
VENV=/exp/mu2e/data/users/$USER/autoresearch_venvs/.venv   # keep it OFF /exp/mu2e/app
uv venv --python 3.11 "$VENV"
uv pip install --python "$VENV/bin/python" \
  --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
uv pip install --python "$VENV/bin/python" -r requirements.txt

AUTORESEARCH_VENV="$VENV" source activate.sh
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
```

Keep it on `/data`: it is far too large for the `/exp/mu2e/app` quota, and
moving it across volumes afterwards is painfully slow on CephFS
(`wiki/incidents/venv-relocated-to-data-volume.md`).

The picker subprocess runs on **the caller's interpreter** by default, so it
never silently diverges from the stack everything else was verified on. To A/B
a different picker stack, build a second venv, link it under the repo root, and
point `AUTORESEARCH_BOTORCH_VENV` at that directory name; only the picker moves.

### Artifacts

Grid stages need a patched Offline build and a prebuilt `Code_*.tar.bz2`. Modes
reference them as `${ARTIFACT}/...`, resolved against
`$AUTORESEARCH_ARTIFACT_ROOT` (default `/exp/mu2e/app/users/$USER`) and falling
through to a **backing** link for anything you have not built — the same
local-wins-then-backing rule as `muse backing`:

```bash
./setup.sh --backing /exp/mu2e/app/users/oksuzian   # personal-path-ok: the build every campaign so far has run on
./setup.sh --status                                 # what am I running against?
```

Any operator who has run a campaign works; the artifacts are world-readable, so
a backing link is all you need and you build nothing. A fresh clone has neither,
so campaign launch fails immediately and names the command above — deliberately.

### Where your results go

- **Live rows** append to `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/`
  (default `/exp/mu2e/data/users/$USER/...`), one flat directory. Grid work
  trees and logs live under the same root.
- **The committed `leaderboards/`** are a read-only archive of past campaigns.
  Every operator starts warm from them; nobody writes to them except by a
  reviewed git commit.

## Running an optimization campaign

The standard entrypoint is the closed loop: a bounded **work pool** that keeps
`q` single-evaluation children in flight and launches a replacement — refitting
the GP against the leaderboard as it stands at that moment — each time one
exits, until `--max-evals` have been launched and the pool drains. No rounds,
no barrier.

```bash
source activate.sh && source setup.sh

nohup python -m graph.closed_loop \
  --mode foilspf --picker hybrid --q 20 --max-evals 40 \
  --name-prefix foilspf05 \
  > "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/foilspf05_parent.log" 2>&1 &
echo "PID=$!"
```

| flag | meaning |
|---|---|
| `--mode` | which optimization line (registry above) |
| `--picker` | `hybrid` (qNEHVI+qNParEGO, default), `qnehvi`, `qnparego`, `qlnei` (sob-only acquisition), `pareto_sob` (GP-corner exploit), `budget_sob` (sob corner within the damage budget) |
| `--q` | pool width: children kept in flight at once |
| `--max-evals` | total evaluations before draining (defaults to `q * --max-rounds`; `--max-rounds` survives only as that multiplier) |
| `--name-prefix` | campaign name; children become `<prefix>R<i>_00`, `<i>` counting launches |

**Pre-launch checklist** (each item has a root-caused incident behind it):

1. **`--name-prefix`** — for a NEW campaign, pick an unused one. Reusing one is
   not an error (it is the documented crash-recovery move below): the pool
   skips any candidate name that already has a leaderboard row, a
   `broken.txt`, a `state/*_cluster.txt`, or an unresolved pending row, and
   advances to the next free index, logging each skip. It will not silently
   launch zero children — but it does interleave two campaigns under one name
   series.
2. **Nothing already running for the mode**: `pgrep -f "closed_loop.*<prefix>"`.
3. **Fresh Kerberos ticket** (a successful submit within the last hour counts).
4. **Don't edit `core/`, `graph/`, or `stage_entries/` while children are in
   flight** — children re-execute the working tree.

**Stopping**: `touch "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/STOP_CLOSED_LOOP"`
(remove it afterwards). The pool stops LAUNCHING at its next top-up check;
children in flight are never signalled, and the parent **blocks until every one
exits** — possibly hours. That is the structural fix for
`wiki/incidents/closed-loop-final-round-orphan-children.md`, but it means STOP
is not a fast exit; to stop sooner, `jobsub_rm` the clusters and kill the
`graph.run` processes yourself.

**Monitoring**: the parent log prints `[pool] heartbeat: N in flight (name Xh, ...)`
every 15 minutes while waiting — a frozen log means the PARENT is wedged, not
the grid, and a child at >24h gets an explicit WARNING. Per-child logs are at
`<graph_data>/closed_loop_logs/<child>.log`; queue via
`jobsub_q -G mu2e --user=$USER`; rows via
`tail "$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/leaderboard_bo_<mode>.tsv"`.

### Recovering from a crashed parent

Children are launched with `start_new_session=True`, so **killing or losing the
parent does not stop them** — they keep polling the grid and can still land rows.

1. Check what survived: `pgrep -f "graph.run.*<prefix>"`.
2. Wait for those to finish, or `jobsub_rm` their clusters and kill them.
   Relaunching under the same `--name-prefix` while a prior child is still in
   flight is the one genuinely unsafe move: two `graph.run` processes under one
   config name re-use each other's per-stage `cluster.txt` files and can land
   two rows under that name, both carrying the first child's metrics.
3. Relaunch with the same `--mode`, `--picker`, `--name-prefix`. The pool
   resumes by skipping names the prior run resolved or left work in flight for
   and continuing from the next free index. Nothing else is resumed — there is
   no checkpointer, and no mid-chain resume for an individual eval either.

## Running a single evaluation

```bash
tools/run_grid.sh [config-name] [mode]     # one grid evaluation, checked
```

With no arguments it picks a timestamped config name and mode `foilspf`. It
sandboxes `AUTORESEARCH_DATA_ROOT`, borrows an operator's artifacts, and runs
every launch gate in `core/launch_checks.py` — artifacts and
`AUTORESEARCH_PRODTOOLS` present, config name free, no stale cluster files,
CephFS quota under 90%, Kerberos ticket good for 4 h — then prints each stage's
grid width read from the mode spec and runs the chain. Takes 3–6 h, so:

```bash
nohup tools/run_grid.sh gridcheck01 \
  > /exp/mu2e/data/users/$USER/gridtest/gridcheck01.log 2>&1 &
```

The chain it wraps is `python -m graph.run --mode M --config-name N --thread-id N`.
Useful flags there: `--x-point v1,v2,...` forces a **designed point**
(comma-separated, in the mode's knob order) instead of a BO ask — for A/B arms,
replicates, and controlled scans; rows land in the same leaderboard. Never
reuse a `--config-name`: the collision guard silently allocates a fresh
auto-incremented name.

Node order:

```
propose → render geometry + preflight (local `mu2e -n 1` G4 init, zero-overlap
gate) → grid stages (mubeam → mustops_ce → elebeam_flash) → harvest →
scan_logs (G4 error audit; blocks the row if broken) → evaluate (append row) → END
```

Per-config artifacts (geometry, FCL, cluster files, harvest `summary.json`,
logs) live under `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<config>/`.
Lower-level entrypoints, normally not needed: `core/bo_driver.py
propose | evaluate | preflight` and `core/pipeline.py`
(`submit | poll | list-outputs`, used directly only to recover stalled chains).

## Running without the grid

`AUTORESEARCH_LOCAL=1` runs every stage on this node instead of the grid — via
prodtools' own `runlocal`, the same tool the grid path uses to build the job,
just executed here. No jobsub, no queue. It is **not offline**: jobs still
stream resampler inputs over xrootd from `/pnfs`, so you need a Kerberos ticket,
read access to the Mu2e datasets, and `AUTORESEARCH_PRODTOOLS`.

From a bare clone:

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
source activate.sh
./setup.sh --backing /exp/mu2e/app/users/oksuzian     # personal-path-ok: borrow a built Offline
export AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/<release>
tools/run_local.sh local01                            # one evaluation, ~20 min
```

`tools/run_local.sh` sandboxes `AUTORESEARCH_DATA_ROOT` to `…/localtest`, runs
the same gates as `run_grid.sh` minus the three only a queued chain needs, sets
a scale that lands a row (8 × 12500), prints the resolved roots, and runs the
chain. Every default is an env override:

| variable | run_local.sh | raw default | meaning |
|---|---|---|---|
| `AUTORESEARCH_LOCAL_NJOBS` | 8 | 1 | jobs per stage |
| `AUTORESEARCH_LOCAL_EVENTS` | 12500 | 200 | events per job |
| `AUTORESEARCH_LOCAL_POOL` | 8 | 4 | jobs running concurrently |

`AUTORESEARCH_LOCAL_EVENTS=200 tools/run_local.sh smoke01` gives a ~30 s/stage
plumbing check instead. Supported stages are `mubeam`, `mustops_ce`,
`elebeam_flash`; anything else is refused rather than half-run.

**Why the sandbox matters**: every path the runner writes — grid tree, logs,
live leaderboard — hangs off `$AUTORESEARCH_DATA_ROOT`, so pointing it at
scratch keeps a local run out of the board your real campaigns train on. Even a
row-landing local run is far noisier than a grid evaluation (~10⁷ events). The
committed `leaderboards/` archive is read as priors either way and never written.

### What a small run gives you — and what it does not

At 1 × 200 events the chain ends with a real `harvest/summary.json`:
`s_over_sqrt_b`, stop counts, efficiencies, the CE ntuple. That is the plumbing
check, and it is the point.

**It will not append a leaderboard row on a flash mode**, by design. Flash
energy reaches only a few events per thousand (`1.3e-3`–`4.2e-3` across local
geometries), so 200 events expects well under one. `evaluate` refuses to append
a row whose second objective is zero, because that zero would dominate the
Pareto front at the next GP refit; you get an explicit
`scan_logs/evaluate_zero_row.tsv` naming the cause, not a silent skip.

`run_local.sh`'s 10⁵ default landed a row on every geometry tried, with 41–137
flash events (~9–16% statistical error, varying by geometry — sample it, don't
assume it) for about 15 minutes of stages on 8 cores. Per-event cost is far
below what the 200-event timing suggests: ~25 s of each job is G4 init and
geometry load, paid once.

## Defining a new optimization line

Copy `tests/fixtures/modes/template.json` to `mode_specs/<name>.json` and edit
the name, leaderboard path, knobs, and geometry block — **read
`mode_specs/README.md` first**; it documents the loader's validation rules and
the gotchas (leaderboard-path uniqueness, integer-knob formats, reserved names).
The loader is `core/mode_json.py`; specs are validated at import and merged into
`core.modes.SPECS`.

## Code structure

```
autoresearch/
├── core/                    # mode definitions + per-evaluation machinery
│   ├── modes.py             #   ModeSpec registry: every per-mode fact in one
│   │                        #   pure-data table, no silent defaults (ADR-0002)
│   ├── paths.py             #   the ONLY module that knows a filesystem
│   │                        #   layout: repo/data/artifact roots + backing
│   ├── runtime.py           #   non-path runtime tunables: per-mode stage
│   │                        #   chains, closed-loop constants, env seams
│   ├── launch_checks.py     #   pre-launch gates (kerberos life, name
│   │                        #   collision, stale clusters, quota, artifacts)
│   ├── mode_json.py         #   JSON spec loader/validator (mode_specs/ → SPECS)
│   ├── bo_driver.py         #   propose | evaluate | preflight CLI; BOMode classes
│   ├── botorch_predict.py   #   GP fit + acquisition (all pickers), ask/tell seam
│   ├── pipeline.py          #   grid runner: fork config, render stage_entries
│   │                        #   into a per-config entry, submit/poll/harvest I/O
│   ├── prodtools_exec.py    #   the ONLY module that shells prodtools
│   │                        #   (json2jobdef/submit/jobwait/runlocal)
│   ├── prodtools_submit_driver.py  # CLI driver prodtools_exec.submit_cnf shells
│   │                        #   out to (ledger row + prodtools' submit_entry)
│   ├── harvest.py           #   metric extraction from grid outputs → Eval summary
│   ├── geom_template.py     #   knob values → rendered Offline geometry file
│   └── pipeline_templates/  #   mubeam extras.fcl (@sequence:: overrides no JSON
│                            #   value can express) — see stage_entries/
├── stage_entries/           # checked-in per-stage json2jobdef entries (fcl +
│                            #   fcl_overrides, inloc/outloc/run/memory/events);
│                            #   THE job description, with mode_specs'
│                            #   stage_tuning layered on top
├── graph/                   # LangGraph orchestration
│   ├── run.py               #   single-evaluation entrypoint (one chain = one run)
│   ├── closed_loop.py       #   campaign parent CLI: picker subprocess, krb5
│   │                        #   renewal, STOP flag; drives pool.run_rolling
│   ├── pool.py              #   the parent itself: q children in flight, one
│   │                        #   replacement per exit (no rounds, no barrier)
│   ├── nodes.py             #   propose, preflight, stages, harvest, evaluate
│   ├── build.py / state.py  #   graph wiring + typed state
│   ├── pipeline_io.py       #   proposal/leaderboard file I/O, name allocation
│   └── sourced_bash.py      #   env-sourcing subprocess helper
├── mode_specs/              # JSON mode definitions (see its README)
├── leaderboards/            # READ-ONLY archive; live rows go to $AUTORESEARCH_DATA_ROOT
├── tests/                   # unittest suite + golden-geometry fixtures
├── tools/                   # run_grid.sh, run_local.sh, capture_golden_geom.py
├── docs/                    # talks, specs, plans, ADRs (docs/adr/)
├── wiki/                    # persistent knowledge base (OKF bundle): concepts,
│                            #   drivers, and 50+ root-caused incidents — read
│                            #   before debugging anything grid-related
├── activate.sh              # resolves $AUTORESEARCH_PYTHON (cvmfs env or venv)
├── setup.sh                 # --status / --backing / --venv; sourced, exports roots
├── CONTEXT.md               # domain glossary
└── CLAUDE.md                # agent/session instructions
```

Off-repo volumes (under `$AUTORESEARCH_DATA_ROOT`, default
`/exp/mu2e/data/users/$USER/`): `autoresearch_grid/` (per-config artifacts),
`autoresearch_graph_data/` (logs, state), `autoresearch_venvs/` (dev venvs).

## Tests

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t . -v
```

679 tests (2 skipped), no grid contact. The golden geometry-parity harness
(renders every registered mode and diffs against `tests/fixtures/golden_geom/`)
runs separately:

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check
```

## Where to read more

- `wiki/index.md` — catalog of every concept, driver, and incident page.
- `wiki/projects/` — one page per optimization line: status, standard
  settings, campaign history.
- `docs/adr/` — architectural decisions.
- `mode_specs/README.md` — the new-mode recipe.
