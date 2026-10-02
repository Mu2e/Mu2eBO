# A first G4beamline study: the production target, through beamkit

Date: 2026-10-02. Status: draft for review.

- **Branch:** `g4bl-ptarget` (from `generic-study-phase-c1` 1c8c14c), worktree `../autoresearch-checkstudy`.
- **Place in the study-writing line:** piece 4, geometry and physics changes that a study file alone cannot express. This is its first real case.
- **Framework plan:** phase 2, "a G4beamline engine through beamkit", in its narrowed form. The engine is already generic over kits, so this needs a beamkit adapter, not a second engine. Deck parameters stand in for a geometry writer, as `docs/superpowers/specs/2026-09-23-generic-study-design.md` (beamkit adapter, phase D) and the framework review's roadmap step 3 already proposed.

## Goal

A production-target study runs on the contract engine through beamkit and lands leaderboard rows:
- **the target:** a tungsten rod whose length and radius profile are knobs;
- **the objective:** μ⁻+π⁻ per proton on target at the transport-solenoid entrance, maximized.

## Decisions taken (operator, 2026-10-02)

- **First piece-4 case:** G4beamline via beamkit.
- **Study:** the production target. Figure of merit: μ⁻ (PDG 13) plus π⁻ (PDG −211) crossing the `Coll_01_Det` virtual detector, per POT, maximized.
- **Where the FoM is computed:** in the beamkit adapter itself (one step), with the plane and particle list given by the study file.
- **Radius profile:** three control radii along the target, made a G4beamline `polycone`, so the radius is linear between them.
- **The rod is bare:** `Use_Proton_Target=4`, so no support geometry has to follow the profile.
- **Deck:** a study branch on the operator's GitHub fork of `G4BeamlineScripts`, pushed by the operator, pinned by sha.
- **Follow-up, not in this spec:** a "design a new study" recipe (an MCP prompt on the `autoresearch` server plus a README checklist), drawn from this design and tested against a no-recipe baseline first.

## What changes

### The deck branch (operator's fork, `G4BeamlineScripts`)

In `Geometry/Proton_Target_W.txt`:
- `tubs pTarget outerRadius=$Tradius length=$Tlength` becomes `polycone pTarget z=-$Tlength/2,0,$Tlength/2 innerRadius=0,0,0 outerRadius=$R_up,$R_mid,$R_dn`, with the same `place`.
- `Tlength`, `R_up`, `R_mid` and `R_dn` are declared `param -unset`, with today's values as defaults (160, and 3.1495 for all three). A command-line value then wins; a plain `param` line would override it.
- `R_up` is the radius at the upstream end (local z = −Tlength/2), `R_dn` at the downstream end.
- The `Use_Proton_Target==5` support block keeps using `R=$Tradius` (left at 3.1495), and is unused with 4.
- A `printf "ptarget: Tlength=%g R_up=%g R_mid=%g R_dn=%g" $Tlength $R_up $R_mid $R_dn` line puts the values in effect into every job log, the proof that the command line reached the target.

The branch also carries the `epsMax=0.01` fix (local commit adba281). Current Geant4 rejects g4bl's 0.05 default. The study pins the branch's sha as `deck_ref` and the fork as `deck_url`.

### `kits.toml`: `[servers.beamkit]`

- **Command:** `${AUTORESEARCH_BEAMKIT}/.venv/bin/beamkit-mcp`.
- **`set`:** `BEAMKIT_PRODTOOLS_ROOT = "${AUTORESEARCH_PRODTOOLS}"` (the dev checkout, as the existing beamkit runs used; the cvmfs prodtools has no MCP venv).
- **`env_passthrough`:** `KRB5CCNAME`, `XDG_RUNTIME_DIR` and the `JOBSUB_*` site settings, as `prodtools_write`.
- **Timeouts:** `run_beamline` 900, `beamline_status` 120, `beamline_outputs` 120.
- **Environment:** `activate.sh` exports `AUTORESEARCH_BEAMKIT`, defaulting to the sibling `../beamkit` when it exists, like the other kits.

### `core/adapters/beamkit.py`: `BeamkitKit`

The constructor is `BeamkitKit(campaign, *, executor, parallel)`. It is registered in `kit_registry.KITS` as `KitDecl("beamkit", ...)` with:
- `executors=("grid",)`: beamkit has no local executor;
- `requires_kerberos=True`;
- `names_runs_after_config=True`;
- `uses_entries=False`, `step_kit=True`, `check_kit=False`.

**Settings:**
- **`study_keys`** (`kits.beamkit`):
  - `deck_url` (string);
  - `deck_ref` (a 40-hex sha);
  - `main_input` (string, "Mu2E.in");
  - `deck_params`: a table of fixed deck parameters, name to number or string, with names `[A-Za-z_]\w*`. beamkit's reserved names (`First_Event`, `Num_Events`, `histoFile`, `viewer`) are refused.
- **`fixed_keys`:**
  - `njobs`, `events_per_job`;
  - `quorum` (required);
  - `plane` (required, string);
  - `pdg` (required, a list of integers).

**The contract:**
- **`submit(name, params, ...)`:**
  - **Tag:** the tag is the name with everything outside `[A-Za-z0-9]` removed, plus the first 6 hex of its sha256. Unique by construction; beamkit's desc allows only letters and digits.
  - **dsconf:** beamkit's default, the deck sha7. The tag already makes the dataset unique.
  - **Deck params:** the knobs, mapped by the step's `params` and given as `repr(float(value))`, plus `deck_params`.
  - **The call:** `run_beamline(tag, run_as="self", deck_url, deck_ref, main_input, params, njobs, events_per_job, outloc="scratch", submit=True)`. It returns the name.
  - **Adoption:** a per-step record (`<grid data>/<config>/state/<step>_beamkit.json`, holding run_id, tag and submit time) is written before the call. A second submit of the same name adopts the run.
- **`status`:** from `beamline_status(run_id)` (prodtools `campaign_status`, with its queue and outputs blocks):
  - **working** while any job of the campaign is idle or running;
  - **completed** when none is, and the run's output files number at least `ceil(quorum × njobs)`;
  - **failed** otherwise, with "k of n files, m held". Held jobs never finish on their own.
  - **A queue block that cannot be read** is working, with its reason. After 6 hours it fails, the same limit the prodtools adapter uses.
  - `make_recoveries` is never called: it acts on the whole ledger.
- **`results`:**
  - **The files:** the run's files from `beamline_outputs`, read from their `/pnfs` paths with uproot.
  - **The count:** every row of the `NTuple/<plane>` tree whose `PDGid` is in `pdg`.
  - **POT:** `n_files × events_per_job`, each event being one proton.
  - **Metrics:** `yield_per_pot = count / pot`, `n_selected`, `pot`, `n_files`; the files go back as FileRefs.
  - **Refusals** (`KitError`, never a partial count): a file without the plane's tree, a file uproot cannot open, or zero POT.
- **`version`:** `"beamkit <server version>; fom <FOM_VERSION>"`. Changing the counting code bumps `FOM_VERSION`, so `measure_sha` changes and an old board refuses the new measurement.
- **`cancel`:** not offered by beamkit. It returns the current state, and says that grid jobs must be removed by hand.

### `mode_specs/ptg4bl.json`

- **Header:** `schema: 2`, `name: "ptg4bl"`, `geom: null`, `preflight: null`, `derive: {}`.
- **Knobs** (fmt `"{:.3f}"`):
  - `Tlength` 100–220 mm;
  - `R_up`, `R_mid`, `R_dn` 2.0–4.5 mm.
- **`kits.beamkit`:**
  - the fork's `deck_url` and `deck_ref`;
  - `main_input: "Mu2E.in"`;
  - `deck_params: {Use_Proton_Target: 4, epsMax: 0.01}`.
- **One step** `g4bl` (kit `beamkit`):
  - `params`: the four knobs by name;
  - `fixed: {njobs: 20, events_per_job: 1000, quorum: 0.9, plane: "Coll_01_Det", pdg: [13, -211]}`.
- **Objective:**
  - `{name: "mu_pi_per_pot", metric: "g4bl.yield_per_pot", direction: "max", transform: "none", fmt: "{:.5f}"}`;
  - `noise: 0.002` at first (2% of a yield near 0.1, provisional); after acceptance step 1 it becomes the measured Poisson σ, before any campaign.
- **Extra metrics:** `n_selected`, `pot`.
- **No constraint.**
- **Board:** `leaderboards/leaderboard_bo_ptg4bl.tsv`.
- **Launch:** campaigns use `--picker qlnei`. It uses the primary objective only, which suits a single-objective study.

## Error handling

Every failure is a `KitError` with beamkit's or uproot's text:
- an unfetchable deck sha;
- a missing Kerberos ticket or token;
- too few files;
- a missing tree;
- zero POT.

Nothing is retried silently, and nothing is resubmitted by the adapter.

## Testing

- **A scripted fake beamkit server** (`tests/fakebeamkit.py`, the toykit pattern). It offers `run_beamline`, `beamline_status` and `beamline_outputs`, records calls, and lets tests set the queue and output counts. Tests:
  - submit is idempotent by name;
  - the tag is unique for names that differ only in `_` or `.`;
  - the status rule: busy queue, quorum met, quorum missed with held jobs, unreadable queue;
  - the reserved deck-param names are refused.
- **A small nts file written with uproot in the test,** two files of known rows:
  - the count takes only the listed PDG ids at the listed plane;
  - POT is files × `events_per_job`;
  - a file without the plane's tree is a `KitError`.
- **The study:** `ptg4bl.json` loads; `check_study` passes its load, artifacts and launch checks with the fake server; `graph.run` against the fake server lands a row in a temporary data root.
- **Whole suite:** green, and every existing `measure_basis_sha` unchanged.

## Acceptance (the operator's fork pushed; grid; Kerberos)

1. **The nominal point** (Tlength 160, all radii 3.1495) through `graph.run` lands a row. It records the yield per POT, the counts, the wall time per job (from the job logs), and the Poisson σ, which becomes the objective's `noise`.
2. **The override check:** a point with `R_mid = 2.0`. Its job logs show `ptarget: … R_mid=2` (the deck's `printf`), and the nominal point's show `R_mid=3.1495`. That proves the command-line value reaches the polycone. Both yields are recorded; no threshold, since a difference in physics is not guaranteed at 20k POT.
3. **Campaigns** come only on the operator's word, through `start_campaign`: a dry run, then confirm. The first proposed is q=5 and max_evals=20, with `--picker qlnei`.

## Records

- **Wiki:**
  - `projects/bo-ptg4bl.md` for the line;
  - a beamkit-adapter section in `drivers/contract-engine.md`;
  - the `log.md` and `index.md` lines.
- **`mode_specs/README.md`:** the deck-param route (`param -unset`, a pinned deck branch) as a third way a knob can reach the simulation.
- **Memory.**

## Not in scope

- A geometry writer for G4beamline (`g4bl_include`) and beamkit `extra_files`.
- NERSC.
- `make_recoveries`.
- A G4beamline geometry pre-check.
- Several FoM planes.
- The "design a new study" recipe (next piece).
