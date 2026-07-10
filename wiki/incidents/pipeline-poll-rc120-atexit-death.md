# pipeline-poll-rc120-atexit-death

**Type:** incident
**Status:** open (2026-06-13) — root-cause refined: system-wide mu2esrv01 memory-pressure event, NOT per-child atexit bug
**Updated:** 2026-06-13

## Summary
pt6d05 R1 7/10 children (`_01,_02,_04,_05,_07,_08,_09`) passed preflight,
then died at the grid-poll step with `RuntimeError: poll pot_only failed
(rc=120)` after ~20 min of polling. Grid jobs were progressing normally
(clusters 28111454, 28111455, 91752577, 28390176, 70335541, 70335542 all
healthy in `jobsub_q` 1h+ later with 30-48/100 outstage subdirs). The
poll wrapper itself died — not the grid jobs.

**Deeper diagnosis (2026-06-13 amendment):** all 7 poll subprocesses died
in a tight 19:01:40-19:03:34 window (poll-log mtimes: 19:01:40, 19:01:46,
19:01:51, 19:03:13, 19:03:30, 19:03:34). The other live campaign on the
same node — foilsf12 R2 — *also* lost its parent + 9 children at ~19:02
(see [[closed-loop-parent-signal-kill-midlaunch]]). Two unrelated python
trees dying synchronously rules out per-child interpreter bug;
this is a **system-wide kill event on mu2esrv01 at 19:01-19:03**.
The rc=120 is the *fingerprint* (CPython TextIOWrapper teardown after
fd corruption), not the cause.

Closed-loop's `decide_next` then misread the 7 grid-killed children +
3 genuine `fail_managed` (real spacer-vs-plate overlap) as "0 new rows,
all failed → exit early", and quit R2 silently. Same SURFACE symptom as
[[preflight-mode-tuple-prodtarget6d-omission]] (which was pt6d04 R1) but
a totally different root cause — the tuple fix did NOT prevent pt6d05's
failure mode.

## Key facts
- **rc=120 source (confirmed by direct test):** rc=120 = `OSError: [Errno 9]
  Bad file descriptor` raised in `TextIOWrapper.__del__` at interpreter
  shutdown when stdout/stderr fd has been invalidated. Reproduced with
  `python -c "import os; os.close(1); print('x')"` → exit 120. Signal
  hypotheses ruled out: SIGTERM→-15, SIGHUP→-1, SIGPIPE→ignored→0,
  unhandled exception→1, raise in atexit→0. Only fd-invalidation
  produces 120.
- **Synchronized cross-campaign death window (19:01:40-19:03:34):**
  all 7 pt6d05R01 poll-log mtimes cluster in this 114-second window,
  AND foilsf12 R2's parent + 9 children died in the same window
  ([[closed-loop-parent-signal-kill-midlaunch]]). Two independent
  python process trees dying synchronously = system-level event, not
  per-child bug.
- **session-23.scope memory.peak = 170.69 GiB (183.27 GB) ≈ 91% of
  system RAM** at the death window. session-23 is oksuzian's VNC
  session on mu2esrv01.fnal.gov (Xvnc :7, pts/3, since 2026-05-20)
  hosting BOTH closed-loop campaigns under one cgroup hierarchy
  `/user.slice/user-11549.slice/session-23.scope`.
- **cgroup OOM did NOT fire:** `memory.events` all-zero (no oom,
  oom_kill, oom_group_kill). `memory.max = max` (no cap). So the
  kill wasn't from cgroup OOM handler. But memory pressure that
  high causes cephfs writeback failures + fd-state corruption
  WITHOUT triggering OOM (especially when writeback errors propagate
  as fd-bad-state rather than process kill).
- **What the poll log shows:** clean periodic output every ~120s
  (`[HH:MM:SS] [pot_only cluster=N] queue:0/100 settled:0/100
  (target=90)`), then nothing — process died mid-`time.sleep(120)`,
  before next print would have fired. No WARN, no traceback, no
  Python error.
- **Grid status was fine throughout:** every R1 cluster that "failed"
  this way had 30-48 outstage subdirs an hour after the rc=120 kill,
  i.e. the jobs were running and writing /pnfs normally. Only the
  Python poll wrapper died.
- **`decide_next` falsely converges:** when rc=120 from poll trips
  `[graph] stage[pot_only/<cfg>] FAILED`, the child is added to
  `completed_names` with no leaderboard row. If ALL q children take
  this path (or take it + real preflight fails), `decide_next`'s
  guard "0 new rows + all q resolved → exit" fires and `closed_loop`
  exits "done" without scheduling R+1, even though q grid clusters
  are still running.
- **Spacer-vs-plate00 overlap pattern (real preflight fails):** the 3
  pt6d05R01 children with `preflight=fail_managed`
  (`_00, _03, _06`) all show overlaps between
  `ProductionTargetSpacerNegZ_{0,1,2}` and `ProductionTargetPlate00`
  (NOT against the ring as in [[prodtarget-spacer-supportring-overlap]]).
  This is a different solid pair — fixing the rod-shrink earlier did
  not cover this case. Likely the same off-by-`stickmanMagicOffset`
  precision issue affects spacer↔plate-00 contact when t0 (first plate
  thickness) sits at certain values; the spacer shrink doesn't apply
  here because spacer-to-plate axial contact differs from
  spacer-to-ring radial overlap.

## Recovery recipe (verified end-to-end 2026-06-14 on pt6d05R01 × 6)
1. Don't kill the orphan grid clusters — they're producing real data.
2. Wait for grid to finish (`jobsub_q -G mu2e --user=oksuzian | grep <cluster>`).
3. For each preflight-pass child, run **TWO** scripts manually — `evaluate`
   is NOT a pipeline.py verb; it lives in the BO driver and needs `--mode`:
   ```
   # 1+2: pipeline.py owns list-outputs + harvest-pot-only
   .venv-graph/bin/python pipeline.py --config <name> list-outputs pot_only
   .venv-graph/bin/python pipeline.py --config <name> harvest-pot-only
   # 3: autoresearch_bo_michael.py owns evaluate (with --mode)
   .venv-botorch/bin/python autoresearch_bo_michael.py --mode <mode> \
       evaluate <name> /exp/mu2e/data/users/oksuzian/autoresearch_grid/<name>/harvest/summary.json
   ```
   `evaluate` takes TWO positional args: `<config_name> <summary_json_path>`.
   It reads the summary, calls `mode.extract_extras(...)`, formats the row
   via `mode.format_row(p, alpha)`, appends to
   `leaderboard_bo_<mode>_v0.tsv`, AND clears the pending row.
4. Relaunch closed-loop with a **FRESH `--name-prefix`** (NOT the same
   prefix bumped — thread-id resume ignores new `--max-rounds`, prefix
   reuse trips [[closed-loop-stale-cluster-silent-no-launch]] and may also
   collide with checkpoint-resume bugs). Rows land under their own
   config_name and feed history.

## Ruled-out non-causes (2026-06-13)
- **cgroup OOM:** `memory.events` zero across session-23.scope.
- **systemd-logind KillUserProcesses:** =`no` (default); not active.
- **systemd-oomd / earlyoom:** both `inactive` on mu2esrv01.
- **VNC killer cron:** vnc_killer script atime 15:12, not 19:01.
- **CephFS MDS reconnect:** no recent reconnect events in dmesg
  window around 19:01.
- **NFS lost-locks:** timestamps don't align.
- **Kerberos mid-run expiry** ([[kerberos-mid-run-expiry]] mechanism):
  would manifest as Errno 127 from subprocess.run, not rc=120 from
  the wrapper itself, and wouldn't synchronize two campaigns.

## Open questions
- **Why didn't cgroup OOM fire at 170.69 GiB peak?** Either the peak
  was transient enough to not trigger oom_kill but long enough to
  corrupt fd state, OR the writeback-error path on cephfs propagates
  EBADF to the next syscall rather than killing the process. Need
  kernel ring-buffer at the 19:01-19:03 window to confirm.
- **decide_next gate hardening:** add a "rc=120 from poll is suspect
  → mark resume-pending not all-failed" branch, or check live
  `jobsub_q` before declaring all-failed.
- **Memory budgeting per closed-loop launch:** session-23 hosts an
  interactive VNC + 2 concurrent closed-loop campaigns; a launch
  storm of 20+ parallel python subprocess trees inside a single
  user session is the load pattern that triggered this. Future
  fix may be to limit concurrent closed_loop campaigns per session,
  or run closed_loop under a fresh systemd-run --scope with
  bounded MemoryMax so OOM-kill produces a clean signal rather
  than silent fd corruption.
- **Spacer-vs-plate00 overlap:** is this a real geometry problem at
  certain t0 values, or another `stickmanMagicOffset` precision
  artefact? Diagnose by reading the GDML at
  `autoresearch_grid/pt6d05R01_00/geom/asbuilt_pt6d05R01_00.gdml`
  (now preserved thanks to GDML-emission wiring).
- **decide_next gate hardening:** add a "rc=120 from poll is suspect
  → mark resume-pending not all-failed" branch, or check live
  `jobsub_q` before declaring all-failed.
- **Spacer-vs-plate00 overlap:** is this a real geometry problem at
  certain t0 values, or another `stickmanMagicOffset` precision
  artefact? Diagnose by reading the GDML at
  `autoresearch_grid/pt6d05R01_00/geom/asbuilt_pt6d05R01_00.gdml`
  (now preserved thanks to GDML-emission wiring).

## Cross-links
- **Same kill window, other campaign:**
  [[closed-loop-parent-signal-kill-midlaunch]] (foilsf12 R2 parent+9
  children died ~19:02 same day; treat as the same root event)
- Symptom-twin (different cause): [[preflight-mode-tuple-prodtarget6d-omission]]
  (pt6d04 R1)
- Related overlap incident (different solid pair):
  [[prodtarget-spacer-supportring-overlap]]
- Related decide_next false-positive on barrier timeout:
  [[closed-loop-barrier-timeout-zero-rows-falsepos]]
- Source files: `graph/pipeline_io.py:202-222` (the verb wrapper that
  raises on non-zero), `graph/closed_loop.py:~620` (`decide_next` exit
  guard), `pipeline.py:593-665` (`poll_cluster`)
