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
  <DATA_ROOT>/autoresearch_grid/<cfg>/
    geom/autoresearch_<cfg>_geom.txt   (placed by bo_driver.py propose)
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

# graph/config.py's own module-level lookup (`_modes.SPECS[os.environ.get(
# "AUTORESEARCH_MODE", "foils")]`) still hardcodes "foils" as its fallback —
# that file is out of scope here (graph/ stays untouched by the 2026-08-08
# Python-mode archive cut). "foils" no longer exists in modes.SPECS, so an
# unset AUTORESEARCH_MODE would KeyError inside `from config import` below.
# Real launches (graph/run.py, graph/closed_loop.py) always stamp
# AUTORESEARCH_MODE before importing config, so setdefault is a no-op for
# them; a bare `import pipeline` (tests, ad-hoc scripts) gets a live JSON
# mode instead of the dead "foils" default.
os.environ.setdefault("AUTORESEARCH_MODE", "foilsflash")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))
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
# ModeSpec registry (ADR-0002): per-mode grid-tarball facts.
import modes as _modes  # noqa: E402
# Local executor: local counterparts to the three grid-contact functions.
import local_exec as lx  # noqa: E402

# Canonical muse-built Code.tar.bz2 produced by `muse tarball` from
# <ARTIFACT_ROOT>/autoresearch_muse/ (mgit Mu2eG4 sparse
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
# Per-mode tarball facts live in root modes.py (ADR-0002). The old
# MUSE_TARBALL_BY_MODE dict's silent `.get(..., michael)` fallback — the
# mechanism behind the foilsflash-tarball-mode-key-omission incident — is
# gone: an unknown mode is now a loud KeyError at import.
MUSE_BASE_TARBALL = Path(
    _modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foilsflash")].grid_tarball)
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
    # foils). Per-stage override via STAGES[s]["dsconf_musing"] for a stage
    # backing a different Musing than the config's default.
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
        # MuBeamCat migrated persistent->tape 2026-07-13 (same migration as
        # EleBeamCat 07-09); see wiki elebeamcat-tape-migration-elebeam-wipeout.
        "default_loc": "tape",
        "output_glob": "sim.*.TargetStops.*.art",
    },
    "run1b_mubeam": {
        "desc_fmt": "Run1B_MuBeam_{cfg}",
        "njobs": STAGE_TARGETS["run1b_mubeam"],
        "events_per_job": 5000,
        "run_number": 1810,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'run1b_mubeam' / 'MuBeamCat.txt'}",
        # MuBeamCat migrated persistent->tape 2026-07-13 (see mubeam above).
        "default_loc": "tape",
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
}

# There is NO mode-specific tuning block here. Per-stage tuning for the flash
# lines (foilsflash/foilspf) is declared in mode_specs/<mode>.json
# `run.stage_tuning` and applied by the generic _apply_stage_tuning() call
# below. The hardcoded `AUTORESEARCH_MODE == "foilsflash"` block that used to
# sit at this spot was RETIRED 2026-07-26 with the Python FoilsFlashMode; its
# values moved verbatim into the JSON (mubeam 200k ev / 2000 MB / quorum 0.8,
# mustops_ce 75k / 2000 / 0.8, elebeam_flash 110k / 2000 / default quorum).
# Two mechanisms writing the same three stages would have let the generic one
# silently win (it runs last), so an edit here would have done nothing while
# looking like it worked.
#
# WHY those values, since the JSON records only the numbers: they size
# events_per_job for ~30-min payloads (measured per-event: mubeam 9.1 ms,
# mustops_ce 24.1 ms, elebeam_flash 16.6 ms) instead of the ~45-s default, so
# the payload dominates the ~44-s muse/setup overhead (~80% grid efficiency vs
# ~15-30%). Paired with njobs=100 (graph/config.py STAGE_TARGETS override) →
# ~15-20× total stats: σ(sob)~0.09% (overkill, harmless) + σ(flash) ~3.8×
# tighter (~59k flash events; flash is the binding noise channel). mubeam and
# mustops_ce events_per_job are SHARED defaults, which is exactly why these are
# per-mode overrides and not edits to STAGES above. Stamped-at-submit (see
# wiki/incidents/events-per-job-mid-flight-edit.md); safe for a FRESH campaign
# (kill+relaunch), NOT for mid-flight edits. See wiki/concepts/bo-noise-budget.md.


def _apply_stage_tuning(stages: dict, tuning: dict) -> None:
    """Apply a mode's ModeSpec.stage_tuning (core/mode_json.py `run.stage_tuning`)
    onto `stages` in place -- each stage key updates that stage's dict with
    the tuning dict's keys (events_per_job/memory_mb/quorum; already
    type/range-validated at JSON-load time by mode_json._validate_stage_tuning).
    A stage name that doesn't exist in `stages` is a loud ValueError, not a
    silently-created no-op entry.
    """
    for stage, overrides in tuning.items():
        if stage not in stages:
            raise ValueError(
                f"stage_tuning references unknown stage {stage!r}; known "
                f"pipeline stages are {sorted(stages)}")
        stages[stage].update(overrides)


# Per-mode stage tuning (core/mode_json.py `run.stage_tuning`) — the SOLE
# mechanism since 2026-07-26. The five Python modes all declare
# stage_tuning={} (core/modes.py), so this is a no-op for every mode except a
# JSON mode that sets it.
_apply_stage_tuning(
    STAGES,
    _modes.SPECS[os.environ.get("AUTORESEARCH_MODE", "foilsflash")].stage_tuning)


# EleBeamCat resampler normalization: each resampled electron corresponds to
# dh.gencount/event_count = 25e6 POT / 2,166,994 electrons ~= 11.537 POT. Used to
# turn the elebeam_flash TOTAL edep into an absolute MeV/POT rate (the flash-per-POT
# objective — the geometry-sensitive lever; the per-event MEAN divides out the
# flash-event count and is blind to it). See wiki/projects/bo-foilsflash.md.


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


def _materialize_template(stage: str) -> Path:
    """Read pipeline_templates/<stage>/template.fcl, substitute __GEOM_FILE__;
    write to <STATE>/<stage>_template_materialized.fcl and return that path.
    """
    src = TEMPLATES_ROOT / stage / "template.fcl"
    text = src.read_text()
    text = text.replace("__GEOM_FILE__", GEOM_FILE.name)
    # Stamp-aware concat-less decision: the Eval's own stage-chain stamp wins
    # (written by cmd_submit before materialization); the env-derived global
    # is only the fallback for pre-stamp legacy configs.
    if stage == "mustops_ce" and hv.concatless(STATE, CONCATLESS):
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
    step, which needs the EdepAna module built into our own autoresearch_muse
    work area (mmackenz's copy went away at his p094→p101 bump, 2026-06-26).
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
        import paths  # see core/paths.py
        _muse = paths.artifact("autoresearch_muse")
        mmlib = str(_muse / "build/al9-prof-e29-p094/Run1BAna/lib")
        prelude = (
            f"cd {_muse} && "
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
        # transient [Errno 5] inside setupmu2e-art.sh (cvmfs read flake OR
        # the NFSv4.0 seqid wedge on ~/.spack locks -- see wiki/incidents/
        # nfsv4-badseqid-lock-wedge-nashome.md) that leaves museDefine.sh
        # unsourced and the `muse` function undefined -- upstream of this
        # line. The retry loop below is what actually recovers it.
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
    # Transient [Errno 5] env-source failures (cvmfs read flake OR NFSv4.0
    # seqid wedge on ~/.spack locks; the run_sourced_bash seam now keeps
    # those locks off NFS entirely) leave museDefine.sh unsourced -> `muse`
    # undefined -> rc=127 "command not found". Retry with backoff either
    # way -- 8+ closed-loop children were lost across X05/X06/X08 before
    # retries were added. Shared retry: graph/sourced_bash.py.
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
        # Drop exported shell functions. `env` prints them across MULTIPLE
        # lines ("BASH_FUNC_muse%%=() {  source ...\n}"), and this parser is
        # line-based, so it captures a body with no closing brace. Every child
        # shell then rejects the malformed definition:
        #   sh: muse: line 1: syntax error: unexpected end of file
        #   sh: error importing function definition for `muse'
        # ~10 of those per shell spawn, hundreds per job log -- they buried
        # both real failures found by the first local smoke run (a missing
        # geom on MU2E_SEARCH_PATH, and an expired bearer token). Nothing is
        # lost: a truncated definition never defined the function anyway.
        if k.startswith("BASH_FUNC_"):
            continue
        env[k] = v
    return env


def write_code_tarball(stage_dir: Path, base_tarball: Path | None = None) -> Path:
    """Build Code.tar.bz2 for the --code path.

    Extracts the chosen muse-built base tarball, drops the per-config geom
    file into Code/, writes Code/setup_post.sh to extend MU2E_SEARCH_PATH +
    FHICL_FILE_PATH so the geom is found by GeometryService, then repacks.
    The base tarball's setup.sh handles all framework setup via `muse setup`,
    so local libs win by link/path order (no LD_PRELOAD).

    base_tarball overrides MUSE_BASE_TARBALL — used by a stage whose backing
    musing differs from the default helical-patched Run1Bak tree (via
    STAGES[stage]["code_tarball"]).
    """
    if base_tarball is None:
        base_tarball = MUSE_BASE_TARBALL
    if not GEOM_FILE.exists():
        raise SystemExit(
            f"geom file missing: {GEOM_FILE}\n"
            f"  Run: ./core/bo_driver.py --mode <mode> propose {CONFIG}\n"
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
    location silently kills the whole cluster. Probing the resolved URLs
    turns 2,000 dead jobs into one loud submit-time error.

    This is the AUTHORITATIVE gate for the incident class (the scan patterns
    in graph/pipeline_io.py stay report-only). FAIL-CLOSED (2026-07-11,
    friction-survey FP-5): the original version skipped any URL that didn't
    match one hardcoded door name — a door rename would have recreated the
    wipeout with the probe green on zero probes. Now any xrootd URL whose
    path can't be mapped to a /pnfs NFS probe is a submit-time error, not a
    skip. Emergency bypass: AUTORESEARCH_SKIP_INPUT_PROBE=1.
    A stage whose FCL has NO xrootd inputs (no auxinput) probes nothing.
    """
    if os.environ.get("AUTORESEARCH_SKIP_INPUT_PROBE") == "1":
        print(f"[{stage}] input probe SKIPPED (AUTORESEARCH_SKIP_INPUT_PROBE=1)",
              flush=True)
        return
    urls = list(dict.fromkeys(re.findall(r'"(x?root://[^"]+\.art)"', fcl_text)))
    if not urls:
        return
    probes = []
    unmapped = []
    for u in urls:
        m = re.match(r"x?root://[^/]+//pnfs/fnal\.gov/usr/mu2e/(.+)", u)
        if m:
            probes.append(Path("/pnfs/mu2e") / m.group(1))
        else:
            unmapped.append(u)
    if unmapped:
        raise SystemExit(
            f"[{stage}] input probe cannot map {len(unmapped)} xrootd URL(s) "
            f"to /pnfs for a liveness check (first: {unmapped[0]}). "
            f"Refusing to submit blind — this fail-open path is how the "
            f"EleBeamCat tape-wipeout recurs. Extend _probe_input_urls's "
            f"mapping or set AUTORESEARCH_SKIP_INPUT_PROBE=1 to override.")
    # Probes are independent — fan out so wall time is max(probe), not sum
    # (each dd blocks up to 10 s on a sick pool).
    procs = [(p, subprocess.Popen(
        ["timeout", "10", "dd", f"if={p}", "of=/dev/null", "bs=64k", "count=1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for p in probes[:4]]
    for p, proc in procs:
        if proc.wait() != 0:
            raise SystemExit(
                f"[{stage}] input probe FAILED: {p} not readable — dataset "
                f"moved (persistent→tape?) or wrong default_loc; fix "
                f"STAGES['{stage}']['default_loc'] before submitting. "
                f"See wiki elebeamcat-tape-migration-elebeam-wipeout.")
        print(f"[{stage}] input probe OK: {p.name}", flush=True)


TOKEN_REFRESH_AGE_S = 3600  # refresh the shared bearer token when >1h old


def _token_age_s() -> float:
    """Age of the shared bearer token file; inf if absent/unreadable."""
    p = (os.environ.get("BEARER_TOKEN_FILE")
         or f"/run/user/{os.getuid()}/bt_u{os.getuid()}")
    try:
        return time.time() - os.stat(p).st_mtime
    except OSError:
        return float("inf")


def _maybe_refresh_token(stage: str) -> None:
    """getToken, unless the token was refreshed within TOKEN_REFRESH_AGE_S.

    The bearer token is one shared 3h file per user per node (local tmpfs,
    so the stat never touches NFS). Refreshing it at every stage submit
    (~30x/round) was ~28 redundant setupmu2e-art.sh sourcings and ~3min of
    serialized submit-lock time per round. Fail-open: unknown age ->
    refresh. MUST be called inside _submit_lock (condor_vault_storer races).
    """
    age = _token_age_s()
    if age <= TOKEN_REFRESH_AGE_S:
        print(f"[{stage}] bearer token refreshed {int(age / 60)}m ago, "
              f"skipping getToken", flush=True)
        return
    print(f"[{stage}] renewing bearer token: getToken", flush=True)
    # getToken sources setupmu2e-art.sh -> shares the transient env-source
    # failure class (cvmfs read flakes; NFSv4.0 seqid wedge -- see
    # wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) -> routed
    # through the shared retry helper.
    tok = run_sourced_bash(f"source {SETUPMU2E} >/dev/null 2>&1 && getToken",
                           label=f"{stage}/getToken")
    if tok.stdout.strip():
        print(tok.stdout)
    if tok.returncode != 0:
        raise subprocess.CalledProcessError(
            tok.returncode, "getToken", output=tok.stdout, stderr=tok.stderr)


def stamp_local_events(stage: str, events: int) -> Path:
    """Stamp the LOCAL events-per-job so harvest scales by what actually ran.

    harvest reads this file, not STAGES[stage]["events_per_job"]. Stamping the
    configured value while running fewer events biases every derived metric by
    the ratio -- the failure class of events-per-job-mid-flight-edit.
    """
    out = STATE / f"{stage}_events_per_job.txt"
    out.write_text(f"{events}\n")
    return out


def _jobdef_cmd(stage: str, template_fcl: Path, dsconf: str, desc: str,
                stage_dir: Path, *, inputs_file: Path | None = None,
                events_per_job: int | None = None,
                merge_factor: int | None = None) -> list[str]:
    """Build the mu2ejobdef argv for a stage.

    Single source of truth for both the grid path (submit_stage) and the local
    path (cmd_local_build). Extracted rather than duplicated: a second copy of
    these conditionals is exactly how the grid tarball drifted from the local
    env in foilsflash-tarball-mode-key-omission, where preflight passed locally
    while every grid job died.

    events_per_job overrides STAGES[stage]["events_per_job"] so a local build
    can request 200 events where the grid config says 5000. merge_factor
    likewise: concat merges 200 files on the grid, but a local mubeam at
    njobs=1 produced one, and mu2ejobdef yields ZERO jobs when the merge
    factor exceeds the input count.
    """
    cfg = STAGES[stage]
    jobdef = ["mu2ejobdef", "--dsconf", dsconf, "--dsowner", USER,
              "--desc", desc, "--embed", str(template_fcl)]
    if cfg["ships_geom"]:
        base = Path(cfg["code_tarball"]) if "code_tarball" in cfg else None
        tarball = write_code_tarball(stage_dir, base_tarball=base)
        jobdef += ["--code", str(tarball)]
    else:
        jobdef += ["--setup", _grid_setup_sh()]
    if "events_per_job" in cfg:
        epj = cfg["events_per_job"] if events_per_job is None else events_per_job
        jobdef += ["--run-number", str(cfg["run_number"]),
                   "--events-per-job", str(epj)]
    if "merge_factor" in cfg:
        if inputs_file is None:
            raise SystemExit(f"[{stage}] needs --inputs file but none provided")
        mf = cfg["merge_factor"] if merge_factor is None else merge_factor
        jobdef += ["--inputs", str(inputs_file), "--merge-factor", str(mf)]
    if "auxinput" in cfg:
        jobdef += [f"--auxinput={cfg['auxinput']}"]
    return jobdef


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

    jobdef = _jobdef_cmd(stage, template_fcl, dsconf, desc, stage_dir,
                         inputs_file=inputs_file)
    if "events_per_job" in cfg:
        # Stamp the per-stage events_per_job at submit time so harvest reads
        # the actual value used, not the current (possibly edited) dict.
        # Without this, editing STAGES[*]["events_per_job"] between submit
        # and harvest mis-scales ce_simulated_events / mubeam_sim_total
        # → biases sob (helicalP01 false high, 2026-05-21).
        (STATE / f"{stage}_events_per_job.txt").write_text(
            f"{cfg['events_per_job']}\n"
        )

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
        _maybe_refresh_token(stage)

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


def poll_cluster(stage: str, cluster: int, *, quorum: float = 0.9,
                 cap_hours: float = 24.0, runner=None) -> None:
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
        out = (runner or subprocess.run)(
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


# Stages the local executor can build today.
#
# mubeam and elebeam_flash resample an EXTERNAL dataset through a static
# auxinput filelist (MuBeamCat.txt / EleBeamCat.txt) and consume no prior
# stage's output -- cmd_submit passes them inputs_file=None, so there is
# nothing to stage and they need no local analogue of anything.
#
# concat and mustops_ce do consume a prior stage: cmd_submit hard-links its
# outputs into one /pnfs dir (stage_hardlink_farm) because mu2ejobdef's
# --inputs takes basenames only. STAGE_INPUT_SOURCE below is the local
# analogue; a stage absent from BOTH tuples is refused rather than handed a
# cnf with no inputs, which mu2ejobdef accepts and which then yields a job
# that silently reads nothing.
LOCAL_SUPPORTED_STAGES = ("mubeam", "run1b_mubeam", "elebeam_flash",
                          "concat", "mustops_ce")

# Stage -> the stage whose outputs it consumes. mustops_ce is resolved at call
# time: a concat-less chain resamples mubeam's mu--pure TargetStops directly.
# Stamp-first (hv.concatless), so a concat-era config re-run under a
# concat-less env keeps staging its concat outputs -- same rule cmd_submit
# follows.
STAGE_INPUT_SOURCE = {
    "concat": lambda: "mubeam",
    "mustops_ce": lambda: ("mubeam" if hv.concatless(STATE, CONCATLESS)
                           else "concat"),
}


def _require_local_stage(stage: str) -> None:
    """Refuse a stage the local executor cannot stage inputs for.

    ONE helper, both verbs, so they cannot drift: `local-run` needs this as
    much as `local-build` does, because it writes state/<stage>_cluster.txt --
    and a runid sitting in, say, concat_cluster.txt trips cmd_submit's
    idempotency guard, silently skipping a REAL grid submit of that stage.
    """
    if stage not in LOCAL_SUPPORTED_STAGES:
        raise SystemExit(
            f"[{stage}] the local executor supports "
            f"{', '.join(LOCAL_SUPPORTED_STAGES)} only.")
    # STATE's unbound default is Path(), i.e. the CURRENT DIRECTORY -- so a
    # caller that skipped _bind_config writes <stage>_cluster.txt and friends
    # into cwd instead of the config's state dir. main() always binds, but a
    # test or a future caller need not: this cost a scatter of state files in
    # the repo root the first time these verbs were reached unbound.
    if not CONFIG:
        raise SystemExit(
            f"[{stage}] no config bound -- pass --config, or call "
            f"_bind_config() first. STATE would otherwise resolve to cwd.")


def _local_stage_inputs(stage: str) -> tuple:
    """Stage a consuming stage's inputs from the PREVIOUS stage's local run.

    Returns (inputs_file, default_loc, merge_factor) -- (None, configured
    default_loc, None) for a stage that consumes nothing.

    The prior stage must have run LOCALLY: its outputs.txt would otherwise
    list /pnfs paths that this job would have to reach over xrootd, which is
    a grid chain wearing a local hat. Refuse instead of half-doing it.
    """
    if stage not in STAGE_INPUT_SOURCE:
        return None, STAGES[stage]["default_loc"], None
    prev = STAGE_INPUT_SOURCE[stage]()
    if not local_marker(prev).exists():
        raise SystemExit(
            f"[{stage}] consumes {prev}, which has no local run "
            f"({local_marker(prev)} missing). Run '--config {CONFIG} "
            f"local-build {prev}' and 'local-run {prev}' first.")
    prev_outputs = STATE / f"{prev}_outputs.txt"
    sources = [Path(p) for p in prev_outputs.read_text().split() if p.strip()]
    if not sources:
        raise SystemExit(
            f"[{stage}] {prev_outputs.name} is empty -- the local {prev} run "
            f"produced no output. Check its job log before rebuilding.")
    staged, basenames = lx.local_farm(stage, CONFIG, sources, STATE)
    mf = None
    if "merge_factor" in STAGES[stage]:
        mf = lx.clamp_merge_factor(STAGES[stage]["merge_factor"], len(sources))
        if mf != STAGES[stage]["merge_factor"]:
            print(f"[{stage}] merge factor clamped "
                  f"{STAGES[stage]['merge_factor']} -> {mf} "
                  f"({len(sources)} local input(s))")
    if stage == "mustops_ce":
        # Resamples the staged files through TargetStopResampler rather than
        # merging them, so it takes auxinput and NOT --inputs -- exactly the
        # split cmd_submit makes (it passes inputs_file=None here too).
        STAGES[stage]["auxinput"] = (
            f"1:physics.filters.TargetStopResampler.fileNames:{basenames}")
        return None, f"dir:{staged}", mf
    return basenames, f"dir:{staged}", mf


def local_marker(stage: str) -> Path:
    """Marker file: state/<stage>_cluster.txt holds a runid, NOT a cluster id.

    Single source of truth for "this stage ran locally". AUTORESEARCH_LOCAL
    alone cannot carry it: `submit --local` is a FLAG, so a later `poll` or
    `list-outputs` in a fresh process (no env var) would take next_runid's
    small int for a ClusterId -- handing it to jobsub_q and then polling a
    nonexistent /pnfs/.../<runid>/00 for the full 24h cap (the
    poll-deadlock-missing-outstage-dirs shape), or globbing the grid outstage
    for a bogus cluster.
    """
    return STATE / f"{stage}_local.txt"


def _is_local_stage(stage: str) -> bool:
    """DETECTION: did THIS stage actually run locally? Marker file only.

    Deliberately NOT `or os.environ.get("AUTORESEARCH_LOCAL")`. The env var is
    an ACTIVATION switch (cmd_submit reads it to choose local mode) and every
    path that runs local jobs -- `local-run`, `submit --local`, `submit` under
    the env var -- goes through cmd_local_run, which always writes the marker.
    So the disjunct added no capability and one failure mode: an operator who
    exports AUTORESEARCH_LOCAL=1 for a study and later launches a campaign
    from that shell would make cmd_poll a no-op on a LIVE GRID CLUSTER, and
    cmd_list_outputs write an empty <stage>_outputs.txt from a nonexistent
    local tree, for stages that never went near the local executor.
    """
    return local_marker(stage).exists()


def cmd_local_build(args):
    """Build this stage's per-index FCLs and stop. Nothing is executed."""
    stage = args.stage
    _require_local_stage(stage)
    njobs = lx.resolve_scale(getattr(args, "local_njobs", None), 1, stage)
    events = lx.resolve_scale(getattr(args, "local_events", None), 200, stage)
    env = sourced_env()
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    template_fcl = _materialize_template(stage)
    dsconf = _stage_dsconf(stage)
    desc = _stage_desc(stage)
    cnf = stage_dir / f"cnf.{USER}.{desc}.{dsconf}.0.tar"
    # Rebuild unconditionally, exactly as submit_stage does. Reusing whatever
    # cnf happens to be on disk silently ignores --local-events and any
    # template edit -- and that cnf is as likely as not one a GRID submit
    # built, at the configured 5000 events/job. The spec's guarantee that
    # `submit --local` always rebuilds is only true if this is the code that
    # rebuilds.
    if cnf.exists():
        print(f"[{stage}] removing existing cnf: {cnf.name}")
        cnf.unlink()
    inputs_file, default_loc, merge_factor = _local_stage_inputs(stage)
    jobdef = _jobdef_cmd(stage, template_fcl, dsconf, desc, stage_dir,
                         inputs_file=inputs_file, events_per_job=events,
                         merge_factor=merge_factor)
    print(f"$ (cd {stage_dir} && {shlex.join(jobdef)})", flush=True)
    subprocess.run(jobdef, cwd=str(stage_dir), env=env, check=True)
    # default_loc is dir:<local farm> for a consuming stage, so mu2ejobfcl
    # resolves the staged basenames to local paths instead of xrootd URLs.
    lx.build_fcls(stage, cnf.name, stage_dir, STATE, njobs, default_loc, env)
    stamp_local_events(stage, events)
    print(f"[{stage}] local-build done; edit "
          f"{STATE / 'fcl'}/{stage}_00000.fcl then 'local-run {stage}'")


def local_job_env() -> dict:
    """sourced_env() plus the per-config geom dir on MU2E_SEARCH_PATH.

    The FCL names the geom by BASENAME (services.GeometryService.inputFile:
    "autoresearch_<cfg>_geom.txt"), which only resolves via MU2E_SEARCH_PATH.
    On the grid that path is extended by Code/setup_post.sh, written into
    Code.tar.bz2 by write_code_tarball and sourced when the worker unpacks it.
    Nothing unpacks that tarball locally, so without this the job runs to
    "Can't find file ... _geom.txt" -- with a rc=1 whose real cause is buried
    ~200 lines deep in the log, under the harmless exported-function noise.
    Mirror setup_post.sh rather than inventing a second mechanism.
    """
    env = sourced_env()
    geom_dir = str(GEOM_FILE.parent)
    for var in ("MU2E_SEARCH_PATH", "FHICL_FILE_PATH"):
        env[var] = f"{geom_dir}:{env[var]}" if env.get(var) else geom_dir
    return env


def cmd_local_run(args):
    """Execute the FCLs already on disk, then list outputs."""
    stage = args.stage
    _require_local_stage(stage)
    njobs = lx.resolve_scale(getattr(args, "local_njobs", None), 1, stage)
    events = lx.resolve_scale(getattr(args, "local_events", None), 200, stage)
    pool = getattr(args, "local_pool", None) or lx.DEFAULT_POOL
    # Console-only for now. The persisted form (a state file, and an
    # fcl_edited field on the row) belongs with the phase that produces local
    # rows; until then it would be a schema field nothing can ever set.
    for name in lx.edited_fcls(STATE, stage):
        print(f"[{stage}] FCL hand-edited: {name}")
    runid = lx.next_runid(CONFIG)
    # INVARIANT (write half): the runid and its marker are written together
    # and cleared together, so a runid can never be present without its
    # marker -- that is the whole basis on which poll/list-outputs decide the
    # int in the cluster file is a runid and not a ClusterId.
    # Marker FIRST: if the process dies between these two writes, the residue
    # is a marker with no cluster file (poll no-ops; harmless) rather than a
    # runid nothing distinguishes from a real cluster id (poll hangs the full
    # 24h cap on a /pnfs dir that will never appear).
    local_marker(stage).write_text(f"{runid}\n")
    (STATE / f"{stage}_cluster.txt").write_text(f"{runid}\n")
    # A local job reads its resampler inputs over xrootd exactly as a grid
    # worker does, so it needs a live bearer token exactly as much -- an
    # expired one surfaces as "Auth failed: No protocols left to try" inside
    # a FatalRootError, ~300 lines into the job log. No _submit_lock here:
    # the lock exists to serialize condor_vault_storer against concurrent
    # submits, and a local run makes none.
    _maybe_refresh_token(stage)
    res = lx.run_jobs_local(stage, CONFIG, runid, STATE, njobs, events,
                            local_job_env(), pool=pool)
    stamp_local_events(stage, events)
    lx.list_outputs_local(stage, CONFIG, runid,
                          STAGES[stage]["output_glob"], STATE)
    if res["failed"]:
        print(f"[{stage}] WARNING: {len(res['failed'])} job(s) failed: "
              f"{res['failed']}")


def cmd_submit(args):
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    # ACTIVATION (as opposed to _is_local_stage's detection): --local, or the
    # env var so a graph-runner child inherits local mode without every call
    # site growing a flag.
    want_local = bool(getattr(args, "local", False)) or bool(
        os.environ.get("AUTORESEARCH_LOCAL"))
    # A grid submit invalidates any marker a prior `--local` run left behind:
    # the cluster file is about to hold a genuine cluster id again, and a stale
    # marker would no-op the poll of a live grid cluster.
    #
    # This runs BEFORE the idempotency guard, and that ordering is the point.
    # The guard cannot tell a runid from a ClusterId, so with the clear placed
    # after it a plain (un-forced) `submit mubeam` following any local run
    # printed "already submitted (cluster=1)" and silently did nothing -- on
    # the exact path a graph child takes. --force happened to work; the path
    # that matters did not.
    #
    # INVARIANT (clear half): drop the runid and its marker TOGETHER, runid
    # first. submit_stage only rewrites <stage>_cluster.txt AFTER mu2ejobsub
    # parses a cluster id, so unlinking the marker alone would leave the local
    # runid behind, unmarked, on every path that never reaches that write:
    # --dry-run returns early, and mu2ejobdef / mu2ejobfcl / _probe_input_urls
    # / token refresh / mu2ejobsub can each raise before it. A later poll would
    # then take that runid for a ClusterId -- the exact 24h-cap hang the marker
    # exists to prevent, reintroduced by the marker's own cleanup.
    if not want_local and local_marker(args.stage).exists():
        cluster_file.unlink(missing_ok=True)
        local_marker(args.stage).unlink(missing_ok=True)
    # Idempotency guard: if a prior submit already produced a cluster file,
    # treat re-entry as a no-op so a killed-and-resumed graph node doesn't
    # double-submit. --force overrides.
    if cluster_file.exists() and not getattr(args, "force", False):
        cid = cluster_file.read_text().strip()
        print(f"[{args.stage}] already submitted (cluster={cid}); skip submit "
              f"(use --force to override)")
        return
    if want_local:
        cmd_local_build(args)
        cmd_local_run(args)
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
    elif args.stage == "mustops_ce":
        # Resamples concat MuminusStopsCat via TargetStopResampler.
        # auxinput list file requires basenames (same restriction as
        # --inputs): hard-link concat outputs into a /pnfs stage dir so
        # xrootd can resolve them when --default-location dir:STAGED
        # expands the basenames.
        # Concat-less chains resample the mu--pure mubeam TargetStops files
        # directly (auxinput=1 -> one file-slice per job, same structure as
        # mubeam<->MuBeamCat).
        # Stamp-first (hv.concatless): a concat-era config resubmitted under
        # a concat-less env must keep staging its concat outputs.
        prev_stage = "mubeam" if hv.concatless(STATE, CONCATLESS) else "concat"
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
    if _is_local_stage(args.stage):
        print(f"[{args.stage}] local mode: jobs already complete; poll is a no-op")
        return
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
    if _is_local_stage(args.stage):
        # Re-list from the LOCAL tree; never fall through to the grid glob.
        # The guard above is not enough on its own: a local run that produced
        # zero outputs leaves `paths` empty, the guard falls through, and
        # list_outputs() would glob the /pnfs outstage for a runid-shaped
        # "cluster" that no grid job ever wrote.
        lx.list_outputs_local(args.stage, CONFIG, cluster,
                              STAGES[args.stage]["output_glob"], STATE)
        return
    list_outputs(args.stage, cluster)


# Constant from extract_analysis_results._MUBEAM_INPUT_EFFICIENCY_BY_FCL["run1a_beam/mubeam.fcl"].
# This is the fraction of upstream POT that survive into the MuBeamCat resampler input,
# needed to convert per-simulated-event yields into per-POT yields.
RUN1A_MUBEAM_INPUT_CORRECTION = hv.RUN1A_MUBEAM_INPUT_CORRECTION  # single source in harvest.py

# Path to the autoresearch repo so we can find the EdepAna fcl + ROOT macro.
from paths import REPO_ROOT as AUTORESEARCH  # see core/paths.py

# EdepAna / sensitivity-macro Steps 1+4 (incl. the sci-notation count fix,
# and EDEP_FCL/SENSITIVITY_MACRO path consts) live in harvest.py:
# run_edepana, run_sensitivity_macro — regression-tested there.

# TargetMuonFinder/stopmat bin labels (mmackenz extract_analysis_results._CALO_STOP_MATERIALS)
_CALO_STOP_MATERIALS = ("G4_CESIUM_IODIDE", "CarbonFiber", "AluminumHoneycomb")

# Tracker StrawGasStep ionizing-Edep extractor (bo-foilsflash objective;
# originally built for the retired bo-ipa line's MuStopPileup stream). Uses
# gallery (uproot can't read StrawGasStep — see wiki
# uproot-cannot-read-steppointmc). Sums ALL StrawGasStep ionizingEdep.
# InputTag is auto-discovered from candidate labels since the kept
# compressed-StrawGasStep label/instance varies by stream.
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
    """Mean tracker StrawGasStep ionizing Edep (MeV) per event.

    Returns (edep_per_event, total_edep_MeV, n_events, tag). Consumed by the
    foilsflash elebeam_flash harvest (Step 6); name retains the trk_edep tag
    from its bo-ipa origin. Gallery requires the muse env, so we shell out to
    a python subprocess that inherits `env` (same pattern as calo).
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
    return hv.events_per_job(STATE, stage, STAGES[stage]["events_per_job"])


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


def _note_degraded(sec, stage, degraded):
    """Record a fail-softed secondary-metric extraction (identical across the
    calo/trk/flash steps): echo the error and stamp degraded[stage]."""
    if sec.error:
        print(f"    {sec.error}")
        degraded[stage] = sec.error


def cmd_harvest(args):
    """Compute s_over_sqrt_b from the smoke pipeline outputs.

    Steps (mirrors extract_analysis_results.run_rough_run1a_sensitivity_analysis):
      1. Run EdepAna on mustops_ce CeEndpoint art files -> nts ROOT + 'Saw N' line
      2. Count events in concat MuminusStopsCat -> muminus_stops_events
      3. ce_scale = input_corr * (muminus_stops / mubeam_sim_total) / ce_simulated_events
         ce_abs_eff = ce_seen * ce_scale
      4. Run rough_run1a_sensitivity.C -> parse 'S/sqrt(B) = X'
    """
    # Check config-sha only for stages this run actually produced — chains
    # differ per mode (foilsflash adds elebeam_flash; sob-only drops
    # run1b_mubeam), so key off the stamped config_sha files rather than a
    # hardcoded per-mode tuple.
    for stage in ("mubeam", "run1b_mubeam", "concat", "mustops_ce",
                  "elebeam_flash"):
        if (STATE / f"{stage}_config_sha.txt").exists():
            _check_stage_config_sha(stage)
    env = sourced_env(with_muse=True)
    harvest_dir = ROOT / "harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)

    ce_files = hv.read_outputs(STATE, "mustops_ce") or []
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
    mubeam_files = hv.read_outputs(STATE, "mubeam") or []
    mubeam_sim_total = len(mubeam_files) * _events_per_job("mubeam")
    ce_simulated_events = len(ce_files) * _events_per_job("mustops_ce")

    print(">>> Step 1: EdepAna on CeEndpoint outputs")
    def _mu2e_runner(cmd, cwd):
        return subprocess.run(
            cmd, cwd=cwd,
            env={**env, "FHICL_FILE_PATH":
                 f"{AUTORESEARCH}:{env.get('FHICL_FILE_PATH', '')}"},
            capture_output=True, text=True, check=False)
    ce_seen, nts_path = hv.run_edepana(harvest_dir, ce_files,
                                       runner=_mu2e_runner)
    edep_log = harvest_dir / "edep.log"  # path hv.run_edepana wrote; summary needs it

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
    def _root_runner(cmd, cwd):
        return subprocess.run(cmd, cwd=cwd, env=env,
                              capture_output=True, text=True, check=False)
    s_over_sqrt_b = hv.run_sensitivity_macro(harvest_dir, nts_path,
                                             ce_abs_eff, runner=_root_runner)
    macro_log = harvest_dir / "rough_run1a_sensitivity.log"  # path hv wrote; summary needs it

    degraded: dict = {}  # stage -> reason, for every fail-softed extraction
    print(">>> Step 5: TargetMuonFinder/stopmat from run1b_mubeam outputs")
    calo = hv.extract_secondary_calo(
        STATE, runner=lambda files: _extract_calo_per_pot(files, env)) \
        or hv.SecondaryCalo()
    calo_per_pot, calo_total, calo_files_seen = calo.per_pot, calo.total, calo.files_seen
    _note_degraded(calo, "run1b_mubeam", degraded)
    if calo_per_pot is not None:
        print(f"    calo_total          = {calo_total}")
        print(f"    calo_files_seen     = {calo_files_seen}")
        print(f"    calo_per_pot        = {calo_per_pot:.6g}")
    else:
        print("    calo_per_pot        = (unavailable)")

    # Step 6: tracker StrawGasStep Edep from the ELECTRON-beam EARLY-FLASH peak
    # (bo-foilsflash 2nd objective). Gallery extractor sums StrawGasStep
    # ionizingEdep (tag compressDetStepMCs, process EleBeamResampler).
    # Only present when the foilsflash chain ran the elebeam_flash stage.
    # The template overrides EarlyPrescaleFilter.nPrescale=1 (NO prescale — prod
    # default drops 999/1000; see pipeline_templates/elebeam_flash/template.fcl:19),
    # so flash_edep_total_MeV is the FULL early-flash total. The BO objective is
    # flash_edep_per_pot = total / (n_input_electrons * POT_PER_ELECTRON) — the
    # geometry-sensitive lever. flash_edep_per_event (mean over the flash-event
    # count) is BLIND to the lever and is kept only for back-compat/diagnostics.
    # Fail-soft like calo/trk_edep.
    print(">>> Step 6: tracker StrawGasStep Edep from elebeam_flash (early) outputs")
    flash = hv.extract_secondary_edep(
        STATE, "elebeam_flash",
        runner=lambda files: _extract_trk_edep_per_pot(files, env)) \
        or hv.SecondaryEdep()
    flash_edep_per_event = flash.per_event
    flash_edep_total_MeV = flash.total_MeV
    flash_edep_events = flash.n_events
    flash_edep_tag = flash.tag
    _note_degraded(flash, "elebeam_flash", degraded)
    # POT denominator = landed files x stamped events_per_job (input electrons
    # resampled 1:1) x POT_PER_ELECTRON — see events-per-job incident.
    epj_flash = _events_per_job("elebeam_flash")
    flash_edep_per_pot, flash_n_input = hv.per_pot(
        flash_edep_total_MeV, flash.n_files, epj_flash)
    # Winsorized per-POT mean + per-file spread: run-level DIAGNOSTICS (the
    # sigma_flash QA data), NOT the objective — the leaderboard stays on the
    # plain mean. See harvest.winsorized_diagnostics.
    flash_edep_per_pot_winsor, flash_perfile_stats = hv.winsorized_diagnostics(
        flash.per_file, epj_flash)
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
    p_sub.add_argument("--local", action="store_true",
                       help="run this stage locally instead of submitting")
    p_sub.add_argument("--local-njobs", action="append",
                       help="--local only: int, or <stage>=<int>; repeatable "
                            "(default 1)")
    p_sub.add_argument("--local-events", action="append",
                       help="--local only: int, or <stage>=<int>; repeatable "
                            "(default 200)")
    p_sub.add_argument("--local-pool", type=int, default=None,
                       help="--local only: max concurrent local jobs "
                            "(default 4)")
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

    for verb, fn in (("local-build", cmd_local_build),
                     ("local-run", cmd_local_run)):
        p_l = sub.add_parser(verb, help=f"{verb}: local executor")
        p_l.add_argument("stage", choices=list(STAGES))
        p_l.add_argument("--local-njobs", action="append",
                         help="int, or <stage>=<int>; repeatable (default 1)")
        p_l.add_argument("--local-events", action="append",
                         help="int, or <stage>=<int>; repeatable (default 200)")
        p_l.add_argument("--local-pool", type=int, default=None,
                         help="max concurrent local jobs (default 4)")
        p_l.set_defaults(func=fn)

    args = p.parse_args()
    _bind_config(args.config)
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
