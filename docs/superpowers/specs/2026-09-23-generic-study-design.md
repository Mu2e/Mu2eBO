# Generic studies: any problem behind MCP, defined as data — design

Date: 2026-09-23. Status: draft for review.

Related:
[`2026-09-23-mcp-framework-plan.md`](2026-09-23-mcp-framework-plan.md) (the MCP
framework plan),
[`2026-09-23-mcp-framework-plan-review.md`](2026-09-23-mcp-framework-plan-review.md)
(the review whose roadmap step 6 this design replaces),
[`2026-09-22-kit-seam-design.md`](2026-09-22-kit-seam-design.md) (spec 1: the kit
client and the verified prodtools facts).

## Goal

The goal comes from the operator (2026-09-23): make the codebase generic, so that
autoresearch can study arbitrary problems.

**The rule: a new study is a data file.** Nothing in autoresearch is edited.
- Domain logic lives in MCP kits, or in named plugins kept outside the core.
- autoresearch itself holds only the generic parts: the loop, the surrogate glue, the leaderboard, the evaluation graph and the kit client.

## Decisions

All decided by the operator on 2026-09-23.

| Question | Decision |
|---|---|
| How arbitrary? | Anything whose evaluation sits behind MCP tools: Mu2e Offline and G4beamline chains, other experiments' servers, toy functions. |
| Objectives and constraints | N objectives, each maximized or minimized, with an optional log10 transform, and at most one constraint in this version. surrokit already supports this, so it needs no change. |
| Who writes studies | People, as JSON files in git or in their own study directory. No `define_study` MCP tool yet. |
| Approach | A standard **evaluator contract** (`submit` / `status` / `results`) plus one **adapter** per existing kit family. |
| Today's foilspf chain | **No legacy engine.** foilspf is the first real study on the new engine. |
| Grid-job recoveries | **None.** A step is complete when all its jobs have finished. Results use successful jobs only, and a `quorum` decides pass or fail. |
| prodtools access | **MCP only.** First fix prodtools P1 and P2 in the operator's prodtools repo. Users install prodtools from a clone, as `mcp/README.md` documents today. |

**Two defaults I set, which the operator can overrule:**
- Knobs are `real` or `int`. Categorical knobs come later.
- Adapters start as in-process Python classes. They are wrapped as MCP servers only if another harness asks for them.

## Where each kind of change goes

| Change | Where |
|---|---|
| A new study | one JSON file |
| A new stage on an existing kit | one stage template, as JSON |
| A new kit that speaks the contract | one entry in `kits.toml` |
| An existing kit family | one adapter, written once |
| A physics quantity nobody computes yet | a metric plugin, or an anakit analysis |
| Geometry that Offline parameters can't express | an Offline C++ patch and a build; the study names the build |
| A new workflow shape (branches, multi-fidelity) or new surrogate features | autoresearch or surrokit code; each is a new feature, out of scope here |

## Architecture

```
 study JSON --load+validate--> Study --> campaign runner (graph/closed_loop.py, unchanged)
                                 |            | picks: build_problem(Study) -> surrokit
                                 |            v one child per point
                                 |       graph.run --study S --config C --x ...
                                 |            |
                                 |   derive -> render geom -> preflight -> steps (DAG) -> score -> row
                                 |                                  |
                                 |              contract: submit / status / results
                                 |        +-----------+-------------+-------------+-----------+
                                 |        v           v             v             v           v
                                 |     toykit    prodtools      beamkit        anakit     metric plugins
                                 |   (native)    adapter        adapter        adapter    (local, e.g.
                                 |                  | MCP          | MCP          | MCP     ce_sensitivity)
                                 |               prodtools      beamkit        anakit
                                 v
                   leaderboard (columns from the Study), MCP server (list_problems from Studies)
```

| # | Component | Job |
|---|---|---|
| 1 | `core/study.py`, the study loader | Loads schema-2 JSON from `mode_specs/` and `$AUTORESEARCH_STUDY_PATH`, validates it and returns a `Study`. |
| 2 | Leaderboard | Columns come from the Study. Old boards are read by header. A board with no header is refused. Writes are idempotent by name. |
| 3 | Surrogate glue, `build_problem(study)` | Builds the surrokit `Problem`: transforms, noise and the constraint. |
| 4 | Campaign runner | Today's work pool. It takes `--study`. |
| 5 | Per-point graph | Built from the Study's steps. |
| 6 | Contract engine and kit client | Runs the steps through adapters or native kits. |
| 7 | Adapters and plugins | A registry keyed by kit name. |
| 8 | MCP server | Studies become problems. `list_problems` gains knob names and units, and objective names and directions. |

## The study file (schema 2)

```json
{
  "schema": 2,
  "name": "foilspfbpz",
  "note": "one-line purpose",

  "knobs": [
    {"name": "rOut_0", "type": "real", "min": 30, "max": 150, "unit": "mm", "fmt": "{:.4f}"}
  ],

  "derive": {
    "consts":   {"n_foils": 49, "extent": 1066.666667},
    "exprs":    {"deltaZ": "extent / 48", "halfext": "extent / 2"},
    "profiles": {
      "rOut_p": {"kind": "lagrange", "count": "n_foils",
                 "control": ["rOut_0", "rOut_1", "rOut_2"], "clip": [30, 150]}
    }
  },

  "geom": {"writer": "offline_simpleconfig",
           "base": "Offline/Mu2eG4/geom/geom_run1_a.txt",
           "lines": ["…today's foilspfbpz geom lines, unchanged…"]},

  "kits": {
    "prodtools": {"code_tarball": "${ARTIFACT}/autoresearch_muse/Code_run1bap_holeradii_ipafix.tar.bz2",
                  "fatal_log_codes": ["GeomSolids1001"]},
    "offline_preflight": {"musing": "${ARTIFACT}/Offline_run1bap_partial/setup_local.sh",
                          "require_zero_overlaps": true}
  },

  "preflight": {"kit": "offline_preflight", "params": {}, "files": ["geom"]},

  "evaluate": [
    {"step": "mubeam", "kit": "prodtools", "entry": "mubeam",
     "files": ["geom"], "files_from": [], "params": {},
     "fixed": {"njobs": 15, "events_per_job": 200000, "memory_mb": 2000, "quorum": 0.8}},
    {"step": "elebeam_flash", "kit": "prodtools", "entry": "elebeam_flash",
     "files": ["geom"], "files_from": [], "params": {},
     "fixed": {"njobs": 100, "events_per_job": 110000, "memory_mb": 2000, "quorum": 0.8}},
    {"step": "mustops_ce", "kit": "prodtools", "entry": "mustops_ce",
     "files": ["geom"], "files_from": ["mubeam"], "params": {},
     "fixed": {"njobs": 15, "events_per_job": 75000, "memory_mb": 2000, "quorum": 0.8}},
    {"step": "sob", "kit": "ce_sensitivity", "entry": null,
     "files": [], "files_from": ["mubeam", "mustops_ce"], "params": {}, "fixed": {}},
    {"step": "flash", "kit": "flash_edep_per_pot", "entry": null,
     "files": [], "files_from": ["elebeam_flash"], "params": {}, "fixed": {}}
  ],

  "objectives": [
    {"name": "sob",        "metric": "sob.s_over_sqrt_b",        "direction": "max",
     "transform": "none",  "noise": 0.006, "fmt": "{:.5f}"},
    {"name": "flash_edep", "metric": "flash.flash_edep_per_pot", "direction": "min",
     "transform": "log10", "noise": 0.01,  "fmt": "{:.5e}"}
  ],
  "constraints":   [{"name": "flash_edep", "max": 6.85443e-7, "k_sigma": 1.0}],
  "extra_metrics": [],
  "extra_columns": [{"name": "alpha", "expr": "100000",                  "fmt": "{:.3f}"},
                    {"name": "obj",   "expr": "sob - 100000 * flash_edep", "fmt": "{:.5f}"}],

  "leaderboard": {"file": "leaderboards/leaderboard_bo_foilspfbpz.tsv"}
}
```

### Field rules

**General:**
- **Every key is required and unknown keys are rejected** (ADR-0002). Empty is written explicitly as `null`, `{}` or `[]`. Validation happens at load, and every error names the file, the field and the rule.
- **`name`** matches the file stem.
- **`${VAR}` substitutes an environment variable** (for example `${ARTIFACT}`). An unset variable is an error at load.

**`knobs`:**
- names are unique; `type` is `real` or `int`; `min < max`;
- an `int` knob has integer bounds;
- `unit` may be `""`.

**`derive`** is lifted from today's `geom` block, and computes named values from the knobs.
- `consts` are numbers.
- `exprs` are expressions in the existing safe evaluator: arithmetic plus `min`, `max`, `abs` and `sqrt`.
- `profiles` expand K control points into `count` values. `kind` is required; only `lagrange` exists now, giving a polynomial of degree K−1, clipped to `clip`. Control points may be knob names or expressions.
- The math is today's `core/geom_template.py`, unchanged.

**`geom`** is `null`, or a `writer` plus the writer's own fields. Only `offline_simpleconfig` (today's writer) exists in this design. Steps that need the rendered file list `"geom"` in `files`.

**`kits`** holds per-study settings for each kit, keyed by kit name.
- They are merged under every step of that kit; a step's `fixed` wins over them.
- Each adapter declares which keys it accepts, and anything else is an error.
- A kit used by no step is an error.

**`preflight`** is `null`, or a `check` call to a kit: `{kit, params, files}`.

**`evaluate`** is a list of steps.
- **`step`:** a unique name.
- **`kit`:** a registered adapter, native kit or plugin.
- **`entry`:** a stage-template name, an inline template object, or `null`.
- **`files`:** names of rendered files, currently only `geom`.
- **`files_from`:** earlier steps whose output files feed this step. They must be step names, and the steps must form a graph with no cycles. A step with no `files_from` starts at once.
- **`params`:** maps the kit's parameter names to knob, expression or profile names. If an adapter declares scalar-only parameters, a profile is sent flattened as `name_0 … name_{N-1}`.
- **`fixed`:** constant settings for this step.

**`objectives`** holds at least one objective. The first is the primary, surrokit's axis 0.
- `metric` is `step.metric_name`.
- `direction` is `max` or `min`; `transform` is `none` or `log10`; `noise` is the absolute noise σ in the transformed space.
- A `log10` metric that is ≤ 0 at scoring makes the evaluation fail. It never produces a row.

**`constraints`** holds at most one entry in this version.
- It refers to an objective by `name` and sets exactly one of `max` or `min`, plus `k_sigma`.
- The bound goes through the same transform as the objective. For example, `max` 6.85e-7 on a `min`+`log10` objective becomes surrokit `Constraint(axis=1, min=-log10(6.85e-7))`.

**`extra_metrics`** are recorded in the row but not optimized, written as `{name, metric, fmt}`.

**`extra_columns`** are row columns computed at scoring by an expression over the objective and extra-metric names and `derive.consts`. They exist so that a converted study keeps its board's exact column layout. foilspf's boards end in `alpha` and `obj`, where `obj = sob − alpha·flash`. Nothing optimizes them.

**`fmt`** on objectives, extra metrics and extra columns is the number format in the TSV. It is required, so that rows appended to old boards match today's bytes.

**`leaderboard.file`** is the board path.

**Environment overrides are gone.** `AUTORESEARCH_FLASH_BUDGET` and `AUTORESEARCH_BUDGET_KSIGMA` are removed, and the study file is the only source of the constraint.

### Stage templates

`entry: "mustops_ce"` resolves to `stage_entries/mustops_ce.json`, searching the repo first and then `$AUTORESEARCH_STUDY_PATH`. `entry` can also hold an inline object in the same format.

Every value that is hard-coded per stage today moves into its template:
- `mustops_ce`'s `MaxEventsToSkip = 8000` (`core/pipeline.py:228`);
- the input-staging rule (`INPUT_STAGE`, `:517`), which becomes `files_from`;
- the stage list (`ALL_STAGES`, `:157`), which becomes the steps.

After this change, no stage name appears in Python.

### Leaderboard rows

```
name | each knob | each objective | each extra metric | handles | spec_sha | time
```

- `handles` records each step's handle.
- `spec_sha` is the SHA-256 of the canonical study JSON.

**Old boards** are read by their header names. The converted foilspf-family studies name their objectives after the existing columns (`sob`, `flash_edep`) and add `alpha` and `obj` as `extra_columns`. The file layout and number formats therefore don't change. New boards use the schema-2 layout.

**Pending files** (`pending/*.tsv`) drop the `alpha` column. The reader accepts both old and new pending files.

## The evaluator contract

Kits that speak the contract offer these as MCP tools; adapters and plugins implement the same functions in Python.

| Call | Input | Output | Rules |
|---|---|---|---|
| `submit` | `name`, `params` (the step's mapped `params` plus `kits` settings plus `fixed`), `files`, `inputs` | `{handle}` | **Idempotent by name:** the same name with the same params returns the existing handle, and with different params it is an error. |
| `status` | `handle` | `{state, message, poll_ms, progress}` | `state` is `working`, `completed`, `failed` or `cancelled`. `progress` is `{done, total, ok}` or `null`. |
| `results` | `handle` | `{metrics, files, metadata}` | Only when `completed`; otherwise an error. `metrics` is `{str: float}`. |
| `check` (optional) | as `submit` | `{ok, message}` | Used for preflight. |
| `describe` (optional) | none | `{params, metrics, accepts_lists}` | Used by the launch check. |
| `cancel` (optional) | `handle` | `{state}` | |

- A `FileRef` is `{name, uri, kind}`, where `uri` is `file://…` or `root://…`.
- **Handles are deterministic,** named `<config>.<step>`.

## One point, end to end

`graph.run --study S --config C --x …` builds a graph with these nodes:

1. **derive:** knobs become expressions and profiles, written to `state/derived.json`.
2. **render:** if `geom` is set, the writer renders `geom.txt`.
3. **preflight:** runs `check`.
   - Not ok: write `broken.txt` and `preflight_verdict.json`, the files the runner already reads, and the point ends.
4. **One node per step,** with edges from `files_from`. Independent steps run in parallel. Each node works from its state files:
   - `state/<step>_results.json` exists: skip the step;
   - `state/<step>_cluster.txt` exists: poll that handle;
   - neither exists: `submit`, then write the handle to `state/<step>_cluster.txt`, the file name the pool, launch checks and scan already use.

   It polls `status` at `poll_ms`, clamped to 30 s–10 min.
   - `completed`: call `results` and write `state/<step>_results.json`.
   - `failed` or `cancelled`: write `broken.txt` naming the step and the kit's message, and the point ends.
5. **score:**
   - look up each objective and extra metric;
   - apply the transforms;
   - write `summary.json` and `evaluate_result.json`;
   - append one leaderboard row, under a lock and idempotent by name.

**Rules for every kit call (the kit client, from spec 1 §1 as amended by the review):**
- **Processes:** one server process per kit, per child.
- **Environment:** each kit's `env_passthrough` comes from `kits.toml`, because the MCP SDK otherwise passes only six variables.
- **Timeouts:** every call has a named timeout.
- **Retries:**
  - `status`, `results`, `describe` and server start get up to 3 bounded retries;
  - `submit` may be repeated, which is safe because it is idempotent by name.
- **Tracing:** every call carries `_meta["gov.fnal.mu2e/workflow"] = "<campaign>/<config>/<step>"` and appends one line to `GRAPH_DATA/<campaign>/kit_trace.jsonl`.

## Adapters and plugins

### Registry

Each entry is keyed by kit name and declares:
- its accepted `kits` and `fixed` keys;
- whether it accepts lists;
- whether it uses stage templates;
- whether it offers `check`.

A kit that speaks the contract natively needs no entry: the engine calls its tools directly.

### `toykit`

A small MCP server in `tests/` that speaks the contract natively. Its delays and failures are configurable. It is the reference implementation, and the CI engine for Phase B.

### prodtools adapter (MCP only)

| Contract call | prodtools |
|---|---|
| `submit`, grid | Render the entry from the stage template (with `{geom}`, job counts, events per job and memory), then call `submit_once(json=<entry>, desc, dsconf, run_as="self")` |
| `submit`, local (`--local`) | `run_local(...)`, the new tool from P2 |
| `status` | `run_status(name)`: `done`/`short` becomes `completed`, `failed` becomes `failed`, anything else is `working`. `unknown` is never success. |
| `results` | Output paths of successful jobs from `run_status`, plus `{njobs, njobs_ok}`. The step fails if `njobs_ok / njobs < quorum`. |

**What the adapter also does:**
- **Input staging:** stages the `files_from` outputs into a `dir:` area, one file per job, which is today's `input_farm`.
- **Events per job:** stamped at submit, as the events-per-job incident requires.
- **Submit stagger:** keeps the per-process submit lock and the 60–90 s gap, which covers the concurrent-token-contention incident. Parallel steps must not submit together.
- **Log scan:** reads the successful and failed jobs' logs under the `outstage` path that `run_status` returns. It fails the step if any `fatal_log_codes` appear, replacing today's `scan_logs` node.
- **No recoveries,** ever.

**Launch settings:** `kits.toml` starts prodtools from the user's clone at `${AUTORESEARCH_PRODTOOLS}/mcp/scripts/start_write_mcp.sh` (and `start_mcp.sh` for reads). Its `env_passthrough` is `KRB5CCNAME` and `BEARER_TOKEN_FILE`, and it sets `SPACK_USER_CACHE_PATH` off NFS.

### beamkit adapter (Phase D)

- `submit` calls `run_beamline(tag, params, deck_ref, njobs, site, dsconf=<per-config>)`. Passing an explicit per-config `dsconf` (with `_` mapped out of the config name) is what makes it idempotent.
- `status` combines `beamline_status` with the output count. A step is `completed` when the queue is empty and the files are counted.
- `results` comes from `beamline_outputs`, with `quorum` applied.
- It **never calls `make_recoveries`.**
- Knobs arrive as `params`. The first study uses deck parameters only, so geometry include files and `extra_files` are out of scope.

### anakit adapter (Phase E, optional)

`submit` and `results` wrap `run_analysis(name, files, params)`. Its tools are synchronous today, so `status` reports `completed` once the call returns.

### Local plugins (`plugins/`)

| Plugin | Contract calls | Source |
|---|---|---|
| `offline_preflight` | `check` | today's `bo_driver` preflight: `mu2e -n 1`, surface check, GDML checks |
| `ce_sensitivity` | full contract | today's harvest steps: EdepAna plus the sensitivity macro, with successful-job denominators. Returns `s_over_sqrt_b` and related metrics. |
| `flash_edep_per_pot` | full contract | today's PyROOT extractor. Returns `flash_edep_per_pot` and `flash_edep_per_event`. |

- Plugins run in a subprocess under the muse environment.
- `submit` runs to completion (bounded by `fixed.timeout_s`), and `status` then reports `completed`.
- They can move to anakit later without any study changing.

## Failures and recovery

Every failure is loud and explained. **A missing number is never replaced by 0.**

| Failure | When it's caught | Result |
|---|---|---|
| Invalid study | at load | The launch refuses and names the field and the rule. |
| A kit won't start, required env is missing, or `describe` disagrees with the study | `check_kits(study)`, a new launch check | The launch refuses. |
| Preflight fails | per point | `broken.txt`; no row. |
| A step ends `failed` or `cancelled`, or is below `quorum` | per point | `broken.txt` naming the step and the message; no row. |
| A metric is missing, not a number, or ≤ 0 under log10 | at score | A failed evaluation naming the metric; no row. |
| A kit reply outside the contract | kit client | A failed evaluation; never read as success. |
| Credentials expire | `status` calls fail | Bounded retries, then fail loudly. Launch still requires 4 h of ticket life. |
| A child or the runner crashes | at restart | Adopted from the state files; no second submit, and at most one row. |

**No grid-job recoveries:** failed jobs inside a step are never resubmitted.

## Changes needed in prodtools

These go in the operator's repo, alongside Phases A–B, with PRs opened only on the go-ahead.

- **P1:** `submit_once` accepts code-tarball entries: `code` set and no `simjob_setup` (`_select_push_params`, `tools.py:94`). It must also accept entries whose `input_data` is a `dir:` staging area; that part is **unverified and gets checked first.**
- **P2:** a `run_local(json, desc, dsconf, nproc)` tool that writes a receipt, plus a local-receipt path in `run_status` so it can report local runs. Today `run_status` depends on condor history.
- **P0** (install without a clone) is optional and not needed here.

## Phases

Each phase gets its own implementation plan. The suite stays green at every commit.

| Phase | Delivers | Depends on | Acceptance |
|---|---|---|---|
| **A. Study model** | `core/study.py`, `derive` lifted out of `geom`, the generic leaderboard, `build_problem(study)`, `list_problems` enriched, and a one-time conversion of the 7 live foilspf-family specs to schema 2 (committed; the old-format loader deleted) | none | Golden parity on foilspfbpz: the same history tensor fingerprint, the same `budget_sob` and `qnehvi` picks, the same rendered `geom.txt`. A synthetic three-objective study fits and picks. |
| **B. Contract engine** | the contract, the kit client (`core/kits.py`, `kits.toml`), the per-point graph builder, the adapter registry, `toykit` | A | A toy study (Branin, 2 objectives, 1 constraint, q = 2, 8 evaluations) runs end to end in CI from a JSON file alone, in under a minute. |
| **C. foilspf on the engine** | the prodtools adapter (MCP only), the stage templates holding every stage-specific value, the three plugins | B, and prodtools P1 and P2 | First a dry run: the rendered entries and submit arguments match today's. Then one foilspfbpz point at q = 1 on the grid, whose row agrees with history within noise. Then **delete** the old path: the `pipeline.py` verbs, `harvest.py` wiring, the `scan_logs` and preflight nodes, `ALL_STAGES`/`INPUT_STAGE`. |
| **D. beamkit adapter** | the adapter, the first G4beamline study | B | A study defined only in JSON lands rows through beamkit. |
| **E. Second Offline study** | OPA: a `mustops_cp` stage template plus a tracker-deposit metric (a plugin, or an anakit analysis) | C | OPA, defined only in JSON (plus that template and metric), lands rows. |

## Testing

**Unit tests:**
- **Loader:** one test per rule, and each must fail loudly naming the field.
- **`derive`:** must match today's `geom_template` output on every foilspf spec.
- **`build_problem`:** transforms, negation and the constraint for N = 1, 2 and 3.
- **Leaderboard:** reads old boards, refuses a board with no header, writes idempotently.

**Engine tests, against `toykit`:**
- a dependency graph with parallel steps;
- `failed` and `cancelled` steps;
- a metric that is missing or ≤ 0;
- a `submit` timeout and an idempotent re-submit;
- a child killed mid-step, restarted with no second submit;
- a runner killed, restarted and adopting its children.

**Adapter tests:** each runs against a scripted fake of its kit. A contract test checks every argument we send against the real kit's tool schema when that kit is installed, and is skipped otherwise.

**Parity:** the existing `tests/golden_parity.py` is extended with the gates above. `hybrid` picks are excluded because of their known nondeterminism at scale.

**Command:** `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`

## Out of scope

- Workflow branches, loops, multi-fidelity and adaptive event counts.
- Categorical and conditional knobs.
- More than one constraint.
- `define_study` over MCP.
- The G4beamline geometry include writer and beamkit `extra_files`.
- http transport.
- The MCP Tasks extension.
- Migrating the 4 archived specs under `mode_specs/archive/`.

## Open questions

1. The first G4beamline study and its figure of merit (Phase D).
2. Whether anakit takes `ce_sensitivity`, `flash_edep_per_pot` and the tracker-deposit metric, or they stay plugins. This needs M. MacKenzie.
3. The exact FHiCL for `mustops_cp`. The retired `mustops_pileup` stage (`b369eda^`) used a `MuStopPileup` stream.
4. Whether q children each running their own prodtools servers reopens the NFS lock wedge. The mitigations are the stagger and the off-NFS spack cache. The fallback is one parent-owned server shared by the children.
