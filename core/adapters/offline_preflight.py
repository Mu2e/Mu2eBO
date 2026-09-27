"""The geometry pre-check as a contract kit: the adapter the engine drives
for a study whose preflight is `offline_preflight` (Phase C2a spec,
docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md, "1. The
offline_preflight kit").

check hands the point to preflight_checks.run_preflight, the sequence the
old pipeline's pre-check runs too: unpack the study's code tarball (the
one its prodtools steps ship, so the pre-check runs the jobs' own code)
under <GRID_DATA_ROOT>/_code/, write the point's geometry and the
surface-check files into the emptied <GRID_DATA_ROOT>/<config>/preflight/,
run `mu2e -n 1` there and read the log into a verdict. This module adds
the contract's side: the checks on check's arguments, the GDML dump kept
as asbuilt.gdml, the verdict as (ok, message). The check always runs on
this node, whatever --executor says: one event, no inputs.
"""
from __future__ import annotations

from pathlib import Path

if __package__ == "core.adapters":
    from core import kit_registry, paths
    from core.adapters import preflight_checks as pc
    from core.adapters import prodtools_entry as pe
    from core.contract import Describe
else:
    import kit_registry
    import paths
    from adapters import preflight_checks as pc
    from adapters import prodtools_entry as pe
    from contract import Describe

VERSION = "offline-preflight-adapter/1"   # bump when a verdict would change
# The kit's study settings, which node_preflight sends as its params: the
# kit takes exactly these, checked by the loader's own validators.
_SETTINGS = kit_registry.KITS["offline_preflight"].study_keys
PARAMS = tuple(_SETTINGS)
ASBUILT_NAME = "asbuilt.gdml"


class OfflinePreflightKit:
    """One campaign child's pre-check. It offers only `check` and
    `describe`: a study names it as its preflight, never as a step."""

    name = "offline_preflight"
    accepts_lists = False
    EXECUTORS = ("grid", "local")
    REQUIRES_KERBEROS = False       # no inputs, no grid
    LAUNCH_STAGGER_S = 0
    config_problem = staticmethod(kit_registry.config_name_problem)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 grid_root=None, runner=None, timeout_s=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"offline_preflight: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign, self.executor = campaign, executor
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._runner = runner       # None: run_preflight's, pc.run_check
        self._timeout_s = pc.TIMEOUT_S if timeout_s is None else timeout_s

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return VERSION

    @property
    def tools(self) -> frozenset:
        return frozenset({"check", "describe"})

    def describe(self):
        return Describe(PARAMS, (), False)

    def close(self) -> None:
        pass

    def check(self, name, params, files, inputs, workflow):
        config = self._config_of(name)
        params = kit_registry.validate(self.name, params, _SETTINGS,
                                       f"{self.name}: params", required=True)
        if inputs:
            raise ValueError(f"offline_preflight: takes no inputs, got "
                             f"{len(inputs)}")
        geoms = [f for f in files if f.get("name") == "geom"]
        if len(geoms) != 1:
            raise ValueError(f"offline_preflight: needs exactly one file "
                             f"named 'geom', got "
                             f"{[f.get('name') for f in files]}")
        geom = pe.local_path(geoms[0], "offline_preflight: file")
        workdir = self._grid_root / config / "preflight"
        verdict, _out = pc.run_preflight(
            params["code_tarball"], geom.read_text(), config, workdir,
            cache_root=self._grid_root / "_code",
            dumps_gdml=params["dumps_gdml"],
            verifies_foil_gdml=params["verifies_foil_gdml"],
            checks_managed_overlap=params["checks_managed_overlap"],
            require_zero_overlaps=params["require_zero_overlaps"],
            label=f"offline_preflight/{config}", timeout_s=self._timeout_s,
            runner=self._runner)
        # run_preflight emptied the workdir first, so a dump here is this
        # run's.
        dump = workdir / pc.PREFLIGHT_GDML_NAME
        if dump.exists():
            dump.replace(workdir / ASBUILT_NAME)
        return verdict.ok, f"{verdict.code}: {verdict.reason}"

    # --- plumbing ----------------------------------------------------------
    @staticmethod
    def _config_of(name) -> str:
        """'<config>.preflight' -> config. The config names the grid jobs'
        geometry file and runs, so it must pass the one config-name rule
        (kit_registry.config_name_problem), as the prodtools kit's does."""
        config, dot, step = name.rpartition(".")
        if not dot or not config or step != "preflight":
            raise ValueError(f"offline_preflight: {name!r} is not "
                             f"<config>.preflight")
        why = kit_registry.config_name_problem(config)
        if why:
            raise ValueError(f"offline_preflight: {why}")
        return config
