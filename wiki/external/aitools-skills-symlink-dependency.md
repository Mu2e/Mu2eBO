# aitools/ — untracked in-tree clone that 12 user skills symlink into

**Type:** external
**Status:** resolved
**Updated:** 2026-07-17

> **RESOLVED 2026-07-17:** clone moved to the neutral home
> `/exp/mu2e/app/users/oksuzian/aitools` (same-volume mv, instant); all 12
> `~/.claude/skills/` symlinks re-pointed and verified resolving; the
> `aitools/` line dropped from the project `.gitignore`. The project tree no
> longer carries any cross-project dependency.

## Summary
`aitools/` at the project root is an untracked, gitignored nested git clone
(the Mu2e "aitools" skills+MCP repo, snapshot 2026-04-29) with **zero
references from project code** — but it is silently load-bearing for the
user's whole Claude setup: 12 symlinks in `~/.claude/skills/` resolve to
`/exp/mu2e/app/users/oksuzian/autoresearch/aitools/skills/*`. Any tree-level
operation (archiving the project, aggressive cleanup, fresh clone elsewhere)
breaks 12 cross-project skills with no error surfaced at the repo.

## Key facts
- Found by the 2026-07-16 simplification audit (lens 2/5): grep over
  `*.py/*.md/*.sh/*.json` in the repo finds no reference; `.gitignore:59`
  hides it; it has its own `.git`.
- `ls -la ~/.claude/skills/` shows the 12 symlinks (building-with-muse,
  coding-with-fhicl, finding-data-sam, …).
- Recommended fix: relocate the clone to a neutral home (e.g.
  `/exp/mu2e/app/users/oksuzian/aitools`) and re-point the 12 symlinks —
  0 lines of project code change. NEVER delete it as part of repo cleanup.

## Cross-links
- Related: [[venv-relocated-to-data-volume]] (same pattern: project-root
  entries whose real substance lives elsewhere)
- Source files: `.gitignore:59`

## Open questions / TODO
- Relocation not yet done (needs a quiet moment; it's a user-level change,
  not a repo change).
