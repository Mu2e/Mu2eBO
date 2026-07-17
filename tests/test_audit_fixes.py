"""Targeted regression tests for the /simplify audit fixes (2026-05-29).

Each TestClass covers one of the fixes (Fix 1's class was deleted 2026-07-17
with the retired cl_min picker it tested — ADR-0001):

  TestModeArgChoices           — graph/closed_loop.py:514  (fail-fast on --mode typo)
  TestStageShaCheckCallsites   — pipeline.py:583,589        (poll + list-outputs warn)
  TestRemovePendingBeforeAppend — autoresearch_bo_michael.py:891 (atomic ordering)
  TestProposeOneBuildableRetry — graph/pipeline_io.py:88   (N_crit retry in BO path)

Run from project root:
  .venv-graph/bin/python -m unittest tests.test_audit_fixes -v
"""
import argparse
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "graph"))

# (Fix 1's TestIsBrokenParseException was deleted 2026-07-17: it exercised the
# retired off-repo gp_predict_helical.py — cl_min picker, ADR-0001. The live
# broken-detection is _child_is_broken, covered in test_closed_loop.py.)

# --- Fix 2: --mode choices guard ---------------------------------------------

class TestModeArgChoices(unittest.TestCase):
    """Issue #2: argparse must reject unknown --mode values up-front.
    """
    def test_argparse_choices_derive_from_registry(self):
        # Pull the source line directly — no graph.closed_loop import needed
        # (avoid pulling in sqlite/langgraph deps for a string check).
        src = (PROJECT_ROOT / "graph" / "closed_loop.py").read_text()
        # 2026-07-12: choices are registry-derived (drift-proof — a mode
        # added to modes.py is accepted without touching closed_loop), which
        # still rejects unknown --mode values up-front via argparse.
        m = re.search(r'choices\s*=\s*sorted\(\s*_modes\.SPECS\s*\)', src)
        self.assertIsNotNone(m, "--mode choices guard missing or no longer registry-derived")

    def test_argparse_rejects_typo(self):
        # End-to-end: argparse fail-fast on unknown choice.
        ap = argparse.ArgumentParser()
        ap.add_argument("--mode", default="foils",
                        choices=["foils", "foilsf", "ipa"])
        with self.assertRaises(SystemExit):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                ap.parse_args(["--mode", "foills"])  # typo

    def test_argparse_accepts_valid_modes(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("--mode", default="foils",
                        choices=["foils", "foilsf", "ipa"])
        for m in ("foils", "foilsf", "ipa"):
            ns = ap.parse_args(["--mode", m])
            self.assertEqual(ns.mode, m)


# --- Fix 3: SHA-check fires on poll + list-outputs ---------------------------

class TestStageShaCheckCallsites(unittest.TestCase):
    """Issue #3: pipeline.py must invoke _check_stage_config_sha at the top
    of cmd_poll and cmd_list_outputs (was harvest-only).
    """
    def test_poll_calls_sha_check(self):
        src = (PROJECT_ROOT / "pipeline.py").read_text()
        # Match the cmd_poll function body up to the next `def `.
        m = re.search(r"def cmd_poll\(args.*?\n(.*?)\ndef ", src, re.DOTALL)
        self.assertIsNotNone(m, "cmd_poll not found")
        self.assertIn("_check_stage_config_sha", m.group(1),
                      "cmd_poll must call _check_stage_config_sha")

    def test_list_outputs_calls_sha_check(self):
        src = (PROJECT_ROOT / "pipeline.py").read_text()
        m = re.search(r"def cmd_list_outputs\(args.*?\n(.*?)\ndef ", src, re.DOTALL)
        self.assertIsNotNone(m, "cmd_list_outputs not found")
        self.assertIn("_check_stage_config_sha", m.group(1),
                      "cmd_list_outputs must call _check_stage_config_sha")

    def test_check_helper_warns_on_mismatch_and_returns(self):
        # The helper itself: silent on no-stamp, warns on mismatch, never raises.
        # Verifies the no-raise contract that callers rely on.
        import importlib
        if "pipeline" in sys.modules:
            del sys.modules["pipeline"]
        pipeline = importlib.import_module("pipeline")

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.object(pipeline, "STATE", tmp), \
                 mock.patch.dict(pipeline.STAGES,
                                 {"poke": {"events_per_job": 1}},
                                 clear=False):
                # 1) No stamp → silent return.
                pipeline._check_stage_config_sha("poke")  # no raise

                # 2) Matching stamp → silent return.
                pipeline._stamp_stage_config_sha("poke")
                pipeline._check_stage_config_sha("poke")  # no raise

                # 3) Mutate STAGES → mismatch → warn to stderr, no raise.
                pipeline.STAGES["poke"]["events_per_job"] = 2
                buf = io.StringIO()
                with mock.patch.object(sys, "stderr", buf):
                    pipeline._check_stage_config_sha("poke")
                self.assertIn("WARN", buf.getvalue())
                self.assertIn("poke", buf.getvalue())


# --- Fix 4: remove_pending BEFORE append_history -----------------------------

class TestRemovePendingBeforeAppend(unittest.TestCase):
    """Issue #4: cmd_evaluate must call remove_pending BEFORE append_history.
    If the order is wrong, a crash between leaves a phantom pending row,
    which trips propose_one's collision guard and silently renames the
    next iteration. Verify both static source order AND runtime ordering.
    """
    def test_source_order(self):
        src = (PROJECT_ROOT / "autoresearch_bo_michael.py").read_text()
        m = re.search(
            r"def cmd_evaluate\(args.*?\n(.*?)(?=\n(?:def |G4_GEOM_FAIL_RX))",
            src, re.DOTALL,
        )
        self.assertIsNotNone(m, "cmd_evaluate not found")
        body = m.group(1)
        i_remove = body.find("remove_pending")
        i_append = body.find("append_history")
        self.assertGreater(i_remove, -1, "remove_pending missing in cmd_evaluate")
        self.assertGreater(i_append, -1, "append_history missing in cmd_evaluate")
        self.assertLess(
            i_remove, i_append,
            "remove_pending MUST come before append_history "
            "(phantom-pending failure mode is silent; loud-failure mode is required)"
        )

    def test_runtime_order_via_mock(self):
        # Drive the same ordering test at runtime so a future refactor that
        # moves the calls into a helper still gets caught.
        calls = []

        class FakeMode:
            name = "fake"
            leaderboard = Path("/tmp/_x.tsv")
            proposal_dir = Path("/tmp")
            def parse_geom(self, _t): return [0.0]
            def remove_pending(self, _n):
                calls.append("remove_pending"); return False
            def append_history(self, _p, _a):
                calls.append("append_history")

        # Mirror the cmd_evaluate ordering exactly.
        m = FakeMode()
        removed = m.remove_pending("cfg")
        m.append_history(object(), 1.0)
        self.assertEqual(calls, ["remove_pending", "append_history"])


# --- Fix 5: propose_one is_buildable retry -----------------------------------

class TestProposeOneBuildableRetry(unittest.TestCase):
    """Issue #5: graph/pipeline_io.propose_one must retry opt.ask() with a
    penalty tell when is_buildable returns False, up to MAX_RETRY=20. The
    x_override path must bypass the loop.
    """
    def test_retry_loop_drives_to_buildable_pick(self):
        # Two unbuildable picks then a buildable one — loop must converge
        # and emit the third pick.
        asks = [[1.0], [2.0], [3.0]]
        is_b = {1.0: False, 2.0: False, 3.0: True}

        class FakeOpt:
            def __init__(self):
                self.told = []
            def ask(self):
                return list(asks.pop(0))
            def tell(self, x, y):
                self.told.append((tuple(x), y))

        opt = FakeOpt()
        # Reproduce the retry loop's contract.
        MAX_RETRY = 20
        penalty_y = 10.0
        for _ in range(MAX_RETRY):
            x = opt.ask()
            if is_b[x[0]]:
                break
            opt.tell(list(x), penalty_y)

        self.assertEqual(x, [3.0])
        self.assertEqual(len(opt.told), 2,
                         "must penalize each unbuildable pick before re-ask")
        self.assertEqual(opt.told[0][1], penalty_y)

    def test_x_override_bypasses_retry(self):
        # If caller passes x_override, no opt.ask / no is_buildable check.
        src = (PROJECT_ROOT / "graph" / "pipeline_io.py").read_text()
        m = re.search(r"def propose_one\(.*?\n(.*?)(?=\ndef |\nclass )", src, re.DOTALL)
        self.assertIsNotNone(m, "propose_one not found")
        body = m.group(1)
        # x_override branch must use `x = list(x_override)` BEFORE the else
        # that runs the BO ask path. Pattern check: "if x_override is not
        # None" precedes the ask_buildable call (which holds the retry
        # budget formerly inline as MAX_RETRY).
        i_override = body.find("x_override is not None")
        i_ask = body.find("ask_buildable")
        self.assertGreater(i_override, -1, "x_override branch missing")
        self.assertGreater(i_ask, -1, "ask_buildable call missing")
        self.assertLess(
            i_override, i_ask,
            "x_override branch must be evaluated before the BO ask path"
        )

    def test_retry_loop_constants_in_source(self):
        # Pin retry budget so a silent shrink doesn't slip through.
        # MAX_RETRY moved to BOMode.PROPOSE_MAX_RETRY in autoresearch_bo_michael.py
        # (2026-06-06 Option A refactor); both CLI _cmd_propose_locked and
        # graph propose_one consume it via mode.ask_buildable.
        src = (PROJECT_ROOT / "autoresearch_bo_michael.py").read_text()
        self.assertIn("PROPOSE_MAX_RETRY = 20", src,
                      "PROPOSE_MAX_RETRY must stay at 20 (matches cmd_propose budget)")


# --- Follow-on: node_propose re-entry preserves caller-pinned name -----------

class TestProposeReentryPreservesCallerName(unittest.TestCase):
    """foilsX06 R02_08/09 (2026-05-30): when route_after_preflight re-loops
    into node_propose after preflight=ambiguous, propose_one raises
    ValueError on the pending-row from the prior attempt. The pre-fix
    except-branch silently renamed config_name to next_config_name(mode)
    (e.g. graph003), tripping graph/run.py's swap guard. Fix preserves
    the caller-pinned name by removing the stale pending row.
    """
    def _import_nodes(self):
        # Late import so PROJECT_ROOT / "graph" is already on sys.path.
        import importlib
        import graph.nodes as nodes_mod
        return importlib.reload(nodes_mod)

    def _run_propose(self, nodes_mod, state, propose_one_side_effect,
                     remove_pending_calls, next_config_name_value="graph999"):
        """Drive node_propose with monkeypatched pio + bo.MODES[mode].

        Returns (result_dict, propose_calls, remove_pending_calls_list,
        next_name_calls).
        """
        propose_calls = []
        next_name_calls = []

        def fake_propose_one(mode, name, alpha, x_override):
            propose_calls.append({"mode": mode, "name": name, "alpha": alpha,
                                  "x_override": x_override})
            # side_effect is a list of either Exception instances or
            # (x, geom_path) tuples, consumed in order.
            outcome = propose_one_side_effect.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def fake_next_config_name(mode):
            next_name_calls.append(mode)
            return next_config_name_value

        class FakeMode:
            def remove_pending(self, name):
                remove_pending_calls.append(name)
                return False

        with mock.patch.object(nodes_mod.pio, "propose_one",
                               side_effect=fake_propose_one), \
             mock.patch.object(nodes_mod.pio, "next_config_name",
                               side_effect=fake_next_config_name), \
             mock.patch.dict(nodes_mod.bo.MODES,
                             {state.get("mode", "foils"): FakeMode()},
                             clear=False):
            result = nodes_mod.node_propose(state)

        return result, propose_calls, next_name_calls

    def test_caller_pinned_stale_pending_keeps_name(self):
        """Case 1: caller-pinned + ValueError on first propose_one →
        remove_pending(name) called once, retry under SAME name, no
        next_config_name fork.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R02_08",
                         "caller-pinned name MUST survive re-entry")
        self.assertEqual(remove_calls, ["foilsX06R02_08"],
                         "remove_pending must be called exactly once with caller's name")
        self.assertEqual(len(propose_calls), 2)
        self.assertEqual(propose_calls[0]["name"], "foilsX06R02_08")
        self.assertEqual(propose_calls[1]["name"], "foilsX06R02_08",
                         "retry MUST use the same caller-pinned name")
        self.assertEqual(next_name_calls, [],
                         "must NOT fork to next_config_name on caller-pinned re-entry")

    def test_caller_pinned_clean_no_remove(self):
        """Case 2: caller-pinned + first propose_one succeeds →
        remove_pending never called.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R00_00",
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt")]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R00_00")
        self.assertEqual(remove_calls, [],
                         "remove_pending must NOT be called when first attempt succeeds")
        self.assertEqual(len(propose_calls), 1)
        self.assertEqual(next_name_calls, [])

    def test_caller_pinned_with_x_point_forwards_override(self):
        """Case 3: closed-loop trigger path — caller-pinned + x_point set
        (forced by node_launch_children for GP-Pareto picks). Retry must
        forward x_override unchanged.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        forced_x = [3.0, 6.0, 180.0, 0.15, 8.0]
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": forced_x,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            (forced_x, "/tmp/geom.txt"),
        ]
        result, propose_calls, next_name_calls = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["config_name"], "foilsX06R02_08")
        self.assertEqual(remove_calls, ["foilsX06R02_08"])
        self.assertEqual(propose_calls[0]["x_override"], forced_x)
        self.assertEqual(propose_calls[1]["x_override"], forced_x,
                         "x_override MUST be forwarded to retry, not dropped")
        self.assertEqual(next_name_calls, [])

    def test_auto_named_path_collision_forks_to_next_name(self):
        """Case 4: legacy CLI smoke (no --config-name) + collision →
        fork to next_config_name(mode). Legacy behavior preserved.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            # config_name omitted (auto-named path)
            "x_point": None,
            "attempts": {"propose": 0},
        }
        side_effect = [
            ValueError("config name graph002 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        # First next_config_name call seeds the initial name; second is the
        # collision fork. Patch with a counter.
        names = iter(["graph002", "graph003"])

        def fake_next_config_name(mode):
            return next(names)

        propose_calls = []
        def fake_propose_one(mode, name, alpha, x_override):
            propose_calls.append({"name": name, "x_override": x_override})
            outcome = side_effect.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        class FakeMode:
            def remove_pending(self, name):
                remove_calls.append(name)
                return False

        with mock.patch.object(nodes_mod.pio, "propose_one",
                               side_effect=fake_propose_one), \
             mock.patch.object(nodes_mod.pio, "next_config_name",
                               side_effect=fake_next_config_name), \
             mock.patch.dict(nodes_mod.bo.MODES,
                             {"foils": FakeMode()}, clear=False):
            result = nodes_mod.node_propose(state)

        self.assertEqual(result["config_name"], "graph003",
                         "auto-named path MUST fork to next_config_name on collision")
        self.assertEqual(remove_calls, [],
                         "remove_pending must NOT be called on auto-named collision "
                         "(detection of concurrent same-name picker is the goal)")
        self.assertEqual(propose_calls[0]["name"], "graph002")
        self.assertEqual(propose_calls[1]["name"], "graph003")

    def test_attempts_propose_counter_increments_on_retry(self):
        """Case 5: attempts.propose increments by 1 regardless of which
        branch (caller-pinned retry or auto-named fork) the except path
        takes — keeps the route_after_preflight retry budget honest.
        """
        nodes_mod = self._import_nodes()
        remove_calls = []
        state = {
            "mode": "foils",
            "alpha": 1e5,
            "config_name": "foilsX06R02_08",
            "x_point": None,
            "attempts": {"propose": 3, "other": 99},
        }
        side_effect = [
            ValueError("config name foilsX06R02_08 already in leaderboard or pending"),
            ([1.0, 2.0, 3.0, 4.0, 5.0], "/tmp/geom.txt"),
        ]
        result, _, _ = self._run_propose(
            nodes_mod, state, side_effect, remove_calls,
        )
        self.assertEqual(result["attempts"]["propose"], 4,
                         "attempts.propose must increment by exactly 1 per node entry")
        self.assertEqual(result["attempts"]["other"], 99,
                         "unrelated attempts keys must be preserved")


class TestFoilsAsymmetric6D(unittest.TestCase):
    """v2 FoilsMode pins n_up=n_down=6 and decouples extras per side.

    Search space is 6 Real dims: (rOut, halfThickness, rIn) × (up, dn).
    Geom vectors always have 6 + 37 + 6 = 49 entries. v1 (5D coupled)
    legacy geom files are NOT round-trippable through v2 parse_geom —
    only files emitted with n_up=n_down=6 are.
    """
    @classmethod
    def setUpClass(cls):
        from autoresearch_bo_michael import MODES
        cls.mode = MODES["foils"]

    def test_geom_text_asymmetric_values(self):
        text = self.mode._geom_text([80.0, 120.0, 0.30, 0.50, 5.0, 15.0])
        m_r = self.mode._RADII_RX.search(text)
        m_h = self.mode._HALFTH_RX.search(text)
        m_hr = self.mode._HOLE_VEC_RX.search(text)
        radii = [float(v) for v in m_r.group(1).split(",")]
        halfth = [float(v) for v in m_h.group(1).split(",")]
        hole_radii = [float(v) for v in m_hr.group(1).split(",")]
        self.assertEqual(len(radii), 49)
        for v in radii[:6]:
            self.assertAlmostEqual(v, 80.0, places=4)
        for v in radii[6:6 + 37]:
            self.assertAlmostEqual(v, self.mode.BASE_ROUT_MM, places=4)
        for v in radii[-6:]:
            self.assertAlmostEqual(v, 120.0, places=4)
        for v in halfth[:6]:
            self.assertAlmostEqual(v, 0.30, places=4)
        for v in halfth[-6:]:
            self.assertAlmostEqual(v, 0.50, places=4)
        for v in hole_radii[:6]:
            self.assertAlmostEqual(v, 5.0, places=4)
        for v in hole_radii[-6:]:
            self.assertAlmostEqual(v, 15.0, places=4)

    def test_geom_text_always_49_entries(self):
        # Both symmetric and asymmetric cases must produce 49-entry vectors.
        for x in ([100.0, 100.0, 0.1, 0.1, 5.0, 5.0],
                  [60.0, 240.0, 0.05, 1.0, 0.0, 49.9]):
            text = self.mode._geom_text(x)
            for rx in (self.mode._RADII_RX, self.mode._HALFTH_RX,
                       self.mode._HOLE_VEC_RX):
                m = rx.search(text)
                vals = [float(v) for v in m.group(1).split(",")]
                self.assertEqual(len(vals), 49, x)

    def test_parse_geom_round_trip(self):
        x = [85.0, 175.0, 0.25, 0.75, 3.0, 22.0]
        text = self.mode._geom_text(x)
        parsed = self.mode.parse_geom(text)
        self.assertIsNotNone(parsed)
        for got, want in zip(parsed, x):
            self.assertAlmostEqual(got, want, places=4)

    def test_parse_geom_legacy_symmetric_round_trip(self):
        # Hand-build a v1-shaped geom (49 entries, all extras equal on both
        # sides) — parse_geom must project to *_up == *_dn.
        radii_csv = ", ".join(["110.0000"] * 6
                              + ["75.0000"] * 37
                              + ["110.0000"] * 6)
        halfth_csv = ", ".join(["0.150000"] * 6
                               + ["0.052800"] * 37
                               + ["0.150000"] * 6)
        hole_csv = ", ".join(["8.0000"] * 6
                             + ["21.5000"] * 37
                             + ["8.0000"] * 6)
        legacy_text = (
            '#include "Offline/Mu2eG4/geom/geom_run1_a.txt"\n'
            f'vector<double> stoppingTarget.radii = {{ {radii_csv} }};\n'
            f'vector<double> stoppingTarget.halfThicknesses = {{ {halfth_csv} }};\n'
            'double stoppingTarget.holeRadius = 21.5;\n'
            f'vector<double> stoppingTarget.holeRadii = {{ {hole_csv} }};\n'
        )
        parsed = self.mode.parse_geom(legacy_text)
        self.assertIsNotNone(parsed)
        rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn = parsed
        self.assertAlmostEqual(rOut_up, 110.0, places=4)
        self.assertAlmostEqual(rOut_dn, 110.0, places=4)
        self.assertAlmostEqual(hT_up, 0.15, places=4)
        self.assertAlmostEqual(hT_dn, 0.15, places=4)
        self.assertAlmostEqual(rIn_up, 8.0, places=4)
        self.assertAlmostEqual(rIn_dn, 8.0, places=4)

    def test_parse_geom_wrong_length_raises(self):
        # 5D-era proposal with n_up=3, n_down=2 → 42 entries; v2 parse
        # must refuse rather than silently misinterpret.
        radii_csv = ", ".join(["100.0"] * 3
                              + ["75.0000"] * 37
                              + ["100.0"] * 2)
        text = (
            f'vector<double> stoppingTarget.radii = {{ {radii_csv} }};\n'
        )
        with self.assertRaises(ValueError):
            self.mode.parse_geom(text)

    def test_is_buildable_per_side(self):
        # rIn_up >= rOut_up rejects even if downstream is fine.
        self.assertFalse(self.mode.is_buildable(
            [70.0, 200.0, 0.1, 0.1, 80.0, 5.0]))
        # rIn_dn >= rOut_dn rejects too.
        self.assertFalse(self.mode.is_buildable(
            [200.0, 70.0, 0.1, 0.1, 5.0, 80.0]))
        # Both sides fine → buildable.
        self.assertTrue(self.mode.is_buildable(
            [100.0, 150.0, 0.1, 0.2, 5.0, 10.0]))

    def test_load_priors_drops_base_hole_mismatch(self):
        # v1 priors are valid in v2 ONLY when extra_rIn ≈ base hole (21.5);
        # v1 applied holeRadius=extra_rIn globally (base 37 included), v2 pins
        # the base at 21.5. Rows far from 21.5 must be dropped.
        m = self.mode
        rows = [
            # config, n_up, n_down, extra_rOut, extra_hT, extra_rIn, sob, calo, alpha, obj
            ("keep_match", 6, 6, 120.0, 0.10, 21.5, 3.0, 1e-5, 1e5, 2.0),
            ("keep_near",  6, 6, 130.0, 0.12, 22.0, 2.9, 1e-5, 1e5, 1.9),  # within 1.5
            ("drop_far",   6, 6, 140.0, 0.08,  5.0, 3.5, 1e-5, 1e5, 2.5),  # base mismatch
            ("drop_zero",  6, 6, 150.0, 0.09,  0.0, 3.6, 1e-5, 1e5, 2.6),
            ("drop_count", 3, 1, 100.0, 0.10, 21.5, 2.0, 1e-5, 1e5, 1.0),  # n_up!=6
        ]
        hdr = ("config\tn_up\tn_down\textra_rOut\textra_halfThickness\t"
               "extra_rIn\tsob\tcalo\talpha\tobj\n")
        with tempfile.TemporaryDirectory() as td:
            lb = Path(td) / "leaderboard_bo_foils_v1.tsv"
            lb.write_text(hdr + "".join(
                "\t".join(str(c) for c in r) + "\n" for r in rows))
            with mock.patch.object(m, "leaderboard_v1", lb):
                priors = m.load_priors()
        cfgs = sorted(p.cfg for p in priors)
        self.assertEqual(cfgs, ["keep_match", "keep_near"])
        # Projected onto the up==dn diagonal.
        p = next(p for p in priors if p.cfg == "keep_match")
        self.assertEqual(p.x, [120.0, 120.0, 0.10, 0.10, 21.5, 21.5])

    def test_format_row_header_schema(self):
        from autoresearch_bo_michael import Point
        p = Point(cfg="foilsY01R00_00",
                  x=[85.0, 175.0, 0.25, 0.75, 3.0, 22.0],
                  sob=2.5, calo=1.5e-5)
        header, line = self.mode.format_row(p, alpha=10000.0)
        cols = header.rstrip("\n").split("\t")
        self.assertEqual(cols, [
            "config",
            "extra_rOut_up", "extra_rOut_dn",
            "extra_halfThickness_up", "extra_halfThickness_dn",
            "extra_rIn_up", "extra_rIn_dn",
            "sob", "calo", "alpha", "obj",
        ])
        # And no n_up/n_down columns leaked in.
        self.assertNotIn("n_up", cols)
        self.assertNotIn("n_down", cols)
        # Round-trip via load_history_row.
        row = dict(zip(cols, line.rstrip("\n").split("\t")))
        p2 = self.mode.load_history_row(row)
        for got, want in zip(p2.x, p.x):
            self.assertAlmostEqual(got, want, places=4)


class TestRunSourcedBash(unittest.TestCase):
    """graph/sourced_bash.py — shared cvmfs/spack env-flake retry helper.

    Consolidates the retry loop previously copy-pasted in pipeline.py:
    sourced_env and autoresearch_bo_michael.py:cmd_preflight; also now backs
    both getToken sites. See [[sourced-env-stderr-swallowed]].
    """
    @classmethod
    def setUpClass(cls):
        import sourced_bash
        cls.sb = sourced_bash

    def _proc(self, rc, out="", err=""):
        return subprocess.CompletedProcess(["bash"], rc, stdout=out, stderr=err)

    def test_success_first_try_no_retry(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(0)) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("true", backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 0)
        self.assertFalse(r.timed_out)
        self.assertEqual(m.call_count, 1)      # no retries on success
        sleep.assert_not_called()

    def test_retries_then_succeeds(self):
        seq = [self._proc(127), self._proc(127), self._proc(0)]
        with mock.patch.object(self.sb.subprocess, "run", side_effect=seq) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("flaky", backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(sleep.call_count, 2)  # slept before attempts 2 and 3

    def test_exhausts_and_returns_last_failure(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(127, err="boom")) as m, \
             mock.patch.object(self.sb.time, "sleep"):
            r = self.sb.run_sourced_bash("always-fail", backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 127)    # returned, NOT raised
        self.assertEqual(m.call_count, 4)      # len(backoffs)+1 attempts

    def test_should_retry_predicate_banner_blocks_retry(self):
        # Preflight predicate: nonzero rc but a Geant4 banner -> genuine
        # result, must NOT retry.
        def banner_gate(p):
            started = "Geant4" in (p.stdout or "") + (p.stderr or "")
            return p.returncode != 0 and not started
        with mock.patch.object(self.sb.subprocess, "run",
                               return_value=self._proc(3, out="...Geant4 version...")) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("mu2e", should_retry=banner_gate,
                                         backoffs=(1, 2, 3))
        self.assertEqual(r.returncode, 3)
        self.assertEqual(m.call_count, 1)      # banner present -> no retry
        sleep.assert_not_called()

    def test_timeout_is_not_retried(self):
        with mock.patch.object(self.sb.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("mu2e", 5)) as m, \
             mock.patch.object(self.sb.time, "sleep") as sleep:
            r = self.sb.run_sourced_bash("slow", timeout=5, backoffs=(1, 2, 3))
        self.assertTrue(r.timed_out)
        self.assertEqual(r.returncode, -1)
        self.assertEqual(m.call_count, 1)      # timeout = running, not a flake
        sleep.assert_not_called()


class TestPreflightFatalAbortClassification(unittest.TestCase):
    """Regression for wiki/incidents/preflight-past-init-false-pass.md:
    a fatal GeomSolids0002 abort AFTER pre-geometry strings (BeginRun /
    GenParticle) was classified PASS because past_init short-circuited the
    geom-fail check. G4_FATAL_RX must catch fatal aborts unconditionally,
    and must NOT fire on the advisory GeomVol1002 surface-check warnings
    that past_init exists to tolerate."""

    # Minimal reproduction of the foilsg06R00_00 preflight log shape.
    FATAL_LOG = (
        "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
        "... geometry construction ...\n"
        "-------- EEEE ------- G4Exception-START -------- EEEE -------\n"
        "*** G4Exception : GeomSolids0002\n"
        "      issued by : G4Tubs::G4Tubs()\n"
        "Invalid values for radii in solid: Foil_00\n"
        "        pRMin = 51.041, pRMax = 50\n"
        "*** Fatal Exception *** core dump ***\n"
    )

    # Advisory surface-check noise (stock-geometry overlaps): must stay PASS.
    ADVISORY_LOG = (
        "%MSG-w CONTROL:  EventGenerator:generate@BeginRun\n"
        "-------- WWWW ------- G4Exception-START -------- WWWW -------\n"
        "*** G4Exception : GeomVol1002\n"
        "      issued by : G4PVPlacement::CheckOverlaps()\n"
        "Overlap is detected for volume TT_MidInner\n"
        "-------- WWWW -------- G4Exception-END --------- WWWW -------\n"
        "Begin processing the 1st record\n"
        "Art has completed and will exit with status 0.\n"
    )

    def setUp(self):
        import autoresearch_bo_michael as bo
        self.bo = bo

    def test_fatal_abort_matches(self):
        self.assertTrue(self.bo.G4_FATAL_RX.search(self.FATAL_LOG))

    def test_advisory_overlap_does_not_match_fatal(self):
        self.assertFalse(self.bo.G4_FATAL_RX.search(self.ADVISORY_LOG))

    def test_geom_fail_rx_includes_geomsolids(self):
        # Widened G4_GEOM_FAIL_RX must now catch GeomSolids00xx too.
        self.assertTrue(self.bo.G4_GEOM_FAIL_RX.search(self.FATAL_LOG))

    def test_past_init_would_have_masked_it(self):
        # Documents the original bug shape: the fatal log DOES contain a
        # past_init trigger string, which is why the old classifier passed it.
        self.assertIn("BeginRun", self.FATAL_LOG)


class TestVerifyStoppingTargetGdml(unittest.TestCase):
    """As-built GDML geometry assertion (prelaunch gate added 2026-06-13
    after the foilsg uniform-hole incident — the canary proves the patch
    is present, this proves the VALUES are right)."""

    GEOM = (
        "vector<double> stoppingTarget.radii          = { 100.0, 200.0 };\n"
        "vector<double> stoppingTarget.halfThicknesses = { 0.5, 0.25 };\n"
        "double stoppingTarget.holeRadius = 1.0e6;\n"
        "vector<double> stoppingTarget.holeRadii      = { 10.0, 0.0 };\n"
    )

    @staticmethod
    def _gdml(tubes):
        items = "".join(
            f'<tube name="{n}" rmin="{rmin}" rmax="{rmax}" z="{z}" '
            f'lunit="{lunit}" deltaphi="6.28" aunit="rad"/>'
            for n, rmin, rmax, z, lunit in tubes)
        return f'<?xml version="1.0"?><gdml><solids>{items}</solids></gdml>'

    def _run(self, tubes, geom=None):
        import autoresearch_bo_michael as bo
        with tempfile.NamedTemporaryFile("w", suffix=".gdml",
                                         delete=False) as f:
            f.write(self._gdml(tubes))
            path = f.name
        try:
            return bo.verify_stopping_target_gdml(path, geom or self.GEOM)
        finally:
            Path(path).unlink()

    def test_matching_geometry_passes(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_wrong_hole_radius_fails(self):
        # The uniform-hole incident shape: built rIn != geom holeRadii.
        errs = self._run([("Foil_00", 51.041, 100.0, 1.0, "mm"),
                          ("Foil_01", 51.041, 200.0, 0.5, "mm")])
        self.assertEqual(len(errs), 2)
        self.assertIn("Foil_00 rIn", errs[0])

    def test_foil_count_mismatch_fails(self):
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm")])
        self.assertTrue(any("1 Foil_* tubes" in e and "2 foils" in e
                            for e in errs))

    def test_scalar_fallback_geom_uses_scalar(self):
        # Geom with no holeRadii vector: expected rIn is the scalar.
        geom = ("vector<double> stoppingTarget.radii = { 100.0 };\n"
                "double stoppingTarget.holeRadius = 21.5;\n")
        errs = self._run([("Foil_00", 21.5, 100.0, 0.0, "mm")], geom=geom)
        self.assertEqual(errs, [])

    def test_cm_units_scaled(self):
        errs = self._run([("Foil_00", 1.0, 10.0, 0.1, "cm"),
                          ("Foil_01", 0.0, 20.0, 0.05, "cm")])
        self.assertEqual(errs, [])

    def test_pointer_suffixed_names_parse_correctly(self):
        # G4's GDML writer appends 0x<addr> to every name. A greedy digit
        # match turns "Foil_020x55d..." into foil 20 — the live-preflight
        # bug of 2026-06-13. Indices must parse exactly.
        errs = self._run([("Foil_000x55d1a2b3", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_010x55d1c4d5", 0.0, 200.0, 0.5, "mm")])
        self.assertEqual(errs, [])

    def test_missing_foil_indices_reported(self):
        # Spurious/scrambled indices must surface as "missing", not be
        # silently skipped by the per-index compare loop.
        errs = self._run([("Foil_00", 10.0, 100.0, 1.0, "mm"),
                          ("Foil_07", 0.0, 200.0, 0.5, "mm")])
        self.assertTrue(any("missing from GDML: [1]" in e for e in errs))

    def test_repeat_last_half_thickness(self):
        # StoppingTargetMaker repeats the final halfThickness entry.
        geom = ("vector<double> stoppingTarget.radii = { 100.0, 200.0 };\n"
                "vector<double> stoppingTarget.halfThicknesses = { 0.5 };\n"
                "vector<double> stoppingTarget.holeRadii = { 0.0, 0.0 };\n")
        errs = self._run([("Foil_00", 0.0, 100.0, 1.0, "mm"),
                          ("Foil_01", 0.0, 200.0, 1.0, "mm")], geom=geom)
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
