"""Unit tests for harvest.py — the Eval-summary module.

Runs grid-free: extractor runners are injected fakes, state dirs are tmpdirs.
Covers the branches that previously lived untested inside cmd_harvest
(FP-1/FP-2 of the 2026-07-11 architecture re-survey), including the two
incident regressions: EdepAna scientific-notation counts and the
concat-vs-mubeam mu⁻-stop input resolution that biased ff11R00_07.
"""
import tempfile
import unittest
from pathlib import Path

import harvest


class TestParsers(unittest.TestCase):
    def test_edepana_plain_int(self):
        self.assertEqual(
            harvest.parse_edepana_saw("EdepAna summary: Saw 576070 events"),
            576070)

    def test_edepana_scientific_notation(self):
        # incident: edepana-saw-events-scientific-notation-parse — %g output
        # at >1M events must parse.
        self.assertEqual(
            harvest.parse_edepana_saw("EdepAna summary: Saw 2.70937e+06 events"),
            2709370)

    def test_edepana_missing_raises(self):
        with self.assertRaises(ValueError):
            harvest.parse_edepana_saw("no summary line here")

    def test_s_over_sqrt_b(self):
        out = "junk\nSignal box [103.85,105.1]: S/sqrt(B) = 3.78\ntrailer"
        self.assertEqual(harvest.parse_s_over_sqrt_b(out), 3.78)

    def test_s_over_sqrt_b_missing_raises(self):
        with self.assertRaises(ValueError):
            harvest.parse_s_over_sqrt_b("Signal box but no metric")


class TestStageChainStamp(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            harvest.stamp_stage_chain(state, ["mubeam", "mustops_ce", "elebeam_flash"])
            self.assertEqual(harvest.stamped_stage_chain(state),
                             ["mubeam", "mustops_ce", "elebeam_flash"])

    def test_legacy_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(harvest.stamped_stage_chain(Path(d)))


def _write_outputs(state: Path, stage: str, names):
    (state / f"{stage}_outputs.txt").write_text(
        "\n".join(f"/pnfs/fake/{n}" for n in names) + "\n")


class TestResolveMuminusInputs(unittest.TestCase):
    def test_stamped_concat_chain_uses_concat(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            harvest.stamp_stage_chain(state, ["mubeam", "concat", "mustops_ce"])
            _write_outputs(state, "concat",
                           ["sim.x.MuminusStopsCat.a.art", "sim.x.MuplusStopsCat.a.art"])
            files, source = harvest.resolve_muminus_inputs(state)
            self.assertEqual(source, "concat")
            self.assertEqual([f.name for f in files], ["sim.x.MuminusStopsCat.a.art"])

    def test_stamped_concatless_chain_uses_mubeam(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            harvest.stamp_stage_chain(state, ["mubeam", "mustops_ce", "elebeam_flash"])
            _write_outputs(state, "mubeam",
                           ["sim.x.TargetStops.a.art", "nts.x.mubeam.a.root"])
            files, source = harvest.resolve_muminus_inputs(state)
            self.assertEqual(source, "mubeam")
            self.assertEqual([f.name for f in files], ["sim.x.TargetStops.a.art"])

    def test_legacy_presence_concat_wins_over_env(self):
        # ff11R00_07 lesson: existing concat outputs are the truth for this
        # config regardless of the current process env / mode chain.
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "concat", ["sim.x.MuminusStopsCat.a.art"])
            _write_outputs(state, "mubeam", ["sim.x.TargetStops.a.art"])
            files, source = harvest.resolve_muminus_inputs(state)
            self.assertEqual(source, "concat")

    def test_legacy_no_concat_falls_back_to_mubeam(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "mubeam", ["sim.x.TargetStops.a.art"])
            files, source = harvest.resolve_muminus_inputs(state)
            self.assertEqual(source, "mubeam")

    def test_blank_concat_outputs_is_hard_error_not_absence(self):
        # stage-out-lag face: a single blank line must NOT be read as
        # "concat absent" (that would silently switch the denominator source).
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            harvest.stamp_stage_chain(state, ["mubeam", "concat", "mustops_ce"])
            (state / "concat_outputs.txt").write_text("\n")
            with self.assertRaises(SystemExit):
                harvest.resolve_muminus_inputs(state)

    def test_no_targetstops_match_raises(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "mubeam", ["nts.x.mubeam.a.root"])
            with self.assertRaises(SystemExit):
                harvest.resolve_muminus_inputs(state)


class TestEventsPerJob(unittest.TestCase):
    def test_stamp_wins(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            (state / "elebeam_flash_events_per_job.txt").write_text("110000\n")
            self.assertEqual(harvest.events_per_job(state, "elebeam_flash", 2500),
                             110000)

    def test_fallback_when_unstamped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(harvest.events_per_job(Path(d), "mubeam", 5000), 5000)


class TestExtractSecondaryEdep(unittest.TestCase):
    def test_absent_stage_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(harvest.extract_secondary_edep(
                Path(d), "elebeam_flash", runner=lambda files: (0, 0, 0, "", [])))

    def test_blank_outputs_records_error(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            (state / "elebeam_flash_outputs.txt").write_text("\n")
            res = harvest.extract_secondary_edep(
                state, "elebeam_flash", runner=lambda files: (0, 0, 0, "", []))
            self.assertIsNotNone(res.error)
            self.assertIsNone(res.total_MeV)

    def test_runner_exception_fail_softs(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "elebeam_flash", ["a.art", "b.art"])

            def boom(files):
                raise RuntimeError("NFS RPC hang, allegedly")

            res = harvest.extract_secondary_edep(state, "elebeam_flash", runner=boom)
            self.assertIn("NFS RPC hang", res.error)
            self.assertEqual(res.n_files, 2)
            self.assertIsNone(res.total_MeV)

    def test_success_populates_metric(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            _write_outputs(state, "elebeam_flash", ["a.art", "b.art"])
            res = harvest.extract_secondary_edep(
                state, "elebeam_flash",
                runner=lambda files: (0.5, 100.0, 200, "makeSGS", [40.0, 60.0]))
            self.assertIsNone(res.error)
            self.assertEqual(res.total_MeV, 100.0)
            self.assertEqual(res.per_file, [40.0, 60.0])
            self.assertEqual(res.n_files, 2)


class TestPerPotAndWinsor(unittest.TestCase):
    def test_per_pot_math(self):
        val, n_input = harvest.per_pot(total_MeV=248.436, n_files=188, epj=110000)
        self.assertEqual(n_input, 188 * 110000)
        self.assertAlmostEqual(val, 248.436 / (188 * 110000 * harvest.POT_PER_ELECTRON))

    def test_per_pot_none_on_missing(self):
        self.assertEqual(harvest.per_pot(None, 188, 110000), (None, None))
        self.assertEqual(harvest.per_pot(1.0, 0, 110000), (None, None))

    def test_winsor_below_min_files(self):
        self.assertEqual(harvest.winsorized_diagnostics([1.0] * 9, 110000),
                         (None, None))

    def test_winsor_clips_tail(self):
        # 20 files: one huge outlier; winsorized mean must sit well below the
        # plain mean, and stats must record the raw spread.
        per_file = [1.0] * 19 + [100.0]
        wm, stats = harvest.winsorized_diagnostics(per_file, epj=1)
        plain = sum(per_file) / len(per_file)  # 5.95
        # k = max(1, int(0.05*20)) = 1 → clip to [v[1], v[-2]] = [1.0, 1.0]
        self.assertAlmostEqual(wm, 1.0 / harvest.POT_PER_ELECTRON)
        self.assertLess(wm, plain / harvest.POT_PER_ELECTRON)
        self.assertEqual(stats["n_files"], 20)
        self.assertEqual(stats["max"], 100.0)
        self.assertGreater(stats["sd_over_mean"], 1.0)

    def test_winsor_matches_legacy_inline_algorithm(self):
        # Bit-parity with the pipeline.py:1421-1436 inline math it replaces.
        per_file = [3.1, 2.9, 3.3, 2.7, 3.0, 3.2, 2.8, 3.05, 2.95, 3.15,
                    9.0, 0.1]
        epj = 110000
        v = sorted(per_file)
        k = max(1, int(0.05 * len(v)))
        lo, hi = v[k], v[-k - 1]
        w = [min(max(x, lo), hi) for x in per_file]
        legacy = (sum(w) / len(w)) / (epj * harvest.POT_PER_ELECTRON)
        wm, _ = harvest.winsorized_diagnostics(per_file, epj=epj)
        self.assertAlmostEqual(wm, legacy)


class TestEvalSummarySchema(unittest.TestCase):
    LEGACY_KEYS = {
        "config", "ce_seen", "muminus_stops", "mubeam_sim_total",
        "ce_simulated_events", "stopping_factor", "ce_abs_eff",
        "s_over_sqrt_b", "trk_edep_per_pot", "trk_edep_total_MeV",
        "trk_edep_events", "trk_edep_tag", "flash_edep_per_event",
        "flash_edep_per_pot", "flash_edep_per_pot_winsor",
        "flash_perfile_stats", "flash_edep_total_MeV", "flash_edep_events",
        "flash_n_input", "flash_edep_tag", "calo_per_pot", "calo_total",
        "calo_files_seen", "nts_path", "edep_log", "macro_log",
    }

    def _minimal(self):
        return harvest.EvalSummary(
            config="testcfg", ce_seen=576070, muminus_stops=238912,
            mubeam_sim_total=2800000, ce_simulated_events=1050000,
            stopping_factor=0.0853, ce_abs_eff=5.98e-4, s_over_sqrt_b=3.78,
            muminus_source="concat")

    def test_all_legacy_keys_present(self):
        # Every key the current cmd_harvest writes must survive the
        # refactor — downstream (extract_metrics, evaluate node, humans)
        # reads summary.json positionally by name.
        import json as _json
        keys = set(_json.loads(self._minimal().to_json()).keys())
        missing = self.LEGACY_KEYS - keys
        self.assertFalse(missing, f"legacy summary keys missing: {missing}")

    def test_write_and_reload(self):
        import json as _json
        with tempfile.TemporaryDirectory() as d:
            out = self._minimal().write(Path(d))
            data = _json.loads(out.read_text())
            self.assertEqual(data["config"], "testcfg")
            self.assertEqual(data["s_over_sqrt_b"], 3.78)
            self.assertIsNone(data["flash_edep_per_pot"])
            self.assertEqual(data["muminus_source"], "concat")
            self.assertEqual(data["degraded"], {})


if __name__ == "__main__":
    unittest.main()
