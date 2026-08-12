# Local Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one config's full stage chain on the local node at reduced
statistics, producing the same `summary.json` and a leaderboard-shaped row, and
expose each job's FCL as an editable file.

**Architecture:** `core/pipeline.py` isolates every grid touch into three
functions (`submit_stage`, `poll_cluster`, `list_outputs`). A new
`core/local_exec.py` provides local counterparts; `pipeline.py` dispatches to
them under `--local`. `harvest` and every metric extractor are shared verbatim,
so local and grid numbers are computed by identical code.

**Tech Stack:** Python 3.11 stdlib only in the new module (`subprocess`,
`concurrent.futures`, `hashlib`, `pathlib`, `os`); `unittest` (NOT pytest); the
existing `mu2ejobdef` / `mu2ejobfcl` tooling.

**Spec:** `docs/superpowers/specs/2026-08-12-local-executor-design.md`

**Branch:** `local-executor`, worktree
`/exp/mu2e/app/users/oksuzian/autoresearch_wt_localexec`, based on `mu2e/main`.
Do NOT develop on `json-modes` — it is 39 commits behind and has no
`core/paths.py`.

## Global Constraints

- `unittest`, never pytest. Suite command:
  `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`
  The leading blank `PYTHONPATH=` and the `-t .` are both required.
- **Zero grid contact in tests.** No test may cause a `mu2ejobsub` or
  `jobsub_q` invocation.
- **`harvest` and the metric extractors are untouched**, with exactly one
  deliberate exception, in Task 6: `EvalSummary` gains one optional field
  (`fcl_edited`). No extraction logic changes; no metric is recomputed.
- `core/local_exec.py` is **Python 3.11 stdlib only** — no torch, no numpy, no
  third-party imports.
- Local rows are written only to `leaderboard_local_<mode>.tsv`. Never to a
  production board.
- Never hardcode `/exp/mu2e/data/users/<name>`; use `core/paths.py`.
  `tests/test_no_hardcoded_paths.py` enforces this and will fail the suite.
- Default local parallelism is **4**, never derived from `nproc`.
- Defaults: `--local-njobs 1`, `--local-events 200`.

## File Structure

- **Create `core/local_exec.py`** — the entire local path: root/runid
  resolution, FCL build + hashing, bounded execution pool, output listing. One
  file because these four things always change together and none is useful
  alone.
- **Modify `core/pipeline.py`** — CLI surface (`--local`, `local-build`,
  `local-run`, scale dials) and three dispatch points. No logic beyond
  dispatch.
- **Modify `core/harvest.py`** — one optional `EvalSummary` field (Task 6).
- **Create `tests/test_local_exec.py`** — all six spec tests.

## Task 0: Worktree setup (do this first, once)

The worktree is already created but has no venv — a fresh worktree never does.

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch_wt_localexec
./setup.sh --venv                                          # link the shared venv
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .
```

Expected: `OK`, under a minute. If this does not pass before you change
anything, stop and report — you are not on a clean base.

---

## Task 1: Local roots, run ids, and output listing

**Files:**
- Create: `core/local_exec.py`
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Consumes: `paths.DATA_ROOT` from `core/paths.py`.
- Produces:
  - `local_outstage(config: str) -> Path` → `DATA_ROOT/autoresearch_local/<config>`
  - `next_runid(config: str) -> int` — smallest unused integer ≥ 1
  - `job_dir(config: str, runid: int, index: int) -> Path` →
    `<local_outstage>/<runid>/00/<index:05d>`
  - `list_outputs_local(stage: str, config: str, runid: int, output_glob: str, state_dir: Path) -> list[Path]`

- [ ] **Step 1: Write the failing test**

Add to a new `tests/test_local_exec.py`:

```python
"""Local executor tests: no grid contact anywhere. Every path is a tmpdir."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import local_exec  # noqa: E402


class TestLocalRoots(unittest.TestCase):
    def test_job_dir_mirrors_the_outstage_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                d = local_exec.job_dir("cfg001", 7, 3)
            self.assertEqual(
                d,
                Path(tmp) / "autoresearch_local" / "cfg001" / "7" / "00" / "00003")

    def test_next_runid_starts_at_one_then_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                self.assertEqual(local_exec.next_runid("cfg001"), 1)
                local_exec.job_dir("cfg001", 1, 0).mkdir(parents=True)
                self.assertEqual(local_exec.next_runid("cfg001"), 2)

    def test_list_outputs_local_writes_the_same_file_the_grid_path_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)):
                for i in (0, 1):
                    d = local_exec.job_dir("cfg001", 1, i)
                    d.mkdir(parents=True)
                    (d / f"sim.x.TargetStops.{i}.art").write_text("x")
                    (d / "ignored.log").write_text("x")
                files = local_exec.list_outputs_local(
                    "mubeam", "cfg001", 1, "sim.*.TargetStops.*.art", state)
            self.assertEqual(len(files), 2)
            listed = (state / "mubeam_outputs.txt").read_text().split()
            self.assertEqual(len(listed), 2)
            self.assertTrue(all(p.endswith(".art") for p in listed))
            self.assertEqual(listed, sorted(listed))
```

- [ ] **Step 2: Run it and watch it fail**

```
PYTHONPATH= .venv/bin/python -m unittest tests.test_local_exec -v
```
Expected: `ModuleNotFoundError: No module named 'local_exec'`.

- [ ] **Step 3: Write the implementation**

Create `core/local_exec.py`:

```python
#!/usr/bin/env python3
"""Local counterparts to pipeline.py's three grid-contact functions.

The local output tree deliberately mirrors the /pnfs outstage layout
(<root>/<runid>/00/<index:05d>/) so listing is a base-path swap rather than a
second implementation. Nothing here may import anything outside the stdlib
plus core.paths.
"""
from __future__ import annotations

from pathlib import Path

from paths import DATA_ROOT

LOCAL_DIRNAME = "autoresearch_local"


def local_outstage(config: str) -> Path:
    return DATA_ROOT / LOCAL_DIRNAME / config


def job_dir(config: str, runid: int, index: int) -> Path:
    return local_outstage(config) / str(runid) / "00" / f"{index:05d}"


def next_runid(config: str) -> int:
    """Smallest unused positive integer, so runids read like cluster ids."""
    base = local_outstage(config)
    if not base.is_dir():
        return 1
    used = {int(d.name) for d in base.iterdir() if d.name.isdigit()}
    n = 1
    while n in used:
        n += 1
    return n


def list_outputs_local(stage: str, config: str, runid: int,
                       output_glob: str, state_dir: Path) -> list[Path]:
    """Glob the local run tree; write <stage>_outputs.txt exactly as the grid
    path does, so the next stage's --inputs and harvest need no changes.

    No rename-drain loop here: that exists only for dCache's staged rename
    semantics (incidents stage-out-lag, stage-out-rename-race) and has no
    local analogue.
    """
    base = local_outstage(config) / str(runid) / "00"
    files = sorted(base.glob(f"[0-9][0-9][0-9][0-9][0-9]/{output_glob}"))
    out_list = state_dir / f"{stage}_outputs.txt"
    out_list.write_text("\n".join(str(f) for f in files) + "\n")
    print(f"[{stage}] {len(files)} local output file(s) -> {out_list}")
    return files
```

- [ ] **Step 4: Run the test again**

```
PYTHONPATH= .venv/bin/python -m unittest tests.test_local_exec -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/local_exec.py tests/test_local_exec.py
git commit -m "feat(local): local outstage layout, run ids, output listing"
```

---

## Task 2: FCL build and hash provenance

**Files:**
- Modify: `core/local_exec.py`
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Consumes: `job_dir` from Task 1.
- Produces:
  - `fcl_path(state_dir: Path, stage: str, index: int) -> Path` →
    `<state_dir>/fcl/<stage>_<index:05d>.fcl`
  - `build_fcls(stage, cnf_name, stage_dir, state_dir, njobs, default_loc, env) -> list[Path]`
  - `edited_fcls(state_dir: str | Path, stage: str) -> list[str]` — basenames
    whose content no longer matches the hash recorded at build

`build_fcls` shells out to `mu2ejobfcl` once per index — the same command
`submit_stage` already uses at `core/pipeline.py:725` for its index-0 smoke
test, with `--index` varying.

- [ ] **Step 1: Write the failing test**

```python
class TestFclProvenance(unittest.TestCase):
    def _build(self, tmp, n=2):
        state = Path(tmp) / "state"
        state.mkdir(parents=True, exist_ok=True)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            idx = cmd[cmd.index("--index") + 1]
            return mock.Mock(returncode=0, stdout=f"# fcl for job {idx}\n",
                             stderr="")

        with mock.patch.object(local_exec.subprocess, "run", fake_run):
            paths = local_exec.build_fcls(
                "mubeam", "cnf.tar", Path(tmp), state, n, "tape", {})
        return state, paths, calls

    def test_build_writes_one_fcl_per_index_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, calls = self._build(tmp, n=2)
            self.assertEqual(len(paths), 2)
            self.assertTrue((state / "fcl" / "mubeam_00000.fcl").exists())
            self.assertTrue((state / "fcl" / "mubeam_00001.fcl").exists())
            self.assertEqual(len(calls), 2)
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"), [])

    def test_hand_edit_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, _ = self._build(tmp, n=2)
            paths[1].write_text("# I changed this by hand\n")
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"),
                             ["mubeam_00001.fcl"])

    def test_a_missing_hash_record_counts_as_edited(self):
        # Deleting the sidecar must not silently read as "unmodified".
        with tempfile.TemporaryDirectory() as tmp:
            state, paths, _ = self._build(tmp, n=1)
            (state / "fcl" / "mubeam_00000.fcl.sha256").unlink()
            self.assertEqual(local_exec.edited_fcls(state, "mubeam"),
                             ["mubeam_00000.fcl"])
```

- [ ] **Step 2: Run it and watch it fail**

```
PYTHONPATH= .venv/bin/python -m unittest tests.test_local_exec.TestFclProvenance -v
```
Expected: `AttributeError: module 'local_exec' has no attribute 'build_fcls'`.

- [ ] **Step 3: Write the implementation**

Add to `core/local_exec.py` (and add `import hashlib`, `import shlex`,
`import subprocess` at the top):

```python
def fcl_path(state_dir: Path, stage: str, index: int) -> Path:
    return Path(state_dir) / "fcl" / f"{stage}_{index:05d}.fcl"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_fcls(stage: str, cnf_name: str, stage_dir: Path, state_dir: Path,
               njobs: int, default_loc: str, env: dict) -> list[Path]:
    """Resolve one FCL per job index and record each one's hash.

    The hash sidecar is what lets `local-run` report an edited FCL as data
    (fcl_edited in summary.json) instead of relying on the operator to
    remember a flag. Compare template-fcl-staleness, where an edit meant for
    one run silently persisted into later ones.
    """
    out_dir = Path(state_dir) / "fcl"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for index in range(njobs):
        cmd = ["mu2ejobfcl", "--jobdef", cnf_name, "--index", str(index),
               "--default-proto", "root", "--default-loc", default_loc]
        print(f"$ (cd {stage_dir} && {shlex.join(cmd)})", flush=True)
        proc = subprocess.run(cmd, cwd=str(stage_dir), env=env, check=True,
                              capture_output=True, text=True)
        target = fcl_path(state_dir, stage, index)
        target.write_text(proc.stdout)
        target.with_suffix(".fcl.sha256").write_text(_sha256(proc.stdout))
        written.append(target)
    print(f"[{stage}] built {len(written)} FCL(s) -> {out_dir}")
    return written


def edited_fcls(state_dir, stage: str) -> list[str]:
    """Basenames whose content differs from the hash recorded at build time.

    A missing sidecar counts as edited: absence of evidence is not evidence
    the file is pristine.
    """
    out_dir = Path(state_dir) / "fcl"
    if not out_dir.is_dir():
        return []
    edited = []
    for f in sorted(out_dir.glob(f"{stage}_[0-9]*.fcl")):
        rec = f.with_suffix(".fcl.sha256")
        if not rec.exists() or rec.read_text().strip() != _sha256(f.read_text()):
            edited.append(f.name)
    return edited
```

- [ ] **Step 4: Run the test again**

Expected: 3 tests PASS (6 total in the file).

- [ ] **Step 5: Commit**

```bash
git add core/local_exec.py tests/test_local_exec.py
git commit -m "feat(local): per-index FCL build with hash provenance"
```

---

## Task 3: Bounded local execution

**Files:**
- Modify: `core/local_exec.py`
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Consumes: `job_dir` (Task 1), `fcl_path` (Task 2).
- Produces: `run_jobs_local(stage, config, runid, state_dir, njobs, events, env, pool=4) -> dict`
  returning `{"ok": int, "failed": [int, ...]}`.

Each job runs `mu2e -c <fcl> -n <events>` with **cwd set to its own job dir**,
so outputs land in the mirrored layout with no path rewriting. Pool default 4:
this is a shared 48-core GPVM and `mustops_ce` requests 3 GB per job, so a pool
sized to the machine would wedge the login node for everyone.

- [ ] **Step 1: Write the failing test**

```python
class TestLocalExecution(unittest.TestCase):
    def test_runs_one_mu2e_per_job_in_its_own_dir_and_never_calls_grid_tools(self):
        seen = []

        def fake_run(cmd, **kw):
            seen.append((cmd, kw.get("cwd")))
            Path(kw["cwd"], "sim.x.TargetStops.0.art").write_text("x")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(3):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 3, 200, {}, pool=2)

        self.assertEqual(res["ok"], 3)
        self.assertEqual(res["failed"], [])
        self.assertEqual(len(seen), 3)
        for cmd, cwd in seen:
            self.assertEqual(cmd[0], "mu2e")
            self.assertIn("-n", cmd)
            self.assertEqual(cmd[cmd.index("-n") + 1], "200")
            self.assertTrue(cwd.endswith(("00000", "00001", "00002")))
        # The point of the whole design: no grid tooling, ever.
        flat = [tok for cmd, _ in seen for tok in cmd]
        self.assertNotIn("mu2ejobsub", flat)
        self.assertNotIn("jobsub_q", flat)

    def test_a_failing_job_is_reported_not_raised(self):
        def fake_run(cmd, **kw):
            idx = int(Path(kw["cwd"]).name)
            return mock.Mock(returncode=0 if idx == 0 else 1,
                             stdout="", stderr="boom")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            (state / "fcl").mkdir(parents=True)
            for i in range(2):
                local_exec.fcl_path(state, "mubeam", i).write_text("x")
            with mock.patch.object(local_exec, "DATA_ROOT", Path(tmp)), \
                 mock.patch.object(local_exec.subprocess, "run", fake_run):
                res = local_exec.run_jobs_local(
                    "mubeam", "cfg001", 1, state, 2, 200, {}, pool=2)

        self.assertEqual(res["ok"], 1)
        self.assertEqual(res["failed"], [1])
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module 'local_exec' has no attribute 'run_jobs_local'`.

- [ ] **Step 3: Write the implementation**

Add to `core/local_exec.py` (add
`from concurrent.futures import ThreadPoolExecutor, as_completed` at the top):

```python
DEFAULT_POOL = 4


def _run_one(stage: str, config: str, runid: int, state_dir: Path,
             index: int, events: int, env: dict) -> tuple[int, int]:
    d = job_dir(config, runid, index)
    d.mkdir(parents=True, exist_ok=True)
    cmd = ["mu2e", "-c", str(fcl_path(state_dir, stage, index)),
           "-n", str(events)]
    log = d / f"{stage}_{index:05d}.log"
    proc = subprocess.run(cmd, cwd=str(d), env=env,
                          capture_output=True, text=True)
    log.write_text(proc.stdout + proc.stderr)
    return index, proc.returncode


def run_jobs_local(stage: str, config: str, runid: int, state_dir: Path,
                   njobs: int, events: int, env: dict,
                   pool: int = DEFAULT_POOL) -> dict:
    """Execute njobs local mu2e jobs, at most `pool` at a time.

    Threads, not processes: each unit of work is a subprocess, so the GIL is
    irrelevant and threads keep the failure reporting simple.
    """
    print(f"[{stage}] local: {njobs} job(s) x {events} events, pool={pool}",
          flush=True)
    ok, failed = 0, []
    with ThreadPoolExecutor(max_workers=pool) as ex:
        futures = [ex.submit(_run_one, stage, config, runid, state_dir,
                             i, events, env) for i in range(njobs)]
        for fut in as_completed(futures):
            index, rc = fut.result()
            if rc == 0:
                ok += 1
            else:
                failed.append(index)
                print(f"[{stage}] job {index:05d} FAILED rc={rc}", flush=True)
    failed.sort()
    print(f"[{stage}] local done: {ok} ok, {len(failed)} failed", flush=True)
    return {"ok": ok, "failed": failed}
```

- [ ] **Step 4: Run the test again**

Expected: 2 tests PASS (8 total in the file).

- [ ] **Step 5: Commit**

```bash
git add core/local_exec.py tests/test_local_exec.py
git commit -m "feat(local): bounded local job execution pool"
```

---

## Task 4: Scale dials

**Files:**
- Modify: `core/local_exec.py`
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Produces: `resolve_scale(values: list[str] | None, default: int, stage: str) -> int`

`--local-njobs` and `--local-events` are each repeatable. A bare value sets the
default for all stages; a `<stage>=<value>` entry overrides one stage and wins
over the bare form regardless of order. Two explicit dials rather than a scale
factor: a multiplier reads clever and then nobody can say what actually ran.

- [ ] **Step 1: Write the failing test**

```python
class TestScaleDials(unittest.TestCase):
    def test_none_gives_the_default(self):
        self.assertEqual(local_exec.resolve_scale(None, 1, "mubeam"), 1)

    def test_bare_value_applies_to_every_stage(self):
        self.assertEqual(local_exec.resolve_scale(["4"], 1, "mubeam"), 4)
        self.assertEqual(local_exec.resolve_scale(["4"], 1, "concat"), 4)

    def test_per_stage_override_wins_regardless_of_order(self):
        self.assertEqual(
            local_exec.resolve_scale(["1", "elebeam_flash=4"], 1,
                                     "elebeam_flash"), 4)
        self.assertEqual(
            local_exec.resolve_scale(["elebeam_flash=4", "1"], 1,
                                     "elebeam_flash"), 4)
        self.assertEqual(
            local_exec.resolve_scale(["1", "elebeam_flash=4"], 1, "mubeam"), 1)

    def test_a_malformed_entry_is_a_loud_error(self):
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["notanumber"], 1, "mubeam")
        with self.assertRaises(ValueError):
            local_exec.resolve_scale(["mubeam=x"], 1, "mubeam")
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module 'local_exec' has no attribute 'resolve_scale'`.

- [ ] **Step 3: Write the implementation**

```python
def resolve_scale(values, default: int, stage: str) -> int:
    """Resolve one repeatable --local-njobs/--local-events flag for a stage."""
    if not values:
        return default
    bare, per_stage = default, {}
    for raw in values:
        item = str(raw)
        if "=" in item:
            key, _, val = item.partition("=")
            try:
                per_stage[key] = int(val)
            except ValueError:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected <stage>=<int>")
        else:
            try:
                bare = int(item)
            except ValueError:
                raise ValueError(
                    f"bad value {item!r}: expected an int or <stage>=<int>")
    return per_stage.get(stage, bare)
```

- [ ] **Step 4: Run the test again**

Expected: 4 tests PASS (12 total in the file).

- [ ] **Step 5: Commit**

```bash
git add core/local_exec.py tests/test_local_exec.py
git commit -m "feat(local): repeatable per-stage scale dials"
```

---

## Task 5: pipeline.py wiring, the events stamp, and the concat clamp

**Files:**
- Modify: `core/pipeline.py` (arg parser ~`:1315-1345`; `cmd_submit` `:886`;
  `cmd_poll` `:935`; `cmd_list_outputs` `:943`)
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: verbs `local-build` / `local-run`; `--local` on `submit`;
  `--local-njobs` / `--local-events` / `--local-pool`.

Two correctness traps live here. Both are tested.

**Trap 1 — the events stamp.** `harvest` scales metrics by
`state/<stage>_events_per_job.txt`, which `submit_stage` writes at
`core/pipeline.py:708`. That stamp exists because editing `events_per_job`
between submit and harvest silently mis-scaled `sob` once already
(`wiki/incidents/events-per-job-mid-flight-edit.md`). The local path **must**
write the local value. Stamping the configured 2500 while running 200 events
makes every local metric wrong by 12.5× in a way that looks entirely plausible.

**Trap 2 — the concat clamp.** `concat`'s configured `merge_factor` is 200, but
a local `mubeam` at `njobs=1` produces one file. Clamp to
`min(merge_factor, n_inputs)`.

- [ ] **Step 1: Write the failing test**

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import pipeline  # noqa: E402


class TestPipelineLocalWiring(unittest.TestCase):
    def test_events_stamp_carries_the_local_value_not_the_configured_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state):
                pipeline.stamp_local_events("mustops_ce", 200)
            self.assertEqual(
                (state / "mustops_ce_events_per_job.txt").read_text().strip(),
                "200")

    def test_concat_merge_factor_clamps_to_available_inputs(self):
        self.assertEqual(pipeline.clamp_merge_factor(200, 1), 1)
        self.assertEqual(pipeline.clamp_merge_factor(200, 350), 200)
        self.assertEqual(pipeline.clamp_merge_factor(200, 200), 200)

    def test_local_build_never_invokes_grid_tools(self):
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return mock.Mock(returncode=0, stdout="# fcl\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            with mock.patch.object(pipeline, "STATE", state), \
                 mock.patch.object(pipeline, "ROOT", Path(tmp)), \
                 mock.patch.object(pipeline, "sourced_env", return_value={}), \
                 mock.patch.object(pipeline, "_materialize_template",
                                   return_value=Path(tmp) / "t.fcl"), \
                 mock.patch.object(pipeline.subprocess, "run", fake_run):
                pipeline.cmd_local_build(SimpleNamespace(
                    stage="mubeam", local_njobs=["2"], local_events=["200"]))

        flat = [tok for cmd in seen for tok in cmd]
        self.assertNotIn("mu2ejobsub", flat)
        self.assertNotIn("jobsub_q", flat)
        self.assertIn("mu2ejobfcl", flat)

    def test_poll_is_a_noop_in_local_mode(self):
        # run_jobs_local is synchronous, so by the time poll could run every
        # job is done. Without this guard a graph-driven chain would feed the
        # runid in <stage>_cluster.txt to jobsub_q as if it were a cluster id.
        with mock.patch.dict(os.environ, {"AUTORESEARCH_LOCAL": "1"}), \
             mock.patch.object(pipeline, "poll_cluster") as pc:
            pipeline.cmd_poll(SimpleNamespace(stage="mubeam", quorum=None,
                                              cap_hours=24.0))
        pc.assert_not_called()
```

Add `from types import SimpleNamespace` to the test file's imports.

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module 'pipeline' has no attribute
'stamp_local_events'`.

- [ ] **Step 3: Write the implementation**

Add to `core/pipeline.py` near the other stage helpers:

```python
import local_exec as lx


def stamp_local_events(stage: str, events: int) -> Path:
    """Stamp the LOCAL events-per-job so harvest scales by what actually ran.

    harvest reads this file, not STAGES[stage]["events_per_job"]. Stamping the
    configured value while running fewer events biases every derived metric by
    the ratio -- the failure class of events-per-job-mid-flight-edit.
    """
    out = STATE / f"{stage}_events_per_job.txt"
    out.write_text(f"{events}\n")
    return out


def clamp_merge_factor(configured: int, n_inputs: int) -> int:
    """concat merges 200 files on the grid; a local run may have produced 1."""
    return max(1, min(configured, n_inputs))


def cmd_local_build(args):
    """Build this stage's per-index FCLs and stop. Nothing is executed."""
    stage = args.stage
    njobs = lx.resolve_scale(getattr(args, "local_njobs", None), 1, stage)
    events = lx.resolve_scale(getattr(args, "local_events", None), 200, stage)
    env = sourced_env()
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    template_fcl = _materialize_template(stage)
    dsconf = _stage_dsconf(stage)
    desc = _stage_desc(stage)
    cnf = stage_dir / f"cnf.{USER}.{desc}.{dsconf}.0.tar"
    if not cnf.exists():
        jobdef = ["mu2ejobdef", "--dsconf", dsconf, "--dsowner", USER,
                  "--desc", desc, "--embed", str(template_fcl)]
        subprocess.run(jobdef, cwd=str(stage_dir), env=env, check=True)
    lx.build_fcls(stage, cnf.name, stage_dir, STATE, njobs,
                  STAGES[stage]["default_loc"], env)
    stamp_local_events(stage, events)
    print(f"[{stage}] local-build done; edit "
          f"{STATE / 'fcl'}/{stage}_00000.fcl then 'local-run {stage}'")


def cmd_local_run(args):
    """Execute the FCLs already on disk, then list outputs."""
    stage = args.stage
    njobs = lx.resolve_scale(getattr(args, "local_njobs", None), 1, stage)
    events = lx.resolve_scale(getattr(args, "local_events", None), 200, stage)
    pool = getattr(args, "local_pool", None) or lx.DEFAULT_POOL
    edited = lx.edited_fcls(STATE, stage)
    for name in edited:
        print(f"[{stage}] FCL hand-edited: {name}")
    (STATE / f"{stage}_fcl_edited.txt").write_text(
        "\n".join(edited) + "\n" if edited else "")
    runid = lx.next_runid(CONFIG)
    (STATE / f"{stage}_cluster.txt").write_text(f"{runid}\n")
    res = lx.run_jobs_local(stage, CONFIG, runid, STATE, njobs, events,
                            sourced_env(), pool=pool)
    stamp_local_events(stage, events)
    lx.list_outputs_local(stage, CONFIG, runid,
                          STAGES[stage]["output_glob"], STATE)
    if res["failed"]:
        print(f"[{stage}] WARNING: {len(res['failed'])} job(s) failed: "
              f"{res['failed']}")
```

`CONFIG` is the module-level config name bound by `_bind_config()` at
`core/pipeline.py:135` when `--config` is parsed. Use it directly; do not
re-derive the name from `ROOT.name`.

`cmd_poll` must also become a no-op under `--local`, because
`run_jobs_local` is synchronous — when it returns, every job has already
finished, so there is nothing to wait for. Without this a graph-driven chain
would call `poll`, read `state/<stage>_cluster.txt` (which now holds a runid,
not a cluster id), and hand that runid to `jobsub_q`. Add at the top of
`cmd_poll` (`core/pipeline.py:935`):

```python
    if os.environ.get("AUTORESEARCH_LOCAL"):
        print(f"[{args.stage}] local mode: jobs already complete; poll is a no-op")
        return
```

Register the verbs in the parser next to the existing ones (~`:1341`):

```python
    for verb, fn in (("local-build", cmd_local_build),
                     ("local-run", cmd_local_run)):
        p_l = sub.add_parser(verb, help=f"{verb}: local executor")
        p_l.add_argument("stage", choices=list(STAGES))
        p_l.add_argument("--local-njobs", action="append",
                         help="int, or <stage>=<int>; repeatable (default 1)")
        p_l.add_argument("--local-events", action="append",
                         help="int, or <stage>=<int>; repeatable (default 200)")
        p_l.add_argument("--local-pool", type=int, default=None,
                         help="max concurrent local jobs (default 4)")
        p_l.set_defaults(func=fn)
```

and add `--local` to the existing `submit` parser (`:1320`), which runs build
then run:

```python
    p_sub.add_argument("--local", action="store_true",
                       help="run this stage locally instead of submitting")
    p_sub.add_argument("--local-njobs", action="append")
    p_sub.add_argument("--local-events", action="append")
    p_sub.add_argument("--local-pool", type=int, default=None)
```

In `cmd_submit`, immediately after the idempotency guard block ends
(`core/pipeline.py:895`), add:

```python
    if getattr(args, "local", False) or os.environ.get("AUTORESEARCH_LOCAL"):
        cmd_local_build(args)
        cmd_local_run(args)
        return
```

- [ ] **Step 4: Run the tests**

```
PYTHONPATH= .venv/bin/python -m unittest tests.test_local_exec -v
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .
```
Expected: the file's 16 tests PASS and the full suite stays green.

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_local_exec.py
git commit -m "feat(local): local-build/local-run verbs, events stamp, concat clamp"
```

---

## Task 6: Row destination and edited-FCL provenance

**Files:**
- Modify: `core/harvest.py` (`EvalSummary`, `:325-370`)
- Modify: `core/local_exec.py`
- Test: `tests/test_local_exec.py`

**Interfaces:**
- Consumes: `edited_fcls` (Task 2).
- Produces: `local_board_path(mode: str, live_root: Path) -> Path`;
  `EvalSummary.fcl_edited: Optional[list] = None`.

**This task contains the plan's one deliberate deviation from "harvest
untouched":** `EvalSummary` gains a single optional field. No extraction logic
changes and no metric is recomputed — the constraint's purpose (identical
numbers between local and grid) is preserved. If a reviewer rejects the
deviation, the fallback is a sibling `harvest/local_provenance.json`, at the
cost of splitting provenance from the row.

- [ ] **Step 1: Write the failing test**

```python
class TestLocalRowDestination(unittest.TestCase):
    def test_local_board_is_a_separate_file_from_the_production_board(self):
        live = Path("/tmp/boards")
        p = local_exec.local_board_path("foilspfbpz", live)
        self.assertEqual(p, live / "leaderboard_local_foilspfbpz.tsv")
        self.assertNotIn("leaderboard_bo_", p.name)

    def test_eval_summary_carries_the_edited_fcl_record(self):
        sys.path.insert(
            0, str(Path(__file__).resolve().parent.parent / "core"))
        import harvest as hv
        s = hv.EvalSummary(
            config="cfg001", ce_seen=1, muminus_stops=1, mubeam_sim_total=1,
            ce_simulated_events=1, stopping_factor=1.0, ce_abs_eff=1.0,
            s_over_sqrt_b=1.0, muminus_source="mubeam",
            fcl_edited=["mubeam_00000.fcl"])
        self.assertIn("fcl_edited", s.to_json())
        self.assertEqual(s.fcl_edited, ["mubeam_00000.fcl"])

    def test_eval_summary_default_is_none_so_grid_rows_are_unchanged(self):
        import harvest as hv
        s = hv.EvalSummary(
            config="cfg001", ce_seen=1, muminus_stops=1, mubeam_sim_total=1,
            ce_simulated_events=1, stopping_factor=1.0, ce_abs_eff=1.0,
            s_over_sqrt_b=1.0, muminus_source="mubeam")
        self.assertIsNone(s.fcl_edited)
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module 'local_exec' has no attribute
'local_board_path'`, then a `TypeError` on the unexpected `fcl_edited` kwarg.

- [ ] **Step 3: Write the implementation**

In `core/local_exec.py`:

```python
def local_board_path(mode: str, live_root: Path) -> Path:
    """Local rows never share a file with grid rows.

    A local run is at 1/1250-1/5000 of campaign statistics, so its sigma is
    tens of percent against the 0.4% the pickers assume. One such row in a
    production board is enough to move a GP fit.
    """
    return Path(live_root) / f"leaderboard_local_{mode}.tsv"
```

In `core/harvest.py`, add to `EvalSummary` after `flash_edep_tag` (`:356`):

```python
    # local-executor provenance: basenames of FCLs hand-edited before the run.
    # None on every grid row; a list (possibly empty) on a local one.
    fcl_edited: Optional[list] = None
```

- [ ] **Step 4: Run the tests**

```
PYTHONPATH= .venv/bin/python -m unittest tests.test_local_exec -v
PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .
```
Expected: 19 tests in the file PASS; full suite green. `tests/test_harvest.py`
must still pass unchanged — the new field is optional precisely so it does not
disturb existing summaries.

- [ ] **Step 5: Commit**

```bash
git add core/local_exec.py core/harvest.py tests/test_local_exec.py
git commit -m "feat(local): separate local board + edited-FCL provenance"
```

---

## Task 7: End-to-end smoke on a real config (manual, not in the suite)

**Files:** none — this is a verification run.

The suite proves the plumbing with everything faked. This proves it against
real `mu2ejobdef` / `mu2ejobfcl` / `mu2e`. It is manual because it needs
`muse setup` and takes minutes, and the suite must stay grid-free and fast.

- [ ] **Step 1: Pick an already-proposed config** that has a rendered geom, e.g.
  any `foilspfbpz07*` directory under `GRID_DATA_ROOT`.

- [ ] **Step 2: Build and inspect**

```bash
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
muse setup
PYTHONPATH= .venv/bin/python core/pipeline.py --config <cfg> local-build mubeam
sed -n '1,40p' <GRID_DATA_ROOT>/<cfg>/state/fcl/mubeam_00000.fcl
```
Expected: a readable resolved FCL naming the geom and the resampler inputs.

- [ ] **Step 3: Run it**

```bash
PYTHONPATH= .venv/bin/python core/pipeline.py --config <cfg> local-run mubeam
```
Expected: one `.art` under
`DATA_ROOT/autoresearch_local/<cfg>/1/00/00000/`, and
`state/mubeam_outputs.txt` listing it.

- [ ] **Step 4: Confirm the edit loop reports**

```bash
printf '\n# touched\n' >> <...>/state/fcl/mubeam_00000.fcl
PYTHONPATH= .venv/bin/python core/pipeline.py --config <cfg> local-run mubeam
```
Expected: `[mubeam] FCL hand-edited: mubeam_00000.fcl`.

- [ ] **Step 5: Record the result** in `wiki/drivers/` and add a `wiki/log.md`
  bullet under today's date at the TOP. Do not commit wiki edits — the operator
  reviews them.

---

## Notes for the implementer

- **A green local chain does NOT validate the grid `Code.tar.bz2`.** Local runs
  exercise the patched muse workdir, not the grid tarball. These have diverged
  before at the cost of a whole campaign
  (`wiki/incidents/foilsflash-tarball-mode-key-omission.md`). Do not describe a
  passing local run as evidence the grid path works.
- Do not run the suite while a closed-loop campaign is live: children re-execute
  the working tree.
- Never `git add -A`. Stage the explicit paths listed in each task.
- Do not push. The operator pushes.
