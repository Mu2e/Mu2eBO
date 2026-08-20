"""ModeSpec registry: every per-mode FACT in one pure-data table (ADR-0002).

Frozen dataclasses, every field passed explicitly (a missing fact is an
import error, never a default) -- the fix for the foilsflash-tarball,
preflight-tuple and foilsg-tarball incident class. Stdlib-only. Two env
seams apply ON TOP of the spec: AUTORESEARCH_NO_RUN1B and
AUTORESEARCH_ELEBEAM_NJOBS. Completeness pinned by tests/test_modes.py.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:
    from core.geom_template import GeomTemplate


@dataclass(frozen=True)
class ModeSpec:
    """The pure-data half of a Mode (CONTEXT.md: 'ModeSpec')."""
    name: str
    musing: str
    grid_tarball: str
    grid_stages: Tuple[str, ...]
    stage_target_overrides: Dict[str, int]
    presubmit_after: Dict[str, Tuple[str, ...]]
    stage_tuning: Dict[str, Dict[str, object]]
    bounds_lo: Optional[Tuple[float, ...]]
    bounds_hi: Optional[Tuple[float, ...]]
    int_dims: Optional[Tuple[int, ...]]
    dumps_gdml: bool
    verifies_foil_gdml: bool
    checks_managed_overlap: bool
    # True => preflight FAILS on ANY surface-check overlap: the managed/
    # baseline whitelist keys on volume NAME, so foilsflashRUN1BAP01 PASSED
    # with 3 never-before-seen IPAsupport overlaps (their position derives
    # from our knobs). Only modes whose Musing can reach zero may set it.
    require_zero_overlaps: bool

    # Leaderboard schema (single source). The leading `config` column is a
    # writer detail (golden parity (a) pins it).
    knob_names: Tuple[str, ...]
    knob_fmts: Tuple[str, ...]
    metric_cols: Tuple[str, ...]

    # Measured ABSOLUTE sigma per GP output axis, fed as train_Yvar: left a
    # free MLL hyperparameter, the foilsflash fit lands at sigma(sob)=0.0507
    # vs replicate-measured 0.0051 (12x), erasing the champion -- see
    # wiki/incidents/gp-free-noise-erases-champion. None is passed
    # EXPLICITLY by ProdTarget, not defaulted.
    obs_noise: Optional[Tuple[float, ...]]

    geom: Optional[GeomTemplate]
    metrics: Optional[Dict[str, Tuple[str, ...]]]
    leaderboard_rel: Optional[str]

    def __post_init__(self):
        if self.bounds_lo is not None and not (
                len(self.knob_names) == len(self.knob_fmts)
                == len(self.bounds_lo)):
            raise ValueError(
                f"{self.name}: knob_names ({len(self.knob_names)}) / "
                f"knob_fmts ({len(self.knob_fmts)}) / bounds "
                f"({len(self.bounds_lo)}) lockstep broken")
        if self.obs_noise is not None and not (
                len(self.obs_noise) == 2
                and all(v > 0 for v in self.obs_noise)):
            raise ValueError(
                f"{self.name}: obs_noise must be 2 positive sigmas "
                f"(one per GP output axis), got {self.obs_noise!r}")


SPECS: Dict[str, ModeSpec] = {}

# THE IMPORT MIRRORS OUR OWN PACKAGE-QUALIFICATION (__package__): this
# module loads as `core.modes` from the repo root AND as bare `modes` in the
# grid subprocess (tests/test_modes.py TestSubprocessImport). A hardcoded
# qualified import fails outright on the bare path; a hardcoded bare import
# would, on the qualified path, load mode_json.py a SECOND time under a
# different sys.modules key, needing a second non-identical ModeSpec class.
if __package__:
    from core.mode_json import load_mode_dir  # noqa: E402 - SPECS must exist first
else:
    from mode_json import load_mode_dir  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
SPECS.update(load_mode_dir(MODES_DIR, SPECS))

# THE fallback for every import-time AUTORESEARCH_MODE reader; single-sourced
# because per-module literals drift. Pinned by
# tests/test_modes.py::test_one_default_mode_literal_in_the_tree.
DEFAULT_MODE = "foilspf"
assert DEFAULT_MODE in SPECS, (
    f"DEFAULT_MODE {DEFAULT_MODE!r} is not a live mode; mode_specs/ has "
    f"{sorted(SPECS)}")


def _unknown_mode_message(source: str, value) -> str:
    """One message shape for every unknown-mode failure; names the bad value
    AND the live modes (they differ by a character or two)."""
    return (f"[mode] FATAL unknown {source} {value!r}. Known modes: "
            f"{', '.join(sorted(SPECS))}. (Mode specs live in mode_specs/; "
            f"retired ones are under mode_specs/archive/.)")


def resolve_env_mode() -> str:
    """The process's mode from AUTORESEARCH_MODE, VALIDATED.

    Unset falls through to DEFAULT_MODE. SET BUT UNKNOWN is FATAL, never a
    silent fallback: coerced, a typo or stale export launches a full
    campaign at rc=0 against the wrong bounds, geometry and LEADERBOARD --
    the last being the most expensive silent failure here, since the
    leaderboard is what the GP refits on. Every module-level reader of
    AUTORESEARCH_MODE calls THIS.
    """
    raw = os.environ.get("AUTORESEARCH_MODE")
    if not raw:
        return DEFAULT_MODE
    if raw not in SPECS:
        raise SystemExit(_unknown_mode_message("AUTORESEARCH_MODE", raw))
    return raw


def stamp_mode_from_argv(argv=None) -> str:
    """Stamp `AUTORESEARCH_MODE` from a `--mode` on the command line.

    core/runtime.py (`_SPEC`) and core/pipeline.py (`MODE`) resolve the mode
    at IMPORT time, so a CLI taking `--mode` MUST stamp BEFORE its first
    `import runtime` / `import build`; the stamp governs the whole per-mode
    knob surface, and another mode's value on the grid is a metric
    DENOMINATOR error with no error surface
    (wiki/incidents/events-per-job-mid-flight-edit.md).

    Precedence: explicit `--mode`; else an already-set AUTORESEARCH_MODE
    naming a live spec (the supported flagless way --
    wiki/incidents/harvest-pyroot-nfs-rpc-hang.md's recovery recipe); else
    `DEFAULT_MODE`. ALWAYS stamps, so every reader agrees BY CONSTRUCTION.
    An UNKNOWN `--mode` is deliberately NOT stamped (it would kill the
    caller's imports before argparse); `assert_mode_stamped` names it
    properly a few lines later. Returns the resolved mode (never None).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = None
    for i, tok in enumerate(argv):
        if tok == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]
        elif tok.startswith("--mode="):
            mode = tok.split("=", 1)[1]
    if mode not in SPECS:
        # resolve_env_mode raises on a set-but-unknown env value.
        mode = resolve_env_mode()
    os.environ["AUTORESEARCH_MODE"] = mode
    return mode


def assert_mode_stamped(cli_mode: str) -> None:
    """Die loudly if the CLI's mode, the env stamp, runtime's spec and
    pipeline's MODE are not all the same string -- the failure it guards is
    silent by construction (an import-order accident), so abort at startup.
    """
    import runtime as _runtime
    import pipeline as _pipeline
    if cli_mode not in SPECS:
        # graph/run.py's --mode has no argparse choices, so a typo lands here.
        raise SystemExit(_unknown_mode_message("--mode", cli_mode))
    env = os.environ.get("AUTORESEARCH_MODE")
    got = {"--mode": cli_mode, "AUTORESEARCH_MODE": env,
           "runtime._SPEC.name": _runtime._SPEC.name,
           "pipeline.MODE": _pipeline.MODE}
    if len(set(got.values())) == 1:
        return
    detail = ", ".join(f"{k}={v!r}" for k, v in got.items())
    raise SystemExit(
        f"[mode] FATAL mode disagreement: {detail}. AUTORESEARCH_MODE must be "
        f"stamped from --mode BEFORE the first `import runtime` / `import "
        f"build` -- both resolve the process's mode at import time and cannot "
        f"be re-pointed. Nothing downstream would have errored: the grid "
        f"would just have run another mode's events_per_job/njobs/tarball/"
        f"stage chain. See core/modes.py::stamp_mode_from_argv.")
