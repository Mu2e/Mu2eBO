"""ModeSpec registry: every per-mode FACT in one pure-data table (ADR-0002).

Mode facts were once scattered across ~20 dispatch sites in 6 files, several
with silent fallbacks -- the soil of the foilsflash-tarball, preflight-tuple
and foilsg-tarball incident class. Here they are frozen dataclasses with
every field passed explicitly (a missing fact is an import error, never a
default), stdlib-only so any venv and pipeline.py can import it. Behavior
stays on bo_driver.py's JsonMode instances, which bind to their spec by name.
Consumers: core/runtime.py, pipeline.py, botorch_predict.py, bo_driver.py.
Completeness is pinned by tests/test_modes.py.

Two seams stay env and are applied ON TOP of the spec: AUTORESEARCH_NO_RUN1B
(bo_driver.py cmd_evaluate's calo=None substitution guard; nothing sets it
automatically, and no live mode's grid_stages has run1b_mubeam to gate on)
and AUTORESEARCH_ELEBEAM_NJOBS (foilsflash's stage_target_overrides).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:  # annotation-only: PEP 563 means this is never resolved at runtime
    from core.geom_template import GeomTemplate


@dataclass(frozen=True)
class ModeSpec:
    """The pure-data half of a Mode (CONTEXT.md: 'ModeSpec')."""
    name: str
    musing: str                       # abs path of the setup.sh preflight/harvest source
    grid_tarball: str                 # Code.tar.bz2 shipped to grid workers
    grid_stages: Tuple[str, ...]      # ordered stage chain
    stage_target_overrides: Dict[str, int]   # njobs overrides read by pipeline.stage_cfg()
    presubmit_after: Dict[str, Tuple[str, ...]]  # after-stage -> stages to presubmit
    # THE stage-tuning mechanism: per-stage events_per_job/memory_mb/quorum
    # overrides from `run.stage_tuning` (core/mode_json.py), applied by
    # pipeline.py's stage_cfg() over the stage_entries/<stage>.json defaults.
    stage_tuning: Dict[str, Dict[str, object]]
    # Search-space box. A non-box (categorical) space passes None
    # EXPLICITLY; it is never a default.
    bounds_lo: Optional[Tuple[float, ...]]
    bounds_hi: Optional[Tuple[float, ...]]
    int_dims: Optional[Tuple[int, ...]]
    # Preflight policy flags (replace 6 hand-listed mode tuples in
    # bo_driver.py; the managed-overlap banner derives from the last one).
    dumps_gdml: bool                  # preflight FCL writes a GDML dump
    verifies_foil_gdml: bool          # per-foil GDML-vs-geom assertion (hard gate)
    checks_managed_overlap: bool      # surface-check managed-volume scan
    # True => preflight FAILS on ANY surface-check overlap, not just volumes
    # the BO knobs build: foilsflashRUN1BAP01 PASSED with 3 never-before-seen
    # IPAsupport overlaps, because the managed/baseline whitelist keys on
    # volume NAME while IPAsupport_* position derives from targetEnd, i.e.
    # from our knobs. Only modes whose Musing can reach zero may set it.
    require_zero_overlaps: bool       # any overlap => fail_managed

    # Leaderboard schema (single source). metric_cols is the FULL post-knob
    # column tail, so the ProdTarget family's divergence (mu_per_POT/edep/
    # peak-dose, no sob/calo/alpha) is data here, not a special case. The
    # leading `config` column is a writer detail (golden parity (a) pins it).
    knob_names: Tuple[str, ...]
    knob_fmts: Tuple[str, ...]
    metric_cols: Tuple[str, ...]

    # Measured ABSOLUTE sigma per GP output axis (the Y column order of
    # botorch_predict._load_history_tensor), fed to SingleTaskGP as
    # train_Yvar so the GP stops inferring noise by MLL: left free, the
    # foilsflash fit lands at sigma(sob)=0.0507 vs a replicate-measured
    # 0.0051 -- a 12x overestimate that shrank the line's best-ever eval
    # (SOBX01, sob=3.90) to a predicted 3.787, ranked 16th of 324. See
    # wiki/incidents/gp-free-noise-erases-champion. None ("axis-1 units are
    # data-dependent") is passed EXPLICITLY by ProdTarget, not defaulted.
    obs_noise: Optional[Tuple[float, ...]]

    # Declarative geometry, metric mapping and leaderboard path, from
    # core/mode_json.py. Optional only because ModeSpec predates the JSON
    # conversion; every live mode populates all three.
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

# Every live mode is JSON (one file per mode in mode_specs/); load_mode_dir
# takes the existing dict so a non-JSON spec cannot be shadowed by a file.
#
# THE IMPORT MIRRORS OUR OWN PACKAGE-QUALIFICATION (__package__), because
# this module loads two ways in production: `core.modes` from the repo root,
# and bare `modes` when bo_driver.py runs as a grid subprocess with only
# core/ on sys.path (pinned by tests/test_modes.py TestSubprocessImport). A
# hardcoded qualified import fails outright on the bare path (no `core`
# package there); a hardcoded bare import would, on the qualified path, load
# core/mode_json.py a SECOND time under a different sys.modules key, which
# would then need a second, non-identical copy of THIS module's ModeSpec to
# build specs from -- the two-non-identical-classes bug already fixed once
# for GeomTemplate. Mirroring __package__ makes mode_json.py resolve the
# ALREADY-loaded `modes`/`core.modes`.
if __package__:
    from core.mode_json import load_mode_dir  # noqa: E402 - SPECS must exist first
else:
    from mode_json import load_mode_dir  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
SPECS.update(load_mode_dir(MODES_DIR, SPECS))

# THE fallback mode for every module that resolves AUTORESEARCH_MODE at
# import time. Single-sourced because per-module literals drift: two of the
# three readers once disagreed, making a flagless run a three-way mode
# disagreement built out of nothing but fallbacks. Pinned by
# tests/test_modes.py::test_one_default_mode_literal_in_the_tree.
DEFAULT_MODE = "foilspf"
assert DEFAULT_MODE in SPECS, (
    f"DEFAULT_MODE {DEFAULT_MODE!r} is not a live mode; mode_specs/ has "
    f"{sorted(SPECS)}")


# ============================================================================
# CLI --mode -> AUTORESEARCH_MODE stamp
# ============================================================================

def _unknown_mode_message(source: str, value) -> str:
    """One message shape for every "that is not a mode" failure, from
    `--mode` or AUTORESEARCH_MODE. Names the bad value AND the live ones:
    they differ by a character or two (foilspf / foilspfbw / foilspfbp /
    foilspfbpx / foilspfbpz), so "invalid mode" alone would not tell an
    operator what they mistyped.
    """
    return (f"[mode] FATAL unknown {source} {value!r}. Known modes: "
            f"{', '.join(sorted(SPECS))}. (Mode specs live in mode_specs/; "
            f"retired ones are under mode_specs/archive/.)")


def resolve_env_mode() -> str:
    """The process's mode from AUTORESEARCH_MODE, VALIDATED.

    UNSET (or empty) falls through to `DEFAULT_MODE` -- the supported
    flagless invocation. SET BUT NOT A LIVE SPEC is FATAL, never a silent
    fallback: coerced, a one-character typo or a stale export naming an
    archived mode launches a full campaign at rc=0 against the wrong bounds,
    the wrong geometry and the wrong LEADERBOARD -- the last being the most
    expensive silent failure available here, since the leaderboard is what
    the GP refits on. Every module-level reader of AUTORESEARCH_MODE calls
    THIS (core/runtime.py, core/pipeline.py, core/bo_driver.py,
    graph/pipeline_io.py, stamp_mode_from_argv), so none can bypass the
    validation by skipping the entrypoints. SystemExit so the message reaches
    the operator verbatim, with no traceback, from a CLI or an import.
    """
    raw = os.environ.get("AUTORESEARCH_MODE")
    if not raw:
        return DEFAULT_MODE
    if raw not in SPECS:
        raise SystemExit(_unknown_mode_message("AUTORESEARCH_MODE", raw))
    return raw


def stamp_mode_from_argv(argv=None) -> str:
    """Stamp `AUTORESEARCH_MODE` from a `--mode` on the command line.

    core/runtime.py (`_SPEC`) and core/pipeline.py (`MODE`) each resolve THE
    process's mode at IMPORT time from this env var and cannot be re-pointed
    afterwards, so a CLI taking `--mode` MUST stamp BEFORE its first `import
    runtime` / `import build`. Otherwise the process silently runs on
    whatever the fallback was, and that governs events_per_job, njobs,
    memory_mb, quorum, grid_tarball, dsconf_musing, MUSING and -- via
    graph/build.py's STAGE_NODES -- the child's stage chain: another mode's
    value on the grid is a metric DENOMINATOR error with no error surface
    (wiki/incidents/events-per-job-mid-flight-edit.md). Callers pair this
    with `assert_mode_stamped()` after argparse and use the RETURN VALUE as
    their `--mode` argparse default. It lives in the registry because only
    the registry can tell a real mode from a typo without importing a reader
    of the env var.

    Precedence: an explicit `--mode <spec>`; else an already-set
    AUTORESEARCH_MODE naming a live spec (the supported flagless way --
    wiki/incidents/harvest-pyroot-nfs-rpc-hang.md's `AUTORESEARCH_MODE=<m>
    python ... pipeline.py` recovery recipe; clobbering an operator's export
    would be its own silent substitution); else `DEFAULT_MODE`. It ALWAYS
    stamps, even in that last case, so every reader agrees BY CONSTRUCTION
    instead of by separate fallbacks holding the same string.

    An UNKNOWN `--mode` is deliberately NOT stamped: that would make the
    caller's `from runtime import ...` die with a bare KeyError before
    argparse ever runs. It falls through, and `assert_mode_stamped` names it
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
    pipeline's MODE are not all the same string.

    Belt-and-braces for `stamp_mode_from_argv`: the failure it guards is
    silent by construction (an import-order accident decides which mode a
    stage-tuning lookup answers with), so it aborts loudly at startup rather
    than warning. Cheap -- both modules are already imported by then.
    """
    import runtime as _runtime
    import pipeline as _pipeline
    if cli_mode not in SPECS:
        # `graph/run.py`'s --mode has no argparse choices (the pool passes an
        # already-validated mode), so a typo lands here, not at argparse, and
        # would otherwise be misreported as an import-order problem.
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
