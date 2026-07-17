# Preflight FCL fails on prodtarget mode (and stock MDC2025aq): GenParticle product missing

**Type:** incident
**Status:** resolved 2026-06-07 — prodtarget switched to the surface-check FCL path (Option 1); preflight pt001 PASS with 0 managed-volume overlaps and 117 baseline overlaps correctly whitelisted.
**Updated:** 2026-06-07

## Summary
The preflight FCL used by `ProdTargetMode` (only `genCounter` + `g4run` via
`mu2eg4runDefaultSingleStage`) fails at job start with:

```
Found zero products matching all selection criteria
C++ type: std::vector<mu2e::GenParticle>
```

`mu2eg4runDefaultSingleStage` consumes a `std::vector<mu2e::GenParticle>`
input product that the preflight FCL never produces — there is no
generator stage, only `genCounter`. The failure has nothing to do with
geometry. Stock MDC2025aq (vanilla `geom_run1_a_stickman.txt`) under the
same preflight FCL fails identically, confirming the bug is in the FCL
template, not in any prodtarget-specific geom override.

## Key facts

- Reproducer A (custom geom): `mu2e -c preflight.fcl -n 1` with any
  ProdTargetMode geom → rc≠0, "GenParticle not found".
- Reproducer B (stock geom): same preflight FCL pointed at stock
  `geom_run1_a_stickman.txt` → identical failure. The bug is in the
  preflight FCL itself, not in the geometry.
- Other modes (helical/foils/foilsf) use a `surfacecheck.fcl`-style path
  that does NOT run g4run with GenParticle input, so they don't hit this.

## Mechanism

- Preflight FCL contains only `genCounter` + `g4run` (via
  `mu2eg4runDefaultSingleStage`).
- `g4run` is configured to consume a `std::vector<mu2e::GenParticle>` as
  its primary-particle input — Geant4 needs particles to start tracking.
- `genCounter` only counts GenParticles; it does NOT produce them. The
  preflight FCL has no generator stage (no ParticleGun, POT generator,
  StoppedMuonGun, etc.).
- art product-lookup is strict: zero matching products → throw at job
  start, BEFORE Mu2eG4Universe is constructed.

## Why it appears as "preflight=ambiguous rc=3"

- Graph runner sees rc≠0 but no `GeomSolids1001` / `GeomNav1002` /
  `GeomMgt0002` token in log → cannot classify as geometry verdict →
  reports "ambiguous".
- The geometry log lines preflight is supposed to gate on never get
  emitted, because the job aborts before geometry construction.
- This is what burned ~1h of mis-debugging the retracted
  [[prodtarget-mother-margin-tt-midinner-overlap]] — the actual signal
  ("GenParticle not found") is buried far above the rc=3 line.

## Fix shipped (2026-06-07)

**Option 1: Swap preflight to surfacecheck-style FCL.** Added
`"prodtarget"` to the three surface-check branches in
`autoresearch_bo_michael.py` (lines 1443, 1519, 1553) and extended
`SURFACE_OVERLAP_MANAGED` regex (line 1420) to whitelist baseline
overlaps while flagging BO-controlled volumes:

```python
SURFACE_OVERLAP_MANAGED = re.compile(
    r"^(TSdA|AbsorberPV|AbsorberS|StoppingTargetFoil_"
    r"|ProductionTargetPlate|ProductionTargetLug|ProductionTargetSpacer|ProductionTargetSupport)")
```

Smoke verify on pt001: PASS, 117 baseline overlaps whitelisted, 0
managed-volume overlaps.

### Considered but not taken

- **Inject stub generator into existing preflight.fcl**: would have
  worked but adds G4 init cost and doesn't give overlap diagnostics.
- **Skip preflight for prodtarget**: loses the local-feasibility gate.

## Cross-links

- Related: [[prodtarget-mother-margin-tt-midinner-overlap]] (retracted
  margin "fix" was triggered by misreading this preflight failure as a
  geometry problem), [[prodtarget-spacer-supportring-overlap]]
- Related: [[foilsx04-all-preflight-ambiguous]] (different cause, same
  symptom shape: silent preflight=ambiguous burns a round)
- Source: `autoresearch_bo_michael.py` ProdTargetMode preflight FCL
  emission (TODO: pin line)

## Open questions / TODO

- Fix: swap prodtarget preflight to `surfacecheck.fcl` style (no g4run),
  OR inject a stub generator stage, OR skip the preflight gate for
  prodtarget mode entirely and rely on graph.run's first job.
- Decide whether to add a positive "preflight FCL must contain a
  GenParticle producer" lint to catch this class of misconfiguration.
