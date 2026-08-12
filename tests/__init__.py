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
