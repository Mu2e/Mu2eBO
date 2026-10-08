"""core/measure.py: one place decides a point's versions and whether a board
matches (spec docs/superpowers/specs/2026-10-05-measure-identity-design.md)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import measure  # noqa: E402
import modes  # noqa: E402
from tests.engine_fixtures import TmpCase, toy_study, write_board  # noqa: E402

BASIS = {
    "ce_chain": "3a300aecbea8dba8d289c4f78c4a941b01ec18c2293a14a793b86f7263e59189",
    "foilsflash_ax": "b96e6c99648c677b5046f7f223df5477eba156dc27ecb15aaed57d31e6b904bd",
    "foilspf_nominal": "f0a9aa00d9d06eeb8235281fc035ad78b0852b4cdf3e487c919412e247539310",
    "foilspfbpz_ax": "fa84cd6e195e4ef865d62c42f8085deb24a81213197a814e23aab49f8856c570",
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


def _two_steps(doc):
    doc["evaluate"].append(dict(doc["evaluate"][0], step="toy2",
                                files_from=["toy"]))
    for o in doc["objectives"]:     # toy2 feeds the objectives
        o["metric"] = "toy2." + o["metric"].split(".", 1)[1]


class _Toy(TmpCase):
    def setUp(self):
        super().setUp()
        self.study = toy_study(self.tmp / "studies", _two_steps, name="mtoy")


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
        return write_board(self.study, self.tmp / "b.tsv", *shas)

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
        keeps that version, so it no longer matches a board measured at the
        current one: the refusal names the version change and a new config
        name, not 'a new leaderboard.file' (the point, not the board, is
        out of date)."""
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


class TestFingerprints(unittest.TestCase):
    def test_basis_shas_are_pinned(self):
        self.assertEqual({n: s.measure_basis_sha
                          for n, s in modes.STUDIES.items()}, BASIS)


if __name__ == "__main__":
    unittest.main()
