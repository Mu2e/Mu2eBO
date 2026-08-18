---
type: incident
title: NFSv4.0 BAD_SEQID lock wedge on /nashome (spack cache EIO)
description: concurrent fcntl churn + RPC disturbance desyncs a v4.0 lock-owner seqid; server then rejects LOCK with BAD_SEQID ~77% of the time, client never recovers — surfaced as "Errno 5 + /bin/museDefine.sh not found" from setupmu2e-art.sh; REPRODUCED under valid krb5 2026-07-30
status: open
status_note: mechanism proven + reproduced on throwaway files; underlying fix (mount vers>=4.1) needs FNAL admins; local mitigation = SPACK_USER_CACHE_PATH off NFS
timestamp: '2026-07-31'
---

# NFSv4.0 BAD_SEQID lock wedge on /nashome

## Summary

`source setupmu2e-art.sh` died with `==> Error: [Errno 5]` + `bash:
/bin/museDefine.sh: No such file or directory` (2026-07-29). The visible
error is three steps downstream of the cause: `spack load` takes an fcntl
lock on `~/.spack/cache/providers/.builtin-index.json.lock`, the kernel
returns **EIO** for any lock on that one inode, spack dies, `MUSE_DIR`
stays unset, line 47 degenerates to `/bin/museDefine.sh`. Root mechanism
(proven by strace + mountstats + canary reproduction): the NFSv4.0 client
on mu2esrv01 holds a **desynced per-owner sequence id** for the inode; the
server answers `LOCK` with `NFS4ERR_BAD_SEQID` (~77% of attempts — it
FLICKERS, 23% succeed), and the el9 client has no recovery path — it logs
`NFS: v4 server returned a bad sequence-id error` and returns EIO,
indefinitely. Reproduced on a throwaway file 2026-07-30 11:38 under a
VALID krb5 ticket: wedge coincided with a multi-owner bad-seqid burst +
node-wide "server not responding" retransmission storm, with **zero**
homesrv01 lease events — so the trigger is RPC disturbance × concurrent
lock churn, NOT lease loss and NOT kerberos expiry (a deliberate 14-min
ticket lapse at 12 locks/s poisoned nothing; expiry gives errno 127
EKEYEXPIRED on open, a different, self-healing signature).

## Key facts

- Fix for a wedged file: **rename it aside** — poison is keyed to the
  inode; spack mints a fresh lock file and recovers instantly. Do NOT
  `rm -rf ~/.spack` (works but slow rebuild). Diagnose with
  `spack --backtrace load ...` and read the file path off the bottom frame.
- Failure taxonomy on a wedged inode: open/read/`F_GETLK` all OK; only
  stateful lock acquisition (`F_SETLK`, `flock`) fails; hardlink to same
  inode fails identically; same inode locks fine from another node
  (client-side state, follows the node not the file).
- The failing lock is on `/nashome` (homesrv01, mounted `vers=4.0`,
  `sec=krb5`) — NOT cvmfs. strace: 30 of 32 `F_SETLK` in one
  `spack load` hit `~/.spack`; the 2 cvmfs locks (`.spack-db/lock`) never
  fail. Wire-proven: each failing lockf = OPEN(ok) → LOCK(rejected) →
  CLOSE in `/proc/self/mountstats`.
- Poisoning is CHRONIC on mu2esrv01: 447 bad-seqid printks / 176 distinct
  owners in a 3 h dmesg window; mu2egpvm03 = 0 in 10 h. srv01 also has a
  continuous pnfs "not responding" storm (~12k msgs / 3 h) — the ambient
  RPC disturbance that, per the captured wedge event, co-fires with
  poisoning bursts (`nfs_increment_seqid: 19 callbacks suppressed`).
- Separate but related disease: v4.0 lease churn to filesrv01
  (/web,/publicweb,/pubhosting) — lease re-established every ~80 s,
  76–84% RENEW failure, on BOTH srv01 and gpvm03, for 15+ days. Not the
  wedge trigger (reproduction had zero lease deltas) but the same
  "v4.0 state fragility" family; strong ticket ammunition.
- Mitigation already in prod for grid children since 2026-06:
  `SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` (pipeline.py:473,
  bo_driver.py:1689) — strace-verified to move all 30 locks off NFS.
  NOT yet covered: `pipeline.py:744` getToken, `closed_loop.py:263`
  renew_token, and interactive login shells (where 2026-07-29 hit).
  pipeline.py's "transient cvmfs flake" comment (~:459) misattributes
  this error class to cvmfs.
- getToken redundancy compounds exposure: ~30 unprotected
  setupmu2e-art.sh sourcings/round to refresh one shared 3 h bearer
  token; a JWT-exp gate (~2 real refreshes/round) would cut ~93% of the
  NFS lock traffic on that path.
- Real fix: mount `/nashome` (+filesrv01 exports) `vers=4.1+` — sessions
  replace the v4.0 seqid machinery entirely. Needs FNAL admins.
- Evidence preserved: `~/.spack/cache/providers/.builtin-index.json.lock.eio-20260729`
  (original, flicker census 98 fail / 30 ok over 2 h) and
  `~/.nfs_lock_probe/hot_0.wedged.1785429513` (reproduction). Standalone
  reproducer (any node, any user; rc=1 + dmesg/counter capture on
  reproduction): `/exp/mu2e/app/users/oksuzian/nfs_badseqid_repro.py`.
  Final canary tally (6 h, 2026-07-30): **11 wedge events, ALL on the
  concurrently-hammered hot files; 0 of 4 cold controls** (same mount,
  probed every 20 s, never locked concurrently) — concurrency is
  REQUIRED. **0 lease events across all 6 h** — lease-flap trigger
  definitively excluded. +1 independent reproduction by the operator
  with the mini script (12.5 min, quiet node, 19:41 CDT). Not rare,
  just normally invisible.

## Cross-links

- Related: [kerberos-mid-run-expiry](/incidents/kerberos-mid-run-expiry.md)
  (its "Errno 127 ENOKEY" is this experiment's measured EKEYEXPIRED open
  signature — a DIFFERENT failure class from the EIO wedge),
  [foilsx04-all-preflight-ambiguous](/incidents/foilsx04-all-preflight-ambiguous.md)
  (first sighting of the class; led to the SPACK_USER_CACHE_PATH
  mitigation), [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md)
  (env-source retry coverage map)
- Source files: `core/pipeline.py:469` (mitigation + stale cvmfs
  attribution), `core/pipeline.py:744`, `graph/closed_loop.py:263`
  (unprotected sites), `graph/sourced_bash.py` (single seam covering all
  four callers if the export moves there)
- External: [RH: BAD_SEQID after NFS4ERR_RESOURCE](https://access.redhat.com/solutions/3873891),
  [RH: client skips sequence-id](https://access.redhat.com/solutions/3686901)

## Open questions / TODO

- ~~Land the three local changes~~ DONE 2026-07-31: seam export in run_sourced_bash (commit from Task 1), getToken mtime gate (Task 2), ~/.bashrc export. Spec: docs/superpowers/specs/2026-07-31-nfs-lock-mitigation-design.md.
- File the FNAL ticket: vers=4.1 request + the RENEW/SETCLIENTID numbers
  (fleet-wide, visible server-side too).
- WATCH next campaign (final-review minor): submit logs should show the
  "bearer token refreshed Nm ago, skipping getToken" line ~28x/round. If
  ABSENT, `_token_age_s`'s fallback path is the suspect: it checks
  `$BEARER_TOKEN_FILE` then hardcodes `/run/user/$UID/bt_u$UID`, but
  htgettoken's chain is `$BEARER_TOKEN_FILE` -> `$XDG_RUNTIME_DIR/bt_u$UID`
  -> `/tmp/bt_u$UID`; a detached parent outliving its logind session would
  stat the dead /run/user path -> inf -> refresh every submit (fail-open:
  behavior identical to pre-gate, only the saving vanishes). Fix = mirror
  the chain / take the freshest candidate.
- Why does the wedge flicker (23% success)? Seqid random-walk vs owner
  GC — undetermined; doesn't change the fix.
- Canary v2 runs until ~17:33 2026-07-30; check for further wedge events.
