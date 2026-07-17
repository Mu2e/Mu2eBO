---
type: incident
title: ProdTargetMode MOTHER_MARGIN_MM=20 → TT_MidInner overlap (RETRACTED)
description: '**RETRACTED 2026-06-07**: diagnostic showed bigmother does NOT cause
  TT_MidInner overlap with real POT.fcl; original overlap was DS2 extension block
  (since removed); margin=4 change is harmless but cause story was wrong'
status: superseded
status_note: (RETRACTED 2026-06-07 — cause story wrong; see Summary)
timestamp: '2026-06-07'
---

# ProdTargetMode MOTHER_MARGIN_MM=20 → TT_MidInner overlap (RETRACTED)

## Summary

This page originally claimed that `ProdTargetMode.MOTHER_MARGIN_MM=20`
extended the PT mother volume past the PS bore and cascaded into a
`VirtualDetector_TT_MidInner` "entirely outside mother DS2Vacuum" G4
fatal. **That claim is wrong.** Six-test diagnostic against MDC2025aq
head shows real `POT.fcl` runs cleanly with `motherHalf=139.3` (the
margin=20 value). Source has been reverted to `MOTHER_MARGIN_MM=20.0`
at `autoresearch_bo_michael.py:1053`.

## Diagnostic refutation (2026-06-07)

| # | Geom | FCL | Result |
|---|---|---|---|
| 1 | stickman + only `motherHalf=139.3` | `POT.fcl` | rc=0 |
| 2 | full pt001 + bigmother (139.3) | `POT.fcl` | **rc=0** |
| 3 | bigmother + `hasVirtualDetector=false` | `POT.fcl` | fail (self-inflicted) |
| 4 | pt001 bigmother, no VD toggle | `POT.fcl` | **rc=0** |
| 5 | pt001 bigmother | preflight FCL | fail: GenParticle not found |
| 6 | **stock** stickman | preflight FCL | fail: GenParticle not found |

## What actually happened

- The original Jun 7 01:03 TT_MidInner overlap (`prodtarget_smoke0.log`)
  was almost certainly caused by the DS2 extension block
  (`tracker.inDS2Vacuum=true` + `ds2.halfLength=3825` + `hasServicePipes=false`)
  that `ProdTargetMode.render_proposal` emitted at that time. That block
  is the documented STMUpstream/TT_MidInner trigger
  ([stickman-inds2vacuum-stmupstream-overlap](/incidents/stickman-inds2vacuum-stmupstream-overlap.md)) and was removed earlier
  on 2026-06-07. Removing it was the real fix.
- The 3/3 preflight retries this session that I attributed to bigmother
  were actually caused by a self-inflicted `hasVirtualDetector=false`
  hack I added mid-debug. Reverted.
- The preflight FCL itself fails on prodtarget mode AND on stock
  MDC2025aq for an unrelated reason — see
  [preflight-fcl-genparticle-missing](/incidents/preflight-fcl-genparticle-missing.md).

## Lessons (worth keeping)

- `mu2e -c POT.fcl -n 1` is the right local smoke for a prodtarget geom
  — NOT the preflight FCL, which has a separate broken-input bug.
- Before publishing a "fix" for a G4 fatal, repro the failure against
  the stock geom AND in isolation to attribute the trigger. Don't ship
  a magic-number tweak based on one log file.
- `VirtualDetectorMaker.cc:208` anchors `ttOffset` on
  `tracker.g4Tracker()->z0()`, NOT on PT mother — so a coordinate-frame
  cascade from PT envelope to tracker VDs was physically implausible
  from the start.

## Cross-links

- Related: [stickman-inds2vacuum-stmupstream-overlap](/incidents/stickman-inds2vacuum-stmupstream-overlap.md) (the actual
  cause of the original overlap)
- Related: [preflight-fcl-genparticle-missing](/incidents/preflight-fcl-genparticle-missing.md) (why preflight gate is
  unusable for prodtarget mode; not the same bug as this retracted one)
- Source: `autoresearch_bo_michael.py:1053` (reverted to
  `MOTHER_MARGIN_MM=20.0`)
