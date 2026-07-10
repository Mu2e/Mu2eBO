# qlnei — sob-only BO picker

**Type:** concept
**Status:** active
**Updated:** 2026-07-07

> **2026-07-07 — qlnei on foilsflash measures BOTH objectives.** The
> AUTORESEARCH_NO_RUN1B stamp only drops `run1b_mubeam`, which the
> foilsflash chain doesn't have (mubeam→concat→mustops_ce→elebeam_flash),
> so under `--picker qlnei --mode foilsflash` the acquisition is sob-only
> but every row still lands with a real flash measurement — no degraded
> rows (unlike the foils qlnei era's calo=0 rows,
> [[foils-cloud-calo-zero-inf]]). Also note the stamp's stage-drop saves
> no wall-clock for foilsflash. Relevant if the unexplored foilsflash sob
> corner (best 3.77 vs foils' 3.91, see [[bo-foilsflash]]) is ever pushed.

> **2026-06-13 — qNEHVI now TIMES OUT on foilsf; use qlnei.** Before the
> holeRadii fix, calo had near-zero variance (holes were inert → calo
> pinned), so the (sob, −calo) Pareto front was nearly degenerate and
> qNEHVI's hypervolume box-decomposition was cheap. Post-fix, real holes
> give calo genuine ~17× spread ([[bo-foils]]), the non-dominated front
> is large, and `botorch_predict.py --picker qnehvi` blows past the
> 3600 s subprocess cap in `closed_loop.py:_qnehvi_picks_subprocess`
> (`TimeoutExpired` → parent SystemExit in `node_predict_picks`, BEFORE
> any child launches, so no orphans). foilsf12 hit this at history=366
> (foilsf11 ran fine at 346 — the 20 real-hole rows are what tipped it).
> qNEHVI HVI cost is superlinear in front size. **Resolution: foilsf is
> now a qlnei (sob-only) line** — the calo trade-off is characterized
> (holes hurt; solid foils optimal), so the remaining question is pure
> max-sob and the multi-objective channel is no longer needed. If a
> future qnehvi front-map is wanted, raise the `timeout=3600` in
> `_qnehvi_picks_subprocess` and/or subsample the Pareto baseline.
>
> **2026-06-14**: timeout raised to **14400 s (4 h)** at
> `graph/closed_loop.py:326` to support **foilsf14** qnehvi relaunch
> (q=10, max-rounds=2) — needed to regenerate slide-5 calo-budget table
> + slide-6 GP cloud from honest-hole calo data (the prior 297-eval
> cloud was fit on uniform-disc fallback rows). Pareto front at relaunch
> = 69 points (from 316 calo-bearing leaderboard rows); qNEHVI HVI
> box-decomp cost is ~cubic in front size, so 3600 s caps out near 50
> points. If front grows past ~120, expect to revisit.
>
> **2026-06-14 datapoint**: foilsf14 R0 picker (qnehvi, q=10,
> history_len_before=386, all 386 with calo>0) **returned in ~14 min**
> (~840 s wall, ~280% CPU on .venv-botorch python) with stock knobs
> (`num_restarts=16 raw_samples=512 MC_SAMPLES=128` in
> `botorch_predict.py:_qnehvi_picks` lines 253/267-268). So 3600 s
> ceiling held at n=386 with a fully non-degenerate front — the
> foilsf12 timeout at n=366 was already on the verge. Speed-up
> levers if needed at n>~500: (1) subsample X_baseline to front +
> ~50 dominated points (Daulton 2021 §5.2), (2) drop MC samples
> 128→64, (3) `num_restarts=8 raw_samples=256`.

## Summary
Alternative closed-loop picker that drops the multi-objective Pareto-HV machinery (`qLogNEHVI`) and acquires q proposals against a single scalar — `s_over_sqrt_b` only. Wired up 2026-06-08 after foilsf01/02/03/06/07 all saturated the 2D (sob, −calo/POT) front at sob≈3.88-3.89; if the calo channel is no longer informative, dropping it both halves the model complexity AND lets us drop the DS-field-off `run1b_mubeam` grid stage (≈40% wall-clock saving per point). See [[bo-foils]] saturation history.

## Key facts
- Selected via `python -m graph.closed_loop --picker qlnei` (`PICKER_CHOICES = ("cl_min", "qnehvi", "qlnei")` in `graph/closed_loop.py`).
- Picker dispatcher lives in `botorch_predict.py:compute_explore_picks(picker=...)`:
  - `qnehvi` → multi-objective `qLogNoisyExpectedHypervolumeImprovement` over (sob, −calo/POT)
  - `qlnei` → single-objective `qLogNoisyExpectedImprovement` over sob only
- `_load_history_tensor(mode, sob_only=False)`: when `sob_only=True`, drops rows where `p.sob` is None/NaN and emits a 1D Y tensor `[[sob]]` (vs 2D `[[sob, −calo]]`).
- `_qlnei_picks(model, X, bounds, q, round_idx)`: builds `qLogNoisyExpectedImprovement(model, X_baseline=X)`, optimizes via `optimize_acqf` with same Sobol seed convention as qnehvi (`seed = 42 ^ round_idx` — see [[botorch-predict-seed-pow-vs-xor]]).
- **Stage dispatch coupling** — closed_loop.py:`_presniff_picker()` stamps `AUTORESEARCH_NO_RUN1B=1` into `os.environ` BEFORE importing `graph.config`. config.py then conditionally drops `run1b_mubeam` from `GRID_STAGES` at module-import time:
  ```python
  if os.environ.get("AUTORESEARCH_NO_RUN1B") == "1":
      GRID_STAGES = [s for s in GRID_STAGES if s != "run1b_mubeam"]
  ```
  Load-order matters — same pattern as `AUTORESEARCH_MODE` for mode-keyed `MUSING` and `GRID_STAGES` selection.
- Harvest still runs the per-mode `harvest` verb (`cmd_harvest`), but `calo_per_pot` will be NaN/None for qlnei-picked rows because run1b_mubeam never produced its DS-field-off output. That is *intentional* — the picker doesn't read calo, and the leaderboard already tolerates missing calo via `p.calo is None`.
- Smoke test 2026-06-08: `PYTHONPATH= .venv-botorch/bin/python botorch_predict.py --mode foilsf --picker qlnei --q 5` returned 5 picks at rO≈90-111, hT_up≈0.057-0.062 — clustered tight near the saturation geometry as expected (no calo-vs-sob tension to spread the front).
- 70/70 unittests pass with the wiring change.
- **Wall-clock cost of pick computation**: foilsf08R00 (first live run, q=10, history=296) `qLogNoisyExpectedImprovement` `optimize_acqf` took ~6 min vs qnehvi's typical ~1-2 min on the same history size. The single-objective acquisition's noisy-EI fantasies + raw_samples optimize is heavier than qnehvi's 2D HVI scalar — closed-loop barrier-poll cadence (5min default) is fine, but don't expect "faster picker = faster round-0."
- **Tooling gotcha: qlnei rows land with `calo = 0.0`, NOT `None`** (e.g. foilsg02 leaderboard rows all show calo=`0.00000e+00`). The harvest path writes `0` rather than NaN/empty when `run1b_mubeam` is skipped. Consumers that filter `calo > 0` or `calo <= 0` will silently drop every qlnei row:
  - `saturation_report.py:48` (`if calo <= 0 or sob <= 0: continue`) — a qlnei-only leaderboard appears empty; report prints "n/a" verdict on rows that survive (e.g. foilsg01 Sobol-init rows only). Workaround for inspection: edit local copy to allow `calo == 0`, or filter on `obj` instead.
  - `botorch_predict._load_history_tensor` (non-`sob_only` path) drops `calo <= 0` at line 161 — but qlnei callers always pass `sob_only=True`, so this is dormant. The trap is for any *other* picker that tries to ingest a mixed qlnei+qnehvi history later.


## Cross-links
- Related: [[bo-foils]], [[scalarized-objective]], [[bo-noise-budget]], [[batch-bo]], [[closed-loop-bo-design]], [[botorch-predict-seed-pow-vs-xor]]
- Source files: `botorch_predict.py:_qlnei_picks`, `botorch_predict.py:_load_history_tensor`, `graph/closed_loop.py:_presniff_picker`, `graph/closed_loop.py:_qnehvi_picks_subprocess`, `graph/config.py:55-56` (AUTORESEARCH_NO_RUN1B gate)
- Driver: [[closed-loop-runner]]

## Open questions / TODO
- Has not been exercised end-to-end on the grid yet — foilsf08R00 would be the first real test.
- Open question: does dropping calo from the GP destabilize the surrogate near the boundary, or is the sob-only model just smoother (no Pareto kink)?  Worth one rounds-comparison once foilsf08 has data.
- If qlnei breaks the sob ceiling, document in [[bo-foils]] log; if not, document why saturation is genuine (see also [[gp-cloud-rendering]]).
