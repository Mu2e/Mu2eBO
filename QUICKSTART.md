# Quick start

How to install and run the autoresearch framework (closed-loop Bayesian
optimization of Mu2e geometry). This is the one how-to; `README.md` is the
overview, `mode_specs/README.md` the study format, `wiki/` the background.

## 0. What you need

- **A Mu2e interactive node** (mu2esrv01 or a mu2egpvm) with `/cvmfs`
  mounted.
- **A Kerberos ticket** (`kinit`), and a grid account in the mu2e group for
  grid runs.
- **Space for runtime data** (boards, point state, logs). It goes under
  `$AUTORESEARCH_DATA_ROOT`, by default `/exp/mu2e/data/users/$USER`.
- **No Python install.** `activate.sh` uses the published `/cvmfs` env
  `ana 2.8.0` (`AUTORESEARCH_VENV=/path/to/venv` swaps in a dev venv).

## 1. Install (once)

The framework is the main repo plus four sibling checkouts in one
directory. `activate.sh` finds each one by its directory name; export
`AUTORESEARCH_SURROKIT`, `AUTORESEARCH_PRODTOOLS`, `AUTORESEARCH_ANAKIT` or
`AUTORESEARCH_BEAMKIT` to use a checkout somewhere else.

```bash
cd /exp/mu2e/app/users/$USER

# the framework
git clone https://github.com/Mu2e/Mu2eBO.git autoresearch

# surrokit: the GP / Bayesian-optimization engine (pinned)
git clone https://github.com/oksuzian/surrokit.git surrokit
git -C surrokit checkout 26929f7      # = SURROKIT_PIN_SHA in core/paths.py

# prodtools: builds and submits each step's Geant4 jobs (grid or local)
git clone https://github.com/Mu2e/prodtools.git prodtools
bash prodtools/mcp/scripts/install.sh       # its MCP venv

# anakit: M. MacKenzie's analysis server, run by the *_ax studies and ce_chain (pinned)
git clone https://github.com/michaelmackenzie/analysis-mcp-server.git analysis-mcp-server
git -C analysis-mcp-server switch --detach 3ba8d23   # = ANAKIT_PIN_SHA in core/adapters/anakit.py

# beamkit: the G4beamline kit for ptg4bl
git clone -b v1 https://github.com/oksuzian/beamkit.git beamkit
# its venv needs Python >= 3.10; the system python3 is 3.9
/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m venv beamkit/.venv
env -u PYTHONPATH beamkit/.venv/bin/pip install -e beamkit

# borrow a built Offline and the grid code tarballs
cd autoresearch
source ./activate.sh
./setup.sh --backing /exp/mu2e/app/users/oksuzian
./setup.sh --status                   # shows every root and whose build
```

A fresh clone has no build; every run refuses until `--backing` links one.
The backing's files are world-readable, so you build nothing.

Check the install. This runs the test suite: about 10 minutes, with no
grid jobs.

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
```

For Claude Code: `.mcp.json` registers the `autoresearch` server (study
and campaign tools) and the `surrogate` server (GP predictions). After any
update, run `/mcp` in the session to reload them.

> **Still in one person's area:** the backing (`/exp/mu2e/app/users/oksuzian`)
> and the DIO table `approx_ce_sensitivity` reads (M. MacKenzie's `Run1BAna/data/`).
> Last tested 2026-10-07: a local `ce_chain` point gives n_selected 40, efficiency 0.975.

## 2. Every new shell

```bash
cd /exp/mu2e/app/users/$USER/autoresearch
source ./activate.sh
export AUTORESEARCH_DATA_ROOT=${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER}
kinit                                 # a grid launch needs >= 4 h left
```

Local runs need the ticket too: their jobs read inputs from `/pnfs` over
xrootd.

## 3. Check a study before running it

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study foilspfbpz_ax
```

It checks that the file loads, that its input paths exist, the launch
checks, and a 1-event geometry pre-check at the centre of the knob box.
It submits nothing. Exit 0 means every check passed.

The studies are `mode_specs/<name>.json`:
- the stopping-target studies `foilsflash_ax` and `foilspfbpz_ax`, and
  `foilspf_nominal` (the deployed target, their baseline);
- `ce_chain`;
- `ptg4bl`.

To write a new study, see `mode_specs/README.md` ("From draft to launch").

## 4. Run one point

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study foilspfbpz_ax \
    --config my001 --campaign my --x=<v1,...,v10> \
    --context alpha=100000 --executor grid      # or: --executor local --parallel 4
```

`--x` gives the knob values in the study's order; a study with no knobs
omits it. `--parallel` (1..16) works only with `--executor local`. Exit
codes:
- 0 means a leaderboard row landed, or `state/broken.txt` says why not;
- 2 means it was refused before anything ran.

## 5. Run a campaign

Dry run first. It runs every launch check and launches nothing:

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop --study foilspfbpz_ax \
    --q 20 --max-evals 40 --picker budget_sob --name-prefix bpz09 \
    --context alpha=100000 --executor grid --check-only
```

Then launch it detached:

```bash
GD=$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data
mkdir -p "$GD"
PYTHONPATH= setsid nohup "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop \
    --study foilspfbpz_ax --q 20 --max-evals 40 --picker budget_sob \
    --name-prefix bpz09 --context alpha=100000 --executor grid \
    > $GD/bpz09_parent.log 2>&1 &
```

The campaign keeps `--q` points in flight and launches one replacement
each time one ends; the GP refits against the board before each pick. The
pickers are `qnehvi`, `qlnei` (one objective), `budget_sob` and `hybrid`.
Use a new `--name-prefix` for each campaign.

To stop launching (the running points finish):

```bash
touch $GD/bpz09/STOP
```

From Claude Code you can do the same with the `autoresearch` tools:
`start_campaign` (dry run, then `confirm=true`), `stop_campaign`,
`campaign_status` and `leaderboard`.

## 6. Follow it

- **Campaign record:** `$GD/<prefix>/campaign.json` has the settings, host
  and exit code. `$GD/<prefix>/outcomes.jsonl` has one line per finished
  point. `parent.lock` is held while the campaign runs.
- **Point logs:** `$GD/closed_loop_logs/<point>.log`.
- **Point state:** `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<point>/state/`:
  `point.json`, each step's `<step>_submit.json`, `_cluster.txt`,
  `_status.json` and `_results.json`, and `broken.txt`, which says why a point failed.
  `run.lock` is held while the point runs: `flock -n .../state/run.lock true`
  fails during that time. The geometry pre-check log is
  `.../<point>/preflight/preflight.log`.
- **Grid queue:** `jobsub_q -G mu2e --user=$USER`.
- **Dashboard:** a live flow graph of every campaign (points, steps,
  results), rebuilt from the records every 2 minutes. Start it on the node
  the campaigns run on:

  ```bash
  D=$AUTORESEARCH_DATA_ROOT/autoresearch_dashboard; mkdir -p "$D"
  PYTHONPATH= setsid nohup "$AUTORESEARCH_PYTHON" -u -m service.dashboard \
      >> "$D/dashboard.log" 2>&1 &
  ```

  Then `ssh -L 8765:localhost:8765 <node>` and open `http://localhost:8765`.
  `--once` writes one snapshot and exits.

## 7. Results

The leaderboards are
`$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/<file>.tsv`, one row
per point, best first through the `leaderboard` tool. The GP picks its next
points from the board as it stands. The committed `leaderboards/` is a
read-only archive of old boards.

A board holds one measurement. A launch is refused when the study's
measurement or a kit's version changed. Kit versions are bumped by hand
(see `mode_specs/README.md`).
