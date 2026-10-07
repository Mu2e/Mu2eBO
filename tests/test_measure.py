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
    "ce_chain": "efe68799bd0a2d599f5b72226cddb39b9bdbe4c6dbb1428084c83eade898888e",
    "foilsflash_ax": "7168e11c18753dea7069d4e308b982efad2d982cf1f7f56135cfb59dd8c934ca",
    "foilspf2k_ax": "b745335f1012bf9484a1976ec3967e0ae5936ce7369359f89dbeec70a5c7b728",
    "foilspf_ax": "dd60ce52710bf13b5d14cfd9a58aeb9d93db9da8dcd94d5a91ab919e2473f0d3",
    "foilspfbp_ax": "82f0becd62921f7ccad8d6f88a1d663902346939d019162573373b8411d38082",
    "foilspfbpx_ax": "3ba745fb27e62447252b92769e228d22573269a07357be374f9560acd0145c40",
    "foilspfbpz_ax": "5bf6b433413bd5325691907824f69e08c989b64166e7ca0c723ca658299437f2",
    "foilspfbw_ax": "a42758de4d23132ef929db5c95a46780096d957f76003f407612e86d5cb01bc6",
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
