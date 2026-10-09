"""Builders shared by the tests: a minimal study on toykit, its file, a
toykit KitConfig that writes under a temp dir, a board holding given rows,
and the temp-dir and engine-subprocess test bases."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_STUDIES = Path(__file__).resolve().parent / "fixtures" / "engine_studies"

# A board row's V2_META cells.
META = {"handles": "toy=c1.toy", "spec_sha": "s" * 64,
        "measure_sha": "m" * 64, "time": "2026-09-24T00:00:00Z"}


def _core():
    """core/ on sys.path, for the bare imports the suite uses."""
    core = str(ROOT / "core")
    if core not in sys.path:
        sys.path.insert(0, core)


def toy_doc(name="toystudy", layout="v2"):
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
             "params_from": {}, "fixed": {"delay_s": 0.0}},
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


def toy_pre(name="toystudy", **kits):
    """toy_doc with a toykit pre-check, plus any toykit setting overrides
    (e.g. function="reject")."""
    doc = toy_doc(name)
    doc["preflight"] = {"kit": "toykit", "files": [], "params": {}}
    doc["kits"]["toykit"].update(kits)
    return doc


def toy_study(directory, mutate=None, **doc_kw):
    """toy_doc(**doc_kw), edited by `mutate`, written to `directory` and
    loaded."""
    _core()
    import study
    doc = toy_doc(**doc_kw)
    if mutate:
        mutate(doc)
    return study.load_study_file(write_study(doc, directory))


def write_board(study, path, *shas, header=None):
    """The study's board at `path`, holding one row per measure_sha in
    `shas` (every value cell 1.0), under `header` or the study's own."""
    _core()
    from leaderboard import Leaderboard
    lb = Leaderboard.for_study(study, path=Path(path), archive_path=None)
    cols = lb.header().rstrip("\n").split("\t")
    lines = [header or lb.header()]
    for i, sha in enumerate(shas):
        row = {c: "1.0" for c in cols}
        row.update(config=f"r{i}", handles="toy=x", spec_sha="s" * 64,
                   measure_sha=sha, time="2026-09-30T00:00:00Z")
        lines.append("\t".join(row[c] for c in cols) + "\n")
    lb.path.parent.mkdir(parents=True, exist_ok=True)
    lb.path.write_text("".join(lines))
    return lb


def board_rows(data, study):
    """The live board's rows of `study` under data root `data`, as dicts
    in column order."""
    path = data / "autoresearch_leaderboards" / f"leaderboard_{study}.tsv"
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


def submits(data):
    """The <config>.<step> names toykit was asked to submit, in order."""
    path = data / "toykit" / "submits.jsonl"
    return ([json.loads(ln)["name"] for ln in path.read_text().splitlines()]
            if path.exists() else [])


class Kits:
    """A kit set that hands out the one kit for every name."""

    def __init__(self, kit):
        self.kit = kit

    def get(self, name):
        return self.kit


class TmpCase(unittest.TestCase):
    """A fresh temp dir at self.tmp for each test, removed after it."""

    def setUp(self):
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)


class EngineCase(TmpCase):
    """studies/ (the study path) and data/ (the data root) in the temp dir,
    and self.env, the environment for an engine subprocess on them."""

    def setUp(self):
        super().setUp()
        self.studies = self.tmp / "studies"
        self.studies.mkdir()
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.env = engine_env(self.data, self.studies)


def toy_config(state_dir, **overrides):
    """The repo's toykit KitConfig, with its state under `state_dir` instead
    of DATA_ROOT, plus any field overrides (e.g. timeouts=...)."""
    import dataclasses
    _core()
    import kit_registry
    base = kit_registry.NATIVE["toykit"]
    fields = {"set_env": {"TOYKIT_STATE_DIR": str(state_dir)}}
    fields.update(overrides)
    return dataclasses.replace(base, **fields)
