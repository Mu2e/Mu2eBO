#!/bin/bash
# Local-executor smoke: build one mubeam FCL in a throwaway config, then run it.
#   tools/local_smoke.sh [config] [source-config]
# Do NOT `muse setup` first -- pipeline.py builds its own env, and muse setup
# is one-shot per shell.
set -euo pipefail

CFG=${1:-localsmoke01}
SRC_CFG=${2:-foilspfbpz07R00_08}
GRID=/exp/mu2e/data/users/$USER/autoresearch_grid
SRC=$GRID/$SRC_CFG
DST=$GRID/$CFG
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

pl() { PYTHONPATH= "$REPO/.venv/bin/python" "$REPO/core/pipeline.py" --config "$CFG" "$@"; }
die() { echo "$*" >&2; exit 1; }

[[ -z ${MUSE_WORK_DIR:-} ]] || die "muse already set up in this shell; use a fresh one"
# local-run overwrites the cluster id and the events-per-job stamp harvest reads
[[ -f $DST/state/mubeam_cluster.txt && ! -f $DST/state/mubeam_local.txt ]] \
    && die "$CFG holds a real grid cluster id; pick another name"

mkdir -p "$DST/geom" "$DST/state"
# Copy the geom only if it differs: a fresh mtime invalidates the Code tarball
# cache (which must be newer), costing a 7-12 min repack on every re-run.
cmp -s "$SRC/geom/autoresearch_${SRC_CFG}_geom.txt" "$DST/geom/autoresearch_${CFG}_geom.txt" \
    || cp "$SRC/geom/autoresearch_${SRC_CFG}_geom.txt" "$DST/geom/autoresearch_${CFG}_geom.txt"
cp -n "$SRC"/Code.*.tar.bz2 "$DST/" 2>/dev/null || true   # after the geom, same reason

pl local-build mubeam
cat "$DST/state/fcl/mubeam_00000.fcl"

read -rp "run it? [y/N] " ans
[[ ${ans:-} == y ]] || exit 0
pl local-run mubeam

cat "$DST/state/mubeam_outputs.txt"
echo "clean up: rm -rf /exp/mu2e/data/users/$USER/autoresearch_local/$CFG $DST"
