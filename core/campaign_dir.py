"""The campaign record: child names and one owner for a campaign's folder,
<graph data>/<prefix>/ (spec
docs/superpowers/specs/2026-10-05-point-campaign-records-design.md).

graph.closed_loop writes it for every campaign, from a shell or from the
MCP server, and the campaign service and the dashboard read it:
  campaign.json    the record: study, q, max_evals, picker, executor, host,
                   pid, started; ended and exit_code when it ends
  outcomes.jsonl   one line per finished child (the pool's Outcome)
  parent.lock      flock held by the closed_loop parent while it lives
  STOP             stop launching; the in-flight children drain
and, for an MCP launch, the server's own files:
  launch.json      the launch (command, the wrapper's pid), claimed O_EXCL
  lock             flock held by the launch wrapper (service/jobs.py)
  parent.log, rc   the wrapper's log and exit code

Stdlib only, plus core/locks.py and core/point_dir.py (write_atomic).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import locks
from point_dir import write_atomic

RECORD = "campaign.json"
OUTCOMES = "outcomes.jsonl"
PARENT_LOCK = "parent.lock"
MCP_LOCK = "lock"
LAUNCH = "launch.json"
RC = "rc"
STOP = "STOP"

CHILD_RE = re.compile(r"(.+)R(\d+)_00")

def child_name(prefix: str, i: int) -> str:
    """THE child-name shape `{prefix}R{i:02d}_00`; every producer and every
    parser goes through here so names cannot drift."""
    return f"{prefix}R{i:02d}_00"


def parse_child(name: str) -> Optional[Tuple[str, int]]:
    """(prefix, index) of a child name, or None. Only a name child_name
    would produce parses: not fooR5_00, not fooR00_01."""
    m = CHILD_RE.fullmatch(name)
    if not m:
        return None
    prefix, i = m.group(1), int(m.group(2))
    return (prefix, i) if child_name(prefix, i) == name else None


def is_child(prefix: str, name: str) -> bool:
    """`name` is a child of the campaign `prefix` (so `foo` never takes
    `foo2R00_00`)."""
    parsed = parse_child(name)
    return parsed is not None and parsed[0] == prefix


class CampaignBusy(RuntimeError):
    """Another closed_loop parent is alive on this prefix."""


class CampaignDir:
    def __init__(self, graph_data: Path, prefix: str):
        self.prefix = prefix
        self.path = Path(graph_data) / prefix

    def _file(self, name: str) -> Path:
        return self.path / name

    # -- the record --------------------------------------------------------

    @contextlib.contextmanager
    def start(self, record: Dict[str, Any]) -> Iterator[None]:
        """Hold parent.lock for the `with` block and write the record,
        replacing one an earlier, ended run of this prefix left
        (outcomes.jsonl keeps appending). CampaignBusy when another parent
        is alive here; a failed write raises."""
        self.path.mkdir(parents=True, exist_ok=True)
        lock = self._file(PARENT_LOCK)
        try:
            holder = locks.hold(lock)
            holder.__enter__()
        except locks.LockBusy:
            raise CampaignBusy(f"campaign {self.prefix!r} is already running "
                               f"(another parent holds {lock})") from None
        try:
            write_atomic(self._file(RECORD),
                         json.dumps(record, indent=1) + "\n")
            yield
        finally:
            holder.__exit__(None, None, None)

    def finish(self, exit_code: int) -> None:
        rec = json.loads(self._file(RECORD).read_text())
        rec.update(ended=time.time(), exit_code=exit_code)
        write_atomic(self._file(RECORD), json.dumps(rec, indent=1) + "\n")

    def record(self) -> Optional[Dict[str, Any]]:
        """The record, or None. A file that is not JSON raises ValueError."""
        try:
            rec = json.loads(self._file(RECORD).read_text())
        except FileNotFoundError:
            return None
        if not isinstance(rec, dict):
            raise ValueError(f"{self._file(RECORD)}: not a JSON object")
        return rec

    # -- outcomes ----------------------------------------------------------

    def append_outcome(self, outcome: Dict[str, Any]) -> None:
        """One line, in one write. A partial last line (a parent killed
        mid-append) is ended first, so this line never glues onto it."""
        path = self._file(OUTCOMES)
        line = json.dumps(outcome) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            if os.fstat(fd).st_size:
                with open(path, "rb") as fh:
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b"\n":
                        line = "\n" + line
            os.write(fd, line.encode())
        finally:
            os.close(fd)

    def outcomes(self, errors: Optional[List[str]] = None
                 ) -> Dict[str, Dict[str, Any]]:
        """{name: its last outcome line}; {} when there is none. A line that
        does not parse raises ValueError naming it; with `errors`, it is
        appended there instead and the other lines are still read."""
        path = self._file(OUTCOMES)
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                out[d["name"]] = d
            except (ValueError, KeyError, TypeError) as exc:
                msg = (f"{path}:{n}: unreadable outcome line "
                       f"({type(exc).__name__}: {exc})")
                if errors is None:
                    raise ValueError(msg) from None
                errors.append(msg)
        return out

    # -- liveness and the end ----------------------------------------------

    def alive(self) -> bool:
        """The closed_loop parent holds parent.lock, or an MCP launch
        wrapper holds lock (activate.sh, before closed_loop starts)."""
        return (locks.held(self._file(PARENT_LOCK))
                or locks.held(self._file(MCP_LOCK)))

    def exit_code(self) -> Optional[int]:
        """The record's exit_code, else the MCP wrapper's rc file."""
        try:
            rec = self.record()
        except (OSError, ValueError):
            rec = None
        if rec is not None and rec.get("exit_code") is not None:
            return int(rec["exit_code"])
        try:
            return int(self._file(RC).read_text())
        except (OSError, ValueError):
            return None

    def launched_by(self) -> Optional[str]:
        """"mcp" (launch.json), "shell" (a record only), or None (no sign of
        a launch)."""
        if self._file(LAUNCH).exists():
            return "mcp"
        return "shell" if self._file(RECORD).exists() else None

    def stopping(self) -> bool:
        return self._file(STOP).exists()

    def stop(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        self._file(STOP).touch()
        return self._file(STOP)

    # -- the MCP launch ----------------------------------------------------

    def write_launch(self, info: Dict[str, Any]) -> None:
        """Claim the prefix for an MCP launch; FileExistsError when it was
        claimed before."""
        self.path.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._file(LAUNCH), os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     0o644)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(info, indent=1) + "\n")

    def update_launch(self, **fields: Any) -> None:
        info = json.loads(self._file(LAUNCH).read_text())
        info.update(fields)
        write_atomic(self._file(LAUNCH), json.dumps(info, indent=1) + "\n")

    def launch(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self._file(LAUNCH).read_text())
        except FileNotFoundError:
            return None
