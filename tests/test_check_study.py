"""graph/check_study.py: a study file is checked before launch -- it loads,
its ${ARTIFACT} paths exist, the launch check passes and its geometry
passes the pre-check at the center point -- with nothing submitted and no
board row (spec docs/superpowers/specs/2026-10-01-check-study-design.md)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "graph"))
sys.path.insert(0, str(ROOT))
import check_study as cs  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402
from study_graph import build_study_graph  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from tests.engine_fixtures import engine_env, toy_doc, write_study  # noqa: E402

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


class _Studies(_Tmp):
    """A study directory on $AUTORESEARCH_STUDY_PATH."""
    def setUp(self):
        super().setUp()
        self.studies = self.tmp / "studies"
        self.studies.mkdir()
        patcher = mock.patch.dict(os.environ, {
            "AUTORESEARCH_STUDY_PATH": str(self.studies)})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestTarget(_Studies):
    def test_an_existing_json_path_is_itself(self):
        path = write_study(toy_doc(), self.tmp / "drafts")
        self.assertEqual(cs.resolve_target(str(path)), path)

    def test_a_missing_path_is_refused(self):
        with self.assertRaises(ValueError):
            cs.resolve_target(str(self.tmp / "nosuch.json"))

    def test_a_name_resolves_through_the_study_path(self):
        write_study(toy_doc(), self.studies)
        self.assertEqual(cs.resolve_target("toystudy"),
                         self.studies / "toystudy.json")

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            cs.resolve_target("nosuchstudy")
        self.assertIn("nosuchstudy", str(cm.exception))


class TestLoad(_Studies):
    def test_a_good_study_passes(self):
        check, study = cs.check_load(write_study(toy_doc(), self.studies))
        self.assertEqual(check.status, "passed", check.problems)
        self.assertEqual(study.name, "toystudy")

    def test_a_load_error_fails(self):
        doc = toy_doc()
        doc["objectives"] = []
        check, study = cs.check_load(write_study(doc, self.tmp / "drafts"))
        self.assertEqual(check.status, "failed")
        self.assertIsNone(study)
        self.assertTrue(any("objectives" in p for p in check.problems),
                        check.problems)

    def test_name_must_equal_the_file_stem(self):
        path = self.tmp / "drafts" / "beta.json"
        path.parent.mkdir()
        path.write_text(json.dumps(toy_doc(name="alpha")))
        check, _ = cs.check_load(path)
        self.assertEqual(check.status, "failed")
        self.assertTrue(any("'alpha'" in p and "beta.json" in p
                            for p in check.problems), check.problems)

    def test_a_board_used_by_another_study_fails(self):
        t1 = write_study(toy_doc(name="t1"), self.studies)
        t2 = toy_doc(name="t2")
        t2["leaderboard"]["file"] = toy_doc(name="t1")["leaderboard"]["file"]
        write_study(t2, self.studies)
        check, _ = cs.check_load(t1)
        self.assertEqual(check.status, "failed")
        self.assertTrue(any("t2.json" in p for p in check.problems),
                        check.problems)

    def test_the_same_study_on_the_path_is_this_study(self):
        check, _ = cs.check_load(write_study(toy_doc(), self.studies))
        self.assertEqual(check.status, "passed", check.problems)

    def test_a_draft_of_a_loaded_study_is_this_study(self):
        write_study(toy_doc(), self.studies)
        check, _ = cs.check_load(write_study(toy_doc(), self.tmp / "drafts"))
        self.assertEqual(check.status, "passed", check.problems)

    def test_another_broken_study_is_a_load_problem(self):
        target = write_study(toy_doc(), self.studies)
        (self.studies / "bad.json").write_text("{}")
        check, _ = cs.check_load(target)
        self.assertEqual(check.status, "failed")
        self.assertTrue(any("bad.json" in p
                            and "every launch loads all studies" in p
                            for p in check.problems), check.problems)

    def test_a_study_defined_twice_on_the_path_fails(self):
        other = self.tmp / "more"
        write_study(toy_doc(), other)
        target = write_study(toy_doc(), self.studies)
        with mock.patch.dict(os.environ, {
                "AUTORESEARCH_STUDY_PATH": f"{self.studies}:{other}"}):
            check, _ = cs.check_load(target)
        self.assertEqual(check.status, "failed")
        self.assertTrue(any("defined twice" in p for p in check.problems),
                        check.problems)


class TestArtifacts(_Tmp):
    REL = "no/such/file.tbl"

    def doc_path(self):
        doc = toy_doc()
        doc["kits"]["toykit"]["function"] = "${ARTIFACT}/" + self.REL
        return write_study(doc, self.tmp / "drafts")

    def test_a_missing_artifact_fails_naming_its_location(self):
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp / "art"), \
                mock.patch.object(paths, "BACKING", None):
            check = cs.check_artifacts(self.doc_path())
        self.assertEqual(check.status, "failed")
        self.assertEqual(len(check.problems), 1, check.problems)
        self.assertTrue(check.problems[0].startswith("kits.toykit.function: "),
                        check.problems)

    def test_an_existing_artifact_passes(self):
        art = self.tmp / "art"
        (art / self.REL).parent.mkdir(parents=True)
        (art / self.REL).write_text("x")
        with mock.patch.object(paths, "ARTIFACT_ROOT", art), \
                mock.patch.object(paths, "BACKING", None):
            check = cs.check_artifacts(self.doc_path())
        self.assertEqual(check.status, "passed", check.problems)

    def test_a_list_index_is_part_of_the_location(self):
        doc = toy_doc()
        doc["evaluate"][0]["fixed"]["table"] = "${ARTIFACT}/" + self.REL
        path = write_study(doc, self.tmp / "drafts")
        with mock.patch.object(paths, "ARTIFACT_ROOT", self.tmp / "art"), \
                mock.patch.object(paths, "BACKING", None):
            check = cs.check_artifacts(path)
        self.assertTrue(check.problems[0].startswith("evaluate[0].fixed.table: "),
                        check.problems)

    def test_none_passes_with_a_note(self):
        check = cs.check_artifacts(write_study(toy_doc(), self.tmp / "drafts"))
        self.assertEqual((check.status, check.note),
                         ("passed", "no ${ARTIFACT} paths"))


class TestCenter(_Tmp):
    def load(self, doc):
        return st.load_study_file(write_study(doc, self.tmp / "drafts"))

    def test_the_midpoint_of_each_knob(self):
        self.assertEqual(cs.center_point(self.load(toy_doc())), [2.5, 7.5])

    def test_an_int_knob_floors(self):
        doc = toy_doc()
        doc["knobs"][1] = {"name": "x2", "type": "int", "min": 1, "max": 4,
                           "unit": "", "fmt": "{:.0f}"}
        self.assertEqual(cs.center_point(self.load(doc))[1], 2.0)

    def test_no_knobs_is_the_empty_point(self):
        doc = toy_doc()
        doc["knobs"] = []
        doc["evaluate"][0]["params"] = {}
        doc["evaluate"][0]["fixed"].update(x1=1.0, x2=2.0)
        self.assertEqual(cs.center_point(self.load(doc)), [])


class TestReport(unittest.TestCase):
    def test_ok_only_when_every_check_passed(self):
        passed = cs.Check("load", "passed")
        for other in (cs.Check("geometry", "skipped", note="skipped: x"),
                      cs.Check("geometry", "failed", ["bad"])):
            rep = cs.report("s", "/p/s.json", {"x1": 1.0}, [passed, other])
            self.assertFalse(rep["ok"])
        self.assertTrue(cs.report("s", "/p/s.json", None, [passed])["ok"])

    def test_it_round_trips_through_json(self):
        rep = cs.report("s", "/p/s.json", {"x1": 1.0},
                        [cs.Check("load", "failed", ["bad"])])
        self.assertEqual(json.loads(json.dumps(rep)), rep)
        self.assertEqual(rep["checks"][0], {"name": "load", "status": "failed",
                                            "problems": ["bad"], "note": ""})

    def test_text_lists_problems_and_ends_failed(self):
        rep = cs.report("s", "/p/s.json", None,
                        [cs.Check("load", "failed", ["it broke"])])
        text = cs.render_text(rep)
        self.assertIn("    - it broke", text)
        self.assertEqual(text.splitlines()[-1], "FAILED")


def toy_pre(**kits):
    doc = toy_doc()
    doc["preflight"] = dict(PRE)
    doc["kits"]["toykit"].update(kits)
    return doc


class TestMain(_Tmp):
    """python -m graph.check_study, as the skill and the MCP tool call it."""
    LOCAL = ("--executor", "local", "--parallel", "1")

    def setUp(self):
        super().setUp()
        self.studies = self.tmp / "studies"
        self.studies.mkdir()
        self.data = self.tmp / "data"
        self.env = engine_env(self.data, self.studies)
        self.scratch = self.data / "autoresearch_grid" / "check_toystudy"

    def check(self, *args, json_out=True):
        argv = [sys.executable, "-m", "graph.check_study", *args, *self.LOCAL]
        if json_out:
            argv.append("--json")
        r = subprocess.run(argv, cwd=ROOT, env=self.env, capture_output=True,
                           text=True, timeout=120)
        self.assertNotIn("Traceback", r.stderr)
        out = json.loads(r.stdout) if json_out and r.returncode != 2 else None
        return r, out

    @staticmethod
    def checks(out):
        return {c["name"]: c for c in out["checks"]}

    def test_a_good_study_passes_every_check(self):
        write_study(toy_pre(), self.studies)
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(out["ok"])
        self.assertEqual([c["status"] for c in out["checks"]], ["passed"] * 4)
        self.assertEqual(list(self.checks(out)),
                         ["load", "artifacts", "launch", "geometry"])
        self.assertEqual(out["point"], {"x1": 2.5, "x2": 7.5})
        self.assertFalse((self.data / "autoresearch_leaderboards"
                          / "leaderboard_toystudy.tsv").exists())
        for name in ("toy_results.json", "toy_cluster.txt"):
            self.assertEqual(list(self.scratch.rglob(name)), [], name)

    def test_a_failing_precheck_is_a_failed_geometry(self):
        write_study(toy_pre(function="reject"), self.studies)
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        c = self.checks(out)
        self.assertEqual(c["launch"]["status"], "passed", c["launch"])
        self.assertEqual(c["geometry"]["status"], "failed")
        self.assertTrue(any("fails the check" in p
                            for p in c["geometry"]["problems"]), c["geometry"])

    def test_a_load_failure_skips_the_rest(self):
        doc = toy_pre()
        doc["objectives"] = []
        path = write_study(doc, self.tmp / "drafts")
        r, out = self.check(str(path))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIsNone(out["point"])
        c = self.checks(out)
        self.assertEqual(c["load"]["status"], "failed")
        for name in ("artifacts", "launch", "geometry"):
            self.assertEqual(c[name]["status"], "skipped", c[name])

    def test_a_broken_draft_on_the_study_path_is_a_failed_load(self):
        bad = self.studies / "bad.json"
        bad.write_text("{}")
        r, out = self.check(str(bad))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.checks(out)["load"]["status"], "failed")

    def test_a_board_of_another_measure_sha_fails_launch_and_skips_geometry(self):
        path = write_study(toy_pre(), self.studies)
        board = self.data / "autoresearch_leaderboards" / "leaderboard_toystudy.tsv"
        board.parent.mkdir(parents=True)
        header = Leaderboard.for_study(st.load_study_file(path), path=board,
                                       archive_path=None).header()
        cols = header.rstrip("\n").split("\t")
        row = ["old1" if c == "config" else "b" * 64 if c == "measure_sha"
               else "1" for c in cols]
        board.write_text(header + "\t".join(row) + "\n")
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        c = self.checks(out)
        self.assertEqual(c["launch"]["status"], "failed")
        self.assertTrue(any("bbbbbbbbbbbb" in p
                            for p in c["launch"]["problems"]), c["launch"])
        self.assertEqual(c["geometry"]["status"], "skipped")

    def test_x_overrides_the_center(self):
        write_study(toy_pre(), self.studies)
        r, out = self.check("toystudy", "--x=1,2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out["point"], {"x1": 1.0, "x2": 2.0})

    def test_a_wrong_length_x_is_a_failed_geometry(self):
        write_study(toy_pre(), self.studies)
        r, out = self.check("toystudy", "--x=1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        geometry = self.checks(out)["geometry"]
        self.assertEqual(geometry["status"], "failed")
        self.assertTrue(any("2 knobs" in p for p in geometry["problems"]),
                        geometry)

    def test_the_marker_dir_is_emptied_and_a_bare_dir_is_refused(self):
        write_study(toy_pre(), self.studies)
        self.assertEqual(self.check("toystudy")[0].returncode, 0)
        stale = self.scratch / "stale.txt"
        stale.write_text("old")
        r, _ = self.check("toystudy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue((self.scratch / ".check_study").exists())
        (self.scratch / ".check_study").unlink()
        stale.write_text("old")
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        geometry = self.checks(out)["geometry"]
        self.assertEqual(geometry["status"], "failed")
        self.assertTrue(any("no .check_study marker" in p
                            for p in geometry["problems"]), geometry)
        self.assertTrue(stale.exists())

    def test_a_geometry_without_precheck_is_rendered(self):
        doc = toy_doc()
        doc["geom"] = {"writer": "offline_simpleconfig",
                       "base": "Offline/Mu2eG4/geom/geom_run1_a.txt",
                       "lines": []}
        doc["evaluate"][0]["files"] = ["geom"]
        write_study(doc, self.studies)
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.checks(out)["geometry"]["note"],
                         "rendered, not pre-checked")
        self.assertTrue((self.scratch / "state" / "geom.txt").exists())

    def test_a_derive_error_at_the_point_is_a_failed_geometry(self):
        doc = toy_doc()
        doc["derive"]["exprs"] = {"inv": "1 / (x1 - 2.5)"}
        doc["geom"] = {"writer": "offline_simpleconfig",
                       "base": "Offline/Mu2eG4/geom/geom_run1_a.txt",
                       "lines": []}
        write_study(doc, self.studies)
        r, out = self.check("toystudy")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        geometry = self.checks(out)["geometry"]
        self.assertEqual(geometry["status"], "failed")
        self.assertTrue(any("ZeroDivisionError" in p or "division" in p
                            for p in geometry["problems"]), geometry)

    def test_an_unknown_name_is_exit_2(self):
        r, _ = self.check("nosuchstudy")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("nosuchstudy", r.stderr)

    def test_a_non_numeric_x_is_exit_2(self):
        write_study(toy_pre(), self.studies)
        r, _ = self.check("toystudy", "--x=a,2")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_text_mode_ends_with_ok(self):
        write_study(toy_pre(), self.studies)
        r, _ = self.check("toystudy", json_out=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "OK")


if __name__ == "__main__":
    unittest.main()
