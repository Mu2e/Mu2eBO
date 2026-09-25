# Studies (schema 2)

One file per study: `mode_specs/<name>.json`, where `<name>` equals the
`"name"` field. Every file here, plus every `*.json` in the directories on
`$AUTORESEARCH_STUDY_PATH` (colon-separated, each entry an ABSOLUTE path;
a relative entry is a load error), is loaded at import by
`core/study.py`. `archive/` holds retired specs in the old format and is
not loaded.

The format, field rules and examples are in
`docs/superpowers/specs/2026-09-23-generic-study-design.md`
("The study file (schema 2)").

## Starting a new study

Copy `tests/fixtures/modes/template.json`, not a shipped spec: it points
at a non-live leaderboard. Then change:

1. `"name"`: must equal the file stem.
2. `"leaderboard": {"file": ...}`: a path no other study uses.
3. the knobs, `derive` and `geom`.

Every key is required and unknown keys are rejected, so a typo fails at
import, never hours into a campaign.

Keep the shipped files' layout: one knob, profile, geom line, kit, step,
objective or column per line. Only the parsed JSON matters (`spec_sha`
hashes it), so the layout is for readable diffs.

## Engine studies

A study whose kits are ALL engine kits (`core.modes.ENGINE`; a kit is an
engine kit once it has either a `kits.toml` entry or, from Phase C, a
registered adapter — `toykit` is the only one today) runs through the
contract engine — `graph.study_run` per point, `graph.study_loop` for a
campaign — instead of the pipeline. Its `leaderboard.layout` should be
`"v2"`, so its board carries `measure_sha` and refuses an append measured
a different way. A study with even one kit that has no adapter yet
(`prodtools`, `offline_preflight`, `ce_sensitivity`,
`flash_edep_per_pot` — Phase C) still runs through the pipeline
(`core/bo_driver.py`, `graph/run.py`, `graph/closed_loop.py`), regardless
of layout.

`tests/fixtures/engine_studies/branin.json` is the worked example: two
knobs, two objectives (Branin minimized, Currin minimized + log10) with
Currin constrained, one `toykit` step, `"layout": "v2"`. It's what
`tests/test_study_loop.py`'s acceptance test runs end to end.

A study need not live in this directory: any `*.json` under a directory
named on `$AUTORESEARCH_STUDY_PATH` (colon-separated, each entry an
absolute path) is loaded the same way. That's where an engine study that
isn't a production line yet — a toy, a one-off experiment — belongs
instead of `mode_specs/`.

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
  (`kits.prodtools.code_tarball`, `kits.offline_preflight.musing`). The
  token expands against this operator's artifact root, falling through to
  the `backing` link for anything not built locally
  (`./setup.sh --backing <path>`). A bare absolute path under a user area is
  rejected at load: it would make the study runnable by exactly one account.

## Why not `modes/`?

A top-level `modes/` directory would be an implicit namespace package: from
the repo root, `import modes` would resolve to it instead of `core/modes.py`,
and `modes.SPECS` would fail with an `AttributeError` far from the cause.
Don't rename it.
