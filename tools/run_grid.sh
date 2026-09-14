#!/bin/bash
# One evaluation, on the grid. The grid sibling of tools/run_local.sh: same
# chain, same checks, jobs queued through jobsub instead of run on this node.
#
#   tools/run_grid.sh [config-name] [mode]
#
# With no arguments: a timestamped config name and mode foilspf. Scale is NOT
# a knob here -- a grid stage runs at its mode's own production width, which
# is the point of using the grid (core/launch_checks.py prints the widths it
# read from the spec). The one exception is the long-standing
# AUTORESEARCH_ELEBEAM_NJOBS seam, honoured if you export it.
#
# Expect ~3-6 h wall clock, most of it queued behind other people's jobs. The
# chain is a foreground process that must outlive your shell, so run it under
# nohup and watch the log:
#
#   nohup tools/run_grid.sh gridcheck01 \
#       > /exp/mu2e/data/users/$USER/gridtest/gridcheck01.log 2>&1 &
set -eo pipefail

CONFIG="${1:-grid$(date +%m%d%H%M%S)}"
MODE="${2:-foilspf}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# A scratch DATA_ROOT keeps a test run's rows, outputs, and logs out of the
# board your real campaigns train on. Point it at your real root when the run
# IS a real evaluation. BACKING defaults to the published operator area so a
# first run needs no arguments; ./setup.sh --status prints what it resolved,
# so you are never on someone else's build without seeing whose.
export AUTORESEARCH_DATA_ROOT="${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER/gridtest}"
export AUTORESEARCH_BACKING="${AUTORESEARCH_BACKING:-/exp/mu2e/app/users/oksuzian}"  # personal-path-ok: the published artifact area, see README

# Resolves $AUTORESEARCH_PYTHON: the published cvmfs env by default,
# AUTORESEARCH_VENV=<path> for a local dev venv. Never activates --
# see activate.sh for why an exported `python` wrapper would poison
# the harvest steps that run PyROOT under `muse setup`.
source activate.sh || exit 2
source setup.sh
./setup.sh --status

# Kerberos life, name collisions, stale cluster files, quota, artifacts and
# prodtools -- every gate that has to fire before a job is queued, in one
# tested module rather than inline bash (tests/test_launch_checks.py).
PYTHONPATH= "$AUTORESEARCH_PYTHON" core/launch_checks.py \
    --mode "$MODE" --config "$CONFIG" --grid || exit 2

echo "run_grid: config=$CONFIG mode=$MODE  (grid; expect 3-6 h)"

exec "$AUTORESEARCH_PYTHON" -m graph.run --mode "$MODE" \
    --config-name "$CONFIG" --thread-id "$CONFIG"
