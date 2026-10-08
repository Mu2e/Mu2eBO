"""core/locks.py: the flock helpers the point and campaign records use
(spec docs/superpowers/specs/2026-10-05-point-campaign-records-design.md)."""
import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import locks  # noqa: E402
from tests.engine_fixtures import TmpCase  # noqa: E402

HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[2], "w").close()
time.sleep(float(sys.argv[3]))
"""


class TestLocks(TmpCase):
    def setUp(self):
        super().setUp()
        self.lock = self.tmp / "x.lock"

    def holder(self, seconds=5.0):
        """A child process holding the lock; returns once it holds it."""
        ready = self.tmp / "ready"
        p = subprocess.Popen([sys.executable, "-c", HOLDER, str(self.lock),
                              str(ready), str(seconds)])
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait()))
        deadline = time.monotonic() + 10
        while not ready.exists():
            self.assertLess(time.monotonic(), deadline, "holder never ready")
            time.sleep(0.02)
        return p

    def test_hold_then_held(self):
        with locks.hold(self.lock):
            self.assertTrue(locks.held(self.lock))
        self.assertFalse(locks.held(self.lock))
        missing = self.tmp / "missing.lock"
        self.assertFalse(locks.held(missing))
        self.assertFalse(missing.exists())

    def test_a_second_holder_is_refused(self):
        self.holder()
        t0 = time.monotonic()
        with self.assertRaises(locks.LockBusy):
            with locks.hold(self.lock, wait_s=0.3):
                pass
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)

    def test_a_holder_waits_out_a_probe(self):
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_SH)

        def release():
            time.sleep(0.2)
            os.close(fd)
        t = threading.Thread(target=release)
        t.start()
        try:
            with locks.hold(self.lock, wait_s=2):
                self.assertTrue(locks.held(self.lock))
        finally:
            t.join()

    def test_released_on_sigkill(self):
        p = self.holder(seconds=60)
        self.assertTrue(locks.held(self.lock))
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        self.assertFalse(locks.held(self.lock))


if __name__ == "__main__":
    unittest.main()
