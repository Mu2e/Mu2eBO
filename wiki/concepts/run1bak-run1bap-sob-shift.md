---
type: concept
title: Run1Bak → Run1Bap sob shift — mechanism and ledger
description: 'at identical x, Run1Bap sits +4.93%±0.20% above Run1Bak in ce_abs_eff
  (sob +5.21%±0.12% champion / +4.82%±0.23% baseline) — ~100% acceptance-at-fixed-box,
  no box migration, background + CE spectrum shape unchanged; isolated to PrimaryFilter
  (DetectorStepFilter) gaining TWO calo-acceptance relaxations (Offline PR#1819
  a9839eeb4 + Production PR#539 a387965f, both mmackenz 2026-05-06, deliberate
  signal-acceptance recovery); MAGNITUDE CONFIRMED jointly (2026-08-01, local
  no-grid re-filter of archived ipafixAB01 CE events, §8) — baseline-pair flash
  anomaly still open'
status: resolved
status_note: 'mechanism isolated + commit-traced 2026-08-01; magnitude CONFIRMED
  same-day by a local re-filter test (§8, evidence doc) — 95.20%±0.05% survivors
  vs 95.1-95.5% predicted, ~102% of the shift, jointly for the lever pair (not
  split per-lever); baseline-pair flash anomaly (+6.35%±2.82%, 2.25σ, opposite
  sign) remains the one open item'
timestamp: '2026-08-01'
---

# Run1Bak → Run1Bap sob shift — mechanism and ledger

## Summary
The 2026-07-28 A/B campaign found every Run1Bap evaluation at the foilsflash
champion x sitting ~+5% above Run1Bak history in sob. A mechanized elimination
(evidence doc `docs/run1bak_run1bap_shift_evidence.md`, §1–§7) proved the shift
real, not ours, and structurally a pure event-count acceptance rescale — then
isolated it to a single scheduled module, `PrimaryFilter`
(`DetectorStepFilter`) on `PrimaryPath`, which between the two releases gained
two compounding, monotonic-increasing calo-acceptance relaxations, introduced
deliberately upstream to recover signal events the old filter wrongly dropped.
A same-day Phase-4a follow-up (§8) then **CONFIRMED the magnitude, no grid
needed**: reverting the two levers together and re-applying the filter locally
to 165,838 already-archived Run1Bap CE events reproduced a survivor fraction
matching the audited shift to within measurement noise. The two levers were
tested jointly (not split per-lever); the one remaining open item is the
baseline-pair flash anomaly, unrelated to this sob mechanism.

## Key facts
- **Audited shift figures (quote these, not the carried +4.75%/+4.9%):**
  ce_abs_eff **+4.93%±0.20%** (champion x, 3-vs-3) / **+4.08%±0.41%**
  (baseline pair); sob **+5.21%±0.12%** / **+4.82%±0.23%**. Recompute closes
  to <0.0001%; landed-consistent by construction; 25σ/10σ from zero.
- **Decomposition:** ~100% acceptance-at-fixed-box; box migration −0.004 pp
  (identical argmax box sets both eras); background unchanged (cosmic is
  structurally fixed in the macro — model-bound statement); CE spectrum shape
  unchanged at the box (Δmean <0.01 MeV, ΔRMS <1%). More events, same shape.
- **Eliminated (ledger §7.2, 15 excluded, 1 bounded FCL-visible, 3 confirmed
  jointly for the lever pair, 1 open — 20 total):** IPA position + override
  pair (direct-paired arms), zEMCSourceInMu2e (massless VD), analysis binary
  (harvest pinned p094 for all configs), job-loss accounting, our
  tarball/geom migration, base geometry (421/421 include-tree files
  byte-identical), Geant4 (same spack build hash `k4bezfr...` — literally the
  same installed binary), art/ROOT, KinKal/artdaq-core-mu2e/mu2e-ort (not
  scheduled on `PrimaryPath`), inert config deltas.
- **The mechanism — magnitude CONFIRMED jointly (§8, 2026-08-01):**
  - Lever 1: new `MinimumSumCaloE: 45` OR-branch — total calo edep across all
    good particles, a pure disjunct added to `selectcalo`.
  - Lever 2: `MinimumCaloPartMom: 0` — removes the 50 MeV/c momentum floor
    calo steps inherited from the shared `MinimumPartMom` under Run1Bak;
    widens the population feeding BOTH Lever 1's sum and the pre-existing
    per-particle `caloESum`/`MinimumSumCaloStepE: 45` branch.
  - Both only ever widen acceptance (`ORRequirements` defaults true, unset in
    FHiCL both eras) → pass rate under Run1Bap ≥ Run1Bak, provably — matches
    the observed sign.
  - **Magnitude proof (§8, local re-filter, no grid):** one local `mu2e` job,
    two `DetectorStepFilter` instances on two `trigger_paths`, over 165,838
    already-archived `ipafixAB01` CE events (`compressDetStepMCs` tags —
    compression preserves both `StrawGasStep`/`CaloShowerStep` collections).
    `newFilter` = exact Run1Bap production block (control, compression-bias
    check): passed **100.0000%** (0/165,838 failures). `oldFilter` = same
    block with both levers reverted together (`MinimumSumCaloE: 1.0e9`,
    `MinimumCaloPartMom: 50.0`): passed **95.2032%±0.05%**. Corrected
    survivor fraction 95.20%±0.05% lands inside the 95.1-95.5% window
    predicted from the audited +4.93%±0.20% shift (0.52σ from center);
    implied production-equivalent shift +5.04%, i.e. **the two levers
    jointly explain ~102% of the measured shift**. Levers were reverted
    together, not split — no per-lever attribution measured.
- **Commit provenance (scoped sweep §7.1):** Offline
  `Filters/src/DetectorStepFilter_module.cc` changed by exactly 2 commits in
  v13_12_10..v13_32_10 — `a9839eeb4` (both levers, 51+/6−) + `2905cfa0b`
  (printout only), both via **Offline PR #1819** (merge `1d79377fc`,
  2026-05-06); prolog engaged by exactly 1 commit in v02_08_00..v02_13_00 —
  `a387965f` via **Production PR #539** (merge `994dda61`, 2026-05-21). All
  by michaelmackenzie. PR intent: *"reduce loss of viable signals that shower
  in the calo"* — the +5% is the change's intended direction.
- **Engagement nuance:** Lever 2 is active from the Offline C++ alone (new
  dedicated Atom defaults 0.0); Lever 1 needs the Production key
  (`OptionalAtom`). Both are FHiCL-reachable in Run1Bap C++ → a pure config
  revert (`MinimumSumCaloE: @erase`/huge-value + `MinimumCaloPartMom: 50.0`)
  restores Run1Bak filter semantics with no rebuild — this is exactly what
  §8's local test did (huge-value form).
- **Musing pins:** Run1Bak = Offline v13_12_10 (`9ce62149c`) + Production
  v02_08_00 (`471a813f`); Run1Bap = Offline v13_32_10 (`1bd2c4db2`) +
  Production v02_13_00 (`062945c1`) — read from the cvmfs trees' own git
  metadata, `git describe --tags` exact on all four.
- **Flash channel is a different story:** champion flash gap (−3.79%±2.12%)
  is essentially fully the override-pair geometry (+2.20% seed-paired);
  version residual −1.53%±2.78% ≈ 0. OPEN: baseline-pair flash
  **+6.35%±2.82% (2.25σ), opposite sign** — not decomposable (no baseline
  arm C, no seed pairing at 400-vs-100 jobs). This is the only item this
  investigation leaves open.
- **Leaderboard input (decision is the operator's):** Run1Bak/Run1Bap rows
  are different absolute-sob populations offset ≈+5%; one GP over both would
  see a ~0.2-sob step ≈ 33× `obs_noise`. Ratios to same-era baseline are
  era-invariant (+25.5% vs +26.0% from audited group means, 1.5σ apart).
  Geometry-independence of the factor is supported (1.5–1.9σ agreement
  across two x-points) but not proven — §8's local test only covered
  `ipafixAB01` (champion x), not the baseline pair or a second champion arm.
- **Task-8 verdict: TRIGGERED, then CLOSED for the PrimaryFilter arm.** The
  recommended first arm (config-level PrimaryFilter revert under Run1Bap,
  cheaper AND sharper than a Run1Bak control re-run) was executed as a
  **local, no-grid** re-filter (§8) rather than a full grid chain — same
  isolation, faster turnaround. A full-chain grid re-run remains available
  as an independent confirmatory step (crosses the compression boundary and
  the `ce_abs_eff`/`s_over_sqrt_b` normalization chain) but is no longer
  required to answer the magnitude question. The baseline flash anomaly
  (row 20) stays deferred/open.

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md),
  [bo-noise-budget](/concepts/bo-noise-budget.md),
  [leaderboards](/datasets/leaderboards.md),
  [no-run1b-substitution-poisons-flash-modes](/incidents/no-run1b-substitution-poisons-flash-modes.md)
- Source files: `docs/run1bak_run1bap_shift_evidence.md` (§1–§8, the full
  audit trail — §8 is the local re-filter magnitude test); `core/pipeline.py:1279-1420`
  (harvest formulas); `core/harvest.py:30` (`RUN1A_MUBEAM_INPUT_CORRECTION`)
- External: [Offline PR #1819](https://github.com/Mu2e/Offline/pull/1819),
  [Production PR #539](https://github.com/Mu2e/Production/pull/539)

## Open questions / TODO
- Baseline-pair flash anomaly (+6.35%±2.82%, opposite sign) — unexplained;
  needs a baseline override-restored arm and/or N=400 flash re-eval if it
  ever matters for a decision.
- Whether the ≈+5% factor is exactly geometry-independent (two x-points
  agree at 1.5–1.9σ across the shift and ratio consistency tests, and §8's
  magnitude confirmation covers only the champion-x `ipafixAB01` point; not
  proven beyond that).
- Per-lever attribution (Lever 1 `MinimumSumCaloE` vs. Lever 2
  `MinimumCaloPartMom` individually) was never measured — §8 reverted both
  together. Not needed for the leaderboard decision, but would need a
  3rd filter path (or two more local re-filter runs) if ever wanted.
