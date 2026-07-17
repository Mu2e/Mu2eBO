# autoresearch — project instructions

This project has a **persistent LLM wiki** at `wiki/`. Read it before starting
work, and update it when you learn something non-obvious.

## Wiki contract (must-read)

@wiki/CLAUDE.md

## Wiki catalog

@wiki/index.md

## When to update the wiki

Update a wiki page (and add a `wiki/log.md` bullet under today's date heading
at the TOP — the log is newest-first per OKF) whenever you learn a fact that:

- Took >5 min to derive from raw sources, OR
- A future session would otherwise have to re-derive, OR
- Is a root-cause for a bug or a magic number you didn't know before.

Do not write to the wiki for ephemeral task state — that goes in `TaskCreate`,
not the wiki. Do not duplicate code into wiki pages — link to it.

## Linting

The wiki is an **OKF v0.1 bundle** (converted 2026-07-17): YAML frontmatter +
bundle-relative markdown links. Run `/wiki-lint` to audit it (broken links,
orphans, stale `timestamp:` fields, OKF conformance, missing backlinks, and
semantic checks for contradictions and decaying claims). The check is
pure-LLM — no helper script. Pass `--quick` to skip the semantic pass.

## Agent skills

### Issue tracker

GitHub Issues at github.com/oksuzian/Mu2eBO via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
