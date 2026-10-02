"""The autoresearch MCP server's study tools, as plain Python: check a study
exactly as `python -m graph.check_study` does, and list, show and read about
studies. No MCP here; service/server.py wraps each method as a tool.

A check is a detached job (bash, then check_study --json) with its own
directory, <data root>/autoresearch_graph_data/check_jobs/<job_id>/:
job.json (target, args, command, pid, start time), lock, report.json,
stderr.log, and rc, written last. The server takes an exclusive flock on
`lock` before the launch and hands that file to the job (pass_fds), so the
lock is held exactly as long as the job's processes live: a check survives a
restart of the server or the client, and a killed one reads as "lost", not
"running" forever. The pid in job.json is there to kill a stuck job by hand;
liveness never depends on it.

Only the standard library and core.paths / core.study: never modes (nor
graph.run, which imports it), so one broken study file on the study path
cannot stop the server that reports it.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core import paths
from core import study as st

MODES_DIR = paths.REPO_ROOT / "mode_specs"
TAIL_LINES = 40
JOB_SCRIPT = ('source ./activate.sh >/dev/null 2>"$1/stderr.log" && '
              'PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study '
              '"${@:2}" --json >"$1/report.json" 2>>"$1/stderr.log"; '
              'echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"')
_DRAFT_NAME = re.compile(r"[A-Za-z0-9_]+")
NOT_JSON = "check_study's output is not JSON"


def _error_text(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


class CheckService:
    def __init__(self, env: Optional[Mapping[str, str]] = None):
        self.env = dict(os.environ if env is None else env)
        root = self.env.get("AUTORESEARCH_DATA_ROOT")
        self.data_root = Path(root) if root else paths.DATA_ROOT
        self.drafts_dir = self.data_root / "study_drafts"
        self.jobs_dir = self.data_root / paths.GRAPH_DATA.name / "check_jobs"

    # -- the read-only queries --------------------------------------------

    def study_files(self) -> List[Path]:
        return st.study_files(MODES_DIR,
                              self.env.get("AUTORESEARCH_STUDY_PATH"))

    def list_studies(self) -> List[Dict[str, Any]]:
        out = []
        for path in self.study_files():
            entry = {"name": path.stem, "path": str(path), "loads": True,
                     "error": None, "knobs": None, "objectives": None,
                     "board": None}
            try:
                study = st.load_study_file(path)
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                entry.update(loads=False, error=_error_text(exc))
            else:
                entry.update(
                    knobs=[k.name for k in study.knobs],
                    objectives=[o.name for o in study.objectives],
                    board=Path(study.leaderboard_rel).name)
            out.append(entry)
        return out

    def show_study(self, name: str) -> Dict[str, Any]:
        files = self.study_files()
        for path in files:
            if path.stem == name:
                try:
                    doc = json.loads(path.read_text())
                except ValueError as exc:
                    raise ValueError(f"{path}: not JSON: {exc}") from exc
                return {"path": str(path), "study": doc}
        raise ValueError(f"no study named {name!r} on the study path; "
                         f"known: {sorted(p.stem for p in files)}")

    def study_guide(self) -> str:
        return (MODES_DIR / "README.md").read_text()

    # -- check jobs -------------------------------------------------------

    def start_check(self, study: str = "", study_json: Optional[dict] = None,
                    x: Optional[Sequence[float]] = None,
                    executor: str = "grid",
                    parallel: Optional[int] = None) -> Dict[str, Any]:
        if bool(study) == (study_json is not None):
            raise ValueError("start_check: give exactly one of study (a "
                             "study name or a .json path) and study_json")
        if study_json is not None:
            name = (study_json.get("name")
                    if isinstance(study_json, dict) else None)
            if not (isinstance(name, str) and _DRAFT_NAME.fullmatch(name)):
                raise ValueError(
                    f"study_json.name must be a string matching "
                    f"[A-Za-z0-9_]+ (it names the draft file "
                    f"study_drafts/<name>.json); got "
                    f"{name if isinstance(study_json, dict) else study_json!r}")
            self.drafts_dir.mkdir(parents=True, exist_ok=True)
            draft = self.drafts_dir / f"{name}.json"
            draft.write_text(json.dumps(study_json, indent=1) + "\n")
            target = str(draft)
        elif study.endswith(".json") or "/" in study:
            # The job runs from the repo root, not this server's directory.
            target = str(Path(study).absolute())
        else:
            target = study
        args = [target]
        if x is not None:
            args.append("--x=" + ",".join(repr(float(v)) for v in x))
        args += ["--executor", executor]
        if parallel is not None:
            args += ["--parallel", str(parallel)]
        job_id = (f"{Path(target).stem}-{time.strftime('%Y%m%d-%H%M%S')}-"
                  f"{secrets.token_hex(2)}")
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        command = ('PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study '
                   + shlex.join([*args, "--json"]))
        fd = os.open(job_dir / "lock", os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            proc = subprocess.Popen(
                ["bash", "-c", JOB_SCRIPT, "_", str(job_dir), *args],
                cwd=paths.REPO_ROOT, env=self.env,
                # The server's own stdin/stdout carry the MCP stream.
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
                pass_fds=(fd,))
        finally:
            os.close(fd)
        # Reap the job when it ends: no zombie in a long-lived server (the
        # lock, not this thread, says whether it is running).
        threading.Thread(target=proc.wait, daemon=True).start()
        (job_dir / "job.json").write_text(json.dumps({
            "job_id": job_id, "target": target, "args": args,
            "command": command, "pid": proc.pid, "started": time.time(),
        }, indent=1) + "\n")
        return {"job_id": job_id, "target": target, "command": command}

    def _job_dir(self, job_id: str) -> Path:
        if (not job_id or "/" in job_id or job_id in (".", "..")
                or not (self.jobs_dir / job_id / "job.json").is_file()):
            raise ValueError(f"no check job {job_id!r} in {self.jobs_dir}")
        return self.jobs_dir / job_id

    @staticmethod
    def _locked(path: Path) -> bool:
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(fd)
        return False

    def check_result(self, job_id: str) -> Dict[str, Any]:
        job_dir = self._job_dir(job_id)
        job = json.loads((job_dir / "job.json").read_text())
        rc = job_dir / "rc"
        # rc first, then the lock, then rc again: a job that ends between
        # the two reads is done, never lost.
        if rc.exists():
            state = "done"
        elif self._locked(job_dir / "lock"):
            state = "running"
        else:
            state = "done" if rc.exists() else "lost"
        out = {"job_id": job_id, "state": state, "exit_code": None,
               "elapsed_s": None, "report": None, "stderr_tail": "",
               "error": None}
        end = rc.stat().st_mtime if state == "done" else time.time()
        out["elapsed_s"] = round(end - job["started"], 1)
        log = job_dir / "stderr.log"
        if log.exists():
            lines = log.read_text(errors="replace").splitlines()
            out["stderr_tail"] = "\n".join(lines[-TAIL_LINES:])
        if state == "done":
            out["exit_code"] = int(rc.read_text())
            if out["exit_code"] != 2:
                try:
                    out["report"] = json.loads(
                        (job_dir / "report.json").read_text())
                except (OSError, ValueError):
                    out["error"] = NOT_JSON
        return out
