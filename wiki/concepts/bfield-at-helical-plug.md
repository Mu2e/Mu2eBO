# B-field & helix kinematics at the helical-plug region

**Type:** concept
**Status:** active
**Updated:** 2026-05-26

## Summary
The helical plug sits in the **graded TS5→DS field-transition region**, NOT in the
flat-DS plateau, and its geometric twist rate is **5–10× faster than the kinematic
gyration rate** of sub-50 MeV/c muons traversing it. Together these break the
"matched-pitch absorber" mental model that has been carried in `bo-helical.md`
since the project started. The plug is empirically functioning as an
**azimuth-randomizing thin-ribbon Coulomb-scatter / small-dE/dx swallow**,
not as a pitch-resonant filter.

## Key facts

### B-field profile (Agent A, 2026-05-26)
- **Map file**: `/cvmfs/mu2e.opensciencegrid.org/DataFiles/BFieldMaps/Mau13/DSMap_altDS11_helical.txt`
  (the helical-plug variant of Mau13; named for this geometry).
- **Wired via**: `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v10_38_00/Offline/Mu2eG4/geom/bfgeom_reco_altDS11_helical_v01.txt`.
- **DS axis**: `X=-3904, Y=0` (`TransportSolenoid_v02.txt:ts.xRing`).
- **On-axis Bz across plug z=4050–4900 mm**: **1.94 T → 1.74 T (10% drop)**;
  mean gradient on-axis `dBz/dz ≈ −0.23 T/m`. The plug occupies the **steep
  upstream half** of the TS5→DS ramp (full ramp is ~2.06 T → ~1.0 T from
  z≈3500 to z≈13000).
- **Br off-axis**: ~1.4e-3 T at r=8 mm (negligible); scales linearly with r,
  so ~3e-2 T at r=200 mm (plug outer-radius scale) — non-trivial for the
  orbit but small vs Bz.

### Larmor radius + pitch (Agent B, 2026-05-26)
- `r_L [mm] = p_⊥ [MeV/c] / (0.3 · B [T])`,
  `pitch [mm] = 2π · p_z [MeV/c] / (0.3 · B [T])`.

| p (MeV/c) | r_L @ 1T | pitch @ 1T |
|---|---|---|
| 10 | 33 | 209 |
| 30 | 100 | 628 |
| **50** | **167** | **1047** |

- r_L at 50 MeV/c (~167 mm) is comparable to the empirical-optimum plug
  `dy ≈ 109 mm` (`bo-helical.md:64`) — consistent with the basic
  geometric-comparability premise.
- BUT pitch at 50 MeV/c in 1 T is **~1 m**, while the plug halflength is
  200–290 mm → a single muon executes **at most ¼ helix turn** inside the
  plug, whereas the plug itself does **1.4–2 full geometric twists**
  (angle ≈ 470–720°). Geometric twist rate >> kinematic gyration rate.

### Adiabaticity
- ε = (r_L/B)·|dB/dz| ≈ 0.05 at 30–50 MeV/c → adiabatic. Helix is **locally
  clean** (well-defined gyration each turn), but μ = p_⊥²/(2mB) is conserved,
  so p_⊥² ∝ B(z): as the muon enters DS from TS5 (2.06 → 1.0 T), p_⊥
  drops by √2 — magnetic-mirror effect. Across the plug span alone
  (1.94 → 1.74 T), p_⊥ drops by ~√(1.94/1.74) ≈ 1.06× — small but
  nonzero. **The Larmor radius is monotonically shrinking while the muon
  transits the plug.**

### Implication for the BO physics premise
- The mental model in `wiki/projects/bo-helical.md:71-74` ("Larmor-pitch-matched
  charged particles see ≈constant material; mismatched integrate ~50% on average")
  **assumes geometric twist rate ≈ kinematic gyration rate**. It doesn't.
  Geometric twist is ~5–10× faster.
- The plug behaves more like an **azimuth-randomizing twisted ribbon**: a muon
  sees only a small slice (<¼ turn) of its own helix while the ribbon spins
  multiple times beneath it. The mean Coulomb scatter / dE/dx depends on the
  (p_⊥/p_z) ratio because that sets transverse path through ribbon, but is
  NOT pitch-resonant in any peaked sense.
- This is consistent with the BO empirically driving **dx → 0.01 mm** (thin
  ribbon, fast twist) — the optimizer found a Coulomb-scatter + dE/dx
  swallow, not a pitch-matched absorber. If the matched-pitch model were
  load-bearing we'd see a sharp peak in the (dx, dy, angle) basin at the
  pitch-matched value; instead the response is monotonic in twist density
  (`bo-helical.md:273-279`, helical028/029 angle-only A/B at fixed sob
  shows calo varying 15× monotonically).

## Cross-links
- Related: [[bo-helical]], [[tsda]], [[scalarized-objective]], [[gp-cloud-rendering]]
- Source files: `/cvmfs/mu2e.opensciencegrid.org/DataFiles/BFieldMaps/Mau13/DSMap_altDS11_helical.txt`,
  `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v10_38_00/Offline/Mu2eG4/geom/bfgeom_reco_altDS11_helical_v01.txt`,
  `/cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v10_38_00/Offline/Mu2eG4/geom/TransportSolenoid_v02.txt`
- External: Mau13 field-map series docs (Mu2e-doc-db)

### Empirical consistency with top-3 obj configs (2026-05-26)
The Coulomb-scatter + azimuth-mix model predicts (a) thin ribbon, (b) fast geometric
twist relative to muon pitch, (c) no sharp resonance, (d) dy matched to muon r_L
scale to set "which orbits clip the ribbon." Top-3 obj leaders (L02, graph023,
helical050a) — see [[bo-helical]] champion section — agree on all four:

| prediction | top-3 measurement |
|---|---|
| thin ribbon | dx ∈ {0.01, 0.07, 0.11} mm |
| twist period ≪ muon pitch (1m) | twist period (2·hl/(angle/360)) ≈ 153–196 mm, ~5× shorter than 1 m muon pitch at 50 MeV/c |
| no sharp resonance, broad basin | top-3 cluster in 20%-wide twist-density basin (1.83–2.36 °/mm) |
| dy ≈ r_L at typical muon momentum | dy ∈ {108.6, 102.0, 109.6} mm = r_L(~30–33 MeV/c, 1 T) |

The **dy=109 mm** convergence is the load-bearing prediction the new model
*adds* over a pure-scatter picture: pure scatter would be dy-insensitive,
but the BO selecting dy = r_L(30–33 MeV/c) suggests the ribbon's radial
extent is tuned to intercept a specific calo-background-producing momentum
band — particles whose Larmor circle just barely clips the ribbon turns
get hit ~once per gyration, particles with much smaller or much larger r_L
either fit between the turns or miss entirely.

## Open questions / TODO
- Reframe `bo-helical.md` "Key facts" section to describe the filter as a
  Coulomb-scatter / dE/dx swallow with azimuth-randomization, not as a
  pitch-matched absorber.
- Empirically test the reframing: if the plug is dE/dx + Coulomb + azimuth-mix,
  the (sob, calo) response should depend mostly on (dx × turn_density), not
  on a special pitch-matched (dy, angle) combination. The current top-3
  (L02/graph023/helical050a) all cluster in dy~100-110, hl~200-260, ang~460-480,
  which IS a single basin — but is that because of dE/dx geometry alone, or
  is there residual pitch-match preference? An angle-sweep at fixed (dx, dy, hl)
  would resolve it.
- Investigate whether the muon p_z distribution at the plug entrance is
  strongly forward-peaked. If p_z >> p_⊥, pitch is even longer than the 1 m
  quoted (which assumed full momentum is transverse), strengthening the
  "<¼ turn in plug" conclusion.
