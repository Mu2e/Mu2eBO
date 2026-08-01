# Evidence: protonabsorber.zStartInMu2e pins the IPA absolutely

Environment: SimJob/Run1Bap backing (Offline v13_32_10), patched
GeometryService from /exp/mu2e/app/users/oksuzian/Offline_run1bap_partial
(patches: stoppingtarget-holeradii, ipa-zstart). Probe geometry: foilspf
deployed profile point, three stack extents. `protonabsorber.verbosityLevel=1`,
full G4 surface check enabled. Date: 2026-07-31.

| probe | mechanism | absorber Z extent printed | overlaps |
|---|---|---|---|
| extent 400, expression | distFromTargetEnd = 825.0 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |
| extent 800, expression | distFromTargetEnd = 625.0 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |
| extent 1100, expression | distFromTargetEnd = 475.0 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |
| extent 400, option only | zStartInMu2e = 6901.02, dist = stock 625 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |
| extent 800, option only | zStartInMu2e = 6901.02, dist = stock 625 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |
| extent 1100, option only | zStartInMu2e = 6901.02, dist = stock 625 | constructProtonAbsorber protonabs1 Z extent in Mu2e    : 6901.02, 7901.02 | 0 |

Default-off no-op: the three expression probes above run the patched library with NO zStartInMu2e key anywhere in the geometry, and reproduce the pre-patch measurements of 2026-07-28 (absorber at 6901.02-7901.02, zero overlaps — recorded in wiki/log.md and mode_specs/foilspf.json before this patch existed). Same geometry, same prints, before and after the library change.

Uncompensated stock behavior, for contrast (wiki log 2026-07-28): a
1066.67 mm stack displaces the absorber rigidly to 7034.35–8034.35.

Upstream PR: https://github.com/Mu2e/Offline/pull/1913
