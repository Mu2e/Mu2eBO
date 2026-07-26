# JSON-defined optimization modes

One file per optimization line: `modes/<name>.json`, where `<name>` matches the
`"name"` field. Every file here is loaded at import and merged into
`core.modes.SPECS`.

See `docs/superpowers/specs/2026-07-25-json-configurable-modes-design.md` for the
schema, and `tests/fixtures/modes/foilsflash.json` for a complete worked example.

A file whose name collides with a Python-defined mode (foils, foilsf, foilsflash,
foilsg, prodtarget, prodtarget6d) is a hard error, not an override.
