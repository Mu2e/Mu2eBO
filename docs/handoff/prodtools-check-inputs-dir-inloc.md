# prodtools: `check_inputs` rejects every `dir:` inloc at the submit gate

**Repo:** `oksuzian/prodtools` (branch `code-tarball`; also shipped as
`/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0`)
**File to change:** `utils/check_inputs.py`
**Reported:** 2026-08-20, from the autoresearch closed-loop grid path
**Severity:** blocks every chained (multi-stage) campaign at submit time

---

## Summary

`check_inputs()` dispatches on `inloc` with a two-way branch: `resilient`
goes to `check_resilient`, and **everything else falls through to
`check_tape`**, which resolves each input through a SAM dataset-location
query. A `dir:<path>` inloc names files on a filesystem path that were
never declared to SAM, so that query can only ever fail. Every submission
whose inputs come from a `dir:` inloc is therefore refused, with a
misleading "unknown storage location" message.

`dir:` is a first-class inloc everywhere else in the repo — `jobdesc.py`
validates it (`INLOC_SIMPLE` plus the `dir:/<abs path>` arm at
`utils/jobdesc.py:233`), `json2jobdef.py` special-cases it
(`_is_dir_inloc`, `utils/json2jobdef.py:145`), and `runmu2e.py` renders
xrootd URLs for it (`utils/runmu2e.py:205`). `check_inputs.py` is the one
consumer that was never taught the shape: it contains zero occurrences of
`dir:`.

This is a gap in newer code rather than a regression. The `dir:` support in
`json2jobdef.py` and `runmu2e.py` is intact; the input pre-flight gate was
added later (`8df2eb3`, `afbd893`, `e47689d`) and its dispatch never
covered `dir:`.

## Why it only surfaced now

The gate runs at submit, not at build. `json2jobdef` builds a `dir:` cnf
without complaint, so the failure appears one step later, after a stage's
cnf already exists. The autoresearch chain hit it the first time it
submitted a *chained* stage after the gate landed: its first stage reads a
real SAM dataset from tape and submits fine, and the second stage — whose
inputs are the first stage's outputs, staged to scratch — is refused.

## Reproduction

Any entry whose `inloc` is `dir:<path>`. Concretely, from a directory
holding a cnf built with a `dir:` inloc:

```python
import sys, json
sys.path.insert(0, "/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0")
from utils.check_inputs import check_inputs
from utils.jobdesc import inloc_of

entry = json.load(open("<stage>_entry.json"))[0]
print(inloc_of(entry))
# dir:/pnfs/mu2e/scratch/users/<user>/.../staged/mustops_ce

ok, problems = check_inputs("cnf.<owner>.<desc>.<dsconf>.0.tar", inloc_of(entry))
print(ok, len(problems))
```

Observed (with a valid Kerberos ticket and `muse setup ops` for
`samweb_client`):

```
Error listing definition files for sim.oksuzian.TargetStops.Run1Bak_gridsmoke03.art:
  No existing dataset definition with name 'sim.oksuzian.TargetStops.Run1Bak_gridsmoke03.art'
check_inputs ok = False   problems = 15
    query_error | unknown storage location 'N/A' for sim.oksuzian.TargetStops.Run1Bak_gridsmoke03.art
```

Through the real submit path the same condition surfaces as:

```
input pre-flight FAILED for cnf.oksuzian.Run1A_CeEndpoint_gridsmoke03.Run1Bak_gridsmoke03.0.tar
  — refusing to submit. Fix the inputs (or stage them) and retry.
```

Note the failure is **not** authentication-related. SAM answers correctly;
it reports, accurately, that no such dataset definition exists. Confirm by
checking that the files are present on the `dir:` path itself.

## Requested change

In `utils/check_inputs.py`, give `dir:` its own branch in `check_inputs()`
(currently `utils/check_inputs.py:210`, dispatch at lines 231-237)
so residency is verified as a **filesystem existence check on the `dir:`
path**, not a SAM query. Both loops (`auxin` and `primary`) need to honour
it — a `dir:` campaign can carry either.

Suggested shape, mirroring the existing `check_resilient` arm:

```python
def check_dir(dataset, files, dir_path, exists=os.path.exists):
    """Verify inputs named by a dir: inloc are present on that path.

    A dir: inloc names files on a filesystem, not a SAM dataset: the
    files may never have been declared (chained intermediate outputs
    are the normal case), so residency is an existence check and a SAM
    lookup would be wrong rather than merely slow.
    """
```

Two details worth getting right:

1. **Filenames vs dataset names.** `_group_by_dataset` (line 48) derives a
   dataset from each filename via `Mu2eName.parse`, which still works for
   `dir:` inputs but yields a name SAM has never heard of. The new branch
   should key off the *filenames*, joining each to the `dir:` path; the
   grouped dataset is useful only for reporting. `json2jobdef._is_dir_inloc`
   documents the same asymmetry — for `dir:` inlocs, `input_data` keys are
   bare basenames, never SAM dataset names.

2. **`/pnfs` `dir:` paths are POSIX-statable** on interactive nodes, and
   `_default_disk_size` (line 72) already relies on that for resilient, so
   `os.path.exists`/`stat` is consistent with existing practice and does not
   trigger a tape recall. Follow `check_resilient`'s fail-closed convention:
   if the check itself raises, emit `query_error` Problems rather than
   letting the exception escape the gate.

**Preferred structure (optional but tidier):** lift the `dir:` predicate out
of `json2jobdef.py:145` into `utils/jobdesc.py`, beside `inloc_of` and
`INLOC_SIMPLE`, and have both `json2jobdef` and `check_inputs` call it. That
matches the "single-home the entry-key set" refactor in `e47689d` and avoids
a second copy of `inloc.startswith('dir:')`. If you'd rather keep the change
surface minimal, an inline check in `check_inputs` is acceptable.

## Callers affected

Both gate call sites pick the fix up automatically, so no caller changes are
needed:

- `utils/submit.py:485` — `enqueue_entry`
- `utils/submit.py:692` — `_preflight_inputs`, reached from `submit_entry`
- `utils/check_inputs.py:322` — the module's own CLI (`--inloc`)

## Tests

Add `test/test_check_inputs_dir_inloc.py`, alongside the existing
`test/test_json2jobdef_dir_resampler.py` and `test/test_runmu2e_dir_pnfs.py`.
Cover:

1. A `dir:` inloc whose files all exist on the path → `ok is True`, no
   Problems, **and the SAM lister is never called** (inject a `sam_sizes` /
   `dataset_location` that raises if invoked — this is the assertion that
   actually pins the bug).
2. A `dir:` inloc with one file missing from the path → not ok, exactly one
   Problem naming that file, kind `missing`.
3. Regression guard: a `tape` inloc still routes to `check_tape`, and
   `resilient` still routes to `check_resilient` — the new branch must not
   widen.
4. `dir:` under `/pnfs` and `dir:` under an ordinary filesystem path both
   behave the same at this layer (the xrootd-vs-POSIX distinction belongs to
   `runmu2e`, not to residency checking).

## Acceptance

`check_inputs("<cnf built with a dir: inloc>", "dir:/<path>")` returns
`(True, [])` when the named files are present on that path, with no SAM
query issued; and a real `submit_entry` of such an entry proceeds past the
pre-flight gate.

## Context for the reviewer

The reporting workflow is the autoresearch closed loop, which chains
`mubeam → mustops_ce → elebeam_flash` (plus `concat` / `run1b_mubeam` in
other modes). Each chained stage consumes the previous stage's outputs by
staging them to scratch and pointing `inloc` at that directory. Those
intermediates are deliberately never declared to SAM — they are per-config
throwaways, one set per BO evaluation, and declaring them would pollute the
catalogue with thousands of dead datasets. `dir:` is exactly the mechanism
for that case, which is why `json2jobdef` and `runmu2e` grew support for it.
