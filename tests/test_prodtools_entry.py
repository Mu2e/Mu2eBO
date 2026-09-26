import errno
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
from adapters import prodtools_entry as pe  # noqa: E402

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
                    code_tarball="CODE",
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
    def test_geom_without_a_geom_file_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(template("mubeam"), config="c1", fixed={},
                              code_tarball="CODE")
        self.assertIn("{geom}", str(cm.exception))

    def test_a_template_without_dsconf_fmt_is_refused(self):
        t = template("mubeam")
        del t["dsconf_fmt"]
        with self.assertRaises(ValueError) as cm:
            pe.entry_for_step(t, config="c1", fixed={}, code_tarball="CODE",
                              geom_name="g.txt")
        self.assertIn("dsconf_fmt", str(cm.exception))

    def test_template_defaults_fill_what_fixed_omits(self):
        entry, facts = pe.entry_for_step(template("elebeam_flash"),
                                         config="c1", fixed={},
                                         code_tarball="CODE",
                                         geom_name="g.txt")
        self.assertEqual((entry["njobs"], entry["events"], entry["memory"]),
                         (100, 2500, "3000MB"))
        self.assertEqual(facts["events_per_job"], 2500)


class _Tmp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)


class TestIncludeFiles(_Tmp):
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


class TestCodeTarball(_Tmp):
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


class TestLinkInputs(_Tmp):
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
