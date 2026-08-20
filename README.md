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

## Quick start

Copy-paste. About two minutes; nothing is built.

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
./setup.sh --venv                                           # link the shared venv
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .   # expect OK, under a minute
# ./setup.sh --backing /exp/mu2e/app/users/oksuzian   # personal-path-ok: uncomment on purpose - see below
source .venv/bin/activate && source setup.sh                 # <- every new shell
./setup.sh --status                                          # confirm before submitting
```

- **`--venv`** with no path links this deployment's reference venv — the same
  as spelling it out:

  ```bash
  ./setup.sh --venv /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv   # personal-path-ok: the site venv, spelled out so the line runs as-is
  ```

  It echoes what it linked, and `--venv -r` unlinks. Any operator's venv works;
  they are world-readable. You get read-only use, so build your own before
  changing a pin — [Building the environment](#building-the-environment).
- **The blank `PYTHONPATH=`** is required: it clears whatever a sourced
  Mu2e/cvmfs environment left behind.
- **`--backing` is commented on purpose.** A fresh clone has no patched Offline
  build, so a campaign launch refuses until you link one — but running on
  someone else's build should be a thing you decided, not a thing a paste did
  to you. Uncomment it once you have read [Artifacts](#artifacts). Any operator
  who has run a campaign works; the artifacts are world-readable.
- **The `source` line is the only per-shell step.** Everything above it is once.
- **`--status`** prints the resolved roots and the venv with where each came
  from. If a line surprises you, stop before submitting jobs.

Next: smoke-test one chain
([Running a single evaluation](#running-a-single-evaluation)), then
[Running an optimization campaign](#running-an-optimization-campaign). With no
grid access — or to study one job's FCL by hand — go straight to
[Running without the grid](#running-without-the-grid), which repeats the steps
above as one self-contained recipe.

## Prerequisites

- **Python env**: the project venv is `.venv` at the repo root — a symlink to a
  real venv on `/data`, either the site one or your own build. Use
  `source .venv/bin/activate` or call `.venv/bin/python` directly. A fresh
  clone has none — link it in the [Quick start](#quick-start).
- **`AUTORESEARCH_PRODTOOLS`** (required, grid AND local): every job this repo
  runs — build, submit, wait, or run-locally — is executed by shelling out to
  [prodtools](https://github.com/Mu2e/prodtools), never by this repo directly.
  Export it to a prodtools checkout (the directory holding `bin/json2jobdef`)
  before running `pipeline.py submit` (directly, via `graph.run`, or via
  `submit --local`):

  ```bash
  export AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0   # pinned release; any prodtools checkout with bin/json2jobdef works
  ```

  Unset or pointing at something without `bin/json2jobdef` fails loudly at
  the first submit, naming the variable — there is no silent fallback.
- **Kerberos**: a fresh ticket before launch. Mid-run expiry kills chains at
  grid submission (see `wiki/incidents/kerberos-mid-run-expiry.md`).
- **Mu2e environment** is sourced by the pipeline itself per stage; do not
  pre-source it in the launching shell. If you source cvmfs setups manually,
  `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` first (NFS lock
  wedge, see `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`).

### Building the environment

Optional — the [Quick start](#quick-start) links an existing venv in one
command, and that is the normal path. Build your own when you need to
change a pin, or want one nobody else can rebuild under you.

One venv serves everything — orchestrator, botorch picker, and plot
renderers (consolidated 2026-07-18 from three separate venvs). Python 3.11,
built with [uv](https://github.com/astral-sh/uv); pinned in
`requirements.txt`, whose header is the authoritative recipe.

**Install the CPU torch wheel FIRST, before anything else.** `botorch` and
`gpytorch` both depend on torch, so if pip resolves it for them you get the
CUDA build — 2.8 GB against the 692 MB of the `+cpu` wheel. The explicit
`+cpu` local version from the pytorch CPU index pre-satisfies that dependency.

```bash
VENV=/exp/mu2e/data/users/$USER/autoresearch_venvs/.venv   # keep it OFF /exp/mu2e/app
uv venv --python 3.11 "$VENV"
uv pip install --python "$VENV/bin/python" \
  --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
uv pip install --python "$VENV/bin/python" -r requirements.txt
ln -s "$VENV" .venv     # `.venv` is the load-bearing name; $VENV itself is free choice
```

Then verify: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`.

The venv lives on the `/data` volume and is symlinked into the repo
deliberately: it is far too large for the `/exp/mu2e/app` quota, and moving
it across volumes afterwards is painfully slow on CephFS
(`wiki/incidents/venv-relocated-to-data-volume.md`).

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
./setup.sh --backing /exp/mu2e/app/users/oksuzian   # personal-path-ok: the build every campaign so far has run on
./setup.sh --status                                 # what am I running against?
```

Any operator who already has the patched Offline build and the grid tarballs
works, not just the one above. Until the build recipes live in this repo that
means asking a colleague who has run a campaign — the artifacts are
world-readable, so a backing link is all you need and you build nothing.

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

The standard entrypoint is the closed loop. It is a bounded **work pool**:
it keeps `q` single-evaluation children in flight at once and launches a
replacement — refitting the GP against the leaderboard as it stands at that
moment — each time one exits, until `--max-evals` have been launched and the
pool drains. There are no rounds and no barrier.

```bash
cd /exp/mu2e/app/users/$USER/autoresearch    # wherever you cloned it
source .venv/bin/activate
source setup.sh   # exports AUTORESEARCH_DATA_ROOT / AUTORESEARCH_ARTIFACT_ROOT used below

nohup python -m graph.closed_loop \
  --mode foilspf \
  --picker hybrid \
  --q 20 \
  --max-evals 40 \
  --name-prefix foilspf05 \
  > "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/foilspf05_parent.log" 2>&1 &
echo "PID=$!"
```

Key flags (`python -m graph.closed_loop --help` for the full list):

| flag | meaning |
|---|---|
| `--mode` | which optimization line (registry above) |
| `--picker` | acquisition: `hybrid` (qNEHVI+qNParEGO, default), `qnehvi`, `qnparego`, `qlnei` (sob-only acquisition — it no longer drops a stage; that auto-stamp died with `graph/presniff.py`), `pareto_sob` (GP-corner exploit), `budget_sob` (sob corner within the damage budget) |
| `--q` | pool width: children kept in flight at once |
| `--max-evals` | total evaluations to launch before draining (defaults to `q * --max-rounds`; `--max-rounds` survives only as that multiplier — there are no rounds) |
| `--name-prefix` | campaign name; child configs become `<prefix>R<i>_00`, `<i>` counting launches |

**Pre-launch checklist** (each item has a root-caused incident behind it):

1. **`--name-prefix`** — for a NEW campaign, pick one no past campaign used.
   Reusing a prefix is not an error (it is the documented crash-recovery
   move, below): the pool skips any candidate name that already has a
   leaderboard row, a `broken.txt`, a `state/*_cluster.txt`, or an
   unresolved pending-TSV row, and advances to the next free index, logging
   each skip. It will not silently launch zero children — but a reused
   prefix does interleave two campaigns' evals under one name series.
2. **Nothing already running for the mode**:
   `pgrep -f "closed_loop.*<prefix>"`.
3. **Fresh Kerberos ticket** (a successful submit within the last hour counts).
4. **Don't edit `core/`, `graph/`, `core/pipeline_templates/`, or
   `stage_entries/` while children are in flight** — children re-execute the
   working tree.

**Stopping**: `source setup.sh` (if not already done in this shell), then
`touch "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/STOP_CLOSED_LOOP"`
(remove the file afterwards). The pool stops LAUNCHING at its next top-up
check; children already in flight are never signalled, and the parent then
**blocks until every one of them exits** — which can be hours. That is
deliberate (it is the structural fix for
`wiki/incidents/closed-loop-final-round-orphan-children.md`), but it means
STOP is not a fast exit. To stop sooner you must deal with the children
yourself (`jobsub_rm`, then kill the `graph.run` processes).

### Recovering from a crashed parent

Children are launched with `start_new_session=True`, so **killing or losing
the parent does not stop them** — they keep polling the grid and can still
land leaderboard rows on their own.

1. Check what survived: `pgrep -f "graph.run.*<prefix>"`.
2. Wait for those to finish, or `jobsub_rm` their clusters and kill them.
   Relaunching under the same `--name-prefix` while a child from the prior
   run is still in flight is the one genuinely unsafe move: two `graph.run`
   processes under one config name re-use each other's per-stage
   `cluster.txt` files and can land two leaderboard rows under that name,
   both carrying the first child's metrics.
3. Then relaunch with the same `--mode`, `--picker` and `--name-prefix`. The
   pool resumes by SKIPPING names the prior run already resolved or left
   work in flight for (see checklist item 1) and continuing from the next
   free index. Nothing else is resumed — there is no checkpointer.

There is no mid-chain resume for an individual eval either. A relaunched
child under an existing name re-attaches to whatever its stages already
submitted (per-stage `cluster.txt` idempotency in `core/pipeline.py`) rather
than resubmitting — which is exactly why step 2 matters.

**Monitoring**: parent log (path in the launch line above) — it prints one
`[pool] heartbeat: N in flight (name Xh, ...)` line every 15 minutes while it
is waiting, so a frozen log means the PARENT is wedged, not the grid, and a
child listed at >24h gets an explicit WARNING; per-child logs at
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
  --config-name mytest01 --thread-id mytest01
```

- `--x-point v1,v2,...` forces a **designed point** (comma-separated values in
  the mode's knob order) instead of a BO ask — used for A/B arms, replicates,
  and controlled scans. Rows land in the same leaderboard as BO rows.
- Never reuse a `--config-name` that already exists: the collision guard
  silently allocates a fresh auto-incremented name.

`tools/run_grid.sh [config-name] [mode]` is that command with the pre-flight
checks a grid chain actually needs, the same way `tools/run_local.sh` wraps the
local one: it sandboxes `AUTORESEARCH_DATA_ROOT`, borrows an operator's
artifacts, verifies them and `AUTORESEARCH_PRODTOOLS`, refuses a config name
already in a board or carrying stale cluster files, checks the CephFS quota,
and refuses a Kerberos ticket with under 4 h left — a chain submits stages for
hours, so a ticket that merely exists now is not enough. It prints each stage's
grid width read from the mode spec, then runs the chain. Since that takes 3–6 h,
run it detached:

```bash
nohup tools/run_grid.sh gridcheck01 \
  > /exp/mu2e/data/users/$USER/gridtest/gridcheck01.log 2>&1 &
```

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

## Running without the grid

Set `AUTORESEARCH_LOCAL=1` (or pass `submit --local` to `core/pipeline.py`
directly) and every stage runs on this node instead of on the grid — via
prodtools' own `runlocal`, the same tool `submit`'s grid path uses to build
the job, just executed here instead of queued. No `jobsub`, no job queue, no
waiting behind other people's work. It is not offline — jobs still stream
their resampler inputs over xrootd from `/pnfs`, so you need a Kerberos
ticket and read access to the Mu2e datasets, same as a grid worker, and
`AUTORESEARCH_PRODTOOLS` (see [Prerequisites](#prerequisites)) is required
here too — `runlocal` is a prodtools binary. From a bare clone:

```bash
git clone https://github.com/Mu2e/Mu2eBO && cd Mu2eBO
./setup.sh --venv                                     # link the shared venv
./setup.sh --backing /exp/mu2e/app/users/oksuzian     # borrow a built Offline (personal-path-ok: a real operator's)
export AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0   # pinned release; any prodtools checkout works
tools/run_local.sh local01                            # one evaluation, ~20 min
```

`tools/run_local.sh [config-name] [mode]` is the rest of this section made
executable: it sandboxes the run, borrows an operator's artifacts, checks them
before starting, sets a scale that lands a row, prints the resolved roots, and
runs the chain. With no arguments it picks a timestamped config name, so the
command above is genuinely all you type.

Every default is an env override — `AUTORESEARCH_LOCAL_EVENTS=200
tools/run_local.sh smoke01` for a 30 s/stage plumbing check instead, or
`AUTORESEARCH_BACKING=/exp/mu2e/app/users/<someone-else>` to borrow a
different build. The backing it resolved is printed in the status block every
run: you are never on someone's build without seeing whose.

Spelled out, the script is these steps:

```bash
# AUTORESEARCH_PRODTOOLS is assumed already exported (Prerequisites) — runlocal is a prodtools binary
source .venv/bin/activate && source setup.sh          # 3. per-shell, every shell
export AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/$USER/localtest   # 4. sandbox
./setup.sh --status                                   # 5. read this before step 6

AUTORESEARCH_LOCAL=1 python -m graph.run \
  --mode foilspf --config-name local01 --thread-id local01   # 6.
```

Steps 1 and 3 are the [Quick start](#quick-start). Step 2 is not optional
here: `harvest` needs Run1BAna's FCL and sensitivity macro, which no fresh
clone has — without a backing, step 6 refuses at preflight and names the
command to fix it.

**Step 4 is the one thing this recipe adds.** Every path the runner writes
hangs off `$AUTORESEARCH_DATA_ROOT` — grid tree, logs, and your live
leaderboard — so pointing it at a scratch directory keeps a local run out of
the board your real campaigns train on. That matters because the default
scale is **1 job × 200 events per stage**: a plumbing check, not a
measurement, and its row belongs in no GP. (The committed `leaderboards/`
archive is read as priors either way and is never written.)

Step 6 needs no extra flag: `pipeline.py submit` dispatches on
`AUTORESEARCH_LOCAL`, and a graph child inherits it. Each stage's `submit`
shells prodtools `runlocal` under `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/
<config>/<stage>/local/`, and writes the same `<stage>_wait.json` result
contract a grid submit's `jobwait` would — `list-outputs` and `harvest` read
that JSON rather than walking a known directory layout, so they need no
executor-specific code at all.

Raise the scale with:

| variable | default | meaning |
|---|---|---|
| `AUTORESEARCH_LOCAL_NJOBS` | 1 | jobs per stage |
| `AUTORESEARCH_LOCAL_EVENTS` | 200 | events per job |
| `AUTORESEARCH_LOCAL_POOL` | 4 | jobs running concurrently |

Supported stages: `mubeam`, `run1b_mubeam`, `concat`, `mustops_ce`,
`elebeam_flash`. A stage outside that set is refused rather than half-run.

### What a default-scale run gives you — and what it does not

The whole chain above takes about **30 s per stage** at 1 × 200 events, and
ends with a real `harvest/summary.json`: `s_over_sqrt_b`, stop counts,
efficiencies, the CE ntuple. That is the plumbing check, and it is the point.

**It will not append a leaderboard row on a flash mode**, and that is by
design. Flash energy reaches only a few events per thousand (`1.3e-3`–`4.2e-3`
across local geometries, `2.4e-3` across production campaigns), so 200 events
expects well under one — zero, most of the time. `evaluate` refuses to append
a row whose second objective is zero, because that zero would dominate the
Pareto front at the next GP refit. You get an explicit
`scan_logs/evaluate_zero_row.tsv` naming the cause, not a silent skip.

To land a row you need enough events for the flash objective to be nonzero;
the total is `NJOBS × EVENTS` per stage. The script's default 10⁵ landed a row
on every geometry tried, with **41–137 flash events (~9–16% statistical error
on the flash objective, and it varies by geometry — sample it, don't assume
it)**, for about **15 minutes of stages** on 8 cores — measured 169 s / 283 s / 426 s for mubeam /
elebeam_flash / mustops_ce, plus harvest. Per-event cost is far below what the
200-event timing suggests: most of those 30 s is G4 init and geometry load,
paid once per job (~25 s of it, measured across 200 → 10⁴ events per job).

```bash
AUTORESEARCH_LOCAL=1 AUTORESEARCH_LOCAL_NJOBS=8 \
AUTORESEARCH_LOCAL_EVENTS=12500 AUTORESEARCH_LOCAL_POOL=8 \
python -m graph.run --mode foilspf --config-name local02 --thread-id local02
```

Even then the row is far noisier than a grid evaluation (~10⁷ events), which
is the other half of why step 4 keeps it in a sandbox.

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
│   ├── runtime.py           #   non-path runtime tunables: per-mode stage
│   │                        #   chains, closed-loop constants, env seams
│   ├── mode_json.py         #   JSON spec loader/validator (mode_specs/ → SPECS)
│   ├── bo_driver.py         #   propose | evaluate | preflight CLI; BOMode classes
│   ├── botorch_predict.py   #   GP fit + acquisition (all pickers), ask/tell seam
│   ├── pipeline.py          #   grid runner: fork config, render stage_entries
│   │                        #   into a per-config entry, submit/poll/harvest I/O
│   ├── prodtools_exec.py    #   the ONLY module that shells prodtools
│   │                        #   (json2jobdef/submit/jobwait/runlocal)
│   ├── prodtools_submit_driver.py  # CLI driver prodtools_exec.submit_cnf shells out
│   │                        #   to (reserves/attaches a ledger row, calls prodtools' submit_entry)
│   ├── harvest.py           #   metric extraction from grid outputs → Eval summary
│   ├── geom_template.py     #   knob values → rendered Offline geometry file
│   └── pipeline_templates/  #   mubeam/run1b_mubeam extras.fcl (@sequence::
│                            #   overrides no JSON value can express) + shared
│                            #   *Cat.txt input lists — NOT per-stage FCL
│                            #   templates anymore, see stage_entries/ below
├── stage_entries/           # checked-in per-stage json2jobdef entries (fcl +
│                            #   fcl_overrides, inloc/outloc/run/memory/events);
│                            #   THE job description, see mode_specs' stage_tuning
│                            #   for the per-mode runtime knobs layered on top
├── graph/                   # LangGraph orchestration
│   ├── run.py               #   single-evaluation entrypoint (one chain = one graph run)
│   ├── closed_loop.py       #   campaign parent CLI: picker subprocess, krb5
│   │                        #   renewal, STOP flag; drives pool.run_rolling
│   ├── pool.py              #   the parent itself: q children in flight, one
│   │                        #   replacement per exit (no rounds, no barrier)
│   ├── nodes.py             #   graph nodes (propose, preflight, stages, harvest, evaluate)
│   ├── build.py / state.py  #   graph wiring + typed state
│   ├── pipeline_io.py       #   proposal/leaderboard file I/O, name allocation
│   └── sourced_bash.py      #   env-sourcing subprocess helper
├── mode_specs/              # JSON mode definitions (see its README)
├── leaderboards/            # READ-ONLY archive of past campaigns; live rows go
│                            #   to $AUTORESEARCH_DATA_ROOT (see Where your results go)
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
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t . -v
```

595 tests (1 skipped), no grid contact. The golden geometry-parity harness (renders
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
