# Leaderboards — TSV result history

**Type:** dataset
**Status:** active
**Updated:** 2026-07-17

## Summary
One TSV per BO driver, append-only, recording every evaluated configuration
along with the metrics and scalarized objective. Used both as the BO history
(re-fed to GP via `opt.tell` on next propose) and as the human-readable record.

## Key facts
- **`leaderboard.tsv`** — **REMOVED 2026-05-21** (original 1D thickness scan;
  only consumer was `autoresearch_loop.py`, also removed).
- **`leaderboard_bo.tsv`** — 7D foil BO history (kept). Sole readers are now
  `slides/analyze_bo.py` and the data-side
  `mmackenz_table_plots/overlay_bo_on_s_sqrt_b.py`; the producing driver
  `autoresearch_bo.py` was removed 2026-05-21.
- **`leaderboard_bo_helical.tsv`** — 5D helical history (kept).
  Rows contaminated by silent disc/plug sibling overlap; was consumed as
  legacy training data by `mmackenz_table_plots/gp_predict_helical.py`
  (HELICAL_LEGACY) until HelicalMode's deletion (2026-07-12) broke that
  script's driver import (see [[bo-helical]]); kept as a frozen archive.
  **2026-05-27 cleanup**: dropped 213→175 main rows (38 quarantined), and
  47→44 for the legacy 5D file (3 quarantined). See sidecar entries below.
- **`leaderboard_bo_helical_v2.tsv`** — current canonical helical leaderboard
  (4D Option-A coupling). Actively appended by [[graph-runner]] iterations.
- **`leaderboard_bo_foilsg.broken.tsv`** (created 2026-06-12) — ENTIRE
  62-row foilsg leaderboard quarantined: every row was measured on
  uniform-hole geometry (unpatched StoppingTargetMaker scalar fallback —
  see [[foilsg-grid-tarball-scalar-holeradius-fallback]]); the f_g knob
  columns describe geometry that was never built. The fresh
  `leaderboard_bo_foilsg.tsv` starts empty for the post-fix foilsg07
  restart. **Future loaders MUST NOT seed the per-group-hole GP with these
  rows** (they would inject spurious f_g structure); they remain valid only
  as samples of the uniform-hole family.
- **`leaderboard_bo_helical_v2.broken.tsv`** + **`leaderboard_bo_helical.broken.tsv`**
  (created 2026-05-27, re-created after the 2026-05-21 deletion) — sidecar
  quarantine of all rows flagged by the [[scan-broken-codes-too-narrow]]
  full census (LikelyGeomOverlap > 100). 38 rows in the v2 sidecar
  (helicalL01–L05, helical037a/041a/050a/051a/052a, helicalH2, graph007–024,
  graph027, helicalNG02/05, helicalRA01–04, helicalPC01R00_02,
  helicalPC02R00_03/04, helicalPC03R01_00, helicalFT03R00_02,
  helicalQR00_02_noise, helicalTWB04_tess), 3 in the legacy sidecar
  (helical015, helical022, helical028). **Future loaders MUST NOT silently
  union these back into training**; the `_is_broken` gate in
  `gp_predict_helical.py:117` was already excluding them so the GP cloud is
  unchanged, but plot-overlay scripts that read the main TSV directly
  benefit from the cleanup.
- **Backup convention**: pre-cleanup snapshots at
  `<file>.tsv.bak.YYYYMMDD_HHMMSS` (2026-05-27 backups timestamped
  `20260527_121530`).
- **`leaderboard_bo_michael.tsv`** — [[bo-michael]] history
  - Columns: `config tsda_rin tsda_halfLength4 holeRadius col5 sob calo alpha obj`
  - Created on first append; header is locked once written
- **Foils mode → leaderboard mapping (load-bearing; `autoresearch_bo_michael.py:685,935`):**
  - `--mode foils` (`FoilsMode`) → **`leaderboard_bo_foils_v2.tsv`**; knob cols
    `extra_rIn_up/dn` = **absolute** inner radius (mm). (`v1` = legacy 7D.)
  - `--mode foilsf` (`FoilsFracMode`) → **`leaderboard_bo_foils_v3.tsv`**; knob cols
    `extra_f_up/dn` = **fractional** hole `f = rIn/rOut`.
  - These are **different optimization spaces**, not versions of one search.
    The honest-hole champions (foilsf11/14, post-tarball-fix, sob≈3.83) and the
    slide-4 cloud all live in **v3 = `--mode foilsf`**.
  - **GOTCHA (cost a wrong-mode campaign 2026-06-18):** the closed-loop
    `--name-prefix` does NOT set the mode. foilsf15/foilsf16 carried a
    "foilsf" prefix but were launched `--mode foils`, so their rows landed in
    **v2** (absolute rIn), NOT the v3 honest-hole search they were meant to
    extend. Always pass `--mode foilsf` (and verify rows land in v3) when
    continuing the honest-hole line; the prefix is cosmetic.
- **Re-scalarization:** since both raw `sob` and `calo` are stored, you can
  recompute `obj` for any α post-hoc without re-running.

## Cross-links
- Consumed by: [[bo-michael]] (`load_history`), [[bo-foil]],
  [[bo-helical]], [[graph-runner]]
