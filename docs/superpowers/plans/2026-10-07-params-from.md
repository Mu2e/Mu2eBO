# params_from Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A study step can take a kit param from an earlier step's metric
(`"params_from": {"stops_per_pot": "stops.stops_per_pot"}`). The engine
copies the number as it is and computes nothing.

**Architecture:** There is one new required step key in `core/study.py`.
It brings two accessors on `Step` (`upstream`, `sent_params`) and one
module function (`metrics_read`), and every reader of "what does a step
depend on, send, or have read from it" moves onto them:
- the scheduler,
- the launch check (`contract._needs`, `anakit.step_problems`),
- the dashboard.

`measure_basis` carries the key only when it is non-empty, so no
existing board changes.

**Tech Stack:** Python 3.12 (ana 2.8.0), stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-07-params-from-design.md`

**Where:**
- **Branch:** `params-from`, from `generic-study-phase-c1` at this
  plan's commit.
- **Worktree:** `/exp/mu2e/app/users/oksuzian/autoresearch-paramsfrom`.
- **Every command below runs from there**, after
  `source ./activate.sh`.

**Test commands:**
- **One module:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.<module> -q`
- **The suite:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
  This takes about 10 minutes. The baseline is 985 tests, OK
  (skipped=5).

## Global Constraints

- **Every study key is required and unknown keys are refused**
  (ADR-0002). `params_from` is `{}` when unused.
- **No silent fallback.** A missing or non-finite metric fails the step
  with a message. There is no default value.
- **Old boards keep their measurement.** Every `mode_specs/*.json`
  keeps its `measure_basis_sha` (the values are pinned in Task 1).
- **No kit `VERSION` bump.** No analysis number changes.
- **`mode_specs/archive/*.json` is not touched.** Those files are not
  loaded.
- **Error text names the field path,** in the existing
  `{where}[evaluate.<step>.params_from...]` style.

## Review Focus

1. **A producer step that fails:** the consumer must never submit, and
   `broken.txt` names the producer. Task 2,
   `test_a_failed_producer_never_submits_the_consumer`.
2. **The same step in a step's `files_from` and `params_from`:** the
   consumer waits once, takes its inputs only from `files_from`, and
   gets the value. Task 2, `test_one_step_in_files_from_and_params_from`.
3. **A hand-edited or old `<step>_results.json` holding a string or a
   bool metric:** this is refused like a NaN. Task 2,
   `test_a_non_number_metric_fails_the_step`.
4. **A `params_from` key that is a kit-reserved name** (`entry`, or a
   beamkit setting): this is refused at load, as for `params`. Task 1,
   `test_reserved_names_are_refused_in_params_from`.
5. **A producer read only through `params_from`:** the dashboard must
   not draw it as a dead end into the result. Task 4,
   `test_a_params_from_source_is_consumed`.

---

### Task 1: The key at load, the accessors, measure basis, migrated files

**Files:**
- **Modify:** `core/study.py` (`_STEP`, `Step`, `_steps`,
  `_check_acyclic`, `_check_steps_used`, `_measure_basis`,
  `load_study_file`).
- **Modify:** `core/kit_registry.py:283-302`
  (`check_deck_params_shadowing`).
- **Migrate:** `mode_specs/*.json` (9 files) and
  `tests/fixtures/engine_studies/*.json` plus
  `tests/fixtures/studies/demo.json` (5 files).
- **Migrate (in-code step dicts):**
  - `tests/engine_fixtures.py:28`
  - `tests/test_score.py:112`
  - `tests/test_beamkit_kit.py:49`
  - `tests/test_c2b_studies.py:25,31`
- **Migrate (positional `Step(...)`):**
  - `tests/test_prodtools_adapter.py:717-719`
  - the `step()` helper in `tests/test_scheduler.py:24`, which gains a
    `params_from=None` keyword.
- **Test:** `tests/test_study.py`, new class `TestParamsFrom`.

**Interfaces:**
- **Produces:** the `Step` field order becomes `step, kit, entry, files,
  files_from, params, params_from: Dict[str, str], fixed`.
- **Produces:** `Step.upstream -> Tuple[str, ...]` (property). It holds
  `files_from` in order, then each `params_from` source step (the part
  before the dot), taken in sorted param order. No step appears twice.
- **Produces:** `Step.sent_params -> frozenset` (property), equal to
  `set(params) | set(params_from) | set(fixed)`.
- **Produces:** `metrics_read(study, step_name: str) -> frozenset` (a
  module function in `core/study.py`). It returns the metric keys read
  from `step_name` by `study.objectives`, `study.extra_metrics` and
  every step's `params_from`. It reads only those three attributes, so
  a namespace fake works.

- [ ] **Step 1: Migrate the files first, so that the key is present when
  it becomes required.**
  - **One-line step files** (the `custom` format: the `_ax` studies,
    `branin.json`, `demo.json`): run
    `sed -i 's/"params": \({[^}]*}\), "fixed"/"params": \1, "params_from": {}, "fixed"/'`.
    A preflight line has `"params": {}, "files"`, so it is untouched.
  - **The indent=1 files** (`ce_chain`, `ptg4bl`, `foilspfbpz_local`,
    `foilspf_nominal`, `prodtools_smoke`): load each with
    `object_pairs_hook=dict` and rebuild each `evaluate[]` step with
    `params_from: {}` inserted after `params`. Then write it back with
    `json.dumps(doc, indent=1) + "\n"`. Check that `git diff --stat`
    shows only these files.
  - **The Python test dicts and positional `Step(...)` calls** listed
    above: add `params_from` the same way.
  - Then grep:
    `grep -L params_from mode_specs/*.json tests/fixtures/engine_studies/*.json tests/fixtures/studies/demo.json`
    must print nothing.

- [ ] **Step 2: Write the failing tests** in `tests/test_study.py`
  (`class TestParamsFrom(_Tmp)`, built on `_doc()` and `_step()`):

```python
PINNED = {  # measure_basis_sha at 8cea00a, before this change
    "ce_chain": "79b9b3e212d94d04f3aece224d3968cb33eae4e6f52c6e23c937281cd058e771",
    "foilsflash_ax": "405cc0e850b9dc4ed28ee96bea8187c94185bce654230acc5016de73a1763d6f",
    "foilspf2k_ax": "2060c97e7de0a4a18f6364e0a721e6abe45e4bc98a089b4ffedcea75385e12a4",
    "foilspf_ax": "e96f0491abe95519352962dc51616fca0598eabf5b5cfba122734179da3b250e",
    "foilspfbp_ax": "54467d3e05b4742da1fbd3a7809cf50f770fdc18219c40773ada487355cb0547",
    "foilspfbpx_ax": "d6ee2d286f6e8e26a6417dfb9530789beefd8f385179036f60c4385d1e6d8a4d",
    "foilspfbpz_ax": "c4aafee1c30ba5121ab727bcab4513786b6d076c10f976d1b786daf95e218a80",
    "foilspfbw_ax": "01bcbd62be9a8f4d8b825e85267a3e7b45a0746b2784f1c48c32aeacba962191",
    "ptg4bl": "b52fce7c37525597cae53862efe0f272af28f766c6deaefa22b71f08a6861689",
}
# test_existing_studies_keep_their_measure_basis_sha: every mode_specs/*.json
#   loads and its measure_basis_sha == PINNED[name]; set(names) == set(PINNED)
# test_params_from_is_required: del every step's params_from ->
#   assertRejects(doc, "missing required field(s) ['params_from']")
# test_params_from_must_be_an_object: = ["a.b"] -> "params_from", "must be an object"
# test_a_bad_source_form: {"x": "sob"} -> "params_from.x", "must be 'step.key'"
# test_an_unknown_source_step: {"x": "nope.v"} -> "params_from.x", "'nope'"
# test_a_self_reference: sob takes {"x": "sob.v"} -> "params_from.x", "its own result"
# test_a_clash_with_params_fixed_or_settings: subTests "fixed" (key "analysis"),
#   kit setting (demo's kits.anakit has "work_area" -> key "work_area"), and params
#   (sob params {"k": "<a knob>"} + params_from {"k": ...}) -> "['<name>']", "more than once"
# test_a_cycle_through_params_from: mubeam params_from {"x": "mustops_ce.v"}
#   (mustops_ce files_from mubeam) -> "cycle"
# test_a_step_read_only_by_params_from_is_used: add step "stops" (anakit,
#   files_from ["mubeam"], fixed {"analysis": "ce_sensitivity"}); sob takes
#   {"x": "stops.v"}; nothing else reads stops -> loads (no "nothing uses")
# test_reserved_names_are_refused_in_params_from: prodtools step {"entry": "sob.v"}
#   -> "'entry' is reserved"; beamkit reserved param -> "a beamkit setting"
# test_upstream_and_sent_params: Step with files_from ("a",) and params_from
#   {"z": "b.m", "y": "a.n"} -> upstream == ("a", "b"); sent_params covers all three keys
# test_metrics_read: objective "sob.s_over_sqrt_b" + flash step params_from
#   {"x": "sob.ce_abs_eff"} -> metrics_read(study, "sob") == {"s_over_sqrt_b", "ce_abs_eff"}
# test_params_from_changes_measure_sha: same doc with/without a params_from
#   -> different measure_basis_sha; with params_from {} on every step, no entry
#   of measure_basis["steps"] has a "params_from" key
```

  In `test_study.py`'s ptg4bl/beamkit cases, use the existing
  `kit_registry.KITS["beamkit"].reserved_params` for the name.

- [ ] **Step 3: Run and watch it fail.**
  `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study -q`.
  Expected: FAIL (unknown key `params_from` in every migrated file, and
  the new tests error).

- [ ] **Step 4: Implement it in `core/study.py`.**
  - **Schema:** add `"params_from"` to `_STEP` after `"params"`, and the
    field to `Step` with the two properties.
  - **Parse:** in `_steps`, parse the key with `_dict`; each value is a
    string. After the loop, check each source with
    `_metric(v, step_names, f"{where}[evaluate.{s.step}.params_from.{k}]")`
    and refuse a self-source with "a step cannot take a param from its
    own result".
  - **Reserved names:** apply the `entry` and `decl.reserved_params`
    checks to `params_from` keys as they apply to `params`.
  - **Clash check:** add `_check_mapped_params(steps, kits_raw, where)`,
    called from `load_study_file` after `_kits_and_preflight`. The
    mapped names are `params | params_from`. They must be disjoint from
    each other and from `fixed | kits[step.kit]`. Refuse with
    `{where}[evaluate.<step>]: param(s) [...] are set more than once
    (params, params_from, fixed, kits.<kit>); a mapped param may not
    share a name with another param of the step`.
  - **Graph checks:** `_check_acyclic` uses `s.upstream`, and its
    message says "files_from/params_from form a cycle".
    `_check_steps_used` adds the `params_from` source steps to `used`.
  - **Measure basis:** `_measure_basis` adds `"params_from"` to a step
    entry only when it is non-empty.
  - **beamkit:** `kit_registry.check_deck_params_shadowing` checks
    `set(step.params) | set(step.params_from)`.

- [ ] **Step 5: Run and watch it pass.** Run `tests.test_study`, then
  the whole suite. Expected: OK. The suite must stay green here,
  because every fixture is migrated.

- [ ] **Step 6: Commit.** Message: "study: params_from, a step param
  from an earlier step's metric (load rules, measure basis)".

### Task 2: Run time — wait for the source, pass the value

**Files:**
- **Modify:** `core/scheduler.py` (`run_steps` readiness and upstream
  dict, `step_params`, `_run_one`).
- **Test:** `tests/test_scheduler.py`.

**Interfaces:**
- **Consumes:** `Step.upstream` and `Step.params_from` (Task 1).
- **Produces:** `params_from_values(step, upstream: Dict[str, dict]) ->
  Dict[str, float]`. It raises `ValueError` with these exact formats:
  - `params_from {param}={source!r}: step {up!r} returned no metric {key!r} (it returned {sorted(metrics)})`
  - `params_from {param}={source!r}: step {up!r} returned {value!r}, not a finite number`
    (for a bool, a non-number, NaN or ±inf).
- **Changes:** `step_params(study, step, env, accepts_lists, upstream)`.
  The `params_from` values join the mapped params before
  `merge_params`.

- [ ] **Step 1: Write the failing tests.**
  - **Helpers:** `FakeKit` gains `metrics=None`, a `{step: {name:
    value}}` map. A step not in the map keeps `{"v": 1.0}`. The
    existing `TestParams` calls pass `{}` as `upstream`.
  - **New tests:**

```python
# test_a_params_from_value_reaches_the_consumer: a returns {"rate": 0.25};
#   b params_from {"r": "a.rate"} -> b's submitted params["r"] == 0.25 and
#   b_results.json["params"]["r"] == 0.25
# test_the_consumer_waits_for_the_producer: a scripted ["working"]*3+["completed"],
#   b only params_from a -> events.index(("submit","b")) > events.index(("done","a"))
# test_a_missing_metric_fails_the_step: a returns {"v": 1.0}, b {"r": "a.rate"} ->
#   not out["b"].ok; "params_from r='a.rate': step 'a' returned no metric 'rate' (it returned ['v'])"
#   in out["b"].message; broken.txt names step b; b never submitted
# test_a_non_finite_metric_fails_the_step: subTests nan, inf -> "not a finite number"
# test_a_non_number_metric_fails_the_step: a adopted from a hand-written
#   state/a_results.json with metrics {"rate": "0.5"} and then {"rate": True}
#   -> "not a finite number"
# test_an_adopted_producer_passes_its_recorded_value: state/a_results.json
#   metrics {"rate": 0.125} -> a not submitted, b gets 0.125
# test_a_failed_producer_never_submits_the_consumer: a scripted ["failed"],
#   b {"r": "a.v"} -> b never submitted, broken.txt names a
# test_one_step_in_files_from_and_params_from: b files_from ["a"],
#   params_from {"r": "a.v"} -> b submitted once, inputs == a's file list, r == 1.0
# TestParams.test_a_params_from_value_joins_the_mapped_params:
#   step_params(st_, step("b", params={"p": "x"}, params_from={"r": "a.rate"}),
#   {"x": 1.5}, False, {"a": {"metrics": {"rate": 2.0}}}) == {"p": 1.5, "r": 2.0}
```

- [ ] **Step 2: Run and watch it fail.** `tests.test_scheduler`.
  Expected: FAIL (`step_params` takes 4 positional arguments, and
  params never carry `r`).

- [ ] **Step 3: Implement it.**
  - **Readiness:** a step is ready when every name in `s.upstream` is
    `ok`, and `upstream = {d: outcomes[d].record for d in s.upstream}`.
  - **Inputs:** `inputs` stays built from `step.files_from` only.
  - **The value:** `params_from_values` reads
    `upstream[up]["metrics"][key]` and accepts it only when it is an
    `int`/`float`, not a `bool`, and `math.isfinite`.
  - **Where it runs:** it is called inside `step_params`, so its
    `ValueError` lands in `_run_one`'s existing `(KeyError, ValueError)`
    catch. That makes it a failed StepOutcome with `broken.txt`.

- [ ] **Step 4: Run and watch it pass.** `tests.test_scheduler`, then
  `tests.test_study_engine` and `tests.test_run`. Expected: OK.

- [ ] **Step 5: Commit.** Message: "scheduler: a step waits for its
  params_from sources and takes their metric".

### Task 3: Launch check — one answer for "read from" and "sent by" a step

**Files:**
- **Modify:** `core/contract.py:514-535` (`_needs`).
- **Modify:** `core/adapters/anakit.py:345-425` (`step_problems`).
- **Test:** `tests/test_contract.py` (`TestLaunchProblems`) and
  `tests/test_anakit_kit.py` (`TestStepProblems`).

**Interfaces:**
- **Consumes:** `Step.sent_params` and `metrics_read(study,
  step_name)` (Task 1).
- **Changes in `_needs`:** `params |= s.sent_params` for each of the
  kit's steps. `metrics` is the union of `metrics_read(study, s.step)`
  over the kit's steps. `contract` imports `metrics_read` from `study`.
  There is no import cycle: `study` does not import `contract`.
- **Changes in `anakit.step_problems`:**
  `sent = set(step.sent_params) - set(OWN_PARAMS)`, and
  `wanted = sorted(metrics_read(study, step.step))`.

- [ ] **Step 1: Write the failing tests.**
  - **Helper:** `TestStepProblems.study()` builds a real
    `Step("sob", "anakit", None, (), (), {}, params_from or {}, fixed)`
    and takes `params_from=None` and `others=()` (extra steps for the
    namespace's `steps`).
  - **New tests:**

```python
# test_contract.TestLaunchProblems (toy_doc + second step "toy2", params {"x1": "x1"},
#   objectives read toy2):
#   test_a_params_from_study_passes: toy2 params_from {"x2": "toy.branin"} -> []
#   test_a_params_from_metric_the_producer_does_not_return: {"x2": "toy.nope"}
#     -> a problem containing "does not return metric(s) ['nope']"
#   test_a_params_from_param_the_consumer_does_not_take: {"zz": "toy.branin"}
#     -> a problem containing "does not accept param(s)" and "zz"
# test_anakit_kit.TestStepProblems:
#   test_a_params_from_param_satisfies_a_required_parameter:
#     fixed {"analysis": "approx_ce_sensitivity"}, params_from {"sig_eff": "stops.rate"}
#     -> no problem containing "needs"
#   test_a_params_from_param_the_analysis_does_not_take:
#     GOOD + params_from {"bogus": "stops.rate"} -> "does not take ['bogus']"
#   test_a_metric_another_step_reads_must_be_returned: sob = GOOD; other step
#     "c" params_from {"x": "sob.nope"} -> step_problems(study, sob) has
#     "does not return ['nope']"
```

- [ ] **Step 2: Run and watch it fail.** `tests.test_contract` and
  `tests.test_anakit_kit`. Expected: FAIL (the `nope` metric and
  `zz`/`bogus` are not reported, and `sig_eff` is reported as needed).

- [ ] **Step 3: Implement the two changes** named in Interfaces.

- [ ] **Step 4: Run and watch it pass.** The two modules, then
  `tests.test_check_study`. Expected: OK.

- [ ] **Step 5: Commit.** Message: "launch check: params_from params
  and metrics count as sent and read".

### Task 4: Dashboard edge, docs, wiki

**Files:**
- **Modify:** `service/dashboard.py`. The payload's step key
  `"files_from"` becomes `"upstream"`, holding `list(s.upstream)`, at
  lines 103, 142, 176 and 200. The page (`dashboard.html`) does not
  read it.
- **Modify:** `tests/test_dashboard.py`: the `camp()` helper's key, and
  the expected payload dicts at lines 138-140.
- **Modify:** `mode_specs/README.md`, the `study_guide` page. Add
  `params_from` to the step keys and a short section "Numbers between
  steps": the spec's example, rules 2-6 in one line each, and "the
  engine passes a metric as it is; a formula belongs in the kit".
- **Modify the wiki:**
  - `wiki/drivers/contract-engine.md`: a key fact, and bump the
    timestamp;
  - `wiki/index.md`: the contract-engine one-liner gains
    "params_from (2026-10-07)";
  - `wiki/log.md`: a bullet under `## 2026-10-07` at the top.

- [ ] **Step 1: Write the failing test.**
  `test_a_params_from_source_is_consumed` (in `TestData`) uses a
  `dag_doc`-style study where step `b` has `files_from: []` and
  `params_from: {"x2": "a.branin"}`. The objectives read `b`.
  - The payload step `b` has `"upstream": ["a"]`.
  - `layout()` edges include `["p1/a", "p1/b"]`.
  - `layout()` edges do not include `["p1/a", "p1/result"]`.

- [ ] **Step 2: Run and watch it fail.** `tests.test_dashboard`.
  Expected: FAIL (KeyError `upstream`, or no edge).

- [ ] **Step 3: Implement the rename and write the docs.**

- [ ] **Step 4: Run and watch it pass.** `tests.test_dashboard`, then
  the whole suite. Expected: OK, with 985 tests plus the new ones and
  skipped=5.

- [ ] **Step 5: Commit.** Message: "dashboard draws params_from edges;
  README and wiki document params_from".
