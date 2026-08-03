# IPA absolute-position option (`protonabsorber.zStartInMu2e`) — design

**Date:** 2026-07-31
**Status:** approved (brainstormed with operator; interface B; operator
directive: the option ships upstream AND runs live locally)
**Context:** `mode_specs/foilspf.json` IPA compensation comment;
`wiki/log.md` 2026-07-28 entries (IPA placement root-cause + measurements);
`docs/superpowers/specs/2026-07-27-foilspf-profile-stopping-target-design.md`

## Problem

Offline places the inner proton absorber **relative to the stopping
target**: `MECOStyleProtonAbsorberMaker.cc` computes
`targetEnd = _target->centerInMu2e().z() + 0.5*cylinderLength() + 2*vdHL`
(line 126 — identical in v13_32_10 and current `Mu2e/Offline` main) and
derives *everything* from it: body placement
(`ipazstart = targetEnd + distFromTargetEnd`), the DS2/DS3 split
bookkeeping, the cone-radius interpolation anchor (lines 212–219), and the
support-wire ring positions (line 372). But the IPA is fixed hardware: the
stock geom file itself says so — `protonAbsorber_cylindrical_v04.txt:31`
reads `distFromTargetEnd = 625.; //mu2e z positions are 6901-7901 mm`. The
config documents an absolute position; the code implements only a relative
one. Concretely: `foilsflash`'s longer stack silently dragged the IPA
133.33 mm downstream (measured 7034.35–8034.35 vs design 6901.02–7901.02)
through 414 production evaluations before the coupling was noticed
(wiki log 2026-07-28).

`foilspf` and `foilsflash` currently compensate in config
(`distFromTargetEnd = 625 − (span − 800)/2`). For the Run1B geometry this
compensation is **exact** — the IPA is a cylinder
(`OutRadius0 = OutRadius1 = 300.5`), so the only residual coupling, the
cone-taper anchor, is degenerate (~1 µm; it would matter for the conical
`protonAbsorber_cylindrical_v03` variant). The option is therefore not a
physics correction for our line; it is (a) the correct general mechanism
for anyone varying target geometry, worth contributing upstream, and
(b) an operator directive (2026-07-31): the IPA must be pinned by the real
mechanism in our local stack too, not only by a per-mode expression.

## Non-goals

- No change to default behavior: option unset → the maker's code path and
  output are bit-identical to stock.
- No extent-bound change for `foilspf` (stays 400–1100).
- No OPA change — the outer absorber is already placed absolutely
  (`protonabsorber.outerPAZCenter = 6250`).
- No change to `foilsflash`: its compensation is a **constant**
  (`distFromTargetEnd = 491.666672`, offsetting a fixed 49-foil stack) and
  already exact; touching it forces golden-fixture churn for zero physics
  change. It can adopt the option later with its restarted leaderboard.
- Not removing the `foilspf` expression. The 2026-07-28 wiki entry records
  why config-only was chosen for campaigns: a stale/regenerated grid
  tarball **silently ignores** an unknown config key (the
  `foilsg-grid-tarball-scalar-holeradius-fallback` class) — the option's
  behavior lives in the binary. Keeping the expression alongside the option
  removes that failure mode instead of accepting it (see §4).

## Design

### 1. The Offline option

`GeometryService/src/MECOStyleProtonAbsorberMaker.cc`, immediately after
the `targetEnd` computation (line 126; `distFromTargetEnd` is read and
clamped earlier, line 71–77):

```cpp
// Optional absolute pinning: when protonabsorber.zStartInMu2e is set, the
// IPA's upstream end sits at that absolute z regardless of the stopping
// target; distFromTargetEnd then only anchors the cone-radius
// interpolation. Unset (default): stock target-relative behavior.
if ( _config.hasName("protonabsorber.zStartInMu2e") ) {
  targetEnd = _config.getDouble("protonabsorber.zStartInMu2e") - distFromTargetEnd;
}
```

`SimpleConfig::hasName` exists (`ConfigTools/inc/SimpleConfig.hh:95`), so
presence-of-key is the enable switch — no sentinel value. Every downstream
formula becomes a function of absolute z: placement lands exactly at
`zStartInMu2e` (the `distFromTargetEnd` term cancels), length, DS2/DS3
split, and wire rings freeze with it. Unset → code path untouched →
bit-identical stock geometry.

Docs in the same diff: a commented example under
`Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt:31`:

```
// double protonabsorber.zStartInMu2e = 6901.; // uncomment to pin the IPA
// at an absolute z, independent of the stopping target (see Maker).
```

### 2. Order of work — evidence first, PR second

Patch and rebuild the local
`/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial` checkout first
(incremental `muse build`, ~26 s; new `ipa-zstart.patch` file +
`rebuild.sh` hook so from-scratch rebuilds keep it), collect the parity
evidence, then open the upstream PR carrying it:

1. **Default-off no-op:** golden parity harness
   (`PYTHONPATH= .venv/bin/python tests/golden_parity.py check`) after the
   lib rebuild — its seam replay runs a real preflight under this musing
   with no `zStartInMu2e` key anywhere.
2. **The option alone pins:** probe geoms rendered from `foilspf` with the
   compensation expression **stripped back to stock 625** and
   `zStartInMu2e = 6901.02` appended, at extent 400/800/1100 — all three
   must print `protonabs1 Z extent in Mu2e` 6901.02–7901.02
   (`protonabsorber.verbosityLevel = 1`), identical to expression-probes
   and to stock, with zero overlaps under the surface check.
3. Evidence recorded in `docs/ipa_zstart_evidence.md` for the PR body.

Precondition (verified 2026-07-31, re-verify at implementation): no
closed-loop campaign running — lib and tarball swaps are forbidden
mid-campaign.

### 3. Upstream PR

- Sparse clone of `Mu2e/Offline` **main** (hunk region verified identical
  to v13_32_10 on 2026-07-31), branch `ipa-absolute-position`, pushed to
  the existing fork `oksuzian/Offline`.
- Push via `gh` credential helper
  (`git -c credential.helper='!gh auth git-credential' push …`); the known
  ssh-agent limitation only blocks ssh pushes. If HTTPS fails too, hand
  the operator a single push command, then `gh pr create -R Mu2e/Offline`
  either way.
- PR body: the IPA is fixed hardware (cite the geom file's own
  `//mu2e z positions are 6901-7901 mm` comment); target-design studies
  silently drag it — concretely the 414-eval / 133.33 mm displacement
  above; option is default-off with bit-identical stock output; §2
  evidence attached; note the coupling is exactly compensable in config
  for a cylindrical IPA but not for the conical variant, which is why a
  first-class option is the right general fix.
- Compile gate for main is Mu2e CI on the PR; the local v13_32_10 build is
  our own compile+runtime gate.

### 4. foilspf goes live on the option (`mode_specs/foilspf.json`)

- **Add** `protonabsorber.zStartInMu2e = 6901.02` to the emitted geometry.
  Value = `z0 (5871) + extent_deployed/2 (400) + 5.02 + 625`: the +5 is
  `StoppingTargetMaker`'s tilt margin, the +0.02 is `2×vd.halfLength`
  (constants pinned in the 2026-07-28 wiki log); confirmed by the
  verbosity measurement in §2 before baking in.
- **Keep** the `ipa_dist` expression exactly as-is. Layering: under the
  patched lib the option is authoritative and placement is
  `zStartInMu2e` exactly; under a stale/unpatched lib the key is ignored
  and the expression still yields the identical exact placement (cylinder
  ⇒ the two mechanisms differ only in the degenerate taper anchor). The
  tarball-drift failure mode is thereby eliminated, not detected.
  Comment in the JSON states this authority order.
- **Consistency invariant** (new test in `tests/test_foilspf_spec.py`):
  for extent ∈ {400, 800, 1100},
  `zStartInMu2e == 5871 + extent/2 + 5.02 + distFromTargetEnd(extent)` —
  i.e. the two mechanisms agree, so patched and unpatched libs cannot
  diverge.
- Rebuild the grid tarball under a **new name**
  (`Code_run1bap_holeradii_ipafix.tar.bz2`, via `muse tarball` from the
  patched workdir) and point `software.grid_tarball` at it — never
  overwrite a tarball in place. Gate: extract the tarball's
  `libmu2e_GeometryService.so` and `strings`-check BOTH markers
  (`zStartInMu2e` and `holeRadii vector active`) before the JSON pointer
  moves — the foilsg incident class is exactly a tarball missing its
  patch.
- **Superseded during execution**: the design called for `foilsflash` to
  keep pointing at the existing `Code_run1bap_holeradii.tar.bz2`, unchanged
  either way. It was instead consolidated onto
  `Code_run1bap_holeradii_ipafix.tar.bz2` alongside `foilspf`, because
  `tests/test_foilspf_spec.py::test_run_configuration_matches_foilsflash`
  pins the two modes' `grid_tarball`/`musing` equal (sibling software
  environments, same leaderboard comparison). The consolidation is
  behaviorally inert for `foilsflash`: its geometry never emits
  `protonabsorber.zStartInMu2e`, so the option is a no-op there either way
  (verified by grep across mode_specs, fixtures, and golden geoms).
- Bounds, stages, `require_zero_overlaps: true` — unchanged.

### 5. Testing

- `tests/test_foilspf_spec.py`: new test for the rendered
  `zStartInMu2e` line + the §4 consistency invariant; the existing
  compensation-invariant test stays untouched (the expression remains).
- Golden parity harness after the lib rebuild (default-off no-op).
- One production `bo_driver preflight` at extent 1100 under the updated
  spec: `rc=0`, zero overlaps, absorber printed at 6901.02–7901.02.
- Suite: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
  (baseline 427 green).

## Rollback

Each piece reverts independently: (1) upstream PR can be closed with no
local effect; (2) local lib — revert the hunk + rebuild (the option is
inert anyway when no geometry sets the key); (3) foilspf — remove the
`zStartInMu2e` line and restore the old `grid_tarball` path (the old
tarball is never overwritten; the expression never left). No data formats,
no state.
