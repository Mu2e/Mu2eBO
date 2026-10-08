---
type: concept
title: Production-chain spike (CeEndpoint sim -> dig -> mcs -> nts -> plot)
description: 'Spike 2026-09-30 (made permanent as the ce_chain study): the engine runs a CeEndpoint dts -> dig -> mcs -> nts chain plus an anakit plot as a zero-knob study; the production gotchas it found'
status: resolved
status_note: spike done 2026-09-30, made permanent the same day as the ce_chain study
timestamp: '2026-10-08'
---

# Production-chain spike (CeEndpoint, 2026-09-30)

## Summary
Can the engine run one standard production path, CeEndpoint dts ->
digitization -> reconstruction -> EventNtuple -> a plot? Yes. A zero-knob
study ran all five steps locally (`graph.run --executor local`, ~7 min at
100 events) and landed a row (median reconstructed |p| at the tracker
front 104.02 MeV/c vs MC truth 104.05). It became the committed study
`ce_chain` the same day; the study as it runs now is described on
[contract-engine](/drivers/contract-engine.md) and [anakit](/external/anakit.md).
The gotchas below still hold.

## Key facts
- **One code tarball covers sim through ntuple:** the AnalysisMDC2025
  v02_02_02 Musing (backed by SimJob MDC2025ax) adds EventNtuple;
  `ce_chain` uses `${ARTIFACT}/autoresearch_muse/Code_ana_v020202.tar.bz2`.
  SimJob MDC2025ax alone has no EventNtuple.
- **prodtools' example entries are stale for MDC2025ax:** MDC2025ax
  digitization has ONE output module, `Output`. Take templates from the
  newest entry for the release and check them against its own FCL.
- **Digitization needs a calibration set:** with none, DbService is
  `EMPTY` and `makeSD` throws `DBHANDLE_NO_TID`. Use
  `services.DbService.purpose: Sim_best`, `version: v1_5`; reco too.
- **Two steps must not share a `desc_fmt`** (prodtools refuses a reused
  run name); the study loader now refuses it up front.
- **A `geom: null` study has no shared geometry,** so steps can silently
  disagree. `ce_chain` renders one geometry for every step (`files:
  ["geom"]`, `{geom}` in each template).
- **EventNtuple layout (v02_02_02):** `EventNtuple/ntuple`; `trksegs` is
  one unsplit `vector<vector<TrkSegInfo>>` branch; `trk` is split. `sid`
  0/1/2 = tracker front/mid/back. Use the median: two misfits pulled the
  mean to 105.83.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md), [anakit](/external/anakit.md)
- Source files: `mode_specs/ce_chain.json`, `stage_entries/ce_{dts,dig,mcs,nts}.json`,
  `core/adapters/prodtools_entry.py` (`entry_for_step`)

## Open questions / TODO
- A `geom: null` study still has no check that its steps agree.
