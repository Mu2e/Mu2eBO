---
type: driver
title: bo_driver.py — driver
description: '`propose | evaluate | preflight` (6 modes; michael/helical retired
  2026-07-12, ipa 2026-07-18; all BO asks via botorch_ask since 2026-07-18)'
status: active
timestamp: '2026-07-19'
updated_note: 'fixed recorded drift: KNOB_NAMES/KNOB_FMTS/CALO_COL are registry
  properties (modes.SPECS) not driver-owned data; preflight/evaluate carry
  --emit-json; build_space lockstep guard now lives in ModeSpec.__post_init__'
---

# bo_driver.py — driver

## Summary
The multi-mode BO driver (all 7 live modes — foils/foilsf/foilsflash/foilsg/
ipa/prodtarget/prodtarget6d). Implements the BO loop as subcommands, each
independently runnable. Born 2026-04 as the dedicated driver for
[bo-michael](/projects/bo-michael.md) (hence its original name
`autoresearch_bo_michael.py`); renamed to `core/bo_driver.py` on 2026-07-17
after the michael mode was retired (2026-07-12).

## Key facts
- **Path:** `core/bo_driver.py` (renamed 2026-07-17 from
  `autoresearch_bo_michael.py`; git history is under the old name pre-rename)
- **Live-verb map (2026-07-12 survey):** only `preflight` and `evaluate` have
  code callers (both subprocess calls from `graph/pipeline_io.py`). `propose`
  has zero code callers but is the documented operator-recovery verb
  (pipeline.py prints it as the recovery hint); `show-priors` and
  `list-pending` have zero callers anywhere. **The skopt kernel was RETIRED
  2026-07-18** (`build_optimizer`/`seed_optimizer`/`ask_buildable`/
  `N_INITIAL_POINTS` deleted; scikit-optimize+scipy dropped from
  requirements-graph): every BO ask — CLI `propose`, `graph/pipeline_io.
  propose_one` (standalone `graph.run` without `--x-point`), and the
  closed-loop picker — now goes through **`bo_driver.botorch_ask()`**, a
  subprocess seam into the botorch venv running `botorch_predict.py`
  (venv resolved from `$AUTORESEARCH_BOTORCH_VENV`, default
  `.venv-botorch`). Pending points ride as X_pending fantasies (replacing
  skopt constant-liar); propose retries bump `seed_idx` (= picker
  `--round-idx`, seed 42^idx) so preflight-driven re-proposes draw fresh
  points.
- **Subcommands:**
  - `show-priors --top K` — print top-K mmackenz priors by current α (no GP fit)
  - `propose <config_name>` — botorch ask (qNEHVI default) via
    `botorch_ask()`, render `bo_work/proposals/<mode>/<config_name>_geom.txt`
  - `evaluate <config_name> <summary.json>` — record completed run in
    `leaderboards/leaderboard_bo_<mode>.tsv` (see [leaderboards](/datasets/leaderboards.md))
  - `preflight <config_name>` — see [preflight](/drivers/preflight.md)
- **α flag:** `--alpha 1e5` default ([scalarized-objective](/concepts/scalarized-objective.md))
- **Search space:** see [bo-michael](/projects/bo-michael.md) / [bo-helical](/projects/bo-helical.md) (per mode)
- **Architecture:** `BOMode(ABC)` with 6 adapters (michael + helical retired
  2026-07-12; the file keeps its historical name). Each subclass owns its
  pinned constants + 4 abstract methods (`load_priors`, `_geom_text`,
  `parse_geom`, `format_row`/`load_history_row` — the last two are also
  concrete-shared for the Foils family, see below). Shared concerns (history
  I/O, pending TSV, proposal write) are concrete on the base. `MODES` is
  the registry argparse selects from.
- **`KNOB_NAMES`/`KNOB_FMTS`/`CALO_COL` are registry-reading PROPERTIES, not
  driver-owned data (since `bd37aa3`, 2026-07-19 — fixes a wiki drift a prior
  round flagged and skipped).** `BOMode.KNOB_NAMES`/`.KNOB_FMTS` read
  `modes.SPECS[self.name].knob_names`/`.knob_fmts`; `.CALO_COL` reads
  `modes.SPECS[self.name].metric_cols[1]` (Foils-family second-objective
  column, `calo` vs `flash_edep`). The driver no longer stores these as
  per-subclass class attrs — `core/modes.py` is the single source, and
  `BOMode.format_row` additionally hard-guards `len(metric_cols) == 4` (a
  future non-sob/calo/alpha/obj mode must override `format_row`, per the
  `ProdTargetMode` pattern, instead of silently mis-writing the header).
- **`build_space` is data-driven (2026-07-12; skopt-free since 2026-07-18):**
  one concrete base method reads `modes.SPECS[name].bounds_lo/hi/int_dims`
  + the `KNOB_NAMES` property (above) → plain `SpaceDim(name, low, high,
  is_int)` rows. The `KNOB_NAMES`/bounds lockstep check used to live IN
  `build_space` (a `ValueError` raise); it is now DEAD CODE there by
  construction (`ModeSpec.__post_init__` already enforces
  `knob_names`/`knob_fmts`/`bounds_lo` lockstep whenever `bounds_lo is not
  None`, raising `ValueError` — was a bare `assert`, strippable under
  `python -O`, hardened to `raise` 2026-07-19) — deleted from `build_space`,
  replaced with a pointer comment. Lockstep is pinned by
  `test_modes.TestBoundsLockstep`. **Watch-note:** the `__post_init__` guard
  is gated on `bounds_lo is not None`, so a future `bounds_lo=None` mode
  (michael's now-retired Categorical pattern) would silently skip lockstep
  validation.
  The Foils family (`foils`/`foilsf`/`foilsflash`) also shares one concrete
  `format_row`/`load_history_row` on `FoilsMode`, parameterized by `KNOB_NAMES`
  + `KNOB_FMTS` (per-position precision) + `CALO_COL` (`calo` vs `flash_edep`).
- **`preflight`/`evaluate` cross the graph↔driver seam as typed JSON
  (2026-07-19, `d07d668`/`6b81a17`): both verbs carry `--emit-json <path>`**
  (`cmd_preflight`/`cmd_evaluate`, argparse at `core/bo_driver.py:1760,1767`).
  When passed, the verb writes `state/<cfg>/{preflight_verdict,
  evaluate_result}.json` atomically (tmp+rename) alongside its normal
  stdout/exit-code behavior; `graph/pipeline_io.py` (`run_preflight`/
  `run_evaluate`) reads the JSON as the primary signal, with the exit code
  as a transport-failure-only backstop. See
  [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md)
  candidate 4.
- **Deleted 2026-07-12:** `show-priors` verb + all `print_top` display methods
  (zero callers); the `--strategy` cl_min/mean/max flag (ADR-0001); `F_MAX`/
  `HT_FLOOR` class attrs (their 0.95/0.002 caps live in `modes.SPECS`).
- **Summary-extraction seam (2026-06-07 for [bo-prodtarget](/projects/bo-prodtarget.md)):**
  `BOMode.extract_metrics(summary) -> (sob, calo)` with default that reads
  the 4-stage harvest schema (`s_over_sqrt_b`, `calo_per_pot`). Override
  only in modes whose pipeline writes a different schema —
  `ProdTargetMode.extract_metrics` returns `(summary["mu_per_POT"], 0.0)`.
  `cmd_evaluate` calls the seam and exits 1 on `KeyError`/`TypeError` (was
  hardcoded `summary.get("s_over_sqrt_b") / summary.get("calo_per_pot")`).
  Default-on-base pattern keeps the 4 legacy modes unchanged with no
  boilerplate — deviates from issue #14's "explicit impl in every mode"
  spec.
- **Adding a closed-loop-capable mode touches 7 places — 8 if you ever run it
  with `--picker qnehvi` (checklist, 2026-06-03 from `foilsf`/v3; item 8 added
  2026-06-04):** "subclass + register" is NOT enough — a propose-only
  mode is, but a closed-loop one also needs the graph + picker wiring:
  1. subclass (e.g. `FoilsFracMode(FoilsMode)` — reuse via `super()`) +
     `MODES["<name>"] = ...` in `bo_driver.py`;
  2. the **3 surface-check gates** `if mode.name in ("helical","foils",…)` in
     `cmd_preflight` (~`:1048,:1114,:1148`) — MISS these and preflight skips
     managed-overlap detection for the mode;
  3. `graph/state.py` mode `Literal`;
  4. `graph/closed_loop.py:_import_gp` `elif mode=="<name>": import
     gp_predict_<name>`;
  5. `graph/closed_loop.py` `--mode` argparse `choices=[…]` (graph/run.py has
     NO choices restriction, so children are fine);
  6. `graph/closed_loop.py:_DRY_RUN_KNOB_LABELS` (optional — falls back to
     `x{i}`, no crash);
  7. the off-repo picker shim `gp_predict_<name>.py` in
     [mmackenz-table-plots-dir](/external/mmackenz-table-plots-dir.md) (binds `MODES["<name>"]`, delegates to
     `build_space` so it auto-tracks the dims).
  8. **qnehvi ONLY:** add the mode to `botorch_predict.py`'s **inlined
     `MODE_SPECS` dict** (`botorch_predict.py:62`) — `{lo,hi,int_dims}` lists.
     This is a SECOND, hand-maintained copy of the bounds, deliberately
     duplicated so `.venv-botorch` (no skopt) needn't import `build_space`;
     order MUST match `build_space`. Items 1–7 (the cl_min/skopt path) are NOT
     enough for qnehvi: `--picker qnehvi` shells into `.venv-botorch` to run
     `botorch_predict.py --mode <name>`, which `raise SystemExit`s at
     `botorch_predict.py:85` "mode not supported" if the mode is absent from
     `MODE_SPECS`. Caught 2026-06-04 launching `foilsZ02` (foilsf+qnehvi) —
     `foilsf` was in `bo.MODES` and all 7 cl_min places but missing here, so
     qnehvi would have died on arrival every round. `foilsf` spec = `foils`
     spec with the last two dims `f∈[0,0.95]` instead of `rIn∈[0,50]`.
- **Render template:** each mode's `_geom_text(x)` returns a FHiCL string;
  base-class `render_proposal(name, x)` writes it to `proposal_dir/`.
- **`foilsf` reuses the `foils` dirs.** `FoilsFracMode` subclasses
  `FoilsMode` and does NOT override `preflight_dir`/`proposal_dir`/
  `leaderboard` — so foilsf preflight logs land in
  **`bo_work/preflight/foils/`** and proposals in `bo_work/proposals/foils/`
  (there is no `foilsf` dir). The leaderboard IS separate
  (`leaderboards/leaderboard_bo_foils_v3.tsv`, overridden). `foilsg` does
  override all three → `bo_work/preflight/foilsg/`,
  `bo_work/proposals/foilsg/`, `leaderboards/leaderboard_bo_foilsg.tsv`.
  When hunting a foilsf<NN> log, look under `bo_work/preflight/foils/`,
  not a foilsf-named dir. (2026-07-17 reorg: the flat `bo_<mode>_{proposals,
  preflight}/` dirs collapsed into `bo_work/{proposals,preflight}/<mode>/`;
  driver + TSVs now live in `core/` + `leaderboards/`.)

## Cross-links
- Projects: [bo-michael](/projects/bo-michael.md), [bo-helical](/projects/bo-helical.md), [bo-foils](/projects/bo-foils.md) (modes registered in `MODES`)
- Predecessor driver: [autoresearch-bo](/drivers/autoresearch-bo.md)
- Priors: [mmackenz-priors](/datasets/mmackenz-priors.md)
- Helper: [preflight](/drivers/preflight.md)
- Consumed by: [pipeline](/drivers/pipeline.md), [graph-runner](/drivers/graph-runner.md), [closed-loop-runner](/drivers/closed-loop-runner.md)
- Regression tests: [tests](/drivers/tests.md)
- Known render bug: [geom-run1a-vs-run1b](/incidents/geom-run1a-vs-run1b.md)
