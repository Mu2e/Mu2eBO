---
type: external
title: Open Knowledge Format (OKF) — candidate target format for this wiki
description: 'OKF v0.1 spec digest + wiki-conversion assessment (2026-07-17): ~90%
  isomorphic, 2 real costs (link rewrite, log.md newest-first regroup); CONVERTED
  2026-07-17'
status: resolved
timestamp: '2026-07-17'
---

# Open Knowledge Format (OKF) — candidate target format for this wiki

## Summary
OKF v0.1 (Google Cloud Data Cloud team, open spec at
github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) is an explicit
formalization of the Karpathy LLM-wiki pattern this wiki follows: a bundle =
directory tree of markdown "concept" files with YAML frontmatter, reserved
`index.md`/`log.md` filenames, and normal markdown cross-links. Conversion of
this wiki was assessed AND EXECUTED 2026-07-17 (user-approved): 117 pages,
1052 links rewritten, log.md regrouped into 61 newest-first date headings,
0 validation errors.

## Key facts
- **Conformance requires exactly 3 things:** every non-reserved .md has
  parseable YAML frontmatter; every frontmatter has non-empty `type`; reserved
  files follow the spec'd structure *when present*. Consumers MUST tolerate:
  missing optional fields, unknown types/keys, broken cross-links, missing
  index.md.
- **Frontmatter:** `type` required; recommended `title`, `description`,
  `resource` (URI), `tags` (list), `timestamp` (ISO 8601). Extra keys allowed
  → our `Status:` maps to a custom `status:` key.
- **Links:** bundle-relative `[text](/folder/page.md)` recommended (relative
  `./x.md` allowed). Relationship type comes from surrounding prose. Our
  `[[stem]]` → path conversion is deterministic (116 stems, zero collisions
  per the 2026-07-17 lint).
- **The two real conversion costs:** (1) rewriting all `[[stem]]` links to
  path links (lose folder-agnostic moves; gain GitHub-clickable links);
  (2) `log.md` MUST be restructured — OKF wants date-grouped `YYYY-MM-DD`
  headings NEWEST FIRST, ours is flat append-only oldest-first (~1000 lines);
  the "append one line" habit in hooks/skills becomes "add under today's
  heading at top".
- **Payoffs:** YAML frontmatter makes conformance machine-checkable (kills
  the bold-field Status-format lint-noise class found 2026-07-17); spec ships
  a static self-contained HTML graph visualizer; vendor-neutral portability.
- Root `index.md` may declare `okf_version: "0.1"` in frontmatter.
- Coordinated-change set if converting: wiki/CLAUDE.md schema, /wiki-lint
  command, stop-hook wording, project CLAUDE.md — same commit as the
  converted pages.

## Cross-links
- Related: [mu2e-exp-website-docroot](/external/mu2e-exp-website-docroot.md) (other publication surface)
- External: [blog](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing), [spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)

## Open questions / TODO
- CONVERTED 2026-07-17. Converter (idempotent, with parse-back validation)
  archived at the session scratchpad `okf_convert.py`; gotcha: 4 pages began
  with a bare `---` horizontal rule that must not be parsed as frontmatter.
- Try the OKF static HTML graph visualizer on the bundle (nice-to-have).
