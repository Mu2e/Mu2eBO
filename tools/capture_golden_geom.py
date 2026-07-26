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
from test_json_mode_parity import SAMPLE_X, GOLDEN  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diff only; do not write")
    args = ap.parse_args()

    GOLDEN.mkdir(parents=True, exist_ok=True)
    drift = skipped = written = 0

    for mode, xs in sorted(SAMPLE_X.items()):
        python_mode = MODES.get(mode)
        if python_mode is None or not hasattr(python_mode, "_geom_text"):
            # Retired or JSON-defined: the golden is the sole surviving oracle.
            print(f"SKIP {mode}: no Python renderer — golden is the oracle "
                  f"and must not be regenerated")
            skipped += 1
            continue
        for i, x in enumerate(xs):
            text = python_mode._geom_text(x)
            p = GOLDEN / f"{mode}_{i}.txt"
            if args.check:
                old = p.read_text() if p.exists() else None
                if old != text:
                    print(f"DRIFT {p.name}")
                    drift += 1
            else:
                p.write_text(text)
                written += 1

    if args.check:
        print(f"{drift} drifted, {skipped} mode(s) skipped")
        return 1 if drift else 0
    print(f"wrote {written} golden(s), {skipped} mode(s) skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
