#!/usr/bin/env python3
"""
Parametric grid pipeline orchestrator for the BO loop.

Pass --config CFG. Per-stage job description: stage_entries/<stage>.json
(json2jobdef's native entry schema); px.load_stage_entry substitutes
{cfg}/{geom}; _render_fcl_overrides applies the one submit-time substitution
(mustops_ce's concat-less MaxEventsToSkip); stage_cfg(stage, mode) merges the
JSON with the mode spec's run.jobs_per_stage/run.stage_tuning. Per-key
rationale: comment block above _render_fcl_overrides.

@sequence::-bearing override blocks can't ride a JSON value, so mubeam and
run1b_mubeam '#include' static pipeline_templates/*.fcl, shipped in the code
tarball (write_code_tarball extra_files) like the geom overlay.

Per-config working tree: <DATA_ROOT>/autoresearch_grid/<cfg>/
{geom,<stage>,state,harvest}. Stages run in sequence per BO point, each its
own subcommand so a failed stage can be re-run alone:
  mubeam (200) + run1b_mubeam (200) -> concat (1) -> mustops_ce (200) -> harvest

Polling: prodtools jobwait; autoresearch applies its own quorum/zero-ok
policy on the wait.json. Outstage (prodtools direct backend):
/pnfs/mu2e/scratch/users/$USER/workflow/default/outstage/<CLUSTER>/<PROC>/ --
flat per-proc dirs; the zero-padded `00/<00000>/` sublevel is legacy
mu2ejobsub (graph/pipeline_io.py _worker_log_paths still checks it).
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
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

# Host-wide lock on the token-refresh + submit critical section:
# condor_vault_storer races when concurrent chains submit within seconds
# (see wiki/incidents/concurrent-token-contention.md).
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

TEMPLATES_ROOT = Path(__file__).resolve().parent / "pipeline_templates"

# Imported above the setdefault because it owns DEFAULT_MODE (stdlib-only,
# does not read AUTORESEARCH_MODE at import).
import modes as _modes  # noqa: E402

# Stamp the mode into the env so subprocesses inherit it; mechanism and
# incident documented ONCE at core/modes.py::stamp_mode_from_argv.
os.environ.setdefault("AUTORESEARCH_MODE", _modes.resolve_env_mode())
# One mode per process; a different mode is a fresh subprocess.
MODE = _modes.resolve_env_mode()
from paths import GRID_DATA_ROOT as DATA_ROOT  # noqa: E402
from runtime import (  # noqa: E402
    GRID_STAGES,
    MUSING,
    SETUPMU2E,
)

# Concat-less chains: mubeam's muminusSelector makes TargetStops mu--pure,
# so mustops_* resample the mubeam files directly.
CONCATLESS = "concat" not in GRID_STAGES
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))
from sourced_bash import run_sourced_bash  # noqa: E402
import harvest as hv  # noqa: E402
import prodtools_exec as px  # noqa: E402

# Mode-aware muse-built Code.tar.bz2; its Code/setup.sh runs `muse setup
# $CODE_DIR -q e29 prof p094`, so local patched libs win by Muse link/path
# order (no LD_PRELOAD). Build: wiki/external/muse-backing-pattern.md;
# motivating bug: wiki/incidents/calo-constant-across-helical.md.
# The foils family needs the patched libmu2e_GeometryService.so (holeRadii
# vector); without it the tarball silently falls back to scalar holeRadius --
# wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
# Per-mode tarball facts live in root modes.py (ADR-0002); an unknown mode is
# a loud KeyError at import, not a silent default tarball
# (wiki/incidents/foilsflash-tarball-mode-key-omission.md).
MUSE_BASE_TARBALL = Path(_modes.SPECS[MODE].grid_tarball)
USER = os.environ["USER"]

# Prodtools submission ledger (runtime writes live on /data).
LEDGER_DB = DATA_ROOT / "prodtools_ledger" / "submissions.db"

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
    # Default = dominant musing; per-stage override: stage_cfg's dsconf_musing.
    DSCONF = f"Run1Bak_{cfg}"
    PNFS_STAGE = Path(f"/pnfs/mu2e/scratch/users/{USER}/autoresearch_grid/{cfg}/staged")


def _stage_dsconf(stage: str) -> str:
    """Per-stage dsconf: `dsconf_musing` key wins, else module DSCONF."""
    musing = stage_cfg(stage, MODE).get("dsconf_musing")
    return f"{musing}_{CONFIG}" if musing else DSCONF


# No module-level STAGES literal: it shadowed stage_entries/ JSON's `events`,
# making JSON edits a silent no-op. stage_cfg() is the ONE reader -- never
# add a second in-Python source for njobs/events/memory_mb/quorum.


_STAGE_CFG_DEFAULT_MODE = object()


def stage_cfg(stage: str, mode=_STAGE_CFG_DEFAULT_MODE) -> dict:
    """Merged stage config: mode spec (run.jobs_per_stage, run.stage_tuning)
    OVERRIDES stage_entries/<stage>.json; nothing overrides the mode spec
    except AUTORESEARCH_ELEBEAM_NJOBS (long-standing env seam) LAST.

    `mode` defaults to the process's MODE, read at CALL time. Do NOT make
    None the default: a bare stage_cfg(stage) would return unmerged
    njobs/events -- the metric-denominator error of
    wiki/incidents/events-per-job-mid-flight-edit.md as a default argument.
    Explicit mode=None still means "raw JSON, no mode merge" (pinned by
    tests/test_stages_retired.py).

    Reads the JSON RAW: desc_fmt's literal `{cfg}` must survive for
    _stage_desc's later .format(cfg=CONFIG).
    """
    if mode is _STAGE_CFG_DEFAULT_MODE:
        mode = MODE
    cfg = json.loads((px.STAGE_ENTRIES_DIR / f"{stage}.json").read_text())
    if mode:
        spec = _modes.SPECS[mode]
        if stage in spec.stage_target_overrides:
            cfg["njobs"] = spec.stage_target_overrides[stage]
        # No second allow-list: mode_json's _validate_stage_tuning rejects
        # unknown keys at LOAD time. stage_entries/ spells the count `events`.
        tuning = dict(spec.stage_tuning.get(stage, {}))
        if "events_per_job" in tuning:
            tuning["events"] = tuning.pop("events_per_job")
        cfg.update(tuning)
    # THE one exception to "nothing overrides the mode spec".
    if stage == "elebeam_flash" and "AUTORESEARCH_ELEBEAM_NJOBS" in os.environ:
        cfg["njobs"] = int(os.environ["AUTORESEARCH_ELEBEAM_NJOBS"])
    return cfg


# All 5 grid stages, independent of any one mode's GRID_STAGES subset
# (legacy/cross-mode chains still need them in --help's stage choices).
ALL_STAGES = ("mubeam", "run1b_mubeam", "concat", "mustops_ce", "elebeam_flash")


def _stage_extra_files(entry_tmpl: dict) -> list[Path]:
    """Extras FCLs to ship in the code tarball, derived from
    fcl_overrides['#include']: a bare basename (no '/') resolves only from
    the tarball's search path so it ships from TEMPLATES_ROOT; a published
    Production/... path resolves from the release and ships nothing."""
    inc = entry_tmpl.get("fcl_overrides", {}).get("#include", [])
    if isinstance(inc, str):
        inc = [inc]
    return [TEMPLATES_ROOT / name for name in inc if "/" not in name]


# Per-stage-JSON-key rationale (stage_entries/ JSON carries only a `_comment`
# pointer back here -- edit HERE, not the JSON).
#
# Shared rules:
#   physicsListName FTFP_BERT -- -20% CPU on mubeam vs ShieldingM (n=200/200),
#     sob/calo deltas inside the ShieldingM-self noise floor (helicalQR00_02
#     A/B). See wiki concepts/g4-speed-knobs.md.
#   NO MaxEventsToSkip on the Cat-resampler stages (mubeam, run1b_mubeam,
#     elebeam_flash): json2jobdef auto-computes it from SAM and appends it as
#     a post_line, which beats every fcl_overrides entry; a frozen value
#     would be a silent lie.
#   "memory": 3000 MB on mustops_ce/elebeam_flash, up from 2500: SR00_00
#     worker logs showed VmPeak=2.75 GB on N_crit~4144 jobs, at eviction
#     risk over the 2.2 GB request.
#   "inloc" is "tape" for the Cat-resampler stages since the 2026-07
#     persistent->tape migrations (wiki
#     elebeamcat-tape-migration-elebeam-wipeout.md); "disk" for
#     concat/mustops_ce (real callers override to `dir:<farm>`).
#
# mubeam.json:
#   '#include' -- sim_kept_products_extras.fcl (shared with run1b_mubeam) +
#     mubeam_targetstop_path.fcl (targetStopPath with muminusSelector
#     inserted); @sequence::-bearing, can't ride a JSON value.
#   'services.GeometryService.inputFile' = "{geom}" -- per-BO-point geom
#     overlay shipped inside code.tar; px.load_stage_entry substitutes.
#   'physics.filters.muminusSelector.*' -- mu- purity so concat-less
#     TargetStopResampler can read TargetStops directly (CeEndpoint throws
#     BADINPUT on no-stopped-mu- events; TargetMuonFinder takes [13,-13]).
#     Harmless with concat (passes ~100%). FLATTENED to dotted leaf keys:
#     write_fcl_template's json.dumps QUOTES dict keys, and FHiCL table
#     syntax requires bare identifiers -- a quoted-key table is a hard
#     fhicl-get parse error.
#
# run1b_mubeam.json: DS field OFF + geom_run1_b_v06 baseline -> real
#   calo_stop/POT measurement. '#include' is sim_kept_products_extras.fcl
#   only (published targetStopPath kept; no muminusSelector).
#
# concat.json: MuonStopSelector split of mu-/mu+ TargetStops. No G4, no
#   geometry, so no BO geom overlay ships with this stage.
#
# mustops_ce.json: G4 on Ce primaries at resampled mu- stops;
#   geometry-dependent, geom overlay travels via --code.
#   'physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip' = 100720 --
#     REQUIRED: the prolog leaves it @nil, art aborts at ResamplingMixer
#     construction without it. dir:-inloc resampler = no SAM auto-compute,
#     so it MUST ride fcl_overrides. _render_fcl_overrides drops it to 8000
#     for concat-less chains: each job reads ONE mubeam file (~16k events vs
#     the ~240k merged concat file), so the random skip must stay below the
#     smallest plausible file. The one substitution kept in Python -- it
#     depends on submit-time chain state.
#
# elebeam_flash.json: foilsflash 2nd objective, EARLY-FLASH StrawGasStep edep
#   with DS ON; harvest globs only the EARLY output. ASCII-only (FHiCL
#   strict).
#   'physics.filters.EarlyPrescaleFilter.nPrescale' = 1 -- production
#     default drops 999/1000 early events (EarlyEleBeamFlashPrescale=1000);
#     the early flash IS the objective, so keeping every event gives ~32x
#     lower per-event flash_edep noise (only StepSim CPU + output grow).


def _render_fcl_overrides(stage: str, entry_tmpl: dict | None = None) -> dict:
    """Entry 'fcl_overrides' with the one per-call substitution applied:
    mustops_ce's concat-less MaxEventsToSkip toggle (stamp-first
    hv.concatless; see the mustops_ce.json comment block above).
    `entry_tmpl`: optional pre-loaded px.load_stage_entry() result.
    """
    entry = entry_tmpl if entry_tmpl is not None else px.load_stage_entry(
        stage, cfg=CONFIG, geom=GEOM_FILE.name)
    overrides = dict(entry.get("fcl_overrides", {}))
    if stage == "mustops_ce" and hv.concatless(STATE, CONCATLESS):
        overrides["physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip"] = 8000
    return overrides


# Flash-line stage tuning (mode_specs/<mode>.json run.stage_tuning, applied
# by stage_cfg): mubeam 200k ev / 2000 MB / quorum 0.8, mustops_ce 75k /
# 2000 / 0.8, elebeam_flash 110k / 2000 / default. WHY: sizes ~30-min
# payloads (measured per-event: mubeam 9.1 ms, mustops_ce 24.1 ms,
# elebeam_flash 16.6 ms) so the payload dominates the ~44-s muse/setup
# overhead (~80% grid efficiency vs ~15-30%). With njobs=100: σ(sob)~0.09%,
# σ(flash) ~3.8x tighter (~59k flash events; flash is the binding noise
# channel). Stamped-at-submit
# (wiki/incidents/events-per-job-mid-flight-edit.md): safe for a FRESH
# campaign, NOT mid-flight edits. See wiki/concepts/bo-noise-budget.md.


# EleBeamCat resampler normalization: each resampled electron = dh.gencount/
# event_count = 25e6 POT / 2,166,994 electrons ~= 11.537 POT. Turns TOTAL
# elebeam_flash edep into MeV/POT (the geometry-sensitive lever; the
# per-event MEAN is blind to rate). See wiki/projects/bo-foilsflash.md.


def _stage_desc(stage: str) -> str:
    return stage_cfg(stage, MODE)["desc_fmt"].format(cfg=CONFIG)


def _stage_config_sha(stage: str) -> str:
    """Stable SHA-256 of stage_cfg(stage, MODE), stamped at submit and
    re-read at harvest (whole-dict generalization of the events_per_job
    stamp -- wiki/incidents/events-per-job-mid-flight-edit.md). `_comment`
    is excluded so a comment-only JSON edit can't trip the WARN.
    """
    cfg = {k: v for k, v in stage_cfg(stage, MODE).items() if k != "_comment"}
    payload = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _stamp_stage_config_sha(stage: str) -> None:
    (STATE / f"{stage}_config_sha.txt").write_text(_stage_config_sha(stage) + "\n")


def _check_stage_config_sha(stage: str) -> None:
    """Warn (do not fail) if stage_cfg changed between submit and read.
    Silent if no stamp file (legacy chains)."""
    stamp_path = STATE / f"{stage}_config_sha.txt"
    if not stamp_path.exists():
        return
    stamped = stamp_path.read_text().strip()
    current = _stage_config_sha(stage)
    if stamped != current:
        print(
            f"[pipeline] WARN: stage_cfg({stage!r}) changed since submit "
            f"(stamp={stamped[:12]}, current={current[:12]}). "
            f"Downstream poll/list-outputs/harvest may use mismatched "
            f"events_per_job or quorum; see "
            f"wiki/incidents/events-per-job-mid-flight-edit.md.",
            file=sys.stderr, flush=True,
        )


def _cnf_build_env(env: dict) -> dict:
    """env for px.build_cnf's json2jobdef subprocess.

    json2jobdef resolves includes via fhicl-get, which consults ONLY
    $FHICL_FILE_PATH -- verified: it does NOT fall back to cwd. The extras
    fcl is a bare basename living in core/pipeline_templates/, not in any
    Offline product, so TEMPLATES_ROOT must be prepended (a no-op for
    stages with no extras fcl).
    """
    return {**env, "FHICL_FILE_PATH":
            f"{TEMPLATES_ROOT}:{env.get('FHICL_FILE_PATH', '')}"}


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
    """Return an env dict with setupmu2e-art.sh + musing + ops tooling sourced.

    For invoking mu2e / prodtools binaries from Python. with_muse=True for
    harvest, which needs the EdepAna module built into our own
    autoresearch_muse work area (mmackenz's copy went away at his p094→p101
    bump -- wiki/incidents/mmackenz-edepana-lib-qualifier-bump.md).
    """
    # `muse setup` is ONE-SHOT per shell: a pre-sourced launching shell makes
    # every prelude below fail "Muse already setup", burning all four retries
    # on a condition no retry can fix. Fail loud instead.
    if os.environ.get("MUSE_WORK_DIR"):
        raise SystemExit(
            f"muse is already set up in this shell "
            f"(MUSE_WORK_DIR={os.environ['MUSE_WORK_DIR']}).\n"
            f"pipeline.py sources its own environment per stage, and muse "
            f"setup cannot run twice in one shell. Start a fresh shell.")
    if with_muse:
        # `-q p094` REQUIRED: without it muse picks p095 from main-HEAD's
        # Offline/.muse and errors on the backing
        # (wiki/external/muse-backing-pattern.md). EdepAna rebuild:
        # `cd autoresearch_muse && muse setup -q p094 && muse build
        # build/al9-prof-e29-p094/Run1BAna/lib/
        # librun1bana_workflows_EdepAna_module.so` (only that target --
        # bare `muse build` dies on evtana).
        import paths  # see core/paths.py
        # require(), not artifact(): a miss becomes `cd <nonexistent>` ->
        # rc=1, indistinguishable from the cvmfs flake the retries exist for.
        _muse = paths.require(paths.artifact("autoresearch_muse"),
                              "the autoresearch_muse work area (harvest's "
                              "EdepAna lib)")
        mmlib = str(_muse / "build/al9-prof-e29-p094/Run1BAna/lib")
        prelude = (
            f"cd {_muse} && "
            f"source {SETUPMU2E} >/dev/null 2>&1 && "
            "muse setup -q p094  >/dev/null 2>&1 && "
            f"export CET_PLUGIN_PATH={mmlib}:$CET_PLUGIN_PATH && "
            f"export LD_LIBRARY_PATH={mmlib}:$LD_LIBRARY_PATH && "
        )
    else:
        # `muse setup ops` (spack-native) provides the condor/jobsub_lite
        # client bits prodtools shells out to (replaces UPS `setup mu2egrid`).
        # rc=127 still happens: a transient [Errno 5] inside setupmu2e-art.sh
        # (cvmfs read flake OR the NFSv4.0 seqid wedge on ~/.spack locks --
        # wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) leaves the
        # `muse` function undefined; the retry loop below recovers it. See
        # wiki/incidents/sourced-env-stderr-swallowed.md.
        #
        # Stat MUSING first: `source` on a missing file is rc=1, same rc as
        # that flake, so an unresolvable musing (any operator without the
        # partial Offline tree, on a path that never ran preflight's
        # paths.verify()) would burn all four retries and name only the
        # command line. SETUPMU2E is deliberately NOT checked: it lives on
        # cvmfs, where "missing" is usually the transient the retries recover.
        import paths  # see core/paths.py
        paths.require(MUSING, "the mode's musing setup script")
        prelude = (
            f"source {SETUPMU2E} && "
            f"source {MUSING} && "
            f"muse setup ops && "
        )
    # Spack provider cache + flock off NFS HOME -> local /tmp: the nashome
    # lock races/corrupts under concurrent setups -> [Errno 5] during spack
    # load. See wiki/incidents/foilsx04-all-preflight-ambiguous.md.
    spack_cache = f"/tmp/spack_cache_{os.environ.get('USER','x')}"
    # `env -0` (NUL-delimited), not plain `env`: exported shell functions
    # (BASH_FUNC_*) hold newlines, so a line-based read cannot tell a value's
    # second line from the next variable. NUL cannot appear in an env entry.
    cmd = f"export SPACK_USER_CACHE_PATH={spack_cache} && {prelude}{extra} env -0"
    # Retry with backoff on the transient [Errno 5] class (rc=127 `muse`
    # undefined) -- 8+ closed-loop children lost before retries were added.
    # Shared retry: graph/sourced_bash.py.
    proc = run_sourced_bash(cmd, label="sourced_env")
    if proc.returncode != 0:
        # Persist stderr so the cause survives the raise -- otherwise the
        # flake surfaces as a bare "submit failed (rc=1)" with no cause.
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
    # BASH_FUNC_* entries are KEPT whole (the point of `env -0`): `muse` is a
    # bash FUNCTION, not a binary, and prodtools runlocal sources
    # Code/setup.sh whose line 4 calls it -- dropping the function kills the
    # local job rc=127 "muse: command not found", surfacing two stages later
    # as "mubeam_outputs.txt is empty". Grid workers source their own env.
    # See wiki/incidents/sourced-env-drops-muse-function-local-jobs.md.
    env = {}
    for record in proc.stdout.split("\0"):
        if "=" not in record:
            continue
        k, _, v = record.partition("=")
        env[k] = v
    return env


def _extra_files_digest(extra_files: list[Path] | None) -> str:
    """Order-independent content digest of extra_files — write_code_tarball's
    staleness signal. Content, not mtime: a fixed repo file has the SAME
    mtime every call, so an mtime gate can't tell "same stage, reuse" from
    "different stage, rebuild"."""
    h = hashlib.sha256()
    for f in sorted(extra_files or [], key=lambda p: p.name):
        h.update(f.name.encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _cache_token(extra_files: list[Path] | None) -> str:
    """8-hex cache-FILENAME token for extra_files' content ("plain" if none).
    The digest MUST stay in the filename: one name per (config, base) made
    mubeam (two extras) and mustops_ce (none) fight over the same cache
    file, forcing a full unpack+rebzip2 (~7-12 min) on nearly every stage.
    """
    return _extra_files_digest(extra_files)[:8] if extra_files else "plain"


def write_code_tarball(stage_dir: Path, base_tarball: Path | None = None,
                       extra_files: list[Path] | None = None) -> Path:
    """Build Code.tar.bz2 for the --code path: extract the base tarball, drop
    the per-config geom + extra_files into Code/, write Code/setup_post.sh
    extending MU2E_SEARCH_PATH + FHICL_FILE_PATH, repack. base_tarball
    overrides MUSE_BASE_TARBALL (stage_cfg's "code_tarball" key).
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

    # Per-(base, extras) cache: build ONCE per variant, else ~7-12 min of
    # unpack+rebzip2 per stage per child, 2/3 redundant. The digest sidecar
    # is a second check beyond the filename token.
    current_digest = _extra_files_digest(extra_files)
    cache = ROOT / (f"Code.{base_tarball.stem.split('.')[0]}."
                    f"{_cache_token(extra_files)}.tar.bz2")
    digest_file = cache.parent / f"{cache.name}.extra_files_sha256"
    if (cache.exists()
            and cache.stat().st_mtime > GEOM_FILE.stat().st_mtime
            and cache.stat().st_mtime > base_tarball.stat().st_mtime
            and digest_file.exists()
            and digest_file.read_text().strip() == current_digest):
        print(f"[tarball] reusing cached {cache.name}", flush=True)
        return cache

    code_dir = stage_dir / "Code"
    if code_dir.exists():
        shutil.rmtree(code_dir)
    run(["tar", "xjf", str(base_tarball), "-C", str(stage_dir)])
    shutil.copy(GEOM_FILE, code_dir / GEOM_FILE.name)
    for f in (extra_files or []):
        shutil.copy(f, code_dir / f.name)
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
    digest_file.write_text(current_digest)
    shutil.rmtree(code_dir, ignore_errors=True)
    return cache


def _input_stage_for(stage: str) -> str:
    """Which stage's outputs feed `stage`: concat <- mubeam; mustops_ce <-
    mubeam-or-concat, stamp-first (hv.concatless) so a concat-era config
    resubmitted under a concat-less env keeps its concat outputs. One owner
    for both the grid and --local staging branches."""
    if stage == "concat":
        return "mubeam"
    return "mubeam" if hv.concatless(STATE, CONCATLESS) else "concat"


def _merge_factor_for(stage: str, n_sources: int) -> int:
    """CLAMPED merge factor (min(configured, n_sources)), else 1: mu2ejobdef
    yielded ZERO jobs when merge factor exceeded input count; prodtools at
    that corner is unvalidated. Every input_map builder goes through here."""
    cfg = stage_cfg(stage, MODE)
    return min(cfg["merge_factor"], n_sources) if "merge_factor" in cfg else 1


def stage_hardlink_farm(stage: str, source_paths: list[Path]) -> Path:
    """/pnfs hard-link farm putting all input files in one dir (entry
    input_data is basename-keyed; inloc assumes one dir). Hard links, NOT
    symlinks: xrootd doors don't follow /pnfs symlinks, but hard links share
    the dCache namespace entry. Returns the staged dir.
    """
    staged_dir = PNFS_STAGE / stage
    if staged_dir.exists():
        for p in staged_dir.iterdir():
            p.unlink()
    else:
        staged_dir.mkdir(parents=True, exist_ok=True)
    for src in source_paths:
        os.link(src, staged_dir / src.name)
    print(f"[{stage}] hard-linked {len(source_paths)} files into {staged_dir}")
    return staged_dir


def local_input_farm(stage: str, sources: list[Path]) -> tuple[Path, dict]:
    """Local analogue of stage_hardlink_farm at ROOT/<stage>/local_inputs.
    Hard links, falling back to a copy on EXDEV (a local outstage tree and
    ROOT can land on different filesystems). Returns
    (farm_dir, {basename: clamped_merge_or_1}).
    """
    farm_dir = ROOT / stage / "local_inputs"
    if farm_dir.exists():
        for p in farm_dir.iterdir():
            p.unlink()
    else:
        farm_dir.mkdir(parents=True, exist_ok=True)
    merge = _merge_factor_for(stage, len(sources))
    input_map = {}
    for src in sources:
        src = Path(src)
        link = farm_dir / src.name
        try:
            os.link(src, link)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            shutil.copy2(src, link)
        input_map[src.name] = merge
    print(f"[{stage}] local-farmed {len(input_map)} file(s) into {farm_dir}")
    return farm_dir, input_map


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

    One shared 3h token file per user per node (local tmpfs). Refreshing at
    every stage submit (~30x/round) cost ~28 redundant setupmu2e-art.sh
    sourcings + ~3min of serialized submit-lock time per round. Fail-open:
    unknown age -> refresh. MUST be called inside _submit_lock.
    """
    age = _token_age_s()
    if age <= TOKEN_REFRESH_AGE_S:
        print(f"[{stage}] bearer token refreshed {int(age / 60)}m ago, "
              f"skipping getToken", flush=True)
        return
    print(f"[{stage}] renewing bearer token: getToken", flush=True)
    # getToken sources setupmu2e-art.sh -> same transient env-source failure
    # class -> routed through the shared retry helper.
    tok = run_sourced_bash(f"source {SETUPMU2E} >/dev/null 2>&1 && getToken",
                           label=f"{stage}/getToken")
    if tok.stdout.strip():
        print(tok.stdout)
    if tok.returncode != 0:
        raise subprocess.CalledProcessError(
            tok.returncode, "getToken", output=tok.stdout, stderr=tok.stderr)


def stamp_local_events(stage: str, events: int) -> Path:
    """Stamp the events-per-job so harvest scales by what actually ran, not
    stage_cfg's configured value -- otherwise every derived metric is biased
    by the ratio (wiki/incidents/events-per-job-mid-flight-edit.md).
    """
    out = STATE / f"{stage}_events_per_job.txt"
    out.write_text(f"{events}\n")
    return out


def _render_and_build_cnf(stage, cfg, entry_tmpl, *, desc, dsconf, stage_dir,
                          env, njobs, events,
                          staged_inputs) -> tuple[Path, Path, Path, str | None]:
    """Shared render -> build sequence for the grid path and the --local
    branch: write_code_tarball -> render_entry -> write_entry -> build_cnf.
    Keep consolidated: when duplicated per call site, the local branch's
    missing --inloc bug hid in the divergence. Renders ONE inloc expression
    for both and hands it back so the local caller passes that exact value
    to px.run_runlocal.
    """
    tarball = write_code_tarball(
        stage_dir,
        base_tarball=Path(cfg["code_tarball"]) if "code_tarball" in cfg else None,
        extra_files=_stage_extra_files(entry_tmpl))
    inloc = (f"dir:{staged_inputs[0]}" if staged_inputs
            else entry_tmpl.get("inloc"))
    entry = px.render_entry(
        dsconf=dsconf, desc=desc, njobs=njobs, code_tarball=tarball,
        fcl_name=entry_tmpl["fcl"],
        fcl_overrides=_render_fcl_overrides(stage, entry_tmpl),
        events=events, run=entry_tmpl.get("run"),
        memory_mb=cfg.get("memory_mb", entry_tmpl.get("memory")),
        input_data=(staged_inputs[1] if staged_inputs
                   else entry_tmpl.get("input_data")),
        inloc=inloc,
        resampler_name=entry_tmpl.get("resampler_name"),
        outloc=entry_tmpl.get("outloc"))
    entry_path = px.write_entry(STATE, stage, entry)
    cnf = px.build_cnf(stage_dir, entry_path, desc, dsconf,
                       _cnf_build_env(env))
    return cnf, tarball, entry_path, inloc


def submit_stage_prodtools(stage, env, *, staged_inputs=None,
                           dry_run=False) -> int | None:
    """Entry -> json2jobdef -> submit_entry. Returns the cluster id.

    staged_inputs: (staged_dir, {basename: merge_or_count}) for consuming
    stages, None otherwise. Writes cluster.txt, the events stamp, the config
    sha, and the jobsub id jobwait needs.
    """
    cfg = stage_cfg(stage, MODE)
    desc, dsconf = _stage_desc(stage), _stage_dsconf(stage)
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    # cfg.get("events") is the ONE source for events; concat has no "events"
    # key (merge stages take none), hence the .get().
    entry_tmpl = px.load_stage_entry(stage, cfg=CONFIG, geom=GEOM_FILE.name)
    cnf, _tarball, entry_path, _inloc = _render_and_build_cnf(
        stage, cfg, entry_tmpl, desc=desc, dsconf=dsconf, stage_dir=stage_dir,
        env=env, njobs=cfg["njobs"], events=cfg.get("events"),
        staged_inputs=staged_inputs)
    if "events" in cfg:
        stamp_local_events(stage, cfg["events"])
    if dry_run:
        print(f"[{stage}] DRY-RUN: cnf built, not submitted: {cnf.name}")
        return None
    with _submit_lock(stage):
        _maybe_refresh_token(stage)
        cluster, jobsub_id = px.submit_cnf(
            stage_dir, entry_path, LEDGER_DB,
            f"autoresearch:{CONFIG}/{stage}", env, cnf=cnf)
    (STATE / f"{stage}_cluster.txt").write_text(f"{cluster}\n")
    (STATE / f"{stage}_jobsub_id.txt").write_text(f"{jobsub_id}\n")
    _stamp_stage_config_sha(stage)
    print(f"[{stage}] cluster={cluster} ({jobsub_id})")
    return cluster


# Stages the local executor can run. The Cat-resampler stages render with
# staged_inputs=None; concat/mustops_ce stage a prior stage's outputs via
# local_input_farm. A stage absent here is refused loudly rather than handed
# an inputless entry prodtools would accept (a job silently reading nothing).
LOCAL_SUPPORTED_STAGES = ("mubeam", "run1b_mubeam", "elebeam_flash",
                          "concat", "mustops_ce")


def _require_local_stage(stage: str) -> None:
    """Refuse a stage the local executor cannot stage inputs for (plus the
    config-bound and grid-cluster-overwrite refusals, in one helper)."""
    if stage not in LOCAL_SUPPORTED_STAGES:
        raise SystemExit(
            f"[{stage}] the local executor supports "
            f"{', '.join(LOCAL_SUPPORTED_STAGES)} only.")
    # STATE's unbound default is Path() == cwd: an unbound caller would
    # scatter state files into the repo root.
    if not CONFIG:
        raise SystemExit(
            f"[{stage}] no config bound -- pass --config, or call "
            f"_bind_config() first. STATE would otherwise resolve to cwd.")
    # A cluster file with no marker holds a REAL ClusterId; a local submit
    # would silently rewrite a finished grid Eval's provenance (the true
    # cluster id then unrecoverable). Grid path: cmd_submit's idempotency
    # guard; this covers local.
    cluster_file = STATE / f"{stage}_cluster.txt"
    if cluster_file.exists() and not local_marker(stage).exists():
        raise SystemExit(
            f"[{stage}] {cluster_file} holds grid cluster "
            f"{cluster_file.read_text().strip()} -- refusing to overwrite it "
            f"with a local runid. Use a different --config.")


def local_marker(stage: str) -> Path:
    """Marker: state/<stage>_cluster.txt holds a runid, NOT a cluster id.
    Single source of truth for "ran locally" -- without it a later poll in a
    fresh process would hand the literal "1" to px.run_jobwait as a jobid
    for a cluster never submitted.
    """
    return STATE / f"{stage}_local.txt"


def _is_local_stage(stage: str) -> bool:
    """DETECTION: did THIS stage run locally? Marker file only -- deliberately
    NOT `or AUTORESEARCH_LOCAL` (an ACTIVATION switch): the disjunct would
    make cmd_poll a no-op on a LIVE GRID CLUSTER for any operator with the
    env var exported.
    """
    return local_marker(stage).exists()


def _resolve_scale(values, default: int, stage: str) -> int:
    """Resolve repeatable --local-njobs/--local-events values: bare int sets
    the all-stage default (last wins), <stage>=<int> overrides per stage."""
    if not values:
        return default
    bare, per_stage = default, {}
    for raw in values:
        item = str(raw)
        if "=" in item:
            key, _, val = item.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected <stage>=<int>")
            try:
                parsed = int(val.strip())
            except ValueError:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected <stage>=<int>")
            if parsed < 1:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected an int >= 1")
            per_stage[key] = parsed
        else:
            try:
                parsed = int(item)
            except ValueError:
                raise ValueError(
                    f"bad value {item!r}: expected an int or <stage>=<int>")
            if parsed < 1:
                raise ValueError(f"bad value {item!r}: expected an int >= 1")
            bare = parsed
    return per_stage.get(stage, bare)


def _scale_default(env_var: str, fallback: int) -> int:
    """Env-seam default for a --local-* flag: the graph runner shells out to
    `pipeline.py submit` and cannot pass flags. An explicit flag still wins.
    """
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return fallback
    try:
        val = int(raw.strip())
    except ValueError:
        raise ValueError(f"${env_var}={raw!r}: expected an int >= 1")
    if val < 1:
        raise ValueError(f"${env_var}={raw!r}: expected an int >= 1")
    return val


# Local job pool size default (--local-pool / $AUTORESEARCH_LOCAL_POOL).
DEFAULT_LOCAL_POOL = 4


def _local_scale(args, stage: str) -> tuple:
    """(njobs, events) for one stage: flag, else env seam, else the default.
    THE resolver for local scale; called from submit --local's branch."""
    return (
        _resolve_scale(getattr(args, "local_njobs", None),
                       _scale_default("AUTORESEARCH_LOCAL_NJOBS", 1),
                       stage),
        _resolve_scale(getattr(args, "local_events", None),
                       _scale_default("AUTORESEARCH_LOCAL_EVENTS", 200),
                       stage),
    )


def cmd_submit(args):
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    # ACTIVATION (vs _is_local_stage's detection): --local, or the env var so
    # a graph-runner child inherits local mode.
    want_local = bool(getattr(args, "local", False)) or bool(
        os.environ.get("AUTORESEARCH_LOCAL"))
    # A grid submit invalidates any prior --local marker. MUST run BEFORE the
    # idempotency guard (which can't tell a runid from a ClusterId --
    # clearing afterwards made an un-forced submit after a local run silently
    # no-op).
    #
    # INVARIANT (clear half): drop runid and marker TOGETHER, runid first.
    # submit_stage_prodtools rewrites <stage>_cluster.txt only AFTER
    # submit_cnf parses a cluster id, so unlinking the marker alone leaves
    # the runid behind unmarked on every early-exit/raise path -- a later
    # poll would hand it to px.run_jobwait as a ClusterId.
    if not want_local and local_marker(args.stage).exists():
        cluster_file.unlink(missing_ok=True)
        local_marker(args.stage).unlink(missing_ok=True)
    # Idempotency: re-entry no-ops so a killed-and-resumed graph node doesn't
    # double-submit. --force overrides.
    if cluster_file.exists() and not getattr(args, "force", False):
        cid = cluster_file.read_text().strip()
        print(f"[{args.stage}] already submitted (cluster={cid}); skip submit "
              f"(use --force to override)")
        return
    if want_local:
        stage = args.stage
        _require_local_stage(stage)
        pool = (getattr(args, "local_pool", None)
               or _scale_default("AUTORESEARCH_LOCAL_POOL", DEFAULT_LOCAL_POOL))
        cfg = stage_cfg(stage, MODE)
        desc, dsconf = _stage_desc(stage), _stage_dsconf(stage)
        stage_dir = ROOT / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        env = sourced_env()

        # ONE shared resolver; concat below recomputes njobs against the
        # staged source count, but an explicit --local-njobs still wins.
        njobs, events = _local_scale(args, stage)

        staged_inputs = None
        if stage in ("concat", "mustops_ce"):
            # Same previous-stage rule as grid staging (_input_stage_for).
            # The prior stage must have run LOCALLY, or <prev>_outputs.txt
            # holds /pnfs paths.
            prev_stage = _input_stage_for(stage)
            if not local_marker(prev_stage).exists():
                raise SystemExit(
                    f"[{stage}] consumes {prev_stage}, which has no local "
                    f"run ({local_marker(prev_stage)} missing). Run "
                    f"'--config {CONFIG} submit {prev_stage} --local' and "
                    f"'list-outputs {prev_stage}' first.")
            prev_outputs = STATE / f"{prev_stage}_outputs.txt"
            if not prev_outputs.exists():
                raise SystemExit(
                    f"Run 'list-outputs {prev_stage}' first to populate "
                    f"{prev_outputs.name}")
            sources = [Path(p) for p in prev_outputs.read_text().splitlines()
                      if p.strip()]
            if not sources:
                raise SystemExit(
                    f"[{stage}] {prev_outputs.name} is empty -- the local "
                    f"{prev_stage} run produced no output. Check its job "
                    f"log before rebuilding.")
            farm_dir, input_map = local_input_farm(stage, sources)
            staged_inputs = (farm_dir, input_map)
            if stage == "concat":
                merge = _merge_factor_for("concat", len(sources))
                njobs_default = -(-len(sources) // merge)  # ceil division
                njobs = _resolve_scale(getattr(args, "local_njobs", None),
                                       njobs_default, stage)
        # Same render/build sequence as grid; only njobs/events differ (LOCAL
        # scale, not stage_cfg). `run` is a fixed cnf run-number.
        entry_tmpl = px.load_stage_entry(stage, cfg=CONFIG, geom=GEOM_FILE.name)
        cnf, tarball, _entry_path, inloc = _render_and_build_cnf(
            stage, cfg, entry_tmpl, desc=desc, dsconf=dsconf,
            stage_dir=stage_dir, env=env, njobs=njobs, events=events,
            staged_inputs=staged_inputs)
        if args.dry_run:
            # Build everything, dispatch nothing -- deliberately BEFORE the
            # marker/cluster writes, which declare "ran locally" and would
            # leave poll/list-outputs hunting a wait.json that never exists.
            print(f"[{stage}] DRY-RUN: cnf built, not run: {cnf.name}")
            return
        # INVARIANT (write half): marker FIRST, then the runid. A death
        # between the two writes leaves a marker with no cluster file (poll
        # no-ops, harmless) rather than a runid indistinguishable from a
        # real ClusterId. The cluster file just needs a parseable int ("1").
        local_marker(stage).write_text("1\n")
        (STATE / f"{stage}_cluster.txt").write_text("1\n")
        stamp_local_events(stage, events)
        # Local jobs resample inputs over xrootd like grid workers -> need a
        # live bearer token. No _submit_lock: no condor_vault_storer here.
        _maybe_refresh_token(stage)
        # `inloc` MUST reach runlocal -- without it prodtools defaults to
        # --inloc tape and resolves a locally-farmed basename against
        # /pnfs/mu2e/tape instead of the farm dir this branch just built. It
        # is the exact value _render_and_build_cnf resolved, not re-derived.
        px.run_runlocal(stage_dir, cnf, njobs,
                        px.wait_json_path(STATE, stage), env,
                        code_tarball=tarball, pool=pool, inloc=inloc)
        # Acceptance policy is the caller's: WARN on shortfall, never
        # SystemExit -- a partial local run is still consumable
        # (list-outputs divides by the true ok count).
        wait = px.read_wait(STATE, stage)
        ok = wait.get("ok", 0)
        if ok < njobs:
            print(f"[{stage}] WARN: {ok}/{njobs} local job(s) ok "
                  f"(failed={wait.get('failed')}, "
                  f"unknown={wait.get('unknown', [])})")
        return
    # Stage-chain stamp at first submit so harvest never re-interprets an old
    # config under the current env's chain (the ff11R00_07 +1.5% sob bias
    # class). Owner: harvest.resolve_muminus_inputs / stamped_stage_chain.
    if not (STATE / hv.STAGE_CHAIN_STAMP).exists():
        hv.stamp_stage_chain(STATE, list(GRID_STAGES))
    env = sourced_env()
    staged_inputs = None
    if args.stage in ("concat", "mustops_ce"):
        # input_data requires basenames: hard-link the previous stage's
        # outputs into a /pnfs stage dir xrootd can resolve.
        prev_stage = _input_stage_for(args.stage)
        prev = STATE / f"{prev_stage}_outputs.txt"
        if not prev.exists():
            raise SystemExit(f"Run 'list-outputs {prev_stage}' first to populate {prev.name}")
        sources = [Path(p) for p in prev.read_text().splitlines() if p.strip()]
        staged_dir = stage_hardlink_farm(args.stage, sources)
        merge = _merge_factor_for(args.stage, len(sources))
        staged_inputs = (staged_dir, {p.name: merge for p in sources})
    submit_stage_prodtools(args.stage, env, staged_inputs=staged_inputs,
                           dry_run=args.dry_run)


def cmd_poll(args):
    if _is_local_stage(args.stage):
        print(f"[{args.stage}] local mode: jobs already complete; poll is a no-op")
        return
    _check_stage_config_sha(args.stage)
    cfg = stage_cfg(args.stage, MODE)
    stage_dir = ROOT / args.stage
    jid_file = STATE / f"{args.stage}_jobsub_id.txt"
    jobid = (jid_file.read_text().strip() if jid_file.exists()
             else (STATE / f"{args.stage}_cluster.txt").read_text().strip())
    cnf = px.cnf_path(stage_dir, _stage_desc(args.stage), _stage_dsconf(args.stage))
    px.run_jobwait(stage_dir, cnf, jobid, cfg["njobs"],
                   px.wait_json_path(STATE, args.stage), sourced_env())
    # Acceptance is autoresearch policy: a partial cluster proceeds (harvest
    # divides by the true ok count), below-quorum is loud, zero ok fails.
    wait = px.read_wait(STATE, args.stage)
    quorum = getattr(args, "quorum", None)
    quorum = quorum if quorum is not None else cfg.get("quorum", 0.9)
    target = max(1, int(cfg["njobs"] * quorum))
    if wait["ok"] == 0:
        raise SystemExit(
            f"[{args.stage}] 0/{cfg['njobs']} jobs succeeded "
            f"(failed={wait.get('failed')}, unknown={wait.get('unknown')})")
    if wait["ok"] < target:
        print(f"[{args.stage}] WARN: {wait['ok']}/{cfg['njobs']} ok "
              f"(< quorum target {target}); proceeding with what landed")


def cmd_list_outputs(args):
    _check_stage_config_sha(args.stage)
    # Idempotency: skip the re-glob if every listed path still resolves.
    outputs_file = STATE / f"{args.stage}_outputs.txt"
    if outputs_file.exists() and not getattr(args, "force", False):
        listed = [p for p in outputs_file.read_text().splitlines() if p.strip()]
        if listed and all(Path(p).exists() for p in listed):
            print(f"[{args.stage}] outputs already listed ({len(listed)} files); "
                  f"skip (use --force to override)")
            return
    # Both executors write the same wait.json, so one reader for both.
    wait = px.read_wait(STATE, args.stage)
    files = px.outputs_from_wait(wait, stage_cfg(args.stage, MODE)["output_glob"])
    outputs_file.write_text("\n".join(files) + "\n")
    print(f"[{args.stage}] {len(files)} output file(s) "
          f"(ok={wait.get('ok')}, failed={wait.get('failed')}, "
          f"unknown={wait.get('unknown', [])}) -> {outputs_file}")


# Fraction of upstream POT surviving into the MuBeamCat resampler input;
# converts per-simulated-event yields to per-POT.
RUN1A_MUBEAM_INPUT_CORRECTION = hv.RUN1A_MUBEAM_INPUT_CORRECTION  # single source in harvest.py

from paths import REPO_ROOT as AUTORESEARCH  # see core/paths.py

# TargetMuonFinder/stopmat bin labels (mmackenz extract_analysis_results._CALO_STOP_MATERIALS)
_CALO_STOP_MATERIALS = ("G4_CESIUM_IODIDE", "CarbonFiber", "AluminumHoneycomb")

# Tracker StrawGasStep ionizing-Edep extractor (foilsflash objective). Uses
# gallery: uproot can't read StrawGasStep (wiki
# uproot-cannot-read-steppointmc). InputTag auto-discovered from candidates.
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
    """Mean tracker StrawGasStep ionizing Edep (MeV) per event. Gallery needs
    the muse env, so shell out to a python subprocess inheriting `env`."""
    if not pileup_files:
        return None, None, None, None
    proc = subprocess.run(
        ["python3", "-c", _TRK_EDEP_EXTRACT_SCRIPT],
        input=json.dumps({"files": [str(p) for p in pileup_files],
                          "tags": list(_TRK_EDEP_CANDIDATE_TAGS)}),
        env=env, capture_output=True, text=True, check=True,
    )
    # gallery/xrootd prints to stdout AFTER our result -- don't trust the
    # last line; find the sentinel-prefixed one.
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
    """events_per_job actually used at submit time (stamped file, falling
    back to stage_cfg for pre-stamp chains) -- editing the JSON between
    submit and harvest otherwise mis-scales every derived metric
    (wiki/incidents/events-per-job-mid-flight-edit.md).
    """
    return hv.events_per_job(STATE, stage, stage_cfg(stage, MODE)["events"])


def _extract_calo_per_pot(run1b_files, env):
    """Sum TargetMuonFinder/stopmat calo bins across run1b_mubeam nts files;
    calo_per_pot = (sum / total simulated events) * input_corr. PyROOT needs
    the muse env, so shell out to a subprocess inheriting `env`.
    """
    if not run1b_files:
        return None, None, None
    # len(run1b_files), not configured njobs -- lost-job denominator rule.
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
    """Record a fail-softed secondary extraction: echo + stamp degraded."""
    if sec.error:
        print(f"    {sec.error}")
        degraded[stage] = sec.error


def cmd_harvest(args):
    """Compute s_over_sqrt_b from the pipeline outputs.

    Steps (mirrors extract_analysis_results.run_rough_run1a_sensitivity_analysis):
      1. EdepAna on mustops_ce CeEndpoint art files -> nts ROOT + 'Saw N'
      2. Count events in MuminusStopsCat -> muminus_stops
      3. ce_scale = input_corr * (muminus_stops / mubeam_sim_total) / ce_simulated_events
         ce_abs_eff = ce_seen * ce_scale
      4. rough_run1a_sensitivity.C -> parse 'S/sqrt(B) = X'
    """
    # Check config-sha only for stages this run actually produced (chains
    # differ per mode) -- key off the stamped files, not a per-mode tuple.
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
    # harvest.resolve_muminus_inputs owns "did concat run for THIS Eval".
    muminus_files, muminus_source = hv.resolve_muminus_inputs(STATE)

    # Denominators derive from the files actually harvested, NOT configured
    # njobs: lost jobs (OOM, held) would bias ce_abs_eff / s_over_sqrt_b
    # high by the loss fraction. wiki/incidents/harvest-denominator-bug.md.
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

    # Step 6: EARLY-FLASH StrawGasStep Edep (foilsflash 2nd objective);
    # present only when the chain ran elebeam_flash (un-prescaled, so the
    # total is the FULL early flash). Objective = flash_edep_per_pot = total
    # / (n_input_electrons * POT_PER_ELECTRON); per-event mean is BLIND to
    # rate, kept as a diagnostic. Fail-soft like calo.
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
    # POT denominator = landed files x stamped events_per_job x
    # POT_PER_ELECTRON -- see events-per-job incident.
    epj_flash = _events_per_job("elebeam_flash")
    flash_edep_per_pot, flash_n_input = hv.per_pot(
        flash_edep_total_MeV, flash.n_files, epj_flash)
    # Winsorized per-POT mean + spread: run-level DIAGNOSTICS only; the
    # leaderboard stays on the plain mean.
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
    p_sub.add_argument("stage", choices=list(ALL_STAGES))
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

    p_poll = sub.add_parser("poll", help="Wait for a stage's cluster via prodtools jobwait")
    p_poll.add_argument("stage", choices=list(ALL_STAGES))
    p_poll.add_argument("--quorum", type=float, default=None,
                        help="Fraction of jobs required (default: per-stage "
                             "stage_cfg()'s quorum if set, else 0.9)")
    p_poll.set_defaults(func=cmd_poll)

    p_ls = sub.add_parser(
        "list-outputs",
        help="Read the stage's wait.json (runlocal/jobwait) and persist "
             "its ok-job output paths")
    p_ls.add_argument("stage", choices=list(ALL_STAGES))
    p_ls.add_argument("--force", action="store_true",
                      help="Re-glob even if state/<stage>_outputs.txt validates.")
    p_ls.set_defaults(func=cmd_list_outputs)

    p_harv = sub.add_parser("harvest", help="Aggregate stage outputs into summary.json")
    p_harv.set_defaults(func=cmd_harvest)

    args = p.parse_args()
    _bind_config(args.config)
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
