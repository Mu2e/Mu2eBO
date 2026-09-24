---
type: concept
title: Engine seam friction survey (2026-08)
description: post-extraction friction map of surrokit + the autoresearch glue — Problem built 3 ways, caller-less surrogate façade, picker-vocabulary divergence at the MCP door, tests that bypass their interfaces; all 4 candidates executed 2026-08-28, façade finally deleted 2026-09-22
status: resolved
status_note: ALL 4 candidates EXECUTED 2026-08-28 (surrokit f89fd86 / glue tip); 4 was cherry-picked to its two worthwhile tests
timestamp: '2026-09-22'
---

# Engine seam friction survey (2026-08)

## Summary

Fresh-eyes architecture walk of the Engine (surrokit @ `6db74f3`) and its
autoresearch glue (`readme-slim` @ `be7393e`), run three weeks after the
extraction ([surrogate](/drivers/surrogate.md)). The Engine core is sound;
the friction is concentrated at the client seam: `Problem` is assembled
three different ways with three different constraint policies, the
`surrogate/` façade fails the deletion test (zero non-test callers), the
picker-name mapping lives in a production-only branch so the MCP door
silently diverges, and several test files pin privates instead of
interfaces. 17 findings, 4 ranked deepening candidates. Line numbers are
valid at the SHAs above (pre-execution).

**Execution status (2026-08-28):** candidate 2 landed as surrokit
`9cb06c3` (fit() enforces len(noise)==Y axes -- which flushed out that
the old noise[:m] slice was silently load-bearing for qlnei sob-only;
emit_picks clamps int dims in-box; Problem rejects integer-free int
boxes; README documents global-RNG seeding). Candidate 1 landed as glue
`abe286d` (`build_problem()` + public `load_history_tensor` +
call-time `flash_budget()`/`budget_k_sigma()`; adapter and facade use
the shared seam). The facade API was KEPT at the time, not deleted --
its docstring recorded a 2026-08-28 agreement with Simon Corrodi that it
is a published plain-Python seam; only the duplicate implementation
went. **SUPERSEDED 2026-09-22: the facade was DELETED.** Four weeks on,
a repo-wide plus off-repo sweep (15 locations incl. mmackenz_table_plots,
autoresearch2, prodtools, both `.claude` trees, EAF, crontab) found zero
callers -- the published seam never acquired one, so candidate 1's
deletion test finally ran and passed. `board_stats`'s champion +
sob-range body moved to `adapter._board_summary` and now rides the MCP
`stats` tool's meta; `predict`'s inverse-log10 reporting was dropped
(the scaffold returns raw per-axis mean/sigma). Suite 676 green. See
[surrogate](/drivers/surrogate.md).
Candidate 3 landed as surrokit `8d92b6c` + glue `802ab14`: the scaffold
gained an optional adapter `suggest()` hook, and AutoresearchAdapter
routes it through `bp.compute_explore_picks` -- MCP picks now ARE what a
closed-loop round would submit (production vocabulary, sob-only qlnei
history, 42^round_idx seed; the tool schema speaks `round_idx`, not a
raw seed).
All verified pick-bit-identical (engine fixture + 90-row CSV; client
foilspf all 4 pickers), suites 47/47 + 682 green, golden a/b/c OK.

## Key facts — the four candidates (ranked)

1. **One Problem-assembly module in the client** (load-bearing).
   `Problem` built 3×, 3 ways: production sets `constraint` only for
   `budget_sob` (`core/botorch_predict.py:129-137`), the Adapter sets it
   unconditionally on all 7 modes (`surrogate/adapter.py:32-34`),
   `surrogate.fit` never sets it (`surrogate/__init__.py:86-88`). So MCP
   `list_problems` reports `constrained: true` for every mode while a
   non-constrained picker silently ignores it. To build Problems the
   Adapter reaches into privates (`bp._load_history_tensor`) and two
   **import-time** env constants (`DEP_FLASH_PER_POT`,
   `BUDGET_SOB_K_SIGMA` — frozen at server start; `hv_frac` read at call
   time: two env disciplines at one seam). `surrogate/__init__.py` is a
   caveat on the extraction: 4 of its 5 functions twin what
   `make_server` generates (incl. a byte-identical fit cache), zero
   non-test callers — deletion test fails. Only `board_stats` and
   `predict`'s inverse-transform reporting are unique behavior.
   **RESOLVED 2026-09-22 by deletion** (see Execution status above).
2. **Engine enforces its own contract.** `Problem.__post_init__`
   validates everything except `noise` length: `noise[:m]`
   (`surrokit/gp.py:68`) silently truncates, a short tuple silently
   broadcasts one sigma across all axes (untested). The client wrote the
   missing check itself (`core/modes.py:66-70` — an Engine rule enforced
   only in the client registry). `emit_picks` `int(round(v))` can land
   outside the box when an int dim's bound is non-integral — in-box is
   NOT a postcondition of `ask`. `ask()` clobbers the caller's global
   torch RNG (`torch.manual_seed` at entry + again in `_qnparego`),
   undocumented in README. Picker-irrelevant kwargs (`hv_frac` on qlnei,
   `min_spacing`/`pool` on non-constrained) accepted silently.
3. **One picker vocabulary at the seam.** `budget_sob → constrained_max`
   mapping exists once, inside a production-only `if`
   (`core/botorch_predict.py:129-130`); the MCP door never sees it.
   Worse: MCP `suggest(picker="qlnei")` trains on the 2-axis
   calo-filtered history while production qlnei uses `sob_only=True`
   (1-axis, keeps calo-invalid rows) — same picker name, different
   dataset, and the only reconciliation is a 12-line English paragraph in
   `surrogate/mcp_server.py`'s `instructions=` string. Seed argument
   spelled 3 ways in one chain: `round_idx` / `seed` / `seed_idx`.
4. **Test through interfaces.** `surrogate/mcp_server.py` builds its
   server at import (no factory) — tests can only assert tool names.
   `tests/test_surrogate.py` clears private `_FITS`;
   `test_constrained_max.py` drives private `_constrained_max` with a
   fake posterior (the deployment-facing picker is only smoke-tested
   through `ask` once); `test_gp.py` noise-roundtrip test transcribes the
   audit arithmetic it checks. Scaffold fit-cache staleness (in-place
   history rewrite, same row count) untested; scaffold `predict` uses the
   cache while `suggest` refits — one session, two models.

## Key facts — remaining findings worth keeping

- `n_rows` means two things: `board_stats`/`modes_info` count raw
  Leaderboard rows; `list_problems` + the fit-cache key count
  post-`calo>0`-filter rows (`core/botorch_predict.py:61-62`). Neither
  names its filter. `axes` reports `None` on an empty board because
  `Problem` has no output-arity field.
- The Engine example (`examples/stopping_target.py`) is `foilspf`
  re-typed as literals: bounds/knobs == `mode_specs/foilspf.json`,
  `NOISE=(0.006,0.01)` == `obs_noise`, `BUDGET=6.85443e-7` ==
  `DEP_FLASH_PER_POT` default; CSV = 90-row Leaderboard snapshot
  (public — verified before shipping). Deliberate pedagogy, but the
  `-log10`/`10**-x` transform pair is written ~7× across the two repos
  and owned by neither.
- Import-order sensitivity: 4 glue modules `sys.path.insert` before
  import; `.mcp.json` passes a relative server path (repo-root-cwd
  only). Forced by the read-only cvmfs interpreter (no pip install into
  ana 2.8.0) — the PYTHONPATH-checkout + `SURROKIT_PIN_SHA` drift test
  is the version contract, and every Engine commit reddening
  `TestSurrokitPin` is its running cost (deliberate; bump-on-validate).
- MCP stdio client strips the env for spawned servers
  (HOME/PATH/SHELL/TERM/USER) — the example forwards `os.environ`; the
  client's server additionally needs `AUTORESEARCH_FLASH_BUDGET` /
  `AUTORESEARCH_BUDGET_KSIGMA` present at import to get non-default
  budgets. Trap surfaces as opaque "Connection closed".

## Cross-links

- Related: [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md),
  [budget-sob-picker](/concepts/budget-sob-picker.md),
  [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md)
- Driver: [surrogate](/drivers/surrogate.md)
- Incidents echoed: [gp-free-noise-erases-champion](/incidents/gp-free-noise-erases-champion.md),
  [hybrid-picker-scipy-abnormal-retry-nondeterminism](/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md),
  [botorch-predict-seed-pow-vs-xor](/incidents/botorch-predict-seed-pow-vs-xor.md)
- Source files: `surrogate/adapter.py`, `surrogate/__init__.py`,
  `core/botorch_predict.py`, `surrokit/pickers.py`, `surrokit/gp.py`,
  `surrokit/mcp_scaffold.py`

## Open questions / TODO

- Candidate 4 cherry-picks landed (surrokit `f89fd86`): constrained_max
  verified on a real fitted GP through ask(); scaffold fit-cache
  staleness under same-count in-place rewrite + refit() recovery.
  Deliberately NOT done from candidate 4: mcp_server import-time build,
  `_FITS.clear()` cosmetics (judged not worth standalone churn).
- Whether the `-log10` transform pair should become an Engine helper or
  stay a client recipe (the math-space contract argues recipe).
