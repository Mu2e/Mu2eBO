# autoresearch — project instructions

This project has a **persistent LLM wiki** at `wiki/`. Read it before starting
work, and update it when you learn something non-obvious.

## Wiki contract (must-read)

@wiki/CLAUDE.md

## Wiki catalog

@wiki/index.md

## When to update the wiki

Update a wiki page (and append one line to `wiki/log.md`) whenever you learn
a fact that:

- Took >5 min to derive from raw sources, OR
- A future session would otherwise have to re-derive, OR
- Is a root-cause for a bug or a magic number you didn't know before.

Do not write to the wiki for ephemeral task state — that goes in `TaskCreate`,
not the wiki. Do not duplicate code into wiki pages — link to it.

## Linting

Run `/wiki-lint` to audit the wiki (dangling `[[wiki-links]]`, orphans, stale
`Updated:` dates, schema conformance, missing backlinks, and semantic checks
for contradictions and decaying claims). The check is pure-LLM — no helper
script — to match the dominant Karpathy-wiki convention. Pass `--quick` to
skip the semantic pass.

## Agent skills

### Issue tracker

GitHub Issues at github.com/oksuzian/Mu2eBO via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
