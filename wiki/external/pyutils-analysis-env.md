# Mu2e pyutils — analysis environment + run recipe

**Type:** external
**Status:** active
**Updated:** 2026-07-01

## Summary
[Mu2e/pyutils](https://github.com/Mu2e/pyutils) is the Mu2e Python analysis toolkit
for **EventNtuple** (uproot/awkward based). It's the standard way to read Mu2e
ntuples into awkward arrays and run cuts/plots/MC-truth analysis without bespoke
ROOT boilerplate. This page is the **verified run recipe in this environment**
(confirmed 2026-06-26), so a future session doesn't re-derive it.

## Key facts
- **Setup (verified working):**
  ```bash
  source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh   # = mu2einit
  pyenv ana                                                  # → pyutils + uproot + awkward
  # pyenv ana 2.7.0  → pin a version;  pyenv rootana → PyROOT variant
  ```
  `pyenv` is a **Mu2e shell function** defined by setupmu2e-art.sh (NOT the
  python-version-manager pyenv). After `pyenv ana`: Python **3.12.13**, pyutils
  **2.7.0**, uproot 5.7.4, awkward 2.9.1, from
  `/cvmfs/mu2e.opensciencegrid.org/env/ana/2.7.0/lib/python3.12/site-packages/pyutils/`.
- **GOTCHA — CWD import shadowing:** there is a personal fork clone at
  `/exp/mu2e/app/users/oksuzian/EAF/pyutils` (the user's `oksuzian/pyutils`,
  branch `pyutils_oksuzian060425`, **v1.0.0**, with a `pyutils/` subdir). Running
  `python` *from inside* that dir imports the local 1.0.0 fork instead of CVMFS
  2.7.0 (Python CWD-first import). Run from anywhere else to get 2.7.0. The fork
  is for `pip install -e . --user` dev work only.
- **Primary interface** = `pyutils.pyprocess.Processor`:
  - ctor: `Processor(tree_path='EventNtuple/ntuple', use_remote=False,
    location='tape', schema='root', verbosity=1, worker_verbosity=0)`
    (`location` ∈ tape|disk|scratch; `use_remote=True` for xrootd).
  - single entry point: `process_data(file_name=None, file_list_path=None,
    defname=None, branches=None, max_workers=None, custom_worker_func=None,
    use_processes=False)` → awkward arrays for the requested `branches`. Pass ONE
    of file_name / file_list_path / defname (SAM/metacat dataset).
  - `Skeleton` class = template for complex analyses; `get_file_list()` lists files.
- **Modules:** `pyread` (uproot read), `pyprocess` (Processor/parallel),
  `pyimport` (TTree→awkward), `pydask` (Dask distributed), `pyplot`, `pyprint`,
  `pyselect` (cut masks), `pycut` (CutManager), `pyvector` (3-vectors),
  `pymcutil` (MC truth), `pycalo`, `pydisplay` (EventDisplay), `pylogger`.
- **Examples:** `EAF/pyutils/examples/{pyutils_basics,pyutils_multifile,pyutils_on_EAF}.ipynb`.

## EventNtuple normalization gotcha (2026-06-26) — reco-filtered, NO gen count
Attempting a from-data Mu2e sensitivity from the MDC2025ar EventNtuples hit a hard
wall: **the ntuples are reconstruction-filtered and carry no generated-event count.**
- File contents (uproot `keys(recursive=True)`): `EventNtuple/ntuple` (TTree),
  `version` (TH1I, e.g. 6.11.0), and **`n_proc_events`** (TH1I) = *processed* events
  only (= the filtered ntuple count, e.g. 20625/file for CeMLeadingLogOnSpill).
  **No genCountLogger / genCount / POT object.** (Verified 2026-06-26.)
- **CORRECTION (2026-06-26): genCountLogger IS a real EventNtuple feature — it's just
  config-toggled-OFF in this production.** It's the `GenEventCountReader` module
  (`Mu2e/EventNtuple fcl/prolog.fcl`: `genCountLogger: {module_type: GenEventCountReader}`),
  part of the EventNtuple EndPath; `from_mcs-primary.fcl` / `from_mcs-Run1B.fcl`
  explicitly "add back genCountLogger", `from_mcs-mockdata.fcl` "removes genCountLogger".
  When enabled it writes the generated-event count into the ntuple file as its own
  top-level histogram. **Empirically ABSENT from all 5 `MDC2025ar_best_v1_1` datasets
  checked** (CeMLeadingLog OnSpill+Mix1BB, DIOtail95, CosmicSignal, RPCInternal): every
  one has only the `EventNtuple/` dir with `n_proc_events`, no genCount hist. The
  `_best_v1_1` naming = a curated skim/resample, which drops the `GenEventCount` SubRun
  product that GenEventCountReader needs → genCountLogger silently produces nothing.
- **RESOLVED (2026-06-30): gencount IS recoverable via SAM `dh.gencount`; there's a working framework.**
  My "not recoverable / re-ntuple / resampling-breaks-it" claims below were WRONG — I
  was looking at ROOT objects + metacat, but the generated count lives in **SAM
  metadata `dh.gencount`** (set by `GenEventCounter`, [[mu2e-offline]]
  `EventGenerator/src/GenEventCounter_module.cc`), **inherited downstream to the nts
  files** via keepDropOptions. Sum it with `prodtools/genFilterEff`.
  **Working framework at `/exp/mu2e/app/users/oksuzian/Run1B/analysis/`:**
  `gencount.py:get_total_gencount(dataset)` (resolves nts→parent mcs, sums dh.gencount);
  `normalization.py:Norm(run,mode,weeks)` — `ce_yield(rue)=npot·stopped_mu_per_pot(0.0016)·
  captures(0.609)·rue`, `weight = ce_yield/gencount` (NOT /n_nts — that inflates by
  1/acceptance, ~17× at ~6% accept); `run_analysis.py` runs the full sensitivity;
  `NORMALIZATION_NOTES.md` (SU2020 Table 1) + `Mu2e_Sensitivities_20250731.xlsx`.
  Resampling-correct by construction: gencount is the generation-stage count, physics
  yield is computed from POT independently. **Caveat:** proven for Run1B datasets;
  whether the MDC2025ar_best_v1_1 nts carry `dh.gencount` in SAM is still unverified
  (metacat showed none — check with `get_total_gencount` on an MDC2025ar dataset).
  **duty-factor gotcha (NORMALIZATION_NOTES.md):** `duty=0.323` = Mu2e's accelerator-
  CALENDAR share, NOT the data-taking beam-on fraction (~88%); "1 week of data-taking"
  = 1.82×10¹⁸ POT (3.84 kW), not the 0.323-scaled 6.69×10¹⁷.
- **RAN it 2026-06-30 — machinery verified, but need full-stats for a physics number.**
  Env recipe (CRITICAL): `source setupmu2e-art.sh` then **`pyenv ana`** (the alias — gives
  python 3.12 w/ h5py 3.14 + pyutils + uproot; `source .../bin/pyenv.sh` directly does NOT
  activate, leaves /usr/bin/python 3.9 w/o h5py); plus `setup sam_web_client` +
  `export PYTHONPATH=/exp/mu2e/app/users/oksuzian/muse_050125/prodtools:$PYTHONPATH` for
  gencount. **Verified:** `python Run1B/analysis/gencount.py nts.mu2e.DIOtail0_60MixLowTriggerable-KL.Run1B-001.root`
  → **989,500,000** (real SAM dh.gencount). `run_analysis.py --load-hists <h5> --mode Low
  --sensitivity LO HI` runs and prints `SES=rue/s_ce`, `Bkg`, `90% CL Rmue<mu_s·SES`
  (mu_s=2.303 at 0 bkg). **Caveat:** the repo's `hists_Run1B-00{6,7,8,9}.h5` are SMOKE
  (only CE+NoPrimary, 1 raw CE evt → SES 8.6e-7, unphysical); `hists_Run1B-004.h5` (has
  DIO+CE) is an OLD hdf5 schema and fails `_load_hists_hdf5` (KeyError component not found).
  A physical number needs a FULL run (`--ce --dio --bkg` over real datasets, ALL files —
  `--max-files` breaks the norm since weight=yield/full-dataset-gencount), i.e. a multi-hour
  ntuple processing job. Machinery is sound; inputs on disk are dev/smoke.
- **BIG CORRECTION (2026-06-30): the MDC2025ar_best_v1_1 datasets DO have gencount — I was
  wrong.** `get_total_gencount("nts.mu2e.CeMLeadingLogOnSpill.MDC2025ar_best_v1_1.root")`
  = **10,000,000** (10⁷ generated CE). The datasets ARE in SAM (def 219606, 200 files) with
  `dh.gencount` via parent mcs. My earlier "MDC2025ar lacks gencount / metacat-only" was
  because I checked **metacat + ROOT objects**, NOT SAM `dh.gencount`. Reconciles: CE nts
  ~4.1M reco (200×20625) / 10⁷ gen = **~41% gen→reco acceptance = the Run1A-note number**;
  reco-relative ε≈38% × 0.41 ≈ the note's ~12% absolute. **⟹ the Run1A/MDC2025ar from-data
  sensitivity IS doable from the provided ntuples** (`get_total_gencount` on SAM + `Norm`
  weight recipe). `../Run1B` was only the METHOD (a different, older SU2020 production).
- ~~**To normalize these samples — NOT simply "re-ntuple with genCountLogger" (2026-06-26; SUPERSEDED above):**~~
  metacat lineage is `nts.…MDC2025ar_best_v1_1 ← mcs.…MDC2025ar_best_v1_1.art ←
  dig.…MDC2025ap_best_v1_1.art ← sim/primary`; `_best_v1_1` is a **production tag
  carried through every stage**, not a final skim. Critically these samples are
  **RESAMPLED** (Run1A note p.5: stopped-muon pool reused to make primaries), so
  1 mcs/dig event ≠ 1 generated CE ≠ 1 POT. A `GenEventCount`/genCountLogger value
  (even recovered by re-ntupling the mcs parent) is the **resampled-event count**,
  NOT the physical normalization. The absolute normalization needs the **resampling
  factors + stops/POT** from the production bookkeeping (note Section 4: 1.5×10⁶
  simulated μ-stops, `f_stops`, `f_sim`, resample weights; Mu2e Production repo /
  DocDB 44084), not any single file's genCountLogger. So a from-data absolute
  sensitivity on resampled samples is a production-bookkeeping exercise, full stop.
- Symptom: 91.9% of CeMLeadingLog ntuple events already contain a reco e⁻ (a truly
  generated CE sample reconstructs only ~40% — the note's gen→reco acceptance). So
  `n_proc_events` is NOT the generated denominator; computing ε=N_pass/N_proc gives
  ~38% (the reco→SR factor), not the absolute 11.66%.
- **Consequence:** absolute signal efficiency, stops/POT, and especially the cosmic
  **live-time** normalization (the dominant background) are NOT in the ntuple — they
  need production-chain metadata (genCountLogger, resampling factors, CRY live-time;
  Mu2e DocDB 44084 / github.com/Mu2e/Production / parent sim datasets via metacat).
  The reco ntuple alone supports **selection efficiency + spectra shapes**, not an
  absolute sensitivity. See [[mu2e-run1-sensitivity]].
- CE selection that works on EventNtuple: tracker-entrance segment is **sid=0**;
  `trksegs.{mom,time,sid}` (depth-3 event→track→seg), `trk.{pdg,nactive,...}` (depth-2),
  `trkqual.result` (ANN score); momentum at sid=0 via `ak.firsts(mag[sid==0],axis=2)`.
- **FIELD-NAME gotcha (verified 2026-07-01):** after `Importer.import_branches()`,
  `trk`/`trkqual` subfields are **dotted** — access as `a["trk"]["trk.pdg"]`,
  `a["trk"]["trk.nactive"]`, `a["trkqual"]["trkqual.result"]` (NOT `a["trk"]["pdg"]`,
  which raises `no field 'pdg' in record with 37 fields`). But **`trksegs` fields are
  BARE**: `a["trksegs"]["sid"]`, `["time"]`, `["mom"]`. `pyvector.Vector().get_mag(ts,"mom")`
  handles the vector-record internally regardless. `ak.to_numpy` on an option-typed
  selection yields a **MaskedArray** — `np.ma.compressed()` before `np.save`
  (`MaskedArray.tofile() not implemented`).
- **Reducing-worker recipe for full-dataset processing (works, 2026-07-01):**
  `Processor.process_data(file_list_path=..., custom_worker_func=worker, max_workers=12)`
  where `worker(file_name)` builds its own `Importer(...).import_branches()` and returns a
  small 1-D np array (e.g. selected sid=0 |p|). Returns a **list** of per-file arrays
  (concatenate yourself). ~4 s/file single-thread; keeps memory tiny over 100s of files.
- **MDC2025ar_best_v1_1 SAM gencounts (2026-07-01, via `get_total_gencount`):**
  `CeMLeadingLogOnSpill`=**1.0e7** (200 files), `DIOtail95OnSpill`=**2.5e7** (500 files),
  `CosmicSignalOnSpill`=**2.5e10** (500 files). CE/DIO match the Run1A note's §4.4 gen
  counts exactly; cosmics are normalized by **livetime (1.3e7 s)** not gencount (anchor a
  from-data plot's cosmic SR integral to the note's **30** instead). See [[mu2e-run1-sensitivity]].

## Cross-links
- External: [Mu2e/pyutils](https://github.com/Mu2e/pyutils); Slack `#analysis-tools`.
- Related: [[mu2e-offline]], [[run1bana-repo]] (EdepAna lives elsewhere), building-with-muse skill.
- This project's own harvest path uses uproot/PyROOT directly, not pyutils — pyutils
  is for EventNtuple-style downstream analysis.

## Verified end-to-end run (2026-06-26)
Ran the full chain on real data, physics correct:
- `proc = Processor(tree_path="EventNtuple/ntuple", use_remote=True, location="tape")`
- `files = proc.get_file_list(defname="nts.mu2e.CeMLeadingLogOnSpill.MDC2025ar_best_v1_1.root")`
  → 200 files (SAM-resolved); `proc.process_data(file_name=files[0], branches=["trksegs"])`
  read 1 file via **xrootd from tape** = 20,625 events, 1.36M track segments. (MDC2025ar_best_v1_1
  EventNtuple datasets are readable with `location="tape", use_remote=True` — no manual prestage needed.)
- `trksegs` fields: `mom, pos, time, dmom, momerr, inbounds, gap, sid, sindex`.
- Track-seg |p| peaked at **103–105 MeV/c** (mean 102.2) = the CE signal (CeMLeadingLog = μ→e ~105 MeV). ✓
- **Gotchas:** `trksegs.mom` is a **nested ROOT vector record** (`mom.fields` is a single
  `fCoordinates`-style entry, NOT bare `x/y/z`) — indexing `mom["x"]` raises FieldNotFoundError;
  use **`pyutils.pyvector.Vector().get_mag(arr, "mom")`** which returns an **already-flat**
  numpy-able array (a second `ak.flatten` raises `AxisError: axis=1 exceeds depth 1`). Use
  `ak.ravel`/`ak.to_numpy` to finish.
