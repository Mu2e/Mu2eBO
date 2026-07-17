---
type: incident
title: botorch_predict.py seed used `**` (pow) where spec said `^` (xor)
description: '`botorch_predict.py:161` used `42 ** round_idx` (pow) instead of documented
  `42 ^ round_idx` (xor); rounds 0+1 silently shared seed=42 → identical Sobol draw'
status: resolved
timestamp: '2026-06-01'
---

# botorch_predict.py seed used `**` (pow) where spec said `^` (xor)

## Summary
`botorch_predict.py:161` set the qNEHVI MC sampler seed as
`42 ** max(1, int(round_idx))` (exponentiation) instead of the documented
`42 ^ round_idx` (XOR). Symptom is silent: round 0 and round 1 both get
seed=42 → same Sobol draw → the exact "fixed-seed diversity bias" the file's
own docstring (lines 22-24) and [bo-helical](/projects/bo-helical.md) (line 848) warn against. From
round 2 onward seeds are `42**k mod (2³¹-1)` — wildly different from the
intended `42^k` (e.g. `42^2=40` vs `42**2=1764`).

## Key facts
- Python `^` is bitwise XOR; `**` is exponentiation. Easy typo when copying
  the formula `42 ^ round_idx` out of a markdown note that uses `^` in the
  prose-math sense.
- Round-1 collision is the silent failure: `42 ** max(1, 1) = 42`, identical
  to round 0. No exception, no warning — just duplicated Sobol draws across
  consecutive rounds.
- XOR form needs no `% (2**31 - 1)` clamp: `42 ^ int(round_idx)` stays well
  inside int32 for any realistic round count, so the modulo line was also
  removed.
- Bug landed with the `--picker qnehvi` wiring at `closed_loop.py:267-298`
  (subprocess shim). Pre-fix runs that exercised qnehvi for >1 round have
  duplicated MC draws.

## Cross-links
- Related: [bo-helical](/projects/bo-helical.md) (line 848 documents the intended `42 ^ round_idx`),
  [batch-bo](/concepts/batch-bo.md)
- Source files: `botorch_predict.py:161`, `graph/closed_loop.py:267-298`

## Open questions / TODO
- Audit any qnehvi closed-loop runs that completed >1 round before 2026-06-01
  for round 0/1 pick duplication.
