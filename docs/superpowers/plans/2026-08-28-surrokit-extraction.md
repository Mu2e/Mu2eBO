# surrokit Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the generic GP-fit/predict/pickers half of `core/botorch_predict.py` into a standalone `surrokit` library (new repo) with an MCP server scaffold, then rewire autoresearch as a client — bit-identical picks, CLI unchanged.

**Architecture:** New repo `/exp/mu2e/app/users/oksuzian/surrokit` holds the physics-agnostic engine (`Problem`/`Constraint` types, `fit`/`predict`/`ask`, five pickers, `make_server(adapter)`). autoresearch keeps data loading, `-log10` transforms, env reads, and the CLI in `core/botorch_predict.py`, which becomes glue. A bit-parity test gates the cut-over; ported bodies are deleted only after it passes.

**Tech Stack:** Python ≥3.10, botorch ≥0.18, torch, scipy, numpy, unittest; optional `mcp>=2.0` (MCPServer). Interpreter for both repos: ana 2.8.0 (`/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python` — botorch 0.18.1, torch 2.5.1, Python 3.12, mcp 2.0.0).

**Spec:** `docs/superpowers/specs/2026-08-28-surrokit-engine-design.md`

## Global Constraints

- **Two working directories.** Tasks 1–6: `/exp/mu2e/app/users/oksuzian/surrokit` (new repo). Tasks 7–10: `/exp/mu2e/app/users/oksuzian/autoresearch`, branch `readme-slim`.
- **Bit-parity gate:** old `compute_explore_picks` vs `surrokit.ask` must produce IDENTICAL picks on the test fixtures (qnehvi, qlnei, hybrid, budget_sob→constrained_max, cold start) before any old body is deleted (Task 7 gates Tasks 8–10).
- **Library discipline (surrokit):** no `print`, no `sys.exit`, no `os.environ` reads, logger name `"surrokit"`. Library never calls `logging.basicConfig` or sets `torch.set_default_dtype` globally; all tensors are built explicitly as `torch.float64` on CPU.
- **Engine conventions:** every Y axis MAXIMIZED; axis 0 primary; `seed` used VERBATIM in every RNG stream (client passes `42 ^ round_idx`); X in raw knob units.
- **CLI frozen:** `core/botorch_predict.py` argparse surface (`--mode --q --round-idx --picker --emit-picks-json --pending-json --leaderboard`) and its JSON output are unchanged — `graph/closed_loop.py` and `graph/pool.py` must not notice.
- **Suite green at every task boundary:** autoresearch `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .` (685+ tests); surrokit `cd /exp/mu2e/app/users/oksuzian/surrokit && PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`
- **Never `git push`** (no ssh-agent in Bash subshells) — the operator pushes. Never `git add -A`/`-u`/`.` — stage explicit paths.
- **Wiki edits stay uncommitted** for operator review (autoresearch house rule).
- Commit trailers (both repos):
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`

## File Structure

**surrokit repo (new):**
- `pyproject.toml`, `LICENSE` (MIT), `README.md`, `.gitignore`, `.github/workflows/test.yml`
- `surrokit/__init__.py` — public API re-exports + `__version__`
- `surrokit/problem.py` — `Problem`, `Constraint`, `NotEnoughData`, `InfeasibleError`
- `surrokit/gp.py` — `fit`, `predict`, internal `_fit_model`, tensor helpers
- `surrokit/sampling.py` — `sampler`, `optimize_acq`, `sobol_cold_start`, `emit_picks`, ACQ constants
- `surrokit/pickers.py` — `_qnehvi`, `_qlnei`, `_qnparego`, `_hybrid`, `_constrained_max`, `ask`, `PICKER_CHOICES`
- `surrokit/mcp_scaffold.py` — `Adapter` protocol, `make_server`
- `tests/common.py`, `tests/test_problem.py`, `tests/test_gp.py`, `tests/test_sampling.py`, `tests/test_constrained_max.py`, `tests/test_ask.py`, `tests/test_scaffold.py`

**autoresearch (modified):**
- `core/paths.py` — add `SURROKIT_ROOT` seam
- `activate.sh` — document `AUTORESEARCH_SURROKIT` override
- `tests/test_surrokit_parity.py` — the gate (created Task 7, retired Task 8)
- `core/botorch_predict.py` — becomes glue (Task 8), dead bodies deleted (Task 10)
- `surrogate/__init__.py`, `surrogate/adapter.py` (new), `surrogate/mcp_server.py` — rewired Task 9
- `tests/test_surrogate.py`, `tests/test_botorch_predict.py` — updated Tasks 9–10

---

### Task 1: surrokit repo scaffold + Problem/Constraint types

**Files:**
- Create: `/exp/mu2e/app/users/oksuzian/surrokit/` — `pyproject.toml`, `LICENSE`, `.gitignore`, `surrokit/__init__.py`, `surrokit/problem.py`
- Test: `tests/test_problem.py`, `tests/common.py`, `tests/__init__.py` (empty)

**Interfaces:**
- Produces: `Problem(bounds_lo, bounds_hi, int_dims=(), noise=None, constraint=None)` frozen dataclass with `.dim` property; `Constraint(axis, min, k_sigma=1.0)` frozen dataclass; exceptions `NotEnoughData(RuntimeError)`, `InfeasibleError(RuntimeError)`. All importable from `surrokit`.

- [ ] **Step 1: Initialize the repo**

```bash
mkdir -p /exp/mu2e/app/users/oksuzian/surrokit
cd /exp/mu2e/app/users/oksuzian/surrokit
git init -b main
mkdir -p surrokit tests
touch tests/__init__.py
```

- [ ] **Step 2: Write pyproject.toml, LICENSE, .gitignore**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "surrokit"
version = "0.1.0"
description = "Generic ask/tell GP surrogate engine: botorch fit/predict/ask with budget-constrained pickers"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "Yuri Oksuzian", email = "oksuzian@gmail.com"}]
dependencies = ["botorch>=0.18", "torch", "scipy", "numpy"]

[project.optional-dependencies]
mcp = ["mcp>=2.0"]

[tool.setuptools.packages.find]
include = ["surrokit*"]
```

`LICENSE`: the standard MIT license text, first line `MIT License`, copyright line `Copyright (c) 2026 Yuri Oksuzian`.

`.gitignore`:
```
__pycache__/
*.egg-info/
.venv/
```

- [ ] **Step 3: Write the failing tests**

`tests/common.py` — shared deterministic fixtures (no RNG):
```python
"""Shared fixtures: a tiny 2D problem with deterministic history."""
import math

from surrokit import Constraint, Problem

# 2D box, dim 1 is integer-valued. noise pinned (fixed-noise GP).
PROB = Problem(bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 10.0),
               int_dims=(1,), noise=(0.01, 0.01))

# Same box with a budget constraint on axis 1 (feasible: mean1 - k*sig1 >= 2.0).
PROB_C = Problem(bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 10.0),
                 int_dims=(1,), noise=(0.01, 0.01),
                 constraint=Constraint(axis=1, min=2.0, k_sigma=1.0))


def history(n=10):
    """Deterministic (X, Y): smooth 2-output landscape, both maximized."""
    X = [[i / max(n - 1, 1), float(i % 10)] for i in range(n)]
    Y = [[math.sin(3.0 * x0) + 0.1 * x1, 3.0 - 0.2 * x1 + 0.5 * x0]
         for x0, x1 in X]
    return X, Y


def in_bounds(row, lo=(0.0, 0.0), hi=(1.0, 10.0)):
    return all(lo[i] <= v <= hi[i] for i, v in enumerate(row))
```

`tests/test_problem.py`:
```python
import unittest

from surrokit import Constraint, InfeasibleError, NotEnoughData, Problem


class TestProblem(unittest.TestCase):
    def test_valid_problem_and_dim(self):
        p = Problem(bounds_lo=(0.0, 1.0), bounds_hi=(1.0, 2.0))
        self.assertEqual(p.dim, 2)
        self.assertEqual(p.int_dims, ())
        self.assertIsNone(p.noise)
        self.assertIsNone(p.constraint)

    def test_bounds_length_mismatch(self):
        with self.assertRaises(ValueError):
            Problem(bounds_lo=(0.0,), bounds_hi=(1.0, 2.0))

    def test_empty_bounds(self):
        with self.assertRaises(ValueError):
            Problem(bounds_lo=(), bounds_hi=())

    def test_lo_not_below_hi(self):
        with self.assertRaises(ValueError):
            Problem(bounds_lo=(0.0, 5.0), bounds_hi=(1.0, 5.0))

    def test_int_dims_out_of_range(self):
        with self.assertRaises(ValueError):
            Problem(bounds_lo=(0.0,), bounds_hi=(1.0,), int_dims=(1,))

    def test_constraint_validation(self):
        with self.assertRaises(ValueError):
            Constraint(axis=-1, min=0.0)
        with self.assertRaises(ValueError):
            Constraint(axis=0, min=0.0, k_sigma=-1.0)

    def test_exception_hierarchy(self):
        self.assertTrue(issubclass(NotEnoughData, RuntimeError))
        self.assertTrue(issubclass(InfeasibleError, RuntimeError))
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /exp/mu2e/app/users/oksuzian/surrokit && PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t . -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'surrokit'` (or ImportError on names).

- [ ] **Step 5: Write surrokit/problem.py**

```python
"""Problem declaration for the surrokit engine.

Math-space contract: the engine sees only numbers. Every Y axis is
MAXIMIZED; axis 0 is the primary objective. Clients transform/negate on
their side and keep their units to themselves.
"""
from __future__ import annotations

from dataclasses import dataclass


class NotEnoughData(RuntimeError):
    """Fewer than 2 history rows: a GP cannot be fit."""


class InfeasibleError(RuntimeError):
    """constrained_max found zero feasible candidates even at k=0."""


@dataclass(frozen=True)
class Constraint:
    """Feasibility rule on one output axis: mean - k_sigma*sigma >= min."""
    axis: int
    min: float
    k_sigma: float = 1.0

    def __post_init__(self):
        if self.axis < 0:
            raise ValueError(f"Constraint.axis must be >= 0, got {self.axis}")
        if self.k_sigma < 0:
            raise ValueError(
                f"Constraint.k_sigma must be >= 0, got {self.k_sigma}")


@dataclass(frozen=True)
class Problem:
    """Search-space declaration: box bounds, integer dims, per-axis noise
    sigma (ABSOLUTE, in the client's Y-space; None = free MLL noise),
    optional budget Constraint (required by the constrained_max picker).
    """
    bounds_lo: tuple[float, ...]
    bounds_hi: tuple[float, ...]
    int_dims: tuple[int, ...] = ()
    noise: tuple[float, ...] | None = None
    constraint: Constraint | None = None

    def __post_init__(self):
        if len(self.bounds_lo) != len(self.bounds_hi):
            raise ValueError(
                f"bounds length mismatch: {len(self.bounds_lo)} lo vs "
                f"{len(self.bounds_hi)} hi")
        if not self.bounds_lo:
            raise ValueError("empty bounds")
        for i, (lo, hi) in enumerate(zip(self.bounds_lo, self.bounds_hi)):
            if not lo < hi:
                raise ValueError(f"dim {i}: lo {lo} must be < hi {hi}")
        for i in self.int_dims:
            if not 0 <= i < len(self.bounds_lo):
                raise ValueError(f"int_dim {i} out of range for "
                                 f"{len(self.bounds_lo)}D bounds")

    @property
    def dim(self) -> int:
        return len(self.bounds_lo)
```

`surrokit/__init__.py`:
```python
"""surrokit — generic ask/tell GP surrogate engine."""
from .problem import Constraint, InfeasibleError, NotEnoughData, Problem

__version__ = "0.1.0"

__all__ = ["Constraint", "InfeasibleError", "NotEnoughData", "Problem",
           "__version__"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: same command as Step 4. Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /exp/mu2e/app/users/oksuzian/surrokit
git add pyproject.toml LICENSE .gitignore surrokit/__init__.py surrokit/problem.py tests/__init__.py tests/common.py tests/test_problem.py
git commit -m "feat: repo scaffold + Problem/Constraint types

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 2: gp.py — fit + predict

**Files:**
- Create: `surrokit/gp.py`
- Modify: `surrokit/__init__.py`
- Test: `tests/test_gp.py`

**Interfaces:**
- Consumes: `Problem`, `NotEnoughData` from Task 1.
- Produces: `fit(problem, X, Y) -> SingleTaskGP` (public, validating); `predict(model, X) -> (mean, sigma)` numpy `(n, m)` pair; internals for Task 5: `_fit_model(X, Y, bounds, noise)` (tensors in, fitted model out), `bounds_tensor(problem) -> (2, d) torch.float64`, `to_f64(a) -> torch.Tensor`.

**Port source:** `_fit_gp` at autoresearch `core/botorch_predict.py:136-180`, verbatim except: `obs_noise` parameter renamed `noise`, the `print(...)` noise-audit becomes `log.info(...)`, and the docstring drops autoresearch wiki references in favor of a generic fixed-noise rationale.

- [ ] **Step 1: Write the failing tests**

`tests/test_gp.py`:
```python
import unittest

import torch

from surrokit import Constraint, NotEnoughData, Problem, fit, predict
from tests.common import PROB, history


class TestFit(unittest.TestCase):
    def test_fit_and_predict_shapes(self):
        X, Y = history(10)
        model = fit(PROB, X, Y)
        mean, sigma = predict(model, [[0.5, 5.0], [0.1, 1.0]])
        self.assertEqual(mean.shape, (2, 2))
        self.assertEqual(sigma.shape, (2, 2))
        self.assertTrue((sigma >= 0).all())

    def test_not_enough_data(self):
        with self.assertRaises(NotEnoughData):
            fit(PROB, [[0.5, 5.0]], [[1.0, 2.0]])

    def test_shape_mismatch(self):
        X, Y = history(10)
        with self.assertRaises(ValueError):
            fit(PROB, X, Y[:5])
        with self.assertRaises(ValueError):
            fit(PROB, [[0.5]] * 10, Y)  # wrong dim

    def test_constraint_axis_checked_against_y_width(self):
        p = Problem(bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 10.0),
                    noise=(0.01,),
                    constraint=Constraint(axis=1, min=0.0))
        X, _ = history(10)
        Y1 = [[row[0]] for row in history(10)[1]]  # (n, 1)
        with self.assertRaises(ValueError):
            fit(p, X, Y1)

    def test_pinned_noise_reaches_likelihood(self):
        X, Y = history(10)
        model = fit(PROB, X, Y)
        # Fixed-noise likelihood present when Problem.noise is set.
        self.assertTrue(hasattr(model.likelihood, "noise"))
        # Standardized noise is small (pinned 0.01 sigma, not MLL-fitted).
        n = model.likelihood.noise.detach()
        self.assertLess(float(n.max()), 0.1)

    def test_free_noise_when_none(self):
        X, Y = history(10)
        p = Problem(bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 10.0))
        model = fit(p, X, Y)  # no error; MLL-fitted noise
        mean, _ = predict(model, [[0.5, 5.0]])
        self.assertEqual(mean.shape, (1, 2))

    def test_interpolates_history(self):
        X, Y = history(10)
        model = fit(PROB, X, Y)
        mean, _ = predict(model, X)
        for i in range(len(X)):
            self.assertAlmostEqual(mean[i][0], Y[i][0], delta=0.05)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: discover command from Task 1 Step 4.
Expected: `ImportError: cannot import name 'fit' from 'surrokit'`.

- [ ] **Step 3: Write surrokit/gp.py**

```python
"""Fixed-noise SingleTaskGP fit + posterior predict.

float64 on CPU throughout: histories are small (hundreds of rows), CPU
beats GPU including transfer, and float64 keeps optimizer paths
deterministic. The library never touches torch's global default dtype.
"""
from __future__ import annotations

import logging

import torch

from .problem import NotEnoughData, Problem

log = logging.getLogger("surrokit")

DEVICE = torch.device("cpu")


def to_f64(a) -> torch.Tensor:
    return torch.as_tensor(a, dtype=torch.float64, device=DEVICE)


def bounds_tensor(problem: Problem) -> torch.Tensor:
    lo = torch.tensor(problem.bounds_lo, dtype=torch.float64, device=DEVICE)
    hi = torch.tensor(problem.bounds_hi, dtype=torch.float64, device=DEVICE)
    return torch.stack([lo, hi], dim=0)


def fit(problem: Problem, X, Y):
    """Fit a SingleTaskGP on (X, Y). Validates shapes against the Problem;
    raises NotEnoughData below 2 rows, ValueError on any mismatch."""
    Xt, Yt = to_f64(X), to_f64(Y)
    if Xt.ndim != 2 or Yt.ndim != 2:
        raise ValueError(f"X and Y must be 2D, got {Xt.ndim}D / {Yt.ndim}D")
    if Xt.shape[0] != Yt.shape[0]:
        raise ValueError(f"X has {Xt.shape[0]} rows but Y has {Yt.shape[0]}")
    if Xt.shape[1] != problem.dim:
        raise ValueError(f"X is {Xt.shape[1]}D but problem.dim is "
                         f"{problem.dim}")
    if problem.constraint is not None and problem.constraint.axis >= Yt.shape[1]:
        raise ValueError(f"constraint.axis {problem.constraint.axis} out of "
                         f"range for {Yt.shape[1]} output axes")
    if Xt.shape[0] < 2:
        raise NotEnoughData(f"{Xt.shape[0]} history rows; need >= 2 to fit")
    return _fit_model(Xt, Yt, bounds_tensor(problem), problem.noise)


def _fit_model(X, Y, bounds, noise):
    """Fit a SingleTaskGP (input Normalize + outcome Standardize).

    noise (ABSOLUTE per-output sigma) squares into train_Yvar -> a
    fixed-noise likelihood. Left free, MLL routinely over-fits noise on
    small replicated datasets and erases real optima; clients with
    replicate-measured noise should always pin it.
    """
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    m = Y.shape[-1]
    train_Yvar = None
    if noise is not None:
        # Broadcast sigma^2 across rows: noise is a property of the
        # client's measurement budget, not the point.
        sig = torch.tensor([float(v) for v in noise[:m]],
                           dtype=Y.dtype, device=Y.device)
        train_Yvar = (sig ** 2).expand(Y.shape[0], m).contiguous()

    model = SingleTaskGP(
        train_X=X,
        train_Y=Y,
        train_Yvar=train_Yvar,
        input_transform=Normalize(d=X.shape[-1], bounds=bounds),
        outcome_transform=Standardize(m=m),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    # Noise audit: likelihood noise is standardized (x stdvs = raw);
    # fixed-noise carries (m, n) -- collapse to per-output.
    noise_t = model.likelihood.noise.detach()
    noise_std = (noise_t.reshape(-1) if noise_t.numel() == m
                 else noise_t.reshape(m, -1)[:, 0]).sqrt()
    stdvs = model.outcome_transform.stdvs.detach().reshape(-1)
    raw = [f"{v:.3e}" for v in (noise_std * stdvs).tolist()]
    src = "FIXED (problem.noise)" if train_Yvar is not None else "MLL-fitted"
    log.info("GP noise sigma per output [%s]: raw=%s standardized=%s",
             src, raw, [f"{v:.3f}" for v in noise_std.tolist()])
    return model


def predict(model, X):
    """Posterior mean and stddev at X: two numpy arrays, each (n, m)."""
    Xq = to_f64(X)
    with torch.no_grad():
        post = model.posterior(Xq)
        mean = post.mean
        sig = post.variance.clamp_min(0).sqrt()
    return mean.cpu().numpy(), sig.cpu().numpy()
```

Extend `surrokit/__init__.py`:
```python
from .gp import fit, predict
```
and add `"fit", "predict"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: discover command. Expected: all PASS (the `_fit_model` body is a verbatim port of `core/botorch_predict.py:136-180` — diff them mentally if a test fails).

- [ ] **Step 5: Commit**

```bash
git add surrokit/gp.py surrokit/__init__.py tests/test_gp.py
git commit -m "feat: fixed-noise GP fit + posterior predict

Ported from autoresearch core/botorch_predict.py:_fit_gp verbatim
(print -> logging).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 3: sampling.py — seed streams, acq optimize, cold start, emit

**Files:**
- Create: `surrokit/sampling.py`
- Test: `tests/test_sampling.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure torch/botorch).
- Produces (for Task 4/5): `sampler(seed) -> SobolQMCNormalSampler`; `optimize_acq(acq, bounds, q) -> (q, d) tensor`; `sobol_cold_start(bounds, q, seed) -> (q, d) tensor`; `emit_picks(cands, int_dims) -> list[list[float|int]]`; constants `ACQ_NUM_RESTARTS = 16`, `ACQ_RAW_SAMPLES = 512`, `ACQ_OPTIONS = {"batch_limit": 5, "maxiter": 200}`.

**Port source:** `core/botorch_predict.py:91-133` (`_sampler`, `_optimize`, `_sobol_cold_start`) and `:291-303` (`_emit_picks`). The ONLY changes: `round_idx` parameters become `seed` used verbatim (no `42 ^` — that derivation stays with the client), and `emit_picks` returns lists, not tuples.

- [ ] **Step 1: Write the failing tests**

`tests/test_sampling.py`:
```python
import unittest

import torch

from surrokit.sampling import emit_picks, sobol_cold_start

BOUNDS = torch.tensor([[0.0, 0.0], [1.0, 10.0]], dtype=torch.float64)


class TestSampling(unittest.TestCase):
    def test_cold_start_deterministic_and_in_bounds(self):
        a = sobol_cold_start(BOUNDS, q=4, seed=7)
        b = sobol_cold_start(BOUNDS, q=4, seed=7)
        c = sobol_cold_start(BOUNDS, q=4, seed=8)
        self.assertTrue(torch.equal(a, b))
        self.assertFalse(torch.equal(a, c))
        self.assertEqual(a.shape, (4, 2))
        self.assertTrue((a >= BOUNDS[0]).all() and (a <= BOUNDS[1]).all())

    def test_emit_picks_native_types_and_int_rounding(self):
        cands = torch.tensor([[0.25, 3.6], [0.75, 7.4]], dtype=torch.float64)
        out = emit_picks(cands, int_dims=[1])
        self.assertEqual(out, [[0.25, 4], [0.75, 7]])
        self.assertIsInstance(out[0][0], float)
        self.assertIsInstance(out[0][1], int)

    def test_emit_picks_no_int_dims(self):
        cands = torch.tensor([[0.5, 1.5]], dtype=torch.float64)
        self.assertEqual(emit_picks(cands, int_dims=[]), [[0.5, 1.5]])
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `ModuleNotFoundError: No module named 'surrokit.sampling'`.

- [ ] **Step 3: Write surrokit/sampling.py**

```python
"""Seeded RNG streams, shared acquisition-optimize call, Sobol cold start.

The seed is used VERBATIM in every stream. Clients that need a per-round
derivation (e.g. `42 ^ round_idx`) apply it on their side before calling.
"""
from __future__ import annotations

import torch

# Acquisition-optimization budget -- ONE tuning point for every picker.
ACQ_NUM_RESTARTS = 16
ACQ_RAW_SAMPLES = 512
ACQ_OPTIONS = {"batch_limit": 5, "maxiter": 200}


def sampler(seed: int):
    """The shared qMC sampler all acquisition pickers use."""
    from botorch.sampling.normal import SobolQMCNormalSampler
    return SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)


def optimize_acq(acq, bounds, q: int) -> torch.Tensor:
    """Shared optimize_acqf call for all acquisition pickers; returns (q, d).

    sequential=True is REQUIRED: joint mode is a ~q*d-dim problem and is
    orders of magnitude slower at q ~ 10.
    """
    from botorch.optim import optimize_acqf
    candidates, _ = optimize_acqf(
        acq_function=acq,
        bounds=bounds,
        q=q,
        num_restarts=ACQ_NUM_RESTARTS,
        raw_samples=ACQ_RAW_SAMPLES,
        options=dict(ACQ_OPTIONS),
        sequential=True,
    )
    return candidates.detach()


def sobol_cold_start(bounds: torch.Tensor, q: int, seed: int) -> torch.Tensor:
    """Draw q Sobol points over `bounds` for the no-history batch."""
    from botorch.utils.sampling import draw_sobol_samples
    cands = draw_sobol_samples(bounds=bounds, n=1, q=q, seed=seed).squeeze(0)
    return cands.detach()


def emit_picks(cands: torch.Tensor, int_dims) -> list:
    """Cast a (q, d) tensor to native-typed lists (int_dims rounded).

    Native Python types only, so results survive any JSON/msgpack layer.
    """
    int_set = set(int_dims)
    out = []
    for row in cands.cpu().numpy().tolist():
        out.append([int(round(v)) if i in int_set else float(v)
                    for i, v in enumerate(row)])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: discover command. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add surrokit/sampling.py tests/test_sampling.py
git commit -m "feat: seeded sampling helpers + shared acq optimizer

seed is used verbatim in every stream; the 42^round_idx derivation
stays with the client.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 4: pickers.py part 1 — constrained_max

**Files:**
- Create: `surrokit/pickers.py` (this task: `_constrained_max` only)
- Test: `tests/test_constrained_max.py`

**Interfaces:**
- Consumes: `Constraint`, `InfeasibleError` (Task 1); `emit_picks` NOT used here (Task 5's `ask` applies it).
- Produces: `_constrained_max(model, bounds, q, seed, pending, constraint, min_spacing=0.10, pool=16384) -> (q, d) tensor`. `model` only needs `.posterior(X)`.

**Port source:** `_budget_sob_picks` at `core/botorch_predict.py:315-398`, verbatim except: `round_idx` → `seed` (verbatim use), `flash_budget`/`k_sigma`/module constants → `constraint.min`/`constraint.k_sigma`/`min_spacing`/`pool` parameters, hard-coded output axis `1` → `constraint.axis`, `print` → `log.warning`/`log.info`, `SystemExit` → `InfeasibleError`, physics wording ("sob", "flash", "MeV/POT") → neutral ("axis-0 objective", "constrained axis", "threshold").

- [ ] **Step 1: Write the failing tests**

`tests/test_constrained_max.py`:
```python
import unittest

import torch

from surrokit import Constraint, InfeasibleError
from surrokit.pickers import _constrained_max

BOUNDS = torch.tensor([[0.0, 0.0], [1.0, 10.0]], dtype=torch.float64)


class FakePost:
    def __init__(self, mean, var):
        self.mean = mean
        self.variance = var


class RampModel:
    """mean0 = x0 (objective), mean1 = x1 (constrained axis), tiny sigma."""
    def posterior(self, X):
        mean = torch.stack([X[:, 0], X[:, 1]], dim=-1)
        var = torch.full_like(mean, 1e-6)
        return FakePost(mean, var)


class InfeasibleModel:
    """Constrained axis pinned far below any threshold."""
    def posterior(self, X):
        mean = torch.stack([X[:, 0], torch.full_like(X[:, 1], -100.0)], dim=-1)
        var = torch.full_like(mean, 1e-6)
        return FakePost(mean, var)


class TestConstrainedMax(unittest.TestCase):
    def test_feasible_picks_rank_by_axis0(self):
        c = Constraint(axis=1, min=5.0, k_sigma=1.0)
        picks = _constrained_max(RampModel(), BOUNDS, q=3, seed=0,
                                 pending=None, constraint=c)
        self.assertEqual(picks.shape, (3, 2))
        # Every pick satisfies the constraint (mean1 = x1 >= 5).
        self.assertTrue((picks[:, 1] >= 5.0 - 1e-6).all())
        # Ranked by axis-0 mean (= x0), descending -- top pick has largest x0.
        self.assertGreaterEqual(float(picks[0, 0]), float(picks[-1, 0]))

    def test_min_spacing_enforced(self):
        c = Constraint(axis=1, min=0.0, k_sigma=0.0)
        picks = _constrained_max(RampModel(), BOUNDS, q=4, seed=0,
                                 pending=None, constraint=c, min_spacing=0.2)
        norm = (picks - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0])
        for i in range(len(norm)):
            for j in range(i + 1, len(norm)):
                d = float((norm[i] - norm[j]).pow(2).sum().sqrt())
                self.assertGreaterEqual(d, 0.2 - 1e-9)

    def test_infeasible_raises(self):
        c = Constraint(axis=1, min=5.0, k_sigma=1.0)
        with self.assertRaises(InfeasibleError):
            _constrained_max(InfeasibleModel(), BOUNDS, q=2, seed=0,
                             pending=None, constraint=c)

    def test_k_ladder_relaxes_before_failing(self):
        # Threshold sits so that k=1 excludes everything but k=0 passes:
        # mean1 in [0, 10], sigma1 = 3 -> mean-1*sigma max = 7 < 9.5,
        # but mean max = 10 >= 9.5.
        class WideSigma:
            def posterior(self, X):
                mean = torch.stack([X[:, 0], X[:, 1]], dim=-1)
                var = torch.stack([torch.full_like(X[:, 0], 1e-6),
                                   torch.full_like(X[:, 1], 9.0)], dim=-1)
                return FakePost(mean, var)
        c = Constraint(axis=1, min=9.5, k_sigma=1.0)
        picks = _constrained_max(WideSigma(), BOUNDS, q=1, seed=0,
                                 pending=None, constraint=c)
        self.assertEqual(picks.shape, (1, 2))

    def test_deterministic_per_seed(self):
        c = Constraint(axis=1, min=2.0, k_sigma=1.0)
        a = _constrained_max(RampModel(), BOUNDS, q=2, seed=3,
                             pending=None, constraint=c)
        b = _constrained_max(RampModel(), BOUNDS, q=2, seed=3,
                             pending=None, constraint=c)
        self.assertTrue(torch.equal(a, b))
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `ModuleNotFoundError: No module named 'surrokit.pickers'`.

- [ ] **Step 3: Write surrokit/pickers.py (constrained_max only)**

```python
"""Pickers: acquisition strategies over a fitted GP.

All pickers return raw (q, d) tensors; ask() (Task 5) applies int-dim
rounding via sampling.emit_picks.
"""
from __future__ import annotations

import logging

import torch

from .problem import Constraint, InfeasibleError

log = logging.getLogger("surrokit")


def _constrained_max(model, bounds, q: int, seed: int, pending,
                     constraint: Constraint, min_spacing: float = 0.10,
                     pool: int = 16384) -> torch.Tensor:
    """The q highest-axis-0 points the GP believes satisfy the constraint.

    Feasibility is mean[axis] - k_sigma*sigma[axis] >= min -- k-sigma,
    not mean-only, because a pick whose TRUE value lands past the
    threshold contributes nothing. The k-relaxation ladder (k -> k/2 ->
    0) trades margin for a full batch rather than returning fewer than q
    picks. pending rows seed the min-distance filter (NOT returned).
    """
    from scipy.stats import qmc

    ax = constraint.axis
    thr = float(constraint.min)
    k = float(constraint.k_sigma)

    d = bounds.shape[-1]
    unit = qmc.Sobol(d=d, scramble=True, seed=seed).random(pool)
    lo = bounds[0].cpu().numpy()
    hi = bounds[1].cpu().numpy()
    Xs = torch.tensor(lo + unit * (hi - lo), dtype=bounds.dtype,
                      device=bounds.device)
    with torch.no_grad():
        post = model.posterior(Xs)
        mean = post.mean
        std = post.variance.clamp_min(0).sqrt()
    obj = mean[:, 0]
    feas_margin = mean[:, ax] - k * std[:, ax]

    # Relax k rather than return an empty batch.
    used_k = k
    feasible = feas_margin >= thr
    for relaxed in (k * 0.5, 0.0):
        if int(feasible.sum()) >= q:
            break
        used_k = relaxed
        feasible = (mean[:, ax] - relaxed * std[:, ax]) >= thr
    n_feas = int(feasible.sum())
    if used_k != k:
        log.warning("constrained_max: only %d candidates at k=%ssigma; "
                    "relaxed to k=%ssigma (%d candidates)",
                    int((feas_margin >= thr).sum()), k, used_k, n_feas)
    if n_feas == 0:
        raise InfeasibleError(
            f"no candidate in the search box satisfies axis-{ax} >= "
            f"{thr:.6g} even at k=0; the threshold is wrong or the box "
            "has moved off the feasible region")

    idx_feas = torch.nonzero(feasible, as_tuple=False).squeeze(-1)
    order = idx_feas[torch.argsort(obj[idx_feas], descending=True)]
    norm = (Xs - bounds[0]) / (bounds[1] - bounds[0])
    avoid = []
    if pending is not None and len(pending):
        avoid = list((pending - bounds[0]) / (bounds[1] - bounds[0]))
    picks: list[int] = []
    for idx in order.tolist():
        if len(picks) >= q:
            break
        dmin = min((float((norm[idx] - a).pow(2).sum().sqrt())
                    for a in avoid), default=float("inf"))
        if dmin >= min_spacing:
            picks.append(idx)
            avoid.append(norm[idx])
    # Top up ONLY from the feasible set -- never leak infeasible picks.
    if len(picks) < q:
        for idx in order.tolist():
            if idx not in picks:
                picks.append(idx)
            if len(picks) >= q:
                break
    sel = torch.tensor(picks[:q])
    log.info("constrained_max: %d/%d candidates feasible at k=%ssigma "
             "(axis-%d >= %.6g); picked q=%d, predicted axis-0 "
             "%.3f-%.3f", n_feas, pool, used_k, ax, thr, len(sel),
             float(obj[sel].min()), float(obj[sel].max()))
    return Xs[sel].detach()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: discover command. Expected: all PASS. If `test_feasible_picks_rank_by_axis0` fails on ordering, check the port against `core/botorch_predict.py:370-392` line by line — the argsort/spacing/top-up flow must be structurally identical (parity in Task 7 depends on it).

- [ ] **Step 5: Commit**

```bash
git add surrokit/pickers.py tests/test_constrained_max.py
git commit -m "feat: constrained_max picker (k-ladder, InfeasibleError)

Ported from autoresearch _budget_sob_picks; physics-neutral axis and
threshold, SystemExit -> InfeasibleError.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 5: pickers.py part 2 — acquisition pickers + ask()

**Files:**
- Modify: `surrokit/pickers.py`, `surrokit/__init__.py`
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: `_fit_model`, `bounds_tensor`, `to_f64` (Task 2); `sampler`, `optimize_acq`, `sobol_cold_start`, `emit_picks`, `ACQ_NUM_RESTARTS`, `ACQ_RAW_SAMPLES`, `ACQ_OPTIONS` (Task 3); `_constrained_max` (Task 4).
- Produces: `ask(problem, X, Y, q=5, picker="hybrid", seed=0, pending=None, min_spacing=0.10, pool=16384, hv_frac=0.6) -> list[list[float]]`; `PICKER_CHOICES = ("qnehvi", "qlnei", "qnparego", "hybrid", "constrained_max")`. Both exported from `surrokit`.

**Port source:** `_qnehvi_picks`/`_qlnei_picks`/`_qnparego_picks`/`_hybrid_picks` at `core/botorch_predict.py:183-288` verbatim except: `round_idx` → `seed` (used verbatim — `_sampler(round_idx)` becomes `sampler(seed)`, `torch.manual_seed(_seed(round_idx))` becomes `torch.manual_seed(seed)`), hybrid's env read becomes the `hv_frac` parameter, `x_pending` → `pending`. The qnparego per-candidate loop, its growing-pending discipline, and the qnehvi ref-point formula must be byte-for-byte structurally identical — parity depends on operation order.

- [ ] **Step 1: Write the failing tests**

`tests/test_ask.py`:
```python
import unittest

from surrokit import Constraint, Problem, ask
from tests.common import PROB, PROB_C, history, in_bounds


class TestAskColdStart(unittest.TestCase):
    def test_cold_start_below_two_rows(self):
        for X, Y in (([], []), ([[0.5, 5.0]], [[1.0, 2.0]])):
            picks = ask(PROB, X, Y, q=3, picker="hybrid", seed=1)
            self.assertEqual(len(picks), 3)
            for row in picks:
                self.assertTrue(in_bounds(row))
                self.assertIsInstance(row[1], int)  # int_dims rounded

    def test_cold_start_deterministic(self):
        a = ask(PROB, [], [], q=2, seed=5)
        b = ask(PROB, [], [], q=2, seed=5)
        self.assertEqual(a, b)


class TestAskValidation(unittest.TestCase):
    def test_unknown_picker(self):
        X, Y = history(10)
        with self.assertRaises(ValueError):
            ask(PROB, X, Y, picker="nope")

    def test_multiobj_pickers_require_m2(self):
        X, Y = history(10)
        Y1 = [[r[0]] for r in Y]
        for p in ("qnehvi", "qnparego", "hybrid"):
            with self.assertRaises(ValueError):
                ask(PROB, X, Y1, picker=p)

    def test_constrained_max_requires_constraint(self):
        X, Y = history(10)
        with self.assertRaises(ValueError):
            ask(PROB, X, Y, picker="constrained_max")
        bad = Problem(bounds_lo=(0.0, 0.0), bounds_hi=(1.0, 10.0),
                      constraint=Constraint(axis=2, min=0.0))
        with self.assertRaises(ValueError):
            ask(bad, X, Y, picker="constrained_max")

    def test_pending_dim_mismatch(self):
        X, Y = history(10)
        with self.assertRaises(ValueError):
            ask(PROB, X, Y, pending=[[0.5]])


class TestAskPickers(unittest.TestCase):
    def _smoke(self, picker, **kw):
        X, Y = history(10)
        picks = ask(PROB if picker != "constrained_max" else PROB_C,
                    X, Y, q=2, picker=picker, seed=0, **kw)
        self.assertEqual(len(picks), 2)
        for row in picks:
            self.assertTrue(in_bounds(row))
            self.assertIsInstance(row[1], int)
        return picks

    def test_qnehvi(self):
        self._smoke("qnehvi")

    def test_qlnei_accepts_1d_y(self):
        X, Y = history(10)
        Y1 = [[r[0]] for r in Y]
        picks = ask(PROB, X, Y1, q=2, picker="qlnei", seed=0)
        self.assertEqual(len(picks), 2)

    def test_qnparego(self):
        self._smoke("qnparego")

    def test_hybrid_and_hv_frac_zero_is_pure_parego(self):
        self._smoke("hybrid")
        X, Y = history(10)
        pure = ask(PROB, X, Y, q=2, picker="hybrid", seed=0, hv_frac=0.0)
        parego = ask(PROB, X, Y, q=2, picker="qnparego", seed=0)
        self.assertEqual(pure, parego)

    def test_constrained_max_through_ask(self):
        self._smoke("constrained_max")

    def test_seed_determinism_qlnei(self):
        X, Y = history(10)
        Y1 = [[r[0]] for r in Y]
        a = ask(PROB, X, Y1, q=2, picker="qlnei", seed=9)
        b = ask(PROB, X, Y1, q=2, picker="qlnei", seed=9)
        self.assertEqual(a, b)

    def test_pending_accepted(self):
        X, Y = history(10)
        picks = ask(PROB, X, Y, q=2, picker="qnehvi", seed=0,
                    pending=[[0.5, 5.0]])
        self.assertEqual(len(picks), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `ImportError: cannot import name 'ask' from 'surrokit'`.

- [ ] **Step 3: Append the acquisition pickers + ask() to surrokit/pickers.py**

```python
from .gp import _fit_model, bounds_tensor, to_f64
from .problem import Problem
from .sampling import (ACQ_NUM_RESTARTS, ACQ_OPTIONS, ACQ_RAW_SAMPLES,
                       emit_picks, sampler, sobol_cold_start)

PICKER_CHOICES = ("qnehvi", "qlnei", "qnparego", "hybrid", "constrained_max")


def _qnehvi(model, X, Y, bounds, q: int, seed: int, pending=None):
    """qLogNEHVI (log-stabilized qNEHVI, Ament 2023) for q candidates.

    pending: optional (k, d) in-flight rows; the acqf fantasizes over
    them so replacements don't re-pick a running point.
    """
    from botorch.acquisition.multi_objective.logei import (
        qLogNoisyExpectedHypervolumeImprovement,
    )

    # Ref point = observed nadir pushed out 10% of span; subtract the
    # offset (sign-robust -- "x 1.1" only works when nadir is negative).
    nadir = Y.min(dim=0).values
    span = (Y.max(dim=0).values - nadir).abs().clamp(min=1e-9)
    ref_point = (nadir - 0.1 * span).tolist()

    acq = qLogNoisyExpectedHypervolumeImprovement(
        model=model,
        ref_point=ref_point,
        X_baseline=X,
        sampler=sampler(seed),
        prune_baseline=True,
        X_pending=pending,
    )
    return optimize_acq(acq, bounds, q)


def _qlnei(model, X, bounds, q: int, seed: int, pending=None):
    """qLogNoisyExpectedImprovement over axis 0 only."""
    from botorch.acquisition.logei import qLogNoisyExpectedImprovement

    acq = qLogNoisyExpectedImprovement(
        model=model,
        X_baseline=X,
        sampler=sampler(seed),
        prune_baseline=True,
        X_pending=pending,
    )
    return optimize_acq(acq, bounds, q)


def _qnparego(model, X, Y, bounds, q: int, seed: int, pending=None):
    """qNParEGO: qLogNEI over a fresh random Chebyshev scalarization per
    candidate -- fans the batch across the WHOLE front.

    Seed discipline: weights drawn inside ONE torch.manual_seed(seed)
    block -- DISTINCT per candidate, REPRODUCIBLE per seed.
    Sequential-greedy via a growing pending set; can't use the shared
    optimize_acq (per-candidate scalarization). pending rows are
    conditioned on but NOT returned.
    """
    from botorch.acquisition.logei import qLogNoisyExpectedImprovement
    from botorch.acquisition.objective import GenericMCObjective
    from botorch.utils.multi_objective.scalarization import (
        get_chebyshev_scalarization,
    )
    from botorch.utils.sampling import sample_simplex
    from botorch.optim import optimize_acqf

    torch.manual_seed(seed)
    pend = [pending] if pending is not None else []
    picks = []
    for _ in range(q):
        w = sample_simplex(d=Y.shape[-1], n=1, dtype=Y.dtype).squeeze(0)
        obj = GenericMCObjective(get_chebyshev_scalarization(weights=w, Y=Y))
        acq = qLogNoisyExpectedImprovement(
            model=model, X_baseline=X, sampler=sampler(seed),
            objective=obj, prune_baseline=True,
            X_pending=torch.cat(pend) if pend else None,
        )
        cand, _ = optimize_acqf(
            acq_function=acq, bounds=bounds, q=1,
            num_restarts=ACQ_NUM_RESTARTS, raw_samples=ACQ_RAW_SAMPLES,
            options=dict(ACQ_OPTIONS),
        )
        pend.append(cand)
        picks.append(cand)
    return torch.cat(picks).detach()


def _hybrid(model, X, Y, bounds, q: int, seed: int, pending=None,
            hv_frac: float = 0.6):
    """One batch = hv_frac qnehvi + rest qnparego; parego conditions on
    the qnehvi picks via pending so the halves don't collide."""
    q_hv = min(q, max(0, round(hv_frac * q)))
    q_pe = q - q_hv
    if q_hv == 0:
        return _qnparego(model, X, Y, bounds, q=q, seed=seed,
                         pending=pending)
    hv_cands = _qnehvi(model, X, Y, bounds, q=q_hv, seed=seed,
                       pending=pending)
    pe_pending = (torch.cat([pending, hv_cands])
                  if pending is not None else hv_cands)
    if q_pe == 0:
        return hv_cands
    pe_cands = _qnparego(model, X, Y, bounds, q=q_pe, seed=seed,
                         pending=pe_pending)
    return torch.cat([hv_cands, pe_cands])


def ask(problem: Problem, X, Y, q: int = 5, picker: str = "hybrid",
        seed: int = 0, pending=None, min_spacing: float = 0.10,
        pool: int = 16384, hv_frac: float = 0.6) -> list:
    """STATELESS batch proposal: fits the GP internally on every call.

    seed is used verbatim in every RNG stream. n < 2 rows -> Sobol cold
    start (never an error). int_dims are rounded in the returned lists.
    """
    if picker not in PICKER_CHOICES:
        raise ValueError(f"unknown picker {picker!r}; choose from "
                         f"{PICKER_CHOICES}")
    bounds = bounds_tensor(problem)
    Xt = (to_f64(X) if len(X)
          else torch.empty((0, problem.dim), dtype=torch.float64))
    pend = None
    if pending:
        pend = to_f64([[float(v) for v in row] for row in pending])
        if pend.shape[-1] != problem.dim:
            raise ValueError(f"pending dim {pend.shape[-1]} != problem "
                             f"dim {problem.dim}")
    if Xt.shape[0] < 2:
        log.info("cold start: %d history rows < 2 -> Sobol draw "
                 "(q=%d, seed=%d)", Xt.shape[0], q, seed)
        return emit_picks(sobol_cold_start(bounds, q, seed),
                          problem.int_dims)
    Yt = to_f64(Y)
    if Yt.ndim != 2 or Yt.shape[0] != Xt.shape[0]:
        raise ValueError(f"Y must be 2D with {Xt.shape[0]} rows")
    m = Yt.shape[1]
    if picker in ("qnehvi", "qnparego", "hybrid") and m < 2:
        raise ValueError(f"picker {picker!r} requires m >= 2 output "
                         f"axes, got {m}")
    if picker == "constrained_max":
        c = problem.constraint
        if c is None:
            raise ValueError("constrained_max requires problem.constraint")
        if c.axis >= m:
            raise ValueError(f"constraint.axis {c.axis} out of range for "
                             f"{m} output axes")
    model = _fit_model(Xt, Yt, bounds, problem.noise)
    if picker == "qlnei":
        cands = _qlnei(model, Xt, bounds, q=q, seed=seed, pending=pend)
    elif picker == "constrained_max":
        cands = _constrained_max(model, bounds, q=q, seed=seed,
                                 pending=pend, constraint=problem.constraint,
                                 min_spacing=min_spacing, pool=pool)
    elif picker == "hybrid":
        cands = _hybrid(model, Xt, Yt, bounds, q=q, seed=seed,
                        pending=pend, hv_frac=hv_frac)
    elif picker == "qnparego":
        cands = _qnparego(model, Xt, Yt, bounds, q=q, seed=seed,
                          pending=pend)
    else:
        cands = _qnehvi(model, Xt, Yt, bounds, q=q, seed=seed,
                        pending=pend)
    return emit_picks(cands, problem.int_dims)
```

Extend `surrokit/__init__.py`:
```python
from .pickers import PICKER_CHOICES, ask
```
and add `"PICKER_CHOICES", "ask"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: discover command (whole suite). Expected: all PASS. These tests fit real GPs — the suite takes O(1 min).

- [ ] **Step 5: Commit**

```bash
git add surrokit/pickers.py surrokit/__init__.py tests/test_ask.py
git commit -m "feat: acquisition pickers + stateless ask()

qnehvi/qlnei/qnparego/hybrid ported verbatim from autoresearch
(round_idx -> verbatim seed; hv_frac env read -> parameter).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 6: MCP scaffold + README + CI

**Files:**
- Create: `surrokit/mcp_scaffold.py`, `README.md`, `.github/workflows/test.yml`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: `Problem`, `fit`, `predict`, `ask`, `PICKER_CHOICES`.
- Produces: `Adapter` protocol (`problems() -> dict[str, Problem]`, `history(name) -> tuple[list, list, dict]`); `make_server(adapter, name="surrokit", instructions=..., middleware=None) -> MCPServer` with tools `list_problems`, `predict`, `suggest`, `stats`, `refit`. Task 9's `AutoresearchAdapter` implements the protocol.

- [ ] **Step 1: Write the failing tests**

`tests/test_scaffold.py`:
```python
import asyncio
import unittest

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

from tests.common import PROB, PROB_C, history


class DictAdapter:
    def __init__(self):
        self._h = {"toy": history(10), "ctoy": history(10)}

    def problems(self):
        return {"toy": PROB, "ctoy": PROB_C}

    def history(self, name):
        X, Y = self._h[name]
        return X, Y, {"note": f"meta-for-{name}"}


@unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
class TestScaffold(unittest.TestCase):
    def setUp(self):
        from surrokit.mcp_scaffold import make_server
        self.server = make_server(DictAdapter())

    def test_tool_names(self):
        tools = asyncio.run(self.server.list_tools())
        names = sorted(t.name for t in tools)
        self.assertEqual(names, ["list_problems", "predict", "refit",
                                 "stats", "suggest"])

    def test_call_list_problems(self):
        result = asyncio.run(self.server.call_tool("list_problems", {}))
        # MCPServer.call_tool returns (content, structured) tuple in mcp 2.0
        structured = result[1]
        self.assertIn("toy", structured)
        self.assertEqual(structured["toy"]["dims"], 2)
        self.assertEqual(structured["toy"]["n_rows"], 10)

    def test_call_predict(self):
        result = asyncio.run(self.server.call_tool(
            "predict", {"problem": "toy", "points": [[0.5, 5.0]]}))
        structured = result[1]
        self.assertEqual(len(structured["mean"]), 1)
        self.assertEqual(len(structured["mean"][0]), 2)
        self.assertEqual(len(structured["sigma"][0]), 2)

    def test_call_suggest(self):
        result = asyncio.run(self.server.call_tool(
            "suggest", {"problem": "toy", "q": 2, "picker": "qlnei",
                        "seed": 0}))
        structured = result[1]
        picks = structured["result"] if isinstance(structured, dict) else structured
        self.assertEqual(len(picks), 2)

    def test_call_stats_merges_meta(self):
        result = asyncio.run(self.server.call_tool("stats",
                                                   {"problem": "ctoy"}))
        structured = result[1]
        self.assertEqual(structured["n_rows"], 10)
        self.assertEqual(structured["note"], "meta-for-ctoy")

    def test_refit_returns_row_count(self):
        result = asyncio.run(self.server.call_tool("refit",
                                                   {"problem": "toy"}))
        self.assertEqual(result[1]["n_rows"], 10)


class TestLazyImport(unittest.TestCase):
    def test_surrokit_import_never_needs_mcp(self):
        import surrokit  # noqa: F401  -- must not raise even without mcp
```

Note for the implementer: if `self.server.call_tool(...)` has a different return shape in the installed mcp SDK, adapt the `structured = ...` lines to the actual API (`mcp.server.mcpserver.MCPServer` — inspect `/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/lib/python3.12/site-packages/mcp/server/mcpserver.py`). The assertions on tool names and payload contents are the contract; the unwrapping is incidental. Known mcp 2.0 facts: `structured_output=True` requires typed return annotations (bare `dict` is rejected); list returns arrive wrapped under a `"result"` key.

- [ ] **Step 2: Run tests to verify they fail**

Expected: `ModuleNotFoundError: No module named 'surrokit.mcp_scaffold'`.

- [ ] **Step 3: Write surrokit/mcp_scaffold.py**

```python
"""MCP server factory: expose any Adapter's problems over the engine.

Import of THIS module requires the optional `mcp` dependency; importing
`surrokit` itself never does.
"""
from __future__ import annotations

from typing import Any, Protocol

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as e:  # pragma: no cover
    raise ImportError(
        'surrokit.mcp_scaffold requires the "mcp" package: '
        'pip install "mcp>=2.0"') from e

from .gp import fit, predict as gp_predict
from .pickers import PICKER_CHOICES, ask
from .problem import Problem

DEFAULT_INSTRUCTIONS = (
    "Generic GP surrogate engine (surrokit). Problems are named search "
    "spaces with observed history; every output axis is maximized and "
    "axis 0 is the primary objective. predict() gives posterior "
    "mean/sigma per axis; suggest() proposes new points via the "
    f"production pickers {PICKER_CHOICES}. Call list_problems first. "
    "Pure computation -- nothing is submitted or written anywhere."
)


class Adapter(Protocol):
    def problems(self) -> dict[str, Problem]: ...
    def history(self, name: str) -> tuple[list, list, dict]: ...


def make_server(adapter: Adapter, name: str = "surrokit",
                instructions: str = DEFAULT_INSTRUCTIONS,
                middleware=None) -> MCPServer:
    kwargs: dict[str, Any] = {"name": name, "instructions": instructions}
    if middleware is not None:
        kwargs["middleware"] = middleware
    server = MCPServer(**kwargs)

    # problem name -> (model, n_rows_at_fit). Append-only-history
    # assumption: same row count == same data. refit() is the escape
    # hatch when a client rewrites history in place.
    cache: dict[str, tuple[object, int]] = {}

    def _resolve(pname: str) -> tuple[Problem, list, list, dict]:
        problems = adapter.problems()
        if pname not in problems:
            raise ValueError(f"unknown problem {pname!r}; choose from "
                             f"{sorted(problems)}")
        X, Y, meta = adapter.history(pname)
        return problems[pname], X, Y, meta

    def _fitted(pname: str, refresh: bool = False):
        problem, X, Y, meta = _resolve(pname)
        n = len(X)
        c = cache.get(pname)
        if c is not None and c[1] == n and not refresh:
            return c[0], n, meta
        model = fit(problem, X, Y)
        cache[pname] = (model, n)
        return model, n, meta

    @server.tool(structured_output=True)
    def list_problems() -> dict[str, Any]:
        """Named problems: dims, bounds, integer dims, output-axis count,
        history row counts."""
        out: dict[str, Any] = {}
        for pname, prob in sorted(adapter.problems().items()):
            X, Y, _ = adapter.history(pname)
            out[pname] = {
                "dims": prob.dim,
                "bounds_lo": list(prob.bounds_lo),
                "bounds_hi": list(prob.bounds_hi),
                "int_dims": list(prob.int_dims),
                "axes": (len(Y[0]) if Y else None),
                "n_rows": len(X),
                "constrained": prob.constraint is not None,
            }
        return out

    @server.tool(structured_output=True)
    def predict(problem: str, points: list[list[float]]) -> dict[str, Any]:
        """Posterior mean and sigma per output axis at each point."""
        model, _, _ = _fitted(problem)
        mean, sigma = gp_predict(model, points)
        return {"mean": mean.tolist(), "sigma": sigma.tolist()}

    @server.tool(structured_output=True)
    def suggest(problem: str, q: int = 5, picker: str = "hybrid",
                seed: int = 0,
                pending: list[list[float]] | None = None,
                min_spacing: float = 0.10,
                hv_frac: float = 0.6) -> list[list[float]]:
        """Propose q new points (stateless ask over the current history).
        pending: x-rows already in flight, to steer picks away from."""
        prob, X, Y, _ = _resolve(problem)
        return ask(prob, X, Y, q=q, picker=picker, seed=seed,
                   pending=pending, min_spacing=min_spacing,
                   hv_frac=hv_frac)

    @server.tool(structured_output=True)
    def stats(problem: str) -> dict[str, Any]:
        """History row count plus whatever metadata the adapter serves."""
        _, X, _, meta = _resolve(problem)
        out: dict[str, Any] = {"problem": problem, "n_rows": len(X)}
        out.update(meta)
        return out

    @server.tool(structured_output=True)
    def refit(problem: str) -> dict[str, Any]:
        """Bypass the fit cache and refit on the current history."""
        _, n, _ = _fitted(problem, refresh=True)
        return {"problem": problem, "n_rows": n, "refitted": True}

    return server
```

- [ ] **Step 4: Run tests to verify they pass**

Run: discover command. Expected: all PASS under ana 2.8.0 (mcp present). Fix any call_tool unwrapping per the Step 1 note before touching the scaffold itself.

- [ ] **Step 5: Write README.md and CI workflow**

`README.md`:
````markdown
# surrokit

Generic ask/tell GP surrogate engine: botorch `fit` / `predict` / `ask`
with budget-constrained pickers, plus an MCP server scaffold.

The engine sees only numbers. Every output axis is **maximized**; axis 0
is the primary objective. Clients transform on their side (negate to
minimize, log to tame dynamic range) and keep their units to themselves.

## Install

```bash
pip install "git+https://github.com/oksuzian/surrokit"   # or a checkout
pip install "surrokit[mcp]"                              # + MCP scaffold
```

## Minimize a metric under a budget (5 lines of client code)

Maximize objective `f`, keep metric `g <= budget` — feed the engine
`-log10(g)` and constrain it above `-log10(budget)`:

```python
from surrokit import Problem, Constraint, ask
prob = Problem(bounds_lo=(0, 0), bounds_hi=(1, 10),
               constraint=Constraint(axis=1, min=-math.log10(budget)))
Y = [[f_i, -math.log10(g_i)] for f_i, g_i in observations]
picks = ask(prob, X, Y, q=5, picker="constrained_max", seed=run_seed)
```

## API

- `Problem(bounds_lo, bounds_hi, int_dims=(), noise=None, constraint=None)`
  — search box; `noise` = ABSOLUTE per-axis sigma (pins a fixed-noise GP;
  strongly recommended when you have replicate measurements).
- `fit(problem, X, Y) -> model`; `predict(model, X) -> (mean, sigma)`.
- `ask(problem, X, Y, q=5, picker="hybrid", seed=0, pending=None,
  min_spacing=0.10, pool=16384, hv_frac=0.6)` — **stateless** (refits per
  call). Pickers: `qnehvi | qlnei | qnparego | hybrid | constrained_max`.
  `seed` is used verbatim in every RNG stream. Fewer than 2 rows falls
  back to a Sobol draw.
- `surrokit.mcp_scaffold.make_server(adapter)` — MCP server over any
  `Adapter` (`problems()`, `history(name)`); tools `list_problems`,
  `predict`, `suggest`, `stats`, `refit`; `middleware=` forwards to
  `MCPServer`.

Library discipline: no prints (logger `"surrokit"`), no env reads, no
`sys.exit` — `InfeasibleError` / `NotEnoughData` / `ValueError` instead.
````

`.github/workflows/test.yml`:
```yaml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install torch --index-url https://download.pytorch.org/whl/cpu
      - run: pip install -e ".[mcp]"
      - run: python -m unittest discover -s tests -t . -v
```

- [ ] **Step 6: Run the full surrokit suite one more time**

Run: discover command. Expected: all PASS.

- [ ] **Step 7: Commit and record the pin SHA**

```bash
git add surrokit/mcp_scaffold.py tests/test_scaffold.py README.md .github/workflows/test.yml
git commit -m "feat: MCP server scaffold + README + CI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
git rev-parse HEAD   # <- record this SHA; Task 7's commit message pins it
```

---

### Task 7: autoresearch — SURROKIT_ROOT seam + bit-parity gate

**Working directory from here on:** `/exp/mu2e/app/users/oksuzian/autoresearch` (branch `readme-slim`).

**Files:**
- Modify: `core/paths.py` (add `SURROKIT_ROOT`), `activate.sh` (one comment block)
- Test: `tests/test_surrokit_parity.py` (new — the gate; retired in Task 8)

**Interfaces:**
- Consumes: the full surrokit API (Tasks 1–6); autoresearch `bp.compute_explore_picks`, `bp._load_history_tensor`, `bp._seed`, `bp.DEP_FLASH_PER_POT`, `bp.BUDGET_SOB_K_SIGMA` (all still the OLD implementations); fixture helpers `write_fixture`, `patched_leaderboard` from `tests/test_botorch_predict.py`.
- Produces: `paths.SURROKIT_ROOT: Path` (env `AUTORESEARCH_SURROKIT` override, default `REPO_ROOT.parent / "surrokit"`). Tasks 8–9 import surrokit via `sys.path.insert(0, str(paths.SURROKIT_ROOT))`.

- [ ] **Step 1: Add the seam to core/paths.py**

Append (match the file's existing style for env-overridable paths):
```python
# Sibling surrokit checkout (the generic ask/tell engine). Overridable so
# tests and other operators can point at a different checkout.
SURROKIT_ROOT = Path(os.environ.get("AUTORESEARCH_SURROKIT")
                     or REPO_ROOT.parent / "surrokit")
```
(If `core/paths.py` does not already `import os`, add it.) Add a comment block to `activate.sh` near the other env documentation:
```bash
# AUTORESEARCH_SURROKIT: path to the surrokit engine checkout
# (default: the repo's sibling directory ../surrokit; see core/paths.py).
```

- [ ] **Step 2: Write the parity gate test**

`tests/test_surrokit_parity.py`:
```python
"""BIT-PARITY GATE: old compute_explore_picks vs surrokit.ask.

Retired (deleted) in the same commit that rewires compute_explore_picks
to call surrokit -- after that the comparison is trivially self-vs-self.
Runs on the small in-repo fixtures where the hybrid/scipy ABNORMAL-retry
nondeterminism (wiki incident) is invisible.
"""
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import paths  # noqa: E402

sys.path.insert(0, str(paths.SURROKIT_ROOT))
import surrokit  # noqa: E402

import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402

from tests.test_botorch_predict import patched_leaderboard  # noqa: E402

MODE = "foilsflash"


def _problem(sob_only=False, constraint=None):
    spec = _modes.SPECS[MODE]
    return surrokit.Problem(
        bounds_lo=tuple(spec.bounds_lo),
        bounds_hi=tuple(spec.bounds_hi),
        int_dims=tuple(spec.int_dims),
        noise=tuple(spec.obs_noise),
        constraint=constraint,
    )


class TestBitParity(unittest.TestCase):
    def _compare(self, picker, *, q=2, round_idx=0, pending=None,
                 sob_only=False, constraint=None, sk_picker=None):
        old = bp.compute_explore_picks(MODE, q=q, round_idx=round_idx,
                                       picker=picker, x_pending=pending)
        X, Y, _, _ = bp._load_history_tensor(MODE, sob_only=sob_only)
        new = surrokit.ask(_problem(sob_only, constraint),
                           X.tolist(), Y.tolist(), q=q,
                           picker=sk_picker or picker,
                           seed=bp._seed(round_idx), pending=pending)
        self.assertEqual([list(t) for t in old], new,
                         f"parity broken for picker={picker}")

    def test_qnehvi(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qnehvi")

    def test_qnehvi_nonzero_round_and_pending(self):
        spec = _modes.SPECS[MODE]
        mid = [ (lo + hi) / 2.0 for lo, hi in
                zip(spec.bounds_lo, spec.bounds_hi) ]
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qnehvi", round_idx=3, pending=[mid])

    def test_qlnei(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("qlnei", sob_only=True)

    def test_hybrid(self):
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            self._compare("hybrid")

    def test_budget_sob_as_constrained_max(self):
        budget = 1.0e-3  # generous: fixture flash values are well inside
        c = surrokit.Constraint(axis=1, min=-math.log10(budget),
                                k_sigma=bp.BUDGET_SOB_K_SIGMA)
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp), \
             mock.patch.object(bp, "DEP_FLASH_PER_POT", budget):
            self._compare("budget_sob", constraint=c,
                          sk_picker="constrained_max")

    def test_cold_start(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patched_leaderboard(tmp, header_only=True):
            self._compare("qnehvi", q=4, round_idx=1)
```

Adapt the `patched_leaderboard` import/usage to the helper's actual signature in `tests/test_botorch_predict.py:25-52` (it writes a 10-row foilsflash fixture and patches the mode's leaderboard path). If the helper needs the mode object rather than a context manager, mirror how `TestComputeExplorePicks` uses it.

- [ ] **Step 3: Run the gate**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_surrokit_parity -v`
Expected: ALL PASS — picks bit-identical. **If any parity test fails, STOP: do not proceed to Task 8.** Diff the surrokit port against `core/botorch_predict.py` for the failing picker; the usual suspects are operation order, a missed `dict(ACQ_OPTIONS)` copy, seed placement, or a dtype divergence (both sides must be float64 end to end — note the autoresearch process sets `torch.set_default_dtype(torch.float64)` at `botorch_predict` import, which also covers surrokit's calls in-process).

- [ ] **Step 4: Run the full autoresearch suite**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: everything green (685 + the new parity tests).

- [ ] **Step 5: Commit (pin the surrokit SHA in the message)**

```bash
git add core/paths.py activate.sh tests/test_surrokit_parity.py
git commit -m "test: surrokit bit-parity gate + SURROKIT_ROOT seam

surrokit pinned at <SHA from Task 6 Step 7>. Parity: qnehvi, qlnei,
hybrid, budget_sob->constrained_max, cold start -- all bit-identical
on the 10-row fixture.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 8: rewire compute_explore_picks to surrokit (CLI frozen)

**Files:**
- Modify: `core/botorch_predict.py` (`compute_explore_picks` + `main` only — do NOT delete the old picker bodies yet; Task 10 does)
- Delete: `tests/test_surrokit_parity.py` (gate passed; comparison is now self-vs-self)

**Interfaces:**
- Consumes: `paths.SURROKIT_ROOT` (Task 7), `surrokit.ask`, `surrokit.Problem`, `surrokit.Constraint`, `surrokit.InfeasibleError`.
- Produces: `compute_explore_picks(mode, q=5, round_idx=0, picker="qnehvi", x_pending=None) -> list[tuple]` — signature and return type UNCHANGED (callers: `graph/closed_loop.py` CLI round-trip, `surrogate.suggest`, tests).

- [ ] **Step 1: Re-run the parity gate one final time**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_surrokit_parity -v`
Expected: PASS (this is the last run against the old implementation).

- [ ] **Step 2: Rewire compute_explore_picks**

In `core/botorch_predict.py`, add near the other imports (after the `modes` import):
```python
sys.path.insert(0, str(Path(__file__).resolve().parent))  # already present
from paths import SURROKIT_ROOT  # noqa: E402
sys.path.insert(0, str(SURROKIT_ROOT))
import surrokit  # noqa: E402
```
Replace the body of `compute_explore_picks` (keep docstring + signature):
```python
def compute_explore_picks(mode: str,
                          q: int = 5,
                          round_idx: int = 0,
                          picker: str = "qnehvi",
                          x_pending: list | None = None,
                          ) -> list[tuple]:
    """Explore-pick engine: picker = qnehvi | qlnei | budget_sob | hybrid.

    Thin glue over surrokit.ask: this side owns leaderboard loading, the
    -log10 transform, env-tunable constants, and the 42^round_idx seed
    convention; the engine owns the GP and the pickers.
    """
    X, Y, bounds, int_dims = _load_history_tensor(mode, sob_only=(picker == "qlnei"))
    if x_pending:
        pend_width = len(x_pending[0])
        if pend_width != bounds.shape[-1]:
            raise SystemExit(
                f"[botorch_predict] x_pending dim {pend_width} != "
                f"search-space dim {bounds.shape[-1]} for mode={mode}")
    if X.shape[0] < 2:
        print(f"[botorch_predict] mode={mode} cold-start: history={X.shape[0]} rows "
              f"< 2 -> Sobol draw (q={q}, round_idx={round_idx})", flush=True)
    spec = _modes.SPECS[mode]
    constraint = None
    sk_picker = picker
    if picker == "budget_sob":
        sk_picker = "constrained_max"
        constraint = surrokit.Constraint(
            axis=1, min=-math.log10(DEP_FLASH_PER_POT),
            k_sigma=BUDGET_SOB_K_SIGMA)
    problem = surrokit.Problem(
        bounds_lo=tuple(spec.bounds_lo), bounds_hi=tuple(spec.bounds_hi),
        int_dims=tuple(int_dims), noise=tuple(spec.obs_noise),
        constraint=constraint)
    hv_frac = float(os.environ.get("AUTORESEARCH_HYBRID_HV_FRAC", "0.6"))
    try:
        picks = surrokit.ask(problem, X.tolist(), Y.tolist(), q=q,
                             picker=sk_picker, seed=_seed(round_idx),
                             pending=x_pending, hv_frac=hv_frac)
    except surrokit.InfeasibleError as e:
        raise SystemExit(
            f"[botorch_predict] budget_sob: GP predicts NO point in the "
            f"search box with flash <= {DEP_FLASH_PER_POT:.3e} MeV/POT "
            f"({e}); refusing to submit blind picks.")
    return [tuple(row) for row in picks]
```
In `main()`, forward surrokit's logger to stdout so campaign logs keep the GP-noise and constrained_max lines (add at the top of `main`, before parsing):
```python
    import logging
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[surrokit] %(message)s"))
    _sk = logging.getLogger("surrokit")
    if not _sk.handlers:
        _sk.addHandler(_h)
        _sk.setLevel(logging.INFO)
```

- [ ] **Step 3: Delete the parity test**

```bash
git rm tests/test_surrokit_parity.py
```

- [ ] **Step 4: Run the full suite + a live CLI smoke**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: green. The existing `tests/test_botorch_predict.py` compute_explore_picks tests (cold start, qnehvi fixture pick, CLI JSON round-trip, seam smoke) now exercise the surrokit path — they are the regression net.

Then one manual CLI smoke against the real foilspf board (read-only):
`PYTHONPATH= "$AUTORESEARCH_PYTHON" core/botorch_predict.py --mode foilspf --picker budget_sob --q 2 --round-idx 99`
Expected: two in-bounds picks printed, constrained_max feasibility line in the output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add core/botorch_predict.py
git commit -m "refactor: compute_explore_picks delegates to surrokit.ask

Parity gate passed (bit-identical on all four legacy pickers + cold
start) then retired -- the comparison is self-vs-self after this
commit. Old picker bodies remain until the surrogate/ rewire lands.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 9: rewire surrogate/ onto surrokit (Adapter + make_server)

**Files:**
- Create: `surrogate/adapter.py`
- Modify: `surrogate/__init__.py` (fit/predict via surrokit), `surrogate/mcp_server.py` (make_server), `requirements.txt` (comment only)
- Test: `tests/test_surrogate.py`

**Interfaces:**
- Consumes: `surrokit.fit/predict/Problem/Constraint`, `surrokit.mcp_scaffold.make_server`, `paths.SURROKIT_ROOT`, glue-side `bp._load_history_tensor`, `bp.DEP_FLASH_PER_POT`, `bp.BUDGET_SOB_K_SIGMA`.
- Produces: `surrogate.adapter.AutoresearchAdapter` (implements the `Adapter` protocol); MCP tool names become `list_problems | predict | suggest | stats | refit`.

- [ ] **Step 1: Update tests/test_surrogate.py first (failing)**

Keep the existing Python-API tests (`modes_info`, `fit`, `predict`, `suggest`, `board_stats` still exist with the same contracts). Replace the `TestMcpAdapter` tool-name assertion with the new names, and add adapter tests:
```python
# inside tests/test_surrogate.py, replacing the old MCP test class
@unittest.skipUnless(HAVE_MCP, "mcp SDK not installed")
class TestMcpAdapter(unittest.TestCase):
    def test_tool_names(self):
        import surrogate.mcp_server as ms
        tools = asyncio.run(ms.server.list_tools())
        names = sorted(t.name for t in tools)
        self.assertEqual(names, ["list_problems", "predict", "refit",
                                 "stats", "suggest"])


class TestAutoresearchAdapter(unittest.TestCase):
    def test_problems_cover_all_modes(self):
        from surrogate.adapter import AutoresearchAdapter
        import modes as _modes
        probs = AutoresearchAdapter().problems()
        self.assertEqual(sorted(probs), sorted(_modes.SPECS))
        for name, prob in probs.items():
            spec = _modes.SPECS[name]
            self.assertEqual(prob.dim, len(spec.knob_names))
            self.assertEqual(prob.noise, tuple(spec.obs_noise))
            self.assertIsNotNone(prob.constraint)

    def test_history_shape_and_meta(self):
        from surrogate.adapter import AutoresearchAdapter
        with tempfile.TemporaryDirectory() as tmp, patched_leaderboard(tmp):
            X, Y, meta = AutoresearchAdapter().history("foilsflash")
            self.assertEqual(len(X), len(Y))
            self.assertEqual(len(Y[0]), 2)
            self.assertIn("objectives", meta)
```
(Reuse the file's existing imports/fixture helpers; adapt `patched_leaderboard` usage to how the file already patches boards.)

- [ ] **Step 2: Run to verify the new tests fail**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest tests.test_surrogate -v`
Expected: FAIL (`No module named 'surrogate.adapter'`; old tool names).

- [ ] **Step 3: Write surrogate/adapter.py**

```python
"""AutoresearchAdapter: serve ModeSpec registry + leaderboards to surrokit.

The physics stays here: Y axis 1 is -log10(metric2), the budget
constraint is -log10(AUTORESEARCH_FLASH_BUDGET), and meta carries the
axis labels so MCP clients can interpret the numbers.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from paths import SURROKIT_ROOT  # noqa: E402
sys.path.insert(0, str(SURROKIT_ROOT))

import surrokit  # noqa: E402
import botorch_predict as bp  # noqa: E402
import modes as _modes  # noqa: E402


class AutoresearchAdapter:
    def problems(self) -> dict[str, surrokit.Problem]:
        out = {}
        for name, spec in _modes.SPECS.items():
            out[name] = surrokit.Problem(
                bounds_lo=tuple(spec.bounds_lo),
                bounds_hi=tuple(spec.bounds_hi),
                int_dims=tuple(spec.int_dims),
                noise=tuple(spec.obs_noise),
                constraint=surrokit.Constraint(
                    axis=1, min=-math.log10(bp.DEP_FLASH_PER_POT),
                    k_sigma=bp.BUDGET_SOB_K_SIGMA),
            )
        return out

    def history(self, name: str):
        spec = _modes.SPECS[name]
        X, Y, _, _ = bp._load_history_tensor(name)
        meta = {
            "objectives": ["sob", f"neg_log10_{spec.metric_cols[1]}"],
            "knob_names": list(spec.knob_names),
            "leaderboard": spec.leaderboard_rel,
        }
        return X.tolist(), Y.tolist(), meta
```

- [ ] **Step 4: Rewire surrogate/mcp_server.py**

Replace everything below the module docstring (keep/refresh the docstring — same .mcp.json registration, note the tool renames) with:
```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surrogate.adapter import AutoresearchAdapter  # noqa: E402
from surrokit.mcp_scaffold import make_server  # noqa: E402

server = make_server(
    AutoresearchAdapter(),
    name="autoresearch-surrogate",
    instructions=(
        "GP surrogate over the autoresearch BO leaderboards (Mu2e "
        "geometry optimization). Problems are the registered BO modes; "
        "axis 0 is sob (maximize), axis 1 is -log10 of the mode's second "
        "objective (maximize = minimize the raw metric). suggest() runs "
        "the production pickers; budget_sob's engine name is "
        "constrained_max. Nothing here submits jobs or writes to "
        "leaderboards -- pure read + compute."
    ),
)

if __name__ == "__main__":
    server.run("stdio")
```
(`surrogate/adapter.py` already put `SURROKIT_ROOT` on `sys.path`, so `surrokit.mcp_scaffold` resolves.)

- [ ] **Step 5: Rewire surrogate/__init__.py fit/predict onto surrokit**

Keep the module docstring, `modes_info`, `suggest` (still delegates to `bp.compute_explore_picks`), `board_stats`, and the `_FITS` cache unchanged. Replace the internals of `fit` and `predict` so they no longer touch `bp._fit_gp`:
```python
# new imports at top (after the existing core path insert):
from paths import SURROKIT_ROOT  # noqa: E402
sys.path.insert(0, str(SURROKIT_ROOT))
import surrokit  # noqa: E402
```
In `fit(mode, refresh=False)`, replace the `bp._fit_gp(...)` call with:
```python
    spec_prob = surrokit.Problem(
        bounds_lo=tuple(spec.bounds_lo), bounds_hi=tuple(spec.bounds_hi),
        int_dims=tuple(spec.int_dims), noise=tuple(spec.obs_noise))
    model = surrokit.fit(spec_prob, X.tolist(), Y.tolist())
```
(keep the existing `n < 2 -> RuntimeError` guard above it — same message). In `predict`, replace the manual `model.posterior` block with:
```python
    mean, sig = surrokit.predict(model, [[float(v) for v in p] for p in points])
```
and build the per-point dicts from `mean[i][0]`, `sig[i][0]`, `mean[i][1]`, `sig[i][1]` exactly as before (`lm, ls = float(mean[i][1]), float(sig[i][1])`).

- [ ] **Step 6: requirements.txt comment**

Update the mcp comment appended earlier to also name surrokit:
```
# surrokit (the ask/tell engine) is imported from the sibling checkout at
# $AUTORESEARCH_SURROKIT (default ../surrokit) -- not pip-installed; see
# core/paths.py and docs/superpowers/specs/2026-08-28-surrokit-engine-design.md
```

- [ ] **Step 7: Run the suite + live MCP smoke**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: green. Then a live stdio round-trip (same pattern used when the server first landed): start `surrogate/mcp_server.py` under ana 2.8.0 with a `stdio_client` + `ClientSession`, call `list_problems` and `predict` on foilspf at the champion x, verify sane numbers.

- [ ] **Step 8: Commit**

```bash
git add surrogate/adapter.py surrogate/mcp_server.py surrogate/__init__.py tests/test_surrogate.py requirements.txt
git commit -m "refactor: surrogate/ rides surrokit's make_server + fit/predict

Tool names change: list_modes->list_problems, board_stats->stats;
refit is new. .mcp.json consumers re-learn on next session start.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 10: delete the ported bodies + docs

**Files:**
- Modify: `core/botorch_predict.py` (delete dead code), `tests/test_botorch_predict.py` (drop tests of deleted internals), `wiki/drivers/surrogate.md` + `wiki/log.md` (UNCOMMITTED)

**Interfaces:**
- Consumes: everything already rewired (Tasks 8–9). After this task `core/botorch_predict.py` contains ONLY: module header/dtype setup, `_load_history_tensor`, `_seed`, `DEP_FLASH_PER_POT`, `BUDGET_SOB_K_SIGMA`, the surrokit import block, `compute_explore_picks`, `main`.

- [ ] **Step 1: Verify the bodies are dead**

```bash
grep -rn "_fit_gp\|_qnehvi_picks\|_qlnei_picks\|_qnparego_picks\|_hybrid_picks\|_budget_sob_picks\|_sobol_cold_start\|_emit_picks\|_sampler\|_optimize\b\|SOB_CORNER_MIN_SPACING\|ACQ_NUM_RESTARTS" --include=*.py . | grep -v "core/botorch_predict.py\|tests/test_botorch_predict.py"
```
Expected: no hits outside the two files (if `surrogate/` or `graph/` still references one, fix that first — it means Task 8/9 missed a call site).

- [ ] **Step 2: Delete from core/botorch_predict.py**

Remove: `_sampler`, `ACQ_NUM_RESTARTS`, `ACQ_RAW_SAMPLES`, `ACQ_OPTIONS`, `SOB_CORNER_MIN_SPACING`, `_optimize`, `_sobol_cold_start`, `_fit_gp`, `_qnehvi_picks`, `_qlnei_picks`, `_qnparego_picks`, `_hybrid_picks`, `_emit_picks`, `_budget_sob_picks`. Keep `DEP_FLASH_PER_POT` / `BUDGET_SOB_K_SIGMA` (glue reads them) and `_seed` / `_load_history_tensor`.

- [ ] **Step 3: Slim tests/test_botorch_predict.py**

Delete tests that called the removed internals directly (their surrokit ports exist since Tasks 2–5): `test_emit_picks_native_types_and_int_rounding`, `test_sobol_cold_start_deterministic_and_in_bounds`, `test_obs_noise_reaches_the_likelihood`, `test_pinned_noise_does_not_shrink_a_high_observation`, `test_budget_sob_picks_respect_the_damage_constraint`, `test_budget_sob_refuses_when_nothing_is_feasible`. KEEP everything that goes through `_load_history_tensor`, `_seed`, `compute_explore_picks`, or the CLI (`test_seed_is_xor_not_pow`, cold-start, fixture pick, JSON emit, seam smoke) — that is the glue's regression net.

- [ ] **Step 4: Full suite + golden harness**

Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`
Expected: green (count drops by the 6 deleted tests, net of the ~12 added in Tasks 7–9's lifetime).
Run: `PYTHONPATH= "$AUTORESEARCH_PYTHON" tests/golden_parity.py check`
Expected: PASS — section (b)'s loader fingerprint pins `_load_history_tensor`, which this extraction must not have touched.

- [ ] **Step 5: Wiki + docs (wiki stays UNCOMMITTED)**

- `wiki/drivers/surrogate.md`: add the surrokit split (engine at `SURROKIT_ROOT`, pinned SHA, tool renames, parity-gate result), bump `timestamp:`.
- `wiki/log.md`: one bullet under today's heading at the TOP.
- Do NOT `git add` wiki files.

- [ ] **Step 6: Commit the code deletion**

```bash
git add core/botorch_predict.py tests/test_botorch_predict.py
git commit -m "refactor: delete picker bodies ported to surrokit

core/botorch_predict.py is now pure glue: history loading, -log10
transforms, env constants, 42^round_idx seeds, CLI. Suite + golden
harness green.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

- [ ] **Step 7: Report the operator hand-offs**

Final message must list: (1) create `github.com/oksuzian/surrokit` and push from an interactive shell (`cd /exp/mu2e/app/users/oksuzian/surrokit && git remote add origin git@github.com:oksuzian/surrokit.git && git push -u origin main`); (2) review + commit the wiki edits; (3) the pinned surrokit SHA; (4) `readme-slim` ready for the operator's own push.
