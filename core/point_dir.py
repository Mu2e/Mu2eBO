"""The point record: one owner for a point's state folder,
<grid>/<config>/state/.

Every writer (the scheduler, the per-point graph, score, graph.run) and
every reader (closed_loop's busy check, check_study, the campaign service,
the dashboard) goes through PointDir, so the file names and what they mean
live here only:
  point.json               the point (claim)
  <step>_submit.json       the kit and its version when the step was
                           submitted, written just before the submit (a
                           handle without one predates the record)
  <step>_cluster.txt       a step's handle: it was submitted
  <step>_status.json       its last status poll (the dashboard's only)
  <step>_results.json      its results: it is done (resume adopts it)
  broken.txt               why the point failed, first writer wins:
                           "step <step>: <reason>" or "<reason>"
  summary.json, evaluate_result.json   what score wrote
  derived.json, geom.txt, preflight_verdict.json   the pre-check's files
  run.lock                 flock held by the graph.run running the point

Stdlib only, plus core/locks.py: the service imports it without modes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import (Any, ContextManager, Dict, Iterable, NamedTuple,
                    Optional, Tuple)

import locks

POINT = "point.json"
BROKEN = "broken.txt"
RUN_LOCK = "run.lock"
SUMMARY = "summary.json"
RESULT = "evaluate_result.json"
VERDICT = "preflight_verdict.json"
DERIVED = "derived.json"
GEOM = "geom.txt"

BROKEN_STEP_RE = re.compile(r"step (\S+): (.*)")


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


class PointMismatch(ValueError):
    """point.json records a different point under this config name."""


class Broken(NamedTuple):
    step: Optional[str]     # the step that broke the point, if one did
    reason: str             # the text after "step <step>: ", else all of it
    text: str               # broken.txt's first line


class PointDir:
    def __init__(self, state: Path):
        self.state = Path(state)

    @classmethod
    def of(cls, grid_root: Path, config: str) -> "PointDir":
        return cls(Path(grid_root) / config / "state")

    def path(self, name: str) -> Path:
        return self.state / name

    def _json(self, name: str) -> Optional[Any]:
        try:
            text = self.path(name).read_text()
        except FileNotFoundError:
            return None
        return json.loads(text)

    # -- point.json --------------------------------------------------------

    def point(self) -> Optional[Dict[str, Any]]:
        """The point, or None; a file that is not a JSON object raises
        ValueError."""
        point = self._json(POINT)
        if point is not None and not isinstance(point, dict):
            raise ValueError(f"{self.path(POINT)}: not a JSON object")
        return point

    def claim(self, point: Dict[str, Any]) -> None:
        """Write point.json, or check that the one there records this
        point. A resume adopts the steps already submitted: they were
        measured the way the study said THEN, so a changed measurement must
        not stamp their numbers with its measure_sha."""
        self.state.mkdir(parents=True, exist_ok=True)
        path = self.path(POINT)
        if not path.exists():
            write_atomic(path, json.dumps(point, indent=1, sort_keys=True))
            return
        old = json.loads(path.read_text())
        if "measure_basis_sha" not in old:
            raise PointMismatch(
                f"{path} has no measure_basis_sha (written before "
                f"point.json recorded how its point is measured), so a "
                f"resume cannot tell whether the study's measurement "
                f"changed since this point was submitted; use a new "
                f"config name")
        was, now = old["measure_basis_sha"], point["measure_basis_sha"]
        if was != now:
            raise PointMismatch(
                f"{path}: the study's measurement changed since "
                f"this point was submitted ({was[:12]} -> {now[:12]}); "
                f"use a new config name")
        if "executor" not in old:
            raise PointMismatch(
                f"{path} has no executor (written before "
                f"point.json recorded one), so a resume cannot tell "
                f"whether it would switch executors mid-point; use a "
                f"new config name")
        if old["executor"] != point["executor"]:
            raise PointMismatch(
                f"{path}: this point was started with --executor "
                f"{old['executor']}; rerun it with --executor "
                f"{old['executor']}, or use a new config name")
        if old != point:
            raise PointMismatch(
                f"{path} records a different point {old}; refusing "
                f"to mix two points under one config name")

    # -- steps -------------------------------------------------------------

    def handle(self, step: str) -> Optional[str]:
        try:
            return self.path(f"{step}_cluster.txt").read_text().strip()
        except FileNotFoundError:
            return None

    def write_handle(self, step: str, handle: str) -> None:
        write_atomic(self.path(f"{step}_cluster.txt"), handle + "\n")

    def write_submit(self, step: str, kit: str, version: str) -> None:
        """Record the kit's version before its submit: a kill during the
        submit can leave the kit a job of this version and no handle. A
        version that is not a string (a kit not started) raises ValueError:
        submit_version could not read it back."""
        if not isinstance(version, str):
            raise ValueError(f"step {step!r}: kit {kit!r} reports version "
                             f"{version!r}, not a string; no submit record "
                             f"written")
        write_atomic(self.path(f"{step}_submit.json"), json.dumps(
            {"kit": kit, "kit_version": version}, indent=1, sort_keys=True))

    def submit_version(self, step: str) -> Optional[str]:
        """The kit's version when the step was submitted; None when it was
        never submitted, or its handle predates the record (unknown, never
        guessed). A file that is not a submit record raises ValueError."""
        path = self.path(f"{step}_submit.json")
        try:
            rec = self._json(path.name)
        except ValueError as exc:
            raise ValueError(f"{path}: not JSON ({exc})") from exc
        if rec is None:
            return None
        if not (isinstance(rec, dict) and isinstance(rec.get("kit"), str)
                and isinstance(rec.get("kit_version"), str)):
            raise ValueError(f"{path}: not a submit record (a JSON object "
                             f"with string kit and kit_version): {rec!r}")
        return rec["kit_version"]

    def submitted(self, steps: Iterable[str]) -> Dict[str, str]:
        """{step: version submitted under} for every step of `steps` with a
        submit record and no results: in flight, or cut short mid-submit."""
        out = {}
        for step in steps:
            version = self.submit_version(step)
            if (version is not None
                    and not self.path(f"{step}_results.json").exists()):
                out[step] = version
        return out

    def status(self, step: str) -> Tuple[Optional[dict], Optional[str]]:
        """(record, error): the last status poll, or why it could not be
        read; (None, None) when there is none."""
        path = self.path(f"{step}_status.json")
        try:
            rec = json.loads(path.read_text())
            if not isinstance(rec, dict):
                raise ValueError("not a JSON object")
            return rec, None
        except FileNotFoundError:
            return None, None
        except (OSError, ValueError) as exc:
            return None, f"unreadable {path.name}: {exc}"

    def write_status(self, step: str, status: Dict[str, Any]) -> None:
        write_atomic(self.path(f"{step}_status.json"), json.dumps(status))

    def results(self, step: str) -> Optional[Dict[str, Any]]:
        return self._json(f"{step}_results.json")

    def write_results(self, step: str, record: Dict[str, Any]) -> None:
        write_atomic(self.path(f"{step}_results.json"),
                     json.dumps(record, indent=1, sort_keys=True))

    def adopted(self, steps: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """{step: record} for every step of `steps` that finished."""
        out = {}
        for step in steps:
            record = self.results(step)
            if record is not None:
                out[step] = record
        return out

    # -- broken.txt --------------------------------------------------------

    def mark_broken(self, reason: str, step: Optional[str] = None) -> bool:
        """Record why the point failed, unless something already did (the
        first failure is the cause; the rest follow from it). True when
        this call wrote it."""
        path = self.path(BROKEN)
        if path.exists():
            return False
        self.state.mkdir(parents=True, exist_ok=True)
        text = f"step {step}: {reason}" if step is not None else reason
        write_atomic(path, text + "\n")
        return True

    def broken(self) -> Optional[Broken]:
        try:
            lines = self.path(BROKEN).read_text().splitlines()
        except FileNotFoundError:
            return None
        first = lines[0].strip() if lines else ""
        m = BROKEN_STEP_RE.match(first)
        if m:
            return Broken(m.group(1), m.group(2), first)
        return Broken(None, first, first)

    # -- scoring -----------------------------------------------------------

    def write_summary(self, summary: Dict[str, Any]) -> None:
        write_atomic(self.path(SUMMARY),
                     json.dumps(summary, indent=1, sort_keys=True))

    def write_result(self, result: Dict[str, Any]) -> None:
        write_atomic(self.path(RESULT), json.dumps(result, indent=1))

    # -- liveness ----------------------------------------------------------

    def run_lock(self) -> ContextManager[None]:
        """Held by the graph.run running this point; LockBusy (after
        locks.hold's wait) when another one holds it."""
        self.state.mkdir(parents=True, exist_ok=True)
        return locks.hold(self.path(RUN_LOCK))

    def running(self) -> bool:
        return locks.held(self.path(RUN_LOCK))

    def ever_ran(self) -> bool:
        """A graph.run of this code started here (its lock file stays)."""
        return self.path(RUN_LOCK).exists()

    def started(self) -> bool:
        """point.json or a handle: something ran or submitted under this
        name."""
        return (self.path(POINT).exists()
                or any(self.state.glob("*_cluster.txt")))

    # -- what a reader shows ----------------------------------------------

    def step_state(self, step: str) -> Dict[str, Any]:
        """A step's state from its files:
          done     <step>_results.json
          failed   its status says failed or cancelled, or broken.txt
                   names it (the step that broke the point is failed
                   whatever its last poll said)
          working  a status, or a handle alone (a run from before the
                   status file)
          waiting  none of these
        plus the last poll's message, progress, time and poll_s, the
        handle's mtime and any read error."""
        rec, error = self.status(step)
        out: Dict[str, Any] = {"state": "waiting", "message": "",
                               "progress": None, "error": error,
                               "handle_mtime": None, "poll_time": None,
                               "poll_s": None}
        cluster = self.path(f"{step}_cluster.txt")
        try:
            out["handle_mtime"] = cluster.stat().st_mtime
        except OSError:
            pass
        if rec is not None:
            out["message"] = str(rec.get("message", ""))
            out["progress"] = rec.get("progress")
            try:
                out["poll_time"] = float(rec["time"])
                out["poll_s"] = float(rec.get("poll_s", 0))
            except (KeyError, TypeError, ValueError) as exc:
                out["poll_time"] = out["poll_s"] = None
                out["error"] = f"bad status record: {exc}"
        broken = self.broken()
        if self.path(f"{step}_results.json").exists():
            out["state"] = "done"
        elif broken is not None and broken.step == step:
            out.update(state="failed", message=broken.reason)
        elif rec is not None and rec.get("state") in ("failed", "cancelled"):
            out["state"] = "failed"
        elif rec is not None or error is not None or cluster.exists():
            out["state"] = "working"
        return out
