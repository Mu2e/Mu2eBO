#!/bin/bash
# One evaluation, on the grid. The grid sibling of tools/run_local.sh: same
# chain, same checks, jobs queued through jobsub instead of run on this node.
#
#   tools/run_grid.sh [config-name] [mode]
#
# With no arguments: a timestamped config name and mode foilspf. Scale is NOT
# a knob here -- a grid stage runs at its mode's own production width (foilspf:
# mubeam 15 x 200k, mustops_ce 15 x 75k, elebeam_flash 100 x 110k), which is
# the point of using the grid. The one exception is the long-standing
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
# board your real campaigns train on -- same seam and same reasoning as
# run_local.sh. Point it at your real root when the run IS a real evaluation.
export AUTORESEARCH_DATA_ROOT="${AUTORESEARCH_DATA_ROOT:-/exp/mu2e/data/users/$USER/gridtest}"

# Artifacts you did not build: default to the published operator area so a
# first run needs no arguments. ./setup.sh --status below prints what it
# resolved, so you are never on someone's build without seeing whose.
export AUTORESEARCH_BACKING="${AUTORESEARCH_BACKING:-/exp/mu2e/app/users/oksuzian}"  # personal-path-ok: the published artifact area, see README

# Kerberos: grid submission needs a ticket, and so does every later stage --
# this chain submits over HOURS, not once at the start. A ticket that expires
# mid-run kills the chain at the next submit
# (wiki/incidents/kerberos-mid-run-expiry.md), and the new prodtools input
# gate reports the auth failure as "absent from dCache tape", which reads as
# missing data rather than an expired ticket. Check the REMAINING life, not
# just validity: anything under 4 h will not survive the chain.
if ! klist -s 2>/dev/null; then
    echo "run_grid: no valid Kerberos ticket -- run kinit first." >&2
    exit 2
fi
if command -v klist >/dev/null && klist 2>/dev/null | grep -q krbtgt; then
    exp_epoch=$(date -d "$(klist | awk '/krbtgt/ {print $3" "$4}' | head -1)" +%s 2>/dev/null || echo 0)
    now_epoch=$(date +%s)
    if [ "$exp_epoch" -gt 0 ] && [ $((exp_epoch - now_epoch)) -lt 14400 ]; then
        echo "run_grid: Kerberos ticket has under 4 h left" \
             "(expires $(date -d @"$exp_epoch" '+%F %H:%M')) -- a grid chain" \
             "submits stages for hours and will die at a later submit." \
             "Run 'kinit' before launching." >&2
        exit 2
    fi
fi

# A name already in a board or pending file makes propose_one raise, which
# langgraph reports as ~30 lines of traceback after the run has already
# started -- and on the grid path, after jobs are already queued.
if grep -qsE "^${CONFIG}[[:space:]]" \
        "$AUTORESEARCH_DATA_ROOT"/autoresearch_leaderboards/*.tsv \
        leaderboards/*.tsv 2>/dev/null; then
    echo "run_grid: config name '$CONFIG' is already used -- pick another," \
         "or pass no argument for a timestamped one" >&2
    exit 2
fi

# Stale cluster files under this config silently make a re-run adopt the old
# cluster ids instead of submitting
# (wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md).
if compgen -G "$AUTORESEARCH_DATA_ROOT/autoresearch_grid/$CONFIG/state/*_cluster.txt" >/dev/null; then
    echo "run_grid: '$CONFIG' already has cluster files under" \
         "$AUTORESEARCH_DATA_ROOT/autoresearch_grid/$CONFIG/state/ --" \
         "pick a fresh name rather than resuming by accident" >&2
    exit 2
fi

# Grid runs accumulate a per-config code tarball plus every stage's outputs.
# A full /exp/mu2e/data quota surfaces as Errno 122 EDQUOT from inside a
# stage submit, hours in (wiki/incidents/data-quota-exhausted-grid-accumulation.md).
# CephFS: read the xattrs, never df.
quota=$(getfattr -n ceph.quota.max_bytes --only-values \
        "/exp/mu2e/data/users/$USER" 2>/dev/null || echo 0)
used=$(getfattr -n ceph.dir.rbytes --only-values \
       "/exp/mu2e/data/users/$USER" 2>/dev/null || echo 0)
if [ "$quota" -gt 0 ] && [ "$used" -gt 0 ]; then
    pct=$((used * 100 / quota))
    printf 'run_grid: /exp/mu2e/data/users/%s at %d%% of quota (%.2f of %.2f TB)\n' \
        "$USER" "$pct" \
        "$(echo "$used" | awk '{print $1/1e12}')" \
        "$(echo "$quota" | awk '{print $1/1e12}')"
    if [ "$pct" -ge 90 ]; then
        echo "run_grid: over 90% -- free space before launching; a full quota" \
             "fails as Errno 122 from inside a stage submit, hours in." >&2
        exit 2
    fi
fi

source .venv/bin/activate
source setup.sh
./setup.sh --status

# Prerequisites, each resolved by the module that owns it rather than
# re-derived here. Artifacts: a miss otherwise surfaces three preflight
# retries later as a bare "ambiguous". AUTORESEARCH_PRODTOOLS: unset or
# pointing somewhere without bin/json2jobdef otherwise dies from deep inside
# the first stage submit -- prodtools builds and submits every job.
PYTHONPATH= python - "$MODE" <<'PY' || exit 2
import sys
sys.path.insert(0, "core")
import harvest, modes, paths
try:
    paths.verify([modes.SPECS[sys.argv[1]]],
                 extra=harvest.REQUIRED_ARTIFACTS, make_dirs=False)
    paths.prodtools_root()
except (paths.PathsError, SystemExit) as e:
    print(f"run_grid: {e}", file=sys.stderr)
    sys.exit(2)
PY

# The per-stage grid width, read from the mode spec rather than restated, so
# this line cannot drift from what actually gets submitted.
PYTHONPATH= python - "$MODE" <<'PY'
import sys
sys.path.insert(0, "core")
import modes
spec = modes.SPECS[sys.argv[1]]
width = ", ".join(f"{s} {spec.stage_target_overrides.get(s, '?')}x"
                  f"{spec.stage_tuning.get(s, {}).get('events_per_job', '?')}"
                  for s in spec.grid_stages)
print(f"run_grid: stages -- {width}")
PY
echo "run_grid: config=$CONFIG mode=$MODE  (grid; expect 3-6 h)"

exec python -m graph.run --mode "$MODE" \
    --config-name "$CONFIG" --thread-id "$CONFIG"
