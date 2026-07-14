# closed-loop-runner — multi-round Pareto-pick BO driver

**Type:** driver
**Status:** active
**Updated:** 2026-07-13 (rolling failure paths live-validated on foilsflash15 abort)

> **Validate a NEW picker with a SMALL round, not full-stats q=10** (lesson
> from foilsflash09, 2026-07-08). A picker only changes the PROPOSAL step; the
> dry-run (`--dry-run`) already proves it emits valid in-bounds spread picks,
> so a live shakedown only needs to confirm the grid+harvest+leaderboard path
> survives the new proposal source — q=2-3 (and/or a non-full-stats config)
> does that for a fraction of the cost. foilsflash09 ran q=10 at full flash
> stats (~1000 grid-hours, ~5h, NFS-poison-pool exposure) on a SATURATED line;
> the extra 7 evals bought only plateau statistics. Right-size the next one.

## Summary
Multi-round closed-loop runner that wraps q parallel
[[graph-runner]] children per round, refits the GP between rounds, and loops
until budget/convergence/operator stop. Replaces the prior operator-paced
loop (human computes 5 Pareto picks → launches 5 chains by hand → waits 2 h
→ refits → repeats) with a checkpointed LangGraph driver. Helical mode only
in this phase.

## Key facts
- **`--rolling` FAILURE PATHS LIVE-VALIDATED 2026-07-13 (foilsflash15):**
  first real flight hit the MuBeamCat tape migration → all children died at
  mubeam submit; observed working: first-resolution barrier exit, replenish
  waves w1/w2 (q_next math + pending JSON handoff), per-wave krb5+bearer
  refresh, and the full-pool streak abort (`no_row_streak 5/5 → ABORT`,
  parent exits clean, 9 launched / 0 rows / 0 grid jobs / ~75 min). Abort
  leaves in-flight children ORPHANED (they self-terminate at their own
  failed submit here; a healthier abort scenario would leave them running —
  same orphan shape as [[closed-loop-final-round-orphan-children]]).
- **`--rolling` FULLY VALIDATED end-to-end (foilsflash16, 2026-07-14):**
  10/10 rows, 0 failures, parent exited via `rolling_done` (budget spent,
  pool drained). Every mechanism fired live: first-resolution barrier exit,
  replenish waves w1–w5 (1 pick each, pool held at 5 continuously), one
  2-resolution wave (w5 +2), drain ticks w6–w8 (q_next=0, no picker
  subprocess), clean DONE. **Measured: 10 evals in 8 h 16 m (20:53→05:09) =
  1.21 evals/h at q=5** vs barrier-mode estimate for the same shape (2
  rounds × slowest-of-5 ≈ 9–11 h) → ~10–25% saved. Gain is structurally
  small at max_evals=2q (only 5 replenishes + a full-cost drain tail);
  the +30–50% projection needs production scale (many waves, larger q)
  where drain cost amortizes. Best new row sob 3.83 (R00_02) — saturated
  line as expected; the 10 rows double as the held-out GP test set
  ([[ml-stack-review-2026-07]]).
- **`--rolling` (wired 2026-07-12, commit c47cd90):**
  pool replenishment — barrier exits on the FIRST resolution, predict_picks
  refills only the free slots and passes in-flight x_points to
  botorch_predict `--pending-json` (X_pending fantasies; pareto_sob spreads
  via its avoid set). Budget = `--max-evals` (default q·max_rounds);
  `--max-rounds` is ignored; `round_idx` counts replenish WAVES (still feeds
  `R{NN}` names, so rolling children are `prefixR03_00`-style with mostly
  one pick per wave). Zero-rows guard generalizes to a streak: q consecutive
  rowless resolutions aborts (foilsX04 shape). 24h barrier backstop ENDs the
  run loudly under rolling (a hung-alive child would pin a slot forever).
  Default (no flag) is byte-identical to barrier mode. Expected +30-50%
  evals/day (kills the slowest-of-q tail — see [[bo-noise-budget]] lever #4).
  First live campaign should A/B a small `--max-evals` run before betting a
  full line on it.
- **Round wall-clock (measured 2026-06-18/19, q=10):** foils **~3 h/round** (foilsf18 R0 2h50m).
  prodtarget6d was **~5 h/round** at the old pot_only **100×5000** (pt6d08 R0 5h43m / R1 4h48m;
  pt6d09 R0 4h53m / R1 4h43m) → **dropped to ~3.1 h/round** after switching pot_only to
  **200×2500** (pt6d10 R0 3h00m / R1 3h13m, total 6h13m vs pt6d09's 9h35m = **−35%**). The
  split (njobs 100→200, events_per_job 5000→2500, constant 500k total) halves per-job wall +
  doubles parallelism; the **−35% (not −50%)** is because the fixed poll/harvest/stage-out
  portion doesn't shrink. Stats unaffected (500k preserved). Counterintuitive baseline:
  even single-stage prodtarget6d (pot_only) was SLOWER than foils' 4-stage pipeline at
  100×5000 because pot_only jobs are heavy (full PT G4 + NIEL SD + PyROOT StepPointMC
  harvest). Dominant per-round cost is grid run + stage-out + harvest-poll, NOT the BO
  refit (seconds) or submit (minutes). Derive fresh from child-log birth times:
  `stat -c %w graph_data/closed_loop_logs/<prefix>R0{0,1}_00.log`.
- **foilsflash per-stage + per-eval wall (measured foilsflash04 R0, 2026-07-01):** per eval
  **~4.5–5 h**; round wall **~5–6 h** (slowest of q=10). Stage boundaries = `<stage>_cluster.txt`
  (submit) → `<stage>_outputs.txt` (land) mtimes under `GRID/<cfg>/state/`:
  preflight+first-submit ~14 min; **mubeam ~75–90 min** (15 jobs × 200k ev, ~30-min/job payload);
  concat ~8–10 min; **mustops_ce ~75–90 min** (15 jobs × 75k ev); **elebeam_flash ~55–90 min**
  (200 jobs × 110k ev — QUEUE-bound not payload-bound, so `AUTORESEARCH_ELEBEAM_NJOBS` 100→200
  barely changes wall); harvest ~12 min (EdepAna + gallery flash + calo); inter-stage gaps
  ~2–8 min. The two long stages are the "fast config" FEW-BIG-JOB stages (mubeam/mustops_ce),
  NOT the 200-job flash stage. ~35-min eval-to-eval spread is pure grid-queue variance.
  - **Parallelization opportunity (elebeam_flash is INDEPENDENT of the sob chain, 2026-07-01):**
    the chain runs strictly SEQUENTIAL (`STAGES_BY_MODE["foilsflash"]` linear; mtimes confirm
    elebeam_flash submits only AFTER mustops_ce lands). But the sob chain (mubeam→concat→mustops_ce,
    internally coupled) and elebeam_flash share NO data — elebeam_flash resamples its own external
    EleBeamCat `auxinput` (run_number 1803) with the same foil geom, reading nothing from the sob
    stages. So flash could run CONCURRENTLY with the sob chain → per-eval wall drops from
    `sum` (~4.5–5 h) to `max(sob-chain, flash)` (~3.5–4 h, ~20–25%). Requires forking the graph
    into two parallel branches feeding one harvest (a `graph/` sequencing change, NOT a config tweak);
    do NOT attempt mid-campaign.
- **The mid-campaign edit freeze covers `botorch_predict.py` too (2026-07-11)**: it is
  NOT only pipeline.py/templates/graph — a multi-round campaign executes
  `botorch_predict.py` fresh at every round transition (`_botorch_picks_subprocess`
  spawns the botorch venv), so editing it mid-campaign changes the NEXT round's picker
  silently. Frozen while any parent with rounds remaining is alive; tests/, new
  standalone files, wiki/docs, and git operations stay safe.
- **Kill-verification gotcha (2026-07-11)**: launching via the Bash tool with
  `nohup python -m graph.closed_loop ... & echo PID=$!` reports the WRAPPER
  shell's PID, not the python's — killing that PID killed the wrapper while
  the real parent (PID+2) survived at the barrier, invisible to `ps -p <pid>`
  checks and to a monitor keyed on the dead PID. After any campaign kill,
  re-verify with the PATTERN (`ps -fu $USER -ww | grep "[g]raph.closed_loop"`),
  and key monitors on the python cmdline's PID from ps, not the $! echo.
  Silver lining exploited: a surviving parent whose killed children later get
  rows via recovery `evaluate` calls WILL resolve its barrier and continue to
  the next round (in-memory old parent code + on-disk new child code is fine
  when the child code is golden-validated).
    - **Chosen mechanism = "early-submit / late-poll", IMPLEMENTED 2026-07-01 → REVERTED 2026-07-02**
      (code removed after it BACKFIRED live — see the OVERTURNED bullet below; the graph is serial again,
      all 91 tests green; only the separate `pipeline.py` submit stderr-leak fix was KEPT). (NOT a LangGraph diamond.)
      `pipeline_io.run_stage` loops idempotent verbs `(submit, poll, list-outputs)` — submit no-ops if
      `state/<stage>_cluster.txt` exists. Wiring: `graph/config.py` `PRESUBMIT_STAGES_BY_MODE =
      {"foilsflash": ["elebeam_flash"]}` (filtered to `GRID_STAGES`); `pipeline_io.presubmit_stage()`
      (submit-only wrapper); `nodes.node_presubmit_parallel` (best-effort — a submit failure is logged +
      recorded in `errors` but does NOT terminate; the late stage node then submits serially = graceful
      degradation; deliberately does NOT write `state["stages"]`); `build.py` routes
      `render_preflight --"real"--> presubmit_parallel --> STAGE_NODES[GRID_STAGES[0]]` (no-op node for
      modes with empty `PRESUBMIT_STAGES` — michael/helical/foils/ipa/prodtarget behaviorally identical).
      Keeps the graph LINEAR — no `stages`/`errors` reducers, no fan-in (diamond rejected as higher-risk).
      Verified: 94 unit tests pass (3 new `TestPresubmitParallel`) + build guard both modes.
    - **LIVE-CONFIRMED working on foilsflash05 R0 (2026-07-02), with a submit-lock caveat.** In R00_00,
      `elebeam_flash_cluster.txt` was written **00:33:31** vs `mubeam_cluster.txt` **00:57:02** — i.e.
      elebeam_flash submitted FIRST, before mubeam (in the old serial code it was LAST, ~3 h after mubeam).
      So the flash grid run overlaps the sob chain as intended. **Verdict test = ORDERING, not gap:**
      elebeam submitted-before-mubeam (or before mustops_ce) = parallel; a small |Δt| is the WRONG test (an
      early check with a 5-min threshold false-flagged it SERIAL — the real Δt was ~24 min but in the
      *right direction*).
      **Second-order cost — the submit-lock serializes the presubmit burst.** With q=10 children each now
      doing TWO early submits (elebeam presubmit + mubeam), the per-`pipeline.py` submit-lock
      ([[concurrent-token-contention]]) processes all 10 elebeam presubmits (each a 200-job `mu2ejobsub`,
      ~4 min) AHEAD of the mubeam submits — observed elebeam presubmits at 00:33/00:37/00:41/00:45/00:49/00:53
      (~4 min apart), delaying each child's mubeam (→ sob-chain start) by ~20 min. So the realized saving is
      **~40-50 min/eval, NOT the full ~70-90 min** (the flash run is removed from the critical path, but the
      lock congestion claws ~20 min back). Exact Δwall vs ff04's 4.5-5 h pending R0 landing.
    - **⚠️ OVERTURNED — the parallelization BACKFIRED at q=10; DO NOT USE (foilsflash05 R0, 2026-07-02).**
      The premise ("elebeam ~70 min hides behind the sob chain") assumed elebeam runtime is independent of
      submit timing. It is NOT: submitting all q=10 children's 200-job elebeam clusters up-front dumps
      **2,000 jobs on the grid at once → a grid squeeze → elebeam ran 258-301 min vs ff04's serial
      52-76 min (4-5× SLOWER).** Tell-tale: durations DECREASE across children (301→297→…→258) as the flood
      drains. **MECHANISM UNVERIFIED (2026-07-02):** the 4-5× slowdown was OBSERVED but its cause was INFERRED,
      not measured — `jobsub_q` idle-vs-running was never checked. FermiGrid has thousands of slots, but ours
      is a fairshare slice (priority decays as we consume), and a 2,000-job burst also contends on I/O the CPUs
      don't fix (677 MB `Code.tar.bz2` RCDS pull ×N, xrootd auxinput reads, `/pnfs` dCache stage-out). So the
      cause is fairshare throttling AND/OR dCache/RCDS I/O contention — NOT necessarily raw compute-slot
      starvation. Settle it next burst: split `jobsub_q` idle (→fairshare/slots) vs running-slow (→I/O). If it's
      fairshare and slots are actually plentiful for us, higher q / more jobs COULD help — don't treat the
      "revert" as proof the grid is full. In serial, each child's elebeam submits at the END of its chain, naturally spread over ~2 h →
      no peak contention. Result: elebeam finished AFTER the sob chain (+33 to +99 min for 9/10 children) —
      it never hid — and **R0 wall ≈ 6 h, NO better than serial.** Lesson: an "independent stage" overlap
      only pays off if the grid has spare slots for the concurrent burst; at q×njobs = 10×200 it doesn't.
      **Recommendation: REVERT** (remove `PRESUBMIT_STAGES_BY_MODE["foilsflash"]` → empty, or the node stays
      a no-op). If retried, must throttle the burst (smaller elebeam njobs, or stagger presubmits over the
      sob-chain duration, not up-front). The "~40-50 min saving" estimate above the fold is WRONG — superseded.
    - **Barrier hangs 24 h on a child that dies WITHOUT a terminal checkpoint (foilsflash05 R00_02).**
      R00_02 died at the `evaluate` node (`autoresearch_bo_michael.py evaluate` subprocess **120 s timeout**,
      pipeline_io ~:443) — harvest succeeded but the leaderboard-append timed out → child crashed, no row,
      no END checkpoint. The barrier polls child SqliteSaver checkpoints; a child with no terminal checkpoint
      is never counted resolved, so the parent parks in the R0 barrier until `CLOSED_LOOP_BARRIER_MAX_MIN`
      = **1440 min (24 h)** before timing out (parent alive, Sl, ~57 s CPU over 9 h — polling, not wedged).
      9/10 rows can be landed + grid empty, yet R0 never advances. Recovery = SIGTERM the parent (keeps the
      landed rows). The evaluate 120 s timeout under 10-way leaderboard-append contention may itself be
      aggravated by the parallelization's extra concurrency.
    - **elebeam_flash is the ONLY stage eligible for pre-submit-at-preflight** because it resamples the
      EXTERNAL EleBeamCat (`auxinput`), depending on nothing internal. **bo-ipa's `mustops_pileup` is
      NOT the same case** (earlier note here was imprecise): it resamples `concat`'s MuminusStopsCat, so
      it can only parallelize WITH `mustops_ce` (both post-concat) via a diamond — it can't be
      pre-submitted before concat exists.
- **Cold-start: `jobsub_q` empty for ~15–20 min after launch is NORMAL, not a stuck campaign (2026-07-03).**
  Before a child's FIRST `mu2ejobsub` (hence before any cluster shows in `jobsub_q`) it must complete
  (a) preflight (~15–20 min real G4 init) AND (b) a per-child **Code.tar.bz2 rebuild** — the submit does
  `tar xjf Code_helical_holeradii.tar.bz2` then re-bzips it to the 677 MB `Code.tar.bz2` (this is both the
  cold-start cost and the source of the [[data-quota-exhausted-grid-accumulation]] bulk). Under the submit-lock
  these serialize across children. So "N children launched, 0 jobs in `jobsub_q`" 20 min in = healthy setup
  phase, NOT failure. Confirm via the child's `graph_logs/submit_mubeam_*.log` mtime (should be current, e.g.
  showing the `tar cf - Code/ | bzip2` step). First clusters appear ~5–10 min after preflight passes.
- **Parent liveness — don't mistake barrier log-silence for a dead parent (2026-07-01).**
  The barrier writes its `{"round_idx":..,"completed":N,..}` line on STATE-CHANGE, not on
  every `CLOSED_LOOP_BARRIER_POLL_SEC=300` poll, so a **stable barrier wait produces a 15–20+ min
  log gap** while `completed` doesn't move — this is normal, not a hang. Confirm with
  `ps -p <parent_pid> -o stat,etime,cmd`: **`STAT=Sl` = healthy interruptible sleep** between polls.
  **`pgrep -af "closed_loop.*<prefix>"` can FALSE-NEGATIVE** (returned empty on a live foilsflash04
  parent that `ps -p 499881` then showed running) — treat a negative pgrep as "check with `ps -p`",
  NOT as "parent dead". **Complement (2026-07-06): an inline `ps -eo cmd | grep 'closed_loop'` launch-GUARD
  can FALSE-POSITIVE** — the Bash-tool wraps the whole command in a `bash -c '…eval <string>…'`, so the
  guard's own pattern text ("closed_loop", "graph.run") appears in that argv and `grep` matches ITSELF →
  spurious "something already running" ABORT (hit on the foilsflash08 launch). Fixes: guard on the
  LEADERBOARD prefix (`grep -c '^foilsflash08' leaderboard...`) or a state file instead of `ps`, or run the
  `ps` check in a SEPARATE call from the launch. The `[c]losed_loop` bracket trick does NOT help in a
  compound guard+launch call — the LAUNCH command text in the same wrapper argv carries the raw string
  regardless of bracketing the grep pattern. **Refinement (2026-07-07, verified)**: in a WATCH-ONLY
  command (no launch text in argv), the bracket trick DOES work for `pgrep -f` — a monitor polling
  `pgrep -f "graph[.]run.*foilsflash08"` matched exactly the 20 real children and not its own shell
  (argv has literal `graph[` where the regex needs `graph.`); beware lookalike substrings though
  (`[.]` would still match a literal `.` elsewhere, e.g. paths). Distinct from the genuine [[closed-loop-parent-signal-kill-midlaunch]]
  death (there the parent is truly gone AND children die too); here children were all `Sl`-alive
  with grid clusters running, the tell that the parent-negative was a pgrep artifact.
- **Log-watch grep trap (2026-07-10)**: the parent's JSON heartbeat lines
  (`{"round_idx":..., "zero_rows": null, "stop_seen": false, ...}`) contain the
  substrings `zero_row`, `FAIL`-adjacent keys, etc. — a monitor grepping the parent log
  with bare `zero_row|FAIL|decide_next` fires on every heartbeat. Anchor the patterns to
  the real event forms: `zero_row\[` (child log form `zero_row[name] cause=`),
  `decide_next\[`, `FAILED`, `barrier: all`.
- **Code**: `graph/closed_loop.py` (one file, ~510 lines). Outer state:
  `RoundState` TypedDict (mode/alpha/q/round_idx/children/completed_names/
  pareto_hashes/converged/errors + knobs). Outer graph nodes:
  `renew_token → predict_picks → assign_names → launch_children → barrier →
  decide_next`; `decide_next` either loops back to `renew_token` or ENDs.
  (`refit_and_check` was deleted 2026-05-29 along with convergence-by-hash;
  `predict_picks` snapshots `history_len_before` and `decide_next` checks
  for zero new rows.) `renew_token` runs `kinit -R` + `source setupmu2e-art.sh && getToken`
  at the top of every round and **hard `sys.exit(2)` if `getToken` fails**
  (continuing past expiry just orphans clusters). Operator runs `kinit`,
  re-invokes with the same `--thread-id`; the outer checkpoint resumes
  from `renew_token`. See [[kerberos-mid-run-expiry]].
- **Children are subprocesses, not LangGraph `Send()` branches.** Each pick
  becomes `python -m graph.run --thread-id <name> --config-name <name>
  --x-point dx,dy,hl,ang --no-mock --mode <mode>` via
  `subprocess.Popen(..., start_new_session=True)`. Subprocess isolation
  means a child OOM/kill doesn't touch siblings or the parent; restart of
  the parent doesn't re-launch in-flight children (barrier just re-polls).
- **The closed-loop picker does NOT enforce `is_buildable` (gap, 2026-06-03).**
  `node_predict_picks` → `gp_predict_{foils,helical}.compute_explore_picks`
  just does `opt.ask(q, cl_min)` within the box — no `is_buildable` filter
  (unlike `cmd_propose` / `propose_one`, which retry-loop on it). And the
  closed-loop launches children with `--x-point`, which **bypasses**
  `propose_one`'s guard (`graph/pipeline_io.py:86` — "x_override bypasses the
  guard"). So a geometrically-invalid pick goes straight to the grid and fails
  at preflight. It has never bitten foils only because the box is safe by
  accident (`max(extra_rIn)=50 == min(extra_rOut)=50`, so `rIn>=rOut` is
  measure-zero). **Any range change that breaks that coincidence (e.g.
  widening `rIn_dn` past 50) MUST first add is_buildable filtering to the
  picker, or reparameterize to remove the infeasible region.** See [[bo-foils]].
- **Barrier polls the SqliteSaver checkpoint, NOT the leaderboard TSV.**
  Per `[[closed-loop-bo-design]]` revision #3: the TSV is a derived
  end-of-harvest artifact, so using it as the barrier source-of-truth
  conflates "child crashed mid-harvest" with "child still running." A child
  is treated as resolved when ANY of: (a) its leaderboard row appears, (b)
  `<grid>/<name>/state/broken.txt` exists, (c) `saver.get_tuple(...).next`
  is empty (terminal checkpoint), (d) **its process is dead with none of
  a-c after one poll tick of grace** (added 2026-06-12; catches the
  foilsf08 crash shape — see
  [[closed-loop-sqlite-checkpoint-transient-corruption]]). Leaderboard read
  goes through `bo.MODES[mode].load_history()` which acquires the `flock`
  lock added in task #90.
- **Barrier waits on child process liveness, NOT a wall-clock window
  (2026-06-12).** There is no per-round pacing timeout: an alive child is
  always progressing (every grid stage inside it is bounded by pipeline.py's
  poll `cap_hours`), a dead one resolves via the pid check in two poll
  ticks. `--barrier-max-min` (default 1440 = 24h) is only a loud backstop
  for alive-but-hung children — tripping it is rare and always worth
  investigating. `--barrier-timeout-min` is DEPRECATED and ignored (still
  parses). The zero-rows early-exit in `decide_next` fires only when ALL of
  this round's `launched_names` resolved AND no new leaderboard rows landed;
  a backstop trip with pending children carries the round forward. Fix
  history + landmines in [[closed-loop-barrier-timeout-zero-rows-falsepos]]
  and `docs/closed-loop-barrier-fix.md`.
- **CLI**:
  ```
  python -m graph.closed_loop \
    --mode helical --q 5 --max-rounds 10 --name-prefix helical \
    [--alpha 1e5] [--nsteps-budget 2000] \
    [--stagger 90] [--barrier-poll-sec 300] [--barrier-timeout-min 240] \
    [--convergence-k 2] [--min-spacing 0.05] \
    [--pessimistic-calo] \
    [--thread-id auto] [--dry-run]
  ```
  Child names are derived as `{prefix}R{round:02d}_{j:02d}` — the `R` is
  the round marker, not part of the prefix. Default prefix `helical` →
  `helicalR00_00 … helicalR00_04` for the first round of q=5.
- **`--name-prefix` defaults to `"helical"` (`graph/closed_loop.py:670`) —
  always pass it explicitly.** Omitting it on a foilsg/foilsf/prodtarget
  launch silently produces `helicalR00_*` child names that collide with the
  real helical campaign's namespace and may even be skipped if any helical
  row of the same name already exists in the leaderboard. Bit me 2026-06-10
  launching foilsg04 → had to kill within 5s before any state landed and
  relaunch with the explicit flag. The hazard is per-campaign-launch (every
  fresh launch needs the override) — there is no project-wide convention
  that protects against forgetting.
- **Stop semantics**:
  - **Clean stop**: `touch
    /exp/mu2e/app/users/oksuzian/autoresearch/graph_data/STOP_CLOSED_LOOP`.
    Both `barrier` and `decide_next` poll this flag. In-flight children
    continue to completion (subprocess isolation); the parent exits at the
    next barrier poll or round boundary.
  - **Hard kill**: `kill <parent_pid>`. Children continue. Restart with the
    same `--thread-id` resumes from the last round checkpoint;
    `assign_names` treats names already in leaderboard or with broken.txt
    as completed, so `launch_children` skips them.
  - **Force-restart a round**: delete the round's leaderboard rows and
    re-invoke with the same thread-id.
- **Extending a COMPLETED campaign needs a FRESH `--name-prefix`, not a
  resume (2026-06-01, foilsY01→foilsY02).** A run that exited via
  `max_rounds` is a closed thread and CANNOT be given more rounds two ways
  that both look plausible and both fail:
  1. **Reuse the same `--thread-id` with a higher `--max-rounds`** → no-op.
     `main()` resume path passes `None` (not init state) when a checkpoint
     exists, so the new `--max-rounds` never enters state — the graph reloads
     its terminal checkpoint (already routed to END at `round_idx>=max_rounds`)
     and does nothing.
  2. **Reuse the same `--name-prefix` with a fresh `--thread-id`** → SILENT
     dead-on-arrival. A fresh thread restarts at `round_idx=0`, regenerating
     `{prefix}R00_{j}` names that are already in the leaderboard;
     `assign_names` marks them completed, `launch_children` skips all q, the
     barrier resolves with 0 children, and the zero-row safety gate ENDs
     immediately (same shape as [[foilsx04-all-preflight-ambiguous]]).
  **Correct continuation:** a new prefix (e.g. `foilsY01`→`foilsY02`). The new
  campaign seeds from prior rows via `load_history` (+ `load_priors`), so the
  GP starts informed — verified by `history_len_before=3` picking up
  foilsY01's 3 rows at foilsY02 round 0. New rows still append to the same
  per-mode leaderboard.
- **Convergence (deleted 2026-05-29)**: previously hashed the rounded
  (2 sig-fig) `q` GP picks and called the run converged when the last
  k hashes were identical. **Deleted entirely** after 15-run production
  audit: 0 demonstrated true saves (FT05/FT06 r0→1 collisions were both
  `--max-rounds 2` runs that would have exited at the same point), and
  1 documented false-positive (foilsX04 zero-row case — identical data
  → byte-identical fit → guaranteed collision). Replaced with a
  zero-row safety break in `node_decide_next`: `predict_picks` snapshots
  `len(load_history())` into state; `decide_next` compares against
  post-barrier length and ENDs if `new_rows <= 0`. `--max-rounds` is the
  budget cap; saturation is now diagnosed post-hoc from the leaderboard
  (Pareto-front movement plots, not a runtime flag).
  Historical notes on the old machinery (kept for context if it's ever
  reconsidered):
  - **2-sig vs 3-sig empirics (2026-05-29 agentic investigation)**: only
    3 hash collisions exist across 15 production parent logs ever —
    foilsX04 r0→1 (spurious, zero rows), helicalFT05 r0→1, helicalFT06
    r0→1 (both real saturation with +8 rows). On real FoilsMode
    progressions (X02/X03), 55–70% of q×D acquisition-argmax coords
    jitter *beyond even the 2-sig bin* between consecutive rounds with
    +6 to +10 new leaderboard rows; the 3rd-sig-fig coord-jitter rate
    is nearly identical (99/160 vs 101/160). Picks come from a fixed
    seed=42 Sobol pool of 2^20 points; the GP refit is the only
    round-to-round mover, and one new row routinely shifts the
    Pareto-knee argmax by several grid cells (cf. bo-helical n=86→87
    10× calo-cloud collapse). **Switching to 3-sig-fig** (one-line
    change at `closed_loop.py:206`: `mult = 10**(exp-1)` →
    `10**(exp-2)`) **would convert FT05/FT06-style real saturations
    into non-events** — organic 3-sig collision is ~10^(q·D)
    suppressed vs 2-sig. Correct fix for the foilsX04 false-positive
    is the orthogonal zero-new-rows gate in `node_refit_and_check`,
    not tightening the bin.
  - **Wide-range pathology** (the failure mode that *is* sig-fig
    relevant): `_pareto_hash` rounding is scale-relative to the VALUE,
    not to the search range — `rOut=184` has bin width 10 whether the
    BO range is `[80, 250]` or `[180, 200]`. So a too-wide range
    doesn't coarsen the hash at the optimum; instead it keeps the GP
    exploring across the full envelope so consecutive-round picks
    jitter in absolute terms big enough to cross 2-sig bins → hash
    never collides → real local saturation looks "still moving."
    Tightening sig-fig makes this worse. Principled fix is to replace
    hash-equality with **per-knob normalized-L2 distance** between
    consecutive pick-sets (e.g., all q picks within 5% of normalized
    range), which decouples from both knob magnitude and search-range
    width.
  - **Mechanism may not be earning its keep at all (2026-05-29)**:
    the 2 "legitimate" 2-sig convergence events (FT05, FT06) were both
    `--max-rounds 2` runs that would have exited at the same point
    regardless of the flag. **No production run has ever exited via
    convergence at round ≥ 2.** So the demonstrated record is: 0 true
    saves, 1 false positive (foilsX04), and no evidence the hash
    correlates with real saturation vs. "GP happened to re-propose
    adjacent Sobol cells." Strong case for either deleting the
    convergence machinery and relying on `--max-rounds`, or replacing
    with normalized-L2-distance gate. The foilsX04 zero-row fix is
    still required either way — it's about not advancing a counter on
    a degenerate round, independent of what the counter means.
- **q-pick spacing** (`[[closed-loop-bo-design]]` revision #7): even-spaced
  ranks along a short Pareto frontier yield near-degenerate picks.
  `gp_predict_helical.compute_explore_picks` is *supposed* to enforce a
  normalized-L2 ≥ `min_spacing` gate (default 0.05) and fall back to fewer
  than q picks if the frontier is too clustered. Future migration to
  skopt-native CL-min (`[[batch-bo]]`) is the cleaner long-term fix.
  - **2026-05-29 simplify-audit fixed**: `compute_explore_picks`
    (gp_predict_helical.py:347) had `min_spacing` declared in the
    signature but the call to `_select_picks(par_idx, s['Xd_all'], q,
    0.02)` hardcoded 0.02 — every closed-loop round prior to this fix
    used 0.02 regardless of `--min-spacing` or
    `CLOSED_LOOP_MIN_PICK_SPACING`. Fix: pass `min_spacing` through.
    Past leaderboard rounds are tighter-clustered than their
    `--min-spacing` setting suggests.
- **WAL gate** (`[[closed-loop-bo-design]]` revision #1, #6): the outer
  graph and q children all write to the same
  `graph_data/checkpoints.sqlite`. WAL is set explicitly in both
  `graph/run.py` and `graph/closed_loop.py` after every connect. Verified
  PASS on CephFS for realistic-rate workloads (5 writers × 5 inserts × 2s
  gap with 30s timeout, 0 errors); aggressive rates (4 writers × 50
  back-to-back inserts) did hit one timeout — that case is not expected in
  production but should be remembered.
- **Closed-loop logs**: per-child stdout/stderr lands at
  `graph_data/closed_loop_logs/<name>.log`. The outer parent's own stream
  goes to whatever stdout the operator gave it (typically `nohup … &` or a
  cron tail).
- **First-real-run (closed_helicalQ_r0, 2026-05-21) surfaced 3 bugs, all
  now patched in `graph/closed_loop.py`:**
  1. `CheckpointTuple` has no `.next` attribute (only `StateSnapshot`
     does). `node_barrier` now compiles `_build_graph()` against the
     shared SqliteSaver and calls `child_graph.get_state(cfg).next` per
     child thread_id.
  2. `main()` previously always passed `init` to `graph.stream()`, which
     re-seeded fresh state on restart and re-ran predict_picks →
     assign_names → launch_children, spawning duplicate `graph.run`
     children for the same configs. Fix: if a checkpoint exists for
     `thread_id`, pass `None` so LangGraph resumes from the last node.
  3. `node_launch_children` only skipped names whose record had a `pid`
     set. On crash-resume mid-launch this re-Popened siblings whose
     submission was already in flight (causing double cluster files /
     pending TSV pollution). Fix: skip names with any
     `<grid>/<name>/state/<stage>_cluster.txt`, a leaderboard row, or a
     `broken.txt`.
  These three failures all compound under the same pattern: **the inner
  child checkpoint and the outer parent checkpoint share the same
  sqlite DB but distinct thread_ids; the parent's "is this child done"
  signal must come from the child's StateSnapshot, not from the
  CheckpointTuple alone**.
- **2026-05-24: first `--max-rounds 2` real run** (`helicalFT05`) revealed
  a **barrier false-positive** in round 1, **now fixed**. Round 0 ran
  clean; round 1 children were declared "all 8 resolved" within ~minutes
  of launch because LangGraph's SqliteSaver returns an empty
  `StateSnapshot(next=(), values={}, step=-1)` for a thread_id with no
  checkpoint yet — indistinguishable from a terminal state by `.next`
  alone. Fix in `_child_terminal_via_checkpoint`: require
  `snap.next` empty AND `snap.values` non-empty AND `metadata.step >= 1`.
  See [[barrier-false-positive-round1]] for the resolution. The
  `--max-rounds 1` workaround in `/closed-loop-launch` is no longer
  strictly required but kept as a conservative default.
- **2026-05-24 (same day): second barrier false-positive on FT06**, also
  fixed. The snapshot-step gate was correct but masked a second compounding
  bug at `node_barrier` line 390: exit condition was
  `if len(completed) >= len(children)`. `completed` is preserved across
  rounds (intentional, so resumed runs don't re-check round-0 children),
  so on entry to round-1 barrier `completed` already had 8 round-0 names
  and `children` had 8 round-1 names → `8 >= 8` True on first tick →
  break before checking any round-1 child. Fix: replace count comparison
  with `if all(n in completed for n in children)`. See
  [[barrier-false-positive-round1]] for both bugs. **Until a clean
  `--max-rounds 2` real-run validates the combined fix, keep
  `/closed-loop-launch`'s `--rounds 1` default in place.**
- **2026-05-25 helicalPC02 (`--pessimistic-calo --max-rounds 2`) surfaced
  TWO new failures, both unfixed:**
  1. **Silent barrier timeout.** Round-0 barrier exited via
     "barrier: all 8 children resolved" log msg (good). Round-1 barrier
     exited at completed=9/16 (8 R00 carried over + 1 R01 leaderboard
     row) with NO log message. The `barrier_timeout_min` path in
     `node_barrier` returns silently — operator-visible state is
     indistinguishable from "all resolved" except by counting completed
     vs len(children). Add a "barrier: TIMEOUT at completed=X/Y" log
     before that return.
  2. **Orphan inner-runner hang between `run1b_mubeam` and `concat`.**
     `start_new_session=True` (Popen kwarg) means inner `graph.run`
     children survive parent death — adopted by init (PPID=1). After
     the silent timeout, 7/8 round-1 inner runners kept running for
     6+ hours, all stuck at the SAME inter-stage point:
     `run1b_mubeam_outputs.txt` present (timestamps 03:59–04:17), but
     `concat_cluster.txt` never appeared. Grid queue was empty, so
     they were not waiting on grid — they were spinning in the inner
     runner's polling loop. `R01_06` was the one that escaped and
     reached leaderboard. Root cause not yet known; needs a `py-spy
     dump` on a stuck pid. Practical effect: silently-orphaned children
     consume RAM/file-handles indefinitely and pollute the leaderboard
     with partial-round data (PC02 round-1 has 1 row, not 0 and not 8).
  **Operator implication:** treat `barrier_timeout_min` as a likely-hit
  bound, not a never-hit safety net. After a closed-loop "done", check
  `ps -ef | grep "graph.run.*<prefix>"` for orphans before declaring
  the run complete. Until #1 is fixed, the only way to tell timeout
  from clean exit is `completed` field in the final state.
- **2026-05-25 PC02 follow-up inspect: 3rd unfixed bug — concat
  convergence-poll never converges.** The "orphan runners hung 6+ h"
  were misdiagnosed: they are NOT hung waiting on grid. Per /proc
  forensics on a stuck PC02R01_00 inner runner:
  - Parent `graph.run` PID 2302141 was blocked in `wait4` on its
    child PID 2363885 = `pipeline.py --config <name> poll concat`.
  - Child sat in `hrtimer_nanosleep` (normal 2-min poll cycle).
  - `poll_concat_*.log` printed `queue:1/1 settled:0/1 (target=1)`
    every 2 min for 6+ hours unchanged.
  - But `jobsub_q` showed 0 jobs total AND `/pnfs/.../staged/concat/`
    contained 200 staged .art files.
  So the concat grid job(s) finished, outputs landed on /pnfs, queue
  drained — but the convergence-poll's "settled" counter never
  recognized them. The poll's settled-side reachability check
  (filename glob or jobsub-history query) is out of sync with what
  actually lands on /pnfs for the concat stage. This is the actual
  reason the parent saw `completed=9/16` at the barrier_timeout — 7
  of 8 round-1 children were spinning in this false-negative poll
  loop, not in a real grid wait. **Operator practical:** after a
  multi-hour `queue:N/N settled:0/M` pattern, cross-check
  `/pnfs/.../staged/<stage>/` directly; data may already be on disk.
  **Root cause + fix (2026-05-25):** `pipeline.py:470`
  `poll_cluster` settled = bare-form (`00000`) only; for this concat
  run the outstage held exactly one dir `00000.6d475c59` (hash-suffix)
  that never got renamed because the underlying art job died with the
  known xrootd `[3012] Pool unavailable` `FileOpenError` in PostEndJob
  (see [[concat-xrootd-fileopen-postendjob]]). **Key insight:**
  jobsub_lite only renames hash→bare on **zero-exit** jobs. A
  perma-hash dir means EITHER rename-in-flight OR FAILED-and-rename-
  skipped — counting hash as settled risks declaring success on a
  cluster where every job actually crashed. Fix in `poll_cluster`
  keeps `settled` = bare-form only (success-only semantics) but adds a
  failure-aware exit: when `in_queue == 0` AND all `njobs` dirs are
  present in either form AND `settled < target`, break with a WARN so
  `list_outputs` + harvest surface the failure loudly instead of the
  poll hanging forever. `list_outputs` (lines 502–513) already drains
  the genuine rename-in-flight tail (10-min cap), then globs bare-form
  — perma-hash dirs (failed jobs) end up missing from `*_outputs.txt`
  and harvest errors out on missing .art.

- **2026-05-31 foilsX08 (`--picker qnehvi --max-rounds 5`) first-launch
  crashed on `subprocess.TimeoutExpired` at `closed_loop.py:293`
  `_qnehvi_picks_subprocess`.** The hard-coded 600s timeout is too tight
  for the BoTorch qNEHVI subprocess pick-time at large n. n=204 foils
  leaderboard exceeded 600s; the overlay benchmark at the same n took
  ~90 min for q=10 picks. Bumped to **3600s** (1 h). qNEHVI runtime is
  super-linear in n; expect further bumps as the leaderboard grows past
  ~300. The `picks subprocess timed out` error surfaces as a Python
  Traceback in the parent log (NOT a LangGraph node error) and the
  parent dies before any child launches → no leaderboard rows added
  for the round, no barrier reached. Validate any future qnehvi launch
  by tail-watching for `launched <prefix>R00_00` rather than absence
  of error within 5 min.

## Campaign turnaround — where the wall-clock goes (2026-06-04, from foilsZ02)
Measured per-round walls (foilsZ02 q=3, child-log mtimes): **2h07 / 1h19 /
1h25 / 1h33 / 1h15 / 0h21**. The 21-min round is the tell — same work, but the
grid queue was empty.
- **Each eval = 4 grid stages run SEQUENTIALLY** (`mubeam → run1b_mubeam →
  concat → mustops_ce`) at **200 / 200 / 1 / 200 jobs** = ~601 jobs/eval
  (`graph/config.py:STAGE_TARGETS` + `pipeline.py:STAGES`). A round runs q of
  these in parallel; the **barrier waits for the slowest child's 4th stage**.
  Rounds are serial (GP refit between). So total wall ≈ rounds × per-round, and
  per-round ≈ slowest-child × (4 × [submit+queue+stage-out+harvest-poll]).
  - **CUMULATIVE vs CONCURRENT job counts (don't conflate — corrected
    2026-06-04):** 601 is the **cumulative** jobs an eval submits over its
    lifetime; because the 4 stages run **SEQUENTIALLY**, one eval has **≤200
    jobs in flight at any instant** (only its current stage). So peak
    *concurrent* grid load ≈ **q × 200** (≈2,000 at q=10), NOT q × 601. Totals
    for a q×R campaign: **cumulative = q·R·601** (e.g. 10×5 = 30,050 jobs),
    **per-round cumulative = q·601**, **peak concurrent ≈ q·200**. The
    quota-relevant number is q·200 (concurrent), the throughput-consumed number
    is q·R·601 (cumulative).
- **Grid queue contention is the DOMINANT, variable cost — not G4 compute.**
  ~20 min/round when slots are free vs ~80–130 min contended. The 4× sequential
  stage round-trips each pay their own queue + stage-out latency.
- **Turnaround levers, by ROI:**
  1. **Early-stop on saturation (~9h/campaign).** foilsZ02 peaked at R02, FoM
     flagged SAT by R04, yet ran all 10 rounds — R03–R09 ≈ 7×~80min wasted. Wire
     the `saturation_report.py` SAT verdict (or "no round-best improvement in k
     rounds") as an auto-stop; gate on "≥N evals AND no-improvement" to dodge the
     [[barrier-false-positive-round1]] / [[foilsx04-all-preflight-ambiguous]]
     false-positive history. NOT currently wired (`CLOSED_LOOP_MAX_ROUNDS`
     budget is the only stop).
  2. **Bigger q, fewer rounds (qNEHVI only) — but with TWO ceilings.** Wall
     scales with #serial barriers = #rounds, so q=10×3 beats q=3×10 *only up to
     a point*. (a) **Throughput ceiling:** peak *concurrent* load is ~q×200
     (≤200/eval since stages are sequential — see cumulative-vs-concurrent note
     above), q×601 *cumulative* per round; past the grid's concurrent-slot
     capacity, extra q just deepens the queue and stretches the slowest-of-q
     barrier — at q=3 (~600 concurrent) we already saw ~400–600 jobs queuing, so
     q=8/q=12 (~1600/~2400 concurrent) deepen contention, partly offsetting the
     fewer-rounds win. (b) **BO-learning
     floor:** rounds = adaptive-feedback steps; foilsZ02 needed R02 to find its
     2.017, so collapsing to 1–2 rounds degenerates the run into batch-Sobol
     (no GP steering). Keep **rounds ≥ ~4**. Also `90s stagger × q` front-loads
     each round's launch (q=8 → ~12 min just launching). cl_min boundary-
     collapses at high q ([[batch-bo]]) but qNEHVI doesn't — so qNEHVI runs go
     wide-and-shallow within these two ceilings (practical sweet spot ~q=8–12 ×
     4 rounds, grid-quota permitting).
  3. **Memory → schedulability.** Smaller VmPeak → smaller mem request → more
     eligible slots → less queue wait. FTFP_BERT's −45% VmPeak ([[g4-speed-knobs]])
     attacks the #1 bottleneck — turnaround justification for the flip, not just
     OOM-safety.
  4. **Structural:** the 4-stage serial chain (incl. a full grid round-trip for
     the 1-job `concat` merge) is 4× the queue+stage-out latency per eval —
     biggest structural target, but architectural not a knob.
  - Minor: `CLOSED_LOOP_BARRIER_POLL_SEC=300` adds ≤5 min/round detection lag
    (~50 min/10-round campaign); safe to drop to 120s (write rate ~0.01/s).

## Cross-links
- Related: [[graph-runner]], [[closed-loop-bo-design]], [[bo-helical]],
  [[batch-bo]], [[autoresearch-bo-michael]], [[scalarized-objective]],
  [[kerberos-mid-run-expiry]], [[g4-speed-knobs]]
- Regression tests: [[tests]]
- Source files: `graph/closed_loop.py`,
  `graph/config.py` (CLOSED_LOOP_* constants),
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py`
  (`compute_explore_picks` library entry point)
- Operator stop file: `graph_data/STOP_CLOSED_LOOP`
- Skills: `/closed-loop-launch [prefix] [--rounds N] [--q Q]` wraps the
  `nohup .venv-graph/bin/python -m graph.closed_loop …` recipe (auto-picks
  next free `helicalFT##` suffix); `/closed-loop-status [prefix]` reports
  parents alive + jobsub queue + parent-log tail + leaderboard top-5.
  Sources: `.claude/commands/closed-loop-launch.md`,
  `.claude/commands/closed-loop-status.md`.

## Saturation FoM (post-hoc, not runtime — 2026-05-29)
- Because `obj = sob - α·calo` is already scalarized, full MOBO HV/EHVI
  machinery is overkill. Recommended post-hoc FoM: **best-scalar regret
  plateau** — per round compute `Δbest = max(obj_round) -
  max(obj_all_prior)`; declare saturated when `Δbest ≤ ε ·
  (max(obj_round1) - max(obj_round0))` for the last k=2 rounds (ε=0.05).
  Pair with **Pareto-set Jaccard turnover** as a secondary check to
  catch "stuck in one Pareto region" that pure best-obj misses.
- This is what convergence-by-pareto-hash was trying to be, but
  anchored on **leaderboard outcomes** (rows that actually landed)
  not GP-proposed coords (which jitter across Sobol cells even at
  saturation — see the 2026-05-29 audit above).
- Numbers in `[[bo-helical]]` ("HV +1.6% / hit-rate 62%→38%") come from
  one-off `/tmp/pareto_saturation.py` (W=20 window, 2D HV via
  axis-aligned rectangle stacking). Promoted 2026-05-29 to
  `autoresearch_grid/mmackenz_table_plots/saturation_report.py`
  (~220 LOC); reads any leaderboard, parses `<prefix>R##_##` to derive
  rounds (rows without that pattern lumped as "seed"), emits 4-panel
  PNG (HV / PF-size / rolling hit-rate / per-round Δbest bars +
  ε·anchor threshold line) + console verdict.
  **Run with `.venv-botorch/bin/python`** (matplotlib); `.venv-graph`
  has no matplotlib. Optional `--prefix foilsX05` to isolate one BO
  campaign from prior history in the same leaderboard.
  - **GOTCHA — a MULTI-campaign prefix pools rounds (2026-06-03):** passing a
    prefix that matches several campaigns which each reuse R00–R09 (e.g.
    `--prefix foilsY` matches foilsY01…Y05) makes the per-round Δbest panel
    POOL by round number across campaigns — "R03=2.00" is then *whichever*
    campaign's R03 was best (foilsY02's), not one run's progression. The
    resulting VERDICT is cross-campaign-blind (says "not saturated" even when
    every campaign plateaued, because it can't see "campaign N didn't beat
    N−1"). The HV / PF-size / hit-rate panels ARE valid (eval-indexed,
    campaign-agnostic). For a true saturation curve use a SINGLE-campaign
    prefix (a 10-round run like foilsY05 is the right analog, as foilsX07 was
    for v1). See [[bo-foils]].
  Validated
  2026-05-29: bo-helical-v2 fires SATURATED at R02 (hit-rate 70%→15%,
  Δbest=-1.02 vs ε·anchor=0.0042); bo-foils-v1 stays not-saturated
  through R04 (hit-rate 55%→50%, Δbest monotone +0.058 to +0.161).
  Closed-loop runtime auto-stop NOT recommended — that's what the
  deleted machinery already attempted and the 15-run audit showed
  wasn't earning its keep.
- **Rolling hit-rate is non-monotone — Δbest is the real verdict
  (2026-05-31, foilsX08).** The W=20 hit-rate (fraction of new evals
  that extend HV in the last 20) can REBOUND late in a saturated run
  if a diverse-picker batch lands and most of its q points scatter to
  fresh corners of the (sob, -calo) frontier without exceeding the
  obj-best ceiling. Concrete: foilsX08 R00 (qNEHVI, q=10) flipped tail
  hit-rate 55%→0% (post-X07 R06, slide 14 hand-authored) back up to
  **65%** while Δbest stayed negative for 8 consecutive rounds (R02–R09)
  and VERDICT remained SATURATED. The diversity-overlay finding (qNEHVI
  scatters into corners, [[batch-bo]]) is the *cause*, not a
  contradiction. **Trust per-round Δbest plateau for the SAT verdict;
  treat the rolling hit-rate as a diversity indicator, not a saturation
  indicator.** Hand-authored hit-rate numbers in slide decks decay
  invisibly — auto-stamp them or drop them.

## Open questions / TODO
- Barrier timeout default (240 min) may be tight if a grid stage hangs;
  configurable but should be revisited after the first multi-round real
  run.
- Convergence by Pareto-hash equality is sensitive to numerical jitter;
  may need to switch to a Hausdorff/L2 metric if it never triggers.
- michael-mode closed loop is out of scope for this phase. Same pattern
  applies once a `compute_explore_picks` equivalent exists for michael.
- Studio observability for the outer graph's checkpoints (Studio only
  attaches to the dev server's in-memory store, not headless SqliteSaver).
- `renew_token` only fires at round boundaries (every 6-8 h). A single
  round's grid stages can still outlive the renewed ticket if a stage
  hangs near the 25 h krb5 limit; consider a sibling watchdog cron that
  `kinit -R`s every ~12 h independent of the closed loop. See
  [[kerberos-mid-run-expiry]].
