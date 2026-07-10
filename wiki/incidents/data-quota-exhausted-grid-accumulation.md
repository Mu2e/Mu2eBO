# /data 2TB CephFS quota exhausted by autoresearch_grid accumulation → Errno 122

**Type:** incident
**Status:** resolved 2026-06-20 (deleted 1474 completed-config dirs → freed
1.88 TB: /data 2148 GB → 269 GB = 12%); campaigns relaunched fresh
**Updated:** 2026-07-01 (re-measured: Code.tar.bz2+cnf.tar=579GB/63%, harvest only 1.1GB, outputs already on /pnfs → delete not reroute)

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
  the venvs were moved to /data — [[venv-relocated-to-data-volume]].)
  **App consumers (rbytes, 2026-06-20): stale `muse_*` build areas dominate** —
  `muse_101323` 21.6 GB (2025-09), `muse_080224` 8.3 GB (2025-08), `muse_050125`
  4.8 GB (2026-04); `Run1B` 14 GB. Cleanup target = the 2 oldest muse builds
  (~30 GB, ~9-10 mo stale, rebuildable). **KEEP the active musings**
  `Offline_helical` (foils/foilsf/foilsg) + `autoresearch_muse_prodtarget`
  (prodtarget) + `autoresearch_muse` — sourced by `MUSING_BY_MODE`. NOTE: the
  /app quota was NOT cleaned during the first 2026-06-20 /data recovery.
  **RESOLVED 2026-06-20:** deleted `muse_101323` + `muse_080224` → /app 85.7→55.8
  GB (99.8%→65%, 30 GB free).
- **Reroute-to-/pnfs does NOT apply; deletion is the only lever (measured 2026-07-01, foilsflash04 era).**
  Re-measured at 913 GB / 335 configs: **`Code.tar.bz2` + `cnf.*.tar` = 579 GB (63%, 1836 files)**, the
  rest work-tree cruft; **`harvest/` (summary.json + nts.ce.root) is only 1.1 GB total** — the sole science
  we keep. **The grid `.art` OUTPUTS already live on `/pnfs/mu2e/scratch/.../outstage/`** (default_location
  `disk`), NOT on /data — confirmed from `state/<stage>_outputs.txt`. So "move data to /pnfs scratch" is moot:
  the physics is already there; what's on /data is regenerable build cruft that should be DELETED, not moved
  (/pnfs is tape-backed dCache — a bad target for build tars anyway). **Cleanup must target BOTH `Code.tar.bz2`
  AND `cnf.*.tar`** (the cnf job-def tar embeds the code again — co-equal size; the earlier recipe named only
  Code.tar.bz2).
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
  [[sqlite-wal-corrupt-after-kill]]) so they stop churning failed children while
  you clean, then relaunch.
- **Outcome (2026-06-20):** deleting the 1474 completed-config dirs (everything
  matching `*R[0-9][0-9]_[0-9][0-9]` except the 3 active prefixes) freed
  **1.88 TB** (2148→269 GB, 12%). So the per-config footprint averaged ~1.3 GB
  (foils ~6.7 GB, old helical/foilsZ smaller). Whole-dir deletion was the right
  call — Code.tar.bz2-only would have freed ~3× less. Then killed the 3 stuck
  campaigns (SIGTERM) and relaunched fresh (new prefixes + fresh decoupled
  checkpoint dirs, since post-SIGTERM WALs may be dirty — [[sqlite-wal-corrupt-after-kill]]).
- **Prevention TODO:** a post-harvest hook that deletes a config's
  `*/Code.tar.bz2` once its leaderboard row lands would bound autoresearch_grid
  growth; right now nothing prunes it.

## Cross-links
- Related: [[jobsub-disk-quota-stderr-swallowed]] (same Errno 122 but at the
  jobsub RCDS-publish step, not the geom-copy), [[venv-relocated-to-data-volume]]
  (app-volume tightness), [[closed-loop-runner]]
- Source: `graph/pipeline_io.py:93` (propose_one geom-copy),
  `graph/config.py:25` (`GRID_DATA_ROOT`)

## Open questions / TODO
- Decide a retention policy for `autoresearch_grid` (auto-prune Code.tar.bz2
  post-harvest? cap configs kept?).
- Request a /data quota bump vs. routine pruning.
