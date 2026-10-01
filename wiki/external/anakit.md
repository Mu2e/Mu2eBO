---
type: external
title: anakit — our fork of M. MacKenzie's analysis MCP server
description: 'our fork of M. MacKenzie''s analysis MCP server ($AUTORESEARCH_ANAKIT,
  branch autoresearch): ce_sensitivity + flash_edep_per_pot for the foilspf
  engine twins, nts_momentum for ce_chain; needs mcp<2 (ana 2.7.0, -P); one
  analysis per server at a time; work area autoresearch_muse_ax (MDC2025ax,
  p107, full-precision EdepAna)'
status: active
timestamp: '2026-09-30'
updated_note: ce-chain (2026-09-30) — nts_momentum, the EdepAna checks now
  apply only to art_files analyses, and the fork commits that changed every
  _ax measure_sha
---

# anakit — our fork of M. MacKenzie's analysis MCP server

## Summary
anakit is M. MacKenzie's analysis MCP server, the tool the contract engine
now uses to compute the foilspf family's two physics metrics — `sob`
(`ce_sensitivity`) and `flash` (`flash_edep_per_pot`) — instead of the
pipeline's local harvest code. Phase C2b works on a fork (never upstream)
and drives it through `core/adapters/anakit.py`
([contract-engine](/drivers/contract-engine.md), "anakit kit"), so the
seven `foilspf*` studies get engine twins that run the same geometry on
SimJob MDC2025ax with a rebuilt, full-precision EdepAna.

## Key facts

**The fork**
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
- **Any fork commit changes every `_ax` study's `measure_sha`:** the
  adapter reports the fork's branch commit as the kit version, and
  `measure_sha` hashes every step kit's version. The ce-chain commits did
  exactly that (operator's decision, 2026-09-30): bpzax01's board
  (`leaderboard_bo_foilspfbpz_ax.tsv`, 40 rows) holds `measure_sha`
  `1a91751589c1…` and now refuses new rows; a launch today measures as
  `28a09663f81f…` and is refused at launch
  ([contract-engine](/drivers/contract-engine.md), the board check). The
  next `_ax` campaign names a new `leaderboard.file`; the old rows stay.
- Suite: `cd $AUTORESEARCH_ANAKIT && TMPDIR=/exp/mu2e/data/users/oksuzian/claude-scratch/tmp
  PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/bin/python
  tests/test_tools.py` (global-constraints.md).

**Runtime seam**
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

**The work area — `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax`**
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
- **A rebuilt EdepAna lands in a NEW work-area directory, not in place.**
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

**`nts_momentum` and the art-only checks (ce-chain, 2026-09-30)**
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
  catalogue; an analysis without one is refused at launch. Before this the
  spike needed a work area backed by AnalysisMDC2025 and a `Mu2eOptAna`
  symlink just to plot an ntuple.

**GenEventCount and the Task 1 gate (measured on gridphaseA01's archived
files, first file per stage)**
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

**Spot check before the build (Michael's macro vs. our cosmic rate)**
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
- Acceptance (parity levels 1–3, local, grid, the budget commit) has not
  run yet; see [contract-engine](/drivers/contract-engine.md)'s Phase C2b
  section, marked pending.
- `EdepAna::GetDIOSpectrum()` hardcodes M. MacKenzie's personal-area path to
  the DIO table in every job (see above); worth turning into an fcl
  parameter on our branch and telling him, rather than leaving every job
  dependent on his personal area staying in place.
