#!/usr/bin/env python3
"""Local counterparts to pipeline.py's three grid-contact functions.

The local output tree deliberately mirrors the /pnfs outstage layout
(<root>/<runid>/00/<index:05d>/) so listing is a base-path swap rather than a
second implementation. Nothing here may import anything outside the stdlib
plus core.paths.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def fcl_path(state_dir: Path, stage: str, index: int) -> Path:
    return Path(state_dir) / "fcl" / f"{stage}_{index:05d}.fcl"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def default_proto_for(default_loc: str) -> str:
    """xroot for /pnfs, plain file for a local dir.

    mu2ejobfcl refuses to build a root:// URL for a path outside /pnfs
    ("root protocol requested but a file pathname does not start with
    /pnfs"), which is every path in a local input farm.
    """
    return "file" if default_loc.startswith("dir:/") \
        and not default_loc.startswith("dir:/pnfs") else "root"


def build_fcls(stage: str, cnf_name: str, stage_dir: Path, state_dir: Path,
               njobs: int, default_loc: str, env: dict) -> list[Path]:
    """Resolve one FCL per job index and record each one's hash.

    The hash sidecar is what lets `local-run` report an edited FCL without
    relying on the operator to remember a flag. Compare
    template-fcl-staleness, where an edit meant for one run silently persisted
    into later ones.
    """
    out_dir = Path(state_dir) / "fcl"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Prune this stage's previous set first. A build of 4 followed by a build
    # (or run) of 1 otherwise leaves indices 1-3 on disk, where edited_fcls'
    # unbounded glob reports them as hand-edited although nothing executed
    # them -- provenance that describes a run that did not happen.
    for stale in sorted(out_dir.glob(f"{stage}_*.fcl")) + \
            sorted(out_dir.glob(f"{stage}_*.fcl.sha256")):
        stale.unlink()
    written = []
    for index in range(njobs):
        cmd = ["mu2ejobfcl", "--jobdef", cnf_name, "--index", str(index),
               "--default-proto", default_proto_for(default_loc),
               "--default-loc", default_loc]
        print(f"$ (cd {stage_dir} && {shlex.join(cmd)})", flush=True)
        try:
            proc = subprocess.run(cmd, cwd=str(stage_dir), env=env, check=True,
                                  capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # check=True raises with stdout/stderr CAPTURED, and str(exc) omits
            # both -- so an rc!=0 here would be as opaque as the two incidents
            # this repo already has of that shape
            # (jobsub-disk-quota-stderr-swallowed, sourced-env-stderr-swallowed).
            # Same handling submit_stage gives mu2ejobsub.
            print(e.stdout or "")
            print("MU2EJOBFCL STDERR:\n" + (e.stderr or "(empty)"),
                  file=sys.stderr)
            raise
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


DEFAULT_POOL = 4


def _run_one(stage: str, config: str, runid: int, state_dir: Path,
             index: int, events: int, env: dict) -> tuple[int, int]:
    d = job_dir(config, runid, index)
    d.mkdir(parents=True, exist_ok=True)
    cmd = ["mu2e", "-c", str(fcl_path(state_dir, stage, index)),
           "-n", str(events)]
    log = d / f"{stage}_{index:05d}.log"
    try:
        proc = subprocess.run(cmd, cwd=str(d), env=env,
                              capture_output=True, text=True)
    except Exception as exc:
        log.write_text(f"{type(exc).__name__}: {exc}")
        return index, 1
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


def resolve_scale(values, default: int, stage: str) -> int:
    """Resolve one repeatable --local-njobs/--local-events flag for a stage."""
    if not values:
        return default
    bare, per_stage = default, {}
    for raw in values:
        item = str(raw)
        if "=" in item:
            key, _, val = item.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected <stage>=<int>")
            try:
                parsed = int(val.strip())
            except ValueError:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected <stage>=<int>")
            if parsed < 1:
                raise ValueError(
                    f"bad per-stage value {item!r}: expected an int >= 1")
            per_stage[key] = parsed
        else:
            try:
                parsed = int(item)
            except ValueError:
                raise ValueError(
                    f"bad value {item!r}: expected an int or <stage>=<int>")
            if parsed < 1:
                raise ValueError(
                    f"bad value {item!r}: expected an int >= 1")
            bare = parsed
    return per_stage.get(stage, bare)


def local_farm(stage: str, config: str, sources: list, state_dir) -> tuple:
    """Hard-link a prior stage's local outputs into ONE dir, as the grid path
    hard-links them into one /pnfs dir.

    mu2ejobdef's --inputs accepts BASENAMES only, and --default-loc dir:DIR
    then assumes every one of them lives in DIR. A local stage's outputs are
    spread one-dir-per-job-index (<runid>/00/00000, .../00001, ...), so they
    need collecting exactly as the grid ones do -- same constraint, different
    filesystem. See pipeline.stage_hardlink_farm, which this mirrors.

    Hard links, not symlinks, and not copies: the .art files are large, and a
    hard link costs nothing. Falls back to a symlink across a device boundary,
    which is fine locally -- the xrootd-door restriction that forces hard
    links on /pnfs does not apply to a POSIX read.

    The farm lives beside the run tree at <local_outstage>/staged/<stage>.
    next_runid only counts digit-named children, so "staged" cannot be
    mistaken for a run id.
    """
    staged = local_outstage(config) / "staged" / stage
    if staged.is_dir():
        for p in staged.iterdir():
            p.unlink()
    staged.mkdir(parents=True, exist_ok=True)
    names = []
    for src in sources:
        src = Path(src)
        link = staged / src.name
        try:
            os.link(src, link)
        except OSError:
            link.symlink_to(src)
        names.append(src.name)
    basenames_file = Path(state_dir) / f"{stage}_basenames.txt"
    basenames_file.write_text("\n".join(names) + "\n")
    print(f"[{stage}] staged {len(names)} local input(s) -> {staged}")
    return staged, basenames_file


def clamp_merge_factor(configured: int, n_inputs: int) -> int:
    """concat merges 200 files on the grid; a local run may have produced 1.

    mu2ejobdef emits ZERO jobs when the merge factor exceeds the input count,
    and a zero-job cnf is not an error -- local-run would then report "0 ok, 0
    failed" and list no outputs, which reads exactly like a stage that ran and
    found nothing.
    """
    return max(1, min(configured, n_inputs))
