---
type: incident
title: kerberos-mid-run-expiry — closed_loop chains die at first stage submitted
  after token expiry
description: closed_loop has no token watchdog; krb5 expiry mid-round → Errno 127
  ENOKEY at subprocess.run → graph terminates before harvest, no leaderboard row
status: resolved
status_note: (workaround documented; no auto-renew yet)
timestamp: '2026-05-21'
---

# kerberos-mid-run-expiry — closed_loop chains die at first stage submitted after token expiry

## Summary
First real `closed_loop.py` run (`closed_helicalQ_r0`, 2026-05-21) lost all 5
children at the **concat** stage with `OSError: [Errno 127] Key has expired`
from `subprocess.run`. Kerberos ticket had expired while the chains sat in
mubeam+run1b_mubeam grid queues (~ several hours). The exec'd `pipeline.py
submit concat` failed before `getToken` could even run, the inner graph
returned `status="failed"`, `route_after_stage` terminated the iteration
before `mustops_ce` / `harvest`, and no leaderboard rows landed. Recovery
required `kinit` + `mu2einit` + `getToken` then driving `pipeline.py
--config <name> <verb> <stage>` per chain.

## Key facts
- **Symptom**: graph node logs end with `OSError: [Errno 127] Key has
  expired` raised from `subprocess.run([python, pipeline.py, ...])` —
  the python interpreter itself fails to exec under an expired krb5
  keyring on this AFS/Kerberos GPVM mount.
- **Root cause**: krb5 ticket lifetime (default ~25 h) can be shorter
  than the closed-loop wall clock for a q=5 round whose grid stages
  (mubeam ~1.5 h + run1b_mubeam ~1.5 h + idle queue time + concat +
  mustops_ce) easily run 6-8 h after `kinit`. `kx509` proxy expiry is
  the proximate trigger — `mu2ejobsub`/`getToken` need it.
- **Stage-out idempotency saved us**: `mubeam_outputs.txt` and
  `run1b_mubeam_outputs.txt` were already written, so recovery only
  needed `submit/poll/list-outputs concat` (or `list-outputs` if
  cluster was already submitted) and full mustops_ce + harvest.
- **`getToken` is per-submit, not per-poll**: `pipeline.py` only calls
  `getToken` inside `submit_stage`. `poll`/`list-outputs`/`harvest` do
  no token refresh, so a fresh ticket only helps the next *submit*. If
  poll/list-outputs themselves fail with auth errors, run `mu2einit` +
  `getToken` manually before retry.
- **No watchdog in `graph/closed_loop.py`**: the closed-loop parent
  loops in pure Python; no node renews kerberos. A long round (q=5,
  4 stages, 6-8 h wall) will hit expiry if started near a ticket's
  end-of-life.
- **Recovery recipe**:
  ```
  kinit                                           # refresh krb5 ticket
  source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
  mu2einit                                        # set up env
  getToken                                        # refresh bearer token
  # then per surviving config (cluster files preserve idempotency):
  python pipeline.py --config <name> list-outputs concat
  python pipeline.py --config <name> submit mustops_ce
  python pipeline.py --config <name> poll mustops_ce
  python pipeline.py --config <name> list-outputs mustops_ce
  # finally run harvest+evaluate via graph.run --resume or hand-call
  ```

## Cross-links
- Related: [closed-loop-runner](/drivers/closed-loop-runner.md), [concurrent-token-contention](/incidents/concurrent-token-contention.md),
  [grid-job-completion-check](/incidents/grid-job-completion-check.md), [closed-loop-parent-signal-kill-midlaunch](/incidents/closed-loop-parent-signal-kill-midlaunch.md), [sqlite-wal-corrupt-after-kill](/incidents/sqlite-wal-corrupt-after-kill.md)
- Source files: `pipeline.py` (`submit_stage` calls `getToken`),
  `graph/closed_loop.py` (no token renewal)

## Open questions / TODO
- Add a `node_renew_token` step at top of each round in
  `graph/closed_loop.py` (idempotent `kinit -R` or shell out to
  `mu2einit; getToken`). Cheap; eliminates this failure mode.
- Or: spawn a sibling watchdog that `kinit -R`s every ~12 h while the
  closed-loop parent runs.
- Detect Errno 127 in graph node and emit a clearer error message ("krb5
  ticket likely expired — run kinit") rather than burying it under
  generic `subprocess.run failed`.
