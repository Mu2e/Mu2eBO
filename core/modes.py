"""The study registry: every schema-2 study file under mode_specs/ (plus the
directories in AUTORESEARCH_STUDY_PATH), loaded once by core/study.py, and
the batch pickers. mode_specs/archive/ is not loaded: it holds retired
studies (older study versions live in git history).
"""
from __future__ import annotations

import os

from paths import MODES_DIR
from study import load_study_dirs

STUDIES = load_study_dirs(MODES_DIR, os.environ.get("AUTORESEARCH_STUDY_PATH"))

# The batch pickers, declared once: graph/closed_loop.py validates --picker
# and core/botorch_predict.py dispatches on it. cl_min retired per ADR-0001.
PICKER_CHOICES = ("qnehvi", "qlnei", "budget_sob", "hybrid")
DEFAULT_PICKER = "hybrid"
