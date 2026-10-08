"""The autoresearch MCP server's campaign tools, as plain Python: start a
`graph.closed_loop` campaign (a dry run through --check-only, then a
confirmed detached launch), stop it, follow it, and read a study's
leaderboard. No MCP here; service/server.py wraps each method as a tool.

A campaign is named by its --name-prefix; its children are
<prefix>R<n>_00 (core/campaign_dir.py: is_child, so `foo` never takes
`foo2`). Status reads the records every campaign leaves behind, from a
shell or from here (spec
docs/superpowers/specs/2026-10-05-point-campaign-records-design.md):
  <graph data>/<prefix>/        the campaign record (core/campaign_dir.py):
                                campaign.json, outcomes.jsonl, parent.lock,
                                STOP; for a launch from here also
                                launch.json, lock, parent.log and rc
  <graph data>/closed_loop_logs/<child>.log   one log per child
  <grid data>/<child>/state/    the point record (core/point_dir.py),
                                run.lock held while the point runs
  the study's board             the rows
Liveness is the records' flocks, so a campaign on any node that shares the
data root shows as running.

Only the standard library and bare core/ modules (paths, study, leaderboard):
never modes, so one broken study file cannot stop the server.
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import paths  # noqa: E402
import study as st  # noqa: E402
from campaign_dir import CampaignDir, is_child  # noqa: E402,F401  (re-exported)
from leaderboard import Leaderboard, LeaderboardError  # noqa: E402
from point_dir import PointDir  # noqa: E402

from service.checks import CheckService  # noqa: E402
from service.jobs import last_lines, spawn_detached  # noqa: E402

PREFIX_RE = re.compile(r"[A-Za-z0-9_]+")
LOG_TAIL = 20
OUTPUT_TAIL = 40
DRY_SCRIPT = ('source ./activate.sh >/dev/null && PYTHONPATH= '
              '"$AUTORESEARCH_PYTHON" -m graph.closed_loop "$@" --check-only')
LAUNCH_SCRIPT = ('source ./activate.sh >/dev/null 2>"$1/parent.log" && '
                 'PYTHONPATH= "$AUTORESEARCH_PYTHON" -u -m graph.closed_loop '
                 '"${@:2}" >>"$1/parent.log" 2>&1; '
                 'echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"')
REFUSED = "[closed_loop] REFUSED: "
SPENT = "this prefix is spent: dry-run again and launch under a new prefix"


def _check_prefix(prefix: str) -> None:
    if not (isinstance(prefix, str) and PREFIX_RE.fullmatch(prefix)):
        raise ValueError(f"name_prefix must match [A-Za-z0-9_]+ (it names "
                         f"the campaign's folder and its children); got "
                         f"{prefix!r}")


def _read(path: Path) -> str:
    """The file's text; "" when it cannot be read."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _last_line(path: Path) -> str:
    lines = _read(path).splitlines()
    return next((ln for ln in reversed(lines) if ln.strip()), "")


def child_state(scored: bool, pd: PointDir, outcome: Optional[dict],
                alive: bool) -> str:
    """One child's state, the one rule: scored (its row is on the board),
    broken (broken.txt), running (its graph.run holds run.lock), starting
    (the campaign is alive and the child has no outcome, has never taken
    its lock and has written nothing: graph.run is still in its launch
    checks, which come before run.lock and point.json), else ended without
    a row. A child from before the records (point.json, no run.lock) is
    never starting."""
    if scored:
        return "scored"
    if pd.broken() is not None:
        return "broken"
    if pd.running():
        return "running"
    if (alive and outcome is None and not pd.ever_ran()
            and not pd.started()):
        return "starting"
    return "ended without a row"


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

    def camp(self, prefix: str) -> CampaignDir:
        return CampaignDir(self.graph_data, prefix)

    def point(self, name: str) -> PointDir:
        return PointDir.of(self.grid_data, name)

    # -- the board ---------------------------------------------------------

    def load_study(self, name: str):
        return st.load_study_file(self.checks.study_path(name))

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
        s = self.load_study(study)
        board = self._board(s)
        points = board.load()
        obj = s.objectives[0]
        return {"study": s.name, "board": str(board.path),
                "n_rows": len(points),
                "objective": {"name": obj.name, "direction": obj.direction},
                "rows": self._rows(s, points, name_prefix)[:max(top, 0)]}

    # -- status ------------------------------------------------------------

    def _children(self, prefix: str) -> List[str]:
        if not self.logs_dir.is_dir():
            return []
        return sorted(p.stem for p in self.logs_dir.glob("*.log")
                      if is_child(prefix, p.stem))

    def _parent(self, camp: CampaignDir,
                record: Optional[dict]) -> Dict[str, Any]:
        launch = camp.launch() or {}
        log = camp.path / "parent.log"
        return {"alive": camp.alive(),
                "pid": (record or {}).get("pid") or launch.get("pid"),
                "launched_by": camp.launched_by(),
                "exit_code": camp.exit_code(),
                "log_tail": last_lines(_read(log), LOG_TAIL)}

    def campaign_status(self, name_prefix: Optional[str] = None):
        if name_prefix is not None:
            _check_prefix(name_prefix)
        if name_prefix is None:
            return self._campaigns()
        prefix = name_prefix
        camp = self.camp(prefix)
        errors = []
        try:
            record = camp.record()
        except (OSError, ValueError) as exc:
            record = None
            errors.append(f"{camp.path / 'campaign.json'}: {exc}")
        try:
            outcomes = camp.outcomes(errors)
        except OSError as exc:
            outcomes = {}
            errors.append(str(exc))
        names = self._children(prefix)
        study_name = (record or {}).get("study")
        study, scored, rows, best, board_error = None, {}, 0, None, None
        if study_name is not None:
            try:
                study = self.load_study(study_name)
                mine = [p for p in self._board(study).load()
                        if is_child(prefix, p.cfg)]
            except (ValueError, LeaderboardError) as exc:
                board_error = str(exc)
            else:
                scored = {p.cfg: p for p in mine}
                rows = len(mine)
                ranked = self._rows(study, mine, None)
                best = ranked[0] if ranked else None
        alive = camp.alive()
        children = []
        for name in names:
            pd = self.point(name)
            row = scored.get(name)
            outcome = outcomes.get(name)
            x = None
            if study is not None:
                try:
                    point = pd.point()
                except (OSError, ValueError) as exc:
                    point = None
                    message = f"{name}: {exc}"
                    if message not in errors:
                        errors.append(message)
                values = (point or {}).get("x") or (row.x if row else None)
                if values is not None:
                    x = dict(zip(study.knob_names, values))
            children.append({
                "name": name,
                "state": child_state(row is not None, pd, outcome, alive),
                "last_line": _last_line(self.logs_dir / f"{name}.log"),
                "outcome": outcome.get("reason") if outcome else None,
                "x": x, "values": dict(row.y) if row else None})
        return {"prefix": prefix, "study": study_name,
                "host": socket.gethostname(),
                "parent": self._parent(camp, record),
                "stopping": camp.stopping(),
                "children": children, "rows": rows, "best": best,
                "board_error": board_error,
                "error": "; ".join(errors) or None}

    def _campaigns(self) -> List[Dict[str, Any]]:
        """Every campaign with a record."""
        out = []
        if self.graph_data.is_dir():
            for path in sorted(self.graph_data.glob("*/campaign.json")):
                camp = self.camp(path.parent.name)
                try:
                    record, error = camp.record() or {}, None
                except (OSError, ValueError) as exc:
                    record, error = {}, f"{path}: {exc}"
                out.append({"prefix": camp.prefix,
                            "study": record.get("study"),
                            "alive": camp.alive(),
                            "launched_by": camp.launched_by(),
                            "error": error})
        return out

    # -- stop --------------------------------------------------------------

    def stop_campaign(self, name_prefix: str) -> Dict[str, Any]:
        _check_prefix(name_prefix)
        camp = self.camp(name_prefix)
        names = self._children(name_prefix)
        warning = None
        if camp.launched_by() is None and not names:
            warning = f"no sign of a campaign named {name_prefix!r}"
        stop = camp.stop()
        return {"stop_file": str(stop),
                "parent_alive": camp.alive(),
                "children_running": sum(1 for n in names
                                        if self.point(n).running()),
                "warning": warning}

    # -- start -------------------------------------------------------------

    def budget(self, study: str, max_evals: int,
               executor: str) -> Optional[Dict[str, int]]:
        """Jobs a campaign would run: prodtools steps' njobs per point."""
        try:
            s = self.load_study(study)
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
        tail = last_lines(output, OUTPUT_TAIL)
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
            # What confirm would refuse, the dry run says too: the check and
            # the launch never disagree.
            refusals = self._launch_refusals(name_prefix)
            if refusals:
                out.update(ok=False, problems=refusals + out["problems"])
            out.update(command=command,
                       budget=self.budget(study, max_evals, executor))
            return out
        return self._launch(name_prefix, study, argv, command)

    def _launch_refusals(self, prefix: str) -> List[str]:
        """Why the server would refuse to launch `prefix` (read only)."""
        out = []
        camp = self.camp(prefix)
        if camp.alive():
            out.append(f"campaign {prefix!r} is already running; stop it or "
                       f"use a new prefix")
        if camp.stopping():
            out.append(f"{camp.path / 'STOP'} exists: the campaign would "
                       f"drain at once and launch nothing; use a new prefix")
        if camp.launched_by() is not None:
            which = "launch.json" if camp.launch() is not None \
                else "campaign.json"
            out.append(f"campaign {prefix!r} was already launched "
                       f"({camp.path / which}); use a new prefix")
        if self._children(prefix):
            # Also a campaign on another node: a second parent on one
            # prefix would double its submits.
            out.append(f"prefix {prefix!r} already has children "
                       f"({self.logs_dir}/{prefix}R*_00.log): another "
                       f"campaign used it; use a new prefix")
        return out

    def _launch(self, prefix: str, study: str, argv: List[str],
                command: str) -> Dict[str, Any]:
        refusals = self._launch_refusals(prefix)
        if refusals:
            raise ValueError("; ".join(refusals))
        camp = self.camp(prefix)
        try:
            camp.write_launch({"prefix": prefix, "study": study,
                               "args": argv, "command": command, "pid": None,
                               "started": time.time()})
        except FileExistsError:
            raise ValueError(f"campaign {prefix!r} was already launched "
                             f"({camp.path / 'launch.json'}); use a new "
                             f"prefix") from None
        pid = spawn_detached(camp.path, LAUNCH_SCRIPT, argv, self.env)
        camp.update_launch(pid=pid)
        log, rc = camp.path / "parent.log", camp.path / "rc"
        deadline = time.time() + self.launch_wait_s
        while True:
            # closed_loop writes the campaign record once its launch checks
            # pass: that is "launched".
            try:
                launched = camp.record() is not None
            except (OSError, ValueError):
                launched = True     # written, if unreadable: it started
            if launched:
                return {"state": "launched", "prefix": prefix, "pid": pid,
                        "log": str(log)}
            if rc.exists():
                text = log.read_text(errors="replace") if log.exists() else ""
                problems = _refusals(text)
                return {"state": "refused", "prefix": prefix,
                        "problems": problems,
                        "exit_code": int(rc.read_text() or -1),
                        "error": (None if problems else
                                  "closed_loop exited before starting; see "
                                  "log_tail"),
                        "log_tail": last_lines(text, OUTPUT_TAIL),
                        "note": SPENT}
            if time.time() > deadline:
                return {"state": "starting", "prefix": prefix, "pid": pid,
                        "log": str(log), "note": "poll campaign_status"}
            time.sleep(1)
