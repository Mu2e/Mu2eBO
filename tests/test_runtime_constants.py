"""core/runtime.py owns the non-path runtime tunables graph/config.py held.

presniff.py existed only because config.py read AUTORESEARCH_* env vars at
IMPORT time while argparse ran in main() -- too late. Constants that are
plain values, resolved once, need no pre-argparse sniffing, so both files go.
`_SPEC` is NOT such a constant: it is a mode-keyed lookup, so the --mode
stamp came back as `core/modes.py::stamp_mode_from_argv()` (final review,
finding I1). The MODULE stays dead -- the tests below pin its absence, not
the absence of pre-argparse stamping. See tests/test_modes.py::
TestModeStamping for the restored mechanism.

NAMES deliberately omits CLOSED_LOOP_BARRIER_POLL_SEC and
CLOSED_LOOP_BARRIER_MAX_MIN, which the originating plan listed as required
exports. Task 3 deleted the closed-loop barrier those constants paced; a
repo-wide grep at the time this file was written found no reference to
either name outside graph/config.py itself. Reviving them here would be
migrating dead weight forward for no consumer -- see wiki ledger Ruling 3
for the same call applied to open_saver_conn/CHECKPOINT_DB/SQLITE_TIMEOUT_S
(also not in NAMES, also not migrated).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

NAMES = [
    "DEFAULT_MODE", "DEFAULT_ALPHA", "MAX_PROPOSE_RETRIES",
    "PREFLIGHT_TIMEOUT_S", "CLOSED_LOOP_Q", "CLOSED_LOOP_MAX_ROUNDS",
    "CLOSED_LOOP_STAGGER_SEC", "STOP_FLAG", "BOTORCH_VENV_PY",
    "BOTORCH_PREDICT", "BO_DRIVER", "PIPELINE_DRIVER", "GRID_STAGES",
    "PRESUBMIT_AFTER", "MUSING",
]


class TestRuntimeConstants(unittest.TestCase):
    def test_all_names_present(self):
        import runtime
        missing = [n for n in NAMES if not hasattr(runtime, n)]
        self.assertEqual(missing, [])

    def test_graph_config_is_gone(self):
        self.assertFalse((ROOT / "graph" / "config.py").exists())

    def test_presniff_is_gone(self):
        self.assertFalse((ROOT / "graph" / "presniff.py").exists())

    def test_no_module_imports_graph_config(self):
        offenders = []
        for p in list((ROOT / "graph").glob("*.py")) + list((ROOT / "core").glob("*.py")):
            t = p.read_text()
            if "from config import" in t or "import presniff" in t:
                offenders.append(p.name)
        self.assertEqual(offenders, [])

    def test_default_mode_is_a_live_mode(self):
        import modes
        import runtime
        self.assertIn(runtime.DEFAULT_MODE, modes.SPECS)


if __name__ == "__main__":
    unittest.main()
