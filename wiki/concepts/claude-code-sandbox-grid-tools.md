---
type: concept
title: Claude Code Bash sandbox vs grid tools
description: 'Claude Code''s Bash sandbox breaks kinit + jobsub_q on mu2esrv01 (no DNS, HTTP-only proxy); grid commands need excludedCommands'
status: active
status_note: measured 2026-09-30 on mu2esrv01, Claude Code 2.1.286
timestamp: '2026-10-08'
---

# Claude Code Bash sandbox vs grid tools

## Summary
Claude Code's built-in sandbox (`/sandbox`, `sandbox.enabled`) runs each Bash
command in a bubblewrap jail with its own network namespace. The only way out
is an HTTP/HTTPS proxy on `localhost:3128` that checks an allowlist of domains.
Kerberos and grid tooling need raw DNS plus non-HTTP TCP/UDP. With the sandbox
on, `kinit` and `jobsub_q` both fail, and allowlisting `*.fnal.gov` does not
change that. For this project the sandbox is only usable with the grid commands
listed in `excludedCommands`, which runs them unsandboxed. At that point it no
longer contains the commands with the largest blast radius.

## Key facts
- Host prerequisites are present on mu2esrv01: `/usr/bin/bwrap`,
  `/usr/bin/socat`, and unprivileged user namespaces
  (`user.max_user_namespaces = 28633`).
- The test was a headless `claude -p` with `--settings
  '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false}}'` running one
  script. The results were the same with `network.allowedDomains:
  ["fnal.gov","*.fnal.gov"]` + `filesystem.allowWrite: ["/tmp"]`:
  - `getent hosts htvaultprod.fnal.gov` prints nothing. There is **no DNS**
    inside the sandbox netns.
  - `klist` works, because reads are allowed everywhere by default.
  - `kinit -R` fails with `kinit: Resource temporarily unavailable while
    renewing credentials`. The KDC is unreachable.
  - `jobsub_q -G mu2e --user oksuzian` fails. `htgettoken` Kerberos negotiate
    dies with `gaierror: [Errno -3] Temporary failure in name resolution`. It
    needs DNS for the SPN even when an HTTPS proxy is set. Condor schedd
    traffic is not HTTP either.
  - The same `jobsub_q` outside the sandbox succeeds in 1.3 s.
- By default the sandbox makes `/tmp` read-only (`touch` fails with
  `Read-only file system`). `TMPDIR` is rewritten to `/tmp/claude-<uid>`.
  `jobsub_lite` writes `/tmp/bt_token_mu2e_Analysis_<uid>`, so it would also
  need `allowWrite`.
- The sandbox exports `HTTP(S)_PROXY`/`ALL_PROXY` with credentials embedded in
  the URL. jobsub_lite's opentelemetry Jaeger exporter then throws `TypeError:
  a bytes-like object is required, not 'str'` in `basic_proxy_auth_header`.
  This is noise, not the failure cause.
- The host ticket cache was untouched: the failed renew never reached the
  write.
- Scope reminder from the docs: the sandbox covers Bash only. Read, Edit and
  Write go through permission rules, and the default read policy is the whole
  machine.

## Cross-links
- Related: [grid-job-completion-check](/incidents/grid-job-completion-check.md),
  [kerberos-mid-run-expiry](/incidents/kerberos-mid-run-expiry.md)
- Alternative: claudebox (Apptainer wrapper; state in
  `/exp/mu2e/app/users/oksuzian/claudebox/`, bind recipe in
  `mu2e-review/memory/reference_claudebox_bind_requirements.md`). It isolates
  every tool by bind list, but the shared host network means it has no network
  isolation.
- External: https://code.claude.com/docs/en/sandboxing

## Open questions / TODO
- An xrootd `root://` read and `muse setup` under the sandbox were not tested.
  xrootd is expected to fail the same way (no DNS, non-HTTP).
