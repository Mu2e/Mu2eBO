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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Ensure core/ (BO/pipeline modules, 2026-07-17 reorg) is importable so we can
# pull the BO modes in-process.
sys.path.insert(0, "/exp/mu2e/app/users/oksuzian/autoresearch/core")

import bo_driver as bo  # noqa: E402
import harvest as hv  # noqa: E402  (canonical outputs.txt reader)
import modes as _modes  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from config import (  # noqa: E402
    BO_DRIVER,
    BOTORCH_VENV_PY,
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRID_DATA_ROOT,
    GRID_STAGES,
    PIPELINE_DRIVER,
    PREFLIGHT_TIMEOUT_S,
    STAGE_TARGETS,
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
    # Coerce numpy scalars to native Python types. np.int64 is NOT
    # msgpack-serializable, and LangGraph's SqliteSaver
    # checkpointer (graph/run.py default) calls ormsgpack on the state dict —
    # so an unguarded np.int64 in x_point bubbles up as
    # `TypeError: Type is not msgpack serializable: numpy.int64` at end-of-run.
    # Affects prodtarget mode (N=numberOfPlates is the only Integer dim across
    # all modes); see wiki/incidents/langgraph-checkpoint-numpy-int64.md.
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
        tail = (f"(preflight verdict JSON missing/unparseable at "
                f"{verdict_path}: {e!r}; rc={proc.returncode} — decoding as "
                f"ambiguous)\n" + tail)
    return status, tail


# --- mock grid (Phase 1) ---


def mock_metrics(x_point: list[float], mode: str = DEFAULT_MODE) -> dict:
    """Synthesize a (s_over_sqrt_b, calo_per_pot) pair from x via a smooth surface.

    Dimension-generic: normalizes each knob against the mode's registry
    bounds (modes.SPECS[mode].bounds_lo/hi), so every numeric mode works
    (6D foilsf … 12D foilsg). sob peaks at mid-range of each knob; calo grows
    with the last two normalized knobs ("more material").
    """
    import math
    spec = _modes.SPECS[mode]
    lo, hi = spec.bounds_lo, spec.bounds_hi
    if len(lo) != len(x_point):
        raise ValueError(f"mock_metrics: x_point has {len(x_point)} dims, "
                         f"mode {mode!r} registry bounds have {len(lo)}")
    u = [(v - lo[i]) / (hi[i] - lo[i]) for i, v in enumerate(x_point)]
    # sob: gaussian bump centered at 0.5 in each dim.
    r2 = sum((ui - 0.5) ** 2 for ui in u)
    sob = 0.9 * math.exp(-2.5 * r2) + 0.05
    # calo: grows with the last two normalized knobs ("more material" dir).
    calo = 1e-7 + 6e-7 * u[-2] * u[-1]
    return {
        "config": "mock",
        "s_over_sqrt_b": round(sob, 6),
        "calo_per_pot": calo,
        "ce_seen": 0,
        "muminus_stops": 0,
        "mubeam_sim_total": 0,
        "stopping_factor": 0.0,
        "ce_abs_eff": 0.0,
        "calo_total": 0.0,
        "calo_files_seen": 0,
        "nts_path": "mock",
        "edep_log": "mock",
        "macro_log": "mock",
        "mock": True,
    }


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
    """Early submit of a data-independent stage (see config.PRESUBMIT_AFTER).

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
        mode = os.environ.get("AUTORESEARCH_MODE", DEFAULT_MODE)
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
    target = STAGE_TARGETS.get(stage, 0)
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


def _worker_log_paths(config_name: str, stage: str) -> list[Path]:
    """Resolve every .log under the per-worker outstage dirs for one stage.

    Reads `<state>/<stage>_outputs.txt`, takes the dirname of each .art path,
    globs *.log in that dir. Returns [] if outputs file is missing (stage
    didn't reach list-outputs yet).
    """
    state_dir = GRID_DATA_ROOT / config_name / "state"
    outputs = hv.read_outputs(state_dir, stage)
    if not outputs:
        return []
    logs: list[Path] = []
    for art_path in outputs:
        try:
            logs.extend(sorted(art_path.parent.glob("*.log")))
        except OSError:
            continue
    return logs


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
    """Write metrics to a tmp summary.json and call the driver's evaluate verb.

    Returns (objective, stdout_tail). objective is None if the driver could
    not compute it (missing fields, etc.).
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"graph_eval_{config_name}_"))
    summary_path = tmp / "summary.json"
    summary_path.write_text(json.dumps(metrics, indent=2))

    cmd = [
        sys.executable,
        str(BO_DRIVER),
        "--mode", mode_name,
        "--alpha", f"{alpha}",
        "evaluate", config_name, str(summary_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])

    obj = None
    # Driver prints `obj={:+.3f}` so the sign is always present; allow both
    # `obj=+0.519` and `obj: 0.5` to be forgiving across formats.
    m = re.search(r"obj\s*[:=]\s*([+-]?\d+\.\d+)", proc.stdout)
    if m:
        obj = float(m.group(1))
    return obj, tail


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
