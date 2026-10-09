---
type: incident
title: prodtools tape-input check crashes under a Python 3.10 Musing
description: 'prodtools'' pre-submit tape check (`import mdh`, Python 3.12) crashes under Run1Bak/Run1Bap''s Python 3.10; SimJob MDC2025ax is immune; not fixed by us'
status: dormant
status_note: not fixed by us (operator, 2026-09-26); our studies avoid it by running on SimJob MDC2025ax
timestamp: '2026-10-08'
---

# prodtools tape-input check crashes under a Python 3.10 Musing

## Summary
The first Phase C1 grid acceptance run (`c1grid01`, 2026-09-26) failed
before any job was submitted. prodtools' `json2jobdef --once` checks
that the inputs are readable before it calls `jobsub_submit`. For a tape
input that check imports `mdh`. By then the write server's command chain
has already set up ops (Python 3.12) and then sourced the entry's Musing,
whose Python 3.10 still sees ops' 3.12 site-packages. `mdh` -> `metacat`
-> `jwt` -> `cryptography` then fails with `ModuleNotFoundError: No
module named '_cffi_backend'` and `pyo3_runtime.PanicException: Python
API call failed`. The job-side tape reads are fine; only this
submit-host check breaks.

## Key facts
- Reproducer, in a clean environment: `setupmu2e-art.sh; setup
  OfflineOps; muse setup ops` then `python3 -c "import mdh"` works (3.12.13).
  After `source /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh`
  the same import fails (3.10.14).
- Path in prodtools: `utils/json2jobdef.py:submit_once` ->
  `utils/submit.py:submit_entry` -> `_preflight_inputs` ->
  `utils/check_inputs.py:check_inputs` -> `check_tape` ->
  `_default_locality` -> `import mdh`. The write server's chain order is
  set in `mcp/src/prodtools_mcp_write/runner.py` (`_SETUP_CHAIN`: ops,
  then the Musing clause, then the command).
- Affected: any tape `inloc` (or tape primary) entry submitted through
  `json2jobdef --once` under Run1Bak or Run1Bap (both Python 3.10.14).
  Not affected: `inloc: resilient` pileup (`check_resilient`, no mdh),
  `dir:` inloc (pure filesystem check), local `run_local` runs (no
  preflight), and SimJob MDC2025ax (Python 3.12.13, `import mdh` works).
- gridphaseA01 (August 2026) submitted tape inputs fine: before ops-021.
- The adapter behaved as designed (receipt stuck in `submitting`, loud
  refusal, nothing submitted twice), but its message named jobsub_q
  instead of the real error, which only the server log showed.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (C1 acceptance),
  [mu2e-cvmfs-python-envs](/external/mu2e-cvmfs-python-envs.md)
- Fix options: run the input check under the ops Python before the Musing
  is sourced (prodtools), or use a Python 3.12 Musing (what we did).

## Open questions / TODO
- Not fixed here: the operator decided (2026-09-26) not to fix it, since
  our studies run on MDC2025ax. Production Run1B submits with tape inputs
  still hit it. The fix, if anyone wants it: record the ops Python before
  the Musing is sourced and run the mdh lookup under it in a subprocess;
  also catch `BaseException`, since the pyo3 panic escapes `except
  Exception`.
