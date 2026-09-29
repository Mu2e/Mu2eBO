# Phase C3: delete the old pipeline

Date: 2026-09-28. Branch: `generic-study-phase-c3`, from
`generic-study-phase-c1` at `3d48db1` (which holds C1, C2a and C2b).

## Goal

The contract engine becomes the only way to run a study. Everything
that exists only for the old pipeline is deleted. The engine's runner
and campaign loop take over the pipeline's command names.

## Why now

C2b moved foilspf's two metrics onto the engine and proved parity on
2026-09-28:
- 495/495 archived harvests reproduced;
- 7/7 quantities on three points;
- an end-to-end re-score;
- a local run and two grid points on MDC2025ax.

The pipeline was kept runnable only for that check
(`wiki/drivers/contract-engine.md`, "Phase C split"). No campaign
needs it.

## Decisions (operator, 2026-09-28)

| Question | Answer |
|---|---|
| The seven original foilspf studies and their v1 boards | **Archive, unloaded** (operator chose the easiest path over read-only history). The study files move to `mode_specs/archive/`. The boards stay in `leaderboards/` as plain files. The surrogate MCP stops seeing them; a pre-C3 commit brings them back. |
| Skills and commands that drive the pipeline | **Rewrite for the engine**, in this phase. |
| How to cut | **In order, on one branch, as one pass.** Simplest over safest: old code can be recovered from git. |

## Rulings (controller, while designing)

- **The `desc_fmt` to `desc` template rename is dropped.** It would
  change every `_ax` study's `measure_sha`, because the stage templates
  are part of `measure_basis`. `Leaderboard.append` refuses mixed
  `measure_sha` (`core/leaderboard.py:266`), so every later
  `foilspfbpz_ax` row would be refused until someone moved the board
  aside. That board holds the one real MDC2025ax row (`c2bR11ax01`).
  The rename was cosmetic. `core/adapters/prodtools_entry.py` keeps
  reading `desc_fmt`.
- **`core/pipeline_templates/` keeps its name.** The engine reads it
  (`prodtools_entry.py`), and renaming it would also touch
  `measure_basis`.
- **v1 layout support stays in `core/leaderboard.py`.** Nothing loaded
  uses it any more. Removing it is extra work with nothing gained.
- **The `engine`/`pipeline` flags on `KitDecl` go**, along with `ENGINE`,
  `runs_on_engine` and the refusal gates that read them. Once the two
  pipeline-only KitDecls are deleted, every kit is an engine kit. The
  loader already refuses a study that names an unknown kit. So "loaded"
  means "runnable".
- **Engine launch checks the pipeline had and the engine lacks are
  follow-ups, not part of C3:** data-quota, config-name-free and
  stale-cluster, from `tools/run_grid.sh` via `core/launch_checks.py`.
  They are listed in the wiki's follow-ups.

## What changes

### 1. The seven originals are archived

- `git mv` into `mode_specs/archive/`:
  - `foilsflash.json`, `foilspf.json`, `foilspf2k.json`;
  - `foilspfbp.json`, `foilspfbpx.json`, `foilspfbpz.json`, `foilspfbw.json`.
- `core/study.py` already leaves `archive/` unloaded (`study.py:700`).
- Their boards, `leaderboards/leaderboard_bo_<name>.tsv`, stay.
- `mode_specs/README.md` gets a note on what `archive/` holds.

### 2. The engine stops using pipeline code

The pipeline's fallbacks live inside these shared modules, so cutting
them breaks the pipeline. They therefore land in the same commit as
section 3. The Kerberos move is the exception: it lands first, and the
tree stays green after it.

- **`core/botorch_predict.py`:**
  - `history_points` reads every study through
    `boards.board_for(study).load()`;
  - the module-level `import bo_driver as bo` goes;
  - the pipeline CLI `main()` goes, since `graph/closed_loop.py` was
    its only caller.
- **`graph/pool.py`:**
  - `run_rolling` no longer falls back to pipeline defaults, so every
    caller passes `run_child`, `next_pick`, `row_landed`, `broken` and
    `stagger`;
  - the default helpers `_default_run_child`, `_default_pick_source`,
    `_default_row_landed`, `_default_broken` and `_pending_names` go,
    together with the pipeline branch of `_name_busy_reason`;
  - the stagger fallback to `runtime.CLOSED_LOOP_STAGGER_SEC` goes: the
    engine loop already passes `launch_stagger(study)`, the largest
    `launch_stagger_s` of the study's kits, so no constant replaces it;
  - the unused `alpha` parameter goes with `_default_run_child`.
- **Kerberos:** `check_kerberos` and `GRID_TICKET_SECONDS = 4 * 3600`
  move from `core/launch_checks.py` into `core/contract.py`, next to
  `requires_kerberos`. `graph/study_run.py:_kerberos` calls them there.
- **`core/modes.py`** keeps only `STUDIES`. These go:
  - `SPECS`, `ModeSpec`, `DEFAULT_MODE` and `resolve_env_mode`;
  - `AUTORESEARCH_MODE`;
  - `ENGINE` and `runs_on_engine`;
  - the `study_compat` import.
- **`core/kit_registry.py`** loses:
  - the `ce_sensitivity` and `flash_edep_per_pot` KitDecls;
  - the `engine`/`pipeline` flags.

### 3. Pipeline code is deleted

- **`core/`:** `pipeline.py`, `harvest.py`, `bo_driver.py`,
  `study_compat.py`, `prodtools_exec.py`, `prodtools_submit_driver.py`,
  `runtime.py`, `launch_checks.py`.
- **`graph/`:** `run.py`, `closed_loop.py`, `nodes.py`,
  `pipeline_io.py`, `state.py`, `build.py`.
- **`tools/`:** `run_grid.sh`, `run_local.sh`, `c2b_parity.py`. The
  `tools/` directory goes if it ends up empty.
- **Tests that test only deleted code:**
  - `test_closed_loop`, `test_foilspf_spec`, `test_geom_golden_parity`;
  - `test_golden_parity_harness`, `test_harvest`, `test_json_mode`;
  - `test_nodes`, `test_no_mock_mode`, `test_pipeline_verbs`;
  - `test_seam_protocol`, `test_stages_retired`, `test_prodtools_exec`;
  - `test_launch_checks`, `test_mode_archive`, `test_c2b_parity`;
  - `test_runtime_constants`;
  - `tests/golden_parity.py`;
  - their pipeline-only fixtures: `tests/fixtures/modes/`,
    `tests/fixtures/golden_geom/`, `tests/goldens/`.

  Before deleting each test file, its tests are checked for engine
  behaviour worth moving. The expected answer is none.
- **Tests that touch both paths are trimmed, not deleted:**
  - `test_modes`, `test_botorch_predict`, `test_surrogate`;
  - `test_generic_core`, `test_study_engine`, `test_c2b_studies`: its
    twin-against-original comparison goes; the fixture tests stay;
  - `test_flock` (imports the lock helpers from `leaderboard.py`);
  - `test_audit_fixes`, `test_recursion_limit`, `test_pool`;
  - `test_live_leaderboard_headers`, `test_no_hardcoded_paths`,
    `test_paths`.
- **Graph dependencies:** LangGraph stays for the engine
  (`graph/study_graph.py`).

### 4. Renames

- `graph/study_run.py` becomes `graph/run.py`, and `graph/study_loop.py`
  becomes `graph/closed_loop.py`. This happens after the old files are
  deleted, with `git mv` so history follows.
- Every code reference follows:
  - the child command in the loop's `make_run_child`;
  - refusal and log prefixes (`[study_run]` becomes `[run]`,
    `[study_loop]` becomes `[closed_loop]`);
  - the `pgrep` hint;
  - docstrings.
- Test files follow: `test_study_run.py` becomes `test_run.py`, and
  `test_study_loop.py` becomes `test_closed_loop.py`.
- Old specs and plans under `docs/superpowers/` are history and keep
  the old names.

### 5. Documentation, skills, memory

- **`README.md`** is rewritten around the engine:
  - `python -m graph.run --study … --config … --x=… --context … --executor grid|local`;
  - `python -m graph.closed_loop`;
  - `kits.toml`, the `_ax` studies, v2 boards.
- **`CONTEXT.md`:** the glossary entries that describe the
  pipeline/engine split are updated.
- **Wiki:**
  - `contract-engine.md` gets a C3 section and the new command names;
  - the pipeline pages get `status: superseded` and a pointer to
    `contract-engine`: `pipeline`, `graph-runner`,
    `closed-loop-runner`, `bo-driver`, `preflight`, `local-executor`;
  - `tests.md` gets the new count;
  - `index.md` and `log.md` are updated.
- **Repo commands:** `.claude/commands/closed-loop-harvest.md` and
  `closed-loop-status.md` are rewritten for the engine: state files
  `<step>_results.json` / `<step>_cluster.txt`, v2 boards,
  `broken.txt`, `graph.closed_loop`.
- **User skills** (`~/.claude/skills/`, not in git) are rewritten for
  the engine: `launch-bo-chain`, `more-jobs`, `autopsy`, `status`.
  Each is read in full first and edited in place.
- **Memory:**
  - `project_pipeline_reference_only` records the deletion;
  - `feedback_use_graph_runner` is updated: `graph.run` is now the
    engine's runner.

## Acceptance

1. The full suite is green:
   `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`.
2. `grep` finds no remaining import of a deleted module in `core/`,
   `graph/`, `surrogate/` or `tests/`, and no `SPECS`, `ModeSpec`,
   `bo_driver` or `AUTORESEARCH_MODE` outside `docs/superpowers/` and
   `wiki/`.
3. **Local engine run under the new name**, with
   `AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c3_sandbox/local`
   and `AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies`:
   ```
   python -m graph.run --study foilspfbpz_local --config c3local01 --campaign c3local --x=99.6745,103.0623,116.9368,0.018037,0.071303,0.035832,0.0904,0.2627,0.3544,-37.1405 --context alpha=100000.0 --executor local --parallel 4
   ```
   Pass: the pre-check passes, all 5 steps complete, and one row lands.
4. **The surrogate MCP** (`surrogate/mcp_server.py`, started fresh)
   answers `list_problems` with the seven `_ax` studies.
5. `graph.closed_loop` is covered by the suite's toykit acceptance test
   (`tests/test_closed_loop.py`, renamed from `test_study_loop.py`). No
   grid run: the engine's code changes only by renames and by losing
   fallbacks it never used.

## Out of scope

- The `desc_fmt` rename and the `pipeline_templates/` rename (rulings
  above).
- Removing v1 layout code from `core/leaderboard.py`.
- Porting the pipeline's launch checks (quota, config-name-free, stale
  clusters) to the engine.
- `Run1BAna/` at the repo root: a gitignored clone, left alone.
- The orphan boards in `leaderboards/` (helical, ipa, prodtarget,
  foils_v*, foilsg): left as files.
- Pushing anything, or opening pull requests.

## Open questions

None.
