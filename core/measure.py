"""Measure identity: which kit versions a point is measured at, and whether
a board's rows match it (wiki/drivers/contract-engine.md).

A row's measure_sha is the study's measure basis plus each step kit's
version (core/study.py:Study.measure_sha). A kit's version changes only
when its author bumps it by hand (2026-10-05): a build -- the anakit checkout
commit, the beamkit server -- is recorded with each step, never in the
version. A step's version is recorded when it is submitted
(state/<step>_submit.json) and must still be its kit's when its results
are read. score, the launch check (contract.launch_problems) and the
scheduler all decide through this module.

Stdlib only, plus core/leaderboard.py: never modes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from leaderboard import SchemaMismatch


class MixedVersions(ValueError):
    """Steps of one kit within a point were recorded at different versions."""


def recorded_versions(records: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """One version per kit from a point's step records. Steps of one kit
    that ran on different versions (a step adopted from before a version
    bump) measured different things."""
    seen: Dict[str, set] = {}
    for r in records.values():
        seen.setdefault(r["kit"], set()).add(r["kit_version"])
    mixed = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    if mixed:
        raise MixedVersions(f"a kit changed version within this point "
                            f"{mixed}; its steps were measured with "
                            f"different builds")
    return {k: next(iter(v)) for k, v in seen.items()}


def in_flight_problem(kit: str, steps: List[str], was: str, now: str) -> str:
    """Why steps of `kit` submitted under version `was` cannot complete
    while it reports `now`: their jobs ran under `was`, their results would
    be read under `now`. Refused, never recorded under either: a bump of
    the results side only (beamkit's FOM_VERSION) makes `was` wrong too.
    The launch check (point_versions) and the scheduler (when a step
    resumes, and when its results are read) both refuse in these words."""
    return (f"kit {kit!r}: step(s) {steps} were submitted under version "
            f"{was!r} but the kit is now {now!r}, so this point cannot "
            f"complete as measured (its jobs ran under one version and "
            f"their results would be read under another); rerun this x "
            f"under a new config name")


def point_versions(study, current: Dict[str, str],
                   adopted: Optional[Dict[str, Dict[str, Any]]] = None,
                   submitted: Optional[Dict[str, str]] = None
                   ) -> Tuple[Dict[str, str], List[str]]:
    """The kit versions `score` will use for this point, and the problems
    that make it unable to complete as measured. `current` is each kit's
    running version; `adopted` is {step: record} for steps already finished
    (resume), each record carrying "kit" and "kit_version". A kit whose
    steps were all adopted keeps the recorded version (recorded_versions
    decides disagreement); one adopted in part at a version other than
    the current one would be measured on two versions, which score refuses
    after running the rest; any other kit measures at its current version.
    `submitted` is {step: version} for steps submitted under a recorded
    version and not finished (PointDir.submitted): one at a version other
    than its kit's current one cannot complete (in_flight_problem). A step
    in flight with no record (a handle from before the record) is not in
    it: its version is read at results, as it always was."""
    versions = dict(current)
    mine = {s.step: adopted[s.step] for s in study.steps
            if adopted and s.step in adopted}
    flying: Dict[Tuple[str, str], List[str]] = {}
    for s in study.steps:
        was = (submitted or {}).get(s.step)
        if was is not None and s.step not in mine and was != current[s.kit]:
            flying.setdefault((s.kit, was), []).append(s.step)
    moved = [in_flight_problem(kit, steps, was, current[kit])
             for (kit, was), steps in sorted(flying.items())]
    if not mine:
        return versions, moved
    try:
        recorded = recorded_versions(mine)
    except MixedVersions as exc:
        return versions, [f"adopted steps of {sorted(mine)}: {exc}"] + moved
    problems = []
    for kit, version in sorted(recorded.items()):
        steps = [s.step for s in study.steps if s.kit == kit]
        if all(step in mine for step in steps):
            versions[kit] = version
        elif version != current[kit]:
            todo = [step for step in steps if step not in mine]
            done = [step for step in steps if step in mine]
            problems.append(
                f"kit {kit!r}: step(s) {done} finished under version "
                f"{version!r} but the kit is now {current[kit]!r} with "
                f"{todo} still to run, so this point cannot complete as "
                f"measured (score refuses a kit measured on two versions); "
                f"use a new config name")
    return versions, problems + moved


def board_problems(study, board, versions: Dict[str, str],
                   current: Optional[Dict[str, str]] = None) -> List[str]:
    """The board must not hold rows measured differently from this launch:
    a row carrying another measure_sha is refused at `score`, after every
    step has run. One problem when it does, or when the board's header is
    not the study's; none for an empty or missing board. With `current`
    (the kits' running versions), a point whose finished steps keep an older
    version (point_versions) is told so."""
    try:
        found = board.measure_shas()
    except SchemaMismatch as exc:
        return [str(exc)]
    this = study.measure_sha(versions)
    if not found or found == {this}:
        return []
    kept = {k: (v, current[k]) for k, v in sorted(versions.items())
            if current is not None and k in current and current[k] != v}
    if kept:
        changes = "; ".join(f"kit {k!r} {old!r}, now {new!r}"
                            for k, (old, new) in kept.items())
        return [f"this point's finished steps were recorded under an older "
                f"kit version ({changes}), so it measures as {this[:12]} "
                f"while {board.path} holds "
                f"{sorted(sha[:12] for sha in found)}: rerun this x under "
                f"a new config name"]
    return [f"{board.path} holds rows measured as "
            f"{sorted(sha[:12] for sha in found)}, but this launch measures "
            f"as {this[:12]} (the study's measurement or a kit's version "
            f"changed); set a new leaderboard.file to start a new board"]
