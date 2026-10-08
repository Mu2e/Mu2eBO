"""The geometry pre-check's pieces, as plain functions (Phase C2a spec,
docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md, "1. The
offline_preflight kit"): the surface-check files, running `mu2e -n 1`
from a code tarball's Code/, and reading its log into a verdict.
run_preflight is the whole sequence; the offline_preflight adapter
(core/adapters/offline_preflight.py) calls it.
Stdlib and prodtools_entry only.
"""
from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from adapters import prodtools_entry as pe

SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
# Wall-clock cap on one `mu2e -n 1` check (G4 init + surface check).
TIMEOUT_S = 1200

# Preflight verdict vocabulary: a check returns pass, fail_managed (every
# FAIL) or ambiguous.
PREFLIGHT_VERDICTS = ("pass", "fail_managed", "ambiguous")

FCL_NAME = "surfacecheck.fcl"
# run_preflight keeps the check's output here, in the workdir.
LOG_NAME = "preflight.log"

G4_GEOM_FAIL_RX = re.compile(
    r"G4Exception.*?(GeomMgt000\d|GeomVol1002|GeomSolids00\d\d|placement|outside mother|overlap)",
    re.IGNORECASE | re.DOTALL,
)

# Fatal G4/art aborts that must FAIL preflight regardless of past_init:
# past_init fires on pre-geometry strings, so a geometry abort AFTER them
# was misclassified PASS while the grid died on the identical error. See
# wiki/incidents/preflight-past-init-false-pass.md.
G4_FATAL_RX = re.compile(
    r"G4Exception\s*:\s*GeomSolids00\d\d"
    r"|\*\*\* Fatal Exception \*\*\*"
    r"|G4Exception.*?Aborting execution",
    re.IGNORECASE | re.DOTALL,
)

# Surface-check detects silent volume overlaps that wouldn't fail G4 init
# (wiki external/mu2e-overlap-check, incidents/tsda-disc-helical-sibling-overlap).
SURFACE_CHECK_GEOM_OVERLAY = """\
#include "{base_geom_basename}"

// Activate G4 CheckOverlaps surface sampling.
bool g4.doSurfaceCheck             = true;
int  g4.nSurfaceCheckPointsPercmsq = 1;
int  g4.minSurfaceCheckPoints      = 100;
int  g4.maxSurfaceCheckPoints      = 10000000;
"""

SURFACE_CHECK_FCL = """\
#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"

services.GeometryService.inputFile : "{geom_basename}"
{gdml_lines}"""

# GDML geometry assertion (foils family): the dump reflects what G4 ACTUALLY
# built, catching value-level divergence the holeRadii canary can't see.
PREFLIGHT_GDML_NAME = "preflight_geom.gdml"
PREFLIGHT_GDML_FCL_LINES = (
    'physics.producers.g4run.debug.writeGDML : true\n'
    f'physics.producers.g4run.debug.GDMLFileName : "{PREFLIGHT_GDML_NAME}"\n'
)

# G4's GDML writer appends a pointer suffix ("Foil_020x55d1..."). A greedy
# \d+ would swallow the leading 0 of "0x" and scramble indices (foil 02 ->
# "20"); non-greedy digits + anchored optional 0x-suffix is exact.
GDML_FOIL_TUBE_RX = re.compile(r"Foil_(\d+?)(?:0x[0-9a-fA-F]+)?$")


def verify_stopping_target_gdml(gdml_path, geom_text, tol_mm=1e-3):
    """Assert the G4-built stopping-target foils match the geom file.

    Plain XML iterparse -- NOT ROOT TGDMLParse, which segfaults on forward
    volume refs (wiki/incidents/root-gdml-forward-volume-ref.md). Each foil
    is a uniquely named G4Tubs "Foil_NN" (constructStoppingTarget.cc:162).
    Returns mismatch strings; empty == verified.
    """
    def _vec(key):
        m = re.search(
            rf"vector<double>\s+stoppingTarget\.{key}\s*=\s*\{{([^}}]*)\}}",
            geom_text)
        return [float(v) for v in m.group(1).split(",")] if m else None

    radii = _vec("radii")
    if radii is None:
        return ["geom has no stoppingTarget.radii vector — nothing to verify"]
    half = _vec("halfThicknesses") or []
    if half and len(half) < len(radii):
        # StoppingTargetMaker repeats the last halfThickness entry.
        half = half + [half[-1]] * (len(radii) - len(half))
    holes = _vec("holeRadii")
    if holes is None:
        m = re.search(r"stoppingTarget\.holeRadius\s*=\s*([0-9.eE+-]+)",
                      geom_text)
        holes = [float(m.group(1))] * len(radii) if m else [0.0] * len(radii)

    found = {}
    for _ev, el in ET.iterparse(str(gdml_path)):
        if el.tag.split("}")[-1] == "tube":
            m = GDML_FOIL_TUBE_RX.match(el.get("name", ""))
            if m:
                lunit = el.get("lunit", "mm")
                scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0}.get(lunit)
                if scale is None:
                    return [f"GDML tube {el.get('name')} has unknown "
                            f"lunit={lunit}"]
                found[int(m.group(1))] = (
                    float(el.get("rmin", 0.0)) * scale,
                    float(el.get("rmax")) * scale,
                    float(el.get("z")) * scale,  # GDML z = FULL length
                )
        el.clear()

    errs = []
    if len(found) != len(radii):
        errs.append(f"GDML has {len(found)} Foil_* tubes but geom "
                    f"specifies {len(radii)} foils")
    missing = [i for i in range(len(radii)) if i not in found]
    if missing:
        errs.append(f"foils missing from GDML: {missing[:10]}"
                    f"{'...' if len(missing) > 10 else ''}")
    for i, r_out in enumerate(radii):
        if i not in found:
            continue
        rmin, rmax, z_full = found[i]
        checks = [("rIn", rmin, holes[i]), ("rOut", rmax, r_out)]
        if half:
            checks.append(("fullThickness", z_full, 2.0 * half[i]))
        for label, got, want in checks:
            if abs(got - want) > tol_mm:
                errs.append(f"Foil_{i:02d} {label}: GDML={got:.4f} "
                            f"geom={want:.4f} (Δ={got - want:+.4f} mm)")
    return errs


# Only overlaps involving BO-managed volumes (StoppingTargetFoil_*) matter:
# stock Mu2e geometry has ~117 baseline overlap lines (FoilSupportStructure_*,
# NorthRailDS3/SouthRailDS3, VirtualDetector_EMC_0_Front), whitelisted by
# volume name.
SURFACE_OVERLAP_RX = re.compile(r"Overlap is detected for volume\s+(\S+)")
SURFACE_OVERLAP_MANAGED = re.compile(r"^StoppingTargetFoil_")

# art got this far (BeginRun, the event loop, produce() asking for input):
# a geometry message after it is advisory surface-check noise.
_PAST_INIT = ("BeginRun", "Event::beginEvent", "EndOfEventAction",
              "Begin processing the 1st record", "GenParticle")
# Any of these in the output means `mu2e` started.
_BANNERS = ("Geant4", "%MSG", "Art has", "Begin processing", "G4Exception")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str                    # one of PREFLIGHT_VERDICTS
    reason: str                  # the PASS / FAIL / AMBIGUOUS line's text
    notes: Tuple[str, ...] = ()  # what the check found on the way
    # The as-built GDML comparison ran and passed (a later rule may still
    # fail the check).
    gdml_verified: bool = False


def overlap_banner(checks_managed_overlap, require_zero_overlaps) -> str:
    """PASS-line suffix naming which overlap policy actually ran (kept next
    to the policy flags so it cannot drift from the gate)."""
    if not checks_managed_overlap:
        return ""
    if require_zero_overlaps:
        return " and zero surface-check overlaps"
    return " and no managed-volume overlap"


def geom_name(config: str) -> str:
    """The geometry file's name for `config`: the name the grid jobs use."""
    return f"autoresearch_{config}_geom.txt"


def check_files(geom_basename: str, *, dumps_gdml: bool) -> dict:
    """{file name: text} of the check's two files: the geometry overlay
    that turns on G4's surface check around `geom_basename`, and the FCL
    that reads it (plus the GDML dump lines when `dumps_gdml`). One G4
    init covers both checks: surfacecheck.fcl enables doSurfaceCheck AND
    exercises the plain G4-init path."""
    overlay = f"surfacecheck_{geom_basename}"
    return {
        overlay: SURFACE_CHECK_GEOM_OVERLAY.format(
            base_geom_basename=geom_basename),
        FCL_NAME: SURFACE_CHECK_FCL.format(
            geom_basename=overlay,
            gdml_lines=PREFLIGHT_GDML_FCL_LINES if dumps_gdml else ""),
    }


def stage_workdir(workdir, *, geom_text: str, geom_basename: str,
                  dumps_gdml: bool) -> Path:
    """Empty `workdir` (created when absent), then write the point's
    geometry as `geom_basename` and the check files into it. Emptied, so
    a rerun never reads the last run's GDML dump or log as its own."""
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    (workdir / geom_basename).write_text(geom_text)
    for name, text in check_files(geom_basename,
                                  dumps_gdml=dumps_gdml).items():
        (workdir / name).write_text(text)
    return workdir


def retry_if_mu2e_never_started(proc) -> bool:
    """run_sourced_bash's retry rule for the check. A transient env-source
    flake ([Errno 5]) leaves `mu2e` unsourced: a nonzero exit with no
    Geant4/art banner. A banner-bearing result is a real run and must NOT
    be retried (wiki/incidents/sourced-env-stderr-swallowed.md)."""
    combined = (proc.stdout or "") + (proc.stderr or "")
    started = any(s in combined for s in _BANNERS)
    return proc.returncode != 0 and not started


# Retries of run_sourced_bash: 4 attempts in all, ~50 s worst case.
DEFAULT_BACKOFFS = (5, 15, 30)
# Node-local /tmp, never NFS HOME (run_sourced_bash).
_SPACK_CACHE = f"/tmp/spack_cache_{os.environ.get('USER', 'x')}"


def run_sourced_bash(
    cmd: str,
    *,
    timeout: Optional[float] = None,
    backoffs: tuple = DEFAULT_BACKOFFS,
    should_retry: Optional[Callable[[subprocess.CompletedProcess], bool]] = None,
    label: str = "sourced_bash",
    log=sys.stderr,
) -> subprocess.CompletedProcess:
    """Run ``bash -c cmd`` with retry + backoff, for a command that sources
    the mu2e environment.

    Transient class: cvmfs read misses and the NFSv4.0 seqid wedge on
    ~/.spack locks (wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) --
    ``==> Error: [Errno 5]`` mid-``setupmu2e-art.sh`` leaves ``muse``/``mu2e``
    undefined (often rc=127); a re-run seconds later succeeds. Every command
    exports ``SPACK_USER_CACHE_PATH`` onto node-local /tmp so spack's fcntl
    locks never touch NFS. Coverage map:
    wiki/incidents/sourced-env-stderr-swallowed.md.

    Retries while ``should_retry(proc)`` (default rc != 0), up to
    ``len(backoffs) + 1`` attempts. A timeout is NON-retriable -- it means
    the command was running (slow init), not an env flake -- returned as
    ``CompletedProcess(returncode=-1)`` with ``.timed_out = True``. Every
    return path sets ``.timed_out``; never raises on a nonzero rc."""
    if should_retry is None:
        should_retry = lambda p: p.returncode != 0  # noqa: E731
    # Must be inside the command string: a parent-shell export does NOT
    # propagate to the sourced environment (foilsZ05, 2026-06-05).
    cmd = f"export SPACK_USER_CACHE_PATH={_SPACK_CACHE} && {cmd}"
    argv = ["bash", "-c", cmd]
    for attempt in range(len(backoffs) + 1):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            proc.timed_out = False
        except subprocess.TimeoutExpired as exc:
            out, err = exc.stdout or "", exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            if isinstance(err, bytes):
                err = err.decode(errors="replace")
            proc = subprocess.CompletedProcess(argv, -1, stdout=out, stderr=err)
            proc.timed_out = True
            return proc
        if not should_retry(proc) or attempt == len(backoffs):
            return proc
        wait = backoffs[attempt]
        print(f"[{label}] attempt {attempt + 1}/{len(backoffs) + 1} rc={proc.returncode}; "
              f"retrying in {wait}s (transient cvmfs/spack flake?)", file=log, flush=True)
        time.sleep(wait)
    return proc  # unreachable: the loop always returns on the last attempt


def run_check(code_dir, workdir, fcl: str, *, timeout_s,
              label: str = "preflight", log=None):
    """Run `mu2e -c <fcl> -n 1` in `workdir` under the code tarball
    unpacked at `code_dir` (prodtools_entry.unpacked): setupmu2e-art.sh,
    then <code_dir>/Code/setup.sh, with `workdir` first on MU2E_SEARCH_PATH
    and FHICL_FILE_PATH so the point's geometry and the check files win.
    Retried only when mu2e never started. Returns (out, rc, timed_out);
    `out` is stdout, a separator line, then stderr."""
    setup = Path(code_dir) / "Code" / "setup.sh"
    cmd = (
        # A launching shell with muse already set up makes `muse setup`
        # refuse ("Muse already setup"), which reads as the env flake and
        # would burn every retry. Unset only this variable, as prodtools'
        # runlocal does for its jobs (utils/runlocal.py:child_env).
        "unset MUSE_WORK_DIR && "
        # `>/dev/null` (not `2>&1`) lets a flake's stderr reach the log.
        f"source {SETUPMU2E} >/dev/null && "
        f"source {setup} >/dev/null && "
        f'export MU2E_SEARCH_PATH="{workdir}:$MU2E_SEARCH_PATH" && '
        f'export FHICL_FILE_PATH="{workdir}:$FHICL_FILE_PATH" && '
        f"cd {workdir} && "
        f"mu2e -c {fcl} -n 1")
    proc = run_sourced_bash(cmd, timeout=timeout_s,
                            should_retry=retry_if_mu2e_never_started,
                            label=label, log=log or sys.stdout)
    out = (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or "")
    return out, proc.returncode, proc.timed_out


def _overlap_context(out, vols) -> str:
    """The log around the first listed volume's overlap report, as a block
    to append to a FAIL reason; empty when the log has none."""
    for v in vols[:1]:
        m = re.search(rf"Overlap is detected for volume\s+{re.escape(v)}.*",
                      out)
        if m:
            return f"\ncontext:\n{out[max(0, m.start() - 100): m.end() + 400]}"
    return ""


def classify(out, rc, timed_out, *, geom_text, gdml_path,
             verifies_foil_gdml, checks_managed_overlap,
             require_zero_overlaps) -> Verdict:
    """The verdict on one check's output, by these rules in order (fatal
    abort, as-built GDML, overlaps, a geometry error before init, then pass
    or ambiguous), minus the retired `holeRadii
    vector active` printout check: upstream Offline prints no such line,
    and the GDML comparison checks every foil's hole radius."""
    notes = []
    verified = False

    def fail(reason):
        return Verdict(False, "fail_managed", reason, tuple(notes), verified)

    past_init = any(s in out for s in _PAST_INIT)

    # Fatal aborts FAIL unconditionally, before past_init or surface-check
    # logic can mask them (see G4_FATAL_RX).
    fatal = G4_FATAL_RX.search(out)
    if fatal:
        snippet = out[max(0, fatal.start() - 300): fatal.end() + 400]
        return fail(f"fatal G4/art abort:\n{snippet}")

    # As-built assertion: G4-constructed foil stack (GDML) vs the geom file,
    # per foil. HARD gate: a run whose built geometry differs from x must
    # never reach the grid.
    if verifies_foil_gdml:
        gdml_path = Path(gdml_path)
        if not gdml_path.exists():
            return fail(f"GDML dump {gdml_path.name} not produced — cannot "
                        f"verify as-built geometry (writeGDML missing from "
                        f"env?)")
        # A dump cut short by a timeout or a crash mid-write is truncated or
        # unreadable XML; that must FAIL the point, not raise out of
        # classify() (node_preflight has no ET.ParseError/OSError handler).
        try:
            mismatches = verify_stopping_target_gdml(gdml_path, geom_text)
        except (ET.ParseError, OSError) as exc:
            return fail(f"GDML dump {gdml_path.name} could not be parsed: "
                        f"{exc}")
        if mismatches:
            listed = "\n".join(f"    {m}" for m in mismatches[:10])
            return fail(f"as-built geometry differs from geom file "
                        f"({len(mismatches)} mismatches):\n{listed}")
        verified = True
        radii_m = re.search(
            r"vector<double>\s+stoppingTarget\.radii\s*=\s*\{([^}]*)\}",
            geom_text)
        n_foils = len(radii_m.group(1).split(",")) if radii_m else 0
        notes.append(f"geometry assertion: {n_foils} foils verified against "
                     f"as-built GDML (rIn/rOut/thickness)")

    # Surface-check emits advisory GeomVol1002 warnings on every baseline
    # overlap (~117 in stock geometry), so the geom_fail regex is only
    # consulted when construction actually aborted (past_init=False).
    if checks_managed_overlap:
        all_hits = SURFACE_OVERLAP_RX.findall(out)
        unique_all = sorted(set(all_hits))
        managed_hits = [v for v in all_hits if SURFACE_OVERLAP_MANAGED.match(v)]
        unique_managed = sorted(set(managed_hits))
        baseline_count = len(all_hits) - len(managed_hits)
        notes.append(f"surface-check total_hits={len(all_hits)} "
                     f"unique_volumes={len(unique_all)} "
                     f"baseline={baseline_count} managed={len(managed_hits)}")
        # Strict policy first, so the reported reason is the real one. The
        # name-based managed/baseline split falsely assumes "not named like
        # a BO volume" => "independent of BO knobs": IPAsupport_* sits at a
        # z derived from targetEnd (MECOStyleProtonAbsorberMaker.cc:124-129);
        # foilsflashRUN1BAP01 introduced 3 such overlaps and still PASSED.
        # Studies whose release can reach zero opt into failing on ANY
        # overlap.
        if require_zero_overlaps and all_hits:
            listed = "\n".join(
                f"    {v}"
                f"{'  [managed]' if SURFACE_OVERLAP_MANAGED.match(v) else ''}"
                for v in unique_all)
            return fail(f"zero-overlap policy: {len(all_hits)} overlap(s) in "
                        f"{len(unique_all)} volume(s):\n{listed}"
                        + _overlap_context(out, unique_managed or unique_all))
        if managed_hits:
            listed = "\n".join(f"    {v}" for v in unique_managed)
            return fail(f"managed-volume overlap detected:\n{listed}"
                        + _overlap_context(out, unique_managed))
        if baseline_count:
            notes.append(f"(info) {baseline_count} known stock-geometry "
                         f"overlaps ({len(unique_all)} unique volumes); "
                         f"ignored — not managed by BO knobs.")

    if not past_init:
        geom_fail = G4_GEOM_FAIL_RX.search(out)
        if geom_fail:
            snippet = out[max(0, geom_fail.start() - 200): geom_fail.end() + 600]
            return fail(f"Geant4 geometry error:\n{snippet}")

    if timed_out or rc == 0 or past_init:
        return Verdict(True, "pass",
                       f"init=True; no geom-fail signature"
                       f"{overlap_banner(checks_managed_overlap, require_zero_overlaps)}.",
                       tuple(notes), verified)

    tail = "\n".join(out.splitlines()[-40:])
    return Verdict(False, "ambiguous",
                   f"rc={rc}, no geom-fail signature. Last 40 lines of "
                   f"log:\n{tail}", tuple(notes), verified)


def run_preflight(code_tarball, geom_text: str, config: str, workdir, *,
                  cache_root, dumps_gdml: bool, verifies_foil_gdml: bool,
                  checks_managed_overlap: bool, require_zero_overlaps: bool,
                  label: str = "preflight", timeout_s: float = TIMEOUT_S,
                  log=None, runner=None) -> Tuple[Verdict, str]:
    """The whole pre-check of one point: unpack `code_tarball` once per
    content under `cache_root` (prodtools_entry.unpacked), stage the
    emptied `workdir` (the geometry as geom_name(config), plus the check
    files), run the check (`runner`, default run_check; `log` takes its
    retry messages), keep its output as <workdir>/preflight.log, classify.
    Returns (verdict, out); the verdict's first note is the run's return
    code, and a dump the check wrote stays at <workdir>/preflight_geom.gdml.
    A missing or non-muse tarball raises before anything runs."""
    runner = run_check if runner is None else runner
    code_dir = pe.unpacked(code_tarball, cache_root)
    workdir = stage_workdir(workdir, geom_text=geom_text,
                            geom_basename=geom_name(config),
                            dumps_gdml=dumps_gdml)
    out, rc, timed_out = runner(code_dir, workdir, FCL_NAME,
                                timeout_s=timeout_s, label=label, log=log)
    (workdir / LOG_NAME).write_text(out)
    verdict = classify(out, rc, timed_out, geom_text=geom_text,
                       gdml_path=workdir / PREFLIGHT_GDML_NAME,
                       verifies_foil_gdml=verifies_foil_gdml,
                       checks_managed_overlap=checks_managed_overlap,
                       require_zero_overlaps=require_zero_overlaps)
    ran = f"return code: {rc}  timed_out={timed_out}"
    return dataclasses.replace(verdict, notes=(ran,) + verdict.notes), out
