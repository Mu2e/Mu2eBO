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


def wait_json_path(state_dir: Path, stage: str) -> Path:
    return state_dir / f"{stage}_wait.json"


def read_wait(state_dir: Path, stage: str) -> dict:
    p = wait_json_path(state_dir, stage)
    if not p.exists():
        raise SystemExit(
            f"[{stage}] {p} missing -- the runner (runlocal/jobwait) died "
            f"before writing its summary; re-run 'poll {stage}'")
    return json.loads(p.read_text())


def run_jobwait(stage_dir, cnf, jobid, njobs, wait_json, env,
                runner=subprocess.run, poll_s=300) -> int:
    """Block on a submitted cluster via prodtools jobwait; return its rc.

    jobwait has no internal timeout by design (the closed-loop barrier
    timeout is the backstop) and its rc reflects the cluster outcome, NOT
    a tool failure -- a partial cluster (some jobs failed) is a nonzero rc
    that callers here still treat as a normal return; SystemExit is
    reserved for the one true tool failure: jobwait dying before it wrote
    its wait.json summary, which leaves callers with nothing to read.
    """
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


def build_cnf(stage_dir, entry_path, desc, dsconf, env,
             runner=subprocess.run) -> Path:
    """Build a cnf tarball via prodtools json2jobdef; return its path.

    SystemExit (stderr surfaced -- c2b154d convention) on a non-zero rc
    or on a rc==0 that somehow didn't produce the expected tarball.
    """
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
    """Submit a built cnf via core/prodtools_submit_driver.py; return
    (cluster_id, jobsub_id). jobsub_id is normalized to NNNN@schedd (the
    shape jobwait wants), dropping the .PROC suffix the driver may pass
    through.

    SystemExit (driver's stderr) if no cluster id came back -- the
    driver's submit_entry already closed the ledger reservation on
    failure, so there is nothing here to unwind. Also SystemExit if
    cluster_id came back but jobsub_id is missing/malformed (no "@schedd"
    to parse): a bare cluster id can't be jobwait'd, so silently returning
    one here would only surface as a confusing jobwait failure downstream
    instead of a clear one at submit time.
    """
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
                cluster = int(data["cluster_id"])
                if "@" not in jobsub:
                    raise SystemExit(
                        f"prodtools submitted cluster {cluster} but returned "
                        f"no usable jobsub_id (got {jobsub!r}) -- cannot "
                        f"derive a schedd for jobwait. Raw SUBMIT_RESULT: "
                        f"{line.strip()}")
                # NNNN.P@schedd -> NNNN@schedd (what jobwait wants).
                schedd = jobsub.split("@", 1)[1]
                return cluster, f"{cluster}@{schedd}"
    raise SystemExit(f"prodtools submit failed rc={res.returncode}:\n"
                     f"{res.stdout}\n{res.stderr}")


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
