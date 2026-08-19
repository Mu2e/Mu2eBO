"""Non-path runtime tunables for the BO loop.

Moved out of graph/config.py 2026-08-19. Path-shaped roots live in
core/paths.py, which is the single filesystem-root resolver; this file holds
only plain values (and the per-mode facts derived from modes.SPECS, which
were always plain values too -- MUSING is a string, GRID_STAGES a list).

graph/presniff.py died with the move -- the MODULE did, not the mechanism.
It scanned sys.argv for `--mode`/`--picker` before graph/config.py's
top-level import ran, so the module-level `_SPEC` lookup below picked the
CLI-requested mode instead of the default. Deleting it was justified on the
grounds that every live JSON mode (the foilspf family + foilsflash) shares
identical `run.stages`/`musing`/`presubmit_after` (all descend from the same
foilspf design), so a mode-keyed lookup cannot disagree.

That argument is about the DATA, not the code, and the surface `_SPEC`
governs is events_per_job, njobs, memory_mb, quorum, grid_tarball,
dsconf_musing, MUSING and (via graph/build.py's STAGE_NODES) the child's
stage chain. The first per-mode edit to `run.stage_tuning.*` would have
shipped another mode's value to the grid silently -- a metric DENOMINATOR
error with no error surface. Measured while it was absent: `--mode
foilspfbw` gave `_SPEC.name == "foilspf"` and `pipeline.MODE ==
"foilsflash"`.

So the --mode stamp is BACK, without the module: `core/modes.py::
stamp_mode_from_argv()`, called by graph/run.py and graph/closed_loop.py
before they import this file, and re-checked after argparse by
`modes.assert_mode_stamped()`. The `--picker`-driven AUTORESEARCH_NO_RUN1B
half was NOT restored (no live mode's stage chain has run1b_mubeam to drop).
See tests/test_modes.py::TestModeStamping, tests/test_runtime_constants.py,
and wiki/incidents/foilsflash-tarball-mode-key-omission.md for the
historical reason mode dispatch existed at all.
"""
from __future__ import annotations

import os
from pathlib import Path

import modes as _modes
from paths import GRAPH_DATA, REPO_ROOT

# Default is foilspf, NOT the historical "foils": that spec was retired and
# the lookup had been dangling since -- a bare `import config` raised
# KeyError('foils'). foilspf is the mode this whole spec (minimal-foilspf-
# workflow) is named for.
_SPEC = _modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foilspf")]

MUSING = _SPEC.musing
GRID_STAGES = list(_SPEC.grid_stages)
PRESUBMIT_AFTER = {k: list(v) for k, v in _SPEC.presubmit_after.items()}

# Mu2e environment sources. Sourced by every preflight/grid invocation.
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"

BO_DRIVER = REPO_ROOT / "core" / "bo_driver.py"
PIPELINE_DRIVER = REPO_ROOT / "core" / "pipeline.py"
BOTORCH_PREDICT = REPO_ROOT / "core" / "botorch_predict.py"
# Picker subprocess plumbing: node_predict_picks/_botorch_picks_subprocess
# shells botorch_predict.py into a child interpreter so torch stays out of
# the long-lived orchestrator process. AUTORESEARCH_BOTORCH_VENV overrides
# the venv DIRECTORY for a picker A/B.
BOTORCH_VENV_PY = (REPO_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")

# Fallback mode when --mode/AUTORESEARCH_MODE is unset (real launches always
# set it explicitly).
DEFAULT_MODE = "foilspf"
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
# Single source of truth; both the BO driver and the graph runner import this.
PREFLIGHT_TIMEOUT_S = 1200

# ============================================================================
# Closed-loop (graph/closed_loop.py, graph/pool.py) constants
# ============================================================================
# Number of parallel children in flight at once.
CLOSED_LOOP_Q = 5
# Cap on rounds in one closed-loop invocation; --max-rounds overrides per call.
CLOSED_LOOP_MAX_ROUNDS = 10
# Delay between consecutive child launches (mitigates concurrent-token-contention;
# see wiki/incidents/concurrent-token-contention.md). 90s matches the value
# proven safe in helicalP01-P05.
CLOSED_LOOP_STAGGER_SEC = 90
# Operator stop file. `touch $GRAPH_DATA/STOP_CLOSED_LOOP` and the pool
# stops LAUNCHING at its next top-up check. In-flight children are neither
# signalled nor abandoned: run_rolling then DRAINS, i.e. the parent blocks
# until every one of them exits, which can take hours. That is the
# structural fix for closed-loop-final-round-orphan-children, not an
# oversight -- but it means STOP is not a fast exit, and the older comment
# here ("exits cleanly without affecting in-flight children") read as if it
# were. To stop sooner, deal with the children yourself (jobsub_rm, then
# kill the graph.run processes).
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"

# Per-stage njobs targets used to live here (STAGE_TARGETS, retired 2026-08-19
# in the same cleanup that retired core/pipeline.py:STAGES -- see
# wiki/incidents/events-per-job-mid-flight-edit.md for the failure shape both
# retirements were closing). It does NOT feed submit any more --
# core/pipeline.py's stage_cfg(stage, mode) reads njobs from
# stage_entries/<stage>.json, overridden by the mode spec's
# run.jobs_per_stage, same as this dict used to be built (base literal +
# _SPEC.stage_target_overrides + the AUTORESEARCH_ELEBEAM_NJOBS env seam --
# all three now live in stage_cfg()). graph/pipeline_io.py's
# read_stage_status (n_failed inference) reads pipeline.stage_cfg() directly
# instead of importing a second copy of the same number, so there is exactly
# one place njobs comes from.
