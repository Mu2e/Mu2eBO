"""The study registry: every schema-2 study file under mode_specs/ (plus the
directories in AUTORESEARCH_STUDY_PATH), loaded once by core/study.py, and
the batch pickers. mode_specs/archive/ is not loaded: it holds retired
studies (older study versions live in git history).
"""
from __future__ import annotations

import os
from pathlib import Path

# THE IMPORT MIRRORS OUR OWN PACKAGE-QUALIFICATION (__package__): this
# module loads as `core.modes` from the repo root AND as bare `modes` from
# code that puts core/ on sys.path. A hardcoded qualified import fails
# outright on the bare path; a hardcoded bare import would, on the
# qualified path, load study.py a SECOND time under a different
# sys.modules key.
if __package__:
    from core.study import load_study_dirs  # noqa: E402
else:
    from study import load_study_dirs  # noqa: E402

MODES_DIR = Path(__file__).resolve().parent.parent / "mode_specs"
STUDIES = load_study_dirs(MODES_DIR, os.environ.get("AUTORESEARCH_STUDY_PATH"))

# The batch pickers, declared once: graph/closed_loop.py validates --picker
# and core/botorch_predict.py dispatches on it. cl_min retired per ADR-0001.
PICKER_CHOICES = ("qnehvi", "qlnei", "budget_sob", "hybrid")
DEFAULT_PICKER = "hybrid"
