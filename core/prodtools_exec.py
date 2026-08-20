"""Prodtools execution seam: entry rendering + tool invocation.

Everything autoresearch says to prodtools goes through here (json2jobdef,
runlocal, submit, jobwait, wait.json readback). pipeline.py's verbs call in;
nothing here knows about modes, leaderboards, or harvest.
Spec: docs/superpowers/specs/2026-08-16-prodtools-switch-design.md.
"""
import getpass
import json
import os
import re
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from paths import REPO_ROOT, prodtools_root

USER = os.environ.get("USER") or getpass.getuser()

# Checked-in json2jobdef-native entry templates, one per stage; see
# load_stage_entry.
STAGE_ENTRIES_DIR = REPO_ROOT / "stage_entries"

# Substitution is closed: ONLY {cfg}/{geom} are recognized. Runtime fields
# (njobs, tuning overrides, staged inputs) are never templated — pipeline.py
# merges them in after load_stage_entry returns.
_STAGE_ENTRY_PLACEHOLDERS = ("cfg", "geom")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def _substitute_placeholders(value, mapping: dict, where: str):
    """Recursively substitute {cfg}/{geom} in string values (nested dicts/lists).

    Any other {token} is a loud ValueError naming the key path: a typo must
    fail at load, not render literally into a submitted FHiCL override.
    Always builds NEW containers — never mutates in place, so repeated calls
    over the same cached raw JSON can't alias between callers.
    """
    if isinstance(value, str):
        def repl(m):
            token = m.group(1)
            if token not in mapping:
                raise ValueError(
                    f"stage_entries: unknown placeholder {{{token}}} at "
                    f"{where!r} -- only {_STAGE_ENTRY_PLACEHOLDERS} are "
                    f"substituted")
            return str(mapping[token])
        return _PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, list):
        return [_substitute_placeholders(v, mapping, f"{where}[{i}]")
                for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: _substitute_placeholders(v, mapping, f"{where}.{k}")
                for k, v in value.items()}
    return value


def load_stage_entry(stage: str, *, cfg: str, geom: str,
                     entries_dir=None) -> dict:
    """Load stage_entries/<stage>.json with {cfg}/{geom} substituted.

    Returns whatever subset of entry fields the stage's JSON declares;
    `_comment` rides along (json2jobdef ignores unknown entry keys).
    `entries_dir` is a tests-only override.
    """
    d = Path(entries_dir) if entries_dir is not None else STAGE_ENTRIES_DIR
    path = d / f"{stage}.json"
    if not path.exists():
        raise SystemExit(
            f"stage_entries: no template for stage {stage!r} at {path}")
    raw = json.loads(path.read_text())
    return _substitute_placeholders(raw, {"cfg": cfg, "geom": geom}, stage)

# Same outstage root the mu2ejobsub era used; prodtools computes it as
# {wftop}/{user}/workflow/{wfproject}/outstage.
WFTOP = "/pnfs/mu2e/scratch/users"
WFPROJECT = "default"


def outstage_root() -> str:
    return f"{WFTOP}/{USER}/workflow/{WFPROJECT}/outstage"


def cluster_worker_logs(cluster_dir) -> list:
    """Worker .log files under one cluster's outstage dir, both layouts:
    legacy mu2ejobsub (`00/<idx>/*.log`, checked first — pre-switch clusters
    can only be legacy, which is also the tie-break) then prodtools flat
    `<proc>/*.log`. Layout knowledge lives ONLY here."""
    cluster_dir = Path(cluster_dir)
    legacy = sorted(cluster_dir.glob("00/*/*.log"))
    if legacy:
        return legacy
    return sorted(cluster_dir.glob("*/*.log"))


_DEFAULT_OUTLOC = {"*.art": "outstage", "*.root": "outstage"}


def render_entry(*, dsconf, desc, njobs,
                 code_tarball, fcl_name, events=None, run=None,
                 memory_mb=None, input_data=None, inloc=None,
                 resampler_name=None, fcl_overrides=None,
                 outloc=None) -> dict:
    """One json2jobdef entry dict for a (config, stage).

    `fcl_name` is the PUBLISHED Production FCL path from
    stage_entries/<stage>.json; `fcl_overrides` is copied verbatim (prodtools
    renders it on top of that base FCL). Code-mode for every stage: the
    per-config tarball ships the geom, so grid and local read identical FCL
    (the env-divergence incident class is closed by construction).
    Caller-supplied `outloc` wins; _DEFAULT_OUTLOC covers only a caller that
    passes none, so editing a stage's JSON outloc actually takes effect
    instead of being silently shadowed here.
    """
    entry = {
        "desc": desc,
        "dsconf": dsconf,
        "owner": USER,
        "fcl": fcl_name,
        "code": str(code_tarball),
        "njobs": njobs,
        "outloc": dict(outloc) if outloc is not None else dict(_DEFAULT_OUTLOC),
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
    if fcl_overrides is not None:
        entry["fcl_overrides"] = dict(fcl_overrides)
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

    No internal timeout (the closed-loop barrier is the backstop). Nonzero
    rc = cluster outcome (partial failures are a normal return); SystemExit
    is reserved for the one true tool failure: jobwait dying before writing
    its wait.json summary, leaving callers nothing to read.
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


def cnf_path(stage_dir, desc, dsconf) -> Path:
    """json2jobdef's own cnf naming: `cnf.<owner>.<desc>.<dsconf>.0.tar`.

    ONE naming rule: build_cnf and pipeline.py's cmd_poll both derive this
    path; they used to inline the f-string separately and could silently
    diverge.
    """
    return Path(stage_dir) / f"cnf.{USER}.{desc}.{dsconf}.0.tar"


def build_cnf(stage_dir, entry_path, desc, dsconf, env,
             runner=subprocess.run) -> Path:
    """Build a cnf tarball via json2jobdef; SystemExit (stderr surfaced)
    on nonzero rc or a missing tarball."""
    cmd = [str(prodtools_root() / "bin" / "json2jobdef"),
           "--json", str(entry_path), "--desc", desc, "--dsconf", dsconf]
    res = runner(cmd, cwd=str(stage_dir), env=env,
                 capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"json2jobdef failed rc={res.returncode}:\n"
                         f"{res.stdout}\n{res.stderr}")
    cnf = cnf_path(stage_dir, desc, dsconf)
    if not cnf.exists():
        raise SystemExit(f"json2jobdef succeeded but {cnf} is missing")
    return cnf


_CODE_ID = ".autoresearch-code-id"


def _invalidate_stale_code_tree(workdir: Path, code_tarball: Path) -> bool:
    """Drop `<workdir>/code` when it was unpacked from a DIFFERENT tarball;
    True if a stale tree was removed.

    runlocal's own `.unpack-complete` sentinel answers "is this tree
    complete", never "is it from THIS tarball" — measured 2026-08-17: an
    edited extras fcl was silently ignored and the job failed rc=90 on a
    deleted include. Identity is (resolved path, size, mtime_ns), NOT the
    path alone: a rebuilt tarball carrying a NEW GEOM lands at the same
    path, and the hidden failure would be a job silently running the
    previous BO point's geometry.
    """
    code_root = workdir / "code"
    if not code_tarball.exists():
        # No identity to compare; let runlocal fail with its own message.
        return False
    st = code_tarball.stat()
    ident = f"{code_tarball.resolve()}\n{st.st_size}\n{st.st_mtime_ns}\n"
    stamp = code_root / _CODE_ID
    stale = code_root.exists() and (
        not stamp.is_file() or stamp.read_text() != ident)
    if stale:
        print(f"[local] code tarball changed -- discarding stale unpack at "
              f"{code_root}")
        shutil.rmtree(code_root)
    code_root.mkdir(parents=True, exist_ok=True)
    # Stamp BEFORE the run: it records which tarball the tree is FOR;
    # runlocal's sentinel records completeness — separate questions, so an
    # interrupted unpack still re-extracts.
    stamp.write_text(ident)
    return stale


def run_runlocal(stage_dir, cnf, njobs, wait_json, env, *, code_tarball,
                 inloc=None, pool=4, runner=subprocess.run) -> int:
    """Run njobs jobs on THIS node via prodtools runlocal; return its rc.

    Writes the same wait.json shape as the grid path (cmd_list_outputs is
    executor-blind); events are already baked into the cnf. Same rc split as
    run_jobwait: SystemExit only for died-before-summary.
    """
    workdir = Path(stage_dir) / "local"
    workdir.mkdir(parents=True, exist_ok=True)
    _invalidate_stale_code_tree(workdir, Path(code_tarball))
    cmd = [str(prodtools_root() / "bin" / "runlocal"),
           "--jobdef", str(cnf), "--first", "0", "--num", str(njobs),
           "-j", str(pool), "--workdir", str(workdir),
           "--code", str(code_tarball), "--json", str(wait_json)]
    if inloc is not None:
        cmd += ["--inloc", str(inloc)]
    res = runner(cmd, cwd=str(stage_dir), env=env)
    if not Path(wait_json).exists():
        raise SystemExit(
            f"runlocal exited rc={res.returncode} without writing "
            f"{wait_json} -- it died before finishing the local run")
    return res.returncode


def submit_cnf(stage_dir, entry_path, ledger_db, origin, env,
               runner=subprocess.run, dry_run=False) -> tuple[int, str]:
    """Submit a built cnf via core/prodtools_submit_driver.py; return
    (cluster_id, jobsub_id normalized to NNNN@schedd for jobwait).

    SystemExit if no cluster id came back (the driver already closed its
    ledger reservation — nothing to unwind) or if jobsub_id lacks "@schedd":
    a bare cluster id can't be jobwait'd and would only fail confusingly
    downstream instead of clearly at submit time.
    """
    driver = Path(__file__).resolve().parent / "prodtools_submit_driver.py"
    cmd = ["python3", str(driver),
           "--prodtools", str(prodtools_root()),
           "--entry", str(entry_path), "--ledger", str(ledger_db),
           "--origin", origin,
           "--wftop", WFTOP, "--wfproject", WFPROJECT]
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
