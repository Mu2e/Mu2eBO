"""TEMPORARY: today's ModeSpec, built from a schema-2 Study.

pipeline.py, runtime.py, preflight and the graph still read ModeSpec
fields. This view keeps them running on schema-2 files until Phase C moves
foilspf onto the contract engine and deletes both this module and those
code paths. A study the old pipeline cannot run is refused here, loudly.
STDLIB ONLY.
"""
from __future__ import annotations

from pathlib import Path

if __package__:
    from core.study import Study, load_study_file
else:
    from study import Study, load_study_file

_PIPELINE_TUNING = ("events_per_job", "memory_mb", "quorum")
_PLUGINS = ("ce_sensitivity", "flash_edep_per_pot")


def _need(cond: bool, study: Study, why: str) -> None:
    if not cond:
        raise ValueError(f"{study.path}: cannot run on the Phase-A pipeline: "
                         f"{why}")


def modespec_from_study(study: Study):
    if __package__:
        from core.modes import ModeSpec
    else:
        from modes import ModeSpec

    _need(study.layout == "v1", study,
          f"its leaderboard layout is {study.layout!r}; the pipeline writes v1 "
          f"rows")
    _need(study.geom is not None, study, "it has no geom")
    _need(study.preflight is not None
          and study.preflight["kit"] == "offline_preflight", study,
          "its preflight is not offline_preflight")
    _need(len(study.objectives) == 2, study,
          f"it has {len(study.objectives)} objectives; the pipeline writes "
          f"exactly 2")
    _need(not study.extra_metrics, study, "it declares extra_metrics")
    _need([c.name for c in study.extra_columns] == ["alpha", "obj"], study,
          "its extra_columns are not ['alpha', 'obj']")
    plugin_steps = {s.step for s in study.steps if s.kit in _PLUGINS}
    for o in study.objectives:
        _need(o.step in plugin_steps, study,
              f"objective {o.name!r} does not come from a harvest plugin")
    grid = [s for s in study.steps if s.kit == "prodtools"]
    _need(bool(grid), study, "it has no prodtools steps")
    roots = [s.step for s in grid if not s.files_from]
    _need(bool(roots) and roots[0] == grid[0].step, study,
          "its first prodtools step must take no files_from")
    for s in grid:
        _need(s.files_from in ((), (roots[0],)), study,
              f"step {s.step!r} files_from must be [] or [{roots[0]!r}] "
              f"(the pipeline's only input rule)")

    pre = study.kits["offline_preflight"]
    o0, o1 = study.objectives
    return ModeSpec(
        name=study.name,
        musing=pre["musing"],
        grid_tarball=study.kits["prodtools"]["code_tarball"],
        grid_stages=tuple(s.step for s in grid),
        stage_target_overrides={s.step: s.fixed["njobs"] for s in grid
                                if "njobs" in s.fixed},
        presubmit_after=({roots[0]: tuple(roots[1:])} if roots[1:] else {}),
        stage_tuning={s.step: {k: s.fixed[k] for k in _PIPELINE_TUNING
                               if k in s.fixed}
                      for s in grid
                      if any(k in s.fixed for k in _PIPELINE_TUNING)},
        bounds_lo=study.bounds_lo,
        bounds_hi=study.bounds_hi,
        int_dims=study.int_dims,
        dumps_gdml=pre["dumps_gdml"],
        verifies_foil_gdml=pre["verifies_foil_gdml"],
        checks_managed_overlap=pre["checks_managed_overlap"],
        require_zero_overlaps=pre["require_zero_overlaps"],
        knob_names=study.knob_names,
        knob_fmts=study.knob_fmts,
        metric_cols=(o0.name, o1.name, "alpha", "obj"),
        obs_noise=(o0.noise, o1.noise),
        geom=study.geom,
        metrics={o.name: (o.key,) for o in study.objectives},
        leaderboard_rel=study.leaderboard_rel,
    )


def load_modespec(path: Path):
    return modespec_from_study(load_study_file(Path(path)))
