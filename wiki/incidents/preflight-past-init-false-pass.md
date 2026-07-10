# preflight past_init false-PASS — geometry aborts classified as PASS

**Type:** incident
**Status:** resolved — fix landed 2026-06-12: `G4_FATAL_RX` fails
unconditionally on `GeomSolids00\d\d` / `*** Fatal Exception ***` /
"Aborting execution" before the past_init logic runs; `G4_GEOM_FAIL_RX`
widened to include GeomSolids; holeRadii canary assertion added; 4
regression tests in `tests/test_audit_fixes.py`
(`TestPreflightFatalAbortClassification`) including the advisory
GeomVol1002 negative case
**Updated:** 2026-06-12

## Summary

The preflight classifier in `autoresearch_bo_michael.py` (~:1938-1990)
returns PASS for runs whose G4 geometry construction **fatally aborted**.
`past_init` keys on substrings that appear in the log *before* geometry
construction (`"BeginRun"` — printed by EventGenerator's
`%MSG-w CONTROL ...@BeginRun` at ~log line 43 — plus `"GenParticle"`
etc.). When geometry then aborts, `past_init` is already True, so:
(1) the `G4_GEOM_FAIL_RX` check is skipped (`if not past_init:`), and
(2) the final verdict `timed_out or rc == 0 or past_init` → PASS.
Doubly broken: `G4_GEOM_FAIL_RX` (~:1815) matches
`GeomMgt000\d|GeomVol1002|placement|outside mother|overlap` but NOT
`GeomSolids0002` (invalid solid parameters) — same too-narrow-pattern
class as [[scan-broken-codes-too-narrow]].

This is why every foilsg06/foilsg05 child sailed through preflight while
its log contained the identical
`G4Exception GeomSolids0002 ... Invalid values for radii in solid:
Foil_00` + "Aborting execution" that killed the grid jobs
([[foilsg-grid-tarball-scalar-holeradius-fallback]]). The surface-check
overlap scan also reported 0 managed overlaps — vacuously, because G4
aborted before any overlap check ran.

## Key facts

- Evidence log: `bo_foilsg_preflight/foilsg06R00_00.log:3369-3371`
  (fatal GeomSolids0002) vs classifier PASS.
- `past_init` substrings (:1939-1943): `BeginRun`, `Event::beginEvent`,
  `EndOfEventAction`, `Begin processing the 1st record`, `GenParticle`.
  At least `BeginRun` and `GenParticle` can fire pre-geometry.
- The `past_init` gate exists for a legitimate reason: helical/foils
  surface-check emits ~117 advisory GeomVol1002 warnings on stock-geometry
  overlaps that must not fail preflight (:1950-1953 comment). The fix must
  preserve that.
- **Fix (pending):** treat `GeomSolids00\d\d` and
  `G4Exception.*Aborting execution`/`*** Fatal Exception ***` as FAIL
  regardless of `past_init`; widen `G4_GEOM_FAIL_RX`; keep the
  GeomVol1002-advisory carve-out.

## Cross-links
- Related: [[foilsg-grid-tarball-scalar-holeradius-fallback]] (the failure
  this masked), [[scan-broken-codes-too-narrow]] (same pattern-too-narrow
  class), [[foilsx04-all-preflight-ambiguous]] (prior preflight
  classification gap), [[preflight]]
- Source files: `autoresearch_bo_michael.py:1938-1990` (classifier),
  `:1815` (`G4_GEOM_FAIL_RX`)

## Open questions / TODO
- Implement the classifier fix + a regression test feeding the
  foilsg06R00_00 preflight log (or a minimal synthetic log with
  BeginRun-then-GeomSolids0002) and asserting FAIL.
- Audit other historical preflight PASSes for masked GeomSolids aborts
  (cheap grep over `bo_*_preflight/*.log`).
