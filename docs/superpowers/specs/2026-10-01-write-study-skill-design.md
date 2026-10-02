# write-study: a Claude Code skill that drafts a study until it passes check_study

Date: 2026-10-01. Status: draft for review. Branch `write-study` (from
`generic-study-phase-c1` 3478ece), worktree `../autoresearch-checkstudy`.
Piece 2 of the study-writing line: 1 check_study (merged 2026-10-01),
2 this skill, 3 the same service on the autoresearch MCP server, 4 geometry
and physics changes as development guided by the skill.

## Goal

The operator describes a study in a sentence ("optimize flash over the three
outer foil radii, sob constrained, on MDC2025ax") and gets a schema-2 study
file that launches on the first try. The skill composes a draft, runs
`python -m graph.check_study <draft> --json`, fixes the draft from the
report until it passes, and then, with the operator's choice of place,
installs it. It never launches a campaign.

## Decisions taken

- **Study file only** (operator, 2026-10-01): the skill composes from parts
  that exist (kits in `kits.toml`, anakit analyses on the fork, templates in
  `stage_entries/`, geometry base files in the release) and writes one file,
  the study JSON. Everything it writes is covered by check_study. A request
  that needs a new stage template, a new analysis or a code change is out of
  scope: the skill says which and stops.
- **Install: ask each time** (operator): `mode_specs/` (a production line,
  committed only with the operator's OK) or a directory on
  `$AUTORESEARCH_STUDY_PATH` (a toy or one-off, never committed).
- **A written skill, no new code** (operator chose approach A): the skill
  holds the loop and the rules and points at the sources for the parts
  lists. A read-only parts command (`graph.study_parts`) was considered and
  deferred to piece 3, which needs the same list.

## The skill

`.claude/skills/write-study/SKILL.md`, in the repo. Its description
triggers on asks to write, draft or make a study, "a new study that
optimizes X over Y", and on fixing a draft that failed check_study. The
argument is the operator's description, or the path of a draft to resume.

### The loop

1. **Understand the ask.** Objective(s), the knobs with bounds and units,
   the geometry, the release and kits, the executor. Fill gaps from the
   nearest existing study; ask the operator only what is still open, one
   question at a time.
2. **Start from the nearest study.** Copy the closest `mode_specs/*_ax.json`
   (or `ce_chain.json` for a zero-knob production chain), as
   `mode_specs/README.md` advises, and edit it.
3. **Write the draft** to `$AUTORESEARCH_DATA_ROOT/study_drafts/<name>.json`
   (never `/tmp`, never `mode_specs/` before install). `name` equals the
   file stem. `leaderboard.file` is new:
   `leaderboards/leaderboard_bo_<name>.tsv`, a basename no loaded study uses.
4. **Check it**: `source ./activate.sh` then
   `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study <draft> --json`
   with the `--executor` (and `--parallel`) the study will launch with, run
   in the background (the pre-check takes about 6 minutes). For a grid
   study, `--executor grid` needs a Kerberos ticket with 4 hours left.
5. **Act on the exit code:**
   - **0**: go to install.
   - **1**: fix the draft from each failed check's `problems` (reading its
     `detail` traceback when the problem line is not enough) and check
     again. Checks marked `skipped` wait on an earlier one; fix that first.
     After 5 rounds, stop and show the operator what is left.
   - **2**: the command line was wrong (a bad `--x`, an unknown target);
     fix the command.
   - **3**: check_study itself broke. Stop and report `error` (type,
     message, traceback) to the operator; never work around a tool bug.
6. **What the skill fixes and what it asks.** It fixes on its own: names,
   keys, formats, typos, a board basename already taken, a missing
   `${ARTIFACT}` path that is clearly a typo. It asks the operator about
   physics: a failed geometry pre-check (an overlap at the center point,
   shown with the kit's verdict) is never answered by quietly shrinking
   bounds or dropping a knob. A board that holds rows of another
   `measure_sha` gets a new `leaderboard.file`, and the skill says so.
7. **Install.** Ask: `mode_specs/` or a directory on
   `$AUTORESEARCH_STUDY_PATH`. Copy the file there, re-run
   `check_study <name>` (by name, from its new place), and print the launch
   command (`graph.run --study <name> --config ... [--x=...]` or
   `graph.closed_loop --study <name> ...`). Committing a file in
   `mode_specs/` waits for the operator's OK.

### What the skill reads

The skill names these sources; it does not copy their contents, so it does
not go stale when a kit changes.

| Need | Source |
|---|---|
| Field rules, gotchas, layout | `mode_specs/README.md`; `docs/superpowers/specs/2026-09-23-generic-study-design.md` sections "The study file (schema 2)" and "Stage templates" |
| Worked examples | `mode_specs/*_ax.json`, `mode_specs/ce_chain.json`, `tests/fixtures/engine_studies/branin.json`, `tests/fixtures/engine_studies/prodtools_smoke.json` |
| Kits and their keys | `kits.toml` (`study_keys`, `fixed_keys`, `executors`, `check`) |
| anakit analyses (params, metrics) | `$AUTORESEARCH_ANAKIT/tools/analyses/*.py`, `$AUTORESEARCH_ANAKIT/tools/registry.py` |
| Stage templates | `stage_entries/*.json` |
| Geometry parameter names | the study's `geom.base` file and its `#include` chain in the release, through the work area's backing links (for MDC2025ax: `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax/backing/backing/Offline/<geom.base>`); never a search of `/cvmfs` |
| Names and boards taken | `mode_specs/*.json` and the directories on `$AUTORESEARCH_STUDY_PATH` |

### Rules the skill carries

Each costs a check round, or worse, when missed:

- A new `leaderboard.file` for every new study and whenever the measurement
  changes; never reuse a basename.
- `name` equals the file stem. No knob, const, expression or profile named
  `i` or `n`, or after a leaderboard column.
- An `int` knob's `fmt` is `"{:.0f}"`, not `"{:d}"`.
- Paths are `${ARTIFACT}/...`, never a user area. `kits.prodtools.code_tarball`
  and `kits.offline_preflight.code_tarball` name the same file.
- Every prodtools step sets `quorum` in `fixed`; `njobs` is at most 200.
- At least one objective, on a metric a step returns. A zero-knob study runs
  with `graph.run` and no `--x`; `graph.closed_loop` refuses it.
- Out of scope (stop and say which): a new stage template, a new anakit
  analysis, an Offline or geometry-code change, a new kit.
- **Never**: `graph.run`, `graph.closed_loop`, a submit, an edit of a board,
  a write to `mode_specs/` before install, a commit without the operator's
  OK.

## Testing

A skill is prose, so it is tested by running it (superpowers'
writing-skills method): watch an agent fail without it, then pass with it.

- **Baseline**: a fresh subagent (sonnet) without the skill gets scenario 1.
  Where it goes wrong confirms or adds rules above.
- **Scenarios**, each a fresh subagent (sonnet) given only the skill, in a
  sandbox: `AUTORESEARCH_DATA_ROOT` and `AUTORESEARCH_STUDY_PATH` under
  `/exp/mu2e/data/users/oksuzian/claude-scratch/`. Installs go to the
  sandbox study path only, never `mode_specs/`. A subagent cannot ask the
  operator, so each scenario's prompt carries the operator's answers (the
  install place, the executor) up front.
  1. **Variant**: "like foilspfbpz_ax, but only the three rOut knobs,
     70-110 mm". Expected: check_study exit 0 with the pre-check passed, a
     fresh board, installed and re-checked by name.
  2. **Zero-knob**: "ce_chain with 200 events per job". Expected: exit 0,
     geometry "rendered, not pre-checked", `--executor local`.
  3. **Out of scope**: "optimize calorimeter occupancy with a new
     calo_occupancy analysis". Expected: the skill stops and says it needs a
     new analysis (piece 4); no file written.
- **Pass**: scenarios 1 and 2 reach exit 0 within 5 check rounds; scenario 3
  stops cleanly; in every run no `graph.run`/`graph.closed_loop`, no submit,
  no write to `mode_specs/` or a board, no commit. Checked from each run's
  transcript and the sandbox afterwards.

## Records

- `mode_specs/README.md`, "Starting a new study": a pointer to the skill.
- `wiki/drivers/contract-engine.md`: a short write-study section; `log.md`;
  the `index.md` one-liner.
- Memory: the branch and its state.

## Not in scope

- New stage templates, analyses, kits or code (later pieces, 4 among them).
- The MCP service (piece 3) and a `graph.study_parts` command.
- Launching or monitoring a campaign.
