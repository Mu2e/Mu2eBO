---
type: incident
title: autoresearch_bo_michael.py propose dies on prodtarget mode (no priors)
description: ProdTargetMode propose dies in skopt with "Random evaluations exhausted
  and no model has been fit" because n_initial_points=0 + zero priors leaves Optimizer
  with nothing to do
status: resolved
status_note: '2026-06-07'
timestamp: '2026-06-07'
updated_note: fix landed — N_INITIAL_POINTS class-attr seam
---

# autoresearch_bo_michael.py propose dies on prodtarget mode (no priors)

## Summary
First-time `--mode prodtarget propose pt001` raises
`RuntimeError: Random evaluations exhausted and no model has been fit`
inside `skopt.optimizer.Optimizer._ask` (skopt/optimizer/optimizer.py:490).
Existing modes (michael/helical/foils) don't hit this because they load
dozens of prior points from `mmackenz/geom_params.tsv` at startup, which
seeds the GP enough to skip the Sobol-init phase. bo-prodtarget has no
free priors and the existing modes use `n_initial_points=0` — so when the
prior set is empty AND `n_initial_points=0`, skopt has nothing to fit and
nothing random to draw, hence the error.

## Key facts
- Error trace:
  ```
  File ".../autoresearch_bo_michael.py:269 ask_buildable"
    xs = [opt.ask()] if q == 1 else opt.ask(n_points=q, strategy=strategy)
  File ".venv-graph/.../skopt/optimizer/optimizer.py:490 _ask"
    raise RuntimeError("Random evaluations exhausted and no model has been fit.")
  ```
- Confirmed: `prodtarget propose` startup logs
  `[prodtarget] seeding GP: 0 priors + 0 history + 0 pending (in-flight)`
  immediately before the crash — empty all the way down.
- The wiki [bo-prodtarget](/projects/bo-prodtarget.md) "Cold-start decision" section explicitly
  argued to **skip Sobol seeding** based on a precedent analogy with
  other modes; this is the operational cost of that choice (the other
  modes have priors, prodtarget doesn't, so the analogy doesn't hold).
- The M1 forker itself works — `_geom_text(x)` renders a valid Stickman
  geom for any in-bounds x. The bug is only in the BO `ask()` loop.

## Workaround (used to unblock issue #12 dry-run, 2026-06-07)
Hand-render the geom file via the forker, bypassing `propose`:
```python
from autoresearch_bo_michael import MODES
mode = MODES["prodtarget"]
x = (3.15, 3.15, 3.15, 5.0, 5.0, 5.0, 6.0, 6.0, 6.0, 35)  # defaults
geom_text = mode._geom_text(x)
Path(f"<data_root>/<cfg>/geom/autoresearch_<cfg>_geom.txt").write_text(geom_text)
```
Sufficient for testing the downstream pipeline; not a fix for batch
propose.

## Skopt mechanic: penalty `tell()` consumes init-budget (2026-06-07)
**Non-obvious gotcha** uncovered during fix-option evaluation: when
`Optimizer(n_initial_points=K)` is configured, *every* `opt.tell(x, y)`
decrements the K budget — including the *penalty tells* that
`ask_buildable` (`autoresearch_bo_michael.py:268-279`) makes when a
proposed config fails engineering constraints (e.g. `min(rOut)<3`).

Implication: setting K=q for the cold-start fix is **fragile**. With
q=2 and any rejection-retry during round 0, the Sobol budget can
empty mid-loop and the same `RuntimeError` re-fires. Safe minimum is
`K >= PROPOSE_MAX_RETRY * q`, which for `PROPOSE_MAX_RETRY=20` (current
value) means K>=40 — obliterating the "cheap cold-start" argument.

This is why **Option 1 (bump n_initial_points) is not a one-line fix.**
Documenting here so a future session doesn't re-derive.

## Resolution: `N_INITIAL_POINTS` class-attr seam (landed 2026-06-07)

`BOMode.N_INITIAL_POINTS: int = 0` class attribute, threaded into
`build_optimizer` as `n_initial_points=self.N_INITIAL_POINTS`.
`ProdTargetMode` overrides to `10`. This is skopt's idiomatic API —
the first 10 `ask()`s are Sobol-random, then the GP takes over.

The penalty-tell budget-drain concern (below) is largely theoretical at
K=10 with prodtarget's ~9% acceptance: a worst-case round burns ~10
penalty tells before the GP kicks in, which is exactly the budget.
Decision overruled the 3-agent grilling's Option-3 pick: the agents
optimized for surgical correctness; user preferred idiomatic skopt.

**Verified working 2026-06-07**: `propose pt002` returned Sobol draw
`(3.87, 3.35, 3.47, 7.83, 6.04, 4.38, 6.37, 5.32, 4.13, N=33)`, geom
rendered + staged, pending file written.

**Secondary bug uncovered + fixed in same commit**: skopt's
`Integer` dimension returns `np.int64`, which broke
`json.dumps(list(x))` at `append_pending` (autoresearch_bo_michael.py:312)
with `TypeError: Object of type int64 is not JSON serializable`.
Existing modes never hit this because their priors come from
TSV-parsed Python floats. Fixed via `v.item() if hasattr(v, "item")`
coercion at the JSON boundary.

## Historical: 3-agent fix-option evaluation (2026-06-07)

Captured the non-obvious rejection reasons for future reference:

1. **Bump `n_initial_points`** for prodtarget mode only: **REJECTED**.
   Penalty-tell budget drain (above) makes K=q fragile; safe K >=
   `PROPOSE_MAX_RETRY * q` = 40, which contradicts the wiki cold-start
   "Sobol is expensive" rationale in [bo-prodtarget](/projects/bo-prodtarget.md).

2. **Manual seed `Optimizer.tell(x_default, y=fake)`**: **REJECTED**.
   y-scaling hazard: prodtarget `obj = mu_per_POT` is O(1e-4), but other
   modes feed obj~O(1). Any picked fake y (0.0 or 1e-4) anchors the
   GP kernel's amplitude hyperparameter to a meaningless scale, which
   collapses EI in rounds 0-1 (the most expensive rounds). Skopt's
   `base_estimator="GP"` does NOT auto-normalize y. Single fake point
   in 11D would also need a `if not history: seed else: []` guard to
   avoid permanent re-injection on every propose call.

3. **Precheck `len(opt.Xi) == 0` → `opt.space.rvs(...)` fallback**:
   **PICKED**. Inside the existing `PROPOSE_MAX_RETRY` rejection loop,
   so engineering constraints still filter. Key facts:
   - `skopt.Space.rvs(n_samples, random_state)` works pre-fit (each
     `Dimension.rvs()` is `scipy.stats` sampling on its prior; no
     Optimizer state required).
   - `Optimizer._ask` raises ONLY when
     `_n_initial_points <= 0 AND len(self.models) == 0`. After the
     first real `opt.tell(x, real_y)`, `_fit_model()` runs and the
     models list is non-empty, so the error fires exactly ONCE per
     fresh Optimizer lifetime. One-shot cold start; no re-trigger
     mid-rounds.
   - **Prefer precheck form** over `try: opt.ask() except RuntimeError`.
     The bare except could shadow an unrelated GP-fit failure later in
     the run; the precheck is unambiguous and durable across skopt
     version bumps (no string-matching the error message).
   - **Seed convention**: `random_state = 42 ^ len(opt.Xi)` (xor, not
     pow — see [botorch-predict-seed-pow-vs-xor](/incidents/botorch-predict-seed-pow-vs-xor.md)). Round 0 → seed=42,
     matches `Optimizer(random_state=42)` for reproducibility.
   - **Rejection-rate sanity check for prodtarget**: joint constraint
     (`min(rOut)>=3` AND `lPlate>=tPlate+0.5` at all 3 knots) accepts
     ~9% of uniform draws in the 11D box → P(all 20 retries fail)
     ≈ 15%. Non-trivial but bounded; if it bites, draw `q*8` candidates
     per retry and filter (deferred — round 0 only).

Implementation site: `autoresearch_bo_michael.py:268-279`
(`BOMode.ask_buildable`). Mode-agnostic — lives in the base class, not
in `ProdTargetMode`, so any future zero-prior mode benefits.

## Cross-links
- Related: [bo-prodtarget](/projects/bo-prodtarget.md) (cold-start decision section), [batch-bo](/concepts/batch-bo.md), [langgraph-checkpoint-numpy-int64](/incidents/langgraph-checkpoint-numpy-int64.md)
- Source: `autoresearch_bo_michael.py:269` (ask_buildable),
  `.venv-graph/.../skopt/optimizer/optimizer.py:490`

## Open questions / TODO
- Decide on fix option 1/2/3 before launching #16 Step A in real (not
  dry-run) mode — Step A is one-config but it goes through `propose`.
