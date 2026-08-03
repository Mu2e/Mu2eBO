---
type: incident
title: Hybrid picker (qnehvi+qnparego) non-reproducible at production leaderboard scale
description: torch.manual_seed(_seed(round_idx)) is set inside the picker, AFTER an unseeded _fit_gp; on a ~300-row leaderboard scipy's L-BFGS-B hits ABNORMAL termination and retries draw extra RNG, so re-running the same seed/inputs gives materially different picks
status: open
status_note: found 2026-07-19 building tests/golden_parity.py Task 4; golden (b) redesigned as a tensor fingerprint and committed (eeb8cb6) — only the underlying picker nondeterminism remains open, no production fix applied
timestamp: '2026-07-19'
---

# Hybrid picker (qnehvi+qnparego) non-reproducible at production leaderboard scale

## Summary

`core/botorch_predict.py`'s `hybrid` picker (60% qnehvi + 40% qnparego,
`_hybrid_picks` at line ~330) is supposed to be reproducible per round via
`torch.manual_seed(_seed(round_idx))` (`_seed` = `42 ^ round_idx`, the XOR
convention pinned by
[botorch-predict-seed-pow-vs-xor](/incidents/botorch-predict-seed-pow-vs-xor.md)).
That holds on small fixtures (Task 3's `test_real_gp_qnehvi_pick_on_fixture`,
10 rows) but **breaks down at production scale**: on the live 304-row
foilsflash leaderboard, five independent `--mode foilsflash --q 2
--round-idx 0 --picker hybrid` invocations against the *identical* frozen
leaderboard copy each produced a **different** picks tensor — not
float-epsilon different, but up to ~0.6 off in a 0-1 normalized knob
dimension. This surfaced building `tests/golden_parity.py` (Task 4, golden
section (b)); capture vs. immediate re-check printed `MISMATCH`, not the
brief's anticipated `WARN (allclose)`.

## Key facts

- `_fit_gp` (`core/botorch_predict.py:198-213`, calls
  `botorch.fit.fit_gpytorch_mll`) runs **before** any `torch.manual_seed`
  call in the picker path — the seed is set later, inside
  `_qnehvi_picks`/`_qnparego_picks` (`core/botorch_predict.py:309`). In
  practice the fitted GP noise sigma WAS bit-identical across all 5 runs
  (`raw=['5.344e-02', '1.454e-02'] standardized=['0.096', '0.141']`), so
  `_fit_gp` itself is not the source — but it's still unseeded and worth
  fixing defensively.
- The actual divergence source: every run hit
  `botorch/optim/optimize.py:480-509`'s retry branch —
  `RuntimeWarning: Optimization failed in gen_candidates_scipy ... status 2
  ABNORMAL ... Trying again with a new set of initial conditions` — which
  calls `opt_inputs.get_ic_generator()` again, drawing **additional**
  random numbers from torch's global RNG stream (the same stream
  `torch.manual_seed(_seed(round_idx))` seeded once at picker-function
  entry).
- Whether/how-many-times a given `num_restarts=16` L-BFGS-B run ABNORMAL's
  is itself sensitive to floating-point summation order in multi-threaded
  BLAS (see the accompanying `NumericalWarning: A not p.d., added jitter of
  1.0e-08` from `linear_operator/utils/cholesky.py:41` — borderline
  positive-definiteness in the posterior covariance is exactly the kind of
  computation whose result depends on thread-count/scheduling). This
  creates a chaotic feedback loop: unseeded numeric noise decides retry
  count → retry count decides how far the seeded RNG stream advances →
  final candidates depend on both.
- Reproduced 5/5 times (1 capture + 4 check re-runs, including once with
  `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` — still diverged, so single-threaded
  BLAS alone does not fix it; the ABNORMAL/retry path itself, not just
  thread-count timing, is implicated).
- Task 3's `test_real_gp_qnehvi_pick_on_fixture` (10-row fixture) never
  exercises this: too small for L-BFGS-B to hit ABNORMAL, so the existing
  test suite has zero coverage of this failure mode. It only shows up at
  ~300-row production scale, exactly the scale `tests/golden_parity.py`
  section (b) targets on purpose (frozen `leaderboard_bo_foilsflash.tsv`
  copy).
- Sections (a) (leaderboard round-trip fingerprint) and (c) (evaluate +
  real-G4 preflight replay) of the same harness are NOT affected — both
  reproduced their own capture exactly across re-runs. This is isolated to
  the acquisition-optimization retry path.

## Cross-links

- Related: [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md),
  [pareto-sob-picker](/concepts/pareto-sob-picker.md),
  [botorch-predict-seed-pow-vs-xor](/incidents/botorch-predict-seed-pow-vs-xor.md),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md)
- Source files: `core/botorch_predict.py:198-213` (`_fit_gp`, unseeded),
  `core/botorch_predict.py:309` (seed set here, too late to cover the fit),
  `core/botorch_predict.py:330-363` (`_hybrid_picks`),
  `.venv/lib/python3.11/site-packages/botorch/optim/optimize.py:480-509`
  (retry-with-new-ICs branch that advances the RNG unpredictably)
- No longer blocked: `tests/golden_parity.py` (all three sections, incl.
  (b)) landed committed 2026-07-19 in `eeb8cb6` (Task 4 of the refactor SDD
  plan, `.superpowers/sdd/task-4-brief.md` / `task-4-report.md`). Golden (b)
  was redesigned as a deterministic history-tensor fingerprint on the frozen
  leaderboard copy (no optimizer in the loop) rather than fixed-seed picker
  output — see the spec amendment in
  `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`. Only
  the underlying picker nondeterminism itself (this incident) remains open;
  it does not block the test suite or the golden harness anymore.

## Open questions / TODO

- Does seeding `torch.manual_seed(_seed(round_idx))` immediately before
  `_fit_gp` (in addition to the existing call inside the picker functions)
  fix it, or does the ABNORMAL/retry RNG-advance coupling dominate
  regardless of where the initial seed is planted?
- Is `torch.use_deterministic_algorithms(True)` viable here (likely to
  break or drastically slow GPyTorch's Cholesky path)?
- Does this nondeterminism also affect live closed-loop campaigns (not
  just the golden harness)? If picks are this sensitive to floating-point
  noise at scale, two "identical" `--round-idx` calls in production could
  already be picking different points without anyone noticing — worth an
  audit of whether any campaign has ever re-run the same round-idx twice
  and diffed the output.
