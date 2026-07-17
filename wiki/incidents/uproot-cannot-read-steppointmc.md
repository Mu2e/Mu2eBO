---
type: incident
title: uproot cannot read mu2e::StepPointMC
description: 'uproot raises `NotImplementedError: memberwise serialization of AsVector(mu2e::StepPointMC)`;
  use PyROOT under `muse setup` (loads libmu2e_MCDataProducts_dict)'
status: resolved
status_note: (2026-06-07; PyROOT used in harvester)
timestamp: '2026-06-07'
---

# uproot cannot read mu2e::StepPointMC

## Summary
uproot raises `NotImplementedError: memberwise serialization of
AsVector(mu2e::StepPointMC)` when asked to read any branch of type
`std::vector<mu2e::StepPointMC>` from an art `.art` file produced by
ROOT 6.32.06. uproot lacks an interpretation for memberwise-streamed
custom-class collections — the dictionary lives in libmu2e_MCDataProducts
and is only known to ROOT's TClass machinery.

## Key facts
- Reproduction:
  ```python
  import uproot
  f = uproot.open("ptmc.art")
  e = f["Events"]
  b = e["mu2e::StepPointMCs_g4run_ProductionTargetPlate17_POT."
        "/mu2e::StepPointMCs_g4run_ProductionTargetPlate17_POT.obj"]
  b.array()  # NotImplementedError
  ```
- Affects any harvester trying to bypass ROOT for StepPointMC, SimParticle,
  StrawGasStep, or any other Mu2e MCDataProducts collection.
- **Solution**: use PyROOT under `muse setup` (loads
  libmu2e_MCDataProducts_dict via ROOT autoloader). Reference harvester:
  `/exp/mu2e/app/users/oksuzian/dpa_smoke/make_dpa_plot.py`.
- PyROOT loop pattern that works:
  ```python
  events = f.Get("Events")
  events.SetBranchStatus("*", 0)
  events.SetBranchStatus(branch_name + "*", 1)
  for ev in range(events.GetEntries()):
      events.GetEntry(ev)
      wrapper = getattr(events, branch_name.rstrip("."))
      for k in range(wrapper.size()):
          sp = wrapper.at(k)
          total_edep += sp.totalEDep()
  ```
  Per-branch loop avoids loading all 35 collections at once.
- **Alternative: gallery.Event (used by the bo-ipa StrawGasStep harvest,
  2026-06-19).** `import ROOT; ROOT.gSystem.Load("libgallery")`; build a
  `ROOT.vector("string")` of files, `ev = ROOT.gallery.Event(fv)`, then loop
  `while not ev.atEnd(): ... ev.next()`. **GOTCHA: the templated `getValidHandle`
  MUST use the `[Type]` subscript idiom** — `ev.getValidHandle(<type-object>)`
  fails with `TypeError: Template method resolution failed`. Correct:
  ```python
  getH = ev.getValidHandle[ROOT.std.vector("mu2e::StrawGasStep")]
  for ...:
      h = getH(ROOT.art.InputTag("compressDetStepMCs"))
      for s in h.product(): total += s.ionizingEdep()
  ```
  InputTag is label[:instance[:process]]; bare label matches. Working ref:
  `pipeline.py:_TRK_EDEP_EXTRACT_SCRIPT` ([bo-ipa](/projects/bo-ipa.md)). gallery is cleaner than the
  SetBranchStatus loop when you have a known InputTag.
- **Why not just write a custom analyzer?** Two paths exist; we chose
  PyROOT for the smoke test because it avoids a second muse rebuild.
  Long-term, a `ProductionTargetEdepHist_module.cc` writing a TH1D via
  TFileService would drop the PyROOT dependency. See
  [steppointmcdumper-no-edep](/incidents/steppointmcdumper-no-edep.md).
- The harvester needs `source mu2e-art.sh + muse setup` in the same
  shell because spack-managed ROOT lives only inside the spack env.
  The project's `.venv-botorch` does not have ROOT bindings.

## Cross-links
- Related: [steppointmcdumper-no-edep](/incidents/steppointmcdumper-no-edep.md),
  [art-instance-name-no-underscore](/incidents/art-instance-name-no-underscore.md), [dpa-scoring](/concepts/dpa-scoring.md)
- External: [uproot custom-class support](https://uproot.readthedocs.io/en/latest/basic.html#reading-a-tbranch-as-an-array)

## Open questions / TODO
- Decide whether to ship PyROOT-based harvest or write the TH1D
  analyzer. For closed-loop pot_only at scale, the analyzer wins
  (avoids 35× PyROOT loops per cluster).
