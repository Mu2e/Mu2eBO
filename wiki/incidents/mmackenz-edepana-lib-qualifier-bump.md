# EdepAna harvest broke — mmackenz rebuilt Run1BAna p094→p101 (hardcoded lib path died)

**Type:** incident
**Status:** RESOLVED 2026-06-26 — EdepAna built into our own muse, pipeline repointed; verified by manual harvest AND a live campaign (foilsf26 R0 +10 rows clean, vs foilsf25 all-metrics_none); no longer depends on mmackenz's area
**Updated:** 2026-06-26

## Summary
All foils + ipa harvests started failing at the EdepAna step (`rc=9`, art config
error: `Library specification "EdepAna" does not correspond to any library in
CET_PLUGIN_PATH of type "module"`) → `harvest_exception` → `metrics_none` → zero
rows → closed-loop "all failed, exiting early" at R0. **Nothing changed on our
side.** Root cause: the EdepAna module is loaded from a **hardcoded path in
mmackenz's build area** (`pipeline.py:360`), and he **rebuilt Run1BAna on
2026-06-25 with a new release qualifier**, deleting the old path we point at.

## Key facts
- **Harvest EdepAna source = external mmackenz lib, prepended to CET_PLUGIN_PATH**
  (`pipeline.py:350-365`, `sourced_env(with_muse=True)`):
  `mmlib = /exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/Run1BAna/lib`.
  Comment there: "His HEAD doesn't match v13_12_10 ABI, so we can't rebuild
  Run1BAna locally without effort" — i.e. we deliberately depend on HIS build.
- **The p094 path is now GONE.** mmackenz's `run1b/build/` (mtime 2026-06-25) now
  holds **`al9-prof-e29-p101`** (+ an `include`), NO `al9-prof-e29-p094`. He bumped
  the Offline release qualifier p094→p101.
- **EdepAna DOES exist in the new p101 build:**
  `…/al9-prof-e29-p101/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so`
  (note: `_workflows_`, not `_modules_`; dated 06-25).
- **ABI mismatch risk:** our `autoresearch_muse` is built `al9-prof-e29-p094`
  (`autoresearch_muse/build/al9-prof-e29-p094`). Loading a p101-built module into
  our p094 art/ROOT base may or may not work — needs a test before trusting.
- **Only foils + ipa break** (both need EdepAna for `s_over_sqrt_b`).
  **prodtarget6d is immune** — its `pot_only` harvest uses uproot/ReadVirtualDetector,
  no EdepAna; pt6d16 completed fine (323 rows) the same day.
- **NOT caused by the 2026-06-24 /app cleanup** (deleting muse_101323/muse_080224)
  — those are unrelated to mmackenz's area; foilsf24 harvested fine AFTER that
  cleanup using the then-still-present p094 path.

## Building EdepAna into our muse (2026-06-26) — the "can't rebuild locally" detail
Our `autoresearch_muse/Run1BAna/workflows/src/EdepAna_module.cc` is IDENTICAL to
mmackenz's (`diff` empty); package uses **SCons** (`workflows/src/SConscript`,
standard `make_plugins`), not CMake. A full `muse build` **FAILS (rc=2)** — but
NOT on EdepAna: the unrelated sub-package **`Run1BAna/evtana`** needs
`EventNtuple/inc/{HitCount,TrkInfo}.hh`, an `EventNtuple` package NOT in our
backing → scons stops on that error before reaching `workflows/`. **That** is the
"his HEAD doesn't match / can't rebuild locally" friction (`pipeline.py:356`).
**EdepAna_module.cc itself has NO EventNtuple dep** — only Offline
(RecoDataProducts/MCDataProducts/Mu2eUtilities) + art + ROOT, all in our p094
muse. So build ONLY the EdepAna target, skipping evtana:
`scons build/al9-prof-e29-p094/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so`
(under `muse setup -q p094`). Produces the .so in OUR lib → harvest can drop the
mmlib prepend (or point it at our own build).

## Fix APPLIED 2026-06-26 (the build route, not the p101 repoint)
- **Built EdepAna into our own muse** (rc=0): `muse setup -q p094` then
  `muse build -j4 build/al9-prof-e29-p094/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so`
  → 1.5 MB .so in our p094 lib, compiled cleanly (no ABI issue; the "can't
  rebuild" was only the evtana/EventNtuple sub-package — pass the explicit target
  to skip it; raw `scons` fails with "No SConstruct" — MUST go through `muse build`).
- **Repointed `pipeline.py:360`** `mmlib` from mmackenz's dead p094 path →
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib`
  (our own). No longer depends on mmackenz's area for the harvest.
- **VERIFIED end-to-end**: test-harvest of foilsf25R00_00 (existing /pnfs outputs)
  produced `s_over_sqrt_b=1.9` (ce_seen=187375). EdepAna loads from our lib. DONE.
- **No grid-tarball rebuild needed**: EdepAna runs ONLY in the LOCAL harvest
  (`sourced_env(with_muse=True)`), not in any grid stage — the worker
  `Code.tar.bz2` never invokes EdepAna. So this harvest-side fix fully covers it;
  just relaunch foils/ipa.

## (superseded) Fix (the p101 repoint option, NOT taken)
1. Repoint `pipeline.py:360` `mmlib` `…p094…`→`…p101…`.
2. **TEST the ABI** non-destructively before relaunching: foilsf25's stage outputs
   already exist on /pnfs, so re-run only the harvest for one child
   (`pipeline.py --config foilsf25R00_00 harvest`, or the recovery path) with the
   repointed lib and confirm EdepAna loads + "Saw N events" appears.
3. If p101 module fails to load under p094 muse → rebuild `autoresearch_muse` to
   p101 (matches mmackenz) OR build EdepAna ourselves.
4. **Longer-term:** stop hardcoding a qualifier-specific path under another user's
   build. Make `mmlib` discover the latest `…/Run1BAna/lib` (glob the build dir)
   or pin a copy of the EdepAna .so into our own tree.

## Cross-links
- Related: [[muse-backing-pattern]], [[sourced-env-stderr-swallowed]],
  [[mmackenz-table-plots-dir]] (other off-repo mmackenz dependencies), [[edepana-saw-events-scientific-notation-parse]], [[elebeamcat-tape-migration-elebeam-wipeout]]
- Reference: `reference_run1bana_repo` (EdepAna is in github.com/michaelmackenzie/Run1BAna)
- Source: `pipeline.py:350-365` (mmlib + CET_PLUGIN_PATH prepend), `:1110-1127`
  (EdepAna invocation, rc check)

## Open questions / TODO
- Does p101 EdepAna load under p094 muse? (the test above)
- Will mmackenz keep bumping qualifiers? → motivates the discover-or-vendor fix.
