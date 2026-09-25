"""score: a finished point's step records -> objectives, extra metrics, the
summary files and one leaderboard row (generic-study design, "One point,
end to end", step 5).

A missing metric, a value that is not a finite number, or a value <= 0
under log10 is a failed evaluation naming the metric: never a row, never a
0 (ADR-0002).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict

if __package__:
    from core.leaderboard import Point
    from core.scheduler import write_atomic
else:
    from leaderboard import Point
    from scheduler import write_atomic


class ScoreError(ValueError):
    """The point's results cannot make a row."""


def _value(metric: str, records, what: str) -> float:
    step, key = metric.split(".", 1)
    record = records.get(step)
    if record is None:
        raise ScoreError(f"{what}: step {step!r} has no results")
    if key not in record["metrics"]:
        raise ScoreError(f"{what}: metric {metric!r} is missing from step "
                         f"{step!r}'s results (it returned "
                         f"{sorted(record['metrics'])})")
    v = record["metrics"][key]
    if (isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v)):
        raise ScoreError(f"{what}: metric {metric!r} is not a finite number: "
                         f"{v!r}")
    return float(v)


def collect(study, records) -> Dict[str, float]:
    """{name: value} for every objective and extra metric."""
    y: Dict[str, float] = {}
    for o in study.objectives:
        v = _value(o.metric, records, f"objective {o.name!r}")
        if o.transform == "log10" and v <= 0:
            raise ScoreError(f"objective {o.name!r}: metric {o.metric!r} is "
                             f"{v!r}, and its log10 transform needs a value > 0")
        y[o.name] = v
    for m in study.extra_metrics:
        y[m.name] = _value(m.metric, records, f"extra metric {m.name!r}")
    return y


def kit_versions(records) -> Dict[str, str]:
    """One version per kit. Steps of one kit that ran on different versions
    (a step adopted from before a kit upgrade) measured different things."""
    seen: Dict[str, set] = {}
    for r in records.values():
        seen.setdefault(r["kit"], set()).add(r["kit_version"])
    mixed = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    if mixed:
        raise ScoreError(f"a kit changed version within this point {mixed}; "
                         f"its steps were measured with different builds")
    return {k: next(iter(v)) for k, v in seen.items()}


def row_meta(study, records, now=None) -> Dict[str, str]:
    return {"handles": ",".join(f"{s}={r['handle']}"
                                for s, r in sorted(records.items())),
            "spec_sha": study.spec_sha,
            "measure_sha": study.measure_sha(kit_versions(records)),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}


def score(study, *, config: str, x, records, context, board,
          state_dir: Path, now=None) -> Dict[str, Any]:
    """Write summary.json, append the row, write evaluate_result.json and
    return its payload. A ScoreError writes broken.txt first; a leaderboard
    refusal propagates for the caller to record."""
    try:
        y = collect(study, records)
        meta = row_meta(study, records, now) if study.layout == "v2" else None
    except ScoreError as exc:
        write_atomic(state_dir / "broken.txt", f"score: {exc}\n")
        raise
    write_atomic(state_dir / "summary.json", json.dumps(
        {"config": config, "x": list(x),
         "steps": {s: r["metrics"] for s, r in sorted(records.items())}},
        indent=1, sort_keys=True))
    appended = board.append(Point(cfg=config, x=list(x), y=y), context, meta)
    result = {"config": config, "primary": y[study.objectives[0].name],
              "objectives": {o.name: y[o.name] for o in study.objectives},
              "row_appended": appended}
    write_atomic(state_dir / "evaluate_result.json",
                 json.dumps(result, indent=1))
    return result
