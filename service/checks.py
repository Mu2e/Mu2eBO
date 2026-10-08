"""The autoresearch MCP server's study tools, as plain Python: check a study
exactly as `python -m graph.check_study` does, and list, show and read about
studies. No MCP here; service/server.py wraps each method as a tool.

A check is a detached job (bash, then check_study --json) with its own
directory, <data root>/autoresearch_graph_data/check_jobs/<job_id>/:
job.json (target, args, command, pid, start time), lock, report.json,
stderr.log, and rc, written last. It is launched by service/jobs.py, which
hands the job a lock it holds exactly as long as its processes live: a check
survives a restart of the server or the client, and a killed one reads as
"lost", not "running" forever. The pid in job.json is there to kill a stuck job by hand;
liveness never depends on it.

Only the standard library and core/paths.py, core/study.py, imported bare
with core/ on sys.path like every engine module (a qualified core.study
would be a second copy of the module; see tests/test_modes.py
TestSingleModuleCopy). Never modes (nor graph.run, which
imports it), so one broken study file on the study path cannot stop the
server that reports it.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths  # noqa: E402
import study as st  # noqa: E402

from service.jobs import last_lines, lock_held, spawn_detached  # noqa: E402

TAIL_LINES = 40
JOB_SCRIPT = ('source ./activate.sh >/dev/null 2>"$1/stderr.log" && '
              'PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study '
              '"${@:2}" --json >"$1/report.json" 2>>"$1/stderr.log"; '
              'echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"')
_DRAFT_NAME = re.compile(r"[A-Za-z0-9_]+")
NOT_JSON = "check_study's output is not JSON"


class CheckService:
    def __init__(self, env: Optional[Mapping[str, str]] = None):
        self.env = dict(os.environ if env is None else env)
        root = self.env.get("AUTORESEARCH_DATA_ROOT")
        self.data_root = Path(root) if root else paths.DATA_ROOT
        self.drafts_dir = self.data_root / "study_drafts"
        self.jobs_dir = self.data_root / paths.GRAPH_DATA.name / "check_jobs"

    # -- the read-only queries --------------------------------------------

    def study_files(self) -> List[Path]:
        return st.study_files(paths.MODES_DIR,
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
                entry.update(loads=False, error=st.load_error_text(exc))
            else:
                entry.update(
                    knobs=[k.name for k in study.knobs],
                    objectives=[o.name for o in study.objectives],
                    board=Path(study.leaderboard_rel).name)
            out.append(entry)
        return out

    def study_path(self, name: str) -> Path:
        """The file of the study `name` on the study path; ValueError
        naming the known ones when there is none."""
        files = self.study_files()
        path = st.study_named(files, name)
        if path is None:
            raise ValueError(f"no study named {name!r} on the study path; "
                             f"known: {sorted(p.stem for p in files)}")
        return path

    def show_study(self, name: str) -> Dict[str, Any]:
        path = self.study_path(name)
        try:
            doc = json.loads(path.read_text())
        except ValueError as exc:
            raise ValueError(f"{path}: not JSON: {exc}") from exc
        return {"path": str(path), "study": doc}

    def study_guide(self) -> str:
        return (paths.MODES_DIR / "README.md").read_text()

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
        elif study.startswith("-"):
            # check_study would parse it as an option ("--help": usage on
            # stdout, exit 0, no report).
            raise ValueError(f"study {study!r} starts with '-': give a study "
                             f"name or a .json path")
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
        pid = spawn_detached(job_dir, JOB_SCRIPT, args, self.env)
        (job_dir / "job.json").write_text(json.dumps({
            "job_id": job_id, "target": target, "args": args,
            "command": command, "pid": pid, "started": time.time(),
        }, indent=1) + "\n")
        return {"job_id": job_id, "target": target, "command": command}

    def _job_dir(self, job_id: str) -> Path:
        if (not job_id or "/" in job_id or job_id in (".", "..")
                or not (self.jobs_dir / job_id / "job.json").is_file()):
            raise ValueError(f"no check job {job_id!r} in {self.jobs_dir}")
        return self.jobs_dir / job_id

    def check_result(self, job_id: str) -> Dict[str, Any]:
        job_dir = self._job_dir(job_id)
        job = json.loads((job_dir / "job.json").read_text())
        rc = job_dir / "rc"
        # rc first, then the lock, then rc again: a job that ends between
        # the two reads is done, never lost.
        if rc.exists():
            state = "done"
        elif lock_held(job_dir / "lock"):
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
            out["stderr_tail"] = last_lines(log.read_text(errors="replace"),
                                            TAIL_LINES)
        if state == "done":
            out["exit_code"] = int(rc.read_text())
            if out["exit_code"] != 2:
                try:
                    out["report"] = json.loads(
                        (job_dir / "report.json").read_text())
                except (OSError, ValueError):
                    out["error"] = NOT_JSON
        return out
