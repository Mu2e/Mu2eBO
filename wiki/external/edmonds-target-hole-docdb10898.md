---
type: external
title: Edmonds target-hole flash study (DocDB-10898)
description: 'Edmonds 2017 (DocDB-10898): a CENTRAL stopping-target hole (R≈18-21.5mm)
  cuts beam flash ~30% (DAQ-window ~10-15%) + tracker dose ~30%, SES unchanged,
  2-3% stop loss at fixed mass; flash parents are central (RMS 24mm) — reconciles
  the [[bo-foilsflash]] null (foilsflash varied the outer envelope, not the central
  hole)'
status: active
timestamp: '2026-06-29'
---

# Edmonds target-hole flash study (DocDB-10898)

## Summary
Andy Edmonds' 2017 study (Mu2e DocDB-10898v1) showing that a **central hole in the
stopping target mitigates the beam flash** in the tracker without hurting sensitivity.
This is the direct physics antecedent of the [bo-foilsflash](/projects/bo-foilsflash.md) line — and it explains
why foilsflash got a NULL: Edmonds' flash lever is a hole in the CENTRE of the main
stopping target, whereas foilsflash varied the OUTER extra-foil envelope on a pinned
base. Two decks were shared with this project: `main3.pdf` = "Target Hole Simulations"
(June 20 2017, 16 slides, full study); `main2.pdf` = "Target Hole Summary" (June 28
2017, 5 slides, condensed). Original analysis note: DocDB-10898v1.

## Key facts
- **DEPLOYED — this is not hypothetical: the experiment ADOPTED Edmonds' holed target.**
  The Run1 stopping-target baseline is the **37-disk / R=21.5 mm / 162 g** holed config
  (the `stoppingTargetHoles_DOE_review_2017.txt` geometry). In this project it is the
  PINNED foilsflash/foilsf base: `BASE_HOLE_RADIUS_MM=21.5` (`bo_driver.py:695`),
  emitted as 37× `21.5` in the holeRadii vector. So the ~30% flash mitigation is ALREADY
  BANKED, and the foilsflash base is this HOLED (low-flash) target — NOT solid. To recover
  the +30% "no-hole" flash you would CLOSE the hole (→ Edmonds' 34-disk solid baseline);
  foilsflash cannot (base rIn pinned). See [bo-foilsflash](/projects/bo-foilsflash.md) CORRECTION bullet.
- **Problem:** the beam flash deposits the MOST charge in the straws and the MOST
  radiation dose in the tracker electronics of all background frames (vs dio/oot/
  neutron/photon/deuteron/proton). "No loss in gain up to 1 C/cm" was the straw limit.
- **Physics rationale (the load-bearing insight):** the flash's parent particles
  originate **strongly toward the CENTRE** of the stopping target (parent-origin
  RMS_x ≈ 24 mm), far more concentrated than the muon stops (broad). So a central
  hole removes flash sources while sacrificing few muon stops. This is why a CENTRAL
  hole works and an outer-envelope change does not.
- **Geometries at FIXED mass (162 g)** — extra disks added to compensate the mass
  removed by the hole: baseline **34 disks / no hole**; **36 disks / R=18 mm**;
  **37 disks / R=21.5 mm**. (A lower-mass 34-disk/R=20 mm/151 g point shows what
  happens if you DON'T hold mass.)
- **Flash straw hits:** all-times integral ↓ **~30–35%** (no-hole 39 691 → R=21.5 mm
  25 875). **BUT in the DAQ window (t > 500 ns) only ↓ ~10–15%** (522 → 468). Most of
  the reduction is in the prompt/early part — relevant when comparing to the
  foilsflash `EarlyEleBeamFlash` metric.
- **Tracker electronics radiation dose:** ↓ **~30%** in upstream G10 volumes.
- **Stopped muons:** at FIXED mass lose only **2–3%** (rel 0.97–0.98). At LOWER mass
  (34-disk/R=20 mm/151 g) lose **8%** (rel 0.92) → holding mass is essential. (This
  2–3% matches the [bo-foils](/projects/bo-foils.md)/[bo-foilsflash](/projects/bo-foilsflash.md) independent finding.)
- **Single Event Sensitivity:** UNCHANGED within errors — 2.69±0.03 → 2.8±0.1 ×10⁻¹⁷
  (S.E.S.). Mechanism (slide 13): the holed target pushes stops to **larger radii** →
  the conversion electron passes through **less material** → "better" tracks, which
  compensates the 2–3% fewer stops.
- **Robustness:** ±5 mm target misalignment in x/y → no major change in flash straw
  hits or muon stopping rate.
- **Caveats vs foilsflash:** (1) Edmonds' "flash" is the FULL prompt-flash cocktail;
  the foilsflash metric is specifically the resampled ELECTRON-beam early component
  (`EleBeamResampler` EarlyEleBeamFlash) — related, not identical. (2) Old "18-station
  / 20-slot" CD3 tracker geometry. (3) Benefit is all-times ~30% but DAQ-window ~10–15%.

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md) (the null this reconciles), [stopping-target-foil-base-spec](/concepts/stopping-target-foil-base-spec.md)
  (the base target whose central holeRadius is Edmonds' lever; scalar holeRadius),
  [mu2e-run1-sensitivity](/concepts/mu2e-run1-sensitivity.md) (SES context)
- External: Mu2e DocDB-10898v1 (Edmonds, "Target Hole Simulations", 2017)

## ★ A/B UPDATE (2026-06-30, high-stats): Edmonds' effect REPRODUCED in flash RATE/TOTAL
The no-hole vs holed A/B, redone at 4× flash stats, shows the hole DOES reduce flash — the
first pass just used the wrong metric. Flash-event COUNT (same ~40M input, equal jobs): solid
133,967 vs holed 101,403 → **hole −24% flash RATE (~67σ), −21.5% TOTAL flash/input** — same
direction and comparable magnitude as Edmonds' ~30%. The per-event MEAN was ~flat (−3.8%,
noise) because it divides out the event count where the lever lives. So Edmonds' central-hole
flash reduction IS present in our sim; the [bo-foilsflash](/projects/bo-foilsflash.md) objective (`flash_edep_per_event`
= mean) was blind to it (metric-definition bug). The section below (electron≠proton, "not a
lever") reflected the mean-only view and is SUPERSEDED by this rate/total result.

## A/B test (2026-06-30, superseded — per-event-mean view): our electron-flash ≠ Edmonds' proton prompt flash
A matched no-hole vs holed 37-foil A/B (no extras) was run to test his +30% on our
pipeline. Result: flash(solid)/flash(holed) = 0.938 (−6.2%) **but that is ≈1.0σ at
single-eval precision — consistent with ZERO**, while stops rose +8.9% as expected
(geometry verified correct, distinct shipped geoms, no propagation bug). **Robust finding:
the central hole is NOT a ~30% flash lever in our metric (Edmonds' +30% is ~5σ absent).**
The −6% sign is not significant — an earlier note claiming an "electron-absorber, opposite
to Edmonds" mechanism was RETRACTED (1σ wiggle). Open hypotheses for why our metric
doesn't show his effect: our `EleBeamCat` resampled electron-beam early flash may be a
different background than his prompt "flash" frame, and/or the electron flash at the straw
radius doesn't sample the central hole. Needs replicas + background-identity check. See
[bo-foilsflash](/projects/bo-foilsflash.md) NO-HOLE A/B RESULT.

## Open questions / TODO
- A real flash-mitigation BO line should vary the base target's **central `holeRadius`
  (+ n_disks to hold mass)** — reproducing Edmonds' proven lever — NOT the extra-foil
  envelope. Cheaper than the IPA/OPA pivot and already validated (~30% flash, SES flat).
- Confirm which time window the foilsflash `EarlyEleBeamFlash` metric integrates vs
  Edmonds' t>500 ns DAQ window (the ~30% vs ~10–15% gap depends on it).
