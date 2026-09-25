"""Declared kits for schema-2 studies (generic-study design, Phase A).

A study names kits in three places: study["kits"], study["preflight"]["kit"]
and each step's "kit". This table says which names exist and which settings
each accepts, so a typo is a load error. Phase B adds the native contract
kits from kits.toml (engine=True); Phase C flips the four pipeline kits to
engine=True when their adapters land. STDLIB ONLY.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict

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


# kits.toml names value types by these keys (kit_config.VALUE_TYPES).
VALIDATORS: Dict[str, Callable] = {
    "string": _string, "number": _number, "positive_int": _positive_int,
    "fraction": _fraction, "flag": _flag, "path": _path}


@dataclass(frozen=True)
class KitDecl:
    name: str
    study_keys: Dict[str, Callable]   # study["kits"][name]: every key required
    fixed_keys: Dict[str, Callable]   # a step's "fixed": each key optional
    uses_entries: bool                # step "entry" names a stage template
    step_kit: bool                    # may appear in evaluate[]
    check_kit: bool                   # may be study["preflight"]["kit"]
    engine: bool                      # runs on the contract engine
                                      # (graph.study_run); the four pipeline
                                      # kits stay False until Phase C gives
                                      # them adapters


KITS: Dict[str, KitDecl] = {d.name: d for d in (
    KitDecl("prodtools",
            study_keys={"code_tarball": _path},
            fixed_keys={"njobs": _positive_int, "events_per_job": _positive_int,
                        "memory_mb": _positive_int, "quorum": _fraction},
            uses_entries=True, step_kit=True, check_kit=False, engine=False),
    KitDecl("offline_preflight",
            study_keys={"musing": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
            fixed_keys={}, uses_entries=False, step_kit=False, check_kit=True,
            engine=False),
    KitDecl("ce_sensitivity", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False, engine=False),
    KitDecl("flash_edep_per_pot", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False, engine=False),
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
                   uses_entries=False, step_kit=True, check_kit=cfg.check,
                   engine=True)


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
