# Phase C2b: sob and flash on anakit, foilspf studies on the engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The foilspf studies' two metrics (`sob.s_over_sqrt_b`, `flash.flash_edep_per_pot`) are computed by anakit analyses on our fork, driven by a new `anakit` engine adapter, for engine twins of the seven foilspf studies on SimJob MDC2025ax.

**Architecture:** Three code bases change. (1) Our fork of anakit (`/exp/mu2e/app/users/oksuzian/analysis-mcp-server`, branch `autoresearch`) gains two analyses, `ce_sensitivity` and `flash_edep_per_pot`, and two optional parameters on `approx_ce_sensitivity`. (2) A new muse work area (`/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax`) holds Mu2eOptAna built on p107 with a full-precision summary patch. (3) autoresearch gains `core/adapters/anakit.py` (one anakit server per step, synchronous run, result file), a `step_problems` launch hook, `${ARTIFACT}/` in step `fixed` values, the C2a pre-check fixes, seven `mode_specs/<study>_ax.json` twins, two fixtures and a parity script.

**Tech Stack:** Python 3.12 (ana 2.8.0, mcp 2.0) for autoresearch; Python 3.12 (ana 2.7.0, mcp 1.28 FastMCP) for anakit; muse/art (SimJob MDC2025ax = Offline v13_38_00, p107) for EdepAna; unittest (autoresearch) and anakit's bare-assert runner.

**Spec:** `docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md`

## Global Constraints

- Work on branch `generic-study-phase-c2b` in `/exp/mu2e/app/users/oksuzian/autoresearch`. Tasks 1–4 also commit in two other repositories, each on a local branch `autoresearch`: the anakit fork `/exp/mu2e/app/users/oksuzian/analysis-mcp-server` and the Mu2eOptAna clone `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/Mu2eOptAna`.
- Never push, never open a pull request, never post to GitHub. Cloning from GitHub is fine.
- Never use `git stash`, `git checkout -- <file>`, `git reset` or `git clean` in autoresearch: the operator has uncommitted files in `docs/` that must stay untouched. Stage explicit paths only (`git add <path> ...`), never `git add -A` or `git add .`.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```
- autoresearch suite: `cd /exp/mu2e/app/users/oksuzian/autoresearch && source activate.sh && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` must end `OK` after every autoresearch task.
- anakit suite: `cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server && TMPDIR=/exp/mu2e/data/users/oksuzian/claude-scratch/tmp PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python tests/test_tools.py` must end `0 failure(s)` after every anakit task.
- Manual scratch output goes under `/exp/mu2e/data/users/oksuzian/` (never `/tmp`, never `$HOME`). Unit tests may use `tempfile` as the existing suites do. No unit test may write under the real `paths.GRID_DATA_ROOT` or `paths.GRAPH_DATA`: pass `grid_root` / patch those paths (the C2a lesson).
- Tracked autoresearch source (`core`, `graph`, `tests`, `tools`, `mode_specs`) must not name a personal user area: `tests/test_no_hardcoded_paths.py` enforces it. Use `${ARTIFACT}/`, `paths.DATA_ROOT`, environment variables, or a `personal-path-ok:` pragma with a reason.
- Never search `/cvmfs`; name exact paths. Never copy files from tape-backed areas to disk.
- No silent fallbacks: every failure below fails loudly with the reason.
- The seven original study files `mode_specs/{foilsflash,foilspf,foilspf2k,foilspfbp,foilspfbpx,foilspfbpz,foilspfbw}.json` are NOT modified.
- Values, verbatim from the spec:
  - `input_correction` = `0.01278168`
  - `cosmic_rate_per_s_per_mev` = `0.0018181818181818182` (`2e4 / 1.1e7`)
  - `dio_fraction` = `0.39`
  - `pot_per_electron` = `11.536718606512062` (`25_000_000 / 2_166_994`)
  - DIO table: `${ARTIFACT}/autoresearch_muse_ax/data/heeck_finer_binning_2016_szafron.tbl`, md5 `be9d67e140645faff63440fb138a2faa`
  - Work area setting: `${ARTIFACT}/autoresearch_muse_ax`
  - Code tarball: `${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2`; dsconf `MDC2025ax_{cfg}`
  - anakit's own run limit `RUN_TIMEOUT_S = 3000`; kits.toml `[servers.anakit]` timeouts `start = 120`, `list_analyses = 120`, `run_analysis = 3600`
  - anakit fork base `039e969`; Mu2eOptAna base `3d8ba5a`
  - Environment variable naming the fork checkout: `AUTORESEARCH_ANAKIT`

## Review Focus

1. The `sob` and `flash` steps of one point submit at the same moment on one `AnakitKit` (the engine runs each step in its own thread): each must get its own anakit server and its own step directory, and neither result may land in the other's file. Test: Task 7, `test_two_steps_at_once_use_two_servers_and_two_directories`.
2. A point rerun after a crash finds its step directory already holding an earlier run's files: the rerun must start from an empty directory, so no stale nts file is reported as this run's. Test: Task 7, `test_submit_empties_a_step_directory_left_by_an_earlier_run`.
3. anakit answers `success` but its metadata lacks a declared metric, or carries one as a string: `results` must raise a `ContractError` naming the metric, never a `KeyError` or a silently missing objective. Test: Task 7, `test_results_refuses_a_missing_or_non_number_metric`.
4. A Level 1 harvest directory whose `summary.json` lacks `ce_abs_eff` or `s_over_sqrt_b`, or has no `nts.ce.root`, or is unreadable: it must be counted as skipped with its reason, never crash the run or vanish from the report. Test: Task 10, `test_level1_inputs_counts_every_skip_with_its_reason`.
5. An EdepAna summary with more than 1e6 events printed at full precision: anakit's `edep` parser must read the exact integers and all 15 significant figures. Test: Task 4, `test_edep_reads_a_full_precision_summary`.

---

### Task 1: The anakit fork, the MDC2025ax work area, and the gate

Set up the two external code bases and prove the design's two assumptions before any code depends on them: Mu2eOptAna builds on p107, and its EdepAna reads the archived Run1Bap-written CeEndpoint and EarlyEleBeamFlash files. **If either fails, stop and report BLOCKED with the first error; do not work around it.**

**Files:**
- Create (outside autoresearch): `/exp/mu2e/app/users/oksuzian/analysis-mcp-server` (git clone), `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax` (muse work area)
- Modify: `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/Mu2eOptAna/src/EdepAna_module.cc` (summary block)

**Interfaces:**
- Produces: the fork checkout (branch `autoresearch` at `039e969`, suite green); the work area with `backing` → `/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax`, `Mu2eOptAna/` on branch `autoresearch` with one commit on `3d8ba5a`, a p107 build of `libmu2eoptana_EdepAna_module.so`, and `data/heeck_finer_binning_2016_szafron.tbl`.

- [ ] **Step 1: Check that neither target exists**

```bash
ls -d /exp/mu2e/app/users/oksuzian/analysis-mcp-server /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax 2>&1
```
Expected: two `No such file or directory` lines. If either exists, STOP and report it (never overwrite).

- [ ] **Step 2: Clone the fork and pin its base**

```bash
git clone https://github.com/michaelmackenzie/analysis-mcp-server.git /exp/mu2e/app/users/oksuzian/analysis-mcp-server
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
git checkout -b autoresearch 039e969
git log --oneline -1
```
Expected: `039e969 Update to handle ROOT file lists`.

- [ ] **Step 3: Run the fork's suite as the baseline**

```bash
mkdir -p /exp/mu2e/data/users/oksuzian/claude-scratch/tmp
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
TMPDIR=/exp/mu2e/data/users/oksuzian/claude-scratch/tmp PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python tests/test_tools.py | tail -3
```
Expected: last line `0 failure(s)`.

- [ ] **Step 4: Create the work area on SimJob MDC2025ax and clone Mu2eOptAna**

```bash
mkdir /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax
cd /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax
env -u MUSE_WORK_DIR bash -c 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh && muse backing SimJob MDC2025ax'
readlink backing
git clone https://github.com/michaelmackenzie/Mu2eOptAna.git
cd Mu2eOptAna && git checkout -b autoresearch 3d8ba5a && git log --oneline -1
```
Expected: `readlink` prints `/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax`; the log shows `3d8ba5a`. If `muse backing` reports an unknown command, create the link with `ln -s /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax backing` and say so in the report. If GitHub has no commit `3d8ba5a`, STOP and report.

- [ ] **Step 5: Patch the EdepAna summary to full precision**

In `Mu2eOptAna/src/EdepAna_module.cc`, the `endJob` summary block starts with `std::cout` followed by `<< "EdepAna summary:\n"` and ends with the `per gen event` tracker line's `<< std::endl;`. Wrap it so it prints at 15 significant figures and restores the stream afterwards:

```cpp
    // Full precision: at the default 6 significant figures the per-gen-event
    // tracker average (flash per POT) is off by up to 5e-6 relative, and an
    // event count above 1e6 prints in scientific notation.
    const std::streamsize old_precision = std::cout.precision(15);
    std::cout
      << "EdepAna summary:\n"
      << "  Saw " << total_events_ << " events" << " (" << ngen_ << " gen events) --> output rate = "
      << eventRate << " events / gen event" << std::endl
      << "  Average calo energy deposition per event: " << averageCaloEdep << " MeV" << std::endl
      << "  Average calo energy deposition per gen event: " << averageCaloEdepGen << " MeV" << std::endl
      << "  Events with calo Edep > 50 MeV: " << events_above_50_mev_ << std::endl
      << "  Average tracker energy deposition per event: " << averageTrkEdep << " MeV" << std::endl
      << "  Average tracker energy deposition per gen event: " << averageTrkEdepGen << " MeV" << std::endl;
    std::cout.precision(old_precision);
```
Keep the seven `<<` lines exactly as they are at `3d8ba5a` (if they differ from the text above, keep the checked-out text and add only the comment and the two `precision` lines).

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/Mu2eOptAna
git add src/EdepAna_module.cc
git commit -m "EdepAna summary: print at full precision

At the default 6 significant figures the per-gen-event tracker average is
off by up to 5e-6 relative, and an event count above 1e6 prints in
scientific notation.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

- [ ] **Step 6: Build on p107**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax
env -u MUSE_WORK_DIR SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER bash -c 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh && muse setup && muse status && muse build -j4' 2>&1 | tail -30
ls build/*/Mu2eOptAna/lib/
```
Expected: `muse status` names envset p107; the build ends without errors; `ls` shows a build directory whose name contains `p107` holding `libmu2eoptana_EdepAna_module.so`. On a compile error, STOP and report BLOCKED with the first error line.

- [ ] **Step 7: Copy the DIO table (a disk file, not tape)**

```bash
mkdir /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/data
cp /exp/mu2e/app/users/oksuzian/autoresearch_muse/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/data/
md5sum /exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/data/heeck_finer_binning_2016_szafron.tbl
```
Expected: `be9d67e140645faff63440fb138a2faa`.

- [ ] **Step 8: The gate — EdepAna and the counts on one archived file per stage**

Run the unchanged fork's standard analyses in-process against the new work area:

```bash
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
TMPDIR=/exp/mu2e/data/users/oksuzian/claude-scratch/tmp PYTHONPATH=$PWD /cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python - <<'EOF'
from tools import run_analysis
from tools.mu2e_env import Mu2eEnv, configure
configure(Mu2eEnv.for_work_area("/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax"))
S = "/exp/mu2e/data/users/oksuzian/gridtest/autoresearch_grid/gridphaseA01/state"
OUT = "/exp/mu2e/data/users/oksuzian/claude-scratch/c2b_gate"
first = lambda stage: open(f"{S}/{stage}_outputs.txt").readline().strip()
for analysis, stage, params in (("edep", "mustops_ce", None),
                                ("edep", "elebeam_flash", None),
                                ("count", "mubeam", {"prescale_filter": "TargetStopPrescaleFilter"})):
    r = run_analysis(analysis=analysis, output_dir=f"{OUT}/{stage}",
                     data_files=[first(stage)], parameters=params, timeout_s=1800)
    print(stage, r.status, r.message)
    print({k: v for k, v in r.metadata.items() if k.startswith(("n_", "avg_", "prescale"))})
EOF
grep "per gen event" /exp/mu2e/data/users/oksuzian/claude-scratch/c2b_gate/elebeam_flash/mu2e.log
```
Expected:
- `mustops_ce success`, `n_events` 39175.0, `n_gen_events` 75000.0;
- `elebeam_flash success`, `n_events` 78.0, `n_gen_events` 110000.0, and the grep shows the tracker `per gen event` value with more than 6 significant digits;
- `mubeam success`, `n_events` 6519.0, `n_gen_events` 200000.0, `prescale` 1.0.

Any `error` status (for example a missing `CaloClusterMaker` collection in the early-flash file, or a library that will not load): STOP, report BLOCKED with the message and the `mu2e.log` tail.

- [ ] **Step 9: Report**

Report: the fork HEAD, the Mu2eOptAna commit SHA, the library path, and the three gate lines. Nothing in autoresearch changes in this task.

---

### Task 2: `approx_ce_sensitivity` takes the DIO table and fraction (fork)

**Files:**
- Modify: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tools/analyses/approx_ce_sensitivity.py`
- Test: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tests/test_tools.py`

**Interfaces:**
- Produces: `compute(nts_path: Path, outdir: Path, *, sig_eff: float, npot: float, mean_pot_per_event: float, cosmic_rate_per_s_per_mev: float, dio_table: Path = DIO_TABLE, dio_fraction: float = 1.0 - MUON_CAPTURE_RATE) -> RunOutcome` (Task 3 calls it); two new optional parameters `dio_table` (text, default `str(DIO_TABLE)`) and `dio_fraction` (number in [0, 1], default `1 - 0.609`); `extra["dio_table"]` and `extra["dio_fraction"]` in every successful result. Test helper `_write_nts(path, *, signal_at=104.0, loss=-1.0, n=1000) -> Path` in `tests/test_tools.py` (Tasks 3 and 4 reuse it).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`, just above the line `# --- the registry (loops over every analysis) --------------------------------`:

```python
# --- approx_ce_sensitivity: the DIO table and fraction ------------------------

def _write_nts(path, *, signal_at=104.0, loss=-1.0, n=1000):
    """A minimal EdepAna-shaped ROOT file: the two hist_2 histograms the
    sensitivity scan reads, each filled with n entries."""
    import uproot
    with uproot.recreate(path) as f:
        f[f"{sens.HIST_DIR}/{sens.SIGNAL_HIST}"] = np.histogram(
            np.full(n, signal_at), bins=1500, range=(0.0, 150.0))
        f[f"{sens.HIST_DIR}/{sens.RESPONSE_HIST}"] = np.histogram(
            np.full(n, loss), bins=500, range=(-100.0, 0.0))
    return Path(path)


def test_sensitivity_dio_parameters_default_to_todays_behaviour():
    ce = list_analyses().metadata["analyses"]["approx_ce_sensitivity"]
    table = ce["parameters"]["dio_table"]
    fraction = ce["parameters"]["dio_fraction"]
    assert table["required"] is False
    assert table["default"] == str(sens.DIO_TABLE)
    assert fraction["required"] is False
    assert fraction["default"] == 1.0 - sens.MUON_CAPTURE_RATE


def test_sensitivity_dio_background_scales_with_dio_fraction(tmp_dir):
    nts = _write_nts(Path(tmp_dir) / "nts.root")
    got = {}
    for fraction in (0.2, 0.4):
        result = run_analysis(
            analysis="approx_ce_sensitivity", data_file=str(nts),
            output_dir=str(Path(tmp_dir) / f"f{fraction}"),
            parameters={"sig_eff": 0.01, "dio_fraction": fraction})
        assert result.status == "success", result.message
        assert result.metadata["dio_fraction"] == fraction
        got[fraction] = result.metadata
    low, high = got[0.2], got[0.4]
    assert (low["signal_box_low_mev"], low["signal_box_high_mev"]) == \
        (high["signal_box_low_mev"], high["signal_box_high_mev"]), (low, high)
    assert low["dio_background"] > 0.0, low
    assert abs(high["dio_background"] / low["dio_background"] - 2.0) < 1e-9


def test_sensitivity_reports_a_missing_dio_table(tmp_dir):
    nts = _write_nts(Path(tmp_dir) / "nts.root")
    missing = Path(tmp_dir) / "no_such.tbl"
    result = run_analysis(
        analysis="approx_ce_sensitivity", data_file=str(nts),
        output_dir=str(Path(tmp_dir) / "out"),
        parameters={"sig_eff": 0.01, "dio_table": str(missing)})
    assert result.status == "error"
    assert "DIO spectrum table not found" in result.message, result.message


def test_compute_is_what_run_computes(tmp_dir):
    nts = _write_nts(Path(tmp_dir) / "nts.root")
    via_tool = run_analysis(
        analysis="approx_ce_sensitivity", data_file=str(nts),
        output_dir=str(Path(tmp_dir) / "a"), parameters={"sig_eff": 0.01})
    direct = sens.compute(
        nts, Path(tmp_dir) / "b", sig_eff=0.01, npot=sens.NPOT,
        mean_pot_per_event=sens.MEAN_POT_PER_EVENT,
        cosmic_rate_per_s_per_mev=sens.COSMIC_RATE_PER_SECOND_PER_MEV,
        dio_table=sens.DIO_TABLE, dio_fraction=1.0 - sens.MUON_CAPTURE_RATE)
    assert direct.error is None, direct.error
    assert direct.metrics["sensitivity"] == via_tool.metadata["sensitivity"]
    assert direct.extra["dio_table"] == str(sens.DIO_TABLE)
```

- [ ] **Step 2: Run the suite and see the four new tests fail**

Run the anakit suite command from Global Constraints.
Expected: `FAIL`/`ERROR` for the four new tests (no `dio_table` parameter; no `compute`), the rest `ok`.

- [ ] **Step 3: Split `run` into `compute` and add the parameters**

In `tools/analyses/approx_ce_sensitivity.py`:

1. Replace the line `def run(context: RunContext) -> RunOutcome:` and its docstring, the four `context.params[...]` reads and the two lines `outdir = context.outdir` / `outdir.mkdir(parents=True, exist_ok=True)` with:

```python
def compute(nts_path: Path, outdir: Path, *, sig_eff: float, npot: float,
            mean_pot_per_event: float, cosmic_rate_per_s_per_mev: float,
            dio_table: Path = DIO_TABLE,
            dio_fraction: float = 1.0 - MUON_CAPTURE_RATE) -> RunOutcome:
    """The window scan on one EdepAna ROOT file. `run` is this with the
    analysis' parameters; `ce_sensitivity` calls it on the file its own
    EdepAna job wrote."""
    import uproot

    outdir.mkdir(parents=True, exist_ok=True)
```

2. In the body now under `compute`, change `with uproot.open(context.input_path) as rootfile:` to `with uproot.open(nts_path) as rootfile:`.

3. Change the DIO line
```python
        dio_true = load_dio_spectrum().scaled((1. - MUON_CAPTURE_RATE) * sig_eff * npot)
```
to
```python
        dio_true = load_dio_spectrum(dio_table).scaled(dio_fraction * sig_eff * npot)
```

4. In the log `lines`, change `f"  input            {context.input_path}",` to `f"  input            {nts_path}",` and add, right after the `cosmic rate` entry:
```python
        f"  DIO              {dio_table} (fraction {dio_fraction:g})",
```

5. In the returned `extra`, replace `"dio_table": str(DIO_TABLE),` with:
```python
            "dio_table": str(dio_table),
            "dio_fraction": dio_fraction,
```

6. Add the new `run` right after `compute`:
```python
def run(context: RunContext) -> RunOutcome:
    """Compute the approximate CE sensitivity for one EdepAna ROOT file."""
    params = context.params
    return compute(
        context.input_path, context.outdir,
        sig_eff=params["sig_eff"], npot=params["npot"],
        mean_pot_per_event=params["mean_pot_per_event"],
        cosmic_rate_per_s_per_mev=params["cosmic_rate_per_s_per_mev"],
        dio_table=Path(params["dio_table"]),
        dio_fraction=params["dio_fraction"],
    )
```

7. Append two entries to `SPEC.parameters` (after `cosmic_rate_per_s_per_mev`):
```python
        ParamSpec(
            name="dio_table",
            description="The DIO spectrum table: (energy, weight) rows on a "
                        "0.01 MeV grid. The default is the Heeck/Szafron "
                        "table this analysis has always read.",
            default=str(DIO_TABLE),
            kind="text",
        ),
        ParamSpec(
            name="dio_fraction",
            description="Fraction of stopped muons that decay in orbit, "
                        "normalizing the DIO spectrum. The default is 1 minus "
                        "the capture rate (0.391); the original macro used "
                        "0.39.",
            default=1.0 - MUON_CAPTURE_RATE, minimum=0.0, maximum=1.0,
        ),
```

- [ ] **Step 4: Run the suite**

Run the anakit suite command. Expected: `0 failure(s)`.

- [ ] **Step 5: Commit (in the fork)**

```bash
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
git add tools/analyses/approx_ce_sensitivity.py tests/test_tools.py
git commit -m "approx_ce_sensitivity: DIO table and fraction as parameters; compute()

compute() is the scan on one nts file, callable by another analysis; run()
is compute() with the analysis' parameters. dio_table and dio_fraction
default to today's behaviour.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 3: The `ce_sensitivity` analysis (fork)

**Files:**
- Create: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tools/analyses/ce_sensitivity.py`
- Modify: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tools/registry.py` (`_ANALYSIS_MODULES`)
- Test: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tests/test_tools.py`

**Interfaces:**
- Consumes: `approx_ce_sensitivity.compute(...)` (Task 2); `count.run_counts_job(context, filter_label) -> RunOutcome` (metrics `n_events`, `n_gen_events`, `prescale`); `edep.run(context) -> RunOutcome` (metrics per `edep.SPEC.metrics`, `files` = the ROOT files written); `_write_nts` (Task 2).
- Produces: analysis `ce_sensitivity` (input `art_files`; required parameters `input_correction`, `cosmic_rate_per_s_per_mev`, `dio_fraction`, `dio_table`); metrics in this order: `s_over_sqrt_b, ce_abs_eff, ce_seen, ce_simulated_events, muminus_stops, mubeam_sim_total, prescale, signal_box_low_mev, signal_box_high_mev, signal_rate, dio_background, cosmic_background`. Module functions `split_inputs(paths) -> (stops, ce)`, `ce_efficiency(*, input_correction, muminus_stops, mubeam_sim_total, prescale, ce_seen, ce_simulated_events) -> float`, `assemble_metrics(counts, ce, scan, efficiency) -> dict`; module attributes `count_job`, `edep_job` (tests replace them). Job subdirectories under `output_dir`: `count/`, `edep/`, `sensitivity/`.

- [ ] **Step 1: Write the failing tests**

Add near the top imports of `tests/test_tools.py`:
```python
from tools.analyses import ce_sensitivity as cs
from tools.spec import RunOutcome
```

Add `"ce_sensitivity": SAMPLE_EDEP_STDOUT,` to the `SAMPLE_STDOUT` dict.

In `test_every_art_analysis_parser_matches_its_declared_metrics`, add a branch after the `muon_stop_rate` one:
```python
        elif name == "ce_sensitivity":
            counts = parse_counts(SAMPLE_COUNTS_STDOUT, PRESCALE_FILTER)
            scan = {m: 1.0 for m in ANALYSES["approx_ce_sensitivity"].metrics}
            assembled = cs.assemble_metrics(
                counts, parse_edep_summary(sample), scan, 1e-4)
            assert tuple(assembled) == spec.metrics
```

Add a section above `# --- the registry (loops over every analysis) ---`:

```python
# --- ce_sensitivity ----------------------------------------------------------

CE_PARAMS = {"input_correction": 0.01278168,
             "cosmic_rate_per_s_per_mev": 2e4 / 1.1e7,
             "dio_fraction": 0.39, "dio_table": str(sens.DIO_TABLE)}


def _art(tmp_dir, name):
    path = Path(tmp_dir) / name
    path.write_text("")
    return path


def _ce_inputs(tmp_dir):
    return [_art(tmp_dir, "sim.t.TargetStops.c.001800_00000000.art"),
            _art(tmp_dir, "sim.t.TargetStops.c.001800_00000001.art"),
            _art(tmp_dir, "dts.t.CeEndpoint.c.001801_00000000.art")]


def _fake_ce_jobs(*, count_error=None, edep_error=None, root_files=1):
    """Stand-ins for ce_sensitivity's two mu2e jobs, with gridphaseA01's
    counts. Returns (calls, restore)."""
    calls = []

    def count_job(context, filter_label):
        calls.append(("count", sorted(p.name for p in context.input_paths),
                      filter_label, context.outdir.name,
                      context.wants_file_list))
        if count_error:
            return RunOutcome(error=count_error)
        return RunOutcome(
            metrics={"n_events": 97520.0, "n_gen_events": 3.0e6,
                     "prescale": 1.0},
            log_path=context.outdir / "mu2e.log", extra={})

    def edep_job(context):
        calls.append(("edep", sorted(p.name for p in context.input_paths),
                      None, context.outdir.name, context.wants_file_list))
        if edep_error:
            return RunOutcome(error=edep_error)
        context.outdir.mkdir(parents=True, exist_ok=True)
        files = [str(_write_nts(context.outdir / f"nts{i}.root"))
                 for i in range(root_files)]
        metrics = {**parse_edep_summary(SAMPLE_EDEP_STDOUT),
                   "n_events": 588681.0, "n_gen_events": 1.125e6}
        return RunOutcome(metrics=metrics, files=files,
                          log_path=context.outdir / "mu2e.log", extra={})

    saved = (cs.count_job, cs.edep_job)
    cs.count_job, cs.edep_job = count_job, edep_job

    def restore():
        cs.count_job, cs.edep_job = saved
    return calls, restore


def test_ce_sensitivity_splits_its_inputs_by_stream(tmp_dir):
    stops, ce = cs.split_inputs(_ce_inputs(tmp_dir))
    assert [p.name for p in stops] == [
        "sim.t.TargetStops.c.001800_00000000.art",
        "sim.t.TargetStops.c.001800_00000001.art"]
    assert [p.name for p in ce] == ["dts.t.CeEndpoint.c.001801_00000000.art"]


def test_ce_sensitivity_refuses_a_file_of_another_stream_or_a_missing_one(tmp_dir):
    inputs = _ce_inputs(tmp_dir)
    other = _art(tmp_dir, "dts.t.EarlyEleBeamFlash.c.001803_00000000.art")
    for paths, needle in ((inputs + [other], "EarlyEleBeamFlash"),
                          (inputs[:2], "no CeEndpoint file"),
                          (inputs[2:], "no TargetStops file")):
        try:
            cs.split_inputs(paths)
        except cs.InputError as exc:
            assert needle in str(exc), exc
        else:
            raise AssertionError(f"accepted {[p.name for p in paths]}")


def test_ce_efficiency_is_the_pipelines_formula():
    # gridphaseA01's harvest (summary.json): 2.174141844862464e-4
    eff = cs.ce_efficiency(input_correction=0.01278168, muminus_stops=97520,
                           mubeam_sim_total=3.0e6, prescale=1.0,
                           ce_seen=588681, ce_simulated_events=1.125e6)
    assert abs(eff / 2.174141844862464e-4 - 1.0) < 1e-12, eff


def test_ce_efficiency_divides_out_the_prescale():
    base = dict(input_correction=0.01, muminus_stops=100, mubeam_sim_total=1e5,
                ce_seen=500, ce_simulated_events=1000)
    full = cs.ce_efficiency(prescale=1.0, **base)
    tenth = cs.ce_efficiency(prescale=0.1, **base)
    assert abs(tenth / full - 10.0) < 1e-12


def test_ce_efficiency_refuses_zero_counts_and_an_efficiency_above_one():
    base = dict(input_correction=0.01, muminus_stops=100, mubeam_sim_total=1e5,
                prescale=1.0, ce_seen=500, ce_simulated_events=1000)
    for key in ("muminus_stops", "mubeam_sim_total", "prescale", "ce_seen",
                "ce_simulated_events"):
        try:
            cs.ce_efficiency(**{**base, key: 0})
        except cs.InputError as exc:
            assert key in str(exc), exc
        else:
            raise AssertionError(f"accepted {key}=0")
    try:
        cs.ce_efficiency(**{**base, "input_correction": 1e6})
    except cs.InputError as exc:
        assert "outside (0, 1]" in str(exc), exc
    else:
        raise AssertionError("accepted an efficiency above 1")


def test_ce_sensitivity_runs_both_jobs_then_the_scan(tmp_dir):
    calls, restore = _fake_ce_jobs()
    try:
        result = run_analysis(analysis="ce_sensitivity",
                              data_files=[str(p) for p in _ce_inputs(tmp_dir)],
                              output_dir=str(Path(tmp_dir) / "out"),
                              parameters=CE_PARAMS)
    finally:
        restore()
    assert result.status == "success", result.message
    assert calls == [
        ("count", ["sim.t.TargetStops.c.001800_00000000.art",
                   "sim.t.TargetStops.c.001800_00000001.art"],
         "TargetStopPrescaleFilter", "count", True),
        ("edep", ["dts.t.CeEndpoint.c.001801_00000000.art"], None, "edep", True),
    ], calls
    meta = result.metadata
    assert abs(meta["ce_abs_eff"] / 2.174141844862464e-4 - 1.0) < 1e-12
    assert (meta["muminus_stops"], meta["mubeam_sim_total"], meta["ce_seen"],
            meta["ce_simulated_events"]) == (97520.0, 3.0e6, 588681.0, 1.125e6)
    assert meta["s_over_sqrt_b"] > 0.0
    assert meta["sensitivity"]["dio_fraction"] == 0.39
    assert any(f.endswith("nts0.root") for f in result.files), result.files


def test_ce_sensitivity_reports_which_job_failed(tmp_dir):
    for kwargs, needle in (({"count_error": "mu2e exited 1"},
                            "counting the TargetStops files: mu2e exited 1"),
                           ({"edep_error": "mu2e exited 2"},
                            "EdepAna on the CeEndpoint files: mu2e exited 2"),
                           ({"root_files": 2}, "wrote 2 ROOT files")):
        calls, restore = _fake_ce_jobs(**kwargs)
        try:
            result = run_analysis(
                analysis="ce_sensitivity",
                data_files=[str(p) for p in _ce_inputs(tmp_dir)],
                output_dir=str(Path(tmp_dir) / "out"), parameters=CE_PARAMS)
        finally:
            restore()
        assert result.status == "error", kwargs
        assert needle in result.message, result.message


def test_ce_sensitivity_refuses_max_events(tmp_dir):
    calls, restore = _fake_ce_jobs()
    try:
        result = run_analysis(analysis="ce_sensitivity",
                              data_files=[str(p) for p in _ce_inputs(tmp_dir)],
                              output_dir=str(Path(tmp_dir) / "out"),
                              parameters=CE_PARAMS, max_events=10)
    finally:
        restore()
    assert result.status == "error"
    assert "max_events" in result.message
    assert calls == []


def test_ce_sensitivity_needs_every_parameter():
    params = list_analyses().metadata["analyses"]["ce_sensitivity"]["parameters"]
    assert sorted(params) == sorted(CE_PARAMS)
    assert all(p["required"] for p in params.values()), params
```

- [ ] **Step 2: Run the suite and see the new tests fail**

Run the anakit suite command. Expected: `ERROR` at import (`cannot import name 'ce_sensitivity'`), since the whole file imports it.

- [ ] **Step 3: Write the analysis**

Create `tools/analyses/ce_sensitivity.py`:

```python
"""CE sensitivity from one configuration's own files: autoresearch's sob.

The whole chain behind S/sqrt(B) for a stopping-target configuration, as
one analysis over the files its simulation wrote:

1. `count` (print_counts.fcl) over the target-stop files
   (sim.*.TargetStops.*.art): the mu- stops they hold, the MuBeam events
   generated to make them, and the target-stop prescale.
2. EdepAna (edep.fcl) over the CE files (dts.*.CeEndpoint.*.art): the CE
   events seen, the CE events generated, and the nts ROOT file.
3. The absolute CE efficiency,

       ce_abs_eff = input_correction
                    * muminus_stops / (mubeam_sim_total * prescale)
                    * ce_seen / ce_simulated_events

   where input_correction is the generated MuBeam events per POT upstream
   of the stops' stage.
4. approx_ce_sensitivity's window scan on that nts file, with
   sig_eff = ce_abs_eff and the caller's cosmic rate, DIO fraction and DIO
   table.

One analysis, not four chained ones: the efficiency needs numbers from both
jobs, and the files of both upstream stages arrive as one list. The
denominators are the files' own generated-event counts (each file's SubRuns
carry its job's GenEventCount), so no events-per-job number has to travel
with them.
"""

import time
from pathlib import Path

from ..spec import AnalysisSpec, ParamSpec, RunContext, RunOutcome
from . import approx_ce_sensitivity as sens
from . import edep
from .count import run_counts_job

STOPS_TAG = ".TargetStops."
CE_TAG = ".CeEndpoint."
PRESCALE_FILTER = "TargetStopPrescaleFilter"

# The two mu2e jobs, as module attributes so the tests can stand in for them.
count_job = run_counts_job
edep_job = edep.run

# Reported in this order; the first is the figure of merit.
METRICS = (
    "s_over_sqrt_b", "ce_abs_eff", "ce_seen", "ce_simulated_events",
    "muminus_stops", "mubeam_sim_total", "prescale",
    "signal_box_low_mev", "signal_box_high_mev", "signal_rate",
    "dio_background", "cosmic_background",
)


class InputError(ValueError):
    """Inputs or counts this analysis cannot turn into an efficiency."""


def split_inputs(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """(target-stop files, CE files), by the Mu2e file name's description.
    Any other file, or an empty group, is an InputError naming it."""
    stops = [p for p in paths if STOPS_TAG in p.name]
    ce = [p for p in paths if CE_TAG in p.name]
    other = [p.name for p in paths
             if STOPS_TAG not in p.name and CE_TAG not in p.name]
    problems = []
    if other:
        problems.append("file(s) neither TargetStops nor CeEndpoint: "
                        + ", ".join(other))
    if not stops:
        problems.append("no TargetStops file (a name containing "
                        f"'{STOPS_TAG}')")
    if not ce:
        problems.append(f"no CeEndpoint file (a name containing '{CE_TAG}')")
    if problems:
        raise InputError("; ".join(problems))
    return stops, ce


def ce_efficiency(*, input_correction: float, muminus_stops: float,
                  mubeam_sim_total: float, prescale: float, ce_seen: float,
                  ce_simulated_events: float) -> float:
    """The absolute CE efficiency (module docstring, step 3)."""
    for name, value in (("muminus_stops", muminus_stops),
                        ("mubeam_sim_total", mubeam_sim_total),
                        ("prescale", prescale), ("ce_seen", ce_seen),
                        ("ce_simulated_events", ce_simulated_events)):
        if not value > 0.0:
            raise InputError(f"{name} is {value:g}: the efficiency needs "
                             f"every count > 0")
    efficiency = (input_correction * muminus_stops
                  / (mubeam_sim_total * prescale)
                  * ce_seen / ce_simulated_events)
    if not 0.0 < efficiency <= 1.0:
        raise InputError(f"CE efficiency {efficiency:g} is outside (0, 1]")
    return efficiency


def assemble_metrics(counts: dict, ce: dict, scan: dict,
                     efficiency: float) -> dict[str, float]:
    """The reported metrics, in METRICS order: the count job's counts,
    EdepAna's on the CE files, the scan's, and the efficiency."""
    return {
        "s_over_sqrt_b": scan["sensitivity"],
        "ce_abs_eff": efficiency,
        "ce_seen": ce["n_events"],
        "ce_simulated_events": ce["n_gen_events"],
        "muminus_stops": counts["n_events"],
        "mubeam_sim_total": counts["n_gen_events"],
        "prescale": counts["prescale"],
        "signal_box_low_mev": scan["signal_box_low_mev"],
        "signal_box_high_mev": scan["signal_box_high_mev"],
        "signal_rate": scan["signal_rate"],
        "dio_background": scan["dio_background"],
        "cosmic_background": scan["cosmic_background"],
    }


def run(context: RunContext) -> RunOutcome:
    try:
        stops, ce_files = split_inputs(context.input_paths)
    except InputError as exc:
        return RunOutcome(error=str(exc))
    if context.max_events is not None:
        return RunOutcome(error=(
            "max_events would leave the generated-event counts covering "
            "events the jobs never read; the efficiency needs every event"))
    params = context.params
    # One budget for both jobs: the caller's timeout covers the analysis.
    deadline = time.monotonic() + context.timeout_s

    def job(paths: list[Path], name: str) -> RunContext:
        return RunContext(
            input_paths=paths, outdir=context.outdir / name, params={},
            timeout_s=max(1, int(deadline - time.monotonic())),
            wants_file_list=True)

    counts = count_job(job(stops, "count"), PRESCALE_FILTER)
    extra = {"count": counts.extra,
             "count_log": str(counts.log_path) if counts.log_path else None}
    if counts.error is not None:
        return RunOutcome(error=f"counting the TargetStops files: {counts.error}",
                          log_path=counts.log_path, extra=extra)

    ce = edep_job(job(ce_files, "edep"))
    extra.update(edep=ce.extra,
                 edep_log=str(ce.log_path) if ce.log_path else None)
    if ce.error is not None:
        return RunOutcome(error=f"EdepAna on the CeEndpoint files: {ce.error}",
                          files=ce.files, log_path=ce.log_path, extra=extra)
    if len(ce.files) != 1:
        return RunOutcome(
            error=(f"EdepAna wrote {len(ce.files)} ROOT files, expected one "
                   f"nts file: {ce.files}"),
            files=ce.files, log_path=ce.log_path, extra=extra)

    try:
        efficiency = ce_efficiency(
            input_correction=params["input_correction"],
            muminus_stops=counts.metrics["n_events"],
            mubeam_sim_total=counts.metrics["n_gen_events"],
            prescale=counts.metrics["prescale"],
            ce_seen=ce.metrics["n_events"],
            ce_simulated_events=ce.metrics["n_gen_events"])
    except InputError as exc:
        return RunOutcome(error=str(exc), files=ce.files,
                          log_path=ce.log_path, extra=extra)

    scan = sens.compute(
        Path(ce.files[0]), context.outdir / "sensitivity",
        sig_eff=efficiency, npot=sens.NPOT,
        mean_pot_per_event=sens.MEAN_POT_PER_EVENT,
        cosmic_rate_per_s_per_mev=params["cosmic_rate_per_s_per_mev"],
        dio_table=Path(params["dio_table"]),
        dio_fraction=params["dio_fraction"])
    extra["sensitivity"] = scan.extra
    files = ce.files + scan.files
    if scan.error is not None:
        return RunOutcome(error=f"sensitivity scan: {scan.error}", files=files,
                          log_path=scan.log_path or ce.log_path, extra=extra)
    return RunOutcome(
        metrics=assemble_metrics(counts.metrics, ce.metrics, scan.metrics,
                                 efficiency),
        files=files, log_path=scan.log_path, extra=extra)


def summarize(metrics: dict[str, float]) -> str:
    return (
        f"S/sqrt(B) = {metrics['s_over_sqrt_b']:.4g} at CE efficiency "
        f"{metrics['ce_abs_eff']:.4g} ({metrics['muminus_stops']:g} stops "
        f"from {metrics['mubeam_sim_total']:g} generated, "
        f"{metrics['ce_seen']:g} of {metrics['ce_simulated_events']:g} CE "
        f"events seen)."
    )


SPEC = AnalysisSpec(
    name="ce_sensitivity",
    fcl=edep.FCL,
    input_kind="art_files",
    run=run,
    description=(
        "CE S/sqrt(B) for one configuration from its own files: its mu- "
        "stops (TargetStops) and CE events (CeEndpoint), in one list, turned "
        "into an absolute CE efficiency and then approx_ce_sensitivity's "
        "window scan."
    ),
    metrics=METRICS,
    units={"signal_box_low_mev": "MeV", "signal_box_high_mev": "MeV"},
    parameters=(
        ParamSpec(
            name="input_correction",
            description="Generated MuBeam events per proton on target "
                        "upstream of the stops' stage (autoresearch: "
                        "0.01278168, the fraction of POT reaching the "
                        "MuBeamCat resampler input).",
            minimum=0.0, maximum=1.0,
        ),
        ParamSpec(
            name="cosmic_rate_per_s_per_mev",
            description="Cosmic background rate, flat in momentum, per "
                        "second per MeV/c (approx_ce_sensitivity's). "
                        "Required: the choice moves the answer by orders of "
                        "magnitude.",
            minimum=0.0,
        ),
        ParamSpec(
            name="dio_fraction",
            description="Fraction of stopped muons that decay in orbit "
                        "(approx_ce_sensitivity's dio_fraction).",
            minimum=0.0, maximum=1.0,
        ),
        ParamSpec(
            name="dio_table",
            description="The DIO spectrum table (approx_ce_sensitivity's "
                        "dio_table).",
            kind="text",
        ),
    ),
    summarize=summarize,
    input_hint=(
        "One configuration's target-stop files (sim.*.TargetStops.*.art) and "
        "CE files (dts.*.CeEndpoint.*.art), in one list. Each file's SubRuns "
        "must carry its job's GenEventCount, and the target-stop files the "
        "TargetStopPrescaleFilter product."
    ),
)
```

In `tools/registry.py`, change `_ANALYSIS_MODULES` to:
```python
_ANALYSIS_MODULES = ("edep", "count", "muon_stop_rate", "approx_ce_sensitivity",
                     "stop_materials", "ce_sensitivity")
```

- [ ] **Step 4: Run the suite**

Run the anakit suite command. Expected: `0 failure(s)`.

- [ ] **Step 5: Commit (in the fork)**

```bash
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
git add tools/analyses/ce_sensitivity.py tools/registry.py tests/test_tools.py
git commit -m "ce_sensitivity: S/sqrt(B) from one configuration's own files

Counts the target-stop files, runs EdepAna on the CE files, forms the
absolute CE efficiency from the files' own generated-event counts, and runs
approx_ce_sensitivity's scan on the nts file.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 4: The `flash_edep_per_pot` analysis (fork)

**Files:**
- Create: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tools/analyses/flash_edep_per_pot.py`
- Modify: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tools/registry.py`
- Test: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server/tests/test_tools.py`

**Interfaces:**
- Consumes: `edep.run(context)`, `edep.SPEC.metrics`, `edep.METRIC_UNITS`, `edep.FCL`.
- Produces: analysis `flash_edep_per_pot` (input `art_files`; required parameter `pot_per_electron`); metrics `("flash_edep_per_pot",) + edep.SPEC.metrics`; module function `flash_metrics(edep_metrics, pot_per_electron) -> dict`; module attribute `edep_job`.

- [ ] **Step 1: Write the failing tests**

Add near the top imports of `tests/test_tools.py`:
```python
from tools.analyses import flash_edep_per_pot as fl
```

Add `"flash_edep_per_pot": SAMPLE_EDEP_STDOUT,` to `SAMPLE_STDOUT`, and a branch in `test_every_art_analysis_parser_matches_its_declared_metrics`:
```python
        elif name == "flash_edep_per_pot":
            parsed = fl.flash_metrics(parse_edep_summary(sample), 1.0)
            assert tuple(parsed) == spec.metrics
```

Add a section above `# --- the registry (loops over every analysis) ---`:

```python
# --- flash_edep_per_pot ------------------------------------------------------

# What the patched EdepAna prints (setprecision(15)): a count above 1e6 in
# full, and every average to 15 significant figures.
SAMPLE_EDEP_FULL_PRECISION_STDOUT = """\
EdepAna summary:
  Saw 2709370 events (2925000 gen events) --> output rate = 0.926280341880342 events / gen event
  Average calo energy deposition per event: 12.3456789012345 MeV
  Average calo energy deposition per gen event: 11.4353290196581 MeV
  Events with calo Edep > 50 MeV: 42
  Average tracker energy deposition per event: 2.21651238766154e-06 MeV
  Average tracker energy deposition per gen event: 2.05303999999999e-06 MeV
Art has completed and will exit with status 0.
"""


def test_edep_reads_a_full_precision_summary():
    metrics = parse_edep_summary(SAMPLE_EDEP_FULL_PRECISION_STDOUT)
    assert metrics["n_events"] == 2709370.0
    assert metrics["n_gen_events"] == 2925000.0
    assert metrics["avg_trk_edep_per_gen_event_mev"] == 2.05303999999999e-06


def test_flash_metrics_divide_by_the_pot_per_electron():
    edep_metrics = parse_edep_summary(SAMPLE_EDEP_FULL_PRECISION_STDOUT)
    got = fl.flash_metrics(edep_metrics, 11.536718606512062)
    assert got["flash_edep_per_pot"] == 2.05303999999999e-06 / 11.536718606512062
    assert got["n_gen_events"] == 2925000.0


def _fake_flash_job(metrics=None, error=None):
    calls = []

    def edep_job(context):
        calls.append((sorted(p.name for p in context.input_paths),
                      context.wants_file_list))
        if error:
            return RunOutcome(error=error)
        return RunOutcome(
            metrics=metrics or parse_edep_summary(SAMPLE_EDEP_FULL_PRECISION_STDOUT),
            files=[], log_path=context.outdir / "mu2e.log", extra={})

    saved = fl.edep_job
    fl.edep_job = edep_job

    def restore():
        fl.edep_job = saved
    return calls, restore


def _flash_inputs(tmp_dir):
    return [str(_art(tmp_dir, f"dts.t.EarlyEleBeamFlash.c.001803_0000000{i}.art"))
            for i in range(2)]


def test_flash_edep_per_pot_runs_edepana_over_every_file(tmp_dir):
    calls, restore = _fake_flash_job()
    try:
        result = run_analysis(analysis="flash_edep_per_pot",
                              data_files=_flash_inputs(tmp_dir),
                              output_dir=str(Path(tmp_dir) / "out"),
                              parameters={"pot_per_electron": 11.536718606512062})
    finally:
        restore()
    assert result.status == "success", result.message
    assert calls == [(["dts.t.EarlyEleBeamFlash.c.001803_00000000.art",
                       "dts.t.EarlyEleBeamFlash.c.001803_00000001.art"], True)]
    assert result.metadata["flash_edep_per_pot"] == \
        2.05303999999999e-06 / 11.536718606512062


def test_flash_edep_per_pot_refuses_what_it_cannot_normalize(tmp_dir):
    zero_energy = {**parse_edep_summary(SAMPLE_EDEP_FULL_PRECISION_STDOUT),
                   "avg_trk_edep_per_gen_event_mev": 0.0}
    zero_gen = {**parse_edep_summary(SAMPLE_EDEP_FULL_PRECISION_STDOUT),
                "n_gen_events": 0.0}
    for kwargs, params, max_events, needle in (
            ({"metrics": zero_energy}, {"pot_per_electron": 11.5}, None,
             "zero tracker energy"),
            ({"metrics": zero_gen}, {"pot_per_electron": 11.5}, None,
             "0 generated events"),
            ({}, {"pot_per_electron": 0.0}, None, "pot_per_electron"),
            ({}, {"pot_per_electron": 11.5}, 10, "max_events"),
            ({"error": "mu2e exited 1"}, {"pot_per_electron": 11.5}, None,
             "mu2e exited 1")):
        calls, restore = _fake_flash_job(**kwargs)
        try:
            result = run_analysis(analysis="flash_edep_per_pot",
                                  data_files=_flash_inputs(tmp_dir),
                                  output_dir=str(Path(tmp_dir) / "out"),
                                  parameters=params, max_events=max_events)
        finally:
            restore()
        assert result.status == "error", (kwargs, params)
        assert needle in result.message, result.message
```

- [ ] **Step 2: Run the suite and see the new tests fail**

Run the anakit suite command. Expected: `ERROR` at import (`cannot import name 'flash_edep_per_pot'`).

- [ ] **Step 3: Write the analysis**

Create `tools/analyses/flash_edep_per_pot.py`:

```python
"""Tracker energy from the early beam flash, per proton on target.

EdepAna (edep.py) over the early-flash files gives the tracker StrawGasStep
ionizing energy per generated event. Each generated event is one resampled
beam electron, so dividing by `pot_per_electron` -- protons on target per
resampled electron, a property of the electron-beam dataset the files were
resampled from -- gives energy per POT.

The per-generated-event average needs every event of every file, so
max_events is refused.
"""

from ..spec import AnalysisSpec, ParamSpec, RunContext, RunOutcome
from . import edep

# The mu2e job, as a module attribute so the tests can stand in for it.
edep_job = edep.run


def flash_metrics(edep_metrics: dict[str, float],
                  pot_per_electron: float) -> dict[str, float]:
    """flash_edep_per_pot first, then EdepAna's own metrics."""
    return {
        "flash_edep_per_pot":
            edep_metrics["avg_trk_edep_per_gen_event_mev"] / pot_per_electron,
        **edep_metrics,
    }


def run(context: RunContext) -> RunOutcome:
    if context.max_events is not None:
        return RunOutcome(error=(
            "max_events would leave the generated-event counts covering "
            "events EdepAna never read; flash per POT needs every event"))
    pot_per_electron = float(context.params["pot_per_electron"])
    if not pot_per_electron > 0.0:
        return RunOutcome(
            error=f"pot_per_electron must be > 0, got {pot_per_electron:g}")

    outcome = edep_job(context)
    if outcome.error is not None:
        return outcome
    metrics = outcome.metrics
    if not metrics["n_gen_events"] > 0.0:
        return RunOutcome(error="the files report 0 generated events",
                          files=outcome.files, log_path=outcome.log_path,
                          extra=outcome.extra)
    if not metrics["avg_trk_edep_per_gen_event_mev"] > 0.0:
        return RunOutcome(
            error=(f"zero tracker energy in {metrics['n_events']:g} events "
                   f"from {metrics['n_gen_events']:g} generated: too few "
                   f"events reached the early-flash output"),
            files=outcome.files, log_path=outcome.log_path,
            extra=outcome.extra)
    return RunOutcome(metrics=flash_metrics(metrics, pot_per_electron),
                      files=outcome.files, log_path=outcome.log_path,
                      extra=outcome.extra)


def summarize(metrics: dict[str, float]) -> str:
    return (
        f"{metrics['flash_edep_per_pot']:.6g} MeV per POT in the tracker "
        f"({metrics['avg_trk_edep_per_gen_event_mev']:.6g} MeV per generated "
        f"event over {metrics['n_gen_events']:g} generated)."
    )


SPEC = AnalysisSpec(
    name="flash_edep_per_pot",
    fcl=edep.FCL,
    input_kind="art_files",
    run=run,
    description=(
        "Tracker (StrawGasStep) ionizing energy per proton on target from "
        "early-flash files: EdepAna's per-generated-event average divided by "
        "the protons on target per resampled electron."
    ),
    metrics=("flash_edep_per_pot",) + edep.SPEC.metrics,
    units={"flash_edep_per_pot": "MeV / POT", **edep.METRIC_UNITS},
    parameters=(
        ParamSpec(
            name="pot_per_electron",
            description="Protons on target per resampled beam electron, a "
                        "property of the electron-beam dataset (EleBeamCat: "
                        "25000000 / 2166994 = 11.5367).",
            minimum=0.0,
        ),
    ),
    summarize=summarize,
    input_hint=(
        "Early-flash art files (dts.*.EarlyEleBeamFlash.*.art) whose SubRuns "
        "carry the resampling job's GenEventCount."
    ),
)
```

In `tools/registry.py`, add `"flash_edep_per_pot"` to the end of `_ANALYSIS_MODULES`.

- [ ] **Step 4: Run the suite**

Run the anakit suite command. Expected: `0 failure(s)`.

- [ ] **Step 5: Commit (in the fork)**

```bash
cd /exp/mu2e/app/users/oksuzian/analysis-mcp-server
git add tools/analyses/flash_edep_per_pot.py tools/registry.py tests/test_tools.py
git commit -m "flash_edep_per_pot: tracker energy per POT from early-flash files

EdepAna's per-generated-event tracker average divided by the protons on
target per resampled electron.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 5: `${ARTIFACT}/` in a step's `fixed` values

**Files:**
- Modify: `core/study.py` (`_expand` → public `expand_artifact`; `_steps`)
- Modify: `core/scheduler.py` (imports; `step_params`)
- Test: `tests/test_study_engine.py`

**Interfaces:**
- Produces: `study.expand_artifact(value, where) -> value` (the renamed `_expand`, same behaviour); `Step.fixed` keeps raw values; `scheduler.step_params` returns fixed values expanded.

- [ ] **Step 1: Write the failing tests**

In `tests/test_study_engine.py`, add `import scheduler  # noqa: E402` after `import paths  # noqa: E402`, and add this class at the end, before `if __name__ == "__main__":` (or at the end of the file if it has none):

```python
class TestFixedPaths(_Tmp):
    """A step's fixed path follows the kit-settings rule: '${ARTIFACT}/'
    expands when the step's params are built, a personal user area and any
    other token are refused at load, and measure_basis keeps the raw value
    (C2b spec, section 4)."""

    RAW = "${ARTIFACT}/c2b/table.tbl"

    def doc(self, value):
        doc = toy_doc(layout="v2")
        doc["evaluate"][0]["fixed"]["fail"] = value
        return doc

    def test_the_raw_value_is_kept_and_expanded_for_the_kit(self):
        s = self.load(self.doc(self.RAW))
        self.assertEqual(s.steps[0].fixed["fail"], self.RAW)
        with mock.patch.multiple(paths, ARTIFACT_ROOT=self.dir / "art",
                                 BACKING=self.dir / "no_backing"):
            params = scheduler.step_params(s, s.steps[0],
                                           {"x1": 1.0, "x2": 2.0}, False)
        self.assertEqual(params["fail"],
                         str(self.dir / "art" / "c2b" / "table.tbl"))

    def test_measure_basis_does_not_depend_on_the_artifact_root(self):
        shas = []
        for root in ("a", "b"):
            with mock.patch.object(paths, "ARTIFACT_ROOT", self.dir / root):
                shas.append(self.load(self.doc(self.RAW)).measure_basis_sha)
        self.assertEqual(shas[0], shas[1])

    def test_a_personal_user_area_is_refused_at_load(self):
        with self.assertRaises(ValueError) as cm:
            self.load(self.doc("/exp/mu2e/app/users/somebody/t.tbl"))  # personal-path-ok: made-up name, exercises the refusal
        self.assertIn("[fixed][fail]", str(cm.exception))
        self.assertIn("personal", str(cm.exception))

    def test_another_token_is_refused_at_load(self):
        with self.assertRaises(ValueError) as cm:
            self.load(self.doc("${HOME}/t.tbl"))
        self.assertIn("[fixed][fail]", str(cm.exception))
        self.assertIn("ARTIFACT", str(cm.exception))
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `cd /exp/mu2e/app/users/oksuzian/autoresearch && source activate.sh && PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_study_engine.TestFixedPaths -v`
Expected: `test_the_raw_value_is_kept...` FAILS (the param is not expanded) and the two refusal tests FAIL (no ValueError); `test_measure_basis...` passes.

- [ ] **Step 3: Implement**

In `core/study.py`, rename `def _expand(value, where):` to `def expand_artifact(value, where):` and update its one caller in `_kits_and_preflight`:
```python
        kits[kit] = {k: expand_artifact(v, f"{kw}[{k}]")
                     for k, v in checked.items()}
```

In `core/study.py` `_steps`, right after the `fixed = kit_registry.validate(...)` statement, add:
```python
        # A fixed path follows the kit-settings rule ('${ARTIFACT}/' only,
        # never a personal user area), checked here. It is expanded where
        # the step's params are built (scheduler.step_params), so Step.fixed
        # -- and so measure_basis -- keep the raw value.
        for key, value in fixed.items():
            expand_artifact(value, f"{sw}[fixed][{key}]")
```

In `core/scheduler.py`, extend both import branches:
```python
if __package__:
    from core import kit_registry
    from core.contract import ContractError
    from core.kits import KitError
    from core.study import expand_artifact
else:
    import kit_registry
    from contract import ContractError
    from kits import KitError
    from study import expand_artifact
```

and in `step_params` replace the `params = merge_params(...)` statement with:
```python
    fixed = {k: expand_artifact(v, f"step {step.step!r} fixed[{k}]")
             for k, v in step.fixed.items()}
    params = merge_params(f"step {step.step!r}",
                          map_params(step.params, env, accepts_lists),
                          {**study.kits.get(step.kit, {}), **fixed})
```
Also add to its docstring: `A fixed '${ARTIFACT}/' value is expanded here (the study keeps it raw).`

- [ ] **Step 4: Run the tests, then the whole suite**

Run the class from Step 2: all 4 pass. Then the autoresearch suite command: `OK`.

- [ ] **Step 5: Commit**

```bash
git add core/study.py core/scheduler.py tests/test_study_engine.py
git commit -m "study: \${ARTIFACT}/ in a step's fixed values

Checked at load by the kit-settings rule, expanded when the step's params
are built; Step.fixed and measure_basis keep the raw value.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 6: The `step_problems` launch hook

**Files:**
- Modify: `core/contract.py` (module docstring; new `kit_step_problems`; `check_kits`)
- Modify: `graph/study_run.py` (launch)
- Test: `tests/test_contract.py`, `tests/test_study_run.py`

**Interfaces:**
- Produces: `contract.kit_step_problems(kit, study, name) -> List[str]`: for a kit with an optional `step_problems(study, step) -> list[str]` method, the problems it reports for each step of `study` whose `kit == name`; `[]` for a kit without the method. `check_kits` and `graph.study_run` both call it (Task 7's adapter implements the method).

- [ ] **Step 1: Write the failing tests**

In `tests/test_contract.py`, add to `class TestCheckKits(_Toy)`:

```python
    def test_a_kit_with_a_step_hook_is_asked_about_each_of_its_steps(self):
        study = self.study()
        asked = []

        class Hooked:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, attr):
                return getattr(self.inner, attr)

            def step_problems(self, study_, step):
                asked.append(step.step)
                return [f"step {step.step!r}: wrong analysis"]

        def opener(name, campaign):
            return Hooked(self.open(name, campaign))

        problems = ct.check_kits(study, campaign="c", opener=opener)
        self.assertEqual(asked, [s.step for s in study.steps
                                 if s.kit == "toykit"])
        self.assertIn("step 'toy': wrong analysis", problems)

    def test_a_kit_without_the_hook_reports_nothing_from_it(self):
        study = self.study()
        kit = types.SimpleNamespace()
        self.assertEqual(ct.kit_step_problems(kit, study, "toykit"), [])
```

(`TestCheckKits.study()` loads `tests.engine_fixtures.toy_doc()`, whose one step is `toy` on `toykit`; `_Toy.open(name, campaign)` opens the real toykit. `types` is already imported in that file.)

In `tests/test_study_run.py`, add after `class _DeadKitSet`:

```python
class _HookedKit:
    """A kit that starts but whose step hook finds a problem."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "1"
    tools = frozenset({"submit", "status", "results"})

    def __init__(self, name):
        self.name = name

    def step_problems(self, study, step):
        return [f"step {step.step!r}: no analysis 'nosuch'"]


class _HookedKitSet(_DeadKitSet):
    def get(self, name):
        return _HookedKit(name)
```

and to `class TestExecutorFlag(_Point)`:

```python
    def test_a_step_hook_problem_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            study = st.load_study_file(write_study(
                toy_doc(name="hooktoy", layout="v2"), tmp / "studies"))
            grid = tmp / "grid"
            out = io.StringIO()
            _HookedKitSet.made = []
            with mock.patch.dict(modes.STUDIES, {"hooktoy": study}), \
                    mock.patch.object(modes, "ENGINE",
                                      modes.ENGINE | {"hooktoy"}), \
                    mock.patch.object(study_run, "KitSet", _HookedKitSet), \
                    mock.patch.object(study_run, "GRID_DATA_ROOT", grid), \
                    mock.patch.object(study_run, "board_for", mock.Mock()), \
                    contextlib.redirect_stdout(out):
                rc = study_run.main(["--study", "hooktoy", "--config", "p1",
                                     "--campaign", "t", "--x=1.0,2.0"])
            self.assertEqual(rc, 2, out.getvalue())
            self.assertIn("REFUSED", out.getvalue())
            self.assertIn("no analysis 'nosuch'", out.getvalue())
            self.assertFalse((grid / "p1").exists(),
                             "state written for a point that never ran")
            self.assertTrue(_HookedKitSet.made[0].closed)
```

- [ ] **Step 2: Run the new tests and see them fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_contract.TestCheckKits tests.test_study_run.TestExecutorFlag -v`
Expected: the three new tests fail (`kit_step_problems` missing; no refusal).

- [ ] **Step 3: Implement**

In `core/contract.py`, add to the Kit interface list in the module docstring:
```
  step_problems(study, step) -> [str]   (optional; the launch check)
```

Add above `def check_kits`:
```python
def kit_step_problems(kit, study, name: str) -> List[str]:
    """What kit `name`'s optional step_problems(study, step) hook says about
    each step of the study that uses it: an adapter's per-step launch check
    (a wrong analysis name or parameter, refused before any job runs). A kit
    without the hook has nothing to say."""
    hook = getattr(kit, "step_problems", None)
    if hook is None:
        return []
    return [p for s in study.steps if s.kit == name for p in hook(study, s)]
```

In `check_kits`, inside the `try:` block, right after the `described = kit.describe()` / `if described is not None:` block, add:
```python
            problems.extend(kit_step_problems(kit, study, name))
```

In `graph/study_run.py`, extend the contract import with `ContractError, kit_step_problems`. Inside the `try:`, right after the "Start every kit now" loop (before `graph = build_study_graph(...)`), add:
```python
        # The per-step half of the launch check (check_kits runs it for a
        # campaign): an adapter that can tell a step is wrong says so before
        # anything is written.
        problems = []
        for name in sorted(kit_registry.kits_of(study)):
            try:
                problems += kit_step_problems(kits.get(name), study, name)
            except (KeyError, KitError, ContractError) as exc:
                problems.append(f"kit {name!r}: {exc}")
        if problems:
            return refuse("; ".join(problems))
```
(`refuse` inside the `try` still runs the `finally: kits.close()`.)

- [ ] **Step 4: Run the tests, then the whole suite**

Run the Step 2 command: all pass. Then the autoresearch suite: `OK`.

- [ ] **Step 5: Commit**

```bash
git add core/contract.py graph/study_run.py tests/test_contract.py tests/test_study_run.py
git commit -m "contract: an adapter's step_problems hook in the launch check

check_kits and graph.study_run ask each kit with the optional hook about
each of its steps, so a wrong step is refused before any job runs.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 7: The `anakit` adapter

**Files:**
- Create: `core/adapters/anakit.py`, `tests/fakeanakit.py`, `tests/test_anakit_kit.py`
- Modify: `core/kit_registry.py` (`KITS`), `core/adapters/__init__.py`, `kits.toml`, `tests/test_kit_config.py`

**Interfaces:**
- Consumes: `prodtools_entry.local_path(ref, what) -> Path`; `contract.parse_status`, `contract.parse_results`, `contract.ContractError`; `kits.KitClient(config, *, campaign, trace_dir)` with `.call(tool, args, *, timeout_s, workflow) -> dict` and `.close()`; `kit_config.load_server_configs()`, `kit_config.ServerConfig(name, command, env_passthrough, set_env, timeouts)`; `contract.kit_step_problems` (Task 6).
- Produces: `AnakitKit(campaign, *, executor="grid", parallel=None, server=None, client_factory=None, grid_root=None, fork=None)`; module constants `VERSION = "anakit-adapter/1"`, `RUN_TIMEOUT_S = 3000`, `RESULT_NAME = "anakit_result.json"`, `FORK_ENV = "AUTORESEARCH_ANAKIT"`; functions `fork_root()`, `fork_commit(root)`, `backing_problem(work_area, code_tarball)`; the result file at `<grid_root>/<config>/anakit/<step>/anakit_result.json` holding `{handle, analysis, work_area, code, version, metrics, reply}`. KitDecl `anakit`: study key `work_area` (path); fixed keys `analysis` (string, required), `input_correction`, `cosmic_rate_per_s_per_mev`, `dio_fraction`, `pot_per_electron` (numbers), `dio_table` (path).

- [ ] **Step 1: Write the fake anakit server**

Create `tests/fakeanakit.py`:

```python
#!/usr/bin/env python3
"""fakeanakit: a stand-in for anakit's MCP server (list_analyses,
run_analysis) for tests/test_anakit_kit.py, driven through the real
KitClient over stdio. It remembers the --work-area it was started with,
answers run_analysis with canned numbers, and writes one ROOT-named file
into output_dir so the adapter has a file to report.

No `from __future__ import annotations` here (see tests/toykit.py).
"""
import sys
from pathlib import Path
from typing import Optional

CATALOGUE = {
    "ce_sensitivity": {
        "metrics": ["s_over_sqrt_b", "ce_abs_eff"],
        "parameters": {"input_correction": {"required": True}},
        "takes_data_files": True},
    "approx_ce_sensitivity": {
        "metrics": ["sensitivity"],
        "parameters": {"sig_eff": {"required": True}},
        "takes_data_files": False},
}


def started_with(argv):
    return argv[argv.index("--work-area") + 1] if "--work-area" in argv else None


def make_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fakeanakit")
    work_area = started_with(sys.argv)

    @server.tool()
    def list_analyses() -> dict:
        return {"status": "success", "files": [], "message": "fake",
                "metadata": {"analyses": CATALOGUE,
                             "environment": f"work area {work_area}"}}

    @server.tool()
    def run_analysis(analysis: str, output_dir: str,
                     data_file: Optional[str] = None,
                     data_files: Optional[list] = None,
                     parameters: Optional[dict] = None,
                     max_events: Optional[int] = None,
                     timeout_s: int = 900) -> dict:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        nts = out / "nts.fake.root"
        nts.write_text("fake\n")
        inputs = data_files if data_files is not None else [data_file]
        return {"status": "success", "files": [str(nts)],
                "message": f"{analysis} over {len(inputs)} file(s)",
                "metadata": {"analysis": analysis, "work_area": work_area,
                             "n_input_files": len(inputs),
                             "used_data_file": data_file is not None,
                             "timeout_s": timeout_s,
                             "s_over_sqrt_b": 4.0, "ce_abs_eff": 6.7e-4,
                             "sensitivity": 4.0}}

    return server


if __name__ == "__main__":
    make_server().run("stdio")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_anakit_kit.py`:

```python
"""core/adapters/anakit.py: anakit (M. MacKenzie's analysis MCP server, our
fork) as a contract kit (Phase C2b spec, section 3). Unit tests drive the
adapter with a fake client; one test drives it through the real KitClient
against tests/fakeanakit.py over stdio."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import contract as ct  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
from adapters import anakit as ak  # noqa: E402
from contract import ContractError  # noqa: E402
from kit_config import ServerConfig  # noqa: E402
from kits import KitError  # noqa: E402

MDC = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax"
CATALOGUE = {
    "ce_sensitivity": {
        "metrics": ["s_over_sqrt_b", "ce_abs_eff"],
        "parameters": {"input_correction": {"required": True},
                       "dio_table": {"required": True},
                       "dio_fraction": {"required": False}},
        "takes_data_files": True},
    "approx_ce_sensitivity": {
        "metrics": ["sensitivity"],
        "parameters": {"sig_eff": {"required": True}},
        "takes_data_files": False},
}
SUCCESS = {"status": "success", "files": [], "message": "ce_sensitivity ok",
           "metadata": {"s_over_sqrt_b": 4.15, "ce_abs_eff": 6.67e-4,
                        "analysis": "ce_sensitivity", "log_path": "/x.log"}}


def server(**timeouts):
    t = {"start": 60, "list_analyses": 30, "run_analysis": 3600}
    t.update(timeouts)
    return ServerConfig(name="anakit", command=("python", "-P", "-m",
                                                 "analysis_mcp_server"),
                        env_passthrough=(), set_env={}, timeouts=t)


def git_repo(root, *files):
    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                    capture_output=True)
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@example.org", "commit",
        "-q", "-m", "init")
    return root


class FakeClient:
    def __init__(self, cfg, log, reply, catalogue=CATALOGUE, gate=None):
        self.cfg, self.log, self.reply = cfg, log, reply
        self.catalogue, self.gate = catalogue, gate

    def call(self, tool, args, *, timeout_s, workflow):
        self.log.append((tool, args, timeout_s, self.cfg.command))
        if tool == "list_analyses":
            return {"status": "success", "files": [], "message": "",
                    "metadata": {"analyses": self.catalogue}}
        if self.gate is not None:
            self.gate.wait(5)
        reply = self.reply(args) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.log.append(("close",))


class _Kit(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.fork = git_repo(self.tmp / "fork", "analysis_mcp_server/__main__.py")
        self.wa = self.tmp / "wa"
        git_repo(self.wa / "Mu2eOptAna", "src/EdepAna_module.cc")
        os.symlink(MDC, self.wa / "backing")
        self.log = []
        self.inputs = []
        for name in ("sim.t.TargetStops.c.0.art", "dts.t.CeEndpoint.c.0.art"):
            p = self.tmp / "in" / name
            p.parent.mkdir(exist_ok=True)
            p.write_text("")
            self.inputs.append({"name": name, "uri": p.as_uri(), "kind": "art"})

    def kit(self, reply=SUCCESS, catalogue=CATALOGUE, gate=None, **kw):
        factory = lambda cfg: FakeClient(cfg, self.log, reply, catalogue, gate)
        return ak.AnakitKit("camp", server=kw.pop("server", server()),
                            client_factory=factory,
                            grid_root=self.tmp / "grid", fork=self.fork, **kw)

    def params(self, **over):
        p = {"work_area": str(self.wa), "analysis": "ce_sensitivity",
             "input_correction": 0.01278168, "dio_table": "/t.tbl"}
        p.update(over)
        return p

    def sdir(self, config="cfg1", step="sob"):
        return self.tmp / "grid" / config / "anakit" / step


class TestOpen(_Kit):
    def test_the_version_names_the_forks_commit(self):
        head = subprocess.run(["git", "-C", str(self.fork), "rev-parse",
                               "--short=12", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        self.assertEqual(self.kit().version, f"anakit-adapter/1+anakit-{head}")

    def test_a_fork_with_uncommitted_changes_is_refused(self):
        (self.fork / "analysis_mcp_server" / "__main__.py").write_text("changed\n")
        with self.assertRaises(KitError) as cm:
            self.kit()
        self.assertIn("uncommitted changes", str(cm.exception))

    def test_the_fork_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": ""}):
            with self.assertRaises(KitError) as cm:
                ak.fork_root()
        self.assertIn("AUTORESEARCH_ANAKIT is not set", str(cm.exception))
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": str(self.tmp)}):
            with self.assertRaises(KitError) as cm:
                ak.fork_root()
        self.assertIn("not an anakit checkout", str(cm.exception))
        with mock.patch.dict(os.environ, {"AUTORESEARCH_ANAKIT": str(self.fork)}):
            self.assertEqual(ak.fork_root(), self.fork)

    def test_the_servers_timeouts_must_cover_anakits_own_limit(self):
        for bad, needle in ((server(run_analysis=3000), "at least"),
                            (ServerConfig("anakit", ("p",), (), {},
                                          {"start": 1.0}), "lack")):
            with self.assertRaises(KitError) as cm:
                self.kit(server=bad)
            self.assertIn(needle, str(cm.exception))

    def test_it_is_a_registered_engine_adapter(self):
        decl = kit_registry.KITS["anakit"]
        self.assertEqual((decl.engine, decl.pipeline, decl.step_kit,
                          decl.check_kit, decl.uses_entries),
                         (True, False, True, False, False))
        self.assertEqual(sorted(decl.study_keys), ["work_area"])
        self.assertEqual(decl.required_fixed, frozenset({"analysis"}))
        ct._load_adapters()
        self.assertIs(ct.ADAPTERS["anakit"], ak.AnakitKit)
        self.assertEqual(self.kit().tools,
                         frozenset({"submit", "status", "results"}))


class TestSubmit(_Kit):
    def test_submit_runs_the_analysis_and_writes_the_result(self):
        kit = self.kit()
        handle = kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(handle, "cfg1.sob")
        (list_call, run_call, close) = self.log
        self.assertEqual(list_call[0], "list_analyses")
        tool, args, timeout_s, command = run_call
        self.assertEqual(tool, "run_analysis")
        self.assertEqual(args, {
            "analysis": "ce_sensitivity", "output_dir": str(self.sdir()),
            "data_files": [str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"),
                           str(self.tmp / "in" / "dts.t.CeEndpoint.c.0.art")],
            "parameters": {"input_correction": 0.01278168,
                           "dio_table": "/t.tbl"},
            "timeout_s": ak.RUN_TIMEOUT_S})
        self.assertEqual(timeout_s, 3600)
        self.assertEqual(command[-2:], ("--work-area", str(self.wa)))
        self.assertEqual(close, ("close",))
        rec = json.loads((self.sdir() / ak.RESULT_NAME).read_text())
        self.assertEqual((rec["handle"], rec["analysis"], rec["metrics"]),
                         ("cfg1.sob", "ce_sensitivity",
                          ["s_over_sqrt_b", "ce_abs_eff"]))
        self.assertEqual(rec["reply"], SUCCESS)

    def test_a_root_file_analysis_gets_data_file(self):
        kit = self.kit()
        kit.submit("cfg1.l1", self.params(analysis="approx_ce_sensitivity",
                                          input_correction=None) | {"sig_eff": 1e-4},
                   [], self.inputs[:1], "w")
        args = self.log[1][1]
        self.assertNotIn("data_files", args)
        self.assertEqual(args["data_file"],
                         str(self.tmp / "in" / "sim.t.TargetStops.c.0.art"))
        with self.assertRaises(ValueError) as cm:
            kit.submit("cfg1.l2", self.params(analysis="approx_ce_sensitivity"),
                       [], self.inputs, "w")
        self.assertIn("takes one ROOT file", str(cm.exception))

    def test_submit_refuses_what_it_cannot_run(self):
        kit = self.kit()
        cases = (
            (dict(params=self.params(work_area="")), "'work_area'"),
            (dict(params=self.params(analysis="")), "'analysis'"),
            (dict(inputs=[]), "no input files"),
            (dict(inputs=[{"name": "r", "uri": "root://x//f.art",
                           "kind": "art"}]), "file://"),
            (dict(files=[{"name": "geom", "uri": "file:///g", "kind": "geom"}]),
             "takes no step files"),
            (dict(params=self.params(analysis="nosuch")), "no analysis 'nosuch'"),
        )
        for over, needle in cases:
            args = {"params": self.params(), "files": [], "inputs": self.inputs}
            args.update(over)
            with self.subTest(needle=needle):
                with self.assertRaises(ValueError) as cm:
                    kit.submit("cfg1.sob", args["params"], args["files"],
                               args["inputs"], "w")
                self.assertIn(needle, str(cm.exception))

    def test_submit_empties_a_step_directory_left_by_an_earlier_run(self):
        self.sdir().mkdir(parents=True)
        (self.sdir() / "nts.stale.root").write_text("old\n")
        self.kit().submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertFalse((self.sdir() / "nts.stale.root").exists())
        self.assertTrue((self.sdir() / ak.RESULT_NAME).exists())

    def test_two_steps_at_once_use_two_servers_and_two_directories(self):
        gate = threading.Barrier(2)

        def reply(args):
            return {**SUCCESS, "message": args["output_dir"]}
        kit = self.kit(reply=reply, gate=gate)
        threads = [threading.Thread(
            target=kit.submit,
            args=(f"cfg1.{step}", self.params(), [], self.inputs, "w"))
            for step in ("sob", "flash")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sum(1 for e in self.log if e == ("close",)), 2)
        for step in ("sob", "flash"):
            rec = json.loads((self.sdir(step=step) / ak.RESULT_NAME).read_text())
            self.assertEqual(rec["reply"]["message"], str(self.sdir(step=step)))

    def test_a_failed_call_leaves_no_result_and_closes_the_server(self):
        kit = self.kit(reply=KitError("anakit", "run_analysis", "timed out"))
        with self.assertRaises(KitError):
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(self.log[-1], ("close",))
        self.assertFalse((self.sdir() / ak.RESULT_NAME).exists())


class TestStatusAndResults(_Kit):
    def submitted(self, reply=SUCCESS):
        kit = self.kit(reply=reply)
        kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        return kit

    def test_a_success_is_completed_with_its_metrics_and_files(self):
        nts = self.tmp / "nts.root"
        nts.write_text("")
        kit = self.submitted({**SUCCESS, "files": [str(nts)]})
        self.assertEqual(kit.status("cfg1.sob", "w").state, "completed")
        res = kit.results("cfg1.sob", "w")
        self.assertEqual(res.metrics, {"s_over_sqrt_b": 4.15,
                                       "ce_abs_eff": 6.67e-4})
        self.assertEqual(res.files, ({"name": "nts.root",
                                      "uri": nts.resolve().as_uri(),
                                      "kind": "root"},))
        self.assertEqual(res.metadata["log_path"], "/x.log")
        self.assertNotIn("s_over_sqrt_b", res.metadata)
        self.assertEqual(res.metadata["work_area"], str(self.wa))
        self.assertTrue(res.metadata["code"])
        self.assertEqual(res.metadata["adapter"], kit.version)

    def test_an_error_reply_is_failed_with_anakits_message(self):
        kit = self.submitted({"status": "error", "files": [], "metadata": {},
                              "message": "ce_sensitivity: no signal window"})
        st = kit.status("cfg1.sob", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn("no signal window", st.message)

    def test_a_missing_result_file_is_failed(self):
        st = self.kit().status("cfg1.sob", "w")
        self.assertEqual(st.state, "failed")
        self.assertIn(ak.RESULT_NAME, st.message)

    def test_results_refuses_a_missing_or_non_number_metric(self):
        for meta, needle in (({"s_over_sqrt_b": 4.15}, "ce_abs_eff"),
                             ({"s_over_sqrt_b": "4.15", "ce_abs_eff": 1e-4},
                              "s_over_sqrt_b")):
            kit = self.submitted({**SUCCESS, "metadata": meta})
            with self.subTest(needle=needle):
                with self.assertRaises(ContractError) as cm:
                    kit.results("cfg1.sob", "w")
                self.assertIn(needle, str(cm.exception))


class TestStepProblems(_Kit):
    def tarball(self, backing):
        path = self.tmp / f"Code_{abs(hash(backing))}.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            d = tarfile.TarInfo("Code")
            d.type, d.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(d)
            link = tarfile.TarInfo("Code/backing")
            link.type, link.linkname = tarfile.SYMTYPE, backing
            tf.addfile(link)
        return path

    def study(self, fixed, tarball=None, metric="sob.s_over_sqrt_b"):
        kits = {"anakit": {"work_area": str(self.wa)}}
        if tarball is not None:
            kits["prodtools"] = {"code_tarball": str(tarball)}
        step = types.SimpleNamespace(step="sob", kit="anakit", params={},
                                     fixed=fixed)
        study = types.SimpleNamespace(
            kits=kits, steps=(step,),
            objectives=(types.SimpleNamespace(metric=metric),),
            extra_metrics=())
        return study, step

    GOOD = {"analysis": "ce_sensitivity", "input_correction": 0.01,
            "dio_table": "${ARTIFACT}/t.tbl"}

    def test_a_right_step_has_no_problems(self):
        study, step = self.study(self.GOOD, self.tarball(MDC))
        self.assertEqual(self.kit().step_problems(study, step), [])

    def test_each_wrong_thing_is_named(self):
        cases = (
            ({**self.GOOD, "analysis": "nosuch"}, None, "sob.s_over_sqrt_b",
             "no analysis 'nosuch'"),
            ({**self.GOOD, "bogus": 1.0}, None, "sob.s_over_sqrt_b",
             "does not take ['bogus']"),
            ({"analysis": "ce_sensitivity", "dio_table": "/t"}, None,
             "sob.s_over_sqrt_b", "needs ['input_correction']"),
            (self.GOOD, None, "sob.flash_edep_per_pot",
             "does not return ['flash_edep_per_pot']"),
            (self.GOOD, self.tarball("/cvmfs/x/Musings/SimJob/Run1Bap"),
             "sob.s_over_sqrt_b", "backed by"),
        )
        for fixed, tarball, metric, needle in cases:
            study, step = self.study(fixed, tarball, metric)
            with self.subTest(needle=needle):
                problems = self.kit().step_problems(study, step)
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_a_work_area_that_is_not_a_directory(self):
        study, step = self.study(self.GOOD)
        study.kits["anakit"]["work_area"] = str(self.tmp / "missing")
        problems = self.kit().step_problems(study, step)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a directory", problems[0])

    def test_the_catalogue_is_asked_once_per_work_area(self):
        kit = self.kit()
        for _ in range(3):
            kit.step_problems(*self.study(self.GOOD))
        self.assertEqual(sum(1 for e in self.log if e[0] == "list_analyses"), 1)

    def test_backing_problem_normalizes_both_links(self):
        self.assertIsNone(ak.backing_problem(self.wa, self.tarball(MDC + "/")))
        self.assertIn("no Code/backing",
                      ak.backing_problem(self.wa, self._no_backing()))

    def _no_backing(self):
        path = self.tmp / "Code_empty.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            d = tarfile.TarInfo("Code")
            d.type, d.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(d)
        return path


class TestOverStdio(_Kit):
    """The real KitClient against tests/fakeanakit.py."""

    def test_submit_status_results_through_the_real_client(self):
        cfg = ServerConfig(name="anakit",
                           command=(sys.executable, str(ROOT / "tests" / "fakeanakit.py")),
                           env_passthrough=(), set_env={},
                           timeouts={"start": 60, "list_analyses": 30,
                                     "run_analysis": 3600})
        with mock.patch.object(paths, "GRAPH_DATA", self.tmp / "graph"):
            kit = ak.AnakitKit("camp", server=cfg, grid_root=self.tmp / "grid",
                               fork=self.fork)
            kit.submit("cfg1.sob", self.params(), [], self.inputs, "w")
        self.assertEqual(kit.status("cfg1.sob", "w").state, "completed")
        res = kit.results("cfg1.sob", "w")
        self.assertEqual(res.metrics, {"s_over_sqrt_b": 4.0, "ce_abs_eff": 6.7e-4})
        self.assertEqual(res.metadata["work_area"], str(self.wa))
        self.assertEqual(res.files[0]["name"], "nts.fake.root")


if __name__ == "__main__":
    unittest.main()
```

Add to `tests/test_kit_config.py`, replacing `test_the_repo_declares_both_prodtools_servers`'s first assertion (keep the rest of that test):
```python
        self.assertEqual(sorted(servers),
                         ["anakit", "prodtools_read", "prodtools_write"])
```
and add:
```python
    def test_the_repo_declares_the_anakit_server(self):
        anakit = kc.load_server_configs()["anakit"]
        self.assertEqual(anakit.command[1:6],
                         ("-P", "-m", "analysis_mcp_server", "--transport",
                          "stdio"))
        self.assertEqual(anakit.set_env["PYTHONPATH"], "${AUTORESEARCH_ANAKIT}")
        self.assertEqual(anakit.timeouts, {"start": 120.0,
                                           "list_analyses": 120.0,
                                           "run_analysis": 3600.0})
```

- [ ] **Step 3: Run the new tests and see them fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_anakit_kit tests.test_kit_config -v`
Expected: import error for `adapters.anakit`; `test_kit_config` failures for the server set.

- [ ] **Step 4: Declare the kit and its server**

In `core/kit_registry.py` `KITS`, add after the `offline_preflight` declaration:
```python
    KitDecl("anakit",
            study_keys={"work_area": _path},
            fixed_keys={"analysis": _string, "input_correction": _number,
                        "cosmic_rate_per_s_per_mev": _number,
                        "dio_fraction": _number, "dio_table": _path,
                        "pot_per_electron": _number},
            required_fixed=frozenset({"analysis"}), uses_entries=False,
            step_kit=True, check_kit=False, engine=True, pipeline=False),
```

Append to `kits.toml`:
```toml
# The anakit adapter (core/adapters/anakit.py) starts one of these per step,
# from the anakit checkout $AUTORESEARCH_ANAKIT (our fork of M. MacKenzie's
# analysis MCP server), under ana 2.7.0: anakit's server imports
# mcp.server.fastmcp, which mcp 2 (ana 2.8.0) no longer has. -P keeps the
# working directory off sys.path, so this repo's tools/ cannot shadow
# anakit's `tools` package. The adapter appends --work-area <the study's
# kits.anakit.work_area>, so anakit's own fallback (its author's work area)
# is never used. anakit runs an analysis synchronously and one at a time per
# server; the adapter stops a run at 3000 s, so run_analysis must allow more.
[servers.anakit]
command = ["/cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python", "-P", "-m", "analysis_mcp_server", "--transport", "stdio"]
env_passthrough = []
set = { PYTHONPATH = "${AUTORESEARCH_ANAKIT}", SPACK_USER_CACHE_PATH = "/tmp/spack_cache_${USER}" }
timeouts = { start = 120, list_analyses = 120, run_analysis = 3600 }
```

In `core/adapters/__init__.py` `register_all`, import `AnakitKit` in both branches (`from core.adapters.anakit import AnakitKit` / `from adapters.anakit import AnakitKit`) and add `("anakit", AnakitKit)` to the tuple of `(name, factory)` pairs.

- [ ] **Step 5: Write the adapter**

Create `core/adapters/anakit.py`:

```python
"""anakit as a contract kit: the adapter the engine drives for every
`kit: "anakit"` step (Phase C2b spec,
docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md, "3. The
anakit adapter").

anakit is M. MacKenzie's analysis MCP server; we run our fork, the checkout
$AUTORESEARCH_ANAKIT names. A step names the analysis in its fixed
`analysis`; every other param except the study's `work_area` setting is
passed to that analysis as a parameter. The physics lives in anakit; this
module holds none.

anakit runs an analysis synchronously, and one server runs one at a time
(FastMCP calls a sync tool on its event loop). So submit starts a server of
its own on the study's work area, runs the analysis to the end, writes the
reply to <GRID_DATA_ROOT>/<config>/anakit/<step>/anakit_result.json and
closes the server. The engine runs every step in its own thread, so the
wait holds up nothing else. status and results only read that file. A point
resumed after a crash mid-analysis has no handle for the step yet, so the
analysis runs again.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

if __package__ == "core.adapters":
    from core import kit_config, paths
    from core.adapters import prodtools_entry as pe
    from core.contract import ContractError, parse_results, parse_status
    from core.kits import KitClient, KitError
else:
    import kit_config
    import paths
    from adapters import prodtools_entry as pe
    from contract import ContractError, parse_results, parse_status
    from kits import KitClient, KitError

VERSION = "anakit-adapter/1"          # bump when a step would measure anew
SERVER = "anakit"                      # kits.toml [servers.anakit]
FORK_ENV = "AUTORESEARCH_ANAKIT"       # the anakit checkout
RESULT_NAME = "anakit_result.json"
# anakit's own limit on one run (its run_analysis allows at most 7200 s).
# The MCP call's timeout (kits.toml) must leave CALL_MARGIN_S above it, so
# anakit reports its own timeout instead of the call being cut off.
RUN_TIMEOUT_S = 3000
CALL_MARGIN_S = 300
OWN_PARAMS = ("work_area", "analysis")  # read here, never sent to anakit


def _error(call, message) -> KitError:
    return KitError(SERVER, call, message)


def fork_root() -> Path:
    """The anakit checkout $AUTORESEARCH_ANAKIT names."""
    root = os.environ.get(FORK_ENV)
    if not root:
        raise _error("open", f"{FORK_ENV} is not set; export it to the "
                     f"anakit checkout (the directory holding "
                     f"analysis_mcp_server/)")
    root = Path(root)
    if not (root / "analysis_mcp_server" / "__main__.py").is_file():
        raise _error("open", f"{FORK_ENV}={root} is not an anakit checkout "
                     f"(no analysis_mcp_server/__main__.py)")
    return root


def _git(root, *args, call) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                       text=True, timeout=60)
    if r.returncode != 0:
        raise _error(call, f"git {' '.join(args)} in {root} failed: "
                     f"{r.stderr.strip()}")
    return r.stdout.strip()


def fork_commit(root) -> str:
    """The checkout's commit, refused when it has uncommitted changes:
    measure_sha tells builds of the analyses apart by this commit alone."""
    dirty = _git(root, "status", "--porcelain", call="open")
    if dirty:
        raise _error("open", f"the anakit checkout {root} has uncommitted "
                     f"changes, so measure_sha could not tell this build of "
                     f"the analyses from the committed one; commit them "
                     f"first:\n{dirty}")
    return _git(root, "rev-parse", "--short=12", "HEAD", call="open")


def code_commit(work_area) -> str:
    """Which Mu2eOptAna the work area's EdepAna was built from, for the
    record. Not part of measure_sha: a rebuilt EdepAna gets a new work-area
    directory, and the work area's path is a study setting."""
    return _git(Path(work_area) / "Mu2eOptAna", "describe", "--always",
                "--dirty", call="submit")


def backing_problem(work_area, code_tarball):
    """Why the work area's EdepAna is not built on the release the study's
    jobs run, or None: its `backing` link against the code tarball's
    `Code/backing` link, read from the archive without unpacking it."""
    link = Path(work_area) / "backing"
    if not link.is_symlink():
        return f"work area {work_area} has no backing link"
    mine = os.path.normpath(os.readlink(link))
    try:
        with tarfile.open(code_tarball) as tf:
            member = tf.getmember("Code/backing")
    except KeyError:
        return f"code tarball {code_tarball} has no Code/backing"
    except (OSError, tarfile.TarError) as exc:
        return f"cannot read code tarball {code_tarball}: {exc}"
    if not member.issym():
        return f"Code/backing in {code_tarball} is not a link"
    theirs = os.path.normpath(member.linkname)
    if mine != theirs:
        return (f"work area {work_area} is backed by {mine}, but the code "
                f"tarball {code_tarball} by {theirs}: EdepAna must be built "
                f"on the release the jobs run")
    return None


def split_handle(name: str):
    config, dot, step = name.rpartition(".")
    if not dot or not config or not step:
        raise ValueError(f"anakit: {name!r} is not <config>.<step>")
    return config, step


def _check_timeouts(server) -> None:
    missing = [k for k in ("list_analyses", "run_analysis")
               if k not in server.timeouts]
    if missing:
        raise _error("open", f"kits.toml [servers.{SERVER}] timeouts lack "
                     f"{missing}")
    need = RUN_TIMEOUT_S + CALL_MARGIN_S
    if server.timeouts["run_analysis"] < need:
        raise _error("open", f"kits.toml [servers.{SERVER}] run_analysis "
                     f"timeout {server.timeouts['run_analysis']:g} s must be "
                     f"at least {need} s: the adapter stops a run at "
                     f"{RUN_TIMEOUT_S} s")


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


class AnakitKit:
    """One campaign child's handle on anakit. run_steps' threads share it,
    one step each; each submit has its own server and step directory."""

    name = "anakit"
    accepts_lists = False
    EXECUTORS = ("grid", "local")     # every analysis runs on this node
    LAUNCH_STAGGER_S = 0.0
    poll_s = (1.0, 5.0)

    def __init__(self, campaign, *, executor="grid", parallel=None,
                 server=None, client_factory=None, grid_root=None,
                 fork=None):
        if executor not in self.EXECUTORS:
            raise ValueError(f"anakit: executor must be one of "
                             f"{list(self.EXECUTORS)}, got {executor!r}")
        self.campaign = campaign
        root = Path(fork) if fork is not None else fork_root()
        self._version = f"{VERSION}+anakit-{fork_commit(root)}"
        if server is None:
            servers = kit_config.load_server_configs()
            if SERVER not in servers:
                raise _error("open", f"kits.toml has no [servers.{SERVER}]")
            server = servers[SERVER]
        _check_timeouts(server)
        self._server = server
        trace = paths.GRAPH_DATA / campaign
        self._factory = client_factory or (
            lambda cfg: KitClient(cfg, campaign=campaign, trace_dir=trace))
        self._grid_root = Path(grid_root or paths.GRID_DATA_ROOT)
        self._catalogues = {}
        self._lock = threading.Lock()

    # --- the Kit interface -------------------------------------------------
    @property
    def version(self) -> str:
        return self._version

    @property
    def tools(self) -> frozenset:
        return frozenset({"submit", "status", "results"})

    def describe(self):
        return None     # per analysis, not per kit: see step_problems

    def close(self) -> None:
        pass            # each server is closed by the call that started it

    def submit(self, name, params, files, inputs, workflow) -> str:
        config, step = split_handle(name)
        if files:
            raise ValueError(f"anakit: takes no step files, got "
                             f"{[f.get('name') for f in files]}")
        params = dict(params)
        for key in OWN_PARAMS:
            if not params.get(key):
                raise ValueError(f"anakit: param {key!r} is missing")
        work_area, analysis = params.pop("work_area"), params.pop("analysis")
        if not inputs:
            raise ValueError(f"anakit: {name} has no input files (its "
                             f"files_from steps gave none)")
        data = [str(pe.local_path(ref, "anakit: input")) for ref in inputs]
        code = code_commit(work_area)
        sdir = self._step_dir(config, step)
        if sdir.exists():
            shutil.rmtree(sdir)     # this step's own directory, from a rerun
        sdir.mkdir(parents=True)
        client = self._client(work_area)
        try:
            spec = self._analyses(client, workflow).get(analysis)
            if spec is None:
                raise ValueError(f"anakit: no analysis {analysis!r} in "
                                 f"{work_area}")
            args = {"analysis": analysis, "output_dir": str(sdir),
                    "parameters": params, "timeout_s": RUN_TIMEOUT_S}
            if spec.get("takes_data_files", True):
                args["data_files"] = data
            elif len(data) == 1:
                args["data_file"] = data[0]
            else:
                raise ValueError(f"anakit: {analysis} takes one ROOT file, "
                                 f"got {len(data)}")
            reply = self._call(client, "run_analysis", args, workflow)
        finally:
            client.close()
        _write_json(sdir / RESULT_NAME, {
            "handle": name, "analysis": analysis, "work_area": str(work_area),
            "code": code, "version": self._version,
            "metrics": list(spec.get("metrics", [])), "reply": reply})
        return name

    def status(self, handle, workflow):
        rec = self._record(handle)
        if rec is None:
            return self._status(
                "failed", f"anakit: no {RESULT_NAME} for {handle}: the step "
                f"directory was removed after the analysis ran; delete the "
                f"point's state/<step>_cluster.txt and broken.txt to run it "
                f"again")
        reply = rec["reply"]
        if isinstance(reply, dict) and reply.get("status") == "success":
            return self._status("completed", str(reply.get("message", "")))
        message = reply.get("message") if isinstance(reply, dict) else reply
        return self._status("failed", f"anakit {rec['analysis']}: {message}")

    def results(self, handle, workflow):
        rec = self._record(handle)
        if rec is None or rec["reply"].get("status") != "success":
            raise ContractError(self.name, "results",
                                f"{handle} has no successful result")
        reply = rec["reply"]
        meta = dict(reply.get("metadata") or {})
        missing = [m for m in rec["metrics"] if m not in meta]
        if missing:
            raise ContractError(self.name, "results", f"anakit's reply "
                                f"lacks declared metric(s) {missing}")
        metrics = {m: meta.pop(m) for m in rec["metrics"]}
        files = [{"name": Path(p).name, "uri": Path(p).resolve().as_uri(),
                  "kind": Path(p).suffix.lstrip(".") or "file"}
                 for p in reply.get("files", [])]
        meta.update(message=reply.get("message"), work_area=rec["work_area"],
                    code=rec["code"], adapter=rec["version"])
        return parse_results({"metrics": metrics, "files": files,
                              "metadata": meta}, self.name)

    # --- the launch check (contract.kit_step_problems) ---------------------
    def step_problems(self, study, step) -> list:
        where = f"step {step.step!r} (kit anakit)"
        work_area = study.kits.get(self.name, {}).get("work_area")
        if not work_area:
            return [f"{where}: kits.anakit.work_area is not set"]
        if not Path(work_area).is_dir():
            return [f"{where}: work area {work_area} is not a directory"]
        problems = []
        tarball = study.kits.get("prodtools", {}).get("code_tarball")
        if tarball is not None:
            why = backing_problem(work_area, tarball)
            if why:
                problems.append(f"{where}: {why}")
        analyses = self._catalogue(work_area,
                                   f"{self.campaign}/launch/{self.name}")
        analysis = step.fixed.get("analysis")
        spec = analyses.get(analysis)
        if spec is None:
            return problems + [f"{where}: anakit has no analysis "
                               f"{analysis!r}; it has {sorted(analyses)}"]
        declared = spec.get("parameters", {})
        sent = (set(step.fixed) | set(step.params)) - set(OWN_PARAMS)
        unknown = sorted(sent - set(declared))
        if unknown:
            problems.append(f"{where}: {analysis} does not take {unknown} "
                            f"(it takes {sorted(declared)})")
        needed = sorted(n for n, p in declared.items()
                        if p.get("required") and n not in sent)
        if needed:
            problems.append(f"{where}: {analysis} needs {needed}")
        wanted = sorted({m.metric.split(".", 1)[1]
                         for m in tuple(study.objectives)
                         + tuple(study.extra_metrics)
                         if m.metric.split(".", 1)[0] == step.step})
        absent = [m for m in wanted if m not in spec.get("metrics", [])]
        if absent:
            problems.append(f"{where}: {analysis} does not return {absent}")
        return problems

    # --- plumbing ----------------------------------------------------------
    def _client(self, work_area):
        cfg = dataclasses.replace(
            self._server,
            command=tuple(self._server.command) + ("--work-area",
                                                   str(work_area)))
        return self._factory(cfg)

    def _call(self, client, tool, args, workflow):
        return client.call(tool, args, timeout_s=self._server.timeouts[tool],
                           workflow=workflow)

    def _analyses(self, client, workflow) -> dict:
        reply = self._call(client, "list_analyses", {}, workflow)
        analyses = (reply.get("metadata") or {}).get("analyses") \
            if isinstance(reply, dict) else None
        if not isinstance(analyses, dict):
            raise KitError(SERVER, "list_analyses", f"reply has no "
                           f"metadata.analyses: {str(reply)[:200]}")
        return analyses

    def _catalogue(self, work_area, workflow) -> dict:
        with self._lock:
            if work_area not in self._catalogues:
                client = self._client(work_area)
                try:
                    self._catalogues[work_area] = self._analyses(client,
                                                                 workflow)
                finally:
                    client.close()
            return self._catalogues[work_area]

    def _step_dir(self, config, step) -> Path:
        return self._grid_root / config / "anakit" / step

    def _record(self, handle):
        config, step = split_handle(handle)
        path = self._step_dir(config, step) / RESULT_NAME
        if not path.exists():
            return None
        rec = json.loads(path.read_text())
        if rec.get("handle") != handle:
            raise ContractError(self.name, "status", f"{path} holds "
                                f"{rec.get('handle')!r}, not {handle!r}")
        return rec

    def _status(self, state, message):
        return parse_status({"state": state, "message": message,
                             "poll_ms": 0, "progress": None}, self.name)
```

(`contract.parse_results` raises `ContractError("... metrics must map names to numbers, got {...}")` for a non-number metric, which names it, and returns `files` as a tuple; `prodtools_entry.local_path` raises `ValueError` for a non-`file://` URI.)

- [ ] **Step 6: Run the tests, then the whole suite**

Run the Step 3 command: all pass. Then the autoresearch suite: `OK`. Fix any other test that enumerates adapters or kits.toml servers by adding `anakit` to its expected set — and only that.

- [ ] **Step 7: Commit**

```bash
git add core/adapters/anakit.py core/adapters/__init__.py core/kit_registry.py kits.toml tests/fakeanakit.py tests/test_anakit_kit.py tests/test_kit_config.py
git commit -m "adapters: anakit as a contract kit

One anakit server per step on the study's work area, a synchronous run into
<config>/anakit/<step>/, the reply kept as anakit_result.json; the version
names the fork's commit and refuses a dirty fork; step_problems checks the
analysis, its parameters and metrics, and the work area's release.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 8: The pre-check's notes, and reusing a saved pass on resume

**Files:**
- Modify: `core/adapters/offline_preflight.py` (`check`'s return)
- Modify: `graph/study_graph.py` (`node_preflight`; new module functions `preflight_basis`, `reusable_pass`)
- Test: `tests/test_offline_preflight_kit.py`, `tests/test_preflight_reuse.py` (new)

**Interfaces:**
- Produces: `study_graph.preflight_basis(pre, settings, env, files) -> dict` (JSON-normalized: `{"kit", "settings", "mapped", "files": {name: {"sha256": ...} | {"uri": ...}}}`); `study_graph.reusable_pass(path, basis) -> bool`; `preflight_verdict.json` = `{"ok", "message", "basis"}` (`basis` absent only when computing it raised). `OfflinePreflightKit.check` message = `f"{code}: {reason}"` followed by one line `"  <note>"` per note.

- [ ] **Step 1: Write the failing tests**

Add to `class TestCheck(_Kit)` in `tests/test_offline_preflight_kit.py`:
```python
    def test_the_message_carries_the_verdicts_notes(self):
        ok, message = self.check()
        self.assertTrue(ok, message)
        first, *notes = message.split("\n")
        self.assertTrue(first.startswith("pass: init=True"), first)
        self.assertIn("  return code: 0  timed_out=False", notes)
        self.assertTrue(any(n.startswith("  surface-check total_hits=")
                            for n in notes), notes)
```

Create `tests/test_preflight_reuse.py`:
```python
"""graph/study_graph.py: a resumed point reuses a saved passing pre-check
verdict for the same kit, settings, mapped values and file contents; a
failure is never reused (Phase C2b spec, section 5)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
from kits import KitError  # noqa: E402
from study_graph import (build_study_graph, preflight_basis,  # noqa: E402
                         reusable_pass)
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

PRE = {"kit": "toykit", "params": {"x1": "x1"}, "files": ["geom"]}


class TestBasis(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text("double a = 1;\n")

    def basis(self, settings=None, env=None, text=None, ref=None):
        if text is not None:
            self.geom.write_text(text)
        ref = ref or {"name": "geom", "uri": self.geom.as_uri(), "kind": "geom"}
        return preflight_basis(PRE, settings or {"function": "branin"},
                               env or {"x1": 1.0}, [ref])

    def test_the_same_inputs_give_the_same_basis(self):
        self.assertEqual(self.basis(), self.basis())

    def test_each_input_changes_it(self):
        base = self.basis()
        self.assertNotEqual(self.basis(settings={"function": "currin"}), base)
        self.assertNotEqual(self.basis(env={"x1": 2.0}), base)
        self.assertNotEqual(self.basis(text="double a = 2;\n"), base)

    def test_a_non_file_ref_is_kept_by_its_uri(self):
        b = self.basis(ref={"name": "geom", "uri": "root://x//g.txt",
                            "kind": "geom"})
        self.assertEqual(b["files"]["geom"], {"uri": "root://x//g.txt"})

    def test_only_a_saved_pass_with_the_same_basis_is_reusable(self):
        path = self.tmp / "preflight_verdict.json"
        basis = self.basis()
        self.assertFalse(reusable_pass(path, basis))
        for saved, want in (({"ok": True, "message": "m", "basis": basis}, True),
                            ({"ok": False, "message": "m", "basis": basis}, False),
                            ({"ok": True, "message": "m"}, False),
                            ({"ok": True, "message": "m",
                              "basis": self.basis(env={"x1": 9.0})}, False)):
            path.write_text(json.dumps(saved))
            self.assertIs(reusable_pass(path, basis), want, saved)
        path.write_text("{not json")
        self.assertFalse(reusable_pass(path, basis))


class CountingKit:
    """Passes (or fails) the pre-check and counts it; its steps never
    submit, so the point stops broken right after the pre-check."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "1"
    tools = frozenset({"submit", "status", "results", "check"})

    def __init__(self, ok):
        self.ok, self.checks = ok, 0

    def check(self, name, params, files, inputs, workflow):
        self.checks += 1
        return self.ok, "pass: fine" if self.ok else "fail: no"

    def submit(self, *args):
        raise KitError("toykit", "submit", "not in this test")


class Kits:
    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class TestResume(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        doc = toy_doc(name="reusetoy", layout="v2")
        doc["preflight"] = {"kit": "toykit", "params": {"x1": "x1"},
                            "files": []}
        self.study = st.load_study_file(write_study(doc, self.tmp / "studies"))
        self.state = self.tmp / "grid" / "p1" / "state"

    def run_point(self, kit, logs):
        build_study_graph(self.study, config="p1", campaign="c", context={},
                          kits=Kits(kit), state_dir=self.state, board=None,
                          log=logs.append, executor="local").compile() \
            .invoke({"config_name": "p1", "x_point": [1.0, 2.0]})
        (self.state / "broken.txt").unlink()   # the operator's retry

    def test_a_saved_pass_is_reused_on_resume(self):
        kit, logs = CountingKit(ok=True), []
        self.run_point(kit, logs)
        verdict = json.loads((self.state / "preflight_verdict.json").read_text())
        self.assertTrue(verdict["ok"])
        self.assertIn("basis", verdict)
        self.run_point(kit, logs)
        self.assertEqual(kit.checks, 1)
        self.assertTrue(any("reusing" in m for m in logs), logs)

    def test_a_saved_failure_is_checked_again(self):
        kit, logs = CountingKit(ok=False), []
        self.run_point(kit, logs)
        self.run_point(kit, logs)
        self.assertEqual(kit.checks, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and see them fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_preflight_reuse tests.test_offline_preflight_kit.TestCheck -v`
Expected: import error for `preflight_basis`; the notes test fails.

- [ ] **Step 3: Implement**

In `core/adapters/offline_preflight.py` `check`, replace the final `return verdict.ok, f"{verdict.code}: {verdict.reason}"` with:
```python
        # The notes say what the check actually verified (foils against the
        # GDML, overlap hits, the return code); a message without them
        # hides that from the point's log and broken.txt.
        message = f"{verdict.code}: {verdict.reason}"
        if verdict.notes:
            message += "\n" + "\n".join(f"  {n}" for n in verdict.notes)
        return verdict.ok, message
```

In `graph/study_graph.py`, add the imports `import hashlib` and `from urllib.parse import unquote, urlparse` (with the existing imports), and add these module-level functions above `build_study_graph`:
```python
def preflight_basis(pre, settings, env, files) -> dict:
    """What a pre-check verdict depends on: the kit, its settings, the
    point's values the pre-check maps, and the content of every file it
    reads (a file:// file by SHA-256; any other ref by its URI).
    JSON-normalized, so it compares equal to the copy read back from
    preflight_verdict.json."""
    def ident(ref):
        uri = ref["uri"]
        if uri.startswith("file://"):
            data = Path(unquote(urlparse(uri).path)).read_bytes()
            return {"sha256": hashlib.sha256(data).hexdigest()}
        return {"uri": uri}
    basis = {"kit": pre["kit"], "settings": settings,
             "mapped": {k: env[v] for k, v in pre["params"].items()},
             "files": {ref["name"]: ident(ref) for ref in files}}
    return json.loads(json.dumps(basis, sort_keys=True))


def reusable_pass(path: Path, basis: dict) -> bool:
    """True when `path` holds a PASSING verdict for exactly this basis. A
    failure is never reused: retrying a point (deleting broken.txt) checks
    it again."""
    if not path.exists():
        return False
    try:
        saved = json.loads(path.read_text())
    except ValueError:
        return False
    return saved.get("ok") is True and saved.get("basis") == basis
```

Replace the body of `node_preflight` with:
```python
    def node_preflight(state):
        pre = study.preflight
        if pre is None:
            return {"broken": False}
        verdict_path = state_dir / "preflight_verdict.json"
        basis = None
        try:
            files = [shared["files"][f] for f in pre["files"]]
            basis = preflight_basis(pre, study.kits.get(pre["kit"], {}),
                                    shared["env"], files)
            # A resumed point already checked: a transient failure on a
            # second run must not break a point whose jobs are running.
            if reusable_pass(verdict_path, basis):
                log(f"[study_run] {config}: preflight passed earlier with "
                    f"the same settings and files; reusing that verdict")
                return {"broken": False}
            kit = kits.get(pre["kit"])
            params = merge_params("preflight",
                                  map_params(pre["params"], shared["env"],
                                             kit.accepts_lists),
                                  study.kits.get(pre["kit"], {}))
            ok, message = kit.check(f"{config}.preflight", params, files, [],
                                    workflow("preflight"))
        except (KitError, ContractError, KeyError, ValueError,
                OSError) as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        record = {"ok": ok, "message": message}
        if basis is not None:
            record["basis"] = basis
        write_atomic(verdict_path, json.dumps(record, indent=1))
        return {"broken": False} if ok else broken(f"preflight: {message}")
```
(`json`, `Path`, `write_atomic`, `merge_params`, `map_params`, `KitError`, `ContractError` are already imported in this module; check and add any that is not.)

- [ ] **Step 4: Run the tests, then the whole suite**

Run the Step 2 command: all pass. Then the autoresearch suite: `OK`.

- [ ] **Step 5: Commit**

```bash
git add core/adapters/offline_preflight.py graph/study_graph.py tests/test_offline_preflight_kit.py tests/test_preflight_reuse.py
git commit -m "preflight: notes in the message; a resumed point reuses a saved pass

The verdict's notes (foils verified, overlap hits, return code) end the
pre-check's message. preflight_verdict.json records what the verdict
depends on, and a restart reuses a saved pass for the same settings and
file contents; a failure is always checked again.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 9: The seven engine twins and the two acceptance fixtures

**Files:**
- Create: `mode_specs/{foilsflash,foilspf,foilspf2k,foilspfbp,foilspfbpx,foilspfbpz,foilspfbw}_ax.json`, `tests/fixtures/engine_studies/foilspfbpz_local.json`, `tests/fixtures/engine_studies/foilspf_nominal.json`, `tests/test_c2b_studies.py`
- Modify: `tests/test_modes.py` (`test_the_primary_directory_is_the_repo_mode_specs`), `tests/test_surrogate.py` (`test_problems_cover_all_modes`), `mode_specs/README.md` ("Engine studies")

**Interfaces:**
- Consumes: the `anakit` KitDecl (Task 7); `${ARTIFACT}/` in fixed (Task 5).
- Produces: studies `<name>_ax` (engine) with boards `leaderboards/leaderboard_bo_<name>_ax.tsv` (v2); fixtures `foilspfbpz_local` and `foilspf_nominal` (engine, v2 boards `leaderboards/leaderboard_foilspfbpz_local.tsv`, `leaderboards/leaderboard_foilspf_nominal.tsv`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_c2b_studies.py`:
```python
"""The C2b engine twins of the foilspf studies (mode_specs/<name>_ax.json)
and the two acceptance fixtures (Phase C2b spec, section 4)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import modes  # noqa: E402
import study as st  # noqa: E402
from tests.engine_fixtures import ENGINE_STUDIES  # noqa: E402

MODES = ROOT / "mode_specs"
ORIGINALS = ("foilsflash", "foilspf", "foilspf2k", "foilspfbp", "foilspfbpx",
             "foilspfbpz", "foilspfbw")
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2"
WORK_AREA = "${ARTIFACT}/autoresearch_muse_ax"
SOB = {"step": "sob", "kit": "anakit", "entry": None, "files": [],
       "files_from": ["mubeam", "mustops_ce"], "params": {},
       "fixed": {"analysis": "ce_sensitivity", "input_correction": 0.01278168,
                 "cosmic_rate_per_s_per_mev": 0.0018181818181818182,
                 "dio_fraction": 0.39,
                 "dio_table": WORK_AREA + "/data/heeck_finer_binning_2016_szafron.tbl"}}
FLASH = {"step": "flash", "kit": "anakit", "entry": None, "files": [],
         "files_from": ["elebeam_flash"], "params": {},
         "fixed": {"analysis": "flash_edep_per_pot",
                   "pot_per_electron": 11.536718606512062}}
SAME = ("schema", "knobs", "derive", "geom", "preflight", "objectives",
        "extra_metrics", "extra_columns")


def doc(path):
    return json.loads(Path(path).read_text())


class TestTwins(unittest.TestCase):
    def test_each_twin_runs_on_the_engine_and_its_original_on_the_pipeline(self):
        for name in ORIGINALS:
            with self.subTest(name=name):
                self.assertIn(f"{name}_ax", modes.ENGINE)
                self.assertIn(name, modes.SPECS)
                self.assertNotIn(name, modes.ENGINE)

    def test_a_twin_differs_from_its_original_only_where_the_spec_says(self):
        for name in ORIGINALS:
            with self.subTest(name=name):
                orig, twin = doc(MODES / f"{name}.json"), doc(MODES / f"{name}_ax.json")
                for key in SAME:
                    self.assertEqual(twin[key], orig[key], key)
                self.assertEqual(twin["name"], f"{name}_ax")
                self.assertIn(f"mode_specs/{name}.json", twin["note"])
                self.assertEqual(twin["kits"], {
                    "prodtools": {**orig["kits"]["prodtools"],
                                  "code_tarball": TARBALL,
                                  "dsconf": "MDC2025ax_{cfg}"},
                    "offline_preflight": {**orig["kits"]["offline_preflight"],
                                          "code_tarball": TARBALL},
                    "anakit": {"work_area": WORK_AREA}})
                steps = {s["step"]: s for s in twin["evaluate"]}
                before = {s["step"]: s for s in orig["evaluate"]}
                self.assertEqual(list(steps), list(before))
                for step in ("mubeam", "mustops_ce", "elebeam_flash"):
                    self.assertEqual(steps[step], before[step])
                self.assertEqual(steps["sob"], SOB)
                self.assertEqual(steps["flash"], FLASH)
                self.assertEqual(
                    [(c["name"], c["k_sigma"]) for c in twin["constraints"]],
                    [(c["name"], c["k_sigma"]) for c in orig["constraints"]])
                self.assertEqual(twin["leaderboard"], {
                    "file": f"leaderboards/leaderboard_bo_{name}_ax.tsv",
                    "layout": "v2", "context": orig["leaderboard"]["context"]})


def geom_vector(text, key):
    m = re.search(rf"{re.escape(key)}\s*=\s*\{{([^}}]*)\}}", text)
    return [float(v) for v in m.group(1).split(",")]


def geom_double(text, key):
    m = re.search(rf"double\s+{re.escape(key)}\s*=\s*([-0-9.eE+]+)", text)
    return float(m.group(1))


class TestFixtures(unittest.TestCase):
    def test_the_nominal_fixture_renders_the_deployed_stack(self):
        s = st.load_study_file(ENGINE_STUDIES / "foilspf_nominal.json")
        self.assertEqual(s.knobs, ())
        text = s.geom.render([])
        self.assertEqual(geom_vector(text, "stoppingTarget.radii"), [75.0] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.halfThicknesses"),
                         [0.0528] * 37)
        self.assertEqual(geom_vector(text, "stoppingTarget.holeRadii"),
                         [21.5] * 37)
        self.assertTrue(all(abs(z) < 1e-3 for z in
                            geom_vector(text, "stoppingTarget.zVars")))
        self.assertAlmostEqual(geom_double(text, "stoppingTarget.deltaZ"),
                               22.222222, places=6)
        self.assertAlmostEqual(
            geom_double(text, "protonabsorber.distFromTargetEnd"), 625.0,
            places=6)

    def test_the_fixtures_run_foilspfbpz_ax_steps(self):
        twin = doc(MODES / "foilspfbpz_ax.json")
        nominal = doc(ENGINE_STUDIES / "foilspf_nominal.json")
        local = doc(ENGINE_STUDIES / "foilspfbpz_local.json")
        self.assertEqual(nominal["evaluate"], twin["evaluate"])
        self.assertEqual(nominal["kits"], twin["kits"])
        self.assertEqual(local["kits"], twin["kits"])
        self.assertEqual(local["knobs"], twin["knobs"])
        for mine, theirs in zip(local["evaluate"], twin["evaluate"]):
            self.assertEqual({k: v for k, v in mine.items() if k != "fixed"},
                             {k: v for k, v in theirs.items() if k != "fixed"})
            if mine["kit"] == "anakit":
                self.assertEqual(mine["fixed"], theirs["fixed"])
            else:
                self.assertLess(mine["fixed"]["njobs"] * mine["fixed"]["events_per_job"],
                                theirs["fixed"]["njobs"] * theirs["fixed"]["events_per_job"])
        for fixture in (nominal, local):
            st.load_study_file(ENGINE_STUDIES / f"{fixture['name']}.json")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and see them fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_c2b_studies -v`
Expected: failures/errors (no twin files, no fixtures).

- [ ] **Step 3: Generate the twins (one-off script, not committed)**

Run from the repo root. It edits each original's TEXT, so the twin keeps the shipped layout, and asserts the result equals the same edits done on the parsed JSON:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
python3 - <<'EOF'
import json, re
from pathlib import Path

M = Path("mode_specs")
TARBALL = "${ARTIFACT}/autoresearch_muse/Code_mdc2025ax.tar.bz2"
WORK_AREA = "${ARTIFACT}/autoresearch_muse_ax"
DIO = WORK_AREA + "/data/heeck_finer_binning_2016_szafron.tbl"
SOB = {"step": "sob", "kit": "anakit", "entry": None, "files": [],
       "files_from": ["mubeam", "mustops_ce"], "params": {},
       "fixed": {"analysis": "ce_sensitivity", "input_correction": 0.01278168,
                 "cosmic_rate_per_s_per_mev": 2e4 / 1.1e7,
                 "dio_fraction": 0.39, "dio_table": DIO}}
FLASH = {"step": "flash", "kit": "anakit", "entry": None, "files": [],
         "files_from": ["elebeam_flash"], "params": {},
         "fixed": {"analysis": "flash_edep_per_pot",
                   "pot_per_electron": 25_000_000 / 2_166_994}}
NOTE = ("Engine twin of mode_specs/{name}.json (Phase C2b, "
        "docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md): "
        "the same knobs, geometry, objectives and columns, run by the "
        "contract engine on SimJob MDC2025ax (Code_mdc2025ax.tar.bz2), with "
        "sob and flash computed by anakit (kit anakit) instead of the "
        "pipeline's harvest. Its own v2 board starts empty: rows measured on "
        "another release cannot be mixed in. The original's note explains "
        "the geometry.")
one = lambda obj: json.dumps(obj, ensure_ascii=False)


def sub(pattern, repl, text, count, what):
    new, n = re.subn(pattern, repl, text, flags=re.M)
    assert n == count, (what, n)
    return new


for name in ("foilsflash", "foilspf", "foilspf2k", "foilspfbp", "foilspfbpx",
             "foilspfbpz", "foilspfbw"):
    src = (M / f"{name}.json").read_text()
    want = json.loads(src)
    want["name"] = f"{name}_ax"
    want["note"] = NOTE.format(name=name)
    want["kits"]["prodtools"].update(code_tarball=TARBALL, dsconf="MDC2025ax_{cfg}")
    want["kits"]["offline_preflight"]["code_tarball"] = TARBALL
    want["kits"]["anakit"] = {"work_area": WORK_AREA}
    want["evaluate"] = [SOB if s["step"] == "sob" else FLASH if s["step"] == "flash"
                        else s for s in want["evaluate"]]
    want["leaderboard"].update(file=f"leaderboards/leaderboard_bo_{name}_ax.tsv",
                               layout="v2")
    t = src
    t = sub(rf'^ "name": "{name}",$', lambda m: f' "name": "{name}_ax",', t, 1, "name")
    t = sub(r'^ "note": ".*",$', lambda m: ' "note": ' + one(want["note"]) + ",", t, 1, "note")
    t = sub(r'"code_tarball": "[^"]*"', lambda m: '"code_tarball": ' + one(TARBALL), t, 2, "tarball")
    t = sub(r'"dsconf": "[^"]*"', lambda m: '"dsconf": "MDC2025ax_{cfg}"', t, 1, "dsconf")
    t = sub(r'^(  "offline_preflight": \{.*\})$',
            lambda m: m.group(1) + ',\n  "anakit": ' + one(want["kits"]["anakit"]), t, 1, "anakit")
    t = sub(r'\{"step": "sob", "kit": "ce_sensitivity".*?"fixed": \{\}\}', lambda m: one(SOB), t, 1, "sob")
    t = sub(r'\{"step": "flash", "kit": "flash_edep_per_pot".*?"fixed": \{\}\}', lambda m: one(FLASH), t, 1, "flash")
    t = sub(rf'"leaderboard": \{{"file": "leaderboards/leaderboard_bo_{name}\.tsv", "layout": "v1"',
            lambda m: f'"leaderboard": {{"file": "leaderboards/leaderboard_bo_{name}_ax.tsv", "layout": "v2"',
            t, 1, "leaderboard")
    assert json.loads(t) == want, name
    out = M / f"{name}_ax.json"
    assert not out.exists(), out
    out.write_text(t)
    print("wrote", out)
EOF
```
Expected: seven `wrote mode_specs/<name>_ax.json` lines. An `AssertionError` names the edit that did not match: read that original's text and adjust only that pattern.

- [ ] **Step 4: Write the two fixtures (one-off script, not committed)**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
python3 - <<'EOF'
import json
from pathlib import Path

twin = json.loads(Path("mode_specs/foilspfbpz_ax.json").read_text())
out = Path("tests/fixtures/engine_studies")

local = json.loads(json.dumps(twin))
local["name"] = "foilspfbpz_local"
local["note"] = ("Phase C2b local acceptance, not a measurement: "
                 "foilspfbpz_ax's five steps at small scale on this node. "
                 "elebeam_flash is sized so the early-flash output holds "
                 "events (about 78 of every 110000 pass): at 1x200 it would "
                 "hold none and the flash step would correctly fail.")
scale = {"mubeam": (2, 10000), "mustops_ce": (2, 2000), "elebeam_flash": (4, 10000)}
for s in local["evaluate"]:
    if s["step"] in scale:
        s["fixed"].update(njobs=scale[s["step"]][0],
                          events_per_job=scale[s["step"]][1], quorum=1.0)
local["leaderboard"] = {"file": "leaderboards/leaderboard_foilspfbpz_local.tsv",
                        "layout": "v2", "context": twin["leaderboard"]["context"]}

nominal = json.loads(json.dumps(twin))
nominal["name"] = "foilspf_nominal"
nominal["note"] = ("Phase C2b grid acceptance: the DEPLOYED stopping target "
                   "(37 foils, rOut 75, halfThickness 0.0528, hole radius "
                   "21.5, 800 mm span: nominalAB01's stack) in foilspfbpz_ax's "
                   "geometry template and environment, on SimJob MDC2025ax. "
                   "Its flash is the damage budget on this release; its sob "
                   "the baseline. The template's comments still say 48 gaps; "
                   "the constants below make it 36.")
nominal["knobs"] = []
consts = nominal["derive"]["consts"]
consts.update(n_foils=37, extent=800.0,
              rOut_0=75.0, rOut_1=75.0, rOut_2=75.0,
              hT_0=0.0528, hT_1=0.0528, hT_2=0.0528,
              f_0=21.5 / 75.0, f_1=21.5 / 75.0, f_2=21.5 / 75.0, zmid=0.0)
nominal["derive"]["exprs"]["deltaZ"] = "extent / 36"
nominal["leaderboard"] = {"file": "leaderboards/leaderboard_foilspf_nominal.tsv",
                          "layout": "v2", "context": twin["leaderboard"]["context"]}

for d in (local, nominal):
    path = out / f"{d['name']}.json"
    assert not path.exists(), path
    path.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print("wrote", path)
EOF
```

- [ ] **Step 5: Update the tests that assume every shipped study is a pipeline study**

In `tests/test_modes.py` `test_the_primary_directory_is_the_repo_mode_specs`, make the subprocess also print the engine set and assert the split:
```python
        script = (
            "import json\n"
            "import modes\n"
            "print(json.dumps([str(modes.MODES_DIR), sorted(modes.STUDIES), "
            "sorted(modes.SPECS), sorted(modes.ENGINE)]))\n"
        )
        modes_dir, studies, specs, engine = json.loads(
            self._fresh_process(script, cwd=self.ROOT / "core").splitlines()[-1])
        want = sorted(p.stem for p in (self.ROOT / "mode_specs").glob("*.json"))
        self.assertEqual(Path(modes_dir), self.ROOT / "mode_specs")
        self.assertEqual(studies, want)
        # C2b: each foilspf study has an engine twin <name>_ax (MDC2025ax,
        # anakit); the twins run on the engine, the originals stay the
        # pipeline's until C3.
        self.assertEqual(engine, [n for n in want if n.endswith("_ax")])
        self.assertEqual(specs, [n for n in want if not n.endswith("_ax")])
```

In `tests/test_surrogate.py` `test_problems_cover_all_modes`, the adapter builds a problem for every study with knobs, so compare against that and read each problem's expectations from its study:
```python
        probs = AutoresearchAdapter().problems()
        self.assertEqual(sorted(probs),
                         sorted(n for n, s in _modes.STUDIES.items() if s.knobs))
        for name, prob in probs.items():
            study = _modes.STUDIES[name]
            self.assertEqual(prob.dim, len(study.knobs))
            self.assertEqual(prob.noise, tuple(o.noise for o in study.objectives))
            self.assertIsNotNone(prob.constraint)
```
Before changing it, check that for every original `tuple(o.noise for o in study.objectives) == tuple(_modes.SPECS[name].obs_noise)`; if not, keep the original `SPECS` branch for names in `SPECS` and use the study branch only for the twins.

In `mode_specs/README.md`, replace the last sentence of "Engine studies" (from `A study with a kit that has no adapter yet` to the end of the paragraph) with:
```
Each foilspf study also has an engine twin, `<name>_ax.json` (Phase C2b):
the same knobs and geometry on SimJob MDC2025ax, with sob and flash from
the `anakit` kit and its own v2 board. The originals keep the
`ce_sensitivity` / `flash_edep_per_pot` kits and run only on the pipeline
(`core/bo_driver.py`, `graph/run.py`, `graph/closed_loop.py`) until Phase
C3 deletes it.
```

- [ ] **Step 6: Run the new tests, then the whole suite**

Run the Step 2 command: all pass. Then the autoresearch suite: `OK`. If another test fails only because it enumerates studies or problems and now meets a twin, change its expected set to exclude or include the twins — never change pipeline behaviour, and report each such change.

- [ ] **Step 7: Commit**

```bash
git add mode_specs/foilsflash_ax.json mode_specs/foilspf_ax.json mode_specs/foilspf2k_ax.json mode_specs/foilspfbp_ax.json mode_specs/foilspfbpx_ax.json mode_specs/foilspfbpz_ax.json mode_specs/foilspfbw_ax.json mode_specs/README.md tests/fixtures/engine_studies/foilspfbpz_local.json tests/fixtures/engine_studies/foilspf_nominal.json tests/test_c2b_studies.py tests/test_modes.py tests/test_surrogate.py
git commit -m "studies: engine twins of the foilspf studies on MDC2025ax

<name>_ax: the same knobs and geometry, the MDC2025ax code tarball and run
label, sob and flash from the anakit kit, a new v2 board. The originals stay
the pipeline's until C3. Fixtures for the C2b acceptance: foilspfbpz_local
(small scale) and foilspf_nominal (the deployed target).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 10: The parity script

**Files:**
- Create: `tools/c2b_parity.py`, `tests/test_c2b_parity.py`

**Interfaces:**
- Consumes: `adapters.anakit.AnakitKit` (Task 7), `modes.STUDIES["foilspfbpz_ax"]` (Task 9), `scheduler.step_params` (Task 5), `adapters.prodtools.VERSION`, `paths.DATA_ROOT`, `paths.GRID_DATA_ROOT`, `paths.leaderboard_live`.
- Produces: `sob_matches(old, new) -> bool`, `rel_close(old, new, tol=1e-6) -> bool`, `level1_inputs(summary_paths) -> (rows, skipped)`, `compare_level2(summary, sob, flash) -> list[(quantity, old, new, ok)]`, `file_ref(path) -> dict`, `adopted_record(config, step, files, events_per_job) -> dict`; CLI subcommands `level1`, `level2`, `level3-setup`, `level3-check`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_c2b_parity.py`:
```python
"""tools/c2b_parity.py's pure parts: the comparison rules, the Level 1
input scan, and the hand-written prodtools record the engine adopts."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("c2b_parity",
                                               ROOT / "tools" / "c2b_parity.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


class TestRules(unittest.TestCase):
    def test_sob_matches_the_macros_three_figures(self):
        for old, new, want in ((4.15, 4.150673260012092, True),
                               (1.69, 1.6921788497327521, True),
                               (4.03, 4.027245662773131, True),
                               (4.15, 4.1549, True),
                               (4.15, 4.1560, False),
                               (4.15, 4.1440, False),
                               (0.912, 0.9125, True),
                               (0.912, 0.9131, False),
                               (-1.0, 1.0, False)):
            with self.subTest(old=old, new=new):
                self.assertIs(cp.sob_matches(old, new), want)

    def test_rel_close(self):
        self.assertTrue(cp.rel_close(6.695048428749645e-07, 6.695048e-07 * (1 + 5e-7)))
        self.assertFalse(cp.rel_close(6.695e-07, 6.695e-07 * (1 + 2e-6)))
        self.assertFalse(cp.rel_close(0.0, 0.0))

    def test_compare_level2_names_each_quantity(self):
        summary = {"muminus_stops": 97520, "mubeam_sim_total": 3.0e6,
                   "ce_seen": 588681, "ce_simulated_events": 1.125e6,
                   "ce_abs_eff": 2.174141844862464e-4,
                   "flash_edep_per_pot": 1.7795659934565772e-07,
                   "s_over_sqrt_b": 1.69}
        sob = {"muminus_stops": 97520.0, "mubeam_sim_total": 3.0e6,
               "ce_seen": 588681.0, "ce_simulated_events": 1.125e6,
               "ce_abs_eff": 2.174141844862464e-4, "s_over_sqrt_b": 1.692}
        flash = {"flash_edep_per_pot": 1.7795659934565772e-07}
        rows = cp.compare_level2(summary, sob, flash)
        self.assertEqual([r[0] for r in rows],
                         ["muminus_stops", "mubeam_sim_total", "ce_seen",
                          "ce_simulated_events", "ce_abs_eff",
                          "flash_edep_per_pot", "s_over_sqrt_b"])
        self.assertTrue(all(r[3] for r in rows), rows)
        bad = cp.compare_level2(summary, {**sob, "ce_seen": 588680.0}, flash)
        self.assertEqual([r[0] for r in bad if not r[3]], ["ce_seen"])


class TestLevel1Inputs(unittest.TestCase):
    def test_level1_inputs_counts_every_skip_with_its_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def harvest(config, summary, nts=True):
                d = root / config / "harvest"
                d.mkdir(parents=True)
                (d / "summary.json").write_text(summary)
                if nts:
                    (d / "nts.ce.root").write_text("")
                return d / "summary.json"

            good = harvest("foilspfA", json.dumps(
                {"ce_abs_eff": 6.6e-4, "s_over_sqrt_b": 4.15}))
            paths = [good,
                     harvest("foilspfB", json.dumps({"s_over_sqrt_b": 4.0})),
                     harvest("foilspfC", json.dumps(
                         {"ce_abs_eff": 6e-4, "s_over_sqrt_b": 4.0}), nts=False),
                     harvest("foilspfD", "{not json")]
            rows, skipped = cp.level1_inputs(paths)
        self.assertEqual([(r[0], r[2], r[3]) for r in rows],
                         [("foilspfA", 6.6e-4, 4.15)])
        reasons = {Path(p).parent.parent.name: why for p, why in skipped}
        self.assertEqual(sorted(reasons), ["foilspfB", "foilspfC", "foilspfD"])
        self.assertIn("ce_abs_eff", reasons["foilspfB"])
        self.assertIn("nts.ce.root", reasons["foilspfC"])
        self.assertIn("unreadable", reasons["foilspfD"])


class TestAdoptedRecord(unittest.TestCase):
    def test_it_is_what_the_scheduler_adopts(self):
        rec = cp.adopted_record("gridphaseA01", "mubeam",
                                ["/pnfs/a/sim.x.TargetStops.y.0.art"], 200000)
        self.assertEqual(rec["step"], "mubeam")
        self.assertEqual(rec["kit"], "prodtools")
        self.assertEqual(rec["handle"], "gridphaseA01.mubeam")
        self.assertEqual(rec["metrics"], {"njobs": 1, "njobs_ok": 1})
        self.assertEqual(rec["files"], [{
            "name": "sim.x.TargetStops.y.0.art",
            "uri": "file:///pnfs/a/sim.x.TargetStops.y.0.art", "kind": "art"}])
        self.assertEqual(rec["metadata"]["events_per_job"], 200000)
        self.assertTrue(rec["kit_version"].startswith("prodtools-adapter/"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and see them fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_c2b_parity -v`
Expected: error loading `tools/c2b_parity.py` (missing).

- [ ] **Step 3: Write the script**

Create `tools/c2b_parity.py`:
```python
#!/usr/bin/env python3
"""C2b parity: the anakit analyses against the old pipeline's harvest, on
the same archived files (Phase C2b spec,
docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md, "6. The
parity check"). Manual, outside the unit-test run; deleted with the
pipeline in C3.

  level1 [--limit N] [--workers W]
      the sensitivity scan alone on every archived foilspf* harvest
  level2 --config C --root R
      the full chain (sob and flash) on one archived point
  level3-setup --config C --root R --sandbox S
      hand-written prodtools records for the engine to adopt; prints the
      graph.study_run command to run next
  level3-check --config C --root R
      the engine's sob/flash results and board row against the archived
      summary.json (run with AUTORESEARCH_DATA_ROOT=S)

R is the grid root holding <config>/state and <config>/harvest (e.g.
$DATA_ROOT/autoresearch_grid). Every analysis runs through the anakit
adapter with foilspfbpz_ax's own settings, so the parity covers the adapter
and the study file as well as the analyses. Reports go under
<DATA_ROOT>/c2b_parity/. Exit 1 on any mismatch or failed analysis.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402

STUDY = "foilspfbpz_ax"
EXACT = ("muminus_stops", "mubeam_sim_total", "ce_seen", "ce_simulated_events")
REL_TOL = 1e-6
OUT = paths.DATA_ROOT / "c2b_parity"
WORKFLOW = "c2bparity"


# --- the comparison rules ----------------------------------------------------

def sob_matches(old: float, new: float) -> bool:
    """The macro printed S/sqrt(B) at 3 significant figures: `new` matches
    `old` when it is within half a unit of that last digit, plus 1e-4
    relative for anakit's convolution change (its README: 0.01%)."""
    if not old > 0 or not math.isfinite(new):
        return False
    unit = 10.0 ** (math.floor(math.log10(abs(old))) - 2)
    return abs(new - old) <= 0.5 * unit + 1e-4 * abs(old)


def rel_close(old: float, new: float, tol: float = REL_TOL) -> bool:
    return old != 0 and abs(new - old) <= tol * abs(old)


def compare_level2(summary: dict, sob: dict, flash: dict) -> list:
    """Each check as (quantity, old, new, ok), in the spec's order."""
    rows = [(k, summary[k], sob[k], float(summary[k]) == float(sob[k]))
            for k in EXACT]
    rows.append(("ce_abs_eff", summary["ce_abs_eff"], sob["ce_abs_eff"],
                 rel_close(summary["ce_abs_eff"], sob["ce_abs_eff"])))
    rows.append(("flash_edep_per_pot", summary["flash_edep_per_pot"],
                 flash["flash_edep_per_pot"],
                 rel_close(summary["flash_edep_per_pot"],
                           flash["flash_edep_per_pot"])))
    rows.append(("s_over_sqrt_b", summary["s_over_sqrt_b"],
                 sob["s_over_sqrt_b"],
                 sob_matches(summary["s_over_sqrt_b"], sob["s_over_sqrt_b"])))
    return rows


def level1_inputs(summary_paths) -> tuple:
    """(config, nts, ce_abs_eff, old sob) for each harvest that has all
    three; every other one as (path, reason) -- counted, never dropped."""
    rows, skipped = [], []
    for path in sorted(Path(p) for p in summary_paths):
        try:
            s = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            skipped.append((str(path), f"unreadable: {exc}"))
            continue
        missing = [k for k in ("ce_abs_eff", "s_over_sqrt_b")
                   if not isinstance(s.get(k), (int, float))]
        if missing:
            skipped.append((str(path), f"no {missing}"))
            continue
        nts = path.parent / "nts.ce.root"
        if not nts.is_file():
            skipped.append((str(path), "no nts.ce.root"))
            continue
        rows.append((path.parent.parent.name, nts, float(s["ce_abs_eff"]),
                     float(s["s_over_sqrt_b"])))
    return rows, skipped


# --- file refs and the adopted records ---------------------------------------

def file_ref(path) -> dict:
    p = Path(path)
    return {"name": p.name, "uri": p.resolve().as_uri(),
            "kind": p.suffix.lstrip(".") or "file"}


def adopted_record(config, step, files, events_per_job) -> dict:
    """A prodtools step's <step>_results.json as run_steps adopts it."""
    from adapters.prodtools import VERSION as PRODTOOLS_VERSION
    return {"step": step, "kit": "prodtools",
            "kit_version": PRODTOOLS_VERSION, "handle": f"{config}.{step}",
            "params": {}, "inputs": [],
            "metrics": {"njobs": len(files), "njobs_ok": len(files)},
            "files": [file_ref(f) for f in files],
            "metadata": {"events_per_job": events_per_job,
                         "source": "hand-written by tools/c2b_parity.py "
                                   "level3-setup from the archived pipeline "
                                   "outputs"}}


def outputs(state_dir: Path, stage: str) -> list:
    path = state_dir / f"{stage}_outputs.txt"
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"{path} lists no files")
    return lines


# --- running the analyses ----------------------------------------------------

def study_params(step_name: str) -> dict:
    import modes
    import scheduler
    study = modes.STUDIES[STUDY]
    step = next(s for s in study.steps if s.step == step_name)
    return scheduler.step_params(study, step, {}, False)


def analyze(kit, handle, params, refs):
    """(metrics, None) or (None, why)."""
    try:
        kit.submit(handle, params, [], refs, f"{WORKFLOW}/{handle}")
    except Exception as exc:      # noqa: BLE001 - reported per point
        return None, f"{type(exc).__name__}: {exc}"
    status = kit.status(handle, WORKFLOW)
    if status.state != "completed":
        return None, status.message
    return kit.results(handle, WORKFLOW).metrics, None


def _kit(sub):
    from adapters.anakit import AnakitKit
    return AnakitKit(WORKFLOW, grid_root=OUT / sub)


def _write_report(name, report) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(report, indent=1, default=str))
    return path


def level1(args) -> int:
    summaries = sorted(paths.GRID_DATA_ROOT.glob("foilspf*/harvest/summary.json"))
    rows, skipped = level1_inputs(summaries)
    if args.limit:
        rows = rows[:args.limit]
    sob = study_params("sob")
    base = {k: sob[k] for k in ("work_area", "cosmic_rate_per_s_per_mev",
                                "dio_fraction", "dio_table")}
    kit = _kit("level1")

    def one(row):
        config, nts, eff, old = row
        params = {**base, "analysis": "approx_ce_sensitivity", "sig_eff": eff}
        metrics, why = analyze(kit, f"{config}.l1", params, [file_ref(nts)])
        new = metrics["sensitivity"] if metrics else None
        return {"config": config, "old": old, "new": new, "error": why,
                "ok": why is None and sob_matches(old, new)}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, rows))
    bad = [r for r in results if not r["ok"]]
    path = _write_report("level1", {"compared": len(results),
                                    "mismatched": len(bad), "results": results,
                                    "skipped": skipped})
    print(f"level1: {len(results)} compared, {len(bad)} mismatched or failed, "
          f"{len(skipped)} skipped; report {path}")
    for r in bad:
        print(f"  {r['config']}: old {r['old']} new {r['new']} {r['error'] or ''}")
    return 1 if bad else 0


def level2(args) -> int:
    point = Path(args.root) / args.config
    state = point / "state"
    summary = json.loads((point / "harvest" / "summary.json").read_text())
    kit = _kit("level2")
    sob_refs = [file_ref(f) for f in outputs(state, "mubeam")
                + outputs(state, "mustops_ce")]
    flash_refs = [file_ref(f) for f in outputs(state, "elebeam_flash")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        sob_f = pool.submit(analyze, kit, f"{args.config}.sob",
                            study_params("sob"), sob_refs)
        flash_f = pool.submit(analyze, kit, f"{args.config}.flash",
                              study_params("flash"), flash_refs)
        (sob, sob_why), (flash, flash_why) = sob_f.result(), flash_f.result()
    if sob_why or flash_why:
        print(f"level2 {args.config}: sob: {sob_why or 'ok'}; "
              f"flash: {flash_why or 'ok'}")
        return 1
    rows = compare_level2(summary, sob, flash)
    path = _write_report(f"level2_{args.config}", {"rows": rows, "sob": sob,
                                                   "flash": flash})
    for q, old, new, ok in rows:
        print(f"  {'ok ' if ok else 'BAD'} {q}: old {old} new {new}")
    print(f"level2 {args.config}: report {path}")
    return 0 if all(r[3] for r in rows) else 1


def level3_setup(args) -> int:
    src = Path(args.root) / args.config / "state"
    dest = Path(args.sandbox) / "autoresearch_grid" / args.config / "state"
    if dest.exists():
        raise SystemExit(f"{dest} exists; use a fresh sandbox")
    dest.mkdir(parents=True)
    for step in ("mubeam", "mustops_ce", "elebeam_flash"):
        files = outputs(src, step)
        epj = int((src / f"{step}_events_per_job.txt").read_text().split()[0])
        (dest / f"{step}_results.json").write_text(json.dumps(
            adopted_record(args.config, step, files, epj), indent=1,
            sort_keys=True))
    print(f"wrote the three prodtools records under {dest}. Next:\n"
          f"  AUTORESEARCH_DATA_ROOT={args.sandbox} PYTHONPATH= "
          f"\"$AUTORESEARCH_PYTHON\" -m graph.study_run --study {STUDY} "
          f"--config {args.config} --campaign {WORKFLOW} --x=<the point's x> "
          f"--context alpha=100000.0 --executor local\n"
          f"then: AUTORESEARCH_DATA_ROOT={args.sandbox} PYTHONPATH= "
          f"\"$AUTORESEARCH_PYTHON\" tools/c2b_parity.py level3-check "
          f"--config {args.config} --root {args.root}")
    return 0


def level3_check(args) -> int:
    import modes
    summary = json.loads((Path(args.root) / args.config / "harvest"
                          / "summary.json").read_text())
    state = paths.GRID_DATA_ROOT / args.config / "state"
    sob = json.loads((state / "sob_results.json").read_text())["metrics"]
    flash = json.loads((state / "flash_results.json").read_text())["metrics"]
    rows = compare_level2(summary, sob, flash)
    study = modes.STUDIES[STUDY]
    board = paths.leaderboard_live(study.leaderboard_rel)
    with board.open() as f:
        found = [r for r in csv.DictReader(f, delimiter="\t")
                 if r["config"] == args.config]
    fmt = {o.name: o.fmt for o in study.objectives}
    want = {"sob": fmt["sob"].format(sob["s_over_sqrt_b"]),
            "flash_edep": fmt["flash_edep"].format(flash["flash_edep_per_pot"])}
    row_ok = (len(found) == 1
              and all(found[0][k] == v for k, v in want.items()))
    for q, old, new, ok in rows:
        print(f"  {'ok ' if ok else 'BAD'} {q}: old {old} new {new}")
    print(f"  {'ok ' if row_ok else 'BAD'} board row {board}: "
          f"{found[0] if found else 'missing'} (want {want})")
    return 0 if row_ok and all(r[3] for r in rows) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("level1")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    for name in ("level2", "level3-setup", "level3-check"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--root", required=True)
        if name == "level3-setup":
            p.add_argument("--sandbox", required=True)
    args = ap.parse_args(argv)
    return {"level1": level1, "level2": level2, "level3-setup": level3_setup,
            "level3-check": level3_check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the new tests, then the whole suite**

Run the Step 2 command: all pass. Then the autoresearch suite: `OK` (this includes `tests/test_no_hardcoded_paths.py`, which scans `tools/`).

- [ ] **Step 5: Commit**

```bash
git add tools/c2b_parity.py tests/test_c2b_parity.py
git commit -m "tools: c2b_parity, the anakit analyses against the harvest

Level 1: the scan alone on every archived foilspf harvest. Level 2: the
full chain on one archived point. Level 3: hand-written prodtools records
for the engine to adopt, then the engine's results and board row checked.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

### Task 11: Engine docs and wiki for Phase C2b

**Files:**
- Modify: `wiki/drivers/contract-engine.md`, `wiki/index.md`, `wiki/log.md`
- Create: `wiki/external/anakit.md`

**Interfaces:**
- Consumes: everything above (read the final code, not this plan, for names and line numbers).

- [ ] **Step 1: Write `wiki/external/anakit.md`**

An OKF page (`wiki/CLAUDE.md` format: frontmatter `type: external`, `title`, `description`, `status: active`, `timestamp: '2026-09-27'`; sections Summary, Key facts, Cross-links, Open questions). Key facts, each with its source:
- The fork: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`, branch `autoresearch` on upstream `039e969`, exported as `$AUTORESEARCH_ANAKIT`; its commits (Tasks 2–4); nothing pushed. Suite: the anakit suite command from this plan's Global Constraints.
- The server needs `mcp<2` (FastMCP): runs under `/cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python`, `-P` so a cwd `tools/` cannot shadow its `tools` package; our mcp 2 KitClient talks to it over stdio.
- FastMCP 1.28 calls a sync tool on its event loop, so one server runs one analysis at a time: the adapter starts one server per step.
- Without `--work-area`/`--musing`/`--code-tarball` (or `MU2E_*` env) anakit silently uses `/exp/mu2e/app/users/mmackenz/mu2eopt`; the adapter always passes `--work-area`.
- The work area `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax`: backing SimJob MDC2025ax (Offline v13_38_00, p107), Mu2eOptAna branch `autoresearch` on `3d8ba5a` plus the full-precision patch, the build recipe from Task 1 Step 6, the DIO table copy (md5). A rebuilt EdepAna goes in a NEW work-area directory (the path is in `measure_sha`; the build is not).
- Every archived output file's SubRun carries its job's `GenEventCount("genCounter")` (200000 TargetStops, 75000 CeEndpoint, 110000 EarlyEleBeamFlash on gridphaseA01), exactly the pipeline's events per job; uproot decodes it byte-swapped (memberwise), art reads it right.
- `geom_run1_b_v06.txt` is gone from Offline v13_38_00; Mu2eOptAna's `edep.fcl` names `geom_run1_b_v40.txt`.
- The macro's cosmic rate `2e4/1.1e7` is 141.8× anakit's default `10/7.8e5`; the studies pass theirs.

Cross-links: `/drivers/contract-engine.md`, `/external/muse-backing-pattern.md`, `/external/mmackenz-workflow.md`, `/incidents/edepana-saw-events-scientific-notation-parse.md`.

- [ ] **Step 2: Add a Phase C2b section to `wiki/drivers/contract-engine.md`**

Bump `timestamp` to `'2026-09-27'` and update `description`. The section covers: the `anakit` adapter (one server per step, `<config>/anakit/<step>/anakit_result.json`, version = adapter + fork commit, dirty fork refused, `RUN_TIMEOUT_S` 3000 under the 3600 s call timeout, no cancel); the `step_problems` hook (from `check_kits` and `graph.study_run`); `${ARTIFACT}/` in step `fixed` (checked at load, expanded in `step_params`, raw in `measure_basis`); the seven `<name>_ax` twins and why twins (the pipeline's `DEFAULT_MODE`); the pre-check reuse on resume and its notes; `tools/c2b_parity.py`. Strike through the "A resumed child re-runs preflight" follow-up with "**Done in C2b**", as C1's items were. Mark the acceptance "pending" (the controller fills it in).

- [ ] **Step 3: Index and log**

`wiki/index.md`: add under External pointers
`- [anakit](/external/anakit.md) — our fork of M. MacKenzie's analysis MCP server ($AUTORESEARCH_ANAKIT, branch autoresearch): ce_sensitivity + flash_edep_per_pot for the foilspf engine twins; needs mcp<2 (ana 2.7.0, -P); one analysis per server at a time; work area autoresearch_muse_ax (MDC2025ax, p107, full-precision EdepAna)`
and extend the contract-engine line with `; C2b anakit adapter (one server per step), step_problems launch hook, <study>_ax engine twins on MDC2025ax`.
`wiki/log.md`: under the existing `## 2026-09-27` heading at the top, add bullets for the new page and the updated one.

- [ ] **Step 4: Commit**

```bash
git add wiki/external/anakit.md wiki/drivers/contract-engine.md wiki/index.md wiki/log.md
git commit -m "docs(wiki): Phase C2b, anakit and the engine twins

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM"
```

---

## Acceptance (the controller, after the final review)

Common environment for every step:
```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch && source activate.sh
export AUTORESEARCH_ANAKIT=/exp/mu2e/app/users/oksuzian/analysis-mcp-server
# AUTORESEARCH_PRODTOOLS: the prodtools checkout the C1 and C2a acceptance
# runs used (it has submit_once/run_status; wiki/drivers/contract-engine.md,
# "prodtools kit (Phase C1)")
```
`git -C $AUTORESEARCH_ANAKIT status --porcelain` must print nothing.

1. **Parity Level 1.** `PYTHONPATH= "$AUTORESEARCH_PYTHON" tools/c2b_parity.py level1 --workers 4`. Pass: exit 0. Any mismatch is investigated (by date and config: an older harvest may predate a macro change); no tolerance is loosened.
2. **Parity Level 2**, three points:
   ```bash
   PYTHONPATH= "$AUTORESEARCH_PYTHON" tools/c2b_parity.py level2 --config gridphaseA01 --root /exp/mu2e/data/users/oksuzian/gridtest/autoresearch_grid
   PYTHONPATH= "$AUTORESEARCH_PYTHON" tools/c2b_parity.py level2 --config foilspfbpz07R11_00 --root /exp/mu2e/data/users/oksuzian/autoresearch_grid
   PYTHONPATH= "$AUTORESEARCH_PYTHON" tools/c2b_parity.py level2 --config foilspfbpz07R19_00 --root /exp/mu2e/data/users/oksuzian/autoresearch_grid
   ```
   Pass: exit 0 for each.
3. **Parity Level 3**, gridphaseA01, sandbox `/exp/mu2e/data/users/oksuzian/c2b_sandbox/l3`: run `level3-setup`, then the printed `graph.study_run` command with `--x=67.7974,111.1044,132.7585,0.140557,0.027008,0.107443,0.4844,0.95,0.95,11.0982` (gridphaseA01's knobs, as in `prodtools_smoke.json`), then `level3-check`. Pass: exit 0. Level 3 compares the engine's `<step>_results.json` metrics under the Level 2 rules and the board row at the study's `fmt` (the row's printed precision cannot carry 1e-6).
4. **Local.** Sandbox `AUTORESEARCH_DATA_ROOT=/exp/mu2e/data/users/oksuzian/c2b_sandbox/local`, `AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies`:
   ```bash
   PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.study_run --study foilspfbpz_local --config c2blocal01 --campaign c2blocal --x=99.6745,103.0623,116.9368,0.018037,0.071303,0.035832,0.0904,0.2627,0.3544,-37.1405 --context alpha=100000.0 --executor local --parallel 4
   ```
   Pass: the pre-check passes, all five steps complete, one row lands. If the flash step fails for zero tracker energy, raise `elebeam_flash`'s `events_per_job` in the fixture (never lower the analysis' requirement), commit that, and rerun with a new config name.
5. **Grid**, the real data root, a Kerberos ticket with at least 4 h left:
   ```bash
   PYTHONPATH= "$AUTORESEARCH_PYTHON" AUTORESEARCH_STUDY_PATH=$PWD/tests/fixtures/engine_studies -m graph.study_run --study foilspf_nominal --config c2bnom01 --campaign c2bgrid --context alpha=100000.0 --executor grid
   # at least 90 s later (prodtools' launch stagger):
   PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.study_run --study foilspfbpz_ax --config c2bR11ax01 --campaign c2bgrid --x=99.6745,103.0623,116.9368,0.018037,0.071303,0.035832,0.0904,0.2627,0.3544,-37.1405 --context alpha=100000.0 --executor grid
   ```
   Pass: both land rows. Report both points' sob and flash next to Run1Bap's (nominalAB01 3.26 / 6.854e-7; foilspfbpz07R11_00 4.15 / 6.695e-7). A change of more than 20% is investigated before step 6.
6. **Budget.** Replace `6.85443e-07` in the seven twins' `constraints` (only the `_ax` files) with c2bnom01's `flash_edep_per_pot` from `state/flash_results.json`, at 6 significant figures; suite green; its own commit.
7. **Wiki.** Record the acceptance in `wiki/drivers/contract-engine.md` (config names, the parity results, the new budget and baseline) and the log; update the project memory (`project_phase_c1_branches.md`).
