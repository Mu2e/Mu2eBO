# preflight-mode-tuple-prodtarget6d-omission

**Type:** incident
**Status:** resolved (2026-06-13)
**Updated:** 2026-06-13

## Summary
pt6d04 R1 had ALL 10 children mis-classified as `fail_managed` and
terminated after 3 retries each, with zero leaderboard rows. Closed-loop
then exited early on the "0 new rows + all resolved → all failed"
guard. Root cause: when wiring PT GDML emission earlier the same day,
I added a new "GDML must exist" check that returns rc=1, but did NOT
extend the FCL-selection tuple at `autoresearch_bo_michael.py:1982` to
include `prodtarget6d` — so prodtarget6d ran the bare `preflight.fcl`
(no `writeGDML`), produced no GDML, hit the new check, returned rc=1,
and `pipeline_io.py:134`'s rc-status map sent that to `fail_managed`.

The R1 picks themselves were geometrically fine — they were never
submitted to grid.

## Key facts
- **Site of bug:** `autoresearch_bo_michael.py:1982` listed
  `("helical","foils","foilsf","foilsg","prodtarget")` only. Three
  sibling sites at lines 1991, 2127, 2147 had the same omission shape.
- **Why classifier mapped to `fail_managed`:** `graph/pipeline_io.py:134`
  uses `{0: pass, 1: fail_managed, 2: fail_init, 3: ambiguous}`. The
  rc=1 slot is overloaded: "managed-volume overlap detected" AND every
  other `return 1` in `cmd_preflight` (fatal-abort, canary fail,
  GDML-missing, geom-fail snippet). When the surface-check tuple
  doesn't include your mode, you get rc=1 with NO `[preflight/<mode>]`
  log line explaining why — the log only shows the mu2e subprocess
  output, classifier sees rc=1, calls it `fail_managed`. Misleading.
- **Driver-stdout NOT in preflight log:** the `[preflight/<mode>]`
  print statements go to the driver's stdout, which `pipeline_io.run_preflight`
  captures but only puts the *last 80 lines* in `tail`. Per-child closed-loop
  logs (`graph_data/closed_loop_logs/<cfg>.log`) likewise don't carry the
  driver lines that explain *why* rc=1. Diagnosis required reading the
  workdir's `.fcl` (it was `preflight.fcl` not `surfacecheck.fcl` — the
  smoking gun).
- **Time-window of damage:** GDML-wiring edits landed between pt6d04
  R0 (preflights ran 17:38–22:30 yesterday under OLD code) and R1
  (preflights ran ~05:35 today under NEW code). Only R1 was hit.
- **Fix:** extend tuple at line 1982 (and the three siblings, all done
  via `replace_all`). All four `prodtarget`-tuple sites now consistently
  include `prodtarget6d`. Effective from next campaign (pt6d05+).

## Tooling lesson
When adding a mode to ONE tuple in `cmd_preflight`, grep ALL `mode.name in (...)`
sites:
```
grep -n '"prodtarget"' autoresearch_bo_michael.py | head -20
```
ProdTarget6DMode subclasses ProdTargetMode (autoresearch_bo_michael.py:1488)
but the `mode.name` strings are NOT a subclass relationship — they're
literal-string tuple membership. Subclasses inherit Python methods,
not driver mode-dispatch.

## Cross-links
- Related: [[foilsflash-tarball-mode-key-omission]], [[pipeline-poll-rc120-atexit-death]]
- Caused by: my 2026-06-13 GDML-emission wiring (see [[preflight]]
  driver page, "GDML emission tier")
- Related rc=1 overload: [[preflight-past-init-false-pass]] (different
  symptom, same overloaded rc=1 channel)
- Per-mode dispatch table: `autoresearch_bo_michael.py:1982, 1991, 2127, 2147`
- Classifier: `graph/pipeline_io.py:134`
