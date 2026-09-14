---
type: external
title: muse-backing-pattern — build a patched Offline subset against a Musing
description: build patched Offline subset against a Musing; how the helical-plug
  lib is produced
status: active
timestamp: '2026-08-18'
updated_note: rewrote the Run1BAna section — it still claimed the local build had failed
  and that we borrow mmackenz's lib, both false since 2026-06-26; documented multi-repo
  work areas as the extra-module mechanism, the one-target build, and the diverged
  second clone that feeds the harvest fcl/macro
---

# muse-backing-pattern — build a patched Offline subset against a Musing

## Summary

How to rebuild one or more Offline `.so` libraries with local patches while
inheriting everything else from a published Musing on CVMFS. Used to ship the
helical-plug `libmu2e_Mu2eG4.so` patch via `Code.tar.bz2` without needing
mmackenz's tree or new CVMFS publication.

## PREFERRED recipe: tag-pinned partial checkout (2026-07-28)

Use this when the backing is a **published tag** (all our Musings are). It is
the mu2ewiki "Partial checkout with backing build" flow with `mgit init`
replaced by a tag clone. Measured on Run1Bap/p101: **2 libs, 26 s, 178 MB**,
vs 535 libs / 11 min / 3.8 GB for the full-tree build — and identical
surface-check output. Frozen at
`/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/rebuild.sh`.

```bash
D=$WORK/Offline_<tag>_partial
SRC=/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_32_10/Offline  # backing's Offline
mkdir -p $D && cd $D

# 1. Source AT THE BACKING'S TAG. `-c safe.directory` is transient: CVMFS is
#    cvmfs-owned, so a plain clone dies "detected dubious ownership".
git -c safe.directory='*' clone -q $SRC Offline

# 2. mgit's ONLY real output is this file (see mg_add: it appends one line and
#    re-reads the tree). Write it directly.
cd Offline
git config core.sparsecheckout true
printf "/.muse\n/.gitignore\n/GeometryService\n" > .git/info/sparse-checkout
git read-tree --reset -u HEAD
cd ..

patch -p1 -d Offline < /path/to/local.patch

export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/tmp/s.log 2>&1
muse backing SimJob Run1Bap
muse setup >/tmp/m.log 2>&1     # derives p101 by itself -- NO -q needed
muse build -j 12
```

### Why NOT `mgit init` when the backing is a tag

`mg_init` **never consults the backing** — grep the function: 0 occurrences of
"backing" (vs 10 in `mg_status`). It unconditionally runs
`git checkout --no-track -b mgit_init_branch mu2e/main`, i.e. Offline main HEAD.
Concretely, 2026-07-28: main HEAD `.muse` says `ENVSET p103`, Run1Bap ships only
`al9-{prof,debug}-e29-p101` → `muse setup` stops with *"backing build area
missing required build"*. Forcing `-q p101` past it is worse: your one local
package is then compiled from newer source than the ~500 libs around it (ABI
drift, no error). This is the same failure as the p094-vs-p095 loss of
2026-05-17 with new numbers.

It is structural, not a bug: `MUSE_BACKING` is set by `muse setup`, which runs
**after** mgit — which is also why `mgit status` refuses to run before setup.
mgit is built for developing against Offline *head*; we are pinned to a tag.

### Is a one-package build ABI-safe?

Ask at **file** granularity, not package. The backing ships
`build/<stub>/Offline/gen/txt/deps.txt` (what `mgit status` reads); for
GeometryService it lists **36 dependent packages** — but that is
package-granularity and over-approximates. The binding check for the holeRadii
patch: `StoppingTargetMaker.hh` (whose class gains a `std::vector<double>`
member) is included by exactly ONE file in all of Offline —
`GeometryService/src/GeometryService.cc`, in its own package. Nothing else can
observe the layout change. Confirmed at runtime, not just by argument: the
patch's `holeRadii vector active (n=49)` canary fires under the partial build,
which stock `GeometryService` cannot print.

## Alternate recipe: mgit + muse tarball (develop-against-head only)

Valid when you are tracking Offline **main** and your backing is near head.
Superseded by the tag-pinned recipe above whenever the backing is a tag.

```bash
# 1. Pick a build root.
mkdir -p $WORK/autoresearch_muse && cd $WORK/autoresearch_muse
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh

# 2. Backing chain. Separator is a SPACE; "SimJob/Run1Bak" is a parse error.
muse backing SimJob Run1Bak

# 3. Partial checkout. mgit init makes an empty sparse repo on
#    `mgit_init_branch`; mgit add <pkg> adds <pkg>/ to sparse-checkout.
mgit init
mgit add Mu2eG4

# 4. *** mgit add pulls HEAD of github.com/Mu2e/Offline main, NOT the backing's
#    tag.*** That breaks ABI against the rest of the backed libs. Overlay the
#    backing's tag onto the sparse tree:
( cd Offline && git checkout v13_12_10 -- Mu2eG4/ )

# 5. Apply local patch(es).
patch -p1 -d Offline < /path/to/helical-plug.patch

# 6. Enter Muse env. CRITICAL: do not pipe (subshell discards MUSE_*).
#    Let muse setup derive the qualifier from the backing chain — that's
#    the mu2ewiki-documented convention. Only pass `-q p094` explicitly
#    if the local `.muse` advertises a newer envset than the backing was
#    built against (see Key facts below).
muse setup >/tmp/setup.log 2>&1
echo $MUSE_WORK_DIR                            # expect: this dir

# 7. Build. -j 8 finishes in ~10-15 min on mu2egpvm.
muse build -j 8 >/tmp/build.log 2>&1

# 8. The rebuilt lib lives at:
ls build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so

# 9. Package for grid (canonical — produces Code.tar.bz2 with a proper
#    setup.sh whose link order naturally prefers our libs over CVMFS).
muse tarball
# Output path printed to stdout: /mu2e/data/users/$USER/museTarball/tmp.<rand>/Code.tar.bz2
```

## Legacy recipe (rsync; do not use for new work)

Worked but ships the *entire* Offline source via rsync rather than a sparse
checkout. Kept for reference because the Offline_helical/ tree built this way
still exists on disk.

```bash
mkdir -p $WORK/Offline_helical && cd $WORK/Offline_helical
rsync -a /cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_12_10/Offline/ Offline/
patch -p1 -d Offline < helical-plug.patch
muse backing SimJob Run1Bak
muse setup >/tmp/setup.log 2>&1
muse build -j 8 >/tmp/build.log 2>&1
```

## Key facts

- **Backing chain syntax:** `muse backing SimJob Run1Bak` (space-separated).
  `SimJob/Run1Bak` is a parse error.
- **Backing transitivity:** our local build → `SimJob/Run1Bak` →
  `Offline/v13_12_10`. Verbose `muse -v setup` confirms this: it adds
  `/cvmfs/.../SimJob/Run1Bak` AND `/cvmfs/.../Offline/v13_12_10` to the
  search/build paths. The rebuilt lib's rpath includes the v13_12_10 lib dir,
  so ABI compatibility is guaranteed by construction.
- **`MUSE_WORK_DIR` does NOT propagate through pipes.** `muse setup -q p094 |
  tail -3` leaves the variable unset in the calling shell — the env was set
  inside the pipe's subshell and discarded. Redirect to a file (`>...log
  2>&1`) and read it after.
- **Envset must match Run1Bak's:** `p094` is what Run1Bak built against; using
  a different qualifier produces a lib the workers can't dlopen cleanly.
- **`muse setup` derives the qualifier from the backing chain.** In the
  `autoresearch_muse/` rsync layout used today, plain `muse setup` (no `-q`)
  picks `p094` correctly because the top-level `.muse` came from
  `Musings/Offline/v13_12_10`. This matches the mu2ewiki-documented
  workflow — no explicit `-q` needed.
- **`-q p094` override is only needed in the mgit-add scenario.** Tested
  2026-05-17 with `mgit init` + `mgit add Mu2eG4`: `muse setup` with no
  `-q` picked `p095` because `mgit add` pulled main HEAD whose top-level
  `.muse` advertises a newer envset than the backing. Result: `ERROR -
  backing build area missing required build (al9-prof-e29-p095)`. The
  `git checkout v13_12_10 -- Mu2eG4/` overlay covers only the added subdir;
  top-level `.muse` is still from main. In *that* layout only, pass
  `-q p094` to override. The rsync recipe doesn't hit this because it
  overlays the whole v13_12_10 tree including the top-level `.muse`.
- **Full Offline source is required.** A partial overlay
  (`.muse` + one `.cc`) makes `scons` say "up to date" and produces nothing —
  the SConscript chain needs the whole tree.
- **Incremental rebuild gotcha (2026-05-20).** After editing one `.cc`,
  `muse build Offline` reports "up to date" without relinking the changed lib
  (the package-level target stops short). Targeting the .so explicitly works:
  ```bash
  muse build build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so
  ```
  This recompiles the changed .os and relinks the .so. Also: `muse build
  Offline/Mu2eG4/src/foo.os` errors with "Do not know how to make File
  target" — scons names objects under `build/.../tmp/Mu2eG4/src/foo.os`, not
  the package subdir; the lib-level target is the safe granularity.
- **Patch isolation:** `git diff Mu2eG4/src/constructTSdA.cc` in mmackenz's
  checkout extracted the +112-line helical-plug change cleanly, separating it
  from his 10 other unrelated working-tree mods.
- **Run1Bak's `constructTSdA.cc` matches mmackenz's `Run1BTargetDesigns`
  branch HEAD exactly** — Run1Bak was built from his fork, not from
  `Mu2e/Offline` main.

## Cross-links

- Used by: [pipeline](/drivers/pipeline.md) (`write_code_tarball` ships `Code/lib/libmu2e_Mu2eG4.so`
  + `LD_PRELOAD` in `setup.sh`)
- Motivating bug: [calo-constant-across-helical](/incidents/calo-constant-across-helical.md)
- Extra-module fallout: [mmackenz-edepana-lib-qualifier-bump](/incidents/mmackenz-edepana-lib-qualifier-bump.md)
  (the borrow path dying is why we build Run1BAna in our own work area)
- Project: [bo-helical](/projects/bo-helical.md)
- Source files: `core/pipeline.py:402` (`mmlib` prepend), `core/harvest.py:64-66`
  (`EDEP_FCL`, `SENSITIVITY_MACRO` — the second, diverged clone)
- Source patch: `/exp/mu2e/app/users/oksuzian/Offline_helical/helical-plug.patch`
- Build dir: `/exp/mu2e/app/users/oksuzian/Offline_helical/build/al9-prof-e29-p094/Offline/lib/`
- Mu2e wiki: https://mu2ewiki.fnal.gov/wiki/GitHubWorkflow#Developer_Workflow

## Extra repos alongside Offline: Run1BAna (EdepAna)

A muse work area holds **several repos side by side in `MUSE_REPOS`**, all
built against one backing — the mechanism is not Offline-specific, so importing
an outside module needs no new machinery. `autoresearch_muse/` uses it today:

```
autoresearch_muse/
├── backing -> /cvmfs/.../Musings/SimJob/Run1Bak
├── Offline/          # patched subset (holeRadii, helical plug)
├── Run1BAna/         # the extra-module repo, a sibling of Offline
└── build/al9-prof-e29-p094/{Offline,Run1BAna}/lib/
```

`EdepAna_module` lives in mmackenz's personal `Run1BAna`
(`github.com/michaelmackenzie/Run1BAna` — **not** the Mu2e org, **not**
Offline, **not** Run1Bak; verified against `Offline/v13_12_10` at full depth
2026-08-18: zero `EdepAna` matches, the only `Edep`-named file being the
unrelated `MCDataProducts/inc/CaloEDepMC.hh`). The harvest step loads it via a
`CET_PLUGIN_PATH` + `LD_LIBRARY_PATH` prepend in
`pipeline.py:sourced_env(with_muse=True)`.

### Build it here — but ONE TARGET, never the package

**Superseded 2026-06-26:** this section previously said a local build had been
attempted and failed, and that the fix was to borrow mmackenz's prebuilt lib.
That borrow path is **dead** — he bumped p094→p101 and deleted the directory we
pointed at, taking every foils/ipa harvest down with it
([mmackenz-edepana-lib-qualifier-bump](/incidents/mmackenz-edepana-lib-qualifier-bump.md)).
We build it ourselves now, and it compiles clean:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch_muse
muse setup -q p094
muse build -j4 build/al9-prof-e29-p094/Run1BAna/lib/librun1bana_workflows_EdepAna_module.so
```

**The explicit lib target is the whole trick.** Run1BAna HEAD has drifted past
the backing, so a package-level or bare `muse build` still fails — on OTHER
sub-packages, never on EdepAna:

- `Run1BAna/evtana/inc/Run1BEvtAna.hh` includes `EventNtuple/inc/HitCount.hh`
  — that repo isn't checked out.
- `Run1BAna/modules/src/CalLineFinder_module.cc:421` references
  `mu2e::CosmicTrackSeed::_caloCluster`, absent from `v13_12_10`.

`EdepAna_module.cc` itself has **no** `EventNtuple` dependency — only Offline
(`RecoDataProducts/CaloCluster`, `MCDataProducts/{PrimaryParticle,CaloShowerStep,
StepPointMC}`, `Mu2eUtilities/StopWatch`), art and ROOT, all present in the
backing. Naming the `.so` makes scons stop short of the broken siblings. Raw
`scons` fails with "No SConstruct" — it MUST go through `muse build`.

**Not a grid concern:** EdepAna runs only in the local harvest, never in a grid
stage, so `Code.tar.bz2` never carries it and no tarball rebuild follows a
Run1BAna change. If a future stage did need it on the worker, this same work
area is what `muse tarball` would ship.

### Known gap: the fcl + macro come from a SECOND, diverged clone

The build tree above supplies only the `.so`. `edep.fcl` and
`rough_run1a_sensitivity.C` are read at harvest time from a **different,
untracked clone** at `autoresearch/Run1BAna/` (gitignored, `.gitignore:72`),
wired in at `harvest.py:64-66`. The two clones have already diverged (disjoint
`config_*` dirs as of 2026-08-18), so nothing prevents the module and the FHiCL
that configures it from being different vintages. Either checkout can also move
under us: neither is pinned to a SHA. Fixing this means one pinned checkout
feeding both the build and the harvest.

## Backing-only tarball (no source overlay, no build)

For a stock Musing with **zero local patches**, the recipe collapses to
just `muse backing` + `muse setup` + `muse tarball` — no rsync, no mgit,
no compile step. The resulting tarball is a few hundred bytes (vs ~60 MB
for a full-Offline overlay) because it contains only `Code/setup.sh` +
`Code/backing` symlink to CVMFS. Workers resolve everything through the
backing.

Concrete example (2026-06-07, produced `Code_MDC2025aq_prodtarget.tar.bz2`
for [bo-prodtarget](/projects/bo-prodtarget.md)):

```bash
mkdir -p $WORK/autoresearch_muse_prodtarget && cd $_
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
muse backing SimJob MDC2025aq    # symlink: backing -> CVMFS path
muse setup                       # picks p101 from backing's .muse
muse tarball                     # tarball: 377 bytes
```

Produced tarball contents:
```
Code/setup.sh        # muse setup $CODE_DIR -q p101 e29 prof
Code/backing         # symlink -> /cvmfs/.../Musings/SimJob/MDC2025aq
```

**Gotcha (cosmetic, non-fatal)**: `muse tarball` prints
`tar: build/al9-prof-e29-p101/.musebuild: Cannot stat: No such file or
directory` because there's no build dir, then exits rc=0 with a valid
tarball. The warning can be ignored.

**When this works vs full-overlay**: backing-only is correct when the
worker runs unmodified CVMFS libraries (e.g. the Stickman PT bo-prodtarget
case — pure-config geometry changes via `MU2E_SEARCH_PATH`). Use the
full-overlay recipe above when any `.so` needs a local patch.

**Why the symlink is preserved (verified against muse 4.17.0, 2026-06-07)**:
`museTarball.sh:272-286` walks the backing chain and, when
`readlink -f backing` matches `^/cvmfs/*` (regex `cvmfsReg` at line 139),
stages **only the symlink** (`ln -s $BDD $TMP/backing`) into the tmp dir,
tars with `-h`, and `break`s. Local-disk backings fall through and get
packed in full. Implication: a CVMFS-backed tarball is **CVMFS-dependent
at runtime** — fine for OSG sites Mu2e uses, but not portable to
non-CVMFS workers.

**Why empty `MUSE_REPOS` is fine**: `museSetup.sh:781` only warns
("setup an empty directory") when **both** `MUSE_REPOS` AND
`MUSE_BACKING` are empty. A pure-backing workDir populates
`MUSE_BACKING` (lines 326-337), and `MUSE_REPOS` is then filled from
`$MUSE_BACKING_REV` (line 553). No stub repo required.

**Grid-side invocation**: the auto-generated `Code/setup.sh` literally
does `muse setup $CODE_DIR -q <qual>` where `<qual>` is pinned to the
local `-q` at tarball time (prof/debug + envset). Prefer
`source Code/setup.sh` over bare `muse setup Code` for reproducibility —
the wrapper replays the exact qualifier.

## Open questions / TODO

- If we add more patches that touch headers, may need to rebuild more than
  just `libmu2e_Mu2eG4.so`. Watch link-time errors on dependents.
