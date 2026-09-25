import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that are generic end to end: no physics names at all.
# core/study_compat.py is deliberately in neither list: it builds
# metric_cols and names the harvest plugins by design -- it is the
# schema-1-compat bridge and is deleted in Phase C.
STRICT = ["core/study.py", "core/leaderboard.py", "core/kit_config.py",
          "core/kits.py", "core/contract.py", "core/boards.py",
          "core/scheduler.py", "core/score.py", "graph/study_graph.py",
          "graph/study_run.py", "graph/study_loop.py"]
# Files that still host Mu2e code paths (preflight, picker names like
# budget_sob) but must not read objectives by physics name.
USAGE = ["core/botorch_predict.py", "core/bo_driver.py",
         "surrogate/adapter.py", "graph/pipeline_io.py",
         "core/kit_registry.py"]
# Attribute reads (`.sob`), the retired ModeSpec/env symbols, and quoted
# physics-name reads (`y["sob"]`, `values['flash_edep']`). The quoted form
# needs the closing quote right after the name, so the plugin kit name
# "flash_edep_per_pot" is not a hit.
USAGE_RX = re.compile(r"\.sob\b|\.calo\b|\bmetric_cols\b|flash_budget|"
                      r"budget_k_sigma|calo_or_flash|\bsob_only\b|"
                      r"[\"'](sob|calo|flash_edep|s_over_sqrt_b)[\"']")


class TestGenericCore(unittest.TestCase):
    def test_strict_files_name_no_physics(self):
        rx = re.compile(r"\bsob\b|\bcalo\b|flash", re.IGNORECASE)
        for rel in STRICT:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if rx.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])

    def test_usage_regex_catches_the_forms_it_claims(self):
        for hit in ('y["sob"]', "y['sob']", 'p.y["calo"]',
                    'values["flash_edep"]', "summary['s_over_sqrt_b']",
                    "spec.sob", "metric_cols[1]"):
            with self.subTest(hit=hit):
                self.assertTrue(USAGE_RX.search(hit), hit)
        for miss in ('KitDecl("flash_edep_per_pot", ...)', "o.name",
                     'values[o.name]', "sobriety"):
            with self.subTest(miss=miss):
                self.assertFalse(USAGE_RX.search(miss), miss)

    def test_usage_files_read_objectives_by_study_name(self):
        for rel in USAGE:
            text = (ROOT / rel).read_text()
            hits = [ln for ln in text.splitlines() if USAGE_RX.search(ln)]
            with self.subTest(file=rel):
                self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
