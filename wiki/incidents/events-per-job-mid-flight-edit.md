# Mid-flight `events_per_job` edit silently mis-scales harvest metrics

**Type:** incident
**Status:** resolved (stamping fix landed 2026-05-21 in `pipeline.py`)
**Updated:** 2026-05-29 (SHA check extended from harvest-only to also fire at poll + list-outputs)

## Summary
`pipeline.py` reads its `STAGES` dict at **both** submit time (to bake
`--events-per-job` into the `mu2ejobdef`) and at harvest time (to compute
`ce_simulated_events` and `mubeam_sim_total` denominators). Editing
`STAGES[stage]["events_per_job"]` *between* submit and harvest leaves the
grid jobs running with the old value but the harvest reading the new value,
which silently scales the leaderboard's `sob` by `old/new`. Discovered
2026-05-21 when a 5000→2500 tuning cut on `mustops_ce` was applied while
helicalP01-P05 chains were in flight; helicalP01 and helicalP03 had
already created their `mu2ejobdef` (with 5000) but were harvested with the
new dict value (2500), so both leaderboard rows came back at **2× the true
`sob`** (P01: 7.46 → corrected 3.73; P03: 6.21 → corrected 3.10).

## Key facts
- **Mechanism.** `cmd_submit` calls `_build_mu2ejobdef` which captures
  `STAGES[stage]["events_per_job"]` at the moment `submit_stage` runs and
  bakes it into the jobdef. `cmd_harvest` later reads the *current* dict
  via `_events_per_job(stage)` to compute denominators. If the dict is
  edited between, the divisor is wrong:
    `ce_scale = input_corr · stopping_factor / ce_simulated_events`
    `ce_abs_eff = ce_seen · ce_scale`
  Halving `ce_simulated_events` doubles `ce_abs_eff`, which doubles `sob`.
- **Stamping fix (pipeline.py:325-333).** `submit_stage` now writes
  `state/<stage>_events_per_job.txt` containing the value at submit time.
  Helper `_events_per_job(stage)` (pipeline.py:582) reads the stamp if
  present, else falls back to `STAGES[stage]["events_per_job"]` for
  backward compat. The three harvest call sites
  (`mubeam_sim_total`, `ce_simulated_events`, `total_events` in
  `_extract_calo_per_pot`) all use the helper.
- **Heuristic that misled the initial forensic table.** I tried to
  reconstruct which chains used 5000 vs 2500 by comparing
  `state/<stage>_cluster.txt` mtime vs my edit time. **This is wrong.**
  `cluster.txt` is written *after* `jobsub` returns the cluster ID, which
  itself runs *after* `mu2ejobdef` (where STAGES is captured). So
  cluster.txt mtime > edit time does **not** mean the jobdef was created
  with the new value. The only authoritative source is the per-worker
  log's `source.maxEvents:` line on /pnfs (or the jobdef artifact itself).
  Verified by: `grep "source.maxEvents" /pnfs/.../log.*.log`.
- **Truth table for helicalP01-P05 mustops_ce** (pipeline.py edit was
  07:34:24; mustops_ce cluster.txt mtimes ranged 07:28-07:41):

  | chain | source.maxEvents in worker log | leaderboard sob (broken) | corrected sob |
  |---|---|---|---|
  | P01 | 5000 | 7.46 | **3.73** |
  | P02 | 2500 | 2.81 | 2.81 |
  | P03 | 5000 | 6.21 | **3.10** |
  | P04 | 2500 | 3.44 | 3.44 |
  | P05 | 2500 | 3.32 | 3.32 |

  Both P01 and P03 had submitted with 5000 despite cluster.txt mtime
  appearing after the edit, because their jobdef creation happened before
  the edit (submit pipeline phase takes ~3-10 min to reach the
  cluster.txt write).
- **Corrected leaderboard standings.** After re-harvest, true new best is
  helicalP01 `sob=3.73` — only **+2.2%** over the previous best
  helical050a_n5000 (`sob=3.65`), not the 2× claimed under the broken
  divisor. P03 is no longer near-best (3.10 < P04 3.44 < P05 3.32).
- **Manual remediation done (2026-05-21).** Wrote
  `state/mustops_ce_events_per_job.txt` containing `5000` for both
  helicalP01 and helicalP03, stripped their broken rows from
  `leaderboard_bo_helical_v2.tsv` (backup at `.tsv.bak_<timestamp>`),
  re-ran `pipeline.py harvest` + `evaluate` for each, regenerated GP
  predictions + overlay plot.

## Config-SHA guard fires on ANY STAGES edit, even harmless ones (2026-07-02)
The `_stamp_stage_config_sha` guard hashes the **whole stage dict**, so editing *any*
field mid-flight trips the "STAGES['<stage>'] changed since submit (stamp=… current=…)"
warning for **all in-flight children's** downstream poll/list-outputs/harvest — including a
**metric-harmless `memory_mb` change** (observed when foilsflash `memory_mb` 3500→2500 was
applied while foilsflash06 was running: all 20 children's harvest logs printed 2 SHA warnings).
**It is ADVISORY, not fatal** — 19/20 ff06 children harvested fine *with* the warnings; the 1
loss (`R00_07`) was an unrelated `mustops_ce` grid failure (1/15 outputs). But the guard
**can't distinguish a safe `memory_mb` edit from a metric-breaking `events_per_job` edit** — it
cries wolf, and the noise can mask a real drift. Lesson: prefer to make even harmless `STAGES`
edits **between** campaigns; if you must edit mid-flight (memory is safe — affects slot-matching
only, not metrics/quorum), expect the warnings and verify harvests still land.

## Cross-links
- Related: [[pipeline]], [[harvest-denominator-bug]] (sister bug — wrong
  denom from STAGES.njobs), [[autoresearch-bo-michael]]
- Source: `pipeline.py:325-333` (stamp write), `pipeline.py:582-593`
  (`_events_per_job` helper), `pipeline.py:674-675` (harvest sites)
- Backup: `leaderboard_bo_helical_v2.tsv.bak_*`

## Open questions / TODO
- Same stamping pattern should be applied to other params that are
  baked into the jobdef and re-read at harvest. Candidates: `njobs`
  (already mitigated by deriving denom from outputs.txt — see
  [[harvest-denominator-bug]]); `run_number` (so far stable). Audit
  before the next mid-flight tuning round.
- Consider hashing the entire effective `STAGES[stage]` dict at submit
  and stamping the hash, so future divergences (memory, lifetime, etc.)
  surface as a harvest-time warning rather than silent miscalculation.
