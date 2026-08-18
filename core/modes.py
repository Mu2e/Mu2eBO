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
  AUTORESEARCH_NO_RUN1B        post-lookup stage filter (graph/config.py)
  AUTORESEARCH_ELEBEAM_NJOBS   override on foilsflash's stage_target_overrides

Consumers: graph/config.py (musing, stage chain, harvest verb, stage targets,
presubmit map), pipeline.py (grid tarball), botorch_predict.py (bounds),
bo_driver.py preflight (policy flags). Completeness is pinned by
tests/test_modes.py: SPECS keys == driver MODES keys == graph/state.py mode
Literal, and driver build_space bounds == spec bounds per mode (replacing the
"MUST stay in lockstep" comment convention with an enforced test).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:  # annotation-only: PEP 563 means this is never resolved at runtime
    from core.geom_template import GeomTemplate


@dataclass(frozen=True)
class StageDef:
    """Per-stage definition: everything pipeline.py needs to submit, poll,
    and collect outputs for one stage.  Replaces the old hardcoded STAGES
    dict in pipeline.py."""
    name: str
    desc_fmt: str                     # e.g. "Run1A_MuBeam_{cfg}"
    output_glob: str                  # e.g. "sim.*.TargetStops.*.art"
    entry: str                        # path to stage_entries JSON, repo-relative
    consumes: Optional[str] = None    # stage whose outputs feed this one
    consumes_filter: Optional[str] = None  # substring filter on consumed outputs
    merge_factor: Optional[int] = None     # for merging stages (concat)
    njobs: int = 200                  # default number of jobs
    events_per_job: int = 5000        # default events per job
    memory_mb: Optional[int] = None   # memory override (MB)
    quorum: Optional[float] = None    # fraction of jobs required to proceed
    dsconf_musing: Optional[str] = None  # per-stage dsconf override


@dataclass(frozen=True)
class HarvestExtractor:
    """One metric-extraction step in the harvest pipeline."""
    name: str
    type: str                         # "mu2e_module", "root_macro", "gallery",
                                      # "event_count", "histogram", "script"
    stage: Optional[str] = None       # which stage's outputs to consume
    # mu2e_module type
    fcl: Optional[str] = None
    output: Optional[str] = None
    # root_macro type
    script: Optional[str] = None
    args: Optional[Tuple[str, ...]] = None
    # gallery type
    collection: Optional[str] = None
    quantity: Optional[str] = None
    tags: Optional[Tuple[str, ...]] = None
    # histogram type
    histogram_path: Optional[str] = None
    bin_labels: Optional[Tuple[str, ...]] = None
    # event_count type
    count_filter: Optional[str] = None
    # script type
    command: Optional[Tuple[str, ...]] = None
    parse_json: bool = False
    fields: Optional[Tuple[str, ...]] = None
    # shared
    parse_pattern: Optional[str] = None
    parse_field: Optional[str] = None
    parse_type: Optional[str] = None  # "int", "float"
    fail_soft: bool = False


@dataclass(frozen=True)
class HarvestConfig:
    """Declarative harvest configuration: extractors + derived fields."""
    extractors: Tuple[HarvestExtractor, ...]
    derived: Dict[str, str]           # field_name -> expression
    summary_fields: Tuple[str, ...]   # ordered fields for summary.json


@dataclass(frozen=True)
class ModeSpec:
    """The pure-data half of a Mode (CONTEXT.md: 'ModeSpec')."""
    name: str
    musing: str                       # abs path of the setup.sh preflight/harvest source
    grid_tarball: str                 # Code.tar.bz2 shipped to grid workers
    grid_stages: Tuple[str, ...]      # ordered stage chain
    harvest_verb: str                 # pipeline.py verb: "harvest"
    stage_target_overrides: Dict[str, int]   # njobs overrides on graph.config.STAGE_TARGETS
    presubmit_after: Dict[str, Tuple[str, ...]]  # after-stage -> stages to presubmit
    stage_tuning: Dict[str, Dict[str, object]]
    # Search-space box
    bounds_lo: Optional[Tuple[float, ...]]
    bounds_hi: Optional[Tuple[float, ...]]
    int_dims: Optional[Tuple[int, ...]]
    # Preflight policy flags
    dumps_gdml: bool
    verifies_foil_gdml: bool
    preserves_gdml: bool
    checks_managed_overlap: bool
    require_zero_overlaps: bool

    # Leaderboard schema
    knob_names: Tuple[str, ...]
    knob_fmts: Tuple[str, ...]
    metric_cols: Tuple[str, ...]

    obs_noise: Optional[Tuple[float, ...]]

    # Declarative geometry, metric mapping, and leaderboard path.
    geom: Optional[GeomTemplate]
    metrics: Optional[Dict[str, Tuple[str, ...]]]
    leaderboard_rel: Optional[str]

    # --- NEW: per-stage definitions and declarative harvest ---
    # stage_defs: the COMPLETE per-stage configuration. Every stage in
    # grid_stages MUST have an entry here. This replaces the old hardcoded
    # STAGES dict in pipeline.py.
    stage_defs: Dict[str, StageDef] = None  # type: ignore[assignment]

    # harvest_config: declarative metric extraction. When present, the
    # generic harvest orchestrator runs these extractors and evaluates the
    # derived-field expressions. When None, falls back to the legacy
    # cmd_harvest in pipeline.py (for backward compat during migration).
    harvest_config: Optional[HarvestConfig] = None

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
        # Validate stage_defs covers every grid_stages entry
        if self.stage_defs is not None:
            for s in self.grid_stages:
                if s not in self.stage_defs:
                    raise ValueError(
                        f"{self.name}: grid_stages includes {s!r} but "
                        f"stage_defs has no entry for it")


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
