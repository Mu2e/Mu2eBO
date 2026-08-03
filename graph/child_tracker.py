"""ChildTracker: the one owner of child Resolution in the closed loop.

Design: wiki/concepts/mode-registry-childtracker-design.md + CONTEXT.md
("ChildTracker", "Resolution", "Signals adapter"). Before this module, the
barrier reconciled FIVE truth sources (leaderboard row, broken.txt, terminal
checkpoint, PID liveness, cluster.txt) with hand-rolled set logic and a
dead-PID grace set smeared across node_barrier locals — the soil under five
incidents (barrier-false-positive, thread-id-collision, barrier-timeout
zero-rows, orphan-children, stale-cluster-silent-no-launch).

The tracker holds that state behind one interface:

    tracker = ChildTracker(children, signals)   # children: name -> record
    resolutions = tracker.tick()                # one pass over raw signals
    tracker.all_resolved()                      # barrier exit condition

Signal reads go through the injected Signals adapter — production wraps the
disk/SQLite helpers; tests inject a fake (no mock.patch acrobatics).

Resolution semantics (sticky once != RUNNING; later signal flaps cannot
un-resolve a child):
  DONE_ROW             leaderboard row exists — the only fully-successful end
  DONE_BROKEN          state/broken.txt — scan_logs blocked the append
  DONE_TERMINAL_NO_ROW terminal checkpoint but no row/broken — preflight or
                       stage failure ended the child graph
  DEAD_UNRESOLVED      child process gone with no artifact, confirmed after
                       one full tick of grace (guards the race where the
                       process dies while its final leaderboard append is
                       landing — foilsf08 crash shape). ALSO raised
                       IMMEDIATELY (no grace) for a child whose Popen itself
                       raised in node_launch_children (`launch_failed` on
                       the record, pid stays None) — it never started, so
                       there is no in-flight append to race.
  STALE_CLUSTER        never launched by this parent (pid is None) AND a
                       prior run's *_cluster.txt exists — grid was submitted
                       by an aborted earlier parent and can never resolve
                       via row/broken/terminal/pid here

  RUNNING              none of the above; an alive child always progresses
                       (every stage inside it is bounded by pipeline.py caps)

Stale-cluster children are now a first-class STALE_CLUSTER Resolution raised
by the tracker itself; node_launch_children still skips the Popen
(double-submit guard) but no longer does its own completed/error
bookkeeping.
"""
from __future__ import annotations

import enum
from typing import Dict, Iterable, Optional, Protocol


class Resolution(str, enum.Enum):
    RUNNING = "running"
    DONE_ROW = "done_row"
    DONE_BROKEN = "done_broken"
    DONE_TERMINAL_NO_ROW = "done_terminal_no_row"
    DEAD_UNRESOLVED = "dead_unresolved"
    STALE_CLUSTER = "stale_cluster"

    @property
    def is_done(self) -> bool:
        return self is not Resolution.RUNNING


class Signals(Protocol):
    """Raw child signals. Production reads disk/SQLite; tests inject a fake."""

    def leaderboard_names(self) -> set:
        """Config names present in the mode's leaderboard (ONE flock-aware
        read per tick — never per child; the TSV grows to hundreds of rows)."""
        ...

    def is_broken(self, name: str) -> bool: ...

    def is_terminal(self, thread_id: str) -> bool: ...

    def pid_alive(self, pid: int) -> bool: ...

    def has_cluster(self, name: str) -> bool:
        """A prior run's *_cluster.txt exists in the child's state dir."""
        ...


class ChildTracker:
    """Per-round, stateful resolver of child Resolutions.

    `children` maps name -> record dict (needs `pid` and optionally
    `thread_id`; missing/None pid means "never launched here" and the child
    can only resolve via row/broken/terminal/stale signals).
    `already_done` names (e.g. resumed from a prior parent) are excluded
    from tracking and counted resolved by `all_resolved()`.
    """

    def __init__(self, children: Dict[str, dict], signals: Signals,
                 already_done: Optional[Iterable[str]] = None):
        self._signals = signals
        self._pre = set(already_done or ()) & set(children)
        self._children = {n: (rec or {}) for n, rec in children.items()
                          if n not in self._pre}
        self._resolutions: Dict[str, Resolution] = {
            n: Resolution.RUNNING for n in self._children}
        self._dead_suspect: set = set()

    # -- queries ------------------------------------------------------------

    def resolutions(self) -> Dict[str, Resolution]:
        return dict(self._resolutions)

    def done_names(self) -> set:
        return self._pre | {n for n, r in self._resolutions.items() if r.is_done}

    def all_resolved(self) -> bool:
        return all(r.is_done for r in self._resolutions.values())

    def pending_count(self) -> int:
        return sum(1 for r in self._resolutions.values() if not r.is_done)

    # -- transitions ---------------------------------------------------------

    def tick(self) -> Dict[str, Resolution]:
        """One reconciliation pass. Returns ONLY the resolutions that changed
        this tick (callers log/react to transitions, not steady state)."""
        changed: Dict[str, Resolution] = {}
        pending = [n for n, r in self._resolutions.items() if not r.is_done]
        if not pending:
            return changed
        lb = self._signals.leaderboard_names()
        for name in pending:
            rec = self._children[name]
            new: Optional[Resolution] = None
            if name in lb:
                new = Resolution.DONE_ROW
            elif self._signals.is_broken(name):
                new = Resolution.DONE_BROKEN
            elif self._signals.is_terminal(rec.get("thread_id") or name):
                new = Resolution.DONE_TERMINAL_NO_ROW
            else:
                pid = rec.get("pid")
                if pid is None:
                    if rec.get("launch_failed"):
                        # Popen raised in node_launch_children — the child
                        # never started and can never produce an artifact.
                        # Immediate (no grace): there is no in-flight append
                        # to race. The launch exception is already in the
                        # round's errors list.
                        new = Resolution.DEAD_UNRESOLVED
                    elif self._signals.has_cluster(name):
                        # Never launched by this parent. If a prior aborted
                        # run left *_cluster.txt, the grid was submitted but
                        # never harvested — this child can never resolve via
                        # row/broken/terminal here. Resolve loudly.
                        new = Resolution.STALE_CLUSTER
                elif not self._signals.pid_alive(pid):
                    if name in self._dead_suspect:
                        new = Resolution.DEAD_UNRESOLVED
                    else:
                        # Grace: confirm on the NEXT tick, in case the final
                        # leaderboard append was racing the process death.
                        self._dead_suspect.add(name)
                else:
                    self._dead_suspect.discard(name)
            if new is not None:
                self._resolutions[name] = new
                self._dead_suspect.discard(name)
                changed[name] = new
        return changed
