---
type: external
title: POMS chained workflows, compared with the study JSON
description: POMS chains stages in an .ini campaign file ([dependencies X] = upstream stage + file pattern) and passes data through SAM lineage once the upstream submission is Located; it moves files, not numbers, and needs SAM-declared outputs, so it is no better for autoresearch studies; three ideas worth borrowing (edge file pattern, completion_pct = quorum, multiparam scan)
status: active
status_note: reviewed 2026-09-25 against fermitools/poms 0dae5d0 (2026-09-11) and Mu2e's Production/CampaignConfig
timestamp: '2026-09-25'
---

# POMS chained workflows, compared with the study JSON

## Summary
POMS (Fermilab's production orchestrator) chains campaign stages. A
downstream stage launches when an upstream submission reaches `Located`, and
reads the upstream outputs as a SAM dataset built from file lineage. It is a
production tool: it moves files between stages, tracks them in SAM, and
recovers failed files. It has no notion of a knob, a metric, an objective or a
loop that picks the next point, so it does not replace the study JSON or the
contract engine. Reviewed on 2026-09-25 when Phase C was being scoped.

## Key facts
- **File format: configparser `.ini`, uploaded with `poms_client upload_wf`.**
  Mu2e's example is
  `muse_050125/Production/CampaignConfig/mdc2020_beam.ini`.
  - `[campaign]` has `campaign_stage_list`, and `[campaign_defaults]` sets
    `completion_type`, `completion_pct`, `cs_split_type`, `job_type`,
    `login_setup` and `output_ancestor_depth`.
  - `[campaign_stage X]` overrides those per stage; its parameters are
    stringly-typed lists such as `param_overrides = [["--stage ", "pot"]]`.
  - `[dependencies X]` lists numbered edges: `campaign_stage_1 = pot_fcl`,
    `file_pattern_1 = %.fcl` (a SQL `like` pattern, or a SAM dimension
    fragment when it contains a space).
  - `[job_type X]` names the launch script (`fife_launch -c <cfg>`),
    `output_file_patterns` and an ordered `recoveries` list
    (`mdc2020_jobtypes.ini`).
  - A second layer, the fife_launch `.cfg` (`mdc2020_beam.cfg`), holds the
    jobsub options, outputs and SAM datasets per stage. For MDC2025 the
    stage settings live only in the POMS database, not in any file.
- **How an edge passes data** (`webservice/SAMSpecifics.py:172`
  `dependency_definition`, `SubmissionsPOMS.py:1428`
  `launch_dependents_if_needed`): once the upstream submission is `Located`,
  POMS creates the SAM definition `poms_depends_<submission>_<i>` =
  `ischildof:(snapshot_for_project_name <project>) and version <v> and
  create_date > '<submission time>' and file_name like '<pattern>'`, then
  launches the downstream stage with it as `dataset_override`. The data
  therefore flows only through SAM-declared outputs with parentage.
- **Dependents wait for recoveries:** they launch only when no recovery fires
  (see prodtools `wiki/pages/poms-reference.md`). Recovery kinds other than
  `pending_files` do not check that outputs exist, which caused the Run1Ban
  mix data loss.
- **Completion:** `completion_pct` promotes a submission to Completed;
  `located` also counts outputs. A submission older than 2 days is
  force-located, which is a silent fallback.
- **`multiparam` split** (`webservice/split_types/multiparam.py`) launches the
  cross product of lists of parameter strings, one launch per combination: a
  fixed scan with no feedback.
- **State is server-side**: a web service plus a database plus the
  `submission_agent` poller. The Mu2e instance is operated at FNAL.

## Compared with the study JSON
| | POMS | study JSON + contract engine |
|---|---|---|
| Edge | stage + file pattern, resolved through SAM lineage | `files_from`, resolved from the upstream step's `results` files |
| Needs SAM-declared outputs | yes | no (`dir:` staging, scratch outputs) |
| Numbers out of a stage | none | `results.metrics`, objectives, rows |
| Chooses the next point | no (`multiparam` is a fixed scan) | surrokit picker |
| Validation | loose (string lists, DB state) | typed loader, refuses unknown keys |
| Reproducibility | MDC2025 settings exist only in the DB | study in git, `spec_sha` / `measure_sha` per row |
| Failed jobs | ordered recoveries | none; `quorum` decides |
| Partial success | `completion_pct` | `quorum` |

**Ideas worth borrowing:**
- a file pattern on an edge, for when an upstream step produces more than one
  output kind;
- `completion_pct` confirms the `quorum` design;
- `multiparam` is the fixed-scan counterpart of the zero-knob analysis study.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md),
  [pipeline](/drivers/pipeline.md)
- Mu2e POMS internals (recoveries, split types, the dropbox): prodtools
  `wiki/pages/poms-reference.md` in `muse_050125/prodtools`
- Source: https://github.com/fermitools/poms (read at 0dae5d0; a shallow
  clone is in `/exp/mu2e/data/users/oksuzian/claude-scratch/poms_src/poms`)

## Open questions / TODO
- None.
