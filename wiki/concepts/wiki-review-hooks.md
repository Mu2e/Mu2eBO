---
type: concept
title: Wiki-review hooks (Claude Code Stop hook contract)
description: Stop hook must emit `{"decision":"block","reason":...}` JSON + check
  `stop_hook_active` guard to actually feed back to the model; plain echo / stderr
  are invisible
status: dormant
status_note: all three hooks PARKED 2026-07-17 per user request; see Key facts for re-enable recipe
timestamp: '2026-07-17'
---

# Wiki-review hooks (Claude Code Stop hook contract)

## Summary
The project's wiki-maintenance discipline is enforced via Claude Code hooks
configured in `.claude/settings.local.json`. Two earlier attempts (plain
`echo` in Stop, `echo ... >&2` in PostToolUse) were operationally invisible
to the model — the model never saw the reminder and never wrote to the wiki
at end of turn. The working pattern is a Stop hook that emits the JSON
envelope `{"decision":"block","reason":"..."}` so the reason is fed back as
a follow-up turn, plus a `stop_hook_active` guard to break the loop after
the review.

## Key facts

- **PARKED 2026-07-17** ("stop wiki hooks for now"): all three hook
  registrations (PreCompact / Stop / PostToolUse) were moved out of
  `.claude/settings.local.json` (now `"hooks": {}`) into
  `.claude/hooks/wiki-hooks.settings.parked.json`, and
  `wiki_review_stop.sh` got an early `exit 0` guard (belt-and-suspenders:
  hook *registrations* are snapshotted at session start, but the Stop
  *script* is re-read every invocation — the script edit is what disables
  it mid-session). **Re-enable:** copy the `hooks` object back into
  settings.local.json AND delete the `exit 0` guard line. The wiki
  maintenance contract in `wiki/CLAUDE.md` still applies — only the
  forced reminders are off.
- **Stop hook delivery contract (Claude Code):**
  - `echo "..."` from a Stop hook is shown to the *user* and does NOT feed
    back to the model. The model stops normally.
  - JSON `{"decision":"block","reason":"..."}` on stdout DOES feed `reason`
    back to the model as a new user turn (the model is forced to continue).
  - To prevent infinite loops, the second invocation receives stdin with
    `"stop_hook_active": true`. The hook must detect this and exit 0
    (allow) on that pass.
- **PostToolUse delivery:** `echo ... >&2` is NOT shown to the model (stderr
  is captured but not piped into the turn). Use stdout + JSON envelope, or
  don't bother. Plain stdout is shown to the user only.
- **Working hook script:**
  `/exp/mu2e/app/users/oksuzian/autoresearch/.claude/hooks/wiki_review_stop.sh`
  — reads stdin, greps for `"stop_hook_active"[[:space:]]*:[[:space:]]*true`,
  exits 0 if matched, else emits the block JSON. Wired into Stop hook in
  `.claude/settings.local.json:139-148`.
- **Hook smoke test (local, no Claude needed):**
  ```bash
  echo '{"stop_hook_active": false}' | .claude/hooks/wiki_review_stop.sh  # emits JSON
  echo '{"stop_hook_active": true}'  | .claude/hooks/wiki_review_stop.sh  # silent, exit 0
  ```
- **Reason-text design:** the reason must tell the model exactly what to
  scan for, what bar to apply (>5-min-to-rederive), and give it an explicit
  escape hatch (`NO-OP (nothing new this turn)`) so it doesn't fabricate
  wiki entries from trivial turns. Without the escape hatch the model
  invents content to justify the block.
- **PreCompact hook** (lines 117-127): plain `echo` is *fine* there — the
  PreCompact reminder runs while the model is still in the loop, and shows
  up as context for the next pre-compression action. It does not need to
  block. No SessionStart hook is wired (the prior `python3 wiki/lint.py`
  one was removed 2026-05-23 when the linter was migrated to pure-LLM
  `/wiki-lint`; an LLM call on every session start was too expensive).

## Cross-links
- Source files: `/exp/mu2e/app/users/oksuzian/autoresearch/.claude/settings.local.json:139-148`,
  `/exp/mu2e/app/users/oksuzian/autoresearch/.claude/hooks/wiki_review_stop.sh`
- Related: [CLAUDE](/CLAUDE.md) (the wiki maintenance contract that this hook enforces)
- External: [Claude Code hooks reference](https://docs.claude.com/en/docs/claude-code/hooks)

## Open questions / TODO
- Add a token-budget check: if the turn-so-far token count exceeds some
  threshold, the wiki-review reminder is high-value; for very short
  conversational turns it just burns context. Could grep the input JSON
  for transcript length.
- Consider a PostToolUse JSON-envelope variant for Bash/Edit tool calls
  that produced load-bearing facts, so the reminder fires closer to the
  source of the fact (PreCompact + Stop are end-of-window).
