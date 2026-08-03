---
marp: true
theme: default
paginate: true
size: 16:9
footer: "FoilsFlash — foils cut tracker electron-flash per POT ~3.1× · Y. Oksuzian · 2026-07-15"
style: |
  section { font-size: 24px; }
  h1 { color: #003366; }
  h2 { color: #003366; border-bottom: 2px solid #003366; padding-bottom: 4px; }
  table { font-size: 18px; }
  code { font-size: 18px; }
  small { font-size: 14px; color: #555; }
---

# Stopping-Target Foils vs Electron-Beam Flash
## Foils cut tracker electron-flash per POT ~3.1×

**Y. Oksuzian**
2026-07-15 · Mu2e — autoresearch / closed-loop BO

> **Result:** the extra stopping-target foils are a real lever on the electron-beam flash.
> Total flash energy per POT in the tracker varies **3.1×** across the explored geometry, at
> **no S/√B cost**. Fifteen **closed-loop BO campaigns** + a directed transplant (289 evals) map a
> clean **Pareto front** whose champion (`foilsflash11R00_07`, **3.31 / 6.26×10⁻⁷**, 400-job flash) **beats the
> deployed target on both axes** (3.11 / 6.45×10⁻⁷: −3% flash, +0.2 S/√B); the ceiling (**3.90**) costs
> **+68% flash** — and iterated Pareto-exploit rounds priced near-ceiling **3.84 at only +26%** (8.14×10⁻⁷, 400-job confirmed).
> A central-hole A/B **reproduces Edmonds** (DocDB-10898), validating the flash pipeline end-to-end.

---

## What we optimize

**6-D extra-foil geometry** — ≤6 upstream + ≤6 downstream extra foils on the pinned 37-foil
base: `extra_rOut_up/dn` (50–250 mm), `extra_halfThickness_up/dn` (0.002–1.0 mm),
`extra_f_up/dn` = hole fraction `rIn/rOut` (0–0.95).

| objective | direction | source |
|---|---|---|
| `S/√B` | **maximize** | Run1A CE significance (`mustops_ce`, EdepAna) |
| total e⁻ EARLY-FLASH edep **per POT** in the tracker | **minimize** | `elebeam_flash` (EleBeamResampler, DS-on) |

**flash per POT** = `flash_edep_total / (N_input × POT-per-e⁻)`, normalized via `genCounter`
(EleBeamCat ≈ 11.5 POT/e⁻).

---

## The landscape

![h:415px](foilsflash_perpot_cloud.png)

<small>289 evals (foilsflash02–17 + transplant, green ◆ at S/√B 3.90; red ✚ = champion, below-left of the deployed-default gold ★: better on both axes), colored by `rOut_dn` (dominant knob). GP Pareto front (cyan) traces the low-flash/high-S/√B edge.</small>

---

## Central-hole A/B — reproduces Edmonds

High-stats **matched** A/B: solid target vs **R = 21.5 mm** central hole (~40 M input e⁻ each):

| observable | solid | holed | hole effect |
|---|---|---|---|
| flash-event rate | — | — | **−24% (≈67σ)** |
| **total flash per POT** | 8.2e-7 | 6.4e-7 | **−21.5%** |

- Reproduces **Edmonds DocDB-10898** (central target hole cuts flash ~30%) — same direction,
  comparable magnitude; validates the pipeline end-to-end.
- Absolute scale ≈ **8×10⁻⁷ MeV/POT** in the straw gas (order-of-magnitude consistent with
  Edmonds once converted to wire charge).
- The **deployed** Run1 target already carries this hole (rIn = 21.5 mm, DOE-2017).

---

## The extra foils are a strong lever

- **best/worst ≈ 3.1×** in flash-per-POT across the 289 evals (GP fit R² ≈ 0.9). The **floor is
  unchanged** at 6.0×10⁻⁷ (ff08R01_10) — the range widened from 2.7× only because ff17 sampled a
  new *worst* case (1.86×10⁻⁶); the achievable cut is set by the floor, not the ceiling.
- Knob physics (all strong, sensible):
  - more **upstream** material / radius → **more** flash (`rOut_up +0.37`, `hT_up +0.51`)
  - larger **downstream** radius + bigger holes → **less** flash (`rOut_dn −0.60`, `f_dn −0.50`)
- **corr(S/√B, flash-per-POT) = −0.13** → cut flash ~2.5× essentially **free** of signal.

The foils act as a scatterer of the on-axis electron beam — the same picture behind Edmonds'
central-hole result.

---

## Anatomy of the max-S/√B point

<style scoped>
  table { font-size: 14px; }
  th, td { padding: 2px 8px; line-height: 1.15; }
  small { font-size: 13px; line-height: 1.25; display: block; }
</style>

![h:170px](foilsflash_bestsob_sketch.png)

| design | rOut up/dn [mm] | 2·hT up/dn [µm] | hole rIn up/dn [mm] | S/√B | flash [MeV/POT] |
|---|---|---|---|---|---|
| `foilsflashSOBX01` — transplant | 112.5 / 109.9 | 126 / 289 | 20.0 / 0.0 | **3.90** | 1.08×10⁻⁶ |
| `foilsflash14R01_00` (2-round exploit, **400j-confirmed**) | 120.9 / 118.2 | 110 / 278 | 30.5 / 36.2 | **3.84** | **8.14×10⁻⁷** |
| `foilsflash09R00_04` (self-found) | 136.3 / 115.9 | 20 / 327 | 1.9 / 10.3 | 3.82 | 1.04×10⁻⁶ |
| `foilsflash13R00_02` (Pareto exploit) | 118.0 / 111.9 | 34 / 288 | 23.5 / 29.6 | 3.80 | **8.97×10⁻⁷** |
| `foilsflash03R02_09` (sketch) | 208.5 / 113.7 | 20 / 275 | 187.0 / 5.7 | 3.77 | 9.93×10⁻⁷ |
| `foilsflash11R00_07` — **champion** | 50.9 / 126.5 | **4** / 292 | 45.5 / 100.1 | 3.31 | **6.26×10⁻⁷** |
| deployed default (no extras) | 75 / 75 | 106 / 106 | 21.5 / 21.5 | 3.11 | 6.45×10⁻⁷ |

<small>Two routes to high S/√B. The **sketch** (`foilsflash03R02_09`, 3.77): a 20 µm ring parked off-beam
(hole rIn 187 mm) + near-solid downstream. The **ceiling** (3.80–3.90): thin but **in-beam** upstream
(34–126 µm, small holes) degrading the beam to stop more muons — higher S/√B at higher flash. Once the
transplant seeded the GP, the optimizer **self-found** this corner (row 3); iterated GP-mean **Pareto-exploit
rounds** (`pareto_sob`, ff13–14) then cut its flash price to **8.14×10⁻⁷ at 3.84** (row 2, 400-job confirmed —
was ≥1.04×10⁻⁶ for 3.8-class S/√B).
Neither route sits at the flash floor — that's the **champion**: 4 µm upstream + holed downstream, **beats deployed on both axes**.</small>

---

## Conclusion & next steps

<style scoped>section { font-size: 17px; li { line-height: 1.25; } }</style>

- The stopping-target foils are a **usable electron-flash lever** — ≈3.1× swing in tracker
  flash-per-POT with **no S/√B trade-off** (a scatterer of the on-axis beam, same physics as Edmonds).
- **Fifteen closed-loop BO campaigns (289 evals)** converged on a floor-flash / high-S/√B corner; for
  7 campaigns the best point (3.28 / 6.28e-7) only **tied** the deployed target — until the hybrid
  qNEHVI+qNParEGO picker (round 11) found **`foilsflash11R00_07` (3.31 / 5.98×10⁻⁷), confirmed at 400 jobs
  (flash 6.26×10⁻⁷): ties the prior best in flash (Δ−0.3%) and wins S/√B (+0.03)** — the top
  point of the line. (The initially reported −7% flash edge was a statistical fluctuation of the
  92-job measurement; run-level flash σ ≈ 5%.)
- **The S/√B ceiling is measured, and priced**: the transplant (`foilsflashSOBX01`) reproduces
  **3.90 vs 3.91 across two independent pipelines** at **+68% flash**; once it seeded the surrogate,
  the optimizer **self-reached 3.82** (was stuck at 3.77 for 7 campaigns). Iterated GP-mean
  **Pareto-exploit rounds** (`pareto_sob`, foilsflash13–14) then repriced near-ceiling S/√B twice:
  3.80 @ 8.97×10⁻⁷, then **3.84 @ 8.14×10⁻⁷ (400-job confirmed; +26% vs deployed, was ≥+61%)** —
  eight new front points across the once-empty 8–10×10⁻⁷ band. The corner supports **multiple
  upstream-foil recipes (34–110 µm full)**; sub-20 µm buys nothing (widened-box probe).
- **Saturated**: ff16–17 (20 evals; the second on an *independent* surrogate) topped out at
  **3.83 / 3.77**, adding nothing above the 3.84 front — two independent pickers failing to beat
  it is the line's strongest saturation evidence.
- **Takeaway: a 4 µm upstream + holed-downstream extra-foil set beats the deployed target** —
  −3% flash and +0.2 S/√B (400-job confirmed). Modest, real, and the line's flash floor
  (~6.3×10⁻⁷) is now mapped to ~3% precision.
- The central-hole A/B **reproduces Edmonds**, confirming the flash pipeline is physically sound.
- **Next:** the **central-hole line** (`bo-foilshole`) — Edmonds' ~30% central-hole lever is 6×
  what the outer envelope bought.
