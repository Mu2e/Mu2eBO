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
# whatever paths.py resolved.
export AUTORESEARCH_DATA_ROOT="${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER/localtest}"

# Artifacts you did not build: default to the published operator area so a
# first run needs no arguments at all. Not silent -- ./setup.sh --status below
# prints the backing it resolved, so you always see whose build you are on.
# Anything explicit wins: your own env value, or a `backing` symlink in the
# repo (which paths.py prefers over the env var).
export AUTORESEARCH_BACKING="${AUTORESEARCH_BACKING:-/exp/mu2e/app/users/oksuzian}"  # personal-path-ok: the published artifact area, see README

# 8 x 12500 = 1e5 events per stage: enough for a nonzero flash objective, so a
# row actually lands. ~15 min of stages on 8 cores, ~20 min end to end. Drop to
# 1 x 200 for a 30 s/stage plumbing check that deliberately lands no row.
export AUTORESEARCH_LOCAL=1
export AUTORESEARCH_LOCAL_NJOBS="${AUTORESEARCH_LOCAL_NJOBS:-8}"
export AUTORESEARCH_LOCAL_EVENTS="${AUTORESEARCH_LOCAL_EVENTS:-12500}"
export AUTORESEARCH_LOCAL_POOL="${AUTORESEARCH_LOCAL_POOL:-8}"

# Local jobs still read their resampler inputs over xrootd from /pnfs, so they
# need a live bearer token exactly as a grid worker does. Without a ticket the
# failure is "Auth failed: No protocols left to try" ~300 lines into a job log.
if ! klist -s 2>/dev/null; then
    echo "run_local: no valid Kerberos ticket -- run kinit first." \
         "Local jobs stream resampler inputs from /pnfs over xrootd." >&2
    exit 2
fi

# A name already in a board or pending file makes propose_one raise, which
# langgraph reports as ~30 lines of traceback after the run has already
# started. Same check, one line, before anything runs.
if grep -qsE "^${CONFIG}[[:space:]]" \
        "$AUTORESEARCH_DATA_ROOT"/autoresearch_leaderboards/*.tsv \
        leaderboards/*.tsv 2>/dev/null; then
    echo "run_local: config name '$CONFIG' is already used -- pick another," \
         "or pass no argument for a timestamped one" >&2
    exit 2
fi

source .venv/bin/activate
source setup.sh
./setup.sh --status

# Prerequisites, before anything runs, each resolved by the module that owns
# it rather than re-derived here. Artifacts: a miss otherwise surfaces three
# preflight retries later as a bare "ambiguous", and `./setup.sh --backing`
# -- what the error suggests -- itself fails when the checkout is not yours.
# AUTORESEARCH_PRODTOOLS: unset or pointing somewhere without bin/json2jobdef
# otherwise dies minutes in, from deep inside the first stage submit -- every
# job, local ones too, is built and run by prodtools binaries. Both cases are
# prodtools_root()'s to word, and it raises SystemExit, not PathsError.
PYTHONPATH= python - "$MODE" <<'PY' || exit 2
import sys
sys.path.insert(0, "core")
import harvest, modes, paths
try:
    paths.verify([modes.SPECS[sys.argv[1]]],
                 extra=harvest.REQUIRED_ARTIFACTS, make_dirs=False)
    paths.prodtools_root()
except (paths.PathsError, SystemExit) as e:
    print(f"run_local: {e}", file=sys.stderr)
    sys.exit(2)
PY
echo "run_local: config=$CONFIG mode=$MODE" \
     "scale=${AUTORESEARCH_LOCAL_NJOBS}x${AUTORESEARCH_LOCAL_EVENTS}"

exec python -m graph.run --mode "$MODE" \
    --config-name "$CONFIG" --thread-id "$CONFIG" --no-mock
