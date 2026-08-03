"""Pre-argparse argv sniffers shared by the graph entry points.

config.py resolves GRID_STAGES / MUSING / MUSE tarball choices from
AUTORESEARCH_* env vars at module-load time (build.STAGE_NODES freezes
GRID_STAGES), but argparse only runs in main() — too late. graph/run.py and
graph/closed_loop.py call these BEFORE `from config import ...`. Issue
Mu2eBO #15.
"""
from __future__ import annotations

import os
import sys


def presniff_mode() -> None:
    for i, a in enumerate(sys.argv[1:], start=1):
        if a == "--mode" and i + 1 < len(sys.argv):
            os.environ["AUTORESEARCH_MODE"] = sys.argv[i + 1]
            return
        if a.startswith("--mode="):
            os.environ["AUTORESEARCH_MODE"] = a.split("=", 1)[1]
            return


def presniff_picker() -> None:
    """If picker=qlnei, stamp AUTORESEARCH_NO_RUN1B=1 so config.GRID_STAGES
    omits run1b_mubeam at import time. Same load-order rationale as
    presniff_mode."""
    for i, a in enumerate(sys.argv[1:], start=1):
        if a == "--picker" and i + 1 < len(sys.argv) and sys.argv[i + 1] == "qlnei":
            os.environ["AUTORESEARCH_NO_RUN1B"] = "1"
            return
        if a == "--picker=qlnei":
            os.environ["AUTORESEARCH_NO_RUN1B"] = "1"
            return
