---
type: incident
title: prodtarget mode preflight + grid silently ran stock MDC2025aq for weeks
description: patched `autoresearch_muse_prodtarget` workdir (% 02d rename + NIEL
  SD + spacer-shrink) was reached by NEITHER preflight (Run1Bak/p094) NOR grid (backing-only
  tarball); **resolved 2026-06-08** via per-mode `MUSING_BY_MODE` dispatch + workdir-level
  `setup_local.sh` + grid tarball rebuild from patched workdir
status: resolved
status_note: (2026-06-08)
timestamp: '2026-06-08'
---

# prodtarget mode preflight + grid silently ran stock MDC2025aq for weeks

## Summary

The patched workdir `autoresearch_muse_prodtarget` (% 02d plate rename,
NIEL SD, spacer-shrink overlap fix) was being **reached by neither
preflight nor grid**. All prodtarget validation up to 2026-06-08 ran
against stock MDC2025aq — every "Stickman SD ships nonzero edep" and
every "preflight fails 5 overlaps" claim was answered by libs that
contained none of our patches.

Three cascading misalignments:

| Surface | Source script | Envset / Offline version | What it pointed at |
|---|---|---|---|
| Preflight | `graph/config.py:19 MUSING` | p094 / Offline v13_12_10 | `Musings/SimJob/Run1Bak/setup.sh` |
| Grid | `pipeline.py:194 code_tarball` | p101 / Offline v13_18_00 | `autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2` |
| Patched workdir | `autoresearch_muse_prodtarget/Offline/.muse` | p101 / Offline v13_18_00 | (built locally, referenced by NONE of the above) |

`tar tjf Code_MDC2025aq_prodtarget.tar.bz2` confirmed the grid tarball
shipped only `Code/setup.sh + Code/backing -> /cvmfs/.../MDC2025aq`.
Zero patched libs.

## Fix

**1. Per-mode MUSING dispatch in `graph/config.py`** (the original
`MUSING = "/cvmfs/.../Run1Bak/setup.sh"` was a single global):

```python
MUSING_BY_MODE = {
    "michael":    ".../Musings/SimJob/Run1Bak/setup.sh",
    "helical":    ".../Musings/SimJob/Run1Bak/setup.sh",
    "foils":      ".../Musings/SimJob/Run1Bak/setup.sh",
    "foilsf":     ".../Musings/SimJob/Run1Bak/setup.sh",
    "prodtarget": "/exp/.../autoresearch_muse_prodtarget/setup_local.sh",
}
MUSING = MUSING_BY_MODE[os.environ.get("AUTORESEARCH_MODE", "michael")]
```

The top-level `MUSING` survives for `pipeline.py` import-time consumers
(`graph/run.py` and `graph/closed_loop.py` already presniff
`--mode` and stamp `AUTORESEARCH_MODE` BEFORE importing config —
load order matters).

**2. BO driver resolves Musing per-call** (it gets `--mode` as a CLI arg,
not via env):

```python
from config import MUSING_BY_MODE  # was: MUSING
musing = MUSING_BY_MODE[mode.name]
bash_cmd = f"source {SETUPMU2E}... && source {musing}..."
```

**3. Drop a workdir-level setup.sh that sources `muse setup` against
the patched workdir** (CODE_DIR-relative, mirrors the
`Musings/SimJob/.../setup.sh` pattern):

```bash
# /exp/.../autoresearch_muse_prodtarget/setup_local.sh
CODE_DIR=$(dirname $(readlink -f $BASH_SOURCE))
muse setup $CODE_DIR
```

After sourcing, `which mu2e` resolves to the workdir's local
`build/al9-prof-e29-p101/Offline/bin/mu2e` and `libmu2e_Mu2eG4.so`
loads from the local lib by muse link order.

**4. Rebuild the grid tarball from the patched workdir** so the grid
ships local libs (was: backing-only):

```bash
cd /exp/.../autoresearch_muse_prodtarget
muse setup && muse tarball
cp /exp/mu2e/data/users/oksuzian/museTarball/tmp.*/Code.tar.bz2 \
   /exp/.../autoresearch_muse/Code_MDC2025aq_prodtarget.tar.bz2
```

Size: 100 KB → 687 MB (includes entire Offline source + p101 build).

## Non-obvious traps

- **`muse tarball` collides with a workdir-level `setup.sh`** — it
  renames the existing one to `setup.sh-<timestamp>` and writes its
  own (with `-q p101 e29 prof` quals). Our entry point must therefore
  be `setup_local.sh`, not `setup.sh`. Verified by failure: the first
  preflight after rebuilding the tarball complained
  `bash: line 1: /exp/.../autoresearch_muse_prodtarget/setup.sh: No
  such file or directory`.

- **`muse` is a shell function, not a binary** — it becomes defined
  only after sourcing `setupmu2e-art.sh`. There is no `mu2einit`
  command in this env (despite Mu2e wiki docs). `muse setup` followed
  by `muse build` (or `muse tarball`) must run in the same bash
  heredoc; `bash -lc` between them loses `MUSE_WORK_DIR`.

- **Muse "unexpected link order" warning is benign here**: the workdir
  has only a local `Offline` checkout that supplements MDC2025aq's
  backing, which provides TrkAna. We don't build TrkAna, so the
  "Offline upstream of TrkAna" complaint is harmless. Silenceable
  with `muse/linkOrder` if it becomes noise.

## Verification

After the fix, `AUTORESEARCH_MODE=prodtarget python autoresearch_bo_michael.py
--mode prodtarget preflight pt001` returns rc=0, "managed=0" — the
spacer-shrink fix in the patched workdir is now actually reached.

## Cross-links

- Related: [prodtarget-spacer-supportring-overlap](/incidents/prodtarget-spacer-supportring-overlap.md) (the bug whose
  fix was being silently bypassed), [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md), [foilsg-grid-tarball-scalar-holeradius-fallback](/incidents/foilsg-grid-tarball-scalar-holeradius-fallback.md)
- Related: [muse-backing-pattern](/external/muse-backing-pattern.md) (general muse layering pattern)
- Related: [venv-relocated-to-data-volume](/incidents/venv-relocated-to-data-volume.md) (sister env-source
  surprise)
- Source: `graph/config.py:18-32`, `autoresearch_bo_michael.py:99,1471`,
  `pipeline.py:194`, `autoresearch_muse_prodtarget/setup_local.sh`

## Open questions / TODO

- [ ] Audit whether any other mode (`foils`, `foilsf`) silently
  depends on a workdir that isn't being shipped to the grid.
