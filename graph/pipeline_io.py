"""Thin wrappers around bo_driver.py + pipeline.py.

BO ops go in-process (bo_driver's BOMode adapters are clean). Preflight,
evaluate, and grid-stage wrappers shell out via subprocess, firewalling
their I/O from the long-lived runner process.
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

# Make core/ (BO/pipeline modules) importable for in-process BO calls.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import bo_driver as bo  # noqa: E402
import harvest as hv  # noqa: E402  (canonical outputs.txt reader)
import modes as _modes  # noqa: E402
# read_stage_status reads njobs via pipeline.stage_cfg() -- the same
# function pipeline.py's submit/poll/list-outputs use, not a copy that
# could drift (wiki/incidents/events-per-job-mid-flight-edit.md). No import
# cycle: pipeline.py doesn't import this module.
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

    x_override skips the BO ask and uses that x directly (forced GP-Pareto
    picks); the pending row is still written so concurrent proposals see it
    as in-flight. Otherwise asks bo.botorch_ask (botorch-venv subprocess,
    fantasizing over pending x-points); seed_idx (node_propose's retry
    counter) varies the picker seed so a re-propose after a preflight
    failure draws a fresh point.

    Returns (x_point, geom_path). Raises ValueError on a config-name
    collision with the leaderboard or pending TSV.
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
            # x_override bypasses this check (deliberate caller choice); a
            # GP pick that fails is surfaced here and left for preflight to
            # reject.
            print(f"WARN: submitting unbuildable pick {list(x)} "
                  f"(preflight will reject)", file=sys.stderr)
    geom_path = mode.render_proposal(config_name, x)
    # Stage geom into pipeline.py's per-config work tree (mirrors
    # cmd_propose in bo_driver.py; submit checks this exact path).
    work_geom_dir = GRID_DATA_ROOT / config_name / "geom"
    work_geom_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(geom_path, work_geom_dir / f"autoresearch_{config_name}_geom.txt")
    mode.append_pending(config_name, x, alpha)
    # Coerce numpy scalars to native types for JSON (picker subprocess) and
    # the leaderboard/pending TSVs. Originally guarded a now-retired
    # SqliteSaver msgpack write against np.int64 (wiki/incidents/langgraph-
    # checkpoint-numpy-int64.md); still needed for these.
    return bo.to_py_scalars(x), str(geom_path)


# --- preflight (subprocess) ---


def run_preflight(mode_name: str, config_name: str, timeout_s: int = PREFLIGHT_TIMEOUT_S) -> tuple[str, str]:
    """Run `bo_driver.py preflight <cfg>` and read the typed verdict JSON.

    status ∈ {"pass", "fail_managed", "fail_init", "ambiguous", "timeout"}.
    Missing/unparseable JSON (process crash, transport failure) decodes as
    "ambiguous" with a loud reason -- fail-safe, since ambiguous retries
    and never silently passes.
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
        # A python death writes its traceback to STDERR, not the stdout
        # tail above -- capture it, or the operator sees only "ambiguous"
        # (same swallowed-stderr class as wiki/incidents/jobsub-disk-quota-
        # stderr-swallowed.md, sourced-env-stderr-swallowed.md).
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

    Each verb is idempotent (submit no-ops if the cluster file exists;
    list-outputs no-ops if the outputs file validates; poll is naturally
    re-entrant), so a killed-and-resumed graph node won't double-submit.
    """
    for verb in ("submit", "poll", "list-outputs"):
        _run_pipeline_verb(config_name, verb, stage)
    return read_stage_status(config_name, stage)


def presubmit_stage(config_name: str, stage: str) -> None:
    """Early submit of a data-independent stage (see runtime.PRESUBMIT_AFTER).

    Submit-only: the stage's own node later finds the cluster (submit
    no-ops) and polls/lists normally, so its grid time overlaps the
    intervening chain. Best-effort -- on failure the stage node just
    submits sequentially.
    """
    _run_pipeline_verb(config_name, "submit", stage)


def run_harvest(config_name: str, mode: str | None = None) -> dict:
    """Run pipeline.py harvest verb for the mode; return parsed summary.json.

    prodtarget's single `pot_only` stage has a different summary schema
    (`mu_per_POT`) than the 4-stage S/√B+calo default. Verb comes from the
    ModeSpec registry.
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

    Pure I/O -- testable with a tmpdir of fake state files. n_failed is
    `target - n_done`; idempotency guards mean "done" is final, not a poll
    snapshot.
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    cluster_file = state_dir / f"{stage}_cluster.txt"
    cid = cluster_file.read_text().strip() if cluster_file.exists() else None
    outputs = hv.read_outputs(state_dir, stage) or []
    # Same njobs pipeline.py's submit/poll/list-outputs use -- see the
    # import comment above.
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
    # Report-only: a few hits are transient xrootd flakes (wiki/incidents/
    # concat-xrootd-fileopen-postendjob.md); hits across ALL jobs mean a
    # moved dataset (wiki/incidents/elebeamcat-tape-migration-elebeam-
    # wipeout.md). Gating would false-positive the transient case.
    ("FileOpenError",          r"FileOpenError"),
)


# Outstage root prodtools writes to (core/prodtools_exec.py
# outstage_root()). Module-level so tests can point it at a tmp dir via
# mock.patch.object(pipeline_io, "OUTSTAGE_ROOT", ...).
OUTSTAGE_ROOT = Path(_prodtools_exec.outstage_root())


def _worker_log_paths(config_name: str, stage: str) -> list[Path]:
    """Resolve every .log under the per-worker outstage dirs for one stage.

    Primary source: `<state>/<stage>_outputs.txt` -- each .art's parent dir
    IS the outstage dir, so globbing *.log there self-adapts to whichever
    backend wrote it. Returned as-is even if empty rather than falling back
    to a cluster-wide glob, which could attribute an unrelated job's log to
    this one (a .log can lag its .art -- wiki/incidents/stage-out-lag.md,
    stage-out-rename-race.md).

    Fallback when outputs.txt is missing/empty: glob the cluster's outstage
    dir via prodtools_exec.cluster_worker_logs.
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


# Nonzero count here means the run is physics-broken; gates the leaderboard
# append. GeomSolids1001 is the smoking gun for
# wiki/incidents/tessellated-solid-facet-orientation.md (a misfacetted
# solid silently corrupts particle navigation).
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

    Returns ({stage: {code: count}}, report_path, broken). Always writes
    the TSV, even all-zero, for visibility. When broken (SCAN_BROKEN_CODES),
    also writes `<config>/state/broken.txt` so the closed-loop refit can
    filter the chain without re-scanning.
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
