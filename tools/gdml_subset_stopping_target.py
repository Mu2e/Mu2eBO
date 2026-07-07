#!/usr/bin/env python3
"""Extract a standalone GDML of ONLY the stopping-target foils.

The as-built preflight GDML (asbuilt_<config>.gdml) contains the full Mu2e
world; most viewers then bury the 49 thin foils and/or undercount them (see
wiki/drivers/preflight.md viewer gotcha). This pulls StoppingTargetMother +
its Foil_* daughters into a minimal GDML whose top (setup/world) volume IS
StoppingTargetMother — so a viewer shows the foil stack and nothing else.

Thin wrapper: the generic extractor (recursive post-order volume walk so
ROOT's TGDMLParse never sees a forward <volume> ref — see
wiki/incidents/root-gdml-forward-volume-ref.md — plus boolean-solid closure
and whole-materials carry) lives in tools/gdml_subset_production_target.py;
this script just pins the mother/daughter names.

Usage:
  python3 tools/gdml_subset_stopping_target.py <asbuilt.gdml> [out.gdml]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gdml_subset_production_target import extract  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".gdml", "_stoppingtarget.gdml")
    extract(src, dst, mother_sub="StoppingTargetMother", daughter_sub="Foil_")
