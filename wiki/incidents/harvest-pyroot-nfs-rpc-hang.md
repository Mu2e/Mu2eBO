---
type: incident
title: Harvest PyROOT extractor hangs in NFS RPC (D-state), no watchdog
description: harvest PyROOT extractor D-state on stuck /pnfs NFS RPC (3s CPU / 5.5h
  wall), no timeout at any layer; kill pipeline parent FIRST (extractor-only kill
  → fail-soft flash-less summary → degraded row); retry works (per-RPC, not dead
  mount)
status: resolved
timestamp: '2026-07-10'
updated_note: 'recurrence #2: EdepAna face'
---

# Harvest PyROOT extractor hangs in NFS RPC (D-state), no watchdog

## Summary
foilsflashSOBX01's harvest sat 5.5 h with all grid work done and no leaderboard
row: the inner PyROOT gallery extractor (the `python3 -c "import ROOT..."`
subprocess of `_extract_trk_edep_per_pot`) blocked forever on a single stuck
/pnfs NFS read. Harvest has NO timeout at any layer (pipeline verb, graph
node), so one wedged RPC stalls the whole chain indefinitely.

## Key facts
- Signature: extractor process in **state `D`** with `wchan =
  rpc_wait_bit_killable` and **~3 s of CPU over hours** (`ps -o
  etime,time,%cpu,stat`). CPU-vs-elapsed is the discriminator between
  "grinding slowly" and "dead RPC" — check it BEFORE killing.
- **ROOT CAUSE (2026-07-08): MULTIPLE poison files on a dead pnfs pool — 6 of
  181 (00018, 00020, 00087, 00106, 00140, 00149; scattered, ~3%).** One-at-a-time
  removal is a whack-a-mole trap: retry-2 hung on the NEXT bad file (00020)
  after 00018 was dropped. Poison signature: `stat` instant (metadata fine),
  data read hangs forever in wchan `nfs4_handle_exception` / read_bytes frozen;
  `/proc/<pid>/fd | grep outstage` names the culprit mid-hang.
- **RECIPE — probe the whole list up front, never remove one-by-one:**
  `xargs -P 16 -I{} sh -c 'timeout 6 dd if="{}" of=/dev/null bs=64k count=2
  2>/dev/null && echo OK {} || echo BAD {}' < elebeam_flash_outputs.txt`
  (~30 s for 180 files); rewrite outputs.txt from the OK lines (backup first).
  Denominator self-consistent — `flash_n_input = len(files)×EPJ`. 175/181
  files → σ_flash ~2% → ~2.1%, negligible.
- **Kill order matters**: kill the `pipeline.py ... harvest` parent FIRST,
  then the extractor. Killing only the extractor lets the fail-soft
  `_edep_from_stage_outputs` catch the nonzero rc, write a **flash-less
  summary.json**, and the graph's evaluate then lands a degraded row.
  Parent-first → harvest verb dies rc≠0 → `node_evaluate` diverts to
  `scan_logs/evaluate_zero_row.tsv` (cause=harvest_exception) → leaderboard
  stays clean (verified in this incident).
- Recovery: re-run `AUTORESEARCH_MODE=<mode> python3 pipeline.py --config
  <cfg> harvest` detached (EdepAna re-runs too, ~15 min total), then append
  the row via the driver `evaluate` verb (documented stalled-chain path);
  arm a watchdog monitor (summary-exists / pid-dead / 45-min cap) so a
  recurrence can't eat hours silently.
- 2 prior xrootd/pnfs flakiness incidents are cousins but distinct:
  [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md) (grid-side art open), 
  [stage-out-rename-race](/incidents/stage-out-rename-race.md) (dir renames). This one is local-harvest NFS.
- TODO (mechanism fix): add a `timeout=` to the extractor `subprocess.run`
  in `pipeline.py:_extract_trk_edep_per_pot` (e.g. 3600 s) so the fail-soft
  path fires instead of an unbounded hang; per-file progress logging would
  identify poison files.

- **RECURRENCE 2026-07-10 (ff12 R00_04/R00_08): the EdepAna face.** The stuck
  process was the harvest Step-1 `mu2e` (EdepAna over mustops_ce files), D-state
  23-35 min on ONE dead-pool file per child (stat-instant/read-hang, probe
  recipe confirms). EdepAna-face recipe differs from the flash face: killing
  the stuck `mu2e` is SAFE (pipeline raises SystemExit on EdepAna rc≠0 → NO
  degraded summary, child zero-rows cleanly) — filter the poison line from
  `mustops_ce_outputs.txt` (keep a .bak_poison), kill the mu2e, then direct
  re-harvest + driver evaluate lands the row. sob denominators are
  file-count-aware so dropping 1/12-13 files stays unbiased. SEQUENCING:
  after the kill the child's graph process still walks its failure path
  (may emit a SECOND zero_row `metrics_none` before `[run] done`) — start
  the manual re-harvest only after the child exits, or accept a benign
  summary.json write race (child reads-only on its way out).

## Cross-links
- Related: [concat-xrootd-fileopen-postendjob](/incidents/concat-xrootd-fileopen-postendjob.md), [stage-out-rename-race](/incidents/stage-out-rename-race.md), [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
- Source files: `pipeline.py:_extract_trk_edep_per_pot`, `pipeline.py:_edep_from_stage_outputs`
- Config: foilsflashSOBX01 (foils-champion transplant eval, 2026-07-08)

## Open questions / TODO
- Wire the subprocess timeout (blocked only on nothing-running; trivial).
- Is the D-state killable RPC reliably killable? (TERM worked here.)
