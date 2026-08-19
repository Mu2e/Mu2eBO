# Minimal foilspf workflow — design

**Status:** approved in brainstorming 2026-08-19, not yet planned or implemented.
**Goal:** cut ~3,000 LOC of orchestration from the BO loop without changing a
single physics or metric path, and retire the largest incident cluster in the
project by construction rather than by guard.

## 1. Motivation, measured

The request was "bare minimum working workflow that works on foilspf — our
codebase is too large." All four candidate pains were confirmed by the
operator: too much to reason about, hard to hand to a collaborator, too much
dead surface, too fragile to change.

What the measurements actually showed:

- **The size is not per-mode branching.** Exactly **5** hardcoded mode-name
  strings remain in all of `core/` + `graph/`. The ModeSpec registry refactor
  worked. Deleting mode specs would save nothing — they are JSON data.
- **The size is orchestration.** `graph/` is 2,524 LOC; `tests/` is 10,494 LOC
  (54% of the repo) with 1,470 of it testing orchestration machinery.
- **The orchestration layer owns the incidents.** 11 of 65 wiki incidents are
  rooted in the checkpointer and barrier: thread-id collision, WAL corruption
  after kill, transient checkpoint corruption, msgpack `np.int64`, barrier
  false-positive, barrier-timeout zero-rows false-positive, final-round orphan
  children, stale-cluster silent no-launch, rolling no-row-streak false
  increment. None is physics.
- **Both the parent round-loop and the child chain are `StateGraph`s**, and
  both are checkpointed to `checkpoints.sqlite`.
- **The child graph is linear**: `propose → render_preflight → stage_mubeam →
  stage_mustops_ce → stage_elebeam_flash → harvest → scan_logs → evaluate →
  END`, with two conditional edges (preflight pass/fail, stage failure).
- **The parent graph is linear with one loop-back**: `renew_token →
  predict_picks → assign_names → launch_children → barrier → decide_next →
  (renew_token | END)` — 6 supersteps per round.

### The checkpointer has never once fired

Audited across every parent log in
`/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/`:

| | |
|---|---|
| Campaigns with parseable rounds | 51 |
| Ended cleanly | 44 |
| Died mid-flight (the checkpointer's opportunity) | 7 — `foilsflash01`, `foilsflash05`, `foilsflash19`, `foilspfbpz07`, + 3 SMOKE probes |
| **Resumed from a checkpoint** | **0** |
| Incidents the checkpointer *caused* | 5 |

Detection: a resumed run restores state and streams `round_idx > 0` as its
first value. All 51 logs start at 0. The only undercount would be a crash
recovered under a *new* name-prefix — which is a fresh campaign, not a resume,
and is precisely what the documented recovery in
`wiki/incidents/closed-loop-stale-cluster-silent-no-launch.md` instructs
("use a new name-prefix or rm the stale cluster files"). The feature's own
recovery path routes around it.

On the real crashes it was net-negative: `sqlite-wal-corrupt-after-kill` is the
case where the checkpointer *blocked* the restart (next run died at
`PRAGMA journal_mode=WAL` with "file is not a database" while the main DB
passed `integrity_check`; fix was to move the WAL sidecars aside).

This mirrors precedent already set in this project: convergence-by-Pareto-hash
was deleted 2026-05-29 after "15 production runs showed 0 true saves and 1 false
positive." This is 51 runs, 0 saves, 5 incidents caused.

Note also that the *useful* half of resume is not the checkpoint. Per
`graph/closed_loop.py`'s own docstring, re-invocation works because
`assign_names` treats names already in the leaderboard (or carrying
`state/broken.txt`) as completed. The leaderboard and the filesystem do that
work, and both survive this change.

## 2. Decisions taken

Recorded because they were operator choices, not derivations:

1. **LangGraph stays.** The operator elected to keep it to preserve the door to
   LLM decision nodes — the same rationale as
   `wiki/concepts/orchestrator-evaluation-2026-05.md`, and the one rationale on
   that page that has not lapsed. (The others have: `interrupt()` /
   `Command(resume=…)` are **never used** anywhere in the repo; Studio was
   retired 2026-07-17; the checkpointer's crash-survival value is 0/51 above.)
2. **No migration to another orchestrator.** Prefect was the 2-of-3 consensus in
   the 2026-05 evaluation, but its wins (cron, retry policy, run history,
   dashboards) are things this project does with `nohup`, an existing retry
   loop, and a TSV. Parsl and Snakemake want to own job submission, which
   prodtools/jobsub already does for SAM/ledger/tarball reasons. Swapping
   engines keeps the layer and its failure modes.
3. **Crash-resume mid-chain is dropped.** Explicitly deprioritized by the
   operator; justified by the 0/51 audit.
4. **Mock mode is dropped.**
5. **q-parallel children + barrier, and multi-round auto-refit, are kept.**
6. **Parent becomes a plain Python loop; the child stays a `StateGraph`.** The
   child is where real branching lives (preflight pass/fail, per-stage failure,
   `scan_logs` triage) and where an LLM node inserts naturally. The parent's six
   nodes are pool bookkeeping in a straight line; an LLM "should we stop?" call
   there is a function call in the loop.
7. **`graph/run.py` keeps both roles** — hand-run one geometry (`--x-point`) and
   parent-spawned child — on one entry point, so running a child by hand
   executes exactly the code the campaign runs. Splitting them invites
   "works by hand, fails in the campaign."

### Cost of decision 1, stated honestly

Keeping LangGraph keeps most of the 32-of-77 locked packages that make up the
langgraph/langchain cluster and its transitives. Dropping only the checkpointer
sheds roughly three (`langgraph-checkpoint-sqlite`, `aiosqlite`, `sqlite-vec`).
The LOC and incident wins survive; the dependency win largely does not. This
also means `docs/pyenv-publication-plan.md`'s goal of reducing the CVMFS ask to
the ML core alone is **not** achieved by this work.

## 3. Architecture

### Unchanged (the value)

`core/botorch_predict.py` (GP picker), `core/geom_template.py` (profile →
geom), `core/harvest.py`, `core/leaderboard.py`, `core/mode_json.py`,
`core/modes.py`, `core/paths.py`, `core/prodtools_exec.py`. Also unchanged: the
leaderboard TSV schema and its file locking, `stage_entries/*.json`, the
mode-spec JSON schema, and `pipeline.py`'s per-stage idempotency guards.

`core/pipeline.py` keeps its CLI. It is the stalled-chain recovery path and the
first thing a second operator reaches for; it stops being the primary seam but
is not deleted.

### The child

Keeps its `StateGraph`, its nodes, and its edges — this is the LLM door.
Compiled **without** a checkpointer. `node_mock_grid` and its routing branch are
removed.

### The parent

Replaced by a bounded work-pool loop. Rolling is the production mode — all
recent campaigns (`foilspfbpz04`–`07`, `foilspf05`) ran `q=20 rolling
max_evals=40` — so `q` is pool *width*, not batch size:

```python
inflight = {}                      # future -> (name, x)
launched = 0
while launched < max_evals or inflight:
    while len(inflight) < q and launched < max_evals and not stop_flag():
        renew_token_if_stale()
        x, name = next_pick(mode, picker,
                            x_pending=[x for _, x in inflight.values()])
        inflight[pool.submit(run_child, name, x)] = (name, x)
        launched += 1
    done = next(as_completed(inflight))          # the barrier
    name, x = inflight.pop(done)
    record(name, done.result())                  # row, or failure + reason
```

Children remain subprocesses (`python -m graph.run …`), so per-child log files
and isolation are preserved; the pool threads simply wait on them.

**A child resolves when its process exits.** That is one truth source,
replacing five: checkpoint terminal, `pid_alive`, `*_cluster.txt`,
`broken.txt`, and leaderboard membership. Outcome is classified from exit code
plus artifacts: exit 0 with a leaderboard row is success; anything else is
failure with the reason read from `broken.txt` or the child log.

`run_child` is an **injected callable**, which is the test seam.

### Four incidents become structurally impossible

| Incident | Why it cannot recur |
|---|---|
| `barrier-false-positive-round1` | No checkpoint `.next` to misread |
| `closed-loop-barrier-timeout-zero-rows-falsepos` | No parent-level barrier timeout; a hung child times out on its own cap and cannot be misread as "all failed" |
| `closed-loop-final-round-orphan-children` | `or inflight` in the loop condition drains the pool before exit |
| `rolling-no-row-streak-false-increment` | Each child's outcome is observed as it resolves; no wave baselines exist for a row to be absorbed into |

The last is the point of the exercise: the recorded fix was name-based
accounting layered on wave baselines. Removing waves removes the bug class.

Two incidental wins: `x_pending` becomes the literal in-flight set rather than a
`pending_*.tsv` that can drift (the TSV is still written, as an observability
artifact that is never read back); `STOP_FLAG` and Kerberos renewal become an
`if` and a call in the top-up loop.

## 4. Scope

**Modes.** Keep the seven `foilspf`-family specs (`foilspf`, `foilspf2k`,
`foilspfbp`, `foilspfbpx`, `foilspfbpz`, `foilspfbw`) plus `foilsflash`, the
objective lineage they inherit. Archive the four one-shot A/B specs (`ipa625`,
`ipafix`, `ipaovr`, `nominal` — 2 rows each). This is tidiness worth ~0 LOC and
is explicitly *not* where the size is.

**Where the size is:**

| | now | after |
|---|---:|---:|
| `graph/` orchestration | 2,524 | ~900 |
| `tests/test_closed_loop.py` | 1,022 | ~250 |
| `tests/test_child_tracker.py` | 214 | 0 |
| `tests/test_wal_multiwriter_stress.py` | 235 | 0 |
| `core/pipeline.py` | 1,919 | ~1,700 |

Net ≈ **3,000 LOC removed.**

**Deleted modules:** `graph/child_tracker.py`, `graph/presniff.py`,
`graph/config.py` (folded into `core/paths.py` + the mode spec), most of
`graph/pipeline_io.py` (calls `core/` in-process; the subprocess firewall
existed for the checkpointed runner).

**`graph/state.py` is NOT deleted.** It holds `BOIterationState`, the *child*
graph's state, imported by `build.py` and `nodes.py` — both of which stay. Only
the parent's `RoundState` goes, and it is defined inline in
`graph/closed_loop.py`, so it leaves with that file.

**"Archive" for the four A/B mode specs means** `git mv` into
`mode_specs/archive/`, not deletion: their leaderboards
(`leaderboard_ab_*.tsv`) stay in place and readable, and the archive directory
is excluded from the registry's spec glob. Nothing that can reproduce a past
row is destroyed.

**Non-goals:** no change to metric definitions, harvest extractors, geom
rendering, the mode-spec schema, the leaderboard schema, or grid submission via
prodtools. No orchestrator migration. No `EXAMPLES.md` regeneration or other
prodtools-repo changes.

## 5. Staging

Five commits on a branch off `json-modes`, suite green after each, each
independently revertible. Claude does not push; the operator pushes.

**Step 0 (blocker) — DONE 2026-08-19** (`8aa867b`, `7d51236`).

`[a]` and `[b]` are green; the suite is 620. `[a]`'s `MISMATCH` with
`current=None` for all 11 modes was never a data regression — the harness had
stopped seeing its input. `_roundtrip_mode` read `mode.leaderboard`, which the
archive/live split redefined as the operator's live board on `$DATA_ROOT`; that
tree is empty, so it returned `None` for every mode. Pointing the round-trip at
the archive reproduced 10 of 11 baselines byte-identically, which is what makes
the diagnosis exact rather than plausible. The 11th (`foilspfbpz`, 173 → 374
rows) was a second, independent staleness the first bug had masked. Both boards
are now pinned under separate `archive`/`live` keys, and `section_a()` raises
when it can pin zero files — the silence was the real defect.

`[c]` had decayed against four migrations (BO_WORK relocation without a data
move; the archive/live pair in its tmp sandbox; the JSON-mode migration
retiring geometry parsers so `x` is only recoverable from the pending TSV; and
a replay-config selector that drifted as history grew). All four are fixed and
its **evaluate half is byte-identical to the 2026-07-19 baseline**.

**`[c]` remains MISMATCH on one point, deliberately not re-captured** — see
§7.1. It is a real finding, not harness drift, and it does **not** block the
orchestration work: `[a]` and `[b]` cover the leaderboard reader/writer and the
row → tensor assembly, which are what this refactor can actually break.

### 7.1 Open: foilsflash preflight now fails a baseline overlap

Replaying `foilsflash18R05_00` — same config, same geom file — now FAILs
preflight where the 2026-07-19 baseline PASSed:

```
surface-check total_hits=1 unique_volumes=1 baseline=1 managed=0
VirtualDetector_EMC_0_Front:119 (G4Tubs) overlaps
StoppingTargetMother:0 (G4Tubs) by 24.8844 cm
```

Classified `baseline=1 managed=0`: the overlap is in the stock geometry, not
produced by the BO knobs — yet the zero-overlap policy counts it. Ruled out:
neither `foilsflash` nor `foilspf` still carries the TT_MidInner→DS2Vacuum
override (named in `foilspf.json` as what "held the last EMC_0_Front overlap"),
and both are on the same `Offline_run1bap_partial` musing.

Needs operator triage. Re-capturing would assert that foilsflash preflight is
*expected* to fail, which is a claim nobody has verified. Note `foilsflash` is a
superseded line, so the operational impact is low — but if the same baseline
overlap reaches the foilspf family it would fail every preflight, which is why
it is recorded rather than dropped.

1. **Pin `recursion_limit` explicitly** in both `.stream()` calls. One line.
   Valuable independently: langgraph 1.2.9 (ours) has no practical cap
   (verified to 200 supersteps), but langgraph 0.2.50 — the version in the
   `ana_v2.8.0` pyenv candidate — defaults to 25, and the parent burns 6 per
   round, so a `--max-rounds 5` campaign would die at round ~4 with
   `GraphRecursionError`. The 617-test suite does not catch this because no
   test runs five parent rounds.
2. **Delete mock mode** — `node_mock_grid`, its routing branch, `--mock` /
   `--no-mock`.
3. **Parent → pool loop.** Atomic: drop the checkpointer, replace the barrier
   with `as_completed`, delete `child_tracker.py`. These cannot be separated —
   the barrier is the checkpointer's only consumer, so dropping the checkpointer
   first would leave the barrier polling something that no longer exists.
4. **Plumbing** — `pipeline_io` in-process, `presniff.py` deleted,
   `graph/config.py` folded into `core/paths.py`.
5. **Archive the four A/B mode specs.**
6. **Delete `core/pipeline.py`'s `STAGES` literal** (§5.1). Must come after
   step 4, because `STAGE_TARGETS` currently lives in `graph/config.py` and
   needs a new home once that file is folded away.

### 5.1 Retiring the `STAGES` literal

`STAGES` (`core/pipeline.py:209`) holds five stages × four fields. The fields
have four different stories, and only one of them is a real gap:

| Field | Status today |
|---|---|
| `njobs` | Already mode-driven — `STAGE_TARGETS[stage]`, overridden by the mode spec's `run.jobs_per_stage` (foilspf: 15 / 15 / 100) |
| `events_per_job` | A default the mode spec overrides via `run.stage_tuning.<stage>.events_per_job` (foilspf: 200000 / 75000 / 110000) |
| `desc_fmt` | Hardcoded. **Zero** overrides across all 11 mode specs |
| `output_glob` | Hardcoded. **Zero** overrides across all 11 mode specs |
| `merge_factor` | Hardcoded (concat only) |

`desc_fmt` and `output_glob` should *not* become mode-driven. They are
properties of the **stage**: `sim.*.TargetStops.*.art` is what mubeam emits
regardless of the geometry fed to it. The Task-14 migration moved everything
mode-*varying* into `stage_entries/<stage>.json`; what remains in `STAGES` is
the residue that does not vary. The defect is not "insufficiently generic" —
it is that stage-level data sits in a module-level Python global instead of the
per-stage file that already exists beside it.

**There is an active shadowing hazard.** `stage_entries/<stage>.json` already
carries an `events` key holding the *same values* as
`STAGES[…]["events_per_job"]` — mubeam 5000, mustops_ce 2500, elebeam_flash
2500, run1b_mubeam 5000. `core/pipeline.py:1062` resolves them as
`events=cfg.get("events_per_job", entry_tmpl.get("events"))`, so `STAGES` wins
and the JSON never fires. The two files agree today by coincidence; editing the
JSON is a **silent no-op**. That is the same failure shape as the outloc bug
(`load_stage_entry` precedence) and as
`wiki/incidents/events-per-job-mid-flight-edit.md`.

**The change:** delete `STAGES`. Move `desc_fmt`, `output_glob`, `merge_factor`,
and the `njobs` defaults from `STAGE_TARGETS` into `stage_entries/<stage>.json`;
drop `events_per_job` entirely, since `events` is already there. One precedence
rule, one direction, no shadowing:

> mode spec (`run.jobs_per_stage`, `run.stage_tuning`) **overrides**
> `stage_entries/<stage>.json` (the default). Nothing overrides the mode spec.

The load-bearing tuning rationale currently in `STAGES` comments — especially
the mustops_ce `events_per_job` history (the 2026-05-21 revert that halved
statistics and moved σ(sob) 0.10 → 0.14) — must travel into the stage entry's
existing `_comment` key. It is measured knowledge, not decoration.

**Why this is step 6 and not part of ExtractAna's approach.** The `ExtractAna`
branch (`3e3e277`, michaelmackenzie) adds a `run.stage_defs` block carrying
exactly `desc_fmt` and `output_glob` — but to the **mode** spec. Measured, all
11 blocks are byte-identical (sha `4b82462f`). That duplication is not
sloppiness and does not need an `$inherit` mechanism: it is the unavoidable cost
of putting stage-level data in a mode-level file, paid once per mode, forever.
Landing these fields in `stage_entries/` instead yields exactly one copy, needs
no inheritance machinery, and cannot produce that branch's `KeyError: 'concat'`
— the stage entry files for `concat` and `run1b_mubeam` already exist.

**Acceptance for step 6:** for each of the 11 modes × 5 stages, the rendered
prodtools entry must be byte-identical before and after. This is pure data
relocation; any diff is a bug.

## 6. Testing

The ~1,470 LOC of deleted tests are replaced by six fast tests against the pool
loop, using a fake `run_child` returning canned outcomes — no grid, no sqlite,
no subprocess:

1. in-flight count never exceeds `q`
2. one resolution frees exactly one slot and triggers exactly one new pick
3. the loop drains `inflight` before exiting (orphan-children fix, asserted)
4. `x_pending` handed to the picker equals the in-flight set
5. `no_row_streak` increments on a rowless child and resets on a row
   (false-increment fix, asserted)
6. `STOP_FLAG` halts top-up but still drains

Global constraints unchanged: `unittest`, not pytest; the suite must stay green
with **zero grid contact** (no `mu2ejobsub`, no `jobsub_q`); run as
`PYTHONPATH= .venv/bin/python -m unittest discover -s tests -t .`.

## 7. Acceptance

**Offline gates:** full suite green, and golden parity `[a]`, `[b]`, `[c]` green
after the Step 0 repair.

**Live gate — controlled A/B, requires explicit operator approval at the point
of launch.** This design's approval does not authorize submission.

- Take an `x_point` already present in `leaderboard_bo_foilspfbpz.tsv`. Run it
  through `graph.run --x-point` on old code and on new code.
- **Rendered geom file must be bit-identical.** Deterministic, so this is a hard
  equality check covering the whole propose → render path.
- **Metrics compared within measured noise**, not bit-identical: re-running the
  same geometry resamples. Use σ(sob)=0.6% from
  `wiki/concepts/bo-noise-budget.md`.
- Then one small rolling campaign (`q=4`, `max_evals=8`) solely to exercise
  replenish-and-drain, which a single eval cannot reach.

Total live cost: 9 evaluations.

## 8. Risks and what is lost

- **A parent killed mid-round loses that round's bookkeeping.** Per-stage
  `cluster.txt` idempotency means a relaunch re-attaches to already-submitted
  grid clusters rather than resubmitting, so the cost is bookkeeping, not
  compute. This is a real regression from the nominal capability, though not
  from observed behavior (0/51).
- **No declarative parent graph to read.** The round loop becomes a function
  read top to bottom.
- **`ThreadPoolExecutor` threads block on `subprocess`.** Cheap (no GIL
  contention while waiting), but a parent-process kill still takes the pool
  with it — unchanged from today, and the subject of
  `wiki/incidents/closed-loop-parent-signal-kill-midlaunch.md`.
- **`hybrid`/`qnehvi` picker nondeterminism is untouched** and will make any
  picker-output A/B noisy. Use `budget_sob`, the only reproducible picker, for
  comparisons — see
  `wiki/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md`.

## 9. Cross-links

- `wiki/concepts/orchestrator-evaluation-2026-05.md` — the decision this
  revisits, including its own "re-evaluate at end of Phase 2" trigger
- `wiki/concepts/closed-loop-bo-design.md` — load-bearing constraints of the
  code being replaced
- `wiki/concepts/architecture-friction-survey-2026-07.md` — prior identification
  of the 5-barrier-truth-sources problem
- `wiki/concepts/mode-registry-childtracker-design.md` — designed the
  `ChildTracker` this removes
- `wiki/incidents/events-per-job-mid-flight-edit.md` — the shadowing hazard in
  §5.1 is the same failure shape
- `docs/pyenv-publication-plan.md` — unaffected; see §2 cost note
- `Mu2e/Mu2eBO` branch `ExtractAna` (`3e3e277`) — independent attempt at the
  §5.1 problem, placing the same fields at mode level; see §5.1 for why
  `stage_entries/` is the better home
- Source: `graph/closed_loop.py`, `graph/build.py`, `graph/nodes.py`,
  `graph/child_tracker.py`, `graph/pipeline_io.py`, `core/pipeline.py:209`
  (`STAGES`), `core/pipeline.py:1062` (the shadowing resolution),
  `graph/config.py:86` (`STAGE_TARGETS`)
