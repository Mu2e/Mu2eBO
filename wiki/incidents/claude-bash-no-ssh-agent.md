---
type: incident
title: claude-bash-no-ssh-agent — Bash-tool subshells can't reach user's ssh-agent
description: Bash-tool subshells can't reach user's `ssh-agent`; `git push` to GitHub
  fails for Claude even when it works in user's interactive shell
status: active
status_note: (general SSH limitation) — but RESOLVED for Mu2eBO via HTTPS remote
timestamp: '2026-06-02'
---

# claude-bash-no-ssh-agent — Bash-tool subshells can't reach user's ssh-agent

## CONFIRMED: Claude CAN push to Mu2eBO (2026-06-02)
The `git push origin main` workaround on lines 67–73 is **live and proven**:
Mu2eBO's `origin` is now `https://github.com/oksuzian/Mu2eBO.git` (HTTPS) with
cached credentials, and **`git push origin main` succeeded directly from the
Claude Bash tool** (pushed `387b3bb..2badabf`). So for THIS repo, do NOT hedge
"I can't push" — just push. The ssh-agent limitation below only bites for
`git@github.com:` (SSH) remotes; Mu2eBO no longer uses one.

## Summary
The user's interactive gpvm shell has a working `ssh-agent` (forwarded from
laptop via `ssh -A`, or started by a long-lived screen/tmux), so
`git push` to GitHub via `git@github.com:...` Just Works for them. But
Claude's Bash tool launches subprocesses that do NOT inherit
`SSH_AUTH_SOCK`, and even when the env var IS set in the subshell, the
socket path resolves to "No such file or directory" — agent inherits
through real `ssh -A` parentage, not via env-var copy. Net effect:
Claude cannot `git push` on the user's behalf even though the user can.

## Root cause
`ssh-agent` uses a Unix-domain socket whose access is bounded by the
session/uid that created it. Bash-tool subprocesses are spawned by the
Claude CLI as a sibling of the user's interactive shell, not as a
descendant — so the kernel's session-keyring + socket-perm chain that
makes the agent reachable from the user's shell doesn't extend to
Claude's subshell.

## Workarounds (in order of preference)

1. **User runs the push themselves.** Claude stages files + commits +
   provides the exact `git push` / `gh repo create` lines; user
   executes them in their own shell. Cleanest, no auth fight.

2. **User starts a path-pinned agent Claude can reach:**
   ```bash
   eval $(ssh-agent -s -a /tmp/ssh-oksuzian-agent)
   ssh-add ~/.ssh/id_ed25519
   chmod 660 /tmp/ssh-oksuzian-agent   # if needed
   ```
   Then Claude can `SSH_AUTH_SOCK=/tmp/ssh-oksuzian-agent git push`.
   Survives across Bash subshells for the agent's lifetime.

3. **Personal Access Token via gh CLI:**
   ```bash
   echo "ghp_xxx..." | gh auth login --with-token
   ```
   Persists in `~/.config/gh/hosts.yml` across sessions; Claude can
   then use `gh repo create` and HTTPS `git push`.

4. **HTTPS push with embedded PAT** — `git push https://oksuzian:ghp_xxx@github.com/owner/repo.git`.
   Token leaks into shell history; only do this for one-off pushes.

## Key facts

- **`gh auth status` shows `not logged into any GitHub hosts`** by
  default on a fresh Claude session, even though the user can
  `git push` from their own shell. The two auth surfaces are
  independent.
- **Three candidate SSH keys exist** at `~/.ssh/`:
  `id_ed25519` (newest), `github_rsa`, `id_rsa`. **All three are
  passphrase-protected** (confirmed 2026-05-29 via
  `ssh-keygen -y -P "" -f <key>` returning "incorrect passphrase
  supplied to decrypt private key" on each). Without the agent
  unlocking one, `ssh -i ~/.ssh/<key>` fails `Permission denied
  (publickey)` non-interactively.
- **No `~/.netrc` and no `~/.git-credentials`** as of 2026-05-29, so
  HTTPS fallback also requires explicit setup. `gh auth login` +
  `gh auth setup-git` is the cleanest path to making future Claude
  pushes Just Work.
- **`gh auth setup-git` alone is NOT enough** (confirmed 2026-05-29
  on Mu2eBO): gh's credential helper only intercepts HTTPS git
  operations. If the remote is `git@github.com:...` (SSH), gh is
  bypassed and push still hits `Permission denied (publickey)`. Fix:
  `git remote set-url origin https://github.com/<owner>/<repo>.git`
  after `gh auth login`. From then on, push from Claude's subshell
  works without any agent.
- **User's interactive `$SSH_AUTH_SOCK` lives at
  `/tmp/ssh-XXXXv4gZfn/agent.<pid>`** — but copying that path into a
  Bash-tool subshell still produces `Error connecting to agent: No
  such file or directory`. Don't waste time trying to inherit it;
  use workaround 1, 2, or 3.

## Cross-links
- Related: [slack-bot-dm-channel-not-found](/incidents/slack-bot-dm-channel-not-found.md) (parallel pattern —
  different auth identities, can't piggyback on each other's session)
- External: [GitHub SSH key setup](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)

## Open questions / TODO
- Test whether `agent.<pid>` becomes reachable if the user `chmod a+rwx`
  the parent `/tmp/ssh-XXXX*/` dir — gpvm `/tmp` is shared, so this
  might be a perm rather than a session issue.
