# Architecture review — deepening opportunities (2026-08-08)

Produced by `/improve-codebase-architecture` on branch `json-modes`. Two
exploration passes (one over `core/`, one over `graph/`), findings merged and
ranked by real friction — incident history, live damage, and test cost — not
theory. Vocabulary: *module / interface / depth / shallow / seam / adapter /
leverage / locality* per the skill glossary; domain terms per `CONTEXT.md`.

**Revision (same day):** every factual claim was re-verified by two
adversarial passes against the code. All region boundaries, patch counts, and
incident narratives held; five substantive corrections were applied inline
(candidate #1's live-damage framing, #2's seam decomposition, #3's solution
shape, #4's `max_rounds` claim, #5/#6 counts), and the *Interactions*,
*Quick wins*, and stale-pending-hazard content is new.

Settled ADRs were not re-litigated: ADR-0001 (cl_min picker retired),
ADR-0002 (ModeSpec registry in stdlib-only `core/modes.py`).

Operational note at review time: **foilspfbpz01 was mid-flight** — anything
touching `closed_loop.py` / `pipeline.py` should be designed but not landed
while children are running.

---

## 1. The Leaderboard is a pair of format/parse functions, not a module — nothing owns the row schema as an invariant

**Files:** `core/bo_driver.py:203-301` (`format_row`, `load_history_row`,
`load_history`, `append_history`, `load_pending`), `core/modes.py:107-109`,
`core/mode_json.py:371-401`, `leaderboards/*.tsv`

**Problem:** The row schema is knowledge in four places: the ModeSpec declares
it, `format_row` writes it, `load_history_row` re-derives it, and the physical
TSV header is a fourth opinion nobody ever reconciles. `append_history:280`
writes the header only when the file does not exist; `load_history:274` and
`load_pending:300` swallow `KeyError/ValueError` (pending also
`JSONDecodeError`) silently. That mechanism produced a real incident on an
**active** campaign the day before this review:
`touched-leaderboard-headerless-history-loss` (foilspfbw01 — GP silently
cold-started every round, abort streak counted successful children).

Corroborating fossil damage (verified, but **inert**): five dormant/dead
pending files (`foilsf`, `foils`, `helical`, `prodtarget`, `prodtarget6d`)
have their first data row(s) fused onto the header line — 35 rows total
swallowed into mega-headers — from a `remove_pending` rewrite bug since fixed
at `bo_driver.py:343`. Subsequent rows still parse positionally, all active
JSON modes' pending files are clean, and `pending_bo_foilspfbpz.tsv` is
load-bearing right now (header + live rows). So the urgency is not "corrupted
today"; it is that **nothing in the system can notice** either corruption
class — no reader ever compares a file's header to the ModeSpec.

**Separate latent hazard found during verification:** pending rows are never
garbage-collected. The dormant files carry 23–95 stale June-era pending rows
each (`foils` 88, `prodtarget6d` 95, `foilsf` 55, `foilsg` 39, `prodtarget`
23). Reviving any of those modes would hand `botorch_ask` up to ~90 phantom
`X_pending` points to repel from — a silent optimizer distortion, worse than
the header fusion.

**Solution:** Make the Leaderboard a deep module that owns the header as an
invariant — on open it reads the header, compares it to the ModeSpec, and
refuses or migrates loudly; append/load/pending (and pending expiry) go
through it; the silent `except: continue` guards go away.

**Benefits:** Locality — every "rows silently vanished" incident class dies in
one place. Tests can assert against a real file's first line instead of
round-tripping in memory. Leverage — pickers, closed loop, and
`x_for_evaluate` all get the same guarantee for free; and this module is the
natural **history seam** candidate #2's third leg needs.

## 2. Finish the ChildTracker deepening — but it's three seams, not one

**Files:** `graph/closed_loop.py:178-230, 397, 405, 429-440, 552, 659-707`,
`graph/child_tracker.py`, `tests/test_closed_loop.py`

**Problem:** The Barrier is the *only* consumer of the ChildTracker seam
(`_DiskSignals` constructed inline at `:552`). The other raw-signal reads
split into two genuinely different kinds:

- **Per-child Resolution questions asked raw:** `node_assign_names:397,405`
  (`_leaderboard_names`, `_child_is_broken`) and
  `node_launch_children._already_running:430-433` (cluster glob + leaderboard
  + broken) are literally asking "has this named child already resolved?" —
  the predicate Resolution encodes. `_DiskSignals.has_cluster:202` is a
  **verbatim duplicate** of the `:431` glob — same probe, two owners. The
  "rolling zombie" fix (`a9387b7`) bolted a fourth predicate
  (`n not in completed`) onto this filter instead of asking the tracker; same
  shape as the stale-cluster incident one node earlier.
- **A Resolution question dressed as a leaderboard read:**
  `node_decide_next:680`'s streak logic (`rowless = [n for n in
  newly_resolved if n not in lb_names]`) recomputes exactly the
  `DONE_ROW`-vs-otherwise distinction the tracker already derived at the
  barrier and threw away (barrier returns only `sorted(completed)` at
  `:632`).
- **Campaign-history questions that do NOT belong to ChildTracker:**
  `node_predict_picks:347,365,385` and `node_decide_next:659` read
  `_leaderboard_len` to snapshot history depth. ChildTracker is per-round and
  per-child; forcing these through it would be the reverse category error.
  Their seam is the Leaderboard module (candidate #1).

Testability cost of the inline adapter: barrier tests patch 7–8 module names
each (`_open_saver_conn`, `SqliteSaver`, `graph.build.build_graph`,
`graph.build.is_child_terminal`, `_leaderboard_names`, `_child_is_broken`,
`_stop_requested`, `GRID_DATA_ROOT`); **124 `mock.patch` calls in
`test_closed_loop.py` vs 1 in `test_child_tracker.py`** (which injects a
fake). `_DiskSignals`'s docstring (`:178-182`) admits the late-binding exists
so patches keep intercepting.

**Solution:** Three moves. (a) Route assign/launch child-state questions
through the ChildTracker/Signals seam. (b) Widen the barrier's return to carry
per-child Resolutions so `decide_next`'s streak accounting consumes tracker
output — this also deletes a full TSV re-read per wave and the
`prev_completed_names` bookkeeping. (c) Give the history-depth reads a
Leaderboard seam (candidate #1), not a ChildTracker one. The barrier receives
its Signals adapter and child-graph from its builder instead of constructing
them.

**Benefits:** Locality — Resolution has one producer, so the next
zombie/stale-cluster variant is impossible to write. The barrier becomes
testable through the seam that already exists; most of the 124 patches become
injected fakes.

## 3. Preflight is a 420-line untested region of the driver, and it is the sole reason the driver imports `graph/`

**Files:** `core/bo_driver.py:1471-1890` (`_cmd_preflight_impl` alone is
`:1641-1874`, 234 lines), `core/bo_driver.py:95-99`

**Problem:** The verdict ladder (past_init `:1725-1731` → fatal gate
`:1740-1745` → overlap classifier `:1816-1857` → geom-fail regex `:1859-1864`
→ `timed_out or rc == 0 or past_init → PASS` at `:1866-1874`) has **zero
tests** — both preflight incidents (`preflight-past-init-false-pass`, the
zero-overlap branch-order bug) lived in branch ordering no test executes;
existing tests assert the regexes, then mock the classifier out
(`test_seam_protocol.py:30,43,251` — the only test references are
`mock.patch` targets). Verified: **all three** of the driver's `graph/`
imports (`SETUPMU2E:1690`, `run_sourced_bash:1714`, `PREFLIGHT_TIMEOUT_S:1715`)
are used exclusively inside `_cmd_preflight_impl` — extracting preflight
removes the `graph/` sys.path hack from `bo_driver.py` entirely. Today the
picker subprocess (`botorch_predict.py:28` → `bo_driver` → `graph/config.py`)
mkdirs a checkpoint dir (`config.py:28`) and freezes `AUTORESEARCH_MODE`
(`:48-50`) at import, just to fit a GP.

**Solution (revised after verification):** Extract Preflight into its own
module split at the impurity line the code already has: the runner
(`:1642-1723` — mkdtemp, render, `run_sourced_bash`, capture) plus the two
GDML-preserve side effects hoisted out of the classifier (`:1764-1791`,
`:1797-1808`), feeding a pure `verdict(evidence) -> rc` over an evidence
struct `(out, rc, timed_out, geom_text, parsed_gdml, spec)` — ~110 of the 234
lines become the pure core. A literal `verdict(log_text, spec)` is not
achievable: three of the six FAIL gates read the geom/GDML artifacts.

**Benefits:** The interface becomes the test surface: every incident's
branch-order bug becomes a table-driven test with no Musing needed. Deleting
the preflight-only imports cuts the `core → graph` import edge for the picker
path outright.

## 4. `--rolling` is a second Campaign machine wearing the first one's state schema

**Files:** `graph/closed_loop.py:136-145, 331-366, 554-555, 597-605, 662-707,
747-756, 835-843, 872-875`

**Problem:** One boolean redefines the state schema: `q` (batch → pool
width, `:339-340`), `round_idx` (Round → wave, but `node_assign_names` is
rolling-blind so each wave burns an `R{NN}` name segment), and `children`
(cleared per Round at `:732-733` vs never cleared under rolling, `:706` —
so `launched_this_round:491` is a lie that accumulates every child ever
launched, inflating the "all N children resolved" log monotonically).
`max_rounds` is **worse than ignored** (the original claim here was wrong):
`route_after_decide:747-756` never checks it, and the `--rolling` help text
(`:840`) says it's ignored — but `main():873` sets
`max_evals = q × max_rounds` when `--max-evals` is absent, so the "ignored"
flag silently defines the whole campaign budget. Verified rolling footprint:
**~128 lines (14% of the file) across 7 blocks**, 4 top-level
`state.get("rolling")` guards plus 3 nested; log prefixes fork (`[r{n}]` vs
`[w{n}]`). Two incidents already (`rolling-no-row-streak-false-increment`,
the `a9387b7` zombie). Rolling is newer than ChildTracker and was added
*around* it rather than through it.

**Solution:** Give the wave/pool concept its own home — rolling and
per-Round-barrier become two campaign shapes behind one interface, instead of
`if rolling:` forks inside four of six nodes.

**Benefits:** Locality — wave accounting (streaks, replenishment, pool
membership, budget) concentrates where the next incident would otherwise
land. Rolling logic becomes testable without patching Round machinery.

## 5. The system's runtime config is an env-var that must beat an import — across two process boundaries

**Files:** `graph/config.py:24-119`, `graph/presniff.py` (all 35 lines),
`core/pipeline.py:70-83`, `graph/closed_loop.py:458-475`,
`graph/pipeline_io.py:192`

**Problem:** `config.py` freezes ModeSpec-derived facts at import time from
`AUTORESEARCH_MODE` (`:48-50`), so "stamp the env var before importing config"
is an interface invariant restated in four files — `presniff.py` exists solely
to satisfy it, and hides a *policy* decision (`--picker qlnei` ⇒ set
`AUTORESEARCH_NO_RUN1B`, `:30-34`) as an env side effect read 40 lines deep in
another module. Layering is inverted: `core/pipeline.py:70-83` imports
`GRID_DATA_ROOT, GRID_STAGES, MUSING, SETUPMU2E, STAGE_TARGETS, CONCATLESS`
from `graph/config.py`. Verified sharpenings: the parent that stamps the env
**never reads the derived values** (`closed_loop.py` consumes neither
`GRID_STAGES` nor `STAGE_TARGETS`); there are **two** subprocess hops, not one
(`closed_loop → graph.run` at `:458-466`, six argv flags including
`--thread-id`; `pipeline_io → pipeline.py` at `:192`), both inheriting the
full env with no `env=` kwarg; `graph/run.py` calls only `presniff_mode`, so
`AUTORESEARCH_NO_RUN1B` has **no argv path at all** — it crosses only by
inheritance, along with `AUTORESEARCH_ELEBEAM_NJOBS`, `AUTORESEARCH_BOTORCH_VENV`,
`AUTORESEARCH_CHECKPOINT_DIR`. **Zero tests** mention `env`/`environ`/
`AUTORESEARCH` in `test_closed_loop.py`; the Popen stubs capture argv only.
Consequence for tests: `build.STAGE_NODES` and `pipeline.STAGES` freeze at
import, so the suite can only ever exercise the default Stage chain
in-process.

**Solution (revised after verification):** Two steps of different cost.
(a) In-process and cheap: make `build_graph(stages=...)` and `pipeline.STAGES`
functions of an explicit StageChain value instead of import-frozen globals —
this alone makes per-Mode graph topology testable. (b) Across the two process
hops, keep a serialized carrier but make it **one** explicit
`--stage-chain`-style argument instead of four invisible env vars, so the
parent→child contract is greppable and testable. Pretending the process
boundary away is not on the table.

**Benefits:** Kills the four-way restated invariant and the backwards import;
converts an unwritten env contract into a checkable argv one.

## 6. The per-Eval state directory is a protocol with no owning module

**Files:** `*_cluster.txt` at **14 sites across 4 files**
(`core/pipeline.py`, `graph/closed_loop.py`, `graph/pipeline_io.py`, and
`graph/child_tracker.py` itself); `broken.txt` written at
`graph/pipeline_io.py:389`, read at `graph/closed_loop.py:206`; the geom
convention at **5 code sites + 1 docstring**

**Problem:** `broken.txt` — the `done_broken` Resolution's carrier — has its
producer and consumer in different packages with the literal duplicated and no
shared accessor (verified: exactly those two code sites repo-wide). The
"this Eval's geometry is materialized where the grid looks" invariant is known
at `bo_driver.py:1381-1386` (`cmd_propose`), `pipeline_io.py:83-88`
(`propose_one`, whose comment still points at "bo_driver.py:567-570" — ~815
lines stale), `pipeline.py:131` (`_bind_config`), `pipeline.py:524-529`
(submit refuses if absent), and `pipeline.py:356` — where
`_parse_n_plates_from_geom` **silently returns 0** if the geom file is
missing instead of raising, a fail-open twin of the submit check. Most
stale-state incidents in the wiki catalog are disagreements about what these
files mean. `core/harvest.py`'s three accessors (`read_outputs`,
`stamped_stage_chain`, `events_per_job`) prove the accessor shape works.

**Solution:** One module owns the per-Eval directory: its names, lifecycle,
and accessors.

**Benefits:** Locality for the largest incident class in the catalog; fakes
for Child-state tests come from faking one module instead of a filesystem.

## 7. The BOMode interface is sized for five dormant adapters the live path doesn't use

**Files:** `core/bo_driver.py:141-344` (interface), `:351-1142` (five
Python-mode adapters — `FoilsMode:351`, `FoilsFracMode:566`,
`FoilsGroupMode:638`, `ProdTargetMode:779`, `ProdTarget6DMode:1041` — 790
lines, 41% of the file; leaderboard last-appends Jun 11–29), `:1143-1243`
(`JsonMode`, 101 lines, backs all 11 active modes)

**Problem:** The live adapter fills `load_priors` with `[]` and `parse_geom`
with `raise` — and that raise forced a *second* x-recovery seam
(`x_for_evaluate:165-180`) whose absence once cost a full campaign (docstring
records it: every JSON-mode child died at evaluate after a ~4.5 h grid run;
zero rows). Every August-touched leaderboard is a JSON mode. Verified
coupling: `harvest-pot-only` is used **only** by `prodtarget`/`prodtarget6d`
(all 11 JSON specs declare `"harvest": "harvest"`), so archiving the Python
modes also retires `cmd_harvest_pot_only`'s untyped 13-key summary dict, the
`PYTHON_MODE_LEADERBOARDS` block in `mode_json.py:65-76`, and the
`format_row`/`load_history_row` override hooks — shrinking candidates #1 and
the mode_json observation below as a side effect.

**Solution:** Decide archive vs product for the Python modes; if archive, the
interface shrinks to what JSON modes need and "where does x come from" has a
single answer.

**Benefits:** Leverage — a 3-method interface instead of 9; ~40% of the driver
file stops demanding maintenance. **Note:** partly a product decision —
`simplification-audit-2026-07` protects foilsg/prodtarget as the botorch-0.18
venue, so this needs an operator call, not just a refactor.

---

## Interactions & suggested sequencing

The candidates are not independent; the cheap enablers come first.

1. **Decide #7 first** (operator decision, no code risk): an archive verdict
   deletes surface area that #1, #3, and the mode_json observation would
   otherwise have to design around.
2. **#1 Leaderboard module** — also supplies the history seam that #2(c)
   needs.
3. **#3 Preflight extraction** — removes the driver's `graph/` imports
   entirely, cleaning the picker import chain and shrinking #5's cycle.
4. **#2 ChildTracker completion** (three seams as revised) — consumes #1;
   pairs naturally with **#6** (the state-dir module is the substrate the
   Signals adapter reads).
5. **#4 Rolling shape** — touches `closed_loop.py` broadly; schedule for a
   window with no Campaign in flight.
6. **#5 Config/env** — biggest lift (two process boundaries); do last, after
   #3 has already removed the worst import edge.

## Quick wins (small, safe, independent of the refactors)

- Fix the stale comment `graph/pipeline_io.py:83-85` → `bo_driver.py:1381-1386`.
- Fix the `--rolling` help text (`closed_loop.py:840`): `--max-rounds` is not
  ignored — it silently sets `max_evals = q × max_rounds` when `--max-evals`
  is absent. Say so, or require `--max-evals` under `--rolling`.
- Rename/fix `launched_this_round` (`closed_loop.py:491`) — under rolling it
  accumulates every child ever launched.
- Make `_parse_n_plates_from_geom` (`pipeline.py:356`) fail loudly instead of
  returning 0 on a missing geom file.
- Add one test asserting the parent→child env contract (the four
  `AUTORESEARCH_*` vars) — currently zero coverage of the only path they
  cross.
- Operator call: expire or truncate the June-era stale pending rows in the
  dormant modes' pending files (23–95 rows each) so a revival doesn't feed
  `botorch_ask` phantom `X_pending` points.

## Lower-priority observations

- `graph/nodes.py` + `graph/pipeline_io.py` are one module split by transport
  (in-process vs subprocess) rather than by concept — both have exactly one
  production caller. The genuinely deep piece, the worker-log scanner
  (`pipeline_io.py:275-401`: `_SCAN_PATTERNS`, `scan_worker_logs`,
  `broken.txt` policy), has no name of its own and is buried in the thin half.
- `EvalSummary` covers only one of the two harvest verbs: `cmd_harvest_pot_only`
  (`core/pipeline.py:1188-1267`) still writes a hand-built 13-key dict that
  `ProdTargetMode` reads back by string. `cmd_harvest` (`:1278-1433`, ending
  in the 24-kwarg `EvalSummary` construction) and `cmd_harvest_pot_only` both
  have 0 tests — the tested pure pieces in `harvest.py` mostly have 1 caller
  each, so the module is a testability seam whose decisions stayed on the
  untested side. (Coupled to #7: archiving the Python modes retires the
  untyped verb.)
- The `if __package__:` bare-vs-qualified import dance appears at ~12 sites
  (`modes.py`, `mode_json.py` ×3, `botorch_predict.py`, `graph/config.py`,
  `graph/pipeline_io.py`, `graph/closed_loop.py`, every test file) with ~45
  lines of explanatory comment; `mode_json.py` also imports two private names
  from `geom_template` and restates four other modules' implementation facts
  as validation rules (`PYTHON_MODE_LEADERBOARDS`, the `row["sob"]` rule, the
  `pot_only` tarball rule).
