#!/usr/bin/env python3
"""Local counterparts to pipeline.py's three grid-contact functions.

The local output tree deliberately mirrors the /pnfs outstage layout
(<root>/<runid>/00/<index:05d>/) so listing is a base-path swap rather than a
second implementation. Nothing here may import anything outside the stdlib
plus core.paths.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
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
