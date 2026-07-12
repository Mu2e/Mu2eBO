# LangGraph SqliteSaver checkpoint fails on numpy.int64 in prodtarget x-point

**Type:** incident
**Status:** resolved
**Updated:** 2026-06-07 (fix shipped at graph/pipeline_io.py:96 — `.item()` coerce in propose_one return)

## Summary
`graph.run --mode prodtarget --config-name pt001` crashes at checkpoint
write with `TypeError: Type is not msgpack serializable: numpy.int64`
inside `langgraph.checkpoint.sqlite.__init__:478` →
`jsonplus._msgpack_enc` → `ormsgpack.packb`. Distinct from the
already-fixed propose-JSON path ([[prodtarget-propose-skopt-empty-init]]
adds a `np.int64` coerce there). The `N` (numberOfPlates) Integer dim
arrives as `np.int64` from skopt and slips into the LangGraph state dict;
SqliteSaver tries to msgpack-encode the state and dies.

## Key facts
- **Failure path**: `langgraph/checkpoint/sqlite/__init__.py:470-478`
  → `serde/jsonplus.py:287-291` → `_msgpack_enc` (line 880) →
  `ormsgpack.packb(data, default=_msgpack_default, option=_option)`.
  `_msgpack_default` does NOT cast numpy scalars (verified by traceback —
  `raise exc` at jsonplus.py:291).
- **Symptom**: graph completes evaluate (zero-row written to scan_logs),
  then the checkpoint write at end-of-stream crashes with the
  msgpack error and brings down the run.
- **Trigger**: only fires on `prodtarget` mode because it's the only mode
  with `int_dims=[9]` (N=numberOfPlates) — other modes are all-Real, so
  skopt returns native floats.
- **Where to coerce**: candidates are (a) `graph/nodes.py` `propose` node
  output (cast x-point ints to native `int`), or (b) `graph/state.py`
  State reducer, or (c) at `ProdTargetMode.x` construction in
  `autoresearch_bo_michael.py`. Option (a) is the smallest change and
  matches the propose-JSON fix pattern.
- **Symptom path is reachable even when harvest fails** — the zero-row
  evaluate still writes state that contains the x-point.

## Cross-links
- Related: [[prodtarget-propose-skopt-empty-init]] (sibling np.int64 fix
  in the propose JSON-write path, NOT the LangGraph checkpoint path),
  [[bo-prodtarget]], [[sqlite-wal-corrupt-after-kill]]
- Source files:
  - `graph/nodes.py` (propose / evaluate nodes that write to state)
  - `graph/state.py` (state dataclass)
  - `autoresearch_bo_michael.py` ProdTargetMode (line ~1078 build_space
    with Integer dim)
- Reproducer: `python -m graph.run --mode prodtarget --config-name pt001`

## Fix shipped
- **Site**: `graph/pipeline_io.py:propose_one` return (line ~96).
  Chose this over `graph/nodes.py:node_propose` because it's the
  single chokepoint for both BO-derived and `--x-override` x-points
  (closed_loop pushes picks through the same path).
- **Coerce idiom**: `[v.item() if hasattr(v, "item") else v for v in x]`
  — works for any numpy scalar (np.int64, np.float64, np.bool_) and
  is a no-op for native Python types. Safer than `int()`/`float()`
  branching, which would have to read `mode.int_dims`.
- **Why not `ormsgpack` numpy option**: ormsgpack has
  `OPT_SERIALIZE_NUMPY` but LangGraph's `jsonplus._msgpack_enc`
  hardcodes its `_option` set and we don't control it; coercing at
  the source is the lower-risk fix.

## Open questions / TODO
- Confirm no other np.* types leak (np.float64 IS msgpack-OK via
  numpy scalar protocol but np.int64 is not — verify with a smoke).
  If a similar crash recurs from a downstream node, audit
  `graph/nodes.py` for state-writes that originate in
  `autoresearch_bo_michael` extras.
