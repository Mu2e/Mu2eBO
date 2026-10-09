---
type: external
title: anakit — M. MacKenzie's analysis MCP server
description: 'M. MacKenzie''s analysis MCP server, checkout of his main pinned at 3ba8d23, run on the SimJob MDC2025ay Musing; feeds the _ax studies and ce_chain; needs mcp<2 (ana 2.7.0, -P)'
status: active
timestamp: '2026-10-08'
---

# anakit — M. MacKenzie's analysis MCP server

## Summary
anakit is M. MacKenzie's analysis MCP server
(github.com/michaelmackenzie/analysis-mcp-server). The contract engine
drives it through `core/adapters/anakit.py`
([contract-engine](/drivers/contract-engine.md), "anakit kit") for every
`kit: "anakit"` step. Since 2026-10-07 the physics lives only in his repo:
the `_ax` studies (`foilspfbpz_ax`, `foilsflash_ax`) chain his separate
analyses step by step, the stopping rate travelling between steps through
`params_from`, and this repo only wires numbers. Until then we ran a fork
with three analyses of our own; a short history is kept below.

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
- The adapter reads each analysis's `input_kind` from `list_analyses`; a
  missing kind or one outside `INPUT_KINDS = ("art_files", "root_file")`
  is refused at launch and at `submit`.
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

**The studies' four steps** (both `_ax` studies)
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

**Acceptance (2026-10-07 local, 2026-10-08 grid)**
- `bpzax01R12_00` re-analysed locally through the engine: `stops_per_pot`
  1.2618671e-03 exact; flash 6.58426e-06 per electron vs the fork's value,
  1e-7 relative (so the budget conversion stands); `sensitivity`
  1.3270656749061143, identical to his tool run by hand (old board x0.3474).
- First grid rows on the `_upstream` boards: `bpzup01` (2026-10-08), then
  the refill bpzup02-21 and the `nomup01` baseline (sob 1.14014, flash
  7.50675e-06 = the damage budget to 6 digits).

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
- We ran a fork (local branch `autoresearch` in the same clone, upstream
  base `039e969`) with three analyses of our own: `ce_sensitivity`
  (S/sqrt(B) from one point's files), `flash_edep_per_pot` and
  `nts_momentum` (reconstructed |p| at the tracker front, the first
  `ce_chain` plot step). The branch stays in the clone as the record;
  nothing runs from it.
- The fork ran with a work area, `autoresearch_muse_ax` (SimJob MDC2025ax +
  a Mu2eOptAna build whose EdepAna printed its summary at full precision).
  It is left on disk, unused. Its EdepAna wrote no `EDepAna/tree`, which is
  why the upstream analyses need the MDC2025ay Musing.
- Until 2026-10-05 the kit version carried the fork commit, so any fork
  commit split every `_ax` board; since then versions are hand-bumped and
  the commit is only each step's recorded build.
- The fork-era EdepAna (Mu2eOptAna) read M. MacKenzie's DIO table from
  his personal area in every job; the module failed to construct without it.
- Check numbers the fork reproduced: the macro's `s_over_sqrt_b` on three
  archived points (gridphaseA01 1.69 -> 1.6922, foilspfbpz07R11_00 4.15 ->
  4.1507, foilspfbpz07R19_00 4.03 -> 4.0272).

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (the `anakit`
  adapter, `step_problems`, the `_ax` engine twins),
  [muse-backing-pattern](/external/muse-backing-pattern.md) (the backing
  mechanism `muse backing` uses, and the multi-repo work-area pattern this
  work area is an instance of), [mmackenz-workflow](/external/mmackenz-workflow.md)
  (the original EdepAna macro this fork's analyses are built from),
  [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
  (a sibling EdepAna precision gotcha in the old harvest's regex)
- Source files: `core/adapters/anakit.py`, `kits.toml[servers.anakit]`,
  `core/kit_registry.py` (`KitDecl("anakit", ...)`),
  `tests/test_anakit_kit.py`, `tests/fakeanakit.py`
- External: github.com/michaelmackenzie/analysis-mcp-server; the checkout
  at `$AUTORESEARCH_ANAKIT`

## Open questions / TODO
- The sob `noise` 0.0021 is the old scale's 0.006 x 0.3474; re-measure it
  from replicates.
