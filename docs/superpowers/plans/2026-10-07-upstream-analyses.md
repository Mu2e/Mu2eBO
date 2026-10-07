# Upstream analyses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The seven `_ax` studies and `ce_chain` run on M. MacKenzie's analyses (his `main`, on the `SimJob MDC2025ay` Musing); the fork's analyses and our work area are no longer used.

**Architecture:** The anakit adapter starts the server with `--musing` instead of `--work-area` and drops its work-area checks. Each `_ax` study chains four of his analyses, and the stops number travels through `params_from`. `ce_chain` reads his `trigger_efficiency_ntuple`. All of them get new boards.

**Tech Stack:** Python 3.12 (ana 2.8.0), unittest, the anakit MCP server under ana 2.7.0.

**Spec:** `docs/superpowers/specs/2026-10-07-upstream-analyses-design.md` (c5c052f)

## Global Constraints

- Musing string: `"SimJob MDC2025ay"`, exactly. The anakit checkout is pinned at `3ba8d23` (michaelmackenzie/analysis-mcp-server main).
- `core/adapters/anakit.py:VERSION = "anakit-adapter/2"`.
- Values:
  - `upstream_eff` 0.01278168
  - `cosmic_rate_per_s_per_mev` 0.0018181818181818182
  - flash budget `7.506758e-06`
  - `trigger_paths` `"apr_TrkDe_80m70p, cpr_TrkDe_80m70p"`
- New board file names end in `_upstream.tsv`. Study names do not change.
- The suite runs with: `env PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`.
- Scratch goes under `/exp/mu2e/data/users/oksuzian/`. anakit runs set `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`.
- **No grid submission anywhere in this plan.** The one grid point (spec check 4) waits for the operator's OK after the merge.
- No silent fallbacks: every refusal names what is wrong.

## Review Focus

1. **A Musing written `"SimJob/MDC2025ay"`, or with extra spaces.** anakit accepts both, so the adapter's published-Musing check must parse it the same way (`/`→space, split) and accept it. A one-word value is refused at launch. *(Task 1 tests.)*
2. **Resuming a point whose `anakit_result.json` was written by `anakit-adapter/1`** (it has `work_area`/`code`, no `musing`). `results` refuses it by version with "rerun the step", never with a `KeyError`. *(Task 1 test.)*
3. **An anakit step feeding an anakit step.** The upstream result's ROOT file URI must reach the next step as `data_file`. A reply listing no files fails that next step's submit with the existing "has no input files" error. *(Task 1 test.)*
4. **The study setting `musing` and the step's `analysis` must never reach his `run_analysis` as parameters**, or he would refuse an unknown parameter. *(Task 1 test.)*
5. **A flash of exactly 0** (no event reached the tracker). The fork's analysis refused it itself; now `core/score.py` must refuse it under log10 as a failed evaluation, never as a row. *(Already pinned by `core/score.py`'s log10 check; Task 2 adds a test that the `_ax` flash objective is log10.)*

---

### Task 1: The anakit kit runs on a Musing

**Files:**
- Modify: `core/adapters/anakit.py`, `core/kit_registry.py:217-228` (anakit `study_keys`), `kits.toml` (`[servers.anakit]` comment and `set`)
- Modify: all 8 anakit studies in `mode_specs/` (`kits.anakit`), `tests/fixtures/studies/demo.json`, `tests/fixtures/engine_studies/{foilspf_nominal,foilspfbpz_local}.json`
- Test: `tests/test_anakit_kit.py`, `tests/fakeanakit.py`, `tests/test_kit_config.py`, `tests/test_c2b_studies.py`, `tests/test_study.py` (`PINNED`)

**Interfaces:**
- Produces:
  - study setting `kits.anakit = {"musing": <str>}`;
  - `ak.MUSINGS_ROOT = Path("/cvmfs/mu2e.opensciencegrid.org/Musings")` (tests patch it);
  - `ak.musing_parts(musing: str) -> tuple[str, str] | None` (anakit's split; `None` unless there are exactly two words);
  - `OWN_PARAMS = ("musing", "analysis")`;
  - the result record and results metadata key `"musing"` (no `work_area`, no `code`).
- Removed: `backing_problem`, `code_commit`, the work-area checks.

- [ ] **Step 1: Write the failing tests.**
  - In `tests/fakeanakit.py`:
    - `started_with` reads `--musing`;
    - replace `CATALOGUE` with his four analyses: `muon_stop_rate`, `edep`, `approx_ce_sensitivity`, `trigger_efficiency_ntuple`. Use his names, `input_kind`, `takes_data_files` (True for the two art ones and for `trigger_efficiency_ntuple`), parameters with `required`/`kind`/`minimum`/`maximum`, and metrics, copied from `git -C <anakit> show 3ba8d23:tools/analyses/<name>.py`;
    - the canned metadata carries `stops_per_pot`, `avg_trk_edep_per_gen_event_mev`, `sensitivity` and `n_selected`.
  - `tests/test_anakit_kit.py` imports `CATALOGUE` from `tests.fakeanakit`. Its `_Kit.setUp`:
    - creates `<tmp>/musings/SimJob/MDC2025ay`;
    - patches `ak.MUSINGS_ROOT` to `<tmp>/musings`;
    - has no work area;
    - `params()` = `{"musing": "SimJob MDC2025ay", "analysis": "muon_stop_rate", "upstream_eff": 0.01278168}`.
  - Delete the tests of the backing, `code_commit`, Mu2eOptAna and the work-area directory. Retarget the rest at the new catalogue.
  - Add these tests:
    - `test_the_version_is_the_hand_constant`: `kit.version == "anakit-adapter/2"`.
    - `test_the_server_starts_on_the_studys_musing`: the `cfg.command` logged at `run_analysis` ends with `("--musing", "SimJob MDC2025ay")`, and `"--work-area"` is not in it.
    - `test_neither_musing_nor_analysis_is_sent_as_a_parameter`: the logged `args["parameters"] == {"upstream_eff": 0.01278168}`.
    - `test_the_result_records_the_musing`: the record has `musing == "SimJob MDC2025ay"` and no `"work_area"` or `"code"`; `results(...).metadata["musing"]` is the same.
    - `test_a_result_from_version_1_is_refused_by_version`: write a record with `version "anakit-adapter/1"`, `work_area` and `code`, and no `musing`. `results` raises `ContractError` containing `"rerun the step"`.
    - `test_an_anakit_result_file_is_the_next_steps_input`:
      - submit `cfg1.ce_edep` (`edep`) with a reply listing `<sdir>/nts.x.root`;
      - feed `results(...).files` as the inputs of `cfg1.sob` (`approx_ce_sensitivity`, `root_file`);
      - the logged `args["data_file"] == str(<that nts>)`.
    - `TestStepProblems` (the helper's `kits = {"anakit": {"musing": ...}}`):
      - `test_an_unpublished_musing_is_named`: `"SimJob MDC2099zz"` gives one problem containing `"not published"`.
      - `test_a_musing_needs_a_name_and_a_version`: `"MDC2025ay"` gives one problem containing `"a Musing and a version"`.
      - `test_a_slash_musing_is_accepted`: `"SimJob/MDC2025ay"` gives `[]` for a right step.
      - `test_the_catalogue_is_asked_once_per_musing` (renamed).
    - `test_it_is_a_registered_engine_adapter`: `sorted(decl.study_keys) == ["musing"]`.
  - `tests/test_kit_config.py::test_the_repo_declares_the_anakit_server` also asserts `set_env["OPENBLAS_NUM_THREADS"] == "1"` and `set_env["OMP_NUM_THREADS"] == "1"`.
  - `tests/test_c2b_studies.py`: `kits["anakit"] == {"musing": "SimJob MDC2025ay"}`.

- [ ] **Step 2: Run them.** Run `<suite> tests.test_anakit_kit tests.test_kit_config tests.test_c2b_studies` (`<suite>` is the Global Constraints command with module names in place of `discover ...`). Expected: they FAIL on the version, the `--musing` argument, `MUSINGS_ROOT`, the kits.toml env and the study setting.

- [ ] **Step 3: Implement.**
  - In `core/adapters/anakit.py`:
    - `VERSION = "anakit-adapter/2"`.
    - `_client(musing)` appends `("--musing", musing)`.
    - `submit` pops `musing` and records it.
    - `results` puts `musing=rec["musing"]` in the metadata.
    - Delete `backing_problem`, `code_commit` and `tarfile`.
    - `step_problems` refuses, as the first and only problem:
      - a missing setting: `"kits.anakit.musing is not set"`;
      - `musing_parts(...) is None`: `"... expected a Musing and a version, e.g. 'SimJob MDC2025ay'"`;
      - `MUSINGS_ROOT/<name>/<version>` is not a directory: `"Musing <m> is not published (no <path>)"`.
    - The catalogue cache is keyed by the musing.
    - Update the module docstring: Michael's server, the Musing, no work area.
  - `core/kit_registry.py`: anakit `study_keys={"musing": _string}`.
  - `kits.toml [servers.anakit]`:
    - `set` adds `OPENBLAS_NUM_THREADS = "1", OMP_NUM_THREADS = "1"`;
    - the comment says the adapter appends `--musing <kits.anakit.musing>`, and the checkout is M. MacKenzie's `main`.
  - The 8 studies and 3 fixtures: `"anakit": {"musing": "SimJob MDC2025ay"}`.

- [ ] **Step 4: Re-pin.** Recompute the 8 changed `measure_basis_sha` with the test's own loop and set them in `tests/test_study.py:PINNED`. `ptg4bl` stays `b52fce7c…`.

- [ ] **Step 5: Verify.** Run the suite (Global Constraints). Expected: OK.

- [ ] **Step 6: Commit.** `anakit on a Musing: --musing replaces the work area; no backing or Mu2eOptAna checks; anakit-adapter/2`.

### Task 2: The seven `_ax` studies on Michael's analyses

**Files:**
- Modify: the 7 `mode_specs/*_ax.json`, `tests/fixtures/engine_studies/{foilspf_nominal,foilspfbpz_local}.json`, `core/kit_registry.py` (anakit `fixed_keys`)
- Test: `tests/test_c2b_studies.py`, `tests/test_study.py`

**Interfaces:**
- Consumes: Task 1's `kits.anakit.musing`.
- Produces:
  - step names `stops`, `ce_edep`, `sob`, `flash`;
  - objective metrics `sob.sensitivity` and `flash.avg_trk_edep_per_gen_event_mev`;
  - anakit `fixed_keys` = `analysis`, `upstream_eff`, `cosmic_rate_per_s_per_mev`.

- [ ] **Step 1: Write the failing tests** in `tests/test_c2b_studies.py`.
  - Replace `SOB`/`FLASH` with four dicts, exactly the spec's table:
    - each has `entry` null, `files` [] and `params` {};
    - `params_from` is `{}`, except the `sob` step's `{"stops_per_pot": "stops.stops_per_pot"}`.
  - `test_each_twin_runs_mdc2025ax_and_anakit` asserts:
    - the step order `["mubeam", "mustops_ce", "elebeam_flash", "stops", "ce_edep", "sob", "flash"]`;
    - the four anakit steps equal the dicts.
  - `test_each_twin_writes_its_own_v2_board`: `f"leaderboards/leaderboard_bo_{name}_upstream.tsv"`.
  - New `test_the_objectives_read_michaels_metrics`:
    - metrics `("sob.sensitivity", "flash.avg_trk_edep_per_gen_event_mev")`;
    - transforms `("none", "log10")`.
  - New `test_the_flash_budget_is_per_generated_electron`:
    - `constraints == [{"name": "flash_edep", "max": 7.506758e-06, "k_sigma": 1.0}]`;
    - `abs(7.506758e-06 - 6.50684e-07 * 11.536718606512062) < 1e-12`.
  - `test_obs_noise_is_the_replicate_measured_sigma` expects `(0.0021, 0.010)`. Add a comment: provisional, Task 5 sets it from the measured ratio.
  - `test_the_fixtures_run_foilspfbpz_ax_steps` also asserts that each fixture's `objectives` metrics and `constraints` equal the twin's.
  - `tests/test_study.py` gets `test_the_retired_anakit_settings_are_refused`. Each of `input_correction`, `dio_fraction`, `dio_table`, `pot_per_electron` added to `_step(doc, "sob")["fixed"]` is refused (`assertRejects(doc, <key>)`).

- [ ] **Step 2: Run them.** Run `<suite> tests.test_c2b_studies tests.test_study`. Expected: FAIL on the steps, boards, metrics, budget, noise and the retired keys.

- [ ] **Step 3: Implement.**
  - Rewrite each `_ax` study's anakit steps, objectives (`noise` 0.0021 for sob), constraint and `leaderboard.file`. Append to each `note`: *"Since 2026-10-07 (docs/superpowers/specs/2026-10-07-upstream-analyses-design.md) its analyses are M. MacKenzie's (anakit main, on SimJob MDC2025ay): stops -> ce_edep -> sob, and flash. flash_edep is MeV per generated beam electron, so the budget is the per-POT one times 11.536718606512062. A new board: the old one is history."*
  - Mirror the evaluate, objectives and constraints into the two fixtures (the local fixture keeps its smaller prodtools `fixed`).
  - In `core/kit_registry.py`, anakit `fixed_keys={"analysis": _string, "upstream_eff": _number, "cosmic_rate_per_s_per_mev": _number}`.

- [ ] **Step 4: Re-pin.** Recompute the 7 `_ax` `PINNED` values.

- [ ] **Step 5: Verify.** Run the suite. Expected: OK.

- [ ] **Step 6: Commit.** `_ax studies on Michael's analyses: stops/ce_edep/sob/flash, flash per electron, new _upstream boards`.

### Task 3: `ce_chain` on `trigger_efficiency_ntuple`

**Files:**
- Modify: `mode_specs/ce_chain.json`, `core/kit_registry.py` (adds `trigger_paths`)
- Test: `tests/test_ce_chain.py`, `tests/test_study.py` (`PINNED`)

- [ ] **Step 1: Write the failing test.** Replace `test_the_plot_step_runs_nts_momentum` with `test_the_plot_step_runs_trigger_efficiency_ntuple`:
  - `plot.fixed == {"analysis": "trigger_efficiency_ntuple", "trigger_paths": "apr_TrkDe_80m70p, cpr_TrkDe_80m70p"}`, and `plot.files_from == ("nts",)`;
  - the objective `("n_selected", "plot.n_selected", "max")`;
  - the extra metrics `[("efficiency", "plot.efficiency"), ("n_triggered", "plot.n_triggered"), ("n_events", "plot.n_events")]`;
  - the board `"leaderboards/leaderboard_ce_chain_upstream.tsv"`.
- [ ] **Step 2: Run it.** Run `<suite> tests.test_ce_chain`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The study: fmt `{:.0f}` for the counts and `{:.4f}` for the efficiency; `noise` stays 1.0.
  - Replace the `note`'s nts_momentum sentence with: *"The plot step is M. MacKenzie's trigger_efficiency_ntuple. The ntuple is the triggered stream, so its efficiency is conditional: this checks the chain, not the trigger."*
  - Add `"trigger_paths": _string` to the anakit `fixed_keys`.
  - Re-pin `ce_chain` in `PINNED`.
- [ ] **Step 4: Verify.** Run the suite. Expected: OK.
- [ ] **Step 5: Commit.** `ce_chain reads trigger_efficiency_ntuple; new board`.

### Task 4: Switch the anakit checkout; docs; the launch check on all 8

**Files:**
- Modify: `QUICKSTART.md`, `mode_specs/README.md`, `CONTEXT.md`, `wiki/external/anakit.md`, `wiki/drivers/contract-engine.md`, `wiki/index.md`, `wiki/log.md`

- [ ] **Step 1: Check that nothing is running.** Run `pgrep -af "graph.closed_loop|graph.run "` and `ps -fu $USER | grep [a]nalysis_mcp_server`. Expected: empty. If not empty, STOP and report: the switch would pull the fork out from under a live run.
- [ ] **Step 2: Switch the checkout.**
  - Run `git -C /exp/mu2e/app/users/oksuzian/analysis-mcp-server status --porcelain`. Expected: empty.
  - Run `git -C … fetch origin && git -C … switch --detach 3ba8d23`.
  - Expected: `rev-parse --short HEAD` = `3ba8d23`. The local branch `autoresearch` is still listed by `git branch`.
- [ ] **Step 3: Docs.** Every mention of `work_area`, `autoresearch_muse_ax`, `ce_sensitivity`, `flash_edep_per_pot`, `nts_momentum` and "the anakit fork" in `QUICKSTART.md`, `mode_specs/README.md` and `CONTEXT.md` now describes the Musing and his `main`. Keep the history notes. The QUICKSTART clone line becomes `git clone https://github.com/michaelmackenzie/analysis-mcp-server.git analysis-mcp-server && git -C analysis-mcp-server switch --detach 3ba8d23`, and the "until the fork is published" note goes.
- [ ] **Step 4: Wiki.**
  - `wiki/external/anakit.md` gets new title, description and Summary; key-facts sections "The checkout" (pinned commit, and the spec's pull rule: pull only on purpose, read the diff of the four analyses, bump `VERSION` if numbers change), "The Musing", "The studies' four steps", "Retired"; and the existing 2026-09/10 facts kept under "History (fork)". Its `timestamp: '2026-10-07'`.
  - `contract-engine.md` gets a key-facts bullet.
  - `index.md` gets one-liners for anakit and contract-engine.
  - `log.md` gets a `## 2026-10-07` bullet.
- [ ] **Step 5: The launch check** (spec check 2), from the worktree, sequentially, in the background: run `python -m graph.check_study <name> --json` for the 8 studies. The 7 geometry pre-checks take about 6 minutes each. Expected: exit 0 with `report.ok` true for each. A failed check is a finding against Task 1–3 code or the study; fix it under TDD before going on.
- [ ] **Step 6: Commit.** `docs: anakit is M. MacKenzie's main on SimJob MDC2025ay`.

### Task 5: Re-analyse an old point; set the sob noise; run `ce_chain` locally

- [ ] **Step 1: Build the sandbox.**
  - Set `S=/exp/mu2e/data/users/oksuzian/claude-scratch/upstream_accept`.
  - For `mubeam`, `mustops_ce` and `elebeam_flash`, copy `<step>_results.json` and `<step>_cluster.txt`, plus `preflight_verdict.json`, from `autoresearch_grid/bpzax01R12_00/state/` to `$S/autoresearch_grid/upacc01/state/`.
  - Read the point's `x` from its `point.json`.
- [ ] **Step 2: Run the anakit steps through the engine.** Run `AUTORESEARCH_DATA_ROOT=$S graph.run --study foilspfbpz_ax --config upacc01 --campaign upacc --x <x> --executor local`. Expected:
  - the three prodtools steps are "adopted";
  - `stops`, `ce_edep`, `sob` and `flash` run;
  - a row lands on `$S`'s `leaderboard_bo_foilspfbpz_ax_upstream.tsv`.
  - If `graph.run` refuses the adopted records or reruns the preflight, write a `Ruling:` and let the preflight run (about 6 min). Never submit prodtools steps.
- [ ] **Step 3: Check the numbers** (spec check 1), from `$S/.../state/<step>_results.json`:
  - `stops` `stops_per_pot` == 296174 / (3e6 × 1.0) × 0.01278168 = 1.2618671e-03 (relative 1e-12);
  - `flash` `avg_trk_edep_per_gen_event_mev` == 6.58426068582917e-06 (relative 1e-5). **If it is off: STOP and report** (the budget needs re-measuring);
  - `sob` `sensitivity` == his `run_analysis("approx_ce_sensitivity", data_file=<ce_edep nts>, parameters={"stops_per_pot": <stops value>, "cosmic_rate_per_s_per_mev": 0.0018181818181818182})`, called by hand in a scratch output dir (relative 1e-9).
  - Record `ratio = sensitivity / 3.820180850105821`.
- [ ] **Step 4: Set the noise.** In the 7 studies, sob `noise = round(0.006 × ratio, 4)`; update the Task 2 test pin. `noise` is not in `measure_basis` (`PINNED` must not move). Run the suite: OK. Commit `_ax sob noise scaled to the new sensitivity (ratio <r> at bpzax01R12_00)`.
- [ ] **Step 5: `ce_chain` locally** (spec check 3). Run `AUTORESEARCH_DATA_ROOT=$S graph.run --study ce_chain --config cechainU01 --campaign cechainU --executor local --parallel 1`. Expected: a row on `$S`'s `leaderboard_ce_chain_upstream.tsv` with `n_selected` > 0 and an `efficiency` value.
- [ ] **Step 6: Record.** Add the three checks' numbers to the anakit wiki page and the log bullet. Commit `wiki: upstream analyses acceptance (stops exact, flash <rel>, sob ratio <r>, ce_chain row)`.
