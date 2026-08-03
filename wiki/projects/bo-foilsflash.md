---
type: project
title: bo-foilsflash — foils geometry vs electron-beam-flash tracker edep (DS-on)
description: '6D BO over the foilsf extra-foil geometry vs tracker StrawGasStep
  edep from the ELECTRON-beam early-flash peak (DS-on), replacing foilsf''s calo
  objective; clone of [[bo-ipa]] structure (elebeam_flash stage resamples EleBeamCat);
  early NULL (foilsflash02/03) was a METRIC BUG (per-event mean, blind to rate)
  — OVERTURNED 2026-06-30: under flash-per-POT foils are a STRONG lever (2.5×, R²=0.89,
  no sob trade-off); objective WIRED + `foilsflash04` relaunched 2026-07-01 (qNEHVI
  q=10×3, ELEBEAM_NJOBS=200)'
status: active
status_note: '**CHAMPION: foilsflash11R00_07 (sob 3.31, flash 5.976e-7), 2026-07-10**
  — first strict domination of the 5-week champion ff05R00_04 (3.28/6.277e-7); parego
  pick, hT_up at the 4 µm floor; flash margin 1.9σ (confirm via one-off ELEBEAM_NJOBS=400
  re-eval). 11 campaigns + transplant, 233 rows. Standard config since 2026-07-10:
  elebeam=100 (default env), HT_FLOOR=0.002, picker hybrid, default_loc=tape for
  elebeam. Historical: flash-per-POT objective wired 2026-07-01 after the per-event-mean
  METRIC BUG null was overturned (foils are a strong flash lever: R²=0.89, 2.5×
  range). - **NOT saturated — new BO sob record 2026-07-16: foilsflash18R01_00 sob=3.86
  @ flash 9.07e-7** (geom rOut 79.1/119.8, 2·hT 142/282 µm, f 0.176/0.201 — a "ceiling"
  recipe: thin IN-BEAM upstream degrading the beam). **#2 all-time behind only the
  3.90 transplant**, and the FIRST BO-found point ABOVE the ff13/14 3.84 exploit
  ceiling. Found by the PRODUCTION 0.10 hybrid picker on the campaign RIGHT AFTER
  ff16/ff17 (20 evals, two independent pickers) "confirmed saturation" — a live
  caution against single-campaign saturation calls. NOT decisive: 3.86 vs 3.84 ≈
  **1.3σ** at σ_sob 0.4% → needs a 400-job confirm re-eval before champion status
  (same flat-top-tie discipline as the 3.31 flash champion). Line is **near-saturated,
  not saturated**.'
timestamp: '2026-07-17'
updated_note: foilsflash18 new BO sob record 3.86; near-saturated not saturated
---

# bo-foilsflash — foils geometry vs electron-beam-flash tracker edep (DS-on)

## Summary
A new BO line that optimizes the **same foilsf 6D extra-foil geometry** and the
**same S/√B signal** as [bo-foils](/projects/bo-foils.md), but swaps the second objective from the
Run1B calo-stop background to the **tracker StrawGasStep ionizing edep from the
ELECTRON-beam EARLY-FLASH peak with DS ON**. Physics rationale: the stopping-
target foils sit in the DS beam path, so they scatter/absorb flash electrons →
flash tracker occupancy should be responsive to the foil geometry. Goal: foil
stacks that keep high S/√B while minimizing electron-flash tracker occupancy.
Wired + offline-verified 2026-06-27 (live grid smoke pending). Structurally a
clone of the [bo-ipa](/projects/bo-ipa.md) mode (foils-family geometry + alternate 2nd-objective
stage + tracker-edep gallery harvest).

## Key facts
- **flash-per-POT objective WIRED + leaderboard migrated + `foilsflash04` launched (2026-07-01).**
  The fix that closes the metric-bug loop:
  - **Harvest** (`pipeline.py` Step 7, ~:1256): computes
    `flash_edep_per_pot = flash_edep_total_MeV / (n_landed_files × events_per_job × POT_PER_ELECTRON)`
    and writes it to `summary.json` (also `flash_n_input`). `POT_PER_ELECTRON = 25e6/2166994 ≈ 11.537`
    (module const, `pipeline.py` ~:276; EleBeamCat `dh.gencount/event_count`). `events_per_job` is the
    SUBMIT-STAMPED value (`_events_per_job("elebeam_flash")`) so a mid-flight edit can't mis-scale.
  - **Objective** (`FoilsFlashMode.extract_metrics`, `bo_driver.py` ~:1047):
    `edep = summary.get("flash_edep_per_pot")` with fallback → `flash_edep_per_event` → `calo_per_pot`
    (so old harvests + `--dry-run`/mock still resolve). Flash still rides the generic `Point.calo` slot.
  - **STALE COMMENT FIXED:** the old `pipeline.py:1253` claimed flash is prescaled 1000× ("per-event
    RELATIVE, NOT per-POT"). WRONG — the template overrides `EarlyPrescaleFilter.nPrescale=1`
    (confirmed in the materialized FCL; `pipeline_templates/elebeam_flash/template.fcl:19`), so
    `flash_edep_total_MeV` is the FULL early-flash total and needs NO prescale correction.
  - **DECK GOTCHA — the headline "foils cut flash N×" is max/min over evals, so it is
    OUTLIER-SENSITIVE and can grow without any physics gain (2026-07-15).** ff17's exploration
    (botorch-0.18 picker A/B) sampled a new WORST design (ff17R00_01: flash 1.864e-6 @ sob 1.65),
    widening the deck range **2.7× → 3.1×** while the FLOOR stayed at 5.999e-7 (ff08R01_10,
    unchanged) — the achievable cut did not improve. `gp_predict_foilsflash_perpot_cloud.py`
    computes the range + `n=` in its title from the leaderboard, so the deck text MUST follow the
    figure; slide 5 now carries an explicit "floor is unchanged" sentence. Cloud row filter is a
    hardcoded allow-list (`range(2, 18)` + `foilsflashSOBX01`, ~line 44) — **bump it every new
    campaign or the new rows are silently absent from the plot**; its n reproduces the in-scope
    leaderboard row count exactly (289 = ff02-17 + transplant; ff15 = 0 rows).
  - **Leaderboard migrated** per-event → per-POT in `flash_edep` col (52 rows, 0 skipped; backup
    `leaderboard_bo_foilsflash.tsv.perevent.bak`). Reproduces the validated cloud/A-B numbers EXACTLY
    (`HOLEDhi`→6.445e-7, `NOHOLEhi`→8.215e-7); per-POT range **6.43e-7→1.63e-6 = 2.53×** vs the flat
    per-event 2.7–3.15e-3. The `obj` col is now stale (per-event-derived) but `load_history_row` reads
    only `sob`+`flash_edep`, so warm-start is unit-consistent. (α/`obj` vestigial under qNEHVI.)
  - **DRY-RUN behaviorally confirmed the fix:** qNEHVI round-0 picks now favor `hT_up=0.01` (min
    upstream thickness, 8/10) + high `f_up` (big upstream holes) = the flash-MINIMIZING direction.
    Under the old flat per-event objective there was no such signal → the corrected objective genuinely
    shapes the acquisition.
  - **Campaign `foilsflash04`:** `python -m graph.closed_loop --mode foilsflash --name-prefix foilsflash04
    --picker qnehvi --q 10 --max-rounds 3`, env `AUTORESEARCH_MODE=foilsflash AUTORESEARCH_ELEBEAM_NJOBS=200`
    (flash jobs 100→200 for finer few-% Pareto discrimination; sob stages stay 15j),
    `AUTORESEARCH_CHECKPOINT_DIR=/tmp/oksuzian/foilsflash04`. Warm-started on the 52 migrated rows.
    thread_id=closed-be3f5920. Log `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/foilsflash04_parent.log`.
    **COMPLETE 2026-07-01:** parent exited clean after `decide_next[r2]`; **28 evals landed**
    (R00 10 / R01 9 / R02 9; 2 lost to `mu2ejobsub` submit rc=1 — R01_06 + one R02, see
    [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md)). Leaderboard now 80 rows (52 warm-start + 28).
    - **FINAL Pareto front (7 non-dominated, sob↑ / flash↓):** R01_09 (3.06, 6.11e-7 = flash FLOOR) ·
      R01_05 (3.23, 6.42e-7) · **R00_00 (3.37, 6.43e-7)** · R01_07 (3.49, 6.71e-7) · R01_04 (3.57, 7.02e-7) ·
      R02_09 (3.70, 8.27e-7) · **R02_02 (3.75, 1.05e-6 = sob CEILING)**. Spans **sob 3.06→3.75** vs
      **flash 6.1e-7→1.05e-6 (2.6×)** — a clean trade-off curve, R2 pushed the high-sob corner.
    - **"R00_00 dominates the deployed default" is a FLASH-TIE + sob-win, NOT lower flash (precision-aware).**
      R00_00 flash 6.43e-7 vs default 6.45e-7 = **0.2% apart, WITHIN the ~2% flash-per-POT noise** — a tie.
      The real, resolved win is **sob 3.37 vs 3.11 ≈ 22σ** at σ_sob 0.4%. So the honest claim is "same flash
      floor (within noise), decisively higher S/√B" — do NOT say foils *lowered* the flash below the default
      (the default already sits at the floor; see the R0-result bullet). Per-point σ: sob **0.4%**,
      flash-per-POT **~2%** @200 elebeam jobs (see [bo-noise-budget](/concepts/bo-noise-budget.md)).
    - Cloud regenerated **n=73** (ff02/03/04), range 2.66×; deck `docs/foilsflash_talk.{md,html}` refreshed.
    - Post-campaign code DONE 2026-07-01: elebeam_flash parallelization + submit stderr-leak fix (see
      [closed-loop-runner](/drivers/closed-loop-runner.md), [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md)).
    - **Low-stats SMOKE4 rows EXCLUDED from the leaderboard 2026-07-02 (81→78 lines, 77 data rows).**
      The 3 `foilsflashSMOKE4` rows ran at `elebeam_flash` epj=**2500** (44× fewer flash events → ~12%
      flash-per-POT CoV vs ~2% prod) and low sob (1.85–2.85, below the 3.06–3.75 prod range). **GOTCHA:
      the GP cloud filters SMOKE out by config-prefix (`foilsflash02/03/04`), but the qNEHVI WARM-START
      reads the WHOLE leaderboard via `load_history_row` — so smoke rows silently seeded every prior
      warm-start (they were in ff04's `history_len_before=52`).** Removed for hygiene (backup
      `leaderboard_bo_foilsflash.tsv.pre-smoke-exclude.bak`). `foilsflash01` (9 epj=2500 configs) had
      state dirs but never landed leaderboard rows — nothing to exclude. Remaining 77 = ff02 15 + ff03 30
      + ff04 28 + 4 A/B (all epj=110000). The 4 A/B rows are full-stats but geometry-mislabeled for
      warm-start (recorded x=`75,75,0.0528,0.0528,0,0` = n=0-extras, ≠ a normal 6-extra build) — kept for now.
  - **foilsflash06 (q=20×2, 2026-07-03) COMPLETE — 39 evals; front SATURATING.** Best sweet-spot points
    R01_04 (sob 3.25 / 6.50e-7) + R01_10 (3.36 / 6.55e-7) **tie but do NOT beat** the standing champion
    **ff04 R00_00 (3.37 / 6.43e-7)** (within the ~2% flash noise). The deployed default already sits near the
    flash floor → diminishing returns on more flash evals; this line can wind down. Leaderboard now 125 rows.
    Campaign doubled as a throughput probe: **q=20 gave ~40% more evals/h than q=10 and measured the grid's
    ~1,250-concurrent ceiling** — see [bo-noise-budget](/concepts/bo-noise-budget.md). (ff05's parallelization stays reverted.)
  - **Best-of-both point across ALL campaigns = `foilsflash05R00_04` (sob 3.28 / flash 6.28e-7), 2026-07-03.**
    Edges the earlier ff04 R00_00 (3.37 / 6.43e-7) on flash at comparable sob. NOTE it comes from ff05 — the
    campaign that was KILLED (parallelization backfire) — but its 9 R0 rows are VALID evals: ff05 died in the
    *barrier* AFTER those children harvested, so the physics is real (only the R0→R1 progression was lost).
    Still within the ~2% flash noise of the cluster → a **tie at the floor**, not a breakthrough.
  - **CONVERGED — the line has a stable optimum: sob ~3.2–3.4 / flash-per-POT ~6.3–6.4e-7**, hit REPEATEDLY
    and independently across ff03/ff04/ff05/ff06 (R01_06, R00_00, R00_04, R01_04 all land there). Four
    campaigns converging on the same corner = strong evidence it's the real optimum; the deployed default
    already sits near the flash floor. **Recommend WIND-DOWN** — more evals give diminishing returns.
  - **foilsflash07 (q=20×2, 2026-07-04) confirms saturation — champion UNCHANGED.** R0 = 20/20 (zero losses;
    leaderboard 145). ff07 R0 best (R00_04 3.23/6.92e-7) landed ~8–15% ABOVE the floor — did NOT reach the
    6.3e-7 corner; `foilsflash05R00_04` (3.28/6.28e-7) still leads all campaigns. Expected qNEHVI behavior at
    a converged front: with 125 warm-start points densely covering the floor, HV-improvement there is ~flat,
    so R0 EXPLORES (extends/verifies the frontier) rather than re-hammering the optimum — the ~2% flash noise
    dominates, so new evals re-sample the plateau, they don't beat it. Textbook saturated-line signature.
  - **IMPROVEMENT vs baseline — decomposed noise-aware (2026-07-04).** Baseline = deployed `foilsflashHOLEDhi`
    (sob 3.11, flash 6.445e-7); σ_sob ~0.4% (±0.012), σ_flash ~2% (±1.3e-8).
    - **FLASH (the objective): NO improvement.** Best flash across 145 evals = ff05 R00_04 6.28e-7 = −2.6%
      ≈ **1.3σ = tie**. Every "better-flash" point is ≤3% below baseline, all within the ±2% bar. The deployed
      21.5 mm hole already sits at the flash floor; extras can't push below it — the core physics result.
    - **S/√B (co-objective): YES, real + resolved.** `ff04 R00_00` = **sob 3.37 (+8.4%, ~21σ) at flash 6.43e-7
      (tie with baseline)** — the cleanest win: same flash floor, decisively more signal significance. ff05 R00_04
      +5.5% sob (~14σ) similar. Mechanism: extra foils add stopping-target MASS → more μ stops → more CE signal,
      at NO flash cost.
    - **Caveat:** the +8% sob is real in the 2-objective metric but carries UN-MODELED costs (added material/mass,
      possible backgrounds this scan doesn't capture) — deploy-worthiness is a physics/cost call beyond the scan.
  - **foilsflash07 COMPLETE (q=20×2, 40 evals, 0 losses; leaderboard 165). DEFINITIVE saturation.** Not one
    ff07 point cracked the all-campaign best-4 (still ff03/04/05); ff07's own best flash (R01_13 6.75e-7,
    R00_04 6.92e-7) came in ~8–10% ABOVE the floor — a full 40-eval campaign warm-started on 125 points could
    not even RE-REACH the 6.28e-7 corner, let alone beat it. Strongest saturation signal yet: seeded with
    everything known, both rounds explored the flat front (qNEHVI at ~zero HV-gradient) and the ~2% noise floor
    dominated. **6 campaigns / 165 evals: champion frozen at ff05 R00_04 (3.28/6.28e-7); line FULLY SATURATED —
    wind down.** Deck (docs/foilsflash_talk) refreshed through ff07 R0 (n=141 cloud).
  - **Best-sob geometry decoded (foilsflash03R02_09, sob=3.77 / flash 9.93e-7)**: upstream extras
    effectively DELETED by the optimizer — 6× 20 µm rings parked at rOut=208.5/hole=187 (f=0.90),
    outside the beam (RMS ~24 mm) since upstream mass only costs stops; downstream extras =
    maximum stopping mass — 6× near-solid 275 µm foils (hole 5.7 mm, rOut 113.7). +21% sob over
    deployed at +54% flash: the anti-champion Pareto corner. BO "removes" mandatory foils by
    thinning to the hT floor + moving them off-beam. Geom truth read from the config's rendered
    geom txt (no z vector — extras extend the stock 22.22 mm pitch). **Recipe is ROBUST**: the
    top-3 sob designs (ff03R02_09, ff06R00_18 3.77 / ff06R00_03 3.76 — two independent campaigns)
    all share it: hT_up pinned at the 0.01 bound (20 µm), f_up large (0.63-0.90), dn near-solid
    (f 0.05-0.16) at 275-335 µm; flash cost +46-54% vs deployed. Deck slide "Anatomy of the
    max-S/√B point" tabulates them. **CROSS-LINE VALIDATION vs [bo-foils](/projects/bo-foils.md)** (foils_talk slide 7,
    foilsf17R01_07 sob=3.91): the two lines' max-sob designs AGREE quantitatively downstream
    (~110 mm near/fully-solid discs at ~0.28-0.33 mm — independent objectives, same answer) and
    diverge ONLY upstream, in the direction each 2nd objective predicts: foils keeps an in-beam
    0.126 mm degrader annulus (rIn=20) worth ~+4% sob (3.77→3.91); foilsflash parks upstream
    because upstream mass is its strongest flash-increasing knob (+0.37/+0.51 corr). Implication:
    foilsflash's 3.77 is NOT its space's sob ceiling — ~3.9 is reachable with an upstream
    degrader at a flash cost qNEHVI correctly refused (also: no sob-corner picker ever ran on
    foilsflash). **CONFIRMED 2026-07-08 by direct transplant (foilsflashSOBX01)**: the foils
    champion x (foilsf17R01_07) evaluated in the flash pipeline gives **sob=3.90** (foils line:
    3.91 — cross-pipeline agreement within noise) at **flash=1.081e-6** = +68% vs deployed /
    +72% vs floor, and +9% flash for +0.13 sob vs the 3.77 corner points. Prediction validated
    on both axes: the in-beam upstream degrader (0.126 mm annulus rIn 20) buys ~+0.13 sob and
    is exactly what the flash objective forbids. Eval used 175/181 flash files (6 on a dead
    pnfs pool — see [harvest-pyroot-nfs-rpc-hang](/incidents/harvest-pyroot-nfs-rpc-hang.md)).
  - **foilsflash09 (q=10×1, 2026-07-08, `--picker hybrid`; 10/10, 0 losses)** — first live hybrid
    (qnehvi+qnparego) run; validated in [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md). **Optimizer self-found
    sob=3.82** (flash 1.04e-6) — the campaign-found ceiling had been stuck at 3.77 across 7 prior
    qNEHVI campaigns; the jump is attributed to the SOBX01=3.90 transplant now being in the 206-row
    training set, re-shaping GP beliefs so acquisition pushed the upstream-degrader region. Batch
    spanned sob 2.07-3.82; champion ff05R00_04 (3.28/6.28e-7) still undominated (every high-sob point
    costs +60-66% flash). Leaderboard now 216 rows. **TWO-RECIPE structure confirmed by ff09 geometry**:
    the 3.82/3.81 points (ff09R00_04: rOut 136/116, 2hT 20/327µm, rIn **1.9**/10.3 mm; R00_00: rIn
    **13.3**/0.0) follow the TRANSPLANT's IN-BEAM upstream recipe (thin foils, SMALL holes → in-beam
    degradation) at flash ~1.04e-6, NOT the parked-off-beam-ring recipe of the older 3.77 points
    (ff03R02_09: rIn 187 mm, ring outside the beam) at flash ~9.9e-7. So the ~+0.05 sob the optimizer
    gained came from ADOPTING the transplant's in-beam degrader, at correspondingly higher flash —
    same physics as SOBX01, self-discovered. Deck slide 6 table + sketch updated to show both routes.
  - **foilsflash08 COMPLETE (q=20×2, 2026-07-07; 40/40 rows, 0 losses; leaderboard 205). 7th campaign,
    saturation reconfirmed.** Best flash R01_10 = 5.999e-7 is a nominal all-time floor but only ~0.9σ
    below ff04R01_09 (6.108e-7) AND sits in the low-sob big-hole corner (sob 2.03) — it does not
    dominate the champion corner. ff05 R00_04 (3.28/6.28e-7) still champion. Line stays wound down.
  - **R0 real-grid result (10 evals, ~2 h) CONFIRMS the fix + a modest Pareto win.** Unlike the
    old flat per-event objective, R0 found floor-flash/high-sob corners, not a random walk:
    `foilsflash04R00_00` (`rOut_up=242, hT_up=0.01, f_up=0.95` — thin upstream foils w/ big upstream
    holes) hits **flash=6.43e-7 at sob=3.37**, i.e. **the same flash floor as the deployed default
    (`HOLEDhi` 6.445e-7) but +0.26 sob (+8%)** → it DOMINATES the default. **But the lever is almost
    entirely UPSIDE:** best achievable flash across all 62 rows is ~6.31e-7 (at useless sob=2.68) /
    6.43e-7 (at sob 3.37), only ~0–2% below the already-holed default — the deployed target already
    sits at the flash floor, so extras mainly RISK raising flash (up to 1.6e-6). The available gain is
    in the **sob direction at fixed floor-flash**, NOT in driving flash lower. (Consistent with the
    2.5× range being mostly the bad direction; see the per-POT range bullet above.)
- **Mode class `FoilsFlashMode(FoilsFracMode)`** (`bo_driver.py`):
  INHERITS build_space/_geom_text/parse_geom/is_buildable from FoilsFracMode
  (identical 6D box: rOut_up/dn 50–250, hT_up/dn 0.01–1.0, f_up/dn 0–0.95).
  Overrides only leaderboard (`leaderboard_bo_foilsflash.tsv`), dirs,
  `extract_metrics` (2nd obj = `summary["flash_edep_per_pot"]`, fallback per_event→calo_per_pot),
  `format_row` (col `flash_edep`), `load_history_row`.
  The flash edep rides in the generic `Point.calo` slot (same trick as ipa's trk_edep).
- **NULL RECONCILED with Edmonds 2017 (DocDB-10898, 2026-06-29) — we varied the WRONG knob for flash.**
  Edmonds already studied target-hole vs flash ([edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md)):
  the flash's parent particles originate **centrally** in the target (RMS_x≈24 mm), so
  the proven flash lever is a **CENTRAL hole in the main stopping target** (R≈18–21.5 mm,
  ~30% flash & tracker-dose reduction all-times, SES unchanged, 2–3% stop loss at fixed
  mass). foilsflash instead varied the **OUTER extra-foil envelope** (extra_rOut 50–250)
  on a PINNED 37-foil base, never touching the central hole → no flash effect → NULL.
  Not a contradiction: our extras sit at the periphery, away from where flash is born.
  Our independent 2–3% stop-loss matches Edmonds exactly. **A real flash line should
  optimize the base `holeRadius` (+ n_disks to hold mass), not the envelope.**
- **WHY no flash impact from the geometry — corrected, NOT an up/down asymmetry (2026-06-29).**
  The up and down extras have IDENTICAL knob ranges (rOut 50–250, hT 0.01–1.0, f 0–0.95);
  any up/down difference in the data is just where the BO SAMPLED, not physics (an
  earlier draft of this bullet wrongly read the sampling pattern — rIn_up 29–223 mm vs
  rIn_dn median 5 mm — as a built-in asymmetry; it is not). The real reasons flash
  barely moves:
  1. **Wrong lever, weak direction.** Our foils act as a thin ABSORBER added in the
     path; Edmonds' ~30% effect is SOURCE removal at the base target core (parent
     RMS≈24 mm). The base ALREADY HAS that hole — `BASE_HOLE_RADIUS_MM=21.5`
     (`bo_driver.py:695`), the Edmonds DOE-review-2017 geometry the
     experiment adopted — and foilsflash PINS it (only the EXTRA foils' rIn are knobs).
     So the central lever is fixed; wiggling extras (peripheral, thin) can't reproduce
     "change the central source."
  2. **All six flash–knob correlations are weak and SYMMETRIC in up/down** (validating
     the operator's intuition): hT_up −0.25, hT_dn −0.30 (more material → slightly LESS
     flash = mild absorber, ~equal up/down); f_up +0.27, f_dn +0.05 (more hole = less
     material → more flash); rOut_up −0.03, rOut_dn +0.16. R²(flash~6 knobs)=0.17 → the
     ~1.6% real variation is below the ~4% per-eval flash noise ([bo-noise-budget](/concepts/bo-noise-budget.md)).
  3. **The only genuine up/down asymmetry is tiny:** only DOWNSTREAM material sits
     between target and tracker, so only it can shield created flash — the single
     strongest (still weak) correlate is downstream central-core material (−0.40);
     upstream extras had no core material in any sampled trial. Below noise, doesn't
     change the null. See [edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md).
  - **All-solid-extras estimate (2026-06-29):** filling ALL extra-foil holes (f=0) does
    NOT give Edmonds' +30%. Data (16 most-solid vs 16 most-holed evals): solid = **−3.3%**
    flash; GP prediction (f=0 vs f=0.95, other knobs at median): **−0.1%**. Both ~0 and
    in the *absorber* direction (solid → slightly LESS flash), NOT +30%. The +30% needs
    changing the BASE central hole (already at rIn=21.5), which foilsflash pins. Confirms
    extras-as-absorber, not source.
  - **CORRECTION (2026-06-29) — the base is NOT solid; it ALREADY carries Edmonds' hole.**
    (Two earlier bullets this session wrongly said "base solid, holeRadius=0, already at
    no-hole HIGH-flash" — that was backwards.) The emitted geom holeRadii vector is
    `{222.55 ×6 (up extras), 21.5 ×37 (BASE), 0.0 ×6 (dn extras)}`: all 37 base foils have
    rIn=**21.5 mm** (Edmonds DOE-review-2017 hole, `BASE_HOLE_RADIUS_MM`). So we are ALREADY
    in the HOLED / **LOW-flash** state — Edmonds' ~30% mitigation is already BANKED in the
    deployed baseline. Consequences: (a) the operator's intuition is RIGHT — CLOSING the
    base holes (21.5→0, solid disks, Edmonds' 34-disk no-hole at fixed mass) SHOULD give
    ~+30% MORE flash; (b) foilsflash never sees it because base rIn=21.5 is pinned and only
    extra-foil rIn varies; (c) "no flash impact from our hole knob" stands, but the reason
    is the central hole is already deployed AND pinned, not that the core is solid.
  - **Validation note:** "closing our holes does nothing" is NOT evidence the flash metric
    is broken/insensitive — the lever was never operated. Clean validation = run solid-base
    vs central-hole-base (R~18-21.5 mm, mass held by disk count) and check we recover
    Edmonds' ~-30%; same A/B is the real flash lever. Needs a base-`holeRadius` knob (not in
    current mode). See [edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md).
- **elebeam_flash SEED is shared across configs — GOTCHA for replicas + flash correlations (2026-06-30).**
  `pipeline_templates/elebeam_flash/template.fcl` pins `services.SeedService.baseSeed: 1` and
  `physics.filters.beamResampler.mu2e.MaxEventsToSkip: 319542`, and the submit run_number is
  fixed (1803 — `pipeline.py:232`; an earlier revision of this page said 1810, which is run1b_mubeam's run number). So per-config the seed structure is IDENTICAL — only the per-job subrun varies
  WITHIN a cluster. Consequences: (1) two SEPARATE elebeam_flash clusters with the same seed
  re-sample the SAME EleBeamCat events → naive same-seed "replicas" are USELESS (identical);
  the correct way to cut σ_flash is a BIGGER SINGLE cluster (more jobs = more independent
  subruns). (2) Different configs (e.g. the whole 48-eval BO + the NOHOLE/HOLED A/B) sample the
  SAME EleBeamCat input population through different geometry → the flash comparison is
  MATCHED-INPUT (input-sampling noise partly cancels; flash differences are geometry+G4-shower,
  not input draw). To bump flash stats: env seam **`AUTORESEARCH_ELEBEAM_NJOBS`** (default 100,
  `graph/config.py` foilsflash block) raises elebeam_flash njobs. High-stats matched A/B
  (NOHOLEhi/HOLEDhi at 400 jobs) launched 2026-06-30 to resolve the residual −6%.
  **STANDARD (user decision 2026-07-09): future campaigns run at the DEFAULT 100 — do NOT
  set the env var.** σ_flash measured 2.52% @100 jobs (vs 1.84% @200; see [bo-noise-budget](/concepts/bo-noise-budget.md)),
  negligible against the ~70% flash dynamic range; the =200 in ff08/09/10 launch commands was
  stats-run inheritance that double-spent 85% of grid-hours. Reserve ≥200 for one-off
  high-stats/replica runs only.
- **★★ 48-EVAL RE-RANK by flash-per-POT (2026-06-30) — NULL OVERTURNED, foils ARE a strong flash lever.**
  Re-analysis (no grid) of the production 45 evals (ff02+ff03; 3 SMOKE rows excluded — anomalous
  ~50× low total) using the correct objective `flash_edep_total_MeV / (files×110000)` (∝ per POT):
  - **R²(flash-per-POT ~ 6 knobs) = 0.89** (vs old per-event-mean R²=0.17) — geometry explains 89%.
  - **best/worst flash-per-POT = 2.5×** (real lever, vs the ~30% mostly-noise spread of the mean).
  - **corr(new metric, old per-event mean) = −0.39 (ANTI-correlated)** — the BO minimizing the mean
    was steering the WRONG way on real flash-per-POT.
  - Knob correlations (all strong + physical): rOut_dn **−0.60**, hT_dn +0.52, hT_up +0.51,
    f_dn **−0.50**, rOut_up +0.37, f_up −0.37 → more upstream material/radius → MORE flash;
    larger downstream radius + bigger holes → LESS flash.
  - **corr(sob, flash-per-POT) = −0.13 → no trade-off** (cut flash ~2.5× at ~no sob cost).
  ACTION: re-run the foilsflash line with the total-per-POT objective; the existing evals already
  show a 2.5× lever. Script: `.venv-botorch` join of summary.json `flash_edep_total_MeV` +
  `state/elebeam_flash_outputs.txt` line count × 110000 + leaderboard knobs.
- **BUT the deployed DEFAULT already sits at the low-flash edge (2026-07-01).** Plotting the
  no-extras baseline (foilsflashHOLEDhi: 37 foils, rIn=21.5) on the flash-per-POT cloud lands it
  at **sob=3.11, flash-per-POT=6.45e-7 — essentially the MINIMUM** of the 45 evals (range
  6.43e-7–1.63e-6). So the 2.5× "lever" is mostly DOWNSIDE: adding extra foils generally
  INCREASES flash (more material → more scatter into the tracker); only a few configs match the
  default's flash, a couple at marginally higher sob (3.1–3.25). Practical read: the extras buy at
  most a small sob gain at ~constant flash — there is NO large flash *reduction* to win by adding
  foils. The real flash lever is the central hole (already deployed). Tempers the "re-run" value:
  a flash-minimizing BO would converge back toward ~no-extras. Star added to
  `gp_predict_foilsflash_perpot_cloud.py` (`_one("foilsflashHOLEDhi")`, gold marker).
- **★ METRIC BUG FOUND (2026-06-30) — the objective `flash_edep_per_event` (MEAN) is BLIND to the real flash lever; the hole DOES reduce flash ~21-24% (Edmonds reproduced).**
  The high-stats A/B mean was ~flat (−3.8%, noise), BUT the flash-event COUNT is decisive:
  solid 133,967 vs holed 101,403 flash events from the SAME ~40M input (361 vs 362 equal
  jobs) → **hole −24% flash RATE at ~67σ** (Poisson), **−21.5% TOTAL flash MeV/input**. Same
  DIRECTION and comparable magnitude as Edmonds' ~30% ([edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md)).
  Mechanism: solid on-axis central target material SCATTERS/SHOWERS beam electrons into the
  tracker → more flash-depositing events; the hole lets the on-axis beam pass → fewer. (Same
  source/scatterer sign as Edmonds — the earlier "opposite-sign absorber" story was WRONG.)
  **Why foilsflash was null: the objective is the MEAN over flash events, which divides out the
  event COUNT — exactly where the geometry lever lives** (conditional-on-deposit mean is ~flat;
  the lever is in HOW MANY events deposit). This is a METRIC-DEFINITION bug, not a code bug —
  the physically-relevant quantity (tracker occupancy, what Edmonds measured) is flash
  TOTAL/RATE per POT, not per-event mean. **ACTION: the whole foilsflash line + its "foils
  aren't a flash lever" null must be REVISITED with a rate/total objective** (`flash_edep_total`
  or flash-events/POT); the per-event-mean objective could not see the lever. Harvest already
  records `flash_edep_total_MeV` and `flash_edep_events` — the rate/total is a re-harvest away,
  no new grid needed for the existing 48 evals.
- **POT normalization via genCounter (2026-06-30).** Correct objective = total flash energy per
  POT ∝ `flash_edep_total_MeV / Σ dh.gencount`. The `elebeam_flash` resampler is 1:1
  (`ResamplingMixer`, prolog.fcl:153); `genCounter` (in `beamResamplerSequence`) records
  **`dh.gencount` per flash `.art.json` = 110000/job** (= resampled EleBeamCat events ≈ beam
  electrons; `event_count` in the same json = the flash-depositing subset, e.g. 259/job for
  HOLEDhi). Sum `dh.gencount` over landed flash files = exact denominator (robust to job loss).
  The geometry RATIO needs no absolute norm (electrons/POT cancels): A/B hole/solid=0.785 (−21.5%).
  ABSOLUTE MeV/POT = ×(EleBeamCat electrons-per-POT) — NOT in genCounter/json (which counts
  resampled events, no `mc.pot`); that constant lives in the parent `sim.mu2e.EleBeamCat.Run1Baa.001430`
  generation metadata (upstream). 1 input event ≈ 1 beam electron (~0.24% deposit early-flash,
  ~2.8 keV each). So the BO objective + geometry comparison are computable NOW from the jsons;
  only the absolute scale needs the one EleBeamCat constant.
- **ABSOLUTE flash MeV/POT (2026-06-30) ≈ 8.2e-7 (solid) / 6.4e-7 (holed).** Got the missing
  constant from `samweb get-metadata sim.mu2e.EleBeamCat.Run1Baa.001430_00003251.art`:
  `dh.gencount=25.0M` (POT simulated) / `event_count=2.17M` (electron events) ⇒ **≈11.5 POT per
  resampled electron**. Effective POT = N_resampled(=Σ flash dh.gencount, ~39.7M) × 11.5 ≈ 4.6e8;
  MeV/POT = flash_edep_total_MeV / eff_POT. ×Run1 3.6e20 POT ⇒ ~3e14 MeV early-flash ionizing
  energy in straw gas (solid). Ratio holed/solid = 0.785 (−21.5%, unchanged — norm cancels).
  **CAVEAT (norm convention, drives ABSOLUTE not ratio):** assumes resampling POT = N_resampled ×
  (parent POT/electron), i.e. wrap-reuse AMPLIFIES represented POT (standard Mu2e resampling
  bookkeeping — confirm with Y.O., author of EleBeamResampler; if POT is capped at the distinct
  pool the absolute scales down). Units = StrawGasStep ionizing edep, early e-beam flash only —
  NOT Edmonds' charge[C/cm]/dose[krad], so compare only the RATIO.
- **Scale cross-check vs Edmonds (2026-06-30): order-of-magnitude CONSISTENT.** Our 8.2e-7
  MeV/POT ×3.6e20 POT = 47 J = 1.75 C primary ionization in the straw gas. Converting to
  Edmonds' wire-charge units (W≈27 eV/pair, gas gain 1e4-1e5, total wire ~1-2.5e6 cm) gives
  **~0.01-0.18 C/cm** vs his slide-3 all-flash **~0.1-0.3 C/cm**. Same order of magnitude, and
  ours (EARLY e-BEAM subset) correctly sits BELOW his all-species total → physically sane, not
  off by decades. Precise match NOT claimable: depends on gain/wire-length/W + we measure energy
  vs his charge (slide 3) / G10 dose (slide 4/10, different volume). Clean assumption-free
  agreement remains the RATIO (−21.5% vs −30%).
- **HIGH-STATS A/B RESULT (2026-06-30, 4x flash jobs) — central hole is NOT a significant flash lever.**
  NOHOLEhi (solid) flash=2.809e-3 (133,967 flash ev); HOLEDhi (holed) flash=2.920e-3 (101,403 ev)
  -> ratio 0.962 = -3.8%, approx 1.2 sigma (ratio sigma ~3.2% at 4x) -> STILL consistent with
  ZERO. The gap SHRANK from -6.2% (1 eval) to -3.8% (4x), and same-geometry run-to-run scatter
  was 1.4% (NOHOLE) / 3.8% (HOLED) -- the "signal" is comparable to noise. Edmonds' +30% is now
  ~9 sigma absent. sob reproducible (solid 3.30 vs holed 3.11, +9% stops, both runs -> geometry
  correct). Consistent small NEGATIVE sign (solid slightly less flash, both runs) hints at a
  ~few-% absorber-direction effect but is NOT established. Aside: holed yields FEWER flash
  events/job (101k vs 134k at equal jobs) -- a geometry effect on event SELECTION, distinct from
  the per-event mean. FINAL: no bug, no big lever; the foilsflash electron-beam flash is weakly
  (<~few-%) sensitive to the central hole, far from Edmonds' proton-prompt-flash +30%.
- **Env seams to emit non-default base geometry (added 2026-06-30, `bo_driver.py:695-703`).**
  Three default-preserving `os.environ` overrides on `FoilsMode` (inherited by FoilsFrac/FoilsFlash):
  `AUTORESEARCH_BASE_HOLE_RADIUS_MM` (default 21.5), `AUTORESEARCH_N_UP`/`AUTORESEARCH_N_DOWN`
  (default 6). Set `N_UP=N_DOWN=0` + a hole value to emit a pure 37-foil base with arbitrary
  central hole (verified: `{75×37}` radii, `{hole×37}` holeRadii; `parse_geom` safe at
  expected_len=37; default run unchanged at 49 foils). Used for the no-hole flash A/B
  (foilsflashNOHOLE00 hole=0 vs foilsflashHOLED00 hole=21.5) to test Edmonds' +30%
  ([edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md)).
- **NO-HOLE A/B RESULT (2026-06-30) — does NOT reproduce Edmonds' +30%; METRIC MISMATCH is the deepest root cause of the whole null.**
  Matched 37-foil pair, no extras, single eval each (~4 h grid):
  | config | base rIn | flash_edep/event | sob | muminus_stops |
  |---|---|---|---|---|
  | foilsflashNOHOLE00 | 0 (solid) | **2.849e-3** | 3.30 | 165,961 |
  | foilsflashHOLED00 | 21.5 | **3.037e-3** | 3.12 | 152,330 |
  - **flash(NOHOLE)/flash(HOLED) = 0.938 → −6.2%, but this is ≈1.0σ — CONSISTENT WITH ZERO.**
    Single eval each, flash σ~4-5% at 26-34k flash events → combined ~6%. So the −6% is NOT a
    significant effect and its SIGN is not trustworthy. (An earlier draft of this bullet
    over-interpreted it as an "electron-absorber, opposite to Edmonds" mechanism — RETRACTED:
    you cannot build a mechanism on a 1σ wiggle.)
  - **stops(NOHOLE)/stops(HOLED) = +8.9%** (sob 3.30 vs 3.12): solid stops MORE muons, as
    expected — confirms the geometry WAS simulated correctly (and verified: the elebeam_flash
    stage shipped distinct geoms, holeRadii {0×37} vs {21.5×37} — NO geometry-propagation bug).
  - **ROBUST FINDING: the central hole is NOT a ~30% flash lever in our metric.** Edmonds'
    +30% would be ~5σ and is decisively absent (HOLED ≈ NOHOLE within noise).
  - **WHY — construction-bug hypothesis RULED OUT (check 2026-06-30).** Read
    `EleBeamResampler.fcl` (Y.O. 2019, `Production/JobConfig/pileup/`, on CVMFS
    `Musings/Production/v00_08_00/`): it resamples the "electron beam entering the DS" as
    `beamResampler:Beam` StepPoints and `g4run` (`simStageOverride:1`,
    `preSimulatedHits:[beamResampler:virtualdetector]`) propagates them THROUGH the DS —
    including the stopping target — to the tracker. So the electrons ENTER UPSTREAM of the
    target and traverse it; the flash objective **IS target-coupled by construction** (NOT a
    bypass/injected-downstream bug). The metric can see the target.
  - **So the small/null flash response is genuine physics, not an artifact:** the central hole
    is simply not a strong lever for the electron-beam flash that reaches the straws (r>38 cm).
    Two unproven refinements for WHY the lever is weak: (a) the straw-radius flash is likely
    dominated by off-axis electrons that don't sample the central r<21.5 mm hole; (b) our
    `EleBeamCat` electron component is a SUBSET of Edmonds' full-species "flash" frame, so it
    needn't carry his full −30%. Remaining to pin the small effect + sign: **replicas**
    (elebeam_flash ~4-8× per config → σ~2%). See [edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md).
- **Cloud "narrow band vs wide dots" is NOT a bug (3-agent audit 2026-06-29).** The
  `gp_predict_foilsflash_cloud.py` density looks like a thin flash band while the 48
  dots scatter ~3× wider — this is the honest signature of the null result, NOT a
  render/fit/data bug. Mechanism: the flash GP's length-scales collapse to the floor
  (5/6 at 0.1) + noise to the cap (3e-2) → mean reverts to bulk across the box → flat
  band; dots are isolated interpolation spikes (in-sample resid ~0.1%). Decisive
  control: the sob GP through the same pipeline gives a full-width cloud. flash R²(6
  knobs)=0.17 (only 17% of flash variance is geometry). Full mechanics + the one
  cosmetic x-clip fix (`:102` x-range 3.4→3.9) in [gp-cloud-rendering](/concepts/gp-cloud-rendering.md).
- **Grid chain** (`graph/config.py`): `mubeam → concat → mustops_ce → elebeam_flash`
  — NO `run1b_mubeam` (no calo channel, like ipa). mubeam+concat+mustops_ce give
  S/√B; `elebeam_flash` gives the flash edep.
- **`elebeam_flash` stage** mirrors **mubeam, NOT mustops_pileup**: it resamples
  the EXTERNAL `sim.mu2e.EleBeamCat.Run1Baa.001430_*.art` dataset via a STATIC
  filelist (`pipeline_templates/elebeam_flash/EleBeamCat.txt`), auxinput path
  `physics.filters.beamResampler.fileNames` (same `beamResampler` ResamplingMixer
  filter mubeam uses), and ships the per-BO foil geom (`ships_geom=True`). It does
  NOT build basenames from concat at submit time (that's the mustops_* pattern).
- **`EleBeamResampler.fcl`** (Production/JobConfig/pileup, original author Y.O.
  2019): resamples electron beam into the DS, DS-on, writes flash DetSteps. Defines
  its OWN `trigger_paths: [flashPath, earlyFlashPath]` + `outPath: [FlashOutput,
  EarlyFlashOutput]`. The template KEEPS both paths (lowest-risk) and harvests
  only the EARLY output.
- **"Early flash" is an OUTPUT choice, NOT an input one** (common confusion):
  the single `EleBeamCat.Run1Baa.001430` catalog is the resampler INPUT for both
  streams; the same input produces `EleBeamFlash` (main, time-cut to digi window)
  AND `EarlyEleBeamFlash` (early peak). We harvest only the EARLY one
  (`output_glob: dts.*.EarlyEleBeamFlash.*.art`). There is no separate "early"
  input dataset.
- **Early-flash prescale is OVERRIDDEN to nPrescale=1** (full stats). The
  production default `EarlyEleBeamFlashPrescale=1000` (`EarlyPrescaleFilter`, a
  RandomPrescaleFilter sitting FIRST in `EarlyDetStepSequence`, pileup/prolog.fcl
  :355-359) drops 999/1000 early events — a production data-volume convenience.
  But the early flash is OUR BO objective, and ×1000 would leave only ~250
  early-flash events at njobs=100×2500 → ~32× (√1000) worse `flash_edep` noise,
  masking geometry sensitivity. The prescale is a random subsample so it does
  NOT bias the per-event mean (harvest divides by surviving events) — it only
  adds variance. Cost of removing: `g4run` (the dominant CPU) runs for all events
  regardless; only StepSim CPU + output volume grow. Set via
  `physics.filters.EarlyPrescaleFilter.nPrescale: 1` in the stage template
  (decided 2026-06-27 before any grid spend). `flash_edep_per_event` is thus a
  per-(early-flash-)event tracker edep, comparable across configs.
- **Early-flash StrawGasStep tag = `compressDetStepMCs`** (process
  `EleBeamResampler`) — the `EarlyDetStepSequence` ends in `compressDetStepMCs`,
  which is already the first candidate tag in the ipa gallery extractor, so harvest
  reuses `pipeline.py:_extract_trk_edep_per_pot` VERBATIM (new "Step 7" block).
- **Musing**: patched `Offline_helical/setup_local.sh` (same as [bo-foils](/projects/bo-foils.md) /
  foilsf) — it varies foil geometry so it NEEDS the holeRadii-vector patch. The
  geom emits the 49-entry `stoppingTarget.holeRadii` vector + poison-pill scalar
  `holeRadius = 1.0e6` (a scalar-fallback worker crashes loudly in G4Tubs rather
  than silently building uniform holes — see
  [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md)).
- **Offline-verified 2026-06-27**: 91 unit tests pass; `propose` writes a faithful
  geom (49 holeRadii + 1e6 scalar); `closed_loop --dry-run` emits in-box picks with
  the 6 foilsf labels; botorch `MODE_SPECS["foilsflash"]` = foilsf box.

## First empirical result (foilsflashSMOKE4, 3 geoms, 2026-06-27) — line VALIDATED + flash IS geometry-sensitive
End-to-end works after the [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md) fix.
**3-geom go/no-go = GO: flash_edep varies ~29% across the 3 Sobol geoms** →
foils measurably affect early-flash tracker occupancy (not flat):
| cfg | sob | flash_edep MeV/ev | flash_events |
|---|---|---|---|
| R00_00 (rOut 249/71, hT .82/.43, f .50/.05) | **2.85** | **2.42e-3** (good corner) | 1318 |
| R00_01 (rOut 141/200, hT .23/.62, f .77/.20) | 2.32 | **3.13e-3** | 875 |
| R00_02 (rOut 58/226, hT .65/.67, f .78/.57) | 1.85 | 2.46e-3 | 712 |
- flash_tag=`compressDetStepMCs` confirmed; mubeam settles 37/37 (no GeomSolids crash).
- **CAVEATS:** (1) sensitivity modest/possibly non-monotonic — R00_00 vs R00_02 (very
  different geoms) gave ~identical flash_edep (2.42 vs 2.46), only R00_01 stands out;
  (2) flash_events 712–1318 → σ(flash_edep) plausibly several % → the 29% spread is
  probably signal but UNCONFIRMED vs noise. **Before a production campaign: bump
  elebeam_flash 100→~300 (more flash_events) OR run a replica to pin σ(flash_edep).**
- R00_00 = highest sob AND lowest flash → early hint of a sob-vs-flash trade-off front.
- **Early-flash tracker-hit rate ≈ 0.54%:** 97 jobs × 2500 = 242.5k input e-beam
  events → only **1318 events** have early-flash tracker StrawGasSteps (pass the
  EarlyDetStepFilter). So flash statistics ≈ input/190 — THIS sizes σ(flash_edep)
  and the njobs needed. At nPrescale=1, 100 jobs → ~1318 flash events (×1000
  prescale would have left ~1, useless). To cut σ(flash_edep) √-wise, scale
  elebeam_flash njobs (each +100 jobs ≈ +1300 flash events).

## Production config (foilsflash02, 2026-06-27): 100 jobs × ~30-min payloads
Operator chose ~30-min jobs × 100/stage (grid-friendly + tighter flash noise).
events_per_job sized from measured per-event rates (below):
| stage | ev/job | njobs | total | payload |
|---|---|---|---|---|
| mubeam | 200,000 | 100 | 2.0e7 | ~30 min |
| mustops_ce | 75,000 | 100 | 7.5e6 | ~30 min |
| elebeam_flash | 110,000 | 100 | 1.1e7 (→~59k flash events) | ~30 min |
~15–20× the smoke statistics → **σ(sob)~0.09%** (overkill, harmless) +
**σ(flash)~3.8× tighter**. **Wiring: AUTORESEARCH_MODE-gated overrides** —
`graph/config.py` (STAGE_TARGETS mubeam/mustops_ce→100; elebeam_flash base=100)
and `pipeline.py` (STAGES events_per_job + memory_mb=3500, after the dict). mubeam/
mustops_ce STAGE_TARGETS + events_per_job are SHARED with foils/ipa/michael, so they
are overridden ONLY for foilsflash — other modes keep their tuned 200×5000/2500.
memory_mb=3500 is precautionary. **VALIDATED 2026-06-28 (foilsflash02):** a 200k-event
mubeam job used **maxres 1.1 GB — IDENTICAL to the 5000-event job** → memory is
event-count-INDEPENDENT (art streams output), so big events_per_job is memory-safe
(3500 MB = 3× headroom, no HOLDs). Payload **24.5 min for 200k ev** (7.3 ms/ev —
faster than the 9.1 ms from tiny jobs since fixed init amortizes) → ~97% grid
efficiency (vs ~15-30% at 45 s). The events_per_job efficiency fix works as designed.

## Timing (measured 2026-06-27)
- **Per-job CPU ≈ 45 s** (mubeam, 5000 ev/job: `TimeReport CPU=42.7s Real=44.4s`,
  95% CPU, ~1.1 GB RAM) — per-job compute is small.
- **Per-stage wall ≈ 6–12 min** (SMOKE4 fast smoke, poll-start→converged: mubeam
  ~12, concat ~6, mustops_ce ~12, elebeam_flash ~10). Wall is dominated by grid
  QUEUE latency + stage-out, NOT compute (jobs finish in ~45 s and run in parallel).
- **Full chain ≈ 1 h/eval** (fast smoke; 4 sequential stages + inter-stage
  submit/list gaps + harvest). Production (q=10 × up to 300 concurrent elebeam_flash
  jobs ≈ 3000 in flight) may queue longer → ~1–2 h/eval. Much faster than the
  launch-bo skill's generic "3–6 h" (foilsflash stages are lighter than helical).
- **Per-event compute rates (for sizing events_per_job):** mubeam **9.1 ms/ev**
  (45.7s/5000), elebeam_flash **16.6 ms/ev** (41.6s/2500, heavier = full G4+DetStep).
  → a ~3–4 min payload (≫ the ~44s grid setup → ~80% efficient) needs mubeam
  ~25k ev/job, elebeam_flash ~12.5k ev/job. **Local muse setup = 13 s** (vs grid
  ~44s; grid adds container + Code.tar.bz2 RCDS download).
- **GOTCHA — can't easily run a resampler stage (mubeam/elebeam_flash) LOCALLY for
  timing:** it needs `mdh`/samweb + a bearer token to resolve the MuBeamCat/EleBeamCat
  resampling inputs over xrootd, but the `Offline_helical` muse env has no `mdh`
  (`command not found`) and setup_local.sh cd's away (resets cwd). The grid jobsub
  wrapper sets up that data-handling env; an interactive muse shell does not. Use the
  grid worker logs (`…/workflow/default/outstage/<cluster>/00/<hash>/log.*`) for
  timing instead — they have `TimeReport` + the `0:NN.NNelapsed` time line.

## RESULT — foilsflash02 campaign (n=15, qnehvi q=10 ×2 rounds, 2026-06-28)
**The foilsflash premise FAILS: the stopping-target foils are NOT a meaningful
electron-flash lever, and there is NO sob-vs-flash trade-off.**
- sob range [1.50, 3.16] (111% spread) but flash_edep range [2.711e-3, 3.094e-3] —
  only **14% spread, CoV 4.1%** across configs (≈2× the ~1.5-2% measurement noise).
- **corr(sob, flash) = +0.26 (weakly POSITIVE)** — a trade-off would be NEGATIVE;
  instead sob and flash drift together weakly. So you can get high sob WITHOUT paying
  flash → no Pareto tension to exploit.
- Physics: the foils sit at the stopping target; they barely shape the electron-beam
  early-flash that reaches the tracker. (Confirms the foilsflashSMOKE4 hint at scale.)
- Best sob: foilsflash02R00_05 sob=3.16 @ flash 2.94e-3; round-1 qNEHVI clustered at
  sob 2.84-3.07 (it just maximized sob, since flash gave no gradient).
- **Implication:** a faster foilsflash03 (speedup levers below) would mostly re-confirm
  this null. Pursue ONLY to (a) tighten the weak +0.26 with more flash stats, or
  (b) pivot to a geometry actually IN the flash path (dedicated DS flash shield / OPA)
  — a NEW line, not foil geometry.

## Harvest gotcha at production scale (2026-06-28)
The big `mustops_ce` (100×75k → EdepAna sees ~2.7M CE events) tripped
[edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md): EdepAna prints the count in
scientific notation past 1M events, which the old `Saw (\d+) events` regex missed
→ `harvest_exception` zero rows on every child. Fixed in `pipeline.py` (regex now
accepts sci-notation); harvest is a fresh subprocess so in-flight children self-heal.

## Speedup levers — 3-fork team verdicts (2026-06-28)
Per-eval ~4 h = ~3 h (4 sequential grid stages, queue-bound) + ~60 min local EdepAna
harvest. The three levers DON'T all stack (1 and 3 are substitutes). Recommended
**foilsflash03 = Lever 1 only**.

**Lever 1 — cut mustops_ce (APPLY; biggest, safest win).** sob needs ~5e5 CE events
(σ=0.4%); uniform-100's 7.5M is 15× overkill. foilsflash03: **mubeam 15×200k,
mustops_ce 15×75k, elebeam_flash 100×110k (unchanged)** → sob σ~0.3% (better than
proven 0.4%), resampling pool healthy (2.5× reuse), EdepAna harvest **~60→~10 min**,
per-eval ~3.2 h. njobs=15 (NOT 10): the poll convergence gate is **90% of njobs**, so
njobs=10 fails after losing 2 jobs. Edit = graph/config.py foilsflash override
(`STAGE_TARGETS["mubeam"]=15; ["mustops_ce"]=15`); pipeline.py events_per_job override
+ elebeam_flash base=100 unchanged. Mode-gated → foils/ipa/michael untouched.

**Lever 2 — parallelize elebeam_flash (DEFER; ~30 min/eval more).** elebeam_flash is
independent of the sob chain, and LangGraph CAN fan-out (conditional edge → LIST
target `[stage_mubeam, stage_elebeam_flash]`) + Pregel's thread pool runs the branches
concurrently (stage nodes block in subprocess I/O, GIL released) → hides elebeam_flash's
~30 min. BUT not a clean change: `route_after_stage` (nodes.py:300) fail-fast→END would
STRAND the harvest fan-in join if a branch fails; needs failure-handling moved into
harvest + a mode-gated per-mode DAG spec (replace flat GRID_STAGES linear `zip` chain +
the `GRID_STAGES[0]` single-head in build.py:53-72). Touches Pregel join / SqliteSaver /
barrier ([closed-loop-bo-design](/concepts/closed-loop-bo-design.md)). Worth ~10 wall-h/campaign but risky — do only if
campaigns get frequent, with full 91-test + barrier dry-run coverage.

**Lever 3 — multithread harvest (SKIP; only 1.6×, redundant after lever 1).** EdepAna is
a legacy `art::EDAnalyzer` (EdepAna_module.cc:35; non-const analyze() fills ~16 TH1* via
TFileService), NOT art::SharedAnalyzer → art runs it SERIALIZED under MT; the only gain
is RootInput decompress/prefetch overlap. MEASURED on a real 29,392-event CE file:
single-thread 39.2 s vs `--nthreads 4 --nschedules 4` 24.2 s = **1.62×**, identical output
(safe). So ~60→~37 min — but once Lever 1 cuts the harvest to ~10 min this 1.6× is
negligible (~10→6). Substitute, not additive. Only use if mustops_ce must stay large:
add `"--nthreads","4","--nschedules","4"` at pipeline.py:1167.

## Slide deck (2026-06-28)
`docs/foilsflash_talk.{md,html}` — 6 slides, IPA-deck style, presents the weak-knob
null result honestly. Cloud: `mmackenz_table_plots/gp_predict_foilsflash_cloud.py`
(self-contained sklearn GP, sob vs e-flash tracker Edep, evals colored by mean foil
half-thickness; writes `docs/foilsflash_predicted_cloud.png`). Render:
`cd docs && CHROME_PATH=… npm_config_cache=/tmp/oksuzian_npm_cache npx -y
@marp-team/marp-cli@latest --html --allow-local-files foilsflash_talk.md -o foilsflash_talk.html`.
No commit/push (operator reviews, like foils/ipa).

## Cross-links
- Related: [bo-foils](/projects/bo-foils.md), [bo-ipa](/projects/bo-ipa.md), [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md)
- Source files: `bo_driver.py` (FoilsFlashMode),
  `pipeline_templates/elebeam_flash/template.fcl`, `pipeline.py` (STAGES + Step 7),
  `graph/config.py` (chain/musing/targets), `mmackenz_table_plots/gp_predict_foilsflash.py`
- External: `Production/JobConfig/pileup/EleBeamResampler.fcl`; dataset
  `sim.mu2e.EleBeamCat.Run1Baa.001430_*.art`

## Where to take the flash objective next (pivot design, 2026-06-28)
**RESOLVED — REFUTED at n=48 (2026-06-29): the "downstream hole drives flash" claim
below is WRONG.** foilsflash03 added 30 evals (f_dn sampled to 0.58, vs ff02's ≤0.27);
on the full 48-row set **corr(flash, f_dn) = +0.05** (collapsed from the n=15 +0.62) —
a textbook narrow-range spurious correlation. corr(flash, f_up)=+0.27 (weak),
corr(sob, f_dn)=−0.52, corr(sob, flash)=+0.24. **Final verdict: foil geometry is NOT
a useful electron-flash lever — flash is weakly geometry-sensitive (~30% over sob
1.5–3.8), no single-knob driver, no trade-off.** The operator hole hypothesis was
well-motivated and worth the 30-eval test, but the data settled it negative. (The
n=15 hole section below is kept only as the cautionary trail; it is superseded.)

**[SUPERSEDED — see RESOLVED above] ROBUSTNESS CORRECTION (2026-06-28): the claim
below was NOT robust.** The corr(flash,
f_dn)=+0.62 holds only over foilsflash02's NARROW f_dn∈[0,0.27] (qNEHVI kept f_dn
small — sloppy for sob); adding the SMOKE rows (f_dn out to 0.57) FLIPS it to −0.08.
f_up IS well-explored ([0.22,0.84]) and genuinely weak (+0.10–0.14). So: upstream
hole ≈ no flash effect (solid); downstream hole = INCONCLUSIVE (narrow range +
sign-flip + mixed stats). The BO never SCANNED the holes, so these observational
correlations are confounded. **Only a controlled scan settles it.** Note "min/bottleneck aperture" (the physically
right variable for on-axis flash transmission — tightest collimator wins) does NOT help
with existing data: downstream IS the min aperture in ~100% of foilsflash02 configs
(94% of all 18), so min-hole ≡ downstream-hole numerically → same +0.62 (narrow) /
−0.08 (wide) non-robust signal. CLEANEST TEST = sweep the bottleneck directly: set
**f_up = f_dn = f** and scan f over [0,0.95] at fixed rOut/hT + consistent production
stats (~6-8 forced-geometry points) — removes the up-vs-down confound and spans the
full aperture range the BO left pinned. The operator hole-size hypothesis is PLAUSIBLE
but unproven. The
section below (asserting the hole lever) OVERSTATES it — kept for the reasoning but
read with this caveat.

**The flash knob is the foil HOLE (downstream) — a small but FREE lever, NOT a null
(corrected 2026-06-28 after the operator hypothesis "flash depends on hole size"; see
the ROBUSTNESS CORRECTION above — the downstream part is NOT robust). THREE earlier
framings retracted: "graze on-axis", "muon-knob-not-electron-knob/thin-negligible",
and "weak/null".** The beam flash is
near-axis, so the central APERTURE governs it: open hole = flash passes; solid disc =
blocked/scattered. Leaderboard (foilsflash02, n=15):
- corr(flash, f_dn) = **+0.62** (and rIn_dn +0.62) — the DOWNSTREAM hole drives flash.
- corr(flash, f_up) = +0.14; corr(flash, bulk material) = +0.08 (NOT a material-amount
  effect — why the earlier bulk-material check missed it).
- corr(sob, f_dn) = **+0.11** (downstream hole SLOPPY for sob) => **closing the downstream
  hole cuts flash at ~ZERO sob cost = a genuine free lever.**
- corr(sob, f_up) = **+0.84** (OPEN upstream hole strongly HELPS sob; ~neutral for flash).

**Win-win geometry: OPEN upstream holes (max sob) + SOLID downstream discs (min flash).**
Every lowest-flash eval has f_dn=0; one still reaches sob=3.16.

**Caveat = MAGNITUDE, not direction:** the free lever is real but **modest (~10-14%)** —
the <=6 extra downstream foils are a small part of total flash blocking; the FIXED
base-37 holes (rIn=21.5) + DS material set the flash floor. More reduction needs
shrinking the base holes (fixed here = deployed target) or more downstream discs.
**qNEHVI UNDER-EXPLORED f_dn** (sloppy for sob => optimizer never pushed it => small
in-sample flash range => the original "weak/null" mis-read). A flash-aware campaign
(force f_dn down / add downstream discs) would map this properly. A bigger flash lever
still likely needs a continuous CE-transparent absorber in the DS flash path (IPA r~300
/ OPA r~454-728).
- **Cheap first step (data-driven, ~10 min, no new sim):** histogram the RADIAL
  distribution of the foilsflash02 `EarlyEleBeamFlash` StrawGasStep hits (outputs already
  on /pnfs) → tells us WHERE the flash lands → picks the absorber: small r → IPA
  (r~300), large r → OPA (r 454–728).
- **`ipaflash` (cheapest pivot, recommended):** reuse the existing [bo-ipa](/projects/bo-ipa.md) 5-D IPA-cone
  geometry + the already-built+validated `elebeam_flash` stage; only a new mode subclass
  (IPA geom + flash `extract_metrics`). The IPA is a continuous poly cone BETWEEN target
  and tracker (r~300), CE-transparent, and bo-ipa showed it intercepts particles there →
  far likelier to show a sob-vs-flash front than the foils.
- **OPA mode:** large-radius CE-free lever (thicken OPA at ~zero CE cost) — more upside if
  the flash is wide-angle, but needs a new geometry parameterization.

## Resolved / TODO
- RESOLVED: tarball mode-key omission ([foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md)), the
  EdepAna sci-notation parse ([edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)), the live
  smoke (foilsflashSMOKE4 PASS), the geometry-sensitivity go/no-go (answered: NULL — see
  RESULT), auxinput path (worked on real submit).
- OPEN (operator decision): close the line as a clean null, OR run the radial check →
  `ipaflash`/OPA pivot. Speedup Lever 1 (foilsflash03) only worth applying if re-running
  foilsflash to tighten the weak +0.26 — otherwise moot given the null.
- **SEARCH-BOX FLOOR is rail-pinned (2026-07-09)**: `extra_halfThickness` ∈ [0.01, 1.0] mm
  → min FULL thickness = **20 µm** (the "20 µm" in the deck is this box floor, NOT physics).
  The optimizer is pressed against it: **141/216 rows** have ≥1 extra at the 0.01 floor, and
  **every sob>3.5 row has hT_up=0.0100 exactly** (upstream mass only scatters the beam → drive
  it to min; hole/off-beam parking is the other lever). Al is manufacturable well below 20 µm,
  so the floor is loosenable, BUT expect diminishing returns — 20 µm is already ~1/5 the base
  foil's 105.6 µm (near-transparent). If thickness matters for the next foils-family line:
  widen the floor to ~4 µm and run a few forced probes at 5-10 µm upstream before assuming
  the gain; a rail-pinned box is a real (likely small) blind spot.
- **foilsflash10 = the widened-box probe (2026-07-09, q=8×1 hybrid, HT_FLOOR 0.01→0.002)**:
  launch itself validated the hypothesis-shape — the picker immediately railed 6/8 children at
  the NEW 0.002 floor (hT_up=0.002 on 5, one both-sides). Round then hit the
  [elebeamcat-tape-migration-elebeam-wipeout](/incidents/elebeamcat-tape-migration-elebeam-wipeout.md) incident: all elebeam jobs died (EleBeamCat
  moved to tape that morning), 0 rows landed despite VALID sob in every summary.json.
  **FINAL VERDICT (2026-07-10, all 7 rows recovered with real flash): sub-20 µm buys
  NOTHING on either objective.** sob: best 3.78 < the 3.82 rail. flash: the 4 µm points
  bottom out at 6.286e-7 (R00_03, BOTH extras at 4 µm) — statistically identical to the
  20 µm champion's 6.28e-7 and above the line floor 6.0e-7 (ff08R01_10). The extras are
  ALREADY transparent at 20 µm; the flash floor is set by the deployed 37-foil base, not
  extra-foil thickness. Only 1/7 recovered rows on the front (R00_07, 3.46/6.62e-7 knee).
  ~~RECOMMENDATION: REVERT HT_FLOOR to 0.01~~ **OVERTURNED hours later by foilsflash11
  (see next entry): the new line champion sits AT the 4 µm rail — ff10's n=7 "buys
  nothing" was premature. KEEP HT_FLOOR=0.002 and commit it.** R00_01 remains lost
  (rc=25 at mustops submit; not recovered).
- **foilsflash11 (2026-07-10, q=10×1 hybrid, FIRST elebeam=100 campaign): NEW CHAMPION.**
  10/10 rows (elebeam=100 config validated end-to-end, incl. mid-campaign inheritance of
  the default_loc=tape fix). **foilsflash11R00_07 = (sob 3.31, flash 5.976e-7) STRICTLY
  DOMINATES the 5-week champion ff05R00_04 (3.28, 6.277e-7)** — first-ever domination of
  the champion corner; also a new line flash-record (prev floor 5.999e-7 @ sob 2.03).
  Geometry: hT_up=0.002 (4 µm, the widened floor), hT_dn=0.146, from a qNParEGO pick.
  **CONFIRMED AT 400 JOBS (2026-07-10 17:26): flash = 6.259e-7** — the original 92-job
  5.976e-7 was a −4.5% downward fluctuation (NC02's 6.96e-7 an upward one; run-level flash
  σ ≈ 5% beyond subrun stats). FINAL STATUS: ties the prior champion in flash (6.259 vs
  6.277, Δ−0.3% = noise) and WINS sob (+0.03, ~3σ) → still the top point, but by sob not
  by a flash record; vs DEPLOYED (3.11/6.445e-7): −2.9% flash / +0.2 sob — "beats deployed
  on both axes" survives with a thinner flash margin. Leaderboard row updated to the
  400-job flash (backup .bak_champ400fix); summary.json sob restored to the valid
  concat-era 3.31 (the confirm harvest ran env-concatless and miscounted mu⁻ +1.5% from
  unfiltered TargetStops — pipeline harvest is now PRESENCE-driven on concat_outputs.txt).
  Hybrid attribution round 2: **ALL front additions came from the parego 40%** (R00_06
  3.72/8.37e-7 + R00_07 champion; parego 2/4 on front) — qNEHVI 0/6 (its high-sob corner
  picks 3.77/3.75 re-treaded known territory; corner exhausted). 15/17 new rows rail at
  hT_up=0.002 (flash-transparency drive).

## Open questions / TODO
- **Next-line candidate (2026-07-10): `bo-foilshole` — central stopping-target hole.**
  This line varied the OUTER envelope and bought ~5% flash at best; a CENTRAL hole
  (R≈18-21 mm) cuts flash ~30% + tracker dose ~30% at unchanged SES per
  [edmonds-target-hole-docdb10898](/external/edmonds-target-hole-docdb10898.md) (flash parents are central, RMS 24 mm). Non-obvious
  enabler: the foilsg **holeRadii-vector patch** (per-foil holeRadius already parseable by
  our patched StoppingTargetMaker + shipped in the grid tarball) means a central-hole knob
  is likely near-FREE geometrically — needs only a mode whose extras write per-foil inner
  radii on the deployed 37-foil base. On the post-2026-07-10 eval cost (~2.5-3 h, half
  footprint) this is plausibly 5-10× more flash headroom than anything left in this box.

- **foilsflash12 (2026-07-10, q=10×1 hybrid): FIRST FULL-STACK CAMPAIGN — speed stack delivered.**
  10/10 rows (244 total; two mid-round [harvest-pyroot-nfs-rpc-hang](/incidents/harvest-pyroot-nfs-rpc-hang.md) recurrences recovered
  in-flight), 10/10 elebeam presubmits fired, tarball cache + input probe live throughout.
  **Real eval wall: median 214 min (168 min best)** vs the 5.4 h pre-stack baseline ≈ **40%
  faster at ~half the grid footprint** (outliers 477-496 min were the two NFS-hang recoveries
  + one straggler). Attribution round 3: qnehvi 2/6, parego 3/4 on-front — 3-round tally
  qnehvi 6/18 (33%) vs parego 7/12 (58%); parego keeps winning per-pick at saturation
  (consider AUTORESEARCH_HYBRID_HV_FRAC≈0.4 next round). New front adds: R00_09
  (3.52/6.58e-7), R00_07 (3.40/6.37e-7), R00_06 (3.10/6.22e-7 — lowest flash at deployed-sob),
  R00_00/01 (3.72/8.30e-7, 3.66/7.15e-7 high-sob shoulder). Champion ff11R00_07 (3.31/6.259e-7
  corrected) HOLDS. All single-run flash values carry the σ≈5% run-level caveat.
- **foilsflash13 (2026-07-11, q=10×1 pareto_sob): SOB-CORNER EXPLOIT ROUND — cyan-dot testing
  works.** First live `pareto_sob` round (pure GP-mean-front picks, user-directed "focus on best
  sob region"). 10/10 rows (244→254), zero failures, barrier clean. **3 new Pareto points in the
  previously-empty 9-10e-7 band: R00_02 sob=3.80 @ 8.97e-7 (round best), R00_00 3.79 @ 9.35e-7,
  R00_04 3.76 @ 9.47e-7** — 3.80-class sob previously cost ≥1.04e-6 flash (ff09R00_00 3.81 @
  1.04e-6; transplant 3.90 @ 1.081e-6). 8/10 rows sob≥3.62: the picker maps the corner densely,
  validating mean-front exploitation at a data-adjacent corner (complements the ff09 lesson that
  acquisition ≠ mean-exploit elsewhere). **Winning upstream thickness is 34-52 µm full**
  (hT_up 0.017-0.026 across the top-4) — between the old 20 µm rail and the 105.6 µm base foil,
  confirming ff10's sub-20µm-doesn't-help-sob and localizing the optimum. Ops: first round at
  the elebeam=100 default (σ_flash 2.5%); eval wall 187-247 min (mean ~225) consistent with
  ff12's post-stack median 214; submit ramp 00:03→00:41 (~4 min/child, tarball cache working);
  ~75 min launch→first-submit cold-start remains the ChildTracker/shared-fit target.
- **foilsflash14 (2026-07-11, q=10 ×2 ROUNDS pareto_sob): ITERATED sob-corner exploit —
  self-found ceiling 3.82→3.84, five new front points.** R0 (10/10 rows, incl. 4 recovered
  after the mid-campaign stop for the Eval-summary refactor — parent survived a wrapper-PID
  kill and self-ran R1 once recovery rows landed): R00_00 3.81@8.97e-7, R00_03 3.76@8.27e-7,
  R00_07 3.66@8.09e-7. R1 (refit on 264 rows, 10/10, ALL sob≥3.66): **R01_00 sob=3.84 @
  8.14e-7 — best self-found sob ever at 25% less flash than the transplant;
  CONFIRMED at 400 jobs 2026-07-12 (8.141e-7 vs 8.162e-7 @92j, −0.3%; row
  updated, .bak_r01_00_400jfix; that harvest = first production run of the
  simplified Eval-summary path)** (rOut 121/118,
  hT 110/278 µm full, f 0.25/0.31 — NOTE: ~110 µm upstream, a THICKER recipe than ff13's
  34-52 µm winners; the corner has multiple designs); R01_07 3.84@1.02e-6 (dominated by
  R01_00); R01_05 3.69@7.78e-7 (new low-flash mark at high sob). Campaign total 20/20 evals
  despite the kill/recovery detour; R1 children ran the switchover harvest in production.
  The 7.8-9.5e-7 × 3.66-3.84 region — empty three days ago — is now densely mapped.
