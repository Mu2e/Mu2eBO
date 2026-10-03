---
type: project
title: ptg4bl — production target on G4beamline through beamkit
description: The first G4beamline study on the contract engine (2026-10-02). A bare tungsten production-target rod whose length and 3-point outer-radius profile are knobs (a polycone on deck branch ptarget-polycone), scored by μ⁻+π⁻ per POT crossing Coll_01_DetIn (unique tracks), maximized; kit beamkit (core/adapters/beamkit.py), grid only; built and tested against a fake beamkit, grid acceptance pending the deck branch's push to the operator's fork
status: active
status_note: grid acceptance passed 2026-10-02 (rows ptgnom02, ptgrmid02); campaigns run on leaderboard_bo_ptg4bl_5k.tsv at 100k POT per point
timestamp: '2026-10-02'
---

# ptg4bl — production target on G4beamline through beamkit

## Summary
`mode_specs/ptg4bl.json` is the first study the contract engine runs on G4beamline rather than Offline. It is the first real case of piece 4 of the study-writing line: a configuration a study file alone could not express. It needed a deck change, a new kit and its own figure of merit.

- **The target:** the deck's tungsten rod (`Use_Proton_Target=4`, bare, with no bicycle-wheel supports) becomes a G4beamline `polycone`. Its length and three outer radii (upstream end, middle, downstream end, linear between) are knobs.
- **The objective:** μ⁻ (PDG 13) plus π⁻ (−211) crossing the `Coll_01_DetIn` virtual detector (COL1's upstream face, the transport-solenoid entrance; the deck places `Coll_01_Det` twice, renamed `…In`/`…Out`, and g4bl names the NTuples so), per proton on target, maximized.

## Key facts
- **Deck:**
  - branch `ptarget-polycone` of G4BeamlineScripts, commit `17bc967238ae3f88ce3610a5e197bbae3b3c63bb`, built on `epsmax-0.01` (adba281: current Geant4 rejects g4bl's default eps_max 0.05);
  - pushed by the operator to their GitHub fork, which is the study's `deck_url`;
  - in `Geometry/Proton_Target_W.txt`, `Tlength`, `R_up`, `R_mid` and `R_dn` are `param -unset`, with defaults that keep today's rod (160 mm, radius 3.1495 mm). A command-line value wins only over `-unset`; a plain `param` line overrides it.
- **Override verified locally (2026-10-02):**
  - **The run:** g4bl 3.08b, via the worker's recipe: `source setupmu2e-art.sh; eval "$(spack load --sh g4beamline)"`. With `Num_Events=0 Use_Proton_Target=4 R_mid=2.0` it echoed `polycone pTarget innerRadius=0,0,0 outerRadius=3.1495,2.0,3.1495`, and Geant4's overlap check on pTarget was OK.
  - **The warnings:** the other G4Exceptions in that log (transport-solenoid pipe overlaps, extrusion vertices, a duplicated triton decay) are existing deck warnings.
  - **No `printf`:** g4bl's `printf` is a per-track print element, not a parse-time echo. g4bl already echoes every command with its values, so the job log itself shows what reached the target.
- **Knobs:** `Tlength` 100–220 mm, and `R_up`, `R_mid`, `R_dn` 2.0–4.5 mm. Fixed deck params: `Use_Proton_Target=4`, `epsMax=0.01`.
- **Step:** one step, `g4bl`, with 20 jobs × 1,000 POT, quorum 0.9, plane `Coll_01_DetIn`, pdg [13, −211]. `R_up` is at local −z, the Mu2e-upstream end where the protons (travelling along −z) leave the rod.
- **The figure of merit** is counted by the adapter (`count_tracks`):
  - unique `(file, EventID, TrackID)` per file, since a track looping in the solenoid field crosses a virtual detector more than once;
  - divided by POT = files × `events_per_job`;
  - metrics `yield_per_pot`, `n_selected`, `pot`, `n_files`;
  - `FOM_VERSION` is in the kit version, so a changed count changes `measure_sha`.
- **Objective:** `mu_pi_per_pot`, maximized, no transform, with a provisional `noise` of 0.002 until the nominal point measures the Poisson σ. No constraint, so campaigns use `--picker qlnei`, which uses the primary objective.
- **Board:** `leaderboards/leaderboard_bo_ptg4bl_5k.tsv` at 20 × 5000 POT per point; `measure_basis_sha` b52fce7c.
  - The 20k-POT acceptance rows stay on `leaderboard_bo_ptg4bl.tsv`, outside the training set.
  - Earlier fingerprints: 43edef92, then 24be5167, then 4f6a450b for the acceptance rows.
- **The plane is a tree path,** `VirtualDetector/Coll_01_DetIn`. g4bl writes a virtualdetector under `VirtualDetector/<name>`; `NTuple/` holds only zntuples (Z3712, LostInTarget_Ntuple). That was seen in the first grid files: 47 keys, with branches x y z Px Py Pz t PDGid EventID TrackID ParentID Weight, float32.
- **Acceptance protocol** (grid, after the push, Kerberos ≥ 4 h):
  1. the nominal point (160, 3.1495 ×3) lands a row, and measures the yield, the time per job and σ;
  2. `R_mid=2.0`: the job logs echo `outerRadius=3.1495,2.0,3.1495`;
  3. the noise is set from σ;
  4. campaigns only on the operator's word (`start_campaign`: a dry run, then confirm; q=5, max_evals=20).

## Grid acceptance (2026-10-02)
- **Attempt 1 submitted nothing.**
  - **Cause:** the beamkit server lacked `OTEL_EXPORTER_JAEGER_ENDPOINT`, which a login shell gets from `/etc/profile.d/jobsub_lite.sh`. Without it, `jobsub_q` prints "Note: tracing not available here… Continuing without tracing…" into its table. prodtools' strict queue-table parser then refused the count ("top-up: queue count failed"), the first tick (rc 2) submitted no jobs, and beamkit returned the run as `needs_attention`, not as an error.
  - **Fix:** `kits.toml` passes the `OTEL_*` pair, and the adapter refuses a non-`submitted` reply with the tick's own words.
  - **The empty campaigns** (19, 20) were then submitted with `make_recoveries`. That covers the whole personal ledger: it reported "the verify/recovery pass covered every active campaign in this ledger".
- **Attempt 2: the jobs ran,** 40/40 at 1000 events per job in about 502 s (0.5 s per proton), but `results` failed on the `NTuple/` path. That was fixed, and the points were rerun under new names, because the plane change moved the fingerprint and the engine rightly refuses such a resume.
- **The override is confirmed on the grid:** job logs echo `polycone pTarget innerRadius=0,0,0 outerRadius=3.1495,2.0,3.1495` for R_mid=2.0, and `3.1495,3.1495,3.1495` for the nominal.
- **Rows, at 20k POT:**

  | point | μ⁻+π⁻ per POT | n |
  |---|---|---|
  | `ptgnom02` | 0.03985 | 797 |
  | `ptgrmid02` (R_mid = 2.0) | 0.04045 | 809 |

  The first batch, counted offline, gave 0.0415 and 0.0380. σ ≈ 0.0014 (3.5%), so R_mid=2.0 cannot be resolved at 20k POT. Hence 100k POT per point from here.

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (the beamkit adapter), [service](/drivers/service.md) (start_campaign), [production-target-stickman](/concepts/production-target-stickman.md) (the Offline production target), [bo-prodtarget](/projects/bo-prodtarget.md) (the Offline-side design)
- Source files: `mode_specs/ptg4bl.json`, `core/adapters/beamkit.py`, `tests/test_beamkit_kit.py`, `tests/fakebeamkit.py`
- Spec: `docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md`; plan: `docs/superpowers/plans/2026-10-02-g4bl-ptarget.md`

## Open questions / TODO
- The next piece: a "design a new study" recipe drawn from this design (operator's OK, 2026-10-02).
