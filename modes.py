"""ModeSpec registry: every per-mode FACT in one pure-data table (ADR-0002).

A Mode's definition was scattered across ~20 dispatch sites in 6 files, several
with silent fallbacks — the root soil of the foilsflash-tarball, preflight-
tuple, and foilsg-tarball incident class. This module is the single source:
frozen dataclasses, every field passed explicitly (a missing fact is an import
error, never a default), stdlib-only so every venv (.venv-graph,
.venv-botorch) and pipeline.py can import it.

Behavior stays on the driver's BOMode subclasses (autoresearch_bo_michael.py),
which bind to their spec by name. Env seams deliberately stay env and are
applied ON TOP of the spec by consumers:
  AUTORESEARCH_NO_RUN1B        post-lookup stage filter (graph/config.py)
  AUTORESEARCH_ELEBEAM_NJOBS   override on foilsflash's stage_target_overrides

Consumers: graph/config.py (musing, stage chain, harvest verb, stage targets,
presubmit map), pipeline.py (grid tarball), botorch_predict.py (bounds),
autoresearch_bo_michael.py preflight (policy flags). Completeness is pinned by
tests/test_modes.py: SPECS keys == driver MODES keys == graph/state.py mode
Literal, and driver build_space bounds == spec bounds per mode (replacing the
"MUST stay in lockstep" comment convention with an enforced test).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

_RUN1BAK = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh"
# foils family preflight MUST see the patched StoppingTargetMaker
# (stoppingTarget.holeRadii vector) or it diverges from the grid tarball and
# silently validates the wrong geometry (foilsg-grid-tarball incident).
_HELICAL_LOCAL = "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh"
# prodtarget: locally-built patched workdir backed by MDC2025aq (%02d plate-LV
# rename + NIEL SD + spacer-shrink). See wiki prodtarget-env-divergence.
_PRODTARGET_LOCAL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/setup_local.sh"

_BASE_TARBALL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_base.tar.bz2"
# Patched libmu2e_GeometryService.so (holeRadii vector). michael/helical stay
# on Code_helical_base (Offline_helical's Mu2eG4 lib predates the twistedbox
# facet fix); foils family requires this one.
_HOLERADII_TARBALL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2"
# prodtarget ships per-STAGE via pipeline.py STAGES["pot_only"]["code_tarball"];
# recorded here as the mode's tarball fact (same file).
_PRODTARGET_TARBALL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2"

_CE_CALO_CHAIN = ("mubeam", "run1b_mubeam", "concat", "mustops_ce")


@dataclass(frozen=True)
class ModeSpec:
    """The pure-data half of a Mode (CONTEXT.md: 'ModeSpec')."""
    name: str
    musing: str                       # abs path of the setup.sh preflight/harvest source
    grid_tarball: str                 # Code.tar.bz2 shipped to grid workers
    grid_stages: Tuple[str, ...]      # ordered stage chain
    harvest_verb: str                 # pipeline.py verb: "harvest" | "harvest-pot-only"
    stage_target_overrides: Dict[str, int]   # njobs overrides on graph.config.STAGE_TARGETS
    presubmit_after: Dict[str, Tuple[str, ...]]  # after-stage -> stages to presubmit
    # Search-space box (numeric modes; michael's Categorical space is not a
    # box — None is passed EXPLICITLY there, it is not a default).
    bounds_lo: Optional[Tuple[float, ...]]
    bounds_hi: Optional[Tuple[float, ...]]
    int_dims: Optional[Tuple[int, ...]]
    # Preflight policy flags (replace the 6 hand-listed mode tuples in
    # autoresearch_bo_michael.py; the managed-overlap banner derives from
    # checks_managed_overlap, which retires the prodtarget6d banner drift).
    preflight_fcl: str                # "surfacecheck" | "preflight"
    dumps_gdml: bool                  # preflight FCL writes a GDML dump
    verifies_foil_gdml: bool          # per-foil GDML-vs-geom assertion (hard gate)
    preserves_gdml: bool              # GDML kept as artifact (emission-only check)
    checks_managed_overlap: bool      # surface-check managed-volume scan


SPECS: Dict[str, ModeSpec] = {
    "michael": ModeSpec(
        name="michael",
        musing=_RUN1BAK,
        grid_tarball=_BASE_TARBALL,
        grid_stages=_CE_CALO_CHAIN,
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=None, bounds_hi=None, int_dims=None,  # Categorical (COL5) space
        preflight_fcl="preflight",
        dumps_gdml=False, verifies_foil_gdml=False, preserves_gdml=False,
        checks_managed_overlap=False,
    ),
    "helical": ModeSpec(
        name="helical",
        musing=_RUN1BAK,
        grid_tarball=_BASE_TARBALL,
        grid_stages=_CE_CALO_CHAIN,
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(0.01, 40.0, 25.0, 60.0),
        bounds_hi=(5.0, 400.0, 500.0, 720.0),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=False, verifies_foil_gdml=False, preserves_gdml=False,
        checks_managed_overlap=True,
    ),
    "foils": ModeSpec(
        name="foils",
        musing=_HELICAL_LOCAL,
        grid_tarball=_HOLERADII_TARBALL,
        grid_stages=_CE_CALO_CHAIN,
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        # last two dims are hole RADII [mm] (foilsf/foilsflash use fractions)
        bounds_lo=(50.0, 50.0, 0.01, 0.01, 0.0, 0.0),
        bounds_hi=(250.0, 250.0, 1.0, 1.0, 50.0, 50.0),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=True, preserves_gdml=False,
        checks_managed_overlap=True,
    ),
    "foilsf": ModeSpec(
        name="foilsf",
        musing=_HELICAL_LOCAL,
        grid_tarball=_HOLERADII_TARBALL,
        grid_stages=_CE_CALO_CHAIN,
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(50.0, 50.0, 0.01, 0.01, 0.0, 0.0),
        bounds_hi=(250.0, 250.0, 1.0, 1.0, 0.95, 0.95),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=True, preserves_gdml=False,
        checks_managed_overlap=True,
    ),
    "foilsflash": ModeSpec(
        name="foilsflash",
        musing=_HELICAL_LOCAL,
        grid_tarball=_HOLERADII_TARBALL,
        # concat dropped 2026-07-10 (mu- purity filter lives in the mubeam
        # template); elebeam_flash resamples the external EleBeamCat.
        grid_stages=("mubeam", "mustops_ce", "elebeam_flash"),
        harvest_verb="harvest",
        # Lever-1 fast sob stages; elebeam stays 100 (σ_flash 2.52%, the
        # 2026-07-09 standard). AUTORESEARCH_ELEBEAM_NJOBS env overrides on top.
        stage_target_overrides={"mubeam": 15, "mustops_ce": 15,
                                "elebeam_flash": 100},
        presubmit_after={"mubeam": ("elebeam_flash",)},
        # hT floor 0.002 = the 2026-07-09 widened thickness-probe box.
        bounds_lo=(50.0, 50.0, 0.002, 0.002, 0.0, 0.0),
        bounds_hi=(250.0, 250.0, 1.0, 1.0, 0.95, 0.95),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=True, preserves_gdml=False,
        checks_managed_overlap=True,
    ),
    "foilsg": ModeSpec(
        name="foilsg",
        musing=_HELICAL_LOCAL,
        grid_tarball=_HOLERADII_TARBALL,
        grid_stages=_CE_CALO_CHAIN,
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(50.0, 0.01, 0.0) * 4,
        bounds_hi=(250.0, 1.0, 0.95) * 4,
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=True, preserves_gdml=False,
        checks_managed_overlap=True,
    ),
    "ipa": ModeSpec(
        name="ipa",
        musing=_RUN1BAK,   # overrides only protonabsorber.* — stock Musing suffices
        # Was the silent .get(..., michael) fallback; Code_helical_base is
        # CORRECT for ipa (needs patched Mu2eG4 only, no holeRadii) — now explicit.
        grid_tarball=_BASE_TARBALL,
        grid_stages=("mubeam", "concat", "mustops_ce", "mustops_pileup"),
        harvest_verb="harvest",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(0.1, 200.0, 250.0, 250.0, 400.0),
        bounds_hi=(3.0, 700.0, 400.0, 400.0, 800.0),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=False, verifies_foil_gdml=False, preserves_gdml=False,
        checks_managed_overlap=False,
    ),
    "prodtarget": ModeSpec(
        name="prodtarget",
        musing=_PRODTARGET_LOCAL,
        grid_tarball=_PRODTARGET_TARBALL,   # shipped via STAGES["pot_only"]["code_tarball"]
        grid_stages=("pot_only",),
        harvest_verb="harvest-pot-only",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 4.0, 4.0, 25.0),
        bounds_hi=(4.5, 4.5, 4.5, 8.0, 8.0, 8.0, 12.0, 12.0, 12.0, 45.0),
        int_dims=(9,),   # numberOfPlates
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=False, preserves_gdml=True,
        checks_managed_overlap=True,
    ),
    "prodtarget6d": ModeSpec(
        name="prodtarget6d",
        musing=_PRODTARGET_LOCAL,
        grid_tarball=_PRODTARGET_TARBALL,
        grid_stages=("pot_only",),
        harvest_verb="harvest-pot-only",
        stage_target_overrides={},
        presubmit_after={},
        bounds_lo=(2.0, 2.0, 2.0, 3.0, 3.0, 3.0),
        bounds_hi=(4.5, 4.5, 4.5, 8.0, 8.0, 8.0),
        int_dims=(),
        preflight_fcl="surfacecheck",
        dumps_gdml=True, verifies_foil_gdml=False, preserves_gdml=True,
        checks_managed_overlap=True,
    ),
}
