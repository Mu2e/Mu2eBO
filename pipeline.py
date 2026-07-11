#!/usr/bin/env python3
"""
Parametric grid pipeline orchestrator for the BO loop.

Single canonical pipeline.py. Pass --config CFG; ROOT, GEOM_FILE, DSCONF,
PNFS_STAGE and per-stage `desc` fields are derived from CFG. Stage templates
live next to this script under pipeline_templates/<stage>/template.fcl with
the geom basename slot marked `__GEOM_FILE__`; submit_stage materializes the
template into <work_root>/<cfg>/state/<stage>_template_materialized.fcl
before handing it to mu2ejobdef.

Per-config working tree (auto-created):
  /exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/
    geom/autoresearch_<cfg>_geom.txt   (placed by autoresearch_bo_michael.py propose)
    <stage>/                           (cnf tarballs, Code.tar.bz2)
    state/                             (cluster IDs, output lists, materialized FCL)
    harvest/                           (summary.json, EdepAna outputs)

Stages run in sequence at a fixed BO knob point:
  mubeam (200) + run1b_mubeam (200) -> concat (1) -> mustops_ce (200) -> harvest

Each stage is its own subcommand so a failed stage can be re-run without redoing
the earlier ones.

Polling uses jobsub_q --user=$USER and direct /pnfs ls.
Outstage convention: /pnfs/mu2e/scratch/users/$USER/workflow/default/outstage/<CLUSTER>/00/<hash>/
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Host-wide lock guarding the mu2ejobsub critical section. condor_vault_storer
# races when N concurrent chains call submit within seconds; serializing the
# token-refresh+submit block eliminates the "Failed to obtain weakened token"
# crashes (see wiki/incidents/concurrent-token-contention.md).
_SUBMIT_LOCK_PATH = Path(f"/tmp/mu2e_submit.{os.environ.get('USER', 'unknown')}.lock")


@contextmanager
def _submit_lock(stage: str):
    """Block until we hold the host-wide submit lock; release on exit."""
    _SUBMIT_LOCK_PATH.touch(exist_ok=True)
    t0 = time.time()
    with open(_SUBMIT_LOCK_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        waited = time.time() - t0
        if waited > 1.0:
            print(f"[{stage}] acquired submit lock after {waited:.1f}s wait", flush=True)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

# --- Paths fixed at the code-repo level (config-independent) ---
TEMPLATES_ROOT = Path(__file__).resolve().parent / "pipeline_templates"

sys.path.insert(0, str(Path(__file__).resolve().parent / "graph"))
from config import (  # noqa: E402
    GRID_DATA_ROOT as DATA_ROOT,
    GRID_STAGES,
    MUSING,
    SETUPMU2E,
    STAGE_TARGETS,
)

# Concat-less chains (foilsflash since 2026-07-10): the mubeam template's
# muminusSelector makes TargetStops mu--pure, so mustops_* resample the
# mubeam files directly and harvest counts mu- stops from them.
CONCATLESS = "concat" not in GRID_STAGES
from sourced_bash import run_sourced_bash  # noqa: E402
# Eval-summary module: schema + pure harvest logic (parsers, stage-chain
# stamp, input resolution, fail-soft secondary extraction). See wiki
# concepts/architecture-friction-survey-2026-07 (2026-07-11 addendum).
import harvest as hv  # noqa: E402

# Canonical muse-built Code.tar.bz2 produced by `muse tarball` from
# /exp/mu2e/app/users/oksuzian/autoresearch_muse/ (mgit Mu2eG4 sparse
# checkout of v13_12_10 + helical-plug.patch, backed by SimJob/Run1Bak).
# Contains Code/setup.sh that does `muse setup $CODE_DIR -q e29 prof p094`,
# so the local libs (incl. patched libmu2e_Mu2eG4.so with mu2e::makeHelicalPlug)
# win via Muse's normal link/path order — no LD_PRELOAD needed.
# See wiki/external/muse-backing-pattern.md for the build workflow and
# wiki/incidents/calo-constant-across-helical.md for the motivating bug.
# Mode-aware base tarball. foils/foilsf/foilsg need the patched
# libmu2e_GeometryService.so (stoppingTarget.holeRadii vector) built in
# Offline_helical/ — Code_helical_base ships only the patched Mu2eG4 and
# silently falls back to the scalar holeRadius (mean of the vector), which
# is how every foilsg row got built with uniform holes. michael/helical stay
# on Code_helical_base because Offline_helical's Mu2eG4 lib (May 16)
# predates the twistedbox facet fix (May 26).
# See wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
_HOLERADII_TARBALL = (
    "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2"
)
MUSE_TARBALL_BY_MODE = {
    "michael": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_base.tar.bz2",
    "helical": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_base.tar.bz2",
    "foils":   _HOLERADII_TARBALL,
    "foilsf":  _HOLERADII_TARBALL,
    "foilsflash": _HOLERADII_TARBALL,  # varies foil holeRadii vector — needs the patched StoppingTargetMaker
    "foilsg":  _HOLERADII_TARBALL,
}
MUSE_BASE_TARBALL = Path(MUSE_TARBALL_BY_MODE.get(
    os.environ.get("AUTORESEARCH_MODE", "michael"),
    MUSE_TARBALL_BY_MODE["michael"],
))
USER = os.environ["USER"]
OUTSTAGE = Path(f"/pnfs/mu2e/scratch/users/{USER}/workflow/default/outstage")

# --- Per-config paths populated by main() once --config is parsed ---
CONFIG: str = ""
ROOT: Path = Path()
STATE: Path = Path()
GEOM_FILE: Path = Path()
DSCONF: str = ""
PNFS_STAGE: Path = Path()


def _bind_config(cfg: str) -> None:
    """Resolve all per-config paths from CFG. Called once by main()."""
    global CONFIG, ROOT, STATE, GEOM_FILE, DSCONF, PNFS_STAGE
    CONFIG = cfg
    ROOT = DATA_ROOT / cfg
    STATE = ROOT / "state"
    GEOM_FILE = ROOT / "geom" / f"autoresearch_{cfg}_geom.txt"
    # DSCONF default reflects the dominant musing (Run1Bak — michael/helical/
    # foils). Per-stage override via STAGES[s]["dsconf_musing"] for modes
    # backing a different Musing (e.g. pot_only -> MDC2025aq).
    DSCONF = f"Run1Bak_{cfg}"
    PNFS_STAGE = Path(f"/pnfs/mu2e/scratch/users/{USER}/autoresearch_grid/{cfg}/staged")


def _stage_dsconf(stage: str) -> str:
    """Return the dsconf string for this stage. Per-stage `dsconf_musing` key
    wins; otherwise the module-global DSCONF (Run1Bak_<cfg>) is used."""
    musing = STAGES[stage].get("dsconf_musing")
    return f"{musing}_{CONFIG}" if musing else DSCONF


# Per-stage knobs (config-invariant). desc_fmt and template path are derived
# at submit time from CONFIG. Inputs that vary per config (geom basename) are
# substituted into the template via __GEOM_FILE__ in submit_stage.
STAGES = {
    "mubeam": {
        "desc_fmt": "Run1A_MuBeam_{cfg}",
        "njobs": STAGE_TARGETS["mubeam"],
        "events_per_job": 5000,
        "run_number": 1800,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'mubeam' / 'MuBeamCat.txt'}",
        "default_loc": "disk",
        "output_glob": "sim.*.TargetStops.*.art",
    },
    "run1b_mubeam": {
        "desc_fmt": "Run1B_MuBeam_{cfg}",
        "njobs": STAGE_TARGETS["run1b_mubeam"],
        "events_per_job": 5000,
        "run_number": 1810,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'run1b_mubeam' / 'MuBeamCat.txt'}",
        "default_loc": "disk",
        "output_glob": "nts.*.mubeam.*.root",
    },
    "concat": {
        "desc_fmt": "Run1A_MuStopsCat_{cfg}",
        "njobs": STAGE_TARGETS["concat"],
        "merge_factor": 200,
        "ships_geom": False,
        "default_loc": "disk",
        "output_glob": "sim.*.MuminusStopsCat.*.art",
    },
    "mustops_ce": {
        "desc_fmt": "Run1A_CeEndpoint_{cfg}",
        # 100 jobs per A/B noise test on helical001 (2026-05-16): half-vs-half
        # ce_seen agreed to 0.4% at 97 jobs each — well below GP noise floor.
        "njobs": STAGE_TARGETS["mustops_ce"],
        # njobs=200 driven by STAGE_TARGETS["mustops_ce"] in graph/config.py.
        # 2500 events/job paired with njobs=200 (set in graph/config.py
        # STAGE_TARGETS) preserves total CE statistics at 500k events but
        # halves per-job wall-time and doubles per-cluster parallelism.
        # 2026-05-21 PM: SR00_00 long-tail (dx=0.011 → N_crit≈4144 → 3-4h
        # CPU/job, 5× normal) showed the implicit throughput gate; halving
        # events_per_job halves the per-job CPU cost at constant total
        # statistics. The earlier 2026-05-21 AM reversion to 5000 was made
        # WITHOUT compensating with njobs, which halved stats and hurt
        # σ(sob) 0.10→0.14; this configuration restores σ(sob).
        # Stamped at submit (see [[events-per-job-mid-flight-edit]]).
        "events_per_job": 2500,
        "run_number": 1801,
        "ships_geom": True,
        "default_loc": "disk",
        "output_glob": "dts.*.CeEndpoint.*.art",
        # 3000 MB (was 2500). SR00_00 worker logs showed VmPeak=2.75 GB on
        # N_crit≈4144 jobs, exceeding the 2.2 GB allocation request and
        # creating eviction risk. 3000 MB gives the high-N_crit tail
        # comfortable headroom without burning slot-matchability.
        "memory_mb": 3000,
    },
    # Muon-stop pileup stage for the IPA BO line (bo-ipa). Resamples the same
    # concat MuminusStopsCat as mustops_ce (TargetStopResampler), generates
    # capture products (protons etc.) and emits StrawGasStep (tracker Edep).
    # njobs 100×2500 = 250k events (half of mustops_ce) — capture-proton steps
    # are dense so this is ample for the trk_edep objective; tune if noisy.
    "mustops_pileup": {
        "desc_fmt": "Run1A_MuStopPileup_{cfg}",
        "njobs": STAGE_TARGETS["mustops_pileup"],
        "events_per_job": 2500,
        "run_number": 1802,
        "ships_geom": True,
        "default_loc": "disk",
        "output_glob": "dts.*.MuStopPileup.*.art",
        "memory_mb": 3000,
    },
    # Electron-beam early-flash stage for the foilsflash BO line. Resamples the
    # external EleBeamCat dataset (like mubeam resamples MuBeamCat — static
    # auxinput filelist, NOT concat), DS-on, ships the per-BO foil geom, and
    # writes EarlyEleBeamFlash StrawGasStep DetSteps. Harvest sums tracker
    # ionizingEdep (reuses _extract_trk_edep_per_pot). See bo-foilsflash.
    "elebeam_flash": {
        "desc_fmt": "Run1A_EleBeamFlash_{cfg}",
        "njobs": STAGE_TARGETS["elebeam_flash"],
        "events_per_job": 2500,
        "run_number": 1803,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'elebeam_flash' / 'EleBeamCat.txt'}",
        # "tape" since 2026-07-10: EleBeamCat Run1Baa migrated persistent→tape
        # on 2026-07-09. mu2ejobfcl derives the auxinput URL from THIS flag
        # ("disk"==persistent), NOT from SAM — a stale value kills every job
        # with FileOpenError at beamResampler. Files are dCache-online; verify
        # locality before campaigns (wiki: elebeamcat-tape-migration-elebeam-wipeout).
        "default_loc": "tape",
        "output_glob": "dts.*.EarlyEleBeamFlash.*.art",
        "memory_mb": 3000,
    },
    # Single-stage POT + ReadVirtualDetector for bo-prodtarget. Ships
    # the MDC2025aq backing-only tarball (no patched libs); geom overlay
    # carries the Stickman knob substitution. Muon counts harvested from
    # pot_vd.root TTree; exact POT denominator from genCountLogger TH1D.
    # VmHWM 2.83 GB measured locally -> 3000 MB request matches mustops_ce
    # headroom.
    "pot_only": {
        "desc_fmt": "POT_{cfg}",
        "njobs": STAGE_TARGETS["pot_only"],
        # 2026-06-19: 5000→2500, paired with STAGE_TARGETS["pot_only"] 100→200
        # (constant 500k total events → 3% noise budget preserved); halves
        # per-job wall + doubles parallelism. Mirrors mustops_ce. First: pt6d10.
        "events_per_job": 2500,
        "run_number": 1700,
        "ships_geom": True,
        "code_tarball": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2",
        "dsconf_musing": "MDC2025aq",
        "default_loc": "disk",
        "output_glob": "nts.*.POT_vd.*.root",
        "memory_mb": 3000,
    },
}

# foilsflash: size events_per_job for ~30-min payloads (measured per-event:
# mubeam 9.1 ms, mustops_ce 24.1 ms, elebeam_flash 16.6 ms) instead of the
# ~45-s default — payload then dominates the ~44-s muse/setup overhead (~80% grid
# efficiency vs ~15-30%). Paired with njobs=100 (graph/config.py STAGE_TARGETS
# override) → ~15-20× total stats: σ(sob)~0.09% (overkill, harmless) + σ(flash)
# ~3.8× tighter (~59k flash events; flash is the binding noise channel). mubeam/
# mustops_ce events_per_job are SHARED, so override ONLY for foilsflash here.
# Stamped-at-submit (see [[events-per-job-mid-flight-edit]]); safe for a FRESH
# campaign (kill+relaunch), NOT for mid-flight edits.
if os.environ.get("AUTORESEARCH_MODE") == "foilsflash":
    STAGES["mubeam"]["events_per_job"] = 200000
    STAGES["mustops_ce"]["events_per_job"] = 75000
    STAGES["elebeam_flash"]["events_per_job"] = 110000
    # Measured VmHWM (2026-07-09, ff09 job logs): elebeam 1311-1313 MB
    # (near-deterministic, 3 samples), mustops_ce 1129 MB. 2000 MB is ~1.5×
    # the resident peak (VmPeak ~1.4-1.7 GB is virtual) and matches the
    # standard 2 GB/core slot exactly → best matchability + smallest
    # footprint against the ~1,250-slot ceiling. Watch the first round for
    # OOM-holds on extreme geometries; bump back to 2500 if any appear.
    # See wiki/concepts/bo-noise-budget.md.
    for _s in ("mubeam", "mustops_ce", "elebeam_flash"):
        STAGES[_s]["memory_mb"] = 2000
    # Narrow 15-job stages are the erratic ones: quorum 0.9 → target 13/15
    # still waits on stragglers and one slow node ~doubles the stage (mustops
    # 75-175 min on identical payloads). 12/15 clips the tail; σ_sob 0.09%
    # has huge margin for the lost ~7% stats. elebeam keeps the 0.9 default
    # (200-wide averages stragglers; flash stats are the binding channel).
    STAGES["mubeam"]["quorum"] = 0.8
    STAGES["mustops_ce"]["quorum"] = 0.8


# EleBeamCat resampler normalization: each resampled electron corresponds to
# dh.gencount/event_count = 25e6 POT / 2,166,994 electrons ~= 11.537 POT. Used to
# turn the elebeam_flash TOTAL edep into an absolute MeV/POT rate (the flash-per-POT
# objective — the geometry-sensitive lever; the per-event MEAN divides out the
# flash-event count and is blind to it). See wiki/projects/bo-foilsflash.md.
POT_PER_ELECTRON = hv.POT_PER_ELECTRON  # single source of truth in harvest.py


def _stage_desc(stage: str) -> str:
    return STAGES[stage]["desc_fmt"].format(cfg=CONFIG)


def _stage_config_sha(stage: str) -> str:
    """Stable SHA-256 of STAGES[stage] — the per-stage config snapshot.

    Stamped at submit, re-read at harvest. Generalizes the events_per_job
    stamp (which only covered one field) to the whole stage dict.
    Path objects are coerced to str so the serialization is reproducible.
    See wiki/incidents/events-per-job-mid-flight-edit.md.
    """
    payload = json.dumps(STAGES[stage], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _stamp_stage_config_sha(stage: str) -> None:
    (STATE / f"{stage}_config_sha.txt").write_text(_stage_config_sha(stage) + "\n")


def _check_stage_config_sha(stage: str) -> None:
    """Warn (do not fail) if STAGES[stage] changed between submit and read.

    Called from cmd_poll, cmd_list_outputs, and cmd_harvest. Silent if no
    stamp file (legacy chains submitted before this guard existed).
    """
    stamp_path = STATE / f"{stage}_config_sha.txt"
    if not stamp_path.exists():
        return
    stamped = stamp_path.read_text().strip()
    current = _stage_config_sha(stage)
    if stamped != current:
        print(
            f"[pipeline] WARN: STAGES[{stage!r}] changed since submit "
            f"(stamp={stamped[:12]}, current={current[:12]}). "
            f"Downstream poll/list-outputs/harvest may use mismatched "
            f"events_per_job or quorum; see "
            f"wiki/incidents/events-per-job-mid-flight-edit.md.",
            file=sys.stderr, flush=True,
        )


def _parse_n_plates_from_geom() -> int:
    """Return targetPS_numberOfPlates from the per-config geom file.

    Returns 0 if the file or key is absent (e.g. non-Stickman geom). The
    caller decides whether 0 plates is fatal for the stage.
    """
    if not GEOM_FILE.exists():
        return 0
    for line in GEOM_FILE.read_text().splitlines():
        s = line.strip()
        if s.startswith("int targetPS_numberOfPlates"):
            return int(s.split("=", 1)[1].rstrip(";").strip())
    return 0


def _render_pt_plate_names_csv(n_plates: int) -> str:
    """Return CSV of quoted ProductionTargetPlate<NN> names for N Stickman PT
    plates. Empty string if n_plates == 0. Used for both
    g4run.SDConfig.sensitiveVolumes and ProductionTargetEdepHist.instanceNames
    (same volume list — one CSV serves both).
    """
    if n_plates <= 0:
        return ""
    names = [f"ProductionTargetPlate{i:02d}" for i in range(n_plates)]
    return ", ".join(f'"{n}"' for n in names)


def _materialize_template(stage: str) -> Path:
    """Read pipeline_templates/<stage>/template.fcl, substitute __GEOM_FILE__
    and (for pot_only) the __PT_PLATE_NAMES__ token; write to
    <STATE>/<stage>_template_materialized.fcl and return that path.
    """
    src = TEMPLATES_ROOT / stage / "template.fcl"
    text = src.read_text()
    text = text.replace("__GEOM_FILE__", GEOM_FILE.name)
    if "__PT_PLATE_NAMES__" in text:
        n = _parse_n_plates_from_geom()
        text = text.replace("__PT_PLATE_NAMES__", _render_pt_plate_names_csv(n))
    # Stamp-aware concat-less decision: the Eval's own stage-chain stamp wins
    # (written by cmd_submit before materialization); the env-derived global
    # is only the fallback for pre-stamp legacy configs.
    chain = hv.stamped_stage_chain(STATE)
    concatless = ("concat" not in chain) if chain is not None else CONCATLESS
    if stage == "mustops_ce" and concatless:
        # The shared template's MaxEventsToSkip (100720) is tuned to the
        # merged concat file (~240k events). Concat-less jobs each read ONE
        # mubeam file (~16k mu- stop events for the 37-foil base +- extras);
        # the random skip must stay below the smallest plausible file.
        text += (
            "\n# concat-less override (see graph/config.py foilsflash chain)\n"
            "physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip: 8000\n"
        )
    out = STATE / f"{stage}_template_materialized.fcl"
    out.write_text(text)
    return out


def run(cmd, *, env=None, check=True, capture=True):
    """Run a shell command; print invocation; return CompletedProcess."""
    if isinstance(cmd, list):
        printable = shlex.join(cmd)
    else:
        printable = cmd
    print(f"$ {printable}", flush=True)
    return subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        env=env,
        check=check,
        capture_output=capture,
        text=True,
    )


def sourced_env(extra="", *, with_muse=False) -> dict:
    """Return an env dict with setupmu2e-art.sh + Run1Bak musing + mu2egrid sourced.

    Use for invoking mu2ejobdef / mu2ejobsub from Python so the child process
    sees the right PATH, MU2E_*_PATH, etc. Set with_muse=True for the harvest
    step which needs the autoresearch-built EdepAna module from mmackenz's
    run1b workspace (matches autoresearch_loop.py SETUP).
    """
    if with_muse:
        # Use our own autoresearch_muse work area (same one that produces the
        # base Code.tar.bz2). `-q p094` is required: without it muse picks
        # p095 from main-HEAD's Offline/.muse and errors on the backing.
        # See wiki/external/muse-backing-pattern.md.
        #
        # EdepAna is mmackenz's Run1BAna module (not in Offline/Run1Bak). We now
        # build it into OUR OWN autoresearch_muse p094 lib (only the standalone
        # workflows/EdepAna target — the rest of Run1BAna's `evtana` needs
        # EventNtuple we don't have; EdepAna itself only needs Offline+art+ROOT).
        # Rebuild: `cd autoresearch_muse && muse setup -q p094 && muse build
        # build/al9-prof-e29-p094/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so`.
        # 2026-06-26: switched off mmackenz's hardcoded path after he bumped
        # p094→p101 and deleted it. See wiki/incidents/mmackenz-edepana-lib-qualifier-bump.md.
        mmlib = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib"
        prelude = (
            "cd /exp/mu2e/app/users/oksuzian/autoresearch_muse && "
            f"source {SETUPMU2E} >/dev/null 2>&1 && "
            "muse setup -q p094  >/dev/null 2>&1 && "
            f"export CET_PLUGIN_PATH={mmlib}:$CET_PLUGIN_PATH && "
            f"export LD_LIBRARY_PATH={mmlib}:$LD_LIBRARY_PATH && "
        )
    else:
        # `muse setup ops` (spack-native) provides the mu2egrid binaries
        # (/cvmfs/.../artexternals/mu2egrid/v8_03_02/bin/{mu2ejobsub,
        # mu2ejobdef,mu2eprodsys}) via the active Musing's env, replacing the
        # legacy UPS `setup mu2egrid`.
        # NOTE: this swap does NOT prevent rc=127. That failure comes from a
        # transient cvmfs I/O flake (==> Error: [Errno 5]) inside
        # setupmu2e-art.sh that leaves museDefine.sh unsourced and the `muse`
        # function itself undefined -- upstream of this line. The retry loop
        # below is what actually recovers it.
        # See wiki/incidents/sourced-env-stderr-swallowed.md.
        prelude = (
            f"source {SETUPMU2E} && "
            f"source {MUSING} && "
            f"muse setup ops && "
        )
    # Move spack provider cache + flock off NFS HOME -> local /tmp; under
    # concurrent setups the nashome lock races/corrupts -> [Errno 5] during
    # spack load. See wiki/incidents/foilsx04-all-preflight-ambiguous.md.
    spack_cache = f"/tmp/spack_cache_{os.environ.get('USER','x')}"
    cmd = f"export SPACK_USER_CACHE_PATH={spack_cache} && {prelude}{extra} env"
    # Transient cvmfs read flakes (==> Error: [Errno 5] Input/output error)
    # leave museDefine.sh unsourced -> `muse` undefined -> rc=127
    # "command not found". These are NOT deterministic: a re-run seconds later
    # succeeds, so retry with backoff before giving up. 8+ closed-loop children
    # were lost to this across X05/X06/X08 before retries were added. Shared
    # retry lives in graph/sourced_bash.py (run_sourced_bash).
    proc = run_sourced_bash(cmd, label="sourced_env")
    if proc.returncode != 0:
        # Persist stderr so the cause survives the CalledProcessError raise.
        # Without this, the transient cvmfs/spack flake surfaces as a bare
        # "submit <stage> failed (rc=1)" with no captured cause.
        err_dir = Path("/tmp") / f"sourced_env_errs_{os.environ.get('USER','x')}"
        err_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        err_path = err_dir / f"sourced_env_{ts}_rc{proc.returncode}.err"
        err_path.write_text(
            f"$ bash -c {shlex.quote(cmd)}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}\n"
        )
        tail = "\n".join(proc.stderr.splitlines()[-20:])
        raise subprocess.CalledProcessError(
            proc.returncode, cmd,
            output=proc.stdout,
            stderr=f"{proc.stderr}\n[sourced_env] full log: {err_path}\n[sourced_env] stderr tail:\n{tail}",
        )
    env = {}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k] = v
    return env


def write_code_tarball(stage_dir: Path, base_tarball: Path | None = None) -> Path:
    """Build Code.tar.bz2 for the --code path.

    Extracts the chosen muse-built base tarball, drops the per-config geom
    file into Code/, writes Code/setup_post.sh to extend MU2E_SEARCH_PATH +
    FHICL_FILE_PATH so the geom is found by GeometryService, then repacks.
    The base tarball's setup.sh handles all framework setup via `muse setup`,
    so local libs win by link/path order (no LD_PRELOAD).

    base_tarball overrides MUSE_BASE_TARBALL — used by stages whose backing
    musing differs from the default helical-patched Run1Bak tree (e.g.
    pot_only ships the MDC2025aq backing-only tarball).
    """
    if base_tarball is None:
        base_tarball = MUSE_BASE_TARBALL
    if not GEOM_FILE.exists():
        raise SystemExit(
            f"geom file missing: {GEOM_FILE}\n"
            f"  Run: ./autoresearch_bo_michael.py --mode <mode> propose {CONFIG}\n"
            f"  (propose auto-stages the geom into the per-config work dir)"
        )
    if not base_tarball.exists():
        raise SystemExit(f"muse base tarball missing: {base_tarball}")

    # Per-config cache (2026-07-10): the tarball content is fully determined
    # by (base_tarball, GEOM_FILE), both identical across a config's stages,
    # so build ONCE per config and reuse — was ~7-12 min of unpack+rebzip2
    # per stage per child, 2/3 of it redundant (~10 min/eval critical path +
    # 3x disk churn; see bo-noise-budget tarball lever). Guard: cache must be
    # newer than both inputs (a re-proposed geom or a rebuilt base
    # invalidates). A config's submits are serial (incl. the elebeam
    # presubmit, which runs inside the mubeam node), so no build race.
    cache = ROOT / f"Code.{base_tarball.stem.split('.')[0]}.tar.bz2"
    if (cache.exists()
            and cache.stat().st_mtime > GEOM_FILE.stat().st_mtime
            and cache.stat().st_mtime > base_tarball.stat().st_mtime):
        print(f"[tarball] reusing cached {cache.name}", flush=True)
        return cache

    code_dir = stage_dir / "Code"
    if code_dir.exists():
        shutil.rmtree(code_dir)
    run(["tar", "xjf", str(base_tarball), "-C", str(stage_dir)])
    shutil.copy(GEOM_FILE, code_dir / GEOM_FILE.name)
    (code_dir / "setup_post.sh").write_text(
        'export MU2E_SEARCH_PATH="$CODE_DIR:$MU2E_SEARCH_PATH"\n'
        'export FHICL_FILE_PATH="$CODE_DIR:$FHICL_FILE_PATH"\n'
    )
    tarball = stage_dir / "Code.tar.bz2"
    if tarball.exists():
        tarball.unlink()
    run(["bash", "-c", f"cd {stage_dir} && tar cf - Code/ | bzip2 > {tarball.name}"])
    tmp = cache.with_suffix(".tmp")
    shutil.move(tarball, tmp)
    tmp.rename(cache)  # atomic within ROOT: readers never see a partial file
    shutil.rmtree(code_dir, ignore_errors=True)
    return cache


def stage_hardlink_farm(stage: str, source_paths: list[Path]) -> tuple[Path, Path]:
    """Build a /pnfs hard-link farm so all input files appear in one dir.

    Needed because mu2ejobdef's --inputs only accepts basenames, and
    mu2ejobsub's --default-location dir:DIR assumes all files live in DIR.
    Hard links (not symlinks): xrootd doors don't follow /pnfs symlinks, but
    hard links share the same dCache namespace entry. Returns (staged_dir, basenames_file).
    """
    staged_dir = PNFS_STAGE / stage
    if staged_dir.exists():
        for p in staged_dir.iterdir():
            p.unlink()
    else:
        staged_dir.mkdir(parents=True, exist_ok=True)
    basenames = []
    for src in source_paths:
        link = staged_dir / src.name
        os.link(src, link)
        basenames.append(src.name)
    basenames_file = STATE / f"{stage}_basenames.txt"
    basenames_file.write_text("\n".join(basenames) + "\n")
    print(f"[{stage}] hard-linked {len(basenames)} files into {staged_dir}")
    return staged_dir, basenames_file


def _grid_setup_sh() -> str:
    """Worker-visible setup script for stages submitted with --setup.

    MUSING may point at a LOCAL patched workdir's setup_local.sh (preflight
    parity with the patched grid tarball — see
    wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md).
    Grid workers cannot see /exp, and the --setup path is sourced ON the
    worker (mu2ejobsub.sh) — handing it a local path kills the job at setup
    (foilsgV01 concat, 2026-06-12). Stages that use --setup instead of
    --code (concat) run no geometry code, so the workdir's cvmfs *backing*
    Musing is always sufficient: resolve it from the `backing` symlink.
    """
    if MUSING.startswith("/cvmfs/"):
        return MUSING
    backing = Path(MUSING).parent / "backing"
    target = Path(os.path.realpath(backing))
    if not str(target).startswith("/cvmfs/"):
        raise SystemExit(
            f"MUSING {MUSING} is local and {backing} does not resolve to a "
            f"/cvmfs Musing — cannot build a worker-visible --setup jobdef"
        )
    return str(target / "setup.sh")


def _probe_input_urls(stage: str, fcl_text: str) -> None:
    """Verify job-0's resolved input files are readable BEFORE submitting.

    EleBeamCat migrated persistent→tape mid-campaign (2026-07-09) and every
    elebeam job died at FileOpenError ~30 s in: the URL comes from OUR
    --default-location flag ('disk'==persistent), not SAM, so a stale
    location silently kills the whole cluster. Probing the first resolved
    URLs turns 200 dead jobs into one loud submit-time error.
    xroot://fndcadoor.fnal.gov//pnfs/fnal.gov/usr/mu2e/X maps to /pnfs/mu2e/X
    for a cheap NFS read probe; non-matching URLs are skipped (fail-open).
    See wiki incident elebeamcat-tape-migration-elebeam-wipeout.
    """
    urls = re.findall(r'"(xroot://[^"]+\.art)"', fcl_text)
    probes = []
    for u in dict.fromkeys(urls):
        m = re.match(r"xroot://fndcadoor\.fnal\.gov//pnfs/fnal\.gov/usr/mu2e/(.+)", u)
        if m:
            probes.append(Path("/pnfs/mu2e") / m.group(1))
        if len(probes) >= 2:
            break
    for p in probes:
        r = subprocess.run(["timeout", "10", "dd", f"if={p}", "of=/dev/null",
                            "bs=64k", "count=1"], capture_output=True)
        if r.returncode != 0:
            raise SystemExit(
                f"[{stage}] input probe FAILED: {p} not readable — dataset "
                f"moved (persistent→tape?) or wrong default_loc; fix "
                f"STAGES['{stage}']['default_loc'] before submitting. "
                f"See wiki elebeamcat-tape-migration-elebeam-wipeout.")
        print(f"[{stage}] input probe OK: {p.name}", flush=True)


def submit_stage(stage: str, env: dict, *, inputs_file: Path | None = None,
                 staged_input_dir: Path | None = None, dry_run: bool = False) -> int | None:
    """Build cnf via mu2ejobdef, smoke-test with mu2ejobfcl, submit via mu2ejobsub.

    Returns the cluster id (or None for dry-run).
    """
    cfg = STAGES[stage]
    desc = _stage_desc(stage)
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Materialize the template (substitute geom basename) into state/.
    template_fcl = _materialize_template(stage)

    dsconf = _stage_dsconf(stage)
    cnf = stage_dir / f"cnf.{USER}.{desc}.{dsconf}.0.tar"
    if cnf.exists():
        print(f"[{stage}] removing existing cnf: {cnf.name}")
        cnf.unlink()

    jobdef = ["mu2ejobdef", "--dsconf", dsconf, "--dsowner", USER, "--desc", desc,
              "--embed", str(template_fcl)]
    if cfg["ships_geom"]:
        base = Path(cfg["code_tarball"]) if "code_tarball" in cfg else None
        tarball = write_code_tarball(stage_dir, base_tarball=base)
        jobdef += ["--code", str(tarball)]
    else:
        jobdef += ["--setup", _grid_setup_sh()]
    if "events_per_job" in cfg:
        jobdef += ["--run-number", str(cfg["run_number"]),
                   "--events-per-job", str(cfg["events_per_job"])]
        # Stamp the per-stage events_per_job at submit time so harvest reads
        # the actual value used, not the current (possibly edited) dict.
        # Without this, editing STAGES[*]["events_per_job"] between submit
        # and harvest mis-scales ce_simulated_events / mubeam_sim_total
        # → biases sob (helicalP01 false high, 2026-05-21).
        (STATE / f"{stage}_events_per_job.txt").write_text(
            f"{cfg['events_per_job']}\n"
        )
    if "merge_factor" in cfg:
        if inputs_file is None:
            raise SystemExit(f"[{stage}] needs --inputs file but none provided")
        jobdef += ["--inputs", str(inputs_file), "--merge-factor", str(cfg["merge_factor"])]
    if "auxinput" in cfg:
        jobdef += [f"--auxinput={cfg['auxinput']}"]

    # mu2ejobdef writes cnf.* in cwd
    print(f"$ (cd {stage_dir} && {shlex.join(jobdef)})", flush=True)
    subprocess.run(jobdef, cwd=stage_dir, env=env, check=True)

    # smoke-test: ask mu2ejobfcl to print job-0's resolved fcl, then probe
    # that the resolved input URLs are actually readable (liveness gate).
    default_loc = f"dir:{staged_input_dir}" if staged_input_dir else cfg["default_loc"]
    fcl_check = ["mu2ejobfcl", "--jobdef", cnf.name, "--index", "0",
                 "--default-proto", "root", "--default-loc", default_loc]
    print(f"$ (cd {stage_dir} && {shlex.join(fcl_check)})", flush=True)
    fcl_proc = subprocess.run(fcl_check, cwd=stage_dir, env=env, check=True,
                              capture_output=True, text=True)
    _probe_input_urls(stage, fcl_proc.stdout)

    if dry_run:
        print(f"[{stage}] DRY-RUN: would submit {cfg['njobs']} job(s)")
        return None

    # Host-wide serialization of the token-refresh + submit block. Under
    # concurrent load condor_vault_storer races; the lock guarantees only one
    # process at a time touches the bearer token + mu2ejobsub.
    with _submit_lock(stage):
        print(f"[{stage}] renewing bearer token: getToken", flush=True)
        # getToken sources setupmu2e-art.sh, so it shares the cvmfs/spack flake
        # class -> route through the shared retry helper (was bare check=True).
        tok = run_sourced_bash(f"source {SETUPMU2E} >/dev/null 2>&1 && getToken",
                               label=f"{stage}/getToken")
        if tok.stdout.strip():
            print(tok.stdout)
        if tok.returncode != 0:
            raise subprocess.CalledProcessError(
                tok.returncode, "getToken", output=tok.stdout, stderr=tok.stderr)

        submit = ["mu2ejobsub", "--jobdef", cnf.name,
                  "--firstjob", "0", "--njobs", str(cfg["njobs"]),
                  "--default-location", default_loc, "--default-protocol", "root",
                  "--predefined-args=al9"]
        if "memory_mb" in cfg:
            submit += ["--memory", f"{cfg['memory_mb']}MB"]
        print(f"[{stage}] submitting: {shlex.join(submit)}")
        try:
            out = subprocess.run(submit, cwd=stage_dir, env=env, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            # check=True raises BEFORE the print lines below, and str(exc) omits
            # stderr → every mu2ejobsub rc!=0 was opaque (see wiki
            # jobsub-disk-quota-stderr-swallowed). Surface stdout+stderr into the
            # submit log before re-raising so the real cause is diagnosable.
            print(e.stdout or "")
            print("MU2EJOBSUB STDERR:\n" + (e.stderr or "(empty)"), file=sys.stderr)
            raise
        print(out.stdout)
        if out.stderr.strip():
            print("STDERR:", out.stderr, file=sys.stderr)

        # parse "<N> job(s) submitted to cluster <CLUSTER>."
        m = re.search(r"submitted to cluster\s+(\d+)", out.stdout)
        if not m:
            raise SystemExit(f"[{stage}] could not parse cluster id from mu2ejobsub output")
        cluster = int(m.group(1))
        (STATE / f"{stage}_cluster.txt").write_text(f"{cluster}\n")
        _stamp_stage_config_sha(stage)
        print(f"[{stage}] cluster={cluster}")
        return cluster


def poll_cluster(stage: str, cluster: int, *, quorum: float = 0.9, cap_hours: float = 24.0) -> None:
    """Wait until stage-out convergence (or wall-clock cap).

    Convergence = (jobs left queue >= target) AND (settled bare-form
    outstage dirs >= target). Polling jobsub_q alone is a lying proxy:
    jobs exit the queue when they *start finishing*, but stage-out
    (worker -> /pnfs copy + jobsub_lite hash->bare rename) is async and
    lags by minutes. Without the outstage check, list_outputs would race
    with stage-out and SystemExit on a missing base or undercount on a
    partial dir. By gating poll on the same /pnfs ls that list_outputs
    ultimately reads, we make list_outputs's precondition structural,
    not hopeful. See wiki/incidents/stage-out-lag.md.
    """
    cfg = STAGES[stage]
    target = max(1, int(cfg["njobs"] * quorum))
    base = OUTSTAGE / str(cluster) / "00"
    deadline = time.time() + cap_hours * 3600
    while time.time() < deadline:
        out = subprocess.run(
            ["jobsub_q", "-G", "mu2e", f"--user={USER}",
             "--constraint", f"ClusterId=={cluster}"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            # Don't silently treat a jobsub_q failure as "queue is empty" - that
            # let the poll claim 200/200 finished within seconds of submission.
            print(f"WARN: jobsub_q rc={out.returncode}; will retry. stderr:\n{out.stderr}",
                  file=sys.stderr)
            time.sleep(60)
            continue
        in_queue = sum(1 for line in out.stdout.splitlines()
                       if re.match(rf"^{cluster}\.\d+@", line))
        finished_q = cfg["njobs"] - in_queue
        if base.exists():
            # settled = bare-form (`00000`) only. jobsub_lite stages into
            # hash form (`00000.6d475c59`), then renames to bare ONCE THE
            # JOB EXITS ZERO. A perma-hash dir is either rename-in-flight
            # or a FAILED job that wrote only the log — counting it as
            # settled risks declaring success on a cluster where every job
            # crashed. See wiki/incidents/stage-out-rename-race.md and
            # concat-xrootd-fileopen-postendjob.md.
            settled = sum(1 for d in base.iterdir() if d.name.isdigit())
            # all_dirs = bare + hash-suffix. If queue is drained AND every
            # job has produced *some* dir (bare or hash), stage-out is done
            # one way or another; let list_outputs sort it out (it drains
            # the genuine rename-in-flight tail and warns on the rest).
            all_dirs = sum(1 for d in base.iterdir()
                           if d.name.split(".", 1)[0].isdigit())
        else:
            settled = 0
            all_dirs = 0
        ts = dt.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{stage} cluster={cluster}] "
              f"queue:{finished_q}/{cfg['njobs']} settled:{settled}/{cfg['njobs']} "
              f"(target={target})", flush=True)
        if finished_q >= target and settled >= target:
            print(f"[{stage}] converged (queue={finished_q}, settled={settled})")
            return
        # Failure-aware exit: queue fully drained AND every job left some
        # outstage dir (bare or hash). Bare-count <target means jobs failed;
        # break loudly so list_outputs + harvest surface the failure rather
        # than hang forever waiting for a rename that will never happen.
        if in_queue == 0 and all_dirs >= cfg["njobs"] and settled < target:
            print(f"[{stage}] WARN: queue drained, all {cfg['njobs']} dirs "
                  f"present but only {settled}/{target} settled (bare-form). "
                  f"{all_dirs - settled} dir(s) stuck in hash form — likely "
                  f"failed jobs (e.g. xrootd PostEndJob). Proceeding so "
                  f"list_outputs + harvest fail loudly.")
            return
        time.sleep(120)
    print(f"[{stage}] WARN: 24h cap hit, proceeding with whatever landed")


def list_outputs(stage: str, cluster: int) -> list[Path]:
    """Glob outstage for stage outputs; persist as <stage>_outputs.txt.

    Precondition: poll_cluster has converged, so `base` exists with at
    least `quorum * njobs` bare-form subdirs. /pnfs may still be renaming
    a small tail of hash-suffix subdirs; we drain those before globbing
    so bare-only enumeration doesn't undercount. See incidents
    stage-out-lag and stage-out-rename-race.
    """
    cfg = STAGES[stage]
    base = OUTSTAGE / str(cluster) / "00"
    if not base.exists():
        # poll_cluster's convergence gate is supposed to guarantee this.
        # If it fires, the gate has a bug or the cap-hours warning path
        # let us through with nothing on disk - either way, fail loudly.
        raise SystemExit(f"[{stage}] outstage missing after poll converged: {base}")

    pattern = f"[0-9][0-9][0-9][0-9][0-9]/{cfg['output_glob']}"
    for attempt in range(20):  # 20 × 30s = 10 min cap
        pending = [d.name for d in base.iterdir()
                   if "." in d.name and d.name.split(".", 1)[0].isdigit()]
        if not pending:
            break
        print(f"[{stage}] {len(pending)} job dir(s) still mid-rename "
              f"(e.g. {pending[0]}); sleeping 30s "
              f"(attempt {attempt + 1}/20)")
        time.sleep(30)
    else:
        print(f"[{stage}] WARN: rename pass did not quiesce after 10 min; "
              f"globbing bare form anyway (may undercount)")

    files = sorted(base.glob(pattern))
    out_list = STATE / f"{stage}_outputs.txt"
    out_list.write_text("\n".join(str(f) for f in files) + "\n")
    print(f"[{stage}] {len(files)} output file(s) -> {out_list}")
    return files


def cmd_submit(args):
    # Idempotency guard: if a prior submit already produced a cluster file,
    # treat re-entry as a no-op so a killed-and-resumed graph node doesn't
    # double-submit. --force overrides.
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    if cluster_file.exists() and not getattr(args, "force", False):
        cid = cluster_file.read_text().strip()
        print(f"[{args.stage}] already submitted (cluster={cid}); skip submit "
              f"(use --force to override)")
        return
    # Stage-chain stamp: record THIS Eval's chain at first submit so harvest
    # and template materialization never re-interpret an old config under the
    # current env's chain (the ff11R00_07 +1.5% sob bias class). One owner:
    # harvest.resolve_muminus_inputs / stamped_stage_chain.
    if not (STATE / hv.STAGE_CHAIN_STAMP).exists():
        hv.stamp_stage_chain(STATE, list(GRID_STAGES))
    env = sourced_env()
    inputs_file = None
    staged_input_dir = None
    if args.stage == "concat":
        mubeam_list = STATE / "mubeam_outputs.txt"
        if not mubeam_list.exists():
            raise SystemExit("Run 'list-outputs mubeam' first to populate mubeam_outputs.txt")
        sources = [Path(p) for p in mubeam_list.read_text().splitlines() if p.strip()]
        staged_input_dir, inputs_file = stage_hardlink_farm("concat", sources)
    elif args.stage in ("mustops_ce", "mustops_pileup"):
        # Both resample concat MuminusStopsCat via TargetStopResampler
        # (mustops_pileup's capture-product generators inside MuStopPileup.fcl
        # then turn each stop into protons/etc. through the IPA + detector;
        # see bo-ipa wiki). auxinput list file requires basenames (same
        # restriction as --inputs): hard-link concat outputs into a /pnfs
        # stage dir so xrootd can resolve them when --default-location
        # dir:STAGED expands the basenames.
        # Concat-less chains resample the mu--pure mubeam TargetStops files
        # directly (auxinput=1 -> one file-slice per job, same structure as
        # mubeam<->MuBeamCat).
        prev_stage = "mubeam" if CONCATLESS else "concat"
        prev = STATE / f"{prev_stage}_outputs.txt"
        if not prev.exists():
            raise SystemExit(f"Run 'list-outputs {prev_stage}' first to populate {prev.name}")
        sources = [Path(p) for p in prev.read_text().splitlines() if p.strip()]
        staged_input_dir, basenames_file = stage_hardlink_farm(args.stage, sources)
        STAGES[args.stage]["auxinput"] = (
            f"1:physics.filters.TargetStopResampler.fileNames:{basenames_file}"
        )
    submit_stage(args.stage, env, inputs_file=inputs_file,
                 staged_input_dir=staged_input_dir, dry_run=args.dry_run)


def cmd_poll(args):
    _check_stage_config_sha(args.stage)
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    cluster = int(cluster_file.read_text().strip())
    quorum = args.quorum if args.quorum is not None else STAGES[args.stage].get("quorum", 0.9)
    poll_cluster(args.stage, cluster, quorum=quorum, cap_hours=args.cap_hours)


def cmd_list_outputs(args):
    _check_stage_config_sha(args.stage)
    # Idempotency guard: if outputs were already listed and every basename
    # still resolves on /pnfs, skip the re-glob. --force overrides.
    outputs_file = STATE / f"{args.stage}_outputs.txt"
    if outputs_file.exists() and not getattr(args, "force", False):
        paths = [p for p in outputs_file.read_text().splitlines() if p.strip()]
        if paths and all(Path(p).exists() for p in paths):
            print(f"[{args.stage}] outputs already listed ({len(paths)} files); "
                  f"skip (use --force to override)")
            return
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    cluster = int(cluster_file.read_text().strip())
    list_outputs(args.stage, cluster)


def cmd_materialize(args):
    """Debug helper: write the materialized template to --out (or stdout)."""
    out = _materialize_template(args.stage)
    if args.out:
        Path(args.out).write_text(out.read_text())
        print(f"[{args.stage}] materialized -> {args.out}")
    else:
        sys.stdout.write(out.read_text())


# Constant from extract_analysis_results._MUBEAM_INPUT_EFFICIENCY_BY_FCL["run1a_beam/mubeam.fcl"].
# This is the fraction of upstream POT that survive into the MuBeamCat resampler input,
# needed to convert per-simulated-event yields into per-POT yields.
RUN1A_MUBEAM_INPUT_CORRECTION = hv.RUN1A_MUBEAM_INPUT_CORRECTION  # single source in harvest.py

# Path to the autoresearch repo so we can find the EdepAna fcl + ROOT macro.
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
EDEP_FCL = AUTORESEARCH / "Run1BAna/workflows/fcl/edep.fcl"
SENSITIVITY_MACRO = AUTORESEARCH / "Run1BAna/workflows/scripts/rough_run1a_sensitivity.C"

# Accept scientific notation: EdepAna prints the count via %g, so >1M events come
# out as e.g. "Saw 2.70937e+06 events" (foilsflash's big mustops_ce). \d+ alone
# missed those → false "summary not found" → harvest_exception zero rows. float()
# then int() handles both "2709366" and "2.70937e+06" (the ~4-event rounding from
# %g is negligible vs 2.7M). See bo-foilsflash harvest-sci-notation fix.
# EdepAna / sensitivity-macro parsers live in harvest.py (parse_edepana_saw,
# parse_s_over_sqrt_b) — incl. the sci-notation fix, regression-tested there.

# TargetMuonFinder/stopmat bin labels (mmackenz extract_analysis_results._CALO_STOP_MATERIALS)
_CALO_STOP_MATERIALS = ("G4_CESIUM_IODIDE", "CarbonFiber", "AluminumHoneycomb")

# bo-ipa: sum tracker StrawGasStep ionizing Edep in the MuStopPileup stream
# (capture products from muon stops on the Al target — proton-dominated). This
# is the IPA's second objective: the energy the absorber is meant to keep out of
# the tracker. Uses gallery (uproot can't read StrawGasStep — see wiki
# uproot-cannot-read-steppointmc). v1 sums ALL capture-product StrawGasStep
# Edep (proton-dominated); a proton-only filter (SimParticle Ptr → pdg 2212) is
# a future refinement. InputTag is auto-discovered from candidate labels since
# the kept compressed-StrawGasStep label/instance is only confirmable on a real
# MuStopPileup dts file (validate + pin in the first live smoke).
_TRK_EDEP_CANDIDATE_TAGS = ("compressDetStepMCs", "compressDetStepMCs:tracker",
                            "makeSGS")
_TRK_EDEP_EXTRACT_SCRIPT = r"""
import json, sys
import ROOT
ROOT.gSystem.Load("libgallery")
data = json.loads(sys.stdin.read())
files, tags = data["files"], data["tags"]
# One gallery.Event PER FILE (2026-07-10): per-file totals feed the
# Winsorized robust flash estimate (per-job tails are 25-35% and a plain
# mean is maximally tail-sensitive — see bo-noise-budget run-level sigma).
# Templated gallery method MUST use the [Type] subscript idiom in PyROOT;
# getValidHandle(<type-object>) fails template resolution (2026-06-19).
total = 0.0; n_events = 0; used = ""; per_file = []
for path in files:
    fv = ROOT.vector("string")()
    fv.push_back(path)
    try:
        ev = ROOT.gallery.Event(fv)
        getH = ev.getValidHandle[ROOT.std.vector("mu2e::StrawGasStep")]
    except Exception as e:
        print("TRKEDEP_RESULT " + json.dumps({"error": "gallery/StrawGasStep init (%s): %s" % (path, e)})); sys.exit(0)
    cand = list(zip(tags, [ROOT.art.InputTag(t) for t in tags]))
    ftot = 0.0; fn = 0
    while not ev.atEnd():
        prod = None
        trylist = [(used, ROOT.art.InputTag(used))] if used else cand
        for tname, it in trylist:
            try:
                prod = getH(it).product(); used = tname; break
            except Exception:
                continue
        if prod is not None:
            for s in prod:
                try:
                    ftot += s.ionizingEdep()
                except Exception:
                    pass
        fn += 1
        ev.next()
    per_file.append(ftot)
    total += ftot; n_events += fn
print("TRKEDEP_RESULT " + json.dumps({"total_edep_MeV": total, "n_events": n_events, "tag": used, "per_file": per_file}))
"""


def _extract_trk_edep_per_pot(pileup_files, env):
    """Mean tracker StrawGasStep ionizing Edep (MeV) per MuStopPileup event.

    Returns (trk_edep_per_event, total_edep_MeV, n_events, tag). This is the
    bo-ipa second objective (proportional to per-POT since every IPA config
    resamples the same TargetStops population, so the per-event mean is a
    consistent objective across the BO). Gallery requires the muse env, so we
    shell out to a python subprocess that inherits `env` (same pattern as calo).
    """
    if not pileup_files:
        return None, None, None, None
    proc = subprocess.run(
        ["python3", "-c", _TRK_EDEP_EXTRACT_SCRIPT],
        input=json.dumps({"files": [str(p) for p in pileup_files],
                          "tags": list(_TRK_EDEP_CANDIDATE_TAGS)}),
        env=env, capture_output=True, text=True, check=True,
    )
    # gallery/xrootd prints "Closing file, read N bytes" to stdout AFTER our
    # result, so don't trust the last line — find the sentinel-prefixed line.
    marker = [ln for ln in proc.stdout.splitlines() if ln.startswith("TRKEDEP_RESULT ")]
    if not marker:
        raise RuntimeError(f"no TRKEDEP_RESULT line in extractor stdout; tail={proc.stdout.strip()[-200:]}")
    result = json.loads(marker[-1][len("TRKEDEP_RESULT "):])
    if "error" in result:
        raise RuntimeError(result["error"])
    total = result["total_edep_MeV"]
    n_events = result["n_events"]
    per_file = result.get("per_file")
    if not n_events:
        return None, total, n_events, result.get("tag"), per_file
    return total / n_events, total, n_events, result.get("tag"), per_file


_CALO_EXTRACT_SCRIPT = r"""
import json, sys
import ROOT
files = json.loads(sys.stdin.read())
mats = set({mats!r})
total_calo = 0.0
files_seen = 0
for path in files:
    tfile = ROOT.TFile.Open(path, "READ")
    if not tfile or tfile.IsZombie():
        continue
    hist = tfile.Get("TargetMuonFinder/stopmat")
    if not hist:
        tfile.Close()
        continue
    files_seen += 1
    xaxis = hist.GetXaxis()
    for b in range(1, xaxis.GetNbins() + 1):
        if xaxis.GetBinLabel(b) in mats:
            total_calo += float(hist.GetBinContent(b))
    tfile.Close()
print(json.dumps({{"total_calo": total_calo, "files_seen": files_seen}}))
"""


def _events_per_job(stage: str) -> int:
    """Resolve the per-stage events_per_job actually used at submit time.

    Reads STATE/<stage>_events_per_job.txt (stamped by submit_stage). Falls back
    to STAGES[stage]["events_per_job"] for chains submitted before the stamping
    fix landed (2026-05-21). Without this, editing STAGES[*]["events_per_job"]
    between submit and harvest mis-scales metrics — see helicalP01 incident.
    """
    stamp = STATE / f"{stage}_events_per_job.txt"
    if stamp.exists():
        return int(stamp.read_text().strip())
    return STAGES[stage]["events_per_job"]


def _extract_calo_per_pot(run1b_files, env):
    """Sum TargetMuonFinder/stopmat calo bins across run1b_mubeam nts files.

    Returns calo_per_pot = (sum calo entries / total simulated events) * input_corr.
    Mirrors mmackenz extract_analysis_results._extract_target_al_entries.

    PyROOT requires the muse env (PYTHONPATH on cvmfs); this process was launched
    without it, so we shell out to a python subprocess that inherits `env`.
    """
    if not run1b_files:
        return None, None, None
    # Use len(run1b_files), not STAGES.njobs — same OOM-bias rationale as ce branch.
    total_events = len(run1b_files) * _events_per_job("run1b_mubeam")

    script = _CALO_EXTRACT_SCRIPT.format(mats=list(_CALO_STOP_MATERIALS))
    proc = subprocess.run(
        ["python3", "-c", script],
        input=json.dumps([str(p) for p in run1b_files]),
        env=env, capture_output=True, text=True, check=True,
    )
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    total_calo = result["total_calo"]
    files_seen = result["files_seen"]
    if files_seen == 0:
        return None, None, None
    calo_per_event = total_calo / total_events
    calo_per_pot = calo_per_event * RUN1A_MUBEAM_INPUT_CORRECTION
    return calo_per_pot, total_calo, files_seen


def _count_events_art(art_path: Path, env: dict, harvest_dir: Path) -> int:
    """Run a tiny mu2e job that just opens art_path and reports events."""
    fcl = harvest_dir / "count_events.fcl"
    fcl.write_text(
        '#include "Offline/fcl/minimalMessageService.fcl"\n'
        "process_name: count\n"
        "source: { module_type: RootInput }\n"
        "services: { message: @local::default_message }\n"
        "physics: {}\n"
    )
    log = harvest_dir / f"count_{art_path.stem}.log"
    proc = subprocess.run(
        ["mu2e", "-c", str(fcl), "-s", str(art_path), "-n", "-1"],
        cwd=harvest_dir, env=env, capture_output=True, text=True, check=True,
    )
    log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    m = re.search(r"TrigReport Events total =\s*(\d+)", proc.stdout)
    if not m:
        raise SystemExit(f"could not parse event count from {art_path} (see {log})")
    return int(m.group(1))


def cmd_harvest_pot_only(args):
    """Aggregate pot_only outputs into mu_per_POT + per-plate edep via uproot.

    Reads nts.*.POT_vd.*.root files listed in STATE/pot_only_outputs.txt:
      - readVD/ntvd                 -> mu count (|pdg|==13, sid==8)
      - genCountLogger/numEvents    -> exact POT per job
      - ptEdepHist/ptEdepHist/edep_MeV         -> per-plate total energy deposit (TH1D)
      - ptEdepHist/ptEdepHist/nielEdep_MeV     -> per-plate non-ionizing edep (TH1D)

    The per-plate TH1Ds are emitted by the custom ProductionTargetEdepHist
    analyzer in autoresearch_muse_prodtarget (uproot-readable; avoids the
    StepPointMC memberwise wall — wiki/incidents/
    steppointmcdumper-no-edep.md). edep histograms are missing on rows
    submitted before that wiring landed; those rows degrade to
    edep_per_POT_MeV=None (mu half still lands).
    """
    import numpy as np
    import uproot

    _check_stage_config_sha("pot_only")
    outputs_file = STATE / "pot_only_outputs.txt"
    if not outputs_file.exists():
        raise SystemExit(f"missing {outputs_file}; run list-outputs pot_only first")
    files = [Path(p) for p in outputs_file.read_text().splitlines() if p.strip()]
    if not files:
        raise SystemExit("pot_only outputs file is empty")

    harvest_dir = ROOT / "harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)

    total_mu = 0
    total_pot = 0
    edep_per_plate_MeV = None  # numpy array, allocated lazily on first hit
    niel_per_plate_MeV = None
    files_seen = 0
    files_with_edep = 0
    files_skipped = []
    for path in files:
        try:
            with uproot.open(path) as f:
                tree = f["readVD/ntvd"]
                arrs = tree.arrays(["sid", "pdg"], library="np")
                total_mu += int(((np.abs(arrs["pdg"]) == 13) & (arrs["sid"] == 8)).sum())
                total_pot += int(f["genCountLogger/numEvents"].values()[0])
                # Per-plate edep histograms (optional — pre-wiring files
                # lack ptEdepHist/). uproot's TH1D.values() drops the
                # under/overflow bins, so the length matches N_plates.
                if "ptEdepHist/ptEdepHist/edep_MeV" in f:
                    e = f["ptEdepHist/ptEdepHist/edep_MeV"].values()
                    n = f["ptEdepHist/ptEdepHist/nielEdep_MeV"].values()
                    if edep_per_plate_MeV is None:
                        edep_per_plate_MeV = np.zeros_like(e, dtype=float)
                        niel_per_plate_MeV = np.zeros_like(n, dtype=float)
                    edep_per_plate_MeV += e
                    niel_per_plate_MeV += n
                    files_with_edep += 1
                files_seen += 1
        except Exception as e:  # noqa: BLE001
            print(f"WARN skipping {path}: {e}")
            files_skipped.append(str(path))

    total_edep_MeV = float(edep_per_plate_MeV.sum()) if edep_per_plate_MeV is not None else 0.0
    total_niel_MeV = float(niel_per_plate_MeV.sum()) if niel_per_plate_MeV is not None else 0.0
    summary = {
        "config": CONFIG,
        "mu_per_POT": (total_mu / total_pot) if total_pot else None,
        "edep_per_POT_MeV": (total_edep_MeV / total_pot) if (total_pot and files_with_edep) else None,
        "niel_per_POT_MeV": (total_niel_MeV / total_pot) if (total_pot and files_with_edep) else None,
        "total_mu": total_mu,
        "total_edep_MeV": total_edep_MeV,
        "total_niel_MeV": total_niel_MeV,
        "total_pot": total_pot,
        "edep_per_plate_MeV": edep_per_plate_MeV.tolist() if edep_per_plate_MeV is not None else None,
        "niel_per_plate_MeV": niel_per_plate_MeV.tolist() if niel_per_plate_MeV is not None else None,
        "files_seen": files_seen,
        "files_with_edep": files_with_edep,
        "files_skipped": files_skipped,
    }
    (harvest_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


def cmd_harvest(args):
    """Compute s_over_sqrt_b from the smoke pipeline outputs.

    Steps (mirrors extract_analysis_results.run_rough_run1a_sensitivity_analysis):
      1. Run EdepAna on mustops_ce CeEndpoint art files -> nts ROOT + 'Saw N' line
      2. Count events in concat MuminusStopsCat -> muminus_stops_events
      3. ce_scale = input_corr * (muminus_stops / mubeam_sim_total) / ce_simulated_events
         ce_abs_eff = ce_seen * ce_scale
      4. Run rough_run1a_sensitivity.C -> parse 'S/sqrt(B) = X'
    """
    # Check config-sha only for stages this run actually produced. The IPA
    # chain drops run1b_mubeam (foils-calo-only) and adds mustops_pileup, so
    # key off the stamped config_sha files rather than a hardcoded tuple.
    for stage in ("mubeam", "run1b_mubeam", "concat", "mustops_ce",
                  "mustops_pileup", "elebeam_flash"):
        if (STATE / f"{stage}_config_sha.txt").exists():
            _check_stage_config_sha(stage)
    env = sourced_env(with_muse=True)
    harvest_dir = ROOT / "harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)

    ce_files = [Path(p) for p in (STATE / "mustops_ce_outputs.txt").read_text().splitlines() if p.strip()]
    if not ce_files:
        raise SystemExit("No mustops_ce outputs to harvest")
    # Stamp+presence-driven, NOT env-driven (ff11R00_07 +1.5% sob bias):
    # harvest.resolve_muminus_inputs owns the "did concat run for THIS Eval"
    # decision (stage-chain stamp first, file presence for legacy configs).
    muminus_files, muminus_source = hv.resolve_muminus_inputs(STATE)

    # Derive denominators from the actual files we'll harvest, not STAGES.njobs
    # — if any grid jobs were lost (OOM, held), STAGES.njobs over-counts and biases
    # ce_abs_eff / s_over_sqrt_b high by the loss fraction. See A/B test on
    # helical001 (2026-05-16) which surfaced this.
    mubeam_files = [Path(p) for p in (STATE / "mubeam_outputs.txt").read_text().splitlines() if p.strip()]
    mubeam_sim_total = len(mubeam_files) * _events_per_job("mubeam")
    ce_simulated_events = len(ce_files) * _events_per_job("mustops_ce")

    print(">>> Step 1: EdepAna on CeEndpoint outputs")
    ce_list = harvest_dir / "ce_files.txt"
    ce_list.write_text("\n".join(str(p) for p in ce_files) + "\n")
    nts_path = harvest_dir / "nts.ce.root"
    wrapper = harvest_dir / "edep_wrapper.fcl"
    wrapper.write_text(
        f'#include "{EDEP_FCL.relative_to(AUTORESEARCH).as_posix()}"\n'
        f'services.TFileService.fileName: "{nts_path.name}"\n'
    )
    edep_log = harvest_dir / "edep.log"
    proc = subprocess.run(
        ["mu2e", "-c", str(wrapper), "-S", str(ce_list)],
        cwd=harvest_dir, env={**env, "FHICL_FILE_PATH": f"{AUTORESEARCH}:{env.get('FHICL_FILE_PATH','')}"},
        capture_output=True, text=True, check=False,
    )
    edep_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"EdepAna failed (rc={proc.returncode}); see {edep_log}")
    try:
        ce_seen = hv.parse_edepana_saw(proc.stdout)
    except ValueError as e:
        raise SystemExit(f"{e}; see {edep_log}")

    print(">>> Step 2: counting events in MuminusStopsCat")
    muminus_stops = sum(_count_events_art(f, env, harvest_dir) for f in muminus_files)

    stopping_factor = muminus_stops / mubeam_sim_total
    ce_scale = RUN1A_MUBEAM_INPUT_CORRECTION * stopping_factor / ce_simulated_events
    ce_abs_eff = ce_seen * ce_scale

    print(f"    ce_seen             = {ce_seen}")
    print(f"    muminus_stops       = {muminus_stops}")
    print(f"    mubeam_sim_total    = {mubeam_sim_total}")
    print(f"    ce_simulated_events = {ce_simulated_events}")
    print(f"    stopping_factor     = {stopping_factor:.6g}")
    print(f"    ce_abs_eff          = {ce_abs_eff:.6g}")

    print(">>> Step 4: rough_run1a_sensitivity.C")
    macro_log = harvest_dir / "rough_run1a_sensitivity.log"
    cwd = SENSITIVITY_MACRO.parent.parent
    cmd = ["root", "-q", "-b", "-l",
           f'scripts/rough_run1a_sensitivity.C("{nts_path}", {ce_abs_eff:.16g}, "{harvest_dir}")']
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    macro_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"rough_run1a_sensitivity.C failed (rc={proc.returncode}); see {macro_log}")
    try:
        s_over_sqrt_b = hv.parse_s_over_sqrt_b(proc.stdout)
    except ValueError as e:
        raise SystemExit(f"{e}; see {macro_log}")

    degraded: dict = {}  # stage -> reason, for every fail-softed extraction
    print(">>> Step 5: TargetMuonFinder/stopmat from run1b_mubeam outputs")
    run1b_outputs = STATE / "run1b_mubeam_outputs.txt"
    calo_per_pot = None
    calo_total = None
    calo_files_seen = None
    if run1b_outputs.exists():
        run1b_files = [Path(p) for p in run1b_outputs.read_text().splitlines() if p.strip()]
        try:
            calo_per_pot, calo_total, calo_files_seen = _extract_calo_per_pot(run1b_files, env)
        except Exception as e:  # noqa: BLE001
            print(f"    calo extraction failed: {e}")
            degraded["run1b_mubeam"] = f"calo extraction failed: {e}"
    if calo_per_pot is not None:
        print(f"    calo_total          = {calo_total}")
        print(f"    calo_files_seen     = {calo_files_seen}")
        print(f"    calo_per_pot        = {calo_per_pot:.6g}")
    else:
        print("    calo_per_pot        = (unavailable)")

    # bo-ipa second objective: tracker StrawGasStep Edep from the muon-stop
    # pileup (capture protons etc.). Only present when the IPA chain ran the
    # mustops_pileup stage. Fail-soft like calo.
    print(">>> Step 6: tracker StrawGasStep Edep from mustops_pileup outputs")
    trk = hv.extract_secondary_edep(
        STATE, "mustops_pileup",
        runner=lambda files: _extract_trk_edep_per_pot(files, env))
    # ipa objective is the per-EVENT mean (∝ per-POT: every IPA config
    # resamples the same TargetStops population) — historic key name kept.
    trk_edep_per_pot = trk.per_event if trk else None
    trk_edep_total_MeV = trk.total_MeV if trk else None
    trk_edep_events = trk.n_events if trk else None
    trk_edep_tag = trk.tag if trk else None
    if trk is not None and trk.error:
        print(f"    {trk.error}")
        degraded["mustops_pileup"] = trk.error
    if trk_edep_per_pot is not None:
        print(f"    trk_edep_total_MeV  = {trk_edep_total_MeV}")
        print(f"    trk_edep_events     = {trk_edep_events}")
        print(f"    trk_edep_tag        = {trk_edep_tag}")
        print(f"    trk_edep_per_pot    = {trk_edep_per_pot:.6g}")
    else:
        print("    trk_edep_per_pot    = (unavailable)")

    # Step 7: tracker StrawGasStep Edep from the ELECTRON-beam EARLY-FLASH peak
    # (bo-foilsflash 2nd objective). Same gallery extractor as the IPA trk_edep
    # (StrawGasStep ionizingEdep, tag compressDetStepMCs, process EleBeamResampler).
    # Only present when the foilsflash chain ran the elebeam_flash stage.
    # The template overrides EarlyPrescaleFilter.nPrescale=1 (NO prescale — prod
    # default drops 999/1000; see pipeline_templates/elebeam_flash/template.fcl:19),
    # so flash_edep_total_MeV is the FULL early-flash total. The BO objective is
    # flash_edep_per_pot = total / (n_input_electrons * POT_PER_ELECTRON) — the
    # geometry-sensitive lever. flash_edep_per_event (mean over the flash-event
    # count) is BLIND to the lever and is kept only for back-compat/diagnostics.
    # Fail-soft like calo/trk_edep.
    print(">>> Step 7: tracker StrawGasStep Edep from elebeam_flash (early) outputs")
    flash = hv.extract_secondary_edep(
        STATE, "elebeam_flash",
        runner=lambda files: _extract_trk_edep_per_pot(files, env))
    flash_edep_per_event = flash.per_event if flash else None
    flash_edep_total_MeV = flash.total_MeV if flash else None
    flash_edep_events = flash.n_events if flash else None
    flash_edep_tag = flash.tag if flash else None
    if flash is not None and flash.error:
        print(f"    {flash.error}")
        degraded["elebeam_flash"] = flash.error
    # POT denominator = landed files x stamped events_per_job (input electrons
    # resampled 1:1) x POT_PER_ELECTRON — see events-per-job incident.
    epj_flash = _events_per_job("elebeam_flash")
    flash_edep_per_pot, flash_n_input = hv.per_pot(
        flash_edep_total_MeV, flash.n_files if flash else 0, epj_flash)
    # Winsorized per-POT mean + per-file spread: run-level DIAGNOSTICS (the
    # sigma_flash QA data), NOT the objective — the leaderboard stays on the
    # plain mean. See harvest.winsorized_diagnostics.
    flash_edep_per_pot_winsor, flash_perfile_stats = hv.winsorized_diagnostics(
        flash.per_file if flash else None, epj_flash)
    if flash_edep_per_event is not None:
        print(f"    flash_edep_total_MeV  = {flash_edep_total_MeV}")
        print(f"    flash_edep_events     = {flash_edep_events}")
        print(f"    flash_edep_tag        = {flash_edep_tag}")
        print(f"    flash_edep_per_event  = {flash_edep_per_event:.6g}")
        print(f"    flash_n_input (POT/e) = {flash_n_input}")
        print(f"    flash_edep_per_pot    = "
              f"{flash_edep_per_pot:.6g}" if flash_edep_per_pot is not None else
              "    flash_edep_per_pot    = (unavailable)")
    else:
        print("    flash_edep_per_event  = (unavailable)")

    summary = hv.EvalSummary(
        config=CONFIG,
        ce_seen=ce_seen,
        muminus_stops=muminus_stops,
        mubeam_sim_total=mubeam_sim_total,
        ce_simulated_events=ce_simulated_events,
        stopping_factor=stopping_factor,
        ce_abs_eff=ce_abs_eff,
        s_over_sqrt_b=s_over_sqrt_b,
        muminus_source=muminus_source,
        calo_per_pot=calo_per_pot,
        calo_total=calo_total,
        calo_files_seen=calo_files_seen,
        trk_edep_per_pot=trk_edep_per_pot,
        trk_edep_total_MeV=trk_edep_total_MeV,
        trk_edep_events=trk_edep_events,
        trk_edep_tag=trk_edep_tag,
        flash_edep_per_event=flash_edep_per_event,
        flash_edep_per_pot=flash_edep_per_pot,
        flash_edep_per_pot_winsor=flash_edep_per_pot_winsor,
        flash_perfile_stats=flash_perfile_stats,
        flash_edep_total_MeV=flash_edep_total_MeV,
        flash_edep_events=flash_edep_events,
        flash_n_input=flash_n_input,
        flash_edep_tag=flash_edep_tag,
        nts_path=str(nts_path),
        edep_log=str(edep_log),
        macro_log=str(macro_log),
        degraded=degraded,
    )
    summary.write(harvest_dir)
    print("\n" + summary.to_json())


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True,
                   help="BO config name (e.g. helical001). Selects per-config work tree under "
                        f"{DATA_ROOT}/<config>/")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sub = sub.add_parser("submit", help="Submit one stage")
    p_sub.add_argument("stage", choices=list(STAGES))
    p_sub.add_argument("--dry-run", action="store_true")
    p_sub.add_argument("--force", action="store_true",
                       help="Re-submit even if state/<stage>_cluster.txt exists.")
    p_sub.set_defaults(func=cmd_submit)

    p_poll = sub.add_parser("poll", help="Poll a stage's cluster until quorum or cap")
    p_poll.add_argument("stage", choices=list(STAGES))
    p_poll.add_argument("--quorum", type=float, default=None,
                        help="Fraction of jobs required (default: per-stage "
                             "STAGES['quorum'] if set, else 0.9)")
    p_poll.add_argument("--cap-hours", type=float, default=24.0)
    p_poll.set_defaults(func=cmd_poll)

    p_ls = sub.add_parser("list-outputs", help="Glob outstage and persist file list")
    p_ls.add_argument("stage", choices=list(STAGES))
    p_ls.add_argument("--force", action="store_true",
                      help="Re-glob even if state/<stage>_outputs.txt validates.")
    p_ls.set_defaults(func=cmd_list_outputs)

    p_harv = sub.add_parser("harvest", help="Aggregate stage outputs into summary.json")
    p_harv.set_defaults(func=cmd_harvest)

    p_hpo = sub.add_parser("harvest-pot-only",
                           help="Aggregate pot_only outputs into mu_per_POT (uproot)")
    p_hpo.set_defaults(func=cmd_harvest_pot_only)

    p_mat = sub.add_parser("materialize",
                           help="Debug: write a stage's materialized template (geom basename substituted)")
    p_mat.add_argument("stage", choices=list(STAGES))
    p_mat.add_argument("--out", help="Output path (default stdout)")
    p_mat.set_defaults(func=cmd_materialize)

    args = p.parse_args()
    _bind_config(args.config)
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
