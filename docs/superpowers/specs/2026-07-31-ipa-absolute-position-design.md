# IPA absolute-position option (`protonabsorber.zStartInMu2e`) — design

**Date:** 2026-07-31
**Status:** approved (brainstormed with operator; interface B, upstream + local backport, foilspf switched)
**Context:** `mode_specs/foilspf.json` IPA compensation comment;
`docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md`

## Problem

Offline places the inner proton absorber **relative to the stopping
target**: `MECOStyleProtonAbsorberMaker.cc` computes
`targetEnd = _target->centerInMu2e().z() + 0.5*cylinderLength() + 2*vdHL`
(v13_32_10 line 126) and derives *everything* from it — body placement
(`ipazstart = targetEnd + distFromTargetEnd`), the DS2/DS3 split
bookkeeping, the cone-radius interpolation
(`rOut(z) = OutRadius0 + (OutRadius1−OutRadius0)/2500 · (z − targetEnd)`,
lines 212–219), and the support-wire ring positions (line 480). But the IPA
is fixed hardware: the stock geom file itself says so —
`protonAbsorber_cylindrical_v04.txt:31` reads
`distFromTargetEnd = 625.; //mu2e z positions are 6901-7901 mm`. The config
documents an absolute position; the code implements only a relative one.

Any study that varies the stopping target therefore silently drags the
absorber. `foilspf` works around this with a config expression
(`ipa_dist = 625 − (extent − 800)/2`) that holds the body at 6901–7901 for
any extent — but it is a per-mode hack, and it is not exactly rigid: the
cone radii are interpolated by distance from the *live* `targetEnd`, so at
extent 1100 the IPA radii still drift ~2.7 mm from stock
(slope 0.0179 mm/mm × 150 mm).

## Non-goals

- No change to default behavior: option unset → the maker's code path and
  output are bit-identical to stock.
- No extent-bound change for `foilspf` (stays 400–1100); reopening beyond
  1100 is a separate survey.
- No OPA change — the outer absorber is already placed absolutely
  (`protonabsorber.outerPAZCenter = 6250`).
- No change to `foilsflash` or other modes. `foilsflash` carries its own
  **constant** compensation (`distFromTargetEnd = 491.666672`, offsetting
  its fixed 49-foil stack's extra 133.33 mm) that already lands the IPA at
  6901.02–7901.02; since its target never varies in extent, switching it to
  the new option is a cosmetic rename that would force golden-fixture
  regeneration for zero physics change.

## Design

### 1. The Offline option

`GeometryService/src/MECOStyleProtonAbsorberMaker.cc`, immediately after
the `targetEnd` computation (~line 126):

```cpp
// Optional: pin the IPA at an absolute z, decoupled from the stopping target.
// When set, the IPA's upstream end sits at zStartInMu2e regardless of target
// geometry; distFromTargetEnd then anchors only the cone-radius interpolation.
if ( _config.hasName("protonabsorber.zStartInMu2e") ) {
  targetEnd = _config.getDouble("protonabsorber.zStartInMu2e") - distFromTargetEnd;
}
```

`SimpleConfig::hasName` exists (`ConfigTools/inc/SimpleConfig.hh:95`), so
presence-of-key is the enable switch — no sentinel value. Every downstream
formula becomes a function of absolute z: position, length, DS2/DS3 split,
cone radii, and wire rings all freeze. With the option set to the value the
stock geometry realizes, output is bit-identical to stock; under target
variations the absorber is exactly rigid.

Docs in the same diff: a commented example under
`Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt:31`:

```
// double protonabsorber.zStartInMu2e = 6901.; // uncomment to pin the IPA
// at an absolute z, independent of the stopping target (see Maker).
```

### 2. Order of work — evidence first, PR second

Patch and rebuild the local
`/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial` checkout first
(`rebuild.sh`, ~26 s, GeometryService only), collect the parity evidence,
then open the upstream PR carrying it:

1. **Default-off no-op:** stock foilsflash/foilspf render, option unset,
   patched lib vs unpatched — identical `protonabsorber.verbosityLevel=1`
   prints and surface-check output. Plus the repo golden parity harness
   (`PYTHONPATH= .venv/bin/python tests/golden_parity.py check`) after the
   lib rebuild.
2. **Equivalence at extent 800:** foilspf render with
   `zStartInMu2e` vs today's expression — identical absorber prints
   (6901.02–7901.02).
3. **Rigidity at extent 400/1100:** absorber prints identical to stock,
   which today's expression only approximates (the radii drift vanishes).

Precondition (verified 2026-07-31, re-verify at implementation): no
closed-loop campaign running — lib and tarball swaps are forbidden
mid-campaign.

### 3. Upstream PR

- Sparse/shallow clone of `Mu2e/Offline` **main** (the maker may have
  drifted from v13_32_10 — adapt the hunk to main first; the local
  backport stays as written for v13_32_10).
- Branch `ipa-absolute-position` on the existing fork `oksuzian/Offline`
  (active, last pushed 2026-07-28).
- Push: attempt HTTPS with the `gh` auth token
  (`git push https://x-access-token:$(gh auth token)@github.com/oksuzian/Offline`);
  the known ssh-agent limitation only blocks ssh pushes. If HTTPS fails
  too, hand the operator a single push command, then `gh pr create -R
  Mu2e/Offline` either way.
- PR body: the IPA is fixed hardware (cite the geom file's own
  `//mu2e z positions are 6901-7901 mm` comment); target-design studies
  silently drag it — concretely, our stopping-target study ran 414
  evaluations with the IPA rigidly displaced 133.33 mm downstream
  (measured: 7034.35–8034.35 vs the design 6901.02–7901.02) before the
  coupling was noticed; option is default-off with bit-identical stock
  output; parity evidence from §2 attached. Invite maintainer guidance on
  validation procedure.
- Compile gate for main is Mu2e CI on the PR; the local v13_32_10 build is
  our own compile+runtime gate.

### 4. foilspf switch (`mode_specs/foilspf.json`)

- Drop the `ipa_dist` derived expression and its long compensation
  comment; replace with two constants:
  - `protonabsorber.zStartInMu2e = <measured>` — the exact `ipazstart`
    today's expression produces, read at full precision from a
    `verbosityLevel=1` render at extent 800 (expected ≈ 6901.02; measure,
    don't hand-compute — `targetEnd` includes `2*vdHL` and end-foil
    half-thickness terms).
  - `protonabsorber.distFromTargetEnd = 625.0` — pinned explicitly even
    though the base include (`protonAbsorber_cylindrical_v04.txt:31`)
    already supplies 625: with `zStartInMu2e` set it degrades to a pure
    shape anchor, and an explicit line with a comment saying so guards the
    cone radii against silent base-geometry drift. (The `491.666672` in
    the foilsflash goldens is that mode's own override, not the base.)
- Rebuild the grid tarball under a **new name**
  (`Code_run1bap_holeradii_ipafix.tar.bz2`) from the patched workdir and
  point `software.grid_tarball` at it — never overwrite a tarball in
  place. `software.musing` is already the patched checkout's
  `setup_local.sh`; the lib rebuild covers it.
- Bounds, stages, `require_zero_overlaps: true` — unchanged.

### 5. Testing

- `tests/test_foilspf_spec.py`: update expectations — expression gone, the
  two constants present (render-level assertion on the emitted geom lines).
- Golden parity harness after the lib rebuild (default-off no-op for every
  mode sharing the library).
- One preflight at extent 1100 under the switched spec: zero overlaps,
  absorber at 6901.02–7901.02.
- Suite: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
  (baseline 427 green).

## Rollback

Each piece reverts independently: (1) upstream PR can be closed with no
local effect; (2) local lib — revert the hunk + `rebuild.sh`; (3) foilspf —
restore the expression block and the old `grid_tarball` path (the old
tarball is never overwritten). No data formats, no state.
