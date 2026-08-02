"""Zero-overlap preflight policy (2026-07-28).

Why this exists: the managed/baseline split classifies overlaps by volume
NAME (`SURFACE_OVERLAP_MANAGED` matches StoppingTargetFoil_*/ProductionTarget*)
and treats everything else as inert stock-geometry noise. That assumption --
"not named like a BO volume" implies "independent of BO knobs" -- is false.
`IPAsupport_*` wires are positioned from `targetEnd`, which is a function of
our foil stack (MECOStyleProtonAbsorberMaker.cc:124-129).

The concrete miss: foilsflashRUN1BAP01 introduced 3 IPAsupport overlaps that
had never appeared in the preceding 461 evaluations, and preflight reported
"3 known stock-geometry overlaps ... ignored" and PASSED. These tests pin the
strict policy that turns that into a failure.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import modes  # noqa: E402
from bo_driver import (  # noqa: E402
    SURFACE_OVERLAP_MANAGED,
    SURFACE_OVERLAP_RX,
    _overlap_banner,
)

# Verbatim G4 output from bo_work/preflight/foilsflash/foilsflashRUN1BAP01.log
# -- the run that passed when it should not have.
IPA_OVERLAP_LOG = """
Checking overlaps for volume IPAsupport_set2_wire1:0 (G4Tubs) ...
-------- WWWW ------- G4Exception-START -------- WWWW -------
*** G4Exception : GeomVol1002
      issued by : G4PVPlacement::CheckOverlaps()
Overlap is detected for volume IPAsupport_set2_wire1:0 (G4Tubs) with its mother volume DS2Vacuum (G4Tubs)
          protrusion at mother local point (0,0,0) by 11.063 cm  (max of 8925 cases)
*** This is just a warning message. ***
-------- WWWW -------- G4Exception-END --------- WWWW -------
Overlap is detected for volume IPAsupport_set2_wire2:0 (G4Tubs) with its mother volume DS2Vacuum (G4Tubs)
Overlap is detected for volume IPAsupport_set2_wire3:0 (G4Tubs) with its mother volume DS2Vacuum (G4Tubs)
"""

# The single overlap every foilsflash eval carried under Run1Bak: 461 of 462
# historical preflights, always this volume.
EMC_OVERLAP_LOG = """
Overlap is detected for volume VirtualDetector_EMC_0_Front:119 (G4Tubs) with StoppingTargetMother:0 (G4Tubs)
"""


class TestOverlapClassification(unittest.TestCase):
    """The whitelist behaviour the strict policy has to compensate for."""

    def test_ipasupport_is_not_matched_as_managed(self):
        """The reason the miss happened -- pinned so it cannot be 'fixed' by
        quietly widening the regex without revisiting this policy."""
        hits = SURFACE_OVERLAP_RX.findall(IPA_OVERLAP_LOG)
        self.assertEqual(len(hits), 3)
        self.assertEqual([h for h in hits if SURFACE_OVERLAP_MANAGED.match(h)], [])

    def test_emc_front_is_not_matched_as_managed_either(self):
        hits = SURFACE_OVERLAP_RX.findall(EMC_OVERLAP_LOG)
        self.assertEqual(len(hits), 1)
        self.assertFalse(SURFACE_OVERLAP_MANAGED.match(hits[0]))

    def test_a_managed_volume_still_matches(self):
        """Guards the guard: the regex must still catch real foil overlaps."""
        self.assertTrue(SURFACE_OVERLAP_MANAGED.match("StoppingTargetFoil_07"))
        self.assertTrue(SURFACE_OVERLAP_MANAGED.match("ProductionTargetPlate03"))


class TestPolicyFlagWiring(unittest.TestCase):

    def test_run1bap_modes_require_zero(self):
        """foilsflash/foilspf run a Musing that can reach zero overlaps."""
        for name in ("foilsflash", "foilspf"):
            self.assertTrue(modes.SPECS[name].require_zero_overlaps, name)

    def test_run1bak_modes_do_not_require_zero(self):
        """Run1Bak carries EMC_0_Front unavoidably; demanding zero there would
        fail every config rather than catch anything."""
        for name in ("foils", "foilsf", "foilsg"):
            self.assertFalse(modes.SPECS[name].require_zero_overlaps, name)

    def test_every_mode_declares_the_flag(self):
        """No silent defaults: a new mode must state its overlap policy."""
        for name, spec in modes.SPECS.items():
            self.assertIsInstance(spec.require_zero_overlaps, bool, name)

    def test_strict_modes_also_scan_overlaps(self):
        """require_zero_overlaps is meaningless unless the scan runs -- the
        gate lives inside the `if checks_managed_overlap:` block."""
        for name, spec in modes.SPECS.items():
            if spec.require_zero_overlaps:
                self.assertTrue(spec.checks_managed_overlap, name)


class TestPassBanner(unittest.TestCase):
    """The banner must name the policy that actually ran (the prodtarget6d
    banner drift is why checks_managed_overlap exists at all)."""

    def test_banner_reports_strict_policy(self):
        self.assertEqual(_overlap_banner("foilsflash"),
                         " and zero surface-check overlaps")

    def test_banner_reports_managed_policy(self):
        self.assertEqual(_overlap_banner("foils"),
                         " and no managed-volume overlap")


class TestJsonSchemaRequiresTheKey(unittest.TestCase):

    def test_loader_rejects_a_spec_missing_the_flag(self):
        """A JSON mode that omits require_zero_overlaps must be a load error,
        not a silent False -- silently-lenient is the failure mode this whole
        policy exists to remove."""
        import mode_json
        self.assertIn("require_zero_overlaps", mode_json._REQUIRED_PREFLIGHT)


if __name__ == "__main__":
    unittest.main()
