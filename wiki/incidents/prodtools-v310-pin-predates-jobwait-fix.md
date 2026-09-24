---
type: incident
title: The cvmfs prodtools v3.1.0 pin predates the jobwait and check_inputs fixes
description: 'gridcheck08221321 (2026-08-22) lost a fully successful 15/15 mubeam cluster as `0/15 ok, unknown` because AUTORESEARCH_PRODTOOLS pointed at cvmfs v3.1.0, whose jobwait still shells the jobsub_lite 1.13 `jobsub_history` wrapper that drops `-name <schedd>` — every query hits the default jobsub01, so any cluster on another schedd reads as empty; the fix (condor_history -name direct, 13d561d) and the check_inputs `dir:` fix (e9369b0) are in v3.2.0, which is byte-identical to the validated checkout at 359c2b5; the wiki had called v3.1.0 "a drop-in pin" on the strength of two files'
status: resolved
status_note: root-caused 2026-08-22; pin v3.2.0 (== cvmfs `current` as of 2026-08-20 21:09); the wrong "drop-in" claims corrected the same day
timestamp: '2026-08-22'
---

# The cvmfs prodtools v3.1.0 pin predates the jobwait and check_inputs fixes

## Summary

The first grid run against the slimmed tree, `gridcheck08221321`
(2026-08-22 13:26), ran its 15-job `mubeam` cluster `71682796@jobsub03`
to completion — every proc has all 6 outputs and
`Art has completed and will exit with status 0` — and then died at `poll`
with `[jobwait] 0/15 ok, failed: -, unknown: [0..14]`. Nothing in the
slimmed `pipeline.py` was involved. The run had been launched with
`AUTORESEARCH_PRODTOOLS=/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0`,
the release the wiki and README pointed at, and v3.1.0 carries the
*pre-fix* `jobwait`.

Two days earlier `gridsmoke05` had run the full chain 130/130 with a row —
on clusters at jobsub02, jobsub03 and jobsub02, none of them the default
schedd — which is only possible with the fixed `collect_exit_codes`. It ran
on the operator checkout `/exp/mu2e/app/users/oksuzian/muse_050125/prodtools`
with the fix in the working tree (committed as `13d561d` at 17:21 while the
chain was mid-flight). "It worked before" and "it is broken now" differ by
exactly one variable: which prodtools tree the env var named.

## Key facts

- **Mechanism** (per `docs/handoff/prodtools-jobwait-empty-history-unknown-rc.md`,
  RESOLVED section): the deployed jobsub_lite 1.13 `jobsub_history` wrapper
  parses `@schedd` out of `-J`, builds `-name <schedd>`, then discards it,
  so every query goes to this node's default `SCHEDD_HOST` = jobsub01.
  A cluster on jobsub01 answers (gridsmoke03, `86299508@jobsub01`, 15/15);
  a cluster anywhere else returns header-only (gridsmoke04 on jobsub05,
  gridcheck08221321 on jobsub03) — today it also hangs past 50 s.
  Schedd-dependent, so it strikes at random across submissions.
- **Proof, reproduced 2026-08-22 against the lost cluster**:
  `jobsub_history -G mu2e -J 71682796@jobsub03.fnal.gov -limit 15 -af ProcId ExitCode`
  → rc=124 at a 50 s cap;
  `condor_history -name jobsub03.fnal.gov 71682796 -limit 15 -af ProcId ExitCode`
  → 15 rows, all ExitCode 0, in 3.9 s. `collect_exit_codes` from v3.2.0 and
  from the checkout both read the cluster as `procs=15 rc0=15`; v3.1.0's
  cannot.
- **What each tree carries** (`utils/jobwait.py` / `utils/check_inputs.py`):
  v3.1.0 — `jobsub_history`, zero `dir:` occurrences (so `mustops_ce` would
  have died at the input pre-flight next, the shape gridsmoke03 hit on
  2026-08-20: `unknown storage location 'N/A'`). v3.2.0 — `condor_history
  -name`, `dir:` arm present; **byte-identical in `utils/` and `bin/` to the
  checkout at `359c2b5` (2026-08-20 21:07)**, the state gridsmoke05 validated.
  cvmfs `current` → v3.2.0 since 2026-08-20 21:09.
- **The checkout head is a moving target**: four more commits landed on
  2026-08-22 (refactors of excepts/SAM errors, a `SAMError` import fix); none
  of those are validated by a grid run. Pin the release, not the checkout.
- **The wiki claim that misled the launch**: "v3.1.0 is a drop-in pin ...
  `utils/jobdesc.py` + `utils/submit.py` byte-identical to the checkout head"
  — true of those two files and false of the two that matter at poll and at
  chained submit. The handoff doc itself had said "cvmfs v3.1.0 still carries
  the old code until the next release"; the pin claim was never reconciled
  with it. Corrected 2026-08-22 in [pipeline](/drivers/pipeline.md) and
  [prodtools-submit-entry-tarball-schema-drift](/incidents/prodtools-submit-entry-tarball-schema-drift.md).
- **Post-switch grid history, for the record** (all 2026-08-20, sandbox root):
  gridsmoke01/02 died at submit (tarball schema drift); gridsmoke03 mubeam
  15/15 on jobsub01 then `mustops_ce` + `elebeam_flash` input pre-flight
  refused (`dir:` gap, EleBeamCat "absent from dCache tape"); gridsmoke04
  all-unknown on jobsub05; gridsmoke05 full chain green. `cutsmoke01` and
  `cvmfssmoke01`, which also reached harvest that day, were LOCAL runs
  (`cluster=None`, runlocal) — not evidence about the grid path.
- **Recovery**: the 3.0M mubeam events (0.61 GB TargetStops) are intact
  under `/pnfs/mu2e/scratch/users/oksuzian/workflow/default/outstage/71682796/`;
  re-running `poll mubeam` under v3.2.0 rewrites `mubeam_wait.json` as 15/15
  and the chain can be hand-driven from `list-outputs mubeam` onward.

## Cross-links

- Related: [prodtools-submit-entry-tarball-schema-drift](/incidents/prodtools-submit-entry-tarball-schema-drift.md), [poll-deadlock-missing-outstage-dirs](/incidents/poll-deadlock-missing-outstage-dirs.md), [elebeamcat-tape-migration-elebeam-wipeout](/incidents/elebeamcat-tape-migration-elebeam-wipeout.md)
- Driver: [pipeline](/drivers/pipeline.md)
- Source files: `core/prodtools_exec.py:309` (`outputs_from_wait`, rc None is never ok), `core/paths.py:112` (`prodtools_root`), `tools/run_grid.sh`, `README.md:27`
- Handoff: `docs/handoff/prodtools-jobwait-empty-history-unknown-rc.md`, `docs/handoff/prodtools-check-inputs-dir-inloc.md`

## Open questions / TODO

- README still reads `prodtools/<release>` — a placeholder a fresh operator cannot copy-paste; pin `v3.2.0` there and in `run_grid.sh`/`run_local.sh` defaults.
- `jobsub_history` now hangs (rc=124 at 50 s) where on 2026-08-20 it returned header-only; irrelevant once nothing calls it, but worth knowing if a v3.1.0 tree is ever used again.
