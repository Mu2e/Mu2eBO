# ReadVirtualDetector savePDG takes symbolic names, not integers

**Type:** incident
**Status:** resolved
**Updated:** 2026-06-07

## Summary
pt001 cluster 28338433 (bo-prodtarget Step A pot_only) had all 100/100 jobs
die identically at G4 module construction in 5.6 s with art exit 66:

```
StdLibException: ReadVirtualDetector:readVD@Construction
PDGCode invalid enum name : -13
```

Root cause: `pipeline_templates/pot_only/template.fcl` set
`physics.analyzers.readVD.savePDG : [ -13, 13 ]` (integers). The module's
parameter type is `vector<string>` of **symbolic PDG names**, not raw PDG
integers. The constructor calls `PDGCode("-13")` which has no enum entry
named `-13` and throws.

## Key facts
- **Source of truth**:
  `Offline/Analyses/src/ReadVirtualDetector_module.cc:252` parses
  `savePDG` as `Vstr` (`std::vector<std::string>`), not `vector<int>`.
- **Line 256**: `PDGCode::enum_type id = PDGCode(pdg_names[i]);` — string
  constructor that does an enum-name lookup. `-13` is not a valid enum NAME
  even though it IS a valid PDG integer.
- **Same trap on `tvd_drop_names`** (line 267) — same fix pattern applies.
- **Fix for pot_only template**: change `savePDG : [ -13, 13 ]` to
  `savePDG : [ "mu_minus", "mu_plus" ]`. Symbolic names live in
  `Offline/DataProducts/inc/PDGCode.hh` enum (mu_minus=13, mu_plus=-13, e_minus=11,
  proton=2212, neutron=2112, etc.).
- **Failure signature in worker log**: `Art has completed and will exit with
  status 66.` after only `[MT]` Geant4 banner + the
  `ReadVirtualDetector: save following particle types in the ntuple:` line
  (which prints BEFORE the parse, so it looks like the module started
  successfully — it didn't).
- **Why the pot_only stage's poll saw "queue drained but 0/100 settled":**
  jobs took 5.6 s wall, were marked Done by jobsub, but the outstage dirs
  stayed in hash-suffix form (`00000.109f95e4`) because the stage-out
  wrapper renames bare-form only on successful art-RC. With art rc=66 the
  rename never fires; pipeline.py's poll convergence-gate (which checks for
  bare-form `00000`) correctly classified all 100 as failures.
- **Cluster-file write happened anyway** (jobsub_submit succeeded — the FCL
  parses fine at submit; the failure is at G4 module construction inside
  the worker). So `<state>/pot_only_cluster.txt` is valid; you just need to
  resubmit with `--force` after fixing the template.

## Cross-links
- Related: [[fcl-unicode-parse-error]] (other "everyone dies identically at
  module construction" incident — same failure pattern, different cause),
  [[bo-prodtarget]], [[pipeline]]
- Source files:
  - `pipeline_templates/pot_only/template.fcl:14` (the bad line)
  - `Offline/Analyses/src/ReadVirtualDetector_module.cc:252-256` (the parser)
  - `Offline/DataProducts/inc/PDGCode.hh` (canonical enum names)

## Open questions / TODO
- Resubmit pt001 with fixed template (`["mu_minus","mu_plus"]`) before
  proceeding to Step A.4 / Step B of bo-prodtarget #16.
- Consider adding a pre-submit FCL lint that catches integer-where-string
  in `savePDG` (and other Vstr enum fields) — would have caught this at
  preflight time. Low priority — symptom is unambiguous in worker logs.
