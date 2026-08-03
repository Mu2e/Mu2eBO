---
type: incident
title: closed-loop SqliteSaver checkpoint transient corruption
description: foilsf08R00 10/10 children crashed at SqliteSaver.put_writes with "file
  is not a database" ~30-45min after launch; post-crash integrity_check passes (transient
  WAL-side, not on-disk); parent hung at barrier 3h with completed=0; likely stale-WAL
  or CephFS lock-jitter despite SQLITE_TIMEOUT_S=30
status: resolved
timestamp: '2026-07-17'
---

# closed-loop SqliteSaver checkpoint transient corruption

## Summary
foilsf08R00 (first live qlnei run, 10 parallel `graph.run` children writing the shared `graph_data/checkpoints.sqlite` via langgraph `SqliteSaver.put_writes`) ALL 10 children crashed at roughly the same wall-clock with `sqlite3.DatabaseError: file is not a database` (9 children) or `database disk image is malformed` (R00_08). Parent then sat in the barrier-poll loop for ~3h with `completed=0` because it could not read terminal state for any child. After the crash, `PRAGMA integrity_check` and `.tables` against the *same* file pass — so the corruption was *transient at write time*, not a permanent on-disk corruption.

## Key facts
- Crash signature: `sqlite3.DatabaseError: file is not a database` at `.venv-graph/lib/python3.11/site-packages/langgraph/checkpoint/sqlite/__init__.py:468` in `put_writes` → `cur.executemany(...)`. One child (R00_08) hit `database disk image is malformed` instead — same root cause, different symptom under the WAL fsync window.
- **"file is not a database" is misleading wording** — it is SQLite's page-header-malformed error (a page read returned bytes that don't match SQLite's expected magic/format), NOT a missing-file error. The file existed and was readable; a *page* inside it was unreadable. So the diagnostic move is `PRAGMA integrity_check` (which tests page-by-page after the dust settles), not `ls`.
- All 10 children crashed within the same ~30-45 min window (~16:30 wall-clock), well after the 90s-staggered launch — so it was not a launch-time race. They had been polling/writing fine for ~half an hour each.
- `checkpoints.sqlite` mtime AFTER the crash: 2026-06-08 07:50 (well before the foilsf08 launch). The crashed writes never made it to the main DB file — they were caught mid-WAL.
- Post-crash integrity passes: `sqlite3 checkpoints.sqlite "PRAGMA integrity_check"` → `ok`; `.tables` → `checkpoints  writes`. The DB itself survived; only the in-flight writes were lost.
- WAL files at crash time: `checkpoints.sqlite-shm` 32K, `checkpoints.sqlite-wal` 486K — non-empty, consistent with WAL-mode writes that never committed.
- **Why this differs from prior closed-loop runs**: foilsf01-07 ran q=10 successfully against the same DB. The only structural delta in foilsf08 was the picker (qlnei vs qnehvi) — but the picker only affects the parent's pre-launch subprocess, NOT the children's runtime checkpointer. So the picker is unlikely to be causal; more probable culprits:
  1. **Stale WAL from prior foilsf07 run** that crashed/was killed unclean → WAL contained writes from an old `journal_mode` state; first concurrent writer triggered cascade
  2. **CephFS lock-acquire jitter** spiking past the `SQLITE_TIMEOUT_S=30` floor + many-small-writer pattern from 10 children + parent barrier-poll = SQLite gives up and returns "not a database"
  3. **SQLite WAL on CephFS** is a known sharp-edge — `mmap` semantics under network FS can corrupt WAL pages even when each individual writer is well-behaved
- Parent (PID 2068057) was hung at barrier for ~3h, 0 completions, blocking ~94 still-running grid jobs whose outputs no consumer would ever harvest.
- Recovery checklist (after operator authorization): kill parent → `jobsub_rm` the in-flight grid jobs → `mv graph_data/checkpoints.sqlite{,-shm,-wal} /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/forensics/foilsf08_crash_<ts>/` (do NOT delete; the WAL has the unwritten state) → relaunch fresh.

## PREVENTION for CONCURRENT campaigns (2026-06-28)
Running TWO closed_loop parents at once (e.g. foilsflash03 + pt6d18) is a sharp
amplifier of this bug: both default to the SAME checkpoint file
`/tmp/$USER/checkpoints.sqlite` (`graph/config.py:16-18`,
`AUTORESEARCH_CHECKPOINT_DIR` env, default `/tmp/$USER`), so two parents + their
~20 children all WAL-write one DB → corruption near-certain. **RULE: each concurrent
campaign MUST get its own `AUTORESEARCH_CHECKPOINT_DIR`.** Launch with e.g.
`AUTORESEARCH_CHECKPOINT_DIR=/tmp/$USER/<prefix> nohup python -m graph.closed_loop …`.
The parent passes its env to children (subprocess inherits os.environ), so one export
isolates the whole campaign. Verify post-launch that the two `checkpoints.sqlite`
paths differ and have independent sizes. (foilsflash03 kept the default; pt6d18 got
`/tmp/$USER/pt6d18` — confirmed separate.)
**Second concurrent-campaign cost — GRID-SLOT contention (2026-06-28):** a high-njobs
campaign STARVES a co-running lighter one. pt6d18 (prodtarget6d, q=10 × pot_only
800 = ~8000 jobs) hogged the grid; foilsflash03's elebeam_flash jobs sat
`queue:0/100 settled:0/100` (0 running) for >1 h, so foilsflash03 landed 0 rows at
~3 h despite all children reaching the final stage. Not a stall — pure slot
contention; the lighter campaign drains only as the heavy one's jobs finish. Plan
concurrent campaigns accordingly (stagger, or don't pair two 800-njob campaigns).

## Root-cause fix (2026-06-09) — upstream None-rejection in cmd_evaluate
**Status:** patched at `bo_driver.py:1338`.

**The chain in one line:** qlnei picker → `AUTORESEARCH_NO_RUN1B=1` → `run1b_mubeam` stage dropped → harvest reads no `run1b_mubeam_outputs.txt` → `calo_per_pot=None` in `summary.json` → `cmd_evaluate` rejects `calo is None` with rc=1 → `run_evaluate` parses no `obj=...` line → `node_evaluate` records `obj_unparseable` zero_row and returns `objective: None` to state → langgraph `SqliteSaver.put_writes` chokes serializing the None-bearing state with msgpack (manifests as `sqlite3.DatabaseError: file is not a database` because the partial frame leaves an unreadable page).

**Fix:** when `AUTORESEARCH_NO_RUN1B=1` AND `calo is None`, substitute `calo=0.0` so `obj = sob - α·0 = sob` matches qlnei's sob-only objective. The row lands, state is fully populated, checkpoint serializes cleanly.

```python
# bo_driver.py:1338
if calo is None and os.environ.get("AUTORESEARCH_NO_RUN1B") == "1":
    calo = 0.0
if sob is None or calo is None:
    return 1
```

**Why the WAL/CephFS story is still partly real but not load-bearing:** the on-disk forensics (3-agent re-review below) showed intact DB + WAL bytes; the per-process "file is not a database" comes from msgpack-side failure during `put_writes`, not from CephFS WAL incoherence. The `CHECKPOINT_DB → /tmp` change in `graph/config.py:7-18` is cheap insurance for the real `-readonly disk I/O error` artifact but does NOT fix foilsf08; the bug above did.

**Verification gate (PASSED 2026-06-09):** foilsf09R00 (qlnei q=10, fresh prefix, NOT pre-staged) completed cleanly: 10/10 leaderboard rows landed (sob 3.87–3.90), zero `obj_unparseable`, zero SqliteSaver crashes, parent reached `completed=10` then advanced to round 1. End-to-end fix validation on a fresh run, not just the recovered-config path.

**Post-fix recovery recipe (no grid re-run, used 2026-06-09 to recover all 10 foilsf08R00 configs):** when a closed-loop crash leaves complete-but-broken harvests on disk (sob populated, calo=None) AND the proposal geoms still exist in `bo_foils_proposals/`, the rows are recoverable without re-running the grid. Per config: `AUTORESEARCH_NO_RUN1B=1 .venv-graph/bin/python bo_driver.py --mode foilsf evaluate <name> <grid_dir>/harvest/summary.json`. This calls the patched `cmd_evaluate` directly, lands the leaderboard row, and clears the pending entry — bypassing the langgraph state machine entirely. Recovered 10/10 foilsf08R00 rows (sob 3.75–3.89) in <10 seconds.

## Corrected timeline + causal chain (3-agent re-review 2026-06-09)
The "Verified root cause" block below was **partially refuted** by a follow-up 3-agent investigation (Skeptic + Forensics + Reproducer). Keep below for reference but read this section first.

- **"All 10 crashed within ~30-45 min window" is wrong.** Per-child log mtimes: 15:57:09 (R00_00) → 16:09:25 (R00_09), monotone with PID launch order, **12-min spread**. Each child crashed **30-60 s after its own launch**. The "same window" is the launch window, not a crash burst.
- **Every child shows the IDENTICAL sequence**: `preflight: pass ×7` → `[graph] zero_row[foilsf08R00_XX] cause=obj_unparseable` (harvest returned `s_over_sqrt_b=3.89, calo_per_pot=None`) → one more `preflight: pass` → crash at `put_writes`. Proximate trigger is langgraph trying to checkpoint a **None-bearing state**, not a slow cache-eviction divergence.
- **foilsf08-specific delta was NOT `--picker qlnei` or `AUTORESEARCH_NO_RUN1B`.** It was that **foilsf08R00 resumed pre-staged grid state**: per-config `state/` dir mtime 15:48 (before R00 launch), pre-existing `mubeam_cluster.txt` + `mustops_ce_cluster.txt` + a complete-but-broken harvest. Each child went straight to harvest, got `calo_per_pot=None`, then died on checkpoint write.
- **Bytes-level forensics show INTACT disk state** (agent `cp -a` to /tmp, then `sqlite3` read-back): main DB header valid (`SQLite format 3`, WAL mode, sqlite_version=3050004), -wal header valid (magic `0x377F0682`, fmt 3007000, 118 frames clean), -shm WalIndexHdr both copies byte-identical, shm/WAL salts `0x43CED797`/`0x56003144` match, `integrity_check` → ok, full read-back: 11,773 checkpoints + 46,356 writes, `wal_checkpoint(TRUNCATE)` → `0|0|0`. **No on-disk corruption visible** — per-process `sqlite3` views were broken, not the bytes.
- **One CephFS-specific anomaly DID surface**: `sqlite3 -readonly` against original WAL on `/exp/mu2e/app` returned `disk I/O error`; copying to `/tmp` first fixed it. So CephFS has WAL-handling rough edges — but foilsf08 looks more like an upstream poisoned-write cascade than pure mmap incoherence.
- **Implication for the fix**: `CHECKPOINT_DB` → `/tmp` is still defensible (cheap insurance + the `-readonly` artifact is real) but likely treats the SYMPTOM. The unfixed REAL bug is upstream: (a) why did resumed configs harvest with `calo_per_pot=None`, and (b) why does langgraph's checkpoint serializer crash on a None-bearing state instead of writing it. Both are foilsf08-specific and would re-bite on /tmp.
- **Reproducer**: `tests/test_wal_multiwriter_stress.py` (~190 lines, not executed). 11 spawned procs, real `SqliteSaver.put_writes()`, error classification + kill-switch via `mp.Event`. `CELL_DURATION_S=15min` may be too short — production crash hit 30-60s only because state was pre-staged; clean cells may need 30+ min.

## Verified root cause (agent investigation 2026-06-09)
**WAL mode on CephFS with 11 concurrent processes** is documented-unsafe by SQLite itself ([sqlite.org/wal.html §1, §7](https://www.sqlite.org/wal.html)): "WAL does not work over a network filesystem … wal-index would diverge → corruption". The wal-index lives in the `-shm` file and requires POSIX-coherent shared `mmap()` across processes; CephFS does not guarantee that.

- 11 processes hammer the same DB: parent's `node_barrier` opens its own conn at `graph/closed_loop.py:482-483` and polls `child_graph.get_state()` every 300s (each tick runs `cursor()` → `conn.commit()` through the WAL); parent's `main` opens a SECOND saver at `closed_loop.py:664-665`; each of 10 children opens a fresh conn at `graph/run.py:74-82`. Total = 12 conns, 11 distinct processes.
- `SqliteSaver` (`langgraph-checkpoint-sqlite 3.1.0`) is single-conn, `check_same_thread=False`, lock = `threading.Lock` — gives zero cross-process protection. Its own docstring (`sqlite/__init__.py:49-53`) warns "meant for lightweight, synchronous use cases".
- `setup()` runs `PRAGMA journal_mode=WAL` on first cursor (`sqlite/__init__.py:141`) — so every process is in WAL the moment it touches the saver. No fallback to rollback-journal mode without intercepting setup().
- Disk forensics match the WAL-divergence story exactly: main `.sqlite` mtime stuck at 07:50 (last clean checkpoint, prior day), `-wal` mtime 15:51 (486 KB), `-shm` mtime 17:49, crashes at 19:19. Main file passes `integrity_check` because the WAL never flushed — it just diverged across processes and was abandoned.
- foilsf01-07 success history is consistent: corruption is probabilistic, depends on cache eviction + `wal_autocheckpoint=1000` page pressure; q=10 hits it within ~30-45 min reliably. Prior wiki "WAL safety smoke" (25 writes / 30s in 2026-05-21 resolved bullet of [closed-loop-bo-design](/concepts/closed-loop-bo-design.md)) was 3 orders below the load that trips it — that "resolved" claim is overconfident.

## Fix proposals (ranked)
1. **Move `CHECKPOINT_DB` off CephFS to node-local** (`/tmp/<user>/checkpoints.sqlite` or `/scratch/...`). Edit `graph/config.py:9` only. Minimum sufficient fix; tradeoff is DB lost on host migration (acceptable — only needs to live one run).
2. **Drop WAL → `journal_mode=DELETE` + `synchronous=FULL`**. Must intercept `SqliteSaver.setup()` or open DB and never call setup (table-create script forces WAL on first cursor). Slower but Ceph-safe. Combine with #1 for belt-and-braces.
3. **Per-process DB + barrier-via-filesystem-state**. Larger refactor; kills the LangGraph-outer-graph deletion-test rationale ([closed-loop-bo-design](/concepts/closed-loop-bo-design.md) "Driver shape" entry).

## Reproducibility check (cheap, no grid)
50-line `tests/test_wal_multiwriter_stress.py`: spawn 11 `multiprocessing.Process` workers each calling `SqliteSaver.put_writes()` against `graph_data/test_stress.sqlite` for 1000 iterations. Run twice — once on `/exp/mu2e/app` (expect corruption in minutes), once on `/tmp` (expect zero failures). <30 min wall.

## Cross-links
- Related: [closed-loop-bo-design](/concepts/closed-loop-bo-design.md) (existing WAL + lock-timeout design; this incident is a counterexample to "WAL + 30s timeout absorbs Ceph jitter"), [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md) (first live test, where this surfaced), [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md) (Ceph is the underlying FS), [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)
- Source files: `.venv-graph/lib/python3.11/site-packages/langgraph/checkpoint/sqlite/__init__.py:468` (the failing call), `graph/config.py:139` (`SQLITE_TIMEOUT_S = 30.0`)

- **All modes share the SAME `CHECKPOINT_DB`** — `graph/config.py:9` `CHECKPOINT_DB = GRAPH_DATA / "checkpoints.sqlite"` is hardcoded with no mode keying. Both `graph/run.py:75` and `graph/closed_loop.py:90,181-183` open this exact path. So if a `prodtarget` closed-loop and a `foilsf` closed-loop run simultaneously they will hammer the same WAL with 2× the writer count (2 parents + 20 children). Tonight's foilsf08 crash was NOT caused by a parallel prodtarget run (no prodtarget activity in `closed_loop_logs/` today), but the design hazard is real for the next parallel campaign — consider per-mode DB paths.

## Open questions / TODO
- Reproduce: relaunch foilsf08 with a fresh `checkpoints.sqlite` and same picker — does it recur? If yes, qlnei or shared-DB is the issue. If no, it was the stale-WAL theory.
- Consider: switch checkpoints.sqlite from CephFS to a node-local tmpfs path (the file is single-host anyway; only need durability across one closed-loop run).
- Consider: add a parent-side health check that times the barrier-poll out earlier when ALL children are reporting `completed=0` after their typical end-to-end ETA + 1h.
- Document the operator runbook for "checkpoint crash mid-round" in [closed-loop-runner](/drivers/closed-loop-runner.md) once the fix is in.
