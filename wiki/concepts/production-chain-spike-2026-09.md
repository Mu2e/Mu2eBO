---
type: concept
title: Production-chain spike (CeEndpoint sim -> dig -> mcs -> nts -> plot)
description: 'Spike 2026-09-30: the contract engine runs a full CeEndpoint chain (prodtools for dts/dig/mcs/nts, anakit for a plot) as a zero-knob study, locally in ~7 min at 100 events; seven config/adapter findings, all fixable without engine changes except the anakit EdepAna assumptions'
status: resolved
status_note: spike done 2026-09-30; made permanent the same day as the
  ce_chain study (branch ce-chain); spike scratch removed
timestamp: '2026-09-30'
updated_note: made permanent as ce_chain (ce-chain branch)
---

# Production-chain spike (CeEndpoint, 2026-09-30)

## Summary
Question: can the engine run one standard production path, CeEndpoint
dts -> digitization -> reconstruction -> EventNtuple -> a plot made by
anakit? Yes. A zero-knob study (`ce_chain_spike`, no geometry file, no
surrokit) ran all five steps locally through `graph.run --executor local`
and landed a row (`cechain05`: 45 downstream e- fits in 50 triggered events
of 100 generated; reconstructed |p| at the tracker front median 104.02
MeV/c against MC truth 104.05). Four Offline steps took ~5.6 min at 100
events; the anakit plot step ~1.5 min. **Made permanent the same day** as the
committed study `ce_chain` (branch `ce-chain`; see
[contract-engine](/drivers/contract-engine.md), "The CeEndpoint production
chain as a study"): the templates are `stage_entries/ce_{dts,dig,mcs,nts}.json`,
the analysis is `nts_momentum` on the anakit fork's `autoresearch` branch,
and the code tarball `${ARTIFACT}/autoresearch_muse/Code_ana_v020202.tar.bz2`
is kept. The spike scratch (`claude-scratch/spike_cechain/`, the anakit
worktree `analysis-mcp-server-spike` and its branch `spike-ntplot`, and
`${ARTIFACT}/autoresearch_muse_ana/`) was removed after acceptance.

## Key facts
- **One code tarball covers sim through ntuple:** the AnalysisMDC2025
  v02_02_02 musing is backed by SimJob MDC2025ax (Offline v13_38_00 +
  Production + mu2e-trig-config) and adds EventNtuple. A `Code/` with only
  `backing -> .../AnalysisMDC2025/v02_02_02` and the usual `setup.sh`
  (`muse setup $CODE_DIR -q p107 e29 prof`) works for every step. SimJob
  MDC2025ax alone has no EventNtuple.
- **prodtools' example entries are not current for MDC2025ax:** its oldest
  `data/mdc2025/digi.json` entries use `TriggeredOutput`/`TriggerableOutput`
  (very old). MDC2025ax digitization has ONE output module, `Output`
  (`dig.owner.desc...`); prodtools' json2jobdef refuses an unsubstituted
  `desc` in it at definition time. Take templates from the newest entry for
  the release and check against the release's own FCL.
- **Digitization needs a calibration set:** with none named, DbService is
  `EMPTY` and `makeSD` throws `DBHANDLE_NO_TID` (TrkPreampStraw). Current
  MDC2025 practice (MDC2025as entries): `services.DbService.purpose:
  Sim_best`, `version: v1_5`; reco needs the same.
- **Two steps of one study must not share a `desc_fmt`:** the prodtools run
  name is `cnf.<owner>.<desc>.<dsconf>.0`, so a second step with the same desc
  is refused as "the config name was used before". The loader does not check
  this yet.
- **Each stage template sets its own geometry:** a study with `geom: null`
  has no shared geometry, so steps can silently disagree (cechain04's ce used
  `geom_run1_a.txt`, dig/reco the release default `geom_common.txt`). Here it
  made no measurable difference, but nothing enforces agreement.
- **The anakit adapter assumes EdepAna:** its launch check requires the work
  area's backing to equal the code tarball's, and `submit` stamps the version
  with `git describe` in `<work_area>/Mu2eOptAna`. A Python-only analysis on
  ntuples needs neither; the spike satisfied both with a work area backed by
  AnalysisMDC2025 v02_02_02 and a symlink to the real Mu2eOptAna checkout.
- **A study whose columns change cannot score onto its old board:** the
  header check refused at `score`, after every step had run. Since ce-chain
  the launch check refuses it, and a board of another `measure_sha`, before
  any step runs.
- **EventNtuple layout (v02_02_02):** `EventNtuple/ntuple`; `trksegs` is ONE
  unsplit `vector<vector<TrkSegInfo>>` branch (uproot reads it whole; there are
  no `trksegs.mom...` sub-branches); `trk` is split (`trk.pdg`, ...). An event
  holds up to four fits (e-/e+ x downstream/upstream), indexed alike in `trk`
  and `trksegs`. `sid` 0/1/2 = tracker front/mid/back. Use the median, not the
  mean: two misfits (136, 159 MeV/c) pulled the mean to 105.83.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md), [anakit](/external/anakit.md)
- Source files: `core/adapters/prodtools_entry.py` (`entry_for_step`),
  `core/adapters/anakit.py`, `core/study.py` (`_stage_template`)

## Open questions / TODO
- ~~Make permanent: the four stage templates, a plot analysis in the anakit
  fork, an anakit adapter with art-only EdepAna checks; loader refuses two
  steps with one `desc_fmt`.~~ Done in ce-chain (2026-09-30).
- ~~A study-level geometry~~: `ce_chain` gives every step one rendered
  geometry (`geom` with no lines, `"files": ["geom"]`, `{geom}` in each
  template). A `geom: null` study still has no check that its steps agree.
- Optional objectives for a stages-only study, and output locations on the
  row: not done (out of ce-chain's scope).
