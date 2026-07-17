# FCL parser rejects non-ASCII characters (Unicode minus, em-dash, brackets)

**Type:** incident
**Status:** resolved
**Updated:** 2026-06-19 (recurred on bo-ipa mustops_pileup template; FHiCL-vs-SimpleConfig distinction added)

## Summary
mu2ejobdef / the FHiCL parser hard-fails on any non-ASCII byte in a
template `.fcl`, **including inside comments**. Discovered 2026-05-23
when 8/8 closed-loop helicalFT01 children failed at mubeam submit
because the FTFP_BERT comment block contained a Unicode minus sign
(`U+2212`, "−") rendered to indicate "-20% CPU savings".

## CRITICAL distinction: FHiCL (strict) vs SimpleConfig (lenient) — 2026-06-19
**This only affects `.fcl` files parsed by FHiCL. Geom `.txt` files parsed by
SimpleConfig TOLERATE non-ASCII.** Recurred 2026-06-19 on the [[bo-ipa]]
`pipeline_templates/mustops_pileup/template.fcl` — a Unicode arrow `→` (U+2192)
in a comment killed `mu2ejobdef --embed` at line 6 (mubeam/concat/mustops_ce had
already succeeded; only the new stage's FCL broke). The confusing part: the
**geom proposal file** emitted by `FoilsMode/IPAMode._geom_text` contains the
SAME chars (`°` U+00B0 in "120°", `→` in "TT_MidInner→DS2Vacuum") and runs fine
on hundreds of foils configs — because geom files go through **SimpleConfig**
(`services.GeometryService.inputFile`), a different, lenient parser, NOT FHiCL.
So: **stage `.fcl` templates MUST be ASCII; geom `.txt` comments need not be**
(though ASCII is still safer). When cloning a `_geom_text` comment into an
`.fcl` template, strip the non-ASCII. `grep -nP "[^\x00-\x7F]" <file>` is the
check.

## Failure signature
The `submit_<stage>_TIMESTAMP.log` in `<config>/graph_logs/` contains:

```
---- Parse error BEGIN
  detected at or near line N, character 1, of file ".../state/<stage>_template_materialized.fcl"

  # FTFP_BERT physics list: −20% CPU on mubeam vs ShieldingM ...
  ^
---- Parse error END
Error processing /.../state/<stage>_template_materialized.fcl
Traceback ...
subprocess.CalledProcessError: Command '['mu2ejobdef', ...]' returned non-zero exit status 1
```

The `^` always points to the first byte of the offending line. The
parser does NOT identify the byte as non-ASCII in its error message —
it just says "Parse error" near a line that to a human looks fine.
You have to inspect the bytes (e.g. `hexdump -C state/*_materialized.fcl | grep -E '^[0-9a-f]+ *([0-9a-f]{2} ){0,15}(e2|c2|c3)'`)
or `file -i` the materialized FCL to spot the UTF-8 marker bytes.

## Failure mode
1. graph.run materializes `pipeline_templates/<stage>/template.fcl` to
   `<grid_root>/<config>/state/<stage>_template_materialized.fcl` via
   `__GEOM_FILE__` substitution.
2. `mu2ejobdef --embed <materialized.fcl>` is invoked.
3. jobdef passes the file through the FHiCL parser, which rejects the
   non-ASCII byte at line N.
4. `subprocess.run(jobdef, check=True)` raises CalledProcessError.
5. The stage node sets `status="failed"` and `route_after_stage`
   terminates the graph; `[run] done` appears in the child log
   even though no cluster was submitted.

## Blast radius
All 8 FT01R00_* children failed identically — each materialized the
same broken template before jobdef. Wasted: 8 Code.tar.bz2 builds
(~30 s each) + 8 preflight runs. No grid jobs submitted (good — the
failure mode is local at submit time, not on the grid), but the
closed-loop parent process must be killed and the artifact dirs
cleaned before relaunching, because the materialized FCLs are
frozen-bad on disk and per-stage idempotency would re-use them.

## Fix
Use ASCII-only characters in template comments. In particular,
replace:

- Unicode minus `−` (U+2212) → ASCII `-`
- em-dash `—` (U+2014) → ASCII `-` or ` -- `
- double-square-bracket wiki-link syntax → "see wiki concepts/xxx.md"
  (the brackets themselves are ASCII but stay out of FCL anyway)
- smart quotes → straight quotes

A pre-commit lint or a `grep -P "[^\x00-\x7f]" pipeline_templates/`
check would catch this. Not yet wired.

## Cross-links
- Related: [[template-fcl-staleness]] (different failure but same
  blast surface — silent on the grid until G4 init), [[pipeline]], [[readvd-savepdg-string-not-int]]
- Driver: [[graph-runner]], [[closed-loop-runner]]
- Source files: `pipeline_templates/<stage>/template.fcl`,
  `pipeline.py:390` (the `subprocess.run(jobdef, ..., check=True)` call)

## Open questions / TODO
- Add `pipeline_templates/` lint to fail on non-ASCII before submit.
- Move template-comment block to a sibling `template.fcl.README.md`
  if we want unicode-rich annotations without contaminating the
  parser input.
