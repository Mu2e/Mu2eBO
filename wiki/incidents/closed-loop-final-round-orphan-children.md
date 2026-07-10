# closed-loop final-round children orphaned when barrier hits max_rounds early

**Type:** incident
**Status:** active (no fix yet — observed 2026-06-09 on ptX02)
**Updated:** 2026-06-09

## Summary
`graph/closed_loop.py` exits cleanly when round_idx reaches `max_rounds`
**before** the final round's barrier-poll has collected every child. Any
in-flight grid cluster from the last launched round becomes orphaned —
the leaderboard row will never be written by the parent (the child's
graph.run does write it directly on its own thread, but only if it
survives to the harvest node; the child python process is killed when
the parent process tree dies on some launch paths). Observed: ptX02
with `--max-rounds 2 --q 4` finished with 8/11 expected R0+R1 evals;
ptX02R01_03 cluster still running at parent-exit time.

## Key facts

- **Reproducer**: `--max-rounds 2 --q 4 --picker qnehvi --mode prodtarget`.
  Parent's `decide_next[r1]` log line fired with `+1 new rows
  (before=7 after=8)`, even though R1 launched 3 children (R01_00,
  R01_02, R01_03 — R01_01 died at preflight). Parent then logged
  `done. final keys: [...]` and exited; R01_03 cluster 91714271 still
  had 16 jobs Running at exit.
- **Root cause**: barrier-poll waits `barrier_timeout_min` *per round*,
  but on the **final** round the controller exits when the round
  function returns, regardless of barrier completion. There's no "drain
  all in-flight clusters before exit" guard.
- **Symptom for the user**: leaderboard short by 1-2 rows after a clean
  `done.` log; jobsub_q shows leftover clusters under the run's
  prefix; their config dirs have `pot_only/` ready but the `state/...`
  outputs land after parent exit and never get harvested into the
  leaderboard.
- **Manual harvest workaround**: after parent exits, find the orphan
  cluster ID(s) in `/exp/mu2e/data/users/oksuzian/autoresearch_grid/
  <config>/state/pot_only_cluster.txt`; wait for `jobsub_q` to show 0;
  then re-run the same `--config-name <orphan>` via `graph/run.py` to
  finish harvest. Or accept the loss for the campaign.

## Cross-links
- Related: [[closed-loop-bo-design]], [[barrier-false-positive-round1]]
- Source files: `graph/closed_loop.py` (the round loop + barrier-poll
  + final return path)

## Open questions / TODO
- Add a `drain_on_exit=True` mode that polls outstanding clusters for
  one additional `cap_hours` cycle after the last round's launch
  before returning.
- Or: alert the user when `completed < launched - preflight_failed` at
  the end of the final round, so the orphan(s) are made visible
  instead of silently lost in a clean exit.
