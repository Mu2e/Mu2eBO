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
directory. `activate.sh` finds each one by its directory name (prodtools
also inside a Muse work area, `../muse_050125/prodtools`); export
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

Builds (the Offline work area, the code tarballs) are looked up first in
your own area (`$AUTORESEARCH_ARTIFACT_ROOT`, by default
`/exp/mu2e/app/users/$USER`), then in the backing. A new user's area holds
none, so every run refuses until `--backing` links one. The backing's
files are world-readable, so you build nothing. `--status` lists the roots
but not the kit checkouts: after `source ./activate.sh`,
`echo $AUTORESEARCH_PRODTOOLS $AUTORESEARCH_ANAKIT $AUTORESEARCH_BEAMKIT`
shows which it found (a kit it did not find stays unset, and a run that
needs it refuses).

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

The foils studies' Geant4 jobs run on SimJob MDC2025ax (their code
tarball's Musing); their analyses run on SimJob MDC2025ay, which a launch
check prints as `mu2e jobs will run against musing SimJob MDC2025ay`.

To write a new study, see `mode_specs/README.md` ("From draft to launch").

## 4. Run one point

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study foilspfbpz_ax \
    --config my001 --campaign my --x=<v1,...,v10> \
    --context alpha=100000 --executor grid      # or: --executor local --parallel 4
```

`--x` gives the knob values in the study's order; a study with no knobs
(`ce_chain`, `foilspf_nominal`) omits it. `--context` is needed only for
the names in the study's `leaderboard.context` (the `_ax` studies:
`alpha`). `--parallel` (1..16) works only with `--executor local`. For
example, a local `ce_chain` point (about 8 minutes):

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study ce_chain \
    --config my002 --campaign my --executor local --parallel 4
```

It prints a `[steps]` line as each step moves on; each step's state is
also in `state/<step>_status.json` (§7). Exit codes:
- 0 means a leaderboard row landed, or `state/broken.txt` says why not;
- 2 means it was refused before anything ran.

## 5. Run a campaign

Dry run first. It runs every launch check, launches nothing and ends with
`[closed_loop] OK: would launch ...` (it leaves only a `kit_trace.jsonl` in
`$GD/<prefix>/`). The MCP `start_campaign` dry run also shows the grid-job
budget.

```bash
PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop --study foilspfbpz_ax \
    --q 20 --max-evals 40 --picker budget_sob --name-prefix bpz09 \
    --context alpha=100000 --executor grid --check-only
```

Then launch it detached:

```bash
GD=$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data
mkdir -p "$GD/bpz09"
PYTHONPATH= setsid nohup "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop \
    --study foilspfbpz_ax --q 20 --max-evals 40 --picker budget_sob \
    --name-prefix bpz09 --context alpha=100000 --executor grid \
    > $GD/bpz09/parent.log 2>&1 &
```

The campaign keeps `--q` points in flight and launches one replacement
each time one ends; the GP refits against the board before each pick. `--max-evals` counts the points this campaign launches; the board's
existing rows only inform the GP. Use a new `--name-prefix` for each
campaign, also to continue one that was stopped or crashed: the board
keeps every row, so the new campaign picks up where it left off. Which
picker:
- `foilspfbpz_ax`, `foilsflash_ax`: `budget_sob`, the best sob the GP
  predicts within the flash damage budget (the study's constraint);
  `qnehvi` or `hybrid` to explore the whole sob-flash front instead;
- `ptg4bl`: `qlnei` (one objective);
- `ce_chain`, `foilspf_nominal`: no knobs, so run them as one point (§4),
  not as a campaign.

To stop launching (the running points finish):

```bash
touch $GD/bpz09/STOP
```

From Claude Code you can do the same with the `autoresearch` tools:
`start_campaign` (dry run, then `confirm=true`), `stop_campaign`,
`campaign_status` and `leaderboard`.

## 6. On the grid

- **Credentials.** A grid submit needs only your Kerberos ticket: jobsub
  turns it into a grid token itself (`htgettoken`). A launch is refused
  with under 4 h left, and nothing renews the ticket for you, so a
  campaign that outlives it dies at its next submit. `klist` shows the
  end time and `renew until`. Before the end, run `kinit -R` (no password)
  until the `renew until` time (typically a week), then a new `kinit`.
- **Stop.** `touch $GD/<prefix>/STOP` (or `stop_campaign`) stops new
  launches only; points in flight run to the end, grid jobs included. To
  end them now, remove their jobs: `jobsub_q -G mu2e --user=$USER` lists
  them, `jobsub_rm -G mu2e --jobid <cluster>@<schedd>` removes a whole
  step. A prodtools step's job id is `metadata.jobid` in
  `autoresearch_grid/<point>/prodtools/<step>/record.json`
  (`<cluster>.0@<schedd>`; drop the `.0` for the whole cluster).
- **Slow jobs.** A step waits until every one of its jobs has ended (done,
  failed or removed), then passes if enough of them succeeded:
  `ok / njobs >= quorum`, the step's `quorum` (0.8 in the foils studies:
  12 of 15, 80 of 100). A few jobs still running hours after the rest
  can be removed one by one (`--jobid <cluster>.<n>@<schedd>`); the step
  then completes on the others if the quorum holds. A step whose status
  stays unreadable for 6 h fails.
- **A failed point.** `state/broken.txt` names the step and the reason;
  the point's log `$GD/closed_loop_logs/<point>.log` has the detail. If
  the step failed before anything ran (the geometry pre-check, a kit that
  would not start), fix the cause, remove `broken.txt` and rerun the same
  `graph.run` command (`state/point.json` holds its arguments). A step
  the kit itself judged failed stays failed under that name: run the x
  again under a new `--config`.
- **Disk.** Grid outputs go to `/pnfs/mu2e/scratch/users/$USER/workflow/`
  (scratch: old files are purged). Each point keeps about 50 MB under
  `$AUTORESEARCH_DATA_ROOT`, so about 2 GB for a 40-point campaign. On
  CephFS `df` is wrong; use
  `getfattr -n ceph.dir.rbytes $AUTORESEARCH_DATA_ROOT` (used) and
  `-n ceph.quota.max_bytes` (quota).
- **From Claude Code.** With its Bash sandbox on, `kinit`, `htgettoken`
  and `jobsub_q` fail (no DNS inside it): list them in the sandbox's
  `excludedCommands` or keep the sandbox off
  ([wiki](wiki/concepts/claude-code-sandbox-grid-tools.md)).

## 7. Follow it

- **Campaign record:** `$GD/<prefix>/campaign.json` has the settings, host
  and exit code. `$GD/<prefix>/outcomes.jsonl` has one line per finished
  point. `parent.lock` is held while the campaign runs. The parent's log
  is `$GD/<prefix>/parent.log`.
- **Point logs:** `$GD/closed_loop_logs/<point>.log` for a campaign's
  points; a point run by hand (§4) logs only to its own output.
- **Point state:** `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<point>/state/`:
  `point.json`, each step's `<step>_submit.json`, `_cluster.txt`,
  `_status.json` and `_results.json`, and `broken.txt`, which says why a point failed.
  `run.lock` is held while the point runs: `flock -n .../state/run.lock true`
  fails during that time. A study with a geometry pre-check (the foils
  studies) logs it to `.../<point>/preflight/preflight.log`.
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
  `--once` writes one snapshot (`$D/index.html`) and exits.

## 8. Results

The leaderboards are
`$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/<file>.tsv`, one row
per point, best first through the `leaderboard` tool. `<file>` is the
study's `leaderboard.file` (for example
`leaderboard_bo_foilspfbpz_ax_upstream.tsv`):
`grep '"file"' mode_specs/<study>.json` shows it. The GP picks its next
points from the board as it stands. The committed `leaderboards/` is a
read-only archive of old boards.

A board holds one measurement. A launch is refused when the study's
measurement or a kit's version changed. Kit versions are bumped by hand
(see `mode_specs/README.md`).
