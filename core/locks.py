"""The flock helpers of the point and campaign records (spec
docs/superpowers/specs/2026-10-05-point-campaign-records-design.md).

A holder keeps an exclusive flock(2) on a file for as long as its `with`
block lasts; the lock belongs to the open file description, so it is
released on exit and on SIGKILL. A reader probes with a shared lock taken
and dropped at once. A probe takes about 0.3 ms, so a holder retries for
`wait_s` before giving up: a dashboard sweep must never refuse a run.

Stdlib only.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path
from typing import Iterator

RETRY_S = 0.05


class LockBusy(RuntimeError):
    """Another process holds the lock."""


@contextlib.contextmanager
def hold(path: Path, wait_s: float = 2.0) -> Iterator[None]:
    """An exclusive flock on `path` (created; its parent must exist) for
    the `with` block. Retried every RETRY_S until `wait_s`, then LockBusy."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"{path} is held by another process") \
                        from None
                time.sleep(RETRY_S)
        yield
    finally:
        os.close(fd)


def held(path: Path) -> bool:
    """Whether a process holds the lock at `path` (False when there is no
    such file). A shared probe: two probes never conflict with each other,
    only with a holder's exclusive lock."""
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False
