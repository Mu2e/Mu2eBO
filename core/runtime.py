"""Non-path runtime tunables for the BO loop (per-mode facts off modes.SPECS).

`_SPEC` resolves the mode at IMPORT time, so an entrypoint taking `--mode`
MUST stamp AUTORESEARCH_MODE before its first `import runtime` -- see
core/modes.py::stamp_mode_from_argv(), which owns that story.
"""
from __future__ import annotations

import os
from pathlib import Path

import modes as _modes
from paths import GRAPH_DATA, REPO_ROOT

_SPEC = _modes.SPECS[_modes.resolve_env_mode()]

MUSING = _SPEC.musing
GRID_STAGES = list(_SPEC.grid_stages)
PRESUBMIT_AFTER = {k: list(v) for k, v in _SPEC.presubmit_after.items()}

SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"

BO_DRIVER = REPO_ROOT / "core" / "bo_driver.py"
PIPELINE_DRIVER = REPO_ROOT / "core" / "pipeline.py"
BOTORCH_PREDICT = REPO_ROOT / "core" / "botorch_predict.py"
# AUTORESEARCH_BOTORCH_VENV overrides the venv DIRECTORY for a picker A/B.
BOTORCH_VENV_PY = (REPO_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")

# Re-exported; core/modes.py owns the value.
DEFAULT_MODE = _modes.DEFAULT_MODE
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
PREFLIGHT_TIMEOUT_S = 1200

# Closed-loop (graph/closed_loop.py, graph/pool.py) constants.
# Number of parallel children in flight at once.
CLOSED_LOOP_Q = 5
# Cap on rounds in one closed-loop invocation; --max-rounds overrides per call.
CLOSED_LOOP_MAX_ROUNDS = 10
# Launch stagger; 90s proven safe in helicalP01-P05.
# See wiki/incidents/concurrent-token-contention.md.
CLOSED_LOOP_STAGGER_SEC = 90
# Operator stop file: the pool stops LAUNCHING at its next top-up check;
# in-flight children DRAIN (can take hours) -- the structural fix for
# closed-loop-final-round-orphan-children. To stop sooner: jobsub_rm, then
# kill the graph.run processes.
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"

# Per-stage njobs is deliberately NOT here (the retired STAGE_TARGETS dict is
# the failure shape in wiki/incidents/events-per-job-mid-flight-edit.md);
# core/pipeline.py's stage_cfg(stage, mode) is the one source.
