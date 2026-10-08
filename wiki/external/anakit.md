---
type: external
title: anakit — M. MacKenzie's analysis MCP server
description: 'M. MacKenzie''s analysis MCP server ($AUTORESEARCH_ANAKIT, a
  checkout of his main pinned at 3ba8d23 since 2026-10-07), run on the
  SimJob MDC2025ay Musing (--musing); the _ax studies chain muon_stop_rate,
  edep and approx_ce_sensitivity (stops_per_pot via params_from) plus edep
  for flash, ce_chain reads trigger_efficiency_ntuple; the fork
  (ce_sensitivity, flash_edep_per_pot, nts_momentum) and the work area
  autoresearch_muse_ax are retired; needs mcp<2 (ana 2.7.0, -P); one analysis
  per server at a time'
status: active
timestamp: '2026-10-07'
updated_note: upstream analyses (2026-10-07) — the checkout is his main, the
  server runs on a Musing, anakit-adapter/2, new _upstream boards
---

# anakit — M. MacKenzie's analysis MCP server

## Summary
anakit is M. MacKenzie's analysis MCP server
(github.com/michaelmackenzie/analysis-mcp-server). The contract engine
drives it through `core/adapters/anakit.py`
([contract-engine](/drivers/contract-engine.md), "anakit kit") for every
`kit: "anakit"` step. Since 2026-10-07 the physics lives only in his repo:
the seven `_ax` studies chain his separate analyses step by step, the
stopping rate travelling between steps through `params_from`, and this repo
only wires numbers (spec
`docs/superpowers/specs/2026-10-07-upstream-analyses-design.md`). Until then
we ran a fork with three analyses of our own; that history is kept below.

## Key facts

**The checkout**
- `$AUTORESEARCH_ANAKIT` (the `activate.sh` default
  `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`) is his `main`,
  detached at `3ba8d23` (2026-10-07: PR #3 stops_per_pot and PR #4
  R_mue x captures per stop merged, plus S. Middleton's `fullsim`
  analyses). The fork's local branch `autoresearch` stays in that clone as
  the record of the retired analyses; nothing runs from it.
- **Pull rule:** pull only on purpose; read the diff of the four analyses
  the studies use (`muon_stop_rate`, `edep`, `approx_ce_sensitivity`,
  `trigger_efficiency_ntuple`, and what they import); bump
  `core/adapters/anakit.py:VERSION` if their numbers change. The checkout
  commit is each step's recorded build, never part of `measure_sha`.
- **Pin:** `core/adapters/anakit.py:ANAKIT_PIN_SHA` names the accepted
  commit, and the suite asserts the checkout matches it
  (`tests/test_anakit_kit.py` TestAnakitPin, like `SURROKIT_PIN_SHA`):
  his defaults and the DIO constants sit outside `measure_basis`, so a
  pulled checkout fails the suite instead of moving the numbers. The
  engine itself does not refuse a newer commit (a step records its
  build); bump the pin after re-validating.
- `VERSION = "anakit-adapter/2"` (2026-10-07): the server runs on a Musing.
- `kits.toml [servers.anakit]` runs it under ana 2.7.0 (his
  `pyproject.toml` pins `mcp<2`) with `-P`, and sets
  `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=1` (his `AGENTS.md`).

**The Musing**
- Study setting `kits.anakit = {"musing": "SimJob MDC2025ay"}`; the adapter
  appends `--musing <it>`. His `edep` needs EdepAna from Offline v13_39_00
  (MDC2025ay or later), which writes the `EDepAna/tree` his analyses read;
  our old work area's EdepAna (a Mu2eOptAna build on MDC2025ax) wrote none.
- The grid jobs stay on MDC2025ax (`Code_mdc2025ax.tar.bz2`); only the
  analyses run on MDC2025ay. MDC2025ay's EdepAna reads an MDC2025ax
  CeEndpoint file and its tree agrees with its printed summary (75,000
  generated, 39,152 seen; checked 2026-10-07).
- The study loader takes one spelling only, `<Musing> <version>` with one
  space (`core/kit_registry.py:_musing`, 2026-10-07): the setting is
  hashed as written, so `SimJob/MDC2025ay` would have given the same
  Musing a second `measure_sha`.
- The launch check refuses a missing setting, a value that is not a Musing
  and a version (split as his `Mu2eEnv.for_musing` splits: `/` or spaces),
  and an unpublished one (no `/cvmfs/mu2e.opensciencegrid.org/Musings/<M>/<v>`).
  The work-area checks (`backing_problem`, `code_commit`) are gone; the
  result records `musing` in their place.
- `approx_ce_sensitivity` reads the DIO table from his personal area
  (`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl`,
  `DIO_TABLE`, not a parameter) and fixes the DIO fraction (0.391).

**The studies' four steps** (all seven `_ax` studies)
- `stops`: `muon_stop_rate` on `mubeam` (TargetStops files only),
  `upstream_eff` 0.01278168 (was `input_correction`).
- `ce_edep`: `edep` on `mustops_ce`; its result file, the EdepAna ntuple,
  is the next step's input. The slowest step: 933 s on bpzax01R12_00's
  files on a loaded node (2026-10-07), under the adapter's
  `RUN_TIMEOUT_S` of 3000 s.
- `sob`: `approx_ce_sensitivity` on `ce_edep`, `params_from`
  `{"stops_per_pot": "stops.stops_per_pot"}`, `cosmic_rate_per_s_per_mev`
  0.0018181818181818182 (the macro's 2e4/1.1e7, 141.8x his default).
  Objective `sob.sensitivity`.
- `flash`: `edep` on `elebeam_flash`. Objective
  `flash.avg_trk_edep_per_gen_event_mev` is MeV per generated beam
  electron, not per POT (the engine does no arithmetic), so the budget is
  the per-POT one times 11.536718606512062: 7.506758e-06. Under log10 that
  is a constant shift.
- New boards `leaderboard_bo_<study>_upstream.tsv`; the old `_ax` boards
  are history. sob is about 0.35x the old values: the signal fix (x0.371)
  plus counting only selected events (about 6% more).

**Acceptance (2026-10-07, no grid jobs)**
- `bpzax01R12_00` (bpzax01's point, all 130 files still on /pnfs scratch)
  re-analysed through the engine in a sandbox data root
  (`claude-scratch/upstream_accept`): copies of its three prodtools step
  records and preflight verdict were adopted, so only the four anakit
  steps ran.
  - `stops_per_pot` 1.2618671e-03 = 296174 / 3e6 x 0.01278168, exactly.
  - flash 6.58426e-06 MeV per electron vs the fork's 6.58426068582917e-06:
    1.0e-7 relative (Offline's EdepAna prints 6 significant figures; the
    counts, 23180 of 1.1e7, are identical). So the budget conversion stands.
  - `sensitivity` 1.3270656749061143, identical to his
    `approx_ce_sensitivity` run by hand on the same ntuple and
    `stops_per_pot`; the old board's 3.820180850105821 x 0.3474. sob
    `noise` 0.006 x 0.3474 rounds to 0.0021.
- `check_study --executor local` on all eight studies: load, `${ARTIFACT}`
  paths and the launch check (his real catalogue) pass on all eight; the
  geometry pre-check passes on seven. `foilspf2k_ax`'s fails at its knob-box
  centre (IPAsupport wires overlap StoppingTargetMother by ~18 cm): its
  extent is pinned at 2000 mm, outside the 1100 mm certified corridor, and
  this change touched none of its geometry.
- `ce_chain` locally (`cechainU01`): 50 triggered-stream events, 40
  selected, 39 triggered, efficiency 0.975; a row on the new board.

**`ce_chain`**
- The `plot` step is `trigger_efficiency_ntuple` with `trigger_paths`
  `"apr_TrkDe_80m70p, cpr_TrkDe_80m70p"`; objective `n_selected`, extra
  metrics `efficiency`, `n_triggered`, `n_events`; board
  `leaderboard_ce_chain_upstream.tsv`. The ntuple is the triggered stream
  (`CeEndpointOnSpillTriggered`), so the efficiency is conditional: a
  check of the chain, not a trigger measurement.

**Retired (2026-10-07)**
- The fork's `ce_sensitivity`, `flash_edep_per_pot`, `nts_momentum`; the
  anakit settings `input_correction`, `dio_fraction`, `dio_table`,
  `pot_per_electron` (refused at load); the work area
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax` (left on disk,
  unused).
- Not used: S. Middleton's `fullsim.sensitivity` — it needs mixed,
  reconstructed CE EventNtuples and SAM provenance, which per-point files
  are not.

## History (fork, 2026-09-27 to 2026-10-07)

### The fork
- `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`, local branch
  `autoresearch` on upstream base `039e969`, exported as
  `$AUTORESEARCH_ANAKIT` (`core/adapters/anakit.py:FORK_ENV`). Nothing is
  pushed.
- Commits on top of `039e969` (Tasks 2–4):
  - `6884ef7` — `approx_ce_sensitivity`: DIO table and fraction as
    parameters; `compute()`
  - `26a5bc1` — `ce_sensitivity`: S/sqrt(B) from one configuration's own
    files
  - `3561c79` — `flash_edep_per_pot`: tracker energy per POT from
    early-flash files
  - `60cb434`, `e232d43`, `fb17702` — C2b/C3 review fixes (F7, F3, F4);
    the last two sat on a parked branch `cleanup-c3` until ce-chain
    folded them in
  - `1f831a1` (ce-chain, 2026-09-30) — `nts_momentum`: reconstructed |p|
    at the tracker front from EventNtuple files (below)
- **The kit version is hand-bumped (since 2026-10-05):** `anakit-adapter/1`
  (`core/adapters/anakit.py:VERSION`). **Bump it whenever a fork change
  alters what an analysis computes** (a new cut, a changed normalization);
  a refactor, a new analysis for another study, or a cosmetic commit needs
  no bump. The fork commit is each step's recorded build: read at submit,
  written into `anakit_result.json` as `build` and into the results
  metadata. An unrelated fork commit no longer splits a board, and no longer
  refuses a running campaign's later submits (the moved-commit refusal was
  dropped; a dirty checkout is still refused).
- **Until 2026-10-05 any fork commit changed every `_ax` `measure_sha`
  (the version was `anakit-adapter/1+anakit-<commit>`). The ce-chain
  commits did exactly that: bpzax01's board
  (`leaderboard_bo_foilspfbpz_ax.tsv`, 41 rows: bpzax01's 40 plus the C2b
  acceptance row `c2bR11ax01`) holds `1a91751589c1…`, measured at fork
  `60cb434419a2`. The fork moved to `1f831a1` in three commits: two
  refactors (`e232d43` ce_sensitivity, `fb17702` flash_edep_per_pot, no
  number changed) and `nts_momentum`. `python -m graph.restamp_board
  --study foilspfbpz_ax` proves the 41 rows and re-stamps them to the new
  `4283c48d96ee…` with the operator's `--confirm`
  ([contract-engine](/drivers/contract-engine.md), "Measure identity").
- Suite: `cd $AUTORESEARCH_ANAKIT && TMPDIR=/exp/mu2e/data/users/oksuzian/claude-scratch/tmp
  PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python
  tests/test_tools.py` (global-constraints.md).

### Runtime seam
- The server needs `mcp<2` (FastMCP): it runs under
  `/cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python -P -m
  analysis_mcp_server --transport stdio` (`kits.toml[servers.anakit]`); `-P`
  keeps the working directory off `sys.path` so a cwd `tools/` (this repo
  has one) cannot shadow anakit's own `tools` package. Our engine's `mcp` 2
  `KitClient` talks to it over stdio regardless — the version mismatch is
  the anakit process's own import, not the wire protocol.
- FastMCP 1.28 calls a sync tool on its event loop, so **one server runs one
  analysis at a time**: `AnakitKit.submit` starts a fresh server per step
  call and closes it when the analysis ends
  (`core/adapters/anakit.py:AnakitKit.submit`).
- Without `--work-area`/`--musing`/`--code-tarball` (or the matching
  `MU2E_*` env), anakit silently falls back to
  `/exp/mu2e/app/users/mmackenz/mu2eopt`; the adapter always appends
  `--work-area <kits.anakit.work_area>` (`AnakitKit._client`), so that
  fallback is never reached.

### The work area — `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax`
- Backing: SimJob MDC2025ax, Offline v13_38_00, qualifier p107
  (`muse backing SimJob MDC2025ax` created the `backing` link that
  `core/adapters/anakit.py:backing_problem` compares against a study's
  `kits.prodtools.code_tarball`).
- Mu2eOptAna: local branch `autoresearch` on upstream base `3d8ba5a`, plus
  one commit: `9b197e2` — "EdepAna summary: print at full precision" (Task
  1) — fixes EdepAna's OWN summary block: at the default 6 significant
  figures the per-gen-event tracker average (flash per POT) is off by up
  to 5e-6 relative, and an event count above 1e6 prints in scientific
  notation (`src/EdepAna_module.cc`, around the `endJob` summary print).
  This is unrelated to the macro's `%.3g`, which is why the parity check's
  `sob_matches` separately tolerates only half a unit of that digit plus
  anakit's own 0.01% convolution change.
- The rebuilt module:
  `build/al9-prof-e29-p107/Mu2eOptAna/lib/libmu2eoptana_EdepAna_module.so`
  (Task 1, Step 6 build recipe).
- DIO table copy: `${ARTIFACT}/autoresearch_muse_ax/data/heeck_finer_binning_2016_szafron.tbl`,
  md5 `be9d67e140645faff63440fb138a2faa`.
- **A rebuilt EdepAna lands in a NEW work-area directory, not in place.
  The directory's path is a study setting (`kits.anakit.work_area`, part of
  `measure_basis` and so `measure_sha`); the build inside it is not —
  `code_commit(work_area)` (`core/adapters/anakit.py`) records Mu2eOptAna's
  commit in each step's `anakit_result.json` for the record only, and
  `backing_problem` catches a work area backed by the wrong release.
- `geom_run1_b_v06.txt` is gone from Offline v13_38_00. Upstream
  Mu2eOptAna's `edep.fcl` already names `geom_run1_b_v40.txt` (verified:
  the only commit ever touching `fcl/edep.fcl` is the upstream import,
  before either of our two commits on top of `3d8ba5a`) — we did not
  change this. `geom_run1_b_v06.txt` is what Run1BAna's own `edep.fcl`
  names, on the mmackenz side.
- The macro's cosmic rate `2e4/1.1e7` (`0.0018181818181818182`,
  global-constraints.md) is **141.8×** anakit's own default `10/7.8e5`; the
  `foilspf*_ax` studies pass theirs explicitly as
  `kits.evaluate[sob].fixed.cosmic_rate_per_s_per_mev`
  (`mode_specs/foilspfbpz_ax.json`), never anakit's default.
- **EdepAna's `GetDIOSpectrum()` (`src/EdepAna_module.cc:206`) hardcodes a
  path in M. MacKenzie's personal area** —
  `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl`
  — and reads it in EVERY job (the ctor calls it unconditionally), not just
  ones that care about DIO. The resulting weight
  (`h_dio_spectrum_->Interpolate(...)`, `:449`) only multiplies events whose
  `creationCode() == ProcessCode::mu2eFlateMinus` (`:447`), so `ce_sensitivity`
  and `flash_edep_per_pot`'s own numbers do not depend on it — but every job
  still needs that file present on disk or the module fails to construct.
  Open question: make it an fcl parameter on our branch (mirroring
  `approx_ce_sensitivity`'s own `dio_table`) and tell M. MacKenzie upstream.

### `nts_momentum` and the art-only checks (ce-chain, 2026-09-30)
- `tools/analyses/nts_momentum.py` (fork `1f831a1`): a `root_file`
  analysis (`combines_files=True`) over EventNtuple files, the plot step of
  the `ce_chain` study ([production-chain-spike-2026-09](/concepts/production-chain-spike-2026-09.md)).
  Keeps, per event, the tracker-front segment (`sid == 0`) of downstream
  e- fits (`trk.pdg == 11`, `pz > 0` there). Metrics `n_events`, `n_fits`,
  `median_p_front`, `mean_p_front`; writes `nts_momentum.png` (95–110
  MeV/c, 0.25 MeV/c bins). The selection, `front_momenta(segs, pdg)`, is a
  pure function over awkward arrays, unit-tested without ROOT files.
- **The adapter's EdepAna checks apply only to `input_kind ==
  "art_files"`** (`core/adapters/anakit.py`, `step_problems` and
  `submit`): `backing_problem` (work-area backing == the study's code
  tarball's) and `code_commit` (`git describe` in
  `<work_area>/Mu2eOptAna`). A `root_file` analysis records `"code":
  null`. Both read `input_kind` from the server's `list_analyses`
  catalogue; an analysis without one, or with a value outside
  `INPUT_KINDS = ("art_files", "root_file")`, is refused at launch (and at
  `submit`) — an unknown kind never silently drops the checks. Before this the
  spike needed a work area backed by AnalysisMDC2025 and a `Mu2eOptAna`
  symlink just to plot an ntuple.

### GenEventCount and the Task 1 gate (measured on gridphaseA01's archived files, first file per stage)
- Every archived output file's SubRun carries its job's
  `GenEventCount("genCounter")`, exactly the pipeline's `events_per_job`:
  200000 (TargetStops), 75000 (CeEndpoint), 110000 (EarlyEleBeamFlash).
  uproot decodes this byte-swapped (memberwise serialization); art (and so
  anakit) reads it right —
  [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md)
  is the sibling gotcha for `StepPointMC` itself.
- CeEndpoint EdepAna: `n_events` 39175 of `n_gen` 75000.
- EarlyEleBeamFlash: `n_events` 78 of `n_gen` 110000; the tracker
  per-gen-event value prints at full (15 significant digit) precision,
  `1.65903960240195e-06` MeV, thanks to `9b197e2` above.
- TargetStops: `n_events` (muminus_stops) 6519 of `n_gen` 200000;
  `TargetStopPrescaleFilter` prescale 1.0.

### Spot check before the build (Michael's macro vs. our cosmic rate)
- `approx_ce_sensitivity` with our cosmic rate reproduced the macro's
  printed `s_over_sqrt_b` on three archived points: gridphaseA01 (1.69 →
  1.6922), foilspfbpz07R11_00 (4.15 → 4.1507), foilspfbpz07R19_00 (4.03 →
  4.0272).

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (the `anakit`
  adapter, `step_problems`, the `_ax` engine twins),
  [muse-backing-pattern](/external/muse-backing-pattern.md) (the backing
  mechanism `muse backing` uses, and the multi-repo work-area pattern this
  work area is an instance of), [mmackenz-workflow](/external/mmackenz-workflow.md)
  (the original EdepAna macro this fork's analyses are built from),
  [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
  (a sibling EdepAna precision gotcha in the old harvest's regex, not this
  fork's own printf)
- Source files: `core/adapters/anakit.py`, `kits.toml[servers.anakit]`,
  `core/kit_registry.py` (`KitDecl("anakit", ...)`),
  `tools/c2b_parity.py`, `tests/test_anakit_kit.py`, `tests/fakeanakit.py`
- External: `/exp/mu2e/app/users/oksuzian/analysis-mcp-server` (fork),
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/Mu2eOptAna` (clone)

## Open questions / TODO
- One grid point of `foilspfbpz_ax` end to end on the new board (spec check
  4), with the operator's OK (needs a fresh Kerberos ticket).
- The sob `noise` 0.0021 is the old scale's 0.006 x 0.3474; re-measure it
  from replicates.
- `foilspf2k_ax`'s knob-box centre fails the geometry pre-check (above).
