# Studies (schema 2)

One file per study: `mode_specs/<name>.json`, where `<name>` equals the
`"name"` field. Every file here, plus every `*.json` in the directories on
`$AUTORESEARCH_STUDY_PATH` (colon-separated, each entry an ABSOLUTE path;
a relative entry is a load error), is loaded at import by
`core/study.py`. `archive/` holds retired studies and is not loaded — see
below.

The format, field rules and examples are in
`docs/superpowers/specs/2026-09-23-generic-study-design.md`
("The study file (schema 2)").

## Starting a new study

There is no template file — copy an existing `_ax` study (e.g.
`mode_specs/foilspfbpz_ax.json`). Then change:

1. `"name"`: must equal the file stem.
2. `"leaderboard": {"file": ...}`: a basename no other *loaded* study
   uses. The loader compares leaderboard basenames across every loaded
   study and refuses a collision (`core/study.py:730-735`), since two
   studies sharing one board would contaminate each other's GP history.
3. the knobs, `derive`, `geom`, `kits` and `evaluate` steps.

Every key is required and unknown keys are rejected, so a typo fails at
import, never hours into a campaign.

### From draft to launch

1. **Draft outside the study path**, in
   `$AUTORESEARCH_DATA_ROOT/study_drafts/<name>.json`. A file dropped
   straight into `mode_specs/` (or a directory on `$AUTORESEARCH_STUDY_PATH`)
   is loaded by every command at once, broken or not.
2. **A new name and a new board.** Never reuse a loaded study's name: a
   second file of that name on the study path makes every load fail
   ("defined twice"), and a draft with an existing name is checked as that
   study's replacement, so it passes and, installed into `mode_specs/`,
   overwrites the original. To change
   an existing study, copy it under a new name with a new
   `leaderboard.file`. Changing a knob's bounds means changing the clip of
   every profile built from it: the loader refuses a profile whose controls
   are all knobs unless its `clip` equals their bounds.
3. **Check it** (`graph/check_study.py`; load, `${ARTIFACT}` paths, the
   launch check, the geometry pre-check at the middle of the knob box):

       source ./activate.sh
       PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.check_study \
           $AUTORESEARCH_DATA_ROOT/study_drafts/<name>.json --json \
           [--executor grid|local] [--parallel N] [--x=v1,...]

   Use `$AUTORESEARCH_PYTHON`: the system `python3` has no `tomllib` and
   fails at import. Pass the executor the study will launch with (grid
   needs a Kerberos ticket with 4 h left). The pre-check takes about 6
   minutes; run it in the background and wait for it to end. Exit 0: every
   check passed. 1: a check failed; its `problems` say why and `detail`
   holds any traceback. 2: a bad command line. 3: check_study itself broke
   (`error` has the traceback). "another check_study of '<name>' is
   running" means wait and rerun, not edit the draft. Through MCP, the
   `autoresearch` server's `start_check`/`check_result` run this same
   check (`wiki/drivers/service.md`).
4. **Install, then check again by name**: copy the file into `mode_specs/`
   (a production line, committed) or a directory on
   `$AUTORESEARCH_STUDY_PATH` (a toy or one-off), then
   `... -m graph.check_study <name>`.
5. **Launch** (`--help` on either lists every flag):

       PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.run --study <name> \
           --config <point> --campaign <campaign> --x=v1,... \
           [--context name=value ...] [--executor local --parallel N]
       PYTHONPATH= "$AUTORESEARCH_PYTHON" -m graph.closed_loop --study <name> \
           --q <in-flight> --max-evals <total> --picker <picker> \
           --name-prefix <prefix> [--context name=value ...] [--executor ...]

   A zero-knob study runs with `graph.run` and no `--x`. Every name in the
   study's `leaderboard.context` needs a `--context name=value` (the `_ax`
   studies declare `alpha`).

**A knob a deck reads (G4beamline, kit `beamkit`).** A G4beamline study
has no geometry writer (`geom: null`): its knobs are deck parameters, given
on the g4bl command line by mapping them in the step's `params`. The deck
must declare each one `param -unset` (a plain `param` line overrides the
command line), on a deck branch pinned by `kits.beamkit.deck_ref` (a full
sha) at `deck_url`. Fixed deck values go in `kits.beamkit.deck_params`.
Example: `ptg4bl.json` and the deck branch `ptarget-polycone`; the job log
echoes every command with its values, which shows what reached the deck.
A `beamkit` study runs on the grid only, and campaigns use
`--picker qlnei` when it has one objective.

**A number from an earlier step (`params_from`).** A step's `params` come
from the point (a knob, const, expr or profile) and its `fixed` values are
constants; `params_from` takes a kit param from an earlier step's metric,
as `"<step>.<metric>"` (the form an objective's `metric` uses). Every step
has the key; it is `{}` when unused. Example: the sensitivity takes the
stopping rate a `muon_stop_rate` step measured, and its files from an
`edep` step:

    {"step": "sob", "kit": "anakit", "entry": null, "files": [],
     "files_from": ["ce_edep"], "params": {},
     "params_from": {"stops_per_pot": "stops.stops_per_pot"},
     "fixed": {"analysis": "approx_ce_sensitivity"}}

- The source must be another step of the study, never the step itself.
- A mapped param (`params` or `params_from`) is set in one place only: not
  also in the other mapping, `fixed` or the kit's settings.
- The step waits for its sources as for `files_from`, and a cycle through
  either is refused. A step read only through `params_from` counts as used.
- The launch check refuses a source step whose kit does not return the
  metric, and a param the step's kit does not take.
- At run time a missing metric, or one that is not a finite number, fails
  the step (`broken.txt` names it); there is no default. The value is kept
  in the step's `<step>_results.json` `params`.
- The engine passes the metric as it is: a formula belongs in the kit (an
  analysis parameter), not in the study.

A step's `measure_basis` carries `params_from` only when it is set, so a
study without one keeps its `measure_sha` and its board.

Keep the shipped files' layout: one knob, profile, geom line, kit, step,
objective or column per line. Only the parsed JSON matters (`spec_sha`
hashes it), so the layout is for readable diffs.

## Studies run on the engine

Every loaded study runs on the contract engine — `graph.run` per point,
`graph.closed_loop` for a campaign. There is no other runner: the pipeline
and its `--mode` dispatch were deleted in Phase C3 (2026-09-28). A study's
`"leaderboard.layout"` must be `"v2"`, so its board carries `measure_sha`
and refuses an append measured a different way; `"v1"` is refused at load
since 2026-09-29 (only the archived studies below still say it).

Each foilspf line has an engine twin, `<name>_ax.json` (Phase C2b): the same
knobs and geometry on SimJob MDC2025ax, with sob and flash from the `anakit`
kit and its own v2 board. These seven `_ax` studies are the production lines
now; the originals they were cloned from are archived (see `archive/` below).

`ce_chain.json` is the one other shipped study: the CeEndpoint production
chain dts -> dig -> mcs -> nts, then an anakit `nts_momentum` plot, with no
knobs (so `graph.run` only; spec
`docs/superpowers/specs/2026-09-30-ce-chain-design.md`).

Since 2026-09-30 the launch itself is refused when the study's board holds
rows of another `measure_sha` (or a header that does not match the study's
columns): set a new `"leaderboard.file"` to start a new board. A kit's
version (part of `measure_sha`) changes only when its author bumps it by
hand (since 2026-10-05): bump an adapter's `VERSION` when a step would
measure anew, including an anakit fork change that alters an analysis. A
board whose rows differ only by an old-scheme build (before 2026-10-05) is
re-stamped once with `python -m graph.restamp_board --study <name> --why
"..." [--confirm]`.

The rules, as the code enforces them:

- A prodtools step must set `quorum` in `fixed` (below it the step
  fails), at most 200 `njobs`, and `kits.prodtools.fatal_log_codes` lists
  the log codes that fail a step (foilspf: `GeomSolids1001`).
- A stage template names its prodtools `desc_fmt` (`{cfg}` and `{geom}`
  are substituted). The key keeps this name — a rename to `desc` was
  considered and dropped, since it would change every `_ax` study's
  `measure_sha`. The run label is the study setting
  `kits.prodtools.dsconf`: it must contain `{cfg}` and, filled in, hold
  only letters, digits and `_`. The `_ax` studies say `MDC2025ax_{cfg}`.
  A template still carrying `dsconf_fmt` is refused.
- `"preflight": {"kit": "offline_preflight", ...}` gates each point on
  `mu2e -n 1` with G4's surface check, run on this node from
  `kits.offline_preflight.code_tarball`, which must equal
  `kits.prodtools.code_tarball` when a study has both. A failure (or an
  `ambiguous` run) marks the point broken before anything is submitted;
  the log is `<GRID_DATA_ROOT>/<config>/preflight/preflight.log`.
- `knobs: []` is a one-shot study: `graph.run` without `--x`;
  `graph.closed_loop` refuses it.
- `--executor grid|local` and `--parallel N` choose where the jobs run;
  `tests/fixtures/engine_studies/prodtools_smoke.json` is the worked
  example.
- A study naming an unknown kit, or breaking any rule above, is refused
  when `core.modes` is imported, so ONE broken study file — here or
  anywhere on `$AUTORESEARCH_STUDY_PATH` — stops every command for every
  study: `graph.run`, `graph.closed_loop`, and the surrogate MCP server.

`tests/fixtures/engine_studies/branin.json` is the worked example: two
knobs, two objectives (Branin minimized, Currin minimized + log10) with
Currin constrained, one `toykit` step, `"layout": "v2"`. It's what
`tests/test_closed_loop.py`'s acceptance test (`TestBraninCampaign`) runs
end to end.

A study need not live in this directory: any `*.json` under a directory
named on `$AUTORESEARCH_STUDY_PATH` (colon-separated, each entry an
absolute path) is loaded the same way. That's where a study that isn't a
production line yet — a toy, a one-off experiment — belongs instead of
`mode_specs/`.

## `archive/`

Not loaded — `core/study.py` leaves this directory out of the load glob, so
nothing here is ever selectable with `--study`, and it stops none of the
routing rules above. Two different things live here:

- The four **schema-1** fixed A/B reference files, in the pre-generic-study
  format: `ipa625.json`, `ipafix.json`, `ipaovr.json`, `nominal.json`, from
  the retired IPA/mmackenz lines.
- The **seven original foilspf studies** — `foilsflash.json`,
  `foilspf.json`, `foilspf2k.json`, `foilspfbp.json`, `foilspfbpx.json`,
  `foilspfbpz.json`, `foilspfbw.json` — archived in Phase C3 (2026-09-28)
  when the pipeline that ran them was deleted. These are schema-2, layout
  `"v1"` (the pipeline's shape), which the loader refuses since
  2026-09-29. Re-running one is NOT just a layout flip, though: each also
  names the `ce_sensitivity`/`flash_edep_per_pot` kits, which C3 deleted
  from `kits.toml` (see e.g. `mode_specs/archive/foilspfbpz.json`'s `sob`/
  `flash` steps) — those analyses now live only as `analysis` params under
  the `anakit` kit. Re-running one for real means using its `_ax` twin, or
  porting its kits to anakit as well as switching the layout to `"v2"`.
  They are archived rather than deleted because their leaderboards,
  `leaderboards/leaderboard_bo_<name>.tsv`, stay as plain files. Their engine twins,
  `<name>_ax.json`, live in this directory's parent, `mode_specs/`, and are
  loaded normally.

## Gotchas

- **Integer knobs still need a float format.** Write `"fmt": "{:.0f}"`, not
  `"fmt": "{:d}"`, even for a knob with `"type": "int"`. The loader
  validates every `fmt` by formatting a float with it, and `"{:d}"` raises
  there: a loud load error, but a round trip if you don't know it.
- **`i` and `n` are reserved names.** The geometry renderer injects them
  into the `per_index` scope, so a knob, const, expr or profile called `i`
  or `n` would be silently shadowed. Use `n_up`, `n_foils`, etc.
- **A knob may not be named after a leaderboard column** (`config`, an
  objective, an extra metric or an extra column): the TSV header would carry
  the column twice and history would read the metric back as a coordinate.
- **Kit paths are written as `${ARTIFACT}/<path>`**
  (`kits.prodtools.code_tarball`, `kits.offline_preflight.code_tarball`). The
  token expands against this operator's artifact root, falling through to
  the `backing` link for anything not built locally
  (`./setup.sh --backing <path>`). A bare absolute path under a user area is
  rejected at load: it would make the study runnable by exactly one account.

## Why not `modes/`?

A top-level `modes/` directory would be an implicit namespace package: from
the repo root, `import modes` would resolve to it instead of `core/modes.py`,
and `modes.STUDIES` would fail with an `AttributeError` far from the cause.
Don't rename it.
