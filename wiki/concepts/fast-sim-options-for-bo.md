---
type: concept
title: Fast-sim options for the BO loop
description: the GP IS the fast sim at 6D/scalar objectives; diffusion surrogates
  fit fixed-geometry production, not geometry search; best ROI = classical range-straggling
  toy calibrated on the eval archive (multi-fidelity low tier); neural surrogates
  only at ~O(100D)
status: active
timestamp: '2026-07-08'
---

# Fast-sim options for the BO loop

## Summary
Assessment + design notes (2026-07-08) for the four realistic fast-sim routes
to cheaper evals. Core framing: in a geometry-search BO loop with scalar
objectives, **the GP IS the fast sim** (R²≈0.9 on flash from ~200 points at
6D); deep generative surrogates (diffusion/flows/GANs — AtlFast3/FastCaloGAN,
CMS FlashSim, CaloDiffusion) answer the opposite problem: distribution-level
response at a FIXED geometry, amortized over production-scale inference. The
pipeline also already amortizes geometry-independent physics classically —
resampled MuBeamCat/EleBeamCat catalogs = "simulate upstream once"; each eval
pays only the irreducibly geometry-dependent target-region G4.

## Option 1 — classical parametric toy (RECOMMENDED first; days, no ML)

**Role**: millisecond-latency LOW fidelity for multi-fidelity screening.
Its job is RANKING candidates, not absolute truth — acceptance bar is rank
correlation (Spearman ρ ≳ 0.8 vs the archive), never absolute agreement.

**sob side (muon stopping)** — tractable single-particle transport:
- Input distributions extracted ONCE from an archived mubeam output: muon
  (p, r, θ) at the ST face (Run1A muons arrive ~tens of MeV/c; range in Al
  ~mm-scale vs the 37×0.106 mm ≈ 3.9 mm base stack + extras).
- Per-muon walk down the foil sequence: crosses foil i iff its radial
  position lies in [rIn_i, rOut_i]; path/foil = t_i/cosθ; subtract dE from
  muon dE/dx tables (Groom); Landau/Vavilov straggling on dE; Highland MCS
  kick per crossing updates (θ, r) — MCS matters because it walks muons
  across hole edges (beam RMS ~24 mm vs base hole rIn 21.5 mm).
- sob ∝ Σ stops weighted by a stop-z acceptance curve: Run1A B is
  cosmic-dominated (~geometry-independent, see [mu2e-run1-sensitivity](/concepts/mu2e-run1-sensitivity.md)),
  so to first order S/√B ∝ S; the z-acceptance weights + overall norm are
  CALIBRATED, not derived.
- ~3-5 fitted nuisances total (norm, acceptance slope, straggling scale),
  fit on the 400+ archived (x, sob) pairs across foils/foilsf/foilsflash.

**flash side (electron scattering)**:
- Input: e⁻ (p, r, θ) at the ST from an EleBeamCat-stage output (on-axis,
  RMS ~24 mm).
- Transport: same foil-crossing walk with Highland MCS (foil ≈ 1e-3 X0 —
  thin-scatterer regime) + ionization; score a proxy for tracker StrawGasStep
  edep (charged flux crossing the straw annulus after drift). The
  MECHANISM's sign (central material RAISES flash — NOHOLE A/B; large-radius
  solid dn foils LOWER it, corr −0.60) is reproduced-or-bust: if the toy
  can't get the archive's signs and rank order after calibration, stop and
  fall back to Option 2 — do not add epicycles.
- Same calibration discipline: few nuisances, fit + LOO against the archive.

**Deliverable/effort**: `tools/toy_foils_objectives.py` (few hundred lines,
numpy) + a validation notebook (R², Spearman, residual-vs-knob plots). 2-4
days. The 400+ archived evals are the irreplaceable asset here — a free
calibration+validation set no new line would have on day 0.

## Option 2 — cheap-G4 multi-fidelity (safe, boring, effective)

- Low fidelity = SAME chain, events ÷5: σ_sob 0.09→0.2%, σ_flash 2→4.5% —
  both still comfortably below front-feature scales. Correlation with full
  fidelity ≈ 1 by construction (same simulator).
- Saves GRID-HOURS (÷3-4 after fixed overhead), NOT latency (queue and
  stage-transition overhead dominate wall; see [bo-noise-budget](/concepts/bo-noise-budget.md)). So its
  win is capacity: more concurrent screening evals inside the ~1,250 ceiling.
- Two-stage integration (skip full MFKG): round = screen phase (M≈2q cheap
  evals) → promote top-q by posterior to full stats.
- **The real work is bookkeeping, not BO**: cheap rows must not silently
  pollute the full-fidelity GP. Cleanest: a fidelity column + per-row noise
  fed to a fixed-noise GP (botorch `train_Yvar`) — then one leaderboard
  serves both tiers. Fidelity must be stamped per-config at submit
  ([events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md) class hazard otherwise).

## Option 3 — geometry-conditioned NN emulator (only for a ~O(100D) future)

- Justified only when GPs strain: e.g. a per-foil line (49×3 ≈ 150 knobs).
  At 6-12D the GP wins on sample efficiency; don't build this for current lines.
- The dimension-scalable trick: do NOT condition on a flat 150D vector —
  encode the foil stack as a SEQUENCE (DeepSets/transformer over per-foil
  (t, rIn, rOut)), emulating per-particle target-region transport
  (muon@face → stop z / e⁻@face → tracker edep). Generalizes across stack
  lengths and shapes; trainable from re-harvested per-event records of the
  existing archive (large I/O job).
- Effort: months (research project). Trigger: a real >~30D line whose GP
  LOO visibly degrades.

## Option 4 — GPU transport (Celeritas / AdePT)

- The non-ML fast-sim that actually exists: GPU EM transport (Celeritas
  general EM offload w/ Geant4 integration; AdePT e±/γ). Physics match to
  `elebeam_flash` (EM-dominated, simple geometry) is excellent; per-GPU
  speedups O(10×) vs a CPU core are reported for such workloads.
- Mismatch: FermiGrid CPU slots, Mu2eG4/art integration, maintenance —
  experiment-level adoption, not a BO bolt-on. Becomes interesting only via
  a GPU allocation + a standalone port of the flash stage, or central Mu2e
  adoption.

## G4beamline (asked 2026-07-08): not inherently faster

Same G4 kernel as Offline — its apparent speed is geometry sparseness
(element-deck ~dozens of volumes vs Offline's ~13.7k world), worth ~2-5×
and capturable in-stack via subset-GDML standalone runs instead. Its output
can't feed the art harvest (screening-tier role only), where it's dominated
from both sides: the parametric toy on latency (~10³×) and cheap-G4 on
consistency (corr≈1, no cross-tool calibration burden). Its real strength
(interactive beamline-element design decks) isn't our bottleneck.

## Decision guide
- Need cheaper screening for the NEXT line → Option 2 now; build Option 1 in
  parallel and let it replace the screen tier if it passes ρ≳0.8.
- Line dimensionality >~30D → start Option 3 evaluation.
- Latency (not grid-hours) is the pain → none of these; see the throughput
  levers in [bo-noise-budget](/concepts/bo-noise-budget.md) (overhead-bound analysis).

## Cross-links
- Related: [bo-noise-budget](/concepts/bo-noise-budget.md), [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md), [batch-bo](/concepts/batch-bo.md), [mu2e-run1-sensitivity](/concepts/mu2e-run1-sensitivity.md)
- Datasets: [leaderboards](/datasets/leaderboards.md) (the calibration/validation archive)
- Incidents: [events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md) (fidelity-stamping hazard)
- External: ATLAS AtlFast3 / CaloDiffusion literature (fixed-geometry surrogates); Celeritas/AdePT (GPU EM transport)

## Open questions / TODO
- If a screening tier is wanted: build Option 1's toy + validation notebook
  (2-4 days) BEFORE any ML surrogate; hard gate at Spearman ρ ≥ 0.8 on both
  objectives, else fall back to Option 2.
- Option 2 prerequisite: fidelity column + fixed-noise GP (`train_Yvar`)
  design — fold into the leaderboard-schema refactor (candidate 3 of the
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md)).
