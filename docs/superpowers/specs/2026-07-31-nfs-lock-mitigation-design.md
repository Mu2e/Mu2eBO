# NFS lock-wedge mitigation (no mount change) — design

**Date:** 2026-07-31
**Status:** approved (brainstormed with operator; Approach A + mtime gate)
**Context:** `wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md`

## Problem

`/nashome` is NFSv4.0. Concurrent fcntl lock traffic + an RPC disturbance
desyncs a lock-owner sequence id; the server then rejects locks on that
inode with `NFS4ERR_BAD_SEQID` and the el9 client never recovers —
permanent per-inode EIO. Reproduced 12× on 2026-07-30 (11 canary events,
all on concurrently-hammered files, zero on cold controls, zero lease
involvement; +1 independent operator reproduction in 12.5 min). The
2026-07-29 outage was spack's cache lock
(`~/.spack/cache/providers/.builtin-index.json.lock`) wedging, which
kills `spack load` inside `setupmu2e-art.sh` → `MUSE_DIR` unset →
`/bin/museDefine.sh: No such file`.

The mount cannot be changed (v4.1 is an FNAL-admin decision). This design
removes OUR exposure: no autoresearch code path or operator shell puts
spack lock traffic on NFS, and the redundant env-sourcing that generates
most of that traffic is eliminated.

## Non-goals

- Fixing the protocol (that is the v4.1 ticket, tracked in the wiki page).
- Auto-healing already-wedged inodes (recovery stays manual: rename the
  file aside).
- Gating `closed_loop.py`'s `renew_token` — 1 call/round, doubles as the
  round-edge krb5 liveness check; deliberately untouched.

## Design

Three independent changes. Each is revertible alone.

### 1. Cache relocation at the seam — `graph/sourced_bash.py`

Every env-sourcing subprocess funnels through `run_sourced_bash()`
(callers: `pipeline.py:480` sourced_env, `pipeline.py:744` getToken,
`bo_driver.py:1714` preflight, `closed_loop.py:269` renew_token). Prepend
the relocation export unconditionally there:

```python
_SPACK_CACHE = f"/tmp/spack_cache_{os.environ.get('USER', 'x')}"
# in run_sourced_bash(), before building argv:
cmd = f"export SPACK_USER_CACHE_PATH={_SPACK_CACHE} && {cmd}"
```

Invariant gained: any command run through the helper — including future
callers — has spack's index cache and its fcntl locks on node-local
/tmp, where the NFS bug cannot reach. Path matches the existing per-site
exports (`pipeline.py:472`, `bo_driver.py:1684`), which become redundant
and STAY (removing them touches stable code for no behavior change).
The prefix must live in the command string, not the parent env — the
foilsZ05 lesson (bo_driver.py:1680 comment): parent-shell export did not
propagate.

Docstring updates in the same diff: state the invariant; replace the
"transient cvmfs read flake" attribution (module docstring, and the
comment at `pipeline.py:458-462`) with the two known causes — cvmfs
read flakes AND the NFSv4.0 seqid wedge — citing the wiki incident page.

### 2. getToken mtime gate — `core/pipeline.py`

The per-stage-submit `getToken` (inside `_submit_lock`, line ~741) runs
~30×/round (3 stages × q=10) to refresh one shared 3 h bearer token —
~28 redundant `setupmu2e-art.sh` sourcings and ~3 min of serialized
submit-lock time per round. Gate it on token-file age ("refresh unless
refreshed within the last hour" — operator's formulation):

```python
TOKEN_REFRESH_AGE_S = 3600

def _token_age_s() -> float:
    """Age of the shared bearer token file; inf if absent/unreadable."""
    p = (os.environ.get("BEARER_TOKEN_FILE")
         or f"/run/user/{os.getuid()}/bt_u{os.getuid()}")
    try:
        return time.time() - os.stat(p).st_mtime
    except OSError:
        return float("inf")
```

At the submit site, inside the lock:

```python
age = _token_age_s()
if age > TOKEN_REFRESH_AGE_S:
    # existing getToken block, unchanged
else:
    print(f"[{stage}] bearer token refreshed {int(age/60)}m ago, skipping getToken")
```

Fail-open: absent/unreadable file → `inf` → refresh (today's behavior).
Safety margin: refreshed-within-1 h ⇒ ≥2 h remaining on a 3 h token.
A wrong skip cannot be silent: `mu2ejobsub` fails loudly and the
existing stderr-persist path (`/tmp/sourced_env_errs_*`) captures it.
The age check happens inside `_submit_lock`, so refresh remains
serialized (condor_vault_storer race protection unchanged). Note the
token file lives on `/run/user` (local tmpfs): `os.stat` never touches
NFS. LangGraph deliberately has no role: it has no timer primitive, and
point-of-use gating covers every launch topology (closed-loop, single
chain, manual `pipeline.py` recovery) identically.

### 3. Operator shell — `~/.bashrc`

Append (operator approved direct edit):

```bash
# 2026-07-31: keep spack's index cache + fcntl locks off NFS /nashome
# (NFSv4.0 seqid wedge — autoresearch wiki: incidents/nfsv4-badseqid-lock-wedge-nashome)
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
```

Covers interactive `source setupmu2e-art.sh` — where the 2026-07-29
failure surfaced. Cost: first spack use per node/boot rebuilds the index
cache (seconds); `/tmp` aging just repeats that.

## Testing

Unit tests only — no grid contact. `PYTHONPATH= .venv/bin/python -m
unittest discover -s tests` (baseline 420 green).

1. **Seam** (extend the existing `run_sourced_bash` tests in
   `tests/test_audit_fixes.py`): capture the argv handed to
   `subprocess.run` (monkeypatch); assert the command string starts with
   `export SPACK_USER_CACHE_PATH=` for both `login=False` and
   `login=True`; existing 5 tests stay green.
2. **Gate**: point `BEARER_TOKEN_FILE` at a temp file — fresh mtime →
   skip; mtime aged >1 h (`os.utime`) → refresh; env pointing at a
   missing path → refresh. Assert by monkeypatching the getToken runner
   (`run_sourced_bash` as imported by `core.pipeline`) and counting
   calls — no wall-clock sleeps, no output parsing.
3. Live validation (next campaign, observational): submit logs show the
   skip line ~28×/round; no `~/.spack` lock traffic from campaign
   processes.

## Rollback

Each change reverts independently: (1) drop the prefix line, (2) drop
the gate guard (getToken becomes unconditional again), (3) delete the
`.bashrc` block. No data formats, no state, no migrations.
