---
type: incident
title: SqliteSaver WAL/SHM corrupt after abrupt graph.run kill
description: abrupt graph.run kill leaves `checkpoints.sqlite-wal/shm` such that
  next run dies at `PRAGMA journal_mode=WAL` with "file is not a database" even
  though main DB `integrity_check ok`; fix is park (mv) the two sidecars and relaunch
status: resolved
status_note: 2026-06-08 (recovery recipe documented)
timestamp: '2026-06-18'
---

# SqliteSaver WAL/SHM corrupt after abrupt graph.run kill

## Summary
Abruptly killing a `graph.run` process mid-write (e.g. SIGKILL of a
mid-`subprocess.run` worker, or kill -9 during `submit_pot_only`) can leave
`graph_data/checkpoints.sqlite-wal` and `-shm` in an inconsistent state.
The next graph.run dies at `conn.execute("PRAGMA journal_mode=WAL;")` in
`graph/run.py:82` with `sqlite3.DatabaseError: file is not a database`, even
though the **main** `checkpoints.sqlite` is fine (`PRAGMA integrity_check;
→ ok`) and its first 16 bytes are still the SQLite magic `SQLite format 3\0`.

## Key facts
- Symptom log line: `sqlite3.DatabaseError: file is not a database` raised
  from `conn.execute("PRAGMA journal_mode=WAL;")` (`graph/run.py:82`).
  Also fires from any `sqlite3.connect(...).execute('PRAGMA ...')` and
  from the system `sqlite3` CLI's `PRAGMA integrity_check;` until WAL/SHM
  are removed.
- Root cause: prior graph.run was killed while it held the WAL lock; the
  sidecar is partially-flushed and SQLite refuses to reconcile it with the
  main file. (Observed 2026-06-08 after the abandon-grid-run wipe in
  [steppointmcdumper-no-edep](/incidents/steppointmcdumper-no-edep.md) flow.)
- Recovery recipe (non-destructive — main DB stays intact):
  ```bash
  mv graph_data/checkpoints.sqlite-wal /tmp/wal.parked
  mv graph_data/checkpoints.sqlite-shm /tmp/shm.parked
  sqlite3 graph_data/checkpoints.sqlite "PRAGMA integrity_check;"  # → ok
  ```
  Then relaunch graph.run; SQLite recreates fresh WAL/SHM on first open.
  Park (don't delete) until the relaunched run succeeds, in case any
  uncommitted state needs to be salvaged from the parked WAL.
- **Cost of recovery:** any checkpoint writes that landed only in the WAL
  (not yet checkpointed back to main) are LOST. For graph.run this is
  fine — `--config-name pt001` is idempotent and the prior run's
  per-stage `cluster.txt` already lives on the filesystem. For closed_loop
  multi-round state this could be a real loss; back up the WAL before
  parking if a long-running campaign was mid-flight.
- **No `fuser` lock visible** even when the DB is unreadable — the killed
  process is gone but its WAL state persists. Don't waste time looking
  for who holds the file.
- **The checkpoint DB is SHARED across all concurrent closed-loop campaigns,
  so a kill's blast radius is cross-campaign (2026-06-18).** Both live parents
  (foilsf16 pid 270874 + pt6d08 pid 624844) held open fds on the *same*
  `checkpoints.sqlite` + `-wal` + `-shm`. Resolved path is
  **`/tmp/oksuzian/checkpoints.sqlite`** (`graph/config.py:18`
  `CHECKPOINT_DB = _CHECKPOINT_DIR / "checkpoints.sqlite"`; `_CHECKPOINT_DIR`
  → `/tmp/oksuzian`, NOT the `graph_data/checkpoints.sqlite` this page's older
  notes assume — verify with `ls -l /proc/<pid>/fd`). Consequence: SIGKILL of
  ONE campaign mid-write can corrupt the WAL and crash the OTHER on its next
  checkpoint write. **When ≥2 closed-loops run concurrently, prefer SIGTERM
  (graceful) over SIGKILL, or wait for one to finish; never `kill -9`.**
- **DECOUPLE concurrent campaigns via `AUTORESEARCH_CHECKPOINT_DIR`
  (`graph/config.py:16`).** The checkpoint dir is env-overridable:
  `_CHECKPOINT_DIR = os.environ.get("AUTORESEARCH_CHECKPOINT_DIR",
  f"/tmp/{USER}")`. Export e.g. `AUTORESEARCH_CHECKPOINT_DIR=/tmp/oksuzian_pt`
  in the second campaign's session and it writes a SEPARATE
  `checkpoints.sqlite` → zero shared-WAL coupling, so a kill (even SIGKILL)
  of one can no longer corrupt the other. Recommended whenever deliberately
  running two campaigns at once. (`/tmp` is node-local, so campaigns that
  happen to land on different GPVM nodes are already decoupled; the env var
  guarantees it regardless of node.)

## Cross-links
- Related: [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (WAL-mode adoption rationale +
  smoke-test results), [langgraph-checkpoint-numpy-int64](/incidents/langgraph-checkpoint-numpy-int64.md) (separate
  msgpack-serialization checkpoint failure mode), [kerberos-mid-run-expiry](/incidents/kerberos-mid-run-expiry.md)
  (another way graph.run dies abruptly mid-write)
- Source: `graph/run.py:74-83` (sqlite connect + WAL pragma), `graph_data/checkpoints.sqlite`

## Open questions / TODO
- Should `graph/run.py` catch `sqlite3.DatabaseError` at the WAL-pragma
  call and auto-park the sidecars (with a loud warning) instead of
  crashing? Pro: shorter recovery loop. Con: hides actual corruption of
  the main DB.
