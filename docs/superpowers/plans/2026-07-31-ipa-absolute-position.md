# IPA Absolute-Position Option Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `protonabsorber.zStartInMu2e` — an optional absolute-position
pin for the inner proton absorber — to Mu2e Offline (upstream PR), the local
patched GeometryService build, and the live `foilspf` mode.

**Architecture:** One substitution point in
`MECOStyleProtonAbsorberMaker.cc` (every target-coupled quantity flows
through the single `targetEnd` variable at line 126). Local
v13_32_10 partial checkout is patched and rebuilt first for evidence; the
`foilspf` spec then emits the key *alongside* its existing exact
compensation expression (fail-safe layering); a fresh grid tarball ships
the lib; finally the identical hunk goes to `Mu2e/Offline` main as a PR
from the `oksuzian/Offline` fork.

**Tech Stack:** C++ (Offline GeometryService), muse partial-checkout
backing build, JSON mode specs + Python unittest, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-07-31-ipa-absolute-position-design.md`

## Global Constraints

- Test suite: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests`
  — baseline **427 OK**. Run from `/exp/mu2e/app/users/oksuzian/autoresearch`.
- autoresearch git: stage **explicit paths only** (never `git add -A`,
  `-u`, or `.`); **NEVER `git push`** from the autoresearch repo. The only
  push anywhere in this plan is the Offline **fork** push in Task 5, via
  the `gh` credential helper.
- Every commit message (both repos) ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` then
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- Before any lib/tarball/spec switch (Task 4):
  `pgrep -f "closed_loop"; pgrep -f "graph[.]run"` must both return
  nothing — swaps are forbidden mid-campaign.
- Never overwrite an existing tarball in place — new filename only
  (`Code_run1bap_holeradii_ipafix.tar.bz2`).
- Any command that sources the Mu2e env must first
  `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` and must **not
  pipe** `muse setup` (a pipe's subshell discards the exported MUSE_*).
- Scratch space: `bo_work/ipa_probe/` under the repo root. Never wildcard
  `rm`; delete by explicit path or `find -name PATTERN -delete`.
- The constant `6901.02` is baked into JSON only **after** Task 2's
  measurement confirms it. If any measured print disagrees, STOP and
  report BLOCKED — do not "fix" the constant unilaterally.

---

### Task 1: Source option in the local Run1Bap checkout + patch capture + rebuild

**Files:**
- Modify: `/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/Offline/GeometryService/src/MECOStyleProtonAbsorberMaker.cc:120-127`
- Create: `/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/ipa-zstart.patch`
- Modify: `/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/rebuild.sh`

**Interfaces:**
- Consumes: existing checkout (already carries `stoppingtarget-holeradii.patch`, applied in-tree).
- Produces: rebuilt `libmu2e_GeometryService.so` honoring
  `protonabsorber.zStartInMu2e`; the string literal
  `protonabsorber.zStartInMu2e` present in the binary (Tasks 2 and 4 grep
  for it); `ipa-zstart.patch` (Task 5 reuses the same hunk).

- [ ] **Step 1: Verify the substitution point is unchanged**

```bash
sed -n '120,130p' /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/Offline/GeometryService/src/MECOStyleProtonAbsorberMaker.cc
```

Expected to contain exactly:

```cpp
    // z of target end in mu2e coordinate
    // we add space for the virtual detector here
    double targetEnd = _target->centerInMu2e().z() + 0.5*_target->cylinderLength() + 2.*vdHL;;
```

If it does not, STOP (report BLOCKED — tree drifted).

- [ ] **Step 2: Apply the edit**

Replace that block with (keep the surrounding lines untouched; note the
stock line keeps its historical double semicolon):

```cpp
    // z of target end in mu2e coordinate
    // we add space for the virtual detector here
    double targetEnd = _target->centerInMu2e().z() + 0.5*_target->cylinderLength() + 2.*vdHL;;

    // Optional absolute pinning: when protonabsorber.zStartInMu2e is set,
    // the IPA's upstream end sits at that absolute z regardless of the
    // stopping target; distFromTargetEnd then only anchors the cone-radius
    // interpolation. Unset (default): stock target-relative behavior.
    if ( _config.hasName("protonabsorber.zStartInMu2e") ) {
      targetEnd = _config.getDouble("protonabsorber.zStartInMu2e") - distFromTargetEnd;
    }
```

(`distFromTargetEnd` is read and clamped at lines 71–77, well before this
point, so the ordering is valid.)

- [ ] **Step 3: Incremental rebuild (~30 s)**

```bash
cd /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh > /tmp/mu2e_setup_ipa.log 2>&1
muse setup > /tmp/muse_setup_ipa.log 2>&1
muse build -j 12
```

Expected: build succeeds; if compilation fails, fix the hunk (typo-level
only — any structural problem is BLOCKED).

- [ ] **Step 4: Verify both markers in the binary**

```bash
LIB=/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/build/al9-prof-e29-p101/Offline/lib/libmu2e_GeometryService.so
strings "$LIB" | grep -c "protonabsorber.zStartInMu2e"   # expect >= 1
strings "$LIB" | grep -c "holeRadii vector active"        # expect >= 1 (prior patch intact)
```

- [ ] **Step 5: Capture the standalone patch file**

```bash
cd /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/Offline
git -c safe.directory='*' diff -- GeometryService/src/MECOStyleProtonAbsorberMaker.cc > ../ipa-zstart.patch
# sanity: the patch is currently applied (reverse dry-run must succeed)
cd .. && patch -p1 --dry-run -R -d Offline < ipa-zstart.patch
```

Expected: dry-run reports the hunk would revert cleanly.
(The holeRadii patch touches only `StoppingTargetMaker.{cc,hh}` /
`GeometryService.cc`, so this per-file diff contains exclusively the new
hunk.)

- [ ] **Step 6: Hook the patch into rebuild.sh**

In `/exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/rebuild.sh`:

After the line
`PATCHFILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stoppingtarget-holeradii.patch"`
add:

```bash
PATCHFILE2="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ipa-zstart.patch"
```

After the line `patch -p1 -d Offline < "$PATCHFILE"` add:

```bash
patch -p1 -d Offline < "$PATCHFILE2"
```

In the verify section, after the existing `strings "$LIB" | grep -q "holeRadii vector active"` block, add:

```bash
strings "$LIB" | grep -q "protonabsorber.zStartInMu2e" \
  && echo "OK  - ipa-zstart patch present in the binary" \
  || { echo "FAIL - ipa-zstart patch missing from the binary"; exit 1; }
```

- [ ] **Step 7: Default-off no-op gate (real G4 via golden parity harness)**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
PYTHONPATH= .venv/bin/python tests/golden_parity.py check
```

Expected: all parity sections pass exactly as at baseline (the seam replay
runs a real preflight under this musing with no `zStartInMu2e` key
anywhere — proving option-unset output is unchanged). If the harness
fails, STOP: the patch is not a no-op.

No git commit — every file in this task lives outside the autoresearch
repo (the checkout is reproducible via `rebuild.sh` + the two patch
files).

---

### Task 2: Parity evidence pack

**Files:**
- Create: `bo_work/ipa_probe/` (scratch: probe geoms, FCLs, logs)
- Create: `docs/ipa_zstart_evidence.md` (committed)

**Interfaces:**
- Consumes: Task 1's rebuilt lib (via
  `Offline_run1bap_partial/setup_local.sh`); `modes.SPECS["foilspf"].geom.render(x)`
  (10-vector: `rOut_0..2, hT_0..2, f_0..2, extent`).
- Produces: `docs/ipa_zstart_evidence.md` — the measured table Task 5's PR
  body cites; confirmation of the constant `6901.02` that Task 3 bakes in.

- [ ] **Step 1: Render the six probe geometries**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
mkdir -p bo_work/ipa_probe
PYTHONPATH= .venv/bin/python - <<'EOF'
import re, sys
sys.path.insert(0, "core")
import modes
DEPLOYED = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287]
for ext in (400.0, 800.0, 1100.0):
    x = DEPLOYED + [ext]
    txt = modes.SPECS["foilspf"].geom.render(x)
    # control: expression as shipped (today's exact behavior)
    with open(f"bo_work/ipa_probe/geom_expr_{int(ext)}.txt", "w") as f:
        f.write(txt + "\nint protonabsorber.verbosityLevel = 1;\n")
    # option-only: strip the compensation back to stock 625, pin via the option
    stripped, n = re.subn(r"double protonabsorber\.distFromTargetEnd = [\d.]+;",
                          "double protonabsorber.distFromTargetEnd = 625.;", txt)
    assert n == 1, f"expected exactly 1 distFromTargetEnd line, found {n}"
    with open(f"bo_work/ipa_probe/geom_opt_{int(ext)}.txt", "w") as f:
        f.write(stripped
                + "\ndouble protonabsorber.zStartInMu2e = 6901.02;"
                + "\nint protonabsorber.verbosityLevel = 1;\n")
print("6 probe geoms written")
EOF
```

- [ ] **Step 2: Write one surface-check FCL per probe**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe
for g in geom_expr_400 geom_expr_800 geom_expr_1100 geom_opt_400 geom_opt_800 geom_opt_1100; do
  # activate G4 CheckOverlaps sampling (same knobs bo_driver preflight uses)
  printf '%s\n' \
    "#include \"${g}.txt\"" \
    'bool g4.doSurfaceCheck             = true;' \
    'int  g4.nSurfaceCheckPointsPercmsq = 1;' \
    'int  g4.minSurfaceCheckPoints      = 100;' \
    'int  g4.maxSurfaceCheckPoints      = 10000000;' > overlay_${g}.txt
  printf '%s\n' \
    '#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"' \
    "services.GeometryService.inputFile : \"overlay_${g}.txt\"" > probe_${g}.fcl
done
ls probe_*.fcl | wc -l   # expect 6
```

- [ ] **Step 3: Run the six probes (~2 min each)**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh > setup1.log 2>&1
source /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial/setup_local.sh > setup2.log 2>&1
export MU2E_SEARCH_PATH="$PWD:$MU2E_SEARCH_PATH"
export FHICL_FILE_PATH="$PWD:$FHICL_FILE_PATH"
for g in geom_expr_400 geom_expr_800 geom_expr_1100 geom_opt_400 geom_opt_800 geom_opt_1100; do
  mu2e -c probe_${g}.fcl -n 1 > log_${g}.txt 2>&1
  echo "$g rc=$?"
done
```

Expected: rc=0 for all six.

- [ ] **Step 4: Extract and compare**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe
grep -h "protonabs1 Z extent in Mu2e" log_*.txt
grep -c "Overlap is detected" log_*.txt
```

Expected: all six logs print the identical absorber extent
**6901.02 → 7901.02**; overlap count 0 in every log. If any `geom_opt_*`
print differs from its `geom_expr_*` twin or from 6901.02: STOP, report
BLOCKED with the actual numbers (the option or the constant is wrong —
do not adjust and continue).

- [ ] **Step 5: Write the evidence document**

Create `docs/ipa_zstart_evidence.md` with the measured content (fill the
actual printed lines, not these placeholders):

```markdown
# Evidence: protonabsorber.zStartInMu2e pins the IPA absolutely

Environment: SimJob/Run1Bap backing (Offline v13_32_10), patched
GeometryService from /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial
(patches: stoppingtarget-holeradii, ipa-zstart). Probe geometry: foilspf
deployed profile point, three stack extents. `protonabsorber.verbosityLevel=1`,
full G4 surface check enabled. Date: 2026-07-31.

| probe | mechanism | absorber Z extent printed | overlaps |
|---|---|---|---|
| extent 400, expression | distFromTargetEnd = 825.0 | <measured> | 0 |
| extent 800, expression | distFromTargetEnd = 625.0 | <measured> | 0 |
| extent 1100, expression | distFromTargetEnd = 475.0 | <measured> | 0 |
| extent 400, option only | zStartInMu2e = 6901.02, dist = stock 625 | <measured> | 0 |
| extent 800, option only | zStartInMu2e = 6901.02, dist = stock 625 | <measured> | 0 |
| extent 1100, option only | zStartInMu2e = 6901.02, dist = stock 625 | <measured> | 0 |

Default-off no-op: golden parity harness (leaderboard round-trip, history
tensor fingerprint, real-preflight seam replay with no zStartInMu2e key)
passes unchanged against the patched library.

Uncompensated stock behavior, for contrast (wiki log 2026-07-28): a
1066.67 mm stack displaces the absorber rigidly to 7034.35–8034.35.
```

- [ ] **Step 6: Commit**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
git add docs/ipa_zstart_evidence.md
git commit -m "docs(evidence): zStartInMu2e pins the IPA at 6901.02-7901.02 across target extents

Six G4 probes (3 extents x expression/option), all print identical
absorber placement with zero overlaps; golden parity confirms
default-off is a no-op.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 3: foilspf emits the option (TDD)

**Files:**
- Modify: `mode_specs/foilspf.json` (geom_lines block, after the
  `protonabsorber.distFromTargetEnd` expr line)
- Test: `tests/test_foilspf_spec.py`

**Interfaces:**
- Consumes: Task 2's confirmation of 6901.02; existing test helpers
  `_scalar(text, key)` / `_render(x)` in `tests/test_foilspf_spec.py`.
- Produces: rendered foilspf geoms contain
  `double protonabsorber.zStartInMu2e = 6901.02;`; Task 4's preflight
  probe relies on this.

- [ ] **Step 1: Write the failing test**

Append to `class TestFoilspfRegistration` (the class holding
`test_target_position_is_fixed_and_the_absorber_is_compensated` — same
class, same style; note it is Registration, not Geometry):

```python
    def test_absolute_pin_and_expression_agree(self):
        """protonabsorber.zStartInMu2e is rendered (authoritative under the
        patched GeometryService) AND agrees with the distFromTargetEnd
        expression (the fail-safe a stale/unpatched lib falls back to).
        If the two mechanisms ever disagree, a lib swap silently moves the
        absorber -- that divergence must be a test failure, not a physics
        surprise. Evidence: docs/ipa_zstart_evidence.md."""
        s = modes.SPECS["foilspf"]
        for ext in (400.0, 800.0, 1100.0):
            x = [120.0, 120.0, 120.0, 0.15, 0.15, 0.15, 0.0, 0.0, 0.0, ext]
            txt = s.geom.render(x)
            z = float(_scalar(txt, "protonabsorber.zStartInMu2e"))
            d = float(re.search(r"distFromTargetEnd = ([\d.]+)", txt).group(1))
            self.assertAlmostEqual(z, 6901.02, places=6, msg=f"extent {ext}")
            # targetEnd = z0 + extent/2 + 5 (tilt margin) + 0.02 (2*vdHL)
            self.assertAlmostEqual(5871.0 + ext / 2 + 5.02 + d, z, places=3,
                                   msg=f"mechanisms disagree at extent {ext}")
```

- [ ] **Step 2: Run it — must fail**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
PYTHONPATH= .venv/bin/python -m unittest tests.test_foilspf_spec -v 2>&1 | tail -5
```

Expected: `KeyError: 'protonabsorber.zStartInMu2e not found in render'`.

- [ ] **Step 3: Edit the spec JSON**

In `mode_specs/foilspf.json`, immediately after the line
`{"key": "protonabsorber.distFromTargetEnd", "type": "double", "expr": "ipa_dist", "fmt": "{:.6f}"},`
insert:

```json
      {"comment": "protonabsorber.zStartInMu2e 6901.02: ABSOLUTE pin, authoritative under the patched GeometryService (maker substitutes targetEnd = zStartInMu2e - distFromTargetEnd, so placement is 6901.02 exactly; see docs/superpowers/specs/2026-07-31-ipa-absolute-position-design.md). The distFromTargetEnd expression above STAYS as the fail-safe: an unpatched lib ignores this key and the expression alone still places the absorber at 6901.02 (cylindrical IPA, OutRadius0 == OutRadius1 == 300.5, so the two routes are degenerate). Consistency pinned by tests/test_foilspf_spec.py."},
      {"key": "protonabsorber.zStartInMu2e", "type": "double", "value": 6901.02},
```

- [ ] **Step 4: Run the test — must pass**

```bash
PYTHONPATH= .venv/bin/python -m unittest tests.test_foilspf_spec -v 2>&1 | tail -5
```

Expected: OK, including the pre-existing
`test_target_position_is_fixed_and_the_absorber_is_compensated`
(the expression is untouched).

- [ ] **Step 5: Full suite**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: **Ran 428**, OK.

- [ ] **Step 6: Commit**

```bash
git add mode_specs/foilspf.json tests/test_foilspf_spec.py
git commit -m "feat(foilspf): emit protonabsorber.zStartInMu2e alongside the exact expression

Option is authoritative under the patched lib; the expression stays as
the fail-safe an unpatched grid tarball falls back to (both place the
absorber at 6901.02 exactly). New invariant test pins their agreement.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 4: Grid tarball + pointer + end-to-end preflight

**Files:**
- Create: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii_ipafix.tar.bz2`
- Modify: `mode_specs/foilspf.json` (`software.grid_tarball` only)
- Create: `bo_work/proposals/foilspf/foilspfIPAPIN1100_geom.txt` (probe, not committed)

**Interfaces:**
- Consumes: Task 1's rebuilt workdir; Task 3's spec (render now emits the
  key).
- Produces: the tarball path Task 5's PR body may reference; `foilspf`
  fully live on the option.

- [ ] **Step 1: Campaign-liveness gate**

```bash
pgrep -f "closed_loop"; pgrep -f "graph[.]run"; true
```

Expected: no PIDs printed. If any appear, STOP (report BLOCKED — no
tarball/spec swaps mid-campaign).

- [ ] **Step 2: Build the tarball from the patched workdir**

```bash
cd /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh > /tmp/mu2e_setup_tb.log 2>&1
muse setup > /tmp/muse_setup_tb.log 2>&1
muse tarball 2>&1 | tee /tmp/muse_tarball_ipa.log
```

Expected: prints the output path
(`/mu2e/data/users/$USER/museTarball/tmp.<rand>/Code.tar.bz2`). A
`tar: ... .musebuild: Cannot stat` warning is cosmetic (rc=0, known).

- [ ] **Step 3: Gate — the tarball must carry the patched lib**

```bash
TB=$(grep -o '/mu2e/data/users/[^ ]*/Code.tar.bz2' /tmp/muse_tarball_ipa.log | tail -1)
mkdir -p /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe/tbcheck
cd /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe/tbcheck
LIBPATH=$(tar tjf "$TB" | grep 'libmu2e_GeometryService.so$')
echo "$LIBPATH"                       # expect one entry; if empty, STOP
tar xjf "$TB" "$LIBPATH"
strings "$LIBPATH" | grep -c "protonabsorber.zStartInMu2e"   # expect >= 1
strings "$LIBPATH" | grep -c "holeRadii vector active"        # expect >= 1
```

If either grep is 0: STOP — this is precisely the
foilsg-grid-tarball-scalar-holeradius-fallback failure class; do not move
the pointer.

- [ ] **Step 4: Install under the new name (never overwrite)**

```bash
test ! -e /exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii_ipafix.tar.bz2
cp "$TB" /exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii_ipafix.tar.bz2
ls -la /exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii*.tar.bz2
```

Expected: new file ~15 MB beside the untouched original.

- [ ] **Step 5: Point foilspf at it**

In `mode_specs/foilspf.json`, change
`"grid_tarball": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii.tar.bz2"`
to
`"grid_tarball": "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii_ipafix.tar.bz2"`.
(`foilsflash` keeps the old tarball — its geometry never sets the key.)

- [ ] **Step 6: End-to-end preflight at extent 1100 through the production path**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
PYTHONPATH= .venv/bin/python - <<'EOF'
import sys
sys.path.insert(0, "core")
import modes
x = [75.0, 75.0, 75.0, 0.0528, 0.0528, 0.0528, 0.287, 0.287, 0.287, 1100.0]
txt = modes.SPECS["foilspf"].geom.render(x)
with open("bo_work/proposals/foilspf/foilspfIPAPIN1100_geom.txt", "w") as f:
    f.write(txt + "\nint protonabsorber.verbosityLevel = 1;\n")
print("probe proposal written")
EOF
PYTHONPATH= .venv/bin/python core/bo_driver.py --mode foilspf preflight foilspfIPAPIN1100
echo "rc=$?"
grep "protonabs1 Z extent in Mu2e" bo_work/preflight/foilspf/foilspfIPAPIN1100.log
```

Expected: `rc=0` (PASS under `require_zero_overlaps`), absorber printed
at **6901.02 → 7901.02**.

- [ ] **Step 7: Suite still green**

```bash
PYTHONPATH= .venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^Ran|^OK|^FAILED"
```

Expected: Ran 428, OK.

- [ ] **Step 8: Commit**

```bash
git add mode_specs/foilspf.json
git commit -m "feat(foilspf): ship the ipa-zstart GeometryService in a new grid tarball

Code_run1bap_holeradii_ipafix.tar.bz2 (old tarball preserved); lib
verified in-tarball via strings markers before the pointer moved;
production preflight at extent 1100: rc=0, zero overlaps, absorber at
6901.02-7901.02.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 5: Upstream PR to Mu2e/Offline

**Files:**
- Create: `/exp/mu2e/app/users/oksuzian/Offline_ipa_pr/` (sparse clone of
  Mu2e/Offline main)
- Modify (in that clone): `GeometryService/src/MECOStyleProtonAbsorberMaker.cc`,
  `Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt`
- Create: `bo_work/ipa_probe/pr_body.md` (scratch)

**Interfaces:**
- Consumes: the identical hunk from Task 1 (region verified byte-identical
  between v13_32_10 and main on 2026-07-31); measured table from
  `docs/ipa_zstart_evidence.md` (Task 2).
- Produces: branch `ipa-absolute-position` on `oksuzian/Offline`; open PR
  against `Mu2e/Offline` main.

- [ ] **Step 1: Sparse clone + branch**

```bash
cd /exp/mu2e/app/users/oksuzian
git clone --filter=blob:none --no-checkout https://github.com/Mu2e/Offline Offline_ipa_pr
cd Offline_ipa_pr
git sparse-checkout init --cone
git sparse-checkout set GeometryService/src Mu2eG4/geom
git checkout main
git checkout -b ipa-absolute-position
grep -n "double targetEnd = _target" GeometryService/src/MECOStyleProtonAbsorberMaker.cc
```

Expected: the grep prints line ~126 with the exact stock line from Task 1
Step 1. If not, STOP (main drifted since 2026-07-31 — report BLOCKED).

- [ ] **Step 2: Apply the identical source hunk**

Same edit as Task 1 Step 2, in
`GeometryService/src/MECOStyleProtonAbsorberMaker.cc` (insert the 8-line
option block after the `targetEnd` line; code repeated here so this task
stands alone):

```cpp
    // Optional absolute pinning: when protonabsorber.zStartInMu2e is set,
    // the IPA's upstream end sits at that absolute z regardless of the
    // stopping target; distFromTargetEnd then only anchors the cone-radius
    // interpolation. Unset (default): stock target-relative behavior.
    if ( _config.hasName("protonabsorber.zStartInMu2e") ) {
      targetEnd = _config.getDouble("protonabsorber.zStartInMu2e") - distFromTargetEnd;
    }
```

- [ ] **Step 3: Add the documented example to the geom file**

In `Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt`, directly under the
line `double protonabsorber.distFromTargetEnd = 625.; //mu2e z positions are 6901-7901 mm`
add:

```
// Optional: pin the IPA at an absolute z, independent of the stopping
// target (see MECOStyleProtonAbsorberMaker):
// double protonabsorber.zStartInMu2e = 6901.;
```

- [ ] **Step 4: Commit as the operator**

```bash
cd /exp/mu2e/app/users/oksuzian/Offline_ipa_pr
git -c user.name="Yuri Oksuzian" -c user.email="oksuzian@gmail.com" commit \
  -m "Add optional protonabsorber.zStartInMu2e: absolute IPA position

The MECO-style inner proton absorber is placed relative to the stopping
target (targetEnd), but it is fixed hardware -- the geometry file itself
documents 'mu2e z positions are 6901-7901 mm'. Studies that vary the
stopping-target geometry silently drag the absorber (and its support-wire
rings) with it. When the new key is set, the maker derives its reference
plane from the given absolute z instead of the live target; unset, the
code path is untouched and output is bit-identical.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c" \
  -- GeometryService/src/MECOStyleProtonAbsorberMaker.cc Mu2eG4/geom/protonAbsorber_cylindrical_v04.txt
```

- [ ] **Step 5: Push to the fork (gh credential helper, NOT ssh)**

```bash
git remote add fork https://github.com/oksuzian/Offline
git -c credential.helper='!gh auth git-credential' push fork ipa-absolute-position
```

If this fails with an auth error: report the failure and print, for the
operator to run from their interactive shell:
`cd /exp/mu2e/app/users/oksuzian/Offline_ipa_pr && git push git@github.com:oksuzian/Offline ipa-absolute-position`
— then stop this task as DONE_WITH_CONCERNS (the PR step below can be
rerun after the manual push).

- [ ] **Step 6: Open the PR**

Write `bo_work/ipa_probe/pr_body.md` (fill the table rows from
`docs/ipa_zstart_evidence.md` — real measured lines, no placeholders):

```markdown
## Motivation

The MECO-style inner proton absorber is placed relative to the stopping
target: `MECOStyleProtonAbsorberMaker` computes `targetEnd` from the live
`StoppingTarget` and derives everything from it — body placement, DS2/DS3
segmentation, the cone-radius interpolation anchor, and the IPA
support-wire ring positions. But the IPA is fixed hardware;
`protonAbsorber_cylindrical_v04.txt` itself documents
`distFromTargetEnd = 625.; //mu2e z positions are 6901-7901 mm`.

Anyone varying stopping-target geometry gets a silently displaced
absorber. In our stopping-target optimization study a longer foil stack
dragged the IPA 133.33 mm downstream as a rigid body (measured with
`protonabsorber.verbosityLevel = 1`: 7034.35–8034.35 vs the design
6901.02–7901.02) through 414 grid evaluations before it was noticed. For
a cylindrical IPA this is exactly compensable by adjusting
`distFromTargetEnd`; for the conical variant it is not (the taper anchor
moves with the target) — hence a first-class option.

## Change

New optional key `protonabsorber.zStartInMu2e`. When present, the maker
derives its reference plane from the given absolute z
(`targetEnd = zStartInMu2e - distFromTargetEnd`), so the absorber's
upstream end lands exactly at the given z and its full geometry (length,
DS2/DS3 split, cone radii, support wires) is independent of the stopping
target. When absent — the default everywhere — the new branch never
executes and output is bit-identical to today. One commented example
added to `protonAbsorber_cylindrical_v04.txt`.

## Validation (Offline v13_32_10 + SimJob/Run1Bap backing)

Six single-event G4 runs with full surface check
(`protonabsorber.verbosityLevel = 1`), stopping-target stack extents
400 / 800 / 1100 mm, each extent probed twice — config-compensated
`distFromTargetEnd` (no new key) vs stock 625 + `zStartInMu2e = 6901.02`:

<table rows from docs/ipa_zstart_evidence.md>

All six print the identical absorber extent 6901.02–7901.02 with zero
overlaps. With the key unset, a golden-parity harness (real G4 preflight
replay) reproduces baseline output unchanged.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c
```

Then:

```bash
cd /exp/mu2e/app/users/oksuzian/Offline_ipa_pr
gh pr create -R Mu2e/Offline --base main --head oksuzian:ipa-absolute-position \
  --title "Add optional protonabsorber.zStartInMu2e: absolute IPA position" \
  --body-file /exp/mu2e/app/users/oksuzian/autoresearch/bo_work/ipa_probe/pr_body.md
```

Expected: PR URL printed. Report it.

- [ ] **Step 7: Record the PR URL**

Append the PR URL as a final line of `docs/ipa_zstart_evidence.md` and
commit:

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
git add docs/ipa_zstart_evidence.md
git commit -m "docs(evidence): link the upstream Mu2e/Offline PR

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```
