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
