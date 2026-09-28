# Phase C2b: the sob and flash analyses on anakit, and the foilspf studies on the engine — design

Date: 2026-09-27. Status: draft for review.

Related:
- [`2026-09-26-c2a-preflight-kit-design.md`](2026-09-26-c2a-preflight-kit-design.md):
  Phase C2a, the split of C2 into C2a and C2b, and the pre-check kit this
  builds on (merged into branch `generic-study-phase-c1`).
- [`2026-09-23-generic-study-design.md`](2026-09-23-generic-study-design.md):
  the generic-study design.
- `wiki/drivers/contract-engine.md`: the engine, the C1 and C2a acceptance
  runs, and the C2a review findings carried here.
- Fact sheet `/exp/mu2e/data/users/oksuzian/claude-scratch/c2b-facts.md`:
  how the pipeline computes sob and flash today, anakit's internals, the
  archived parity inputs. File and line references below that are not
  repeated here come from it.
- anakit: `github.com/michaelmackenzie/analysis-mcp-server` (clone at
  HEAD `039e969`); Mu2eOptAna: `github.com/michaelmackenzie/Mu2eOptAna`
  (HEAD `3d8ba5a`).

## Goal

The foilspf studies run on the contract engine, on SimJob MDC2025ax, with
their two metrics computed by anakit instead of the old pipeline's harvest:

- `sob.s_over_sqrt_b`: EdepAna on the CE files, the μ⁻ stop count, the
  absolute CE efficiency, and the rough Run 1A sensitivity scan.
- `flash.flash_edep_per_pot`: tracker StrawGasStep ionizing energy from
  the electron-beam early flash, per proton on target.

Done when:
1. the parity check (section 6) passes: the new analyses give the
   pipeline's numbers on the same archived files;
2. a local foilspfbpz point runs end to end on the engine on MDC2025ax;
3. two full-scale grid points land rows: the deployed target, which sets
   the new damage budget, and the bpz07R11_00 champion.

C3 then deletes the old pipeline.

## Decisions

All decided by the operator on 2026-09-27, except where a finding is
noted.

| Question | Decision |
|---|---|
| Whose code computes sob? | M. MacKenzie's: Mu2eOptAna's EdepAna and anakit's `approx_ce_sensitivity`, with our constants passed in. |
| Which cosmic rate? | Ours, `2e4/1.1e7` per s per MeV/c (the macro's), not anakit's default `10/7.8e5` or the Run 1A paper's. |
| How many engine kits? | One generic `anakit` kit. A step names the anakit analysis to run; the adapter holds no physics. |
| Where does the physics live? | In anakit analyses on our fork: a new `ce_sensitivity` and a new `flash_edep_per_pot`. Offered to M. MacKenzie as a pull request only with the operator's go-ahead. |
| Where do the denominators come from? | The files themselves (finding, 2026-09-27): every output file's SubRun carries its job's `GenEventCount("genCounter")` — 200000 (mubeam TargetStops), 75000 (CeEndpoint), 110000 (EarlyEleBeamFlash) on gridphaseA01, exactly the pipeline's events per job. No study repeats events-per-job numbers. |
| EdepAna for MDC2025ax | We build Mu2eOptAna ourselves on p107 in a new work area. No fallback to M. MacKenzie's p103 build. |
| How does a synchronous anakit run fit the engine? | Each step starts its own anakit server; `submit` waits for the analysis. Finding: anakit's FastMCP (mcp 1.28) calls sync tools on the event loop, so one server runs one analysis at a time. |
| No signal window, or any other analysis error | The step fails loudly; the point is broken; no row. Finding: none of the 2,151 rows across the 13 foils-family boards that carry sob has sob ≤ 0, so the macro's `-1` path never mattered. |
| Parity | Three levels: sensitivity alone on every archived point; the full chain on three points; the engine end to end on one point. |
| Boards | New v2 boards; the old ones stay as frozen history. |
| Damage budget | Re-measured on MDC2025ax from the deployed target at acceptance, then written into the study files. |
| C2a leftovers | A resumed point reuses a saved pre-check pass; the pre-check's notes reach its message. |
| Edit the seven study files in place, or add engine twins? | Twins, `<study>_ax` (ruling while planning, 2026-09-27). Editing in place would move all seven off the pipeline, but the pipeline's code and about 30 test files use `foilspf` as their reference mode (`core/modes.py` asserts `DEFAULT_MODE = "foilspf"` is a pipeline study). The originals stay as the pipeline's frozen reference until C3 deletes both. |

## 1. The analyses, on our anakit fork

### The fork
- A clone of anakit at `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`,
  branch `autoresearch`, from upstream `039e969`. Nothing is pushed to
  GitHub without the operator's go-ahead.
- It runs under the ana 2.7.0 interpreter (mcp 1.28; anakit needs
  `mcp<2`), with the clone on `PYTHONPATH`. Measured on 2026-09-27: our
  mcp 2.0 client talks to it over stdio.
- Its tests (`python3 tests/test_tools.py`) cover every change below,
  including the `SAMPLE_STDOUT` its registry tests require per `art_files`
  analysis.

### Change to `approx_ce_sensitivity`
Two new optional parameters, whose defaults keep today's behaviour:
- `dio_table`: path of the DIO spectrum table (default: the path it
  hard-codes today). A missing file is an error.
- `dio_fraction`: the DIO normalisation (default `1 - 0.609`). We pass
  `0.39`, the macro's.

The scan itself is split out as a function the new `ce_sensitivity`
analysis calls, so both run the same code.

### New analysis `ce_sensitivity`
- **Input:** `art_files`, a mixed list. Files whose name contains
  `.TargetStops.` are the stops; files containing `.CeEndpoint.` are the
  CE files. Any other file, or an empty group, is an error.
- **Parameters, all required:** `input_correction` (we pass
  `0.01278168`), `cosmic_rate_per_s_per_mev` (`2e4/1.1e7`),
  `dio_fraction` (`0.39`), `dio_table` (our copy, section 2).
- **Steps:**
  1. anakit's `count` job (`Mu2eOptAna/fcl/print_counts.fcl`) over the
     TargetStops files, with filter label `TargetStopPrescaleFilter`:
     `muminus_stops` = events, `mubeam_sim_total` = generated events,
     `prescale` = the filter's fraction.
  2. EdepAna (`Mu2eOptAna/fcl/edep.fcl`) over the CE files: `ce_seen` =
     events, `ce_simulated_events` = generated events, and the
     `nts` ROOT file.
  3. `ce_abs_eff = input_correction × muminus_stops / (mubeam_sim_total ×
     prescale) × ce_seen / ce_simulated_events`. The pipeline's formula
     is the same with `prescale = 1` (`TargetStopPrescaleFilter.nPrescale`
     is 1 in our mubeam stage).
  4. The sensitivity scan on the `nts` file with `sig_eff = ce_abs_eff`
     and the three constants.
- **Metrics:** `s_over_sqrt_b`, `ce_abs_eff`, `ce_seen`,
  `ce_simulated_events`, `muminus_stops`, `mubeam_sim_total`, `prescale`,
  the box edges, and the signal, DIO and cosmic counts in the box.
- **Errors:** zero stops, zero generated events, zero CE events, a
  prescale fraction of 0, or no qualifying signal window.

### New analysis `flash_edep_per_pot`
- **Input:** `art_files`, the early-flash files.
- **Parameter, required:** `pot_per_electron` (we pass `25000000 /
  2166994` = 11.536718606512062, EleBeamCat's generated count per event).
- **Steps:** EdepAna over the files; `flash_edep_per_pot =
  avg_trk_edep_per_gen_event_mev / pot_per_electron`.
- **Metrics:** `flash_edep_per_pot`, plus EdepAna's own (`n_events`,
  `n_gen_events`, the per-event and per-gen-event averages).
- **Errors:** zero generated events, or zero tracker energy.
- The pipeline's Winsorized per-file diagnostics are dropped: they were
  never the objective, and one EdepAna job over all files has no per-file
  totals.

## 2. EdepAna for MDC2025ax

- A new muse work area, `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax`,
  whose `backing` is SimJob MDC2025ax (Offline v13_38_00, p107). It holds a
  clone of Mu2eOptAna, branch `autoresearch`, from `3d8ba5a`.
- One patch on that clone: the EdepAna summary prints its numbers at full
  precision (`std::setprecision(15)`). Today it prints doubles at 6
  significant figures, so the per-gen-event average — flash itself — is
  off by up to 5e-6 relative, and an event count above 1e6 prints as
  `2.70937e+06` (incident `edepana-saw-events-scientific-notation-parse`).
  anakit's number pattern already reads the longer form.
- Build: `muse setup` (the backing sets p107) and `muse build`. If it does
  not compile on p107, the fix goes on our clone and M. MacKenzie is told.
- The DIO table is copied from
  `autoresearch_muse/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl`
  (byte-identical to M. MacKenzie's, md5 `be9d67e140645faff63440fb138a2faa`) to
  `autoresearch_muse_ax/data/`, and the sob step names that copy.
- **A rebuilt EdepAna gets a new work-area directory.** The work area's
  path is a study setting, so a new path changes `measure_sha`; rebuilding
  in place would not.
- The old `autoresearch_muse` (Run1BAna, p094) stays only for the pipeline
  until C3.

Checked first in the plan, before anything depends on them: Mu2eOptAna
builds on p107, and its EdepAna reads the archived Run1Bap-written
CeEndpoint and EarlyEleBeamFlash files (its FCL names calorimeter
collections the early-flash files may not hold).

## 3. The `anakit` adapter

### Files
- **New:** `core/adapters/anakit.py`, `AnakitKit`, registered in
  `core/adapters/__init__.py` like the prodtools and pre-check adapters.
- **Registry:** a `KitDecl` for `anakit` (`engine=True`, `pipeline=False`,
  `step_kit=True`, `uses_entries=False`). Study setting: `work_area`
  (required). Fixed keys: `analysis` plus every parameter the two
  analyses take (`input_correction`, `cosmic_rate_per_s_per_mev`,
  `dio_fraction`, `dio_table`, `pot_per_electron`).
- **kits.toml:** `[servers.anakit]`: the ana 2.7.0 python with
  `-P -m analysis_mcp_server --transport stdio` (`-P` keeps the working
  directory off `sys.path`, so our repo's `tools/` can never shadow
  anakit's `tools` package); `set` `PYTHONPATH` to the
  fork and `SPACK_USER_CACHE_PATH`; timeouts `start` 120,
  `list_analyses` 120, `run_analysis` 3600. The adapter appends
  `--work-area <work_area>` when it starts a server, so anakit's silent
  default (M. MacKenzie's own work area) can never be used.

### Running a step
- `submit(name, params, files, inputs, workflow)`: `name` is
  `<config>.<step>`. The adapter
  1. converts every input FileRef to a local path (`file://` only, via
     `prodtools_entry.local_path`; a `root://` ref is an error);
  2. empties the step's directory `<GRID_DATA_ROOT>/<config>/anakit/<step>/`
     (beside the prodtools adapter's `<config>/prodtools/<step>/`, so a step
     named `state` or `preflight` cannot collide with the point's own
     directories);
  3. starts its own anakit server for this step and calls `list_analyses`
     for the analysis' declared metrics and whether it takes a file list;
  4. calls `run_analysis(analysis, output_dir=<step dir>, data_files=…`
     (or `data_file` for an analysis that takes one ROOT file)`,
     parameters=<params minus work_area and analysis>, timeout_s=3000)`:
     anakit's own limit, kept under the 3600 s MCP call timeout;
  5. writes the reply to `<step dir>/anakit_result.json`, closes the
     server, and returns `name`.

  The engine runs each step in its own thread, so a waiting `submit`
  holds up nothing else.
- `status`: reads `anakit_result.json`: `completed` if anakit said
  `success`, `failed` with anakit's message otherwise, and `failed` if the
  file is missing.
- `results`: the analysis' declared metrics (from `list_analyses`) as
  `metrics`; the files anakit wrote, as `file://` FileRefs; everything else
  anakit returned (box, assumptions, log path, fork and Mu2eOptAna
  commits) as `metadata`.
- No `cancel`: anakit has none. A step whose sibling failed runs to
  completion; the scheduler already logs that.
- A point resumed after a crash mid-analysis has no handle for the step,
  so the analysis runs again (at most about 15 minutes).

### Version
`anakit-adapter/1` plus the fork's commit. The adapter refuses to open
if the fork has uncommitted changes, since `measure_sha` could not tell
those builds apart.

### Launch check
`check_kits` gains an optional adapter hook, `step_problems(study, step)
-> list[str]`, called once per step that uses the kit. The anakit adapter
starts a server on the study's work area, calls `list_analyses`, and
reports:
- an unknown analysis;
- a parameter the analysis does not take, or a required one missing;
- an objective metric the analysis does not return;
- a work area whose `backing` names a different Musing than the study's
  prodtools `code_tarball` (read from the tarball's `Code/backing` link,
  without unpacking).

The hook runs from `check_kits` (`graph.study_loop`) and from
`graph.study_run`'s launch, once its kits have started, so a wrong study is
refused before any grid job, not after hours of it.

## 4. The foilspf studies

Each of the seven foilspf-family studies (`foilsflash`, `foilspf`,
`foilspf2k`, `foilspfbp`, `foilspfbpx`, `foilspfbpz`, `foilspfbw`) gets an
engine twin, `mode_specs/<study>_ax.json`: the same knobs, derive, geometry,
objectives and columns, with these differences:
- `kits.prodtools.code_tarball` and `kits.offline_preflight.code_tarball`:
  `${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2`;
  `kits.prodtools.dsconf`: `MDC2025ax_{cfg}`.
- New `kits.anakit.work_area`: `${ARTIFACT}/autoresearch_muse_ax`.
- The `sob` step: `"kit": "anakit"`, `fixed` = `{"analysis":
  "ce_sensitivity", "input_correction": 0.01278168,
  "cosmic_rate_per_s_per_mev": 0.0018181818181818182, "dio_fraction":
  0.39, "dio_table": "${ARTIFACT}/autoresearch_muse_ax/data/heeck_finer_binning_2016_szafron.tbl"}`.
- The `flash` step: `"kit": "anakit"`, `fixed` = `{"analysis":
  "flash_edep_per_pot", "pot_per_electron": 11.536718606512062}`.
- Objective metrics are unchanged (`sob.s_over_sqrt_b`,
  `flash.flash_edep_per_pot`).
- The loader checks a step's `fixed` string values by the same rule as
  kit settings (`core/study.py` `_expand`: only `${ARTIFACT}/` expands, a
  personal user area is refused) at load, and `scheduler.step_params`
  expands them when it builds a step's params. `Step.fixed` keeps the raw
  values, so `measure_basis` hashes them unexpanded, as it does kit
  settings.
- Leaderboard: `leaderboards/leaderboard_bo_<study>_ax.tsv`, layout `v2`,
  starting empty. The old boards stay as frozen history: a new release
  moves sob (Run1Bak to Run1Bap moved it +5%), so their rows cannot be
  mixed in.
- The originals are unchanged: they keep the `ce_sensitivity` and
  `flash_edep_per_pot` kits and stay the pipeline's frozen reference, with
  no campaigns, until C3 deletes the pipeline, those KitDecls and the
  originals together. Tests that assert every shipped study is a pipeline
  study are updated to exclude the twins.

Only `foilspfbpz_ax` gets acceptance runs; the other six twins get a load
test. Their searches are closed and no campaigns are planned.

The damage budget (`constraints` `flash_edep max 6.85443e-07`, the flash
of the deployed target `nominalAB01` on Run1Bap) is replaced after the
grid acceptance by the deployed target's flash on MDC2025ax, in the
seven twins only, in a separate commit.

New fixtures under `tests/fixtures/engine_studies/`:
- `foilspfbpz_local.json`: `foilspfbpz_ax`'s five steps at small scale for the
  local acceptance. The flash step is sized so the early-flash output
  holds events: at 1×200 it would hold none (about 78 of 110000 events
  pass) and the step would correctly fail. The plan measures the size.
- `foilspf_nominal.json`: zero knobs; `foilspfbpz_ax`'s geometry template
  with the deployed stack as constants (37 foils, rOut 75, halfThickness
  0.0528, hole radius 21.5, extent 800 so the pitch is 22.2222 and the
  IPA distance is 625), matching
  `autoresearch_grid/nominalAB01/geom/autoresearch_nominalAB01_geom.txt`'s
  stack; `foilspfbpz_ax`'s five steps at full scale.

## 5. Leftovers from C2a's review

### A resumed point reuses a saved pre-check pass
- **Today:** `node_preflight` (`graph/study_graph.py`) runs the pre-check
  on every start of a point, including a restart. A transient failure on
  the second run marks the point broken while its grid jobs still run.
- **Change:** `preflight_verdict.json` also records the pre-check's
  params and the SHA-256 of each file it was given. On a restart, a saved
  verdict with `ok: true` and the same params and hashes is reused, and
  the log says so. A saved failure is never reused: retrying a point
  (deleting `broken.txt`) checks it again.

### The pre-check's notes reach its message
- **Today:** `OfflinePreflightKit.check` returns
  `f"{code}: {reason}"`; the verdict's notes (foils verified against the
  GDML, overlap hit counts, known stock overlaps) are dropped.
- **Change:** the message ends with the notes, one per line, and
  `preflight_verdict.json` carries them.

## 6. The parity check

A manual script, `tools/c2b_parity.py`, outside the unit-test run (like
`tests/golden_parity.py`). It talks to the fork through the
`[servers.anakit]` config, writes a report file, and is deleted with the
pipeline in C3.

**Level 1: the sensitivity scan alone, on every archived point.**
- For each `foilspf*` harvest directory whose `summary.json` has
  `ce_abs_eff` and `s_over_sqrt_b` and which keeps `nts.ce.root` (497
  today), it runs `approx_ce_sensitivity` on that file with `sig_eff =
  ce_abs_eff`, our cosmic rate, `dio_fraction 0.39` and our DIO table.
- Pass: for old value `v` (printed by the macro at 3 significant figures)
  and new value `w`, `|w − v| ≤ 0.5·u + 1e-4·|v|`, where `u = 10^(⌊log10
  |v|⌋ − 2)` is the last printed digit's unit. The `1e-4` covers anakit's
  convolution change, which its README puts at 0.01%.
- Directories skipped for missing fields are counted in the report, not
  silently dropped.

**Level 2: the full chain, on gridphaseA01, foilspfbpz07R11_00 and
foilspfbpz07R19_00.**
- The inputs are the art files listed in each point's
  `state/{mubeam,mustops_ce,elebeam_flash}_outputs.txt`. All are on disk
  (checked 2026-09-27).
- It runs the new `ce_sensitivity` and `flash_edep_per_pot` and compares
  with `summary.json`:
  - `muminus_stops`, `mubeam_sim_total`, `ce_seen`,
    `ce_simulated_events`: equal;
  - `ce_abs_eff` and `flash_edep_per_pot`: relative difference ≤ 1e-6;
  - `s_over_sqrt_b`: the Level 1 rule.
- Two known differences could break it: the new EdepAna (Offline
  v13_38_00) reads files written by Run1Bap (v13_32_10), and Mu2eOptAna's
  `edep.fcl` names geometry `geom_run1_b_v40.txt` where ours names `v06`
  (which v13_38_00 no longer ships).
  A mismatch is investigated, never absorbed by loosening a tolerance.

**Level 3: the engine end to end, on gridphaseA01.**
- In a sandbox `AUTORESEARCH_DATA_ROOT`, the three prodtools steps'
  `<step>_results.json` are written by hand, pointing at the archived
  files, so the scheduler adopts them. `graph.study_run` then runs the
  pre-check, the `sob` and `flash` steps, and the scoring for
  gridphaseA01's point under `foilspfbpz_ax`.
- Pass: the sandbox board's row matches `summary.json` under the Level 2
  rules.

## Failures

| Failure | Result |
|---|---|
| anakit replies `status: error` (bad input, mu2e job failed, no signal window, zero counts) | the step fails with anakit's message; the point is broken; no row |
| anakit's server fails to start, dies, or a run exceeds 3600 s | the step fails with the KitClient error |
| an input ref is not `file://`, or a file is missing | the step fails before any job runs |
| a TargetStops or CeEndpoint group is empty, or a file is neither | the sob step fails |
| the fork has uncommitted changes | the adapter refuses to open; the launch check reports it |
| unknown analysis, wrong parameters, missing metric, or work area on a different Musing than the code tarball | the launch check refuses the study before any job |
| the engine child dies mid-analysis | the rerun repeats that analysis |
| a restart after a passing pre-check | the saved pass is reused if params and files are unchanged; otherwise the check runs again |

## Testing
- Fork (`tests/test_tools.py`): the file-name split; the efficiency
  formula on fixed counts; the new parameters and their defaults; the
  errors listed in section 1; `SAMPLE_STDOUT` for both new analyses,
  including the full-precision EdepAna summary.
- `tests/test_anakit_kit.py`: the adapter against a fake anakit server
  (like `tests/toykit.py`): submit/status/results, the step directory,
  `file://` to path, error replies, a missing result file, the version
  and the dirty-fork refusal, and `step_problems` for each launch-check
  case, including the backing comparison on a small test tarball.
- `tests/test_contract*`: `check_kits` calls `step_problems` when an
  adapter has it and ignores adapters that do not.
- Registry and loader: the `anakit` KitDecl; `${ARTIFACT}/` expansion and
  the personal-area refusal in step `fixed` values, with `measure_basis`
  unchanged by the expansion; the seven twins load and resolve to the
  engine, the seven originals still to the pipeline.
- `tests/test_study_graph*`: the pre-check reuse rules (pass reused;
  failure, changed params, changed file each re-run) and the notes in the
  message.

## Acceptance (the controller, after the final review)
1. The parity check passes at all three levels.
2. `foilspfbpz_local` runs locally on MDC2025ax on the engine: the
   pre-check passes, all five steps complete, a row lands on a sandbox
   board.
3. Grid, full scale: `foilspf_nominal` (the deployed target) and
   `foilspfbpz_ax` at bpz07R11_00's point both land rows.
   The report gives both points' sob and flash next to their Run1Bap
   values (3.26 / 6.854e-7 and 4.15 / 6.695e-7). There is no pass or fail
   on the values; a change of more than 20% is investigated before the
   budget is written.
4. The deployed target's MDC2025ax flash replaces `6.85443e-07` in the
   seven twins' `constraints`, as its own commit.

## Out of scope
- Pushing the anakit fork or the Mu2eOptAna patch, or opening pull
  requests to M. MacKenzie: each needs the operator's go-ahead.
- Moving EdepAna into Offline (M. MacKenzie's plan).
- New foilspf campaigns.
- Deleting the pipeline and the `ce_sensitivity` / `flash_edep_per_pot`
  KitDecls (C3), and the `desc_fmt` rename.
- Testing `cancel_run` against real servers; the prodtools tape-check bug.

## Open questions
- None.
