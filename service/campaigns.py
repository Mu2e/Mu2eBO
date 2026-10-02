"""The autoresearch MCP server's campaign tools, as plain Python: start a
`graph.closed_loop` campaign (a dry run through --check-only, then a
confirmed detached launch), stop it, follow it, and read a study's
leaderboard. No MCP here; service/server.py wraps each method as a tool.

A campaign is named by its --name-prefix; its children are
<prefix>R<n>_00 (matched exactly by is_child, so `foo` never takes `foo2`).
Status reads only what every campaign leaves behind, so it covers campaigns
started from a shell too:
  <graph data>/closed_loop_logs/<child>.log   one log per child
  <grid data>/<child>/state/                  point.json, broken.txt, ...
  the study's board                           the rows
  <graph data>/<prefix>/STOP                  draining
A campaign launched here also has <graph data>/<prefix>/campaign.json,
parent.log, lock (held by the parent for as long as it lives; see
service/jobs.py) and rc. A shell-launched parent is found by a scan of this
user's processes (/proc/*/cmdline), which covers the whole host: a campaign
of the same prefix under another data root counts as live.

Only the standard library and bare core/ modules (paths, study, leaderboard):
never modes, so one broken study file cannot stop the server.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths  # noqa: E402
import study as st  # noqa: E402
from leaderboard import Leaderboard  # noqa: E402

from service.checks import CheckService  # noqa: E402
from service.jobs import lock_held, spawn_detached  # noqa: E402

PREFIX_RE = re.compile(r"[A-Za-z0-9_]+")
LOG_TAIL = 20
OUTPUT_TAIL = 40
DRY_SCRIPT = ('source ./activate.sh >/dev/null && PYTHONPATH= '
              '"$AUTORESEARCH_PYTHON" -m graph.closed_loop "$@" --check-only')
LAUNCH_SCRIPT = ('source ./activate.sh >/dev/null 2>"$1/parent.log" && '
                 'PYTHONPATH= "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop '
                 '"${@:2}" >>"$1/parent.log" 2>&1; '
                 'echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"')
BANNER = "[closed_loop] study="
REFUSED = "[closed_loop] REFUSED: "
SPENT = "this prefix is spent: dry-run again and launch under a new prefix"


def is_child(prefix: str, name: str) -> bool:
    """`name` is a child of the campaign `prefix`: <prefix>R<n>_00."""
    return re.fullmatch(re.escape(prefix) + r"R\d+_00", name) is not None


def _check_prefix(prefix: str) -> None:
    if not (isinstance(prefix, str) and PREFIX_RE.fullmatch(prefix)):
        raise ValueError(f"name_prefix must match [A-Za-z0-9_]+ (it names "
                         f"the campaign's folder and its children); got "
                         f"{prefix!r}")


def _flag(argv: List[str], flag: str) -> Optional[str]:
    """The value of `flag` in argv, as `flag value` or `flag=value`."""
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a[len(flag) + 1:]
    return None


def _last_line(path: Path) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return next((ln for ln in reversed(lines) if ln.strip()), "")


def _tail(path: Path, n: int) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def _refusals(text: str) -> List[str]:
    return [ln[len(REFUSED):] for ln in text.splitlines()
            if ln.startswith(REFUSED)]


class CampaignService:
    check_timeout_s = 600
    launch_wait_s = 600

    def __init__(self, env: Optional[Mapping[str, str]] = None):
        self.checks = CheckService(env)
        self.env = self.checks.env
        self.data_root = self.checks.data_root
        self.graph_data = self.data_root / paths.GRAPH_DATA.name
        self.grid_data = self.data_root / paths.GRID_DATA_ROOT.name
        self.logs_dir = self.graph_data / "closed_loop_logs"

    def camp_dir(self, prefix: str) -> Path:
        return self.graph_data / prefix

    # -- what is running ---------------------------------------------------

    @staticmethod
    def _processes() -> List[Tuple[int, List[str]]]:
        """(pid, argv) of this user's processes."""
        out = []
        uid = os.getuid()
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.stat(f"/proc/{entry}").st_uid != uid:
                    continue
                raw = Path(f"/proc/{entry}/cmdline").read_bytes()
            except OSError:
                continue            # gone while we looked, or not ours
            argv = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
            if argv:
                out.append((int(entry), argv))
        return out

    def _scan(self) -> Tuple[Dict[str, Tuple[int, Optional[str]]], set]:
        """Live closed_loop parents {prefix: (pid, study)} and the configs
        of live graph.run children."""
        parents, children = {}, set()
        for pid, argv in self._processes():
            if "graph.closed_loop" in argv:
                prefix = _flag(argv, "--name-prefix")
                if prefix:
                    parents.setdefault(prefix, (pid, _flag(argv, "--study")))
            elif "graph.run" in argv:
                config = _flag(argv, "--config")
                if config:
                    children.add(config)
        return parents, children

    # -- the board ---------------------------------------------------------

    def _load_study(self, name: str):
        files = self.checks.study_files()
        for path in files:
            if path.stem == name:
                return st.load_study_file(path)
        raise ValueError(f"no study named {name!r} on the study path; "
                         f"known: {sorted(p.stem for p in files)}")

    def _board(self, study) -> Leaderboard:
        # Built from this service's data root, as board_for builds it from
        # the process's (they agree in the server, where env is the
        # process's own).
        rel = study.leaderboard_rel
        return Leaderboard.for_study(
            study,
            path=(self.data_root / paths.LEADERBOARD_LIVE.name
                  / Path(rel).name),
            archive_path=paths.leaderboard_archive(rel))

    @staticmethod
    def _rows(study, points, prefix: Optional[str]) -> List[Dict[str, Any]]:
        obj = study.objectives[0]
        if prefix is not None:
            points = [p for p in points if is_child(prefix, p.cfg)]

        def key(p):
            v = p.y.get(obj.name)
            if v is None:
                return (1, 0.0)
            return (0, -v if obj.direction == "max" else v)
        return [{"config": p.cfg, "x": dict(zip(study.knob_names, p.x)),
                 "values": dict(p.y)} for p in sorted(points, key=key)]

    def leaderboard(self, study: str, name_prefix: Optional[str] = None,
                    top: int = 20) -> Dict[str, Any]:
        s = self._load_study(study)
        board = self._board(s)
        points = board.load()
        obj = s.objectives[0]
        return {"study": s.name, "board": str(board.path),
                "n_rows": len(points),
                "objective": {"name": obj.name, "direction": obj.direction},
                "rows": self._rows(s, points, name_prefix)[:max(top, 0)]}

    # -- status ------------------------------------------------------------

    def _campaign_json(self, prefix: str) -> Optional[dict]:
        try:
            return json.loads((self.camp_dir(prefix) / "campaign.json")
                              .read_text())
        except (OSError, ValueError):
            return None

    def _children(self, prefix: str) -> List[str]:
        if not self.logs_dir.is_dir():
            return []
        return sorted(p.stem for p in self.logs_dir.glob("*.log")
                      if is_child(prefix, p.stem))

    def _parent(self, prefix: str, parents) -> Dict[str, Any]:
        cdir = self.camp_dir(prefix)
        record = self._campaign_json(prefix)
        if (cdir / "campaign.json").exists():
            rc = cdir / "rc"
            exit_code = None
            if rc.exists():
                try:
                    exit_code = int(rc.read_text())
                except ValueError:
                    exit_code = None
            return {"alive": lock_held(cdir / "lock"),
                    "pid": (record or {}).get("pid"),
                    "launched_by": "mcp", "exit_code": exit_code,
                    "log_tail": _tail(cdir / "parent.log", LOG_TAIL)}
        if prefix in parents:
            return {"alive": True, "pid": parents[prefix][0],
                    "launched_by": "shell", "exit_code": None,
                    "log_tail": ""}
        return {"alive": False, "pid": None, "launched_by": None,
                "exit_code": None, "log_tail": ""}

    def _study_of(self, prefix: str, parents, children) -> Optional[str]:
        record = self._campaign_json(prefix)
        if record and record.get("study"):
            return record["study"]
        if prefix in parents and parents[prefix][1]:
            return parents[prefix][1]
        for name in children:
            try:
                point = json.loads((self.grid_data / name / "state"
                                    / "point.json").read_text())
            except (OSError, ValueError):
                continue
            if point.get("study"):
                return point["study"]
        return None

    def campaign_status(self, name_prefix: Optional[str] = None):
        parents, running = self._scan()
        if name_prefix is None:
            return self._campaigns(parents)
        prefix = name_prefix
        names = self._children(prefix)
        study_name = self._study_of(prefix, parents, names)
        scored, rows, best, board_error = set(), 0, None, None
        if study_name is not None:
            try:
                s = self._load_study(study_name)
                mine = [p for p in self._board(s).load()
                        if is_child(prefix, p.cfg)]
            except ValueError as exc:
                board_error = str(exc)
            else:
                scored = {p.cfg for p in mine}
                rows = len(mine)
                ranked = self._rows(s, mine, None)
                best = ranked[0] if ranked else None
        children = []
        for name in names:
            if name in scored:
                state = "scored"
            elif (self.grid_data / name / "state" / "broken.txt").exists():
                state = "broken"
            elif name in running:
                state = "running"
            else:
                state = "ended without a row"
            children.append({"name": name, "state": state,
                             "last_line": _last_line(
                                 self.logs_dir / f"{name}.log")})
        return {"prefix": prefix, "study": study_name,
                "parent": self._parent(prefix, parents),
                "stopping": (self.camp_dir(prefix) / "STOP").exists(),
                "children": children, "rows": rows, "best": best,
                "board_error": board_error}

    def _campaigns(self, parents) -> List[Dict[str, Any]]:
        out = {}
        if self.graph_data.is_dir():
            for record_path in self.graph_data.glob("*/campaign.json"):
                prefix = record_path.parent.name
                record = self._campaign_json(prefix) or {}
                out[prefix] = {"prefix": prefix, "study": record.get("study"),
                               "alive": lock_held(record_path.parent / "lock"),
                               "launched_by": "mcp"}
        for prefix, (pid, study_name) in parents.items():
            out.setdefault(prefix, {"prefix": prefix, "study": study_name,
                                    "alive": True, "launched_by": "shell"})
        return [out[p] for p in sorted(out)]

    # -- stop --------------------------------------------------------------

    def stop_campaign(self, name_prefix: str) -> Dict[str, Any]:
        _check_prefix(name_prefix)
        parents, running = self._scan()
        names = self._children(name_prefix)
        parent = self._parent(name_prefix, parents)
        cdir = self.camp_dir(name_prefix)
        warning = None
        if (parent["launched_by"] is None and not names):
            warning = f"no sign of a campaign named {name_prefix!r}"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "STOP").touch()
        return {"stop_file": str(cdir / "STOP"),
                "parent_alive": parent["alive"],
                "children_running": sum(1 for n in names if n in running),
                "warning": warning}

    # -- start -------------------------------------------------------------

    def budget(self, study: str, max_evals: int,
               executor: str) -> Optional[Dict[str, int]]:
        """Jobs a campaign would run: prodtools steps' njobs per point."""
        try:
            s = self._load_study(study)
        except ValueError:
            return None
        per = sum(int(step.fixed.get("njobs", 0)) for step in s.steps
                  if step.kit == "prodtools")
        if executor == "local":
            return {"grid_jobs_per_point": 0, "grid_jobs_total": 0,
                    "local_jobs_per_point": per}
        return {"grid_jobs_per_point": per,
                "grid_jobs_total": per * max_evals}

    def _dry_run(self, argv: List[str]) -> Dict[str, Any]:
        proc = subprocess.Popen(
            ["bash", "-c", DRY_SCRIPT, "_", *argv], cwd=paths.REPO_ROOT,
            env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=self.check_timeout_s)
        except subprocess.TimeoutExpired:
            # The whole group: closed_loop and the kits it started.
            os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate()
            why = "timed out"
        else:
            why = None if proc.returncode in (0, 2) \
                else f"exit {proc.returncode}"
        tail = "\n".join(output.splitlines()[-OUTPUT_TAIL:])
        if why is not None:
            return {"ok": False, "problems": _refusals(output),
                    "output_tail": tail,
                    "error": f"closed_loop's check did not finish ({why})"}
        return {"ok": proc.returncode == 0, "problems": _refusals(output),
                "output_tail": tail, "error": None}

    def start_campaign(self, study: str, name_prefix: str, q: int,
                       max_evals: int, picker: str = "hybrid",
                       executor: str = "grid", parallel: Optional[int] = None,
                       context: Optional[Sequence[str]] = None,
                       stagger: Optional[float] = None,
                       confirm: bool = False) -> Dict[str, Any]:
        _check_prefix(name_prefix)
        argv = ["--study", study, "--q", str(q), "--max-evals",
                str(max_evals), "--picker", picker, "--name-prefix",
                name_prefix]
        for pair in context or []:
            argv += ["--context", pair]
        argv += ["--executor", executor]
        if parallel is not None:
            argv += ["--parallel", str(parallel)]
        if stagger is not None:
            argv += ["--stagger", repr(float(stagger))]
        command = ('PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop '
                   + shlex.join(argv))
        if not confirm:
            out = self._dry_run(argv)
            out.update(command=command,
                       budget=self.budget(study, max_evals, executor))
            return out
        return self._launch(name_prefix, study, argv, command)

    def _launch(self, prefix: str, study: str, argv: List[str],
                command: str) -> Dict[str, Any]:
        parents, _ = self._scan()
        if prefix in parents:
            raise ValueError(f"campaign {prefix!r} is already running (pid "
                             f"{parents[prefix][0]}); stop it or use a new "
                             f"prefix")
        cdir = self.camp_dir(prefix)
        if (cdir / "STOP").exists():
            raise ValueError(f"{cdir / 'STOP'} exists: the campaign would "
                             f"drain at once and launch nothing; use a new "
                             f"prefix")
        cdir.mkdir(parents=True, exist_ok=True)
        record_path = cdir / "campaign.json"
        try:
            fd = os.open(record_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                         0o644)
        except FileExistsError:
            raise ValueError(f"campaign {prefix!r} was already launched from "
                             f"MCP ({record_path}); use a new prefix") \
                from None
        record = {"prefix": prefix, "study": study, "args": argv,
                  "command": command, "pid": None, "started": time.time()}
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(record, indent=1) + "\n")
        record["pid"] = spawn_detached(cdir, LAUNCH_SCRIPT, argv, self.env)
        record_path.write_text(json.dumps(record, indent=1) + "\n")
        log, rc = cdir / "parent.log", cdir / "rc"
        deadline = time.time() + self.launch_wait_s
        while True:
            text = log.read_text(errors="replace") if log.exists() else ""
            if BANNER in text:
                return {"state": "launched", "prefix": prefix,
                        "pid": record["pid"], "log": str(log)}
            if rc.exists():
                problems = _refusals(text)
                return {"state": "refused", "prefix": prefix,
                        "problems": problems,
                        "exit_code": int(rc.read_text() or -1),
                        "error": (None if problems else
                                  "closed_loop exited before starting; see "
                                  "log_tail"),
                        "log_tail": "\n".join(
                            text.splitlines()[-OUTPUT_TAIL:]),
                        "note": SPENT}
            if time.time() > deadline:
                return {"state": "starting", "prefix": prefix,
                        "pid": record["pid"], "log": str(log),
                        "note": "poll campaign_status"}
            time.sleep(1)
