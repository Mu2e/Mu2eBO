"""The per-point graph for a study on the contract engine (generic-study
design, "One point, end to end"): derive -> render -> preflight ->
run_steps -> score, built from the Study. Kits come in through a KitSet
the caller owns and closes. No checkpointer: the state files are the
durability, so a killed child re-run on the same point adopts its steps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from contract import ContractError  # noqa: E402
from kits import KitError  # noqa: E402
from leaderboard import LeaderboardError  # noqa: E402
from scheduler import map_params, run_steps, write_atomic  # noqa: E402
from score import ScoreError, score  # noqa: E402


class PointMismatch(ValueError):
    """point.json records a different point under this config name."""


class PointState(TypedDict, total=False):
    config_name: str
    x_point: List[float]
    broken: bool
    reason: str
    objective: Optional[float]


def check_x(study, x) -> None:
    """One value per knob, each inside its knob's bounds."""
    if len(x) != len(study.knobs):
        raise ValueError(f"x has {len(x)} value(s); study {study.name!r} has "
                         f"{len(study.knobs)} knobs {list(study.knob_names)}")
    for knob, v in zip(study.knobs, x):
        if not knob.min <= v <= knob.max:
            raise ValueError(f"x: knob {knob.name!r} = {v!r} is outside its "
                             f"bounds [{knob.min}, {knob.max}]")


def build_study_graph(study, *, config: str, campaign: str, context: dict,
                      kits, state_dir: Path, board, log=print) -> StateGraph:
    def workflow(step: str) -> str:
        return f"{campaign}/{config}/{step}"

    shared: Dict[str, Any] = {}     # env, x, files, records: process-local

    def broken(reason: str) -> dict:
        path = state_dir / "broken.txt"
        if not path.exists():
            write_atomic(path, reason + "\n")
        log(f"[study_run] {config}: broken: {reason}")
        return {"broken": True, "reason": reason}

    def node_derive(state):
        x = [float(v) for v in state["x_point"]]
        check_x(study, x)
        env = (study.geom.derived_env(x) if study.geom is not None
               else dict(zip(study.knob_names, x)))
        state_dir.mkdir(parents=True, exist_ok=True)
        point = {"study": study.name, "config": config, "campaign": campaign,
                 "x": x, "context": context}
        point_path = state_dir / "point.json"
        if point_path.exists():
            old = json.loads(point_path.read_text())
            if old != point:
                raise PointMismatch(
                    f"{point_path} records a different point {old}; refusing "
                    f"to mix two points under one config name")
        else:
            write_atomic(point_path, json.dumps(point, indent=1, sort_keys=True))
        write_atomic(state_dir / "derived.json",
                     json.dumps(env, indent=1, sort_keys=True))
        shared["env"], shared["x"] = env, x
        return {"broken": False}

    def node_render(state):
        files = {}
        if study.geom is not None:
            path = state_dir / "geom.txt"
            write_atomic(path, study.geom.render(shared["x"]))
            files["geom"] = {"name": "geom", "uri": path.resolve().as_uri(),
                             "kind": "geom"}
        shared["files"] = files
        return {"broken": False}

    def node_preflight(state):
        pre = study.preflight
        if pre is None:
            return {"broken": False}
        try:
            kit = kits.get(pre["kit"])
            params = {**map_params(pre["params"], shared["env"],
                                   kit.accepts_lists),
                      **study.kits.get(pre["kit"], {})}
            ok, message = kit.check(f"{config}.preflight", params,
                                    [shared["files"][f] for f in pre["files"]],
                                    [], workflow("preflight"))
        except (KitError, ContractError, KeyError, ValueError) as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        write_atomic(state_dir / "preflight_verdict.json",
                     json.dumps({"ok": ok, "message": message}, indent=1))
        return {"broken": False} if ok else broken(f"preflight: {message}")

    def node_run_steps(state):
        outcomes = run_steps(study, config=config, state_dir=state_dir,
                             env=shared["env"], files=shared["files"],
                             kits=kits, workflow=workflow, log=log)
        failed = [o for o in outcomes.values() if not o.ok]
        if failed:
            return broken(f"step {failed[0].step}: {failed[0].message}")
        shared["records"] = {s: o.record for s, o in outcomes.items()}
        return {"broken": False}

    def node_score(state):
        try:
            result = score(study, config=config, x=shared["x"],
                           records=shared["records"], context=context,
                           board=board, state_dir=state_dir)
        except (ScoreError, LeaderboardError) as exc:
            return broken(f"score: {exc}")
        log(f"[study_run] {config}: primary={result['primary']} "
            f"row_appended={result['row_appended']}")
        return {"objective": result["primary"]}

    def route(state):
        return END if state.get("broken") else "next"

    g = StateGraph(PointState)
    for name, fn in (("derive", node_derive), ("render", node_render),
                     ("preflight", node_preflight),
                     ("run_steps", node_run_steps), ("score", node_score)):
        g.add_node(name, fn)
    g.add_edge(START, "derive")
    g.add_edge("derive", "render")
    g.add_edge("render", "preflight")
    g.add_conditional_edges("preflight", route, {"next": "run_steps", END: END})
    g.add_conditional_edges("run_steps", route, {"next": "score", END: END})
    g.add_edge("score", END)
    return g
