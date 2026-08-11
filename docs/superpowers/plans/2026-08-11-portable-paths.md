# Portable Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every hardcoded `/exp/mu2e/{app,data}/users/oksuzian/...` path from the code so a second Mu2e operator can clone the repo and run their own campaigns against their own volumes.

**Architecture:** One stdlib-only module, `core/paths.py`, resolves every root once — the repo root from `Path(__file__)`, the data and artifact roots from env vars with per-`$USER` defaults, and a muse-style `backing` symlink for shared read-only build artifacts (local wins, backing fills in). The 22 files carrying literals import from it instead. Committed leaderboards become a read-only archive; live rows append to the operator's own `/data` area.

**Tech Stack:** Python 3.11 (stdlib only for `core/paths.py`), `unittest`, bash for `setup.sh`. No new dependencies.

Spec: `docs/superpowers/specs/2026-08-11-portable-paths-design.md`.

## Global Constraints

- **`core/paths.py` is stdlib-only and imports nothing from the rest of the project** — same rule `core/leaderboard.py` follows, so the botorch venv subprocess and the tests import it with no path games.
- **Importing `core/paths.py` never raises for a missing path and never requires `/exp/mu2e` to exist.** It performs exactly one `lstat` (the `backing` symlink probe). Only `artifact()` and `verify()` stat beyond that.
- **The full suite must stay green with no `AUTORESEARCH_*` variable set.** Baseline as of 2026-08-11: `Ran 422 tests ... OK (skipped=1)`.
- **Test command:** `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`. The leading blank `PYTHONPATH=` is required — it clears what a sourced Mu2e/cvmfs environment leaves behind. Single file: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"`.
- **Golden parity must still pass:** `PYTHONPATH= .venv/bin/python tests/golden_parity.py check` (manual, not in discover).
- **Zero behaviour change for the current operator.** With `$USER=oksuzian` and no overrides, every resolved path must be byte-identical to today's literal. Task 4 has an explicit before/after diff step proving it.
- **Do not commit `wiki/` edits** — project convention is that they stay uncommitted for operator review. Do not `git push`. Stage explicit paths only; never `git add -A`/`-u`/`.`.
- **Commit trailers** (every commit in this plan):
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
  ```
- **MERGE GATE — do not merge to `json-modes`/`main` while closed-loop children are in flight.** Children re-execute the working tree. `foilspfbpz07` was running when this plan was written. Check with `pgrep -f "closed_loop"` and wait for drain. Implementation on a branch is fine at any time.

## Deviations from the spec (deliberate, with reasons)

1. **`verify()` does not validate archive leaderboard headers** (spec §"verify(modes)" item 3). Doing so would require `paths.py` to import `leaderboard.py`, breaking the stdlib-only constraint, which is a stronger invariant. The protection already exists twice over: `Leaderboard.load()` raises `SchemaMismatch` on a bad header at first use, and `tests/test_live_leaderboard_headers.py` checks every tracked file permanently in the suite. Task 5 extends that test to the archive files.
2. **`Leaderboard.load()` de-duplicates by `cfg`, archive-wins.** The spec did not specify this. Promotion of live rows into the committed archive is a manual git commit, so a promoted-but-not-deleted live row would otherwise appear twice in the GP training set — silent contamination of exactly the class this project keeps hitting. One `set` and a condition; Task 5 tests it.

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `core/paths.py` | The only module that knows a filesystem layout. Resolves `REPO_ROOT`, `DATA_ROOT`, `ARTIFACT_ROOT`, `BACKING`, the three derived data roots, and the `artifact()` / `leaderboard_*()` helpers. Owns `verify()`. |
| `setup.sh` | Operator-facing skin: `--status`, `--backing`, sourced export. Mirrors `muse setup` / `muse backing` / `muse status`. |
| `tests/test_paths.py` | Unit tests for resolution, `artifact()` link order, and `verify()`. |
| `tests/test_no_hardcoded_paths.py` | Permanent anti-regression: no `users/oksuzian` in tracked sources. |
| `tests/test_setup_sh.py` | Subprocess tests for `setup.sh`. |

**Modified:** `core/bo_driver.py`, `core/botorch_predict.py`, `core/harvest.py`, `core/pipeline.py`, `core/mode_json.py`, `core/leaderboard.py`, `graph/config.py`, `graph/pipeline_io.py`, `graph/closed_loop.py`, 11 × `mode_specs/*.json`, 3 × `tests/fixtures/modes/*.json`, `tests/golden_parity.py`, `tests/test_wal_multiwriter_stress.py`, `tests/test_live_leaderboard_headers.py`, `tests/test_leaderboard.py`, `tests/test_modes.py`, `tests/test_mode_json.py`, `tests/test_botorch_predict.py`, `tests/test_seam_protocol.py`, `tests/test_audit_fixes.py`, `tests/test_json_mode.py`, `README.md`, `requirements.txt`.

---

### Task 1: `core/paths.py` — the resolver

**Files:**
- Create: `core/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `class PathsError(RuntimeError)`
  - `REPO_ROOT: Path`, `DATA_ROOT: Path`, `ARTIFACT_ROOT: Path`, `BACKING: Path | None`
  - `GRID_DATA_ROOT: Path`, `GRAPH_DATA: Path`, `LEADERBOARD_LIVE: Path`
  - `artifact(rel: str) -> Path`
  - `leaderboard_archive(rel: str) -> Path`
  - `leaderboard_live(rel: str) -> Path`

  `verify()` is added later, in Task 6.

**Context you need:** the constants are module-level (matching `graph/config.py`'s existing style), so tests vary the environment with `mock.patch.dict(os.environ, ...)` followed by `importlib.reload(paths)`. Always reload once more in `tearDown` with the original environment, or later tests inherit a patched module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths.py`:

```python
"""Unit tests for core/paths.py — the single filesystem-root resolver.

Constants are module-level, so environment variation is done with
mock.patch.dict + importlib.reload, and tearDown reloads once more with the
pristine environment so later tests do not inherit a patched module.
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402


def reload_with(**env):
    """Reload paths with exactly `env` overlaid on a USER-only environment."""
    base = {"USER": "testuser"}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return importlib.reload(paths)


class TestPathsResolution(unittest.TestCase):
    def tearDown(self):
        importlib.reload(paths)   # restore the real environment's view

    def test_repo_root_is_the_directory_holding_core_and_graph(self):
        p = reload_with()
        self.assertTrue((p.REPO_ROOT / "core" / "paths.py").is_file())
        self.assertTrue((p.REPO_ROOT / "graph" / "config.py").is_file())

    def test_repo_root_matches_this_test_files_own_derivation(self):
        p = reload_with()
        self.assertEqual(p.REPO_ROOT, ROOT)

    def test_data_root_defaults_to_the_users_data_volume(self):
        p = reload_with()
        self.assertEqual(p.DATA_ROOT, Path("/exp/mu2e/data/users/testuser"))
        self.assertEqual(p.ARTIFACT_ROOT, Path("/exp/mu2e/app/users/testuser"))

    def test_env_override_beats_the_user_default(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d",
                        AUTORESEARCH_ARTIFACT_ROOT="/scratch/a")
        self.assertEqual(p.DATA_ROOT, Path("/scratch/d"))
        self.assertEqual(p.ARTIFACT_ROOT, Path("/scratch/a"))

    def test_derived_data_roots_hang_off_data_root(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.GRID_DATA_ROOT, Path("/scratch/d/autoresearch_grid"))
        self.assertEqual(p.GRAPH_DATA,
                         Path("/scratch/d/autoresearch_graph_data"))
        self.assertEqual(p.LEADERBOARD_LIVE,
                         Path("/scratch/d/autoresearch_leaderboards"))

    def test_unset_user_raises_instead_of_inventing_a_path(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(paths.PathsError) as cm:
                importlib.reload(paths)
        self.assertIn("AUTORESEARCH_DATA_ROOT", str(cm.exception))

    def test_import_does_not_require_exp_mu2e_to_exist(self):
        # Resolution is string math: a root pointing at a nonexistent tree
        # must import cleanly. Only artifact()/verify() stat.
        p = reload_with(AUTORESEARCH_DATA_ROOT="/no/such/tree/d",
                        AUTORESEARCH_ARTIFACT_ROOT="/no/such/tree/a")
        self.assertEqual(p.DATA_ROOT, Path("/no/such/tree/d"))
        self.assertFalse(p.DATA_ROOT.exists())


class TestArtifactLinkOrder(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        (self.tmp / "local").mkdir()
        (self.tmp / "backing").mkdir()

    def tearDown(self):
        self._td.cleanup()
        importlib.reload(paths)

    def _paths(self):
        return reload_with(
            AUTORESEARCH_ARTIFACT_ROOT=str(self.tmp / "local"),
            AUTORESEARCH_BACKING=str(self.tmp / "backing"))

    def test_local_wins_over_backing(self):
        (self.tmp / "local" / "tool.sh").write_text("local\n")
        (self.tmp / "backing" / "tool.sh").write_text("backing\n")
        p = self._paths()
        self.assertEqual(p.artifact("tool.sh").read_text(), "local\n")

    def test_backing_fills_in_what_local_lacks(self):
        (self.tmp / "backing" / "tool.sh").write_text("backing\n")
        p = self._paths()
        self.assertEqual(p.artifact("tool.sh").read_text(), "backing\n")

    def test_miss_returns_the_intended_local_path_and_never_raises(self):
        p = self._paths()
        got = p.artifact("nowhere/tool.sh")
        self.assertEqual(got, self.tmp / "local" / "nowhere" / "tool.sh")
        self.assertFalse(got.exists())

    def test_no_backing_configured_is_fine(self):
        p = reload_with(AUTORESEARCH_ARTIFACT_ROOT=str(self.tmp / "local"))
        self.assertIsNone(p.BACKING)
        self.assertEqual(p.artifact("tool.sh"), self.tmp / "local" / "tool.sh")

    def test_absolute_rel_is_rejected(self):
        p = self._paths()
        with self.assertRaises(paths.PathsError):
            p.artifact("/etc/passwd")


class TestLeaderboardPaths(unittest.TestCase):
    def tearDown(self):
        importlib.reload(paths)

    def test_archive_keeps_the_repo_relative_path(self):
        p = reload_with()
        self.assertEqual(p.leaderboard_archive("leaderboards/lb_x.tsv"),
                         p.REPO_ROOT / "leaderboards" / "lb_x.tsv")

    def test_live_flattens_to_the_basename(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.leaderboard_live("leaderboards/lb_x.tsv"),
                         Path("/scratch/d/autoresearch_leaderboards/lb_x.tsv"))

    def test_absolute_leaderboard_rel_is_rejected(self):
        p = reload_with()
        with self.assertRaises(paths.PathsError):
            p.leaderboard_live("/tmp/escaped.tsv")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: `ModuleNotFoundError: No module named 'paths'`.

- [ ] **Step 3: Write `core/paths.py`**

```python
"""Single source of truth for every filesystem root this project uses.

Stdlib only, and it imports nothing from the rest of the project, so the
botorch venv subprocess and the test suite can import it with no path games
(the same rule core/leaderboard.py follows).

Resolution is string math. Importing this module performs exactly one lstat
(the `backing` symlink probe), never requires /exp/mu2e to exist, and never
raises for a missing path. Only artifact() and verify() stat beyond that --
which is what keeps the suite green on a machine with no /exp/mu2e.

Layout borrowed from Mu2e's own build system (see museSetup.sh /
museBacking.sh on cvmfs): location is identity, a `backing` link supplies
what you have not built yourself, and a setup-time gate refuses a backing
that cannot deliver. Full rationale, including what we deliberately do NOT
copy from muse (cwd-as-identity), is in
docs/superpowers/specs/2026-08-11-portable-paths-design.md.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathsError(RuntimeError):
    """A root could not be resolved, or verify() found a missing input."""


# Deliberately NOT configurable: this is not a preference, it is where the
# code is. An env override could only ever let the two disagree. Verified
# equal to the old hardcoded constant before this module existed.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _root_from_env_or_user(env_var: str, volume: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override)
    user = os.environ.get("USER")
    if not user:
        raise PathsError(
            f"cannot resolve the /exp/mu2e/{volume} root: $USER is unset and "
            f"${env_var} is not set. Export ${env_var} explicitly -- cron and "
            f"service accounts routinely have no $USER, and inventing a path "
            f"here would silently create an empty tree (see "
            f"wiki/incidents/touched-leaderboard-headerless-history-loss.md "
            f"for what an empty leaderboard costs).")
    return Path(f"/exp/mu2e/{volume}/users/{user}")


DATA_ROOT = _root_from_env_or_user("AUTORESEARCH_DATA_ROOT", "data")
ARTIFACT_ROOT = _root_from_env_or_user("AUTORESEARCH_ARTIFACT_ROOT", "app")


def _resolve_backing() -> Path | None:
    """A `backing` symlink in the repo root wins over the env var, so the
    operator's explicit `./setup.sh --backing` beats a stale export."""
    link = REPO_ROOT / "backing"
    if link.is_symlink():
        return Path(os.path.realpath(link))
    env = os.environ.get("AUTORESEARCH_BACKING")
    return Path(env) if env else None


BACKING = _resolve_backing()

# Per-operator runtime volumes. Everything the runner writes derives from
# DATA_ROOT: grid work trees, parent/child logs, and this operator's own
# appendable leaderboards.
GRID_DATA_ROOT = DATA_ROOT / "autoresearch_grid"
GRAPH_DATA = DATA_ROOT / "autoresearch_graph_data"
LEADERBOARD_LIVE = DATA_ROOT / "autoresearch_leaderboards"


def _relative(rel: str, what: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        raise PathsError(
            f"{what} must be relative, got {rel!r}: pathlib's '/' operator "
            f"silently DISCARDS the left side when the right side is "
            f"absolute, so an absolute value escapes the root instead of "
            f"erroring.")
    return p


def artifact(rel: str) -> Path:
    """Muse's link order in one function: local wins, backing fills in.

    Total -- never raises for a missing file. A miss returns the INTENDED
    local path, so a caller's error message names where the operator meant
    to put it. verify() is the single place that turns a miss into a
    failure, which is why spec loading at import cannot explode in a bare
    environment.
    """
    p = _relative(rel, "artifact() path")
    local = ARTIFACT_ROOT / p
    if local.exists():
        return local
    if BACKING is not None:
        backed = BACKING / p
        if backed.exists():
            return backed
    return local


def leaderboard_archive(rel: str) -> Path:
    """The committed read-only priors, at their repo-relative path."""
    return REPO_ROOT / _relative(rel, "leaderboard 'file'")


def leaderboard_live(rel: str) -> Path:
    """This operator's own appendable board. The live tree is FLAT, so only
    the basename survives -- which is why core/mode_json.py enforces
    uniqueness on the basename rather than the whole relative path."""
    return LEADERBOARD_LIVE / _relative(rel, "leaderboard 'file'").name
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: `OK`.

- [ ] **Step 5: Verify the derived root equals the old literal**

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import paths
old = '/exp/mu2e/app/users/oksuzian/autoresearch'
print('REPO_ROOT :', paths.REPO_ROOT)
print('identical :', str(paths.REPO_ROOT) == old)
assert str(paths.REPO_ROOT) == old
"
```

Expected: `identical : True`. If this fails, stop — the whole plan assumes it.

- [ ] **Step 6: Run the full suite (nothing imports paths yet, so it must be unchanged)**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: `Ran 44x tests` / `OK (skipped=1)` — the baseline 422 plus the new `test_paths.py` cases.

- [ ] **Step 7: Commit**

```bash
git add core/paths.py tests/test_paths.py
git commit -F - <<'EOF'
feat(paths): single filesystem-root resolver

core/paths.py resolves REPO_ROOT from __file__ and DATA_ROOT/ARTIFACT_ROOT
from env vars with per-$USER defaults, plus a muse-style `backing` link
where local artifacts win and the backing fills in. Stdlib-only and
project-import-free, so the botorch subprocess and the tests import it with
no path games.

Resolution is string math: import does exactly one lstat (the backing
probe), never requires /exp/mu2e, and never raises for a missing path.
Only artifact() stats, and it is total -- a miss returns the intended local
path so callers can name it. That keeps spec loading safe in a bare
environment; verify() (next) is the single place a miss becomes a failure.

$USER unset with no override raises rather than inventing a path: an
invented root silently creates an empty tree, which is how
touched-leaderboard-headerless-history-loss cost a campaign.

No consumers yet -- the 22 files carrying literals are rewired next.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 2: Rewire the repo-root literals

**Files:**
- Modify: `core/bo_driver.py:47`, `core/harvest.py:64`, `core/botorch_predict.py:26`, `core/pipeline.py:965`, `graph/config.py:7`, `graph/pipeline_io.py:22`
- Test: `tests/test_paths.py` (add a class)

**Interfaces:**
- Consumes: `paths.REPO_ROOT` (Task 1).
- Produces: nothing new. The existing module-level names keep their spelling — `ROOT` in `bo_driver.py`, `AUTORESEARCH` in `harvest.py`/`pipeline.py`/`botorch_predict.py`, `PROJECT_ROOT` in `graph/config.py` — so no call sites change.

**Context you need.** Five of these six modules can `import paths` directly because `core/` is already on `sys.path` by the time they are imported (they already do bare `import modes` / `from leaderboard import ...`). Two need care:

- `core/botorch_predict.py` puts `core/` on `sys.path` itself, so it must do that *before* `import paths`.
- `graph/config.py` puts `core/` on `sys.path` at line 12 but needs the root at line 7 — a chicken-and-egg. It bootstraps with a two-line `Path(__file__)` derivation, then imports `paths` and takes the value from there, so `paths` remains the single definition.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paths.py`, before the `if __name__` block:

```python
class TestEveryModuleAgreesOnTheRoot(unittest.TestCase):
    """The point of the module: one definition, not five copies that can
    drift. Each consumer keeps its own historic constant name; all must be
    the same object value as paths.REPO_ROOT."""

    def test_core_modules_use_the_resolver(self):
        import bo_driver
        import botorch_predict
        import harvest
        import pipeline
        self.assertEqual(bo_driver.ROOT, paths.REPO_ROOT)
        self.assertEqual(harvest.AUTORESEARCH, paths.REPO_ROOT)
        self.assertEqual(pipeline.AUTORESEARCH, paths.REPO_ROOT)
        self.assertEqual(botorch_predict.AUTORESEARCH, paths.REPO_ROOT)

    def test_graph_modules_use_the_resolver(self):
        sys.path.insert(0, str(ROOT / "graph"))
        import config
        self.assertEqual(config.PROJECT_ROOT, paths.REPO_ROOT)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: FAIL — the constants are still `Path("/exp/mu2e/app/users/oksuzian/autoresearch")` string literals, which happen to compare *equal* today. **If this test passes before the change, that is expected** (the literal and the derivation are the same value on this machine): treat Step 2 as informational, and rely on Task 8's grep test for the real enforcement. Record which happened in your report.

- [ ] **Step 3: Rewire `core/bo_driver.py`**

Replace line 47:

```python
ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
```

with:

```python
from paths import REPO_ROOT as ROOT  # single root resolver, see core/paths.py
```

Place it immediately after the existing `from leaderboard import (...)` block (line ~44), so it sits with the other `core/`-local imports.

- [ ] **Step 4: Rewire `core/harvest.py`**

Replace line 64:

```python
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
```

with:

```python
from paths import REPO_ROOT as AUTORESEARCH  # see core/paths.py
```

`harvest.py` documents itself as stdlib-only; `paths.py` is stdlib-only and imports nothing from the project, so this does not weaken that property. Keep the two derived constants (`EDEP_FCL`, `SENSITIVITY_MACRO`) exactly as they are.

- [ ] **Step 5: Rewire `core/botorch_predict.py`**

Replace lines 26-27:

```python
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
sys.path.insert(0, str(AUTORESEARCH / "core"))  # BO/pipeline modules (2026-07-17 reorg)
```

with:

```python
# This file lives in core/, so its own directory IS the core/ dir. Bootstrap
# sys.path from it, then take the root from the resolver.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import REPO_ROOT as AUTORESEARCH  # noqa: E402  (see core/paths.py)
```

- [ ] **Step 6: Rewire `core/pipeline.py`**

Replace line 965:

```python
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
```

with:

```python
from paths import REPO_ROOT as AUTORESEARCH  # see core/paths.py
```

Also update the two stale path mentions in comments so they do not name a person — `pipeline.py:13` (module docstring) becomes `<DATA_ROOT>/autoresearch_grid/<cfg>/` and `pipeline.py:102` becomes `<ARTIFACT_ROOT>/autoresearch_muse/ (mgit Mu2eG4 sparse`.

- [ ] **Step 7: Rewire `graph/config.py`**

Replace line 7 and the sys.path block at lines 10-12:

```python
PROJECT_ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
# The BO/pipeline modules live in core/ (2026-07-17 reorg). Put it on
# sys.path so bare `import modes` / `import bo_driver` resolve
# from any graph entrypoint regardless of import order.
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(PROJECT_ROOT / "core"))
```

with:

```python
# The BO/pipeline modules live in core/ (2026-07-17 reorg). Put it on
# sys.path so bare `import modes` / `import bo_driver` resolve from any
# graph entrypoint regardless of import order. This has to happen BEFORE
# `import paths`, so the repo root is bootstrapped from this file's own
# location; paths.REPO_ROOT is then the single definition everyone uses.
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from paths import REPO_ROOT as PROJECT_ROOT  # noqa: E402  (see core/paths.py)
```

- [ ] **Step 8: Rewire `graph/pipeline_io.py`**

Replace line 22:

```python
sys.path.insert(0, "/exp/mu2e/app/users/oksuzian/autoresearch/core")
```

with:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
```

`Path` is already imported at line 18. Do not add a `paths` import here — this module only needs `core/` on `sys.path`, and it imports `GRID_DATA_ROOT` from `config` in Task 3.

- [ ] **Step 9: Run the full suite**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: `OK (skipped=1)`, same count as after Task 1 plus the 2 new tests.

- [ ] **Step 10: Run golden parity**

```bash
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: PASS. If it fails, the geometry renderers are reading a path they should not — stop and report.

- [ ] **Step 11: Commit**

```bash
git add core/bo_driver.py core/harvest.py core/botorch_predict.py \
        core/pipeline.py graph/config.py graph/pipeline_io.py tests/test_paths.py
git commit -F - <<'EOF'
refactor(paths): derive the repo root instead of hardcoding it

Five copies of `/exp/mu2e/app/users/oksuzian/autoresearch` plus one
sys.path literal become one import from core/paths.py. Each consumer keeps
its historic constant name (ROOT, AUTORESEARCH, PROJECT_ROOT), so no call
site changes.

graph/config.py needs the root before core/ is on sys.path, so it
bootstraps sys.path from its own __file__ and then imports paths -- the
resolver stays the single definition.

Verified: the derived value is byte-identical to the literal it replaces.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 3: Rewire the data roots

**Files:**
- Modify: `graph/config.py:16,33,158`, `core/bo_driver.py:428,833,850`, `tests/golden_parity.py:114`, `tests/test_wal_multiwriter_stress.py:213`
- Test: `tests/test_paths.py` (add a class)

**Interfaces:**
- Consumes: `paths.GRID_DATA_ROOT`, `paths.GRAPH_DATA` (Task 1).
- Produces: `graph.config.GRAPH_DATA` and `graph.config.GRID_DATA_ROOT` keep their names and remain the import site for `graph/run.py`, `graph/closed_loop.py`, `graph/pipeline_io.py` and `core/pipeline.py` — none of those change.

**Context you need.** The seam already exists and is well used: 15 call sites already import `GRID_DATA_ROOT` / `GRAPH_DATA` from `graph/config.py`. The bug this task fixes is that `core/bo_driver.py` **bypasses** that seam three times with its own inline copy of the grid root, which can silently disagree with `config.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_paths.py`, before the `if __name__` block:

```python
class TestDataRootsHaveOneDefinition(unittest.TestCase):
    """bo_driver.py used to carry three private copies of the grid-data root
    that could drift from graph/config.py's. After the rewiring there is one
    definition and every consumer agrees with it."""

    def tearDown(self):
        importlib.reload(paths)

    def test_config_data_roots_come_from_the_resolver(self):
        sys.path.insert(0, str(ROOT / "graph"))
        import config
        self.assertEqual(config.GRID_DATA_ROOT, paths.GRID_DATA_ROOT)
        self.assertEqual(config.GRAPH_DATA, paths.GRAPH_DATA)

    def test_bo_driver_no_longer_carries_its_own_grid_root(self):
        src = (ROOT / "core" / "bo_driver.py").read_text()
        self.assertNotIn("/exp/mu2e/data/users/", src)
        self.assertIn("GRID_DATA_ROOT", src)

    def test_grid_root_tracks_a_data_root_override(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT="/scratch/d")
        self.assertEqual(p.GRID_DATA_ROOT,
                         Path("/scratch/d/autoresearch_grid"))
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: FAIL on `test_bo_driver_no_longer_carries_its_own_grid_root` — the literal `Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")` is still there.

- [ ] **Step 3: Rewire `graph/config.py`**

Replace line 16:

```python
GRAPH_DATA = Path("/exp/mu2e/data/users/oksuzian/autoresearch_graph_data")
```

with:

```python
from paths import GRAPH_DATA  # noqa: E402  (per-operator; see core/paths.py)
```

Replace line 33:

```python
GRID_DATA_ROOT = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
```

with:

```python
from paths import GRID_DATA_ROOT  # noqa: E402  (per-operator)
```

Keep both surrounding comment blocks — they explain *why* the runtime volumes live off `/app`, which is still true. Update the comment at line 158 from the literal to `($GRAPH_DATA/STOP_CLOSED_LOOP)`.

- [ ] **Step 4: Rewire the three `core/bo_driver.py` sites**

Add to the import block near `from paths import REPO_ROOT as ROOT` (added in Task 2):

```python
from paths import GRID_DATA_ROOT
```

Then at line ~428 replace:

```python
        work_geom_dir = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid") / name / "geom"
```

with:

```python
        work_geom_dir = GRID_DATA_ROOT / name / "geom"
```

And at both line ~833 and line ~850 replace:

```python
        keep_dir = (Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
                    / name / "geom")
```

with:

```python
        keep_dir = GRID_DATA_ROOT / name / "geom"
```

- [ ] **Step 5: Rewire `tests/golden_parity.py`**

At line ~114 replace:

```python
    grid = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")
```

with:

```python
    grid = paths.GRID_DATA_ROOT
```

and add `import paths  # noqa: E402` next to the file's existing `core/`-path imports (it already does `sys.path.insert` for `core/`; check the top of the file and put it with the others).

- [ ] **Step 6: Rewire `tests/test_wal_multiwriter_stress.py`**

At line ~213 replace:

```python
    ceph_db = Path("/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/stress_test/test_ceph.sqlite")
```

with:

```python
    ceph_db = paths.GRAPH_DATA / "stress_test" / "test_ceph.sqlite"
```

Add the import at the top of the file, following the pattern already used by `tests/test_live_leaderboard_headers.py`:

```python
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "core"))
import paths  # noqa: E402
```

This file is a manual stress script with zero `TestCase` classes (see `wiki/drivers/tests.md`), so `discover` will not execute `main()` — the edit is for correctness, not for the suite.

- [ ] **Step 7: Run the full suite and golden parity**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: `OK (skipped=1)` and golden parity PASS.

- [ ] **Step 8: Commit**

```bash
git add graph/config.py core/bo_driver.py tests/golden_parity.py \
        tests/test_wal_multiwriter_stress.py tests/test_paths.py
git commit -F - <<'EOF'
refactor(paths): one definition for the grid and graph data roots

graph/config.py takes both roots from core/paths.py, so they follow
$USER (or AUTORESEARCH_DATA_ROOT) instead of naming a person. The 15
call sites that already import them from config are untouched.

Also removes three private copies of the grid-data root inside
bo_driver.py (:428, :833, :850) that bypassed that seam entirely and
could silently disagree with it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 4: `${ARTIFACT}` token in mode specs

**Files:**
- Modify: `core/mode_json.py` (spec build ~line 396-400; uniqueness check ~line 455)
- Modify: `core/pipeline.py:402-404` (Run1BAna EdepAna lib + the muse workdir `cd`)
- Modify: `mode_specs/foilsflash.json`, `foilspf.json`, `foilspf2k.json`, `foilspfbp.json`, `foilspfbpx.json`, `foilspfbpz.json`, `foilspfbw.json`, `ipa625.json`, `ipafix.json`, `ipaovr.json`, `nominal.json` (11 files)
- Modify: `tests/fixtures/modes/foils.json`, `tests/fixtures/modes/foilsflash.json`, `tests/fixtures/modes/template.json`
- Test: `tests/test_mode_json.py`

**Interfaces:**
- Consumes: `paths.artifact(rel)` (Task 1).
- Produces: `ModeSpec.musing` and `ModeSpec.grid_tarball` remain **absolute `str`** — unchanged type, unchanged consumers (`graph/config.py` reads `_SPEC.musing`, `core/pipeline.py` reads `grid_tarball`). Only the on-disk JSON syntax changes.

**Context you need.** `software.musing` and `software.grid_tarball` are required by `_REQUIRED_SOFTWARE` at `core/mode_json.py:34` and read at `:398-399`. The values today are absolute paths under `/exp/mu2e/app/users/oksuzian/`. `ARTIFACT_ROOT` defaults to `/exp/mu2e/app/users/$USER`, so for the current operator `${ARTIFACT}/Offline_run1bap_partial/setup_local.sh` expands to *exactly* today's literal — zero behaviour change. Step 1 captures a before-snapshot to prove it.

- [ ] **Step 1: Capture the before-snapshot (do this FIRST, before any edit)**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import modes
for n, s in sorted(modes.SPECS.items()):
    print(n, s.musing); print(n, s.grid_tarball)
" > /tmp/artifact_paths_before.txt
wc -l /tmp/artifact_paths_before.txt
```

Expected: 22 lines (11 specs × 2 fields).

- [ ] **Step 2: Write the failing tests**

Append these methods to the existing test class in `tests/test_mode_json.py` that uses the `_expect_error` helper (the class containing `test_leaderboard_file_must_be_relative` around line 171 — match its style and helper usage):

```python
    def test_artifact_token_expands_against_the_artifact_root(self):
        import paths
        doc = self._doc()
        doc["software"]["musing"] = "${ARTIFACT}/MyBuild/setup_local.sh"
        spec = mode_json.build_spec(doc, "test")
        self.assertEqual(spec.musing,
                         str(paths.ARTIFACT_ROOT / "MyBuild/setup_local.sh"))

    def test_unknown_variable_token_is_rejected(self):
        self._expect_error(
            lambda d: d["software"].update({"musing": "${HOME}/x/setup.sh"}),
            "ARTIFACT")

    def test_personal_absolute_path_is_rejected(self):
        self._expect_error(
            lambda d: d["software"].update(
                {"musing": "/exp/mu2e/app/users/somebody/x/setup.sh"}),
            "${ARTIFACT}")

    def test_leaderboards_colliding_on_basename_are_rejected(self):
        # The live tree is flat, so a/x.tsv and b/x.tsv would become one
        # file even though their declarations differ.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i, rel in enumerate(("a/lb_dup.tsv", "b/lb_dup.tsv")):
                doc = self._doc()
                doc["name"] = f"dupmode{i}"
                doc["leaderboard"]["file"] = rel
                (d / f"dupmode{i}.json").write_text(json.dumps(doc))
            with self.assertRaises(ValueError) as cm:
                mode_json.load_mode_dir(d, {})
        self.assertIn("basename", str(cm.exception).lower())
```

If `tests/test_mode_json.py` does not already import `json`, `tempfile`, or `Path`, add them at the top. If the helper that builds a valid document is not named `self._doc()`, use whatever that file already calls it and keep the rest identical.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_mode_json.py"
```

Expected: FAIL — `${ARTIFACT}` is currently stored verbatim, and the basename collision is currently accepted.

- [ ] **Step 4: Add expansion + validation to `core/mode_json.py`**

Add near the top of the file, with the other imports:

```python
import paths
```

Add this helper next to `_normalize_leaderboard_rel` (~line 82):

```python
_ARTIFACT_TOKEN = "${ARTIFACT}/"


def _expand_artifact(value: str, field: str, where: str) -> str:
    """Expand the one supported token, `${ARTIFACT}/`, through
    paths.artifact() -- local artifact wins, backing fills in, a miss
    returns the intended local path (paths.verify() is what turns a miss
    into a failure, so spec loading stays safe in a bare environment).

    A bare absolute path under someone's user area is refused: that is how
    the tree acquired ~20 personal literals in the first place.
    """
    if value.startswith(_ARTIFACT_TOKEN):
        return str(paths.artifact(value[len(_ARTIFACT_TOKEN):]))
    if "${" in value:
        raise ValueError(
            f"{where}[software.{field}]: unknown variable in {value!r}. "
            f"The only supported token is '${{ARTIFACT}}/', which resolves "
            f"against this operator's artifact root (or the `backing` link).")
    if re.match(r"^/exp/mu2e/(app|data)/users/[^/]+/", value):
        raise ValueError(
            f"{where}[software.{field}]: {value!r} hardcodes a personal user "
            f"area, so this mode would only run for that account. Use "
            f"'${{ARTIFACT}}/<rest-of-path>' instead; see "
            f"docs/superpowers/specs/2026-08-11-portable-paths-design.md.")
    return value
```

`re` is already imported by `core/mode_json.py`; confirm before adding it.

Then at `:398-399` replace:

```python
        musing=software["musing"],
        grid_tarball=software["grid_tarball"],
```

with:

```python
        musing=_expand_artifact(software["musing"], "musing", where),
        grid_tarball=_expand_artifact(software["grid_tarball"],
                                      "grid_tarball", where),
```

- [ ] **Step 5: Tighten the leaderboard uniqueness check to the basename**

In `load_mode_dir` (~line 455), replace:

```python
        lb = spec.leaderboard_rel
        if lb in seen_leaderboards:
            raise ValueError(
                f"{path}: leaderboard {lb!r} is already declared by "
                f"{seen_leaderboards[lb]}. Two modes sharing one leaderboard "
                f"silently cross-contaminate their GP history; give each mode "
                f"its own leaderboards/*.tsv.")
        seen_leaderboards[lb] = path
```

with:

```python
        # Keyed on the BASENAME, not the relative path: live boards are a
        # flat per-operator directory (paths.leaderboard_live flattens to
        # the name), so 'a/x.tsv' and 'b/x.tsv' would become one file even
        # though the declarations differ.
        lb = Path(spec.leaderboard_rel).name
        if lb in seen_leaderboards:
            raise ValueError(
                f"{path}: leaderboard basename {lb!r} is already declared by "
                f"{seen_leaderboards[lb]}. Two modes sharing one leaderboard "
                f"silently cross-contaminate their GP history; give each mode "
                f"its own leaderboards/*.tsv with a distinct filename.")
        seen_leaderboards[lb] = path
```

- [ ] **Step 6: Convert the 11 mode specs**

In each of the 11 `mode_specs/*.json`, replace the `/exp/mu2e/app/users/oksuzian/` prefix in `software.musing` and `software.grid_tarball` with `${ARTIFACT}/`:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
for f in mode_specs/foilsflash.json mode_specs/foilspf.json \
         mode_specs/foilspf2k.json mode_specs/foilspfbp.json \
         mode_specs/foilspfbpx.json mode_specs/foilspfbpz.json \
         mode_specs/foilspfbw.json mode_specs/ipa625.json \
         mode_specs/ipafix.json mode_specs/ipaovr.json \
         mode_specs/nominal.json; do
  python - "$f" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for k in ("musing", "grid_tarball"):
    v = d["software"][k]
    pre = "/exp/mu2e/app/users/oksuzian/"
    assert v.startswith(pre), (p, k, v)
    d["software"][k] = "${ARTIFACT}/" + v[len(pre):]
open(p, "w").write(json.dumps(d, indent=2) + "\n")
print("converted", p)
PY
done
```

**Then check the diff before continuing** — `json.dumps(indent=2)` may reformat unrelated parts of the file:

```bash
git diff --stat mode_specs/
git diff mode_specs/foilspf.json | head -40
```

If the reformatting is larger than the two changed lines per file, revert (`git checkout -- mode_specs/`) and edit the 22 lines by hand with the Edit tool instead. Preserving the existing formatting matters — these files are reviewed by eye.

- [ ] **Step 7: Convert the 3 test fixtures**

Apply the same `${ARTIFACT}/` substitution by hand to `tests/fixtures/modes/foils.json`, `tests/fixtures/modes/foilsflash.json`, and `tests/fixtures/modes/template.json`. `template.json` is the documented starting point for a new mode (`mode_specs/README.md`), so it teaches the pattern — get it right.

- [ ] **Step 8: Route the Run1BAna harvest artifact through `artifact()`**

`core/pipeline.py:402-404` hardcodes the EdepAna plugin library and `cd`s into the muse workdir. Both are artifacts, so they resolve the same way. Add `import paths` to the file's imports if Task 2 did not already, then replace:

```python
        mmlib = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib"
        prelude = (
            "cd /exp/mu2e/app/users/oksuzian/autoresearch_muse && "
```

with:

```python
        _muse = paths.artifact("autoresearch_muse")
        mmlib = str(_muse / "build/al9-prof-e29-p094/Run1BAna/lib")
        prelude = (
            f"cd {_muse} && "
```

Keep the whole existing comment block above it — it records why this switched off mmackenz's path after the p094→p101 bump (`wiki/incidents/mmackenz-edepana-lib-qualifier-bump.md`), which is still the reason this constant exists.

Verify the resolved value is unchanged:

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import paths
got = str(paths.artifact('autoresearch_muse') / 'build/al9-prof-e29-p094/Run1BAna/lib')
old = '/exp/mu2e/app/users/oksuzian/autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib'
print(got); print('identical:', got == old)
assert got == old
"
```

- [ ] **Step 9: Run the tests**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: `OK (skipped=1)`.

- [ ] **Step 10: Prove zero behaviour change with the after-snapshot**

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import modes
for n, s in sorted(modes.SPECS.items()):
    print(n, s.musing); print(n, s.grid_tarball)
" > /tmp/artifact_paths_after.txt
diff /tmp/artifact_paths_before.txt /tmp/artifact_paths_after.txt && echo "IDENTICAL"
```

Expected: `IDENTICAL`. **If the diff is non-empty, stop and report** — every resolved artifact path must be unchanged for the current operator.

- [ ] **Step 11: Update `mode_specs/README.md`**

Find the section documenting the `software` block and add:

```markdown
`musing` and `grid_tarball` are written as `${ARTIFACT}/<path>`. The token
expands against this operator's artifact root — `$AUTORESEARCH_ARTIFACT_ROOT`,
or `/exp/mu2e/app/users/$USER` by default — falling through to the `backing`
link for anything not built locally (`./setup.sh --backing <path>`). A bare
absolute path under a user area is rejected at load: it would make the mode
runnable by exactly one account.
```

- [ ] **Step 12: Commit**

```bash
git add core/mode_json.py core/pipeline.py mode_specs/ tests/fixtures/modes/ \
        tests/test_mode_json.py mode_specs/README.md
git commit -F - <<'EOF'
feat(modes): ${ARTIFACT} token instead of personal absolute paths

software.musing and software.grid_tarball in all 11 specs (and the 3 test
fixtures, template.json included) become ${ARTIFACT}/<rest>, expanded at
load through paths.artifact(): local artifact wins, `backing` fills in.
The Run1BAna EdepAna lib and muse workdir in pipeline.py:402 resolve the
same way.

Two new load-time errors: an unknown ${VAR}, and a bare absolute path under
a user area -- the second is what stops the hardcode returning through a
copy-pasted spec, which is how the tree acquired ~20 of them.

Also tightens the leaderboard-uniqueness check from the whole relative path
to the basename. Live boards are a flat per-operator directory, so a/x.tsv
and b/x.tsv would silently become one file and cross-contaminate two modes'
GP history. All 11 current specs already use distinct basenames.

Verified: every resolved musing/grid_tarball is byte-identical before and
after for the current operator.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 5: Leaderboard archive + live

**Files:**
- Modify: `core/leaderboard.py` (dataclass ~123-130, `from_spec` ~141, `load` ~156, `append` ~183)
- Modify: `core/bo_driver.py:240` (`JsonMode.__init__`), `:199` (`leaderboard_io`)
- Modify: `core/botorch_predict.py:698` (CLI override)
- Modify: `tests/golden_parity.py:99,103,132,149`, `tests/test_json_mode.py:169`, `tests/test_botorch_predict.py:41`, `tests/test_seam_protocol.py:93`, `tests/test_audit_fixes.py:678`, `tests/test_live_leaderboard_headers.py:22`, `tests/test_modes.py:136`
- Test: `tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `paths.leaderboard_live(rel)`, `paths.leaderboard_archive(rel)` (Task 1).
- Produces:
  - `Leaderboard` gains `archive_path: Path | None = None` (last field, defaulted, so the 4 existing construction sites stay valid).
  - `Leaderboard.from_spec(cls, spec, *, live_root: Path, archive_root: Path) -> Leaderboard` — **signature change**; the old `root=` keyword is gone.
  - `JsonMode` gains `self.leaderboard_archive: Path | None`.

**Context you need — read this before writing code.** Seven places override `mode.leaderboard` to point at an isolated temporary board. If `leaderboard_archive` stays pointed at the repo when they do, `load()` will return the ~330 real archive rows on top of the temporary ones and those tests will break in confusing ways. **Every override site must set `leaderboard_archive = None` too.** `mock.patch.multiple` does both atomically and still auto-restores. The sites are listed in Steps 6-8; do not skip any.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_leaderboard.py` (it already has a `Leaderboard(...)` construction helper at line 23 — reuse its column/knob shape so the headers match):

```python
class TestArchivePlusLive(unittest.TestCase):
    """The committed leaderboards/ are read-only priors; this operator's own
    rows append to a separate live file. load() returns both."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.archive = self.tmp / "archive.tsv"
        self.live = self.tmp / "live" / "board.tsv"

    def tearDown(self):
        self._td.cleanup()

    def _lb(self):
        return Leaderboard(path=self.live, name="m", archive_path=self.archive,
                           knob_names=("a",), knob_fmts=("{:.3f}",),
                           metric_cols=("sob", "calo", "alpha", "obj"))

    def test_load_returns_archive_rows_then_live_rows(self):
        lb = self._lb()
        self.archive.write_text(
            lb.header()
            + "old1\t1.000\t3.10000\t1.00000e-06\t0.000\t3.10000\n")
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["old1", "new1"])

    def test_append_creates_the_live_directory(self):
        lb = self._lb()
        self.assertFalse(self.live.parent.exists())
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertTrue(self.live.exists())

    def test_append_never_writes_to_the_archive(self):
        lb = self._lb()
        self.archive.write_text(lb.header())
        before = self.archive.read_text()
        lb.append(Point(cfg="new1", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertEqual(self.archive.read_text(), before)

    def test_a_promoted_row_is_not_counted_twice(self):
        # Promotion into the committed archive is a manual git commit; a row
        # left behind in the live file must not enter the GP twice.
        lb = self._lb()
        lb.append(Point(cfg="dup", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.archive.write_text(
            lb.header()
            + "dup\t2.000\t4.00000\t2.00000e-06\t0.000\t4.00000\n")
        got = [p.cfg for p in lb.load()]
        self.assertEqual(got, ["dup"])

    def test_a_malformed_archive_header_fails_loud(self):
        lb = self._lb()
        self.archive.write_text("wrong\theader\n1\t2\n")
        with self.assertRaises(SchemaMismatch):
            lb.load()

    def test_no_archive_configured_behaves_as_before(self):
        lb = Leaderboard(path=self.live, name="m",
                         knob_names=("a",), knob_fmts=("{:.3f}",),
                         metric_cols=("sob", "calo", "alpha", "obj"))
        lb.append(Point(cfg="only", x=[2.0], sob=4.0, calo=2e-6), 0.0)
        self.assertEqual([p.cfg for p in lb.load()], ["only"])

    def test_pending_follows_the_live_file_not_the_archive(self):
        lb = self._lb()
        self.assertEqual(lb.pending_path().parent, self.live.parent)
```

Ensure `SchemaMismatch` and `Point` are imported at the top of the file; add them to the existing import if missing.

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_leaderboard.py"
```

Expected: FAIL — `Leaderboard.__init__() got an unexpected keyword argument 'archive_path'`.

- [ ] **Step 3: Add `archive_path` to `core/leaderboard.py`**

Add the field last in the dataclass (after `metric_cols`) so existing positional construction is unaffected:

```python
    archive_path: Path | None = None   # committed read-only priors
```

Replace `from_spec` (~line 141):

```python
    @classmethod
    def from_spec(cls, spec, root: Path) -> "Leaderboard":
        return cls(path=root / spec.leaderboard_rel, name=spec.name,
                   knob_names=tuple(spec.knob_names),
                   knob_fmts=tuple(spec.knob_fmts),
                   metric_cols=tuple(spec.metric_cols))
```

with:

```python
    @classmethod
    def from_spec(cls, spec, *, live_root: Path,
                  archive_root: Path) -> "Leaderboard":
        """live_root is this operator's flat board directory; archive_root is
        the repo, where the committed priors keep their relative path."""
        rel = Path(spec.leaderboard_rel)
        return cls(path=live_root / rel.name, name=spec.name,
                   knob_names=tuple(spec.knob_names),
                   knob_fmts=tuple(spec.knob_fmts),
                   metric_cols=tuple(spec.metric_cols),
                   archive_path=archive_root / rel)
```

Rename the existing `load` to a private single-file reader and add the new `load`:

```python
    def _load_one(self, path: Path) -> list[Point]:
        if not path.exists():
            return []
        out = []
        with _flock_sh(path), path.open() as f:
            first = f.readline()
            if first.rstrip("\n") != self.header().rstrip("\n"):
                raise SchemaMismatch(path, self.header(), first)
            cols = ("config", *self.knob_names, *self.metric_cols)
            reader = csv.DictReader(f, fieldnames=cols, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                try:
                    out.append(Point(
                        cfg=row["config"],
                        x=[float(row[c]) for c in self.knob_names],
                        sob=float(row[self.metric_cols[0]]),
                        calo=float(row[self.metric_cols[1]])))
                except (KeyError, ValueError, TypeError) as e:
                    raise RowParseError(path, line_no, e) from e
        return out

    def load(self) -> list[Point]:
        """Committed priors first, then this operator's own rows.

        A config appearing in BOTH is counted once, archive-wins: promoting
        live rows into the committed archive is a manual git commit, so a
        row left behind in the live file would otherwise enter the GP
        training set twice.
        """
        archive = self._load_one(self.archive_path) if self.archive_path else []
        seen = {p.cfg for p in archive}
        live = [p for p in self._load_one(self.path) if p.cfg not in seen]
        return archive + live
```

In `append`, create the live directory before the first write. Replace:

```python
        with _flock_ex(self.path):
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return
```

with:

```python
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _flock_ex(self.path):
            if not self.path.exists():
                self.path.write_text(self.header() + line)
                return
```

Do not touch `_append_quarantine`, `pending_*`, or `quarantine_path` — pending is live-only state and already derives from `self.path.parent`.

- [ ] **Step 4: Run the leaderboard tests**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_leaderboard.py"
```

Expected: `OK`.

- [ ] **Step 5: Wire `JsonMode` to the two roots**

In `core/bo_driver.py`, add to the `paths` import line:

```python
from paths import leaderboard_archive, leaderboard_live
```

Replace line ~240 in `JsonMode.__init__`:

```python
        self.leaderboard = ROOT / spec.leaderboard_rel
```

with:

```python
        # Live rows go to this operator's own /data board; the committed
        # leaderboards/ are read-only priors both operators start warm from.
        self.leaderboard = leaderboard_live(spec.leaderboard_rel)
        self.leaderboard_archive = leaderboard_archive(spec.leaderboard_rel)
```

In `leaderboard_io` (~line 199), extend the cache-invalidation check and pass the archive through:

```python
        archive = getattr(self, "leaderboard_archive", None)
        if lb is None or lb.path != self.leaderboard or lb.archive_path != archive:
            spec = _modes.SPECS[self.name]
            lb = Leaderboard(path=self.leaderboard, name=self.name,
                             knob_names=tuple(spec.knob_names),
                             knob_fmts=tuple(spec.knob_fmts),
                             metric_cols=tuple(spec.metric_cols),
                             archive_path=archive)
            self._lb_cache = lb
```

The existing comment above this block explains why the cache is path-keyed rather than first-access-keyed — keep it, and extend its first sentence to mention the archive.

- [ ] **Step 6: Update the two production override sites**

`core/botorch_predict.py:698` — an explicit `--leaderboard` means "use this file alone":

```python
    if ns.leaderboard:
        bo.MODES[ns.mode].leaderboard = Path(ns.leaderboard)
        bo.MODES[ns.mode].leaderboard_archive = None
```

`tests/golden_parity.py` at lines ~99/103 and ~132/149 — this harness swaps in a frozen board; save and restore both attributes:

```python
    orig, orig_arch = mode.leaderboard, mode.leaderboard_archive
    mode.leaderboard = FROZEN_LB
    mode.leaderboard_archive = None
    ...
    finally:
        mode.leaderboard = orig
        mode.leaderboard_archive = orig_arch
```

Apply the same shape at the second site (`lb_copy`, ~line 132/149).

- [ ] **Step 7: Update the four test override sites**

`tests/test_botorch_predict.py:41` — change the helper to patch both:

```python
    return mock.patch.multiple(bo.MODES["foilsflash"],
                               leaderboard=lb, leaderboard_archive=None)
```

`tests/test_seam_protocol.py:90-95` — the `_tmp_mode` helper builds a list of patches; replace the first entry:

```python
        patches = [
            mock.patch.multiple(
                mode,
                leaderboard=Path(tmp) / "leaderboard_bo_foilsflash.tsv",
                leaderboard_archive=None),
            mock.patch.object(mode, "proposal_dir", Path(tmp) / "proposals"),
        ]
```

`tests/test_audit_fixes.py:678`:

```python
            mock.patch.multiple(
                self.mode,
                leaderboard=self.tmp / "leaderboard_bo_probe.tsv",
                leaderboard_archive=None)
```

`tests/test_json_mode.py:169`:

```python
        mode.leaderboard = self.tmp / f"leaderboard_bo_{self.name}.tsv"
        mode.leaderboard_archive = None
```

- [ ] **Step 8: Update the two direct-construction test sites**

`tests/test_live_leaderboard_headers.py:22` — this test guards the *committed* files, so point it at the archive:

```python
            lb = Leaderboard.from_spec(spec, live_root=ROOT / "leaderboards",
                                       archive_root=ROOT)
            for target in (lb.archive_path, lb.path):
                if target is None or not target.exists():
                    continue
                with target.open() as f:
                    first = f.readline()
                self.assertEqual(
                    first.rstrip("\n"), lb.header().rstrip("\n"),
                    msg=f"{target} header != ModeSpec({name}) schema")
                checked += 1
```

`tests/test_modes.py:136` — a direct `bo.Leaderboard(...)` construction; add `archive_path=None` explicitly so the intent is visible.

- [ ] **Step 9: Run the full suite and golden parity**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: `OK (skipped=1)` and golden parity PASS. A failure mentioning unexpected leaderboard rows means an override site was missed — re-check Steps 6-8 against the list in **Files**.

- [ ] **Step 10: Verify the live board reads the real archive**

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import bo_driver as bo
m = bo.MODES['foilspfbpz']
print('live   :', m.leaderboard)
print('archive:', m.leaderboard_archive)
print('rows   :', len(m.load_history()))
"
```

Expected: live under `/exp/mu2e/data/users/oksuzian/autoresearch_leaderboards/`, archive under the repo, and a row count **equal to the archive's data-line count** (`wc -l leaderboards/leaderboard_bo_foilspfbpz.tsv` minus 1). If the count dropped to 0, the archive is not being read.

- [ ] **Step 11: Operator migration check for in-flight pending rows**

`pending_bo_*.tsv` derives from the live file's directory, so it moves to `/data` with it. Any pending row still sitting in the repo's `leaderboards/` at merge time would be orphaned:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
wc -l leaderboards/pending_bo_*.tsv 2>/dev/null
```

A file with more than 1 line (header only) has live pending rows. **Report this to the operator rather than deciding** — the fix is either to wait for drain or to copy those files into `$(PYTHONPATH= .venv/bin/python -c "import sys;sys.path.insert(0,'core');import paths;print(paths.LEADERBOARD_LIVE)")` before the first post-merge launch.

- [ ] **Step 12: Commit**

```bash
git add core/leaderboard.py core/bo_driver.py core/botorch_predict.py \
        tests/test_leaderboard.py tests/golden_parity.py \
        tests/test_json_mode.py tests/test_botorch_predict.py \
        tests/test_seam_protocol.py tests/test_audit_fixes.py \
        tests/test_live_leaderboard_headers.py tests/test_modes.py
git commit -F - <<'EOF'
feat(leaderboard): committed boards become a read-only archive

Live rows now append to this operator's own flat /data board while the
committed leaderboards/ stay in git as frozen priors. load() reads archive
then live, so a second operator starts warm from the full history without
ever contending for a file, and nothing moves on disk.

A config present in both is counted once, archive-wins: promotion is a
manual git commit, so a row left behind in the live file would otherwise
enter the GP training set twice.

Every site that overrides mode.leaderboard now clears leaderboard_archive
alongside it (mock.patch.multiple where it was patch.object) -- an override
means "use this file alone", and leaving the archive live would have fed
~330 real rows into isolated-board tests.

append() creates the live directory; pending follows the live file, as it
already derives from its parent.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 6: `paths.verify()` and its wiring

**Files:**
- Modify: `core/paths.py` (add `verify`)
- Modify: `graph/closed_loop.py` (startup), `core/bo_driver.py` (preflight entry)
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `paths.ARTIFACT_ROOT`, `paths.BACKING`, the three data roots (Task 1); expanded `spec.musing` / `spec.grid_tarball` (Task 4).
- Produces: `verify(specs, *, make_dirs: bool = True) -> None`, raising `PathsError`. `specs` is any iterable of objects with `.name`, `.musing`, `.grid_tarball` — injected, never imported, so `paths.py` stays project-import-free.

**Context you need.** This is the muse mechanic that pays for itself: `museSetup.sh:502` refuses to proceed when the backing cannot supply the required build. Two of this project's worst incidents — `prodtarget-env-divergence` and `foilsflash-tarball-mode-key-omission` — were both "preflight ran against a patched local environment while the grid silently shipped an unpatched tarball". Resolving both through one function at launch is what makes those unrepresentable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_paths.py`, before the `if __name__` block:

```python
class FakeSpec:
    def __init__(self, name, musing, grid_tarball):
        self.name, self.musing, self.grid_tarball = name, musing, grid_tarball


class TestVerify(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
        importlib.reload(paths)

    def test_passes_when_every_artifact_exists(self):
        setup = self.tmp / "setup_local.sh"
        tarball = self.tmp / "Code.tar.bz2"
        setup.write_text("")
        tarball.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(tarball))])

    def test_creates_the_three_data_dirs(self):
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(setup))])
        self.assertTrue(p.GRID_DATA_ROOT.is_dir())
        self.assertTrue(p.GRAPH_DATA.is_dir())
        self.assertTrue(p.LEADERBOARD_LIVE.is_dir())

    def test_missing_artifact_names_the_remediation_command(self):
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        with self.assertRaises(paths.PathsError) as cm:
            p.verify([FakeSpec("m", str(self.tmp / "gone.sh"),
                               str(self.tmp / "gone.tar.bz2"))])
        msg = str(cm.exception)
        self.assertIn("setup.sh --backing", msg)
        self.assertIn("gone.sh", msg)
        self.assertIn("m", msg)

    def test_make_dirs_false_does_not_create_anything(self):
        setup = self.tmp / "s.sh"
        setup.write_text("")
        p = reload_with(AUTORESEARCH_DATA_ROOT=str(self.tmp / "d"))
        p.verify([FakeSpec("m", str(setup), str(setup))], make_dirs=False)
        self.assertFalse(p.GRID_DATA_ROOT.exists())
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: `AttributeError: module 'paths' has no attribute 'verify'`.

- [ ] **Step 3: Add `verify()` to `core/paths.py`**

Append to the module:

```python
def verify(specs, *, make_dirs: bool = True) -> None:
    """Fail at launch, not three hours into a grid chain.

    `specs` is any iterable of objects carrying .name, .musing and
    .grid_tarball -- pass core.modes.SPECS.values(). Injected rather than
    imported so this module stays project-import-free.

    Modelled on museSetup.sh:502, which refuses to proceed when the backing
    build cannot supply what is needed. Both prodtarget-env-divergence and
    foilsflash-tarball-mode-key-omission were "preflight used a patched
    local environment while the grid shipped an unpatched tarball"; both
    become unrepresentable once these resolve through one function.

    Deliberately does NOT validate leaderboard headers -- that would need an
    import of leaderboard.py, breaking the stdlib-only rule. Leaderboard's
    own SchemaMismatch and tests/test_live_leaderboard_headers.py already
    cover it twice over.
    """
    for spec in specs:
        for field in ("musing", "grid_tarball"):
            p = Path(getattr(spec, field))
            if not p.exists():
                raise PathsError(
                    f"mode {spec.name!r}: {field} not found at {p}\n"
                    f"  ARTIFACT_ROOT = {ARTIFACT_ROOT}\n"
                    f"  BACKING       = {BACKING if BACKING else '(none)'}\n"
                    f"Point at an operator who has it:\n"
                    f"    ./setup.sh --backing /exp/mu2e/app/users/<them>\n"
                    f"or build your own (see README, 'Artifacts').")
    if make_dirs:
        for d in (GRID_DATA_ROOT, GRAPH_DATA, LEADERBOARD_LIVE):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise PathsError(f"cannot create {d}: {e}") from e
```

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_paths.py"
```

Expected: `OK`.

- [ ] **Step 5: Wire into `graph/closed_loop.py`**

Find the `main()` entry point (the function that reads the parsed args and creates `GRAPH_DATA / "closed_loop_logs"`, around line 856 where `GRAPH_DATA.mkdir` is called). Immediately **before** that `mkdir`, add:

```python
    import paths as _paths
    import modes as _modes_verify
    _paths.verify(_modes_verify.SPECS.values())
```

`core/` is already on `sys.path` by then (`graph/config.py` puts it there at import). Place it before any grid submission or child launch so a misconfigured environment costs seconds, not hours.

- [ ] **Step 6: Wire into the preflight entry in `core/bo_driver.py`**

Find the `preflight` subcommand handler (the function invoked for `bo_driver.py preflight`). At the top of that function, before the mode is used, add:

```python
    import paths as _paths
    _paths.verify([_modes.SPECS[mode.name]], make_dirs=False)
```

`make_dirs=False` here: preflight is a read-only feasibility check and should not create data volumes as a side effect. Only the campaign launch does that.

- [ ] **Step 7: Confirm the gate actually fires**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
AUTORESEARCH_ARTIFACT_ROOT=/tmp/definitely-not-here \
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import paths, modes
try:
    paths.verify(modes.SPECS.values())
    print('FAIL: verify did not raise')
except paths.PathsError as e:
    print('OK, raised:'); print(e)
"
```

Expected: it raises, and the message names the missing file, both roots, and the `./setup.sh --backing` command.

- [ ] **Step 8: Confirm it passes in the real environment**

```bash
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import paths, modes
paths.verify(modes.SPECS.values(), make_dirs=False)
print('all 11 modes verified')
"
```

Expected: `all 11 modes verified`. If any mode fails here, **stop** — Task 4's expansion has changed a real path.

- [ ] **Step 9: Run the full suite and golden parity**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: `OK (skipped=1)` and PASS.

- [ ] **Step 10: Commit**

```bash
git add core/paths.py graph/closed_loop.py core/bo_driver.py tests/test_paths.py
git commit -F - <<'EOF'
feat(paths): verify() gate at campaign launch and preflight

Modelled on museSetup.sh:502, which refuses to proceed when the backing
cannot supply the required build. verify() checks that every registered
mode's musing and grid_tarball actually resolve, and that the three data
volumes exist, before a single child is launched.

This is the mechanic that makes prodtarget-env-divergence and
foilsflash-tarball-mode-key-omission unrepresentable: both were "preflight
ran against a patched local environment while the grid shipped an unpatched
tarball", and both artifacts now resolve through one function.

specs are injected, not imported, so paths.py stays project-import-free.
Preflight passes make_dirs=False -- a read-only feasibility check should not
create data volumes as a side effect.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 7: `setup.sh`

**Files:**
- Create: `setup.sh` (repo root, mode 755)
- Test: `tests/test_setup_sh.py`

**Interfaces:**
- Consumes: `core/paths.py` (invoked as a subprocess via the venv python).
- Produces: a shell entry point. No Python API.

**Context you need.** `backing` is already in `.gitignore:70`, so the symlink will not show up as a working-tree change. The script must work both sourced (`source setup.sh`, to export) and executed (`./setup.sh --status`); detect with `[[ "${BASH_SOURCE[0]}" != "$0" ]]`. It must **not** activate the venv and must **not** touch `PYTHONPATH` — the suite depends on `PYTHONPATH=` being empty.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup_sh.py`:

```python
"""setup.sh — the operator-facing skin over core/paths.py.

Mirrors muse's verbs: --status is `muse status`, --backing is
`muse backing`. Executed as a subprocess so we test the real script.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "setup.sh"


def run(*args, env=None):
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    if env:
        e.update(env)
    return subprocess.run([str(SETUP), *args], capture_output=True,
                          text=True, env=e, cwd=str(ROOT))


class TestSetupSh(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(SETUP.is_file())
        self.assertTrue(os.access(SETUP, os.X_OK))

    def test_status_prints_all_four_roots(self):
        r = run("--status")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        for key in ("REPO_ROOT", "DATA_ROOT", "ARTIFACT_ROOT", "BACKING"):
            self.assertIn(key, r.stdout)

    def test_status_reports_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            r = run("--status", env={"AUTORESEARCH_DATA_ROOT": td})
            self.assertIn(td, r.stdout)
            self.assertIn("env", r.stdout)

    def test_unknown_flag_exits_nonzero_with_usage(self):
        r = run("--bogus")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage", (r.stdout + r.stderr).lower())

    def test_backing_creates_and_removes_the_symlink(self):
        link = ROOT / "backing"
        self.assertFalse(link.exists() or link.is_symlink(),
                         msg="a backing link already exists; refusing to "
                             "clobber the operator's own link")
        with tempfile.TemporaryDirectory() as td:
            try:
                r = run("--backing", td)
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.path.realpath(link),
                                 os.path.realpath(td))
            finally:
                run("--backing", "-r")
        self.assertFalse(link.is_symlink())

    def test_backing_at_a_nonexistent_path_is_refused(self):
        r = run("--backing", "/no/such/dir")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((ROOT / "backing").is_symlink())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_setup_sh.py"
```

Expected: FAIL — `setup.sh` does not exist.

- [ ] **Step 3: Write `setup.sh`**

```bash
#!/bin/bash
# Operator-facing skin over core/paths.py. Mirrors muse's verbs:
#   --status   ~ muse status
#   --backing  ~ muse backing
#
#   source setup.sh          export the resolved roots into this shell, so a
#                            campaign's children cannot have them shift
#   ./setup.sh --status      print the four roots and where each came from
#   ./setup.sh --backing P   link P as the artifact backing (local wins)
#   ./setup.sh --backing -r  remove the link
#
# Deliberately does NOT activate the venv and does NOT touch PYTHONPATH:
# the test suite depends on `PYTHONPATH=` being empty, and this script has
# one job. Resolution itself lives in core/paths.py -- this is a view over
# it, never a second implementation.
set -uo pipefail

_SOURCED=0
[[ "${BASH_SOURCE[0]}" != "$0" ]] && _SOURCED=1

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PY="$_HERE/.venv/bin/python"
[[ -x "$_PY" ]] || _PY="python3"

_usage() {
    cat <<'EOF'
usage:
  source setup.sh              export resolved roots into this shell
  ./setup.sh --status          print the four roots and their provenance
  ./setup.sh --backing PATH    link PATH as the artifact backing
  ./setup.sh --backing -r      remove the backing link

Roots resolve from core/paths.py:
  REPO_ROOT      this file's location (never configurable)
  DATA_ROOT      $AUTORESEARCH_DATA_ROOT      or /exp/mu2e/data/users/$USER
  ARTIFACT_ROOT  $AUTORESEARCH_ARTIFACT_ROOT  or /exp/mu2e/app/users/$USER
  BACKING        the `backing` symlink, else $AUTORESEARCH_BACKING
EOF
}

# One python call prints everything; the shell never re-derives a path.
_dump() {
    PYTHONPATH= "$_PY" - "$_HERE" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "core"))
import paths

def why(env_var):
    return "env" if os.environ.get(env_var) else "default ($USER)"

print(f"REPO_ROOT     {paths.REPO_ROOT}   (this file's location)")
print(f"DATA_ROOT     {paths.DATA_ROOT}   ({why('AUTORESEARCH_DATA_ROOT')})")
print(f"ARTIFACT_ROOT {paths.ARTIFACT_ROOT}   "
      f"({why('AUTORESEARCH_ARTIFACT_ROOT')})")
if paths.BACKING is None:
    print("BACKING       (none)   -- ./setup.sh --backing <path> to set one")
else:
    src = "symlink" if (paths.REPO_ROOT / "backing").is_symlink() else "env"
    print(f"BACKING       {paths.BACKING}   ({src})")
print(f"  grid        {paths.GRID_DATA_ROOT}")
print(f"  logs        {paths.GRAPH_DATA}")
print(f"  live boards {paths.LEADERBOARD_LIVE}")
PY
}

_export() {
    local d a
    d="$(PYTHONPATH= "$_PY" -c "import sys;sys.path.insert(0,'$_HERE/core');import paths;print(paths.DATA_ROOT)")" || return 1
    a="$(PYTHONPATH= "$_PY" -c "import sys;sys.path.insert(0,'$_HERE/core');import paths;print(paths.ARTIFACT_ROOT)")" || return 1
    export AUTORESEARCH_DATA_ROOT="$d"
    export AUTORESEARCH_ARTIFACT_ROOT="$a"
    echo "exported AUTORESEARCH_DATA_ROOT=$d"
    echo "exported AUTORESEARCH_ARTIFACT_ROOT=$a"
}

_backing() {
    local target="${1:-}"
    local link="$_HERE/backing"
    if [[ -z "$target" ]]; then
        echo "ERROR - --backing needs a path (or -r to remove)" >&2
        return 1
    fi
    if [[ "$target" == "-r" || "$target" == "--rm" ]]; then
        rm -f "$link"
        echo "removed backing link"
        return 0
    fi
    if [[ ! -d "$target" ]]; then
        echo "ERROR - backing target is not a directory: $target" >&2
        return 1
    fi
    if [[ -e "$link" && ! -L "$link" ]]; then
        echo "ERROR - $link exists and is not a symlink" >&2
        return 1
    fi
    ln -sfn "$(cd "$target" && pwd)" "$link"
    echo "backing -> $(cd "$target" && pwd)"
}

if (( _SOURCED )); then
    _export
else
    case "${1:-}" in
        --status)  _dump ;;
        --backing) shift; _backing "${1:-}" ;;
        -h|--help) _usage ;;
        "")        _usage; exit 1 ;;
        *)         echo "ERROR - unknown option: $1" >&2; _usage >&2; exit 1 ;;
    esac
fi
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod 755 setup.sh
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_setup_sh.py"
```

Expected: `OK`.

- [ ] **Step 5: Eyeball the real output**

```bash
./setup.sh --status
```

Expected: four roots, `DATA_ROOT` and `ARTIFACT_ROOT` marked `default ($USER)` and pointing under `oksuzian`, `BACKING (none)`.

- [ ] **Step 6: Check sourcing works and does not disturb the shell**

```bash
bash -c 'cd /exp/mu2e/app/users/oksuzian/autoresearch; PYTHONPATH=sentinel; source setup.sh; echo "PYTHONPATH=[$PYTHONPATH]"; echo "DATA=$AUTORESEARCH_DATA_ROOT"'
```

Expected: `PYTHONPATH=[sentinel]` (untouched) and `DATA=/exp/mu2e/data/users/oksuzian`.

- [ ] **Step 7: Run the full suite**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: `OK (skipped=1)`.

- [ ] **Step 8: Commit**

```bash
git add setup.sh tests/test_setup_sh.py
git commit -F - <<'EOF'
feat(setup): setup.sh — status, backing, and sourced export

The operator-facing skin over core/paths.py, with muse's verbs: --status is
`muse status` (what am I actually running against, in one command, which was
previously unanswerable without reading source) and --backing is
`muse backing`. Sourcing exports the resolved roots so a campaign's children
cannot have them shift mid-flight.

Resolution is never reimplemented here -- every value comes from a python
call into paths.py, so the shell and the code cannot disagree.

Does not activate the venv and does not touch PYTHONPATH: the suite depends
on `PYTHONPATH=` being empty, and the script has one job.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

### Task 8: Anti-regression test and documentation

**Files:**
- Create: `tests/test_no_hardcoded_paths.py`
- Modify: `README.md`, `requirements.txt`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: nothing importable.

**Context you need.** This task must go last: the grep test fails until every literal is gone. Scope it to **tracked** files (`git ls-files`) under `core/`, `graph/`, `tests/`, `mode_specs/`. `wiki/` and `docs/` are excluded on purpose — they are a historical record of what actually happened, and rewriting history to hide a username would be worse than leaving it. Untracked new specs are covered by the *other* layer, `core/mode_json.py`'s load-time rejection (Task 4).

Before this task, 22 tracked files matched. All should now be clean.

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_hardcoded_paths.py`:

```python
"""Permanent guard: no personal user path in tracked source.

Two layers protect this. Here, a grep over tracked sources catches a
literal anyone pastes back in. In core/mode_json.py, a load-time check
rejects a bare /exp/mu2e/.../users/<name>/ in a mode spec, which covers
untracked specs this grep never sees.

wiki/ and docs/ are deliberately NOT scanned: they record what actually
happened, including who ran it, and rewriting that to hide a username would
be worse than leaving it.
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("core", "graph", "tests", "mode_specs")
NEEDLE = "users/oksuzian"


class TestNoHardcodedPaths(unittest.TestCase):
    def test_no_tracked_source_names_a_personal_user_area(self):
        tracked = subprocess.run(
            ["git", "ls-files", *SCANNED],
            cwd=str(ROOT), capture_output=True, text=True, check=True
        ).stdout.split()
        offenders = []
        for rel in tracked:
            f = ROOT / rel
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if NEEDLE in line:
                    offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
        self.assertEqual(
            offenders, [],
            msg="hardcoded personal path(s) reintroduced — route them "
                "through core/paths.py (REPO_ROOT / DATA_ROOT / "
                "ARTIFACT_ROOT / artifact()); see "
                "docs/superpowers/specs/2026-08-11-portable-paths-design.md"
                "\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -p "test_no_hardcoded_paths.py"
```

Expected: `OK`. **If it fails, the listed files were missed in Tasks 2-5** — go back and fix them rather than widening the exclusion list.

- [ ] **Step 3: Rewrite the README's environment section**

In `README.md`, replace the **Portability caveat** block (lines ~76-85, the paragraph beginning "**Portability caveat.** Building the venv under your own `$USER`…") with:

```markdown
### Artifacts

Grid stages need a patched Offline build and a prebuilt `Code_*.tar.bz2`.
Modes reference them as `${ARTIFACT}/...`, resolved against
`$AUTORESEARCH_ARTIFACT_ROOT` (default `/exp/mu2e/app/users/$USER`) and
falling through to a **backing** link for anything you have not built
yourself — the same local-wins-then-backing rule as `muse backing`:

```bash
./setup.sh --backing /exp/mu2e/app/users/oksuzian    # use another operator's build
./setup.sh --status                                  # what am I running against?
```

A fresh clone has no backing and no local artifacts, so campaign launch
fails immediately, naming the command above. That is deliberate: running
against someone else's build should be something you said, not something
that happened.

### Where your results go

- **Live rows** append to `$AUTORESEARCH_DATA_ROOT/autoresearch_leaderboards/`
  (default `/exp/mu2e/data/users/$USER/...`), one flat directory.
- **The committed `leaderboards/`** are a read-only archive of past
  campaigns. Every operator starts warm from them; nobody writes to them
  except by a reviewed git commit.
- Grid work trees and logs likewise live under your own `$AUTORESEARCH_DATA_ROOT`.
```

Also update the **Prerequisites** venv bullet (line ~25) to use `$USER` rather than the literal, and delete the "This path is deliberately literal, not `$USER`" note above the campaign code block (lines ~93-97).

- [ ] **Step 4: De-personalise the remaining README paths**

Replace in the campaign example (lines ~100, ~110, ~135, ~174, ~226):

- `cd /exp/mu2e/app/users/oksuzian/autoresearch` → `cd /exp/mu2e/app/users/$USER/autoresearch    # wherever you cloned it`
- the `nohup ... >` log redirect → `> "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/foilspf05_parent.log" 2>&1 &`
- the STOP-file `touch` path → `touch "$AUTORESEARCH_DATA_ROOT/autoresearch_graph_data/STOP_CLOSED_LOOP"`
- the per-config artifacts path → `$AUTORESEARCH_DATA_ROOT/autoresearch_grid/<config>/`
- "Off-repo data volumes (all under `/exp/mu2e/data/users/oksuzian/`)" → "Off-repo data volumes (all under `$AUTORESEARCH_DATA_ROOT`, default `/exp/mu2e/data/users/$USER/`)"

Add `paths.py` and `setup.sh` to the **Code structure** tree:

```
│   ├── paths.py             #   the ONLY module that knows a filesystem
│   │                        #   layout: repo/data/artifact roots + backing
```

and, at the top level of that tree, `├── setup.sh                 # --status / --backing; sourced, exports the roots`.

- [ ] **Step 5: De-personalise `requirements.txt`**

Replace the three `oksuzian` occurrences in the header recipe (lines 8, 9, 11, 13) with `$USER`, matching the `VENV=` form already used in the README's build recipe.

- [ ] **Step 6: Re-run the grep test and the full suite**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: `OK (skipped=1)` and golden parity PASS. Note the README and `requirements.txt` are outside the scanned dirs, so the grep test does not enforce Steps 3-5 — check them by eye:

```bash
grep -n "oksuzian" README.md requirements.txt
```

Expected: no output.

- [ ] **Step 7: Final end-to-end check as a hypothetical second operator**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
AUTORESEARCH_DATA_ROOT=/tmp/$USER/asr_fake_operator \
AUTORESEARCH_ARTIFACT_ROOT=/tmp/$USER/asr_fake_artifacts \
PYTHONPATH= .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import paths, modes
print('data    :', paths.DATA_ROOT)
print('grid    :', paths.GRID_DATA_ROOT)
print('boards  :', paths.LEADERBOARD_LIVE)
print('archive :', paths.leaderboard_archive('leaderboards/leaderboard_bo_foilspfbpz.tsv'))
try:
    paths.verify(modes.SPECS.values(), make_dirs=False)
    print('FAIL: should have refused, no artifacts there')
except paths.PathsError as e:
    print('correctly refused:'); print(str(e).splitlines()[0])
"
```

Expected: all four roots under the fake operator's tree **except** the archive, which stays in the repo; and `verify()` refuses because the fake artifact root is empty. This is the whole point of the change demonstrated in one command.

- [ ] **Step 8: Commit**

```bash
git add tests/test_no_hardcoded_paths.py README.md requirements.txt
git commit -F - <<'EOF'
test(paths): permanent guard against personal paths, and README rewrite

A grep over tracked sources in core/ graph/ tests/ mode_specs/ fails if a
`users/<name>` literal comes back. It is the second of two layers -- the
first is core/mode_json.py rejecting a bare personal absolute path in a
mode spec, which covers untracked specs the grep never sees.

wiki/ and docs/ are deliberately not scanned: they record what actually
happened, and rewriting that to hide a username would be worse.

README drops the portability caveat entirely (it no longer applies) and
gains an Artifacts section explaining the backing link, plus a statement of
where results go: live rows to your own /data, committed leaderboards/ as a
read-only archive everyone starts warm from.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
EOF
```

---

## After the plan

1. **Do not merge until campaigns drain.** `pgrep -f "closed_loop"` must be empty. Children re-execute the working tree, and Task 5 changes where leaderboard rows land.
2. **Before the first post-merge launch**, resolve any pending rows flagged in Task 5 Step 11, then confirm with `./setup.sh --status` and one `bo_driver.py preflight` run.
3. **Wiki updates** (uncommitted, per project convention): a new `wiki/concepts/portable-paths.md` describing the resolver and the backing rule; cross-links from `wiki/incidents/prodtarget-env-divergence.md` and `wiki/incidents/foilsflash-tarball-mode-key-omission.md` to the `verify()` gate that now prevents them; a `wiki/log.md` bullet at the top under today's date.
4. **Spec B — artifact reproducibility** is the natural follow-on: bring `rebuild.sh`, `stoppingtarget-holeradii.patch`, `ipa-zstart.patch`, and the `Code_*.tar.bz2` production recipe (currently only a comment at `core/pipeline.py:395-400`) into the repo, so "each operator builds their own" becomes achievable rather than aspirational.
