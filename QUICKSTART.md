# Quick start

How to install and run the autoresearch framework (closed-loop Bayesian
optimization of Mu2e geometry). The details are in `README.md`,
`mode_specs/README.md` and `wiki/`.

## 0. What you need

- **A Mu2e interactive node** (mu2esrv01 or a mu2egpvm) with `/cvmfs`
  mounted.
- **A Kerberos ticket** (`kinit`), and a grid account in the mu2e group for
  grid runs.
- **Space under `/exp/mu2e/data/users/$USER`.** All runtime data goes there:
  boards, point state and logs. Set `AUTORESEARCH_DATA_ROOT` to use
  another place.
- **No Python install.** `activate.sh` uses the published `/cvmfs` env
  `ana 2.8.0`.

## 1. Install (once)

The framework is the main repo plus four sibling checkouts in one
directory. `activate.sh` finds each one by its directory name.

```bash
cd /exp/mu2e/app/users/$USER

# the framework
git clone -b generic-study-phase-c1 https://github.com/oksuzian/Mu2eBO.git autoresearch

# surrokit: the GP / Bayesian-optimization engine (pinned)
git clone https://github.com/oksuzian/surrokit.git surrokit
git -C surrokit checkout 26929f7      # = SURROKIT_PIN_SHA in core/paths.py

# prodtools: submits the grid (or local) Geant4 jobs
mkdir -p muse_050125
git clone https://github.com/Mu2e/prodtools.git muse_050125/prodtools
bash muse_050125/prodtools/mcp/scripts/install.sh       # its MCP venv

# anakit: the analysis kit for the *_ax studies (fork, branch autoresearch)
git clone -b autoresearch https://github.com/oksuzian/analysis-mcp-server.git analysis-mcp-server

# beamkit: the G4beamline kit for ptg4bl
git clone -b v1 https://github.com/oksuzian/beamkit.git beamkit
python3 -m venv beamkit/.venv
env -u PYTHONPATH beamkit/.venv/bin/pip install -e beamkit

# borrow a built Offline, the grid code tarballs and the anakit work area
cd autoresearch
source ./activate.sh
./setup.sh --backing /exp/mu2e/app/users/oksuzian
./setup.sh --status                   # shows every root and whose build
```

Check the install. This runs the test suite: about 10 minutes, with no
grid jobs.

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .
```

For Claude Code: `.mcp.json` registers the `autoresearch` server (study
and campaign tools) and the `surrogate` server (GP predictions). After any
update, run `/mcp` in the session to reload them.

> **Still shared from one person's area (2026-10-06):**
> - **The backing.** `setup.sh --backing` points at
>   `/exp/mu2e/app/users/oksuzian`: the built Offline, the grid code
>   tarballs, and the anakit work area `autoresearch_muse_ax`. That work area
>   carries a local Mu2eOptAna branch. All of it is world-readable, but it
>   lives in a personal area until it moves to a shared Mu2e location.
> - **The anakit fork.** Until `oksuzian/analysis-mcp-server` (branch
>   `autoresearch`) is published, copy `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`.
>
> Tested on 2026-10-06 against upstream `Mu2e/prodtools` `main`: a local
> `ce_chain` point ran end to end (median |p| 104.022, the same as on the
> development checkout).

## 2. Every new shell

```bash
cd /exp/mu2e/app/users/$USER/autoresearch
source ./activate.sh
kinit                                 # a grid launch needs >= 4 h left
```

## 3. Check a study before running it

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study foilspfbpz_ax
```

It checks that the file loads, that its input paths exist, the launch
checks, and a 1-event geometry pre-check at the centre of the knob box.
It submits nothing. Exit 0 means every check passed.

The studies are `mode_specs/<name>.json`:
- the seven stopping-target `*_ax` studies;
- `ce_chain`;
- `ptg4bl`.

To write a new study, see `mode_specs/README.md` ("From draft to launch").

## 4. Run one point

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study foilspfbpz_ax \
    --config my001 --campaign my --x=<v1,...,v10> \
    --context alpha=100000 --executor grid      # or: --executor local --parallel 4
```

`--x` gives the knob values in the study's order. Exit codes:
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
GD=/exp/mu2e/data/users/$USER/autoresearch_graph_data
PYTHONPATH= setsid nohup "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop \
    --study foilspfbpz_ax --q 20 --max-evals 40 --picker budget_sob \
    --name-prefix bpz09 --context alpha=100000 --executor grid \
    > $GD/bpz09_parent.log 2>&1 &
```

The pickers are `qnehvi`, `qlnei` (one objective), `budget_sob` and
`hybrid`. Use a new `--name-prefix` for each campaign.

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
  point.
- **Point logs:** `$GD/closed_loop_logs/<point>.log`.
- **Point state:**
  `/exp/mu2e/data/users/$USER/autoresearch_grid/<point>/state/`.
  `broken.txt` says why a point failed. `run.lock` is held while the point
  runs: `flock -n .../state/run.lock true` fails during that time.
- **Grid queue:** `jobsub_q -G mu2e --user=$USER`.
- **Dashboard:** see README, "Dashboard".

## 7. Results

The leaderboards are
`/exp/mu2e/data/users/$USER/autoresearch_leaderboards/<file>.tsv`, one row
per point, best first through the `leaderboard` tool. The GP picks its next
points from the board as it stands.

A board holds one measurement. A launch is refused when the study's
measurement or a kit's version changed. Kit versions are bumped by hand
(see `mode_specs/README.md`).

## 8. Once, after updating to 2026-10-05 or later

Boards measured before that date carry the old kit version strings.
First prove they changed only by build, with a dry run:

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.restamp_board --study foilspfbpz_ax \
    --why "the anakit fork moved; no analysis number changed"
```

Then rewrite the board, which keeps a backup and a log line next to it:

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.restamp_board --study foilspfbpz_ax \
    --why "the anakit fork moved; no analysis number changed" --confirm
```

Do the same for `ptg4bl`. Run it with no campaign running.
