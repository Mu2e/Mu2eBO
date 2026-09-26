"""Declared kits for schema-2 studies (generic-study design, Phase A).

A study names kits in three places: study["kits"], study["preflight"]["kit"]
and each step's "kit". This table says which names exist and which settings
each accepts, so a typo is a load error. Phase B adds the native contract
kits from kits.toml (engine=True). Phase C gives the pipeline kits engine
support one by one; a kit either runner can drive has both flags. STDLIB
ONLY.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet

if __package__:
    from core.kit_config import load_kit_configs
else:
    from kit_config import load_kit_configs


def _positive_int(v, where):
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValueError(f"{where}: must be a positive int, got {v!r}")
    return v


def _fraction(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
        raise ValueError(f"{where}: must be a number in (0, 1], got {v!r}")
    return float(v)


def _flag(v, where):
    if not isinstance(v, bool):
        raise ValueError(f"{where}: must be true or false, got {v!r}")
    return v


def _path(v, where):
    if not isinstance(v, str) or not v:
        raise ValueError(f"{where}: must be a non-empty path string, got {v!r}")
    return v


def _string(v, where):
    if not isinstance(v, str):
        raise ValueError(f"{where}: must be a string, got {v!r}")
    return v


def _number(v, where):
    if (isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v)):
        raise ValueError(f"{where}: must be a finite number, got {v!r}")
    return float(v)


# prodtools' run_status lists at most this many jobs' outputs (INDEX_CAP in
# its mcp/src/prodtools_mcp/tools/runs.py): a larger step would read a
# silently truncated output list.
MAX_JOBS_PER_STEP = 200


def _job_count(v, where):
    _positive_int(v, where)
    if v > MAX_JOBS_PER_STEP:
        raise ValueError(f"{where}: at most {MAX_JOBS_PER_STEP} jobs per "
                         f"step, got {v}: prodtools run_status lists at most "
                         f"{MAX_JOBS_PER_STEP} jobs' outputs, so a larger "
                         f"step would read a truncated output list")
    return v


def _string_list(v, where):
    if not isinstance(v, list) or not all(isinstance(s, str) and s
                                          for s in v):
        raise ValueError(f"{where}: must be a list of non-empty strings, "
                         f"got {v!r}")
    return list(v)


# kits.toml names value types by these keys (kit_config.VALUE_TYPES).
VALIDATORS: Dict[str, Callable] = {
    "string": _string, "number": _number, "positive_int": _positive_int,
    "fraction": _fraction, "flag": _flag, "path": _path}


@dataclass(frozen=True)
class KitDecl:
    name: str
    study_keys: Dict[str, Callable]   # study["kits"][name]: every key required
    fixed_keys: Dict[str, Callable]   # a step's "fixed": each key optional ...
    required_fixed: FrozenSet[str]    # ... except these, which every step sets
    uses_entries: bool                # step "entry" names a stage template
    step_kit: bool                    # may appear in evaluate[]
    check_kit: bool                   # may be study["preflight"]["kit"]
    engine: bool                      # the contract engine (graph.study_run)
                                      # can drive it
    pipeline: bool                    # the old pipeline (graph.run) can
                                      # drive it; Phase C3 deletes this flag


KITS: Dict[str, KitDecl] = {d.name: d for d in (
    KitDecl("prodtools",
            study_keys={"code_tarball": _path,
                        "fatal_log_codes": _string_list},
            fixed_keys={"njobs": _job_count, "events_per_job": _positive_int,
                        "memory_mb": _positive_int, "quorum": _fraction},
            required_fixed=frozenset({"quorum"}),
            uses_entries=True, step_kit=True, check_kit=False,
            engine=True, pipeline=True),
    KitDecl("offline_preflight",
            study_keys={"musing": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
            fixed_keys={}, required_fixed=frozenset(), uses_entries=False,
            step_kit=False, check_kit=True, engine=False, pipeline=True),
    KitDecl("ce_sensitivity", study_keys={}, fixed_keys={},
            required_fixed=frozenset(), uses_entries=False, step_kit=True,
            check_kit=False, engine=False, pipeline=True),
    KitDecl("flash_edep_per_pot", study_keys={}, fixed_keys={},
            required_fixed=frozenset(), uses_entries=False, step_kit=True,
            check_kit=False, engine=False, pipeline=True),
)}

# Native contract kits: one kits.toml entry each, no Python. The engine calls
# their MCP tools directly (core/contract.py).
NATIVE = load_kit_configs()


def _native_decl(cfg) -> KitDecl:
    return KitDecl(cfg.name,
                   study_keys={k: VALIDATORS[t]
                               for k, t in cfg.study_keys.items()},
                   fixed_keys={k: VALIDATORS[t]
                               for k, t in cfg.fixed_keys.items()},
                   required_fixed=frozenset(), uses_entries=False,
                   step_kit=True, check_kit=cfg.check, engine=True,
                   pipeline=False)


_clash = sorted(set(NATIVE) & set(KITS))
if _clash:
    raise ValueError(f"kits.toml declares {_clash}, which core/kit_registry.py "
                     f"already declares as pipeline kits")
KITS.update({name: _native_decl(cfg) for name, cfg in NATIVE.items()})


def kits_of(study) -> set:
    """Every kit a study names: its steps' kits and its preflight kit."""
    names = {s.kit for s in study.steps}
    if study.preflight is not None:
        names.add(study.preflight["kit"])
    return names


def validate(kit: str, raw, table: Dict[str, Callable], where: str, *,
             required: bool) -> dict:
    """study["kits"][kit] (table=study_keys, required=True: exactly the
    declared keys) or a step's "fixed" (table=fixed_keys, required=False:
    any subset). Each value is type-checked by its table entry."""
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: must be an object, got {raw!r}")
    unknown = sorted(set(raw) - set(table))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; kit {kit!r} "
                         f"accepts {sorted(table)}")
    missing = sorted(set(table) - set(raw))
    if required and missing:
        raise ValueError(f"{where}: missing required key(s) {missing} for "
                         f"kit {kit!r}")
    return {k: table[k](v, f"{where}[{k}]") for k, v in raw.items()}
