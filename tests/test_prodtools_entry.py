import errno
import hashlib
import json
import os
import shutil
import sys
import tarfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
from adapters import prodtools_entry as pe  # noqa: E402
from tests.engine_fixtures import TmpCase  # noqa: E402

PARITY = ROOT / "tests" / "fixtures" / "prodtools_parity"
# foilspfbpz's fixed values, which gridphaseA01 ran with.
FIXED = {"mubeam": {"njobs": 15, "events_per_job": 200000, "memory_mb": 2000},
         "mustops_ce": {"njobs": 15, "events_per_job": 75000,
                        "memory_mb": 2000},
         "elebeam_flash": {"njobs": 100, "events_per_job": 110000,
                           "memory_mb": 2000}}


def template(step):
    return json.loads((ROOT / "stage_entries" / f"{step}.json").read_text())


class TestParity(unittest.TestCase):
    def test_entries_match_gridphaseA01(self):
        for step in FIXED:
            (want,) = json.loads((PARITY / f"{step}_entry.json").read_text())
            staged = (("STAGED", dict(want["input_data"]))
                      if want["inloc"] == "dir:STAGED" else None)
            with mock.patch.object(pe, "USER", want["owner"]):
                got, facts = pe.entry_for_step(
                    template(step), config="gridphaseA01", fixed=FIXED[step],
                    code_tarball="CODE", dsconf="Run1Bak_{cfg}",
                    geom_name="autoresearch_gridphaseA01_geom.txt",
                    staged=staged)
            # The mustops_ce template gained sequential_aux after
            # gridphaseA01 ran (a5e991d); nothing else may differ.
            got.pop("sequential_aux", None)
            with self.subTest(step=step):
                self.assertEqual(got, want)
                self.assertEqual((facts["desc"], facts["dsconf"]),
                                 (want["desc"], want["dsconf"]))


class TestEntryForStep(unittest.TestCase):
    def test_refusals(self):
        mubeam = template("mubeam")
        for label, t, kw, *needles in (
                # the template names {geom} but the study has no geom file
                ("{geom} without a geom file", mubeam,
                 dict(dsconf="Run1Bak_{cfg}"), "{geom}"),
                ("a template still naming dsconf_fmt",
                 dict(mubeam, dsconf_fmt="Run1Bak_{cfg}"),
                 dict(dsconf="Run1Bak_{cfg}", geom_name="g.txt"),
                 "dsconf_fmt", "kits.prodtools.dsconf"),
                ("a dsconf without {cfg}", mubeam,
                 dict(dsconf="Run1Bak", geom_name="g.txt"), "{cfg}")):
            with self.subTest(label):
                with self.assertRaises(ValueError) as cm:
                    pe.entry_for_step(t, config="c1", fixed={},
                                      code_tarball="CODE", **kw)
                for n in needles:
                    self.assertIn(n, str(cm.exception))

    def test_the_run_label_is_the_dsconf_setting_with_cfg_filled(self):
        entry, facts = pe.entry_for_step(
            template("mubeam"), config="c1", fixed={}, code_tarball="CODE",
            dsconf="MDC2025ax_{cfg}", geom_name="g.txt")
        self.assertEqual((entry["dsconf"], facts["dsconf"]),
                         ("MDC2025ax_c1", "MDC2025ax_c1"))

    def test_template_defaults_fill_what_fixed_omits(self):
        entry, facts = pe.entry_for_step(template("elebeam_flash"),
                                         config="c1", fixed={},
                                         code_tarball="CODE",
                                         dsconf="Run1Bak_{cfg}",
                                         geom_name="g.txt")
        self.assertEqual((entry["njobs"], entry["events"], entry["memory"]),
                         (100, 2500, "3000MB"))
        self.assertEqual(facts["events_per_job"], 2500)


class TestTheEntry(unittest.TestCase):
    """The json2jobdef entry entry_for_step builds, key by key (render_entry
    until it was folded into entry_for_step, its only caller)."""

    def entry(self, fixed=None, staged=None, **template):
        t = dict(desc_fmt="Run1A_MuBeam_{cfg}", njobs=200,
                 # `fcl` is the published Production FCL path, not a
                 # per-config materialized file's basename.
                 fcl="Production/JobConfig/pileup/MuBeamResampler.fcl",
                 output_glob="*.art")
        t.update(template)
        entry, _ = pe.entry_for_step(
            t, config="t001", fixed=fixed or {},
            code_tarball=Path("/data/t001/Code.tar.bz2"),
            dsconf="Run1Bak_{cfg}", staged=staged)
        return entry

    def test_resampler_stage_shape(self):
        e = self.entry(events=5000, run=1800,
                       resampler_name="beamResampler",
                       input_data={"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                       inloc="tape")
        self.assertEqual(e["desc"], "Run1A_MuBeam_t001")
        self.assertEqual(e["dsconf"], "Run1Bak_t001")
        self.assertEqual(e["fcl"],
                         "Production/JobConfig/pileup/MuBeamResampler.fcl")
        self.assertEqual(e["code"], "/data/t001/Code.tar.bz2")
        self.assertEqual(e["events"], 5000)
        self.assertEqual(e["run"], 1800)
        self.assertEqual(e["resampler_name"], "beamResampler")
        self.assertEqual(e["inloc"], "tape")
        self.assertEqual(e["outloc"],
                         {"*.art": "outstage", "*.root": "outstage"})
        self.assertNotIn("simjob_setup", e)   # exactly one Offline source
        self.assertNotIn("fcl_overrides", e)  # not in the template -> absent

    def test_fcl_overrides_copied_into_the_entry_when_given(self):
        overrides = {"#include": "epilog_1b.fcl",
                     "services.SeedService.baseSeed": 1}
        e = self.entry(fcl_overrides=overrides)
        self.assertEqual(e["fcl_overrides"], overrides)

    def test_fcl_overrides_is_a_copy_not_an_alias(self):
        # A caller mutating its own overrides dict after the call must never
        # leak into the already-built entry.
        overrides = {"a": 1}
        e = self.entry(fcl_overrides=overrides)
        overrides["a"] = 2
        overrides["b"] = 3
        self.assertEqual(e["fcl_overrides"], {"a": 1})

    def test_merge_stage_no_events(self):
        e = self.entry(desc_fmt="Run1A_MuStopsCat_{cfg}", njobs=1,
                       staged=("/pnfs/stage/t001/mustops_ce_inputs",
                               {"sim.a.art": 200, "sim.b.art": 200}))
        self.assertNotIn("events", e)
        self.assertNotIn("run", e)
        self.assertNotIn("resampler_name", e)
        self.assertEqual(e["input_data"], {"sim.a.art": 200, "sim.b.art": 200})
        self.assertEqual(e["inloc"], "dir:/pnfs/stage/t001/mustops_ce_inputs")

    def test_memory_formatted(self):
        e = self.entry(fixed={"memory_mb": 3000}, events=2500, run=1801)
        self.assertEqual(e["memory"], "3000MB")

    def test_outloc_defaults_to_the_outstage_literal_when_omitted(self):
        e = self.entry()
        self.assertEqual(e["outloc"], {"*.art": "outstage", "*.root": "outstage"})

    def test_outloc_in_the_template_wins_over_the_default(self):
        # A stage template's "outloc" must actually reach the entry, not be
        # shadowed by the hardcoded literal.
        custom = {"*.art": "tape", "*.root": "disk"}
        e = self.entry(outloc=custom)
        self.assertEqual(e["outloc"], custom)

    def test_outloc_is_a_copy_not_an_alias(self):
        custom = {"*.art": "tape"}
        e = self.entry(outloc=custom)
        custom["*.art"] = "disk"
        custom["*.root"] = "outstage"
        self.assertEqual(e["outloc"], {"*.art": "tape"})


class TestSubstitutePlaceholders(unittest.TestCase):
    """substitute_placeholders on its own (moved from
    tests/test_prodtools_exec.py in Phase C3, which reached it through the
    pipeline's prodtools_exec.load_stage_entry)."""

    MAPPING = {"cfg": "cfg007", "geom": "g.txt"}

    def test_substitutes_cfg_and_geom_recursively(self):
        e = pe.substitute_placeholders({
            "fcl": "a/b.fcl",
            "fcl_overrides": {
                "services.GeometryService.inputFile": "{geom}",
                "nested": {"list": ["prefix_{cfg}_suffix", 3]},
            },
        }, self.MAPPING, "x")
        self.assertEqual(
            e["fcl_overrides"]["services.GeometryService.inputFile"], "g.txt")
        self.assertEqual(
            e["fcl_overrides"]["nested"]["list"][0], "prefix_cfg007_suffix")
        self.assertEqual(e["fcl_overrides"]["nested"]["list"][1], 3)  # untouched

    def test_unknown_placeholder_raises_naming_the_key_path(self):
        with self.assertRaises(ValueError) as cm:
            pe.substitute_placeholders(
                {"fcl_overrides": {"a": {"b": "{typo}"}}}, self.MAPPING, "x")
        self.assertIn("typo", str(cm.exception))
        self.assertIn("x.fcl_overrides.a.b", str(cm.exception))

    def test_include_key_stays_first_through_substitution(self):
        e = pe.substitute_placeholders({
            "fcl_overrides": {
                "#include": ["a.fcl", "b.fcl"],
                "services.SeedService.baseSeed": 1,
                "services.GeometryService.inputFile": "{geom}",
            },
        }, self.MAPPING, "x")
        self.assertEqual(list(e["fcl_overrides"].keys())[0], "#include")

    def test_repeated_calls_over_one_template_do_not_alias_or_leak(self):
        template = {"fcl_overrides":
                    {"services.GeometryService.inputFile": "{geom}"}}
        e1 = pe.substitute_placeholders(template, {"cfg": "c",
                                                   "geom": "geom1.txt"}, "x")
        e1["fcl_overrides"]["injected"] = "leak"
        e2 = pe.substitute_placeholders(template, {"cfg": "c",
                                                   "geom": "geom2.txt"}, "x")
        self.assertEqual(
            e2["fcl_overrides"]["services.GeometryService.inputFile"],
            "geom2.txt")
        self.assertNotIn("injected", e2["fcl_overrides"])
        self.assertEqual(template["fcl_overrides"],
                         {"services.GeometryService.inputFile": "{geom}"})

    def test_comment_key_rides_along_unsubstituted(self):
        e = pe.substitute_placeholders({"_comment": "see the template",
                                        "fcl": "a.fcl"}, self.MAPPING, "x")
        self.assertEqual(e["_comment"], "see the template")


class TestIncludeFiles(TmpCase):
    def test_bare_names_ship_and_published_paths_do_not(self):
        got = pe.include_files(template("mubeam"), pe.TEMPLATES_ROOT)
        self.assertEqual(sorted(p.name for p in got),
                         ["mubeam_targetstop_path.fcl",
                          "sim_kept_products_extras.fcl"])
        self.assertEqual(pe.include_files(template("elebeam_flash"),
                                          pe.TEMPLATES_ROOT), [])

    def test_a_missing_include_is_refused(self):
        t = {"fcl_overrides": {"#include": ["nope.fcl"]}}
        with self.assertRaises(ValueError) as cm:
            pe.include_files(t, self.tmp)
        self.assertIn("nope.fcl", str(cm.exception))


class TestCodeTarball(TmpCase):
    def base(self, with_code=True):
        src = self.tmp / "src" / ("Code" if with_code else "Other")
        src.mkdir(parents=True)
        (src / "setup.sh").write_text("echo hi\n")
        out = self.tmp / "base.tar.bz2"
        with tarfile.open(out, "w:bz2") as tf:
            tf.add(src, arcname=src.name)
        return out

    def build(self, base, geom_text="g1"):
        geom = self.tmp / "geom.txt"
        geom.write_text(geom_text)
        extra = self.tmp / "extra.fcl"
        extra.write_text("x: 1\n")
        return pe.build_code_tarball(base, geom_path=geom,
                                     geom_name="autoresearch_c1_geom.txt",
                                     extra_files=[extra],
                                     out_dir=self.tmp / "out")

    def test_contents(self):
        path = self.build(self.base())
        with tarfile.open(path) as tf:
            names = set(tf.getnames())
            post = tf.extractfile("Code/setup_post.sh").read().decode()
        self.assertTrue({"Code/setup.sh", "Code/autoresearch_c1_geom.txt",
                         "Code/extra.fcl", "Code/setup_post.sh"} <= names)
        self.assertEqual(post, pe.SETUP_POST)

    def test_same_inputs_reuse_and_a_new_geom_does_not(self):
        base = self.base()
        a = self.build(base)
        mtime = a.stat().st_mtime_ns
        self.assertEqual(self.build(base), a)
        self.assertEqual(a.stat().st_mtime_ns, mtime)
        self.assertNotEqual(self.build(base, geom_text="g2"), a)

    def test_two_builders_at_once_get_one_valid_tarball(self):
        base = self.base()
        geom = self.tmp / "geom.txt"
        geom.write_text("g")
        got, errors = [], []

        def build():
            try:
                got.append(pe.build_code_tarball(
                    base, geom_path=geom, geom_name="g.txt", extra_files=[],
                    out_dir=self.tmp / "out"))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=build) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(got)), 1)
        with tarfile.open(got[0]) as tf:
            self.assertIn("Code/g.txt", tf.getnames())
        self.assertEqual(sorted(p.name for p in (self.tmp / "out").iterdir()),
                         [got[0].name])

    def test_a_base_without_code_or_missing_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.build(self.base(with_code=False))
        self.assertIn("Code/", str(cm.exception))
        with self.assertRaises(ValueError):
            self.build(self.tmp / "missing.tar.bz2")


class TestUnpacked(TmpCase):
    def tarball(self, setup_text="echo hi\n", with_setup=True):
        """A muse-style tarball at a fixed path: Code/setup.sh and the
        Code/backing link to a /cvmfs release. Rebuilding overwrites it."""
        src = self.tmp / "src"
        if src.exists():
            shutil.rmtree(src)
        code = src / "Code"
        code.mkdir(parents=True)
        if with_setup:
            (code / "setup.sh").write_text(setup_text)
        (code / "backing").symlink_to(
            "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/MDC2025ax")
        path = self.tmp / "Code.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            tf.add(code, arcname="Code")
        return path

    def test_unpacks_once_under_the_digest_of_its_bytes(self):
        t = self.tarball()
        cache = self.tmp / "cache"
        root = pe.unpacked(t, cache)
        self.assertEqual(root,
                         cache / hashlib.sha256(t.read_bytes()).hexdigest())
        self.assertEqual((root / "Code" / "setup.sh").read_text(), "echo hi\n")
        self.assertTrue((root / "Code" / "backing").is_symlink())
        mtime = (root / "Code" / "setup.sh").stat().st_mtime_ns
        self.assertEqual(pe.unpacked(str(t), cache), root)
        self.assertEqual((root / "Code" / "setup.sh").stat().st_mtime_ns, mtime)
        self.assertEqual([p.name for p in cache.iterdir()], [root.name])

    def test_a_tarball_rebuilt_in_place_gets_a_new_tree(self):
        cache = self.tmp / "cache"
        old = pe.unpacked(self.tarball(), cache)
        new = pe.unpacked(self.tarball(setup_text="echo rebuilt\n"), cache)
        self.assertNotEqual(new, old)
        self.assertEqual((new / "Code" / "setup.sh").read_text(),
                         "echo rebuilt\n")

    def test_two_unpackers_at_once_share_one_tree(self):
        t = self.tarball()
        cache = self.tmp / "cache"
        got, errors = [], []

        def unpack():
            try:
                got.append(pe.unpacked(t, cache))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=unpack) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(got)), 1)
        self.assertEqual([p.name for p in cache.iterdir()], [got[0].name])

    def test_a_missing_codeless_or_broken_tarball_is_refused_naming_it(self):
        cache = self.tmp / "cache"
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(self.tmp / "gone.tar.bz2", cache)
        self.assertIn("gone.tar.bz2", str(cm.exception))
        bare = self.tarball(with_setup=False)
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(bare, cache)
        self.assertIn(str(bare), str(cm.exception))
        self.assertIn("Code/setup.sh", str(cm.exception))
        junk = self.tmp / "junk.tar.bz2"
        junk.write_text("not a tarball")
        with self.assertRaises(ValueError) as cm:
            pe.unpacked(junk, cache)
        self.assertIn(str(junk), str(cm.exception))
        self.assertEqual(list(cache.iterdir()), [])


class TestLinkInputs(TmpCase):
    def sources(self, n=2):
        d = self.tmp / "up"
        d.mkdir(exist_ok=True)
        out = []
        for i in range(n):
            p = d / f"f{i}.art"
            p.write_text(str(i))
            out.append(p)
        return out

    def test_hard_links_and_a_fresh_directory(self):
        dest = self.tmp / "staged"
        dest.mkdir()
        (dest / "stale.art").write_text("old")
        src = self.sources()
        got = pe.link_inputs(src, dest, allow_copy=False)
        self.assertEqual(got, {"f0.art": 1, "f1.art": 1})
        self.assertEqual(sorted(p.name for p in dest.iterdir()),
                         ["f0.art", "f1.art"])
        self.assertEqual(os.stat(dest / "f0.art").st_ino, os.stat(src[0]).st_ino)

    def test_duplicate_basenames_are_refused(self):
        src = self.sources(1)
        other = self.tmp / "other"
        other.mkdir()
        (other / "f0.art").write_text("x")
        with self.assertRaises(ValueError):
            pe.link_inputs([src[0], other / "f0.art"], self.tmp / "s",
                           allow_copy=False)

    def test_a_cross_device_link_copies_only_when_allowed(self):
        src = self.sources(1)
        exdev = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(pe.os, "link", side_effect=exdev):
            with self.assertRaises(OSError):
                pe.link_inputs(src, self.tmp / "grid", allow_copy=False)
            pe.link_inputs(src, self.tmp / "local", allow_copy=True)
        self.assertEqual((self.tmp / "local" / "f0.art").read_text(), "0")


if __name__ == "__main__":
    unittest.main()
