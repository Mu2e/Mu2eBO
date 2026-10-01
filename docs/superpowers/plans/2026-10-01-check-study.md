# check_study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m graph.check_study <path-or-name>` reports whether a study file loads, finds its artifacts, passes the launch check and passes its geometry pre-check at the center point, without submitting anything or writing a board row.

**Architecture:** A new entry point `graph/check_study.py` runs four checks through the engine's own code: `load_study_file`, `paths.artifact`, `contract.launch_problems` and `build_study_graph(..., through="preflight")`. A new helper `study.study_files` gives the loader's directory rules one home. The report is text or JSON; exit 0 if every check passes, 1 if any fails, 2 for a bad command line.

**Tech Stack:** Python 3.12 (ana 2.8.0), LangGraph `StateGraph`, unittest, toykit (`tests/toykit.py`) as the test kit.

**Spec:** `docs/superpowers/specs/2026-10-01-check-study-design.md`

## Global Constraints

- **Suite:** `cd /exp/mu2e/app/users/oksuzian/autoresearch-checkstudy && PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`. The baseline is 773 tests OK (skipped=3).
- **The seven `_ax` `measure_basis_sha` values must not change:**
  - foilsflash_ax 405cc0e8
  - foilspf2k_ax 2060c97e
  - foilspf_ax e96f0491
  - foilspfbp_ax 54467d3e
  - foilspfbpx_ax d6ee2d28
  - foilspfbpz_ax c4aafee1
  - foilspfbw_ax 01bcbd62

  ce_chain is 79b9b3e2.
- **Never submit, never append:** check_study never calls a kit's `submit`, never appends to a board, and writes nowhere outside `<GRID_DATA_ROOT>/check_<study>/` except the shared `_code/` unpack and the kit trace.
- **Stdout:** with `--json`, stdout holds exactly one JSON object; every log line goes to stderr.
- **Process rules:**
  - No silent fallbacks.
  - Nothing is pushed.
  - Scratch goes under `/exp/mu2e/data/users/oksuzian/`, never /tmp.
  - Commit messages end with:
    ```
    Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
    ```

## Review Focus

1. **A draft in `mode_specs/` that fails to load.** check_study must report `load` failed, never crash at import. So no module-level `import modes` or `import run` in `graph/check_study.py`: `graph/run.py` imports `modes`, which loads every study. Test: Task 3 `test_a_broken_draft_on_the_study_path_is_a_failed_load`.
2. **Another study file on the path that fails to load.** That breaks every launch, since the runners load all studies. Report it as a load problem naming that file. Test: Task 2 `test_another_broken_study_is_a_load_problem`.
3. **Log lines must not land in stdout under `--json`.** `build_study_graph`'s default `log=print` would put `[run]` lines there. Test: every Task 3 test parses stdout with `json.loads`.
4. **Kit servers must close on every exit path.** That includes a failed geometry and an `--x` of the wrong length. Test: Task 3 `test_a_wrong_length_x_is_a_failed_geometry`, which also checks the exit code is 1 and not a traceback.
5. **A second run must not reuse the first run's verdict or files.** Test: Task 3 `test_the_marker_dir_is_emptied_and_a_bare_dir_is_refused`.

---

### Task 1: `through="preflight"` and `study.study_files`

**Files:**
- Modify: `graph/study_graph.py` (`build_study_graph`, lines 84-245)
- Modify: `core/study.py` (`load_study_dirs`, ~line 720)
- Test: `tests/test_check_study.py` (new; class `TestThrough`, `TestStudyFiles`)

**Interfaces:**
- Produces:
  - `build_study_graph(study, *, config, campaign, context, kits, state_dir, board, log=print, executor="grid", through: str = "score") -> StateGraph`. `through="preflight"` builds derive → render → preflight → END. Any value other than `"score"` or `"preflight"` raises `ValueError` naming the value.
  - `study.study_files(primary: Path, extra: Optional[str]) -> List[Path]`: the `*.json` files `load_study_dirs` loads, in its order, with its rules for `extra` (absolute paths only, each a directory, `ValueError` otherwise; a missing `primary` is skipped). `load_study_dirs` is rewritten on top of it, with no behaviour change.

- [ ] **Step 1: Write the failing tests** in `tests/test_check_study.py`:
  - `TestThrough.test_through_preflight_stops_before_the_steps`:
    - set up a toy study (`tests.engine_fixtures.toy_doc`, loaded with `study.load_study_file`), with `"preflight": {"kit": "toykit", "files": [], "params": {}}`;
    - use a fake `kits` whose `get("toykit")` returns an object with `accepts_lists = False` and `check(...)` returning `(True, "ok")`. Model it on `tests/test_preflight_reuse.py`'s `CountingKit`/`Kits`;
    - `build_study_graph(..., through="preflight", board=None, context={}).compile().invoke({"config_name": "c1", "x_point": [2.5, 7.5]})` returns a state with `broken` False;
    - `point.json`, `derived.json` and `preflight_verdict.json` exist in `state_dir`;
    - no `toy_results.json` or `toy_cluster.txt` was written, and the fake kit's `submit` (make it raise `AssertionError`) was never called.
  - `TestThrough.test_an_unknown_through_is_refused`: `through="run_steps"` raises `ValueError` whose message contains `'run_steps'`.
  - `TestStudyFiles.test_it_lists_what_load_study_dirs_loads`:
    - two dirs, each with one study file (`write_study`);
    - `study_files(a, str(b))` equals `[a/x.json, b/y.json]`;
    - `sorted(load_study_dirs(a, str(b)))` equals `["x", "y"]`;
    - a relative `extra` entry raises `ValueError`.

- [ ] **Step 2: Run them to see them fail.** Run: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest tests.test_check_study -v`. Expected: errors for the unknown keyword `through` and for `study_files` not existing.

- [ ] **Step 3: Implement.** In `build_study_graph`:
  - validate `through` first;
  - for `"preflight"`, add only the first three nodes and end with `g.add_edge("preflight", END)`.

  In `core/study.py`, extract `study_files` from `load_study_dirs`'s directory loop and have `load_study_dirs` iterate `study_files(...)`.

- [ ] **Step 4: Run** the new tests, then `tests.test_study tests.test_study_engine tests.test_run tests.test_preflight_reuse tests.test_modes`. Expected: all OK.

- [ ] **Step 5: Commit**: `git commit -m "study_graph: a through option that stops after preflight; study.study_files"`.

---

### Task 2: the static checks (`load`, `artifacts`) and the report

**Files:**
- Create: `graph/check_study.py`
- Test: `tests/test_check_study.py` (classes `TestTarget`, `TestLoad`, `TestArtifacts`, `TestCenter`, `TestReport`)

**Interfaces:**
- Consumes: `study.study_files`, `study.load_study_file`, `study.expand_artifact`, `study._ARTIFACT_TOKEN` (`"${ARTIFACT}/"`).
- Produces (all in `graph/check_study.py`; module-level imports limited to the stdlib plus `core/` modules that do not import `modes`):
  - `@dataclass class Check: name: str; status: str; problems: List[str] = field(default_factory=list); note: str = ""`.
    - `status` is one of `"passed"`, `"failed"`, `"skipped"`.
    - `as_dict()` returns `{"name", "status", "problems", "note"}`.
  - `resolve_target(arg: str) -> Path`:
    - an argument that ends in `.json` or contains `/` is a path, which must be an existing file;
    - otherwise it is a study name, found as the file in `study_files(MODES_DIR, $AUTORESEARCH_STUDY_PATH)` whose stem equals it;
    - `ValueError` (with a message) when neither works;
    - `MODES_DIR` is `REPO_ROOT / "mode_specs"`, the directory `core/modes.py` uses.
  - `check_load(path: Path) -> Tuple[Check, Optional[Study]]`. Its problems are:
    - the loader's `ValueError` / JSON error, as text;
    - `study {name!r} is in {stem}.json; the name must equal the file name`;
    - a board basename used by a study of another name: `leaderboard basename {b!r} is already used by {other_path}`;
    - for every other study file in `study_files(...)`, skipping `path` itself (compared resolved), that fails to load: `{other_path} fails to load ({error}); every launch loads all studies`.

    Returns `(Check("load", "passed"), study)` or `(Check("load", "failed", problems), None)`.
  - `check_artifacts(path: Path) -> Check`:
    - walk the raw JSON at any depth;
    - for each string starting with `_ARTIFACT_TOKEN`, expand it with `expand_artifact(value, location)`;
    - add one problem per expanded path that does not exist: `{location}: {value} -> {expanded} does not exist`;
    - `location` is dotted keys with `[i]` for list indexes, e.g. `kits.prodtools.code_tarball`, `evaluate[2].fixed.dio_table`;
    - `"passed"` with note `"no ${ARTIFACT} paths"` when there are none.
  - `center_point(study) -> List[float]`: per knob, `(min + max) // 2` for `int` and `(min + max) / 2` for `real`, as floats; `[]` for no knobs.
  - `report(study_name: str, path: str, point: Optional[dict], checks: List[Check]) -> dict`: the spec's JSON object; `ok` is true iff every check is `"passed"`.
  - `render_text(rep: dict) -> str`: one line per check, `"{name:9} {STATUS}  {note}"`, followed by its problems indented as `"    - {problem}"`, and a last line `"OK"` or `"FAILED"`.

- [ ] **Step 1: Write the failing tests** (write study files into a temp dir with `tests.engine_fixtures.write_study`; set `AUTORESEARCH_STUDY_PATH` to it with `mock.patch.dict(os.environ, ...)`):
  - `TestTarget`:
    - a `.json` path that exists resolves to itself;
    - a missing path raises `ValueError`;
    - the name `"toystudy"` resolves to `<studydir>/toystudy.json`;
    - an unknown name raises `ValueError` containing that name.
  - `TestLoad.test_a_good_study_passes`: status `"passed"`, study name `"toystudy"`.
  - `TestLoad.test_a_load_error_fails`: a doc with `"objectives": []` fails, and the problem contains `"objectives"`.
  - `TestLoad.test_name_must_equal_the_file_stem`: `toy_doc(name="alpha")` written as `beta.json` fails, and the problem contains `"'alpha'"` and `"beta.json"`.
  - `TestLoad.test_a_board_used_by_another_study_fails`:
    - the target `t1` and a second study `t2` whose `leaderboard.file` equals t1's;
    - fails, and the problem names `t2.json`.
  - `TestLoad.test_the_same_study_on_the_path_is_this_study`: checking `<studydir>/toystudy.json` itself passes.
  - `TestLoad.test_another_broken_study_is_a_load_problem`: a second file `bad.json` holding `{}` makes the target's load fail, and the problem contains `"bad.json"` and `"every launch loads all studies"`.
  - `TestArtifacts`:
    - a doc whose `kits.toykit.function` is `"${ARTIFACT}/no/such/file.tbl"` fails with exactly one problem, which starts with `"kits.toykit.function: "` (a string study key, so the loader accepts it; toykit reads it only at submit);
    - the same doc with a file created at that relative path under a temp dir, with `mock.patch.object(paths, "ARTIFACT_ROOT", tmp)` and `mock.patch.object(paths, "BACKING", None)`, passes;
    - a doc with none passes with note `"no ${ARTIFACT} paths"`.
  - `TestCenter`:
    - toy knobs `[-5, 10]` and `[0, 15]` give `[2.5, 7.5]`;
    - an `int` knob `[1, 4]` gives `2.0`;
    - zero knobs give `[]`.
  - `TestReport`:
    - `ok` is false when any check is `"skipped"` or `"failed"`;
    - `report(...)` round-trips through `json.dumps`;
    - `render_text` ends with `"FAILED"` for a failed check and lists its problem.

- [ ] **Step 2: Run them to see them fail.** Run: `... -m unittest tests.test_check_study -v`. Expected: `ModuleNotFoundError: check_study` errors for the new classes, and the Task 1 classes passing.

- [ ] **Step 3: Implement** the six functions and `Check` in `graph/check_study.py`. Insert `graph/` and `core/` into `sys.path` as `graph/run.py` does. Do not import `modes`, `run` or `boards`/`contract` at module level.

- [ ] **Step 4: Run** `tests.test_check_study`. Expected: all OK.

- [ ] **Step 5: Commit**: `git commit -m "check_study: the load and artifacts checks, the center point and the report"`.

---

### Task 3: the `launch` and `geometry` checks and `main`

**Files:**
- Modify: `graph/check_study.py`
- Test: `tests/test_check_study.py` (class `TestMain`, subprocess style as in `tests/test_zero_knob.py`: `engine_env(data, studies)` and `python -m graph.check_study`)

**Interfaces:**
- Consumes:
  - Task 2's functions;
  - `contract.KitSet(campaign, executor=, parallel=)` and `contract.launch_problems(study, kits, *, executor, parallel, config_names, board)`;
  - `boards.board_for(study)`;
  - `run.local_env_refusal()`, imported inside the function: `run` imports `modes`;
  - `study_graph.check_x` and `build_study_graph(..., through="preflight")`;
  - `paths.GRID_DATA_ROOT`.
- Produces:
  - `check_launch(study, kits, *, executor: str, parallel, config: str) -> Check`. Problems are `local_env_refusal()`'s message (if any) plus `launch_problems(...)`, with `board=board_for(study)` and `config_names=[config]`.
  - `prepare_scratch(config: str) -> Optional[str]`, for `d = GRID_DATA_ROOT / config`:
    - if `d` exists without `d/.check_study`, return the problem `"{d} exists but was not made by check_study (no .check_study marker); left untouched"`;
    - otherwise remove `d` if present (`shutil.rmtree` on that one named path), recreate it, write the marker, and return None.
  - `check_geometry(study, kits, *, x: List[float], config: str, executor: str) -> Check`:
    - `check_x` errors are a failed check carrying the message;
    - else `prepare_scratch` (a problem fails the check);
    - else invoke the `through="preflight"` graph with `state_dir = GRID_DATA_ROOT/config/"state"`, `campaign="check"`, `context={}`, `board=None`, and `log` writing to stderr;
    - `broken` gives failed with the state's `reason`;
    - otherwise passed, with note:
      - the preflight verdict's message when `study.preflight` is set; `"pre-check passed"` if the message is empty;
      - `"rendered, not pre-checked"` when the study has a `geom` but no preflight;
      - `"no geometry"` when it has neither.
  - `main(argv=None) -> int`:
    - **Arguments:** `target`, `--x`, `--executor` (choices `contract.EXECUTORS`, default `"grid"`) and `--parallel` (int).
    - **`--json`:** prints `report(...)` as one JSON object.
    - **Resolving the target:** `resolve_target`; a `ValueError` prints to stderr and returns 2. A non-numeric `--x` value also prints to stderr and returns 2.
    - **Config name:** `config = f"check_{study.name}"`.
    - **Order:**
      1. load;
      2. artifacts (skipped if load failed);
      3. launch (skipped if load failed);
      4. geometry (skipped if launch failed or was skipped).

      A skip's note says which check it waited on, e.g. `"skipped: launch failed"`.
    - **Kits:** a single `KitSet("check", executor=..., parallel=...)` is shared by launch and geometry, and closed in `finally`.
    - **Point:** `point` is `{knob: value}` from `--x` (split on commas, as floats) or `center_point`; null when load failed.
    - **Return:** 0 if `rep["ok"]`, else 1.
    - **Text mode:** prints `render_text`.
  - Module docstring: usage and exit codes, as in `graph/run.py`.

- [ ] **Step 1: Write the failing tests.** Run `run_module("graph.check_study", ...)` with `--json` and check `json.loads(r.stdout)` in each. Use `--executor local --parallel 1` for toykit studies, so no Kerberos is needed. Here `toy_pre` means `toy_doc` with `"preflight": {"kit": "toykit", "files": [], "params": {}}`, and `checks` is `{c["name"]: c for c in out["checks"]}`.
  - `test_a_good_study_passes_every_check`: `toy_pre` gives exit 0, `ok` true, all four `"passed"`, and `point == {"x1": 2.5, "x2": 7.5}`. Afterwards, no file `autoresearch_leaderboards/leaderboard_toystudy.tsv` exists under the data root, and nothing named `toy_results.json`/`toy_cluster.txt` exists under `autoresearch_grid/check_toystudy/`.
  - `test_a_failing_precheck_is_a_failed_geometry`: `toy_pre` with `kits.toykit.function = "reject"` gives exit 1; geometry `"failed"` with a problem containing `"fails the check"`; launch `"passed"`.
  - `test_a_load_failure_skips_the_rest`: exit 1, `point` null, and artifacts, launch and geometry all `"skipped"`.
  - `test_a_broken_draft_on_the_study_path_is_a_failed_load`: a broken file `bad.json` on the study path, checked by path, gives exit 1, load `"failed"`, and stderr contains no `Traceback`.
  - `test_a_board_of_another_measure_sha_fails_launch_and_skips_geometry`:
    - write `<data>/autoresearch_leaderboards/leaderboard_toystudy.tsv` directly: the header `Leaderboard.for_study(st.load_study_file(path), path=board_path).header()`, then one row with `"1"` in every column except `config` `"old1"` and `measure_sha` `"b"*64`;
    - expect exit 1, launch `"failed"` with a problem containing `"bbbbbbbbbbbb"`, and geometry `"skipped"`.
  - `test_x_overrides_the_center`: `--x=1,2` gives `point == {"x1": 1.0, "x2": 2.0}` and exit 0.
  - `test_a_wrong_length_x_is_a_failed_geometry`: `--x=1` gives exit 1, geometry `"failed"` with a problem containing `"2 knobs"`, and no `Traceback` in stderr.
  - `test_the_marker_dir_is_emptied_and_a_bare_dir_is_refused`:
    - run once, then put a file `stale.txt` into `autoresearch_grid/check_toystudy/`;
    - a second run gives exit 0, `stale.txt` is gone, and `.check_study` exists;
    - then delete `.check_study` and recreate `stale.txt`;
    - a third run gives exit 1, geometry `"failed"` with a problem containing `"no .check_study marker"`, and `stale.txt` still exists.
  - `test_a_geometry_without_precheck_is_rendered`:
    - a toy doc with `"geom": {"writer": "offline_simpleconfig", "base": "Offline/Mu2eG4/geom/geom_run1_a.txt", "lines": []}`, `preflight` null, and the step's `"files": ["geom"]`;
    - expect exit 0, geometry note `"rendered, not pre-checked"`, and `autoresearch_grid/check_toystudy/state/geom.txt` exists.
  - `test_an_unknown_name_is_exit_2`: `nosuchstudy` gives exit 2, with the name in stderr.
  - `test_a_non_numeric_x_is_exit_2`: `--x=a,2` gives exit 2.
  - `test_text_mode_ends_with_ok`: without `--json`, stdout's last line is `"OK"`.

- [ ] **Step 2: Run them to see them fail.** Run: `... -m unittest tests.test_check_study.TestMain -v`. Expected: failures, because `main` does not exist yet and the module has no `__main__`.

- [ ] **Step 3: Implement** `check_launch`, `prepare_scratch`, `check_geometry`, `main` and the `if __name__ == "__main__": sys.exit(main())` block.

- [ ] **Step 4: Run** `tests.test_check_study`, then the full suite once. Expected: all OK, and the seven `_ax` `measure_basis_sha` unchanged. Print them with `cd core && AUTORESEARCH_DATA_ROOT=<scratch> python -c "import modes; [print(n, s.measure_basis_sha[:8]) for n, s in sorted(modes.STUDIES.items())]"`.

- [ ] **Step 5: Commit**: `git commit -m "check_study: the launch and geometry checks, and main"`.

---

### Task 4: Acceptance, records (controller)

- [ ] **Step 1: Suite** green; record the count and the seven `_ax` basis shas.
- [ ] **Step 2:** `python -m graph.check_study foilspfbpz_ax --json` against the live data root. Expected: exit 1, launch failed on the board (`1a91751589c1` vs the current sha), geometry skipped.
- [ ] **Step 3:** The same check with `AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/claude-scratch/checkstudy_accept`. Expected:
  - exit 0, with the pre-check passed at the center point (~4.5 min);
  - no `autoresearch_leaderboards/` rows in the sandbox;
  - only `check_foilspfbpz_ax/` and `_code/` under its `autoresearch_grid/`.
- [ ] **Step 4:** `python -m graph.check_study ce_chain --executor local --parallel 1 --json` in that sandbox. Expected: exit 0, geometry note `"rendered, not pre-checked"`.
- [ ] **Step 5:** Copy `foilspfbpz_ax.json` to the scratch dir as `bpzcopy.json` (name `bpzcopy`, board `leaderboards/leaderboard_bpzcopy.tsv`), and point `kits.prodtools.code_tarball` at `${ARTIFACT}/autoresearch_muse/Code_missing.tar.bz2`. Check it by path in the sandbox. Expected: exit 1, artifacts failed naming `kits.prodtools.code_tarball`.
- [ ] **Step 6: Records.**
  - Wiki: `drivers/contract-engine.md` (a check_study section), `log.md`, the `index.md` one-liner.
  - Memory `project_phase_c1_branches.md`.
  - Commit.
