import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that are generic end to end: no physics names at all.
STRICT = ["core/study.py", "core/leaderboard.py"]
# core/study_compat.py builds metric_cols and names the harvest plugins by
# design -- it is the schema-1-compat bridge and is deleted in Phase C.
EXEMPT_UNTIL_PHASE_C = ["core/study_compat.py"]
# Files that still host Mu2e code paths (preflight, picker names like
# budget_sob) but must not read objectives by physics name.
USAGE = ["core/botorch_predict.py", "core/bo_driver.py",
         "surrogate/adapter.py", "graph/pipeline_io.py",
         "core/kit_registry.py"]
USAGE_RX = re.compile(r"\.sob\b|\.calo\b|\bmetric_cols\b|flash_budget|"
                      r"budget_k_sigma|calo_or_flash|\bsob_only\b")


class TestGenericCore(unittest.TestCase):
    def test_strict_files_name_no_physics(self):
        rx = re.compile(r"\bsob\b|\bcalo\b|flash", re.IGNORECASE)
        for rel in STRICT:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if rx.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])

    def test_usage_files_read_objectives_by_study_name(self):
        for rel in USAGE:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if USAGE_RX.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
