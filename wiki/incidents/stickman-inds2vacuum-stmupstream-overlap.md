---
type: incident
title: Stickman + inDS2Vacuum overrides → STMUpstream G4 fatal overlap
description: '`inDS2Vacuum=true` + `ds2.halfLength=3825` overrides push VirtualDetector_STMUpstream
  outside DS2 (G4 rc=134 fatal); STMUpstream is unconditional in VirtualDetectorMaker.cc:195;
  workaround = strip the DS2 extension for pot_only smoke'
status: resolved
status_note: (2026-06-07; ProdTargetMode.render_proposal no longer emits the DS2
  extension; first hit on grid as cluster 84569380, 100/100 jobs rc=134)
timestamp: '2026-06-07'
updated_note: added placement-math root cause + MDC2025aq-is-fine clarification
  + minimal reproducer + canonical 3646 value
---

# Stickman + inDS2Vacuum overrides → STMUpstream G4 fatal overlap

## Summary
Local smoke tests of the nominal Stickman geometry (pt001) fatally
crashed at G4 init with:

```
VirtualDetector_STMUpstream entirely outside mother logical volume DS2Vacuum
```

rc=134 — full process abort. Caused by the autoresearch_pt001_geom.txt
fragment carrying three lines that extend DS2 and migrate trackers into
it, which pushes STMUpstream past the DS2 envelope.

## Key facts
- Offending overrides (present in
  `/exp/mu2e/app/users/oksuzian/dpa_smoke/autoresearch_pt001_geom.txt:20-22`):
  ```
  bool tracker.inDS2Vacuum = true;
  double ds2.halfLength = 3825;
  bool calorimeter.inDS2Vacuum = true;
  ```
  These mirror the `geom_run1_a.txt` Stickman delta that
  [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md) tracks for muon production runs.
- `VirtualDetectorMaker.cc:195` adds `VirtualDetector_STMUpstream`
  **unconditionally** — no toggle. `hasSTM=false` and
  `vd.STMUpStr.build=false` do not affect this VD (they govern
  different STM constructions).
- The mother envelope DS2Vacuum default halfLength is ~2080 mm.
  Extending to 3825 mm pushes the STM-upstream face outside the DS2
  geometry → "entirely outside mother" overlap → G4 abort.
- **Workaround for local smoke**: strip the three overrides from the
  geom file. The result (`dpa_smoke/g.txt`) runs cleanly, ptmc.art
  files generated successfully, edep totals match Stickman expectations
  (~7 MeV/POT on plate 0, ~17 MeV peak on plate 15).
- **Production grid impact**: the production pipeline runs
  mubeam (uses `geom_run1_a.txt`) where STMUpstream is suppressed via
  the production VD config. The conflict only fires for ad-hoc pot_only
  smoke jobs that reuse pt001_geom + a non-mubeam top-level FCL.
- **Placement math (`VirtualDetectorMaker.cc:185-196`)**: STMUpstream is
  placed at `ds2center + STMOffset` where
  `STMOffset.z = -shift.z - 0.5 * (coll5_far_z - target_near_z)`
  — i.e. halfway between COL5 downstream face and the stopping-target
  upstream face. The math does NOT consult `ds2.halfLength`, so any
  override that shifts DS2's effective span without simultaneously
  patching COL5/target positions leaves STMUpstream stranded outside.
- **MDC2025aq itself is NOT broken**: the stock
  `DetectorSolenoid_v04.txt:284` (chained from MDC2025aq) sets
  `ds2.halfLength = 2080.` — exactly the value the STMUpstream math
  assumes. The crash is purely a downstream-override problem.
- **`geom_run1_b_v01.txt:55` ships the canonical extended-DS2 value:
  `ds2.halfLength = 3646` (NOT 3825)**, paired with the STM-VD
  relocations needed to make that work. Our 3825 was copy-pasted from
  FoilsMode/MichaelMode (where it patches a foil-stack-specific
  TT_MidInner overlap), NOT from the Run1 geom — those modes never
  exercise STMUpstream so the conflict stayed hidden until prodtarget
  pot_only put a stock POT.fcl on top.
- **Minimal reproducer** (no Code rebuild needed, runs against stock
  `muse setup SimJob MDC2025aq`):
  ```bash
  cat > /tmp/break_stm.txt <<'EOF'
  #include "Offline/Mu2eG4/geom/geom_common_current.txt"
  double ds2.halfLength = 3825;
  EOF
  cat > /tmp/break_stm.fcl <<'EOF'
  #include "Production/JobConfig/beam/POT.fcl"
  services.GeometryService.inputFile : "/tmp/break_stm.txt"
  source.maxEvents : 1
  EOF
  mu2e -c /tmp/break_stm.fcl
  # → G4Exception GeomMgt0002 "VirtualDetector_STMUpstream entirely
  #   outside mother logical volume DS2Vacuum !!" → rc=134
  ```
  Change `3825` → `2080` or `3646` and the crash disappears. The
  single load-bearing knob is `ds2.halfLength`; `inDS2Vacuum=true` /
  `hasServicePipes=false` are unrelated to this particular abort.
- **Fix shipped 2026-06-07 for pot_only stage**:
  `bo_driver.py:ProdTargetMode.render_proposal` (~line
  1152) no longer appends the `inDS2Vacuum=true / ds2.halfLength=3825
  / hasServicePipes=false` block. The block was copy-pasted from
  FoilsMode/HelicalMode/MichaelMode where it patches a
  TT_MidInner→DS2Vacuum overlap, but pot_only doesn't use the
  tracker/calorimeter at all and the extension is what creates the
  STMUpstream overlap. This is a `pot_only`-stage-only fix; **if a
  future prodtarget stage uses mubeam, the override will need to be
  conditional on stage rather than dropped entirely**.

## Cross-links
- Related: [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md), [bo-prodtarget](/projects/bo-prodtarget.md),
  [production-target-stickman](/concepts/production-target-stickman.md), [dpa-scoring](/concepts/dpa-scoring.md), [prodtarget-mother-margin-tt-midinner-overlap](/incidents/prodtarget-mother-margin-tt-midinner-overlap.md)
- Source files:
  `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_18_00/Offline/GeometryService/src/VirtualDetectorMaker.cc:195`
- Work-around geom: `/exp/mu2e/app/users/oksuzian/dpa_smoke/g.txt`

## Open questions / TODO
- Add a pot_only-specific geom variant that strips STMUpstream cleanly
  (don't just delete DS2 overrides — they were added for a reason).
- Verify whether the production mubeam path is silently encountering
  the same overlap and just not logging it (G4 surface check off by
  default).
