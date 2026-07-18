---
type: incident
title: Patched ProductionTargetMaker — spacer + support-ring overlaps with downstream
  plate
description: pt001 5 managed-volume overlaps all reported "by 50 nm" = `stickmanMagicOffset/2`
  precision-tolerance; **resolved 2026-06-08** by shrinking `spacerHalfLength` by
  `stickmanMagicOffset` (matches existing rod shrink at constructTargetPS.cc:1730)
status: active
status_note: 'shrinks + lug-cap cover 8/10 of ptX05R00 picks; **third failure mode
  discovered 2026-06-10**: thick-plate regime re-triggers; **fourth failure mode**
  had a wrong magnitude claim (250–500 µm) — **CORRECTED 2026-06-17 via pt6d07 evidence**:
  end-plate clamp `lPlate[{0,-1}]=tPlate` (shipped autoresearch_bo_michael.py:1527-1534)
  DID eliminate the macro overhang (pt6d07 R0 = 10/10 clean, R1 = 7/10 with 3 fails
  reporting only **50–100 nm** = magic-offset class), so the original 4-OOM physical-overhang
  diagnosis was incorrect. Residual `SpacerNegZ_0 ⟷ Plate00` at precision tolerance
  is the same class as the documented `SpacerPosZ × Plate_last` mode and needs the
  mirror-side spacer shrink in `constructTargetPS.cc:1730`.'
timestamp: '2026-07-17'
updated_note: 'pt6d07 evidence: clamp works, residual is precision-tolerance class'
---

# Patched ProductionTargetMaker — spacer + support-ring overlaps with downstream plate

## Summary
pt001 (stock Stickman defaults: N=33 plates, rOut=3.15, t=5, lug=6,
spacerHalf=1.5) emitted **5 unique managed-volume overlaps** under
`g4.doSurfaceCheck=true`:

```
ProductionTargetSpacerPosZ_0   ⟷ ProductionTargetPlate_32  (G4UnionSolid)
ProductionTargetSpacerPosZ_1   ⟷ ProductionTargetPlate_32
ProductionTargetSpacerPosZ_2   ⟷ ProductionTargetPlate_32
ProductionTargetSupportRing_Upstream    ⟷ ProductionTargetSpacerNegZ_0
ProductionTargetSupportRing_Downstream  ⟷ ProductionTargetSpacerPosZ_0
```

Each was reported "by 50 nm (max of N cases)" → all the same precision-
tolerance signature, not a geometry-math bug. These are
`GeomVol1002` advisories: jobs would START on the grid but with
physically undefined navigation in the overlap region → biased
totalEdep and biased VD/POT counts. Surface-check preflight
([preflight-fcl-genparticle-missing](/incidents/preflight-fcl-genparticle-missing.md)) caught them before submit.

## Root cause: 50 nm = `stickmanMagicOffset / 2`

`constructTargetPS.cc:1343` defines
`stickmanMagicOffset = 0.0001 mm = 100 nm` as a precision tolerance
for nominally-touching solids. The **rod** uses it
(`constructTargetPS.cc:1730: rodHalfLength - stickmanMagicOffset`) to
keep its planar face just inside the support-ring inner face. The
**spacer, plate, and support-ring** solids did NOT, so their planar
faces sat exactly at the same z as the adjacent volume's face. G4's
overlap checker fires `GeomVol1002` at any nonzero shared volume; with
the spacer cylinder and the support-ring face nominally coincident,
floating-point round-off in the union/placement chain produces a 50 nm
intersection slab — exactly `magicOffset / 2`.

## Fix

One line in `constructTargetPS.cc:~1723` (patched workdir
`/exp/mu2e/app/users/oksuzian/autoresearch_muse_prodtarget/Offline/Mu2eG4/src/constructTargetPS.cc`):

```cpp
G4VSolid* spacerSolid = reg.add(new G4Tubs(
      "ProductionTargetSpacerSolid",
      tgt->spacerInnerRadius(),
      tgt->spacerOuterRadius(),
      tgt->spacerHalfLength() - stickmanMagicOffset, // precision shrink
      0., CLHEP::twopi));
```

Shrink the spacer's half-length by `stickmanMagicOffset` so its two
planar faces sit 100 nm inside the adjacent plate / support-ring face.
The mid-spacer-vs-mid-spacer gap is closed by the rod, which is
itself shrunk by the same offset at line 1730 — geometry remains
flush-touching to within rod thickness, navigation is unambiguous.

Result: pt001 preflight goes from 5 managed overlaps to 0.

## False trail (worth recording)

Initial hypothesis was a downstream-advance bug: BO can pick
`plateLugThickness[i] < plateThickness[i]`, and if the loop advances
by `lugThickness` only, the plate visually overflows past the lug
union → spacer collision. Tested by switching the advance to
`std::max(plate, lug)` and re-rendering pt001 geometry; numpy diff =
0.0. The BO driver already enforces `lPlate[i] >= tPlate[i] + 0.5`
at `autoresearch_bo_michael.py:1112`, so the overflow case can't
arise from BO picks. Reverted those edits in
`constructTargetPS.cc:1719`, `ProductionTarget.cc:230`, and
`autoresearch_bo_michael.py:_geom_text`.

Lesson: the "by N nm" magnitude in the G4 overlap log is the
single most diagnostic line — read it before patterning off
the previous turn's hypothesis. 50 nm = round-off, not math.

## Secondary observation: LV name vs SD instance-name mismatch

G4 physical-volume names use `ProductionTargetPlate_<n>` (underscore,
not zero-padded — visible in `Checking overlaps for volume
ProductionTargetPlate_0:0`). But `pipeline.py:266` generates the SD
sensitive-volume list as `ProductionTargetPlate{i:02d}` (e.g.
`ProductionTargetPlate00`) — see [art-instance-name-no-underscore](/incidents/art-instance-name-no-underscore.md)
for why the rename happened on the art-instance-name side.

These two name forms don't textually match. Path D edep harvest may
be relying on a prefix-match in the patched
`SensitiveDetectorHelper::instantiateLVSDs` dispatch
(`SensitiveDetectorHelper.cc:140-152`) rather than exact LV-name
lookup. Worth verifying that:
- (a) The dispatch logic actually attaches the SD to every
  `ProductionTargetPlate_*` LV (prefix match).
- (b) Local smoke trees `ptPlate0/nt` ... `ptPlate(N-1)/nt` are all
  populated (not just plate 0).

## Cross-links

- Source: `Offline/Mu2eG4/src/constructTargetPS.cc:~1723` and `:1730` (patched in
  `autoresearch_muse_prodtarget` muse)
- Related: [preflight-fcl-genparticle-missing](/incidents/preflight-fcl-genparticle-missing.md) (surface-check is
  what surfaced this — without it, the overlap would have silently
  reached the grid), [pipeline-poll-rc120-atexit-death](/incidents/pipeline-poll-rc120-atexit-death.md)
- Related: [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md) (without env wiring the
  fixed libs never reach preflight or grid)
- Related: [art-instance-name-no-underscore](/incidents/art-instance-name-no-underscore.md) (the prior patch that
  caused the secondary LV-name mismatch noted below)
- Related: [stickman-sd-unwired](/incidents/stickman-sd-unwired.md) (Path B SD dispatch context)
- Related: [tessellated-solid-facet-orientation](/incidents/tessellated-solid-facet-orientation.md) (other example of
  silent-pass `GeomVol1002` overlaps that bias physics)

## Re-trigger under ptX03 wider bounds (2026-06-09)

ptX03 expanded `MODE_SPECS["prodtarget"]` envelope (lug 4–12 mm, thick
3–8 mm, N 25–45) past the ptX02 envelope. 4/10 R0 children (R00_00,
_01, _02, _08) died at preflight=`fail_managed` ×3 retries.

**Preflight logs are NOT swallowed** — full G4 stdout (including
`Overlap is detected for volume ...` lines + 50 nm magnitude) lives at
`/exp/mu2e/app/users/oksuzian/autoresearch/bo_prodtarget_preflight/<config>.log`.
`autoresearch_bo_michael.py:cmd_preflight` writes `log.write_text(out)`
with combined stdout+stderr (line ~1756). Only the closed-loop child log
(`/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/closed_loop_logs/<config>.log`) shows the bare
`preflight=fail_managed` status — to see the overlap pair, go to the
preflight dir.

**Same overlap class as pt001, different plate indices:**
- R00_00, R00_01 (N=34): SpacerPosZ × Plate33 (×3) + ring/spacer pairs
- R00_02 (N=35, l2=4.0mm floor): SpacerPosZ × Plate34
- R00_08 (N=34, t2=8.0mm ceiling): SpacerNegZ × **Plate00** (new index!)

**Key correlated knob: upstream lug `l0`.** When l0 (or l2 at the
opposite end) shrinks toward the 4mm floor, the spacer–plate planar
faces become coincident-mod-roundoff at whichever stack end has the
smallest lug. Passing configs (R00_03, _05) all have mid-range lug
values 4.88–7.32mm at every knot.

## Code fix designed but not yet applied (2026-06-09)

**Single-line fix in `constructTargetPS.cc:~1389`:**
```cpp
// before
const double lugHalfThickness = tgt->plateLugThickness(ithPlate)/2.;
// after
const double lugNominalHalfThickness = tgt->plateLugThickness(ithPlate)/2.;
const double lugHalfThickness = lugNominalHalfThickness - stickmanMagicOffset;
```
Then `lugZShift` (used for plate-center placement) MUST keep using
`lugNominalHalfThickness`, not the shrunk value — otherwise plate centers
drift and the z-march accumulates error across N plates. Net effect:
every intra-stack plate-to-plate junction gains a 200 nm gap (100 nm
from lug shrink × 2 faces) without shifting any plate center.

**Optional companion: bump `stickmanMagicOffset` 100nm → 1µm**
(`constructTargetPS.cc:1343`) for 20× headroom; still sub-percent of
smallest feature (rod radius 2mm).

Verification recipe: after `muse build`, run preflight on R00_00's
geometry + the 4 envelope corners
`{(N,lug,t,r) = (25,4,3,2), (45,12,8,4.5), (45,12,3,2), (25,4,8,4.5)}`.
Expect 0 `Overlap is detected for volume ProductionTarget` matches.

**Spacer↔SupportRing and Rod↔SupportRing junctions did NOT need
additional shrinks** — the existing 2026-06-08 spacer shrink already
covers them (verified by reading 1620-1760 — only the intra-stack
plate-lug junctions are unprotected). This contradicts the earlier
TODO "extend shrink to support-ring and plate end-caps" — only the
plate-lug needs adding.

**RETRACTED 2026-06-10 (post-fix verification on ptX04R00_00):** the
plate-lug shrink at line 1389 took R00_00 from 5 overlaps → 2 (killed
SpacerPosZ×Plate33 ×3 + Rod×SupportRing_Upstream), but a residual
`SupportRing_{Downstream,Upstream} × SpacerPosZ_0` pair persists at 50 nm.
The 2026-06-08 spacer shrink alone does NOT cover the ring-end junction
when N or end-knot values change. A second shrink at line ~1851
(`ringHalfLength = stickmanSupportRingLength()/2. - stickmanMagicOffset`,
with `ringNominalHalfLength` kept for cutout-z placement at line ~2022)
was applied 2026-06-10. Rebuild + re-verify pending.

## Lug-floor hypothesis RETRACTED (2026-06-10, ptX04)

The 2026-06-09 "key correlated knob: upstream lug l0" claim was wrong.
ptX04R00_00 had lug profile **(7.74, 6.91, 7.39)** — all knots ~3 mm above
the (then-clamped) 5.0 mm floor — and still triggered the SAME 50 nm
`SpacerPosZ × Plate33` overlap (+ Rod×SupportRing_Upstream + SpacerPosZ ×
SupportRing_Downstream pairs). ptX04R00_08 (lug 8.06–8.80) added a NEW
**150 nm** signature on the upstream end (`SpacerNegZ × Plate00`, ×3
spacers, 3× the magnitude of the downstream side).

What the failures actually share: any geometry that diverges from pt001's
exact `(rOut=3.15, t=5, lug=8, spacer=1.5)` baseline at the stack ends
re-exposes spacer/plate face coincidence at one or both ends. Lug
magnitude alone is not the trigger; the union/placement chain has a
roundoff path that 50 nm of magic-offset shrink at one junction (the
2026-06-08 spacer shrink) doesn't fully cover when N or end-knot values
change. The 150 nm magnitude on the NegZ side suggests the upstream junction
accumulates extra roundoff via the support-ring subtraction solid.

The lug-bounds clamp in `autoresearch_bo_michael.py:1301-1306` and
`botorch_predict.py:95-96` (l0/l1/l2 ∈ [5, 10.5]) is therefore a
**dead workaround** and should be reverted alongside the code fix.

## Workaround applied 2026-06-10: lug bounds clamp (ptX04)

After ptX03R00 4/10 preflight failures, ptX03 was killed (parent PID 2263326
+ 3 surviving children; grid clusters 28082628/28082652/84607452 left to
finish for bonus data). BO lug bounds were tightened in two places to
avoid the floor:

- `autoresearch_bo_michael.py:1301-1306` ProdTargetMode.build_space — `l0/l1/l2`
  Real bounds `(4.0, 12.0)` → `(5.0, 10.5)`.
- `botorch_predict.py:95-96` MODE_SPECS["prodtarget"] — matching clamp on
  the qLogNEHVI picker's normalized search domain (must mirror build_space
  or picker proposes values build_space then rejects).

Rationale: ptX02 children all lived in lug `[4.86, 10.21]` and all passed
preflight; clamping to `[5.0, 10.5]` keeps a 1 mm buffer from the 4 mm
floor where the spacer/plate face coincidence triggers. r/t/N untouched.
Verified `MODES['prodtarget'].build_space()` matches `MODE_SPECS` after
edit. Relaunched as ptX04 (NEW prefix per [closed-loop-stale-cluster-silent-no-launch](/incidents/closed-loop-stale-cluster-silent-no-launch.md)).

**This is a workaround, not the fix.** The code fix (`constructTargetPS.cc:~1389`
plate-lug shrink, designed above) still needs to land; once muse-built and
the new tarball ships, revert this clamp.

## Second root cause: lug overhang (2026-06-10, ptX04R00_08 family)

After applying both stickmanMagicOffset shrinks (plate-lug at line 1389 +
support-ring at line 1851), ptX04R00_00 + ptX03R00_00 passed but
ptX04R00_08 still failed: `SpacerNegZ_0 × Plate00` at **150 nm × 16 cases**
(qualitatively different signature — large magnitude, many distinct probe
hits, NOT magic-offset roundoff).

**Mechanism.** Plate i's lug is centered on the plate core (`lugZShift =
lugNominalHalf - plateHalfThickness`). When `lPlate[i] > tPlate[i]`, the
lug's half-length exceeds the plate-core's half-length and the lug
protrudes past the plate's planar face. The lug's annular footprint
(`plateLugInnerRadius=1.525, plateLugOuterRadius=3.0`) is essentially
identical to the spacer's (`spacerInnerRadius=1.55, spacerOuterRadius=3.0`).
For Plate 0 specifically, the upstream face borders SpacerNegZ_0 — so a
lug overhang of any size guarantees a radial overlap inside the rod span.

Numbers: pt001 baseline `lPlate - tPlate = 1.0 mm`; ptX04R00_00 (passing)
max `lPlate - tPlate ≈ 1.5 mm`; ptX04R00_08 (failing) max
`lPlate - tPlate ≈ 2.4 mm` (and 0.84 mm on plate 0 specifically).

**Fix.** Upper cap in `ProdTargetMode._expand`
(`autoresearch_bo_michael.py:~1329`):

```python
LUG_OVER_THICK_MAX_MM = 1.0      # plateLugThickness <= plateThickness + 1.0
...
lPlate = np.clip(lPlate,
                 tPlate + self.LUG_OVER_THICK_MARGIN_MM,
                 tPlate + self.LUG_OVER_THICK_MAX_MM)
```

Mirrors the pt001 baseline diff exactly. Verified on ptX04R00_08-capped:
0 overlaps. Lug `Real(4.0, 12.0)` bounds restored in `build_space` +
`botorch_predict.MODE_SPECS` — `_expand` clips post-projection so the
BO search space stays wide while pre-empting silent overlaps.

## Fourth mode: end-plate UPSTREAM lug overhang into SpacerNegZ (2026-06-15, pt6d05R01)

Subagent diagnosis on `pt6d05R01_{00,03,06}/geom/asbuilt_*.gdml`:

- Failing children share `SpacerNegZ_{0,1,2} × ProductionTargetPlate00`
  managed-volume overlap at the **upstream** end of the stack.
- Plate00 lug protrudes ~250–500 µm upstream past the plate-core face
  (because BO clamps `lPlate − tPlate ∈ [0.5, 1.0]`, the lug ALWAYS
  overhangs by `(lPlate-tPlate)/2 ≥ 0.25 mm` at every plate, including
  end plates).
- Spacer +z face sits at `(plate00 core upstream face) − 100 nm` (the
  2026-06-08 `spacerHalfLength -= stickmanMagicOffset` shrink); the
  entire 250–500 µm of lug overhang sits INSIDE SpacerNegZ.
- This is the **mirror image** of the documented `Plate_last ×
  SpacerPosZ` mode (second-root-cause block above). The
  `LUG_OVER_THICK_MAX_MM=1.0` clamp only caps how big the overhang gets
  — it does not eliminate it. Both end plates need explicit
  zero-overhang clamping OR the z-march needs to shift.
- Overlap magnitude is 250–500 µm = **4 orders of magnitude above 50 nm
  magic-offset**, so this is real geometry, not precision tolerance.
  Three children failing under 6D mode with `lPlate-tPlate` pinned at
  the 0.75 mm midpoint (BO converged on the middle of the clamp range)
  implies EVERY 6D config is one Sobol-jitter away from the same fail.

**Two ship paths:**

1. **BO-side end-plate clamp (~30 min, no rebuild):** in `_expand`
   (`autoresearch_bo_michael.py:1351-1353`), additionally clip
   `lPlate[0] = tPlate[0]` and `lPlate[-1] = tPlate[-1]` (zero
   overhang on end plates only; interior plates keep the existing
   [+0.5, +1.0] clamp). Python-only; no muse rebuild; no grid tarball
   redeploy. Unblocks 3/10 lost pt6d05R01 cells + all future 6D corners
   the overlap currently masks.

2. **Source patch (~3–4 h):** `constructTargetPS.cc:1669` shift
   z-march start by `max(0., (plateLugThickness(0) − plateThickness(0))/2.)`
   (and matching `halfStickmanLength` formula in `ProductionTarget.cc:230`).
   The 6D `_expand` already enforces ≥0.5 mm overhang so this is
   non-zero for every config. Requires `muse build -j 16` + grid
   tarball rebuild from patched workdir (per [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md)).

Recommended order: ship #1 first as the unblocker, queue #2 as the
proper fix at next muse rebuild cycle.

### 2026-06-17 update — clamp shipped, fourth-mode magnitude retracted

End-plate clamp `lPlate[0]=lPlate[-1]=tPlate` shipped at
`autoresearch_bo_michael.py:1527-1534` together with t-upper 7→8 raise
(launched as pt6d07). Result:

| round | banked | failures | failure mode |
|---|---|---|---|
| pt6d07 R0 | 10/10 | 0 | (none) |
| pt6d07 R1 | 7/10 | 3 | `SpacerNegZ_0 ⟷ Plate00` by **50 nm / 50 nm / 100 nm** |

The clamp **removed the macro overhang** (R0 clean even with picks hitting
the lifted t-cap). The 3 R1 fails are **precision-tolerance class**
(50–100 nm = `stickmanMagicOffset/2` to `stickmanMagicOffset`), not the
~250–500 µm physical overhang the prior subagent claimed. Three rows lost
because the existing `spacerHalfLength -= stickmanMagicOffset` shrink at
`constructTargetPS.cc:1730` only applies to the **PosZ** spacer (mitigating
`SpacerPosZ × Plate_last`); the **NegZ** spacer has no matching shrink, so
its +z face sits exactly at the upstream face of Plate00 and round-off in
the union-solid placement produces the 50–100 nm intersection slab.

**Real fix (deferred):** apply the same `-= stickmanMagicOffset` shrink to
the negative-Z spacer half-length. Source patch + muse rebuild + grid
tarball rebuild per [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md). Until then, BO loses
~15–30% of picks at the upstream-spacer boundary on average.

## Agent-review corrections (2026-06-10)

Two parallel agent reviews of the proposed "bump magicOffset 100nm→1µm"
fix flagged the following:

**Size-scaling hypothesis is WRONG.** G4's
`G4GeometryTolerance::GetSurfaceTolerance()` is a **global absolute**
(~1 nm = 1e-6 mm), not scaled by solid size. The observed "50 nm"
magnitude is STABLE across every overlap report we have — if round-off
scaled with lug magnitude (8.5 mm vs 6 mm pt001 baseline), R00_06/R00_08
would report ~70 nm, not 50 nm. The "third failure mode: thick-plate
regime" hypothesis above (that fixed 100 nm shrink stops being sufficient
above lug ~8 mm because round-off scales with magnitude) is therefore
RETRACTED.

**Likely real root cause: plate-CORE half-length is unshrunk** at
`constructTargetPS.cc:1485`. The 2026-06-10 lug shrink at line 1389
protects intra-stack lug↔lug junctions, but the LAST plate's downstream
face is bounded by its CORE, not its lug — so under thick-regime
topology (t_max ≥ 7.7 mm), the plate-core face goes coincident with
SpacerPosZ at the same 50 nm magic-offset signature. Fix: apply
`stickmanMagicOffset` shrink to plate-core half-length analogously to
the lug/spacer/ring shrinks; keep nominal half-length for placement math
(`lugZShift` and `_currentZ` advance).

**Bumping magicOffset 100nm→1µm alone is whack-a-mole.** It would mask
the next-narrowest coincident-face junction by 10× headroom but not fix
the underlying unshrunk-face bug; expected to recur in ptX06 with
slightly different envelope picks. OK as belt-and-suspenders, NOT as
the only change.

**RCDS-publishing freezes R0 against base tarball.** mu2ejobsub uploads
per-child `cnf.*.tar` to RCDS at submit time; grid nodes pull from RCDS,
not the project filesystem. So already-submitted R0 children are immune
to a mid-flight base-tarball overwrite. R1 children doing `tar xjf` at
submit are NOT immune — base-tarball replacement MUST be atomic
temp+rename, not in-place `mv`/overwrite.

**muse build .so writes are NOT atomic** (SCons rewrites in place →
brief undefined-symbol window). No preflights or grid `tar xjf` may
race a muse build; rebuild only between closed-loop rounds, never
mid-round.

**R1 cost of doing nothing:** P(t_max ≥ 7.7 of 8 mm Real bound) =
1 - (4.7/5)³ ≈ 16.9% → ~1.7/10 thick-regime preflight failures per
round. Workaround acceptable for several rounds while real fix lands.

## Third failure mode: thick-plate regime (2026-06-10, ptX05R00)

After both shrinks + the lug-cap shipped, ptX05R00 still saw 2/10 children
fail preflight (R00_06, R00_08). Both hit the **original pt001 5-overlap
signature** (SpacerPosZ × Plate_last ×3 + ring/spacer pairs at 50nm) —
NOT the 150nm overhang pattern. Both have `t_max >= 7.7 mm` at one or
both ends:
- R00_06: t control = (8.000, 6.503, 3.000), N=33 → t_first ≈ 8 mm
- R00_08: t control = (7.729, 6.409, 8.000), N=34 → t_last = 8 mm

With the cap forcing `lPlate = tPlate + 0.5` at the thick end, lug
becomes ~8.5 mm in absolute terms — much larger than the pt001 baseline
lug (6 mm). The 1389 shrink subtracts a fixed 100 nm regardless of lug
magnitude, so the *relative* shrink shrinks-with-magnitude: at lug=8.5mm
the shrink fraction is 100/8500000 ≈ 1.2e-8, possibly below G4's
internal precision for the union-solid → cylinder face comparison at
this scale. Hypothesis: the union-placement chain produces ~50nm
floating-point round-off proportional to lug magnitude; the fixed
100nm shrink stops being sufficient above some threshold.

**Workaround options (not yet evaluated):**
- Cap `tPlate` Real bounds at ~6.5 mm (pt001 has t=5 mm)
- Bump `stickmanMagicOffset` from 100nm → 1µm (10× headroom, ~1e-7
  fractional impact on smallest feature rod radius 2mm)
- Add a *relative* shrink alongside the absolute one
  (`lugHalfThickness -= max(magicOffset, 1e-8 * lugNominalHalfThickness)`)

ptX05 closed-loop continues with 80% R0 success (8/10 grid-running);
failed children get retried in subsequent rounds with different picks.

## Open questions / TODO

- [ ] Verify Path D plate-tree population for plates > 0
  (LV-name-vs-SD-instance-name mismatch, [stickman-sd-unwired](/incidents/stickman-sd-unwired.md)).
- [x] Identify which dimension combination triggers each overlap class —
  RESOLVED 2026-06-10: 50nm class = `lPlate - tPlate` ≈ 0 (face
  coincidence at lug junction) covered by 1389/1851 shrinks; 150nm class
  = `lPlate - tPlate > ~1mm` (lug overhang into spacer) covered by
  `LUG_OVER_THICK_MAX_MM` cap.
- [ ] Re-verify after grid tarball rebuild that the patched libs reach
  the closed-loop child jobs (per [prodtarget-env-divergence](/incidents/prodtarget-env-divergence.md)).
