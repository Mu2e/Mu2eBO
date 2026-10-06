"""core/measure.py: one place decides a point's versions and whether a board
matches (spec docs/superpowers/specs/2026-10-05-measure-identity-design.md)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import measure  # noqa: E402
import modes  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

BASIS = {
    "ce_chain": "79b9b3e212d94d04f3aece224d3968cb33eae4e6f52c6e23c937281cd058e771",
    "foilsflash_ax": "405cc0e850b9dc4ed28ee96bea8187c94185bce654230acc5016de73a1763d6f",
    "foilspf2k_ax": "2060c97e7de0a4a18f6364e0a721e6abe45e4bc98a089b4ffedcea75385e12a4",
    "foilspf_ax": "e96f0491abe95519352962dc51616fca0598eabf5b5cfba122734179da3b250e",
    "foilspfbp_ax": "54467d3e05b4742da1fbd3a7809cf50f770fdc18219c40773ada487355cb0547",
    "foilspfbpx_ax": "d6ee2d286f6e8e26a6417dfb9530789beefd8f385179036f60c4385d1e6d8a4d",
    "foilspfbpz_ax": "c4aafee1c30ba5121ab727bcab4513786b6d076c10f976d1b786daf95e218a80",
    "foilspfbw_ax": "01bcbd62be9a8f4d8b825e85267a3e7b45a0746b2784f1c48c32aeacba962191",
    "ptg4bl": "b52fce7c37525597cae53862efe0f272af28f766c6deaefa22b71f08a6861689",
}


def rec(kit, version, step="s"):
    return {"step": step, "kit": kit, "kit_version": version,
            "handle": f"c.{step}"}


class TestVersions(unittest.TestCase):
    def test_recorded_versions(self):
        self.assertEqual(measure.recorded_versions(
            {"a": rec("anakit", "V1", "a"), "b": rec("anakit", "V1", "b"),
             "c": rec("prodtools", "P1", "c")}),
            {"anakit": "V1", "prodtools": "P1"})
        with self.assertRaises(measure.MixedVersions) as cm:
            measure.recorded_versions({"a": rec("anakit", "V1", "a"),
                                       "b": rec("anakit", "V2", "b")})
        self.assertIn("a kit changed version within this point",
                      str(cm.exception))


class _Toy(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        doc = toy_doc(name="mtoy", layout="v2")
        doc["evaluate"].append(dict(doc["evaluate"][0], step="toy2",
                                    files_from=["toy"]))
        for o in doc["objectives"]:     # toy2 feeds the objectives
            o["metric"] = "toy2." + o["metric"].split(".", 1)[1]
        write_study(doc, self.tmp / "studies")
        self.study = st.load_study_file(self.tmp / "studies" / "mtoy.json")


class TestPointVersions(_Toy):
    def test_fresh(self):
        self.assertEqual(measure.point_versions(self.study, {"toykit": "T"}),
                         ({"toykit": "T"}, []))

    def test_all_steps_adopted_keep_the_recorded_version(self):
        adopted = {"toy": rec("toykit", "OLD", "toy"),
                   "toy2": rec("toykit", "OLD", "toy2")}
        versions, problems = measure.point_versions(
            self.study, {"toykit": "NEW"}, adopted)
        self.assertEqual((versions, problems), ({"toykit": "OLD"}, []))

    def test_part_adopted_at_another_version(self):
        versions, problems = measure.point_versions(
            self.study, {"toykit": "NEW"}, {"toy": rec("toykit", "OLD", "toy")})
        self.assertEqual(len(problems), 1)
        self.assertIn("finished under version", problems[0])

    def test_a_resume_across_the_version_format_change(self):
        """A point adopted under the old anakit string, resumed under the
        new one, names both versions (not 'set a new leaderboard.file')."""
        old, new = "anakit-adapter/1+anakit-60cb434419a2", "anakit-adapter/1"
        _, problems = measure.point_versions(
            self.study, {"toykit": new}, {"toy": rec("toykit", old, "toy")})
        self.assertEqual(len(problems), 1)
        self.assertIn(old, problems[0])
        self.assertIn(new, problems[0])
        self.assertNotIn("leaderboard.file", problems[0])


class TestBoardProblems(_Toy):
    def board(self, *shas):
        lb = Leaderboard.for_study(self.study, path=self.tmp / "b.tsv",
                                   archive_path=None)
        cols = lb.header().rstrip("\n").split("\t")
        lines = [lb.header()]
        for i, sha in enumerate(shas):
            row = {c: "1.0" for c in cols}
            row.update(config=f"r{i}", handles="toy=x", spec_sha="s" * 64,
                       measure_sha=sha, time="2026-09-30T00:00:00Z")
            lines.append("\t".join(row[c] for c in cols) + "\n")
        lb.path.write_text("".join(lines))
        return lb

    def test_board_problems(self):
        v = {"toykit": "T"}
        this = self.study.measure_sha(v)
        self.assertEqual(measure.board_problems(self.study, self.board(), v),
                         [])
        self.assertEqual(measure.board_problems(self.study,
                                                self.board(this, this), v), [])
        problems = measure.board_problems(self.study, self.board("f" * 64), v)
        self.assertEqual(len(problems), 1)
        self.assertIn("holds rows measured as", problems[0])


class TestAFullyAdoptedOldPoint(TestBoardProblems):
    def test_the_refusal_names_the_version_change(self):
        """A resumed point whose steps all finished under the old version
        keeps that version, so after a re-stamp it no longer matches the
        board: the refusal names the version change and a new config name,
        not 'a new leaderboard.file' (re-stamping covers rows, not
        unfinished points)."""
        old, new = "anakit-adapter/1+anakit-60cb434419a2", "anakit-adapter/1"
        adopted = {"toy": rec("toykit", old, "toy"),
                   "toy2": rec("toykit", old, "toy2")}
        versions, problems = measure.point_versions(
            self.study, {"toykit": new}, adopted)
        self.assertEqual((versions, problems), ({"toykit": old}, []))
        board = self.board(self.study.measure_sha({"toykit": new}))
        problems = measure.board_problems(self.study, board, versions,
                                          current={"toykit": new})
        self.assertEqual(len(problems), 1)
        for needle in (old, new, "new config name"):
            self.assertIn(needle, problems[0])
        self.assertNotIn("leaderboard.file", problems[0])


class TestHandVersion(unittest.TestCase):
    def test_hand_version(self):
        hv = measure.hand_version
        self.assertEqual(hv("anakit", "anakit-adapter/1+anakit-60cb434419a2"),
                         "anakit-adapter/1")
        self.assertEqual(hv("beamkit", "beamkit-adapter/1+beamkit-0.5.1+fom1"),
                         "beamkit-adapter/1+fom1")
        self.assertEqual(hv("anakit", "anakit-adapter/1"), "anakit-adapter/1")
        self.assertEqual(hv("prodtools", "prodtools-adapter/1+x"),
                         "prodtools-adapter/1+x")
        with self.assertRaises(ValueError):
            hv("anakit", "anakit-adapter/1+anakit-")


class TestFingerprints(unittest.TestCase):
    def test_basis_shas_are_pinned(self):
        self.assertEqual({n: s.measure_basis_sha
                          for n, s in modes.STUDIES.items()}, BASIS)


if __name__ == "__main__":
    unittest.main()
