"""Declared kits for schema-2 studies (generic-study design, Phase A).

A study names kits in three places: study["kits"], study["preflight"]["kit"]
and each step's "kit". This table says which names exist and which settings
each accepts, so a typo is a load error. The Python-adapter kits are declared
here; the native contract kits come from kits.toml. STDLIB ONLY.
"""
from __future__ import annotations

import math
import re
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


# prodtools builds a run's name from dot-separated parts, the config name
# among them, and its file names from the run's: a part may hold only
# letters, digits and _.
_RUN_NAME_PART = re.compile(r"[A-Za-z0-9_]+")


def bad_run_name_characters(text: str) -> list:
    """The characters of `text` a prodtools run-name part cannot hold
    (anything but letters, digits and _), sorted; empty when none."""
    return sorted(set(_RUN_NAME_PART.sub("", text)))


def config_name_problem(name: str):
    """Why `name` cannot be a config name, or None. Every kit that names a
    run after the config applies this one rule."""
    if not name:
        return "config name is empty"
    bad = bad_run_name_characters(name)
    if not bad:
        return None
    return (f"config name {name!r} has character(s) "
            f"{', '.join(repr(c) for c in bad)}; only letters, digits and _ "
            f"may appear, because the config is part of prodtools' "
            f"dot-separated run name")


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


def _dsconf(v, where):
    """A prodtools run label (json2jobdef's dsconf): one per config, so it
    holds {cfg}; with {cfg} filled it goes into prodtools' dot-separated
    run and file names, so it must pass the same rule as a config name
    (config_name_problem)."""
    if not isinstance(v, str) or "{cfg}" not in v:
        raise ValueError(f"{where}: must be a string containing {{cfg}} "
                         f"(each config needs its own run label), got {v!r}")
    filled = v.replace("{cfg}", "cfg")
    bad = bad_run_name_characters(filled)
    if bad:
        raise ValueError(f"{where}: {v!r} has character(s) "
                         f"{', '.join(repr(c) for c in bad)}; with {{cfg}} "
                         f"filled in only letters, digits and _ may appear, "
                         f"because the label is part of prodtools' "
                         f"dot-separated run and file names")
    return v


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


KITS: Dict[str, KitDecl] = {d.name: d for d in (
    KitDecl("prodtools",
            study_keys={"code_tarball": _path, "dsconf": _dsconf,
                        "fatal_log_codes": _string_list},
            fixed_keys={"njobs": _job_count, "events_per_job": _positive_int,
                        "memory_mb": _positive_int, "quorum": _fraction},
            required_fixed=frozenset({"quorum"}),
            uses_entries=True, step_kit=True, check_kit=False),
    KitDecl("offline_preflight",
            study_keys={"code_tarball": _path, "dumps_gdml": _flag,
                        "verifies_foil_gdml": _flag,
                        "checks_managed_overlap": _flag,
                        "require_zero_overlaps": _flag},
            fixed_keys={}, required_fixed=frozenset(), uses_entries=False,
            step_kit=False, check_kit=True),
    KitDecl("anakit",
            study_keys={"work_area": _path},
            fixed_keys={"analysis": _string, "input_correction": _number,
                        "cosmic_rate_per_s_per_mev": _number,
                        "dio_fraction": _number, "dio_table": _path,
                        "pot_per_electron": _number},
            required_fixed=frozenset({"analysis"}), uses_entries=False,
            step_kit=True, check_kit=False),
)}

# Settings two kits must agree on when a study uses both:
# (kit, key, other kit, other key, why).
MATCHING_SETTINGS = (
    ("offline_preflight", "code_tarball", "prodtools", "code_tarball",
     "the geometry pre-check must run the code the jobs run, or a geometry "
     "it passes can build differently on the grid (the env-divergence "
     "incidents)"),
)


def check_matching_settings(kits: dict, where: str) -> None:
    """Refuse a study whose kits disagree on a MATCHING_SETTINGS pair.
    `kits` is study["kits"] as written, so the message names the values
    the author wrote."""
    for kit, key, other, other_key, why in MATCHING_SETTINGS:
        if kit in kits and other in kits:
            mine, theirs = kits[kit].get(key), kits[other].get(other_key)
            if mine != theirs:
                raise ValueError(
                    f"{where}[kits.{kit}.{key}]: {mine!r} differs from "
                    f"kits.{other}.{other_key} {theirs!r}; the two must "
                    f"name the same file: {why}")


def check_offline_preflight_overlap_policy(kits: dict, where: str) -> None:
    """Refuse an offline_preflight study whose settings turn on the
    zero-overlap policy while the scan that enforces it is off. classify()
    (core/adapters/preflight_checks.py) reads require_zero_overlaps only
    INSIDE the `if checks_managed_overlap:` block, so
    require_zero_overlaps=true with checks_managed_overlap=false is
    silently never enforced -- a geometry with overlaps passes."""
    settings = kits.get("offline_preflight")
    if not isinstance(settings, dict):
        return
    if settings.get("require_zero_overlaps") and not settings.get(
            "checks_managed_overlap"):
        raise ValueError(
            f"{where}[kits.offline_preflight]: require_zero_overlaps=true "
            f"needs checks_managed_overlap=true; with the managed-overlap "
            f"scan off, classify() never reaches the require_zero_overlaps "
            f"check, so a geometry with overlaps would silently pass")


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
                   step_kit=True, check_kit=cfg.check)


_clash = sorted(set(NATIVE) & set(KITS))
if _clash:
    raise ValueError(f"kits.toml declares {_clash}, which core/kit_registry.py "
                     f"already declares as adapter kits")
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
