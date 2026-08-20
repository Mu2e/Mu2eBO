#!/usr/bin/env python3
"""Bayesian Optimization driver for Mu2e geometry searches.

Modes are JSON-defined (mode_specs/<name>.json, schema in
mode_specs/README.md; bounds/facts in modes.SPECS, the registry of record).

Subcommands:
  propose   : propose next candidate(s), render geom override file(s)
  evaluate  : parse summary.json + append to leaderboard
  preflight : run mu2e -n 1 locally to catch G4 init failures

JsonMode is the single driver class, one instance per spec; MODES is keyed
1:1 with modes.SPECS (ADR-0002). Adding a mode = drop a JSON file.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

# ModeSpec registry (ADR-0002): preflight policy flags replace the
# hand-listed mode tuples behind the preflight-mode-tuple-omission class.
import modes as _modes  # noqa: E402

from leaderboard import (  # noqa: E402  (re-exports: Point, to_py_scalars
    Leaderboard, Point, to_py_scalars,   # are public API of this module)
    _flock_ex, _flock_sh, _lock_path)

from paths import REPO_ROOT as ROOT  # single root resolver, see core/paths.py
from paths import BO_WORK, GRID_DATA_ROOT
from paths import leaderboard_archive, leaderboard_live

# Explicit-env mode stamp; see core/modes.py::stamp_mode_from_argv.
os.environ.setdefault("AUTORESEARCH_MODE", _modes.resolve_env_mode())
from runtime import PREFLIGHT_TIMEOUT_S, SETUPMU2E  # noqa: E402
sys.path.insert(0, str(ROOT / "graph"))
from sourced_bash import run_sourced_bash  # noqa: E402

DEFAULT_ALPHA = 1.0e5  # mmackenz calo range 4e-8..2.5e-5; alpha=1e5 makes
                       # 1e-5 calo cost 1 unit of S/sqrt(B). Override per study.


class SpaceDim(NamedTuple):
    """One search-space dimension (the picker reads bounds from modes.SPECS
    directly; this exists for the lockstep check and printing)."""
    name: str
    low: float
    high: float
    is_int: bool


# --- JsonMode: the mode seam. One instance per mode_specs/*.json ----------

class JsonMode:
    """A BO mode = search space + render + prior loader + leaderboard format,
    all read from the same modes.SPECS spec (TSV I/O delegated to
    core/leaderboard.py via leaderboard_io())."""
    name: str
    leaderboard: Path
    proposal_dir: Path
    preflight_dir: Path

    def __init__(self, name: str):
        spec = _modes.SPECS[name]
        if spec.geom is None:
            raise ValueError(f"{name}: JsonMode requires a geom template")
        self.name = name
        # Live rows -> operator's /data board; committed leaderboards/ are
        # read-only priors.
        self.leaderboard = leaderboard_live(spec.leaderboard_rel)
        self.leaderboard_archive = leaderboard_archive(spec.leaderboard_rel)
        self.proposal_dir = BO_WORK / "proposals" / name
        self.preflight_dir = BO_WORK / "preflight" / name

    def _geom_text(self, x) -> str:
        return _modes.SPECS[self.name].geom.render(x)

    def load_priors(self) -> list[Point]:
        """No code-carried priors: Sobol cold-start + leaderboard history."""
        return []

    # --- x recovery at evaluate time (the seam cmd_evaluate calls) ---
    def x_for_evaluate(self, config_name: str, geom_text: str):
        """Recover x from the pending TSV (written at propose, cleared only
        after this call). An absent config is a HARD refusal: a guessed x
        would train the GP on a point that was never evaluated.
        """
        for name, x in self.load_pending():
            if name == config_name:
                return list(x)
        raise SystemExit(
            f"[{self.name}] cannot recover x for {config_name!r}: no such row "
            f"in {self.pending_path()}. JSON-defined modes have no geometry "
            f"parser, so the pending TSV is the ONLY record of the proposed "
            f"x; it is written by propose and cleared by a SUCCESSFUL "
            f"evaluate. Re-running evaluate for an already-recorded config "
            f"hits this. Refusing to append a row rather than guess x.")

    # Row shape (KNOB_NAMES/KNOB_FMTS/metric_cols) reads modes.SPECS, the
    # single source (ADR-0002 extension) -- no class-attr overrides.
    @property
    def KNOB_NAMES(self) -> tuple:
        return _modes.SPECS[self.name].knob_names

    @property
    def KNOB_FMTS(self) -> tuple:
        return _modes.SPECS[self.name].knob_fmts

    # bounds↔KNOB_NAMES must line up 1:1 -- a mismatch is a loud error,
    # never a silently-truncated space.
    def build_space(self) -> list[SpaceDim]:
        spec = _modes.SPECS[self.name]
        # lockstep enforced at ModeSpec construction (modes.py __post_init__)
        int_dims = set(spec.int_dims or ())
        return [
            SpaceDim(nm, float(lo), float(hi), i in int_dims)
            for i, (lo, hi, nm) in enumerate(
                zip(spec.bounds_lo, spec.bounds_hi, self.KNOB_NAMES))
        ]

    def render_proposal(self, name: str, x) -> Path:
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        out = self.proposal_dir / f"{name}_geom.txt"
        out.write_text(self._geom_text(x))
        return out

    # --- leaderboard + pending I/O: owned by core/leaderboard.py -----------
    def leaderboard_io(self) -> Leaderboard:
        lb = getattr(self, "_lb_cache", None)
        # Rebuild whenever the cached instance's paths no longer match (attr
        # patching is the standard test seam AND a runtime path): a
        # path-blind cache would keep serving a stale Leaderboard -- the
        # failure mode of
        # wiki/incidents/touched-leaderboard-headerless-history-loss.md at
        # the object-cache layer.
        archive = getattr(self, "leaderboard_archive", None)
        if lb is None or lb.path != self.leaderboard or lb.archive_path != archive:
            spec = _modes.SPECS[self.name]
            lb = Leaderboard(path=self.leaderboard, name=self.name,
                             knob_names=tuple(spec.knob_names),
                             knob_fmts=tuple(spec.knob_fmts),
                             metric_cols=tuple(spec.metric_cols),
                             archive_path=archive)
            self._lb_cache = lb
        return lb

    def load_history(self) -> list[Point]:
        return self.leaderboard_io().load()

    def append_history(self, p: Point, alpha: float):
        self.leaderboard_io().append(p, alpha)

    def pending_path(self) -> Path:
        return self.leaderboard_io().pending_path()

    def load_pending(self) -> list[tuple[str, list]]:
        return self.leaderboard_io().pending_load()

    def append_pending(self, name: str, x, alpha: float):
        self.leaderboard_io().pending_add(name, x, alpha)

    def remove_pending(self, name: str) -> bool:
        return self.leaderboard_io().pending_remove(name)

    @staticmethod
    def _resolve_metric(summary: dict, keys) -> tuple:
        """First candidate key that is present AND non-null wins.
        Returns (value, key), or (None, None) when none resolves."""
        for key in keys:
            if summary.get(key) is not None:
                return float(summary[key]), key
        return None, None

    def extract_metrics(self, summary: dict) -> tuple[float, float | None]:
        """Map summary.json onto (sob, second objective).

        UNRESOLVED and RESOLVED-TO-ZERO are deliberately different:
        unresolved returns None and cmd_evaluate refuses the row with rc=1
        (raising here made every child of a second-objective-less launch
        fail after full wall-clock);
        resolved to zero/negative from a REAL key is refused outright -- a
        fake zero row at good sob dominates the whole Pareto front at the
        next GP refit (7 poison rows landed that way 2026-07-10). A missing
        sob raises KeyError (rc=1); nothing to substitute there.
        """
        spec = _modes.SPECS[self.name]
        sob_col, second_col = spec.metric_cols[0], spec.metric_cols[1]
        sob, _sob_key = self._resolve_metric(summary, spec.metrics[sob_col])
        if sob is None:
            raise KeyError(
                f"{self.name}: summary.json has none of "
                f"{list(spec.metrics[sob_col])} for column {sob_col!r}")
        second, second_key = self._resolve_metric(
            summary, spec.metrics[second_col])
        if second is None:
            return sob, None
        if second <= 0:
            raise SystemExit(
                f"[{self.name}] second-objective column {second_col!r} "
                f"resolved to {second!r} from summary.json key "
                f"{second_key!r} -- refusing to append a row; a "
                f"zero/negative second metric would dominate the Pareto "
                f"front at the next GP refit")
        return sob, second


MODES: dict[str, JsonMode] = {}

# One JsonMode per spec carrying a geom template.
for _name, _spec in _modes.SPECS.items():
    if _spec.geom is not None:
        MODES[_name] = JsonMode(_name)


# --- BO ask: botorch subprocess (the single ask engine) --------------------

def botorch_ask(mode_name: str, q: int = 1, *, seed_idx: int = 0,
                picker: str = "qnehvi", pending: list | None = None,
                venv_py: Path | None = None,
                leaderboard: Path | None = None,
                timeout_s: int = 14400) -> list[list]:
    """Ask the botorch picker for q points; returns a list of x-lists.

    EVERY BO ask goes through here (CLI propose, graph propose_one,
    closed-loop picker): shells botorch_predict.py in the botorch venv,
    round-tripping picks through a temp JSON file. seed_idx -> --round-idx
    (Sobol/acq seed = 42 ^ idx), so a bumped seed_idx draws fresh points.
    `pending` x-lists ride --pending-json and are fantasized (X_pending).
    venv_py default resolves the AUTORESEARCH_BOTORCH_VENV env seam;
    leaderboard is a test/golden-only override.
    """
    import subprocess

    if venv_py is None:
        venv_py = (ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")
    venv_py = Path(venv_py)
    if not venv_py.exists():
        raise FileNotFoundError(
            f"[botorch_ask] picker venv python missing: {venv_py} "
            f"(install .venv or set AUTORESEARCH_BOTORCH_VENV)")

    predict = Path(__file__).resolve().parent / "botorch_predict.py"
    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as tf:
        out_path = Path(tf.name)
    pend_path = None
    try:
        cmd = [
            str(venv_py), str(predict),
            "--mode", mode_name, "--q", str(q),
            "--round-idx", str(seed_idx),
            "--picker", picker,
            "--emit-picks-json", str(out_path),
        ]
        if leaderboard is not None:
            cmd += ["--leaderboard", str(leaderboard)]
        if pending:
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False) as pf:
                json.dump([list(x) for x in pending], pf)
                pend_path = Path(pf.name)
            cmd += ["--pending-json", str(pend_path)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s)
        if r.returncode != 0:
            raise RuntimeError(
                f"[botorch_ask] botorch_predict rc={r.returncode}: "
                f"stderr={r.stderr.strip()[:400]}")
        raw = json.loads(out_path.read_text())
    finally:
        for p in (out_path, pend_path):
            if p is not None:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
    return [list(p) for p in raw]


# --- Subcommands ------------------------------------------------------------

def cmd_propose(args):
    mode = MODES[args.mode]
    names = args.config_names
    lock_path = _lock_path(mode.leaderboard.with_name(f"propose_{mode.name}"))
    with lock_path.open("w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        return _cmd_propose_locked(args, mode, names)


def _cmd_propose_locked(args, mode, names):
    history = mode.load_history()
    pending = mode.load_pending()

    existing = {p.cfg for p in history} | {n for n, _ in pending}
    dupes = [n for n in names if n in existing]
    if dupes:
        print(f"ERROR: name(s) already used (in leaderboard or pending): {dupes}",
              file=sys.stderr)
        return 1

    q = len(names)
    space = mode.build_space()
    print(f"[{mode.name}] botorch ask: {len(history)} history rows, "
          f"{len(pending)} pending (in-flight, fantasized as X_pending)")

    xs = botorch_ask(mode.name, q=q, pending=[px for _, px in pending])
    print(f"\nProposed batch of {q}:")

    for name, x in zip(names, xs):
        print(f"\n  '{name}':")
        for dim, val in zip(space, x):
            print(f"    {dim.name:24s} = {val}")
        geom = mode.render_proposal(name, x)
        # Auto-stage geom into the per-config work tree
        # (wiki/incidents/template-fcl-staleness.md).
        work_geom_dir = GRID_DATA_ROOT / name / "geom"
        work_geom_dir.mkdir(parents=True, exist_ok=True)
        work_geom = work_geom_dir / f"autoresearch_{name}_geom.txt"
        shutil.copy(geom, work_geom)
        print(f"    geom: {geom}  →  {work_geom}")
        mode.append_pending(name, x, args.alpha)

    print(f"\nPending file: {mode.pending_path()}")
    print(f"\nNext per config (run in parallel):")
    for name in names:
        print(f"  pipeline.py --config {name} submit mubeam")
    print(f"\nThen as each finishes:")
    print(f"  ./core/bo_driver.py --mode {mode.name} --alpha {args.alpha} "
          f"evaluate <name> <summary.json>")
    return 0


def cmd_evaluate(args):
    mode = MODES[args.mode]
    summary = json.loads(Path(args.summary).read_text())
    try:
        sob, calo = mode.extract_metrics(summary)
    except (KeyError, TypeError) as e:
        print(f"summary.json missing metric for {mode.name}: {e}; got {summary}")
        return 1
    # A missing second objective is NEVER coerced to a number. Every stage
    # in every mode chain produces a real second objective, so None means
    # its producing stage fail-softed; writing 0.0 would land a fake
    # zero-flash row that dominates the whole Pareto front at the next GP
    # refit (the 7-poison-row incident, 2026-07-10;
    # wiki/incidents/no-run1b-substitution-poisons-flash-modes.md).
    if sob is None or calo is None:
        print(f"[{mode.name}] summary.json metric is None ({summary}) — "
              f"refusing to append a row; recover the failed stage first.")
        return 1
    geom = mode.proposal_dir / f"{args.config_name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 1
    x = mode.x_for_evaluate(args.config_name, geom.read_text())
    if x is None:
        print(f"Failed to parse {mode.name} params from {geom}", file=sys.stderr)
        return 1
    p = Point(cfg=args.config_name, x=x, sob=float(sob), calo=float(calo))
    # Clear pending BEFORE appending: a crash in between leaves "missing
    # leaderboard row" (loud, re-runnable) rather than a silent phantom
    # pending row that trips propose_one's collision guard.
    removed = mode.remove_pending(args.config_name)
    mode.append_history(p, args.alpha)
    if getattr(args, "emit_json", None):
        write_json_atomic(Path(args.emit_json), {
            "config": p.cfg,
            "obj": p.obj(args.alpha),
            "sob": p.sob,
            "calo_or_flash": p.calo,
            "row_appended": True,
        })
    pend_tag = "  (cleared from pending)" if removed else ""
    print(f"[{mode.name}] recorded {p.cfg}: sob={p.sob:.3f} calo={p.calo:.3e} "
          f"obj={p.obj(args.alpha):+.3f}  →  {mode.leaderboard}{pend_tag}")
    return 0


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
    import xml.etree.ElementTree as ET

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


def _overlap_banner(mode_name):
    """PASS-line suffix naming which overlap policy actually ran (kept next
    to the policy flags so it cannot drift from the gate)."""
    spec = _modes.SPECS[mode_name]
    if not spec.checks_managed_overlap:
        return ""
    if spec.require_zero_overlaps:
        return " and zero surface-check overlaps"
    return " and no managed-volume overlap"
SURFACE_OVERLAP_MANAGED = re.compile(r"^StoppingTargetFoil_")


# Preflight verdict vocabulary — the ONE home of the rc mapping.
PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init",
                      3: "ambiguous"}


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp+rename (atomic within one filesystem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _cmd_preflight_impl(args):
    mode = MODES[args.mode]

    import harvest as _harvest
    import paths as _paths
    # Preflight runs first, so a missing backing surfaces here -- including
    # harvest's Run1BAna artifacts, which no earlier step touches.
    _paths.verify([_modes.SPECS[mode.name]],
                  extra=_harvest.REQUIRED_ARTIFACTS, make_dirs=False)

    name = args.config_name
    geom = mode.proposal_dir / f"{name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 2

    mode.preflight_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"preflight_{name}_", dir="/tmp"))
    geom_basename = f"autoresearch_{name}_geom.txt"
    shutil.copyfile(geom, workdir / geom_basename)

    # One G4 init covers both checks: surfacecheck.fcl enables
    # doSurfaceCheck AND exercises the plain G4-init path (pinned by
    # test_modes.test_all_modes_use_surfacecheck_preflight).
    overlay_basename = f"autoresearch_{name}_surfacecheck_geom.txt"
    (workdir / overlay_basename).write_text(
        SURFACE_CHECK_GEOM_OVERLAY.format(base_geom_basename=geom_basename))
    fcl_basename = "surfacecheck.fcl"
    # foils family: also dump the as-built geometry to GDML.
    gdml_lines = (PREFLIGHT_GDML_FCL_LINES
                  if _modes.SPECS[mode.name].dumps_gdml else "")
    (workdir / fcl_basename).write_text(
        SURFACE_CHECK_FCL.format(geom_basename=overlay_basename,
                                 gdml_lines=gdml_lines))

    log = mode.preflight_dir / f"{name}.log"
    print(f"[preflight/{mode.name}] cfg={name}  workdir={workdir}  log={log}")
    print(f"[preflight/{mode.name}] geom: {geom}  fcl: {fcl_basename}")

    # SPACK_USER_CACHE_PATH off NFS HOME onto /tmp: under concurrent
    # preflights the NFS flock on ~/.spack races and self-corrupts ->
    # [Errno 5] during spack load -> muse undefined -> rc=3 ambiguous. It
    # MUST be set INSIDE the bash command; export-at-launch did NOT
    # propagate. See wiki/incidents/foilsx04-all-preflight-ambiguous.md.
    spack_cache = f"/tmp/spack_cache_{os.environ.get('USER','x')}"
    # Per-mode Musing, resolved per-call (--mode is a CLI arg).
    musing = _modes.SPECS[mode.name].musing
    bash_cmd = (
        f"export SPACK_USER_CACHE_PATH={spack_cache} && "
        f"source {SETUPMU2E} >/dev/null && "
        f"source {musing}    >/dev/null && "
        f"export MU2E_SEARCH_PATH=\"{workdir}:$MU2E_SEARCH_PATH\" && "
        f"export FHICL_FILE_PATH=\"{workdir}:$FHICL_FILE_PATH\" && "
        f"cd {workdir} && "
        f"mu2e -c {fcl_basename} -n 1"
    )
    # Transient env-source flakes ([Errno 5]) leave `mu2e` unsourced -> exit
    # nonzero with NO output -> misread as rc=3 "ambiguous" (burned 2/3
    # foilsY02 round-0 children). Retry ONLY when mu2e never started: a
    # genuine run always emits a Geant4/art banner, and a banner-bearing
    # result must NOT be retried. `>/dev/null` (not `2>&1`) lets the flake's
    # stderr reach the log; wiki/incidents/sourced-env-stderr-swallowed.md.
    def _retry_if_no_banner(p):
        combined = (p.stdout or "") + (p.stderr or "")
        started = any(s in combined for s in
                      ("Geant4", "%MSG", "Art has", "Begin processing",
                       "G4Exception"))
        return p.returncode != 0 and not started

    proc = run_sourced_bash(
        bash_cmd, timeout=PREFLIGHT_TIMEOUT_S,
        should_retry=_retry_if_no_banner,
        label=f"preflight/{mode.name}", log=sys.stdout,
    )
    out = (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or "")
    rc = proc.returncode
    timed_out = proc.timed_out

    log.write_text(out)

    past_init = (
        "BeginRun" in out
        or "Event::beginEvent" in out
        or "EndOfEventAction" in out
        or "Begin processing the 1st record" in out  # art entered event loop
        or "GenParticle" in out                       # produce() ran, asked for input
    )

    print(f"[preflight/{mode.name}] return code: {rc}  timed_out={timed_out}")

    # Fatal aborts FAIL unconditionally, before past_init or surface-check
    # logic can mask them (see G4_FATAL_RX).
    fatal = G4_FATAL_RX.search(out)
    if fatal:
        snippet = out[max(0, fatal.start() - 300): fatal.end() + 400]
        print(f"[preflight/{mode.name}] FAIL  fatal G4/art abort:\n{snippet}")
        return 1

    # Env-divergence canary: a geom requesting per-foil holeRadii without
    # the patched StoppingTargetMaker's announcement means an unpatched
    # GeometryService silently built the wrong geometry --
    # wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
    if "stoppingTarget.holeRadii" in Path(geom).read_text() \
            and "holeRadii vector active" not in out:
        print(f"[preflight/{mode.name}] FAIL  geom requests "
              f"stoppingTarget.holeRadii but the env never printed "
              f"'holeRadii vector active' — unpatched StoppingTargetMaker "
              f"(scalar fallback). Check modes.py musing / grid tarball.")
        return 1

    # As-built assertion: G4-constructed foil stack (GDML) vs the geom file,
    # per foil. Catches value-level divergence the canary can't. HARD gate:
    # a run whose built geometry differs from x must never reach the grid.
    if _modes.SPECS[mode.name].verifies_foil_gdml:
        gdml_path = workdir / PREFLIGHT_GDML_NAME
        if not gdml_path.exists():
            print(f"[preflight/{mode.name}] FAIL  GDML dump "
                  f"{PREFLIGHT_GDML_NAME} not produced — cannot verify "
                  f"as-built geometry (writeGDML missing from env?)")
            return 1
        mismatches = verify_stopping_target_gdml(
            gdml_path, Path(geom).read_text())
        if mismatches:
            print(f"[preflight/{mode.name}] FAIL  as-built geometry differs "
                  f"from geom file ({len(mismatches)} mismatches):")
            for line in mismatches[:10]:
                print(f"    {line}")
            return 1
        radii_m = re.search(
            r"vector<double>\s+stoppingTarget\.radii\s*=\s*\{([^}]*)\}",
            Path(geom).read_text())
        n_foils = len(radii_m.group(1).split(",")) if radii_m else 0
        print(f"[preflight/{mode.name}] geometry assertion: {n_foils} foils "
              f"verified against as-built GDML (rIn/rOut/thickness)")
        # Preserve the verified GDML (the /tmp workdir is tmpwatch-cleaned).
        keep_dir = GRID_DATA_ROOT / name / "geom"
        keep_dir.mkdir(parents=True, exist_ok=True)
        keep_path = keep_dir / f"asbuilt_{name}.gdml"
        shutil.copyfile(gdml_path, keep_path)

    # Surface-check emits advisory GeomVol1002 warnings on every baseline
    # overlap (~117 in stock geometry), so the geom_fail regex is only
    # consulted when construction actually aborted (past_init=False).
    if _modes.SPECS[mode.name].checks_managed_overlap:
        all_hits = SURFACE_OVERLAP_RX.findall(out)
        unique_all = sorted(set(all_hits))
        managed_hits = [v for v in all_hits if SURFACE_OVERLAP_MANAGED.match(v)]
        unique_managed = sorted(set(managed_hits))
        baseline_count = len(all_hits) - len(managed_hits)
        print(f"[preflight/{mode.name}] surface-check "
              f"total_hits={len(all_hits)} unique_volumes={len(unique_all)} "
              f"baseline={baseline_count} managed={len(managed_hits)}")
        def _dump_context(vols):
            for v in vols[:1]:
                m = re.search(rf"Overlap is detected for volume\s+{re.escape(v)}.*", out)
                if m:
                    ctx = out[max(0, m.start() - 100): m.end() + 400]
                    print(f"[preflight/{mode.name}] context:\n{ctx}")

        # Strict policy first, so the reported reason is the real one. The
        # name-based managed/baseline split falsely assumes "not named like
        # a BO volume" => "independent of BO knobs": IPAsupport_* sits at a
        # z derived from targetEnd (MECOStyleProtonAbsorberMaker.cc:124-129);
        # foilsflashRUN1BAP01 introduced 3 such overlaps and still PASSED.
        # Modes whose Musing can reach zero opt into failing on ANY overlap.
        if _modes.SPECS[mode.name].require_zero_overlaps and all_hits:
            print(f"[preflight/{mode.name}] FAIL  zero-overlap policy: "
                  f"{len(all_hits)} overlap(s) in {len(unique_all)} volume(s):")
            for v in unique_all:
                print(f"    {v}{'  [managed]' if SURFACE_OVERLAP_MANAGED.match(v) else ''}")
            _dump_context(unique_managed or unique_all)
            return 1
        if managed_hits:
            print(f"[preflight/{mode.name}] FAIL  managed-volume overlap detected:")
            for v in unique_managed:
                print(f"    {v}")
            _dump_context(unique_managed)
            return 1
        if baseline_count:
            print(f"[preflight/{mode.name}] (info) {baseline_count} known "
                  f"stock-geometry overlaps ({len(unique_all)} unique volumes); "
                  f"ignored — not managed by BO knobs.")

    if not past_init:
        geom_fail = G4_GEOM_FAIL_RX.search(out)
        if geom_fail:
            snippet = out[max(0, geom_fail.start() - 200): geom_fail.end() + 600]
            print(f"[preflight/{mode.name}] FAIL  Geant4 geometry error:\n{snippet}")
            return 1

    if timed_out or rc == 0 or past_init:
        print(f"[preflight/{mode.name}] PASS  init=True; "
              f"no geom-fail signature"
              f"{_overlap_banner(mode.name)}.")
        return 0

    print(f"[preflight/{mode.name}] AMBIGUOUS  rc={rc}, no geom-fail signature. See {log}")
    print(f"[preflight/{mode.name}] Last 40 lines of log:\n" + "\n".join(out.splitlines()[-40:]))
    return 3


def cmd_preflight(args):
    rc = _cmd_preflight_impl(args)
    if getattr(args, "emit_json", None):
        mode = MODES[args.mode]
        verdict = PREFLIGHT_VERDICTS.get(rc, "ambiguous")
        write_json_atomic(Path(args.emit_json), {
            "verdict": verdict,
            "rc": rc,
            # Coarse cause class; the log carries the detailed FAIL lines.
            "reasons": [f"preflight classifier verdict: {verdict} (rc={rc})"],
            "log_path": str(mode.preflight_dir / f"{args.config_name}.log"),
            "config": args.config_name,
        })
    return rc


def cmd_pending_prune(args):
    mode = MODES[args.mode]
    removed = mode.leaderboard_io().pending_prune(
        older_than_h=args.older_than_hours)
    if removed:
        print(f"[{mode.name}] pruned {len(removed)} stale pending row(s): "
              + ", ".join(removed))
    else:
        print(f"[{mode.name}] nothing stale "
              f"(threshold {args.older_than_hours:.0f}h)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(MODES.keys()), required=True,
                    help="Search-space mode")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                    help=f"Scalarization weight (default {DEFAULT_ALPHA})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prop = sub.add_parser("propose",
                            help="Propose q≥1 candidate(s) + render geom(s). "
                                 "Pass multiple names for batch BO (CL-mean by default).")
    p_prop.add_argument("config_names", nargs="+",
                        help="One or more proposal names, e.g. `helical003 helical004 helical005`")
    p_prop.set_defaults(func=cmd_propose)

    p_eval = sub.add_parser("evaluate", help="Record completed run in leaderboard")
    p_eval.add_argument("config_name")
    p_eval.add_argument("summary", help="path to harvest/summary.json")
    p_eval.add_argument("--emit-json", dest="emit_json", default=None,
                        help="Write the typed result JSON to this path "
                             "(graph seam; written only after the row lands)")
    p_eval.set_defaults(func=cmd_evaluate)

    p_pre = sub.add_parser("preflight", help="Run mu2e -n 1 locally to test G4 init feasibility")
    p_pre.add_argument("config_name", help="Proposal name (must exist in proposal dir)")
    p_pre.add_argument("--emit-json", dest="emit_json", default=None,
                       help="Write the typed verdict JSON to this path "
                            "(graph seam; tmp+rename atomic)")
    p_pre.set_defaults(func=cmd_preflight)

    p_prune = sub.add_parser(
        "pending-prune",
        help="Delete pending rows older than a threshold (never automatic; "
             "this is the command the stale-row warning points at)")
    p_prune.add_argument("--older-than-hours", type=float, default=48.0)
    p_prune.set_defaults(func=cmd_pending_prune)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
