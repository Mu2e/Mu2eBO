"""Non-path runtime tunables for the BO loop.

Path-shaped roots live in core/paths.py, the single filesystem-root
resolver; this file holds only plain values, including the per-mode facts
read off modes.SPECS (MUSING is a string, GRID_STAGES a list).

`_SPEC` below resolves THE process's mode eagerly, at import time, so an
entrypoint taking `--mode` MUST stamp AUTORESEARCH_MODE before its first
`import runtime` -- see core/modes.py::stamp_mode_from_argv(), which owns
that story.
"""
from __future__ import annotations

import os
from pathlib import Path

import modes as _modes
from paths import GRAPH_DATA, REPO_ROOT

# The fallback literal lives in core/modes.py (the registry), not here.
# resolve_env_mode rather than a bare dict lookup: unset falls through to
# DEFAULT_MODE, but a SET-BUT-UNKNOWN value is fatal with a message naming
# the bad value and the live modes, instead of KeyError('bogusmode').
_SPEC = _modes.SPECS[_modes.resolve_env_mode()]

MUSING = _SPEC.musing
GRID_STAGES = list(_SPEC.grid_stages)
PRESUBMIT_AFTER = {k: list(v) for k, v in _SPEC.presubmit_after.items()}

# Mu2e environment sources. Sourced by every preflight/grid invocation.
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"

BO_DRIVER = REPO_ROOT / "core" / "bo_driver.py"
PIPELINE_DRIVER = REPO_ROOT / "core" / "pipeline.py"
BOTORCH_PREDICT = REPO_ROOT / "core" / "botorch_predict.py"
# _botorch_picks_subprocess shells botorch_predict.py into a child
# interpreter so torch stays out of the long-lived orchestrator process.
# AUTORESEARCH_BOTORCH_VENV overrides the venv DIRECTORY for a picker A/B.
BOTORCH_VENV_PY = (REPO_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")

# Re-exported from the registry so `from runtime import DEFAULT_MODE` keeps
# working; core/modes.py owns the value.
DEFAULT_MODE = _modes.DEFAULT_MODE
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check);
# both the BO driver and the graph runner import this one value.
PREFLIGHT_TIMEOUT_S = 1200

# ============================================================================
# Closed-loop (graph/closed_loop.py, graph/pool.py) constants
# ============================================================================
# Number of parallel children in flight at once.
CLOSED_LOOP_Q = 5
# Cap on rounds in one closed-loop invocation; --max-rounds overrides per call.
CLOSED_LOOP_MAX_ROUNDS = 10
# Delay between consecutive child launches; 90s is the value proven safe in
# helicalP01-P05. See wiki/incidents/concurrent-token-contention.md.
CLOSED_LOOP_STAGGER_SEC = 90
# Operator stop file. `touch $GRAPH_DATA/STOP_CLOSED_LOOP` and the pool stops
# LAUNCHING at its next top-up check; in-flight children are neither
# signalled nor abandoned, run_rolling DRAINS them, which can take hours.
# That is the structural fix for closed-loop-final-round-orphan-children, but
# it means STOP is not a fast exit -- to stop sooner, deal with the children
# yourself (jobsub_rm, then kill the graph.run processes).
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"

# Per-stage njobs is deliberately NOT here (the retired STAGE_TARGETS dict is
# the failure shape in wiki/incidents/events-per-job-mid-flight-edit.md).
# core/pipeline.py's stage_cfg(stage, mode) is the one source: it reads
# stage_entries/<stage>.json and applies _SPEC.stage_target_overrides plus
# the AUTORESEARCH_ELEBEAM_NJOBS seam. graph/pipeline_io.py's
# read_stage_status calls stage_cfg() rather than keeping a second copy.
