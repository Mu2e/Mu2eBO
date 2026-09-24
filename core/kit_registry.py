"""Declared kits for schema-2 studies (generic-study design, Phase A).

A study names kits in three places: study["kits"], study["preflight"]["kit"]
and each step's "kit". This table says which names exist and which settings
each accepts, so a typo is a load error. Phase B adds the adapters that
implement the evaluator contract under these same names. STDLIB ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict


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


@dataclass(frozen=True)
class KitDecl:
    name: str
    study_keys: Dict[str, Callable]   # study["kits"][name]: every key required
    fixed_keys: Dict[str, Callable]   # a step's "fixed": each key optional
    uses_entries: bool                # step "entry" names a stage template
    step_kit: bool                    # may appear in evaluate[]
    check_kit: bool                   # may be study["preflight"]["kit"]


KITS: Dict[str, KitDecl] = {d.name: d for d in (
    KitDecl("prodtools",
            study_keys={"code_tarball": _path},
            fixed_keys={"njobs": _positive_int, "events_per_job": _positive_int,
                        "memory_mb": _positive_int, "quorum": _fraction},
            uses_entries=True, step_kit=True, check_kit=False),
    KitDecl("offline_preflight",
            study_keys={"musing": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
            fixed_keys={}, uses_entries=False, step_kit=False, check_kit=True),
    KitDecl("ce_sensitivity", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False),
    KitDecl("flash_edep_per_pot", study_keys={}, fixed_keys={},
            uses_entries=False, step_kit=True, check_kit=False),
)}


def validate_study_settings(kit: str, settings, where: str) -> dict:
    """study["kits"][kit]: an object holding exactly the declared keys."""
    decl = KITS[kit]
    if not isinstance(settings, dict):
        raise ValueError(f"{where}: must be an object, got {settings!r}")
    unknown = sorted(set(settings) - set(decl.study_keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; kit {kit!r} "
                         f"accepts {sorted(decl.study_keys)}")
    missing = sorted(set(decl.study_keys) - set(settings))
    if missing:
        raise ValueError(f"{where}: missing required key(s) {missing} for "
                         f"kit {kit!r}")
    return {k: decl.study_keys[k](v, f"{where}[{k}]")
            for k, v in settings.items()}


def validate_fixed(kit: str, fixed, where: str) -> dict:
    """A step's "fixed": any subset of the declared keys, each type-checked."""
    decl = KITS[kit]
    if not isinstance(fixed, dict):
        raise ValueError(f"{where}: must be an object, got {fixed!r}")
    unknown = sorted(set(fixed) - set(decl.fixed_keys))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; kit {kit!r} "
                         f"accepts {sorted(decl.fixed_keys)}")
    return {k: decl.fixed_keys[k](v, f"{where}[{k}]") for k, v in fixed.items()}
