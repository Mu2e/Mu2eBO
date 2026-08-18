# Publishing the BO stack to a CVMFS `pyenv` env — work plan

**Goal:** stop shipping this project's Python stack as a personal `/exp` venv and
get its ML core into `/cvmfs/mu2e.opensciencegrid.org/env/`, so a second operator
needs no build step and past campaigns can be reproduced against an immutable,
versioned prefix.

**Background + all measurements:** `wiki/external/mu2e-cvmfs-python-envs.md`
(measured 2026-08-12). Read that first — this plan does not repeat the numbers.

**Be honest about the payoff.** Grid jobs run `art`/`mu2e` from the Musing
tarball and never touch this venv, so there is **no grid-side win**. The wins are
(a) no build step for a second operator, (b) 1.2 GB off a personal quota that has
filled once already, (c) reproducibility. Costs: no mid-campaign pin hotfixes,
and campaigns must activate an explicit version — never `current`, which moving
between BO rounds would change the numerical stack under a running campaign.

---

## Phase 1 — our side (do this before contacting anyone)

Envs are **immutable published prefixes**. A venv cannot be moved there; it can
only be rebuilt as a release from a lockfile. We cannot currently produce one.

- [x] **Emit a lockfile.** *(done 2026-08-17)* `requirements.lock` — 77 packages,
      1744 hashes, `--require-hashes` clean, dry-run against the live venv
      reports "would make no changes". Constrained to the **verified installed
      venv**, not re-resolved: a fresh unconstrained resolve moved 20 packages
      the same day. `requirements.txt` stays the human-readable intent.
- [ ] **Land portable paths on the default branch.** Done on `local-executor`
      (`setup.sh` root resolution + `tests/test_no_hardcoded_paths.py`), still
      unmerged into `json-modes`. The build recipe in `requirements.txt` must
      stop hardcoding `/exp/mu2e/data/users/oksuzian/...`.
- [ ] **Re-verify Python 3.12.** The 3.12 run was green at 471 tests; the suite
      is now 612. Rebuild `.venv312` from the lockfile and re-run. `ana` and
      `rootana` are both 3.12, so this decides whether we need a sibling env or
      can ride an existing one.
- [ ] **Split the dependency list in two, explicitly.** Only **9 packages are the
      ML core** (`torch==2.13.0+cpu`, `botorch`, `gpytorch`, `linear-operator`,
      `multipledispatch`, `pyre-extensions`, `typing-inspect`, `mypy-extensions`,
      `ninja`). The other **19 are the LangGraph/LangSmith orchestrator cluster**,
      which no analysis user will ever import. Make the split mechanical — two
      requirements files — so the ask is 9 packages, not 29.

## Phase 2 — the ask

Nobody has been contacted, and `pyenv.sh` names no maintainer for `env/`.

- [ ] **Identify the owner.** Start with the EAF/analysis-tools maintainers who
      own the EAF change log `pyenv.sh` points at. Ask for the *slot and
      process* first — not for a publish.
- [ ] **Opening position: 9 ML packages riding a numpy-2.x `ana`.** `ana` is the
      better target (14 conflicts vs `rootana`'s 26, and 13 of the 14 are trivial
      point drift we simply accept). `rootana`'s reason to exist — bundled
      PyROOT — buys us nothing, because our ROOT reads already run under
      `muse setup`. **First question to ask: is a numpy-2.x `ana` already
      planned?** If yes, this is a cheap package add and we are done.
- [ ] **Fallback: a sibling env.** `ana` ships numpy 1.26.4; torch 2.13 +
      botorch 0.18 need numpy 2.x, and moving `ana` to numpy 2 forces a recompile
      of every C-extension in it — a major release, not a package add. If that is
      not on their roadmap, ask for a sibling instead. **Precedent:
      `env/trkqual/`** is published alongside `ana`/`rootana` but advertised by
      neither, on py3.11 with torch — a working-group-specific ML env is an
      accepted thing. Quote **1.2 GB, 77 packages, `+cpu` torch deliberately**
      (not the multi-GB CUDA build).

## Phase 3 — adopt

- [ ] Publish one version only after the pins settle. Do not publish mid-campaign.
- [ ] Pin campaigns to an **explicit version**; make `current` unusable from our
      launch path so nobody can pick it up by accident.
- [ ] Keep `setup.sh --venv` working. A local venv stays the supported path for
      pin hotfixes and picker A/Bs (`AUTORESEARCH_BOTORCH_VENV`), and remains the
      only option while a published version is in flight.

## Non-goals

- Publishing the LangGraph orchestrator half. It stays local.
- Any grid-side change. Grid jobs are unaffected by all of this.
- Moving off Python 3.11 for its own sake — `trkqual` shows 3.11 is fine, so
  3.12 matters only if it makes an `ana` slot possible.
