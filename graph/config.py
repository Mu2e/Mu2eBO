"""Paths and tunables for the LangGraph runner."""
from __future__ import annotations

import os
from pathlib import Path

# The BO/pipeline modules live in core/ (2026-07-17 reorg). Put it on
# sys.path so bare `import modes` / `import bo_driver` resolve from any
# graph entrypoint regardless of import order. This has to happen BEFORE
# `import paths`, so the repo root is bootstrapped from this file's own
# location; paths.REPO_ROOT is then the single definition everyone uses.
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from paths import REPO_ROOT as PROJECT_ROOT  # noqa: E402  (see core/paths.py)
# Runtime logs/forensics live off the /app repo on /data (2026-07-17), so the
# repo root stays clean and grid-log churn doesn't eat the /app quota. Single
# seam: everything (parent logs, closed_loop_logs/, STOP_FLAG) derives from here.
from paths import GRAPH_DATA  # noqa: E402  (per-operator; see core/paths.py)
# CHECKPOINT_DB moved off CephFS to node-local /tmp on 2026-06-09: SQLite's
# WAL mmap is incoherent across processes on CephFS (sqlite.org/wal.html §1, §7),
# which crashed foilsf08R00 10/10 children with "file is not a database" /
# "database disk image is malformed". /tmp is node-local xfs/tmpfs → POSIX-
# coherent mmap. The DB is a resume-convenience only (grid + leaderboard TSV
# + state dirs are the source of truth), so loss across host reboot is OK.
# See wiki/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md.
_CHECKPOINT_DIR = Path(os.environ.get("AUTORESEARCH_CHECKPOINT_DIR",
                                      f"/tmp/{os.environ.get('USER', 'autoresearch')}"))
CHECKPOINT_DB = _CHECKPOINT_DIR / "checkpoints.sqlite"
_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

BO_DRIVER = PROJECT_ROOT / "core" / "bo_driver.py"
PIPELINE_DRIVER = PROJECT_ROOT / "core" / "pipeline.py"

# Per-config grid work tree lives under here; harvest/summary.json gets written here.
from paths import GRID_DATA_ROOT  # noqa: E402  (per-operator)

# Mu2e environment sources. Sourced by every preflight/grid invocation.
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
# Per-mode Musing dispatch. CE/calo modes (michael/helical/foils*) use the
# Run1Bak patched-helical Offline (v13_12_10 / p094). prodtarget uses a
# locally-built patched workdir backed by MDC2025aq (v13_18_00 / p101) that
# carries the % 02d plate-LV rename, NIEL SD, and spacer-shrink overlap fix.
# Sourcing the workdir's setup.sh runs `muse setup <workdir>` so the local
# build/al9-prof-e29-p101/Offline/lib libs win over the backing by link order.
# Per-mode facts live in root modes.py (ADR-0002). This module derives the
# session's view once from the AUTORESEARCH_MODE env var — loud KeyError on
# an unknown mode, nothing hand-maintained here anymore.
import modes as _modes  # noqa: E402

_SPEC = _modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foils")]

MUSING = _SPEC.musing
MODE_SPEC = _SPEC  # full spec, exported for pipeline.py stage_defs access

# Stage chain (Phase 2b). Each entry is the stage name; per-stage `run_stage`
# calls submit → poll → list-outputs internally. Harvest runs once after the
# stages complete. Mode dispatch (2026-06-07, Mu2eBO #15): bo-prodtarget runs
# a single-stage chain (`pot_only`) backed by MDC2025aq; the original
# CE/calo modes keep the 4-stage chain. Selection is keyed on the
# `AUTORESEARCH_MODE` env var which `graph/closed_loop.py` and `graph/run.py`
# stamp BEFORE importing this module (load-order matters — `GRID_STAGES` is
# frozen at import time and `build.STAGE_NODES`/`build.build_graph` read it
# once).
GRID_STAGES = list(_SPEC.grid_stages)

# Overlap seam (2026-07-10): stages with NO internal data dependency are
# pre-submitted as soon as an earlier stage lands, hiding their grid time
# behind the rest of the chain. Map: after-stage -> [stages to presubmit].
# elebeam_flash resamples the EXTERNAL EleBeamCat (reads nothing from
# mubeam/mustops), so it is submitted right after mubeam completes — NOT at
# preflight: q parallel children presubmitting at round start would double
# the submit-lock ramp (the ff05 flood lesson, see bo-noise-budget).
# elebeam wall ~90 min hides fully behind mustops_ce ~111 min → ~25%/eval.
# Best-effort: a presubmit failure degrades to the sequential path via
# pipeline.py's idempotent cluster-file guard.
PRESUBMIT_AFTER = {k: list(v) for k, v in _SPEC.presubmit_after.items()}

# Sob-only picker (qlnei) doesn't need calo → drop the DS-off run1b_mubeam
# stage entirely. Stamped via AUTORESEARCH_NO_RUN1B env var by closed_loop.py
# when --picker qlnei is set. Saves ~40% of per-point grid time.
if os.environ.get("AUTORESEARCH_NO_RUN1B") == "1":
    GRID_STAGES = [s for s in GRID_STAGES if s != "run1b_mubeam"]

# Per-stage njobs targets — canonical source of truth for both
# pipeline.STAGES (consumed as njobs at submit) and read_stage_status
# (consumed to infer n_failed). Changing these here changes both.
STAGE_TARGETS = {
    "mubeam":       200,
    "run1b_mubeam": 200,
    "concat":         1,
    "mustops_ce":   200,
    # bo-foilsflash electron-beam early-flash stage (tracker StrawGasStep Edep).
    # foilsflash-only stage. 100 jobs × 110k ev ≈ 30-min payload (~80% grid eff);
    # ~0.54% hit rate → ~59k flash events → σ(flash) ~3.8× tighter than the smoke.
    # See bo-foilsflash + bo-noise-budget.
    "elebeam_flash": 100,
    # bo-prodtarget single-stage (see wiki/projects/bo-prodtarget.md).
    # 2026-06-19: 100→200 (paired with events_per_job 5000→2500 in pipeline.py,
    # constant 500k total events) to halve per-job wall + double parallelism,
    # mirroring the mustops_ce 200×2500 throughput fix. First used: pt6d10.
    # 2026-06-24: 200→800 (×4 jobs = 800×2500 = 2M events/eval) to cut the
    # μ_per_POT Poisson noise ~3%→~1.5% — the surrogate-fit-quality fix is more
    # stats, NOT ARD/kernel (gp-cloud-rendering "GP underfit = real noise").
    # njobs-safe: mu_per_POT denominator is exact POT from genCountLogger summed
    # over LANDED files, so 4× jobs = 4× POT num+denom, unbiased. Wall ~same as
    # 200 if grid slots available (parallel), else some queueing. First: pt6d15.
    "pot_only":     800,
}

# foilsflash uses ~30-min payloads: 100 jobs/stage paired with big events_per_job
# (set in pipeline.py STAGES override). mubeam/mustops_ce STAGE_TARGETS are SHARED
# with the foils family (tuned at 200), so override them ONLY for foilsflash
# here rather than changing the shared base. elebeam_flash is foilsflash-only (100
# in the base above). Keyed on AUTORESEARCH_MODE, stamped before import by closed_loop.
# Per-mode njobs overrides come from the ModeSpec; the env seam stays env
# and applies ON TOP (AUTORESEARCH_ELEBEAM_NJOBS: one-off high-stats runs —
# a bigger SINGLE cluster is the correct way to cut σ_flash because the
# elebeam template pins baseSeed:1; separate same-seed clusters re-sample
# identical EleBeamCat events. See bo-foilsflash A/B).
STAGE_TARGETS.update(_SPEC.stage_target_overrides)
if "AUTORESEARCH_ELEBEAM_NJOBS" in os.environ:
    STAGE_TARGETS["elebeam_flash"] = int(os.environ["AUTORESEARCH_ELEBEAM_NJOBS"])

# Fallback mode when --mode/AUTORESEARCH_MODE is unset (real launches always
# set it explicitly). foils = the stable base foil line (michael/helical retired
# 2026-07-12).
DEFAULT_MODE = "foils"
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
# Single source of truth; both the BO driver and the graph runner import this.
# Was previously split as 600s (bo_driver.py) vs 1200s
# (graph/pipeline_io.py:run_preflight) — the lower value caused silent
# preflight timeouts on cold-cache CVMFS hits.
PREFLIGHT_TIMEOUT_S = 1200

# ============================================================================
# Closed-loop (graph/closed_loop.py) constants
# ============================================================================
# Number of parallel chains per round.
CLOSED_LOOP_Q = 5
# Cap on rounds in one closed-loop invocation; --max-rounds overrides per call.
CLOSED_LOOP_MAX_ROUNDS = 10
# Delay between consecutive child launches (mitigates concurrent-token-contention;
# see wiki/incidents/concurrent-token-contention.md). 90s matches the value
# proven safe in helicalP01-P05.
CLOSED_LOOP_STAGGER_SEC = 90
# Barrier polling cadence — how often the parent re-reads child checkpoints.
# Closed-loop write rate is ~0.01 writes/sec, so polling every 5min is plenty
# without flooding the SqliteSaver.
CLOSED_LOOP_BARRIER_POLL_SEC = 300
# Loud backstop cap on a single round's barrier, for alive-but-hung
# children only (NOT round pacing; pipeline.py's per-stage cap_hours
# backstop is gone -- jobwait has no internal timeout by design, so this
# barrier timeout is now the ONLY backstop an alive-but-hung child resolves
# against). 1440 = 24h. Tripping this is rare and always worth investigating.
CLOSED_LOOP_BARRIER_MAX_MIN = 1440
# Operator stop file. `touch $GRAPH_DATA/STOP_CLOSED_LOOP` ($GRAPH_DATA expands to
# the path value at runtime) and the next barrier-poll iteration or decide_next will exit cleanly without affecting
# in-flight children.
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"

# SqliteSaver connection timeout — closed-loop adds outer parent + q children
# all writing to checkpoints.sqlite. WAL is on by default (see
# wiki/concepts/closed-loop-bo-design.md) but bumping the connect timeout
# from the SQLite default 5s to 30s absorbs CephFS lock-acquire jitter
# under bursty multi-writer load.
SQLITE_TIMEOUT_S = 30.0


def open_saver_conn():
    """Open the shared checkpoints.sqlite with WAL + bumped timeout.

    Single home for the SqliteSaver connection recipe (run.py + closed_loop).
    WAL is persistent per-DB, but set it explicitly so a fresh
    checkpoints.sqlite (deleted/recreated) doesn't fall back to the default
    DELETE journal, which serializes all writers.
    """
    import sqlite3
    conn = sqlite3.connect(
        str(CHECKPOINT_DB),
        check_same_thread=False,
        timeout=SQLITE_TIMEOUT_S,
    )
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

# Picker subprocess plumbing: node_predict_picks shells botorch_predict.py
# into a child interpreter, dumps picks to a tmp JSON, and loads them back
# into the langgraph state. Since the 2026-07-18 venv consolidation there is
# ONE project venv (.venv) — the subprocess keeps torch out of the
# long-lived orchestrator process, not out of a different dependency set.
# AUTORESEARCH_BOTORCH_VENV overrides the venv DIRECTORY for a picker A/B
# (e.g. a future train_Yvar or botorch-0.19 arm; see wiki
# ml-stack-review-2026-07).
BOTORCH_VENV_PY = (PROJECT_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")
BOTORCH_PREDICT = PROJECT_ROOT / "core" / "botorch_predict.py"
