# Phase C1: the prodtools kit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a study whose steps all run on prodtools run on the contract engine, locally or on the grid, from its JSON file alone.

**Architecture:** An in-process adapter, `core/adapters/prodtools.py`, speaks the evaluator contract and calls the prodtools read and write MCP servers through the existing `KitClient`. Its plain helpers (entry rendering, the code tarball, input staging) live in `core/adapters/prodtools_entry.py`, which the old pipeline also calls, so the two runners share one copy until C3 deletes the pipeline. The engine gains `--executor grid|local`, zero-knob studies, retry backoff, and cancelling the other steps when one fails. A small prodtools change, P3, adds `cancel_run`.

**Tech Stack:** Python 3 (ana 2.8.0 via `$AUTORESEARCH_PYTHON`), `unittest`, LangGraph, the `mcp` 2.x SDK; prodtools' own stdlib-only test suite for P3.

**Spec:** `docs/superpowers/specs/2026-09-25-prodtools-kit-design.md`

## Global Constraints

- Test command (autoresearch): `source ./activate.sh && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` — the suite must be green at every commit.
- Test command (prodtools, Task 9 only), from the prodtools checkout's root: `env -i PATH=/usr/bin:/bin HOME=$HOME /usr/bin/python3 -m unittest test.test_unit`.
- `core/kit_config.py`, `core/kit_registry.py` and `core/study.py` are STDLIB ONLY (their headers say so).
- No silent fallbacks: every refusal names the field or value and the rule. A missing number is never replaced by a default.
- Every `kits.toml` key is required and unknown keys are rejected (ADR-0002).
- No personal user path (`/exp/mu2e/(app|data)/users/<name>`) in tracked source under `core`, `graph`, `tests`, `tools`, `mode_specs` (`tests/test_no_hardcoded_paths.py`).
- Scratch and outputs under `/exp/mu2e/data/users/oksuzian/`, never `/tmp` — except the two existing `/tmp` conventions this plan reuses on purpose: the host-wide submit lock `/tmp/mu2e_submit.<user>.lock` and the spack cache `/tmp/spack_cache_<user>`.
- Nothing is pushed, and nothing is submitted to the grid, without the operator's go-ahead.
- Stage explicit paths only (`git add <path> ...`, never `-A` or `.`).
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

## Review Focus

1. A config name with `-` or `.` (people name configs `smoke-1`): `submit` must refuse it, naming the character, before anything reaches prodtools. Pinned by `test_config_names_with_other_characters_are_refused` (Task 7).
2. An upstream step whose successful jobs produced no file matching its `output_glob`: that step must fail, instead of the downstream step failing later inside json2jobdef. Pinned by `test_no_output_matching_the_glob_fails` (Task 7).
3. Two steps of one config building the code tarball at the same moment (`mubeam` and `elebeam_flash` start together): both must get the same valid tarball. Pinned by `test_two_builders_at_once_get_one_valid_tarball` (Task 6).
4. run_status replies are JSON, so `outputs` is keyed by string indices: the adapter must read them. The fake server in Task 7 always uses string keys; pinned by `test_done_is_completed_and_results_carry_files_and_metadata`.
5. A read-server error reply other than `not_found` (an expired token): retried, then raised; never read as "no such run", which would make `submit` submit a second time. Pinned by `test_an_error_reply_other_than_not_found_is_raised_after_retries` (Task 7).

---

### Task 1: Registry flags, the runner rule, required `quorum`, `fatal_log_codes`

**Files:**
- Modify: `core/kit_registry.py` (validators, `KitDecl`, `KITS`, `_native_decl`)
- Modify: `core/study.py` (`_steps`: required fixed keys)
- Modify: `core/modes.py` (`runs_on_engine`)
- Modify: `mode_specs/{foilsflash,foilspf,foilspf2k,foilspfbp,foilspfbpx,foilspfbpz,foilspfbw}.json`, `tests/fixtures/studies/demo.json`, `tests/fixtures/modes/template.json`
- Modify: `stage_entries/mustops_ce.json`, `core/pipeline.py` (comment block above `_render_fcl_overrides`)
- Modify: `tests/golden_parity.py` (section d's declared changes)
- Test: `tests/test_study.py`, `tests/test_study_engine.py`, `tests/test_contract.py`

**Interfaces:**
- Produces: `kit_registry.KitDecl(name, study_keys, fixed_keys, required_fixed, uses_entries, step_kit, check_kit, engine, pipeline)` — every field required; `kit_registry.MAX_JOBS_PER_STEP = 200`; `modes.runs_on_engine(study) -> bool` with the three-way rule. `prodtools` stays `engine=False` here; Task 7 flips it when the adapter exists.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_study.py`:

```python
class TestProdtoolsKeys(_Tmp):
    def test_a_prodtools_step_without_quorum_is_refused(self):
        doc = _doc()
        del _step(doc, "mubeam")["fixed"]["quorum"]
        self.assertRejects(doc, "evaluate[0]", "quorum")

    def test_njobs_over_200_is_refused(self):
        doc = _doc()
        _step(doc, "elebeam_flash")["fixed"]["njobs"] = 201
        self.assertRejects(doc, "njobs", "200")

    def test_fatal_log_codes_must_be_a_list_of_strings(self):
        for bad in ("GeomSolids1001", [""], [3]):
            doc = _doc()
            doc["kits"]["prodtools"]["fatal_log_codes"] = bad
            with self.subTest(bad=bad):
                self.assertRejects(doc, "fatal_log_codes")

    def test_the_fixture_carries_the_codes_and_every_quorum(self):
        s = st.load_study_file(FIXTURE)
        self.assertEqual(s.kits["prodtools"]["fatal_log_codes"],
                         ["GeomSolids1001"])
        for step in s.steps:
            if step.kit == "prodtools":
                self.assertIn("quorum", step.fixed, step.step)
```

In `tests/test_study_engine.py`, class `TestEngineClassification`: change the needle of `test_a_mixed_study_is_refused` from `"mixes"` to `"no single runner"`, and add (import `dataclasses` and `from unittest import mock` at the top if absent):

```python
    def test_a_study_both_runners_can_drive_runs_on_the_engine(self):
        both = dataclasses.replace(kit_registry.KITS["toykit"],
                                   name="bothkit", pipeline=True)
        doc = toy_doc()
        doc["kits"] = {"bothkit": {"function": "branin_currin"}}
        doc["evaluate"][0]["kit"] = "bothkit"
        with mock.patch.dict(kit_registry.KITS, {"bothkit": both}):
            self.assertTrue(modes.runs_on_engine(self.load(doc)))
```

(`kit_registry` must be imported in that test module; add `import kit_registry  # noqa: E402` next to the other `core` imports if it is not.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study.TestProdtoolsKeys tests.test_study_engine.TestEngineClassification -v`
Expected: FAIL — `quorum` not required, `fatal_log_codes` unknown key, `pipeline` not a field of `KitDecl`, the mixed study still says "mixes".

- [ ] **Step 3: Implement the registry**

In `core/kit_registry.py`, change the typing import to `from typing import Callable, Dict, FrozenSet`, and add after `_number`:

```python
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
```

Replace the `KitDecl` dataclass and the `KITS` table with:

```python
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
            engine=False, pipeline=True),
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
```

In `_native_decl`, pass `required_fixed=frozenset()` and `pipeline=False` (keep `engine=True`). Update the module docstring's last sentence to: "Phase C gives the pipeline kits engine support one by one; a kit either runner can drive has both flags."

- [ ] **Step 4: Enforce required fixed keys in the loader**

In `core/study.py`, `_steps`, right after the `fixed = kit_registry.validate(...)` line:

```python
        missing = sorted(decl.required_fixed - set(fixed))
        if missing:
            raise ValueError(f"{sw}[fixed]: kit {kit!r} needs {missing} in "
                             f"every step's fixed")
```

- [ ] **Step 5: The three-way runner rule**

Replace `runs_on_engine` in `core/modes.py` with:

```python
def runs_on_engine(study) -> bool:
    """True when the contract engine can drive every kit the study names
    (graph.study_run); False when it cannot but the old pipeline can drive
    every kit (graph.run). A study no single runner can drive whole is
    refused. Phase C3 deletes the pipeline and with it the second branch."""
    kits = kit_registry.kits_of(study)
    decls = {k: kit_registry.KITS[k] for k in kits}
    if all(d.engine for d in decls.values()):
        return True
    if all(d.pipeline for d in decls.values()):
        return False
    engine_only = sorted(k for k, d in decls.items() if not d.pipeline)
    pipeline_only = sorted(k for k, d in decls.items() if not d.engine)
    raise ValueError(
        f"{study.path}: no single runner can drive all its kits: "
        f"{engine_only} run only on the engine and {pipeline_only} only on "
        f"the pipeline")
```

- [ ] **Step 6: Update the study files and fixtures**

Run this once from the repo root; it edits text in place (the files are hand-formatted, one step per line), and asserts each replacement happened exactly once:

```python
import pathlib
FILES = ["mode_specs/foilsflash.json", "mode_specs/foilspf.json",
         "mode_specs/foilspf2k.json", "mode_specs/foilspfbp.json",
         "mode_specs/foilspfbpx.json", "mode_specs/foilspfbpz.json",
         "mode_specs/foilspfbw.json", "tests/fixtures/studies/demo.json"]
OLD_FLASH = ('"fixed": {"njobs": 100, "events_per_job": 110000, '
             '"memory_mb": 2000}}')
NEW_FLASH = ('"fixed": {"njobs": 100, "events_per_job": 110000, '
             '"memory_mb": 2000, "quorum": 0.8}}')
for f in FILES:
    p = pathlib.Path(f)
    s = p.read_text()
    assert s.count(OLD_FLASH) == 1, f
    s = s.replace(OLD_FLASH, NEW_FLASH)
    head = '"prodtools": {"code_tarball": '
    i = s.index(head)
    j = s.index("}", i)
    assert s.count(head) == 1, f
    s = s[:j] + ', "fatal_log_codes": ["GeomSolids1001"]' + s[j:]
    p.write_text(s)
t = pathlib.Path("tests/fixtures/modes/template.json")
s = t.read_text()
for step in ("mubeam", "mustops_ce", "elebeam_flash"):
    old = f'"entry": "{step}", '
    i = s.index(old)
    j = s.index('"fixed": {}', i)
    s = s[:j] + '"fixed": {"quorum": 0.8}' + s[j + len('"fixed": {}'):]
head = '"prodtools": {"code_tarball": '
i = s.index(head)
j = s.index("}", i)
s = s[:j] + ', "fatal_log_codes": ["GeomSolids1001"]' + s[j:]
t.write_text(s)
```

Then `git diff --stat` must show exactly those 9 files, each with 2 lines changed (template.json: 4).

- [ ] **Step 7: `MaxEventsToSkip` in the `mustops_ce` template**

In `stage_entries/mustops_ce.json`, change `"physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip": 100720` to `8000`, and append to the end of the `_comment` string (before its closing quote): ` MaxEventsToSkip is 8000 here, in the template: the prolog leaves it nil and art aborts at ResamplingMixer construction without it; a dir: inloc gets no SAM auto-compute; and each job reads ONE staged mubeam file of about 16k events, so the random skip must stay below the smallest plausible file.` (no braces anywhere in that text: the template loader substitutes brace tokens).

In `core/pipeline.py`, in the comment block above `_render_fcl_overrides`, replace the two lines
```
#   'physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip' = 100720 --
```
…through…
```
#     in Python -- it depends on submit-time state.
```
with:
```
#   'physics.filters.TargetStopResampler.mu2e.MaxEventsToSkip' = 8000 --
#     REQUIRED (the prolog leaves it @nil); the rationale lives in the
#     template's _comment since Phase C1. _render_fcl_overrides still sets
#     the same 8000, a no-op until C3 deletes this module.
```

- [ ] **Step 8: Golden (d) declares the new quorum**

In `tests/golden_parity.py`, after `_drop_per_event_fallback`, add:

```python
def _quorum_on_elebeam_flash(base):
    """Intended Phase-C1 change (prodtools-kit spec, "Registry and data
    changes"): every prodtools step sets quorum, so elebeam_flash gains the
    0.8 the other stages use."""
    for rec in base.values():
        tuning = rec.get("stage_tuning", {})
        if "elebeam_flash" in tuning:
            tuning["elebeam_flash"]["quorum"] = 0.8


def _declared_changes(base):
    _drop_per_event_fallback(base)
    _quorum_on_elebeam_flash(base)
```

and in `SECTIONS["d"]` replace `_drop_per_event_fallback` with `_declared_changes`. Update the docstring's (d) paragraph: "check applies the declared changes (`_declared_changes`: the per-event fallback drop, and C1's elebeam_flash quorum) to the baseline, never to the file."

- [ ] **Step 9: Fix the tests that build `KitDecl` by hand**

In `tests/test_contract.py`, `TestRegistry.setUp`, add `required_fixed=frozenset(), pipeline=False` to the `KitDecl(...)` call. Search the tests for any other `KitDecl(` call and do the same: `grep -rn "KitDecl(" tests/`.

- [ ] **Step 10: Run the tests and the golden**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check d`
Expected: section d passes. (Sections a–c and e are unaffected; run `check a b e` too, and skip c, which runs real G4.)

- [ ] **Step 11: Commit**

```bash
git add core/kit_registry.py core/study.py core/modes.py core/pipeline.py \
  mode_specs/foilsflash.json mode_specs/foilspf.json mode_specs/foilspf2k.json \
  mode_specs/foilspfbp.json mode_specs/foilspfbpx.json mode_specs/foilspfbpz.json \
  mode_specs/foilspfbw.json tests/fixtures/studies/demo.json \
  tests/fixtures/modes/template.json stage_entries/mustops_ce.json \
  tests/golden_parity.py tests/test_study.py tests/test_study_engine.py \
  tests/test_contract.py
git commit -m "feat(registry): pipeline flag, three-way runner rule, required quorum, fatal_log_codes"
```

---

### Task 2: `kits.toml` servers and executors

**Files:**
- Modify: `core/kit_config.py`
- Modify: `kits.toml`
- Test: `tests/test_kit_config.py`

**Interfaces:**
- Produces: `kit_config.ServerConfig(name, command, env_passthrough, set_env, timeouts)` with `resolve_command()` and `resolve_env(base)` (same behavior as `KitConfig`'s); `kit_config.load_server_configs(path=KITS_TOML) -> Dict[str, ServerConfig]`; `KitConfig.executors: Tuple[str, ...]`; `kit_config.EXECUTORS = ("grid", "local")`. `KitClient(ServerConfig(...), campaign=..., trace_dir=...)` works unchanged (it uses only `name`, `resolve_command`, `resolve_env`, `timeouts["start"]`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_kit_config.py` (it imports `kit_config as kc`, and already has `sys`, `tempfile`, `ROOT` and `mock`):

```python
TOY_ENTRY = '''
[toy]
command = ["python3", "toy.py"]
env_passthrough = []
set = {}
study_keys = {}
fixed_keys = {}
accepts_lists = false
check = false
executors = ["grid", "local"]
launch_stagger_s = 0
poll_s = [0.1, 1.0]
timeouts = { start = 1, submit = 1, status = 1, results = 1, check = 1, describe = 1, cancel = 1 }
'''

SERVER = '''
[servers.alpha]
command = ["${REPO_ROOT}/x.sh"]
env_passthrough = []
set = { A = "b" }
timeouts = { start = 5, do_thing = 7 }
'''


class TestServersAndExecutors(unittest.TestCase):
    def write(self, text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "kits.toml"
        p.write_text(text)
        return p

    def test_a_kit_declares_its_executors(self):
        cfg = kc.load_kit_configs(self.write(TOY_ENTRY))["toy"]
        self.assertEqual(cfg.executors, ("grid", "local"))

    def test_executors_are_checked(self):
        for bad in ('[]', '["cloud"]', '["grid", "grid"]', '"grid"'):
            text = TOY_ENTRY.replace('executors = ["grid", "local"]',
                                     f"executors = {bad}")
            with self.subTest(bad=bad), self.assertRaises(
                    kc.KitConfigError) as cm:
                kc.load_kit_configs(self.write(text))
            self.assertIn("executors", str(cm.exception))

    def test_servers_are_not_kits(self):
        p = self.write(TOY_ENTRY + SERVER)
        self.assertEqual(sorted(kc.load_kit_configs(p)), ["toy"])
        srv = kc.load_server_configs(p)["alpha"]
        self.assertEqual((srv.timeouts["start"], srv.timeouts["do_thing"]),
                         (5.0, 7.0))
        self.assertEqual(srv.resolve_env({})["A"], "b")

    def test_a_server_needs_every_key_and_a_start_timeout(self):
        for old, new, needle in (
                ('set = { A = "b" }\n', "", "set"),
                ("start = 5, ", "", "start"),
                ('timeouts = { start = 5, do_thing = 7 }',
                 'timeouts = { start = 5, do_thing = 0 }', "do_thing"),
                ("[servers.alpha]", "[servers.Alpha]", "lower-case")):
            with self.subTest(needle=needle), self.assertRaises(
                    kc.KitConfigError) as cm:
                kc.load_server_configs(
                    self.write(SERVER.replace(old, new)))
            self.assertIn(needle, str(cm.exception))

    def test_the_repo_declares_both_prodtools_servers(self):
        servers = kc.load_server_configs()
        self.assertEqual(sorted(servers), ["prodtools_read", "prodtools_write"])
        self.assertIn("submit_once", servers["prodtools_write"].timeouts)
        self.assertIn("run_status", servers["prodtools_read"].timeouts)

    def test_a_kit_client_starts_from_a_server_config(self):
        import kits
        with tempfile.TemporaryDirectory() as td:
            srv = kc.ServerConfig(
                name="toysrv",
                command=(sys.executable, str(ROOT / "tests" / "toykit.py")),
                env_passthrough=(), set_env={"TOYKIT_STATE_DIR": td},
                timeouts={"start": 60.0, "describe": 30.0})
            client = kits.KitClient(srv, campaign="c", trace_dir=Path(td))
            try:
                client.start()
                self.assertIn("describe", client.tools)
            finally:
                client.close()
```


- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_kit_config -v`
Expected: FAIL — `executors` unknown key, no `load_server_configs`, `servers` parsed as a kit.

- [ ] **Step 3: Implement**

In `core/kit_config.py`:

1. Constants:

```python
KEYS = ("command", "env_passthrough", "set", "study_keys", "fixed_keys",
        "accepts_lists", "check", "executors", "launch_stagger_s", "poll_s",
        "timeouts")
SERVER_KEYS = ("command", "env_passthrough", "set", "timeouts")
EXECUTORS = ("grid", "local")
SERVERS_TABLE = "servers"      # [servers.<name>]: not a kit
```

2. Module-level launch helpers, and `KitConfig` delegating to them:

```python
def _resolve_command(name: str, command) -> list:
    return [resolve(v, name, f"command[{i}]") for i, v in enumerate(command)]


def _resolve_env(name: str, passthrough, set_env, base) -> Dict[str, str]:
    """`base` (the MCP SDK's short default allowlist) plus every
    env_passthrough variable, which must be set, plus `set`."""
    env = dict(base)
    for var in passthrough:
        value = os.environ.get(var)
        if not value:
            raise KitConfigError(
                f"kit {name!r}: env_passthrough names ${var}, which is not "
                f"set in this environment")
        env[var] = value
    for key, value in set_env.items():
        env[key] = resolve(value, name, f"set.{key}")
    return env
```

In `KitConfig`, add the field `executors: Tuple[str, ...]` right after `check`, and make its two methods one-liners calling `_resolve_command(self.name, self.command)` and `_resolve_env(self.name, self.env_passthrough, self.set_env, base)`.

3. `ServerConfig`:

```python
@dataclass(frozen=True)
class ServerConfig:
    """An MCP server an adapter talks to (kits.toml [servers.<name>]): how
    to start it, and a timeout per tool it is called with plus "start"."""
    name: str
    command: Tuple[str, ...]
    env_passthrough: Tuple[str, ...]
    set_env: Dict[str, str]
    timeouts: Dict[str, float]

    def resolve_command(self) -> list:
        return _resolve_command(self.name, self.command)

    def resolve_env(self, base: Dict[str, str]) -> Dict[str, str]:
        return _resolve_env(self.name, self.env_passthrough, self.set_env,
                            base)
```

4. Split the shared launch-field checks out of `_entry` into `_launch_fields(raw, where) -> (command, passthrough, set_env)` (the existing `command`, `env_passthrough` and `set` checks, moved verbatim), call it from `_entry`, and add the executors check to `_entry`:

```python
    executors = raw["executors"]
    _need(isinstance(executors, list) and executors
          and all(e in EXECUTORS for e in executors)
          and len(set(executors)) == len(executors),
          f"{where}.executors",
          f"must be a non-empty list of distinct values from "
          f"{list(EXECUTORS)}")
```

passing `executors=tuple(executors)` to `KitConfig`.

5. `_server` and the loaders:

```python
def _server(name: str, raw, where: str) -> ServerConfig:
    _need(_KIT_NAME.fullmatch(name), where,
          "a server name is a lower-case identifier")
    _need(isinstance(raw, dict), where, "must be a table")
    missing = [k for k in SERVER_KEYS if k not in raw]
    _need(not missing, where, f"missing required key(s) {missing}")
    unknown = sorted(set(raw) - set(SERVER_KEYS))
    _need(not unknown, where, f"unknown key(s) {unknown}; accepted keys are "
          f"{sorted(SERVER_KEYS)}")
    command, passthrough, set_env = _launch_fields(raw, where)
    timeouts = raw["timeouts"]
    _need(isinstance(timeouts, dict) and "start" in timeouts,
          f"{where}.timeouts", "must be a table with a 'start' timeout")
    for k, v in timeouts.items():
        _need(_is_number(v) and v > 0, f"{where}.timeouts.{k}",
              "must be a number of seconds > 0")
    return ServerConfig(name=name, command=tuple(command),
                        env_passthrough=tuple(passthrough),
                        set_env=dict(set_env),
                        timeouts={k: float(v) for k, v in timeouts.items()})


def _load_doc(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise KitConfigError(f"{path}: the kit registry is missing")
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise KitConfigError(f"{path}: invalid TOML: {exc}") from None


def load_kit_configs(path: Path = KITS_TOML) -> Dict[str, KitConfig]:
    doc = _load_doc(path)
    return {name: _entry(name, raw, f"{path}[{name}]")
            for name, raw in doc.items() if name != SERVERS_TABLE}


def load_server_configs(path: Path = KITS_TOML) -> Dict[str, ServerConfig]:
    servers = _load_doc(path).get(SERVERS_TABLE, {})
    if not isinstance(servers, dict):
        raise KitConfigError(f"{path}[{SERVERS_TABLE}]: must be a table")
    return {name: _server(name, raw, f"{path}[{SERVERS_TABLE}.{name}]")
            for name, raw in servers.items()}
```

Update the module docstring: add a paragraph "A `[servers.<name>]` table declares an MCP server an adapter talks to (Phase C1): `command`, `env_passthrough`, `set` and `timeouts`, all required."

- [ ] **Step 4: Update `kits.toml`**

In `[toykit]` add `executors = ["grid", "local"]` after `check = true` (toykit does not care where it runs). Append:

```toml

# Servers an adapter talks to (core/kit_config.py ServerConfig): not kits.
# The prodtools adapter (core/adapters/prodtools.py) starts both from the
# checkout $AUTORESEARCH_PRODTOOLS names. KRB5CCNAME is the only credential
# to pass: the bearer token lives at its default /run/user/<uid>/bt_u<uid>,
# and the write server refreshes it on every call. The spack cache goes to
# local disk, as the pipeline and preflight already do
# (wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md).
[servers.prodtools_write]
command = ["${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_write_mcp.sh"]
env_passthrough = ["KRB5CCNAME"]
set = { SPACK_USER_CACHE_PATH = "/tmp/spack_cache_${USER}" }
timeouts = { start = 120, submit_once = 900, run_local = 300, cancel_run = 120 }

[servers.prodtools_read]
command = ["${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_mcp.sh"]
env_passthrough = ["KRB5CCNAME"]
set = { SPACK_USER_CACHE_PATH = "/tmp/spack_cache_${USER}" }
timeouts = { start = 120, run_status = 120 }
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass. (Any test that builds a `KitConfig` by keyword must now pass `executors`; `grep -rn "KitConfig(" tests/` and add `executors=("grid", "local")`.)

- [ ] **Step 6: Commit**

```bash
git add core/kit_config.py kits.toml tests/test_kit_config.py
git commit -m "feat(kit_config): [servers.*] table and per-kit executors"
```

---

### Task 3: Retry backoff, `--executor`/`--parallel`, the ticket check

**Files:**
- Modify: `core/contract.py`
- Create: `core/adapters/__init__.py`
- Modify: `graph/study_graph.py` (`build_study_graph`: `executor`, `point.json`)
- Modify: `graph/study_run.py`, `graph/study_loop.py`
- Test: `tests/test_contract.py`, `tests/test_study_run.py`, `tests/test_study_loop.py`

**Interfaces:**
- Consumes: `kit_config.EXECUTORS`, `KitConfig.executors` (Task 2).
- Produces:
  - `contract.RETRY_PAUSES_S = (5.0, 20.0)`; `contract.call_with_retries(fn, *, retry_tool_errors, attempts=ATTEMPTS, pause=time.sleep)`;
  - `NativeKit(config, client, *, pause=time.sleep)`;
  - `contract.open_kit(name, campaign, *, executor="grid", parallel=None)`; adapter factories are called `factory(campaign, executor=..., parallel=...)`;
  - `KitSet(campaign, opener=None, *, executor="grid", parallel=None)`;
  - `check_kits(study, *, campaign, opener=None, executor="grid", parallel=None)`;
  - `contract.MAX_PARALLEL = 16`; `contract.executor_problems(study, executor, parallel) -> List[str]`; `contract.requires_kerberos(study, executor) -> bool`;
  - `core/adapters/__init__.py: register_all(register, adapters)` (empty until Task 7);
  - `study_run.launch_refusals(study, executor, parallel, *, kerberos=None) -> list`;
  - `build_study_graph(..., executor="grid")`; `point.json` gains `"executor"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_contract.py`:
- In `TestRetryPolicy.kit`, construct `ct.NativeKit(self.CFG, client, pause=lambda s: None)`.
- Add to `TestRetryPolicy`:

```python
    def test_pauses_grow_between_attempts(self):
        pauses = []
        client = FakeClient([KitError("k", "status", "lost")] * 3)
        kit = ct.NativeKit(self.CFG, client, pause=pauses.append)
        with self.assertRaises(KitError):
            kit.status("h", "w")
        self.assertEqual(pauses, [5.0, 20.0])
```

- In `TestRegistry.test_register_and_open`, give `Fake.__init__` the signature `(self, campaign, *, executor, parallel)`, store both, and assert `ct.open_kit("fakeadapter", "camp", executor="local", parallel=3)` carries `("camp", "local", 3)`. Also add `EXECUTORS = ("grid",)` to `Fake`.
- In `TestRegistry.test_a_kit_with_neither_is_refused`, open `"offline_preflight"` instead of `"prodtools"` (Task 7 gives prodtools an adapter).
- Add:

```python
class TestExecutors(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.study = st.load_study_file(write_study(toy_doc(), Path(td.name)))

    def test_toykit_runs_either_way(self):
        for executor in ("grid", "local"):
            self.assertEqual(ct.executor_problems(self.study, executor, None),
                             [])

    def test_parallel_only_with_local_and_bounded(self):
        self.assertTrue(ct.executor_problems(self.study, "grid", 2))
        self.assertTrue(ct.executor_problems(self.study, "local", 17))
        self.assertEqual(ct.executor_problems(self.study, "local", 16), [])

    def test_an_unknown_executor(self):
        self.assertIn("cloud", ct.executor_problems(self.study, "cloud",
                                                    None)[0])

    def test_a_kit_that_runs_only_on_the_grid(self):
        cfg = replace(kit_registry.NATIVE["toykit"], executors=("grid",))
        with mock.patch.dict(kit_registry.NATIVE, {"toykit": cfg}):
            (problem,) = ct.executor_problems(self.study, "local", None)
        self.assertIn("toykit", problem)

    def test_kerberos_only_for_a_grid_adapter_that_asks(self):
        self.assertFalse(ct.requires_kerberos(self.study, "grid"))
        doc = toy_doc()

        class Grid:
            EXECUTORS = ("grid", "local")
            REQUIRES_KERBEROS = True
            LAUNCH_STAGGER_S = 0

        with mock.patch.dict(ct.ADAPTERS, {"toykit": Grid}):
            self.assertTrue(ct.requires_kerberos(self.study, "grid"))
            self.assertFalse(ct.requires_kerberos(self.study, "local"))
```

In `tests/test_study_run.py`, add:

```python
class TestExecutorFlag(_Point):
    def run_with(self, study, *flags, config="p1"):
        return subprocess.run(self.cmd(study, config, (1.0, 2.0)) + list(flags),
                              cwd=ROOT, env=self.env, capture_output=True,
                              text=True, timeout=120)

    def test_local_is_recorded_and_a_switch_is_refused(self):
        s = self.add_study()
        r = self.run_with(s, "--executor", "local", "--parallel", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        point = json.loads((self.state() / "point.json").read_text())
        self.assertEqual(point["executor"], "local")
        r = self.run_with(s, "--executor", "grid")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--executor local", r.stdout)

    def test_parallel_with_grid_is_refused(self):
        r = self.run_with(self.add_study(), "--parallel", "2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--parallel", r.stdout)

    def test_a_point_json_without_an_executor_is_refused(self):
        s = self.add_study()
        study = st.load_study_file(self.studies / f"{s}.json")
        self.state().mkdir(parents=True)
        (self.state() / "point.json").write_text(json.dumps(
            {"study": s, "config": "p1", "campaign": "t", "x": [1.0, 2.0],
             "context": {}, "measure_basis_sha": study.measure_basis_sha}))
        r = self.run_point(s)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("executor", r.stdout)


class TestLaunchRefusals(unittest.TestCase):
    def test_the_ticket_is_checked_only_when_a_kit_asks(self):
        study = object()
        calls = []

        def kerberos():
            calls.append(1)
            return "ticket has under 4 h left"

        with mock.patch.object(study_run, "executor_problems",
                               return_value=[]), \
                mock.patch.object(study_run, "requires_kerberos",
                                  return_value=True):
            self.assertEqual(study_run.launch_refusals(
                study, "grid", None, kerberos=kerberos),
                ["ticket has under 4 h left"])
        with mock.patch.object(study_run, "executor_problems",
                               return_value=[]), \
                mock.patch.object(study_run, "requires_kerberos",
                                  return_value=False):
            self.assertEqual(study_run.launch_refusals(
                study, "grid", None, kerberos=kerberos), [])
        self.assertEqual(calls, [1])
```

In `tests/test_study_loop.py`, add (use the module's existing imports; add `from unittest import mock` if absent):

```python
class TestChildFlags(unittest.TestCase):
    def test_children_get_the_executor_and_parallel(self):
        seen = {}

        class P:
            def __init__(self, cmd, **kw):
                seen["cmd"] = cmd

            def wait(self):
                return 0

        study = types.SimpleNamespace(name="toy")
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(study_loop.subprocess, "Popen", P), \
                mock.patch.object(study_loop.paths, "GRAPH_DATA", Path(td)):
            study_loop.make_run_child(study, "camp", [], "local", 3)(
                "n1", [1.0, 2.0])
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--executor") + 1], "local")
        self.assertEqual(cmd[cmd.index("--parallel") + 1], "3")

    def test_grid_children_get_no_parallel(self):
        seen = {}

        class P:
            def __init__(self, cmd, **kw):
                seen["cmd"] = cmd

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(study_loop.subprocess, "Popen", P), \
                mock.patch.object(study_loop.paths, "GRAPH_DATA", Path(td)):
            study_loop.make_run_child(types.SimpleNamespace(name="toy"),
                                      "camp", [], "grid", None)("n1", [1.0])
        self.assertNotIn("--parallel", seen["cmd"])
```

(`study_loop` must be importable in that test module: it is, as `graph` is on `sys.path` there; add `import types` if absent.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract tests.test_study_run tests.test_study_loop -v`
Expected: FAIL (no `pause`, no `executor_problems`, no `--executor`).

- [ ] **Step 3: Implement the contract side**

In `core/contract.py`:

1. Imports: add `import functools`, `import time`; `from core.kit_config import EXECUTORS` / `from kit_config import EXECUTORS` in the two branches.

2. After `ATTEMPTS = 3`:

```python
RETRY_PAUSES_S = (5.0, 20.0)   # after the 1st and the 2nd failed attempt
MAX_PARALLEL = 16              # prodtools' MAX_LOCAL_PARALLEL


def call_with_retries(fn, *, retry_tool_errors, attempts=ATTEMPTS,
                      pause=time.sleep):
    """fn() up to `attempts` times. Transport failures and timeouts are
    retried; a tool error only when retry_tool_errors (a refused submit --
    same name, different params -- must never be repeated). Between
    attempts it pauses RETRY_PAUSES_S: a credential blip lasts seconds."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except KitToolError:
            if not retry_tool_errors or attempt == attempts:
                raise
        except KitError:
            if attempt == attempts:
                raise
        pause(RETRY_PAUSES_S[min(attempt - 1, len(RETRY_PAUSES_S) - 1)])
```

3. `NativeKit.__init__(self, config, client, *, pause=time.sleep)` stores `self._pause = pause`, and `_call` becomes:

```python
    def _call(self, tool, args, workflow, *, retry_tool_errors,
              attempts=ATTEMPTS):
        """Transport failures and timeouts are retried (the client respawns
        a lost server before the next call); see call_with_retries."""
        return call_with_retries(
            lambda: self.client.call(tool, args,
                                     timeout_s=self.config.timeouts[tool],
                                     workflow=workflow),
            retry_tool_errors=retry_tool_errors, attempts=attempts,
            pause=self._pause)
```

4. Replace the `ADAPTERS` comment and add the lazy registration, and the executor functions:

```python
# Kits implemented in Python (core/adapters/). A factory is a class called
# factory(campaign, executor=..., parallel=...), with LAUNCH_STAGGER_S and
# EXECUTORS attributes (REQUIRES_KERBEROS optional); its kit needs a
# kit_registry declaration with engine=True and no kits.toml entry.
ADAPTERS: Dict[str, Callable[..., Any]] = {}


def _load_adapters() -> None:
    """Register core/adapters' kits once per process (idempotent): lazily,
    because an adapter module imports this one."""
    if __package__:
        from core.adapters import register_all
    else:
        from adapters import register_all
    register_all(register_adapter, ADAPTERS)
```

`open_kit` becomes:

```python
def open_kit(name: str, campaign: str, *, executor: str = "grid",
             parallel=None):
    _load_adapters()
    if name in ADAPTERS:
        return ADAPTERS[name](campaign, executor=executor, parallel=parallel)
    cfg = kit_registry.NATIVE.get(name)
    if cfg is None:
        raise KeyError(f"kit {name!r} has no adapter and no kits.toml entry, "
                       f"so the contract engine cannot run it (the pipeline "
                       f"kits run through graph.run until Phase C)")
    return NativeKit(cfg, KitClient(cfg, campaign=campaign,
                                    trace_dir=paths.GRAPH_DATA / campaign))
```

In `launch_stagger`, call `_load_adapters()` first. Then add:

```python
def _executors_of(name: str) -> tuple:
    if name in ADAPTERS:
        return tuple(ADAPTERS[name].EXECUTORS)
    cfg = kit_registry.NATIVE.get(name)
    return cfg.executors if cfg is not None else ()


def executor_problems(study, executor: str, parallel) -> List[str]:
    """Why the study cannot run with this --executor / --parallel; an empty
    list means it can."""
    if executor not in EXECUTORS:
        return [f"--executor must be one of {list(EXECUTORS)}, got "
                f"{executor!r}"]
    _load_adapters()
    problems = []
    if parallel is not None:
        if executor != "local":
            problems.append("--parallel applies to --executor local only")
        elif not 1 <= parallel <= MAX_PARALLEL:
            problems.append(f"--parallel must be 1..{MAX_PARALLEL}, got "
                            f"{parallel}")
    for name in sorted(kit_registry.kits_of(study)):
        supported = _executors_of(name)
        if executor not in supported:
            problems.append(f"kit {name!r} cannot run with --executor "
                            f"{executor} (it supports {list(supported)})")
    return problems


def requires_kerberos(study, executor: str) -> bool:
    """True when a grid launch of this study needs a Kerberos ticket: some
    kit of it says so (the prodtools adapter does)."""
    if executor != "grid":
        return False
    _load_adapters()
    return any(getattr(ADAPTERS.get(n), "REQUIRES_KERBEROS", False)
               for n in kit_registry.kits_of(study))
```

5. `KitSet.__init__(self, campaign, opener=None, *, executor="grid", parallel=None)` sets `self._opener = opener or functools.partial(open_kit, executor=executor, parallel=parallel)`.

6. `check_kits(study, *, campaign, opener=None, executor="grid", parallel=None)`: first line `opener = opener or functools.partial(open_kit, executor=executor, parallel=parallel)`.

7. Create `core/adapters/__init__.py`:

```python
"""Python adapters for kits that do not speak the evaluator contract
themselves (Phase C1 spec, docs/superpowers/specs/2026-09-25-prodtools-kit-design.md).
register_all is idempotent; core/contract.py calls it before it looks a
kit up."""


def register_all(register, adapters) -> None:
    """Register every adapter this package holds that `adapters` lacks."""
```

- [ ] **Step 4: Implement the runner side**

In `graph/study_graph.py`: `build_study_graph(study, *, config, campaign, context, kits, state_dir, board, log=print, executor="grid")`. In `node_derive`, add `"executor": executor` to `point`, and in the resume branch, right after the `measure_basis_sha` checks and before `if old != point:`:

```python
            if "executor" not in old:
                raise PointMismatch(
                    f"{point_path} has no executor (written before "
                    f"point.json recorded one), so a resume cannot tell "
                    f"whether it would switch executors mid-point; use a "
                    f"new config name")
            if old["executor"] != executor:
                raise PointMismatch(
                    f"{point_path}: this point was started with --executor "
                    f"{old['executor']}; rerun it with --executor "
                    f"{old['executor']}, or use a new config name")
```

In `graph/study_run.py`:
- imports: `from contract import EXECUTORS, KitSet, executor_problems, requires_kerberos  # noqa: E402`.
- add:

```python
def _kerberos():
    import launch_checks
    return launch_checks.check_kerberos(launch_checks.GRID_TICKET_SECONDS)


def launch_refusals(study, executor, parallel, *, kerberos=None) -> list:
    """Why this launch must not start, before any kit does: the executor
    rules, then (a grid launch whose kit asks) a Kerberos ticket with 4 h
    left."""
    problems = executor_problems(study, executor, parallel)
    if not problems and requires_kerberos(study, executor):
        err = (kerberos or _kerberos)()
        if err:
            problems.append(err)
    return problems
```

- argparse: `ap.add_argument("--executor", choices=EXECUTORS, default="grid", help="where the jobs run; recorded in point.json, and a rerun must use the same one")` and `ap.add_argument("--parallel", type=int, default=None, help="jobs at once on this node, with --executor local only (1..16)")`.
- after the `check_x`/`parse_context` try block: 
```python
    problems = launch_refusals(study, args.executor, args.parallel)
    if problems:
        return refuse("; ".join(problems))
```
- `kits = KitSet(args.campaign, executor=args.executor, parallel=args.parallel)`, and pass `executor=args.executor` to `build_study_graph`.

In `graph/study_loop.py`:
- `from study_run import launch_refusals, parse_context  # noqa: E402`, and `from contract import EXECUTORS, check_kits, launch_stagger  # noqa: E402`.
- `make_run_child(study, campaign, context_args, executor, parallel)`: after the `--context` loop, `cmd += ["--executor", executor]` and `if parallel is not None: cmd += ["--parallel", str(parallel)]`.
- argparse: the same `--executor` and `--parallel` as `study_run` (help: "passed to every child").
- after `parse_context`: 
```python
    problems = launch_refusals(study, args.executor, args.parallel)
    problems += check_kits(study, campaign=args.name_prefix,
                           executor=args.executor, parallel=args.parallel)
```
  replacing the existing `problems = check_kits(...)` line; the refusal loop below stays.
- `run_child=make_run_child(study, args.name_prefix, args.context, args.executor, args.parallel)`; add `executor={args.executor}` to the startup print.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass. Any existing test that writes a `point.json` by hand for a resume must add `"executor": "grid"` (the `measure_basis_sha` refusal test must NOT: it still expects that refusal first).

- [ ] **Step 6: Commit**

```bash
git add core/contract.py core/adapters/__init__.py graph/study_graph.py \
  graph/study_run.py graph/study_loop.py tests/test_contract.py \
  tests/test_study_run.py tests/test_study_loop.py
git commit -m "feat(engine): retry backoff, --executor/--parallel, the grid ticket check"
```

---

### Task 4: The step's template in `params`; cancel the other steps when one fails

**Files:**
- Modify: `core/study.py` (`Study.entry_template`)
- Modify: `core/scheduler.py`
- Test: `tests/test_scheduler.py`, `tests/test_study.py`

**Interfaces:**
- Produces: `Study.entry_template(step: str) -> dict` (deep copy of the resolved template `measure_basis` holds); `scheduler.step_params(...)` adds `params["entry"]` for a kit whose `KitDecl.uses_entries` is true, and refuses a mapped or fixed param named `entry` for such a kit; `run_steps` cancels running steps whose kit's `tools` include `"cancel"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_study.py`:

```python
class TestEntryTemplate(_Tmp):
    def test_the_resolved_template_is_a_copy(self):
        s = st.load_study_file(FIXTURE)
        want = json.loads((Path(__file__).resolve().parent.parent
                           / "stage_entries" / "mubeam.json").read_text())
        got = s.entry_template("mubeam")
        self.assertEqual(got, want)
        got["njobs"] = -1
        self.assertEqual(s.entry_template("mubeam")["njobs"], want["njobs"])

    def test_an_unknown_step(self):
        with self.assertRaises(KeyError):
            st.load_study_file(FIXTURE).entry_template("nope")
```

In `tests/test_scheduler.py`, give `FakeKit` cancel support: in `__init__` add `cancellable=False` as a keyword, `self.tools = frozenset({"submit", "status", "results"} | ({"cancel"} if cancellable else set()))`, `self.cancelled = set()`; in `status`, before reading the script: `if handle in self.cancelled: return Status("cancelled", f"{s} cancelled", self.poll_ms, None)`; and add

```python
    def cancel(self, handle, workflow):
        with self._lock:
            self.cancelled.add(handle)
            self.events.append(("cancel", handle.split(".", 1)[1]))
        return "cancelled"
```

Then add:

```python
class TestCancelOnFailure(_Run):
    def test_a_failure_cancels_the_running_steps(self):
        kit = FakeKit({"a": ["working", "failed"],
                       "b": ["working"] * 10000}, cancellable=True)
        out = self.run_steps(study(step("a"), step("b")), kit)
        self.assertFalse(out["a"].ok)
        self.assertFalse(out["b"].ok)
        self.assertIn("cancelled", out["b"].message)
        self.assertIn(("cancel", "b"), kit.events)
        self.assertIn("step a", (self.state / "broken.txt").read_text())

    def test_a_kit_that_cannot_cancel_runs_to_completion(self):
        logs = []
        kit = FakeKit({"a": ["working", "failed"],
                       "b": ["working"] * 5 + ["completed"]})
        out = self.run_steps(study(step("a"), step("b")), kit,
                             log=logs.append)
        self.assertTrue(out["b"].ok)
        self.assertTrue(any("cannot cancel" in m for m in logs), logs)

    def test_a_step_not_submitted_yet_never_submits(self):
        kit = FakeKit()
        stop = threading.Event()
        stop.set()
        out = sch._run_one(study(step("a")), step("a"), "c", self.state, {},
                           {}, Kits(kit), {}, "camp/c/a",
                           lambda s: None, lambda m: None, stop)
        self.assertFalse(out.ok)
        self.assertIn("not submitted", out.message)
        self.assertEqual(kit.submits, [])


class TestEntryParam(unittest.TestCase):
    def test_an_entry_kit_gets_the_resolved_template(self):
        s = st_mod.load_study_file(DEMO)
        mubeam = next(x for x in s.steps if x.step == "mubeam")
        params = sch.step_params(s, mubeam, {}, False)
        self.assertEqual(params["entry"], s.entry_template("mubeam"))
        self.assertEqual(params["quorum"], 0.8)

    def test_entry_is_reserved_for_an_entry_kit(self):
        s = st_mod.load_study_file(DEMO)
        mubeam = next(x for x in s.steps if x.step == "mubeam")
        clash = dataclasses.replace(mubeam, fixed=dict(mubeam.fixed, entry=1))
        with self.assertRaises(ValueError) as cm:
            sch.step_params(s, clash, {}, False)
        self.assertIn("entry", str(cm.exception))
```

with, at the top of `tests/test_scheduler.py`: `import dataclasses`, `import study as st_mod  # noqa: E402`, and `DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_scheduler tests.test_study -v`
Expected: FAIL (no `entry_template`, no cancel, `_run_one` has no `stop`).

- [ ] **Step 3: Implement `Study.entry_template`**

In `core/study.py`, add `import copy` and, in `Study`:

```python
    def entry_template(self, step: str) -> Dict[str, Any]:
        """The step's stage template as the study resolved it at load (the
        one measure_sha hashed), deep-copied so a kit cannot alter it."""
        for s in self.measure_basis["steps"]:
            if s["step"] == step:
                return copy.deepcopy(s["entry"])
        raise KeyError(f"study {self.name!r} has no step {step!r}")
```

- [ ] **Step 4: Implement the scheduler**

In `core/scheduler.py`:
1. Imports: `import threading`; `from core import kit_registry` / `import kit_registry` in the two branches.
2. Docstring: replace "A failed or cancelled step, a kit error, or a reply outside the contract stops new launches; running steps finish;" with "A failed or cancelled step, a kit error, or a reply outside the contract stops new launches and cancels the running steps whose kit offers `cancel` (the others finish);".
3. `step_params`:

```python
def step_params(study, step, env, accepts_lists) -> Dict[str, Any]:
    """The mapped params, then the study's settings for the step's kit, then
    the step's fixed values, which win over the settings. A mapped param may
    not share a name with a setting or a fixed value. A kit that takes stage
    templates also gets the step's resolved template as `entry`."""
    params = merge_params(f"step {step.step!r}",
                          map_params(step.params, env, accepts_lists),
                          {**study.kits.get(step.kit, {}), **step.fixed})
    decl = kit_registry.KITS.get(step.kit)
    if decl is not None and decl.uses_entries:
        if "entry" in params:
            raise ValueError(f"step {step.step!r}: 'entry' is reserved for "
                             f"kit {step.kit!r}, which receives the step's "
                             f"stage template under that name")
        params["entry"] = study.entry_template(step.step)
    return params
```

4. `run_steps`: create `stop = threading.Event()` before the pool; pass `stop` as the last argument of `pool.submit(_run_one, ...)`; and where the first failure is recorded (`if not out.ok and failed is None:`), after writing `broken.txt`, add:

```python
                    stop.set()
                    _cancel_running(study, set(running.values()), state_dir,
                                    kits, workflow, log)
```

5. New helpers:

```python
def _cancel_one(kit, step, handle, workflow, log) -> None:
    if "cancel" not in getattr(kit, "tools", ()):
        log(f"[steps] {step.step}: kit {step.kit} cannot cancel; it runs to "
            f"completion")
        return
    try:
        state = kit.cancel(handle, workflow)
        log(f"[steps] {step.step}: cancel requested ({state})")
    except (KitError, ContractError) as exc:
        log(f"[steps] {step.step}: cancel failed ({exc}); it runs to "
            f"completion")


def _cancel_running(study, names, state_dir, kits, workflow, log) -> None:
    """Cancel each running step that has submitted. One that has not yet
    will see the stop event and never submit."""
    by_name = {s.step: s for s in study.steps}
    for name in sorted(names):
        handle_path = state_dir / f"{name}_cluster.txt"
        if not handle_path.exists():
            continue
        s = by_name[name]
        _cancel_one(kits.get(s.kit), s, handle_path.read_text().strip(),
                    workflow(name), log)
```

6. `_run_one(study, step, config, state_dir, env, files, kits, upstream, workflow, sleep, log, stop)`: in the `else:` (submit) branch, first

```python
            if stop.is_set():
                return StepOutcome(step.step, False, "cancelled: not "
                                   "submitted, another step failed first",
                                   None)
```

and after `log(f"[steps] {step.step}: submitted {handle}")`:

```python
            if stop.is_set():   # a step failed while this one submitted
                _cancel_one(kit, step, handle, workflow, log)
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/study.py core/scheduler.py tests/test_scheduler.py tests/test_study.py
git commit -m "feat(scheduler): stage template as params.entry; cancel running steps on a failure"
```

---

### Task 5: Zero-knob studies

**Files:**
- Modify: `core/study.py` (`_knobs`), `core/modes.py` (`runs_on_engine`)
- Modify: `graph/study_run.py` (`--x` optional), `graph/study_loop.py` (refusal)
- Modify: `core/botorch_predict.py` (`build_problem`), `surrogate/adapter.py` (`problems`)
- Modify: `kits.toml` (toykit fixed `x1`, `x2`)
- Test: `tests/test_zero_knob.py` (new)

**Interfaces:**
- Consumes: the three-way rule (Task 1), `--executor` (Task 3).
- Produces: `knobs: []` loads; `graph.study_run` takes no `--x` for such a study.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_zero_knob.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402

DEMO = ROOT / "tests" / "fixtures" / "studies" / "demo.json"


def zero_doc(name="zk"):
    doc = toy_doc(name=name, layout="v2")
    doc["knobs"] = []
    doc["evaluate"][0]["params"] = {}
    doc["evaluate"][0]["fixed"].update(x1=1.0, x2=2.0)
    return doc


class _Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.studies = self.tmp / "studies"
        self.data = self.tmp / "data"
        self.env = engine_env(self.data, self.studies)

    def run_module(self, *args):
        return subprocess.run([sys.executable, "-m", *args], cwd=ROOT,
                              env=self.env, capture_output=True, text=True,
                              timeout=120)


class TestLoader(_Tmp):
    def test_no_knobs_loads(self):
        s = st.load_study_file(write_study(zero_doc(), self.studies))
        self.assertEqual(s.knobs, ())
        self.assertTrue(modes.runs_on_engine(s))

    def test_a_pipeline_study_with_no_knobs_is_refused(self):
        doc = json.loads(DEMO.read_text())
        doc["derive"]["consts"].update({k["name"]: k["min"]
                                        for k in doc["knobs"]})
        doc["knobs"] = []
        s = st.load_study_file(write_study(doc, self.studies))
        with self.assertRaises(ValueError) as cm:
            modes.runs_on_engine(s)
        self.assertIn("no knobs", str(cm.exception))


class TestRunners(_Tmp):
    def test_a_zero_knob_point_lands_a_row_without_knob_columns(self):
        write_study(zero_doc(), self.studies)
        r = self.run_module("graph.study_run", "--study", "zk", "--config",
                            "z1", "--campaign", "t")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        board = self.data / "autoresearch_leaderboards" / "leaderboard_zk.tsv"
        header, row = board.read_text().splitlines()
        self.assertEqual(header.split("\t")[:3], ["config", "branin", "currin"])
        self.assertTrue(row.startswith("z1\t"))

    def test_x_is_refused_without_knobs_and_required_with_them(self):
        write_study(zero_doc(), self.studies)
        write_study(toy_doc(name="kn", layout="v2"), self.studies)
        r = self.run_module("graph.study_run", "--study", "zk", "--config",
                            "z1", "--campaign", "t", "--x=1,2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no knobs", r.stdout)
        r = self.run_module("graph.study_run", "--study", "kn", "--config",
                            "k1", "--campaign", "t")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--x", r.stdout)

    def test_the_loop_refuses_a_zero_knob_study(self):
        write_study(zero_doc(), self.studies)
        r = self.run_module("graph.study_loop", "--study", "zk", "--q", "1",
                            "--max-evals", "1", "--name-prefix", "zk")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no knobs", r.stdout)


class TestSurrogate(_Tmp):
    def test_build_problem_refuses_and_problems_skip(self):
        s = st.load_study_file(write_study(zero_doc(), self.studies))
        import botorch_predict as bp
        with mock.patch.dict(bp._modes.STUDIES, {"zk": s}):
            with self.assertRaises(ValueError) as cm:
                bp.build_problem("zk")
            self.assertIn("no knobs", str(cm.exception))
            from surrogate import adapter
            self.assertNotIn("zk", adapter.AutoresearchAdapter().problems())


if __name__ == "__main__":
    unittest.main()
```

(If `surrogate.adapter` refers to a differently-qualified `modes` module than `bp._modes`, patch `adapter._modes.STUDIES` as well in the same `with`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_zero_knob -v`
Expected: FAIL ("at least one knob is required"; toykit rejects fixed `x1`).

- [ ] **Step 3: Implement**

1. `core/study.py`, `_knobs`: delete the `if not raw: raise ... "at least one knob is required"` lines. Leave everything else.
2. `core/modes.py`, `runs_on_engine`: between the engine branch and the pipeline branch, add

```python
    if not study.knobs:
        raise ValueError(
            f"{study.path}: a study with no knobs runs only on the engine, "
            f"and kit(s) {sorted(k for k, d in decls.items() if not d.engine)} "
            f"have no engine implementation yet")
```

3. `graph/study_run.py`: `ap.add_argument("--x", default=None, help="comma-separated knob values, in the study's knob order; omit it for a study with no knobs")`, and replace `x = [float(v) for v in args.x.split(",")]` with

```python
        if not study.knobs:
            if args.x is not None:
                return refuse(f"study {study.name!r} has no knobs; drop --x")
            x = []
        elif args.x is None:
            return refuse(f"study {study.name!r} has knobs "
                          f"{list(study.knob_names)}; pass --x=<values>")
        else:
            x = [float(v) for v in args.x.split(",")]
```

Update the module docstring's usage lines: add "A study with no knobs runs once, with no --x: python -m graph.study_run --study prodtools_smoke --config smoke01 --campaign smoke --executor local".
4. `graph/study_loop.py`, after the ENGINE refusal:

```python
    if not study.knobs:
        print(f"[study_loop] REFUSED: study {args.study!r} has no knobs: "
              f"there is nothing to pick; run graph.study_run", flush=True)
        return 2
```

(move the `study = _modes.STUDIES[args.study]` line above it if needed).
5. `core/botorch_predict.py`, `build_problem`, after `study = _modes.STUDIES[mode]`:

```python
    if not study.knobs:
        raise ValueError(f"study {mode!r} has no knobs: there is nothing to "
                         f"fit or pick")
```

6. `surrogate/adapter.py`, `problems`: `return {name: bp.build_problem(name) for name, s in _modes.STUDIES.items() if s.knobs}`.
7. `kits.toml`, `[toykit]`: `fixed_keys = { delay_s = "number", fail = "string", submit_sleep_s = "number", x1 = "number", x2 = "number" }`.

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/study.py core/modes.py graph/study_run.py graph/study_loop.py \
  core/botorch_predict.py surrogate/adapter.py kits.toml tests/test_zero_knob.py
git commit -m "feat(study): zero-knob studies run once through graph.study_run"
```

---

### Task 6: prodtools entry helpers, `dsconf_fmt`, the parity test

**Files:**
- Create: `core/adapters/prodtools_entry.py`
- Modify: `core/prodtools_exec.py` (use the moved `render_entry` / `substitute_placeholders`)
- Modify: `core/pipeline.py` (`_stage_extra_files`, `input_farm` delegate)
- Modify: `stage_entries/{mubeam,mustops_ce,elebeam_flash}.json` (`dsconf_fmt`)
- Create: `tests/fixtures/prodtools_parity/{mubeam,mustops_ce,elebeam_flash}_entry.json`
- Test: `tests/test_prodtools_entry.py` (new)

**Interfaces:**
- Produces (all in `core/adapters/prodtools_entry.py`):
  - `USER: str`; `TEMPLATES_ROOT: Path` (`core/pipeline_templates`); `SETUP_POST: str`
  - `substitute_placeholders(value, mapping: dict, where: str)` — any `{token}` not in `mapping` is a `ValueError` naming it
  - `render_entry(*, dsconf, desc, njobs, code_tarball, fcl_name, events=None, run=None, memory_mb=None, input_data=None, inloc=None, resampler_name=None, fcl_overrides=None, outloc=None, sequential_aux=None) -> dict` (moved verbatim from `prodtools_exec`)
  - `entry_for_step(template, *, config, fixed, code_tarball, geom_name=None, staged=None) -> (entry: dict, facts: dict)`; `facts` has `desc`, `dsconf`, `njobs`, `events_per_job`, `output_glob`
  - `include_files(template, templates_root) -> list[Path]`
  - `build_code_tarball(base, *, geom_path, geom_name, extra_files, out_dir) -> Path`
  - `link_inputs(sources, dest, *, allow_copy) -> dict` (`{basename: 1}`)
  - `write_entry_file(path, entry) -> Path`

- [ ] **Step 1: Create the parity fixtures**

Run once (it reads the operator's archived gridphaseA01 run; the output has no personal paths):

```python
import json, pathlib
src = pathlib.Path("/exp/mu2e/data/users/oksuzian/gridtest/autoresearch_grid/gridphaseA01/state")
dst = pathlib.Path("tests/fixtures/prodtools_parity")
dst.mkdir(parents=True, exist_ok=True)
for step in ("mubeam", "mustops_ce", "elebeam_flash"):
    (entry,) = json.loads((src / f"{step}_entry.json").read_text())
    entry["code"] = "CODE"
    if entry["inloc"].startswith("dir:"):
        entry["inloc"] = "dir:STAGED"
    (dst / f"{step}_entry.json").write_text(json.dumps([entry], indent=1) + "\n")
```

Check: `grep -rn "/exp/mu2e" tests/fixtures/prodtools_parity/` prints nothing.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_prodtools_entry.py`:

```python
import errno
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
from adapters import prodtools_entry as pe  # noqa: E402

PARITY = ROOT / "tests" / "fixtures" / "prodtools_parity"
# foilspfbpz's fixed values, which gridphaseA01 ran with.
FIXED = {"mubeam": {"njobs": 15, "events_per_job": 200000, "memory_mb": 2000},
         "mustops_ce": {"njobs": 15, "events_per_job": 75000,
                        "memory_mb": 2000},
         "elebeam_flash": {"njobs": 100, "events_per_job": 110000,
                           "memory_mb": 2000}}


def template(step):
    return json.loads((ROOT / "stage_entries" / f"{step}.json").read_text())


class TestParity(unittest.TestCase):
    def test_entries_match_gridphaseA01(self):
        for step in FIXED:
            (want,) = json.loads((PARITY / f"{step}_entry.json").read_text())
            staged = (("STAGED", dict(want["input_data"]))
                      if want["inloc"] == "dir:STAGED" else None)
            with mock.patch.object(pe, "USER", want["owner"]):
                got, facts = pe.entry_for_step(
                    template(step), config="gridphaseA01", fixed=FIXED[step],
                    code_tarball="CODE",
                    geom_name="autoresearch_gridphaseA01_geom.txt",
                    staged=staged)
            # The mustops_ce template gained sequential_aux after
            # gridphaseA01 ran (a5e991d); nothing else may differ.
            got.pop("sequential_aux", None)
            with self.subTest(step=step):
                self.assertEqual(got, want)
                self.assertEqual((facts["desc"], facts["dsconf"]),
                                 (want["desc"], want["dsconf"]))


class TestEntryForStep(unittest.TestCase):
    def test_geom_without_a_geom_file_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(template("mubeam"), config="c1", fixed={},
                              code_tarball="CODE")
        self.assertIn("{geom}", str(cm.exception))

    def test_a_template_without_dsconf_fmt_is_refused(self):
        t = template("mubeam")
        del t["dsconf_fmt"]
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(t, config="c1", fixed={}, code_tarball="CODE",
                              geom_name="g.txt")
        self.assertIn("dsconf_fmt", str(cm.exception))

    def test_template_defaults_fill_what_fixed_omits(self):
        entry, facts = pe.entry_for_step(template("elebeam_flash"),
                                         config="c1", fixed={},
                                         code_tarball="CODE",
                                         geom_name="g.txt")
        self.assertEqual((entry["njobs"], entry["events"], entry["memory"]),
                         (100, 2500, "3000MB"))
        self.assertEqual(facts["events_per_job"], 2500)


class _Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)


class TestIncludeFiles(_Tmp):
    def test_bare_names_ship_and_published_paths_do_not(self):
        got = pe.include_files(template("mubeam"), pe.TEMPLATES_ROOT)
        self.assertEqual(sorted(p.name for p in got),
                         ["mubeam_targetstop_path.fcl",
                          "sim_kept_products_extras.fcl"])
        self.assertEqual(pe.include_files(template("elebeam_flash"),
                                          pe.TEMPLATES_ROOT), [])

    def test_a_missing_include_is_refused(self):
        t = {"fcl_overrides": {"#include": ["nope.fcl"]}}
        with self.assertRaises(ValueError) as cm:
            pe.include_files(t, self.tmp)
        self.assertIn("nope.fcl", str(cm.exception))


class TestCodeTarball(_Tmp):
    def base(self, with_code=True):
        src = self.tmp / "src" / ("Code" if with_code else "Other")
        src.mkdir(parents=True)
        (src / "setup.sh").write_text("echo hi\n")
        out = self.tmp / "base.tar.bz2"
        with tarfile.open(out, "w:bz2") as tf:
            tf.add(src, arcname=src.name)
        return out

    def build(self, base, geom_text="g1"):
        geom = self.tmp / "geom.txt"
        geom.write_text(geom_text)
        extra = self.tmp / "extra.fcl"
        extra.write_text("x: 1\n")
        return pe.build_code_tarball(base, geom_path=geom,
                                     geom_name="autoresearch_c1_geom.txt",
                                     extra_files=[extra],
                                     out_dir=self.tmp / "out")

    def test_contents(self):
        path = self.build(self.base())
        with tarfile.open(path) as tf:
            names = set(tf.getnames())
            post = tf.extractfile("Code/setup_post.sh").read().decode()
        self.assertTrue({"Code/setup.sh", "Code/autoresearch_c1_geom.txt",
                         "Code/extra.fcl", "Code/setup_post.sh"} <= names)
        self.assertEqual(post, pe.SETUP_POST)

    def test_same_inputs_reuse_and_a_new_geom_does_not(self):
        base = self.base()
        a = self.build(base)
        mtime = a.stat().st_mtime_ns
        self.assertEqual(self.build(base), a)
        self.assertEqual(a.stat().st_mtime_ns, mtime)
        self.assertNotEqual(self.build(base, geom_text="g2"), a)

    def test_two_builders_at_once_get_one_valid_tarball(self):
        base = self.base()
        geom = self.tmp / "geom.txt"
        geom.write_text("g")
        got, errors = [], []

        def build():
            try:
                got.append(pe.build_code_tarball(
                    base, geom_path=geom, geom_name="g.txt", extra_files=[],
                    out_dir=self.tmp / "out"))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=build) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(got)), 1)
        with tarfile.open(got[0]) as tf:
            self.assertIn("Code/g.txt", tf.getnames())
        self.assertEqual(sorted(p.name for p in (self.tmp / "out").iterdir()),
                         [got[0].name])

    def test_a_base_without_code_or_missing_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.build(self.base(with_code=False))
        self.assertIn("Code/", str(cm.exception))
        with self.assertRaises(ValueError):
            self.build(self.tmp / "missing.tar.bz2")


class TestLinkInputs(_Tmp):
    def sources(self, n=2):
        d = self.tmp / "up"
        d.mkdir(exist_ok=True)
        out = []
        for i in range(n):
            p = d / f"f{i}.art"
            p.write_text(str(i))
            out.append(p)
        return out

    def test_hard_links_and_a_fresh_directory(self):
        dest = self.tmp / "staged"
        dest.mkdir()
        (dest / "stale.art").write_text("old")
        src = self.sources()
        got = pe.link_inputs(src, dest, allow_copy=False)
        self.assertEqual(got, {"f0.art": 1, "f1.art": 1})
        self.assertEqual(sorted(p.name for p in dest.iterdir()),
                         ["f0.art", "f1.art"])
        self.assertEqual(os.stat(dest / "f0.art").st_ino, os.stat(src[0]).st_ino)

    def test_duplicate_basenames_are_refused(self):
        src = self.sources(1)
        other = self.tmp / "other"
        other.mkdir()
        (other / "f0.art").write_text("x")
        with self.assertRaises(ValueError):
            pe.link_inputs([src[0], other / "f0.art"], self.tmp / "s",
                           allow_copy=False)

    def test_a_cross_device_link_copies_only_when_allowed(self):
        src = self.sources(1)
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev):
            with self.assertRaises(OSError):
                pe.link_inputs(src, self.tmp / "grid", allow_copy=False)
            pe.link_inputs(src, self.tmp / "local", allow_copy=True)
        self.assertEqual((self.tmp / "local" / "f0.art").read_text(), "0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_entry -v`
Expected: FAIL (`No module named 'adapters.prodtools_entry'`).

- [ ] **Step 4: Add `dsconf_fmt` to the three templates**

In each of `stage_entries/mubeam.json`, `stage_entries/mustops_ce.json`, `stage_entries/elebeam_flash.json`, insert a line `"dsconf_fmt": "Run1Bak_{cfg}",` directly after the `"desc_fmt": ...` line, with the file's one-space indent.

- [ ] **Step 5: Create `core/adapters/prodtools_entry.py`**

```python
"""prodtools entries, code tarballs and input staging, as plain functions
(Phase C1 spec, "The adapter"): the prodtools adapter
(core/adapters/prodtools.py) and, until Phase C3 deletes it, the old
pipeline (core/prodtools_exec.py, core/pipeline.py) both call these, so
the two runners render and stage the same way.
"""
from __future__ import annotations

import errno
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

USER = os.environ.get("USER") or getpass.getuser()
TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "pipeline_templates"
# Prepends the unpacked tarball to both search paths, so the geometry file
# and the bare-name #include files it ships are found before the release's.
SETUP_POST = ('export MU2E_SEARCH_PATH="$CODE_DIR:$MU2E_SEARCH_PATH"\n'
              'export FHICL_FILE_PATH="$CODE_DIR:$FHICL_FILE_PATH"\n')
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_DEFAULT_OUTLOC = {"*.art": "outstage", "*.root": "outstage"}
_TEMPLATE_KEYS = ("desc_fmt", "dsconf_fmt", "fcl", "output_glob")


def substitute_placeholders(value, mapping: dict, where: str):
    """Recursively substitute {name} tokens in string values (nested dicts
    and lists). Any token not in `mapping` is a loud ValueError naming the
    key path: a typo must fail here, not render literally into a submitted
    FHiCL override. Always builds NEW containers, so repeated calls over one
    cached template never alias."""
    if isinstance(value, str):
        def repl(m):
            token = m.group(1)
            if token not in mapping:
                raise ValueError(
                    f"stage template: unknown placeholder {{{token}}} at "
                    f"{where!r} -- only {sorted(mapping)} are substituted "
                    f"here")
            return str(mapping[token])
        return _PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, list):
        return [substitute_placeholders(v, mapping, f"{where}[{i}]")
                for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: substitute_placeholders(v, mapping, f"{where}.{k}")
                for k, v in value.items()}
    return value


# render_entry: moved here verbatim from core/prodtools_exec.py (its
# docstring and body unchanged, including the USER owner and
# _DEFAULT_OUTLOC).


def entry_for_step(template, *, config, fixed, code_tarball, geom_name=None,
                   staged=None):
    """(entry, facts) for one prodtools step.

    `template` is the step's stage template as the study resolved it;
    {cfg} becomes `config`, and {geom} `geom_name` (a template that names
    {geom} for a step with no geometry file is refused). `fixed` holds the
    study's njobs / events_per_job / memory_mb when it sets them; the
    template's njobs / events / memory are the defaults. `staged` is
    (directory, {basename: 1}) when the step reads upstream outputs.
    `facts` are what the adapter records: desc, dsconf, njobs,
    events_per_job and output_glob.
    """
    mapping = {"cfg": config}
    if geom_name is not None:
        mapping["geom"] = geom_name
    t = substitute_placeholders(template, mapping, "entry")
    missing = [k for k in _TEMPLATE_KEYS if k not in t]
    if missing:
        raise ValueError(f"stage template: missing key(s) {missing}")
    njobs = fixed.get("njobs", t.get("njobs"))
    if njobs is None:
        raise ValueError("stage template: no njobs in the step's fixed or "
                         "the template")
    events = fixed.get("events_per_job", t.get("events"))
    entry = render_entry(
        dsconf=t["dsconf_fmt"], desc=t["desc_fmt"], njobs=njobs,
        code_tarball=code_tarball, fcl_name=t["fcl"], events=events,
        run=t.get("run"), memory_mb=fixed.get("memory_mb", t.get("memory")),
        input_data=staged[1] if staged else t.get("input_data"),
        inloc=f"dir:{staged[0]}" if staged else t.get("inloc"),
        resampler_name=t.get("resampler_name"),
        fcl_overrides=t.get("fcl_overrides"), outloc=t.get("outloc"),
        sequential_aux=t.get("sequential_aux"))
    facts = {"desc": t["desc_fmt"], "dsconf": t["dsconf_fmt"],
             "njobs": njobs, "events_per_job": events,
             "output_glob": t["output_glob"]}
    return entry, facts


def include_files(template, templates_root) -> list:
    """The FHiCL files a code tarball must ship: every bare-name (no '/')
    '#include' of the template's fcl_overrides, from `templates_root`. A
    published Production/... path resolves from the release and ships
    nothing."""
    inc = template.get("fcl_overrides", {}).get("#include", [])
    if isinstance(inc, str):
        inc = [inc]
    out = []
    for name in inc:
        if "/" in name:
            continue
        path = Path(templates_root) / name
        if not path.is_file():
            raise ValueError(f"stage template: #include {name!r} is not in "
                             f"{templates_root}")
        out.append(path)
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tar(args, what):
    r = subprocess.run(["tar", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"{what} failed (rc={r.returncode}): "
                         f"{r.stderr.strip()}")


def build_code_tarball(base, *, geom_path, geom_name, extra_files,
                       out_dir) -> Path:
    """Code.<digest>.tar.bz2 in `out_dir`: the base tarball's Code/, plus the
    geometry file (as `geom_name`), the extra files and setup_post.sh. The
    digest covers every input's bytes, so identical inputs reuse one file
    and a changed geometry never does. Built in a private directory and
    moved into place atomically: concurrent builders are safe."""
    base = Path(base)
    if not base.is_file():
        raise ValueError(f"code_tarball {base} does not exist")
    parts = sorted([(Path(p).name, Path(p)) for p in extra_files]
                   + ([(geom_name, Path(geom_path))] if geom_path else []))
    h = hashlib.sha256(_sha256_file(base).encode())
    for name, path in parts:
        h.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    h.update(SETUP_POST.encode())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"Code.{h.hexdigest()[:16]}.tar.bz2"
    if final.exists():
        return final
    work = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=out_dir))
    try:
        _tar(["xjf", str(base), "-C", str(work)], f"unpacking {base}")
        code = work / "Code"
        if not code.is_dir():
            raise ValueError(f"code_tarball {base} has no top-level Code/ "
                             f"directory")
        for name, path in parts:
            shutil.copy(path, code / name)
        (code / "setup_post.sh").write_text(SETUP_POST)
        packed = work / "packed.tar.bz2"
        _tar(["cjf", str(packed), "-C", str(work), "Code"],
             f"packing {final.name}")
        os.replace(packed, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return final


def link_inputs(sources, dest, *, allow_copy) -> dict:
    """Hard-link every source into `dest` (emptied first); return
    {basename: 1}, json2jobdef's input_data. Hard, not symbolic, links:
    xrootd will not follow /pnfs symlinks. allow_copy: a cross-device link
    falls back to a copy (a local run only; on /pnfs a copy would eat the
    quota, wiki/incidents/data-quota-exhausted-grid-accumulation.md)."""
    dest = Path(dest)
    if dest.exists():
        for p in dest.iterdir():
            p.unlink()
    else:
        dest.mkdir(parents=True)
    names = {}
    for src in map(Path, sources):
        if src.name in names:
            raise ValueError(f"two inputs share the basename {src.name!r}; "
                             f"input_data is keyed by basename")
        try:
            os.link(src, dest / src.name)
        except OSError as exc:
            if exc.errno != errno.EXDEV or not allow_copy:
                raise
            shutil.copy2(src, dest / src.name)
        names[src.name] = 1
    return names


def write_entry_file(path, entry) -> Path:
    """The one-element list json2jobdef reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([entry], indent=1) + "\n")
    return path
```

Move `render_entry` (with its docstring) and `_DEFAULT_OUTLOC` out of `core/prodtools_exec.py` into the marked place in this file, verbatim.

- [ ] **Step 6: Point the old pipeline at the helpers**

In `core/prodtools_exec.py`: delete `_STAGE_ENTRY_PLACEHOLDERS`, `_PLACEHOLDER_RE`, `_substitute_placeholders`, `_DEFAULT_OUTLOC` and `render_entry`; add `from adapters.prodtools_entry import render_entry, substitute_placeholders  # noqa: F401 -- render_entry: pipeline.py calls px.render_entry`; in `load_stage_entry`, return `substitute_placeholders(raw, {"cfg": cfg, "geom": geom}, stage)`; in `write_entry`, `return write_entry_file(state_dir / f"{stage}_entry.json", entry)` (import it too). Keep `import re` only if something else still uses it.

In `core/pipeline.py`: add `from adapters import prodtools_entry as pe` next to the `import prodtools_exec as px` line; `_stage_extra_files` becomes `return pe.include_files(entry_tmpl, TEMPLATES_ROOT)` (keep its docstring); `input_farm` keeps its signature and print and becomes:

```python
    input_map = pe.link_inputs(sources, dest, allow_copy=allow_copy)
    print(f"[{stage}] farmed {len(input_map)} file(s) into {dest}")
    return dest, input_map
```

- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass, including `tests/test_prodtools_exec.py` (it tests `pex.render_entry`, now re-exported). If a test asserts the old placeholder message text, update the expected text to the new one (`only ['cfg', 'geom'] are substituted here`).

- [ ] **Step 8: Commit**

```bash
git add core/adapters/prodtools_entry.py core/prodtools_exec.py core/pipeline.py \
  stage_entries/mubeam.json stage_entries/mustops_ce.json stage_entries/elebeam_flash.json \
  tests/fixtures/prodtools_parity tests/test_prodtools_entry.py
git commit -m "feat(adapters): prodtools entry, code tarball and staging helpers; parity with gridphaseA01"
```

---

### Task 7: The adapter, `ProdtoolsKit`

**Files:**
- Create: `core/adapters/prodtools.py`
- Modify: `core/adapters/__init__.py` (register), `core/kit_registry.py` (`prodtools` `engine=True`)
- Test: `tests/test_prodtools_adapter.py` (new), `tests/test_contract.py`

**Interfaces:**
- Consumes: Task 2's `load_server_configs`; Task 3's `call_with_retries`, adapter factory signature; Task 4's `params["entry"]`; Task 6's helpers; `contract.parse_status`, `parse_results`, `parse_cancel`, `Describe`.
- Produces: `ProdtoolsKit(campaign, *, executor="grid", parallel=None, clients=None, clock=time.time, pause=time.sleep, grid_root=None, pnfs_root=None, templates_root=None, submit_lock=None)` implementing the Kit interface; class attributes `EXECUTORS = ("grid", "local")`, `REQUIRES_KERBEROS = True`, `LAUNCH_STAGGER_S = 90.0`; `prodtools.VERSION = "prodtools-adapter/1"`; `prodtools.split_handle(name) -> (config, step)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prodtools_adapter.py`:

```python
import copy
import errno
import json
import os
import sys
import tarfile
import tempfile
import types
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import scheduler  # noqa: E402
from adapters import prodtools as pk  # noqa: E402
from adapters import prodtools_entry as pe  # noqa: E402
from kits import KitError, KitTimeout, KitToolError  # noqa: E402
from study import Step  # noqa: E402

USER = "tester"


class FakeServer:
    def __init__(self, tools, handler):
        self.tools, self.handler = frozenset(tools), handler
        self.started, self.server_version = True, "p9"
        self.config = SimpleNamespace(timeouts=defaultdict(lambda: 1.0))
        self.calls = []

    def start(self):
        pass

    def close(self):
        pass

    def call(self, tool, args, *, timeout_s, workflow):
        self.calls.append((tool, dict(args)))
        return self.handler(tool, dict(args))


class FakeProdtools:
    """Both prodtools servers over one table of runs, keyed by run name.
    Replies are JSON-shaped: `outputs` is keyed by string indices."""

    def __init__(self, root):
        self.root, self.runs, self.entries = Path(root), {}, {}
        self.raise_after_submit = None
        self.autofinish = False
        self.write = FakeServer({"submit_once", "run_local"}, self._write)
        self.read = FakeServer({"run_status"}, self._read)

    def _write(self, tool, args):
        if tool == "cancel_run":
            self.runs[args["name"]]["state"] = "cancelled"
            return {"name": args["name"], "state": "cancelled"}
        (entry,) = json.loads(Path(args["json"]).read_text())
        name = f"cnf.{entry['owner']}.{args['desc']}.{args['dsconf']}.0"
        if name in self.runs:
            raise KitToolError("prodtools-write", tool,
                               f"{name} exists: a desc+dsconf pair is used "
                               f"once")
        self.entries[name] = entry
        run_dir = self.root / "runs" / name
        run_dir.mkdir(parents=True)
        self.runs[name] = {
            "name": name, "njobs": entry["njobs"], "cluster_id": 77,
            "state": "submitted" if tool == "submit_once" else "running",
            "jobid": "77.0@schedd.example",
            "outstage": str(self.root / "outstage"),
            "host": "node.example", "pid": 4242,
            "receipt": str(run_dir / "receipt.json")}
        if self.raise_after_submit is not None:
            exc, self.raise_after_submit = self.raise_after_submit, None
            raise exc
        return copy.deepcopy(self.runs[name])

    def _read(self, tool, args):
        run = self.runs.get(args["name"])
        if run is None:
            return {"error": {"kind": "not_found",
                              "message": f"no run {args['name']!r}",
                              "remedy": ""}}
        if self.autofinish and run["state"] in ("submitted", "running"):
            self.finish(args["name"], {i: 0 for i in range(run["njobs"])},
                        grid=run["state"] == "submitted")
        return copy.deepcopy(run)

    def finish(self, name, rcs, *, pattern=None, log=True, grid=True):
        """Every job ended with rcs[index]; each ok job wrote one output."""
        run = self.runs[name]
        entry = self.entries[name]
        glob_word = entry["fcl_overrides"].get(
            "outputs.TargetStopOutput.fileName", "")
        pattern = pattern or ("sim.x.TargetStops.y.{i:08d}.art"
                              if glob_word else "dts.x.CeEndpoint.y.{i:08d}.art")
        outputs = {}
        for i, rc in rcs.items():
            d = (Path(run["outstage"]) / "77" / f"{i:05d}" if grid
                 else Path(run["receipt"]).parent / f"job_{i:06d}")
            d.mkdir(parents=True, exist_ok=True)
            if log:
                (d / "job.log").write_text("ok\n")
            if rc == 0:
                out = d / pattern.format(i=i)
                out.write_text("x")
                outputs[str(i)] = [str(out)]
        failed = [i for i, rc in rcs.items() if rc != 0]
        jobs = {"expected": len(rcs), "ok": len(outputs), "failed": failed,
                "unknown": []}
        if failed:
            jobs["exit_codes"] = {str(i): rcs[i] for i in failed}
        run.update(state="short" if failed else "done", jobs=jobs,
                   outputs=outputs)


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.fake = FakeProdtools(self.tmp / "prodtools")
        self.clock = [1000.0]
        patch = mock.patch.object(pe, "USER", USER)
        patch.start()
        self.addCleanup(patch.stop)
        code = self.tmp / "src" / "Code"
        code.mkdir(parents=True)
        (code / "setup.sh").write_text("echo setup\n")
        self.base = self.tmp / "Code_base.tar.bz2"
        with tarfile.open(self.base, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text("// geom\n")

    def kit(self, executor="grid", cancel=False, parallel=None):
        if cancel:
            self.fake.write.tools = self.fake.write.tools | {"cancel_run"}
        return pk.ProdtoolsKit(
            "camp", executor=executor, parallel=parallel,
            clients={"write": self.fake.write, "read": self.fake.read},
            clock=lambda: self.clock[0], pause=lambda s: None,
            grid_root=self.tmp / "grid", pnfs_root=self.tmp / "pnfs",
            submit_lock=self.tmp / "submit.lock")

    def params(self, step="mubeam", **over):
        entry = json.loads((ROOT / "stage_entries" / f"{step}.json")
                           .read_text())
        p = {"entry": entry, "code_tarball": str(self.base),
             "fatal_log_codes": ["GeomSolids1001"], "njobs": 2,
             "events_per_job": 200, "memory_mb": 2000, "quorum": 0.5}
        p.update(over)
        return p

    def files(self):
        return [{"name": "geom", "uri": self.geom.as_uri(), "kind": "geom"}]

    def submit(self, kit, name="cfg1.mubeam", step="mubeam", inputs=(),
               **over):
        return kit.submit(name, self.params(step, **over), self.files(),
                          list(inputs), "camp/cfg1/mubeam")

    def run_name(self, desc="Run1A_MuBeam_cfg1"):
        return f"cnf.{USER}.{desc}.Run1Bak_cfg1.0"

    def record_path(self, step="mubeam"):
        return self.tmp / "grid" / "cfg1" / "prodtools" / step / "record.json"

    def record(self, step="mubeam"):
        return json.loads(self.record_path(step).read_text())

    def set_record(self, step="mubeam", **fields):
        rec = self.record(step)
        rec.update(fields)
        self.record_path(step).write_text(json.dumps(rec))


class TestSubmit(_Kit):
    def test_a_first_submit_renders_the_entry_and_records_the_run(self):
        self.assertEqual(self.submit(self.kit()), "cfg1.mubeam")
        entry = self.fake.entries[self.run_name()]
        self.assertEqual((entry["njobs"], entry["events"], entry["memory"]),
                         (2, 200, "2000MB"))
        self.assertEqual(
            entry["fcl_overrides"]["services.GeometryService.inputFile"],
            "autoresearch_cfg1_geom.txt")
        with tarfile.open(entry["code"]) as tf:
            names = set(tf.getnames())
        self.assertTrue({"Code/autoresearch_cfg1_geom.txt",
                         "Code/sim_kept_products_extras.fcl",
                         "Code/setup_post.sh"} <= names)
        rec = self.record()
        self.assertEqual((rec["state"], rec["run_name"], rec["executor"]),
                         ("submitted", self.run_name(), "grid"))
        self.assertTrue((self.tmp / "submit.lock").exists())
        self.assertEqual([c[0] for c in self.fake.write.calls],
                         ["submit_once"])

    def test_the_same_params_again_do_not_submit_twice(self):
        kit = self.kit()
        self.submit(kit)
        self.submit(kit)
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_different_params_are_refused(self):
        kit = self.kit()
        self.submit(kit)
        with self.assertRaises(ValueError) as cm:
            self.submit(kit, njobs=3)
        self.assertIn("other params", str(cm.exception))

    def test_a_crash_after_the_receipt_is_adopted(self):
        self.submit(self.kit())
        self.set_record(state="submitting")
        self.submit(self.kit())
        self.assertEqual(len(self.fake.write.calls), 1)
        self.assertEqual(self.record()["state"], "submitted")

    def test_a_crash_before_the_receipt_submits_again(self):
        self.submit(self.kit())
        del self.fake.runs[self.run_name()]
        self.set_record(state="submitting")
        self.submit(self.kit())
        self.assertEqual(len(self.fake.write.calls), 2)

    def test_a_receipt_stuck_in_submitting_fails_loudly(self):
        self.submit(self.kit())
        self.fake.runs[self.run_name()]["state"] = "submitting"
        self.set_record(state="submitting")
        with self.assertRaises(KitError) as cm:
            self.submit(self.kit())
        self.assertIn("jobsub_q", str(cm.exception))

    def test_a_timeout_whose_run_exists_is_adopted(self):
        self.fake.raise_after_submit = KitTimeout("prodtools", "submit_once",
                                                  "timed out")
        self.submit(self.kit())
        self.assertEqual(self.record()["state"], "submitted")

    def test_a_timeout_with_no_run_raises_and_stays_submitting(self):
        def boom(tool, args):
            raise KitTimeout("prodtools", tool, "timed out")
        self.fake.write.handler = boom
        with self.assertRaises(KitTimeout):
            self.submit(self.kit())
        self.assertEqual(self.record()["state"], "submitting")

    def test_local_runs_run_local_with_parallel(self):
        self.submit(self.kit(executor="local", parallel=3))
        tool, args = self.fake.write.calls[0]
        self.assertEqual((tool, args["parallel"]), ("run_local", 3))
        self.assertFalse((self.tmp / "submit.lock").exists())

    def upstream(self, n=2):
        d = self.tmp / "up"
        d.mkdir(exist_ok=True)
        refs = []
        for i in range(n):
            f = d / f"sim.x.TargetStops.y.{i}.art"
            f.write_text(str(i))
            refs.append({"name": f.name, "uri": f.as_uri(), "kind": "art"})
        return refs

    def test_inputs_are_hard_linked_into_the_staged_dir(self):
        refs = self.upstream()
        self.submit(self.kit(), name="cfg1.mustops_ce", step="mustops_ce",
                    inputs=refs)
        entry = self.fake.entries[self.run_name("Run1A_CeEndpoint_cfg1")]
        staged = self.tmp / "pnfs" / "cfg1" / "staged" / "mustops_ce"
        self.assertEqual(entry["inloc"], f"dir:{staged}")
        self.assertEqual(entry["input_data"], {r["name"]: 1 for r in refs})
        self.assertEqual(os.stat(staged / refs[0]["name"]).st_ino,
                         os.stat(self.tmp / "up" / refs[0]["name"]).st_ino)

    def test_grid_staging_never_copies(self):
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev), \
                self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=self.upstream())
        self.assertIn("staging", str(cm.exception))

    def test_local_staging_copies_across_devices(self):
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev):
            self.submit(self.kit(executor="local"), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=self.upstream(1))
        staged = (self.tmp / "grid" / "cfg1" / "prodtools" / "mustops_ce"
                  / "staged")
        self.assertTrue((staged / "sim.x.TargetStops.y.0.art").exists())

    def test_a_non_file_input_is_refused(self):
        ref = {"name": "a.art", "uri": "root://fndca/pnfs/a.art",
               "kind": "art"}
        with self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), name="cfg1.mustops_ce",
                        step="mustops_ce", inputs=[ref])
        self.assertIn("file://", str(cm.exception))

    def test_config_names_with_other_characters_are_refused(self):
        for name, needle in (("cfg-1.mubeam", "'-'"),
                             ("cfg.1.mubeam", "'.'"),
                             ("mubeam", "<config>.<step>")):
            with self.subTest(name=name), \
                    self.assertRaises(ValueError) as cm:
                self.kit().submit(name, self.params(), self.files(), [], "w")
            self.assertIn(needle, str(cm.exception))
        self.assertEqual(self.fake.write.calls, [])

    def test_unknown_params_are_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.submit(self.kit(), bogus=1)
        self.assertIn("bogus", str(cm.exception))

    def test_a_template_naming_geom_without_a_geom_file_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.kit().submit("cfg1.mubeam", self.params(), [], [], "w")
        self.assertIn("{geom}", str(cm.exception))


class TestStatus(_Kit):
    def submitted(self, executor="grid", **over):
        kit = self.kit(executor=executor)
        self.submit(kit, **over)
        return kit, self.run_name()

    def state(self, kit):
        return kit.status("cfg1.mubeam", "w")

    def test_running_is_working(self):
        kit, name = self.submitted()
        self.fake.runs[name]["state"] = "running"
        self.assertEqual(self.state(kit).state, "working")

    def test_unknown_is_working_until_six_hours_then_failed(self):
        kit, name = self.submitted()
        self.fake.runs[name].update(state="unknown", note="schedd away")
        self.assertEqual(self.state(kit).state, "working")
        self.clock[0] += 6 * 3600
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("6 h", s.message)

    def test_failed_carries_the_prodtools_error(self):
        kit, name = self.submitted()
        self.fake.runs[name].update(state="failed", error="json2jobdef died")
        s = self.state(kit)
        self.assertEqual((s.state, "json2jobdef died" in s.message),
                         ("failed", True))

    def test_done_is_completed_and_results_carry_files_and_metadata(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        self.assertEqual(self.state(kit).state, "completed")
        res = kit.results("cfg1.mubeam", "w")
        self.assertEqual(res.metrics, {"njobs": 2.0, "njobs_ok": 2.0})
        self.assertEqual(len(res.files), 2)
        self.assertTrue(res.files[0]["uri"].startswith("file://"))
        self.assertEqual(res.files[0]["kind"], "art")
        md = res.metadata
        self.assertEqual((md["events_per_job"], md["executor"], md["jobid"],
                          md["prodtools_version"]),
                         (200, "grid", "77.0@schedd.example", "p9"))

    def test_below_quorum_fails(self):
        kit, name = self.submitted(quorum=0.8)
        self.fake.finish(name, {0: 0, 1: 1})
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("1/2 jobs ok, below quorum 0.8", s.message)

    def test_zero_ok_fails_even_at_a_low_quorum(self):
        kit, name = self.submitted(quorum=0.01)
        self.fake.finish(name, {0: 1, 1: 1})
        self.assertEqual(self.state(kit).state, "failed")

    def test_missing_outputs_wait_for_stage_out_then_fail(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        Path(self.fake.runs[name]["outputs"]["1"][0]).unlink()
        s = self.state(kit)
        self.assertEqual(s.state, "working")
        self.assertIn("waiting for stage-out", s.message)
        self.clock[0] += 30 * 60
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("still missing", s.message)

    def test_a_fatal_log_code_fails_the_step(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        log = Path(self.fake.runs[name]["outputs"]["0"][0]).parent / "job.log"
        log.write_text("... GeomSolids1001 ...\n")
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("GeomSolids1001", s.message)

    def test_a_successful_job_without_a_log_fails_the_step(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0}, log=False)
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("no .log", s.message)

    def test_no_output_matching_the_glob_fails(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0}, pattern="dts.x.Other.y.{i}.art")
        s = self.state(kit)
        self.assertEqual(s.state, "failed")
        self.assertIn("matches", s.message)

    def test_the_verdict_is_reused(self):
        kit, name = self.submitted()
        self.fake.finish(name, {0: 0, 1: 0})
        self.state(kit)
        calls = len(self.fake.read.calls)
        self.assertEqual(self.state(kit).state, "completed")
        self.assertEqual(len(self.fake.read.calls), calls)

    def test_local_logs_are_read_from_the_job_dirs(self):
        kit, name = self.submitted(executor="local")
        self.fake.finish(name, {0: 0, 1: 0}, grid=False)
        log = Path(self.fake.runs[name]["outputs"]["1"][0]).parent / "job.log"
        log.write_text("GeomSolids1001\n")
        self.assertEqual(self.state(kit).state, "failed")

    def test_an_error_reply_other_than_not_found_is_raised_after_retries(self):
        kit, _ = self.submitted()
        self.fake.read.handler = lambda tool, args: {
            "error": {"kind": "auth_expired", "message": "token expired",
                      "remedy": "renew"}}
        with self.assertRaises(KitToolError) as cm:
            self.state(kit)
        self.assertIn("auth_expired", str(cm.exception))
        self.assertEqual(len(self.fake.read.calls), 3)
        self.assertEqual(len(self.fake.write.calls), 1)

    def test_results_before_completed_are_refused(self):
        kit, _ = self.submitted()
        with self.assertRaises(KitError):
            kit.results("cfg1.mubeam", "w")


class TestCancelAndLaunch(_Kit):
    def test_cancel_is_offered_only_with_cancel_run(self):
        self.assertNotIn("cancel", self.kit().tools)
        self.assertIn("cancel", self.kit(cancel=True).tools)

    def test_cancel_calls_cancel_run_once(self):
        kit = self.kit(cancel=True)
        self.submit(kit)
        self.assertEqual(kit.cancel("cfg1.mubeam", "w"), "cancelled")
        self.assertEqual([c[0] for c in self.fake.write.calls],
                         ["submit_once", "cancel_run"])
        self.assertEqual(kit.status("cfg1.mubeam", "w").state, "cancelled")

    def test_a_write_server_without_the_executors_tool_is_refused(self):
        self.fake.write.tools = frozenset({"run_local"})
        with self.assertRaises(KitError) as cm:
            self.kit().tools
        self.assertIn("submit_once", str(cm.exception))
        self.fake.write.tools = frozenset({"submit_once"})
        with self.assertRaises(KitError) as cm:
            self.kit(executor="local").tools
        self.assertIn("run_local", str(cm.exception))

    def test_describe_and_version(self):
        kit = self.kit()
        self.assertIn("quorum", kit.describe().params)
        self.assertEqual(kit.describe().metrics, ("njobs", "njobs_ok"))
        self.assertEqual(kit.version, "prodtools-adapter/1")


class TestWithRunSteps(_Kit):
    def test_mubeam_then_mustops_ce_stages_the_mubeam_outputs(self):
        self.fake.autofinish = True
        entries = {s: json.loads((ROOT / "stage_entries" / f"{s}.json")
                                 .read_text())
                   for s in ("mubeam", "mustops_ce")}
        settings = {"code_tarball": str(self.base),
                    "fatal_log_codes": ["GeomSolids1001"]}
        fixed = {"njobs": 2, "events_per_job": 200, "memory_mb": 2000,
                 "quorum": 1.0}
        study = types.SimpleNamespace(
            steps=(Step("mubeam", "prodtools", "mubeam", ("geom",), (), {},
                        dict(fixed)),
                   Step("mustops_ce", "prodtools", "mustops_ce", ("geom",),
                        ("mubeam",), {}, dict(fixed))),
            kits={"prodtools": settings},
            entry_template=lambda step: copy.deepcopy(entries[step]))

        class Kits:
            def __init__(self, kit):
                self.kit = kit

            def get(self, name):
                return self.kit

        out = scheduler.run_steps(
            study, config="cfg1", state_dir=self.tmp / "state", env={},
            files={"geom": self.files()[0]}, kits=Kits(self.kit()),
            workflow=lambda s: f"camp/cfg1/{s}", sleep=lambda s: None,
            log=lambda m: None)
        self.assertTrue(all(o.ok for o in out.values()),
                        {k: o.message for k, o in out.items()})
        ce = self.fake.entries[self.run_name("Run1A_CeEndpoint_cfg1")]
        mubeam_files = sorted(Path(p).name for p in sum(
            self.fake.runs[self.run_name()]["outputs"].values(), []))
        self.assertEqual(sorted(ce["input_data"]), mubeam_files)


class TestRegistration(unittest.TestCase):
    def test_prodtools_opens_as_the_adapter(self):
        kit = ct.open_kit("prodtools", "camp", executor="local", parallel=2)
        self.assertIsInstance(kit, pk.ProdtoolsKit)
        self.assertEqual((kit.executor, kit.parallel), ("local", 2))

    def test_prodtools_is_an_engine_and_a_pipeline_kit(self):
        d = kit_registry.KITS["prodtools"]
        self.assertTrue(d.engine and d.pipeline)


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_kit_config.py`, `test_pipeline_kits_are_not_engine_kits`: drop `"prodtools"` from its loop (it is now both), and add `self.assertTrue(kit_registry.KITS[name].pipeline)` inside the loop.

In `tests/test_contract.py`, `TestRegistry.test_only_an_engine_kit_without_a_kits_toml_entry_takes_an_adapter`: loop over `("toykit", "nosuchkit", "offline_preflight")` instead of `("prodtools", "toykit", "nosuchkit")` — prodtools now legitimately takes an adapter.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_prodtools_adapter -v`
Expected: FAIL (`No module named 'adapters.prodtools'`).

- [ ] **Step 3: Implement `core/adapters/prodtools.py`**

```python
"""prodtools as a contract kit: the adapter the engine drives for every
`kit: "prodtools"` step (Phase C1 spec,
docs/superpowers/specs/2026-09-25-prodtools-kit-design.md, "The adapter").

submit renders the step's stage template into a json2jobdef entry, builds
the per-config code tarball, hard-links the upstream outputs into a dir:
area, and hands the entry to prodtools' submit_once (grid) or run_local
(local) over MCP. status and results read prodtools' run_status and apply
autoresearch's acceptance: quorum, stage-out, the fatal-log scan.

A step's record, <GRID_DATA_ROOT>/<config>/prodtools/<step>/record.json,
is written before the submit and updated after, so a killed child re-run
on the same point adopts the run instead of submitting it twice; the
completion verdict is kept there too.
"""
from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ == "core.adapters":
    from core import kit_config, paths
    from core.adapters import prodtools_entry as pe
    from core.contract import (Describe, call_with_retries, parse_cancel,
                               parse_results, parse_status)
    from core.kits import KitClient, KitError, KitToolError
else:
    import kit_config
    import paths
    from adapters import prodtools_entry as pe
    from contract import (Describe, call_with_retries, parse_cancel,
                          parse_results, parse_status)
    from kits import KitClient, KitError, KitToolError

VERSION = "prodtools-adapter/1"      # bump when a step would measure anew
PARAMS = ("entry", "code_tarball", "fatal_log_codes", "njobs",
          "events_per_job", "memory_mb", "quorum")
METRICS = ("njobs", "njobs_ok")
DEFAULT_PARALLEL = 4
UNKNOWN_LIMIT_S = 6 * 3600
STAGEOUT_LIMIT_S = 30 * 60
WORKING = ("building", "submitting", "starting", "submitted", "running")
# The file core/pipeline.py's _submit_lock uses, so both runners serialize
# their grid submits on a host (wiki/incidents/concurrent-token-contention.md).
SUBMIT_LOCK = Path(f"/tmp/mu2e_submit.{pe.USER}.lock")
PNFS_STAGE_ROOT = Path(f"/pnfs/mu2e/scratch/users/{pe.USER}/autoresearch_grid")
_CONFIG = re.compile(r"[A-Za-z0-9_]+")
_POLL = {"grid": ((30.0, 600.0), 60_000), "local": ((5.0, 60.0), 10_000)}


def split_handle(name: str):
    """'<config>.<step>' -> (config, step). The config becomes part of
    prodtools' dot-separated run name, so only letters, digits and _."""
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"prodtools: {name!r} is not <config>.<step>")
    if not _CONFIG.fullmatch(config):
        bad = sorted(set(_CONFIG.sub("", config)))
        raise ValueError(
            f"prodtools: config name {config!r} has character(s) "
            f"{', '.join(repr(c) for c in bad)}; only letters, digits and _ "
            f"may appear, because the config is part of prodtools' "
            f"dot-separated run name")
    return config, step


def _digest(blob) -> str:
    return hashlib.sha256(json.dumps(blob, sort_keys=True,
                                     separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None


def _write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


def _local_path(ref, what) -> Path:
    uri = ref.get("uri", "")
    if not uri.startswith("file://"):
        raise ValueError(f"prodtools: {what} {ref.get('name')!r} is "
                         f"{uri!r}; only file:// URIs can be staged")
    return Path(unquote(urlparse(uri).path))


@contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _progress(reply):
    jobs = reply.get("jobs")
    if not jobs:
        return None
    ok = int(jobs.get("ok", 0))
    failed = int((jobs.get("truncated") or {}).get(
        "failed", len(jobs.get("failed") or [])))
    return {"done": ok + failed, "total": int(jobs.get("expected", 0)),
            "ok": ok}


class ProdtoolsKit:
    """One campaign child's handle on prodtools. run_steps' threads share
    it, one step each; every write is per step or content-addressed."""

    name = "prodtools"
    accepts_lists = False
    EXECUTORS = ("grid", "local")
    REQUIRES_KERBEROS = True
    LAUNCH_STAGGER_S = 90.0

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 clients=None, clock=time.time, pause=time.sleep,
                 grid_root=None, pnfs_root=None, templates_root=None,
                 submit_lock=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"prodtools: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign, self.executor = campaign, executor
        self.parallel = DEFAULT_PARALLEL if parallel is None else parallel
        self.poll_s, self._poll_ms = _POLL[executor]
        if clients is None:
            servers = kit_config.load_server_configs()
            trace = paths.GRAPH_DATA / campaign
            clients = {role: KitClient(servers[f"prodtools_{role}"],
                                       campaign=campaign, trace_dir=trace)
                       for role in ("write", "read")}
        self._write, self._read = clients["write"], clients["read"]
        self._clock, self._pause = clock, pause
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._pnfs_root = Path(pnfs_root or PNFS_STAGE_ROOT)
        self._templates = Path(templates_root or pe.TEMPLATES_ROOT)
        self._submit_lock = Path(submit_lock or SUBMIT_LOCK)

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return VERSION

    @property
    def tools(self) -> frozenset:
        self._ensure_started()
        out = {"submit", "status", "results", "describe"}
        if "cancel_run" in self._write.tools:
            out.add("cancel")
        return frozenset(out)

    def describe(self):
        return Describe(PARAMS, METRICS, False)

    def close(self) -> None:
        for client in (self._write, self._read):
            client.close()

    def submit(self, name, params, files, inputs, workflow) -> str:
        config, step = split_handle(name)
        unknown = sorted(set(params) - set(PARAMS))
        if unknown:
            raise ValueError(f"prodtools: unknown param(s) {unknown}; it "
                             f"accepts {list(PARAMS)}")
        for key in ("entry", "code_tarball", "fatal_log_codes", "quorum"):
            if key not in params:
                raise ValueError(f"prodtools: param {key!r} is missing")
        sdir = self._step_dir(config, step)
        digest = _digest({"params": params, "files": list(files),
                          "inputs": list(inputs), "executor": self.executor})
        rec = _read_json(sdir / "record.json")
        if rec is not None:
            if rec["digest"] != digest:
                raise ValueError(
                    f"prodtools: {name!r} was already submitted with other "
                    f"params, files, inputs or executor "
                    f"({sdir / 'record.json'}: digest {rec['digest'][:12]}, "
                    f"now {digest[:12]}); the same name with different "
                    f"params is an error")
            if rec["state"] == "submitted":
                return name
            if self._adopt(rec, workflow):
                self._save(sdir, rec, state="submitted")
                return name
        rec = self._prepare(name, config, step, params, files, inputs, sdir,
                            digest)
        self._save(sdir, rec)          # "submitting", before prodtools acts
        try:
            self._launch(rec, workflow)
        except KitError:
            if not self._adopt(rec, workflow):
                raise
        self._save(sdir, rec, state="submitted")
        return name

    def status(self, handle, workflow):
        sdir, rec = self._submitted(handle, "status")
        if "verdict" in rec:
            return self._status_of(rec["verdict"])
        reply = self._run_status(rec["run_name"], workflow)
        if reply is None:
            raise KitError(self.name, "status",
                           f"prodtools has no run {rec['run_name']!r}, though "
                           f"{sdir / 'record.json'} says it was submitted")
        state, progress = reply.get("state"), _progress(reply)
        if state == "unknown":
            since = rec.setdefault("unknown_since", self._clock())
            self._save(sdir, rec)
            note = reply.get("note")
            if self._clock() - since >= UNKNOWN_LIMIT_S:
                return self._decide(
                    sdir, rec, "failed",
                    f"run_status has said unknown for "
                    f"{UNKNOWN_LIMIT_S // 3600} h"
                    + (f": {note}" if note else ""))
            return self._working(f"unknown: {note or 'no note'}", progress)
        if rec.pop("unknown_since", None) is not None:
            self._save(sdir, rec)
        if state in WORKING:
            return self._working(state, progress)
        if state == "failed":
            return self._decide(sdir, rec, "failed", "prodtools: " + str(
                reply.get("error") or reply.get("note") or "failed"))
        if state == "cancelled":
            return self._decide(sdir, rec, "cancelled", "prodtools: cancelled")
        if state in ("done", "short"):
            return self._complete(sdir, rec, reply, progress)
        raise KitError(self.name, "status",
                       f"run_status returned state {state!r} for "
                       f"{rec['run_name']}, which this adapter does not know")

    def results(self, handle, workflow):
        _sdir, rec = self._submitted(handle, "results")
        verdict = rec.get("verdict") or {}
        if verdict.get("state") != "completed":
            raise KitError(self.name, "results",
                           f"{handle} is {verdict.get('state', 'unfinished')}"
                           f", not completed")
        return parse_results({"metrics": {"njobs": rec["njobs"],
                                          "njobs_ok": verdict["ok"]},
                              "files": rec["files"],
                              "metadata": rec["metadata"]}, self.name)

    def cancel(self, handle, workflow) -> str:
        _sdir, rec = self._submitted(handle, "cancel")
        if "cancel_run" not in self._write.tools:
            raise KitError(self.name, "cancel",
                           "the prodtools write server has no cancel_run tool")
        reply = self._call(self._write, "cancel_run",
                           {"name": rec["run_name"], "run_as": "self"},
                           workflow)
        return parse_cancel({"state": reply.get("state")}, self.name)

    # --- submit ------------------------------------------------------------
    def _ensure_started(self) -> None:
        for client in (self._write, self._read):
            if not client.started:
                client.start()
        need = "submit_once" if self.executor == "grid" else "run_local"
        if need not in self._write.tools:
            raise KitError(self.name, "start",
                           f"the prodtools write server has no {need!r} tool "
                           f"(it has {sorted(self._write.tools)}); point "
                           f"AUTORESEARCH_PRODTOOLS at a checkout with code "
                           f"entries and run_local")
        if "run_status" not in self._read.tools:
            raise KitError(self.name, "start",
                           f"the prodtools read server has no 'run_status' "
                           f"tool (it has {sorted(self._read.tools)})")

    def _step_dir(self, config, step) -> Path:
        return self._grid_root / config / "prodtools" / step

    def _prepare(self, name, config, step, params, files, inputs, sdir,
                 digest) -> dict:
        geom = [f for f in files if f.get("name") == "geom"]
        geom_path = _local_path(geom[0], "file") if geom else None
        geom_name = f"autoresearch_{config}_geom.txt" if geom else None
        template = params["entry"]
        staged = None
        if inputs:
            sources = [_local_path(ref, "input") for ref in inputs]
            dest = (self._pnfs_root / config / "staged" / step
                    if self.executor == "grid" else sdir / "staged")
            try:
                staged = (dest, pe.link_inputs(
                    sources, dest, allow_copy=self.executor == "local"))
            except OSError as exc:
                raise ValueError(f"prodtools: staging {len(sources)} "
                                 f"input(s) into {dest} failed: {exc}") from exc
        tarball = pe.build_code_tarball(
            Path(params["code_tarball"]), geom_path=geom_path,
            geom_name=geom_name,
            extra_files=pe.include_files(template, self._templates),
            out_dir=self._grid_root / config / "prodtools")
        fixed = {k: params[k] for k in ("njobs", "events_per_job",
                                        "memory_mb") if k in params}
        entry, facts = pe.entry_for_step(template, config=config, fixed=fixed,
                                         code_tarball=str(tarball),
                                         geom_name=geom_name, staged=staged)
        entry_path = pe.write_entry_file(sdir / "entry.json", entry)
        return {"name": name, "digest": digest, "executor": self.executor,
                "state": "submitting", "entry_path": str(entry_path),
                "run_name": (f"cnf.{entry['owner']}.{facts['desc']}."
                             f"{facts['dsconf']}.0"),
                "desc": facts["desc"], "dsconf": facts["dsconf"],
                "njobs": facts["njobs"],
                "events_per_job": facts["events_per_job"],
                "output_glob": facts["output_glob"],
                "quorum": params["quorum"],
                "fatal_log_codes": list(params["fatal_log_codes"])}

    def _launch(self, rec, workflow) -> None:
        args = {"json": rec["entry_path"], "desc": rec["desc"],
                "dsconf": rec["dsconf"], "run_as": "self"}
        if self.executor == "grid":
            with _flock(self._submit_lock):
                receipt = self._call(self._write, "submit_once", args,
                                     workflow)
        else:
            receipt = self._call(self._write, "run_local",
                                 dict(args, parallel=self.parallel), workflow)
        if receipt.get("name") != rec["run_name"]:
            raise KitError(self.name, "submit",
                           f"prodtools named the run {receipt.get('name')!r}; "
                           f"expected {rec['run_name']!r}")

    def _adopt(self, rec, workflow) -> bool:
        """True when prodtools already has this step's run, past
        submission; False when it has none. A receipt stuck in submitting
        or building is an error: whether jobs reached the grid is unknown."""
        reply = self._run_status(rec["run_name"], workflow)
        if reply is None:
            return False
        if reply.get("state") in ("submitting", "building"):
            raise KitError(
                self.name, "submit",
                f"{rec['run_name']}: its receipt is stuck in "
                f"{reply['state']!r}, so whether its jobs reached the grid "
                f"cannot be told. Look for its cluster in jobsub_q; this "
                f"point needs a new config name")
        return True

    # --- status ------------------------------------------------------------
    def _submitted(self, handle, call):
        config, step = split_handle(handle)
        sdir = self._step_dir(config, step)
        rec = _read_json(sdir / "record.json")
        if rec is None or rec.get("state") != "submitted":
            raise KitError(self.name, call, f"{handle}: no submitted run is "
                           f"recorded in {sdir / 'record.json'}")
        return sdir, rec

    def _complete(self, sdir, rec, reply, progress):
        jobs = reply.get("jobs") or {}
        njobs, ok = int(rec["njobs"]), int(jobs.get("ok", 0))
        if reply.get("outputs_truncated") is not None:
            return self._decide(
                sdir, rec, "failed",
                f"run_status truncated the output list "
                f"({reply['outputs_truncated']} ok jobs), so not every "
                f"output can be seen")
        if ok == 0 or ok / njobs < rec["quorum"]:
            return self._decide(sdir, rec, "failed",
                                f"{ok}/{njobs} jobs ok, below quorum "
                                f"{rec['quorum']}", progress=progress)
        outputs = {int(i): list(p)
                   for i, p in (reply.get("outputs") or {}).items()}
        every = [p for ps in outputs.values() for p in ps]
        missing = [p for p in every if not os.path.exists(p)]
        if missing:
            since = rec.setdefault("missing_since", self._clock())
            self._save(sdir, rec)
            if self._clock() - since >= STAGEOUT_LIMIT_S:
                return self._decide(
                    sdir, rec, "failed",
                    f"{len(missing)} of {len(every)} outputs still missing "
                    f"{STAGEOUT_LIMIT_S // 60} min after the jobs ended, "
                    f"e.g. {missing[0]}")
            return self._working(f"waiting for stage-out: {len(missing)} of "
                                 f"{len(every)} outputs missing", progress)
        problem = self._scan_logs(rec, reply, outputs)
        if problem:
            return self._decide(sdir, rec, "failed", problem,
                                progress=progress)
        files = [{"name": Path(p).name, "uri": Path(p).absolute().as_uri(),
                  "kind": Path(p).suffix.lstrip(".") or "file"}
                 for p in sorted(every)
                 if fnmatch.fnmatch(Path(p).name, rec["output_glob"])]
        if not files:
            return self._decide(
                sdir, rec, "failed",
                f"no output of the {ok} successful jobs matches "
                f"{rec['output_glob']!r}, so a downstream step would get no "
                f"inputs")
        rec["files"], rec["metadata"] = files, self._metadata(rec, reply)
        return self._decide(sdir, rec, "completed",
                            f"{ok}/{njobs} jobs ok", ok=ok, progress=progress)

    def _scan_logs(self, rec, reply, outputs):
        for index, job_paths in sorted(outputs.items()):
            job_dir = Path(job_paths[0]).parent if job_paths else None
            if job_dir is None or not any(job_dir.glob("*.log")):
                where = f" in {job_dir}" if job_dir else ""
                return (f"job {index} succeeded but has no .log file{where}, "
                        f"so the fatal-log scan could not run")
        if self.executor == "grid":
            # prodtools' flat <outstage>/<cluster>/<proc>/ layout.
            logs = (Path(reply["outstage"]) / str(reply["cluster_id"])).glob(
                "*/*.log")
        else:
            logs = Path(reply["receipt"]).parent.glob("job_*/*.log")
        for log in sorted(logs):
            text = log.read_text(errors="replace")
            for code in rec["fatal_log_codes"]:
                if code in text:
                    return f"fatal log code {code} in {log}"
        return None

    def _metadata(self, rec, reply) -> dict:
        codes = (reply.get("jobs") or {}).get("exit_codes") or {}
        md = {"events_per_job": rec["events_per_job"],
              "executor": self.executor, "run_name": rec["run_name"],
              "desc": rec["desc"], "dsconf": rec["dsconf"],
              "failed_exit_codes": {str(k): v for k, v in codes.items()},
              "prodtools_version": self._write.server_version}
        if self.executor == "grid":
            md.update(jobid=reply.get("jobid"), outstage=reply.get("outstage"))
        else:
            md.update(host=reply.get("host"), pid=reply.get("pid"),
                      run_dir=str(Path(reply["receipt"]).parent))
        return md

    # --- plumbing ----------------------------------------------------------
    def _call(self, client, tool, args, workflow):
        return client.call(tool, args, timeout_s=client.config.timeouts[tool],
                           workflow=workflow)

    def _run_status(self, run_name, workflow):
        """run_status for one run, or None when prodtools has no such run.
        The read server reports failures as {"error": {kind, ...}}; any
        kind but not_found is raised, after the read-only retries."""
        def once():
            reply = self._call(self._read, "run_status",
                               {"name": run_name, "user": pe.USER}, workflow)
            err = reply.get("error")
            if err and err.get("kind") != "not_found":
                raise KitToolError(
                    self.name, "run_status",
                    f"{err.get('kind')}: {err.get('message')} "
                    f"{err.get('remedy') or ''}".strip())
            return reply
        reply = call_with_retries(once, retry_tool_errors=True,
                                  pause=self._pause)
        return None if reply.get("error") else reply

    def _save(self, sdir, rec, **fields) -> None:
        rec.update(fields)
        _write_json(sdir / "record.json", rec)

    def _working(self, message, progress):
        return parse_status({"state": "working", "message": message,
                             "poll_ms": self._poll_ms, "progress": progress},
                            self.name)

    def _decide(self, sdir, rec, state, message, **extra):
        rec["verdict"] = {"state": state, "message": message, **extra}
        self._save(sdir, rec)
        return self._status_of(rec["verdict"])

    def _status_of(self, verdict):
        return parse_status({"state": verdict["state"],
                             "message": verdict["message"], "poll_ms": 0,
                             "progress": verdict.get("progress")}, self.name)
```

- [ ] **Step 4: Register it and make `prodtools` an engine kit**

`core/adapters/__init__.py`, `register_all` body:

```python
    if __package__ == "core.adapters":
        from core.adapters.prodtools import ProdtoolsKit
    else:
        from adapters.prodtools import ProdtoolsKit
    if "prodtools" not in adapters:
        register("prodtools", ProdtoolsKit)
```

`core/kit_registry.py`: `prodtools` gets `engine=True` (keep `pipeline=True`).

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass. The foilspf specs must still be pipeline studies (`offline_preflight` and the two analysis kits are not engine kits), which the existing `test_a_pipeline_study_does_not` pins.

- [ ] **Step 6: Commit**

```bash
git add core/adapters/prodtools.py core/adapters/__init__.py core/kit_registry.py \
  tests/test_prodtools_adapter.py tests/test_contract.py tests/test_kit_config.py
git commit -m "feat(adapters): prodtools adapter on submit_once/run_local/run_status"
```

---

### Task 8: The smoke study, and the docs

**Files:**
- Create: `tests/fixtures/engine_studies/prodtools_smoke.json`
- Modify: `tests/test_study_engine.py`
- Modify: `CONTEXT.md`, `mode_specs/README.md`, `wiki/drivers/contract-engine.md`, `wiki/index.md`, `wiki/log.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the `prodtools_smoke` engine study the acceptance runs use.

- [ ] **Step 1: Write the failing test**

In `tests/test_study_engine.py`, change `test_engine_studies_stay_out_of_specs`'s expected last line to `"['branin', 'prodtools_smoke'] False True"`, and add:

```python
X_GRIDPHASEA01 = [67.7974, 111.1044, 132.7585, 0.140557, 0.027008, 0.107443,
                  0.4844, 0.95, 0.95, 11.0982]


class TestProdtoolsSmoke(unittest.TestCase):
    def test_it_is_foilspfbpz_at_one_fixed_point(self):
        smoke = st.load_study_file(ENGINE_STUDIES / "prodtools_smoke.json")
        bpz = st.load_study_file(ROOT / "mode_specs" / "foilspfbpz.json")
        self.assertEqual(smoke.knobs, ())
        self.assertTrue(modes.runs_on_engine(smoke))
        self.assertEqual(smoke.geom.render([]),
                         bpz.geom.render(X_GRIDPHASEA01))
        self.assertEqual([s.step for s in smoke.steps],
                         ["mubeam", "mustops_ce"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_engine -v`
Expected: FAIL (no such file).

- [ ] **Step 3: Generate the smoke study**

Run once from the repo root:

```python
import json
src = json.load(open("mode_specs/foilspfbpz.json"))
names = [k["name"] for k in src["knobs"]]
x = [67.7974, 111.1044, 132.7585, 0.140557, 0.027008, 0.107443,
     0.4844, 0.95, 0.95, 11.0982]          # gridphaseA01, a point that ran
assert names == ["rOut_0", "rOut_1", "rOut_2", "hT_0", "hT_1", "hT_2",
                 "f_0", "f_1", "f_2", "zmid"], names
derive = json.loads(json.dumps(src["derive"]))
derive["consts"].update(dict(zip(names, x)))
doc = {
    "schema": 2,
    "name": "prodtools_smoke",
    "note": ("Phase C1 acceptance, not a measurement: foilspfbpz's geometry "
             "at gridphaseA01's point (the knobs as consts), mubeam 1x200 "
             "then mustops_ce 1 job reading it, on the prodtools kit."),
    "knobs": [],
    "derive": derive,
    "geom": src["geom"],
    "kits": {"prodtools": src["kits"]["prodtools"]},
    "preflight": None,
    "evaluate": [
        {"step": "mubeam", "kit": "prodtools", "entry": "mubeam",
         "files": ["geom"], "files_from": [], "params": {},
         "fixed": {"njobs": 1, "events_per_job": 200, "memory_mb": 2000,
                   "quorum": 1.0}},
        {"step": "mustops_ce", "kit": "prodtools", "entry": "mustops_ce",
         "files": ["geom"], "files_from": ["mubeam"], "params": {},
         "fixed": {"njobs": 1, "events_per_job": 200, "memory_mb": 3000,
                   "quorum": 1.0}}],
    "objectives": [{"name": "ce_jobs_ok", "metric": "mustops_ce.njobs_ok",
                    "direction": "max", "transform": "none", "noise": 1.0,
                    "fmt": "{:.0f}"}],
    "constraints": [],
    "extra_metrics": [{"name": "mubeam_jobs_ok", "metric": "mubeam.njobs_ok",
                       "fmt": "{:.0f}"}],
    "extra_columns": [],
    "leaderboard": {"file": "leaderboards/leaderboard_prodtools_smoke.tsv",
                    "layout": "v2", "context": []},
}
open("tests/fixtures/engine_studies/prodtools_smoke.json", "w").write(
    json.dumps(doc, indent=1) + "\n")
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: all pass. (If another test enumerates `tests/fixtures/engine_studies/` and expects only `branin`, add `prodtools_smoke` to its expectation.)

- [ ] **Step 5: The docs**

- `CONTEXT.md`:
  - **Engine study**: replace "`branin` (...) is the only one as of Phase B." with "`branin` (`tests/fixtures/engine_studies/branin.json`, on `toykit`) and `prodtools_smoke` (the Phase C1 acceptance study, on `prodtools`)."
  - **Pipeline study**: replace "A study's kits are all engine kits or all pipeline kits: a mix runs on neither and is refused" with "A study runs on the engine when the engine can drive every kit it names, otherwise on the pipeline when the pipeline can; one that neither runner can drive whole is refused, and so is a pipeline study with no knobs".
  - **Adapter**: replace "None is registered yet — Phase C adds `prodtools`." with "`prodtools` (`core/adapters/prodtools.py`, Phase C1) is the first; `core/adapters/__init__.py:register_all` registers them."
  - Add an entry **Executor**: "Where a point's jobs run: `grid` (the default) or `local` (this node), chosen by `graph.study_run --executor` / `graph.study_loop --executor` and recorded in the point's `point.json`. Not part of `measure_sha`: the physics is the same. A small test is its own study file with its own board, not a scale-down of a real one."
- `mode_specs/README.md`, section "Engine studies": replace the bullet "A study's kits are all engine kits or all pipeline kits. One that mixes the two runs on neither and is refused (`core/modes.py:runs_on_engine`)." with the three-way rule, and add bullets: "A prodtools step must set `quorum` in `fixed` (below it the step fails), at most 200 `njobs`, and `kits.prodtools.fatal_log_codes` lists the log codes that fail a step (foilspf: `GeomSolids1001`)."; "A stage template names its prodtools `desc_fmt` and `dsconf_fmt`; `{cfg}` and `{geom}` are substituted."; "`knobs: []` is a one-shot study: `graph.study_run` without `--x`; `graph.study_loop` refuses it."; "`--executor grid|local` and `--parallel N` choose where the jobs run; `tests/fixtures/engine_studies/prodtools_smoke.json` is the worked example."
- `wiki/drivers/contract-engine.md`: bump `timestamp`; in Key facts add a subsection "prodtools kit (Phase C1)" summarising: the adapter (`core/adapters/prodtools.py`) and its record file; the entry template arriving as `params["entry"]`; `dsconf_fmt`; the 200-job cap and why; quorum required; the log scan; `unknown` failing after 6 h and missing outputs after 30 min; the submit lock shared with the pipeline; no token refresh in the adapter (the write server's self path does it); `--executor`/`--parallel`; zero-knob studies; cancel of the other steps; `cancel_run` (P3). In Open questions, strike the backoff, cancel and ticket items as done in C1 (keep the rest for C2).
- `wiki/index.md`: extend the contract-engine line with "; C1 prodtools adapter (`core/adapters/`), --executor, zero-knob studies".
- `wiki/log.md`: a bullet under `## 2026-09-25` (create the heading at the top if absent): "**updated** [contract-engine](/drivers/contract-engine.md): Phase C1 implemented on branch `generic-study-phase-c1` — the prodtools adapter, --executor, zero-knob studies, cancel of the other steps."

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/engine_studies/prodtools_smoke.json tests/test_study_engine.py \
  CONTEXT.md mode_specs/README.md wiki/drivers/contract-engine.md wiki/index.md wiki/log.md
git commit -m "docs: prodtools smoke study, engine docs and wiki for Phase C1"
```

---

### Task 9: P3 in the prodtools repo — `cancel_run`

Work in a worktree of `/exp/mu2e/app/users/oksuzian/muse_050125/prodtools`, on a new branch `cancel-run` off its local `main` (6640e6e). Nothing is pushed.

**Files (prodtools repo):**
- Create: `utils/runcancel.py`, `bin/runcancel` (executable)
- Modify: `mcp/src/prodtools_mcp_write/runner.py` (`ALLOWED_ENTRY_POINTS`)
- Modify: `mcp/src/prodtools_mcp_write/tools.py` (`cancel_run`)
- Modify: `mcp/src/prodtools_mcp_write/server.py` (`TOOL_FUNCTIONS`)
- Modify: `mcp/src/prodtools_mcp/server.py` (instructions: the `cancelled` state), `mcp/README.md`, `mcp/SUBMIT.md`
- Test: `test/test_unit.py`

**Interfaces:**
- Produces: write tool `cancel_run(name: str, run_as: str) -> receipt` (state `"cancelled"`); `utils.runcancel.cancel(root, name, *, host=..., alive=..., kill=..., jobsub_rm=...) -> (receipt, run_dir)`; `utils.runcancel.Refused`.

- [ ] **Step 1: Confirm the jobsub_rm form**

On this node: `source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1; jobsub_rm --help 2>&1 | head -30`. Confirm it accepts `-G mu2e --jobid <cluster>@<schedd>` to remove a whole cluster. If the flag differs, use the form it documents and note it in the report.

- [ ] **Step 2: Write the failing tests**

Append to `test/test_unit.py`, before the final `if __name__ == '__main__':` block (use the file's existing `_mkdtemp` helper):

```python
class TestRunCancel(unittest.TestCase):
    """utils/runcancel: cancel a --once run by its receipt."""

    NAME = 'cnf.alice.CeEndpoint.T1.0'

    def setUp(self):
        from utils import run_receipt, runcancel
        self.rr, self.rc = run_receipt, runcancel
        self.root = _mkdtemp()
        self.dir = run_receipt.reserve(self.root, self.NAME,
                                       {'tarball': self.NAME + '.tar'})

    def test_a_grid_run_is_removed_by_cluster(self):
        self.rr.update(self.dir, state='submitted',
                       jobid='12345.0@jobsub01.fnal.gov')
        removed = []
        receipt, _ = self.rc.cancel(self.root, self.NAME,
                                    jobsub_rm=removed.append)
        self.assertEqual(removed, ['12345@jobsub01.fnal.gov'])
        self.assertEqual((receipt['state'], receipt['cancelled_from']),
                         ('cancelled', 'submitted'))
        self.assertIn('cancelled_utc', receipt)

    def test_a_local_run_gets_sigterm_on_its_own_host(self):
        summary = os.path.join(self.dir, 'summary.json')
        self.rr.update(self.dir, state='running', executor='local',
                       host='node.fnal.gov', pid=4242, summary=summary)
        killed = []
        receipt, _ = self.rc.cancel(
            self.root, self.NAME, host=lambda: 'node.fnal.gov',
            alive=lambda pid, path: True,
            kill=lambda pid, sig: killed.append((pid, sig)))
        self.assertEqual(killed, [(4242, signal.SIGTERM)])
        self.assertEqual(receipt['state'], 'cancelled')

    def test_refusals(self):
        summary = os.path.join(self.dir, 'summary.json')
        self.rr.update(self.dir, state='running', executor='local',
                       host='node.fnal.gov', pid=4242, summary=summary)
        for kwargs, needle in (
                ({'host': lambda: 'other.fnal.gov'}, 'other'),
                ({'host': lambda: 'node.fnal.gov',
                  'alive': lambda pid, path: False}, 'gone')):
            with self.subTest(needle=needle), \
                    self.assertRaises(self.rc.Refused) as cm:
                self.rc.cancel(self.root, self.NAME,
                               kill=lambda *a: self.fail('killed'), **kwargs)
            self.assertIn(needle, str(cm.exception))
        with open(summary, 'w') as fh:
            fh.write('{}')
        with self.assertRaises(self.rc.Refused) as cm:
            self.rc.cancel(self.root, self.NAME, host=lambda: 'node.fnal.gov',
                           alive=lambda pid, path: True,
                           kill=lambda *a: self.fail('killed'))
        self.assertIn('finished', str(cm.exception))

    def test_cancelling_twice_returns_the_same_receipt(self):
        self.rr.update(self.dir, state='submitted',
                       jobid='12345.0@jobsub01.fnal.gov')
        first, _ = self.rc.cancel(self.root, self.NAME,
                                  jobsub_rm=lambda j: None)
        again, _ = self.rc.cancel(self.root, self.NAME,
                                  jobsub_rm=lambda j: self.fail('twice'))
        self.assertEqual(first, again)

    def test_run_status_reports_cancelled_without_asking_condor(self):
        from prodtools_mcp.tools import runs
        self.rr.update(self.dir, state='submitted',
                       jobid='12345.0@jobsub01.fnal.gov')
        self.rc.cancel(self.root, self.NAME, jobsub_rm=lambda j: None)

        def condor(*args, **kwargs):
            raise AssertionError('a cancelled run never asks condor')
        out = runs.run_status(self.NAME, user='alice', runs_root=self.root,
                              clusters_fn=condor, codes_fn=condor)
        self.assertEqual(out['state'], 'cancelled')


class TestCancelRunTool(unittest.TestCase):
    def test_it_runs_runcancel_and_returns_the_receipt(self):
        from prodtools_mcp_write import runner, tools
        root = _mkdtemp()
        path = os.path.join(root, 'receipt.json')
        with open(path, 'w') as fh:
            json.dump({'name': 'cnf.a.b.c.0', 'state': 'cancelled',
                       'entry': {}}, fh)
        seen = {}

        def run_cli(argv, run_as, **kw):
            seen['argv'], seen['run_as'] = argv, run_as
            return {'rc': 0, 'stdout': f'RECEIPT {path}\n', 'stderr': ''}
        with patch.object(runner, 'run_cli', run_cli):
            receipt = tools.cancel_run('cnf.a.b.c.0', 'self')
        self.assertEqual(seen['argv'], ['bin/runcancel', '--name',
                                        'cnf.a.b.c.0'])
        self.assertEqual(receipt['state'], 'cancelled')
        self.assertNotIn('entry', receipt)
        self.assertIn('bin/runcancel', runner.ALLOWED_ENTRY_POINTS)

    def test_self_only(self):
        from prodtools_mcp_write import tools
        with self.assertRaises(ValueError):
            tools.cancel_run('cnf.a.b.c.0', 'mu2epro')

    def test_registered(self):
        from prodtools_mcp_write import server
        self.assertIn('cancel_run', server.TOOL_FUNCTIONS)
```

(`signal`, `json`, `os` and `patch` (`from unittest.mock import MagicMock, patch`) are already imported at the top of `test/test_unit.py`.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `env -i PATH=/usr/bin:/bin HOME=$HOME /usr/bin/python3 -m unittest test.test_unit.TestRunCancel test.test_unit.TestCancelRunTool -v`
Expected: FAIL (`No module named 'utils.runcancel'`).

- [ ] **Step 4: Implement**

`utils/runcancel.py`:

```python
#!/usr/bin/env python3
"""Cancel a one-shot run (`json2jobdef --once`, grid or `--local`) by name.

A grid run's cluster is removed with jobsub_rm; a local run's runlocal gets
SIGTERM, which ends every job it started (runlocal's stop handler). The
receipt's state becomes `cancelled`, with `cancelled_utc` and
`cancelled_from`, and run_status reports it as it stands. A grid run is not
checked against condor first: a cluster that had just finished still reads
cancelled. Prints `RECEIPT <path>`.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import run_receipt  # noqa: E402


class Refused(Exception):
    pass


def _cluster(jobid):
    """12345.0@schedd -> 12345@schedd: jobsub_rm on the whole cluster."""
    head, at, schedd = str(jobid).partition('@')
    if not at or not head or not schedd:
        raise Refused(f'receipt jobid {jobid!r} is not '
                      f'<cluster>.<proc>@<schedd>')
    return f"{head.split('.')[0]}@{schedd}"


def _jobsub_rm(jobid):
    r = subprocess.run(['jobsub_rm', '-G', 'mu2e', '--jobid', jobid],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused(f'jobsub_rm {jobid} failed (rc={r.returncode}): '
                      f'{(r.stderr or r.stdout).strip()}')


def _alive(pid, summary):
    """The run_status guard: /proc/<pid>/cmdline names this run's summary
    (pids are reused, so kill(pid, 0) would not do)."""
    try:
        with open(f'/proc/{int(pid)}/cmdline', 'rb') as fh:
            argv = fh.read().split(b'\0')
    except FileNotFoundError:
        return False
    return os.fsencode(summary) in argv


def cancel(root, name, *, host=socket.getfqdn, alive=_alive, kill=os.kill,
           jobsub_rm=_jobsub_rm):
    """(receipt, run_dir) after cancelling `name`. Raises Refused."""
    receipt = run_receipt.read(root, name)
    run_dir = os.path.join(root, name)
    state = receipt.get('state')
    if state == 'cancelled':
        return receipt, run_dir
    if receipt.get('executor') == 'local':
        if state != 'running':
            raise Refused(f'{name} is {state!r}; only a running local run '
                          f'can be cancelled')
        if os.path.exists(receipt['summary']):
            raise Refused(f"{name} has finished: {receipt['summary']} exists")
        if receipt.get('host') != host():
            raise Refused(f"{name} runs on {receipt.get('host')}, not this "
                          f"host; cancel it there")
        if not alive(receipt['pid'], receipt['summary']):
            raise Refused(f"{name}: its runlocal (pid {receipt['pid']}) is "
                          f"gone")
        kill(int(receipt['pid']), signal.SIGTERM)
    else:
        if state != 'submitted':
            raise Refused(f'{name} is {state!r}; only a submitted grid run '
                          f'can be cancelled')
        jobsub_rm(_cluster(receipt['jobid']))
    receipt = run_receipt.update(run_dir, state='cancelled',
                                 cancelled_from=state,
                                 cancelled_utc=run_receipt._now())
    return receipt, run_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--name', required=True, help='the run name, as '
                    'run_status takes it')
    args = ap.parse_args(argv)
    try:
        _receipt, run_dir = cancel(run_receipt.runs_root(), args.name)
    except (Refused, run_receipt.RunNotFound, ValueError) as exc:
        sys.exit(f'runcancel: {exc}')
    print(f'RECEIPT {os.path.join(run_dir, run_receipt.RECEIPT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

`bin/runcancel` (then `chmod +x bin/runcancel`):

```bash
#!/bin/bash

# Wrapper for utils/runcancel.py: cancel a json2jobdef --once run by name.
# Runs in the caller's environment (the write server's run_cli sets it up,
# so jobsub_rm is on PATH exactly as jobsub_submit was).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/../utils/runcancel.py" "$@"
```

`mcp/src/prodtools_mcp_write/runner.py`: add `'bin/runcancel',` to `ALLOWED_ENTRY_POINTS`.

`mcp/src/prodtools_mcp_write/tools.py`, after `run_local`:

```python
def cancel_run(name: str, run_as: str):
    """Cancel a submit_once or run_local run, by its run name.

    A grid run's cluster is removed (jobsub_rm); a local run's runlocal is
    sent SIGTERM on the host that runs it, which ends every job it
    started. The receipt's state becomes "cancelled" (with cancelled_utc
    and cancelled_from), and run_status reports it so. Cancelling a
    cancelled run returns the same receipt. A local run that has finished
    is refused. A grid run is not checked against condor first: a cluster
    that had just finished still reads "cancelled".

    run_as="self" only. Returns the receipt.
    """
    if run_as != 'self':
        raise ValueError(
            f"cancel_run is run_as=\"self\" only, got {run_as!r}: it "
            f"cancels your own one-shot runs.")
    result = runner.run_cli(['bin/runcancel', '--name', name], run_as)
    if result['rc'] != 0:
        raise RuntimeError(
            f"runcancel failed (rc={result['rc']}): {_both_streams(result)}")
    return _receipt_from(result, 'runcancel')
```

`mcp/src/prodtools_mcp_write/server.py`: add `'cancel_run': tools.cancel_run,` to `TOOL_FUNCTIONS`.

Docs: in `mcp/src/prodtools_mcp/server.py`'s instructions, where `run_status` states are described, add that a receipt cancelled with `cancel_run` reads `cancelled`; in `mcp/README.md` and `mcp/SUBMIT.md`, next to `run_local`, a short `cancel_run` paragraph with the same facts as its docstring.

- [ ] **Step 5: Run the prodtools suite**

Run: `env -i PATH=/usr/bin:/bin HOME=$HOME /usr/bin/python3 -m unittest test.test_unit`
Expected: OK (1553 + the new tests; any test pinning the write-tool list must now include `cancel_run`).

- [ ] **Step 6: Commit (prodtools repo)**

```bash
git add utils/runcancel.py bin/runcancel mcp/src/prodtools_mcp_write/runner.py \
  mcp/src/prodtools_mcp_write/tools.py mcp/src/prodtools_mcp_write/server.py \
  mcp/src/prodtools_mcp/server.py mcp/README.md mcp/SUBMIT.md test/test_unit.py
git commit -m "feat(mcp-write): cancel_run cancels a submit_once or run_local run"
```

---

## Acceptance (the controller, after the final review)

These run the real servers, so they are not subagent tasks. Set once:

```bash
cd <autoresearch worktree> && source ./activate.sh
export AUTORESEARCH_PRODTOOLS=/exp/mu2e/app/users/oksuzian/muse_050125/prodtools   # local main, with P3 merged
export AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies
export AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c1accept
```

1. **Dry run:** `tests/test_prodtools_entry.py::TestParity` passes (it already runs in the suite).
2. **Local:** `time PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.study_run --study prodtools_smoke --config c1local01 --campaign c1 --executor local` exits 0 and `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/leaderboard_prodtools_smoke.tsv` has one row with `ce_jobs_ok` 1. Record the wall time and the two prodtools servers' start time (from the kit trace and the log) in the wiki.
3. **Grid (needs the operator's go-ahead):** the same with `--config c1grid01 --executor grid`; then one throwaway grid run started by hand through the adapter and cancelled with `cancel_run`, reading `cancelled`.
