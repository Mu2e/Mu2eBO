# JSON-defined optimization modes

One file per optimization line: `mode_specs/<name>.json`, where `<name>`
matches the `"name"` field. Every file here is loaded at import and merged
into `core.modes.SPECS`.

See `docs/superpowers/specs/2026-07-25-json-configurable-modes-design.md` for the
schema.

## Starting a new line

Copy **`tests/fixtures/modes/template.json`** — it is deliberately pointed at a
non-live leaderboard — and change three things:

1. `"name"` — must equal the file stem (`mode_specs/<name>.json`).
2. `"leaderboard": {"file": ...}` — must be a path **no other mode uses**.
3. the knobs and the `geom` block.

Do **not** start from `tests/fixtures/modes/foils.json` or `foilsflash.json`.
Those are the reference fixtures that reproduce the live Python lines
byte-for-byte, so they declare the **live** leaderboards on purpose (the parity
tests need the real paths). Cloning one and missing the leaderboard line — it
looks plausible — would append a new line's evals into a live TSV under an
identical column schema, and the owning mode's `load_history()` would then
parse them as its own. The loader rejects that now (leaderboard files must be
unique across specs — `core/mode_json.py` rejects a duplicate basename at
load), but the template is what you should copy.

A `"name"` that does not equal the file stem is a hard error, and so is a
`leaderboard.file` basename another spec already claims.

## Gotchas

- **Integer knobs still need a float format.** Write `"fmt": "{:.0f}"`, not
  `"fmt": "{:d}"`, even for a knob listed in `int_dims`. The loader validates
  every `fmt` by formatting a float with it (so a format that cannot render the
  values is caught at load, not on the grid), and `"{:d}"` raises there. This is
  a loud load error, not a silent one — but it costs a round trip if you don't
  know it.
- **`i` and `n` are reserved names.** The geometry renderer injects them into
  the `per_index` scope, so a knob/const/derived/profile called `i` or `n`
  would be silently shadowed. Use `n_up`, `n_foils`, etc.
- **A knob may not be named after a leaderboard column** (`sob`, your second
  objective, `alpha`, `obj`, `config`) — the TSV header would carry the column
  twice and history would read the metric back as a coordinate.
- **`musing` and `grid_tarball` are written as `${ARTIFACT}/<path>`.** The
  token expands against this operator's artifact root —
  `$AUTORESEARCH_ARTIFACT_ROOT`, or `/exp/mu2e/app/users/$USER` by default —
  falling through to the `backing` link for anything not built locally
  (`./setup.sh --backing <path>`). A bare absolute path under a user area is
  rejected at load: it would make the mode runnable by exactly one account.

## Why not `modes/`?

This directory is deliberately NOT named `modes/`, even though that would
read more naturally next to `core/modes.py`. A top-level `modes/` directory
is an implicit Python namespace package: from the repo root, `import modes`
would resolve to that empty directory instead of failing loudly, and
anything that later did `modes.SPECS` (e.g. `core/runtime.py`, which puts
`core/` on `sys.path` before importing `modes`) would get a confusing
`AttributeError` far from the real cause. Before this directory existed,
`import modes` was a loud `ModuleNotFoundError` — much easier to diagnose
than a silently-empty package. If you're tempted to rename this back to
`modes/` for tidiness, don't: it re-opens that collision with
`core/modes.py`.
