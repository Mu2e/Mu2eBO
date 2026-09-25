"""Builders shared by the engine tests: a minimal study on toykit, its
file, and (Task 3 on) a toykit KitConfig that writes under a temp dir."""
import json
from pathlib import Path

ENGINE_STUDIES = Path(__file__).resolve().parent / "fixtures" / "engine_studies"


def toy_doc(name="toystudy", layout="v1"):
    """One toykit step, Branin and Currin as the two objectives, Currin
    constrained. Tests mutate the returned dict freely."""
    return {
        "schema": 2,
        "name": name,
        "note": "engine test study on toykit",
        "knobs": [
            {"name": "x1", "type": "real", "min": -5.0, "max": 10.0,
             "unit": "", "fmt": "{:.6f}"},
            {"name": "x2", "type": "real", "min": 0.0, "max": 15.0,
             "unit": "", "fmt": "{:.6f}"},
        ],
        "derive": {"consts": {}, "exprs": {}, "profiles": {}},
        "geom": None,
        "kits": {"toykit": {"function": "branin_currin"}},
        "preflight": None,
        "evaluate": [
            {"step": "toy", "kit": "toykit", "entry": None, "files": [],
             "files_from": [], "params": {"x1": "x1", "x2": "x2"},
             "fixed": {"delay_s": 0.0}},
        ],
        "objectives": [
            {"name": "branin", "metric": "toy.branin", "direction": "min",
             "transform": "none", "noise": 0.01, "fmt": "{:.6f}"},
            {"name": "currin", "metric": "toy.currin", "direction": "min",
             "transform": "log10", "noise": 0.01, "fmt": "{:.6f}"},
        ],
        "constraints": [{"name": "currin", "max": 10.0, "k_sigma": 1.0}],
        "extra_metrics": [],
        "extra_columns": [],
        "leaderboard": {"file": f"leaderboards/leaderboard_{name}.tsv",
                        "layout": layout, "context": []},
    }


def write_study(doc, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['name']}.json"
    path.write_text(json.dumps(doc, indent=1))
    return path


def engine_env(data_root, study_dir):
    """Environment for an engine subprocess: every runtime root under
    `data_root` (never the real DATA_ROOT), studies from `study_dir`."""
    import os
    env = dict(os.environ)
    env.update(AUTORESEARCH_DATA_ROOT=str(data_root),
               AUTORESEARCH_STUDY_PATH=str(study_dir), PYTHONPATH="")
    return env


def toy_config(state_dir, **overrides):
    """The repo's toykit KitConfig, with its state under `state_dir` instead
    of DATA_ROOT, plus any field overrides (e.g. timeouts=...)."""
    import dataclasses
    import sys
    core = str(Path(__file__).resolve().parent.parent / "core")
    if core not in sys.path:
        sys.path.insert(0, core)
    import kit_registry
    base = kit_registry.NATIVE["toykit"]
    fields = {"set_env": {"TOYKIT_STATE_DIR": str(state_dir)}}
    fields.update(overrides)
    return dataclasses.replace(base, **fields)
