"""ModeSpec registry: every per-mode FACT in one pure-data table (ADR-0002).

A Mode's definition was scattered across ~20 dispatch sites in 6 files, several
with silent fallbacks — the root soil of the foilsflash-tarball, preflight-
tuple, and foilsg-tarball incident class. This module is the single source:
frozen dataclasses, every field passed explicitly (a missing fact is an import
error, never a default), stdlib-only so the project .venv (and any
A/B picker venv) and pipeline.py can import it.

Behavior stays on the driver's BOMode subclasses (bo_driver.py),
which bind to their spec by name. Env seams deliberately stay env and are
applied ON TOP of the spec by consumers:
  AUTORESEARCH_NO_RUN1B        read by bo_driver.py cmd_evaluate's calo=None
                                substitution guard; the presniff_picker()
                                auto-stamp that used to set it from `--picker
                                qlnei` was retired 2026-08-19 with
                                graph/presniff.py -- dead weight even before
                                that, since no live mode's grid_stages
                                contains run1b_mubeam for the guard to gate on
  AUTORESEARCH_ELEBEAM_NJOBS   override on foilsflash's stage_target_overrides

Consumers: core/runtime.py (musing, stage chain, harvest verb, stage targets,
presubmit map), pipeline.py (grid tarball), botorch_predict.py (bounds),
bo_driver.py preflight (policy flags). Completeness is pinned by
tests/test_modes.py: SPECS keys == driver MODES keys == graph/state.py mode
Literal, and driver build_space bounds == spec bounds per mode (replacing the
"MUST stay in lockstep" comment convention with an enforced test).
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
    harvest_verb: str                 # pipeline.py verb: "harvest"
    stage_target_overrides: Dict[str, int]   # njobs overrides read by pipeline.stage_cfg()
    presubmit_after: Dict[str, Tuple[str, ...]]  # after-stage -> stages to presubmit
    # Per-stage stage_entries/<stage>.json overrides (events_per_job/memory_mb/
    # quorum), applied by pipeline.py's stage_cfg() on top of the
    # stage_entries defaults. The five Python modes pass {} explicitly (this
    # module's rule: a missing fact is an import error, never a default);
    # JSON modes populate this from `run.stage_tuning` (core/mode_json.py),
    # which has been the sole stage-tuning mechanism since the hardcoded
    # foilsflash block was retired from pipeline.py (2026-07-26).
    stage_tuning: Dict[str, Dict[str, object]]
    # Search-space box (numeric modes; michael's Categorical space is not a
    # box — None is passed EXPLICITLY there, it is not a default).
    bounds_lo: Optional[Tuple[float, ...]]
    bounds_hi: Optional[Tuple[float, ...]]
    int_dims: Optional[Tuple[int, ...]]
    # Preflight policy flags (replace the 6 hand-listed mode tuples in
    # bo_driver.py; the managed-overlap banner derives from
    # checks_managed_overlap, which retires the prodtarget6d banner drift).
    dumps_gdml: bool                  # preflight FCL writes a GDML dump
    verifies_foil_gdml: bool          # per-foil GDML-vs-geom assertion (hard gate)
    preserves_gdml: bool              # GDML kept as artifact (emission-only check)
    checks_managed_overlap: bool      # surface-check managed-volume scan
    # Strict overlap policy. True => preflight FAILS on ANY surface-check
    # overlap, not just volumes the BO knobs build. Added 2026-07-28 after
    # foilsflashRUN1BAP01 introduced 3 never-before-seen IPAsupport overlaps
    # and still PASSED: the managed/baseline whitelist keys on volume NAME,
    # but IPAsupport_* position derives from targetEnd, i.e. from our knobs.
    # Only modes whose Musing can actually reach zero may set this.
    require_zero_overlaps: bool       # any overlap => fail_managed

    # Leaderboard schema (single source — ADR-0002 extension, 2026-07-19).
    # knob_names/knob_fmts: per-knob column names + per-position formats.
    # metric_cols: the FULL post-knob column tail; the ProdTarget family's
    # divergence (mu_per_POT/edep/peak-dose, no sob/calo/alpha) is data
    # here, not a special case. The leading `config` column is a writer
    # detail (golden (a) pins it).
    knob_names: Tuple[str, ...]
    knob_fmts: Tuple[str, ...]
    metric_cols: Tuple[str, ...]

    # Measured observation noise, as ABSOLUTE sigma on each GP output axis
    # (botorch_predict._load_history_tensor's Y columns, in that order).
    # Fed to SingleTaskGP as train_Yvar so the GP stops inferring noise by
    # MLL. Left free, the foilsflash fit lands at sigma(sob)=0.0507 against
    # a replicate-measured 0.0051 — a 12x overestimate that shrank the
    # line's best-ever eval (SOBX01, sob=3.90) to a predicted 3.787 and
    # ranked it 16th of 324. See wiki/incidents/gp-free-noise-erases-champion.
    # None means "axis-1 units are data-dependent, a fixed sigma is
    # undefined" — passed EXPLICITLY by the ProdTarget family, not a default.
    obs_noise: Optional[Tuple[float, ...]]

    # Declarative geometry, metric mapping, and leaderboard path. Present ONLY
    # on JSON-defined modes (core/mode_json.py); the six Python modes render via
    # their BOMode subclass, set `leaderboard` as a class attribute, and pass
    # None here EXPLICITLY, never by default.
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

# JSON-defined modes (one file per line) are merged in AFTER the Python table,
# and may never shadow it -- see core/mode_json.py.
#
# Import mirrors our own package-qualification (__package__): this module is
# loaded two ways in production -- `core.modes` from the repo root, and bare
# `modes` when bo_driver.py runs as a grid-submitted subprocess with only
# core/ on sys.path (see tests/test_modes.py TestSubprocessImport, which
# pins the bare path). A hardcoded `from core.mode_json import ...` fails
# outright under the bare path (no `core` package to find there). A
# hardcoded bare `from mode_json import ...` would, under the qualified
# path, load core/mode_json.py a SECOND time under a different sys.modules
# key, which in turn would need a second, non-identical copy of THIS
# module's own ModeSpec to build specs from -- the exact
# two-non-identical-classes bug fixed for GeomTemplate in Task 4 (commit
# 9180eb3), resurrected here for ModeSpec. Mirroring __package__ guarantees
# mode_json.py resolves the ALREADY-loaded `modes`/`core.modes` instead of
# re-executing this file.
if __package__:
    from core.mode_json import load_mode_dir  # noqa: E402 - SPECS must exist first
else:
    from mode_json import load_mode_dir  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
SPECS.update(load_mode_dir(MODES_DIR, SPECS))

# THE fallback mode, for every module that resolves AUTORESEARCH_MODE at
# import time. Single-sourced here on purpose: core/runtime.py,
# core/pipeline.py and core/bo_driver.py each used to carry their own
# literal, and two of them disagreed ("foilspf" vs "foilsflash"), so
# `python -m graph.closed_loop --dry-run` with no --mode produced a
# three-way mode disagreement out of nothing but fallbacks. That is the
# shadow shape this whole branch existed to delete -- see
# tests/test_modes.py::test_one_default_mode_literal_in_the_tree, which
# fails if a fourth reader adds a fifth literal.
DEFAULT_MODE = "foilspf"
assert DEFAULT_MODE in SPECS, (
    f"DEFAULT_MODE {DEFAULT_MODE!r} is not a live mode; mode_specs/ has "
    f"{sorted(SPECS)}")


# ============================================================================
# CLI --mode -> AUTORESEARCH_MODE stamp
# ============================================================================

def _unknown_mode_message(source: str, value) -> str:
    """One message shape for every "that is not a mode" failure, whether it
    came from `--mode` or from AUTORESEARCH_MODE. Always names the bad value
    AND lists the live ones -- the live names differ by one or two
    characters (foilspf / foilspfbw / foilspfbp / foilspfbpx / foilspfbpz),
    so "invalid mode" alone does not tell an operator what they mistyped.
    """
    return (f"[mode] FATAL unknown {source} {value!r}. Known modes: "
            f"{', '.join(sorted(SPECS))}. (Mode specs live in mode_specs/; "
            f"retired ones are under mode_specs/archive/.)")


def resolve_env_mode() -> str:
    """The process's mode from AUTORESEARCH_MODE, VALIDATED.

    UNSET (or empty) falls through to `DEFAULT_MODE` -- that is the
    supported flagless invocation. SET BUT NOT A LIVE SPEC is FATAL, never a
    silent fallback: an unknown value used to be coerced to DEFAULT_MODE, so
    a single-character typo or a stale export naming a mode archived in
    Task 5 launched a full campaign at rc=0 against the wrong bounds, the
    wrong geometry and the wrong LEADERBOARD. That last one is the most
    expensive silent failure available here, because the leaderboard is what
    the GP refits on. `--mode nosuchmode` was already loud on both
    entrypoints; this closes the asymmetry.

    Every module-level reader of AUTORESEARCH_MODE calls THIS --
    core/runtime.py, core/pipeline.py, core/bo_driver.py,
    graph/pipeline_io.py, and rung 2 of
    `stamp_mode_from_argv` -- so the validation cannot be bypassed by
    reaching a reader that does not go through an entrypoint. A standalone
    `python core/pipeline.py` previously died with a bare
    KeyError('bogusmode') from core/runtime.py's dict lookup: same failure,
    much worse message. It now gets this one.

    SystemExit rather than a custom exception so the message reaches the
    operator verbatim, with no traceback, whether it fires during a CLI's
    argument handling or during a module import.
    """
    raw = os.environ.get("AUTORESEARCH_MODE")
    if not raw:
        return DEFAULT_MODE
    if raw not in SPECS:
        raise SystemExit(_unknown_mode_message("AUTORESEARCH_MODE", raw))
    return raw


def stamp_mode_from_argv(argv=None) -> str:
    """Stamp `AUTORESEARCH_MODE` from a `--mode` on the command line.

    Both core/runtime.py (`_SPEC`) and core/pipeline.py (`MODE`) resolve THE
    process's mode at IMPORT time out of this env var, and neither can be
    re-pointed afterwards. So a CLI entrypoint that takes `--mode` must stamp
    it BEFORE the first `import runtime` / `import build`, or the whole
    process runs against whatever mode happened to be the fallback -- with
    no error anywhere.

    graph/presniff.py used to do this and was deleted 2026-08-19 on the
    argument that every live spec's `run.*` fields are currently identical,
    so no mode-keyed lookup can disagree. That is true TODAY and is a
    statement about the data, not about the code: the surface it governs is
    events_per_job, njobs, memory_mb, quorum, grid_tarball, dsconf_musing,
    MUSING and -- via graph/build.py's STAGE_NODES -- the child's stage chain
    itself. The first per-mode edit to `run.stage_tuning.*` (exactly what
    mode_specs/ exists to enable) silently ships another mode's value to the
    grid, which is a metric DENOMINATOR error with no error surface. See
    wiki/incidents/events-per-job-mid-flight-edit.md for that failure shape.
    Callers pair this with `assert_mode_stamped()` after argparse, and use
    the RETURN VALUE as their `--mode` argparse default so that `args.mode`
    IS the resolved mode rather than a second constant that happens to
    match it.

    Lives here rather than in a resurrected presniff module because this is
    the registry: it is the only thing that can tell a real mode name from a
    typo without importing anything that reads the env var.

    Precedence, highest first:

      1. an explicit `--mode <spec>` on the command line
      2. an already-set AUTORESEARCH_MODE naming a live spec -- the
         supported way to pick a mode without the flag. (Not "documented":
         it appears nowhere in README.md, only in
         wiki/incidents/harvest-pyroot-nfs-rpc-hang.md and two
         docs/superpowers/plans/* files, always as an
         `AUTORESEARCH_MODE=<m> python ... pipeline.py` recovery recipe.
         Honouring it is still right -- clobbering an operator's explicit
         export with DEFAULT_MODE would be its own silent substitution.)
      3. `DEFAULT_MODE`

    It ALWAYS stamps, even in case 3. Returning without stamping is what
    made omitting `--mode` a hard startup FATAL: every module-level reader
    then applied its OWN fallback, and they did not agree. Stamping the
    default makes all of them agree BY CONSTRUCTION rather than by two
    constants happening to hold the same string.

    An UNKNOWN `--mode` is deliberately not stamped AS SUCH: stamping it
    would make the caller's `from runtime import ...` die with a bare
    `KeyError('foilspfbwq')` before argparse ever runs, replacing argparse's
    "invalid choice: ... (choose from ...)" with a traceback. It falls
    through to case 2/3 instead, and `assert_mode_stamped` reports the
    unknown name properly a few lines later.

    Returns the resolved mode (never None).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = None
    for i, tok in enumerate(argv):
        if tok == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]
        elif tok.startswith("--mode="):
            mode = tok.split("=", 1)[1]
    if mode not in SPECS:
        # Rung 2 + 3. resolve_env_mode RAISES on a set-but-unknown env value
        # rather than coercing it to DEFAULT_MODE -- see its docstring.
        mode = resolve_env_mode()
    os.environ["AUTORESEARCH_MODE"] = mode
    return mode


def assert_mode_stamped(cli_mode: str) -> None:
    """Die loudly if the CLI's mode, the env stamp, runtime's spec and
    pipeline's MODE are not all the same string.

    Belt-and-braces for `stamp_mode_from_argv`. The failure it guards is
    silent by construction -- an import-order accident inside graph/build.py
    decides which mode a stage-tuning lookup answers with -- so the check is
    a loud startup abort rather than a warning. Cheap: both modules are
    already imported by the time any caller reaches this.
    """
    import runtime as _runtime
    import pipeline as _pipeline
    if cli_mode not in SPECS:
        # Distinct message: `graph/run.py`'s --mode has no argparse choices
        # (the pool passes an already-validated mode), so a typo lands here
        # rather than at argparse. Without this branch it would be reported
        # as an import-order problem, which it is not. Same shape as the
        # AUTORESEARCH_MODE version -- see _unknown_mode_message.
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
