"""Thin wrappers around bo_driver.py + pipeline.py.

BO ops go in-process via `import bo_driver as bo` (the BOMode
adapters are clean — no need to fork a subprocess for those). Preflight,
evaluate, and the grid-stage wrappers (run_stage / run_harvest, which shell
out to pipeline.py's idempotent verbs) use subprocess to keep their I/O
side-effects firewalled from the long-lived runner process.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure core/ (BO/pipeline modules, 2026-07-17 reorg) is importable so we can
# pull the BO modes in-process.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import bo_driver as bo  # noqa: E402
import harvest as hv  # noqa: E402  (canonical outputs.txt reader)
import modes as _modes  # noqa: E402
# read_stage_status's n_failed inference reads njobs through
# pipeline.stage_cfg() (Task 6 fix round) -- the SAME function core/
# pipeline.py's own submit/poll/list-outputs read, instead of a second
# runtime.STAGE_TARGETS copy of the same number that could silently drift
# from it (the exact shape events-per-job-mid-flight-edit and the STAGES/
# stage_entries shadow this task retired both were). Safe to import
# in-process: pipeline.py never imports graph/pipeline_io.py, so there is no
# cycle, and this module already imports bo_driver/harvest/modes/
# prodtools_exec from the same core/ tree.
import pipeline as _pipeline  # noqa: E402
import prodtools_exec as _prodtools_exec  # noqa: E402
from paths import GRID_DATA_ROOT  # noqa: E402
from runtime import (  # noqa: E402
    BO_DRIVER,
    BOTORCH_VENV_PY,
    DEFAULT_ALPHA,
    GRID_STAGES,
    PIPELINE_DRIVER,
    PREFLIGHT_TIMEOUT_S,
)


# --- propose (in-process, single-config flavor of cmd_propose) ---


def propose_one(mode_name: str, config_name: str, alpha: float = DEFAULT_ALPHA,
                x_override: list[float] | None = None, seed_idx: int = 0):
    """Propose a single config, materialize its geom, append to pending TSV.

    If x_override is given, skip the BO ask and use that x directly (used to
    force-evaluate GP-Pareto picks). The pending row is still written so
    concurrent BO proposals see this point as in-flight.

    The BO ask is bo.botorch_ask (botorch-venv subprocess; the picker loads
    priors+history itself and fantasizes over the pending x-points instead
    of the retired skopt constant-liar suppression). seed_idx varies the
    picker seed — node_propose passes its retry counter so a preflight-driven
    re-propose draws a fresh point instead of the same one.

    Returns: (x_point: list[float], geom_path: str). Raises ValueError if the
    config name collides with an existing leaderboard or pending entry.
    """
    mode = bo.MODES[mode_name]

    pending = mode.load_pending()
    existing = {p.cfg for p in mode.load_history()} | {n for n, _ in pending}
    if config_name in existing:
        raise ValueError(f"config name {config_name!r} already in leaderboard or pending")

    if x_override is not None:
        x = list(x_override)
    else:
        xs = bo.botorch_ask(mode_name, q=1, seed_idx=seed_idx,
                            pending=[px for _, px in pending],
                            venv_py=BOTORCH_VENV_PY)
        x = xs[0]
        if not mode.is_buildable(x):
            # x_override bypasses this check since the caller chose the point
            # intentionally; here the pick came from the GP — surface it and
            # let preflight reject it downstream.
            print(f"WARN: submitting unbuildable pick {list(x)} "
                  f"(preflight will reject)", file=sys.stderr)
    geom_path = mode.render_proposal(config_name, x)
    # Stage geom into pipeline.py's per-config work tree (mirror cmd_propose in
    # bo_driver.py:567-570; pipeline.py's submit checks for this
    # exact path and refuses otherwise).
    work_geom_dir = GRID_DATA_ROOT / config_name / "geom"
    work_geom_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(geom_path, work_geom_dir / f"autoresearch_{config_name}_geom.txt")
    mode.append_pending(config_name, x, alpha)
    # Coerce numpy scalars to native Python types. Kept after the
    # checkpointer's retirement (2026-08-19), which removed the original
    # motive: LangGraph's SqliteSaver called ormsgpack on the state dict and
    # np.int64 is not msgpack-serializable, so an unguarded np.int64 in
    # x_point surfaced as `TypeError: Type is not msgpack serializable:
    # numpy.int64` at end-of-run (wiki/incidents/langgraph-checkpoint-numpy-
    # int64.md, prodtarget's Integer numberOfPlates dim -- archived). The
    # coercion still earns its place: x_point is JSON-serialized into the
    # picker subprocess and written to the leaderboard/pending TSVs, and
    # np.int64 is no friendlier there.
    return bo.to_py_scalars(x), str(geom_path)


# --- preflight (subprocess) ---


def run_preflight(mode_name: str, config_name: str, timeout_s: int = PREFLIGHT_TIMEOUT_S) -> tuple[str, str]:
    """Run `bo_driver.py preflight <cfg>` and read the typed verdict JSON.

    Returns (status, log_tail). status ∈ {"pass", "fail_managed",
    "fail_init", "ambiguous", "timeout"}. A missing/unparseable JSON
    (process crash, transport failure) decodes as "ambiguous" with a loud
    reason — fail-safe: ambiguous routes to retry/human review and never
    silently passes.
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = state_dir / "preflight_verdict.json"
    verdict_path.unlink(missing_ok=True)  # never read a stale verdict
    cmd = [
        sys.executable,
        str(BO_DRIVER),
        "--mode", mode_name,
        "preflight", config_name,
        "--emit-json", str(verdict_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return "timeout", "(preflight timed out)"

    tail = "\n".join(proc.stdout.splitlines()[-80:])
    try:
        status = json.loads(verdict_path.read_text())["verdict"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        status = "ambiguous"
        # No verdict means the subprocess died BEFORE writing one, and a
        # python death writes its traceback to STDERR -- which the tail above
        # does not include. So the one message explaining the failure was
        # discarded and the operator saw "ambiguous" three times and nothing
        # else (mmackenz 2026-08-13: a missing backing, whose PathsError names
        # the exact fix, was invisible). Same swallowed-stderr class as the
        # jobsub-disk-quota-stderr-swallowed and sourced-env-stderr-swallowed
        # incidents.
        err = "\n".join(proc.stderr.splitlines()[-40:])
        tail = (f"(preflight verdict JSON missing/unparseable at "
                f"{verdict_path}: {e!r}; rc={proc.returncode} — decoding as "
                f"ambiguous)\n"
                + (f"PREFLIGHT STDERR:\n{err}\n" if err.strip() else "")
                + tail)
    return status, tail


# --- per-stage grid driver (Phase 2b) ---


def _run_pipeline_verb(config_name: str, verb: str, stage: str | None) -> Path:
    """Shell out to pipeline.py with one verb + optional stage. Returns log path.

    Raises RuntimeError on non-zero exit; caller adds stage context.
    """
    log_dir = GRID_DATA_ROOT / config_name / "graph_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(PIPELINE_DRIVER), "--config", config_name, verb]
    if stage is not None:
        cmd.append(stage)
    log_path = log_dir / f"{verb}_{stage or 'harvest'}_{int(time.time())}.log"
    with log_path.open("w") as fh:
        fh.write(f"$ {' '.join(cmd)}\n\n")
        fh.flush()
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{verb} {stage or ''} failed (rc={proc.returncode}); see {log_path}"
        )
    return log_path


def run_stage(config_name: str, stage: str) -> dict:
    """Run submit → poll → list-outputs for one stage. Returns a StageStatus.

    Each pipeline.py verb is idempotent: submit no-ops if the cluster file
    exists; list-outputs no-ops if the outputs file validates. Poll is
    naturally re-entrant. So a killed-and-resumed graph node re-runs this
    helper without double-submitting.
    """
    for verb in ("submit", "poll", "list-outputs"):
        _run_pipeline_verb(config_name, verb, stage)
    return read_stage_status(config_name, stage)


def presubmit_stage(config_name: str, stage: str) -> None:
    """Early submit of a data-independent stage (see runtime.PRESUBMIT_AFTER).

    Submit-only: the stage's own node later finds the cluster file (submit
    no-ops), polls the already-running jobs, and lists outputs — so the
    stage's grid time overlaps the intervening chain. Callers treat this as
    best-effort; on failure the stage node just submits sequentially.
    """
    _run_pipeline_verb(config_name, "submit", stage)


def run_harvest(config_name: str, mode: str | None = None) -> dict:
    """Run pipeline.py harvest verb for the mode; return parsed summary.json.

    Mode dispatch (2026-06-07): prodtarget chains a single `pot_only` stage
    whose summary schema differs (`mu_per_POT`) from the 4-stage S/√B+calo
    schema. Verb selection comes from the ModeSpec registry; defaults to the
    legacy 4-stage `harvest` for backward compat when no mode is passed.
    """
    if mode is None:
        mode = _modes.resolve_env_mode()
    verb = _modes.SPECS[mode].harvest_verb  # loud KeyError on unknown mode (ADR-0002)
    _run_pipeline_verb(config_name, verb, None)
    summary_path = GRID_DATA_ROOT / config_name / "harvest" / "summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"harvest finished but {summary_path} is missing")
    return json.loads(summary_path.read_text())


def read_stage_status(config_name: str, stage: str) -> dict:
    """Parse state/<stage>_cluster.txt + outputs.txt into a StageStatus dict.

    Pure I/O — testable with a tmpdir of fake state files. n_failed is
    inferred as `target - n_done`; with our idempotency guards, "stage done"
    means submit + poll + list-outputs all returned, so n_done is final.
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    cluster_file = state_dir / f"{stage}_cluster.txt"
    cid = cluster_file.read_text().strip() if cluster_file.exists() else None
    outputs = hv.read_outputs(state_dir, stage) or []
    # Same njobs pipeline.py's own submit/poll/list-outputs use for this
    # stage under this process's mode -- see the import comment above.
    target = _pipeline.stage_cfg(stage, _pipeline.MODE)["njobs"]
    n_done = len(outputs)
    status = "done" if (cid and outputs) else ("in_flight" if cid else "pending")
    return {
        "cluster_id": cid,
        "status": status,
        "n_done": n_done,
        "n_failed": max(0, target - n_done),
        "last_poll_ts": time.time(),
    }


# --- end-of-workflow log scanner (report-only) ---


# Patterns counted per worker log. Order matters only for report column order.
_SCAN_PATTERNS = (
    ("G4Exception",            r"G4Exception"),
    ("StuckTrack",             r"Stuck Track"),
    ("LikelyGeomOverlap",      r"Likely geometry overlap"),
    ("GeomSolids1001",         r"GeomSolids1001"),
    ("GeomNav1002",            r"GeomNav1002"),
    ("Error",                  r"\bError\b"),
    ("Warning",                r"\bWarning\b"),
    ("FATAL",                  r"FATAL"),
    ("SEGV",                   r"SEGV|segmentation fault|Segmentation fault"),
    # Report-only (NOT in SCAN_BROKEN_CODES): a few hits = transient xrootd
    # flakes (concat-xrootd-fileopen-postendjob); hits across ALL jobs = a
    # moved input dataset (elebeamcat-tape-migration-elebeam-wipeout). Gating
    # on it would false-positive the transient case — surface, don't block.
    ("FileOpenError",          r"FileOpenError"),
)


# Outstage root prodtools writes to -- same root the mu2ejobsub era used
# (core/prodtools_exec.py outstage_root()). Module-level so tests can point
# it at a tmp dir via mock.patch.object(pipeline_io, "OUTSTAGE_ROOT", ...).
OUTSTAGE_ROOT = Path(_prodtools_exec.outstage_root())


def _worker_log_paths(config_name: str, stage: str) -> list[Path]:
    """Resolve every .log under the per-worker outstage dirs for one stage.

    Primary source: `<state>/<stage>_outputs.txt` -- each .art path's parent
    dir already IS the per-worker outstage dir, so globbing *.log there
    self-adapts to whichever backend wrote it. Once outputs.txt has
    entries, this is authoritative and returned as-is (even if empty --
    e.g. stage-out-lag/-rename-race means a job's .log hasn't landed next
    to its .art yet; falling through to a cluster-wide glob there would
    risk attributing an unrelated proc's log to this one).

    Fallback (outputs.txt missing/empty -- i.e. list-outputs hasn't run,
    or every job in the cluster died before producing an .art, so there
    is no per-worker dir to derive at all): glob the cluster's outstage
    dir (`<state>/<stage>_cluster.txt`) via
    prodtools_exec.cluster_worker_logs, which owns the known worker-log
    layouts (legacy mu2ejobsub vs prodtools-direct flat) and their
    tie-break.
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    outputs = hv.read_outputs(state_dir, stage)
    if outputs:
        logs: list[Path] = []
        for art_path in outputs:
            try:
                logs.extend(sorted(art_path.parent.glob("*.log")))
            except OSError:
                continue
        return logs
    cluster_file = state_dir / f"{stage}_cluster.txt"
    if not cluster_file.exists():
        return []
    cluster = cluster_file.read_text().strip()
    if not cluster:
        return []
    return _prodtools_exec.cluster_worker_logs(OUTSTAGE_ROOT / cluster)


def _scan_one_stage(config_name: str, stage: str, jobs: int = 16) -> dict[str, int]:
    """Count occurrences of each _SCAN_PATTERNS regex across all worker logs.

    Uses `xargs -P jobs grep -cE` for a single fan-out per pattern; on /pnfs
    this is ~4-5s per 200 logs (file-open is the bottleneck, not regex).
    """
    logs = _worker_log_paths(config_name, stage)
    if not logs:
        return {code: 0 for code, _ in _SCAN_PATTERNS}
    counts: dict[str, int] = {}
    paths_blob = "\n".join(str(p) for p in logs).encode()
    for code, regex in _SCAN_PATTERNS:
        proc = subprocess.run(
            ["xargs", "-0", "-P", str(jobs), "-n", "20",
             "grep", "-cE", "--", regex],
            input=paths_blob.replace(b"\n", b"\0"),
            capture_output=True,
        )
        # grep -c prints one line per file: "path:N". Sum the N.
        total = 0
        for ln in proc.stdout.decode("utf-8", "replace").splitlines():
            _, _, n = ln.rpartition(":")
            try:
                total += int(n)
            except ValueError:
                continue
        counts[code] = total
    return counts


# Pattern codes whose nonzero count means the run is physics-broken (do not
# trust the metrics). GeomSolids1001 is the smoking gun for the
# tessellated-facet-orientation incident: a single misfacetted solid floods
# logs with GeomNav1002 entries and silently corrupts particle navigation.
# Any nonzero hit gates the leaderboard append.
SCAN_BROKEN_CODES = ("GeomSolids1001",)


def is_scan_broken(report: dict[str, dict[str, int]]) -> bool:
    """Return True if any stage's report has a nonzero count for a broken-code."""
    for stage_counts in report.values():
        for code in SCAN_BROKEN_CODES:
            if stage_counts.get(code, 0) > 0:
                return True
    return False


def scan_worker_logs(config_name: str) -> tuple[dict[str, dict[str, int]], Path, bool]:
    """Scan all stages' worker logs for known issue patterns.

    Returns ({stage: {code: count}}, report_path, broken). Always writes the
    TSV even when all counts are zero — downstream visibility wants the row.
    When `broken` is True (see SCAN_BROKEN_CODES), also writes
    `<config>/state/broken.txt` so the closed-loop refit can filter the chain
    out without re-running the scan.
    """
    report_dir = GRID_DATA_ROOT / config_name / "scan_logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, int]] = {}
    for stage in GRID_STAGES:
        report[stage] = _scan_one_stage(config_name, stage)
    # TSV: stage \t n_logs \t <pattern_columns...>
    report_path = report_dir / "report.tsv"
    headers = ["stage", "n_logs"] + [code for code, _ in _SCAN_PATTERNS]
    lines = ["\t".join(headers)]
    for stage in GRID_STAGES:
        n_logs = len(_worker_log_paths(config_name, stage))
        row = [stage, str(n_logs)] + [str(report[stage].get(c, 0)) for c, _ in _SCAN_PATTERNS]
        lines.append("\t".join(row))
    report_path.write_text("\n".join(lines) + "\n")
    (report_dir / "report.json").write_text(json.dumps(report, indent=2))
    broken = is_scan_broken(report)
    if broken:
        state_dir = GRID_DATA_ROOT / config_name / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        marker = state_dir / "broken.txt"
        hit_codes = sorted({
            code
            for stage_counts in report.values()
            for code in SCAN_BROKEN_CODES
            if stage_counts.get(code, 0) > 0
        })
        marker.write_text(
            "scan_logs detected broken-run patterns; leaderboard append suppressed.\n"
            f"codes={','.join(hit_codes)}\n"
            f"report={report_path}\n"
        )
    return report, report_path, broken


# --- evaluate (subprocess; writes leaderboard, clears pending) ---


def run_evaluate(mode_name: str, config_name: str, metrics: dict,
                 alpha: float = DEFAULT_ALPHA) -> tuple[float | None, str]:
    """Write metrics to a tmp summary.json, call the driver's evaluate verb,
    and read the objective from the typed result JSON.

    Contract: rc != 0 → the driver refused (missing metrics, bad geom…) and
    appended nothing → return (None, tail) — callers already treat that as
    a zero_row. rc == 0 with missing/unparseable JSON is a HARD error: a
    run that cannot prove it recorded a row already is one.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"graph_eval_{config_name}_"))
    summary_path = tmp / "summary.json"
    summary_path.write_text(json.dumps(metrics, indent=2))
    result_path = GRID_DATA_ROOT / config_name / "state" / "evaluate_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)  # never read a stale result

    cmd = [
        sys.executable,
        str(BO_DRIVER),
        "--mode", mode_name,
        "--alpha", f"{alpha}",
        "evaluate", config_name, str(summary_path),
        "--emit-json", str(result_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])

    if proc.returncode != 0:
        return None, tail
    try:
        return float(json.loads(result_path.read_text())["obj"]), tail
    except (FileNotFoundError, json.JSONDecodeError, KeyError,
            TypeError, ValueError) as e:
        raise RuntimeError(
            f"evaluate rc=0 but result JSON missing/unparseable at "
            f"{result_path}: {e!r}; stdout tail:\n{tail}")


# --- helper: synthesize next config name from leaderboard width ---


def next_config_name(mode_name: str, prefix: str = "graph") -> str:
    """Pick the next free `<prefix>NNN` not in leaderboard or pending."""
    mode = bo.MODES[mode_name]
    used = {p.cfg for p in mode.load_history()} | {n for n, _ in mode.load_pending()}
    for i in range(1, 10_000):
        cand = f"{prefix}{i:03d}"
        if cand not in used:
            return cand
    raise RuntimeError("ran out of config name candidates (1..9999)")
