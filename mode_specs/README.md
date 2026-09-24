# Studies (schema 2)

One file per study: `mode_specs/<name>.json`, where `<name>` equals the
`"name"` field. Every file here, plus every `*.json` in the directories on
`$AUTORESEARCH_STUDY_PATH` (colon-separated), is loaded at import by
`core/study.py`. `archive/` holds retired specs in the old format and is
not loaded.

The format, field rules and examples are in
`docs/superpowers/specs/2026-09-23-generic-study-design.md`
("The study file (schema 2)").

## Starting a new study

Copy `tests/fixtures/modes/template.json` (it points at a non-live
leaderboard) and change:

1. `"name"`: must equal the file stem.
2. `"leaderboard": {"file": ...}`: a path no other study uses.
3. the knobs, `derive` and `geom`.

Every key is required and unknown keys are rejected, so a typo fails at
import, never hours into a campaign.

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

This directory is deliberately NOT named `modes/`, even though that would
read more naturally next to `core/modes.py`. A top-level `modes/` directory
is an implicit Python namespace package: from the repo root, `import modes`
would resolve to that empty directory instead of failing loudly, and
anything that later did `modes.SPECS` (e.g. `graph/nodes.py:13`, which puts
`core/` on `sys.path` before importing `modes`) would get a confusing
`AttributeError` far from the real cause. Before this directory existed,
`import modes` was a loud `ModuleNotFoundError` — much easier to diagnose
than a silently-empty package. If you're tempted to rename this back to
`modes/` for tidiness, don't: it re-opens that collision with
`core/modes.py`.
