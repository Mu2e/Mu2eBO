"""kits.toml: the registry of native contract kits (generic-study design,
Phase B).

A kit that speaks the evaluator contract over MCP needs one entry here and
no Python. Every key is required and unknown keys are rejected (ADR-0002);
each error names the file, the kit and the key. `command` and `set` values
resolve only when a kit starts, so loading the registry never needs the
environment the kit will run in. STDLIB ONLY.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

if __package__:
    from core import paths
else:
    import paths

KITS_TOML = paths.REPO_ROOT / "kits.toml"
KEYS = ("command", "env_passthrough", "set", "study_keys", "fixed_keys",
        "accepts_lists", "check", "launch_stagger_s", "poll_s", "timeouts")
TIMEOUT_KEYS = ("start", "submit", "status", "results", "check", "describe",
                "cancel")
VALUE_TYPES = ("string", "number", "positive_int", "fraction", "flag", "path")
_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_KIT_NAME = re.compile(r"[a-z][a-z0-9_]*")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class KitConfigError(ValueError):
    """A kits.toml entry is malformed, or one of its values cannot be
    resolved in this environment."""


@dataclass(frozen=True)
class KitConfig:
    name: str
    command: Tuple[str, ...]
    env_passthrough: Tuple[str, ...]
    set_env: Dict[str, str]
    study_keys: Dict[str, str]      # study["kits"][name]: key -> value type
    fixed_keys: Dict[str, str]      # a step's "fixed": key -> value type
    accepts_lists: bool
    check: bool                     # offers the contract's `check` (preflight)
    launch_stagger_s: float         # gap between a campaign's child launches
    poll_s: Tuple[float, float]     # clamp on the kit's poll_ms hint
    timeouts: Dict[str, float]      # seconds, per contract call and "start"

    def resolve_command(self) -> list:
        return [resolve(v, self.name, f"command[{i}]")
                for i, v in enumerate(self.command)]

    def resolve_env(self, base: Dict[str, str]) -> Dict[str, str]:
        """`base` (the MCP SDK's short default allowlist) plus every
        env_passthrough variable, which must be set, plus `set`."""
        env = dict(base)
        for var in self.env_passthrough:
            value = os.environ.get(var)
            if not value:
                raise KitConfigError(
                    f"kit {self.name!r}: env_passthrough names ${var}, "
                    f"which is not set in this environment")
            env[var] = value
        for key, value in self.set_env.items():
            env[key] = resolve(value, self.name, f"set.{key}")
        return env


def resolve(value: str, kit: str, field: str) -> str:
    """${PYTHON} (the running interpreter), ${REPO_ROOT} and ${DATA_ROOT}
    (core/paths.py), else the environment variable of that name, which must
    be set and non-empty. No defaults."""
    def sub(m):
        var = m.group(1)
        if var == "PYTHON":
            return sys.executable
        if var == "REPO_ROOT":
            return str(paths.REPO_ROOT)
        if var == "DATA_ROOT":
            return str(paths.DATA_ROOT)
        got = os.environ.get(var)
        if not got:
            raise KitConfigError(
                f"kit {kit!r} {field}: ${{{var}}} is not set in this "
                f"environment")
        return got
    return _TOKEN.sub(sub, value)


def _need(ok, where: str, rule: str) -> None:
    if not ok:
        raise KitConfigError(f"{where}: {rule}")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _entry(name: str, raw, where: str) -> KitConfig:
    _need(_KIT_NAME.fullmatch(name), where,
          "a kit name is a lower-case identifier")
    _need(isinstance(raw, dict), where, "must be a table")
    missing = [k for k in KEYS if k not in raw]
    _need(not missing, where, f"missing required key(s) {missing}")
    unknown = sorted(set(raw) - set(KEYS))
    _need(not unknown, where,
          f"unknown key(s) {unknown}; accepted keys are {sorted(KEYS)}")

    command = raw["command"]
    _need(isinstance(command, list) and command
          and all(isinstance(c, str) and c for c in command),
          f"{where}.command", "must be a non-empty list of non-empty strings")
    passthrough = raw["env_passthrough"]
    _need(isinstance(passthrough, list)
          and all(isinstance(v, str) and _ENV_NAME.fullmatch(v)
                  for v in passthrough),
          f"{where}.env_passthrough",
          "must be a list of environment variable names")
    set_env = raw["set"]
    _need(isinstance(set_env, dict)
          and all(_ENV_NAME.fullmatch(k) and isinstance(v, str)
                  for k, v in set_env.items()),
          f"{where}.set", "must map environment variable names to strings")
    for key in ("study_keys", "fixed_keys"):
        table = raw[key]
        _need(isinstance(table, dict), f"{where}.{key}", "must be a table")
        for k, t in table.items():
            _need(t in VALUE_TYPES, f"{where}.{key}.{k}",
                  f"must be one of {list(VALUE_TYPES)}, got {t!r}")
    for key in ("accepts_lists", "check"):
        _need(isinstance(raw[key], bool), f"{where}.{key}",
              "must be true or false")
    stagger = raw["launch_stagger_s"]
    _need(_is_number(stagger) and stagger >= 0, f"{where}.launch_stagger_s",
          "must be a number >= 0")
    poll = raw["poll_s"]
    _need(isinstance(poll, list) and len(poll) == 2
          and all(_is_number(v) for v in poll) and 0 < poll[0] <= poll[1],
          f"{where}.poll_s", "must be [min, max] seconds with 0 < min <= max")
    timeouts = raw["timeouts"]
    _need(isinstance(timeouts, dict) and set(timeouts) == set(TIMEOUT_KEYS),
          f"{where}.timeouts", f"must set exactly {list(TIMEOUT_KEYS)}")
    for k, v in timeouts.items():
        _need(_is_number(v) and v > 0, f"{where}.timeouts.{k}",
              "must be a number of seconds > 0")
    return KitConfig(
        name=name, command=tuple(command), env_passthrough=tuple(passthrough),
        set_env=dict(set_env), study_keys=dict(raw["study_keys"]),
        fixed_keys=dict(raw["fixed_keys"]), accepts_lists=raw["accepts_lists"],
        check=raw["check"], launch_stagger_s=float(stagger),
        poll_s=(float(poll[0]), float(poll[1])),
        timeouts={k: float(v) for k, v in timeouts.items()})


def load_kit_configs(path: Path = KITS_TOML) -> Dict[str, KitConfig]:
    path = Path(path)
    if not path.exists():
        raise KitConfigError(f"{path}: the kit registry is missing")
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise KitConfigError(f"{path}: invalid TOML: {exc}") from None
    return {name: _entry(name, raw, f"{path}[{name}]")
            for name, raw in doc.items()}
