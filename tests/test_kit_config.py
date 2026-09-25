import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import kit_config as kc  # noqa: E402
import kit_registry  # noqa: E402
import paths  # noqa: E402
import study as st  # noqa: E402

sys.path.insert(0, str(ROOT))
from tests.engine_fixtures import toy_doc, write_study  # noqa: E402

GOOD = """
[demo]
command = ["${PYTHON}", "${REPO_ROOT}/x.py", "--data", "${DATA_ROOT}/d"]
env_passthrough = ["DEMO_TOKEN"]
set = { DEMO_DIR = "${DATA_ROOT}/demo" }
study_keys = { mode = "string" }
fixed_keys = { n = "positive_int" }
accepts_lists = false
check = true
launch_stagger_s = 0
poll_s = [0.5, 5]
timeouts = { start = 60, submit = 30, status = 30, results = 30, check = 30, describe = 30, cancel = 30 }
"""


class _Toml(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "kits.toml"
            path.write_text(text)
            return kc.load_kit_configs(path)

    def assertRejects(self, text, *needles):
        with self.assertRaises(kc.KitConfigError) as cm:
            self.load(text)
        for n in needles:
            self.assertIn(n, str(cm.exception))


class TestLoad(_Toml):
    def test_good_entry(self):
        cfg = self.load(GOOD)["demo"]
        self.assertEqual(cfg.poll_s, (0.5, 5.0))
        self.assertTrue(cfg.check)
        self.assertEqual(cfg.timeouts["submit"], 30.0)
        self.assertEqual(cfg.fixed_keys, {"n": "positive_int"})

    def test_every_key_is_required(self):
        for key in kc.KEYS:
            text = "\n".join(line for line in GOOD.splitlines()
                             if not line.startswith(key + " "))
            with self.subTest(key=key):
                self.assertRejects(text, "[demo]", key)

    def test_unknown_key(self):
        self.assertRejects(GOOD + 'color = "red"\n', "unknown key", "color")

    def test_bad_value_type_name(self):
        self.assertRejects(GOOD.replace('"positive_int"', '"posint"'),
                           "fixed_keys.n", "posint")

    def test_timeouts_must_name_every_call(self):
        self.assertRejects(GOOD.replace(", cancel = 30", ""),
                           "timeouts", "cancel")

    def test_poll_bounds_must_be_ordered(self):
        self.assertRejects(GOOD.replace("[0.5, 5]", "[5, 0.5]"), "poll_s")

    def test_invalid_toml_names_the_file(self):
        self.assertRejects("[demo\n", "invalid TOML")


class TestResolve(_Toml):
    def test_tokens(self):
        cmd = self.load(GOOD)["demo"].resolve_command()
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], f"{paths.REPO_ROOT}/x.py")
        self.assertEqual(cmd[3], f"{paths.DATA_ROOT}/d")

    def test_env_is_base_plus_passthrough_plus_set(self):
        cfg = self.load(GOOD)["demo"]
        with mock.patch.dict(os.environ, {"DEMO_TOKEN": "t"}):
            env = cfg.resolve_env({"HOME": "/h"})
        self.assertEqual(env, {"HOME": "/h", "DEMO_TOKEN": "t",
                               "DEMO_DIR": f"{paths.DATA_ROOT}/demo"})

    def test_unset_passthrough_names_kit_and_variable(self):
        cfg = self.load(GOOD)["demo"]
        with mock.patch.dict(os.environ):
            os.environ.pop("DEMO_TOKEN", None)
            with self.assertRaises(kc.KitConfigError) as cm:
                cfg.resolve_env({})
        self.assertIn("'demo'", str(cm.exception))
        self.assertIn("DEMO_TOKEN", str(cm.exception))

    def test_unset_token_in_command(self):
        cfg = self.load(GOOD.replace("${PYTHON}", "${NO_SUCH_VAR_XYZ}"))["demo"]
        with self.assertRaises(kc.KitConfigError) as cm:
            cfg.resolve_command()
        self.assertIn("NO_SUCH_VAR_XYZ", str(cm.exception))


class TestRepoRegistry(unittest.TestCase):
    def test_repo_kits_toml_loads(self):
        self.assertIn("toykit", kc.load_kit_configs())

    def test_value_types_match_the_validators(self):
        self.assertEqual(set(kc.VALUE_TYPES), set(kit_registry.VALIDATORS))

    def test_native_kits_are_engine_kits(self):
        decl = kit_registry.KITS["toykit"]
        self.assertTrue(decl.engine)
        self.assertTrue(decl.step_kit)
        self.assertTrue(decl.check_kit)
        self.assertFalse(decl.uses_entries)

    def test_pipeline_kits_are_not_engine_kits(self):
        for name in ("prodtools", "offline_preflight", "ce_sensitivity",
                     "flash_edep_per_pot"):
            with self.subTest(kit=name):
                self.assertFalse(kit_registry.KITS[name].engine)


class TestNativeKitInStudies(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)

    def load(self, doc):
        return st.load_study_file(write_study(doc, self.dir))

    def assertRejects(self, doc, *needles):
        with self.assertRaises(ValueError) as cm:
            self.load(doc)
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_a_toykit_study_loads(self):
        s = self.load(toy_doc())
        self.assertEqual(s.steps[0].kit, "toykit")
        self.assertEqual(kit_registry.kits_of(s), {"toykit"})

    def test_unknown_kit_setting(self):
        doc = toy_doc()
        doc["kits"]["toykit"]["color"] = "red"
        self.assertRejects(doc, "kits.toykit", "color")

    def test_missing_kit_setting(self):
        doc = toy_doc()
        doc["kits"]["toykit"] = {}
        self.assertRejects(doc, "kits.toykit", "function")

    def test_fixed_value_type(self):
        doc = toy_doc()
        doc["evaluate"][0]["fixed"]["delay_s"] = "slow"
        self.assertRejects(doc, "delay_s", "number")

    def test_native_kit_takes_no_entry(self):
        doc = toy_doc()
        doc["evaluate"][0]["entry"] = "toy"
        self.assertRejects(doc, "entry")


if __name__ == "__main__":
    unittest.main()
