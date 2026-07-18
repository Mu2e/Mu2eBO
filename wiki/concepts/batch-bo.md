---
type: concept
title: Batch / Asynchronous Bayesian Optimization
description: q>1 parallel BO; CL-mean q=3 (michael) / CL-min q=2 (helical); skopt-native
status: active
timestamp: '2026-06-04'
updated_note: 'n=251 overlay post-foilsX08: CL-min L2=0.075 + 10/10 dominance —
  collapse onto `(n_up=6, n_down∈{0,1}, rOut≈128, hT≈0.23, rIn=0)`; sequence n=128→0.139,
  n=164→0.095, n=178→0.821, n=186→0.079, n=193→0.590, n=204→0.122, n=251→0.075'
---

# Batch / Asynchronous Bayesian Optimization

## Summary
How to propose **q > 1 in-flight BO points** at once instead of one-at-a-time, so
grid wall-clock parallelism amplifies into BO iteration throughput. The decision
that matters here: which batch-acquisition method, at which `q`, given our
setup (sklearn-GP + EI in `skopt.Optimizer`, ~96 michael priors, 10 helical
priors, 4–5D continuous + 1 categorical, ~1–2 h grid wall per point, async
returns are the norm because mustops_ce wall-time spans wider than mubeam).

The short answer: **CL-mean at q=3, ceiling q=5, for michael mode. CL-min at
q=2 for helical until history grows.** scikit-optimize ships this natively as
`Optimizer.ask(n_points=q, strategy=...)` — the retrofit is ~10–30 LOC inside
`bo_driver.py:cmd_propose` plus a small pending-state file.
Long answer below.

## Key facts — method landscape

| Method | What | Cost | Practical q | Notes for us |
|---|---|---|---|---|
| **Constant Liar (CL-mean/min/max)** | greedy; pretend picked points returned a fake `y`, refit, repeat | `O(q)` GP updates | up to ~50 | Native in skopt. Default starting point. CL-min more exploratory, CL-max more exploitative, CL-mean neutral. |
| **Kriging Believer (KB)** | greedy; fake value = posterior mean → collapses variance at pick | `O(q)` GP updates | up to ~50 | Better diversity than CL-mean; not in skopt. Equivalent to BoTorch `qNEI` fantasy mode. |
| **q-EI / q-NEI** | jointly optimize multipoint EI over all q points | `O(N_mc · q · n²)` per eval | ~10 closed-form, ~50 MC | Theoretically Bayes-optimal one-step lookahead. Requires BoTorch rewrite. |
| **qKG / fantasy KG** | one-step lookahead in posterior-mean improvement | `N_fantasies` GP refits per eval | ~8 | Most expensive; overkill for n≈100. |
| **Thompson Sampling (TS)** | draw q posterior samples, each worker maxes its own | `O(n³)` Cholesky, then independent | hundreds discrete / ~20 continuous | **Collapses** with strong priors — all samples concentrate near the incumbent. Bad fit for us once history grows. |
| **Local Penalization (LP)** | maximize `α(x)·Π_j φ(x;x_j)` with exclusion ball at each pick | `O(q)` acq maximizations, no GP refit | ~20–50 | Lipschitz-estimate based; fragile in high-D or non-stationary surfaces. GPyOpt has it; archived. Trieste also. |
| **Async TS / PLAyBOOK** | improved LP for asynchronous workers | per-pending-point | worker-limited | PLAyBOOK (Alvi 2019) beats async-TS / async-KB on most benchmarks; not in skopt. |

**Empirical pecking order (general):** qEI/qKG > KB ≈ CL-mix > CL-mean > CL-min/max > random. LP and TS swap places depending on whether the surface is rugged (LP wins) or the prior is informative (TS collapses).

**Sync vs async:** async dominates wall-clock when worker runtimes are heterogeneous (mustops_ce stage has 5–10× more variance than mubeam due to OOM tails and FCL init time). Sync only wins if all evaluations finish in lockstep — they don't.

## Key facts — fit to our setup

- **`skopt.Optimizer` already supports CL natively** via `ask(n_points=q, strategy="cl_min"|"cl_mean"|"cl_max")` — the `Optimizer` built at `bo_driver.py:152-161` is CL-capable out of the box. No new dependency.
- **Prior leverage:** 96 michael priors → CL fakes are ~5% perturbation of the conditioned set, safe up to q=5. 10 helical priors → q=5 means 50% extra "fake data" per round; CL aggressively flattens EI near picks → cap helical at **q=2 with `cl_min`** until history reaches ~30 real points.
- **The seam is q=1 today.** `cmd_propose` (`bo_driver.py:423-458`) calls `opt.ask()` once, renders one geom, prints one shell instruction.
- **Pending state must persist across `propose` invocations.** `Optimizer` is rebuilt from scratch every call (`bo_driver.py:429`) with `random_state=42` (`:160`) — without a pending-points file, two back-to-back `propose` calls return the *same* `x`.
- **Grid layer is q-ready.** `pipeline.py` is fully parametric per `--config` (`pipeline.py:36-67`); `poll_cluster` is cluster-scoped (`pipeline.py:323-356`); q parallel pipelines do not interfere. Per-user FIFE quota easily absorbs q=5 × ~300 jobs ≈ 1500 jobs.
- **Library alternatives that preserve the 96-point warm start:** BoTorch (`SingleTaskGP(X, y)` + `qLogNoisyExpectedImprovement` with `X_pending=`), Trieste (`AsynchronousGreedy`), HEBO (`observe(X, y)`). Ax wraps BoTorch but needs `Experiment` ceremony. Dragonfly has unique async-TS but stagnant since 2022.
- **One pitfall the libraries don't fix:** the categorical `col5` dimension in michael mode (`bo_driver.py:204`) is awkward for libraries that assume pure-continuous spaces. Stay on skopt unless we're already paying the rewrite cost for q-EI semantics.

## Key facts — retrofit shape (no code yet)

Three surgical patches land the batch retrofit; a fourth would automate the grid handoff.

1. **`cmd_propose` (`bo_driver.py:423`):**
   - `nargs="+"` on the config-name argument or add `--q N`.
   - Replace `opt.ask()` with `opt.ask(n_points=q, strategy="cl_mean")`.
   - Loop the render/stage block over the q `xs`.
   - Write each as a pending row.
2. **`BOMode.load_history` (`bo_driver.py:132`):** union the pending file so the next `propose` knows what's in flight — **do not `tell` pending points to the optimizer** (CL injects them internally during `ask`). Pending suppression only prevents re-proposal on rerun.
3. **Pending persistence:** new sibling file `pending_bo_<mode>.tsv` with `config, knobs…, alpha, submitted_at`. `cmd_evaluate` atomically moves pending → leaderboard. `flock` around `cmd_propose` body to prevent concurrent-propose races (no locking exists today).
4. **(Optional) Orchestrator:** thin driver that takes the q proposal names and fans out the per-config `pipeline.py … submit/poll/harvest/evaluate` chains. `autoresearch_loop.py` is the natural home.

**Recommended starting strategy by mode:**
- `michael`: `strategy="cl_mean"`, q=3 → bump to q=5 if batches stay diverse.
- `helical`: `strategy="cl_min"`, q=2 only — until history ≥ ~30 real points.

**Diagnostic for q creep:** if `propose` starts returning near-duplicate geometries within a batch, CL is leaking; drop q or switch `strategy` to a more pessimistic variant.

**Measured CL-min collapse on saturated frontier (2026-05-31, foils n=128):**
`mmackenz_table_plots/diversity_overlay_foils.py` asked both pickers for q=10
batches against the same n=128 leaderboard. CL-min produced an essentially-
degenerate batch: all 10 picks within a normalized-5D L2 ball of radius ≈0.07
around `(n_up=6, n_down=6, rOut≈155, hT≈0.12, rIn≈7)`; **intra-batch mean
pairwise L2 = 0.139** (vs sqrt(5)=2.24 max, vs BoTorch qNEHVI **0.959**).
BoTorch picks dominated ≥1 CL pick on predicted (sob, calo) in **10/10**
cases; CL dominated BoTorch in **0/10**. Mechanism: the running-min lie
saturates near the incumbent once the frontier is wide, so subsequent
fake-tells don't push EI away. **Operational implication:** at n≈100+
with a wide frontier, skopt's `cl_min` is no longer a useful diversifier
for foils; closed_loop should either (a) switch the picker to BoTorch
qNEHVI (already available as `botorch_predict.compute_explore_picks
--mode foils`), or (b) add jitter to the running-min lie. The Phase-2
gate above ("cluster fraction < 0.2 OR median batch-best ≥ 1.2× sequential")
is now empirically hit on foils. Plot: `diversity_overlay_foils.png`.

**Picker-comparison referee bias (2026-05-31, methodology audit):** both
the n=128 and n=164 "BoTorch dominates CL" / "CL dominates BoTorch"
results in `diversity_overlay_foils.py:107,126-130` are produced by
**a single BoTorch GP** scoring **both pickers' picks**. BoTorch qNEHVI
optimizes against that exact posterior surface; its picks are extremal
on the (sob, calo) plane being plotted **by construction**. CL-min
optimizes against a *different* posterior (sklearn Matérn, different
lengthscales). The "flip" between n=128 and n=164 is consistent with
the BoTorch GP's belief shifting (champion ridge sharpened by
foilsX07R01_03), not with one picker producing better OBSERVED obj on
the grid. **Honest test (not yet run):** held-out judge GP fit on
cohorts NEITHER picker has trained on, then score both pickers' picks
by judge-predicted mean obj. Leaderboard has 20 cohorts (foilsX01R00 →
foilsX07R04); LOCO over last 5 cohorts is ~100s no-grid runtime. The
**existing closed_loop default (CL-min) is safer than a switch to
qNEHVI** for THIS surface because (a) the picker comparison is biased,
(b) qNEHVI maximizes Pareto HV but our objective is scalarized
(`obj = sob − 1e5·calo`) — the matching BoTorch acquisition is
**qLogNEI** not qNEHVI, and (c) `botorch_predict.py:185-191` rounds
Integer dims (n_up, n_down) post-hoc, silently collapsing intra-batch
diversity for those dims. If exploration restoration is wanted, the
cheaper first move is **switch CL-min → CL-mean** (one-character config
change, no new venv plumbing) before reaching for BoTorch.

**qLogNEHVI is now LIVE on the qnehvi path (applied 2026-06-04, for `foilsZ03`).**
`.venv-botorch` ships **botorch 0.10.0** with the Log-EI family
(`qLogNoisyExpectedHypervolumeImprovement` / `qLogNoisyExpectedImprovement`
in `botorch.acquisition.multi_objective.logei`). `botorch_predict.py:_qnehvi_picks`
now imports + instantiates **`qLogNoisyExpectedHypervolumeImprovement`** (was the
plain `qNoisyExpectedHypervolumeImprovement`). **Swap gotcha:** the Log variant
lives in a DIFFERENT module — `…multi_objective.logei`, not `…monte_carlo` — so
the swap changes the **import line**, not just the class name (constructor args
are identical = drop-in). So `--picker qnehvi` now runs qLogNEHVI. The Log
variants (Ament et al. 2023,
"Unexpected Improvements to Expected Improvement") fix the **vanishing
acquisition-value / flat-gradient** failure of the original MC acquisitions,
so `optimize_acqf` finds better candidates — the gain is largest **near
saturation**, where improvement (hence the raw acquisition value) is tiny
(exactly where `foilsZ02` sat at round 6). Swapping qNEHVI →
**qLogNEHVI is a drop-in** (identical constructor args). Note the deeper
mismatch already flagged above: our objective is *scalarized*, so the truly
matching single-objective acquisition is **qLogNEI**, not either qNEHVI
variant — "go Log" applies to whichever acquisition you pick.
  - **`sequential=True` is MANDATORY at large q (gotcha, 2026-06-04).**
    `botorch_predict.py:_qnehvi_picks` called `optimize_acqf(..., q=q,
    sequential=False)` = **joint** batch optimization, a single **q×d-dim**
    problem (`num_restarts=16, raw_samples=512, maxiter=200`). Tractable at q=3
    (18-D, ~20 s) but **blew past a 10-min wall at q=10** (60-D) → smoke-test
    `rc=124` timeout, no picks. Fix: **`sequential=True`** (sequential greedy —
    optimize the q candidates one at a time, each a cheap d-dim problem; the "N"
    handles pending picks via fantasies). This is *also* BoTorch's recommended
    batch mode for qNEHVI. **Confirmed: sequential q=10 qLogNEHVI = ~4.5 min**
    (4:28, vs >10 min joint-timeout) — that's the per-round picker cost,
    negligible vs the ~80 min grid wall/round. Launched `foilsZ03` (q=10×5) on it.
    So the q-scaling ceiling has a **picker-side cost**
    on top of the grid-throughput one ([closed-loop-runner](/drivers/closed-loop-runner.md) lever 2): joint
    optimize_acqf is O(q·d)-dim and explodes; sequential is linear in q. Always
    `sequential=True` for q≳5.
  - **Acquisition-selection rule for THIS problem (2026-06-04):**
    **noise → keep the "N"** — our `(sob, calo)` carry a real ~8% calo run-to-run
    floor (the foilsZ02 `obj=2.017` may itself be a 1-sample noise spike), so the
    *Noisy* variants (qLogNEHVI / qLogNParEGO) are correct and **qLogEHVI is
    wrong** (it trusts the noisy front as exact). **≤3 objectives → NEHVI**: we
    have exactly **2** objectives (`sob`, `−log10 calo`), the regime where NEHVI
    is most sample-efficient and its hypervolume box-decomposition is cheap (2-D);
    **qLogNParEGO** (random-Chebyshev-scalarization, also α-free) is a *downgrade*
    here — its edge is **4+ objectives or very large batches**, where NEHVI's HV
    cost explodes. **Trigger to revisit:** if a 3rd+ objective is ever added
    (e.g. CPU/eval, a 2nd background channel, stop-efficiency), switch to
    qLogNParEGO. Until then: **qLogNEHVI**.
  - **Library survey CLOSED (2026-06-04) — don't re-shop.** Evaluated and
    rejected: **GPflowOpt** (2017-era, GPflow/**TF 1.x**, unmaintained —
    superseded by BoTorch on every axis); **BoTier** (BoTorch extension for
    *tiered/lexicographic* objective priorities — solves a preference structure
    we don't have; ours is a flat 2-obj trade-off); **MOBO** (not a library —
    the general *category* of multi-objective BO that qNEHVI already IS). Net:
    BoTorch + qLogNEHVI is the settled choice for our noisy 2-objective regime;
    **marginal gains are now in the PROBLEM (pitch dimension [bo-foils](/projects/bo-foils.md),
    confirming the 2.017, or adding a 3rd objective), not in more
    optimizer/library shopping.**
- **Mid-campaign edit GOTCHA:** `closed_loop` re-shells `botorch_predict.py`
  in a **fresh subprocess every round** (`_qnehvi_picks_subprocess`), so
  editing the acquisition does NOT need a parent restart — it takes effect on
  the **live run's very next round**, silently changing the picker mid-campaign.
  To keep a running campaign's picker consistent, apply acquisition swaps only
  between campaigns (or accept the round-N+ switch deliberately).

**Pareto-dominance flip at n=164 (2026-05-31, post-foilsX07 R04):** re-ran
the same overlay on the 164-row leaderboard. Intra-batch spread:
**BoTorch 0.833**, **CL-min 0.095** (CL collapsed even tighter than at n=128).
But predicted Pareto dominance **fully reversed**: CL-min picks dominated
≥1 BoTorch pick in **10/10** cases; BoTorch dominated CL in **0/10**.
Mechanism: foilsX07R01_03 (obj=2.178, sob=3.60, calo=1.4e-5) and siblings
defined a narrow band of champions at `(n_up=6, n_down=6, rOut≈210-230,
hT≈0.08, rIn≈20)`; CL-min collapses ONTO that band (its 10 picks predict
sob∈[3.07, 3.34], calo∈[1.37e-5, 1.65e-5]) while BoTorch qNEHVI scatters
across underexplored corners (sob∈[0.80, 3.58]) and lands mostly at
predicted-worse points. **Operational implication:** the n=128 conclusion
("switch to BoTorch") was leaderboard-state-specific — once the champion
ridge is sharp, exploitation (CL-min collapse) beats exploration (qNEHVI
scatter) on next-pick predicted dominance. The robust answer is to keep
both pickers in rotation, not to crown one.

**LOCO honest-judge result (2026-05-31, foils n=177, q=5):**
`mmackenz_table_plots/loco_picker_eval.py` removes the self-refereeing
bias above by holding cohort C out of BOTH pickers' training and
holding the **judge GP** out of cohorts {C, C−1} (target + closest
neighbor). Judge scores both pickers' q=5 picks by
`posterior.mean → obj = sob − 1e5·calo`. Aggregate over last 5 cohorts
(foilsX07R02..R06): **CL-min wins mean-obj 4/5, best-obj 3/5**;
Δ(BO−CL) mean=**−0.53**, median=**−0.60**, range [−1.22, +0.72]. BO
only wins R02 (least-sharpened leaderboard). **Confirms** the
referee-bias hypothesis: once the judge has not seen what either picker
trained on, CL-min's champion-ridge exploitation actually scores higher
on judge-predicted obj than qNEHVI's scatter. The n=128 / n=164
diversity_overlay flips were artifacts of the BoTorch self-judge, not
real picker-quality signals. **Operational implication:** do NOT swap
closed_loop's default picker to qNEHVI on the strength of the
diversity_overlay finding; CL-min is the better next-pick predictor on
this surface as of 2026-05-31. Pickers should be kept in rotation, not
crowned.

**Two-phase explore→exploit strategy (proposed 2026-06-04, not yet run).**
"Keep both in rotation" concretizes as a *sequence*: (1) **qNEHVI/qLogNEHVI
explores** (wide q ~10, α-free, batch-diverse) until its **hypervolume
plateaus**, populating the leaderboard with a sharp ridge; (2) **cl_min
exploits/refines** (small q ~2–3, α-targeted) seeded from that ridge. This puts
each picker exactly where LOCO shows it wins (qNEHVI on un-sharpened boards,
cl_min once the ridge is sharp). Non-obvious design points:
- **Handoff is automatic** — both pickers read the same per-mode leaderboard via
  `load_history`, so phase-2 cl_min just seeds from phase-1's rows; no transfer.
- **Defer α to phase 2.** Phase-1 qNEHVI is α-blind (maps the whole front), so
  you choose α *after* seeing the front, then cl_min drills that α-optimum.
- **Hand off on HV-plateau, NOT obj-plateau.** qNEHVI doesn't optimize `obj`
  (it's α-blind), so "obj stopped improving" is the wrong trigger; use the
  saturation FoM's HV plateau.
- **cl_min's boundary-collapse becomes the FEATURE in phase 2** — you *want* it
  to stop wandering and densely sample the best region. Small q sidesteps the
  large-q collapse pathology.
- **Bounded upside:** phase 2 polishes (confirm/refine, few-% obj), it does not
  leap — near a true optimum, refinement has diminishing returns. Good use right
  now: confirm whether foilsZ02's marginal n=1 `obj=2.017` ([bo-foils](/projects/bo-foils.md)) is real
  by collapsing cl_min onto the thin-annulus region. **Runtime knob:** the LOCO script monkey-patches
`botorch.optim.optimize_acqf` with cheap settings (num_restarts=4,
raw_samples=128, maxiter=50; vs production 16/512/200) for ~30× speedup;
parallel-pool of 5 cohorts runs in ~3 min wall (was ~7-8 min serial).
Output: `loco_picker_eval.json`.

**n=178 overlay refresh (2026-05-31, post-foilsX07 R07):** third
diversity_overlay run on the now-178-row leaderboard. **CL-min intra-batch
L2 jumped 0.095 (n=164) → 0.821 (n=178)** — no longer the degenerate
collapse seen at n=128/164. Mechanism: foilsX07 R05+R06+R07 added points
that broadened the champion ridge (multiple distinct (n_up=6, n_down∈{2..5},
rOut∈[180,250]) configs near obj≈2.1), so the running-min lie no longer
locks every pick to a single corner. Pareto dominance also moderated:
**CL-min 5/10 vs BoTorch 3/10** (vs the dramatic 10/0 reversals at n=128
and n=164). **Operational implication reinforces the LOCO finding:**
CL-min's "saturation collapse" is leaderboard-state-specific, not a
permanent failure mode; whichever picker the closed_loop is configured
with, the diversity_overlay should be re-run after every ~30 evals to
catch the transition. The 3-hour qNEHVI runtime at n=178 (was ~5 min at
n=128) is also load-bearing: BoTorch GP fit + qNEHVI optimize scales
super-linearly in n; budget accordingly. Wall: 25 min from skopt-CL-min
start to PNG write; ~3 hr aggregate CPU on 12 cores. Plot:
`diversity_overlay_foils.png`.

**n=186 overlay (2026-05-31, post-foilsX07 R07):** fourth run, +8 rows
from R07 (top R07 obj=1.992, none beat the R01 champion 2.178). **CL-min
L2 collapsed back to 0.079** (the tightest of all four runs: n=128→0.139,
n=164→0.095, n=178→0.821, n=186→0.079). All 10 CL picks pinned at
`(n_up∈{3,4}, n_down=6, rOut≈130, hT≈0.13, rIn≈12)` — a *different* ridge
than the R01 champion neighborhood. Dominance fully reverted: CL-min
10/10 vs BoTorch 0/10. **Mechanism:** the R07 picks at `(n_up=3, n_down=6,
rOut≈160, hT≈0.21)` (obj≈1.99) sharpened CL-min's posterior view of a
second sub-champion ridge, and the running-min lie immediately collapses
onto it. **Implication:** the n=178 broadening was a temporary artifact
of mid-cohort posterior smoothness, NOT a stable behavioral change.
Spread is volatile in BOTH directions; do not infer a trend from any
single overlay snapshot — use the LOCO honest-judge metric (above) for
operational picker decisions.

**n=193 overlay (2026-05-31, post-foilsX07 R08 partial):** fifth run.
**CL-min L2=0.590** (recovered from 0.079 at n=186 but well below the
n=178 0.821 peak); BoTorch L2=0.968; inter-batch centroid 0.576.
**Pareto dominance: BoTorch 5/10 vs CL-min 0/10** — *sharpest BoTorch
advantage observed in this series* (vs 3/5 at n=178, 0/10 at n=186).
CL-min still spends 8/10 picks on the `rOut=250, hT=1, rIn=0` boundary
corner (mode-collapse to GP-predicted "safe" extreme). Sequence so far:
n=128→L2 0.139, n=164→0.095, n=178→0.821, n=186→0.079, n=193→0.590 —
confirms volatility is fundamental, not a transient. Wall time:
~1h45min total (qNEHVI step alone exceeded 90 min on 12 cores at
n=193 — well past the super-linear knee). Plot:
`diversity_overlay_foils.png`.

**n=204 overlay (2026-05-31, post-foilsX07 exit, +11 rows from R08+R09):**
sixth run. **Dramatic reversal vs n=193**: CL-min L2 collapsed back to
**0.122**, Pareto dominance flipped fully to **CL-min 10/10 vs BoTorch
2/10**. Inter-batch centroid distance **1.197** (largest in the series —
the two pickers' picks are now in *entirely different* regions of X-space).
**New observation:** CL-min collapsed onto a NEW corner this time —
`rOut≈245, hT≈0.5, rIn≈50` (boundary on all three continuous dims) — vs
the n=186 collapse onto `rOut≈130, hT≈0.13, rIn≈12`. The corner *identity*
varies between collapses even when L2 is similarly low; CL-min finds
whichever GP-predicted "safe" extreme the current posterior favors.
Updated sequence: n=128→0.139, n=164→0.095, n=178→0.821, n=186→0.079,
n=193→0.590, n=204→0.122. **Operational implication:** ratchets the
LOCO-honest-judge conclusion. The diversity_overlay metric oscillates
wildly with leaderboard state (BoTorch L2 ∈ [0.83, 1.07], CL-min L2
∈ [0.079, 0.821], dominance flips fully both ways within 11 rows) —
it is NOT a reliable picker-quality signal in isolation. Plot:
`diversity_overlay_foils.png`.

**n=251 overlay (2026-06-01, post-foilsX08 close at R04):** seventh run,
+47 rows from full foilsX08 cohort (qNEHVI production picker). **CL-min
L2 collapsed to 0.075** (tightest in the entire series, beating n=186's
0.079); BoTorch L2=1.148 (highest seen). Inter-batch centroid 1.010.
Pareto dominance fully on CL-min: **10/10 vs BoTorch 0/10**. New corner
this time: CL-min collapsed onto `(n_up=6, n_down∈{0,1}, rOut≈128,
hT≈0.23, rIn=0)` — a *third distinct* collapse corner across the series
(n=186 was rOut≈130/hT≈0.13/rIn≈12; n=204 was rOut≈245/hT≈0.5/rIn≈50).
**Notable:** the qNEHVI-driven foilsX08 cohort did NOT shift CL-min's
behavior toward the BoTorch picks — the running-min lie still finds
whichever GP-predicted safe extreme dominates the current posterior,
independent of which picker generated the recent evals. Updated
sequence: n=128→0.139, n=164→0.095, n=178→0.821, n=186→0.079,
n=193→0.590, n=204→0.122, n=251→0.075. Plot:
`diversity_overlay_foils.png`.

## Cross-links
- Related: [bo-noise-budget](/concepts/bo-noise-budget.md), [fast-sim-options-for-bo](/concepts/fast-sim-options-for-bo.md), [orchestrator-evaluation-2026-05](/concepts/orchestrator-evaluation-2026-05.md), [pareto-sob-picker](/concepts/pareto-sob-picker.md), [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md), [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md)
- Driver: [bo-driver](/drivers/bo-driver.md)
- Driver: [pipeline](/drivers/pipeline.md)
- Concept: [bo-modes](/concepts/bo-modes.md), [closed-loop-bo-design](/concepts/closed-loop-bo-design.md), [gp-cloud-rendering](/concepts/gp-cloud-rendering.md), [scalarized-objective](/concepts/scalarized-objective.md)
- Project: [bo-michael](/projects/bo-michael.md), [bo-helical](/projects/bo-helical.md)
- Source files: `bo_driver.py:152-161` (Optimizer factory), `:423-458` (cmd_propose, batch retrofit lands here), `:132-150` (history I/O, pending-union point), `pipeline.py:36-67` (per-config paths, q-safe today)

## Sources
- Ginsbourger, Le Riche, Carraro 2010 — *Kriging is well-suited to parallelize optimization* (CL + KB) — [PDF](https://www.cs.ubc.ca/labs/algorithms/EARG/stack/2010_CI_Ginsbourger-ParallelKriging.pdf)
- Chevalier & Ginsbourger 2013 — *Fast computation of multi-points EI* — [HAL](https://hal.science/hal-00732512v2)
- González, Dai, Hennig, Lawrence 2016 — *Batch BO via Local Penalization* — [arXiv:1505.08052](https://arxiv.org/abs/1505.08052)
- Wang, Clark, Liu, Frazier 2020 — *Parallel BO of Expensive Functions* (MC qEI) — [arXiv:1602.05149](https://arxiv.org/abs/1602.05149)
- Hernández-Lobato et al. 2017 — *Parallel & Distributed Thompson Sampling* — [ICML PDF](http://proceedings.mlr.press/v70/hernandez-lobato17a/hernandez-lobato17a.pdf)
- Kandasamy, Krishnamurthy, Schneider, Póczos 2018 — *Parallelised BO via TS* — [arXiv:1705.09236](https://arxiv.org/abs/1705.09236)
- Alvi, Ru, Calliess, Roberts, Osborne 2019 — *Async batch BO with improved LP* (PLAyBOOK) — [arXiv:1901.10452](https://arxiv.org/abs/1901.10452)
- Balandat et al. 2020 — *BoTorch* (qEI/qNEI/qKG via SAA) — [NeurIPS PDF](https://proceedings.neurips.cc/paper/2020/file/f5b1b89d98b7286673128a5fb112cb9a-Paper.pdf)
- skopt parallel-optimization example — [docs](https://scikit-optimize.github.io/stable/auto_examples/parallel-optimization.html)
- BoTorch closed-loop qNEI tutorial — [docs](https://botorch.org/docs/tutorials/closed_loop_botorch_only/)
- Trieste async-greedy notebook — [docs](https://secondmind-labs.github.io/trieste/3.0.0/notebooks/asynchronous_greedy_multiprocessing.html)

## Open questions / TODO

### Q1: skopt CL-mean vs BoTorch qLogNEI

**Trade-off.** skopt CL is ~30 LOC of glue inside `cmd_propose`; reuses the
existing GP, EI, and `col5` categorical handling. BoTorch `qLogNEI` with
`X_pending=` is the gold-standard joint acquisition with native async, but
costs a GP-layer rewrite (sklearn → GPyTorch), a categorical encoding (one-hot
or `MixedSingleTaskGP`), and refits hyperparameters from scratch on first run.

**Recommendation — staged path:**
1. **Phase 1 (now):** ship skopt CL-mean q=3. Measures whether batch BO is
   worth the engineering at all on *this* surface. ~30 LOC + pending file +
   `flock`. Risk-free: if it underperforms sequential, revert is one git revert.
2. **Phase 2 (gate on phase-1 evidence):** if after ~5 batches the leaderboard
   shows CL batches clustering (≥2 points in a batch within 10% of each other
   in the dominant `tsda.rin` axis), or the per-batch best-improvement is
   flat vs sequential, **then** commit to BoTorch. Otherwise stay on skopt.
3. **Skip Phase 2 entirely** if `col5` becomes irrelevant (e.g. one
   category dominates the leaderboard); the case for BoTorch is much weaker
   without the mixed-space need.

**Decision criterion for Phase 2 (write this down so we don't relitigate):**
median batch-best-improvement over 5 batches must be ≥ 1.2× sequential-best
over the same wall-clock window, OR cluster fraction must drop below 0.2.
Anything weaker = skopt is already at the Pareto frontier for this problem.

### Q2: helical lengthscale fragility

**Problem.** 10 priors in 5D is sparse — sklearn's `GaussianProcessRegressor`
will fit kernel lengthscales by marginal-likelihood maximization, which is
underdetermined here and frequently snaps to either the bound or a degenerate
near-zero value. `cl_min`'s pessimism repels picks via the *kernel* — if
lengthscales are too short, repulsion is local-only and CL barely diversifies
the batch; if too long, every batch member ends up in the same basin.

**Recommendation — three-step diagnostic + fallback:**
1. **Diagnose first (10 min of work):** after `build_optimizer` + warm-up
   `tell`, dump the fitted kernel via `opt.base_estimator_.kernel_`. For each
   dimension, ratio = `length_scale / (bound_high − bound_low)`. Healthy: 0.1–0.5.
   Pathological: <0.01 (overfit to noise) or >2 (kernel claims everything is
   the same). Add this as a one-shot print in `cmd_propose` behind `--debug`.
2. **If pathological, pin priors:** swap the default kernel for
   `Matern(length_scale=[0.3*(b-a) for each dim], length_scale_bounds="fixed")`
   in `build_optimizer` for helical only. Loses adaptation but buys stability.
   skopt accepts a custom `base_estimator` kwarg — no fork needed.
3. **Until lengthscales stabilize (~30 real points), don't trust CL.** Use
   `strategy="cl_max"` (most exploitative, treats picks as already-good →
   smallest distortion to subsequent picks) at q=2 only. This is counterintuitive
   but right: with bad kernel info, *less* CL distortion is safer than more.

**When to revisit:** every 10 new helical points, rerun the diagnostic. Once
all dim ratios are in 0.1–0.5 stably, switch to `cl_min` q=3.

### Q3: autoresearch_loop.py — auto-evaluate or stay human-gated?

**Problem.** Async batch only pays off if `cmd_evaluate` fires as soon as
each pipeline finishes — otherwise pending rows linger and the next `propose`
gets stale info. But auto-evaluation on a corrupt `summary.json` would
silently poison the leaderboard. We have one known case of that already
([harvest-denominator-bug](/incidents/harvest-denominator-bug.md) — the corrected sob was 3% off and the GP would
have happily learned the wrong shape for many batches).

**Recommendation — gated auto-eval with three sanity assertions:**
1. **Harvest writes a `summary.json` + a `harvest.ok` marker** only after
   passing internal checks (file count ratios per [grid-job-completion-check](/incidents/grid-job-completion-check.md),
   non-NaN sob/calo, ce_simulated_events > 0). One-line change in `cmd_harvest`.
2. **`autoresearch_loop.py` polls** for `harvest.ok` across pending configs
   (cheap directory listing every 5 min). On hit, runs `cmd_evaluate` with
   three assertions before the leaderboard append:
   - `0 < sob < 10` (current best 2.71; a value outside this is sensor noise)
   - `0 < calo_per_pot < 1e-4` (orders-of-magnitude sanity)
   - `0.05 < ce_files / ce_njobs_configured < 1.0` (lost-job fraction in
     plausible range — guards against the denominator bug regressing)
   Any assertion fails → leave pending row, log to `autoresearch_loop.errors`,
   page the human (write to stderr, no Slack ceremony).
3. **Human-gated escape hatch:** `--manual-eval CONFIG` flag on the loop
   driver to suppress auto-eval for a specific config if it's known weird.

**What to NOT automate:** `cmd_propose` itself stays human-triggered. The
"submit q new configs" call is the only place a human sanity-checks the
proposed geometries before grid resources commit. Pure-loop autonomy is a
future decision once we have 10+ successful auto-evals on record.

**Definition of done:** loop survives 5 consecutive auto-evals without a
human-triggered correction. At that point, consider relaxing the assertions
or adding more (e.g. preflight-pass requirement on proposed geoms before
they hit the grid).
