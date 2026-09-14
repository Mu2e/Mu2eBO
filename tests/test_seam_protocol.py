"""Typed-JSON seam tests: preflight verdict (Phase 2a) and — from Task 7 —
evaluate result (Phase 2b). The driver subprocess is faked by writing (or
not writing) the JSON the way a real/crashed run would."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph"))
import bo_driver as bo  # noqa: E402
import pipeline_io as pio  # noqa: E402


class TestWriteJsonAtomic(unittest.TestCase):
    def test_writes_parseable_json_and_no_tmp_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "v.json"
            bo.write_json_atomic(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})
            self.assertEqual(list(p.parent.glob("*.tmp")), [])


class TestPreflightVerdictEmit(unittest.TestCase):
    def test_wrapper_emits_verdict_json(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(bo, "_cmd_preflight_impl", return_value=1):
            out = Path(tmp) / "preflight_verdict.json"
            rc = bo.cmd_preflight(SimpleNamespace(
                mode="foilsflash", config_name="cfgX", emit_json=str(out)))
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["verdict"], "fail_managed")
            self.assertEqual(payload["rc"], 1)
            self.assertEqual(payload["config"], "cfgX")
            self.assertTrue(payload["reasons"])
            self.assertIn("cfgX.log", payload["log_path"])

    def test_no_emit_json_attr_is_fine(self):
        with mock.patch.object(bo, "_cmd_preflight_impl", return_value=0):
            rc = bo.cmd_preflight(SimpleNamespace(mode="foilsflash",
                                                  config_name="cfgX"))
            self.assertEqual(rc, 0)


def _fake_run(write_json=None, rc=0, stderr=""):
    """subprocess.run stand-in: optionally writes the verdict JSON the way
    the driver would, then returns a completed-process shim."""
    def run(cmd, **kw):
        if write_json is not None:
            i = cmd.index("--emit-json")
            bo.write_json_atomic(Path(cmd[i + 1]), write_json)
        return SimpleNamespace(returncode=rc, stdout="tail line\n",
                               stderr=stderr)
    return run


class TestRunPreflightReadsJson(unittest.TestCase):
    def _call(self, tmp, runner):
        with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
             mock.patch.object(pio.subprocess, "run", side_effect=runner):
            return pio.run_preflight("foilsflash", "cfgX")

    def test_valid_json_wins(self):
        # JSON says pass while rc=2 (old rc-map would say fail_init):
        # only a JSON-reading implementation returns "pass" here.
        with tempfile.TemporaryDirectory() as tmp:
            status, _ = self._call(tmp, _fake_run(
                {"verdict": "pass", "rc": 2, "reasons": [],
                 "log_path": "x", "config": "cfgX"}, rc=2))
            self.assertEqual(status, "pass")

    def test_missing_json_decodes_ambiguous_with_loud_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, tail = self._call(tmp, _fake_run(None, rc=0))
            self.assertEqual(status, "ambiguous")
            self.assertIn("missing/unparseable", tail)

    def test_a_crash_shows_its_stderr_not_just_ambiguous(self):
        """The tail was built from stdout ONLY.

        A preflight that dies before writing a verdict puts its traceback on
        stderr, so the operator saw "ambiguous" three times and never the
        cause -- a missing backing, whose PathsError names the exact fix
        (mmackenz 2026-08-13). Third instance of this repo's swallowed-stderr
        class, after jobsub-disk-quota and sourced-env.
        """
        with tempfile.TemporaryDirectory() as tmp:
            status, tail = self._call(tmp, _fake_run(
                None, rc=1,
                stderr="paths.PathsError: musing not found at /nope\n"
                       "    ./setup.sh --backing /exp/mu2e/app/users/<them>"))
            self.assertEqual(status, "ambiguous")
            self.assertIn("PathsError", tail)
            self.assertIn("--backing", tail)

    def test_stale_verdict_from_prior_run_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "cfgX" / "state" / "preflight_verdict.json"
            bo.write_json_atomic(stale, {"verdict": "pass", "rc": 0})
            status, _ = self._call(tmp, _fake_run(None, rc=1))
            self.assertEqual(status, "ambiguous")  # stale "pass" not trusted


class TestCmdEvaluateEmit(unittest.TestCase):
    def _tmp_mode(self, tmp):
        mode = bo.MODES["foilsflash"]
        patches = [
            mock.patch.multiple(
                mode,
                leaderboard=Path(tmp) / "leaderboard_bo_foilsflash.tsv",
                leaderboard_archive=None),
            mock.patch.object(mode, "proposal_dir", Path(tmp) / "proposals"),
        ]
        return mode, patches

    def test_success_appends_row_and_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                x = [100.0, 100.0, 0.05, 0.05, 0.5, 0.5]
                mode.render_proposal("cfgE", x)
                # propose writes BOTH the geom and the pending row
                # (graph/pipeline_io.py:82+89, bo_driver.py:1364+1372).
                # Rendering alone under-simulates it: since foilsflash became
                # JSON-defined it has no geometry parser, so the pending TSV
                # is the only record of x that evaluate can read.
                mode.append_pending("cfgE", x, bo.DEFAULT_ALPHA)
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps(
                    {"s_over_sqrt_b": 3.5, "flash_edep_per_pot": 1e-6}))
                out = Path(tmp) / "evaluate_result.json"
                rc = bo.cmd_evaluate(SimpleNamespace(
                    mode="foilsflash", config_name="cfgE",
                    summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                    emit_json=str(out)))
                self.assertEqual(rc, 0)
                self.assertIn("cfgE\t", mode.leaderboard.read_text())
                payload = json.loads(out.read_text())
                self.assertEqual(payload["config"], "cfgE")
                self.assertTrue(payload["row_appended"])
                self.assertAlmostEqual(payload["sob"], 3.5)

    def test_refusal_emits_nothing(self):
        """Flash edep missing → no row, no emit. Since foilsflash became
        JSON-defined the refusal is rc=1 rather than the retired
        FoilsFlashMode's SystemExit; what must not change is that nothing is
        appended and nothing is emitted."""
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                x = [100.0, 100.0, 0.05, 0.05, 0.5, 0.5]
                mode.render_proposal("cfgE", x)
                mode.append_pending("cfgE", x, bo.DEFAULT_ALPHA)
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps({"s_over_sqrt_b": 3.5}))
                out = Path(tmp) / "evaluate_result.json"
                rc = bo.cmd_evaluate(SimpleNamespace(
                    mode="foilsflash", config_name="cfgE",
                    summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                    emit_json=str(out)))
                self.assertEqual(rc, 1)
                self.assertFalse(out.exists())
                self.assertFalse(mode.leaderboard.exists())

    def test_zero_flash_is_never_substituted_for_a_flash_mode(self):
        """The 7-poison-row guard, generically.

        A missing second objective means the elebeam stage failed fail-soft.
        Substituting 0.0 there would append a fake zero-flash row at good sob
        that dominates the Pareto front at the next GP refit (2026-07-10).
        The retired FoilsFlashMode refused this by raising; cmd_evaluate must
        still refuse.
        """
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                x = [100.0, 100.0, 0.05, 0.05, 0.5, 0.5]
                mode.render_proposal("cfgE", x)
                mode.append_pending("cfgE", x, bo.DEFAULT_ALPHA)
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps({"s_over_sqrt_b": 3.5}))
                out = Path(tmp) / "evaluate_result.json"
                rc = bo.cmd_evaluate(SimpleNamespace(
                    mode="foilsflash", config_name="cfgE",
                    summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                    emit_json=str(out)))
                self.assertEqual(rc, 1)
                self.assertFalse(mode.leaderboard.exists(),
                                 "a zero-flash poison row was appended")
                self.assertFalse(out.exists())

    def test_missing_pending_row_refuses_loudly(self):
        """Without a geometry parser the pending TSV is the only record of x.
        If it is absent (e.g. evaluate re-run after a successful one cleared
        it) the refusal must be loud and must not guess."""
        with tempfile.TemporaryDirectory() as tmp:
            mode, patches = self._tmp_mode(tmp)
            with patches[0], patches[1]:
                mode.render_proposal("cfgE", [100.0, 100.0, 0.05, 0.05, 0.5, 0.5])
                summary = Path(tmp) / "summary.json"
                summary.write_text(json.dumps(
                    {"s_over_sqrt_b": 3.5, "flash_edep_per_pot": 1e-6}))
                with self.assertRaises(SystemExit) as cm:
                    bo.cmd_evaluate(SimpleNamespace(
                        mode="foilsflash", config_name="cfgE",
                        summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                        emit_json=None))
                self.assertIn("cannot recover x", str(cm.exception))
                self.assertFalse(mode.leaderboard.exists())


def _fake_eval_run(write_json=None, rc=0):
    def run(cmd, **kw):
        if write_json is not None:
            i = cmd.index("--emit-json")
            bo.write_json_atomic(Path(cmd[i + 1]), write_json)
        return SimpleNamespace(returncode=rc, stdout="tail\n", stderr="")
    return run


class TestRunEvaluateReadsJson(unittest.TestCase):
    def _call(self, tmp, runner):
        with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
             mock.patch.object(pio.subprocess, "run", side_effect=runner):
            return pio.run_evaluate("foilsflash", "cfgX",
                                    {"s_over_sqrt_b": 1.0})

    def test_obj_comes_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj, _ = self._call(tmp, _fake_eval_run(
                {"config": "cfgX", "obj": 1.234, "sob": 1.2,
                 "calo_or_flash": 1e-6, "row_appended": True}, rc=0))
            self.assertEqual(obj, 1.234)

    def test_rc_nonzero_returns_none_unchanged_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj, tail = self._call(tmp, _fake_eval_run(None, rc=1))
            self.assertIsNone(obj)
            self.assertIn("tail", tail)

    def test_rc_zero_without_json_is_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self._call(tmp, _fake_eval_run(None, rc=0))


class TestSeamStaleAndFallback(unittest.TestCase):
    def test_stale_evaluate_result_not_reused(self):
        # Pre-seed a stale result; driver writes nothing, rc=1 → (None, tail)
        # and the stale obj must NOT be returned.
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "cfgX" / "state" / "evaluate_result.json"
            bo.write_json_atomic(stale, {"config": "cfgX", "obj": 9.9,
                                         "sob": 9.9, "calo_or_flash": 1e-9,
                                         "row_appended": True})
            with mock.patch.object(pio, "GRID_DATA_ROOT", Path(tmp)), \
                 mock.patch.object(pio.subprocess, "run",
                                   side_effect=_fake_eval_run(None, rc=1)):
                obj, _ = pio.run_evaluate("foilsflash", "cfgX",
                                          {"s_over_sqrt_b": 1.0})
            self.assertIsNone(obj)

    def test_preflight_out_of_domain_rc_decodes_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(bo, "_cmd_preflight_impl", return_value=99):
            out = Path(tmp) / "preflight_verdict.json"
            rc = bo.cmd_preflight(SimpleNamespace(
                mode="foilsflash", config_name="cfgX", emit_json=str(out)))
            self.assertEqual(rc, 99)
            self.assertEqual(json.loads(out.read_text())["verdict"],
                             "ambiguous")


if __name__ == "__main__":
    unittest.main()
