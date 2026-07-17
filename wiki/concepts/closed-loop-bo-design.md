---
type: concept
title: Closed-loop BO design constraints
description: load-bearing constraints for `graph/closed_loop.py` (SqliteSaver WAL,
  leaderboard/pending locking, barrier source-of-truth, config-SHA stamping, scan_logs
  gating)
status: active
timestamp: '2026-06-28'
---

# Closed-loop BO design constraints

> **2026-06-12 — process liveness is a sufficient barrier wait condition.**
> Once the barrier checks child pid liveness (landed with the
> [closed-loop-barrier-timeout-zero-rows-falsepos](/incidents/closed-loop-barrier-timeout-zero-rows-falsepos.md) fix), a per-round
> wall-clock timeout is no longer load-bearing: an alive `graph.run` child
> is always progressing toward resolution because every grid stage inside it
> is bounded by pipeline.py's `cap_hours` (24h) poll cap — it either
> succeeds, fails a stage (terminal checkpoint), or crashes (dead pid).
> Wall-clock windows were only ever a proxy for "will this child resolve?",
> and the proxy caused two orphan-storm incidents (foilsg03/05). A single
> loud backstop cap for alive-but-hung children is sufficient; round pacing
> by timeout is an anti-pattern here. (Implemented 2026-06-12: barrier
> waits on liveness; `--barrier-timeout-min` deprecated/ignored;
> `--barrier-max-min` 1440 is the lone backstop.)

## Summary
Load-bearing architectural constraints for `graph/closed_loop.py` (multi-round
batch BO runner that fans out q grid chains as subprocess children, waits at a
barrier, refits the GP, loops). These were surfaced by a 3-agent review of the
initial plan on 2026-05-21. Future sessions revising the closed-loop driver
must respect them; ignoring any one of them re-introduces a class of bug we
already paid to learn.

## Key facts

- **One SqliteSaver DB, q+1 writers.** `graph_data/checkpoints.sqlite` is
  opened by every `graph.run` invocation (each q child) AND by the outer
  closed-loop graph. SQLite's default journal mode locks the whole DB for
  writes, so concurrent checkpoint writes serialize and can time out. Fix:
  enable **WAL mode** on the connection (`PRAGMA journal_mode=WAL;`) once at
  startup. This is a per-DB persistent setting; safe to set in both
  `graph/run.py` and `graph/closed_loop.py`. Alternative (per-thread DBs)
  forfeits cross-thread checkpoint visibility we want for the barrier.

- **Leaderboard append (`autoresearch_bo_michael.py:150-156`) has no file
  lock.** Today it is safe only because `pipeline.py` submits are
  serialized by a coarse single-process pattern. Under closed-loop the q
  children all call `append_history` concurrently at harvest time. Fix:
  wrap the write in `fcntl.flock(LOCK_EX)` on a sibling `.lock` file
  (cross-platform-poor but adequate for Linux GPVM). Same fix applies to
  `append_pending` / `remove_pending` (`autoresearch_bo_michael.py:186-206`)
  — the latter does a read-write-truncate cycle that is *especially*
  unsafe across q writers.

- **Source of truth for the barrier is the SqliteSaver checkpoint, not the
  leaderboard TSV.** The leaderboard is a derived artifact written *at the
  end* of the inner graph's harvest node. Polling it for "is child N done?"
  introduces a window where the child has crashed mid-harvest (no row) vs
  is still running (no row) — indistinguishable. Polling the checkpoint
  (`SqliteSaver.list(config={"configurable":{"thread_id":<child>}})`) gives
  the actual node state and last-update timestamp. Fall back to TSV only
  as a sanity cross-check.

- **Config snapshot at submit-time generalizes the events-per-job stamp.**
  The same class of bug that produced [events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md)
  applies to anything else the closed loop reads at multiple points in
  time. Recommended: at submit, hash the effective config dict
  (STAGES[stage] + relevant `graph/config.py` constants) and stamp the
  hash under `state/<stage>_config_sha.txt`. Harvest reads the stamp and
  warns if the *current* hash differs. Cheap insurance against future
  silent miscalculations of the same family.

- **Scan_logs gating must precede leaderboard inclusion.** Inner graph
  has a `scan_logs` node that detects `GeomSolids1001` /
  [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) floods (see incident page). Today
  it logs and continues. For closed-loop, hits there mean the row is
  physics-broken (count saturated by stuck-track inflation) and must NOT
  feed the GP — else round N+1's picks chase a phantom Pareto frontier.
  Closed loop's `refit_and_check` should re-read the leaderboard with a
  scan_logs-clean filter, OR (better) the inner graph should refuse to
  append rows that failed the scan.

- **Deletion-test cost of the outer graph.** The outer round graph is a
  thin wrapper around a hand-coded for-loop. The depth-justifying
  benefit is **checkpoint-based resume across restarts** (kill parent →
  restart same `--thread-id` → barrier re-polls without re-launching
  children). Without that property, the LangGraph node structure is
  shallow and a plain `while round < max:` script is better. Implication:
  if WAL/locking issues force per-thread DBs, the outer graph loses its
  reason to exist and should collapse to a script.

- **q-parallel BO acquisition function quality.** With q=5 children all
  proposed from the same GP fit, the first-round picks share the same
  acquisition surface — they cluster unless the picker uses CL-mean / CL-min
  fantasy points (see [batch-bo](/concepts/batch-bo.md)). The current
  `gp_predict_helical.compute_explore_picks` uses Pareto-evenly-spaced
  picks across sob-rank, which is a workable proxy but NOT a calibrated
  acquisition. Round 1 may produce 5 nearly-degenerate picks if the
  Pareto frontier is short. Mitigation: enforce a minimum L2 distance
  between picks in normalized space, OR migrate to skopt-native CL-min.

- **N_crit margin at HELICAL_NSTEPS=5000 was empirically too loose.**
  SR00_00 (`dx=0.011, dy=125, halflen=251, angle=167`, N_crit≈4144)
  reproduced the GeomSolids1001 + stuck-track flood the gate was
  supposed to prevent (90/100 mustops_ce jobs flagged; see
  [bo-helical](/projects/bo-helical.md) "N_crit margin too loose"). scan_logs gating worked
  end-to-end — broken.txt written, leaderboard append suppressed —
  but the closed loop wasted 6 h of grid CPU on a doomed pick because
  the propose-time guard accepted it. Lowered to **2000** in
  `HelicalMode.HELICAL_NSTEPS`; closed_loop must be invoked with
  matching `--nsteps-budget 2000` (the two are co-equal, drift re-opens
  the hole). Earlier framing of this incident as a separate "throughput
  gate" was a misread — at the broken corner, the per-job cost IS the
  brokenness, not a slow-but-correct simulation.

## Cross-links
- Related: [mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md), [batch-bo](/concepts/batch-bo.md), [events-per-job-mid-flight-edit](/incidents/events-per-job-mid-flight-edit.md),
  [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md),
  [orchestrator-evaluation-2026-05](/concepts/orchestrator-evaluation-2026-05.md), [bo-helical](/projects/bo-helical.md), [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md), [mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md), [qlnei-sob-only-picker](/concepts/qlnei-sob-only-picker.md), [saturation-is-acquisition-relative](/concepts/saturation-is-acquisition-relative.md)
- Source: `graph/run.py:51` (sqlite connect, no WAL today),
  `autoresearch_bo_michael.py:150-156` (append_history, no lock),
  `autoresearch_bo_michael.py:186-206` (pending TSV r-w-t cycle, no lock),
  `pipeline.py:325-333` (events-per-job stamp pattern to generalize)
- Plan: `~/.claude/plans/zazzy-booping-ladybug.md`

## Propose-path topology (2026-06-06)

- **Closed-loop bypasses the propose + pending-TSV layer entirely.**
  `node_predict_picks` (`graph/closed_loop.py`) gets q x-points directly
  from `gp_predict_helical.compute_explore_picks` (cl_min) or
  `botorch_predict.py` (qLogNEHVI) — both are pure picker functions, no
  `append_pending` call, no `_flock_ex` on the pending TSV.
  `node_launch_children` then passes the pre-computed x-point to each
  child via `graph.run --x-point`. The pending TSV is only written by
  the CLI propose path and by `pipeline_io.propose_one` (manual single
  proposals); closed-loop rounds never touch it. Any refactor that
  "unifies all propose paths" must NOT route closed-loop picks through
  pending — that would re-introduce flock contention proportional to q
  per round for no benefit (closed-loop's barrier already gates re-runs
  via leaderboard presence, not pending).
- **CLI and `propose_one` ask the optimizer DIFFERENTLY for the same
  leaderboard.** CLI's `_cmd_propose_locked` uses
  `opt.ask(n_points=q, strategy=args.strategy)` (skopt's native Constant-
  Liar batched ask, strategy ∈ cl_mean/cl_min/cl_max). `propose_one`
  uses `opt.ask()` once (q=1; the graph node is per-config). Same
  leaderboard → different candidate sets across the two paths. Neither
  is wrong; the divergence is structural. A future shared "BOProposer"
  cannot collapse these without losing one feature.

## Child terminal-state signatures — preflight-fail vs harvest zero-row (2026-06-28)
A child that ends `[run] done` with **`objective: null` is NOT necessarily a bug** —
disambiguate by the artifacts before alarming:
- **Preflight-failed (managed overlap, infeasible geometry):** child log shows
  `preflight: fail_managed` ×N then `[graph] terminating <cfg>: preflight=fail_managed
  attempts=3/3` (MAX_PROPOSE_RETRIES=3) → `[run] done` objective=null. Grid dir has
  **only `geom/`** (no stage dirs), **no summary.json**, and **no `zero_row[...]` line**.
  Expected rejection — the geometry never reached the grid. (Seen pt6d18 R0: 5/10
  Sobol picks fail_managed — prodtarget6d plate box has a large infeasible region.)
- **Harvest zero-row (geometry ran, metric extraction failed):** child log HAS
  `zero_row[<cfg>] cause=<harvest_exception|metrics_none|obj_unparseable>`, grid dir
  has full stage outputs + a harvest/ dir. THIS is the one to investigate
  (cf [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)).
So: "done + objective=null + no zero_row + geom-only grid dir" = preflight reject (fine);
"done + objective=null + zero_row cause=..." = real harvest problem.

## Barrier checkpoint inspection (2026-06-06)

- **Terminal-check helper now lives in `graph/build.is_child_terminal`
  (was `closed_loop._child_terminal_via_checkpoint`).** Signature is
  `is_child_terminal(thread_id, child_graph) -> bool`. The
  `thread_id or name` legacy fallback moved to the call site
  (`closed_loop.py` barrier loop) — the helper itself no longer knows
  about config names. `_build_graph` was renamed to public `build_graph`
  in the same refactor (callers: `graph/build.py:graph`, `graph/run.py`,
  `graph/closed_loop.py` barrier).
- **`compile(checkpointer=saver)` is not free — must compile inner graph
  ONCE outside the polling loop.** `build_graph().compile(...)` is pure-
  Python topology but it re-wires the checkpointer object on every call;
  per-tick re-compile is wasted work that scales with `q × ticks_per_round`
  (e.g. 5 children × ~36 ticks at `CLOSED_LOOP_BARRIER_POLL_SEC=300` over
  a 3 h round ≈ 180 needless compiles). Current pattern at
  `graph/closed_loop.py` barrier (compile once outside `while True:`,
  reuse across ticks) is load-bearing — preserve it in any future
  refactor.
- **`MemorySaver` has no snapshot-write API.** Unit-testing the
  "real terminal" branch of the disambiguation logic (`snap.values`
  populated AND `snap.metadata.step >= 1`) requires actually running ≥1
  super-step through a compiled graph against the saver; you cannot
  inject a fake snapshot. The fresh-thread branch (`step=-1` → False)
  IS testable cheaply with `from langgraph.checkpoint.memory import
  InMemorySaver` + compile + `get_state` on a never-run thread. So any
  test of the terminal-check logic is a two-path design: cheap fresh-
  thread unit + a one-node toy `StateGraph` for the terminal path.

## Open questions / TODO
- Whether `compute_explore_picks` should grow a `--min-spacing` knob or
  the closed loop should post-filter picks. Choose before round 2.

## Resolved (2026-05-21)
- **WAL safety on the mount: OK.** `graph_data/` is on **CephFS**
  (`/exp/mu2e/app` resolves to ceph), not NFS — POSIX locking semantics
  apply. Smoke (5 concurrent writers × 5 inserts with 2s gap, 30s
  connection timeout): 25 writes, 0 lock errors, 11s wall. Aggressive
  test (4 writers × 50 inserts back-to-back, 5s timeout): one
  `OperationalError('database is locked')`. Closed-loop workload (q=5,
  ~10 checkpoints per child over 2h ≈ 0.01 writes/sec) is two orders
  below the failure regime. Adopt: explicit `PRAGMA journal_mode=WAL`
  + 30s SQLite timeout in `graph/run.py` and `graph/closed_loop.py`.
  **OVERTURNED 2026-06-09**: the smoke was 3 orders below the actual
  load and only tested lock-acquire contention, not WAL mmap coherence
  across processes — see [closed-loop-sqlite-checkpoint-transient-corruption](/incidents/closed-loop-sqlite-checkpoint-transient-corruption.md).
- **Driver shape: LangGraph outer graph (closed_loop.py) wins the
  deletion test.** WAL works → cross-thread checkpoint visibility
  preserved → barrier can re-poll via `SqliteSaver.list({thread_id})`
  after parent restart, justifying the LangGraph node structure.

## Blast radius if CHECKPOINT_DB is deleted mid-run (2026-06-09)
Survivable; checkpoints DB is a resume-convenience, not a source of truth. Grid jobs never touch it. Leaderboard TSV + `state/*_cluster.txt` + `state/broken.txt` + `state/scan_logs/` remain authoritative for "is this child done." Parent's currently-open conns hold fds to the unlinked inode → continue reading the stale snapshot and writing to a phantom file invisible to anyone else (parent hangs at barrier until timeout, but no data is lost). After parent kill + restart: fresh DB at the path → outer graph re-runs from scratch → `launch_children` correctly stale-skips all 10 children via the cluster-file guard (with the 2026-06-09 fix, loud SKIP per child + RuntimeError from empty-launch guard). Implication for node-local DB choice: `/scratch` wipe between sessions costs mid-round resume capability but nothing physics-critical — weakens the "LangGraph outer graph wins the deletion test" claim above.

## Filesystem coherence for CHECKPOINT_DB (2026-06-09)
`/exp/mu2e/data` is ALSO CephFS (same MDS cluster as `/exp/mu2e/app`), so moving the DB there does NOT fix WAL incoherence — only the journal-mode change (`DELETE` + `synchronous=FULL`) makes a network-FS path safe. Node-local mounts on GPVMs: `/scratch` (xfs, ~9 GB, lost on reboot), `/var/tmp` (ext3, ~16 GB, semi-persistent), `/tmp` (cleared often).
