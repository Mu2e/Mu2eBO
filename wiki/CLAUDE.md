# LLM Wiki — schema and maintenance contract

This folder is a **persistent, AI-maintained knowledge base** for the
`/exp/mu2e/app/users/oksuzian/autoresearch` project. It follows the pattern in
[Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

The wiki is the *compounding artifact* of this project: facts, decisions, and
mental models that would otherwise live only in chat history or git commit
messages. Every Claude session that touches this project should read this file
first and update the wiki when it learns something the wiki doesn't already
know.

## Three-layer architecture

1. **Raw sources** — code, logs, leaderboards, summary.json files, mmackenz
   workflow tree, `program.md`. Immutable from the wiki's perspective.
2. **The wiki** (this folder) — synthesized markdown entity pages with
   `[[wiki-links]]`, indexed by `index.md`, journaled by `log.md`.
3. **Schema** (this file) — rules for how entries are shaped and maintained.

## Folder layout

```
wiki/
├── CLAUDE.md          # this schema + contract
├── index.md           # one-line pointer per page, grouped by category
├── log.md             # append-only chronological changelog
├── projects/          # active research lines (e.g. Michael's optimization)
├── concepts/          # physics + software concepts (TSdA, COL5, BO objective)
├── datasets/          # mmackenz priors, leaderboards, summary files
├── drivers/           # the executable scripts and their roles
├── incidents/         # bugs, gotchas, surprising failures, root causes
└── external/          # pointers to mmackenz repo, Mu2e Offline, CVMFS paths
```

## Page format

Every entity page is a markdown file with this skeleton:

```markdown
# <Title>

**Type:** project | concept | dataset | driver | incident | external
**Status:** active | dormant | resolved | superseded | open | recurring
**Updated:** YYYY-MM-DD

## Summary
One-paragraph elevator pitch. What is this and why does it matter to the project.

## Key facts
- Bullet points of load-bearing facts (file paths, parameter ranges, magic numbers).
- Each fact should be the kind of thing that would take >5 min to re-derive
  from raw sources.

## Cross-links
- Related: [[other-page]], [[another-page]]
- Source files: `path/to/file.py:LINE`
- External: [link](url)

## Open questions / TODO
- Anything unresolved. Empty section is fine.
```

Use `[[bare-stem]]` wiki-links (the page's filename without `.md` and without
the folder prefix). The maintenance loop resolves them.

## Maintenance loop

**Ingest** — When you learn a non-obvious fact while working in this project:
1. Find the entity page that fact belongs to. Create it if missing.
2. Update the page (edit `Updated:` date, edit `Key facts`).
3. Add a one-line entry to `log.md` (`YYYY-MM-DD: <what changed> — <page>`).
4. If you created a new page, add a one-line entry to `index.md`.

**Query** — Before asking the user to re-explain something, grep this wiki.
If you find an answer here, cite the page in your response. If you derive a
better answer than the page contains, *update the page*.

**Lint** — Periodically (or when asked):
- Find orphaned pages (not linked from `index.md` or any other page).
- Find dangling `[[wiki-links]]` (target file does not exist).
- Find stale pages (`Updated:` > 90 days old) and verify or refresh them.
- Find contradictions between pages and flag them.

## What does NOT go here

- **Code** — code lives in the project root. Pages link to code, not duplicate it.
- **Per-session todo lists** — use `TaskCreate`, not the wiki.
- **Conversation snippets** — distill the *fact*, not the dialogue.
- **Private/cross-project preferences** — those go in `~/.claude/.../memory/MEMORY.md`,
  which is per-user and persistent across all projects. The wiki is per-project
  and shared across collaborators (in principle).

## Boundary with other persistence

| Surface | Scope | Lifetime |
|---|---|---|
| `wiki/` (this folder) | This project, shared | Permanent |
| `~/.claude/.../memory/` | Per user, all projects | Permanent |
| `~/.claude/plans/` | One implementation task | Per task |
| `TaskCreate` todos | One conversation | Per session |
| `program.md` | Single-knob scan spec (legacy) | Stable |
