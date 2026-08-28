# Prodtools Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Autoresearch stops owning job execution — build/run/watch goes through
prodtools (`json2jobdef` / `runlocal` / `submit_entry` / `jobwait`), deleting
`core/local_exec.py`, the mu2ejobdef/mu2ejobsub wrappers, `poll_cluster`, and
the outstage glob walkers, per
`docs/superpowers/specs/2026-08-16-prodtools-switch-design.md`.

**Architecture:** `pipeline.py` keeps its three verb surface (`submit | poll |
list-outputs`) so `graph/pipeline_io.run_stage`, `graph/nodes.py`, and the
closed-loop barrier are untouched. Each verb's body is rewired: `submit`
renders a per-(config, stage) prodtools entry JSON → `json2jobdef` → cnf →
`submit_entry` (grid) or `runlocal` (local); `poll` runs `jobwait`;
`list-outputs` reads the shared wait.json summary and writes
`state/<stage>_outputs.txt` exactly as before, so harvest and its
file-count denominators never change. A new seam module
`core/prodtools_exec.py` owns entry rendering + prodtools invocation.

**Tech Stack:** Python 3.11 stdlib only for new modules; unittest; prodtools
checkout located via env `AUTORESEARCH_PRODTOOLS`.

## Global Constraints

- Test command: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .` — suite must stay green with **zero grid contact** (no `jobsub_q`, no `jobsub_submit`, no /pnfs access; all prodtools invocations injected as fake runners).
- **Harvest and the metric extractors are untouched.** `cmd_harvest`, `hv.*`, `_extract_*` keep byte-identical behavior. Denominators stay `len(outputs) * events_per_job(stage)`.
- State-file contracts preserved verbatim: `state/<stage>_cluster.txt` (bare integer cluster id / local runid), `state/<stage>_outputs.txt`, `state/<stage>_events_per_job.txt`, `state/<stage>_config_sha.txt`, `state/<stage>_local.txt` marker semantics (marker ⇒ the int in cluster.txt is a runid).
- New state files (additive, grid only): `state/<stage>_jobsub_id.txt` (`NNNN@schedd`, what jobwait needs), `state/<stage>_wait.json` (the shared runlocal/jobwait summary), `state/<stage>_entry.json`.
- `AUTORESEARCH_PRODTOOLS` = path to the prodtools checkout. No hardcoded personal path in committed code; `core/paths.py` names the missing variable at verify time.
- Grid outstage root stays `/pnfs/mu2e/scratch/users/$USER/workflow/default/outstage` (prodtools `compute_outstage(wftop='/pnfs/mu2e/scratch/users', wfproject='default')` — same root the old `OUTSTAGE` constant pointed at; only the per-job layout below `<cluster>/` changes from `00/<00000>/` to `<proc>/`).
- Do NOT submit any grid job during implementation. The offline validation task uses `json2jobdef`/`jobfcl` only (interactive node, no submission). Live gates are operator-approved follow-ups outside this plan.
- `git add` explicit paths only; never push (operator pushes).
- Prodtools tasks (10) run in `/exp/mu2e/app/users/oksuzian/muse_050125/prodtools` on branch `code-tarball`; do not touch files the operator has in flight there (`test/test_unit.py`, `utils/runlocal.py`, `data/*`, `docs/EXAMPLES_schema.md`) except the named one-line `utils/runmu2e.py` edit; never hand-edit `EXAMPLES.md`.

## File Structure

- Create: `core/prodtools_exec.py` — entry rendering, prodtools CLI invocation (injected runners), wait.json reading. One responsibility: "talk to prodtools".
- Create: `core/prodtools_submit_driver.py` — standalone script run under the Mu2e env; imports prodtools `utils.submit` and calls `submit_entry`; prints a `SUBMIT_RESULT {json}` line.
- Create: `tests/test_prodtools_exec.py` — all new unit tests.
- Modify: `core/paths.py` — `PRODTOOLS` resolution + `verify()` entry.
- Modify: `core/pipeline.py` — rewire `cmd_submit` / `cmd_poll` / `cmd_list_outputs`; delete `_jobdef_cmd`, `submit_stage`, `poll_cluster`, `list_outputs`, `_probe_input_urls`, `_grid_setup_sh`, `cmd_local_build`, `cmd_local_run`, `local_job_env`, `_local_scale`, `_local_stage_inputs`, and the `local-build`/`local-run` argparse verbs.
- Modify: `graph/pipeline_io.py` — `_worker_log_paths` learns the direct-backend outstage layout.
- Delete: `core/local_exec.py`, `tests/test_local_exec.py`.
- Prodtools (separate repo): modify `utils/runmu2e.py` (one line + test) so `dir:` inlocs under `/pnfs/` stream via xrootd.

---

### Task 1: Prodtools location seam (`core/paths.py`)

**Files:**
- Modify: `core/paths.py`
- Test: `tests/test_prodtools_exec.py` (new file)

**Interfaces:**
- Produces: `paths.prodtools_root() -> Path` — raises `SystemExit` naming `AUTORESEARCH_PRODTOOLS` when unset or not a directory containing `bin/json2jobdef`. Later tasks call this for every prodtools invocation.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prodtools_exec.py
"""Unit tests for the prodtools execution seam (core/prodtools_exec.py).

Zero grid contact: every prodtools invocation is an injected fake runner.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths


class TestProdtoolsRoot(unittest.TestCase):
    def test_unset_env_names_the_variable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTORESEARCH_PRODTOOLS", None)
            with self.assertRaises(SystemExit) as cm:
                paths.prodtools_root()
            self.assertIn("AUTORESEARCH_PRODTOOLS", str(cm.exception))

    def test_valid_checkout_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bin").mkdir()
            (Path(td) / "bin" / "json2jobdef").touch()
            with mock.patch.dict(os.environ,
                                 {"AUTORESEARCH_PRODTOOLS": td}):
                self.assertEqual(paths.prodtools_root(), Path(td))

    def test_dir_without_json2jobdef_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ,
                                 {"AUTORESEARCH_PRODTOOLS": td}):
                with self.assertRaises(SystemExit):
                    paths.prodtools_root()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_prodtools_exec -v`
Expected: FAIL — `AttributeError: module 'paths' has no attribute 'prodtools_root'`

- [ ] **Step 3: Implement in `core/paths.py`** (append, following the module's existing style):

```python
def prodtools_root() -> Path:
    """The prodtools checkout, from env AUTORESEARCH_PRODTOOLS.

    Env-resolved, never a hardcoded personal path (9f0c43c convention).
    Checked for bin/json2jobdef so a typo fails at the seam, not three
    subprocesses deep inside a stage submit.
    """
    root = os.environ.get("AUTORESEARCH_PRODTOOLS")
    if not root:
        raise SystemExit(
            "AUTORESEARCH_PRODTOOLS is not set -- export it to the "
            "prodtools checkout (the directory holding bin/json2jobdef)")
    root = Path(root)
    if not (root / "bin" / "json2jobdef").exists():
        raise SystemExit(
            f"AUTORESEARCH_PRODTOOLS={root} has no bin/json2jobdef -- "
            f"not a prodtools checkout")
    return root
```

- [ ] **Step 4: Run tests → PASS, run full suite → green**
- [ ] **Step 5: Commit**

```bash
git add core/paths.py tests/test_prodtools_exec.py
git commit -m "feat(prodtools-switch): AUTORESEARCH_PRODTOOLS resolution seam"
```

---

### Task 2: Entry rendering (`core/prodtools_exec.py`)

**Files:**
- Create: `core/prodtools_exec.py`
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Consumes: `paths.prodtools_root()` (Task 1).
- Produces:
  - `render_entry(stage, stage_cfg, *, config, dsconf, desc, njobs, code_tarball, fcl_name, events=None, run=None, memory_mb=None, input_data=None, inloc=None, resampler_name=None) -> dict`
  - `write_entry(state_dir: Path, stage: str, entry: dict) -> Path` — writes `state/<stage>_entry.json` as a one-element JSON list (json2jobdef's file shape).
  - `WFTOP = "/pnfs/mu2e/scratch/users"`, `WFPROJECT = "default"`, `outstage_root() -> str`.

**Entry shapes** (the target output — from prodtools `EXAMPLES.md` §3; every
stage is code-mode: the per-config `Code.<base>.tar.bz2` from
`write_code_tarball` ships geom + the materialized template FCL, and its
`setup_post.sh` puts the Code dir on `MU2E_SEARCH_PATH`/`FHICL_FILE_PATH`, so
`fcl` is the template's *basename*):

| stage | extra fields |
|---|---|
| mubeam / run1b_mubeam | `resampler_name: "beamResampler"`, `input_data: {"sim.mu2e.MuBeamCat.Run1Baa.art": 1}`, `inloc: "tape"`, `events`, `run` |
| elebeam_flash | same with `"sim.mu2e.EleBeamCat.Run1Baa.art"` |
| concat | `input_data: {<basename>: <merge_factor> ...}`, `inloc: "dir:<staged>"` (no events/run) |
| mustops_ce | `resampler_name: "TargetStopResampler"`, `input_data: {<basename>: 1 ...}`, `inloc: "dir:<staged>"`, `events`, `run` |

All entries: `outloc: {"*.art": "outstage", "*.root": "outstage"}`,
`owner: USER`, `code: str(code_tarball)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_prodtools_exec.py`):

```python
import prodtools_exec as pex


class TestRenderEntry(unittest.TestCase):
    def _base(self, **kw):
        args = dict(config="t001", dsconf="Run1Bak_t001",
                    desc="Run1A_MuBeam_t001", njobs=200,
                    code_tarball=Path("/data/t001/Code.tar.bz2"),
                    fcl_name="mubeam_template_materialized.fcl")
        args.update(kw)
        return args

    def test_resampler_stage_shape(self):
        e = pex.render_entry(
            "mubeam", {}, **self._base(
                events=5000, run=1800,
                resampler_name="beamResampler",
                input_data={"sim.mu2e.MuBeamCat.Run1Baa.art": 1},
                inloc="tape"))
        self.assertEqual(e["desc"], "Run1A_MuBeam_t001")
        self.assertEqual(e["dsconf"], "Run1Bak_t001")
        self.assertEqual(e["fcl"], "mubeam_template_materialized.fcl")
        self.assertEqual(e["code"], "/data/t001/Code.tar.bz2")
        self.assertEqual(e["events"], 5000)
        self.assertEqual(e["run"], 1800)
        self.assertEqual(e["resampler_name"], "beamResampler")
        self.assertEqual(e["inloc"], "tape")
        self.assertEqual(e["outloc"],
                         {"*.art": "outstage", "*.root": "outstage"})
        self.assertNotIn("simjob_setup", e)   # exactly one Offline source

    def test_merge_stage_no_events(self):
        e = pex.render_entry(
            "concat", {}, **self._base(
                desc="Run1A_MuStopsCat_t001", njobs=1,
                input_data={"sim.a.art": 200, "sim.b.art": 200},
                inloc="dir:/pnfs/stage/t001/concat_inputs"))
        self.assertNotIn("events", e)
        self.assertNotIn("run", e)
        self.assertNotIn("resampler_name", e)
        self.assertEqual(e["inloc"], "dir:/pnfs/stage/t001/concat_inputs")

    def test_memory_formatted(self):
        e = pex.render_entry("mustops_ce", {},
                             **self._base(memory_mb=3000, events=2500,
                                          run=1801))
        self.assertEqual(e["memory"], "3000MB")

    def test_write_entry_is_one_element_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = pex.write_entry(Path(td), "mubeam", {"desc": "d"})
            self.assertEqual(p.name, "mubeam_entry.json")
            data = json.loads(p.read_text())
            self.assertEqual(data, [{"desc": "d"}])


class TestOutstageRoot(unittest.TestCase):
    def test_matches_legacy_constant(self):
        self.assertEqual(
            pex.outstage_root(),
            f"/pnfs/mu2e/scratch/users/{pex.USER}/workflow/default/outstage")
```

- [ ] **Step 2: Run → FAIL (no module `prodtools_exec`)**
- [ ] **Step 3: Implement** `core/prodtools_exec.py`:

```python
"""Prodtools execution seam: entry rendering + tool invocation.

Everything autoresearch says to prodtools goes through this module:
render a json2jobdef entry, build the cnf, run it (runlocal), submit it
(submit_entry via core/prodtools_submit_driver.py), wait on it (jobwait),
and read back the shared wait.json summary. pipeline.py's verbs call in;
nothing here knows about modes, leaderboards, or harvest.

Spec: docs/superpowers/specs/2026-08-16-prodtools-switch-design.md.
"""
import getpass
import json
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from paths import prodtools_root

USER = os.environ.get("USER") or getpass.getuser()

# Same outstage root the mu2ejobsub era used (pipeline.py OUTSTAGE);
# prodtools computes it as {wftop}/{user}/workflow/{wfproject}/outstage.
WFTOP = "/pnfs/mu2e/scratch/users"
WFPROJECT = "default"


def outstage_root() -> str:
    return f"{WFTOP}/{USER}/workflow/{WFPROJECT}/outstage"


def render_entry(stage, stage_cfg, *, config, dsconf, desc, njobs,
                 code_tarball, fcl_name, events=None, run=None,
                 memory_mb=None, input_data=None, inloc=None,
                 resampler_name=None) -> dict:
    """One json2jobdef entry dict for a (config, stage).

    Code-mode for every stage: the per-config Code tarball ships the
    geom AND the materialized template, whose basename is `fcl` -- the
    worker resolves it via the tarball's setup_post.sh search path, so
    grid and local read the identical FCL (the env-divergence class of
    incidents is closed by construction, not by care).
    """
    entry = {
        "desc": desc,
        "dsconf": dsconf,
        "owner": USER,
        "fcl": fcl_name,
        "code": str(code_tarball),
        "njobs": njobs,
        "outloc": {"*.art": "outstage", "*.root": "outstage"},
    }
    if events is not None:
        entry["events"] = events
        entry["run"] = run
    if memory_mb is not None:
        entry["memory"] = f"{memory_mb}MB"
    if input_data is not None:
        entry["input_data"] = input_data
        entry["inloc"] = inloc
    if resampler_name is not None:
        entry["resampler_name"] = resampler_name
    return entry


def write_entry(state_dir: Path, stage: str, entry: dict) -> Path:
    """state/<stage>_entry.json, as the one-element list json2jobdef reads."""
    out = state_dir / f"{stage}_entry.json"
    out.write_text(json.dumps([entry], indent=1) + "\n")
    return out
```

- [ ] **Step 4: Run tests → PASS; full suite → green**
- [ ] **Step 5: Commit** (`git add core/prodtools_exec.py tests/test_prodtools_exec.py`)

---

### Task 3: wait.json contract + `cmd_list_outputs` rewire

**Files:**
- Modify: `core/prodtools_exec.py`, `core/pipeline.py:1291-1313` (`cmd_list_outputs`)
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Produces:
  - `read_wait(state_dir: Path, stage: str) -> dict` — loads `state/<stage>_wait.json`; `SystemExit` naming the path when missing (a missing summary means the runner died before reporting — never "zero jobs ran").
  - `outputs_from_wait(wait: dict, output_glob: str) -> list[str]` — output paths of **rc == 0 jobs only**, basename-filtered by `output_glob`; entries in a job's `outputs` that are relative are joined onto that job's `dir` (runlocal shape).
- The wait.json schema (both producers): top-level `jobs` (list of `{index, rc, outputs, ...}`), `ok` (int), `failed` (list). jobwait adds `unknown` (list) and `cluster`; runlocal adds `dir`/`log`/`seconds`. Consumers key only on the shared core.

- [ ] **Step 1: Write the failing tests:**

```python
_WAIT_GRID = {
    "jobdef": "cnf.t.tar", "cluster": "777@jobsub01.fnal.gov",
    "jobs": [
        {"index": 0, "proc": 0, "rc": 0,
         "outputs": ["/pnfs/out/777/0/sim.u.D.C.0.art"]},
        {"index": 1, "proc": 1, "rc": 1,
         "outputs": ["/pnfs/out/777/1/sim.u.D.C.1.art"]},
        {"index": 2, "proc": 2, "rc": None,
         "outputs": ["/pnfs/out/777/2/sim.u.D.C.2.art"]},
    ],
    "ok": 1, "failed": [1], "unknown": [2],
}

_WAIT_LOCAL = {
    "jobdef": "cnf.t.tar",
    "jobs": [
        {"index": 0, "rc": 0, "dir": "/data/local/j0",
         "outputs": ["sim.u.D.C.0.art", "nts.u.D.C.0.root"]},
        {"index": 1, "rc": 137, "dir": "/data/local/j1",
         "outputs": ["sim.u.D.C.1.art"]},
    ],
    "ok": 1, "failed": [1],
}


class TestWaitContract(unittest.TestCase):
    def test_ok_jobs_only(self):
        outs = pex.outputs_from_wait(_WAIT_GRID, "sim.*.art")
        self.assertEqual(outs, ["/pnfs/out/777/0/sim.u.D.C.0.art"])

    def test_unknown_is_not_ok(self):
        # rc None (condor history had no record) must never count as done.
        outs = pex.outputs_from_wait(_WAIT_GRID, "sim.*.art")
        self.assertNotIn("/pnfs/out/777/2/sim.u.D.C.2.art", outs)

    def test_glob_filters_secondary_streams(self):
        outs = pex.outputs_from_wait(_WAIT_LOCAL, "sim.*.art")
        self.assertEqual(outs, ["/data/local/j0/sim.u.D.C.0.art"])

    def test_relative_outputs_join_job_dir(self):
        outs = pex.outputs_from_wait(_WAIT_LOCAL, "nts.*.root")
        self.assertEqual(outs, ["/data/local/j0/nts.u.D.C.0.root"])

    def test_read_wait_missing_is_systemexit(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                pex.read_wait(Path(td), "mubeam")

    def test_contract_core_keys_shared(self):
        # The "same JSON either way" claim, pinned: consumers may key on
        # these and only these.
        for fx in (_WAIT_GRID, _WAIT_LOCAL):
            self.assertLessEqual({"jobdef", "jobs", "ok", "failed"},
                                 set(fx))
            for j in fx["jobs"]:
                self.assertLessEqual({"index", "rc", "outputs"}, set(j))
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement in `core/prodtools_exec.py`:**

```python
def wait_json_path(state_dir: Path, stage: str) -> Path:
    return state_dir / f"{stage}_wait.json"


def read_wait(state_dir: Path, stage: str) -> dict:
    p = wait_json_path(state_dir, stage)
    if not p.exists():
        raise SystemExit(
            f"[{stage}] {p} missing -- the runner (runlocal/jobwait) died "
            f"before writing its summary; re-run 'poll {stage}'")
    return json.loads(p.read_text())


def outputs_from_wait(wait: dict, output_glob: str) -> list[str]:
    """Output paths of jobs that exited 0, filtered to the stage's glob.

    rc None (unknown -- condor history had no record) is NOT ok: an
    unverifiable job never contributes files to harvest denominators.
    """
    outs = []
    for job in wait.get("jobs", []):
        if job.get("rc") != 0:
            continue
        for o in job.get("outputs", []):
            if not fnmatch(Path(o).name, output_glob):
                continue
            if not os.path.isabs(o) and job.get("dir"):
                o = str(Path(job["dir"]) / o)
            outs.append(o)
    return sorted(outs)
```

- [ ] **Step 4: Rewire `cmd_list_outputs`** in `core/pipeline.py` — replace the body after the existing idempotency guard (keep the guard and `_check_stage_config_sha` exactly as they are; delete the `_is_local_stage` branch and the `list_outputs(...)` call):

```python
def cmd_list_outputs(args):
    _check_stage_config_sha(args.stage)
    # Idempotency guard: unchanged (existing lines).
    outputs_file = STATE / f"{args.stage}_outputs.txt"
    if outputs_file.exists() and not getattr(args, "force", False):
        paths_ = [p for p in outputs_file.read_text().splitlines() if p.strip()]
        if paths_ and all(Path(p).exists() for p in paths_):
            print(f"[{args.stage}] outputs already listed ({len(paths_)} files); "
                  f"skip (use --force to override)")
            return
    # One code path for grid and local -- both executors write the same
    # wait.json (spec decision 5), so "where did the files land" has one
    # reader instead of the old glob-walker pair.
    wait = px.read_wait(STATE, args.stage)
    files = px.outputs_from_wait(wait, STAGES[args.stage]["output_glob"])
    outputs_file.write_text("\n".join(files) + "\n")
    print(f"[{args.stage}] {len(files)} output file(s) "
          f"(ok={wait.get('ok')}, failed={wait.get('failed')}, "
          f"unknown={wait.get('unknown', [])}) -> {outputs_file}")
```

with `import prodtools_exec as px` added at the top of `pipeline.py`.

- [ ] **Step 5: Add a pipeline-level test** (same test file) — write a fake
`state/` tree with `mubeam_wait.json` = `_WAIT_GRID`, call
`pipeline.cmd_list_outputs` via `pipeline._bind_config` on a tmp `DATA_ROOT`
(follow the existing pattern in `tests/test_pipeline_*.py` for binding), and
assert `mubeam_outputs.txt` contains exactly the one ok path. Name it
`TestListOutputsFromWait.test_outputs_txt_has_ok_jobs_only`.
- [ ] **Step 6: Full suite → green (old grid tests still pass because `list_outputs`/`poll_cluster` are not deleted until Task 9). Commit.**

---

### Task 4: Grid submit via prodtools `submit_entry`

**Files:**
- Create: `core/prodtools_submit_driver.py`
- Modify: `core/prodtools_exec.py`, `core/pipeline.py` (`cmd_submit` grid branch, replacing the `submit_stage` call)
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Produces:
  - `build_cnf(stage_dir, entry_path, desc, dsconf, env, runner=subprocess.run) -> Path` — runs `<prodtools>/bin/json2jobdef --json <entry_path> --desc <desc> --dsconf <dsconf>` with `cwd=stage_dir`; returns `stage_dir / f"cnf.{USER}.{desc}.{dsconf}.0.tar"`; `SystemExit` on rc != 0 (stderr surfaced — c2b154d convention).
  - `submit_cnf(stage_dir, entry_path, ledger_db, origin, env, runner=subprocess.run) -> tuple[int, str]` — runs the driver script under the sourced env, parses the `SUBMIT_RESULT {…}` line, returns `(cluster_id, jobsub_id)`; `SystemExit` with the driver's stderr when no cluster id came back (no reservation leak — the driver's `submit_entry` closes the ledger row on failure).
  - Ledger path: `DATA_ROOT / "prodtools_ledger" / "submissions.db"` (runtime state on /data, 9f0c43c convention).
- Driver contract: `python3 core/prodtools_submit_driver.py --prodtools <root> --entry <entry.json> --ledger <db> --origin <text> [--dry-run]`, run with `cwd=<stage_dir>` (submit_entry resolves the cnf tarball relative to cwd). Prints exactly one `SUBMIT_RESULT ` line with `{"cluster_id": ..., "jobsub_id": ..., "status": ...}`.

- [ ] **Step 1: Write the failing tests:**

```python
class TestSubmitCnf(unittest.TestCase):
    def _runner(self, stdout, rc=0, stderr=""):
        def run(cmd, **kw):
            self.last_cmd = cmd
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
        return run

    def test_parses_submit_result(self):
        out = ('noise\nSUBMIT_RESULT {"cluster_id": 86123999, '
               '"jobsub_id": "86123999.0@jobsub01.fnal.gov", '
               '"status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td:
            cluster, jobsub_id = pex.submit_cnf(
                Path(td), Path(td) / "e.json", Path(td) / "l.db",
                "autoresearch:t001/mubeam", {}, runner=self._runner(out))
        self.assertEqual(cluster, 86123999)
        # jobwait wants NNNN@schedd -- proc stripped, schedd kept.
        self.assertEqual(jobsub_id, "86123999@jobsub01.fnal.gov")

    def test_no_result_line_is_systemexit(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                pex.submit_cnf(Path(td), Path(td) / "e.json",
                               Path(td) / "l.db", "o", {},
                               runner=self._runner("boom", rc=1,
                                                   stderr="ledger sad"))

    def test_driver_cmd_shape(self):
        out = ('SUBMIT_RESULT {"cluster_id": 1, '
               '"jobsub_id": "1.0@s", "status": "submitted"}\n')
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"AUTORESEARCH_PRODTOOLS": td}):
            (Path(td) / "bin").mkdir(); (Path(td) / "bin" / "json2jobdef").touch()
            pex.submit_cnf(Path(td), Path(td) / "e.json", Path(td) / "l.db",
                           "o", {}, runner=self._runner(out))
        joined = " ".join(str(c) for c in self.last_cmd)
        self.assertIn("prodtools_submit_driver.py", joined)
        self.assertIn("--entry", joined)
        self.assertIn("--ledger", joined)
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement.** Driver (`core/prodtools_submit_driver.py`):

```python
#!/usr/bin/env python3
"""Submit one rendered entry through prodtools submit_entry.

Runs under the sourced Mu2e env (prodtools utils import samweb_client),
cwd = the stage dir holding the cnf tarball. Prints one line:
SUBMIT_RESULT {"cluster_id": ..., "jobsub_id": ..., "status": ...}
The ledger row lifecycle (reserve -> attach / fail) is submit_entry's
own -- a failed submission closes its reservation before we exit.
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prodtools", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--origin", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, args.prodtools)
    from utils import submission_ledger
    from utils.submit import SubmitOptions, submit_entry

    entry = json.loads(open(args.entry).read())[0]
    ledger_db = submission_ledger.ensure_ledger_dir(args.ledger)
    opts = SubmitOptions(ledger_db=ledger_db, dry_run=args.dry_run,
                         origin=args.origin,
                         wftop="/pnfs/mu2e/scratch/users",
                         wfproject="default")
    result = submit_entry(entry, 0, opts)
    print("SUBMIT_RESULT " + json.dumps({
        "cluster_id": result.get("cluster_id"),
        "jobsub_id": result.get("jobsub_id"),
        "status": result.get("status"),
    }), flush=True)
    return 0 if result.get("cluster_id") else 1


if __name__ == "__main__":
    sys.exit(main())
```

(Implementation note for the implementer: verify
`submission_ledger.ensure_ledger_dir`'s signature in the prodtools checkout
before relying on it — if it only takes the default path, create the parent
directory in the driver and pass `args.ledger` straight to `SubmitOptions`.
The result dict keys `cluster_id`/`jobsub_id`/`status` come from
`utils/submit.py submit_entry`; confirm the exact key names there.)

`core/prodtools_exec.py` additions:

```python
def build_cnf(stage_dir, entry_path, desc, dsconf, env,
              runner=subprocess.run) -> Path:
    cmd = [str(prodtools_root() / "bin" / "json2jobdef"),
           "--json", str(entry_path), "--desc", desc, "--dsconf", dsconf]
    res = runner(cmd, cwd=str(stage_dir), env=env,
                 capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"json2jobdef failed rc={res.returncode}:\n"
                         f"{res.stdout}\n{res.stderr}")
    cnf = Path(stage_dir) / f"cnf.{USER}.{desc}.{dsconf}.0.tar"
    if not cnf.exists():
        raise SystemExit(f"json2jobdef succeeded but {cnf} is missing")
    return cnf


def submit_cnf(stage_dir, entry_path, ledger_db, origin, env,
               runner=subprocess.run, dry_run=False) -> tuple[int, str]:
    driver = Path(__file__).resolve().parent / "prodtools_submit_driver.py"
    cmd = ["python3", str(driver),
           "--prodtools", str(prodtools_root()),
           "--entry", str(entry_path), "--ledger", str(ledger_db),
           "--origin", origin]
    if dry_run:
        cmd.append("--dry-run")
    res = runner(cmd, cwd=str(stage_dir), env=env,
                 capture_output=True, text=True)
    for line in (res.stdout or "").splitlines():
        if line.startswith("SUBMIT_RESULT "):
            data = json.loads(line[len("SUBMIT_RESULT "):])
            if data.get("cluster_id"):
                jobsub = data.get("jobsub_id") or ""
                # NNNN.P@schedd -> NNNN@schedd (what jobwait wants).
                cluster = int(data["cluster_id"])
                schedd = jobsub.split("@", 1)[1] if "@" in jobsub else ""
                jid = f"{cluster}@{schedd}" if schedd else str(cluster)
                return cluster, jid
    raise SystemExit(f"prodtools submit failed rc={res.returncode}:\n"
                     f"{res.stdout}\n{res.stderr}")
```

- [ ] **Step 4: Rewire the grid branch of `cmd_submit`** (`core/pipeline.py`): keep everything up to and including the input-staging block (`stage_hardlink_farm` calls) and the stage-chain stamp; then replace `submit_stage(...)` with a new `submit_stage_prodtools(stage, env, staged=...)` in `pipeline.py`:

```python
def submit_stage_prodtools(stage, env, *, staged_inputs=None,
                           dry_run=False) -> int | None:
    """Entry -> json2jobdef -> submit_entry. Returns the cluster id.

    staged_inputs: (staged_dir, {basename: merge_or_count}) for
    consuming stages, None otherwise. Writes the same state files the
    mu2ejobsub path wrote (cluster.txt, events stamp, config sha) plus
    the jobsub id for jobwait.
    """
    cfg = STAGES[stage]
    desc, dsconf = _stage_desc(stage), _stage_dsconf(stage)
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    template_fcl = _materialize_template(stage)
    tarball = write_code_tarball(
        stage_dir,
        base_tarball=Path(cfg["code_tarball"]) if "code_tarball" in cfg else None,
        extra_files=[template_fcl])
    entry = px.render_entry(
        stage, cfg, config=CONFIG, dsconf=dsconf, desc=desc,
        njobs=cfg["njobs"], code_tarball=tarball,
        fcl_name=template_fcl.name,
        events=cfg.get("events_per_job"), run=cfg.get("run_number"),
        memory_mb=cfg.get("memory_mb"),
        input_data=(staged_inputs[1] if staged_inputs else _cat_input_data(stage)),
        inloc=(f"dir:{staged_inputs[0]}" if staged_inputs
               else cfg.get("default_loc")),
        resampler_name=_resampler_name(stage))
    entry_path = px.write_entry(STATE, stage, entry)
    cnf = px.build_cnf(stage_dir, entry_path, desc, dsconf, env)
    if "events_per_job" in cfg:
        stamp_local_events(stage, cfg["events_per_job"])
    if dry_run:
        print(f"[{stage}] DRY-RUN: cnf built, not submitted: {cnf.name}")
        return None
    with _submit_lock(stage):
        _maybe_refresh_token(stage)
        cluster, jobsub_id = px.submit_cnf(
            stage_dir, entry_path, LEDGER_DB,
            f"autoresearch:{CONFIG}/{stage}", env)
    (STATE / f"{stage}_cluster.txt").write_text(f"{cluster}\n")
    (STATE / f"{stage}_jobsub_id.txt").write_text(f"{jobsub_id}\n")
    _stamp_stage_config_sha(stage)
    print(f"[{stage}] cluster={cluster} ({jobsub_id})")
    return cluster
```

with module-level helpers + constant:

```python
LEDGER_DB = DATA_ROOT / "prodtools_ledger" / "submissions.db"

# Static resampler wiring per stage (was mu2ejobdef --auxinput).
_RESAMPLER_BY_STAGE = {
    "mubeam": ("beamResampler", {"sim.mu2e.MuBeamCat.Run1Baa.art": 1}, None),
    "run1b_mubeam": ("beamResampler",
                     {"sim.mu2e.MuBeamCat.Run1Baa.art": 1}, None),
    "elebeam_flash": ("beamResampler",
                      {"sim.mu2e.EleBeamCat.Run1Baa.art": 1}, None),
    "mustops_ce": ("TargetStopResampler", None, None),  # input_data staged
}

def _resampler_name(stage):
    return _RESAMPLER_BY_STAGE.get(stage, (None,))[0]

def _cat_input_data(stage):
    """Static Cat-dataset input_data for resampler stages; the inloc is
    the stage's default_loc (tape since the 2026-07 migrations)."""
    ent = _RESAMPLER_BY_STAGE.get(stage)
    return ent[1] if ent else None
```

`write_code_tarball` grows an optional `extra_files: list[Path]` parameter
appending the materialized template beside the geom inside the tarball's
Code dir (same mechanism that already ships the geom; ~4 lines).
`cmd_submit`'s consuming-stage blocks change their `submit_stage(...)` call
to `submit_stage_prodtools(stage, env, staged_inputs=(staged_dir, input_map))`,
where `input_map` is `{basename: merge_factor}` for concat
(`cfg["merge_factor"]` per file) and `{basename: 1}` for mustops_ce.

- [ ] **Step 5: Tests for the rewired submit** — fake runners for
`json2jobdef` (touch the expected cnf path) and the driver (emit
`SUBMIT_RESULT`), tmp DATA_ROOT; assert: `mubeam_cluster.txt` holds the bare
int, `mubeam_jobsub_id.txt` holds `NNNN@schedd`, events stamp written,
entry JSON on disk matches the Task 2 golden. Name:
`TestSubmitStageProdtools.test_state_files_written`.
- [ ] **Step 6: Full suite → green. Commit.**

---

### Task 5: `cmd_poll` via jobwait

**Files:**
- Modify: `core/prodtools_exec.py`, `core/pipeline.py:1280-1288` (`cmd_poll`)
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Produces: `run_jobwait(stage_dir, cnf, jobid, njobs, wait_json, env, runner=subprocess.run, poll_s=300) -> int` — invokes `<prodtools>/bin/jobwait --jobdef <cnf> --cluster <jobid> --njobs <njobs> --outstage <outstage_root()> --poll-s <poll_s> --json <wait_json>`; returns the process rc (0 = all ok; nonzero = partial — NOT an error here: acceptance is ours).

- [ ] **Step 1: Failing tests:** command shape (all six flags present, `--outstage` = `outstage_root()`); nonzero rc returns (not raises); missing wait.json after run → `SystemExit`.
- [ ] **Step 2: Implement:**

```python
def run_jobwait(stage_dir, cnf, jobid, njobs, wait_json, env,
                runner=subprocess.run, poll_s=300) -> int:
    cmd = [str(prodtools_root() / "bin" / "jobwait"),
           "--jobdef", str(cnf), "--cluster", str(jobid),
           "--njobs", str(njobs), "--outstage", outstage_root(),
           "--poll-s", str(poll_s), "--json", str(wait_json)]
    res = runner(cmd, cwd=str(stage_dir), env=env)
    if not Path(wait_json).exists():
        raise SystemExit(
            f"jobwait exited rc={res.returncode} without writing "
            f"{wait_json} -- it died before the cluster drained")
    return res.returncode
```

- [ ] **Step 3: Rewire `cmd_poll`:**

```python
def cmd_poll(args):
    if _is_local_stage(args.stage):
        print(f"[{args.stage}] local mode: jobs already complete; poll is a no-op")
        return
    _check_stage_config_sha(args.stage)
    cfg = STAGES[args.stage]
    stage_dir = ROOT / args.stage
    jid_file = STATE / f"{args.stage}_jobsub_id.txt"
    jobid = (jid_file.read_text().strip() if jid_file.exists()
             else (STATE / f"{args.stage}_cluster.txt").read_text().strip())
    cnf = stage_dir / f"cnf.{USER}.{_stage_desc(args.stage)}.{_stage_dsconf(args.stage)}.0.tar"
    px.run_jobwait(stage_dir, cnf, jobid, cfg["njobs"],
                   px.wait_json_path(STATE, args.stage), sourced_env())
    # Acceptance is autoresearch policy, not the tool's (spec): a partial
    # cluster proceeds -- harvest divides by the true ok count -- but a
    # below-quorum stage is loud, and zero ok jobs fails the stage here
    # (same behavior the old convergence gate's failure-aware exit had).
    wait = px.read_wait(STATE, args.stage)
    quorum = args.quorum if args.quorum is not None else cfg.get("quorum", 0.9)
    target = max(1, int(cfg["njobs"] * quorum))
    if wait["ok"] == 0:
        raise SystemExit(
            f"[{args.stage}] 0/{cfg['njobs']} jobs succeeded "
            f"(failed={wait.get('failed')}, unknown={wait.get('unknown')})")
    if wait["ok"] < target:
        print(f"[{args.stage}] WARN: {wait['ok']}/{cfg['njobs']} ok "
              f"(< quorum target {target}); proceeding with what landed")
```

(Note: `--cap-hours` disappears as a poll knob — jobwait has no internal
timeout by design; the closed-loop barrier timeout is the backstop. Keep the
argparse flag accepted-but-ignored with a deprecation print until Task 9
removes it, so in-flight tooling doesn't break mid-plan.)

- [ ] **Step 4: Tests:** fake jobwait runner that writes `_WAIT_GRID`-shaped
JSON: (a) ok≥target proceeds silently, (b) 0 ok → `SystemExit`, (c) partial
prints WARN and proceeds, (d) local marker → no-op without invoking the
runner. Full suite green. **Commit.**

---

### Task 6: Local mode via runlocal

**Files:**
- Modify: `core/prodtools_exec.py`, `core/pipeline.py` (`cmd_submit` local branch)
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Produces: `run_runlocal(stage_dir, cnf, njobs, wait_json, env, *, code_tarball, inloc=None, pool=4, runner=subprocess.run) -> int` — invokes `<prodtools>/bin/runlocal --jobdef <cnf> --first 0 --num <njobs> -j <pool> --workdir <stage_dir>/local --code <code_tarball> --json <wait_json>` plus `--inloc <inloc>` when given (`dir:<local farm>` for consuming stages; the entry's events are baked into the cnf, so no `--nevts`).
- `cmd_submit`'s local branch (replacing `cmd_local_build(args); cmd_local_run(args)`):
  1. `_require_local_stage(stage)` (kept, minus the `lx` references)
  2. resolve `njobs, events` from `--local-njobs/--local-events` flags + `AUTORESEARCH_LOCAL_NJOBS/EVENTS` env seams (inline the two-line resolver; `local_exec.resolve_scale/scale_default` die with the module — reimplement as a ~10-line `_local_scale` in pipeline.py without the lx dependency)
  3. render entry with the LOCAL njobs/events (merge factor clamped `min(cfg["merge_factor"], n_inputs)` for concat), build cnf via `px.build_cnf`
  4. write marker FIRST then runid to cluster.txt (runid = `1`; with runlocal owning execution there is no run-numbering to manage — the marker file is what carries "local", and the cluster file just needs a parseable int; keep the marker-first write ordering comment)
  5. `stamp_local_events(stage, events)`
  6. `px.run_runlocal(...)`; wait.json lands at `state/<stage>_wait.json` — the SAME file the grid path writes, which is what makes `cmd_list_outputs` executor-blind.

- [ ] **Step 1: Failing tests:** command shape (`--num`, `--json`, `--code` present); local branch writes marker before cluster.txt (assert both exist and cluster.txt == "1"); `cmd_poll` no-ops on the marker; `cmd_list_outputs` then reads the runlocal-shaped wait.json fixture and writes outputs.txt (reuses Task 3 machinery).
- [ ] **Step 2: Implement; full suite → green. Commit.**

---

### Task 7: Input staging for consuming stages, both executors

**Files:**
- Modify: `core/pipeline.py` (`cmd_submit` staging blocks; new `local_input_farm`)
- Test: `tests/test_prodtools_exec.py`

**Interfaces:**
- Grid: `stage_hardlink_farm(stage, sources)` — **kept verbatim** (flat /pnfs dir + basenames). Its `(staged_dir, inputs_file)` return feeds `staged_inputs=(staged_dir, input_map)` where `input_map = {Path(p).name: cfg.get("merge_factor", 1) for p in sources}`.
- Local: new `local_input_farm(stage, sources) -> tuple[Path, dict]` — hard-links (falls back to copy across filesystems) the previous stage's outputs into `ROOT/<stage>/local_inputs/`, returns `(dir, {basename: merge_or_1})`. The entry then carries `inloc: f"dir:{dir}"` — `runmu2e` reads `dir:` POSIX locally, which is correct on an interactive node.
- The previous-stage resolution keeps the existing rules verbatim: concat ← mubeam; mustops_ce ← mubeam-or-concat via `hv.concatless(STATE, CONCATLESS)` (stamp-first). Local requires the previous stage's `local` marker (the old `_local_stage_inputs` refusal, minus the `lx` calls).

- [ ] **Step 1: Failing tests:** `local_input_farm` links N files flat and returns basenames map; concat input_map carries the clamped merge factor (`min(200, n_sources)`); mustops_ce map values are all 1; local mustops_ce refuses when mubeam has no local marker (`SystemExit`).
- [ ] **Step 2: Implement; suite green; commit.**

---

### Task 8: scan_logs learns the direct-backend outstage layout

**Files:**
- Modify: `graph/pipeline_io.py` (`_worker_log_paths`)
- Test: `tests/test_prodtools_exec.py` (or the existing scan-logs test file if one covers `_worker_log_paths` — extend in place)

The old layout was `<OUTSTAGE>/<cluster>/00/<00000>/*.log`; prodtools direct
writes `<outstage>/<cluster>/<proc>/*.log` (flat proc dirs, no `00/`
sublevel). `_worker_log_paths` must glob BOTH shapes (old first for legacy
configs, then flat) and return whichever is non-empty.

- [ ] **Step 1: Read the current `_worker_log_paths` body (`graph/pipeline_io.py:305`) and write a failing test:** build a tmp tree `<root>/<cluster>/3/foo.log` (flat) and `<root>/<cluster>/00/00003/bar.log` (legacy); assert each is found by the function pointed at that root.
- [ ] **Step 2: Implement the two-shape glob; suite green; commit.**

---

### Task 9: The deletion sweep

**Files:**
- Delete: `core/local_exec.py`, `tests/test_local_exec.py`
- Modify: `core/pipeline.py`, `core/paths.py` (drop dead constants), `README.md`

- [ ] **Step 1: Delete from `core/pipeline.py`** (current line anchors): `_jobdef_cmd` (712), `submit_stage` (753), `poll_cluster` (841), `list_outputs` (915), `_probe_input_urls` (603), `_grid_setup_sh` (579), `_local_stage_inputs` (1017), `cmd_local_build` (1106), `cmd_local_run` (1160), `local_job_env` (1141), `_local_scale`'s lx-based body (1089 — replaced in Task 6), the `import local_exec as lx` line, the `local-build`/`local-run` argparse verbs and the deprecated `--cap-hours` plumbing in `main()`. KEEP: `_require_local_stage` (slimmed), `local_marker`, `_is_local_stage`, `stage_hardlink_farm`, `stamp_local_events`, `write_code_tarball`, `sourced_env`, `_maybe_refresh_token`, `_submit_lock`, `_materialize_template`, all `_stamp/_check_stage_config_sha`, the whole harvest half of the file.
- [ ] **Step 2: Delete the two files:**

```bash
git rm core/local_exec.py tests/test_local_exec.py
```

- [ ] **Step 3: Sweep for dead references:**

```bash
grep -rn "local_exec\|mu2ejobdef\|mu2ejobsub\|poll_cluster\|list_outputs(" core/ graph/ tests/ tools/ README.md
```

Every remaining hit is either a comment to update or a missed call site to
fix. `tools/run_local.sh` (untracked) is superseded — flag it to the operator
rather than deleting an untracked file.
- [ ] **Step 4: Full suite → green. Count the deletion** (`git diff --stat` should show roughly −1,700 including tests). **Commit.**

---

### Task 10: Prodtools — `dir:` on /pnfs streams via xrootd

**Repo:** `/exp/mu2e/app/users/oksuzian/muse_050125/prodtools` (branch `code-tarball`)

**Why (the one spec deviation this plan introduces):** the spec's grid stage
chaining ("a downstream entry's `inloc` points at the upstream stage's
output location") assumed `dir:<pnfs path>` is readable on a worker. It is
not: `utils/runmu2e.py:309` forces the `file` protocol for every `dir:`
inloc, and workers do not mount /pnfs. `utils/file_resolver.py` already
renders `dir:` + `root` proto correctly (`locate()` returns
`<dir>/<file>`, `url()` xroot-rewrites any `/pnfs/` path), so the fix is
confined to the proto choice. Nothing is lost: POSIX-reading a /pnfs `dir:`
from a worker can never have worked.

**Files:**
- Modify: `utils/runmu2e.py:309`
- Test: `test/test_runmu2e_dir_pnfs.py` (new file — do NOT touch the operator's in-flight `test/test_unit.py`)

- [ ] **Step 1: Failing test** (self-contained, mirrors `test_jobwait.py`'s standalone style):

```python
import unittest
from utils.runmu2e import proto_for_inloc  # extracted helper

class TestDirInlocProto(unittest.TestCase):
    def test_local_dir_is_file(self):
        self.assertEqual(proto_for_inloc("dir:/cvmfs/mu2e/DataFiles"), "file")
    def test_pnfs_dir_is_root(self):
        self.assertEqual(proto_for_inloc(
            "dir:/pnfs/mu2e/scratch/users/u/workflow/default/outstage/1/staged"),
            "root")
    def test_sam_locations_are_root(self):
        self.assertEqual(proto_for_inloc("tape"), "root")
```

- [ ] **Step 2: Extract + fix** — replace line 309's inline ternary with a module-level helper right above the call site:

```python
def proto_for_inloc(inloc):
    """'file' only for dir: paths a worker can POSIX-read. A dir: under
    /pnfs is dCache -- never mounted on a grid worker -- so it streams
    via xrootd like every other dCache location (file_resolver already
    renders the xroot URL for dir:+root)."""
    if inloc.startswith('dir:') and not inloc[4:].startswith('/pnfs/'):
        return 'file'
    return 'root'
```

and at the call site: `proto = proto_for_inloc(inloc)`.
- [ ] **Step 3: Run the new test file AND the full prodtools suite** (`python3 test/test_unit.py` per its header convention) → green. **Commit in prodtools** (its own repo, its own commit).

---

### Task 11: Offline entry validation (interactive node, NO submission)

The empirical gate for every residual schema question (does the dir: shape
honor merge factors; does a basename `fcl` embed cleanly; does the resampler
auto-config coexist with our template's hardcoded `MaxEventsToSkip`). Needs
the Mu2e env; run on a mu2egpvm node. No jobs are submitted or run.

- [ ] **Step 1:** For a scratch config (`--config prodsw_smoke01`, geometry from any existing config's geom file), run `pipeline.py --config prodsw_smoke01 submit mubeam --dry-run` — this renders the entry, builds the cnf via json2jobdef, and stops (Task 4 made `--dry-run` stop before the driver).
- [ ] **Step 2:** Print job 0's resolved FCL: `<prodtools>/bin/jobfcl --jobdef <cnf> --index 0` (check `bin/jobfcl --help` for exact flags) and diff the physics content against the mu2ejobdef-era materialized FCL for the same stage (geometry basename, resampler fileNames slicing, events/run).
- [ ] **Step 3:** Repeat for `concat` and `mustops_ce` with a hand-made flat input dir of 2 dummy `.art` files (copy any small art file twice) — validates the `dir:` + basenames + merge shape end-to-end at build time.
- [ ] **Step 4:** Record findings (and any schema corrections fed back into Task 2's goldens) in the plan-execution notes; if a shape does not work as pinned, STOP and report BLOCKED with the observed json2jobdef/jobfcl output.

---

### Task 12: Docs

- [ ] **Step 1:** Update `wiki/drivers/pipeline.md` (verbs now shell prodtools; new state files; jobwait/wait.json contract), `wiki/drivers/local-executor.md` (status: superseded → points at prodtools runlocal), `wiki/index.md` one-liners, `wiki/log.md` bullet under today's heading (top). Leave ALL wiki changes **uncommitted** (operator reviews wiki edits).
- [ ] **Step 2:** Update `README.md` run instructions (env: `AUTORESEARCH_PRODTOOLS`; local runs via `submit --local`). Commit README only.
- [ ] **Step 3:** Remind the operator: prodtools `EXAMPLES.md` needs `/refresh-examples` for jobwait (never hand-edit).

---

### Task 13: Retire the stage templates — published FCL + `fcl_overrides` (operator-approved extension, 2026-08-16)

**Decision record:** every `core/pipeline_templates/<stage>/template.fcl` is
`#include <published Production FCL>` + flat overrides — exactly what a
json2jobdef entry's `fcl` + `fcl_overrides` renders (prodtools
`write_fcl_template`: `'#include'` override key supports extra includes;
values go through `json.dumps`). The one FHiCL construct that cannot ride a
JSON value is the `@sequence::`-bearing `outputCommands` lists in
mubeam/run1b_mubeam — those blocks move to ONE tiny
`autoresearch_<stage>_extras.fcl` shipped in the code tarball (geometry-style
delivery) and pulled in via the `'#include'` override (option 1; no prodtools
change). Depends on the Task-11 fix round: the prodtools `dir:`-resampler
MaxEventsToSkip skip must be in place (mustops_ce's hand-tuned override must
stand; for the Cat resampler stages the SAM-computed post_line replaces our
frozen 319542 — validated numerically identical for MuBeamCat Run1Baa).

**Files:**
- Modify: `core/pipeline.py` (per-stage `fcl` + `fcl_overrides` data; `submit_stage_prodtools` + local branch stop materializing; delete `_materialize_template` + `__GEOM_FILE__` substitution), `core/prodtools_exec.py` (`render_entry` carries `fcl_overrides` through)
- Create: `core/pipeline_templates/mubeam_extras.fcl`, `run1b_mubeam_extras.fcl` (the outputCommands blocks, verbatim)
- Delete: the five `core/pipeline_templates/<stage>/template.fcl` (transcribed, then removed)
- Test: `tests/test_prodtools_exec.py` / `tests/test_pipeline_verbs.py`

**Rules for the transcription (binding):**
- Each template's non-include lines move VERBATIM into that stage's `fcl_overrides` dict (same keys, same values — including output fileName placeholder strings); the second `#include` (epilog_1b) becomes the `'#include'` override key, FIRST in the dict; `@sequence` lists go to the extras fcl instead.
- The load-bearing comments in the templates (physics-list A/B rationale, prescale reasoning, MaxEventsToSkip provenance — wiki-linked) move to Python comments beside the per-stage overrides dicts. Zero comment content may be dropped.
- Geometry: `services.GeometryService.inputFile: "autoresearch_<cfg>_geom.txt"` rendered per config (replaces `__GEOM_FILE__`); concat gets NO geom key (no G4); the concat-less `MaxEventsToSkip: 8000` conditional from `_materialize_template` moves to the same conditional in the overrides assembly (`hv.concatless` stamp-first, unchanged rule).
- Entry `fcl` = the published path (e.g. `Production/JobConfig/pileup/MuBeamResampler.fcl`).
- `write_code_tarball` `extra_files` now ships the extras fcl (mubeam/run1b only) instead of materialized templates; digest cache stays.

- [ ] **Step 1: Failing tests** — golden entry per stage now asserts `fcl` (published path) + key `fcl_overrides` entries (geom basename, physics list, `'#include'` key placement); a test asserting no `*_template_materialized.fcl` is written; mubeam entry test asserts the extras fcl rides `'#include'` and is in the tarball's extra_files.
- [ ] **Step 2: Implement; full suite green; commit.**
- [ ] **Step 3: Offline re-validation (Mu2e env, NO submission):** re-run the Task-11 mubeam + mustops_ce checks under the new shape; diff jobfcl job-0 output against the pre-retirement Task-11 captures — semantically identical FCL required (report any delta as a finding, do not paper over).

### Task 14: Stage-entry JSON templates out of `STAGES` (operator-approved extension, 2026-08-16)

Per-stage job description becomes checked-in JSON in json2jobdef's native
schema; `STAGES` shrinks to orchestration residue.

**Files:**
- Create: `stage_entries/<stage>.json` for the five stages — full entry template: `fcl`, `fcl_overrides` (with `{cfg}`/`{geom}` placeholders in string values), `resampler_name`, static Cat `input_data`, `inloc`, `outloc`, `run`, `memory`, default `events`
- Modify: `core/pipeline.py` (entry assembly loads + substitutes the JSON; `STAGES` keeps ONLY `desc_fmt`, `njobs`, `events_per_job`, `output_glob`, `quorum`, `merge_factor`, `dsconf_musing` — runtime/orchestration values that mode_specs `stage_tuning` and `STAGE_TARGETS` tune), `core/prodtools_exec.py` if the substitution helper lands there
- Test: goldens re-pointed at the JSON files; a test proving `stage_tuning` overrides flow into the rendered entry; a test that an unknown placeholder in a stage JSON fails loudly (no silent `{typo}` passthrough)

**Rules (binding):**
- Substitution is explicit and closed: only `{cfg}` and `{geom}` placeholders, applied to string values recursively; anything else in braces raises. Runtime fields (njobs, events, memory, staged `input_data`/`inloc`) are merged in by the assembly code, never templated.
- The rendered `state/<stage>_entry.json` stays the audit record — unchanged contract.
- Python comments carrying the physics rationale stay beside the assembly code; the JSON files carry none (JSON has no comments) — each JSON gets a `"_comment"` key pointing at the pipeline.py comment block (json2jobdef ignores unknown keys — verify that assumption against `_reject_unknown`-style validation in prodtools jobdesc before relying on it; if entries are strictly validated, drop the `_comment` key and rely on the Python-side comments alone).

- [ ] **Step 1: Failing tests; Step 2: implement, suite green, commit; Step 3: one offline mubeam re-validation (env, no submission) proving byte-identical rendered entry JSON vs Task 13's.**

---

## Out of plan (operator-gated live validation, from the spec)

1. 2-job grid smoke through `submit` + `jobwait` (verifies ExitCode passthrough for OUR jobs).
2. One full closed-loop child mubeam→…→harvest on the grid.
3. Local chain re-run through runlocal.

## Self-review notes

- Spec coverage: decisions 1–5 map to Tasks 2/4 (entry+submit), 5 (jobwait), 3 (one results contract), 6 (runlocal), 4 (ledger under DATA_ROOT, no SAM — outloc outstage everywhere). Deletion inventory → Task 9. Error handling (submit failure loud, partial-ok policy, unknown≠ok) → Tasks 4/5/3. `grid_stages` flash gating untouched (no harvest changes anywhere).
- Known deviation from spec, made explicit: Task 10 (prodtools `dir:`/pnfs proto fix) — the spec's grid chaining is unimplementable without it; flagged for the operator in the handoff.
- Type consistency: `submit_cnf` returns `(int, str)`; `run_jobwait` returns rc int; wait.json fixtures shared between Tasks 3/5/6 tests.
