import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tools"))
import convert_spec_v2 as cv  # noqa: E402
import study_compat as sc  # noqa: E402
from mode_json import load_mode_file  # noqa: E402

LIVE = sorted((ROOT / "mode_specs").glob("*.json"))
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "modes").glob("*.json"))


def _x_points(spec):
    lo, hi = spec.bounds_lo, spec.bounds_hi
    return [list(lo), [(a + b) / 2 for a, b in zip(lo, hi)],
            [a + 0.3 * (b - a) for a, b in zip(lo, hi)]]


class TestConversionMatchesOldLoader(unittest.TestCase):
    def _compare(self, path, allow_presubmit_change=False):
        old = load_mode_file(path)
        doc = json.loads(path.read_text())
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / path.name
            p.write_text(json.dumps(cv.convert(doc)))
            new = sc.load_modespec(p)
        skip = {"geom", "metrics"}
        if allow_presubmit_change:
            skip.add("presubmit_after")
        for f in dataclasses.fields(old):
            if f.name in skip:
                continue
            with self.subTest(file=path.name, field=f.name):
                self.assertEqual(getattr(new, f.name), getattr(old, f.name))
        # The one intended change: no per-event fallback for the flash metric.
        self.assertEqual(new.metrics["sob"], old.metrics["sob"])
        self.assertEqual(new.metrics[old.metric_cols[1]],
                         old.metrics[old.metric_cols[1]][:1])
        for x in _x_points(old):
            self.assertEqual(new.geom.render(x), old.geom.render(x))

    def test_every_live_spec(self):
        self.assertEqual(len(LIVE), 7)
        for p in LIVE:
            self._compare(p)

    def test_fixtures(self):
        # foils.json and template.json declare no presubmit_after; in
        # schema 2 two independent steps always start together, so their
        # view gains {mubeam: (elebeam_flash,)}. Everything else must match.
        for p in FIXTURES:
            self._compare(p, allow_presubmit_change=True)


class TestConvertShape(unittest.TestCase):
    def test_structure(self):
        doc = json.loads((ROOT / "mode_specs" / "foilspfbpz.json").read_text())
        out = cv.convert(doc)
        self.assertEqual(out["schema"], 2)
        self.assertEqual([s["step"] for s in out["evaluate"]],
                         ["mubeam", "mustops_ce", "elebeam_flash", "sob", "flash"])
        self.assertEqual(out["constraints"],
                         [{"name": "flash_edep", "max": 6.85443e-7, "k_sigma": 1.0}])
        self.assertEqual(out["leaderboard"]["context"], ["alpha"])
        self.assertEqual(out["derive"]["profiles"]["rOut_p"]["kind"], "lagrange")

    def test_refuses_unexpected_metrics(self):
        doc = json.loads((ROOT / "mode_specs" / "foilspf.json").read_text())
        doc["leaderboard"]["metrics"]["sob"] = ["something_else"]
        with self.assertRaises(ValueError):
            cv.convert(doc)

    def test_refuses_unexpected_presubmit_after(self):
        doc = json.loads((ROOT / "mode_specs" / "foilspf.json").read_text())
        doc["run"]["presubmit_after"] = {"mubeam": ["mustops_ce"]}
        with self.assertRaisesRegex(ValueError, "presubmit_after"):
            cv.convert(doc)


if __name__ == "__main__":
    unittest.main()
