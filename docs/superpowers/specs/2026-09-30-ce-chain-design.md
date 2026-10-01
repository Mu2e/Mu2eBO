# The CeEndpoint production chain as a study

Date: 2026-09-30. Status: draft for review. Branch `ce-chain` (from
`generic-study-phase-c1` 6634f82). Follows the spike recorded in
`wiki/concepts/production-chain-spike-2026-09.md`.

## Goal

Run one standard production path, CeEndpoint dts -> digitization ->
reconstruction -> EventNtuple -> a plot, as an ordinary study on the contract
engine: `graph.run --study ce_chain --config <name>` with no knobs, no
surrokit, locally or on the grid. The spike proved the engine can; this makes
it a committed study and removes the workarounds the spike needed.

## Decisions taken

- **anakit's version changes** (operator, 2026-09-30, option 1). The new
  analysis is a commit on the fork's `autoresearch` branch, and the anakit
  version is that branch's commit, so every `_ax` study's `measure_sha`
  changes. Existing `_ax` boards keep their rows and refuse new ones; the next
  `_ax` campaign names a new `leaderboard.file`. The two parked cosmetic
  commits on the fork's `cleanup-c3` (e232d43, fb17702) are folded in first, so
  the `_ax` fingerprints change once, not twice.
- **Objectives stay mandatory.** `ce_chain` reports a stand-in objective
  (the plot step's fit count). Making objectives optional is a separate piece.
- **Stage templates stay CeEndpoint-specific** (`ce_*`). The output file names
  must be literal (our placeholder substitution knows only `{cfg}` and
  `{geom}`), so a generic digitization template would need a `{desc}`-like
  token; not needed for one chain.

## What changes

### 1. The study, `mode_specs/ce_chain.json`

- No knobs. The surrogate already lists only studies with knobs
  (`surrogate/adapter.py`), and `graph.closed_loop` refuses a zero-knob study,
  so the study runs only through `graph.run`.
- **One geometry for every step, by construction:** `geom` is
  `{"writer": "offline_simpleconfig", "base":
  "Offline/Mu2eG4/geom/geom_run1_a.txt", "lines": []}` with an empty `derive`.
  Every prodtools step lists `"files": ["geom"]`, so each job's tarball ships
  the same rendered geometry and its template points
  `services.GeometryService.inputFile` at `{geom}`. (The spike pinned the file
  in each template instead; nothing enforced agreement.)
- `kits.prodtools`: `code_tarball`
  `${ARTIFACT}/autoresearch_muse/Code_ana_v020202.tar.bz2` (a `Code/` holding
  `backing -> /cvmfs/.../Musings/AnalysisMDC2025/v02_02_02`, which is backed by
  SimJob MDC2025ax and adds EventNtuple, plus the usual `setup.sh`), `dsconf`
  `MDC2025ax_{cfg}`, `fatal_log_codes` `[]`. No preflight (stock geometry).
- `kits.anakit.work_area`: `${ARTIFACT}/autoresearch_muse_ax` (see 4).
- Steps and their `fixed` values (local and grid alike):

  | step | kit | entry | files_from | fixed |
  |---|---|---|---|---|
  | `ce` | prodtools | `ce_dts` | | njobs 1, events_per_job 100, memory_mb 3000, quorum 1.0 |
  | `dig` | prodtools | `ce_dig` | ce | njobs 1, memory_mb 3000, quorum 1.0 |
  | `mcs` | prodtools | `ce_mcs` | dig | njobs 1, memory_mb 4000, quorum 1.0 |
  | `nts` | prodtools | `ce_nts` | mcs | njobs 1, memory_mb 3000, quorum 1.0 |
  | `plot` | anakit | | nts | analysis `nts_momentum` |

- Objective `n_fits` = `plot.n_fits` (max, noise 1.0). Extra metrics
  `median_p_front`, `mean_p_front`, `n_events`. Board
  `leaderboards/leaderboard_ce_chain.tsv`, layout v2.

### 2. Stage templates, `stage_entries/ce_{dts,dig,mcs,nts}.json`

From the spike, with the geometry as `{geom}` and the field map
`Offline/Mu2eG4/geom/bfgeom_no_tsu_ps_v01.txt` in all four:

- `ce_dts`: `Production/JobConfig/primary/CeEndpoint.fcl`, resampler
  `TargetStopResampler` over `sim.mu2e.MuminusStopsCat.MDC2025ac.art` (inloc
  `disk`, `sequential_aux`), run 1430, output
  `dts.owner.CeEndpoint.version.sequencer.art`.
- `ce_dig`: `Production/JobConfig/digitize/OnSpill.fcl`, the single
  `outputs.Output.fileName` `dig.owner.CeEndpointOnSpill.version.sequencer.art`,
  `services.DbService` `Sim_best` / `v1_5`.
- `ce_mcs`: `Production/JobConfig/recoMC/OnSpill.fcl`,
  `outputs.LoopHelixOutput.fileName`
  `mcs.owner.CeEndpointOnSpillTriggered.version.sequencer.art`, DbService as dig.
- `ce_nts`: `EventNtuple/fcl/from_mcs-mockdata.fcl`,
  `services.TFileService.fileName`
  `nts.owner.CeEndpointOnSpillTriggered.version.sequencer.root`.
- `desc_fmt` differs per step: `CeEndpoint_{cfg}`, `CeEndpointOnSpill_{cfg}`,
  `CeEndpointOnSpillReco_{cfg}`, `CeEndpointOnSpillNtuple_{cfg}`.

### 3. The anakit fork: analysis `nts_momentum`

On the fork's `autoresearch` branch, after `cleanup-c3` is merged into it.
A `root_file` analysis (`combines_files=True`) over EventNtuple files:
`EventNtuple/ntuple`; `trksegs` read whole (one unsplit
`vector<vector<TrkSegInfo>>` branch); keep the segment at the tracker front
(`sid == 0`) of downstream e- fits (`trk.pdg == 11`, `pz > 0` there). Metrics
`n_events`, `n_fits`, `median_p_front`, `mean_p_front`; writes
`nts_momentum.png` (|p| from 95 to 110 MeV/c, 0.25 MeV/c bins). The selection
is a pure function over awkward arrays, unit-tested in the fork without ROOT
files or mu2e.

### 4. The anakit adapter: EdepAna checks only for art-job analyses

`core/adapters/anakit.py` today assumes every analysis is an EdepAna art job:
`step_problems` requires the work area's `backing` to equal the code tarball's,
and `submit` stamps `code_commit` from `<work_area>/Mu2eOptAna`. Both now apply
only when the step's analysis has `input_kind == "art_files"` (from the
server's `list_analyses` catalogue, which `step_problems` already fetches). A
`root_file` analysis records `code: null`. `ce_sensitivity` and
`flash_edep_per_pot` (both `art_files`) keep both checks.

### 5. Loader: one `desc_fmt` per study

`core/study.py` refuses a study in which two steps of a kit whose entries are
stage templates (`uses_entries`) resolve to the same `desc_fmt`: prodtools
names a run `cnf.<owner>.<desc>.<dsconf>.0`, so the second step is refused at
submit, after the first ran ("the config name was used before").

### 6. Launch check: a board measured differently refuses the launch

`contract.launch_problems` already starts every kit and reads its version.
It now also computes the `measure_sha` this launch would write and compares it
with the rows of the study's board: if the board has rows and none carries
that `measure_sha`, the launch is refused, naming both shas and saying to set
a new `leaderboard.file`. A board whose header does not match the study's
columns (`SchemaMismatch`, also found only at `score` today) is refused the
same way. Today that case runs every step and is refused only
at `score` (`MeasureMismatch`). Both runners get it through the one shared
check. This is the board check planned for `check_study`, moved where every
launch passes.

## Testing

- **Fork:** the selection function on hand-built awkward arrays (front segment
  chosen, upstream and e+ fits dropped, empty events); the registry lists
  `nts_momentum`.
- **Adapter** (`tests/test_anakit_kit.py`, scripted fake server): an
  `art_files` analysis with a mismatched backing is refused and stamps
  `code`; a `root_file` analysis passes with a mismatched work area, needs no
  `Mu2eOptAna`, and records `code: null`.
- **Loader:** two steps with one `desc_fmt` are refused, naming both steps.
- **Launch check:** with toykit, a board holding rows of another
  `measure_sha` is refused; an empty or missing board passes; a board whose
  rows match passes.
- **Study:** `ce_chain` loads, its four prodtools steps all receive the
  `geom` file, and its entries render with the geometry placeholder filled.

## Acceptance

1. Suite green.
2. The seven `_ax` studies' `measure_basis_sha` unchanged (nothing here touches
   their basis; their full `measure_sha` changes through the anakit version,
   as decided).
3. Local `graph.run --study ce_chain --config cechainL01 --executor local`
   lands a row: `median_p_front` within 0.5 MeV/c of 104.0 at 100 events.
4. `graph.run --study foilspfbpz_ax --executor local` against the existing board (bpzax01's 40
   rows) is refused at launch by check 6, naming both shas, before any submit.
5. Spike leftovers removed after acceptance, each looked at first:
   `${ARTIFACT}/autoresearch_muse_ana/`, the anakit worktree
   `analysis-mcp-server-spike` and its branch `spike-ntplot`, and the scratch
   `claude-scratch/spike_cechain/`.

## Not in scope

- Optional objectives (a stages-only study) and recording output locations on
  the row.
- `check_study`.
- A grid run of `ce_chain` at scale.
- Pileup mixing (Mix1BB): the chain digitizes OnSpill with no pileup.
