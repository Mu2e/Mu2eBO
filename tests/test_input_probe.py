"""Tests for pipeline._probe_input_urls — the authoritative auxinput
liveness gate (friction-survey FP-5).

The regression these pin: the original probe silently skipped URLs that
didn't match one hardcoded door name, so a door rename would recreate the
EleBeamCat tape-wipeout with the probe green on zero probes. The gate is
now fail-closed on unmappable URLs.
"""
import os
import unittest
from unittest import mock

import pipeline


def _ok():
    m = mock.Mock()
    m.wait.return_value = 0
    return m


def _fail():
    m = mock.Mock()
    m.wait.return_value = 1
    return m


class TestProbeInputUrls(unittest.TestCase):
    def test_no_urls_is_a_noop(self):
        # Stages without auxinput (e.g. pot_only) have nothing to probe.
        with mock.patch.object(pipeline.subprocess, "Popen") as r:
            pipeline._probe_input_urls("pot_only", "physics: {}")
        r.assert_not_called()

    def test_mapped_readable_passes(self):
        fcl = ('fileNames: ["xroot://fndcadoor.fnal.gov//pnfs/fnal.gov/usr/'
               'mu2e/tape/phy-sim/sim/mu2e/EleBeamCat/x.art"]')
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=_ok()) as r:
            pipeline._probe_input_urls("elebeam_flash", fcl)
        self.assertEqual(r.call_count, 1)
        probed = r.call_args.args[0][3]
        self.assertTrue(probed.startswith("if=/pnfs/mu2e/tape/"), probed)

    def test_mapped_unreadable_gates(self):
        fcl = ('"xroot://fndcadoor.fnal.gov//pnfs/fnal.gov/usr/mu2e/'
               'persistent/datasets/x.art"')
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=_fail()):
            with self.assertRaises(SystemExit) as cm:
                pipeline._probe_input_urls("elebeam_flash", fcl)
        self.assertIn("not readable", str(cm.exception))

    def test_renamed_door_still_maps(self):
        # Door-agnostic mapping: a renamed dCache door must not bypass the gate.
        fcl = '"root://newdoor.fnal.gov//pnfs/fnal.gov/usr/mu2e/tape/y.art"'
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=_ok()) as r:
            pipeline._probe_input_urls("mubeam", fcl)
        self.assertEqual(r.call_count, 1)

    def test_unmappable_url_fails_closed(self):
        # THE FP-5 regression: URLs present but none probeable used to pass
        # silently; now it refuses to submit blind.
        fcl = '"xroot://door.example.org//store/other/experiment/z.art"'
        with mock.patch.object(pipeline.subprocess, "Popen") as r:
            with self.assertRaises(SystemExit) as cm:
                pipeline._probe_input_urls("elebeam_flash", fcl)
        self.assertIn("cannot map", str(cm.exception))
        r.assert_not_called()

    def test_escape_hatch(self):
        fcl = '"xroot://door.example.org//store/other/z.art"'
        with mock.patch.dict(os.environ, {"AUTORESEARCH_SKIP_INPUT_PROBE": "1"}):
            pipeline._probe_input_urls("elebeam_flash", fcl)  # no raise

    def test_probe_capped_at_four(self):
        urls = "".join(
            f'"xroot://d.fnal.gov//pnfs/fnal.gov/usr/mu2e/tape/f{i}.art" '
            for i in range(9))
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=_ok()) as r:
            pipeline._probe_input_urls("elebeam_flash", urls)
        self.assertEqual(r.call_count, 4)


if __name__ == "__main__":
    unittest.main()
