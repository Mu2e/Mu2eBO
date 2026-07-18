#!/usr/bin/env python3
"""Shared retry-with-backoff runner for mu2e env-source shell commands.

Centralizes the transient cvmfs/spack env-flake retry that was copy-pasted in
``pipeline.py:sourced_env`` and ``bo_driver.py:cmd_preflight``,
and was absent entirely from the two ``getToken`` sites. A cvmfs read miss
(``==> Error: [Errno 5]``) mid-``setupmu2e-art.sh`` leaves ``muse``/``mu2e``
undefined -> the command exits nonzero (often rc=127) producing little/no
output; a re-run seconds later succeeds.

See wiki/incidents/sourced-env-stderr-swallowed.md (env-source coverage map).
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import Callable, Optional

DEFAULT_BACKOFFS = (5, 15, 30)  # 4 attempts total, ~50s worst case


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

    Retries while ``should_retry(proc)`` is True (default: ``returncode != 0``)
    up to ``len(backoffs) + 1`` attempts, sleeping ``backoffs[attempt]`` between
    tries. A subprocess timeout is treated as NON-retriable -- a timeout means
    the command was running (slow init), not an env flake -- and is returned as
    a ``CompletedProcess(returncode=-1)`` carrying ``.timed_out = True``.

    Returns the final ``CompletedProcess`` (with a ``.timed_out`` bool attribute
    set on every return path). Callers keep their own success/failure handling
    (env parsing, raising CalledProcessError, sys.exit). This helper never
    raises on a nonzero rc -- only an unrunnable ``bash`` would propagate.
    """
    if should_retry is None:
        should_retry = lambda p: p.returncode != 0  # noqa: E731
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
