# prodtools: feature request — chained entries (`input_from` + `jobwait --quorum`)

**Repo:** `oksuzian/prodtools` (branch `code-tarball`; shipped as
`/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0`)
**Files in scope:** `utils/submit.py` (`submit_entry`, `check_inputs` gate),
`utils/jobwait.py`, `utils/json2jobdef.py` (entry schema),
`utils/submission_ledger.py`, `utils/chain_emit.py` (existing tier-based chaining)
**Requested:** 2026-08-20, from the autoresearch (Mu2eBO) closed-loop path
**Kind:** feature, not a defect. Read after
`prodtools-check-inputs-dir-inloc.md` and
`prodtools-jobwait-empty-history-unknown-rc.md` — both of those are symptoms
of the seam this proposal would move inside prodtools.

---

## Summary

Ask: let one `json2jobdef`-style entry declare that its inputs are the
outputs of another entry in the same map, and let `jobwait` accept a quorum
so the downstream entry can start when "enough" upstream jobs have landed.
Concretely:

```json
{"desc": "Run1A_CeEndpoint_X", "fcl": "Production/JobConfig/primary/CeEndpoint.fcl",
 "input_from": "Run1A_MuBeam_X", "input_glob": "dts.*.MuBeamCat.*.art",
 "quorum": 0.9, ...}
```

```
jobwait --jobdef ... --cluster ... --quorum 0.9 --json wait.json
```

With those two pieces, a multi-stage chain (mubeam → mustops → CE; for
Mu2eBO today, `mubeam → mustops_ce` plus an independent `elebeam_flash`) is
a single map submitted once, with prodtools resolving the hop. Today the
caller resolves it by hand, outside prodtools, and the two open briefs above
are bugs at exactly that hand-made seam.

## What the caller does today at the hop

autoresearch `core/pipeline.py` (branch `json-modes`):

1. `jobwait` writes `state/<stage>/wait.json`.
2. `cmd_poll` (`core/pipeline.py:934`) applies the acceptance policy
   prodtools does not have: `ok == 0` → fail; `ok < njobs*quorum` → warn and
   proceed; harvest divides by the true ok count.
3. `cmd_list_outputs` (`:962`) turns `wait.json` + the stage's `output_glob`
   into `state/mubeam_outputs.txt` (absolute /pnfs or local paths).
4. `stage_hardlink_farm` (`:530`) hard-links those files into one /pnfs dir
   (`input_data` is basename-keyed and `inloc` assumes one dir; hard links,
   not symlinks, because xrootd doors do not follow /pnfs symlinks).
   `local_input_farm` (`:548`) is the same for `runlocal`, with an EXDEV copy
   fallback.
5. `cmd_submit` (`:810`) renders the consuming entry with
   `inloc = dir:<farm>` and `input_data = {basename: 1}` and calls
   `submit_entry`. This `dir:` inloc is what `check_inputs` rejects
   (`prodtools-check-inputs-dir-inloc.md`).

All of that exists to express one sentence: *"this entry's inputs are the
outputs of that entry."*

## Why prodtools' existing chaining does not cover it

`utils/chain_emit.py` chains dts→digi→reco→ntuple by **SAM dataset-tier
discovery** (`latestDatasets --emit`): the downstream stage finds its input
as a declared dataset. Mu2eBO outputs are per-configuration, land on
`outloc: outstage`, and are never SAM-declared (hundreds of tiny one-off
datasets per campaign would be the alternative). Nothing in prodtools can
see them as inputs except through a `dir:` inloc — the path `check_inputs`
currently blocks.

`utils/submissions.py`'s recovery loop is the opposite acceptance policy
("resubmit missing indices until complete"). For an optimization loop, time
beats completeness: a 90% cluster is a usable point, and the partial-ness is
already handled downstream by dividing by the true ok count. That is why
quorum has to be a caller-chosen flag, not a fixed behaviour.

## Proposed shape

1. **Entry field `input_from: <desc of another entry>`** (+ `input_glob`).
   At submit time of the downstream entry, `submit` resolves the upstream
   entry's cluster through the ledger (`submission_ledger.py` already keys
   rows by cnf/desc), reads its `wait.json`, applies `input_glob`, builds the
   `input_data` map (one file per job unless a merge factor is given) and
   stages the files into a single dir prodtools owns. Hard links on /pnfs;
   link-or-copy locally. `inloc` becomes `dir:<that dir>`, which means
   `check_inputs` must accept `dir:` for prodtools-staged dirs — this is the
   fix `prodtools-check-inputs-dir-inloc.md` asks for anyway.
2. **`jobwait --quorum F`**: return success (rc 0) once `ok >= ceil(njobs*F)`
   and the cluster is drained (or, optionally, as soon as the quorum is
   reached, with `--early`). Keep `ok == 0` a hard failure. Write the
   shortfall into `wait.json` so the caller can warn. Independent of (1) and
   useful on its own.
3. **Map-level ordering**: `submit` on a map with `input_from` edges submits
   sources first, waits (via `jobwait` with the entry's `quorum`), then
   submits dependents; entries without edges go in parallel. This is what
   turns three submits into one.

The jobwait empty-history defect (`prodtools-jobwait-empty-history-unknown-rc.md`)
becomes load-bearing under (3): a chain must not stall on a schedd that
returns zero history rows, so that fix lands first.

## What it would save on the Mu2eBO side (measured 2026-08-20)

| Surface | Today | After |
|---|---|---|
| `core/pipeline.py` hop code (`_input_stage_for`, both farms, staging branches in `cmd_submit` grid+local, `cmd_poll` quorum, `cmd_list_outputs`, local marker/stamp half) | ~160 of 1283 lines | deleted |
| `graph/nodes.py` + `graph/pipeline_io.py` per-stage nodes, `route_after_stage`, `read_stage_status`, `PRESUBMIT_AFTER` overlap hack | ~40 lines, 3 stage nodes | 1 chain node |
| Per-stage state files `<stage>_outputs.txt`, `<stage>_cluster.txt`, `.local` marker | 92 references across code+tests | 1 chain id |
| Tests touching the hop (`test_pipeline_verbs.py` 37 refs, `test_audit_fixes.py`, `test_prodtools_exec.py`) | ~50 assertions | rewritten, not deleted |
| Incident pages about inter-stage plumbing (stage-out lag, rename race, poll deadlock, empty outputs.txt, sourced-env across stages) | 28 of 42 pipeline-related | class relocates to prodtools, fixed once for all users |

Net for Mu2eBO: ~200 lines removed, ~50 rewritten, two of the five
barrier/resume truth-sources gone. Wall-clock unchanged (same jobs, same
waits). Prodtools cost: roughly 300–400 lines plus tests across the three
items above, and one migration round with both paths live.

Honest framing: on code volume this is break-even across the two repos.
The case for it is (a) the `dir:` inloc and jobwait-history bugs stop being
autoresearch-specific workarounds, (b) any prodtools user gets
one-map multi-stage submission, and (c) the hop's failure modes get one
owner instead of being re-discovered per caller.

## Not in scope

- Per-config code tarball (geom overlay + extras FCL) stays with the caller.
- Harvest/scan/evaluate stay with the caller.
- SAM-declaring per-config outputs — rejected as the alternative (dataset
  explosion); noted so it is not re-proposed.

## Pointers

- autoresearch hop code: `core/pipeline.py:523-560` (farms),
  `:810-931` (`cmd_submit` staging branches), `:934-975` (`cmd_poll`,
  `cmd_list_outputs`); `core/prodtools_exec.py:306` (`outputs_from_wait`).
- Entry consumed today: `stage_entries/mustops_ce.json` (`inloc: disk` in
  the checked-in file; `dir:` is substituted at submit).
- Wiki: `wiki/drivers/pipeline.md`,
  `wiki/concepts/architecture-friction-survey-2026-07.md` (the five
  truth-sources).
