---
type: external
title: Mu2e CVMFS Python envs (pyenv ana/rootana/trkqual) — contents + our delta
description: The /cvmfs env/ area and `pyenv` mechanism; measured package delta from
  our .venv to ana/rootana (ana is the closer fit, 14 conflicts vs 26, only numpy
  load-bearing); trkqual is the py3.11+torch precedent for a sibling ML env; our
  stack verified green on Python 3.12; requirements.lock landed 2026-08-18
status: active
status_note: measured 2026-08-12; lockfile blocker cleared 2026-08-18; ana 2.8.0 published
  on /cvmfs and adopted as the default interpreter 2026-08-20
timestamp: '2026-08-21'
updated_note: lockfile blocker resolved (requirements.lock, 77 pkgs / 1744 hashes,
  pinned to the installed venv because a fresh resolve drifts 20 packages); remaining
  Phase-1 work moved to docs/pyenv-publication-plan.md
---

# Mu2e CVMFS Python envs (pyenv ana/rootana/trkqual) — contents + our delta

## Summary
Mu2e publishes shared Python environments under
`/cvmfs/mu2e.opensciencegrid.org/env/`, activated by the `pyenv` shell function
(see [pyutils-analysis-env](/external/pyutils-analysis-env.md) for the analysis-side
recipe). This page records **what is actually installed in each env** and the
**measured delta from this project's `.venv`**, derived to answer "can our BO stack
be published there instead of living in a personal `/exp` venv". The delta is not
re-derivable in under 5 minutes — it needs a dist-info diff across three prefixes.

## Key facts

- **Three envs exist, not two.** `pyenv.sh`'s own usage text advertises only `ana`
  and `rootana`, but `env/trkqual/` is published alongside them (`1.0.0`, `1.1.0`,
  `1.2.0`, `current` → `1.1.0`). So **an unadvertised, working-group-specific env is
  an accepted thing to publish** — that is the precedent for asking for one.
- **`pyenv` is `muse activate ENV_NAME [VERSION]`**, defaulting to **version 2.7.0**
  when no version is given (`/cvmfs/mu2e.opensciencegrid.org/bin/pyenv.sh`). It
  supports both Pixi and Conda builds. Envs are immutable published prefixes — a
  venv cannot be "moved" there, only **rebuilt as a release from a lockfile**.
- **Latest versions as of 2026-08-12:** `ana` 2.7.0 (py3.12, 236 packages),
  `rootana` 2.5.0 (py3.12, 229 packages), `trkqual` 1.1.0 = `current` (**py3.11**,
  503 packages).
- **`trkqual` is the py3.11 + torch precedent:** torch 2.1.2.post100, tensorflow
  2.15.0, xgboost 3.1.3, scikit-learn 1.8.0, numpy 1.26.4, uproot 5.7.0. It exists
  *because* heavy ML deps don't belong in `ana`/`rootana` — which is the same
  argument for a BO sibling env.
- **Measured delta from our `.venv` (77 packages, py3.11)** — dist-info diff,
  script kept at `scratchpad/cmp_env.py` in-session:

  | target | packages | we'd ADD | version CONFLICTS | already identical |
  |---|---|---|---|---|
  | `ana` 2.7.0 | 236 | 29 | 14 | 34 |
  | `rootana` 2.5.0 | 229 | 30 | 26 | 21 |

- **`ana` is the better fit**, for three independent reasons: half the conflicts
  (14 vs 26) and 13 of those 14 are trivial point drift (`anyio` 4.14.2 vs 4.14.0,
  `pillow` 12.3 vs 12.2) we would simply accept; `rootana` **lags** (`urllib3`
  1.26.16, `scikit-learn` 1.8.0, `awkward` 2.9.0, newest release 2.5.0 vs ana's
  2.7.0); and **rootana's raison d'être — bundled PyROOT — buys this project
  nothing**, because our ROOT reads already run under `muse setup`
  (forced by [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md)).
- **Exactly ONE conflict is load-bearing: numpy 1.26.4 (both envs) vs our 2.4.6.**
  torch 2.13 + botorch 0.18 need numpy 2.x, and moving `ana` to numpy 2 forces a
  recompile of every C-extension in it (`awkward-cpp`, `scipy`, `scikit-learn`,
  `matplotlib`, `pillow`) — i.e. a **major release of ana**, not a package add.
- **The 29 adds split two ways, and the split is the argument:** only **9 are the ML
  core** (`torch 2.13.0+cpu`, `botorch`, `gpytorch`, `linear-operator`,
  `multipledispatch`, `pyre-extensions`, `typing-inspect`, `mypy-extensions`,
  `ninja`); **19 are the LangGraph/LangSmith orchestrator cluster** (`langgraph` ×5,
  `langchain-core`, `langchain-protocol`, `langsmith`, `aiosqlite`, `sqlite-vec`,
  `orjson`, `ormsgpack`, `uuid-utils`, `websockets`, `zstandard`, `tenacity`,
  `jsonpatch`, `requests-toolbelt`, `distro`) plus `setuptools`. **No analysis user
  will ever import the orchestrator half** — so the smallest credible ask is the
  9 ML packages riding a future numpy-2.x `ana`, with LangGraph staying local.
- **Our stack runs on Python 3.12 — verified, not assumed (2026-08-12).** A
  `.venv312` built from the same `requirements.txt` (CPython 3.12.13, torch
  `2.13.0+cpu` first, then the rest) runs the **full suite 471/471 OK**. Warm
  runtime **38.2 s vs 37.8 s on 3.11 — indistinguishable**. The first run took
  139 s; that is a **cold torch JIT extension cache**, not a regression (cf.
  [torch-cpp-extension-stale-filebaton-suite-hang](/incidents/torch-cpp-extension-stale-filebaton-suite-hang.md)).
  Nothing in the repo pins 3.11 (only prose in `requirements.txt`, `README.md`,
  and wiki pages), and no code uses stdlib removed in 3.12 (`distutils`, `imp`,
  `asynchat`, removed `unittest` aliases). Venv kept at
  `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv312`.
- **Lockfile blocker RESOLVED 2026-08-18.** `requirements.txt` remains
  unpublishable on its own — 7 of its 12 lines are `>=` ranges (`langgraph`,
  `langgraph-checkpoint-sqlite`, `python-dotenv`, `matplotlib`, `scikit-learn`,
  `uproot`, `awkward`) — so `requirements.lock` now carries the pinned, hashed
  resolution: **77 packages, 1744 hashes**, `--require-hashes` clean, and
  `uv pip install --dry-run` against the live venv reports *"would make no
  changes"*.
- **The lock is constrained to the INSTALLED venv, not re-resolved — and that
  distinction is load-bearing.** A fresh unconstrained `uv pip compile` of the
  same `requirements.txt` on 2026-08-18 moved **20 of the 77**: `langgraph`
  1.2.9→1.2.11, `langchain-core` 1.4.9→1.5.6, `langsmith` 0.10.6→0.11.0,
  `awkward` 2.10.0→2.13.0 (+`awkward-cpp` 54→56), `setuptools` 78.1.0→84.0.0,
  `orjson` 3.11.9→3.12.0, `xxhash` 3.8.1→4.0.1, `typing-extensions`
  4.15.0→4.16.0, plus point drift. None of that is reviewed or suite-verified,
  so the regenerate recipe in the lock's header keeps `--constraint` on a freeze
  of a green venv. The `+cpu` pin also makes the pytorch index mandatory at
  install: plain `torch` from PyPI is the 2.8 GB CUDA build.
- **`.gitignore`'s blanket `*.lock` (runtime file locks) silently swallowed it.**
  `git status` stayed clean and the one file a second operator or a publisher
  needs would never have left this machine. Fixed with a `!requirements.lock`
  exception; worth remembering the pattern is that broad.
- The build recipe's hardcoded `/exp/mu2e/data/users/oksuzian/...` was fixed by the
  portable-paths work, on the default branch since 2026-08-21 (PR #31).
- **PUBLISHED AND ADOPTED 2026-08-20: `ana 2.8.0` is on `/cvmfs` and is now
  this project's default interpreter.** `source activate.sh` resolves
  `/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python` (CPython 3.12.13)
  and exports it as `$AUTORESEARCH_PYTHON`; `AUTORESEARCH_VENV=<path>` selects
  a dev venv instead. The published build ships **numpy 2.5.2** — the single
  load-bearing conflict recorded above, cleared. Measured on the published
  prefix, not the staging copy: full suite **681/681 OK (skipped=2)**, warm
  66 s vs 60 s on the venv (cold first run 187 s — cvmfs page cache, not the
  env); `--picker budget_sob` **bit-identical** to the venv's torch
  2.13.0+cpu; `graph.run` + `build_graph()` import clean on its langgraph
  0.2.50. One full local evaluation (`pyenvlocal01`, 8×12500/stage) ran end to
  end on it, harvest `degraded={}`, row appended.
- **Two traps when pointing anything at this env.** (1) **Always name the
  version.** `pyenv ana` with no version resolves to **2.7.0**
  (`pyenv.sh:40`) and `env/ana/current` is **2.6.1** — both numpy 1.26, which
  torch will not run on; `activate.sh` refuses a name without a version rather
  than resolve one. (2) **Do NOT activate the env in a shell that spawns our
  jobs.** `pyenv.sh` `export -f`s wrappers for `python`/`pip`/`jupyter`/
  `conda`/`mamba`, and each wrapper re-runs `setup_mu2e_python_env` on EVERY
  call, re-prepending the env's site-packages to `PYTHONPATH` and its `lib/`
  to `LD_LIBRARY_PATH`. Exported bash functions cross into every child (see
  [sourced-env-drops-muse-function-local-jobs](/incidents/sourced-env-drops-muse-function-local-jobs.md)),
  so an activated shell pushes a second ROOT/XRootD binding and a second
  libstdc++ into the harvest steps that run PyROOT under `muse setup` — the
  shadowing behind [uproot-cannot-read-steppointmc](/incidents/uproot-cannot-read-steppointmc.md).
  `activate.sh` therefore exports an absolute interpreter PATH and never
  sources `pyenv.sh`; a test pins that.
- **The picker interpreter must follow the caller.** `core/runtime.py` and
  `core/bo_driver.py` both resolved a repo-relative `.venv/bin/python`; left
  alone, the launchers would have moved to the published env while the GP fit
  kept running on the old venv's torch. Both now default to `sys.executable`;
  `AUTORESEARCH_BOTORCH_VENV` still names a repo-relative directory for a
  two-build picker A/B.
- **Superseded staging measurement (2026-08-18, kept for provenance):**
  `/exp/mu2e/data/users/sophie/pyenv-v2.8.0/ana_v2.8.0` (318 packages, 13 GB)
  ran the then-617-test suite with zero changes: `PYTHONPATH= <env>/bin/python -m unittest discover -s tests -t .`
  → `Ran 617 tests ... OK (skipped=1)`. It already carries botorch 0.18.1,
  gpytorch 1.15.2, langgraph + langgraph-checkpoint-sqlite, uproot, awkward,
  scikit-learn — i.e. someone has already folded our ask into the candidate.
  Only **3 of our 77 locked packages are absent** (`langgraph-prebuilt`,
  `langchain-protocol`, `sqlite-vec`) and none is imported by our code —
  they are transitive-only.
- **Numerically equivalent for BO, verified against the deterministic picker.**
  `--picker budget_sob` (GP-mean corner search, no acquisition optimizer) is
  **bit-identical** across the two envs on `foilspfbpz`, despite torch
  2.5.1 (ana, CUDA 12.4 build) vs our 2.13.0+cpu — so the GP fit and
  posterior agree. `qnehvi`/`hybrid` differ across envs, but they differ
  run-to-run *within a single venv* too, so that is
  [hybrid-picker-scipy-abnormal-retry-nondeterminism](/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md),
  not an env delta. `SqliteSaver` put/get round-trips identically on
  checkpoint-sqlite 2.0.0 (ana) and 3.1.0 (ours), including the same
  `np.int64` metadata rejection.
- **The version deltas that look alarming are not.** langgraph 0.2.50 (ana)
  vs 1.2.9 (ours) is a major-version gap, yet the suite is green and
  `build_graph().compile(checkpointer=SqliteSaver(...))` works — we use only
  `langgraph.graph.StateGraph` + `langgraph.checkpoint.sqlite`, both stable
  across that gap. Warm suite wall-clock is a wash (41.9 s ana vs 40.5 s
  ours); a **cold** first run cost 219 s, which is NFS page-cache, not the env.
- **Caveat: sophie's path is a personal `/exp/mu2e/data` staging area**, not a
  supported dependency — the same class of fragility as the `${ARTIFACT}`
  misresolution in
  [sourced-env-stderr-swallowed](/incidents/sourced-env-stderr-swallowed.md).
  Treat it as evidence for the publication ask, not as a venv to point at.
- **Remaining Phase-1 work** is tracked in `docs/pyenv-publication-plan.md`:
  merge portable paths, re-verify 3.12 at the current 612-test suite (the green
  run was at 471), and split the requirements mechanically into the 9-package ML
  core vs the 19-package orchestrator cluster so the ask is the former.
- **Size to quote when asking: 1.2 GB, 77 packages**, torch deliberately the `+cpu`
  wheel rather than the multi-GB CUDA build.

## What publication would actually buy us
Modest, and worth being honest about: grid jobs do **not** use this venv (they run
`art`/`mu2e` from the Musing tarball), so there is no grid-side win. The wins are
(a) a second operator needs no build step, (b) it comes off the personal `/exp`
quota — which filled once already
([data-quota-exhausted-grid-accumulation](/incidents/data-quota-exhausted-grid-accumulation.md)),
and (c) the strongest one: an **immutable, versioned stack that a past campaign can
be reproduced against**. Costs: no mid-campaign pin hotfixes, and we must always
activate an **explicit version, never `current`** — a `current` that moves between
BO rounds would change the numerical stack under a running campaign.

## Cross-links
- Related: [pyutils-analysis-env](/external/pyutils-analysis-env.md) (the `pyenv ana`
  run recipe + CWD-shadowing gotcha), [mu2e-offline](/external/mu2e-offline.md)
- Related: [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md)
  (why the venv lives on /data behind a root symlink),
  [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md) (why the pins are
  what they are)
- Source files: `requirements.txt`, `setup.sh` (`--venv` links a shared venv),
  `README.md` build recipe
- External: `/cvmfs/mu2e.opensciencegrid.org/bin/pyenv.sh`,
  `/cvmfs/mu2e.opensciencegrid.org/env/{ana,rootana,trkqual}/`, EAF change log on
  mu2ewiki

## Open questions / TODO
- **Request not sent.** Ask the EAF/analysis-tools maintainers (owners of the EAF
  change log that `pyenv.sh` points at) for the *slot and process* first; publish a
  first version only after portable-paths lands and the pins settle.
- Is a numpy-2.x `ana` already planned? If so the 9-package ML ask is far cheaper
  than a sibling env and should be the opening position.
- Who actually owns `env/`? Not identified — `pyenv.sh` names no maintainer.
- Should we move to 3.12 regardless of publication? It costs nothing (verified) and
  matches `ana`/`rootana`, but `trkqual` shows 3.11 is fine, so there is no forcing
  reason yet.
