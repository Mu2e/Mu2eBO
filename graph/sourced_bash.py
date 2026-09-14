#!/usr/bin/env python3
"""Shared retry-with-backoff runner for mu2e env-source shell commands.

Transient class: cvmfs read misses and the NFSv4.0 seqid wedge on ~/.spack
locks (wiki/incidents/nfsv4-badseqid-lock-wedge-nashome.md) -- ``==> Error:
[Errno 5]`` mid-``setupmu2e-art.sh`` leaves ``muse``/``mu2e`` undefined
(often rc=127); a re-run seconds later succeeds. Every command exports
``SPACK_USER_CACHE_PATH`` onto node-local /tmp so spack's fcntl locks never
touch NFS. Coverage map: wiki/incidents/sourced-env-stderr-swallowed.md."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable, Optional

DEFAULT_BACKOFFS = (5, 15, 30)  # 4 attempts total, ~50s worst case

# Node-local /tmp, never NFS HOME (module docstring); supersedes the per-site
# exports in pipeline.py:sourced_env / bo_driver.py:cmd_preflight.
_SPACK_CACHE = f"/tmp/spack_cache_{os.environ.get('USER', 'x')}"


def run_sourced_bash(
    cmd: str,
    *,
    login: bool = False,
    timeout: Optional[float] = None,
    backoffs: tuple = DEFAULT_BACKOFFS,
    should_retry: Optional[Callable[[subprocess.CompletedProcess], bool]] = None,
    label: str = "sourced_bash",
    log=sys.stderr,
) -> subprocess.CompletedProcess:
    """Run ``bash -c cmd`` (``bash -lc`` if ``login``) with retry + backoff.

    Retries while ``should_retry(proc)`` (default rc != 0), up to
    ``len(backoffs) + 1`` attempts. A timeout is NON-retriable -- it means
    the command was running (slow init), not an env flake -- returned as
    ``CompletedProcess(returncode=-1)`` with ``.timed_out = True``. Every
    return path sets ``.timed_out``; never raises on a nonzero rc."""
    if should_retry is None:
        should_retry = lambda p: p.returncode != 0  # noqa: E731
    # Must be inside the command string: a parent-shell export does NOT
    # propagate to the sourced environment (foilsZ05, 2026-06-05).
    cmd = f"export SPACK_USER_CACHE_PATH={_SPACK_CACHE} && {cmd}"
    argv = ["bash", "-lc" if login else "-c", cmd]
    for attempt in range(len(backoffs) + 1):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            proc.timed_out = False
        except subprocess.TimeoutExpired as exc:
            out, err = exc.stdout or "", exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            if isinstance(err, bytes):
                err = err.decode(errors="replace")
            proc = subprocess.CompletedProcess(argv, -1, stdout=out, stderr=err)
            proc.timed_out = True
            return proc
        if not should_retry(proc) or attempt == len(backoffs):
            return proc
        wait = backoffs[attempt]
        print(f"[{label}] attempt {attempt + 1}/{len(backoffs) + 1} rc={proc.returncode}; "
              f"retrying in {wait}s (transient cvmfs/spack flake?)", file=log, flush=True)
        time.sleep(wait)
    return proc  # unreachable: the loop always returns on the last attempt
