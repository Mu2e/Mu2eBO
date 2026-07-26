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

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

try:
    from core.geom_template import GeomTemplate
except ImportError:
    # Fallback when core is on sys.path directly (subprocess case;
    # see wiki/incidents/claude-bash-no-ssh-agent.md for cross-shell context)
    from geom_template import GeomTemplate  # type: ignore[no-redef]

_RUN1BAK = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh"
# foils family preflight MUST see the patched StoppingTargetMaker
# (stoppingTarget.holeRadii vector) or it diverges from the grid tarball and
# silently validates the wrong geometry (foilsg-grid-tarball incident).
_HELICAL_LOCAL = "/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh"
# prodtarget: locally-built patched workdir backed by MDC2025aq (%02d plate-LV
# rename + NIEL SD + spacer-shrink). See wiki prodtarget-env-divergence.
_PRODTARGET_LOCAL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/setup_local.sh"

# Patched libmu2e_GeometryService.so (holeRadii vector). michael/helical stay
# on Code_helical_base (Offline_helical's Mu2eG4 lib predates the twistedbox
# facet fix); foils family requires this one.
_HOLERADII_TARBALL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2"
# prodtarget ships per-STAGE via pipeline.py STAGES["pot_only"]["code_tarball"];
# recorded here as the mode's tarball fact (same file).
_PRODTARGET_TARBALL = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2"

_CE_CALO_CHAIN = ("mubeam", "run1b_mubeam", "concat", "mustops_ce")

# Replicate-measured observation noise (see ModeSpec.obs_noise).
# sigma(sob): pooled within-group sd over repeated geometries — 0.0059 raw
# on foilsflash (9 groups, df=12), 0.0051 after removing the 0.01
# leaderboard quantization; 0.0030 on foils_v3 (3 groups, df=8). 0.006 is
# the conservative round number covering both.
_SIGMA_SOB = 0.006
# calo modes: axis 1 is -log10(calo), so sigma = sigma_rel / ln(10).
# Uses the 8% budget from wiki/concepts/bo-noise-budget.md rather than the
# 3.29% replicate estimate (df=8, dominated by one 11% group) — deliberately
# conservative on the axis that is NOT the decision axis.
_FOILS_FAMILY_NOISE = (_SIGMA_SOB, 0.035)


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
    # bo_driver.py; the managed-overlap banner derives from
    # checks_managed_overlap, which retires the prodtarget6d banner drift).
    preflight_fcl: str                # "surfacecheck" | "preflight"
    dumps_gdml: bool                  # preflight FCL writes a GDML dump
    verifies_foil_gdml: bool          # per-foil GDML-vs-geom assertion (hard gate)
    preserves_gdml: bool              # GDML kept as artifact (emission-only check)
    checks_managed_overlap: bool      # surface-check managed-volume scan

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


SPECS: Dict[str, ModeSpec] = {
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
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_rIn_up", "extra_rIn_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "calo", "alpha", "obj"),
        obs_noise=_FOILS_FAMILY_NOISE,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
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
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_f_up", "extra_f_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "calo", "alpha", "obj"),
        obs_noise=_FOILS_FAMILY_NOISE,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
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
        knob_names=("extra_rOut_up", "extra_rOut_dn",
                    "extra_halfThickness_up", "extra_halfThickness_dn",
                    "extra_f_up", "extra_f_dn"),
        knob_fmts=("{:.4f}", "{:.4f}", "{:.6f}", "{:.6f}", "{:.4f}", "{:.4f}"),
        metric_cols=("sob", "flash_edep", "alpha", "obj"),
        # axis 1 is -log10(flash_edep): sigma_rel 2.31% / ln(10) = 0.0100.
        obs_noise=(_SIGMA_SOB, 0.010),
        geom=None,
        metrics=None,
        leaderboard_rel=None,
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
        knob_names=("rOut_g0", "hT_g0", "f_g0", "rOut_g1", "hT_g1", "f_g1",
                    "rOut_g2", "hT_g2", "f_g2", "rOut_g3", "hT_g3", "f_g3"),
        knob_fmts=("{:.4f}", "{:.6f}", "{:.4f}") * 4,
        metric_cols=("sob", "calo", "alpha", "obj"),
        obs_noise=_FOILS_FAMILY_NOISE,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
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
        knob_names=("r0", "r1", "r2", "t0", "t1", "t2",
                    "l0", "l1", "l2", "N"),
        knob_fmts=("{:.4f}",) * 9 + ("{:d}",),
        metric_cols=("mu_per_POT", "edep_per_POT_MeV",
                     "peak_dose_Gy_per_POT", "peak_plate_idx", "obj"),
        # EXPLICIT None, not a default: this family's GP axis 1 is a raw
        # negated value whose units depend on which fallback fired
        # (-peak_dose_Gy_per_POT, else -edep_per_POT_MeV — see
        # botorch_predict._load_history_tensor). One absolute sigma cannot
        # cover both scales, and no replicate evals exist to measure one.
        # Keeps the MLL-fitted noise until somebody measures it.
        obs_noise=None,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
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
        knob_names=("r0", "r1", "r2", "t0", "t1", "t2"),
        knob_fmts=("{:.4f}",) * 6,
        metric_cols=("mu_per_POT", "edep_per_POT_MeV",
                     "peak_dose_Gy_per_POT", "peak_plate_idx", "obj"),
        # EXPLICIT None, not a default: this family's GP axis 1 is a raw
        # negated value whose units depend on which fallback fired
        # (-peak_dose_Gy_per_POT, else -edep_per_POT_MeV — see
        # botorch_predict._load_history_tensor). One absolute sigma cannot
        # cover both scales, and no replicate evals exist to measure one.
        # Keeps the MLL-fitted noise until somebody measures it.
        obs_noise=None,
        geom=None,
        metrics=None,
        leaderboard_rel=None,
    ),
}
