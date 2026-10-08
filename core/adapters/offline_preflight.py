"""The geometry pre-check as a contract kit: the adapter the engine drives
for a study whose preflight is `offline_preflight` (Phase C2a spec,
docs/superpowers/specs/2026-09-26-c2a-preflight-kit-design.md, "1. The
offline_preflight kit").

check hands the point to preflight_checks.run_preflight: unpack the
study's code tarball (the one its prodtools steps ship, so the pre-check
runs the jobs' own code) under <GRID_DATA_ROOT>/_code/, write the point's
geometry and the surface-check files into the emptied
<GRID_DATA_ROOT>/<config>/preflight/, run `mu2e -n 1` there and read the log
into a verdict. This module adds the contract's side: the checks on check's
arguments, the GDML dump kept as asbuilt.gdml, the verdict as (ok, message).
The check always runs on this node, whatever --executor says: one event, no
inputs.
"""
from __future__ import annotations

from pathlib import Path

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

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 grid_root=None, runner=None, timeout_s=None):
        executors = kit_registry.KITS[self.name].executors
        if executor not in executors:
            raise ValueError(f"{self.name}: executor must be one of "
                             f"{list(executors)}, got {executor!r}")
        self.campaign, self.executor = campaign, executor
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._runner = runner       # None: run_preflight's, pc.run_check
        self._timeout_s = pc.TIMEOUT_S if timeout_s is None else timeout_s

    # --- the Kit interface -------------------------------------------------
    def start(self) -> None:
        """Nothing to start: the check runs a local process per call."""

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
        cache_root = self._grid_root / "_code"
        # EDQUOT/ENOSPC in stage_workdir, a failed mkdtemp/rename in
        # pe.unpacked, or a failed read of the geometry file surface as a
        # bare OSError; the rewrap names the workdir and the cache, which
        # the bare one does not.
        try:
            verdict, _out = pc.run_preflight(
                params["code_tarball"], geom.read_text(), config, workdir,
                cache_root=cache_root,
                dumps_gdml=params["dumps_gdml"],
                verifies_foil_gdml=params["verifies_foil_gdml"],
                checks_managed_overlap=params["checks_managed_overlap"],
                require_zero_overlaps=params["require_zero_overlaps"],
                label=f"offline_preflight/{config}", timeout_s=self._timeout_s,
                runner=self._runner)
        except OSError as exc:
            raise ValueError(f"offline_preflight: pre-check for {config} "
                             f"under {workdir} (cache {cache_root}) failed: "
                             f"{exc}") from exc
        # run_preflight emptied the workdir first, so a dump here is this
        # run's.
        dump = workdir / pc.PREFLIGHT_GDML_NAME
        if dump.exists():
            dump.replace(workdir / ASBUILT_NAME)
        # The notes say what the check actually verified (foils against the
        # GDML, overlap hits, the return code); a message without them
        # hides that from the point's log and broken.txt.
        message = f"{verdict.code}: {verdict.reason}"
        if verdict.notes:
            message += "\n" + "\n".join(f"  {n}" for n in verdict.notes)
        return verdict.ok, message

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
