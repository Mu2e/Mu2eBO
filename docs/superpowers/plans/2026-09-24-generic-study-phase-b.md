# Generic Studies, Phase B: Contract Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A study whose evaluation sits behind MCP kits that speak the evaluator contract runs end to end, from its JSON file alone. The acceptance test is a Branin–Currin campaign on `toykit`: 2 objectives, 1 constraint, q = 2, 8 evaluations, in under a minute in CI.

**Architecture:** Kits that speak the contract (`submit` / `status` / `results`, plus optional `check` / `describe` / `cancel`) are listed in a new `kits.toml` and reached through a synchronous stdio MCP client (`core/kits.py`). `core/contract.py` validates every reply and wraps kits behind one interface. The per-point graph (`graph/study_graph.py`) is derive → render → preflight → `run_steps` → score. `run_steps` (`core/scheduler.py`) is ONE node that starts each step as soon as its own `files_from` steps finish, so LangGraph's superstep barrier never holds back a dependent chain. Scoring (`core/score.py`) appends a v2 row that carries `measure_sha`, and a board refuses a row measured a different way. The campaign runner (`graph/study_loop.py`) reuses `graph/pool.py`'s rolling pool. The foilspf pipeline (`graph.run`, `graph.closed_loop`, `core/pipeline.py`) is untouched: a study runs on the engine only when every kit it names is an engine kit, and Phase C moves foilspf over.

**Tech Stack:** Python 3.12 (ana 2.8.0, `$AUTORESEARCH_PYTHON`), official `mcp` SDK 2.0.0 (already in ana 2.8.0), LangGraph, `tomllib` (stdlib), surrokit via `core/botorch_predict.py`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-23-generic-study-design.md` (amended 2026-09-24). Also read `docs/superpowers/specs/2026-09-22-kit-seam-design.md` §1–2 and §5 (the kit client, `kits.toml`, trace). Where they disagree, the generic-study design wins: read-only calls DO get bounded retries.

**Branch:** create `generic-study-phase-b` from `generic-study-phase-a` (PR #34). Phase A must be merged or this branch rebased onto `main` after it merges.

## Global Constraints

- ADR-0002: every key required, unknown keys rejected, every error names the file, the field and the rule. No silent fallbacks, no defaults. A missing number is never replaced by 0.
- The suite stays green at every commit: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` (`source activate.sh` first if `$AUTORESEARCH_PYTHON` is unset).
- `tests/test_no_hardcoded_paths.py` scans `git ls-files` only: `git add` new files BEFORE running the suite.
- Golden parity stays OK: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b c d e` (c takes ~4 min of local G4; run it once, at the end of Task 6 and Task 10). Nothing in this plan changes the pipeline's rows, geometry or picks.
- MCP: stdio only, the `mcp` 2.0.0 SDK already in ana 2.8.0. No new dependencies, no http transport, no Tasks extension.
- Every kit call carries `_meta["gov.fnal.mu2e/workflow"] = "<campaign>/<config>/<step>"` and appends one line to `GRAPH_DATA/<campaign>/kit_trace.jsonl`.
- Handles are deterministic: `<config>.<step>`.
- Do not change `graph/run.py`, `graph/closed_loop.py`, `graph/build.py`, `graph/nodes.py`, `core/pipeline.py`, `core/harvest.py` or `core/bo_driver.py`. The only shared-code edits are the ones a task names: `graph/pool.py` (a name-allocation helper), `core/botorch_predict.py` and `surrogate/adapter.py` (history reads), `core/modes.py`, `core/study.py`, `core/study_compat.py`, `core/kit_registry.py`, `core/geom_template.py`, `core/leaderboard.py`.
- Files that are generic end to end name no physics quantity (`tests/test_generic_core.py` STRICT gate). Task 10 adds every new core/graph file to that gate.
- Scratch and large outputs live under `/exp/mu2e/data/users/<you>/` or a test's `tempfile` dir, never `$HOME`. Tests must never write under the real `DATA_ROOT`: in-process tests pass explicit paths; subprocess tests set `AUTORESEARCH_DATA_ROOT` to a temp dir.
- Every commit message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```
- Stage explicit paths only (`git add <path>`); never `git add -A`, `.` or `-u`. The working tree has unrelated uncommitted files under `docs/`.

## Review Focus

These five conditions follow from the spec but no happy-path test exercises them. Each is pinned by a test in the task named.

1. **A kit whose server can't start** (a `kits.toml` command or `env_passthrough` naming an unset variable, or a server that exits at start-up): the campaign refuses at launch and names the kit and the variable. It never launches children that all die. → Task 4 (`check_kits` names the kit and the variable) and Task 10 (any `check_kits` problem makes `study_loop` refuse and launch nothing).
2. **A kit server that dies between polls:** the next call respawns it and the step carries on; read-only calls retry up to 3 times. → Task 3 (respawn) and Task 4 (retry policy).
3. **Relaunching under the same `--name-prefix` while a killed runner's children still run:** no name is launched twice and each point lands at most one row. → Task 10.
4. **Editing how a study measures (a kit setting, a `fixed` value, a metric) and appending to its existing v2 board:** the append is refused with the row quarantined, never mixed into the GP history. → Task 6 and Task 9.
5. **A hand-run point with x outside the knob box, or of the wrong length:** refused before any submit. → Task 9.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `kits.toml` | new | Registry of native contract kits (one entry: `toykit`) |
| `core/kit_config.py` | new | Parse `kits.toml` → `KitConfig`; resolve `${...}` tokens when a kit starts |
| `core/kit_registry.py` | modify | Add `engine` flag, value-type validators, native declarations from `kits.toml`, `kits_of(study)` |
| `core/kits.py` | new | `KitClient`: synchronous stdio MCP client (timeouts, respawn, meta, trace) |
| `core/contract.py` | new | Reply validation, `NativeKit`, `KitSet`, adapter registry, `open_kit`, `check_kits`, `launch_stagger` |
| `core/study.py` | modify | `layout` v2, `measure_basis` + `measure_sha`, stage-template resolution |
| `core/geom_template.py` | modify | `GeomTemplate.derived_env(x)` (render uses it) |
| `core/modes.py` | modify | `runs_on_engine`, `ENGINE`; `SPECS` built for pipeline studies only |
| `core/study_compat.py` | modify | Refuse a v2 board |
| `core/leaderboard.py` | modify | v2 layout: meta columns, idempotent-by-name append, `measure_sha` refusal |
| `core/boards.py` | new | `board_for(study)`: a study's live board plus its archive |
| `core/botorch_predict.py` | modify | `history_points(name)`: engine studies read their board |
| `surrogate/adapter.py` | modify | Board summary through `history_points` |
| `core/scheduler.py` | new | `run_steps`: the step DAG, one thread per ready step, state-file resume |
| `core/score.py` | new | Objectives and extra metrics from step results → summary files + one row |
| `graph/study_graph.py` | new | Per-point LangGraph: derive → render → preflight → run_steps → score |
| `graph/study_run.py` | new | Child CLI: one point (`python -m graph.study_run`) |
| `graph/pool.py` | modify | `next_free_name` helper shared by both pick sources |
| `graph/study_loop.py` | new | Campaign CLI over the rolling pool (`python -m graph.study_loop`) |
| `tests/toykit.py` | new | The reference contract kit (MCP server + `ToyStore`) |
| `tests/engine_fixtures.py` | new | `toy_doc`, `write_study`, `toy_config`, `engine_env` helpers |
| `tests/fixtures/engine_studies/branin.json` | new | The acceptance study |
| `tests/test_kit_config.py`, `test_toykit.py`, `test_kits.py`, `test_contract.py`, `test_study_engine.py`, `test_scheduler.py`, `test_score.py`, `test_study_run.py`, `test_study_loop.py` | new | Tests |
| `tests/test_boards.py` | new | `board_for`; engine studies train on their board |
| `tests/test_leaderboard.py`, `tests/test_generic_core.py`, `tests/test_pool.py` | modify | v2 board tests; STRICT gate list; `next_free_name` |

---

### Task 1: `kits.toml` and native kit declarations

**Files:**
- Create: `kits.toml`
- Create: `core/kit_config.py`
- Modify: `core/kit_registry.py`
- Create: `tests/engine_fixtures.py`
- Test: `tests/test_kit_config.py`

**Interfaces:**
- Produces: `kit_config.KitConfig` (fields `name, command, env_passthrough, set_env, study_keys, fixed_keys, accepts_lists, check, launch_stagger_s, poll_s, timeouts`; methods `resolve_command() -> list[str]`, `resolve_env(base: dict) -> dict`), `kit_config.KitConfigError(ValueError)`, `kit_config.load_kit_configs(path=KITS_TOML) -> dict[str, KitConfig]`, `kit_config.KEYS`, `kit_config.TIMEOUT_KEYS`, `kit_config.VALUE_TYPES`.
- Produces: `kit_registry.KitDecl.engine: bool`, `kit_registry.NATIVE: dict[str, KitConfig]`, `kit_registry.VALIDATORS: dict[str, Callable]`, `kit_registry.kits_of(study) -> set[str]`. `kit_registry.KITS` now also holds one `KitDecl` per `kits.toml` entry (`engine=True`, `uses_entries=False`, `step_kit=True`, `check_kit=cfg.check`).
- Produces (tests): `engine_fixtures.toy_doc(name="toystudy", layout="v1") -> dict`, `engine_fixtures.write_study(doc, directory) -> Path`.

- [ ] **Step 1: Write `kits.toml`**

```toml
# Native contract kits (docs/superpowers/specs/2026-09-23-generic-study-design.md,
# "The evaluator contract"). A kit that speaks submit / status / results over
# MCP needs only an entry here: the engine calls its tools directly. Every key
# is required and unknown keys are rejected (ADR-0002). Tokens in `command`
# and `set`: ${PYTHON} (the running interpreter), ${REPO_ROOT} and
# ${DATA_ROOT} (core/paths.py), and ${NAME} for any environment variable,
# which must be set. They resolve when the kit starts, never at import.

[toykit]
# The reference implementation and the CI engine: tests/toykit.py.
command = ["${PYTHON}", "${REPO_ROOT}/tests/toykit.py"]
env_passthrough = []
set = { TOYKIT_STATE_DIR = "${DATA_ROOT}/toykit" }
study_keys = { function = "string" }
fixed_keys = { delay_s = "number", fail = "string", submit_sleep_s = "number" }
accepts_lists = false
check = true
launch_stagger_s = 0
poll_s = [0.1, 2.0]
timeouts = { start = 60, submit = 30, status = 30, results = 30, check = 30, describe = 30, cancel = 30 }
```

- [ ] **Step 2: Write the failing tests** — `tests/engine_fixtures.py` and `tests/test_kit_config.py`

`tests/engine_fixtures.py`:

```python
"""Builders shared by the engine tests: a minimal study on toykit, its
file, and (Task 3 on) a toykit KitConfig that writes under a temp dir."""
import json
from pathlib import Path

ENGINE_STUDIES = Path(__file__).resolve().parent / "fixtures" / "engine_studies"


def toy_doc(name="toystudy", layout="v1"):
    """One toykit step, Branin and Currin as the two objectives, Currin
    constrained. Tests mutate the returned dict freely."""
    return {
        "schema": 2,
        "name": name,
        "note": "engine test study on toykit",
        "knobs": [
            {"name": "x1", "type": "real", "min": -5.0, "max": 10.0,
             "unit": "", "fmt": "{:.6f}"},
            {"name": "x2", "type": "real", "min": 0.0, "max": 15.0,
             "unit": "", "fmt": "{:.6f}"},
        ],
        "derive": {"consts": {}, "exprs": {}, "profiles": {}},
        "geom": None,
        "kits": {"toykit": {"function": "branin_currin"}},
        "preflight": None,
        "evaluate": [
            {"step": "toy", "kit": "toykit", "entry": None, "files": [],
             "files_from": [], "params": {"x1": "x1", "x2": "x2"},
             "fixed": {"delay_s": 0.0}},
        ],
        "objectives": [
            {"name": "branin", "metric": "toy.branin", "direction": "min",
             "transform": "none", "noise": 0.01, "fmt": "{:.6f}"},
            {"name": "currin", "metric": "toy.currin", "direction": "min",
             "transform": "log10", "noise": 0.01, "fmt": "{:.6f}"},
        ],
        "constraints": [{"name": "currin", "max": 10.0, "k_sigma": 1.0}],
        "extra_metrics": [],
        "extra_columns": [],
        "leaderboard": {"file": f"leaderboards/leaderboard_{name}.tsv",
                        "layout": layout, "context": []},
    }


def write_study(doc, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['name']}.json"
    path.write_text(json.dumps(doc, indent=1))
    return path
```

`tests/test_kit_config.py`:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import kit_config as kc  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402

sys.path.insert(0, str(ROOT))
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

GOOD = """
[demo]
command = ["${PYTHON}", "${REPO_ROOT}/x.py", "--data", "${DATA_ROOT}/d"]
env_passthrough = ["DEMO_TOKEN"]
set = { DEMO_DIR = "${DATA_ROOT}/demo" }
study_keys = { mode = "string" }
fixed_keys = { n = "positive_int" }
accepts_lists = false
check = true
launch_stagger_s = 0
poll_s = [0.5, 5]
timeouts = { start = 60, submit = 30, status = 30, results = 30, check = 30, describe = 30, cancel = 30 }
"""


class _Toml(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kits.toml"
            path.write_text(text)
            return kc.load_kit_configs(path)

    def assertRejects(self, text, *needles):
        with self.assertRaises(kc.KitConfigError) as cm:
            self.load(text)
        for n in needles:
            self.assertIn(n, str(cm.exception))


class TestLoad(_Toml):
    def test_good_entry(self):
        cfg = self.load(GOOD)["demo"]
        self.assertEqual(cfg.poll_s, (0.5, 5.0))
        self.assertTrue(cfg.check)
        self.assertEqual(cfg.timeouts["submit"], 30.0)
        self.assertEqual(cfg.fixed_keys, {"n": "positive_int"})

    def test_every_key_is_required(self):
        for key in kc.KEYS:
            text = "\n".join(line for line in GOOD.splitlines()
                             if not line.startswith(key + " "))
            with self.subTest(key=key):
                self.assertRejects(text, "[demo]", key)

    def test_unknown_key(self):
        self.assertRejects(GOOD + 'color = "red"\n', "unknown key", "color")

    def test_bad_value_type_name(self):
        self.assertRejects(GOOD.replace('"positive_int"', '"posint"'),
                           "fixed_keys.n", "posint")

    def test_timeouts_must_name_every_call(self):
        self.assertRejects(GOOD.replace(", cancel = 30", ""),
                           "timeouts", "cancel")

    def test_poll_bounds_must_be_ordered(self):
        self.assertRejects(GOOD.replace("[0.5, 5]", "[5, 0.5]"), "poll_s")

    def test_invalid_toml_names_the_file(self):
        self.assertRejects("[demo\n", "invalid TOML")


class TestResolve(_Toml):
    def test_tokens(self):
        cmd = self.load(GOOD)["demo"].resolve_command()
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], f"{paths.REPO_ROOT}/x.py")
        self.assertEqual(cmd[3], f"{paths.DATA_ROOT}/d")

    def test_env_is_base_plus_passthrough_plus_set(self):
        cfg = self.load(GOOD)["demo"]
        with mock.patch.dict(os.environ, {"DEMO_TOKEN": "t"}):
            env = cfg.resolve_env({"HOME": "/h"})
        self.assertEqual(env, {"HOME": "/h", "DEMO_TOKEN": "t",
                               "DEMO_DIR": f"{paths.DATA_ROOT}/demo"})

    def test_unset_passthrough_names_kit_and_variable(self):
        cfg = self.load(GOOD)["demo"]
        with mock.patch.dict(os.environ):
            os.environ.pop("DEMO_TOKEN", None)
            with self.assertRaises(kc.KitConfigError) as cm:
                cfg.resolve_env({})
        self.assertIn("'demo'", str(cm.exception))
        self.assertIn("DEMO_TOKEN", str(cm.exception))

    def test_unset_token_in_command(self):
        cfg = self.load(GOOD.replace("${PYTHON}", "${NO_SUCH_VAR_XYZ}"))["demo"]
        with self.assertRaises(kc.KitConfigError) as cm:
            cfg.resolve_command()
        self.assertIn("NO_SUCH_VAR_XYZ", str(cm.exception))


class TestRepoRegistry(unittest.TestCase):
    def test_repo_kits_toml_loads(self):
        self.assertIn("toykit", kc.load_kit_configs())

    def test_value_types_match_the_validators(self):
        self.assertEqual(set(kc.VALUE_TYPES), set(kit_registry.VALIDATORS))

    def test_native_kits_are_engine_kits(self):
        decl = kit_registry.KITS["toykit"]
        self.assertTrue(decl.engine)
        self.assertTrue(decl.step_kit)
        self.assertTrue(decl.check_kit)
        self.assertFalse(decl.uses_entries)

    def test_pipeline_kits_are_not_engine_kits(self):
        for name in ("prodtools", "offline_preflight", "ce_sensitivity",
                     "flash_edep_per_pot"):
            with self.subTest(kit=name):
                self.assertFalse(kit_registry.KITS[name].engine)


class TestNativeKitInStudies(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)

    def load(self, doc):
        return st.load_study_file(write_study(doc, self.dir))

    def assertRejects(self, doc, *needles):
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_a_toykit_study_loads(self):
        s = self.load(toy_doc())
        self.assertEqual(s.steps[0].kit, "toykit")
        self.assertEqual(kit_registry.kits_of(s), {"toykit"})

    def test_unknown_kit_setting(self):
        doc = toy_doc()
        doc["kits"]["toykit"]["color"] = "red"
        self.assertRejects(doc, "kits.toykit", "color")

    def test_missing_kit_setting(self):
        doc = toy_doc()
        doc["kits"]["toykit"] = {}
        self.assertRejects(doc, "kits.toykit", "function")

    def test_fixed_value_type(self):
        doc = toy_doc()
        doc["evaluate"][0]["fixed"]["delay_s"] = "slow"
        self.assertRejects(doc, "delay_s", "number")

    def test_native_kit_takes_no_entry(self):
        doc = toy_doc()
        doc["evaluate"][0]["entry"] = "toy"
        self.assertRejects(doc, "entry")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kit_config -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kit_config'`.

- [ ] **Step 4: Write `core/kit_config.py`**

```python
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
```

- [ ] **Step 5: Extend `core/kit_registry.py`**

Add after the existing imports (`from dataclasses import dataclass`, `from typing import Callable, Dict`):

```python
import math

if __package__:
    from core.kit_config import load_kit_configs
else:
    from kit_config import load_kit_configs
```

Add two validators after `_path`:

```python
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
```

Add a field at the end of `KitDecl`:

```python
    engine: bool                      # runs on the contract engine
                                      # (graph.study_run); the four pipeline
                                      # kits stay False until Phase C gives
                                      # them adapters
```

Pass `engine=False` in each of the four existing `KitDecl(...)` calls. Then add after `KITS`:

```python
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
```

Update the module docstring's last sentence to: `Phase B adds the native contract kits from kits.toml (engine=True); Phase C flips the four pipeline kits to engine=True when their adapters land.`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `git add kits.toml core/kit_config.py core/kit_registry.py tests/engine_fixtures.py tests/test_kit_config.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kit_config -v`
Expected: all PASS.

- [ ] **Step 7: Run the whole suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK. If a test enumerates `kit_registry.KITS` and now also sees `toykit`, make it filter on `not d.engine` (the pipeline kits) and say so in the commit body.

- [ ] **Step 8: Commit**

```bash
git add kits.toml core/kit_config.py core/kit_registry.py tests/engine_fixtures.py tests/test_kit_config.py
git commit -m "feat(kits): kits.toml registry of native contract kits

A kit that speaks the evaluator contract needs one kits.toml entry and no
Python. kit_registry declares each entry as an engine kit, so studies can
name it and its settings and fixed values are type-checked at load.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 2: `toykit`, the reference contract kit

**Files:**
- Create: `tests/toykit.py`
- Test: `tests/test_toykit.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (stdlib + `mcp`).
- Produces: `tests/toykit.py` runnable as `"$PYTHON" tests/toykit.py` (stdio MCP server named `toykit`, version `"1"`), with tools `submit(name, params, files, inputs)`, `status(handle)`, `results(handle)`, `check(name, params, files, inputs)`, `describe()`, `cancel(handle)`, and debug tools `debug_env(names)`, `debug_meta()`, `debug_sleep(seconds)`, `debug_exit()`. Importable pieces: `ToyStore(root, clock=time.time)`, `branin(x1, x2)`, `currin(x1, x2)`, `VERSION`, `PARAMS`, `METRICS`, `FAILS`.
- `ToyStore.submit` returns `(reply, created)`; a NEW job appends `{"name": ...}` to `<root>/submits.jsonl` (tests count double submits there).
- Params toykit reads: `x1`, `x2`, `function` (`branin_currin` | `reject`), `delay_s`, `fail` (`failed` | `cancelled` | `bad_state` | `missing_metric` | `nonpositive`), `submit_sleep_s`. Metrics: `branin`, `currin`, `n_inputs`.

- [ ] **Step 1: Write the failing tests** — `tests/test_toykit.py`

```python
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests import toykit  # noqa: E402

P = {"x1": 1.0, "x2": 2.0, "function": "branin_currin"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Store(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.store = toykit.ToyStore(self.root, clock=self.clock)

    def submits(self):
        path = self.root / "submits.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln)["name"] for ln in path.read_text().splitlines()]


class TestFunctions(unittest.TestCase):
    def test_branin_global_minimum(self):
        self.assertAlmostEqual(toykit.branin(math.pi, 2.275), 0.397887, places=5)

    def test_currin_at_the_centre(self):
        # u1 = u2 = 0.5: (1 - e^-1) * 1868.5 / 159.5
        self.assertAlmostEqual(toykit.currin(2.5, 7.5), 7.405, places=3)

    def test_currin_is_finite_and_positive_on_the_x2_zero_edge(self):
        v = toykit.currin(0.0, 0.0)
        self.assertTrue(math.isfinite(v) and v > 0)


class TestJobs(_Store):
    def test_job_completes_after_its_delay(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        self.assertEqual(self.store.status("c.toy")["state"], "working")
        self.clock.t += 5
        st = self.store.status("c.toy")
        self.assertEqual(st["state"], "completed")
        self.assertEqual(set(st), {"state", "message", "poll_ms", "progress"})

    def test_results(self):
        self.store.submit("c.toy", P, [], [{"name": "a", "uri": "file:///a",
                                            "kind": "text"}])
        res = self.store.results("c.toy")
        self.assertAlmostEqual(res["metrics"]["branin"], toykit.branin(1, 2))
        self.assertAlmostEqual(res["metrics"]["currin"], toykit.currin(1, 2))
        self.assertEqual(res["metrics"]["n_inputs"], 1.0)
        self.assertTrue(res["files"][0]["uri"].startswith("file://"))

    def test_same_submit_is_idempotent(self):
        _, created = self.store.submit("c.toy", P, [], [])
        _, again = self.store.submit("c.toy", P, [], [])
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(self.submits(), ["c.toy"])

    def test_same_name_different_params_is_refused(self):
        self.store.submit("c.toy", P, [], [])
        with self.assertRaises(ValueError) as cm:
            self.store.submit("c.toy", dict(P, x1=3.0), [], [])
        self.assertIn("different", str(cm.exception))

    def test_results_before_completion_is_refused(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        with self.assertRaises(ValueError):
            self.store.results("c.toy")

    def test_unknown_handle(self):
        with self.assertRaises(ValueError) as cm:
            self.store.status("nope")
        self.assertIn("no job 'nope'", str(cm.exception))

    def test_unknown_function_and_fail_are_refused(self):
        with self.assertRaises(ValueError):
            self.store.submit("a.t", dict(P, function="rosenbrock"), [], [])
        with self.assertRaises(ValueError):
            self.store.submit("b.t", dict(P, fail="sometimes"), [], [])

    def test_cancel(self):
        self.store.submit("c.toy", dict(P, delay_s=5), [], [])
        self.assertEqual(self.store.cancel("c.toy"), {"state": "cancelled"})
        self.assertEqual(self.store.status("c.toy")["state"], "cancelled")


class TestFailures(_Store):
    def test_status_failures(self):
        for fail, state in (("failed", "failed"), ("cancelled", "cancelled"),
                            ("bad_state", "bogus")):
            with self.subTest(fail=fail):
                self.store.submit(f"{fail}.t", dict(P, fail=fail), [], [])
                self.assertEqual(self.store.status(f"{fail}.t")["state"], state)

    def test_missing_metric(self):
        self.store.submit("m.t", dict(P, fail="missing_metric"), [], [])
        self.assertNotIn("currin", self.store.results("m.t")["metrics"])

    def test_nonpositive_metric(self):
        self.store.submit("n.t", dict(P, fail="nonpositive"), [], [])
        self.assertEqual(self.store.results("n.t")["metrics"]["currin"], 0.0)


class TestCheckAndDescribe(unittest.TestCase):
    def test_check(self):
        self.assertTrue(toykit.ToyStore.check("c.pre", P, [], [])["ok"])
        bad = toykit.ToyStore.check("c.pre", dict(P, function="reject"), [], [])
        self.assertFalse(bad["ok"])
        self.assertIn("reject", bad["message"])

    def test_describe(self):
        d = toykit.ToyStore.describe()
        self.assertEqual(d, {"params": list(toykit.PARAMS),
                             "metrics": list(toykit.METRICS),
                             "accepts_lists": False})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_toykit -v`
Expected: FAIL with `ImportError: cannot import name 'toykit'`.

- [ ] **Step 3: Write `tests/toykit.py`**

```python
#!/usr/bin/env python3
"""toykit: the reference contract kit and the CI engine (generic-study
design, "toykit"). A native MCP kit with the contract tools submit, status,
results, check, describe and cancel, plus debug_* tools the kit-client
tests use.

Jobs live on disk under $TOYKIT_STATE_DIR (kits.toml sets it under
DATA_ROOT), so a restarted child talking to a fresh server process finds
the job it submitted before it was killed. A job completes delay_s seconds
after its submit; `fail` picks a failure (failed | cancelled | bad_state |
missing_metric | nonpositive). Functions: branin_currin (Branin and
Currin on x1 in [-5, 10], x2 in [0, 15]) and reject (the check fails).
Run as a script it serves stdio; imported, it exposes ToyStore.

No `from __future__ import annotations` here: the MCP SDK evaluates tool
annotations against module globals, and Context is imported inside
make_server.
"""
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "1"
FUNCTIONS = ("branin_currin", "reject")
FAILS = ("failed", "cancelled", "bad_state", "missing_metric", "nonpositive")
PARAMS = ("x1", "x2", "function", "delay_s", "fail", "submit_sleep_s")
METRICS = ("branin", "currin", "n_inputs")
POLL_MS = 100


def branin(x1: float, x2: float) -> float:
    b, c, t = 5.1 / (4 * math.pi ** 2), 5 / math.pi, 1 / (8 * math.pi)
    return (x2 - b * x1 ** 2 + c * x1 - 6) ** 2 + 10 * (1 - t) * math.cos(x1) + 10


def currin(x1: float, x2: float) -> float:
    """Currin's function on the unit square, mapped from the Branin box."""
    u1, u2 = (x1 + 5) / 15, x2 / 15
    factor = 1.0 if u2 == 0 else 1 - math.exp(-1 / (2 * u2))
    num = 2300 * u1 ** 3 + 1900 * u1 ** 2 + 2092 * u1 + 60
    den = 100 * u1 ** 3 + 500 * u1 ** 2 + 4 * u1 + 20
    return factor * num / den


class ToyStore:
    """The kit's jobs, one JSON file each. submits.jsonl logs every NEW job,
    which is where the tests count double submits."""

    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        (self.root / "out").mkdir(parents=True, exist_ok=True)

    def _path(self, handle: str) -> Path:
        return self.root / "jobs" / f"{handle}.json"

    def _load(self, handle: str) -> dict:
        path = self._path(handle)
        if not path.exists():
            raise ValueError(f"toykit: no job {handle!r}")
        return json.loads(path.read_text())

    def _save(self, job: dict) -> None:
        path = self._path(job["name"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job))
        tmp.replace(path)

    def submit(self, name, params, files, inputs):
        """(reply, created). Idempotent by name: the same name with the same
        params, files and inputs returns the existing handle; different ones
        are refused."""
        if params.get("function") not in FUNCTIONS:
            raise ValueError(f"toykit: unknown function "
                             f"{params.get('function')!r}; choose from "
                             f"{list(FUNCTIONS)}")
        fail = params.get("fail")
        if fail is not None and fail not in FAILS:
            raise ValueError(f"toykit: unknown fail {fail!r}; choose from "
                             f"{list(FAILS)}")
        job = {"name": name, "params": params, "files": files, "inputs": inputs}
        if self._path(name).exists():
            old = self._load(name)
            if {k: old[k] for k in job} != job:
                raise ValueError(f"toykit: {name!r} was already submitted "
                                 f"with different params, files or inputs")
            return {"handle": name}, False
        job.update(submitted_at=self.clock(), cancelled=False)
        self._save(job)
        with open(self.root / "submits.jsonl", "a") as f:
            f.write(json.dumps({"name": name}) + "\n")
        return {"handle": name}, True

    @staticmethod
    def _state(state: str, message: str) -> dict:
        return {"state": state, "message": message, "poll_ms": POLL_MS,
                "progress": None}

    def status(self, handle: str) -> dict:
        job = self._load(handle)
        params, fail = job["params"], job["params"].get("fail")
        if job["cancelled"] or fail == "cancelled":
            return self._state("cancelled", "toykit: cancelled")
        if fail == "failed":
            return self._state("failed", "toykit: asked to fail")
        if fail == "bad_state":
            return self._state("bogus", "toykit: a state outside the contract")
        elapsed = self.clock() - job["submitted_at"]
        done = elapsed >= float(params.get("delay_s", 0.0))
        return self._state("completed" if done else "working", "")

    def results(self, handle: str) -> dict:
        state = self.status(handle)["state"]
        if state != "completed":
            raise ValueError(f"toykit: {handle!r} is {state}, not completed")
        job = self._load(handle)
        params = job["params"]
        x1, x2 = float(params["x1"]), float(params["x2"])
        metrics = {"branin": branin(x1, x2), "currin": currin(x1, x2),
                   "n_inputs": float(len(job["inputs"]))}
        if params.get("fail") == "missing_metric":
            del metrics["currin"]
        if params.get("fail") == "nonpositive":
            metrics["currin"] = 0.0
        out = self.root / "out" / f"{handle}.txt"
        out.write_text(json.dumps(metrics))
        return {"metrics": metrics,
                "files": [{"name": "out", "uri": out.resolve().as_uri(),
                           "kind": "text"}],
                "metadata": {"function": params["function"]}}

    def cancel(self, handle: str) -> dict:
        job = self._load(handle)
        job["cancelled"] = True
        self._save(job)
        return {"state": "cancelled"}

    @staticmethod
    def check(name, params, files, inputs) -> dict:
        if params.get("function") == "reject":
            return {"ok": False,
                    "message": "toykit: function 'reject' fails the check"}
        return {"ok": True, "message": ""}

    @staticmethod
    def describe() -> dict:
        return {"params": list(PARAMS), "metrics": list(METRICS),
                "accepts_lists": False}


def make_server(store: ToyStore):
    from mcp.server.mcpserver import Context, MCPServer

    server = MCPServer(name="toykit", version=VERSION)

    @server.tool(structured_output=True)
    async def submit(name: str, params: dict[str, Any],
                     files: list[dict[str, Any]],
                     inputs: list[dict[str, Any]]) -> dict[str, Any]:
        reply, created = store.submit(name, params, files, inputs)
        sleep = float(params.get("submit_sleep_s", 0.0))
        if created and sleep:
            # Recorded BEFORE the sleep: a client that times out and
            # re-submits finds the job and gets the handle at once.
            await asyncio.sleep(sleep)
        return reply

    @server.tool(structured_output=True)
    def status(handle: str) -> dict[str, Any]:
        return store.status(handle)

    @server.tool(structured_output=True)
    def results(handle: str) -> dict[str, Any]:
        return store.results(handle)

    @server.tool(structured_output=True)
    def check(name: str, params: dict[str, Any], files: list[dict[str, Any]],
              inputs: list[dict[str, Any]]) -> dict[str, Any]:
        return store.check(name, params, files, inputs)

    @server.tool(structured_output=True)
    def describe() -> dict[str, Any]:
        return store.describe()

    @server.tool(structured_output=True)
    def cancel(handle: str) -> dict[str, Any]:
        return store.cancel(handle)

    @server.tool(structured_output=True)
    def debug_env(names: list[str]) -> dict[str, Any]:
        return {n: os.environ.get(n) for n in names}

    @server.tool(structured_output=True)
    def debug_meta(ctx: Context) -> dict[str, Any]:
        return {"meta": dict(ctx.request_context.meta or {})}

    @server.tool(structured_output=True)
    async def debug_sleep(seconds: float) -> dict[str, Any]:
        await asyncio.sleep(seconds)
        return {"slept": seconds}

    @server.tool(structured_output=True)
    def debug_exit() -> dict[str, Any]:
        os._exit(3)

    return server


def main() -> int:
    root = os.environ.get("TOYKIT_STATE_DIR")
    if not root:
        sys.stderr.write("toykit: TOYKIT_STATE_DIR is not set "
                         "(kits.toml sets it)\n")
        return 2
    make_server(ToyStore(Path(root))).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `git add tests/toykit.py tests/test_toykit.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_toykit -v`
Expected: all PASS.

- [ ] **Step 5: Smoke-test the server by hand**

Run: `TOYKIT_STATE_DIR=$(mktemp -d) timeout 5 "$AUTORESEARCH_PYTHON" tests/toykit.py </dev/null; echo rc=$?`
Expected: `rc=0` (the server sees EOF on stdin and exits cleanly), with no traceback. `rc=124` means it didn't exit on EOF; a traceback means the tool registration is wrong: `InvalidSignature` means an annotation names a symbol that is not a module global (keep `from __future__ import annotations` out of this file), and a serialization error means a tool is not annotated `-> dict[str, Any]`.

- [ ] **Step 6: Commit**

```bash
git add tests/toykit.py tests/test_toykit.py
git commit -m "test(toykit): the reference contract kit

A native MCP kit with the evaluator contract (submit, status, results,
check, describe, cancel) and Branin/Currin metrics. Jobs live on disk so a
restarted child finds them; fail modes cover every engine failure path.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 3: `KitClient`, the synchronous stdio MCP client

**Files:**
- Create: `core/kits.py`
- Modify: `tests/engine_fixtures.py` (add `toy_config`)
- Test: `tests/test_kits.py`

**Interfaces:**
- Consumes: `kit_config.KitConfig`, `KitConfigError` (Task 1); `tests/toykit.py` (Task 2).
- Produces: `kits.KitError(kit, tool, message)` (`.kit`, `.tool`, `.message`), `kits.KitToolError(KitError)` (the server answered `is_error`), `kits.KitTimeout(KitError)` (the call timed out; the session is kept), `kits.WORKFLOW_META_KEY = "gov.fnal.mu2e/workflow"`, `kits.KitClient(config, *, campaign, trace_dir)` with `start()`, `call(tool, args, *, timeout_s, workflow) -> dict`, `close()`, and attributes `campaign`, `started`, `tools: frozenset`, `server_name`, `server_version`.
- Produces (tests): `engine_fixtures.toy_config(state_dir, **overrides) -> KitConfig`.

Behaviour this task pins:
- One server process per client, started lazily on the first call, on a private event loop in a daemon thread (lifted from beamkit's `src/beamkit/mcpclient.py`).
- The child's environment is the MCP SDK's default allowlist (`mcp.client.stdio.get_default_environment()`), plus `env_passthrough`, plus `set`. A variable that can't be resolved fails at start, naming the kit and the variable.
- A timeout (`MCPError` code `REQUEST_TIMEOUT`) raises `KitTimeout` and KEEPS the session. Any other transport failure closes the session, and the next call respawns the server. The client never retries a call itself; `NativeKit` owns retries (Task 4).
- A tool error raises `KitToolError` with the server's own text (the SDK's `Error executing tool <name>: ` prefix stripped).
- Every call sends `meta={WORKFLOW_META_KEY: workflow}` and appends one JSON line to `<trace_dir>/kit_trace.jsonl`: `time`, `workflow`, `kit`, `tool`, `args_sha256`, `duration_s`, `ok`, `error`, `server` (`{name, version}`).

- [ ] **Step 1: Add `toy_config` to `tests/engine_fixtures.py`**

Append:

```python
def toy_config(state_dir, **overrides):
    """The repo's toykit KitConfig, with its state under `state_dir` instead
    of DATA_ROOT, plus any field overrides (e.g. timeouts=...)."""
    import dataclasses
    import sys
    core = str(Path(__file__).resolve().parent.parent / "core")
    if core not in sys.path:
        sys.path.insert(0, core)
    import kit_registry
    base = kit_registry.NATIVE["toykit"]
    fields = {"set_env": {"TOYKIT_STATE_DIR": str(state_dir)}}
    fields.update(overrides)
    return dataclasses.replace(base, **fields)
```

- [ ] **Step 2: Write the failing tests** — `tests/test_kits.py`

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
from kits import (KitClient, KitError, KitTimeout, KitToolError,  # noqa: E402
                  WORKFLOW_META_KEY)
from tests.engine_fixtures import toy_config  # noqa: E402

WF = "camp/cfg/step"


class _Client(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def client(self, **overrides):
        c = KitClient(toy_config(self.tmp / "toy", **overrides),
                      campaign="camp", trace_dir=self.tmp / "trace")
        self.addCleanup(c.close)
        return c

    @staticmethod
    def call(client, tool, args=None, timeout_s=30):
        return client.call(tool, args or {}, timeout_s=timeout_s, workflow=WF)

    def trace(self):
        path = self.tmp / "trace" / "kit_trace.jsonl"
        return [json.loads(ln) for ln in path.read_text().splitlines()]


class TestCalls(_Client):
    def test_describe_round_trip(self):
        c = self.client()
        reply = self.call(c, "describe")
        self.assertIn("x1", reply["params"])
        self.assertEqual((c.server_name, c.server_version), ("toykit", "1"))
        self.assertIn("submit", c.tools)

    def test_tool_error_is_a_kit_tool_error_with_the_server_text(self):
        c = self.client()
        with self.assertRaises(KitToolError) as cm:
            self.call(c, "status", {"handle": "nope"})
        self.assertIn("no job 'nope'", cm.exception.message)
        self.assertNotIn("Error executing tool", cm.exception.message)
        self.assertEqual((cm.exception.kit, cm.exception.tool),
                         ("toykit", "status"))

    def test_unknown_tool(self):
        with self.assertRaises(KitError) as cm:
            self.call(self.client(), "frobnicate")
        self.assertIn("no tool 'frobnicate'", cm.exception.message)

    def test_meta_is_forwarded(self):
        reply = self.call(self.client(), "debug_meta")
        self.assertEqual(reply["meta"][WORKFLOW_META_KEY], WF)


class TestFailures(_Client):
    def test_timeout_keeps_the_session(self):
        c = self.client()
        self.call(c, "describe")
        with self.assertRaises(KitTimeout) as cm:
            self.call(c, "debug_sleep", {"seconds": 5}, timeout_s=0.5)
        self.assertIn("timed out", cm.exception.message)
        self.assertTrue(c.started)
        self.assertIn("x1", self.call(c, "describe")["params"])

    def test_server_death_respawns_on_the_next_call(self):
        c = self.client()
        with self.assertRaises(KitError) as cm:
            self.call(c, "debug_exit")
        self.assertNotIsInstance(cm.exception, KitTimeout)
        self.assertFalse(c.started)
        self.assertIn("x1", self.call(c, "describe")["params"])

    def test_start_failure_carries_the_child_stderr(self):
        c = self.client(set_env={})       # no TOYKIT_STATE_DIR
        with self.assertRaises(KitError) as cm:
            self.call(c, "describe")
        self.assertEqual(cm.exception.tool, "start")
        self.assertIn("TOYKIT_STATE_DIR is not set", cm.exception.message)

    def test_unset_passthrough_fails_at_start_naming_kit_and_variable(self):
        c = self.client(env_passthrough=("TOYKIT_NOT_SET_ANYWHERE",))
        with mock.patch.dict(os.environ):
            os.environ.pop("TOYKIT_NOT_SET_ANYWHERE", None)
            with self.assertRaises(KitError) as cm:
                self.call(c, "describe")
        self.assertEqual(cm.exception.tool, "start")
        self.assertIn("TOYKIT_NOT_SET_ANYWHERE", cm.exception.message)
        self.assertIn("'toykit'", cm.exception.message)


class TestEnvironment(_Client):
    def test_child_env_is_allowlist_plus_passthrough_plus_set(self):
        c = self.client(env_passthrough=("TOYKIT_PROBE",))
        with mock.patch.dict(os.environ, {"TOYKIT_PROBE": "xyz",
                                          "TOYKIT_LEAK": "no"}):
            reply = self.call(c, "debug_env",
                              {"names": ["TOYKIT_PROBE", "TOYKIT_STATE_DIR",
                                         "TOYKIT_LEAK"]})
        self.assertEqual(reply, {"TOYKIT_PROBE": "xyz",
                                 "TOYKIT_STATE_DIR": str(self.tmp / "toy"),
                                 "TOYKIT_LEAK": None})


class TestTrace(_Client):
    def test_one_line_per_call(self):
        c = self.client()
        self.call(c, "describe")
        with self.assertRaises(KitToolError):
            self.call(c, "status", {"handle": "nope"})
        ok, bad = self.trace()
        self.assertEqual((ok["tool"], ok["ok"], ok["error"]),
                         ("describe", True, None))
        self.assertEqual((bad["tool"], bad["ok"]), ("status", False))
        self.assertIn("no job", bad["error"])
        for line in (ok, bad):
            self.assertEqual(line["workflow"], WF)
            self.assertEqual(line["kit"], "toykit")
            self.assertEqual(len(line["args_sha256"]), 64)
            self.assertEqual(line["server"], {"name": "toykit", "version": "1"})
            self.assertGreaterEqual(line["duration_s"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kits -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kits'`.

- [ ] **Step 4: Write `core/kits.py`**

```python
"""KitClient: a synchronous handle on one kit's MCP server over stdio
(generic-study design, "Rules for every kit call"; kit-seam spec §1).

A nested asyncio.run is impossible under a caller's own loop, so the session
lives on a private loop in a daemon thread, and its whole lifetime runs in
ONE task there (anyio cancel scopes must be exited by the task that entered
them). Lifted from beamkit's src/beamkit/mcpclient.py, plus: named timeouts,
the workflow meta tag, the trace log, and the kits.toml environment.

The client never retries a call. A timeout keeps the session (the server
may still be working); any other transport failure closes it, and the next
call respawns the server. Retries belong to core/contract.py's NativeKit,
which knows which calls are safe to repeat.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

if __package__:
    from core.kit_config import KitConfig, KitConfigError
else:
    from kit_config import KitConfig, KitConfigError

WORKFLOW_META_KEY = "gov.fnal.mu2e/workflow"
STDERR_TAIL = 20
_GRACE_S = 5.0          # future.result() margin over the MCP read timeout
_TRACE_LOCK = threading.Lock()


class KitError(RuntimeError):
    """A kit call failed: start, transport, timeout or tool error."""

    def __init__(self, kit: str, tool: str, message: str):
        super().__init__(f"kit {kit!r} {tool}: {message}")
        self.kit, self.tool, self.message = kit, tool, message


class KitToolError(KitError):
    """The server answered is_error; `message` is the server's own text."""


class KitTimeout(KitError):
    """The call timed out. The session is kept: the server may still be
    working on it."""


def _strip_prefix(text: str, tool: str) -> str:
    prefix = f"Error executing tool {tool}: "
    return text[len(prefix):] if text.startswith(prefix) else text


class KitClient:
    def __init__(self, config: KitConfig, *, campaign: str, trace_dir: Path):
        self.config = config
        self.campaign = campaign
        self.trace_path = Path(trace_dir) / "kit_trace.jsonl"
        self.server_name = None
        self.server_version = None
        self.tools = frozenset()
        self._stderr_tail = deque(maxlen=STDERR_TAIL)
        self._pump = None
        self._lock = threading.RLock()
        self._loop = self._thread = None
        self._serve_fut = self._task = self._stop = None
        self._session = None
        atexit.register(self.close)

    @property
    def started(self) -> bool:
        return self._session is not None

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        name = self.config.name
        with self._lock:
            if self._session is not None:
                return
            try:
                from mcp.client.stdio import get_default_environment
                command = self.config.resolve_command()
                env = self.config.resolve_env(get_default_environment())
            except KitConfigError as exc:
                raise KitError(name, "start", str(exc)) from None
            self._stderr_tail.clear()
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever,
                                            name=f"kit-{name}", daemon=True)
            self._thread.start()
            ready = concurrent.futures.Future()
            self._serve_fut = asyncio.run_coroutine_threadsafe(
                self._serve(ready, command, env), self._loop)
            timeout = self.config.timeouts["start"]
            try:
                ready.result(timeout)
            except concurrent.futures.TimeoutError:
                self._teardown()
                raise KitError(name, "start", f"server did not start within "
                               f"{timeout:g} s ({command})") from None
            except Exception as exc:  # noqa: BLE001 - reported with stderr
                self._teardown()
                if self._pump is not None:
                    self._pump.join(2)
                tail = " | ".join(self._stderr_tail)
                raise KitError(name, "start", f"server did not start "
                               f"({command}): {type(exc).__name__}: {exc}; "
                               f"child stderr: {tail}") from exc

    async def _serve(self, ready, command, env):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._task = asyncio.current_task()
        self._stop = asyncio.Event()
        params = StdioServerParameters(command=command[0], args=command[1:],
                                       env=env)
        errlog = self._stderr_tee()
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                errlog.close()      # the child holds its own copy
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.server_name = init.server_info.name
                    self.server_version = init.server_info.version
                    listing = await session.list_tools()
                    self.tools = frozenset(t.name for t in listing.tools)
                    self._session = session
                    ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - via ready, or on stop
            if not ready.done():
                ready.set_exception(exc)
        finally:
            if not errlog.closed:
                errlog.close()
            self._session = None
            self.tools = frozenset()

    def _stderr_tee(self):
        """A pipe the child writes to; a pump thread keeps the last lines
        and forwards everything to our stderr."""
        r, w = os.pipe()

        def pump():
            with os.fdopen(r, "rb", buffering=0) as fh:
                for raw in iter(fh.readline, b""):
                    line = raw.decode("utf-8", "replace")
                    self._stderr_tail.append(line.rstrip("\n"))
                    sys.stderr.write(line)
                    sys.stderr.flush()
        self._pump = threading.Thread(target=pump, daemon=True,
                                      name=f"kit-{self.config.name}-stderr")
        self._pump.start()
        return os.fdopen(w, "w")

    def close(self) -> None:
        with self._lock:
            if self._loop is None:
                return
            if (self._stop is not None and self._serve_fut is not None
                    and not self._serve_fut.done()):
                self._loop.call_soon_threadsafe(self._stop.set)
                try:
                    self._serve_fut.result(10)
                except Exception:  # noqa: BLE001 - shutting down regardless
                    pass
            self._teardown()

    def _teardown(self) -> None:
        loop, thread, task = self._loop, self._thread, self._task
        self._session = None
        self.tools = frozenset()
        if task is not None and not task.done():
            # Cancel and await the REAL task on its own loop, so
            # stdio_client's shutdown (close stdin, wait, SIGTERM/SIGKILL)
            # runs before the loop stops and the child cannot survive.
            async def _cancel_and_wait():
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001 - tearing down
                    pass
            try:
                asyncio.run_coroutine_threadsafe(_cancel_and_wait(),
                                                 loop).result(5)
            except Exception:  # noqa: BLE001 - best effort
                sys.stderr.write(f"kit {self.config.name}: serve task did "
                                 f"not finish within 5 s; its server may "
                                 f"still be running\n")
        self._serve_fut = self._stop = self._task = None
        self._loop = self._thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(5)
            if not loop.is_running():
                loop.close()

    # --- calls -------------------------------------------------------------
    def call(self, tool: str, args: dict, *, timeout_s: float,
             workflow: str) -> dict:
        t0 = time.monotonic()
        error = None
        try:
            return self._call(tool, args, timeout_s, workflow)
        except BaseException as exc:
            error = getattr(exc, "message", None) or repr(exc)
            raise
        finally:
            self._trace(tool, args, workflow, time.monotonic() - t0, error)

    def _call(self, tool, args, timeout_s, workflow) -> dict:
        from mcp.shared.exceptions import MCPError
        from mcp.types import REQUEST_TIMEOUT
        name = self.config.name
        with self._lock:
            if self._session is None:
                self.start()
            if tool not in self.tools:
                raise KitError(name, tool, f"server has no tool {tool!r}; it "
                               f"has {sorted(self.tools)}")
            coro = self._session.call_tool(
                tool, args, read_timeout_seconds=timeout_s,
                meta={WORKFLOW_META_KEY: workflow})
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            try:
                res = fut.result(timeout_s + _GRACE_S)
            except MCPError as exc:
                if exc.code == REQUEST_TIMEOUT:
                    raise KitTimeout(name, tool, f"timed out after "
                                     f"{timeout_s:g} s") from exc
                self._lost(tool, exc)
            except Exception as exc:  # noqa: BLE001 - transport state unknown
                fut.cancel()
                self._lost(tool, exc)
        text = "".join(c.text for c in res.content
                       if getattr(c, "type", None) == "text")
        if res.is_error:
            raise KitToolError(name, tool, _strip_prefix(text, tool))
        if res.structured_content is None:
            raise KitError(name, tool, f"reply has no structured content: "
                           f"{text[:200]!r}")
        return res.structured_content

    def _lost(self, tool, exc):
        """The session is gone or in an unknown state: close it so the next
        call respawns the server, and report with the child's stderr."""
        self.close()
        if self._pump is not None:
            self._pump.join(2)
        tail = " | ".join(self._stderr_tail)
        raise KitError(self.config.name, tool, f"server lost: "
                       f"{type(exc).__name__}: {exc}; child stderr: "
                       f"{tail}") from exc

    def _trace(self, tool, args, workflow, duration, error) -> None:
        line = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "workflow": workflow, "kit": self.config.name, "tool": tool,
            "args_sha256": hashlib.sha256(json.dumps(
                args, sort_keys=True, default=str).encode()).hexdigest(),
            "duration_s": round(duration, 3), "ok": error is None,
            "error": error,
            "server": {"name": self.server_name,
                       "version": self.server_version},
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_LOCK, open(self.trace_path, "a") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `git add core/kits.py tests/engine_fixtures.py tests/test_kits.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kits -v`
Expected: all PASS, in about 15 s (each test starts a server).


- [ ] **Step 6: Run the whole suite, then commit**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add core/kits.py tests/engine_fixtures.py tests/test_kits.py
git commit -m "feat(kits): KitClient, a synchronous stdio MCP client for kits

One server per client on a private loop thread. Named timeouts keep the
session; a lost server is respawned by the next call. Every call carries
the workflow meta tag and writes one kit_trace.jsonl line. The child gets
the SDK allowlist plus the kits.toml passthrough and set variables.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---
### Task 4: The contract layer — reply validation, `NativeKit`, `KitSet`, adapter registry, `check_kits`

**Files:**
- Create: `core/contract.py`
- Test: `tests/test_contract.py`

**Interfaces:**
- Consumes: `kits.KitClient`, `KitError`, `KitToolError`, `KitTimeout` (Task 3); `kit_registry.KITS`, `NATIVE`, `kits_of` (Task 1).
- Produces:
  - `contract.ContractError(kit, call, message)`; `contract.STATES = ("working", "completed", "failed", "cancelled")`.
  - Frozen dataclasses: `Status(state, message, poll_ms, progress)`, `Results(metrics: dict[str, float], files: tuple[dict, ...], metadata: dict)`, `Describe(params: tuple, metrics: tuple, accepts_lists: bool)`.
  - Parsers: `parse_submit(reply, kit, name) -> str`, `parse_status(reply, kit) -> Status`, `parse_results(reply, kit) -> Results`, `parse_check(reply, kit) -> (bool, str)`, `parse_describe(reply, kit) -> Describe`, `parse_cancel(reply, kit) -> str`, `parse_file_ref(v, kit, call) -> dict`.
  - `NativeKit(config, client)` implementing the Kit interface: attributes `name`, `version`, `tools`, `accepts_lists`, `poll_s`; methods `submit(name, params, files, inputs, workflow) -> str`, `status(handle, workflow) -> Status`, `results(handle, workflow) -> Results`, `check(name, params, files, inputs, workflow) -> (bool, str)`, `describe() -> Describe | None`, `cancel(handle, workflow) -> str`, `close()`.
  - `ADAPTERS: dict[str, factory]`, `register_adapter(name, factory)`, `open_kit(name, campaign) -> Kit`, `launch_stagger(study) -> float`, `KitSet(campaign, opener=open_kit)` with `.get(name)` and `.close()`, `check_kits(study, *, campaign, opener=open_kit) -> list[str]`.

Rules this task pins:
- Replies must carry the keys the contract names, with the right types. Keys it doesn't name are ignored, so a kit can add fields.
- `submit`'s handle must equal the name it was given (`<config>.<step>`).
- Retries: up to 3 attempts. Transport failures and timeouts are retried for `submit`, which is idempotent by name, and for `status`, `results`, `check` and `describe`. Tool errors are retried only for the read-only calls: a refused `submit` (same name, different params) is never repeated. `cancel` is never retried.

- [ ] **Step 1: Write the failing tests** — `tests/test_contract.py`

```python
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import study as st  # noqa: E402
from kits import KitClient, KitError, KitTimeout, KitToolError  # noqa: E402
from tests.engine_fixtures import toy_config, toy_doc, write_study  # noqa: E402

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"
STATUS = {"state": "working", "message": "", "poll_ms": 100, "progress": None}
RESULTS = {"metrics": {"a": 1.0}, "files": [], "metadata": {}}


class TestParsers(unittest.TestCase):
    def assertViolation(self, fn, *needles):
        with self.assertRaises(ct.ContractError) as cm:
            fn()
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_status(self):
        s = ct.parse_status(dict(STATUS, progress={"done": 1, "total": 3,
                                                   "ok": 1}, extra=1), "k")
        self.assertEqual((s.state, s.poll_ms, s.progress["total"]),
                         ("working", 100, 3))

    def test_status_violations(self):
        for bad, needle in ((dict(STATUS, state="bogus"), "state"),
                            (dict(STATUS, poll_ms=True), "poll_ms"),
                            (dict(STATUS, poll_ms=-1), "poll_ms"),
                            (dict(STATUS, message=3), "message"),
                            (dict(STATUS, progress={"done": 1}), "total"),
                            ({"state": "working"}, "missing")):
            with self.subTest(needle=needle):
                self.assertViolation(lambda: ct.parse_status(bad, "k"), needle)

    def test_results(self):
        r = ct.parse_results({"metrics": {"a": 1, "b": 2.5},
                              "files": [{"name": "o", "uri": "file:///o",
                                         "kind": "text"}],
                              "metadata": {"m": 1}}, "k")
        self.assertEqual(r.metrics, {"a": 1.0, "b": 2.5})
        self.assertEqual(r.files, ({"name": "o", "uri": "file:///o",
                                    "kind": "text"},))

    def test_results_violations(self):
        ref = {"name": "o", "uri": "http://x", "kind": "t"}
        for bad, needle in ((dict(RESULTS, metrics={"a": "1"}), "metrics"),
                            (dict(RESULTS, metrics={"a": None}), "metrics"),
                            (dict(RESULTS, metrics={"a": True}), "metrics"),
                            (dict(RESULTS, files=[ref]), "uri"),
                            (dict(RESULTS, files="x"), "files"),
                            (dict(RESULTS, metadata=[]), "metadata")):
            with self.subTest(needle=needle):
                self.assertViolation(lambda: ct.parse_results(bad, "k"), needle)

    def test_submit_handle_must_be_the_name(self):
        self.assertEqual(ct.parse_submit({"handle": "c.s"}, "k", "c.s"), "c.s")
        self.assertViolation(
            lambda: ct.parse_submit({"handle": "other"}, "k", "c.s"), "c.s")

    def test_check_describe_cancel(self):
        self.assertEqual(ct.parse_check({"ok": False, "message": "m"}, "k"),
                         (False, "m"))
        self.assertViolation(lambda: ct.parse_check({"ok": 1, "message": ""},
                                                    "k"), "ok")
        d = ct.parse_describe({"params": ["a"], "metrics": ["m"],
                               "accepts_lists": True}, "k")
        self.assertEqual(d, ct.Describe(("a",), ("m",), True))
        self.assertEqual(ct.parse_cancel({"state": "cancelled"}, "k"),
                         "cancelled")
        self.assertViolation(lambda: ct.parse_cancel({"state": "x"}, "k"),
                             "state")


class FakeClient:
    """A scripted KitClient: one reply or exception per call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.started = True
        self.server_version = "9"
        self.tools = frozenset(ct.REQUIRED_TOOLS)
        self.campaign = "c"

    def start(self):
        pass

    def call(self, tool, args, *, timeout_s, workflow):
        self.calls.append(tool)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class TestRetryPolicy(unittest.TestCase):
    CFG = kit_registry.NATIVE["toykit"]
    DONE = dict(STATUS, state="completed")

    def kit(self, script):
        client = FakeClient(script)
        return ct.NativeKit(self.CFG, client), client

    def test_status_retries_transport_and_tool_errors(self):
        kit, c = self.kit([KitError("k", "status", "lost"),
                           KitToolError("k", "status", "ticket expired"),
                           self.DONE])
        self.assertEqual(kit.status("h", "w").state, "completed")
        self.assertEqual(len(c.calls), 3)

    def test_status_gives_up_after_three_attempts(self):
        kit, c = self.kit([KitError("k", "status", "lost")] * 3)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(len(c.calls), 3)

    def test_submit_retries_a_timeout(self):
        kit, c = self.kit([KitTimeout("k", "submit", "timed out"),
                           {"handle": "c.s"}])
        self.assertEqual(kit.submit("c.s", {}, [], [], "w"), "c.s")
        self.assertEqual(len(c.calls), 2)

    def test_submit_never_repeats_a_refusal(self):
        kit, c = self.kit([KitToolError("k", "submit", "different params")])
        with self.assertRaises(KitToolError):
            kit.submit("c.s", {}, [], [], "w")
        self.assertEqual(len(c.calls), 1)

    def test_cancel_is_never_retried(self):
        kit, c = self.kit([KitError("k", "cancel", "lost")])
        with self.assertRaises(KitError):
            kit.cancel("h", "w")
        self.assertEqual(len(c.calls), 1)


class _Toy(unittest.TestCase):
    P = {"x1": 1.0, "x2": 2.0, "function": "branin_currin"}

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.cfg = toy_config(self.tmp / "toy")

    def open(self, name="toykit", campaign="c", cfg=None):
        cfg = cfg or self.cfg
        kit = ct.NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                          trace_dir=self.tmp / "trace"))
        self.addCleanup(kit.close)
        return kit

    def submits(self):
        path = self.tmp / "toy" / "submits.jsonl"
        return path.read_text().splitlines() if path.exists() else []


class TestNativeKitOnToykit(_Toy):
    def test_submit_status_results(self):
        kit = self.open()
        handle = kit.submit("c.toy", self.P, [], [], "c/c/toy")
        self.assertEqual(kit.status(handle, "w").state, "completed")
        self.assertIn("branin", kit.results(handle, "w").metrics)
        self.assertEqual(kit.version, "1")

    def test_resubmit_is_idempotent(self):
        kit = self.open()
        kit.submit("c.toy", self.P, [], [], "w")
        kit.submit("c.toy", self.P, [], [], "w")
        self.assertEqual(len(self.submits()), 1)

    def test_submit_timeout_then_idempotent_resubmit(self):
        cfg = replace(self.cfg, timeouts=dict(self.cfg.timeouts, submit=0.5))
        kit = self.open(cfg=cfg)
        handle = kit.submit("c.toy", dict(self.P, submit_sleep_s=3), [], [], "w")
        self.assertEqual(handle, "c.toy")
        self.assertEqual(len(self.submits()), 1)
        lines = (self.tmp / "trace" / "kit_trace.jsonl").read_text().splitlines()
        oks = [json.loads(ln)["ok"] for ln in lines
               if json.loads(ln)["tool"] == "submit"]
        self.assertEqual(oks, [False, True])

    def test_a_state_outside_the_contract(self):
        kit = self.open()
        handle = kit.submit("c.toy", dict(self.P, fail="bad_state"), [], [], "w")
        with self.assertRaises(ct.ContractError):
            kit.status(handle, "w")

    def test_check_and_describe(self):
        kit = self.open()
        self.assertEqual(kit.check("c.pre", self.P, [], [], "w"), (True, ""))
        self.assertFalse(kit.check("c.pre", dict(self.P, function="reject"),
                                   [], [], "w")[0])
        self.assertIn("x1", kit.describe().params)


class TestKitSet(unittest.TestCase):
    def test_opens_each_kit_once_and_closes_all(self):
        opened = []

        class K:
            def __init__(self, name):
                self.name, self.closed = name, False

            def close(self):
                self.closed = True

        def opener(name, campaign):
            opened.append(K(name))
            return opened[-1]

        kits = ct.KitSet("c", opener=opener)
        first = kits.get("a")
        self.assertIs(kits.get("a"), first)
        kits.get("b")
        kits.close()
        self.assertEqual([k.name for k in opened], ["a", "b"])
        self.assertTrue(all(k.closed for k in opened))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        decl = kit_registry.KitDecl("fakeadapter", study_keys={},
                                    fixed_keys={}, uses_entries=False,
                                    step_kit=True, check_kit=False,
                                    engine=True)
        for patch in (mock.patch.dict(ct.ADAPTERS, {}, clear=True),
                      mock.patch.dict(kit_registry.KITS,
                                      {"fakeadapter": decl})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_register_and_open(self):
        class Fake:
            LAUNCH_STAGGER_S = 7

            def __init__(self, campaign):
                self.campaign = campaign

        ct.register_adapter("fakeadapter", Fake)
        self.assertEqual(ct.open_kit("fakeadapter", "camp").campaign, "camp")
        with self.assertRaises(ValueError):
            ct.register_adapter("fakeadapter", Fake)

    def test_only_an_engine_kit_without_a_kits_toml_entry_takes_an_adapter(self):
        for name in ("prodtools", "toykit", "nosuchkit"):
            with self.subTest(kit=name):
                with self.assertRaises(ValueError):
                    ct.register_adapter(name, object)

    def test_a_kit_with_neither_is_refused(self):
        with self.assertRaises(KeyError) as cm:
            ct.open_kit("prodtools", "c")
        self.assertIn("kits.toml", str(cm.exception))

    def test_launch_stagger(self):
        with tempfile.TemporaryDirectory() as td:
            study = st.load_study_file(write_study(toy_doc(), Path(td)))
        self.assertEqual(ct.launch_stagger(study), 0.0)


class TestCheckKits(_Toy):
    def study(self, mutate=lambda doc: None):
        doc = toy_doc()
        mutate(doc)
        return st.load_study_file(write_study(doc, self.tmp / "studies"))

    def check(self, study, cfg=None):
        return ct.check_kits(study, campaign="c",
                             opener=lambda n, c: self.open(n, c, cfg=cfg))

    def test_a_good_study_passes(self):
        self.assertEqual(self.check(self.study()), [])

    def test_an_unknown_param(self):
        study = self.study(lambda d: d["evaluate"][0]["params"].update(x3="x1"))
        self.assertTrue(any("x3" in p for p in self.check(study)))

    def test_an_unknown_metric(self):
        study = self.study(lambda d: d["objectives"][0].update(metric="toy.nope"))
        self.assertTrue(any("nope" in p for p in self.check(study)))

    def test_a_server_that_cannot_start(self):
        problems = self.check(self.study(), cfg=replace(self.cfg, set_env={}))
        self.assertEqual(len(problems), 1)
        self.assertIn("TOYKIT_STATE_DIR", problems[0])

    def test_an_unset_passthrough_variable(self):
        cfg = replace(self.cfg, env_passthrough=("TOYKIT_NOT_SET_ANYWHERE",))
        with mock.patch.dict(os.environ):
            os.environ.pop("TOYKIT_NOT_SET_ANYWHERE", None)
            problems = self.check(self.study(), cfg=cfg)
        self.assertEqual(len(problems), 1)
        self.assertIn("TOYKIT_NOT_SET_ANYWHERE", problems[0])
        self.assertIn("'toykit'", problems[0])

    def test_pipeline_kits_are_refused_without_starting_anything(self):
        problems = ct.check_kits(st.load_study_file(DEMO), campaign="c")
        self.assertTrue(problems)
        self.assertTrue(all("kits.toml" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'contract'`.

- [ ] **Step 3: Write `core/contract.py`**

```python
"""The evaluator contract (generic-study design, "The evaluator contract"):
reply validation, the Kit interface the engine drives, NativeKit (a kit
that speaks the contract over MCP), the adapter registry, KitSet (the kits
one child uses) and check_kits (the launch check).

A reply outside the contract raises ContractError: a failed evaluation,
never success. Replies must carry the keys the contract names, with the
right types; keys it doesn't name are ignored, so a kit can add fields.

The Kit interface, which NativeKit and every adapter implement:
  name, version, tools, accepts_lists, poll_s
  submit(name, params, files, inputs, workflow) -> handle
  status(handle, workflow) -> Status
  results(handle, workflow) -> Results
  check(name, params, files, inputs, workflow) -> (ok, message)
  describe() -> Describe | None
  cancel(handle, workflow) -> state
  close()
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

if __package__:
    from core import kit_registry, paths
    from core.kits import KitClient, KitError, KitToolError
else:
    import kit_registry
    import paths
    from kits import KitClient, KitError, KitToolError

STATES = ("working", "completed", "failed", "cancelled")
REQUIRED_TOOLS = ("submit", "status", "results")
ATTEMPTS = 3            # bounded retries of the calls safe to repeat
_URI_SCHEMES = ("file://", "root://")


class ContractError(RuntimeError):
    def __init__(self, kit: str, call: str, message: str):
        super().__init__(f"kit {kit!r} {call}: reply outside the contract: "
                         f"{message}")
        self.kit, self.call, self.message = kit, call, message


@dataclass(frozen=True)
class Status:
    state: str
    message: str
    poll_ms: int
    progress: Optional[Dict[str, int]]


@dataclass(frozen=True)
class Results:
    metrics: Dict[str, float]
    files: Tuple[Dict[str, str], ...]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class Describe:
    params: Tuple[str, ...]
    metrics: Tuple[str, ...]
    accepts_lists: bool


def _fields(reply, keys, kit, call) -> dict:
    if not isinstance(reply, dict):
        raise ContractError(kit, call, f"expected an object, got {reply!r}")
    missing = [k for k in keys if k not in reply]
    if missing:
        raise ContractError(kit, call, f"missing key(s) {missing}")
    return reply


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_file_ref(v, kit, call) -> dict:
    ref = _fields(v, ("name", "uri", "kind"), kit, call)
    if not all(isinstance(ref[k], str) and ref[k]
               for k in ("name", "uri", "kind")):
        raise ContractError(kit, call, f"a FileRef's name, uri and kind are "
                            f"non-empty strings, got {ref!r}")
    if not ref["uri"].startswith(_URI_SCHEMES):
        raise ContractError(kit, call, f"a FileRef uri starts with "
                            f"{list(_URI_SCHEMES)}, got {ref['uri']!r}")
    return {"name": ref["name"], "uri": ref["uri"], "kind": ref["kind"]}


def parse_submit(reply, kit, name) -> str:
    handle = _fields(reply, ("handle",), kit, "submit")["handle"]
    if handle != name:
        raise ContractError(kit, "submit", f"the handle must be the submitted "
                            f"name {name!r} (handles are <config>.<step>), "
                            f"got {handle!r}")
    return handle


def parse_status(reply, kit) -> Status:
    r = _fields(reply, ("state", "message", "poll_ms", "progress"), kit,
                "status")
    if r["state"] not in STATES:
        raise ContractError(kit, "status", f"state must be one of "
                            f"{list(STATES)}, got {r['state']!r}")
    if not isinstance(r["message"], str):
        raise ContractError(kit, "status", "message must be a string")
    if not _is_int(r["poll_ms"]) or r["poll_ms"] < 0:
        raise ContractError(kit, "status", f"poll_ms must be an int >= 0, "
                            f"got {r['poll_ms']!r}")
    progress = r["progress"]
    if progress is not None:
        p = _fields(progress, ("done", "total", "ok"), kit, "status")
        if not all(_is_int(p[k]) and p[k] >= 0 for k in ("done", "total", "ok")):
            raise ContractError(kit, "status", "progress done, total and ok "
                                "must be ints >= 0")
        progress = {k: p[k] for k in ("done", "total", "ok")}
    return Status(r["state"], r["message"], r["poll_ms"], progress)


def parse_results(reply, kit) -> Results:
    r = _fields(reply, ("metrics", "files", "metadata"), kit, "results")
    metrics = r["metrics"]
    if not isinstance(metrics, dict) or not all(
            isinstance(k, str) and _is_number(v) for k, v in metrics.items()):
        raise ContractError(kit, "results", f"metrics must map names to "
                            f"numbers, got {metrics!r}")
    if not isinstance(r["files"], list):
        raise ContractError(kit, "results", "files must be a list of FileRefs")
    files = tuple(parse_file_ref(f, kit, "results") for f in r["files"])
    if not isinstance(r["metadata"], dict):
        raise ContractError(kit, "results", "metadata must be an object")
    return Results({k: float(v) for k, v in metrics.items()}, files,
                   dict(r["metadata"]))


def parse_check(reply, kit) -> Tuple[bool, str]:
    r = _fields(reply, ("ok", "message"), kit, "check")
    if not isinstance(r["ok"], bool) or not isinstance(r["message"], str):
        raise ContractError(kit, "check", "ok must be true or false and "
                            "message a string")
    return r["ok"], r["message"]


def parse_describe(reply, kit) -> Describe:
    r = _fields(reply, ("params", "metrics", "accepts_lists"), kit, "describe")
    for key in ("params", "metrics"):
        if not isinstance(r[key], list) or not all(isinstance(v, str)
                                                   for v in r[key]):
            raise ContractError(kit, "describe", f"{key} must be a list of "
                                f"names")
    if not isinstance(r["accepts_lists"], bool):
        raise ContractError(kit, "describe", "accepts_lists must be true or "
                            "false")
    return Describe(tuple(r["params"]), tuple(r["metrics"]),
                    r["accepts_lists"])


def parse_cancel(reply, kit) -> str:
    state = _fields(reply, ("state",), kit, "cancel")["state"]
    if state not in STATES:
        raise ContractError(kit, "cancel", f"state must be one of "
                            f"{list(STATES)}, got {state!r}")
    return state


class NativeKit:
    """A kit that speaks the contract over MCP: one kits.toml entry."""

    def __init__(self, config, client):
        self.name = config.name
        self.config = config
        self.client = client
        self.accepts_lists = config.accepts_lists
        self.poll_s = config.poll_s

    def _ensure_started(self) -> None:
        if not self.client.started:
            self.client.start()

    @property
    def version(self) -> str:
        self._ensure_started()
        return self.client.server_version or ""

    @property
    def tools(self) -> frozenset:
        self._ensure_started()
        return self.client.tools

    def _call(self, tool, args, workflow, *, retry_tool_errors,
              attempts=ATTEMPTS):
        """Transport failures and timeouts are retried (the client respawns
        a lost server before the next call). A tool error is retried only
        for read-only calls: a refused submit (same name, different params)
        must never be repeated."""
        for attempt in range(1, attempts + 1):
            try:
                return self.client.call(tool, args,
                                        timeout_s=self.config.timeouts[tool],
                                        workflow=workflow)
            except KitToolError:
                if not retry_tool_errors or attempt == attempts:
                    raise
            except KitError:
                if attempt == attempts:
                    raise

    def submit(self, name, params, files, inputs, workflow) -> str:
        # Safe to repeat after a timeout: submit is idempotent by name.
        reply = self._call("submit", {"name": name, "params": params,
                                      "files": list(files),
                                      "inputs": list(inputs)},
                           workflow, retry_tool_errors=False)
        return parse_submit(reply, self.name, name)

    def status(self, handle, workflow) -> Status:
        return parse_status(self._call("status", {"handle": handle}, workflow,
                                       retry_tool_errors=True), self.name)

    def results(self, handle, workflow) -> Results:
        return parse_results(self._call("results", {"handle": handle},
                                        workflow, retry_tool_errors=True),
                             self.name)

    def check(self, name, params, files, inputs, workflow) -> Tuple[bool, str]:
        return parse_check(self._call("check", {"name": name, "params": params,
                                                "files": list(files),
                                                "inputs": list(inputs)},
                                      workflow, retry_tool_errors=True),
                           self.name)

    def describe(self) -> Optional[Describe]:
        if "describe" not in self.tools:
            return None
        workflow = f"{self.client.campaign}/launch/describe"
        return parse_describe(self._call("describe", {}, workflow,
                                         retry_tool_errors=True), self.name)

    def cancel(self, handle, workflow) -> str:
        return parse_cancel(self._call("cancel", {"handle": handle}, workflow,
                                       retry_tool_errors=False, attempts=1),
                            self.name)

    def close(self) -> None:
        self.client.close()


# Kits implemented in Python: Phase C registers prodtools and the three
# plugins. A factory is a class taking the campaign name, with a
# LAUNCH_STAGGER_S attribute; its kit needs a kit_registry declaration with
# engine=True and no kits.toml entry.
ADAPTERS: Dict[str, Callable[[str], Any]] = {}


def register_adapter(name: str, factory) -> None:
    if name in ADAPTERS:
        raise ValueError(f"adapter {name!r} is registered twice")
    decl = kit_registry.KITS.get(name)
    if decl is None or not decl.engine or name in kit_registry.NATIVE:
        raise ValueError(f"adapter {name!r} needs a kit_registry declaration "
                         f"with engine=True and no kits.toml entry")
    ADAPTERS[name] = factory


def open_kit(name: str, campaign: str):
    if name in ADAPTERS:
        return ADAPTERS[name](campaign)
    cfg = kit_registry.NATIVE.get(name)
    if cfg is None:
        raise KeyError(f"kit {name!r} has no adapter and no kits.toml entry, "
                       f"so the contract engine cannot run it (the pipeline "
                       f"kits run through graph.run until Phase C)")
    return NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                    trace_dir=paths.GRAPH_DATA / campaign))


def launch_stagger(study) -> float:
    """Seconds between a campaign's child launches: the largest any of the
    study's kits asks for."""
    gap = 0.0
    for name in kit_registry.kits_of(study):
        if name in ADAPTERS:
            gap = max(gap, float(ADAPTERS[name].LAUNCH_STAGGER_S))
        else:
            gap = max(gap, kit_registry.NATIVE[name].launch_stagger_s)
    return gap


class KitSet:
    """The kits one child uses: opened on first use (one server per kit),
    closed together. Thread-safe: run_steps' threads share it."""

    def __init__(self, campaign: str, opener=open_kit):
        self.campaign = campaign
        self._opener = opener
        self._kits: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, name: str):
        with self._lock:
            if name not in self._kits:
                self._kits[name] = self._opener(name, self.campaign)
            return self._kits[name]

    def close(self) -> None:
        with self._lock:
            kits, self._kits = list(self._kits.values()), {}
        for kit in kits:
            kit.close()


def _needs(study, kit_name):
    """(param names sent, metric keys read, params that carry a profile)
    for one kit of the study."""
    settings = set(study.kits.get(kit_name, {}))
    profiles = set(study.derive["profiles"])
    steps = [s for s in study.steps if s.kit == kit_name]
    mappings = [s.params for s in steps]
    params = set(settings)
    for s in steps:
        params |= set(s.params) | set(s.fixed)
    pre = study.preflight
    if pre is not None and pre["kit"] == kit_name:
        params |= set(pre["params"])
        mappings.append(pre["params"])
    profile_params = {k for m in mappings for k, v in m.items() if v in profiles}
    step_names = {s.step for s in steps}
    metrics = set()
    for m in tuple(study.objectives) + tuple(study.extra_metrics):
        step, key = m.metric.split(".", 1)
        if step in step_names:
            metrics.add(key)
    return params, metrics, profile_params


def check_kits(study, *, campaign: str, opener=open_kit) -> List[str]:
    """The launch check. Every kit the study names must start, offer the
    contract's tools (and `check` when it runs the preflight), and report a
    server version, which measure_sha needs. When a kit offers `describe`,
    the study's params must be ones it accepts and its metrics ones it
    returns. Returns the problems; an empty list means launch."""
    problems = []
    for name in sorted(kit_registry.kits_of(study)):
        try:
            kit = opener(name, campaign)
        except (KeyError, KitError) as exc:
            problems.append(str(exc).strip("\"'"))
            continue
        try:
            need = set(REQUIRED_TOOLS)
            if study.preflight is not None and study.preflight["kit"] == name:
                need.add("check")
            missing = sorted(need - set(kit.tools))
            if missing:
                problems.append(f"kit {name!r} lacks contract tool(s) "
                                f"{missing}")
            if not kit.version:
                problems.append(f"kit {name!r} reports no server version, so "
                                f"measure_sha could not tell its builds apart")
            described = kit.describe()
            if described is not None:
                params, metrics, profile_params = _needs(study, name)
                if described.accepts_lists != kit.accepts_lists:
                    problems.append(
                        f"kit {name!r}: describe says accepts_lists="
                        f"{described.accepts_lists}, its registry entry says "
                        f"{kit.accepts_lists}")
                sent = {f"{p}_0" if p in profile_params and not kit.accepts_lists
                        else p for p in params}
                unknown = sorted(sent - set(described.params))
                if unknown:
                    problems.append(f"kit {name!r} does not accept param(s) "
                                    f"{unknown} (it accepts "
                                    f"{list(described.params)})")
                absent = sorted(metrics - set(described.metrics))
                if absent:
                    problems.append(f"kit {name!r} does not return metric(s) "
                                    f"{absent} (it returns "
                                    f"{list(described.metrics)})")
        except (KitError, ContractError) as exc:
            problems.append(str(exc))
        finally:
            kit.close()
    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `git add core/contract.py tests/test_contract.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add core/contract.py tests/test_contract.py
git commit -m "feat(contract): reply validation, NativeKit, adapter registry, check_kits

A reply outside the evaluator contract is a ContractError, never success.
NativeKit retries only what is safe to repeat: reads, and an idempotent
submit after a timeout, but never a refused submit or a cancel.
check_kits is the launch check: every kit starts, offers the contract,
reports a version, and accepts the study's params and metrics.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 5: The study model for the engine — v2 layout, `measure_sha`, engine classification

**Files:**
- Modify: `core/study.py`
- Modify: `core/geom_template.py` (add `derived_env`)
- Modify: `core/modes.py`
- Modify: `core/study_compat.py`
- Create: `tests/fixtures/engine_studies/branin.json`
- Modify: `tests/test_study.py` (delete `test_layout_v2_arrives_in_phase_b`, which asserts v2 is refused)
- Test: `tests/test_study_engine.py`

**Interfaces:**
- Consumes: `kit_registry.KITS[...].engine`, `kit_registry.kits_of` (Task 1); `engine_fixtures.toy_doc`, `write_study`.
- Produces:
  - `Study.layout` may be `"v2"`.
  - `Study.measure_basis: dict` (field, `compare=False`) and `Study.measure_sha(kit_versions: dict[str, str]) -> str`.
  - `GeomTemplate.derived_env(x) -> dict` (knob values, consts, derived exprs, profiles); `render(x)` uses it and its output is unchanged.
  - `modes.runs_on_engine(study) -> bool` (raises `ValueError` for a study that mixes engine and pipeline kits), `modes.ENGINE: frozenset[str]`. `modes.SPECS` now holds pipeline studies only.
  - `study_compat.modespec_from_study` refuses a `layout` other than `"v1"`.

`measure_basis` holds exactly what the spec lists: `derive`, `geom` and `kits` (raw, so a `${ARTIFACT}/` value hashes the same for every operator), and per step `step`, `kit`, the resolved `entry` template, `files`, `files_from`, `params` and `fixed`. Per objective it holds `metric` and `transform`, and per extra metric its `metric`. It leaves out `note`, knob bounds and units, `fmt`, `noise`, `constraints`, `preflight` and `leaderboard`. A string `entry` resolves to `stage_entries/<entry>.json`, searching the repo first and then `<dir>/stage_entries/` for each `$AUTORESEARCH_STUDY_PATH` directory. A missing template is a load error.

- [ ] **Step 1: Write the Branin study** — `tests/fixtures/engine_studies/branin.json`

```json
{
 "schema": 2,
 "name": "branin",
 "note": "Phase B acceptance: Branin-Currin on toykit, two objectives, Currin constrained.",
 "knobs": [
  {"name": "x1", "type": "real", "min": -5.0, "max": 10.0, "unit": "", "fmt": "{:.6f}"},
  {"name": "x2", "type": "real", "min": 0.0, "max": 15.0, "unit": "", "fmt": "{:.6f}"}
 ],
 "derive": {"consts": {}, "exprs": {}, "profiles": {}},
 "geom": null,
 "kits": {"toykit": {"function": "branin_currin"}},
 "preflight": null,
 "evaluate": [
  {"step": "toy", "kit": "toykit", "entry": null, "files": [], "files_from": [], "params": {"x1": "x1", "x2": "x2"}, "fixed": {"delay_s": 0.2}}
 ],
 "objectives": [
  {"name": "branin", "metric": "toy.branin", "direction": "min", "transform": "none", "noise": 0.01, "fmt": "{:.6f}"},
  {"name": "currin", "metric": "toy.currin", "direction": "min", "transform": "log10", "noise": 0.01, "fmt": "{:.6f}"}
 ],
 "constraints": [{"name": "currin", "max": 10.0, "k_sigma": 1.0}],
 "extra_metrics": [],
 "extra_columns": [],
 "leaderboard": {"file": "leaderboards/leaderboard_branin.tsv", "layout": "v2", "context": []}
}
```

- [ ] **Step 2: Write the failing tests** — `tests/test_study_engine.py`

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402
import study_compat  # noqa: E402
from tests.engine_fixtures import (ENGINE_STUDIES, toy_doc,  # noqa: E402
                                   write_study)

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"
V = {"toykit": "1"}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)

    def load(self, doc):
        return st.load_study_file(write_study(doc, self.dir))


class TestLayout(_Tmp):
    def test_v2_loads(self):
        self.assertEqual(self.load(toy_doc(layout="v2")).layout, "v2")

    def test_other_layouts_are_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.load(toy_doc(layout="v3"))
        self.assertIn("leaderboard.layout", str(cm.exception))

    def test_the_branin_fixture_loads(self):
        s = st.load_study_file(ENGINE_STUDIES / "branin.json")
        self.assertEqual((s.name, s.layout, len(s.objectives)),
                         ("branin", "v2", 2))


class TestMeasureSha(_Tmp):
    def sha(self, mutate=lambda d: None, versions=V):
        doc = toy_doc(layout="v2")
        mutate(doc)
        return self.load(doc).measure_sha(versions)

    def test_unchanged_by_what_does_not_measure(self):
        base = self.sha()
        for label, mutate in (
                ("note", lambda d: d.update(note="edited")),
                ("bounds", lambda d: d["knobs"][0].update(max=12.0)),
                ("fmt", lambda d: d["objectives"][0].update(fmt="{:.3f}")),
                ("noise", lambda d: d["objectives"][0].update(noise=0.5)),
                ("constraint", lambda d: d["constraints"][0].update(max=9.0)),
                ("leaderboard", lambda d: d["leaderboard"].update(
                    file="leaderboards/other.tsv"))):
            with self.subTest(edit=label):
                self.assertEqual(self.sha(mutate), base)

    def test_changed_by_what_measures(self):
        base = self.sha()
        for label, mutate in (
                ("kit setting", lambda d: d["kits"]["toykit"].update(
                    function="reject")),
                ("fixed", lambda d: d["evaluate"][0]["fixed"].update(delay_s=1.0)),
                ("params", lambda d: d["evaluate"][0]["params"].update(x2="x1")),
                ("metric", lambda d: d["objectives"][1].update(metric="toy.n_inputs",
                                                               transform="none")),
                ("transform", lambda d: d["objectives"][0].update(transform="log10"))):
            with self.subTest(edit=label):
                self.assertNotEqual(self.sha(mutate), base)

    def test_changed_by_the_kit_version(self):
        self.assertNotEqual(self.sha(), self.sha(versions={"toykit": "2"}))

    def test_a_missing_kit_version_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.sha(versions={})
        self.assertIn("toykit", str(cm.exception))

    def test_an_artifact_path_hashes_the_same_for_every_operator(self):
        a = st.load_study_file(DEMO).measure_basis
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.dir):
            b = st.load_study_file(DEMO).measure_basis
        self.assertEqual(a, b)
        self.assertIn("${ARTIFACT}/", json.dumps(a["kits"]))


class TestStageTemplates(_Tmp):
    def test_a_named_entry_resolves_to_its_template(self):
        basis = st.load_study_file(DEMO).measure_basis
        step = next(s for s in basis["steps"] if s["step"] == "mubeam")
        repo = json.loads((ROOT / "stage_entries" / "mubeam.json").read_text())
        self.assertEqual(step["entry"], repo)

    def test_a_missing_template_is_a_load_error(self):
        doc = json.loads(DEMO.read_text())
        next(s for s in doc["evaluate"] if s["step"] == "mubeam")["entry"] = \
            "no_such_stage"
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        self.assertIn("no_such_stage", str(cm.exception))
        self.assertIn("stage_entries", str(cm.exception))


class TestDerivedEnv(unittest.TestCase):
    def test_env_carries_knobs_consts_and_profiles(self):
        study = modes.STUDIES["foilspf"]
        x = [(lo + hi) / 2 for lo, hi in zip(study.bounds_lo, study.bounds_hi)]
        env = study.geom.derived_env(x)
        for name, v in zip(study.knob_names, x):
            self.assertEqual(env[name], v)
        for name in study.derive["consts"]:
            self.assertIn(name, env)
        for name in study.derive["profiles"]:
            self.assertIsInstance(env[name], list)

    def test_derive_without_geom_message_is_current(self):
        doc = toy_doc()
        doc["derive"]["consts"] = {"k": 1.0}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as cm:
                st.load_study_file(write_study(doc, Path(td)))
        self.assertIn("geom is null", str(cm.exception))
        self.assertNotIn("Phase B", str(cm.exception))


class TestEngineClassification(_Tmp):
    def test_a_toykit_study_runs_on_the_engine(self):
        self.assertTrue(modes.runs_on_engine(self.load(toy_doc())))

    def test_a_pipeline_study_does_not(self):
        self.assertFalse(modes.runs_on_engine(st.load_study_file(DEMO)))

    def test_a_mixed_study_is_refused(self):
        doc = json.loads(DEMO.read_text())
        doc["kits"]["toykit"] = {"function": "branin_currin"}
        doc["evaluate"].append({"step": "toy", "kit": "toykit", "entry": None,
                                "files": [], "files_from": [], "params": {},
                                "fixed": {}})
        doc["extra_metrics"].append({"name": "toyv", "metric": "toy.branin",
                                     "fmt": "{:.3f}"})
        with self.assertRaises(ValueError) as cm:
            modes.runs_on_engine(self.load(doc))
        self.assertIn("mixes", str(cm.exception))

    def test_compat_refuses_a_v2_board(self):
        doc = json.loads(DEMO.read_text())
        doc["leaderboard"]["layout"] = "v2"
        with self.assertRaises(ValueError) as cm:
            study_compat.modespec_from_study(self.load(doc))
        self.assertIn("layout", str(cm.exception))

    def test_engine_studies_stay_out_of_specs(self):
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        env = dict(os.environ, PYTHONPATH="", AUTORESEARCH_DATA_ROOT=data.name,
                   AUTORESEARCH_STUDY_PATH=str(ENGINE_STUDIES))
        script = ("import modes; print(sorted(modes.ENGINE), "
                  "'branin' in modes.SPECS, 'branin' in modes.STUDIES)")
        r = subprocess.run([sys.executable, "-c", script], env=env,
                           cwd=str(ROOT / "core"), capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1],
                         "['branin'] False True")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `git add tests/fixtures/engine_studies/branin.json tests/test_study_engine.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_engine -v`
Expected: FAIL. The v2 tests fail with `must be one of ['v1']`, and the rest with `AttributeError` (`measure_sha`, `derived_env`, `runs_on_engine`).

- [ ] **Step 4: Add `derived_env` to `core/geom_template.py`**

Replace the start of `GeomTemplate.render`, from `x = list(x)` through the profiles loop, with a call to a new public method:

```python
    def derived_env(self, x: Iterable[float]) -> Dict[str, Any]:
        """Knob values, consts, derived exprs and profiles for one point: the
        env render() formats. Public so the engine hands a kit the same
        values the geometry file carries."""
        x = list(x)
        if len(x) != len(self._knob_names):
            raise ValueError(
                f"expected {len(self._knob_names)} knob values, got {len(x)}")
        env: Dict[str, Any] = dict(zip(self._knob_names, (float(v) for v in x)))
        env.update(self._consts)
        for name, compiled in self._derived.items():
            env[name] = eval_expr(compiled, dict(env))
        for name, (count, controls, clip) in self._profiles.items():
            ctrl = [eval_expr(c, dict(env)) for c in controls]
            env[name] = lagrange_profile(ctrl, count, clip)
        return env

    def render(self, x: Iterable[float]) -> str:
        env = self.derived_env(x)
        out = [f'#include "{self._base}"', ""]
        for ln in self._lines:
            out.append(self._render_line(ln, env))
        return "\n".join(out) + "\n"
```

- [ ] **Step 5: Change `core/study.py`**

1. Add `import os` to the imports.
2. In `_leaderboard`, change the layout check to `_one_of(lb["layout"], ("v1", "v2"), f"{where}[leaderboard.layout]")`, dropping the `"; 'v2' arrives with Phase B"` argument. Delete `test_layout_v2_arrives_in_phase_b` from `tests/test_study.py`: it asserts the refusal this step removes, and `test_study_engine.TestLayout.test_v2_loads` now pins v2 loading.
3. In `_derive_and_geom`, replace the error text for a non-empty `derive` with a null `geom` by:
   `f"{where}[derive]: must be empty when geom is null: derive values are computed by the geometry template, and derive without a geometry file is not supported yet"`.
4. Add the field `measure_basis: Dict[str, Any] = field(compare=False, repr=False)` after `spec_sha` in `Study`, and the method:

```python
    def measure_sha(self, kit_versions: Dict[str, str]) -> str:
        """SHA-256 of measure_basis plus each step kit's version: what a v2
        row's numbers depend on and nothing else (not the note, bounds,
        fmt, noise, constraints or leaderboard)."""
        used = sorted({s.kit for s in self.steps})
        missing = [k for k in used if k not in kit_versions]
        if missing:
            raise ValueError(f"{self.path}: measure_sha needs the version of "
                             f"kit(s) {missing}")
        blob = {"basis": self.measure_basis,
                "kit_versions": {k: kit_versions[k] for k in used}}
        return hashlib.sha256(json.dumps(
            blob, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

5. Add these helpers before `load_study_file`:

```python
def _stage_template(name: str, where: str) -> Dict[str, Any]:
    """A stage template by name: stage_entries/<name>.json in the repo, then
    <dir>/stage_entries/<name>.json for each $AUTORESEARCH_STUDY_PATH
    directory. Missing everywhere is a load error."""
    dirs = [paths.REPO_ROOT / "stage_entries"] + [
        Path(d) / "stage_entries"
        for d in os.environ.get("AUTORESEARCH_STUDY_PATH", "").split(":") if d]
    for d in dirs:
        path = d / f"{name}.json"
        if path.exists():
            try:
                doc = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise ValueError(f"{where}[entry]: {path}: invalid JSON: "
                                 f"{exc}") from None
            if not isinstance(doc, dict):
                raise ValueError(f"{where}[entry]: {path} must hold a JSON "
                                 f"object")
            return doc
    raise ValueError(f"{where}[entry]: stage template {name!r} not found; "
                     f"searched {[str(d) for d in dirs]}")


def _measure_basis(doc, steps, where) -> Dict[str, Any]:
    """What a row's numbers depend on (design, "Leaderboard rows"). kits are
    the RAW settings, so a ${ARTIFACT}/ value hashes the same for every
    operator."""
    def entry(s):
        if isinstance(s.entry, str):
            return _stage_template(s.entry, f"{where}[evaluate.{s.step}]")
        return s.entry
    return {
        "derive": doc["derive"], "geom": doc["geom"], "kits": doc["kits"],
        "steps": [{"step": s.step, "kit": s.kit, "entry": entry(s),
                   "files": list(s.files), "files_from": list(s.files_from),
                   "params": s.params, "fixed": s.fixed} for s in steps],
        "objectives": [{"metric": o["metric"], "transform": o["transform"]}
                       for o in doc["objectives"]],
        "extra_metrics": [{"metric": m["metric"]}
                          for m in doc["extra_metrics"]],
    }
```

6. In `load_study_file`, pass `measure_basis=_measure_basis(doc, steps, where)` to the `Study(...)` call.

- [ ] **Step 6: Change `core/modes.py`**

Import `kit_registry` next to the existing `study` imports (mirror the `__package__` pattern already used there):

```python
if __package__:
    from core import kit_registry  # noqa: E402
    from core.study import load_study_dirs  # noqa: E402
    from core.study_compat import modespec_from_study  # noqa: E402
else:
    import kit_registry  # noqa: E402
    from study import load_study_dirs  # noqa: E402
    from study_compat import modespec_from_study  # noqa: E402
```

Replace the `SPECS` line with:

```python
def runs_on_engine(study) -> bool:
    """True when every kit the study names runs on the contract engine
    (graph.study_run), False when none does (the Phase-A pipeline,
    graph.run). A study mixing the two can run on neither until Phase C
    moves the pipeline kits onto the engine: refused."""
    kits = kit_registry.kits_of(study)
    engine = {k for k in kits if kit_registry.KITS[k].engine}
    if engine and engine != kits:
        raise ValueError(
            f"{study.path}: mixes engine kits {sorted(engine)} with pipeline "
            f"kits {sorted(kits - engine)}; a study runs on one or the other "
            f"until Phase C")
    return bool(engine)


# Engine studies run through graph.study_run / graph.study_loop; SPECS is
# today's ModeSpec view of the pipeline studies only.
ENGINE = frozenset(n for n, s in STUDIES.items() if runs_on_engine(s))
SPECS: Dict[str, ModeSpec] = {n: modespec_from_study(s)
                               for n, s in STUDIES.items() if n not in ENGINE}
```

- [ ] **Step 7: Change `core/study_compat.py`**

Add as the first check in `modespec_from_study`:

```python
    _need(study.layout == "v1", study,
          f"its leaderboard layout is {study.layout!r}; the pipeline writes v1 "
          f"rows")
```

- [ ] **Step 8: Run the new tests, then the whole suite and golden d**

Run: `git add core/study.py core/geom_template.py core/modes.py core/study_compat.py tests/test_study.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_engine -v`
Expected: all PASS.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK. If a test builds a step whose `entry` names a template that doesn't exist, point it at a real one (`mubeam`, `mustops_ce`, `elebeam_flash`) and say so in the commit body.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b d e`
Expected: `[a] … OK`, `[b] … OK`, `[d] parity: OK`, `[e] parity: OK`. Golden d proves `render` is unchanged.

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/engine_studies/branin.json tests/test_study_engine.py tests/test_study.py core/study.py core/geom_template.py core/modes.py core/study_compat.py
git commit -m "feat(study): v2 boards, measure_sha, and engine studies

A study may declare a v2 board. measure_basis holds what a row's numbers
depend on (derive, geom, raw kits, steps with resolved stage templates,
metrics and transforms), and measure_sha adds the kit versions. A study
whose kits are all engine kits is an engine study, kept out of SPECS; a
mix is refused. GeomTemplate.derived_env exposes the render env.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 6: v2 leaderboard rows, `board_for`, and history for engine studies

**Files:**
- Modify: `core/leaderboard.py`
- Create: `core/boards.py`
- Modify: `core/botorch_predict.py`
- Modify: `surrogate/adapter.py`
- Test: `tests/test_leaderboard.py` (add `TestV2Rows`), `tests/test_boards.py`

**Interfaces:**
- Consumes: `Study.layout`, `Study.measure_sha` (Task 5).
- Produces:
  - `leaderboard.V2_META = ("handles", "spec_sha", "measure_sha", "time")`.
  - `leaderboard.MeasureMismatch(LeaderboardError)` and `leaderboard.DuplicateRow(LeaderboardError)`.
  - `Leaderboard.layout: str` (default `"v1"`; `for_study` passes `study.layout`).
  - `Leaderboard.format_line(p, context, meta=None) -> str`.
  - `Leaderboard.append(p, context, meta=None) -> bool`: True when a row was written. v2 only: False when the same name already holds the same row apart from `time`.
  - `boards.board_for(study) -> Leaderboard` (live board plus archive).
  - `botorch_predict.history_points(name) -> list[Point]`.
- A v2 row is `config | knobs | objectives | extra metrics | extra columns | handles | spec_sha | measure_sha | time`. `handles` is `step=handle` pairs joined by `,` and sorted by step (no quotes or tabs, so the TSV reader needs no quoting rules). `time` is UTC `YYYY-MM-DDTHH:MM:SSZ`.
- Appending to a v2 board: a name already on the board (live or archive) with the same values apart from `time` is a no-op returning False. With different values it is `DuplicateRow`. A `measure_sha` different from the board's rows (live or archive) is `MeasureMismatch`. Both errors quarantine the row first, like `SchemaMismatch`. v1 behaviour is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_leaderboard.py` (it already imports `Leaderboard`, `Point`, `lbm`, `st`, `tempfile`, `unittest`, `Path`). Add these imports at the top with the others:

```python
sys.path.insert(0, str(ROOT))
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402
```

Then append:

```python
META = {"handles": "toy=c1.toy", "spec_sha": "s" * 64,
        "measure_sha": "m" * 64, "time": "2026-09-24T00:00:00Z"}


class TestV2Rows(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(
            write_study(toy_doc(layout="v2"), self.tmp / "studies"))
        self.lb = Leaderboard.for_study(self.study, path=self.tmp / "b.tsv",
                                        archive_path=self.tmp / "arch.tsv")

    def pt(self, name="c1", b=1.5):
        return Point(name, [1.0, 2.0], {"branin": b, "currin": 3.0})

    def rows(self):
        return self.lb.path.read_text().splitlines()[1:]

    def test_header_ends_with_the_meta_columns(self):
        self.assertEqual(self.lb.header().rstrip("\n").split("\t")[-4:],
                         list(lbm.V2_META))

    def test_a_v2_row_needs_all_its_meta(self):
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {})
        partial = {k: v for k, v in META.items() if k != "time"}
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {}, partial)

    def test_meta_may_not_hold_a_tab(self):
        with self.assertRaises(lbm.LeaderboardError):
            self.lb.append(self.pt(), {}, dict(META, handles="a\tb"))

    def test_a_v1_row_carries_no_meta(self):
        v1 = st.load_study_file(write_study(toy_doc(name="v1toy"),
                                            self.tmp / "studies"))
        lb = Leaderboard.for_study(v1, path=self.tmp / "v1.tsv",
                                   archive_path=None)
        with self.assertRaises(lbm.LeaderboardError):
            lb.append(self.pt(), {}, META)

    def test_append_then_load(self):
        self.assertTrue(self.lb.append(self.pt(), {}, META))
        (p,) = self.lb.load()
        self.assertEqual((p.cfg, p.x, p.y),
                         ("c1", [1.0, 2.0], {"branin": 1.5, "currin": 3.0}))
        self.assertTrue(self.rows()[0].endswith(
            "\ttoy=c1.toy\t" + "s" * 64 + "\t" + "m" * 64
            + "\t2026-09-24T00:00:00Z"))

    def test_the_same_row_again_is_a_no_op(self):
        self.lb.append(self.pt(), {}, META)
        again = self.lb.append(self.pt(), {},
                               dict(META, time="2026-09-25T00:00:00Z"))
        self.assertFalse(again)
        self.assertEqual(len(self.rows()), 1)

    def test_the_same_name_with_other_values_is_refused(self):
        self.lb.append(self.pt(), {}, META)
        with self.assertRaises(lbm.DuplicateRow):
            self.lb.append(self.pt(b=2.0), {}, META)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("c1", self.lb.quarantine_path().read_text())

    def test_a_different_measurement_is_refused(self):
        self.lb.append(self.pt(), {}, META)
        with self.assertRaises(lbm.MeasureMismatch) as cm:
            self.lb.append(self.pt("c2"), {}, dict(META, measure_sha="n" * 64))
        self.assertIn("new board", str(cm.exception))
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("c2", self.lb.quarantine_path().read_text())

    def test_the_archive_counts_for_the_measurement(self):
        arch = Leaderboard.for_study(self.study, path=self.tmp / "arch.tsv",
                                     archive_path=None)
        arch.append(self.pt("a1"), {}, dict(META, measure_sha="a" * 64))
        with self.assertRaises(lbm.MeasureMismatch):
            self.lb.append(self.pt("c2"), {}, META)
        self.assertFalse(self.lb.path.exists())
```

Create `tests/test_boards.py`:

```python
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import boards  # noqa: E402
import bo_driver as bo  # noqa: E402
import botorch_predict as bp  # noqa: E402
import modes  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Point  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

META = {"handles": "toy=h1.toy", "spec_sha": "s" * 64,
        "measure_sha": "m" * 64, "time": "2026-09-24T00:00:00Z"}


class TestBoardFor(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.study = st.load_study_file(
            write_study(toy_doc(name="histtoy", layout="v2"),
                        self.tmp / "studies"))
        for patch in (
                mock.patch.object(boards, "leaderboard_live",
                                  lambda rel: self.tmp / "live" / Path(rel).name),
                mock.patch.object(boards, "leaderboard_archive",
                                  lambda rel: self.tmp / "arch" / Path(rel).name),
                mock.patch.dict(modes.STUDIES, {"histtoy": self.study})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_board_paths_come_from_the_study(self):
        board = boards.board_for(self.study)
        self.assertEqual(board.path, self.tmp / "live" / "leaderboard_histtoy.tsv")
        self.assertEqual(board.archive_path,
                         self.tmp / "arch" / "leaderboard_histtoy.tsv")
        self.assertEqual(board.layout, "v2")

    def test_an_engine_study_trains_on_its_board(self):
        boards.board_for(self.study).append(
            Point("h1", [1.0, 2.0], {"branin": 5.0, "currin": 3.0}), {}, META)
        X, Y, _, _ = bp.load_history_tensor("histtoy")
        self.assertEqual(X.tolist(), [[1.0, 2.0]])
        self.assertAlmostEqual(Y.tolist()[0][0], -5.0)
        self.assertAlmostEqual(Y.tolist()[0][1], -math.log10(3.0))

    def test_a_pipeline_study_still_reads_through_its_mode(self):
        with mock.patch.object(bo.MODES["foilspf"], "load_history",
                               return_value=[]) as m:
            self.assertEqual(bp.history_points("foilspf"), [])
        m.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `git add tests/test_boards.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_leaderboard tests.test_boards -v`
Expected: FAIL (`AttributeError: module 'leaderboard' has no attribute 'V2_META'`, `No module named 'boards'`).

- [ ] **Step 3: Change `core/leaderboard.py`**

After `PENDING_HEADER`, add:

```python
# v2 rows end in these columns (generic-study design, "Leaderboard rows").
V2_META = ("handles", "spec_sha", "measure_sha", "time")
```

After `RowParseError`, add:

```python
class MeasureMismatch(LeaderboardError):
    def __init__(self, path: Path, found, new: str, quarantined: Path):
        super().__init__(
            f"{path}: this row's measure_sha {new[:12]} differs from the "
            f"board's {sorted(s[:12] for s in found)}.\n"
            f"  row saved to quarantine: {quarantined}\n"
            f"  A board holds one measurement: a changed kit setting, step, "
            f"metric or kit version means a new board (leaderboard.file), "
            f"never mixed rows.")


class DuplicateRow(LeaderboardError):
    def __init__(self, path: Path, name: str, quarantined: Path):
        super().__init__(
            f"{path}: config {name!r} already has a row with different "
            f"values.\n  row saved to quarantine: {quarantined}")
```

In the `Leaderboard` dataclass, add after `archive_path`:

```python
    layout: str = "v1"                 # "v2" adds the V2_META columns
```

In `for_study`, pass `layout=study.layout`.

Replace `header`, `format_line` and `append`:

```python
    def header(self) -> str:
        cols = ("config", *self.knob_names, *self.value_names,
                *(c.name for c in self.extra_columns))
        if self.layout == "v2":
            cols += V2_META
        return "\t".join(cols) + "\n"

    def format_line(self, p: Point, context: dict, meta: dict | None = None) -> str:
        """The exact line append() writes. Public so a caller holding the
        only record of a row's x can validate the row before discarding
        that record."""
        missing = [c for c in self.context_names if c not in context]
        if missing:
            raise LeaderboardError(
                f"{self.name}: row {p.cfg!r} needs runtime value(s) {missing} "
                f"(leaderboard.context) and the caller did not pass them")
        knobs = [fmt.format(v) for fmt, v in zip(self.knob_fmts, p.x)]
        values = [fmt.format(p.y[n])
                  for fmt, n in zip(self.value_fmts, self.value_names)]
        env = {**self.consts, **p.y, **context}
        extras = [c.fmt.format(c.evaluate(env)) for c in self.extra_columns]
        cells = [p.cfg, *knobs, *values, *extras]
        if self.layout == "v2":
            if meta is None or set(meta) != set(V2_META):
                raise LeaderboardError(
                    f"{self.name}: a v2 row needs meta {list(V2_META)}, got "
                    f"{None if meta is None else sorted(meta)}")
            for key in V2_META:
                v = meta[key]
                if not isinstance(v, str) or not v or "\t" in v or "\n" in v:
                    raise LeaderboardError(
                        f"{self.name}: meta {key!r} must be a non-empty "
                        f"string without tabs or newlines, got {v!r}")
            cells += [meta[k] for k in V2_META]
        elif meta is not None:
            raise LeaderboardError(f"{self.name}: a v1 row carries no meta")
        return "\t".join(cells) + "\n"

    def _raw_rows(self, path: Path | None) -> list[dict]:
        """Every row of `path` as {column: text}; the caller holds the lock
        (the live board) or none is needed (the archive)."""
        if path is None or not path.exists():
            return []
        with path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = self.header().rstrip("\n").split("\t")
            return list(csv.DictReader(f, fieldnames=cols, delimiter="\t"))

    def _check_v2(self, rows: list[dict], line: str) -> bool:
        """False when this exact row (apart from `time`) is already on the
        board. Raises DuplicateRow or MeasureMismatch, quarantining first."""
        cols = self.header().rstrip("\n").split("\t")
        new = dict(zip(cols, line.rstrip("\n").split("\t")))

        def sans_time(row):
            return {k: v for k, v in row.items() if k != "time"}
        same = [r for r in rows if r["config"] == new["config"]]
        if same:
            if all(sans_time(r) == sans_time(new) for r in same):
                return False
            self._append_quarantine(self.header(), line)
            raise DuplicateRow(self.path, new["config"],
                               self.quarantine_path())
        found = {r["measure_sha"] for r in rows}
        if found and found != {new["measure_sha"]}:
            self._append_quarantine(self.header(), line)
            raise MeasureMismatch(self.path, found, new["measure_sha"],
                                  self.quarantine_path())
        return True

    def append(self, p: Point, context: dict, meta: dict | None = None) -> bool:
        """True when a row was written. On a v2 board, False when the same
        row (apart from `time`) is already there: idempotent by name."""
        line = self.format_line(p, context, meta)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _flock_ex(self.path):
            if self.path.exists():
                with self.path.open() as f:
                    first = f.readline()
                if first.rstrip("\n") != self.header().rstrip("\n"):
                    self._append_quarantine(self.header(), line)
                    raise SchemaMismatch(self.path, self.header(), first,
                                         quarantined=self.quarantine_path())
            if self.layout == "v2":
                rows = (self._raw_rows(self.archive_path)
                        + self._raw_rows(self.path))
                if not self._check_v2(rows, line):
                    return False
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return True
            with self.path.open("a") as f:
                f.write(line)
            return True
```

(Every existing v1 call site ignores `append`'s return value, so returning `True` changes nothing for them.)

- [ ] **Step 4: Write `core/boards.py`**

```python
"""board_for: the leaderboard a study writes and trains on, which is its
live board under DATA_ROOT plus the committed archive at its repo-relative
path (core/leaderboard.py owns the format)."""
from __future__ import annotations

if __package__:
    from core.leaderboard import Leaderboard
    from core.paths import leaderboard_archive, leaderboard_live
else:
    from leaderboard import Leaderboard
    from paths import leaderboard_archive, leaderboard_live


def board_for(study) -> Leaderboard:
    return Leaderboard.for_study(
        study, path=leaderboard_live(study.leaderboard_rel),
        archive_path=leaderboard_archive(study.leaderboard_rel))
```

- [ ] **Step 5: Change `core/botorch_predict.py` and `surrogate/adapter.py`**

In `core/botorch_predict.py`, add `import boards  # noqa: E402` after `import modes as _modes`, and this function before `load_history_tensor`:

```python
def history_points(name: str):
    """A study's evaluated points. Pipeline studies read through their
    JsonMode (the patchable leaderboard paths the golden harness and tests
    use); engine studies read their board directly."""
    if name in bo.MODES:
        return bo.MODES[name].load_history()
    return boards.board_for(_modes.STUDIES[name]).load()
```

In `load_history_tensor`, change `for p in bo.MODES[mode].load_history():` to `for p in history_points(mode):`.

In `surrogate/adapter.py` `_board_summary`, change `bo.MODES[name].load_history()` to `bp.history_points(name)`. Then delete `import bo_driver as bo` if nothing else in the file uses `bo`.

- [ ] **Step 6: Run the tests, the suite and goldens a b d e**

Run: `git add core/leaderboard.py core/boards.py core/botorch_predict.py surrogate/adapter.py tests/test_leaderboard.py tests/test_boards.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_leaderboard tests.test_boards -v`
Expected: all PASS.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` and `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b c d e` (c needs a muse shell and takes about 4 min)
Expected: OK, and all five sections OK. Golden a proves v1 rows are byte-identical.

- [ ] **Step 7: Commit**

```bash
git add core/leaderboard.py core/boards.py core/botorch_predict.py surrogate/adapter.py tests/test_leaderboard.py tests/test_boards.py
git commit -m "feat(leaderboard): v2 rows with measure_sha; engine studies train on their board

A v2 row ends in handles, spec_sha, measure_sha and time. Appending is
idempotent by name, and a row measured differently from the board's rows
(live or archive) is refused and quarantined. board_for(study) is the
live board plus archive; history_points reads it for engine studies.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---
### Task 7: `run_steps`, the step scheduler

**Files:**
- Create: `core/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `contract.ContractError`, `Status`, `Results` (Task 4); `kits.KitError` (Task 3); `study.Step` (Phase A). The `kits` argument is anything with `.get(name) -> Kit` (a `contract.KitSet` in production).
- Produces:
  - `scheduler.StepOutcome(step, ok, message, record)`.
  - `scheduler.write_atomic(path, text)`.
  - `scheduler.map_params(mapping, env, accepts_lists) -> dict`.
  - `scheduler.step_params(study, step, env, accepts_lists) -> dict`.
  - `scheduler.run_steps(study, *, config, state_dir, env, files, kits, workflow, sleep=time.sleep, log=print) -> dict[str, StepOutcome]`. `workflow` is a callable `step -> "<campaign>/<config>/<step>"`. `files` maps rendered file names to FileRefs.
- State files per step: `<step>_cluster.txt` (the handle plus a newline) and `<step>_results.json`. The results record holds `step`, `kit`, `kit_version`, `handle`, `params`, `inputs`, `metrics`, `files` and `metadata`. On failure `broken.txt` holds `step <name>: <message>`.

- [ ] **Step 1: Write the failing tests** — `tests/test_scheduler.py`

```python
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import scheduler as sch  # noqa: E402
from contract import ContractError, Results, Status  # noqa: E402
from kits import KitError  # noqa: E402
from study import Step  # noqa: E402


def step(name, files_from=(), params=None, fixed=None, kit="fake"):
    return Step(name, kit, None, (), tuple(files_from), dict(params or {}),
                dict(fixed or {}))


def study(*steps, kits=None):
    return types.SimpleNamespace(steps=tuple(steps), kits=dict(kits or {}))


class FakeKit:
    """A scripted contract kit: each handle walks its step's states, one per
    status call; an exception in the script is raised instead."""

    def __init__(self, scripts=None, poll_s=(0.0, 0.0), poll_ms=0):
        self.name, self.version, self.accepts_lists = "fake", "f1", False
        self.poll_s, self.poll_ms = poll_s, poll_ms
        self.scripts = scripts or {}
        self.events, self.submits = [], []
        self._pos = {}
        self._lock = threading.Lock()

    def submit(self, name, params, files, inputs, workflow):
        with self._lock:
            self.events.append(("submit", name.split(".", 1)[1]))
            self.submits.append((name, params, files, inputs, workflow))
        return name

    def status(self, handle, workflow):
        s = handle.split(".", 1)[1]
        seq = self.scripts.get(s, ["completed"])
        with self._lock:
            i = self._pos.get(handle, 0)
            self._pos[handle] = i + 1
        state = seq[min(i, len(seq) - 1)]
        if isinstance(state, Exception):
            raise state
        return Status(state, f"{s} {state}", self.poll_ms, None)

    def results(self, handle, workflow):
        s = handle.split(".", 1)[1]
        with self._lock:
            self.events.append(("done", s))
        return Results({"v": 1.0},
                       ({"name": s, "uri": f"file:///tmp/{s}", "kind": "text"},),
                       {})

    def close(self):
        pass


class Kits:
    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class _Run(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.state = Path(self._td.name) / "state"

    def run_steps(self, st, kit, env=None, sleep=None, state=None):
        return sch.run_steps(st, config="c", state_dir=state or self.state,
                             env=env or {}, files={}, kits=Kits(kit),
                             workflow=lambda s: f"camp/c/{s}",
                             sleep=sleep or (lambda s: time.sleep(0.001)),
                             log=lambda m: None)


class TestScheduling(_Run):
    def test_a_dependent_step_starts_before_a_slow_unrelated_step_ends(self):
        kit = FakeKit({"a": ["working"] * 3 + ["completed"],
                       "slow": ["working"] * 300 + ["completed"]})
        out = self.run_steps(study(step("a"), step("b", ["a"]), step("slow")),
                             kit)
        self.assertTrue(all(o.ok for o in out.values()))
        self.assertLess(kit.events.index(("submit", "b")),
                        kit.events.index(("done", "slow")))

    def test_inputs_are_the_upstream_files(self):
        kit = FakeKit()
        self.run_steps(study(step("a"), step("b", ["a"])), kit)
        b = next(s for s in kit.submits if s[0] == "c.b")
        self.assertEqual(b[3], [{"name": "a", "uri": "file:///tmp/a",
                                 "kind": "text"}])

    def test_handle_file_and_workflow(self):
        kit = FakeKit()
        self.run_steps(study(step("a")), kit)
        self.assertEqual((kit.submits[0][0], kit.submits[0][4]),
                         ("c.a", "camp/c/a"))
        self.assertEqual((self.state / "a_cluster.txt").read_text(), "c.a\n")

    def test_the_results_record_carries_provenance(self):
        self.run_steps(study(step("a", params={"p": "x1"}, fixed={"n": 2})),
                       FakeKit(), env={"x1": 0.5})
        rec = json.loads((self.state / "a_results.json").read_text())
        self.assertEqual((rec["kit"], rec["kit_version"], rec["handle"]),
                         ("fake", "f1", "c.a"))
        self.assertEqual(rec["params"], {"p": 0.5, "n": 2})
        self.assertEqual((rec["metrics"], rec["inputs"]), ({"v": 1.0}, []))


class TestFailures(_Run):
    def test_a_failed_step_stops_new_launches_and_writes_broken(self):
        kit = FakeKit({"a": ["failed"]})
        out = self.run_steps(study(step("a"), step("b", ["a"])), kit)
        self.assertFalse(out["a"].ok)
        self.assertNotIn("b", out)
        self.assertNotIn(("submit", "b"), kit.events)
        broken = (self.state / "broken.txt").read_text()
        self.assertIn("step a", broken)
        self.assertIn("a failed", broken)

    def test_running_steps_finish_after_a_failure(self):
        kit = FakeKit({"a": ["failed"], "c": ["working"] * 50 + ["completed"]})
        out = self.run_steps(study(step("a"), step("c")), kit)
        self.assertTrue(out["c"].ok)
        self.assertTrue((self.state / "c_results.json").exists())
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_a_cancelled_step(self):
        out = self.run_steps(study(step("a")), FakeKit({"a": ["cancelled"]}))
        self.assertFalse(out["a"].ok)
        self.assertIn("cancelled", out["a"].message)

    def test_a_kit_error_fails_the_step(self):
        kit = FakeKit({"a": [KitError("fake", "status", "boom")]})
        out = self.run_steps(study(step("a")), kit)
        self.assertFalse(out["a"].ok)
        self.assertIn("boom", out["a"].message)

    def test_a_reply_outside_the_contract_fails_the_step(self):
        kit = FakeKit({"a": [ContractError("fake", "status", "bad state")]})
        out = self.run_steps(study(step("a")), kit)
        self.assertIn("outside the contract", out["a"].message)


class TestResume(_Run):
    def test_a_results_file_skips_the_step(self):
        self.state.mkdir(parents=True)
        rec = {"step": "a", "kit": "fake", "kit_version": "f1", "handle": "c.a",
               "params": {}, "inputs": [], "metrics": {"v": 2.0},
               "files": [{"name": "old", "uri": "file:///old", "kind": "text"}],
               "metadata": {}}
        (self.state / "a_results.json").write_text(json.dumps(rec))
        kit = FakeKit()
        out = self.run_steps(study(step("a"), step("b", ["a"])), kit)
        self.assertEqual([s[0] for s in kit.submits], ["c.b"])
        self.assertEqual(out["a"].record["metrics"], {"v": 2.0})
        self.assertEqual(kit.submits[0][3], rec["files"])

    def test_a_handle_file_is_polled_not_resubmitted(self):
        self.state.mkdir(parents=True)
        (self.state / "a_cluster.txt").write_text("c.a\n")
        kit = FakeKit()
        out = self.run_steps(study(step("a")), kit)
        self.assertEqual(kit.submits, [])
        self.assertTrue(out["a"].ok)


class TestPolling(_Run):
    def test_the_poll_hint_is_clamped_to_the_kit_bounds(self):
        for poll_ms, expected in ((10, 0.5), (1500, 1.5), (10000, 2.0)):
            with self.subTest(poll_ms=poll_ms):
                slept = []
                kit = FakeKit({"a": ["working", "completed"]}, poll_s=(0.5, 2.0),
                              poll_ms=poll_ms)
                self.run_steps(study(step("a")), kit, sleep=slept.append,
                               state=self.state / str(poll_ms))
                self.assertEqual(slept, [expected])


class TestParams(unittest.TestCase):
    def test_mapped_then_settings_then_fixed(self):
        st_ = study(step("a", params={"p": "x"}, fixed={"n": 3, "mode": "fast"}),
                    kits={"fake": {"mode": "slow", "tag": "t"}})
        self.assertEqual(sch.step_params(st_, st_.steps[0], {"x": 1.5}, False),
                         {"p": 1.5, "mode": "fast", "tag": "t", "n": 3})

    def test_a_profile_is_flattened_for_a_kit_without_lists(self):
        st_ = study(step("a", params={"r": "prof"}))
        env = {"prof": [1.0, 2.0]}
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, False),
                         {"r_0": 1.0, "r_1": 2.0})
        self.assertEqual(sch.step_params(st_, st_.steps[0], env, True),
                         {"r": [1.0, 2.0]})

    def test_a_mapped_param_may_not_clash_with_a_setting(self):
        st_ = study(step("a", params={"n": "x"}, fixed={"n": 3}))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(st_, st_.steps[0], {"x": 1.0}, False)
        self.assertIn("['n']", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_scheduler -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler'`.

- [ ] **Step 3: Write `core/scheduler.py`**

```python
"""run_steps: the one per-point node that runs a study's steps
(generic-study design, "One point, end to end", step 4).

A step starts as soon as every step in its files_from has completed, and
ready steps run concurrently in threads, so a slow independent step never
holds back a dependent chain. One LangGraph node per step would: LangGraph
finishes a whole superstep before starting the next, which is the wait
today's presubmit_after works around.

Each step works from its state files, which is what makes a killed child
resumable with no second submit:
  state/<step>_results.json  done: adopt the record, skip the step
  state/<step>_cluster.txt   submitted: poll that handle
  neither                    submit, then write the handle
A failed or cancelled step, a kit error, or a reply outside the contract
stops new launches; running steps finish; broken.txt names the first step
that failed. A failed step is never retried.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

if __package__:
    from core.contract import ContractError
    from core.kits import KitError
else:
    from contract import ContractError
    from kits import KitError


@dataclass(frozen=True)
class StepOutcome:
    step: str
    ok: bool
    message: str
    record: Optional[Dict[str, Any]]    # the <step>_results.json content


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def map_params(mapping: Dict[str, str], env: Dict[str, Any],
               accepts_lists: bool) -> Dict[str, Any]:
    """Kit param name -> the value of the knob, const, expr or profile it
    names. A profile goes to a kit that takes no lists flattened as
    <param>_0 ... <param>_{N-1}."""
    out: Dict[str, Any] = {}
    for key, name in mapping.items():
        value = env[name]
        if isinstance(value, list) and not accepts_lists:
            out.update({f"{key}_{i}": v for i, v in enumerate(value)})
        else:
            out[key] = list(value) if isinstance(value, list) else value
    return out


def step_params(study, step, env, accepts_lists) -> Dict[str, Any]:
    """The mapped params, then the study's settings for the step's kit, then
    the step's fixed values, which win over the settings. A mapped param may
    not share a name with a setting or a fixed value."""
    mapped = map_params(step.params, env, accepts_lists)
    constant = {**study.kits.get(step.kit, {}), **step.fixed}
    clash = sorted(set(mapped) & set(constant))
    if clash:
        raise ValueError(f"step {step.step!r}: param(s) {clash} are both "
                         f"mapped from the point and set in kits/fixed")
    return {**mapped, **constant}


def run_steps(study, *, config: str, state_dir: Path, env, files, kits,
              workflow: Callable[[str], str], sleep=time.sleep,
              log=print) -> Dict[str, StepOutcome]:
    state_dir.mkdir(parents=True, exist_ok=True)
    outcomes: Dict[str, StepOutcome] = {}
    for s in study.steps:
        path = state_dir / f"{s.step}_results.json"
        if path.exists():
            outcomes[s.step] = StepOutcome(s.step, True, "adopted",
                                           json.loads(path.read_text()))
            log(f"[steps] {s.step}: adopted {path.name}")
    pending = [s for s in study.steps if s.step not in outcomes]
    failed: Optional[StepOutcome] = None
    with ThreadPoolExecutor(max_workers=max(1, len(pending))) as pool:
        running = {}
        while True:
            if failed is None:
                for s in list(pending):
                    if all(d in outcomes and outcomes[d].ok
                           for d in s.files_from):
                        pending.remove(s)
                        upstream = {d: outcomes[d].record for d in s.files_from}
                        fut = pool.submit(_run_one, study, s, config,
                                          state_dir, env, files, kits,
                                          upstream, workflow(s.step), sleep,
                                          log)
                        running[fut] = s.step
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                name = running.pop(fut)
                out = fut.result()      # _run_one reports errors as outcomes
                outcomes[name] = out
                log(f"[steps] {name}: "
                    f"{'completed' if out.ok else 'FAILED: ' + out.message}")
                if not out.ok and failed is None:
                    failed = out
    if failed is not None:
        write_atomic(state_dir / "broken.txt",
                     f"step {failed.step}: {failed.message}\n")
    return outcomes


def _run_one(study, step, config, state_dir, env, files, kits, upstream,
             workflow, sleep, log) -> StepOutcome:
    try:
        kit = kits.get(step.kit)
        params = step_params(study, step, env, kit.accepts_lists)
        step_files = [files[f] for f in step.files]
        inputs = [ref for up in step.files_from for ref in upstream[up]["files"]]
        handle_path = state_dir / f"{step.step}_cluster.txt"
        if handle_path.exists():
            handle = handle_path.read_text().strip()
            log(f"[steps] {step.step}: polling {handle} (submitted by an "
                f"earlier run)")
        else:
            handle = kit.submit(f"{config}.{step.step}", params, step_files,
                                inputs, workflow)
            write_atomic(handle_path, handle + "\n")
            log(f"[steps] {step.step}: submitted {handle}")
        lo, hi = kit.poll_s
        while True:
            status = kit.status(handle, workflow)
            if status.state == "completed":
                break
            if status.state in ("failed", "cancelled"):
                return StepOutcome(step.step, False,
                                   f"{status.state}: {status.message}", None)
            sleep(min(max(status.poll_ms / 1000.0, lo), hi))
        res = kit.results(handle, workflow)
        record = {"step": step.step, "kit": step.kit,
                  "kit_version": kit.version, "handle": handle,
                  "params": params, "inputs": inputs,
                  "metrics": res.metrics, "files": list(res.files),
                  "metadata": res.metadata}
        write_atomic(state_dir / f"{step.step}_results.json",
                     json.dumps(record, indent=1, sort_keys=True))
        return StepOutcome(step.step, True, "completed", record)
    except (KitError, ContractError, KeyError, ValueError) as exc:
        return StepOutcome(step.step, False, f"{type(exc).__name__}: {exc}",
                           None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `git add core/scheduler.py tests/test_scheduler.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_scheduler -v`
Expected: all PASS, in under 5 s. Run it three times: the ordering test must never flake. If it does, raise the `slow` script to 1000 states; do not add sleeps to the scheduler.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add core/scheduler.py tests/test_scheduler.py
git commit -m "feat(engine): run_steps, one scheduler node for the step DAG

Each step starts as soon as its own files_from steps finish, so a slow
independent step never holds back a dependent chain (LangGraph's superstep
barrier would). State files make a killed child resumable with no second
submit; a failure stops new launches and writes broken.txt.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 8: `score`, from step results to one row

**Files:**
- Create: `core/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `scheduler.write_atomic` and the results-record shape (Task 7); `Leaderboard.append(p, context, meta) -> bool`, `MeasureMismatch` (Task 6); `Study.measure_sha`, `Study.layout` (Task 5).
- Produces:
  - `score.ScoreError(ValueError)`.
  - `score.collect(study, records) -> dict[str, float]`.
  - `score.kit_versions(records) -> dict[str, str]`.
  - `score.row_meta(study, records, now=None) -> dict`.
  - `score.score(study, *, config, x, records, context, board, state_dir, now=None) -> dict`. It returns the `evaluate_result.json` payload `{config, primary, objectives, row_appended}`. `records` maps step name to that step's results record. A `ScoreError` writes `broken.txt` (`score: <reason>`) before raising. A `LeaderboardError` from the board propagates, and the caller records it.
- Files written: `summary.json` (`{config, x, steps: {step: metrics}}`) and `evaluate_result.json`.

- [ ] **Step 1: Write the failing tests** — `tests/test_score.py`

```python
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import leaderboard as lbm  # noqa: E402
import score as sc  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

GOOD = {"branin": 1.5, "currin": 3.0, "n_inputs": 0.0}


def rec(metrics, step="toy", handle="c.toy", version="1"):
    return {"step": step, "kit": "toykit", "kit_version": version,
            "handle": handle, "params": {}, "inputs": [], "metrics": metrics,
            "files": [], "metadata": {}}


class _Score(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.state = self.tmp / "state"
        self.state.mkdir()

    def study(self, mutate=lambda d: None, layout="v2", name="scoretoy"):
        doc = toy_doc(name=name, layout=layout)
        mutate(doc)
        return st.load_study_file(write_study(doc, self.tmp / "studies"))

    def board(self, study):
        return Leaderboard.for_study(study, path=self.tmp / f"{study.name}.tsv",
                                     archive_path=None)

    def score(self, study, records, board=None, config="c"):
        return sc.score(study, config=config, x=[1.0, 2.0], records=records,
                        context={}, board=board or self.board(study),
                        state_dir=self.state, now=0)


class TestRows(_Score):
    def test_a_row_and_the_summary_files(self):
        study = self.study()
        board = self.board(study)
        res = self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(res, {"config": "c", "primary": 1.5,
                               "objectives": {"branin": 1.5, "currin": 3.0},
                               "row_appended": True})
        self.assertEqual(json.loads((self.state / "evaluate_result.json")
                                    .read_text()), res)
        summary = json.loads((self.state / "summary.json").read_text())
        self.assertEqual((summary["x"], summary["steps"]),
                         ([1.0, 2.0], {"toy": GOOD}))
        row = board.path.read_text().splitlines()[1].split("\t")
        self.assertEqual(row[-4:], ["toy=c.toy", study.spec_sha,
                                    study.measure_sha({"toykit": "1"}),
                                    "1970-01-01T00:00:00Z"])

    def test_scoring_again_lands_no_second_row(self):
        study = self.study()
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertFalse(self.score(study, {"toy": rec(GOOD)}, board)
                         ["row_appended"])
        self.assertEqual(len(board.path.read_text().splitlines()), 2)

    def test_extra_metrics_are_recorded(self):
        study = self.study(lambda d: d["extra_metrics"].append(
            {"name": "n_in", "metric": "toy.n_inputs", "fmt": "{:.0f}"}))
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(board.load()[0].y["n_in"], 0.0)

    def test_a_v1_study_writes_a_v1_row(self):
        study = self.study(layout="v1", name="scorev1")
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board)
        self.assertEqual(len(board.path.read_text().splitlines()[1]
                             .split("\t")), 5)


class TestFailedEvaluations(_Score):
    def assertFails(self, records, *needles, study=None):
        study = study or self.study()
        board = self.board(study)
        with self.assertRaises(sc.ScoreError) as cm:
            self.score(study, records, board)
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertIn("score:", (self.state / "broken.txt").read_text())
        self.assertFalse(board.path.exists())

    def test_a_missing_metric(self):
        self.assertFails({"toy": rec({"branin": 1.5})}, "currin", "missing")

    def test_a_step_with_no_results(self):
        self.assertFails({}, "toy", "no results")

    def test_not_a_finite_number(self):
        self.assertFails({"toy": rec(dict(GOOD, branin=math.nan))},
                         "branin", "finite")

    def test_nonpositive_under_log10(self):
        self.assertFails({"toy": rec(dict(GOOD, currin=0.0))}, "currin",
                         "log10")

    def test_one_kit_on_two_versions(self):
        def two_steps(d):
            d["evaluate"].append({"step": "toy2", "kit": "toykit",
                                  "entry": None, "files": [],
                                  "files_from": [],
                                  "params": {"x1": "x1", "x2": "x2"},
                                  "fixed": {}})
            d["extra_metrics"].append({"name": "b2", "metric": "toy2.branin",
                                       "fmt": "{:.3f}"})
        self.assertFails({"toy": rec(GOOD),
                          "toy2": rec(GOOD, step="toy2", handle="c.toy2",
                                      version="2")},
                         "version", study=self.study(two_steps))


class TestBoardRefusals(_Score):
    def test_a_board_measured_another_way_refuses_the_row(self):
        study = self.study()
        board = self.board(study)
        self.score(study, {"toy": rec(GOOD)}, board, config="c1")
        with self.assertRaises(lbm.MeasureMismatch):
            self.score(study, {"toy": rec(GOOD, handle="c2.toy", version="2")},
                       board, config="c2")
        self.assertEqual(len(board.path.read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_score -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'score'`.

- [ ] **Step 3: Write `core/score.py`**

```python
"""score: a finished point's step records -> objectives, extra metrics, the
summary files and one leaderboard row (generic-study design, "One point,
end to end", step 5).

A missing metric, a value that is not a finite number, or a value <= 0
under log10 is a failed evaluation naming the metric: never a row, never a
0 (ADR-0002).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict

if __package__:
    from core.leaderboard import Point
    from core.scheduler import write_atomic
else:
    from leaderboard import Point
    from scheduler import write_atomic


class ScoreError(ValueError):
    """The point's results cannot make a row."""


def _value(metric: str, records, what: str) -> float:
    step, key = metric.split(".", 1)
    record = records.get(step)
    if record is None:
        raise ScoreError(f"{what}: step {step!r} has no results")
    if key not in record["metrics"]:
        raise ScoreError(f"{what}: metric {metric!r} is missing from step "
                         f"{step!r}'s results (it returned "
                         f"{sorted(record['metrics'])})")
    v = record["metrics"][key]
    if (isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v)):
        raise ScoreError(f"{what}: metric {metric!r} is not a finite number: "
                         f"{v!r}")
    return float(v)


def collect(study, records) -> Dict[str, float]:
    """{name: value} for every objective and extra metric."""
    y: Dict[str, float] = {}
    for o in study.objectives:
        v = _value(o.metric, records, f"objective {o.name!r}")
        if o.transform == "log10" and v <= 0:
            raise ScoreError(f"objective {o.name!r}: metric {o.metric!r} is "
                             f"{v!r}, and its log10 transform needs a value > 0")
        y[o.name] = v
    for m in study.extra_metrics:
        y[m.name] = _value(m.metric, records, f"extra metric {m.name!r}")
    return y


def kit_versions(records) -> Dict[str, str]:
    """One version per kit. Steps of one kit that ran on different versions
    (a step adopted from before a kit upgrade) measured different things."""
    seen: Dict[str, set] = {}
    for r in records.values():
        seen.setdefault(r["kit"], set()).add(r["kit_version"])
    mixed = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    if mixed:
        raise ScoreError(f"a kit changed version within this point {mixed}; "
                         f"its steps were measured with different builds")
    return {k: next(iter(v)) for k, v in seen.items()}


def row_meta(study, records, now=None) -> Dict[str, str]:
    return {"handles": ",".join(f"{s}={r['handle']}"
                                for s, r in sorted(records.items())),
            "spec_sha": study.spec_sha,
            "measure_sha": study.measure_sha(kit_versions(records)),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}


def score(study, *, config: str, x, records, context, board,
          state_dir: Path, now=None) -> Dict[str, Any]:
    """Write summary.json, append the row, write evaluate_result.json and
    return its payload. A ScoreError writes broken.txt first; a leaderboard
    refusal propagates for the caller to record."""
    try:
        y = collect(study, records)
        meta = row_meta(study, records, now) if study.layout == "v2" else None
    except ScoreError as exc:
        write_atomic(state_dir / "broken.txt", f"score: {exc}\n")
        raise
    write_atomic(state_dir / "summary.json", json.dumps(
        {"config": config, "x": list(x),
         "steps": {s: r["metrics"] for s, r in sorted(records.items())}},
        indent=1, sort_keys=True))
    appended = board.append(Point(cfg=config, x=list(x), y=y), context, meta)
    result = {"config": config, "primary": y[study.objectives[0].name],
              "objectives": {o.name: y[o.name] for o in study.objectives},
              "row_appended": appended}
    write_atomic(state_dir / "evaluate_result.json",
                 json.dumps(result, indent=1))
    return result
```

- [ ] **Step 4: Run the tests, then the suite, then commit**

Run: `git add core/score.py tests/test_score.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_score -v`
Expected: all PASS.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add core/score.py tests/test_score.py
git commit -m "feat(engine): score step results into one row

Objectives and extra metrics come from the step records by study name. A
missing metric, a non-number, or <= 0 under log10 fails the evaluation and
writes broken.txt; a v2 row carries handles, spec_sha, measure_sha (with
the kits' versions) and time. Scoring twice lands one row.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 9: The per-point graph and the `graph.study_run` child

**Files:**
- Create: `graph/study_graph.py`
- Create: `graph/study_run.py`
- Modify: `tests/engine_fixtures.py` (add `engine_env`)
- Test: `tests/test_study_run.py`

**Interfaces:**
- Consumes: `modes.STUDIES`, `modes.ENGINE` (Task 5); `boards.board_for` (Task 6); `contract.KitSet`, `ContractError` (Task 4); `scheduler.run_steps`, `map_params`, `write_atomic` (Task 7); `score.score`, `ScoreError` (Task 8); `leaderboard.LeaderboardError`.
- Produces:
  - `study_graph.PointMismatch(ValueError)`.
  - `study_graph.check_x(study, x)`, which raises `ValueError`.
  - `study_graph.build_study_graph(study, *, config, campaign, context, kits, state_dir, board, log=print) -> StateGraph`.
  - The CLI `python -m graph.study_run --study S --config C --campaign P --x v1,v2,... [--context name=value ...]`. It exits 0 when the point ran (a row, or `broken.txt` saying why not) and 2 on a refusal before anything ran.
  - `engine_fixtures.engine_env(data_root, study_dir) -> dict`.
- State directory: `<GRID_DATA_ROOT>/<config>/state/`, holding `point.json`, `derived.json`, `geom.txt` (when the study has a geometry), `preflight_verdict.json` (when it has a preflight), the per-step files, `summary.json`, `evaluate_result.json` and `broken.txt`.
- Refusals (exit 2, nothing submitted):
  - an unknown study, or a pipeline study;
  - `x` of the wrong length or outside the knob bounds;
  - a missing `--context` value;
  - an existing `broken.txt`;
  - a `point.json` recording a different point under the same config.

- [ ] **Step 1: Add `engine_env` to `tests/engine_fixtures.py`**

```python
def engine_env(data_root, study_dir):
    """Environment for an engine subprocess: every runtime root under
    `data_root` (never the real DATA_ROOT), studies from `study_dir`."""
    import os
    env = dict(os.environ)
    env.update(AUTORESEARCH_DATA_ROOT=str(data_root),
               AUTORESEARCH_STUDY_PATH=str(study_dir), PYTHONPATH="")
    return env
```

- [ ] **Step 2: Write the failing tests** — `tests/test_study_run.py`

```python
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests import toykit  # noqa: E402
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402


class _Point(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.studies = self.tmp / "studies"
        self.studies.mkdir(parents=True)
        self.data = self.tmp / "data"
        self.env = engine_env(self.data, self.studies)

    def add_study(self, mutate=lambda d: None, name="pointtoy"):
        doc = toy_doc(name=name, layout="v2")
        mutate(doc)
        write_study(doc, self.studies)
        return name

    @staticmethod
    def cmd(study, config, x):
        # "--x=" form: argparse reads "--x -3.0,2.0" as a flag, not a value.
        return [sys.executable, "-m", "graph.study_run", "--study", study,
                "--config", config, "--campaign", "t",
                "--x=" + ",".join(str(v) for v in x)]

    def run_point(self, study, config="p1", x=(1.0, 2.0)):
        return subprocess.run(self.cmd(study, config, x), cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=120)

    def state(self, config="p1"):
        return self.data / "autoresearch_grid" / config / "state"

    def board_rows(self, study):
        path = (self.data / "autoresearch_leaderboards"
                / f"leaderboard_{study}.tsv")
        return path.read_text().splitlines()[1:] if path.exists() else []

    def submits(self):
        path = self.data / "toykit" / "submits.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln)["name"] for ln in path.read_text().splitlines()]


class TestAPoint(_Point):
    def test_a_point_lands_one_row(self):
        s = self.add_study()
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = self.board_rows(s)
        self.assertTrue(row.startswith("p1\t1.000000\t2.000000\t"))
        res = json.loads((self.state() / "evaluate_result.json").read_text())
        self.assertAlmostEqual(res["primary"], toykit.branin(1.0, 2.0),
                               places=5)
        for name in ("point.json", "derived.json", "toy_cluster.txt",
                     "toy_results.json", "summary.json"):
            self.assertTrue((self.state() / name).exists(), name)
        trace = (self.data / "autoresearch_graph_data" / "t"
                 / "kit_trace.jsonl").read_text()
        self.assertIn('"workflow": "t/p1/toy"', trace)
        self.assertEqual(self.submits(), ["p1.toy"])

    def test_a_negative_knob_value(self):
        s = self.add_study()
        r = self.run_point(s, x=(-3.0, 2.0))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (row,) = self.board_rows(s)
        self.assertTrue(row.startswith("p1\t-3.000000\t2.000000\t"))


class TestFailedPoints(_Point):
    def assertBroken(self, r, *needles):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.state() / "broken.txt").read_text()
        for n in needles:
            self.assertIn(n, text)

    def test_a_failed_step(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(fail="failed"))
        self.assertBroken(self.run_point(s), "step toy", "asked to fail")
        self.assertEqual(self.board_rows(s), [])

    def test_a_missing_metric(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(
            fail="missing_metric"))
        self.assertBroken(self.run_point(s), "score", "currin")
        self.assertEqual(self.board_rows(s), [])

    def test_a_rejected_preflight_submits_nothing(self):
        def reject(d):
            d["preflight"] = {"kit": "toykit", "params": {"x1": "x1"},
                              "files": []}
            d["kits"]["toykit"]["function"] = "reject"
        s = self.add_study(reject)
        self.assertBroken(self.run_point(s), "preflight", "reject")
        self.assertEqual(self.submits(), [])
        verdict = json.loads((self.state() / "preflight_verdict.json").read_text())
        self.assertFalse(verdict["ok"])

    def test_a_board_measured_another_way_refuses_the_row(self):
        s = self.add_study()
        self.assertEqual(self.run_point(s).returncode, 0)
        self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=0.1))
        r = self.run_point(s, config="p2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("measure_sha",
                      (self.state("p2") / "broken.txt").read_text())
        self.assertEqual(len(self.board_rows(s)), 1)


class TestRefusals(_Point):
    def assertRefused(self, r, *needles):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for n in needles:
            self.assertIn(n, r.stdout)
        self.assertEqual(self.submits(), [])

    def test_x_outside_the_box(self):
        self.assertRefused(self.run_point(self.add_study(), x=(11.0, 2.0)),
                           "x1", "outside")

    def test_x_of_the_wrong_length(self):
        self.assertRefused(self.run_point(self.add_study(), x=(1.0,)),
                           "2 knobs")

    def test_a_pipeline_study(self):
        self.assertRefused(self.run_point("foilspf"), "graph.run")

    def test_a_broken_point_is_not_rerun(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(fail="failed"))
        self.run_point(s)
        r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("broken.txt", r.stdout)

    def test_a_different_x_under_the_same_name(self):
        s = self.add_study()
        self.run_point(s)
        r = self.run_point(s, x=(3.0, 4.0))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("point.json", r.stdout)
        self.assertEqual(self.submits(), ["p1.toy"])


class TestResume(_Point):
    def test_a_child_killed_mid_step_resumes_without_a_second_submit(self):
        s = self.add_study(lambda d: d["evaluate"][0]["fixed"].update(delay_s=4.0))
        proc = subprocess.Popen(self.cmd(s, "p1", (1.0, 2.0)), cwd=ROOT,
                                env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        handle = self.state() / "toy_cluster.txt"
        deadline = time.monotonic() + 60
        while not handle.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(handle.exists(), "the child never submitted")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        self.assertEqual(self.board_rows(s), [])
        r = self.run_point(s)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("submitted by an earlier run", r.stdout)
        self.assertEqual(self.submits(), ["p1.toy"])
        self.assertEqual(len(self.board_rows(s)), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `git add tests/engine_fixtures.py tests/test_study_run.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_run -v`
Expected: FAIL (every subprocess exits 1 with `No module named graph.study_run`).

- [ ] **Step 4: Write `graph/study_graph.py`**

```python
"""The per-point graph for a study on the contract engine (generic-study
design, "One point, end to end"): derive -> render -> preflight ->
run_steps -> score, built from the Study. Kits come in through a KitSet
the caller owns and closes. No checkpointer: the state files are the
durability, so a killed child re-run on the same point adopts its steps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from contract import ContractError  # noqa: E402
from kits import KitError  # noqa: E402
from leaderboard import LeaderboardError  # noqa: E402
from scheduler import map_params, run_steps, write_atomic  # noqa: E402
from score import ScoreError, score  # noqa: E402


class PointMismatch(ValueError):
    """point.json records a different point under this config name."""


class PointState(TypedDict, total=False):
    config_name: str
    x_point: List[float]
    broken: bool
    reason: str
    objective: Optional[float]


def check_x(study, x) -> None:
    """One value per knob, each inside its knob's bounds."""
    if len(x) != len(study.knobs):
        raise ValueError(f"x has {len(x)} value(s); study {study.name!r} has "
                         f"{len(study.knobs)} knobs {list(study.knob_names)}")
    for knob, v in zip(study.knobs, x):
        if not knob.min <= v <= knob.max:
            raise ValueError(f"x: knob {knob.name!r} = {v!r} is outside its "
                             f"bounds [{knob.min}, {knob.max}]")


def build_study_graph(study, *, config: str, campaign: str, context: dict,
                      kits, state_dir: Path, board, log=print) -> StateGraph:
    def workflow(step: str) -> str:
        return f"{campaign}/{config}/{step}"

    shared: Dict[str, Any] = {}     # env, x, files, records: process-local

    def broken(reason: str) -> dict:
        path = state_dir / "broken.txt"
        if not path.exists():
            write_atomic(path, reason + "\n")
        log(f"[study_run] {config}: broken: {reason}")
        return {"broken": True, "reason": reason}

    def node_derive(state):
        x = [float(v) for v in state["x_point"]]
        check_x(study, x)
        env = (study.geom.derived_env(x) if study.geom is not None
               else dict(zip(study.knob_names, x)))
        state_dir.mkdir(parents=True, exist_ok=True)
        point = {"study": study.name, "config": config, "campaign": campaign,
                 "x": x, "context": context}
        point_path = state_dir / "point.json"
        if point_path.exists():
            old = json.loads(point_path.read_text())
            if old != point:
                raise PointMismatch(
                    f"{point_path} records a different point {old}; refusing "
                    f"to mix two points under one config name")
        else:
            write_atomic(point_path, json.dumps(point, indent=1, sort_keys=True))
        write_atomic(state_dir / "derived.json",
                     json.dumps(env, indent=1, sort_keys=True))
        shared["env"], shared["x"] = env, x
        return {"broken": False}

    def node_render(state):
        files = {}
        if study.geom is not None:
            path = state_dir / "geom.txt"
            write_atomic(path, study.geom.render(shared["x"]))
            files["geom"] = {"name": "geom", "uri": path.resolve().as_uri(),
                             "kind": "geom"}
        shared["files"] = files
        return {"broken": False}

    def node_preflight(state):
        pre = study.preflight
        if pre is None:
            return {"broken": False}
        try:
            kit = kits.get(pre["kit"])
            params = {**map_params(pre["params"], shared["env"],
                                   kit.accepts_lists),
                      **study.kits.get(pre["kit"], {})}
            ok, message = kit.check(f"{config}.preflight", params,
                                    [shared["files"][f] for f in pre["files"]],
                                    [], workflow("preflight"))
        except (KitError, ContractError, KeyError, ValueError) as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        write_atomic(state_dir / "preflight_verdict.json",
                     json.dumps({"ok": ok, "message": message}, indent=1))
        return {"broken": False} if ok else broken(f"preflight: {message}")

    def node_run_steps(state):
        outcomes = run_steps(study, config=config, state_dir=state_dir,
                             env=shared["env"], files=shared["files"],
                             kits=kits, workflow=workflow, log=log)
        failed = [o for o in outcomes.values() if not o.ok]
        if failed:
            return broken(f"step {failed[0].step}: {failed[0].message}")
        shared["records"] = {s: o.record for s, o in outcomes.items()}
        return {"broken": False}

    def node_score(state):
        try:
            result = score(study, config=config, x=shared["x"],
                           records=shared["records"], context=context,
                           board=board, state_dir=state_dir)
        except (ScoreError, LeaderboardError) as exc:
            return broken(f"score: {exc}")
        log(f"[study_run] {config}: primary={result['primary']} "
            f"row_appended={result['row_appended']}")
        return {"objective": result["primary"]}

    def route(state):
        return END if state.get("broken") else "next"

    g = StateGraph(PointState)
    for name, fn in (("derive", node_derive), ("render", node_render),
                     ("preflight", node_preflight),
                     ("run_steps", node_run_steps), ("score", node_score)):
        g.add_node(name, fn)
    g.add_edge(START, "derive")
    g.add_edge("derive", "render")
    g.add_edge("render", "preflight")
    g.add_conditional_edges("preflight", route, {"next": "run_steps", END: END})
    g.add_conditional_edges("run_steps", route, {"next": "score", END: END})
    g.add_edge("score", END)
    return g
```

- [ ] **Step 5: Write `graph/study_run.py`**

```python
"""One point of a study on the contract engine; graph/study_loop.py spawns
one per child. By hand:
  python -m graph.study_run --study branin --config brn001 --campaign brn --x=-1.5,2.25
(Write --x=... : argparse reads "--x -1.5,..." as a flag.)
Exit 0: the point ran (a leaderboard row, or broken.txt saying why not).
Exit 2: refused before anything ran. Anything else: a crash.
Phase C renames this to graph.run when the pipeline path is deleted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import modes as _modes  # noqa: E402
from boards import board_for  # noqa: E402
from contract import KitSet  # noqa: E402
from paths import GRID_DATA_ROOT  # noqa: E402
from study_graph import PointMismatch, build_study_graph, check_x  # noqa: E402


def refuse(message: str) -> int:
    print(f"[study_run] REFUSED: {message}", flush=True)
    return 2


def parse_context(pairs, study) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"--context {pair!r}: expected name=value")
        if key not in study.context:
            raise ValueError(f"--context {key!r}: study {study.name!r} "
                             f"declares context {list(study.context)}")
        out[key] = float(value)
    missing = [c for c in study.context if c not in out]
    if missing:
        raise ValueError(f"study {study.name!r} needs --context for {missing}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--config", required=True,
                    help="the point's name; state in <GRID_DATA_ROOT>/<config>/state")
    ap.add_argument("--campaign", required=True,
                    help="groups the kit trace: GRAPH_DATA/<campaign>/kit_trace.jsonl")
    ap.add_argument("--x", required=True,
                    help="comma-separated knob values, in the study's knob order")
    ap.add_argument("--context", action="append", default=[],
                    help="name=value for each leaderboard.context value")
    args = ap.parse_args(argv)

    if args.study not in _modes.STUDIES:
        return refuse(f"unknown study {args.study!r}; known "
                      f"{sorted(_modes.STUDIES)}")
    if args.study not in _modes.ENGINE:
        return refuse(f"study {args.study!r} runs on the pipeline kits; use "
                      f"graph.run / graph.closed_loop until Phase C")
    study = _modes.STUDIES[args.study]
    try:
        x = [float(v) for v in args.x.split(",")]
        check_x(study, x)
        context = parse_context(args.context, study)
    except ValueError as exc:
        return refuse(str(exc))
    state_dir = GRID_DATA_ROOT / args.config / "state"
    broken = state_dir / "broken.txt"
    if broken.exists():
        return refuse(f"{broken} exists: this point already failed "
                      f"({broken.read_text().strip()}). Remove {state_dir} to "
                      f"run it again")

    kits = KitSet(args.campaign)
    try:
        graph = build_study_graph(
            study, config=args.config, campaign=args.campaign,
            context=context, kits=kits, state_dir=state_dir,
            board=board_for(study)).compile()
        graph.invoke({"config_name": args.config, "x_point": x})
    except PointMismatch as exc:
        return refuse(str(exc))
    finally:
        kits.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `git add graph/study_graph.py graph/study_run.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_run -v`
Expected: all PASS, in under 90 s. If `test_a_child_killed_mid_step_resumes_without_a_second_submit` shows two submits, the resumed child did not find `toy_cluster.txt`. Check that `run_steps` writes the handle file before its first status call.

- [ ] **Step 7: Run the whole suite, then commit**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK.

```bash
git add graph/study_graph.py graph/study_run.py tests/engine_fixtures.py tests/test_study_run.py
git commit -m "feat(engine): the per-point graph and the graph.study_run child

derive -> render -> preflight -> run_steps -> score, built from the study.
A point lands one row or writes broken.txt; a killed child re-run on the
same point adopts its submitted step. Bad x, a pipeline study, a broken
point or a different x under the same name are refused before any submit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---
### Task 10: The campaign runner `graph.study_loop`, and the Branin acceptance

**Files:**
- Modify: `graph/pool.py` (add `next_free_name`; `_default_pick_source` uses it)
- Create: `graph/study_loop.py`
- Modify: `tests/test_pool.py` (add `TestNextFreeName`)
- Modify: `tests/test_generic_core.py` (STRICT list)
- Test: `tests/test_study_loop.py`

**Interfaces:**
- Consumes: `pool.run_rolling`, `pool.child_name`, `pool.SKIP_LOG_LIMIT` (existing); `contract.check_kits`, `launch_stagger` (Task 4); `boards.board_for` (Task 6); `botorch_predict.compute_explore_picks` (existing, now study-generic via `history_points`); `graph.study_run` (Task 9).
- Produces:
  - `pool.next_free_name(name_prefix, start, busy_reason, *, log, summary_hint) -> (name, index)`.
  - `study_loop.state_dir(name) -> Path` and `study_loop.busy_reason(name, board_names) -> str | None`.
  - `study_loop.make_pick_source(study, name_prefix, pick)` and `study_loop.surrokit_pick(study)`.
  - `study_loop.make_run_child(study, campaign, context_args)`.
  - The CLI `python -m graph.study_loop --study S --q N --max-evals M --name-prefix P [--picker K] [--stagger S] [--context name=value ...]`. It exits 0 when done, 1 when the pool aborted, and 2 when refused at launch.
- The campaign name is the `--name-prefix`. The stop flag is `GRAPH_DATA/<prefix>/STOP`. Child logs go to `GRAPH_DATA/closed_loop_logs/<child>.log`.
- A name is busy, and skipped, when it has a board row, `broken.txt`, `point.json` or any `*_cluster.txt`. The last two cover a killed runner whose children are still running.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pool.py`:

```python
class TestNextFreeName(unittest.TestCase):
    def test_skips_busy_names_and_summarises_after_the_limit(self):
        n = pool.SKIP_LOG_LIMIT + 3
        busy = {pool.child_name("p", i) for i in range(n)}
        lines = []
        name, i = pool.next_free_name(
            "p", 0, lambda nm: "busy" if nm in busy else None,
            log=lines.append, summary_hint="HINT")
        self.assertEqual((name, i), (pool.child_name("p", n), n))
        self.assertEqual(sum(ln.startswith("[pool] SKIP") for ln in lines),
                         pool.SKIP_LOG_LIMIT)
        self.assertIn("3 further", lines[-1])
        self.assertIn("HINT", lines[-1])

    def test_a_free_start_is_returned_as_is(self):
        lines = []
        self.assertEqual(pool.next_free_name("p", 4, lambda nm: None,
                                             log=lines.append, summary_hint=""),
                         ("pR04_00", 4))
        self.assertEqual(lines, [])
```

Create `tests/test_study_loop.py`:

```python
import json
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402
import study_loop  # noqa: E402
from tests import toykit  # noqa: E402
from tests.engine_fixtures import (ENGINE_STUDIES, engine_env,  # noqa: E402
                                   toy_doc, write_study)


def loop_cmd(study, q, max_evals, prefix, picker="budget_sob"):
    return [sys.executable, "-m", "graph.study_loop", "--study", study,
            "--q", str(q), "--max-evals", str(max_evals), "--picker", picker,
            "--name-prefix", prefix]


def board_rows(data, study):
    path = data / "autoresearch_leaderboards" / f"leaderboard_{study}.tsv"
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


def submits(data):
    path = data / "toykit" / "submits.jsonl"
    return ([json.loads(ln)["name"] for ln in path.read_text().splitlines()]
            if path.exists() else [])


class TestBusyNames(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        patch = mock.patch.object(paths, "GRID_DATA_ROOT", Path(self._td.name))
        patch.start()
        self.addCleanup(patch.stop)

    def touch(self, name, file):
        sd = study_loop.state_dir(name)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / file).write_text("x\n")

    def test_every_busy_signal(self):
        self.touch("pR01_00", "broken.txt")
        self.touch("pR02_00", "point.json")
        self.touch("pR03_00", "toy_cluster.txt")
        for name, needle in (("pR00_00", "leaderboard row"),
                             ("pR01_00", "broken.txt"),
                             ("pR02_00", "in flight"),
                             ("pR03_00", "in flight")):
            with self.subTest(name=name):
                self.assertIn(needle, study_loop.busy_reason(name, {"pR00_00"}))
        self.assertIsNone(study_loop.busy_reason("pR04_00", {"pR00_00"}))

    def test_the_pick_source_skips_busy_names_and_seeds_by_index(self):
        self.touch("pR00_00", "toy_cluster.txt")
        self.touch("pR01_00", "broken.txt")
        calls = []

        def pick(round_idx, picker, x_pending):
            calls.append((round_idx, picker, x_pending))
            return [0.0, 0.0]

        board = types.SimpleNamespace(load=lambda: [])
        with mock.patch.object(study_loop, "board_for", return_value=board):
            nxt = study_loop.make_pick_source(object(), "p", pick)
            self.assertEqual(nxt("s", "budget_sob", [])[1], "pR02_00")
            self.assertEqual(nxt("s", "budget_sob", [[1.0, 1.0]])[1], "pR03_00")
        self.assertEqual(calls, [(2, "budget_sob", []),
                                 (3, "budget_sob", [[1.0, 1.0]])])


class TestBraninCampaign(unittest.TestCase):
    """The Phase B acceptance: a toy study runs end to end from its JSON file
    alone (Branin, 2 objectives, 1 constraint, q = 2, 8 evaluations) in
    under a minute."""

    def test_eight_points_in_under_a_minute(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            t0 = time.monotonic()
            r = subprocess.run(loop_cmd("branin", 2, 8, "brn"), cwd=ROOT,
                               env=engine_env(data, ENGINE_STUDIES),
                               capture_output=True, text=True, timeout=180)
            elapsed = time.monotonic() - t0
            self.assertEqual(r.returncode, 0,
                             r.stdout[-3000:] + r.stderr[-3000:])
            rows = board_rows(data, "branin")
            names = [f"brnR{i:02d}_00" for i in range(8)]
            self.assertEqual(sorted(row["config"] for row in rows), names)
            self.assertEqual(len({row["measure_sha"] for row in rows}), 1)
            for row in rows:
                x1, x2 = float(row["x1"]), float(row["x2"])
                self.assertEqual(row["handles"], f"toy={row['config']}.toy")
                self.assertTrue(-5.0 <= x1 <= 10.0 and 0.0 <= x2 <= 15.0)
                self.assertAlmostEqual(float(row["branin"]),
                                       toykit.branin(x1, x2), places=3)
            self.assertEqual(sorted(submits(data)),
                             [f"{n}.toy" for n in names])
            self.assertLess(elapsed, 60, f"the campaign took {elapsed:.1f} s")


class TestRunnerRestart(unittest.TestCase):
    def test_a_killed_runner_restarts_without_reusing_a_name(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, studies = tmp / "data", tmp / "studies"
            doc = toy_doc(name="slowtoy", layout="v2")
            doc["evaluate"][0]["fixed"]["delay_s"] = 5.0
            write_study(doc, studies)
            env = engine_env(data, studies)
            cmd = loop_cmd("slowtoy", 2, 2, "rst")
            runner = subprocess.Popen(cmd, cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            handles = [data / "autoresearch_grid" / f"rstR0{i}_00" / "state"
                       / "toy_cluster.txt" for i in (0, 1)]
            deadline = time.monotonic() + 60
            while (not all(h.exists() for h in handles)
                   and time.monotonic() < deadline):
                time.sleep(0.2)
            self.assertTrue(all(h.exists() for h in handles))
            runner.kill()           # the parent only: children have own sessions
            runner.wait()
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                               text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
            self.assertIn("SKIP rstR00_00", r.stdout)
            self.assertIn("SKIP rstR01_00", r.stdout)
            deadline = time.monotonic() + 60
            while (len(board_rows(data, "slowtoy")) < 4
                   and time.monotonic() < deadline):
                time.sleep(0.2)
            names = sorted(row["config"] for row in board_rows(data, "slowtoy"))
            self.assertEqual(names, [f"rstR0{i}_00" for i in range(4)])
            self.assertEqual(sorted(submits(data)),
                             [f"rstR0{i}_00.toy" for i in range(4)])


class TestLaunchRefusals(unittest.TestCase):
    def test_a_study_its_kit_rejects_launches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data, studies = tmp / "data", tmp / "studies"
            doc = toy_doc(name="badtoy", layout="v2")
            doc["evaluate"][0]["params"]["x3"] = "x1"
            write_study(doc, studies)
            r = subprocess.run(loop_cmd("badtoy", 1, 1, "bad"), cwd=ROOT,
                               env=engine_env(data, studies),
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("x3", r.stdout)
            self.assertFalse((data / "autoresearch_graph_data"
                              / "closed_loop_logs").exists())

    def test_a_pipeline_study_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(loop_cmd("foilspf", 1, 1, "pipe"), cwd=ROOT,
                               env=engine_env(Path(td), ENGINE_STUDIES),
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("graph.closed_loop", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_generic_core.py`, extend `STRICT`:

```python
STRICT = ["core/study.py", "core/leaderboard.py", "core/kit_config.py",
          "core/kits.py", "core/contract.py", "core/boards.py",
          "core/scheduler.py", "core/score.py", "graph/study_graph.py",
          "graph/study_run.py", "graph/study_loop.py"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `git add tests/test_study_loop.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_pool.TestNextFreeName tests.test_study_loop -v`
Expected: FAIL (`AttributeError: module 'pool' has no attribute 'next_free_name'`, `No module named 'study_loop'`).

- [ ] **Step 3: Add `next_free_name` to `graph/pool.py`**

Add after `child_name`:

```python
def next_free_name(name_prefix, start, busy_reason, *, log, summary_hint):
    """(name, index) of the first name at or after index `start` that
    busy_reason(name) calls free (None). Skips are logged, capped at
    SKIP_LOG_LIMIT lines plus one summary line ending in `summary_hint`."""
    i, skipped = start, 0
    while True:
        name = child_name(name_prefix, i)
        why = busy_reason(name)
        if why is None:
            break
        if skipped < SKIP_LOG_LIMIT:
            log(f"[pool] SKIP {name}: {why}")
        skipped += 1
        i += 1
    if skipped > SKIP_LOG_LIMIT:
        log(f"[pool] ... and {skipped - SKIP_LOG_LIMIT} further consecutive "
            f"busy names skipped (last was {child_name(name_prefix, i - 1)}); "
            f"resuming at {name}. {summary_hint}")
    return name, i
```

In `_default_pick_source.next_pick`, replace the `skipped = 0` / `while True` / summary block, and the `counter["i"] = i + 1` that follows it, with:

```python
        name, i = next_free_name(
            name_prefix, counter["i"],
            lambda n: _name_busy_reason(cl, n, lb_names, pending_names),
            log=lambda m: print(m, flush=True),
            summary_hint=("Reasons are the same four signals as above -- see "
                          "graph/pool.py::_name_busy_reason."))
        counter["i"] = i + 1
```

Also delete the now-unused `i = counter["i"]` line at the top of `next_pick`. The printed lines are byte-identical to before; `tests/test_pool.py::TestNameSkip` must pass unchanged.

- [ ] **Step 4: Write `graph/study_loop.py`**

```python
"""A campaign over a study on the contract engine: q children in flight
through graph/pool.py's rolling pool, each child one `graph.study_run`
point, picks from surrokit through core/botorch_predict.py.
  python -m graph.study_loop --study branin --q 2 --max-evals 8 --picker budget_sob --name-prefix brn
check_kits must pass before anything launches. To stop launching, touch
GRAPH_DATA/<name-prefix>/STOP; running children drain. Phase C folds this
into graph/closed_loop.py when the pipeline path is deleted.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import modes as _modes  # noqa: E402
import paths  # noqa: E402
from boards import board_for  # noqa: E402
from contract import check_kits, launch_stagger  # noqa: E402
from pool import next_free_name, run_rolling  # noqa: E402


def state_dir(name: str) -> Path:
    return paths.GRID_DATA_ROOT / name / "state"


def busy_reason(name: str, board_names: set) -> str | None:
    """Why `name` must not be launched again, or None if it is free. A row
    or broken.txt means a prior run RESOLVED it; point.json or a
    *_cluster.txt means a child under it may still be IN FLIGHT (a runner
    killed while its children run). Launching it again would submit the
    same <config>.<step> names from two children."""
    if name in board_names:
        return ("already has a leaderboard row from a prior run under this "
                "--name-prefix")
    sd = state_dir(name)
    if (sd / "broken.txt").exists():
        return (f"already carries {sd / 'broken.txt'} from a prior run under "
                f"this --name-prefix")
    if (sd / "point.json").exists() or any(sd.glob("*_cluster.txt")):
        return (f"has state in {sd}: a child under this name is in flight or "
                f"was abandoned. Advancing to the next index. RECOVERY: "
                f"confirm nothing runs it (pgrep -f 'study_run.*{name}'), then "
                f"remove {sd} or use another --name-prefix")
    return None


def make_pick_source(study, name_prefix, pick):
    """next_pick for pool.run_rolling. `pick(round_idx, picker, x_pending)`
    returns one x; the board is read once per process, like the pipeline's
    pick source (graph/pool.py::_default_pick_source)."""
    counter = {"i": 0}
    seen = {}

    def next_pick(mode, picker, x_pending):
        if "board" not in seen:
            seen["board"] = {p.cfg for p in board_for(study).load()}
        name, i = next_free_name(
            name_prefix, counter["i"],
            lambda n: busy_reason(n, seen["board"]),
            log=lambda m: print(m, flush=True),
            summary_hint="Reasons as logged above -- see "
                         "graph/study_loop.py::busy_reason.")
        counter["i"] = i + 1
        return pick(i, picker, x_pending), name
    return next_pick


def surrokit_pick(study):
    """One pick per launch, seeded 42 ^ round_idx like the pipeline's."""
    def pick(round_idx, picker, x_pending):
        import botorch_predict as bp
        picks = bp.compute_explore_picks(study.name, q=1, round_idx=round_idx,
                                         picker=picker,
                                         x_pending=x_pending or None)
        return [float(v) for v in picks[0]]
    return pick


def make_run_child(study, campaign, context_args):
    """Popen `graph.study_run` and WAIT: the wait is the barrier."""
    def run_child(name, x):
        logs = paths.GRAPH_DATA / "closed_loop_logs"
        logs.mkdir(parents=True, exist_ok=True)
        # "--x=" form: argparse reads "--x -3.2,..." as a flag, not a value.
        cmd = [sys.executable, "-m", "graph.study_run", "--study", study.name,
               "--config", name, "--campaign", campaign,
               "--x=" + ",".join(repr(float(v)) for v in x)]
        for pair in context_args:
            cmd += ["--context", pair]
        with open(logs / f"{name}.log", "w") as fh:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                    cwd=str(paths.REPO_ROOT))
        return proc.wait()
    return run_child


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--q", type=int, required=True,
                    help="children kept in flight at once")
    ap.add_argument("--max-evals", type=int, required=True,
                    help="points to launch in total")
    ap.add_argument("--picker", choices=_modes.PICKER_CHOICES,
                    default=_modes.DEFAULT_PICKER)
    ap.add_argument("--name-prefix", required=True,
                    help="child names are {prefix}R{i:02d}_00; also the "
                         "campaign name")
    ap.add_argument("--stagger", type=float, default=None,
                    help="seconds between launches (default: the largest "
                         "launch_stagger_s of the study's kits)")
    ap.add_argument("--context", action="append", default=[],
                    help="name=value, passed to every child")
    args = ap.parse_args(argv)

    if args.study not in _modes.STUDIES:
        print(f"[study_loop] REFUSED: unknown study {args.study!r}; known "
              f"{sorted(_modes.STUDIES)}", flush=True)
        return 2
    if args.study not in _modes.ENGINE:
        print(f"[study_loop] REFUSED: study {args.study!r} runs on the "
              f"pipeline kits; use graph.closed_loop until Phase C", flush=True)
        return 2
    study = _modes.STUDIES[args.study]
    problems = check_kits(study, campaign=args.name_prefix)
    if problems:
        for problem in problems:
            print(f"[study_loop] REFUSED: {problem}", flush=True)
        return 2
    stagger = launch_stagger(study) if args.stagger is None else args.stagger
    stop = paths.GRAPH_DATA / args.name_prefix / "STOP"
    print(f"[study_loop] study={study.name} q={args.q} "
          f"max_evals={args.max_evals} picker={args.picker} "
          f"prefix={args.name_prefix} board={board_for(study).path} "
          f"stagger={stagger:g}s", flush=True)
    result = run_rolling(
        mode=study.name, picker=args.picker, q=args.q,
        max_evals=args.max_evals, alpha=None, name_prefix=args.name_prefix,
        run_child=make_run_child(study, args.name_prefix, args.context),
        next_pick=make_pick_source(study, args.name_prefix,
                                   surrokit_pick(study)),
        stop_flag=stop.exists,
        row_landed=lambda name, mode: name in {p.cfg for p in
                                               board_for(study).load()},
        broken=lambda name: (state_dir(name) / "broken.txt").exists(),
        stagger=stagger)
    tally = Counter(oc.reason for oc in result["outcomes"])
    print(f"[study_loop] done: launched={result['launched']} "
          f"rows={result['rows']} aborted={result['aborted']} | "
          + ", ".join(f"{k}={n}" for k, n in sorted(tally.items())),
          flush=True)
    return 1 if result["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `git add graph/pool.py graph/study_loop.py tests/test_pool.py tests/test_generic_core.py && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_pool tests.test_study_loop tests.test_generic_core -v`
Expected: all PASS. The acceptance test prints nothing on success and must finish its campaign in under 60 s.

If the acceptance campaign takes over 60 s, find the slow part in its child logs (`closed_loop_logs/*.log`) before changing anything. The budget is roughly 3 s of picker import in the parent, about 3 s per child (interpreter, LangGraph, the toykit server), and four waves at q = 2. Do not raise the limit, and do not drop evaluations.

- [ ] **Step 6: Run the whole suite and all five goldens**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: OK. Report the new total in the commit body.

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check a b c d e`
Expected: all five OK (c takes about 4 min).

- [ ] **Step 7: Commit**

```bash
git add graph/pool.py graph/study_loop.py tests/test_pool.py tests/test_generic_core.py tests/test_study_loop.py
git commit -m "feat(engine): graph.study_loop campaigns; the Branin acceptance

A study on the contract engine runs as a campaign from its JSON file
alone: check_kits gates the launch, the rolling pool keeps q
graph.study_run children in flight, picks come from surrokit. Branin
(2 objectives, 1 constraint, q = 2, 8 evaluations) lands 8 rows in under
a minute; a killed runner restarts without reusing a name.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 11: Documentation — the design amendments, the wiki, the glossary

**Files:**
- Modify: `docs/superpowers/specs/2026-09-23-generic-study-design.md`
- Create: `wiki/drivers/contract-engine.md`
- Modify: `wiki/index.md`, `wiki/log.md`, `wiki/drivers/tests.md`
- Modify: `CONTEXT.md`, `mode_specs/README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Amend the design spec** where Phase B made a concrete choice the spec left open or stated differently:
  - **"One point, end to end", step 4:** replace "It polls `status` at `poll_ms`, clamped to 30 s–10 min." with "It polls `status` at `poll_ms`, clamped to the kit's `poll_s` bounds in `kits.toml` (30 s–10 min for grid kits; `toykit` uses 0.1–2 s so CI runs in seconds)."
  - **"One point, end to end", first line:** add after it: "Until Phase C deletes the pipeline path, the engine's child is `python -m graph.study_run` and its campaign runner is `python -m graph.study_loop`; Phase C renames them to `graph.run` and `graph.closed_loop`."
  - **"The evaluator contract" bullets:** add three:
    - "Replies must carry the keys this table names, with the right types; keys it doesn't name are ignored."
    - "`submit`'s handle must equal the name it was given."
    - "A kit's version is the `serverInfo.version` its MCP server reports at initialize (an adapter's own constant), and `check_kits` refuses a kit that reports none, because `measure_sha` needs it."
  - **"Adapters and plugins" → "Registry":** add "Native kits are `kits.toml` entries with the keys `command`, `env_passthrough`, `set`, `study_keys`, `fixed_keys`, `accepts_lists`, `check`, `launch_stagger_s`, `poll_s` and `timeouts`, all required. An adapter is a class registered in `core/contract.py`'s `ADAPTERS`, taking the campaign name, with a `LAUNCH_STAGGER_S` attribute."
  - **"Kit client" → "Retries":** replace "`status`, `results`, `describe` and server start get up to 3 bounded retries" with "`status`, `results`, `check` and `describe` get up to 3 bounded retries, and a server that fails to start or dies is restarted inside those attempts. At launch, `check_kits` starts each kit once and refuses the campaign if one won't start."
  - **"Leaderboard" → `layout`:** delete "`\"v2\"` arrives with Phase B."; and make the v2 row line read `name | each knob | each objective | each extra metric | extra columns | handles | spec_sha | measure_sha | time` (a v2 row keeps the extra columns).
  - **`measure_sha` bullet:** replace "and each kit's reported version" with "and the reported version of each kit a step runs on (the preflight kit gates a point but does not produce its numbers, so only its settings in `kits` are hashed)".
  - **Results-record bullet:** replace "records the kit's version and environment (from `describe`), its `params` and its input file list" with "records the kit and its version, its `params`, its inputs, and the kit's `files` and `metadata`. The kit's environment from `describe` is not recorded in Phase B."
  - **"Failures and recovery" table, the "A child or the runner crashes" row:** make the result read "Adopted from the state files (`point.json`, `<step>_cluster.txt`, `<step>_results.json`); no second submit, and at most one row. A restarted runner skips every name that has state, rather than adopting its child."

- [ ] **Step 2: Write `wiki/drivers/contract-engine.md`**

It needs the OKF frontmatter (`type: driver`, `title`, `description`, `status: active`, `timestamp: '<today>'`), then Summary, Key facts, Cross-links, and Open questions. The Key facts must cover, each one line with the file it lives in:
- `kits.toml` and its keys, and the tokens `${PYTHON}` / `${REPO_ROOT}` / `${DATA_ROOT}` / `${NAME}`;
- the SDK environment allowlist, which is why `env_passthrough` exists;
- `KitClient`: a timeout keeps the session and a lost server respawns on the next call;
- the retry policy in `NativeKit`;
- the `run_steps` state files, and why a scheduler node rather than one node per step (the superstep barrier);
- `measure_sha`: what is in it, what is not, and that the kit version is `serverInfo.version`;
- v2 row columns, and `handles` as `step=handle` pairs;
- `graph.study_run` exit codes 0 and 2;
- `graph.study_loop` busy names (row, `broken.txt`, `point.json`, `*_cluster.txt`) and the stop flag `GRAPH_DATA/<prefix>/STOP`;
- `toykit` fail modes and `TOYKIT_STATE_DIR`;
- the acceptance timing you measured in Task 10.

Link to `drivers/closed-loop-runner.md`, `drivers/surrogate.md`, `drivers/tests.md` and `concepts/closed-loop-bo-design.md`.

- [ ] **Step 3: Update the index, the log and the tests page**
  - `wiki/index.md` → Drivers: add `- [contract-engine](/drivers/contract-engine.md) — Phase B engine: kits.toml native kits over stdio MCP (KitClient), the evaluator contract (NativeKit, check_kits), run_steps (one scheduler node, state-file resume), v2 rows with measure_sha, graph.study_run / graph.study_loop; toykit Branin acceptance in <measured> s`.
  - `wiki/log.md`: under today's `## YYYY-MM-DD` heading at the TOP (create it if absent), add one bullet: `- **created** [contract-engine](/drivers/contract-engine.md): the Phase B contract engine; ...` with the one-line facts above.
  - `wiki/drivers/tests.md`: update the file and test counts (frontmatter `description` and body) and `timestamp`. Name the new test files, and note that the engine subprocess tests set `AUTORESEARCH_DATA_ROOT` to a temp dir and add about 2 minutes to the suite.

- [ ] **Step 4: Update `CONTEXT.md` and `mode_specs/README.md`**
  - `CONTEXT.md` glossary: add **Kit** (an MCP server that evaluates steps), **Native kit** (speaks the evaluator contract; one `kits.toml` entry), **Adapter** (Python that speaks the contract for a kit that doesn't), **Engine study** (every kit it names is an engine kit; runs through `graph.study_run`) as opposed to a **Pipeline study** (foilspf until Phase C), and **measure_sha**.
  - `mode_specs/README.md`: add a short section, "Engine studies". A study whose kits are all engine kits runs through `graph.study_loop`. Its board should be `"layout": "v2"`. Studies outside the repo go in a directory on `$AUTORESEARCH_STUDY_PATH`. Point to `tests/fixtures/engine_studies/branin.json` as the example.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-23-generic-study-design.md wiki/drivers/contract-engine.md wiki/index.md wiki/log.md wiki/drivers/tests.md CONTEXT.md mode_specs/README.md
git commit -m "docs: the Phase B contract engine in the spec, wiki and glossary

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

## Out of scope for Phase B (Phase C and later)

- The prodtools adapter, the stage templates holding every stage-specific value, and the three plugins (`offline_preflight` from the code tarball, `ce_sensitivity`, `flash_edep_per_pot`), which wait on prodtools P1 and P2.
- Moving foilspf onto the engine, and deleting the pipeline path, `study_compat.py` and `ModeSpec`.
- Credential renewal for engine campaigns: `toykit` needs none. Phase C adds it with the prodtools adapter.
- `derive` without a geometry file.
- beamkit (Phase D) and a second Offline study (Phase E).
