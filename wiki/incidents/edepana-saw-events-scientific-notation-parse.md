# EdepAna "Saw N events" parse miss at >1M events (scientific notation)

**Type:** incident
**Status:** resolved
**Updated:** 2026-06-28

## Summary
foilsflash02 R00_00 (the first child to harvest) produced a `harvest_exception`
zero row: `EdepAna 'Saw N events' summary not found`. But EdepAna had **succeeded**
— its log showed `EdepAna summary: Saw 2.70937e+06 events, average calo energy
deposition per event: 75.745 MeV`. Root cause: the harvest parser regex
`pipeline.py:_EDEP_SAW_RX = r"EdepAna summary:\s*Saw\s+(\d+)\s+events"` only matched
**integers**, but EdepAna prints the count with `%g`, so once it exceeds ~1M events
it comes out in **scientific notation** (`2.70937e+06`) → `\d+` misses → SystemExit
→ harvest rc=1 → zero row. A SCALE-INDUCED bug: it never fired before because
foils/ipa/smoke ran mustops_ce at ≤5e5 events (<1M), but foilsflash02's big
`events_per_job` (100×75k → EdepAna saw 2.7M CE events) crossed the 1M threshold.

## Key facts
- **Fix (`pipeline.py`):** regex → `r"EdepAna summary:\s*Saw\s+([\d.eE+-]+)\s+events"`
  + `ce_seen = int(float(m.group(1)))`. Handles both `2709366` and `2.70937e+06`.
  The %g rounding (2709366 → 2.70937e+06 ≈ 2709370, ~4 events) is negligible vs 2.7M.
- **Trigger threshold:** EdepAna's count prints as integer below ~1e6 and switches
  to `e+06` scientific at/above ~1e6. Any mode driving mustops_ce ≥ ~1M total CE
  events hits this — currently only foilsflash (big events_per_job), but the fix is
  general (protects foils/ipa if ever scaled up).
- **Harvest is a fresh subprocess** (`graph/pipeline_io._run_pipeline_verb` →
  `subprocess.run([sys.executable, pipeline.py, harvest])`), so the fix is picked up
  by every not-yet-harvested child WITHOUT relaunching the campaign — only the
  already-failed R00_00 needed a manual re-harvest.
- **The visible edep.log tail is misleading:** it's full of benign
  `error importing function definition for muse/spack/...` sh warnings
  ([[sourced-env-stderr-swallowed]]); the real EdepAna summary + TrigReport
  (`Events total = 2709366`) are above the noise. Filter the import-noise to see
  the true result.

## Cross-links
- Related: [[bo-foilsflash]], [[bo-noise-budget]], [[mmackenz-edepana-lib-qualifier-bump]],
  [[sourced-env-stderr-swallowed]], [[harvest-pyroot-nfs-rpc-hang]]
- Source files: `pipeline.py` (`_EDEP_SAW_RX` ~852, `ce_seen` parse ~1172)

## Harvest race with the fix (2026-06-28)
EdepAna on ~2.7-3.1M CE events (the big foilsflash mustops_ce) takes **~35 min**.
So a harvest that FINISHES at time T STARTED ~35 min earlier, and the harvest
subprocess imports pipeline.py at START. After saving the regex fix at 04:44, two
children (R00_00 fin 04:42, R00_02 fin 05:19) still failed because their harvests
STARTED before 04:44 (old regex in memory). Children whose harvest started after
04:44 self-heal. Lesson: when hot-fixing pipeline.py mid-campaign, in-flight
harvests that already started keep the old code — re-harvest the ones that finish
"too soon" after the edit. (Also: EdepAna ~35 min is the per-eval harvest cost at
this scale — parallel across children so ~35 min/round wall, not cumulative.)

## Open questions / TODO
- None. (If EdepAna's `%g` formatting is ever tightened to always-integer upstream,
  the broadened regex still works.)
