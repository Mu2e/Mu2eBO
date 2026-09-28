"""graph/study_graph.py: a resumed point reuses a saved passing pre-check
verdict for the same kit, settings, mapped values and file contents; a
failure is never reused (Phase C2b spec, section 5)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import study as st  # noqa: E402
from kits import KitError  # noqa: E402
from study_graph import (build_study_graph, preflight_basis,  # noqa: E402
                         reusable_pass)
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

PRE = {"kit": "toykit", "params": {"x1": "x1"}, "files": ["geom"]}


class TestBasis(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.geom = self.tmp / "geom.txt"
        self.geom.write_text("double a = 1;\n")

    def basis(self, settings=None, env=None, text=None, ref=None):
        if text is not None:
            self.geom.write_text(text)
        ref = ref or {"name": "geom", "uri": self.geom.as_uri(), "kind": "geom"}
        return preflight_basis(PRE, settings or {"function": "branin"},
                               env or {"x1": 1.0}, [ref])

    def test_the_same_inputs_give_the_same_basis(self):
        self.assertEqual(self.basis(), self.basis())

    def test_each_input_changes_it(self):
        base = self.basis()
        self.assertNotEqual(self.basis(settings={"function": "currin"}), base)
        self.assertNotEqual(self.basis(env={"x1": 2.0}), base)
        self.assertNotEqual(self.basis(text="double a = 2;\n"), base)

    def test_a_non_file_ref_is_kept_by_its_uri(self):
        b = self.basis(ref={"name": "geom", "uri": "root://x//g.txt",
                            "kind": "geom"})
        self.assertEqual(b["files"]["geom"], {"uri": "root://x//g.txt"})

    def test_only_a_saved_pass_with_the_same_basis_is_reusable(self):
        path = self.tmp / "preflight_verdict.json"
        basis = self.basis()
        self.assertFalse(reusable_pass(path, basis))
        for saved, want in (({"ok": True, "message": "m", "basis": basis}, True),
                            ({"ok": False, "message": "m", "basis": basis}, False),
                            ({"ok": True, "message": "m"}, False),
                            ({"ok": True, "message": "m",
                              "basis": self.basis(env={"x1": 9.0})}, False)):
            path.write_text(json.dumps(saved))
            self.assertIs(reusable_pass(path, basis), want, saved)
        path.write_text("{not json")
        self.assertFalse(reusable_pass(path, basis))

    def test_an_oserror_reading_the_verdict_is_not_reusable(self):
        # A directory where a file is expected makes Path.read_text() raise
        # IsADirectoryError (an OSError), not the ValueError the code used to
        # catch alone; the point must be re-checked, not crash.
        path = self.tmp / "preflight_verdict.json"
        path.mkdir()
        self.assertFalse(reusable_pass(path, self.basis()))


class CountingKit:
    """Passes (or fails) the pre-check and counts it; its steps never
    submit, so the point stops broken right after the pre-check."""
    accepts_lists, poll_s, version = False, (0.0, 0.0), "1"
    tools = frozenset({"submit", "status", "results", "check"})

    def __init__(self, ok):
        self.ok, self.checks = ok, 0

    def check(self, name, params, files, inputs, workflow):
        self.checks += 1
        return self.ok, "pass: fine" if self.ok else "fail: no"

    def submit(self, *args):
        raise KitError("toykit", "submit", "not in this test")


class Kits:
    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class TestResume(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        doc = toy_doc(name="reusetoy", layout="v2")
        doc["preflight"] = {"kit": "toykit", "params": {"x1": "x1"},
                            "files": []}
        self.study = st.load_study_file(write_study(doc, self.tmp / "studies"))
        self.state = self.tmp / "grid" / "p1" / "state"

    def run_point(self, kit, logs):
        build_study_graph(self.study, config="p1", campaign="c", context={},
                          kits=Kits(kit), state_dir=self.state, board=None,
                          log=logs.append, executor="local").compile() \
            .invoke({"config_name": "p1", "x_point": [1.0, 2.0]})
        (self.state / "broken.txt").unlink()   # the operator's retry

    def test_a_saved_pass_is_reused_on_resume(self):
        kit, logs = CountingKit(ok=True), []
        self.run_point(kit, logs)
        verdict = json.loads((self.state / "preflight_verdict.json").read_text())
        self.assertTrue(verdict["ok"])
        self.assertIn("basis", verdict)
        self.run_point(kit, logs)
        self.assertEqual(kit.checks, 1)
        self.assertTrue(any("reusing" in m for m in logs), logs)

    def test_a_saved_failure_is_checked_again(self):
        kit, logs = CountingKit(ok=False), []
        self.run_point(kit, logs)
        self.run_point(kit, logs)
        self.assertEqual(kit.checks, 2)


if __name__ == "__main__":
    unittest.main()
