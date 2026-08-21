#!/bin/bash
# One evaluation, no grid. The README section "Running without the grid",
# executable. Prints the resolved roots before it runs anything.
#
#   tools/run_local.sh [config-name] [mode]
#
# With no arguments: a timestamped config name and mode foilspf. Override any
# default below from the command line, e.g.
#   AUTORESEARCH_LOCAL_EVENTS=200 tools/run_local.sh smoke01
set -eo pipefail

CONFIG="${1:-local$(date +%m%d%H%M%S)}"
MODE="${2:-foilspf}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# A scratch DATA_ROOT keeps a local run's rows, outputs, and logs out of the
# board your real campaigns train on. Set it BEFORE setup.sh, which re-exports
# whatever paths.py resolved. BACKING defaults to the published operator area
# so a first run needs no arguments at all; anything explicit wins, including
# a `backing` symlink in the repo (which paths.py prefers over the env var).
export AUTORESEARCH_DATA_ROOT="${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER/localtest}"
export AUTORESEARCH_BACKING="${AUTORESEARCH_BACKING:-/exp/mu2e/app/users/oksuzian}"  # personal-path-ok: the published artifact area, see README

# 8 x 12500 = 1e5 events per stage: enough for a nonzero flash objective, so a
# row actually lands. ~15 min of stages on 8 cores, ~20 min end to end. Drop to
# 1 x 200 for a 30 s/stage plumbing check that deliberately lands no row.
export AUTORESEARCH_LOCAL=1
export AUTORESEARCH_LOCAL_NJOBS="${AUTORESEARCH_LOCAL_NJOBS:-8}"
export AUTORESEARCH_LOCAL_EVENTS="${AUTORESEARCH_LOCAL_EVENTS:-12500}"
export AUTORESEARCH_LOCAL_POOL="${AUTORESEARCH_LOCAL_POOL:-8}"

source .venv/bin/activate
source setup.sh
./setup.sh --status

# Kerberos, name collisions, artifacts and prodtools -- the same tested module
# run_grid.sh uses, minus the gates only a queued chain needs
# (tests/test_launch_checks.py). Local jobs submit nothing but still stream
# resampler inputs from /pnfs over xrootd, so they need a ticket too.
PYTHONPATH= python core/launch_checks.py \
    --mode "$MODE" --config "$CONFIG" || exit 2

echo "run_local: config=$CONFIG mode=$MODE" \
     "scale=${AUTORESEARCH_LOCAL_NJOBS}x${AUTORESEARCH_LOCAL_EVENTS}"

exec python -m graph.run --mode "$MODE" \
    --config-name "$CONFIG" --thread-id "$CONFIG"
