---
type: driver
title: refresh-foils-slides
description: (**script trio DELETED 2026-07-17** — captions stamper clobbered the
  live deck footer) now the record of per-deck figure→generator maps; refresh path
  = refresh-foils-talk skill
status: superseded
timestamp: '2026-07-17'
updated_note: '**the script trio was DELETED** — this page is now the record of
  the per-deck figure→generator maps, which remain current'
---

# refresh-foils-slides

> **2026-07-17: `tools/refresh_foils_slides.sh` + `tools/stamp_foils_highlights.py`
> + `tools/refresh_foils_talk_captions.py` were deleted** (simplification
> audit): the captions stamper's marker-free footer rewrite reached the live
> `docs/foils_talk.md` destructively (stale v1 counts), and the .sh managed an
> image set the live deck no longer references. The refresh path is the
> refresh-foils-talk project skill / refresh-deck user skill, per the
> generator maps below. 3 of the script's 7 managed PNGs survive in docs/
> because wiki concept pages cite them (gp_predicted_foils_cloud.{gif,png},
> diversity_overlay_foils.png); the other 4 were deleted.

## Three live decks now (foils + ipa + prodtarget6d), all hand-refreshed (2026-06-22)
There are now THREE active study decks in `docs/`, none driven by
`refresh_foils_slides.sh` — each is refreshed by regenerating its figures then
marp-rendering by hand. Per-deck figure→generator (all generators under
`mmackenz_table_plots/`, run `.venv-botorch`, then `cp` the PNG into `docs/`
EXCEPT saturation_*/ipa which write `docs/` directly):
- **foils_talk** → `gp_predict_foils_v2v3_cloud.py --honest-only` (honest cloud),
  `sketch_foil_champions.py`, `saturation_report.py <v3.tsv>`, `saturation_foilsg.py`
  + hand-built slide-5/7 HTML tables (see below).
- **ipa_talk** → `gp_predict_ipa_cloud.py` (writes docs/ directly),
  `sketch_ipa.py`. See [bo-ipa](/projects/bo-ipa.md).
- **prodtarget6d_talk** → `botorch_predict_prodtarget6d_cloud.py --current-box-only`
  (→ `*_t8only.png`) and `--acq` (→ `*_acq_cloud.png`) — both write the PLOTS dir,
  must `cp` into `docs/`; `pt6d07R01_07_geometry_sketch.png` (champion, static).
  GOTCHA: the two clouds are a slow botorch GP fit (~minutes each, sequential),
  and their n=… captions + the status `<small>` block are HAND-edited (count the
  t-upper>7 rows for the t8only caption). marp render needs CHROME_PATH +
  npm_config_cache=/tmp/oksuzian_npm_cache (see [marp-pdf-rendering](/concepts/marp-pdf-rendering.md)).

## Current deck image → generator map (2026-06-18) — the .sh is ORPHANED
`docs/foils_talk.md` now references **5 images, and `tools/refresh_foils_slides.sh`
generates NONE of them** — running the script alone does NOT refresh the live deck
(it copies/renders a stale image set: `gp_predicted_foils_cloud.{gif,png}`, botorch,
diversity, `saturation_bo_foils_v1_*` — all unreferenced). To refresh the real deck,
regenerate each image directly (all under `mmackenz_table_plots/`, run from
`.venv-botorch`):

| slide | deck image | generator | champion-dependent? |
|---|---|---|---|
| 4 | `gp_predicted_foils_honest_cloud.png` | `gp_predict_foils_v2v3_cloud.py --honest-only` | YES — filter regex `foilsf1[147]` (was `[14]`; add each new honest qnehvi prefix) |
| 7 | `foil_champion_<champ>_v3_sketch.png` | `sketch_foil_champions.py` | YES — `CHAMPS` list is HARDCODED; edit the dict (rIn=f·rOut per side) AND the slide-7 `![]` ref + bullets |
| 8 | `saturation_foils_v3all.png` | `saturation_report.py leaderboard_bo_foils_v3.tsv --out docs/saturation_foils_v3all.png` (no prefix = all v3) | grows with any new v3 rows |
| 9 | `saturation_foilsf09_10_qlnei.png` | `saturation_report.py` (frozen foilsf09/10 campaigns) | no — regen is byte-identical |
| 11 | `saturation_foilsg.png` | `saturation_foilsg.py` (writes `docs/` directly; hardcodes a stale "foilsf plateau=3.89") | grows with foilsg rows |

Then `cp` the cloud + sketch into `docs/` (saturation scripts write `docs/` directly)
and marp-re-render.

**TWO MORE slides carry NO image — hand-built HTML `<table>` + inline `<svg>`, no
generator, fully champion-stale (2026-06-18 trap):**
- **marp slide 5** "The result: best S/√B at a calo budget" — a 3-row calo-budget
  table (≤1e-6 / ≤1e-5 knee / unconstrained) with per-row end-on `<svg>` foil
  sketches, the "N honest-hole evals" count, and a "X% of max" line. Recompute
  by hand from the honest set (rows matching `foilsf1[147]`, calo>0): best sob
  within each calo cap + that row's geometry (rIn = f·rOut per side). **SVG scale
  = 0.12 px/mm** (viewBox `-35 -35 70 70`; the dashed red `r=9` circle = base
  rOut=75 mm reference, 9/75=0.12). So a circle/path radius = `rOut_mm * 0.12`;
  f=0 → solid `<circle>`, f>0 → annulus `<path fill-rule="evenodd">` with outer
  `rOut*0.12` and inner `rIn*0.12`. The `<span class="dim">` thickness label is
  the FULL thickness = `2*hT`.
- **marp slide 7** "Top 3 by S/√B" — hand-built top-3 `<table>` + a narrative
  bullet block.
Neither is touched by ANY script; both silently keep the prior champion. (marp
page numbering: frontmatter is NOT a slide, so deck slide N = the Nth `## ` after
frontmatter; matches the `foils_talk.html#N` anchor.)

**Champion change checklist (FULL):** (1) widen cloud regex `foilsf1[...]`,
(2) edit `sketch_foil_champions.py` `CHAMPS` + slide-6 `![]` ref + bullets,
(3) v3all auto-updates, (4) **hand-edit slide-5 calo-budget table + SVGs**,
(5) **hand-edit slide-7 top-3 table + narrative**, (6) the slide-8
**"VERDICT: SATURATED"** caption is hand-written prose, NOT auto-stamped — a new
champion (foilsf17 3.83→3.91) silently contradicts it. Steps 4-6 are the ones an
"images only" refresh misses.

**Older notes below are partially stale on image NAMES** (foilsZ/foilsY → current set
above) but correct on `saturation_report.py` mechanics + marp sizing.

## n_evals divergence (2026-06-17) — caption reads 251, GIF reads 323
Manual rerun 2026-06-17: `gp_predict_foils_cloud_anim.py` GIF final-frame caption = `n=323 foilsZ07R01` (loader pulls v1+v2+v3 via `load_history_all_v1_symmetric`, latest sweep up to foilsZ07), but `refresh_foils_talk_captions.py` stamps `n_evals=251` into `docs/foils_talk.md` because it reads only `leaderboard_bo_foils_v1.tsv` (per "Highlights templating" + "Caption refresh" bullets below — both are v1-only). Two different counters; the cron will publish a deck where the **image** says 323 and the **adjacent caption** says 251. Surface this before push. Fix path: either point captioner at the all-v3 leaderboard, or accept the v1-era 251 number as historical and drop the bullet that names it.

## v1-era pipeline NOT fully orphaned (2026-06-17 correction)
The earlier "entire `refresh_foils_slides.sh` pipeline is orphaned w.r.t. the live deck" claim (2026-06-04 bullet below) is **outdated**: a clean rerun on 2026-06-17 modified `docs/foils_talk.{html,md,pdf}` (caption stamp + marp re-render) and DELETED `docs/gp_predicted_foilsY_cloud.png` (no longer referenced). So the deck IS wired to the refresh script for at least the caption + HTML render — the orphan claim only applied to the v1-era image *copies* (GIF/PNG/BoTorch/diversity), which the script still recreates as untracked files but which no current slide references. Don't blanket-commit the recreated untracked PNGs; they'll re-orphan immediately.

**Updated (older):** 2026-06-06 (champion-sketch renderer extended for v3 — `mmackenz_table_plots/sketch_foil_champions.py` was a v1-era script keyed off single `extra_rOut/hT/rIn` triples + a GLOBAL `extra_rIn` hole. Extended 2026-06-06 to accept per-side keys (`extra_rOut_up/dn`, `extra_hT_up/dn`, `extra_rIn_up/dn`) with `.get()` fallback so v1 CHAMPS entries still render. When per-side keys present (`"extra_rOut_up" in cfg`), base hole is forced to 21.5 mm — v3 uses the patched `stoppingTarget.holeRadii` vector, so the extras' rIn does NOT propagate to the base (unlike v1's scalar override). Output: `foil_champion_<name>_sketch.png`. The v3 best-S/√B sketch (foilsf02R00_03) is now slide 6 of `docs/foils_talk.md`; don't hand-roll diagrams — extend this script with a new CHAMPS dict entry instead.)

## Summary
`tools/refresh_foils_slides.sh` rebuilds the `docs/foils_talk.*` artifacts
from the latest GP-cloud render so the GitHub Pages slide deck at
https://oksuzian.github.io/Mu2eBO/foils_talk.html stays in sync with the
animated GIF the 4-hourly cron posts to Slack. Safer split: this script
**does not commit or push** — operator reviews `git status docs/` then
pushes manually.

## Key facts
- **`saturation_report.py` regret panel now reads ΔHV per q-step (2026-06-07, final).**
  Replaced the obj/sob-based scalar regret with **dominated-HV-attained**
  binned by **leaderboard-order chunks of `Q=10`** (the BO batch size).
  Reason: (a) the picker is qLogNEHVI → HV is the actual objective;
  (b) parsed round labels (R00, R01, ...) are NOT unique across mixed-prefix
  leaderboards — foilsf01R03 and foilsf06R03 both parse as `R3` and silently
  collide in the `by_round = defaultdict(list)` grouping at line ~83.
  Chunking by leaderboard index sidesteps the collision and gives one bar
  per BO batch end-to-end. Y2 axis label = "dominated HV (black)"; bars =
  `ΔHV per round (red = saturated, k=2, ε=0.05)`. The text-summary print
  uses `:.4f` which truncates HV~6e-5 to 0.0001; the plot itself
  auto-scales (units 1e-5) and is correct.

- **`saturation_report.py` regret panel reads OBJ (legacy scalar), not sob (2026-06-07).**
  The bottom-right Δbest panel + black "round-best obj" line both consume
  column 11 `obj = sob − α·calo` with α=1e5 (the [scalarized-objective](/concepts/scalarized-objective.md) from
  the v1/skopt era — stamped on every leaderboard row at harvest time). The
  v3 picker is qLogNEHVI on the 2D Pareto front `(sob, −log calo)` and
  **does NOT use `obj`**. Consequence: the regret-panel y2 scale (~1.7-2.0)
  does not match slide 5/7 sob values (3.88-3.89) — they're plotting
  different objectives. The saturation VERDICT itself is still valid as a
  Δbest signal, just measured against obj-scalar rather than 2D-HV. To
  realign with the deck, point `best_scalar_regret` at column 8 (sob)
  instead of column 11 (obj). Same applies if a future picker switches
  objective; the report doesn't track which scalarization is current.

- **`saturation_report.py` 4-panel layout is now 2x2 LANDSCAPE (2026-06-07).**
  Previously always `(n_panels, 1)` vertical stack → 1400×1792 portrait
  (h/w=1.28). Patched at line ~158: when `len(panel_keys)==4` (the default
  `hv,pf,hitrate,regret`), switch to `plt.subplots(2, 2, figsize=(14, 8))` →
  **1960×1120 landscape (h/w=0.57)**. Same 4 metrics, just gridded. The 1xN
  stacked path is preserved for `--panels hitrate,regret` slim variant.
  Deck-friendly sizing on a 16:9 slide: **`![h:480px]`** with a ONE-LINE
  verdict at `font-size: 18px` fits above the page footer; multi-line verdicts
  clip even at h:460. The earlier 2x2-of-portrait-PNGs hack (h:200px / 11px
  captions / 4 separate prefix renders) is OBSOLETE; one landscape regen now
  does the same job.

- **Saturation 4-panel PNG is PORTRAIT (2026-06-03):** `saturation_report.py`
  writes `saturation_<prefix>.png` at **1400×1792 (h/w=1.28, taller than
  wide)**, so embedding it `![w:..%]` in the deck's 60/40 side-by-side grid
  overflows the 16:9 slide vertically. Fix: cap the HEIGHT —
  `![h:520px](...)` (Marp 16:9 = 1280×720px; ~580px usable after the h2 title
  + footer). This is why the v1 deck used the separate landscape
  `saturation_bo_foils_v1_{slim,hv,pf}.png` panels instead of the full
  4-panel PNG. Image+bullets slides also need `font-size: 18px` (or 17px) in
  the grid `<div>` to fit, matching slides 14–16.
  - **Denser two-column RESULTS slides need 16px, not 18px (2026-06-04, from
    the v3 result slide).** When the right column carries the full saturation
    plot on the LEFT *and* a multi-bullet text column on the RIGHT (≥4 bullets +
    verdict + a footer line), `font-size: 18px` overflows the *text* column —
    the last paragraph renders under the page-footer and clips. `16px` +
    `h:520px` (plot) fits a 58/42 grid. Verify by exporting PNGs
    (`marp … --images png -o /tmp/s.png`) and Read-ing the last slide; the h2
    title + footer eat enough vertical space that eyeballing the markdown is
    NOT reliable. The portrait plot itself fits fine at h:520–540; the binding
    constraint is always the text column, not the image.
- Inputs (read-only):
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predicted_foils_cloud.{gif,png}`
- Outputs (written into `docs/`):
  `gp_predicted_foils_cloud.gif`, optional `.png`,
  `foils_talk.html` (re-rendered from `foils_talk.md`).
- **Image-copy gap (resolved 2026-05-31):** the script now also copies
  `botorch_predicted_foils_cloud.png` and `diversity_overlay_foils.png`
  from `mmackenz_table_plots/` into `docs/` (WARN-but-continue if either
  source is missing). Previously these were hand-cp'd, which let them
  decay independently of the GP cloud.
- Renderer: `npx -y @marp-team/marp-cli@latest --html --allow-local-files`.
  Confirmed working with v4.4.0; no system `marp` binary required.
  `--allow-local-files` lets the GIF be inlined as data-URI.
- Cron `d3cf6d4b` (session-only, 7-day expiry): runs at `:22 */4 * * *`,
  9 min after the existing GIF-render cron `41e49197` (`:13`) finishes
  writing the new GIF — ordering is load-bearing.
- The script does **not** touch the slide content (`foils_talk.md`)
  itself; if md needs updating, that's a manual edit. Memory rule
  "do NOT modify slide deck" applies to `slides/slides.tex` (LaTeX);
  `docs/foils_talk.md` is editable when asked.
- **Deck split to CONCISE + archive (2026-06-04).** `docs/foils_talk.md` is now
  an **8-slide concise v3/qLogNEHVI deck** (latest-version-only: v3 fractional
  geometry, cl_min-vs-qNEHVI/qLogNEHVI, foilsZ01/Z02 results, scoreboard). The
  prior **26-slide comprehensive deck** (v1→v2→v3 full history) is archived
  verbatim at **`docs/foils_talk_full.md`** (not rendered, not published; restore
  via `cp`/`git`). Consequence for THIS script + cron: the concise deck **dropped
  the `<!-- highlights:* -->` / `<!-- botorch-cross-check:* -->` /
  `<!-- run-timeline:* -->` marker regions**, so `stamp_foils_highlights.py` and
  `refresh_foils_talk_captions.py` now **warn-but-skip** (idempotent, "no
  markers" → no-op) — expected, not a failure. **Broader: the concise deck
  references NONE of the artifacts this cron maintains** — it uses
  `saturation_foilsZ.png`, `saturation_foilsZ02.png`, `gp_predicted_foilsY_cloud.png`
  (all hand-maintained), while the cron refreshes the v1 GIF/PNG, BoTorch +
  diversity overlays, and v1 saturation panels. So the **entire
  `refresh_foils_slides.sh` pipeline is orphaned** w.r.t. the live deck:
  re-establishing the cron would copy/re-render v1-era inputs the deck no longer
  shows. (Cron `d3cf6d4b` was session-only/7-day and is **not currently
  scheduled** — `CronList` empty 2026-06-04.) Treat the v1 stamp/refresh
  machinery as **retired** unless the concise deck is re-wired to the v3
  leaderboard with fresh markers; the `.py` scripts still match
  `foils_talk_full.md` if that deck is ever restored.
- **GP cloud is produced by `gp_predict_foils_v2v3_cloud.py` (2026-06-05).**
  The deck's `docs/gp_predicted_foilsY_cloud.png` is literally a `cp` of
  `mmackenz_table_plots/gp_predicted_foils_v2v3_cloud.png` (md5-verified
  identical). The historical "foilsY" suffix is a misnomer — this is the
  v2+v3 6D cloud, not a foilsY-only render. To refresh the deck cloud:
  `.venv-botorch/bin/python gp_predict_foils_v2v3_cloud.py` (run from
  `mmackenz_table_plots/`), then `cp` the output into `docs/`. The
  v3 leaderboard now feeds into the loader via `load_history(include_v3=True)`
  at `gp_predict_foils_v2v3_cloud.py:56`.
- **v3-only mode (2026-06-05):** same script accepts `--v3-only` to retrain
  the GP on the v3 (foilsZ) leaderboard alone (drops v1 n=6/6 projection +
  v2). Writes to a SEPARATE output `gp_predicted_foils_v3only_cloud.png` so
  the deck/cron consumer (`gp_predicted_foils_v2v3_cloud.png`) is untouched.
  Useful as a sanity check that v3 exploration carries the front without v2
  priors — the two clouds' sob ranges match within ~1% (v2v3: [0.62, 3.84];
  v3-only on 67 evals: [0.63, 3.88]).
- **Saturation plot prefix conventions (2026-06-05; nuance 2026-06-07).** The deck's
  `saturation_foilsZ.png` is `saturation_report.py --prefix foilsZ` — it
  captures **all foilsZ* rounds (foilsZ01–Z06 currently)**, but **does NOT
  include foilsf* campaigns** (foilsf01/02/03/06). The prefix match is
  literal-substring `startswith`; `foilsf06` doesn't start with `foilsZ`.
  Consequence: when only foilsf* rounds land between deck refreshes, the
  `saturation_foilsZ*.png` PNGs regen byte-identical (deterministic on the
  same filtered subset) → `git status` shows no diff → operator may
  incorrectly conclude "saturation is current". Slide 8 "Convergence" then
  silently lags reality. To include foilsf* in the convergence story, add a
  third panel `--prefix foilsf` or switch the deck to a no-prefix all-v3
  panel. The deck's `saturation_foilsZ02.png` is `--prefix foilsZ02` — only
  the foilsZ02 campaign. Both write into `docs/` directly via `--out docs/...`.
  `saturation_report.py` lives off-repo at
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/saturation_report.py`
  (NOT in `tools/`), and is run from `.venv-botorch`. **The leaderboard
  is a POSITIONAL argument, not a flag** — call
  `saturation_report.py <leaderboard_path> --prefix foilsZ --out docs/saturation_foilsZ.png`.
  Forgetting the positional yields argparse error
  `the following arguments are required: leaderboard`.
- **v1-era deck assets PRUNED (2026-06-04).** To minimize the maintenance
  surface, `docs/` was cut to the 5 files the concise deck needs
  (`foils_talk.{md,html}` + `saturation_foilsZ.png`, `saturation_foilsZ02.png`,
  `gp_predicted_foilsY_cloud.png`). **Deleted (13, recoverable from git):**
  `foils_talk_full.md` (the comprehensive-deck archive — full content also at
  `git@379f56a:docs/foils_talk.md`) + 12 v1-era images
  (`gp_predicted_foils_cloud.{gif,png}`, `botorch_predicted_foils_cloud.png`,
  `diversity_overlay_foils.png`, `saturation_bo_foils_v1{,_slim,_hv,_pf,_progress}.png`,
  `saturation_foilsY.png`, `foil_champion_foilsX0{7,8}*_sketch.png`). So the
  image names this page (and `refresh_foils_slides.sh`) still reference **no
  longer exist on disk** — `refresh_foils_slides.sh` would re-create the ones it
  generates if ever re-run, but the champion sketches + foilsY saturation are
  gone unless restored from git. The 3 refresh scripts (`.sh` + 2 `.py`) were
  KEPT (re-wireable to v3).
- **Highlights templating (added 2026-05-30):** before marp re-render,
  `tools/stamp_foils_highlights.py` rewrites the block between
  `<!-- highlights:start -->` / `<!-- highlights:end -->` markers in
  `docs/foils_talk.md:137-141` (slide 9 caption) from
  `leaderboard_bo_foils_v1.tsv`. Stamps `n_evals`, best `obj`/`sob`/`calo`,
  calo floor, modal `n_down` + mean `rOut` over top-5. Idempotent
  (re-run on unchanged leaderboard prints `[stamp] no change`). Prose
  outside the markers is preserved; if you remove the markers the
  caption stops auto-updating.
- **Stamp bug (fixed 2026-05-31):** the first highlights bullet was
  hardcoded `"frontier still expanding (not saturated)"` and contradicted
  the deck's own slide 14 SAT verdict. Now `stamp_foils_highlights.py`
  shells out to `saturation_report.py --prefix foilsX`, parses its
  VERDICT line, and emits `"frontier saturated"` / `"frontier still
  expanding"` / `"frontier status unknown"` (fallback if the script
  can't run). 60 s timeout.
- **Caption refresh (added 2026-05-31):** `tools/refresh_foils_talk_captions.py`
  rewrites three more leaderboard-derived regions before marp:
  `<!-- botorch-cross-check:start/end -->` (n + sob_max + calo_min),
  `<!-- run-timeline:start/end -->` (total + per-prefix breakdown),
  and the YAML `footer:` line by line-regex (HTML comments aren't
  legal inside YAML frontmatter). Idempotent — prints `[caps] no change`
  if leaderboard unchanged. The four marker regions and the footer
  line are owned by this pair of scripts; do not hand-edit the regions
  themselves, edit prose outside the markers.
- **Full-deck refresh skill (added 2026-05-31):** the `/refresh-foils-talk`
  skill at `.claude/skills/refresh-foils-talk/SKILL.md` is the heavier
  cousin: it renders all four plots (GP cloud, BoTorch, diversity overlay)
  in `.venv-botorch` *before* calling this shell script. Diversity overlay
  is the bottleneck (~90 min); pass `--skip-overlay` for a fast refresh.

## Cross-links
- Related: [gp-cloud-rendering](/concepts/gp-cloud-rendering.md) (what produces the input GIF)
- Related: [github-pages-publish-dir](/external/github-pages-publish-dir.md) (why `docs/` is the publish dir)
- Related: [slack-file-upload-flow](/external/slack-file-upload-flow.md) (sibling Slack cron `41e49197`)
- Source files: `tools/refresh_foils_slides.sh`,
  `tools/stamp_foils_highlights.py`, `tools/refresh_foils_talk_captions.py`,
  `.claude/skills/refresh-foils-talk/SKILL.md`

## Open questions / TODO
- Decide whether `docs/saturation_bo_foils_v1*.png` (untracked legacy
  outputs) should be committed or `.gitignore`'d so the cron's
  `git status docs/` report stays clean.
- Mirror an analogous script for the helical talk if/when a helical
  cron is added.
