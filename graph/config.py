"""Paths and tunables for the LangGraph runner."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
GRAPH_DATA = PROJECT_ROOT / "graph_data"
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

BO_DRIVER = PROJECT_ROOT / "autoresearch_bo_michael.py"
PIPELINE_DRIVER = PROJECT_ROOT / "pipeline.py"

# Per-config grid work tree lives under here; harvest/summary.json gets written here.
GRID_DATA_ROOT = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")

# Mu2e environment sources. Sourced by every preflight/grid invocation.
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
# Per-mode Musing dispatch. CE/calo modes (michael/helical/foils*) use the
# Run1Bak patched-helical Offline (v13_12_10 / p094). prodtarget uses a
# locally-built patched workdir backed by MDC2025aq (v13_18_00 / p101) that
# carries the % 02d plate-LV rename, NIEL SD, and spacer-shrink overlap fix.
# Sourcing the workdir's setup.sh runs `muse setup <workdir>` so the local
# build/al9-prof-e29-p101/Offline/lib libs win over the backing by link order.
MUSING_BY_MODE = {
    "michael":      "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh",
    "helical":      "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh",
    # foils/foilsf/foilsg preflight MUST see the patched StoppingTargetMaker
    # (stoppingTarget.holeRadii vector) or it diverges from the grid tarball
    # and silently validates the wrong geometry. See
    # wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
    "foils":        "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh",
    "foilsf":       "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh",
    # foilsflash varies foil geometry (holeRadii vector) → same patched musing as foilsf.
    "foilsflash":   "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh",
    "foilsg":       "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh",
    # ipa overrides only protonabsorber.* (no holeRadii vector) → stock Run1Bak
    # Musing is sufficient; it does NOT need the patched StoppingTargetMaker.
    "ipa":          "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh",
    "prodtarget":   "/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/setup_local.sh",
    "prodtarget6d": "/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/setup_local.sh",
}
MUSING = MUSING_BY_MODE[os.environ.get("AUTORESEARCH_MODE", "michael")]

# Stage chain (Phase 2b). Each entry is the stage name; per-stage `run_stage`
# calls submit → poll → list-outputs internally. Harvest runs once after the
# stages complete. Mode dispatch (2026-06-07, Mu2eBO #15): bo-prodtarget runs
# a single-stage chain (`pot_only`) backed by MDC2025aq; the original
# CE/calo modes keep the 4-stage chain. Selection is keyed on the
# `AUTORESEARCH_MODE` env var which `graph/closed_loop.py` and `graph/run.py`
# stamp BEFORE importing this module (load-order matters — `GRID_STAGES` is
# frozen at import time and `build.STAGE_NODES`/`build.build_graph` read it
# once).
GRID_STAGES_BY_MODE = {
    "michael":      ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    "helical":      ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    "foils":        ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    "foilsf":       ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    "foilsg":       ["mubeam", "run1b_mubeam", "concat", "mustops_ce"],
    # ipa: NO run1b_mubeam — that DS-off stage only feeds the foils calo
    # channel, which IPA replaces with mustops_pileup tracker Edep. So:
    # mubeam (→TargetStops) → concat → mustops_ce (S/√B) + mustops_pileup (Edep).
    # Both mustops_* resample concat. Saves a full beam-sim stage.
    "ipa":          ["mubeam", "concat", "mustops_ce", "mustops_pileup"],
    # foilsflash: like ipa, NO run1b_mubeam (calo dropped). 2nd objective is the
    # electron-beam early-flash tracker edep from the elebeam_flash stage (which
    # resamples the external EleBeamCat dataset, DS-on, ships the foil geom).
    # mubeam→concat→mustops_ce gives S/√B; elebeam_flash gives flash edep.
    "foilsflash":   ["mubeam", "concat", "mustops_ce", "elebeam_flash"],
    "prodtarget":   ["pot_only"],
    "prodtarget6d": ["pot_only"],
}
GRID_STAGES = GRID_STAGES_BY_MODE[os.environ.get("AUTORESEARCH_MODE", "michael")]

# Sob-only picker (qlnei) doesn't need calo → drop the DS-off run1b_mubeam
# stage entirely. Stamped via AUTORESEARCH_NO_RUN1B env var by closed_loop.py
# when --picker qlnei is set. Saves ~40% of per-point grid time.
if os.environ.get("AUTORESEARCH_NO_RUN1B") == "1":
    GRID_STAGES = [s for s in GRID_STAGES if s != "run1b_mubeam"]

# Per-mode harvest verb. `cmd_harvest` (4-stage S/√B − α·calo/POT) vs
# `cmd_harvest_pot_only` (uproot-based mu_per_POT at VD sid=8). Dispatched in
# graph/pipeline_io.run_harvest.
HARVEST_VERB_BY_MODE = {
    "michael":      "harvest",
    "helical":      "harvest",
    "foils":        "harvest",
    "foilsf":       "harvest",
    "foilsflash":   "harvest",
    "foilsg":       "harvest",
    "ipa":          "harvest",
    "prodtarget":   "harvest-pot-only",
    "prodtarget6d": "harvest-pot-only",
}

# Per-stage njobs targets — canonical source of truth for both
# pipeline.STAGES (consumed as njobs at submit) and read_stage_status
# (consumed to infer n_failed). Changing these here changes both.
STAGE_TARGETS = {
    "mubeam":       200,
    "run1b_mubeam": 200,
    "concat":         1,
    "mustops_ce":   200,
    # bo-ipa muon-stop pileup stage (tracker StrawGasStep Edep from capture
    # protons). 100×2500 = half of mustops_ce — capture-proton steps are dense.
    "mustops_pileup": 100,
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
# with michael/helical/foils/ipa (tuned at 200), so override them ONLY for foilsflash
# here rather than changing the shared base. elebeam_flash is foilsflash-only (100
# in the base above). Keyed on AUTORESEARCH_MODE, stamped before import by closed_loop.
if os.environ.get("AUTORESEARCH_MODE") == "foilsflash":
    # Lever-1 (fast) config from foilsflash03 on: trim the sob stages (sob σ~0.3%,
    # plenty) so the local EdepAna harvest is ~10 min not ~60 — more trials/time →
    # denser slide-3 cloud. elebeam_flash stays 100 (full flash stats per trial).
    STAGE_TARGETS["mubeam"] = 15
    STAGE_TARGETS["mustops_ce"] = 15
    # Env seam (default 100, preserving) to raise flash statistics for one-off
    # high-stats / replica runs. More jobs in ONE cluster = more INDEPENDENT
    # subruns (the elebeam_flash template pins baseSeed:1, so SEPARATE same-seed
    # clusters would re-sample identical EleBeamCat events — useless; a bigger
    # single cluster is the correct way to cut σ_flash). See bo-foilsflash A/B.
    STAGE_TARGETS["elebeam_flash"] = int(os.environ.get("AUTORESEARCH_ELEBEAM_NJOBS", "100"))

# Phase 1: helical only. michael wiring follows in Phase 2.
DEFAULT_MODE = "helical"
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
# Single source of truth; both the BO driver and the graph runner import this.
# Was previously split as 600s (autoresearch_bo_michael.py) vs 1200s
# (graph/pipeline_io.py:run_preflight) — the lower value caused silent
# preflight timeouts on cold-cache CVMFS hits.
PREFLIGHT_TIMEOUT_S = 1200

# Mock metrics knobs (Phase 1 only) — smooth analytic surface over the
# 4D helical search space so the graph has something to optimize.
MOCK_SOB_PEAK = 1.0
MOCK_CALO_FLOOR = 1.0e-7

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
# children only (NOT round pacing; alive children always resolve via
# pipeline.py's per-stage cap_hours). 1440 = 24h. Tripping this is rare
# and always worth investigating.
CLOSED_LOOP_BARRIER_MAX_MIN = 1440
# Budget knob passed to gp_predict_helical.compute_explore_picks — the
# N_crit Sobol gate for the GP-pick acquisition search. 2000 matches the
# empirically-validated value used by gp_predict_helical.DEFAULT_NSTEPS_BUDGET
# and botorch_predict_helical.NSTEPS_BUDGET; decoupled from HELICAL_NSTEPS
# (FCL render resolution) 2026-05-27 — see wiki/projects/bo-helical.md
# "Update 2026-05-27".
NSTEPS_BUDGET = 2000
# Operator stop file. `touch graph_data/STOP_CLOSED_LOOP` and the next
# barrier-poll iteration or decide_next will exit cleanly without affecting
# in-flight children.
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"
# Minimum normalized-L2 distance between picks returned by
# compute_explore_picks (revision #7). Guards against the degenerate case
# where a short Pareto frontier yields near-duplicate q-picks.
CLOSED_LOOP_MIN_PICK_SPACING = 0.05

# SqliteSaver connection timeout — closed-loop adds outer parent + q children
# all writing to checkpoints.sqlite. WAL is on by default (see
# wiki/concepts/closed-loop-bo-design.md) but bumping the connect timeout
# from the SQLite default 5s to 30s absorbs CephFS lock-acquire jitter
# under bursty multi-writer load.
SQLITE_TIMEOUT_S = 30.0

# Disjoint-venv plumbing: closed_loop.py runs under .venv-graph (langgraph,
# sklearn, skopt) but the botorch_predict.py qNEHVI picker needs .venv-botorch
# (gpytorch + botorch). When --picker qnehvi is requested, node_predict_picks
# subprocess-shells into this interpreter, dumps picks to a tmp JSON, and
# loads them back into the langgraph state.
BOTORCH_VENV_PY = PROJECT_ROOT / ".venv-botorch" / "bin" / "python"
BOTORCH_PREDICT = PROJECT_ROOT / "botorch_predict.py"
