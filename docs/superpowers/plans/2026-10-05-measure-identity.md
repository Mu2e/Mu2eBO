# Measure Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A board splits only when a kit version is bumped by hand. One
module decides whether a point and a board match. Old boards are
re-stamped once, by hand, after a proof.

**Architecture:**
- **`core/measure.py`** takes over the version and board checks now in
  `score`/`contract`.
- **anakit and beamkit** report hand-constant versions and record their
  build per step at submit.
- **`Leaderboard`** gains a locked, atomic rewrite of the `measure_sha`
  column, which `graph/restamp_board.py` uses after proving each old sha
  from the rows' step records.

**Tech Stack:** Python 3.12 stdlib, unittest.

**Spec:** `docs/superpowers/specs/2026-10-05-measure-identity-design.md` (tip 7b0d2ab)

## Global Constraints

- **`core/measure.py`** is stdlib only (plus `core/point_dir.py`), uses the
  dual import pattern, and never imports `modes`.
- **No `measure_basis_sha` changes.** Task 1 pins all nine:
  - ce_chain 79b9b3e212d94d04f3aece224d3968cb33eae4e6f52c6e23c937281cd058e771
  - foilsflash_ax 405cc0e850b9dc4ed28ee96bea8187c94185bce654230acc5016de73a1763d6f
  - foilspf2k_ax 2060c97e7de0a4a18f6364e0a721e6abe45e4bc98a089b4ffedcea75385e12a4
  - foilspf_ax e96f0491abe95519352962dc51616fca0598eabf5b5cfba122734179da3b250e
  - foilspfbp_ax 54467d3e05b4742da1fbd3a7809cf50f770fdc18219c40773ada487355cb0547
  - foilspfbpx_ax d6ee2d286f6e8e26a6417dfb9530789beefd8f385179036f60c4385d1e6d8a4d
  - foilspfbpz_ax c4aafee1c30ba5121ab727bcab4513786b6d076c10f976d1b786daf95e218a80
  - foilspfbw_ax 01bcbd62be9a8f4d8b825e85267a3e7b45a0746b2784f1c48c32aeacba962191
  - ptg4bl b52fce7c37525597cae53862efe0f272af28f766c6deaefa22b71f08a6861689
- **The new version strings are exact:** anakit `anakit-adapter/1`, beamkit
  `beamkit-adapter/1+fom1`. prodtools and offline_preflight are unchanged.
- **Never write to the live data root.** Tests use temp dirs.
  Acceptance runs only dry runs on the live boards; `--confirm` needs the
  operator's OK.
- **Test command:** `source ./activate.sh >/dev/null 2>&1; PYTHONPATH=
  "$AUTORESEARCH_PYTHON" -m unittest <modules>`. Ignore the tests
  package's stdout discard: assert on returned values or on captured
  `log` lists.

## Review Focus

1. **Two old shas on one board, one provable and one not:** nothing is
   written (all or nothing). Test: Task 5.
2. **A row appended while the proof runs:** `restamp_rows` touches only
   the mapped shas, under the exclusive lock. Test: Task 4.
3. **A crash during the rewrite:** the board is intact, either old or new,
   and the backup exists. Test: Task 4 (an `os.replace` failure).
4. **A resumed point whose adopted steps carry the old version format:**
   the launch is refused with a message naming the version change, not
   "set a new leaderboard.file". Test: Task 1.
5. **The anakit git log fails in the dry run** (no checkout): the plan
   still prints, with a "git log failed: ..." line. Test: Task 5.

---

### Task 1: `core/measure.py`; score and contract use it

**Files:**
- Create: `core/measure.py`, `tests/test_measure.py`.
- Modify: `core/score.py`. `row_meta` uses `recorded_versions`, and
  `MixedVersions` becomes `ScoreError` with the same message text. Delete
  `kit_versions`.
- Modify: `core/contract.py`. `launch_problems` calls
  `measure.point_versions` and `measure.board_problems`. Delete
  `board_problems`, `board_versions` and the late `score` import.

**Interfaces:**
- Produces, in `core/measure.py`:
  - `class MixedVersions(ValueError)`;
  - `recorded_versions(records: Dict[str, dict]) -> Dict[str, str]`;
  - `point_versions(study, current: Dict[str, str], adopted:
    Optional[Dict[str, dict]] = None) -> Tuple[Dict[str, str],
    List[str]]`;
  - `board_problems(study, board, versions: Dict[str, str]) -> List[str]`;
  - `hand_version(kit: str, version: str) -> str`.
- The bodies of the first three move unchanged from score and contract,
  messages included. In `point_versions`, the "finished under version X
  but the kit is now Y" message stays; it already names the version
  change.

- [ ] **Step 1: Write the failing tests** (`tests/test_measure.py`):
  - **`test_recorded_versions`:** one version per kit. Two versions of one
    kit raise `MixedVersions`, with "a kit changed version within this
    point" in the message.
  - **`test_point_versions`:**
    - fresh gives `current`;
    - all of a kit's steps adopted keeps the recorded version;
    - partly adopted at another version gives a problem containing
      "finished under version";
    - a resumed point adopting `anakit-adapter/1+anakit-60cb434419a2`
      under current `anakit-adapter/1` gives a problem naming both strings
      (Review Focus 4).
  - **`test_board_problems`:** empty board gives `[]`; matching gives
    `[]`; another sha gives one problem containing "holds rows measured
    as". Use `Leaderboard.for_study` on a temp path and the toy study from
    `tests/engine_fixtures`.
  - **`test_hand_version`:**
    - `("anakit", "anakit-adapter/1+anakit-60cb434419a2")` gives
      `"anakit-adapter/1"`;
    - `("beamkit", "beamkit-adapter/1+beamkit-0.5.1+fom1")` gives
      `"beamkit-adapter/1+fom1"`;
    - `("anakit", "anakit-adapter/1")` is unchanged;
    - `("prodtools", "prodtools-adapter/1+x")` is unchanged;
    - `("anakit", "anakit-adapter/1+anakit-")` raises ValueError.
  - **`test_basis_shas_are_pinned`:** `modes.STUDIES` gives
    `measure_basis_sha` equal to the nine values in Global Constraints.
- [ ] **Step 2: Run** `tests.test_measure`. Expected: ImportError.
- [ ] **Step 3: Implement.**
  - `hand_version` removes the first `+{kit}-<build>` segment, where the
    build runs to the next `+` or the end, only when `kit` is in
    `("anakit", "beamkit")`.
  - It raises ValueError when that segment is present with an empty
    build.
- [ ] **Step 4: Run** `tests.test_measure tests.test_score tests.test_contract
  tests.test_run`. Expected: OK.
- [ ] **Step 5: Commit** "measure: one module decides a point's versions and
  the board match".

### Task 2: anakit reports a hand version and records its build

**Files:**
- Modify: `core/adapters/anakit.py`:
  - `self._version = VERSION`;
  - a `build` property, which re-reads `fork_commit(self._fork_root)`
    (the dirty-checkout refusal stays);
  - `submit`:
    - drops the moved-commit refusal;
    - reads `build = fork_commit(...)`, which still refuses a dirty
      checkout;
    - writes `"build": build` into `anakit_result.json`;
  - `results` keeps the `rec["version"] != self._version` refusal, with
    message text "was written by version", and puts
    `build=rec.get("build")` in the metadata.
  - Update the `VERSION` comment: "bump when a step would measure anew,
    including a fork change that alters what an analysis computes".
- Test: `tests/test_anakit_kit.py`.

**Interfaces:**
- Produces: `AnakitKit.version == "anakit-adapter/1"`, `AnakitKit.build ->
  str` (the 12-char commit), and the results metadata key `build`.

- [ ] **Step 1: Write the failing tests** (`tests/test_anakit_kit.py`):
  - **`test_the_version_is_the_hand_constant`** (replaces :125-129):
    `kit().version == "anakit-adapter/1"`, and `kit().build` equals the
    fork HEAD's 12-char commit.
  - **`test_a_newer_fork_commit_does_not_break_results`:** submit, then
    commit a change in the fork (`git commit --allow-empty`), then
    `results`. It is accepted, and `metadata["build"]` is the commit
    recorded at submit.
  - **`test_a_newer_fork_commit_does_not_refuse_submit`:** open, commit
    in the fork, submit. Accepted, and the recorded `build` is the new
    commit.
  - **`test_results_refuses_a_result_written_by_another_version`**
    (replaces :402-415): set `rec["version"]` to
    `"anakit-adapter/1+anakit-deadbeefcafe"`. ContractError naming both
    versions.
- [ ] **Step 2: Run** `tests.test_anakit_kit`. Expected: the new tests
  FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_anakit_kit tests.test_measure`. Expected:
  OK.
- [ ] **Step 5: Commit** "anakit: a hand-bumped version; the fork commit is
  the step's recorded build".

### Task 3: beamkit reports a hand version and records its server

**Files:**
- Modify: `core/adapters/beamkit.py`:
  - `start()` keeps `self._server_version` (still refusing a missing one)
    and sets `self._version = f"{VERSION}+fom{FOM_VERSION}"`;
  - a `build` property returns `self._server_version`;
  - `submit` writes `"server": self._server_version` into the step
    record;
  - `results` metadata gets `server=rec.get("server")`.
- Test: `tests/test_beamkit_kit.py`.

**Interfaces:**
- Produces: `BeamkitKit.version == "beamkit-adapter/1+fom1"`,
  `BeamkitKit.build -> Optional[str]`, and the results metadata key
  `server`.

- [ ] **Step 1: Write the failing test** `test_version_is_the_hand_constant`
  (replaces :432-434):
  - `self.kit.version == "beamkit-adapter/1+fom1"`;
  - `self.kit.build` contains `"0.5.1-fake"`;
  - after a submit and a completed status, `results(...).metadata
    ["server"]` contains `"0.5.1-fake"`.
- [ ] **Step 2: Run** `tests.test_beamkit_kit`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_beamkit_kit`. Expected: OK.
- [ ] **Step 5: Commit** "beamkit: a hand-bumped version; the server is the
  step's recorded build".

### Task 4: `Leaderboard` reads rows and rewrites `measure_sha`

**Files:**
- Modify: `core/leaderboard.py`.
- Test: `tests/test_leaderboard.py`.

**Interfaces:**
- Produces:
  - `Leaderboard.live_rows() -> List[Dict[str, str]]`: the live board's
    rows as `{column: text}`, read under the shared lock;
  - `Leaderboard.archive_measure_shas() -> Set[str]`;
  - `Leaderboard.restamp_rows(mapping: Dict[str, str], backup: Path) ->
    int`.
- `restamp_rows`, under the exclusive lock:
  - copies the board to `backup` (`shutil.copy2`);
  - rewrites the `measure_sha` cell of each row whose sha is a key of
    `mapping`;
  - writes a temp file and `os.replace`s it;
  - returns the number of rows changed;
  - raises ValueError when the board does not exist.

- [ ] **Step 1: Write the failing tests:**
  - **`test_restamp_rows_rewrites_only_mapped_shas`:** three rows (shas
    a, a, b) and mapping {a: c} give 2. The shas read c, c, b, every
    other cell is byte-identical, and the backup equals the old file
    (Review Focus 2).
  - **`test_a_failed_replace_leaves_the_board`:** patch
    `leaderboard.os.replace` to raise OSError. `restamp_rows` raises, the
    board is unchanged, and the backup exists (Review Focus 3).
  - **`test_live_rows_and_archive_shas`.**
- [ ] **Step 2: Run** `tests.test_leaderboard`. Expected: AttributeError.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_leaderboard`. Expected: OK.
- [ ] **Step 5: Commit** "leaderboard: read rows and rewrite measure_sha
  under the lock".

### Task 5: `graph/restamp_board.py`

**Files:**
- Create: `graph/restamp_board.py`, `tests/test_restamp_board.py`.

**Interfaces:**
- Consumes:
  - Task 1: `recorded_versions`, `hand_version`;
  - Task 4: `live_rows`, `archive_measure_shas`, `restamp_rows`;
  - `PointDir.of(...).adopted(...)`.
- Produces:
  - **`restamp(study, board, grid_root: Path, current: Dict[str, str],
    builds: Dict[str, Optional[str]], *, why: str, confirm: bool, user:
    str, now: float, log: Callable[[str], None], anakit_log:
    Callable[[str, str], str]) -> int`.** It returns the exit code: 0 for
    proven or nothing to do, 2 for refused.
    - It does the proof in the spec's order and refuses all-or-nothing.
    - It logs one plan block per old sha: row count, the old/new version
      and build of each kit, and for anakit `anakit_log(old_build,
      new_build)`. A failure there logs "git log failed: <exc>" and does
      not refuse.
    - With `confirm`, it calls `board.restamp_rows(mapping,
      backup=<board>.pre-restamp-<UTC %Y%m%dT%H%M%SZ>.tsv)` and appends
      one JSON line per old sha to `<board>.restamp.jsonl` (the spec's
      keys).
  - **`main(argv=None) -> int`** takes `--study`, `--why` (required) and
    `--confirm`.
    - It opens a `KitSet("restamp", executor="grid")`, then reads
      `kit.version` and `getattr(kit, "build", None)` for each step kit.
    - A kit error refuses with exit 2.
    - `anakit_log` runs `git -C $AUTORESEARCH_ANAKIT log --oneline
      <old>..<new> -- tools/analyses/`.
  - **The old build** is parsed from the recorded version: anakit
    `+anakit-<b>`, beamkit `+beamkit-<b>`. A kit with no build segment
    shows its build as "-".
  - **No mixed-build warning.** The spec's warning cannot fire: an
    old-scheme point whose steps ran on two builds recorded two versions,
    which score refused (`MixedVersions`), so no such row is on a board;
    and a new-scheme row is never re-stamped. The spec is amended to
    match.

- [ ] **Step 1: Write the failing tests** (`tests/test_restamp_board.py`).
  - **The fixture:**
    - study `modes.STUDIES["foilspfbpz_ax"]`;
    - a temp board via `Leaderboard.for_study(study, path=tmp/board.tsv,
      archive_path=tmp/none.tsv)`;
    - rows appended with `row_meta`-style meta at
      `study.measure_sha(OLD)`, where
      `OLD = {"anakit": "anakit-adapter/1+anakit-60cb434419a2",
      "prodtools": "prodtools-adapter/1"}`;
    - each row's step records written with `PointDir.of(tmp/grid,
      cfg).write_results(step, {"step", "kit", "kit_version", "handle",
      "metrics": {}, ...})` for all five steps;
    - `CUR = {"anakit": "anakit-adapter/1", "prodtools":
      "prodtools-adapter/1"}`.
  - **`test_dry_run_plans_and_writes_nothing`:**
    - exit 0;
    - the log names the old and new sha, "2 rows", both versions and
      `anakit_log`'s output;
    - the board bytes are unchanged, and there is no backup or log file.
  - **`test_confirm_rewrites_backs_up_and_logs`:**
    - exit 0;
    - `board.measure_shas() == {study.measure_sha(CUR)}`;
    - the backup exists;
    - `restamp.jsonl` has one line with `from`, `to`, `rows: 2`, `by`,
      `why` and `backup`;
    - `measure.board_problems(study, board, CUR) == []`.
  - **`test_refusals_write_nothing`,** one subTest each, each exit 2 with
    the reason in the log and the board unchanged:
    - the basis changed (rows at a sha made with an edited basis: write
      the meta sha from a copy of the study with a changed `fixed`);
    - a hand bump (`CUR` anakit `anakit-adapter/2`);
    - a row whose records are missing;
    - mismatched handles;
    - the old sha present in the archive board;
    - one provable sha plus one unprovable sha (Review Focus 1).
  - **`test_git_log_failure_is_reported`:** `anakit_log` raises
    RuntimeError("no checkout"). Exit 0, and the log contains "git log
    failed: no checkout" (Review Focus 5).
  - **`test_nothing_to_do`:** an empty board, and an already-current board.
    Exit 0 and "nothing to do".
- [ ] **Step 2: Run** `tests.test_restamp_board`. Expected: ImportError.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests.test_restamp_board tests.test_measure
  tests.test_leaderboard`. Expected: OK.
- [ ] **Step 5: Commit** "restamp_board: re-stamp an old board once, after
  proving only builds differ".

### Task 6: Docs, full suite, acceptance

**Files:**
- Modify:
  - `wiki/external/anakit.md` (the bump rule; the fork commit is now the
    step's `build`);
  - `wiki/drivers/contract-engine.md` (a "Measure identity (2026-10-05)"
    section: hand versions, `core/measure.py`, restamp, rollout);
  - `wiki/index.md` (the anakit line "any fork commit changes every _ax
    measure_sha" becomes "a fork commit changes no measure_sha; bump
    anakit's VERSION when an analysis's numbers change");
  - `mode_specs/README.md` (the bump rule next to the board rule);
  - `CONTEXT.md` (the measure_sha entry: kit versions are hand-bumped);
  - `wiki/log.md`;
  - the project memory line about "any anakit fork commit changes every
    _ax measure_sha".

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Run the full suite.** Expected: OK (skipped=3).
- [ ] **Step 3: Check the fingerprints.** The nine basis shas are
  unchanged (the pinned test). `measure_sha` changes for the seven `_ax`
  studies, `ce_chain` and `ptg4bl`: print old and new for each into the
  ledger.
- [ ] **Step 4: Acceptance (read-only on the live data).** Run
  `python -m graph.restamp_board --study foilspfbpz_ax --why "acceptance
  dry run"` and the same for `ptg4bl`. Expected:
  - exit 0;
  - 41 and 29 rows;
  - the anakit dry run lists the commits 60cb434..1f831a1 under
    `tools/analyses/`.
  - Record the output in the ledger.
  - Do NOT pass `--confirm`; that is the operator's call after the merge
    (spec Rollout).
- [ ] **Step 5: Commit** "docs: measure identity".
