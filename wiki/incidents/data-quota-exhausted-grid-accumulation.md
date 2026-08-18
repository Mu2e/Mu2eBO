---
type: incident
title: /data 2TB CephFS quota exhausted by autoresearch_grid accumulation → Errno
  122
description: /exp/mu2e/data/users/oksuzian 2TB CephFS quota filled by autoresearch_grid
  (2.04TB, Code.tar.bz2 accumulation) → Errno 122 EDQUOT at propose_one geom-copy;
  killed ipa02 4/5 children; diagnose with getfattr not df; 2026-06-19
status: resolved
status_note: '2026-07-24 structurally: code tarball + cnf jobdef rerouted to dCache
  scratch (LRU-purged), so /exp cost falls ~2.7 GB/eval → ~10 MB/eval and needs no
  pruning; earlier 2026-06-20 recovery deleted 1474 config dirs (freed 1.88 TB)'
timestamp: '2026-07-24'
updated_note: 'REVERSAL: the 2026-07-01 "reroute-to-/pnfs is moot, delete instead"
  conclusion was wrong (it conflated /pnfs/mu2e/tape with the disk-only LRU
  /pnfs/mu2e/scratch); reroute implemented + dry-run verified. Also found the
  687.5 GB / 1271 orphaned unpacked Code/ trees the tar-only census had missed.'
---

# /data 2TB CephFS quota exhausted by autoresearch_grid accumulation → Errno 122

## Summary
The per-user CephFS **byte quota on `/exp/mu2e/data/users/oksuzian` (2.0 TB)**
filled up and every closed-loop child began crashing with
`OSError: [Errno 122] Disk quota exceeded` at the geom-copy in
`graph/pipeline_io.py:93` (`shutil.copy` into
`GRID_DATA_ROOT/<config>/geom/`). In the child graph this surfaces as a crash in
the **`propose` node** — the child log ends with
`During task with name 'propose' and id ...` (the LangGraph error-context line)
above the Errno-122 traceback. Affects ALL campaigns writing to /data at once:
ipa02 lost 4/5 R0 children; foilsf20 + pt6d11 were next.

## Key facts
- **It is a CephFS DIRECTORY quota, NOT filesystem-full.** `df` lies here:
  `/exp/mu2e/data` was 17% used (67 TB free) yet writes failed. The cap is a
  per-directory xattr. **Diagnose with getfattr, not df:**
  ```
  getfattr -n ceph.quota.max_bytes -n ceph.dir.rbytes /exp/mu2e/data/users/oksuzian
  ```
  Observed: `max_bytes=2147483648000` (2.0 TB), `rbytes=2147977326981`
  (2.0004 TB) → **100.02%, OVER**. The quota is on the **user dir**, not on
  `autoresearch_grid` (which has no own quota) — child quotas are hierarchical,
  so a parent cap bites writes anywhere beneath it.
- **`ceph.dir.rbytes` updates LAZILY — do NOT trust it immediately after a bulk delete (2026-07-01).**
  After `find -delete` of 1633 tars (~464 GB), the instant re-read of `rbytes` was UNCHANGED
  (1013.7 GB before AND after → "0 GB reclaimed"), even though the files were gone (verified by
  re-globbing: 0 matches remained). The MDS recomputes recursive `rbytes` asynchronously; it settled
  to the correct 550.1 GB seconds later. **Don't panic at "0 GB freed" and re-run the delete** — confirm
  the delete by counting remaining files (`find ... | wc -l`), then re-read `rbytes` after a short wait.
- **Dominant consumer = `autoresearch_grid` (2.04 TB, 95% of the user quota;
  ~13.2M files; 1655 config dirs).** Per-config footprint (measured via rbytes
  2026-06-20): a completed **foils** config ≈ **6.7 GB** — `Code.tar.bz2` is
  **710 MB × ~3 stages ≈ 2.1 GB**, plus a similarly-sized unpacked `Code/` dir
  per stage; i.e. **~all 6.7 GB is regenerable muse code artifacts**. Older
  configs are smaller (foilsZ ~0.7 GB, helical ~0.5 GB; prodtarget pot_only ~4 MB).
  Top-level /data siblings are negligible (autoresearch_runs 38 GB, Run1B 19 GB,
  venvs 8 GB). **Cleanup yield: deleting `Code.tar.bz2` only ≈ 2.1 GB/foils
  config; deleting whole COMPLETED-config dirs ≈ 6.7 GB each** (also safe — the
  leaderboard row is already extracted, the working dir is dead weight) → the
  whole-dir route frees ~3× more, likely >1 TB across the foils-family configs.
- **Second, separate squeeze: the /app quota.**
  `/exp/mu2e/app/users/oksuzian` = `ceph.quota.max_bytes` **86 GB**, ~99.8% full.
  Breaks leaderboard/proposal/log/wiki writes on app. (App tightness is also why
  the venvs were moved to /data — [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md).)
  **App consumers (rbytes, 2026-06-20): stale `muse_*` build areas dominate** —
  `muse_101323` 21.6 GB (2025-09), `muse_080224` 8.3 GB (2025-08), `muse_050125`
  4.8 GB (2026-04); `Run1B` 14 GB. Cleanup target = the 2 oldest muse builds
  (~30 GB, ~9-10 mo stale, rebuildable). **KEEP the active musings**
  `Offline_helical` (foils/foilsf/foilsg) + `autoresearch_muse_prodtarget`
  (prodtarget) + `autoresearch_muse` — sourced by `MUSING_BY_MODE`. NOTE: the
  /app quota was NOT cleaned during the first 2026-06-20 /data recovery.
  **RESOLVED 2026-06-20:** deleted `muse_101323` + `muse_080224` → /app 85.7→55.8
  GB (99.8%→65%, 30 GB free).
- **~~Reroute-to-/pnfs does NOT apply; deletion is the only lever~~ — REFUTED 2026-07-24, reroute DONE.**
  The 2026-07-01 measurement stands (**`Code.tar.bz2` + `cnf.*.tar` = 579 GB / 63% of 913 GB**; `harvest/`
  only 1.1 GB; grid `.art` outputs already on `/pnfs/.../outstage/`). The *conclusion* was wrong, on one
  bad premise: **"/pnfs is tape-backed dCache — a bad target for build tars"** conflates
  `/pnfs/mu2e/tape` with **`/pnfs/mu2e/scratch`, which is disk-only and LRU-purged, never tape-backed.**
  Measured facts that overturn it:
  - **Scratch retention ≈ 5-8 weeks** (sampled our own outstage: content intact at 36 d, partial at 2 mo)
    vs a cluster lifetime of **<24 h** — so "LRU could evict a live jobdef" is not a real failure mode.
  - **dCache accepts sequential writes at 415 MB/s** and refuses only random-access writes
    (`seek`+`write` → `PermissionError: EPERM`).
  - **`mu2ejobdef` writes exactly that pattern**: `sysopen(O_CREAT|O_EXCL|O_WRONLY)` + one
    `Archive::Tar->write` (it *deliberately* avoids `tar --append`, which "produces corrupt tarballs" —
    its own comment). It also has a first-class **`--outdir`** flag (default `.`).
  - `mu2ejobfcl`/`mu2ejobsub` resolve `--jobdef` through `mu2egrid::find_file` → `abs_path()`, so an
    absolute `/pnfs` path works from any cwd.
  **Both blobs now write to `/pnfs/mu2e/scratch/users/$USER/autoresearch_grid/<cfg>/`** and age out on
  their own — ~2.7 GB/eval that no longer touches the quota and needs no pruning hook. Verified by a real
  `submit --dry-run` (tarball → scratch, `mu2ejobdef --outdir` → scratch, `mu2ejobfcl` readback OK).
  Caveat that keeps the *unpack* tree local: dCache is bad at many-small-files, and `Code/` is ~1000 of them.
- **Blast radius:** with 3 concurrent campaigns, the quota fills faster and ALL
  of them fail their next /data write simultaneously. Children crash in the
  graph `propose` node; the closed-loop barrier then reports them
  "died without resolution (no leaderboard row / broken.txt / terminal
  checkpoint)".

## Fix / recovery
- **Free /data.** Safe high-yield target: delete `Code.tar.bz2` in
  COMPLETED-config stage dirs — they are muse-regenerated on the next submit and
  useless once a config is done. Also old completed-campaign config dirs
  (foilsZ*/foilsf01–19/helical*/pt6d01–10/…). Use **named-path** deletes, never
  wildcard `rm` (see memory `feedback_avoid_rm_rf_star`).
- **Pause campaigns first** (SIGTERM, not -9 — shared-checkpoint safety,
  [sqlite-wal-corrupt-after-kill](/incidents/sqlite-wal-corrupt-after-kill.md)) so they stop churning failed children while
  you clean, then relaunch.
- **Outcome (2026-06-20):** deleting the 1474 completed-config dirs (everything
  matching `*R[0-9][0-9]_[0-9][0-9]` except the 3 active prefixes) freed
  **1.88 TB** (2148→269 GB, 12%). So the per-config footprint averaged ~1.3 GB
  (foils ~6.7 GB, old helical/foilsZ smaller). Whole-dir deletion was the right
  call — Code.tar.bz2-only would have freed ~3× less. Then killed the 3 stuck
  campaigns (SIGTERM) and relaunched fresh (new prefixes + fresh decoupled
  checkpoint dirs, since post-SIGTERM WALs may be dirty — [sqlite-wal-corrupt-after-kill](/incidents/sqlite-wal-corrupt-after-kill.md)).
- **Prevention — DONE 2026-07-24, and no hook was needed.** Rather than pruning,
  the two big blobs were rerouted to dCache scratch (see the REFUTED bullet
  above), where LRU purges them. `core/pipeline.py` `_bind_config` now binds
  `PNFS_ROOT`; `write_code_tarball` streams bzip2 straight there and
  `submit_stage` passes `mu2ejobdef --outdir`. Steady-state /exp cost per eval
  drops from **~2.7 GB to ~10 MB** (geom + state + harvest only).
- **Second leak, distinct and already fixed: 1271 orphaned unpacked `Code/` trees
  = 687.5 GB / 3.58M files (found 2026-07-24).** `write_code_tarball` extracted
  `Code/` into the stage dir, repacked, and never removed the tree; the
  `rmtree` at the START of the function only cleaned it on a *repeat* call to the
  same stage. Fixed at `core/pipeline.py:545` (`shutil.rmtree(code_dir,
  ignore_errors=True)`) on 2026-07-10, which the mtimes confirm — **no orphan tree
  is newer than 2026-07-10 07:27**. What remained was pure pre-fix debris.
  This is why the 2026-07-01 tarball census (579 GB) didn't add up to the 1.16 TB
  actually on disk: **it counted `*.tar*` files and missed the unpacked trees.**

## Cross-links
- Related: [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md) (same Errno 122 but at the
  jobsub RCDS-publish step, not the geom-copy), [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md)
  (app-volume tightness), [closed-loop-runner](/drivers/closed-loop-runner.md)
- Source: `graph/pipeline_io.py:93` (propose_one geom-copy),
  `graph/config.py:25` (`GRID_DATA_ROOT`)

## Open questions / TODO
- Decide a retention policy for `autoresearch_grid` (auto-prune Code.tar.bz2
  post-harvest? cap configs kept?).
- Request a /data quota bump vs. routine pruning.
