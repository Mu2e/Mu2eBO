---
type: incident
title: Stale torch cpp_extension FileBaton lock hangs the unittest suite indefinitely
description: a killed process can orphan ~/.cache/torch_extensions/py311_cpu/logei_fused_ext/lock; torch's FileBaton spin-waits on it forever, so the ~15 s suite HANGS (not fails) with no output — delete the lock file
status: resolved
status_note: 2026-08-01 — stale lock removed; recurs whenever a suite/import is killed mid-JIT-compile
timestamp: '2026-08-01'
---

# Stale torch cpp_extension FileBaton lock hangs the unittest suite indefinitely

## Summary

During the IPA-option fix wave (2026-08-01), `unittest discover` runs that
normally finish in ~15 s hung indefinitely with zero output — across
multiple fresh shells, looking exactly like a wedged filesystem or an
infinite test. Root cause: botorch's fused-LogEI JIT extension build takes
a `FileBaton` lock at
`~/.nashome …/.cache/torch_extensions/py311_cpu/logei_fused_ext/lock`;
a prior suite process had been killed mid-compile and left the lock file
behind. `FileBaton.wait()` is a bare `while os.path.exists(lock): sleep()`
spin — no timeout, no staleness check, no owner-pid — so every later
import that triggers the extension build waits forever, silently.

## Key facts

- Symptom: suite (or any `import` reaching botorch's fused acquisition
  path) produces NO output and never exits; CPU near zero. It looks like
  NFS trouble but is a single local lock file.
- Fix: delete the lock file
  (`~/.cache/torch_extensions/py311_cpu/logei_fused_ext/lock`). Safe when
  no live process is actually compiling (check `ps` for a compiler/ninja).
- Cause of orphaning: any SIGKILL of a process mid-JIT-compile — killed
  subagents, `timeout`-cut Bash calls, session reaping. The 2026-08-01
  lock's mtime matched a suite run killed by an agent harness ~30 min
  earlier.
- torch's `FileBaton` has no staleness detection by design
  (`torch/utils/cpp_extension.py`); the hang recurs whenever the kill
  scenario repeats.
- Diagnosis recipe: when the suite hangs with no output, check
  `~/.cache/torch_extensions/*/*/lock` mtimes BEFORE suspecting NFS; a
  lock older than the newest python process is stale.
- Note the cache lives on /nashome (NFS) — distinct failure family from
  [nfsv4-badseqid-lock-wedge-nashome](/incidents/nfsv4-badseqid-lock-wedge-nashome.md)
  (that one is fcntl/BAD_SEQID; this one is a plain exists()-spin on an
  orphaned file), but the same "lock debris on a shared home" theme.
  `SPACK_USER_CACHE_PATH`-style relocation would also help here
  (`TORCH_EXTENSIONS_DIR` → /tmp) if it recurs often.

## Cross-links

- Related: [nfsv4-badseqid-lock-wedge-nashome](/incidents/nfsv4-badseqid-lock-wedge-nashome.md),
  [tests](/drivers/tests.md)
- Source files: `.venv` botorch fused-LogEI JIT path;
  `torch/utils/cpp_extension.py` (`FileBaton`)

## Open questions / TODO

- If it recurs: set `TORCH_EXTENSIONS_DIR=/tmp/torch_ext_$USER` in the
  test/campaign environment to move the lock off NFS and make debris
  per-node.
