#!/usr/bin/env python
"""Re-capture the frozen geometry goldens used by tests/test_json_mode_parity.py.

The goldens are the parity oracle for JSON-defined modes. They exist because
retiring a Python mode deletes the renderer the parity test used to compare
against -- see the docstring on
`ParityMixin.test_same_geometry_as_python_renderer`.

Run this ONLY when a surviving Python renderer legitimately changes. It
refuses to capture a mode that no longer has a Python renderer: for those the
golden IS the definition, and silently regenerating it from the JSON spec
would turn the parity test into a tautology that compares the JSON to itself.

  PYTHONPATH= .venv/bin/python tools/capture_golden_geom.py [--check]

  --check  re-render and diff without writing (exit 1 on drift)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tests"))

from bo_driver import MODES  # noqa: E402
# has_python_renderer lives with the goldens it protects (and is pinned by
# tests there); importing it here keeps a single tool -> test dependency
# rather than a cycle.
from test_json_mode_parity import (  # noqa: E402
    SAMPLE_X, GOLDEN, parse_assignments, has_python_renderer)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diff only; do not write")
    args = ap.parse_args()

    GOLDEN.mkdir(parents=True, exist_ok=True)
    drift = cosmetic = skipped = written = 0

    for mode, xs in sorted(SAMPLE_X.items()):
        if not has_python_renderer(mode):
            print(f"SKIP {mode}: no Python renderer — golden is the oracle "
                  f"and must not be regenerated")
            skipped += 1
            continue
        python_mode = MODES[mode]
        for i, x in enumerate(xs):
            text = python_mode._geom_text(x)
            p = GOLDEN / f"{mode}_{i}.txt"
            if args.check:
                old = p.read_text() if p.exists() else None
                if old == text:
                    continue
                # Compare the way test_json_mode_parity does: real drift is a
                # changed FHiCL assignment, not a reflowed comment. Raw-text
                # diffing here reported DRIFT on goldens the suite passes.
                if old is not None and parse_assignments(old) == parse_assignments(text):
                    print(f"cosmetic {p.name} (comments/whitespace only)")
                    cosmetic += 1
                else:
                    print(f"DRIFT {p.name}")
                    drift += 1
            else:
                p.write_text(text)
                written += 1

    if args.check:
        print(f"{drift} drifted, {cosmetic} cosmetic, {skipped} mode(s) skipped")
        return 1 if drift else 0
    print(f"wrote {written} golden(s), {skipped} mode(s) skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
