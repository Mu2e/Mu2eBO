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
executors = ["grid", "local"]
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

    def test_refusals(self):
        for label, text, *needles in (
                ("unknown key", GOOD + 'color = "red"\n',
                 "unknown key", "color"),
                ("bad value type name",
                 GOOD.replace('"positive_int"', '"posint"'),
                 "fixed_keys.n", "posint"),
                ("timeouts must name every call",
                 GOOD.replace(", cancel = 30", ""), "timeouts", "cancel"),
                ("poll bounds must be ordered",
                 GOOD.replace("[0.5, 5]", "[5, 0.5]"), "poll_s"),
                ("invalid TOML names the file", "[demo\n", "invalid TOML")):
            with self.subTest(label):
                self.assertRejects(text, *needles)


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
        self.assertTrue(decl.step_kit)
        self.assertTrue(decl.check_kit)
        self.assertFalse(decl.uses_entries)


class TestConfigNameRule(unittest.TestCase):
    """The one rule for a config name (prodtools' run names carry it)."""

    def test_letters_digits_and_underscore_pass(self):
        self.assertIsNone(kit_registry.config_name_problem("foilspf_R01_07"))

    def test_other_characters_are_named(self):
        why = kit_registry.config_name_problem("cfg-1.a-")
        self.assertIn("'cfg-1.a-'", why)
        self.assertIn("'-', '.'", why)
        self.assertIn("only letters, digits and _", why)
        self.assertEqual(kit_registry.bad_run_name_characters("a-b.c-"),
                         ["-", "."])
        self.assertEqual(kit_registry.bad_run_name_characters("a_1"), [])

    def test_an_empty_name(self):
        self.assertIn("empty", kit_registry.config_name_problem(""))


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

    def test_refusals(self):
        for label, mutate, *needles in (
                ("unknown kit setting",
                 lambda d: d["kits"]["toykit"].update(color="red"),
                 "kits.toykit", "color"),
                ("missing kit setting",
                 lambda d: d["kits"].update(toykit={}),
                 "kits.toykit", "function"),
                ("fixed value type",
                 lambda d: d["evaluate"][0]["fixed"].update(delay_s="slow"),
                 "delay_s", "number"),
                ("native kit takes no entry",
                 lambda d: d["evaluate"][0].update(entry="toy"), "entry")):
            with self.subTest(label):
                doc = toy_doc()
                mutate(doc)
                self.assertRejects(doc, *needles)


TOY_ENTRY = '''
[toy]
command = ["python3", "toy.py"]
env_passthrough = []
set = {}
study_keys = {}
fixed_keys = {}
accepts_lists = false
check = false
executors = ["grid", "local"]
launch_stagger_s = 0
poll_s = [0.1, 1.0]
timeouts = { start = 1, submit = 1, status = 1, results = 1, check = 1, describe = 1, cancel = 1 }
'''

SERVER = '''
[servers.alpha]
command = ["${REPO_ROOT}/x.sh"]
env_passthrough = []
set = { A = "b" }
timeouts = { start = 5, do_thing = 7 }
'''


class TestServersAndExecutors(unittest.TestCase):
    def write(self, text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "kits.toml"
        p.write_text(text)
        return p

    def test_a_kit_declares_its_executors(self):
        cfg = kc.load_kit_configs(self.write(TOY_ENTRY))["toy"]
        self.assertEqual(cfg.executors, ("grid", "local"))

    def test_executors_are_checked(self):
        for bad in ('[]', '["cloud"]', '["grid", "grid"]', '"grid"'):
            text = TOY_ENTRY.replace('executors = ["grid", "local"]',
                                     f"executors = {bad}")
            with self.subTest(bad=bad), self.assertRaises(
                    kc.KitConfigError) as cm:
                kc.load_kit_configs(self.write(text))
            self.assertIn("executors", str(cm.exception))

    def test_servers_are_not_kits(self):
        p = self.write(TOY_ENTRY + SERVER)
        self.assertEqual(sorted(kc.load_kit_configs(p)), ["toy"])
        srv = kc.load_server_configs(p)["alpha"]
        self.assertEqual((srv.timeouts["start"], srv.timeouts["do_thing"]),
                         (5.0, 7.0))
        self.assertEqual(srv.resolve_env({})["A"], "b")

    def test_a_server_needs_every_key_and_a_start_timeout(self):
        for old, new, needle in (
                ('set = { A = "b" }\n', "", "set"),
                ("start = 5, ", "", "start"),
                ('timeouts = { start = 5, do_thing = 7 }',
                 'timeouts = { start = 5, do_thing = 0 }', "do_thing"),
                ("[servers.alpha]", "[servers.Alpha]", "lower-case")):
            with self.subTest(needle=needle), self.assertRaises(
                    kc.KitConfigError) as cm:
                kc.load_server_configs(
                    self.write(SERVER.replace(old, new)))
            self.assertIn(needle, str(cm.exception))

    def test_the_repo_declares_both_prodtools_servers(self):
        servers = kc.load_server_configs()
        self.assertEqual(sorted(servers),
                         ["anakit", "beamkit", "prodtools_read",
                          "prodtools_write"])
        self.assertIn("run_beamline", servers["beamkit"].timeouts)
        # beamkit submits through prodtools: the write server's credentials
        # and jobsub site settings, plus jobsub's tracing endpoint -- without
        # it jobsub_q prints "Continuing without tracing..." into its table
        # and prodtools' tick refuses the queue count, submitting nothing
        # (ptg4bl grid acceptance, 2026-10-02).
        self.assertTrue(set(servers["prodtools_write"].env_passthrough)
                        <= set(servers["beamkit"].env_passthrough))
        self.assertIn("OTEL_EXPORTER_JAEGER_ENDPOINT",
                      servers["beamkit"].env_passthrough)
        self.assertIn("submit_once", servers["prodtools_write"].timeouts)
        self.assertIn("run_status", servers["prodtools_read"].timeouts)
        # The bearer token is found at $XDG_RUNTIME_DIR/bt_u<uid>; without
        # the variable the servers would read a stale /tmp/bt_u<uid>.
        creds = ("KRB5CCNAME", "XDG_RUNTIME_DIR")
        self.assertEqual(servers["prodtools_read"].env_passthrough, creds)
        # jobsub_submit publishes the code tarball only with the site's
        # JOBSUB_* settings (/etc/profile.d/jobsub_lite.sh).
        self.assertEqual(servers["prodtools_write"].env_passthrough,
                         creds + ("JOBSUB_DROPBOX_SERVER_LIST",
                                  "JOBSUB_OUTPUT_URL", "JOBSUB_FETCHLOG_URL",
                                  "JOBSUB_AUTH_METHODS", "JOBSUB_POOL_MAP"))

    def test_the_repo_declares_the_anakit_server(self):
        anakit = kc.load_server_configs()["anakit"]
        self.assertEqual(anakit.command[1:6],
                         ("-P", "-m", "analysis_mcp_server", "--transport",
                          "stdio"))
        self.assertEqual(anakit.set_env["PYTHONPATH"], "${AUTORESEARCH_ANAKIT}")
        # M. MacKenzie's AGENTS.md: one thread per analysis job.
        self.assertEqual(anakit.set_env["OPENBLAS_NUM_THREADS"], "1")
        self.assertEqual(anakit.set_env["OMP_NUM_THREADS"], "1")
        self.assertEqual(anakit.timeouts, {"start": 120.0,
                                           "list_analyses": 120.0,
                                           "run_analysis": 3600.0})

    def test_a_kit_client_starts_from_a_server_config(self):
        import kits
        with tempfile.TemporaryDirectory() as td:
            srv = kc.ServerConfig(
                name="toysrv",
                command=(sys.executable, str(ROOT / "tests" / "toykit.py")),
                env_passthrough=(), set_env={"TOYKIT_STATE_DIR": td},
                timeouts={"start": 60.0, "describe": 30.0})
            client = kits.KitClient(srv, campaign="c", trace_dir=Path(td))
            try:
                client.start()
                self.assertIn("describe", client.tools)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
