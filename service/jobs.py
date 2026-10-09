"""The detached launch the autoresearch MCP server uses for every job it
starts (a check_study run, a campaign), its liveness probe, and the tail
of what it printed.

spawn_detached takes an exclusive flock on <job_dir>/lock, hands that file
to the job (pass_fds) and closes its own copy: the lock belongs to the open
file description, so it is held exactly as long as a job process still has
it open, through a restart of the server or the client, and is released on
exit and on SIGKILL. lock_held probes it without blocking. The job runs in
its own session with stdin, stdout and stderr at /dev/null: the server's own
stdin/stdout carry the MCP stream.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths  # noqa: E402
from locks import held as lock_held  # noqa: E402,F401  (re-exported)


def spawn_detached(job_dir: Path, script: str, args: Sequence[str],
                   env: Mapping[str, str]) -> int:
    """Run `bash -c <script> _ <job_dir> <args...>` from the repo root,
    detached, holding <job_dir>/lock for as long as it lives; the pid."""
    fd = os.open(Path(job_dir) / "lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            ["bash", "-c", script, "_", str(job_dir), *args],
            cwd=paths.REPO_ROOT, env=dict(env),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
            pass_fds=(fd,))
    finally:
        os.close(fd)
    # Reap the job when it ends: no zombie in a long-lived server (the lock,
    # not this thread, says whether it is running).
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc.pid


def last_lines(text: str, n: int) -> str:
    """The last `n` lines of `text`."""
    return "\n".join(text.splitlines()[-n:])
