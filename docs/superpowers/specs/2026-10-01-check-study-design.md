# check_study: prove a study file works before launch

Date: 2026-10-01. Status: draft for review. Branch `check-study` (from
`generic-study-phase-c1` 582c33b), worktree `../autoresearch-checkstudy`.
Piece 1 of the study-writing line: 1 check_study, 2 a Claude Code
study-writing skill, 3 the service on the autoresearch MCP server.

## Goal

One command tells whether a study file (`mode_specs/*.json`, schema 2, or a
draft anywhere on disk) will launch and pass its geometry pre-check, without
submitting a job or writing a leaderboard row:

    python -m graph.check_study <path-or-name> [--x=v1,...]
        [--executor grid|local] [--parallel N] [--json]

The skill (piece 2) and the MCP tool (piece 3) call it and read its JSON.
A hand-written study gets the same check today.

## Decisions taken

- **Reuse the engine's own code paths** (operator, 2026-09-30, option A):
  the loader, `contract.launch_problems` and the per-point graph. No second
  set of rules that could drift from what a launch enforces.
- **Static checks plus the geometry pre-check, at one point** (operator,
  2026-09-30: "just center, the geometry should be provided, it's a fixed
  release study"): the center of the knob bounds, or `--x`. No rendering at
  the corners (a corner may be legitimately infeasible and would read as a
  failure), no search.
- **Not checked here:** stage-template FCL paths and prodtools' own entry
  validation (the ce_chain spike's old output-module names). That needs
  `json2jobdef`/`fhicl-dump` under the tarball's setup for each step; a
  follow-up flag.
- The board check lives in `contract.launch_problems` already (ce-chain,
  merged 2026-10-01), so check_study gets it by calling that.

## What changes

### 1. `graph/study_graph.py`: `through`

`build_study_graph(..., through: str = "score")`. With `through="preflight"`
the graph is derive -> render -> preflight -> END: `run_steps` and `score`
are not added. Any other value than `"preflight"` or `"score"` is a
`ValueError`. Default behaviour is unchanged.

### 2. `graph/check_study.py` (new)

Four checks, in order. Each ends `passed`, `failed` (with its problems, one
string each) or `skipped` (with the reason).

1. **load.** The argument is a path to a `.json` file, or a study name
   (resolved through the loaded studies, `modes.STUDIES[name].path`).
   `load_study_file(path)` (so a draft outside `mode_specs/` works). Plus the
   two rules `load_study_dirs` applies across files: the study's name equals
   the file's stem, and its leaderboard basename is not used by a loaded
   study of another name (a loaded study of the same name is this study, a
   draft of an edit). A failure stops the run: checks 2–4 are skipped.
2. **artifacts.** Every string value in the raw JSON (kit settings, steps'
   `fixed` and `params`, at any depth) that starts with `${ARTIFACT}/` must
   name an existing file or directory, via `paths.artifact`. Today
   `paths.artifact` returns the intended path on a miss and the failure
   surfaces only when a kit opens it. One problem per missing path, naming
   the JSON location and the resolved path.
3. **launch.** `run.local_env_refusal()` and
   `contract.launch_problems(study, kits, executor=..., parallel=...,
   config_names=[config], board=board_for(study))`, with the `KitSet` the
   geometry check then reuses (campaign `check`). That is the check
   `graph.run` makes: executor rules, Kerberos with 4 h left on grid when a
   kit asks for it, the config-name rule, every kit starts and reports a
   version, the params/metrics cross-check, each kit's step checks, and the
   board (another `measure_sha`, or a header that is not the study's).
   `--executor` defaults to `grid`, as `graph.run`.
4. **geometry.** Skipped if check 3 failed (the kits it needs did not
   start). The point: `--x` if given (checked by `check_x`), else the
   midpoint of each knob's bounds (`(min + max) // 2` for an `int` knob,
   `(min + max) / 2` for a `real` one); a zero-knob
   study has the empty point. `build_study_graph(..., through="preflight",
   context={}, board=None)` invoked on it, in the scratch state directory
   below. Outcomes:
   - the study has a `preflight` kit: `passed` with the kit's message, or
     `failed` with the reason written to `broken.txt` (the kit's verdict, or
     a derive/render error such as a bad expression);
   - no `preflight` kit but a `geom`: `passed`, noted "rendered, not
     pre-checked" (e.g. `ce_chain`);
   - no `geom`: `passed`, noted "no geometry".

**Scratch.** Config name `check_<study>`, so the state directory is
`<GRID_DATA_ROOT>/check_<study>/state` and the pre-check works in
`<GRID_DATA_ROOT>/check_<study>/preflight` (the offline_preflight kit's own
layout); the shared `<GRID_DATA_ROOT>/_code/` unpack is reused as real runs
reuse it. Before the geometry check the directory is emptied, but only if it
holds the marker file `.check_study` that check_study writes when it creates
it; a directory of that name without the marker is reported as a failed
geometry check and left untouched. So a pre-check verdict is never reused:
every run checks again.

**Never:** a submit, a board append, a write outside
`<GRID_DATA_ROOT>/check_<study>/` (apart from the shared `_code/` unpack
and the kit-call trace every run writes).

**Output.** A readable report on stdout, or with `--json` one JSON object:

    {"study": "<name>", "path": "<file>", "ok": true|false,
     "point": {"<knob>": <value>, ...} | null,
     "checks": [{"name": "load"|"artifacts"|"launch"|"geometry",
                 "status": "passed"|"failed"|"skipped",
                 "problems": ["..."], "note": "..."}]}

`problems` is empty unless the check failed; `note` is "" unless there is
something to say (a skip reason, the pre-check's message, "rendered, not
pre-checked").

`point` is null when check 1 failed. Exit code 0 when every check passed, 1
when any failed, 2 for a bad command line (argparse) or a name that is not a
loaded study and not a file.

## Testing

- `through`: a toykit study built with `through="preflight"` ends after
  preflight; `run_steps` and `score` never run; a bad `through` raises.
- check_study on engine fixtures (toykit, `tests/fixtures/engine_studies`),
  through its `main(argv)` with `--json`:
  - a good study: all four `passed`, exit 0, the point is the bounds'
    midpoint (an `int` knob by floor division);
  - a file that fails to load: `load` failed, the rest `skipped`, exit 1;
  - a name/stem mismatch, and a board basename used by another loaded study;
  - a `${ARTIFACT}/` path that does not exist: `artifacts` failed, naming
    the JSON location;
  - a launch refusal (a kit that will not start) and a board of another
    `measure_sha`: `launch` failed, `geometry` skipped;
  - a preflight kit that fails at the center point: `geometry` failed with
    its message; one that passes: `passed`;
  - `--x` overrides the center; an out-of-bounds `--x` is a failed geometry
    check naming the knob;
  - the marker rule: an existing `check_<study>` directory without the
    marker is refused and left as it was; with the marker it is emptied.
- Nothing writes a board row or a cluster file in any test.

## Acceptance

1. Suite green.
2. `python -m graph.check_study foilspfbpz_ax` against the live data root:
   exit 1, `launch` failed on the board (its rows were measured with the
   pre-ce-chain anakit), `geometry` skipped.
3. The same in a sandbox `AUTORESEARCH_DATA_ROOT`: exit 0, the pre-check
   passes at the center point (~4.5 min); nothing under the sandbox's
   `autoresearch_leaderboards/`.
4. `python -m graph.check_study ce_chain --executor local --parallel 1`
   (sandbox): exit 0, `geometry` "rendered, not pre-checked".
5. A copy of `foilspfbpz_ax.json` (renamed, with its own board file) whose
   code tarball names a missing `${ARTIFACT}` path: exit 1, `artifacts`
   failed naming that path.

## Not in scope

- Stage-template FCL and prodtools-entry checks (a follow-up flag).
- Corner or multi-point checks; a local smoke run of the steps.
- The study-writing skill and the MCP tool (pieces 2 and 3).
- Optional objectives / a stages-only study.
