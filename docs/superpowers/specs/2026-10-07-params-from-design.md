# A step param from an earlier step's result (`params_from`) — design

Date: 2026-10-07. Status: draft for the operator's review.

## Why

The analysis tools in M. MacKenzie's analysis-mcp-server (anakit) feed
each other numbers. For example, `muon_stop_rate` returns `stops_per_pot`,
and since PR #3 `approx_ce_sensitivity` takes `stops_per_pot` as an input.

The engine lets steps pass files to each other (`files_from`), but not
numbers. A step's params come only from the point (`params`: a knob,
const, expr or profile) or from constants (`fixed`). That gap is why our
fork carries `ce_sensitivity`: it does the number-combining physics
inside one tool.

This design adds the missing link. The engine copies one step's metric
into a later step's param, unchanged. The engine never computes a
number, so all analysis physics stays in the analysis kit.

## What a study author writes

Each step gets a new key, `params_from`, which maps a kit param to
`"<step>.<metric>"`. This is the same form an objective's `metric`
uses.

Below is an illustrative example: the foilspfbpz sensitivity, rebuilt
from Michael's tools. The real study rewrite is a later spec.

```json
{"step": "stops", "kit": "anakit", "entry": null, "files": [],
 "files_from": ["mubeam"], "params": {}, "params_from": {},
 "fixed": {"analysis": "muon_stop_rate", "upstream_eff": 0.01278168}},
{"step": "ce_edep", "kit": "anakit", "entry": null, "files": [],
 "files_from": ["mustops_ce"], "params": {}, "params_from": {},
 "fixed": {"analysis": "edep"}},
{"step": "sob", "kit": "anakit", "entry": null, "files": [],
 "files_from": ["ce_edep"], "params": {},
 "params_from": {"stops_per_pot": "stops.stops_per_pot"},
 "fixed": {"analysis": "approx_ce_sensitivity",
           "cosmic_rate_per_s_per_mev": 0.0018181818181818182}}
```

The objective then reads `"sob.sensitivity"`.

## Rules at load (`core/study.py`)

1. **The key is required.** Every step must have `params_from` (ADR-0002:
   every key is required, unknown keys are refused). It is `{}` when
   unused, and the existing study files in `mode_specs/` gain
   `"params_from": {}`. Files in `mode_specs/archive/` are not loaded, so
   they stay as they are.
2. **The source must be a real, earlier step.** Each value is
   `"<step>.<metric>"`. The step must exist, and it may not be the step
   itself.
3. **A param name is set in one place only.** It may appear in only one
   of `params`, `params_from`, `fixed` and the kit's settings. This is
   the existing clash rule in `merge_params`, now also checked at load
   instead of only at the first run.
4. **Kit name rules cover the new key.** Kit rules that check `params`
   names also check `params_from` names: the beamkit deck-param name
   rule, the beamkit `deck_params` shadowing rule, and the reserved
   `entry`.
5. **The step waits for its sources.** A step depends on the steps in
   its `files_from` and in its `params_from`, and the cycle check covers
   both.
6. **Feeding a param counts as use.** A step read only through another
   step's `params_from` counts as used, so `_check_steps_used` does not
   refuse it.
7. **The preflight is unchanged.** It runs before any step, so it has no
   `params_from`.

## Measure identity

`params_from` is part of what a row measures, so each step's entry in
`measure_basis` carries it. A step's entry includes `params_from` only
when it is not empty. So every existing study keeps its
`measure_basis_sha`, and the boards of `ce_chain`, `ptg4bl` and the
`_ax` twins stay valid.

## Launch check: one place answers "what does a step read and send"

Today two places work out which metrics a study reads from a step and
which params a step sends: `contract._needs` and
`anakit.step_problems`. Both would miss `params_from`. So both move onto
two new accessors:

- `Study.metrics_read(step_name) -> frozenset[str]`: the metric keys
  read from that step by objectives, extra metrics and other steps'
  `params_from`.
- `Step.sent_params -> frozenset[str]`: the keys of `params`,
  `params_from` and `fixed` together.

With these, the launch refuses two mistakes before any job runs:

- **The producer does not return the metric.** The check uses the
  kit's `describe`, or anakit's catalogue `metrics`.
- **The consumer does not take the param.** anakit checks its declared
  `parameters`. A `params_from` param also satisfies a required
  parameter.

Range checks stay on `fixed` values only. A `params_from` value, like a
knob value, is unknown until the run.

## At run time (`core/scheduler.py`)

- **Start.** A step starts once every step in its `files_from` and
  `params_from` has completed.
- **The value.** Before submit, the param's value is read from the
  upstream record: `record["metrics"][metric]`.
- **Missing or bad value.** If the metric is missing or not a finite
  number, the step fails with no default and no fallback. `broken.txt`
  names the step with a message like this:
  `params_from stops_per_pot='stops.stops_per_pot': step 'stops' returned
  no metric 'stops_per_pot' (it returned [...])`. The contract already
  makes every metric a number, but a NaN can still pass through.
- **Record.** The value joins the step's `params`, which
  `<step>_results.json` already records. So each row's input is kept on
  file, and the record format does not change.
- **Resume.** Resume is unchanged. An adopted upstream record gives the
  same value, and a step that was already submitted is only polled, so
  its params are not sent again.

## Dashboard

`service/dashboard.py` also draws an edge from each `params_from`
source, the same way it draws a `files_from` edge.

## Docs

- `mode_specs/README.md` (the `study_guide` page) gets the key, the rules
  and the example.
- The wiki gets the same: the `contract-engine` page and a `log.md`
  bullet.

## Not in scope

- **Arithmetic on passed numbers** (scale, sum, ratio). The engine
  passes a metric as it is. If a study needs a combination, the
  analysis kit gets a param or an analysis for it, as PR #3 did for
  `stops_per_pot`. This is the line between analysis and framework.
- **Passing text, lists or files through `params_from`.** Files already
  have `files_from`.
- **The `_ax` study rewrite.** That covers Michael's tools as separate
  steps, `trigger_efficiency_ntuple` for `ce_chain`, the MDC2025ay
  Musing, new boards, and re-expressing the `budget_sob` budget. It is
  its own spec, after PR #3 merges.

## Tests

- **Load:**
  - a missing key, a bad form, an unknown step and a self-reference are
    each refused;
  - a clash with `params`, `fixed` or kit settings is refused;
  - a cycle through `params_from` is refused (for example, b gets
    `files_from` a and a gets `params_from` b);
  - a step used only by `params_from` is accepted;
  - the beamkit name rules apply to `params_from` keys.
- **Measure:**
  - every study in `mode_specs/` keeps its `measure_basis_sha`;
  - changing a `params_from` changes `measure_sha`.
- **Launch:**
  - a producer that does not return the metric is refused, on both the
    `describe` path and the anakit catalogue path;
  - a consumer that does not take the param is refused;
  - a `params_from` param satisfies a required anakit parameter.
- **Scheduler, with fake kits:**
  - the consumer waits for the producer and receives the metric's value
    in its params;
  - a missing metric or a NaN fails the step and writes `broken.txt`;
  - a resumed point with an adopted producer passes the same value.
- **Dashboard:** the edge is drawn.
