# Per-mode facts live in one pure-data registry: root `modes.py`

A mode's definition (musing, grid tarball, stage chain, harvest verb, stage
targets, search-space bounds, preflight policy) was scattered across ~20
dispatch sites in 6 files, several with silent fallbacks — the root soil of the
foilsflash-tarball, preflight-tuple, and foilsg-tarball incident class. Decided
2026-07-06: consolidate all per-mode *data* into frozen `ModeSpec` dataclasses
in a stdlib-only root `modes.py`, with every field required (a missing fact is
an import error, never a default). Behavior stays on the driver's `BOMode`
subclasses, which bind to their spec.

Why not the two obvious alternatives: growing `graph/config.py` would keep the
import-time env-var freezing and the "driver imports from graph/" inversion in
the same file; folding data into `BOMode` would force `pipeline.py`,
`graph/config.py`, and `.venv-botorch` to import the 2400-line driver (the
botorch venv lacks skopt, which is imported inside `build_space` — bounds must
be plain data precisely so that venv can read them). Consequence: `MODE_SPECS`
in `botorch_predict.py` and `MUSE_TARBALL_BY_MODE`'s `.get(..., michael)`
default are deleted, and a completeness test pins registry keys against the
`graph/state.py` mode Literal.
