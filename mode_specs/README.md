# JSON-defined optimization modes

One file per optimization line: `mode_specs/<name>.json`, where `<name>`
matches the `"name"` field. Every file here is loaded at import and merged
into `core.modes.SPECS`.

See `docs/superpowers/specs/2026-07-25-json-configurable-modes-design.md` for the
schema, and `tests/fixtures/modes/foilsflash.json` for a complete worked example.

A file whose name collides with a Python-defined mode (foils, foilsf, foilsflash,
foilsg, prodtarget, prodtarget6d) is a hard error, not an override.

## Why not `modes/`?

This directory is deliberately NOT named `modes/`, even though that would
read more naturally next to `core/modes.py`. A top-level `modes/` directory
is an implicit Python namespace package: from the repo root, `import modes`
would resolve to that empty directory instead of failing loudly, and
anything that later did `modes.SPECS` (e.g. `graph/config.py`, which puts
`core/` on `sys.path` before importing `modes`) would get a confusing
`AttributeError` far from the real cause. Before this directory existed,
`import modes` was a loud `ModuleNotFoundError` — much easier to diagnose
than a silently-empty package. If you're tempted to rename this back to
`modes/` for tidiness, don't: it re-opens that collision with
`core/modes.py`.

Concretely, this bit in production: a top-level `modes/` directory makes a
bare `import modes` from the repo root resolve as an implicit namespace
package instead of finding `core/modes.py` — silently succeeding with an
empty module (no `SPECS`) instead of raising `ModuleNotFoundError`. That
silent-wrong-answer failure mode is strictly worse than the loud import
error it replaces, because it surfaces later, elsewhere, as a confusing
`AttributeError: module 'modes' has no attribute 'SPECS'` rather than at
the actual point of the bad import.
