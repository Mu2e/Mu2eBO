#!/usr/bin/env python3
"""ONE-TIME: convert today's mode spec JSON to a schema-2 study file.

Knows exactly one family, the foilspf/foilsflash chain (mubeam ->
mustops_ce, elebeam_flash; harvest = EdepAna sensitivity + flash), and
refuses anything else. Deleted after the switch (Task 5).

Usage: tools/convert_spec_v2.py --in-place FILE [FILE ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FLASH_BUDGET = 6.85443e-7   # was botorch_predict.flash_budget()'s default
BUDGET_K_SIGMA = 1.0        # was botorch_predict.budget_k_sigma()'s default
_EXPECTED_STAGES = ["mubeam", "mustops_ce", "elebeam_flash"]


def convert(doc: dict) -> dict:
    run, lb = doc["run"], doc["leaderboard"]
    if run["stages"] != _EXPECTED_STAGES:
        raise ValueError(f"{doc['name']}: stages {run['stages']} are not the "
                         f"foilspf chain {_EXPECTED_STAGES}")
    c0, c1 = lb["columns"][0], lb["columns"][1]
    if lb["columns"][2:] != ["alpha", "obj"]:
        raise ValueError(f"{doc['name']}: unexpected columns {lb['columns']}")
    if lb["metrics"].get(c0) != ["s_over_sqrt_b"] or \
            lb["metrics"].get(c1, [None])[0] != "flash_edep_per_pot":
        raise ValueError(f"{doc['name']}: unexpected metrics {lb['metrics']}")

    int_dims = set(doc.get("int_dims") or [])
    knobs = [{"name": k["name"], "type": "int" if i in int_dims else "real",
              "min": k["min"], "max": k["max"], "unit": "", "fmt": k["fmt"]}
             for i, k in enumerate(doc["knobs"])]
    g = doc["geom"]
    derive = {"consts": g.get("consts") or {}, "exprs": g.get("derived") or {},
              "profiles": {n: {"kind": "lagrange", **p}
                           for n, p in (g.get("profiles") or {}).items()}}
    geom = {"writer": "offline_simpleconfig", "base": g["base"],
            "lines": g["lines"]}

    presubmitted = set()
    for targets in (run.get("presubmit_after") or {}).values():
        presubmitted.update(targets)
    jobs = run.get("jobs_per_stage") or {}
    tuning = run.get("stage_tuning") or {}
    first = run["stages"][0]
    steps = []
    for stage in run["stages"]:
        fixed = {}
        if stage in jobs:
            fixed["njobs"] = jobs[stage]
        fixed.update(tuning.get(stage, {}))
        # The pipeline feeds only the first stage's outputs forward
        # (pipeline.py INPUT_STAGE); elebeam_flash resamples its own input.
        files_from = [] if stage in (first, "elebeam_flash") else [first]
        steps.append({"step": stage, "kit": "prodtools", "entry": stage,
                      "files": ["geom"], "files_from": files_from,
                      "params": {}, "fixed": fixed})
    steps += [
        {"step": "sob", "kit": "ce_sensitivity", "entry": None, "files": [],
         "files_from": ["mubeam", "mustops_ce"], "params": {}, "fixed": {}},
        {"step": "flash", "kit": "flash_edep_per_pot", "entry": None,
         "files": [], "files_from": ["elebeam_flash"], "params": {},
         "fixed": {}},
    ]
    noise = lb["obs_noise"]
    return {
        "schema": 2,
        "name": doc["name"],
        "note": doc.get("note", ""),
        "knobs": knobs,
        "derive": derive,
        "geom": geom,
        "kits": {
            "prodtools": {"code_tarball": doc["software"]["grid_tarball"]},
            "offline_preflight": {"musing": doc["software"]["musing"],
                                  **doc["preflight"]},
        },
        "preflight": {"kit": "offline_preflight", "params": {},
                      "files": ["geom"]},
        "evaluate": steps,
        "objectives": [
            {"name": c0, "metric": "sob.s_over_sqrt_b", "direction": "max",
             "transform": "none", "noise": noise[0], "fmt": "{:.5f}"},
            {"name": c1, "metric": "flash.flash_edep_per_pot",
             "direction": "min", "transform": "log10", "noise": noise[1],
             "fmt": "{:.5e}"},
        ],
        "constraints": [{"name": c1, "max": FLASH_BUDGET,
                         "k_sigma": BUDGET_K_SIGMA}],
        "extra_metrics": [],
        "extra_columns": [
            {"name": "alpha", "expr": "alpha", "fmt": "{:.3f}"},
            {"name": "obj", "expr": f"{c0} - alpha * {c1}", "fmt": "{:.5f}"},
        ],
        "leaderboard": {"file": lb["file"], "layout": "v1",
                        "context": ["alpha"]},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in-place", action="store_true", required=True)
    ap.add_argument("files", nargs="+", type=Path)
    ns = ap.parse_args(argv)
    for p in ns.files:
        doc = json.loads(p.read_text())
        if doc.get("schema") == 2:
            print(f"skip (already schema 2): {p}")
            continue
        p.write_text(json.dumps(convert(doc), indent=1) + "\n")
        print(f"converted: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
