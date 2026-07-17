---
type: schema
title: LLM Wiki — OKF v0.1 schema and maintenance contract
description: The rules for how wiki entries are shaped and maintained (Open
  Knowledge Format v0.1 bundle).
timestamp: '2026-07-17'
---

# LLM Wiki — OKF schema and maintenance contract

This folder is a **persistent, AI-maintained knowledge base** for the
`/exp/mu2e/app/users/oksuzian/autoresearch` project. It is an
**[Open Knowledge Format v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle** — OKF is the open-spec formalization of the
[Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
this wiki originally followed (converted 2026-07-17; see
[open-knowledge-format](/external/open-knowledge-format.md)).

The wiki is the *compounding artifact* of this project: facts, decisions, and
mental models that would otherwise live only in chat history or git commit
messages. Every Claude session that touches this project should read this file
first and update the wiki when it learns something the wiki doesn't already
know.

## Three-layer architecture

1. **Raw sources** — code, logs, leaderboards, summary.json files, mmackenz
   workflow tree. Immutable from the wiki's perspective.
2. **The wiki** (this folder) — an OKF bundle of markdown concept pages with
   YAML frontmatter, indexed by `index.md`, journaled by `log.md`.
3. **Schema** (this file) — rules for how entries are shaped and maintained.

## Folder layout

```
wiki/
├── CLAUDE.md          # this schema + contract
├── index.md           # reserved OKF index: one-line pointer per page (root declares okf_version)
├── log.md             # reserved OKF log: date-grouped changelog, NEWEST FIRST
├── projects/          # active research lines
├── concepts/          # physics + software concepts
├── datasets/          # priors, leaderboards, summary files
├── drivers/           # the executable scripts and their roles
├── incidents/         # bugs, gotchas, surprising failures, root causes
└── external/          # pointers to external repos, docs, specs
```

## Page format (OKF concept document)

Every entity page = YAML frontmatter + markdown body:

```markdown
---
type: project | concept | dataset | driver | incident | external
title: Human-readable name
description: One-line summary (mirrors the index.md one-liner)
status: active | dormant | resolved | superseded | open | recurring
status_note: optional free-text qualifier (dates, context)
timestamp: 'YYYY-MM-DD'          # last-modified date — bump on every edit
updated_note: optional free-text qualifier for the last update
---

# <Title>

## Summary
One-paragraph elevator pitch. What is this and why does it matter.

## Key facts
- Load-bearing facts (file paths, parameter ranges, magic numbers).
- Each fact should take >5 min to re-derive from raw sources.

## Cross-links
- Related: [other-page](/concepts/other-page.md), [another](/incidents/another.md)
- Source files: `path/to/file.py:LINE`
- External: [link](url)

## Open questions / TODO
- Anything unresolved. Empty section is fine.
```

Rules:
- `type` is REQUIRED (OKF conformance) and must match the parent folder
  (projects/→project, concepts/→concept, datasets/→dataset, drivers/→driver,
  incidents/→incident, external/→external).
- `status` vocabulary: active | dormant | resolved | superseded | open |
  recurring. Put qualifiers in `status_note`, keep `status` a bare enum.
- **Cross-links are bundle-relative markdown links**: `[stem](/folder/stem.md)`.
  Do NOT use the old `[[stem]]` wiki-link syntax — it was retired at the OKF
  conversion. Link text is usually the stem; prose-friendly text is fine too.
- `index.md` and `log.md` are OKF-reserved at every level; only the root ones
  exist here. Root `index.md` frontmatter declares `okf_version: "0.1"`.

## Maintenance loop

**Ingest** — When you learn a non-obvious fact while working in this project:
1. Find the entity page that fact belongs to. Create it if missing.
2. Update the page (bump `timestamp`, edit `Key facts`; keep `description`
   in sync with the index one-liner).
3. Add a bullet to `log.md` **under today's `## YYYY-MM-DD` heading at the
   TOP of the file** (create the heading if absent — newest first, per OKF).
4. If you created a new page, add a one-line entry to `index.md`.

**Query** — Before asking the user to re-explain something, grep this wiki.
If you find an answer here, cite the page in your response. If you derive a
better answer than the page contains, *update the page*.

**Lint** — Run `/wiki-lint` (see `.claude/commands/wiki-lint.md`):
- OKF conformance: frontmatter parses, `type` present + folder-matched.
- Broken markdown links (tolerated by OKF consumers, but we fix ours).
- Orphans, stale timestamps (>90d), missing backlinks, index completeness.
- Semantic pass: contradictions, decaying claims, missing cross-references.

## What does NOT go here

- **Code** — code lives in the project root. Pages link to code, not duplicate it.
- **Per-session todo lists** — use `TaskCreate`, not the wiki.
- **Conversation snippets** — distill the *fact*, not the dialogue.
- **Private/cross-project preferences** — those go in `~/.claude/.../memory/`,
  which is per-user and persistent across all projects. The wiki is per-project
  and shared across collaborators (in principle — and, as an OKF bundle, any
  OKF consumer can now read it).

## Boundary with other persistence

| Surface | Scope | Lifetime |
|---|---|---|
| `wiki/` (this folder) | This project, shared | Permanent |
| `~/.claude/.../memory/` | Per user, all projects | Permanent |
| `~/.claude/plans/` | One implementation task | Per task |
| `TaskCreate` todos | One conversation | Per session |
