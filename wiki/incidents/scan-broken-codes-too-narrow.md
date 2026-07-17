---
type: incident
title: scan_logs SCAN_BROKEN_CODES filter is too narrow
description: SCAN_BROKEN_CODES=("GeomSolids1001",) only; 19 configs with LikelyGeomOverlap
  > 100 (up to 28.5M on helical050a) entered leaderboard; champion status of top-3
  may be tainted
status: active
timestamp: '2026-05-29'
updated_note: parse-exception branch now broken-unknown to match missing-report
---

# scan_logs SCAN_BROKEN_CODES filter is too narrow

## Summary
`graph/pipeline_io.py:336` defines `SCAN_BROKEN_CODES = ("GeomSolids1001",)`
— the only signature that triggers `state/broken.txt` and gates the row out
of the leaderboard. `LikelyGeomOverlap`, `GeomNav1002`, and `Stuck Track`
warnings — even in the **millions** per config — are silently passed through.
Empirical scan across 159 configs shows the gate suppresses 3 configs but
**19 configs with `LikelyGeomOverlap > 100` (and several with 100k–4M)
landed in the leaderboard**, polluting GP training data with results from
geometries G4 considers broken.

## Key facts

### The gating policy
- Filter list: `SCAN_BROKEN_CODES = ("GeomSolids1001",)` only
  (`graph/pipeline_io.py:336`).
- Other patterns scanned but never gate: `LikelyGeomOverlap`,
  `GeomNav1002`, `StuckTrack`, generic `G4Exception`, `Error`, `Warning`,
  `FATAL`, `SEGV` (`_SCAN_PATTERNS` at L264-274).
- `GeomSolids1001` fires on `G4TessellatedSolid::SetSolidClosed` negative-volume
  (the [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) failure mode) — but the
  broader navigation overlaps (`LikelyGeomOverlap`) are NOT a trigger.

### Empirical census (2026-05-26, n=159 scanned configs)
- 3 auto-flagged broken (GeomSolids1001 hits): only PC03R01_01 (581 hits)
  was caught on a recent run.
- **19 configs** with `LikelyGeomOverlap > 100` entered the leaderboard.

### Post-filter top-3 by objective (2026-05-26)
Of the unfiltered top-3 obj champions, **only helical050a (rank #3) is
overlap-tainted**; helicalL02 and graph023 are clean. Post-filter ranking:

| Rank | Config | obj | sob | calo |
|---|---|---:|---:|---:|
| 1 | helicalL02 | 3.084 | 3.330 | 2.46e-6 |
| 2 | graph023 | 2.972 | 3.280 | 3.08e-6 |
| 3 | helical041a | 2.833 | 3.130 | 2.97e-6 |
| 4 | helicalL03 | 2.779 | 2.980 | 2.01e-6 |
| 5 | helicalL04 | 2.676 | 2.910 | 2.34e-6 |

So the "top-3 champion" status migrates from helical050a → helical041a;
the #1 and #2 stand.

### Plot overlay has a second leaderboard path (2026-05-26)
`overlay_gp_predictions_helical_mpl.py:115` `load_top_n_by_obj()` reads
`leaderboard_bo_helical_v2.tsv` directly to render gold-star "Top-3 obj"
champions — independent of the `gp_observed_helical.tsv` path that
`gp_predict_helical.py` writes. Without an explicit gate this helper would
re-introduce helical050a/NG05/RA-chain as champions even though the
cloud + observed stars exclude them. **Fixed 2026-05-26** by importing
`gp_predict_helical._is_broken` and filtering in the loader; the patched
overlay now reports `filtered 17 broken/overlap rows` and the gold stars
match the GP-trusted set.

### GP training-set scope (2026-05-26)
- `leaderboard_bo_helical_v2.tsv` = 196 unique configs (4D Option-A).
- `leaderboard_bo_helical.tsv` = 46 unique configs (legacy 5D, merged in).
- Union = **243 unique configs** training the GP cloud.
- `_is_broken()` gate at `gp_predict_helical.py:70-78` filters via
  `<grid>/<config>/state/broken.txt` existence; currently **3 flags on
  disk**: `helicalPC02R00_00`, `helicalPC03R01_01`, `helicalSR00_00`.
- Therefore GP fits on **~240 configs**, of which the **19 high-overlap
  configs (8% of training set)** are silently included — including the
  top-3 obj champion helical050a.
- Most polluted offenders:

  | config | LikelyGeomOverlap | Stuck Track | leaderboard obj |
  |---|---:|---:|---:|
  | helical050a | 28,512,942 | 28,512,942 | top-3 champion |
  | helicalNG05 | 4,040,332 | 4,040,332 | 2.570 |
  | helicalPC03R01_00 | 1,372,978 | 1,372,978 | 1.885 |
  | helicalRA04 | 778,736 | 778,736 | 2.650 |
  | helicalRA03 | 503,096 | 503,096 | 2.641 |
  | helicalRA02 | 309,466 | 309,466 | 2.577 |
  | helicalRA01 | 165,434 | 165,434 | 2.626 |
  | helicalNG02 | 62,976 | 62,976 | 2.529 |

### Monotonic angle → overlap-count scaling (RA chain)
Holding (dx=0.23, dy=110, hl=200) fixed and sweeping angle:
- ang=760 → 165k overlap
- ang=800 → 309k overlap
- ang=830 → 503k overlap
- ang=860 → 779k overlap
This is the helical plug self-clipping as twist density increases — same
failure mode as `tessellated-solid-facet-orientation` but at a different edge
of the angle range. The plug source-fix (G4TwistedBox primitive landed
2026-05-20) is supposed to handle it, but the **grid tarball repackage is
still pending** (per `tessellated-solid-facet-orientation` page status) — so
grid jobs still build against the old tessellated code.

### mmackenz table.org configs are structurally unverifiable (2026-05-27)
The mmackenz background scatter rendered on the cloud PNGs comes from
`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/table.org`. These
configs were produced by mmackenz's own pre-2026-05-21 pipeline, which
- builds against the **tessellated** `TSdAHelicalTube` (the dispatcher
  only landed in our `autoresearch_muse` on 2026-05-21), and
- does **not** emit `scan_logs/report.tsv` (no per-job G4Exception scan).

Consequence: we can never run `_is_broken()` against a table.org config —
they're "no report" rows by construction. The only on-disk filter is
`TABLE_BLACKLIST = {"v113"}` (`cloud_plot.py:28`), populated by hand from
incident reports. To verify a table.org point (e.g. v111 at
sob_rel≈0.48, calo≈1.07e-6 — `holeRadius=0` no-hole target + 4×85×150
360° helical plug + nsteps=5000), the only path is to re-run its knobs
through our pipeline with twisted-box + scan_logs. N_crit is a useful
*lower bound* on suspicion (v111's N_crit ≈ 33, far from the failure
regime), but `LikelyGeomOverlap` can fire at modest N_crit when the
tessellated plug grazes a sibling volume, so low N_crit ≠ clean.

### Silent-pass-on-missing-report covers 32/179 displayed configs (2026-05-26)
`gp_predict_helical._is_broken` returns `False` when `scan_logs/report.tsv`
is absent (gp_predict_helical.py:133-134). Parallel-agent audit of the GP
training pool found **32 of 179 v2 rows (17.9%) have no report.tsv** —
these are pre-2026-05-20 configs (graph001–graph024, graphsmoke00x,
helical037a–052a, helicalH2, helicalL01–L05, helicalQR00_0x, helical041a)
that predate the `node_scan_logs` graph node. The gate has **zero signal**
on them.

**Critical**: all three current top-3 obj champions sit in the silent-pass
set — `helicalL02` (sob 3.33, calo 2.46e-6), `graph023` (3.28, 3.08e-6),
`helical041a` (3.13, 2.97e-6). The GP fits the champion regime to rows
whose geometry-correctness is unknown. Two of these (L02, helical041a) are
explicitly on this incident's named-suspect list.

Subthreshold pattern in the 29 rows with `LikelyGeomOverlap ∈ [1,100]`:
all show counts `ovr=1-2, nav=1-2, stk=1-2` simultaneously — a single
event tripping all three counters, not a meaningful failure mode.

Options: (a) treat missing report.tsv as broken-unknown (drops 32 rows
including champions); (b) retro-run scan_logs node on archived legacy
`.log` trees; (c) document and accept the unknown taint.

**Option (a) landed 2026-05-26** at `gp_predict_helical.py:134`
(`if not rpt.exists(): return True`). Empirical impact of strict gate:
- filtered v2 rows: 17 → **49** (+32 silent-pass)
- GP training pool: 189 → **157**
- max GP-predicted sob: 4.67 → **4.28** (champion regime collapses)
- Pareto frontier: 169 → **589** (GP no longer anchored at high-sob tail)
- explore-pick #0 sob/calo: 3.8 / 1.9e-6 → **2.0 / 1.99e-6**

### Retro-scan of the 32 silent-pass configs (2026-05-26)
Ran `graph.pipeline_io.scan_worker_logs` on each of the 32 (driver:
`/tmp/retro_scan_legacy.py`). Result:

| outcome | n | configs |
|---|--:|---|
| **BROKEN** | **20** | helicalL01–L05, helical037a/041a/051a/052a, helicalH2, graph011–013, graph015–017, graph020, graph022–024 |
| clean | 5 | helicalQR00_00..04 |
| SKIP (pre-pipeline, no state dir) | 7 | graph001–005, graphsmoke001/002 |

The 20 BROKEN configs each show **>4M LikelyGeomOverlap** AND **>450
GeomSolids1001 hits** (every job in every stage tripped the
tessellated-facet-orientation pattern). Sample worst offender: helicalL02
mubeam=1.96M overlaps + 191 GeomSolids1001 (191/191 jobs broken);
mustops_ce=45.6M overlaps + 96/96 jobs broken.

**All three top-3 obj champions are in the BROKEN set**: helicalL02 (47M
overlaps, 481 GeomSolids1001), graph023 (35M, 480), helical041a (24M,
478). The "champion regime" the GP has been optimizing toward for the
past month is built on simulations G4 considered fundamentally broken.

The 5 clean QR00_* configs come from one early checkpoint batch run in a
non-pathological corner. The 7 SKIP configs have no state/output files
on disk and remain treated as broken-unknown.

Post-retro-scan refit (`gp_predict_helical.py` re-run):
- filtered: 49 → **44** (the 5 clean QR00_* recovered into training)
- training pool: 157 → **163**
- max GP-predicted sob: 4.28 → **4.33** (modest recovery)
- Pareto frontier: 589 → **469**
- explore-pick #0 sob/calo: 2.0 / 1.92e-6 (essentially unchanged — the
  recovered QR00_* sit at sob ~3.6 but at calo ~3e-6, above the 2e-6 cap)

The plot `gp_predicted_helical_cloud_mpl.png` now reflects only
geometry-validated training data; the gold-star "top-3 obj" pass also
drops to top-3-of-clean.

### A/B grid test at helical041a knobs confirms champion was an artifact (2026-05-26)
Re-ran helical041a knobs (`dx=0.57, dy=110, halflen=246, angle=538.77`)
through the new FCL-selectable dispatcher under both implementations
(configs `helicalTWB01_tess` and `helicalTWB01_twist`):

| branch | sob | calo | obj | vs original helical041a |
|---|---:|---:|---:|---|
| original (broken) | 3.13 | 2.97e-6 | 2.83 | (in retro-scan-BROKEN set: 24M overlaps + 478 GeomSolids1001) |
| tess (clean) | 2.91 | 6.55e-6 | 2.25 | calo 2.2× higher |
| twist (clean) | 2.71 | 6.49e-6 | 2.06 | calo 2.2× higher |

Neither clean reproduction recovers the original sob=3.13 / calo=2.97e-6
metrics. The calo inflation direction (clean > broken) matches the
[tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) mechanism (broken plug absorbs
stuck tracks, masking calo background). **Direct empirical proof that
helical041a's "top-3 champion" rank was a broken-geometry artifact, not
a real physics signal.** By extension the other two retro-scan-broken
champions (helicalL02, graph023) sit on the same artifact mechanism.

### helical050a (one of the top-3 obj champions) is in this set
- 28.5M `LikelyGeomOverlap`, 28.5M stuck tracks, 486 `GeomSolids1001` hits.
- Predates the scan gate (task #70 vs gate-add task #92).
- The "top-3 obj" status (`bo-helical.md`, `gp-cloud-rendering.md`) inherits
  metrics from a simulation G4 considers broken — its 3.08e-6 calo /
  4.04 sob ratio may be a numerical artifact of stuck-track behaviour, not
  a real physics signal.

### Full-census taint inventory (2026-05-27, n=211 scanned configs)
Walked all `<grid>/<cfg>/scan_logs/report.tsv`. Threshold `ovr>100`:
- 211 scanned; 80 with ovr>0; **44 tainted (ovr>100)**.
- 38 of the 44 sit in `leaderboard_bo_helical_v2.tsv`; 3 in legacy
  `leaderboard_bo_helical.tsv` (helical015/022/028); 3 not in either
  (`helicalPC02R00_00`, `helicalSR00_00`, `helicalPC03R01_01`).
- **Clean bucket gap**: zero configs land in 100–1000 overlap range —
  threshold 100 cleanly separates clean (ovr=0) from broken (ovr>10⁴).
  Bucket distribution of the 44 broken: >1e6: 31, 1e5–1e6: 9, 1e3–1e5: 4,
  1e2–1e3: 0.

### Two failure-mode taxonomy (2026-05-27)
The 44 broken split cleanly by `GeomSolids1001 (g4s)` co-presence:

| class | n | g4s | example configs | failure mode |
|---|--:|---|---|---|
| A. tess facet self-intersection | 28 | >450 | graph007–024, helical037a/041a/050a/051a/052a, helicalL01–L05, helicalH2 | [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) (N_crit exceeded) |
| B. nav-only overlap | 16 | 0 | helicalNG02/05, helicalRA01–04, helicalPC01R00_02, PC02R00_03/04, PC03R01_00, helicalFT03R00_02, helicalQR00_02_noise, graph027, helicalTWB04_tess | sub-N_crit geometry but G4 navigation reports thousands of LikelyGeomOverlap; current `SCAN_BROKEN_CODES=("GeomSolids1001",)` gate **completely misses these** |

Class B is the more dangerous bucket: configs build (no GeomSolids1001)
so the harvest-time gate passes them, yet G4 sees navigation overlaps —
likely the helical-plug × TSdA4-disc sibling overlap mode of
[tsda-disc-helical-sibling-overlap](/incidents/tsda-disc-helical-sibling-overlap.md) or thin-plate ÷ high-angle
tessellation creating G4Voxel binning pathology below the
self-intersection threshold (see [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md)
TWB04 entry for empirical example at dx=0.3mm × angle=600° below N_crit).

The `_is_broken` gate in `gp_predict_helical.py:117` (ovr>100) catches
both classes, so the GP cloud is protected. The TSV files themselves
still carry all 41 broken rows — repo-hygiene cleanup is a separate task
(see "Open questions").

### Parse-exception now treated as broken-unknown (2026-05-29)
`gp_predict_helical.py:158` previously returned `False` on `OSError` /
`ValueError` while reading `report.tsv` (e.g. truncated file mid-write,
encoding error, missing `LikelyGeomOverlap` column header). That
re-opened the same silent-pass hole the 2026-05-26 missing-report fix
had closed: a malformed report behaved like a clean one. Fix: return
`True` (broken-unknown), matching the missing-report branch at line 140.
Symmetric and conservative — any report we can't trust to read is treated
the same as no report at all.

## Cross-links
- Related: [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md), [tsda-disc-helical-sibling-overlap](/incidents/tsda-disc-helical-sibling-overlap.md),
  [bo-helical](/projects/bo-helical.md), [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), [calo-constant-across-helical](/incidents/calo-constant-across-helical.md), [elebeamcat-tape-migration-elebeam-wipeout](/incidents/elebeamcat-tape-migration-elebeam-wipeout.md), [foilsx04-all-preflight-ambiguous](/incidents/foilsx04-all-preflight-ambiguous.md), [preflight-past-init-false-pass](/incidents/preflight-past-init-false-pass.md)
- Source files: `graph/pipeline_io.py:336` (SCAN_BROKEN_CODES),
  `graph/pipeline_io.py:264` (_SCAN_PATTERNS), `graph/nodes.py:115`
  (node_scan_logs)
- Data: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<config>/scan_logs/report.tsv`

## Open questions / TODO
- Add `LikelyGeomOverlap` (with a threshold, e.g. > 100 or > 1% of events)
  to `SCAN_BROKEN_CODES` — currently it never gates.
- Re-evaluate champion list with broken-overlap rows filtered out.
  Quick test: refit GP excluding the 19 high-overlap configs and check
  whether helical050a / NG05 / RA-chain still sit on the Pareto front.
- Confirm whether the G4TwistedBox source fix (per
  `tessellated-solid-facet-orientation` 2026-05-20 entry) is actually
  in the grid Code.tar.bz2 yet — if not, ongoing closed-loop rounds
  keep producing tainted data at any angle ≥ ~700.
- Decide whether to mass-re-evaluate the 16 not-broken-flagged
  high-overlap configs once the grid lib is rebuilt, or just suppress
  them in GP training via a leaderboard-side filter.
