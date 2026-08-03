# NFS Lock-Wedge Mitigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all autoresearch spack-lock traffic from NFS `/nashome` and cut redundant `getToken` env-sourcings ~30→2-3/round, so the NFSv4.0 BAD_SEQID wedge (wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) has nothing of ours to bite.

**Architecture:** Three independent changes per the approved spec (`docs/superpowers/specs/2026-07-31-nfs-lock-mitigation-design.md`): (1) an unconditional `SPACK_USER_CACHE_PATH` export prepended inside `run_sourced_bash()` — the single seam all four env-sourcing callers route through; (2) an mtime gate that skips the per-stage-submit `getToken` when the shared bearer token was refreshed <1 h ago, factored into a testable `_maybe_refresh_token()`; (3) the same export in the operator's `~/.bashrc`.

**Tech Stack:** Python 3.11 stdlib only, `unittest` + `unittest.mock`. No new dependencies.

## Global Constraints

- Test command (verbatim, from repo root): `PYTHONPATH= .venv/bin/python -m unittest discover -s tests` — baseline **420 tests green**; expect **427** after this plan.
- **NEVER `git push`** (Bash-tool shells cannot reach the ssh-agent — wiki/incidents/claude-bash-no-ssh-agent.md).
- **git add with EXPLICIT paths only** — the working tree carries unrelated uncommitted work (`docs/`, `leaderboards/`, `wiki/`, `mode_specs/`). Never `git add -A` or `git add .`.
- Before touching `core/pipeline.py` or `graph/*.py`, verify no campaign is running: `ps -fu $USER -ww | grep "[g]raph\.closed_loop\|[g]raph\.run"` must print nothing.
- The spack export must live **inside the bash command string**, never only in the parent environment — parent-shell export does not propagate (foilsZ05 2026-06-05, comment at `core/bo_driver.py:1680`).
- Cache path is exactly `/tmp/spack_cache_$USER` — must match the existing per-site exports at `core/pipeline.py:472` and `core/bo_driver.py:1684` (those two STAY; they become redundant, not wrong).
- `graph/closed_loop.py` is deliberately NOT modified (its once-per-round `renew_token` doubles as the krb5 liveness check).
- Wiki edits stay **uncommitted** (operator reviews them); code + tests + plan/spec docs are committed.
- Commit message trailer (every commit):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
  ```

---

### Task 1: Spack-cache relocation at the `run_sourced_bash` seam

**Files:**
- Modify: `graph/sourced_bash.py` (69 lines total; docstring lines 2-12, imports lines 13-18, constant after line 20, command build line 48)
- Test: `tests/test_audit_fixes.py` (class `TestRunSourcedBash`, ends line ~645)

**Interfaces:**
- Consumes: nothing new.
- Produces: `run_sourced_bash(cmd, ...)` — signature unchanged; behavioral contract extended: the executed bash command is always `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER && <cmd>`. Module constant `_SPACK_CACHE: str`. Task 2's gate tests rely on nothing from this task (independent).

- [ ] **Step 1: Write the failing tests** — append to `class TestRunSourcedBash` in `tests/test_audit_fixes.py` (after `test_timeout_is_not_retried`):

```python
    def test_spack_cache_export_prepended(self):
        # NFSv4.0 seqid-wedge mitigation: every command must run with
        # spack's cache (and its fcntl locks) on node-local /tmp, not
        # NFS HOME. See wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md.
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m:
            self.sb.run_sourced_bash("source setup.sh && getToken")
        argv = m.call_args[0][0]
        self.assertEqual(argv[:2], ["bash", "-c"])
        self.assertTrue(argv[2].startswith(
            "export SPACK_USER_CACHE_PATH=/tmp/spack_cache_"))
        self.assertTrue(argv[2].endswith(" && source setup.sh && getToken"))

    def test_spack_cache_export_prepended_login_shell(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m:
            self.sb.run_sourced_bash("getToken", login=True)
        argv = m.call_args[0][0]
        self.assertEqual(argv[:2], ["bash", "-lc"])
        self.assertTrue(argv[2].startswith("export SPACK_USER_CACHE_PATH="))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_audit_fixes.TestRunSourcedBash -v`
Expected: the two new tests FAIL on the `startswith` assertion (command has no export prefix); the existing 5 pass.

- [ ] **Step 3: Implement the seam** — in `graph/sourced_bash.py`:

3a. Add `import os` to the imports (alphabetical, before `subprocess`):

```python
import os
import subprocess
import sys
import time
```

3b. Add the constant directly under `DEFAULT_BACKOFFS`:

```python
DEFAULT_BACKOFFS = (5, 15, 30)  # 4 attempts total, ~50s worst case

# Keep spack's index cache + its fcntl locks on node-local /tmp, never NFS
# HOME: concurrent lock traffic on /nashome (NFSv4.0) intermittently wedges
# a lock file with permanent EIO (BAD_SEQID desync). Same path as the
# per-site exports in pipeline.py:sourced_env / bo_driver.py:cmd_preflight,
# which this seam supersedes (they stay, redundantly, to avoid churning
# stable code). See wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md.
_SPACK_CACHE = f"/tmp/spack_cache_{os.environ.get('USER', 'x')}"
```

3c. Prepend the export where argv is built (line 48). Replace:

```python
    argv = ["bash", "-lc" if login else "-c", cmd]
```

with:

```python
    # Must be inside the command string: a parent-shell export does NOT
    # propagate to the sourced environment (foilsZ05, 2026-06-05).
    cmd = f"export SPACK_USER_CACHE_PATH={_SPACK_CACHE} && {cmd}"
    argv = ["bash", "-lc" if login else "-c", cmd]
```

3d. Replace the module docstring (lines 2-12) — the old text attributes the [Errno 5] class solely to cvmfs, refuted 2026-07-30:

```python
"""Shared retry-with-backoff runner for mu2e env-source shell commands.

Centralizes the transient env-source failure retry that was copy-pasted in
``pipeline.py:sourced_env`` and ``bo_driver.py:cmd_preflight``,
and was absent entirely from the two ``getToken`` sites. Known causes of
the transient class: cvmfs read misses, and the NFSv4.0 seqid wedge on
``~/.spack`` lock files (wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md).
Either way ``==> Error: [Errno 5]`` mid-``setupmu2e-art.sh`` leaves
``muse``/``mu2e`` undefined -> the command exits nonzero (often rc=127)
producing little/no output; a re-run seconds later succeeds.

Additionally, every command runs with ``SPACK_USER_CACHE_PATH`` on
node-local /tmp (prepended export), so spack's index-cache fcntl locks
never touch NFS -- the wedge above cannot bite any caller of this helper.

See wiki/incidents/sourced-env-stderr-swallowed.md (env-source coverage map).
"""
```

- [ ] **Step 4: Run the class, then the full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_audit_fixes.TestRunSourcedBash -v`
Expected: 7/7 PASS.
Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3`
Expected: 422 tests, OK. (If any OTHER test broke, it was inspecting the command string — fix that test to accept the prefix, and note it in the commit body.)

- [ ] **Step 5: Commit**

```bash
git add graph/sourced_bash.py tests/test_audit_fixes.py
git commit -m "fix(env): relocate spack cache off NFS at the run_sourced_bash seam

Every env-sourcing subprocess (sourced_env, preflight, both getToken
sites, future callers) now runs with SPACK_USER_CACHE_PATH on node-local
/tmp. Concurrent fcntl lock traffic on /nashome (NFSv4.0) intermittently
wedges a lock inode with permanent EIO -- reproduced 12x on 2026-07-30.
See wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 2: getToken mtime gate in `core/pipeline.py`

**Files:**
- Modify: `core/pipeline.py` (helper + constant at module level; the `with _submit_lock(stage):` block at lines ~738-751; two stale comments at lines ~455-463 and ~474-479)
- Test: `tests/test_pipeline_verbs.py` (new class at end of file; add `import time` to its imports)

**Interfaces:**
- Consumes: `run_sourced_bash` (already imported by `core/pipeline.py`), `SETUPMU2E` (already imported from `config`).
- Produces: module-level `TOKEN_REFRESH_AGE_S: int = 3600`, `_token_age_s() -> float`, `_maybe_refresh_token(stage: str) -> None` (raises `subprocess.CalledProcessError` on getToken rc!=0). Tests patch `pipeline.run_sourced_bash` and env var `BEARER_TOKEN_FILE`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pipeline_verbs.py`. First add `import time` to that file's imports (it already has `os`, `subprocess`, `tempfile`, `unittest`, `mock`, `Path`, `SimpleNamespace`). Then:

```python
class TestGetTokenMtimeGate(unittest.TestCase):
    """_maybe_refresh_token: run getToken only when the shared bearer token
    file is older than TOKEN_REFRESH_AGE_S (1h). Fail-open on unknown age.
    Spec: docs/superpowers/specs/2026-07-31-nfs-lock-mitigation-design.md."""

    def _token_file(self, age_s):
        d = tempfile.mkdtemp(prefix="tokgate_")
        p = Path(d) / "bt_u12345"
        p.write_text("header.payload.sig\n")
        past = time.time() - age_s
        os.utime(p, (past, past))
        return str(p)

    def _ok(self):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_fresh_token_skips_gettoken(self):
        p = self._token_file(120)
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash") as rt:
            pipeline._maybe_refresh_token("stageX")
        rt.assert_not_called()

    def test_old_token_refreshes(self):
        p = self._token_file(pipeline.TOKEN_REFRESH_AGE_S + 100)
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=self._ok()) as rt:
            pipeline._maybe_refresh_token("stageX")
        self.assertEqual(rt.call_count, 1)
        self.assertIn("getToken", rt.call_args[0][0])

    def test_missing_token_file_refreshes(self):
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": "/nonexistent/bt"}), \
             mock.patch.object(pipeline, "run_sourced_bash",
                               return_value=self._ok()) as rt:
            pipeline._maybe_refresh_token("stageX")
        self.assertEqual(rt.call_count, 1)

    def test_gettoken_failure_still_raises(self):
        p = self._token_file(pipeline.TOKEN_REFRESH_AGE_S + 100)
        bad = SimpleNamespace(returncode=1, stdout="", stderr="denied")
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": p}), \
             mock.patch.object(pipeline, "run_sourced_bash", return_value=bad):
            with self.assertRaises(subprocess.CalledProcessError):
                pipeline._maybe_refresh_token("stageX")

    def test_token_age_inf_when_missing(self):
        with mock.patch.dict(os.environ, {"BEARER_TOKEN_FILE": "/nonexistent/bt"}):
            self.assertEqual(pipeline._token_age_s(), float("inf"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_pipeline_verbs.TestGetTokenMtimeGate -v`
Expected: all 5 FAIL/ERROR with `AttributeError: module 'pipeline' has no attribute '_maybe_refresh_token'` (and `_token_age_s`).

- [ ] **Step 3: Implement** — in `core/pipeline.py`:

3a. Find the function holding the submit block: `grep -n "_submit_lock(stage)" core/pipeline.py`. At **module level immediately above that function's `def` line**, insert:

```python
TOKEN_REFRESH_AGE_S = 3600  # refresh the shared bearer token when >1h old


def _token_age_s() -> float:
    """Age of the shared bearer token file; inf if absent/unreadable."""
    p = (os.environ.get("BEARER_TOKEN_FILE")
         or f"/run/user/{os.getuid()}/bt_u{os.getuid()}")
    try:
        return time.time() - os.stat(p).st_mtime
    except OSError:
        return float("inf")


def _maybe_refresh_token(stage: str) -> None:
    """getToken, unless the token was refreshed within TOKEN_REFRESH_AGE_S.

    The bearer token is one shared 3h file per user per node (local tmpfs,
    so the stat never touches NFS). Refreshing it at every stage submit
    (~30x/round) was ~28 redundant setupmu2e-art.sh sourcings and ~3min of
    serialized submit-lock time per round. Fail-open: unknown age ->
    refresh. MUST be called inside _submit_lock (condor_vault_storer races).
    """
    age = _token_age_s()
    if age <= TOKEN_REFRESH_AGE_S:
        print(f"[{stage}] bearer token refreshed {int(age / 60)}m ago, "
              f"skipping getToken", flush=True)
        return
    print(f"[{stage}] renewing bearer token: getToken", flush=True)
    # getToken sources setupmu2e-art.sh -> shares the transient env-source
    # failure class (cvmfs read flakes; NFSv4.0 seqid wedge -- see
    # wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) -> routed
    # through the shared retry helper.
    tok = run_sourced_bash(f"source {SETUPMU2E} >/dev/null 2>&1 && getToken",
                           label=f"{stage}/getToken")
    if tok.stdout.strip():
        print(tok.stdout)
    if tok.returncode != 0:
        raise subprocess.CalledProcessError(
            tok.returncode, "getToken", output=tok.stdout, stderr=tok.stderr)
```

3b. Replace the inline block at the submit site. Old (lines ~738-751):

```python
    with _submit_lock(stage):
        print(f"[{stage}] renewing bearer token: getToken", flush=True)
        # getToken sources setupmu2e-art.sh, so it shares the cvmfs/spack flake
        # class -> route through the shared retry helper (was bare check=True).
        tok = run_sourced_bash(f"source {SETUPMU2E} >/dev/null 2>&1 && getToken",
                               label=f"{stage}/getToken")
        if tok.stdout.strip():
            print(tok.stdout)
        if tok.returncode != 0:
            raise subprocess.CalledProcessError(
                tok.returncode, "getToken", output=tok.stdout, stderr=tok.stderr)
```

New:

```python
    with _submit_lock(stage):
        _maybe_refresh_token(stage)
```

(The `# Host-wide serialization ...` comment above the `with` stays.)

3c. Correct the two stale cvmfs-only attributions in the same file. First, in `sourced_env`'s else-branch NOTE (lines ~455-463), replace:

```python
        # NOTE: this swap does NOT prevent rc=127. That failure comes from a
        # transient cvmfs I/O flake (==> Error: [Errno 5]) inside
        # setupmu2e-art.sh that leaves museDefine.sh unsourced and the `muse`
        # function itself undefined -- upstream of this line. The retry loop
        # below is what actually recovers it.
```

with:

```python
        # NOTE: this swap does NOT prevent rc=127. That failure comes from a
        # transient [Errno 5] inside setupmu2e-art.sh (cvmfs read flake OR
        # the NFSv4.0 seqid wedge on ~/.spack locks -- see wiki/incidents/
        # nfsv4-badseqid-lock-wedge-nashome.md) that leaves museDefine.sh
        # unsourced and the `muse` function undefined -- upstream of this
        # line. The retry loop below is what actually recovers it.
```

Second, above the `run_sourced_bash` call at line ~474, replace:

```python
    # Transient cvmfs read flakes (==> Error: [Errno 5] Input/output error)
    # leave museDefine.sh unsourced -> `muse` undefined -> rc=127
    # "command not found". These are NOT deterministic: a re-run seconds later
    # succeeds, so retry with backoff before giving up. 8+ closed-loop children
    # were lost to this across X05/X06/X08 before retries were added. Shared
    # retry lives in graph/sourced_bash.py (run_sourced_bash).
```

with:

```python
    # Transient [Errno 5] env-source failures (cvmfs read flake OR NFSv4.0
    # seqid wedge on ~/.spack locks; the run_sourced_bash seam now keeps
    # those locks off NFS entirely) leave museDefine.sh unsourced -> `muse`
    # undefined -> rc=127 "command not found". Retry with backoff either
    # way -- 8+ closed-loop children were lost across X05/X06/X08 before
    # retries were added. Shared retry: graph/sourced_bash.py.
```

- [ ] **Step 4: Run the class, then the full suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_pipeline_verbs.TestGetTokenMtimeGate -v`
Expected: 5/5 PASS.
Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3`
Expected: 427 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline_verbs.py
git commit -m "feat(pipeline): gate per-submit getToken on bearer-token age (1h)

The shared 3h token was refreshed at every stage submit (~30x/round =
~28 redundant setupmu2e-art.sh sourcings + ~3min serialized submit-lock
time). Now: refresh only when the token file is >TOKEN_REFRESH_AGE_S
(3600s) old; fail-open (absent/unreadable -> refresh); still inside
_submit_lock. closed_loop's round-edge renew_token is untouched. Also
corrects two comments blaming the [Errno 5] class solely on cvmfs.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 3: Operator shell export + wiki closure

**Files:**
- Modify: `~/.bashrc` (append; NOT in the repo — no git operations on it)
- Modify: `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md` (TODO list + timestamp; stays UNCOMMITTED)
- Modify: `wiki/log.md` (one bullet under `## 2026-07-31` at TOP; stays UNCOMMITTED)

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (independent).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Append the export block to `~/.bashrc`**

```bash
cat >> ~/.bashrc <<'EOF'

# 2026-07-31: keep spack's index cache + fcntl locks off NFS /nashome
# (NFSv4.0 seqid wedge — autoresearch wiki: incidents/nfsv4-badseqid-lock-wedge-nashome)
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
EOF
```

- [ ] **Step 2: Verify it takes effect in a fresh login shell**

Run: `bash -lc 'echo cache=$SPACK_USER_CACHE_PATH'`
Expected: `cache=/tmp/spack_cache_oksuzian`

- [ ] **Step 3: End-to-end spot check** (~40 s: sources the real env, confirms spack populates the /tmp cache and MUSE_DIR resolves)

Run: `bash -lc 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1; echo MUSE_DIR=${MUSE_DIR:+set}; ls /tmp/spack_cache_$USER/cache 2>/dev/null | head -3'`
Expected: `MUSE_DIR=set` and cache subdirs (`providers`/`patches`/`tags` or similar) listed.

- [ ] **Step 4: Close the loop in the wiki** (edits stay uncommitted). In `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`: bump `timestamp:` to `'2026-07-31'`; in **Open questions / TODO** replace the first bullet
  `- Land the three local changes: export in run_sourced_bash, ~/.bashrc export, getToken JWT-exp gate (all pending operator go-ahead).`
  with
  `- ~~Land the three local changes~~ DONE 2026-07-31: seam export in run_sourced_bash (commit from Task 1), getToken mtime gate (Task 2), ~/.bashrc export. Spec: docs/superpowers/specs/2026-07-31-nfs-lock-mitigation-design.md.`
  In `wiki/log.md`, add under a new `## 2026-07-31` heading at the TOP:
  `- **updated** NFS wedge mitigations LANDED — SPACK_USER_CACHE_PATH seam export in run_sourced_bash (all 4 env-source callers), getToken mtime gate (~30→2-3 sourcings/round), operator .bashrc export; suite 427 green — [nfsv4-badseqid-lock-wedge-nashome](/incidents/nfsv4-badseqid-lock-wedge-nashome.md)`

- [ ] **Step 5: Final full-suite confirmation**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3`
Expected: 427 tests, OK. (No commit in this task: `.bashrc` is not in the repo; wiki edits await operator review.)
