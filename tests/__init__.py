"""Test package init — quiets production stdout for the duration of a run.

The modules under test print progress to stdout as a matter of course:
`[closed_loop] barrier ...`, `[botorch_predict] picked q=4 ...`,
`[poke] converged ...`. Under the suite that is ~85 lines of narration for
a green run, and much of it is deliberately alarming -- the tests that
exercise failure handling emit `FATAL renew_token`, `ABORT (streak = full
pool of rowless resolutions)`, `child process died without resolution`,
`all failed; exiting early`. A first-time operator following the README
runs this as their second command and watches a passing suite scroll past
looking like a catastrophe.

So stdout is discarded here, at import of the test package, before any test
module loads. Set AUTORESEARCH_TEST_VERBOSE=1 to keep it when you are
debugging a specific failure.

This file only runs when discovery imports `tests` AS A PACKAGE, which needs
the top-level dir to be the repo root -- that is what the `-t .` in the
documented command buys. Plain `discover -s tests` makes `tests/` itself the
top level, imports the modules as bare `test_*`, never touches this file, and
is simply noisy again. Nothing breaks either way.

This is safe for the runner and for tests that capture output:

  - unittest writes results and -v test names to sys.stderr, so pass/fail
    reporting, tracebacks, and the final OK/FAILED line are untouched.
  - `contextlib.redirect_stdout` and `mock.patch` in individual tests save
    and replace whatever sys.stdout currently is, so assertions on printed
    output keep working.
  - Anything a module writes to stderr still shows -- warnings included.
"""
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# The suite's mode, stamped ONCE, here.
#
# core/runtime.py (_SPEC) and core/pipeline.py (MODE) each resolve the
# process's mode from AUTORESEARCH_MODE at IMPORT time and cannot be
# re-pointed afterwards, so a single-process suite necessarily runs under ONE
# mode. Before this stamp, that mode was decided by whichever test module
# `discover` imported first: tests/test_closed_loop.py sorts ahead of
# tests/test_pool.py and tests/test_no_mock_mode.py, so its
# setdefault("foilsflash") won and THEIR setdefault("foilspf") lines were
# silent no-ops. Two costs: the mode the suite actually exercised was an
# accident of filename ordering, and a mode-stamping bug (final review,
# finding I1) was untestable because every module already agreed by
# accident. Setting it in the package __init__ makes the choice explicit and
# single-sourced; the per-module setdefaults below it stay as harmless
# belt-and-braces for `discover -s tests` without `-t .`, which never imports
# this file.
#
# The value comes from core/modes.py::DEFAULT_MODE -- the same single source
# core/runtime.py, core/pipeline.py and core/bo_driver.py now read -- rather
# than a fifth literal that could drift from it. Tests that need a DIFFERENT
# mode must say so per-test (see tests/test_modes.py::TestModeStamping, which
# spawns a fresh interpreter rather than trying to re-point this one).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes as _modes  # noqa: E402
os.environ.setdefault("AUTORESEARCH_MODE", _modes.DEFAULT_MODE)


class _Discard:
    """Minimal write-only sink. `print(..., flush=True)` needs flush()."""

    def write(self, _s):
        return len(_s)

    def flush(self):
        pass

    def isatty(self):
        return False


if not os.environ.get("AUTORESEARCH_TEST_VERBOSE"):
    sys.stdout = _Discard()
