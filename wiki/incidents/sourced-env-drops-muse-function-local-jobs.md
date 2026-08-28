---
type: incident
title: sourced_env dropped the `muse` shell function — every local job died rc=127
description: 'First local run after the prodtools switch died at mubeam with `muse: command not found` in 1.2 s: `sourced_env` dropped all `BASH_FUNC_*` env entries (a lossless choice under the OLD local executor), but prodtools `runlocal` sources `Code/setup.sh`, whose line 4 calls `muse` — a bash FUNCTION, not a binary. Fixed 2026-08-17 by reading `env -0` (NUL-delimited) and keeping the functions whole'
status: resolved
status_note: 'resolved 2026-08-17, autoresearch commit 3cc590f (branch local-executor); validated end-to-end on ptlocal02'
timestamp: '2026-08-17'
---

# sourced_env dropped the `muse` shell function — every local job died rc=127

## Summary
The first grid-free run attempted after the
[prodtools switch](/drivers/pipeline.md) (`ptlocal01`, foilspf, 1×200) failed
at `mubeam`: the single local job exited **rc=127, `muse: command not found`,
after 1.2 s**. The cause was `core/pipeline.py:sourced_env`, which built its
env dict by parsing plain `env` line-by-line and **deliberately discarded
every `BASH_FUNC_*` entry**. That was a correct, lossless choice when it was
made (2026-08-12, commit `eb3037e`) — but the prodtools switch silently
invalidated its premise, and nothing failed at the seam where the premise
changed.

## Key facts
- **`muse` is a bash FUNCTION, not a binary.** `setupmu2e-art.sh` exports it
  as `BASH_FUNC_muse%%=() {  source ${MUSE_DIR}/bin/muse\n}`. Ten other
  functions ride along the same way (`spack`, `setup`, `module`, `ml`, …).
- **Why the drop existed.** `env` prints an exported function across
  MULTIPLE lines, so a line-based parser captures a body with no closing
  brace; child shells then reject it with `syntax error: unexpected end of
  file`, ~10 lines per shell spawn. Those errors buried two real failures
  during the first local smoke run, so `eb3037e` dropped the entries with the
  note *"Nothing is lost: a truncated definition never defined the function
  anyway."* True at the time: the then-current `core/local_exec.py` ran
  `mu2e` directly from an already-sourced env and never needed `muse`.
- **What invalidated it.** prodtools `runlocal` runs
  `bash -c 'source Code/setup.sh && mu2e -c <cnf>.fcl'`, and `Code/setup.sh`
  line 4 is `muse setup $CODE_DIR -q p101 e29 prof`. So the local job now
  needs exactly the function that was being discarded. **Grid workers source
  their own environment**, so the grid path — sharing the same `sourced_env`
  — was never affected.
- **The failure surfaces two stages downstream.** `submit mubeam` exits 0
  with only `WARN: 0/1 local job(s) ok` (M5: runlocal's acceptance policy is
  the caller's, deliberately non-fatal), `list-outputs` writes an empty
  `mubeam_outputs.txt`, and the operator's first hard error is
  `[mustops_ce] mubeam_outputs.txt is empty`. Read
  `state/<stage>_wait.json` (`ok`, `failed`) and the per-job
  `local/job_NNNNNN/stdout.log` to land on the real stage.
- **`runlocal`'s `stdout.log` does not capture the job's stderr.** On this
  failure the log ended at the `[local] index 0: ['bash', '-c', ...]` line
  with no error text at all; the cause was only visible by re-running that
  exact command by hand.
- **Fix (commit `3cc590f`): read `env -0` and split on NUL**, then keep the
  function entries. NUL is the one byte an environment entry cannot contain,
  so records survive whole — the truncation that motivated the original drop
  becomes impossible rather than being avoided by discarding the data.
- **Validated end-to-end** on `ptlocal02` (same mode + scale): mubeam
  `ok=1`/33 s/6 outputs, elebeam_flash `ok=1`/33 s/3 outputs, mustops_ce
  `ok=1`/32 s/1 output, harvest `s_over_sqrt_b=3.1` (`ce_seen=109`,
  `muminus_stops=12`). `evaluate` then correctly refused the row on
  `flash_edep=0.0` — expected at 200 events, see
  [local-executor](/drivers/local-executor.md).
- **Class of bug: a premise that decayed silently.** No test could catch it —
  every test mocks `subprocess.run`, so none ever runs `mu2e`. The only
  detector was a real local run, which is why one belongs in the
  merge-readiness gate for any change to the execution seam.

## Cross-links
- Related: [local-executor](/drivers/local-executor.md),
  [pipeline](/drivers/pipeline.md),
  [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md),
  [nfsv4-badseqid-lock-wedge-nashome](/incidents/nfsv4-badseqid-lock-wedge-nashome.md)
- Source files: `core/pipeline.py` (`sourced_env`),
  `core/prodtools_exec.py` (`run_runlocal`),
  `tests/test_pipeline_verbs.py` (`TestSourcedEnvGuards`)
- External: `$AUTORESEARCH_PRODTOOLS/utils/runlocal.py`

## Open questions / TODO
- `tools/run_local.sh` checks Kerberos and artifacts up front but **not**
  `AUTORESEARCH_PRODTOOLS`, which the README lists as a prerequisite and
  `runlocal` requires — a fresh operator gets a `SystemExit` from
  `paths.prodtools_root()` mid-run instead of the script's own refusal.
- Should `submit --local` fail the stage outright at `ok == 0` rather than
  WARN? The current split (WARN, let `list-outputs` divide by the true `ok`
  count) is deliberate for PARTIAL runs, but a total failure has no consumer.
