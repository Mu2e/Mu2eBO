"""graph/check_study.py: a study file is checked before launch -- it loads,
its ${ARTIFACT} paths exist, the launch check passes and its geometry
passes the pre-check at the center point -- with nothing submitted and no
board row (spec docs/superpowers/specs/2026-10-01-check-study-design.md)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
from study_graph import build_study_graph  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

PRE = {"kit": "toykit", "files": [], "params": {}}


class _Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)


class PassingKit:
    """Passes the pre-check; a submit would be a step running, which a
    graph built through the preflight must never reach."""
    accepts_lists = False

    def __init__(self):
        self.checks = 0

    def check(self, name, params, files, inputs, workflow):
        self.checks += 1
        return True, "ok"

    def submit(self, *args, **kwargs):
        raise AssertionError("submit called on a graph built through preflight")


class Kits:
    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class TestThrough(_Tmp):
    def build(self, through, kit=None):
        doc = toy_doc()
        doc["preflight"] = dict(PRE)
        study = st.load_study_file(write_study(doc, self.tmp / "studies"))
        self.state = self.tmp / "grid" / "c1" / "state"
        return build_study_graph(study, config="c1", campaign="t", context={},
                                 kits=Kits(kit or PassingKit()),
                                 state_dir=self.state, board=None,
                                 log=lambda m: None, through=through)

    def test_through_preflight_stops_before_the_steps(self):
        kit = PassingKit()
        out = self.build("preflight", kit).compile().invoke(
            {"config_name": "c1", "x_point": [2.5, 7.5]})
        self.assertFalse(out["broken"])
        self.assertEqual(kit.checks, 1)
        for name in ("point.json", "derived.json", "preflight_verdict.json"):
            self.assertTrue((self.state / name).exists(), name)
        for name in ("toy_results.json", "toy_cluster.txt"):
            self.assertFalse((self.state / name).exists(), name)

    def test_an_unknown_through_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.build("run_steps")
        self.assertIn("'run_steps'", str(cm.exception))


class TestStudyFiles(_Tmp):
    def test_it_lists_what_load_study_dirs_loads(self):
        a, b = self.tmp / "a", self.tmp / "b"
        write_study(toy_doc(name="x"), a)
        write_study(toy_doc(name="y"), b)
        self.assertEqual(st.study_files(a, str(b)), [a / "x.json", b / "y.json"])
        self.assertEqual(sorted(st.load_study_dirs(a, str(b))), ["x", "y"])
        with self.assertRaises(ValueError):
            st.study_files(a, "relative/dir")


if __name__ == "__main__":
    unittest.main()
