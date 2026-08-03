---
type: project
title: bo-ipa — inner proton absorber 5D BO
description: (**code retired 2026-07-18**) 5D BO over the Run1A inner proton absorber;
  objective S/√B vs tracker StrawGasStep eDep from target-stop protons (via `MuStopPileup.fcl`);
  saturated at sob=3.31 (n=70, ipa04–11; deployed 0.511mm near-optimal); `IPAMode`
  + `mustops_pileup` stage deleted, leaderboard frozen
status: superseded
status_note: '`IPAMode` class + the ipa-only `mustops_pileup` stage DELETED from
  code 2026-07-18 (wound down 2026-06-27 at 70 evals: sob locked at 3.31 since
  ipa06, deployed thickness near-optimal). Leaderboard/pending TSVs remain frozen;
  `--mode ipa` is rejected; `_extract_trk_edep_per_pot` survives (foilsflash flash
  harvest reuses it); harvest trk_edep_* summary fields kept for archived
  summary.json back-compat. gp_loo_benchmark can no longer score the ipa archive
  (needs the deleted MODES entry) — its A/B numbers are recorded in
  ml-stack-review.'
timestamp: '2026-07-18'
updated_note: code retired
---

# bo-ipa — inner proton absorber 5D BO

## Summary
Optimize the **Run1A inner proton absorber (IPA)** geometry to trade **signal
significance S/√B** against **tracker energy deposition from muon-stop products**
— specifically the **protons (and other secondaries) from muon nuclear capture
on the Al stopping target**, which the IPA exists to absorb before they reach
the tracker. Same closed-loop qNEHVI machinery as [bo-foils](/projects/bo-foils.md); only the geometry
knobs and the second objective differ. The deployed 37-foil stopping target is
left untouched — only the IPA cylinder/cone varies.

## Key facts
- **IPA geometry knobs** live in `Offline/Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt`
  (included by `geom_run1_a.txt`; `protonabsorber.version=4`). 5D search:
  `thickness` (0.511 mm default), `halfLength` (500), `OutRadius0`/`OutRadius1`
  (300.5 each — cone taper), `distFromTargetEnd` (625). Overridden by appending
  `double protonabsorber.* = …;` after the geom include (same pattern as
  [bo-foils](/projects/bo-foils.md) `_geom_text`). Starting BO ranges (CONFIRM before live):
  thickness [0.1,3.0], halfLength [200,700], OutRadius0/1 [250,400],
  distFromTargetEnd [400,800] mm.
- **Second objective = tracker `StrawGasStep` eDep from target-stop protons**
  (pdg 2212 from the Al target), per POT — minimized. NOT calorimeter calo, NOT
  the signal primary's energy.
- **The Edep source FCL is `Production/JobConfig/pileup/MuStopPileup.fcl`**
  (Musing `…/SimJob/Run1Bak/Production/`). Header: "generate and produce Detector
  Steps from generic muon target stops." It resamples `TargetStops` (already
  produced by the `run1b_mubeam` stage), runs the capture-product generators
  (`muonCaptureProtonGenTool` + deuteron/neutron/photon/RMC/1809keV-gamma), and
  emits the full DetStepSequence → `StrawGasStep` (tracker) + CaloShowerStep.
  So the IPA chain gets a NEW `mustops_pileup` stage (MuStopPileup.fcl + IPA geom
  overlay) and the harvest sums proton-provenance StrawGasStep eDep there.
- **GOTCHA — EdepAna gives the WRONG tracker quantity.** `EdepAna`
  (`Run1BAna/workflows/src/EdepAna_module.cc`) `h_trk_front_energy_` is the
  *signal primary's* momentum at the tracker-front virtual detector
  (`VirtualDetectorId::TT_FrontHollow/TT_FrontPA`), NOT summed straw Edep from
  background capture products. Don't reuse it for the IPA objective.
- **Mode mechanics** (mirrors [bo-foils](/projects/bo-foils.md), minimally invasive): the 2nd
  objective rides the generic `Point.calo` slot (`= trk_edep_per_pot`), so
  `obj = sob − α·trk_edep` and qNEHVI(sob, −trk_edep) need no plumbing change.
  `IPAMode.extract_metrics` reads `trk_edep_per_pot` (falls back to
  `calo_per_pot` so the mock/dry-run path works). Uses **stock Run1Bak Musing**
  (no patched StoppingTargetMaker needed — no holeRadii vector).
- **Chain has NO run1b_mubeam (2026-06-19, user catch).** run1b (DS-off) exists
  ONLY to produce the foils `calo_per_pot` channel; IPA replaces calo with
  mustops_pileup tracker Edep, so run1b is dead weight. IPA chain =
  **`mubeam (→TargetStops) → concat → mustops_ce (S/√B) + mustops_pileup (Edep)`**
  (`GRID_STAGES_BY_MODE["ipa"]`, graph/config.py). Both mustops_* resample the
  concat MuminusStopsCat. Saves a full beam-sim stage.
- **mustops_pileup stage:** `pipeline_templates/mustops_pileup/template.fcl`
  (MuStopPileup.fcl + FTFP_BERT + IPA geom overlay + bfgeom_v01 DS-ON +
  TargetStopResampler MaxEventsToSkip). `STAGES["mustops_pileup"]` (njobs 100 ×
  2500 ev = half mustops_ce; run_number 1802; output `dts.*.MuStopPileup.*.art`).
  `cmd_submit` branch clones mustops_ce: hardlink-farm concat outputs + set
  `TargetStopResampler.fileNames` auxinput.
- **Harvest (`pipeline.py` `_extract_trk_edep_per_pot` + cmd_harvest Step 6):**
  gallery PyROOT sum of tracker `StrawGasStep.ionizingEdep()` over the
  mustops_pileup output, ÷ n_events → `trk_edep_per_pot` in summary.json.
  Config-sha check is now file-existence-keyed (tolerates the missing run1b).
  **TAG + IDIOM CONFIRMED (ipa01 smoke 2026-06-19):** Events-tree branch is
  `mu2e::StrawGasSteps_compressDetStepMCs__MuStopPileup.` → InputTag
  **`compressDetStepMCs`** (empty instance), accessor `s.ionizingEdep()`;
  ~0.029 MeV/event on the real file (88 ev / 180 steps / 2.55 MeV over 3 files).
  `mu2e::SimParticlemv_compressDetStepMCs__MuStopPileup.` also present → proton
  filter (pdg 2212) feasible later. **v1 sums ALL capture-product Edep**
  (proton-dominated).
  **TWO bugs the smoke caught (both fixed 2026-06-19):**
  (a) **brace bug** — the script is `python3 -c`'d WITHOUT `.format()` (unlike
  `_CALO_EXTRACT_SCRIPT`), so the copied doubled `{{ }}` were literal invalid
  Python (set-of-dict) → exit 1 → `trk_edep=None` → `obj=sob−α·None` TypeError →
  zero row (`cause=obj_unparseable`). Use single braces in non-`.format()`
  embedded scripts.
  (b) **gallery idiom** — `ev.getValidHandle(<type>)` fails PyROOT template
  resolution; MUST use the **`ev.getValidHandle[ROOT.std.vector("mu2e::StrawGasStep")]`
  subscript** idiom (then call with the InputTag per event).
  (c) **stdout-trailing-noise parse bug (3rd, found on ipa03 2026-06-20).**
  The harvest parsed the extractor result with `json.loads(stdout.splitlines()
  [-1])`, but **gallery/xrootd prints `Closing file, read N bytes …` to stdout
  AFTER our JSON**, so `[-1]` grabbed that line → `json.loads` →
  `Expecting value: line 1 column 1 (char 0)` → `trk_edep=None` →
  `obj_unparseable` zero row (ipa03: all 5 R0 children). **My earlier "end-to-end"
  check missed it because I eyeballed the JSON instead of running the actual
  `_extract_trk_edep_per_pot` parse.** Fix: print the result with a
  `TRKEDEP_RESULT ` sentinel prefix and parse the sentinel line, not `[-1]`.
  **Lesson: validate via the REAL parse function, not by reading the script's
  stdout.** Only the IPA mode hits all this; foilsf/prodtarget harvests are
  unaffected.
- **Status 2026-06-19:** `IPAMode` + registration + `botorch_predict.MODE_SPECS`
  + `graph/config.py` (musing=stock Run1Bak) + `closed_loop` + `state.py` +
  `gp_predict_ipa.py` shim + mustops_pileup stage + harvest extractor all built.
  91 tests pass; graph builds the 4-stage chain; `propose`/`closed_loop
  --dry-run` give valid 5D picks. REMAINING: 1-config live smoke to pin the
  StrawGasStep tag + confirm non-zero trk_edep.

## Saturation status (2026-06-27, n=70 ipa04–11)
**High-S/√B corner: SATURATED.** Best sob per campaign: ipa04 3.25 → ipa05 3.28
→ ipa06 3.31 → ipa07 3.29 → ipa08/09/11 all **3.31**. The ceiling has been flat
for ~40 evals (ipa06→ipa11); the top cluster (3.31/3.31/3.31/3.31) is within
σ(sob)=0.4% ([bo-noise-budget](/concepts/bo-noise-budget.md)) = statistically tied. Same plateau signature as
[bo-foils](/projects/bo-foils.md) at 3.89.
**Pareto FRONT: still being filled (NOT fully saturated).** The last 2 campaigns
(ipa09, ipa11) contributed **8 of the 22 current front points**, mostly on the
**low-trk_edep side** (incl. the lowest-edep corner ipa09R00_04 sob=2.54/edep=8.8e-3).
qLogNEHVI is still gaining hypervolume on the low-background end, but with
diminishing returns — no new high-sob ground.
**Verdict: wind down.** The headline result is locked (deployed 0.511 mm
near-optimal; max sob 3.31; knee ~0.6 mm / sob 3.01 / edep 1.67e-2). Further
rounds only refine the low-edep tail. If the #1 ranking matters, do a
confirmation/replica of the 3.31 cluster rather than more exploration.

## First empirical results (ipa04 R0, 2026-06-20) — trade-off CONFIRMED
First real IPA data (5 Sobol R0 points; harvest fully working). The predicted
thickness-driven (sob, trk_edep) trade-off is real:
| thickness mm | sob | trk_edep MeV/ev |
|---|---|---|
| 0.26 | **3.25** | 4.06e-2 (thin → high sob, high Edep) |
| 0.58 | 3.03 | 1.88e-2 (knee) |
| 2.45 | 2.61 | 2.70e-2 |
| 2.99 | 2.47 | 3.54e-2 (thick → low sob) |
| 2.03 (long/far) | 2.45 | **1.12e-2** (max absorption corner) |
sob spans **2.45–3.25**, trk_edep **1.1e-2–4.1e-2** — a genuine Pareto front,
matching the agent prediction (thin = protons leak ⇒ high Edep but low CE
scatter ⇒ high sob; thick = absorbs protons but scatters CE ⇒ low sob).
With α=80 the `obj` column is sensible (both terms O(1)).

**Knob dominance (Pearson corr over n=20, 2026-06-20):** thickness is THE
dominant parameter — **corr(thickness, sob) = −0.92** (sole S/√B driver; next is
OutRadius0 at 0.22). Tracker Edep is **multi-knob**: thickness −0.42, halfLength
−0.43, OutRadius0 +0.36 all co-lead (cut Edep by thicker + longer + narrower
upstream). **distFromTargetEnd ≈ 0 on both (inert)** — z-position barely matters
(protons helix over a long z-range); OutRadius1 also weak (−0.13/−0.12). So
thickness sets the Pareto axis; halfLength + OutRadius0 are the secondary Edep
levers; z and downstream radius are nearly irrelevant.

**ipa05/ipa06 COMPLETE → 30 pts total (ipa06 2026-06-21).** Successive campaigns
keep pushing the high-sob corner: thickness **rails to the 0.10 mm BO floor →
sob 3.28 (ipa05) → 3.31 (ipa06R01_03)** @ edep ~5-7e-2 (the "minimal
absorber" limit — thinnest wall = least CE scatter = max S/√B but max proton
background). Full front now: thin/floor 3.28@5e-2 → knee ~0.6mm 3.01@1.67e-2 →
thick 2.03mm 2.45@1.12e-2; deployed (GP est) 3.14@2.25e-2 between thin-corner and
knee. Thickness confirmed the dominant axis. (If the floor matters, note 0.10 mm
may be unbuildable — treat the thin corner as the asymptotic no-IPA limit.)

**ipa04 (R0+R1, 10 pts) — qNEHVI validates the deployed thickness.**
R1's exploit clustered ALL 5 picks at thickness **0.19–0.92 mm** (avoided the
thick region R0 showed was low-sob). Front:
- high-sob corner: thickness 0.19–0.26 → sob **3.25** @ edep 4.1–4.6e-2
- **knee (qNEHVI converged): thickness 0.63 → sob 3.01 @ edep 1.67e-2**
  (`ipa04R01_00`) — ~2.4× less tracker Edep than the 3.25 point for −0.24 sob
- low-edep corner: thickness 2.03 → sob 2.45 @ edep **1.12e-2**
**Key finding: the BO knee (~0.6 mm) sits right next to the deployed as-built
0.511 mm → the current Mu2e IPA thickness is near-optimal for the
S/√B-vs-tracker-occupancy trade.** The other 4 knobs (halfLength, OutRadius0/1,
distFromTargetEnd) stayed interior, modulating edep at fixed thickness — i.e.
thickness is the dominant Pareto axis, as predicted. (More rounds (ipa05) could
tighten the knee but the answer is already clear.)

## The IPA does NOT capture muons — too far from the beam (2026-06-20)
The IPA inner radius (~300 mm) is set OUTSIDE the target envelope (clears
stopping-target rOut=75 with margin). The muon beam is near-axis (stops in the
target at r<75); unstopped muons continue downstream still at small r, so the IPA
wall at r~300 sees negligible muon flux. It only intercepts the wider-angle
**capture protons** (emitted from target stops, helixing downstream to r~300).
**The BO data confirms it:** corr(thickness, sob) = −0.92 with thickness ONLY
*lowering* sob (via CE multiple-scatter) — if the IPA captured muons, adding
material would *raise* the stop count/sob. So an Al IPA would add no muon stops;
it would only worsen CE resolution. Implication: don't expect the IPA material/
mass to contribute signal — it's purely a background-shield-vs-CE-scatter knob.

## IPA physics (for interpreting the optimum; 2026-06-19 agent research)
- **Capture-proton source:** μ⁻ on Al-27 captures ~61% (39% DIO); a few % of
  captures eject a proton. Spectrum is evaporation-like — threshold few MeV,
  **peak ~3–5 MeV, exponential tail to ~tens of MeV**, emitted ~isotropically
  from the ST foils (r<75 mm). Highly ionizing → big tracker-straw Edep if they
  reach the tracker.
- **Why polyethylene / ~0.5 mm:** low-Z + H-rich = high proton stopping power
  but large X₀≈50 cm (≈0.001 X₀ at 0.5 mm) so it barely perturbs the 105 MeV CE.
  Proton range in poly: **~0.35 mm @5 MeV, ~1.2 mm @10 MeV, ~4 mm @20 MeV** — so
  0.511 mm fully stops only the ≲6–7 MeV bulk and degrades the rest.
- **The 0.511 mm is an as-built MEASURED value** ("S. Krave 6/22/2021"), NOT a
  documented optimization → genuine headroom. Currently a CYLINDER
  (OutRadius0=OutRadius1=300.5) in a file that supports a cone taper.
- **CE cost** (the competing objective): each mm of IPA the CE crosses adds
  multiple-Coulomb-scattering (smears the 104.97 MeV peak → ↓sob) + dE/dx
  down-shift; CE may cross the wall >once on its helix. Beyond ~2–3 mm the
  resolution penalty overwhelms the proton-shielding gain.
- **Distinct from the Outer Proton Absorber (OPA):** 20 mm polyethylene at
  r 454–728 mm does bulk shielding; the IPA is the thin CE-transparent inner one.
  Don't confuse them. Design basis: Mu2e docdb-3186/3155/3006/2259 (not
  web-accessible), [TDR arXiv:1501.05241].
- **Predicted optimum direction:** thickness is the dominant Pareto knob; if
  trk_edep is weighted, optimum likely pushes thickness **~1–2 mm** (catch the
  proton tail) before CE scattering bites; radius wants to be **as small as the
  CE-helix clearance allows**; cone taper is the lever to hug the proton cone.
  Expect a soft/broad front (like foils), deployed point at the
  low-thickness/high-sob corner. (Prediction — no IPA BO data yet.)

## Picker MUST be qnehvi (NOT qlnei) + front exploration works normally
- **Use `--picker qnehvi`.** qNEHVI explores the IPA (sob, −trk_edep) Pareto
  front exactly as it did foils (sob, −calo): it `Standardize`-normalizes both
  objectives internally, so the magnitude gap (trk_edep~0.029 vs calo~1e-5) and
  α are irrelevant to the search. Genuine trade-off exists (thicker IPA → ↓Edep
  but ↓sob → curved front), so qNEHVI has a real front to map.
- **Do NOT use qlnei for IPA** — qlnei is sob-ONLY (drops run1b/the 2nd
  objective). For foils that was a deliberate ceiling-test; for IPA it would
  silently throw away trk_edep, the whole point of the line.
- Caveat: qNEHVI `optimize_acqf` has timed out on dense near-saturated fronts
  before ([qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)) — a late-stage robustness issue, not
  IPA-specific; early/sparse IPA is fine.
- **Cloud/Pareto rendering TODO:** `cloud_plot.render_density` is hardcoded to
  the calo axis (LogNorm 1e-8…1e-4); to visualize the IPA front, rescale the 2nd
  axis to trk_edep's ~0.01–0.05 MeV range. Just axis retuning.

## α (alpha) is VESTIGIAL — do NOT bother tuning it
α is a leftover from the old skopt scalarized era; **qNEHVI ignores it entirely**
([scalarized-objective](/concepts/scalarized-objective.md) Key facts). It was **never tuned for foils or
prodtarget** — it sat at the default 1e5 and nobody cared, because the campaigns
are ranked by the raw `sob`/cost columns, not the `obj` column. Same for IPA:
with trk_edep~0.029 (≫ calo~1e-5), the `obj` column reads ~−2900 — cosmetic junk
nobody reads, NOT a problem. ipa02 was launched with `--alpha 80` (harmless,
makes obj less silly) but it makes **zero** difference to the optimization.
**Lesson: don't re-flag α as something to fix** — the durable result is the
α-independent (sob, trk_edep) Pareto front.

## Slide deck + plots (created 2026-06-20)
`docs/ipa_talk.{md,html}` (6 slides, marp, foils-style). Deck → generator map
(all under `mmackenz_table_plots/`, run with `.venv-botorch`, write into `docs/`):
- **`ipa_predicted_cloud.png`** ← `gp_predict_ipa_cloud.py` — SELF-CONTAINED GP
  density cloud (does NOT use `cloud_plot.py`, which is hardcoded to the calo
  y-axis). Two sklearn GPs (sob, log10 **trk_edep**) on `leaderboard_bo_ipa.tsv`
  over the 5D box; Sobol N=16384 pushforward; y-axis = tracker Edep (MeV/event,
  log ~1e-2..1e-1), NOT calo; evals colored by thickness; deployed-0.511 ringed.
- **`ipa_geometry_sketch.png`** ← `sketch_ipa.py` — r-z schematic of the IPA cone
  (default knee `ipa04R01_00`) with target + tracker context; wall ×60 for
  visibility. (Geom note: IPA is DOWNSTREAM of the target — z 6901–7901 vs target
  ~5471–6271 — protons helix downstream in the DS field to reach it.)
Render: `cd docs && CHROME_PATH=… npm_config_cache=/tmp/oksuzian_npm_cache npx -y
@marp-team/marp-cli@latest --html --allow-local-files ipa_talk.md -o ipa_talk.html`.
No commit/push (operator reviews, like foils). Refresh both PNGs as rounds land.
- **Nominal/deployed marker (2026-06-20):** no eval lands exactly at the deployed
  geometry, so the cloud plots the GP posterior-MEAN estimate at NOMINAL =
  [thickness 0.511, halfLength 500, OutRadius0/1 300.5, dist 625] → **sob 3.14,
  trk_edep 2.25e-2** (red ★). It sits high on the front near the knee — another
  confirmation the deployed config is near-optimal. (To get a MEASURED nominal
  point, submit one config at those values.)

## Cross-links
- Related: [bo-foilsflash](/projects/bo-foilsflash.md) (clone of this mode's structure), [bo-foils](/projects/bo-foils.md) (predecessor mode pattern + qNEHVI machinery),
  [scalarized-objective](/concepts/scalarized-objective.md), [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md) (StrawGasStep
  needs PyROOT under muse, not uproot), [bo-foilsflash](/projects/bo-foilsflash.md)
- Source files: `bo_driver.py` (IPAMode),
  `mmackenz_table_plots/gp_predict_ipa.py`,
  `Production/JobConfig/pileup/MuStopPileup.fcl`,
  `Offline/Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt`

## "Better config" synthesis (2026-06-20) — gains are material + OPA, not IPA
The deployed single-poly **cylinder is already near-optimal** (BO knee ≈ deployed
0.511 mm). Ranked improvements:
1. **Material → borated polyethylene**: μ⁻ capture on Al sprays neutrons (~1–2/
   capture) as well as protons; plain poly only MODERATES neutrons (H elastic),
   doesn't remove them. Borated poly = moderate-then-absorb in one material:
   H thermalizes, then **¹⁰B(n,α)⁷Li (~3840 barns thermal)** captures — products
   short-range (stay local), and it avoids the 2.2 MeV H(n,γ) gamma. Small B
   loading → same proton-stopping-per-X₀, no CE penalty. **CAVEAT: the current
   objective (tracker straw Edep) is PROTON-dominated and neutrons barely ionize
   the thin straw gas, so the direct trk_edep gain may be modest — borated mainly
   helps the broader neutron background/activation.** No-downside, possible-upside
   swap (vs Al = clear downside). Stay low-Z/H-rich; never Al/denser.
2. **OPA, not IPA, is the big lever:** the Outer Proton Absorber (r 454–728) is
   OUTSIDE the ~300 mm CE helix → thickening it cuts tracker proton Edep at ~zero
   CE cost. **Thin IPA + thicker OPA likely beats any IPA-only change.** (Verify
   the OPA-is-CE-free claim before building.)
3. **Thickness:** keep ~deployed; nudge to the ~0.6–0.8 mm knee ONLY if tracker
   occupancy is the binding constraint (cuts proton Edep ~2.4× for ~0.2 sob).
4. **Shape:** cylinder (cone/helical buy nothing — see below).
Next mode candidates to test head-to-head: a material categorical
(plain/borated poly) arm, and an IPA+OPA joint mode.

## Alternative geometries (v2 directions; 2026-06-19 agent analysis)
Ranked extensions beyond the current 5D single-cone, all reusing existing
profile-mode code (`prodtarget6d` K-quadratic / `foilsg` z-groups):
- **Thickness-z PROFILE (highest value):** thickness is one scalar today, but
  the CE crosses only a localized helix arc while protons exit over the whole
  z-range → make the wall thick where protons are dense but the CE doesn't cross,
  thin where it does. K=3 thickness(z) control points. Exploits the dominant
  asymmetry the cone can't express.
- **OPA is the CE-FREE lever (most interesting):** the Outer Proton Absorber
  (20 mm poly at r 454–728 mm) sits OUTSIDE the ~300 mm CE helix, so thickening
  it cuts tracker proton Edep at ~ZERO CE cost. The current mode optimizes only
  the *inner* (expensive, in-CE-path) absorber. A joint IPA+OPA (or OPA-only)
  mode likely gets most of the Edep reduction for free — arguably a better
  target than the IPA alone. VERIFY the "OPA is CE-free" claim before building.
- **K-point radius profile** (vs straight linear cone) — hug the non-linear
  proton-cone spread.
- **Material** categorical — explore LOWER-Z / more-hydrogenous, NOT denser.
  **Figure of merit = proton-stopping-power per radiation length** (CE multiple
  scattering ∝ √(x/X₀)). X₀: polyethylene **78.8 g/cm²** vs aluminum **24.0
  g/cm²** → Al packs ~3.3× more X₀ per gram. At EQUAL proton stopping, Al
  scatters the CE **~2× more** (√(0.8·24/79)≈0.5) → **thin Al is WORSE for
  momentum resolution**, which is exactly why Mu2e chose poly. **CORRECTION
  (2026-06-19): an earlier "poly+thin-Al liner (denser→less scatter)" note here
  was backwards** — denser/higher-Z reduces length but increases X₀-traversed.
  Good material candidates: higher-H-density poly, or borated poly (also eats
  capture neutrons). Al only "helps" resolution by stopping FEWER protons (=
  just less material; sacrifices the trk_edep objective).
- **NOT worth it:** holes/apertures (isotropic protons leak through), offset/
  non-coaxial (isotropic → coaxial optimal).
- **Cone vs cylinder — barely matters (BO, 2026-06-20).** The radius knobs are
  weak: OutRadius1 corr ≈ −0.13/−0.12 (nearly inert), OutRadius0 corr 0.22/+0.36
  (mild). Knee came out ~cylinder (345 vs 334, 3% taper); deployed is a true
  cylinder. Thickness dominates; tapering buys little.
- **Helical IPA — predicted NO gain (not yet tested).** (1) **No pitch resonance
  — quantified:** a capture proton at the ~5 MeV spectral peak has
  p=√(2·m_p·E)≈√(2·938·5)≈**97 MeV/c**; in the ~1T DS field its gyroradius
  r_L=p⊥/(0.3B)≈**32 cm** (≈ the IPA radius — that's WHY protons reach r~300mm),
  but its helix **pitch=2π·p∥/(0.3B)≈1–2 m** (~4 m for the tens-of-MeV tail).
  Any buildable absorber-helix pitch is ~cm → **~100× mismatch, no resonant
  threading possible**; same lesson as [bfield-at-helical-plug](/concepts/bfield-at-helical-plug.md) (muon pitch ~1m
  ≫ plug halflength; "matched-pitch filter" model was WRONG). (2) A helix leaves
  azimuthal GAPS → isotropically-emitted protons escape; wind it tight enough to
  close the gaps and it's just a cylinder with the same material → helical is
  worse-or-equal, never better. (3) Wrong discriminant: the IPA separates by
  RANGE (5 MeV proton ranges out in ~0.35mm poly; 105 MeV CE ignores 0.5mm), a
  dE/dx×thickness×(low-Z) effect a uniform cylinder already optimizes; geometry
  adds nothing. (4) Helical gives the CE a position-dependent path → non-uniform
  resolution smear (worse than the cylinder's uniform minimal path). The winning
  direction is thin + uniform + low-Z, not geometric cleverness (cf [bo-helical](/projects/bo-helical.md),
  retired after saturating; consistent with thickness corr(sob)=−0.92 dominant,
  shape inert). Could add a helical arm as a null-result CONFIRMATION, but physics
  + the helical-plug result both say no gain.

## Open questions / TODO
- Confirm physical knob bounds (IPA inner radius must clear stopping-target
  rOut=75 and stay inside DS2).
- `mustops_pileup` harvest: filter StrawGasStep to proton provenance
  (pdg 2212 from target) vs all capture products — needs SimParticle truth;
  decide PyROOT-under-muse vs an EdepAna-style analyzer (rebuild). Verify
  StrawGasStep + SimParticle are persisted in the MuStopPileup output.
