---
type: incident
title: foils GP cloud crashes on calo=0 sob-only-picker rows
description: foils GP cloud crashes on calo=0 sob-only rows (log10(0)=-inf); fix=calo>0
  filter; ALSO flags refresh-foils-talk skill stale vs live deck
status: resolved
status_note: (calo>0 filter added 2026-06-20)
timestamp: '2026-06-20'
---

# foils GP cloud crashes on calo=0 sob-only-picker rows

## Summary
`gp_predict_foils_v2v3_cloud.py` (the foils deck GP-cloud producer) crashes with
`ValueError: Input y contains infinity or a value too large for dtype('float64')`
when the v3 leaderboard contains `calo=0` rows. Root cause: the calo-axis GP is
fit on `log10(calo)` (`gp_predict_foils_v2v3_cloud.py:98`), and the sob-only
picker campaigns (qlnei / `AUTORESEARCH_NO_RUN1B`) write **`calo=0`** = "no calo
measured" → `log10(0) = -inf` → sklearn rejects the training target.

## Key facts
- As of 2026-06-20, **90 of 486** v3 rows have `calo=0`: foilsf08 (10), foilsf09
  (20), foilsf10 (20), foilsf12 (20), foilsf19 (20). All sob-only-picker runs
  ([qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)) that drop the DS-off run1b_mubeam stage, so calo is
  never measured and harvested as 0.
- These same `calo=0` rows are the deck's "inflated" champions: the top sob
  (foilsf19R01_00, **3.91**) is calo=0 and is explicitly the kind the deck's
  honest-vs-inflated caption warns about. They can't sit on a log-calo cloud.
- **Fix:** drop `calo<=0` rows before the GP fit. Added in the `--v3-only` branch
  (`gp_predict_foils_v2v3_cloud.py` after the `X=np.array(X3)...` line): mask
  `calo_obs>0`, print the drop count. Result: 486→**396** honest rows, fit
  succeeds. The `--honest-only` path already filtered `calo>0` (for foilsf11/14/17);
  this extends the guard to the default `--v3-only` path.
- The crash is silent in the background: my `... > log 2>&1; echo exit $?` wrapper
  reported the bash exit (0, from the trailing `tail`), NOT python's. Always grep
  the log for `Traceback`/`Wrote`, don't trust the wrapper exit code.

## Cross-links
- Source: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_foils_v2v3_cloud.py:82-98`
- Related: [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md) (writes calo=0), [refresh-foils-slides](/drivers/refresh-foils-slides.md),
  `refresh-foils-talk` (skill; see [refresh-foils-slides](/drivers/refresh-foils-slides.md)) (the skill — also STALE vs the live deck, see below)

## Open questions / TODO
- **`refresh-foils-talk` skill is out of date vs the live deck (2026-06-20).** The
  deck (`docs/foils_talk.md`) references `gp_predicted_foils_honest_cloud.png`
  (slide 4), `saturation_foils_v3all.png` / `saturation_foilsg.png` /
  `saturation_foilsf09_10_qlnei.png` — NOT the `foilsZ`/`v3only` artifacts the
  skill regenerates. The skill needs updating to the real producers before it can
  drive a correct refresh.
- **Actual producer map for the live deck (determined 2026-06-20), all under
  `…/mmackenz_table_plots/`, run with `.venv-botorch`, write to `docs/`:**
  - `gp_predicted_foils_honest_cloud.png` (slide 4) ← `gp_predict_foils_v2v3_cloud.py --honest-only`
    (foilsf11/14/17, calo>0 → 60 rows). **Static** — those campaigns are done, so
    regen is byte-identical; caption "60 honest-hole evals" stays valid. (The deck
    does NOT use the `--v3-only` cloud.)
  - `saturation_foils_v3all.png` ← `saturation_report.py <v3-leaderboard> --out …`
    (NO `--prefix` = all rows). cp not needed (writes via `--out`).
  - `saturation_foilsg.png` ← `saturation_foilsg.py` (own script; reads
    `leaderboard_bo_foilsg.tsv` which is near-empty — n=1 as of 2026-06-20).
  - `saturation_foilsf09_10_qlnei.png` ← historical qlnei A/B panel (2026-06-09);
    **static**, do not regen.
  - Eval count `486` appears once (slide-8 SATURATED verdict, line ~222); footer
    `n=251` is a different/older count — leave unless you know its definition.
- **`saturation_foils_v3all` ALSO ingests the 90 calo=0 rows** (same root cause):
  `saturation_report.py` doesn't crash (no log10), but calo=0 = "perfect calo"
  points sit at the front corner and can distort the HV/Pareto panels. Not yet
  filtered — decide whether the saturation panel should exclude calo=0 like the
  cloud does.
