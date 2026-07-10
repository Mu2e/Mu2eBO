# closed-loop parent + children signal-killed mid-launch (no traceback)

**Type:** incident
**Status:** open — observed 2026-06-13 on foilsf12 R2, 3 foilsf13
relaunch attempts (same night), AND 2026-06-17 on foilsf15 R0;
memory-pressure-linked, infra-unstable
**Updated:** 2026-06-17

## Summary

foilsf12's closed-loop parent (qlnei, q=10, max-rounds=3) died **abruptly
during R2 `node_launch_children`** — after launching R02_00..R02_08 it
never launched R02_09, never reached the barrier, and left **no traceback**
in the parent log (the log just stops after the R02_08 launch line). The
parent AND all 9 just-launched R2 children died near-simultaneously
(~19:02). R02_01..R02_08 died before submitting any grid stage (no
`*_cluster.txt`); only R02_00 got one mubeam cluster out (which then had 0
queued jobs — its dead child never harvested).

No-traceback death = killed by a **signal**, not a Python exception
(contrast the same evening's qNEHVI `TimeoutExpired`, which printed a full
stack — see [[qlnei-sob-only-picker]]). R0+R1 had already completed
cleanly (20 rows, best sob 3.85); the science verdict was banked, so
nothing scientific was lost.

## Key facts

- **Signature:** parent log ends mid-round at a `launched <prefix>R<NN>_<j>`
  line with no `barrier`, no `decide_next`, no traceback. `ps` shows the
  parent pid gone; the round's already-launched children are ALSO gone.
- **`setsid` does NOT escape the systemd user-session cgroup.**
  `node_launch_children` Popens each child with `start_new_session=True`
  (setsid) — that gives a new session/process-group for *signal* delivery
  (so killing the parent doesn't SIGHUP them), but it does NOT move them
  out of the launching shell's `user-<uid>.slice/session-<N>.scope` cgroup.
  So a **session-scoped cgroup OOM** (systemd-oomd / cgroup OOM killer) or
  a session teardown kills the parent AND every child in that scope at
  once, regardless of setsid. The stale dmesg OOM line on this host even
  shows the `task_memcg=…/session-<N>.scope` pattern. **Leading hypothesis
  (unconfirmed):** 9 simultaneous `graph.run` langgraph imports + the
  parent tripped a per-session memory cgroup limit. Could not confirm —
  `journalctl --user` not readable, and the only dmesg OOM is stale
  (Jun 12, unrelated 9 GB pid).
- **Distinct from neighbors:** NOT [[closed-loop-final-round-orphan-children]]
  (that's a CLEAN exit at max_rounds leaving still-running children — here
  the children DIED too). NOT [[kerberos-mid-run-expiry]] (that throws
  Errno 127 with a traceback). NOT the liveness-barrier false-positive
  ([[closed-loop-barrier-timeout-zero-rows-falsepos]], now fixed) — the
  parent never reached the barrier.
- **No grid orphans:** the one submitted cluster (R02_00 mubeam) drained
  to 0; other queued jobs at the time were unrelated (pt6d-family).
- **Recovery:** R0+R1 rows are durable in the leaderboard. If the final
  round is wanted, relaunch under a FRESH `--name-prefix` (foilsf13);
  reuse trips [[closed-loop-stale-cluster-silent-no-launch]].

## foilsf15 R0 recurrence (2026-06-17) — all 10 children died at `preflight: pass`

Third occurrence, qNEHVI q=10 max-rounds=2. New corroborating detail:
**every one of the 10 R0 children stopped at exactly `preflight: pass` and
went no further** — no grid submit, no `*_cluster.txt`, no traceback in any
child log; parent log ends after the `launched …R00_09` line + one barrier
poll, then gone. Parent + all children absent from `ps`. Zero foilsf15
leaderboard rows; champion unchanged at foilsf14R00_06 sob=3.83. The
uniform death-point at `preflight: pass` (the memory-heavy concurrent
G4-init step, ×10) strengthens the session-cgroup memory-pressure
hypothesis: the children peak RAM together right at preflight, not at
submit. Could not confirm OOM (`dmesg` unreadable without sudo on this
host). Same recovery rule: relaunch under a FRESH prefix (foilsf16), and
prefer lower `--q` / larger `--stagger` so the 10 preflights don't peak
simultaneously.

## Diagnostic distinguisher: dead-at-preflight vs slow-submit (2026-06-17, from foilsf16 recovery)

A child stuck at `preflight: pass` in its log is **ambiguous** — both a
signal-killed child (this incident) and a perfectly healthy child mid-submit
look IDENTICAL in the child log, because the run.py log emits nothing between
`preflight: pass` and the eventual cluster line. The silent gap is the
**`tar cf - Code/ | bzip2 > Code.tar.bz2`** step in `pipeline.py submit
mubeam` — Code-tarball compression runs **several minutes per child** with no
log output, followed by `mu2ejobdef` (jobdef materialize) + RCDS publish.

**The silence is not just the submit gap — it spans the ENTIRE grid phase.**
The graph.run child log emits a JSON snapshot at `preflight: pass` and then
the *next* line only at `objective` (post-harvest), hours later. Across all
four stages (mubeam→run1b_mubeam→concat→mustops_ce) + every grid poll, the
child log shows nothing. So a child sitting at `preflight: pass` for hours is
the **normal** running state, not a stall. Read real per-stage progress from
the grid queue + the live pipeline procs (`poll <stage>` / `submit <stage>`),
never from the child log.

To tell them apart, do NOT trust the child log — check for the live submit
or poll subprocess on the node:
`ps -u oksuzian -o pid,etime,cmd | grep -E "pipeline.py .* submit|bzip2|mu2ejobdef"`.
- **Alive** (a `pipeline.py --config <child> submit mubeam` pid, or its
  `tar/bzip2`/`mu2ejobdef` grandchildren) ⇒ healthy, just slow; wait.
- **Absent** for a child whose log stopped at `preflight: pass` ⇒ this
  incident (signal-killed).
foilsf16 (stagger=150) confirmed healthy this way: R00_00 sat at
`preflight: pass` ~5 min but `pipeline.py submit mubeam` was actively
bzip2-ing — the stagger spaced the launches enough to clear the
concurrent-preflight memory spike that killed foilsf15.

**Parent-liveness gotcha: `$!` ≠ the closed_loop pid.** When launched as
`setsid env nohup .venv-graph/bin/python -m graph.closed_loop … &`, the `$!`
the shell reports is the **`setsid`/`env` wrapper**, which exec-chains/exits
immediately; the real `graph.closed_loop` python is a *different* pid
(observed foilsf16: reported `$!`=270873, actual parent=270874). So
`kill -0 <reported-$!>` (or `ps -p`) will say DEAD even when the campaign is
perfectly alive — a false-positive that compounds the cross-node visibility
caveat above. **Reliable parent-liveness check:**
`ps -u oksuzian -o pid,etime,cmd | grep "graph.closed_loop"` (grep the
cmdline, never trust the captured launch pid).

## foilsf13 relaunch attempts (same night) — couldn't clear startup

Tried to relaunch the lost final round as foilsf13 (q=10, max-rounds=2,
`--stagger 150`). **3 consecutive failures, all with an EMPTY parent log
(died before the `thread_id=` banner, i.e. during module import — the
venvs are on cold Ceph, [[venv-relocated-to-data-volume]], so import is
slow):**
- 2× plain `nohup … &`: parent died ~2 min in, 8.8 GB free (NOT memory on
  this node — it's an 11 GB GPVM, distinct from the 170 GiB session where
  foilsf12 died).
- 1× full `setsid env … </dev/null >log 2>&1 & disown`: survived ~10 min
  (vs 2 min) but still produced zero output and then vanished. setsid
  (new session/pgid) delayed but did not prevent it.
- **Node-visibility caveat:** mu2egpvm is multi-node; a backgrounded
  process and a later `ps` check via separate Bash calls can land on
  DIFFERENT hosts, so "process not found" is ambiguous. The reliable
  signal is the SHARED filesystem: foilsf13 wrote no proposal, no child
  log, no leaderboard row, and a 0-byte parent log — so it genuinely
  never progressed past import on any node.
- **Decision:** stopped relaunching. The science was already banked
  (foilsf11 + foilsf12 R0/R1 → verdict confirmed, best 3.85); fighting an
  unstable launcher for an incremental R2 is not worth it. No grid
  clusters were ever submitted; nothing to clean up.
- **For the next attempt** (when the node is quiet): launch under `tmux`
  / `screen` on a PINNED host, or `systemd-run --user --scope -p
  MemoryMax=…`, NOT a Bash-tool `nohup`/`setsid`. Pre-warm the venv import
  (`.venv-graph/bin/python -c "import graph.closed_loop"`) so the cold-Ceph
  import isn't inside the fragile launch window.

## Cross-links
- **Same kill window, sister campaign:**
  [[pipeline-poll-rc120-atexit-death]] (pt6d05 R1: 7 poll subprocesses
  in the OTHER live closed-loop on this node died synchronously in
  19:01:40-19:03:34, same session-23.scope; memory.peak 170.69 GiB
  ≈91% RAM). Strong evidence this incident's "session-cgroup OOM"
  hypothesis is right, although cgroup `memory.events` didn't record
  an oom_kill so the mechanism is closer to memory-pressure-induced
  fd corruption than a clean OOM signal.
- Related: [[closed-loop-final-round-orphan-children]],
  [[kerberos-mid-run-expiry]],
  [[closed-loop-barrier-timeout-zero-rows-falsepos]],
  [[closed-loop-runner]], [[bo-foils]]
- Source: `graph/closed_loop.py` `node_launch_children`
  (`start_new_session=True` Popen)

## Open questions / TODO
- Confirm cause on recurrence: check `journalctl --user -u` /
  `systemd-cgls` for the session.scope around the death time; if it's a
  session-cgroup OOM, mitigations are (a) larger `--stagger` so child
  imports don't peak together, (b) lower `--q`, or (c) launch the parent
  under its own `systemd-run --scope` with a generous MemoryMax so a
  child storm can't take the campaign down.
- If it recurs without an OOM signature, suspect node drain / session
  teardown and run the parent under `tmux`/`screen` rather than a
  Bash-tool `nohup`.
