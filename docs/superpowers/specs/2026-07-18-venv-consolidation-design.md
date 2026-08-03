# Design: venv consolidation — three venvs to one

Date: 2026-07-18
Status: approved (brainstorming session 2026-07-18)
Supersedes: the "venv pair KEEP / consolidation off the table" decision in
wiki `concepts/simplification-audit-2026-07` and recommendation #1 ("keep the
0.10 stack for the next campaign") in `concepts/ml-stack-review-2026-07` —
both revisited eyes-open in this session.

## Context

The repo carries three venvs (symlinks to `/exp/mu2e/data/users/oksuzian/
autoresearch_venvs/`):

| venv | Python | stack | role |
|---|---|---|---|
| `.venv-graph` | 3.11.15 | langgraph 1.2, numpy 2.4.6, scipy 1.17.1 | orchestrator + main suite |
| `.venv-botorch` | 3.9.25 | botorch 0.10, numpy 2.0.2, matplotlib | production picker default, A/B control arm, sole matplotlib host |
| `.venv-botorch-new` | 3.11.15 | botorch 0.18.1, torch 2.13+cpu, numpy 2.4.6 | A/B experiment arm; committed venue for d≥10 lines |

The historical constraint — `.venv-graph` cannot merge with the 3.9-based
0.10 venv — no longer binds the endgame: `.venv-botorch-new` and
`.venv-graph` are twins (same Python 3.11.15, numpy 2.4.6, scipy 1.17.1).
The recorded "consolidation off the table" predates the 0.18 venv's
existence.

## Decision (user, 2026-07-18)

Consolidate to **one venv**, retiring botorch 0.10. Consequences accepted
explicitly:

- Future foilsflash rounds pick under **0.18-base**. The ff16+ff17 pooled
  LOO evidence says 0.10-base slightly beats 0.18-base at 6D (sob NLL −0.69
  vs −0.43; corner NLL −2.14 vs −1.35; corner RMSE 0.046 vs 0.062), while
  0.18 wins robustness (0 vs 3 ModelFittingError folds) and ~15% fit speed.
  This small measured regression is the price of one venv; it also unlocks
  the best-measured variant (per-row `train_Yvar`, a 0.18-API feature, sob
  NLL −0.824, 10× faster fits), which lands **separately** as the
  env-flagged A/B the ml-stack review already recommended — one change at a
  time. Its σ/njobs leaderboard column rides the schema round (see
  `2026-07-18-tests-schema-protocol-design.md`).
- GP-fit-based figures (e.g. the perpot cloud) will render slightly
  differently under 0.18 defaults; the next deck refresh regenerates them.

## Target state

- One venv **`.venv`** (Python 3.11.15, uv-built) at
  `autoresearch_venvs/.venv` on /data, symlinked from the repo root like
  the current three.
- One **`requirements.txt`** replaces `requirements-graph.txt`,
  `requirements-botorch.txt`, `requirements-botorch-new.txt`: the langgraph
  stack (incl. uproot/awkward for the prodtarget harvest) + botorch 0.18.1
  / gpytorch 1.15.2 / torch 2.13.0+cpu (CPU wheel index recorded in the
  file) / numpy 2.4.6 / scipy 1.17.1 + matplotlib.
- `.gitignore`: a single `.venv*` glob (also silences the untracked
  `.venv-botorch-new` symlink).
- **Unchanged by design**: the `botorch_ask()` subprocess seam (child
  interpreter keeps torch out of the long-lived orchestrator process; now
  same venv) and the `AUTORESEARCH_BOTORCH_VENV` env override (how the
  yvar arm or botorch 0.19 gets A/B'd later).
- `botorch_predict.py` needs zero code changes — it already ran under 0.18
  for the ff16/ff17 A/B.
- No 0.10 binary archive: `requirements-botorch.txt` is the reproducible
  record and remains in git history after deletion. Skipping a tarball
  frees ~4–5 GB on the /data quota (which has EDQUOT'd before).

## Migration touch points

In-repo:

- Seam defaults `".venv-botorch"` → `".venv"`: `graph/config.py:196-197`
  and `core/bo_driver.py:1190,1196` (comments + error message too).
- Reference sweep for `.venv-graph` / `.venv-botorch`: operator skills
  (launch-bo-chain, more-jobs, status, autopsy, closed-loop-*),
  `wiki/drivers/tests.md` test command, related wiki pages.

Off-repo (/data, unversioned by convention):

- ~20 plotters: invocation `.venv-botorch/bin/python` → `.venv/bin/python`;
  0.10→0.18 API breakage fixed as found when each is exercised.

## Validation gates (in order; nothing deleted before all pass)

1. uv build resolves and installs (`requirements.txt` → `.venv`). If
   resolution fails (langgraph vs torch conflict — judged unlikely,
   disjoint dependency trees), fall back to the two-venv shape with
   nothing else touched.
2. Main suite green under `.venv`.
3. Real `botorch_ask` q=2 picker smoke on the live foilsflash leaderboard.
4. Full `graph.run --mock` chain end-to-end.
5. One plotter regenerated under `.venv` and visually checked.
6. Flip the seam defaults + reference sweep; re-run suite + smokes.
7. Delete the three old symlinks and their /data dirs (one named `rm` per
   path).

## Rollback

- Before the flip (gate 6): nothing user-visible has changed.
- After the flip, before deletion: restore one default string.
- After deletion: rebuild the 0.10 venv from the git-history
  `requirements-botorch.txt` (uv can fetch Python 3.9).

## Sequencing

This round lands **before** the tests/schema/protocol round, and simplifies
it: with one venv the `tests_botorch/` split dissolves — picker tests go
directly into `tests/` (the main suite can import botorch), and the
cross-venv smoke becomes a plain seam smoke.
`2026-07-18-tests-schema-protocol-design.md` is amended accordingly in this
round's docs commit.

## Commits

1. `requirements.txt` + `.gitignore` glob (venv build itself is an
   operation, not a commit).
2. Seam-default flip + in-repo reference sweep.
3. Delete the three old requirements files + wiki sweep (ml-stack verdict
   revision; simplification-audit KEEP → superseded; venv-relocated
   incident inventory; tests page) + amendment of the tests/schema spec.

Off-repo plotter edits are operations logged in `wiki/log.md`, not commits.

## Success criteria

One `.venv` runs the orchestrator, the picker, the test suite, and the
plotters; both seams (subprocess + env override) intact; suite and smokes
green under it; old venvs gone from /data; every in-repo and skill
reference updated; wiki records the revisited verdicts and the yvar A/B as
the next picker experiment.
