"""Non-path runtime tunables for the BO loop.

Moved out of graph/config.py 2026-08-19. Path-shaped roots live in
core/paths.py, which is the single filesystem-root resolver; this file holds
only plain values (and the per-mode facts derived from modes.SPECS, which
were always plain values too -- MUSING is a string, GRID_STAGES a list).

graph/presniff.py died with the move. It scanned sys.argv for `--mode`/
`--picker` before graph/config.py's top-level import ran, so the module-
level `_SPEC` lookup below picked the CLI-requested mode instead of the
default -- needed
only because live modes used to differ in grid_stages/musing (Python-mode
era: michael/helical/ipa/foils/foilsg/prodtarget each had their own stage
chain or software stack). Every live JSON mode today (the foilspf family +
foilsflash) shares the identical `run.stages`/`musing`/`presubmit_after`
(all descend from the same foilspf design), so presniffing a value that
never varies between them buys nothing. See
tests/test_runtime_constants.py and wiki/incidents/foilsflash-tarball-mode-
key-omission.md for the historical reason mode dispatch existed at all.
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
# Operator stop file. `touch $GRAPH_DATA/STOP_CLOSED_LOOP` and the pool's
# next stop_flag() check exits cleanly without affecting in-flight children.
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"

# ============================================================================
# Per-stage njobs targets (core/pipeline.py:STAGES, retired into
# stage_entries/ by a later task) -- canonical source of truth for both
# njobs at submit and read_stage_status's n_failed inference.
# ============================================================================
STAGE_TARGETS = {
    "mubeam":       200,
    "run1b_mubeam": 200,
    "concat":         1,
    "mustops_ce":   200,
    # bo-foilsflash electron-beam early-flash stage (tracker StrawGasStep Edep).
    "elebeam_flash": 100,
}
STAGE_TARGETS.update(_SPEC.stage_target_overrides)
if "AUTORESEARCH_ELEBEAM_NJOBS" in os.environ:
    STAGE_TARGETS["elebeam_flash"] = int(os.environ["AUTORESEARCH_ELEBEAM_NJOBS"])
