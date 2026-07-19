#!/usr/bin/env python3
"""Bayesian Optimization driver for Mu2e geometry searches.

Modes (select with --mode; bounds live in modes.SPECS, the registry of record):

  foils         5D/6D extras-only stopping-target envelope (absolute rIn)
  foilsf        v3 foils: hole radius as FRACTION of rOut (rIn = f*rOut)
  foilsflash    foilsf geometry vs elebeam-flash tracker edep objective
  foilsg        12D grouped 49-foil stack (4 z-groups x (rOut, hT, f))
  prodtarget    ~11D Stickman production-target profile search (mu_per_POT)
  prodtarget6d  6D simplification of prodtarget (no lug knobs, N pinned)

Subcommands:
  propose      : seed GP, propose next candidate, render geom override file
  evaluate     : after pipeline run, parse summary.json + append to leaderboard
  preflight    : run mu2e -n 1 locally on a proposal to catch G4 init failures

Architecture: BOMode is an ABC; each concrete mode is an adapter. MODES =
{name: instance} is the registry argparse selects from, keyed 1:1 with
modes.SPECS (ADR-0002). Adding a mode = subclass BOMode + add to MODES +
modes.SPECS + graph/state.py Literal (the lockstep is pinned by test_modes).
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# ModeSpec registry (ADR-0002): preflight policy flags replace the six
# hand-listed mode tuples that bred the preflight-mode-tuple-omission
# incident class. Stdlib-only import.
import modes as _modes  # noqa: E402


def _lock_path(target: Path) -> Path:
    """Flock anchor for `target`: <target's dir>/locks/<target's name>.lock.

    All runtime lock files live in a dedicated locks/ folder next to the
    thing they guard (relative to the target's parent, NOT a global constant,
    so tests that point a mode's TSVs at a tmp dir keep their lock isolation).
    Lock files are created if absent and intentionally NEVER deleted —
    deleting one while a process holds it would let the next opener lock a
    fresh inode at the same path, silently splitting the mutual exclusion.
    """
    lock_dir = target.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / (target.name + ".lock")


@contextmanager
def _flock_ex(target: Path):
    """Exclusive-lock target's locks/-dir anchor for the duration of the block.

    Used by leaderboard/pending TSV writers when multiple closed-loop child
    processes may append concurrently.
    """
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@contextmanager
def _flock_sh(target: Path):
    """Shared-lock target's locks/-dir anchor for the duration of the block.

    Paired with _flock_ex on the same path: writers (append_history) hold EX
    and block readers; readers (load_history) hold SH and block only writers,
    not each other. Closes the torn-row race where a reader could observe a
    partially-written leaderboard line mid-append.
    """
    lock_path = _lock_path(target)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")

sys.path.insert(0, str(ROOT / "graph"))
from config import PREFLIGHT_TIMEOUT_S, SETUPMU2E  # noqa: E402
from sourced_bash import run_sourced_bash  # noqa: E402

DEFAULT_ALPHA = 1.0e5  # mmackenz calo range 4e-8..2.5e-5; alpha=1e5 makes
                       # 1e-5 calo cost 1 unit of S/sqrt(B). Override per study.


@dataclass
class Point:
    """Generic BO point: x layout depends on mode."""
    cfg: str
    x: list      # mode-specific list of param values
    sob: float
    calo: float
    extras: dict | None = None  # mode-specific side metrics (logged not optimized)

    def obj(self, alpha: float) -> float:
        return self.sob - alpha * self.calo




def to_py_scalars(x) -> list:
    """Coerce numpy scalars (np.int64/np.float64) to native Python types for
    JSON/msgpack. Shared by append_pending and graph/pipeline_io.propose_one —
    see wiki/incidents/langgraph-checkpoint-numpy-int64.md."""
    return [v.item() if hasattr(v, "item") else v for v in x]


class SpaceDim(NamedTuple):
    """One search-space dimension. Plain data (skopt kernel retired
    2026-07-18) — the picker consumes bounds from modes.SPECS directly;
    this exists for the KNOB_NAMES↔bounds lockstep check and for printing."""
    name: str
    low: float
    high: float
    is_int: bool


# ============================================================================
# BOMode: the seam. One concrete adapter per mode below (see MODES).
# ============================================================================

class BOMode(ABC):
    """A BO mode = search space + render + prior loader + leaderboard format.

    Each subclass owns its pinned constants and its 6 mode-specific methods
    (load_priors, build_space, _geom_text, parse_geom, format_row,
    load_history_row). Shared concerns (history I/O, pending TSV,
    proposal file write) are concrete on this base class.
    """
    name: str
    leaderboard: Path
    proposal_dir: Path
    preflight_dir: Path

    # --- abstract: each concrete mode implements ---
    @abstractmethod
    def load_priors(self) -> list[Point]: ...

    @abstractmethod
    def _geom_text(self, x) -> str: ...

    @abstractmethod
    def parse_geom(self, text: str): ...

    # Leaderboard row shape shared by every sob/calo-schema mode: knob columns
    # = KNOB_NAMES, per-position precision = KNOB_FMTS, second-objective column
    # = CALO_COL. These are registry-reading properties now (modes.SPECS is
    # the single source — ADR-0002 extension); subclasses that change the
    # knob names (FoilsFracMode: rIn->f) or the objective column
    # (FoilsFlashMode: flash_edep) get that from their own spec entry, no
    # class-attr override needed. The ProdTarget family overrides both
    # methods (different metric columns).
    @property
    def KNOB_NAMES(self) -> tuple:
        return _modes.SPECS[self.name].knob_names

    @property
    def KNOB_FMTS(self) -> tuple:
        return _modes.SPECS[self.name].knob_fmts

    @property
    def CALO_COL(self) -> str:
        # Foils-family second-objective column = metric_cols[1].
        return _modes.SPECS[self.name].metric_cols[1]

    def format_row(self, p: Point, alpha: float) -> tuple[str, str]:
        cols = _modes.SPECS[self.name].metric_cols
        header = ("config\t" + "\t".join(self.KNOB_NAMES)
                  + "\t" + "\t".join(cols) + "\n")
        knobs = "\t".join(fmt.format(v) for fmt, v in zip(self.KNOB_FMTS, p.x))
        line = (f"{p.cfg}\t{knobs}"
                f"\t{p.sob:.5f}\t{p.calo:.5e}\t{alpha:.3f}\t{p.obj(alpha):.5f}\n")
        return header, line

    def load_history_row(self, row: dict) -> Point:
        return Point(cfg=row["config"],
                     x=[float(row[c]) for c in self.KNOB_NAMES],
                     sob=float(row["sob"]), calo=float(row[self.CALO_COL]))

    # Search space: SpaceDim rows from the ModeSpec registry box
    # (modes.SPECS[name].bounds_lo/hi/int_dims) paired with the per-mode
    # KNOB_NAMES tuple (also registry-derived now). KNOB_NAMES must line up
    # 1:1 with the registry bounds — a mismatch is a loud error, never a
    # silently-truncated space.
    def build_space(self) -> list[SpaceDim]:
        spec = _modes.SPECS[self.name]
        if len(self.KNOB_NAMES) != len(spec.bounds_lo):
            raise ValueError(
                f"{self.name}: KNOB_NAMES ({len(self.KNOB_NAMES)}) != registry "
                f"bounds ({len(spec.bounds_lo)})")
        int_dims = set(spec.int_dims or ())
        return [
            SpaceDim(nm, float(lo), float(hi), i in int_dims)
            for i, (lo, hi, nm) in enumerate(
                zip(spec.bounds_lo, spec.bounds_hi, self.KNOB_NAMES))
        ]

    # Constraint hook: override to reject infeasible regions of search space.
    # propose() calls this on every ask() output and tells the GP a penalty
    # for unbuildable picks before re-asking. Default = no constraint.
    def is_buildable(self, x) -> bool:
        return True

    # Summary-extraction hook: map a per-config summary.json into the (sob, calo)
    # pair Point.obj() consumes. Default reads the 4-stage harvest schema
    # (`s_over_sqrt_b`, `calo_per_pot`). Override in modes whose pipeline writes
    # a different summary schema (e.g. ProdTargetMode -> `mu_per_POT`).
    def extract_metrics(self, summary: dict) -> tuple[float, float]:
        return summary["s_over_sqrt_b"], summary["calo_per_pot"]

    # Optional side metrics (logged via format_row, not part of obj). Default
    # returns None — modes opt in (e.g. ProdTargetMode -> edep_per_POT_MeV).
    # x is the BO x_point (geometry knobs), supplied so modes can compute
    # derived quantities that need both per-plate harvest output and the
    # geom that produced it (e.g. peak specific dose = max_i Edep_i/mass_i).
    def extract_extras(self, summary: dict, x=None) -> dict | None:
        return None

    # --- concrete: shared ---
    def render_proposal(self, name: str, x) -> Path:
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        out = self.proposal_dir / f"{name}_geom.txt"
        out.write_text(self._geom_text(x))
        return out

    def load_history(self) -> list[Point]:
        if not self.leaderboard.exists():
            return []
        out = []
        with _flock_sh(self.leaderboard), self.leaderboard.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    out.append(self.load_history_row(row))
                except (KeyError, ValueError):
                    continue
        return out

    def append_history(self, p: Point, alpha: float):
        with _flock_ex(self.leaderboard):
            new_file = not self.leaderboard.exists()
            header, line = self.format_row(p, alpha)
            with self.leaderboard.open("a") as f:
                if new_file:
                    f.write(header)
                f.write(line)

    # --- batch BO pending-state (see wiki/concepts/batch-bo.md) ---
    def pending_path(self) -> Path:
        return self.leaderboard.parent / f"pending_bo_{self.name}.tsv"

    def load_pending(self) -> list[tuple[str, list]]:
        pp = self.pending_path()
        if not pp.exists():
            return []
        out = []
        with _flock_sh(pp), pp.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    out.append((row["config"], json.loads(row["x"])))
                except (KeyError, ValueError, json.JSONDecodeError):
                    continue
        return out

    def append_pending(self, name: str, x, alpha: float):
        pp = self.pending_path()
        with _flock_ex(pp):
            new = not pp.exists()
            with pp.open("a") as f:
                if new:
                    f.write("config\tx\talpha\tsubmitted_at\n")
                x_py = to_py_scalars(x)
                f.write(f"{name}\t{json.dumps(x_py)}\t{alpha:.3f}\t{int(time.time())}\n")

    def remove_pending(self, name: str) -> bool:
        pp = self.pending_path()
        # Read-modify-write under lock: without LOCK_EX two concurrent removals
        # can race and one's truncate overwrites the other's deletion.
        with _flock_ex(pp):
            if not pp.exists():
                return False
            rows = pp.read_text().splitlines()
            if len(rows) < 2:
                return False
            header, body = rows[0], rows[1:]
            kept = [r for r in body if not r.startswith(name + "\t")]
            if len(kept) == len(body):
                return False
            pp.write_text("\n".join([header] + kept) + ("\n" if kept else ""))
            return True


# ============================================================================
# FoilsMode: 5D extras-only stopping-target foil-stack search
# ============================================================================

class FoilsMode(BOMode):
    """BO over the extras around the pinned 37-foil base — 6D, per-side decoupled.

    n_up and n_down are PINNED at 6 (both champions foilsX07R01_03 and
    foilsX08R04_08 railed there in the 5D era). The 6 free knobs are
    (rOut, halfThickness, rIn) × (up, dn) — upstream extras carry their own
    triple, downstream their own.

    Geom vectors always have BASE_N_FOILS + 2*6 = 49 entries: 6 upstream
    extras, 37 pinned base, 6 downstream extras. Base 37 keep
    rOut=75, halfThickness=0.0528, holeRadius=21.5.

    Patched StoppingTargetMaker.cc reads the per-foil holeRadii vector;
    legacy binaries fall back to scalar holeRadius (still emitted at
    BASE_HOLE_RADIUS_MM so the base 37 build correctly under either lib).

    v1 (5D coupled) leaderboard rows are loaded as 6D priors via the
    n_up=n_down=6 subset projection (*_up = *_dn = scalar).

    No helical plug (tsda.helical.build = false, hasTSdA = false).
    """
    name = "foils"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_foils_v2.tsv"
    leaderboard_v1 = ROOT / "leaderboards" / "leaderboard_bo_foils_v1.tsv"
    proposal_dir = ROOT / "bo_work" / "proposals" / "foils"
    preflight_dir = ROOT / "bo_work" / "preflight" / "foils"

    # Base 37-foil DOE-2017 spec.
    BASE_N_FOILS = 37
    BASE_ROUT_MM = 75.0
    BASE_HALFTHICK_MM = 0.0528
    # Deployed base central hole = Edmonds DOE-review-2017 (21.5 mm). Env-gated
    # ONLY for one-off geometry experiments (e.g. the no-hole flash A/B that tests
    # Edmonds' ~30% central-hole effect); default unchanged so normal BO is unaffected.
    # See wiki/external/edmonds-target-hole-docdb10898.md.
    BASE_HOLE_RADIUS_MM = float(os.environ.get("AUTORESEARCH_BASE_HOLE_RADIUS_MM", "21.5"))

    # v2: integer envelope knobs pinned at the saturated v1 upper bound. Env-gated
    # (default 6) so a one-off can drop the extras and emit a pure 37-foil base.
    FIXED_N_UP = int(os.environ.get("AUTORESEARCH_N_UP", "6"))
    FIXED_N_DOWN = int(os.environ.get("AUTORESEARCH_N_DOWN", "6"))

    # A v1 row is only a valid v2 prior when its global holeRadius matches v2's
    # FIXED base hole. v1 _geom_text emitted `holeRadius = extra_rIn` GLOBALLY
    # (base 37 + extras) whenever extras were present, whereas v2 pins the base
    # 37 at BASE_HOLE_RADIUS_MM and only the extras get rIn. So unless
    # extra_rIn == base hole, the prior's (sob,calo) was measured with a
    # different base geometry than the projected v2 x-point builds -- and the
    # base 37 dominate the 49-foil stack, so that mismatch makes the y
    # meaningless for v2 (base stopping-area sensitivity ~0.83%/mm near 21.5).
    # 1.5 mm tol keeps the base-area mismatch under ~1.3%.
    # See wiki/projects/bo-foils.md (v1->v2 prior base-hole mismatch).
    PRIOR_BASE_HOLE_TOL_MM = 1.5

    def load_priors(self):
        """Project the SUBSET of v1 rows that round-trip into v2 geometry.

        A v1 row qualifies only if n_up==n_down==6 AND its extra_rIn is within
        PRIOR_BASE_HOLE_TOL_MM of BASE_HOLE_RADIUS_MM. For those rows the full
        v1 geometry (symmetric extras, base+extras all at hole≈21.5) is
        identical to the v2 geometry at x=[rOut,rOut,hT,hT,rIn,rIn], so the
        (sob,calo) is valid. Rows with a different extra_rIn are DROPPED --
        their y reflects a base hole v2 cannot reproduce (most v1 rows; see
        wiki/projects/bo-foils.md). v2's own leaderboard history is the primary
        warm start; these priors are supplementary.
        """
        if not self.leaderboard_v1.exists():
            return []
        out = []
        with self.leaderboard_v1.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    if int(row["n_up"]) != self.FIXED_N_UP:
                        continue
                    if int(row["n_down"]) != self.FIXED_N_DOWN:
                        continue
                    rOut = float(row["extra_rOut"])
                    hT = float(row["extra_halfThickness"])
                    rIn = float(row["extra_rIn"])
                    if abs(rIn - self.BASE_HOLE_RADIUS_MM) > self.PRIOR_BASE_HOLE_TOL_MM:
                        continue  # base-hole mismatch -> y invalid for v2
                    out.append(Point(
                        cfg=row["config"],
                        x=[rOut, rOut, hT, hT, rIn, rIn],
                        sob=float(row["sob"]),
                        calo=float(row["calo"]),
                    ))
                except (KeyError, ValueError):
                    continue
        return out

    def is_buildable(self, x) -> bool:
        rOut_up, rOut_dn, _, _, rIn_up, rIn_dn = x
        if rIn_up >= rOut_up:
            return False
        if rIn_dn >= rOut_dn:
            return False
        return True

    def _geom_text(self, x) -> str:
        rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn = x
        n_up = self.FIXED_N_UP
        n_down = self.FIXED_N_DOWN
        radii = ([rOut_up] * n_up
                 + [self.BASE_ROUT_MM] * self.BASE_N_FOILS
                 + [rOut_dn] * n_down)
        halfth = ([hT_up] * n_up
                  + [self.BASE_HALFTHICK_MM] * self.BASE_N_FOILS
                  + [hT_dn] * n_down)
        hole_radii = ([rIn_up] * n_up
                      + [self.BASE_HOLE_RADIUS_MM] * self.BASE_N_FOILS
                      + [rIn_dn] * n_down)
        radii_csv = ", ".join(f"{r:.4f}" for r in radii)
        halfth_csv = ", ".join(f"{h:.6f}" for h in halfth)
        hole_radii_csv = ", ".join(f"{h:.4f}" for h in hole_radii)

        hole_lines = (
            # POISON-PILL scalar: an unpatched StoppingTargetMaker ignores
            # the holeRadii vector and reads this scalar — emitting the old
            # back-compat 21.5 made that fallback silent (all 297 v3 rows
            # built with hole=21.5, f knobs inert). 1e6 forces a loud G4Tubs
            # crash in any scalar-fallback env. See
            # wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
            f'double stoppingTarget.holeRadius = 1.0e6;\n'
            f'vector<double> stoppingTarget.holeRadii      = {{ {hole_radii_csv} }};\n'
        )

        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a.txt"\n'
            '\n// === bo_driver (foils mode v2, 6D) proposal ===\n'
            f'// 37 base foils (DOE-2017, rOut=75, hT=0.0528, holeRadius=21.5)\n'
            f'// + {n_up} up at (rOut={rOut_up:.2f}, hT={hT_up:.4f}, rIn={rIn_up:.2f})\n'
            f'// + {n_down} dn at (rOut={rOut_dn:.2f}, hT={hT_dn:.4f}, rIn={rIn_dn:.2f})\n'
            '// holeRadii vector decouples extras-rIn from base-rIn (patched lib).\n'
            'bool hasTSdA = false;\n'
            'bool tsda.helical.build = false;\n'
            f'vector<double> stoppingTarget.radii          = {{ {radii_csv} }};\n'
            f'vector<double> stoppingTarget.halfThicknesses = {{ {halfth_csv} }};\n'
            + hole_lines
            + '\n// Degrader parked at 120° (mmackenz hardware detent)\n'
              'bool degrader.build = false;\n'
              'double degrader.rotation = 120.0;\n'
              'string ts.coll5.material1Name = "COL5Poly";\n'
              '\n// TT_MidInner→DS2Vacuum fix (manually patched, mirrors v111)\n'
              'bool tracker.inDS2Vacuum = true;\n'
              'double ds2.halfLength = 3825;\n'
              'bool ds.hasServicePipes = false;\n'
              '\n// Overlap-suppression (foil-support off + rail shrink)\n'
              'bool stoppingTarget.foilTarget_supportStructure = false;\n'
              'double ds.lengthRail2 = 0.1;\n'
              'double ds.lengthRail3 = 0.1;\n'
        )

    _RADII_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.radii\s*=\s*\{([^}]*)\}")
    _HALFTH_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.halfThicknesses\s*=\s*\{([^}]*)\}")
    _HOLE_VEC_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.holeRadii\s*=\s*\{([^}]*)\}")
    _HOLE_RX = re.compile(
        r"stoppingTarget\.holeRadius\s*=\s*([\d.eE+-]+)")

    def parse_geom(self, text: str):
        """Parse a v2 (6D, n_up=n_down=6) geom file. Vectors must have
        BASE_N_FOILS + 12 = 49 entries; the first/last entries on each side
        are the *_up/*_dn extras for (rOut, halfThickness, rIn)."""
        n_up = self.FIXED_N_UP
        n_down = self.FIXED_N_DOWN
        expected_len = self.BASE_N_FOILS + n_up + n_down

        m = self._RADII_RX.search(text)
        if not m:
            return None
        radii = [float(v) for v in m.group(1).split(",")]
        if len(radii) != expected_len:
            raise ValueError(
                f"FoilsMode v2 expects {expected_len}-entry radii vector "
                f"(n_up={n_up}+base={self.BASE_N_FOILS}+n_down={n_down}); "
                f"got {len(radii)} entries"
            )

        mh = self._HALFTH_RX.search(text)
        if not mh:
            return None
        halfth = [float(v) for v in mh.group(1).split(",")]
        if len(halfth) != expected_len:
            raise ValueError(
                f"FoilsMode v2 expects {expected_len}-entry halfThicknesses; "
                f"got {len(halfth)}"
            )

        mvec = self._HOLE_VEC_RX.search(text)
        if mvec:
            hole_radii = [float(v) for v in mvec.group(1).split(",")]
            if len(hole_radii) != expected_len:
                raise ValueError(
                    f"FoilsMode v2 expects {expected_len}-entry holeRadii; "
                    f"got {len(hole_radii)}"
                )
            rIn_up = hole_radii[0]
            rIn_dn = hole_radii[-1]
        else:
            # Pre-holeRadii era: scalar holeRadius applied to all foils; the
            # extras' rIn was implicitly the scalar.
            mr = self._HOLE_RX.search(text)
            scalar = float(mr.group(1)) if mr else self.BASE_HOLE_RADIUS_MM
            rIn_up = scalar
            rIn_dn = scalar

        return [radii[0], radii[-1], halfth[0], halfth[-1], rIn_up, rIn_dn]

    # Row format/parse inherited from the BOMode generic; KNOB_FMTS comes
    # from modes.SPECS["foils"].knob_fmts.


class FoilsFracMode(FoilsMode):
    """v3: identical 6D foils geometry to FoilsMode, but each side's hole radius
    is a FRACTION of that side's outer radius (rIn = f * rOut) rather than an
    absolute mm value. Two payoffs:

      * the downstream hole can exceed the old 50 mm cap (the rIn_dn=50 pegging
        pointed past it) with NO infeasible rIn>=rOut region — f in [0, 0.95]
        means rIn < rOut always, so is_buildable is trivially True;
      * LOSSLESS reparam of v2 — every v2 row maps EXACTLY via f = rIn/rOut
        (same physical foil), so all v2 evals + the 1 v1 prior reuse with no
        base-hole filter. See wiki/projects/bo-foils.md.

    Point.x = [rOut_up, rOut_dn, hT_up, hT_dn, f_up, f_dn]. The geometry layer
    (geom emission, parse, preflight, harvest) is unchanged and still works in
    absolute rIn; only the BO search coordinate differs, so _geom_text /
    parse_geom just wrap the v2 methods with the f<->rIn transform.
    """
    name = "foilsf"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_foils_v3.tsv"

    # hole = FRACTION of rOut (rIn = f*rOut); registry caps f at 0.95 so
    # rIn < rOut always. Same geometry as FoilsMode, so only the last two
    # knob NAMES change (rIn -> f) — that's modes.SPECS["foilsf"].knob_names;
    # bounds also come from modes.SPECS["foilsf"].

    def is_buildable(self, x) -> bool:
        return True  # f in [0, 0.95] => rIn = f*rOut < rOut, always buildable

    @staticmethod
    def _frac_to_abs(x):
        rOut_up, rOut_dn, hT_up, hT_dn, f_up, f_dn = x
        return [rOut_up, rOut_dn, hT_up, hT_dn, f_up * rOut_up, f_dn * rOut_dn]

    @staticmethod
    def _abs_to_frac(xa):
        rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn = xa
        return [rOut_up, rOut_dn, hT_up, hT_dn, rIn_up / rOut_up, rIn_dn / rOut_dn]

    def _geom_text(self, x) -> str:
        return FoilsMode._geom_text(self, self._frac_to_abs(x))

    def parse_geom(self, text: str):
        xa = FoilsMode.parse_geom(self, text)  # [..., rIn_up, rIn_dn] absolute
        return None if xa is None else self._abs_to_frac(xa)

    def load_priors(self):
        """v3-only: empty prior list. Live picker trains only on the v3
        leaderboard (via load_history). The v1 prior + 54 v2 evals are
        intentionally NOT loaded because v2's rIn<=50 regime regresses the GP
        away from v3's high-f exploration (see
        [[gp-cloud-rendering]] foils v2+v3 bias; v3-only cloud envelopes the
        gold stars, v2+v3 does not). Trade-off: GP becomes under-identified
        (length_scale -> upper-bound saturation observed on 67-row v3-only
        fit). Accepted 2026-06-05 per operator direction."""
        return []



class FoilsFlashMode(FoilsFracMode):
    """Same 6D foils geometry + S/√B signal as FoilsFracMode, but the SECOND
    objective is the tracker StrawGasStep ionizing edep from the ELECTRON beam
    EARLY-FLASH peak (DS on), not the Run1B calo-stop background. The foils sit
    in the DS beam path, so they scatter/absorb flash electrons → flash tracker
    occupancy is responsive to the foil geometry. Geometry layer (build_space,
    _geom_text, parse_geom, is_buildable, load_priors) inherited unchanged; only
    the leaderboard + the 2nd-objective plumbing differ. See
    wiki/projects/bo-foilsflash.md. The flash edep is carried in the generic
    Point.calo slot (reused)."""
    name = "foilsflash"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_foilsflash.tsv"
    proposal_dir = ROOT / "bo_work" / "proposals" / "foilsflash"
    preflight_dir = ROOT / "bo_work" / "preflight" / "foilsflash"


    # Search space = FoilsFracMode's (inherited KNOB_NAMES) but with a widened
    # halfThickness floor of 0.002 mm (=4 µm full, vs the 0.01 mm=20 µm the
    # optimizer rail-pinned against) for the thickness-probe experiment
    # (2026-07-09). That floor lives in modes.SPECS["foilsflash"].bounds_lo,
    # which the picker reads too — see wiki/projects/bo-foilsflash.md
    # "SEARCH-BOX FLOOR" and tests/test_modes.py (bounds lockstep enforced).

    def load_priors(self):
        return []

    # 2nd objective = TOTAL early-flash tracker edep PER POT (MeV/POT), the
    # geometry-sensitive lever (harvest writes flash_edep_per_pot). The old
    # per-event MEAN (flash_edep_per_event) divides out the flash-event count and
    # is BLIND to the geometry — it produced the spurious "foils are not a flash
    # lever" null (see wiki/projects/bo-foilsflash.md). Fall back to per_event then
    # calo_per_pot so --dry-run/mock (which only write calo_per_pot) still work.
    def extract_metrics(self, summary: dict) -> tuple[float, float]:
        sob = summary["s_over_sqrt_b"]
        edep = summary.get("flash_edep_per_pot")
        if edep is None:
            edep = summary.get("flash_edep_per_event")
        if edep is None or edep <= 0:
            # Flash-less summary = the elebeam stage failed fail-soft. NEVER
            # coerce to 0: a fake zero-flash row at good sob dominates the
            # entire Pareto front at the next GP refit (7 poison rows landed
            # this way 2026-07-10 via the direct-CLI evaluate path; the graph
            # path was guarded in node_evaluate, this path was not).
            raise SystemExit(
                f"[foilsflash] flash edep missing/zero in summary for "
                f"{summary.get('config', '?')} — refusing to append a row; "
                f"recover the elebeam stage first (see wiki "
                f"elebeamcat-tape-migration-elebeam-wipeout)")
        return sob, edep

    # Only the objective column name differs from FoilsFracMode: the flash
    # edep-per-POT lands under "flash_edep" (Point.calo carries it) — that's
    # modes.SPECS["foilsflash"].metric_cols[1]. Row shape, knob names, and
    # parse all inherit unchanged.


class FoilsGroupMode(BOMode):
    """49 free foils in 4 z-grouped bands (sizes 12-13-12-12); 12-D BO.

    Replaces the deployed 37-foil baseline rather than augmenting it: the
    *whole* stack is free. Each contiguous z-group shares one
    (rOut, halfThickness, hole_fraction) triple — so 4 groups × 3 knobs = 12
    Real dims. Hole is parameterised as a fraction f ∈ [0, 0.95] of that
    group's rOut (mirrors FoilsFracMode), giving rIn < rOut always and
    is_buildable trivially True.

    Z-layout (Option 1): uniform spacing across the same z-extent as the
    deployed baseline. Deployed: 37 foils × deltaZ=22.222222 → extent ≈ 800 mm
    (36 gaps). New: 49 foils with deltaZ = 800/48 ≈ 16.667 mm. Stack center
    pinned by keeping z0InMu2e = 5871.

    No carryover priors (load_priors=[]); first round is Sobol-init.
    """
    name = "foilsg"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_foilsg.tsv"
    proposal_dir = ROOT / "bo_work" / "proposals" / "foilsg"
    preflight_dir = ROOT / "bo_work" / "preflight" / "foilsg"

    N_FOILS = 49
    GROUP_SIZES = (12, 13, 12, 12)  # sum == 49; center-loaded
    Z0_MM = 5871.0
    # Match deployed z-extent: 36 gaps × 22.222222 mm ≈ 800 mm spread over 49
    # foils → 48 gaps of 800/48 ≈ 16.6667 mm.
    DEPLOYED_DELTA_Z = 22.222222
    DEPLOYED_GAPS = 36
    BASE_EXTENT_MM = DEPLOYED_DELTA_Z * DEPLOYED_GAPS
    DELTA_Z_MM = BASE_EXTENT_MM / (N_FOILS - 1)

    # (rOut, hT, f) per z-group; hole f in [0, 0.95] of rOut. 12 dims (names +
    # fmts + bounds) all live in modes.SPECS["foilsg"] (registry stores
    # (50,0.01,0)*4 / (250,1,0.95)*4 for bounds).

    def load_priors(self):
        return []  # fresh 12D space — no upstream rows to project

    def is_buildable(self, x) -> bool:
        return True  # f<1 ⇒ rIn = f*rOut < rOut, always buildable

    @staticmethod
    def _unpack_groups(x):
        """Yield (group_index, n_foils_in_group, rOut, hT, f) for each group."""
        for g, n in enumerate(FoilsGroupMode.GROUP_SIZES):
            rOut, hT, f = x[3 * g], x[3 * g + 1], x[3 * g + 2]
            yield g, n, rOut, hT, f

    def _geom_text(self, x) -> str:
        radii, halfth, hole_radii = [], [], []
        per_group_lines = []
        for g, n, rOut, hT, f in self._unpack_groups(x):
            radii.extend([rOut] * n)
            halfth.extend([hT] * n)
            hole_radii.extend([f * rOut] * n)
            per_group_lines.append(
                f'// group {g} (n={n}): rOut={rOut:.2f}, hT={hT:.4f}, '
                f'f={f:.3f} → rIn={f*rOut:.2f}'
            )
        radii_csv = ", ".join(f"{r:.4f}" for r in radii)
        halfth_csv = ", ".join(f"{h:.6f}" for h in halfth)
        hole_csv = ", ".join(f"{h:.4f}" for h in hole_radii)
        group_block = "\n".join(per_group_lines)

        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a.txt"\n'
            '\n// === bo_driver (foilsg mode, 12D 4-group) proposal ===\n'
            f'// {self.N_FOILS} free foils in groups {self.GROUP_SIZES} (replaces deployed 37 baseline)\n'
            f'// uniform z-spacing across deployed extent ({self.BASE_EXTENT_MM:.2f} mm)\n'
            f'// deltaZ = {self.DELTA_Z_MM:.6f} mm; z0InMu2e pinned at {self.Z0_MM:.1f}\n'
            + group_block + '\n'
            'bool hasTSdA = false;\n'
            'bool tsda.helical.build = false;\n'
            f'double stoppingTarget.z0InMu2e = {self.Z0_MM:.4f};\n'
            f'double stoppingTarget.deltaZ   = {self.DELTA_Z_MM:.6f};\n'
            f'vector<double> stoppingTarget.radii          = {{ {radii_csv} }};\n'
            f'vector<double> stoppingTarget.halfThicknesses = {{ {halfth_csv} }};\n'
            # holeRadii vector requires the patched StoppingTargetMaker.cc.
            # POISON-PILL scalar: an unpatched binary falls back to the
            # scalar and must crash loudly (G4Tubs rMin>rMax on every foil)
            # instead of silently building uniform-hole geometry. The
            # "sensible scalar (mean)" emitted before 2026-06-12 is exactly
            # how 62 leaderboard rows got built with the wrong geometry. See
            # wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
            f'double stoppingTarget.holeRadius = 1.0e6;\n'
            f'vector<double> stoppingTarget.holeRadii      = {{ {hole_csv} }};\n'
            '\n// Degrader parked at 120° (mmackenz hardware detent)\n'
            'bool degrader.build = false;\n'
            'double degrader.rotation = 120.0;\n'
            'string ts.coll5.material1Name = "COL5Poly";\n'
            '\n// TT_MidInner→DS2Vacuum fix (mirrors v111)\n'
            'bool tracker.inDS2Vacuum = true;\n'
            'double ds2.halfLength = 3825;\n'
            'bool ds.hasServicePipes = false;\n'
            '\n// Overlap-suppression (mirrors FoilsMode)\n'
            'bool stoppingTarget.foilTarget_supportStructure = false;\n'
            'double ds.lengthRail2 = 0.1;\n'
            'double ds.lengthRail3 = 0.1;\n'
        )

    _RADII_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.radii\s*=\s*\{([^}]*)\}")
    _HALFTH_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.halfThicknesses\s*=\s*\{([^}]*)\}")
    _HOLE_VEC_RX = re.compile(
        r"vector<double>\s+stoppingTarget\.holeRadii\s*=\s*\{([^}]*)\}")

    def parse_geom(self, text: str):
        """Recover the 12-D x by reading the first foil of each group.

        Each group is a contiguous run of identical (rOut, hT, hole) entries,
        so the first index of each group suffices: 0, 12, 25, 37.
        """
        m = self._RADII_RX.search(text)
        mh = self._HALFTH_RX.search(text)
        mv = self._HOLE_VEC_RX.search(text)
        if not (m and mh and mv):
            return None
        radii = [float(v) for v in m.group(1).split(",")]
        halfth = [float(v) for v in mh.group(1).split(",")]
        hole = [float(v) for v in mv.group(1).split(",")]
        if not (len(radii) == len(halfth) == len(hole) == self.N_FOILS):
            raise ValueError(
                f"FoilsGroupMode expects {self.N_FOILS}-entry vectors; "
                f"got radii={len(radii)}, hT={len(halfth)}, holeRadii={len(hole)}"
            )
        offsets, acc = [], 0
        for n in self.GROUP_SIZES:
            offsets.append(acc)
            acc += n
        x = []
        for off in offsets:
            rOut = radii[off]
            hT = halfth[off]
            f = hole[off] / rOut if rOut > 0 else 0.0
            x.extend([rOut, hT, f])
        return x



class ProdTargetMode(BOMode):
    """BO over Stickman PS production target (MDC2025aq), profile mode (v0).

    11D search (K=3 Lagrange quadratic profiles + N int):
      r_ctrl  = (r0, r1, r2)         per-plate rOut profile      [mm]
      t_ctrl  = (t0, t1, t2)         per-plate thickness profile [mm]
      l_ctrl  = (l0, l1, l2)         per-plate lugThickness prof [mm]
      N       = numberOfPlates       int

    Profiles evaluated at u = i/(N-1) for i=0..N-1 (no extrapolation).
    Material fixed Inconel718 in v0. Hard constraints in is_buildable +
    forker:
      lPlate[i] >= tPlate[i] + 0.5      (silent overlap; PTM.cc:419-438)
      min(rOut) >= 3.0                  (beam clearance, sigma=1 mm)
      Stickman envelope: halfStickmanLength recomputed each config
        (= supportRingLength + 2*spacerHalfLength + sum(lPlate)/2)
      productionTargetMotherHalfLength bumped to halfStickman + MARGIN

    Objective: muons per POT at VD sid=8 (Coll5_Out, post-TS exit).
    Stored in Point.sob; Point.calo unused (alpha=0 → obj = mu_per_POT).

    See wiki/projects/bo-prodtarget.md for the full design rationale and
    wiki/concepts/production-target-stickman.md for the per-plate semantics.
    """
    name = "prodtarget"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_prodtarget_v0.tsv"
    proposal_dir = ROOT / "bo_work" / "proposals" / "prodtarget"
    preflight_dir = ROOT / "bo_work" / "preflight" / "prodtarget"


    # Stickman defaults (from ProductionTarget_Stickman_v1_0.txt).
    DEFAULT_N = 35
    DEFAULT_ROUT_MM = 3.15
    DEFAULT_PLATETHICK_MM = 5.0
    DEFAULT_LUGTHICK_MM = 6.0
    DEFAULT_MATERIAL = "Inconel718"

    # Envelope identity constants (also in production-target-stickman wiki).
    SUPPORT_RING_LEN_MM = 8.1
    SPACER_HALFLEN_MM = 1.5
    MOTHER_MARGIN_MM = 20.0  # mother >= halfStickman + margin (HALF units).
    MOTHER_OUTER_R_MM = 200.0  # base file default; not searched

    # Hard constraints.
    LUG_OVER_THICK_MARGIN_MM = 0.5   # plateLugThickness >= plateThickness + 0.5
    # Upper cap on (lug - plate) to keep the lug from protruding past the plate
    # core's z-face into the SpacerNegZ/PosZ annular region (lug rIn=1.525,
    # rOut=3.0 = spacer rIn=1.55, rOut=3.0 — overlap is guaranteed if the lug
    # overhangs the plate). pt001 baseline has diff=1.0mm; ptX04R00_00 (passing)
    # has max diff~1.5mm; ptX04R00_08 (failing, 150nm × 16 cases) has
    # max diff~2.4mm. Cap at 1.0mm to match pt001.
    # See wiki/incidents/prodtarget-spacer-supportring-overlap.md.
    LUG_OVER_THICK_MAX_MM = 1.0      # plateLugThickness <= plateThickness + 1.0
    MIN_ROUT_MM = 3.0                # >= 3 sigma of beamSpotSigma=1 mm

    # Inconel718 density, g/cm^3 (Mu2e Offline material def + standard tables).
    # Used to convert per-plate Edep [MeV] -> specific dose [Gy/POT].
    RHO_INCONEL718_G_PER_CM3 = 8.19

    def extract_metrics(self, summary: dict) -> tuple[float, float]:
        # bo-prodtarget harvest writes `mu_per_POT`. Point.calo stays 0
        # (DEFAULT_ALPHA=1e5 would otherwise drown sob); edep_per_POT_MeV
        # is logged via Point.extras / format_row.
        return summary["mu_per_POT"], 0.0

    def extract_extras(self, summary: dict, x=None) -> dict | None:
        import numpy as np
        edep_stack = summary.get("edep_per_POT_MeV")
        edep_arr = summary.get("edep_per_plate_MeV")
        total_pot = summary.get("total_pot")
        out: dict = {}
        if edep_stack is not None:
            out["edep_per_POT_MeV"] = float(edep_stack)
        # Compute peak specific dose [Gy/POT] = max_i (Edep_i / mass_i).
        # Needs per-plate edep array + x (so we know rOut[i], tPlate[i] per
        # plate; ProductionTargetMaker reads these length-N vectors). MeV->J
        # = 1.602176634e-13; g->kg = 1e-3. Length units mm -> cm via /10.
        # Guarding on _expand's N makes this method work unchanged for
        # ProdTarget6DMode (whose _expand returns FIXED_N) — no override.
        if x is not None and edep_arr and total_pot:
            rOut, tPlate, _, N = self._expand(x)
            if len(edep_arr) == N:
                # Volume_i = pi * rOut^2 * tPlate (mm^3 -> cm^3 by /1000).
                vol_cm3 = np.pi * (rOut ** 2) * tPlate / 1000.0
                mass_g = vol_cm3 * self.RHO_INCONEL718_G_PER_CM3
                # edep_arr is per-plate Edep_total [MeV] summed across the job.
                # Per-plate per-POT dose [Gy/POT] = (Edep_i / total_pot [MeV/POT])
                #   * 1.602e-13 J/MeV / (mass_i [g] * 1e-3 kg/g).
                edep_per_pot = np.asarray(edep_arr, dtype=float) / float(total_pot)
                dose_per_pot_Gy = (edep_per_pot * 1.602176634e-13
                                   / (mass_g * 1e-3))
                out["peak_dose_Gy_per_POT"] = float(dose_per_pot_Gy.max())
                out["peak_dose_plate_idx"] = int(np.argmax(dose_per_pot_Gy))
        return out or None

    @staticmethod
    def _parse_pt_extras(row: dict) -> dict:
        """Shared leaderboard extras parse for prodtarget/prodtarget6d
        load_history_row (was duplicated verbatim in both)."""
        extras: dict = {}
        edep = row.get("edep_per_POT_MeV")
        if edep not in (None, "", "nan"):
            extras["edep_per_POT_MeV"] = float(edep)
        peak = row.get("peak_dose_Gy_per_POT")
        if peak not in (None, "", "nan"):
            extras["peak_dose_Gy_per_POT"] = float(peak)
        idx = row.get("peak_plate_idx")
        if idx not in (None, "", "nan"):
            try:
                extras["peak_dose_plate_idx"] = int(idx)
            except (ValueError, TypeError):
                pass
        return extras

    def load_priors(self):
        # No external priors in v0; baseline lands via the first evaluation.
        return []

    # r{0,1,2}=rOut / t{0,1,2}=thickness / l{0,1,2}=lugThickness quadratic
    # profile control knots [mm] + N=numberOfPlates (Integer). Names, fmts,
    # and bounds (roughly ±30-60% around defaults) all live in
    # modes.SPECS["prodtarget"]; the lug range (4,12) pairs with _expand's
    # per-plate lPlate clip that pre-projects silent spacer overlaps away
    # (wiki/incidents/prodtarget-spacer-supportring-overlap).

    @staticmethod
    def _profile(c, N):
        """Lagrange quadratic through (c0,c1,c2) at u=0,0.5,1; eval at N points
        in u in [0,1]. No extrapolation; first/last sample hit c0/c2 exactly."""
        import numpy as np
        u = np.linspace(0.0, 1.0, N)
        c0, c1, c2 = c
        return c0*(1-2*u)*(1-u) + c1*4*u*(1-u) + c2*u*(2*u-1)

    def _expand(self, x):
        """Return (rOut[N], tPlate[N], lPlate[N], N) after profile expansion
        and per-plate constraint projection."""
        import numpy as np
        r_ctrl = (x[0], x[1], x[2])
        t_ctrl = (x[3], x[4], x[5])
        l_ctrl = (x[6], x[7], x[8])
        N = int(x[9])
        rOut = np.asarray(self._profile(r_ctrl, N))
        tPlate = np.asarray(self._profile(t_ctrl, N))
        lPlate = np.asarray(self._profile(l_ctrl, N))
        # Per-plate silent-overlap guard: lug must be >= thickness + floor (so the
        # lug actually contains the plate-core junction) but <= thickness + max
        # (so the lug doesn't overhang the plate into the spacer's annular region).
        lPlate = np.clip(lPlate,
                         tPlate + self.LUG_OVER_THICK_MARGIN_MM,
                         tPlate + self.LUG_OVER_THICK_MAX_MM)
        return rOut, tPlate, lPlate, N

    def is_buildable(self, x) -> bool:
        rOut, _, _, _ = self._expand(x)
        if float(rOut.min()) < self.MIN_ROUT_MM:
            return False
        return True

    def _geom_text(self, x) -> str:
        rOut, tPlate, lPlate, N = self._expand(x)
        # Envelope identity (from ProductionTarget.cc:230 + constructTargetPS.cc:1659).
        halfStickman = (self.SUPPORT_RING_LEN_MM
                        + 2.0 * self.SPACER_HALFLEN_MM
                        + float(lPlate.sum()) / 2.0)
        motherHalf = halfStickman + self.MOTHER_MARGIN_MM
        material_vec = [self.DEFAULT_MATERIAL] * N
        rOut_csv = ", ".join(f"{v:.4f}" for v in rOut)
        tPlate_csv = ", ".join(f"{v:.4f}" for v in tPlate)
        lPlate_csv = ", ".join(f"{v:.4f}" for v in lPlate)
        mat_csv = ", ".join(f'"{m}"' for m in material_vec)
        # Fin angles vector is sized to nStickmanFins, not N — pass through default.
        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a_stickman.txt"\n'
            '\n// === bo_driver (prodtarget mode v0, 11D) proposal ===\n'
            f'// N={N} plates, profile-mode K=3 quadratic Lagrange (no extrapolation)\n'
            f'// rOut control:  ({x[0]:.3f}, {x[1]:.3f}, {x[2]:.3f}) mm\n'
            f'// thick control: ({x[3]:.3f}, {x[4]:.3f}, {x[5]:.3f}) mm\n'
            f'// lug control:   ({x[6]:.3f}, {x[7]:.3f}, {x[8]:.3f}) mm\n'
            f'// Material fixed = {self.DEFAULT_MATERIAL}\n'
            '// Per-plate constraint applied: '
            f'tPlate[i] + {self.LUG_OVER_THICK_MARGIN_MM} <= lPlate[i] <= '
            f'tPlate[i] + {self.LUG_OVER_THICK_MAX_MM} mm.\n'
            f'int targetPS_numberOfPlates = {N};\n'
            f'double targetPS_halfStickmanLength = {halfStickman:.4f};\n'
            f'double targetPS_productionTargetMotherHalfLength = {motherHalf:.4f};\n'
            f'double targetPS_productionTargetMotherOuterRadius = {self.MOTHER_OUTER_R_MM};\n'
            f'vector<string> targetPS_plateMaterial = {{ {mat_csv} }};\n'
            f'vector<double> targetPS_rOut = {{ {rOut_csv} }};\n'
            f'vector<double> targetPS_plateThickness = {{ {tPlate_csv} }};\n'
            f'vector<double> targetPS_plateLugThickness = {{ {lPlate_csv} }};\n'
        )

    _N_RX = re.compile(r"targetPS_numberOfPlates\s*=\s*(\d+)")
    _ROUT_RX = re.compile(r"vector<double>\s+targetPS_rOut\s*=\s*\{([^}]*)\}")
    _TPLATE_RX = re.compile(
        r"vector<double>\s+targetPS_plateThickness\s*=\s*\{([^}]*)\}")
    _LPLATE_RX = re.compile(
        r"vector<double>\s+targetPS_plateLugThickness\s*=\s*\{([^}]*)\}")

    def parse_geom(self, text: str):
        """Recover (r_ctrl, t_ctrl, l_ctrl, N) approximately from a rendered
        geom file. Control points are read at indices 0, N//2, N-1 of the
        expanded vectors — exact roundtrip for v0 quadratic profiles."""
        mN = self._N_RX.search(text)
        mR = self._ROUT_RX.search(text)
        mT = self._TPLATE_RX.search(text)
        mL = self._LPLATE_RX.search(text)
        if not (mN and mR and mT and mL):
            raise ValueError("prodtarget parse_geom: missing required vectors")
        N = int(mN.group(1))
        def _vec(m):
            return [float(s) for s in m.group(1).split(",")]
        rOut = _vec(mR); tPlate = _vec(mT); lPlate = _vec(mL)
        if not (len(rOut) == len(tPlate) == len(lPlate) == N):
            raise ValueError(
                f"prodtarget parse_geom: vector length mismatch "
                f"(N={N}, |rOut|={len(rOut)}, |t|={len(tPlate)}, |l|={len(lPlate)})")
        mid = N // 2
        return [rOut[0], rOut[mid], rOut[-1],
                tPlate[0], tPlate[mid], tPlate[-1],
                lPlate[0], lPlate[mid], lPlate[-1],
                N]

    # Row machinery shared by the ProdTarget family (mu_per_POT/edep/peak-dose
    # metric columns, extras side-channel). Subclasses supply only the knob
    # cells: ProdTarget6D drops l0-l2 and the integer N.
    def _knob_cells(self, x) -> str:
        r0, r1, r2, t0, t1, t2, l0, l1, l2, N = x
        return (f"{r0:.4f}\t{r1:.4f}\t{r2:.4f}"
                f"\t{t0:.4f}\t{t1:.4f}\t{t2:.4f}"
                f"\t{l0:.4f}\t{l1:.4f}\t{l2:.4f}"
                f"\t{int(N)}")

    def _knob_x(self, row: dict) -> list:
        return [float(row["r0"]), float(row["r1"]), float(row["r2"]),
                float(row["t0"]), float(row["t1"]), float(row["t2"]),
                float(row["l0"]), float(row["l1"]), float(row["l2"]),
                int(float(row["N"]))]

    def format_row(self, p: Point, alpha: float) -> tuple[str, str]:
        header = ("config\t" + "\t".join(self.KNOB_NAMES)
                  + "\t" + "\t".join(_modes.SPECS[self.name].metric_cols)
                  + "\n")
        ex = p.extras or {}
        edep = ex.get("edep_per_POT_MeV", float("nan"))
        peak = ex.get("peak_dose_Gy_per_POT", float("nan"))
        idx = ex.get("peak_dose_plate_idx", -1)
        line = (f"{p.cfg}\t{self._knob_cells(p.x)}"
                f"\t{p.sob:.6e}\t{edep:.6e}"
                f"\t{peak:.6e}\t{int(idx)}"
                f"\t{p.obj(alpha):.6e}\n")
        return header, line

    def load_history_row(self, row: dict) -> Point:
        extras = self._parse_pt_extras(row)
        return Point(cfg=row["config"], x=self._knob_x(row),
                     sob=float(row["mu_per_POT"]), calo=0.0,
                     extras=extras or None)



class ProdTarget6DMode(ProdTargetMode):
    """6D simplification of ProdTargetMode for faster BO convergence.

    Drops the 3 lug knobs (l0/l1/l2 are post-clipped to a 0.5mm window
    around tPlate anyway — see wiki/projects/bo-prodtarget.md "Lug dims
    are effectively redundant") and the integer N (pinned at Stickman
    default 35 to dodge the thick-plate-regime overlap class for stack
    ends — wiki/incidents/prodtarget-spacer-supportring-overlap.md).

    6D search:  (r0, r1, r2, t0, t1, t2)
    Fixed:      N = 35; lPlate[i] = tPlate[i] + LUG_MID_OFFSET_MM (0.75)
    """
    name = "prodtarget6d"
    leaderboard = ROOT / "leaderboards" / "leaderboard_bo_prodtarget6d_v0.tsv"
    proposal_dir = ROOT / "bo_work" / "proposals" / "prodtarget6d"
    preflight_dir = ROOT / "bo_work" / "preflight" / "prodtarget6d"

    # Mid-window: (LUG_OVER_THICK_MARGIN_MM + LUG_OVER_THICK_MAX_MM)/2 = 0.75
    LUG_MID_OFFSET_MM = 0.75
    FIXED_N = 35  # Stickman v1.0 default; well-tested at this plate count.

    # 6D rOut+thickness profile only (N fixed at 35, lug derived). Names,
    # fmts, and bounds in modes.SPECS["prodtarget6d"]; t upper was 7→8
    # (2026-06-15) after the end-plate lug clamp shipped.

    def _expand(self, x):
        import numpy as np
        r_ctrl = (x[0], x[1], x[2])
        t_ctrl = (x[3], x[4], x[5])
        N = int(self.FIXED_N)
        rOut = np.asarray(self._profile(r_ctrl, N))
        tPlate = np.asarray(self._profile(t_ctrl, N))
        lPlate = tPlate + self.LUG_MID_OFFSET_MM
        # 2026-06-15: clamp end-plate lug to zero overhang. Fourth mode
        # in prodtarget-spacer-supportring-overlap: upstream-lug
        # overhang into SpacerNegZ × Plate00 (and mirror at Plate_last
        # × SpacerPosZ) is real ~250-500 µm overlap — 4 OOM above the
        # stickmanMagicOffset precision artifact. Setting end-plate
        # lug = plate thickness removes the overhang without source patch.
        lPlate[0] = tPlate[0]
        lPlate[-1] = tPlate[-1]
        return rOut, tPlate, lPlate, N

    # extract_extras: inherited from ProdTargetMode — its guard uses
    # _expand()'s N, which is FIXED_N here, so the parent body is exact.

    def _geom_text(self, x) -> str:
        rOut, tPlate, lPlate, N = self._expand(x)
        halfStickman = (self.SUPPORT_RING_LEN_MM
                        + 2.0 * self.SPACER_HALFLEN_MM
                        + float(lPlate.sum()) / 2.0)
        motherHalf = halfStickman + self.MOTHER_MARGIN_MM
        material_vec = [self.DEFAULT_MATERIAL] * N
        rOut_csv = ", ".join(f"{v:.4f}" for v in rOut)
        tPlate_csv = ", ".join(f"{v:.4f}" for v in tPlate)
        lPlate_csv = ", ".join(f"{v:.4f}" for v in lPlate)
        mat_csv = ", ".join(f'"{m}"' for m in material_vec)
        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a_stickman.txt"\n'
            '\n// === bo_driver (prodtarget6d mode v0, 6D) proposal ===\n'
            f'// N={N} plates (FIXED), profile-mode K=3 quadratic Lagrange\n'
            f'// rOut control:  ({x[0]:.3f}, {x[1]:.3f}, {x[2]:.3f}) mm\n'
            f'// thick control: ({x[3]:.3f}, {x[4]:.3f}, {x[5]:.3f}) mm\n'
            f'// lug derived = tPlate + {self.LUG_MID_OFFSET_MM} mm (mid of [0.5, 1.0] cap window)\n'
            f'// Material fixed = {self.DEFAULT_MATERIAL}\n'
            f'int targetPS_numberOfPlates = {N};\n'
            f'double targetPS_halfStickmanLength = {halfStickman:.4f};\n'
            f'double targetPS_productionTargetMotherHalfLength = {motherHalf:.4f};\n'
            f'double targetPS_productionTargetMotherOuterRadius = {self.MOTHER_OUTER_R_MM};\n'
            f'vector<string> targetPS_plateMaterial = {{ {mat_csv} }};\n'
            f'vector<double> targetPS_rOut = {{ {rOut_csv} }};\n'
            f'vector<double> targetPS_plateThickness = {{ {tPlate_csv} }};\n'
            f'vector<double> targetPS_plateLugThickness = {{ {lPlate_csv} }};\n'
        )

    def parse_geom(self, text: str):
        mN = self._N_RX.search(text)
        mR = self._ROUT_RX.search(text)
        mT = self._TPLATE_RX.search(text)
        if not (mN and mR and mT):
            raise ValueError("prodtarget6d parse_geom: missing required vectors")
        N = int(mN.group(1))
        if N != self.FIXED_N:
            raise ValueError(f"prodtarget6d parse_geom: N={N} != FIXED_N={self.FIXED_N}")
        def _vec(m):
            return [float(s) for s in m.group(1).split(",")]
        rOut = _vec(mR); tPlate = _vec(mT)
        mid = N // 2
        return [rOut[0], rOut[mid], rOut[-1],
                tPlate[0], tPlate[mid], tPlate[-1]]

    def _knob_cells(self, x) -> str:
        r0, r1, r2, t0, t1, t2 = x
        return (f"{r0:.4f}\t{r1:.4f}\t{r2:.4f}"
                f"\t{t0:.4f}\t{t1:.4f}\t{t2:.4f}")

    def _knob_x(self, row: dict) -> list:
        return [float(row["r0"]), float(row["r1"]), float(row["r2"]),
                float(row["t0"]), float(row["t1"]), float(row["t2"])]



MODES: dict[str, BOMode] = {
    "foils":        FoilsMode(),
    "foilsf":       FoilsFracMode(),
    "foilsflash":   FoilsFlashMode(),
    "foilsg":       FoilsGroupMode(),
    "prodtarget":   ProdTargetMode(),
    "prodtarget6d": ProdTarget6DMode(),
}


# ============================================================================
# BO ask — botorch subprocess (the single ask engine since the skopt
# propose kernel retired 2026-07-18)
# ============================================================================

def botorch_ask(mode_name: str, q: int = 1, *, seed_idx: int = 0,
                picker: str = "qnehvi", pending: list | None = None,
                venv_py: Path | None = None,
                leaderboard: Path | None = None,
                timeout_s: int = 14400) -> list[list]:
    """Ask the botorch picker for q points; returns a list of x-lists.

    Shells into the botorch venv to run botorch_predict.py (this file's
    sibling) and round-trips picks through a temp JSON file. Every BO ask
    goes through here: CLI propose, graph propose_one, and the closed-loop
    picker (which passes its own picker/venv). The picker loads priors +
    leaderboard history itself.

    seed_idx maps to --round-idx (Sobol/acq seed = 42 ^ idx), so retries
    with a bumped seed_idx draw fresh points. `pending` x-lists ride via
    --pending-json: the acquisition fantasizes over them (X_pending), which
    replaces the retired skopt constant-liar suppression.

    venv_py: python interpreter to use; default resolves the
    AUTORESEARCH_BOTORCH_VENV env seam against the project root (same rule
    as graph/config.py BOTORCH_VENV_PY).
    leaderboard: test/golden-only override forwarded as --leaderboard.
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


# ============================================================================
# Subcommands
# ============================================================================

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
    n_unbuildable = sum(1 for x in xs if not mode.is_buildable(x))
    if n_unbuildable:
        print(f"WARN: batch contains {n_unbuildable} unbuildable pick(s) "
              f"(preflight will reject them)", file=sys.stderr)
    print(f"\nProposed batch of {q}:")

    for name, x in zip(names, xs):
        print(f"\n  '{name}':")
        for dim, val in zip(space, x):
            print(f"    {dim.name:24s} = {val}")
        geom = mode.render_proposal(name, x)
        # Auto-stage geom into the parametric pipeline's per-config work tree
        # (see wiki/incidents/template-fcl-staleness.md).
        work_geom_dir = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid") / name / "geom"
        work_geom_dir.mkdir(parents=True, exist_ok=True)
        work_geom = work_geom_dir / f"autoresearch_{name}_geom.txt"
        shutil.copy(geom, work_geom)
        print(f"    geom: {geom}  →  {work_geom}")
        mode.append_pending(name, x, args.alpha)

    print(f"\nPending file: {mode.pending_path()}")
    print(f"\nNext per config (run in parallel):")
    for name in names:
        print(f"  pipeline.py --config {name} submit mubeam   (and run1b_mubeam)")
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
    # qlnei picker stamps AUTORESEARCH_NO_RUN1B=1, which drops the
    # run1b_mubeam stage (saves ~40% wall-clock) and therefore intentionally
    # produces calo=None. Substitute 0.0 so the row still lands; obj()
    # becomes sob - alpha*0 = sob, matching qlnei's sob-only objective.
    # Without this, run_evaluate returns obj=None, graph records
    # `obj_unparseable`, and SqliteSaver crashes serializing the None-bearing
    # state (foilsf08R00 10/10 children, 2026-06-08). See wiki/incidents/
    # closed-loop-sqlite-checkpoint-transient-corruption.md.
    if calo is None and os.environ.get("AUTORESEARCH_NO_RUN1B") == "1":
        print(f"[{mode.name}] calo is None (AUTORESEARCH_NO_RUN1B=1); "
              f"substituting 0.0 for sob-only objective")
        calo = 0.0
    if sob is None or calo is None:
        print(f"summary.json metric is None for {mode.name}: {summary}")
        return 1
    geom = mode.proposal_dir / f"{args.config_name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 1
    x = mode.parse_geom(geom.read_text())
    if x is None:
        print(f"Failed to parse {mode.name} params from {geom}", file=sys.stderr)
        return 1
    extras = mode.extract_extras(summary, x=x)
    p = Point(cfg=args.config_name, x=x, sob=float(sob), calo=float(calo), extras=extras)
    # Clear pending BEFORE appending leaderboard so a crash between leaves
    # the failure mode "missing leaderboard row" (loud, re-runnable) instead
    # of "phantom pending row" (silent; trips propose_one collision guard
    # and renames the next iteration — see wiki graph-runner resume gotcha).
    removed = mode.remove_pending(args.config_name)
    mode.append_history(p, args.alpha)
    pend_tag = "  (cleared from pending)" if removed else ""
    print(f"[{mode.name}] recorded {p.cfg}: sob={p.sob:.3f} calo={p.calo:.3e} "
          f"obj={p.obj(args.alpha):+.3f}  →  {mode.leaderboard}{pend_tag}")
    return 0


G4_GEOM_FAIL_RX = re.compile(
    r"G4Exception.*?(GeomMgt000\d|GeomVol1002|GeomSolids00\d\d|placement|outside mother|overlap)",
    re.IGNORECASE | re.DOTALL,
)

# Fatal G4/art aborts that must FAIL preflight regardless of past_init.
# past_init exists to tolerate advisory GeomVol1002 surface-check warnings
# (~117 in stock geometry), but it also fires on pre-geometry strings like
# EventGenerator's "...@BeginRun" — so a geometry abort AFTER those strings
# was misclassified PASS for every foilsg child while the grid died on the
# identical error. See wiki/incidents/preflight-past-init-false-pass.md.
G4_FATAL_RX = re.compile(
    r"G4Exception\s*:\s*GeomSolids00\d\d"
    r"|\*\*\* Fatal Exception \*\*\*"
    r"|G4Exception.*?Aborting execution",
    re.IGNORECASE | re.DOTALL,
)

# Surface-check pass detects silent volume overlaps that wouldn't fail G4 init
# (e.g. TSdA disc vs helical plug as siblings of DS2Vacuum). See wiki:
# external/mu2e-overlap-check + incidents/tsda-disc-helical-sibling-overlap.
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

# Written into the preflight workdir when the mode requests a GDML
# geometry assertion (foils family). The dump reflects what G4 ACTUALLY
# built — catching value-level divergence (indexing, units, clipping)
# that the holeRadii canary can't see.
PREFLIGHT_GDML_NAME = "preflight_geom.gdml"
PREFLIGHT_GDML_FCL_LINES = (
    'physics.producers.g4run.debug.writeGDML : true\n'
    f'physics.producers.g4run.debug.GDMLFileName : "{PREFLIGHT_GDML_NAME}"\n'
)

# G4's GDML writer appends a pointer suffix to every name
# ("Foil_020x55d1..."). A greedy \d+ would swallow the leading 0 of "0x"
# and scramble indices (foil 02 → "20"); the non-greedy digits + anchored
# optional 0x-suffix parse is exact for both suffixed and bare names.
GDML_FOIL_TUBE_RX = re.compile(r"Foil_(\d+?)(?:0x[0-9a-fA-F]+)?$")


def verify_stopping_target_gdml(gdml_path, geom_text, tol_mm=1e-3):
    """Assert the G4-built stopping-target foils match the geom file.

    Parses the GDML with plain XML iterparse — NOT ROOT TGDMLParse, which
    segfaults on forward volume refs (see
    wiki/incidents/root-gdml-forward-volume-ref.md). Each foil is a
    uniquely named G4Tubs "Foil_NN" (constructStoppingTarget.cc:162), so
    the writer cannot dedupe them away.

    Returns a list of mismatch strings; empty list == verified.
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

# G4 CheckOverlaps emits lines like
#   "Overlap is detected for volume <X> ... with [its mother volume] <Y> ..."
# We only care about overlaps that involve volumes our BO knobs touch:
#   - StoppingTargetFoil_*  (foils family)
#   - ProductionTarget*     (prodtarget family: plates, lugs, spacers, supports)
# (TSdA/AbsorberPV/AbsorberS prefixes retired 2026-07-17 with the helical
# plug — every surviving mode pins hasTSdA=false.)
# Stock Mu2e geometry has ~117 baseline overlap lines (FoilSupportStructure_*
# with StoppingTargetMother; NorthRailDS3 / SouthRailDS3 with DS3Vacuum;
# VirtualDetector_EMC_0_Front with StoppingTargetMother). Whitelisting by
# volume name keeps those out of our failure signal.
SURFACE_OVERLAP_RX = re.compile(r"Overlap is detected for volume\s+(\S+)")
SURFACE_OVERLAP_MANAGED = re.compile(
    r"^(StoppingTargetFoil_"
    r"|ProductionTargetPlate|ProductionTargetLug|ProductionTargetSpacer|ProductionTargetSupport)")


# Preflight verdict vocabulary — the ONE home of the rc mapping (was
# duplicated as a decode dict in graph/pipeline_io.py).
PREFLIGHT_VERDICTS = {0: "pass", 1: "fail_managed", 2: "fail_init",
                      3: "ambiguous"}


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp+rename in the destination dir (readers never see
    a partial file; rename is atomic within one filesystem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _cmd_preflight_impl(args):
    mode = MODES[args.mode]
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
    # g4.doSurfaceCheck=true AND exercises the same init path a plain G4-init
    # preflight would. Every surviving mode sets preflight_fcl="surfacecheck"
    # (michael's lighter preflight.fcl retired with the mode, 2026-07-12;
    # pinned by test_modes.test_all_modes_use_surfacecheck_preflight).
    overlay_basename = f"autoresearch_{name}_surfacecheck_geom.txt"
    (workdir / overlay_basename).write_text(
        SURFACE_CHECK_GEOM_OVERLAY.format(base_geom_basename=geom_basename))
    fcl_basename = "surfacecheck.fcl"
    # foils family: also dump the as-built geometry to GDML so the
    # per-foil assertion below can verify it against the geom file.
    gdml_lines = (PREFLIGHT_GDML_FCL_LINES
                  if _modes.SPECS[mode.name].dumps_gdml else "")
    (workdir / fcl_basename).write_text(
        SURFACE_CHECK_FCL.format(geom_basename=overlay_basename,
                                 gdml_lines=gdml_lines))

    log = mode.preflight_dir / f"{name}.log"
    print(f"[preflight/{mode.name}] cfg={name}  workdir={workdir}  log={log}")
    print(f"[preflight/{mode.name}] geom: {geom}  fcl: {fcl_basename}")

    # SPACK_USER_CACHE_PATH moves spack's provider cache + flock off NFS HOME
    # onto local /tmp. Under concurrent preflights (q>1 closed-loop) the NFS
    # flock on ~/.spack/cache/providers/.fnal_art-index.json.lock races and
    # self-corrupts, surfacing as [Errno 5] during `spack load` inside
    # setupmu2e-art.sh -> muse undefined -> rc=3 ambiguous. Setting this
    # INSIDE the bash command (not just exporting at parent shell) is what
    # actually propagates to the child -- export-at-launch did NOT propagate
    # (foilsZ05, 2026-06-05). See wiki/incidents/foilsx04-all-preflight-ambiguous.md.
    spack_cache = f"/tmp/spack_cache_{os.environ.get('USER','x')}"
    # Per-mode Musing dispatch: prodtarget sources the patched MDC2025aq/p101
    # workdir; CE/calo modes source Run1Bak. Resolved per-call (not import-time)
    # because the BO driver is invoked with --mode as a CLI arg.
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
    # Transient cvmfs/spack env-source flakes (==> Error: [Errno 5]) leave
    # `mu2e` unsourced -> the subprocess exits nonzero having produced NO
    # output, which the rc-map below misreads as rc=3 "ambiguous" (a real but
    # rare G4 outcome). That false-ambiguous burned 2/3 foilsY02 round-0
    # children (2026-06-01). Use the shared retry helper, but retry ONLY when
    # mu2e never started -- a genuine run always emits a Geant4/art banner, so
    # its presence means the result is real (pass, geom-fail, or
    # true-ambiguous) and must NOT be retried. `>/dev/null` (not `2>&1`) in
    # bash_cmd lets the flake's stderr reach the captured log.
    # See wiki/incidents/sourced-env-stderr-swallowed.md.
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

    # Fatal aborts FAIL unconditionally — before past_init or surface-check
    # logic can mask them. past_init matches pre-geometry strings (e.g.
    # EventGenerator's "...@BeginRun"), so a geometry abort after those
    # strings used to be classified PASS while the grid died on the same
    # error. See wiki/incidents/preflight-past-init-false-pass.md.
    fatal = G4_FATAL_RX.search(out)
    if fatal:
        snippet = out[max(0, fatal.start() - 300): fatal.end() + 400]
        print(f"[preflight/{mode.name}] FAIL  fatal G4/art abort:\n{snippet}")
        return 1

    # Env-divergence canary: if the geom requests per-foil holeRadii, the
    # patched StoppingTargetMaker MUST have announced it. A silent scalar
    # fallback means the sourced env runs unpatched GeometryService — the
    # exact silent-wrong-geometry failure of
    # wiki/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md.
    if "stoppingTarget.holeRadii" in Path(geom).read_text() \
            and "holeRadii vector active" not in out:
        print(f"[preflight/{mode.name}] FAIL  geom requests "
              f"stoppingTarget.holeRadii but the env never printed "
              f"'holeRadii vector active' — unpatched StoppingTargetMaker "
              f"(scalar fallback). Check modes.py musing / grid tarball.")
        return 1

    # As-built geometry assertion: compare the G4-constructed foil stack
    # (GDML dump) against the geom file, per foil (rIn / rOut / thickness).
    # Catches value-level divergence the canary can't: indexing bugs, unit
    # errors, repeat-last mistakes, silent clipping. Hard gate — a foils
    # run whose built geometry differs from x must never reach the grid.
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
        # Preserve the verified as-built GDML alongside the config's grid
        # artifacts (the /tmp workdir is node-local and tmpwatch-cleaned).
        keep_dir = (Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
                    / name / "geom")
        keep_dir.mkdir(parents=True, exist_ok=True)
        keep_path = keep_dir / f"asbuilt_{name}.gdml"
        shutil.copyfile(gdml_path, keep_path)

    # prodtarget family: emission-only (no per-plate verifier yet).
    # The GDML is a parseable artifact for offline inspection / debugging
    # — surfaces silent geometry divergence that the rc/past_init/canary
    # path can't see. Preserved alongside grid artifacts.
    if _modes.SPECS[mode.name].preserves_gdml:
        gdml_path = workdir / PREFLIGHT_GDML_NAME
        if not gdml_path.exists():
            print(f"[preflight/{mode.name}] FAIL  GDML dump "
                  f"{PREFLIGHT_GDML_NAME} not produced — cannot preserve "
                  f"as-built geometry (writeGDML missing from env?)")
            return 1
        keep_dir = (Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
                    / name / "geom")
        keep_dir.mkdir(parents=True, exist_ok=True)
        keep_path = keep_dir / f"asbuilt_{name}.gdml"
        shutil.copyfile(gdml_path, keep_path)
        print(f"[preflight/{mode.name}] as-built GDML preserved at "
              f"{keep_path} ({gdml_path.stat().st_size} bytes)")

    # Helical preflight runs surface-check, which emits G4Exception(GeomVol1002)
    # WWWW warnings on every baseline overlap (~117 hits in stock geometry).
    # These are advisory, not init failures, so the geom_fail regex must only
    # be consulted when geometry construction actually aborted (past_init=False).
    if _modes.SPECS[mode.name].checks_managed_overlap:
        all_hits = SURFACE_OVERLAP_RX.findall(out)
        unique_all = sorted(set(all_hits))
        managed_hits = [v for v in all_hits if SURFACE_OVERLAP_MANAGED.match(v)]
        unique_managed = sorted(set(managed_hits))
        baseline_count = len(all_hits) - len(managed_hits)
        print(f"[preflight/{mode.name}] surface-check "
              f"total_hits={len(all_hits)} unique_volumes={len(unique_all)} "
              f"baseline={baseline_count} managed={len(managed_hits)}")
        if managed_hits:
            print(f"[preflight/{mode.name}] FAIL  managed-volume overlap detected:")
            for v in unique_managed:
                print(f"    {v}")
            for v in unique_managed[:1]:
                m = re.search(rf"Overlap is detected for volume\s+{re.escape(v)}.*", out)
                if m:
                    ctx = out[max(0, m.start() - 100): m.end() + 400]
                    print(f"[preflight/{mode.name}] context:\n{ctx}")
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
              f"{' and no managed-volume overlap' if _modes.SPECS[mode.name].checks_managed_overlap else ''}.")
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(MODES.keys()), default="foils",
                    help="Search-space mode (default: foils)")
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
    p_eval.set_defaults(func=cmd_evaluate)

    p_pre = sub.add_parser("preflight", help="Run mu2e -n 1 locally to test G4 init feasibility")
    p_pre.add_argument("config_name", help="Proposal name (must exist in proposal dir)")
    p_pre.add_argument("--emit-json", dest="emit_json", default=None,
                       help="Write the typed verdict JSON to this path "
                            "(graph seam; tmp+rename atomic)")
    p_pre.set_defaults(func=cmd_preflight)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
