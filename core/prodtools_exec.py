"""Prodtools execution seam: entry rendering + tool invocation.

Everything autoresearch says to prodtools goes through this module:
render a json2jobdef entry, build the cnf, run it (runlocal), submit it
(submit_entry via core/prodtools_submit_driver.py), wait on it (jobwait),
and read back the shared wait.json summary. pipeline.py's verbs call in;
nothing here knows about modes, leaderboards, or harvest.

Spec: docs/superpowers/specs/2026-08-16-prodtools-switch-design.md.
"""
import getpass
import json
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from paths import prodtools_root

USER = os.environ.get("USER") or getpass.getuser()

# Same outstage root the mu2ejobsub era used (pipeline.py OUTSTAGE);
# prodtools computes it as {wftop}/{user}/workflow/{wfproject}/outstage.
WFTOP = "/pnfs/mu2e/scratch/users"
WFPROJECT = "default"


def outstage_root() -> str:
    return f"{WFTOP}/{USER}/workflow/{WFPROJECT}/outstage"


def render_entry(stage, stage_cfg, *, config, dsconf, desc, njobs,
                 code_tarball, fcl_name, events=None, run=None,
                 memory_mb=None, input_data=None, inloc=None,
                 resampler_name=None) -> dict:
    """One json2jobdef entry dict for a (config, stage).

    Code-mode for every stage: the per-config Code tarball ships the
    geom AND the materialized template, whose basename is `fcl` -- the
    worker resolves it via the tarball's setup_post.sh search path, so
    grid and local read the identical FCL (the env-divergence class of
    incidents is closed by construction, not by care).
    """
    entry = {
        "desc": desc,
        "dsconf": dsconf,
        "owner": USER,
        "fcl": fcl_name,
        "code": str(code_tarball),
        "njobs": njobs,
        "outloc": {"*.art": "outstage", "*.root": "outstage"},
    }
    if events is not None:
        entry["events"] = events
        entry["run"] = run
    if memory_mb is not None:
        entry["memory"] = f"{memory_mb}MB"
    if input_data is not None:
        entry["input_data"] = input_data
        entry["inloc"] = inloc
    if resampler_name is not None:
        entry["resampler_name"] = resampler_name
    return entry


def write_entry(state_dir: Path, stage: str, entry: dict) -> Path:
    """state/<stage>_entry.json, as the one-element list json2jobdef reads."""
    out = state_dir / f"{stage}_entry.json"
    out.write_text(json.dumps([entry], indent=1) + "\n")
    return out
