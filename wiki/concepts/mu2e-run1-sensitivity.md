# Mu2e Run 1 sensitivity — parameters + scaling model

**Type:** concept
**Status:** active
**Updated:** 2026-07-01 (superseded by Run1A note for the current config — see top section)

## ⚠️ CURRENT Run1A config supersedes the 2022 paper (Middleton note, 2026-06-15)
The actual late-2027 **Run 1A** (`Run1A_PhysicsNot-8.pdf` in repo root; do NOT
quote the numbers publicly — note says "limit is not final… do not quote") is a
**4-week / 50%-nominal-intensity / reduced-cosmic-shielding** run, and is
**BACKGROUND-DOMINATED**, which breaks the 1/N_stop scaling below:
- 28 d wall (2.42×10⁶ s, duty 0.323, 1BB 3.84 kW) → **POT 7.27×10¹⁸**, stopped μ
  **5.58×10¹⁵**, captures **3.40×10¹⁵** (yield **7.67×10⁻⁴/POT** = ½ SU2020, new
  Inconel target), signal eff **11.66%**.
- **Background ≈ 30 cosmic events** in the SR (reduced shielding!); DIO/RPC/RMC/IPA
  each <1. So limit scales as **√B/N_cap**, NOT 1/N_cap.
- **Per-event SES ≈ 2.5×10⁻¹⁵** (=1/(ε·N_cap)=1/3.96×10¹⁴) — but the **90% CL UL ≈
  2.6×10⁻¹⁴ (stat-only) / 3.5×10⁻¹⁴ (w/ prelim 20% cosmic+4% accept syst)** because
  ~10 signal events must be excluded over the ~30-event cosmic bkg. Limit is ~10×
  worse than SES due to background.
- Blessed talk line: **"Run 1 improves on SINDRUM-II by ≥1 order of magnitude in one
  month"** (~20–25×). Specific numbers preliminary; full unbinned-ML fit later 2026.
- **Lesson:** the 1/N_stop background-free scaling (below) ONLY applies to the
  full-shielding Run 1; Run1A's stripped shielding makes it cosmic-dominated, so a
  background-free extrapolation under-estimates the limit by ~10×.

## Run1A note §4 — samples & normalization (the from-data analysis itself, 2026-06-30)
The Run1A note (`Run1A_PhysicsNot-8.pdf`, Middleton) IS the full from-data sensitivity;
its §4.4 Table 1 specifies the samples (primaries **`MDC2025an-best-v1-1`**, ensembles
**`MDS3c`** — the user-provided `MDC2025ar` is a newer reprocess, same CE gencount):
- **CE (CeMLL): 10⁷ generated (50000×200), 4,009,075 reco → 40.1% gen→reco acceptance.**
  Matches `get_total_gencount(nts...CeMLeadingLogOnSpill.MDC2025ar_best_v1_1)`=**10⁷** exactly.
- DIO 2.5×10⁷ gen / 8.78M reco (POT-eq 2.30e21); Int.RPC 1.25e8 / Ext.RPC 5e9; Int.RMC
  1.25e9 / Ext.RMC 9.92e9; IPA-DIO 10⁷/2.75M. **Cosmics normalized by LIVETIME = 1.3×10⁷ s**
  (NOT gencount — this is the cosmic-specific normalization).
- Normalization formulas (§4.2): `N_DIO = N_POT·f_stops·f_decay·f_reco·f_sim`
  (f_sim(p>95)=3.64e-11); `N_CE = N_POT·f_stops·f_surv·f_reco·R_μe`; RMC f_RMC=1.43e-5
  (>57 MeV); RPC BR=0.0215±0.002, ρ=0.0069, ζ=1e-10; f_decay/f_surv=0.39/0.61.
- MDS ensemble weighting = `github.com/Mu2e/Production/JobConfig/ensemble`.
So "run the full from-data sensitivity" = reproduce THIS note on the samples; the answer
is already 2.6e-14 (stat) / 3.5e-14 (syst) — see top section.
- **Ensemble/MDS ntuple (found via SAM, 2026-07-01):** the note's MDS3c ensemble IS ntupled as
  **`nts.mu2e.ensembleMDS3cOnSpill.MDC2025ar_best_v1_1.root`** (496 files; also `...Mix1BB...`, and
  MDS3a `...MDC2025-001/002`). It's a **POOL of many pseudo-experiments** (mock DATA = signal+all-bkg
  pre-combined at expected yields), NOT one realization: ~9924 evt/file, and after full §6.1 cuts only
  ~1 event/file lands in 99–106 (DIO dominates the 80–99 region below the window). Same EventNtuple
  structure → the `extract_mom3.py` §6.1 worker runs on it unchanged. To reproduce Fig 16 (one MDS
  example) take one exposure's worth (scale the pool by expected ~30 cosmic/exposure in SR). MDS3c
  appears **background-only** (no ~104 MeV signal cluster in the file-0 probe).
- **Ensemble VALIDATES the §6.1 templates (2026-07-01, `docs/fig15_ensemble_vs_templates.png`).** Ran the
  full §6.1 worker on all 494/496 MDS3c files → 79504 AND survivors, |p| 74–150; **80–99: 75665 (DIO tail),
  99–106: 1451, SR: 152**. Pool = **5.07 Run1A exposures** (SR 152 / 30). Scaled to 1 exposure, the ensemble
  mock-data points **overlay my independent component templates** across 99–106: the **physically-normalized
  DIO** template (gencount+f_sim, NOT anchored) matches the ensemble DIO fall-off @99–101, and the flat cosmic
  pedestal matches @103–106. **No 104-MeV bump → background-only confirmed.** ⟹ two independent paths (my
  per-component extraction vs the collaboration's ensemble machinery) give the same spectrum, and the ensemble
  independently yields ~30 bkg/SR/exposure. (SR normalization agreement is partly by construction — both
  anchored to 30 — but the DIO shape+norm and overall |p| dependence agree independently.)

## From-ntuple Fig-15 remake (full-stats MDC2025ar, 2026-07-01)
Reconstructed momentum spectrum rebuilt from the REAL ntuples (not figure-matched):
`docs/fig15_remake.png`, script `/tmp/plot_fig15.py`, arrays `/tmp/mom_{CE,DIO,COS}.npy`
(sid=0 |p| for e⁻ tracks, loose selection: nactive≥20, trkqual>0.2, 640<t₀<1650 ns).
Full datasets processed via [[pyutils-analysis-env]] reducing-worker (CE 198/200, DIO
497/500, COS 496/500 files; ~2h wall total). Normalization (subset-corrected `×n_tot/n_succ`):
- **CE:** `w = N_cap·R_μe/gencount = 3.40e15·1e-13/1e7 = 3.43e-5` → **55 signal ev in SR**
  at R_μe=1e-13. That's >the note's 40 because this loose selection has **ε≈0.16 vs the
  note's full-cut ε=0.1166** (missing fiducial/quality cuts) — gencount-normalization is
  honest, it just reflects the looser cut.
- **DIO:** `w = N_decay·f_sim(p>95)/gencount = 2.18e15·3.64e-11/2.5e7 = 3.19e-3` → **0.03 ev
  in SR** (steep endpoint tail dies before 103 MeV; consistent with note's <1).
- **Cosmic:** anchored to note Table-4 **SR=30**; spectrum is **flat ~4.3 ev/bin** (0.2 MeV)
  across 100–106 → dominates the SR. This is the from-data confirmation that Run1A is
  **background(cosmic)-dominated**, exactly the top-section story.
- **Why our cosmic is dead-flat (measured 2026-07-01):** the CosmicSignal reco |p| population
  is very broad — spans **3→574 MeV/c, median 101** — so the CE window (99–106) is a thin
  **4.9% slice** that is locally flat (~5100 raw MC/bin, no slope). Flat here is CORRECT, not an
  artifact. Our cosmic differs from the note's mainly because our selection **omits the
  cosmic-specific cuts**: no **CRV veto** (|Δt|<150 ns; ~momentum-independent, so it changes
  normalization not shape — and we anchor to 30 anyway) and no **TrkPID / track-angle
  0.5<pz/pt<0.95** cut (these ARE momentum-correlated and sculpt the note's cosmic slightly off
  flat). [SUPERSEDED: the CRV veto IS reproducible — see the full-cut-set section below.]
- **Why the note's Figure 15 shows the cosmic SMOOTHED while DIO/RPC/signal are raw scaled
  histograms (asked 2026-07-01):** the post-veto cosmic MC is **statistics-starved** — the CRV
  `|Δt|<150 ns` veto + quality cuts + TrkPID + track-angle `0.5<pz/pt<0.95` leave very few
  simulated cosmics in the SR, and each survivor carries a **large livetime scale weight**
  (sim ~1.3×10⁷ s scaled to 28 d), so a raw histogram is Poisson-jagged with tall isolated
  spikes and empty SR bins. Since cosmic is the DOMINANT background, its SR shape sets the
  limit, so it's smoothed (KDE) into a continuous estimate (→ the flat ~4.3 ev/bin) to avoid
  zero/fluctuation-driven bins under the signal peak. The note justifies this in its own words:
  *"when sampling rare events … the Central Limit Theorem hasn't fully 'smoothed out' the data
  yet … the shape retains the native right-skewed low-mean Poisson properties."* The smoothing
  ALGORITHM is not stated in the note (KDE-vs-fit unconfirmed).

### Full note cut-set (Table 2) reproduction — CE→40, ε≈11.8% (2026-07-01)
The loose-selection remake above was tightened to the note's ACTUAL Table-2 + §6.1.4 cuts.
Script `/tmp/extract_mom2.py` (worker) + `/tmp/plot_fig15_v2.py`; arrays `/tmp/mom2_{CE,DIO,COS}.npy`;
output `docs/fig15_remake_fullcuts.png`. **Cut → EventNtuple branch map (all reproducible except
t0err):**
- signal trigger = `trig_cpr_TrkDe_80m70p` and/or `trig_apr_TrkDe_80m70p` (per-event bool).
  **RESOLVED to AND (2026-07-01, measured on 20 CE files, denom = full selection incl t0err, SR e⁻,
  n=117414):** cpr-only **89.0%**, apr-only **98.8%**, **AND 88.0%**, **OR 99.7%**. The note quotes
  **92%** → OR (99.7%) is clearly INCONSISTENT; AND (88%) / cpr-only (89%) bracket it. Combined with
  §6.1.2's literal "must pass **two** triggers", **AND is the correct interpretation** — OR was too
  loose and inflated the signal (SR 40 with OR → **~35 with AND**). Earlier "OR matches 92%" was
  wrong (that 64% was event-level over ALL reco events). Definitive plot (`_v3` arrays,
  `docs/fig15_remake_AND.png`) saves per-track cpr/apr bits so AND/OR is a post-hoc toggle.
  DIO 99-MeV peak drops **34→25** between the OR and AND plots, BUT ⚠️ that comparison is CONFOUNDED
  (OR plot = v2, no t0err; AND plot = v3, adds `t0err<0.9` AND AND) — DIO has worse t0 resolution than
  signal, so part of the drop is likely **t0err**, not the trigger. Needs a clean same-array noT/OR/AND
  DIO breakdown to attribute (not yet run). Full-§6.1 AND result: **SR signal 35.2, DIO 0.013, cosmic 30,
  S/√B 6.4** (vs OR's 39.9).
- **Tension in the note (2026-07-01): its Fig 15 SHAPES favor OR, its quoted efficiency favors AND.**
  The note's Fig 15 DIO peak (~34 @99 MeV/c) and signal (~40) match our **OR** version; our **AND** version
  lowers DIO to ~25 @99 (turn-on suppression) and signal to 35. But the note's 92% trigger eff matches AND.
  **Likely resolution: the note applies the trigger as a flat ~92% efficiency FACTOR on OR-like (≈untriggered)
  shapes**, not a strict per-track AND of both bits — giving OR-shaped distributions scaled ~0.92. ⟹ to
  reproduce Fig 15 visually use **OR** (+ mock-data points + 0.21 MeV/c bins + y-range→45); the AND version is
  the stricter cut-text reading but does NOT match the published figure.
- is-e⁻ `trk.pdg==11`; downstream `trksegs.mom.z>0` at sid=0; nactive `trk.nactive≥20`;
  `trkqual.result>0.2`; **`trkpid.result>0.67`** (TrkPID, rejects μ); **N_ST>0** = `trk.nstup+trk.nstdown>0`;
  **N_OPA==0** = `trk.opainter==0` (these two REPLACED the deprecated d0/rmax helix cuts, note p.17);
  pitch **0.5<pz/pt<0.95** from mom components `trksegs.mom.fCoordinates.f{X,Y,Z}` at sid=0; time `640<t0<1650`.
- **CRV veto (reproducible via `crvcoincs`):** quality coincidences `PEs>25 & nHits≥15 &
  (timeEnd-timeStart)<175 ns`; veto a track if any quality coincidence has `|crvcoincs.time−t0|<150 ns`.
  Vectorized as `ak.cartesian({t:t0_sel,c:qtimes},axis=1,nested=True)` → `ak.any(|Δ|<150,axis=2)`.
  Removes **~62%** of cosmic tracks that pass the track cuts; **0%** of CE (signal e⁻ don't fire CRV —
  matches note p.17). **t0err<0.9ns IS reproducible (corrected 2026-07-01):** it lives in
  **`trksegpars_lh.t0err`** (the KinKal `LoopHelixInfo` struct, depth-3, which ALSO has d0/maxr/tanDip/t0
  + errors — NOT just calo timeErr as I wrongly claimed). Applying it keeps **100.0%** of SR signal e⁻
  (117414→117414) — CE tracks have excellent t0 resolution, so it's a genuine no-op for the signal yield
  (matters more for backgrounds).
- **Result:** full cuts give **ε≈11.8% and 39.9 signal ev in SR** (vs loose 55 / ε 0.16) — reproduces
  the note's 40 / 11.66% essentially exactly. Cosmic survivors are sparse post-veto (2 files → 48 track-cut,
  18 after CRV; all 498 files → 5202 survivors) → anchored to SR=30, same as the note.
- **Full-cut cosmic is a broad peak ~108 MeV/c but only ~FLAT within 99–106 — and it does NOT fall as
  steeply as the note's Fig 15 cosmic (UNRESOLVED, 2026-07-01).** CRV-vetoed survivor reco-|p| raw 5-MeV
  bins: 90–95:482, 95–100:567, 100–105:629, 105–110:700, 110–115:612 (peak ~108, falls to ~0.83× at 95).
  But **within 99–106 the raw 1-MeV counts are essentially flat** (115,121,142,115,112,139,137 → only a
  ~7–14% rise), whereas the note's Fig 15 cosmic visibly drops ~50% from 106→99. **Root of the flatness
  (2026-07-01): the cosmic |p| RISES with momentum (as physically expected) from ~134/2MeV @90 to a broad
  peak, but the peak sits at ~106–108 — i.e. RIGHT AT the top of the 99–106 window — so the SR is on the
  crest, not the rising slope, and looks flat.** (Full-range shape: 90→peak106–108→falls to ~80/2MeV @129.)
  If the note's cosmic peaks even a few MeV higher (~110), its 99–106 would still be on the rising slope →
  the visibly steeper increase it shows; that few-MeV peak-location shift is plausibly the `CosmicSignal`
  skim effect. Diagnostics:
  - **Trigger is NOT the cause (refuted for BOTH OR and AND):** for quality-passing cosmic tracks the
    trigger pass-fraction is **flat vs momentum** — OR ~98–100%, **AND ~85–91%** (no turn-on) across 95→113.
    So applying the trigger (either combo) scales the cosmic uniformly but does NOT tilt it toward low |p|.
    (Contrast DIO, where the trigger *may* be momentum-dependent — unconfirmed, see above.) Trigger is
    definitively ruled out as the reason our cosmic is flatter than the note's.
  - **Our sample is a signal-region SKIM.** Lineage: `sim.CosmicDSStopsCRYAll.MDC2025ab` →
    `dts.CosmicCRYAll` (full CRY) → **`dts.CosmicSignal`** (skim) → dig(MDC2025ap) → mcs → `nts.CosmicSignalOnSpill`.
    The `CosmicCRYAll→CosmicSignal` filter is the leading suspect for the flat in-window shape, but unproven.
  - **Definitive test not yet run:** the unfiltered `CosmicCRYAll` exists only as a `dts` art file (no nts),
    so a direct same-cuts comparison needs re-ntupling; alternatively check the note's cosmic normalization
    config (DocDB 52969 CRY/CORSIKA + MDS ensemble). So the note-vs-ours cosmic-slope difference is OPEN.
  - **Plotting gotcha (separate):** `gaussian_kde(bw_method=0.35)` over-smooths even the ~14% in-window slope
    to flat — use a **degree-2 polyfit over 92–122 MeV/c** to preserve it. The earlier "dead-flat ~4.3/bin"
    was the *pre-veto loose* sample (thin flat slice of a broad 3–574 MeV/c distribution).
- **Per-track field access:** load via [[pyutils-analysis-env]] `Importer` with branch list incl.
  `trkpid.result`, `crvcoincs.*`, and the two `trig_*` bools; `pyvector.get_mag` for |p|, and
  `trksegs.mom.fCoordinates.f{X,Y,Z}` for the pz/pt pitch cut.
- **Fig 15 vs Fig 16 (note p.24–25):** SAME momentum spectrum twice. **Fig 15** ("scaled
  distributions and smoothed cosmic") = smoothed cosmic, 3 components (cosmic/DIO/signal).
  **Fig 16** ("MDS example") = the un-smoothed / raw MDS draw, cosmic visibly jagged, AND adds
  **Internal + External RPC** (yellow/green) components absent from Fig 15. To visually MATCH
  Fig 15 (vs our raw normalized-histogram remake): signal **stacked** (not outlined), x-range
  **99–106**, bins **0.21 MeV/c**, plus a **Mock-Data** overlay = one Poisson pseudo-experiment
  on S+B (black points ± err). Conditions box: R_μe=1e-13, t=1 month/28 d, N_POT=7.3e18.

## Summary (2022 paper — full-shielding Run 1, optimistic baseline)
Canonical Mu2e Run-1 μ⁻→e⁻ sensitivity numbers and a **validated** SES model for
scaling to any exposure. Source: Mu2e Collaboration,
*Run I Sensitivity Projections...*, arXiv:2210.11380 (Universe 2023). NOTE: this is
the older full-shielding config; for the current Run1A see the section above.

## Key facts (arXiv:2210.11380, Tables 1 & 8, §8.2)
- **SES factorization (validated):** `SES = 1 / (N_stop · f_cap · A_sel)`.
  With N_stop=6.0e16, f_cap=0.61 (Al), A_sel=0.117 → SES=2.3e-16, **reproduces the
  paper's quoted SES=2.4e-16 exactly** → the model is trustworthy for scaling.
- **Run-1 anchors:** live running time **11.1×10⁶ s** (~128 d; already folds in the
  spill duty factor — beam on ~0.4 s of each 1.4 s cycle), POT **3.8×10¹⁹**, stopped
  muons **6.0×10¹⁶**, total selection efficiency **11.7%**, optimized window
  **103.60 < p < 104.90 MeV/c, 640 < T0 < 1650 ns**, E_CE(Al)=104.97 MeV.
- **Run-1 results:** total background **0.105 ± 0.032 events**; **90% CL UL R_μe <
  6.2×10⁻¹⁶** (no signal); **5σ discovery R_μe = 1.2×10⁻¹⁵** (needs ≥5 events).
  SINDRUM II current limit 7×10⁻¹³ → Run 1 is ~1000× better.
- **Run-1 beam modes (Table 1):** low-intensity 1.6×10⁷ p/pulse for 9.5×10⁶ s →
  2.9×10¹⁹ POT / 4.6×10¹⁶ stops (75% of POT, the commissioning/first phase); high-
  intensity 3.9×10⁷ p/pulse for 1.6×10⁶ s → 9.0×10¹⁸ POT / 1.4×10¹⁶ stops. Stopping
  rate N_stop/POT = **1.6×10⁻³**.
- **Scaling rule (paper, §8.4):** at fixed live time, discovery/limit R_μe ∝
  **1/N_stop**; backgrounds grow sub-linearly (½ the stopped-muon rate → 2× run time
  → only +50% background → <5% change in discovery R_μe). So the search stays
  background-free and **sensitivity ∝ 1/(stopped muons) ∝ 1/livetime** to good approx.

## Worked example — 1 month of data taking (2026-06-26)
1 month of *live* running = 2.59×10⁶ s. At low-intensity (4.84×10⁹ stops/s):
N_stop≈1.25×10¹⁶ (~7.9×10¹⁸ POT, ~21% of Run 1) → **SES≈1.1×10⁻¹⁵**, expected
**90% CL UL R_μe≲3×10⁻¹⁵**, **5σ discovery≈6×10⁻¹⁵**, background ≪0.1 ev. Range:
high-intensity month → SES~6×10⁻¹⁶. CAVEAT: "1 month of data taking" = live Table-1
seconds; a *calendar* month yields less live time after accelerator downtime → ×1.3–2
worse SES.

## Cross-links
- External: arXiv:2210.11380. Signal/bkg MC = MDC2025ar EventNtuple datasets
  (CeMLeadingLog* = signal, DIOtail95, Cosmic*, RPC*, RMC*, etc.), readable via
  [[pyutils-analysis-env]] (CE |p| peak at ~105 MeV verified 2026-06-26).
- Related: [[production-target-stickman]] (the PT the BO lines optimize feeds N_stop).
