"""The ce_chain study (docs/superpowers/specs/2026-09-30-ce-chain-design.md):
the CeEndpoint dts -> dig -> mcs -> nts -> plot chain, zero knobs."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
from core.adapters import prodtools_entry  # noqa: E402

PRODTOOLS_STEPS = ["ce", "dig", "mcs", "nts"]


def load():
    return st.load_study_file(ROOT / "mode_specs" / "ce_chain.json")


class TestCeChain(unittest.TestCase):
    def test_it_loads_with_five_steps(self):
        s = load()
        self.assertEqual([x.step for x in s.steps],
                         ["ce", "dig", "mcs", "nts", "plot"])
        self.assertEqual([x.kit for x in s.steps],
                         ["prodtools"] * 4 + ["anakit"])
        self.assertEqual(s.knobs, ())

    def test_every_prodtools_step_gets_the_one_geometry(self):
        s = load()
        steps = [x for x in s.steps if x.kit == "prodtools"]
        self.assertEqual([x.step for x in steps], PRODTOOLS_STEPS)
        for x in steps:
            self.assertEqual(x.files, ("geom",), x.step)
            template = st._stage_template(x.entry, x.step)
            entry, _ = prodtools_entry.entry_for_step(
                template, config="c1", fixed=x.fixed, code_tarball="x",
                dsconf="MDC2025ax_{cfg}", geom_name="autoresearch_c1_geom.txt")
            self.assertEqual(
                entry["fcl_overrides"]["services.GeometryService.inputFile"],
                "autoresearch_c1_geom.txt", x.step)

    def test_the_rendered_geometry_is_the_base_alone(self):
        text = load().geom.render([])
        self.assertIn('#include "Offline/Mu2eG4/geom/geom_run1_a.txt"', text)
        rest = [ln for ln in text.splitlines()
                if not ln.startswith("#include") and ln.strip()]
        self.assertEqual(rest, [])
        self.assertIsNone(re.search(r"^\s*\S+\s*:", text, re.M))

    def test_the_plot_step_runs_nts_momentum(self):
        s = load()
        plot = s.steps[-1]
        self.assertEqual(plot.fixed["analysis"], "nts_momentum")
        self.assertEqual(plot.files_from, ("nts",))
        self.assertIsNone(plot.entry)
        self.assertEqual(s.objectives[0].metric, "plot.n_fits")

    def test_the_surrogate_does_not_list_it(self):
        from surrogate import adapter
        import modes
        self.assertIn("ce_chain", modes.STUDIES)
        self.assertNotIn("ce_chain", adapter.AutoresearchAdapter().problems())


if __name__ == "__main__":
    unittest.main()
