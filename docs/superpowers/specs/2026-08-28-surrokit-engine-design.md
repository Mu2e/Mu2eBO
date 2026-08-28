# surrokit — generic ask/tell surrogate engine (design)

**Date:** 2026-08-28
**Status:** approved (Yuri Oksuzian; scope agreed with Simon Corrodi's
package-plus-thin-adapter direction, 2026-08-28)
**Repo:** `github.com/oksuzian/surrokit` (new; name free on PyPI as of
2026-08-28)

## Goal

Extract the generic half of `core/botorch_predict.py` — GP fit, posterior
prediction, and the production pickers — into a standalone,
physics-agnostic Python library (`surrokit`), plus a reusable MCP server
scaffold. autoresearch becomes a *client*: it keeps its leaderboards,
ModeSpec registry, and `-log10` conventions, and feeds the engine plain
numbers.

Why: reuse beyond this project (Simon, Ray, other optimization lines), one
MCP integration surface for Ray's future auth/logging middleware, and a
smaller, provable core (pure math, no per-experiment special cases).

## Decisions locked during brainstorming

1. **Scope B — surrogate engine.** `fit` / `predict` / `ask` plus an
   optional MCP scaffold. Not just a picker library (scope A); not a
   full data-service (scope C).
2. **Contract A — math-space boundary.** The engine sees only numbers.
   All Y axes arrive already transformed by the client and are maximized
   by convention; noise sigmas are given in that same space; the budget
   constraint is an abstract inequality on one output axis. The engine
   never learns what "flash" or "MeV/POT" means.
3. **MCP shape A — server factory.** `make_server(adapter)` returns a
   ready MCP server; every client gets identical tool names and shapes.
4. **Hosting:** personal GitHub (`oksuzian/surrokit`), MIT license,
   pip-installable via `git+https` now, PyPI later. Transferable to an
   org without breaking clients (GitHub redirects).

## Repo layout

```
surrokit/
├── pyproject.toml          # deps: botorch>=0.18, torch, scipy, numpy;
│                           #   requires-python >=3.10; MIT
├── README.md               # incl. the "minimize-with-budget" recipe
├── surrokit/
│   ├── __init__.py         # public API: Problem, Constraint, fit, predict,
│   │                       #   ask, InfeasibleError, __version__
│   ├── problem.py          # Problem, Constraint dataclasses + validation
│   ├── gp.py               # fixed-noise SingleTaskGP fit + posterior predict
│   ├── pickers.py          # qnehvi | qlnei | qnparego | hybrid | constrained_max
│   ├── sampling.py         # Sobol cold-start, seeding, acq-optimize helpers
│   └── mcp_scaffold.py     # Adapter protocol + make_server; lazy mcp import
└── tests/                  # unittest; no autoresearch imports anywhere
```

`mcp` is an optional dependency: importing `surrokit` never requires it;
`surrokit.mcp_scaffold` raises a clear ImportError naming `pip install
"mcp>=2.0"` when absent (it ships in the Mu2e `ana 2.8.0` env).

## Core types

```python
@dataclass(frozen=True)
class Constraint:
    axis: int             # output axis the rule applies to
    min: float            # threshold, in the client's (transformed) Y-space
    k_sigma: float = 1.0  # feasible: posterior mean - k_sigma*sigma >= min

@dataclass(frozen=True)
class Problem:
    bounds_lo: tuple[float, ...]
    bounds_hi: tuple[float, ...]
    int_dims: tuple[int, ...] = ()            # indices rounded in ask() output
    noise: tuple[float, ...] | None = None    # ABSOLUTE sigma per output axis;
                                              # None = free MLL noise (see
                                              # gp-free-noise-erases-champion —
                                              # clients with replicate-measured
                                              # noise should always pin it)
    constraint: Constraint | None = None      # required by constrained_max
```

Validation in `__post_init__`: equal bounds lengths, `lo < hi` per dim,
`int_dims` in range, `constraint.axis` checked against Y width at fit/ask
time (Y width is not known to Problem).

Conventions (documented in README, enforced where checkable):
- Every Y axis is MAXIMIZED. Clients negate/transform on their side.
- Axis 0 is the primary objective: `qlnei` optimizes it alone;
  `constrained_max` ranks by it.
- X rows are in raw (un-normalized) knob units inside `bounds`.

## Functions

```python
fit(problem, X, Y) -> Model
    # X: (n, d), Y: (n, m) — lists of lists or numpy/torch arrays.
    # SingleTaskGP, input Normalize(bounds), outcome Standardize,
    # train_Yvar = noise**2 broadcast when problem.noise is set.
    # Raises ValueError on shape mismatch; NotEnoughData(RuntimeError)
    # when n < 2.

predict(model, X) -> (mean, sigma)
    # posterior mean and stddev, (n, m) numpy arrays, Y-space.

ask(problem, X, Y, q=5, picker="hybrid", seed=0, pending=None,
    min_spacing=0.10, pool=16384, hv_frac=0.6) -> list[list[float]]
    # picker: qnehvi | qlnei | qnparego | hybrid | constrained_max.
    # STATELESS: fits the GP internally on every call (today's
    #   compute_explore_picks contract — leaderboard as it stands at
    #   that moment). The fit cache lives only in the MCP scaffold,
    #   never in the library.
    # seed: used VERBATIM in every RNG stream (MC sampler, Sobol
    #   draws, torch.manual_seed) — the engine derives nothing.
    #   autoresearch passes 42 ^ round_idx from its side (the xor is a
    #   client convention; see botorch-predict-seed-pow-vs-xor), so all
    #   streams stay bit-identical to today's.
    # pending: list of x-rows in flight — acquisition pickers fantasize
    #   over them (X_pending); constrained_max spreads away from them.
    # n < 2 -> Sobol cold-start draw (never an error).
    # Y-width validation (ValueError): qnehvi/qnparego/hybrid require
    #   m >= 2; constrained_max requires problem.constraint set and
    #   constraint.axis < m; qlnei accepts m >= 1 and uses axis 0 alone.
    #   autoresearch keeps its sob-only load path and passes (n, 1) for
    #   qlnei — a 2-output fit is not guaranteed bit-identical on
    #   axis 0, and the parity gate depends on it.
    # int_dims rounded in the returned lists (today's _emit_picks).
    # min_spacing/pool apply to constrained_max only (today's
    #   SOB_CORNER_MIN_SPACING=0.10 and N=16384 as defaults).
    # hv_frac applies to hybrid only: qnehvi share of the batch
    #   (today's AUTORESEARCH_HYBRID_HV_FRAC env read at
    #   botorch_predict.py:274 — a third env constant relocated to the
    #   client side; autoresearch keeps reading the env var and passes
    #   the value in). 0.0 = pure qnparego.
    # qnparego: today internal to hybrid (not in PICKER_CHOICES);
    #   promoted to a standalone choice here. No legacy CLI counterpart,
    #   so it is excluded from the bit-parity gate — covered transitively
    #   by hybrid parity plus its own surrokit unit tests.
```

`constrained_max` (today's `budget_sob`, renamed physics-neutral):
Sobol-sample `pool` points, keep those with
`mean[axis] - k_sigma*sigma[axis] >= min`, rank by axis-0 mean, enforce
`min_spacing` in normalized X against picks + pending. Keeps the
k-relaxation ladder (k -> k/2 -> 0 when fewer than q candidates are
feasible, logged at WARNING). When zero candidates are feasible even at
k=0 it raises `InfeasibleError` — the library never calls SystemExit.
(autoresearch glue catches `InfeasibleError` at the CLI seam and
re-raises today's SystemExit message; `graph/pool.py:143` catches
`(Exception, SystemExit)` uniformly, so pool behavior is unchanged
either way.)

Library discipline: no `print` (the `logging` module, logger name
`surrokit`), no `sys.exit`, no environment-variable reads. Today's
env-tunable constants become explicit arguments supplied by the client
(autoresearch keeps reading `AUTORESEARCH_FLASH_BUDGET` /
`AUTORESEARCH_BUDGET_KSIGMA` / `AUTORESEARCH_HYBRID_HV_FRAC` on its side
and passes the values in).

## MCP scaffold

```python
class Adapter(Protocol):
    def problems(self) -> dict[str, Problem]
        # name -> Problem, re-queried per call (cheap; registry may grow)
    def history(self, name: str) -> tuple[list, list, dict]
        # (X, Y, meta) for the CURRENT data. meta is a free-form
        # JSON-serializable dict merged into stats output (e.g. axis
        # labels, champion row, leaderboard path).

make_server(adapter, name="surrokit", instructions="...") -> MCPServer
```

Tools (identical for every client; structured output with typed return
annotations — bare `dict` returns are rejected by mcp 2.0):
- `list_problems()` — names, dims, bounds, axis count, row counts
- `predict(problem, points)` — mean/sigma per axis per point
- `suggest(problem, q=5, picker="hybrid", seed=0, pending=None,
  min_spacing=0.10, hv_frac=0.6)` — faithful ask() passthrough (pending
  lets external clients declare their own in-flight set)
- `stats(problem)` — row count + adapter meta
- `refit(problem)` — cache bypass

Fit cache: per problem name, keyed on `len(X)` (append-only history
assumption, documented; `refit` is the escape hatch). Middleware:
`make_server` forwards a `middleware=` kwarg to `MCPServer` — Ray's
auth/logging layer plugs in there without touching tools.

## autoresearch migration

**Bootstrap:** Claude scaffolds the full local repo at
`/exp/mu2e/app/users/oksuzian/surrokit` (git init, code, tests, CI,
pyproject); the operator creates the empty GitHub repo and pushes from
an interactive shell (Claude cannot push — no ssh-agent in Bash
subshells). autoresearch pins the LOCAL checkout's SHA, so the GitHub
push is off the critical path.

**Install constraint:** the default interpreter (`ana 2.8.0` on cvmfs) is
immutable — no pip install. Short-term: sibling checkout pinned to a
commit SHA (`/exp/mu2e/app/users/oksuzian/surrokit`), path exported by
`activate.sh` (new `AUTORESEARCH_SURROKIT` seam, defaulting to the sibling
path). Long-term: publish to PyPI and request inclusion in the next
published `ana` release (the 2.8.0 adoption channel).

**Cut-over plan (summary — the implementation plan details tasks):**
1. Create surrokit repo; port `_fit_gp`, picker functions, sampling
   helpers, `_emit_picks` verbatim-modulo-interface; port their tests
   from `tests/test_botorch_predict.py` onto generic fixtures.
2. **Parity gate:** A/B harness in autoresearch runs old
   `compute_explore_picks` vs `surrokit.ask` on the golden fixtures at
   fixed seeds for the four legacy pickers (qnehvi, qlnei, hybrid,
   budget_sob-as-constrained_max) + cold start — picks must be
   BIT-IDENTICAL before any old code is deleted. (Known hazard: the
   hybrid picker's scipy ABNORMAL-retry nondeterminism at ~300-row scale
   — wiki/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md
   — parity runs on the small golden fixtures where it is invisible.)
3. Rewire `core/botorch_predict.py` into glue: leaderboard -> tensors,
   `-log10` transform, `thr = -log10(budget)`, Problem construction,
   surrokit calls. CLI surface (argparse, --emit-picks-json) unchanged —
   graph/closed_loop.py must not notice.
4. `surrogate/` package delegates to surrokit; `surrogate/mcp_server.py`
   becomes `make_server(AutoresearchAdapter())` (~15 lines). Tool names
   change (list_modes -> list_problems, board_stats -> stats): .mcp.json
   consumers re-learn on next session start; no other in-repo callers.
5. Delete the ported picker bodies from botorch_predict.py; the 685-test
   suite and golden harness must stay green throughout; the A/B parity
   test retires with the old code (goldens then pin engine behavior).

## Testing

- surrokit repo: self-contained unittest suite — picker behavior ports,
  Problem validation, InfeasibleError paths, cold start, seed
  determinism, scaffold tests (`skipUnless mcp`). CI: GitHub Actions,
  pip-installed botorch (no cvmfs). CI asserts BEHAVIOR, not bits —
  shapes, same-process seed determinism, validation errors, k-ladder /
  InfeasibleError paths, cold start. Bit-level parity binds only in the
  autoresearch environment (ana 2.8.0: botorch 0.18.1, torch 2.5.1,
  Python 3.12): the A/B harness
  during extraction, the golden harness after. No pinned-version CI
  lane.
- autoresearch: existing 685-test suite green at every step; parity gate
  as above; `tests/test_surrogate.py` updated for the adapter shape.

## Non-goals

- No transforms inside the engine (contract A). The README recipe covers
  "minimize a metric under a budget" in 5 lines of client code.
- No data loading, no leaderboard formats, no campaign orchestration.
- No HTTP transport yet (`server.run("streamable-http")` exists in the
  SDK if a non-local client appears; stdio covers everything today).
- No new pickers or GP variants during the extraction — behavior-
  preserving move first.

## Closed questions (grill session 2026-08-28)

- PyPI publish timing: **after the first external user.** git+https +
  the sibling checkout cover all consumers today; the name is free and
  squatting risk for a niche name is low.
- `ana 2.9.0+` inclusion: **through Simon/Ray**, in the same
  conversation as the middleware handoff (Simon holds the
  pyenv-publisher relationship).
